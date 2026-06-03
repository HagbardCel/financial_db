from __future__ import annotations

import argparse
import csv
import io

import pandas as pd
import psycopg2

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.eligibility import build_daily_eligibility
from db_utils.config import get_database_config
from db_utils.database import build_engine, read_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build daily stock-momentum eligibility.")
    parser.add_argument("--config", default="config/stock_momentum_eodhd_us.toml")
    return parser.parse_args()


def _copy(cursor, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(
        [["\\N" if pd.isna(value) else value for value in row] for row in frame.itertuples(index=False, name=None)]
    )
    stream.seek(0)
    cursor.copy_expert(f"COPY equity_eligibility ({', '.join(frame.columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", stream)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    profile = config["project"]["profile"]
    provider = config["sources"]["eodhd"]["provider"]
    universe = config["universe"]
    engine = build_engine()
    prices = read_sql(engine, f"SELECT * FROM equity_prices_eur WHERE profile = '{profile}' AND provider = '{provider}'")
    metrics = read_sql(engine, "SELECT * FROM eodhd.curated_price_metrics")
    with psycopg2.connect(**get_database_config()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM equity_eligibility WHERE profile = %s", (profile,))
            for (_, _), listing_prices in prices.groupby(["security_id", "listing_id"], sort=True):
                symbol = listing_prices.iloc[0]["provider_symbol"]
                listing_metrics = metrics[metrics["provider_symbol"].eq(symbol)]
                output = build_daily_eligibility(
                    listing_prices, listing_metrics, profile=profile, provider=provider, calendar_name=universe.get("calendar", "XNYS"),
                    min_price_eur=float(universe["min_price_eur"]),
                    min_history_months=int(universe["min_history_months_before_eligibility"]),
                    max_stale_days=int(universe["max_stale_price_days_at_rebalance"]),
                    missingness_window_sessions=int(universe["missingness_window_sessions"]),
                    max_missing_ratio=float(universe["max_missing_daily_price_ratio_per_year"]),
                    liquidity_window_sessions=int(universe["liquidity_window_sessions"]),
                    min_median_dollar_volume=float(universe["min_median_dollar_volume"]),
                )
                _copy(cursor, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
