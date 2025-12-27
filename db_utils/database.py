#!/usr/bin/env python3

import psycopg2
from psycopg2 import pool
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from .schemas import get_schema
from .config import get_database_config

# Global variable to store the connection pool
_CONNECTION_POOL = None

def init_connection_pool(config: Dict[str, str], minconn: int = 1, maxconn: int = 10):
    """Initialize the global connection pool."""
    global _CONNECTION_POOL
    if _CONNECTION_POOL is None:
        # Ensure all required keys are present
        required_keys = ['dbname', 'user', 'password']
        missing_keys = [k for k in required_keys if not config.get(k)]
        if missing_keys:
            raise ValueError(f"Missing required database config keys: {', '.join(missing_keys)}")
        
        _CONNECTION_POOL = pool.ThreadedConnectionPool(minconn, maxconn, **config)
    return _CONNECTION_POOL

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
        self.pool = None

    def connect(self):
        """Get a connection from the pool."""
        global _CONNECTION_POOL
        if not self.config:
            raise ValueError("Database configuration not provided")
        
        if _CONNECTION_POOL is None:
            init_connection_pool(self.config)
        
        self.pool = _CONNECTION_POOL
        self.conn = self.pool.getconn()
        self.cursor = self.conn.cursor()

    def disconnect(self):
        """Return the connection to the pool."""
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn and self.pool:
            self.pool.putconn(self.conn)
            self.conn = None

    def __enter__(self):
        """Context manager entry point."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        if exc_type:
            if self.conn:
                self.conn.rollback()
        else:
            if self.conn:
                self.conn.commit()
        self.disconnect()

