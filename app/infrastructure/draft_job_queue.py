"""Bounded draft generation queue.

Keeps /process from creating one Python thread per request. The HTTP handler
enqueues work and returns 202 quickly; a fixed worker pool drains the queue.
"""

from __future__ import annotations

import os
import queue
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.infrastructure.logging_config import get_logger
from app.infrastructure.redis_config import get_redis_url

logger = get_logger(__name__)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _redis_queue_fail_closed() -> bool:
    if _env_flag("DRAFT_QUEUE_REDIS_FAIL_CLOSED"):
        return True
    if _env_flag("AGENTYS_LOAD_TEST_MODE"):
        return True
    prod_markers = (
        os.getenv("RAILWAY_ENVIRONMENT"),
        os.getenv("RAILWAY_ENVIRONMENT_NAME"),
        os.getenv("APP_ENV"),
        os.getenv("FLASK_ENV"),
        os.getenv("ENV"),
    )
    return any((value or "").strip().lower() == "production" for value in prod_markers)


def _redis_enqueue_failure_reason(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "lock" in name or "lock" in text:
        return "redis_lock_timeout"
    if "timeout" in name or "timeout" in text:
        return "redis_timeout"
    if "connection" in name or "connection" in text:
        return "redis_connection_error"
    return "redis_unavailable"


@dataclass(frozen=True)
class DraftJobSubmission:
    status: str
    task_id: str
    queue_depth: int
    queue_max: int
    active_workers: int
    active_for_account: int
    retry_after_seconds: int = 0
    backend: str = "memory"
    rejection_reason: str = ""

    @property
    def enqueued(self) -> bool:
        return self.status == "enqueued"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"

    @property
    def full(self) -> bool:
        return self.status in {"full", "account_full"}


@dataclass(frozen=True)
class _DraftJob:
    key: str
    account_key: str
    email_id: str
    task_id: str
    run: Callable[[], None]
    enqueued_at: float


@dataclass
class _DraftJobState:
    task_id: str
    account_key: str
    status: str
    enqueued_at: float


class DraftJobQueue:
    """Fixed-size worker queue for draft generation jobs."""

    def __init__(
        self,
        *,
        max_workers: int,
        queue_max: int,
        per_account_max: int,
        per_account_queue_max: int,
        retry_after_seconds: int,
    ) -> None:
        self.max_workers = max(1, max_workers)
        self.queue_max = max(1, queue_max)
        self.per_account_max = max(1, per_account_max)
        self.per_account_queue_max = max(self.per_account_max, per_account_queue_max)
        self.retry_after_seconds = max(1, retry_after_seconds)
        self._queue: "queue.Queue[_DraftJob | None]" = queue.Queue(maxsize=self.queue_max)
        self._lock = threading.RLock()
        self._started = False
        self._workers: list[threading.Thread] = []
        self._jobs_by_key: dict[str, _DraftJobState] = {}
        self._account_semaphores: dict[str, threading.Semaphore] = {}
        self._active_workers = 0
        self._active_by_account: dict[str, int] = {}
        self._rejected_total = 0
        self._rejected_queue_total = 0
        self._rejected_account_total = 0
        self._submitted_total = 0
        self._duplicate_total = 0
        self._completed_total = 0
        self._failed_total = 0
        self._queue_wait_ms_total = 0
        self._queue_wait_samples = 0
        self._queue_wait_ms_max = 0

    def enqueue(
        self,
        *,
        key: str,
        account_id: object,
        email_id: str,
        task_id: str,
        run: Callable[[], None],
    ) -> DraftJobSubmission:
        """Add a draft job or report duplicate/full without blocking."""
        account_key = self._account_key(account_id)
        self._ensure_started()
        with self._lock:
            existing = self._jobs_by_key.get(key)
            if existing is not None:
                self._duplicate_total += 1
                return self._submission(
                    status="duplicate",
                    task_id=existing.task_id,
                    account_key=existing.account_key,
                )
            if self._account_job_count(account_key) >= self.per_account_queue_max:
                self._rejected_total += 1
                self._rejected_account_total += 1
                return self._submission(
                    status="account_full",
                    task_id=task_id,
                    account_key=account_key,
                    retry_after_seconds=self.retry_after_seconds,
                    rejection_reason="account_queue_full",
                )
            if self._queue.full():
                self._rejected_total += 1
                self._rejected_queue_total += 1
                return self._submission(
                    status="full",
                    task_id=task_id,
                    account_key=account_key,
                    retry_after_seconds=self.retry_after_seconds,
                    rejection_reason="queue_full",
                )

            job = _DraftJob(
                key=key,
                account_key=account_key,
                email_id=email_id,
                task_id=task_id,
                run=run,
                enqueued_at=time.monotonic(),
            )
            self._jobs_by_key[key] = _DraftJobState(
                task_id=task_id,
                account_key=account_key,
                status="queued",
                enqueued_at=job.enqueued_at,
            )
            self._submitted_total += 1

        try:
            self._queue.put_nowait(job)
        except queue.Full:
            with self._lock:
                self._jobs_by_key.pop(key, None)
                self._rejected_total += 1
                self._rejected_queue_total += 1
            return self._submission(
                status="full",
                task_id=task_id,
                account_key=account_key,
                retry_after_seconds=self.retry_after_seconds,
                rejection_reason="queue_full",
            )

        return self._submission(status="enqueued", task_id=task_id, account_key=account_key)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "queue_depth": self._queue.qsize(),
                "queue_max": self.queue_max,
                "max_workers": self.max_workers,
                "per_account_max": self.per_account_max,
                "per_account_queue_max": self.per_account_queue_max,
                "active_workers": self._active_workers,
                "jobs_total": len(self._jobs_by_key),
                "rejected_total": self._rejected_total,
                "rejected_queue_total": self._rejected_queue_total,
                "rejected_account_total": self._rejected_account_total,
                "submitted_total": self._submitted_total,
                "duplicate_total": self._duplicate_total,
                "completed_total": self._completed_total,
                "failed_total": self._failed_total,
                "queue_wait_ms_avg": int(
                    self._queue_wait_ms_total / self._queue_wait_samples
                )
                if self._queue_wait_samples
                else 0,
                "queue_wait_ms_max": self._queue_wait_ms_max,
                "retry_after_seconds": self.retry_after_seconds,
            }

    def shutdown(self) -> None:
        for _ in range(len(self._workers)):
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        for worker in self._workers:
            worker.join(timeout=1)

    def _submission(
        self,
        *,
        status: str,
        task_id: str,
        account_key: str,
        retry_after_seconds: int = 0,
        rejection_reason: str = "",
    ) -> DraftJobSubmission:
        with self._lock:
            return DraftJobSubmission(
                status=status,
                task_id=task_id,
                queue_depth=self._queue.qsize(),
                queue_max=self.queue_max,
                active_workers=self._active_workers,
                active_for_account=self._active_by_account.get(account_key, 0),
                retry_after_seconds=retry_after_seconds,
                backend="memory",
                rejection_reason=rejection_reason,
            )

    def _ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            for index in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"draft-worker-{index + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)
            self._started = True

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                return

            semaphore = self._get_account_semaphore(job.account_key)
            queue_wait_ms = int((time.monotonic() - job.enqueued_at) * 1000)
            semaphore.acquire()
            with self._lock:
                state = self._jobs_by_key.get(job.key)
                if state is not None:
                    state.status = "running"
                self._active_workers += 1
                self._active_by_account[job.account_key] = (
                    self._active_by_account.get(job.account_key, 0) + 1
                )
                self._queue_wait_ms_total += queue_wait_ms
                self._queue_wait_samples += 1
                self._queue_wait_ms_max = max(self._queue_wait_ms_max, queue_wait_ms)
            job_failed = False
            try:
                if queue_wait_ms >= 500:
                    logger.warning(
                        "[DRAFT-QUEUE] status=started email_id=%s account=%s "
                        "queue_wait_ms=%s queue_depth=%s active_workers=%s",
                        job.email_id,
                        job.account_key,
                        queue_wait_ms,
                        self._queue.qsize(),
                        self._active_workers,
                    )
                job.run()
            except Exception:
                job_failed = True
                with self._lock:
                    self._failed_total += 1
                raise
            finally:
                with self._lock:
                    self._jobs_by_key.pop(job.key, None)
                    self._active_workers = max(0, self._active_workers - 1)
                    if not job_failed:
                        self._completed_total += 1
                    active_for_account = max(
                        0,
                        self._active_by_account.get(job.account_key, 0) - 1,
                    )
                    if active_for_account:
                        self._active_by_account[job.account_key] = active_for_account
                    else:
                        self._active_by_account.pop(job.account_key, None)
                semaphore.release()
                self._queue.task_done()

    def _get_account_semaphore(self, account_key: str) -> threading.Semaphore:
        with self._lock:
            semaphore = self._account_semaphores.get(account_key)
            if semaphore is None:
                semaphore = threading.Semaphore(self.per_account_max)
                self._account_semaphores[account_key] = semaphore
            return semaphore

    def _account_job_count(self, account_key: str) -> int:
        return sum(
            1 for state in self._jobs_by_key.values()
            if state.account_key == account_key
        )

    @staticmethod
    def _account_key(account_id: object) -> str:
        if account_id in (None, "", -1):
            return "__global__"
        return str(account_id)


