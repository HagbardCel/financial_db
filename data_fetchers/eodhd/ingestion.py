from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import psycopg2

from db_utils.config import get_database_config
from .downloader import resolve_root, sha256_file


UTC = dt.timezone.utc


def parquet_artifacts(root: Path) -> Iterable[tuple[str, Path]]:
    patterns = {
        "exchange_snapshots": "metadata/exchanges/snapshot_date=*/exchanges.parquet",
        "symbol_snapshots": "metadata/symbol_lists/snapshot_date=*/symbols.parquet",
        "eod_prices": "prices/eod_daily/exchange=*/delisted=*/*.parquet",
        "dividends": "events/dividends/exchange=*/delisted=*/*.parquet",
        "splits": "events/splits/exchange=*/delisted=*/*.parquet",
        "symbol_changes": "metadata/symbol_changes/snapshot_date=*/symbol_changes.parquet",
    }
    for dataset, pattern in patterns.items():
        for path in sorted(root.glob(pattern)):
            yield dataset, path


def _clean(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _value(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return _clean(row[name])
    return default


def _json(row: dict[str, Any]) -> str:
    return json.dumps({key: _clean(value) for key, value in row.items()}, default=str, sort_keys=True, separators=(",", ":"))


def _hash(row: dict[str, Any]) -> str:
    volatile = {"dataset", "full_symbol", "exchange_code", "is_delisted_from_symbol_list", "retrieved_at", "vendor"}
    stable = {key: value for key, value in row.items() if key not in volatile}
    return hashlib.sha256(_json(stable).encode("utf-8")).hexdigest()


def transform(dataset: str, frame: pd.DataFrame, relative_path: str) -> tuple[list[str], list[list[Any]]]:
    records = frame.to_dict("records")
    if dataset == "exchange_snapshots":
        columns = ["snapshot_date", "exchange_code", "name", "country", "currency", "operating_mic", "raw_json", "source_file"]
        rows = [[_value(r, "snapshot_date"), _value(r, "code"), _value(r, "name"), _value(r, "country"), _value(r, "currency"), _value(r, "operating_mic"), _json(r), relative_path] for r in records]
    elif dataset == "symbol_snapshots":
        columns = ["snapshot_date", "eodhd_symbol", "exchange_code", "code", "name", "country", "currency", "security_type", "isin", "is_delisted", "request_type_filter", "raw_json", "source_file"]
        rows = [[_value(r, "snapshot_date"), _value(r, "full_symbol"), _value(r, "exchange_code"), _value(r, "code"), _value(r, "name"), _value(r, "country"), _value(r, "currency"), _value(r, "type"), _value(r, "isin"), _value(r, "is_delisted", default=False), _value(r, "request_type_filter", default="ALL"), _json(r), relative_path] for r in records]
    elif dataset == "eod_prices":
        columns = ["eodhd_symbol", "exchange_code", "date", "open", "high", "low", "close", "adjusted_close", "volume", "is_delisted_from_symbol_list", "requested_period", "retrieved_at", "source_file"]
        rows = [[_value(r, "full_symbol"), _value(r, "exchange_code"), _value(r, "date"), _value(r, "open"), _value(r, "high"), _value(r, "low"), _value(r, "close"), _value(r, "adjusted_close"), _value(r, "volume"), _value(r, "is_delisted_from_symbol_list", default=False), _value(r, "requested_period", default="d"), _value(r, "retrieved_at"), relative_path] for r in records]
    elif dataset == "dividends":
        columns = ["eodhd_symbol", "exchange_code", "date", "declaration_date", "record_date", "payment_date", "value", "unadjusted_value", "currency", "period", "is_delisted_from_symbol_list", "retrieved_at", "event_hash", "raw_json", "source_file"]
        rows = [[_value(r, "full_symbol"), _value(r, "exchange_code"), _value(r, "date"), _value(r, "declaration_date"), _value(r, "record_date"), _value(r, "payment_date"), _value(r, "value"), _value(r, "unadjusted_value"), _value(r, "currency"), _value(r, "period"), _value(r, "is_delisted_from_symbol_list", default=False), _value(r, "retrieved_at"), _hash(r), _json(r), relative_path] for r in records]
    elif dataset == "splits":
        columns = ["eodhd_symbol", "exchange_code", "date", "split", "is_delisted_from_symbol_list", "retrieved_at", "event_hash", "raw_json", "source_file"]
        rows = [[_value(r, "full_symbol"), _value(r, "exchange_code"), _value(r, "date"), _value(r, "split", "value"), _value(r, "is_delisted_from_symbol_list", default=False), _value(r, "retrieved_at"), _hash(r), _json(r), relative_path] for r in records]
    elif dataset == "symbol_changes":
        columns = ["exchange_code", "old_symbol", "new_symbol", "company_name", "effective_date", "snapshot_date", "raw_json", "source_file"]
        rows = [[_value(r, "exchange", "exchange_code"), _value(r, "old_symbol"), _value(r, "new_symbol"), _value(r, "company_name"), _value(r, "effective", "effective_date"), _value(r, "snapshot_date"), _json(r), relative_path] for r in records]
    else:
        raise ValueError(f"Unsupported EODHD dataset: {dataset}")
    return columns, rows


def _copy_rows(cursor: Any, table: str, columns: list[str], rows: list[list[Any]]) -> None:
    if not rows:
        return
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows([["\\N" if value is None else value for value in row] for row in rows])
    stream.seek(0)
    cursor.copy_expert(f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", stream)


def ingest_file(conn: Any, root: Path, dataset: str, path: Path, *, batch_rows: int = 10_000) -> bool:
    relative = str(path.relative_to(root))
    sha256 = sha256_file(path)
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM eodhd.ingestion_artifacts WHERE parquet_path = %s AND sha256 = %s", (relative, sha256))
        if cursor.fetchone():
            conn.rollback()
            return False
        frame = pd.read_parquet(path)
        columns, rows = transform(dataset, frame, relative)
        cursor.execute(f"DELETE FROM eodhd.{dataset} WHERE source_file = %s", (relative,))
        conflict_columns = {
            "exchange_snapshots": ["snapshot_date", "exchange_code"],
            "symbol_snapshots": ["snapshot_date", "eodhd_symbol", "is_delisted", "request_type_filter"],
            "eod_prices": ["eodhd_symbol", "date", "is_delisted_from_symbol_list", "requested_period"],
            "dividends": ["eodhd_symbol", "event_hash"],
            "splits": ["eodhd_symbol", "event_hash"],
            "symbol_changes": ["exchange_code", "old_symbol", "new_symbol", "effective_date"],
        }[dataset]
        updates = [column for column in columns if column not in conflict_columns]
        for start in range(0, len(rows), batch_rows):
            cursor.execute(f"CREATE TEMP TABLE eodhd_stage (LIKE eodhd.{dataset} INCLUDING DEFAULTS) ON COMMIT DROP")
            _copy_rows(cursor, "eodhd_stage", columns, rows[start:start + batch_rows])
            cursor.execute(
                f"INSERT INTO eodhd.{dataset} ({', '.join(columns)}) "
                f"SELECT {', '.join(columns)} FROM eodhd_stage "
                f"ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE SET "
                + ", ".join(f"{column} = EXCLUDED.{column}" for column in updates)
            )
            cursor.execute("DROP TABLE eodhd_stage")
        cursor.execute(
            "INSERT INTO eodhd.ingestion_artifacts (parquet_path, sha256, dataset, row_count, ingested_at) "
            "VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT (parquet_path) DO UPDATE SET "
            "sha256 = EXCLUDED.sha256, dataset = EXCLUDED.dataset, row_count = EXCLUDED.row_count, ingested_at = EXCLUDED.ingested_at",
            (relative, sha256, dataset, len(frame)),
        )
    conn.commit()
    return True


def ingest(root: Path | None = None, *, batch_rows: int = 10_000) -> tuple[int, int]:
    resolved_root = resolve_root(root)
    loaded = skipped = 0
    with psycopg2.connect(**get_database_config()) as conn:
        for dataset, path in parquet_artifacts(resolved_root):
            if ingest_file(conn, resolved_root, dataset, path, batch_rows=batch_rows):
                loaded += 1
            else:
                skipped += 1
    return loaded, skipped
