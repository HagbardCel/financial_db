from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalDates:
    rebalance_date: pd.Timestamp
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp


def _last_price_on_or_before(series: pd.Series, target: pd.Timestamp, max_stale_days: int = 5):
    eligible = series[series.index <= target].dropna()
    if eligible.empty:
        return None
    date = eligible.index[-1]
    if (target - date).days > max_stale_days:
        return None
    return date, eligible.iloc[-1]


def momentum(price_series: pd.Series, signal_date: pd.Timestamp, lookback_months: int, skip_recent_months: int = 0) -> float | None:
    prices = price_series.copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()
    end_target = signal_date - pd.DateOffset(months=skip_recent_months)
    start_target = signal_date - pd.DateOffset(months=lookback_months)
    end = _last_price_on_or_before(prices, end_target)
    start = _last_price_on_or_before(prices, start_target)
    if not end or not start:
        return None
    _, end_price = end
    _, start_price = start
    if start_price == 0:
        return None
    return float(end_price / start_price - 1.0)


def build_momentum_panel(
    eur_prices: pd.DataFrame,
    frequency: str = "monthly",
    profile: str = "free_prototype",
) -> pd.DataFrame:
    prices = eur_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    if frequency not in {"monthly", "quarterly"}:
        raise ValueError("frequency must be monthly or quarterly")
    freq = "ME" if frequency == "monthly" else "QE"
    rebalance_dates = pd.date_range(prices["date"].min(), prices["date"].max(), freq=freq)
    rows = []
    for rebalance_date in rebalance_dates:
        for security_id, group in prices.groupby("security_id"):
            group = group.sort_values("date")
            series = group.set_index("date")["price_eur"]
            signal = _last_price_on_or_before(series, rebalance_date)
            future = group[group["date"] > (signal[0] if signal else rebalance_date)] if signal else pd.DataFrame()
            if not signal or future.empty:
                continue
            signal_date, signal_price = signal
            execution_date = future.iloc[0]["date"]
            row = group.iloc[-1]
            m3 = momentum(series, signal_date, 3)
            m6 = momentum(series, signal_date, 6)
            m9 = momentum(series, signal_date, 9)
            m12 = momentum(series, signal_date, 12)
            m121 = momentum(series, signal_date, 12, skip_recent_months=1)
            rows.append(
                {
                    "strategy_family": "stock_momentum",
                    "profile": profile,
                    "rebalance_frequency": frequency,
                    "rebalance_date": rebalance_date.date(),
                    "signal_date": signal_date.date(),
                    "execution_date": execution_date.date(),
                    "security_id": security_id,
                    "listing_id": row.get("listing_id"),
                    "provider_symbol": row.get("provider_symbol"),
                    "name": None,
                    "currency": row.get("currency"),
                    "price_eur_signal": signal_price,
                    "price_eur_lookback": None,
                    "momentum_3m": m3,
                    "momentum_6m": m6,
                    "momentum_9m": m9,
                    "momentum_12m": m12,
                    "momentum_12_1m": m121,
                    "volatility_3m": None,
                    "volatility_6m": None,
                    "volatility_12m": None,
                    "rank_metric": m12,
                    "rank_ascending_false": None,
                    "eligible_final": m12 is not None,
                    "run_id": None,
                }
            )
    panel = pd.DataFrame(rows)
    if panel.empty:
        return panel
    panel["rank_ascending_false"] = (
        panel[panel["eligible_final"]]
        .groupby("rebalance_date")["rank_metric"]
        .rank(method="first", ascending=False)
    )
    return panel
