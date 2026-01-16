from __future__ import annotations

import re
import pandas as pd
import streamlit as st

from dashboard import db


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

    regions = db.list_distinct(engine, "interest_rates", "region")["id"].tolist()
    rate_types = db.list_distinct(engine, "interest_rates", "rate_type")["id"].tolist()
    currencies = db.list_distinct(engine, "interest_rates", "currency")["id"].tolist()

    if not regions or not rate_types or not currencies:
        st.info("No rate data available.")
        return

    region = st.selectbox("Region", regions)
    rate_type = st.selectbox("Rate Type", rate_types)
    currency = st.selectbox("Currency", currencies)

    min_date, max_date = db.get_date_bounds(engine, "interest_rates", "date")
    if min_date is None or max_date is None:
        st.info("No date data available for interest rates.")
        return
    snapshot_date = st.date_input("Snapshot date", value=max_date)

    curve_query = """
        SELECT maturity, interest_rate
        FROM interest_rates
        WHERE date = :snapshot_date
          AND region = :region
          AND rate_type = :rate_type
          AND currency = :currency
    """
    curve = db.read_sql(
        engine,
        curve_query,
        params={
            "snapshot_date": snapshot_date,
            "region": region,
            "rate_type": rate_type,
            "currency": currency,
        },
    )
    if curve.empty:
        st.info("No data for the selected snapshot.")
    else:
        curve["maturity_years"] = curve["maturity"].map(_maturity_to_years)
        curve = curve.sort_values("maturity_years").set_index("maturity_years")
        st.subheader("Yield Curve")
        st.line_chart(curve["interest_rate"], use_container_width=True)

    st.subheader("Historical Series")
    maturities = db.read_sql(
        engine,
        """
        SELECT DISTINCT maturity
        FROM interest_rates
        WHERE region = :region
          AND rate_type = :rate_type
          AND currency = :currency
        ORDER BY maturity
        """,
        params={"region": region, "rate_type": rate_type, "currency": currency},
    )["maturity"].tolist()
    if not maturities:
        st.info("No maturities available.")
        return

    maturity = st.selectbox("Maturity", _sort_maturities(maturities))
    series_query = """
        SELECT date, interest_rate
        FROM interest_rates
        WHERE region = :region
          AND rate_type = :rate_type
          AND currency = :currency
          AND maturity = :maturity
        ORDER BY date
    """
    series = db.read_sql(
        engine,
        series_query,
        params={
            "region": region,
            "rate_type": rate_type,
            "currency": currency,
            "maturity": maturity,
        },
    )
    if series.empty:
        st.info("No history for the selected maturity.")
        return

    series["date"] = pd.to_datetime(series["date"])
    series = series.set_index("date")
    st.line_chart(series["interest_rate"], use_container_width=True)
