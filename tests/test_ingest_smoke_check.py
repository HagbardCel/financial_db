from scripts.ingest_smoke_check import run_smoke_check


def test_run_smoke_check_summarizes_success_and_failure():
    outcomes = {
        "ok-cmd": [
            {"status": "success", "returncode": 0, "duration_seconds": 0.5, "stdout_tail": "", "stderr_tail": ""},
            {"status": "success", "returncode": 0, "duration_seconds": 0.7, "stdout_tail": "", "stderr_tail": ""},
        ],
        "fail-cmd": [
            {"status": "failure", "returncode": 1, "duration_seconds": 1.2, "stdout_tail": "", "stderr_tail": "err"},
            {"status": "success", "returncode": 0, "duration_seconds": 0.8, "stdout_tail": "", "stderr_tail": ""},
        ],
    }
    call_counts = {"ok-cmd": 0, "fail-cmd": 0}

    def fake_runner(command: str, timeout_seconds: float):
        _ = timeout_seconds
        idx = call_counts[command]
        call_counts[command] += 1
        record = dict(outcomes[command][idx])
        record["command"] = command
        return record

    summary = run_smoke_check(
        commands=["ok-cmd", "fail-cmd"],
        runs=2,
        timeout_seconds=10.0,
        runner=fake_runner,
    )

    assert len(summary["results"]) == 4
    assert summary["summary_by_command"]["ok-cmd"]["success_count"] == 2
    assert summary["summary_by_command"]["ok-cmd"]["failure_count"] == 0
    assert summary["summary_by_command"]["fail-cmd"]["success_count"] == 1
    assert summary["summary_by_command"]["fail-cmd"]["failure_count"] == 1
    assert summary["summary_by_command"]["ok-cmd"]["avg_duration_seconds"] == 0.6
