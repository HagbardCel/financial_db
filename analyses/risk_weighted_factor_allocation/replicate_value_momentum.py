from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


VALUE_FILE = "105868 - MSCI World Value Index - FULL - 1998-12-31 - 2026-02-06 - Daily.xlsx"
MOMENTUM_FILE = "703755 - MSCI World Momentum Index - FULL - 1997-01-31 - 2026-02-06 - Daily.xlsx"
SHEET_NAME = "Performance Data"
DEFAULT_OUTPUT_DIR = "outputs"
PAPER_URL = "https://www.spglobal.com/content/dam/spglobal/mi/en/documents/general/S-P-Global-Market-Intelligence-Value-Momentum-January-2019.pdf"


@dataclass(frozen=True)
class RWParams:
    lookback_months: int
    target_vol_monthly: float


@dataclass(frozen=True)
class FMParams:
    lookback_months: int


@dataclass(frozen=True)
class StrategyFamilyConfig:
    name: str
    params_grid: Sequence[object]
    build_detail_fn: Callable[[pd.Series, pd.Series, object, float], pd.DataFrame]
    param_to_record_fn: Callable[[object], Dict[str, object]]
    baseline_param: Optional[object] = None


@dataclass
class StrategyFamilyEvaluation:
    name: str
    cache: Dict[object, pd.DataFrame]
    fold_scores: pd.DataFrame
    winners: pd.DataFrame
    param_summary: pd.DataFrame
    fullsample_summary: pd.DataFrame
    oos_stitched: pd.DataFrame
    oos_best_param: object
    oos_best_detail: pd.DataFrame
    fullsample_best_param: object
    fullsample_best_detail: pd.DataFrame
    baseline_detail: Optional[pd.DataFrame]


def load_msci_levels(path: Path) -> pd.Series:
    raw = pd.read_excel(path, sheet_name=SHEET_NAME, header=None)
    date_rows = raw.index[raw.iloc[:, 0].astype(str).str.strip().eq("Date")]
    if len(date_rows) == 0:
        raise ValueError(f"Could not find 'Date' row in {path.name}")

    start = int(date_rows[0]) + 1
    data = raw.iloc[start:, [0, 1]].copy()
    data.columns = ["date", "level"]
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["level"] = pd.to_numeric(data["level"], errors="coerce")
    data = data.dropna(subset=["date", "level"]).sort_values("date")
    data = data.drop_duplicates(subset=["date"], keep="last")
    return data.set_index("date")["level"].rename(path.stem)


def sample_monthly_levels(levels: pd.Series) -> Tuple[pd.Series, List[pd.Timestamp]]:
    monthly = levels.resample("ME").last().dropna()
    dropped: List[pd.Timestamp] = []

    last_daily = levels.index.max()
    last_month_end = last_daily.to_period("M").to_timestamp("M")
    if last_daily < last_month_end and last_month_end in monthly.index:
        monthly = monthly.drop(last_month_end)
        dropped.append(last_month_end)

    return monthly, dropped


def metrics(returns: pd.Series, risk_free_annual: float = 0.0) -> Dict[str, float]:
    clean = returns.dropna()
    if clean.empty:
        return {
            "months": 0,
            "cagr": np.nan,
            "annualized_vol": np.nan,
            "sharpe": np.nan,
            "max_drawdown": np.nan,
            "calmar": np.nan,
        }

    periods_per_year = 12.0
    years = clean.shape[0] / periods_per_year
    wealth = (1.0 + clean).cumprod()
    cagr = wealth.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan

    vol = clean.std(ddof=0) * np.sqrt(periods_per_year)
    rf_monthly = (1.0 + risk_free_annual) ** (1.0 / periods_per_year) - 1.0
    excess = clean - rf_monthly
    denom = clean.std(ddof=0)
    sharpe = np.nan if denom == 0 else excess.mean() / denom * np.sqrt(periods_per_year)

    peak = wealth.cummax()
    drawdown = wealth / peak - 1.0
    mdd = float(drawdown.min())
    calmar = np.nan if mdd >= 0 else cagr / abs(mdd)

    return {
        "months": int(clean.shape[0]),
        "cagr": float(cagr),
        "annualized_vol": float(vol),
        "sharpe": float(sharpe),
        "max_drawdown": mdd,
        "calmar": float(calmar),
    }


def rolling_sharpe(returns: pd.Series, window: int = 36) -> pd.Series:
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std(ddof=0)
    out = mean / std * np.sqrt(12.0)
    return out.replace([np.inf, -np.inf], np.nan)


def rolling_vol(returns: pd.Series, window: int = 12) -> pd.Series:
    return returns.rolling(window).std(ddof=0) * np.sqrt(12.0)


def trailing_momentum(returns: pd.Series, window: int) -> pd.Series:
    return (1.0 + returns).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1.0


