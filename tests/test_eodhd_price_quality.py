from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from data_fetchers.eodhd import __main__ as eodhd_main
from data_fetchers.eodhd.downloader import dataset_output_path
from data_fetchers.eodhd import price_quality
from data_fetchers.eodhd.price_quality import build_price_quality_report, load_memberships_file, load_persisted_memberships


UNIVERSE = "eodhd_us_listed_common_equities_v1"
BUILD_ID = "test-build"


def _membership(symbol: str, *, is_delisted: bool = False, status: str = "selected_candidate") -> dict:
    return {
        "build_id": BUILD_ID,
        "eodhd_symbol": symbol,
        "exchange_code": "US",
        "is_delisted": is_delisted,
        "membership_status": status,
    }


def _write_memberships(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_prices(root: Path, symbol: str, rows: list[dict], *, is_delisted: bool = False) -> Path:
    path = dataset_output_path(root, "eod_daily", "US", symbol, is_delisted)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _price(date: str, close: float, *, adjusted_close: float | None = None, volume: int | None = 100) -> dict:
    return {
        "date": date,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "adjusted_close": close if adjusted_close is None else adjusted_close,
        "volume": volume,
    }


def test_scan_selected_active_and_delisted_candidates_with_quality_metrics(tmp_path: Path):
    memberships = _write_memberships(
        tmp_path / "memberships.csv",
        [
            _membership("A.US"),
            _membership("A.US", is_delisted=True),
            _membership("DUPLICATE.US", status="excluded_duplicate_listing"),
            _membership("MISSING.US"),
        ],
    )
    _write_prices(
        tmp_path,
        "A.US",
        [
            _price("2026-01-02", 10),
            _price("2026-01-02", 10, volume=0),
            _price("bad-date", 0, adjusted_close=0),
            {"date": "2026-01-03", "open": 20, "high": 15, "low": 10, "close": 20, "adjusted_close": None, "volume": None},
        ],
    )
    _write_prices(tmp_path, "A.US", [_price("2020-01-02", 5), _price("2020-01-03", 5)], is_delisted=True)

    report = build_price_quality_report(
        tmp_path,
        universe_name=UNIVERSE,
        memberships_file=memberships,
        output_root=tmp_path / "reports",
        workers=2,
    )

    rows = report.symbol_quality.set_index(["eodhd_symbol", "is_delisted"])
    active = rows.loc[("A.US", False)]
    assert active["status"] == "quality_issues"
    assert active["row_count"] == 4
    assert active["invalid_date_count"] == 1
    assert active["duplicate_date_count"] == 1
    assert active["non_positive_close_count"] == 1
    assert active["inconsistent_ohlc_count"] == 1
    assert active["adjusted_close_coverage_ratio"] == pytest.approx(0.75)
    assert active["non_positive_adjusted_close_count"] == 1
    assert active["null_or_non_positive_volume_ratio"] == pytest.approx(0.5)
    assert active["longest_unchanged_close_run"] == 2
    assert rows.loc[("A.US", True), "status"] == "ok"
    assert rows.loc[("A.US", True), "longest_unchanged_close_run"] == 2
    assert rows.loc[("MISSING.US", False), "status"] == "missing_file"
    assert "DUPLICATE.US" not in set(report.symbol_quality["eodhd_symbol"])
    assert report.summary["status_counts"] == {"missing_file": 1, "ok": 1, "quality_issues": 1}
    assert (report.output_dir / "symbol_quality.parquet").exists()
    assert pd.read_csv(report.output_dir / "missing_price_files.csv")["eodhd_symbol"].tolist() == ["MISSING.US"]


def test_scan_records_unreadable_empty_and_missing_column_files(tmp_path: Path):
    memberships = _write_memberships(
        tmp_path / "memberships.csv",
        [_membership("BAD.US"), _membership("EMPTY.US"), _membership("SCHEMA.US")],
    )
    bad = dataset_output_path(tmp_path, "eod_daily", "US", "BAD.US", False)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not parquet", encoding="utf-8")
    _write_prices(tmp_path, "EMPTY.US", [])
    _write_prices(tmp_path, "SCHEMA.US", [{"date": "2026-01-01", "close": 1}])

    report = build_price_quality_report(tmp_path, universe_name=UNIVERSE, memberships_file=memberships, output_root=tmp_path / "reports")
    rows = report.symbol_quality.set_index("eodhd_symbol")

    assert rows.loc["BAD.US", "status"] == "unreadable_parquet"
    assert rows.loc["EMPTY.US", "status"] == "empty_file"
    assert rows.loc["SCHEMA.US", "status"] == "missing_required_columns"
    assert rows.loc["SCHEMA.US", "missing_columns"] == "adjusted_close,high,low,open,volume"


def test_scan_is_deterministic_across_worker_counts_and_max_symbols(tmp_path: Path):
    memberships = _write_memberships(tmp_path / "memberships.csv", [_membership("B.US"), _membership("A.US")])
    _write_prices(tmp_path, "A.US", [_price("2026-01-01", 1)])
    _write_prices(tmp_path, "B.US", [_price("2026-01-01", 2)])

    first = build_price_quality_report(tmp_path, universe_name=UNIVERSE, memberships_file=memberships, output_root=tmp_path / "one", workers=1)
    second = build_price_quality_report(tmp_path, universe_name=UNIVERSE, memberships_file=memberships, output_root=tmp_path / "two", workers=4)
    pd.testing.assert_frame_equal(first.symbol_quality, second.symbol_quality)
    assert first.summary == second.summary

    partial = build_price_quality_report(tmp_path, universe_name=UNIVERSE, memberships_file=memberships, output_root=tmp_path / "partial", max_symbols=1)
    assert partial.symbol_quality["eodhd_symbol"].tolist() == ["A.US"]
    assert partial.summary["partial_scan"] is True
    assert partial.summary["selected_candidate_count"] == 2


def test_price_quality_cli_supports_database_free_membership_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    memberships = _write_memberships(tmp_path / "memberships.csv", [_membership("A.US")])
    _write_prices(tmp_path, "A.US", [_price("2026-01-01", 1)])
    output_root = tmp_path / "reports"

    assert eodhd_main.main(
        [
            "prices", "scan-quality", "--root", str(tmp_path), "--universe", UNIVERSE,
            "--memberships-file", str(memberships), "--output-root", str(output_root),
        ]
    ) == 0

    summary = json.loads((output_root / UNIVERSE / f"build_id={BUILD_ID}" / "summary.json").read_text())
    assert summary["scanned_symbol_count"] == 1
    assert "EODHD price quality report written" in capsys.readouterr().out


def test_membership_file_requires_one_matching_build_id(tmp_path: Path):
    path = _write_memberships(tmp_path / "memberships.csv", [_membership("A.US"), {**_membership("B.US"), "build_id": "other"}])
    with pytest.raises(ValueError, match="exactly one build_id"):
        load_memberships_file(path)

    path = _write_memberships(tmp_path / "memberships.csv", [_membership("A.US")])
    with pytest.raises(ValueError, match="not requested"):
        load_memberships_file(path, build_id="requested")


def test_persisted_memberships_resolves_latest_build(monkeypatch: pytest.MonkeyPatch):
    class Cursor:
        def __init__(self) -> None:
            self.results = iter([(BUILD_ID,), (1,)])

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, *_):
            return None

        def fetchone(self):
            return next(self.results)

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    expected = pd.DataFrame([_membership("A.US")])
    monkeypatch.setattr(price_quality, "get_database_config", lambda: {"dbname": "unused"})
    monkeypatch.setattr(price_quality.psycopg2, "connect", lambda **_: connection)
    monkeypatch.setattr(price_quality.pd, "read_sql_query", lambda *_, **__: expected)

    resolved_build_id, memberships = load_persisted_memberships(UNIVERSE)

    assert resolved_build_id == BUILD_ID
    pd.testing.assert_frame_equal(memberships, expected)


def test_missing_file_uses_upstream_empty_checkpoint_status(tmp_path: Path):
    memberships = _write_memberships(tmp_path / "memberships.csv", [_membership("EMPTY.US")])
    state = tmp_path / "state/eodhd_all_world_snapshot.sqlite3"
    state.parent.mkdir(parents=True)
    connection = sqlite3.connect(state)
    connection.execute("CREATE TABLE dataset_download_state (dataset TEXT, full_symbol TEXT, is_delisted INTEGER, status TEXT)")
    connection.execute("INSERT INTO dataset_download_state VALUES ('eod_daily', 'EMPTY.US', 0, 'empty')")
    connection.commit()
    connection.close()

    report = build_price_quality_report(tmp_path, universe_name=UNIVERSE, memberships_file=memberships, output_root=tmp_path / "reports")

    assert report.symbol_quality.loc[0, "status"] == "upstream_empty"
    assert report.symbol_quality.loc[0, "checkpoint_status"] == "empty"
