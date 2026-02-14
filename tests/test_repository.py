import pandas as pd
import pytest

from db_utils.repository import DataRepository


class _FakeCursor:
    pass


class _FakeDb:
    def __init__(self):
        self.cursor = _FakeCursor()


def test_save_dataframe_rejects_invalid_table_identifier():
    repo = DataRepository(_FakeDb())
    frame = pd.DataFrame(
        {
            "id": ["x"],
            "date": [pd.Timestamp("2024-01-01")],
            "long_name": ["Series X"],
            "value": [1.0],
        }
    )

    with pytest.raises(ValueError, match="Invalid SQL table"):
        repo.save_dataframe(frame, "macro_data;DROP")


def test_save_dataframe_rejects_unknown_table_name():
    repo = DataRepository(_FakeDb())
    frame = pd.DataFrame({"id": ["x"], "date": [pd.Timestamp("2024-01-01")], "value": [1.0]})

    with pytest.raises(ValueError, match="Unknown table"):
        repo.save_dataframe(frame, "unknown_table")


def test_save_dataframe_builds_insert_sql_for_valid_table(monkeypatch):
    repo = DataRepository(_FakeDb())
    frame = pd.DataFrame(
        {
            "id": ["x"],
            "date": [pd.Timestamp("2024-01-01")],
            "long_name": ["Series X"],
            "value": [1.0],
        }
    )
    captured = {}

    def _fake_execute_values(cursor, sql, rows, page_size):
        captured["sql"] = sql
        captured["rows"] = list(rows)
        captured["page_size"] = page_size

    monkeypatch.setattr("db_utils.repository.extras.execute_values", _fake_execute_values)

    repo.save_dataframe(frame, "macro_data")

    assert captured["sql"].startswith("INSERT INTO macro_data (")
    assert "ON CONFLICT (id, date) DO UPDATE SET" in captured["sql"]
    assert len(captured["rows"]) == 1
    assert captured["page_size"] == 500
