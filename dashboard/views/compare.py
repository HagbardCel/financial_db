from __future__ import annotations

import pandas as pd
import seaborn as sns
import streamlit as st
import matplotlib.pyplot as plt

from dashboard import analytics, db


COMPARE_DATASETS = {
    "Assets Prices": {
        "table": "assets_prices",
        "id_col": "id",
        "date_col": "date",
        "value_col": "price_usd",
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
    "Commodity Prices (Close)": {
        "table": "commodity_prices",
        "id_col": "symbol",
        "date_col": "date",
        "value_col": "close",
        "label_col": None,
    },
    "Shiller Derived": {
        "table": "shiller_derived_view",
        "id_col": "id",
        "date_col": "date",
        "value_col": "value",
        "label_col": "long_name",
    },
}


def render(engine) -> None:
    st.header("Compare & Correlate")

    dataset_labels = list(COMPARE_DATASETS.keys())
    chosen_datasets = st.multiselect("Include datasets", dataset_labels, default=dataset_labels[:2])
    if not chosen_datasets:
        st.info("Select at least one dataset.")
        return

    options = []
    option_map = {}
    for dataset_label in chosen_datasets:
        dataset = COMPARE_DATASETS[dataset_label]
        ids_df = db.list_distinct(engine, dataset["table"], dataset["id_col"], dataset["label_col"])
        if ids_df.empty:
            continue
        if "label" in ids_df.columns:
            label_map = {row["id"]: f"{row['id']} - {row['label']}" for _, row in ids_df.iterrows()}
        else:
            label_map = {row["id"]: row["id"] for _, row in ids_df.iterrows()}
        for series_id in ids_df["id"].tolist():
            option_key = f"{dataset_label}::{series_id}"
            options.append(option_key)
            option_map[option_key] = {
                **dataset,
                "id": series_id,
                "dataset_label": dataset_label,
                "short_label": label_map[series_id],
            }

    if not options:
        st.info("No series available for the selected datasets.")
        return

    option_label_counts = {}
    for option in options:
        short_label = option_map[option]["short_label"]
        option_label_counts[short_label] = option_label_counts.get(short_label, 0) + 1
    for option in options:
        meta = option_map[option]
        label = meta["short_label"]
        if option_label_counts[label] > 1:
            label = f"{label} ({meta['dataset_label']})"
        meta["display_label"] = label

    date_bounds = []
    for dataset_label in chosen_datasets:
        dataset = COMPARE_DATASETS[dataset_label]
        min_date, max_date = db.get_date_bounds(engine, dataset["table"], dataset["date_col"])
        if min_date is not None and max_date is not None:
            date_bounds.append((min_date, max_date))
    if not date_bounds:
        st.info("No date data available for the selected datasets.")
        return

    global_min = min(bound[0] for bound in date_bounds)
    global_max = max(bound[1] for bound in date_bounds)
    date_range = st.date_input("Date range", value=(global_min, global_max))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    selected = st.multiselect(
        "Series to compare",
        options,
        default=options[:2],
        format_func=lambda option: option_map[option]["display_label"],
    )
    if not selected:
        st.info("Select at least one series.")
        return

    normalize = st.checkbox("Normalize to 100", value=True)

    selected_meta = [option_map[item] for item in selected]
    label_counts = {}
    for meta in selected_meta:
        label_counts[meta["short_label"]] = label_counts.get(meta["short_label"], 0) + 1
    for meta in selected_meta:
        label = meta["short_label"]
        if label_counts[label] > 1:
            label = f"{label} ({meta['dataset_label']})"
        meta["final_label"] = label

    selected_by_table = {}
    for meta in selected_meta:
        entry = selected_by_table.setdefault(
            meta["table"],
            {"meta": meta, "ids": [], "label_map": {}},
        )
        entry["ids"].append(meta["id"])
        entry["label_map"][meta["id"]] = meta["final_label"]

    frames = []
    for table, entry in selected_by_table.items():
        dataset = entry["meta"]
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
            params={"ids": entry["ids"], "start_date": start_date, "end_date": end_date},
        )
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df["label"] = df["id"].map(entry["label_map"])
        frames.append(df[["date", "label", "value"]])

    if not frames:
        st.info("No data for the selected series.")
        return

    combined = pd.concat(frames, ignore_index=True)
    pivot = combined.pivot(index="date", columns="label", values="value").sort_index()

    if not pivot.empty:
        span_days = (pivot.index.max() - pivot.index.min()).days
        if span_days > 365:
            pivot = pivot.resample("W").last().dropna(how="all")
            st.caption("Auto-resampled to weekly for performance (range > 1 year).")

    if normalize:
        pivot = pivot.apply(analytics.normalize_to_base, axis=0)

    st.subheader("Series")
    st.line_chart(pivot, use_container_width=True)

    st.subheader("Correlation (Returns)")
    returns = pivot.pct_change().dropna()
    corr = returns.corr()
    st.dataframe(corr, use_container_width=True)

    if st.checkbox("Show heatmap", value=False):
        fig, ax = plt.subplots(figsize=(6, 4))
        sns.heatmap(corr, cmap="viridis", ax=ax)
        st.pyplot(fig)
