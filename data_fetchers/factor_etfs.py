from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import pandas as pd

from data_fetchers.openbb_equity_prices import OpenBBEquityPriceFetcher
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

logger = logging.getLogger(__name__)

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


def _etf_reference_frames(tickers: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    securities = []
    listings = []
    for ticker in tickers:
        security_id = f"openbb:{ticker}"
        securities.append(
            {
                "security_id": security_id,
                "isin": None,
                "name": ETF_NAMES.get(ticker, ticker),
                "security_type": "etf",
                "country": None,
                "currency_primary": None,
                "source_first_seen": "openbb",
                "source_last_seen": "openbb",
                "active_flag_current": True,
                "created_at_utc": now,
                "updated_at_utc": now,
            }
        )
        listings.append(
            {
                "listing_id": security_id,
                "security_id": security_id,
                "provider": "openbb",
                "provider_symbol": ticker,
                "exchange_code": None,
                "mic": None,
                "trading_currency": None,
                "isin": None,
                "name": ETF_NAMES.get(ticker, ticker),
                "first_seen_date": None,
                "last_seen_date": None,
                "is_currently_tradable": True,
                "source_file": None,
            }
        )
    return pd.DataFrame(securities), pd.DataFrame(listings)


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


def main() -> int:
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

    args = parse_args()
    db_config = get_database_config()
    tickers = _resolve_tickers(args.etf_set, args.tickers)
    prefer_adjusted = not args.use_raw_close
    start_date = args.start_date or "1900-01-01"
    failed_symbols: list[str] = []

    with DatabaseConnection(config=db_config) as db:
        repo = DataRepository(db)
        securities, listings = _etf_reference_frames(tickers)
        repo.save_dataframe(securities, "securities")
        repo.save_dataframe(listings, "listings")
        db.conn.commit()
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
                fetcher.run_with_repository(repo, table_name="equity_price_bars")
                db.conn.commit()
                logger.info("Successfully processed %s", symbol)
            except Exception:
                db.conn.rollback()
                failed_symbols.append(symbol)
                logger.exception("Failed to process %s", symbol)

    succeeded = len(tickers) - len(failed_symbols)
    logger.info(
        "Factor ETF ingest finished: %s succeeded, %s failed.",
        succeeded,
        len(failed_symbols),
    )
    if failed_symbols:
        logger.error("Failed symbols: %s", ", ".join(failed_symbols))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
