# Architecture Assessment - financial_db

## Summary
This assessment reviews the runtime architecture for a small, laptop-first financial analysis project and focuses on improvements that keep the system lean, maintainable, and fast enough for local use.

Scope covered:
- `db_utils/`
- `data_fetchers/`
- `dashboard/`

Out of scope:
- `analyses/`
- notebooks
- historical planning docs

## Implementation Status Update (2026-02-14)

Status of findings F1-F9 after implementation:

| ID | Status | Evidence |
|---|---|---|
| F1 | Implemented | Shared DB-session batch ingest via `run_with_repository` loops in `data_fetchers/stock_prices.py`, `data_fetchers/commodities.py`, and `data_fetchers/factor_etfs.py`. |
| F2 | Implemented | Central identifier-safe query assembly in `db_utils/database.py` (`build_select_query`, `validate_identifier`, helpers) with tests in `tests/test_sql_query_builder.py`. |
| F3 | Implemented | Shared dataset descriptors and query helpers consolidated in `dashboard/data_access.py`; views now consume this layer. |
| F4 | Implemented | Metadata/data-access caching via `@st.cache_data` wrappers in `dashboard/data_access.py`. |
| F5 | Implemented | `data_fetchers/shiller_cape.py` refactored to argparse + timeout/retry + tempfile cleanup + helper tests. |
| F6 | Implemented | Lean runtime dependencies in `pyproject.toml`; optional groups split into `dashboard`, `analysis`, `dev`; lockfile synced in `uv.lock`. |
| F7 | Implemented | Public `close_connection_pool()` in `db_utils/database.py`; fixture-safe tests in `tests/test_database.py` no longer import private globals. |
| F8 | Implemented | Canonical docs root declared (`db_utils/paths.py`: `DOCS_ROOT`), with root pointers in `README.md`, `doc/README.md`, and `docs/README.md`. |
| F9 | Implemented | Dashboard query contract coverage added in `tests/test_dashboard_data_access.py` (dataset contracts + filter/date query semantics). |

### Remaining Gaps

- No benchmark timings were recorded for Scenario A (ingestion throughput before/after F1).
- Scenario C is partially covered (DB env/connection and fetcher guardrails), but no full failure-matrix report is documented.
- This document's original finding evidence line numbers remain a historical snapshot and may not match current file offsets.

## Current Architecture Snapshot
Runtime flow is clear and pragmatic:
1. Fetchers ingest external data and normalize to pandas (`data_fetchers/*`).
2. Repository layer persists into Postgres with batched upserts (`db_utils/repository.py`).
3. Dashboard reads via SQLAlchemy/pandas and renders with Streamlit (`dashboard/*`).

Strengths already in place:
- A reusable fetch-transform-save lifecycle via `BaseFetcher`.
- Batched persistence (`execute_values`) rather than row-by-row inserts.
- SQL-derived metrics colocated with schema bootstrap.
- Explicit date-range and filter-driven dashboard UI patterns.

Complexity hotspots by file size:
- `data_fetchers/ken_french.py` (519 lines)
- `data_fetchers/aqr.py` (478 lines)
- `db_utils/db_setup.sql` (438 lines)
- `dashboard/views/compare.py` (312 lines)
- `data_fetchers/open_asset_pricing.py` (292 lines)
- `data_fetchers/open_asset_pricing_parsers.py` (289 lines)

## Architecture Scorecard

| Dimension | Current Score (1-5) | Notes |
|---|---:|---|
| Boundary clarity | 3 | Core boundaries exist but query/data-access concerns are repeated across views. |
| Runtime efficiency (laptop) | 3 | Works for local use, but repeated DB session churn and metadata queries add avoidable overhead. |
| Maintainability | 3 | Good base abstractions, but large modules and repeated SQL/view logic increase change cost. |
| Operational robustness | 3 | Basic guardrails exist; pool lifecycle and legacy fetcher behavior need hardening. |
| Testability | 3 | Parser coverage is solid; dashboard/query contract coverage is thin. |

## Key Findings

### F1 - Per-symbol ingestion repeatedly opens/closes DB connections
Why it matters:
- Adds avoidable connection and transaction overhead on laptops during batch ingest.
- Makes ingestion runtime scale poorly with symbol count.

Evidence:
- `data_fetchers/base_fetcher.py:40` opens a DB connection inside every `save()`.
- `data_fetchers/stock_prices.py:69`
- `data_fetchers/factor_etfs.py:72`
- `data_fetchers/commodities.py:61`

Recommendation:
- Add a multi-asset ingest path that saves all symbols for one run within a shared DB connection.
- Keep current CLI UX but route loops through a batch method (`run_many`) to reduce connection churn.

### F2 - Dynamic SQL identifiers are spread across runtime code
Why it matters:
- Identifier interpolation (`table`, `column`) is duplicated and easy to drift.
- Harder to audit and test query safety/consistency.

