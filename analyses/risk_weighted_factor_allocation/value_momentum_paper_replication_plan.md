# Ad-hoc analysis plan — Reproducing S&P Global "Value + Momentum" (monthly) with OOS hyperparameter search

**Goal:** Reproduce the paper's risk-weighted (RW) Value-Momentum blend using MSCI World Value and Momentum index data, then run a controlled hyperparameter search to identify settings that maximize out-of-sample realized returns.

**Primary focus (this plan):** Monthly implementation aligned with the paper's mechanism.  
**Extension (end of plan):** Optional daily/hybrid implementations.

---

## 0) Paper reference and faithfulness check

### 0.1 Reference
- S&P Global Market Intelligence (January 2019), "Value + Momentum":
  - https://www.spglobal.com/content/dam/spglobal/mi/en/documents/general/S-P-Global-Market-Intelligence-Value-Momentum-January-2019.pdf

### 0.2 Brief faithfulness review
This plan is faithful to the paper on the core mechanics:
- Dynamic Momentum weight rule: \(w_{mom} = \min(\sigma_{target}/\sigma^{obs}_{mom}, 1)\)
- Rolling volatility signal based on trailing returns and lagged application (no lookahead)
- Comparison against Value-only, Momentum-only, and EW blend
- Paper-aligned baseline values: 6-month lookback and 2% target volatility, plus robustness sweeps

Known non-faithful elements (explicitly documented):
- We are using long-only MSCI index proxies, not the exact long-short factor portfolios used in the paper.
- We default to zero transaction cost for base results, then run cost sensitivity.

---

## 1) Inputs, scope, and assumptions

### 1.1 Data inputs (provided)
- Daily index levels (not daily return series):
  - `105868 - MSCI World Value Index - FULL - 1998-12-31 - 2026-02-06 - Daily.xlsx`
  - `703755 - MSCI World Momentum Index - FULL - 1997-01-31 - 2026-02-06 - Daily.xlsx`

### 1.2 Output series to construct
- Daily returns from levels:
  - `r_val_d[t]`, `r_mom_d[t]`
- Monthly returns:
  - `r_val_m[m]`, `r_mom_m[m]`
- Strategy returns:
  - `r_EW[m]`: equal-weight (50/50, monthly rebalance)
  - `r_RW[m]`: risk-weighted blend

### 1.3 High-level replication target
Implement the paper's risk-weighting rule where Momentum allocation is scaled by observed Momentum volatility and residual allocation goes to Value.

---

## 2) Data preparation and quality checks (daily -> monthly)

### 2.1 Parse and clean index-level files
- Files contain metadata rows before the true header.
- Detect the row where first column equals `Date`; start data from the next row.
- Keep only `Date` and the index level column (`MSCI World Value Index` or `MSCI World Momentum Index`).
- Convert to numeric levels and sort by date.
- Drop duplicate dates (keep last), drop non-numeric rows.

### 2.2 Build daily return series from levels
For each index:
\[
r_{d,t} = \frac{P_t}{P_{t-1}} - 1
\]
- Use simple returns in decimal units.
- Validate scale and sanity (extreme outliers flagged for review).

### 2.3 Align daily series
- Align Value and Momentum daily returns on the intersection of dates.
- Record missing-date counts and dropped observations by source.

### 2.4 Convert daily to monthly returns
For each calendar month `m`, compound daily returns:
\[
r_m = \prod_{t \in m}(1+r_{d,t}) - 1
\]
- Use calendar month-end (`ME`) grouping.
- Drop partial edge months (first/last month with incomplete coverage).
- For current files, expected full-month sample starts in `1999-01` and ends in `2026-01`.

**Deliverables**
- Table of monthly daily-observation counts and dropped edge months
- Summary stats for monthly Value/Momentum returns (mean, vol, skew, kurtosis)
- Monthly correlation matrix

---

## 3) Baseline portfolios to reproduce (monthly)

Construct all strategies side-by-side:
- Momentum-only
- Value-only
- EW 50/50 (monthly rebalance)
- RW (paper baseline)
- RW (optimized)

### 3.1 Standalone indices
- Momentum-only: \(r_{mom,m}\)
- Value-only: \(r_{val,m}\)

### 3.2 Equal-weight blend (EW, monthly rebalance)
\[
r_{EW,m} = 0.5 \cdot r_{mom,m} + 0.5 \cdot r_{val,m}
\]

### 3.3 Risk-weight blend (RW) — paper mechanism
Momentum weight:
\[
w_{mom,m} = \min\left(\frac{\sigma_{target}}{\sigma^{obs}_{mom,m}}, 1\right), \quad
w_{val,m} = 1 - w_{mom,m}
\]
Monthly RW return:
\[
r^{gross}_{RW,m} = w_{mom,m}\, r_{mom,m} + w_{val,m}\, r_{val,m}
\]

Observed Momentum volatility (paper-faithful signal basis):
- Compute from daily Momentum returns over trailing \(L\) months (approx. \(21L\) trading days), annualized by \(\sqrt{252}\).
- Use only data available through end of month \(m-1\), apply weight to month \(m\) return.

### 3.4 Paper-faithful baseline configuration
- Baseline lookback: \(L = 6\) months (approx. 126 trading days)
- Baseline target volatility: \(\sigma_{target} = 2\%\) annualized
- Weight cap at 1.0 (no leverage), residual to Value

### 3.5 Numerical safeguards
- Volatility floor: \(\sigma^{obs}_{mom,m} \leftarrow \max(\sigma^{obs}_{mom,m}, \epsilon)\), e.g. `1e-6`
- Enforce `w_mom` in `[0, 1]`
- Unit consistency: keep both \(\sigma_{target}\) and \(\sigma^{obs}\) in annualized units

