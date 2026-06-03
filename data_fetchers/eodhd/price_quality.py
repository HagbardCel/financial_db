from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2

from db_utils.config import get_database_config

from .common import resolve_state_db_path
from .paths import atomic_write_csv, atomic_write_parquet, atomic_write_text, dataset_output_path, resolve_root


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "adjusted_close", "volume"}
SCANNER_VERSION = "1"
QUALITY_COLUMNS = [
    "build_id", "eodhd_symbol", "exchange_code", "is_delisted", "source_file", "status", "error",
    "missing_columns", "row_count", "first_date", "last_date", "invalid_date_count", "duplicate_date_count",
    "non_positive_close_count", "inconsistent_ohlc_count", "adjusted_close_coverage_ratio",
    "non_positive_adjusted_close_count", "null_or_non_positive_volume_ratio", "longest_unchanged_close_run",
    "checkpoint_status",
]


@dataclass(frozen=True)
class PriceQualityReport:
    build_id: str
    universe_name: str
    output_dir: Path
    summary: dict[str, Any]
    symbol_quality: pd.DataFrame


def _latest_build_id(cursor: Any, universe_name: str) -> str:
    cursor.execute(
        "SELECT build_id FROM eodhd.universe_builds WHERE universe_name = %s "
        "ORDER BY created_at DESC, build_id DESC LIMIT 1",
        (universe_name,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"No persisted EODHD universe build found for {universe_name}.")
    return str(row[0])


def load_persisted_memberships(universe_name: str, *, build_id: str = "latest") -> tuple[str, pd.DataFrame]:
    with psycopg2.connect(**get_database_config()) as connection:
        with connection.cursor() as cursor:
            resolved_build_id = _latest_build_id(cursor, universe_name) if build_id == "latest" else build_id
            cursor.execute(
                "SELECT 1 FROM eodhd.universe_builds WHERE universe_name = %s AND build_id = %s",
                (universe_name, resolved_build_id),
            )
            if cursor.fetchone() is None:
                raise RuntimeError(f"Universe build {resolved_build_id} does not belong to {universe_name}.")
            return resolved_build_id, pd.read_sql_query(
                "SELECT * FROM eodhd.universe_memberships WHERE build_id = %s",
                connection,
                params=(resolved_build_id,),
            )


def load_memberships_file(path: Path, *, build_id: str = "latest") -> tuple[str, pd.DataFrame]:
    memberships = pd.read_csv(path, low_memory=False)
    required = {"build_id", "eodhd_symbol", "exchange_code", "is_delisted", "membership_status"}
    missing = sorted(required.difference(memberships.columns))
    if missing:
        raise ValueError(f"Membership file is missing required columns: {missing}")
    build_ids = sorted(memberships["build_id"].dropna().astype(str).unique())
    if len(build_ids) != 1:
        raise ValueError("Membership file must contain exactly one build_id.")
    resolved_build_id = build_ids[0]
    if build_id != "latest" and build_id != resolved_build_id:
        raise ValueError(f"Membership file build_id is {resolved_build_id}, not {build_id}.")
    return resolved_build_id, memberships


def _longest_unchanged_close_run(frame: pd.DataFrame) -> int:
    ordered = frame.dropna(subset=["date", "close"]).sort_values("date")
    if ordered.empty:
        return 0
    groups = ordered["close"].ne(ordered["close"].shift()).cumsum()
    return int(ordered.groupby(groups).size().max())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"Unsupported is_delisted value: {value!r}")


def load_checkpoint_statuses(root: Path) -> dict[tuple[str, bool], str]:
    path = resolve_state_db_path(root)
    if not path.exists():
        return {}
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return {
            (str(symbol), bool(is_delisted)): str(status)
            for symbol, is_delisted, status in connection.execute(
                "SELECT full_symbol, is_delisted, status FROM dataset_download_state WHERE dataset = 'eod_daily'"
            )
        }
    finally:
        connection.close()


def _empty_metrics(row: pd.Series, root: Path, status: str, *, error: str | None = None, checkpoint_status: str | None = None) -> dict[str, Any]:
    path = dataset_output_path(root, "eod_daily", str(row["exchange_code"]), str(row["eodhd_symbol"]), _as_bool(row["is_delisted"]))
    return {
        "build_id": str(row["build_id"]),
        "eodhd_symbol": str(row["eodhd_symbol"]),
        "exchange_code": str(row["exchange_code"]),
        "is_delisted": _as_bool(row["is_delisted"]),
        "source_file": str(path.relative_to(root)),
        "status": status,
        "error": error,
        "missing_columns": None,
        "row_count": 0,
        "first_date": None,
        "last_date": None,
        "invalid_date_count": 0,
        "duplicate_date_count": 0,
        "non_positive_close_count": 0,
        "inconsistent_ohlc_count": 0,
        "adjusted_close_coverage_ratio": None,
        "non_positive_adjusted_close_count": 0,
        "null_or_non_positive_volume_ratio": None,
        "longest_unchanged_close_run": 0,
        "checkpoint_status": checkpoint_status,
    }


