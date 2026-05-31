# Development Guide

## Environment Setup

This project supports two local development paths:
- **Devcontainer**: VS Code opens the repository inside the application container and starts PostgreSQL beside it.
- **Host without devcontainer**: Python commands run on the host, while PostgreSQL runs through the existing Compose service.

### Devcontainer Prerequisites
-   Docker Desktop (or Docker Engine)
-   Visual Studio Code
-   VS Code Dev Containers extension

### Devcontainer Getting Started
1.  Open the project folder in VS Code.
2.  When prompted, click "Reopen in Container".
3.  Wait for the container to build and the post-create commands to finish.

The devcontainer will automatically:
-   Install Python 3.10+
-   Install core runtime dependencies using `uv`
-   Spin up a generic PostgreSQL database container

### Host Prerequisites
-   Docker Desktop or Docker Engine with Docker Compose
-   Python compatible with `pyproject.toml`
-   `uv`

### Host Getting Started
Run these commands from the repository root:

```bash
uv sync --group dashboard --group analysis --group dev
make db-up
make db-init
make refresh
```

Both workflows read `.devcontainer/.env`. The devcontainer uses `POSTGRES_HOST=db` because commands run inside the Compose network. The Makefile overrides `POSTGRES_HOST=localhost` for host-side Python commands because the database port is published to the host.

The Makefile wraps the standard commands:

```bash
make db-up      # start PostgreSQL
make db-down    # stop PostgreSQL
make db-init    # run uv run python db_utils/db_setup.py
make refresh    # run uv run python -m data_fetchers.refresh_all
make dashboard  # run uv run streamlit run dashboard/app.py
make test       # run uv run pytest tests/
```

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
We keep these in `.devcontainer/.env`. Do not commit local secrets.

Provider secrets follow the same pattern. Add them to `.devcontainer/.env`.

### Initialization
To set up the database schema (create tables):
```bash
uv run python db_utils/db_setup.py
```

Host-side Makefile equivalent:

```bash
make db-init
```

### Resetting
To drop all tables and start fresh (WARNING: Data will be lost):
```bash
uv run python db_utils/db_setup.py --reset --yes
```

## Running Data Fetchers

Data fetchers are located in `data_fetchers/` and can be run individually from the repo root:

### Refresh Everything Configured for This Repo

The canonical operator command is:

```bash
uv run python -m data_fetchers.refresh_all
```

Host-side Makefile equivalent:

```bash
make refresh
```

It reads `config/data_refresh.toml`, runs enabled fetchers in config order, and prints a summary of successes, failures, and skipped entries.
To capture a complete run log, redirect both streams:

```bash
uv run python -m data_fetchers.refresh_all >out_test 2>&1
```

Useful commands:

```bash
uv run python -m data_fetchers.refresh_all --list
uv run python -m data_fetchers.refresh_all --only ken_french aqr
uv run python -m data_fetchers.refresh_all --skip factor_etfs
uv run python -m data_fetchers.refresh_all --fail-fast
uv run python -m data_fetchers.refresh_all --config path/to/custom_refresh.toml
```

Config notes:
- `order` controls execution order.
- Each `[fetchers.<name>]` section defines `module`, `enabled`, `description`, and `args`.
- `args` is forwarded unchanged to the target fetcher CLI.
- Sources that need operator-provided parameters stay disabled by default, except `shiller_cape` when `config/data_refresh.toml` contains a current Excel URL:
  - `openbb_equity_prices` needs explicit ticker symbols.
  - stock momentum Xetra/Stooq inputs need operator-provided raw files.
  - `shiller_cape` needs a current upstream Excel URL and is currently enabled in the default config.
  - `open_asset_pricing_portfolio_characteristics` needs `--portfolio-scores-url`.

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
Explicit provider:
```bash
python -m data_fetchers.bonds --provider fred
```

**Equity Price Bars (OpenBB)**:
```bash
python -m data_fetchers.openbb_equity_prices AAPL MSFT
```
Defaults to adjusted close (when available). To force raw close:
```bash
python -m data_fetchers.openbb_equity_prices --use-raw-close AAPL MSFT
```
These rows are stored in `equity_price_bars`; the old `stock_prices` table is no longer part of the active schema.

