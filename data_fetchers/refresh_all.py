from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "data_refresh.toml"


@dataclass(frozen=True)
class FetcherEntry:
    name: str
    module: str
    enabled: bool
    args: list[str]
    description: str = ""


@dataclass(frozen=True)
class FetchResult:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    skipped: bool = False
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all configured data fetchers.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the TOML refresh config file.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        help="Run only the named fetchers from the config.",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        help="Skip the named fetchers from the config.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first fetcher failure.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List configured fetchers and exit.",
    )
    return parser.parse_args(argv)


def _require_string(value: object, field_name: str, fetcher_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Fetcher '{fetcher_name}' must define non-empty string field '{field_name}'.")
    return value


def _require_bool(value: object, field_name: str, fetcher_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Fetcher '{fetcher_name}' field '{field_name}' must be a boolean.")
    return value


def _require_string_list(value: object, field_name: str, fetcher_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Fetcher '{fetcher_name}' field '{field_name}' must be a list of strings.")
    return list(value)


def load_refresh_config(path: Path) -> list[FetcherEntry]:
    with path.open("rb") as handle:
        raw_config = tomllib.load(handle)

    order = raw_config.get("order")
    fetchers = raw_config.get("fetchers")

    if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
        raise ValueError("Refresh config must define 'order' as a list of fetcher names.")
    if not isinstance(fetchers, dict):
        raise ValueError("Refresh config must define a [fetchers] table.")

    unknown = [name for name in order if name not in fetchers]
    if unknown:
        raise ValueError(f"Refresh config 'order' references unknown fetchers: {', '.join(unknown)}")

    entries: list[FetcherEntry] = []
    for name in order:
        config = fetchers[name]
        if not isinstance(config, dict):
            raise ValueError(f"Fetcher '{name}' config must be a table.")
        entries.append(
            FetcherEntry(
                name=name,
                module=_require_string(config.get("module"), "module", name),
                enabled=_require_bool(config.get("enabled"), "enabled", name),
                args=_require_string_list(config.get("args"), "args", name),
                description=_require_string(config.get("description", ""), "description", name),
            )
        )

    return entries


def select_fetchers(
    entries: Sequence[FetcherEntry],
    only: Iterable[str] | None = None,
    skip: Iterable[str] | None = None,
) -> list[FetcherEntry]:
    by_name = {entry.name: entry for entry in entries}
    only_set = set(only or [])
    skip_set = set(skip or [])

    unknown_only = sorted(name for name in only_set if name not in by_name)
    if unknown_only:
        raise ValueError(f"Unknown fetcher(s) in --only: {', '.join(unknown_only)}")

    unknown_skip = sorted(name for name in skip_set if name not in by_name)
    if unknown_skip:
        raise ValueError(f"Unknown fetcher(s) in --skip: {', '.join(unknown_skip)}")

    selected = list(entries)
    if only_set:
        selected = [entry for entry in selected if entry.name in only_set]
    if skip_set:
        selected = [entry for entry in selected if entry.name not in skip_set]
    return selected


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def build_command(entry: FetcherEntry) -> list[str]:
    return [sys.executable, "-m", entry.module, *entry.args]


def _emit_child_output(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n")


def _tail_lines(text: str, limit: int = 12) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


def run_fetchers(
    entries: Sequence[FetcherEntry],
    fail_fast: bool = False,
    runner: Runner | None = None,
) -> list[FetchResult]:
    exec_runner = runner or _default_runner
    results: list[FetchResult] = []

    for entry in entries:
        command = build_command(entry)
        if not entry.enabled:
            print(f"[skip] {entry.name}: disabled in config")
            results.append(
                FetchResult(
                    name=entry.name,
                    command=command,
                    returncode=0,
                    duration_seconds=0.0,
                    skipped=True,
                )
            )
            continue

        print(f"[run] {entry.name}: {' '.join(command)}")
        started_at = time.perf_counter()
        completed = exec_runner(command)
        duration_seconds = time.perf_counter() - started_at
        _emit_child_output(completed)
        results.append(
            FetchResult(
                name=entry.name,
                command=command,
                returncode=completed.returncode,
                duration_seconds=duration_seconds,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
        )

        if completed.returncode == 0:
            print(f"[ok] {entry.name}: {duration_seconds:.2f}s")
            continue

        print(f"[fail] {entry.name}: exit {completed.returncode} after {duration_seconds:.2f}s")
        if fail_fast:
            break

    return results


def print_fetcher_list(entries: Sequence[FetcherEntry]) -> None:
    for entry in entries:
        status = "enabled" if entry.enabled else "disabled"
        print(f"{entry.name}: {status} -> {entry.module}")
        if entry.description:
            print(f"  {entry.description}")


def print_summary(results: Sequence[FetchResult]) -> None:
    succeeded = sum(1 for result in results if not result.skipped and result.returncode == 0)
    failed = sum(1 for result in results if result.returncode != 0)
    skipped = sum(1 for result in results if result.skipped)
    total_seconds = sum(result.duration_seconds for result in results)

    print("\nSummary")
    print(f"- succeeded: {succeeded}")
    print(f"- failed: {failed}")
    print(f"- skipped: {skipped}")
    print(f"- total runtime: {total_seconds:.2f}s")

    if failed:
        failed_names = ", ".join(result.name for result in results if result.returncode != 0)
        print(f"- failed fetchers: {failed_names}")
        for result in results:
            if result.returncode == 0:
                continue
            output_tail = _tail_lines("\n".join(part for part in (result.stdout, result.stderr) if part))
            if not output_tail:
                continue
            print(f"\nFailure details for {result.name}:")
            print(output_tail)


def main(argv: Sequence[str] | None = None, runner: Runner | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).resolve()
    entries = load_refresh_config(config_path)

    if args.list:
        print_fetcher_list(entries)
        return 0

    selected = select_fetchers(entries, only=args.only, skip=args.skip)
    results = run_fetchers(selected, fail_fast=args.fail_fast, runner=runner)
    print_summary(results)
    return 1 if any(result.returncode != 0 for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
