# Implementation Plan: Database Configuration & Schema Separation

This plan addresses the first item in the [Roadmap](../roadmap.md): **Database Configuration & Schema Separation**.

## Goal
The goal is to decouple database configuration and table schemas from the `DatabaseConnection` class to improve maintainability, testability, and flexibility.

## Current State
- **Schemas**: Hardcoded in `DatabaseConnection.TABLE_SCHEMAS`.
- **Configuration**: `DatabaseConnection.connect()` calls `os.getenv` directly.

## Proposed Changes

### 1. Create `db_utils/schemas.py`
Extract the table schemas into a dedicated registry.

**File Content Structure:**
```python
from typing import Dict, List, Any

TABLE_SCHEMAS = {
    'assets_prices': {
        'columns': ['id', 'date', 'price_usd'],
        'primary_keys': ['id', 'date']
    },
    # ... other tables
}

def get_schema(table_name: str) -> Dict[str, Any]:
    if table_name not in TABLE_SCHEMAS:
        raise ValueError(f"Unknown table: {table_name}")
    return TABLE_SCHEMAS[table_name]
```

### 2. Create `db_utils/config.py`
Handle environment variable reading and configuration object creation distinct from the connection logic.

**File Content Structure:**
```python
import os
from typing import Dict

def get_database_config() -> Dict[str, str]:
    """
    Reads database configuration from environment variables.
    Returns a dictionary suitable for psycopg2.connect kwargs.
    """
    return {
        'dbname': os.getenv('POSTGRES_DB'),
        'user': os.getenv('POSTGRES_USER'),
        'password': os.getenv('POSTGRES_PASSWORD'),
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432')
    }
```

### 3. Refactor `db_utils/database.py`
Modify `DatabaseConnection` to accept configuration via `__init__` (Dependency Injection).

**Changes:**
- Remove `TABLE_SCHEMAS`.
- Import `get_schema` from `.schemas`.
- Update `__init__`:
```python
    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or get_database_config() # Optional: Fallback to env for backward compat or ease of use
        self.conn = None
        self.cursor = None
```
- Update `connect()`:
```python
    def connect(self):
        if not self.config:
             raise ValueError("Database configuration not provided")
        self.conn = psycopg2.connect(**self.config)
        self.cursor = self.conn.cursor()
```
- Update `write_data` to use `get_schema(table_name)`.

### 4. Update Consumers
Update scripts to inject the configuration.

**Files to Update:**
- `data_fetchers/shiller_cape.py`
- `data_fetchers/bonds.py`

**Usage Pattern:**
```python
from db_utils.database import DatabaseConnection
from db_utils.config import get_database_config

# ...
with DatabaseConnection(config=get_database_config()) as db:
    # ...
```

## Verification Plan

### Manual Verification
1.  Run `python data_fetchers/shiller_cape.py <url>` and verify data is written to DB.
2.  Run `python data_fetchers/bonds.py` and verify data is written to DB.
3.  Check if `DatabaseConnection` can be instantiated with valid config.

### Automated Tests
- If existing tests use `DatabaseConnection`, they might need updates if they mock `os.getenv` or `DatabaseConnection`.
- (Optional) Add unit tests for `get_database_config` and `get_schema`.
