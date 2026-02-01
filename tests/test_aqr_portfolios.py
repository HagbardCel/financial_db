import pandas as pd

from data_fetchers.aqr import parse_aqr_sheet, normalize_aqr_portfolios


def test_parse_aqr_sheet_and_normalize():
    raw_df = pd.DataFrame(
        [
            ["Notes", None, None],
            ["DATE", "Lo 10", "Hi 10"],
            [192607, 1.0, 2.0],
            [192608, 3.0, -99.99],
        ]
    )

    parsed = parse_aqr_sheet(raw_df)
    assert parsed.index[0] == pd.Timestamp("1926-07-31")
    assert parsed.columns.tolist() == ["Lo 10", "Hi 10"]
    assert pd.isna(parsed.loc[pd.Timestamp("1926-08-31"), "Hi 10"])

    normalized = normalize_aqr_portfolios(parsed, "qmj_10_deciles", "USA")
    sample = normalized.loc[
        (normalized["portfolio"] == "Lo 10") & (normalized["date"] == pd.Timestamp("1926-07-31"))
    ]
    assert sample["value"].iloc[0] == 0.01
