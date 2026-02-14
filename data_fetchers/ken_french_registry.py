from __future__ import annotations

from typing import Dict

SOURCE = "ken_french"
FREQUENCY = "M"

SENTINELS = {-99.99, -999.0, -999, -99.999}

DATASETS = {
    "ff3": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors.zip",
        ],
        "column_map": {
            "MKT-RF": "Mkt-RF",
            "SMB": "SMB",
            "HML": "HML",
            "RF": "RF",
        },
    },
    "ff5": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3.zip",
        ],
        "column_map": {
            "MKT-RF": "Mkt-RF",
            "SMB": "SMB",
            "HML": "HML",
            "RMW": "RMW",
            "CMA": "CMA",
            "RF": "RF",
        },
    },
    "mom": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor.zip",
        ],
        "column_map": {
            "MOM": "UMD",
            "UMD": "UMD",
        },
    },
}

PORTFOLIO_DATASETS: Dict[str, Dict[str, object]] = {
    "10_Portfolios_Formed_on_BE-ME": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Portfolios_Formed_on_BE-ME_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_BE-ME_CSV.zip",
        ],
    },
    "10_Portfolios_Formed_on_OP": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Portfolios_Formed_on_OP_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_OP_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Portfolios_Formed_on_Operating_Profitability_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_Operating_Profitability_CSV.zip",
        ],
    },
    "10_Portfolios_Formed_on_Momentum": {
        "urls": [
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Prior_12_2_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_Prior_12_2_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_Prior_2-12_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Portfolios_Formed_on_Prior_12_2_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Formed_on_Momentum_CSV.zip",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Portfolios_Formed_on_Momentum_CSV.zip",
        ],
    },
}
