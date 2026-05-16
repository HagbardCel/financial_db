import pytest

from db_utils.database import (
    build_select_query,
    order_by_clause,
    validate_identifier,
    where_any,
    where_between,
    where_eq,
)


def test_validate_identifier_accepts_simple_names():
    assert validate_identifier("equity_price_bars") == "equity_price_bars"
    assert validate_identifier("date") == "date"
    assert validate_identifier("factor_set_1") == "factor_set_1"


@pytest.mark.parametrize("name", ["", "stock-prices", "1table", "table name", "table;DROP"])
def test_validate_identifier_rejects_invalid_names(name):
    with pytest.raises(ValueError):
        validate_identifier(name)


def test_build_select_query_with_aliases_and_filters():
    query = build_select_query(
        table="equity_price_bars",
        columns={"date": "date", "provider_symbol": "id", "close": "value"},
        where=[where_eq("provider_symbol", "symbol"), where_between("date", "start_date", "end_date")],
        order_by=[order_by_clause("date")],
    )
    assert query == (
        "SELECT date AS date, provider_symbol AS id, close AS value FROM equity_price_bars "
        "WHERE provider_symbol = :symbol AND date BETWEEN :start_date AND :end_date "
        "ORDER BY date ASC"
    )


def test_build_select_query_supports_wildcard_and_limit():
    query = build_select_query(
        table="macro_data",
        columns=["*"],
        where=[where_any("id", "ids")],
        order_by=[order_by_clause("date", descending=True)],
        limit_param="limit",
    )
    assert query == (
        "SELECT * FROM macro_data WHERE id = ANY(:ids) ORDER BY date DESC LIMIT :limit"
    )
