from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2
import pytest

from data_fetchers.eodhd.ingestion import ingest_file


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
        conn.commit()
        path = tmp_path / "prices/eod_daily/exchange=US/delisted=0/AAPL.US.parquet"
        path.parent.mkdir(parents=True)
        pd.DataFrame(
            [{
                "full_symbol": "AAPL.US", "exchange_code": "US", "date": "2026-01-02",
                "open": 10, "high": 12, "low": 9, "close": 11, "adjusted_close": 10.5,
                "volume": 100, "is_delisted_from_symbol_list": False, "requested_period": "d",
                "retrieved_at": "2026-01-03T00:00:00+00:00",
            }]
        ).to_parquet(path, index=False, compression="zstd")
        assert ingest_file(conn, tmp_path, "eod_prices", path, batch_rows=1) is True
        assert ingest_file(conn, tmp_path, "eod_prices", path, batch_rows=1) is False
        with conn.cursor() as cursor:
            cursor.execute("SELECT close FROM public.eodhd_stock_prices_raw")
            assert cursor.fetchone()[0] == 11
            cursor.execute("SELECT close FROM public.eodhd_stock_prices_adjusted")
            assert cursor.fetchone()[0] == 10.5
            cursor.execute("SELECT COUNT(*) FROM eodhd.ingestion_artifacts")
            assert cursor.fetchone()[0] == 1
    finally:
        conn.close()
