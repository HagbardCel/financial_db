from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from data_fetchers.aqr_parsers import (
    normalize_aqr_factors,
    normalize_aqr_portfolios,
    parse_aqr_sheet,
)
from data_fetchers.aqr_registry import FACTOR_DATASETS, PORTFOLIO_DATASETS
from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers.download_utils import download_url_to_path, use_cached_file
from db_utils.config import get_database_config

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

        if use_cached_file(path, self.refresh, self.logger):
            return path

        self.logger.info("Downloading %s", dataset["url"])
        download_url_to_path(dataset["url"], path, timeout=30)
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

        if use_cached_file(path, self.refresh, self.logger):
            return path

        self.logger.info("Downloading %s", dataset["url"])
        download_url_to_path(dataset["url"], path, timeout=30)
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
