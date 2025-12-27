# Phase 5 Implementation Plan: Advanced Repository Pattern (Data Access Layer)

## Goal
The goal of this phase is to complete the **Repository Pattern** implementation by extending the existing `DataRepository` to support **Read Operations** and creating **Domain-Specific Repositories**. This will create a clean Data Access Layer (DAL), decoupling SQL logic from the application logic (e.g., future Dashboards or Analysis scripts) and ensuring that all database interactions are consistent, reusable, and testable.

Currently, the project supports generic *writes* via `DataRepository.save_dataframe`, but *reads* are unimplemented or likely to be ad-hoc. We will fix this.

## Prerequisites
-   Completion of Basic Database Configuration (Phase 1/2).
-   `db_utils/repository.py` existence (Generic Write support).
-   `db_utils/database.py` with Connection Pooling support.

---

## Step 1: Restructure `db_utils` for Repositories

To avoid a monolithic `repository.py`, we will categorize repositories by domain (e.g., specific to Shiller data, Yahoo data, etc.).

1.  **Create a Repository Package**:
    *   Create directory: `db_utils/repos/`
    *   Create `db_utils/repos/__init__.py` (empty) to make it a package.
2.  **Move/Refactor Base Repository**:
    *   Ideally, we keep the abstract/base repository in `db_utils/repository.py` or move it to `db_utils/repos/base.py`.
    *   *Decision*: For backward compatibility with simpler scripts, we will keep `DataRepository` in `db_utils/repository.py` but rename it to `BaseRepository` in our minds (or actually rename it if safe) and have it support both generic Read/Write.

## Step 2: Enhance `DataRepository` for Reads

We need generic methods to query data without writing raw SQL in the business logic.

1.  **Modify** `db_utils/repository.py`:
    *   Import `pandas as pd` (already there).
    *   Add a method: `read_dataframe(self, query: str, params: tuple = None) -> pd.DataFrame`.
    *   This method should:
        *   Accept a SQL query and optional parameters.
        *   Use `pd.read_sql` or manual cursor execution + DataFrame construction.
    *   *Junior Dev Note*: `pd.read_sql` requires a SQLAlchemy connection or a pure DBAPI2 connection. Our `DatabaseConnection` gives a cursor/connection. `pd.read_sql(sql, con=self.db.conn, params=params)` should work with `psycopg2` connection objects.

    ```python
    def read_dataframe(self, query: str, params: Optional[Tuple] = None) -> pd.DataFrame:
        """
        Executes a SELECT query and returns the result as a Pandas DataFrame.
        """
        if self.db.conn is None:
             self.db.connect() # Ensure connected
        
        try:
            # Pandas read_sql supports psycopg2 connection objects
            return pd.read_sql(query, self.db.conn, params=params)
        except Exception as e:
            # Log error
            raise e
    ```

2.  **Add Helper Methods (Optional but good)**:
    *   `find_all(table_name: str) -> pd.DataFrame`

## Step 3: Implement `ShillerRepository`

We want to encapsulate queries specific to the Shiller CAPE dataset.

1.  **Create File**: `db_utils/repos/shiller.py`.
2.  **Define Class**: `class ShillerRepository(DataRepository):`.
3.  **Implement Domain Methods**:
    *   Instead of writing `SELECT * FROM shiller_data WHERE date > ...` in your dashboard code, you will call:
    *   `get_cape_data(start_date=None, end_date=None) -> pd.DataFrame`
    
    ```python
    from db_utils.repository import DataRepository
    
    class ShillerRepository(DataRepository):
        def get_data_by_range(self, start_date=None, end_date=None, table_name='shiller_macro'):
            query = f"SELECT * FROM {table_name} WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND date_col >= %s" # Ensure column name is correct (e.g. 'date')
                params.append(start_date)
            if end_date:
                query += " AND date_col <= %s"
                params.append(end_date)
                
            return self.read_dataframe(query, tuple(params))
    
        def get_latest_cape_ratio(self):
            query = "SELECT date, value FROM shiller_macro WHERE id = 'CAPE' ORDER BY date DESC LIMIT 1"
            return self.read_dataframe(query)
    ```

## Step 4: Validate with a Test Script

To ensure the new Repository layer works as expected without breaking existing functionality.

1.  **Create Script**: `scripts/test_repository_layer.py`.
2.  **Logic**:
    *   Initialize `DatabaseConnection`.
    *   Initialize `ShillerRepository(db)`.
    *   Call `get_latest_cape_ratio()`.
    *   Print the result.
    *   *Verify*: It should print a DataFrame with the latest date and CAPE value.

## Implementation Details & "User Manual" for Junior Devs

### Files to touch:
1.  `db_utils/repository.py` (Edit)
2.  `db_utils/repos/` (Create Directory)
3.  `db_utils/repos/__init__.py` (Create)
4.  `db_utils/repos/shiller.py` (Create)
5.  `scripts/test_repository_layer.py` (Create)

### Detailed Code Changes

#### 1. `db_utils/repository.py`
Add the `read_dataframe` method to the `DataRepository` class.

```python
    def read_dataframe(self, query: str, params: Optional[Tuple] = None) -> pd.DataFrame:
        """
        Executes a generic SQL SELECT query using pandas.
        
        Args:
            query (str): The SQL query string.
            params (tuple, optional): Parameters to bind to the query for safety.
        
        Returns:
            pd.DataFrame: Result set.
        """
        # Ensure connection is active
        if self.db.conn is None:
            raise ConnectionError("Database connection is not active.")
            
        # Use pandas read_sql for convenience
        # Note: generic psycopg2 connection works fine here
        return pd.read_sql(sql=query, con=self.db.conn, params=params)
```

#### 2. `db_utils/repos/shiller.py`
This is where the magic happens. We hide the SQL complexity here.

```python
from typing import Optional
import pandas as pd
from db_utils.repository import DataRepository

class ShillerRepository(DataRepository):
    """
    Repository for accessing Shiller CAPE data.
    """
    
    def get_macro_data(self, 
                       indicator_ids: list = None, 
                       start_date: str = None, 
                       end_date: str = None) -> pd.DataFrame:
        """
        Fetch macro data (CPI, CAPE, IR) with optional filtering.
        """
        # Base query
        query = "SELECT * FROM macro_data WHERE 1=1" # Assumes table name is macro_data
        params = []
        
        if indicator_ids:
            # secure "IN" clause handling is tricky with %s, so generic approach:
            # For simplicity in this phase, we might iterate or use tuple templating
            # But let's stick to simple scalar filters or no filter for junior dev ease
            pass 
            
        if start_date:
            query += " AND date >= %s"
            params.append(start_date)
            
        if end_date:
            query += " AND date <= %s"
            params.append(end_date)
            
        query += " ORDER BY date ASC"
        
        return self.read_dataframe(query, tuple(params))
```

## Checklist
- [ ] Update `DataRepository` in `db_utils/repository.py` with `read_dataframe`.
- [ ] Create `db_utils/repos/` directory.
- [ ] Create `db_utils/repos/shiller.py` with `ShillerRepository`.
- [ ] Create `scripts/test_repository_layer.py` and verify `read_dataframe` works (e.g., SELECT 1).
- [ ] (Optional) Update `base_fetcher.py` if it needs to read anything (unlikely for now).

## Troubleshooting Noteseed
-   **Pandas read_sql Error**: If `read_sql` complains about the connection, ensure `psycopg2` is installed and the connection is not closed.
-   **Table Names**: Verify exact table names in `db_utils/schemas.py` or the DB directly (e.g. `macro_data`, `shiller_data`).
