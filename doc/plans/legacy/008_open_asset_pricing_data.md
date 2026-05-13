# Implementation Plan: Open Asset Pricing Data (Chen & Zimmermann) — Factors + Characteristics

## Goal
Ingest the key datasets described in the “Open Source Cross-Sectional Asset Pricing / Open Asset Pricing Data” ecosystem into our Postgres database so they can be queried like our existing `factor_returns` and `portfolio_returns`.

Specifically, we want to capture (at minimum):
- **Anomaly / predictor long-short factor returns** (monthly, and optionally daily).
- **Green–Hand–Zhang (2017)-style characteristics** coverage, including the **GHZ “72 used in RAAD010” subset** (as available).
- **Pre-computed characteristic scores at the portfolio level** (or a reproducible alternative if they are not directly published).

This plan is structured so the first sections focus on **dataset format + database placement**, and later sections cover **download + ingestion implementation**.

---

## Implementation Status
- [x] Phase 1 — Add DB schema objects (`characteristic_metadata`, `portfolio_characteristics`)
- [x] Phase 2 — Implement OAPD fetcher (`data_fetchers/open_asset_pricing.py`)
- [x] Phase 3 — Update documentation (`doc/database.md`, datasource catalog links)
- [x] Phase 4 — Add parser tests and run targeted test suite

---

## 1) Dataset Inventory & Format Analysis (what we will ingest)

### 1.1 OpenAssetPricing.com “Data” downloads (primary surface)
The Open Asset Pricing Data site publishes data releases that generally include:

1. **Monthly predictor/anomaly long-short returns (wide CSV)**
   - Typical filename: `PredictorLSretWide.csv`
   - Shape: `date` + ~200–220 predictor columns (release-dependent).
   - Semantics: each column is a long-short return series for a predictor/anomaly portfolio.
   - Frequency: monthly (store as month-end `DATE`).

2. **Daily predictor/anomaly long-short returns (folder of files)**
   - Typically presented as a folder with one file per predictor (release-dependent).
   - Frequency: daily (store as `DATE`).

3. **Signal / characteristic documentation (CSV)**
   - Typical filename: `SignalDoc.csv`
   - Shape: one row per signal/characteristic with identifiers, definitions, and paper metadata.
   - This is **metadata**, not time series.

4. **Stock-level signed signals (zip; very large)**
   - Typical filename: `signed_predictors_dl_wide.zip` (order-of-GB).
   - Shape (common pattern): `(permno, date)` panel with one column per signal.
   - Note: This dataset is much larger than our current tables and needs an explicit storage decision.

5. **Release notes / data dictionaries**
   - Often include PDFs/XLSX describing coverage, construction rules, and known omissions.

### 1.2 Mismatch to the provided requirements (452 vs ~200 predictors)
The request text cites:
- “**452 Hou–Xue–Zhang (2017) anomaly factor returns (1963–2020+)**”

But the OpenAssetPricing releases commonly reference ~200–220 predictor portfolios “following original papers” (release-dependent).

**Decision:** for this integration, we will ingest the **existing ~200–220 OpenAssetPricing predictor portfolios** (monthly long-short returns + SignalDoc metadata). We will not pursue a separate “452 HXZ anomalies” ingestion in this plan.

### 1.3 Portfolio-level characteristic scores
The request includes:
- “**Pre-computed characteristic scores at portfolio level**”

We should confirm whether these are:
- directly published as a dataset (preferred), or
- something we must compute from stock-level signals + portfolio membership/weights.

**Plan implication:** design a table that can store these portfolio-level scores if published; if not, define a fallback computation path (see Sections 2 and 3).

---

## 2) Database Placement & Schema Recommendations

### 2.1 Reuse existing tables where possible
We already have:
- `factor_returns` — good fit for **long-short anomaly/predictor return series**
- `portfolio_returns` — good fit for **long-only buckets/legs** if we ingest 2×3 or decile portfolios later

**Recommendation:** store OAPD long-short returns in `factor_returns`:
- `source = 'open_asset_pricing'`
- `factor_set = <release_key>::<construction_key>` (examples below)
- `frequency = 'M'` for monthly, `'D'` for daily
- `factor = <predictor_code>` (keep exact codes; do not rename)
- `value` stored as **decimal** returns (consistent with the rest of this DB)

Example `factor_set` conventions:
- `oapd::predictor_ls` (monthly long-short predictor portfolio returns)
- `oapd::predictor_ls_daily` (daily long-short predictor portfolio returns; optional follow-up)

