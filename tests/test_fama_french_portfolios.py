from pathlib import Path

import pandas as pd

from data_fetchers.ken_french import (
    parse_ken_french_portfolios_monthly,
    normalize_ken_french_portfolios,
)


def test_parse_ken_french_portfolios_monthly_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ff_deciles_sample.csv"
    text = fixture_path.read_text()
    df = parse_ken_french_portfolios_monthly(text)

    assert list(df.columns[:3]) == ["date", "Lo 10", "2"]
    assert df["date"].iloc[0] == pd.Timestamp("1926-07-31")
    assert pd.isna(df.loc[df["date"] == pd.Timestamp("1926-08-31"), "Lo 10"]).iloc[0]


def test_normalize_ken_french_portfolios_decimal():
    fixture_path = Path(__file__).parent / "fixtures" / "ff_deciles_sample.csv"
    text = fixture_path.read_text()
    df = parse_ken_french_portfolios_monthly(text)
    normalized = normalize_ken_french_portfolios(df, "10_Portfolios_Formed_on_BE-ME")

    sample = normalized.loc[
        (normalized["portfolio"] == "Hi 10")
        & (normalized["date"] == pd.Timestamp("1926-07-31"))
    ]
    assert sample["value"].iloc[0] == 0.10
