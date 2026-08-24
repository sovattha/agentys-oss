# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Run RQ workers for draft generation."""

from __future__ import annotations

import os
import signal
import socket
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import Process
from threading import Thread

from dotenv import load_dotenv

from app.infrastructure.logging_config import setup_logging, get_logger
from app.infrastructure.redis_config import get_redis_url


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _select_worker_class(logger):
    """Return the RQ worker class and mode label.

    ``fork`` keeps RQ's default per-job isolation. ``simple`` is available as
    an explicit experiment for I/O-bound jobs, but it also lets deferred
    background work keep running in the worker process.
    """
    mode = os.getenv("DRAFT_RQ_WORKER_MODE", "fork").strip().lower()
    if mode in {"fork", "process", "default"}:
        from rq import Worker

        return Worker, "fork"
    if mode not in {"simple", "in-process", "inprocess", "inline"}:
        logger.warning(
            "Unknown DRAFT_RQ_WORKER_MODE=%s; using fork worker",
            mode,
        )
        from rq import Worker

        return Worker, "fork"

    from rq.worker import SimpleWorker
    return SimpleWorker, "simple"


def _apply_load_test_defaults() -> None:
    if not _env_bool("AGENTYS_LOAD_TEST_MODE"):
        return
    load_data_dir = os.environ.setdefault(
        "AGENTYS_DATA_DIR",
        os.path.join(tempfile.gettempdir(), "agentys-load-data"),
    )
    os.makedirs(load_data_dir, exist_ok=True)
    os.environ.setdefault("AGENTYS_DB_PATH", os.path.join(load_data_dir, "agentys-load.db"))
    os.environ.setdefault("AGENTYS_ENCRYPTION_ENABLED", "false")
    os.environ.setdefault("AGENTYS_MOCK_LLM", "true")
    os.environ.setdefault("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    os.environ.setdefault("AGENTYS_LOAD_TEST_BYPASS_RATE_LIMIT", "true")
    os.environ.setdefault("BATCH_API_ENABLED", "false")


def _start_health_server(logger) -> None:
    port = _positive_int_env("PORT", 0)
    if not port:
        return

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] not in {
                "/api/health",
                "/api/health/strict",
                "/healthz",
            }:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy","service":"draft-worker"}')

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True, name="draft-worker-health")
    thread.start()
    logger.info("Draft worker health server listening on port %s", port)


def _worker_name(index: int) -> str:
    deployment = os.getenv("RAILWAY_DEPLOYMENT_ID", "").strip()
    replica = os.getenv("RAILWAY_REPLICA_ID", "").strip()
    host = os.getenv("HOSTNAME", "").strip() or socket.gethostname()
    identity_parts = [
        part[:12]
        for part in (replica, host, deployment, str(os.getpid()))
        if part
    ]
    identity = "-".join(identity_parts)
    configured = os.getenv("RQ_WORKER_NAME", "").strip()
    if configured:
        return f"{configured}-{identity}-{index}" if identity else f"{configured}-{index}"
    return f"draft-worker-{identity}-{index}" if identity else f"draft-worker-{index}"


def _run_worker(index: int) -> int:
    load_dotenv()
    _apply_load_test_defaults()
    setup_logging()
    logger = get_logger(__name__)
    redis_url = get_redis_url()
    if not redis_url:
        logger.error("REDIS_URL or REDIS_PRIVATE_URL is required for draft worker")
        return 2

    from redis import Redis
    from rq import Queue

    queue_name = os.getenv("DRAFT_QUEUE_NAME", "drafts")
    connection = Redis.from_url(redis_url)
    connection.ping()
    queues = [Queue(queue_name, connection=connection)]
    worker_name = _worker_name(index)
    WorkerClass, worker_mode = _select_worker_class(logger)
    worker = WorkerClass(queues, connection=connection, name=worker_name)
    try:
        from app.application.draft_worker_job import _get_worker_app

        _get_worker_app()
    except Exception:
        logger.warning("Draft worker app warmup failed", exc_info=True)
    logger.info(
        "Starting draft RQ worker queue=%s name=%s mode=%s",
        queue_name,
        worker_name,
        worker_mode,
    )
    worker.work(with_scheduler=True)
    return 0


def main() -> int:
    load_dotenv()
    _apply_load_test_defaults()
    setup_logging()
    logger = get_logger(__name__)
    _start_health_server(logger)
    worker_count = _positive_int_env("DRAFT_RQ_WORKERS", 1)
    if worker_count <= 1:
        return _run_worker(1)

    processes: list[Process] = []
    stopping = False

    def _stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        for process in processes:
            if process.is_alive():
                process.terminate()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    for index in range(worker_count):
        process = Process(target=_run_worker, args=(index + 1,), daemon=False)
        process.start()
        processes.append(process)
    logger.info("Started %s draft RQ worker processes", worker_count)

    while not stopping:
        for process in processes:
            if process.exitcode not in (None, 0):
                logger.error("Draft worker process exited with code %s", process.exitcode)
                _stop(signal.SIGTERM, None)
                return process.exitcode or 1
        if all(process.exitcode == 0 for process in processes):
            return 0
        time.sleep(1)
    for process in processes:
        process.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
