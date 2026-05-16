"""Backward-compatible wrapper for OpenBB equity price ingestion."""

from data_fetchers.openbb_equity_prices import OpenBBEquityPriceFetcher, main, parse_args

__all__ = ["OpenBBEquityPriceFetcher", "main", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
