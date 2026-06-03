from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path("config/eodhd.toml")


def _require_table(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"EODHD config field '{field_name}' must be a table.")
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"EODHD config field '{field_name}' must be a non-empty string.")
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"EODHD config field '{field_name}' must be an integer.")
    return value


def _require_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"EODHD config field '{field_name}' must be a number.")
    return float(value)


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"EODHD config field '{field_name}' must be a boolean.")
    return value


def _require_str_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"EODHD config field '{field_name}' must be a list of strings.")
    return list(value)


def _relative_path(value: object, field_name: str) -> Path:
    path = Path(_require_str(value, field_name))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"EODHD config field '{field_name}' must be a relative path without '..'.")
    return path


@dataclass(frozen=True)
class PathsConfig:
    archive_subdir: Path
    state_db: Path


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    symbol_change_start_date: str


@dataclass(frozen=True)
class RateLimitsConfig:
    max_requests_per_minute: int
    max_api_calls_per_day: int
    min_seconds_between_requests: float
    provider_rate_limit_cooldown_seconds: float
    max_provider_rate_limit_cooldown_seconds: float


@dataclass(frozen=True)
class DownloadScopeConfig:
    confirm_full_plan_download: bool
    include_delisted: bool
    download_prices: bool
    download_dividends: bool
    download_splits: bool
    exclude_virtual_categories: bool
    virtual_asset_categories: tuple[str, ...]
    corporate_action_eligible_types: frozenset[str]
    supported_type_filters: frozenset[str]


@dataclass(frozen=True)
class DownloadConfig:
    start: str
    corporate_actions_scope: str
    refresh_after_days: int
    concurrency: int
    http_timeout: int
    progress_every: int
    log_level: str
    raw_json: bool
    force: bool
    sleep_on_daily_limit: bool
    rate_limits: RateLimitsConfig
    scope: DownloadScopeConfig


@dataclass(frozen=True)
class IngestConfig:
    default_scope: str
    batch_rows: int


@dataclass(frozen=True)
class MetadataReportConfig:
    snapshot_date: str
    output_root: Path


@dataclass(frozen=True)
class UniversesReportConfig:
    snapshot_date: str
    output_root: Path
    persist_to_db: bool


@dataclass(frozen=True)
class PriceQualityReportConfig:
    build_id: str
    workers: int
    output_root: Path


@dataclass(frozen=True)
class MaterializationReportConfig:
    build_id: str
    output_root: Path
    allow_partial: bool


@dataclass(frozen=True)
class ReportsConfig:
    metadata: MetadataReportConfig
    universes: UniversesReportConfig
    price_quality: PriceQualityReportConfig
    materialization: MaterializationReportConfig


@dataclass(frozen=True)
class EodhdConfig:
    paths: PathsConfig
    api: ApiConfig
    download: DownloadConfig
    ingest: IngestConfig
    reports: ReportsConfig
    universes: dict[str, dict[str, Any]]


def config_for_universe(cfg: EodhdConfig, universe_name: str) -> dict[str, Any]:
    try:
        return cfg.universes[universe_name]
    except KeyError as exc:
        raise ValueError(f"Unknown universe '{universe_name}' in EODHD config.") from exc


