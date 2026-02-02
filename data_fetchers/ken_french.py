from __future__ import annotations

import argparse
import zipfile
from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers.download_utils import download_first_available_url, use_cached_file
from db_utils.config import get_database_config

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


def _select_csv_name(names: Iterable[str]) -> str:
    csv_names = [name for name in names if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("No CSV file found in the Ken French zip archive.")
    non_daily = [name for name in csv_names if "daily" not in name.lower()]
    return non_daily[0] if non_daily else csv_names[0]


def _load_csv_from_zip(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        csv_name = _select_csv_name(archive.namelist())
        return archive.read(csv_name).decode("utf-8", errors="ignore")


def _is_csv_header(tokens: List[str], column_keys: set[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0].upper()
    if first in {"", "DATE", "YEAR", "YYYYMM"}:
        return any(token.upper() in column_keys for token in tokens[1:])
    return any(token.upper() in column_keys for token in tokens)


def _is_date_token(token: str) -> bool:
    value = token.strip()
    if not value:
        return False
    if value.isdigit():
        return len(value) in {6, 8}
    if len(value) in {7, 10} and value[4] == "-":
        return True
    return False


def _parse_monthly_date(value: str) -> pd.Timestamp:
    text = str(value).strip()
    if not text:
        return pd.NaT
    if text.isdigit():
        if len(text) == 6:
            return pd.to_datetime(text, format="%Y%m", errors="coerce")
        if len(text) == 8:
            return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce")


def parse_ken_french_monthly(text: str, column_map: Dict[str, str]) -> pd.DataFrame:
    lines = text.splitlines()
    column_keys = set(column_map.keys())
    column_positions: List[int] = []
    column_names: List[str] = []
    data_rows: List[List[str]] = []

    for line in lines:
        raw_line = line.strip()
        if not raw_line:
            if data_rows:
                break
            continue

        tokens = [tok.strip() for tok in line.split(",")]
        if tokens:
            tokens[0] = tokens[0].lstrip("\ufeff")

        if _is_csv_header(tokens, column_keys):
            column_positions = []
            column_names = []
            start_idx = 1 if tokens and tokens[0].upper() in {"", "DATE", "YEAR", "YYYYMM"} else 0
            for idx, token in enumerate(tokens[start_idx:], start=start_idx):
                key = token.upper()
                if key in column_map:
                    column_positions.append(idx)
                    column_names.append(column_map[key])
            continue

        if tokens and _is_date_token(tokens[0]):
            if not column_positions:
                continue
            row = [tokens[0]]
            for pos in column_positions:
                row.append(tokens[pos] if pos < len(tokens) else None)
            data_rows.append(row)
            continue

        if data_rows:
            break

    if not data_rows:
        raise ValueError("No monthly data found in Ken French dataset.")

    df = pd.DataFrame(data_rows, columns=["date"] + column_names)
    df["date"] = df["date"].apply(_parse_monthly_date) + MonthEnd(0)
    for col in column_names:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace(list(SENTINELS), np.nan, inplace=True)
    return df


def _download_ken_french_zip(urls: Iterable[str], zip_path: Path, refresh: bool, logger) -> Path:
    if use_cached_file(zip_path, refresh, logger):
        return zip_path

    attempted = list(urls)
    for url in attempted:
        logger.info("Downloading %s", url)
    download_first_available_url(attempted, zip_path, timeout=30)
    return zip_path


def _find_portfolio_header_line(lines: List[str]) -> int:
    for idx, line in enumerate(lines):
        tokens = [tok.strip() for tok in line.split(",")]
        if tokens:
            tokens[0] = tokens[0].lstrip("\ufeff")
        if not tokens or all(not tok for tok in tokens):
            continue

        first = tokens[0].upper()
        upper_tokens = [tok.upper() for tok in tokens if tok]

        if first in {"", "DATE", "YYYYMM"} and len(upper_tokens) > 1:
            return idx

        if any("LO 10" in tok or "HI 10" in tok for tok in upper_tokens):
            if not tokens[0].strip().isdigit():
                return idx

    raise ValueError("No header line found for Ken French portfolio data.")


def _load_portfolios_csv_from_zip(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV file found in the Ken French zip archive.")

        candidates = [
            name
            for name in csv_names
            if all(token not in name.lower() for token in ("daily", "annual", "weekly"))
        ]
        if not candidates:
            candidates = csv_names

        last_error: Exception | None = None
        for name in candidates:
            text = archive.read(name).decode("utf-8", errors="ignore")
            try:
                parse_ken_french_portfolios_monthly(text)
            except Exception as exc:
                last_error = exc
                continue
            return text

    if last_error:
        raise last_error
    raise ValueError("No suitable monthly portfolio CSV found in the Ken French zip archive.")


def parse_ken_french_portfolios_monthly(text: str) -> pd.DataFrame:
    lines = [line.strip() for line in text.splitlines()]
    header_idx = _find_portfolio_header_line(lines)
    header_line = lines[header_idx]

    data_rows: List[str] = []
    for line in lines[header_idx + 1 :]:
        if not line:
            if data_rows:
                break
            continue
        if line.lower().startswith("annual"):
            break
        first = line.split(",")[0].strip()
        if not (first.isdigit() and len(first) == 6):
            break
        data_rows.append(line)

    if not data_rows:
        raise ValueError("No monthly data rows found in Ken French portfolio dataset.")

    df = pd.read_csv(StringIO("\n".join([header_line] + data_rows)))
    df.columns = [str(col).strip() for col in df.columns]

    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col].astype(str), format="%Y%m", errors="coerce")
    df[date_col] = df[date_col] + MonthEnd(0)
    df = df.dropna(subset=[date_col])

    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace(list(SENTINELS), np.nan, inplace=True)
    return df.rename(columns={date_col: "date"})


def normalize_ken_french_portfolios(
    parsed_df: pd.DataFrame,
    portfolio_set: str,
    frequency: str = FREQUENCY,
    source: str = SOURCE,
) -> pd.DataFrame:
    if parsed_df.empty:
        return pd.DataFrame(
            columns=[
                "source",
                "portfolio_set",
                "universe",
                "frequency",
                "portfolio",
                "date",
                "value",
                "unit",
            ]
        )

    melted = parsed_df.melt(id_vars=["date"], var_name="portfolio", value_name="value")
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["portfolio_set"] = portfolio_set
    melted["universe"] = "NA"
    melted["frequency"] = frequency
    melted["unit"] = "decimal"
    return melted[
        [
            "source",
            "portfolio_set",
            "universe",
            "frequency",
            "portfolio",
            "date",
            "value",
            "unit",
        ]
    ]


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
        urls = dataset.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return _download_ken_french_zip(urls, zip_path, self.refresh, self.logger)

    def _load_dataset_text(self, zip_path: Path) -> str:
        return _load_csv_from_zip(zip_path)

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


class KenFrenchPortfoliosFetcher(BaseFetcher):
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
        dataset = PORTFOLIO_DATASETS[key]
        zip_path = self.cache_dir / f"{key}.zip"
        urls = dataset.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return _download_ken_french_zip(urls, zip_path, self.refresh, self.logger)

    def _load_dataset_text(self, zip_path: Path) -> str:
        return _load_portfolios_csv_from_zip(zip_path)

    def fetch(self) -> Dict[str, str]:
        payloads: Dict[str, str] = {}
        for key in self.dataset_keys:
            zip_path = self._download_zip(key)
            payloads[key] = self._load_dataset_text(zip_path)
        return payloads

    def transform(self, raw_data: Dict[str, str]) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        for key, text in raw_data.items():
            parsed = parse_ken_french_portfolios_monthly(text)
            frames.append(normalize_ken_french_portfolios(parsed, key))

        if not frames:
            return pd.DataFrame(
                columns=[
                    "source",
                    "portfolio_set",
                    "universe",
                    "frequency",
                    "portfolio",
                    "date",
                    "value",
                    "unit",
                ]
            )
        return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Ken French datasets.")
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["all", "factors", "portfolios"],
        help="What to fetch (default: all).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload source files even if cached.",
    )
    parser.add_argument(
        "--factors-sets",
        nargs="+",
        default=["ff3", "ff5", "mom"],
        choices=sorted(DATASETS.keys()),
        help="Factor sets to ingest.",
    )
    parser.add_argument(
        "--portfolios-sets",
        nargs="+",
        default=list(PORTFOLIO_DATASETS.keys()),
        choices=sorted(PORTFOLIO_DATASETS.keys()),
        help="Portfolio datasets to ingest.",
    )
    parser.add_argument(
        "--factors-cache-dir",
        default=str(Path("derived") / "ken_french"),
        help="Directory to cache downloaded factor zip files.",
    )
    parser.add_argument(
        "--portfolios-cache-dir",
        default=str(Path("derived") / "ken_french_portfolios"),
        help="Directory to cache downloaded portfolio zip files.",
    )
    parser.add_argument(
        "--sets",
        nargs="+",
        help="Alias for --factors-sets (command=factors) or --portfolios-sets (command=portfolios).",
    )
    parser.add_argument(
        "--cache-dir",
        help="Alias for --factors-cache-dir (command=factors) or --portfolios-cache-dir (command=portfolios).",
    )

    args = parser.parse_args()
    db_config = get_database_config()

    if args.sets:
        if args.command == "factors":
            args.factors_sets = args.sets
        elif args.command == "portfolios":
            args.portfolios_sets = args.sets
        else:
            raise ValueError("--sets is ambiguous for command=all. Use --factors-sets/--portfolios-sets.")

    if args.cache_dir:
        if args.command == "factors":
            args.factors_cache_dir = args.cache_dir
        elif args.command == "portfolios":
            args.portfolios_cache_dir = args.cache_dir
        else:
            raise ValueError("--cache-dir is ambiguous for command=all. Use --factors-cache-dir/--portfolios-cache-dir.")

    if args.command in {"all", "factors"}:
        fetcher = FamaFrenchFactorsFetcher(
            dataset_keys=args.factors_sets,
            cache_dir=Path(args.factors_cache_dir),
            refresh=args.refresh,
            db_config=db_config,
        )
        fetcher.run(table_name="factor_returns")

    if args.command in {"all", "portfolios"}:
        fetcher = KenFrenchPortfoliosFetcher(
            dataset_keys=args.portfolios_sets,
            cache_dir=Path(args.portfolios_cache_dir),
            refresh=args.refresh,
            db_config=db_config,
        )
        fetcher.run(table_name="portfolio_returns")


if __name__ == "__main__":
    main()
