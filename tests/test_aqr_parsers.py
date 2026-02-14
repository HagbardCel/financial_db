import pandas as pd
import pytest

from data_fetchers.aqr_parsers import (
    normalize_aqr_factors,
    normalize_aqr_portfolios,
    parse_aqr_sheet,
)


def test_parse_aqr_sheet_handles_duplicate_headers_and_sentinels():
    raw_df = pd.DataFrame(
        [
            ["Metadata", None, None, None],
            ["DATE", "Lo 10", "Lo 10", "Hi 10"],
            [192607, 1.0, 2.0, 3.0],
            [192608, -99.99, 4.0, 5.0],
        ]
    )

    parsed = parse_aqr_sheet(raw_df)

    assert parsed.columns.tolist() == ["Lo 10", "Lo 10_1", "Hi 10"]
    assert parsed.index[0] == pd.Timestamp("1926-07-31")
    assert pd.isna(parsed.loc[pd.Timestamp("1926-08-31"), "Lo 10"])


def test_parse_aqr_sheet_requires_date_header():
    raw_df = pd.DataFrame([["Notes", "A"], ["Still notes", "B"]])
    with pytest.raises(ValueError, match="Header row with DATE/YYYYMM not found"):
        parse_aqr_sheet(raw_df)


def test_normalize_aqr_factors_adds_sheet_prefix_and_decimal_values():
    parsed = pd.DataFrame(
        {"QMJ": [1.5], "BAB": [2.0]},
        index=[pd.Timestamp("2020-01-31")],
    )
    parsed.index.name = "date"

    normalized = normalize_aqr_factors(parsed, factor_set="qmj_factors", sheet_label="USA")
    assert normalized["factor"].tolist() == ["USA::QMJ", "USA::BAB"]
    assert normalized["value"].tolist() == [0.015, 0.02]


def test_normalize_aqr_portfolios_preserves_required_columns():
    parsed = pd.DataFrame({"Lo 10": [1.0]}, index=[pd.Timestamp("2020-01-31")])
    parsed.index.name = "date"
    normalized = normalize_aqr_portfolios(parsed, "qmj_10_deciles", "NA")
    assert list(normalized.columns) == [
        "source",
        "portfolio_set",
        "universe",
        "frequency",
        "portfolio",
        "date",
        "value",
        "unit",
    ]
