from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
import requests
from pandas.tseries.offsets import MonthEnd

from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config

SOURCE = "ken_french"
FREQUENCY = "M"

SENTINELS = {-99.99, -999.0, -999, -99.999}

DATASETS = {
    "ff3": {
        "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors.zip",
        "column_map": {
            "MKT-RF": "Mkt-RF",
            "SMB": "SMB",
            "HML": "HML",
            "RF": "RF",
        },
    },
    "ff5": {
        "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3.zip",
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
        "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor.zip",
        "column_map": {
            "MOM": "UMD",
            "UMD": "UMD",
        },
    },
}


def _select_csv_name(names: Iterable[str]) -> str:
    csv_names = [name for name in names if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("No CSV file found in the Ken French zip archive.")
    non_daily = [name for name in csv_names if "daily" not in name.lower()]
    return non_daily[0] if non_daily else csv_names[0]


def _is_header(tokens: List[str], column_keys: set[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0].upper()
    if first in {"DATE", "YEAR", "YYYYMM"}:
        return any(token.upper() in column_keys for token in tokens[1:])
    if not tokens[0][0].isdigit():
        return any(token.upper() in column_keys for token in tokens)
    return False


def parse_ken_french_monthly(text: str, column_map: Dict[str, str]) -> pd.DataFrame:
    lines = text.splitlines()
    column_keys = set(column_map.keys())
    column_indices: List[int] = []
    column_names: List[str] = []
    data_rows: List[List[str]] = []

    for line in lines:
        tokens = line.strip().replace(",", " ").split()
        if not tokens:
            if data_rows:
                break
            continue

        if _is_header(tokens, column_keys):
            column_indices = []
            column_names = []
            for idx, token in enumerate(tokens[1:]):
                key = token.upper()
                if key in column_map:
                    column_indices.append(idx)
                    column_names.append(column_map[key])
            continue

        if tokens[0].isdigit() and len(tokens[0]) == 6:
            if not column_indices:
                continue
            row = [tokens[0]]
            for idx in column_indices:
                value_idx = 1 + idx
                row.append(tokens[value_idx] if value_idx < len(tokens) else None)
            data_rows.append(row)
            continue

        if data_rows:
            break

    if not data_rows:
        raise ValueError("No monthly data found in Ken French dataset.")

    df = pd.DataFrame(data_rows, columns=["date"] + column_names)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m") + MonthEnd(0)
    for col in column_names:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace(list(SENTINELS), np.nan, inplace=True)
    return df


class FamaFrenchFactorsFetcher(BaseFetcher):
    def __init__(
        self,
        dataset_keys: Iterable[str],
        cache_dir: Path,
        refresh: bool = False,
        db_config: dict | None = None,
    ):
        super().__init__(db_config)
        self.dataset_keys = list(dataset_keys)
        self.cache_dir = cache_dir
        self.refresh = refresh

    def _download_zip(self, key: str) -> Path:
        dataset = DATASETS[key]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.cache_dir / f"{key}.zip"

        if zip_path.exists() and not self.refresh:
            self.logger.info("Using cached file for %s", key)
            return zip_path

        self.logger.info("Downloading %s", dataset["url"])
        response = requests.get(dataset["url"], timeout=30)
        response.raise_for_status()
        zip_path.write_bytes(response.content)
        return zip_path

    def _load_dataset_text(self, zip_path: Path) -> str:
        with zipfile.ZipFile(zip_path) as archive:
            csv_name = _select_csv_name(archive.namelist())
            return archive.read(csv_name).decode("utf-8", errors="ignore")

    def fetch(self) -> Dict[str, str]:
        payloads: Dict[str, str] = {}
        for key in self.dataset_keys:
            zip_path = self._download_zip(key)
            payloads[key] = self._load_dataset_text(zip_path)
        return payloads

    def transform(self, raw_data: Dict[str, str]) -> pd.DataFrame:
        frames = []
        for key, text in raw_data.items():
            dataset = DATASETS[key]
            parsed = parse_ken_french_monthly(text, dataset["column_map"])
            melted = parsed.melt(id_vars=["date"], var_name="factor", value_name="value")
            melted = melted.dropna(subset=["value"])
            melted["value"] = melted["value"] / 100.0
            melted["source"] = SOURCE
            melted["factor_set"] = key
            melted["frequency"] = FREQUENCY
            melted["unit"] = "decimal"
            frames.append(melted)

        if not frames:
            return pd.DataFrame(
                columns=["source", "factor_set", "frequency", "factor", "date", "value", "unit"]
            )
        df = pd.concat(frames, ignore_index=True)
        return df[["source", "factor_set", "frequency", "factor", "date", "value", "unit"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Fama-French monthly factor returns.")
    parser.add_argument(
        "--sets",
        nargs="+",
        default=["ff3", "ff5", "mom"],
        choices=sorted(DATASETS.keys()),
        help="Factor sets to ingest.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(Path("derived") / "ken_french"),
        help="Directory to cache downloaded zip files.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload source files even if cached.",
    )
    args = parser.parse_args()

    fetcher = FamaFrenchFactorsFetcher(
        dataset_keys=args.sets,
        cache_dir=Path(args.cache_dir),
        refresh=args.refresh,
        db_config=get_database_config(),
    )
    fetcher.run(table_name="factor_returns")


if __name__ == "__main__":
    main()
