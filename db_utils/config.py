from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.toml"


def load_project_environment(env_file: str | Path | None = None) -> None:
    if env_file is not None:
        load_dotenv(Path(env_file), override=False)
    load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass(frozen=True)
class EodhdSettings:
    archive_subdir: Path


@dataclass(frozen=True)
class ProjectSettings:
    eodhd: EodhdSettings


def _relative_subdir(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty relative path.")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must be a relative path without '..'.")
    return path


def load_project_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> ProjectSettings:
    with Path(path).open("rb") as handle:
        config = tomllib.load(handle)
    eodhd = config.get("eodhd", {})
    if not isinstance(eodhd, dict):
        raise ValueError("Settings must define [eodhd] as a table.")
    return ProjectSettings(
        eodhd=EodhdSettings(
            archive_subdir=_relative_subdir(eodhd.get("archive_subdir", "eodhd"), "eodhd.archive_subdir"),
        ),
    )


def get_eodhd_archive_root(settings_path: str | Path = DEFAULT_SETTINGS_PATH) -> Path:
    load_project_environment()
    raw_data_dir = os.getenv("RAW_DATA_DIR")
    if not raw_data_dir:
        raise ValueError("Missing EODHD root: pass --root or set RAW_DATA_DIR.")
    settings = load_project_settings(settings_path)
    return Path(raw_data_dir).expanduser() / settings.eodhd.archive_subdir


def get_database_config() -> Dict[str, str]:
    """
    Reads database configuration from environment variables.
    Returns a dictionary suitable for psycopg2.connect kwargs.
    
    Raises:
        ValueError: If required environment variables are missing.
    """
    load_project_environment()
    config = {
        'dbname': os.getenv('POSTGRES_DB'),
        'user': os.getenv('POSTGRES_USER'),
        'password': os.getenv('POSTGRES_PASSWORD'),
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432')
    }
    
    required = ['dbname', 'user', 'password']
    missing = [k for k in required if not config[k]]
    if missing:
        raise ValueError(f"Missing required database environment variables: {', '.join(['POSTGRES_' + k.upper() for k in missing])}")
        
    return config
