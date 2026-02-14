# Plan: Predict AQR Factor Returns Using Open Asset Pricing (OAPD) Predictors — 12-Month Horizon

## Goal
Build a research + implementation workflow to **forecast 12-month-ahead AQR factor returns** using **Open Asset Pricing Data (Chen & Zimmermann) predictor series** as inputs.

The intent is to **start with very simple, transparent models** to identify which OAPD predictors contain information about future AQR factor performance, and only then move to more complex / RAAD010-inspired approaches.

---

## Implementation Status
- [x] Phase 0 implemented in `analyses/aqr_oapd_forecasting.py` (dataset builder + baseline models + metrics output).
- [x] Phase 1 implemented in `analyses/aqr_oapd_forecasting.py` (walk-forward univariate screening, ranking, stability diagnostics).
- [x] Phase 2 implemented in `analyses/aqr_oapd_forecasting.py` (Top-K OLS, Ridge, Elastic Net with time-aware validation split).
- [x] Phase 3 implemented in `analyses/aqr_oapd_forecasting.py` (PCA regression + PLS with walk-forward evaluation).
- [x] Phase 4 implemented in `analyses/aqr_oapd_forecasting.py` (binary/vol-scaled timing backtests + benchmark comparison).

---

## Scope & Constraints

### In-scope (data covered by current fetchers)
- **Targets (y): AQR factor returns** from `data_fetchers/aqr.py` → `factor_returns`.
  - Example factor sets: `qmj_factors`, `vme_factors`.
- **Predictors (X): OAPD predictor long-short returns** from `data_fetchers/open_asset_pricing.py` → `factor_returns`.
  - Factor set: `oapd::predictor_ls` (monthly).
- **Metadata / documentation for OAPD predictors** from `data_fetchers/open_asset_pricing.py` → `characteristic_metadata` (`oapd_signals`).
- **Optional benchmarks** (for evaluation only) from existing fetchers:
  - Ken French factors / RF (`data_fetchers/ken_french.py`)
  - Any other already-ingested factor series in `factor_returns` (for comparison).

### Out-of-scope for the core plan (mention as future extensions only)
- Stock-level OAPD signed signals (very large) and any predictor construction from raw CRSP/Compustat.
- IBES/analyst data, Compustat fundamentals, CRSP delistings, options-implied data, etc.

---

## Current Data Layout (DB)
We assume data is already ingested into the canonical tables:

- `factor_returns` (monthly decimals)
  - AQR targets: `source='aqr'`, `frequency='M'`, `factor_set in ('qmj_factors','vme_factors',...)`
  - OAPD predictors: `source='open_asset_pricing'`, `frequency='M'`, `factor_set='oapd::predictor_ls'`
- `characteristic_metadata`
  - `source='open_asset_pricing'`, `characteristic_set='oapd_signals'`

If missing, ingestion is:
- `python -m data_fetchers.aqr factors`
- `python -m data_fetchers.open_asset_pricing factors`
- `python -m data_fetchers.open_asset_pricing metadata`

---

## Prediction Target Definition (12-Month Horizon)

### 1) Monthly timing index (t)
Let `t` denote **month-end timestamps** (consistent with `factor_returns.date`).

### 2) Target return construction
For each AQR factor series \( r^{AQR}_{t} \) (monthly decimal return), define the **12-month-ahead cumulative return**:

\[
y_{t}^{(12)} = \prod_{k=1}^{12}(1 + r^{AQR}_{t+k}) - 1
\]

This means the predictor information available at **end of month t** is used to forecast the **realized return over months t+1 … t+12**.

### 3) Overlapping vs. non-overlapping targets (two evaluation modes)
Because \( y_{t}^{(12)} \) overlaps across months, we should evaluate in two parallel ways:

- **Overlapping monthly forecasts (primary)**: produce a forecast each month; evaluate with HAC-aware methods / block bootstrap.
- **Non-overlapping annual forecasts (robustness)**: evaluate only every 12th month (e.g., use December t only), eliminating overlap at the cost of fewer samples.

The plan below supports both without changing the data pipeline.

---

## Predictor Set (OAPD) and Feature Engineering

### 1) Raw predictor inputs
Base predictor universe:
- \( x_{j,t} = r^{OAPD}_{j,t} \) for each OAPD predictor long-short series \( j \)
- from `factor_returns` where `source='open_asset_pricing'` and `factor_set='oapd::predictor_ls'`

### 2) Simple time-series transforms (start small; add complexity only if needed)
For each predictor series \( r^{OAPD}_{j,t} \), define features available at time t:

1. **Level / last month return**
   - \( X^{(1)}_{j,t} = r^{OAPD}_{j,t} \)
