# Implementation Plan: Historic Commodity Prices (Gold, Silver, Copper)

## Goal
Add a lean, repeatable way to ingest historic commodity prices (gold, silver, copper) using an existing data source and a dedicated table.

## Source (Already Connected)
- **Yahoo Finance** via `yfinance` (already used by `data_fetchers/stock_prices.py`).
- Symbols:
  - `GC=F` (Gold futures)
  - `SI=F` (Silver futures)
  - `HG=F` (Copper futures)

## Current State
- `data_fetchers/stock_prices.py` writes OHLCV data to `stock_prices`.
- No commodity-specific table or runner.

## Proposed Changes
1. **Add a dedicated table**
   - Create `commodity_prices` with the same OHLCV structure as `stock_prices`.
   - Update:
     - `db_utils/db_setup.sql` (table definition)
     - `db_utils/schemas.py` (schema registry)
     - `doc/database.md` (documentation)
2. **Add a tiny commodity runner**
   - Create `data_fetchers/commodities.py` that imports `YahooFinanceFetcher`.
   - Default to the three symbols above, with optional CLI override.
   - Save into `commodity_prices`.
3. **Document usage**
   - Add a short section to `doc/development.md` (or `README.md`) with a one-line run command:
     `python -m data_fetchers.commodities`

## Verification Plan (Lightweight)
1. Run `python db_utils/db_setup.py` to create the new table.
2. Run `python -m data_fetchers.commodities`.
3. Query `commodity_prices` for `GC=F`, `SI=F`, `HG=F` and confirm rows exist.
