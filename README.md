# Financial Data Local Database

## Overview
This repository provides a robust setup for managing financial data locally using Docker and PostgreSQL. It includes a pipeline for fetching data from major sources (like Yahoo Finance and FRED) and tools for computing advanced financial metrics.

## Documentation
-   **[Architecture Overview](doc/architecture.md)**: High-level system design and components.
-   **[Database Schema](doc/database.md)**: Detailed breakdown of tables and views.
-   **[Development Guide](doc/development.md)**: Setup instructions and workflows.

## Features
-   **Containerized Environment**: Fully isolated setup using Docker.
-   **Automated Ingestion**: Scripts to specific fetch financial data.
-   **Advanced Analytics**: SQL-based computation of derived metrics (e.g., CAPE).
-   **Modern Tooling**: Uses `uv` for fast package management.

## Quick Start
1.  Clone the repository.
2.  Open in VS Code and reopen in Devcontainer.
3.  Initialize the database: `python db_utils/db_setup.py`
4.  Run a fetcher from the repo root: `python -m data_fetchers.bonds`

## License
Personal use only. Not for public distribution.
