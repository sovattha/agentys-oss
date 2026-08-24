# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Railway process dispatcher for web and draft worker services."""

from __future__ import annotations

import os
import subprocess
import sys


WORKER_ROLES = {"draft-worker", "worker", "rq-worker"}


def _service_role() -> str:
    return os.getenv("AGENTYS_SERVICE_ROLE", "web").strip().lower()


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _exec_python(args: list[str]) -> None:
    os.environ.setdefault("AGENTYS_ASYNC_MODE", "threading")
    os.execvp(sys.executable, [sys.executable, *args])


def _exec_process(args: list[str]) -> None:
    os.execvp(args[0], args)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _start_gunicorn() -> None:
    os.environ.setdefault("AGENTYS_ASYNC_MODE", "threading")
    host = os.getenv("API_HOST", "0.0.0.0")
    port = os.getenv("PORT", os.getenv("API_PORT", "5050"))
    threads = str(_positive_int_env("AGENTYS_GUNICORN_THREADS", 256))
    timeout = str(_positive_int_env("AGENTYS_GUNICORN_TIMEOUT", 120))
    graceful_timeout = str(_positive_int_env("AGENTYS_GUNICORN_GRACEFUL_TIMEOUT", 30))
    keepalive = str(_positive_int_env("AGENTYS_GUNICORN_KEEPALIVE", 15))
    backlog = str(_positive_int_env("AGENTYS_GUNICORN_BACKLOG", 4096))
    _exec_process(
        [
            "gunicorn",
            "--workers",
            "1",
            "--worker-class",
            "gthread",
            "--threads",
            threads,
            "--bind",
            f"{host}:{port}",
            "--timeout",
            timeout,
            "--graceful-timeout",
            graceful_timeout,
            "--keep-alive",
            keepalive,
            "--backlog",
            backlog,
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "app.api.gunicorn_app:app",
        ]
    )


def predeploy() -> int:
    if _service_role() in WORKER_ROLES:
        print("[railway] worker role detected; skipping alembic predeploy")
        return 0
    if _env_bool("AGENTYS_LOAD_TEST_MODE"):
        print("[railway] load-test mode detected; skipping alembic predeploy")
        return 0
    return subprocess.call(["alembic", "upgrade", "head"])


def start() -> None:
    if _service_role() in WORKER_ROLES:
        _exec_python(["-m", "app.workers.draft_worker"])
        return
    # 2026-06-13: prod web now boots gunicorn (gthread) like load tests do.
    # Werkzeug had no graceful drain: every Railway deploy (~10/day) cut
    # in-flight requests and flashed the frontend "Connection lost" banner.
    # AGENTYS_WEB_SERVER=werkzeug is the instant-rollback knob (env var
    # change on Railway, no code redeploy).
    if os.getenv("AGENTYS_WEB_SERVER", "").strip().lower() == "werkzeug":
        _exec_python(["run_api.py", "--host", "0.0.0.0"])
        return
    _start_gunicorn()


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    if command == "predeploy":
        return predeploy()
    if command == "start":
        start()
        return 0
    print(f"Usage: {sys.argv[0]} [start|predeploy]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