### 2.2 Add new tables for characteristic metadata + portfolio-level scores
Our existing schema does not have a clean place for:
- signal/characteristic **metadata**
- portfolio-level **characteristic scores**

#### 2.2.1 New table: `characteristic_metadata` (recommended)
Purpose: store `SignalDoc.csv`-style metadata so codes used in returns/scores can be decoded in SQL and the dashboard later.

Proposed columns:
- `source` (TEXT) — `open_asset_pricing`
- `characteristic_set` (TEXT) — e.g. `oapd_signals`
- `characteristic` (TEXT) — short code / mnemonic (primary identifier)
- `name` (TEXT) — human-readable name (if available)
- `category` (TEXT) — optional grouping (if available)
- `paper_ref` (TEXT) — citation string / bib key (if available)
- `notes` (TEXT) — free-form notes (optional)

Primary key:
- (`source`, `characteristic_set`, `characteristic`)

#### 2.2.2 New table: `portfolio_characteristics` (recommended)
Purpose: store **portfolio-level characteristic scores** so we can join them to `portfolio_returns` (and/or compare to `factor_returns` constructions).

Proposed columns (mirrors `portfolio_returns` keys):
- `source` (TEXT)
- `portfolio_set` (TEXT) — identifies the portfolio family (e.g., `oapd::signal_sorts_10`, `oapd::ff_2x3`)
- `universe` (TEXT) — use `'NA'` unless the source provides a region/universe
- `frequency` (CHAR(1)) — `M`/`D`
- `portfolio` (TEXT) — portfolio label within the set (e.g. `Lo`, `Hi`, `S/L`, `B/H`, `Decile_1`, …)
- `date` (DATE)
- `characteristic` (TEXT) — the score’s characteristic/signal code
- `value` (NUMERIC) — the portfolio-level characteristic score
- `unit` (TEXT, default `'raw'`) — e.g. `raw`, `zscore`, `rank`, `signed_signal`

Primary key:
- (`source`, `portfolio_set`, `universe`, `frequency`, `portfolio`, `date`, `characteristic`)

Indexes:
- (`portfolio_set`, `frequency`, `characteristic`, `date`)
- (`date`)

### 2.3 Postgres schemas (“public” vs a dedicated namespace)
The codebase currently uses the default `public` schema and assumes unqualified table names.

**Recommendation:** do **not** introduce a new Postgres schema namespace right now (e.g. `asset_pricing.*`), because it cascades into:
- search_path assumptions,
- fully-qualified table naming everywhere,
- `db_utils/schemas.py` and query helper updates.

Instead, keep tables in `public` and use `source`/`*_set` fields to logically separate datasets.

---

## 3) Download, Parsing, Validation, and Ingestion Plan

### 3.1 Add a dedicated fetcher module
Create a new fetcher along the existing pattern:
- `data_fetchers/open_asset_pricing.py`

CLI shape (suggested):
- `python -m data_fetchers.open_asset_pricing factors` (monthly long-short; MVP)
- `python -m data_fetchers.open_asset_pricing factors --daily` (daily; optional follow-up)
- `python -m data_fetchers.open_asset_pricing metadata` (SignalDoc → `characteristic_metadata`)
- `python -m data_fetchers.open_asset_pricing portfolio-scores` (if published; else compute fallback)

Caching:
- Default cache dir: `derived/open_asset_pricing/`
- Cache raw downloads (CSV/ZIP) by release key so reruns are idempotent.

### 3.2 Implement a small dataset registry (keeps maintenance sane)
Add a registry dict in the fetcher defining:
- dataset key (`oapd_monthly_ls`, `oapd_daily_ls`, `oapd_signal_doc`, …)
- release identifier (e.g., `2024-12`), if exposed
- download URL(s)
- expected columns/patterns (date column name, predictor count sanity checks)
- parsing hints (date format, percent vs decimal)

### 3.3 Parsing rules (normalize to our DB conventions)
For each dataset:

#### 3.3.1 Long-short returns wide CSV → `factor_returns`
Steps:
1. Read CSV into a DataFrame.
2. Parse `date` to `datetime64[ns]`.
   - Monthly: normalize to month-end using `MonthEnd(0)` (matches Ken French/AQR ingestion).