class RedisDraftJobQueue:
    """RQ-backed draft queue for deployments with separate worker services."""

    _ADMISSION_SCRIPT = """
local meta_key = KEYS[1]
local account_set_key = KEYS[2]
local global_set_key = KEYS[3]
local status_key = KEYS[4]

local key_hash = ARGV[1]
local task_id = ARGV[2]
local account_key = ARGV[3]
local job_id = ARGV[4]
local email_id_hash = ARGV[5]
local now = ARGV[6]
local ttl = tonumber(ARGV[7])
local queue_max = tonumber(ARGV[8])
local account_max = tonumber(ARGV[9])
local meta_prefix = ARGV[10]

local existing_task_id = redis.call("HGET", meta_key, "task_id")
if existing_task_id then
    local existing_account_key = redis.call("HGET", meta_key, "account_key") or account_key
    return {
        "duplicate",
        existing_task_id,
        existing_account_key,
        tostring(redis.call("SCARD", global_set_key)),
        tostring(redis.call("SCARD", account_set_key))
    }
end

local account_members = redis.call("SMEMBERS", account_set_key)
for _, member in ipairs(account_members) do
    if redis.call("EXISTS", meta_prefix .. member) == 0 then
        redis.call("SREM", account_set_key, member)
    end
end

local global_members = redis.call("SMEMBERS", global_set_key)
for _, member in ipairs(global_members) do
    if redis.call("EXISTS", meta_prefix .. member) == 0 then
        redis.call("SREM", global_set_key, member)
    end
end

local account_jobs = redis.call("SCARD", account_set_key)
local global_jobs = redis.call("SCARD", global_set_key)

if account_jobs >= account_max then
    return {"account_full", "", account_key, tostring(global_jobs), tostring(account_jobs)}
end
if global_jobs >= queue_max then
    return {"full", "", account_key, tostring(global_jobs), tostring(account_jobs)}
end

redis.call(
    "HSET",
    meta_key,
    "task_id", task_id,
    "account_key", account_key,
    "job_id", job_id,
    "email_id_hash", email_id_hash,
    "queued_at", now
)
redis.call(
    "HSET",
    status_key,
    "task_id", task_id,
    "status", "queued",
    "job_id", job_id,
    "account_key", account_key,
    "email_id_hash", email_id_hash,
    "queued_at", now,
    "updated_at", now
)
redis.call("EXPIRE", meta_key, ttl)
redis.call("EXPIRE", status_key, ttl)
redis.call("SADD", account_set_key, key_hash)
redis.call("EXPIRE", account_set_key, ttl)
redis.call("SADD", global_set_key, key_hash)
redis.call("EXPIRE", global_set_key, ttl)

return {
    "enqueued",
    task_id,
    account_key,
    tostring(global_jobs + 1),
    tostring(account_jobs + 1)
}
"""

    def __init__(
        self,
        *,
        redis_url: str,
        queue_name: str,
        queue_max: int,
        per_account_queue_max: int,
        retry_after_seconds: int,
        job_timeout_seconds: int,
        job_ttl_seconds: int,
    ) -> None:
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.queue_max = max(1, queue_max)
        self.per_account_queue_max = max(1, per_account_queue_max)
        self.retry_after_seconds = max(1, retry_after_seconds)
        self.job_timeout_seconds = max(1, job_timeout_seconds)
        self.job_ttl_seconds = max(60, job_ttl_seconds)
        self._connection = None
        self._queue = None

    def enqueue(
        self,
        *,
        key: str,
        account_id: object,
        email_id: str,
        task_id: str,
        payload: dict[str, Any] | None,
    ) -> DraftJobSubmission:
        if payload is None:
            raise ValueError("Redis draft jobs require a serializable payload")

        account_key = DraftJobQueue._account_key(account_id)
        key_hash = self._hash_key(key)
        job_id = f"draft-{key_hash}"
        meta_key = self._meta_key(key_hash)
        account_set_key = self._account_set_key(account_key)
        connection = self._get_connection()
        queue_obj = self._get_queue()

        status, existing_task_id, existing_account_key, global_jobs, account_jobs = (
            self._admit_atomically(
                connection=connection,
                key_hash=key_hash,
                task_id=task_id,
                account_key=account_key,
                job_id=job_id,
                email_id=email_id,
                meta_key=meta_key,
                account_set_key=account_set_key,
            )
        )

        if status == "duplicate":
            self._incr("duplicate_total")
            return self._submission(
                status="duplicate",
                task_id=existing_task_id or task_id,
                account_key=existing_account_key or account_key,
                queue_depth=global_jobs,
                active_for_account=account_jobs,
            )
        if status == "account_full":
            self._incr("rejected_total")
            self._incr("rejected_account_total")
            return self._submission(
                status="account_full",
                task_id=task_id,
                account_key=account_key,
                queue_depth=global_jobs,
                active_for_account=account_jobs,
                retry_after_seconds=self.retry_after_seconds,
                rejection_reason="account_queue_full",
            )
        if status == "full":
            self._incr("rejected_total")
            self._incr("rejected_queue_total")
            return self._submission(
                status="full",
                task_id=task_id,
                account_key=account_key,
                queue_depth=global_jobs,
                active_for_account=account_jobs,
                retry_after_seconds=self.retry_after_seconds,
                rejection_reason="queue_full",
            )

        from app.application.draft_worker_job import process_draft_generation_job

        job_payload = dict(payload)
        job_payload["job_key"] = key
        job_payload["job_account_id"] = account_id
        try:
            queue_obj.enqueue(
                process_draft_generation_job,
                job_payload,
                job_id=job_id,
                job_timeout=self.job_timeout_seconds,
                ttl=self.job_ttl_seconds,
                result_ttl=300,
                failure_ttl=86400,
                meta={
                    "draft_key_hash": key_hash,
                    "account_key": account_key,
                    "email_id": email_id,
                    "task_id": task_id,
                },
            )
        except Exception:
            self._cleanup_admission(
                connection=connection,
                key_hash=key_hash,
                account_key=account_key,
                meta_key=meta_key,
                status_key=self._status_key(task_id),
                account_set_key=account_set_key,
            )
            raise
        self._incr("submitted_total")

        return self._submission(
            status="enqueued",
            task_id=task_id,
            account_key=account_key,
            queue_depth=global_jobs,
            active_for_account=account_jobs,
        )

    def mark_started(self, *, task_id: str) -> None:
        if not task_id:
            return
        now = time.time()
        connection = self._get_connection()
        pipe = connection.pipeline()
        pipe.hset(
            self._status_key(task_id),
            mapping={
                "status": "started",
                "started_at": str(now),
                "updated_at": str(now),
            },
        )
        pipe.expire(self._status_key(task_id), self.job_ttl_seconds)
        pipe.execute()

    def release(
        self,
        *,
        key: str,
        account_id: object,
        task_id: str | None = None,
        failed: bool = False,
        error: str | None = None,
    ) -> None:
        connection = self._get_connection()
        account_key = DraftJobQueue._account_key(account_id)
        key_hash = self._hash_key(key)
        now = time.time()
        terminal_field = "failed_at" if failed else "completed_at"
        status_mapping = {
            "status": "failed" if failed else "completed",
            terminal_field: str(now),
            "updated_at": str(now),
        }
        if error:
            status_mapping["error"] = error[:500]
        pipe = connection.pipeline()
        pipe.delete(self._meta_key(key_hash))
        pipe.srem(self._account_set_key(account_key), key_hash)
        pipe.srem(self._global_set_key(), key_hash)
        pipe.incr(self._counter_key("failed_total" if failed else "completed_total"))
        if task_id:
            pipe.hset(self._status_key(task_id), mapping=status_mapping)
            pipe.expire(self._status_key(task_id), self.job_ttl_seconds)
        pipe.execute()

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        if not task_id:
            return None
        raw = self._get_connection().hgetall(self._status_key(task_id))
        if not raw:
            return None
        data = {self._decode(key): self._decode(value) for key, value in raw.items()}
        for name in ("queued_at", "started_at", "completed_at", "failed_at", "updated_at"):
            value = data.get(name)
            if value is None:
                continue
            try:
                data[f"{name}_epoch"] = float(value)
            except (TypeError, ValueError):
                pass
        queued_at = data.get("queued_at_epoch")
        started_at = data.get("started_at_epoch")
        completed_at = data.get("completed_at_epoch")
        failed_at = data.get("failed_at_epoch")
        terminal_at = completed_at if isinstance(completed_at, float) else failed_at
        if isinstance(queued_at, float):
            end = terminal_at if isinstance(terminal_at, float) else time.time()
            data["age_ms"] = int((end - queued_at) * 1000)
        if isinstance(queued_at, float) and isinstance(started_at, float):
            data["queue_wait_ms"] = int((started_at - queued_at) * 1000)
        if isinstance(started_at, float) and isinstance(terminal_at, float):
            data["run_ms"] = int((terminal_at - started_at) * 1000)
        data["ready"] = data.get("status") == "completed"
        return data

    def store_shared_pending_draft(
        self,
        *,
        draft: dict[str, Any],
        account_id: object,
        email_id: str,
        draft_id: str,
    ) -> None:
        if not draft or not email_id or not draft_id:
            return
        payload = json.dumps(draft, ensure_ascii=False)
        ttl = max(
            self.job_ttl_seconds,
            _positive_int_env("DRAFT_SHARED_PENDING_TTL_SECONDS", 30 * 24 * 3600),
        )
        pipe = self._get_connection().pipeline()
        pipe.set(
            self._shared_pending_email_key(account_id, email_id),
            payload,
            ex=ttl,
        )
        pipe.set(
            self._shared_pending_id_key(draft_id),
            payload,
            ex=ttl,
        )
        pipe.execute()

    def get_shared_pending_draft_by_email(
        self,
        *,
        account_id: object,
        email_id: str,
    ) -> dict[str, Any] | None:
        if not email_id:
            return None
        raw = self._get_connection().get(
            self._shared_pending_email_key(account_id, email_id)
        )
        return self._decode_json_dict(raw)

    def get_shared_pending_draft_by_id(self, draft_id: str) -> dict[str, Any] | None:
        if not draft_id:
            return None
        raw = self._get_connection().get(self._shared_pending_id_key(draft_id))
        return self._decode_json_dict(raw)

    def delete_shared_pending_draft(
        self,
        *,
        draft_id: str,
        account_id: object | None = None,
        email_id: str | None = None,
    ) -> None:
        keys = []
        if draft_id:
            keys.append(self._shared_pending_id_key(draft_id))
        if account_id is not None and email_id:
            keys.append(self._shared_pending_email_key(account_id, email_id))
        if keys:
            self._get_connection().delete(*keys)

    def stats(self) -> dict[str, int]:
        connection = self._get_connection()
        queue_depth = self._queue_depth()
        active_workers = self._started_count()
        admitted_jobs = self._admitted_count(connection)
        return {
            "queue_depth": queue_depth,
            "queue_max": self.queue_max,
            "max_workers": _positive_int_env("DRAFT_RQ_WORKERS", 0),
            "per_account_max": _positive_int_env("DRAFT_PER_ACCOUNT_MAX", 4),
            "per_account_queue_max": self.per_account_queue_max,
            "active_workers": active_workers,
            "jobs_total": max(queue_depth + active_workers, admitted_jobs),
            "rejected_total": self._counter(connection, "rejected_total"),
            "rejected_queue_total": self._counter(connection, "rejected_queue_total"),
            "rejected_account_total": self._counter(connection, "rejected_account_total"),
            "submitted_total": self._counter(connection, "submitted_total"),
            "duplicate_total": self._counter(connection, "duplicate_total"),
            "completed_total": self._counter(connection, "completed_total"),
            "failed_total": self._counter(connection, "failed_total"),
            "queue_wait_ms_avg": 0,
            "queue_wait_ms_max": 0,
            "retry_after_seconds": self.retry_after_seconds,
        }

    def _get_connection(self):
        if self._connection is None:
            from redis import Redis

            self._connection = Redis.from_url(self.redis_url)
            self._connection.ping()
        return self._connection

    def _get_queue(self):
        if self._queue is None:
            from rq import Queue

            self._queue = Queue(self.queue_name, connection=self._get_connection())
        return self._queue

    def _queue_depth(self) -> int:
        queue_obj = self._get_queue()
        try:
            return int(queue_obj.count)
        except Exception:
            return int(len(queue_obj))

    def _started_count(self) -> int:
        try:
            from rq.registry import StartedJobRegistry

            return int(
                StartedJobRegistry(
                    self.queue_name,
                    connection=self._get_connection(),
                ).count
            )
        except Exception:
            return 0

    def _submission(
        self,
        *,
        status: str,
        task_id: str,
        account_key: str,
        queue_depth: int,
        active_for_account: int,
        retry_after_seconds: int = 0,
        rejection_reason: str = "",
    ) -> DraftJobSubmission:
        return DraftJobSubmission(
            status=status,
            task_id=task_id,
            queue_depth=queue_depth,
            queue_max=self.queue_max,
            active_workers=self._started_count(),
            active_for_account=active_for_account,
            retry_after_seconds=retry_after_seconds,
            backend="redis",
            rejection_reason=rejection_reason,
        )

    def _admit_atomically(
        self,
        *,
        connection,
        key_hash: str,
        task_id: str,
        account_key: str,
        job_id: str,
        email_id: str,
        meta_key: str,
        account_set_key: str,
    ) -> tuple[str, str, str, int, int]:
        now = str(time.time())
        result = connection.eval(
            self._ADMISSION_SCRIPT,
            4,
            meta_key,
            account_set_key,
            self._global_set_key(),
            self._status_key(task_id),
            key_hash,
            task_id,
            account_key,
            job_id,
            self._hash_key(email_id),
            now,
            str(self.job_ttl_seconds),
            str(self.queue_max),
            str(self.per_account_queue_max),
            self._meta_prefix(),
        )
        values = [self._decode(value) for value in result]
        status = values[0] if values else "full"
        returned_task_id = values[1] if len(values) > 1 else ""
        returned_account_key = values[2] if len(values) > 2 else account_key
        try:
            global_jobs = int(values[3]) if len(values) > 3 else self.queue_max
        except (TypeError, ValueError):
            global_jobs = self.queue_max
        try:
            account_jobs = int(values[4]) if len(values) > 4 else 0
        except (TypeError, ValueError):
            account_jobs = 0
        return status, returned_task_id, returned_account_key, global_jobs, account_jobs

    def _cleanup_admission(
        self,
        *,
        connection,
        key_hash: str,
        account_key: str,
        meta_key: str,
        status_key: str,
        account_set_key: str,
    ) -> None:
        try:
            pipe = connection.pipeline()
            pipe.delete(meta_key)
            pipe.delete(status_key)
            pipe.srem(account_set_key, key_hash)
            pipe.srem(self._global_set_key(), key_hash)
            pipe.execute()
        except Exception:
            logger.warning("Redis draft queue admission cleanup failed", exc_info=True)

    def _admitted_count(self, connection) -> int:
        try:
            return int(connection.scard(self._global_set_key()))
        except Exception:
            return 0

    def _incr(self, name: str) -> None:
        try:
            self._get_connection().incr(self._counter_key(name))
        except Exception:
            logger.debug("Redis draft queue counter increment failed", exc_info=True)

    def _counter(self, connection, name: str) -> int:
        raw = connection.get(self._counter_key(name))
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _global_set_key(self) -> str:
        return f"draftq:{self.queue_name}:jobs"

    def _meta_prefix(self) -> str:
        return f"draftq:{self.queue_name}:job:"

    def _meta_key(self, key_hash: str) -> str:
        return f"{self._meta_prefix()}{key_hash}"

    def _account_set_key(self, account_key: str) -> str:
        return f"draftq:{self.queue_name}:account:{self._hash_key(account_key)}"

    def _counter_key(self, name: str) -> str:
        return f"draftq:{self.queue_name}:counter:{name}"

    def _status_key(self, task_id: str) -> str:
        return f"draftq:{self.queue_name}:status:{self._hash_key(task_id)}"

    def _shared_pending_email_key(self, account_id: object, email_id: str) -> str:
        account_key = DraftJobQueue._account_key(account_id)
        return (
            f"draftq:{self.queue_name}:pending:email:"
            f"{self._hash_key(f'{account_key}:{email_id}')}"
        )

    def _shared_pending_id_key(self, draft_id: str) -> str:
        return f"draftq:{self.queue_name}:pending:id:{self._hash_key(draft_id)}"

    @staticmethod
    def _decode_json_dict(value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def _hash_key(value: object) -> str:
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _decode(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


_draft_queue = DraftJobQueue(
    max_workers=_positive_int_env("DRAFT_WORKER_MAX", 16),
    queue_max=_positive_int_env("DRAFT_QUEUE_MAX", 200),
    per_account_max=_positive_int_env("DRAFT_PER_ACCOUNT_MAX", 4),
    per_account_queue_max=_positive_int_env("DRAFT_PER_ACCOUNT_QUEUE_MAX", 50),
    retry_after_seconds=_positive_int_env("DRAFT_QUEUE_RETRY_AFTER_SECONDS", 10),
)
_redis_draft_queue: RedisDraftJobQueue | None = None


def draft_queue_backend() -> str:
    if (
        os.getenv("DRAFT_QUEUE_BACKEND", "").strip().lower() == "redis"
        and get_redis_url()
    ):
        return "redis"
    return "memory"


def _get_redis_draft_queue() -> RedisDraftJobQueue:
    global _redis_draft_queue
    if _redis_draft_queue is None:
        _redis_draft_queue = RedisDraftJobQueue(
            redis_url=get_redis_url(),
            queue_name=os.getenv("DRAFT_QUEUE_NAME", "drafts"),
            queue_max=_positive_int_env("DRAFT_QUEUE_MAX", 1000),
            per_account_queue_max=_positive_int_env("DRAFT_PER_ACCOUNT_QUEUE_MAX", 100),
            retry_after_seconds=_positive_int_env("DRAFT_QUEUE_RETRY_AFTER_SECONDS", 10),
            job_timeout_seconds=_positive_int_env("DRAFT_JOB_TIMEOUT_SECONDS", 120),
            job_ttl_seconds=_positive_int_env("DRAFT_JOB_TTL_SECONDS", 3600),
        )
    return _redis_draft_queue


def enqueue_draft_job(
    *,
    key: str,
    account_id: object,
    email_id: str,
    task_id: str,
    run: Callable[[], None],
    payload: dict[str, Any] | None = None,
) -> DraftJobSubmission:
    if draft_queue_backend() == "redis":
        try:
            return _get_redis_draft_queue().enqueue(
                key=key,
                account_id=account_id,
                email_id=email_id,
                task_id=task_id,
                payload=payload,
            )
        except Exception as exc:
            rejection_reason = _redis_enqueue_failure_reason(exc)
            if _redis_queue_fail_closed():
                queue_max = _positive_int_env("DRAFT_QUEUE_MAX", 1000)
                retry_after_seconds = _positive_int_env("DRAFT_QUEUE_RETRY_AFTER_SECONDS", 10)
                logger.warning(
                    "Redis draft queue unavailable, failing closed reason=%s: %s",
                    rejection_reason,
                    exc,
                )
                return DraftJobSubmission(
                    status="full",
                    task_id=task_id,
                    queue_depth=queue_max,
                    queue_max=queue_max,
                    active_workers=0,
                    active_for_account=0,
                    retry_after_seconds=retry_after_seconds,
                    backend="redis",
                    rejection_reason=rejection_reason,
                )
            logger.warning(
                "Redis draft queue unavailable, falling back to memory queue reason=%s: %s",
                rejection_reason,
                exc,
                exc_info=True,
            )
    return _draft_queue.enqueue(
        key=key,
        account_id=account_id,
        email_id=email_id,
        task_id=task_id,
        run=run,
    )


def get_draft_queue_stats() -> dict[str, int]:
    if draft_queue_backend() == "redis":
        try:
            return _get_redis_draft_queue().stats()
        except Exception as exc:
            logger.warning("Redis draft queue stats unavailable: %s", exc)
    return _draft_queue.stats()


def get_draft_job_status(task_id: str) -> dict[str, Any] | None:
    if draft_queue_backend() != "redis":
        return None
    try:
        return _get_redis_draft_queue().get_status(task_id)
    except Exception as exc:
        logger.warning("Redis draft job status unavailable: %s", exc)
        return None


def store_shared_pending_draft(
    *,
    draft: dict[str, Any],
    account_id: object,
    email_id: str,
    draft_id: str,
) -> None:
    if draft_queue_backend() != "redis":
        return
    try:
        _get_redis_draft_queue().store_shared_pending_draft(
            draft=draft,
            account_id=account_id,
            email_id=email_id,
            draft_id=draft_id,
        )
    except Exception:
        logger.warning("Redis shared pending draft store failed", exc_info=True)


def get_shared_pending_draft_by_email(
    *,
    account_id: object,
    email_id: str,
) -> dict[str, Any] | None:
    if draft_queue_backend() != "redis":
        return None
    try:
        return _get_redis_draft_queue().get_shared_pending_draft_by_email(
            account_id=account_id,
            email_id=email_id,
        )
    except Exception as exc:
        logger.warning("Redis shared pending draft lookup failed: %s", exc)
        return None


def get_shared_pending_draft_by_id(draft_id: str) -> dict[str, Any] | None:
    if draft_queue_backend() != "redis":
        return None
    try:
        return _get_redis_draft_queue().get_shared_pending_draft_by_id(draft_id)
    except Exception as exc:
        logger.warning("Redis shared pending draft lookup failed: %s", exc)
        return None


def delete_shared_pending_draft(
    *,
    draft_id: str,
    account_id: object | None = None,
    email_id: str | None = None,
) -> None:
    if draft_queue_backend() != "redis":
        return
    try:
        _get_redis_draft_queue().delete_shared_pending_draft(
            draft_id=draft_id,
            account_id=account_id,
            email_id=email_id,
        )
    except Exception:
        logger.warning("Redis shared pending draft delete failed", exc_info=True)


def mark_redis_draft_job_started(*, task_id: str) -> None:
    if draft_queue_backend() != "redis":
        return
    _get_redis_draft_queue().mark_started(task_id=task_id)


def release_redis_draft_job(
    *,
    key: str,
    account_id: object,
    task_id: str | None = None,
    failed: bool = False,
    error: str | None = None,
) -> None:
    if draft_queue_backend() != "redis":
        return
    _get_redis_draft_queue().release(
        key=key,
        account_id=account_id,
        task_id=task_id,
        failed=failed,
        error=error,
    )
