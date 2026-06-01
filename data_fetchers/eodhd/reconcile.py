from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


LEGACY_PREFIX = "data/external/eodhd/"


@dataclass(frozen=True)
class ReconcileResult:
    candidates: int
    verified: int
    updated: int
    missing: tuple[str, ...]


def reconcile_state(root: Path, *, state_db: Path | None = None, apply: bool = False) -> ReconcileResult:
    db_path = state_db or root / "state" / "eodhd_all_world_snapshot.sqlite3"
    conn = sqlite3.connect(db_path if apply else f"file:{db_path}?mode=ro&immutable=1", uri=not apply)
    try:
        rows = conn.execute(
            "SELECT dataset, full_symbol, is_delisted, file_path FROM dataset_download_state "
            "WHERE file_path LIKE ?",
            (f"{LEGACY_PREFIX}%",),
        ).fetchall()
        verified: list[tuple[str, str, int, str]] = []
        missing: list[str] = []
        for dataset, full_symbol, is_delisted, old_path in rows:
            relative = str(old_path)[len(LEGACY_PREFIX):]
            if (root / relative).exists():
                verified.append((dataset, full_symbol, int(is_delisted), relative))
            else:
                missing.append(relative)
        if apply:
            conn.executemany(
                "UPDATE dataset_download_state SET file_path = ? "
                "WHERE dataset = ? AND full_symbol = ? AND is_delisted = ?",
                [(relative, dataset, full_symbol, is_delisted) for dataset, full_symbol, is_delisted, relative in verified],
            )
            conn.commit()
        return ReconcileResult(len(rows), len(verified), len(verified) if apply else 0, tuple(missing))
    finally:
        conn.close()