def scan_symbol(root: Path, row: pd.Series, checkpoint_statuses: dict[tuple[str, bool], str] | None = None) -> dict[str, Any]:
    path = dataset_output_path(root, "eod_daily", str(row["exchange_code"]), str(row["eodhd_symbol"]), _as_bool(row["is_delisted"]))
    if not path.exists():
        checkpoint_status = (checkpoint_statuses or {}).get((str(row["eodhd_symbol"]), _as_bool(row["is_delisted"])))
        return _empty_metrics(row, root, "upstream_empty" if checkpoint_status == "empty" else "missing_file", checkpoint_status=checkpoint_status)
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return _empty_metrics(row, root, "unreadable_parquet", error=f"{type(exc).__name__}: {exc}")
    if frame.empty:
        return _empty_metrics(row, root, "empty_file")

    missing_columns = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing_columns:
        metrics = _empty_metrics(row, root, "missing_required_columns")
        metrics["row_count"] = int(len(frame))
        metrics["missing_columns"] = ",".join(missing_columns)
        return metrics

    dates = pd.to_datetime(frame["date"], errors="coerce")
    numeric = frame[["open", "high", "low", "close", "adjusted_close", "volume"]].apply(pd.to_numeric, errors="coerce")
    quality = pd.DataFrame({"date": dates, **{column: numeric[column] for column in numeric.columns}})
    valid_dates = dates.dropna()
    inconsistent_ohlc = (
        numeric["high"].lt(numeric["low"])
        | numeric["high"].lt(numeric["open"])
        | numeric["high"].lt(numeric["close"])
        | numeric["low"].gt(numeric["open"])
        | numeric["low"].gt(numeric["close"])
    )
    anomaly_count = (
        int(dates.isna().sum())
        + int(valid_dates.duplicated().sum())
        + int(numeric["close"].le(0).sum())
        + int(inconsistent_ohlc.sum())
    )
    metrics = _empty_metrics(row, root, "quality_issues" if anomaly_count else "ok")
    metrics.update(
        {
            "row_count": int(len(frame)),
            "first_date": valid_dates.min().date().isoformat() if not valid_dates.empty else None,
            "last_date": valid_dates.max().date().isoformat() if not valid_dates.empty else None,
            "invalid_date_count": int(dates.isna().sum()),
            "duplicate_date_count": int(valid_dates.duplicated().sum()),
            "non_positive_close_count": int(numeric["close"].le(0).sum()),
            "inconsistent_ohlc_count": int(inconsistent_ohlc.sum()),
            "adjusted_close_coverage_ratio": float(numeric["adjusted_close"].notna().mean()),
            "non_positive_adjusted_close_count": int(numeric["adjusted_close"].le(0).sum()),
            "null_or_non_positive_volume_ratio": float((numeric["volume"].isna() | numeric["volume"].le(0)).mean()),
            "longest_unchanged_close_run": _longest_unchanged_close_run(quality),
        }
    )
    return metrics


def build_price_quality_report(
    root: Path | None = None,
    *,
    universe_name: str,
    build_id: str = "latest",
    memberships_file: Path | None = None,
    output_root: Path = Path("derived/reports/eodhd/price_quality"),
    workers: int = 8,
    max_symbols: int | None = None,
) -> PriceQualityReport:
    if workers < 1:
        raise ValueError("workers must be at least 1.")
    if max_symbols is not None and max_symbols < 1:
        raise ValueError("max_symbols must be at least 1.")
    resolved_root = resolve_root(root)
    if memberships_file is None:
        resolved_build_id, memberships = load_persisted_memberships(universe_name, build_id=build_id)
        membership_source = "postgresql"
    else:
        resolved_build_id, memberships = load_memberships_file(memberships_file, build_id=build_id)
        membership_source = str(memberships_file)

    selected = memberships[memberships["membership_status"].eq("selected_candidate")].copy()
    selected["is_delisted"] = selected["is_delisted"].map(_as_bool)
    selected = selected.sort_values(["eodhd_symbol", "is_delisted"], kind="stable")
    selected_candidate_count = int(len(selected))
    if max_symbols is not None:
        selected = selected.head(max_symbols)

    rows = [row for _, row in selected.iterrows()]
    checkpoint_statuses = load_checkpoint_statuses(resolved_root)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        quality = pd.DataFrame(executor.map(lambda row: scan_symbol(resolved_root, row, checkpoint_statuses), rows), columns=QUALITY_COLUMNS)
    quality = quality.sort_values(["eodhd_symbol", "is_delisted"], kind="stable").reset_index(drop=True)

    output_dir = output_root / universe_name / f"build_id={resolved_build_id}"
    status_counts = (
        quality.groupby("status").size().rename("count").reset_index().sort_values("status")
        if not quality.empty
        else pd.DataFrame(columns=["status", "count"])
    )
    summary = {
        "scanner_version": SCANNER_VERSION,
        "universe_name": universe_name,
        "build_id": resolved_build_id,
        "membership_source": membership_source,
        "selected_candidate_count": selected_candidate_count,
        "scanned_symbol_count": int(len(quality)),
        "partial_scan": max_symbols is not None,
        "max_symbols": max_symbols,
        "status_counts": {str(row.status): int(row.count) for row in status_counts.itertuples(index=False)},
    }
    atomic_write_parquet(quality, output_dir / "symbol_quality.parquet")
    atomic_write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", output_dir / "summary.json")
    atomic_write_csv(status_counts, output_dir / "status_counts.csv")
    atomic_write_csv(quality[quality["status"].eq("missing_file")], output_dir / "missing_price_files.csv")
    coverage_columns = ["build_id", "eodhd_symbol", "exchange_code", "is_delisted", "status", "row_count", "adjusted_close_coverage_ratio", "non_positive_adjusted_close_count"]
    atomic_write_csv(quality.reindex(columns=coverage_columns), output_dir / "adjusted_close_coverage.csv")
    return PriceQualityReport(resolved_build_id, universe_name, output_dir, summary, quality)
