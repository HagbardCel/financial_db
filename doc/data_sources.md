# Data Sources Catalog (by Database Table)

This document describes **which external data sources populate each table**, how to distinguish sources in SQL, and where to find upstream documentation.

Conventions:
- Unless noted otherwise, all data lives in the default Postgres `public` schema.
- “Ingest command” examples assume you are in the repo root and the DB is configured via env vars (see `doc/development.md`).
- `python -m data_fetchers.refresh_all` is the canonical repo-level refresh command; it reads `config/data_refresh.toml` and runs only enabled fetchers.

## Provenance Model

Not every table stores source provenance the same way:

- Persisted source columns: `factor_returns`, `portfolio_returns`, `characteristic_metadata`, and `portfolio_characteristics` store a `source` value directly in the table.
- Inferred provenance: `commodity_prices`, `interest_rates`, `macro_data`, and `test_data` do **not** store a dedicated source column. For these tables, provenance is inferred from the ingest command, configured OpenBB provider/path, symbol or id, and `config/data_refresh.toml`.
- OpenBB-backed tables are provider-dependent. The OpenBB endpoint path defaults live in `data_fetchers/openbb_client.py`, while provider overrides are passed by CLI arguments or environment variables such as `OPENBB_EQUITY_PROVIDER`, `OPENBB_COMMODITY_PROVIDER`, `OPENBB_OIL_PROVIDER`, and `OPENBB_RATES_PROVIDER`.

## Summary Matrix

| Table | Contents | External origin | Frequency | Key identifiers | Refresh status |
| --- | --- | --- | --- | --- | --- |
| `factor_returns` | Factor return series | Ken French ZIP files, AQR Excel files, Open Asset Pricing Google Drive files | Monthly today; daily optional for OAPD | `source`, `factor_set`, `factor`, `date` | Included by default |
| `portfolio_returns` | Portfolio return series | AQR Excel files, Ken French ZIP files | Monthly | `source`, `portfolio_set`, `universe`, `portfolio`, `date` | Included by default |
| `securities` | Security master | Xetra tradable instruments, OpenBB ETF metadata | Static/current snapshot | `security_id` | Xetra disabled until source file is provided; factor ETF metadata included by default |
| `listings` | Provider/listing identifiers | Xetra, Stooq mappings, OpenBB ETF metadata | Static/current snapshot | `listing_id`, `provider_symbol` | Xetra disabled until source file is provided; factor ETF metadata included by default |
| `equity_price_bars` | Equity and ETF OHLCV history | Stooq daily files, OpenBB `equity.price.historical` provider data | Daily | `provider`, `provider_symbol`, `date` | Stooq disabled until source files are provided; `factor_etfs` enabled by default |
| `fx_rates` | FX rates against EUR | ECB reference rates | Daily | `currency`, `date` | Disabled by default for stock momentum profile |
| `equity_prices_eur` | EUR-denominated equity panel | Derived from `equity_price_bars` + `fx_rates` | Daily | `security_id`, `listing_id`, `date` | Built by stock momentum analysis command |
| `commodity_prices` | Commodity, gold, and oil benchmark history | OpenBB futures/spot provider data, datasets/gold-prices CSV, EIA oil history pages | Daily for OpenBB futures; monthly for gold/oil spot; annual backfill for long-run U.S. oil | `symbol`, `date` | Included by default for commodities, gold, and oil |
| `interest_rates` | Treasury rate series | OpenBB `economy.fred_series` backed by FRED series IDs | Daily | `region`, `rate_type`, `maturity`, `currency`, `date` | Included by default |
| `macro_data` | Shiller macro series | Robert Shiller online Excel data | Monthly | `id`, `date` | Included by default when `config/data_refresh.toml` contains a current Excel URL |
| `test_data` | Derived Shiller series | Derived from Robert Shiller online Excel data | Monthly | `id`, `date` | Same ingest as `macro_data` |
| `characteristic_metadata` | Characteristic definitions | Open Asset Pricing `SignalDoc.csv` Google Drive file | Static/reference | `source`, `characteristic_set`, `characteristic` | Included by default |
| `portfolio_characteristics` | Portfolio-level characteristic time series | Open Asset Pricing-compatible portfolio scores URL supplied by operator | Depends on provided file | `source`, `portfolio_set`, `universe`, `portfolio`, `characteristic`, `date` | Disabled until a real source URL is configured |
| `indices` | Generic index levels | No pipeline currently implemented | N/A | `id`, `date` | Not populated |
| `eodhd.*` | EODHD exchange, symbol, daily price, dividend, split, and symbol-change snapshots | EOD Historical Data parquet archive | Snapshot/daily | EODHD symbol and date | Refresh disabled by default; ingest-only rebuild supported |

