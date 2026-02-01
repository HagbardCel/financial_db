# Implementation Plan: Fama-French Factors (Ken French Data Library)

## Goal
Ingest monthly Fama-French factor returns (including Momentum and FF5, plus the included risk-free rate) from the Ken French Data Library into PostgreSQL, and expose them in the Streamlit dashboard for exploration and analysis.

## Why This Matters
- Provides a consistent reference dataset for return attribution, correlation, and general factor exploration.
- Keeps factor data first-class (separate table) rather than mixing with `macro_data`.
- Includes `RF` for completeness and future excess-return work, without requiring any “RF application” in the MVP.

## Scope (Phased)
### Phase 1 (MVP): Monthly factors + display
1. **Monthly factor sets**
   - **FF3 + RF:** `Mkt-RF`, `SMB`, `HML`, `RF`
   - **Momentum:** `UMD` (and/or `Mom` depending on the specific dataset naming)
   - **FF5 + RF:** `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA`, `RF`
2. **Dashboard integration**
   - Make the factors discoverable in the dashboard “Series Explorer” and “Compare & Correlate”.
   - Add a dedicated “Factors” page for factor-specific views (stats + correlation).

### Phase 2 (Optional): Factor models / regressions
- Not planned right now; keep this as a later extension once ingestion + visualization is stable.

### Phase 3 (Optional): Add daily frequency
- Add daily factor ingestion + daily regressions once monthly is stable.
- Reuse the same `factor_returns` schema with `frequency = 'D'`.

### Phase 4 (Optional): Extensions
- Industry/portfolio datasets (e.g., 25 portfolios), reversal factors, and international factors.
- Persist derived series (rolling beta, factor-implied returns) back to DB for reuse.

## Data Source
- Ken French Data Library: `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html`

Notes:
- The library typically provides factor data as **zipped CSV** files (with human-readable headers/footers).
- Values are commonly expressed as **percent returns** (e.g., `0.45` meaning `0.45%` for that period).

## Data Modeling (Database)
### Recommendation: Add a dedicated long-format factors table
Avoid overloading `macro_data` with factor-series semantics (multiple factor sets, frequencies, and a risk-free rate that behaves differently from “macro levels”).

**Proposed table:** `factor_returns`
- `source` (TEXT, not null) — e.g. `ken_french`
- `factor_set` (TEXT, not null) — e.g. `ff3`, `ff5`, `mom`
- `frequency` (CHAR(1), not null) — `D` or `M`
- `factor` (TEXT, not null) — preserve canonical labels like `Mkt-RF`, `SMB`, `HML`, `RF`, `UMD`, `RMW`, `CMA`
- `date` (DATE, not null) — normalized as described below
- `value` (NUMERIC, not null) — stored as a **decimal return** (e.g., `0.0123` means `1.23%`)
- `unit` (TEXT, not null, default `decimal`) — explicit unit marker to prevent confusion downstream

**Primary key**
- (`source`, `factor_set`, `frequency`, `factor`, `date`)

**Indexes**
- (`factor_set`, `frequency`, `factor`, `date`) for common range queries
- (`date`) for date-driven joins

**Schema changes**
- `db_utils/db_setup.sql`: create `factor_returns` (and indexes)
- `db_utils/schemas.py`: register schema + PK so the repository upsert works
- `doc/database.md`: document table purpose, units, and naming

### Explicit non-goal: Store in `macro_data`
Do not store factor data in `macro_data`.

## Date & Unit Conventions
### Frequencies (Monthly-only for now)
- **Monthly (`M`)**: parse `YYYYMM` and store as **month-end** `DATE` (e.g., `2024-01-31`)

### Units
- Convert source **percent** values to **decimal** on ingest:
  - `decimal_return = pct_value / 100.0`
- In the dashboard, display percentages by multiplying by `100` where appropriate.

### Missing values / sentinels
- Handle common sentinels (`-99.99`, `-999`) as nulls.
- Drop all-null rows after parsing.

## Ingestion / ETL Design
### New fetcher: `data_fetchers/ken_french.py` (Monthly)
Use the `factors` subcommand to ingest factor returns.
Implement a fetch-transform-save pipeline consistent with existing fetchers:
- `fetch()`
  - Download the relevant zipped CSV payload(s) from the data library.
  - Support local caching (e.g., write zip to `derived/` with an `ETag`/timestamp) to avoid unnecessary downloads.
