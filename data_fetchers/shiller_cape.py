from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, Optional

import pandas as pd
import requests
from pandas.tseries.offsets import MonthEnd

from data_fetchers.base_fetcher import BaseFetcher
from db_utils.config import get_database_config


DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_SHEET_NAME = "Data"
DEFAULT_COLUMNS_PATH = Path(__file__).with_name("shiller_cols.json")


class ShillerCapeFetcher(BaseFetcher):
    def __init__(
        self,
        file_url: str,
        column_mapping: Dict[str, Dict[str, str]],
        db_config: Optional[dict] = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sheet_name: str = DEFAULT_SHEET_NAME,
    ):
        super().__init__(db_config)
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self.file_url = file_url
        self.column_mapping = column_mapping
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sheet_name = sheet_name
        self._temp_file_path: Optional[Path] = None

    def _download_content(self) -> bytes:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(
                    "Downloading Shiller CAPE data (attempt %s/%s): %s",
                    attempt,
                    self.max_retries,
                    self.file_url,
                )
                response = requests.get(self.file_url, timeout=self.request_timeout)
                response.raise_for_status()
                return response.content
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
                self.logger.warning(
                    "Shiller download failed on attempt %s/%s: %s. Retrying in %.1fs.",
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Shiller download failed unexpectedly without an error.")

    def fetch(self) -> str:
        """Download the Excel file and return its temporary path."""
        content = self._download_content()
        with NamedTemporaryFile(prefix="shiller_cape_", suffix=".xls", delete=False) as temp_file:
            temp_file.write(content)
            self._temp_file_path = Path(temp_file.name)

        self.logger.info("Saved downloaded Shiller file to %s", self._temp_file_path)
        return str(self._temp_file_path)

    def _extract_column_names(self, file_path: str) -> list[str]:
        raw_columns = pd.read_excel(
            file_path,
            sheet_name=self.sheet_name,
            skiprows=1,
            nrows=7,
            header=None,
        ).transpose()
        return [
            " ".join(name.split())
            for name in raw_columns.apply(
                lambda row: " ".join(row.dropna().astype(str)),
                axis=1,
            ).iloc[1:].tolist()
        ]

    def _parse_dates(self, file_path: str) -> pd.DatetimeIndex:
        date_data = pd.read_excel(
            file_path,
            sheet_name=self.sheet_name,
            skiprows=7,
            usecols=["Date"],
            dtype={"Date": str},
        ).dropna()
        dates = pd.to_datetime(
            date_data["Date"].apply(lambda value: value + "0" if len(value) < 7 else value),
            format="%Y.%m",
        ) + MonthEnd(0)
        return dates

    def transform(self, file_path: str) -> Dict[str, pd.DataFrame]:
        col_names = self._extract_column_names(file_path)
        dates = self._parse_dates(file_path)

        cape_data = pd.read_excel(
            file_path,
            sheet_name=self.sheet_name,
            skiprows=8,
            header=None,
            names=col_names,
            nrows=len(dates),
        )
        cape_data.dropna(how="all", axis=1, inplace=True)
        cape_data.dropna(how="all", inplace=True)
        cape_data = cape_data.apply(pd.to_numeric, errors="coerce")
        cape_data.index = dates

        missing_columns = [column for column in self.column_mapping if column not in cape_data.columns]
        if missing_columns:
            raise ValueError(
                "Expected Shiller columns missing from source file: "
                + ", ".join(sorted(missing_columns))
            )

        records = []
        for date, row in cape_data.iterrows():
            for raw_col, details in self.column_mapping.items():
                value = row[raw_col]
                if pd.notna(value):
                    records.append(
                        {
                            "date": date,
                            "id": details["id"],
                            "long_name": details["long_name"],
                            "value": value,
                            "type": details["type"],
                        }
                    )

        if not records:
            raise ValueError("No valid Shiller rows were parsed from the source file.")

        frame = pd.DataFrame(records)
        macro_data = frame[frame["type"] != "derived"].drop("type", axis=1)
        test_data = frame[frame["type"] == "derived"].drop("type", axis=1)

        return {
            "macro_data": macro_data,
            "test_data": test_data,
        }

    def _cleanup_temp_file(self) -> None:
        if self._temp_file_path is None:
            return
        try:
            if self._temp_file_path.exists():
                self._temp_file_path.unlink()
        except OSError as exc:
            self.logger.warning("Could not remove temporary file %s: %s", self._temp_file_path, exc)
        finally:
            self._temp_file_path = None

    def run(self, table_name: Optional[str] = None):
        try:
            super().run(table_name)
        finally:
            self._cleanup_temp_file()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and ingest Shiller CAPE data from an Excel URL.")
    parser.add_argument(
        "url",
        nargs="?",
        help="Shiller Excel URL (legacy positional argument).",
    )
    parser.add_argument(
        "--url",
        dest="url_override",
        help="Shiller Excel URL (overrides positional URL when provided).",
    )
    parser.add_argument(
        "--column-mapping",
        default=str(DEFAULT_COLUMNS_PATH),
        help="Path to shiller column mapping JSON.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help="HTTP timeout in seconds for download requests.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Number of download attempts.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF_SECONDS,
        help="Base seconds for exponential backoff between retries.",
    )
    return parser.parse_args()


def _resolve_url(args: argparse.Namespace) -> str:
    url = args.url_override or args.url
    if not url:
        raise ValueError(
            "Shiller Excel URL is required. Provide it as positional arg or via --url."
        )
    return url


def _load_column_mapping(path_value: str) -> Dict[str, Dict[str, str]]:
    mapping_path = Path(path_value)
    if not mapping_path.is_absolute():
        candidates = [
            (Path.cwd() / mapping_path).resolve(),
            (Path(__file__).resolve().parent / mapping_path).resolve(),
            (Path(__file__).resolve().parent.parent / mapping_path).resolve(),
        ]
        mapping_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    if not mapping_path.exists():
        raise ValueError(f"Column mapping file not found: {mapping_path}")

    with mapping_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    args = parse_args()
    file_url = _resolve_url(args)
    column_mapping = _load_column_mapping(args.column_mapping)

    fetcher = ShillerCapeFetcher(
        file_url=file_url,
        column_mapping=column_mapping,
        db_config=get_database_config(),
        request_timeout=args.timeout,
        max_retries=args.retries,
        retry_backoff_seconds=args.retry_backoff,
    )
    fetcher.run()


if __name__ == "__main__":
    main()
