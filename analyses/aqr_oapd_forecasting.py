from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.decomposition import PCA
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge

from db_utils.config import get_database_config
from db_utils.database import build_engine, read_table


TARGET_COLUMN = "target"
DEFAULT_AQR_FACTOR_SETS = ("qmj_factors", "vme_factors")
DEFAULT_OAPD_FACTOR_SET = "oapd::predictor_ls"


@dataclass
class ForecastConfig:
    horizon_months: int = 12
    label_gap_months: int = 12
    min_train_months: int = 120
    validation_months: int = 60
    max_missing_fraction: float = 0.30
    phase1_top_n_candidates: int = 40
    top_k_ols_values: Tuple[int, ...] = (5, 10, 20)
    ridge_alphas: Tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
    elasticnet_alphas: Tuple[float, ...] = (0.001, 0.01, 0.1, 1.0)
    elasticnet_l1_ratios: Tuple[float, ...] = (0.2, 0.5, 0.8)
    pca_components: Tuple[int, ...] = (3, 5, 8, 12)
    pls_components: Tuple[int, ...] = (2, 3, 5, 8)
    max_iter: int = 10000


def _clean_series_name(value: str) -> str:
    return value.replace("/", "_").replace(" ", "_").replace("::", "__")


def _save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _safe_corr(x: pd.Series, y: pd.Series) -> float:
    merged = pd.concat([x, y], axis=1).dropna()
    if merged.shape[0] < 3:
        return np.nan
    return float(merged.iloc[:, 0].corr(merged.iloc[:, 1]))


