from __future__ import annotations

from io import StringIO
from typing import Dict, List

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from data_fetchers.ken_french_registry import FREQUENCY, SENTINELS, SOURCE


def _is_csv_header(tokens: List[str], column_keys: set[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0].upper()
    if first in {"", "DATE", "YEAR", "YYYYMM"}:
        return any(token.upper() in column_keys for token in tokens[1:])
    return any(token.upper() in column_keys for token in tokens)


def _is_date_token(token: str) -> bool:
    value = token.strip()
    if not value:
        return False
    if value.isdigit():
        return len(value) in {6, 8}
    if len(value) in {7, 10} and value[4] == "-":
        return True
    return False


def _parse_monthly_date(value: str) -> pd.Timestamp:
    text = str(value).strip()
    if not text:
        return pd.NaT
    if text.isdigit():
        if len(text) == 6:
            return pd.to_datetime(text, format="%Y%m", errors="coerce")
        if len(text) == 8:
            return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce")


def parse_ken_french_monthly(text: str, column_map: Dict[str, str]) -> pd.DataFrame:
    lines = text.splitlines()
    column_keys = set(column_map.keys())
    column_positions: List[int] = []
    column_names: List[str] = []
    data_rows: List[List[str]] = []

    for line in lines:
        raw_line = line.strip()
        if not raw_line:
            if data_rows:
                break
            continue

        tokens = [tok.strip() for tok in line.split(",")]
        if tokens:
            tokens[0] = tokens[0].lstrip("\ufeff")

        if _is_csv_header(tokens, column_keys):
            column_positions = []
            column_names = []
            start_idx = 1 if tokens and tokens[0].upper() in {"", "DATE", "YEAR", "YYYYMM"} else 0
            for idx, token in enumerate(tokens[start_idx:], start=start_idx):
                key = token.upper()
                if key in column_map:
                    column_positions.append(idx)
                    column_names.append(column_map[key])
            continue

        if tokens and _is_date_token(tokens[0]):
            if not column_positions:
                continue
            row = [tokens[0]]
            for pos in column_positions:
                row.append(tokens[pos] if pos < len(tokens) else None)
            data_rows.append(row)
            continue

        if data_rows:
            break

    if not data_rows:
        raise ValueError("No monthly data found in Ken French dataset.")

    df = pd.DataFrame(data_rows, columns=["date"] + column_names)
    df["date"] = df["date"].apply(_parse_monthly_date) + MonthEnd(0)
    for col in column_names:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace(list(SENTINELS), np.nan, inplace=True)
    return df


def _find_portfolio_header_line(lines: List[str]) -> int:
    for idx, line in enumerate(lines):
        tokens = [tok.strip() for tok in line.split(",")]
        if tokens:
            tokens[0] = tokens[0].lstrip("\ufeff")
        if not tokens or all(not tok for tok in tokens):
            continue

        first = tokens[0].upper()
        upper_tokens = [tok.upper() for tok in tokens if tok]

        if first in {"", "DATE", "YYYYMM"} and len(upper_tokens) > 1:
            return idx

        if any("LO 10" in tok or "HI 10" in tok for tok in upper_tokens):
            if not tokens[0].strip().isdigit():
                return idx

    raise ValueError("No header line found for Ken French portfolio data.")


def parse_ken_french_portfolios_monthly(text: str) -> pd.DataFrame:
    lines = [line.strip() for line in text.splitlines()]
    header_idx = _find_portfolio_header_line(lines)
    header_line = lines[header_idx]

    data_rows: List[str] = []
    for line in lines[header_idx + 1 :]:
        if not line:
            if data_rows:
                break
            continue
        if line.lower().startswith("annual"):
            break
        first = line.split(",")[0].strip()
        if not (first.isdigit() and len(first) == 6):
            break
        data_rows.append(line)

    if not data_rows:
        raise ValueError("No monthly data rows found in Ken French portfolio dataset.")

    df = pd.read_csv(StringIO("\n".join([header_line] + data_rows)))
    df.columns = [str(col).strip() for col in df.columns]

    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col].astype(str), format="%Y%m", errors="coerce")
    df[date_col] = df[date_col] + MonthEnd(0)
    df = df.dropna(subset=[date_col])

    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace(list(SENTINELS), np.nan, inplace=True)
    return df.rename(columns={date_col: "date"})


def normalize_ken_french_portfolios(
    parsed_df: pd.DataFrame,
    portfolio_set: str,
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

    melted = parsed_df.melt(id_vars=["date"], var_name="portfolio", value_name="value")
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["portfolio_set"] = portfolio_set
    melted["universe"] = "NA"
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
