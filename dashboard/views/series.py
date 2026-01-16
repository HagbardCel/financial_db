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
}


def _build_label_map(df: pd.DataFrame) -> dict:
    if "label" in df.columns:
        return {row["id"]: f"{row['id']} - {row['label']}" for _, row in df.iterrows()}
    return {row["id"]: row["id"] for _, row in df.iterrows()}


def render(engine) -> None:
    st.header("Series Explorer")

    dataset_label = st.selectbox("Dataset", list(DATASETS.keys()))
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

    query = f"""
        SELECT {dataset["date_col"]} AS date, {dataset["id_col"]} AS id, {dataset["value_col"]} AS value
        FROM {dataset["table"]}
        WHERE {dataset["id_col"]} = ANY(:ids)
          AND {dataset["date_col"]} BETWEEN :start_date AND :end_date
        ORDER BY {dataset["date_col"]}
    """
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
