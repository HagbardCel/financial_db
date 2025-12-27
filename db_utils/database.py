#!/usr/bin/env python3

import psycopg2
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from .schemas import get_schema
from .config import get_database_config

class DatabaseConnection:
    def __init__(self, config: Optional[Dict[str, str]] = None):
        """
        Initialize the database connection.
        
        Args:
            config: Optional dictionary with database connection parameters.
                   If not provided, it will be read from environment variables.
        """
        self.config = config or get_database_config()
        self.conn = None
        self.cursor = None

    def connect(self):
        """Establish database connection using the provided configuration."""
        if not self.config:
            raise ValueError("Database configuration not provided")
        
        # Ensure all required keys are present (basic validation)
        required_keys = ['dbname', 'user', 'password']
        missing_keys = [k for k in required_keys if not self.config.get(k)]
        if missing_keys:
            raise ValueError(f"Missing required database config keys: {', '.join(missing_keys)}")

        self.conn = psycopg2.connect(**self.config)
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
        """
        schema = get_schema(table_name)
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
