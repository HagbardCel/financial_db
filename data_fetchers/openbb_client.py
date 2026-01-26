from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
import os

import pandas as pd


DATE_CANDIDATES = ("date", "datetime", "timestamp", "time")
VALUE_CANDIDATES = ("value", "rate", "yield", "close", "last", "price")


def get_equity_history_path() -> str:
    return os.getenv("OPENBB_EQUITY_HISTORICAL_PATH", "equity.price.historical")


def get_commodity_history_path() -> str:
    return os.getenv("OPENBB_COMMODITY_HISTORICAL_PATH", "derivatives.futures.historical")


def get_fred_series_path() -> str:
    return os.getenv("OPENBB_FRED_SERIES_PATH", "economy.fred_series")


def _get_obb():
    _sync_credentials_env()
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError(
            "OpenBB SDK is not installed. Add `openbb` to pyproject.toml."
        ) from exc
    return obb


def _sync_credentials_env() -> None:
    """Normalize provider API key env vars to OpenBB's expected names."""
    aliases = {
        "OPENBB_FRED_API_KEY": "FRED_API_KEY",
        "API_FRED_KEY": "FRED_API_KEY",
    }
    for src, dest in aliases.items():
        if os.getenv(dest):
            continue
        value = os.getenv(src)
        if value:
            os.environ[dest] = value


def _resolve_path(root: Any, path: str) -> Any:
    target = root
    for part in path.split("."):
        try:
            target = getattr(target, part)
        except AttributeError as exc:
            raise AttributeError(
                f"OpenBB path '{path}' is invalid (missing '{part}')."
            ) from exc
    return target


def _resolve_column(df: pd.DataFrame, candidates: Iterable[Optional[str]]) -> Optional[str]:
    if df.empty:
        return None
    lower_map = {col.lower(): col for col in df.columns}
    for cand in candidates:
        if not cand:
            continue
        key = cand.lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _call_openbb(path: str, **kwargs: Any) -> Any:
    func = _resolve_path(_get_obb(), path)
    filtered = {key: value for key, value in kwargs.items() if value is not None}

    try:
        return func(**filtered)
    except TypeError as exc:
        message = str(exc)
        if "provider" in filtered and "provider" in message:
            retry = dict(filtered)
            retry.pop("provider", None)
            return func(**retry)
        if "series_id" in filtered and "series_id" in message:
            retry = dict(filtered)
            retry["symbol"] = retry.pop("series_id")
            return func(**retry)
        if "symbol" in filtered and "symbol" in message:
            retry = dict(filtered)
            retry["series_id"] = retry.pop("symbol")
            return func(**retry)
        raise


def to_dataframe(result: Any) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result
    if hasattr(result, "to_df"):
        return result.to_df()
    if hasattr(result, "to_dataframe"):
        return result.to_dataframe()
    try:
        return pd.DataFrame(result)
    except Exception as exc:
        raise ValueError("OpenBB response could not be converted to a DataFrame.") from exc


def fetch_dataframe(path: str, **kwargs: Any) -> pd.DataFrame:
    return to_dataframe(_call_openbb(path, **kwargs))


def _get_date_series(df: pd.DataFrame, date_col: Optional[str] = None) -> pd.Series:
    if df.empty:
        raise ValueError("OpenBB response was empty.")

    date_col = _resolve_column(df, [date_col, *DATE_CANDIDATES])
    if date_col:
        return df[date_col]

    index = df.index
    if isinstance(index, (pd.DatetimeIndex, pd.PeriodIndex)):
        return pd.Series(index, index=index, name="date")

    index_name = getattr(index, "name", None)
    if index_name and index_name.lower() in DATE_CANDIDATES:
        return pd.Series(pd.to_datetime(index, errors="coerce"), index=index, name="date")

    if not isinstance(index, (pd.RangeIndex, pd.Int64Index)) and len(index) > 0:
        parsed = pd.to_datetime(index, errors="coerce")
        if parsed.notna().any():
            return pd.Series(parsed, index=index, name="date")

    raise ValueError(
        "No date column found in OpenBB response. "
        f"Columns: {df.columns.tolist()} | Index type: {type(index).__name__}"
    )


def _resolve_value_column(
    df: pd.DataFrame,
    date_col: Optional[str] = None,
    candidates: Iterable[str] = VALUE_CANDIDATES,
) -> str:
    value_col = _resolve_column(df, candidates)
    if value_col:
        return value_col

    excluded = {date_col} if date_col else set()
    numeric_cols = [
        col
        for col in df.columns
        if col not in excluded and pd.api.types.is_numeric_dtype(df[col])
    ]
    if numeric_cols:
        return numeric_cols[0]

    for col in df.columns:
        if col in excluded:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().any():
            return col

    raise ValueError("No numeric value column found in OpenBB response.")


def normalize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        raise ValueError("OpenBB response was empty.")

    date_series = _get_date_series(df)
    close_col = _resolve_column(df, ("close", "adj_close", "adjclose", "price", "value"))
    if not close_col:
        raise ValueError(
            "No close/price column found for OHLCV normalization. "
            f"Columns: {df.columns.tolist()}"
        )

    open_col = _resolve_column(df, ("open",)) or close_col
    high_col = _resolve_column(df, ("high",)) or close_col
    low_col = _resolve_column(df, ("low",)) or close_col
    volume_col = _resolve_column(df, ("volume", "vol"))

    normalized = pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.to_datetime(date_series).dt.date,
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": (
                pd.to_numeric(df[volume_col], errors="coerce").fillna(0).astype(int)
                if volume_col
                else 0
            ),
        }
    )

    return normalized.dropna(subset=["close"])


def normalize_rate_series(
    df: pd.DataFrame,
    maturity: str,
    region: str = "US",
    rate_type: str = "Treasury",
    currency: str = "USD",
) -> pd.DataFrame:
    if df.empty:
        return df

    date_series = _get_date_series(df)
    date_col = _resolve_column(df, [*DATE_CANDIDATES])
    value_col = _resolve_value_column(df, date_col=date_col)

    normalized = pd.DataFrame(
        {
            "date": pd.to_datetime(date_series).dt.date,
            "region": region,
            "rate_type": rate_type,
            "maturity": str(maturity),
            "interest_rate": pd.to_numeric(df[value_col], errors="coerce"),
            "currency": currency,
        }
    )

    return normalized.dropna(subset=["interest_rate"])
