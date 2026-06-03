"""EODHD per-symbol dataset download orchestration."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from .client import EntitlementDenied, NonRetryableAPIError, QuotaExceeded, RateLimitedEODHDClient, redact_sensitive
from .common import UTC
from .normalize import normalize_eod_df, normalize_event_df
from .paths import atomic_write_json_gz, atomic_write_parquet, dataset_output_path, raw_output_path
from .state import SQLiteState


def should_attempt_corporate_actions(
    row: pd.Series,
    scope: str,
    *,
    corporate_action_eligible_types: frozenset[str],
) -> bool:
    if scope == "all":
        return True
    if scope == "none":
        return False
    exchange_code = str(row.get("exchange_code", "")).upper()
    if exchange_code in {"FOREX", "CC", "GBOND", "MONEY"}:
        return False
    typ = str(row.get("type", "")).strip().lower()
    return typ in corporate_action_eligible_types or typ == ""


def write_dataset_rows(
    *,
    dataset: str,
    rows: list[dict[str, Any]],
    root: Path,
    exchange_code: str,
    full_symbol: str,
    is_delisted: bool,
    normalize_fn: Callable[..., pd.DataFrame],
    raw_json: bool,
    state: SQLiteState,
) -> None:
    retrieved_at = dt.datetime.now(UTC).isoformat(timespec="seconds")
    if raw_json:
        atomic_write_json_gz(rows, raw_output_path(root, dataset, exchange_code, full_symbol, is_delisted))

    if not rows:
        state.mark_dataset(
            dataset=dataset,
            exchange_code=exchange_code,
            full_symbol=full_symbol,
            is_delisted=is_delisted,
            status="empty",
            rows=0,
            retrieved_at=retrieved_at,
        )
        return

    df = normalize_fn(
        rows,
        full_symbol=full_symbol,
        exchange_code=exchange_code,
        is_delisted=is_delisted,
        retrieved_at=retrieved_at,
    )
    if df.empty:
        state.mark_dataset(
            dataset=dataset,
            exchange_code=exchange_code,
            full_symbol=full_symbol,
            is_delisted=is_delisted,
            status="empty",
            rows=0,
            retrieved_at=retrieved_at,
        )
        return

    out = dataset_output_path(root, dataset, exchange_code, full_symbol, is_delisted)
    bytes_written, sha = atomic_write_parquet(df, out)
    state.mark_dataset(
        dataset=dataset,
        exchange_code=exchange_code,
        full_symbol=full_symbol,
        is_delisted=is_delisted,
        status="done",
        rows=len(df),
        bytes_written=bytes_written,
        sha256=sha,
        file_path=state.relative_file_path(out),
        retrieved_at=retrieved_at,
    )


@dataclasses.dataclass(frozen=True)
class WorkItem:
    dataset: str
    exchange_code: str
    full_symbol: str
    is_delisted: bool


def plan_work_items(
    *,
    dataset: str,
    universe: pd.DataFrame,
    state: SQLiteState,
    refresh_after_days: Optional[int],
    force: bool,
    max_symbols: Optional[int],
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
) -> tuple[list[WorkItem], dict[str, int]]:
    rows = universe.drop_duplicates(subset=["exchange_code", "full_symbol", "is_delisted"]).sort_values(
        ["exchange_code", "full_symbol", "is_delisted"]
    )
    if dataset in {"dividends", "splits"}:
        mask = rows.apply(
            lambda r: should_attempt_corporate_actions(
                r, corporate_actions_scope, corporate_action_eligible_types=corporate_action_eligible_types
            ),
            axis=1,
        )
        rows = rows[mask]
    if max_symbols is not None:
        rows = rows.head(max_symbols)

    fresh_skipped = 0
    missing_or_incomplete: list[WorkItem] = []
    stale: list[WorkItem] = []
    forced: list[WorkItem] = []

    for rec in rows.itertuples(index=False):
        item = WorkItem(
            dataset=dataset,
            exchange_code=str(rec.exchange_code),
            full_symbol=str(rec.full_symbol),
            is_delisted=bool(rec.is_delisted),
        )
        if force:
            forced.append(item)
            continue
        state_name = state.completion_state(dataset, item.full_symbol, item.is_delisted, refresh_after_days)
        if state_name == "fresh_complete":
            fresh_skipped += 1
        elif state_name == "stale_complete":
            stale.append(item)
        else:
            missing_or_incomplete.append(item)

    items = forced if force else missing_or_incomplete + stale
    stats = {
        "total_candidates": int(len(rows)),
        "fresh_skipped": fresh_skipped,
        "missing_or_incomplete": len(missing_or_incomplete),
        "stale_to_refresh": len(stale),
        "forced": len(forced),
        "planned": len(items),
    }
    return items, stats


def download_one_item(
    *,
    client: RateLimitedEODHDClient,
    state: SQLiteState,
    root: Path,
    item: WorkItem,
    start: Optional[str],
    end: Optional[str],
    raw_json: bool,
) -> tuple[str, str]:
    getter = {
        "eod_daily": client.get_eod_history,
        "dividends": client.get_dividends,
        "splits": client.get_splits,
    }[item.dataset]
    normalizer = {
        "eod_daily": normalize_eod_df,
        "dividends": lambda rows, **kw: normalize_event_df(rows, dataset="dividends", **kw),
        "splits": lambda rows, **kw: normalize_event_df(rows, dataset="splits", **kw),
    }[item.dataset]

    try:
        rows = getter(item.full_symbol, start, end)
        write_dataset_rows(
            dataset=item.dataset,
            rows=rows,
            root=root,
            exchange_code=item.exchange_code,
            full_symbol=item.full_symbol,
            is_delisted=item.is_delisted,
            normalize_fn=normalizer,
            raw_json=raw_json,
            state=state,
        )
        return item.full_symbol, "done_or_empty"
    except QuotaExceeded as exc:
        state.mark_dataset(
            dataset=item.dataset,
            exchange_code=item.exchange_code,
            full_symbol=item.full_symbol,
            is_delisted=item.is_delisted,
            status="quota_deferred",
            error=str(exc)[:2000],
        )
        state.log_event(
            "WARNING",
            "quota_exceeded_during_dataset",
            {"dataset": item.dataset, "symbol": item.full_symbol, "error": redact_sensitive(exc)},
        )
        raise
    except EntitlementDenied as exc:
        state.mark_dataset(
            dataset=item.dataset,
            exchange_code=item.exchange_code,
            full_symbol=item.full_symbol,
            is_delisted=item.is_delisted,
            status="not_entitled",
            error=str(exc)[:2000],
        )
        return item.full_symbol, "not_entitled"
    except NonRetryableAPIError as exc:
        state.mark_dataset(
            dataset=item.dataset,
            exchange_code=item.exchange_code,
            full_symbol=item.full_symbol,
            is_delisted=item.is_delisted,
            status="non_retryable",
            error=str(exc)[:2000],
        )
        return item.full_symbol, "non_retryable"
    except Exception as exc:
        state.mark_dataset(
            dataset=item.dataset,
            exchange_code=item.exchange_code,
            full_symbol=item.full_symbol,
            is_delisted=item.is_delisted,
            status="failed",
            error=str(exc)[:2000],
        )
        return item.full_symbol, "failed"


def write_counts_snapshot(state: SQLiteState, root: Path, snapshot_date: str, label: str = "download_state_counts") -> None:
    counts = state.dataset_counts()
    out = root / "metadata" / "estimates" / f"snapshot_date={snapshot_date}" / f"{label}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_parquet(counts, out)
        logging.info("State counts written: %s", out)
    except Exception:
        csv_out = out.with_suffix(".csv")
        counts.to_csv(csv_out, index=False)
        logging.warning("Could not write state counts as Parquet; wrote CSV instead: %s", csv_out)


def download_dataset_concurrent(
    *,
    dataset: str,
    client: RateLimitedEODHDClient,
    state: SQLiteState,
    root: Path,
    universe: pd.DataFrame,
    start: Optional[str],
    end: Optional[str],
    max_symbols: Optional[int],
    force: bool,
    raw_json: bool,
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
    refresh_after_days: Optional[int],
    concurrency: int,
    progress_every: int,
    snapshot_date: str,
) -> None:
    items, plan_stats = plan_work_items(
        dataset=dataset,
        universe=universe,
        state=state,
        refresh_after_days=refresh_after_days,
        force=force,
        max_symbols=max_symbols,
        corporate_actions_scope=corporate_actions_scope,
        corporate_action_eligible_types=corporate_action_eligible_types,
    )
    logging.info("%s plan: %s", dataset, json.dumps(plan_stats, sort_keys=True))
    if not items:
        return

    counts = {"done_or_empty": 0, "failed": 0, "not_entitled": 0, "non_retryable": 0}
    submitted = 0
    completed = 0
    quota_exc: Optional[BaseException] = None
    start_t = time.monotonic()
    max_workers = max(1, int(concurrency))
    in_flight: set[Future[tuple[str, str]]] = set()
    iterator = iter(items)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"eodhd-{dataset}") as executor:
        def submit_until_full() -> None:
            nonlocal submitted
            while len(in_flight) < max_workers:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                future = executor.submit(
                    download_one_item,
                    client=client,
                    state=state,
                    root=root,
                    item=item,
                    start=start,
                    end=end,
                    raw_json=raw_json,
                )
                in_flight.add(future)
                submitted += 1

        submit_until_full()
        while in_flight:
            done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    _symbol, status = fut.result()
                    counts[status] = counts.get(status, 0) + 1
                    completed += 1
                except QuotaExceeded as exc:
                    quota_exc = exc
                    completed += 1
                except Exception as exc:
                    logging.exception("Unexpected worker failure in %s: %s", dataset, redact_sensitive(exc))
                    counts["failed"] = counts.get("failed", 0) + 1
                    completed += 1

            if completed % max(1, progress_every) == 0 or quota_exc is not None:
                elapsed = max(0.001, time.monotonic() - start_t)
                rate = completed / elapsed * 60.0
                calls_today, requests_today = state.get_today_usage()
                logging.info(
                    "%s progress completed=%s/%s submitted=%s in_flight=%s rate=%.1f items/min counts=%s api_calls_today=%s requests_today=%s",
                    dataset,
                    completed,
                    len(items),
                    submitted,
                    len(in_flight),
                    rate,
                    json.dumps(counts, sort_keys=True),
                    calls_today,
                    requests_today,
                )
                write_counts_snapshot(state, root, snapshot_date, label=f"download_state_counts_{dataset}")

            if quota_exc is not None:
                for pending in in_flight:
                    pending.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                raise quota_exc

            submit_until_full()

    elapsed = max(0.001, time.monotonic() - start_t)
    logging.info(
        "%s finished completed=%s planned=%s elapsed=%.1fs counts=%s",
        dataset,
        completed,
        len(items),
        elapsed,
        json.dumps(counts, sort_keys=True),
    )
    write_counts_snapshot(state, root, snapshot_date, label=f"download_state_counts_{dataset}")


def estimate_calls(
    universe: pd.DataFrame,
    *,
    prices: bool,
    dividends: bool,
    splits: bool,
    corporate_actions_scope: str,
    corporate_action_eligible_types: frozenset[str],
    max_api_calls_per_day: int,
) -> dict[str, Any]:
    deduped = universe.drop_duplicates(subset=["full_symbol", "is_delisted"])
    n_symbols = int(len(deduped))
    ca_mask = (
        universe.apply(
            lambda r: should_attempt_corporate_actions(
                r, corporate_actions_scope, corporate_action_eligible_types=corporate_action_eligible_types
            ),
            axis=1,
        )
        if not universe.empty
        else pd.Series(dtype=bool)
    )
    ca_symbols = int(len(universe[ca_mask].drop_duplicates(subset=["full_symbol", "is_delisted"]))) if not universe.empty else 0

    def bundle(p: bool, d: bool, s: bool) -> dict[str, int | None]:
        price_calls = n_symbols if p else 0
        div_calls = ca_symbols if d else 0
        split_calls = ca_symbols if s else 0
        total = price_calls + div_calls + split_calls
        return {
            "price_api_calls_estimate": price_calls,
            "dividend_api_calls_estimate": div_calls,
            "split_api_calls_estimate": split_calls,
            "total_download_api_calls_estimate_excluding_metadata": total,
            "minimum_paid_days_at_configured_daily_budget": (total + max_api_calls_per_day - 1) // max_api_calls_per_day
            if max_api_calls_per_day
            else None,
            "minimum_paid_days_at_100k_per_day": (total + 99_999) // 100_000,
        }

    selected = bundle(prices, dividends, splits)
    potential = bundle(True, True, True)
    return {
        "symbols_total": n_symbols,
        "symbols_corporate_action_attempts": ca_symbols,
        "selected_download_flags": {
            "download_prices": prices,
            "download_dividends": dividends,
            "download_splits": splits,
            "corporate_actions_scope": corporate_actions_scope,
        },
        **selected,
        "selected_download_estimate": selected,
        "potential_full_eod_plan_estimate": potential,
    }
