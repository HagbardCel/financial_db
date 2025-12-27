import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from .schemas import get_schema
from .database import DatabaseConnection

class DataRepository:
    """
    Repository class to handle data persistence logic, separating SQL construction
    from database connection management.
    """
    def __init__(self, db_connection: DatabaseConnection):
        self.db = db_connection

    def save_dataframe(self, 
                      data: pd.DataFrame, 
                      table_name: str, 
                      value_mapping: Optional[Dict[str, str]] = None):
        """
        Saves a DataFrame to the specified table using an upsert (INSERT ON CONFLICT) strategy.
        
        Args:
            data: The DataFrame containing data to persist.
            table_name: The name of the database table.
            value_mapping: Optional mapping from DataFrame column names to table column names.
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
        if self.db.cursor is None:
            raise RuntimeError("Database cursor is not initialized. Are you in a connection context?")

        for _, row in data.iterrows():
            values = []
            for col in columns:
                try:
                    df_col = value_mapping[col]
                    value = row[df_col]
                except KeyError:
                    raise KeyError(f"Column '{col}' not found in DataFrame or value_mapping")

                # Convert NumPy types to native Python types
                if isinstance(value, np.generic):
                    value = value.item()
                # Handle NaN for SQL NULL
                if pd.isna(value):
                    value = None
                    
                values.append(value)
            
            self.db.cursor.execute(sql, tuple(values))
        
        # Transaction commit is handled by the DatabaseConnection context manager
        # or manually by the connection object.
