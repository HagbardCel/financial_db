from __future__ import annotations

from typing import Dict, Tuple

SOURCE = "open_asset_pricing"
DATA_PAGE_URL = "https://www.openassetpricing.com/data/"

FACTOR_DATASETS: Dict[str, Dict[str, str]] = {
    "predictor_ls_monthly": {
        "file_id": "10sOryk_ddjkXagaajTKUk1nwJs2ZLRiI",
        "file_name": "PredictorLSretWide.csv",
        "factor_set": "oapd::predictor_ls",
        "frequency": "M",
        "data_page_label": "Monthly long-short returns of",
    },
    "predictor_ls_daily": {
        "folder_id": "1ANhiAAgqdUoxGmrCOq-F1rCgBx32PEIH",
        "file_name": "PredictorsLongShort_Daily.zip",
        "factor_set": "oapd::predictor_ls_daily",
        "frequency": "D",
        "data_page_label": "Daily portfolio returns",
        "data_page_alt_label": "csv zip files of daily returns",
    },
}

METADATA_DATASET: Dict[str, str] = {
    "file_id": "1Sev9s6cPFUGgxp1pFiej0lGzpsMqJCI2",
    "file_name": "SignalDoc.csv",
    "characteristic_set": "oapd_signals",
    "data_page_label": "Signal Documentation csv file",
}

DATE_CANDIDATES: Tuple[str, ...] = ("date", "datetime", "timestamp", "yyyymm", "yearmonth", "month", "time")
PORTFOLIO_CANDIDATES: Tuple[str, ...] = ("portfolio", "port", "bucket", "decile", "leg")
CHARACTERISTIC_CANDIDATES: Tuple[str, ...] = ("characteristic", "signal", "predictor", "anomaly", "acronym")
VALUE_CANDIDATES: Tuple[str, ...] = ("value", "score", "ret", "return")
