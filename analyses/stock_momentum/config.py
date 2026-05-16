from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path("config/stock_momentum_free.toml")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    project = config.setdefault("project", {})
    project.setdefault("name", "stock_momentum")
    project.setdefault("profile", "free_prototype")
    project.setdefault("base_currency", "EUR")
    project.setdefault("artifact_dir", "derived/stock_momentum")
    return config


def artifact_dir(config: dict[str, Any]) -> Path:
    return Path(config["project"]["artifact_dir"]).expanduser()