Evidence:
- `db_utils/database.py:122` (`SELECT ... FROM {table}`)
- `db_utils/database.py:141`
- `db_utils/database.py:160`
- `dashboard/views/series.py:207`
- `dashboard/views/compare.py:257`
- `dashboard/views/prices.py:41`
- `dashboard/views/browser.py:68`

Recommendation:
- Introduce a small query-spec registry for allowed datasets/columns.
- Centralize SQL assembly in one helper module that validates identifiers against that registry.

### F3 - Dashboard data-access logic is duplicated across views
Why it matters:
- Changes to filters/date logic must be updated in many files.
- Increases bug risk and slows future feature changes.

Evidence:
- Repeated dataset metadata dicts and selection logic:
  - `dashboard/views/series.py:10`
  - `dashboard/views/compare.py:12`
  - `dashboard/views/prices.py:10`
  - `dashboard/views/browser.py:8`
- Repeated date window controls and query blocks:
  - `dashboard/views/series.py:193`
  - `dashboard/views/compare.py:177`
  - `dashboard/views/prices.py:33`
  - `dashboard/views/browser.py:58`

Recommendation:
- Create shared dashboard data descriptors and reusable query/selector helpers.
- Keep view files focused on presentation.

### F4 - Minimal caching leaves dashboard responsiveness on the table
Why it matters:
- Streamlit reruns trigger many metadata queries repeatedly (distinct IDs, date bounds).
- Unnecessary DB round-trips are costly on constrained local environments.

Evidence:
- Engine is cached (`dashboard/app.py:10`), but view-level metadata queries are not:
  - `dashboard/views/rates.py:28`
  - `dashboard/views/prices.py:22`
  - `dashboard/views/browser.py:38`
  - `dashboard/views/series.py:54`

Recommendation:
- Add `@st.cache_data` wrappers for stable metadata queries (distinct values, min/max dates, factor options).
- Use short TTL and clear cache controls where needed.

### F5 - One legacy fetcher diverges from project conventions
Why it matters:
- Inconsistent CLI, temp-file handling, and networking behavior create maintenance drag.
- This module is harder to reason about than the newer fetchers.

Evidence:
- Fixed temp path: `data_fetchers/shiller_cape.py:20`
- No timeout in request: `data_fetchers/shiller_cape.py:25`
- Manual `sys.argv` parsing vs argparse: `data_fetchers/shiller_cape.py:99`
- Mixed old/new style imports and script shape: `data_fetchers/shiller_cape.py:1`

Recommendation:
- Align `shiller_cape.py` with the newer fetcher pattern:
  - argparse CLI
  - timeout/retry behavior
  - tempfile usage
  - consistent entrypoint and logging

### F6 - Runtime dependency set is heavier than necessary
Why it matters:
- Slower installs and larger environments on simple laptops.
- Increases dependency conflict surface.

Evidence:
- Core dependencies include tooling/analysis packages and `pytest` in the default runtime set: `pyproject.toml:6`
- `pytest` also appears in dev dependency group: `pyproject.toml:20`, `pyproject.toml:25`

Recommendation:
- Split dependencies into lean runtime + optional extras (`dashboard`, `analysis`, `dev`).
- Keep default install minimal for ingestion + DB operations.

### F7 - DB connection-pool lifecycle and boundaries are underspecified
Why it matters:
- Global mutable pool can complicate tests and long-lived processes.
- Harder to explicitly teardown resources.

Evidence:
- Global pool singleton: `db_utils/database.py:14`
- Pool init path only, no explicit close/reset API: `db_utils/database.py:16`
- Tests import private global symbol: `tests/test_database.py:3`

Recommendation:
- Add explicit `close_connection_pool()` and test fixture helpers.
- Stop importing private globals in tests.

### F8 - Documentation root is split (`doc/` vs `docs/`)
Why it matters:
- Architectural docs become harder to discover and maintain.
- New contributors may update the wrong location.

Evidence:
- Main docs links point to `doc/`: `README.md:10`
- Path constants also point to `doc/`: `db_utils/paths.py:12`
- A separate `docs/` tree exists and is being used for plans.

Recommendation:
- Define one canonical docs root and add lightweight redirects or index pointers.
- Keep architecture/operations docs under the same root.

### F9 - Test coverage is strong for parsers, weak for dashboard/query paths
Why it matters:
- UI query regressions can slip through without detection.
- Architecture refactors in dashboard/data-access become riskier.

Evidence:
- Current tests focus on parsers and DB behavior:
  - `tests/test_openbb_client.py:1`
  - `tests/test_open_asset_pricing.py:1`
  - `tests/test_database.py:1`
  - `tests/test_shiller.py:1`
- No dashboard-specific tests are present in `tests/`.

Recommendation:
- Add lightweight tests for shared query-builder helpers and dataset registry contracts.
- Avoid full UI integration tests; target pure query-shaping functions first.

## Original Prioritized Backlog (Historical Snapshot)

