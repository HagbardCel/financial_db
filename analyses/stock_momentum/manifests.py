from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_manifest(
    source: str,
    local_path: str | Path,
    source_url: Optional[str] = None,
    row_count: Optional[int] = None,
    status: str = "ok",
    notes: Optional[str] = None,
) -> pd.DataFrame:
    path = Path(local_path)
    content = path.read_bytes()
    digest = sha256_bytes(content)
    return pd.DataFrame(
        [
            {
                "manifest_id": f"{source}:{digest[:16]}",
                "source": source,
                "source_url": source_url,
                "local_path": str(path),
                "downloaded_at_utc": utc_now(),
                "sha256": digest,
                "byte_size": len(content),
                "row_count": row_count,
                "status": status,
                "notes": notes,
            }
        ]
    )
