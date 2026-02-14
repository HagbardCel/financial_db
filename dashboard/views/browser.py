from __future__ import annotations

import streamlit as st

from dashboard.data_access import BROWSER_DATASETS, get_table_bounds, list_distinct_values
from db_utils import database as db


def render(engine) -> None:
    st.header("Data Browser / Export")

    dataset_label = st.selectbox("Dataset", list(BROWSER_DATASETS.keys()))
    dataset = BROWSER_DATASETS[dataset_label]

    params = {}
    filters = []

    if dataset.id_col:
        options = list_distinct_values(engine, dataset.table, dataset.id_col)
        selected_ids = st.multiselect("Filter IDs", options)
        if selected_ids:
            filters.append(db.where_any(dataset.id_col, "ids"))
            params["ids"] = selected_ids

    for col in dataset.filters:
        options = list_distinct_values(engine, dataset.table, col)
        selected = st.multiselect(f"Filter {col}", options)
        if selected:
            key = f"{col}_filter"
            filters.append(db.where_any(col, key))
            params[key] = selected

    min_date, max_date = get_table_bounds(engine, dataset.table, dataset.date_col)
    if min_date is None or max_date is None:
        st.info("No date data available for this dataset.")
        return
    date_range = st.date_input("Date range", value=(min_date, max_date))
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
        filters.append(db.where_between(dataset.date_col, "start_date", "end_date"))
        params["start_date"] = start_date
        params["end_date"] = end_date

    limit = st.number_input("Row limit", min_value=100, max_value=5000, value=1000, step=100)
    query = db.build_select_query(
        table=dataset.table,
        columns=["*"],
        where=filters or None,
        order_by=[db.order_by_clause(dataset.date_col, descending=True)],
        limit_param="limit",
    )
    params["limit"] = int(limit)

    st.code(query, language="sql")

    df = db.read_sql(engine, query, params=params)
    if df.empty:
        st.info("No data for the selected filters.")
        return

    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, file_name="data_export.csv", mime="text/csv")
