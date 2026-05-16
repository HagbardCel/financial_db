from __future__ import annotations

import argparse

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.signals import build_momentum_panel
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection, build_engine, read_sql
from db_utils.repository import DataRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build stock momentum panel.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    parser.add_argument("--frequency", choices=["monthly", "quarterly"], default="monthly")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    prices = read_sql(build_engine(), "SELECT * FROM equity_prices_eur")
    panel = build_momentum_panel(
        prices,
        frequency=args.frequency,
        profile=config["project"].get("profile", "free_prototype"),
    )
    with DatabaseConnection(config=get_database_config()) as db:
        DataRepository(db).save_dataframe(panel, "stock_momentum_panels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
