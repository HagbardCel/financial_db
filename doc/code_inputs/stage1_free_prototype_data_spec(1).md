# Stage 1 Specification — Free Prototype Data Pipeline for Scalable-Style Stock Momentum Backtesting

**Project:** Scalable-compatible top-N stock momentum backtest  
**Stage:** 1 — free prototype  
**Audience:** junior developer implementing independently  
**Authoring date:** 2026-05-13  
**Primary goal:** Build a reproducible, free, local data pipeline sufficient to prototype and debug the monthly/quarterly top-3/top-5/top-10 stock momentum strategy.

---

## 1. Executive summary

Stage 1 is a **free prototype**, not the final investment-grade dataset.

It should allow us to:

1. Build the local data lake structure.
2. Ingest current tradable-instrument reference data from Deutsche Börse/Xetra.
3. Ingest free historical daily prices from Stooq.
4. Ingest EUR FX reference rates from the ECB.
5. Build a first EUR-denominated return panel.
6. Run a first momentum backtest with monthly and quarterly rebalancing.
7. Identify implementation bugs, identifier-mapping problems, survivorship-bias issues, and signal/execution assumptions before paying for better data.

The correct interpretation of Stage 1 results is:

> Useful for engineering and first-order intuition.  
> Not sufficient for final strategy conclusions because the universe is not point-in-time, delisting coverage is incomplete, and corporate-action adjustment quality is not fully controlled.

---

## 2. Stage 1 deliverables

The developer must produce the following deliverables.

### 2.1 Repository deliverables

```text
scalable-momentum/
├── pyproject.toml
├── README.md
├── configs/
│   ├── stage1_free.yaml
│   └── logging.yaml
├── src/
│   └── scalable_momentum/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── io/
│       │   ├── http.py
│       │   ├── parquet.py
│       │   └── manifests.py
│       ├── ingest/
│       │   ├── xetra.py
│       │   ├── stooq.py
│       │   └── ecb_fx.py
│       ├── transform/
│       │   ├── security_master.py
│       │   ├── prices.py
│       │   ├── fx.py
│       │   ├── eligibility.py
│       │   └── momentum_panel.py
│       ├── backtest/
│       │   ├── signals.py
│       │   ├── weights.py
│       │   ├── engine.py
│       │   ├── costs.py
│       │   └── metrics.py
│       └── validation/
│           ├── checks.py
│           └── reports.py
├── tests/
│   ├── test_xetra_parser.py
│   ├── test_stooq_parser.py
│   ├── test_ecb_fx.py
│   ├── test_momentum_signal.py
│   ├── test_no_lookahead.py
│   └── test_backtest_accounting.py
└── Makefile
```

### 2.2 Data deliverables

All local data must be written below a configurable base directory, default:

```text
~/data/finance/scalable_momentum/
```

Required structure:

```text
~/data/finance/scalable_momentum/
├── raw/
│   ├── xetra/
│   ├── stooq/
│   └── ecb_fx/
├── bronze/
│   ├── xetra/
│   ├── stooq/
│   └── ecb_fx/
├── silver/
│   ├── securities/
│   ├── listings/
│   ├── prices/
│   ├── fx/
│   └── eligibility/
├── gold/
│   ├── momentum_panels/
│   ├── backtests/
│   └── reports/
└── metadata/
    ├── manifests/
    ├── data_quality/
    └── run_logs/
```

### 2.3 Analytical deliverables

The stage is complete when these files exist:

```text
gold/momentum_panels/stage1_monthly_panel.parquet
gold/momentum_panels/stage1_quarterly_panel.parquet
gold/backtests/stage1_results_summary.parquet
gold/backtests/stage1_trades.parquet
gold/reports/stage1_data_quality_report.md
gold/reports/stage1_backtest_summary.md
```

---

## 3. Source data overview

### 3.1 Deutsche Börse/Xetra tradable instruments

**Purpose:** Approximate the broker-tradable universe using Xetra tradable instruments.

Scalable offers access to Xetra/gettex/EIX trading venues. Stage 1 should start with Xetra as the cleanest official reference file.

Official source pages:

```text
https://www.cashmarket.deutsche-boerse.com/cash-de/Handel/Handelbare-Werte-Xetra/Downloads
https://www.cashmarket.deutsche-boerse.com/cash-en/trading/Tradable-Instruments-Xetra/Downloads/xetra-downloads
```

Relevant file:

