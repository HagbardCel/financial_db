from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import analytics
from db_utils import database as db


DATASETS = {
    "Assets Prices": {
        "table": "assets_prices",
        "id_col": "id",
        "date_col": "date",
        "value_col": "price_usd",
        "label_col": None,
    },
    "Commodity Prices (Close)": {
        "table": "commodity_prices",
        "id_col": "symbol",
        "date_col": "date",
        "value_col": "close",
        "label_col": None,
    },
    "Indices": {
        "table": "indices",
        "id_col": "id",
        "date_col": "date",
        "value_col": "value",
        "label_col": "index_name",
    },
    "Macro Data": {
        "table": "macro_data",
        "id_col": "id",
        "date_col": "date",
        "value_col": "value",
        "label_col": "long_name",
    },
    "Fama-French Factors": {
        "table": "factor_returns",
    },
}

FREQ_LABELS = {"M": "Monthly", "D": "Daily"}


def _build_label_map(df: pd.DataFrame) -> dict:
    if "label" in df.columns:
        return {row["id"]: f"{row['id']} - {row['label']}" for _, row in df.iterrows()}
    return {row["id"]: row["id"] for _, row in df.iterrows()}


def _render_factor_series(engine) -> None:
    freq_df = db.read_sql(
        engine,
        "SELECT DISTINCT frequency FROM factor_returns ORDER BY frequency",
    )
    if freq_df.empty:
        st.info("No factor data available.")
        return
    freq_options = freq_df["frequency"].tolist()
    if len(freq_options) == 1:
        frequency = freq_options[0]
        st.caption(f"Frequency: {FREQ_LABELS.get(frequency, frequency)}")
    else:
        frequency = st.selectbox(
            "Frequency",
            freq_options,
            format_func=lambda value: FREQ_LABELS.get(value, value),
        )

    factor_sets_df = db.read_sql(
        engine,
        """
        SELECT DISTINCT factor_set
        FROM factor_returns
        WHERE frequency = :frequency
        ORDER BY factor_set
        """,
        params={"frequency": frequency},
    )
    if factor_sets_df.empty:
        st.info("No factor sets available.")
        return
    factor_sets = factor_sets_df["factor_set"].tolist()
    selected_sets = st.multiselect("Factor sets", factor_sets, default=factor_sets)
    if not selected_sets:
        st.info("Select at least one factor set.")
        return

    options_df = db.read_sql(
        engine,
        """
        SELECT DISTINCT factor_set, factor
        FROM factor_returns
        WHERE frequency = :frequency
          AND factor_set = ANY(:sets)
        ORDER BY factor_set, factor
        """,
        params={"frequency": frequency, "sets": selected_sets},
    )
    if options_df.empty:
        st.info("No factors available.")
        return
    options = [f"{row['factor_set']}::{row['factor']}" for _, row in options_df.iterrows()]
    selected = st.multiselect("Series", options, default=options[:4])
    if not selected:
        st.info("Select at least one series.")
        return

    show_percent = st.checkbox("Show as %", value=True)

    date_bounds = db.read_sql(
        engine,
        """
        SELECT MIN(date) AS min_date, MAX(date) AS max_date
        FROM factor_returns
        WHERE frequency = :frequency
          AND factor_set = ANY(:sets)
        """,
        params={"frequency": frequency, "sets": selected_sets},
    )
    min_date = date_bounds.loc[0, "min_date"]
    max_date = date_bounds.loc[0, "max_date"]
    if pd.isna(min_date) or pd.isna(max_date):
        st.info("No date data available for factors.")
        return

    date_range = st.date_input("Date range", value=(min_date, max_date))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    params = {"frequency": frequency, "start_date": start_date, "end_date": end_date}
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
          AND date BETWEEN :start_date AND :end_date
          AND ({where_clause})
        ORDER BY date
    """
    df = db.read_sql(engine, query, params=params)
    if df.empty:
        st.info("No data for the selected range.")
        return

    df["date"] = pd.to_datetime(df["date"])
    df["label"] = df["factor_set"] + "::" + df["factor"]
    pivot = df.pivot(index="date", columns="label", values="value").sort_index()

    if show_percent:
        pivot_display = pivot * 100
    else:
        pivot_display = pivot

    st.line_chart(pivot_display, use_container_width=True)
    st.subheader("Summary Stats")
    st.dataframe(pivot_display.describe().transpose(), use_container_width=True)


def render(engine) -> None:
    st.header("Series Explorer")

    dataset_label = st.selectbox("Dataset", list(DATASETS.keys()))
    if dataset_label == "Fama-French Factors":
        _render_factor_series(engine)
        return

    dataset = DATASETS[dataset_label]

    ids_df = db.list_distinct(engine, dataset["table"], dataset["id_col"], dataset["label_col"])
    if ids_df.empty:
        st.info("No series available.")
        return

    label_map = _build_label_map(ids_df)
    options = [label_map[row_id] for row_id in ids_df["id"].tolist()]
    selected_labels = st.multiselect("Series", options, default=options[:1])
    if not selected_labels:
        st.info("Select at least one series.")
        return
    selected_ids = [key for key, label in label_map.items() if label in selected_labels]

    min_date, max_date = db.get_date_bounds(engine, dataset["table"], dataset["date_col"])
    if min_date is None or max_date is None:
        st.info("No date data available for this dataset.")
        return
    date_range = st.date_input("Date range", value=(min_date, max_date))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    freq = st.selectbox("Resample", ["D", "W", "M"], index=0)
    transform = st.selectbox("Transform", ["Level", "% Change", "YoY % Change"])
    normalize = st.checkbox("Normalize to 100", value=False)

    query = db.build_select_query(
        table=dataset["table"],
        columns={
            dataset["date_col"]: "date",
            dataset["id_col"]: "id",
            dataset["value_col"]: "value",
        },
        where=[
            db.where_any(dataset["id_col"], "ids"),
            db.where_between(dataset["date_col"], "start_date", "end_date"),
        ],
        order_by=[db.order_by_clause(dataset["date_col"])],
    )
    df = db.read_sql(
        engine,
        query,
        params={"ids": selected_ids, "start_date": start_date, "end_date": end_date},
    )
    if df.empty:
        st.info("No data for the selected range.")
        return

    df["date"] = pd.to_datetime(df["date"])
    pivot = df.pivot(index="date", columns="id", values="value").sort_index()
    pivot = pivot.resample(freq).last()

    if transform == "% Change":
        pivot = pivot.pct_change()
    elif transform == "YoY % Change":
        periods = {"D": 252, "W": 52, "M": 12}[freq]
        pivot = pivot.pct_change(periods=periods)

    if normalize:
        pivot = pivot.apply(analytics.normalize_to_base, axis=0)

    pivot = pivot.rename(columns=label_map)

    st.line_chart(pivot, use_container_width=True)
    st.subheader("Summary Stats")
    st.dataframe(pivot.describe().transpose(), use_container_width=True)
