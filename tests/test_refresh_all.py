from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from data_fetchers.refresh_all import (
    FetcherEntry,
    DEFAULT_CONFIG_PATH,
    build_command,
    load_refresh_config,
    main,
    run_fetchers,
    select_fetchers,
)


def test_load_refresh_config_reads_default_config():
    entries = load_refresh_config(DEFAULT_CONFIG_PATH)

    assert [entry.name for entry in entries][:4] == ["bonds", "commodities", "gold_prices", "oil_prices"]
    assert entries[0].module == "data_fetchers.bonds"
    assert entries[0].enabled is True
    eodhd = next(entry for entry in entries if entry.name == "eodhd_refresh")
    assert eodhd.enabled is False
    assert eodhd.module == "data_fetchers.eodhd"
    assert eodhd.args == ["refresh"]


def test_load_refresh_config_rejects_missing_order_target(tmp_path: Path):
    config_path = tmp_path / "bad.toml"
    config_path.write_text(
        """
order = ["missing"]

[fetchers.present]
module = "data_fetchers.bonds"
enabled = true
description = "ok"
args = []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown fetchers: missing"):
        load_refresh_config(config_path)


def test_load_refresh_config_rejects_non_string_args(tmp_path: Path):
    config_path = tmp_path / "bad_args.toml"
    config_path.write_text(
        """
order = ["bonds"]

[fetchers.bonds]
module = "data_fetchers.bonds"
enabled = true
description = "ok"
args = ["--start", 123]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="args"):
        load_refresh_config(config_path)


def test_select_fetchers_preserves_config_order():
    entries = [
        FetcherEntry("bonds", "data_fetchers.bonds", True, []),
        FetcherEntry("aqr", "data_fetchers.aqr", True, []),
        FetcherEntry("ken_french", "data_fetchers.ken_french", True, []),
    ]

    selected = select_fetchers(entries, only=["ken_french", "bonds"])

    assert [entry.name for entry in selected] == ["bonds", "ken_french"]


def test_select_fetchers_applies_skip_after_only():
    entries = [
        FetcherEntry("bonds", "data_fetchers.bonds", True, []),
        FetcherEntry("aqr", "data_fetchers.aqr", True, []),
        FetcherEntry("ken_french", "data_fetchers.ken_french", True, []),
    ]

    selected = select_fetchers(entries, only=["bonds", "aqr"], skip=["aqr"])

    assert [entry.name for entry in selected] == ["bonds"]


def test_select_fetchers_rejects_unknown_names():
    entries = [FetcherEntry("bonds", "data_fetchers.bonds", True, [])]

    with pytest.raises(ValueError, match="Unknown fetcher"):
        select_fetchers(entries, only=["missing"])


def test_build_command_forwards_args_unchanged():
    entry = FetcherEntry(
        "shiller_cape",
        "data_fetchers.shiller_cape",
        True,
        ["--url", "https://example.com/data.xls", "--timeout", "15"],
    )

    command = build_command(entry)

    assert command[:3] == [command[0], "-m", "data_fetchers.shiller_cape"]
    assert command[3:] == ["--url", "https://example.com/data.xls", "--timeout", "15"]


def test_run_fetchers_continues_and_reports_failures():
    entries = [
        FetcherEntry("bonds", "data_fetchers.bonds", True, []),
        FetcherEntry("openbb_equity_prices", "data_fetchers.openbb_equity_prices", False, ["AAPL"]),
        FetcherEntry("aqr", "data_fetchers.aqr", True, ["--refresh"]),
    ]
    commands: list[list[str]] = []
    returncodes = iter([0, 2])

    def fake_runner(command):
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command,
            next(returncodes),
            stdout="done\n",
            stderr="boom\n" if command[2] == "data_fetchers.aqr" else "",
        )

    results = run_fetchers(entries, runner=fake_runner)

    assert [result.name for result in results] == ["bonds", "openbb_equity_prices", "aqr"]
    assert results[0].returncode == 0
    assert results[1].skipped is True
    assert results[2].returncode == 2
    assert len(commands) == 2
    assert commands[1][3:] == ["--refresh"]
    assert results[2].stderr == "boom\n"


def test_run_fetchers_fail_fast_stops_after_first_failure():
    entries = [
        FetcherEntry("bonds", "data_fetchers.bonds", True, []),
        FetcherEntry("aqr", "data_fetchers.aqr", True, []),
        FetcherEntry("ken_french", "data_fetchers.ken_french", True, []),
    ]
    commands: list[list[str]] = []
    returncodes = iter([1, 0, 0])

    def fake_runner(command):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, next(returncodes))

    results = run_fetchers(entries, fail_fast=True, runner=fake_runner)

    assert [result.name for result in results] == ["bonds"]
    assert len(commands) == 1


def test_main_lists_fetchers(capsys):
    exit_code = main(["--list"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "bonds: enabled" in captured.out
    assert "oil_prices: enabled" in captured.out
    assert "shiller_cape: enabled" in captured.out


def test_main_returns_nonzero_when_any_fetcher_fails():
    def fake_runner(command):
        module_name = command[2]
        returncode = 1 if module_name == "data_fetchers.aqr" else 0
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout="aqr-out\n" if returncode else "",
            stderr="aqr-err\n" if returncode else "",
        )

    exit_code = main(["--only", "bonds", "aqr"], runner=fake_runner)

    assert exit_code == 1


def test_main_prints_failure_details_from_child_output(capsys):
    def fake_runner(command):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="child stdout\n",
            stderr="child stderr\ntraceback line\n",
        )

    exit_code = main(["--only", "bonds"], runner=fake_runner)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "child stdout" in captured.out
    assert "child stderr" in captured.out
    assert "Failure details for bonds:" in captured.out
