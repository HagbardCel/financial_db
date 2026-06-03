from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from data_fetchers.eodhd import __main__ as eodhd_main
from data_fetchers.eodhd.downloader import (
    ApiLimits,
    EntitlementDenied,
    QuotaExceeded,
    RateLimitedEODHDClient,
    SQLiteState,
    atomic_write_parquet,
    dataset_output_path,
    normalize_eod_df,
    normalize_exchange_df,
    normalize_symbol_df,
    normalize_symbol_changes_df,
    parse_args,
    refresh_symbol_changes,
    redact_sensitive,
    resolve_api_token,
    resolve_root,
    symbol_changes_path,
    symbol_list_part_path,
)
from data_fetchers.eodhd.ingestion import ALL_DATASETS, LOADER_VERSIONS, METADATA_DATASETS, parquet_artifacts, transform
from data_fetchers.eodhd.reconcile import LEGACY_PREFIX, reconcile_state


def test_resolve_root_prefers_explicit_path_and_uses_raw_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    assert resolve_root(None) == tmp_path / "eodhd"
    assert resolve_root(tmp_path / "explicit") == tmp_path / "explicit"
    monkeypatch.delenv("RAW_DATA_DIR")
    with pytest.raises(ValueError, match="RAW_DATA_DIR"):
        resolve_root(None)


def test_resolve_api_token_with_cli_token_still_loads_explicit_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    explicit = tmp_path / "explicit.env"
    explicit.write_text("RAW_DATA_DIR=/tmp/eodhd-raw\n", encoding="utf-8")
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAW_DATA_DIR", raising=False)

    assert resolve_api_token("token", explicit) == ("token", "--api-token")

    assert os.environ["RAW_DATA_DIR"] == "/tmp/eodhd-raw"


def test_reconcile_state_cli_loads_root_env_before_resolving_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / ".env").write_text(f"RAW_DATA_DIR={tmp_path / 'raw'}\n", encoding="utf-8")
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAW_DATA_DIR", raising=False)
    captured: dict[str, Path] = {}

    def fake_reconcile_state(root: Path, *, state_db: Path | None, apply: bool):
        captured["root"] = root
        return type("Result", (), {"candidates": 0, "verified": 0, "updated": 0, "missing": ()})()

    monkeypatch.setattr(eodhd_main, "reconcile_state", fake_reconcile_state)

    assert eodhd_main.main(["reconcile-state", "--apply"]) == 0
    assert captured["root"] == tmp_path / "raw/eodhd"


def test_ingest_cli_loads_root_env_before_ingestion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / ".env").write_text(f"RAW_DATA_DIR={tmp_path / 'raw'}\nPOSTGRES_DB=test\n", encoding="utf-8")
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAW_DATA_DIR", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    captured: dict[str, str] = {}

    def fake_ingest(root: Path | None, *, batch_rows: int, datasets):
        captured["raw_data_dir"] = os.environ["RAW_DATA_DIR"]
        captured["postgres_db"] = os.environ["POSTGRES_DB"]
        captured["datasets"] = tuple(datasets)
        return 0, 0

    monkeypatch.setattr(eodhd_main, "ingest", fake_ingest)

    assert eodhd_main.main(["ingest"]) == 0
    assert captured == {
        "raw_data_dir": str(tmp_path / "raw"),
        "postgres_db": "test",
        "datasets": METADATA_DATASETS,
    }


def test_ingest_all_cli_requires_confirmation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(eodhd_main, "ingest", lambda *args, **kwargs: pytest.fail("ingest should not run"))
    with pytest.raises(SystemExit):
        eodhd_main.main(["ingest", "all"])


