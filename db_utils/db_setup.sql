-- Create Tables
CREATE TABLE IF NOT EXISTS assets_prices (
    id VARCHAR(14) NOT NULL,
    date DATE NOT NULL,
    price_usd NUMERIC(10, 2),
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS bonds_data (
    id VARCHAR(14) NOT NULL,
    date DATE NOT NULL,
    bond_type VARCHAR(50) NOT NULL,
    yield NUMERIC(10, 4),
    price NUMERIC(10, 2)
);

CREATE TABLE IF NOT EXISTS indices (
    id VARCHAR(14) NOT NULL,
    date DATE NOT NULL,
    index_name VARCHAR(50) NOT NULL,
    value NUMERIC(14, 2),
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS macro_data (
    id VARCHAR(14) NOT NULL,
    date DATE NOT NULL,
    long_name VARCHAR(50) NOT NULL,
    value NUMERIC(14, 2),
    PRIMARY KEY (id, date)
);

CREATE TABLE IF NOT EXISTS test_data (
    id VARCHAR(14) NOT NULL,
    date DATE NOT NULL,
    long_name VARCHAR(50) NOT NULL,
    value NUMERIC(14, 2),
    PRIMARY KEY (id, date)
);