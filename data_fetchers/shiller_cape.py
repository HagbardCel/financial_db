#!/usr/bin/env python3

import os
import sys
import requests
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd
import psycopg2
import json

def download_file(file_url: str, save_as: str) -> None:
    """Download a file from a URL and save it locally."""
    response = requests.get(file_url)
    response.raise_for_status()
    with open(save_as, "wb") as file:
        file.write(response.content)

def extract_column_names(file_path: str, sheet_name: str) -> list:
    """Extract and clean column names from the Excel file."""
    raw_columns = pd.read_excel(
        file_path, 
        sheet_name=sheet_name, 
        skiprows=1, 
        nrows=7, 
        header=None
    ).transpose()
    return [
        ' '.join(name.split()) 
        for name in raw_columns.apply(lambda x: ' '.join(x.dropna().astype(str)), axis=1).iloc[1:].tolist()
    ]

def parse_dates(file_path: str, sheet_name: str) -> pd.DatetimeIndex:
    """Parse and process the dates from the Excel file."""
    date_data = pd.read_excel(
        file_path, 
        sheet_name=sheet_name, 
        skiprows=7, 
        usecols=['Date'], 
        dtype={'Date': str}
    ).dropna()
    dates = pd.to_datetime(
        date_data['Date'].apply(lambda x: x + '0' if len(x) < 7 else x),
        format='%Y.%m'
    ) + MonthEnd(0)
    return dates

def process_main_data(file_path: str, sheet_name: str, col_names: list, nrows: int) -> pd.DataFrame:
    """Load and process the main data from the Excel file."""
    cape_data = pd.read_excel(
        file_path, 
        sheet_name=sheet_name, 
        skiprows=8, 
        header=None, 
        names=col_names, 
        nrows=nrows
    )
    cape_data.dropna(how='all', axis=1, inplace=True)
    cape_data.dropna(how='all', inplace=True)
    cape_data = cape_data.apply(pd.to_numeric, errors='coerce')
    return cape_data

def load_shiller_cape_data(file_url: str) -> pd.DataFrame:
    """
    Load and process Shiller CAPE data from a given URL.

    This function downloads an Excel file containing Shiller CAPE data,
    processes it, and returns a cleaned DataFrame with the data.
    """
    temp_file = '/tmp/shiller_cape.xls'
    sheet_name = 'Data'

    # Step 1: Download the file
    download_file(file_url, temp_file)

    # Step 2: Extract column names
    col_names = extract_column_names(temp_file, sheet_name)

    # Step 3: Parse and process dates
    dates = parse_dates(temp_file, sheet_name)

    # Step 4: Process main data
    cape_data = process_main_data(temp_file, sheet_name, col_names, len(dates))
    cape_data.index = dates  # Assign processed dates as index

    return cape_data

def write_to_database(data: pd.DataFrame, column_mapping: dict):
    """Write raw columns to the macro_data table in the database."""
    # Database connection parameters
    conn = psycopg2.connect(
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432')
    )
    cursor = conn.cursor()

    for date, row in data.iterrows():
        for raw_col, details in column_mapping.items():
            long_name = details['long_name']  # Use the long_name from the JSON
            column_id = details['id']  # Use the id from the JSON
            value = row[raw_col]
            if pd.notna(value):
                # Convert NumPy types to native Python types
                value = value.item() if isinstance(value, np.generic) else value
                cursor.execute(
                    """
                    INSERT INTO macro_data (id, date, long_name, value)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id, date) DO UPDATE
                    SET value = EXCLUDED.value;
                    """,
                    (column_id, date, long_name, value)
                )

    conn.commit()
    cursor.close()
    conn.close()

def main():
    if len(sys.argv) != 2:
        print("Usage: python shiller_cape.py <url>")
        sys.exit(1)

    file_url = sys.argv[1]

    # Load the column mapping from the JSON file
    with open('data_fetchers/shiller_cols.json', 'r') as f:
        column_mapping = json.load(f)['raw_data']

    # Apply load_shiller_cape_data to the provided URL
    cape_data = load_shiller_cape_data(file_url)

    # Write the raw columns to the database
    write_to_database(cape_data, column_mapping)

if __name__ == "__main__":
    main()