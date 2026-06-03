"""Backward-compatible re-exports for the EODHD downloader package."""

from __future__ import annotations

from .cli import FULL_ARCHIVE_SCOPE_OPTIONS, apply_full_archive_preset, main, parse_args
from .client import (
    ApiLimits,
    EntitlementDenied,
    NonRetryableAPIError,
    QuotaExceeded,
    RateLimitedEODHDClient,
    redact_sensitive,
    resolve_api_token,
)
from .discovery import build_exchange_codes, build_universe, discover_symbol_universe, refresh_symbol_changes
from .download import (
    WorkItem,
    download_dataset_concurrent,
    download_one_item,
    estimate_calls,
    plan_work_items,
    should_attempt_corporate_actions,
    write_counts_snapshot,
    write_dataset_rows,
)
from .normalize import (
    normalize_eod_df,
    normalize_event_df,
    normalize_exchange_df,
    normalize_symbol_changes_df,
    normalize_symbol_df,
)
from .paths import (
    atomic_write_json_gz,
    atomic_write_parquet,
    dataset_output_path,
    latest_universe_path,
    raw_output_path,
    resolve_root,
    sha256_file,
    symbol_changes_path,
    symbol_list_part_path,
)
from .state import SQLiteState

__all__ = [
    "FULL_ARCHIVE_SCOPE_OPTIONS",
    "ApiLimits",
    "EntitlementDenied",
    "NonRetryableAPIError",
    "QuotaExceeded",
    "RateLimitedEODHDClient",
    "SQLiteState",
    "WorkItem",
    "apply_full_archive_preset",
    "atomic_write_json_gz",
    "atomic_write_parquet",
    "build_exchange_codes",
    "build_universe",
    "dataset_output_path",
    "discover_symbol_universe",
    "download_dataset_concurrent",
    "download_one_item",
    "estimate_calls",
    "latest_universe_path",
    "main",
    "normalize_eod_df",
    "normalize_event_df",
    "normalize_exchange_df",
    "normalize_symbol_changes_df",
    "normalize_symbol_df",
    "parse_args",
    "plan_work_items",
    "raw_output_path",
    "redact_sensitive",
    "refresh_symbol_changes",
    "resolve_api_token",
    "resolve_root",
    "sha256_file",
    "should_attempt_corporate_actions",
    "symbol_changes_path",
    "symbol_list_part_path",
    "write_counts_snapshot",
    "write_dataset_rows",
]
