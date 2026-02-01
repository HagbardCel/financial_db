from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import re

from analyses.db_timeseries import load_monthly_returns
from data_fetchers.factor_etfs import ETF_NAMES, ETF_SETS
from db_utils.config import get_database_config
from db_utils.database import build_engine, read_table


DEFAULT_AQR_MAP = {
    "Quality": {
        "portfolio_set": "qmj_10_deciles",
        "label_candidates": ["P10", "HI 10", "10", "HIGH"],
    },
    "Value": {
        "portfolio_set": "vme_portfolios",
        "portfolio_contains": ["VAL", "VALUE"],
        "portfolio_suffixes": ["VME_EQ", "US"],
        "label_candidates": ["HI", "HIGH", "TOP", "5", "10"],
    },
    "Momentum": {
        "portfolio_set": "vme_portfolios",
        "portfolio_contains": ["MOM", "MOMENTUM"],
        "portfolio_suffixes": ["VME_EQ", "US"],
        "label_candidates": ["HI", "HIGH", "TOP", "5", "10"],
    },
}

DEFAULT_FF_MAP = {
    "Value": {
        "portfolio_set": "10_Portfolios_Formed_on_BE-ME",
        "label_candidates": ["HI 10", "HI", "HIGH", "10"],
    },
    "Quality": {
        "portfolio_set": "10_Portfolios_Formed_on_OP",
        "label_candidates": ["HI 10", "HI", "HIGH", "10"],
    },
    "Momentum": {
        "portfolio_set": "10_Portfolios_Formed_on_Momentum",
        "label_candidates": ["HI PRIOR", "HI", "HIGH", "10"],
    },
}


def _find_label(labels: Iterable[str], candidates: List[str]) -> Optional[str]:
    labels_list = list(labels)
    upper_labels = {label.upper(): label for label in labels_list}

    for cand in candidates:
        cand_upper = cand.upper()
        if cand_upper in upper_labels:
            return upper_labels[cand_upper]

    for cand in candidates:
        cand_upper = cand.upper()
        for label in labels_list:
            if cand_upper in label.upper():
                return label

    return None


def _extract_numeric(label: str) -> Optional[int]:
    match = re.search(r"([0-9]+)", label)
    if not match:
        return None
    return int(match.group(1))


def _select_by_numeric(labels: Iterable[str]) -> Optional[str]:
    labeled: List[Tuple[int, str]] = []
    for label in labels:
        number = _extract_numeric(str(label))
        if number is not None:
            labeled.append((number, str(label)))
    if not labeled:
        return None
    labeled.sort(key=lambda item: (item[0], item[1]))
    return labeled[-1][1]


def _select_hi_label(labels: Iterable[str]) -> Optional[str]:
    candidates = [label for label in labels if "HI" in str(label).upper()]
    if not candidates:
        return None
    return _select_by_numeric(candidates) or candidates[-1]


def _load_portfolio_series(
    engine,
    source: str,
    portfolio_set: str,
    factor_label: str,
    label_candidates: List[str],
    universe_candidates: Optional[List[str]] = None,
    portfolio_contains: Optional[List[str]] = None,
    portfolio_suffixes: Optional[List[str]] = None,
) -> Tuple[Optional[pd.Series], Optional[str]]:
    df = read_table(
        engine,
        table="portfolio_returns",
        columns=["date", "universe", "portfolio", "value"],
        where="source = :source AND portfolio_set = :portfolio_set",
        params={"source": source, "portfolio_set": portfolio_set},
        order_by=["date"],
    )
    if df.empty:
        return None, None
    df["date"] = pd.to_datetime(df["date"])

    if universe_candidates:
        universe = _find_label(df["universe"].dropna().unique(), universe_candidates)
        if universe is None:
            universe_candidates = None
        else:
            df = df.loc[df["universe"] == universe].copy()
            if df.empty:
                return None, None

    if portfolio_contains:
        patterns = [pattern.upper() for pattern in portfolio_contains]
        mask = df["portfolio"].astype(str).apply(
            lambda value: any(pattern in value.upper() for pattern in patterns)
        )
        df = df.loc[mask].copy()
        if df.empty:
            return None, None

    if portfolio_suffixes:
        filtered = None
        for suffix in portfolio_suffixes:
            suffix_upper = suffix.upper()
            candidate = df.loc[
                df["portfolio"].astype(str).str.upper().str.endswith(suffix_upper)
            ].copy()
            if not candidate.empty:
                filtered = candidate
                break
        if filtered is None:
            return None, None
        df = filtered

    label = _find_label(df["portfolio"].unique(), label_candidates)
    if label is None:
        label = _select_hi_label(df["portfolio"].unique()) or _select_by_numeric(
            df["portfolio"].unique()
        )
        if label is None:
            return None, None

    series = (
        df.loc[df["portfolio"] == label, ["date", "value"]]
        .set_index("date")["value"]
        .sort_index()
        .rename(factor_label)
    )
    return series, label