def test_ingest_all_cli_forwards_all_datasets(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_ingest(root, *, batch_rows, datasets):
        captured["datasets"] = tuple(datasets)
        return 0, 0

    monkeypatch.setattr(eodhd_main, "ingest", fake_ingest)
    assert eodhd_main.main(["ingest", "all", "--confirm-all-datasets"]) == 0
    assert captured["datasets"] == ALL_DATASETS


def test_refresh_cli_forwards_bare_command_to_full_archive_preset(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_downloader_main(argv):
        captured["args"] = parse_args(argv)
        return 0

    monkeypatch.setattr(eodhd_main.downloader, "main", fake_downloader_main)

    assert eodhd_main.main(["refresh"]) == 0
    args = captured["args"]
    assert args.full_archive_preset is True
    assert args.include_delisted is True
    assert args.download_prices is True
    assert args.download_dividends is True
    assert args.download_splits is True


def test_storage_paths_remain_backward_compatible(tmp_path: Path):
    assert symbol_list_part_path(tmp_path, "2026-05-31", "US", "stock", True) == tmp_path / "metadata/symbol_lists_parts/snapshot_date=2026-05-31/exchange=US/delisted=1/type=stock/symbols.parquet"
    assert dataset_output_path(tmp_path, "eod_daily", "US", "AAPL.US", False) == tmp_path / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
    assert dataset_output_path(tmp_path, "dividends", "US", "AAPL.US", False) == tmp_path / "events/dividends/exchange=US/delisted=0/AAPL.US.parquet"
    assert symbol_changes_path(tmp_path, "2026-05-31") == tmp_path / "metadata/symbol_changes/snapshot_date=2026-05-31/symbol_changes.parquet"


def test_bare_download_args_apply_full_archive_preset():
    args = parse_args([])
    assert args.full_archive_preset is True
    assert args.confirm_full_plan_download is True
    assert args.include_delisted is True
    assert args.download_prices is True
    assert args.download_dividends is True
    assert args.download_splits is True
    assert args.corporate_actions_scope == "eligible"
    assert args.refresh_after_days == 7
    assert args.raw_json is False
    assert args.min_seconds_between_requests == 0.05
    assert ApiLimits().min_seconds_between_requests == 0.05


def test_operational_args_keep_full_archive_preset(tmp_path: Path):
    args = parse_args(["--root", str(tmp_path), "--concurrency", "3", "--refresh-after-days", "-1", "--raw-json", "--min-seconds-between-requests", "0.2"])
    assert args.full_archive_preset is True
    assert args.include_delisted is True
    assert args.download_prices is True
    assert args.download_dividends is True
    assert args.download_splits is True
    assert args.refresh_after_days == -1
    assert args.raw_json is True
    assert args.min_seconds_between_requests == 0.2


def test_explicit_scope_args_preserve_selective_behavior():
    args = parse_args(["--confirm-full-plan-download", "--download-prices"])
    assert args.full_archive_preset is False
    assert args.download_prices is True
    assert args.download_dividends is False
    assert args.download_splits is False
    assert args.include_delisted is False


def test_atomic_parquet_write_replaces_file(tmp_path: Path):
    path = tmp_path / "nested/data.parquet"
    atomic_write_parquet(pd.DataFrame({"value": [1]}), path)
    atomic_write_parquet(pd.DataFrame({"value": [2]}), path)
    assert pd.read_parquet(path)["value"].tolist() == [2]
    assert not list(path.parent.glob("*.tmp"))


def test_redact_sensitive_hides_tokens():
    assert redact_sensitive("https://example.test?api_token=secret&fmt=json") == "https://example.test?api_token=<REDACTED>&fmt=json"


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status_code: int, *, headers: dict[str, str] | None = None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload
        self.url = "https://eodhd.com/api/test?api_token=secret&fmt=json"
        self.text = "Too Many Requests" if status_code == 429 else json.dumps(payload)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return next(self.responses)


def test_provider_429_retries_after_shared_retry_after_cooldown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    clock = FakeClock()
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.monotonic", clock.monotonic)
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.sleep", clock.sleep)
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, payload=[{"ok": True}])])
    client = RateLimitedEODHDClient("token", state, ApiLimits(), timeout=1, pool_size=1)
    monkeypatch.setattr(client, "session", lambda: session)

    assert client.get_json("test") == [{"ok": True}]
    assert session.calls == 2
    assert clock.sleeps == [7.0]
    assert state.get_today_usage() == (2, 2)
    assert state.conn.execute("SELECT message FROM run_events").fetchall() == [("provider_rate_limit_retry",)]
    state.close()


