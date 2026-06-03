#!/usr/bin/env python3
"""
EODHD All World EOD snapshot downloader with bounded concurrency.

Scope of this implementation
----------------------------
This implements recommendation B only: bounded concurrent per-symbol downloads.
It does not implement Parquet compaction, bulk daily updates, database loading,
or a redesigned architecture.

Core datasets covered for the EOD Historical Data — All World plan:
- exchange metadata
- active and optionally delisted symbol lists
- historical daily EOD OHLCV + adjusted_close
- historical dividends
- historical splits

Designed placement inside financial_db/findb:
    data_fetchers/eodhd_all_world_snapshot.py

Dependencies:
    uv add requests pandas pyarrow

First full bootstrap, paid plan:
    uv run python -m data_fetchers.eodhd_all_world_snapshot \
      --root data/external/eodhd \
      --confirm-full-plan-download \
      --include-delisted \
      --download-prices \
      --download-dividends \
      --download-splits \
      --refresh-after-days -1 \
      --max-requests-per-minute 900 \
      --max-api-calls-per-day 95000 \
      --concurrency 20

Weekly refresh after initial bootstrap:
    uv run python -m data_fetchers.eodhd_all_world_snapshot \
      --root data/external/eodhd \
      --confirm-full-plan-download \
      --include-delisted \
      --download-prices \
      --download-dividends \
      --download-splits \
      --refresh-after-days 7 \
      --max-requests-per-minute 900 \
      --max-api-calls-per-day 95000 \
      --concurrency 20
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import email.utils
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

from db_utils.config import get_eodhd_archive_root, load_project_environment

from .settings import DEFAULT_CONFIG_PATH, EodhdConfig, load_eodhd_config

UTC = dt.timezone.utc
FULL_ARCHIVE_SCOPE_OPTIONS = {
    "--confirm-full-plan-download",
    "--exchanges",
    "--exclude-virtual-categories",
    "--type-filters",
    "--include-delisted",
    "--reuse-universe",
    "--metadata-only",
    "--download-prices",
    "--download-dividends",
    "--download-splits",
    "--corporate-actions-scope",
    "--max-symbols",
}

TOKEN_ENV_NAMES = ["EODHD_API_TOKEN", "EODHD_TOKEN", "EOD_HISTORICAL_DATA_API_TOKEN"]


class EntitlementDenied(RuntimeError):
    """Raised when a token is not entitled to an endpoint/category."""


class NonRetryableAPIError(RuntimeError):
    """Raised for deterministic API errors that should not be retried."""


class QuotaExceeded(RuntimeError):
    """Raised when local/provider API quota is exhausted.

    Callers should persist state, stop scheduling new work, and allow a later run
    to resume using the same state DB.
    """


def redact_sensitive(value: Any) -> str:
    s = str(value)
    s = re.sub(r"(?i)(api_token=)[^&\s]+", r"\1<REDACTED>", s)
    s = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1<REDACTED>", s)
    s = re.sub(r"(?i)(token=)[^&\s]+", r"\1<REDACTED>", s)
    return s


def looks_like_quota_error(value: Any) -> bool:
    t = str(value).lower()
    patterns = [
        "quota",
        "rate limit",
        "rate-limit",
        "too many requests",
        "api call limit",
        "api calls limit",
        "calls limit",
        "call limit",
        "daily limit",
        "request limit",
        "requests limit",
        "usage limit",
        "limit reached",
        "limit exceeded",
        "exceeded your limit",
        "maximum number of requests",
        "you have exceeded",
        "no api calls left",
        "out of api calls",
    ]
    return any(p in t for p in patterns)


def looks_like_entitlement_error(value: Any) -> bool:
    t = str(value).lower()
    patterns = [
        "not entitled",
        "not authorized",
        "not authorised",
        "forbidden",
        "access denied",
        "permission",
        "subscription",
        "subscribe",
        "upgrade",
        "paid account",
        "package",
        "plan",
        "api key associated",
    ]
    return any(p in t for p in patterns)


def resolve_api_token(cli_token: Optional[str], env_file: Optional[Path]) -> tuple[Optional[str], str]:
    load_project_environment(env_file)
    if cli_token:
        return cli_token, "--api-token"

    for name in TOKEN_ENV_NAMES:
        val = os.getenv(name)
        if val:
            return val, f"env:{name}"
    return None, "missing"


@dataclasses.dataclass(frozen=True)
class ApiLimits:
    max_requests_per_minute: int = 900
    max_api_calls_per_day: int = 95_000
    min_seconds_between_requests: float = 0.05
    sleep_on_daily_limit: bool = False


class SQLiteState:
    def __init__(self, path: Path, *, root: Optional[Path] = None) -> None:
        self.path = path
        self.root = root
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    @staticmethod
    def utc_now() -> str:
        return dt.datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def utc_today() -> str:
        return dt.datetime.now(UTC).date().isoformat()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def _init_schema(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_usage (
                    utc_date TEXT PRIMARY KEY,
                    api_calls INTEGER NOT NULL DEFAULT 0,
                    requests INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dataset_download_state (
                    dataset TEXT NOT NULL,
                    exchange_code TEXT NOT NULL,
                    full_symbol TEXT NOT NULL,
                    is_delisted INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    rows INTEGER,
                    bytes_written INTEGER,
                    sha256 TEXT,
                    file_path TEXT,
                    last_error TEXT,
                    retrieved_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset, full_symbol, is_delisted)
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT
                );
                """
            )
            # Migrations for older state DBs.
            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(dataset_download_state)").fetchall()}
            if "retrieved_at" not in cols:
                self.conn.execute("ALTER TABLE dataset_download_state ADD COLUMN retrieved_at TEXT")
            self.conn.commit()

    def get_today_usage(self) -> tuple[int, int]:
        with self.lock:
            row = self.conn.execute(
                "SELECT api_calls, requests FROM api_usage WHERE utc_date = ?",
                (self.utc_today(),),
            ).fetchone()
            if row is None:
                return 0, 0
            return int(row[0]), int(row[1])

    def add_usage(self, api_calls: int, requests_count: int = 1) -> None:
        with self.lock:
            today = self.utc_today()
            now = self.utc_now()
            self.conn.execute(
                """
                INSERT INTO api_usage (utc_date, api_calls, requests, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(utc_date) DO UPDATE SET
                    api_calls = api_usage.api_calls + excluded.api_calls,
                    requests = api_usage.requests + excluded.requests,
                    updated_at = excluded.updated_at
                """,
                (today, int(api_calls), int(requests_count), now),
            )
            self.conn.commit()

    def mark_dataset(
        self,
        *,
        dataset: str,
        exchange_code: str,
        full_symbol: str,
        is_delisted: bool,
        status: str,
        rows: Optional[int] = None,
        bytes_written: Optional[int] = None,
        sha256: Optional[str] = None,
        file_path: Optional[str] = None,
        error: Optional[str] = None,
        retrieved_at: Optional[str] = None,
    ) -> None:
        if error is not None:
            error = redact_sensitive(error)
        now = self.utc_now()
        if retrieved_at is None and status in {"done", "empty"}:
            retrieved_at = now
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO dataset_download_state
                    (dataset, exchange_code, full_symbol, is_delisted, status, attempts,
                     rows, bytes_written, sha256, file_path, last_error, retrieved_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, full_symbol, is_delisted) DO UPDATE SET
                    exchange_code = excluded.exchange_code,
                    status = excluded.status,
                    attempts = dataset_download_state.attempts + 1,
                    rows = excluded.rows,
                    bytes_written = excluded.bytes_written,
                    sha256 = excluded.sha256,
                    file_path = excluded.file_path,
                    last_error = excluded.last_error,
                    retrieved_at = excluded.retrieved_at,
                    updated_at = excluded.updated_at
                """,
                (
                    dataset,
                    exchange_code,
                    full_symbol,
                    1 if is_delisted else 0,
                    status,
                    rows,
                    bytes_written,
                    sha256,
                    file_path,
                    error,
                    retrieved_at,
                    now,
                ),
            )
            self.conn.commit()

    def log_event(self, level: str, message: str, payload: Optional[dict[str, Any]] = None) -> None:
        redacted_payload = None
        if payload is not None:
            redacted_payload = json.loads(redact_sensitive(json.dumps(payload, default=str, sort_keys=True)))
        with self.lock:
            self.conn.execute(
                "INSERT INTO run_events(event_time, level, message, payload_json) VALUES (?, ?, ?, ?)",
                (self.utc_now(), level, redact_sensitive(message), json.dumps(redacted_payload, sort_keys=True) if redacted_payload else None),
            )
            self.conn.commit()

    def dataset_counts(self) -> pd.DataFrame:
        with self.lock:
            return pd.read_sql_query(
                """
                SELECT dataset, status, COUNT(*) AS n
                FROM dataset_download_state
                GROUP BY dataset, status
                ORDER BY dataset, status
                """,
                self.conn,
            )

    def get_dataset_record(self, dataset: str, full_symbol: str, is_delisted: bool) -> Optional[dict[str, Any]]:
        with self.lock:
            row = self.conn.execute(
                """
                SELECT status, file_path, retrieved_at, updated_at
                FROM dataset_download_state
                WHERE dataset = ? AND full_symbol = ? AND is_delisted = ?
                """,
                (dataset, full_symbol, 1 if is_delisted else 0),
            ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "file_path": row[1], "retrieved_at": row[2], "updated_at": row[3]}

    @staticmethod
    def _parse_ts(value: Optional[str]) -> Optional[dt.datetime]:
        if not value:
            return None
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def completion_state(
        self,
        dataset: str,
        full_symbol: str,
        is_delisted: bool,
        refresh_after_days: Optional[int],
    ) -> str:
        rec = self.get_dataset_record(dataset, full_symbol, is_delisted)
        if rec is None:
            return "missing"
        status = str(rec.get("status") or "")
        if status not in {"done", "empty"}:
            return "incomplete"
        file_path = self.resolve_file_path(rec.get("file_path"))
        if status == "done" and file_path and not file_path.exists():
            return "missing_file"
        if refresh_after_days is None or refresh_after_days < 0:
            return "fresh_complete"
        retrieved = self._parse_ts(rec.get("retrieved_at") or rec.get("updated_at"))
        if retrieved is None:
            return "stale_complete"
        if dt.datetime.now(UTC) - retrieved > dt.timedelta(days=refresh_after_days):
            return "stale_complete"
        return "fresh_complete"

    def is_done(
        self,
        dataset: str,
        full_symbol: str,
        is_delisted: bool,
        refresh_after_days: Optional[int],
    ) -> bool:
        return self.completion_state(dataset, full_symbol, is_delisted, refresh_after_days) == "fresh_complete"

    def relative_file_path(self, path: Path) -> str:
        if self.root is None:
            return str(path)
        return str(path.resolve().relative_to(self.root.resolve()))

    def resolve_file_path(self, value: Optional[str]) -> Optional[Path]:
        if not value:
            return None
        path = Path(value)
        if path.is_absolute() or self.root is None:
            return path
        return self.root / path


class RateLimitedEODHDClient:
    def __init__(
        self,
        token: str,
        state: SQLiteState,
        limits: ApiLimits,
        timeout: int,
        pool_size: int,
        *,
        api_base: str,
        symbol_change_start_date: str,
        default_provider_cooldown_seconds: float,
        max_provider_cooldown_seconds: float,
    ) -> None:
        self.token = token
        self.state = state
        self.limits = limits
        self.timeout = timeout
        self.pool_size = pool_size
        self.api_base = api_base
        self.symbol_change_start_date = symbol_change_start_date
        self.default_provider_cooldown_seconds = default_provider_cooldown_seconds
        self.max_provider_cooldown_seconds = max_provider_cooldown_seconds
        self.rate_lock = threading.RLock()
        self._request_timestamps: list[float] = []
        self._last_request_at = 0.0
        self._provider_cooldown_until = 0.0
        self._local = threading.local()

    def session(self) -> requests.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = requests.Session()
            adapter = HTTPAdapter(pool_connections=self.pool_size, pool_maxsize=self.pool_size, max_retries=0)
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
            sess.headers.update({"User-Agent": "financial-db-eodhd-concurrent/1.0"})
            self._local.session = sess
        return sess

    @staticmethod
    def _sleep_until_next_utc_day() -> None:
        now = dt.datetime.now(UTC)
        tomorrow = now.date() + dt.timedelta(days=1)
        wake = dt.datetime.combine(tomorrow, dt.time(hour=0, minute=5), tzinfo=UTC)
        time.sleep(max(60.0, (wake - now).total_seconds()))

    def _retry_after_seconds(self, value: Optional[str]) -> float:
        if value:
            with contextlib.suppress(ValueError):
                return min(self.max_provider_cooldown_seconds, max(0.0, float(value)))
            with contextlib.suppress(TypeError, ValueError, OverflowError):
                retry_at = email.utils.parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at - dt.datetime.now(UTC)).total_seconds()
                return min(self.max_provider_cooldown_seconds, max(0.0, delay))
        return self.default_provider_cooldown_seconds

    def schedule_provider_cooldown(self, retry_after: Optional[str] = None) -> float:
        delay = self._retry_after_seconds(retry_after)
        with self.rate_lock:
            self._provider_cooldown_until = max(self._provider_cooldown_until, time.monotonic() + delay)
        return delay

    def acquire_request_slot(self, api_cost: int) -> None:
        with self.rate_lock:
            calls_today, _ = self.state.get_today_usage()
            if calls_today + api_cost > self.limits.max_api_calls_per_day:
                msg = f"Daily API-call budget would be exceeded: {calls_today}+{api_cost}>{self.limits.max_api_calls_per_day}"
                if self.limits.sleep_on_daily_limit:
                    logging.warning("%s; sleeping until next UTC day", msg)
                    self.state.log_event("WARNING", "local_daily_quota_sleep", {"calls_today": calls_today, "api_cost": api_cost})
                    self._sleep_until_next_utc_day()
                else:
                    self.state.log_event("WARNING", "local_daily_quota_exceeded", {"calls_today": calls_today, "api_cost": api_cost})
                    raise QuotaExceeded(msg)

            now = time.monotonic()
            cooldown_remaining = self._provider_cooldown_until - now
            if cooldown_remaining > 0:
                logging.debug("Provider cooldown active; sleeping %.2fs", cooldown_remaining)
                time.sleep(cooldown_remaining)
                now = time.monotonic()

            cutoff = now - 60.0
            self._request_timestamps = [t for t in self._request_timestamps if t >= cutoff]
            if len(self._request_timestamps) >= self.limits.max_requests_per_minute:
                sleep_for = 60.0 - (now - self._request_timestamps[0]) + 0.25
                logging.debug("Minute request budget reached; sleeping %.2fs", max(0.1, sleep_for))
                time.sleep(max(0.1, sleep_for))
                now = time.monotonic()
                cutoff = now - 60.0
                self._request_timestamps = [t for t in self._request_timestamps if t >= cutoff]

            elapsed = now - self._last_request_at
            if elapsed < self.limits.min_seconds_between_requests:
                time.sleep(self.limits.min_seconds_between_requests - elapsed)
                now = time.monotonic()

            # Reserve locally before the HTTP call to make concurrent workers obey
            # the daily/minute budget. This is intentionally conservative.
            self._request_timestamps.append(now)
            self._last_request_at = now
            self.state.add_usage(api_cost, 1)

    def get_json(self, path: str, *, params: Optional[dict[str, Any]] = None, api_cost: int = 1, max_attempts: int = 5) -> Any:
        params = dict(params or {})
        params["api_token"] = self.token
        params["fmt"] = "json"
        url = f"{self.api_base}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            self.acquire_request_slot(api_cost)
            try:
                response = self.session().get(url, params=params, timeout=self.timeout)
                safe_url = redact_sensitive(response.url)
                body_preview = redact_sensitive(response.text[:500])

                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    with contextlib.suppress(ValueError):
                        if int(remaining) <= 2:
                            cooldown_s = self.schedule_provider_cooldown(response.headers.get("Retry-After"))
                            logging.info("Provider minute remaining near zero; scheduling shared %.2fs cooldown", cooldown_s)

                if response.status_code == 429:
                    cooldown_s = self.schedule_provider_cooldown(response.headers.get("Retry-After"))
                    payload = {"status_code": 429, "url": safe_url, "body_preview": body_preview, "attempt": attempt, "max_attempts": max_attempts, "cooldown_seconds": cooldown_s}
                    if attempt == max_attempts:
                        self.state.log_event("WARNING", "provider_quota_or_rate_limit", payload)
                        raise QuotaExceeded(f"HTTP 429 provider quota/rate limit after {max_attempts} attempts for {safe_url}: {body_preview!r}")
                    self.state.log_event("WARNING", "provider_rate_limit_retry", payload)
                    logging.warning("HTTP 429 for %s; scheduling shared %.2fs cooldown before retry %s/%s", safe_url, cooldown_s, attempt + 1, max_attempts)
                    continue
                if response.status_code in {401, 402, 403}:
                    if looks_like_quota_error(body_preview):
                        self.state.log_event("WARNING", "provider_quota_exceeded", {"status_code": response.status_code, "url": safe_url})
                        raise QuotaExceeded(f"HTTP {response.status_code} provider quota for {safe_url}: {body_preview!r}")
                    raise EntitlementDenied(f"HTTP {response.status_code} for {safe_url}: {body_preview!r}")
                if response.status_code in {400, 404}:
                    raise NonRetryableAPIError(f"HTTP {response.status_code} for {safe_url}: {body_preview!r}")
                if response.status_code in {408, 500, 502, 503, 504}:
                    if attempt == max_attempts:
                        raise RuntimeError(f"HTTP {response.status_code} for {safe_url}: {body_preview!r}")
                    wait_s = min(120, 2**attempt)
                    logging.warning("HTTP %s for %s; retrying in %ss", response.status_code, safe_url, wait_s)
                    time.sleep(wait_s)
                    continue
                if response.status_code >= 400:
                    raise NonRetryableAPIError(f"HTTP {response.status_code} for {safe_url}: {body_preview!r}")

                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"Non-JSON response from {safe_url}: {body_preview!r}") from exc

                if isinstance(data, dict):
                    payload = redact_sensitive(json.dumps(data, default=str))
                    lowered = payload.lower()
                    if any(k in data for k in ["error", "Error", "message", "Message"]):
                        if looks_like_quota_error(lowered):
                            raise QuotaExceeded(f"Provider quota/error payload from {redact_sensitive(url)}: {payload[:500]}")
                        if looks_like_entitlement_error(lowered):
                            raise EntitlementDenied(f"Provider entitlement/error payload from {redact_sensitive(url)}: {payload[:500]}")
                        if "not found" not in lowered and "no data" not in lowered:
                            raise RuntimeError(f"Provider returned error payload from {redact_sensitive(url)}: {payload[:500]}")
                return data

            except (QuotaExceeded, EntitlementDenied, NonRetryableAPIError):
                raise
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                if attempt == max_attempts:
                    break
                wait_s = min(120, 2**attempt)
                logging.warning("Request failed attempt %s/%s: %s; sleeping %ss", attempt, max_attempts, redact_sensitive(exc), wait_s)
                time.sleep(wait_s)

        raise RuntimeError(f"Failed GET {redact_sensitive(url)} after {max_attempts} attempts: {redact_sensitive(last_exc)}")

    def get_exchanges(self) -> list[dict[str, Any]]:
        data = self.get_json("exchanges-list/", api_cost=1)
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected exchanges-list payload: {type(data)}")
        return [dict(x) for x in data]

    def get_exchange_symbols(self, exchange_code: str, *, security_type: Optional[str], delisted: bool) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if security_type:
            params["type"] = security_type
        if delisted:
            params["delisted"] = 1
        data = self.get_json(f"exchange-symbol-list/{exchange_code}", params=params, api_cost=1)
        return normalize_list_or_empty(data, f"symbols:{exchange_code}", "symbol-list")

    def get_eod_history(self, full_symbol: str, start: Optional[str], end: Optional[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"period": "d"}
        if start:
            params["from"] = start
        if end:
            params["to"] = end
        data = self.get_json(f"eod/{full_symbol}", params=params, api_cost=1)
        return normalize_list_or_empty(data, full_symbol, "eod_daily")

    def get_dividends(self, full_symbol: str, start: Optional[str], end: Optional[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if start:
            params["from"] = start
        if end:
            params["to"] = end
        data = self.get_json(f"div/{full_symbol}", params=params, api_cost=1)
        return normalize_list_or_empty(data, full_symbol, "dividends")

    def get_splits(self, full_symbol: str, start: Optional[str], end: Optional[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if start:
            params["from"] = start
        if end:
            params["to"] = end
        data = self.get_json(f"splits/{full_symbol}", params=params, api_cost=1)
        return normalize_list_or_empty(data, full_symbol, "splits")

    def get_symbol_changes(self) -> list[dict[str, Any]]:
        data = self.get_json("symbol-change-history", params={"from": self.symbol_change_start_date}, api_cost=5)
        return normalize_list_or_empty(data, "symbol-change-history", "symbol-changes")


def normalize_list_or_empty(data: Any, symbol: str, label: str) -> list[dict[str, Any]]:
    if data is None or data == {}:
        return []
    if isinstance(data, dict):
        text = json.dumps(data, default=str)[:500]
        if "no data" in text.lower() or "not found" in text.lower():
            return []
        for key in ["data", "results", "items"]:
            if isinstance(data.get(key), list):
                return [dict(x) if isinstance(x, dict) else {"value": x} for x in data[key]]
        return [{"payload": data}]
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected {label} payload for {symbol}: {type(data)} {str(data)[:300]}")
    return [dict(x) if isinstance(x, dict) else {"value": x} for x in data]


def camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.replace(" ", "_").replace("-", "_").lower()


def provider_payload_json(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))


def rows_with_provider_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "provider_payload_json": provider_payload_json(row)} for row in rows]


def sanitize_path_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", str(value))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=path.name, suffix=".tmp", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        df.to_parquet(tmp_path, index=False, compression="zstd")
        sha = sha256_file(tmp_path)
        tmp_path.replace(path)
        return path.stat().st_size, sha
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def atomic_write_json_gz(obj: Any, path: Path) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=path.name, suffix=".tmp", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        sha = sha256_file(tmp_path)
        tmp_path.replace(path)
        return path.stat().st_size, sha
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def normalize_exchange_df(exchanges: list[dict[str, Any]], snapshot_date: str) -> pd.DataFrame:
    df = pd.DataFrame(rows_with_provider_payload(exchanges))
    if df.empty:
        return df
    df.columns = [camel_to_snake(c) for c in df.columns]
    df["snapshot_date"] = snapshot_date
    df["vendor"] = "eodhd"
    return df


def normalize_symbol_df(rows: list[dict[str, Any]], *, exchange_code: str, is_delisted: bool, snapshot_date: str) -> pd.DataFrame:
    df = pd.DataFrame(rows_with_provider_payload(rows))
    if df.empty:
        return pd.DataFrame(columns=["code", "name", "country", "exchange", "currency", "type", "isin", "provider_payload_json", "exchange_code", "full_symbol", "is_delisted", "snapshot_date", "vendor"])
    df.columns = [camel_to_snake(c) for c in df.columns]
    if "code" not in df.columns:
        raise RuntimeError(f"Symbol list for {exchange_code} has no code column: {list(df.columns)}")
    df["exchange_code"] = exchange_code
    df["full_symbol"] = df["code"].astype(str).str.strip() + "." + exchange_code
    df["is_delisted"] = bool(is_delisted)
    df["snapshot_date"] = snapshot_date
    df["vendor"] = "eodhd"
    return df


def normalize_eod_df(rows: list[dict[str, Any]], *, full_symbol: str, exchange_code: str, is_delisted: bool, retrieved_at: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    if "date" not in df.columns:
        raise RuntimeError(f"EOD payload for {full_symbol} has no date column: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.NA
    df["volume"] = pd.to_numeric(df.get("volume", pd.Series([pd.NA] * len(df))), errors="coerce").astype("Int64")
    df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    df["vendor"] = "eodhd"
    df["full_symbol"] = full_symbol
    df["exchange_code"] = exchange_code
    df["is_delisted_from_symbol_list"] = bool(is_delisted)
    df["requested_period"] = "d"
    df["retrieved_at"] = retrieved_at
    return df[["vendor", "full_symbol", "exchange_code", "date", "open", "high", "low", "close", "adjusted_close", "volume", "is_delisted_from_symbol_list", "requested_period", "retrieved_at", "provider_payload_json"]]


def normalize_event_df(rows: list[dict[str, Any]], *, full_symbol: str, exchange_code: str, is_delisted: bool, retrieved_at: str, dataset: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    for col in ["date", "declaration_date", "record_date", "payment_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    for col in ["value", "unadjusted_value"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["vendor"] = "eodhd"
    df["full_symbol"] = full_symbol
    df["exchange_code"] = exchange_code
    df["dataset"] = dataset
    df["is_delisted_from_symbol_list"] = bool(is_delisted)
    df["retrieved_at"] = retrieved_at
    return df


def normalize_symbol_changes_df(rows: list[dict[str, Any]], snapshot_date: str) -> pd.DataFrame:
    columns = ["exchange", "old_symbol", "new_symbol", "company_name", "effective", "snapshot_date", "vendor", "provider_payload_json"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    aliases = {
        "exchange_code": "exchange",
        "old_ticker": "old_symbol",
        "new_ticker": "new_symbol",
        "name": "company_name",
        "date": "effective",
        "effective_date": "effective",
    }
    for source, target in aliases.items():
        if source in df.columns and target not in df.columns:
            df[target] = df[source]
    for col in columns[:5]:
        if col not in df.columns:
            df[col] = pd.NA
    df["effective"] = pd.to_datetime(df["effective"], errors="coerce").dt.date
    df["snapshot_date"] = snapshot_date
    df["vendor"] = "eodhd"
    return df[columns]


def symbol_changes_path(root: Path, snapshot_date: str) -> Path:
    return root / "metadata" / "symbol_changes" / f"snapshot_date={snapshot_date}" / "symbol_changes.parquet"


def refresh_symbol_changes(client: RateLimitedEODHDClient, root: Path, snapshot_date: str) -> None:
    key = "symbol-change-history"
    if client.state.is_done("symbol_changes", key, False, 1):
        return
    try:
        rows = client.get_symbol_changes()
    except EntitlementDenied as exc:
        logging.warning("Symbol-change history not entitled; continuing: %s", redact_sensitive(exc))
        client.state.mark_dataset(dataset="symbol_changes", exchange_code="", full_symbol=key, is_delisted=False, status="not_entitled", error=str(exc)[:2000])
        return
    df = normalize_symbol_changes_df(rows, snapshot_date)
    out = symbol_changes_path(root, snapshot_date)
    bytes_written, sha = atomic_write_parquet(df, out)
    client.state.mark_dataset(
        dataset="symbol_changes", exchange_code="", full_symbol=key, is_delisted=False,
        status="done" if len(df) else "empty", rows=len(df), bytes_written=bytes_written,
        sha256=sha, file_path=client.state.relative_file_path(out),
    )


def build_exchange_codes(
    exchange_df: pd.DataFrame,
    requested: Optional[list[str]],
    include_virtual_categories: bool,
    *,
    virtual_asset_categories: tuple[str, ...],
) -> list[str]:
    codes = sorted(set(str(c).strip() for c in exchange_df.get("code", pd.Series(dtype=str)).dropna()))
    if requested:
        return sorted(set(x.strip().upper() for x in requested))
    if include_virtual_categories:
        codes = sorted(set(codes).union(virtual_asset_categories))
    return codes


def symbol_list_state_key(exchange: str, type_value: Optional[str], is_delisted: bool) -> str:
    return f"{exchange}|type={type_value or 'ALL'}|delisted={1 if is_delisted else 0}"


def symbol_list_part_path(root: Path, snapshot_date: str, exchange: str, type_value: Optional[str], is_delisted: bool) -> Path:
    return root / "metadata" / "symbol_lists_parts" / f"snapshot_date={snapshot_date}" / f"exchange={sanitize_path_component(exchange)}" / f"delisted={1 if is_delisted else 0}" / f"type={sanitize_path_component(type_value or 'ALL')}" / "symbols.parquet"


def consolidate_universe(frames: list[pd.DataFrame], root: Path, snapshot_date: str, *, partial: bool) -> pd.DataFrame:
    universe = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if universe.empty:
        return universe
    universe = universe.drop_duplicates(subset=["full_symbol", "is_delisted"], keep="first")
    universe = universe.sort_values(["exchange_code", "full_symbol", "is_delisted"])
    out = root / "metadata" / "symbol_lists" / f"snapshot_date={snapshot_date}" / ("symbols_partial.parquet" if partial else "symbols.parquet")
    atomic_write_parquet(universe, out)
    logging.info("Universe %s written: %s (%s rows)", "partial" if partial else "final", out, len(universe))
    return universe


def build_universe(
    client: RateLimitedEODHDClient,
    root: Path,
    exchange_codes: list[str],
    type_filters: Optional[list[str]],
    include_delisted: bool,
    snapshot_date: str,
    refresh_after_days: Optional[int],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for exchange in exchange_codes:
        for is_delisted in ([False, True] if include_delisted else [False]):
            request_types: list[Optional[str]] = type_filters if type_filters else [None]
            for type_value in request_types:
                key = symbol_list_state_key(exchange, type_value, is_delisted)
                part_path = symbol_list_part_path(root, snapshot_date, exchange, type_value, is_delisted)
                if client.state.is_done("symbol_list", key, False, refresh_after_days) and part_path.exists():
                    df_cached = pd.read_parquet(part_path)
                    if not df_cached.empty:
                        frames.append(df_cached)
                    logging.info("Skipping fresh symbol list exchange=%s type=%s delisted=%s", exchange, type_value or "ALL", is_delisted)
                    continue

                logging.info("Fetching symbol list exchange=%s type=%s delisted=%s", exchange, type_value or "ALL", is_delisted)
                try:
                    rows = client.get_exchange_symbols(exchange, security_type=type_value, delisted=is_delisted)
                except QuotaExceeded as exc:
                    partial = consolidate_universe(frames, root, snapshot_date, partial=True)
                    client.state.mark_dataset(dataset="symbol_list", exchange_code=exchange, full_symbol=key, is_delisted=False, status="quota_deferred", error=str(exc)[:2000])
                    client.state.log_event("WARNING", "quota_exceeded_during_symbol_list", {"exchange": exchange, "delisted": is_delisted, "type": type_value, "partial_rows": len(partial), "error": redact_sensitive(exc)})
                    raise
                except EntitlementDenied as exc:
                    logging.warning("Symbol-list not entitled/access denied; exchange=%s delisted=%s type=%s error=%s", exchange, is_delisted, type_value, redact_sensitive(exc))
                    client.state.mark_dataset(dataset="symbol_list", exchange_code=exchange, full_symbol=key, is_delisted=False, status="not_entitled", rows=0, error=str(exc)[:2000])
                    continue
                except NonRetryableAPIError as exc:
                    logging.warning("Symbol-list non-retryable failure; exchange=%s delisted=%s type=%s error=%s", exchange, is_delisted, type_value, redact_sensitive(exc))
                    client.state.mark_dataset(dataset="symbol_list", exchange_code=exchange, full_symbol=key, is_delisted=False, status="non_retryable", rows=0, error=str(exc)[:2000])
                    continue
                except Exception as exc:
                    logging.exception("Symbol-list fetch failed for exchange=%s delisted=%s type=%s", exchange, is_delisted, type_value)
                    client.state.mark_dataset(dataset="symbol_list", exchange_code=exchange, full_symbol=key, is_delisted=False, status="failed", rows=0, error=str(exc)[:2000])
                    continue

                df = normalize_symbol_df(rows, exchange_code=exchange, is_delisted=is_delisted, snapshot_date=snapshot_date)
                df["request_type_filter"] = type_value or "ALL"
                bytes_written, sha = atomic_write_parquet(df, part_path)
                if not df.empty:
                    frames.append(df)
                client.state.mark_dataset(dataset="symbol_list", exchange_code=exchange, full_symbol=key, is_delisted=False, status="done" if len(df) else "empty", rows=len(df), bytes_written=bytes_written, sha256=sha, file_path=client.state.relative_file_path(part_path))

    universe = consolidate_universe(frames, root, snapshot_date, partial=False)
    if universe.empty:
        raise RuntimeError("No symbols returned; check exchange access, token, and filters.")
    return universe


def should_attempt_corporate_actions(
    row: pd.Series,
    scope: str,
    *,
    corporate_action_eligible_types: frozenset[str],
) -> bool:
    if scope == "all":
        return True
    if scope == "none":
        return False
    exchange_code = str(row.get("exchange_code", "")).upper()
    if exchange_code in {"FOREX", "CC", "GBOND", "MONEY"}:
        return False
    typ = str(row.get("type", "")).strip().lower()
    return typ in corporate_action_eligible_types or typ == ""


def dataset_output_path(root: Path, dataset: str, exchange_code: str, full_symbol: str, is_delisted: bool) -> Path:
    base = root / ("events" if dataset in {"dividends", "splits"} else "prices") / dataset
    return base / f"exchange={sanitize_path_component(exchange_code)}" / f"delisted={1 if is_delisted else 0}" / f"{sanitize_path_component(full_symbol)}.parquet"


def raw_output_path(root: Path, dataset: str, exchange_code: str, full_symbol: str, is_delisted: bool) -> Path:
    return root / "raw" / f"{dataset}_json" / f"exchange={sanitize_path_component(exchange_code)}" / f"delisted={1 if is_delisted else 0}" / f"{sanitize_path_component(full_symbol)}.json.gz"


def write_dataset_rows(
    *,
    dataset: str,
    rows: list[dict[str, Any]],
    root: Path,
    exchange_code: str,
    full_symbol: str,
    is_delisted: bool,
    normalize_fn: Callable[..., pd.DataFrame],
    raw_json: bool,
    state: SQLiteState,
) -> None:
    retrieved_at = dt.datetime.now(UTC).isoformat(timespec="seconds")
    if raw_json:
        atomic_write_json_gz(rows, raw_output_path(root, dataset, exchange_code, full_symbol, is_delisted))

    if not rows:
        state.mark_dataset(dataset=dataset, exchange_code=exchange_code, full_symbol=full_symbol, is_delisted=is_delisted, status="empty", rows=0, retrieved_at=retrieved_at)
        return

    df = normalize_fn(rows, full_symbol=full_symbol, exchange_code=exchange_code, is_delisted=is_delisted, retrieved_at=retrieved_at)
    if df.empty:
        state.mark_dataset(dataset=dataset, exchange_code=exchange_code, full_symbol=full_symbol, is_delisted=is_delisted, status="empty", rows=0, retrieved_at=retrieved_at)
        return

    out = dataset_output_path(root, dataset, exchange_code, full_symbol, is_delisted)
    bytes_written, sha = atomic_write_parquet(df, out)
    state.mark_dataset(dataset=dataset, exchange_code=exchange_code, full_symbol=full_symbol, is_delisted=is_delisted, status="done", rows=len(df), bytes_written=bytes_written, sha256=sha, file_path=state.relative_file_path(out), retrieved_at=retrieved_at)


@dataclasses.dataclass(frozen=True)
class WorkItem:
    dataset: str
    exchange_code: str
    full_symbol: str
    is_delisted: bool


def plan_work_items(
    *,
    dataset: str,
    universe: pd.DataFrame,
    state: SQLiteState,
    refresh_after_days: Optional[int],
    force: bool,
    max_symbols: Optional[int],
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
) -> tuple[list[WorkItem], dict[str, int]]:
    rows = universe.drop_duplicates(subset=["exchange_code", "full_symbol", "is_delisted"]).sort_values(["exchange_code", "full_symbol", "is_delisted"])
    if dataset in {"dividends", "splits"}:
        mask = rows.apply(
            lambda r: should_attempt_corporate_actions(
                r, corporate_actions_scope, corporate_action_eligible_types=corporate_action_eligible_types
            ),
            axis=1,
        )
        rows = rows[mask]
    if max_symbols is not None:
        rows = rows.head(max_symbols)

    fresh_skipped = 0
    missing_or_incomplete: list[WorkItem] = []
    stale: list[WorkItem] = []
    forced: list[WorkItem] = []

    for rec in rows.itertuples(index=False):
        item = WorkItem(dataset=dataset, exchange_code=str(rec.exchange_code), full_symbol=str(rec.full_symbol), is_delisted=bool(rec.is_delisted))
        if force:
            forced.append(item)
            continue
        state_name = state.completion_state(dataset, item.full_symbol, item.is_delisted, refresh_after_days)
        if state_name == "fresh_complete":
            fresh_skipped += 1
        elif state_name == "stale_complete":
            stale.append(item)
        else:
            missing_or_incomplete.append(item)

    items = forced if force else missing_or_incomplete + stale
    stats = {
        "total_candidates": int(len(rows)),
        "fresh_skipped": fresh_skipped,
        "missing_or_incomplete": len(missing_or_incomplete),
        "stale_to_refresh": len(stale),
        "forced": len(forced),
        "planned": len(items),
    }
    return items, stats


def download_one_item(
    *,
    client: RateLimitedEODHDClient,
    state: SQLiteState,
    root: Path,
    item: WorkItem,
    start: Optional[str],
    end: Optional[str],
    raw_json: bool,
) -> tuple[str, str]:
    getter = {
        "eod_daily": client.get_eod_history,
        "dividends": client.get_dividends,
        "splits": client.get_splits,
    }[item.dataset]
    normalizer = {
        "eod_daily": normalize_eod_df,
        "dividends": lambda rows, **kw: normalize_event_df(rows, dataset="dividends", **kw),
        "splits": lambda rows, **kw: normalize_event_df(rows, dataset="splits", **kw),
    }[item.dataset]

    try:
        rows = getter(item.full_symbol, start, end)
        write_dataset_rows(dataset=item.dataset, rows=rows, root=root, exchange_code=item.exchange_code, full_symbol=item.full_symbol, is_delisted=item.is_delisted, normalize_fn=normalizer, raw_json=raw_json, state=state)
        return item.full_symbol, "done_or_empty"
    except QuotaExceeded as exc:
        state.mark_dataset(dataset=item.dataset, exchange_code=item.exchange_code, full_symbol=item.full_symbol, is_delisted=item.is_delisted, status="quota_deferred", error=str(exc)[:2000])
        state.log_event("WARNING", "quota_exceeded_during_dataset", {"dataset": item.dataset, "symbol": item.full_symbol, "error": redact_sensitive(exc)})
        raise
    except EntitlementDenied as exc:
        # Per-symbol entitlement denials should not stop a full archive run.
        state.mark_dataset(dataset=item.dataset, exchange_code=item.exchange_code, full_symbol=item.full_symbol, is_delisted=item.is_delisted, status="not_entitled", error=str(exc)[:2000])
        return item.full_symbol, "not_entitled"
    except NonRetryableAPIError as exc:
        state.mark_dataset(dataset=item.dataset, exchange_code=item.exchange_code, full_symbol=item.full_symbol, is_delisted=item.is_delisted, status="non_retryable", error=str(exc)[:2000])
        return item.full_symbol, "non_retryable"
    except Exception as exc:
        state.mark_dataset(dataset=item.dataset, exchange_code=item.exchange_code, full_symbol=item.full_symbol, is_delisted=item.is_delisted, status="failed", error=str(exc)[:2000])
        return item.full_symbol, "failed"


def write_counts_snapshot(state: SQLiteState, root: Path, snapshot_date: str, label: str = "download_state_counts") -> None:
    counts = state.dataset_counts()
    out = root / "metadata" / "estimates" / f"snapshot_date={snapshot_date}" / f"{label}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_parquet(counts, out)
        logging.info("State counts written: %s", out)
    except Exception:
        csv_out = out.with_suffix(".csv")
        counts.to_csv(csv_out, index=False)
        logging.warning("Could not write state counts as Parquet; wrote CSV instead: %s", csv_out)


def download_dataset_concurrent(
    *,
    dataset: str,
    client: RateLimitedEODHDClient,
    state: SQLiteState,
    root: Path,
    universe: pd.DataFrame,
    start: Optional[str],
    end: Optional[str],
    max_symbols: Optional[int],
    force: bool,
    raw_json: bool,
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
    refresh_after_days: Optional[int],
    concurrency: int,
    progress_every: int,
    snapshot_date: str,
) -> None:
    items, plan_stats = plan_work_items(
        dataset=dataset,
        universe=universe,
        state=state,
        refresh_after_days=refresh_after_days,
        force=force,
        max_symbols=max_symbols,
        corporate_actions_scope=corporate_actions_scope,
        corporate_action_eligible_types=corporate_action_eligible_types,
    )
    logging.info("%s plan: %s", dataset, json.dumps(plan_stats, sort_keys=True))
    if not items:
        return

    counts = {"done_or_empty": 0, "failed": 0, "not_entitled": 0, "non_retryable": 0}
    submitted = 0
    completed = 0
    quota_exc: Optional[BaseException] = None
    start_t = time.monotonic()
    max_workers = max(1, int(concurrency))
    in_flight: set[Future[tuple[str, str]]] = set()
    iterator = iter(items)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"eodhd-{dataset}") as executor:
        def submit_until_full() -> None:
            nonlocal submitted
            while len(in_flight) < max_workers:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                future = executor.submit(download_one_item, client=client, state=state, root=root, item=item, start=start, end=end, raw_json=raw_json)
                in_flight.add(future)
                submitted += 1

        submit_until_full()
        while in_flight:
            done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    _symbol, status = fut.result()
                    counts[status] = counts.get(status, 0) + 1
                    completed += 1
                except QuotaExceeded as exc:
                    quota_exc = exc
                    completed += 1
                except Exception as exc:
                    logging.exception("Unexpected worker failure in %s: %s", dataset, redact_sensitive(exc))
                    counts["failed"] = counts.get("failed", 0) + 1
                    completed += 1

            if completed % max(1, progress_every) == 0 or quota_exc is not None:
                elapsed = max(0.001, time.monotonic() - start_t)
                rate = completed / elapsed * 60.0
                calls_today, requests_today = state.get_today_usage()
                logging.info(
                    "%s progress completed=%s/%s submitted=%s in_flight=%s rate=%.1f items/min counts=%s api_calls_today=%s requests_today=%s",
                    dataset,
                    completed,
                    len(items),
                    submitted,
                    len(in_flight),
                    rate,
                    json.dumps(counts, sort_keys=True),
                    calls_today,
                    requests_today,
                )
                write_counts_snapshot(state, root, snapshot_date, label=f"download_state_counts_{dataset}")

            if quota_exc is not None:
                # Cancel any work that has not started. Already running workers may
                # still finish, but no new work is submitted.
                for pending in in_flight:
                    pending.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                raise quota_exc

            submit_until_full()

    elapsed = max(0.001, time.monotonic() - start_t)
    logging.info("%s finished completed=%s planned=%s elapsed=%.1fs counts=%s", dataset, completed, len(items), elapsed, json.dumps(counts, sort_keys=True))
    write_counts_snapshot(state, root, snapshot_date, label=f"download_state_counts_{dataset}")


def estimate_calls(
    universe: pd.DataFrame,
    *,
    prices: bool,
    dividends: bool,
    splits: bool,
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
    max_api_calls_per_day: int,
) -> dict[str, Any]:
    deduped = universe.drop_duplicates(subset=["full_symbol", "is_delisted"])
    n_symbols = int(len(deduped))
    ca_mask = (
        universe.apply(
            lambda r: should_attempt_corporate_actions(
                r, corporate_actions_scope, corporate_action_eligible_types=corporate_action_eligible_types
            ),
            axis=1,
        )
        if not universe.empty
        else pd.Series(dtype=bool)
    )
    ca_symbols = int(len(universe[ca_mask].drop_duplicates(subset=["full_symbol", "is_delisted"]))) if not universe.empty else 0

    def bundle(p: bool, d: bool, s: bool) -> dict[str, int | None]:
        price_calls = n_symbols if p else 0
        div_calls = ca_symbols if d else 0
        split_calls = ca_symbols if s else 0
        total = price_calls + div_calls + split_calls
        return {
            "price_api_calls_estimate": price_calls,
            "dividend_api_calls_estimate": div_calls,
            "split_api_calls_estimate": split_calls,
            "total_download_api_calls_estimate_excluding_metadata": total,
            "minimum_paid_days_at_configured_daily_budget": (total + max_api_calls_per_day - 1) // max_api_calls_per_day if max_api_calls_per_day else None,
            "minimum_paid_days_at_100k_per_day": (total + 99_999) // 100_000,
        }

    selected = bundle(prices, dividends, splits)
    potential = bundle(True, True, True)
    return {
        "symbols_total": n_symbols,
        "symbols_corporate_action_attempts": ca_symbols,
        "selected_download_flags": {"download_prices": prices, "download_dividends": dividends, "download_splits": splits, "corporate_actions_scope": corporate_actions_scope},
        **selected,
        "selected_download_estimate": selected,
        "potential_full_eod_plan_estimate": potential,
    }


def latest_universe_path(root: Path) -> Optional[Path]:
    base = root / "metadata" / "symbol_lists"
    if not base.exists():
        return None
    paths = sorted(base.glob("snapshot_date=*/symbols.parquet"), reverse=True)
    return paths[0] if paths else None


def resolve_root(root: Optional[Path]) -> Path:
    if root is not None:
        return root.expanduser()
    return get_eodhd_archive_root()


def apply_full_archive_preset(args: argparse.Namespace, argv: Iterable[str], cfg: EodhdConfig) -> argparse.Namespace:
    supplied_options = {str(value).split("=", 1)[0] for value in argv if str(value).startswith("--")}
    scope = cfg.download.scope
    if supplied_options.isdisjoint(FULL_ARCHIVE_SCOPE_OPTIONS):
        args.confirm_full_plan_download = scope.confirm_full_plan_download
        args.include_delisted = scope.include_delisted
        args.download_prices = scope.download_prices
        args.download_dividends = scope.download_dividends
        args.download_splits = scope.download_splits
        args.full_archive_preset = True
    else:
        args.full_archive_preset = False
    return args


def _parse_config_path(argv: Iterable[str]) -> Path:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    pre_args, _ = pre.parse_known_args(list(argv))
    return pre_args.config


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    cfg = load_eodhd_config(_parse_config_path(raw_args))
    download = cfg.download
    limits = download.rate_limits
    scope = download.scope

    p = argparse.ArgumentParser(description="Download EODHD All World EOD data with resumable state and bounded concurrency.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--api-token", default=None)
    p.add_argument("--env-file", type=Path, default=None)
    p.add_argument("--from", dest="start", default=download.start)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--confirm-full-plan-download", action="store_true")
    p.add_argument("--exchanges", nargs="*")
    p.add_argument("--exclude-virtual-categories", action="store_true", default=scope.exclude_virtual_categories)
    p.add_argument("--type-filters", nargs="*", default=None)
    p.add_argument("--include-delisted", action="store_true")
    p.add_argument("--reuse-universe", action="store_true")
    p.add_argument("--metadata-only", action="store_true")
    p.add_argument("--download-prices", action="store_true")
    p.add_argument("--download-dividends", action="store_true")
    p.add_argument("--download-splits", action="store_true")
    p.add_argument("--corporate-actions-scope", choices=["eligible", "all", "none"], default=download.corporate_actions_scope)
    p.add_argument("--max-symbols", type=int, default=None)
    p.add_argument(
        "--refresh-after-days",
        type=int,
        default=download.refresh_after_days,
        help="Refresh completed items older than N days. Use -1 to skip completed items forever unless --force.",
    )
    p.add_argument("--force", action="store_true", default=download.force)
    p.add_argument("--raw-json", action="store_true", default=download.raw_json)
    p.add_argument("--concurrency", type=int, default=download.concurrency, help="Bounded worker count for per-symbol downloads. Metadata discovery remains serial.")
    p.add_argument("--http-timeout", type=int, default=download.http_timeout)
    p.add_argument("--connection-pool-size", type=int, default=None)
    p.add_argument("--progress-every", type=int, default=download.progress_every)
    p.add_argument("--max-requests-per-minute", type=int, default=limits.max_requests_per_minute)
    p.add_argument("--max-api-calls-per-day", type=int, default=limits.max_api_calls_per_day)
    p.add_argument("--sleep-on-daily-limit", action="store_true", default=download.sleep_on_daily_limit)
    p.add_argument("--min-seconds-between-requests", type=float, default=limits.min_seconds_between_requests)
    p.add_argument("--state-db", type=Path, default=None)
    p.add_argument("--log-level", default=download.log_level, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(raw_args)
    args.eodhd_config = cfg
    return apply_full_archive_preset(args, raw_args, cfg)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    cfg: EodhdConfig = args.eodhd_config
    scope = cfg.download.scope
    api = cfg.api
    rate_limits = cfg.download.rate_limits
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    if args.full_archive_preset:
        logging.info("No scope-selection arguments supplied; using full archive preset with active and delisted symbols, prices, dividends, and splits.")

    if args.type_filters:
        bad = [x for x in args.type_filters if x not in scope.supported_type_filters]
        if bad:
            logging.error("Unsupported type filters: %s. Supported: %s", bad, sorted(scope.supported_type_filters))
            return 2
    if not args.confirm_full_plan_download and not args.exchanges and not args.reuse_universe:
        logging.error("Refusing broad discovery without --confirm-full-plan-download, --exchanges, or --reuse-universe.")
        return 2

    token, token_source = resolve_api_token(args.api_token, args.env_file)
    if not token:
        logging.error("Missing API token. Set EODHD_API_TOKEN in .env or pass --api-token.")
        return 2
    logging.info("Using EODHD API token from %s", token_source)

    try:
        root = resolve_root(args.root)
    except ValueError as exc:
        logging.error("%s", exc)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    state = SQLiteState(args.state_db or root / cfg.paths.state_db, root=root)
    snapshot_date = dt.datetime.now(UTC).date().isoformat()

    try:
        pool_size = args.connection_pool_size or max(10, int(args.concurrency) * 2)
        client = RateLimitedEODHDClient(
            token=token,
            state=state,
            limits=ApiLimits(max_requests_per_minute=args.max_requests_per_minute, max_api_calls_per_day=args.max_api_calls_per_day, min_seconds_between_requests=args.min_seconds_between_requests, sleep_on_daily_limit=args.sleep_on_daily_limit),
            timeout=args.http_timeout,
            pool_size=pool_size,
            api_base=api.base_url,
            symbol_change_start_date=api.symbol_change_start_date,
            default_provider_cooldown_seconds=rate_limits.provider_rate_limit_cooldown_seconds,
            max_provider_cooldown_seconds=rate_limits.max_provider_rate_limit_cooldown_seconds,
        )
        refresh_symbol_changes(client, root, snapshot_date)

        if args.reuse_universe:
            universe_path = latest_universe_path(root)
            if universe_path is None:
                raise RuntimeError("--reuse-universe requested but no metadata/symbol_lists snapshot exists.")
            logging.info("Reusing universe: %s", universe_path)
            universe = pd.read_parquet(universe_path)
        else:
            exchanges = client.get_exchanges()
            exchange_df = normalize_exchange_df(exchanges, snapshot_date=snapshot_date)
            exchange_out = root / "metadata" / "exchanges" / f"snapshot_date={snapshot_date}" / "exchanges.parquet"
            atomic_write_parquet(exchange_df, exchange_out)
            logging.info("Exchange metadata written: %s (%s rows)", exchange_out, len(exchange_df))
            exchange_codes = build_exchange_codes(
                exchange_df,
                requested=args.exchanges,
                include_virtual_categories=not args.exclude_virtual_categories,
                virtual_asset_categories=scope.virtual_asset_categories,
            )
            universe = build_universe(client, root, exchange_codes, args.type_filters, args.include_delisted, snapshot_date, args.refresh_after_days)

        if not any([args.download_prices, args.download_dividends, args.download_splits]):
            logging.info("No core EOD download flags supplied; defaulting selected estimate/run scope to prices + dividends + splits.")
            args.download_prices = True
            args.download_dividends = True
            args.download_splits = True

        estimate = estimate_calls(
            universe,
            prices=args.download_prices,
            dividends=args.download_dividends,
            splits=args.download_splits,
            corporate_actions_scope=args.corporate_actions_scope,
            corporate_action_eligible_types=scope.corporate_action_eligible_types,
            max_api_calls_per_day=args.max_api_calls_per_day,
        )
        estimate_out = root / "metadata" / "estimates" / f"snapshot_date={snapshot_date}" / "all_world_eod_estimate.json"
        estimate_out.parent.mkdir(parents=True, exist_ok=True)
        estimate_out.write_text(json.dumps(estimate, indent=2, sort_keys=True), encoding="utf-8")
        logging.info("Estimate written: %s", estimate_out)
        logging.info("Estimate: %s", json.dumps(estimate, indent=2, sort_keys=True))

        if args.metadata_only:
            logging.info("Stopping before downloads due to --metadata-only")
            return 0

        common = dict(
            client=client,
            state=state,
            root=root,
            universe=universe,
            start=args.start,
            end=args.end,
            max_symbols=args.max_symbols,
            force=args.force,
            raw_json=args.raw_json,
            corporate_actions_scope=args.corporate_actions_scope,
            corporate_action_eligible_types=scope.corporate_action_eligible_types,
            refresh_after_days=args.refresh_after_days,
            concurrency=args.concurrency,
            progress_every=args.progress_every,
            snapshot_date=snapshot_date,
        )
        if args.download_prices:
            download_dataset_concurrent(dataset="eod_daily", **common)
        if args.download_dividends:
            download_dataset_concurrent(dataset="dividends", **common)
        if args.download_splits:
            download_dataset_concurrent(dataset="splits", **common)

        write_counts_snapshot(state, root, snapshot_date)
        counts = state.dataset_counts()
        failed = counts[counts["status"].eq("failed")]["n"].sum() if not counts.empty else 0
        if failed:
            logging.warning("Run finished with failed items. Re-run without --force to retry failed/missing only. failures=%s", failed)
            return 1
        return 0

    except QuotaExceeded as exc:
        logging.warning("Quota exhausted/local budget reached. State is persisted; rerun the same command later. Error=%s", redact_sensitive(exc))
        state.log_event("WARNING", "run_stopped_quota_exceeded", {"error": redact_sensitive(exc)})
        write_counts_snapshot(state, root, snapshot_date, label="download_state_counts_quota_stop")
        return 75
    finally:
        state.close()


if __name__ == "__main__":
    raise SystemExit(main())