2. **Short lag stack (autoregressive information)**
   - \( X^{(2)}_{j,t} = [r_{j,t}, r_{j,t-1}, r_{j,t-2}] \) (keep tiny initially)
3. **12-month trailing momentum of predictor returns**
   - \( X^{(3)}_{j,t} = \prod_{k=0}^{11}(1 + r_{j,t-k}) - 1 \)
4. **Trailing volatility (scale proxy)**
   - \( X^{(4)}_{j,t} = \mathrm{stdev}(r_{j,t-11:t}) \)

Start with (1) only, then add (2)–(4) incrementally and measure marginal gains.

### 3) Standardization and leakage control
All standardization must be **fit on training data only** inside the walk-forward loop:
- For linear models, z-score each feature column using expanding-window mean/std.
- Missing values:
  - Drop predictors with excessive missingness (e.g., >30% missing in the training window).
  - For remaining predictors: impute with 0 **after z-scoring** (equivalent to “missing = average”) or use last-observation-carried-forward if justified.

### 4) Dimensionality notes
OAPD predictors are numerous (~200+). Even simple lag stacks can create hundreds of inputs.
This strongly motivates starting with univariate screens and regularized models.

---

## Modeling Roadmap (Simple → Complex)

## Phase 0 — Build the modeling dataset + baselines (no “alpha” yet)
**Objective:** confirm we can reproduce a clean `(date, y, X)` panel and establish simple benchmark forecasts.

1. **Extract and align series**
   - Pull AQR factor series into wide format: `date × factor`.
   - Pull OAPD predictors into wide format: `date × predictor`.
   - Inner-join on dates; keep a record of coverage gaps per series.

2. **Compute targets**
   - For each AQR factor, compute \( y_{t}^{(12)} \) from future returns.
   - Drop the last 12 months (no future window) and any rows with insufficient history (for lagged features).

3. **Benchmarks**
   - **Mean benchmark:** forecast \( \hat{y}_{t} = \bar{y}_{0:t} \) (expanding mean).
   - **AR(1) benchmark:** forecast using last observed AQR monthly return or last-year return (keep extremely simple).

4. **Metrics**
   - Out-of-sample R² relative to mean benchmark:
     \[
     R^2_{OOS} = 1 - \frac{\sum (y_t - \hat{y}_t)^2}{\sum (y_t - \hat{y}^{mean}_t)^2}
     \]
   - RMSE / MAE, directional accuracy (`sign(y)` vs `sign(ŷ)`), and correlation.

Deliverable: a reproducible dataset builder and a baseline scorecard per AQR factor.

---

## Phase 1 — Univariate screening (which predictors matter at all?)
**Objective:** identify individual OAPD predictors with stable, out-of-sample forecasting power for each AQR factor.

For each AQR target factor \( f \) and each OAPD predictor \( j \):

1. Fit a univariate model in a walk-forward setup:
   - \( y^{(12,f)}_{t} = \alpha_t + \beta_{t} \, x_{j,t} + \epsilon_t \)
2. Generate a one-step-ahead forecast \( \hat{y}_{t}^{(12,f)} \) each month.
3. Record:
   - `R²_OOS` contribution vs benchmark
   - Stability across subperiods (e.g., pre/post 2000, pre/post GFC)
   - Feature direction consistency (sign of β)

**Multiple testing control (practical)**
- Use **out-of-sample selection** rules rather than in-sample t-stats:
  - Example: select top-K predictors by `R²_OOS` in the training window only, then test next period.
- Add a robustness layer via **block bootstrap** on forecast errors (no new dependencies required).

Deliverable: a ranked table of predictors per AQR factor, with stability diagnostics.

---

## Phase 2 — Small multivariate models (still interpretable)
**Objective:** test whether combining a handful of “good” predictors materially improves forecasts.

1. **Top-K OLS**
   - Take top-K predictors from Phase 1 (e.g., K ∈ {5, 10, 20}).
   - Fit OLS in walk-forward mode; monitor instability / multicollinearity.

2. **Ridge regression (recommended first multivariate step)**
   - Uses all predictors, stabilizes coefficients.
   - Tune `alpha` using time-series-aware validation (see “Evaluation Protocol”).

3. **Elastic Net / Lasso (sparse models)**
   - Start with Elastic Net (more stable than pure Lasso under collinearity).
   - Track which predictors get selected repeatedly over time (signal robustness).

Deliverable: model comparison table against baseline and against the best univariate predictor.

---

## Phase 3 — Dimension reduction (RAAD010-inspired, but constrained to our data)
**Objective:** capture broad “predictor regimes” in OAPD and use them to forecast AQR factors.