def test_provider_429_uses_bounded_fallback_cooldown_and_stops_after_five_attempts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    clock = FakeClock()
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.monotonic", clock.monotonic)
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.sleep", clock.sleep)
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)
    session = FakeSession([FakeResponse(429) for _ in range(5)])
    client = RateLimitedEODHDClient("token", state, ApiLimits(), timeout=1, pool_size=1)
    monkeypatch.setattr(client, "session", lambda: session)

    with pytest.raises(QuotaExceeded, match="after 5 attempts"):
        client.get_json("test")
    assert session.calls == 5
    assert clock.sleeps == [60.25] * 4
    assert client._retry_after_seconds("999") == 120.0
    assert state.get_today_usage() == (5, 5)
    assert state.conn.execute("SELECT message, COUNT(*) FROM run_events GROUP BY message ORDER BY message").fetchall() == [
        ("provider_quota_or_rate_limit", 1),
        ("provider_rate_limit_retry", 4),
    ]
    state.close()


def test_provider_remaining_header_schedules_shared_cooldown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    clock = FakeClock()
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.monotonic", clock.monotonic)
    monkeypatch.setattr("data_fetchers.eodhd.downloader.time.sleep", clock.sleep)
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)
    session = FakeSession([
        FakeResponse(200, headers={"X-RateLimit-Remaining": "2"}, payload={"ok": 1}),
        FakeResponse(200, payload={"ok": 2}),
    ])
    client = RateLimitedEODHDClient("token", state, ApiLimits(), timeout=1, pool_size=1)
    monkeypatch.setattr(client, "session", lambda: session)

    assert client.get_json("test") == {"ok": 1}
    assert client.get_json("test") == {"ok": 2}
    assert clock.sleeps == [60.25]
    state.close()


def test_local_daily_budget_stops_before_http_request(tmp_path: Path):
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)
    session = FakeSession([])
    client = RateLimitedEODHDClient("token", state, ApiLimits(max_api_calls_per_day=0), timeout=1, pool_size=1)
    client.session = lambda: session

    with pytest.raises(QuotaExceeded, match="Daily API-call budget"):
        client.get_json("test")
    assert session.calls == 0
    assert state.get_today_usage() == (0, 0)
    state.close()


def test_completion_state_resolves_relative_paths(tmp_path: Path):
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)
    target = tmp_path / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
    target.parent.mkdir(parents=True)
    target.touch()
    state.mark_dataset(dataset="eod_daily", exchange_code="US", full_symbol="AAPL.US", is_delisted=False, status="done", file_path=str(target.relative_to(tmp_path)))
    assert state.completion_state("eod_daily", "AAPL.US", False, -1) == "fresh_complete"
    state.close()


def test_parquet_artifacts_excludes_partial_symbol_snapshots(tmp_path: Path):
    complete = tmp_path / "metadata/symbol_lists/snapshot_date=2026-05-31/symbols.parquet"
    partial = complete.with_name("symbols_partial.parquet")
    complete.parent.mkdir(parents=True)
    complete.touch()
    partial.touch()
    assert list(parquet_artifacts(tmp_path)) == [("symbol_snapshots", complete)]


def test_parquet_artifacts_can_select_metadata_only(tmp_path: Path):
    symbol = tmp_path / "metadata/symbol_lists/snapshot_date=2026-05-31/symbols.parquet"
    price = tmp_path / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
    symbol.parent.mkdir(parents=True)
    price.parent.mkdir(parents=True)
    symbol.touch()
    price.touch()
    assert list(parquet_artifacts(tmp_path, datasets=METADATA_DATASETS)) == [("symbol_snapshots", symbol)]


def test_normalize_symbol_changes():
    frame = normalize_symbol_changes_df([{"ExchangeCode": "US", "OldTicker": "OLD", "NewTicker": "NEW", "Name": "Example", "Date": "2026-01-02"}], "2026-05-31")
    assert frame.iloc[0].to_dict()["old_symbol"] == "OLD"
    assert str(frame.iloc[0]["effective"]) == "2026-01-02"


