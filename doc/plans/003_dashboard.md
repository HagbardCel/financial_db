# Implementation Plan: Data Analysis Dashboard (Streamlit)

## Goal
Create a lightweight, local dashboard to explore and analyze the financial time-series data stored in PostgreSQL (prices, indices, macro indicators, rates, and derived views).

## Package Choice
**Recommended:** `streamlit`

**Why Streamlit**
- Python-only UI (no frontend stack) so it stays simple and lean.
- Great fit for exploratory analytics: widgets, tables, and caching (`st.cache_data`) are built-in.
- Runs well in a devcontainer/local workflow: `streamlit run ...`.
- Integrates cleanly with the existing stack (`pandas`, `sqlalchemy`, `matplotlib`/`seaborn`).

**Optional (only if needed)**
- `plotly` for interactive OHLC/candlestick charts and richer tooltips.

## Data Sources in This Repo
- Time-series (id/date/value): `assets_prices`, `indices`, `macro_data`, `shiller_derived_view`
- OHLCV: `stock_prices`, `commodity_prices`
- Rates: `interest_rates` (date/region/rate_type/maturity/currency)

## Dashboard Structure (Pages)
1. **Overview**
   - Row counts and date coverage per table
   - Latest observation date per dataset (freshness)
2. **Prices Explorer (Stocks/Commodities)**
   - Controls: symbol(s), date range, resample frequency (D/W/M)
   - Charts: close + volume (optional candlestick)
   - Metrics: total return, CAGR, max drawdown, rolling volatility
3. **Series Explorer (Assets/Indices/Macro)**
   - Controls: dataset + id(s), date range, transform (level, % change, YoY)
   - Charts: time series + distribution + summary stats
4. **Compare & Correlate**
   - Multi-select series from different sources (normalized to a common date index)
   - Correlation heatmap + pairwise scatter + rolling correlation
5. **Rates**
   - Yield curve snapshot (pick a date; maturity vs rate)
   - Historical series (pick region/rate_type/maturity/currency)
6. **Derived Metrics (Shiller CAPE)**
   - CAPE, real price/earnings/dividends, excess returns (from `shiller_derived_view`)
   - Percentile bands and “where are we vs history” indicators
7. **Data Browser / Export**
   - Filtered table view with CSV download
   - Display the SQL used for transparency/reproducibility

## Implementation Approach (Lean)
1. **Add dependencies**
   - `uv add streamlit`
   - Optional: `uv add plotly`
2. **Create a small `dashboard/` package**
   - `dashboard/app.py` (main entry, sidebar controls, page navigation)
   - `dashboard/db.py` (read-only query helpers via SQLAlchemy)
   - `dashboard/analytics.py` (returns, drawdown, rolling stats)
   - `dashboard/pages/` (one file per page; keep each page small)
3. **Reuse existing configuration**
   - Read `POSTGRES_*` env vars (already used elsewhere via `.devcontainer/.env`)
4. **Keep queries simple**
   - Always filter by date range + selected identifiers server-side
   - Prefer explicit column lists over `SELECT *`
5. **Performance basics**
   - Cache query results by parameters (`st.cache_data`) with a short TTL (e.g. 5–15 min)
   - Resample in Pandas for charting instead of pulling more rows than needed
6. **Minimal documentation**
   - Add a short “Run the dashboard” section to `doc/development.md` once the MVP is in place

## Out of Scope (For Now)
- Authentication/authorization (assumed local use)
- Multi-user deployment and permissions
- Heavy testing harness or migration tooling
- Elaborate error taxonomy; stick to clear UI messaging for common issues (missing env vars, empty results)

## Verification Plan (Lightweight)
1. Initialize schema: `python db_utils/db_setup.py`
2. Run: `uv run streamlit run dashboard/app.py`
3. Spot-check each page with a known symbol/id; confirm charts/metrics render and CSV export works.

