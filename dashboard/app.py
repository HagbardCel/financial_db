from __future__ import annotations

import streamlit as st
from sqlalchemy import text

from db_utils import database as db
from dashboard.views import browser, compare, derived, factors, overview, prices, rates, series


@st.cache_resource
def get_engine():
    return db.build_engine()


def main() -> None:
    st.set_page_config(page_title="Financial Data Dashboard", layout="wide")
    st.title("Financial Data Dashboard")

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Database connection failed: {exc}")
        st.stop()

    pages = {
        "Overview": overview.render,
        "Prices Explorer": prices.render,
        "Series Explorer": series.render,
        "Compare & Correlate": compare.render,
        "Rates": rates.render,
        "Factors": factors.render,
        "Derived Metrics": derived.render,
        "Data Browser / Export": browser.render,
    }

    page_name = st.sidebar.radio("Page", list(pages.keys()))
    pages[page_name](engine)


if __name__ == "__main__":
    main()
