from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_sync_job_quota_state(monkeypatch):
    from app.services import sync_jobs

    sync_jobs._reset_gmail_quota_for_tests()
    monkeypatch.delenv("AGENTYS_GMAIL_PROJECT_UNITS_PER_MINUTE", raising=False)
    monkeypatch.delenv("AGENTYS_GMAIL_ACCOUNT_UNITS_PER_MINUTE", raising=False)
    monkeypatch.delenv("AGENTYS_GMAIL_QUOTA_SHARDS", raising=False)
    monkeypatch.delenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", raising=False)
    monkeypatch.delenv("AGENTYS_SYNC_JOB_LEASE_SECONDS", raising=False)
    yield
    sync_jobs._reset_gmail_quota_for_tests()


def test_sync_job_datetime_helpers_normalize_to_naive_utc():
    from datetime import datetime, timezone

    from app.services import sync_jobs

    aware = datetime(2026, 5, 20, 19, 46, 45, tzinfo=timezone.utc)

    assert sync_jobs._now_utc().tzinfo is None
    assert sync_jobs._coerce_utc(aware).tzinfo is None
    assert sync_jobs._coerce_utc("2026-05-20T19:46:45+00:00").tzinfo is None
    assert sync_jobs._datetime_to_json(aware) == "2026-05-20T19:46:45"
    assert sync_jobs._quota_window_start(aware).tzinfo is None


def test_sync_job_scope_lock_uses_postgres_advisory_lock():
    from app.services import sync_jobs

    calls = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, statement, params):
            calls.append((statement, params))

    sync_jobs._lock_sync_job_scope(_Session(), 13, "inbox")

    assert calls
    assert "pg_advisory_xact_lock" in str(calls[0][0])
    assert isinstance(calls[0][1]["namespace_key"], int)
    assert isinstance(calls[0][1]["scope_key"], int)


def test_sync_job_scope_lock_noops_outside_postgres():
    from app.services import sync_jobs

    class _Dialect:
        name = "sqlite"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, statement, params):  # pragma: no cover - guard should return first
            raise AssertionError("unexpected advisory lock call")

    sync_jobs._lock_sync_job_scope(_Session(), 13, "inbox")


def test_init_db_repairs_legacy_sync_jobs_backoff_columns(tmp_path, monkeypatch):
    from sqlalchemy import inspect, text

    from app.db.database import get_db_session, get_engine, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SyncJob
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "legacy_sync_jobs.db"))
    reset_engine()
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE sync_jobs (
                id VARCHAR(32) PRIMARY KEY,
                user_id BIGINT,
                account_id INTEGER NOT NULL,
                folder VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                source VARCHAR(32) NOT NULL,
                requested_limit INTEGER NOT NULL DEFAULT 50,
                unread_only BOOLEAN NOT NULL DEFAULT 0,
                coalesced_count INTEGER NOT NULL DEFAULT 0,
                started_at VARCHAR(32),
                completed_at VARCHAR(32),
                error_summary TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))

    init_db()

    sync_job_columns = {col["name"]: col for col in inspect(engine).get_columns("sync_jobs")}
    columns = set(sync_job_columns)
    assert "attempt_count" in columns
    assert "backoff_until" in columns
    assert "last_error_code" in columns
    assert "provider_units_estimate" in columns
    assert str(sync_job_columns["attempt_count"].get("default")).strip("'") == "0"
    assert str(sync_job_columns["provider_units_estimate"].get("default")).strip("'") == "0"

    with get_db_session() as session:
        account = Account(email="legacy-sync@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        result = enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)

    assert result["coalesced"] is False
    assert len(submitted) == 1

    with get_db_session() as session:
        job = session.get(SyncJob, result["id"])
        assert job is not None
        assert job.attempt_count >= 1
        assert job.provider_units_estimate >= 0

    reset_engine()


def test_enqueue_sync_job_coalesces_per_account_folder(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SyncJob
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "sync_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="sync@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        first = enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)
        second = enqueue_sync_job(account_id=account_id, folder="inbox", limit=200)

    assert first["coalesced"] is False
    assert second["coalesced"] is True
    assert first["id"] == second["id"]
    assert len(submitted) == 1

    with get_db_session() as session:
        job = session.get(SyncJob, first["id"])
        assert job is not None
        assert job.requested_limit == 100
        assert job.coalesced_count == 1

    reset_engine()


def test_enqueue_sync_job_reclaims_stale_running_job(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_FAILED,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "stale_sync_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="stale-sync@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            SyncJob(
                id="stale-job",
                account_id=account_id,
                folder="inbox",
                status="running",
                source="auto",
                requested_limit=100,
                unread_only=False,
                started_at=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
            )
        )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        replacement = enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)

    assert replacement["coalesced"] is False
    assert replacement["id"] != "stale-job"
    assert len(submitted) == 1

    with get_db_session() as session:
        stale = session.get(SyncJob, "stale-job")
        fresh = session.get(SyncJob, replacement["id"])
        assert stale is not None
        assert stale.status == SYNC_JOB_STATUS_FAILED
        assert stale.completed_at is not None
        assert stale.error_summary is not None
        assert "Stale sync job reclaimed" in stale.error_summary
        assert fresh is not None
        assert fresh.status == SYNC_JOB_STATUS_RUNNING
        assert fresh.lease_owner is not None
        assert fresh.lease_expires_at is not None

    reset_engine()