def _load_portfolio_series_exact(
    engine,
    source: str,
    portfolio_set: str,
    portfolio: str,
    series_name: Optional[str] = None,
) -> Optional[pd.Series]:
    df = read_table(
        engine,
        table="portfolio_returns",
        columns=["date", "portfolio", "value"],
        where="source = :source AND portfolio_set = :portfolio_set AND portfolio = :portfolio",
        params={"source": source, "portfolio_set": portfolio_set, "portfolio": portfolio},
        order_by=["date"],
    )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    name = series_name or portfolio
    return df.set_index("date")["value"].sort_index().rename(name)


def _corr_table(left: pd.Series, right: pd.Series) -> Optional[float]:
    merged = pd.concat([left, right], axis=1).dropna()
    if merged.empty:
        return None
    return float(merged.iloc[:, 0].corr(merged.iloc[:, 1]))


def _corr_details(left: pd.Series, right: pd.Series) -> Dict[str, object]:
    merged = pd.concat([left, right], axis=1).dropna()
    if merged.empty:
        return {"correlation": None, "overlap_months": 0, "overlap_start": None, "overlap_end": None}
    return {
        "correlation": float(merged.iloc[:, 0].corr(merged.iloc[:, 1])),
        "overlap_months": int(merged.shape[0]),
        "overlap_start": merged.index.min(),
        "overlap_end": merged.index.max(),
    }


def _overlap_summary(series: Dict[str, pd.Series]) -> pd.DataFrame:
    records = []
    for label, ser in series.items():
        if ser is None or ser.empty:
            records.append({"series": label, "rows": 0, "min_date": None, "max_date": None})
        else:
            records.append(
                {
                    "series": label,
                    "rows": int(ser.dropna().shape[0]),
                    "min_date": ser.dropna().index.min(),
                    "max_date": ser.dropna().index.max(),
                }
            )
    return pd.DataFrame(records)


def _format_section(title: str, df: pd.DataFrame) -> str:
    lines = [title]
    if df.empty:
        lines.append("(no data)")
    else:
        lines.append(df.to_string(index=False))
    lines.append("")
    return "\n".join(lines)


def _format_selection(title: str, selections: Dict[str, str]) -> str:
    lines = [title]
    if not selections:
        lines.append("(no selections)")
        lines.append("")
        return "\n".join(lines)
    df = pd.DataFrame(
        [{"factor": factor, "portfolio": portfolio} for factor, portfolio in selections.items()]
    )
    lines.append(df.to_string(index=False))
    lines.append("")
    return "\n".join(lines)


def _format_etf_universe(etf_set: str, etf_map: Dict[str, str]) -> str:
    lines = ["ETF universe"]
    df = pd.DataFrame(
        [
            {"factor": factor, "ticker": ticker, "name": ETF_NAMES.get(ticker, "")}
            for ticker, factor in etf_map.items()
        ]
    )
    df = df.sort_values(["factor", "ticker"])
    lines.append(f"etf_set = {etf_set}")
    lines.append(df.to_string(index=False))
    lines.append("")
    return "\n".join(lines)


def _format_date_ranges(title: str, ranges: pd.DataFrame) -> str:
    lines = [title]
    if ranges.empty:
        lines.append("(no data)")
        lines.append("")
        return "\n".join(lines)
    lines.append(ranges.to_string(index=False))
    lines.append("")
    return "\n".join(lines)


