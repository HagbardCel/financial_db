from pathlib import Path

import pandas as pd

from data_fetchers.fama_french_factors import DATASETS, parse_ken_french_monthly


def test_parse_ff3_monthly_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ff3_monthly_sample.csv"
    text = fixture_path.read_text()
    df = parse_ken_french_monthly(text, DATASETS["ff3"]["column_map"])

    assert list(df.columns) == ["date", "Mkt-RF", "SMB", "HML", "RF"]
    assert len(df) == 7
    assert df["date"].iloc[0] == pd.Timestamp("1926-07-31")

    sentinel_row = df.loc[df["date"] == pd.Timestamp("1927-01-31")]
    assert sentinel_row.shape[0] == 1
    assert pd.isna(sentinel_row["Mkt-RF"].iloc[0])
