# Data Sources Catalog (by Database Table)

This document describes **which external data sources populate each table**, how to distinguish sources in SQL, and where to find upstream documentation.

Conventions:
- Unless noted otherwise, all data lives in the default Postgres `public` schema.
- “Ingest command” examples assume you are in the repo root and the DB is configured via env vars (see `doc/development.md`).

---

## `factor_returns`
Long-format factor **return** series (stored as decimals).

### Sources currently ingested
1. **Ken French Data Library** (`source = 'ken_french'`)
   - Ingested by: `python -m data_fetchers.ken_french factors`
   - Distinguish in-table:
     - `factor_set`: `ff3`, `ff5`, `mom`
     - `frequency`: currently `M`
     - `factor`: canonical labels like `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA`, `UMD`, `RF`
   - Upstream docs:
     - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

2. **AQR Data Sets** (`source = 'aqr'`)
   - Ingested by: `python -m data_fetchers.aqr factors`
   - Distinguish in-table:
     - `factor_set`: `qmj_factors`, `vme_factors`, …
     - `frequency`: currently `M`
     - `factor`: stored as `<sheet_name>::<column_name>` to preserve sheet/universe context
   - Upstream docs:
     - AQR “Data Sets” landing: https://www.aqr.com/Insights/Datasets
     - Direct file URLs are encoded in `data_fetchers/aqr.py` (see `FACTOR_DATASETS`).

### Additional source (implemented; ingestion optional)
3. **Open Asset Pricing Data (Chen & Zimmermann)** (`source = 'open_asset_pricing'`)
   - Ingested by: `python -m data_fetchers.open_asset_pricing factors`
   - Scope: monthly long-short predictor portfolio returns (~200–220 series)
   - Distinguish in-table:
     - `factor_set`: `oapd::predictor_ls` (and optionally `oapd::predictor_ls_daily`)
     - `frequency`: `M` (daily optional follow-up)
     - `factor`: predictor code (as published; no renames)
   - Upstream docs:
     - https://www.openassetpricing.com

### Notes
- `value` is stored as a **decimal return** (e.g., `0.0123` = `1.23%`).
- To see what you have: `SELECT source, factor_set, frequency, COUNT(*) FROM factor_returns GROUP BY 1,2,3 ORDER BY 1,2,3;`

---

## `portfolio_returns`
Long-format portfolio **return** series (stored as decimals), typically long-only buckets/deciles.

### Sources currently ingested
1. **AQR Data Sets** (`source = 'aqr'`)
   - Ingested by: `python -m data_fetchers.aqr portfolios`
   - Distinguish in-table:
     - `portfolio_set`: dataset key (e.g., `qmj_10_deciles`, `momentum_indices`, …)
     - `universe`: either a fixed label (e.g., `NA`) or the Excel sheet name (often a region/universe)
     - `portfolio`: column label from the source file (e.g., deciles/buckets)
     - `frequency`: currently `M`
   - Upstream docs:
     - AQR “Data Sets” landing: https://www.aqr.com/Insights/Datasets
     - Direct file URLs are encoded in `data_fetchers/aqr.py` (see `PORTFOLIO_DATASETS`).

2. **Ken French Data Library** (`source = 'ken_french'`)
   - Ingested by: `python -m data_fetchers.ken_french portfolios`
   - Distinguish in-table:
     - `portfolio_set`: e.g., `10_Portfolios_Formed_on_BE-ME`, `10_Portfolios_Formed_on_OP`, `10_Portfolios_Formed_on_Momentum`
     - `universe`: currently `NA`
     - `portfolio`: portfolio label (e.g., `Lo 10`, …, `Hi 10`)
     - `frequency`: currently `M`
   - Upstream docs:
     - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

### Notes
- `value` is stored as a **decimal return**.
- To see what you have: `SELECT source, portfolio_set, universe, frequency, COUNT(*) FROM portfolio_returns GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;`

---

## `stock_prices`
Daily OHLCV price history for equities/ETFs.

### Sources currently ingested
1. **OpenBB SDK (provider-backed)** (no `source` column in-table)
   - Ingested by:
     - `python -m data_fetchers.stock_prices <TICKERS...>`
     - `python -m data_fetchers.factor_etfs --set <msci_world|us>` (wrapper around `stock_prices`)
   - Distinguish in-table:
     - `symbol`: the ticker used for ingestion
     - The chosen OpenBB provider is determined at ingest time (env vars) and is **not persisted** in the table.
   - Upstream docs:
     - OpenBB documentation: https://docs.openbb.co

