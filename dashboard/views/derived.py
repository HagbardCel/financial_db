from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import db


def render(engine) -> None:
    st.header("Derived Metrics (Shiller CAPE)")

    ids_df = db.list_distinct(engine, "shiller_derived_view", "id", "long_name")
    if ids_df.empty:
        st.info("No derived series available.")
        return

    label_map = {row["id"]: f"{row['id']} - {row['label']}" for _, row in ids_df.iterrows()}
    options = [label_map[row_id] for row_id in ids_df["id"].tolist()]
    selected_labels = st.multiselect("Series", options, default=options[:2])
    if not selected_labels:
        st.info("Select at least one series.")
        return
    selected_ids = [key for key, label in label_map.items() if label in selected_labels]

    min_date, max_date = db.get_date_bounds(engine, "shiller_derived_view", "date")
    if min_date is None or max_date is None:
        st.info("No date data available for this view.")
        return
    date_range = st.date_input("Date range", value=(min_date, max_date))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    query = """
        SELECT date, id, long_name, value
        FROM shiller_derived_view
        WHERE id = ANY(:ids)
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date
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
    pivot = pivot.rename(columns=label_map)

    st.line_chart(pivot, use_container_width=True)

    st.subheader("Latest Value vs History")
    rows = []
    for column in pivot.columns:
        series = pivot[column].dropna()
        if series.empty:
            continue
        latest_date = series.index.max()
        latest_value = series.loc[latest_date]
        percentile = series.rank(pct=True).iloc[-1]
        rows.append(
            {
                "Series": column,
                "Latest Date": latest_date,
                "Latest Value": latest_value,
                "Percentile": percentile,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