def build_rw_strategy(
    monthly_value: pd.Series,
    monthly_momentum: pd.Series,
    params: RWParams,
    transaction_cost_bps: float = 0.0,
    vol_floor: float = 1e-6,
) -> pd.DataFrame:
    sigma_obs = (
        monthly_momentum.rolling(params.lookback_months, min_periods=params.lookback_months)
        .std(ddof=1)
        .shift(1)
    )
    sigma_obs = sigma_obs.clip(lower=vol_floor)

    w_mom = (params.target_vol_monthly / sigma_obs).clip(lower=0.0, upper=1.0)
    w_val = 1.0 - w_mom
    gross = w_mom * monthly_momentum + w_val * monthly_value
    turnover = w_mom.diff().abs().fillna(0.0)
    tc = transaction_cost_bps / 10000.0 * turnover
    net = gross - tc

    return pd.DataFrame(
        {
            "w_mom": w_mom,
            "w_val": w_val,
            "turnover": turnover,
            "tc": tc,
            "gross": gross,
            "net": net,
            "sigma_obs_monthly": sigma_obs,
        }
    )


def build_factor_momentum_strategy(
    monthly_value: pd.Series,
    monthly_momentum: pd.Series,
    params: FMParams,
    transaction_cost_bps: float = 0.0,
) -> pd.DataFrame:
    k = params.lookback_months
    sig_val = (1.0 + monthly_value).rolling(k, min_periods=k).apply(np.prod, raw=True).shift(1) - 1.0
    sig_mom = (1.0 + monthly_momentum).rolling(k, min_periods=k).apply(np.prod, raw=True).shift(1) - 1.0

    w_mom = pd.Series(index=monthly_value.index, dtype=float)
    valid = sig_val.notna() & sig_mom.notna()

    # TODO: evaluate a linear-tilt mapping from signal spread to weights.
    # TODO: evaluate a persistence filter before switching allocations.
    w_mom.loc[valid] = np.select(
        [sig_mom.loc[valid] > sig_val.loc[valid], sig_mom.loc[valid] < sig_val.loc[valid]],
        [1.0, 0.0],
        default=0.5,
    )
    w_val = 1.0 - w_mom

    gross = w_mom * monthly_momentum + w_val * monthly_value
    turnover = w_mom.diff().abs().fillna(0.0)
    tc = transaction_cost_bps / 10000.0 * turnover
    net = gross - tc

    return pd.DataFrame(
        {
            "w_mom": w_mom,
            "w_val": w_val,
            "turnover": turnover,
            "tc": tc,
            "gross": gross,
            "net": net,
            "sig_val": sig_val,
            "sig_mom": sig_mom,
        }
    )


def rw_param_record(param: RWParams) -> Dict[str, object]:
    return {
        "lookback_months": param.lookback_months,
        "target_vol_monthly": param.target_vol_monthly,
        "param_label": f"L{param.lookback_months}_TV{param.target_vol_monthly:.4f}",
    }


def fm_param_record(param: FMParams) -> Dict[str, object]:
    return {
        "lookback_months": param.lookback_months,
        "target_vol_monthly": np.nan,
        "param_label": f"L{param.lookback_months}",
    }


