from __future__ import annotations

import pandas as pd
import exchange_calendars as xcals


ELIGIBILITY_COLUMNS = [
    "profile", "provider", "security_id", "listing_id", "date", "eligible_price_available",
    "eligible_min_history", "eligible_min_price", "eligible_missingness", "eligible_security_type",
    "eligible_current_tradable_proxy", "eligible_liquidity", "trailing_session_count",
    "trailing_missing_price_ratio", "trailing_median_dollar_volume", "stale_price_days",
    "eligibility_basis", "eligible_final", "ineligibility_reason",
]


def _reason(row: pd.Series) -> str | None:
    checks = [
        ("price_unavailable", row["eligible_price_available"]),
        ("insufficient_history", row["eligible_min_history"]),
        ("price_below_minimum", row["eligible_min_price"]),
        ("excess_missingness", row["eligible_missingness"]),
        ("wrong_security_type", row["eligible_security_type"]),
        ("outside_price_history", row["eligible_current_tradable_proxy"]),
        ("insufficient_liquidity", row["eligible_liquidity"]),
    ]
    return ",".join(reason for reason, passed in checks if not passed) or None


def build_daily_eligibility(
    eur_prices: pd.DataFrame,
    raw_metrics: pd.DataFrame,
    *,
    profile: str = "eodhd_us_v1",
    provider: str = "eodhd",
    calendar_name: str = "XNYS",
    min_price_eur: float = 2.0,
    min_history_months: int = 13,
    max_stale_days: int = 5,
    missingness_window_sessions: int = 252,
    max_missing_ratio: float = 0.10,
    liquidity_window_sessions: int = 63,
    min_median_dollar_volume: float = 1_000_000.0,
) -> pd.DataFrame:
    if eur_prices.empty:
        return pd.DataFrame(columns=ELIGIBILITY_COLUMNS)
    prices = eur_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    metrics = raw_metrics.copy()
    metrics["date"] = pd.to_datetime(metrics["date"])
    calendar = xcals.get_calendar(calendar_name)
    rows = []
    for (security_id, listing_id), group in prices.groupby(["security_id", "listing_id"], sort=True):
        group = group.sort_values("date").drop_duplicates("date", keep="last")
        start, end = group["date"].min(), group["date"].max()
        sessions = calendar.sessions_in_range(start, end).tz_localize(None)
        frame = pd.DataFrame(index=sessions)
        indexed = group.set_index("date")
        frame["price_eur"] = indexed["price_eur"]
        listing_symbol = str(group.iloc[-1]["provider_symbol"])
        listing_metrics = metrics[metrics["provider_symbol"].eq(listing_symbol)].drop_duplicates("date").set_index("date")
        frame["dollar_volume"] = listing_metrics["dollar_volume"]
        frame["has_price"] = frame["price_eur"].notna()
        frame["last_price_date"] = pd.Series(frame.index.where(frame["has_price"]), index=frame.index).ffill()
        frame["stale_price_days"] = (pd.Series(frame.index, index=frame.index) - frame["last_price_date"]).dt.days
        frame["eligible_price_available"] = frame["last_price_date"].notna() & frame["stale_price_days"].le(max_stale_days)
        frame["eligible_min_history"] = frame.index >= (start + pd.DateOffset(months=min_history_months))
        frame["eligible_min_price"] = frame["price_eur"].ffill().ge(min_price_eur)
        trailing_present = frame["has_price"].rolling(missingness_window_sessions, min_periods=1).sum()
        trailing_sessions = frame["has_price"].rolling(missingness_window_sessions, min_periods=1).count()
        frame["trailing_session_count"] = trailing_sessions.astype(int)
        frame["trailing_missing_price_ratio"] = 1.0 - trailing_present / trailing_sessions
        frame["eligible_missingness"] = frame["trailing_missing_price_ratio"].le(max_missing_ratio)
        frame["trailing_median_dollar_volume"] = frame["dollar_volume"].rolling(liquidity_window_sessions, min_periods=liquidity_window_sessions).median()
        frame["eligible_liquidity"] = frame["trailing_median_dollar_volume"].ge(min_median_dollar_volume)
        frame["eligible_security_type"] = True
        frame["eligible_current_tradable_proxy"] = True
        frame["profile"] = profile
        frame["provider"] = provider
        frame["security_id"] = security_id
        frame["listing_id"] = listing_id
        frame["eligibility_basis"] = "price_derived_proxy"
        required = [
            "eligible_price_available", "eligible_min_history", "eligible_min_price", "eligible_missingness",
            "eligible_security_type", "eligible_current_tradable_proxy", "eligible_liquidity",
        ]
        frame["eligible_final"] = frame[required].all(axis=1)
        frame["ineligibility_reason"] = frame.apply(_reason, axis=1)
        frame["date"] = frame.index.date
        rows.append(frame.reset_index(drop=True)[ELIGIBILITY_COLUMNS])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=ELIGIBILITY_COLUMNS)
