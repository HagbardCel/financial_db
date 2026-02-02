from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers.download_utils import download_any_url, parse_drive_folder_id, use_cached_file
from data_fetchers.open_asset_pricing_links import (
    extract_data_page_drive_link,
    resolve_dataset_download_url,
)
from data_fetchers.open_asset_pricing_parsers import (
    normalize_oapd_factors,
    normalize_portfolio_characteristics,
    parse_oapd_factors_wide,
    parse_oapd_factors_zip,
    parse_oapd_signal_doc,
    parse_portfolio_characteristics_csv,
    validate_oapd_factors,
)
from data_fetchers.open_asset_pricing_registry import (
    FACTOR_DATASETS,
    METADATA_DATASET,
)
from db_utils.config import get_database_config

# Backward-compatible aliases for existing tests/imports.
_parse_drive_folder_id = parse_drive_folder_id
_extract_data_page_drive_link = extract_data_page_drive_link


def _ensure_direct_file_url(url: str, flag_name: str) -> None:
    if parse_drive_folder_id(url):
        raise ValueError(
            f"{flag_name} points to a Google Drive folder, not a downloadable file. "
            f"Pass a direct CSV/ZIP file URL in {flag_name}."
        )


class OpenAssetPricingFactorsFetcher(BaseFetcher):
    def __init__(
        self,
        dataset_key: str,
        cache_dir: Path,
        refresh: bool = False,
        url_override: Optional[str] = None,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        if dataset_key not in FACTOR_DATASETS:
            raise ValueError(f"Unknown Open Asset Pricing factor dataset: {dataset_key}")
        self.dataset_key = dataset_key
        self.dataset = FACTOR_DATASETS[dataset_key]
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.url_override = url_override

    def _download(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / self.dataset["file_name"]
        if use_cached_file(path, self.refresh, self.logger):
            return path

        url = resolve_dataset_download_url(self.dataset, self.url_override, logger=self.logger)
        _ensure_direct_file_url(url, "--factors-url")

        self.logger.info("Downloading %s", url)
        download_any_url(url, path)
        return path

    def fetch(self) -> Path:
        return self._download()

    def transform(self, raw_data: Path) -> pd.DataFrame:
        frequency = self.dataset["frequency"]
        if raw_data.suffix.lower() == ".zip":
            parsed = parse_oapd_factors_zip(raw_data)
        else:
            text = raw_data.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_oapd_factors_wide(text, frequency=frequency)

        validate_oapd_factors(parsed, frequency=frequency, logger=self.logger)
        return normalize_oapd_factors(
            parsed,
            factor_set=self.dataset["factor_set"],
            frequency=frequency,
        )


class OpenAssetPricingMetadataFetcher(BaseFetcher):
    def __init__(
        self,
        cache_dir: Path,
        refresh: bool = False,
        url_override: Optional[str] = None,
        characteristic_set: Optional[str] = None,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.url_override = url_override
        self.characteristic_set = characteristic_set or METADATA_DATASET["characteristic_set"]

    def _download(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / METADATA_DATASET["file_name"]
        if use_cached_file(path, self.refresh, self.logger):
            return path

        url = resolve_dataset_download_url(METADATA_DATASET, self.url_override, logger=self.logger)
        _ensure_direct_file_url(url, "--metadata-url")

        self.logger.info("Downloading %s", url)
        download_any_url(url, path)
        return path

    def fetch(self) -> Path:
        return self._download()

    def transform(self, raw_data: Path) -> pd.DataFrame:
        text = raw_data.read_text(encoding="utf-8", errors="ignore")
        return parse_oapd_signal_doc(text, characteristic_set=self.characteristic_set)


class OpenAssetPricingPortfolioCharacteristicsFetcher(BaseFetcher):
    def __init__(
        self,
        url: str,
        cache_dir: Path,
        refresh: bool = False,
        frequency: str = "M",
        portfolio_set: str = "oapd::portfolio_characteristics",
        universe: str = "NA",
        unit: str = "raw",
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.url = url
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.frequency = frequency
        self.portfolio_set = portfolio_set
        self.universe = universe
        self.unit = unit

    def _download(self) -> Path:
        _ensure_direct_file_url(self.url, "--portfolio-scores-url")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(self.url)
        file_name = Path(parsed.path).name or "portfolio_characteristics.csv"
        path = self.cache_dir / file_name
        if use_cached_file(path, self.refresh, self.logger):
            return path

        self.logger.info("Downloading %s", self.url)
        download_any_url(self.url, path)
        return path

    def fetch(self) -> Path:
        return self._download()

    def transform(self, raw_data: Path) -> pd.DataFrame:
        text = raw_data.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_portfolio_characteristics_csv(text, frequency=self.frequency)
        return normalize_portfolio_characteristics(
            parsed,
            portfolio_set=self.portfolio_set,
            universe=self.universe,
            frequency=self.frequency,
            unit=self.unit,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Open Asset Pricing datasets.")
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["all", "factors", "metadata", "portfolio_characteristics", "portfolio-scores"],
        help="What to fetch (default: all = factors + metadata).",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Use daily predictor long-short dataset (factors command only).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload source files even if cached.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(Path("derived") / "open_asset_pricing"),
        help="Directory to cache downloaded files.",
    )
    parser.add_argument(
        "--factors-url",
        help="Override factors dataset URL.",
    )
    parser.add_argument(
        "--metadata-url",
        help="Override metadata (SignalDoc) URL.",
    )
    parser.add_argument(
        "--characteristic-set",
        default=METADATA_DATASET["characteristic_set"],
        help="Characteristic set label stored in characteristic_metadata.",
    )
    parser.add_argument(
        "--portfolio-scores-url",
        help="URL for portfolio-level characteristic scores CSV (required for portfolio commands).",
    )
    parser.add_argument(
        "--portfolio-set",
        default="oapd::portfolio_characteristics",
        help="Portfolio set label for portfolio characteristics.",
    )
    parser.add_argument(
        "--universe",
        default="NA",
        help="Universe label for portfolio characteristics.",
    )
    parser.add_argument(
        "--frequency",
        default="M",
        choices=["D", "M"],
        help="Frequency for portfolio characteristic scores.",
    )
    parser.add_argument(
        "--unit",
        default="raw",
        help="Unit stored in portfolio_characteristics.",
    )
    return parser.parse_args()


def _resolve_factor_dataset_key(daily: bool) -> str:
    return "predictor_ls_daily" if daily else "predictor_ls_monthly"


def main() -> None:
    args = parse_args()
    db_config = get_database_config()
    cache_dir = Path(args.cache_dir)

    if args.command in {"all", "factors"}:
        factor_fetcher = OpenAssetPricingFactorsFetcher(
            dataset_key=_resolve_factor_dataset_key(args.daily),
            cache_dir=cache_dir,
            refresh=args.refresh,
            url_override=args.factors_url,
            db_config=db_config,
        )
        factor_fetcher.run(table_name="factor_returns")

    if args.command in {"all", "metadata"}:
        metadata_fetcher = OpenAssetPricingMetadataFetcher(
            cache_dir=cache_dir,
            refresh=args.refresh,
            url_override=args.metadata_url,
            characteristic_set=args.characteristic_set,
            db_config=db_config,
        )
        metadata_fetcher.run(table_name="characteristic_metadata")

    if args.command in {"portfolio_characteristics", "portfolio-scores"}:
        if not args.portfolio_scores_url:
            raise ValueError(
                "--portfolio-scores-url is required for command=portfolio_characteristics/portfolio-scores."
            )
        portfolio_fetcher = OpenAssetPricingPortfolioCharacteristicsFetcher(
            url=args.portfolio_scores_url,
            cache_dir=cache_dir,
            refresh=args.refresh,
            frequency=args.frequency,
            portfolio_set=args.portfolio_set,
            universe=args.universe,
            unit=args.unit,
            db_config=db_config,
        )
        portfolio_fetcher.run(table_name="portfolio_characteristics")


if __name__ == "__main__":
    main()
