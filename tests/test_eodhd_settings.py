from __future__ import annotations

from pathlib import Path

import pytest

from data_fetchers.eodhd.downloader import parse_args
from data_fetchers.eodhd.settings import DEFAULT_CONFIG_PATH, load_eodhd_config


def test_load_default_config_has_required_sections():
    cfg = load_eodhd_config(DEFAULT_CONFIG_PATH)
    assert cfg.paths.archive_subdir == Path("eodhd")
    assert cfg.download.concurrency == 20
    assert "eodhd_us_listed_common_equities_v1" in cfg.universes


def test_parse_args_uses_custom_config_defaults(tmp_path: Path):
    config_path = tmp_path / "eodhd.toml"
    config_path.write_text(
        """
[paths]
archive_subdir = "eodhd"
state_db = "state/eodhd_all_world_snapshot.sqlite3"

[api]
base_url = "https://eodhd.com/api"
symbol_change_start_date = "2022-07-22"

[download]
start = "1900-01-01"
corporate_actions_scope = "eligible"
refresh_after_days = 7
concurrency = 99
http_timeout = 60
progress_every = 500
log_level = "INFO"
raw_json = false
force = false
sleep_on_daily_limit = false

[download.rate_limits]
max_requests_per_minute = 900
max_api_calls_per_day = 95000
min_seconds_between_requests = 0.05
provider_rate_limit_cooldown_seconds = 60.25
max_provider_rate_limit_cooldown_seconds = 120.0

[download.scope]
confirm_full_plan_download = true
include_delisted = true
download_prices = true
download_dividends = true
download_splits = true
exclude_virtual_categories = false
virtual_asset_categories = ["EUFUND"]
corporate_action_eligible_types = ["common stock"]
supported_type_filters = ["stock"]

[ingest]
default_scope = "metadata"
batch_rows = 10000

[reports.metadata]
snapshot_date = "latest"
output_root = "derived/reports/eodhd/metadata"

[reports.universes]
snapshot_date = "latest"
output_root = "derived/reports/eodhd/universes"
persist_to_db = true

[reports.price_quality]
build_id = "latest"
workers = 8
output_root = "derived/reports/eodhd/price_quality"

[reports.materialization]
build_id = "latest"
output_root = "derived/reports/eodhd/materialization"
allow_partial = false
""".strip()
        + "\n",
        encoding="utf-8",
    )
    args = parse_args(["--config", str(config_path), "--confirm-full-plan-download"])
    assert args.concurrency == 99
    assert args.full_archive_preset is False


def test_cli_overrides_config_concurrency(tmp_path: Path):
    config_path = tmp_path / "eodhd.toml"
    config_path.write_text(
        (DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")).replace("concurrency = 20", "concurrency = 99"),
        encoding="utf-8",
    )
    args = parse_args(["--config", str(config_path), "--concurrency", "3", "--confirm-full-plan-download"])
    assert args.concurrency == 3
