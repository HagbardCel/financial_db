import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Union, Optional
import pandas as pd
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

class BaseFetcher(ABC):
    """
    Abstract base class for all data fetchers.
    Defines a standard lifecycle: fetch -> transform -> save.
    """
    
    def __init__(self, db_config: Optional[dict] = None):
        self.db_config = db_config
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            logging.basicConfig(level=logging.INFO)

    @abstractmethod
    def fetch(self) -> Any:
        """
        Fetch raw data from the source (API, Website, File, etc.).
        Returns the raw data in whatever format is convenient (e.g. requests.Response or list).
        """
        pass

    @abstractmethod
    def transform(self, raw_data: Any) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """
        Transform the raw data into a cleaned pandas DataFrame or a dict of DataFrames.
        """
        pass

    def save(self, data: Union[pd.DataFrame, Dict[str, pd.DataFrame]], table_name: Optional[str] = None):
        """
        Persist the transformed data to the database using the Repository pattern.
        Handles both single DataFrames and dictionaries of DataFrames for multi-table saves.
        """
        with DatabaseConnection(config=self.db_config) as db:
            repo = DataRepository(db)
            self._save_with_repository(repo, data, table_name)

    def _save_with_repository(
        self,
        repo: DataRepository,
        data: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
        table_name: Optional[str] = None,
    ) -> None:
        """Persist transformed data using an already-initialized repository."""
        if isinstance(data, dict):
            for t_name, df in data.items():
                if not df.empty:
                    self.logger.info(f"Saving {len(df)} rows to table: {t_name}")
                    repo.save_dataframe(df, t_name)
                else:
                    self.logger.warning(f"DataFrame for table {t_name} is empty. Skipping.")
            return

        if table_name is None:
            raise ValueError("table_name must be provided for single DataFrame saves.")
        if not data.empty:
            self.logger.info(f"Saving {len(data)} rows to table: {table_name}")
            repo.save_dataframe(data, table_name)
        else:
            self.logger.warning(f"DataFrame for table {table_name} is empty. Skipping.")

    def run(self, table_name: Optional[str] = None):
        """
        Execute the full fetch-transform-save pipeline with error handling and logging.
        """
        try:
            self.logger.info("Starting fetch stage...")
            raw_data = self.fetch()
            
            self.logger.info("Starting transform stage...")
            clean_data = self.transform(raw_data)
            
            self.logger.info("Starting save stage...")
            self.save(clean_data, table_name)
            
            self.logger.info("Pipeline execution finished successfully.")
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {str(e)}", exc_info=True)
            raise

    def run_with_repository(self, repo: DataRepository, table_name: Optional[str] = None):
        """
        Execute fetch-transform-save using a shared repository/connection.
        Useful for batch ingest commands that process many symbols in one DB session.
        """
        try:
            self.logger.info("Starting fetch stage...")
            raw_data = self.fetch()

            self.logger.info("Starting transform stage...")
            clean_data = self.transform(raw_data)

            self.logger.info("Starting save stage...")
            self._save_with_repository(repo, clean_data, table_name)

            self.logger.info("Pipeline execution finished successfully.")
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {str(e)}", exc_info=True)
            raise
