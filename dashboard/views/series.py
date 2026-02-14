from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import analytics
from dashboard.data_access import (
    FACTOR_FREQ_LABELS,
    SERIES_DATASETS,
    build_label_map,
    fetch_factor_data,
    fetch_value_series,
    get_dataset_bounds,
    get_factor_bounds,
    get_factor_frequencies,
    get_factor_options,
    get_factor_sets,
    list_series_ids,
)


def _render_factor_series(engine) -> None:
    freq_options = get_factor_frequencies(engine)
    if not freq_options:
        st.info("No factor data available.")
        return

    if len(freq_options) == 1:
        frequency = freq_options[0]
        st.caption(f"Frequency: {FACTOR_FREQ_LABELS.get(frequency, frequency)}")
    else:
        frequency = st.selectbox(
            "Frequency",
            freq_options,
            format_func=lambda value: FACTOR_FREQ_LABELS.get(value, value),
        )

    factor_sets = get_factor_sets(engine, frequency)
    if not factor_sets:
        st.info("No factor sets available.")
        return

    selected_sets = st.multiselect("Factor sets", factor_sets, default=factor_sets)
    if not selected_sets:
        st.info("Select at least one factor set.")
        return

    options = get_factor_options(engine, frequency, selected_sets)
    if not options:
        st.info("No factors available.")
        return

    selected = st.multiselect("Series", options, default=options[:4])
    if not selected:
        st.info("Select at least one series.")
        return

    show_percent = st.checkbox("Show as %", value=True)

    min_date, max_date = get_factor_bounds(engine, frequency, selected_sets)
    if min_date is None or max_date is None:
        st.info("No date data available for factors.")
        return

    date_range = st.date_input("Date range", value=(min_date, max_date))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    df = fetch_factor_data(
        engine,
        frequency=frequency,
        options=selected,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        st.info("No data for the selected range.")
        return

    df["date"] = pd.to_datetime(df["date"])
    df["label"] = df["factor_set"] + "::" + df["factor"]
    pivot = df.pivot(index="date", columns="label", values="value").sort_index()

    pivot_display = pivot * 100 if show_percent else pivot
    st.line_chart(pivot_display, use_container_width=True)
    st.subheader("Summary Stats")
    st.dataframe(pivot_display.describe().transpose(), use_container_width=True)


def render(engine) -> None:
    st.header("Series Explorer")

    dataset_labels = list(SERIES_DATASETS.keys()) + ["Fama-French Factors"]
    dataset_label = st.selectbox("Dataset", dataset_labels)
    if dataset_label == "Fama-French Factors":
        _render_factor_series(engine)
        return

    dataset = SERIES_DATASETS[dataset_label]

    ids_df = list_series_ids(engine, dataset)
    if ids_df.empty:
        st.info("No series available.")
        return

    label_map = build_label_map(ids_df)
    options = [label_map[row_id] for row_id in ids_df["id"].tolist()]
    selected_labels = st.multiselect("Series", options, default=options[:1])
    if not selected_labels:
        st.info("Select at least one series.")
        return

    selected_ids = [key for key, label in label_map.items() if label in selected_labels]

    min_date, max_date = get_dataset_bounds(engine, dataset)
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

    df = fetch_value_series(
        engine,
        dataset,
        ids=selected_ids,
        start_date=start_date,
        end_date=end_date,
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
