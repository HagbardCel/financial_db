"""Parquet dtype policy for the EODHD archive.

Forward-only: new writes enforce Arrow types (date32 for calendar dates, float64 OHLC,
UTC timestamps for retrieved_at). Existing archive files may still use legacy string dates
until refreshed. Postgres ingestion remains stricter (NUMERIC/DATE/TIMESTAMPTZ) on load.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATE_COLUMNS = frozenset(
    {
        "date",
        "snapshot_date",
        "effective",
        "declaration_date",
        "record_date",
        "payment_date",
    }
)
FLOAT_COLUMNS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "value",
        "unadjusted_value",
    }
)
BOOL_COLUMNS = frozenset({"is_delisted", "is_delisted_from_symbol_list"})
STRING_COLUMNS = frozenset(
    {
        "vendor",
        "full_symbol",
        "exchange_code",
        "requested_period",
        "provider_payload_json",
        "dataset",
        "exchange",
        "old_symbol",
        "new_symbol",
        "company_name",
        "code",
        "name",
        "country",
        "currency",
        "type",
        "isin",
        "request_type_filter",
        "split",
        "period",
        "operating_mic",
        "country_iso2",
        "country_iso3",
    }
)

EOD_DAILY_COLUMNS = (
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
)

SYMBOL_CHANGES_COLUMNS = (
    "exchange",
    "old_symbol",
    "new_symbol",
    "company_name",
    "effective",
    "snapshot_date",
    "vendor",
    "provider_payload_json",
)

SCHEMAS: dict[str, pa.Schema] = {
    "eod_daily": pa.schema(
        [
            ("vendor", pa.string()),
            ("full_symbol", pa.string()),
            ("exchange_code", pa.string()),
            ("date", pa.date32()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("adjusted_close", pa.float64()),
            ("volume", pa.int64()),
            ("is_delisted_from_symbol_list", pa.bool_()),
            ("requested_period", pa.string()),
            ("retrieved_at", pa.timestamp("ns", tz="UTC")),
            ("provider_payload_json", pa.string()),
        ]
    ),
    "symbol_changes": pa.schema(
        [
            ("exchange", pa.string()),
            ("old_symbol", pa.string()),
            ("new_symbol", pa.string()),
            ("company_name", pa.string()),
            ("effective", pa.date32()),
            ("snapshot_date", pa.date32()),
            ("vendor", pa.string()),
            ("provider_payload_json", pa.string()),
        ]
    ),
}


def parse_snapshot_date(value: str | dt.date | dt.datetime) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid snapshot_date: {value!r}")
    return parsed.date()


def _coerce_date_column(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _coerce_timestamp_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _coerce_string_column(series: pd.Series) -> pd.Series:
    return series.astype("string[pyarrow]")


def _coerce_float_column(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("float64")


def _coerce_int_column(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _coerce_bool_column(series: pd.Series) -> pd.Series:
    return series.astype("boolean")


def _coerce_column(series: pd.Series, column: str) -> pd.Series:
    if column in DATE_COLUMNS:
        return _coerce_date_column(series)
    if column == "retrieved_at":
        return _coerce_timestamp_utc(series)
    if column in FLOAT_COLUMNS:
        return _coerce_float_column(series)
    if column == "volume":
        return _coerce_int_column(series)
    if column in BOOL_COLUMNS:
        return _coerce_bool_column(series)
    if column in STRING_COLUMNS or column == "provider_payload_json":
        return _coerce_string_column(series)
    if series.dtype == object:
        return series.astype("string[pyarrow]")
    return series


def _arrow_type_for_column(column: str) -> pa.DataType:
    if column in DATE_COLUMNS:
        return pa.date32()
    if column == "retrieved_at":
        return pa.timestamp("ns", tz="UTC")
    if column in FLOAT_COLUMNS:
        return pa.float64()
    if column == "volume":
        return pa.int64()
    if column in BOOL_COLUMNS:
        return pa.bool_()
    return pa.string()


def schema_for_dataframe(df: pd.DataFrame) -> pa.Schema:
    return pa.schema([(column, _arrow_type_for_column(column)) for column in df.columns])


def coerce_dataframe(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for column in out.columns:
        out[column] = _coerce_column(out[column], column)
    if dataset == "eod_daily":
        for column in ("open", "high", "low", "close", "adjusted_close"):
            if column not in out.columns:
                out[column] = pd.Series(float("nan"), index=out.index, dtype="float64")
        if "volume" not in out.columns:
            out["volume"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        return out[list(EOD_DAILY_COLUMNS)]
    if dataset == "symbol_changes":
        return out[list(SYMBOL_CHANGES_COLUMNS)]
    return out


def table_for_write(df: pd.DataFrame, dataset: str) -> pa.Table:
    if df.empty and dataset in SCHEMAS:
        return SCHEMAS[dataset].empty_table()
    coerced = coerce_dataframe(df, dataset)
    if dataset in SCHEMAS:
        return pa.Table.from_pandas(coerced, schema=SCHEMAS[dataset], preserve_index=False)
    return pa.Table.from_pandas(coerced, schema=schema_for_dataframe(coerced), preserve_index=False)


def write_parquet_table(table: pa.Table, path: Any, *, compression: str = "zstd") -> None:
    pq.write_table(table, path, compression=compression)
