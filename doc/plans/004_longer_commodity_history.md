# Plan: Longer-History Commodity Prices (Beyond Yahoo Finance)

## TL;DR
- The repo already requests the **maximum** Yahoo Finance history via `yfinance` (`ticker.history(period="max")`) in `data_fetchers/stock_prices.py`.
- If `GC=F` / `SI=F` / `HG=F` still have a “short” history in your DB, that’s a **Yahoo symbol coverage** limitation (not a code/config issue).
- To get materially longer history for free, the most reliable next source is typically:
  - **FRED** for long-run **spot/benchmark** commodity series (close/level only, no OHLCV).
  - Optionally **Stooq** or **Nasdaq Data Link (Quandl/CHRIS)** for longer-run **futures** style series (coverage + licensing vary; often requires an API key for Nasdaq Data Link).
- Implemented: `data_fetchers/fred_commodities.py` ingests FRED spot series into `commodity_prices` as close-only (sets `open=high=low=close`, `volume=0`).
- Important: FRED removed LBMA gold/silver price series (IBA dataset removal). Many remaining “global commodity price” series on FRED are monthly and often start in 1990, so FRED may not satisfy a “back to 1970” requirement for metals.

## Current State (Repo)
- Commodity futures are ingested via Yahoo Finance:
  - Runner: `data_fetchers/commodities.py` (defaults to `GC=F`, `SI=F`, `HG=F`)
  - Fetcher: `data_fetchers/stock_prices.py` uses `ticker.history(period="max")`
  - Target table: `commodity_prices` (schema in `db_utils/db_setup.sql`, registry in `db_utils/schemas.py`)

## What “Longer History” Can Mean (Decide First)
Before changing providers, confirm what you actually need:
1. **Instrument definition**
   - *Futures continuous series* (front-month roll / settlement style), or
   - *Spot/benchmark* price (e.g., LBMA gold fix), or
   - *ETF proxy* (GLD/SLV) if acceptable.
2. **Fields**
   - Do you need **OHLCV**, or is a single daily level (close/spot) enough?
3. **Granularity**
   - Daily/weekly/monthly is easiest for long history.
   - Intraday “years of 1m/5m bars” is generally **not** available for free and not supported by Yahoo at long ranges.

## Yahoo Finance: Practical Limits
- For daily/weekly/monthly, `period="max"` is the longest range Yahoo exposes for that ticker.
- If the returned history starts later than you want, Yahoo simply doesn’t have older bars for that symbol (common for some futures series).
- Yahoo is not an official, guaranteed API; availability can change.

## Free Alternatives (Recommended Shortlist)

### Option A (Recommended): FRED spot/benchmark series → `macro_data`
**Best when** you want multi-decade history and can live with a single daily/weekly/monthly level.
- Access: free; easy via `pandas_datareader` (already used in `data_fetchers/bonds.py`).
- Typical commodity series IDs (examples you can validate on FRED):
  - Gold (LBMA AM fix): `GOLDAMGBD228NLBM`
  - Silver (LBMA fix): `SILVERAMGBD228NLBM`
  - Copper (global price): `PCOPPUSDM`
- Storage options:
  - **A1 (clean)**: write into `macro_data` (IDs can be the raw FRED series IDs, up to `VARCHAR(18)`).
  - **A2 (dashboard-friendly)**: write into `commodity_prices` using short `symbol`s (<= 10 chars) and treat the series as **close-only**.
    - This repo uses A2 in `data_fetchers/fred_commodities.py`.

### Option B: Stooq daily OHLC → `commodity_prices` (coverage-dependent)
**Best when** you need OHLC-style bars and can accept a community/free-data source.
- Access: free CSV download endpoints; typically no auth.
- Caveats:
  - Coverage for specific commodity futures/spot tickers must be confirmed.
  - Ticker naming differs from Yahoo; you’ll need a mapping table/config.

### Option C: Nasdaq Data Link (Quandl/CHRIS continuous futures) → `commodity_prices` (policy-dependent)
**Best when** you want long continuous-futures history with futures-like fields.
- Access: often requires account + API key; some datasets may be free, others paid.
- Caveats:
  - Licensing/availability can change; confirm datasets are usable for your purpose.

## Proposed Implementation Plan (Concrete)

### Phase 0 — Measure the current “max” you’re getting from Yahoo
1. Run the commodity fetcher once (if you haven’t recently):
   - `python -m data_fetchers.commodities`
2. Check earliest dates in Postgres:
   - `SELECT symbol, MIN(date) AS start, MAX(date) AS end, COUNT(*) AS rows FROM commodity_prices GROUP BY symbol ORDER BY symbol;`
3. If the “start” dates are later than you want, proceed to Phase 1.

### Phase 1 — Add long-history spot series via FRED (fastest win)
1. Add a fetcher: `data_fetchers/fred_commodities.py` (implemented)
   - Similar to `data_fetchers/bonds.py` (uses `pandas_datareader.data.DataReader(..., "fred", ...)`).
   - Mapping is now primarily IMF Primary Commodity Prices series on FRED (see `python -m data_fetchers.fred_commodities --list`).
   - Note: LBMA gold/silver series were removed from FRED and may return 404.
2. Transform output to match `commodity_prices` schema (close-only)
   - Set `open=high=low=close` and `volume=0`.
3. Document and run
   - `python -m data_fetchers.fred_commodities --list`
    - `python -m data_fetchers.fred_commodities --start 1970-01-01`

**Acceptance criteria**
- `commodity_prices` contains the selected FRED series with clearly understood coverage (frequency + start date).
- Dashboard “Prices Explorer” / “Series Explorer” can plot them without further code changes.

### Phase 2 (Optional) — Unified “commodity” abstraction (if you want futures + spot cleanly)
If you want to treat “Gold” as one concept with multiple sources:
1. Introduce a small mapping config (YAML/JSON) for commodity instruments:
   - canonical commodity id (`gold`, `silver`, `copper`)
   - provider (`yahoo`, `fred`, `stooq`, `nasdaq_datalink`)
   - provider symbol / series id
   - field semantics (close vs settle vs spot)
2. Add a single runner (e.g., `python -m data_fetchers.commodity_prices --source ...`) that reads this mapping and dispatches to provider-specific fetchers.

### Phase 3 (Optional) — If you need multi-source OHLC in `commodity_prices`
Right now, `commodity_prices` has primary key `(symbol, date)` and `symbol VARCHAR(10)`.
If you plan to ingest the *same* commodity from multiple providers or use longer symbols:
1. Schema decision (choose one):
   - **A.** Add `source` column and change PK to `(source, symbol, date)`, and widen `symbol` (e.g., `VARCHAR(32)`), or
   - **B.** Keep PK as-is but namespace `symbol` values (e.g., `YF:GC=F`, `FRED:GOLDAM...`) and widen `symbol`.
2. Update:
   - `db_utils/db_setup.sql` and `db_utils/schemas.py`
   - Dashboard queries that filter by `symbol` (e.g., `dashboard/views/prices.py`, `dashboard/views/series.py`)

## Provider Selection Guidance
- If your goal is “long-run inflation-adjusted commodity context” → pick **FRED**.
- If your goal is “tradeable futures-like return series with OHLC/volume” → investigate **Nasdaq Data Link (CHRIS)** or **Stooq**, but expect more mapping/licensing work.

## Open Questions (Answer These to Lock the Design)
1. Do you want **futures** (`GC=F`) specifically, or a **spot proxy** is acceptable?
2. Is **OHLCV** required for your analytics, or is **close/level** enough?
3. Should the dashboard treat these as a single “Commodity Prices” dataset, or is “Macro Data (Commodities)” acceptable?