### Notes
- `close` is stored as **adjusted close when available by default** (see `data_fetchers/stock_prices.py` and `data_fetchers/openbb_client.py`).

---

## `commodity_prices`
Daily (or monthly, for some series) OHLCV history for commodities.

### Sources currently ingested
1. **OpenBB SDK (provider-backed)** (no `source` column in-table)
   - Ingested by: `python -m data_fetchers.commodities [SYMBOLS...]`
   - Typical symbols: `GC=F`, `SI=F`, `HG=F`
   - Upstream docs:
     - OpenBB documentation: https://docs.openbb.co

2. **datasets/gold-prices (GitHub) monthly CSV** (stored into `commodity_prices`)
   - Ingested by: `python -m data_fetchers.gold_prices`
   - Distinguish in-table:
     - `symbol`: defaults to `GOLD` (configurable via `--symbol` / `GOLD_SYMBOL`)
     - Dates are normalized to **month-end**.
   - Upstream docs:
     - Repo: https://github.com/datasets/gold-prices
     - Raw monthly CSV used by default: https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv

---

## `interest_rates`
Interest rate series (typically FRED-backed) keyed by region/type/maturity/currency.

### Sources currently ingested
1. **OpenBB SDK → FRED series** (no `source` column in-table)
   - Ingested by: `python -m data_fetchers.bonds`
   - Distinguish in-table:
     - `region`, `rate_type`, `maturity`, `currency`
     - The FRED series IDs used for each maturity live in `data_fetchers/bonds.py` (`DEFAULT_SERIES`).
     - The OpenBB provider used is determined at ingest time and is **not persisted** in the table.
   - Upstream docs:
     - FRED: https://fred.stlouisfed.org
     - FRED API: https://fred.stlouisfed.org/docs/api/fred/
     - OpenBB documentation: https://docs.openbb.co

---

## `macro_data`
General macroeconomic series keyed by an `id` and date.

### Sources currently ingested
1. **Robert Shiller online data (Excel)**
   - Ingested by: `python -m data_fetchers.shiller_cape <excel_url>`
   - Distinguish in-table:
     - `id`: identifiers are defined in `data_fetchers/shiller_cols.json` (e.g., `sp_comp_price`, `sp_comp_div`, `sp_comp_earn`, `cpi`, `rate_gs10`)
     - `long_name`: descriptive name stored alongside the values
   - Upstream docs:
     - Shiller data index page: http://www.econ.yale.edu/~shiller/data.htm
     - The exact Excel URL can change; pass the current “ie_data” Excel URL to the fetcher.

---

## `test_data`
Non-standard or derived series used during development/testing.

### Sources currently ingested
1. **Derived fields from Shiller ingest**
   - Ingested by: `python -m data_fetchers.shiller_cape <excel_url>`
   - Distinguish in-table:
     - `id` values with `type: "derived"` in `data_fetchers/shiller_cols.json` (e.g., `sp_cape`, `r_sp_price`, …)

---

## `assets_prices`
Generic “asset price in USD” table.

### Current status
- Table exists, but there is **no ingestion pipeline implemented** in this repository at the moment.

---

## `indices`
Generic “index level” table.

### Current status
- Table exists, but there is **no ingestion pipeline implemented** in this repository at the moment.

---

## `characteristic_metadata`
Metadata describing characteristic/signal definitions and identifiers.

### Source
1. **Open Asset Pricing Data (Chen & Zimmermann)** (`source = 'open_asset_pricing'`)
   - Ingested by: `python -m data_fetchers.open_asset_pricing metadata`
   - Scope: `SignalDoc.csv` (or equivalent) → one row per characteristic/signal
   - Distinguish in-table:
     - `source`, `characteristic_set`, `characteristic`
   - Upstream docs:
     - https://www.openassetpricing.com

---

## `portfolio_characteristics`
Portfolio-level characteristic scores (time series keyed by portfolio and characteristic).

### Source
1. **Open Asset Pricing Data (Chen & Zimmermann)** (`source = 'open_asset_pricing'`)
   - Ingested by: `python -m data_fetchers.open_asset_pricing portfolio_characteristics --portfolio-scores-url <URL>` (alias: `portfolio-scores`)
   - Scope: published portfolio-level scores if available; otherwise computed for a curated subset (e.g., GHZ72)
   - Distinguish in-table:
     - `source`, `portfolio_set`, `universe`, `frequency`, `portfolio`, `characteristic`
   - Upstream docs:
     - https://www.openassetpricing.com