**Stock Momentum Free Prototype Inputs**:
```bash
python -m data_fetchers.xetra_instruments --config config/stock_momentum_free.toml
python -m data_fetchers.stooq_prices --config config/stock_momentum_free.toml --zip derived/stock_momentum/raw/stooq/bulk/stooq_daily.zip
python -m data_fetchers.ecb_fx --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.build_price_panel --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.build_momentum_panel --config config/stock_momentum_free.toml --frequency monthly
python -m analyses.stock_momentum.run_backtest --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.validate --config config/stock_momentum_free.toml
```

The stock momentum free prototype uses a current tradability proxy, incomplete delisting coverage, and Stooq prices with unverified adjustment quality. Use it for engineering and signal intuition, not final allocation conclusions.
Xetra and ECB are downloaded automatically from public sources by default. Stooq bulk files are still manual for now; use `--file` or `--zip` after downloading them.

**Commodity Prices (OpenBB)**:
```bash
python -m data_fetchers.commodities
```

**Gold Prices (CSV normalized via OpenBB helper)**:
```bash
python -m data_fetchers.gold_prices
```

**Oil benchmark prices**:
```bash
python -m data_fetchers.oil_prices
```
This ingests:
- `USOIL`: long-run U.S. crude benchmark from official EIA history
- `WTI`: monthly WTI benchmark spot series
- `BRENT`: monthly Brent benchmark spot series
Targeted reruns:
```bash
python -m data_fetchers.oil_prices --provider fred --series USOIL
python -m data_fetchers.oil_prices --provider fred --series WTI BRENT
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

**AQR datasets (Factors + Portfolios)**:
```bash
python -m data_fetchers.aqr
```

**Open Asset Pricing factors + metadata**:
```bash
python -m data_fetchers.open_asset_pricing
```

## Ingest Smoke Check

Run a lightweight, repeatable ingest check that records per-command runtime and success/failure counts in JSON:

```bash
python scripts/ingest_smoke_check.py \
  --command "python -m data_fetchers.openbb_equity_prices AAPL MSFT --start 2024-01-01 --end 2024-03-31" \
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

For FRED-backed rates and oil spot benchmarks, use `FRED_API_KEY` as the canonical secret name and put it in the environment file for the workflow you are using:

```dotenv
FRED_API_KEY=your_fred_api_key_here
```

Notes:
- `FRED_API_KEY` is the preferred repo-wide name.
- `OPENBB_FRED_API_KEY` is still accepted for backward compatibility.
- A temporary shell override also works, for example `export FRED_API_KEY=...`.
- Use `.devcontainer/.env` for both devcontainer and host-side Makefile runs.

OpenBB dependency footprint: this repo installs the full OpenBB meta-package for now. If dependency weight becomes an issue, revisit slimming providers by switching to `openbb-core` plus the specific provider packages we use.

OpenBB model layer: normalization stays DataFrame-based in `data_fetchers/openbb_client.py` rather than relying on OpenBB models for now.

Gold prices are sourced from the datasets/gold-prices monthly CSV:
`https://github.com/datasets/gold-prices/blob/main/data/monthly.csv?utm_source=chatgpt.com`

## Dashboard

The dashboard is a local Streamlit app. Run these commands from the repo root.

Install the optional dashboard dependencies if they are not already present:
```bash
uv sync --group dashboard
```

Make sure the normal database environment variables are available before starting it:
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional: `POSTGRES_HOST`, `POSTGRES_PORT`).

Start the dashboard:
```bash
uv run streamlit run dashboard/app.py
```

Host-side Makefile equivalent:

```bash
make dashboard
```

Streamlit prints the local URL after startup, usually `http://localhost:8501`. In a devcontainer, use the forwarded `8501` port from VS Code if the browser does not open automatically.

## Testing

Tests are written using `pytest` and located in the `tests/` directory.

Run all tests:
```bash
uv run pytest tests/
```

Run a specific test file:
```bash
uv run pytest tests/test_database.py
```

Run only integration tests:
```bash
uv run pytest -m integration
```