## EODHD Snapshot Archive

The archive is stored outside the repository at `${RAW_DATA_DIR}/eodhd` (archive subdir configured in `config/eodhd.toml`). Default download, ingest, report, and universe settings also live in `config/eodhd.toml`; CLI flags override those defaults. Bare `python -m data_fetchers.eodhd download` and `python -m data_fetchers.eodhd refresh` run the resumable full-archive preset: exchange reference metadata, active and delisted symbol metadata, daily prices, and eligible dividends and splits. Bare `python -m data_fetchers.eodhd ingest` loads broad metadata only and never calls the vendor API; loading every archived parquet dataset requires `python -m data_fetchers.eodhd ingest all --confirm-all-datasets`. Exchange and symbol snapshots retain the original provider row and expose documented fields as typed columns. Symbol-change history is additive metadata and does not merge historical price series.

---

## `factor_returns`
Long-format factor **return** series (stored as decimals).

### Sources currently ingested
1. **Ken French Data Library** (`source = 'ken_french'`)
   - Ingested by: `python -m data_fetchers.ken_french factors`
   - Source files:
     - `ff3`: `F-F_Research_Data_Factors_CSV.zip` (fallback: non-`_CSV` ZIP)
     - `ff5`: `F-F_Research_Data_5_Factors_2x3_CSV.zip` (fallback: non-`_CSV` ZIP)
     - `mom`: `F-F_Momentum_Factor_CSV.zip` (fallback: non-`_CSV` ZIP)
     - The canonical URL list is in `data_fetchers/ken_french_registry.py`.
   - Distinguish in-table:
     - `factor_set`: `ff3`, `ff5`, `mom`
     - `frequency`: currently `M`
     - `factor`: canonical labels like `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA`, `UMD`, `RF`
   - Upstream docs:
     - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

2. **AQR Data Sets** (`source = 'aqr'`)
   - Ingested by: `python -m data_fetchers.aqr factors`
   - Source files:
     - `qmj_factors`: `Quality-Minus-Junk-Factors-Monthly.xlsx`
     - `vme_factors`: `Value-and-Momentum-Everywhere-Factors-Monthly.xlsx`
     - The canonical URL list is in `data_fetchers/aqr_registry.py`.
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
   - Source files:
     - Monthly: `PredictorLSretWide.csv` from the Open Asset Pricing data page / Google Drive file ID in `data_fetchers/open_asset_pricing_registry.py`.
     - Daily optional: `PredictorsLongShort_Daily.zip` from the Open Asset Pricing data page / Google Drive folder or direct file override.
   - Scope: monthly long-short predictor portfolio returns (~200–220 series)
   - Distinguish in-table:
     - `factor_set`: `oapd::predictor_ls` (and optionally `oapd::predictor_ls_daily`)
     - `frequency`: `M` (daily optional follow-up)
     - `factor`: predictor code (as published; no renames)
   - Upstream docs:
     - https://www.openassetpricing.com

### Notes
- `value` is stored as a **decimal return** (e.g., `0.0123` = `1.23%`).
- Included in `python -m data_fetchers.refresh_all` by default via `ken_french`, `aqr`, and `open_asset_pricing`.
- To see what you have: `SELECT source, factor_set, frequency, COUNT(*) FROM factor_returns GROUP BY 1,2,3 ORDER BY 1,2,3;`

---

## `portfolio_returns`
Long-format portfolio **return** series (stored as decimals), typically long-only buckets/deciles.

### Sources currently ingested
1. **AQR Data Sets** (`source = 'aqr'`)
   - Ingested by: `python -m data_fetchers.aqr portfolios`
   - Source files:
     - `qmj_10_deciles`: `Quality-Minus-Junk-10-QualitySorted-Portfolios-Monthly.xlsx`
     - `qmj_6_size_quality`: `Quality-Minus-Junk-Six-Portfolios-Formed-on-Size-and-Quality-Monthly.xlsx`
     - `vme_portfolios`: `Value-and-Momentum-Everywhere-Portfolios-Monthly.xlsx`
     - `momentum_indices`: `Momentum-Indices-Monthly.xlsx`
     - The canonical URL list is in `data_fetchers/aqr_registry.py`.
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
   - Source files:
     - BE/ME, operating profitability, and momentum portfolio ZIP URLs are tried from `data_fetchers/ken_french_registry.py`.
     - Several fallback names are configured because Ken French file names have varied over time.
   - Distinguish in-table:
     - `portfolio_set`: e.g., `10_Portfolios_Formed_on_BE-ME`, `10_Portfolios_Formed_on_OP`, `10_Portfolios_Formed_on_Momentum`
     - `universe`: currently `NA`
     - `portfolio`: portfolio label (e.g., `Lo 10`, …, `Hi 10`)
     - `frequency`: currently `M`
   - Upstream docs:
     - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