```text
T7 (Xetra) All tradable instruments
Expected production filename pattern:
t7-xetr-allTradableInstruments.csv
```

Official format notes from the Cash Markets Instrument Reference Data Guide:

```text
File extension: CSV
Delimiter: semicolon ;
Decimal symbol: point .
Line 1: market MIC, e.g. XETR
Line 2: last update date
Line 3: column names
Line 4 onward: instrument records
```

Required ingestion behavior:

1. Download the CSV to `raw/xetra/`.
2. Store the exact raw file unchanged.
3. Store a manifest with:
   - source URL
   - download timestamp
   - file name
   - SHA-256 checksum
   - byte size
   - row count after parsing
4. Parse the file starting from the correct header row.
5. Preserve all raw columns in bronze.
6. Create a normalized silver security/listing table.

### 3.2 Optional Deutsche Börse Frankfurt tradable instruments

Use this only after Xetra ingestion works.

Official source page:

```text
https://www.cashmarket.deutsche-boerse.com/cash-de/Handel/Handelbare-Werte-Xetra/Downloads/frankfurt-downloads
```

Relevant file:

```text
T7 (Frankfurt) All tradable instruments - csv
Expected filename pattern:
t7-xfra-BF-allTradableInstruments.csv
```

This can help approximate names that are tradable via Börse Frankfurt/gettex-like retail venues, but Stage 1 must not depend on it.

### 3.3 Stooq historical data

**Purpose:** Free prototype price history.

Official source:

```text
https://stooq.com/db/h/
```

Stooq provides free historical market data downloads in daily/hourly/5-minute frequencies and ASCII/Metastock formats. The relevant Stage 1 dataset is **daily ASCII**.

Important limitation:

- Stooq is excellent for prototyping.
- It is not a clean survivorship-bias-free institutional equity database.
- Corporate-action adjustment must be empirically checked.
- Identifier mapping to Xetra/Scalable instruments is imperfect because Stooq tickers do not reliably carry ISINs.

Required ingestion modes:

1. **Bulk mode, preferred for broad prototype:**
   - Manually download Stooq daily ASCII archive(s) from the official database page.
   - Place raw ZIP files into `raw/stooq/bulk/`.
   - The pipeline must parse all ZIP files in that folder.

2. **Per-symbol mode, useful for debugging:**
   - Use Stooq quote download URLs for specific symbols.
   - Store each raw CSV in `raw/stooq/symbols/{symbol}.csv`.
   - This mode is acceptable for a restricted prototype universe.

The developer should implement both, but bulk mode has priority.

### 3.4 ECB EUR FX reference rates

**Purpose:** Convert non-EUR price series into EUR.

Official pages:

```text
https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
https://data.ecb.europa.eu/help/api/data
```

ECB data API concept:

```text
Daily USD against EUR reference rate key:
D.USD.EUR.SP00.A

All daily currencies against EUR:
D..EUR.SP00.A
```

Required ingestion behavior:

1. Download all daily FX rates against EUR.
2. Store raw response under `raw/ecb_fx/`.
3. Normalize to long format:

```text
date | currency | units_per_eur | source
```

Interpretation:

```text
units_per_eur = number of foreign-currency units for 1 EUR
```

Price conversion:

```text
price_eur = price_local / units_per_eur
```

Special case:

```text
If currency == "EUR":
    units_per_eur = 1.0
    price_eur = price_local
```

---

## 4. Technology stack

Use Python with `uv`.

Minimum Python version:

```text
Python >= 3.11
```

Required dependencies:

```text
pandas
numpy
pyarrow
duckdb
requests
tenacity
pydantic
pydantic-settings
typer
rich
python-dateutil
pyyaml
pytest
ruff
mypy
```

Optional but useful:

```text
polars
pandera
great-expectations
```

Preferred storage:

```text
Parquet files partitioned by provider/exchange/year
DuckDB for ad-hoc queries and validation
```

Do **not** start with PostgreSQL in Stage 1 unless specifically requested. Parquet + DuckDB is simpler and better for rapid iteration.

---

## 5. Configuration file

Create `configs/stage1_free.yaml`.

Minimum required structure:

