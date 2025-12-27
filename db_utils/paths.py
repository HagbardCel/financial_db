import os
from pathlib import Path

# This determines the absolute path to the directory containing this file (db_utils/)
_DB_UTILS_DIR = Path(__file__).resolve().parent

# The project root is one level up from db_utils/
PROJECT_ROOT = _DB_UTILS_DIR.parent

# Define other useful paths
DATA_DIR = PROJECT_ROOT / "data"
DOC_DIR = PROJECT_ROOT / "doc"
LOG_DIR = PROJECT_ROOT / "logs"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
DATA_FETCHERS_DIR = PROJECT_ROOT / "data_fetchers"

# Ensure directories exist if they are expected to be present
# For now, we just define them.
