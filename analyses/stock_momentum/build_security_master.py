from __future__ import annotations

import argparse

from analyses.stock_momentum.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Security master is built during Xetra ingestion.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    return parser.parse_args()


def main() -> int:
    load_config(parse_args().config)
    print("Security master rows are maintained in securities/listings by data_fetchers.xetra_instruments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
