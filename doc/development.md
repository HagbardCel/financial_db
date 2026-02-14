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
-   Install core runtime dependencies using `uv`
-   Spin up a generic PostgreSQL database container

## Package Management

We use `uv` for fast and reliable dependency management.

-   **Sync Dependencies**:
    ```bash
    uv sync
    ```
-   **Sync Optional Dependency Sets**:
    ```bash
    uv sync --group dashboard --group analysis --group dev
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

Database access requires these environment variables:
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional: `POSTGRES_HOST`, `POSTGRES_PORT`).
We keep these in `.devcontainer/.env` (or a local `.env`) and do not commit personal editor settings.

### Initialization
To set up the database schema (create tables):
```bash
python db_utils/db_setup.py
```

### Resetting
To drop all tables and start fresh (WARNING: Data will be lost):
```bash
python db_utils/db_setup.py --reset --yes
```

## Running Data Fetchers

Data fetchers are located in `data_fetchers/` and can be run individually from the repo root:

**Shiller CAPE Data**:
```bash
python -m data_fetchers.shiller_cape --url <url_to_excel_file>
```
Legacy positional URL is still supported:
```bash
python -m data_fetchers.shiller_cape <url_to_excel_file>
```
Optional resilience flags:
```bash
python -m data_fetchers.shiller_cape --url <url_to_excel_file> --timeout 30 --retries 3 --retry-backoff 1.0
```

**Treasury Rates (OpenBB)**:
```bash
python -m data_fetchers.bonds
```

**Equity Prices (OpenBB)**:
```bash
python -m data_fetchers.stock_prices AAPL MSFT
```
Defaults to adjusted close (when available). To force raw close:
```bash
python -m data_fetchers.stock_prices --use-raw-close AAPL MSFT
```

**Commodity Prices (OpenBB)**:
```bash
python -m data_fetchers.commodities
```

**Gold Prices (OpenBB + CSV)**:
```bash
python -m data_fetchers.gold_prices
```

**Ken French datasets (Factors + Portfolios)**:
```bash
python -m data_fetchers.ken_french
```
Fetch only factors:
```bash
python -m data_fetchers.ken_french factors
```
Fetch only portfolios:
```bash
python -m data_fetchers.ken_french portfolios
```

## Ingest Smoke Check

Run a lightweight, repeatable ingest check that records per-command runtime and success/failure counts in JSON:

```bash
python scripts/ingest_smoke_check.py \
  --command "python -m data_fetchers.stock_prices AAPL MSFT --start 2024-01-01 --end 2024-03-31" \
  --command "python -m data_fetchers.commodities GC=F SI=F --start 2024-01-01 --end 2024-03-31" \
  --runs 2 \
  --label "baseline" \
  --output derived/reports/ingest_smoke_baseline.json
```

The summary includes:
- command durations (`min` / `max` / `avg`)
- success/failure counts
- DB environment variable presence check (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`)

### OpenBB Provider Configuration
OpenBB pulls data via providers; set provider keys via env vars as needed. Optional overrides:
- `OPENBB_EQUITY_PROVIDER`
- `OPENBB_COMMODITY_PROVIDER`
- `OPENBB_RATES_PROVIDER`
- `OPENBB_EQUITY_HISTORICAL_PATH` (default: `equity.price.historical`)
- `OPENBB_COMMODITY_HISTORICAL_PATH` (default: `derivatives.futures.historical`)
- `OPENBB_FRED_SERIES_PATH` (default: `economy.fred_series`)

For FRED-backed rates, set `FRED_API_KEY` (or `OPENBB_FRED_API_KEY`).

OpenBB dependency footprint: this repo installs the full OpenBB meta-package for now. If dependency weight becomes an issue, revisit slimming providers by switching to `openbb-core` plus the specific provider packages we use.

OpenBB model layer: normalization stays DataFrame-based in `data_fetchers/openbb_client.py` rather than relying on OpenBB models for now.

Gold prices are sourced from the datasets/gold-prices monthly CSV:
`https://github.com/datasets/gold-prices/blob/main/data/monthly.csv?utm_source=chatgpt.com`

## Dashboard

Run the Streamlit dashboard:
```bash
uv run streamlit run dashboard/app.py
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

Run only integration tests:
```bash
pytest -m integration
```
