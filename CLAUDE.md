# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a personal financial data management system that uses a PostgreSQL database running in Docker to store and analyze financial data from multiple sources (OpenBB providers plus Shiller CAPE data). The project includes Python data fetchers, database utilities, and SQL views for computing derived financial metrics.

## Development Environment

This project uses a devcontainer setup with Docker Compose. Two containers run:
- `devcontainer`: Development environment with Python and all dependencies
- `db`: PostgreSQL 15 database instance

Database connection parameters are read from environment variables:
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `POSTGRES_HOST` (defaults to 'localhost')
- `POSTGRES_PORT` (defaults to '5432')

### Package Management

This project uses **uv** (from Astral) for fast, modern Python package management:

- Dependencies are defined in `pyproject.toml` (PEP 621 standard)
- Lock file `uv.lock` ensures reproducible builds
- Core dependencies: pandas, psycopg2-binary, openbb, scikit-learn, jupyterlab, matplotlib, seaborn, xlrd, numpy

**Common uv commands:**
```bash
# Generate/update lock file after changing pyproject.toml
uv lock

# Add a new dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>

# Install/sync all dependencies (using lock file)
uv sync --system

# Install without using lock file
uv pip install -r pyproject.toml --system
```

The Dockerfile installs dependencies during build using `uv sync` (if `uv.lock` exists) or falls back to installing from `pyproject.toml` directly.

## Common Commands

### Database Setup
```bash
# Initialize database schema (creates all tables)
python db_utils/db_setup.py

# Reset database (drop all tables) and reinitialize
python db_utils/db_setup.py --reset
```

### Data Fetching
```bash
# Fetch Shiller CAPE data (requires URL to Shiller's Excel file)
python data_fetchers/shiller_cape.py <url>

# Fetch US Treasury rates (via OpenBB)
python data_fetchers/bonds.py
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_database.py
```

## Architecture

### Database Schema

Five main tables defined in `db_utils/db_setup.sql`:

1. **assets_prices**: Asset price history (composite PK: id, date)
2. **interest_rates**: Interest rate data (composite PK: date, region, maturity, currency)
3. **indices**: Market indices (composite PK: id, date)
4. **macro_data**: Raw macroeconomic data (composite PK: id, date)
5. **test_data**: Derived/computed data for testing (composite PK: id, date)

### Database Layer (`db_utils/database.py`)

The `DatabaseConnection` class provides a generic interface for writing data:
- Context manager for automatic connection handling
- `write_data()` method handles upserts (INSERT ... ON CONFLICT DO UPDATE)
- Table schemas defined in `TABLE_SCHEMAS` class attribute with columns and primary keys
- Automatic NumPy type conversion to Python native types

When adding new tables:
1. Add SQL CREATE statement to `db_utils/db_setup.sql`
2. Add schema definition to `DatabaseConnection.TABLE_SCHEMAS` in `db_utils/database.py`

### Data Fetchers Pattern

All data fetchers in `data_fetchers/` follow a similar pattern:
1. Fetch raw data from external source (API, file download)
2. Transform into DataFrame with required columns
3. Use `DatabaseConnection.write_data()` to upsert into appropriate table(s)

Column mapping is used when DataFrame columns don't match table columns exactly. Example from `shiller_cape.py`:
- Raw data columns are mapped via `shiller_cols.json` configuration
- Each mapping specifies: id, long_name, and type (raw vs derived)
- Raw data goes to `macro_data`, derived data goes to `test_data`

### Derived Data with SQL Views

Complex financial calculations are performed in SQL views rather than Python. The main example is `derived/shiller_cape.sql`:
- Creates `shiller_derived_view` that computes 13+ derived metrics
- Uses CTEs (WITH clauses) to build up calculations step by step
- Examples: real prices (CPI-adjusted), CAPE ratios, excess returns
- Calculations use window functions for rolling averages, lead/lag operations

This architecture allows efficient computation directly in the database and makes calculations auditable/transparent.

## Code Structure Notes

- `/data_fetchers/`: Scripts to fetch and load data from external sources
- `/db_utils/`: Database connection, schema definitions, and setup scripts
- `/derived/`: SQL files with views for computed/derived metrics
- `/tests/`: Test files (pytest-based)
- `/notebooks/`: Jupyter notebooks for analysis and experimentation
- `/scripts/`: Utility scripts (e.g., notebook cleaning)

## Database Connection Pattern

Always use the `DatabaseConnection` context manager:

```python
from db_utils.database import DatabaseConnection

with DatabaseConnection() as db:
    db.write_data(
        data=dataframe,
        table_name='macro_data',
        value_mapping={'df_col': 'table_col'}  # optional
    )
```

This ensures proper connection cleanup and transaction handling.
