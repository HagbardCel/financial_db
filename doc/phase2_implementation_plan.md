# Phase 2 Implementation Plan: Architectural & Structural Improvements

This document explicitly details the steps required to implement Phase 2 of the roadmap. It is designed for developers of all levels, including those new to the codebase.

## Objective
Enhance the `financial_db` project's maintainability, robustness, and performance by:
1.  Fixing path handling issues.
2.  Decoupling database schemas.
3.  Implementing connection pooling.
4.  Introducing a Repository pattern.
5.  Standardizing data fetchers.

---

## 1. Robust Path Handling

**Problem**: Scripts currently use relative paths like `'data_fetchers/shiller_cols.json'`. This fails if the script is run from a different directory (e.g., inside `tests/` or from root).

**Implementation Guide**:
1.  Identify all occurrences of hardcoded relative paths (e.g., `open('data_fetchers/...')`).
2.  Use Python's `pathlib` to resolve paths relative to the *current file*.

**Example Pattern**:
```python
from pathlib import Path

# Get the directory where the current script resides
CURRENT_DIR = Path(__file__).parent
# Resolve the path to the resource relative to the script
JSON_PATH = CURRENT_DIR / 'shiller_cols.json'

# Use it
with open(JSON_PATH, 'r') as f:
    ...
```

**Action Items**:
-   [ ] Search for `open(` calls in `data_fetchers/*.py` and `scripts/*.py`.
-   [ ] Refactor `shiller_cape.py` to use `Path(__file__).parent` to locate `shiller_cols.json`.

---

## 2. Database Configuration & Schema Separation

**Problem**: While `schemas.py` exists, the specific database configuration logic and schema usage can be tightened. The roadmap suggests decoupling and dependency injection.

**Implementation Guide**:
1.  **Review `db_utils/schemas.py`**:
    -   Ensure it contains all table definitions.
    -   Consider converting it to a JSON or YAML file if we want to support non-Python consumers, but keeping it as `schemas.py` is fine for now. It currently serves as a registry.
2.  **Dependency Injection in `DatabaseConnection`**:
    -   Currently, `DatabaseConnection` can take a `config` dict. This is good.
    -   Ensure that `get_database_config()` in `db_utils/config.py` is robust (e.g., handling missing env vars with clear errors).

**Action Items**:
-   [ ] Verify `db_utils/config.py` raises clear errors if critical env vars (`POSTGRES_USER`, etc.) are missing.
-   [ ] Ensure `DatabaseConnection` defaults to `get_database_config()` only if no config is passed (already largely implemented, just verify robustness).

---

## 3. Connection Pooling

**Problem**: `DatabaseConnection` opens a new TCP connection to Postgres for every usage (every `with DatabaseConnection()...` block). This is slow and resource-intensive.

**Implementation Guide**:
We will modify `db_utils/database.py` to use `psycopg2.pool`.

**Step-by-Step Changes**:
1.  **Create a Singleton Pool**:
    -   In `db_utils/database.py`, create a module-level variable `_CONNECTION_POOL = None`.
    -   Create a function `init_connection_pool()` that initializes `ThreadedConnectionPool` (minconn=1, maxconn=10).
2.  **Modify `DatabaseConnection`**:
    -   Instead of `psycopg2.connect()`, use `_CONNECTION_POOL.getconn()`.
    -   In `disconnect()` (or `__exit__`), use `_CONNECTION_POOL.putconn(self.conn)`.
    -   **Important**: Do not close the connection in `__exit__`, just return it to the pool.

**Code Snippet (Concept)**:
```python
from psycopg2 import pool

_POOL = None

def get_pool(config):
    global _POOL
    if _POOL is None:
        _POOL = pool.ThreadedConnectionPool(1, 10, **config)
    return _POOL

class DatabaseConnection:
    def connect(self):
        self.pool = get_pool(self.config)
        self.conn = self.pool.getconn()
    
    def disconnect(self):
        if self.conn:
            self.pool.putconn(self.conn)
            self.conn = None
```

**Action Items**:
-   [ ] Implement the singleton pool pattern in `db_utils/database.py`.
-   [ ] Update `test_database.py` (which is empty) to test that connections are reused (check connection ID or similar).

---

## 4. Repository Pattern

**Problem**: SQL generation logic (`INSERT ... ON CONFLICT`) is mixed into `DatabaseConnection.write_data`. This limits flexibility for complex queries.

**Implementation Guide**:
Create `db_utils/repository.py`.

1.  **Define `BaseRepository`**:
    -   It should hold a `DatabaseConnection` instance.
    -   It should provide methods like `save_batch(data, table_name)`.
2.  **Extract write logic**:
    -   Move the `write_data` logic from `DatabaseConnection` to this repository class.
    -   `DatabaseConnection` should strictly handle *connecting* and *executing* raw SQL, not *generating* it.

**New Structure**:
```python
# db_utils/repository.py
class DataRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def save_dataframe(self, df, table_name):
        # ... logic mapped from current write_data ...
        sql = "INSERT INTO ..."
        self.db.cursor.execute(sql, ...)
```

**Action Items**:
-   [ ] Create `db_utils/repository.py`.
-   [ ] Move SQL generation logic there.
-   [ ] Update fetchers to use `DataRepository` instead of calling `db.write_data`.

---

## 5. Standardized BaseFetcher

**Problem**: `shiller_cape.py` has custom logic. Adding a new fetcher (e.g., Yahoo Finance) requires copy-pasting structure.

**Implementation Guide**:
Create `data_fetchers/base_fetcher.py`.

1.  **Define Abstract Base Class**:
    ```python
    from abc import ABC, abstractmethod

    class BaseFetcher(ABC):
        @abstractmethod
        def fetch_data(self):
            """Download raw data."""
            pass
        
        @abstractmethod
        def transform(self, raw_data):
            """Clean and format data."""
            pass
            
        def run(self):
            """Orchestrates the pipeline."""
            data = self.fetch_data()
            clean_data = self.transform(data)
            self.save(clean_data)

        def save(self, data):
            # Use Repository to save
            pass
    ```

2.  **Refactor `shiller_cape.py`**:
    -   Make `ShillerCapeFetcher` inherit from `BaseFetcher`.
    -   Move `download_file` -> `fetch_data`.
    -   Move processing logic -> `transform`.

**Action Items**:
-   [ ] Create `data_fetchers/base_fetcher.py`.
-   [ ] Refactor `shiller_cape.py` to inherit from `BaseFetcher`.

---
