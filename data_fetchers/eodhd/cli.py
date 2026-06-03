#!/usr/bin/env python3
"""
EODHD All World EOD snapshot downloader CLI.

Entry point: ``python -m data_fetchers.eodhd download`` or ``refresh``.

``refresh`` is an alias for ``download``: both use the full-archive preset when no
scope flags are passed, and honor ``download.refresh_after_days`` from config for
stale symbol/data refresh.

First full bootstrap (paid plan)::

    uv run python -m data_fetchers.eodhd download \\
      --confirm-full-plan-download \\
      --include-delisted \\
      --download-prices --download-dividends --download-splits \\
      --refresh-after-days -1

Weekly refresh after bootstrap::

    uv run python -m data_fetchers.eodhd refresh
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from .client import ApiLimits, QuotaExceeded, RateLimitedEODHDClient, redact_sensitive, resolve_api_token
from .common import UTC, parse_config_path
from .discovery import build_exchange_codes, discover_symbol_universe, refresh_symbol_changes
from .download import download_dataset_concurrent, estimate_calls, write_counts_snapshot
from .normalize import normalize_exchange_df
from .paths import atomic_write_parquet, latest_universe_path, resolve_root
from .settings import DEFAULT_CONFIG_PATH, EodhdConfig, load_eodhd_config
from .state import SQLiteState

FULL_ARCHIVE_SCOPE_OPTIONS = {
    "--confirm-full-plan-download",
    "--exchanges",
    "--exclude-virtual-categories",
    "--type-filters",
    "--include-delisted",
    "--reuse-universe",
    "--metadata-only",
    "--download-prices",
    "--download-dividends",
    "--download-splits",
    "--corporate-actions-scope",
    "--max-symbols",
}


def apply_full_archive_preset(args: argparse.Namespace, argv: Iterable[str], cfg: EodhdConfig) -> argparse.Namespace:
    supplied_options = {str(value).split("=", 1)[0] for value in argv if str(value).startswith("--")}
    scope = cfg.download.scope
    if supplied_options.isdisjoint(FULL_ARCHIVE_SCOPE_OPTIONS):
        args.confirm_full_plan_download = scope.confirm_full_plan_download
        args.include_delisted = scope.include_delisted
        args.download_prices = scope.download_prices
        args.download_dividends = scope.download_dividends
        args.download_splits = scope.download_splits
        args.full_archive_preset = True
    else:
        args.full_archive_preset = False
    return args


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    cfg = load_eodhd_config(parse_config_path(raw_args))
    download = cfg.download
    limits = download.rate_limits
    scope = download.scope

    p = argparse.ArgumentParser(description="Download EODHD All World EOD data with resumable state and bounded concurrency.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--api-token", default=None)
    p.add_argument("--env-file", type=Path, default=None)
    p.add_argument("--from", dest="start", default=download.start)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--confirm-full-plan-download", action="store_true")
    p.add_argument("--exchanges", nargs="*")
    p.add_argument("--exclude-virtual-categories", action="store_true", default=scope.exclude_virtual_categories)
    p.add_argument("--type-filters", nargs="*", default=None)
    p.add_argument("--include-delisted", action="store_true")
    p.add_argument("--reuse-universe", action="store_true")
    p.add_argument("--metadata-only", action="store_true")
    p.add_argument("--download-prices", action="store_true")
    p.add_argument("--download-dividends", action="store_true")
    p.add_argument("--download-splits", action="store_true")
    p.add_argument("--corporate-actions-scope", choices=["eligible", "all", "none"], default=download.corporate_actions_scope)
    p.add_argument("--max-symbols", type=int, default=None)
    p.add_argument(
        "--refresh-after-days",
        type=int,
        default=download.refresh_after_days,
        help="Refresh completed items older than N days. Use -1 to skip completed items forever unless --force.",
    )
    p.add_argument("--force", action="store_true", default=download.force)
    p.add_argument("--raw-json", action="store_true", default=download.raw_json)
    p.add_argument(
        "--concurrency",
        type=int,
        default=download.concurrency,
        help="Bounded worker count for per-symbol downloads. Metadata discovery remains serial.",
    )
    p.add_argument("--http-timeout", type=int, default=download.http_timeout)
    p.add_argument("--connection-pool-size", type=int, default=None)
    p.add_argument("--progress-every", type=int, default=download.progress_every)
    p.add_argument("--max-requests-per-minute", type=int, default=limits.max_requests_per_minute)
    p.add_argument("--max-api-calls-per-day", type=int, default=limits.max_api_calls_per_day)
    p.add_argument("--sleep-on-daily-limit", action="store_true", default=download.sleep_on_daily_limit)
    p.add_argument("--min-seconds-between-requests", type=float, default=limits.min_seconds_between_requests)
    p.add_argument("--state-db", type=Path, default=None)
    p.add_argument("--log-level", default=download.log_level, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(raw_args)
    args.eodhd_config = cfg
    return apply_full_archive_preset(args, raw_args, cfg)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    cfg: EodhdConfig = args.eodhd_config
    scope = cfg.download.scope
    api = cfg.api
    rate_limits = cfg.download.rate_limits
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    if args.full_archive_preset:
        logging.info(
            "No scope-selection arguments supplied; using full archive preset with active and delisted symbols, prices, dividends, and splits."
        )

    if args.type_filters:
        bad = [x for x in args.type_filters if x not in scope.supported_type_filters]
        if bad:
            logging.error("Unsupported type filters: %s. Supported: %s", bad, sorted(scope.supported_type_filters))
            return 2
    if not args.confirm_full_plan_download and not args.exchanges and not args.reuse_universe:
        logging.error("Refusing broad discovery without --confirm-full-plan-download, --exchanges, or --reuse-universe.")
        return 2

    token, token_source = resolve_api_token(args.api_token, args.env_file)
    if not token:
        logging.error("Missing API token. Set EODHD_API_TOKEN in .env or pass --api-token.")
        return 2
    logging.info("Using EODHD API token from %s", token_source)

    try:
        root = resolve_root(args.root)
    except ValueError as exc:
        logging.error("%s", exc)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    state = SQLiteState(args.state_db or root / cfg.paths.state_db, root=root)
    snapshot_date = dt.datetime.now(UTC).date().isoformat()

    try:
        pool_size = args.connection_pool_size or max(10, int(args.concurrency) * 2)
        client = RateLimitedEODHDClient(
            token=token,
            state=state,
            limits=ApiLimits(
                max_requests_per_minute=args.max_requests_per_minute,
                max_api_calls_per_day=args.max_api_calls_per_day,
                min_seconds_between_requests=args.min_seconds_between_requests,
                sleep_on_daily_limit=args.sleep_on_daily_limit,
            ),
            timeout=args.http_timeout,
            pool_size=pool_size,
            api_base=api.base_url,
            symbol_change_start_date=api.symbol_change_start_date,
            default_provider_cooldown_seconds=rate_limits.provider_rate_limit_cooldown_seconds,
            max_provider_cooldown_seconds=rate_limits.max_provider_rate_limit_cooldown_seconds,
        )
        refresh_symbol_changes(client, root, snapshot_date)

        if args.reuse_universe:
            universe_path = latest_universe_path(root)
            if universe_path is None:
                raise RuntimeError("--reuse-universe requested but no metadata/symbol_lists snapshot exists.")
            logging.info("Reusing universe: %s", universe_path)
            universe = pd.read_parquet(universe_path)
        else:
            exchanges = client.get_exchanges()
            exchange_df = normalize_exchange_df(exchanges, snapshot_date=snapshot_date)
            exchange_out = root / "metadata" / "exchanges" / f"snapshot_date={snapshot_date}" / "exchanges.parquet"
            atomic_write_parquet(exchange_df, exchange_out)
            logging.info("Exchange metadata written: %s (%s rows)", exchange_out, len(exchange_df))
            exchange_codes = build_exchange_codes(
                exchange_df,
                requested=args.exchanges,
                include_virtual_categories=not args.exclude_virtual_categories,
                virtual_asset_categories=scope.virtual_asset_categories,
            )
            universe = discover_symbol_universe(
                client,
                root,
                exchange_codes,
                args.type_filters,
                args.include_delisted,
                snapshot_date,
                args.refresh_after_days,
            )

        if not any([args.download_prices, args.download_dividends, args.download_splits]):
            logging.info("No core EOD download flags supplied; defaulting selected estimate/run scope to prices + dividends + splits.")
            args.download_prices = True
            args.download_dividends = True
            args.download_splits = True

        estimate = estimate_calls(
            universe,
            prices=args.download_prices,
            dividends=args.download_dividends,
            splits=args.download_splits,
            corporate_actions_scope=args.corporate_actions_scope,
            corporate_action_eligible_types=scope.corporate_action_eligible_types,
            max_api_calls_per_day=args.max_api_calls_per_day,
        )
        estimate_out = root / "metadata" / "estimates" / f"snapshot_date={snapshot_date}" / "all_world_eod_estimate.json"
        estimate_out.parent.mkdir(parents=True, exist_ok=True)
        estimate_out.write_text(json.dumps(estimate, indent=2, sort_keys=True), encoding="utf-8")
        logging.info("Estimate written: %s", estimate_out)
        logging.info("Estimate: %s", json.dumps(estimate, indent=2, sort_keys=True))

        if args.metadata_only:
            logging.info("Stopping before downloads due to --metadata-only")
            return 0

        common = dict(
            client=client,
            state=state,
            root=root,
            universe=universe,
            start=args.start,
            end=args.end,
            max_symbols=args.max_symbols,
            force=args.force,
            raw_json=args.raw_json,
            corporate_actions_scope=args.corporate_actions_scope,
            corporate_action_eligible_types=scope.corporate_action_eligible_types,
            refresh_after_days=args.refresh_after_days,
            concurrency=args.concurrency,
            progress_every=args.progress_every,
            snapshot_date=snapshot_date,
        )
        if args.download_prices:
            download_dataset_concurrent(dataset="eod_daily", **common)
        if args.download_dividends:
            download_dataset_concurrent(dataset="dividends", **common)
        if args.download_splits:
            download_dataset_concurrent(dataset="splits", **common)

        write_counts_snapshot(state, root, snapshot_date)
        counts = state.dataset_counts()
        failed = counts[counts["status"].eq("failed")]["n"].sum() if not counts.empty else 0
        if failed:
            logging.warning("Run finished with failed items. Re-run without --force to retry failed/missing only. failures=%s", failed)
            return 1
        return 0

    except QuotaExceeded as exc:
        logging.warning(
            "Quota exhausted/local budget reached. State is persisted; rerun the same command later. Error=%s",
            redact_sensitive(exc),
        )
        state.log_event("WARNING", "run_stopped_quota_exceeded", {"error": redact_sensitive(exc)})
        write_counts_snapshot(state, root, snapshot_date, label="download_state_counts_quota_stop")
        return 75
    finally:
        state.close()


if __name__ == "__main__":
    raise SystemExit(main())
