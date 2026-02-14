from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

from dashboard import analytics
from dashboard.data_access import (
    COMPARE_DATASETS,
    FACTOR_FREQ_LABELS,
    build_label_map,
    fetch_factor_data,
    fetch_value_series,
    get_dataset_bounds,
    get_factor_bounds,
    get_factor_frequencies,
    get_factor_options,
    list_series_ids,
)


FACTOR_DATASET_LABEL = "Fama-French Factors"


def render(engine) -> None:
    st.header("Compare & Correlate")

    dataset_labels = list(COMPARE_DATASETS.keys()) + [FACTOR_DATASET_LABEL]
    chosen_datasets = st.multiselect("Include datasets", dataset_labels, default=dataset_labels[:2])
    if not chosen_datasets:
        st.info("Select at least one dataset.")
        return

    factor_frequency = None
    if FACTOR_DATASET_LABEL in chosen_datasets:
        freq_options = get_factor_frequencies(engine)
        if not freq_options:
            st.info("No factor data available.")
            return
        if len(freq_options) == 1:
            factor_frequency = freq_options[0]
            st.caption(f"Factor frequency: {FACTOR_FREQ_LABELS.get(factor_frequency, factor_frequency)}")
        else:
            factor_frequency = st.selectbox(
                "Factor frequency",
                freq_options,
                format_func=lambda value: FACTOR_FREQ_LABELS.get(value, value),
            )

    options: list[str] = []
    option_map: dict[str, dict] = {}

    for dataset_label in chosen_datasets:
        if dataset_label == FACTOR_DATASET_LABEL:
            if factor_frequency is None:
                continue
            factor_options = get_factor_options(engine, factor_frequency)
            for option in factor_options:
                option_key = f"{dataset_label}::{option}"
                options.append(option_key)
                option_map[option_key] = {
                    "dataset_label": dataset_label,
                    "frequency": factor_frequency,
                    "factor_option": option,
                    "short_label": option,
                    "return_series": True,
                }
            continue

        dataset = COMPARE_DATASETS[dataset_label]
        ids_df = list_series_ids(engine, dataset)
        if ids_df.empty:
            continue
        label_map = build_label_map(ids_df)
        for series_id in ids_df["id"].tolist():
            option_key = f"{dataset_label}::{series_id}"
            options.append(option_key)
            option_map[option_key] = {
                "dataset_label": dataset_label,
                "dataset": dataset,
                "id": series_id,
                "short_label": label_map[series_id],
                "return_series": False,
            }

    if not options:
        st.info("No series available for the selected datasets.")
        return

    option_label_counts: dict[str, int] = {}
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
        if dataset_label == FACTOR_DATASET_LABEL and factor_frequency is not None:
            min_date, max_date = get_factor_bounds(engine, factor_frequency)
        else:
            min_date, max_date = get_dataset_bounds(engine, COMPARE_DATASETS[dataset_label])
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
    label_counts: dict[str, int] = {}
    for meta in selected_meta:
        label_counts[meta["short_label"]] = label_counts.get(meta["short_label"], 0) + 1

    label_is_return: dict[str, bool] = {}
    for meta in selected_meta:
        label = meta["short_label"]
        if label_counts[label] > 1:
            label = f"{label} ({meta['dataset_label']})"
        meta["final_label"] = label
        label_is_return[label] = meta["return_series"]

    frames = []

    factor_selected = [m for m in selected_meta if m["dataset_label"] == FACTOR_DATASET_LABEL]
    if factor_selected and factor_frequency is not None:
        selected_options = [m["factor_option"] for m in factor_selected]
        factor_df = fetch_factor_data(
            engine,
            frequency=factor_frequency,
            options=selected_options,
            start_date=start_date,
            end_date=end_date,
        )
        if not factor_df.empty:
            factor_df["date"] = pd.to_datetime(factor_df["date"])
            factor_df["option"] = factor_df["factor_set"] + "::" + factor_df["factor"]
            factor_label_map = {m["factor_option"]: m["final_label"] for m in factor_selected}
            factor_df["label"] = factor_df["option"].map(factor_label_map)
            frames.append(factor_df[["date", "label", "value"]])

    dataset_groups: dict[str, dict] = {}
    for meta in selected_meta:
        if meta["dataset_label"] == FACTOR_DATASET_LABEL:
            continue
        group = dataset_groups.setdefault(
            meta["dataset_label"],
            {
                "dataset": meta["dataset"],
                "ids": [],
                "label_map": {},
            },
        )
        group["ids"].append(meta["id"])
        group["label_map"][meta["id"]] = meta["final_label"]

    for group in dataset_groups.values():
        df = fetch_value_series(
            engine,
            dataset=group["dataset"],
            ids=group["ids"],
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df["label"] = df["id"].map(group["label_map"])
        frames.append(df[["date", "label", "value"]])

    if not frames:
        st.info("No data for the selected series.")
        return

    combined = pd.concat(frames, ignore_index=True)
    pivot = combined.pivot(index="date", columns="label", values="value").sort_index()

    span_days = 0
    if not pivot.empty:
        span_days = (pivot.index.max() - pivot.index.min()).days
    if span_days > 365:
        pivot = pivot.resample("W").last().dropna(how="all")
        st.caption("Auto-resampled to weekly for performance (range > 1 year).")

    if normalize:
        pivot = pivot.copy()
        for column in pivot.columns:
            if not label_is_return.get(column, False):
                pivot[column] = analytics.normalize_to_base(pivot[column])

    st.subheader("Series")
    st.line_chart(pivot, use_container_width=True)

    st.subheader("Correlation (Returns)")
    returns = pd.DataFrame(index=pivot.index)
    for label in pivot.columns:
        series = pivot[label]
        if label_is_return.get(label, False):
            returns[label] = series
        else:
            returns[label] = series.pct_change()
    returns = returns.dropna()
    corr = returns.corr()
    st.dataframe(corr, use_container_width=True)

    if st.checkbox("Show heatmap", value=False):
        fig, ax = plt.subplots(figsize=(6, 4))
        sns.heatmap(corr, cmap="viridis", ax=ax)
        st.pyplot(fig)
