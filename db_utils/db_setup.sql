-- Create Tables
DROP TABLE IF EXISTS assets_prices;
DROP TABLE IF EXISTS stock_prices;

CREATE SCHEMA IF NOT EXISTS eodhd;

CREATE TABLE IF NOT EXISTS eodhd.exchange_snapshots (
    snapshot_date DATE NOT NULL, exchange_code TEXT NOT NULL, name TEXT, country TEXT,
    currency TEXT, operating_mic TEXT, raw_json JSONB NOT NULL, source_file TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, exchange_code)
);
CREATE TABLE IF NOT EXISTS eodhd.symbol_snapshots (
    snapshot_date DATE NOT NULL, eodhd_symbol TEXT NOT NULL, exchange_code TEXT NOT NULL,
    code TEXT, name TEXT, country TEXT, currency TEXT, security_type TEXT, isin TEXT,
    is_delisted BOOLEAN NOT NULL, request_type_filter TEXT NOT NULL, raw_json JSONB NOT NULL,
    source_file TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, eodhd_symbol, is_delisted, request_type_filter)
);
CREATE TABLE IF NOT EXISTS eodhd.eod_prices (
    eodhd_symbol TEXT NOT NULL, exchange_code TEXT NOT NULL, date DATE NOT NULL,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, adjusted_close NUMERIC,
    volume BIGINT, is_delisted_from_symbol_list BOOLEAN NOT NULL, requested_period TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ, source_file TEXT NOT NULL,
    PRIMARY KEY (eodhd_symbol, date, is_delisted_from_symbol_list, requested_period)
);
CREATE TABLE IF NOT EXISTS eodhd.dividends (
    eodhd_symbol TEXT NOT NULL, exchange_code TEXT NOT NULL, date DATE,
    declaration_date DATE, record_date DATE, payment_date DATE, value NUMERIC,
    unadjusted_value NUMERIC, currency TEXT, period TEXT,
    is_delisted_from_symbol_list BOOLEAN NOT NULL, retrieved_at TIMESTAMPTZ,
    event_hash TEXT NOT NULL, raw_json JSONB NOT NULL, source_file TEXT NOT NULL,
    PRIMARY KEY (eodhd_symbol, event_hash)
);
CREATE TABLE IF NOT EXISTS eodhd.splits (
    eodhd_symbol TEXT NOT NULL, exchange_code TEXT NOT NULL, date DATE, split TEXT,
    is_delisted_from_symbol_list BOOLEAN NOT NULL, retrieved_at TIMESTAMPTZ,
    event_hash TEXT NOT NULL, raw_json JSONB NOT NULL, source_file TEXT NOT NULL,
    PRIMARY KEY (eodhd_symbol, event_hash)
);
CREATE TABLE IF NOT EXISTS eodhd.symbol_changes (
    exchange_code TEXT NOT NULL, old_symbol TEXT NOT NULL, new_symbol TEXT NOT NULL,
    company_name TEXT, effective_date DATE NOT NULL, snapshot_date DATE NOT NULL,
    raw_json JSONB NOT NULL, source_file TEXT NOT NULL,
    PRIMARY KEY (exchange_code, old_symbol, new_symbol, effective_date)
);
CREATE TABLE IF NOT EXISTS eodhd.ingestion_artifacts (
    parquet_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, dataset TEXT NOT NULL,
    row_count BIGINT NOT NULL, ingested_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW eodhd.latest_exchanges AS
SELECT * FROM eodhd.exchange_snapshots
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM eodhd.exchange_snapshots);

CREATE OR REPLACE VIEW eodhd.latest_symbols AS
SELECT * FROM eodhd.symbol_snapshots
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM eodhd.symbol_snapshots);

CREATE OR REPLACE VIEW public.eodhd_stock_prices_raw AS
SELECT eodhd_symbol AS symbol, exchange_code, date, open, high, low, close, volume
FROM (
    SELECT p.*, ROW_NUMBER() OVER (
        PARTITION BY eodhd_symbol, date
        ORDER BY is_delisted_from_symbol_list ASC, retrieved_at DESC NULLS LAST, source_file
    ) AS row_number
    FROM eodhd.eod_prices p
) ranked WHERE row_number = 1;

