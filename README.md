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
1.  Clone the repository.
2.  Open in VS Code and reopen in Devcontainer.
    The devcontainer installs core runtime dependencies into the project venv at `/workspaces/financial_db/.venv`.
    Verify with: `python -c "import pandas, openbb; print('ok')"`
    Optional sets can be added as needed: `uv sync --group dashboard --group analysis --group dev`
3.  Initialize the database: `python db_utils/db_setup.py`
4.  Run a fetcher from the repo root: `python -m data_fetchers.bonds`

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
The database currently includes factor returns, portfolio returns, stock and commodity prices, Treasury rates, Shiller macro series, oil benchmark series, and Open Asset Pricing metadata. Some sources run in the default refresh workflow, while sources that require explicit parameters stay disabled until configured.

See [`doc/data_sources.md`](doc/data_sources.md) for the full table-by-table inventory and source catalog.

## License
Personal use only. Not for public distribution.
