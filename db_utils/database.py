#!/usr/bin/env python3

import os
import psycopg2
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional

class DatabaseConnection:
    # Table schemas defining columns and primary keys for each table
    TABLE_SCHEMAS = {
        'assets_prices': {
            'columns': ['id', 'date', 'price_usd'],
            'primary_keys': ['id', 'date']
        },
        'interest_rates': {
            'columns': ['date', 'region', 'rate_type', 'maturity', 'interest_rate', 'currency'],
            'primary_keys': ['date', 'region', 'maturity', 'currency']
        },
        'indices': {
            'columns': ['id', 'date', 'index_name', 'value'],
            'primary_keys': ['id', 'date']
        },
        'macro_data': {
            'columns': ['id', 'date', 'long_name', 'value'],
            'primary_keys': ['id', 'date']
        },
        'test_data': {
            'columns': ['id', 'date', 'long_name', 'value'],
            'primary_keys': ['id', 'date']
        }
    }

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self):
        """Establish database connection using environment variables."""
        self.conn = psycopg2.connect(
            dbname=os.getenv('POSTGRES_DB'),
            user=os.getenv('POSTGRES_USER'),
            password=os.getenv('POSTGRES_PASSWORD'),
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432')
        )
        self.cursor = self.conn.cursor()

    def disconnect(self):
        """Close database connection and cursor."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry point."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        self.disconnect()

    def write_data(self, 
                   data: pd.DataFrame,
                   table_name: str,
                   value_mapping: Optional[Dict[str, str]] = None):
        """
        Generic function to write data to any table.
        
        Args:
            data: DataFrame containing the data to write
            table_name: Name of the target table
            value_mapping: Optional dictionary mapping DataFrame columns to table columns
        
        Raises:
            ValueError: If table_name is not found in TABLE_SCHEMAS
        """
        if table_name not in self.TABLE_SCHEMAS:
            raise ValueError(f"Unknown table: {table_name}. Must be one of {list(self.TABLE_SCHEMAS.keys())}")

        schema = self.TABLE_SCHEMAS[table_name]
        columns = schema['columns']
        primary_keys = schema['primary_keys']

        # If no mapping provided, assume DataFrame columns match table columns
        if value_mapping is None:
            value_mapping = {col: col for col in columns}

        # Create the SQL statements
        columns_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        update_str = ', '.join([f"{col} = EXCLUDED.{col}" 
                              for col in columns if col not in primary_keys])
        
        sql = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT ({', '.join(primary_keys)})
            DO UPDATE SET {update_str};
        """

        # Prepare and execute the statements
        for _, row in data.iterrows():
            values = []
            for col in columns:
                value = row[value_mapping[col]]
                # Convert NumPy types to native Python types
                if isinstance(value, np.generic):
                    value = value.item()
                values.append(value)
            
            self.cursor.execute(sql, tuple(values))
        
        self.conn.commit()
