# Stock Momentum Data Pipeline

## Goal

Build a free prototype data pipeline for testing stock momentum strategies while keeping the implementation aligned with this repository's Postgres-first architecture.

The initial profile is `free_prototype`, using Xetra reference data, Stooq daily equity bars, and ECB EUR FX rates. The durable project name is `stock_momentum`; avoid encoding "stage1" in active file, table, and module names.

## Architecture Decisions

- Store normalized data in Postgres, not Parquet/DuckDB.
- Keep source-specific fetchers in `data_fetchers/`.
- Keep strategy construction, validation, and backtest helpers in `analyses/stock_momentum/`.
- Use `config/stock_momentum_free.toml` for the free prototype profile.
- Keep source limitations visible in generated reports and docs.

## Active Tables

- `securities`
- `listings`
- `equity_price_bars`
- `fx_rates`
- `equity_prices_eur`
- `equity_eligibility`
- `stock_momentum_panels`
- `stock_momentum_trades`
- `stock_momentum_results`
- `ingestion_manifests`
- `pipeline_runs`

The old `stock_prices` and `assets_prices` tables are intentionally removed from active schema setup. Equity data needs source, listing, currency, FX, adjustment, and mapping provenance.

## Run Order

```bash
python -m data_fetchers.xetra_instruments --config config/stock_momentum_free.toml
python -m data_fetchers.stooq_prices --config config/stock_momentum_free.toml --zip derived/stock_momentum/raw/stooq/bulk/stooq_daily.zip
python -m data_fetchers.ecb_fx --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.build_price_panel --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.build_momentum_panel --config config/stock_momentum_free.toml --frequency monthly
python -m analyses.stock_momentum.build_momentum_panel --config config/stock_momentum_free.toml --frequency quarterly
python -m analyses.stock_momentum.run_backtest --config config/stock_momentum_free.toml
python -m analyses.stock_momentum.validate --config config/stock_momentum_free.toml
```

## Prototype Limitations

- The free prototype uses a current tradability proxy, not a historical point-in-time broker universe.
- Delisted securities are not reliably included.
- Stooq adjustment status is not treated as institutional-quality total-return data.
- Identifier mapping is incomplete and partly manual.
- Results are useful for engineering and signal intuition, not final allocation decisions.

## Download Behavior

- Xetra reference data is downloaded automatically from the configured Deutsche Borse downloads page. Use `--url` for a direct download override or `--file` for a local reproducibility fixture.
- ECB FX data is downloaded automatically from the configured ECB Data API endpoint. Use `--url` or `--file` for overrides.
- Stooq bulk data remains manual for now; place the downloaded ZIP under `derived/stock_momentum/raw/stooq/bulk/` and pass it with `--zip`.
