# Multi-Strategy Value-Momentum Allocation Replication

Implements the plan in `value_momentum_paper_replication_plan.md` using:
- `105868 - MSCI World Value Index - FULL - 1998-12-31 - 2026-02-06 - Daily.xlsx`
- `703755 - MSCI World Momentum Index - FULL - 1997-01-31 - 2026-02-06 - Daily.xlsx`

Paper reference:
- https://www.spglobal.com/content/dam/spglobal/mi/en/documents/general/S-P-Global-Market-Intelligence-Value-Momentum-January-2019.pdf

## Run

From repo root:

```bash
python -m analyses.risk_weighted_factor_allocation.replicate_value_momentum \
  --base-dir analyses/risk_weighted_factor_allocation \
  --output-dir outputs \
  --cost-bps 0
```

## What it does

- Parses MSCI Excel files with metadata headers and extracts Date + index level.
- Immediately samples index levels to month-end levels (last available daily observation in each month).
- Computes monthly returns from sampled monthly levels.
- Evaluates two dynamic strategy families with shared optimization/reporting infrastructure:
  - `rw` (paper-style risk-weighted allocation)
  - `factor_momentum` (winner-takes-all factor momentum timing)
- Builds comparison strategies:
  - Momentum-only
  - Value-only
  - EW 50/50
  - RW baseline (`L=6`, `target_vol=2% monthly`, no leverage)
  - RW OOS-best (walk-forward stitched)
  - RW full-sample-best (no CV, in-sample optimization)
  - Factor-momentum fixed windows: `fm_l1`, `fm_l3`, `fm_l6`, `fm_l12`
  - Factor-momentum OOS-best (walk-forward stitched)
  - Factor-momentum full-sample-best (no CV)
- Runs walk-forward CV over parameter grids:
  - `rw`: `L in {3,6,9,12}`, `target_vol_monthly in [0.5%, 8.0%]` monthly, 0.25% step
  - `factor_momentum`: `L in {1,3,6,12}`
- Applies transaction-cost model with default `0 bps`, plus sensitivity (`5`, `10` bps).
- Uses paper-faithful RW volatility signal:
  - \(\sigma^{obs}_m = \text{stdev}(r_{mom,m-L}, \ldots, r_{mom,m-1})\)
  - one-month lag before applying month `m` weights
- Uses factor-momentum timing signal:
  - lagged trailing \(K\)-month cumulative return for Value and Momentum
  - winner-takes-all allocation (Momentum, Value, or 50/50 on ties)
  - TODO notes in code for future alternatives (linear tilt, persistence filter)

## Outputs

Generated under `analyses/risk_weighted_factor_allocation/outputs`:
- Core tables:
  - `metrics_common_sample.csv`
  - `selected_hyperparameters.csv`
  - `walkforward_param_summary.csv` (all hyperparameters, both strategy families)
  - `walkforward_fold_scores.csv` (all hyperparameters for every CV fold, both families)
  - `fullsample_param_summary.csv` (all hyperparameters over full history, both families)
  - `rw_baseline_detail.csv`
  - `rw_fullsample_best_detail.csv`
  - `rw_oos_best_series.csv`
  - `fm_fullsample_best_detail.csv`
  - `fm_oos_best_series.csv`
  - `transaction_cost_sensitivity.csv`
- Plots:
  - cumulative wealth + drawdown
  - rolling metrics
  - momentum allocation overlays (RW and factor-momentum optimized variants)
  - per-family weights/turnover
  - RW + factor-momentum parameter surfaces
  - RW + factor-momentum winner stability
- Summary report: `summary.md`

## Faithfulness to paper (brief)

Paper-faithful core:
- \(w_{mom,m} = \min(\sigma_{target} / \sigma^{obs}_{mom,m}, 1)\)
- lagged signal usage (no lookahead)
- baseline (`L=6`, target vol `2%`)

Main deviation:
- Uses long-only MSCI index proxies instead of the paper's exact factor portfolios.
