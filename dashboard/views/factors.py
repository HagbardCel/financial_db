from __future__ import annotations

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from db_utils import database as db


FREQ_LABELS = {"M": "Monthly", "D": "Daily"}


def _get_frequency(engine) -> str | None:
    freq_df = db.read_sql(engine, "SELECT DISTINCT frequency FROM factor_returns ORDER BY frequency")
    if freq_df.empty:
        return None
    options = freq_df["frequency"].tolist()
    if len(options) == 1:
        return options[0]
    return st.selectbox("Frequency", options, format_func=lambda f: FREQ_LABELS.get(f, f))


def _build_factor_options(engine, frequency: str) -> list[str]:
    options_df = db.read_sql(
        engine,
        """
        SELECT DISTINCT factor_set, factor
        FROM factor_returns
        WHERE frequency = :frequency
        ORDER BY factor_set, factor
        """,
        params={"frequency": frequency},
    )
    if options_df.empty:
        return []
    return [f"{row['factor_set']}::{row['factor']}" for _, row in options_df.iterrows()]


def _fetch_factor_data(engine, frequency: str, selected: list[str]) -> pd.DataFrame:
    params = {"frequency": frequency}
    clauses = []
    for idx, option in enumerate(selected):
        factor_set, factor = option.split("::", 1)
        params[f"set_{idx}"] = factor_set
        params[f"factor_{idx}"] = factor
        clauses.append(f"(factor_set = :set_{idx} AND factor = :factor_{idx})")
    where_clause = " OR ".join(clauses)
    query = f"""
        SELECT date, factor_set, factor, value
        FROM factor_returns
        WHERE frequency = :frequency
          AND ({where_clause})
        ORDER BY date
    """
    return db.read_sql(engine, query, params=params)


def render(engine) -> None:
    st.header("Fama-French Factors")

    frequency = _get_frequency(engine)
    if frequency is None:
        st.info("No factor data available.")
        return

    options = _build_factor_options(engine, frequency)
    if not options:
        st.info("No factor series available.")
        return

    selected = st.multiselect("Series", options, default=options[:4])
    if not selected:
        st.info("Select at least one factor.")
        return

    show_percent = st.checkbox("Show as %", value=True)

    df = _fetch_factor_data(engine, frequency, selected)
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