```yaml
project:
  name: scalable_momentum_stage1
  base_currency: EUR
  data_dir: "~/data/finance/scalable_momentum"
  start_date: "2000-01-01"
  end_date: null

sources:
  xetra:
    enabled: true
    manual_download_allowed: true
    source_page: "https://www.cashmarket.deutsche-boerse.com/cash-de/Handel/Handelbare-Werte-Xetra/Downloads"
    expected_file_pattern: "t7-xetr-allTradableInstruments*.csv"

  frankfurt:
    enabled: false
    manual_download_allowed: true
    source_page: "https://www.cashmarket.deutsche-boerse.com/cash-de/Handel/Handelbare-Werte-Xetra/Downloads/frankfurt-downloads"
    expected_file_pattern: "t7-xfra-BF-allTradableInstruments*.csv"

  stooq:
    enabled: true
    source_page: "https://stooq.com/db/h/"
    ingestion_modes:
      - bulk
      - per_symbol
    markets:
      - us
      - de
      - uk
      - fr
      - nl
      - ch
    raw_bulk_dir: "raw/stooq/bulk"

  ecb_fx:
    enabled: true
    api_base: "https://data-api.ecb.europa.eu/service/data"
    series_key: "D..EUR.SP00.A"

universe:
  include_trading_venues:
    - XETR
  include_security_types:
    - common_stock
  exclude_name_patterns:
    - ETF
    - ETC
    - ETN
    - FUND
    - WARRANT
    - CERTIFICATE
    - TURBO
    - OPTION
    - BOND
  min_price_eur: 2.0
  min_history_months_before_eligibility: 13
  max_stale_price_days_at_rebalance: 5
  max_missing_daily_price_ratio_per_year: 0.10

momentum:
  lookbacks_months:
    - 3
    - 6
    - 9
    - 12
  skip_recent_months:
    - 0
    - 1
  rank_metric: total_return_eur
  positive_momentum_only: false

backtest:
  rebalance_frequencies:
    - monthly
    - quarterly
  top_n:
    - 3
    - 5
    - 10
  weighting_schemes:
    - equal_weight
    - positive_momentum_proportional
  cash_return_annual: 0.0
  transaction_cost_bps_one_way:
    - 0
    - 10
    - 25
    - 50
    - 100
```

---

## 6. Data model

### 6.1 `silver/securities/securities.parquet`

One row per economic security when possible.

Required columns:

```text
security_id              string, stable internal ID
isin                     string or null
name                     string
security_type            string
country                  string or null
currency_primary         string or null
source_first_seen        string
source_last_seen         string
active_flag_current      bool
created_at_utc           timestamp
updated_at_utc           timestamp
```

Implementation note:

- In Stage 1, `security_id` can be generated as:
  - `isin` if available
  - otherwise `provider:exchange:symbol`
- Do not assume ticker is a stable identity.

### 6.2 `silver/listings/listings.parquet`

One row per listing/trading line.

Required columns:

```text
listing_id               string, stable internal ID
security_id              string
provider                 string, e.g. xetra, stooq
provider_symbol          string
exchange_code            string or null
mic                      string or null
trading_currency         string or null
isin                     string or null
name                     string or null
first_seen_date          date or null
last_seen_date           date or null
is_currently_tradable    bool or null
source_file              string
```

### 6.3 `silver/prices/stooq_daily.parquet`

Partition by year or by provider/exchange/year.

Required columns:

```text
provider                 string, "stooq"
provider_symbol          string
security_id              string or null
listing_id               string or null
date                     date
open                     float64
high                     float64
low                      float64
close                    float64
volume                   float64
currency                 string or null
adjustment_status        string, e.g. unknown, close_only, adjusted_unverified
source_file              string
ingested_at_utc          timestamp
```

Stage 1 must not label Stooq data as reliable total-return data unless adjustment quality has been verified.

### 6.4 `silver/fx/ecb_daily.parquet`

Required columns:

```text
date                     date
currency                 string
units_per_eur            float64
source                   string, "ECB"
ingested_at_utc          timestamp
```

### 6.5 `silver/prices/prices_eur_daily.parquet`

Required columns:

```text
security_id              string
listing_id               string
provider                 string
provider_symbol          string
date                     date
price_local              float64
currency                 string
units_per_eur            float64
price_eur                float64
is_fx_forward_filled     bool
source_price_file        string
source_fx_file           string
```

FX forward-fill rule:

- Forward-fill ECB FX only across non-publication days.
- Maximum forward-fill: 5 calendar days.
- If no valid FX rate exists within 5 calendar days, set `price_eur = null`.

### 6.6 `silver/eligibility/eligibility_daily.parquet`

