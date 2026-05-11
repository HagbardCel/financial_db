from __future__ import annotations

import pytest

from data_fetchers.bonds import DEFAULT_PROVIDER, TreasuryFetcher, parse_args


def test_parse_args_defaults_provider_to_fred():
    args = parse_args([])

    assert args.provider == DEFAULT_PROVIDER


def test_transform_raises_aggregated_error_when_all_series_fail():
    fetcher = TreasuryFetcher(
        start_date=__import__("datetime").date(2024, 1, 1),
        end_date=__import__("datetime").date(2024, 12, 31),
        db_config={},
    )
    fetcher.fetch_errors = {
        "1M:DGS1MO": "missing credentials",
        "10Y:DGS10": "provider error",
    }

    with pytest.raises(ValueError, match="FRED_API_KEY"):
        fetcher.transform({})