### Notes
- `value` is stored as a **decimal return**.
- Included in `python -m data_fetchers.refresh_all` by default via `aqr` and `ken_french`.
- To see what you have: `SELECT source, portfolio_set, universe, frequency, COUNT(*) FROM portfolio_returns GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;`

---

## Equity Security Master And Price Bars
Normalized equity reference, listing, and OHLCV history for stock momentum research.

### Sources currently ingested
1. **OpenBB SDK factor ETFs** (`provider = 'openbb'`)
   - Ingested by:
     - `python -m data_fetchers.factor_etfs --set <msci_world|us>`
     - `python -m data_fetchers.openbb_equity_prices <TICKERS...>` for explicit symbols
   - OpenBB path:
     - Default endpoint path: `equity.price.historical`
     - Override path: `OPENBB_EQUITY_HISTORICAL_PATH`
     - Provider override: `--provider` or `OPENBB_EQUITY_PROVIDER`
   - Distinguish in-table:
     - `provider`, `provider_symbol`
     - `adjustment_status`
   - Upstream docs:
     - OpenBB documentation: https://docs.openbb.co

2. **Xetra tradable instruments** (`provider = 'xetra'`)
   - Ingested by: `python -m data_fetchers.xetra_instruments --config config/stock_momentum_free.toml`
   - Writes normalized rows to `securities` and `listings`.
   - Downloads automatically from the configured Deutsche Borse downloads page by default. `--file` and `--url` are supported overrides.

3. **Stooq daily price history** (`provider = 'stooq'`)
   - Ingested by: `python -m data_fetchers.stooq_prices --config config/stock_momentum_free.toml --zip <archive>` or `--symbol <symbol>`
   - Writes normalized OHLCV rows to `equity_price_bars`.
   - `adjustment_status` is `unknown` unless explicitly verified.
   - Bulk ZIP input remains manual for now.

4. **ECB FX rates** (`source = 'ECB'`)
   - Ingested by: `python -m data_fetchers.ecb_fx --config config/stock_momentum_free.toml`
   - Writes long-format rows to `fx_rates`.

### Notes
- `stock_prices` has been removed from the active schema in favor of `equity_price_bars`.
- The free stock momentum prototype is not point-in-time, does not reliably include delistings, and must not be treated as final allocation evidence.

---

## `commodity_prices`
Daily (or monthly, for some series) OHLCV history for commodities and benchmark price series.

### Sources currently ingested
1. **OpenBB SDK (provider-backed)** (no `source` column in-table)
   - Ingested by: `python -m data_fetchers.commodities [SYMBOLS...]`
   - Typical symbols: `GC=F`, `SI=F`, `HG=F`
   - OpenBB path:
     - Default endpoint path: `derivatives.futures.historical`
     - Override path: `OPENBB_COMMODITY_HISTORICAL_PATH`
     - Provider override: `--provider` or `OPENBB_COMMODITY_PROVIDER`
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

3. **Oil benchmark series** (stored into `commodity_prices`)
   - Ingested by: `python -m data_fetchers.oil_prices`
   - Source files/endpoints:
     - `USOIL`: EIA annual and monthly history pages:
       - https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=A&n=PET&s=F000000__3
       - https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=M&n=PET&s=F000000__3
     - `WTI` and `BRENT`: OpenBB `commodity.price.spot` with default provider `fred`.
   - Distinguish in-table:
     - `symbol = 'USOIL'`: official EIA long-run U.S. crude benchmark; annual history before monthly coverage, then monthly
     - `symbol = 'WTI'`: monthly WTI benchmark spot series
     - `symbol = 'BRENT'`: monthly Brent benchmark spot series
   - Storage shape:
     - All oil rows are stored as close-only benchmark levels with `open=high=low=close` and `volume=0`
   - Upstream docs:
     - EIA Petroleum Navigator history pages: https://www.eia.gov/dnav/pet/pet_pri_dfp1_k.htm
     - OpenBB commodity spot endpoint: https://docs.openbb.co/platform/reference/commodity/price/spot

### Notes
- Included in `python -m data_fetchers.refresh_all` by default via `commodities`, `gold_prices`, and `oil_prices`.
- This table has no `source` column. Use `symbol` and ingest path to infer provenance: futures symbols such as `GC=F` come from OpenBB futures history, `GOLD` comes from the GitHub CSV, `USOIL` comes from EIA, and `WTI`/`BRENT` come from OpenBB spot data.