def _max_drawdown(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.empty:
        return np.nan
    wealth = (1.0 + clean).cumprod()
    peak = wealth.cummax()
    drawdown = wealth / peak - 1.0
    return float(drawdown.min())


def _annualized_sharpe(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.shape[0] < 2:
        return np.nan
    vol = clean.std(ddof=0)
    if vol == 0 or np.isnan(vol):
        return np.nan
    return float(clean.mean() / vol * np.sqrt(12.0))


def _annualized_mean(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.empty:
        return np.nan
    return float(clean.mean() * 12.0)


def _annualized_vol(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.shape[0] < 2:
        return np.nan
    return float(clean.std(ddof=0) * np.sqrt(12.0))


def load_factor_matrix(
    engine,
    source: str,
    factor_sets: Sequence[str],
    frequency: str = "M",
    factors: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    where_parts = [
        "source = :source",
        "frequency = :frequency",
        "factor_set IN :factor_sets",
    ]
    params: Dict[str, object] = {
        "source": source,
        "frequency": frequency,
        "factor_sets": tuple(factor_sets),
    }
    expanding: List[str] = ["factor_sets"]

    if factors:
        where_parts.append("factor IN :factors")
        params["factors"] = tuple(factors)
        expanding.append("factors")

    raw = read_table(
        engine,
        table="factor_returns",
        columns=["factor_set", "factor", "date", "value"],
        where=" AND ".join(where_parts),
        params=params,
        order_by=["date"],
        expanding=expanding,
    )
    if raw.empty:
        return pd.DataFrame()

    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.dropna(subset=["date", "factor", "value"])
    raw["series"] = raw["factor_set"].astype(str) + "::" + raw["factor"].astype(str)
    raw = raw.drop_duplicates(subset=["series", "date"], keep="last")
    wide = raw.pivot(index="date", columns="series", values="value").sort_index()
    return wide


def load_oapd_predictors(
    engine,
    factor_set: str = DEFAULT_OAPD_FACTOR_SET,
) -> pd.DataFrame:
    panel = load_factor_matrix(
        engine=engine,
        source="open_asset_pricing",
        factor_sets=[factor_set],
        frequency="M",
    )
    if panel.empty:
        return panel
    renamed = {}
    for col in panel.columns:
        parts = col.split("::")
        renamed[col] = parts[-1] if parts else col
    panel = panel.rename(columns=renamed)
    if panel.columns.duplicated().any():
        panel = panel.groupby(level=0, axis=1).mean()
    return panel.sort_index()


def build_predictor_features(
    predictor_returns: pd.DataFrame,
    lag_values: Sequence[int] = (1, 2),
    include_mom12: bool = True,
    include_vol12: bool = True,
) -> pd.DataFrame:
    if predictor_returns.empty:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = [predictor_returns.add_suffix("__lvl")]
    for lag in lag_values:
        frames.append(predictor_returns.shift(lag).add_suffix(f"__lag{lag}"))

    if include_mom12:
        momentum_12 = (1.0 + predictor_returns).rolling(window=12, min_periods=12).apply(
            np.prod, raw=True
        ) - 1.0
        frames.append(momentum_12.add_suffix("__mom12"))

    if include_vol12:
        vol_12 = predictor_returns.rolling(window=12, min_periods=12).std(ddof=0)
        frames.append(vol_12.add_suffix("__vol12"))

    return pd.concat(frames, axis=1).sort_index()


def forward_cumulative_return(monthly_returns: pd.Series, horizon_months: int) -> pd.Series:
    values = pd.to_numeric(monthly_returns, errors="coerce").to_numpy(dtype=float)
    out = np.full(values.shape[0], np.nan, dtype=float)
    if horizon_months < 1:
        raise ValueError("horizon_months must be >= 1")

    gross = 1.0 + values
    for idx in range(0, values.shape[0] - horizon_months):
        window = gross[idx + 1 : idx + 1 + horizon_months]
        if np.isnan(window).any():
            continue
        out[idx] = np.prod(window) - 1.0

    return pd.Series(out, index=monthly_returns.index, name=TARGET_COLUMN)


def build_factor_dataset(
    factor_returns: pd.Series,
    predictor_features: pd.DataFrame,
    horizon_months: int,
) -> pd.DataFrame:
    own_returns = factor_returns.sort_index().rename("aqr_return_l0")
    own_mom12 = (1.0 + own_returns).rolling(window=12, min_periods=12).apply(np.prod, raw=True) - 1.0
    own_mom12 = own_mom12.rename("aqr_mom12")
    own_vol12 = own_returns.rolling(window=12, min_periods=12).std(ddof=0).rename("aqr_vol12")
    own_lag1 = own_returns.shift(1).rename("aqr_return_l1")

    target = forward_cumulative_return(own_returns, horizon_months=horizon_months)
    dataset = pd.concat(
        [target, own_returns, own_lag1, own_mom12, own_vol12, predictor_features],
        axis=1,
        join="inner",
    ).sort_index()
    dataset.index.name = "date"
    return dataset


def _forecast_positions(
    dataset: pd.DataFrame,
    config: ForecastConfig,
) -> Iterable[Tuple[int, int]]:
    for idx in range(dataset.shape[0]):
        train_end = idx - config.label_gap_months
        if train_end < config.min_train_months:
            continue
        actual = dataset.iloc[idx][TARGET_COLUMN]
        if pd.isna(actual):
            continue
        yield idx, train_end


def _prepare_design(
    train_df: pd.DataFrame,
    pred_row: pd.Series,
    feature_cols: Sequence[str],
    max_missing_fraction: float,
    standardize: bool = True,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]]:
    if not feature_cols:
        return None

    used = train_df[[TARGET_COLUMN, *feature_cols]].dropna(subset=[TARGET_COLUMN])
    if used.empty:
        return None

    feature_frame = used[list(feature_cols)]
    missing_ratio = feature_frame.isna().mean()
    kept_cols = [col for col in feature_cols if missing_ratio.get(col, 1.0) <= max_missing_fraction]
    if not kept_cols:
        return None

    x_train_df = used[kept_cols].copy()
    col_means = x_train_df.mean(axis=0)
    x_train_df = x_train_df.fillna(col_means)
    x_train_df = x_train_df.fillna(0.0)

    x_pred = pred_row[kept_cols].copy()
    x_pred = x_pred.fillna(col_means)
    x_pred = x_pred.fillna(0.0)

    y_train = used[TARGET_COLUMN].astype(float).to_numpy()
    x_train = x_train_df.astype(float).to_numpy()
    x_pred_arr = x_pred.astype(float).to_numpy().reshape(1, -1)

    if standardize:
        mean = x_train.mean(axis=0)
        std = x_train.std(axis=0, ddof=0)
        std[std == 0.0] = 1.0
        x_train = (x_train - mean) / std
        x_pred_arr = (x_pred_arr - mean) / std

    return x_train, y_train, x_pred_arr, kept_cols


def _train_validation_split(
    x_train: np.ndarray,
    y_train: np.ndarray,
    validation_months: int,
    minimum_train: int = 36,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    if y_train.shape[0] < validation_months + minimum_train:
        return None
    split = y_train.shape[0] - validation_months
    return (
        x_train[:split],
        y_train[:split],
        x_train[split:],
        y_train[split:],
    )


ModelFunction = Callable[[pd.DataFrame, pd.Series], Tuple[Optional[float], Dict[str, object]]]


def run_walk_forward(
    dataset: pd.DataFrame,
    config: ForecastConfig,
    model_name: str,
    model_fn: ModelFunction,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for idx, train_end in _forecast_positions(dataset, config):
        train_df = dataset.iloc[:train_end].copy()
        pred_row = dataset.iloc[idx]
        forecast, meta = model_fn(train_df, pred_row)
        if forecast is None or pd.isna(forecast):
            continue
        row = {
            "date": dataset.index[idx],
            "actual": float(pred_row[TARGET_COLUMN]),
            "forecast": float(forecast),
            "train_obs": int(train_end),
            "model": model_name,
        }
        row.update(meta)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["date", "actual", "forecast", "train_obs", "model"])
    return pd.DataFrame(rows).sort_values("date")


def compute_forecast_metrics(
    forecast_df: pd.DataFrame,
    benchmark_df: Optional[pd.DataFrame] = None,
) -> Dict[str, object]:
    if forecast_df.empty:
        return {
            "n_obs": 0,
            "rmse": np.nan,
            "mae": np.nan,
            "corr": np.nan,
            "sign_accuracy": np.nan,
            "mse": np.nan,
            "r2_oos": np.nan,
        }

    merged = forecast_df[["date", "actual", "forecast"]].dropna()
    if merged.empty:
        return {
            "n_obs": 0,
            "rmse": np.nan,
            "mae": np.nan,
            "corr": np.nan,
            "sign_accuracy": np.nan,
            "mse": np.nan,
            "r2_oos": np.nan,
        }

    errors = merged["actual"] - merged["forecast"]
    mse = float(np.mean(np.square(errors)))
    rmse = float(np.sqrt(mse))
    mae = float(np.mean(np.abs(errors)))
    corr = _safe_corr(merged["actual"], merged["forecast"])
    sign_accuracy = float((np.sign(merged["actual"]) == np.sign(merged["forecast"])).mean())

    metrics: Dict[str, object] = {
        "n_obs": int(merged.shape[0]),
        "rmse": rmse,
        "mae": mae,
        "corr": corr,
        "sign_accuracy": sign_accuracy,
        "mse": mse,
        "r2_oos": np.nan,
    }

    if benchmark_df is not None and not benchmark_df.empty:
        joined = merged.merge(
            benchmark_df[["date", "forecast"]].rename(columns={"forecast": "benchmark_forecast"}),
            on="date",
            how="inner",
        )
        if not joined.empty:
            bench_mse = float(np.mean(np.square(joined["actual"] - joined["benchmark_forecast"])))
            metrics["benchmark_mse"] = bench_mse
            metrics["r2_oos"] = np.nan if bench_mse == 0 else float(1.0 - mse / bench_mse)
    return metrics


def subset_r2_oos(
    forecast_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    date_mask: pd.Series,
) -> float:
    if forecast_df.empty or benchmark_df.empty:
        return np.nan

    subset = forecast_df.loc[date_mask].copy()
    bench_subset = benchmark_df.loc[benchmark_df["date"].isin(subset["date"])]
    metrics = compute_forecast_metrics(subset, benchmark_df=bench_subset)
    return float(metrics.get("r2_oos", np.nan))


def make_mean_model() -> ModelFunction:
    def _model(train_df: pd.DataFrame, _: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        values = train_df[TARGET_COLUMN].dropna()
        if values.empty:
            return None, {}
        return float(values.mean()), {"model_type": "baseline_mean"}

    return _model


def make_linear_single_feature_model(
    feature_col: str,
    config: ForecastConfig,
    model_type: str,
) -> ModelFunction:
    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=[feature_col],
            max_missing_fraction=config.max_missing_fraction,
            standardize=False,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, _ = prepared
        if y_train.shape[0] < 24:
            return None, {}
        reg = LinearRegression()
        reg.fit(x_train, y_train)
        pred = float(reg.predict(x_pred)[0])
        return pred, {
            "model_type": model_type,
            "coef": float(reg.coef_[0]) if reg.coef_.size else np.nan,
            "intercept": float(reg.intercept_),
        }

    return _model


def make_naive_feature_model(feature_col: str, model_type: str) -> ModelFunction:
    def _model(_: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        value = pred_row.get(feature_col)
        if value is None or pd.isna(value):
            return None, {}
        return float(value), {"model_type": model_type}

    return _model


def make_univariate_oos_model(
    feature_col: str,
    config: ForecastConfig,
) -> ModelFunction:
    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=[feature_col],
            max_missing_fraction=config.max_missing_fraction,
            standardize=True,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, _ = prepared
        if y_train.shape[0] < 36:
            return None, {}
        reg = LinearRegression()
        reg.fit(x_train, y_train)
        pred = float(reg.predict(x_pred)[0])
        return pred, {
            "model_type": "univariate_linear",
            "feature": feature_col,
            "beta": float(reg.coef_[0]) if reg.coef_.size else np.nan,
        }

    return _model


def _select_top_k_by_abs_corr(
    train_df: pd.DataFrame,
    candidate_features: Sequence[str],
    top_k: int,
) -> List[str]:
    scores: List[Tuple[str, float]] = []
    target = train_df[TARGET_COLUMN]
    for feature in candidate_features:
        corr = _safe_corr(target, train_df[feature])
        if np.isnan(corr):
            continue
        scores.append((feature, abs(corr)))
    scores.sort(key=lambda item: item[1], reverse=True)
    return [feature for feature, _ in scores[:top_k]]


def make_topk_ols_model(
    candidate_features: Sequence[str],
    top_k: int,
    config: ForecastConfig,
) -> ModelFunction:
    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        selected = _select_top_k_by_abs_corr(train_df, candidate_features, top_k=top_k)
        if not selected:
            return None, {}
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=selected,
            max_missing_fraction=config.max_missing_fraction,
            standardize=True,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, kept_cols = prepared
        if y_train.shape[0] < 36:
            return None, {}
        reg = LinearRegression()
        reg.fit(x_train, y_train)
        pred = float(reg.predict(x_pred)[0])
        return pred, {
            "model_type": "topk_ols",
            "top_k": top_k,
            "n_features": int(len(kept_cols)),
        }

    return _model


def make_ridge_model(
    feature_cols: Sequence[str],
    config: ForecastConfig,
) -> ModelFunction:
    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=feature_cols,
            max_missing_fraction=config.max_missing_fraction,
            standardize=True,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, kept_cols = prepared
        if y_train.shape[0] < 36:
            return None, {}

        chosen_alpha = config.ridge_alphas[0]
        split = _train_validation_split(x_train, y_train, validation_months=config.validation_months)
        if split is not None:
            x_inner, y_inner, x_val, y_val = split
            best_mse = np.inf
            for alpha in config.ridge_alphas:
                model = Ridge(alpha=float(alpha))
                model.fit(x_inner, y_inner)
                val_pred = model.predict(x_val)
                mse = float(np.mean(np.square(y_val - val_pred)))
                if mse < best_mse:
                    best_mse = mse
                    chosen_alpha = alpha

        final_model = Ridge(alpha=float(chosen_alpha))
        final_model.fit(x_train, y_train)
        pred = float(final_model.predict(x_pred)[0])
        return pred, {
            "model_type": "ridge",
            "alpha": float(chosen_alpha),
            "n_features": int(len(kept_cols)),
        }

    return _model


def make_elasticnet_model(
    feature_cols: Sequence[str],
    config: ForecastConfig,
) -> ModelFunction:
    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=feature_cols,
            max_missing_fraction=config.max_missing_fraction,
            standardize=True,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, kept_cols = prepared
        if y_train.shape[0] < 60:
            return None, {}

        chosen_alpha = config.elasticnet_alphas[0]
        chosen_l1_ratio = config.elasticnet_l1_ratios[0]
        split = _train_validation_split(x_train, y_train, validation_months=config.validation_months)
        if split is not None:
            x_inner, y_inner, x_val, y_val = split
            best_mse = np.inf
            for l1_ratio in config.elasticnet_l1_ratios:
                for alpha in config.elasticnet_alphas:
                    model = ElasticNet(
                        alpha=float(alpha),
                        l1_ratio=float(l1_ratio),
                        max_iter=config.max_iter,
                        random_state=0,
                    )
                    model.fit(x_inner, y_inner)
                    val_pred = model.predict(x_val)
                    mse = float(np.mean(np.square(y_val - val_pred)))
                    if mse < best_mse:
                        best_mse = mse
                        chosen_alpha = alpha
                        chosen_l1_ratio = l1_ratio

        final_model = ElasticNet(
            alpha=float(chosen_alpha),
            l1_ratio=float(chosen_l1_ratio),
            max_iter=config.max_iter,
            random_state=0,
        )
        final_model.fit(x_train, y_train)
        pred = float(final_model.predict(x_pred)[0])
        non_zero = int(np.sum(np.abs(final_model.coef_) > 1e-10))
        return pred, {
            "model_type": "elasticnet",
            "alpha": float(chosen_alpha),
            "l1_ratio": float(chosen_l1_ratio),
            "n_features": int(len(kept_cols)),
            "non_zero_features": non_zero,
        }

    return _model


def _choose_n_components(
    available: Sequence[int],
    x_train: np.ndarray,
    y_train: np.ndarray,
    validation_months: int,
    fit_predict: Callable[[int, np.ndarray, np.ndarray, np.ndarray], np.ndarray],
) -> int:
    feasible = [
        n
        for n in available
        if n >= 1 and n < min(x_train.shape[0], x_train.shape[1] + 1)
    ]
    if not feasible:
        return 1
    split = _train_validation_split(x_train, y_train, validation_months=validation_months)
    if split is None:
        return feasible[0]
    x_inner, y_inner, x_val, y_val = split

    best_n = feasible[0]
    best_mse = np.inf
    for n_components in feasible:
        val_pred = fit_predict(n_components, x_inner, y_inner, x_val)
        mse = float(np.mean(np.square(y_val - val_pred)))
        if mse < best_mse:
            best_mse = mse
            best_n = n_components
    return int(best_n)


def make_pca_regression_model(
    feature_cols: Sequence[str],
    config: ForecastConfig,
) -> ModelFunction:
    def _predict_with_components(
        n_components: int,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_new: np.ndarray,
    ) -> np.ndarray:
        pca = PCA(n_components=n_components, random_state=0)
        z_train = pca.fit_transform(x_train)
        reg = LinearRegression()
        reg.fit(z_train, y_train)
        return reg.predict(pca.transform(x_new))

    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=feature_cols,
            max_missing_fraction=config.max_missing_fraction,
            standardize=True,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, kept_cols = prepared
        if y_train.shape[0] < 48:
            return None, {}

        n_components = _choose_n_components(
            available=config.pca_components,
            x_train=x_train,
            y_train=y_train,
            validation_months=config.validation_months,
            fit_predict=_predict_with_components,
        )
        forecast = float(_predict_with_components(n_components, x_train, y_train, x_pred)[0])
        return forecast, {
            "model_type": "pca_regression",
            "n_components": int(n_components),
            "n_features": int(len(kept_cols)),
        }

    return _model


def make_pls_model(
    feature_cols: Sequence[str],
    config: ForecastConfig,
) -> ModelFunction:
    def _predict_with_components(
        n_components: int,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_new: np.ndarray,
    ) -> np.ndarray:
        pls = PLSRegression(n_components=n_components, scale=True)
        pls.fit(x_train, y_train)
        return pls.predict(x_new).reshape(-1)

    def _model(train_df: pd.DataFrame, pred_row: pd.Series) -> Tuple[Optional[float], Dict[str, object]]:
        prepared = _prepare_design(
            train_df,
            pred_row,
            feature_cols=feature_cols,
            max_missing_fraction=config.max_missing_fraction,
            standardize=False,
        )
        if prepared is None:
            return None, {}
        x_train, y_train, x_pred, kept_cols = prepared
        if y_train.shape[0] < 48:
            return None, {}

        max_comp = min(x_train.shape[0] - 1, x_train.shape[1])
        available = [n for n in config.pls_components if n <= max_comp]
        if not available:
            available = [max(1, min(2, max_comp))]

        n_components = _choose_n_components(
            available=available,
            x_train=x_train,
            y_train=y_train,
            validation_months=config.validation_months,
            fit_predict=_predict_with_components,
        )
        forecast = float(_predict_with_components(n_components, x_train, y_train, x_pred)[0])
        return forecast, {
            "model_type": "pls",
            "n_components": int(n_components),
            "n_features": int(len(kept_cols)),
        }

    return _model


def evaluate_timing_strategies(
    factor_monthly_returns: pd.Series,
    forecast_df: pd.DataFrame,
    max_weight: float = 2.0,
    allow_short_binary: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if forecast_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    returns = factor_monthly_returns.sort_index()
    forecast_rows = forecast_df[["date", "forecast"]].dropna().sort_values("date")
    rows: List[Dict[str, object]] = []
    for _, row in forecast_rows.iterrows():
        signal_date = pd.Timestamp(row["date"])
        realized_date = signal_date + pd.offsets.MonthEnd(1)
        if realized_date not in returns.index:
            continue

        realized_return = returns.loc[realized_date]
        trailing = returns.loc[:signal_date].tail(12)
        trailing_vol = float(trailing.std(ddof=0)) if trailing.shape[0] >= 2 else np.nan
        trailing_mom = np.nan
        if trailing.shape[0] >= 12:
            trailing_mom = float(np.prod(1.0 + trailing.values) - 1.0)

        forecast_value = float(row["forecast"])
        binary_pos = 0.0
        if forecast_value > 0:
            binary_pos = 1.0
        elif allow_short_binary and forecast_value < 0:
            binary_pos = -1.0

        if np.isnan(trailing_vol) or trailing_vol <= 0:
            vol_pos = 0.0
        else:
            vol_pos = float(np.clip(forecast_value / trailing_vol, -max_weight, max_weight))

        momentum_pos = 0.0
        if not np.isnan(trailing_mom) and trailing_mom > 0:
            momentum_pos = 1.0

        rows.append(
            {
                "signal_date": signal_date,
                "date": realized_date,
                "realized_factor_return": float(realized_return),
                "binary_position": binary_pos,
                "vol_position": vol_pos,
                "mom12_position": momentum_pos,
                "binary_return": float(binary_pos * realized_return),
                "vol_return": float(vol_pos * realized_return),
                "buy_hold_return": float(realized_return),
                "mom12_return": float(momentum_pos * realized_return),
            }
        )

    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    monthly = pd.DataFrame(rows).sort_values("date")

    def _summarize(name: str, returns_col: str, position_col: Optional[str]) -> Dict[str, object]:
        series = monthly[returns_col]
        turnover = np.nan
        if position_col is not None:
            turnover = float(monthly[position_col].diff().abs().mean())
        return {
            "strategy": name,
            "n_months": int(series.dropna().shape[0]),
            "annual_return": _annualized_mean(series),
            "annual_vol": _annualized_vol(series),
            "sharpe": _annualized_sharpe(series),
            "max_drawdown": _max_drawdown(series),
            "hit_rate": float((series > 0).mean()) if not series.empty else np.nan,
            "turnover": turnover,
        }

    summary_rows = [
        _summarize("binary_timing", "binary_return", "binary_position"),
        _summarize("vol_scaled_timing", "vol_return", "vol_position"),
        _summarize("buy_and_hold", "buy_hold_return", None),
        _summarize("aqr_mom12_baseline", "mom12_return", "mom12_position"),
    ]
    summary = pd.DataFrame(summary_rows)
    return monthly, summary


def run_phase_0(
    dataset: pd.DataFrame,
    config: ForecastConfig,
    output_dir: Path,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    models = {
        "phase0_mean": make_mean_model(),
        "phase0_ar1": make_linear_single_feature_model(
            feature_col="aqr_return_l0",
            config=config,
            model_type="baseline_ar1_like",
        ),
        "phase0_mom12": make_naive_feature_model(
            feature_col="aqr_mom12",
            model_type="baseline_mom12_naive",
        ),
    }
    forecasts: Dict[str, pd.DataFrame] = {}
    metrics_rows: List[Dict[str, object]] = []

    baseline = run_walk_forward(dataset, config, "phase0_mean", models["phase0_mean"])
    forecasts["phase0_mean"] = baseline
    _save_csv(baseline, output_dir / "phase0" / "forecasts_phase0_mean.csv")
    metrics_rows.append({"model": "phase0_mean", **compute_forecast_metrics(baseline, benchmark_df=baseline)})

    for name, model_fn in models.items():
        if name == "phase0_mean":
            continue
        forecast_df = run_walk_forward(dataset, config, name, model_fn)
        forecasts[name] = forecast_df
        _save_csv(forecast_df, output_dir / "phase0" / f"forecasts_{name}.csv")
        metrics_rows.append({"model": name, **compute_forecast_metrics(forecast_df, benchmark_df=baseline)})

    metrics = pd.DataFrame(metrics_rows).sort_values("model")
    _save_csv(metrics, output_dir / "phase0" / "metrics.csv")
    return metrics, forecasts


def run_phase_1(
    dataset: pd.DataFrame,
    config: ForecastConfig,
    level_feature_cols: Sequence[str],
    baseline_df: pd.DataFrame,
    output_dir: Path,
) -> Tuple[pd.DataFrame, List[str], Dict[str, pd.DataFrame]]:
    expected_columns = [
        "feature",
        "model",
        "rank_order_hint",
        "r2_oos",
        "rmse",
        "mae",
        "corr",
        "sign_accuracy",
        "n_obs",
        "pre_2000_r2_oos",
        "post_2000_r2_oos",
        "beta_sign_consistency",
        "beta_positive_fraction",
    ]
    rows: List[Dict[str, object]] = []
    forecast_store: Dict[str, pd.DataFrame] = {}
    split_date = pd.Timestamp("2000-01-31")

    for idx, feature in enumerate(level_feature_cols):
        model_name = f"phase1_uni::{feature}"
        forecasts = run_walk_forward(
            dataset=dataset,
            config=config,
            model_name=model_name,
            model_fn=make_univariate_oos_model(feature, config=config),
        )
        if forecasts.empty:
            continue
        metrics = compute_forecast_metrics(forecasts, benchmark_df=baseline_df)
        pre_mask = forecasts["date"] < split_date
        post_mask = forecasts["date"] >= split_date
        pre_r2 = subset_r2_oos(forecasts, baseline_df, pre_mask)
        post_r2 = subset_r2_oos(forecasts, baseline_df, post_mask)
        betas = pd.to_numeric(forecasts.get("beta"), errors="coerce").dropna()
        non_zero = betas.loc[betas.abs() > 1e-10]
        sign_consistency = np.nan
        beta_positive_fraction = np.nan
        if not non_zero.empty:
            sign_consistency = float(abs(np.sign(non_zero).mean()))
            beta_positive_fraction = float((non_zero > 0).mean())

        rows.append(
            {
                "feature": feature,
                "model": model_name,
                "rank_order_hint": idx,
                "r2_oos": metrics.get("r2_oos", np.nan),
                "rmse": metrics.get("rmse", np.nan),
                "mae": metrics.get("mae", np.nan),
                "corr": metrics.get("corr", np.nan),
                "sign_accuracy": metrics.get("sign_accuracy", np.nan),
                "n_obs": metrics.get("n_obs", 0),
                "pre_2000_r2_oos": pre_r2,
                "post_2000_r2_oos": post_r2,
                "beta_sign_consistency": sign_consistency,
                "beta_positive_fraction": beta_positive_fraction,
            }
        )
        forecast_store[feature] = forecasts

    result = pd.DataFrame(rows, columns=expected_columns)
    if not result.empty:
        result = result.sort_values(["r2_oos", "corr"], ascending=False)
    _save_csv(result, output_dir / "phase1" / "univariate_screening.csv")

    top_features: List[str] = []
    if not result.empty:
        top_features = (
            result["feature"].head(config.phase1_top_n_candidates).astype(str).tolist()
        )
    top_df = pd.DataFrame({"feature": top_features})
    _save_csv(top_df, output_dir / "phase1" / "top_features.csv")
    return result, top_features, forecast_store


def run_phase_2(
    dataset: pd.DataFrame,
    config: ForecastConfig,
    level_feature_cols: Sequence[str],
    phase1_top_features: Sequence[str],
    baseline_df: pd.DataFrame,
    output_dir: Path,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    candidate_features = list(phase1_top_features) if phase1_top_features else list(level_feature_cols)
    models: Dict[str, ModelFunction] = {}
    for k in config.top_k_ols_values:
        if k <= len(candidate_features):
            models[f"phase2_topk_ols_k{k}"] = make_topk_ols_model(
                candidate_features=candidate_features,
                top_k=int(k),
                config=config,
            )
    models["phase2_ridge_all"] = make_ridge_model(level_feature_cols, config=config)
    models["phase2_elasticnet_all"] = make_elasticnet_model(level_feature_cols, config=config)

    rows: List[Dict[str, object]] = []
    forecasts: Dict[str, pd.DataFrame] = {}
    for model_name, model_fn in models.items():
        forecast_df = run_walk_forward(dataset, config, model_name, model_fn)
        forecasts[model_name] = forecast_df
        _save_csv(forecast_df, output_dir / "phase2" / f"forecasts_{model_name}.csv")
        metrics = compute_forecast_metrics(forecast_df, benchmark_df=baseline_df)
        rows.append({"model": model_name, **metrics})

    result = pd.DataFrame(rows).sort_values(["r2_oos", "corr"], ascending=False)
    _save_csv(result, output_dir / "phase2" / "metrics.csv")
    return result, forecasts


def run_phase_3(
    dataset: pd.DataFrame,
    config: ForecastConfig,
    extended_feature_cols: Sequence[str],
    baseline_df: pd.DataFrame,
    output_dir: Path,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    models = {
        "phase3_pca_regression": make_pca_regression_model(
            feature_cols=extended_feature_cols,
            config=config,
        ),
        "phase3_pls": make_pls_model(
            feature_cols=extended_feature_cols,
            config=config,
        ),
    }

    rows: List[Dict[str, object]] = []
    forecasts: Dict[str, pd.DataFrame] = {}
    for model_name, model_fn in models.items():
        forecast_df = run_walk_forward(dataset, config, model_name, model_fn)
        forecasts[model_name] = forecast_df
        _save_csv(forecast_df, output_dir / "phase3" / f"forecasts_{model_name}.csv")
        metrics = compute_forecast_metrics(forecast_df, benchmark_df=baseline_df)
        rows.append({"model": model_name, **metrics})

    result = pd.DataFrame(rows).sort_values(["r2_oos", "corr"], ascending=False)
    _save_csv(result, output_dir / "phase3" / "metrics.csv")
    return result, forecasts


def run_phase_4(
    factor_returns: pd.Series,
    forecast_by_model: Dict[str, pd.DataFrame],
    output_dir: Path,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    summary_rows: List[pd.DataFrame] = []
    details_store: Dict[str, pd.DataFrame] = {}
    for model_name, forecast_df in forecast_by_model.items():
        monthly, summary = evaluate_timing_strategies(factor_returns, forecast_df)
        if summary.empty:
            continue
        summary = summary.copy()
        summary["model"] = model_name
        summary_rows.append(summary)
        details_store[model_name] = monthly
        _save_csv(monthly, output_dir / "phase4" / f"timing_monthly_{model_name}.csv")

    if not summary_rows:
        result = pd.DataFrame()
    else:
        result = pd.concat(summary_rows, ignore_index=True).sort_values(
            ["strategy", "sharpe"], ascending=[True, False]
        )
    _save_csv(result, output_dir / "phase4" / "timing_summary.csv")
    return result, details_store


def _select_target_factors(
    matrix: pd.DataFrame,
    explicit_targets: Optional[Sequence[str]],
    max_factors: Optional[int],
) -> List[str]:
    columns = list(matrix.columns)
    if explicit_targets:
        keep = [col for col in columns if col in set(explicit_targets)]
    else:
        keep = columns
    keep = sorted(keep)
    if max_factors is not None and max_factors > 0:
        keep = keep[:max_factors]
    return keep


def _split_feature_columns(features: pd.DataFrame) -> Tuple[List[str], List[str]]:
    all_cols = [col for col in features.columns if features[col].notna().any()]
    level_cols = [col for col in all_cols if col.endswith("__lvl")]
    return level_cols, all_cols


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Forecast 12-month-ahead AQR factor returns from Open Asset Pricing predictors "
            "across Phases 0-4 (baseline, screening, multivariate, dimension reduction, timing)."
        )
    )
    parser.add_argument(
        "--aqr-factor-sets",
        nargs="+",
        default=list(DEFAULT_AQR_FACTOR_SETS),
        help="AQR factor_sets to use from factor_returns.",
    )
    parser.add_argument(
        "--target-factors",
        nargs="+",
        help="Optional explicit target columns after loading (format: factor_set::factor).",
    )
    parser.add_argument(
        "--oapd-factor-set",
        default=DEFAULT_OAPD_FACTOR_SET,
        help="Open Asset Pricing factor_set in factor_returns.",
    )
    parser.add_argument("--horizon-months", type=int, default=12)
    parser.add_argument("--label-gap-months", type=int, default=12)
    parser.add_argument("--min-train-months", type=int, default=120)
    parser.add_argument("--validation-months", type=int, default=60)
    parser.add_argument("--max-missing-fraction", type=float, default=0.30)
    parser.add_argument("--phase1-top-n-candidates", type=int, default=40)
    parser.add_argument("--max-factors", type=int, help="Optional limit on number of target factors.")
    parser.add_argument(
        "--output-dir",
        default=str(Path("analyses") / "analyses_outputs" / "aqr_oapd_forecasting"),
    )
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace) -> None:
    config = ForecastConfig(
        horizon_months=int(args.horizon_months),
        label_gap_months=int(args.label_gap_months),
        min_train_months=int(args.min_train_months),
        validation_months=int(args.validation_months),
        max_missing_fraction=float(args.max_missing_fraction),
        phase1_top_n_candidates=int(args.phase1_top_n_candidates),
    )
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    with (output_root / "run_config.json").open("w", encoding="utf-8") as file:
        json.dump(asdict(config), file, indent=2, sort_keys=True)

    engine = build_engine(get_database_config())
    aqr_matrix = load_factor_matrix(
        engine=engine,
        source="aqr",
        factor_sets=args.aqr_factor_sets,
        frequency="M",
    )
    if aqr_matrix.empty:
        raise ValueError(
            "No AQR factor returns found in `factor_returns`. Run: python -m data_fetchers.aqr factors"
        )

    oapd_predictors = load_oapd_predictors(engine, factor_set=args.oapd_factor_set)
    if oapd_predictors.empty:
        raise ValueError(
            "No Open Asset Pricing predictors found in `factor_returns`. "
            "Run: python -m data_fetchers.open_asset_pricing factors"
        )

    predictor_features = build_predictor_features(oapd_predictors)
    level_feature_cols, extended_feature_cols = _split_feature_columns(predictor_features)
    if not level_feature_cols:
        raise ValueError("No usable OAPD level predictor features found after preprocessing.")

    target_factors = _select_target_factors(
        aqr_matrix,
        explicit_targets=args.target_factors,
        max_factors=args.max_factors,
    )
    if not target_factors:
        raise ValueError("No target AQR factors selected. Check --target-factors input.")

    combined_metrics: List[pd.DataFrame] = []
    timing_metrics: List[pd.DataFrame] = []

    for factor_col in target_factors:
        factor_returns = aqr_matrix[factor_col].dropna().sort_index()
        if factor_returns.shape[0] < 180:
            print(f"[skip] {factor_col}: insufficient monthly observations ({factor_returns.shape[0]}).")
            continue

        factor_slug = _clean_series_name(factor_col)
        factor_output = output_root / factor_slug
        factor_output.mkdir(parents=True, exist_ok=True)
        print(f"[run] factor={factor_col} rows={factor_returns.shape[0]}")

        dataset = build_factor_dataset(
            factor_returns=factor_returns,
            predictor_features=predictor_features,
            horizon_months=config.horizon_months,
        )

        usable_level_cols = [col for col in level_feature_cols if col in dataset.columns]
        usable_extended_cols = [col for col in extended_feature_cols if col in dataset.columns]

        phase0_metrics, phase0_forecasts = run_phase_0(dataset, config, output_dir=factor_output)
        baseline_df = phase0_forecasts["phase0_mean"]

        phase1_metrics, top_features, phase1_forecasts = run_phase_1(
            dataset=dataset,
            config=config,
            level_feature_cols=usable_level_cols,
            baseline_df=baseline_df,
            output_dir=factor_output,
        )

        phase2_metrics, phase2_forecasts = run_phase_2(
            dataset=dataset,
            config=config,
            level_feature_cols=usable_level_cols,
            phase1_top_features=top_features,
            baseline_df=baseline_df,
            output_dir=factor_output,
        )

        phase3_metrics, phase3_forecasts = run_phase_3(
            dataset=dataset,
            config=config,
            extended_feature_cols=usable_extended_cols,
            baseline_df=baseline_df,
            output_dir=factor_output,
        )

        phase0_metrics = phase0_metrics.copy()
        phase0_metrics["phase"] = "phase0"
        if phase1_metrics.empty:
            phase1_phase_metrics = pd.DataFrame(
                columns=["model", "r2_oos", "rmse", "mae", "corr", "sign_accuracy", "n_obs"]
            )
        else:
            phase1_phase_metrics = (
                phase1_metrics[["model", "r2_oos", "rmse", "mae", "corr", "sign_accuracy", "n_obs"]]
                .head(config.phase1_top_n_candidates)
                .copy()
            )
        phase1_phase_metrics["phase"] = "phase1"

        phase2_metrics = phase2_metrics.copy()
        phase2_metrics["phase"] = "phase2"
        phase3_metrics = phase3_metrics.copy()
        phase3_metrics["phase"] = "phase3"

        factor_metrics = pd.concat(
            [phase0_metrics, phase1_phase_metrics, phase2_metrics, phase3_metrics],
            ignore_index=True,
        )
        factor_metrics["factor"] = factor_col
        combined_metrics.append(factor_metrics)
        _save_csv(factor_metrics, factor_output / "summary_model_metrics.csv")

        forecast_for_timing: Dict[str, pd.DataFrame] = {}
        forecast_for_timing.update({k: v for k, v in phase0_forecasts.items() if k != "phase0_mean"})
        forecast_for_timing.update(phase2_forecasts)
        forecast_for_timing.update(phase3_forecasts)
        if phase1_metrics.shape[0] > 0:
            top_phase1_feature = str(phase1_metrics.iloc[0]["feature"])
            top_phase1_model = f"phase1_uni::{top_phase1_feature}"
            if top_phase1_feature in phase1_forecasts:
                forecast_for_timing[top_phase1_model] = phase1_forecasts[top_phase1_feature]

        phase4_summary, _ = run_phase_4(
            factor_returns=factor_returns,
            forecast_by_model=forecast_for_timing,
            output_dir=factor_output,
        )
        if not phase4_summary.empty:
            phase4_summary["factor"] = factor_col
            timing_metrics.append(phase4_summary)

    if combined_metrics:
        all_metrics = pd.concat(combined_metrics, ignore_index=True)
        _save_csv(all_metrics, output_root / "all_factors_model_metrics.csv")
        print(f"[done] wrote model metrics: {output_root / 'all_factors_model_metrics.csv'}")

    if timing_metrics:
        all_timing = pd.concat(timing_metrics, ignore_index=True)
        _save_csv(all_timing, output_root / "all_factors_timing_metrics.csv")
        print(f"[done] wrote timing metrics: {output_root / 'all_factors_timing_metrics.csv'}")

    print("[done] pipeline completed.")


def main() -> None:
    args = parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
