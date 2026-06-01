from __future__ import annotations

import os
from pathlib import Path

import pytest

from db_utils.config import get_database_config, get_eodhd_archive_root, load_project_environment, load_project_settings


def _write_settings(path: Path, archive_subdir: str) -> Path:
    path.write_text(f'[eodhd]\narchive_subdir = "{archive_subdir}"\n', encoding="utf-8")
    return path


def test_load_project_settings_reads_eodhd_archive_subdir(tmp_path: Path):
    settings = load_project_settings(_write_settings(tmp_path / "settings.toml", "vendor/eodhd"))

    assert settings.eodhd.archive_subdir == Path("vendor/eodhd")


@pytest.mark.parametrize("archive_subdir", ["", "/absolute/eodhd", "../eodhd", "vendor/../eodhd"])
def test_load_project_settings_rejects_invalid_archive_subdir(tmp_path: Path, archive_subdir: str):
    with pytest.raises(ValueError, match="eodhd.archive_subdir"):
        load_project_settings(_write_settings(tmp_path / "settings.toml", archive_subdir))


def test_get_eodhd_archive_root_uses_raw_data_dir_and_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    settings_path = _write_settings(tmp_path / "settings.toml", "eodhd")

    assert get_eodhd_archive_root(settings_path) == tmp_path / "raw/eodhd"


def test_get_eodhd_archive_root_requires_raw_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAW_DATA_DIR", raising=False)

    with pytest.raises(ValueError, match="RAW_DATA_DIR"):
        get_eodhd_archive_root()


def test_load_project_environment_reads_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / ".env").write_text("FROM_ROOT=loaded\n", encoding="utf-8")
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("FROM_ROOT", raising=False)

    load_project_environment()

    assert os.environ["FROM_ROOT"] == "loaded"


def test_load_project_environment_prefers_explicit_file_and_preserves_exported_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / ".env").write_text("FROM_FILES=root\nEXPORTED=root\n", encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("FROM_FILES=explicit\nEXPORTED=explicit\n", encoding="utf-8")
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("FROM_FILES", raising=False)
    monkeypatch.setenv("EXPORTED", "shell")

    load_project_environment(explicit)

    assert os.environ["FROM_FILES"] == "explicit"
    assert os.environ["EXPORTED"] == "shell"


def test_load_project_environment_ignores_missing_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)

    load_project_environment(tmp_path / "missing.env")


def test_get_database_config_reads_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / ".env").write_text(
        "POSTGRES_DB=test_db\nPOSTGRES_USER=test_user\nPOSTGRES_PASSWORD=test_password\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("db_utils.config.PROJECT_ROOT", tmp_path)
    for name in ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT"]:
        monkeypatch.delenv(name, raising=False)

    assert get_database_config() == {
        "dbname": "test_db",
        "user": "test_user",
        "password": "test_password",
        "host": "localhost",
        "port": "5432",
    }
