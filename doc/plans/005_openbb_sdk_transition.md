# Plan: Transition Data Fetching to OpenBB SDK

## Goal
Use the OpenBB SDK as the single integration point for fetching market/macro data so the repo can add/replace data sources quickly with minimal bespoke API code, while adding a deterministic historical gold price series from the datasets/gold-prices monthly CSV.

Constraints from this repo/task:
- Keep the codebase lean (avoid over-abstraction and heavy frameworks).
- Keep testing lightweight (no broad test harness).
- Do not plan a migration strategy for existing DB data.
- Do not preserve compatibility with legacy fetcher entrypoints/code.
- Historical gold prices must be sourced from `https://github.com/datasets/gold-prices/blob/main/data/monthly.csv?utm_source=chatgpt.com`.
- Use OpenBB for all data sources (even when loading CSV manually); only Shiller CAPE remains a direct, non-OpenBB pipeline for now.

## Current State (Repo)
Today, data ingestion is implemented as standalone scripts in `data_fetchers/` following `fetch()` → `transform()` → `save()` via `BaseFetcher` and `DataRepository`.

Primary sources/libraries:
- OpenBB SDK → `data_fetchers/stock_prices.py` (stocks), `data_fetchers/commodities.py` (commodities), and `data_fetchers/bonds.py` (Treasury yields).
- Shiller CAPE via direct download + `pandas.read_excel` → `data_fetchers/shiller_cape.py` (independent of OpenBB).

## Pros / Cons (Debate)

### Pros
- **Single API surface**: one client (`openbb`) instead of per-provider SDKs (`yfinance`, `pandas_datareader`, bespoke HTTP).
- **More sources, faster**: adding a new provider often becomes a config change (provider selection + API key) rather than a new fetcher implementation.
- **Better long-term optionality**: easy to branch into asset classes not currently covered (crypto, fx, options, fundamentals) without re-architecting ingestion.
- **Centralized auth/config**: one place to manage provider keys and provider selection.
- **Smaller per-source code**: fetchers become mostly “call OpenBB → normalize → save”.

### Cons
- **Dependency weight**: OpenBB can pull in a large dependency graph (risking bloat for a small repo).
- **Version churn**: OpenBB’s API surface and provider behavior can change; pinning versions becomes important.
- **Abstraction leakage**: different providers still have different coverage/quirks; you often still need provider-specific handling.
- **API keys + rate limits**: many “better sources” require keys and have usage limits; OpenBB doesn’t remove that reality.
- **Debugging complexity**: failures may be harder to diagnose when routed through a framework layer.

### Practical recommendation
Adopt OpenBB if the priority is “expand sources quickly” and you’re okay with:
- pinning a specific OpenBB version/provider set, and
- isolating OpenBB usage behind a small adapter layer so future upstream changes are localized.

If the priority is “minimal dependencies and maximum stability”, keep the current direct-provider approach and add sources surgically.

## Transition Plan (Detailed, Lean)

### Phase 0 — Spike (time-boxed) to validate fit
Deliverable: a short script proving OpenBB can fetch the minimum datasets needed *and* the dependency footprint is acceptable.

1. Choose the packaging strategy (to minimize bloat):
   - Confirm the correct package name/version for “OpenBB SDK” in this environment (e.g., `openbb` vs `openbb-sdk`) and what provider extras are required.
   - Prefer installing only the providers you will actually use (e.g., Yahoo + FRED equivalents), not “all providers”.
2. Verify output shapes for:
   - Equity OHLCV historical prices (for `stock_prices`).
   - Commodity/futures-like series (for `commodity_prices`).
   - FRED-like macro series and/or yield data (for `macro_data` and `interest_rates`).
3. Decide go/no-go:
   - If OpenBB is too heavy or cannot reliably cover the needed endpoints, stop here and keep the current approach.

### Phase 1 — Add OpenBB dependency + pin versions
1. Add OpenBB dependencies to `pyproject.toml` and regenerate `uv.lock`.
2. Pin a specific major/minor version to reduce churn.
3. Document required environment variables for providers (API keys), keeping the repo’s existing “env var only” style.

### Phase 2 — Create a tiny OpenBB adapter (single file)
Goal: concentrate OpenBB imports, provider selection, and result normalization in one place.

1. Add `data_fetchers/openbb_client.py` (or similar) that:
   - Instantiates/returns the OpenBB client.
   - Applies provider selection defaults (hardcoded minimal defaults are fine).
   - Converts returned results into plain `pandas.DataFrame` objects.
2. Keep the adapter intentionally small:
   - No caching layer (the DB is the cache).
   - No new configuration system; use env vars + a few CLI flags.

### Phase 2b — Evaluate OpenBB data models (optional)
Goal: reduce normalization glue if OpenBB’s model layer makes this simpler without adding complexity.

