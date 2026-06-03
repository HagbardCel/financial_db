"""Shared helpers for the EODHD package."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Iterable

import pandas as pd

UTC = dt.timezone.utc

from .settings import DEFAULT_CONFIG_PATH, EodhdConfig, load_eodhd_config

ISIN_PATTERN = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"
DEFAULT_STATE_DB_RELATIVE = Path("state/eodhd_all_world_snapshot.sqlite3")


def parse_config_path(argv: Iterable[str]) -> Path:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    pre_args, _ = pre.parse_known_args(list(argv))
    return pre_args.config


def is_valid_isin(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.match(ISIN_PATTERN)


def resolve_state_db_path(
    root: Path,
    cfg: EodhdConfig | None = None,
    *,
    state_db: Path | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> Path:
    if state_db is not None:
        return state_db
    if cfg is None:
        cfg = load_eodhd_config(config_path)
    return root / cfg.paths.state_db


def resolve_snapshot_date(root: Path, snapshot_date: str) -> str:
    if snapshot_date != "latest":
        return snapshot_date
    snapshots = sorted((root / "metadata" / "symbol_lists").glob("snapshot_date=*/symbols.parquet"))
    if not snapshots:
        raise RuntimeError("No consolidated EODHD symbol snapshots found.")
    return snapshots[-1].parent.name.split("=", 1)[1]
