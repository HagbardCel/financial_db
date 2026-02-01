from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Tuple

import pandas as pd

from analyses.db_timeseries import load_monthly_returns
from data_fetchers.factor_etfs import ETF_NAMES, ETF_SETS
from db_utils.config import get_database_config
from db_utils.database import build_engine, read_table


def _load_aqr_portfolios(engine) -> pd.DataFrame:
    df = read_table(
        engine,
        table="portfolio_returns",
        columns=["portfolio_set", "universe", "portfolio", "date", "value"],
        where="source = :source",
        params={"source": "aqr"},
        order_by=["date"],
    )
    if df.empty:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df["series_id"] = (
        df["portfolio_set"].astype(str)
        + "::"
        + df["universe"].astype(str)
        + "::"
        + df["portfolio"].astype(str)
    )

    df = df.sort_values(["series_id", "date"])
    df = df.dropna(subset=["value"])
    df = df.drop_duplicates(subset=["series_id", "date"], keep="last")
    wide = df.pivot(index="date", columns="series_id", values="value").sort_index()
    return wide


def _best_match(
    etf_returns: pd.Series,
    aqr_returns: pd.DataFrame,
    min_overlap: int,
    use_abs: bool,
) -> Tuple[Optional[str], Optional[float], int, Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    common_index = aqr_returns.index.intersection(etf_returns.index)
    if common_index.empty:
        return None, None, 0, None, None

    etf_aligned = etf_returns.loc[common_index]
    aqr_aligned = aqr_returns.loc[common_index]

    overlap_counts = aqr_aligned.notna().mul(etf_aligned.notna(), axis=0).sum()
    eligible = overlap_counts[overlap_counts >= min_overlap].index
    if len(eligible) == 0:
        return None, None, 0, None, None

    corr = aqr_aligned[eligible].corrwith(etf_aligned)
    corr = corr.dropna()
    if corr.empty:
        return None, None, 0, None, None

    best_id = (corr.abs() if use_abs else corr).idxmax()
    best_corr = float(corr.loc[best_id])
    best_overlap = int(overlap_counts.loc[best_id])

    merged = pd.concat([aqr_aligned[best_id], etf_aligned], axis=1).dropna()
    if merged.empty:
        return best_id, best_corr, 0, None, None
    return best_id, best_corr, best_overlap, merged.index.min(), merged.index.max()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find the best-matching AQR portfolio for each ETF (by correlation)."
    )
    parser.add_argument(
        "--etf-set",
        default="msci_world",
        choices=sorted(ETF_SETS.keys()),
        help="ETF universe to use (default: msci_world).",
    )
    parser.add_argument(
        "--min-overlap",
        type=int,
        default=24,
        help="Minimum overlapping months required (default: 24).",
    )
    parser.add_argument(
        "--signed",
        action="store_true",
        help="Use signed correlation instead of absolute correlation for ranking.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = build_engine(get_database_config())

    etf_map = ETF_SETS[args.etf_set]
    tickers = list(etf_map.keys())

    etf_returns = load_monthly_returns(engine, tickers)
    if etf_returns.empty:
        raise ValueError("No ETF returns found. Run: python -m data_fetchers.factor_etfs")

    aqr_returns = _load_aqr_portfolios(engine)
    if aqr_returns.empty:
        raise ValueError("No AQR portfolio returns found. Run: python -m data_fetchers.aqr portfolios")

    use_abs = not args.signed
    print(f"ETF set: {args.etf_set}")
    print(f"Ranking: {'abs(correlation)' if use_abs else 'correlation'} | min_overlap={args.min_overlap}\n")

    rows: List[Dict[str, object]] = []
    for ticker in tickers:
        etf_series = etf_returns.get(ticker)
        if etf_series is None or etf_series.dropna().empty:
            rows.append(
                {
                    "ticker": ticker,
                    "name": ETF_NAMES.get(ticker, ""),
                    "factor": etf_map.get(ticker, ""),
                    "best_aqr_portfolio": None,
                    "correlation": None,
                    "overlap_months": 0,
                    "overlap_start": None,
                    "overlap_end": None,
                }
            )
            continue

        best_id, best_corr, overlap, start, end = _best_match(
            etf_series,
            aqr_returns,
            min_overlap=args.min_overlap,
            use_abs=use_abs,
        )
        rows.append(
            {
                "ticker": ticker,
                "name": ETF_NAMES.get(ticker, ""),
                "factor": etf_map.get(ticker, ""),
                "best_aqr_portfolio": best_id,
                "correlation": best_corr,
                "overlap_months": overlap,
                "overlap_start": start,
                "overlap_end": end,
            }
        )

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