def test_enqueue_sync_job_reclaims_expired_running_lease(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "expired_lease_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="expired-lease@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            SyncJob(
                id="leased-job",
                account_id=account_id,
                folder="inbox",
                status=SYNC_JOB_STATUS_RUNNING,
                source="auto",
                requested_limit=100,
                unread_only=False,
                started_at=datetime.now(timezone.utc).isoformat(),
                lease_owner="old-worker",
                lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
                attempt_count=1,
            )
        )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        reclaimed = enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)

    assert reclaimed["id"] == "leased-job"
    assert reclaimed["coalesced"] is True
    assert len(submitted) == 1

    with get_db_session() as session:
        job = session.get(SyncJob, "leased-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_RUNNING
        assert job.lease_owner is not None
        assert job.lease_expires_at is not None
        assert job.error_summary is not None
        assert "Expired sync job lease reclaimed" in job.error_summary or "claimed" in job.error_summary

    reset_engine()


def test_enqueue_sync_job_reclaims_overdue_running_lease_with_future_expiry(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SYNC_JOB_STATUS_RUNNING, SyncJob
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "overdue_lease_jobs.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_LEASE_SECONDS", "60")
    reset_engine()
    init_db()

    now = datetime.now(timezone.utc)
    with get_db_session() as session:
        account = Account(email="overdue-lease@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            SyncJob(
                id="overdue-lease-job",
                account_id=account_id,
                folder="inbox",
                status=SYNC_JOB_STATUS_RUNNING,
                source="auto",
                requested_limit=100,
                unread_only=False,
                started_at=(now - timedelta(minutes=3)).isoformat(),
                lease_owner="old-worker",
                lease_expires_at=now + timedelta(minutes=12),
                attempt_count=1,
            )
        )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        reclaimed = enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)

    assert reclaimed["id"] == "overdue-lease-job"
    assert reclaimed["coalesced"] is True
    assert len(submitted) == 1

    with get_db_session() as session:
        job = session.get(SyncJob, "overdue-lease-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_RUNNING
        assert job.lease_owner is not None
        assert job.lease_owner != "old-worker"
        assert job.error_summary is not None
        assert "Expired sync job lease reclaimed" in job.error_summary

    reset_engine()


def test_enqueue_sync_job_respects_retry_backoff(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SYNC_JOB_STATUS_RETRY_WAITING, SyncJob
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "retry_waiting_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="retry-waiting@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            SyncJob(
                id="retry-job",
                account_id=account_id,
                folder="inbox",
                status=SYNC_JOB_STATUS_RETRY_WAITING,
                source="auto",
                requested_limit=50,
                unread_only=False,
                backoff_until=datetime.now(timezone.utc) + timedelta(minutes=5),
                attempt_count=1,
                last_error_code="RuntimeError",
            )
        )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        coalesced = enqueue_sync_job(account_id=account_id, folder="inbox", limit=100)

    assert coalesced["id"] == "retry-job"
    assert coalesced["coalesced"] is True
    assert coalesced["status"] == SYNC_JOB_STATUS_RETRY_WAITING
    assert submitted == []

    with get_db_session() as session:
        job = session.get(SyncJob, "retry-job")
        assert job is not None
        assert job.coalesced_count == 1
        assert job.requested_limit == 100

    reset_engine()


def test_enqueue_sync_job_dispatcher_caps_concurrent_jobs(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_QUEUED,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "dispatcher_cap.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", "3")
    reset_engine()
    init_db()

    account_ids = []
    with get_db_session() as session:
        for index in range(10):
            account = Account(email=f"burst-{index}@example.com", provider="gmail", user_id=42)
            session.add(account)
            session.flush()
            account_ids.append(account.id)

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        for account_id in account_ids:
            enqueue_sync_job(account_id=account_id, folder="inbox", limit=50)

    assert len(submitted) == 3

    with get_db_session() as session:
        running = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RUNNING).count()
        queued = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_QUEUED).count()
        assert running == 3
        assert queued == 7

    reset_engine()


