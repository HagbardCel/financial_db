# Implementation Plan: AQR Long-Only Portfolios + Factor ETF Validation

## Goal
1. Ingest AQR “long-only” sorted portfolios (10 portfolios / deciles where available) into PostgreSQL.
2. Ingest historic price data for a curated set of factor ETFs into PostgreSQL.
3. Add an `analyses/` folder with a script that quantifies how well tradable ETFs track the academic long-only portfolios (AQR + Ken French), and cross-validates AQR vs Ken French.

## Why This Matters
- We want to test investment strategies intended to be implemented with **long-only ETFs**, while using **long-history academic datasets** (AQR and Ken French) as proxies.
- This work makes the proxy mapping explicit and testable: *do the ETF returns actually behave like the portfolio returns we want to model?*

## Scope (Phased)
- **Phase 0**: Confirm datasets + ETF universe
- **Phase 1**: Add database table(s)
- **Phase 2**: Implement AQR portfolio fetcher
- **Phase 3**: Implement factor ETF price fetcher (OpenBB-backed)
- **Phase 4**: Ingest Ken French *decile portfolios* (to support the analysis)
- **Phase 5**: Add `analyses/` + correlation / cross-validation script
- **Phase 6**: Tests + verification + docs

## Implementation Status (as of now)
- [x] **Phase 1**: `portfolio_returns` table + schema + docs (`db_utils/db_setup.sql`, `db_utils/schemas.py`, `doc/database.md`).
- [x] **Phase 2**: AQR fetcher implemented (`data_fetchers/aqr.py`) with cache + header detection + decimal conversion.
- [x] **Phase 3**: Factor ETF fetcher implemented (`data_fetchers/factor_etfs.py`) with adjusted-close support in `data_fetchers/openbb_client.py` + `data_fetchers/stock_prices.py`.
- [x] **Phase 3 (default)**: ETF universe default set to `msci_world` in `data_fetchers/factor_etfs.py`.
- [x] **Phase 4**: Ken French portfolio ingestion implemented in `data_fetchers/ken_french.py` (`portfolios` subcommand).
- [x] **Phase 6 (partial)**: Unit tests added for AQR + Ken French parsing and adjusted-close handling.
- [ ] **Phase 0**: Finalize ETF universe + mapping (a default mapping exists, but needs confirmation).
- [x] **Phase 5**: `analyses/` folder + correlation/cross-validation script implemented (`analyses/factor_etf_proxy_validation.py`).
- [ ] **Phase 6 (remaining)**: DB smoke checks + analysis script verification.

---

## Phase 0 — Dataset & Universe Decisions (One-Time)

### AQR: which “10 long-only portfolios”?
AQR publishes multiple Excel “Data Sets” with different layouts (and sometimes tertiles rather than deciles). Before coding, lock down:
- The exact **AQR dataset(s)** to ingest (URLs + sheet names).
- Whether “10 long-only portfolios” means:
  - **One** AQR dataset that contains **10 portfolios (deciles)** (e.g., “10 Quality-Sorted Portfolios”), or
  - **A set** of AQR long-only portfolios across multiple factors (Quality/Value/Momentum/etc.).
- The **universe** to use as default (recommendation: `USA` if available, because most ETF proxies are US listings).

Deliverable:
- A small dataset registry in code (similar to `data_fetchers/ken_french.py`) with `key → {url, sheets, parsing hints}`.
  - **Implemented** for AQR in `data_fetchers/aqr.py` (`qmj_10_deciles` currently uses the “10 Portfolios Formed on Quality” sheet).

### Factor ETFs: choose the proxy tickers
Pick the ETF universe and a factor→ticker mapping (keep it explicit and versionable in code):
- Recommendation: start with **US-listed, liquid factor ETFs** (Momentum/Value/Quality), then expand.
- Keep a single canonical mapping dict like:
  - `momentum → MTUM`, `value → VLUE`, `quality → QUAL` (example only; finalize during Phase 0).

Deliverable:
- A committed list of tickers and factor labels used throughout ingestion + analysis.
  - **Implemented (default)** in `data_fetchers/factor_etfs.py` with sets `msci_world` and `us` (needs final decision).

---

## Phase 1 — Data Modeling (Database)

### New table: `portfolio_returns` (long-format, reusable)
Create a single normalized table for “portfolio return series” so we can store both AQR and Ken French long-only portfolios in the same shape (mirrors the approach used for `factor_returns`).

