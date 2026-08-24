# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Gunicorn WSGI entrypoint — production web server and load tests.

2026-06-13: promoted from load-test-only to the production entrypoint
(scripts/railway_entrypoint.py). Werkzeug (run_api.py) had no graceful drain:
every Railway deploy cut in-flight requests and flashed the frontend
"Connection lost" banner. Gunicorn gthread drains in-flight requests within
--graceful-timeout on SIGTERM; background services are drained via atexit
(the gthread worker exits through sys.exit(0) after the drain, which runs
atexit hooks).
"""

from __future__ import annotations

import atexit
import os
import tempfile

from dotenv import load_dotenv

os.environ.setdefault("AGENTYS_ASYNC_MODE", "threading")
load_dotenv()


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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


_apply_load_test_defaults()

from app.api import create_app  # noqa: E402
from app.api.bootstrap import (  # noqa: E402
    start_background_services,
    stop_background_services,
)
from app.api.websocket import init_socketio  # noqa: E402
from app.infrastructure.logging_config import setup_logging  # noqa: E402

setup_logging()

app = create_app()
socketio = init_socketio(app)

# Same background services as run_api.py (sync, schedulers, workers, warmup).
# start_background_services() is a no-op in load-test mode, preserving the
# historical gunicorn load-test behavior (bare app, no services).
#
# Review F02 — drain best-effort assumé : si le drain dépasse
# --graceful-timeout (30s), gunicorn SIGKILL le worker et atexit ne tourne
# pas (aucun hook ne survit à SIGKILL, worker_exit inclus). Le drain mesuré
# prend <1s à vide et ~15s au pire (bulk jobs en vol). Le seul état qui
# compte est couvert par design : SQLite WAL est crash-safe, et
# start_background_services() refait un checkpoint_wal(source="startup")
# à chaque boot qui répare un WAL non checkpointé.
_services = start_background_services(app)
atexit.register(stop_background_services, _services)

