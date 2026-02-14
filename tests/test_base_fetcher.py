import pandas as pd
import pytest

from data_fetchers.base_fetcher import BaseFetcher


class _DummyFetcher(BaseFetcher):
    def __init__(self, transformed):
        super().__init__(db_config={})
        self._transformed = transformed

    def fetch(self):
        return {"raw": True}

    def transform(self, raw_data):
        return self._transformed


class _FakeRepository:
    def __init__(self):
        self.saved = []

    def save_dataframe(self, df, table_name):
        self.saved.append((table_name, len(df)))


def test_run_with_repository_single_dataframe():
    df = pd.DataFrame({"id": ["x"], "date": [pd.Timestamp("2024-01-01")], "value": [1.0]})
    fetcher = _DummyFetcher(df)
    repo = _FakeRepository()

    fetcher.run_with_repository(repo, table_name="macro_data")

    assert repo.saved == [("macro_data", 1)]


def test_run_with_repository_multi_table_dict():
    transformed = {
        "macro_data": pd.DataFrame({"id": ["x"], "date": [pd.Timestamp("2024-01-01")], "value": [1.0]}),
        "test_data": pd.DataFrame(columns=["id", "date", "value"]),
    }
    fetcher = _DummyFetcher(transformed)
    repo = _FakeRepository()

    fetcher.run_with_repository(repo)

    assert repo.saved == [("macro_data", 1)]


def test_run_with_repository_requires_table_for_single_dataframe():
    df = pd.DataFrame({"id": ["x"], "date": [pd.Timestamp("2024-01-01")], "value": [1.0]})
    fetcher = _DummyFetcher(df)
    repo = _FakeRepository()

    with pytest.raises(ValueError, match="table_name must be provided"):
        fetcher.run_with_repository(repo)
