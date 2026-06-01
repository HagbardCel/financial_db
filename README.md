# Financial Data Local Database

## Overview
This repository provides a robust setup for managing financial data locally using Docker and PostgreSQL. It includes a pipeline for fetching data via the OpenBB SDK (multi-provider) and tools for computing advanced financial metrics.

Gold prices are sourced from the datasets/gold-prices monthly CSV:
`https://github.com/datasets/gold-prices/blob/main/data/monthly.csv?utm_source=chatgpt.com`

## Documentation
Canonical docs root: `doc/`
-   **[Architecture Overview](doc/architecture.md)**: High-level system design and components.
-   **[Database Schema](doc/database.md)**: Detailed breakdown of tables and views.
-   **[Data Sources Catalog](doc/data_sources.md)**: What populates each table + upstream source links.
-   **[Development Guide](doc/development.md)**: Setup instructions and workflows.

## Features
-   **Containerized Environment**: Fully isolated setup using Docker.
-   **Automated Ingestion**: Scripts to specific fetch financial data.
-   **Advanced Analytics**: SQL-based computation of derived metrics (e.g., CAPE).
-   **Modern Tooling**: Uses `uv` for fast package management.

## Quick Start

### Devcontainer
1.  Clone the repository.
2.  Set `PROJECT_DATA_DIR` (absolute path) in `.devcontainer/.env` and run `mkdir -p "$PROJECT_DATA_DIR/db"` before first start.
3.  Open in VS Code and reopen in Devcontainer.
    The devcontainer installs core runtime dependencies into the project venv at `/workspaces/financial_db/.venv`.
    Verify with: `python -c "import pandas, openbb; print('ok')"`
    Optional sets can be added as needed: `uv sync --group dashboard --group analysis --group dev`
4.  Initialize the database: `python db_utils/db_setup.py`
5.  Run a fetcher from the repo root: `python -m data_fetchers.bonds`

### Host Without Devcontainer
1.  Install Docker or Docker Desktop and [`uv`](https://docs.astral.sh/uv/).
2.  Configure `.devcontainer/.env` with local database settings, provider secrets, and an absolute `PROJECT_DATA_DIR`.
    PostgreSQL persists under `$PROJECT_DATA_DIR/db`. See [Development Guide](doc/development.md#database-management).
    The Makefile reads this file and uses `POSTGRES_HOST=localhost` for host-side Python commands.
3.  Install dependencies:
    ```bash
    uv sync --group dashboard --group analysis --group dev
    ```
4.  Start PostgreSQL and initialize the schema:
    ```bash
    make db-up
    make db-init
    ```
5.  Run the main refresh workflow:
    ```bash
    make refresh
    ```

Useful local targets:
```bash
make dashboard
make test
make db-down
```

## Refresh All Configured Data
The canonical refresh workflow is:

```bash
python -m data_fetchers.refresh_all
```

This command reads [`config/data_refresh.toml`](config/data_refresh.toml), runs enabled fetchers in order, and leaves sources that need manual parameters disabled by default.

Useful variants:

```bash
python -m data_fetchers.refresh_all --list
python -m data_fetchers.refresh_all --only ken_french aqr
python -m data_fetchers.refresh_all --skip gold_prices
python -m data_fetchers.refresh_all --fail-fast
```

## Available Data Overview
The database currently includes factor returns, portfolio returns, normalized equity price bars, commodity prices, Treasury rates, Shiller macro series, oil benchmark series, Open Asset Pricing metadata, and stock momentum prototype tables. Some sources run in the default refresh workflow, while sources that require explicit parameters stay disabled until configured.

See [`doc/data_sources.md`](doc/data_sources.md) for the full table-by-table inventory and source catalog.

## License
Personal use only. Not for public distribution.
