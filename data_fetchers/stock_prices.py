import argparse
import os
from typing import Optional

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers import openbb_client
from db_utils.config import get_database_config


class OpenBBEquityPriceFetcher(BaseFetcher):
    """Fetcher for equity price data via OpenBB."""

    def __init__(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        provider: Optional[str] = None,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.provider = provider or os.getenv("OPENBB_EQUITY_PROVIDER")

    def fetch(self) -> pd.DataFrame:
        self.logger.info("Fetching data for symbol: %s", self.symbol)
        return openbb_client.fetch_dataframe(
            openbb_client.get_equity_history_path(),
            symbol=self.symbol,
            start_date=self.start_date,
            end_date=self.end_date,
            provider=self.provider,
        )

    def transform(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        self.logger.info("Transforming data for symbol: %s", self.symbol)
        return openbb_client.normalize_ohlcv(raw_df, symbol=self.symbol)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch equity OHLCV via OpenBB.")
    parser.add_argument("symbols", nargs="+", help="Equity symbols (e.g., AAPL MSFT)")
    parser.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", help="OpenBB provider override")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_config = get_database_config()

    for symbol in args.symbols:
        try:
            fetcher = OpenBBEquityPriceFetcher(
                symbol,
                start_date=args.start_date,
                end_date=args.end_date,
                provider=args.provider,
                db_config=db_config,
            )
            fetcher.run(table_name="stock_prices")
            print(f"Successfully processed {symbol}")
        except Exception as exc:
            print(f"Failed to process {symbol}: {exc}")


if __name__ == "__main__":
    main()