def load_eodhd_config(path: str | Path = DEFAULT_CONFIG_PATH) -> EodhdConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    paths_raw = _require_table(raw.get("paths"), "paths")
    api_raw = _require_table(raw.get("api"), "api")
    download_raw = _require_table(raw.get("download"), "download")
    rate_limits_raw = _require_table(download_raw.get("rate_limits"), "download.rate_limits")
    scope_raw = _require_table(download_raw.get("scope"), "download.scope")
    ingest_raw = _require_table(raw.get("ingest"), "ingest")
    reports_raw = _require_table(raw.get("reports"), "reports")

    universes_raw = raw.get("universes", {})
    if not isinstance(universes_raw, dict):
        raise ValueError("EODHD config field 'universes' must be a table.")
    universes = {str(name): _require_table(defn, f"universes.{name}") for name, defn in universes_raw.items()}

    corporate_types = frozenset(t.lower() for t in _require_str_list(scope_raw.get("corporate_action_eligible_types"), "download.scope.corporate_action_eligible_types"))
    supported_filters = frozenset(_require_str_list(scope_raw.get("supported_type_filters"), "download.scope.supported_type_filters"))

    return EodhdConfig(
        paths=PathsConfig(
            archive_subdir=_relative_path(paths_raw.get("archive_subdir", "eodhd"), "paths.archive_subdir"),
            state_db=_relative_path(paths_raw.get("state_db", "state/eodhd_all_world_snapshot.sqlite3"), "paths.state_db"),
        ),
        api=ApiConfig(
            base_url=_require_str(api_raw.get("base_url", "https://eodhd.com/api"), "api.base_url"),
            symbol_change_start_date=_require_str(
                api_raw.get("symbol_change_start_date", "2022-07-22"),
                "api.symbol_change_start_date",
            ),
        ),
        download=DownloadConfig(
            start=_require_str(download_raw.get("start", "1900-01-01"), "download.start"),
            corporate_actions_scope=_require_str(download_raw.get("corporate_actions_scope", "eligible"), "download.corporate_actions_scope"),
            refresh_after_days=_require_int(download_raw.get("refresh_after_days", 7), "download.refresh_after_days"),
            concurrency=_require_int(download_raw.get("concurrency", 20), "download.concurrency"),
            http_timeout=_require_int(download_raw.get("http_timeout", 60), "download.http_timeout"),
            progress_every=_require_int(download_raw.get("progress_every", 500), "download.progress_every"),
            log_level=_require_str(download_raw.get("log_level", "INFO"), "download.log_level"),
            raw_json=_require_bool(download_raw.get("raw_json", False), "download.raw_json"),
            force=_require_bool(download_raw.get("force", False), "download.force"),
            sleep_on_daily_limit=_require_bool(download_raw.get("sleep_on_daily_limit", False), "download.sleep_on_daily_limit"),
            rate_limits=RateLimitsConfig(
                max_requests_per_minute=_require_int(rate_limits_raw.get("max_requests_per_minute", 900), "download.rate_limits.max_requests_per_minute"),
                max_api_calls_per_day=_require_int(rate_limits_raw.get("max_api_calls_per_day", 95_000), "download.rate_limits.max_api_calls_per_day"),
                min_seconds_between_requests=_require_float(
                    rate_limits_raw.get("min_seconds_between_requests", 0.05),
                    "download.rate_limits.min_seconds_between_requests",
                ),
                provider_rate_limit_cooldown_seconds=_require_float(
                    rate_limits_raw.get("provider_rate_limit_cooldown_seconds", 60.25),
                    "download.rate_limits.provider_rate_limit_cooldown_seconds",
                ),
                max_provider_rate_limit_cooldown_seconds=_require_float(
                    rate_limits_raw.get("max_provider_rate_limit_cooldown_seconds", 120.0),
                    "download.rate_limits.max_provider_rate_limit_cooldown_seconds",
                ),
            ),
            scope=DownloadScopeConfig(
                confirm_full_plan_download=_require_bool(scope_raw.get("confirm_full_plan_download", True), "download.scope.confirm_full_plan_download"),
                include_delisted=_require_bool(scope_raw.get("include_delisted", True), "download.scope.include_delisted"),
                download_prices=_require_bool(scope_raw.get("download_prices", True), "download.scope.download_prices"),
                download_dividends=_require_bool(scope_raw.get("download_dividends", True), "download.scope.download_dividends"),
                download_splits=_require_bool(scope_raw.get("download_splits", True), "download.scope.download_splits"),
                exclude_virtual_categories=_require_bool(scope_raw.get("exclude_virtual_categories", False), "download.scope.exclude_virtual_categories"),
                virtual_asset_categories=tuple(
                    _require_str_list(scope_raw.get("virtual_asset_categories"), "download.scope.virtual_asset_categories")
                ),
                corporate_action_eligible_types=corporate_types,
                supported_type_filters=supported_filters,
            ),
        ),
        ingest=IngestConfig(
            default_scope=_require_str(ingest_raw.get("default_scope", "metadata"), "ingest.default_scope"),
            batch_rows=_require_int(ingest_raw.get("batch_rows", 10_000), "ingest.batch_rows"),
        ),
        reports=ReportsConfig(
            metadata=MetadataReportConfig(
                snapshot_date=_require_str(
                    _require_table(reports_raw.get("metadata"), "reports.metadata").get("snapshot_date", "latest"),
                    "reports.metadata.snapshot_date",
                ),
                output_root=_relative_path(
                    _require_table(reports_raw.get("metadata"), "reports.metadata").get(
                        "output_root", "derived/reports/eodhd/metadata"
                    ),
                    "reports.metadata.output_root",
                ),
            ),
            universes=UniversesReportConfig(
                snapshot_date=_require_str(
                    _require_table(reports_raw.get("universes"), "reports.universes").get("snapshot_date", "latest"),
                    "reports.universes.snapshot_date",
                ),
                output_root=_relative_path(
                    _require_table(reports_raw.get("universes"), "reports.universes").get(
                        "output_root", "derived/reports/eodhd/universes"
                    ),
                    "reports.universes.output_root",
                ),
                persist_to_db=_require_bool(
                    _require_table(reports_raw.get("universes"), "reports.universes").get("persist_to_db", True),
                    "reports.universes.persist_to_db",
                ),
            ),
            price_quality=PriceQualityReportConfig(
                build_id=_require_str(
                    _require_table(reports_raw.get("price_quality"), "reports.price_quality").get("build_id", "latest"),
                    "reports.price_quality.build_id",
                ),
                workers=_require_int(
                    _require_table(reports_raw.get("price_quality"), "reports.price_quality").get("workers", 8),
                    "reports.price_quality.workers",
                ),
                output_root=_relative_path(
                    _require_table(reports_raw.get("price_quality"), "reports.price_quality").get(
                        "output_root", "derived/reports/eodhd/price_quality"
                    ),
                    "reports.price_quality.output_root",
                ),
            ),
            materialization=MaterializationReportConfig(
                build_id=_require_str(
                    _require_table(reports_raw.get("materialization"), "reports.materialization").get("build_id", "latest"),
                    "reports.materialization.build_id",
                ),
                output_root=_relative_path(
                    _require_table(reports_raw.get("materialization"), "reports.materialization").get(
                        "output_root", "derived/reports/eodhd/materialization"
                    ),
                    "reports.materialization.output_root",
                ),
                allow_partial=_require_bool(
                    _require_table(reports_raw.get("materialization"), "reports.materialization").get("allow_partial", False),
                    "reports.materialization.allow_partial",
                ),
            ),
        ),
        universes=universes,
    )


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Backward-compatible dict view for universe build hashing and persistence."""
    cfg = load_eodhd_config(path)
    return {"universes": cfg.universes}
