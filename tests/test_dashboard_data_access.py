import pandas as pd
import pytest
from sqlalchemy import create_engine

import dashboard.data_access as da


@pytest.fixture(autouse=True)
def clear_data_access_caches():
    cached_functions = [
        da.list_series_ids,
        da.get_table_bounds,
        da.get_dataset_bounds,
        da.get_table_stats,
        da.list_distinct_values,
        da.get_factor_frequencies,
        da.get_factor_sets,
        da.get_factor_options,
        da.get_factor_bounds,
        da.get_rate_dimensions,
        da.get_rate_maturities,
    ]
    for fn in cached_functions:
        clear_fn = getattr(fn, "clear", None)
        if callable(clear_fn):
            clear_fn()
    yield


def _capture_read_sql(monkeypatch, frame: pd.DataFrame):
    captured = {}

    def _fake_read_sql(engine, query, params=None):
        captured["engine"] = engine
        captured["query"] = query
        captured["params"] = params
        return frame.copy()

    monkeypatch.setattr(da.db, "read_sql", _fake_read_sql)
    return captured


def test_build_label_map_without_label_column():
    frame = pd.DataFrame({"id": ["A", "B"]})
    assert da.build_label_map(frame) == {"A": "A", "B": "B"}


def test_build_label_map_with_label_column():
    frame = pd.DataFrame({"id": ["A"], "label": ["Alpha"]})
    assert da.build_label_map(frame) == {"A": "A - Alpha"}


def test_parse_factor_options():
    options = ["ff3::Mkt-RF", "ff3::SMB"]
    assert da.parse_factor_options(options) == [("ff3", "Mkt-RF"), ("ff3", "SMB")]


def test_parse_factor_options_rejects_invalid_format():
    with pytest.raises(ValueError):
        da.parse_factor_options(["invalid"])


def test_engine_cache_key_uses_url():
    engine = create_engine("sqlite://")
    assert da._engine_cache_key(engine).startswith("sqlite")


def test_dataset_registries_cover_expected_contracts():
    for registry in [da.PRICE_DATASETS, da.SERIES_DATASETS, da.COMPARE_DATASETS]:
        assert registry
        for dataset in registry.values():
            assert dataset.table
            assert dataset.id_col
            assert dataset.date_col
            assert dataset.value_col

    assert "Shiller Derived" in da.COMPARE_DATASETS
    assert "Factor Returns" in da.BROWSER_DATASETS
    assert da.BROWSER_DATASETS["Factor Returns"].filters == (
        "source",
        "factor_set",
        "frequency",
        "factor",
        "unit",
    )


