from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import requests
from pandas.tseries.offsets import MonthEnd

from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config

SOURCE = "aqr"
FREQUENCY = "M"
SENTINELS = {-99.99, -999.0, -999, -99.999}

PORTFOLIO_DATASETS = {
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

FACTOR_DATASETS = {
    "qmj_factors": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Monthly.xlsx",
        "sheets": [],
    },
    "vme_factors": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Value-and-Momentum-Everywhere-Factors-Monthly.xlsx",
        "sheets": [],
    },
}


def _normalize_header(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip()


def _find_header_row(raw_df: pd.DataFrame) -> Optional[int]:
    for idx, row in raw_df.iterrows():
        first = _normalize_header(row.iloc[0]).upper()
        if first in {"DATE", "YYYYMM", "MONTH"}:
            return idx
    return None


def _parse_dates(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        return pd.to_datetime(values).dt.to_period("M").dt.to_timestamp("M")

    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any():
        as_str = numeric.fillna(0).astype(int).astype(str).str.zfill(6)
        parsed = pd.to_datetime(as_str, format="%Y%m", errors="coerce")
    else:
        text = values.astype(str).str.strip()
        parsed = pd.to_datetime(text, format="%Y%m", errors="coerce")
        if parsed.notna().sum() == 0:
            parsed = pd.to_datetime(text, errors="coerce")

    return parsed + MonthEnd(0)


def parse_aqr_sheet(raw_df: pd.DataFrame) -> pd.DataFrame:
    header_row = _find_header_row(raw_df)
    if header_row is None:
        raise ValueError("Header row with DATE/YYYYMM not found in AQR sheet.")

    raw_header = [_normalize_header(value) for value in raw_df.iloc[header_row].tolist()]
    seen: dict[str, int] = {}
    header: list[Optional[str]] = []
    for name in raw_header:
        if not name:
            header.append(None)
            continue
        if name in seen:
            seen[name] += 1
            header.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            header.append(name)
    data = raw_df.iloc[header_row + 1 :].copy()
    data.columns = header
    data = data.loc[:, [col for col in data.columns if col]]
    data = data.dropna(how="all")

    date_col = data.columns[0]
    data[date_col] = _parse_dates(data[date_col])
    data = data.dropna(subset=[date_col])

    for col in data.columns[1:]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    data.replace(list(SENTINELS), np.nan, inplace=True)
    data = data.dropna(how="all", axis=1)
    data = data.set_index(date_col)
    data.index.name = "date"
    return data


def normalize_aqr_portfolios(
    parsed_df: pd.DataFrame,
    portfolio_set: str,
    universe: str,
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

    melted = parsed_df.reset_index().melt(
        id_vars=["date"], var_name="portfolio", value_name="value"
    )
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["portfolio_set"] = portfolio_set
    melted["universe"] = universe
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


def normalize_aqr_factors(
    parsed_df: pd.DataFrame,
    factor_set: str,
    frequency: str = FREQUENCY,
    source: str = SOURCE,
    sheet_label: str = "NA",
) -> pd.DataFrame:
    if parsed_df.empty:
        return pd.DataFrame(
            columns=["source", "factor_set", "frequency", "factor", "date", "value", "unit"]
        )

    melted = parsed_df.reset_index().melt(id_vars=["date"], var_name="factor", value_name="value")
    melted = melted.dropna(subset=["value"])
    melted["value"] = melted["value"] / 100.0
    melted["source"] = source
    melted["factor_set"] = factor_set
    melted["frequency"] = frequency
    melted["unit"] = "decimal"
    sheet = (sheet_label or "NA").strip()
    melted["factor"] = melted["factor"].astype(str).map(lambda value: f"{sheet}::{value}")
    return melted[["source", "factor_set", "frequency", "factor", "date", "value", "unit"]]


class AQRPortfolioFetcher(BaseFetcher):
    def __init__(
        self,
        dataset_keys: Iterable[str],
        cache_dir: Path,
        refresh: bool = False,
        universe: Optional[str] = None,
        db_config: dict | None = None,
    ):
        super().__init__(db_config)
        self.dataset_keys = list(dataset_keys)
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.universe = universe

    def _download_file(self, key: str) -> Path:
        dataset = PORTFOLIO_DATASETS[key]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.xlsx"

        if path.exists() and not self.refresh:
            self.logger.info("Using cached file for %s", key)
            return path

        self.logger.info("Downloading %s", dataset["url"])
        response = requests.get(dataset["url"], timeout=30)
        response.raise_for_status()
        path.write_bytes(response.content)
        return path

    def fetch(self) -> Dict[str, Dict[str, pd.DataFrame]]:
        payloads: Dict[str, Dict[str, pd.DataFrame]] = {}
        for key in self.dataset_keys:
            dataset = PORTFOLIO_DATASETS[key]
            path = self._download_file(key)
            sheets = dataset.get("sheets", [])
            with pd.ExcelFile(path) as workbook:
                sheet_names = (
                    [name for name in sheets if name in workbook.sheet_names]
                    if sheets
                    else workbook.sheet_names
                )
                payloads[key] = {
                    name: pd.read_excel(workbook, sheet_name=name, header=None)
                    for name in sheet_names
                }
        return payloads

    def transform(self, raw_data: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        matched_universe = False
        for key, sheets in raw_data.items():
            dataset = PORTFOLIO_DATASETS[key]
            dataset_universe_label = dataset.get("universe_label")
            for sheet_name, raw_df in sheets.items():
                universe_label = dataset_universe_label or sheet_name
                if self.universe and self.universe not in {sheet_name, universe_label}:
                    continue
                matched_universe = True
                try:
                    parsed = parse_aqr_sheet(raw_df)
                except Exception as exc:
                    self.logger.warning(
                        "Skipping sheet '%s' for dataset '%s': %s",
                        sheet_name,
                        key,
                        exc,
                    )
                    continue
                frames.append(normalize_aqr_portfolios(parsed, key, universe_label))

        if self.universe and not matched_universe:
            available = []
            for key, sheets in raw_data.items():
                dataset = PORTFOLIO_DATASETS[key]
                label = dataset.get("universe_label")
                for sheet_name in sheets.keys():
                    available.append(label or sheet_name)
            available_display = ", ".join(sorted(set(available))) if available else "None"
            raise ValueError(
                f"Universe '{self.universe}' did not match any available sheets. "
                f"Available: {available_display}"
            )

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


class AQRFactorsFetcher(BaseFetcher):
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

    def _download_file(self, key: str) -> Path:
        dataset = FACTOR_DATASETS[key]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.xlsx"

        if path.exists() and not self.refresh:
            self.logger.info("Using cached file for %s", key)
            return path

        self.logger.info("Downloading %s", dataset["url"])
        response = requests.get(dataset["url"], timeout=30)
        response.raise_for_status()
        path.write_bytes(response.content)
        return path

    def fetch(self) -> Dict[str, Dict[str, pd.DataFrame]]:
        payloads: Dict[str, Dict[str, pd.DataFrame]] = {}
        for key in self.dataset_keys:
            dataset = FACTOR_DATASETS[key]
            path = self._download_file(key)
            sheets = dataset.get("sheets", [])
            with pd.ExcelFile(path) as workbook:
                sheet_names = (
                    [name for name in sheets if name in workbook.sheet_names]
                    if sheets
                    else workbook.sheet_names
                )
                payloads[key] = {
                    name: pd.read_excel(workbook, sheet_name=name, header=None)
                    for name in sheet_names
                }
        return payloads

    def transform(self, raw_data: Dict[str, Dict[str, pd.DataFrame]]) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        for key, sheets in raw_data.items():
            for sheet_name, raw_df in sheets.items():
                try:
                    parsed = parse_aqr_sheet(raw_df)
                except Exception as exc:
                    self.logger.warning(
                        "Skipping sheet '%s' for dataset '%s': %s",
                        sheet_name,
                        key,
                        exc,
                    )
                    continue
                frames.append(normalize_aqr_factors(parsed, key, sheet_label=sheet_name))

        if not frames:
            return pd.DataFrame(
                columns=["source", "factor_set", "frequency", "factor", "date", "value", "unit"]
            )
        return pd.concat(frames, ignore_index=True)


class AQRFetcher(BaseFetcher):
    def __init__(
        self,
        command: str,
        portfolio_keys: Iterable[str],
        factor_keys: Iterable[str],
        cache_dir: Path,
        refresh: bool = False,
        universe: Optional[str] = None,
        db_config: dict | None = None,
    ):
        super().__init__(db_config)
        self.command = command
        self.portfolio_keys = list(portfolio_keys)
        self.factor_keys = list(factor_keys)
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.universe = universe

    def fetch(self) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        if self.command in {"all", "portfolios"} and self.portfolio_keys:
            payload["portfolios"] = AQRPortfolioFetcher(
                dataset_keys=self.portfolio_keys,
                cache_dir=self.cache_dir,
                refresh=self.refresh,
                universe=self.universe,
                db_config=self.db_config,
            ).fetch()

        if self.command in {"all", "factors"} and self.factor_keys:
            payload["factors"] = AQRFactorsFetcher(
                dataset_keys=self.factor_keys,
                cache_dir=self.cache_dir,
                refresh=self.refresh,
                db_config=self.db_config,
            ).fetch()

        return payload

    def transform(self, raw_data: Dict[str, object]) -> Dict[str, pd.DataFrame]:
        outputs: Dict[str, pd.DataFrame] = {}
        if "portfolios" in raw_data:
            outputs["portfolio_returns"] = AQRPortfolioFetcher(
                dataset_keys=self.portfolio_keys,
                cache_dir=self.cache_dir,
                refresh=self.refresh,
                universe=self.universe,
                db_config=self.db_config,
            ).transform(raw_data["portfolios"])  # type: ignore[arg-type]

        if "factors" in raw_data:
            outputs["factor_returns"] = AQRFactorsFetcher(
                dataset_keys=self.factor_keys,
                cache_dir=self.cache_dir,
                refresh=self.refresh,
                db_config=self.db_config,
            ).transform(raw_data["factors"])  # type: ignore[arg-type]

        return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch AQR datasets (portfolios + factors).")
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["all", "portfolios", "factors"],
        help="What to fetch (default: all).",
    )
    parser.add_argument(
        "--sets",
        nargs="+",
        help="Alias for --portfolios-sets (command=portfolios) or --factors-sets (command=factors).",
    )
    parser.add_argument(
        "--portfolios-sets",
        nargs="+",
        default=list(PORTFOLIO_DATASETS.keys()),
        choices=sorted(PORTFOLIO_DATASETS.keys()),
        help="AQR portfolio dataset keys to ingest.",
    )
    parser.add_argument(
        "--factors-sets",
        nargs="+",
        default=list(FACTOR_DATASETS.keys()),
        choices=sorted(FACTOR_DATASETS.keys()),
        help="AQR factor dataset keys to ingest.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(Path("derived") / "aqr"),
        help="Directory to cache downloaded AQR Excel files.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload source files even if cached.",
    )
    parser.add_argument(
        "--universe",
        help="Optional sheet/universe name filter (e.g., USA).",
    )
    args = parser.parse_args()

    if args.sets:
        if args.command == "portfolios":
            args.portfolios_sets = args.sets
        elif args.command == "factors":
            args.factors_sets = args.sets
        else:
            raise ValueError("--sets is ambiguous for command=all. Use --portfolios-sets/--factors-sets.")

    fetcher = AQRFetcher(
        command=args.command,
        portfolio_keys=args.portfolios_sets,
        factor_keys=args.factors_sets,
        cache_dir=Path(args.cache_dir),
        refresh=args.refresh,
        universe=args.universe,
        db_config=get_database_config(),
    )
    fetcher.run()


if __name__ == "__main__":
    main()
