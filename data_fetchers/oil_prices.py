from __future__ import annotations

import argparse
import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd
from pandas.tseries.offsets import MonthEnd, YearEnd

from data_fetchers import openbb_client
from data_fetchers.base_fetcher import BaseFetcher
from data_fetchers.download_utils import download_url_to_path, use_cached_file
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

logger = logging.getLogger(__name__)

EIA_US_CRUDE_ANNUAL_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=A&n=PET&s=F000000__3"
EIA_US_CRUDE_MONTHLY_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=M&n=PET&s=F000000__3"
DEFAULT_CACHE_DIR = Path("derived") / "oil_prices"
DEFAULT_OPENBB_PROVIDER = "fred"
FRED_SETUP_HINT = (
    "Set FRED_API_KEY in .devcontainer/.env (preferred) or export it in the shell "
    "before running the fetcher."
)
MONTH_COLUMNS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class OilSeriesSpec:
    symbol: str
    label: str
    kind: str
    commodity: Optional[str] = None


SERIES_SPECS = (
    OilSeriesSpec(symbol="USOIL", label="Long-run U.S. crude benchmark", kind="eia"),
    OilSeriesSpec(symbol="WTI", label="WTI spot benchmark", kind="openbb", commodity="wti"),
    OilSeriesSpec(symbol="BRENT", label="Brent spot benchmark", kind="openbb", commodity="brent"),
)
SERIES_BY_SYMBOL = {series.symbol: series for series in SERIES_SPECS}


def _find_history_table(html_text: str, first_column_name: str) -> pd.DataFrame:
    tables = pd.read_html(io.StringIO(html_text))
    for table in tables:
        first_col = str(table.columns[0]).strip()
        if first_col == first_column_name:
            return table
    raise ValueError(f"Could not find EIA history table with first column '{first_column_name}'.")


def parse_eia_annual_history(html_text: str, symbol: str = "USOIL") -> pd.DataFrame:
    table = _find_history_table(html_text, "Decade")
    records: list[dict[str, object]] = []

    for _, row in table.iterrows():
        decade_value = str(row["Decade"]).strip()
        if not decade_value or decade_value.lower() == "nan":
            continue
        decade_base = int(decade_value[:4])
        for offset in range(10):
            col = f"Year-{offset}"
            value = pd.to_numeric(row.get(col), errors="coerce")
            if pd.isna(value):
                continue
            year = decade_base + offset
            records.append(
                {
                    "symbol": symbol,
                    "date": (pd.Timestamp(year=year, month=12, day=31) + YearEnd(0)).date(),
                    "open": float(value),
                    "high": float(value),
                    "low": float(value),
                    "close": float(value),
                    "volume": 0,
                }
            )

    if not records:
        raise ValueError("No annual U.S. crude benchmark rows were parsed from EIA.")
    return pd.DataFrame.from_records(records)


def parse_eia_monthly_history(html_text: str, symbol: str = "USOIL") -> pd.DataFrame:
    table = _find_history_table(html_text, "Year")
    records: list[dict[str, object]] = []

    for _, row in table.iterrows():
        year_value = pd.to_numeric(row["Year"], errors="coerce")
        if pd.isna(year_value):
            continue
        year = int(year_value)
        for month_idx, month_name in enumerate(MONTH_COLUMNS, start=1):
            value = pd.to_numeric(row.get(month_name), errors="coerce")
            if pd.isna(value):
                continue
            date = pd.Timestamp(year=year, month=month_idx, day=1) + MonthEnd(0)
            records.append(
                {
                    "symbol": symbol,
                    "date": date.date(),
                    "open": float(value),
                    "high": float(value),
                    "low": float(value),
                    "close": float(value),
                    "volume": 0,
                }
            )

    if not records:
        raise ValueError("No monthly U.S. crude benchmark rows were parsed from EIA.")
    return pd.DataFrame.from_records(records)


def combine_eia_us_oil_history(annual_df: pd.DataFrame, monthly_df: pd.DataFrame) -> pd.DataFrame:
    first_monthly_year = pd.to_datetime(monthly_df["date"]).dt.year.min()
    annual_keep = annual_df[pd.to_datetime(annual_df["date"]).dt.year < first_monthly_year]
    combined = pd.concat([annual_keep, monthly_df], ignore_index=True)
    return combined.sort_values(["date", "symbol"]).reset_index(drop=True)