CREATE OR REPLACE VIEW public.eodhd_stock_prices_adjusted AS
SELECT eodhd_symbol AS symbol, exchange_code, date, open, high, low,
       COALESCE(adjusted_close, close) AS close, volume
FROM (
    SELECT p.*, ROW_NUMBER() OVER (
        PARTITION BY eodhd_symbol, date
        ORDER BY is_delisted_from_symbol_list ASC, retrieved_at DESC NULLS LAST, source_file
    ) AS row_number
    FROM eodhd.eod_prices p
) ranked WHERE row_number = 1;

CREATE TABLE IF NOT EXISTS interest_rates (
    date DATE NOT NULL,
    region VARCHAR(50) NOT NULL,
    rate_type VARCHAR(50) NOT NULL,
    maturity VARCHAR(20) NOT NULL,
    interest_rate NUMERIC(10, 4) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    PRIMARY KEY (date, region, maturity, currency)
);

CREATE TABLE IF NOT EXISTS indices (
    id VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    index_name VARCHAR(50) NOT NULL,
    value NUMERIC(16, 2),
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS commodity_prices (
    symbol VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(16, 4),
    high NUMERIC(16, 4),
    low NUMERIC(16, 4),
    close NUMERIC(16, 4),
    volume BIGINT,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS macro_data (
    id VARCHAR(18) NOT NULL,
    date DATE NOT NULL,
    long_name VARCHAR(80) NOT NULL,
    value NUMERIC,
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS test_data (
    id VARCHAR(18) NOT NULL,
    date DATE NOT NULL,
    long_name VARCHAR(80) NOT NULL,
    value NUMERIC,
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS factor_returns (
    source TEXT NOT NULL,
    factor_set TEXT NOT NULL,
    frequency CHAR(1) NOT NULL,
    factor TEXT NOT NULL,
    date DATE NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL DEFAULT 'decimal',
    PRIMARY KEY (source, factor_set, frequency, factor, date)
);

CREATE INDEX IF NOT EXISTS idx_factor_returns_set_freq_factor_date
    ON factor_returns (factor_set, frequency, factor, date);
CREATE INDEX IF NOT EXISTS idx_factor_returns_date
    ON factor_returns (date);

CREATE TABLE IF NOT EXISTS portfolio_returns (
    source TEXT NOT NULL,
    portfolio_set TEXT NOT NULL,
    universe TEXT NOT NULL,
    frequency CHAR(1) NOT NULL,
    portfolio TEXT NOT NULL,
    date DATE NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL DEFAULT 'decimal',
    PRIMARY KEY (source, portfolio_set, universe, frequency, portfolio, date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_returns_set_universe_freq_portfolio_date
    ON portfolio_returns (portfolio_set, universe, frequency, portfolio, date);
CREATE INDEX IF NOT EXISTS idx_portfolio_returns_date
    ON portfolio_returns (date);

CREATE TABLE IF NOT EXISTS characteristic_metadata (
    source TEXT NOT NULL,
    characteristic_set TEXT NOT NULL,
    characteristic TEXT NOT NULL,
    name TEXT,
    category TEXT,
    paper_ref TEXT,
    notes TEXT,
    PRIMARY KEY (source, characteristic_set, characteristic)
);

CREATE INDEX IF NOT EXISTS idx_characteristic_metadata_set_characteristic
    ON characteristic_metadata (characteristic_set, characteristic);

CREATE TABLE IF NOT EXISTS portfolio_characteristics (
    source TEXT NOT NULL,
    portfolio_set TEXT NOT NULL,
    universe TEXT NOT NULL,
    frequency CHAR(1) NOT NULL,
    portfolio TEXT NOT NULL,
    date DATE NOT NULL,
    characteristic TEXT NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL DEFAULT 'raw',
    PRIMARY KEY (source, portfolio_set, universe, frequency, portfolio, date, characteristic)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_characteristics_set_freq_char_date
    ON portfolio_characteristics (portfolio_set, frequency, characteristic, date);
CREATE INDEX IF NOT EXISTS idx_portfolio_characteristics_date
    ON portfolio_characteristics (date);

CREATE TABLE IF NOT EXISTS ingestion_manifests (
    manifest_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    local_path TEXT,
    downloaded_at_utc TIMESTAMP,
    sha256 TEXT,
    byte_size BIGINT,
    row_count INTEGER,
    status TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (manifest_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL,
    profile TEXT NOT NULL,
    config_path TEXT,
    config_sha256 TEXT,
    git_commit_hash TEXT,
    run_started_at_utc TIMESTAMP,
    run_finished_at_utc TIMESTAMP,
    status TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS securities (
    security_id TEXT NOT NULL,
    isin TEXT,
    name TEXT NOT NULL,
    security_type TEXT,
    country TEXT,
    currency_primary TEXT,
    source_first_seen TEXT NOT NULL,
    source_last_seen TEXT NOT NULL,
    active_flag_current BOOLEAN NOT NULL,
    created_at_utc TIMESTAMP NOT NULL,
    updated_at_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (security_id)
);

CREATE INDEX IF NOT EXISTS idx_securities_isin
    ON securities (isin);

CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    exchange_code TEXT,
    mic TEXT,
    trading_currency TEXT,
    isin TEXT,
    name TEXT,
    first_seen_date DATE,
    last_seen_date DATE,
    is_currently_tradable BOOLEAN,
    source_file TEXT,
    PRIMARY KEY (listing_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_security_id
    ON listings (security_id);
CREATE INDEX IF NOT EXISTS idx_listings_provider_symbol
    ON listings (provider, provider_symbol);

CREATE TABLE IF NOT EXISTS equity_price_bars (
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    security_id TEXT,
    listing_id TEXT,
    date DATE NOT NULL,
    open NUMERIC(20, 6),
    high NUMERIC(20, 6),
    low NUMERIC(20, 6),
    close NUMERIC(20, 6),
    volume NUMERIC(24, 4),
    currency TEXT,
    adjustment_status TEXT NOT NULL,
    source_file TEXT,
    ingested_at_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (provider, provider_symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_equity_price_bars_security_date
    ON equity_price_bars (security_id, date);
CREATE INDEX IF NOT EXISTS idx_equity_price_bars_listing_date
    ON equity_price_bars (listing_id, date);

CREATE TABLE IF NOT EXISTS fx_rates (
    date DATE NOT NULL,
    currency TEXT NOT NULL,
    units_per_eur NUMERIC(20, 8) NOT NULL,
    source TEXT NOT NULL,
    ingested_at_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (date, currency, source)
);

CREATE TABLE IF NOT EXISTS equity_prices_eur (
    security_id TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    date DATE NOT NULL,
    price_local NUMERIC(20, 6),
    currency TEXT NOT NULL,
    units_per_eur NUMERIC(20, 8),
    price_eur NUMERIC(20, 6),
    is_fx_forward_filled BOOLEAN NOT NULL,
    source_price_file TEXT,
    source_fx_file TEXT,
    PRIMARY KEY (security_id, listing_id, provider, date)
);

CREATE INDEX IF NOT EXISTS idx_equity_prices_eur_date
    ON equity_prices_eur (date);

CREATE TABLE IF NOT EXISTS equity_eligibility (
    security_id TEXT NOT NULL,
    date DATE NOT NULL,
    eligible_price_available BOOLEAN NOT NULL,
    eligible_min_history BOOLEAN NOT NULL,
    eligible_min_price BOOLEAN NOT NULL,
    eligible_missingness BOOLEAN NOT NULL,
    eligible_security_type BOOLEAN NOT NULL,
    eligible_current_tradable_proxy BOOLEAN NOT NULL,
    eligible_final BOOLEAN NOT NULL,
    ineligibility_reason TEXT,
    PRIMARY KEY (security_id, date)
);

CREATE TABLE IF NOT EXISTS stock_momentum_panels (
    strategy_family TEXT NOT NULL,
    profile TEXT NOT NULL,
    rebalance_frequency TEXT NOT NULL,
    rebalance_date DATE NOT NULL,
    signal_date DATE NOT NULL,
    execution_date DATE NOT NULL,
    security_id TEXT NOT NULL,
    listing_id TEXT,
    provider_symbol TEXT,
    name TEXT,
    currency TEXT,
    price_eur_signal NUMERIC(20, 6),
    price_eur_lookback NUMERIC(20, 6),
    momentum_3m NUMERIC,
    momentum_6m NUMERIC,
    momentum_9m NUMERIC,
    momentum_12m NUMERIC,
    momentum_12_1m NUMERIC,
    volatility_3m NUMERIC,
    volatility_6m NUMERIC,
    volatility_12m NUMERIC,
    rank_metric NUMERIC,
    rank_ascending_false INTEGER,
    eligible_final BOOLEAN NOT NULL,
    run_id TEXT,
    PRIMARY KEY (strategy_family, profile, rebalance_frequency, rebalance_date, security_id)
);

CREATE TABLE IF NOT EXISTS stock_momentum_trades (
    strategy_id TEXT NOT NULL,
    rebalance_date DATE NOT NULL,
    execution_date DATE NOT NULL,
    security_id TEXT NOT NULL,
    provider_symbol TEXT,
    side TEXT NOT NULL,
    target_weight NUMERIC NOT NULL,
    previous_weight NUMERIC NOT NULL,
    trade_weight NUMERIC NOT NULL,
    price_eur NUMERIC(20, 6),
    gross_trade_value_eur NUMERIC(20, 6),
    transaction_cost_eur NUMERIC(20, 6),
    rationale_rank INTEGER,
    rationale_momentum NUMERIC,
    run_id TEXT,
    PRIMARY KEY (strategy_id, rebalance_date, security_id, side)
);

CREATE TABLE IF NOT EXISTS stock_momentum_results (
    strategy_id TEXT NOT NULL,
    rebalance_frequency TEXT NOT NULL,
    top_n INTEGER NOT NULL,
    lookback_months INTEGER NOT NULL,
    skip_recent_months INTEGER NOT NULL,
    weighting_scheme TEXT NOT NULL,
    transaction_cost_bps_one_way NUMERIC NOT NULL,
    start_date DATE,
    end_date DATE,
    total_return NUMERIC,
    cagr NUMERIC,
    annualized_volatility NUMERIC,
    sharpe_ratio NUMERIC,
    max_drawdown NUMERIC,
    turnover NUMERIC,
    rebalance_count INTEGER,
    trade_count INTEGER,
    run_id TEXT,
    PRIMARY KEY (
        strategy_id,
        rebalance_frequency,
        top_n,
        lookback_months,
        skip_recent_months,
        weighting_scheme,
        transaction_cost_bps_one_way
    )
);

-- Derived views

-- Create a view for derived Shiller CAPE data
CREATE OR REPLACE VIEW shiller_derived_view AS
-- Define the derived data
WITH sp_comp_price AS (
    SELECT date, value FROM macro_data WHERE id = 'sp_comp_price'
),
sp_comp_div AS (
    SELECT date, value FROM macro_data WHERE id = 'sp_comp_div'
),
sp_comp_earn AS (
    SELECT date, value FROM macro_data WHERE id = 'sp_comp_earn'
),
rate_gs10 AS (
    SELECT date, value FROM macro_data WHERE id = 'rate_gs10'
),
cpi AS (
    SELECT date, value FROM macro_data WHERE id = 'cpi'
),
cpi_factor AS (
    SELECT 
        date,
        LAST_VALUE(value) OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) / value AS value 
    FROM cpi
),
real_price AS (
    SELECT
        sp_comp_price.date,
        (sp_comp_price.value * cpi_factor.value) AS value
    FROM sp_comp_price
    JOIN cpi_factor ON sp_comp_price.date = cpi_factor.date
),
real_div AS (
    SELECT
        sp_comp_div.date,
        (sp_comp_div.value * cpi_factor.value) AS value
    FROM sp_comp_div
    JOIN cpi_factor ON sp_comp_div.date = cpi_factor.date
),
real_earn AS (
    SELECT
        sp_comp_earn.date,
        (sp_comp_earn.value * cpi_factor.value) AS value
    FROM sp_comp_earn
    JOIN cpi_factor ON sp_comp_earn.date = cpi_factor.date
),
real_totret_price AS (
        SELECT
            date, 
            EXP(
            SUM(LN(tr_contribution)) OVER (ORDER BY date)
            ) AS value
    FROM (
        SELECT
            real_price.date AS date,
                COALESCE(
                    (
                        real_price.value + 
                        (1.0/12.0) * COALESCE(real_div.value, 0))/ 
                    LAG(real_price.value) OVER (ORDER BY real_price.date),
                    real_price.value
                ) AS tr_contribution
        FROM real_price
        JOIN real_div ON real_price.date = real_div.date
    ) AS contributions
),
real_tr_sc_earn AS (
    SELECT
        real_earn.date as date,
        (real_earn.value * real_totret_price.value / real_price.value) AS value
    FROM real_earn
    JOIN real_price ON real_earn.date = real_price.date
    JOIN real_totret_price ON real_earn.date = real_totret_price.date
),
cape_ratio AS (
    SELECT
        real_price.date as date,
        real_price.value / (
            CASE 
                WHEN COUNT(*) OVER (
                    ORDER BY real_earn.date
                    ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING
                ) = 120 THEN 
                    AVG(real_earn.value) OVER (
                        ORDER BY real_earn.date
                        ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING
                    )
                ELSE NULL
            END
        ) AS value
    FROM real_price
    JOIN real_earn ON real_price.date = real_earn.date
),
cape_tr_sc AS (
    SELECT
        real_totret_price.date as date,
        real_totret_price.value / (
            CASE 
                WHEN COUNT(*) OVER (
                    ORDER BY real_tr_sc_earn.date
                    ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING
                ) = 120 THEN 
                    AVG(real_tr_sc_earn.value) OVER (
                        ORDER BY real_tr_sc_earn.date
                        ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING
                    )
                ELSE NULL
            END
        ) AS value
    FROM real_totret_price
    JOIN real_tr_sc_earn ON real_totret_price.date = real_tr_sc_earn.date
),
sp_exc_cape_yield AS (
    SELECT
        cape_ratio.date as date,
        (1 / cape_ratio.value -
        rate_gs10.value * 0.01 +
        (cpi.value / LAG(cpi.value, 120) OVER (ORDER BY cpi.date))^(1.0/10.0)
        - 1
        ) as value
    FROM cape_ratio
    JOIN rate_gs10 ON cape_ratio.date = rate_gs10.date
    JOIN cpi ON cape_ratio.date = cpi.date
),
m_tot_bond_ret AS (
    with forward_looking_rate as (
        SELECT
            date,
            value,
            LEAD(value) OVER (ORDER BY date) as next_value
        FROM rate_gs10
    )
    SELECT
        date,
        (
            value / next_value +
            value / 1200 +
            (1+next_value/1200)^(-119) *
            (1-value/next_value)
        ) as value
    FROM forward_looking_rate
),
r_tot_bond_ret AS (
    SELECT
        m_tot_bond_ret.date,
        (
            COALESCE(EXP(SUM(LN(m_tot_bond_ret.value)) OVER (ORDER BY m_tot_bond_ret.date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)), 1) *
            FIRST_VALUE(cpi.value) OVER (ORDER BY cpi.date) / cpi.value
        )  as value
    FROM m_tot_bond_ret
    JOIN cpi ON m_tot_bond_ret.date = cpi.date
),
r_ann_stock_ret AS (
    SELECT
        real_totret_price.date,
        'r_ann_stock_ret' AS id,
        '10-Year Annualized Stock Real Return' AS long_name,
        (
            POWER(LEAD(real_totret_price.value, 120) OVER (ORDER BY real_totret_price.date) / 
            real_totret_price.value, 1.0/10.0) - 1
        ) AS value
    FROM real_totret_price
),
r_ann_bonds_ret AS (
    SELECT
        date,
        'r_ann_bonds_ret' AS id,
        '10-Year Annualized Bonds Real Return' AS long_name,
        (POWER(LEAD(value, 120) OVER (ORDER BY date) / value, 1.0/10.0) - 1) AS value
    FROM r_tot_bond_ret
),
r_10y_exc_ann_ret AS (
    SELECT
        r_ann_stock_ret.date as date,
        'r_10y_exc_ann_ret' AS id,
        'Real 10-Year Excess Annualized Returns' AS long_name,
        (r_ann_stock_ret.value - r_ann_bonds_ret.value) AS value
    FROM r_ann_stock_ret
    JOIN r_ann_bonds_ret ON r_ann_stock_ret.date = r_ann_bonds_ret.date
)

-- Real S&P Composite Price
SELECT
    real_price.date,
    'r_sp_price' AS id,
    'Real S&P Composite Price' AS long_name,
    value AS value
FROM real_price

UNION ALL

-- Real S&P Composite Dividend
SELECT
    real_div.date,
    'r_sp_div' AS id,
    'Real S&P Composite Dividend' AS long_name,
    value AS value
FROM real_div

UNION ALL

-- Real Total Return Price
SELECT
    date,
    'r_totret_price' AS id,
    'Real Total Return Price' AS long_name,
    value
FROM real_totret_price

UNION ALL

-- Real S&P Composite Earnings
SELECT
    date,
    'r_sp_earn' AS id,
    'Real S&P Composite Earnings' AS long_name,
    value
FROM real_earn

UNION ALL

-- Real Total Return Scaled Earnings
SELECT
    date,
    'r_tr_sc_earn' AS id,
    'Real S&P Composite Total Return Scaled Earnings' AS long_name,
    value 
FROM real_tr_sc_earn

UNION ALL

-- Cyclically Adjusted Price Earnings Ratio (CAPE)
SELECT
    date,
    'sp_cape' AS id,
    'Cyclically Adjusted S&P Composite Price Earnings Ratio (CAPE)' AS long_name,
    value 
FROM cape_ratio

UNION ALL

-- Cyclically Adjusted Total Return Price Earnings Ratio (TR CAPE)
SELECT
    date,
    'sp_tr_cape' AS id,
    'Cyclically Adjusted S&P Composite Total Return Price Earnings Ratio (TR CAPE)' AS long_name,
    value 
FROM cape_tr_sc

UNION ALL

-- Excess CAPE Yield
SELECT
    date,
    'sp_exc_cape_yield' AS id,
    'Excess S&P Composite CAPE Yield' AS long_name,
    value
FROM sp_exc_cape_yield

UNION ALL

-- Monthly Total Bond Returns
SELECT
    date,
    'm_tot_bond_ret' AS id,
    'Monthly Total Bond Returns' AS long_name,
    value
FROM m_tot_bond_ret

UNION ALL

-- Real Total Bond Returns
SELECT
    date,
    'r_tot_bond_ret' AS id,
    'Real Total Bond Returns' AS long_name,
    value
FROM r_tot_bond_ret

UNION ALL

-- 10-Year Annualized Stock Real Return
SELECT
    date,
    'r_ann_stock_ret' AS id,
    '10-Year Annualized Stock Real Return' AS long_name,
    value
FROM r_ann_stock_ret

UNION ALL

-- 10-Year Annualized Bonds Real Return
SELECT
    date,
    'r_ann_bonds_ret' AS id,
    '10-Year Annualized Bonds Real Return' AS long_name,
    value
FROM r_ann_bonds_ret

UNION ALL

-- Real 10-Year Excess Annualized Returns
SELECT
    date,
    'r_10y_exc_ann_ret' AS id,
    'Real 10-Year Excess Annualized Returns' AS long_name,
    value
FROM r_10y_exc_ann_ret;
