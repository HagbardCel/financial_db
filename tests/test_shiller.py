#!/usr/bin/env python3

import os
import sys
import logging
import psycopg2
import pandas as pd
import numpy as np
from typing import Tuple, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Create a database connection."""
    return psycopg2.connect(
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432')
    )

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
    import json
    with open('data_fetchers/shiller_cols.json', 'r') as f:
        data = json.load(f)
    return [details['id'] for details in data.values() if details['type'] == 'derived']

def compare_values(view_data: pd.DataFrame, test_data: pd.DataFrame, tolerance: float = 1e-10) -> Tuple[bool, pd.DataFrame]:
    """
    Compare values between view and test data.
    Returns a tuple of (all_match, differences_df).
    """
    # Merge the two dataframes
    merged = pd.merge(
        view_data, 
        test_data,
        on=['date', 'id'],
        suffixes=('_view', '_test')
    )
    
    # Calculate absolute and relative differences
    merged['abs_diff'] = np.abs(merged['value_view'] - merged['value_test'])
    merged['rel_diff'] = merged['abs_diff'] / np.abs(merged['value_test'])
    
    # Check if values match within tolerance
    matches = (merged['abs_diff'] <= tolerance) | (merged['rel_diff'] <= tolerance)
    differences = merged[~matches]
    
    return matches.all(), differences, merged

def summarize_significant_deviations(merged_data: pd.DataFrame, threshold: float = 0.0001) -> pd.DataFrame:
    """
    Summarize columns with significant deviations (≥ 0.01%).
    Returns a DataFrame with summary statistics for each affected column.
    """
    # Filter for significant deviations
    significant = merged_data[merged_data['rel_diff'] >= threshold]
    
    if len(significant) == 0:
        return pd.DataFrame()
    
    # Group by column and calculate summary statistics
    summary = significant.groupby('id').agg({
        'rel_diff': ['count', 'mean', 'max'],
        'abs_diff': ['mean', 'max']
    }).round(6)
    
    # Flatten column names
    summary.columns = [f"{col[0]}_{col[1]}" for col in summary.columns]
    
    # Sort by maximum relative difference
    return summary.sort_values('rel_diff_max', ascending=False)

def main():
    """Main function to run tests."""
    conn = get_db_connection()
    
    try:
        # Get list of derived columns
        derived_cols = get_derived_columns()
        
        # Fetch data from view and test_data table
        view_data = fetch_data(conn, 'shiller_derived_view')
        test_data = fetch_data(conn, 'test_data')
        
        # Filter for derived columns only
        view_data = view_data[view_data['id'].isin(derived_cols)]
        test_data = test_data[test_data['id'].isin(derived_cols)]
        
        # Compare values
        all_match, differences, merged_data = compare_values(view_data, test_data)
        
        if all_match:
            logger.info("All derived values match within tolerance limits! ✅")
        else:
            logger.warning("Mismatches found in derived values! ❌")
            
            # Log detailed differences
            for _, row in differences.iterrows():
                logger.warning(
                    f"\nDate: {row['date']}"
                    f"\nColumn: {row['id']}"
                    f"\nView value: {row['value_view']}"
                    f"\nTest value: {row['value_test']}"
                    f"\nAbsolute difference: {row['abs_diff']}"
                    f"\nRelative difference: {row['rel_diff']}"
                    f"\n{'-'*50}"
                )
            
            # Summarize significant deviations
            logger.warning("\nColumns with significant deviations (≥ 0.01%):")
            summary = summarize_significant_deviations(merged_data)
            if not summary.empty:
                logger.warning("\nSummary Statistics:")
                logger.warning("\nColumn Details:")
                logger.warning(f"\n{summary.to_string()}")
                logger.warning("\nColumn Descriptions:")
                logger.warning("- rel_diff_count: Number of deviating values")
                logger.warning("- rel_diff_mean: Average relative difference")
                logger.warning("- rel_diff_max: Maximum relative difference")
                logger.warning("- abs_diff_mean: Average absolute difference")
                logger.warning("- abs_diff_max: Maximum absolute difference")
            else:
                logger.warning("No significant deviations found.")
            
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error during testing: {str(e)}")
        sys.exit(1)
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()