def test_run_sync_job_dispatches_next_ready_job_after_completion(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_COMPLETED,
        SYNC_JOB_STATUS_QUEUED,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services.sync_jobs import _dispatch_ready_sync_jobs, _run_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "dispatcher_drain.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", "2")
    reset_engine()
    init_db()

    account_ids = []
    with get_db_session() as session:
        for index in range(3):
            account = Account(email=f"drain-{index}@example.com", provider="gmail", user_id=42)
            session.add(account)
            session.flush()
            account_ids.append(account.id)
            session.add(
                SyncJob(
                    id=f"drain-job-{index}",
                    account_id=account.id,
                    folder="inbox",
                    status=SYNC_JOB_STATUS_QUEUED,
                    source="manual",
                    requested_limit=50,
                    unread_only=False,
                )
            )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))):
        _dispatch_ready_sync_jobs()

    assert len(submitted) == 2
    first_job_id, first_lease_owner = submitted[0][1]

    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
         patch("app.api.routes_emails._sync_emails_to_cache"), \
         patch("app.api.websocket.emit_sync_progress"), \
         patch("app.api.websocket.emit_to_account"):
        _run_sync_job(first_job_id, first_lease_owner)

    assert len(submitted) == 3

    with get_db_session() as session:
        completed = session.get(SyncJob, first_job_id)
        assert completed is not None
        assert completed.status == SYNC_JOB_STATUS_COMPLETED
        running = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RUNNING).count()
        queued = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_QUEUED).count()
        assert running == 2
        assert queued == 0

    reset_engine()


def test_dispatcher_respects_gmail_project_quota_budget(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_QUEUED,
        SYNC_JOB_STATUS_RETRY_WAITING,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services import sync_jobs
    from app.services.sync_jobs import _dispatch_ready_sync_jobs

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "project_quota.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", "10")
    monkeypatch.setenv("AGENTYS_GMAIL_PROJECT_UNITS_PER_MINUTE", "200")
    monkeypatch.setenv("AGENTYS_GMAIL_ACCOUNT_UNITS_PER_MINUTE", "1000")
    monkeypatch.setenv("AGENTYS_GMAIL_QUOTA_SHARDS", "1")
    sync_jobs._reset_gmail_quota_for_tests()
    reset_engine()
    init_db()

    with get_db_session() as session:
        for index in range(3):
            account = Account(email=f"project-quota-{index}@example.com", provider="gmail", user_id=42)
            session.add(account)
            session.flush()
            session.add(
                SyncJob(
                    id=f"project-quota-job-{index}",
                    account_id=account.id,
                    folder="inbox",
                    status=SYNC_JOB_STATUS_QUEUED,
                    source="manual",
                    requested_limit=5,
                    unread_only=False,
                )
            )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))):
        claimed = _dispatch_ready_sync_jobs()

    assert len(claimed) == 1
    assert len(submitted) == 1

    with get_db_session() as session:
        running = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RUNNING).count()
        waiting = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RETRY_WAITING).count()
        queued = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_QUEUED).count()
        assert running == 1
        assert waiting == 2
        assert queued == 0

    sync_jobs._reset_gmail_quota_for_tests()
    reset_engine()


def test_dispatcher_persists_gmail_project_quota_between_dispatch_cycles(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.provider_quota_window import ProviderQuotaWindow
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_COMPLETED,
        SYNC_JOB_STATUS_QUEUED,
        SYNC_JOB_STATUS_RETRY_WAITING,
        SyncJob,
    )
    from app.services import sync_jobs
    from app.services.sync_jobs import _dispatch_ready_sync_jobs

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "durable_project_quota.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", "1")
    monkeypatch.setenv("AGENTYS_GMAIL_PROJECT_UNITS_PER_MINUTE", "200")
    monkeypatch.setenv("AGENTYS_GMAIL_ACCOUNT_UNITS_PER_MINUTE", "1000")
    monkeypatch.setenv("AGENTYS_GMAIL_QUOTA_SHARDS", "1")
    reset_engine()
    init_db()

    with get_db_session() as session:
        for index in range(2):
            account = Account(
                email=f"durable-quota-{index}@example.com",
                provider="gmail",
                user_id=42,
            )
            session.add(account)
            session.flush()
            session.add(
                SyncJob(
                    id=f"durable-quota-job-{index}",
                    account_id=account.id,
                    folder="inbox",
                    status=SYNC_JOB_STATUS_QUEUED,
                    source="manual",
                    requested_limit=5,
                    unread_only=False,
                )
            )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))):
        first_claimed = _dispatch_ready_sync_jobs()

    assert len(first_claimed) == 1
    assert len(submitted) == 1

    with get_db_session() as session:
        first_job = session.get(SyncJob, first_claimed[0])
        assert first_job is not None
        first_job.status = SYNC_JOB_STATUS_COMPLETED

    sync_jobs._reset_gmail_quota_for_tests()

    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))):
        second_claimed = _dispatch_ready_sync_jobs()

    assert second_claimed == []
    assert len(submitted) == 1

    with get_db_session() as session:
        waiting = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RETRY_WAITING).count()
        project_window = (
            session.query(ProviderQuotaWindow)
            .filter_by(provider="gmail", quota_scope="project", scope_key="project:0")
            .one()
        )
        assert waiting == 1
        assert project_window.units_reserved == 105

    reset_engine()


