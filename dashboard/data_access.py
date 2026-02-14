from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy.engine import Engine

from db_utils import database as db


@dataclass(frozen=True)
class SeriesDataset:
    table: str
    id_col: str
    date_col: str
    value_col: str
    label_col: Optional[str] = None


@dataclass(frozen=True)
class BrowserDataset:
    table: str
    date_col: str
    id_col: Optional[str] = None
    filters: Tuple[str, ...] = ()


PRICE_DATASETS: Dict[str, SeriesDataset] = {
    "Stock Prices": SeriesDataset(
        table="stock_prices",
        id_col="symbol",
        date_col="date",
        value_col="close",
    ),
    "Commodity Prices": SeriesDataset(
        table="commodity_prices",
        id_col="symbol",
        date_col="date",
        value_col="close",
    ),
}

SERIES_DATASETS: Dict[str, SeriesDataset] = {
    "Assets Prices": SeriesDataset(
        table="assets_prices",
        id_col="id",
        date_col="date",
        value_col="price_usd",
    ),
    "Commodity Prices (Close)": SeriesDataset(
        table="commodity_prices",
        id_col="symbol",
        date_col="date",
        value_col="close",
    ),
    "Indices": SeriesDataset(
        table="indices",
        id_col="id",
        date_col="date",
        value_col="value",
        label_col="index_name",
    ),
    "Macro Data": SeriesDataset(
        table="macro_data",
        id_col="id",
        date_col="date",
        value_col="value",
        label_col="long_name",
    ),
}

COMPARE_DATASETS: Dict[str, SeriesDataset] = {
    "Assets Prices": SERIES_DATASETS["Assets Prices"],
    "Indices": SERIES_DATASETS["Indices"],
    "Macro Data": SERIES_DATASETS["Macro Data"],
    "Commodity Prices (Close)": SERIES_DATASETS["Commodity Prices (Close)"],
    "Shiller Derived": SeriesDataset(
        table="shiller_derived_view",
        id_col="id",
        date_col="date",
        value_col="value",
        label_col="long_name",
    ),
}

BROWSER_DATASETS: Dict[str, BrowserDataset] = {
    "Assets Prices": BrowserDataset(table="assets_prices", date_col="date", id_col="id"),
    "Indices": BrowserDataset(table="indices", date_col="date", id_col="id"),
    "Stock Prices": BrowserDataset(table="stock_prices", date_col="date", id_col="symbol"),
    "Commodity Prices": BrowserDataset(table="commodity_prices", date_col="date", id_col="symbol"),
    "Macro Data": BrowserDataset(table="macro_data", date_col="date", id_col="id"),
    "Interest Rates": BrowserDataset(
        table="interest_rates",
        date_col="date",
        filters=("region", "rate_type", "maturity", "currency"),
    ),
    "Factor Returns": BrowserDataset(
        table="factor_returns",
        date_col="date",
        filters=("source", "factor_set", "frequency", "factor", "unit"),
    ),
    "Shiller Derived View": BrowserDataset(table="shiller_derived_view", date_col="date", id_col="id"),
}

OVERVIEW_TABLES: Dict[str, str] = {
    "Assets Prices": "assets_prices",
    "Indices": "indices",
    "Stock Prices": "stock_prices",
    "Commodity Prices": "commodity_prices",
    "Interest Rates": "interest_rates",
    "Macro Data": "macro_data",
    "Factor Returns": "factor_returns",
    "Shiller Derived View": "shiller_derived_view",
}

FACTOR_TABLE = "factor_returns"
FACTOR_FREQ_LABELS: Mapping[str, str] = {"M": "Monthly", "D": "Daily"}


def build_label_map(df: pd.DataFrame) -> Dict[str, str]:
    if "label" in df.columns:
        return {row["id"]: f"{row['id']} - {row['label']}" for _, row in df.iterrows()}
    return {row["id"]: row["id"] for _, row in df.iterrows()}


def list_series_ids(engine: Engine, dataset: SeriesDataset) -> pd.DataFrame:
    return db.list_distinct(engine, dataset.table, dataset.id_col, dataset.label_col)


def get_table_bounds(engine: Engine, table: str, date_col: str = "date"):
    return db.get_date_bounds(engine, table, date_col)


def get_dataset_bounds(engine: Engine, dataset: SeriesDataset):
    return db.get_date_bounds(engine, dataset.table, dataset.date_col)


def fetch_value_series(
    engine: Engine,
    dataset: SeriesDataset,
    ids: Sequence[str],
    start_date: Any,
    end_date: Any,
) -> pd.DataFrame:
    query = db.build_select_query(
        table=dataset.table,
        columns={
            dataset.date_col: "date",
            dataset.id_col: "id",
            dataset.value_col: "value",
        },
        where=[
            db.where_any(dataset.id_col, "ids"),
            db.where_between(dataset.date_col, "start_date", "end_date"),
        ],
        order_by=[db.order_by_clause(dataset.date_col)],
    )
    return db.read_sql(
        engine,
        query,
        params={"ids": list(ids), "start_date": start_date, "end_date": end_date},
    )


