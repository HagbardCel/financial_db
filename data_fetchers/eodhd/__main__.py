from __future__ import annotations

import argparse
import sys
from pathlib import Path

from db_utils.config import load_project_environment

from . import downloader
from .ingestion import ALL_DATASETS, METADATA_DATASETS, ingest
from .materialization import materialize_curated
from .price_quality import build_price_quality_report
from .reconcile import reconcile_state
from .reporting import build_metadata_report
from .universes import build_universe, persist_universe_build, write_universe_report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args and args[0] in {"download", "refresh", "ingest", "report", "universes", "prices", "reconcile-state"} else "download"
    if command in {"download", "refresh"}:
        return downloader.main(args)
    parser = argparse.ArgumentParser(prog=f"python -m data_fetchers.eodhd {command}")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--env-file", type=Path)
    if command == "ingest":
        parser.add_argument("scope", nargs="?", choices=["metadata", "all"], default="metadata")
        parser.add_argument("--confirm-all-datasets", action="store_true")
        parser.add_argument("--batch-rows", type=int, default=10_000)
        parsed = parser.parse_args(args)
        load_project_environment(parsed.env_file)
        if parsed.scope == "all" and not parsed.confirm_all_datasets:
            parser.error("ingest all requires --confirm-all-datasets")
        datasets = ALL_DATASETS if parsed.scope == "all" else METADATA_DATASETS
        loaded, skipped = ingest(parsed.root, batch_rows=parsed.batch_rows, datasets=datasets)
        print(f"EODHD {parsed.scope} parquet ingestion complete: loaded={loaded} skipped={skipped}")
        return 0
    if command == "report":
        subcommand = args.pop(0) if args and args[0] == "metadata" else None
        if subcommand != "metadata":
            parser.error("report requires the metadata subcommand")
        parser.add_argument("--snapshot-date", default="latest")
        parser.add_argument("--output-root", type=Path, default=Path("derived/reports/eodhd/metadata"))
        parsed = parser.parse_args(args)
        load_project_environment(parsed.env_file)
        report = build_metadata_report(parsed.root, snapshot_date=parsed.snapshot_date, output_root=parsed.output_root)
        print(f"EODHD metadata report written: snapshot_date={report.snapshot_date} output={report.output_dir}")
        return 0
    if command == "universes":
        subcommand = args.pop(0) if args and args[0] == "build" else None
        if subcommand != "build":
            parser.error("universes requires the build subcommand")
        parser.add_argument("--config", type=Path, default=Path("config/eodhd_universes.toml"))
        parser.add_argument("--snapshot-date", default="latest")
        parser.add_argument("--universe", required=True)
        parser.add_argument("--output-root", type=Path, default=Path("derived/reports/eodhd/universes"))
        parser.add_argument("--no-db", action="store_true")
        parsed = parser.parse_args(args)
        load_project_environment(parsed.env_file)
        build = build_universe(parsed.root, universe_name=parsed.universe, snapshot_date=parsed.snapshot_date, config_path=parsed.config)
        output_dir = write_universe_report(build, output_root=parsed.output_root)
        if not parsed.no_db:
            persist_universe_build(build, config_path=parsed.config)
        print(f"EODHD universe built: build_id={build.build_id} output={output_dir}")
        return 0
    if command == "prices":
        subcommand = args.pop(0) if args and args[0] in {"scan-quality", "materialize-curated"} else None
        if subcommand is None:
            parser.error("prices requires the scan-quality or materialize-curated subcommand")
        parser.add_argument("--universe", required=True)
        parser.add_argument("--build-id", default="latest")
        parser.add_argument("--memberships-file", type=Path)
        default_output_root = Path("derived/reports/eodhd/materialization") if subcommand == "materialize-curated" else Path("derived/reports/eodhd/price_quality")
        parser.add_argument("--output-root", type=Path, default=default_output_root)
        if subcommand == "materialize-curated":
            parser.add_argument("--quality-report", type=Path, required=True)
            parser.add_argument("--allow-partial", action="store_true")
            parsed = parser.parse_args(args)
            load_project_environment(parsed.env_file)
            summary = materialize_curated(
                parsed.root, universe_name=parsed.universe, build_id=parsed.build_id,
                memberships_file=parsed.memberships_file, quality_report=parsed.quality_report,
                allow_partial=parsed.allow_partial, output_root=parsed.output_root,
            )
            print(f"EODHD curated prices materialized: build_id={summary['build_id']} bars={summary['bar_count']}")
            return 0
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--max-symbols", type=int)
        parsed = parser.parse_args(args)
        load_project_environment(parsed.env_file)
        report = build_price_quality_report(
            parsed.root,
            universe_name=parsed.universe,
            build_id=parsed.build_id,
            memberships_file=parsed.memberships_file,
            output_root=parsed.output_root,
            workers=parsed.workers,
            max_symbols=parsed.max_symbols,
        )
        print(f"EODHD price quality report written: build_id={report.build_id} output={report.output_dir}")
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
