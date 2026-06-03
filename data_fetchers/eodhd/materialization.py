from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2

from db_utils.config import get_database_config

from .downloader import dataset_output_path, resolve_root, sha256_file
from .price_quality import load_memberships_file, load_persisted_memberships


UTC = dt.timezone.utc
PROVIDER = "eodhd"
QUALITY_BLOCKING_STATUSES = {"missing_file", "unreadable_parquet", "missing_required_columns"}


@dataclass(frozen=True)
class CuratedFrames:
    securities: pd.DataFrame
    listings: pd.DataFrame
    bars: pd.DataFrame
    raw_metrics: pd.DataFrame
    rejected_rows: pd.DataFrame


def _security_id(row: pd.Series) -> str:
    return str(row["isin"]) if bool(row.get("isin_valid")) and pd.notna(row.get("isin")) else f"eodhd:{row['eodhd_symbol']}"


def build_reference_frames(memberships: pd.DataFrame, *, source_file: str = "eodhd.universe_memberships") -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = memberships[memberships["membership_status"].eq("selected_candidate")].copy()
    now = dt.datetime.now(UTC).replace(tzinfo=None)
    securities = []
    listings = []
    for symbol, group in selected.groupby("eodhd_symbol", sort=True):
        row = group.sort_values("is_delisted").iloc[0]
        security_id = _security_id(row)
        active = bool((~group["is_delisted"].astype(bool)).any())
        securities.append(
            {
                "security_id": security_id, "isin": row.get("isin") if pd.notna(row.get("isin")) else None,
                "name": row.get("name") or symbol, "security_type": str(row.get("security_type") or "").lower(),
                "country": "US", "currency_primary": row.get("currency") or "USD", "source_first_seen": PROVIDER,
                "source_last_seen": PROVIDER, "active_flag_current": active, "created_at_utc": now, "updated_at_utc": now,
            }
        )
        listings.append(
            {
                "listing_id": f"eodhd:{symbol}", "security_id": security_id, "provider": PROVIDER,
                "provider_symbol": symbol, "exchange_code": row.get("exchange_code"), "mic": None,
                "trading_currency": row.get("currency") or "USD", "isin": row.get("isin") if pd.notna(row.get("isin")) else None,
                "name": row.get("name") or symbol, "first_seen_date": None, "last_seen_date": None,
                "is_currently_tradable": active, "source_file": source_file,
            }
        )
    return pd.DataFrame(securities), pd.DataFrame(listings)


