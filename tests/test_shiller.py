#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Tuple, List

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
import pytest

from db_utils.config import get_database_config

pytestmark = pytest.mark.integration


def fetch_data(conn, table_name: str) -> pd.DataFrame:
    """Fetch data from specified table/view."""
    query = f"""
        SELECT date, id, value
        FROM {table_name}
        ORDER BY date, id
    """
    return pd.read_sql_query(query, conn, parse_dates=['date'])


def get_derived_columns() -> List[str]:
    """Get list of derived column IDs from shiller_cols.json."""
    config_path = Path(__file__).resolve().parent.parent / 'data_fetchers' / 'shiller_cols.json'
    with open(config_path, 'r') as f:
        data = json.load(f)
    return [details['id'] for details in data.values() if details['type'] == 'derived']


def compare_values(
    view_data: pd.DataFrame,
    test_data: pd.DataFrame,
    tolerance: float = 1e-10,
) -> Tuple[bool, pd.DataFrame, pd.DataFrame]:
    """
    Compare values between view and test data.
    Returns a tuple of (all_match, differences_df, merged_df).
    """
    merged = pd.merge(
        view_data,
        test_data,
        on=['date', 'id'],
        suffixes=('_view', '_test'),
    )

    merged['abs_diff'] = np.abs(merged['value_view'] - merged['value_test'])
    merged['rel_diff'] = merged['abs_diff'] / np.abs(merged['value_test'])

    matches = (merged['abs_diff'] <= tolerance) | (merged['rel_diff'] <= tolerance)
    differences = merged[~matches]

    return matches.all(), differences, merged


def summarize_significant_deviations(
    merged_data: pd.DataFrame,
    threshold: float = 0.0001,
) -> pd.DataFrame:
    """
    Summarize columns with significant deviations (>= 0.01%).
    Returns a DataFrame with summary statistics for each affected column.
    """
    significant = merged_data[merged_data['rel_diff'] >= threshold]

    if significant.empty:
        return pd.DataFrame()

    summary = significant.groupby('id').agg({
        'rel_diff': ['count', 'mean', 'max'],
        'abs_diff': ['mean', 'max'],
    }).round(6)

    summary.columns = [f"{col[0]}_{col[1]}" for col in summary.columns]
    return summary.sort_values('rel_diff_max', ascending=False)


@pytest.fixture(scope="module")
def db_conn():
    try:
        config = get_database_config()
    except ValueError as exc:
        pytest.skip(str(exc))
    # build SQLAlchemy URL so pandas can accept the connectable
    url = (
        f"postgresql+psycopg2://{config['user']}:{config['password']}@"
        f"{config['host']}:{config['port']}/{config['dbname']}"
    )
    engine = create_engine(url)
    conn = engine.connect()
    yield conn
    conn.close()
    engine.dispose()


def test_shiller_derived_view_matches_test_data(db_conn):
    derived_cols = get_derived_columns()

    view_data = fetch_data(db_conn, 'shiller_derived_view')
    test_data = fetch_data(db_conn, 'test_data')

    if view_data.empty or test_data.empty:
        pytest.skip("Required data not present; run the Shiller ingestion before testing.")

    view_data = view_data[view_data['id'].isin(derived_cols)]
    test_data = test_data[test_data['id'].isin(derived_cols)]

    all_match, differences, merged_data = compare_values(view_data, test_data)

    if not all_match:
        summary = summarize_significant_deviations(merged_data)
        diff_preview = differences.head(20).to_string(index=False)
        summary_text = summary.to_string() if not summary.empty else "No significant deviations."
        pytest.fail(
            "Mismatches found in derived values.\n"
            f"Differences (first 20 rows):\n{diff_preview}\n\n"
            f"Summary:\n{summary_text}"
        )
