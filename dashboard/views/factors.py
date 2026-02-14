from __future__ import annotations

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from db_utils import database as db
from dashboard.data_access import FACTOR_FREQ_LABELS, fetch_factor_data, get_factor_frequencies, get_factor_options


def _get_frequency(engine) -> str | None:
    options = get_factor_frequencies(engine)
    if not options:
        return None
    if len(options) == 1:
        return options[0]
    return st.selectbox("Frequency", options, format_func=lambda f: FACTOR_FREQ_LABELS.get(f, f))


def render(engine) -> None:
    st.header("Fama-French Factors")

    frequency = _get_frequency(engine)
    if frequency is None:
        st.info("No factor data available.")
        return

    options = get_factor_options(engine, frequency)
    if not options:
        st.info("No factor series available.")
        return

    selected = st.multiselect("Series", options, default=options[:4])
    if not selected:
        st.info("Select at least one factor.")
        return

    show_percent = st.checkbox("Show as %", value=True)

    df = fetch_factor_data(engine, frequency=frequency, options=selected)
    if df.empty:
        st.info("No data for the selected factors.")
        return

    df["date"] = pd.to_datetime(df["date"])
    df["label"] = df["factor_set"] + "::" + df["factor"]
    pivot = df.pivot(index="date", columns="label", values="value").sort_index()

    display = pivot * 100 if show_percent else pivot
    st.subheader("Series")
    st.line_chart(display, use_container_width=True)

    stats = pd.DataFrame(
        {
            "mean": pivot.mean(),
            "std": pivot.std(),
            "min": pivot.min(),
            "max": pivot.max(),
            "positive_share": (pivot > 0).mean(),
        }
    )
    if show_percent:
        stats[["mean", "std", "min", "max"]] = stats[["mean", "std", "min", "max"]] * 100
        stats["positive_share"] = stats["positive_share"] * 100
    st.subheader("Summary Stats")
    st.dataframe(stats, use_container_width=True)

    st.subheader("Correlation")
    corr = pivot.corr()
    st.dataframe(corr, use_container_width=True)

    if st.checkbox("Show histograms", value=False):
        for column in pivot.columns:
            fig, ax = plt.subplots(figsize=(5, 3))
            ax.hist(pivot[column].dropna(), bins=30, alpha=0.8)
            ax.set_title(column)
            st.pyplot(fig)

    if st.checkbox("Show rolling mean / volatility", value=False):
        window = st.number_input("Rolling window (months)", min_value=3, max_value=120, value=12, step=1)
        rolling_mean = pivot.rolling(window).mean()
        rolling_vol = pivot.rolling(window).std()
        st.subheader("Rolling Mean")
        st.line_chart(rolling_mean, use_container_width=True)
        st.subheader("Rolling Volatility")
        st.line_chart(rolling_vol, use_container_width=True)

    st.subheader("Data Coverage")
    coverage = db.read_sql(
        engine,
        """
        SELECT factor_set, frequency, factor, COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date
        FROM factor_returns
        GROUP BY factor_set, frequency, factor
        ORDER BY factor_set, frequency, factor
        """,
    )
    st.dataframe(coverage, use_container_width=True)
