import sys
from typing import Optional, List
from data_fetchers.yahoo_finance import YahooFinanceFetcher
from db_utils.config import get_database_config

DEFAULT_SYMBOLS: List[str] = ["GC=F", "SI=F", "HG=F"]

def parse_symbols(args: List[str]) -> List[str]:
    if not args:
        return DEFAULT_SYMBOLS
    return args

def main():
    symbols = parse_symbols(sys.argv[1:])
    db_config = get_database_config()

    for symbol in symbols:
        try:
            fetcher = YahooFinanceFetcher(symbol, db_config=db_config)
            fetcher.run(table_name="commodity_prices")
            print(f"Successfully processed {symbol}")
        except Exception as e:
            print(f"Failed to process {symbol}: {e}")

if __name__ == "__main__":
    main()
