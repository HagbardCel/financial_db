from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from data_fetchers.aqr_registry import FREQUENCY, SENTINELS, SOURCE


def _normalize_header(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip()


def _find_header_row(raw_df: pd.DataFrame) -> Optional[int]:
    for idx, row in raw_df.iterrows():
        first = _normalize_header(row.iloc[0]).upper()
        if first in {"DATE", "YYYYMM", "MONTH"}:
            return idx
    return None


def _parse_dates(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        return pd.to_datetime(values).dt.to_period("M").dt.to_timestamp("M")

    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any():
        as_str = numeric.fillna(0).astype(int).astype(str).str.zfill(6)
        parsed = pd.to_datetime(as_str, format="%Y%m", errors="coerce")
    else:
        text = values.astype(str).str.strip()
        parsed = pd.to_datetime(text, format="%Y%m", errors="coerce")
        if parsed.notna().sum() == 0:
            parsed = pd.to_datetime(text, errors="coerce")

    return parsed + MonthEnd(0)


def parse_aqr_sheet(raw_df: pd.DataFrame) -> pd.DataFrame:
    header_row = _find_header_row(raw_df)
    if header_row is None:
        raise ValueError("Header row with DATE/YYYYMM not found in AQR sheet.")

    raw_header = [_normalize_header(value) for value in raw_df.iloc[header_row].tolist()]
    seen: dict[str, int] = {}
    header: list[Optional[str]] = []
    for name in raw_header:
        if not name:
            header.append(None)
            continue
        if name in seen:
            seen[name] += 1
            header.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            header.append(name)

    data = raw_df.iloc[header_row + 1 :].copy()
    data.columns = header
    data = data.loc[:, [col for col in data.columns if col]]
    data = data.dropna(how="all")

    date_col = data.columns[0]
    data[date_col] = _parse_dates(data[date_col])
    data = data.dropna(subset=[date_col])

    for col in data.columns[1:]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    data.replace(list(SENTINELS), np.nan, inplace=True)
    data = data.dropna(how="all", axis=1)
    data = data.set_index(date_col)
    data.index.name = "date"
    return data


def normalize_aqr_portfolios(
    parsed_df: pd.DataFrame,
    portfolio_set: str,
    universe: str,
    frequency: str = FREQUENCY,
    source: str = SOURCE,
) -> pd.DataFrame:
    if parsed_df.empty:
        return pd.DataFrame(
            columns=[
                "source",
                "portfolio_set",
                "universe",
                "frequency",
                "portfolio",
                "date",
                "value",
                "unit",
            ]
        )

    melted = parsed_df.reset_index().melt(id_vars=["date"], var_name="portfolio", value_name="value")
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["portfolio_set"] = portfolio_set
    melted["universe"] = universe
    melted["frequency"] = frequency
    melted["unit"] = "decimal"
    return melted[
        [
            "source",
            "portfolio_set",
            "universe",
            "frequency",
            "portfolio",
            "date",
            "value",
            "unit",
        ]
    ]


def normalize_aqr_factors(
    parsed_df: pd.DataFrame,
    factor_set: str,
    frequency: str = FREQUENCY,
    source: str = SOURCE,
    sheet_label: str = "NA",
) -> pd.DataFrame:
    if parsed_df.empty:
        return pd.DataFrame(
            columns=["source", "factor_set", "frequency", "factor", "date", "value", "unit"]
        )

    melted = parsed_df.reset_index().melt(id_vars=["date"], var_name="factor", value_name="value")
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["factor_set"] = factor_set
    melted["frequency"] = frequency
    melted["unit"] = "decimal"
    sheet = (sheet_label or "NA").strip()
    melted["factor"] = melted["factor"].astype(str).map(lambda value: f"{sheet}::{value}")
    return melted[["source", "factor_set", "frequency", "factor", "date", "value", "unit"]]
