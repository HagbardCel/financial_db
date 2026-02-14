import argparse
import os
from typing import List, Optional

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers import openbb_client
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository


DEFAULT_SYMBOLS: List[str] = ["GC=F", "SI=F", "HG=F"]


class OpenBBCommodityPriceFetcher(BaseFetcher):
    """Fetcher for commodity price data via OpenBB."""

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
        self.provider = provider or os.getenv("OPENBB_COMMODITY_PROVIDER")

    def fetch(self) -> pd.DataFrame:
        self.logger.info("Fetching data for commodity: %s", self.symbol)
        return openbb_client.fetch_dataframe(
            openbb_client.get_commodity_history_path(),
            symbol=self.symbol,
            start_date=self.start_date,
            end_date=self.end_date,
            provider=self.provider,
        )

    def transform(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        self.logger.info("Transforming data for commodity: %s", self.symbol)
        return openbb_client.normalize_ohlcv(raw_df, symbol=self.symbol)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch commodity OHLCV via OpenBB.")
    parser.add_argument("symbols", nargs="*", help="Commodity symbols (e.g., GC=F SI=F)")
    parser.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", help="OpenBB provider override")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = args.symbols or DEFAULT_SYMBOLS
    db_config = get_database_config()

    with DatabaseConnection(config=db_config) as db:
        repo = DataRepository(db)
        for symbol in symbols:
            try:
                fetcher = OpenBBCommodityPriceFetcher(
                    symbol,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    provider=args.provider,
                    db_config=db_config,
                )
                fetcher.run_with_repository(repo, table_name="commodity_prices")
                db.conn.commit()
                print(f"Successfully processed {symbol}")
            except Exception as exc:
                db.conn.rollback()
                print(f"Failed to process {symbol}: {exc}")


if __name__ == "__main__":
    main()
