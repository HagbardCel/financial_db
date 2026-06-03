from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .downloader import resolve_root


@dataclass(frozen=True)
class MetadataReport:
    snapshot_date: str
    output_dir: Path
    summary: dict[str, Any]


def resolve_snapshot_date(root: Path, snapshot_date: str) -> str:
    if snapshot_date != "latest":
        return snapshot_date
    snapshots = sorted((root / "metadata" / "symbol_lists").glob("snapshot_date=*/symbols.parquet"))
    if not snapshots:
        raise RuntimeError("No consolidated EODHD symbol snapshots found.")
    return snapshots[-1].parent.name.split("=", 1)[1]


def metadata_paths(root: Path, snapshot_date: str) -> tuple[Path, Path]:
    return (
        root / "metadata" / "exchanges" / f"snapshot_date={snapshot_date}" / "exchanges.parquet",
        root / "metadata" / "symbol_lists" / f"snapshot_date={snapshot_date}" / "symbols.parquet",
    )


def _valid_isin(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _download_state_counts(root: Path) -> pd.DataFrame:
    path = root / "state" / "eodhd_all_world_snapshot.sqlite3"
    columns = ["dataset", "status", "count"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return pd.read_sql_query(
            "SELECT dataset, status, COUNT(*) AS count "
            "FROM dataset_download_state GROUP BY dataset, status ORDER BY dataset, status",
            connection,
        )
    finally:
        connection.close()


def build_metadata_report(
    root: Path | None = None,
    *,
    snapshot_date: str = "latest",
    output_root: Path = Path("derived/reports/eodhd/metadata"),
) -> MetadataReport:
    resolved_root = resolve_root(root)
    resolved_date = resolve_snapshot_date(resolved_root, snapshot_date)
    exchange_path, symbol_path = metadata_paths(resolved_root, resolved_date)
    if not exchange_path.exists() or not symbol_path.exists():
        raise RuntimeError(f"Incomplete EODHD metadata snapshot: {resolved_date}")

    exchanges = pd.read_parquet(exchange_path)
    symbols = pd.read_parquet(symbol_path)
    output_dir = output_root / f"snapshot_date={resolved_date}"
    output_dir.mkdir(parents=True, exist_ok=True)

    exchange_codes = set(exchanges["code"].dropna().astype(str))
    symbol_exchange_codes = set(symbols["exchange_code"].dropna().astype(str))
    coverage = exchanges[["code", "name", "country", "currency", "operating_mic"]].copy()
    coverage["has_symbol_rows"] = coverage["code"].isin(symbol_exchange_codes)
    coverage.to_csv(output_dir / "exchange_coverage.csv", index=False)

    counts = symbols.groupby("exchange_code", dropna=False).size().rename("symbol_count").reset_index()
    counts.to_csv(output_dir / "symbol_counts_by_exchange.csv", index=False)
    symbols.groupby("type", dropna=False).size().rename("symbol_count").reset_index().to_csv(
        output_dir / "instrument_type_counts.csv", index=False
    )
    isin_missing = symbols["isin"].isna() | symbols["isin"].fillna("").astype(str).str.strip().eq("")
    missing_isin = symbols.assign(missing_isin=isin_missing).groupby("exchange_code").agg(
        symbol_count=("full_symbol", "size"),
        missing_isin_count=("missing_isin", "sum"),
    )
    missing_isin["missing_isin_rate"] = missing_isin["missing_isin_count"] / missing_isin["symbol_count"]
    missing_isin.reset_index().to_csv(output_dir / "missing_isin_by_exchange.csv", index=False)

    valid = symbols[_valid_isin(symbols["isin"])].copy()
    duplicates = valid[valid.duplicated("isin", keep=False)].sort_values(["isin", "exchange_code", "full_symbol"])
    duplicates.to_csv(output_dir / "duplicate_isin_groups.csv", index=False)
    cross_exchange = duplicates.groupby("isin").filter(lambda frame: frame["exchange_code"].nunique() > 1)
    cross_exchange.to_csv(output_dir / "cross_exchange_duplicate_isin_groups.csv", index=False)

    us = symbols[symbols["exchange_code"].eq("US")]
    us.groupby("exchange", dropna=False).size().rename("symbol_count").reset_index().to_csv(
        output_dir / "us_provider_venue_counts.csv", index=False
    )
    state_counts = _download_state_counts(resolved_root)
    state_counts.to_csv(output_dir / "download_state_counts.csv", index=False)

    summary = {
        "snapshot_date": resolved_date,
        "exchange_count": int(len(exchanges)),
        "symbol_exchange_count": int(symbols["exchange_code"].nunique()),
        "exchanges_without_symbol_rows": sorted(exchange_codes - symbol_exchange_codes),
        "symbol_count": int(len(symbols)),
        "active_symbol_count": int((~symbols["is_delisted"]).sum()),
        "delisted_symbol_count": int(symbols["is_delisted"].sum()),
        "missing_isin_count": int(isin_missing.sum()),
        "duplicate_isin_group_count": int(duplicates["isin"].nunique()),
        "cross_exchange_duplicate_isin_group_count": int(cross_exchange["isin"].nunique()),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MetadataReport(resolved_date, output_dir, summary)
