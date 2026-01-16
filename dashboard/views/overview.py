from __future__ import annotations

import pandas as pd
import streamlit as st

from db_utils import database as db


TABLES = [
    {"label": "Assets Prices", "table": "assets_prices", "date_col": "date"},
    {"label": "Indices", "table": "indices", "date_col": "date"},
    {"label": "Stock Prices", "table": "stock_prices", "date_col": "date"},
    {"label": "Commodity Prices", "table": "commodity_prices", "date_col": "date"},
    {"label": "Interest Rates", "table": "interest_rates", "date_col": "date"},
    {"label": "Macro Data", "table": "macro_data", "date_col": "date"},
    {"label": "Shiller Derived View", "table": "shiller_derived_view", "date_col": "date"},
]


def render(engine) -> None:
    st.header("Overview")
    rows = []
    for meta in TABLES:
        stats = db.get_table_stats(engine, meta["table"], meta["date_col"])
        rows.append(
            {
                "Dataset": meta["label"],
                "Rows": stats["row_count"],
                "Start": stats["min_date"],
                "End": stats["max_date"],
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
