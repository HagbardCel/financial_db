from __future__ import annotations

import argparse
from typing import Dict, Iterable, List, Optional

from data_fetchers.stock_prices import OpenBBEquityPriceFetcher
from db_utils.config import get_database_config

ETF_NAMES: Dict[str, str] = {
    "IWFM.L": "iShares Edge MSCI World Momentum Factor UCITS ETF",
    "IWFV.L": "iShares Edge MSCI World Value Factor UCITS ETF",
    "IWQU.L": "iShares Edge MSCI World Quality Factor UCITS ETF",
    "MTUM": "iShares MSCI USA Momentum Factor ETF",
    "VLUE": "iShares MSCI USA Value Factor ETF",
    "QUAL": "iShares MSCI USA Quality Factor ETF",
}

ETF_SETS: Dict[str, Dict[str, str]] = {
    "msci_world": {
        "IWFM.L": "Momentum",
        "IWFV.L": "Value",
        "IWQU.L": "Quality",
    },
    "us": {
        "MTUM": "Momentum",
        "VLUE": "Value",
        "QUAL": "Quality",
    },
}


def _resolve_tickers(etf_set: str, tickers: Optional[Iterable[str]]) -> List[str]:
    if tickers:
        return list(tickers)
    if etf_set not in ETF_SETS:
        raise ValueError(f"Unknown ETF set '{etf_set}'. Available: {', '.join(sorted(ETF_SETS.keys()))}")
    return list(ETF_SETS[etf_set].keys())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch factor ETF prices via OpenBB.")
    parser.add_argument(
        "--set",
        dest="etf_set",
        default="msci_world",
        choices=sorted(ETF_SETS.keys()),
        help="Predefined ETF set to ingest.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Explicit list of ETF tickers (overrides --set).",
    )
    parser.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", help="OpenBB provider override")
    parser.add_argument(
        "--use-raw-close",
        action="store_true",
        help="Use raw close instead of adjusted close when both are available.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_config = get_database_config()
    tickers = _resolve_tickers(args.etf_set, args.tickers)
    prefer_adjusted = not args.use_raw_close
    start_date = args.start_date or "1900-01-01"

    for symbol in tickers:
        try:
            fetcher = OpenBBEquityPriceFetcher(
                symbol,
                start_date=start_date,
                end_date=args.end_date,
                provider=args.provider,
                prefer_adjusted=prefer_adjusted,
                db_config=db_config,
            )
            fetcher.run(table_name="stock_prices")
            print(f"Successfully processed {symbol}")
        except Exception as exc:
            print(f"Failed to process {symbol}: {exc}")


if __name__ == "__main__":
    main()
