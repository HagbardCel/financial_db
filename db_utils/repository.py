import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from psycopg2 import extras
from .schemas import get_schema
from .database import DatabaseConnection, validate_identifier

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
                      value_mapping: Optional[Dict[str, str]] = None,
                      batch_size: int = 500):
        """
        Saves a DataFrame to the specified table using an upsert (INSERT ON CONFLICT) strategy.
        
        Args:
            data: The DataFrame containing data to persist.
            table_name: The name of the database table.
            value_mapping: Optional mapping from DataFrame column names to table column names.
            batch_size: Number of rows per batch insert.
        """
        table_name = validate_identifier(table_name, "table")
        schema = get_schema(table_name)
        columns = schema['columns']
        primary_keys = schema['primary_keys']

        # If no mapping provided, assume DataFrame columns match table columns
        if value_mapping is None:
            value_mapping = {col: col for col in columns}

        if data.empty:
            return

        for col in columns:
            if col not in value_mapping:
                raise KeyError(f"Column '{col}' missing from value_mapping")
            if value_mapping[col] not in data.columns:
                raise KeyError(f"Column '{value_mapping[col]}' not found in DataFrame")

        # Create the SQL statement
        columns_str = ', '.join(columns)
        non_pk_cols = [col for col in columns if col not in primary_keys]
        if non_pk_cols:
            update_str = ', '.join([f"{col} = EXCLUDED.{col}" for col in non_pk_cols])
            conflict_clause = f"ON CONFLICT ({', '.join(primary_keys)}) DO UPDATE SET {update_str}"
        else:
            conflict_clause = f"ON CONFLICT ({', '.join(primary_keys)}) DO NOTHING"

        sql = f"INSERT INTO {table_name} ({columns_str}) VALUES %s {conflict_clause};"

        # Prepare and execute the statements
        if self.db.cursor is None:
            raise RuntimeError("Database cursor is not initialized. Are you in a connection context?")

        def normalize_value(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, np.generic):
                value = value.item()
            if pd.isna(value):
                return None
            return value

        mapped_cols = [value_mapping[col] for col in columns]
        batch = []
        for row in data[mapped_cols].itertuples(index=False, name=None):
            batch.append(tuple(normalize_value(value) for value in row))
            if len(batch) >= batch_size:
                extras.execute_values(self.db.cursor, sql, batch, page_size=batch_size)
                batch = []

        if batch:
            extras.execute_values(self.db.cursor, sql, batch, page_size=batch_size)
        
        # Transaction commit is handled by the DatabaseConnection context manager
        # or manually by the connection object.
