from __future__ import annotations

import argparse

from analyses.stock_momentum.config import artifact_dir, load_config
from db_utils.database import build_engine, read_sql


LIMITATIONS = """# Stock Momentum Data Quality Report

## Known Limitations

1. The free prototype uses a current tradability proxy, not a historical point-in-time broker universe.
2. Delisted securities are not reliably included.
3. Stooq adjustment status is not treated as institutional-quality total-return data.
4. Identifier mapping is incomplete and partly manual.
5. Results are useful for engineering and signal intuition, not final allocation decisions.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate stock momentum prototype outputs.")
    parser.add_argument("--config", default="config/stock_momentum_free.toml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    engine = build_engine()
    counts = {
        "securities": read_sql(engine, "SELECT COUNT(*) AS count FROM securities").loc[0, "count"],
        "listings": read_sql(engine, "SELECT COUNT(*) AS count FROM listings").loc[0, "count"],
        "equity_price_bars": read_sql(engine, "SELECT COUNT(*) AS count FROM equity_price_bars").loc[0, "count"],
        "fx_rates": read_sql(engine, "SELECT COUNT(*) AS count FROM fx_rates").loc[0, "count"],
    }
    report = LIMITATIONS + "\n## Row Counts\n\n" + "\n".join(f"- {name}: {count}" for name, count in counts.items()) + "\n"
    out_dir = artifact_dir(config) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock_momentum_data_quality_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
