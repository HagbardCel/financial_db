from typing import Any, Dict

# Table schemas defining columns and primary keys for each table
TABLE_SCHEMAS = {
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
    },
    'ingestion_manifests': {
        'columns': ['manifest_id', 'source', 'source_url', 'local_path', 'downloaded_at_utc', 'sha256', 'byte_size', 'row_count', 'status', 'notes'],
        'primary_keys': ['manifest_id']
    },
    'pipeline_runs': {
        'columns': ['run_id', 'strategy_family', 'profile', 'config_path', 'config_sha256', 'git_commit_hash', 'run_started_at_utc', 'run_finished_at_utc', 'status', 'notes'],
        'primary_keys': ['run_id']
    },
    'securities': {
        'columns': ['security_id', 'isin', 'name', 'security_type', 'country', 'currency_primary', 'source_first_seen', 'source_last_seen', 'active_flag_current', 'created_at_utc', 'updated_at_utc'],
        'primary_keys': ['security_id']
    },
    'listings': {
        'columns': ['listing_id', 'security_id', 'provider', 'provider_symbol', 'exchange_code', 'mic', 'trading_currency', 'isin', 'name', 'first_seen_date', 'last_seen_date', 'is_currently_tradable', 'source_file'],
        'primary_keys': ['listing_id']
    },
    'equity_price_bars': {
        'columns': ['provider', 'provider_symbol', 'security_id', 'listing_id', 'date', 'open', 'high', 'low', 'close', 'volume', 'currency', 'adjustment_status', 'source_file', 'ingested_at_utc'],
        'primary_keys': ['provider', 'provider_symbol', 'date']
    },
    'fx_rates': {
        'columns': ['date', 'currency', 'units_per_eur', 'source', 'ingested_at_utc'],
        'primary_keys': ['date', 'currency', 'source']
    },
    'equity_prices_eur': {
        'columns': ['security_id', 'listing_id', 'provider', 'provider_symbol', 'date', 'price_local', 'currency', 'units_per_eur', 'price_eur', 'is_fx_forward_filled', 'source_price_file', 'source_fx_file'],
        'primary_keys': ['security_id', 'listing_id', 'provider', 'date']
    },
    'equity_eligibility': {
        'columns': ['security_id', 'date', 'eligible_price_available', 'eligible_min_history', 'eligible_min_price', 'eligible_missingness', 'eligible_security_type', 'eligible_current_tradable_proxy', 'eligible_final', 'ineligibility_reason'],
        'primary_keys': ['security_id', 'date']
    },
    'stock_momentum_panels': {
        'columns': ['strategy_family', 'profile', 'rebalance_frequency', 'rebalance_date', 'signal_date', 'execution_date', 'security_id', 'listing_id', 'provider_symbol', 'name', 'currency', 'price_eur_signal', 'price_eur_lookback', 'momentum_3m', 'momentum_6m', 'momentum_9m', 'momentum_12m', 'momentum_12_1m', 'volatility_3m', 'volatility_6m', 'volatility_12m', 'rank_metric', 'rank_ascending_false', 'eligible_final', 'run_id'],
        'primary_keys': ['strategy_family', 'profile', 'rebalance_frequency', 'rebalance_date', 'security_id']
    },
    'stock_momentum_trades': {
        'columns': ['strategy_id', 'rebalance_date', 'execution_date', 'security_id', 'provider_symbol', 'side', 'target_weight', 'previous_weight', 'trade_weight', 'price_eur', 'gross_trade_value_eur', 'transaction_cost_eur', 'rationale_rank', 'rationale_momentum', 'run_id'],
        'primary_keys': ['strategy_id', 'rebalance_date', 'security_id', 'side']
    },
    'stock_momentum_results': {
        'columns': ['strategy_id', 'rebalance_frequency', 'top_n', 'lookback_months', 'skip_recent_months', 'weighting_scheme', 'transaction_cost_bps_one_way', 'start_date', 'end_date', 'total_return', 'cagr', 'annualized_volatility', 'sharpe_ratio', 'max_drawdown', 'turnover', 'rebalance_count', 'trade_count', 'run_id'],
        'primary_keys': ['strategy_id', 'rebalance_frequency', 'top_n', 'lookback_months', 'skip_recent_months', 'weighting_scheme', 'transaction_cost_bps_one_way']
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
