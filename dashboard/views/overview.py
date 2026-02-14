from __future__ import annotations

import pandas as pd
import streamlit as st

from db_utils import database as db
from dashboard.data_access import OVERVIEW_TABLES


def render(engine) -> None:
    st.header("Overview")
    rows = []
    for label, table in OVERVIEW_TABLES.items():
        stats = db.get_table_stats(engine, table, "date")
        rows.append(
            {
                "Dataset": label,
                "Rows": stats["row_count"],
                "Start": stats["min_date"],
                "End": stats["max_date"],
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
