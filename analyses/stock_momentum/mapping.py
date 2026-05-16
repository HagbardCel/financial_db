from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_mapping_overrides(path: str | Path = "config/stock_momentum_mapping_overrides.csv") -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return frame
    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0)
    return frame


def apply_mapping_overrides(price_bars: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    if overrides.empty:
        return price_bars.copy()
    usable = overrides[overrides["confidence"] >= 0.95].copy()
    if usable.empty:
        return price_bars.copy()
    mapping = usable.set_index("stooq_symbol")[["security_id", "xetra_symbol"]].to_dict("index")
    output = price_bars.copy()
    for idx, row in output.iterrows():
        symbol = row["provider_symbol"]
        if symbol in mapping:
            output.at[idx, "security_id"] = mapping[symbol]["security_id"]
            output.at[idx, "listing_id"] = f"mapped:{mapping[symbol]['xetra_symbol'] or symbol}"
    return output