def collapse_to_month_end(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    normalized = df.copy().reset_index(drop=True)
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"]).sort_values("date")
    normalized["month"] = normalized["date"].dt.to_period("M")
    collapsed = normalized.groupby("month", as_index=False).tail(1).copy()
    collapsed["date"] = (collapsed["date"] + MonthEnd(0)).dt.date
    return collapsed.drop(columns=["month"]).reset_index(drop=True)


def _is_provider_auth_error(exc: Exception) -> bool:
    detail = str(exc).lower()
    auth_markers = (
        "api key",
        "authentication",
        "unauthorized",
        "forbidden",
        "access denied",
        "permission denied",
        "credential",
        "provider auth",
    )
    provider_markers = ("fred", "openbb", "provider")
    return any(marker in detail for marker in auth_markers) and any(marker in detail for marker in provider_markers)


class EIAUSOilPriceFetcher(BaseFetcher):
    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        refresh: bool = False,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.cache_dir = cache_dir
        self.refresh = refresh

    def _download(self, url: str, file_name: str) -> str:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / file_name
        if not use_cached_file(path, self.refresh, self.logger):
            self.logger.info("Downloading %s", url)
            download_url_to_path(url, path, timeout=30)
        return path.read_text(encoding="utf-8", errors="ignore")

    def fetch(self) -> tuple[str, str]:
        annual = self._download(EIA_US_CRUDE_ANNUAL_URL, "us_crude_annual.html")
        monthly = self._download(EIA_US_CRUDE_MONTHLY_URL, "us_crude_monthly.html")
        return annual, monthly

    def transform(self, raw_data: tuple[str, str]) -> pd.DataFrame:
        annual_html, monthly_html = raw_data
        annual_df = parse_eia_annual_history(annual_html, symbol="USOIL")
        monthly_df = parse_eia_monthly_history(monthly_html, symbol="USOIL")
        return combine_eia_us_oil_history(annual_df, monthly_df)


class OpenBBOilSpotFetcher(BaseFetcher):
    def __init__(
        self,
        symbol: str,
        commodity: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        provider: Optional[str] = None,
        db_config: Optional[dict] = None,
    ):
        super().__init__(db_config)
        self.symbol = symbol
        self.commodity = commodity
        self.start_date = start_date
        self.end_date = end_date
        self.provider = provider or os.getenv("OPENBB_OIL_PROVIDER") or DEFAULT_OPENBB_PROVIDER

    def fetch(self) -> pd.DataFrame:
        self.logger.info("Fetching %s benchmark data from OpenBB (%s)", self.symbol, self.provider)
        return openbb_client.fetch_dataframe(
            openbb_client.get_commodity_spot_path(),
            commodity=self.commodity,
            start_date=self.start_date,
            end_date=self.end_date,
            provider=self.provider,
        )

    def transform(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        normalized = openbb_client.normalize_ohlcv(raw_df, symbol=self.symbol)
        return collapse_to_month_end(normalized)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch oil benchmark series into commodity_prices.")
    parser.add_argument(
        "--series",
        nargs="+",
        choices=sorted(SERIES_BY_SYMBOL.keys()),
        default=[series.symbol for series in SERIES_SPECS],
        help="Oil series to ingest (default: all).",
    )
    parser.add_argument(
        "--start",
        dest="start_date",
        help="Optional start date for OpenBB spot series (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        dest="end_date",
        help="Optional end date for OpenBB spot series (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_OPENBB_PROVIDER,
        help="OpenBB provider override for WTI/BRENT spot series (default: fred).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload cached EIA source pages.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Directory to cache EIA source pages.",
    )
    return parser.parse_args(argv)


def resolve_series(selection: Iterable[str]) -> list[OilSeriesSpec]:
    return [SERIES_BY_SYMBOL[name] for name in selection]


def main(argv: Sequence[str] | None = None) -> int:
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

    args = parse_args(argv)
    db_config = get_database_config()
    cache_dir = Path(args.cache_dir)
    selected_series = resolve_series(args.series)
    failed_symbols: list[str] = []
    failure_details: dict[str, str] = {}

    with DatabaseConnection(config=db_config) as db:
        repo = DataRepository(db)
        for series in selected_series:
            try:
                if series.kind == "eia":
                    fetcher = EIAUSOilPriceFetcher(
                        cache_dir=cache_dir,
                        refresh=args.refresh,
                        db_config=db_config,
                    )
                else:
                    fetcher = OpenBBOilSpotFetcher(
                        symbol=series.symbol,
                        commodity=series.commodity or "",
                        start_date=args.start_date,
                        end_date=args.end_date,
                        provider=args.provider,
                        db_config=db_config,
                    )
                fetcher.run_with_repository(repo, table_name="commodity_prices")
                db.conn.commit()
                logger.info("Successfully processed %s", series.symbol)
            except Exception as exc:
                db.conn.rollback()
                failed_symbols.append(series.symbol)
                logger.exception("Failed to process %s", series.symbol)
                detail = str(exc)
                if series.kind == "openbb" and _is_provider_auth_error(exc):
                    detail = f"{detail}. {FRED_SETUP_HINT}"
                failure_details[series.symbol] = detail

    succeeded = len(selected_series) - len(failed_symbols)
    logger.info("Oil ingest finished: %s succeeded, %s failed.", succeeded, len(failed_symbols))
    if failed_symbols:
        logger.error("Failed symbols: %s", ", ".join(failed_symbols))
        for symbol in failed_symbols:
            logger.error("%s failure detail: %s", symbol, failure_details[symbol])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