Required columns:

```text
security_id
date
eligible_price_available
eligible_min_history
eligible_min_price
eligible_missingness
eligible_security_type
eligible_current_tradable_proxy
eligible_final
ineligibility_reason
```

### 6.7 `gold/momentum_panels/*.parquet`

Required columns:

```text
rebalance_date
signal_date
execution_date
security_id
listing_id
provider_symbol
name
currency
price_eur_signal
price_eur_lookback
momentum_3m
momentum_6m
momentum_9m
momentum_12m
momentum_12_1m
volatility_3m
volatility_6m
volatility_12m
rank_metric
rank_ascending_false
eligible_final
```

### 6.8 `gold/backtests/stage1_trades.parquet`

Required columns:

```text
strategy_id
rebalance_date
execution_date
security_id
provider_symbol
side                       buy/sell
target_weight
previous_weight
trade_weight
price_eur
gross_trade_value_eur
transaction_cost_eur
rationale_rank
rationale_momentum
```

---

## 7. Identifier mapping strategy

Identifier mapping is the highest-risk engineering area in Stage 1.

### 7.1 Mapping priorities

Use the following hierarchy:

1. Exact ISIN match where both sources provide ISIN.
2. Exact provider symbol mapping from manually curated override file.
3. Exchange ticker + normalized name match.
4. Fuzzy name match only for candidate generation, never for automatic final mapping without a confidence threshold.

### 7.2 Manual override file

Create:

```text
configs/mapping_overrides_stage1.csv
```

Columns:

```text
security_id,isin,xetra_symbol,stooq_symbol,name,exchange_code,currency,confidence,notes
```

Rules:

- `confidence >= 0.95` may be used automatically.
- `confidence < 0.95` must be flagged in data-quality report.
- Every manual override must include a short note.

### 7.3 Stage 1 mapping acceptance

The Stage 1 pipeline is acceptable if it maps at least:

```text
Minimum: 250 securities with usable daily history
Target: 500-2,000 securities with usable daily history
```

The developer must report:

```text
xetra_current_instruments_count
stooq_symbols_count
mapped_security_count
mapped_security_count_by_currency
mapped_security_count_by_country
unmapped_xetra_count
ambiguous_mapping_count
```

---

## 8. Backtest assumptions

### 8.1 Timeline and no-lookahead rule

Use three dates per rebalance:

```text
signal_date     = last available trading day in the formation period
rebalance_date  = calendar month-end or quarter-end label
execution_date  = first available trading day after signal_date
```

The strategy must never use prices from `execution_date` or later when calculating ranks.

### 8.2 Rebalance frequencies

Monthly:

```text
One rebalance per calendar month.
Signal uses last available close before or on month-end.
Execution occurs on the next available trading day.
```

Quarterly:

```text
One rebalance per calendar quarter.
Quarter ends: Mar, Jun, Sep, Dec.
Signal uses last available close before or on quarter-end.
Execution occurs on the next available trading day.
```

### 8.3 Momentum calculations

For lookback `L` months:

```text
momentum_Lm = price_eur(signal_date) / price_eur(signal_date - L calendar months) - 1
```

For 12-month momentum excluding the most recent month:

```text
momentum_12_1m = price_eur(signal_date - 1 calendar month)
                 / price_eur(signal_date - 12 calendar months)
                 - 1
```

Price lookup rule:

- For target dates that are not trading days, use the most recent available price not older than 5 trading days.
- If no price is available within tolerance, momentum is null.

### 8.4 Eligibility

A stock is eligible at a rebalance date if all conditions are true:

```text
currently_tradable_proxy == true
price_eur_signal is not null
price_eur_signal >= min_price_eur
history available for selected lookback
missing-price ratio within threshold
security type is included
```

### 8.5 Ranking

For each rebalance date and strategy variant:

1. Filter to eligible securities.
2. Compute selected momentum metric.
3. Exclude null metric values.
4. Sort descending by momentum.
5. Select top N where N ∈ {3, 5, 10}.

Tie-breakers:

```text
1. Higher momentum
2. Higher trailing 3-month EUR volume proxy if available
3. Lower provider_symbol alphabetically for deterministic output
```

### 8.6 Weighting

Equal weight:

```text
weight_i = 1 / N
```

Positive momentum proportional:

```text
raw_i = max(momentum_i, 0)
if sum(raw_i) > 0:
    weight_i = raw_i / sum(raw_i)
else:
    hold cash
```

