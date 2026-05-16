from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from db_utils.database import read_table


def load_equity_price_bars(engine, tickers: List[str]) -> pd.DataFrame:
    df = read_table(
        engine,
        table="equity_price_bars",
        columns=["provider_symbol", "date", "close"],
        where="provider_symbol IN :symbols",
        params={"symbols": tickers},
        order_by=["date"],
        expanding=["symbols"],
    )
    if df.empty:
        return df
    df = df.rename(columns={"provider_symbol": "symbol"})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["symbol", "date"])


def load_stock_prices(engine, tickers: List[str]) -> pd.DataFrame:
    """Backward-compatible helper returning equity bars using the old function name."""
    return load_equity_price_bars(engine, tickers)


def to_monthly_returns(
    prices: pd.DataFrame,
    symbol_col: str = "symbol",
    date_col: str = "date",
    price_col: str = "close",
) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()

    monthly = (
        prices.set_index(date_col)
        .groupby(symbol_col)[price_col]
        .resample("ME")
        .last()
        .reset_index()
    )
    monthly["return"] = monthly.groupby(symbol_col)[price_col].pct_change()
    monthly = monthly.dropna(subset=["return"])
    return (
        monthly.pivot(index=date_col, columns=symbol_col, values="return")
        .sort_index()
        .dropna(axis=1, how="all")
    )


def load_monthly_returns(
    engine,
    tickers: List[str],
    column_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    prices = load_equity_price_bars(engine, tickers)
    returns = to_monthly_returns(prices)
    if returns.empty or not column_map:
        return returns
    renamed = returns.rename(columns=column_map)
    if renamed.columns.duplicated().any():
        renamed = renamed.groupby(level=0, axis=1).mean()
    return renamed
