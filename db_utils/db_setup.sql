-- Create Tables
CREATE TABLE IF NOT EXISTS assets_prices (
    id VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    price_usd NUMERIC(10, 2),
    PRIMARY KEY (id, date)
);

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

CREATE TABLE IF NOT EXISTS stock_prices (
    symbol VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(16, 4),
    high NUMERIC(16, 4),
    low NUMERIC(16, 4),
    close NUMERIC(16, 4),
    volume BIGINT,
    PRIMARY KEY (symbol, date)
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
