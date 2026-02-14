from pathlib import Path

import pandas as pd

from data_fetchers.ken_french_parsers import (
    normalize_ken_french_portfolios,
    parse_ken_french_monthly,
    parse_ken_french_portfolios_monthly,
)
from data_fetchers.ken_french_registry import DATASETS


def test_parse_ken_french_monthly_from_fixture_direct_module():
    fixture_path = Path(__file__).parent / "fixtures" / "ff3_monthly_sample.csv"
    text = fixture_path.read_text()
    df = parse_ken_french_monthly(text, DATASETS["ff3"]["column_map"])
    assert list(df.columns) == ["date", "Mkt-RF", "SMB", "HML", "RF"]
    assert df["date"].iloc[0] == pd.Timestamp("1926-07-31")


def test_parse_ken_french_portfolios_monthly_and_normalize_direct_module():
    text = "\n".join(
        [
            "Header line",
            ",Lo 10,Hi 10",
            "192607,1.0,2.0",
            "192608,3.0,4.0",
            "",
        ]
    )
    parsed = parse_ken_french_portfolios_monthly(text)
    normalized = normalize_ken_french_portfolios(parsed, portfolio_set="10_Portfolios_Formed_on_BE-ME")

    assert list(parsed.columns) == ["date", "Lo 10", "Hi 10"]
    assert normalized["portfolio"].tolist() == ["Lo 10", "Lo 10", "Hi 10", "Hi 10"]
    assert normalized["value"].tolist()[0] == 0.01
