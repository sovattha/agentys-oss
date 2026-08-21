import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.infrastructure import draft_job_queue
from app.infrastructure.draft_job_queue import DraftJobQueue, RedisDraftJobQueue


class _FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.values = {}
        self.deleted = []
        self.removed = []
        self.eval_calls = 0

    def pipeline(self):
        return self

    def execute(self):
        return []

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def expire(self, key, seconds):
        return True

    def exists(self, key):
        return int(key in self.hashes)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.deleted.append(key)
            self.hashes.pop(key, None)
            self.values.pop(key, None)

    def srem(self, key, *values):
        for value in values:
            self.removed.append((key, value))
            self.sets.setdefault(key, set()).discard(value)

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1

    def get(self, key):
        return self.values.get(key)

    def eval(self, script, numkeys, *keys_and_args):
        self.eval_calls += 1
        meta_key, account_set_key, global_set_key, status_key = keys_and_args[:numkeys]
        (
            key_hash,
            task_id,
            account_key,
            job_id,
            email_id_hash,
            now,
            ttl,
            queue_max,
            account_max,
            meta_prefix,
        ) = keys_and_args[numkeys:]
        existing_task_id = self.hget(meta_key, "task_id")
        if existing_task_id:
            return [
                "duplicate",
                existing_task_id,
                self.hget(meta_key, "account_key") or account_key,
                str(self.scard(global_set_key)),
                str(self.scard(account_set_key)),
            ]
        self._prune_set(account_set_key, meta_prefix)
        self._prune_set(global_set_key, meta_prefix)
        account_jobs = self.scard(account_set_key)
        global_jobs = self.scard(global_set_key)
        if account_jobs >= int(account_max):
            return ["account_full", "", account_key, str(global_jobs), str(account_jobs)]
        if global_jobs >= int(queue_max):
            return ["full", "", account_key, str(global_jobs), str(account_jobs)]
        self.hset(
            meta_key,
            mapping={
                "task_id": task_id,
                "account_key": account_key,
                "job_id": job_id,
                "email_id_hash": email_id_hash,
                "queued_at": now,
            },
        )
        self.hset(
            status_key,
            mapping={
                "task_id": task_id,
                "status": "queued",
                "job_id": job_id,
                "account_key": account_key,
                "email_id_hash": email_id_hash,
                "queued_at": now,
                "updated_at": now,
            },
        )
        self.sadd(account_set_key, key_hash)
        self.sadd(global_set_key, key_hash)
        return ["enqueued", task_id, account_key, str(global_jobs + 1), str(account_jobs + 1)]

    def _prune_set(self, key, meta_prefix):
        stale = [member for member in self.sets.get(key, set()) if not self.exists(meta_prefix + member)]
        if stale:
            self.srem(key, *stale)


