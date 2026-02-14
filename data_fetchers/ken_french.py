from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers.download_utils import download_first_available_url, use_cached_file
from data_fetchers.ken_french_parsers import (
    normalize_ken_french_portfolios,
    parse_ken_french_monthly,
    parse_ken_french_portfolios_monthly,
)
from data_fetchers.ken_french_registry import (
    DATASETS,
    FREQUENCY,
    PORTFOLIO_DATASETS,
    SOURCE,
)
from db_utils.config import get_database_config

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


def _download_ken_french_zip(urls: Iterable[str], zip_path: Path, refresh: bool, logger) -> Path:
    if use_cached_file(zip_path, refresh, logger):
        return zip_path

    attempted = list(urls)
    for url in attempted:
        logger.info("Downloading %s", url)
    download_first_available_url(attempted, zip_path, timeout=30)
    return zip_path


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
