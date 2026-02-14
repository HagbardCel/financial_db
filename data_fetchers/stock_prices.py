import argparse
import logging
import os
from typing import Optional

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers import openbb_client
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

logger = logging.getLogger(__name__)


class OpenBBEquityPriceFetcher(BaseFetcher):
    """Fetcher for equity price data via OpenBB."""

    def __init__(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        provider: Optional[str] = None,
        prefer_adjusted: bool = True,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.provider = provider or os.getenv("OPENBB_EQUITY_PROVIDER")
        self.prefer_adjusted = prefer_adjusted

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
        return openbb_client.normalize_ohlcv(
            raw_df,
            symbol=self.symbol,
            prefer_adjusted=self.prefer_adjusted,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch equity OHLCV via OpenBB.")
    parser.add_argument("symbols", nargs="+", help="Equity symbols (e.g., AAPL MSFT)")
    parser.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", help="OpenBB provider override")
    parser.add_argument(
        "--use-raw-close",
        action="store_true",
        help="Use raw close instead of adjusted close when both are available.",
    )
    return parser.parse_args()


def main() -> int:
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

    args = parse_args()
    db_config = get_database_config()
    prefer_adjusted = not args.use_raw_close
    failed_symbols: list[str] = []

    with DatabaseConnection(config=db_config) as db:
        repo = DataRepository(db)
        for symbol in args.symbols:
            try:
                fetcher = OpenBBEquityPriceFetcher(
                    symbol,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    provider=args.provider,
                    prefer_adjusted=prefer_adjusted,
                    db_config=db_config,
                )
                fetcher.run_with_repository(repo, table_name="stock_prices")
                db.conn.commit()
                logger.info("Successfully processed %s", symbol)
            except Exception:
                db.conn.rollback()
                failed_symbols.append(symbol)
                logger.exception("Failed to process %s", symbol)

    succeeded = len(args.symbols) - len(failed_symbols)
    logger.info(
        "Stock price ingest finished: %s succeeded, %s failed.",
        succeeded,
        len(failed_symbols),
    )
    if failed_symbols:
        logger.error("Failed symbols: %s", ", ".join(failed_symbols))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