def fetch_ohlcv_series(
    engine: Engine,
    dataset: SeriesDataset,
    symbol: str,
    start_date: Any,
    end_date: Any,
) -> pd.DataFrame:
    query = db.build_select_query(
        table=dataset.table,
        columns=["date", "open", "high", "low", "close", "volume"],
        where=[
            db.where_eq(dataset.id_col, "symbol"),
            db.where_between(dataset.date_col, "start_date", "end_date"),
        ],
        order_by=[db.order_by_clause(dataset.date_col)],
    )
    return db.read_sql(
        engine,
        query,
        params={"symbol": symbol, "start_date": start_date, "end_date": end_date},
    )


def list_distinct_values(
    engine: Engine,
    table: str,
    column: str,
) -> list[str]:
    return db.list_distinct(engine, table, column)["id"].tolist()


def parse_factor_options(options: Sequence[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in options:
        factor_set, factor = value.split("::", 1)
        pairs.append((factor_set, factor))
    return pairs


def get_factor_frequencies(engine: Engine) -> list[str]:
    query = db.build_select_query(
        table=FACTOR_TABLE,
        columns={"frequency": "frequency"},
        order_by=[db.order_by_clause("frequency")],
    )
    query = query.replace("SELECT ", "SELECT DISTINCT ", 1)
    df = db.read_sql(engine, query)
    return df["frequency"].tolist() if not df.empty else []


def get_factor_sets(engine: Engine, frequency: str) -> list[str]:
    query = db.build_select_query(
        table=FACTOR_TABLE,
        columns={"factor_set": "factor_set"},
        where=[db.where_eq("frequency", "frequency")],
        order_by=[db.order_by_clause("factor_set")],
    )
    query = query.replace("SELECT ", "SELECT DISTINCT ", 1)
    df = db.read_sql(engine, query, params={"frequency": frequency})
    return df["factor_set"].tolist() if not df.empty else []


def get_factor_options(engine: Engine, frequency: str, factor_sets: Optional[Sequence[str]] = None) -> list[str]:
    where = [db.where_eq("frequency", "frequency")]
    params: Dict[str, Any] = {"frequency": frequency}
    if factor_sets:
        where.append(db.where_any("factor_set", "sets"))
        params["sets"] = list(factor_sets)

    query = db.build_select_query(
        table=FACTOR_TABLE,
        columns={"factor_set": "factor_set", "factor": "factor"},
        where=where,
        order_by=[db.order_by_clause("factor_set"), db.order_by_clause("factor")],
    )
    query = query.replace("SELECT ", "SELECT DISTINCT ", 1)
    df = db.read_sql(engine, query, params=params)
    if df.empty:
        return []
    return [f"{row['factor_set']}::{row['factor']}" for _, row in df.iterrows()]


def get_factor_bounds(
    engine: Engine,
    frequency: str,
    factor_sets: Optional[Sequence[str]] = None,
):
    where = [db.where_eq("frequency", "frequency")]
    params: Dict[str, Any] = {"frequency": frequency}
    if factor_sets:
        where.append(db.where_any("factor_set", "sets"))
        params["sets"] = list(factor_sets)

    where_clause = " AND ".join(where)
    query = (
        "SELECT MIN(date) AS min_date, MAX(date) AS max_date "
        f"FROM {FACTOR_TABLE} "
        f"WHERE {where_clause}"
    )
    frame = db.read_sql(engine, query, params=params)
    if frame.empty:
        return None, None
    min_date = frame.loc[0, "min_date"]
    max_date = frame.loc[0, "max_date"]
    if pd.isna(min_date) or pd.isna(max_date):
        return None, None
    return min_date, max_date


def fetch_factor_data(
    engine: Engine,
    frequency: str,
    options: Sequence[str],
    start_date: Any | None = None,
    end_date: Any | None = None,
) -> pd.DataFrame:
    pairs = parse_factor_options(options)
    params: Dict[str, Any] = {"frequency": frequency}
    pair_clauses = []
    for idx, (factor_set, factor) in enumerate(pairs):
        set_key = f"set_{idx}"
        factor_key = f"factor_{idx}"
        params[set_key] = factor_set
        params[factor_key] = factor
        pair_clauses.append(
            f"({db.where_eq('factor_set', set_key)} AND {db.where_eq('factor', factor_key)})"
        )

    where = [db.where_eq("frequency", "frequency"), f"({' OR '.join(pair_clauses)})"]
    if start_date is not None and end_date is not None:
        where.insert(1, db.where_between("date", "start_date", "end_date"))
        params["start_date"] = start_date
        params["end_date"] = end_date

    query = db.build_select_query(
        table=FACTOR_TABLE,
        columns=["date", "factor_set", "factor", "value"],
        where=where,
        order_by=[db.order_by_clause("date")],
    )
    return db.read_sql(engine, query, params=params)
