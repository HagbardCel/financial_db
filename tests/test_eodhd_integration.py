from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd
import psycopg2
import pytest

from data_fetchers.eodhd.downloader import atomic_write_parquet, normalize_eod_df, normalize_exchange_df, normalize_symbol_df
from data_fetchers.eodhd.ingestion import ingest_file
from data_fetchers.eodhd import materialization
from data_fetchers.eodhd.materialization import materialize_curated


pytestmark = pytest.mark.integration


def test_parquet_ingest_upsert_skip_and_price_views(tmp_path: Path):
    dsn = os.getenv("EODHD_TEST_DB_DSN")
    if not dsn:
        pytest.skip("Set EODHD_TEST_DB_DSN to run disposable PostgreSQL integration tests.")
    conn = psycopg2.connect(dsn)
    try:
        sql = (Path(__file__).parents[1] / "db_utils/db_setup.sql").read_text(encoding="utf-8")
        with conn.cursor() as cursor:
            cursor.execute(sql)
            cursor.execute(sql)
        conn.commit()
        exchange_path = tmp_path / "metadata/exchanges/snapshot_date=2026-01-03/exchanges.parquet"
        exchange_path.parent.mkdir(parents=True)
        exchange_df = normalize_exchange_df(
            [{
                "Code": "US", "Name": "USA Stocks", "Country": "USA", "Currency": "USD",
                "OperatingMIC": "XNAS, XNYS", "CountryISO2": "US", "CountryISO3": "USA",
            }],
            snapshot_date="2026-01-03",
        )
        atomic_write_parquet(exchange_df, exchange_path, dataset="exchange_snapshots")
        symbol_path = tmp_path / "metadata/symbol_lists/snapshot_date=2026-01-03/symbols.parquet"
        symbol_path.parent.mkdir(parents=True)
        symbol_df = normalize_symbol_df(
            [{
                "Code": "AAPL", "Name": "Apple", "Exchange": "NASDAQ", "Country": "USA",
                "Currency": "USD", "Type": "Common Stock", "Isin": "US0378331005",
            }],
            exchange_code="US",
            is_delisted=False,
            snapshot_date="2026-01-03",
        )
        symbol_df["request_type_filter"] = "ALL"
        atomic_write_parquet(symbol_df, symbol_path, dataset="symbol_snapshots")
        assert ingest_file(conn, tmp_path, "exchange_snapshots", exchange_path, batch_rows=1) is True
        assert ingest_file(conn, tmp_path, "symbol_snapshots", symbol_path, batch_rows=1) is True
        path = tmp_path / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
        path.parent.mkdir(parents=True)
        price_df = normalize_eod_df(
            [{
                "date": "2026-01-02", "open": 10, "high": 12, "low": 9, "close": 11,
                "adjusted_close": 10.5, "volume": 100,
            }],
            full_symbol="AAPL.US",
            exchange_code="US",
            is_delisted=False,
            retrieved_at=dt.datetime(2026, 1, 3, tzinfo=dt.timezone.utc),
        )
        atomic_write_parquet(price_df, path, dataset="eod_daily")
        assert ingest_file(conn, tmp_path, "eod_prices", path, batch_rows=1) is True
        assert ingest_file(conn, tmp_path, "eod_prices", path, batch_rows=1) is False
        with conn.cursor() as cursor:
            cursor.execute("SELECT close FROM public.eodhd_stock_prices_raw")
            assert cursor.fetchone()[0] == 11
            cursor.execute("SELECT close FROM public.eodhd_stock_prices_adjusted")
            assert cursor.fetchone()[0] == 10.5
            cursor.execute("SELECT COUNT(*) FROM eodhd.ingestion_artifacts")
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                "SELECT provider_exchange_code, exchange_name, exchange_country_iso2 "
                "FROM eodhd.latest_symbols_with_exchange_metadata WHERE eodhd_symbol = 'AAPL.US'"
            )
            assert cursor.fetchone() == ("NASDAQ", "USA Stocks", "US")
            cursor.execute("SELECT loader_version FROM eodhd.ingestion_artifacts WHERE parquet_path = %s", (str(path.relative_to(tmp_path)),))
            assert cursor.fetchone()[0] == "legacy"
    finally:
        conn.close()


def test_curated_materialization_rebuild_is_provider_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dsn = os.getenv("EODHD_TEST_DB_DSN")
    if not dsn:
        pytest.skip("Set EODHD_TEST_DB_DSN to run disposable PostgreSQL integration tests.")
    conn = psycopg2.connect(dsn)
    try:
        sql = (Path(__file__).parents[1] / "db_utils/db_setup.sql").read_text(encoding="utf-8")
        with conn.cursor() as cursor:
            cursor.execute(sql)
            cursor.execute(
                "INSERT INTO securities "
                "(security_id, isin, name, source_first_seen, source_last_seen, active_flag_current, created_at_utc, updated_at_utc) "
                "VALUES ('US0378331005', 'US0378331005', 'Existing', 'xetra', 'xetra', TRUE, NOW(), NOW())"
            )
            cursor.execute(
                "INSERT INTO equity_price_bars "
                "(provider, provider_symbol, date, adjustment_status, ingested_at_utc) "
                "VALUES ('stooq', 'keep.us', '2024-01-02', 'unknown', NOW())"
            )
        conn.commit()
    finally:
        conn.close()

    memberships = tmp_path / "memberships.csv"
    pd.DataFrame([{
        "build_id": "build", "eodhd_symbol": "A.US", "exchange_code": "US", "isin": "US0378331005",
        "isin_valid": True, "name": "A", "security_type": "Common Stock", "currency": "USD",
        "is_delisted": False, "membership_status": "selected_candidate",
    }]).to_csv(memberships, index=False)
    prices = tmp_path / "prices/eod_daily/exchange=US/delisted=0/A.US.parquet"
    prices.parent.mkdir(parents=True)
    pd.DataFrame([{
        "date": "2024-01-02", "open": 10, "high": 12, "low": 8, "close": 10,
        "adjusted_close": 5, "volume": 100,
    }]).to_parquet(prices, index=False)
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "summary.json").write_text('{"partial_scan": false}', encoding="utf-8")
    pd.DataFrame([{"status": "ok"}]).to_parquet(quality / "symbol_quality.parquet")
    monkeypatch.setattr(materialization, "get_database_config", lambda: psycopg2.extensions.parse_dsn(dsn))

    for _ in range(2):
        materialize_curated(
            tmp_path, universe_name="eodhd_us_listed_common_equities_v1", memberships_file=memberships,
            quality_report=quality, output_root=tmp_path / "reports",
        )

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT provider, provider_symbol, close FROM equity_price_bars ORDER BY provider")
            assert cursor.fetchall() == [("eodhd", "A.US", 5), ("stooq", "keep.us", None)]
            cursor.execute("SELECT COUNT(*) FROM eodhd.curated_price_metrics")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM eodhd.curated_materialization_runs")
            assert cursor.fetchone()[0] == 2
            cursor.execute("SELECT source_first_seen, source_last_seen FROM securities WHERE security_id = 'US0378331005'")
            assert cursor.fetchone() == ("xetra", "eodhd")
    finally:
        conn.close()
