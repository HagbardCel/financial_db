from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import analytics
from dashboard.data_access import PRICE_DATASETS, fetch_ohlcv_series, get_dataset_bounds, list_series_ids


def render(engine) -> None:
    st.header("Prices Explorer")

    dataset_label = st.selectbox("Dataset", list(PRICE_DATASETS.keys()))
    dataset = PRICE_DATASETS[dataset_label]

    symbols_df = list_series_ids(engine, dataset)
    if symbols_df.empty:
        st.info("No symbols available for this dataset.")
        return

    symbol = st.selectbox("Symbol", symbols_df["id"].tolist())
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
    df = fetch_ohlcv_series(engine, dataset, symbol, start_date, end_date)
    if df.empty:
        st.info("No data for the selected range.")
        return

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = analytics.resample_ohlc(df, freq)

    st.subheader("Price")
    st.line_chart(df["close"], use_container_width=True)

    st.subheader("Volume")
    st.bar_chart(df["volume"], use_container_width=True)

    metrics = analytics.summary_metrics(df["close"], freq)
    cols = st.columns(4)
    cols[0].metric("Total Return", f"{metrics['total_return']:.2%}")
    cols[1].metric("CAGR", f"{metrics['cagr']:.2%}")
    cols[2].metric("Max Drawdown", f"{metrics['max_drawdown']:.2%}")
    cols[3].metric("Volatility", f"{metrics['volatility']:.2%}")

    st.subheader("Latest Data")
    st.dataframe(df.tail(20), use_container_width=True)