def test_reference_metadata_preserves_provider_payload_and_maps_typed_columns():
    exchange = normalize_exchange_df(
        [{"Code": "US", "Name": "USA Stocks", "CountryISO2": "US", "CountryISO3": "USA", "FutureField": "kept"}],
        "2026-06-01",
    )
    columns, rows = transform("exchange_snapshots", exchange, "exchanges.parquet")
    mapped = dict(zip(columns, rows[0]))
    assert mapped["country_iso2"] == "US"
    assert mapped["country_iso3"] == "USA"
    assert json.loads(mapped["raw_json"])["FutureField"] == "kept"

    symbol = normalize_symbol_df(
        [{"Code": "AAPL", "Name": "Apple", "Exchange": "NASDAQ", "FutureField": "kept"}],
        exchange_code="US",
        is_delisted=False,
        snapshot_date="2026-06-01",
    )
    columns, rows = transform("symbol_snapshots", symbol, "symbols.parquet")
    mapped = dict(zip(columns, rows[0]))
    assert mapped["exchange_code"] == "US"
    assert mapped["provider_exchange_code"] == "NASDAQ"
    assert json.loads(mapped["raw_json"])["FutureField"] == "kept"


def test_eod_and_symbol_change_parquet_rows_preserve_unknown_provider_fields():
    eod = normalize_eod_df(
        [{"date": "2026-01-02", "close": 11, "future_field": "kept"}],
        full_symbol="AAPL.US",
        exchange_code="US",
        is_delisted=False,
        retrieved_at="2026-01-03T00:00:00+00:00",
    )
    assert json.loads(eod.iloc[0]["provider_payload_json"])["future_field"] == "kept"

    changes = normalize_symbol_changes_df(
        [{"ExchangeCode": "US", "OldTicker": "OLD", "NewTicker": "NEW", "Date": "2026-01-02", "FutureField": "kept"}],
        "2026-06-01",
    )
    assert json.loads(changes.iloc[0]["provider_payload_json"])["FutureField"] == "kept"


def test_loader_versions_avoid_price_reingestion():
    assert LOADER_VERSIONS["exchange_snapshots"] != "legacy"
    assert LOADER_VERSIONS["symbol_snapshots"] != "legacy"
    assert LOADER_VERSIONS["eod_prices"] == "legacy"


def test_symbol_change_entitlement_is_recorded_and_continues(tmp_path: Path):
    state = SQLiteState(tmp_path / "state.sqlite3", root=tmp_path)

    class Client:
        def __init__(self):
            self.state = state

        def get_symbol_changes(self):
            raise EntitlementDenied("not entitled")

    refresh_symbol_changes(Client(), tmp_path, "2026-05-31")
    assert state.get_dataset_record("symbol_changes", "symbol-change-history", False)["status"] == "not_entitled"
    state.close()


def test_reconcile_state_converts_only_verified_legacy_paths(tmp_path: Path):
    root = tmp_path / "eodhd"
    db = root / "state/eodhd_all_world_snapshot.sqlite3"
    db.parent.mkdir(parents=True)
    target = root / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
    target.parent.mkdir(parents=True)
    target.touch()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE dataset_download_state (dataset TEXT, full_symbol TEXT, is_delisted INTEGER, file_path TEXT)")
    conn.execute("INSERT INTO dataset_download_state VALUES (?, ?, ?, ?)", ("eod_daily", "AAPL.US", 0, LEGACY_PREFIX + "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"))
    conn.execute("INSERT INTO dataset_download_state VALUES (?, ?, ?, ?)", ("eod_daily", "MISS.US", 0, LEGACY_PREFIX + "prices/eod_daily/exchange=US/delisted=0/MISS.US.parquet"))
    conn.commit()
    conn.close()
    result = reconcile_state(root, apply=True)
    assert (result.candidates, result.verified, result.updated) == (2, 1, 1)
    conn = sqlite3.connect(db)
    paths = [row[0] for row in conn.execute("SELECT file_path FROM dataset_download_state ORDER BY full_symbol")]
    conn.close()
    assert paths[0] == "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
    assert paths[1].startswith(LEGACY_PREFIX)