- `transform(raw)`
  - Read the zipped CSV content via `zipfile`.
  - Parse into a normalized long-format DataFrame with columns:
    - `source`, `factor_set`, `frequency`, `factor`, `date`, `value`, `unit`
  - Normalize date + numeric types; drop bad lines; coerce errors to null.
  - Convert percent values to **decimal** before persistence.
- `save(df)`
  - Upsert to `factor_returns` via `DataRepository.save_dataframe`.

### Dataset registry (keeps parsing maintainable)
Create an internal registry dict describing (monthly datasets only for MVP):
- `factor_set` (ff3/ff5/mom)
- `frequency` (M)
- `url`
- `expected_columns` (e.g., `["Mkt-RF", "SMB", "HML", "RF"]`)
- parsing hints (header row detection, footer cutoff markers)

This lets you add new Ken French datasets later without rewriting the core parser.

### Incremental updates
Even if the source provides full-history files, ingestion can still be incremental:
1. Query max(`date`) for each (`factor_set`, `frequency`, `factor`) currently in DB.
2. Fetch the latest file, parse full history, then filter rows with `date > max_date`.
3. Upsert filtered rows (safe even if overlap exists).

### Operational entrypoint
Add one of:
- `python -m data_fetchers.ken_french` (fetches factors + portfolios by default)
or
- a small runner in `scripts/` that calls the fetcher(s) with sensible defaults.

## Dashboard Integration
### Phase 1: Make monthly factors visible everywhere
1. **Series Explorer**
   - Add a new dataset option “Fama-French Factors” backed by `factor_returns`.
   - Treat `factor` (or `factor_set::factor`) as the selectable series identifier.
   - Add a display toggle for “Show as %” (multiply by 100) vs “Show as decimal”.
2. **Compare & Correlate**
   - Allow factors to be selected alongside assets/indices/macro series.
   - Consider an auto-resample rule similar to current behavior for long date ranges.
   - For correlations, compute on **returns in decimal** (factors already are returns).

### New page: `Factors`
Add `dashboard/views/factors.py` and include in `dashboard/app.py` navigation.

Suggested layout:
1. **Factor Explorer**
   - Controls: `factor_set`, `frequency`, factor multi-select, date range
   - Charts: time series, histogram, rolling mean/volatility
   - Table: summary stats (mean, stdev, min/max, % positive)
2. **Correlation**
   - Correlation heatmap on factor returns (already aligned by date)
3. **Data Coverage**
   - Row counts and min/max dates per factor set and frequency (freshness checks)

### Explicitly out of scope (for now): Regressions and “RF application”
- No factor-model regressions are planned at this moment.
- `RF` is ingested as just another factor series (for completeness and future work), but the dashboard MVP does not need to compute excess returns.

## Verification Plan
### Unit-level (no network)
- Add a small fixture file under `tests/fixtures/` containing a representative snippet of a Ken French CSV (including headers/footers).
- Test the parser:
  - correctly identifies the data block
  - parses monthly dates correctly (including month-end normalization)
  - converts numeric strings and handles sentinel missing values
  - outputs expected columns and row counts

### Integration-level (with DB)
1. Run `python db_utils/db_setup.py` to create `factor_returns`.
2. Run the fetcher for monthly `ff3`, `mom`, and `ff5`.
3. Query:
   - distinct `factor_set`, `frequency`, `factor`
   - min/max `date`
   - sanity check: `RF` is non-negative most of the time; factor series have reasonable magnitudes

### Dashboard smoke test
- Run `uv run streamlit run dashboard/app.py`.
- Confirm:
  - Factors appear in “Series Explorer” and “Compare & Correlate”.
  - Factors page renders charts for monthly `ff3`, `mom`, and `ff5`.

## Risks / Edge Cases
- **Format drift:** Ken French CSV headers/footers may change; implement robust parsing (find numeric header row + stop at blank line/“Annual Factors” markers).
- **Unit confusion:** percent vs decimal; enforce explicit `unit=decimal` and convert only in one place (ingest). Display conversions happen in the dashboard UI.
- **Date alignment:** monthly factor dates must match how monthly dependent returns are computed (month-end is recommended).
- **Missing rows:** holidays and non-trading days; use inner joins and clear UI messaging when overlap is small.

## Out of Scope (For This Plan)
- Automated scheduling/orchestration (cron/systemd) beyond a simple runnable script.
- Persisting factor regression results back into the DB (can be added later if useful).
- International factor sets and portfolio/industry returns (Phase 3).
