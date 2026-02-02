from __future__ import annotations

import zipfile
from io import StringIO
from logging import Logger
from pathlib import Path
from typing import List, Optional

import pandas as pd

from data_fetchers.open_asset_pricing_registry import (
    CHARACTERISTIC_CANDIDATES,
    DATE_CANDIDATES,
    PORTFOLIO_CANDIDATES,
    SOURCE,
    VALUE_CANDIDATES,
)
from data_fetchers.parsing_utils import find_column, looks_like_percent, parse_dates


def parse_oapd_factors_wide(csv_text: str, frequency: str) -> pd.DataFrame:
    data = pd.read_csv(StringIO(csv_text))
    if data.empty:
        raise ValueError("Open Asset Pricing factor CSV is empty.")

    date_col = find_column(data.columns, DATE_CANDIDATES) or data.columns[0]
    data["date"] = parse_dates(data[date_col], frequency=frequency)
    data = data.dropna(subset=["date"])

    value_cols = [column for column in data.columns if column not in {date_col, "date"}]
    if not value_cols:
        raise ValueError("No factor columns found in Open Asset Pricing factors dataset.")

    for column in value_cols:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    data = data[["date", *value_cols]]
    data = data.dropna(axis=1, how="all")
    return data


def _parse_factor_zip_member(csv_text: str, member_name: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    if frame.empty:
        return pd.DataFrame(columns=["date", "factor", "value"])

    date_col = find_column(frame.columns, DATE_CANDIDATES) or frame.columns[0]
    value_col = find_column(frame.columns, VALUE_CANDIDATES)
    if not value_col:
        numeric_candidates = [
            col
            for col in frame.columns
            if col != date_col and pd.to_numeric(frame[col], errors="coerce").notna().any()
        ]
        if not numeric_candidates:
            return pd.DataFrame(columns=["date", "factor", "value"])
        value_col = numeric_candidates[0]

    factor_name = Path(member_name).stem
    parsed = pd.DataFrame(
        {
            "date": parse_dates(frame[date_col], frequency="D"),
            "factor": factor_name,
            "value": pd.to_numeric(frame[value_col], errors="coerce"),
        }
    )
    return parsed.dropna(subset=["date", "value"])


def parse_oapd_factors_zip(file_path: Path) -> pd.DataFrame:
    members: List[pd.DataFrame] = []
    with zipfile.ZipFile(file_path) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV files found in the Open Asset Pricing daily zip archive.")

        for name in csv_names:
            text = archive.read(name).decode("utf-8", errors="ignore")
            parsed = _parse_factor_zip_member(text, name)
            if not parsed.empty:
                members.append(parsed)

    if not members:
        return pd.DataFrame(columns=["date", "factor", "value"])
    return pd.concat(members, ignore_index=True)


def validate_oapd_factors(parsed: pd.DataFrame, frequency: str, logger: Optional[Logger] = None) -> None:
    if parsed.empty:
        raise ValueError("No Open Asset Pricing factor rows parsed.")

    if {"date", "factor", "value"}.issubset(parsed.columns):
        factor_count = parsed["factor"].nunique()
        duplicate_count = int(parsed.duplicated(subset=["date", "factor"]).sum())
    else:
        value_cols = [column for column in parsed.columns if column != "date"]
        factor_count = len(value_cols)
        melted = parsed.melt(id_vars=["date"], value_vars=value_cols, var_name="factor", value_name="value")
        duplicate_count = int(melted.duplicated(subset=["date", "factor"]).sum())

    if duplicate_count:
        raise ValueError(f"Duplicate Open Asset Pricing rows found for (date, factor): {duplicate_count}")

    if frequency == "M" and factor_count < 100:
        raise ValueError(
            "Unexpectedly low number of monthly Open Asset Pricing factors parsed "
            f"({factor_count} < 100). Check source file format."
        )

    min_date = pd.to_datetime(parsed["date"]).min()
    max_date = pd.to_datetime(parsed["date"]).max()
    if logger:
        logger.info(
            "Parsed Open Asset Pricing factors: %s factors, %s to %s.",
            factor_count,
            None if pd.isna(min_date) else min_date.date(),
            None if pd.isna(max_date) else max_date.date(),
        )


def normalize_oapd_factors(
    parsed: pd.DataFrame,
    factor_set: str,
    frequency: str,
    source: str = SOURCE,
) -> pd.DataFrame:
    if parsed.empty:
        return pd.DataFrame(
            columns=["source", "factor_set", "frequency", "factor", "date", "value", "unit"]
        )

    if {"date", "factor", "value"}.issubset(parsed.columns):
        long_df = parsed[["date", "factor", "value"]].copy()
    else:
        value_cols = [column for column in parsed.columns if column != "date"]
        long_df = parsed.melt(id_vars=["date"], value_vars=value_cols, var_name="factor", value_name="value")
        long_df = long_df.dropna(subset=["value"])

    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    long_df = long_df.dropna(subset=["value"])
    if looks_like_percent(long_df["value"]):
        long_df["value"] = long_df["value"] / 100.0

    long_df["source"] = source
    long_df["factor_set"] = factor_set
    long_df["frequency"] = frequency
    long_df["unit"] = "decimal"
    long_df["factor"] = long_df["factor"].astype(str).str.strip()
    long_df = long_df[long_df["factor"] != ""]
    return long_df[["source", "factor_set", "frequency", "factor", "date", "value", "unit"]]


def parse_oapd_signal_doc(csv_text: str, characteristic_set: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    if frame.empty:
        raise ValueError("SignalDoc CSV is empty.")

    characteristic_col = find_column(
        frame.columns,
        ("signalname", "predictor", "signal", "characteristic", "acronym"),
    )
    if not characteristic_col:
        raise ValueError(
            "Could not identify a characteristic identifier column in SignalDoc.csv. "
            f"Columns: {list(frame.columns)}"
        )

    name_col = find_column(frame.columns, ("signallongname", "longname", "description", "name"))
    category_col = find_column(frame.columns, ("catsignal", "category", "group"))
    paper_col = find_column(frame.columns, ("study", "paper", "citation", "reference", "ref"))
    notes_col = find_column(frame.columns, ("note", "notes", "comment", "detail", "details"))

    output = pd.DataFrame(
        {
            "source": SOURCE,
            "characteristic_set": characteristic_set,
            "characteristic": frame[characteristic_col].astype(str).str.strip(),
            "name": frame[name_col].astype(str).str.strip() if name_col else None,
            "category": frame[category_col].astype(str).str.strip() if category_col else None,
            "paper_ref": frame[paper_col].astype(str).str.strip() if paper_col else None,
            "notes": frame[notes_col].astype(str).str.strip() if notes_col else None,
        }
    )
    output["characteristic"] = output["characteristic"].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    output = output.dropna(subset=["characteristic"])

    for col in ("name", "category", "paper_ref", "notes"):
        output[col] = output[col].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})

    output = output.drop_duplicates(
        subset=["source", "characteristic_set", "characteristic"],
        keep="last",
    )
    return output[
        ["source", "characteristic_set", "characteristic", "name", "category", "paper_ref", "notes"]
    ]


