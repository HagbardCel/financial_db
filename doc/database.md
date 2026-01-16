# Database Schema Documentation

This document details the database structure, including tables, views, and connection management for the `financial_db` project.

## Tables

The database consists of the following primary tables, defined in `db_utils/db_setup.sql` and mapped in `db_utils/database.py`.

### `assets_prices`
Stores historical price data for various financial assets.
-   `id` (TEXT): Unique identifier for the asset (e.g., ticker symbol).
-   `date` (DATE): Observational date.
-   `price_usd` (NUMERIC): Price of the asset in USD.
-   **Primary Key**: `(id, date)`

### `interest_rates`
Stores historical interest rate data across different regions and maturities.
-   `date` (DATE): Observational date.
-   `region` (TEXT): Geographic region (e.g., 'US', 'EU').
-   `rate_type` (TEXT): Type of rate (e.g., 'government_bond').
-   `maturity` (TEXT): Term to maturity (e.g., '10Y', '3M').
-   `interest_rate` (NUMERIC): The interest rate value in percent.
-   `currency` (TEXT): Currency code (e.g., 'USD').
-   **Primary Key**: `(date, region, maturity, currency)`

### `indices`
Stores historical values for market indices.
-   `id` (TEXT): Unique identifier for the index.
-   `date` (DATE): Observational date.
-   `index_name` (TEXT): Human-readable name of the index.
-   `value` (NUMERIC): The index value.
-   **Primary Key**: `(id, date)`

### `stock_prices`
Stores historical price data for equities and other ticker-based assets.
-   `symbol` (TEXT): Ticker symbol.
-   `date` (DATE): Observational date.
-   `open` (NUMERIC): Open price.
-   `high` (NUMERIC): High price.
-   `low` (NUMERIC): Low price.
-   `close` (NUMERIC): Close price.
-   `volume` (BIGINT): Trade volume.
-   **Primary Key**: `(symbol, date)`

### `commodity_prices`
Stores historical price data for commodities.
-   `symbol` (TEXT): Ticker symbol (e.g., `GC=F`).
-   `date` (DATE): Observational date.
-   `open` (NUMERIC): Open price.
-   `high` (NUMERIC): High price.
-   `low` (NUMERIC): Low price.
-   `close` (NUMERIC): Close price.
-   `volume` (BIGINT): Trade volume.
-   **Primary Key**: `(symbol, date)`

### `macro_data`
Stores general macroeconomic indicators.
-   `id` (TEXT): Identifier for the metric (e.g., 'CPI', 'UNRATE').
-   `date` (DATE): Observational date.
-   `long_name` (TEXT): Descriptive name of the metric.
-   `value` (NUMERIC): The recorded value.
-   **Primary Key**: `(id, date)`

### `test_data`
Used for storing non-standard or derived data during testing or development phases.
-   `id` (TEXT): Identifier.
-   `date` (DATE): Observational date.
-   `long_name` (TEXT): Description.
-   `value` (NUMERIC): Value.
-   **Primary Key**: `(id, date)`

## Views

### `shiller_derived_view`
Defined in `db_utils/db_setup.sql` (mirrors `derived/shiller_cape.sql`). This view computes advanced valuation metrics based on Shiller's data.
-   **Calculations**:
    -   Real Prices (CPI-adjusted)
    -   Real Earnings and Dividends
    -   CAPE Ratio (Cyclically Adjusted Price-to-Earnings)
    -   Excess Returns
-   **Logic**: Uses Common Table Expressions (CTEs) and window functions to perform rolling calculations over historical data.

## Connection Management

Database connections are managed via the `DatabaseConnection` class in `db_utils/database.py`.

-   **Environment Variables**: Connection parameters (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`) are loaded from the environment.
-   **Context Manager**: The class implements `__enter__` and `__exit__` to ensure connections are closed properly.
-   **Type Handling**: Automatically converts NumPy types to native Python types before insertion.
