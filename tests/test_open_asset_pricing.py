import pandas as pd

from data_fetchers.open_asset_pricing import (
    _extract_data_page_drive_link,
    _parse_drive_folder_id,
    normalize_oapd_factors,
    normalize_portfolio_characteristics,
    parse_oapd_factors_wide,
    parse_oapd_signal_doc,
    parse_portfolio_characteristics_csv,
)


def test_parse_oapd_monthly_factors_and_normalize_decimal():
    text = "\n".join(
        [
            "yyyymm,acc,bm",
            "196301,1.2,-0.5",
            "196302,0.8,1.1",
        ]
    )
    parsed = parse_oapd_factors_wide(text, frequency="M")
    assert parsed["date"].iloc[0] == pd.Timestamp("1963-01-31")

    normalized = normalize_oapd_factors(parsed, factor_set="oapd::predictor_ls", frequency="M")
    sample = normalized.loc[
        (normalized["factor"] == "acc") & (normalized["date"] == pd.Timestamp("1963-01-31"))
    ]
    assert sample["value"].iloc[0] == 0.012


def test_parse_signal_doc_maps_columns():
    text = "\n".join(
        [
            "SignalName,SignalLongName,Cat.Signal,Study,Notes",
            "acc,Accruals,Investment,Sloan 1996,example note",
        ]
    )
    parsed = parse_oapd_signal_doc(text, characteristic_set="oapd_signals")
    assert parsed.shape[0] == 1
    assert parsed["characteristic"].iloc[0] == "acc"
    assert parsed["name"].iloc[0] == "Accruals"
    assert parsed["category"].iloc[0] == "Investment"
    assert parsed["paper_ref"].iloc[0] == "Sloan 1996"


def test_parse_portfolio_characteristics_wide_and_normalize():
    text = "\n".join(
        [
            "date,portfolio,acc,bm",
            "1963-01-31,Lo,0.1,0.2",
            "1963-01-31,Hi,0.3,0.4",
        ]
    )
    parsed = parse_portfolio_characteristics_csv(text, frequency="M")
    assert {"date", "portfolio", "characteristic", "value"} == set(parsed.columns)

    normalized = normalize_portfolio_characteristics(
        parsed,
        portfolio_set="oapd::portfolio_characteristics",
        universe="NA",
        frequency="M",
        unit="raw",
    )
    sample = normalized.loc[
        (normalized["portfolio"] == "Lo")
        & (normalized["characteristic"] == "bm")
        & (normalized["date"] == pd.Timestamp("1963-01-31"))
    ]
    assert sample["value"].iloc[0] == 0.2


def test_extract_data_page_drive_link_by_label():
    html = """
    <ul>
      <li><a href="https://drive.google.com/file/d/AAA111/view?usp=sharing">Monthly long-short returns of 239 predictors (wide csv)</a></li>
      <li><a href="https://drive.google.com/file/d/BBB222/view?usp=sharing">Signal Documentation csv file</a></li>
    </ul>
    """
    monthly = _extract_data_page_drive_link(html, "Monthly long-short returns of")
    metadata = _extract_data_page_drive_link(html, "Signal Documentation csv file")
    assert monthly == "https://drive.google.com/file/d/AAA111/view?usp=sharing"
    assert metadata == "https://drive.google.com/file/d/BBB222/view?usp=sharing"


def test_parse_drive_folder_id():
    folder_url = "https://drive.google.com/drive/folders/1ANhiAAgqdUoxGmrCOq-F1rCgBx32PEIH?usp=sharing"
    assert _parse_drive_folder_id(folder_url) == "1ANhiAAgqdUoxGmrCOq-F1rCgBx32PEIH"
