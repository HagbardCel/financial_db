import sys
import pandas as pd
import yfinance as yf
from typing import Optional
from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config

class YahooFinanceFetcher(BaseFetcher):
    """
    Fetcher for stock market data using the yfinance library.
    """
    def __init__(self, symbol: str, db_config: Optional[dict] = None):
        super().__init__(db_config)
        self.symbol = symbol

    def fetch(self) -> pd.DataFrame:
        """
        Fetch historical price data for the given symbol.
        """
        self.logger.info(f"Fetching data for symbol: {self.symbol}")
        ticker = yf.Ticker(self.symbol)
        # Fetching maximum possible history
        df = ticker.history(period="max")
        if df.empty:
            raise ValueError(f"No data found for symbol: {self.symbol}")
        return df

    def transform(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and format the yfinance data to match the stock_prices schema.
        """
        self.logger.info(f"Transforming data for symbol: {self.symbol}")
        
        # Reset index to move 'Date' from index to a column
        df = raw_df.reset_index()
        
        # Ensure 'Date' is just the date part (yfinance often returns datetime with timezone)
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        # Add the symbol column
        df['symbol'] = self.symbol
        
        # Rename columns to match the database schema
        # Schema: ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']
        column_mapping = {
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        }
        
        df = df.rename(columns=column_mapping)
        
        # Select only the columns defined in the schema
        schema_cols = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']
        df = df[schema_cols]
        
        # Convert to appropriate types
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(int)
        
        return df

def main():
    if len(sys.argv) < 2:
        print("Usage: python yahoo_finance.py <symbol1> <symbol2> ...")
        sys.exit(1)

    symbols = sys.argv[1:]
    db_config = get_database_config()

    for symbol in symbols:
        try:
            fetcher = YahooFinanceFetcher(symbol, db_config=db_config)
            fetcher.run(table_name='stock_prices')
            print(f"Successfully processed {symbol}")
        except Exception as e:
            print(f"Failed to process {symbol}: {e}")

if __name__ == "__main__":
    main()
