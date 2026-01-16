import os
import sys
from pathlib import Path

import requests
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd
from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config
import json

from typing import Dict, Union

class ShillerCapeFetcher(BaseFetcher):
    def __init__(self, file_url: str, column_mapping: dict, db_config: dict = None):
        super().__init__(db_config)
        self.file_url = file_url
        self.column_mapping = column_mapping
        self.temp_file = '/tmp/shiller_cape.xls'
        self.sheet_name = 'Data'

    def fetch(self) -> str:
        """Download the Excel file and return the path."""
        response = requests.get(self.file_url)
        response.raise_for_status()
        with open(self.temp_file, "wb") as file:
            file.write(response.content)
        return self.temp_file

    def _extract_column_names(self, file_path: str) -> list:
        raw_columns = pd.read_excel(
            file_path, 
            sheet_name=self.sheet_name, 
            skiprows=1, 
            nrows=7, 
            header=None
        ).transpose()
        return [
            ' '.join(name.split()) 
            for name in raw_columns.apply(lambda x: ' '.join(x.dropna().astype(str)), axis=1).iloc[1:].tolist()
        ]

    def _parse_dates(self, file_path: str) -> pd.DatetimeIndex:
        date_data = pd.read_excel(
            file_path, 
            sheet_name=self.sheet_name, 
            skiprows=7, 
            usecols=['Date'], 
            dtype={'Date': str}
        ).dropna()
        dates = pd.to_datetime(
            date_data['Date'].apply(lambda x: x + '0' if len(x) < 7 else x),
            format='%Y.%m'
        ) + MonthEnd(0)
        return dates

    def transform(self, file_path: str) -> Dict[str, pd.DataFrame]:
        col_names = self._extract_column_names(file_path)
        dates = self._parse_dates(file_path)
        
        cape_data = pd.read_excel(
            file_path, 
            sheet_name=self.sheet_name, 
            skiprows=8, 
            header=None, 
            names=col_names, 
            nrows=len(dates)
        )
        cape_data.dropna(how='all', axis=1, inplace=True)
        cape_data.dropna(how='all', inplace=True)
        cape_data = cape_data.apply(pd.to_numeric, errors='coerce')
        cape_data.index = dates

        # Prepare data for macro_data and test_data tables
        records = []
        for date, row in cape_data.iterrows():
            for raw_col, details in self.column_mapping.items():
                value = row[raw_col]
                if pd.notna(value):
                    records.append({
                        'date': date,
                        'id': details['id'],
                        'long_name': details['long_name'],
                        'value': value,
                        'type': details['type']
                    })
        
        df = pd.DataFrame(records)
        macro_data = df[df['type'] != 'derived'].drop('type', axis=1)
        test_data = df[df['type'] == 'derived'].drop('type', axis=1)
        
        return {
            'macro_data': macro_data,
            'test_data': test_data
        }

def main():
    if len(sys.argv) != 2:
        print("Usage: python shiller_cape.py <url>")
        sys.exit(1)

    file_url = sys.argv[1]
    
    current_dir = Path(__file__).parent
    config_path = current_dir / 'shiller_cols.json'

    with open(config_path, 'r') as f:
        column_mapping = json.load(f)

    fetcher = ShillerCapeFetcher(file_url, column_mapping, db_config=get_database_config())
    fetcher.run()

if __name__ == "__main__":
    main()