For Stage 1, do not use leverage.

### 8.7 Cash

Cash return default:

```text
0.0% annualized
```

This is intentionally conservative and simple for Stage 1.

### 8.8 Transaction costs

Apply one-way cost to absolute traded weight:

```text
cost_t = portfolio_value_before_trade
         * sum(abs(target_weight_i - previous_weight_i))
         * transaction_cost_bps_one_way / 10000
```

Run sensitivity:

```text
0 bps
10 bps
25 bps
50 bps
100 bps
```

### 8.9 Dividends and corporate actions

Stage 1 uses Stooq prices as a prototype return proxy.

The data-quality report must explicitly say:

```text
Stage 1 Stooq-based returns are not guaranteed to be total-return-adjusted.
Final conclusions require Stage 2 adjusted close / dividend-adjusted data.
```

---

## 9. CLI requirements

Implement a Typer-based CLI.

Required commands:

```bash
scalable-momentum ingest-xetra --config configs/stage1_free.yaml
scalable-momentum ingest-stooq --config configs/stage1_free.yaml
scalable-momentum ingest-ecb-fx --config configs/stage1_free.yaml
scalable-momentum build-security-master --config configs/stage1_free.yaml
scalable-momentum build-price-panel --config configs/stage1_free.yaml
scalable-momentum build-momentum-panel --config configs/stage1_free.yaml --frequency monthly
scalable-momentum build-momentum-panel --config configs/stage1_free.yaml --frequency quarterly
scalable-momentum run-backtest --config configs/stage1_free.yaml
scalable-momentum validate-stage1 --config configs/stage1_free.yaml
```

Add convenience commands:

```bash
make stage1
make test
make lint
make validate
```

`make stage1` must run the full pipeline in correct order.

---

## 10. Validation and quality checks

### 10.1 Raw ingestion checks

For every raw source file:

```text
file_exists
byte_size > 0
checksum recorded
download_timestamp recorded
source URL recorded
```

### 10.2 Xetra checks

Required checks:

```text
row_count > 0
header row detected correctly
MIC parsed from line 1
last_update parsed from line 2
ISIN column exists or is mapped
no duplicate (isin, instrument_id) rows after normalization unless expected
```

### 10.3 Stooq checks

Required checks:

```text
date parses as date
OHLC columns numeric
high >= low
open between low and high, unless missing
close between low and high, unless missing
volume >= 0
no duplicate (provider_symbol, date)
dates strictly increasing per symbol after sorting
```

### 10.4 FX checks

Required checks:

```text
EUR rate is always 1.0
all rates > 0
no duplicate (date, currency)
USD, GBP, CHF, JPY exist for recent dates unless source missing
forward-fill never exceeds configured max days
```

### 10.5 No-lookahead checks

Unit tests must verify:

1. A stock whose price jumps on execution date is not ranked using that jump.
2. A stock without enough lookback history is excluded.
3. A delisted or missing series does not create artificial zero returns.
4. Weights sum to 1.0 or less; residual is cash.

### 10.6 Backtest accounting checks

Required checks:

```text
sum(target_weights) <= 1.0 + tolerance
portfolio_value never negative
transaction cost >= 0
turnover >= 0
daily/monthly returns finite unless no portfolio exists
no duplicate strategy_id/rebalance_date/security_id rows
```

---

## 11. Stage 1 report requirements

Create:

```text
gold/reports/stage1_data_quality_report.md
gold/reports/stage1_backtest_summary.md
```

### 11.1 Data-quality report contents

Minimum sections:

1. Source files ingested.
2. Date ranges by source.
3. Security counts by source.
4. Mapping coverage.
5. Unmapped instruments.
6. Ambiguous mappings.
7. Price-history coverage.
8. Missing-data statistics.
9. FX coverage.
10. Known limitations.
11. Recommendation for Stage 2 corrections.

### 11.2 Backtest summary contents

Minimum sections:

1. Strategy variants tested.
2. Parameter grid.
3. CAGR / annualized return.
4. Annualized volatility.
5. Sharpe ratio, using cash return as risk-free proxy for Stage 1.
6. Maximum drawdown.
7. Turnover.
8. Number of rebalances.
9. Number of trades.
10. Average holding period.
11. Best/worst rebalance periods.
12. Top recurring holdings.
13. Warning box: Stage 1 is not final evidence.

---

## 12. Implementation order

