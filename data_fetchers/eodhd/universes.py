from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
from psycopg2 import extras

from db_utils.config import get_database_config
from .common import is_valid_isin
from .paths import resolve_root, sha256_file
from .reporting import metadata_paths, resolve_snapshot_date
from .settings import DEFAULT_CONFIG_PATH, config_for_universe, load_eodhd_config


@dataclass(frozen=True)
class UniverseBuild:
    build_id: str
    universe_name: str
    snapshot_date: str
    memberships: pd.DataFrame
    summary: dict[str, Any]


def _config_json(config: dict[str, Any]) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def _build_id(universe_name: str, snapshot_date: str, config: dict[str, Any], paths: tuple[Path, Path]) -> str:
    payload = "|".join(
        [universe_name, snapshot_date, _config_json(config), *(sha256_file(path) for path in paths)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _exclusion_reason(row: pd.Series, definition: dict[str, Any]) -> str | None:
    if row["exchange_code"] not in definition["include_exchange_codes"]:
        return "excluded_exchange_not_in_universe"
    if str(row.get("type", "")).strip() not in definition["include_instrument_types"]:
        return "excluded_wrong_instrument_type"
    venue = str(row.get("exchange", "")).strip()
    if venue in definition["exclude_provider_venues"]:
        return "excluded_otc_venue"
    if venue not in definition["allow_provider_venues"]:
        return "manual_review_provider_venue"
    name = str(row.get("name", ""))
    if pd.Series([name]).str.contains(definition["adr_name_regex"], regex=True, na=False).iloc[0]:
        return "excluded_adr"
    return None


def build_universe(
    root: Path | None,
    *,
    universe_name: str,
    snapshot_date: str = "latest",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> UniverseBuild:
    resolved_root = resolve_root(root)
    resolved_date = resolve_snapshot_date(resolved_root, snapshot_date)
    paths = metadata_paths(resolved_root, resolved_date)
    cfg = load_eodhd_config(config_path)
    config = {"universes": cfg.universes}
    definition = config_for_universe(cfg, universe_name)
    symbols = pd.read_parquet(paths[1]).copy()
    symbols["isin_valid"] = is_valid_isin(symbols["isin"])
    symbols["identity_key"] = symbols["full_symbol"]
    symbols.loc[symbols["isin_valid"], "identity_key"] = symbols.loc[symbols["isin_valid"], "isin"]
    symbols["membership_status"] = symbols.apply(lambda row: _exclusion_reason(row, definition), axis=1)
    symbols["selection_reason"] = pd.NA

    eligible = symbols["membership_status"].isna()
    symbols.loc[eligible, "membership_status"] = "selected_candidate"
    preferences = {venue: rank for rank, venue in enumerate(definition["provider_venue_preference"])}
    symbols["_venue_rank"] = symbols["exchange"].map(preferences).fillna(len(preferences))
    symbols["_delisted_rank"] = symbols["is_delisted"].astype(int)

    listing_candidates = symbols[eligible & symbols["isin_valid"]].drop_duplicates("full_symbol")
    grouped = listing_candidates.groupby("isin", sort=True)
    for _, group in grouped:
        if len(group) < 2:
            continue
        ranked = group.sort_values(["_venue_rank", "_delisted_rank", "full_symbol"])
        selected_symbol = ranked.iloc[0]["full_symbol"]
        rejected_symbols = set(ranked.iloc[1:]["full_symbol"])
        symbols.loc[symbols["full_symbol"].eq(selected_symbol), "selection_reason"] = "selected_preferred_exact_isin_listing"
        rejected = symbols["full_symbol"].isin(rejected_symbols)
        symbols.loc[rejected, "membership_status"] = "excluded_duplicate_listing"
        symbols.loc[rejected, "selection_reason"] = "rejected_lower_preference_exact_isin_listing"

    symbols.loc[
        symbols["membership_status"].eq("selected_candidate") & symbols["selection_reason"].isna(),
        "selection_reason",
    ] = "selected_unique_identity"
    build_id = _build_id(universe_name, resolved_date, config, paths)
    memberships = symbols[
        [
            "full_symbol",
            "exchange_code",
            "exchange",
            "isin",
            "isin_valid",
            "identity_key",
            "name",
            "type",
            "currency",
            "is_delisted",
            "membership_status",
            "selection_reason",
        ]
    ].rename(columns={"full_symbol": "eodhd_symbol", "exchange": "provider_exchange_code", "type": "security_type"})
    memberships.insert(0, "build_id", build_id)
    summary = {
        "build_id": build_id,
        "universe_name": universe_name,
        "snapshot_date": resolved_date,
        "symbol_count": int(len(memberships)),
        "selected_candidate_count": int(memberships["membership_status"].eq("selected_candidate").sum()),
        "excluded_duplicate_listing_count": int(memberships["membership_status"].eq("excluded_duplicate_listing").sum()),
        "manual_review_count": int(memberships["membership_status"].str.startswith("manual_review").sum()),
    }
    return UniverseBuild(build_id, universe_name, resolved_date, memberships, summary)


def persist_universe_build(build: UniverseBuild, *, config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    definition = config_for_universe(load_eodhd_config(config_path), build.universe_name)
    rows = [
        [None if pd.isna(value) else value.item() if hasattr(value, "item") else value for value in row]
        for row in build.memberships.itertuples(index=False, name=None)
    ]
    columns = list(build.memberships.columns)
    with psycopg2.connect(**get_database_config()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO eodhd.universe_definitions (universe_name, description, config_json, updated_at) "
                "VALUES (%s, %s, %s, NOW()) ON CONFLICT (universe_name) DO UPDATE SET "
                "description = EXCLUDED.description, config_json = EXCLUDED.config_json, updated_at = NOW()",
                (build.universe_name, definition.get("description"), json.dumps(definition)),
            )
            cursor.execute(
                "INSERT INTO eodhd.universe_builds "
                "(build_id, universe_name, snapshot_date, config_sha256, summary_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (build_id) DO UPDATE SET summary_json = EXCLUDED.summary_json",
                (
                    build.build_id,
                    build.universe_name,
                    build.snapshot_date,
                    hashlib.sha256(_config_json(config).encode("utf-8")).hexdigest(),
                    json.dumps(build.summary),
                ),
            )
            cursor.execute("DELETE FROM eodhd.universe_memberships WHERE build_id = %s", (build.build_id,))
            extras.execute_values(
                cursor,
                f"INSERT INTO eodhd.universe_memberships ({', '.join(columns)}) VALUES %s",
                rows,
                page_size=5_000,
            )


def write_universe_report(
    build: UniverseBuild,
    *,
    output_root: Path = Path("derived/reports/eodhd/universes"),
) -> Path:
    output_dir = output_root / build.universe_name / f"build_id={build.build_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(build.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    build.memberships.to_csv(output_dir / "memberships.csv", index=False)
    return output_dir