def _format_diagnostics(items: List[str]) -> str:
    if not items:
        return "Diagnostics\nOK\n"
    return "Diagnostics\n" + "\n".join(f"- {item}" for item in items) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate ETF proxies vs AQR/Ken French portfolios.")
    parser.add_argument(
        "--etf-set",
        default="msci_world",
        choices=sorted(ETF_SETS.keys()),
        help="ETF universe to use (default: msci_world).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path("analyses") / "analyses_outputs"),
        help="Directory for analysis outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = build_engine(get_database_config())

    etf_map = ETF_SETS[args.etf_set]
    etf_returns = load_monthly_returns(engine, list(etf_map.keys()), column_map=etf_map)
    etf_momentum = etf_returns["Momentum"] if "Momentum" in etf_returns.columns else None

    aqr_series: Dict[str, pd.Series] = {}
    aqr_selection: Dict[str, str] = {}
    for factor, mapping in DEFAULT_AQR_MAP.items():
        series, label = _load_portfolio_series(
            engine,
            source="aqr",
            portfolio_set=mapping["portfolio_set"],
            factor_label=factor,
            label_candidates=mapping["label_candidates"],
            universe_candidates=mapping.get("universe_candidates"),
            portfolio_contains=mapping.get("portfolio_contains"),
            portfolio_suffixes=mapping.get("portfolio_suffixes"),
        )
        if series is not None:
            aqr_series[factor] = series
            if label:
                aqr_selection[factor] = label

    vme_momentum_comparisons = []
    momentum_indices_comparisons = []
    extra_series: Dict[str, pd.Series] = {}
    if etf_momentum is not None and not etf_momentum.dropna().empty:
        for aqr_label in [
            "MOM1_VME_EQ",
            "MOM2_VME_EQ",
            "MOM3_VME_EQ",
            "MOM1US",
            "MOM2US",
            "MOM3US",
        ]:
            series = _load_portfolio_series_exact(
                engine,
                source="aqr",
                portfolio_set="vme_portfolios",
                portfolio=aqr_label,
                series_name=f"AQR_{aqr_label}",
            )
            if series is None:
                continue
            extra_series[series.name] = series
            stats = _corr_details(series, etf_momentum)
            vme_momentum_comparisons.append({"aqr_series": aqr_label, **stats})

        for aqr_label in ["International", "U.S. Large Cap"]:
            series = _load_portfolio_series_exact(
                engine,
                source="aqr",
                portfolio_set="momentum_indices",
                portfolio=aqr_label,
                series_name=f"AQR_momentum_indices::{aqr_label}",
            )
            if series is None:
                continue
            extra_series[series.name] = series
            stats = _corr_details(series, etf_momentum)
            momentum_indices_comparisons.append({"aqr_series": aqr_label, **stats})

    ff_series: Dict[str, pd.Series] = {}
    ff_selection: Dict[str, str] = {}
    for factor, mapping in DEFAULT_FF_MAP.items():
        series, label = _load_portfolio_series(
            engine,
            source="ken_french",
            portfolio_set=mapping["portfolio_set"],
            factor_label=factor,
            label_candidates=mapping["label_candidates"],
        )
        if series is not None:
            ff_series[factor] = series
            if label:
                ff_selection[factor] = label

    diagnostics: List[str] = []
    for factor, mapping in DEFAULT_AQR_MAP.items():
        if factor not in aqr_series:
            diagnostics.append(
                f"Missing AQR series '{factor}' (portfolio_set={mapping['portfolio_set']}). "
                f"Run: python -m data_fetchers.aqr portfolios --sets {mapping['portfolio_set']} --refresh"
            )
    for factor, mapping in DEFAULT_FF_MAP.items():
        if factor not in ff_series:
            diagnostics.append(
                f"Missing Ken French series '{factor}' (portfolio_set={mapping['portfolio_set']}). "
                "Run: python -m data_fetchers.ken_french portfolios --sets "
                f"{mapping['portfolio_set']} --refresh"
            )
    if etf_returns.empty:
        diagnostics.append(
            f"No ETF returns loaded for etf_set='{args.etf_set}'. "
            "Run: python -m data_fetchers.factor_etfs"
        )
    else:
        etf_min = etf_returns.index.min()
        etf_max = etf_returns.index.max()
        for factor, series in aqr_series.items():
            if factor in etf_returns.columns:
                overlap = series.dropna().index.intersection(etf_returns[factor].dropna().index)
                if overlap.empty:
                    diagnostics.append(
                        f"No overlap between AQR '{factor}' and ETF '{factor}' "
                        f"(AQR: {series.index.min()} → {series.index.max()}, "
                        f"ETF: {etf_min} → {etf_max}). "
                        "Re-fetch ETF history with python -m data_fetchers.factor_etfs --start 1900-01-01."
                    )

    aqr_etf_records = []
    for factor, series in aqr_series.items():
        if factor in etf_returns.columns:
            corr = _corr_table(series, etf_returns[factor])
            aqr_etf_records.append({"factor": factor, "correlation": corr})

    ff_etf_records = []
    for factor, series in ff_series.items():
        if factor in etf_returns.columns:
            corr = _corr_table(series, etf_returns[factor])
            ff_etf_records.append({"factor": factor, "correlation": corr})

    aqr_ff_records = []
    for factor in sorted(set(aqr_series.keys()) & set(ff_series.keys())):
        corr = _corr_table(aqr_series[factor], ff_series[factor])
        aqr_ff_records.append({"factor": factor, "correlation": corr})

    aqr_etf_df = pd.DataFrame(aqr_etf_records)
    ff_etf_df = pd.DataFrame(ff_etf_records)
    aqr_ff_df = pd.DataFrame(aqr_ff_records)
    vme_momentum_df = pd.DataFrame(vme_momentum_comparisons)
    momentum_indices_df = pd.DataFrame(momentum_indices_comparisons)

    overlap = _overlap_summary(
        {
            **{f"AQR_{k}": v for k, v in aqr_series.items()},
            **{f"FF_{k}": v for k, v in ff_series.items()},
            **{f"ETF_{col}": etf_returns[col] for col in etf_returns.columns},
        }
    )
    summary_path = out_dir / "factor_etf_proxy_validation.txt"
    range_rows = []
    for factor, series in aqr_series.items():
        ser = series.dropna()
        if not ser.empty:
            range_rows.append(
                {
                    "series": f"AQR_{factor}",
                    "start_date": ser.index.min(),
                    "end_date": ser.index.max(),
                }
            )
    for factor, series in ff_series.items():
        ser = series.dropna()
        if not ser.empty:
            range_rows.append(
                {
                    "series": f"FF_{factor}",
                    "start_date": ser.index.min(),
                    "end_date": ser.index.max(),
                }
            )
    for factor in etf_returns.columns:
        ser = etf_returns[factor].dropna()
        if not ser.empty:
            range_rows.append(
                {
                    "series": f"ETF_{factor}",
                    "start_date": ser.index.min(),
                    "end_date": ser.index.max(),
                }
            )
    for name, series in extra_series.items():
        ser = series.dropna()
        if not ser.empty:
            range_rows.append(
                {
                    "series": name,
                    "start_date": ser.index.min(),
                    "end_date": ser.index.max(),
                }
            )
    ranges_df = pd.DataFrame(range_rows)

    sections = [
        _format_diagnostics(diagnostics),
        _format_etf_universe(args.etf_set, etf_map),
        _format_selection("AQR selection", aqr_selection),
        _format_selection("Ken French selection", ff_selection),
        _format_date_ranges("Series date ranges", ranges_df),
        _format_section("AQR vs ETF correlations", aqr_etf_df),
        _format_section("ETF Momentum vs AQR VME Momentum buckets", vme_momentum_df),
        _format_section("ETF Momentum vs AQR Momentum Indices", momentum_indices_df),
        _format_section("Ken French vs ETF correlations", ff_etf_df),
        _format_section("AQR vs Ken French cross-validation", aqr_ff_df),
        _format_section("Overlap summary", overlap),
    ]
    summary_path.write_text("\n".join(sections), encoding="utf-8")

    print(f"Outputs written to {summary_path}")


if __name__ == "__main__":
    main()
