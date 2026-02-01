import pandas as pd

from data_fetchers import openbb_client


def test_normalize_ohlcv_standard_columns():
    df = pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-02"],
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000, 1100],
        }
    )

    out = openbb_client.normalize_ohlcv(df, symbol="TEST")
    assert list(out.columns) == ["symbol", "date", "open", "high", "low", "close", "volume"]
    assert out["symbol"].unique().tolist() == ["TEST"]
    assert out.loc[0, "close"] == 101.0


def test_normalize_rate_series():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "value": [4.1, 4.2],
        }
    )

    out = openbb_client.normalize_rate_series(
        df,
        maturity="10Y",
        region="US",
        rate_type="Treasury",
        currency="USD",
    )
    assert list(out.columns) == [
        "date",
        "region",
        "rate_type",
        "maturity",
        "interest_rate",
        "currency",
    ]
    assert out.loc[0, "interest_rate"] == 4.1


def test_normalize_ohlcv_prefers_adjusted_close():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "close": [100.0, 101.0],
            "adj_close": [105.0, 106.0],
            "open": [99.0, 100.0],
            "high": [110.0, 111.0],
            "low": [98.0, 99.0],
            "volume": [1000, 1100],
        }
    )

    out = openbb_client.normalize_ohlcv(df, symbol="TEST", prefer_adjusted=True)
    assert out.loc[0, "close"] == 105.0
