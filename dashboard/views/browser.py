from __future__ import annotations

import streamlit as st

from dashboard import db


TABLES = {
    "Assets Prices": {"table": "assets_prices", "date_col": "date", "id_col": "id"},
    "Indices": {"table": "indices", "date_col": "date", "id_col": "id"},
    "Stock Prices": {"table": "stock_prices", "date_col": "date", "id_col": "symbol"},
    "Commodity Prices": {"table": "commodity_prices", "date_col": "date", "id_col": "symbol"},
    "Macro Data": {"table": "macro_data", "date_col": "date", "id_col": "id"},
    "Interest Rates": {
        "table": "interest_rates",
        "date_col": "date",
        "filters": ["region", "rate_type", "maturity", "currency"],
    },
    "Shiller Derived View": {"table": "shiller_derived_view", "date_col": "date", "id_col": "id"},
}


def render(engine) -> None:
    st.header("Data Browser / Export")

    dataset_label = st.selectbox("Dataset", list(TABLES.keys()))
    dataset = TABLES[dataset_label]

    params = {}
    filters = []

    if "id_col" in dataset:
        ids_df = db.list_distinct(engine, dataset["table"], dataset["id_col"])
        options = ids_df["id"].tolist()
        selected_ids = st.multiselect("Filter IDs", options)
        if selected_ids:
            filters.append(f"{dataset['id_col']} = ANY(:ids)")
            params["ids"] = selected_ids

    if "filters" in dataset:
        for col in dataset["filters"]:
            options = db.list_distinct(engine, dataset["table"], col)["id"].tolist()
            selected = st.multiselect(f"Filter {col}", options)
            if selected:
                key = f"{col}_filter"
                filters.append(f"{col} = ANY(:{key})")
                params[key] = selected

    min_date, max_date = db.get_date_bounds(engine, dataset["table"], dataset["date_col"])
    if min_date is None or max_date is None:
        st.info("No date data available for this dataset.")
        return
    date_range = st.date_input("Date range", value=(min_date, max_date))
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
        filters.append(f"{dataset['date_col']} BETWEEN :start_date AND :end_date")
        params["start_date"] = start_date
        params["end_date"] = end_date

    limit = st.number_input("Row limit", min_value=100, max_value=5000, value=1000, step=100)

    where_clause = " AND ".join(filters)
    query = f"SELECT * FROM {dataset['table']}"
    if where_clause:
        query += f" WHERE {where_clause}"
    query += f" ORDER BY {dataset['date_col']} DESC LIMIT :limit"
    params["limit"] = int(limit)

    st.code(query, language="sql")

    df = db.read_sql(engine, query, params=params)
    if df.empty:
        st.info("No data for the selected filters.")
        return

    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, file_name="data_export.csv", mime="text/csv")