The junior developer should implement in this order.

### Step 1 — repository skeleton

Acceptance criteria:

```bash
uv run pytest
uv run ruff check .
```

both run successfully, even if tests are initially minimal.

### Step 2 — config loader

Acceptance criteria:

```bash
uv run scalable-momentum show-config --config configs/stage1_free.yaml
```

prints the resolved config including expanded data paths.

### Step 3 — manifest system

Implement `metadata/manifests/*.json`.

Each manifest entry:

```json
{
  "source": "stooq",
  "source_url": "...",
  "local_path": "...",
  "downloaded_at_utc": "...",
  "sha256": "...",
  "byte_size": 123,
  "row_count": 456,
  "status": "ok"
}
```

Acceptance criteria:

- Manifest is written for every raw file.
- Re-running ingestion does not overwrite raw files without recording a new manifest version.

### Step 4 — Xetra parser

Acceptance criteria:

- Parses semicolon-delimited CSV.
- Correctly skips metadata rows.
- Outputs bronze and silver tables.
- Unit test uses a small fixture with the first three metadata lines.

### Step 5 — Stooq parser

Acceptance criteria:

- Parses at least one per-symbol CSV.
- Parses at least one ZIP-based bulk fixture.
- Outputs normalized daily prices.
- Flags adjustment status as `unknown` unless explicitly verified.

### Step 6 — ECB FX parser

Acceptance criteria:

- Downloads or reads fixture of ECB FX data.
- Outputs long-format daily FX rates.
- Converts a known USD price to EUR correctly.

### Step 7 — security master and mapping

Acceptance criteria:

- Builds `securities.parquet` and `listings.parquet`.
- Reads manual mapping overrides.
- Produces mapping statistics report.

### Step 8 — EUR price panel

Acceptance criteria:

- Produces `prices_eur_daily.parquet`.
- Handles EUR and non-EUR currencies.
- Does not forward-fill FX beyond limit.

### Step 9 — momentum panel

Acceptance criteria:

- Produces monthly and quarterly panels.
- Momentum calculations match manually checked examples.
- No-lookahead tests pass.

### Step 10 — backtest engine

Acceptance criteria:

- Runs all combinations:
  - top N ∈ {3, 5, 10}
  - frequency ∈ {monthly, quarterly}
  - lookback ∈ {3m, 6m, 9m, 12m, 12-1m}
  - weighting ∈ {equal, positive-momentum-proportional}
  - costs ∈ {0, 10, 25, 50, 100 bps}
- Writes trades and summary tables.
- Unit tests verify accounting.

### Step 11 — reports

Acceptance criteria:

- Markdown reports are generated.
- Reports include explicit limitations.
- Reports include enough numbers to decide whether Stage 2 is worth executing.

---

## 13. Reproducibility requirements

Every run must record:

```text
git_commit_hash
config_file_path
config_sha256
run_started_at_utc
run_finished_at_utc
python_version
package_versions
source_manifest_ids
```

Store in:

```text
metadata/run_logs/{run_id}.json
```

All gold outputs must include `run_id`.

---

## 14. Definition of done

Stage 1 is done when:

1. `make stage1` completes from a clean checkout after placing required manual raw files in the expected directories.
2. All tests pass.
3. Data-quality report exists.
4. Backtest summary exists.
5. At least 250 mapped securities have usable price histories.
6. Monthly and quarterly backtests run for top 3, 5, and 10.
7. The report clearly states that Stage 1 is a free prototype with survivorship-bias and corporate-action limitations.

---

## 15. Known limitations to preserve in all reports

The developer must not hide these limitations.

```text
1. Stage 1 uses a current tradability proxy, not a historical point-in-time Scalable universe.
2. Stage 1 does not reliably include delisted securities.
3. Stooq adjustment status is not treated as institutional-quality total-return data.
4. Identifier mapping is incomplete and partly manual.
5. Results are useful for engineering and signal intuition, not final allocation decisions.
```

---

## 16. Suggested first milestone scope

To avoid over-engineering, implement a limited first milestone:

```text
Universe:
    250-500 large liquid stocks mapped between Xetra/Stooq manually or semi-automatically

Price history:
    daily Stooq data from 2005 onward if available

Backtests:
    equal-weight top 3/5/10
    monthly and quarterly
    6m, 12m, and 12-1m momentum
    25 bps one-way transaction cost
```

After this milestone works, expand to all Stage 1 variants.
