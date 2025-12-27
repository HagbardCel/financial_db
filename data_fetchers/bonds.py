#!/usr/bin/env python3
import pandas as pd
import pandas_datareader.data as web
from datetime import datetime
from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config

class TreasuryFetcher(BaseFetcher):
    def __init__(self, start_date=datetime(1934, 1, 1), end_date=None, db_config=None):
        super().__init__(db_config)
        self.start_date = start_date
        self.end_date = end_date or datetime.now()
        self.series_ids = {
            '1M': 'DGS1MO', '3M': 'DTB3', '6M': 'DTB6',
            '1Y': 'DGS1', '2Y': 'DGS2', '3Y': 'DGS3',
            '5Y': 'DGS5', '7Y': 'DGS7', '10Y': 'DGS10',
            '20Y': 'DGS20', '30Y': 'DGS30'
        }

    def fetch(self) -> dict:
        """Fetches historical treasury rates for various maturities from FRED."""
        data = {}
        for maturity, series_id in self.series_ids.items():
            try:
                df = web.DataReader(series_id, 'fred', self.start_date, self.end_date)
                data[maturity] = df
            except Exception as e:
                print(f"Error fetching {maturity} treasury rate: {e}")
        return data

    def transform(self, raw_data: dict) -> pd.DataFrame:
        """Transform multiple FRED series into a single long-format DataFrame."""
        records = []
        for maturity, df in raw_data.items():
            for date, row in df.iterrows():
                rate = row.iloc[0]
                if pd.notna(rate):
                    records.append({
                        'date': date.date(),
                        'region': 'US',
                        'rate_type': 'Treasury',
                        'maturity': maturity,
                        'interest_rate': float(rate),
                        'currency': 'USD'
                    })
        return pd.DataFrame(records)

    def run_pipeline(self):
        """Execute the fetch-transform-save pipeline for treasury rates."""
        # Note: mapping is done in transform logic here, so no value_mapping needed for save
        self.run(table_name='interest_rates')

if __name__ == "__main__":
    from datetime import timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    fetcher = TreasuryFetcher(start_date=start_date, end_date=end_date, db_config=get_database_config())
    fetcher.run_pipeline()
    print("Done fetching and saving Treasury rates.")
