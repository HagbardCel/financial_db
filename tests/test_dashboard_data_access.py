import pandas as pd
import pytest
from sqlalchemy import create_engine

from dashboard.data_access import _engine_cache_key, build_label_map, parse_factor_options


def test_build_label_map_without_label_column():
    frame = pd.DataFrame({"id": ["A", "B"]})
    assert build_label_map(frame) == {"A": "A", "B": "B"}


def test_build_label_map_with_label_column():
    frame = pd.DataFrame({"id": ["A"], "label": ["Alpha"]})
    assert build_label_map(frame) == {"A": "A - Alpha"}


def test_parse_factor_options():
    options = ["ff3::Mkt-RF", "ff3::SMB"]
    assert parse_factor_options(options) == [("ff3", "Mkt-RF"), ("ff3", "SMB")]


def test_parse_factor_options_rejects_invalid_format():
    with pytest.raises(ValueError):
        parse_factor_options(["invalid"])


def test_engine_cache_key_uses_url():
    engine = create_engine("sqlite://")
    assert _engine_cache_key(engine).startswith("sqlite")
