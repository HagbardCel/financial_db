from __future__ import annotations

import pandas as pd


def convert_prices_to_eur(
    price_bars: pd.DataFrame,
    fx_rates: pd.DataFrame,
    max_forward_fill_days: int = 5,
    profile: str = "free_prototype",
) -> pd.DataFrame:
    prices = price_bars.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    rates = fx_rates.copy()
    rates["date"] = pd.to_datetime(rates["date"])
    rates["currency"] = rates["currency"].str.upper()
    prices["currency"] = prices["currency"].fillna("EUR").astype(str).str.upper()

    rows = []
    for currency, group in prices.groupby("currency", dropna=False):
        group = group.sort_values("date")
        if currency == "EUR":
            merged = group.copy()
            merged["units_per_eur"] = 1.0
            merged["fx_date"] = merged["date"]
            merged["is_fx_forward_filled"] = False
            merged["source_fx_file"] = None
        else:
            fx = rates[rates["currency"] == currency][["date", "units_per_eur"]].sort_values("date")
            fx = fx.rename(columns={"date": "fx_date"})
            merged = pd.merge_asof(
                group,
                fx,
                left_on="date",
                right_on="fx_date",
                direction="backward",
                tolerance=pd.Timedelta(days=max_forward_fill_days),
            )
            merged["is_fx_forward_filled"] = merged["fx_date"].notna() & merged["fx_date"].ne(merged["date"])
            merged["source_fx_file"] = "fx_rates"
        merged["price_local"] = merged["close"]
        merged["price_eur"] = merged["price_local"] / merged["units_per_eur"]
        merged["source_price_file"] = merged.get("source_file")
        rows.append(merged)

    output = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if output.empty:
        return output
    output["date"] = output["date"].dt.date
    output["fx_date"] = pd.to_datetime(output["fx_date"]).dt.date
    output["profile"] = profile
    return output[
        [
            "profile",
            "security_id",
            "listing_id",
            "provider",
            "provider_symbol",
            "date",
            "price_local",
            "currency",
            "units_per_eur",
            "fx_date",
            "price_eur",
            "is_fx_forward_filled",
            "source_price_file",
            "source_fx_file",
        ]
    ]