def test_fetch_value_series_builds_macro_query_with_id_and_date_filters(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame({"date": ["2020-01-31"], "id": ["cpi"], "value": [100.0]})
    captured = _capture_read_sql(monkeypatch, frame)

    result = da.fetch_value_series(
        engine,
        da.SERIES_DATASETS["Macro Data"],
        ids=["cpi"],
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert captured["query"] == (
        "SELECT date AS date, id AS id, value AS value FROM macro_data "
        "WHERE id = ANY(:ids) AND date BETWEEN :start_date AND :end_date "
        "ORDER BY date ASC"
    )
    assert captured["params"] == {
        "ids": ["cpi"],
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
    }
    assert list(result.columns) == ["date", "id", "value"]


def test_fetch_ohlcv_series_builds_price_query_with_symbol_and_date_filters(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame(
        {
            "date": ["2020-01-31"],
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [1000],
        }
    )
    captured = _capture_read_sql(monkeypatch, frame)

    result = da.fetch_ohlcv_series(
        engine,
        da.PRICE_DATASETS["Stock Prices"],
        symbol="SPY",
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert captured["query"] == (
        "SELECT date, open, high, low, close, volume FROM stock_prices "
        "WHERE symbol = :symbol AND date BETWEEN :start_date AND :end_date "
        "ORDER BY date ASC"
    )
    assert captured["params"] == {
        "symbol": "SPY",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
    }
    assert list(result.columns) == ["date", "open", "high", "low", "close", "volume"]


def test_get_rate_maturities_builds_dimension_filter_query(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame({"maturity": ["1Y", "2Y"]})
    captured = _capture_read_sql(monkeypatch, frame)

    maturities = da.get_rate_maturities(engine, region="US", rate_type="gov", currency="USD")

    assert captured["query"] == (
        "SELECT DISTINCT maturity AS maturity FROM interest_rates "
        "WHERE region = :region AND rate_type = :rate_type AND currency = :currency "
        "ORDER BY maturity ASC"
    )
    assert captured["params"] == {"region": "US", "rate_type": "gov", "currency": "USD"}
    assert maturities == ["1Y", "2Y"]


def test_get_factor_options_applies_frequency_and_factor_set_filters(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame(
        {
            "factor_set": ["ff3", "mom"],
            "factor": ["SMB", "MOM"],
        }
    )
    captured = _capture_read_sql(monkeypatch, frame)

    options = da.get_factor_options(engine, frequency="M", factor_sets=("ff3", "mom"))

    assert captured["query"] == (
        "SELECT DISTINCT factor_set AS factor_set, factor AS factor FROM factor_returns "
        "WHERE frequency = :frequency AND factor_set = ANY(:sets) "
        "ORDER BY factor_set ASC, factor ASC"
    )
    assert captured["params"] == {"frequency": "M", "sets": ["ff3", "mom"]}
    assert options == ["ff3::SMB", "mom::MOM"]


def test_get_factor_bounds_applies_filters_and_returns_date_tuple(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame({"min_date": [pd.Timestamp("2020-01-31")], "max_date": [pd.Timestamp("2020-12-31")]})
    captured = _capture_read_sql(monkeypatch, frame)

    min_date, max_date = da.get_factor_bounds(engine, frequency="M", factor_sets=("ff3",))

    assert captured["query"] == (
        "SELECT MIN(date) AS min_date, MAX(date) AS max_date "
        "FROM factor_returns "
        "WHERE frequency = :frequency AND factor_set = ANY(:sets)"
    )
    assert captured["params"] == {"frequency": "M", "sets": ["ff3"]}
    assert min_date == pd.Timestamp("2020-01-31")
    assert max_date == pd.Timestamp("2020-12-31")


def test_fetch_factor_data_builds_pair_and_date_filters(monkeypatch):
    engine = create_engine("sqlite://")
    frame = pd.DataFrame(
        {
            "date": ["2020-01-31"],
            "factor_set": ["ff3"],
            "factor": ["SMB"],
            "value": [0.02],
        }
    )
    captured = _capture_read_sql(monkeypatch, frame)

    result = da.fetch_factor_data(
        engine,
        frequency="M",
        options=["ff3::SMB", "mom::MOM"],
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert captured["query"] == (
        "SELECT date, factor_set, factor, value FROM factor_returns "
        "WHERE frequency = :frequency AND date BETWEEN :start_date AND :end_date "
        "AND ((factor_set = :set_0 AND factor = :factor_0) OR (factor_set = :set_1 AND factor = :factor_1)) "
        "ORDER BY date ASC"
    )
    assert captured["params"] == {
        "frequency": "M",
        "set_0": "ff3",
        "factor_0": "SMB",
        "set_1": "mom",
        "factor_1": "MOM",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
    }
    assert list(result.columns) == ["date", "factor_set", "factor", "value"]


def test_fetch_factor_data_without_date_range_omits_between_clause(monkeypatch):
    engine = create_engine("sqlite://")
    captured = _capture_read_sql(
        monkeypatch,
        pd.DataFrame({"date": [], "factor_set": [], "factor": [], "value": []}),
    )

    da.fetch_factor_data(engine, frequency="M", options=["ff3::SMB"])

    assert "date BETWEEN :start_date AND :end_date" not in captured["query"]
    assert captured["params"] == {
        "frequency": "M",
        "set_0": "ff3",
        "factor_0": "SMB",
    }


def test_fetch_factor_data_requires_non_empty_options():
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="options must contain at least one factor option"):
        da.fetch_factor_data(engine, frequency="M", options=[])
