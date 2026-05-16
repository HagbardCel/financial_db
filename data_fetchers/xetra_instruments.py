from __future__ import annotations

import argparse
import io
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import requests

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.manifests import file_manifest
from data_fetchers.download_utils import download_url_to_path
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository


COLUMN_CANDIDATES = {
    "isin": ("isin", "isin code"),
    "symbol": ("instrument mnemonic", "mnemonic", "symbol", "ticker"),
    "name": ("instrument name", "name", "security name"),
    "currency": ("currency", "trading currency"),
    "instrument_id": ("instrument id", "instrumentid", "product id"),
    "security_type": ("instrument type", "product type", "security type"),
}


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current_href: Optional[str] = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href is not None:
            self.links.append({"href": self._current_href, "text": " ".join(self._text_parts).strip()})
            self._current_href = None
            self._text_parts = []


def _normalize_column(name: str) -> str:
    return " ".join(str(name).strip().lower().replace("_", " ").split())


def _find_column(columns: Iterable[str], key: str) -> Optional[str]:
    normalized = {_normalize_column(col): col for col in columns}
    for candidate in COLUMN_CANDIDATES[key]:
        if candidate in normalized:
            return normalized[candidate]
    return None


def discover_xetra_download_url(page_html: str, page_url: str, link_text: str) -> str:
    parser = LinkExtractor()
    parser.feed(page_html)
    needles = [link_text.lower(), "all tradable instruments", "alltradableinstruments"]
    candidates: list[str] = []
    for link in parser.links:
        href = unquote(link["href"])
        text = link["text"].lower()
        haystack = f"{href.lower()} {text}"
        if any(needle in haystack for needle in needles):
            candidates.append(urljoin(page_url, href))
    if not candidates:
        raise ValueError(f"Could not find Xetra download link matching '{link_text}' on {page_url}")
    csv_like = [url for url in candidates if "csv" in url.lower() or "alltradableinstruments" in url.lower()]
    return csv_like[0] if csv_like else candidates[0]


def _filename_from_url(url: str, fallback: str) -> str:
    path_name = Path(urlparse(url).path).name
    path_name = unquote(path_name)
    if path_name:
        return path_name
    match = re.search(r"[\w.-]*allTradableInstruments[\w.-]*\.csv", url)
    return match.group(0) if match else fallback


def download_xetra_file(config: dict, url_override: Optional[str] = None) -> tuple[Path, str]:
    source = config["sources"]["xetra"]
    page_url = source["source_page"]
    if url_override:
        download_url = url_override
    else:
        response = requests.get(page_url, timeout=30)
        response.raise_for_status()
        download_url = discover_xetra_download_url(
            response.text,
            page_url,
            source.get("download_link_text", "T7 (Xetra) All tradable instruments"),
        )
    raw_dir = Path(source.get("raw_dir", "derived/stock_momentum/raw/xetra"))
    destination = raw_dir / _filename_from_url(download_url, "t7-xetr-allTradableInstruments.csv")
    download_url_to_path(download_url, destination, timeout=60)
    return destination, download_url


def parse_xetra_csv(raw_text: str, source_file: str = "") -> tuple[pd.DataFrame, str, str]:
    lines = raw_text.splitlines()
    if len(lines) < 4:
        raise ValueError("Xetra tradable instruments file must contain metadata plus a header row.")
    mic = lines[0].strip()
    last_update = lines[1].strip()
    frame = pd.read_csv(io.StringIO("\n".join(lines[2:])), sep=";", dtype=str)
    frame.columns = [str(col).strip() for col in frame.columns]
    frame["source_file"] = source_file
    return frame, mic, last_update


def normalize_xetra_instruments(bronze: pd.DataFrame, mic: str, last_update: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    isin_col = _find_column(bronze.columns, "isin")
    symbol_col = _find_column(bronze.columns, "symbol")
    name_col = _find_column(bronze.columns, "name")
    currency_col = _find_column(bronze.columns, "currency")
    type_col = _find_column(bronze.columns, "security_type")
    instrument_id_col = _find_column(bronze.columns, "instrument_id")

    if not symbol_col:
        raise ValueError(f"Could not identify Xetra symbol column. Columns: {bronze.columns.tolist()}")
    if not name_col:
        raise ValueError(f"Could not identify Xetra name column. Columns: {bronze.columns.tolist()}")

    rows = []
    listing_rows = []
    for _, row in bronze.iterrows():
        symbol = str(row.get(symbol_col) or "").strip()
        if not symbol:
            continue
        isin = str(row.get(isin_col) or "").strip() if isin_col else ""
        name = str(row.get(name_col) or "").strip()
        currency = str(row.get(currency_col) or "").strip() if currency_col else None
        security_type = str(row.get(type_col) or "unknown").strip().lower() if type_col else "unknown"
        instrument_id = str(row.get(instrument_id_col) or symbol).strip() if instrument_id_col else symbol
        security_id = isin or f"xetra:{symbol}"
        listing_id = f"xetra:{mic}:{instrument_id}"
        rows.append(
            {
                "security_id": security_id,
                "isin": isin or None,
                "name": name or symbol,
                "security_type": security_type,
                "country": None,
                "currency_primary": currency,
                "source_first_seen": "xetra",
                "source_last_seen": "xetra",
                "active_flag_current": True,
                "created_at_utc": now,
                "updated_at_utc": now,
            }
        )
        listing_rows.append(
            {
                "listing_id": listing_id,
                "security_id": security_id,
                "provider": "xetra",
                "provider_symbol": symbol,
                "exchange_code": "XETR",
                "mic": mic,
                "trading_currency": currency,
                "isin": isin or None,
                "name": name or symbol,
                "first_seen_date": pd.to_datetime(last_update, errors="coerce").date()
                if pd.notna(pd.to_datetime(last_update, errors="coerce"))
                else None,
                "last_seen_date": pd.to_datetime(last_update, errors="coerce").date()
                if pd.notna(pd.to_datetime(last_update, errors="coerce"))
                else None,
                "is_currently_tradable": True,
                "source_file": str(row.get("source_file") or ""),
            }
        )
    securities = pd.DataFrame(rows).drop_duplicates(subset=["security_id"])
    listings = pd.DataFrame(listing_rows).drop_duplicates(subset=["listing_id"])
    return securities, listings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Xetra tradable instruments for stock momentum.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    parser.add_argument("--file", help="Path to a downloaded Xetra tradable instruments CSV.")
    parser.add_argument("--url", help="Direct Xetra CSV/download URL override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    source_url = None
    if args.file:
        path = Path(args.file)
    else:
        path, source_url = download_xetra_file(config, url_override=args.url)
    raw_text = path.read_text(encoding="utf-8-sig")
    bronze, mic, last_update = parse_xetra_csv(raw_text, source_file=str(path))
    securities, listings = normalize_xetra_instruments(bronze, mic, last_update)
    manifest = file_manifest("xetra", path, source_url=source_url or args.url, row_count=len(bronze))
    with DatabaseConnection(config=get_database_config()) as db:
        repo = DataRepository(db)
        repo.save_dataframe(manifest, "ingestion_manifests")
        repo.save_dataframe(securities, "securities")
        repo.save_dataframe(listings, "listings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