def _curate_symbol(root: Path, listing: pd.Series, membership_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = []
    for row in membership_rows.sort_values("is_delisted", ascending=False).itertuples(index=False):
        path = dataset_output_path(root, "eod_daily", str(row.exchange_code), str(row.eodhd_symbol), bool(row.is_delisted))
        if not path.exists():
            continue
        frame = pd.read_parquet(path).copy()
        frame["source_file"] = str(path.relative_to(root))
        frame["is_delisted_archive"] = bool(row.is_delisted)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.date
    for column in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.sort_values(["date", "is_delisted_archive"]).drop_duplicates("date", keep="first")
    valid = raw["date"].notna() & raw["close"].gt(0) & raw["adjusted_close"].gt(0)
    rejected = raw[~valid].copy()
    rejected["rejection_reason"] = "missing_or_non_positive_close"
    accepted = raw[valid].copy()
    factor = accepted["adjusted_close"] / accepted["close"]
    now = dt.datetime.now(UTC).replace(tzinfo=None)
    bars = pd.DataFrame(
        {
            "provider": PROVIDER, "provider_symbol": listing["provider_symbol"], "security_id": listing["security_id"],
            "listing_id": listing["listing_id"], "date": accepted["date"],
            "open": accepted["open"] * factor, "high": accepted["high"] * factor, "low": accepted["low"] * factor,
            "close": accepted["adjusted_close"], "volume": accepted["volume"], "currency": listing["trading_currency"],
            "adjustment_status": "eodhd_adjusted_ohlc_scaled", "source_file": accepted["source_file"], "ingested_at_utc": now,
        }
    )
    metrics = pd.DataFrame(
        {
            "provider_symbol": listing["provider_symbol"], "date": accepted["date"], "raw_close": accepted["close"],
            "volume": accepted["volume"], "dollar_volume": accepted["close"] * accepted["volume"],
            "adjustment_factor": factor, "source_file": accepted["source_file"],
        }
    )
    return bars, metrics, rejected


def build_curated_frames(root: Path, memberships: pd.DataFrame) -> CuratedFrames:
    securities, listings = build_reference_frames(memberships)
    selected = memberships[memberships["membership_status"].eq("selected_candidate")].copy()
    bars = []
    raw_metrics = []
    rejected = []
    for _, listing in listings.iterrows():
        symbol_rows = selected[selected["eodhd_symbol"].eq(listing["provider_symbol"])]
        symbol_bars, symbol_metrics, symbol_rejected = _curate_symbol(root, listing, symbol_rows)
        if not symbol_bars.empty:
            bars.append(symbol_bars)
        if not symbol_metrics.empty:
            raw_metrics.append(symbol_metrics)
        if not symbol_rejected.empty:
            rejected.append(symbol_rejected)
    return CuratedFrames(
        securities, listings, pd.concat(bars, ignore_index=True) if bars else pd.DataFrame(),
        pd.concat(raw_metrics, ignore_index=True) if raw_metrics else pd.DataFrame(),
        pd.concat(rejected, ignore_index=True) if rejected else pd.DataFrame(),
    )


def validate_quality_report(path: Path, *, allow_partial: bool) -> str:
    summary_path = path / "summary.json"
    quality_path = path / "symbol_quality.parquet"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    quality = pd.read_parquet(quality_path)
    if summary.get("partial_scan") and not allow_partial:
        raise RuntimeError("Refusing production materialization from a partial quality report.")
    blocked = quality[quality["status"].isin(QUALITY_BLOCKING_STATUSES)]
    if not blocked.empty and not allow_partial:
        raise RuntimeError(f"Refusing materialization with {len(blocked)} unresolved price quality failures.")
    return sha256_file(summary_path)


def _copy_frame(cursor: Any, table: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows([["\\N" if pd.isna(value) else value for value in row] for row in frame.itertuples(index=False, name=None)])
    stream.seek(0)
    cursor.copy_expert(f"COPY {table} ({', '.join(frame.columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", stream)


def _upsert_securities(cursor: Any, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    cursor.execute("CREATE TEMP TABLE eodhd_security_stage (LIKE securities INCLUDING DEFAULTS) ON COMMIT DROP")
    _copy_frame(cursor, "eodhd_security_stage", frame)
    updates = [
        "isin", "name", "security_type", "country", "currency_primary", "source_last_seen",
        "active_flag_current", "updated_at_utc",
    ]
    cursor.execute(
        f"INSERT INTO securities ({', '.join(frame.columns)}) SELECT {', '.join(frame.columns)} FROM eodhd_security_stage "
        "ON CONFLICT (security_id) DO UPDATE SET "
        + ", ".join(f"{column} = EXCLUDED.{column}" for column in updates)
    )
    cursor.execute("DROP TABLE eodhd_security_stage")


def build_adjustment_jump_audit(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return pd.DataFrame(columns=["provider_symbol", "date", "adjustment_factor", "previous_adjustment_factor", "has_factor_jump"])
    audit = metrics[["provider_symbol", "date", "adjustment_factor"]].copy().sort_values(["provider_symbol", "date"])
    audit["previous_adjustment_factor"] = audit.groupby("provider_symbol")["adjustment_factor"].shift()
    audit["has_factor_jump"] = audit["previous_adjustment_factor"].notna() & audit["adjustment_factor"].ne(audit["previous_adjustment_factor"])
    return audit[audit["has_factor_jump"]].reset_index(drop=True)


def materialize_curated(
    root: Path | None,
    *, universe_name: str, build_id: str = "latest", memberships_file: Path | None = None,
    quality_report: Path, allow_partial: bool = False, output_root: Path = Path("derived/reports/eodhd/materialization"),
) -> dict[str, Any]:
    resolved_root = resolve_root(root)
    resolved_build_id, memberships = (
        load_memberships_file(memberships_file, build_id=build_id) if memberships_file
        else load_persisted_memberships(universe_name, build_id=build_id)
    )
    quality_sha = validate_quality_report(quality_report, allow_partial=allow_partial)
    securities, listings = build_reference_frames(memberships)
    selected = memberships[memberships["membership_status"].eq("selected_candidate")].copy()
    run_id = uuid.uuid4().hex
    summary = {
        "run_id": run_id, "build_id": resolved_build_id, "universe_name": universe_name,
        "security_count": len(securities), "listing_count": len(listings),
        "bar_count": 0, "raw_metric_count": 0, "rejected_row_count": 0,
    }
    rejected_frames = []
    audit_frames = []
    with psycopg2.connect(**get_database_config()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM stock_momentum_panels WHERE profile = 'eodhd_us_v1'")
            cursor.execute("DELETE FROM equity_eligibility WHERE provider = %s", (PROVIDER,))
            cursor.execute("DELETE FROM equity_prices_eur WHERE provider = %s", (PROVIDER,))
            cursor.execute("DELETE FROM equity_price_bars WHERE provider = %s", (PROVIDER,))
            cursor.execute("DELETE FROM eodhd.curated_price_metrics")
            cursor.execute("DELETE FROM listings WHERE provider = %s", (PROVIDER,))
            cursor.execute("DELETE FROM securities WHERE source_first_seen = %s", (PROVIDER,))
            _upsert_securities(cursor, securities)
            _copy_frame(cursor, "listings", listings)
            for _, listing in listings.iterrows():
                symbol_rows = selected[selected["eodhd_symbol"].eq(listing["provider_symbol"])]
                bars, metrics, rejected = _curate_symbol(resolved_root, listing, symbol_rows)
                _copy_frame(cursor, "equity_price_bars", bars)
                _copy_frame(cursor, "eodhd.curated_price_metrics", metrics)
                summary["bar_count"] += len(bars)
                summary["raw_metric_count"] += len(metrics)
                summary["rejected_row_count"] += len(rejected)
                if not rejected.empty:
                    rejected_frames.append(rejected)
                jumps = build_adjustment_jump_audit(metrics)
                if not jumps.empty:
                    audit_frames.append(jumps)
            cursor.execute(
                "INSERT INTO eodhd.curated_materialization_runs "
                "(run_id, build_id, universe_name, quality_report_sha256, status, summary_json, started_at, finished_at) "
                "VALUES (%s, %s, %s, %s, 'complete', %s, NOW(), NOW())",
                (run_id, resolved_build_id, universe_name, quality_sha, json.dumps(summary)),
            )
    output_dir = output_root / universe_name / f"build_id={resolved_build_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rejected = pd.concat(rejected_frames, ignore_index=True) if rejected_frames else pd.DataFrame()
    audit = pd.concat(audit_frames, ignore_index=True) if audit_frames else build_adjustment_jump_audit(pd.DataFrame())
    rejected.to_csv(output_dir / "rejected_rows.csv", index=False)
    audit.to_csv(output_dir / "adjustment_jump_audit.csv", index=False)
    return summary
