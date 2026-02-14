import argparse
import json

import pytest

from data_fetchers.shiller_cape import ShillerCapeFetcher, _load_column_mapping, _resolve_url


def test_resolve_url_uses_override_when_present():
    args = argparse.Namespace(url="https://example.com/positional.xls", url_override="https://example.com/flag.xls")
    assert _resolve_url(args) == "https://example.com/flag.xls"


def test_resolve_url_uses_positional_when_override_missing():
    args = argparse.Namespace(url="https://example.com/positional.xls", url_override=None)
    assert _resolve_url(args) == "https://example.com/positional.xls"


def test_resolve_url_requires_input():
    args = argparse.Namespace(url=None, url_override=None)
    with pytest.raises(ValueError, match="Shiller Excel URL is required"):
        _resolve_url(args)


def test_load_column_mapping_reads_relative_path_from_cwd(tmp_path, monkeypatch):
    mapping = {"A": {"id": "a", "long_name": "A", "type": "raw"}}
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    loaded = _load_column_mapping("mapping.json")

    assert loaded == mapping


def test_load_column_mapping_falls_back_to_module_relative_path(tmp_path, monkeypatch):
    # This path exists relative to the module but not relative to the temporary cwd.
    monkeypatch.chdir(tmp_path)

    loaded = _load_column_mapping("data_fetchers/shiller_cols.json")

    assert isinstance(loaded, dict)
    assert "Date Fraction" in loaded


def test_load_column_mapping_raises_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Column mapping file not found"):
        _load_column_mapping("missing_mapping.json")


def test_fetcher_rejects_invalid_retry_count():
    with pytest.raises(ValueError, match="max_retries must be >= 1"):
        ShillerCapeFetcher(
            file_url="https://example.com/data.xls",
            column_mapping={},
            db_config={},
            max_retries=0,
        )
