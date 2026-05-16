from __future__ import annotations

import argparse
import io
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyses.stock_momentum.config import load_config
from analyses.stock_momentum.manifests import file_manifest
from data_fetchers.download_utils import download_url_to_path
from db_utils.config import get_database_config
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository


def parse_ecb_csv(raw_csv: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(raw_csv))
    lower = {str(col).strip().lower(): col for col in frame.columns}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if {"date", "currency", "units_per_eur"}.issubset(lower):
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(frame[lower["date"]], errors="coerce").dt.date,
                "currency": frame[lower["currency"]].astype(str).str.upper(),
                "units_per_eur": pd.to_numeric(frame[lower["units_per_eur"]], errors="coerce"),
                "source": "ECB",
                "ingested_at_utc": now,
            }
        )
    elif {"time_period", "currency", "obs_value"}.issubset(lower):
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(frame[lower["time_period"]], errors="coerce").dt.date,
                "currency": frame[lower["currency"]].astype(str).str.upper(),
                "units_per_eur": pd.to_numeric(frame[lower["obs_value"]], errors="coerce"),
                "source": "ECB",
                "ingested_at_utc": now,
            }
        )
    else:
        date_col = lower.get("date") or lower.get("time_period")
        if not date_col:
            raise ValueError(f"Could not identify ECB date column. Columns: {frame.columns.tolist()}")
        wide = frame.rename(columns={date_col: "date"})
        out = wide.melt(id_vars=["date"], var_name="currency", value_name="units_per_eur")
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
        out["currency"] = out["currency"].astype(str).str.upper()
        out["units_per_eur"] = pd.to_numeric(out["units_per_eur"], errors="coerce")
        out["source"] = "ECB"
        out["ingested_at_utc"] = now

    out = out.dropna(subset=["date", "currency", "units_per_eur"])
    out = out[out["units_per_eur"] > 0]
    eur_dates = pd.DataFrame(
        {
            "date": sorted(out["date"].unique()),
            "currency": "EUR",
            "units_per_eur": 1.0,
            "source": "ECB",
            "ingested_at_utc": now,
        }
    )
    return pd.concat([out, eur_dates], ignore_index=True).drop_duplicates(subset=["date", "currency", "source"])


def build_ecb_download_url(config: dict, url_override: str | None = None) -> str:
    if url_override:
        return url_override
    source = config["sources"]["ecb_fx"]
    return f"{source['api_base'].rstrip('/')}/EXR/{source['series_key']}?format=csvdata"


def download_ecb_file(config: dict, url_override: str | None = None) -> tuple[Path, str]:
    url = build_ecb_download_url(config, url_override=url_override)
    raw_dir = Path(config["sources"]["ecb_fx"].get("raw_dir", "derived/stock_momentum/raw/ecb_fx"))
    path = raw_dir / "ecb_fx.csv"
    download_url_to_path(url, path, timeout=60)
    return path, url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest ECB EUR reference FX rates for stock momentum.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    parser.add_argument("--file", help="Local ECB CSV file.")
    parser.add_argument("--url", help="ECB CSV URL override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    source_url = None
    if args.file:
        path = Path(args.file)
        raw = path.read_text(encoding="utf-8")
    else:
        path, source_url = download_ecb_file(config, url_override=args.url)
        raw = path.read_text(encoding="utf-8")

    frame = parse_ecb_csv(raw)
    manifest = file_manifest("ecb_fx", path, source_url=source_url or args.url, row_count=len(frame))
    with DatabaseConnection(config=get_database_config()) as db:
        repo = DataRepository(db)
        repo.save_dataframe(manifest, "ingestion_manifests")
        repo.save_dataframe(frame, "fx_rates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
