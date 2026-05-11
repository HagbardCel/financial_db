from __future__ import annotations

import logging

import pandas as pd

from data_fetchers.oil_prices import (
    EIAUSOilPriceFetcher,
    OpenBBOilSpotFetcher,
    collapse_to_month_end,
    combine_eia_us_oil_history,
    main,
    parse_eia_annual_history,
    parse_eia_monthly_history,
    parse_args,
    resolve_series,
)


ANNUAL_HTML = """
<table>
  <tr><th>Decade</th><th>Year-0</th><th>Year-1</th><th>Year-2</th><th>Year-3</th><th>Year-4</th><th>Year-5</th><th>Year-6</th><th>Year-7</th><th>Year-8</th><th>Year-9</th></tr>
  <tr><td>1950's</td><td>2.51</td><td>2.53</td><td>2.53</td><td>2.68</td><td>2.78</td><td>2.77</td><td>2.79</td><td>3.09</td><td>3.01</td><td>2.90</td></tr>
  <tr><td>1960's</td><td>2.88</td><td>2.89</td><td>2.90</td><td>2.89</td><td>2.88</td><td>2.86</td><td>2.88</td><td>2.92</td><td>2.94</td><td>3.09</td></tr>
</table>
"""

MONTHLY_HTML = """
<table>
  <tr><th>Year</th><th>Jan</th><th>Feb</th><th>Mar</th><th>Apr</th><th>May</th><th>Jun</th><th>Jul</th><th>Aug</th><th>Sep</th><th>Oct</th><th>Nov</th><th>Dec</th></tr>
  <tr><td>1974</td><td>6.95</td><td>6.87</td><td>6.77</td><td>6.77</td><td>6.87</td><td>6.85</td><td>6.80</td><td>6.71</td><td>6.70</td><td>6.97</td><td>6.97</td><td>7.09</td></tr>
  <tr><td>1975</td><td>7.61</td><td>7.47</td><td>7.57</td><td>7.55</td><td>7.52</td><td>7.49</td><td>7.75</td><td>7.73</td><td>7.75</td><td>7.83</td><td>7.80</td><td>7.93</td></tr>
</table>
"""


def test_parse_eia_annual_history_builds_year_end_close_only_rows():
    df = parse_eia_annual_history(ANNUAL_HTML)

    assert df.iloc[0].to_dict()["symbol"] == "USOIL"
    assert str(df.iloc[0]["date"]) == "1950-12-31"
    assert df.iloc[0]["open"] == df.iloc[0]["close"] == 2.51
    assert df.iloc[-1]["close"] == 3.09


def test_parse_eia_monthly_history_builds_month_end_close_only_rows():
    df = parse_eia_monthly_history(MONTHLY_HTML)

    assert str(df.iloc[0]["date"]) == "1974-01-31"
    assert str(df.iloc[11]["date"]) == "1974-12-31"
    assert df.iloc[0]["high"] == df.iloc[0]["close"] == 6.95
    assert df.iloc[0]["volume"] == 0


def test_combine_eia_us_oil_history_keeps_annual_rows_before_monthly_coverage():
    annual_df = parse_eia_annual_history(ANNUAL_HTML)
    monthly_df = parse_eia_monthly_history(MONTHLY_HTML)

    combined = combine_eia_us_oil_history(annual_df, monthly_df)

    assert str(combined.iloc[0]["date"]) == "1950-12-31"
    assert str(combined.iloc[-1]["date"]) == "1975-12-31"
    assert "1974-12-31" in combined["date"].astype(str).tolist()


def test_collapse_to_month_end_keeps_last_observation_per_month():
    df = pd.DataFrame(
        {
            "symbol": ["WTI", "WTI", "WTI"],
            "date": ["2024-01-02", "2024-01-31", "2024-02-15"],
            "open": [70.0, 71.0, 72.0],
            "high": [70.0, 71.0, 72.0],
            "low": [70.0, 71.0, 72.0],
            "close": [70.0, 71.0, 72.0],
            "volume": [0, 0, 0],
        }
    )

    collapsed = collapse_to_month_end(df)

    assert collapsed["date"].astype(str).tolist() == ["2024-01-31", "2024-02-29"]
    assert collapsed["close"].tolist() == [71.0, 72.0]


def test_eia_fetcher_combines_annual_and_monthly(monkeypatch):
    fetcher = EIAUSOilPriceFetcher(db_config={})

    monkeypatch.setattr(fetcher, "_download", lambda url, file_name: ANNUAL_HTML if "f=A" in url else MONTHLY_HTML)

    frame = fetcher.transform(fetcher.fetch())

    assert frame["symbol"].unique().tolist() == ["USOIL"]
    assert frame["date"].astype(str).min() == "1950-12-31"
    assert frame["date"].astype(str).max() == "1975-12-31"


def test_openbb_oil_fetcher_collapses_to_month_end(monkeypatch):
    sample = pd.DataFrame(
        {
            "date": ["2024-01-05", "2024-01-30", "2024-02-02"],
            "price": [71.0, 72.0, 73.0],
        }
    )

    monkeypatch.setattr("data_fetchers.oil_prices.openbb_client.fetch_dataframe", lambda path, **kwargs: sample)

    fetcher = OpenBBOilSpotFetcher(symbol="WTI", commodity="wti", db_config={})
    frame = fetcher.transform(fetcher.fetch())

    assert frame["symbol"].unique().tolist() == ["WTI"]
    assert frame["date"].astype(str).tolist() == ["2024-01-31", "2024-02-29"]
    assert frame["close"].tolist() == [72.0, 73.0]


