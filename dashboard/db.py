from __future__ import annotations

"""Compatibility layer for dashboard database helpers.

Prefer importing from db_utils.database directly.
"""

from db_utils.database import (
    build_engine,
    get_date_bounds,
    get_table_stats,
    list_distinct,
    read_sql,
)

__all__ = [
    "build_engine",
    "get_date_bounds",
    "get_table_stats",
    "list_distinct",
    "read_sql",
]
