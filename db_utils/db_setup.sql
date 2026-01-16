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