def walk_forward_folds(
    index: pd.DatetimeIndex,
    train_months: int,
    test_months: int,
    step_months: int,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    folds: List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    start = train_months
    while start + test_months <= len(index):
        folds.append((index[start - train_months], index[start - 1], index[start], index[start + test_months - 1]))
        start += step_months
    return folds


def evaluate_strategy_family(
    config: StrategyFamilyConfig,
    monthly_value: pd.Series,
    monthly_momentum: pd.Series,
    folds: Sequence[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    transaction_cost_bps: float,
) -> StrategyFamilyEvaluation:
    cache: Dict[object, pd.DataFrame] = {}
    key_to_param: Dict[str, object] = {}
    param_meta: Dict[str, Dict[str, object]] = {}

    for param in config.params_grid:
        detail = config.build_detail_fn(monthly_value, monthly_momentum, param, transaction_cost_bps)
        if not {"net", "gross", "turnover", "w_mom"}.issubset(detail.columns):
            raise RuntimeError(f"Strategy '{config.name}' detail output missing required columns.")
        cache[param] = detail

        rec = config.param_to_record_fn(param)
        key = f"{config.name}|{rec['param_label']}"
        key_to_param[key] = param
        param_meta[key] = rec

    fold_records: List[Dict[str, object]] = []
    winner_records: List[Dict[str, object]] = []
    stitched = pd.DataFrame(
        index=monthly_value.index,
        columns=["net", "gross", "turnover", "w_mom"],
        dtype=float,
    )

    for fold_id, (train_start, train_end, test_start, test_end) in enumerate(folds, start=1):
        train_mask = (monthly_value.index >= train_start) & (monthly_value.index <= train_end)
        test_mask = (monthly_value.index >= test_start) & (monthly_value.index <= test_end)

        fold_scores: List[Tuple[str, float, float]] = []
        for key, param in key_to_param.items():
            detail = cache[param]
            train_cagr = metrics(detail.loc[train_mask, "net"])["cagr"]
            test_cagr = metrics(detail.loc[test_mask, "net"])["cagr"]
            fold_scores.append((key, train_cagr, test_cagr))

            fold_records.append(
                {
                    "strategy_family": config.name,
                    "param_key": key,
                    "fold": fold_id,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "lookback_months": param_meta[key]["lookback_months"],
                    "target_vol_monthly": param_meta[key]["target_vol_monthly"],
                    "train_cagr": train_cagr,
                    "test_cagr": test_cagr,
                }
            )

        fold_scores.sort(key=lambda x: np.nan_to_num(x[1], nan=-1e9), reverse=True)
        best_key, best_train_cagr, best_test_cagr = fold_scores[0]
        best_param = key_to_param[best_key]
        best_detail = cache[best_param]

        winner_records.append(
            {
                "strategy_family": config.name,
                "fold": fold_id,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "selected_param_key": best_key,
                "selected_L": param_meta[best_key]["lookback_months"],
                "selected_target_vol_monthly": param_meta[best_key]["target_vol_monthly"],
                "selected_train_cagr": best_train_cagr,
                "selected_test_cagr": best_test_cagr,
            }
        )

        stitched.loc[test_mask, "net"] = best_detail.loc[test_mask, "net"]
        stitched.loc[test_mask, "gross"] = best_detail.loc[test_mask, "gross"]
        stitched.loc[test_mask, "turnover"] = best_detail.loc[test_mask, "turnover"]
        stitched.loc[test_mask, "w_mom"] = best_detail.loc[test_mask, "w_mom"]

    fold_df = pd.DataFrame(fold_records)
    winners_df = pd.DataFrame(winner_records)

    param_summary = (
        fold_df.groupby(
            ["strategy_family", "param_key", "lookback_months", "target_vol_monthly"],
            as_index=False,
            dropna=False,
        )
        .agg(
            mean_train_cagr=("train_cagr", "mean"),
            mean_test_cagr=("test_cagr", "mean"),
            median_test_cagr=("test_cagr", "median"),
            n_folds=("fold", "count"),
        )
        .sort_values("mean_test_cagr", ascending=False)
    )

    common_eval_index = monthly_value.index
    for detail in cache.values():
        common_eval_index = common_eval_index.intersection(detail["net"].dropna().index)
    if common_eval_index.empty:
        raise RuntimeError(f"No common full-sample index for strategy family '{config.name}'.")

    fullsample_rows: List[Dict[str, object]] = []
    for key, param in key_to_param.items():
        detail = cache[param]
        returns = detail.loc[common_eval_index, "net"]
        mm = metrics(returns)
        fullsample_rows.append(
            {
                "strategy_family": config.name,
                "param_key": key,
                "lookback_months": param_meta[key]["lookback_months"],
                "target_vol_monthly": param_meta[key]["target_vol_monthly"],
                "fullsample_cagr": mm["cagr"],
                "fullsample_annualized_vol": mm["annualized_vol"],
                "fullsample_sharpe": mm["sharpe"],
                "fullsample_max_drawdown": mm["max_drawdown"],
                "fullsample_calmar": mm["calmar"],
                "eval_months": int(returns.dropna().shape[0]),
            }
        )

    fullsample_summary = pd.DataFrame(fullsample_rows).sort_values("fullsample_cagr", ascending=False)

    oos_best_key = str(param_summary.iloc[0]["param_key"])
    oos_best_param = key_to_param[oos_best_key]
    full_best_key = str(fullsample_summary.iloc[0]["param_key"])
    full_best_param = key_to_param[full_best_key]

    baseline_detail = None
    if config.baseline_param is not None:
        baseline_detail = config.build_detail_fn(
            monthly_value,
            monthly_momentum,
            config.baseline_param,
            transaction_cost_bps,
        )

    return StrategyFamilyEvaluation(
        name=config.name,
        cache=cache,
        fold_scores=fold_df,
        winners=winners_df,
        param_summary=param_summary,
        fullsample_summary=fullsample_summary,
        oos_stitched=stitched,
        oos_best_param=oos_best_param,
        oos_best_detail=cache[oos_best_param],
        fullsample_best_param=full_best_param,
        fullsample_best_detail=cache[full_best_param],
        baseline_detail=baseline_detail,
    )


def _safe_filename(value: str) -> str:
    return value.replace(" ", "_").replace("%", "pct").replace(".", "p")


def _markdown_table(df: pd.DataFrame, floatfmt: str = ".6f") -> str:
    if df.empty:
        return "(no data)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        values = []
        for c in cols:
            v = row[c]
            if isinstance(v, float) and np.isfinite(v):
                values.append(format(v, floatfmt))
            elif pd.isna(v):
                values.append("")
            else:
                values.append(str(v))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def plot_cumulative_and_drawdown(
    strategies: pd.DataFrame,
    allocations: pd.DataFrame,
    outdir: Path,
) -> None:
    wealth = (1.0 + strategies).cumprod()
    drawdowns = wealth.div(wealth.cummax()).sub(1.0)
    alloc = allocations.reindex(wealth.index)
    value_input = strategies["value_only"] if "value_only" in strategies.columns else None
    momentum_input = strategies["momentum_only"] if "momentum_only" in strategies.columns else None

    fig, axes = plt.subplots(5, 1, figsize=(14, 22), sharex=True)
    for col in wealth.columns:
        axes[0].plot(wealth.index, wealth[col], label=col)
    axes[0].set_yscale("log")
    axes[0].set_title("Cumulative Wealth (log scale)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    for col in drawdowns.columns:
        axes[1].plot(drawdowns.index, drawdowns[col], label=col)
    axes[1].set_title("Drawdowns")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    for col in alloc.columns:
        axes[2].plot(alloc.index, alloc[col], label=col)
    axes[2].set_ylim(-0.05, 1.05)
    axes[2].set_title("Momentum Allocation Over Time")
    axes[2].set_ylabel("Weight")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best")

    if value_input is not None and momentum_input is not None:
        for w in [1, 3, 6, 12]:
            axes[3].plot(
                strategies.index,
                trailing_momentum(value_input, window=w),
                label=f"value_{w}m",
            )
            axes[3].plot(
                strategies.index,
                trailing_momentum(momentum_input, window=w),
                label=f"momentum_{w}m",
            )
        axes[3].set_title("Trailing Momentum - Input Portfolios")
        axes[3].grid(True, alpha=0.3)
        axes[3].legend(loc="best", ncol=2)
    else:
        axes[3].axis("off")
        axes[3].text(0.5, 0.5, "Input portfolios not present in strategies panel", ha="center", va="center")

    if momentum_input is not None:
        for w in [3, 6, 12]:
            axes[4].plot(
                strategies.index,
                rolling_vol(momentum_input, window=w),
                label=f"momentum_vol_{w}m",
            )
        axes[4].set_title("Trailing Annualized Volatility - Momentum ETF")
        axes[4].grid(True, alpha=0.3)
        axes[4].legend(loc="best")
    else:
        axes[4].axis("off")
        axes[4].text(0.5, 0.5, "Momentum input portfolio not present in strategies panel", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(outdir / "cumulative_and_drawdowns.png", dpi=150)
    plt.close(fig)


def plot_rolling_metrics(strategies: pd.DataFrame, outdir: Path) -> None:
    rolling_vol_df = pd.DataFrame({c: rolling_vol(strategies[c], window=12) for c in strategies.columns})
    rolling_sharpe_df = pd.DataFrame({c: rolling_sharpe(strategies[c], window=36) for c in strategies.columns})

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for col in rolling_vol_df.columns:
        axes[0].plot(rolling_vol_df.index, rolling_vol_df[col], label=col)
    axes[0].set_title("Rolling 12M Annualized Volatility")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    for col in rolling_sharpe_df.columns:
        axes[1].plot(rolling_sharpe_df.index, rolling_sharpe_df[col], label=col)
    axes[1].set_title("Rolling 36M Sharpe")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    fig.tight_layout()
    fig.savefig(outdir / "rolling_metrics.png", dpi=150)
    plt.close(fig)


def plot_weights_turnover(detail: pd.DataFrame, outdir: Path, name: str) -> None:
    w_mom = detail["w_mom"]
    w_val = detail["w_val"] if "w_val" in detail.columns else 1.0 - w_mom

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    axes[0].plot(detail.index, w_mom, label="w_mom")
    axes[0].plot(detail.index, w_val, label="w_val")
    axes[0].set_title(f"Weights ({name})")
    axes[0].set_ylim(-0.05, 1.05)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(detail.index, detail["turnover"], color="tab:orange", label="turnover")
    axes[1].set_title(f"Turnover ({name})")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    fig.tight_layout()
    fig.savefig(outdir / f"weights_turnover_{_safe_filename(name)}.png", dpi=150)
    plt.close(fig)


def plot_param_surface(
    summary_df: pd.DataFrame,
    value_col: str,
    title: str,
    outpath: Path,
) -> None:
    d = summary_df.copy()
    d = d.sort_values(["lookback_months"])
    has_target = d["target_vol_monthly"].notna().any()

    if has_target:
        pivot = d.pivot(index="lookback_months", columns="target_vol_monthly", values=value_col)
        plt.figure(figsize=(10, 6))
        sns.heatmap(pivot, annot=True, fmt=".2%", cmap="viridis")
        plt.ylabel("Lookback (months)")
        plt.xlabel("Target vol (monthly)")
    else:
        plt.figure(figsize=(10, 6))
        plt.plot(d["lookback_months"], d[value_col], marker="o")
        plt.grid(True, alpha=0.3)
        plt.ylabel(value_col)
        plt.xlabel("Lookback (months)")

    plt.title(title)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def plot_winner_stability(winners: pd.DataFrame, outpath: Path, title_prefix: str) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    axes[0].step(winners["test_start"], winners["selected_L"], where="post")
    axes[0].set_title(f"{title_prefix} - Selected Lookback by Fold")
    axes[0].grid(True, alpha=0.3)

    if winners["selected_target_vol_monthly"].notna().any():
        axes[1].step(winners["test_start"], winners["selected_target_vol_monthly"], where="post")
        axes[1].set_title(f"{title_prefix} - Selected Target Vol (monthly)")
    else:
        axes[1].axis("off")
        axes[1].text(0.5, 0.5, "No target_vol hyperparameter", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def generate_summary_markdown(
    outdir: Path,
    data_quality: pd.DataFrame,
    metrics_table: pd.DataFrame,
    selected_params: pd.DataFrame,
    walkforward_param_summary: pd.DataFrame,
    fullsample_param_summary: pd.DataFrame,
    walkforward_winners: pd.DataFrame,
    transaction_cost_sensitivity: pd.DataFrame,
    notes: Iterable[str],
) -> None:
    with (outdir / "summary.md").open("w", encoding="utf-8") as f:
        f.write("# Value-Momentum Multi-Strategy Replication Summary\n\n")
        f.write(f"Paper reference: {PAPER_URL}\n\n")

        f.write("## Notes\n")
        for note in notes:
            f.write(f"- {note}\n")
        f.write("\n")

        f.write("## Data Quality\n")
        f.write(_markdown_table(data_quality))
        f.write("\n\n")

        f.write("## Selected Hyperparameters\n")
        f.write(_markdown_table(selected_params))
        f.write("\n\n")

        f.write("## Strategy Metrics (Common Sample)\n")
        f.write(_markdown_table(metrics_table))
        f.write("\n\n")

        f.write("## Walk-Forward Parameter Summary (All Hyperparameters)\n")
        f.write(_markdown_table(walkforward_param_summary))
        f.write("\n\n")

        f.write("## Full-Sample Parameter Summary (All Hyperparameters)\n")
        f.write(_markdown_table(fullsample_param_summary))
        f.write("\n\n")

        f.write("## Walk-Forward Fold Winners\n")
        f.write(_markdown_table(walkforward_winners))
        f.write("\n\n")

        f.write("## Transaction Cost Sensitivity\n")
        f.write(_markdown_table(transaction_cost_sensitivity))
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monthly-only multi-strategy replication: RW + factor-momentum allocation"
    )
    parser.add_argument("--base-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=0.0)
    parser.add_argument("--train-months", type=int, default=60)
    parser.add_argument("--test-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=12)
    args = parser.parse_args()

    base_dir = args.base_dir
    outdir = base_dir / args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    value_levels_daily = load_msci_levels(base_dir / VALUE_FILE)
    momentum_levels_daily = load_msci_levels(base_dir / MOMENTUM_FILE)
    if not value_levels_daily.index.is_monotonic_increasing or value_levels_daily.index.has_duplicates:
        raise RuntimeError("Value daily levels index must be sorted and unique.")
    if not momentum_levels_daily.index.is_monotonic_increasing or momentum_levels_daily.index.has_duplicates:
        raise RuntimeError("Momentum daily levels index must be sorted and unique.")

    value_levels_monthly, value_dropped_months = sample_monthly_levels(value_levels_daily)
    momentum_levels_monthly, momentum_dropped_months = sample_monthly_levels(momentum_levels_daily)

    common_months = value_levels_monthly.index.intersection(momentum_levels_monthly.index).sort_values()
    monthly_levels = pd.concat(
        [
            value_levels_monthly.reindex(common_months).rename("value_level"),
            momentum_levels_monthly.reindex(common_months).rename("momentum_level"),
        ],
        axis=1,
    )
    if monthly_levels.isna().any().any():
        raise RuntimeError("Unexpected NaN after aligning sampled monthly levels.")

    monthly = monthly_levels.pct_change().dropna()
    monthly.columns = ["value", "momentum"]
    if monthly.empty:
        raise RuntimeError("No monthly returns available after sampling.")

    ew = (0.5 * monthly["value"] + 0.5 * monthly["momentum"]).rename("ew_50_50")
    folds = walk_forward_folds(
        index=monthly.index,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
    )
    if not folds:
        raise RuntimeError("Walk-forward produced no folds. Adjust train/test/step.")

    rw_baseline_param = RWParams(lookback_months=6, target_vol_monthly=0.02)
    rw_grid = [
        RWParams(lookback_months=l, target_vol_monthly=t)
        for l, t in itertools.product([3, 6, 9, 12], [round(x, 4) for x in np.arange(0.005, 0.0801, 0.0025)])
    ]
    fm_grid = [FMParams(lookback_months=l) for l in [1, 3, 6, 12]]

    rw_config = StrategyFamilyConfig(
        name="rw",
        params_grid=rw_grid,
        build_detail_fn=lambda v, m, p, c: build_rw_strategy(v, m, p, c),
        param_to_record_fn=rw_param_record,
        baseline_param=rw_baseline_param,
    )
    fm_config = StrategyFamilyConfig(
        name="factor_momentum",
        params_grid=fm_grid,
        build_detail_fn=lambda v, m, p, c: build_factor_momentum_strategy(v, m, p, c),
        param_to_record_fn=fm_param_record,
        baseline_param=None,
    )

    rw_eval = evaluate_strategy_family(
        config=rw_config,
        monthly_value=monthly["value"],
        monthly_momentum=monthly["momentum"],
        folds=folds,
        transaction_cost_bps=args.cost_bps,
    )
    fm_eval = evaluate_strategy_family(
        config=fm_config,
        monthly_value=monthly["value"],
        monthly_momentum=monthly["momentum"],
        folds=folds,
        transaction_cost_bps=args.cost_bps,
    )

    fm_fixed = {}
    for l in [1, 3, 6, 12]:
        detail = fm_eval.cache[FMParams(lookback_months=l)]
        fm_fixed[f"fm_l{l}"] = detail["net"]

    comparison_panel = pd.concat(
        [
            monthly["momentum"].rename("momentum_only"),
            monthly["value"].rename("value_only"),
            ew,
            rw_eval.baseline_detail["net"].rename("rw_baseline") if rw_eval.baseline_detail is not None else None,
            rw_eval.oos_stitched["net"].rename("rw_oos_best"),
            rw_eval.fullsample_best_detail["net"].rename("rw_fullsample_best"),
            fm_fixed["fm_l1"].rename("fm_l1"),
            fm_fixed["fm_l3"].rename("fm_l3"),
            fm_fixed["fm_l6"].rename("fm_l6"),
            fm_fixed["fm_l12"].rename("fm_l12"),
            fm_eval.oos_stitched["net"].rename("fm_oos_best"),
            fm_eval.fullsample_best_detail["net"].rename("fm_fullsample_best"),
        ],
        axis=1,
    )
    comparison_panel = comparison_panel.dropna(axis=1, how="all")
    common_panel = comparison_panel.dropna()
    if common_panel.empty:
        raise RuntimeError("No common sample after combining strategy return series.")

    allocation_panel = pd.concat(
        [
            rw_eval.oos_stitched["w_mom"].rename("rw_oos_best_w_mom"),
            rw_eval.fullsample_best_detail["w_mom"].rename("rw_fullsample_best_w_mom"),
            fm_eval.oos_stitched["w_mom"].rename("fm_oos_best_w_mom"),
            fm_eval.fullsample_best_detail["w_mom"].rename("fm_fullsample_best_w_mom"),
        ],
        axis=1,
    )

    metrics_rows: List[Dict[str, object]] = []
    for col in common_panel.columns:
        row = metrics(common_panel[col])
        row["strategy"] = col
        metrics_rows.append(row)
    metrics_table = pd.DataFrame(metrics_rows)[
        ["strategy", "months", "cagr", "annualized_vol", "sharpe", "max_drawdown", "calmar"]
    ]

    combined_fold_scores = pd.concat([rw_eval.fold_scores, fm_eval.fold_scores], ignore_index=True)
    combined_winners = pd.concat([rw_eval.winners, fm_eval.winners], ignore_index=True)
    walkforward_param_summary = pd.concat([rw_eval.param_summary, fm_eval.param_summary], ignore_index=True)
    fullsample_param_summary = pd.concat([rw_eval.fullsample_summary, fm_eval.fullsample_summary], ignore_index=True)
    walkforward_param_summary = walkforward_param_summary.sort_values(["strategy_family", "mean_test_cagr"], ascending=[True, False])
    fullsample_param_summary = fullsample_param_summary.sort_values(["strategy_family", "fullsample_cagr"], ascending=[True, False])

    rw_oos_best_row = rw_eval.param_summary.iloc[0]
    rw_full_best_row = rw_eval.fullsample_summary.iloc[0]
    fm_oos_best_row = fm_eval.param_summary.iloc[0]
    fm_full_best_row = fm_eval.fullsample_summary.iloc[0]
    selected_params = pd.DataFrame(
        [
            {
                "strategy_family": "rw",
                "selection_method": "baseline",
                "lookback_months": rw_baseline_param.lookback_months,
                "target_vol_monthly": rw_baseline_param.target_vol_monthly,
                "notes": "Fixed paper baseline",
            },
            {
                "strategy_family": "rw",
                "selection_method": "walkforward_oos_best",
                "lookback_months": int(rw_oos_best_row["lookback_months"]),
                "target_vol_monthly": float(rw_oos_best_row["target_vol_monthly"]),
                "notes": "Best mean OOS CAGR",
            },
            {
                "strategy_family": "rw",
                "selection_method": "fullsample_best_no_cv",
                "lookback_months": int(rw_full_best_row["lookback_months"]),
                "target_vol_monthly": float(rw_full_best_row["target_vol_monthly"]),
                "notes": "Best full-sample CAGR",
            },
            {
                "strategy_family": "factor_momentum",
                "selection_method": "walkforward_oos_best",
                "lookback_months": int(fm_oos_best_row["lookback_months"]),
                "target_vol_monthly": np.nan,
                "notes": "Winner-takes-all signal, best mean OOS CAGR",
            },
            {
                "strategy_family": "factor_momentum",
                "selection_method": "fullsample_best_no_cv",
                "lookback_months": int(fm_full_best_row["lookback_months"]),
                "target_vol_monthly": np.nan,
                "notes": "Winner-takes-all signal, best full-sample CAGR",
            },
        ]
    )

    cost_rows: List[Dict[str, object]] = []
    for c_bps in [0.0, 5.0, 10.0]:
        rw_baseline_tmp = build_rw_strategy(monthly["value"], monthly["momentum"], rw_baseline_param, c_bps)
        rw_full_tmp = build_rw_strategy(monthly["value"], monthly["momentum"], rw_eval.fullsample_best_param, c_bps)
        fm_full_tmp = build_factor_momentum_strategy(monthly["value"], monthly["momentum"], fm_eval.fullsample_best_param, c_bps)
        rw_oos_fixed = rw_eval.oos_stitched["gross"] - (c_bps / 10000.0) * rw_eval.oos_stitched["turnover"]
        fm_oos_fixed = fm_eval.oos_stitched["gross"] - (c_bps / 10000.0) * fm_eval.oos_stitched["turnover"]

        for strategy_name, returns, turnover in (
            ("rw_baseline", rw_baseline_tmp["net"], rw_baseline_tmp["turnover"]),
            ("rw_fullsample_best", rw_full_tmp["net"], rw_full_tmp["turnover"]),
            ("rw_oos_best_fixed_params", rw_oos_fixed, rw_eval.oos_stitched["turnover"]),
            ("fm_fullsample_best", fm_full_tmp["net"], fm_full_tmp["turnover"]),
            ("fm_oos_best_fixed_params", fm_oos_fixed, fm_eval.oos_stitched["turnover"]),
        ):
            mm = metrics(returns)
            cost_rows.append(
                {
                    "strategy": strategy_name,
                    "cost_bps": c_bps,
                    "cagr": mm["cagr"],
                    "annualized_vol": mm["annualized_vol"],
                    "sharpe": mm["sharpe"],
                    "max_drawdown": mm["max_drawdown"],
                    "calmar": mm["calmar"],
                    "avg_turnover": float(turnover.dropna().mean()),
                }
            )
    transaction_cost_sensitivity = pd.DataFrame(cost_rows)

    data_quality = pd.DataFrame(
        [
            {
                "series": "value_daily_levels",
                "rows": int(value_levels_daily.shape[0]),
                "start": value_levels_daily.index.min(),
                "end": value_levels_daily.index.max(),
            },
            {
                "series": "momentum_daily_levels",
                "rows": int(momentum_levels_daily.shape[0]),
                "start": momentum_levels_daily.index.min(),
                "end": momentum_levels_daily.index.max(),
            },
            {
                "series": "value_monthly_levels_sampled",
                "rows": int(value_levels_monthly.shape[0]),
                "start": value_levels_monthly.index.min(),
                "end": value_levels_monthly.index.max(),
            },
            {
                "series": "momentum_monthly_levels_sampled",
                "rows": int(momentum_levels_monthly.shape[0]),
                "start": momentum_levels_monthly.index.min(),
                "end": momentum_levels_monthly.index.max(),
            },
            {
                "series": "monthly_common_returns",
                "rows": int(monthly.shape[0]),
                "start": monthly.index.min(),
                "end": monthly.index.max(),
            },
            {
                "series": "value_dropped_partial_end_months",
                "rows": len(value_dropped_months),
                "start": value_dropped_months[0] if value_dropped_months else pd.NaT,
                "end": value_dropped_months[-1] if value_dropped_months else pd.NaT,
            },
            {
                "series": "momentum_dropped_partial_end_months",
                "rows": len(momentum_dropped_months),
                "start": momentum_dropped_months[0] if momentum_dropped_months else pd.NaT,
                "end": momentum_dropped_months[-1] if momentum_dropped_months else pd.NaT,
            },
        ]
    )

    notes = [
        "Monthly-only pipeline: daily levels are sampled to month-end levels immediately after load.",
        "RW strategy: paper-faithful sigma_obs from trailing monthly momentum volatility, lagged by one month.",
        "Factor-momentum strategy: winner-takes-all allocation using lagged trailing K-month factor momentum signals (K in {1,3,6,12}).",
        "TODO alternatives documented in code: linear-tilt signal mapping and persistence filter.",
        "All hyperparameters are reported for CV and full-sample summaries across both strategy families.",
    ]

    monthly_levels.to_csv(outdir / "monthly_levels.csv", index_label="date")
    monthly.to_csv(outdir / "monthly_returns.csv", index_label="date")
    comparison_panel.to_csv(outdir / "strategy_returns_panel.csv", index_label="date")
    common_panel.to_csv(outdir / "strategy_returns_common_sample.csv", index_label="date")
    metrics_table.to_csv(outdir / "metrics_common_sample.csv", index=False)
    data_quality.to_csv(outdir / "data_quality.csv", index=False)

    rw_eval.baseline_detail.to_csv(outdir / "rw_baseline_detail.csv", index_label="date")
    rw_eval.fullsample_best_detail.to_csv(outdir / "rw_fullsample_best_detail.csv", index_label="date")
    rw_eval.oos_stitched["net"].to_frame("rw_oos_best").to_csv(outdir / "rw_oos_best_series.csv", index_label="date")
    fm_eval.fullsample_best_detail.to_csv(outdir / "fm_fullsample_best_detail.csv", index_label="date")
    fm_eval.oos_stitched["net"].to_frame("fm_oos_best").to_csv(outdir / "fm_oos_best_series.csv", index_label="date")

    combined_fold_scores.to_csv(outdir / "walkforward_fold_scores.csv", index=False)
    combined_winners.to_csv(outdir / "walkforward_winners.csv", index=False)
    walkforward_param_summary.to_csv(outdir / "walkforward_param_summary.csv", index=False)
    fullsample_param_summary.to_csv(outdir / "fullsample_param_summary.csv", index=False)
    selected_params.to_csv(outdir / "selected_hyperparameters.csv", index=False)
    transaction_cost_sensitivity.to_csv(outdir / "transaction_cost_sensitivity.csv", index=False)

    plot_cumulative_and_drawdown(common_panel, allocation_panel, outdir)
    plot_rolling_metrics(common_panel, outdir)
    plot_weights_turnover(rw_eval.baseline_detail, outdir, "rw_baseline")
    plot_weights_turnover(rw_eval.fullsample_best_detail, outdir, "rw_fullsample_best")
    plot_weights_turnover(fm_eval.fullsample_best_detail, outdir, "fm_fullsample_best")
    plot_weights_turnover(fm_eval.oos_stitched, outdir, "fm_oos_best")

    plot_param_surface(
        rw_eval.param_summary,
        value_col="mean_test_cagr",
        title="RW Walk-forward mean OOS CAGR",
        outpath=outdir / "surface_oos_cagr_rw.png",
    )
    plot_param_surface(
        rw_eval.fullsample_summary,
        value_col="fullsample_cagr",
        title="RW Full-sample CAGR (no CV)",
        outpath=outdir / "surface_fullsample_cagr_rw.png",
    )
    plot_param_surface(
        fm_eval.param_summary,
        value_col="mean_test_cagr",
        title="Factor Momentum Walk-forward mean OOS CAGR",
        outpath=outdir / "surface_oos_cagr_factor_momentum.png",
    )
    plot_param_surface(
        fm_eval.fullsample_summary,
        value_col="fullsample_cagr",
        title="Factor Momentum Full-sample CAGR (no CV)",
        outpath=outdir / "surface_fullsample_cagr_factor_momentum.png",
    )

    plot_winner_stability(
        rw_eval.winners,
        outpath=outdir / "winner_stability_rw.png",
        title_prefix="RW",
    )
    plot_winner_stability(
        fm_eval.winners,
        outpath=outdir / "winner_stability_factor_momentum.png",
        title_prefix="Factor Momentum",
    )

    generate_summary_markdown(
        outdir=outdir,
        data_quality=data_quality,
        metrics_table=metrics_table,
        selected_params=selected_params,
        walkforward_param_summary=walkforward_param_summary,
        fullsample_param_summary=fullsample_param_summary,
        walkforward_winners=combined_winners,
        transaction_cost_sensitivity=transaction_cost_sensitivity,
        notes=notes,
    )

    print(f"Completed multi-strategy replication. Outputs written to: {outdir}")
    print(
        "RW best OOS: "
        f"L={int(rw_oos_best_row['lookback_months'])}, "
        f"target_vol_monthly={float(rw_oos_best_row['target_vol_monthly']):.4f}"
    )
    print(
        "Factor momentum best OOS: "
        f"L={int(fm_oos_best_row['lookback_months'])}"
    )


if __name__ == "__main__":
    main()