**Proposed columns**
- `source` (TEXT, not null) — `aqr`, `ken_french`
- `portfolio_set` (TEXT, not null) — dataset identifier (e.g., `qmj_10_deciles`, `10_portfolios_formed_on_be-me`)
- `universe` (TEXT, not null, default `'NA'`) — AQR sheet name (e.g., `USA`); use `'NA'` for sources without a universe concept
- `frequency` (CHAR(1), not null) — `M` initially
- `portfolio` (TEXT, not null) — e.g., `Lo 10`, `2`, …, `Hi 10` (preserve canonical labels as much as possible)
- `date` (DATE, not null) — month-end for monthly data
- `value` (NUMERIC, not null) — **decimal return** (e.g., `0.0123` = `1.23%`)
- `unit` (TEXT, not null, default `'decimal'`)

**Primary key**
- (`source`, `portfolio_set`, `universe`, `frequency`, `portfolio`, `date`)

**Indexes**
- (`portfolio_set`, `universe`, `frequency`, `portfolio`, `date`)
- (`date`)

**Files to update**
- `db_utils/db_setup.sql`: create table + indexes
- `db_utils/schemas.py`: register schema + PK for upserts
- `doc/database.md`: document purpose, units, and keys

Notes:
- Keep ETFs in the existing `stock_prices` table (ETFs are equities).
- Do not overload `factor_returns` with portfolio-return semantics.

---

## Phase 2 — AQR Fetcher (Portfolios + Factors)

### New fetcher: `data_fetchers/aqr.py`
Implement a fetch-transform-save pipeline aligned with existing patterns (`BaseFetcher`, `DataRepository`):

**Fetch**
- Download the Excel file(s) via `requests`.
- Cache raw downloads in `derived/aqr/` (consistent with the Ken French cache pattern).
- Support `--refresh` to redownload.

**Transform**
- Read the target sheet(s) via `pandas.read_excel`.
- Robustly find the header row (search for `DATE` / `YYYYMM` in first column; similar to `sample_code.py`’s approach).
- Parse dates as `YYYYMM` and normalize to **month-end** (`+ MonthEnd(0)`).
- Identify the 10 portfolio columns (deciles) and coerce numeric.
- Normalize units:
  - AQR datasets are often in **percent returns**; convert to **decimal** exactly once on ingest (`pct / 100.0`).
  - Drop/NA sentinel values if present.
- Melt to long format for `portfolio_returns`.

**Save**
- Upsert long-only / index-style datasets into `portfolio_returns`.
- Upsert long/short factor datasets into `factor_returns`.

**Initial datasets (implemented)**
- Portfolios / index series:
  - `qmj_10_deciles`
  - `qmj_6_size_quality`
  - `vme_portfolios`
  - `momentum_indices`
- Factors:
  - `qmj_factors`
  - `vme_factors`

**CLI entrypoint**
- `python -m data_fetchers.aqr --refresh` (defaults to all available AQR datasets; portfolios + factors)
  - Current dataset uses a non‑regional sheet (“10 Portfolios Formed on Quality”), so `--universe USA` is not applicable.

---

## Phase 3 — Factor ETF Price Fetcher

### Preferred approach: reuse `data_fetchers/stock_prices.py`
The repo already supports OpenBB-backed equity OHLCV ingestion into `stock_prices`. Leverage it rather than creating a parallel ingestion stack.

Deliverable options:
1. **Thin runner script** (recommended): `scripts/fetch_factor_etfs.py`
   - Imports the factor ETF ticker list and calls `OpenBBEquityPriceFetcher` for each ticker.
   - Accepts `--start`, `--end`, and `--provider`.
2. **Dedicated module**: `data_fetchers/factor_etfs.py`
   - Wraps the same logic but keeps everything under `data_fetchers/`.
   - **Implemented**: `python -m data_fetchers.factor_etfs --set msci_world` (default) or `--set us`.

Notes on “close” vs total return:
- For factor comparisons, **use adjusted close** (dividends included) when computing ETF returns.
- If the OpenBB response includes `adj_close` (or equivalent), the analysis should use it explicitly.
- Keep this choice explicit in code + docs to avoid silent unit mistakes.

---

## Phase 4 — Ken French Decile Portfolios (for Analysis)

Item (4.2) requires **top decile portfolios** from Ken French, which are distinct from the already-ingested `factor_returns`.

### New fetcher: `data_fetchers/ken_french.py`
Implement Ken French “10 Portfolios Formed on …” ingestion into `portfolio_returns` via the `portfolios` subcommand.

**Initial datasets (minimum)**
- `10_Portfolios_Formed_on_BE-ME` (Value deciles)
- `10_Portfolios_Formed_on_OP` (Quality/profitability deciles)
- `10_Portfolios_Formed_on_Momentum` (Momentum deciles)

