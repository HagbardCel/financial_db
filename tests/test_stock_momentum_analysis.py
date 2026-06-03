from __future__ import annotations

import pandas as pd
import pytest

from analyses.stock_momentum.backtest import build_trades, target_weights
from analyses.stock_momentum.fx import convert_prices_to_eur
from analyses.stock_momentum.eligibility import build_daily_eligibility
from analyses.stock_momentum.signals import build_momentum_panel, momentum


def test_fx_conversion_uses_units_per_eur_and_eur_special_case():
    prices = pd.DataFrame(
        [
            {
                "security_id": "A",
                "listing_id": "A",
                "provider": "stooq",
                "provider_symbol": "a.us",
                "date": "2024-01-02",
                "close": 110.0,
                "currency": "USD",
                "source_file": "prices.csv",
            },
            {
                "security_id": "B",
                "listing_id": "B",
                "provider": "stooq",
                "provider_symbol": "b.de",
                "date": "2024-01-02",
                "close": 50.0,
                "currency": "EUR",
                "source_file": "prices.csv",
            },
        ]
    )
    rates = pd.DataFrame([{"date": "2024-01-02", "currency": "USD", "units_per_eur": 1.1}])

    converted = convert_prices_to_eur(prices, rates)

    usd = converted[converted["security_id"] == "A"].iloc[0]
    eur = converted[converted["security_id"] == "B"].iloc[0]
    assert usd["price_eur"] == pytest.approx(100.0)
    assert eur["price_eur"] == pytest.approx(50.0)
    assert usd["is_fx_forward_filled"] == False


def test_fx_conversion_marks_only_prior_rate_as_forward_filled():
    prices = pd.DataFrame([{"security_id": "A", "listing_id": "A", "provider": "eodhd", "provider_symbol": "A.US", "date": "2024-01-03", "close": 110, "currency": "USD", "source_file": "a"}])
    rates = pd.DataFrame([{"date": "2024-01-02", "currency": "USD", "units_per_eur": 1.1}])
    converted = convert_prices_to_eur(prices, rates, profile="eodhd_us_v1")
    assert converted.loc[0, "fx_date"] == pd.Timestamp("2024-01-02").date()
    assert converted.loc[0, "is_fx_forward_filled"]
    assert converted.loc[0, "profile"] == "eodhd_us_v1"


def test_momentum_uses_signal_date_not_future_execution_jump():
    series = pd.Series(
        [100.0, 110.0, 1000.0],
        index=pd.to_datetime(["2023-01-31", "2024-01-31", "2024-02-01"]),
    )

    assert momentum(series, pd.Timestamp("2024-01-31"), 12) == pytest.approx(0.10)


def test_build_momentum_panel_sets_execution_after_signal():
    dates = pd.to_datetime(["2023-01-31", "2024-01-31", "2024-02-01"])
    prices = pd.DataFrame(
        {
            "security_id": ["A", "A", "A"],
            "listing_id": ["A", "A", "A"],
            "provider": ["stooq", "stooq", "stooq"],
            "provider_symbol": ["a", "a", "a"],
            "date": dates,
            "price_eur": [100.0, 120.0, 999.0],
            "currency": ["EUR", "EUR", "EUR"],
        }
    )

    panel = build_momentum_panel(prices, frequency="monthly")

    row = panel[panel["rebalance_date"] == pd.Timestamp("2024-01-31").date()].iloc[0]
    assert row["signal_date"] == pd.Timestamp("2024-01-31").date()
    assert row["execution_date"] == pd.Timestamp("2024-02-01").date()
    assert row["momentum_12m"] == pytest.approx(0.20)


def test_daily_eligibility_uses_xnys_sessions_and_raw_dollar_volume():
    dates = pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03", "2024-07-05"])
    prices = pd.DataFrame({"security_id": "A", "listing_id": "A", "provider": "eodhd", "provider_symbol": "A.US", "date": dates, "price_eur": 10})
    metrics = pd.DataFrame({"provider_symbol": "A.US", "date": dates, "dollar_volume": 2_000_000})
    output = build_daily_eligibility(prices, metrics, min_history_months=0, missingness_window_sessions=4, liquidity_window_sessions=2)
    assert pd.Timestamp("2024-07-04").date() not in set(output["date"])
    assert output.iloc[-1]["eligible_liquidity"]
    assert output.iloc[-1]["trailing_median_dollar_volume"] == 2_000_000


def test_momentum_panel_applies_signal_date_eligibility():
    dates = pd.to_datetime(["2023-01-31", "2024-01-31", "2024-02-01"])
    prices = pd.DataFrame({"security_id": "A", "listing_id": "A", "provider": "eodhd", "provider_symbol": "A.US", "date": dates, "price_eur": [100, 120, 121], "currency": "USD"})
    eligibility = pd.DataFrame([{"security_id": "A", "date": "2024-01-31", "eligible_final": False}])
    panel = build_momentum_panel(prices, eligibility)
    row = panel[panel["rebalance_date"] == pd.Timestamp("2024-01-31").date()].iloc[0]
    assert not row["eligible_final"]


def test_target_weights_and_trades_account_for_turnover_and_costs():
    panel = pd.DataFrame(
        [
            {
                "rebalance_date": "2024-01-31",
                "execution_date": "2024-02-01",
                "security_id": "A",
                "provider_symbol": "a",
                "eligible_final": True,
                "rank_metric": 0.2,
                "price_eur_signal": 100,
                "rank_ascending_false": 1,
            },
            {
                "rebalance_date": "2024-01-31",
                "execution_date": "2024-02-01",
                "security_id": "B",
                "provider_symbol": "b",
                "eligible_final": True,
                "rank_metric": 0.1,
                "price_eur_signal": 50,
                "rank_ascending_false": 2,
            },
        ]
    )

    weights = target_weights(panel, top_n=2)
    trades = build_trades(panel, "test", top_n=2, weighting_scheme="equal_weight", transaction_cost_bps_one_way=25)

    assert weights["target_weight"].sum() == pytest.approx(1.0)
    assert trades["transaction_cost_eur"].sum() == pytest.approx(0.0025)
