from __future__ import annotations

import pandas as pd


def target_weights(candidates: pd.DataFrame, top_n: int, weighting_scheme: str = "equal_weight") -> pd.DataFrame:
    selected = candidates[candidates["eligible_final"]].sort_values(
        ["rank_metric", "provider_symbol"], ascending=[False, True]
    ).head(top_n).copy()
    if selected.empty:
        selected["target_weight"] = []
        return selected
    if weighting_scheme == "equal_weight":
        selected["target_weight"] = 1.0 / len(selected)
    elif weighting_scheme == "positive_momentum_proportional":
        raw = selected["rank_metric"].clip(lower=0)
        total = raw.sum()
        selected["target_weight"] = raw / total if total > 0 else 0.0
    else:
        raise ValueError(f"Unknown weighting scheme: {weighting_scheme}")
    return selected


def build_trades(
    panel: pd.DataFrame,
    strategy_id: str,
    top_n: int,
    weighting_scheme: str,
    transaction_cost_bps_one_way: float,
    portfolio_value: float = 1.0,
) -> pd.DataFrame:
    previous: dict[str, float] = {}
    trades = []
    for rebalance_date, group in panel.groupby("rebalance_date", sort=True):
        selected = target_weights(group, top_n=top_n, weighting_scheme=weighting_scheme)
        target = dict(zip(selected["security_id"], selected["target_weight"]))
        names = sorted(set(previous) | set(target))
        for security_id in names:
            prev_weight = previous.get(security_id, 0.0)
            tgt_weight = target.get(security_id, 0.0)
            trade_weight = tgt_weight - prev_weight
            if abs(trade_weight) < 1e-12:
                continue
            row = selected[selected["security_id"] == security_id]
            reference = row.iloc[0] if not row.empty else group[group["security_id"] == security_id].iloc[0]
            trades.append(
                {
                    "strategy_id": strategy_id,
                    "rebalance_date": rebalance_date,
                    "execution_date": reference["execution_date"],
                    "security_id": security_id,
                    "provider_symbol": reference.get("provider_symbol"),
                    "side": "buy" if trade_weight > 0 else "sell",
                    "target_weight": tgt_weight,
                    "previous_weight": prev_weight,
                    "trade_weight": trade_weight,
                    "price_eur": reference.get("price_eur_signal"),
                    "gross_trade_value_eur": abs(trade_weight) * portfolio_value,
                    "transaction_cost_eur": abs(trade_weight) * portfolio_value * transaction_cost_bps_one_way / 10000,
                    "rationale_rank": reference.get("rank_ascending_false"),
                    "rationale_momentum": reference.get("rank_metric"),
                    "run_id": reference.get("run_id"),
                }
            )
        previous = target
    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame, strategy_id: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            [{
                "strategy_id": strategy_id,
                "rebalance_frequency": "",
                "top_n": 0,
                "lookback_months": 12,
                "skip_recent_months": 0,
                "weighting_scheme": "",
                "transaction_cost_bps_one_way": 0,
                "start_date": None,
                "end_date": None,
                "total_return": None,
                "cagr": None,
                "annualized_volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "turnover": 0,
                "rebalance_count": 0,
                "trade_count": 0,
                "run_id": None,
            }]
        )
    return pd.DataFrame(
        [{
            "strategy_id": strategy_id,
            "rebalance_frequency": "",
            "top_n": 0,
            "lookback_months": 12,
            "skip_recent_months": 0,
            "weighting_scheme": "",
            "transaction_cost_bps_one_way": 0,
            "start_date": trades["rebalance_date"].min(),
            "end_date": trades["rebalance_date"].max(),
            "total_return": None,
            "cagr": None,
            "annualized_volatility": None,
            "sharpe_ratio": None,
            "max_drawdown": None,
            "turnover": trades["trade_weight"].abs().sum(),
            "rebalance_count": trades["rebalance_date"].nunique(),
            "trade_count": len(trades),
            "run_id": trades["run_id"].dropna().iloc[0] if trades["run_id"].notna().any() else None,
        }]
    )