---

## `interest_rates`
Interest rate series (typically FRED-backed) keyed by region/type/maturity/currency.

### Sources currently ingested
1. **OpenBB SDK → FRED series** (no `source` column in-table)
   - Ingested by: `python -m data_fetchers.bonds`
   - OpenBB path:
     - Default endpoint path: `economy.fred_series`
     - Override path: `OPENBB_FRED_SERIES_PATH`
     - Provider override: `--provider` or `OPENBB_RATES_PROVIDER`; `config/data_refresh.toml` currently passes `--provider fred`.
   - Distinguish in-table:
     - `region`, `rate_type`, `maturity`, `currency`
     - The FRED series IDs used for each maturity live in `data_fetchers/bonds.py` (`DEFAULT_SERIES`): `DGS1MO`, `DTB3`, `DTB6`, `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30`.
     - The OpenBB provider used is determined at ingest time and is **not persisted** in the table.
   - Upstream docs:
     - FRED: https://fred.stlouisfed.org
     - FRED API: https://fred.stlouisfed.org/docs/api/fred/
     - OpenBB documentation: https://docs.openbb.co

### Notes
- Included in `python -m data_fetchers.refresh_all` by default via `bonds`.

---

## `macro_data`
General macroeconomic series keyed by an `id` and date.

### Sources currently ingested
1. **Robert Shiller online data (Excel)**
   - Ingested by: `python -m data_fetchers.shiller_cape --url <excel_url>`
   - Legacy positional URL form also works: `python -m data_fetchers.shiller_cape <excel_url>`
   - Source file:
     - A current Shiller `ie_data` Excel URL is supplied by CLI or `config/data_refresh.toml`.
     - The URL can move over time, so the Yale data index remains the durable discovery page.
   - Distinguish in-table:
     - `id`: identifiers are defined in `data_fetchers/shiller_cols.json` (e.g., `sp_comp_price`, `sp_comp_div`, `sp_comp_earn`, `cpi`, `rate_gs10`)
     - `long_name`: descriptive name stored alongside the values
   - Upstream docs:
     - Shiller data index page: http://www.econ.yale.edu/~shiller/data.htm
     - The exact Excel URL can change; pass the current “ie_data” Excel URL to the fetcher.

### Notes
- The central refresh config currently enables `shiller_cape` with a configured Excel URL. Recheck or update that URL if the upstream Shiller file moves.

---

## `test_data`
Non-standard or derived series used during development/testing.

### Sources currently ingested
1. **Derived fields from Shiller ingest**
   - Ingested by: `python -m data_fetchers.shiller_cape --url <excel_url>`
   - Legacy positional URL form also works: `python -m data_fetchers.shiller_cape <excel_url>`
   - Distinguish in-table:
     - `id` values with `type: "derived"` in `data_fetchers/shiller_cols.json` (e.g., `sp_cape`, `r_sp_price`, …)

### Notes
- Populated by the same Shiller ingest run that fills `macro_data`; the current central refresh config enables that ingest with a configured Excel URL.

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
   - Source file:
     - `SignalDoc.csv` from the Open Asset Pricing data page / Google Drive file ID in `data_fetchers/open_asset_pricing_registry.py`.
   - Scope: one row per characteristic/signal
   - Distinguish in-table:
     - `source`, `characteristic_set`, `characteristic`
   - Upstream docs:
     - https://www.openassetpricing.com

### Notes
- Included in `python -m data_fetchers.refresh_all` by default via `open_asset_pricing`.

---

## `portfolio_characteristics`
Portfolio-level characteristic scores (time series keyed by portfolio and characteristic).

### Source
1. **Open Asset Pricing Data (Chen & Zimmermann)** (`source = 'open_asset_pricing'`)
   - Ingested by: `python -m data_fetchers.open_asset_pricing portfolio_characteristics --portfolio-scores-url <URL>` (alias: `portfolio-scores`)
   - Source file:
     - Operator-supplied CSV/ZIP URL via `--portfolio-scores-url`; `config/data_refresh.toml` contains a placeholder URL and keeps this fetcher disabled.
   - Scope: published portfolio-level scores if available; otherwise computed for a curated subset (e.g., GHZ72)
   - Distinguish in-table:
     - `source`, `portfolio_set`, `universe`, `frequency`, `portfolio`, `characteristic`
   - Upstream docs:
     - https://www.openassetpricing.com

### Notes
- The central refresh config ships with this ingest disabled by default until `--portfolio-scores-url` is configured.
