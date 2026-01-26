import argparse
import io
import os
from typing import Optional

import pandas as pd
import requests

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers import openbb_client
from db_utils.config import get_database_config


RAW_CSV_URL = "https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv"
DATE_CANDIDATES = ("date", "month", "datetime", "time")
VALUE_CANDIDATES = ("price", "value", "gold", "usd", "usd_price")


class GoldPriceFetcher(BaseFetcher):
    """Fetch historical gold prices from the datasets/gold-prices monthly CSV."""

    def __init__(
        self,
        csv_url: str = RAW_CSV_URL,
        symbol: Optional[str] = None,
        db_config: Optional[dict] = None,
    ) -> None:
        super().__init__(db_config)
        self.csv_url = csv_url
        self.symbol = symbol or os.getenv("GOLD_SYMBOL", "GOLD")

    def fetch(self) -> str:
        response = requests.get(self.csv_url, timeout=30)
        response.raise_for_status()
        return response.text

    def transform(self, raw_csv: str) -> pd.DataFrame:
        df = pd.read_csv(io.StringIO(raw_csv))
        df = openbb_client.to_dataframe(df)
        if df.empty:
            raise ValueError("Gold price CSV response was empty.")

        lower_map = {col.lower(): col for col in df.columns}
        date_col = next(
            (lower_map[cand] for cand in DATE_CANDIDATES if cand in lower_map),
            None,
        )
        if not date_col:
            raise ValueError(f"No date column found in gold CSV. Columns: {df.columns.tolist()}")

        value_col = next(
            (lower_map[cand] for cand in VALUE_CANDIDATES if cand in lower_map),
            None,
        )
        if not value_col:
            numeric_cols = [
                col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])
            ]
            if numeric_cols:
                value_col = numeric_cols[0]
            else:
                raise ValueError("No numeric price column found in gold CSV.")

        dates = pd.to_datetime(df[date_col], errors="coerce") + pd.offsets.MonthEnd(0)
        prices = pd.to_numeric(df[value_col], errors="coerce")

        normalized = pd.DataFrame(
            {
                "symbol": self.symbol,
                "date": dates.dt.date,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": 0,
            }
        )

        return normalized.dropna(subset=["close", "date"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch gold prices from CSV via OpenBB.")
    parser.add_argument("--url", default=RAW_CSV_URL, help="CSV URL override")
    parser.add_argument("--symbol", help="Symbol stored in commodity_prices (default: GOLD)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fetcher = GoldPriceFetcher(
        csv_url=args.url,
        symbol=args.symbol,
        db_config=get_database_config(),
    )
    fetcher.run(table_name="commodity_prices")


if __name__ == "__main__":
    main()
