"""EODHD dataframe normalization helpers."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import pandas as pd

from .parquet_schema import parse_snapshot_date


def camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.replace(" ", "_").replace("-", "_").lower()


def provider_payload_json(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))


def rows_with_provider_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "provider_payload_json": provider_payload_json(row)} for row in rows]


def normalize_exchange_df(exchanges: list[dict[str, Any]], snapshot_date: str) -> pd.DataFrame:
    df = pd.DataFrame(rows_with_provider_payload(exchanges))
    if df.empty:
        return df
    df.columns = [camel_to_snake(c) for c in df.columns]
    df["snapshot_date"] = parse_snapshot_date(snapshot_date)
    df["vendor"] = "eodhd"
    return df


def normalize_symbol_df(rows: list[dict[str, Any]], *, exchange_code: str, is_delisted: bool, snapshot_date: str) -> pd.DataFrame:
    df = pd.DataFrame(rows_with_provider_payload(rows))
    if df.empty:
        return pd.DataFrame(
            columns=[
                "code",
                "name",
                "country",
                "exchange",
                "currency",
                "type",
                "isin",
                "provider_payload_json",
                "exchange_code",
                "full_symbol",
                "is_delisted",
                "snapshot_date",
                "vendor",
            ]
        )
    df.columns = [camel_to_snake(c) for c in df.columns]
    if "code" not in df.columns:
        raise RuntimeError(f"Symbol list for {exchange_code} has no code column: {list(df.columns)}")
    df["exchange_code"] = exchange_code
    df["full_symbol"] = df["code"].astype(str).str.strip() + "." + exchange_code
    df["is_delisted"] = bool(is_delisted)
    df["snapshot_date"] = parse_snapshot_date(snapshot_date)
    df["vendor"] = "eodhd"
    return df


def normalize_eod_df(
    rows: list[dict[str, Any]],
    *,
    full_symbol: str,
    exchange_code: str,
    is_delisted: bool,
    retrieved_at: dt.datetime,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    if "date" not in df.columns:
        raise RuntimeError(f"EOD payload for {full_symbol} has no date column: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        else:
            df[col] = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["volume"] = pd.to_numeric(df.get("volume", pd.Series([pd.NA] * len(df))), errors="coerce").astype("Int64")
    df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    df["vendor"] = "eodhd"
    df["full_symbol"] = full_symbol
    df["exchange_code"] = exchange_code
    df["is_delisted_from_symbol_list"] = bool(is_delisted)
    df["requested_period"] = "d"
    df["retrieved_at"] = retrieved_at
    return df[
        [
            "vendor",
            "full_symbol",
            "exchange_code",
            "date",
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "is_delisted_from_symbol_list",
            "requested_period",
            "retrieved_at",
            "provider_payload_json",
        ]
    ]


def normalize_event_df(
    rows: list[dict[str, Any]],
    *,
    full_symbol: str,
    exchange_code: str,
    is_delisted: bool,
    retrieved_at: dt.datetime,
    dataset: str,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    for col in ["date", "declaration_date", "record_date", "payment_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    for col in ["value", "unadjusted_value"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["vendor"] = "eodhd"
    df["full_symbol"] = full_symbol
    df["exchange_code"] = exchange_code
    df["dataset"] = dataset
    df["is_delisted_from_symbol_list"] = bool(is_delisted)
    df["retrieved_at"] = retrieved_at
    return df


def normalize_symbol_changes_df(rows: list[dict[str, Any]], snapshot_date: str) -> pd.DataFrame:
    columns = ["exchange", "old_symbol", "new_symbol", "company_name", "effective", "snapshot_date", "vendor", "provider_payload_json"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows_with_provider_payload(rows))
    df.columns = [camel_to_snake(c) for c in df.columns]
    aliases = {
        "exchange_code": "exchange",
        "old_ticker": "old_symbol",
        "new_ticker": "new_symbol",
        "name": "company_name",
        "date": "effective",
        "effective_date": "effective",
    }
    for source, target in aliases.items():
        if source in df.columns and target not in df.columns:
            df[target] = df[source]
    for col in columns[:5]:
        if col not in df.columns:
            df[col] = pd.NA
    df["effective"] = pd.to_datetime(df["effective"], errors="coerce").dt.date
    df["snapshot_date"] = parse_snapshot_date(snapshot_date)
    df["vendor"] = "eodhd"
    return df[columns]
