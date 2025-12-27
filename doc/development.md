# Development Guide

## Environment Setup

This project is configured to run inside a **Devcontainer**. This ensures a consistent development environment with all dependencies pre-installed.

### Prerequisites
-   Docker Desktop (or Docker Engine)
-   Visual Studio Code
-   VS Code Dev Containers extension

### Getting Started
1.  Open the project folder in VS Code.
2.  When prompted, click "Reopen in Container".
3.  Wait for the container to build and the post-create commands to finish.

The devcontainer will automatically:
-   Install Python 3.10+
-   Install project dependencies using `uv`
-   Spin up a generic PostgreSQL database container

## Package Management

We use `uv` for fast and reliable dependency management.

-   **Sync Dependencies**:
    ```bash
    uv sync
    ```
-   **Add a Package**:
    ```bash
    uv add pandas
    ```
-   **Add a Dev Dependency**:
    ```bash
    uv add --dev pytest
    ```

## Database Management

### Initialization
To set up the database schema (create tables):
```bash
python db_utils/db_setup.py
```

### Resetting
To drop all tables and start fresh (WARNING: Data will be lost):
```bash
python db_utils/db_setup.py --reset
```

## Running Data Fetchers

Data fetchers are located in `data_fetchers/` and can be run individually:

**Shiller CAPE Data**:
```bash
python data_fetchers/shiller_cape.py <url_to_excel_file>
```

**Bond Yields (FRED)**:
```bash
python data_fetchers/bonds.py
```

## Testing

Tests are written using `pytest` and located in the `tests/` directory.

Run all tests:
```bash
pytest tests/
```

Run a specific test file:
```bash
pytest tests/test_database.py
```
