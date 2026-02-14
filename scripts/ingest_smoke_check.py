#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_OUTPUT = "derived/reports/ingest_smoke_check.json"


def _run_command(command: str, timeout_seconds: float) -> Dict[str, Any]:
    started_at = time.perf_counter()
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration_seconds = time.perf_counter() - started_at
        return {
            "command": command,
            "duration_seconds": duration_seconds,
            "returncode": result.returncode,
            "status": "success" if result.returncode == 0 else "failure",
            "stdout_tail": result.stdout[-500:],
            "stderr_tail": result.stderr[-500:],
        }
    except subprocess.TimeoutExpired as exc:
        duration_seconds = time.perf_counter() - started_at
        return {
            "command": command,
            "duration_seconds": duration_seconds,
            "returncode": None,
            "status": "timeout",
            "stdout_tail": (exc.stdout or "")[-500:],
            "stderr_tail": (exc.stderr or "")[-500:],
        }


def run_smoke_check(
    commands: List[str],
    runs: int,
    timeout_seconds: float,
    runner=_run_command,
) -> Dict[str, Any]:
    run_results: List[Dict[str, Any]] = []
    for run_idx in range(1, runs + 1):
        for command in commands:
            record = runner(command, timeout_seconds)
            record["run_index"] = run_idx
            run_results.append(record)

    by_command: Dict[str, Dict[str, Any]] = {}
    for command in commands:
        records = [item for item in run_results if item["command"] == command]
        durations = [item["duration_seconds"] for item in records]
        success_count = sum(1 for item in records if item["status"] == "success")
        failure_count = sum(1 for item in records if item["status"] in {"failure", "timeout"})
        by_command[command] = {
            "runs": len(records),
            "success_count": success_count,
            "failure_count": failure_count,
            "min_duration_seconds": min(durations) if durations else None,
            "max_duration_seconds": max(durations) if durations else None,
            "avg_duration_seconds": (sum(durations) / len(durations)) if durations else None,
        }

    db_env_keys = ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    db_env_present = all(bool(os.getenv(key)) for key in db_env_keys)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_env_keys_checked": db_env_keys,
        "db_env_present": db_env_present,
        "commands": commands,
        "runs": runs,
        "results": run_results,
        "summary_by_command": by_command,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run lightweight ingest smoke checks and write a machine-readable JSON summary "
            "(duration + success/failure)."
        )
    )
    parser.add_argument(
        "--command",
        action="append",
        required=True,
        help="Command to execute (repeatable). Example: --command \"python -m data_fetchers.stock_prices AAPL MSFT\"",
    )
    parser.add_argument("--runs", type=int, default=1, help="Number of times to run each command.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=600.0,
        help="Per-command timeout in seconds.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Path to output JSON summary (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional label included in output for before/after comparisons.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be >= 1")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be > 0")

    summary = run_smoke_check(
        commands=args.command,
        runs=args.runs,
        timeout_seconds=args.timeout_seconds,
    )
    if args.label:
        summary["label"] = args.label

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote ingest smoke summary to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