def parse_portfolio_characteristics_csv(csv_text: str, frequency: str) -> pd.DataFrame:
    data = pd.read_csv(StringIO(csv_text))
    if data.empty:
        raise ValueError("Portfolio characteristics CSV is empty.")

    date_col = find_column(data.columns, DATE_CANDIDATES) or data.columns[0]
    portfolio_col = find_column(data.columns, PORTFOLIO_CANDIDATES)
    characteristic_col = find_column(data.columns, CHARACTERISTIC_CANDIDATES)
    value_col = find_column(data.columns, VALUE_CANDIDATES)

    if portfolio_col and characteristic_col and value_col:
        normalized = pd.DataFrame(
            {
                "date": parse_dates(data[date_col], frequency=frequency),
                "portfolio": data[portfolio_col].astype(str).str.strip(),
                "characteristic": data[characteristic_col].astype(str).str.strip(),
                "value": pd.to_numeric(data[value_col], errors="coerce"),
            }
        )
        return normalized.dropna(subset=["date", "portfolio", "characteristic", "value"])

    if not portfolio_col:
        raise ValueError(
            "Could not identify portfolio column in portfolio characteristic file. "
            f"Columns: {list(data.columns)}"
        )

    value_cols = [column for column in data.columns if column not in {date_col, portfolio_col}]
    if not value_cols:
        raise ValueError("No characteristic value columns found in portfolio characteristics file.")

    data["date"] = parse_dates(data[date_col], frequency=frequency)
    melted = data.melt(
        id_vars=["date", portfolio_col],
        value_vars=value_cols,
        var_name="characteristic",
        value_name="value",
    )
    melted["value"] = pd.to_numeric(melted["value"], errors="coerce")
    melted = melted.dropna(subset=["date", portfolio_col, "characteristic", "value"])
    return melted.rename(columns={portfolio_col: "portfolio"})[
        ["date", "portfolio", "characteristic", "value"]
    ]


def normalize_portfolio_characteristics(
    parsed: pd.DataFrame,
    portfolio_set: str,
    universe: str,
    frequency: str,
    unit: str,
    source: str = SOURCE,
) -> pd.DataFrame:
    if parsed.empty:
        return pd.DataFrame(
            columns=[
                "source",
                "portfolio_set",
                "universe",
                "frequency",
                "portfolio",
                "date",
                "characteristic",
                "value",
                "unit",
            ]
        )

    normalized = parsed.copy()
    normalized["source"] = source
    normalized["portfolio_set"] = portfolio_set
    normalized["universe"] = universe
    normalized["frequency"] = frequency
    normalized["unit"] = unit
    normalized = normalized.drop_duplicates(
        subset=["portfolio", "date", "characteristic"],
        keep="last",
    )
    return normalized[
        [
            "source",
            "portfolio_set",
            "universe",
            "frequency",
            "portfolio",
            "date",
            "characteristic",
            "value",
            "unit",
        ]
    ]
