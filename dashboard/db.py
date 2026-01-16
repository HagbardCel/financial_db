from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

from db_utils.config import get_database_config


def build_engine() -> Engine:
    config = get_database_config()
    url = URL.create(
        "postgresql+psycopg2",
        username=config["user"],
        password=config["password"],
        host=config["host"],
        port=int(config["port"]),
        database=config["dbname"],
    )
    return create_engine(url, pool_pre_ping=True)


def read_sql(engine: Engine, query: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    return pd.read_sql(text(query), engine, params=params)


def list_distinct(
    engine: Engine,
    table: str,
    id_col: str,
    label_col: Optional[str] = None,
) -> pd.DataFrame:
    if label_col:
        query = f"""
            SELECT DISTINCT {id_col} AS id, {label_col} AS label
            FROM {table}
            ORDER BY {id_col}
        """
    else:
        query = f"""
            SELECT DISTINCT {id_col} AS id
            FROM {table}
            ORDER BY {id_col}
        """
    return read_sql(engine, query)


def get_date_bounds(
    engine: Engine,
    table: str,
    date_col: str,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    query = f"""
        SELECT MIN({date_col}) AS min_date, MAX({date_col}) AS max_date
        FROM {table}
    """
    df = read_sql(engine, query)
    min_date = df.loc[0, "min_date"]
    max_date = df.loc[0, "max_date"]
    if pd.isna(min_date) or pd.isna(max_date):
        return None, None
    return min_date, max_date


def get_table_stats(engine: Engine, table: str, date_col: str) -> Dict[str, Any]:
    query = f"""
        SELECT COUNT(*) AS row_count, MIN({date_col}) AS min_date, MAX({date_col}) AS max_date
        FROM {table}
    """
    df = read_sql(engine, query)
    return {
        "row_count": int(df.loc[0, "row_count"]),
        "min_date": df.loc[0, "min_date"],
        "max_date": df.loc[0, "max_date"],
    }
