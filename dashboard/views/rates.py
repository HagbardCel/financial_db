from __future__ import annotations

import re
import pandas as pd
import streamlit as st

from dashboard.data_access import (
    fetch_rate_curve,
    fetch_rate_history,
    get_rate_dimensions,
    get_rate_maturities,
    get_table_bounds,
)


def _maturity_to_years(value: str) -> float:
    match = re.match(r"^(\d+)([MY])$", value)
    if not match:
        return float("nan")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "M":
        return amount / 12.0
    return float(amount)


def _sort_maturities(values: list[str]) -> list[str]:
    return sorted(values, key=_maturity_to_years)


def render(engine) -> None:
    st.header("Rates")

    regions, rate_types, currencies = get_rate_dimensions(engine)

    if not regions or not rate_types or not currencies:
        st.info("No rate data available.")
        return

    region = st.selectbox("Region", regions)
    rate_type = st.selectbox("Rate Type", rate_types)
    currency = st.selectbox("Currency", currencies)

    min_date, max_date = get_table_bounds(engine, "interest_rates", "date")
    if min_date is None or max_date is None:
        st.info("No date data available for interest rates.")
        return
    snapshot_date = st.date_input("Snapshot date", value=max_date)

    curve = fetch_rate_curve(
        engine,
        snapshot_date=snapshot_date,
        region=region,
        rate_type=rate_type,
        currency=currency,
    )
    if curve.empty:
        st.info("No data for the selected snapshot.")
    else:
        curve["maturity_years"] = curve["maturity"].map(_maturity_to_years)
        curve = curve.sort_values("maturity_years").set_index("maturity_years")
        st.subheader("Yield Curve")
        st.line_chart(curve["interest_rate"], use_container_width=True)

    st.subheader("Historical Series")
    maturities = get_rate_maturities(
        engine,
        region=region,
        rate_type=rate_type,
        currency=currency,
    )
    if not maturities:
        st.info("No maturities available.")
        return

    maturity = st.selectbox("Maturity", _sort_maturities(maturities))
    series = fetch_rate_history(
        engine,
        region=region,
        rate_type=rate_type,
        currency=currency,
        maturity=maturity,
    )
    if series.empty:
        st.info("No history for the selected maturity.")
        return

    series["date"] = pd.to_datetime(series["date"])
    series = series.set_index("date")
    st.line_chart(series["interest_rate"], use_container_width=True)
