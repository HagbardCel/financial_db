from __future__ import annotations

import argparse

from analyses.stock_momentum.backtest import build_trades, summarize_trades
from analyses.stock_momentum.config import load_config
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection, build_engine, read_sql
from db_utils.repository import DataRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stock momentum prototype backtest.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--weighting-scheme", default="equal_weight")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    profile = config["project"].get("profile", "free_prototype")
    panel = read_sql(build_engine(), f"SELECT * FROM stock_momentum_panels WHERE profile = '{profile}'")
    strategy_id = f"stock_momentum_top{args.top_n}_{args.weighting_scheme}_{args.cost_bps:g}bps"
    trades = build_trades(panel, strategy_id, args.top_n, args.weighting_scheme, args.cost_bps)
    results = summarize_trades(trades, strategy_id)
    results["top_n"] = args.top_n
    results["weighting_scheme"] = args.weighting_scheme
    results["transaction_cost_bps_one_way"] = args.cost_bps
    with DatabaseConnection(config=get_database_config()) as db:
        repo = DataRepository(db)
        repo.save_dataframe(trades, "stock_momentum_trades")
        repo.save_dataframe(results, "stock_momentum_results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
