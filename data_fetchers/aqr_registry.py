from __future__ import annotations

from typing import Dict

SOURCE = "aqr"
FREQUENCY = "M"
SENTINELS = {-99.99, -999.0, -999, -99.999}

PORTFOLIO_DATASETS: Dict[str, Dict[str, object]] = {
    "qmj_10_deciles": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-10-QualitySorted-Portfolios-Monthly.xlsx",
        "sheets": ["10 Portfolios Formed on Quality"],
        "universe_label": "NA",
    },
    "qmj_6_size_quality": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Six-Portfolios-Formed-on-Size-and-Quality-Monthly.xlsx",
        "sheets": [],
    },
    "vme_portfolios": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Value-and-Momentum-Everywhere-Portfolios-Monthly.xlsx",
        "sheets": [],
    },
    "momentum_indices": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Momentum-Indices-Monthly.xlsx",
        "sheets": [],
    },
}

FACTOR_DATASETS: Dict[str, Dict[str, object]] = {
    "qmj_factors": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Monthly.xlsx",
        "sheets": [],
    },
    "vme_factors": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Value-and-Momentum-Everywhere-Factors-Monthly.xlsx",
        "sheets": [],
    },
}
