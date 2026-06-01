#!/usr/bin/env python3
import argparse
import os
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Sequence

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers import openbb_client
from db_utils.config import get_database_config


DEFAULT_SERIES: Dict[str, str] = {
    "1M": "DGS1MO",
    "3M": "DTB3",
    "6M": "DTB6",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}
DEFAULT_PROVIDER = "fred"
FRED_SETUP_HINT = (
    "Set FRED_API_KEY in .env (preferred) or export it in the shell "
    "before running the fetcher."
)


class TreasuryFetcher(BaseFetcher):
    """Fetch Treasury rate series via OpenBB (typically FRED-backed)."""

    def __init__(
        self,
        start_date: date,
        end_date: date,
        db_config: Optional[dict] = None,
        series_ids: Optional[Dict[str, str]] = None,
        provider: Optional[str] = None,
        region: str = "US",
        rate_type: str = "Treasury",
        currency: str = "USD",
    ):
        super().__init__(db_config)
        self.start_date = start_date
        self.end_date = end_date
        self.series_ids = series_ids or DEFAULT_SERIES
        self.provider = provider or os.getenv("OPENBB_RATES_PROVIDER") or DEFAULT_PROVIDER
        self.region = region
        self.rate_type = rate_type
        self.currency = currency
        self.fetch_errors: Dict[str, str] = {}

    def fetch(self) -> Dict[str, pd.DataFrame]:
        data: Dict[str, pd.DataFrame] = {}
        path = openbb_client.get_fred_series_path()
        self.fetch_errors = {}
        for maturity, series_id in self.series_ids.items():
            try:
                df = openbb_client.fetch_dataframe(
                    path,
                    symbol=series_id,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    provider=self.provider,
                )
                if df.empty:
                    self.logger.warning("Empty response for series %s (%s)", maturity, series_id)
                    continue
                data[maturity] = df
            except Exception as exc:
                self.fetch_errors[f"{maturity}:{series_id}"] = str(exc)
                self.logger.error(
                    "Error fetching %s treasury rate (%s): %s",
                    maturity,
                    series_id,
                    exc,
                )
        return data

    def transform(self, raw_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = []
        for maturity, df in raw_data.items():
            if df.empty:
                continue
            frames.append(
                openbb_client.normalize_rate_series(
                    df,
                    maturity=maturity,
                    region=self.region,
                    rate_type=self.rate_type,
                    currency=self.currency,
                )
            )
        if not frames:
            detail = "; ".join(
                f"{series}: {message}" for series, message in self.fetch_errors.items()
            ) or "No per-series errors were captured."
            raise ValueError(
                "No treasury rate series fetched successfully via OpenBB/FRED. "
                f"Attempted series: {', '.join(self.series_ids.values())}. "
                f"Errors: {detail}. {FRED_SETUP_HINT}"
            )
        return pd.concat(frames, ignore_index=True)


def _parse_date(value: Optional[str], default: date) -> date:
    if not value:
        return default
    return datetime.fromisoformat(value).date()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Treasury rates via OpenBB.")
    parser.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="OpenBB provider override")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    end_date = _parse_date(args.end_date, datetime.now().date())
    start_date = _parse_date(args.start_date, end_date - timedelta(days=365))

    fetcher = TreasuryFetcher(
        start_date=start_date,
        end_date=end_date,
        provider=args.provider,
        db_config=get_database_config(),
    )
    fetcher.run(table_name="interest_rates")


if __name__ == "__main__":
    main()