def test_dispatcher_respects_gmail_account_quota_budget(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_RETRY_WAITING,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services import sync_jobs
    from app.services.sync_jobs import _dispatch_ready_sync_jobs

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "account_quota.db"))
    monkeypatch.setenv("AGENTYS_SYNC_JOB_DISPATCH_CONCURRENCY", "10")
    monkeypatch.setenv("AGENTYS_GMAIL_PROJECT_UNITS_PER_MINUTE", "1000")
    monkeypatch.setenv("AGENTYS_GMAIL_ACCOUNT_UNITS_PER_MINUTE", "150")
    monkeypatch.setenv("AGENTYS_GMAIL_QUOTA_SHARDS", "1")
    sync_jobs._reset_gmail_quota_for_tests()
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="account-quota@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        for index, folder in enumerate(["inbox", "sent", "spam"]):
            session.add(
                SyncJob(
                    id=f"account-quota-job-{index}",
                    account_id=account_id,
                    folder=folder,
                    status="queued",
                    source="manual",
                    requested_limit=5,
                    unread_only=False,
                )
            )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))):
        claimed = _dispatch_ready_sync_jobs()

    assert len(claimed) == 1
    assert len(submitted) == 1

    with get_db_session() as session:
        running = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RUNNING).count()
        waiting = session.query(SyncJob).filter_by(status=SYNC_JOB_STATUS_RETRY_WAITING).count()
        assert running == 1
        assert waiting == 2

    sync_jobs._reset_gmail_quota_for_tests()
    reset_engine()


