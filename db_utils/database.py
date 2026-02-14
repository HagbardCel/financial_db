#!/usr/bin/env python3

from psycopg2 import pool
import pandas as pd
import re
from typing import Dict, Any, Iterable, List, Tuple, Optional, Mapping, Sequence
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine, URL
from .config import get_database_config

# Global variable to store the connection pool
_CONNECTION_POOL = None
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def init_connection_pool(config: Dict[str, str], minconn: int = 1, maxconn: int = 10):
    """Initialize the global connection pool."""
    global _CONNECTION_POOL
    if _CONNECTION_POOL is None:
        # Ensure all required keys are present
        required_keys = ['dbname', 'user', 'password']
        missing_keys = [k for k in required_keys if not config.get(k)]
        if missing_keys:
            raise ValueError(f"Missing required database config keys: {', '.join(missing_keys)}")
        
        _CONNECTION_POOL = pool.ThreadedConnectionPool(minconn, maxconn, **config)
    return _CONNECTION_POOL


def close_connection_pool() -> None:
    """Close and reset the shared connection pool."""
    global _CONNECTION_POOL
    if _CONNECTION_POOL is None:
        return
    _CONNECTION_POOL.closeall()
    _CONNECTION_POOL = None


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Validate SQL identifiers used in query assembly."""
    if not isinstance(name, str) or not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL {kind}: {name!r}")
    return name


def where_eq(column: str, param: str) -> str:
    return f"{validate_identifier(column, 'column')} = :{validate_identifier(param, 'param')}"


def where_any(column: str, param: str) -> str:
    return f"{validate_identifier(column, 'column')} = ANY(:{validate_identifier(param, 'param')})"


def where_between(column: str, start_param: str, end_param: str) -> str:
    col = validate_identifier(column, "column")
    start = validate_identifier(start_param, "param")
    end = validate_identifier(end_param, "param")
    return f"{col} BETWEEN :{start} AND :{end}"


def order_by_clause(column: str, descending: bool = False) -> str:
    direction = "DESC" if descending else "ASC"
    return f"{validate_identifier(column, 'column')} {direction}"


def build_select_query(
    table: str,
    columns: Sequence[str] | Mapping[str, str],
    where: Optional[Sequence[str]] = None,
    order_by: Optional[Sequence[str]] = None,
    limit_param: Optional[str] = None,
) -> str:
    """
    Build a SELECT query while validating all dynamic SQL identifiers.
    Supports:
    - columns as list[str]
    - columns as mapping[source_column -> alias]
    - wildcard columns=['*'] for browse/export use cases
    """
    table_name = validate_identifier(table, "table")

    select_parts: List[str] = []
    if isinstance(columns, Mapping):
        if not columns:
            raise ValueError("columns mapping cannot be empty")
        for source_col, alias in columns.items():
            source = validate_identifier(source_col, "column")
            alias_name = validate_identifier(alias, "alias")
            select_parts.append(f"{source} AS {alias_name}")
    else:
        column_list = list(columns)
        if not column_list:
            raise ValueError("columns list cannot be empty")
        if column_list == ["*"]:
            select_parts = ["*"]
        else:
            select_parts = [validate_identifier(col, "column") for col in column_list]

    query = f"SELECT {', '.join(select_parts)} FROM {table_name}"
    if where:
        query += " WHERE " + " AND ".join(where)
    if order_by:
        query += " ORDER BY " + ", ".join(order_by)
    if limit_param:
        limit_key = validate_identifier(limit_param, "param")
        query += f" LIMIT :{limit_key}"
    return query

class DatabaseConnection:
    def __init__(self, config: Optional[Dict[str, str]] = None):
        """
        Initialize the database connection.
        
        Args:
            config: Optional dictionary with database connection parameters.
                   If not provided, it will be read from environment variables.
        """
        self.config = config or get_database_config()
        self.conn = None
        self.cursor = None
        self.pool = None

    def connect(self):
        """Get a connection from the pool."""
        global _CONNECTION_POOL
        if not self.config:
            raise ValueError("Database configuration not provided")
        
        if _CONNECTION_POOL is None:
            init_connection_pool(self.config)
        
        self.pool = _CONNECTION_POOL
        self.conn = self.pool.getconn()
        self.cursor = self.conn.cursor()

    def disconnect(self):
        """Return the connection to the pool."""
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn and self.pool:
            self.pool.putconn(self.conn)
            self.conn = None

    def __enter__(self):
        """Context manager entry point."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        if exc_type:
            if self.conn:
                self.conn.rollback()
        else:
            if self.conn:
                self.conn.commit()
        self.disconnect()


def build_engine(config: Optional[Dict[str, str]] = None) -> Engine:
    """Create a SQLAlchemy engine using the shared database configuration."""
    config = config or get_database_config()
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


def read_sql_expanding(
    engine: Engine,
    query: str,
    params: Optional[Dict[str, Any]] = None,
    expanding: Optional[List[str]] = None,
) -> pd.DataFrame:
    stmt = text(query)
    if expanding:
        for key in expanding:
            stmt = stmt.bindparams(bindparam(key, expanding=True))
    return pd.read_sql(stmt, engine, params=params)


def read_table(
    engine: Engine,
    table: str,
    columns: List[str],
    where: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    order_by: Optional[Iterable[str]] = None,
    expanding: Optional[List[str]] = None,
) -> pd.DataFrame:
    order_by_clauses = None
    if order_by:
        order_by_clauses = [order_by_clause(col) for col in order_by]
    query = build_select_query(
        table=table,
        columns=columns,
        where=[where] if where else None,
        order_by=order_by_clauses,
    )

    if expanding:
        return read_sql_expanding(engine, query, params=params, expanding=expanding)
    return read_sql(engine, query, params=params)


def list_distinct(
    engine: Engine,
    table: str,
    id_col: str,
    label_col: Optional[str] = None,
) -> pd.DataFrame:
    if label_col:
        query = build_select_query(
            table=table,
            columns={id_col: "id", label_col: "label"},
            order_by=[order_by_clause(id_col)],
        )
    else:
        query = build_select_query(
            table=table,
            columns={id_col: "id"},
            order_by=[order_by_clause(id_col)],
        )
    query = query.replace("SELECT ", "SELECT DISTINCT ", 1)
    return read_sql(engine, query)


def get_date_bounds(
    engine: Engine,
    table: str,
    date_col: str,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    validated_table = validate_identifier(table, "table")
    validated_date_col = validate_identifier(date_col, "column")
    query = (
        f"SELECT MIN({validated_date_col}) AS min_date, "
        f"MAX({validated_date_col}) AS max_date "
        f"FROM {validated_table}"
    )
    df = read_sql(engine, query)
    min_date = df.loc[0, "min_date"]
    max_date = df.loc[0, "max_date"]
    if pd.isna(min_date) or pd.isna(max_date):
        return None, None
    return min_date, max_date


def get_table_stats(engine: Engine, table: str, date_col: str) -> Dict[str, Any]:
    validated_table = validate_identifier(table, "table")
    validated_date_col = validate_identifier(date_col, "column")
    query = (
        f"SELECT COUNT(*) AS row_count, MIN({validated_date_col}) AS min_date, "
        f"MAX({validated_date_col}) AS max_date "
        f"FROM {validated_table}"
    )
    df = read_sql(engine, query)
    return {
        "row_count": int(df.loc[0, "row_count"]),
        "min_date": df.loc[0, "min_date"],
        "max_date": df.loc[0, "max_date"],
    }
