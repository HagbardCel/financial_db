from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data_fetchers.eodhd.downloader import dataset_output_path
from data_fetchers.eodhd.materialization import build_curated_frames, validate_quality_report


def _membership(is_delisted: bool) -> dict:
    return {
        "build_id": "build", "eodhd_symbol": "A.US", "exchange_code": "US", "isin": "US0378331005",
        "isin_valid": True, "name": "A", "security_type": "Common Stock", "currency": "USD",
        "is_delisted": is_delisted, "membership_status": "selected_candidate",
    }


def _write_prices(root: Path, is_delisted: bool, rows: list[dict]) -> None:
    path = dataset_output_path(root, "eod_daily", "US", "A.US", is_delisted)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_curated_frames_scale_adjusted_ohlc_and_prefer_active_overlap(tmp_path: Path):
    _write_prices(tmp_path, True, [{"date": "2024-01-02", "open": 5, "high": 6, "low": 4, "close": 5, "adjusted_close": 5, "volume": 10}])
    _write_prices(tmp_path, False, [
        {"date": "2024-01-02", "open": 10, "high": 12, "low": 8, "close": 10, "adjusted_close": 5, "volume": 100},
        {"date": "2024-01-03", "open": 11, "high": 13, "low": 9, "close": 11, "adjusted_close": None, "volume": 100},
    ])

    frames = build_curated_frames(tmp_path, pd.DataFrame([_membership(False), _membership(True)]))

    assert frames.securities.loc[0, "security_id"] == "US0378331005"
    assert frames.listings.loc[0, "listing_id"] == "eodhd:A.US"
    assert len(frames.bars) == 1
    bar = frames.bars.iloc[0]
    assert bar["open"] == pytest.approx(5)
    assert bar["high"] == pytest.approx(6)
    assert bar["low"] == pytest.approx(4)
    assert bar["close"] == pytest.approx(5)
    assert bar["volume"] == 100
    assert frames.raw_metrics.loc[0, "dollar_volume"] == 1000
    assert len(frames.rejected_rows) == 1


def test_quality_report_rejects_partial_or_blocking_scan(tmp_path: Path):
    (tmp_path / "summary.json").write_text(json.dumps({"partial_scan": True}), encoding="utf-8")
    pd.DataFrame([{"status": "missing_file"}]).to_parquet(tmp_path / "symbol_quality.parquet")
    with pytest.raises(RuntimeError, match="partial"):
        validate_quality_report(tmp_path, allow_partial=False)
    assert validate_quality_report(tmp_path, allow_partial=True)
