from __future__ import annotations

import re
from typing import Iterable, Optional

import pandas as pd
from pandas.tseries.offsets import MonthEnd


def normalize_token(value: object) -> str:
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def find_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    normalized = {normalize_token(col): col for col in columns}
    for candidate in candidates:
        key = normalize_token(candidate)
        if key in normalized:
            return normalized[key]

    for candidate in candidates:
        key = normalize_token(candidate)
        for normalized_name, original in normalized.items():
            if key and key in normalized_name:
                return original
    return None


def parse_dates(values: pd.Series, frequency: str) -> pd.Series:
    text = values.astype(str).str.strip()
    date_values = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")

    mask_yyyymm = text.str.fullmatch(r"\d{6}")
    if mask_yyyymm.any():
        date_values.loc[mask_yyyymm] = pd.to_datetime(
            text.loc[mask_yyyymm], format="%Y%m", errors="coerce"
        )

    mask_yyyymmdd = text.str.fullmatch(r"\d{8}")
    if mask_yyyymmdd.any():
        date_values.loc[mask_yyyymmdd] = pd.to_datetime(
            text.loc[mask_yyyymmdd], format="%Y%m%d", errors="coerce"
        )

    unresolved = date_values.isna()
    if unresolved.any():
        date_values.loc[unresolved] = pd.to_datetime(text.loc[unresolved], errors="coerce")

    if frequency == "M":
        return date_values + MonthEnd(0)
    return date_values.dt.normalize()


def looks_like_percent(series: pd.Series, threshold_quantile: float = 0.95, threshold_value: float = 0.50) -> bool:
    clean = series.dropna().abs()
    if clean.empty:
        return False
    return float(clean.quantile(threshold_quantile)) > threshold_value
