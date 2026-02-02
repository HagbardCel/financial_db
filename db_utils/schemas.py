from typing import Dict, List, Any

# Table schemas defining columns and primary keys for each table
TABLE_SCHEMAS = {
    'assets_prices': {
        'columns': ['id', 'date', 'price_usd'],
        'primary_keys': ['id', 'date']
    },
    'interest_rates': {
        'columns': ['date', 'region', 'rate_type', 'maturity', 'interest_rate', 'currency'],
        'primary_keys': ['date', 'region', 'maturity', 'currency']
    },
    'indices': {
        'columns': ['id', 'date', 'index_name', 'value'],
        'primary_keys': ['id', 'date']
    },
    'macro_data': {
        'columns': ['id', 'date', 'long_name', 'value'],
        'primary_keys': ['id', 'date']
    },
    'test_data': {
        'columns': ['id', 'date', 'long_name', 'value'],
        'primary_keys': ['id', 'date']
    },
    'stock_prices': {
        'columns': ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume'],
        'primary_keys': ['symbol', 'date']
    },
    'commodity_prices': {
        'columns': ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume'],
        'primary_keys': ['symbol', 'date']
    },
    'factor_returns': {
        'columns': ['source', 'factor_set', 'frequency', 'factor', 'date', 'value', 'unit'],
        'primary_keys': ['source', 'factor_set', 'frequency', 'factor', 'date']
    },
    'portfolio_returns': {
        'columns': ['source', 'portfolio_set', 'universe', 'frequency', 'portfolio', 'date', 'value', 'unit'],
        'primary_keys': ['source', 'portfolio_set', 'universe', 'frequency', 'portfolio', 'date']
    },
    'characteristic_metadata': {
        'columns': ['source', 'characteristic_set', 'characteristic', 'name', 'category', 'paper_ref', 'notes'],
        'primary_keys': ['source', 'characteristic_set', 'characteristic']
    },
    'portfolio_characteristics': {
        'columns': ['source', 'portfolio_set', 'universe', 'frequency', 'portfolio', 'date', 'characteristic', 'value', 'unit'],
        'primary_keys': ['source', 'portfolio_set', 'universe', 'frequency', 'portfolio', 'date', 'characteristic']
    }
}

def get_schema(table_name: str) -> Dict[str, Any]:
    """
    Returns the schema for a given table name.
    
    Args:
        table_name: Name of the table to get the schema for.
        
    Returns:
        A dictionary containing 'columns' and 'primary_keys'.
        
    Raises:
        ValueError: If the table name is unknown.
    """
    if table_name not in TABLE_SCHEMAS:
        raise ValueError(f"Unknown table: {table_name}. Must be one of {list(TABLE_SCHEMAS.keys())}")
    return TABLE_SCHEMAS[table_name]