---

## 4) Evaluation metrics (monthly)

### 4.1 Core performance metrics
For Momentum-only, Value-only, EW, RW baseline, RW best:
- CAGR
- Annualized volatility
- Sharpe ratio (risk-free assumption explicitly stated)
- Max drawdown
- Calmar ratio

### 4.2 Distribution and path diagnostics
- Return histogram and percentiles
- Worst 1/3/6/12-month periods
- Rolling 12-month return and rolling 36-month Sharpe

### 4.3 Turnover and transaction cost model
Define one-way turnover:
\[
\tau_m = \frac{|w_{mom,m}-w_{mom,m-1}| + |w_{val,m}-w_{val,m-1}|}{2} = |w_{mom,m}-w_{mom,m-1}|
\]

Transaction cost per month:
\[
tc_m = \frac{c_{bps}}{10{,}000}\,\tau_m
\]

Net RW return:
\[
r^{net}_{RW,m} = r^{gross}_{RW,m} - tc_m
\]

Defaults and sensitivity:
- **Default:** `c_bps = 0` (no transaction costs)
- Sensitivity runs: `c_bps in {5, 10}` as robustness checks

**Deliverables**
- Unified chart set (all strategies): cumulative wealth, drawdowns, rolling metrics
- RW weight and turnover time series
- Gross vs net RW performance summary

---

## 5) Hyperparameter search (monthly, OOS)

### 5.1 Hyperparameters
Primary:
1. Lookback \(L \in \{1, 3, 6, 9, 12\}\) months (mapped to `{21, 63, 126, 189, 252}` daily observations)
2. \(\sigma_{target}\) annualized grid: `0.5%` to `7.0%`, step `0.25%` (paper range), with optional extension to `8.0%` if needed

### 5.2 Objective
- Primary: maximize **out-of-sample net CAGR**
- Default optimization run uses `c_bps = 0`
- Secondary reporting: drawdown, vol, Sharpe, turnover

### 5.3 Selection protocol (strict no-lookahead)
Use walk-forward cross-validation:
- Train window: 60 months
- Test window: 12 months
- Step: 12 months

Per fold:
1. Build training-month returns and lagged signals only from data up to each month.
2. Evaluate all \((L, \sigma_{target})\) on train by net CAGR.
3. Select winner on train.
4. Freeze winner, apply to next 12-month test window.
5. Store test returns and selected parameters.

Information boundary requirement:
- For each test month `m`, weight uses volatility estimated with daily data available only through the last trading day of month `m-1`.

**Deliverables**
- Training CAGR heatmap by \((L, \sigma_{target})\)
- Aggregated OOS CAGR heatmap by \((L, \sigma_{target})\)
- Winner-stability chart across folds
- Final selected parameter pair by OOS objective

---

## 6) Robustness checks

### 6.1 Lookback sensitivity
- Hold \(\sigma_{target}\) fixed and compare \(L\) choices

### 6.2 Target-volatility sensitivity
- Hold \(L\) fixed and sweep \(\sigma_{target}\)

### 6.3 Regime analysis
Bucket months by lagged \(\sigma^{obs}_{mom,m}\) quantiles:
- Compare RW vs EW vs standalone components by regime

### 6.4 Stress windows
Define stress periods algorithmically (e.g., top drawdowns in Momentum):
- Compare cumulative return, drawdown, and recovery time

### 6.5 Transaction cost sensitivity
- Recompute key RW results under `c_bps in {0, 5, 10}`
- Identify whether best hyperparameters are stable under costs

### 6.6 Uncertainty estimates
- Bootstrap confidence intervals for RW-EW performance differences (CAGR, Sharpe, max drawdown)
- Prefer block bootstrap at monthly frequency to preserve serial dependence

**Deliverables**
- Regime and stress tables
- Cost-sensitivity table
- CI table for RW vs EW deltas
- Narrative: where RW helps/hurts and how robust results are

---

## 7) Final reporting package

### 7.1 Core comparison table
Rows:
- Momentum-only
- Value-only
- EW 50/50
- RW baseline (`L=6`, `sigma_target=2%`, `c_bps=0`)
- RW optimized (OOS-selected)

Columns:
- CAGR, vol, Sharpe, max drawdown, Calmar
- Mean/median turnover
- Net metrics under `c_bps = 0` (default) and sensitivity columns for `5` and `10` bps

### 7.2 Plots
- Cumulative wealth (log scale recommended), all strategies overlaid
- Drawdown curves, all strategies overlaid
- Rolling vol and rolling Sharpe
- RW weights and turnover
- OOS heatmap and winner stability

### 7.3 Reproducibility notes
Document:
- parsing method for MSCI files with metadata rows
- index-level-to-return conversion
- month-end grouping and dropped edge months
- no-lookahead signal lagging convention
- volatility unit conventions
- transaction-cost assumptions (default and sensitivity)

---

## 8) Implementation notes

### 8.1 Start-of-sample handling
- RW weights undefined until enough trailing daily data exists
- Start RW performance only after full lookback is available

### 8.2 Numerical stability
- Apply volatility floor
- Ensure no NaNs in aligned monthly series

### 8.3 Validation checkpoints
- Confirm daily return reconstruction from levels matches direct level compounding
- Confirm RW weights at month `m` do not use month `m` daily returns
- Confirm gross and net return pipelines are both tested

---

# Appendix — Optional daily/hybrid extension

Once monthly replication is complete, test daily/hybrid variants (not directly paper-comparable):
- Daily volatility signal with monthly rebalancing
- Fully daily RW with daily updates and stronger turnover/cost controls

For daily variants:
- Convert monthly \(\sigma_{target}\) to daily only if needed, or keep annualized units consistently
- Report explicit turnover and transaction-cost scenarios

