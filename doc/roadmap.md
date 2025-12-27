# Project Roadmap & Improvement Proposals

This document outlines proposed structural and architectural improvements for the `financial_db` project. These suggestions aim to enhance maintainability, scalability, and code quality.

## Architectural Improvements

### 1. Database Configuration & Schema Separation
**Current State**: Table schemas are hardcoded in the `DatabaseConnection` class.
**Proposal**:
-   Extract `TABLE_SCHEMAS` to a dedicated registry (e.g., `schemas.py` or `schemas.json`).
-   Use dependency injection for database configuration instead of direct `os.getenv` calls deep in the code.

### 2. Connection Pooling
**Current State**: A new database connection is established for every operation (context manager entry).
**Proposal**:
-   Implement `psycopg2.pool.SimpleConnectionPool` or `ThreadedConnectionPool`.
-   Reuse connections to reduce overhead, especially for frequent small writes.

### 3. Standardized Data Fetching
**Current State**: Each fetcher script has its own logic for downloading and processing.
**Proposal**:
-   Create a `BaseFetcher` abstract class.
-   Enforce a standard lifecycle: `fetch()` -> `transform()` -> `save()`.
-   This makes adding new data sources (e.g., Bloomberg, Alpha Vantage) consistent and faster.

### 4. Robust Path Handling
**Current State**: Scripts often rely on purely relative paths or expected current working directories.
**Proposal**:
-   Use Python's `pathlib` for robust, absolute path resolution relative to the script's location.
-   Ensure scripts can be called from any directory without `FileNotFoundError`.

### 5. Repository Pattern
**Current State**: SQL construction is handled generically in `DatabaseConnection.write_data`.
**Proposal**:
-   For more complex queries, consider a Repository pattern or a lightweight data access layer.
-   This separates SQL logic from business logic / data fetching logic.

## Future Features (Backlog)
-   **Dashboard**: A simple web UI (Streamlit or Dash) to visualize the data in `shiller_derived_view`.
-   **Automated Scheduling**: A cron job or Celery task to run fetchers daily/weekly.
-   **Data Validation**: Pydantic models to validate data before it hits the database.
