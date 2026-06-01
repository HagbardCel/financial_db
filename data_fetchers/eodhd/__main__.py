from __future__ import annotations

import argparse
import sys
from pathlib import Path

from db_utils.config import load_project_environment

from . import downloader
from .ingestion import ingest
from .reconcile import reconcile_state


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args and args[0] in {"download", "refresh", "ingest", "reconcile-state"} else "download"
    if command in {"download", "refresh"}:
        return downloader.main(args)
    parser = argparse.ArgumentParser(prog=f"python -m data_fetchers.eodhd {command}")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--env-file", type=Path)
    if command == "ingest":
        parser.add_argument("--batch-rows", type=int, default=10_000)
        parsed = parser.parse_args(args)
        load_project_environment(parsed.env_file)
        loaded, skipped = ingest(parsed.root, batch_rows=parsed.batch_rows)
        print(f"EODHD parquet ingestion complete: loaded={loaded} skipped={skipped}")
        return 0
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(args)
    load_project_environment(parsed.env_file)
    root = downloader.resolve_root(parsed.root)
    result = reconcile_state(root, state_db=parsed.state_db, apply=parsed.apply)
    print(f"EODHD state reconciliation: candidates={result.candidates} verified={result.verified} updated={result.updated} missing={len(result.missing)}")
    for path in result.missing:
        print(f"missing: {path}")
    return 1 if result.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
