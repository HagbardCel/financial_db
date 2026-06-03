"""EODHD symbol-list discovery and metadata refresh."""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .client import EntitlementDenied, NonRetryableAPIError, QuotaExceeded, RateLimitedEODHDClient, redact_sensitive
from .normalize import normalize_symbol_changes_df, normalize_symbol_df
from .paths import atomic_write_parquet, symbol_changes_path, symbol_list_part_path


def refresh_symbol_changes(client: RateLimitedEODHDClient, root, snapshot_date: str) -> None:
    key = "symbol-change-history"
    if client.state.is_done("symbol_changes", key, False, 1):
        return
    try:
        rows = client.get_symbol_changes()
    except EntitlementDenied as exc:
        logging.warning("Symbol-change history not entitled; continuing: %s", redact_sensitive(exc))
        client.state.mark_dataset(
            dataset="symbol_changes",
            exchange_code="",
            full_symbol=key,
            is_delisted=False,
            status="not_entitled",
            error=str(exc)[:2000],
        )
        return
    df = normalize_symbol_changes_df(rows, snapshot_date)
    out = symbol_changes_path(root, snapshot_date)
    bytes_written, sha = atomic_write_parquet(df, out)
    client.state.mark_dataset(
        dataset="symbol_changes",
        exchange_code="",
        full_symbol=key,
        is_delisted=False,
        status="done" if len(df) else "empty",
        rows=len(df),
        bytes_written=bytes_written,
        sha256=sha,
        file_path=client.state.relative_file_path(out),
    )


def build_exchange_codes(
    exchange_df: pd.DataFrame,
    requested: Optional[list[str]],
    include_virtual_categories: bool,
    *,
    virtual_asset_categories: tuple[str, ...],
) -> list[str]:
    codes = sorted(set(str(c).strip() for c in exchange_df.get("code", pd.Series(dtype=str)).dropna()))
    if requested:
        return sorted(set(x.strip().upper() for x in requested))
    if include_virtual_categories:
        codes = sorted(set(codes).union(virtual_asset_categories))
    return codes


def symbol_list_state_key(exchange: str, type_value: Optional[str], is_delisted: bool) -> str:
    return f"{exchange}|type={type_value or 'ALL'}|delisted={1 if is_delisted else 0}"


def consolidate_symbol_lists(frames: list[pd.DataFrame], root, snapshot_date: str, *, partial: bool) -> pd.DataFrame:
    universe = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if universe.empty:
        return universe
    universe = universe.drop_duplicates(subset=["full_symbol", "is_delisted"], keep="first")
    universe = universe.sort_values(["exchange_code", "full_symbol", "is_delisted"])
    out = root / "metadata" / "symbol_lists" / f"snapshot_date={snapshot_date}" / (
        "symbols_partial.parquet" if partial else "symbols.parquet"
    )
    atomic_write_parquet(universe, out)
    logging.info("Universe %s written: %s (%s rows)", "partial" if partial else "final", out, len(universe))
    return universe


def discover_symbol_universe(
    client: RateLimitedEODHDClient,
    root,
    exchange_codes: list[str],
    type_filters: Optional[list[str]],
    include_delisted: bool,
    snapshot_date: str,
    refresh_after_days: Optional[int],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for exchange in exchange_codes:
        for is_delisted in ([False, True] if include_delisted else [False]):
            request_types: list[Optional[str]] = type_filters if type_filters else [None]
            for type_value in request_types:
                key = symbol_list_state_key(exchange, type_value, is_delisted)
                part_path = symbol_list_part_path(root, snapshot_date, exchange, type_value, is_delisted)
                if client.state.is_done("symbol_list", key, False, refresh_after_days) and part_path.exists():
                    df_cached = pd.read_parquet(part_path)
                    if not df_cached.empty:
                        frames.append(df_cached)
                    logging.info(
                        "Skipping fresh symbol list exchange=%s type=%s delisted=%s",
                        exchange,
                        type_value or "ALL",
                        is_delisted,
                    )
                    continue

                logging.info("Fetching symbol list exchange=%s type=%s delisted=%s", exchange, type_value or "ALL", is_delisted)
                try:
                    rows = client.get_exchange_symbols(exchange, security_type=type_value, delisted=is_delisted)
                except QuotaExceeded as exc:
                    partial_df = consolidate_symbol_lists(frames, root, snapshot_date, partial=True)
                    client.state.mark_dataset(
                        dataset="symbol_list",
                        exchange_code=exchange,
                        full_symbol=key,
                        is_delisted=False,
                        status="quota_deferred",
                        error=str(exc)[:2000],
                    )
                    client.state.log_event(
                        "WARNING",
                        "quota_exceeded_during_symbol_list",
                        {
                            "exchange": exchange,
                            "delisted": is_delisted,
                            "type": type_value,
                            "partial_rows": len(partial_df),
                            "error": redact_sensitive(exc),
                        },
                    )
                    raise
                except EntitlementDenied as exc:
                    logging.warning(
                        "Symbol-list not entitled/access denied; exchange=%s delisted=%s type=%s error=%s",
                        exchange,
                        is_delisted,
                        type_value,
                        redact_sensitive(exc),
                    )
                    client.state.mark_dataset(
                        dataset="symbol_list",
                        exchange_code=exchange,
                        full_symbol=key,
                        is_delisted=False,
                        status="not_entitled",
                        rows=0,
                        error=str(exc)[:2000],
                    )
                    continue
                except NonRetryableAPIError as exc:
                    logging.warning(
                        "Symbol-list non-retryable failure; exchange=%s delisted=%s type=%s error=%s",
                        exchange,
                        is_delisted,
                        type_value,
                        redact_sensitive(exc),
                    )
                    client.state.mark_dataset(
                        dataset="symbol_list",
                        exchange_code=exchange,
                        full_symbol=key,
                        is_delisted=False,
                        status="non_retryable",
                        rows=0,
                        error=str(exc)[:2000],
                    )
                    continue
                except Exception as exc:
                    logging.exception("Symbol-list fetch failed for exchange=%s delisted=%s type=%s", exchange, is_delisted, type_value)
                    client.state.mark_dataset(
                        dataset="symbol_list",
                        exchange_code=exchange,
                        full_symbol=key,
                        is_delisted=False,
                        status="failed",
                        rows=0,
                        error=str(exc)[:2000],
                    )
                    continue

                df = normalize_symbol_df(rows, exchange_code=exchange, is_delisted=is_delisted, snapshot_date=snapshot_date)
                df["request_type_filter"] = type_value or "ALL"
                bytes_written, sha = atomic_write_parquet(df, part_path)
                if not df.empty:
                    frames.append(df)
                client.state.mark_dataset(
                    dataset="symbol_list",
                    exchange_code=exchange,
                    full_symbol=key,
                    is_delisted=False,
                    status="done" if len(df) else "empty",
                    rows=len(df),
                    bytes_written=bytes_written,
                    sha256=sha,
                    file_path=client.state.relative_file_path(part_path),
                )

    universe = consolidate_symbol_lists(frames, root, snapshot_date, partial=False)
    if universe.empty:
        raise RuntimeError("No symbols returned; check exchange access, token, and filters.")
    return universe


# Backward-compatible alias for download-stage symbol discovery.
build_universe = discover_symbol_universe