class _FakeRqQueue:
    count = 0

    def __init__(self):
        self.jobs = []

    def enqueue(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_draft_job_queue_deduplicates_same_account_email():
    started = threading.Event()
    release = threading.Event()
    calls = []
    queue = DraftJobQueue(
        max_workers=1,
        queue_max=4,
        per_account_max=1,
        per_account_queue_max=4,
        retry_after_seconds=7,
    )

    def job():
        calls.append("run")
        started.set()
        release.wait(timeout=2)

    first = queue.enqueue(
        key="1:email-1",
        account_id=1,
        email_id="email-1",
        task_id="task-1",
        run=job,
    )
    assert started.wait(timeout=1)

    duplicate = queue.enqueue(
        key="1:email-1",
        account_id=1,
        email_id="email-1",
        task_id="task-2",
        run=lambda: calls.append("duplicate"),
    )

    release.set()
    queue.shutdown()

    assert first.status == "enqueued"
    assert duplicate.status == "duplicate"
    assert duplicate.task_id == "task-1"
    assert calls == ["run"]


def test_draft_job_queue_rejects_when_bounded_queue_is_full():
    first_started = threading.Event()
    release = threading.Event()
    queue = DraftJobQueue(
        max_workers=1,
        queue_max=1,
        per_account_max=1,
        per_account_queue_max=4,
        retry_after_seconds=9,
    )

    def blocking_job():
        first_started.set()
        release.wait(timeout=2)

    queue.enqueue(
        key="1:first",
        account_id=1,
        email_id="first",
        task_id="task-first",
        run=blocking_job,
    )
    assert first_started.wait(timeout=1)
    queued = queue.enqueue(
        key="1:queued",
        account_id=1,
        email_id="queued",
        task_id="task-queued",
        run=lambda: None,
    )
    full = queue.enqueue(
        key="1:full",
        account_id=1,
        email_id="full",
        task_id="task-full",
        run=lambda: None,
    )

    release.set()
    deadline = time.monotonic() + 1
    while queue.stats()["jobs_total"] and time.monotonic() < deadline:
        time.sleep(0.01)
    queue.shutdown()

    assert queued.status == "enqueued"
    assert full.status == "full"
    assert full.rejection_reason == "queue_full"
    assert full.retry_after_seconds == 9


def test_draft_job_queue_rejects_account_when_account_backlog_is_full():
    first_started = threading.Event()
    release = threading.Event()
    queue = DraftJobQueue(
        max_workers=1,
        queue_max=4,
        per_account_max=1,
        per_account_queue_max=2,
        retry_after_seconds=11,
    )

    def blocking_job():
        first_started.set()
        release.wait(timeout=2)

    queue.enqueue(
        key="1:first",
        account_id=1,
        email_id="first",
        task_id="task-first",
        run=blocking_job,
    )
    assert first_started.wait(timeout=1)
    second = queue.enqueue(
        key="1:second",
        account_id=1,
        email_id="second",
        task_id="task-second",
        run=lambda: None,
    )
    account_full = queue.enqueue(
        key="1:third",
        account_id=1,
        email_id="third",
        task_id="task-third",
        run=lambda: None,
    )
    other_account = queue.enqueue(
        key="2:first",
        account_id=2,
        email_id="other",
        task_id="task-other",
        run=lambda: None,
    )

    release.set()
    deadline = time.monotonic() + 1
    while queue.stats()["jobs_total"] and time.monotonic() < deadline:
        time.sleep(0.01)
    stats = queue.stats()
    queue.shutdown()

    assert second.status == "enqueued"
    assert account_full.status == "account_full"
    assert account_full.full is True
    assert account_full.rejection_reason == "account_queue_full"
    assert account_full.retry_after_seconds == 11
    assert other_account.status == "enqueued"
    assert stats["rejected_account_total"] == 1


def test_redis_draft_job_status_survives_release_for_api_polling():
    fake = _FakeRedis()
    queue = RedisDraftJobQueue(
        redis_url="redis://localhost:6379/0",
        queue_name="drafts-test",
        queue_max=100,
        per_account_queue_max=10,
        retry_after_seconds=7,
        job_timeout_seconds=60,
        job_ttl_seconds=300,
    )
    queue._connection = fake
    task_id = "task-status-123"
    status_key = queue._status_key(task_id)
    fake.hset(
        status_key,
        mapping={
            "task_id": task_id,
            "status": "queued",
            "queued_at": str(time.time() - 1),
            "updated_at": str(time.time() - 1),
        },
    )

    queue.mark_started(task_id=task_id)
    started = queue.get_status(task_id)
    queue.release(key="1:email-1", account_id=1, task_id=task_id)
    completed = queue.get_status(task_id)

    assert started["status"] == "started"
    assert started["queue_wait_ms"] >= 0
    assert completed["status"] == "completed"
    assert completed["ready"] is True
    assert completed["age_ms"] >= started["queue_wait_ms"]
    assert fake.values[queue._counter_key("completed_total")] == 1


def test_redis_shared_pending_draft_round_trip_by_email_and_id():
    fake = _FakeRedis()
    queue = RedisDraftJobQueue(
        redis_url="redis://localhost:6379/0",
        queue_name="drafts-test",
        queue_max=100,
        per_account_queue_max=10,
        retry_after_seconds=7,
        job_timeout_seconds=60,
        job_ttl_seconds=300,
    )
    queue._connection = fake
    draft = {
        "id": "draft-1",
        "email_id": "email-1",
        "account_id": "14",
        "draft_body": "Bonjour,\n\nRéponse.",
        "status": "pending",
    }

    queue.store_shared_pending_draft(
        draft=draft,
        account_id=14,
        email_id="email-1",
        draft_id="draft-1",
    )

    assert queue.get_shared_pending_draft_by_email(
        account_id=14,
        email_id="email-1",
    ) == draft
    assert queue.get_shared_pending_draft_by_id("draft-1") == draft

    queue.delete_shared_pending_draft(
        draft_id="draft-1",
        account_id=14,
        email_id="email-1",
    )

    assert queue.get_shared_pending_draft_by_email(
        account_id=14,
        email_id="email-1",
    ) is None
    assert queue.get_shared_pending_draft_by_id("draft-1") is None


def test_redis_draft_queue_uses_atomic_admission_without_locks():
    fake = _FakeRedis()
    fake_queue = _FakeRqQueue()
    queue = RedisDraftJobQueue(
        redis_url="redis://localhost:6379/0",
        queue_name="drafts-test",
        queue_max=100,
        per_account_queue_max=10,
        retry_after_seconds=7,
        job_timeout_seconds=60,
        job_ttl_seconds=300,
    )
    queue._connection = fake
    queue._queue = fake_queue

    first = queue.enqueue(
        key="1:email-1",
        account_id=1,
        email_id="email-1",
        task_id="task-1",
        payload={"email_id": "email-1"},
    )
    second = queue.enqueue(
        key="2:email-2",
        account_id=2,
        email_id="email-2",
        task_id="task-2",
        payload={"email_id": "email-2"},
    )

    assert first.status == "enqueued"
    assert second.status == "enqueued"
    assert len(fake_queue.jobs) == 2
    assert fake.eval_calls == 2
    assert fake.scard(queue._global_set_key()) == 2


def test_redis_draft_queue_atomic_admission_enforces_global_limit():
    fake = _FakeRedis()
    fake_queue = _FakeRqQueue()
    queue = RedisDraftJobQueue(
        redis_url="redis://localhost:6379/0",
        queue_name="drafts-test",
        queue_max=1,
        per_account_queue_max=10,
        retry_after_seconds=7,
        job_timeout_seconds=60,
        job_ttl_seconds=300,
    )
    queue._connection = fake
    queue._queue = fake_queue

    first = queue.enqueue(
        key="1:email-1",
        account_id=1,
        email_id="email-1",
        task_id="task-1",
        payload={"email_id": "email-1"},
    )
    second = queue.enqueue(
        key="2:email-2",
        account_id=2,
        email_id="email-2",
        task_id="task-2",
        payload={"email_id": "email-2"},
    )

    assert first.status == "enqueued"
    assert second.status == "full"
    assert second.rejection_reason == "queue_full"
    assert len(fake_queue.jobs) == 1


def test_redis_draft_queue_enqueue_failure_cleans_atomic_admission():
    fake = _FakeRedis()
    fake_queue = _FakeRqQueue()
    fake_queue.enqueue = Mock(side_effect=RuntimeError("rq unavailable"))
    queue = RedisDraftJobQueue(
        redis_url="redis://localhost:6379/0",
        queue_name="drafts-test",
        queue_max=100,
        per_account_queue_max=10,
        retry_after_seconds=7,
        job_timeout_seconds=60,
        job_ttl_seconds=300,
    )
    queue._connection = fake
    queue._queue = fake_queue

    with pytest.raises(RuntimeError, match="rq unavailable"):
        queue.enqueue(
            key="1:email-1",
            account_id=1,
            email_id="email-1",
            task_id="task-1",
            payload={"email_id": "email-1"},
        )

    key_hash = queue._hash_key("1:email-1")
    assert fake.scard(queue._global_set_key()) == 0
    assert key_hash not in fake.sets.get(queue._account_set_key("1"), set())
    assert queue._meta_key(key_hash) not in fake.hashes


def test_redis_queue_failure_falls_back_to_memory_only_outside_prod(monkeypatch):
    monkeypatch.setenv("DRAFT_QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("DRAFT_QUEUE_REDIS_FAIL_CLOSED", raising=False)
    monkeypatch.delenv("AGENTYS_LOAD_TEST_MODE", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)

    memory_submission = SimpleNamespace(status="enqueued")
    redis_queue = Mock()
    redis_queue.enqueue.side_effect = RuntimeError("redis lock timeout")

    with patch.object(draft_job_queue, "_get_redis_draft_queue", return_value=redis_queue), \
         patch.object(draft_job_queue._draft_queue, "enqueue", return_value=memory_submission) as memory_enqueue:
        submission = draft_job_queue.enqueue_draft_job(
            key="1:email",
            account_id=1,
            email_id="email",
            task_id="task",
            run=lambda: None,
            payload={"email_id": "email"},
        )

    assert submission is memory_submission
    memory_enqueue.assert_called_once()


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("DRAFT_QUEUE_REDIS_FAIL_CLOSED", "true"),
        ("AGENTYS_LOAD_TEST_MODE", "true"),
        ("RAILWAY_ENVIRONMENT", "production"),
    ],
)
def test_redis_queue_failure_fails_closed_for_prod_like_modes(monkeypatch, env_name, env_value):
    monkeypatch.setenv("DRAFT_QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    for name in (
        "DRAFT_QUEUE_REDIS_FAIL_CLOSED",
        "AGENTYS_LOAD_TEST_MODE",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "APP_ENV",
        "FLASK_ENV",
        "ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env_name, env_value)
    redis_queue = Mock()
    redis_queue.enqueue.side_effect = RuntimeError("redis lock timeout")

    with patch.object(draft_job_queue, "_get_redis_draft_queue", return_value=redis_queue), \
         patch.object(draft_job_queue._draft_queue, "enqueue") as memory_enqueue:
        submission = draft_job_queue.enqueue_draft_job(
            key="1:email",
            account_id=1,
            email_id="email",
            task_id="task",
            run=lambda: None,
            payload={"email_id": "email"},
        )

    assert submission.status == "full"
    assert submission.backend == "redis"
    assert submission.rejection_reason == "redis_lock_timeout"
    assert submission.retry_after_seconds == 10
    assert submission.queue_depth == submission.queue_max
    memory_enqueue.assert_not_called()
