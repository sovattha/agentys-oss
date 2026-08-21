from scripts.load_test_mocked import (
    classify_stage,
    parse_queue_events_by_account,
    wait_for_capacity_idle,
)


def test_parse_queue_events_by_account(tmp_path):
    log = tmp_path / "server.log"
    log.write_text(
        "\n".join(
            [
                "[DRAFT-QUEUE] status=enqueued email_id=load-run-dpm4000-a1-aaa account_id=1 task_id=t1",
                "[DRAFT-QUEUE] status=full email_id=load-run-dpm4000-a1-bbb account_id=1 queue_depth=50",
                "[DRAFT-QUEUE] status=duplicate email_id=load-run-dpm4000-a2-ccc account_id=2 task_id=t2",
                "[DRAFT-QUEUE] status=full email_id=load-other-dpm4000-a1-ddd account_id=1 queue_depth=50",
            ]
        ),
        encoding="utf-8",
    )

    stats = parse_queue_events_by_account(log, "load-run-dpm4000-")

    assert [(item.account_id, item.attempts, item.accepted, item.backpressure, item.duplicates) for item in stats] == [
        ("1", 2, 1, 1, 0),
        ("2", 1, 1, 0, 1),
    ]


def test_wait_for_capacity_idle_returns_true_when_queue_empty(monkeypatch):
    monkeypatch.setattr(
        "scripts.load_test_mocked.read_capacity",
        lambda url: {"draft_queue": {"queue_depth": 0, "active_workers": 0, "jobs_total": 0}},
    )

    assert wait_for_capacity_idle("http://127.0.0.1:5050", timeout_seconds=1) is True


def test_classify_stage_marks_drain_timeout_degraded():
    status, reason = classify_stage(
        locust_exit_code=0,
        server_alive=True,
        drain_completed=False,
        failures=0,
        aggregate_p95_ms=50,
        process_p95_ms=50,
        background_p95_ms=100,
        backpressure_count=0,
        max_failure_rate=0.001,
        http_p95_degraded_ms=250,
        background_p95_degraded_ms=1500,
        requests=10,
    )

    assert status == "degraded"
    assert reason == "drain_timeout"