**Pipeline**
- Download `*_CSV.zip` from the Ken French FTP endpoint.
- Parse the “monthly” block only (skip annual section), similar to the logic in `sample_code.py`.
- Convert percent to decimal on ingest.
- Normalize date to month-end.
- Melt to long format (`portfolio` labels should preserve `Lo 10`/`Hi 10` if present).
- Save to `portfolio_returns` with `source='ken_french'`.
  - **Implemented** in `data_fetchers/ken_french.py` (`python -m data_fetchers.ken_french` runs factors + portfolios; `python -m data_fetchers.ken_french portfolios --sets ...` is still available).
  - Note: multiple URL fallbacks are configured for the Ken French portfolio zip filenames.

---

## Phase 5 — `analyses/` Folder + Validation Script

### Folder
Create `analyses/` as a first-class place for research scripts that:
- pull data from the DB (not the network),
- compute statistics, and
- write outputs to `derived/` (so runs are reproducible and artifacts are disposable).

### Script: correlations + cross-validation
Add `analyses/factor_etf_proxy_validation.py` with a CLI similar in spirit to the fetchers (simple `argparse`, DB config via `db_utils.config.get_database_config()`).

**Inputs**
- AQR portfolio returns from `portfolio_returns`
- Ken French portfolio returns from `portfolio_returns`
- ETF prices from `stock_prices`

**Core transforms**
- Convert ETF prices to **monthly returns** (month-end close/adj-close → `pct_change()`), stored as **decimal**.
- For AQR/Ken French:
  - select top portfolio (`Hi 10` / Decile 10) and optionally include all 10 deciles for richer diagnostics.
- Align by month-end date and drop non-overlapping rows.

**Required outputs**
1. **ETF ↔ AQR correlations** (top portfolio and optionally per-decile curve)
2. **ETF ↔ Ken French top decile correlations**
3. **AQR ↔ Ken French cross-validation** (same-factor portfolio comparisons)

**Recommended extras (optional)**
- Simple regressions: `ETF_returns ~ portfolio_returns` (alpha/R²) for each factor.
- Output artifacts in `analyses/analyses_outputs/`:
  - correlation CSVs
  - overlap window summary (min/max dates, n months)
  - a small `README.md` or report snippet summarizing key findings

---

## Phase 6 — Verification, Tests, and Documentation

### Unit tests (no network)
Follow the existing testing style (`tests/test_fama_french_parser.py`):
- Add small fixtures under `tests/fixtures/`:
  - a minimal Ken French “10 portfolios” CSV snippet (header + a few rows + annual marker)
  - a minimal AQR-like Excel fixture *if licensing permits*; otherwise generate a tiny in-memory Excel file in the test and ensure the parser path is testable.
- Test:
  - header detection
  - month-end date normalization
  - percent→decimal conversion
  - output schema columns
  - **Implemented**: `tests/test_aqr_portfolios.py`, `tests/test_fama_french_parser.py`, `tests/test_fama_french_portfolios.py`.

### Integration smoke checks (DB required)
- Run DB setup to ensure `portfolio_returns` exists.
- Run AQR + Ken French portfolio fetchers and confirm row counts and date ranges.
- Run ETF price fetcher for chosen tickers.
- Run the analysis script and confirm outputs are created.

### Docs
- Update `doc/database.md` for `portfolio_returns`.
- Add a short “How to run” section in the plan’s follow-up PR description (or `README.md` if it becomes a standard workflow).

---

## Acceptance Criteria
- `portfolio_returns` is created and populated for:
  - AQR long-only (10 portfolios) dataset(s)
  - Ken French 10-portfolio datasets needed for validation
- `stock_prices` contains the chosen factor ETF tickers with sufficient history.
- `analyses/factor_etf_proxy_validation.py` runs end-to-end using DB-only inputs and produces:
  - ETF↔AQR correlations
  - ETF↔Ken French correlations
  - AQR↔Ken French cross-validation outputs
- All ingestions are idempotent (safe to rerun).

## Risks / Edge Cases
- AQR Excel layouts and sheet names can change; parsing must be defensive.
- ETF inception dates can sharply limit overlap; analysis must report overlap windows clearly.
- Factor definition mismatches (portfolio construction vs ETF index methodology) can reduce correlations even when “factor names” match.
- Dividend handling (raw close vs adjusted close) can materially affect results; make the choice explicit.

## Next Steps
1. **Run DB smoke checks** (with a resolvable `POSTGRES_HOST`):
   - `python db_utils/db_setup.py`
   - `python -m data_fetchers.aqr --refresh`
   - `python -m data_fetchers.ken_french portfolios --sets 10_Portfolios_Formed_on_BE-ME 10_Portfolios_Formed_on_Momentum --refresh`
   - `python -m data_fetchers.factor_etfs --set msci_world`
2. **Run analysis script**:
   - `python -m analyses.factor_etf_proxy_validation`
3. **Validate outputs** in `analyses/analyses_outputs/` and iterate on mappings as needed.