1. **PCA on OAPD predictor returns**
   - Compute PCs on the predictor return matrix \( X_t \) inside the walk-forward loop.
   - Regress AQR 12m returns on a small number of PCs (e.g., 3–10).
   - Advantages: handles collinearity and reduces noise.

2. **PLS (supervised dimension reduction)**
   - Use PLS regression to extract components most correlated with the target.
   - Keep components small; tune via walk-forward validation.

Deliverable: a “few-factor” predictor representation and forecast performance vs Phase 2.

---

## Phase 4 — Economic evaluation (simple factor timing strategy)
**Objective:** translate forecast skill into an investable timing overlay on AQR factors.

For each AQR factor \( f \):

1. Forecast \( \hat{y}^{(12,f)}_{t} \).
2. Convert to a position signal (simple, avoid overfitting):
   - **Binary timing:** long if forecast > 0, else flat (or short if allowed).
   - **Vol-scaled:** \( w_t = \mathrm{clip}(\hat{y}_t / \hat{\sigma}_t, -w_{max}, w_{max}) \)
3. Realized strategy return:
   - Use the subsequent realized AQR monthly returns and re-balance monthly.
4. Compare to:
   - Buy-and-hold of the AQR factor
   - Naive 12-month momentum on the AQR factor itself (as a baseline)

Deliverable: a timing backtest summary (Sharpe, drawdown, hit rate, turnover proxy).

---

## Evaluation Protocol (Avoiding Lookahead + Leakage)

### 1) Walk-forward training loop
At each month t:
1. Training set = all dates ≤ t (expanding) or trailing window (e.g., last 10 years).
2. Validation set = last `V` months of training (e.g., 60 months) for hyperparameter tuning.
3. Fit preprocessing (standardization, PCA) on training only.
4. Fit model on training (or training+validation after choosing hyperparameters).
5. Predict \( y_{t}^{(12)} \) using features at time t.

### 2) Hyperparameter tuning (time-series aware)
Avoid standard randomized CV shuffles.
Use one of:
- Rolling-origin evaluation within the training window.
- A simple “train/validate split” approach (last 5 years as validation).

### 3) Significance and uncertainty
For overlapping 12m targets, standard errors are autocorrelated.
Prefer robust methods that do not require new deps:
- Block bootstrap of forecast error series (block size ~12–24 months).
- Compare forecast MSE to benchmark via bootstrap distribution.

---

## Implementation Plan in This Repo

### 1) Minimal code artifacts (suggested)
Create a small, reproducible analysis entrypoint that:
- queries `factor_returns` for AQR and OAPD,
- builds the modeling dataset,
- runs Phase 0–2 at minimum,
- writes results to `derived/` as Parquet/CSV, and
- (optionally) outputs plots into `derived/reports/`.

Suggested locations:
- `analyses/aqr_factor_forecasting/` (module-style) OR `notebooks/aqr_factor_forecasting.ipynb` (exploratory).

### 2) Data extraction helpers
Implement helpers to pull wide matrices from `factor_returns`:
- `get_factor_matrix(source, factor_set, factors=None) -> DataFrame(date × factor)`

### 3) Reproducibility
- Fix random seeds for any stochastic steps (Elastic Net solvers, bootstrap).
- Cache intermediate matrices (aligned X/y, feature variants) so iterations are fast.
- Persist “run manifests”: date range, target factor list, predictor universe size, model config hash.

---

## Acceptance Criteria
- A single reproducible pipeline can:
  - build \( y^{(12)} \) for selected AQR factors,
  - build a clean OAPD feature matrix using only data in the DB,
  - run walk-forward forecasting without lookahead,
  - produce a baseline + univariate screen + at least one regularized multivariate model.
- The outputs include:
  - per-factor forecast skill metrics (R²_OOS, RMSE, sign accuracy),
  - a ranked list of OAPD predictors by forecasting contribution,
  - stability diagnostics across subperiods,
  - a simple timing backtest summary (optional but preferred).

---

## Potential Additional Data Sources (Explicitly Not Used in the Core Plan)
These are natural extensions once the core pipeline is stable:
- **Macro + rates:** FRED (inflation, unemployment, industrial production, yield curve), survey expectations.
- **Valuation and long-run predictors:** dividend yield, earnings yield, term spread, credit spread.
- **Firm fundamentals / characteristics:** Compustat-derived profitability/investment; requires proprietary or heavy ETL.
- **Analyst expectations:** IBES (earnings revisions, dispersion) — proprietary.
- **Options / volatility:** VIX, variance risk premium, option-implied skew — often proprietary / specialized.
- **Global coverage:** regional macro + FX hedged returns, local factor definitions.

The plan above intentionally avoids these until we have a strong baseline using only AQR + OAPD predictor data already supported by this repo.
