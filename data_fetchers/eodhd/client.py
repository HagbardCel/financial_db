"""EODHD HTTP API client with rate limiting."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import email.utils
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import requests
from requests.adapters import HTTPAdapter

from db_utils.config import load_project_environment

from .common import UTC

if TYPE_CHECKING:
    from .state import SQLiteState

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


@dataclasses.dataclass(frozen=True)
class ApiLimits:
    max_requests_per_minute: int = 900
    max_api_calls_per_day: int = 95_000
    min_seconds_between_requests: float = 0.05
    sleep_on_daily_limit: bool = False


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
                    payload = {
                        "status_code": 429,
                        "url": safe_url,
                        "body_preview": body_preview,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "cooldown_seconds": cooldown_s,
                    }
                    if attempt == max_attempts:
                        self.state.log_event("WARNING", "provider_quota_or_rate_limit", payload)
                        raise QuotaExceeded(
                            f"HTTP 429 provider quota/rate limit after {max_attempts} attempts for {safe_url}: {body_preview!r}"
                        )
                    self.state.log_event("WARNING", "provider_rate_limit_retry", payload)
                    logging.warning(
                        "HTTP 429 for %s; scheduling shared %.2fs cooldown before retry %s/%s",
                        safe_url,
                        cooldown_s,
                        attempt + 1,
                        max_attempts,
                    )
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
