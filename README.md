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
2.  Create `.env` from `.env.example`, set `PROJECT_DATA_DIR` to an absolute path, and run `mkdir -p "$PROJECT_DATA_DIR/db"` before first start.
3.  Open in VS Code and reopen in Devcontainer.
    The devcontainer installs core runtime dependencies into the project venv at `/workspaces/financial_db/.venv`.
    Verify with: `python -c "import pandas, openbb; print('ok')"`
    Optional sets can be added as needed: `uv sync --group dashboard --group analysis --group dev`
4.  Initialize the database: `python db_utils/db_setup.py`
5.  Run a fetcher from the repo root: `python -m data_fetchers.bonds`

### Host Without Devcontainer
1.  Install Docker or Docker Desktop and [`uv`](https://docs.astral.sh/uv/).
2.  Create `.env` from `.env.example` and configure local database settings, provider secrets, and an absolute `PROJECT_DATA_DIR`.
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

## EODHD Snapshot Archive

Set `RAW_DATA_DIR` to the parent raw-data directory and `EODHD_API_TOKEN` in `.env`.
The managed archive remains at `${RAW_DATA_DIR}/eodhd`; it is not stored inside the repository.

```bash
uv run python -m data_fetchers.eodhd download
uv run python -m data_fetchers.eodhd reconcile-state
uv run python -m data_fetchers.eodhd reconcile-state --apply
uv run python -m data_fetchers.eodhd refresh
uv run python -m data_fetchers.eodhd ingest
uv run python -m data_fetchers.eodhd report metadata --snapshot-date latest
uv run python -m data_fetchers.eodhd universes build --universe eodhd_us_listed_common_equities_v1
```

Bare `download` and `refresh` run the resumable full-archive preset: exchange and symbol-change metadata, active and delisted symbols, daily prices, and eligible dividends and splits. Completed per-symbol files refresh after seven days. Pass explicit scope flags for selective runs; add `--raw-json` only when compressed vendor JSON copies are needed.
Bare `ingest` loads metadata only. Loading every archived parquet dataset into PostgreSQL requires the explicit `ingest all --confirm-all-datasets` command.

Back up `${RAW_DATA_DIR}/eodhd` and its `state/eodhd_all_world_snapshot.sqlite3` checkpoint database together.

## Configuration

The project uses layered configuration:

- `.env`: untracked local secrets and machine-specific absolute paths
- `.env.example`: committed bootstrap template
- `config/settings.toml`: committed non-secret project defaults
- `config/data_refresh.toml`: committed refresh orchestration and stable fetcher arguments
- `compose.yml`: container wiring, including the container-only `POSTGRES_HOST=db` override

Host-side Make targets read `.env` and connect to PostgreSQL through `localhost`. For scheduled local jobs, run `make -C /path/to/financial_db refresh` or explicitly export the same environment before invoking Python.
Direct Python commands that use the shared configuration helpers also load the root `.env` without overriding exported shell values.

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
