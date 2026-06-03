# EODHD Metadata and US Universe V1

## Goal

Keep `${RAW_DATA_DIR}/eodhd` as the exhaustive EODHD parquet archive while making PostgreSQL ingestion selective. The first increment loads broad reference metadata, emits metadata-quality reports, and builds an auditable US listed-common-equity candidate universe without ingesting the full price lake.

The local archive is intentionally not moved or rewritten. It already contains historical exchange and symbol snapshots plus per-symbol price files.

## Architecture Decisions

- Bare `python -m data_fetchers.eodhd ingest` is metadata-only.
- Full parquet-to-PostgreSQL ingestion remains available only through `ingest all --confirm-all-datasets`.
- `eodhd.*` stores provider snapshots, artifact provenance, universe definitions, build records, and membership decisions.
- Existing generic stock-momentum tables remain the later target for curated research-ready bars.
- Price quality, liquidity, FX conversion, and rolling backtest eligibility are follow-up phases.
- Metadata collected from `2026-05-29` onward cannot reconstruct true historical point-in-time membership before that date.

## Step 1: Broad Metadata Ingestion

Load complete exchange snapshots, consolidated symbol snapshots, and available symbol-change snapshots:

```bash
python -m data_fetchers.eodhd ingest metadata
```

Preserve typed exchange and symbol fields plus the original provider row in `raw_json`. Do not ingest prices, dividends, or splits through the safe default path.

## Step 2: Metadata Report

Generate an API-free report from parquet metadata and the SQLite checkpoint state:

```bash
python -m data_fetchers.eodhd report metadata --snapshot-date latest
```

Write reports under `derived/reports/eodhd/metadata/snapshot_date=<YYYY-MM-DD>/`, including exchange coverage, symbol counts, type counts, missing-ISIN rates, checkpoint statuses, US venue counts, and exact-ISIN duplicate groups.

## Step 3: US Candidate Universe

Build the first metadata-only candidate universe:

```bash
python -m data_fetchers.eodhd universes build \
  --snapshot-date latest \
  --universe eodhd_us_listed_common_equities_v1
```

Use `exchange_code = "US"`, provider type `Common Stock`, and an explicit listed-venue allowlist. Exclude known OTC venue labels and explicit ADR-like names. Keep uncertain venue labels in manual review. Preserve delisted candidates separately from active candidates.

## Cross-Exchange Duplicates

- Automatically group listings only when they share the same well-formed ISIN.
- Choose one preferred eligible US listing deterministically using the committed venue order.
- Keep active and delisted rows for the same EODHD symbol together as one listing history.
- Never merge missing-ISIN rows using ticker or normalized company name.
- Report cross-exchange exact-ISIN groups even when foreign listings are outside the US universe.
- Defer ADR-underlying, share-class, and manually reviewed mappings to a later override layer.

## Verification

Tests must cover metadata-only artifact selection, guarded full ingestion, report generation, exchange coverage gaps, SQLite checkpoint counts, OTC filtering, ADR filtering, exact-ISIN duplicate selection, similar missing-ISIN names remaining separate, and deterministic repeated builds.

## Step 4: US Price Quality Scan

Scan the selected active and delisted US candidates directly from the parquet archive before loading curated bars into PostgreSQL:

```bash
python -m data_fetchers.eodhd prices scan-quality \
  --universe eodhd_us_listed_common_equities_v1 \
  --build-id latest
```

Write deterministic reports under `derived/reports/eodhd/price_quality/<universe>/build_id=<build-id>/`. Keep structural failures, raw-price anomalies, adjusted-close coverage, volume quality, and unchanged-close runs visible at listing-history level. Use `--memberships-file` for an API-free and database-free report pass, and `--max-symbols` for deterministic smoke scans.

This phase does not ingest bars or apply present-day liquidity filters to historical data. Curated bar ingestion, exchange-calendar completeness checks, rolling as-of-date liquidity eligibility, FX conversion, and momentum-panel integration remain follow-up phases.

## Steps 5-8: Archive Completion and Selective Research Pipeline

Continue the exhaustive parquet archive independently:

```bash
python -m data_fetchers.eodhd refresh --refresh-after-days -1
```

Once a complete selected-US quality report exists, rebuild only EODHD research rows:

```bash
python -m data_fetchers.eodhd prices materialize-curated \
  --universe eodhd_us_listed_common_equities_v1 \
  --build-id latest \
  --quality-report derived/reports/eodhd/price_quality/eodhd_us_listed_common_equities_v1/build_id=<build-id>

python -m data_fetchers.ecb_fx --config config/stock_momentum_eodhd_us.toml
python -m analyses.stock_momentum.build_price_panel --config config/stock_momentum_eodhd_us.toml
python -m analyses.stock_momentum.build_eligibility --config config/stock_momentum_eodhd_us.toml
python -m analyses.stock_momentum.build_momentum_panel --config config/stock_momentum_eodhd_us.toml
```

The curated loader uses valid ISINs as security identities, preserves missing-ISIN listings separately, merges active and delisted parquet histories with active overlap precedence, and scales full OHLC values using `adjusted_close / close`. Rows without usable adjusted close are rejected. Raw close, volume, dollar volume, and adjustment factors remain available in compact EODHD audit metrics.

The isolated `eodhd_us_v1` profile converts prices with ECB FX rates and persists daily price-derived eligibility on XNYS sessions. Eligibility requires 13 months of history, EUR 2 minimum price, at most 5 stale calendar days, at most 10% missing sessions over 252 XNYS sessions, and a trailing 63-session median raw dollar volume of USD 1 million. Historical rows before the first EODHD metadata snapshot remain explicitly labeled as a price-derived proxy rather than historical point-in-time membership.