def test_enqueue_sync_job_requeues_after_retry_backoff(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_RETRY_WAITING,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services.sync_jobs import enqueue_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "retry_elapsed_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="retry-elapsed@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            SyncJob(
                id="retry-elapsed-job",
                account_id=account_id,
                folder="inbox",
                status=SYNC_JOB_STATUS_RETRY_WAITING,
                source="auto",
                requested_limit=50,
                unread_only=False,
                backoff_until=datetime.now(timezone.utc) - timedelta(seconds=5),
                attempt_count=1,
                last_error_code="RuntimeError",
            )
        )

    submitted = []
    with patch("app.services.sync_jobs.submit_background", lambda fn, *args: submitted.append((fn, args))), \
         patch("app.api.websocket.emit_sync_progress"):
        requeued = enqueue_sync_job(account_id=account_id, folder="inbox", limit=80)

    assert requeued["id"] == "retry-elapsed-job"
    assert requeued["coalesced"] is True
    assert len(submitted) == 1

    with get_db_session() as session:
        job = session.get(SyncJob, "retry-elapsed-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_RUNNING
        assert job.backoff_until is None
        assert job.lease_owner is not None
        assert job.lease_expires_at is not None
        assert job.requested_limit == 80

    reset_engine()


def test_run_sync_job_uses_specialized_sent_refresh(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SYNC_JOB_STATUS_COMPLETED, SyncJob
    from app.services.sync_jobs import _run_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "sent_sync_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="sent-sync@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        job = SyncJob(
            id="sent-job",
            account_id=account.id,
            folder="sent",
            status="queued",
            source="manual",
            requested_limit=50,
            unread_only=False,
        )
        session.add(job)
        account_id = account.id

    called = []
    with patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value="oauth-1"), \
         patch("app.api.routes_helpers._refresh_sent_cache_bg", lambda *args: called.append(args)), \
         patch("app.api.websocket.emit_sync_progress"), \
         patch("app.api.websocket.emit_to_account"):
        _run_sync_job("sent-job")

    assert called == [(account_id, "oauth-1", 50)]
    with get_db_session() as session:
        job = session.get(SyncJob, "sent-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_COMPLETED
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        assert job.attempt_count == 1

    reset_engine()


def test_sync_job_ticker_redispatches_elapsed_backoff_job(tmp_path, monkeypatch):
    """B-04 (audit 2026-06-11): a retry_waiting job whose backoff_until has
    elapsed must be re-dispatched by the periodic ticker even when no other
    enqueue/worker event fires."""
    import time
    from datetime import datetime, timedelta, timezone

    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import (
        SYNC_JOB_STATUS_RETRY_WAITING,
        SYNC_JOB_STATUS_RUNNING,
        SyncJob,
    )
    from app.services import sync_jobs

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "ticker_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="ticker@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        session.add(
            SyncJob(
                id="ticker-job",
                account_id=account.id,
                folder="inbox",
                status=SYNC_JOB_STATUS_RETRY_WAITING,
                source="auto",
                requested_limit=50,
                unread_only=False,
                backoff_until=datetime.now(timezone.utc) - timedelta(seconds=5),
                attempt_count=1,
                last_error_code="RuntimeError",
            )
        )

    submitted = []
    try:
        with patch(
            "app.services.sync_jobs.submit_background",
            lambda fn, *args: submitted.append((fn, args)),
        ):
            sync_jobs.start_sync_job_ticker(interval_seconds=0.05)
            deadline = time.monotonic() + 5.0
            while not submitted and time.monotonic() < deadline:
                time.sleep(0.05)
    finally:
        sync_jobs.stop_sync_job_ticker()

    assert len(submitted) >= 1, "ticker never re-dispatched the elapsed backoff job"

    with get_db_session() as session:
        job = session.get(SyncJob, "ticker-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_RUNNING
        assert job.backoff_until is None
        assert job.lease_owner is not None

    reset_engine()


def test_sync_job_ticker_start_is_idempotent():
    from app.services import sync_jobs

    try:
        with patch("app.services.sync_jobs._dispatch_ready_sync_jobs", return_value=[]):
            sync_jobs.start_sync_job_ticker(interval_seconds=60)
            first_thread = sync_jobs._ticker_thread
            sync_jobs.start_sync_job_ticker(interval_seconds=60)
            assert sync_jobs._ticker_thread is first_thread
            assert first_thread is not None and first_thread.is_alive()
    finally:
        sync_jobs.stop_sync_job_ticker()
    assert sync_jobs._ticker_thread is None


def test_sync_job_ticker_survives_dispatch_failure():
    """DB pas prête / erreur transitoire : le tick log un warning et continue,
    le thread ne meurt pas."""
    import time

    from app.services import sync_jobs

    try:
        with patch(
            "app.services.sync_jobs._dispatch_ready_sync_jobs",
            side_effect=RuntimeError("db not ready"),
        ):
            sync_jobs.start_sync_job_ticker(interval_seconds=0.01)
            time.sleep(0.2)  # plusieurs ticks en échec
            assert sync_jobs._ticker_thread is not None
            assert sync_jobs._ticker_thread.is_alive()
    finally:
        sync_jobs.stop_sync_job_ticker()


def test_run_sync_job_failure_enters_retry_backoff(tmp_path, monkeypatch):
    from app.db.database import get_db_session, init_db, reset_engine
    from app.db.models.account import Account
    from app.db.models.sync_job import SYNC_JOB_STATUS_RETRY_WAITING, SyncJob
    from app.services.sync_jobs import _run_sync_job

    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "failed_retry_jobs.db"))
    reset_engine()
    init_db()

    with get_db_session() as session:
        account = Account(email="failed-retry@example.com", provider="gmail", user_id=42)
        session.add(account)
        session.flush()
        session.add(
            SyncJob(
                id="failed-job",
                account_id=account.id,
                folder="inbox",
                status="queued",
                source="manual",
                requested_limit=50,
                unread_only=False,
            )
        )

    with patch("app.api.routes_helpers._resolve_oauth_account_id_for_db_account", return_value=""), \
         patch("app.api.websocket.emit_sync_progress"), \
         patch("app.api.websocket.emit_sync_error"):
        _run_sync_job("failed-job")

    with get_db_session() as session:
        job = session.get(SyncJob, "failed-job")
        assert job is not None
        assert job.status == SYNC_JOB_STATUS_RETRY_WAITING
        assert job.attempt_count == 1
        assert job.backoff_until is not None
        assert job.completed_at is None
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        assert job.last_error_code == "RuntimeError"
        assert job.error_summary is not None
        assert "No OAuth account configured" in job.error_summary

    reset_engine()
