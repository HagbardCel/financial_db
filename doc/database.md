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
-   `close` (NUMERIC): Close price (stored as **adjusted close when available**, otherwise raw close).
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

### `factor_returns`
Stores factor return series (e.g., Fama-French).
-   `source` (TEXT): Data source identifier (e.g., `ken_french`, `aqr`, `open_asset_pricing`).
-   `factor_set` (TEXT): Factor set name (e.g., `ff3`, `ff5`, `mom`).
-   `frequency` (CHAR(1)): Observation frequency (`M` for monthly).
-   `factor` (TEXT): Factor label (e.g., `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA`, `UMD`, `RF`).
-   `date` (DATE): Observational date (month-end for monthly data).
-   `value` (NUMERIC): Factor return stored as a **decimal** (e.g., `0.0123` = `1.23%`).
-   `unit` (TEXT): Unit marker (default `decimal`).
-   **Primary Key**: `(source, factor_set, frequency, factor, date)`

### `portfolio_returns`
Stores long-only portfolio return series (e.g., AQR and Ken French deciles).
-   `source` (TEXT): Data source identifier (e.g., `aqr`, `ken_french`).
-   `portfolio_set` (TEXT): Portfolio set name (e.g., `qmj_10_deciles`, `10_portfolios_formed_on_be-me`).
-   `universe` (TEXT): Universe or region tag (e.g., `USA`, `Global`, `NA`).
-   `frequency` (CHAR(1)): Observation frequency (`M` for monthly).
-   `portfolio` (TEXT): Portfolio label (e.g., `Lo 10`, `2`, …, `Hi 10`).
-   `date` (DATE): Observational date (month-end for monthly data).
-   `value` (NUMERIC): Portfolio return stored as a **decimal** (e.g., `0.0123` = `1.23%`).
-   `unit` (TEXT): Unit marker (default `decimal`).
-   **Primary Key**: `(source, portfolio_set, universe, frequency, portfolio, date)`

### `characteristic_metadata`
Stores characteristic/signal metadata (identifier + descriptive fields).
-   `source` (TEXT): Data source identifier (e.g., `open_asset_pricing`).
-   `characteristic_set` (TEXT): Characteristic collection identifier (e.g., `oapd_signals`).
-   `characteristic` (TEXT): Characteristic/signal code used in time-series tables.
-   `name` (TEXT): Human-readable characteristic name (nullable).
-   `category` (TEXT): Characteristic category/group (nullable).
-   `paper_ref` (TEXT): Citation/reference field (nullable).
-   `notes` (TEXT): Additional notes/metadata (nullable).
-   **Primary Key**: `(source, characteristic_set, characteristic)`

### `portfolio_characteristics`
Stores portfolio-level characteristic scores over time.
-   `source` (TEXT): Data source identifier.
-   `portfolio_set` (TEXT): Portfolio family identifier.
-   `universe` (TEXT): Universe/region label.
-   `frequency` (CHAR(1)): Observation frequency (`M`/`D`).
-   `portfolio` (TEXT): Portfolio label within the family.
-   `date` (DATE): Observation date.
-   `characteristic` (TEXT): Characteristic/signal code.
-   `value` (NUMERIC): Portfolio-level characteristic score.
-   `unit` (TEXT): Unit marker (default `raw`).
-   **Primary Key**: `(source, portfolio_set, universe, frequency, portfolio, date, characteristic)`

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