3. Convert wide → long:
   - Melt into (`date`, `factor`, `value`) and attach:
     - `source='open_asset_pricing'`
     - `factor_set='oapd::predictor_ls'` (or include release key)
     - `frequency='M'`
     - `unit='decimal'`
4. Unit conversion:
   - Detect whether values are percent or decimal and convert to decimal.
   - Store decimals in DB (consistent with `factor_returns`).
5. Persist with repository upsert into `factor_returns`.

#### 3.3.2 Signal documentation CSV → `characteristic_metadata`
Steps:
1. Load `SignalDoc.csv`.
2. Standardize columns into the metadata table fields.
3. Persist into `characteristic_metadata`.

#### 3.3.3 Portfolio-level characteristic scores → `portfolio_characteristics`
Preferred path (if published):
1. Download the published portfolio-level score file(s).
2. Normalize to long format using the proposed keys.
3. Persist into `portfolio_characteristics`.

Fallback path (if not published):
1. Do **not** ingest the full stock-level signed signal matrix into Postgres by default (keep raw files in `derived/open_asset_pricing/`).
2. Compute portfolio-level scores only for a curated subset (e.g., GHZ72) using published construction rules/weights (if available).
3. Persist only the computed portfolio-level outputs into `portfolio_characteristics` (keep DB manageable).

### 3.4 Validation checks (lightweight, deterministic)
Before writing to DB, run sanity checks:
- Column count / predictor count matches release expectations (within a small tolerance).
- No duplicated `(factor, date)` pairs after melting.
- Date range is plausible (e.g., starts near 1963 for the long-history series).
- Value magnitudes consistent with returns (e.g., mostly in [-1, 1] for decimals; if values are ~1–5, they are likely percent).

After ingestion:
- Row count checks:
  - monthly: `n_months * n_factors`
  - daily: `n_days * n_factors` (optional)
- Spot-check a few factors for non-null coverage across decades.

### 3.5 Database changes required (implementation files)
To support the new tables:
- `db_utils/db_setup.sql`: add `characteristic_metadata`, `portfolio_characteristics` + indexes
- `db_utils/schemas.py`: register the new tables so `DataRepository.save_dataframe()` can upsert
- `doc/database.md`: document the new tables and unit conventions

---

## 4) Decisions (locked)

1. **Anomaly universe**
   - Decision: ingest the **existing ~200–220 OpenAssetPricing predictor portfolios** (not a separate “452 HXZ anomalies” dataset).

2. **Frequency scope**
   - Decision: implement **monthly ingestion first**. Daily ingestion is a follow-up once monthly is stable.

3. **Stock-level signed signals storage**
   - Decision: do **not** ingest the full stock-level signal matrix into Postgres by default; keep raw files in `derived/open_asset_pricing/` and ingest only portfolio-/factor-level outputs.

4. **Portfolio-level characteristic scores**
   - Decision: ingest **published portfolio-level scores if available**; otherwise compute them only for a curated subset (e.g., GHZ72) and store results in `portfolio_characteristics`.

5. **GHZ72 identification**
   - Decision: store an authoritative GHZ72 code list / mapping file in-repo.
   - Current artifact: `doc/plans/legacy/references_raad010_ghz72.csv` (starter scaffold; fill with authoritative RAAD010 mapping before production use).

6. **Return units**
   - Decision: auto-detect and normalize all return series to **decimal** before writing to `factor_returns`.

7. **Dataset/version registry**
   - Decision: do **not** add a dataset/version registry table in this integration.

---

## 5) Acceptance Criteria
- `factor_returns` contains OpenAssetPricing long-short return series (monthly) with:
  - stable `source='open_asset_pricing'`
  - a clear `factor_set` convention
  - correct date normalization and decimal units
- `characteristic_metadata` is populated from `SignalDoc.csv`.
- `portfolio_characteristics` exists and is populated with portfolio-level characteristic scores **or** we have a documented fallback plan + stubs ready for computation.
- All ingestions are idempotent (safe to rerun) and cached under `derived/open_asset_pricing/`.

---

## 6) Datasource Documentation (cross-cutting)
Add a dedicated datasource catalog that follows the DB table structure and explains:
- which external sources populate each table,
- how to distinguish sources in-query (e.g., `source`, `*_set`, `id`, `symbol`),
- and where to find the upstream documentation.

Deliverables:
- `doc/data_sources.md` (table-by-table catalog, including existing + planned OpenAssetPricing ingestion)
- Update `README.md` “Documentation” links to include the new datasource catalog.
