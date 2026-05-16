from __future__ import annotations

import argparse
import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from pandas.errors import EmptyDataError, ParserError
import requests

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.manifests import file_manifest
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

logger = logging.getLogger(__name__)

EQUITY_PRICE_BAR_COLUMNS = [
    "provider",
    "provider_symbol",
    "security_id",
    "listing_id",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "currency",
    "adjustment_status",
    "source_file",
    "ingested_at_utc",
]

STOOQ_COLUMNS = {
    "date": ("date", "<date>"),
    "open": ("open", "<open>"),
    "high": ("high", "<high>"),
    "low": ("low", "<low>"),
    "close": ("close", "<close>"),
    "volume": ("volume", "<vol>", "vol"),
}


def empty_price_bars_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=EQUITY_PRICE_BAR_COLUMNS)


def _normalize_stooq_column(column: object) -> str:
    return str(column).strip().lower().strip("<>").replace(" ", "_")


def _column_lookup(columns: Iterable[str]) -> dict[str, str]:
    normalized = {_normalize_stooq_column(col): col for col in columns}
    found = {}
    for canonical, candidates in STOOQ_COLUMNS.items():
        for candidate in candidates:
            normalized_candidate = _normalize_stooq_column(candidate)
            if normalized_candidate in normalized:
                found[canonical] = normalized[normalized_candidate]
                break
    return found


def _parse_stooq_dates(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    compact = text.str.fullmatch(r"\d{8}")
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    if (~compact).any():
        parsed.loc[~compact] = pd.to_datetime(text.loc[~compact], errors="coerce")
    return parsed


def _provider_symbol_from_frame(frame: pd.DataFrame, fallback: str) -> str:
    normalized = {_normalize_stooq_column(col): col for col in frame.columns}
    ticker_col = normalized.get("ticker")
    if ticker_col:
        tickers = frame[ticker_col].dropna().astype(str).str.strip()
        tickers = tickers[tickers != ""]
        if not tickers.empty:
            return tickers.iloc[0].lower()
    return fallback.lower()


def parse_stooq_csv(
    raw_csv: str,
    provider_symbol: str,
    source_file: str = "",
    currency: Optional[str] = None,
    security_id: Optional[str] = None,
    listing_id: Optional[str] = None,
) -> pd.DataFrame:
    if not raw_csv or not raw_csv.strip():
        return empty_price_bars_frame()
    try:
        frame = pd.read_csv(io.StringIO(raw_csv))
    except EmptyDataError:
        return empty_price_bars_frame()
    if frame.empty:
        return empty_price_bars_frame()
    lookup = _column_lookup(frame.columns)
    missing = sorted(set(["date", "open", "high", "low", "close"]) - set(lookup))
    if missing:
        raise ValueError(f"Missing Stooq columns: {', '.join(missing)}")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    resolved_symbol = _provider_symbol_from_frame(frame, provider_symbol)
    output = pd.DataFrame(
        {
            "provider": "stooq",
            "provider_symbol": resolved_symbol,
            "security_id": security_id,
            "listing_id": listing_id,
            "date": _parse_stooq_dates(frame[lookup["date"]]).dt.date,
            "open": pd.to_numeric(frame[lookup["open"]], errors="coerce"),
            "high": pd.to_numeric(frame[lookup["high"]], errors="coerce"),
            "low": pd.to_numeric(frame[lookup["low"]], errors="coerce"),
            "close": pd.to_numeric(frame[lookup["close"]], errors="coerce"),
            "volume": pd.to_numeric(frame[lookup["volume"]], errors="coerce") if "volume" in lookup else 0,
            "currency": currency,
            "adjustment_status": "unknown",
            "source_file": source_file,
            "ingested_at_utc": now,
        }
    )
    output = output.dropna(subset=["date", "open", "high", "low", "close"])
    if output.empty:
        return empty_price_bars_frame()
    invalid = output[(output["high"] < output["low"]) | (output["close"] < output["low"]) | (output["close"] > output["high"])]
    if not invalid.empty:
        raise ValueError(f"Invalid OHLC rows for {provider_symbol}: {len(invalid)}")
    return output[EQUITY_PRICE_BAR_COLUMNS].drop_duplicates(subset=["provider", "provider_symbol", "date"]).sort_values("date")


def parse_stooq_zip(path: str | Path) -> pd.DataFrame:
    zip_path = Path(path)
    frames = []
    parsed_count = 0
    skipped_empty = 0
    failed = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            member = info.filename
            if info.is_dir() or member.endswith("/") or not member.lower().endswith((".csv", ".txt")):
                continue
            if info.file_size == 0:
                skipped_empty += 1
                continue
            provider_symbol = Path(member).stem.lower()
            try:
                raw = archive.read(member).decode("utf-8", errors="replace")
                frame = parse_stooq_csv(raw, provider_symbol=provider_symbol, source_file=f"{zip_path}:{member}")
            except (EmptyDataError, ParserError, UnicodeError, ValueError) as exc:
                failed += 1
                logger.debug("Skipping invalid Stooq member %s: %s", member, exc)
                continue
            if frame.empty:
                skipped_empty += 1
                continue
            frames.append(frame)
            parsed_count += 1
    logger.info(
        "Parsed Stooq ZIP %s: parsed %s files, skipped %s empty files, failed %s files.",
        zip_path,
        parsed_count,
        skipped_empty,
        failed,
    )
    if not frames:
        return empty_price_bars_frame()
    return pd.concat(frames, ignore_index=True)


def _download_symbol(symbol: str) -> str:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Stooq equity price history for stock momentum.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    parser.add_argument("--file", help="Path to a Stooq CSV file.")
    parser.add_argument("--zip", dest="zip_path", help="Path to a Stooq ZIP archive.")
    parser.add_argument("--symbol", help="Stooq symbol for --file or per-symbol download mode.")
    parser.add_argument("--currency", help="Trading currency override.")
    return parser.parse_args()


def main() -> int:
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

    args = parse_args()
    load_config(args.config)
    if args.zip_path:
        frame = parse_stooq_zip(args.zip_path)
        manifest_path = Path(args.zip_path)
    else:
        if args.file:
            raw = Path(args.file).read_text(encoding="utf-8")
            manifest_path = Path(args.file)
            symbol = args.symbol or Path(args.file).stem
        elif args.symbol:
            raw = _download_symbol(args.symbol)
            raw_dir = Path("derived/stock_momentum/raw/stooq/symbols")
            raw_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = raw_dir / f"{args.symbol}.csv"
            manifest_path.write_text(raw, encoding="utf-8")
            symbol = args.symbol
        else:
            raise SystemExit("Provide --zip, --file, or --symbol.")
        frame = parse_stooq_csv(raw, provider_symbol=symbol, source_file=str(manifest_path), currency=args.currency)

    manifest = file_manifest("stooq", manifest_path, row_count=len(frame))
    with DatabaseConnection(config=get_database_config()) as db:
        repo = DataRepository(db)
        repo.save_dataframe(manifest, "ingestion_manifests")
        repo.save_dataframe(frame, "equity_price_bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