def test_openbb_oil_fetcher_handles_named_datetime_index(monkeypatch):
    sample = pd.DataFrame(
        {
            "price": [71.0, 72.0, 73.0],
        },
        index=pd.DatetimeIndex(["2024-01-05", "2024-01-30", "2024-02-02"], name="date"),
    )

    monkeypatch.setattr("data_fetchers.oil_prices.openbb_client.fetch_dataframe", lambda path, **kwargs: sample)

    fetcher = OpenBBOilSpotFetcher(symbol="WTI", commodity="wti", db_config={})
    frame = fetcher.transform(fetcher.fetch())

    assert frame.index.name is None
    assert frame["symbol"].unique().tolist() == ["WTI"]
    assert frame["date"].astype(str).tolist() == ["2024-01-31", "2024-02-29"]
    assert frame["close"].tolist() == [72.0, 73.0]


def test_parse_args_defaults_to_all_series_and_fred_provider():
    args = parse_args([])

    assert args.series == ["USOIL", "WTI", "BRENT"]
    assert args.provider == "fred"


def test_resolve_series_filters_requested_symbols():
    series = resolve_series(["USOIL", "BRENT"])

    assert [item.symbol for item in series] == ["USOIL", "BRENT"]


def test_main_returns_nonzero_when_any_series_fails(monkeypatch):
    monkeypatch.setattr("data_fetchers.oil_prices.get_database_config", lambda: {})

    class FakeConn:
        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeDb:
        def __init__(self, config=None):
            self.conn = FakeConn()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    class FakeRepo:
        def __init__(self, db):
            self.db = db

    def fake_run_with_repository(self, repo, table_name=None):
        if getattr(self, "symbol", "USOIL") == "BRENT":
            raise RuntimeError("boom")

    monkeypatch.setattr("data_fetchers.oil_prices.DatabaseConnection", FakeDb)
    monkeypatch.setattr("data_fetchers.oil_prices.DataRepository", FakeRepo)
    monkeypatch.setattr(EIAUSOilPriceFetcher, "run_with_repository", fake_run_with_repository)
    monkeypatch.setattr(OpenBBOilSpotFetcher, "run_with_repository", fake_run_with_repository)

    assert main([]) == 1


def test_main_can_run_single_series(monkeypatch):
    monkeypatch.setattr("data_fetchers.oil_prices.get_database_config", lambda: {})

    class FakeConn:
        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeDb:
        def __init__(self, config=None):
            self.conn = FakeConn()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    class FakeRepo:
        def __init__(self, db):
            self.db = db

    seen_symbols = []

    def fake_run_with_repository(self, repo, table_name=None):
        seen_symbols.append(getattr(self, "symbol", "USOIL"))

    monkeypatch.setattr("data_fetchers.oil_prices.DatabaseConnection", FakeDb)
    monkeypatch.setattr("data_fetchers.oil_prices.DataRepository", FakeRepo)
    monkeypatch.setattr(EIAUSOilPriceFetcher, "run_with_repository", fake_run_with_repository)
    monkeypatch.setattr(OpenBBOilSpotFetcher, "run_with_repository", fake_run_with_repository)

    assert main(["--series", "USOIL"]) == 0
    assert seen_symbols == ["USOIL"]


def test_openbb_failure_mentions_fred_api_key(monkeypatch, caplog):
    monkeypatch.setattr("data_fetchers.oil_prices.get_database_config", lambda: {})

    class FakeConn:
        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeDb:
        def __init__(self, config=None):
            self.conn = FakeConn()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    class FakeRepo:
        def __init__(self, db):
            self.db = db

    def fake_run_with_repository(self, repo, table_name=None):
        raise RuntimeError("provider auth failed")

    monkeypatch.setattr("data_fetchers.oil_prices.DatabaseConnection", FakeDb)
    monkeypatch.setattr("data_fetchers.oil_prices.DataRepository", FakeRepo)
    monkeypatch.setattr(OpenBBOilSpotFetcher, "run_with_repository", fake_run_with_repository)

    with caplog.at_level(logging.ERROR):
        assert main(["--series", "WTI"]) == 1

    assert "FRED_API_KEY" in caplog.text


def test_openbb_non_auth_failure_does_not_mention_fred_api_key(monkeypatch, caplog):
    monkeypatch.setattr("data_fetchers.oil_prices.get_database_config", lambda: {})

    class FakeConn:
        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeDb:
        def __init__(self, config=None):
            self.conn = FakeConn()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    class FakeRepo:
        def __init__(self, db):
            self.db = db

    def fake_run_with_repository(self, repo, table_name=None):
        raise RuntimeError("date is both an index level and a column label")

    monkeypatch.setattr("data_fetchers.oil_prices.DatabaseConnection", FakeDb)
    monkeypatch.setattr("data_fetchers.oil_prices.DataRepository", FakeRepo)
    monkeypatch.setattr(OpenBBOilSpotFetcher, "run_with_repository", fake_run_with_repository)

    with caplog.at_level(logging.ERROR):
        assert main(["--series", "WTI"]) == 1

    assert "FRED_API_KEY" not in caplog.text
