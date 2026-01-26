# Phase 3 Implementation Plan: Standardized Data Fetching

This document details the plan for **Phase 3** of the roadmap: **Standardized Data Fetching**.
This phase focuses on enforcing a strict, consistent architecture for all data retrieval scripts. By the end of this phase, all data fetchers will inherit from a robust `BaseFetcher` class and share a common lifecycle (`fetch` -> `transform` -> `save`).

**Roadmap Reference**: Item #3 "Standardized Data Fetching" in `doc/roadmap.md`.

## Objective
To eliminate code duplication and inconsistency across data fetchers by:
1.  Finalizing the `BaseFetcher` abstract class with strict typing and error handling.
2.  Refactoring existing fetchers (`shiller_cape.py`, `bonds.py`) to adhere to this standard.
3.  Implementing a new fetcher (`stock_prices.py`) as a proof-of-concept for the standard.

---

## 1. Enhance the `BaseFetcher` Class
**Current State**: `data_fetchers/base_fetcher.py` exists but lacks robust error handling, logging, and rigid structure enforcement.

**Detailed Step-by-Step**:
1.  **Add Error Handling**: Wrap the pipeline steps in `try/except` blocks in the `run()` method.
2.  **Add Logging**: Replace `print` statements with Python's `logging` module.
3.  **Support Multi-Table Saves**: Update the `save` method (or the `run` loop) to handle use cases where one fetcher produces multiple tables (like `shiller_cape.py`).

**Proposed Code Pattern (`data_fetchers/base_fetcher.py`)**:
```python
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Union, Optional
import pandas as pd
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

class BaseFetcher(ABC):
    def __init__(self, db_config: Optional[dict] = None):
        self.db_config = db_config
        self.logger = logging.getLogger(self.__class__.__name__)
        logging.basicConfig(level=logging.INFO)

    @abstractmethod
    def fetch(self) -> Any:
        """Fetch raw data. Returns raw object (str path, dict, response, etc)."""
        pass

    @abstractmethod
    def transform(self, raw_data: Any) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """
        Clean data. 
        Returns either a single DataFrame OR a dict of {table_name: DataFrame} 
        for multi-table outputs.
        """
        pass

    def save(self, data: Union[pd.DataFrame, Dict[str, pd.DataFrame]], default_table_name: str = None):
        """
        Saves data to the database. Handles both single DF and dict of DFs.
        """
        with DatabaseConnection(config=self.db_config) as db:
            repo = DataRepository(db)
            
            if isinstance(data, dict):
                # Multi-table case: data = {'table_name': df, 'other_table': df2}
                for table, df in data.items():
                    self.logger.info(f"Saving {len(df)} rows to {table}...")
                    repo.save_dataframe(df, table)
            else:
                # Single table case
                if not default_table_name:
                    raise ValueError("table_name required for single DataFrame save")
                self.logger.info(f"Saving {len(data)} rows to {default_table_name}...")
                repo.save_dataframe(data, default_table_name)

    def run(self, table_name: str = None):
        """Standard execution pipeline."""
        try:
            self.logger.info("Starting fetch...")
            raw = self.fetch()
            
            self.logger.info("Starting transform...")
            clean_data = self.transform(raw)
            
            self.logger.info("Starting save...")
            self.save(clean_data, table_name)
            
            self.logger.info("Pipeline completed successfully.")
        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}", exc_info=True)
            raise
```

---

## 2. Refactor `bonds.py`
**Current State**: `bonds.py` has a redundant `run_pipeline` method and manually iterates through results.

**Implementation Guide**:
1.  **Remove `run_pipeline`**: The base `run()` method should be sufficient.
2.  **Update `transform`**: Ensure it returns a clean DataFrame ready for insertion.
3.  **CLI Entry Point**: Update `if __name__ == "__main__":` to call `fetcher.run(table_name="interest_rates")`.

---

## 3. Refactor `shiller_cape.py`
**Current State**: Uses a custom `run_pipeline` because it splits data into `macro_data` and `test_data`.

**Implementation Guide**:
1.  **Update `transform`**: Instead of returning a generic DF, this method should now map the raw data to the specific schemas and return a dictionary:
    ```python
    def transform(self, file_path: str) -> Dict[str, pd.DataFrame]:
        # ... existing logic ...
        # logic to split into macro_data and test_data
        return {
            "macro_data": df_macro,
            "test_data": df_test
        }
    ```
2.  **Remove `run_pipeline`**: Inherit the logic from the enhanced `BaseFetcher.run`.
3.  **Column Mapping**: Ensure `transform` handles the column mapping logic currently inside `run_pipeline`.

---

## 4. Implement `stock_prices.py`
**Objective**: Create a new fetcher for Stock Market data (e.g., SPY, VOO) to validate the new architecture.

**Prerequisites**:
-   Install `yfinance`: `pip install yfinance`

**Implementation Guide**:
1.  **Create Class**: `YahooFinanceFetcher` inheriting from `BaseFetcher`.
2.  **Implement `fetch`**:
    -   Use `yfinance.Ticker("SPY").history(period="max")`.
3.  **Implement `transform`**:
    -   Reset index to make `Date` a column.
    -   Rename columns to match DB schema (e.g., `Close` -> `price`, `Date` -> `date`).
    -   Add metadata columns like `symbol='SPY'`.
4.  **CLI**: Allow passing ticker symbols as arguments.

**Code Skeleton**:
```python
import yfinance as yf
from data_fetchers.base_fetcher import BaseFetcher

class YahooFinanceFetcher(BaseFetcher):
    def __init__(self, symbol: str, db_config=None):
        super().__init__(db_config)
        self.symbol = symbol

    def fetch(self):
        return yf.Ticker(self.symbol).history(period="max")

    def transform(self, raw_df):
        df = raw_df.reset_index()
        df['symbol'] = self.symbol
        # ... logic to rename columns to match 'stock_prices' table ...
        return df
```

---

## 5. Verification Checklist
-   [ ] Run `python -m data_fetchers.bonds` -> Success.
-   [ ] Run `python -m data_fetchers.shiller_cape <url>` -> Success, data in both tables.
-   [ ] Run `python -m data_fetchers.stock_prices SPY` -> Success, data in `stock_prices` (assuming table exists).
