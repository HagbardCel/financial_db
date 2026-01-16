from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import analytics
from db_utils import database as db


DATASETS = {
    "Stock Prices": {"table": "stock_prices", "symbol_col": "symbol"},
    "Commodity Prices": {"table": "commodity_prices", "symbol_col": "symbol"},
}


def render(engine) -> None:
    st.header("Prices Explorer")

    dataset_label = st.selectbox("Dataset", list(DATASETS.keys()))
    dataset = DATASETS[dataset_label]

    symbols_df = db.list_distinct(engine, dataset["table"], dataset["symbol_col"])
    if symbols_df.empty:
        st.info("No symbols available for this dataset.")
        return

    symbol = st.selectbox("Symbol", symbols_df["id"].tolist())
    min_date, max_date = db.get_date_bounds(engine, dataset["table"], "date")
    if min_date is None or max_date is None:
        st.info("No date data available for this dataset.")
        return

    date_range = st.date_input("Date range", value=(min_date, max_date))
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("Select a start and end date.")
        return
    start_date, end_date = date_range

    freq = st.selectbox("Resample", ["D", "W", "M"], index=0)

    query = f"""
        SELECT date, open, high, low, close, volume
        FROM {dataset["table"]}
        WHERE {dataset["symbol_col"]} = :symbol
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date
    """
    df = db.read_sql(
        engine,
        query,
        params={"symbol": symbol, "start_date": start_date, "end_date": end_date},
    )
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
