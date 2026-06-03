"""EODHD SQLite checkpoint state."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .client import redact_sensitive
from .common import UTC


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
