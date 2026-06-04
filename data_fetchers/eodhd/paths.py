"""EODHD archive path helpers and atomic file writes."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from db_utils.config import get_eodhd_archive_root

from .parquet_schema import table_for_write


def resolve_root(root: Path | None) -> Path:
    if root is not None:
        return root.expanduser()
    return get_eodhd_archive_root()


def sanitize_path_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", str(value))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_parquet(df: pd.DataFrame, path: Path, *, dataset: str | None = None) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=path.name, suffix=".tmp", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if dataset is not None:
            pq.write_table(table_for_write(df, dataset), tmp_path, compression="zstd")
        else:
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


def atomic_write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=path.name, suffix=".tmp", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(frame.to_csv(index=False), path)


def symbol_changes_path(root: Path, snapshot_date: str) -> Path:
    return root / "metadata" / "symbol_changes" / f"snapshot_date={snapshot_date}" / "symbol_changes.parquet"


def symbol_list_part_path(root: Path, snapshot_date: str, exchange: str, type_value: str | None, is_delisted: bool) -> Path:
    return (
        root
        / "metadata"
        / "symbol_lists_parts"
        / f"snapshot_date={snapshot_date}"
        / f"exchange={sanitize_path_component(exchange)}"
        / f"delisted={1 if is_delisted else 0}"
        / f"type={sanitize_path_component(type_value or 'ALL')}"
        / "symbols.parquet"
    )


def dataset_output_path(root: Path, dataset: str, exchange_code: str, full_symbol: str, is_delisted: bool) -> Path:
    base = root / ("events" if dataset in {"dividends", "splits"} else "prices") / dataset
    return base / f"exchange={sanitize_path_component(exchange_code)}" / f"delisted={1 if is_delisted else 0}" / f"{sanitize_path_component(full_symbol)}.parquet"


def raw_output_path(root: Path, dataset: str, exchange_code: str, full_symbol: str, is_delisted: bool) -> Path:
    return (
        root
        / "raw"
        / f"{dataset}_json"
        / f"exchange={sanitize_path_component(exchange_code)}"
        / f"delisted={1 if is_delisted else 0}"
        / f"{sanitize_path_component(full_symbol)}.json.gz"
    )


def latest_universe_path(root: Path) -> Path | None:
    base = root / "metadata" / "symbol_lists"
    if not base.exists():
        return None
    paths = sorted(base.glob("snapshot_date=*/symbols.parquet"), reverse=True)
    return paths[0] if paths else None
