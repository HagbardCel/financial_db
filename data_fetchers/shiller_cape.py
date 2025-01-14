#!/usr/bin/env python3

import os
import sys
import requests
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd
from db_utils.database import DatabaseConnection
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
    """Write raw and derived columns to the appropriate tables in the database."""
    # Prepare data for macro_data and test_data tables
    records = []
    for date, row in data.iterrows():
        for raw_col, details in column_mapping.items():
            value = row[raw_col]
            if pd.notna(value):
                records.append({
                    'date': date,
                    'id': details['id'],
                    'long_name': details['long_name'],
                    'value': value,
                    'type': details['type']
                })
    
    # Convert records to DataFrame
    df = pd.DataFrame(records)
    
    # Split data into macro and test data
    macro_data = df[df['type'] != 'derived'].drop('type', axis=1)
    test_data = df[df['type'] == 'derived'].drop('type', axis=1)
    
    with DatabaseConnection() as db:
        if not macro_data.empty:
            db.write_data(
                data=macro_data,
                table_name='macro_data'
            )
        if not test_data.empty:
            db.write_data(
                data=test_data,
                table_name='test_data'
            )

def main():
    if len(sys.argv) != 2:
        print("Usage: python shiller_cape.py <url>")
        sys.exit(1)

    file_url = sys.argv[1]

    # Load the column mapping from the JSON file
    with open('data_fetchers/shiller_cols.json', 'r') as f:
        column_mapping = json.load(f)  # No need to access ['raw_data'] anymore

    # Apply load_shiller_cape_data to the provided URL
    cape_data = load_shiller_cape_data(file_url)

    # Write the raw and derived columns to the database
    write_to_database(cape_data, column_mapping)

if __name__ == "__main__":
    main()