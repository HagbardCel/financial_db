from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from data_fetchers.eodhd.reporting import build_metadata_report
from data_fetchers.eodhd.universes import build_universe


UNIVERSE = "eodhd_us_listed_common_equities_v1"


def _write_metadata(root: Path, symbols: list[dict], snapshot_date: str = "2026-06-01") -> None:
    exchanges = root / "metadata/exchanges" / f"snapshot_date={snapshot_date}" / "exchanges.parquet"
    exchanges.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"code": "US", "name": "USA Stocks", "country": "USA", "currency": "USD", "operating_mic": "XNAS, XNYS"},
            {"code": "XETRA", "name": "XETRA", "country": "Germany", "currency": "EUR", "operating_mic": "XETR"},
            {"code": "EMPTY", "name": "Empty", "country": "Nowhere", "currency": "USD", "operating_mic": ""},
        ]
    ).to_parquet(exchanges, index=False)
    path = root / "metadata/symbol_lists" / f"snapshot_date={snapshot_date}" / "symbols.parquet"
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame(symbols)
    frame["snapshot_date"] = snapshot_date
    frame["request_type_filter"] = "ALL"
    frame["vendor"] = "eodhd"
    frame.to_parquet(path, index=False)


def _symbol(
    full_symbol: str,
    exchange_code: str,
    venue: str,
    *,
    isin: str | None,
    name: str = "Example Corp",
    security_type: str = "Common Stock",
    is_delisted: bool = False,
) -> dict:
    return {
        "code": full_symbol.split(".", 1)[0],
        "full_symbol": full_symbol,
        "exchange_code": exchange_code,
        "exchange": venue,
        "isin": isin,
        "name": name,
        "type": security_type,
        "currency": "USD",
        "country": "USA",
        "is_delisted": is_delisted,
    }


def test_us_universe_filters_otc_adr_and_prefers_exact_isin_listing(tmp_path: Path):
    isin = "US0378331005"
    _write_metadata(
        tmp_path,
        [
            _symbol("PREFERRED.US", "US", "NYSE", isin=isin),
            _symbol("SECONDARY.US", "US", "NASDAQ", isin=isin),
            _symbol("PREFERRED.US", "US", "NYSE", isin=isin, is_delisted=True),
            _symbol("FOREIGN.XETRA", "XETRA", "XETRA", isin=isin),
            _symbol("OTC.US", "US", "PINK", isin=None),
            _symbol("ADR.US", "US", "NASDAQ", isin=None, name="Example ADR"),
            _symbol("ETF.US", "US", "NYSE", isin=None, security_type="ETF"),
            _symbol("UNKNOWN.US", "US", "US", isin=None),
        ],
    )

    build = build_universe(tmp_path, universe_name=UNIVERSE)
    rows = build.memberships.set_index(["eodhd_symbol", "is_delisted"])

    assert rows.loc[("PREFERRED.US", False), "membership_status"] == "selected_candidate"
    assert rows.loc[("PREFERRED.US", True), "membership_status"] == "selected_candidate"
    assert rows.loc[("SECONDARY.US", False), "membership_status"] == "excluded_duplicate_listing"
    assert rows.loc[("FOREIGN.XETRA", False), "membership_status"] == "excluded_exchange_not_in_universe"
    assert rows.loc[("OTC.US", False), "membership_status"] == "excluded_otc_venue"
    assert rows.loc[("ADR.US", False), "membership_status"] == "excluded_adr"
    assert rows.loc[("ETF.US", False), "membership_status"] == "excluded_wrong_instrument_type"
    assert rows.loc[("UNKNOWN.US", False), "membership_status"] == "manual_review_provider_venue"


def test_missing_isin_similar_names_remain_separate_and_build_is_deterministic(tmp_path: Path):
    _write_metadata(
        tmp_path,
        [
            _symbol("ONE.US", "US", "NYSE", isin=None, name="Same Name"),
            _symbol("TWO.US", "US", "NASDAQ", isin=None, name="Same Name"),
        ],
    )
    first = build_universe(tmp_path, universe_name=UNIVERSE)
    second = build_universe(tmp_path, universe_name=UNIVERSE)
    assert first.build_id == second.build_id
    assert first.memberships["membership_status"].tolist() == ["selected_candidate", "selected_candidate"]
    assert first.memberships["identity_key"].tolist() == ["ONE.US", "TWO.US"]


def test_metadata_report_includes_coverage_duplicates_and_checkpoint_counts(tmp_path: Path):
    isin = "US0378331005"
    _write_metadata(
        tmp_path,
        [
            _symbol("AAPL.US", "US", "NASDAQ", isin=isin),
            _symbol("APC.XETRA", "XETRA", "XETRA", isin=isin),
        ],
    )
    state = tmp_path / "state/eodhd_all_world_snapshot.sqlite3"
    state.parent.mkdir(parents=True)
    connection = sqlite3.connect(state)
    connection.execute("CREATE TABLE dataset_download_state (dataset TEXT, status TEXT)")
    connection.execute("INSERT INTO dataset_download_state VALUES ('symbol_list', 'not_entitled')")
    connection.commit()
    connection.close()

    report = build_metadata_report(tmp_path, output_root=tmp_path / "reports")

    assert report.summary["exchanges_without_symbol_rows"] == ["EMPTY"]
    assert report.summary["cross_exchange_duplicate_isin_group_count"] == 1
    assert json.loads((report.output_dir / "summary.json").read_text())["symbol_count"] == 2
    checkpoint = pd.read_csv(report.output_dir / "download_state_counts.csv")
    assert checkpoint.to_dict("records") == [{"dataset": "symbol_list", "status": "not_entitled", "count": 1}]
