from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    if freq == "D":
        return df
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    resampled = df.resample(freq).agg(agg)
    return resampled.dropna(subset=["close"])


def total_return(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return series.iloc[-1] / series.iloc[0] - 1


def cagr(series: pd.Series) -> float:
    if series.empty or len(series) < 2:
        return float("nan")
    start, end = series.index.min(), series.index.max()
    years = (end - start).days / 365.25
    if years <= 0:
        return float("nan")
    return (series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1


def max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    running_max = series.cummax()
    drawdowns = series / running_max - 1
    return drawdowns.min()


def rolling_volatility(returns: pd.Series, periods_per_year: int) -> float:
    if returns.empty:
        return float("nan")
    return returns.std() * np.sqrt(periods_per_year)


def periods_per_year(freq: str) -> int:
    return {"D": 252, "W": 52, "M": 12}.get(freq, 252)


def normalize_to_base(series: pd.Series, base: float = 100.0) -> pd.Series:
    if series.empty:
        return series
    return series / series.iloc[0] * base


def summary_metrics(series: pd.Series, freq: str) -> Dict[str, float]:
    returns = series.pct_change().dropna()
    return {
        "total_return": total_return(series),
        "cagr": cagr(series),
        "max_drawdown": max_drawdown(series),
        "volatility": rolling_volatility(returns, periods_per_year(freq)),
    }
