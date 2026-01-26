# Project Assessment: financial_db

## Scope and method
- Reviewed repository structure, core Python modules, SQL definitions, and tests.
- Focused on architectural cohesion, engineering practices, maintainability, and documentation gaps.

## Current architecture summary
- Local PostgreSQL database, managed via `db_utils/db_setup.sql` and `db_utils/db_setup.py`.
- Data ingestion via standalone fetchers in `data_fetchers/`, each following a fetch -> transform -> save lifecycle.
- Persistence handled by a lightweight repository (`db_utils/repository.py`) and a connection pool wrapper (`db_utils/database.py`).
- Derived metrics computed in SQL (`derived/shiller_cape.sql`).

## Strengths
- Clear separation between fetch, transform, and persistence logic.
- Reasonable use of a repository layer to isolate SQL construction.
- Database-centric computation for derived metrics avoids re-computation in Python.
- Devcontainer-centric workflow and basic development docs are already in place.

## Key issues and risks
1. **Schema drift and source-of-truth ambiguity**
   - `db_utils/schemas.py` defines `stock_prices`, but `db_utils/db_setup.sql` does not create it.
   - `doc/database.md` omits `stock_prices` entirely.
   - Derived view definitions live outside the standard setup flow.

2. **Packaging and import hygiene**
   - Fetchers manipulate `sys.path`, which is fragile and obscures expected run context.
   - The intended “run from repo root” flow is not enforced or documented, leading to inconsistent imports.

4. **Inefficient insert strategy**
   - `DataRepository.save_dataframe` performs row-by-row inserts, which will be slow for large datasets.
   - No batching or `COPY`-based ingestion pipeline is used.

3. **Configuration and environment handling**
   - Configuration relies on environment variables only; no `.env` support or config file fallback.
   - Tests depend on a live database with expected environment variables, and will fail silently without them.

4. **Testing approach is inconsistent**
   - `tests/test_shiller.py` is a script-like integration test with `sys.exit`, not a true pytest test.
   - No unit tests for transformations or schema validation, and no isolated test database fixture.

5. **Operational risk in destructive commands**
   - `db_utils/db_setup.py --reset` drops all tables without a secondary confirmation step.

6. **Missing dependencies and data validation**
   - `requests` is used but not listed in `pyproject.toml` dependencies.
   - No validation layer for incoming data schemas (column presence, data types, ranges).

## Architectural improvements
### 1. Keep “out-of-the-box” execution while cleaning imports
- Standardize the run context: require running scripts from repo root and document it.
- Replace `sys.path` manipulation with `python -m data_fetchers.stock_prices` from repo root.
- Optionally add a small `scripts/run_fetcher.py` or `Makefile` targets to keep usage consistent.

### 2. Establish a single schema source-of-truth without migrations
- Keep `db_utils/db_setup.sql` as the canonical schema definition.
- Expand it to include **all tables** and **all views** (e.g., incorporate `derived/shiller_cape.sql`).
- Add a lightweight `schema_version` table that is updated by `db_setup.py` for traceability.

### 3. Improve ingestion performance and reliability
- Use `psycopg2.extras.execute_values` or `COPY` for bulk inserts.
- Add incremental fetching windows where possible to avoid repeated full-history pulls.
- Add retries, backoff, and basic error classification for external data sources.

### 4. Formalize configuration management
- Introduce a configuration object (e.g., Pydantic settings) with `.env` support.
- Provide configuration profiles (local/dev/test/prod) and document precedence.

### 5. Strengthen data modeling and metadata
- Add a `metrics` table to store canonical metadata (id, long_name, units, source).
- Add foreign keys from `macro_data` and `test_data` to `metrics`.
- Define indexes for common query dimensions (date, id, symbol).

### 6. Increase test coverage and consistency
- Split tests into unit and integration suites.
- Use pytest fixtures and markers for DB tests.
- Add transformation-level tests (input -> output shape/fields).
- Consider using testcontainers or a disposable Docker DB for CI.

### 7. Improve operational safety
- Add a confirmation step for `--reset`, or require `--force` and `--yes`.
- Emit structured logs and write ingestion metadata to a `ingestion_runs` table.

## Leaner, more maintainable structure
- Keep layers thin and explicit: **fetchers** (I/O), **transforms** (pure data shaping), **db** (persistence), **pipelines** (orchestration), **cli** (user entrypoints).
- Preserve the current top-level layout but enforce a “run from repo root” contract to avoid import hacks.
- Centralize DB schema definitions and use consistent naming across code, SQL, and docs.
- Keep derived SQL under a single directory with a naming convention and include it in setup.
- Favor pure functions for transformations; make side effects visible in orchestration code.

## Documentation extensions recommended
1. **Data sources catalog**
   - Source URLs, refresh cadence, licensing, and backfill rules.

2. **Data dictionary**
   - Table-level and column-level definitions, units, and data provenance.

3. **Schema lifecycle (without migrations)**
   - How `db_setup.sql` is the canonical schema, how views are included, and how schema changes are rolled out.

4. **Operational runbook**
   - How to bootstrap the database, run ingestion, troubleshoot failures, and recover.

5. **Testing strategy**
   - What is unit vs integration, how to provision DB for tests, expected env vars.

6. **Architecture decisions (ADRs)**
   - Why Postgres, why SQL-derived metrics, why specific fetchers, and future evolution.

7. **Security and secrets**
   - How credentials are managed locally, storage of API keys, and safe defaults.

## Suggested priorities (short-term)
1. Align schema definitions across `db_utils/schemas.py`, `db_utils/db_setup.sql`, and `doc/database.md`.
2. Include derived view creation in `db_utils/db_setup.sql`.
3. Replace row-by-row inserts with batch ingestion.
4. Replace `sys.path` hacks with a documented repo-root run pattern and `python -m` usage.
5. Convert `tests/test_shiller.py` into a real pytest integration test.

## Concrete short-term tasks
1. **Schema alignment** (done)
   - Add missing tables to `db_utils/db_setup.sql` to match `db_utils/schemas.py`.
   - Update `doc/database.md` to include any new or missing tables (e.g., `stock_prices`).
   - Acceptance: `db_setup.py` creates all tables referenced by `get_schema`, and docs match schema.

2. **Include derived views in setup** (done)
   - Append `derived/shiller_cape.sql` into `db_utils/db_setup.sql` (or load it from `db_setup.py`).
   - Acceptance: Running `python db_utils/db_setup.py` creates `shiller_derived_view` without manual steps.

3. **Batch ingestion** (done)
   - Replace per-row `cursor.execute` in `db_utils/repository.py` with `psycopg2.extras.execute_values`.
   - Add a simple batch size parameter and measure with a large DataFrame.
   - Acceptance: Inserts use a single `execute_values` call per batch, and existing functionality remains intact.

4. **Repo-root execution standard** (done)
   - Remove `sys.path` manipulation from `data_fetchers/*.py`.
   - Update `doc/development.md` and `README.md` with `python -m data_fetchers.stock_prices ...` examples.
   - Acceptance: Fetchers run from repo root without `sys.path` hacks.

5. **Pytest integration test cleanup** (done)
   - Refactor `tests/test_shiller.py` into pytest-style tests without `sys.exit`.
   - Add markers for DB integration tests (e.g., `@pytest.mark.integration`).
   - Acceptance: `pytest tests/test_shiller.py` returns proper pass/fail status.