1. Review OpenBB model outputs (`to_df()`, model classes, or `openbb-core` models) for the datasets in scope.
2. If using models eliminates custom normalization logic, adapt `openbb_client` to rely on those models.
3. If models add weight or don’t align with the DB schemas, keep the current DataFrame normalization.

Decision (current): keep the existing DataFrame normalization layer; revisit after the gold CSV and stock/commodity/rates fetchers are stabilized.

### Phase 3 — Replace the existing price/rates fetchers
Goal: keep the *database tables* the same so the dashboard and derived SQL remain intact, while replacing the *ingestion* layer.

1. Replace stock price ingestion:
   - Replace `data_fetchers/stock_prices.py` with `data_fetchers/stock_prices.py` (OpenBB-backed) that writes to `stock_prices`.
   - Continue to accept CLI symbols: `python -m data_fetchers.stock_prices AAPL MSFT`.
   - Normalize to the existing schema: `symbol,date,open,high,low,close,volume`.
2. Replace commodity price ingestion:
   - Replace `data_fetchers/commodities.py` with an OpenBB-backed equivalent that writes to `commodity_prices`.
   - Keep it close to today’s behavior (default symbols like `GC=F`, `SI=F`, `HG=F` are fine).
   - Add a dedicated gold history fetcher sourced from the datasets/gold-prices monthly CSV:
     - Prefer a small fetcher (e.g., `data_fetchers/gold_prices.py`) rather than overloading the OpenBB path.
     - Use the raw GitHub URL (`https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv`) for ingestion.
     - Route the CSV through the OpenBB adapter (e.g., `openbb_client.to_dataframe`) to keep the OpenBB-only policy.
     - Parse monthly dates and normalize to `commodity_prices` (set `open=high=low=close`, `volume=0`) using a stable symbol (e.g., `GOLD` or `XAUUSD`).
     - Store provenance (source URL) in doc comments and README so it remains explicit.
3. Replace FRED-based ingestion (macro and/or yields):
   - Replace `data_fetchers/bonds.py` with an OpenBB-backed yield curve fetcher that writes to `interest_rates`.
4. Leave Shiller CAPE ingestion as-is:
   - It’s already a clean standalone pipeline and OpenBB doesn’t materially simplify it.

### Phase 4 — Delete/trim legacy dependencies and code
Goal: keep the repo lean after the switch.

1. Remove direct usage of provider-specific packages from the codebase.
2. If OpenBB fully replaces them, remove direct dependencies (`yfinance`, `pandas-datareader`) from `pyproject.toml`.
   - If OpenBB internally requires one of them, keep the dependency but remove *direct* imports from this repo.
3. Remove old fetcher modules that are no longer used (no compatibility requirement).

### Phase 5 — Update docs and keep testing light
1. Update run instructions:
   - `README.md` and `doc/development.md` should show OpenBB-based commands and required provider env vars.
2. Lightweight verification (no heavy harness):
   - Add one or two unit tests that validate the OpenBB → schema normalization logic using small, local DataFrames (no network).
   - Keep any “hits the network + writes to DB” checks as manual smoke tests or `pytest -m integration` tests.

## Acceptance Criteria
- A single OpenBB-backed ingestion path exists for:
  - `stock_prices` (equities OHLCV)
  - `commodity_prices` (commodities/futures-like series)
  - `interest_rates` (Treasury/yield curve style data)
  - (Optional) `macro_data` (macro time series)
- Gold historical prices are ingested from the datasets/gold-prices monthly CSV and visible in the chosen table.
- A decision is recorded on whether OpenBB data models reduce normalization complexity.
- Legacy naming is removed; `data_fetchers.stock_prices` is the standard entrypoint.
- The dashboard continues to work without schema changes (or is trivially updated if a small schema tweak is chosen).
- Provider configuration is env-var driven and minimal.
- Dependencies are reviewed and trimmed (no “install everything”).

## Verification Plan (Lightweight)
1. Initialize schema: `python db_utils/db_setup.py`
2. Run smoke ingestions (small date windows):
   - Stocks: ingest 1–2 symbols into `stock_prices`
   - Commodities: ingest 1–2 symbols into `commodity_prices`
   - Gold: ingest the monthly CSV into the chosen table (check date coverage and row counts)
   - Rates: ingest US Treasuries into `interest_rates`
3. Open the dashboard and confirm the new series appear in the browser/explorer.
4. Run tests: `pytest -q` (and optionally `pytest -m integration` if you add an integration smoke test).

## Out of Scope (By Design)
- Migrating or preserving existing DB data
- Keeping old script names/CLI compatibility
- Building a generic “provider plugin system” beyond what OpenBB already provides
- Large test suites, elaborate mocking, or full end-to-end CI pipelines
