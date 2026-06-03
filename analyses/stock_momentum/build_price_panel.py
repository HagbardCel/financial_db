from __future__ import annotations

import argparse

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.fx import convert_prices_to_eur
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection, build_engine, read_sql
from db_utils.repository import DataRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EUR-denominated equity price panel.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    max_days = int(config["universe"].get("max_stale_price_days_at_rebalance", 5))
    profile = config["project"].get("profile", "free_prototype")
    provider = config.get("sources", {}).get("eodhd", {}).get("provider")
    engine = build_engine()
    where = f" WHERE provider = '{provider}'" if provider else ""
    prices = read_sql(engine, f"SELECT * FROM equity_price_bars{where}")
    rates = read_sql(engine, "SELECT * FROM fx_rates")
    output = convert_prices_to_eur(prices, rates, max_forward_fill_days=max_days, profile=profile)
    with DatabaseConnection(config=get_database_config()) as db:
        db.cursor.execute("DELETE FROM equity_prices_eur WHERE profile = %s", (profile,))
        DataRepository(db).save_dataframe(output, "equity_prices_eur")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