| ID | Recommendation | Impact (1-5) | Effort (1-5) | Risk Reduction (1-5) | Runtime Overhead Change | Priority | Acceptance Criteria |
|---|---|---:|---:|---:|---|---|---|
| F1 | Batch multi-symbol ingest with shared DB session | 5 | 3 | 4 | Positive | Now | Ingesting N symbols opens one DB session per command, not per symbol. |
| F2 | Centralize and validate SQL identifier assembly | 5 | 3 | 5 | Neutral | Now | No ad-hoc identifier f-strings remain in dashboard runtime paths. |
| F4 | Add cached metadata query helpers in dashboard | 4 | 2 | 3 | Positive | Now | Distinct/date-bound queries use cached wrappers; rerender query count drops. |
| F5 | Refactor `shiller_cape.py` to modern fetcher conventions | 4 | 2 | 3 | Positive | Now | Uses argparse, timeout, tempfile, and consistent logging pattern. |
| F3 | Consolidate dashboard dataset/query helper layer | 4 | 3 | 4 | Neutral | Next | Shared dataset descriptors + helper functions are used by all views. |
| F7 | Add pool teardown API and fixture-safe test boundaries | 3 | 2 | 4 | Neutral | Next | Public pool-close helper exists; tests no longer import private pool global. |
| F6 | Split dependencies into minimal runtime and extras | 3 | 2 | 3 | Positive | Next | Default env installs only runtime deps; optional groups cover dashboard/dev/analysis. |
| F9 | Add dashboard/query contract tests | 3 | 2 | 3 | Neutral | Next | Query helper tests cover each dataset type and filter/date combinations. |
| F8 | Canonicalize docs root and add pointers | 2 | 1 | 2 | Neutral | Later | One docs root is declared and linked from README and path constants. |

## Validation Snapshot (Post-Implementation)

- Query/data-access and shared-helper regression suite:
  - `tests/test_dashboard_data_access.py`
  - `tests/test_sql_query_builder.py`
  - `tests/test_base_fetcher.py`
  - `tests/test_shiller_cape_cli.py`
  - `tests/test_paths.py`
  - `tests/test_database.py` (environment-dependent; skips when DB env is unavailable)
- Latest local run result: `34 passed, 3 skipped`.

## Potential Interface Changes (if backlog is implemented)
No mandatory public API changes are required for this assessment. Potential incremental interface changes:
- Add optional batch-oriented CLI behavior in price/factor fetchers (same commands, more efficient internals).
- Introduce a shared dashboard query-spec structure for datasets and filters.
- Add explicit DB pool lifecycle functions (`close_connection_pool`) in `db_utils.database`.

## Test Scenarios for Improvement Work

### Scenario A: Ingestion throughput on laptop
- Run existing multi-symbol ingests before/after F1.
- Compare wall time and number of DB connections created.
- Pass condition: lower runtime without behavior change.

### Scenario B: Dashboard query correctness after centralization
- For each dataset type (prices, macro, factors), verify:
  - filter semantics
  - date range behavior
  - output schema shape
- Pass condition: same data outputs as current implementation on sample ranges.

### Scenario C: Failure-path robustness
- Missing DB env vars (`POSTGRES_*`) should fail with clear errors.
- External fetch timeout/retry behavior should surface actionable error context.
- Pass condition: deterministic, concise failure messages and non-corrupt partial writes.

### Scenario D: Regression safety for SQL assembly
- Unit-test query helper for allowed identifiers only.
- Ensure unknown dataset/column definitions fail fast.
- Pass condition: no free-form table/column interpolation from UI state.

## Lean Guardrails (Do Not Add)
To keep the codebase lightweight:
- Do not add a heavy workflow orchestrator.
- Do not introduce a full migration framework unless schema change frequency materially increases.
- Do not add broad UI e2e automation for Streamlit pages; prefer query/helper unit tests.
- Do not add additional service containers beyond Postgres for routine local runs.
- Do not replace pandas + SQL with distributed or async stacks for this project size.

## Assumptions
- Primary target remains a single-user local laptop workflow.
- PostgreSQL remains the system of record.
- Streamlit remains the dashboard framework.
- Backward compatibility of current CLI entrypoints is preferred.

## Evidence Index
- `data_fetchers/base_fetcher.py:40`
- `data_fetchers/stock_prices.py:69`
- `data_fetchers/factor_etfs.py:72`
- `data_fetchers/commodities.py:61`
- `db_utils/database.py:14`
- `db_utils/database.py:122`
- `db_utils/database.py:141`
- `db_utils/database.py:160`
- `db_utils/repository.py:56`
- `dashboard/app.py:10`
- `dashboard/views/prices.py:22`
- `dashboard/views/prices.py:41`
- `dashboard/views/series.py:10`
- `dashboard/views/series.py:207`
- `dashboard/views/compare.py:12`
- `dashboard/views/compare.py:257`
- `dashboard/views/browser.py:8`
- `dashboard/views/browser.py:68`
- `data_fetchers/shiller_cape.py:20`
- `data_fetchers/shiller_cape.py:25`
- `data_fetchers/shiller_cape.py:99`
- `tests/test_database.py:3`
- `pyproject.toml:6`
- `pyproject.toml:20`
- `pyproject.toml:25`
- `README.md:10`
- `db_utils/paths.py:12`
