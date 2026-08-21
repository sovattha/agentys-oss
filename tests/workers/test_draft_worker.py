"""Tests for draft worker process naming."""

from app.workers import draft_worker


def test_worker_name_includes_unique_runtime_identity(monkeypatch):
    monkeypatch.delenv("RQ_WORKER_NAME", raising=False)
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-123456789")
    monkeypatch.setenv("HOSTNAME", "host-abcdef")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "abcdef1234567890")
    monkeypatch.setattr(draft_worker.os, "getpid", lambda: 4242)

    assert (
        draft_worker._worker_name(3)
        == "draft-worker-replica-1234-host-abcdef-abcdef123456-4242-3"
    )


def test_worker_name_keeps_configured_prefix_unique_per_process(monkeypatch):
    monkeypatch.setenv("RQ_WORKER_NAME", "custom-worker")
    monkeypatch.setenv("HOSTNAME", "host-abcdef")
    monkeypatch.setattr(draft_worker.os, "getpid", lambda: 4242)

    assert draft_worker._worker_name(1) == "custom-worker-host-abcdef-4242-1"
    assert draft_worker._worker_name(2) == "custom-worker-host-abcdef-4242-2"


def test_worker_class_defaults_to_fork_worker(monkeypatch):
    monkeypatch.delenv("DRAFT_RQ_WORKER_MODE", raising=False)

    worker_class, mode = draft_worker._select_worker_class(_NullLogger())

    assert worker_class.__name__ == "Worker"
    assert mode == "fork"


def test_worker_class_can_use_simple_mode(monkeypatch):
    monkeypatch.setenv("DRAFT_RQ_WORKER_MODE", "simple")

    worker_class, mode = draft_worker._select_worker_class(_NullLogger())

    assert worker_class.__name__ == "SimpleWorker"
    assert mode == "simple"


class _NullLogger:
    def warning(self, *_args, **_kwargs):
        return None
