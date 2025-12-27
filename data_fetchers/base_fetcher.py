from abc import ABC, abstractmethod
import pandas as pd
from typing import Optional, Any
from db_utils.database import DatabaseConnection
from db_utils.repository import DataRepository

class BaseFetcher(ABC):
    """
    Abstract base class for all data fetchers.
    Defines a standard lifecycle: fetch -> transform -> save.
    """
    
    def __init__(self, db_config: Optional[dict] = None):
        self.db_config = db_config

    @abstractmethod
    def fetch(self) -> Any:
        """
        Fetch raw data from the source (API, Website, File, etc.).
        Returns the raw data in whatever format is convenient (e.g. requests.Response or list).
        """
        pass

    @abstractmethod
    def transform(self, raw_data: Any) -> pd.DataFrame:
        """
        Transform the raw data into a cleaned pandas DataFrame.
        """
        pass

    def save(self, data: pd.DataFrame, table_name: str, value_mapping: Optional[dict] = None):
        """
        Persist the transformed data to the database using the Repository pattern.
        """
        with DatabaseConnection(config=self.db_config) as db:
            repo = DataRepository(db)
            repo.save_dataframe(data, table_name, value_mapping)

    def run(self, table_name: str, value_mapping: Optional[dict] = None):
        """
        Execute the full fetch-transform-save pipeline.
        """
        raw_data = self.fetch()
        clean_data = self.transform(raw_data)
        self.save(clean_data, table_name, value_mapping)
