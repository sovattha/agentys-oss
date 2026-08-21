#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Point d'entrée pour l'API REST Agentys.

Usage:
    python run_api.py [--port PORT] [--host HOST] [--debug]

Options:
    --port PORT  Port d'écoute (default: $PORT or 5050)
    --host HOST  Host d'écoute (default: 0.0.0.0)
    --debug      Mode debug avec auto-reload
"""

import os
import sys as _sys

# ── Async backend selection for Flask-SocketIO.
#
# Default on all platforms is "threading" — rock solid, reuses the native
# thread pool, and the Windows stdlib (sqlite3, ssl, subprocess) isn't
# monkey-patch-friendly so eventlet/gevent often deadlock on Windows.
#
# In threading mode the Socket.IO client still works perfectly: local clients
# stay on long-polling transport. Prod Linux can opt into eventlet so the cloud
# web app uses a real WebSocket first and only falls back to polling if needed.
#
# Opt-in with AGENTYS_ASYNC_MODE=eventlet on Linux-only deployments where
# eventlet.monkey_patch() is known to behave.
_ASYNC_MODE = (os.environ.get("AGENTYS_ASYNC_MODE") or "threading").strip().lower()
if _ASYNC_MODE == "eventlet":
    try:
        import eventlet  # type: ignore
        eventlet.monkey_patch()
    except Exception as _evlt_exc:  # pragma: no cover — fallback path
        _sys.stderr.write(
            f"[run_api] eventlet monkey_patch failed ({_evlt_exc}); "
            "falling back to threading mode\n"
        )
        _ASYNC_MODE = "threading"
os.environ["AGENTYS_ASYNC_MODE"] = _ASYNC_MODE

import argparse
import logging
import socket as _socket
import tempfile
from dotenv import load_dotenv

# Windows WMI hang fix: Python's `platform` module calls _wmi.exec_query() at
# import time to detect OS info.  If the WMI service is unresponsive (corrupted
# repository, stuck provider, etc.), the query hangs indefinitely, blocking
# every library that imports `platform` (sqlalchemy, sentry, etc.).
# Patching _wmi.exec_query to raise OSError makes `platform` fall back to its
# registry-based codepath, which works without WMI.
if _sys.platform == "win32":
    try:
        import _wmi
        _orig_wmi_exec = _wmi.exec_query

        def _safe_wmi_exec(query):
            import threading
            result = [None]
            error = [None]

            def _run():
                try:
                    result[0] = _orig_wmi_exec(query)
                except Exception as e:
                    error[0] = e

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=3)
            if t.is_alive():
                raise OSError("WMI query timed out")
            if error[0]:
                raise error[0]
            return result[0]

        _wmi.exec_query = _safe_wmi_exec
    except ImportError:
        pass

# Load environment variables FIRST before any app imports
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


_LOAD_TEST_MODE = _env_bool("AGENTYS_LOAD_TEST_MODE")
if _LOAD_TEST_MODE:
    _load_data_dir = os.environ.setdefault(
        "AGENTYS_DATA_DIR",
        os.path.join(tempfile.gettempdir(), "agentys-load-data"),
    )
    os.makedirs(_load_data_dir, exist_ok=True)
    os.environ.setdefault("AGENTYS_DB_PATH", os.path.join(_load_data_dir, "agentys-load.db"))
    os.environ.setdefault("AGENTYS_ENCRYPTION_ENABLED", "false")
    os.environ.setdefault("AGENTYS_MOCK_LLM", "true")
    os.environ.setdefault("AGENTYS_MOCK_EMAIL_PROVIDER", "true")
    os.environ.setdefault("AGENTYS_LOAD_TEST_BYPASS_RATE_LIMIT", "true")
    os.environ.setdefault("BATCH_API_ENABLED", "false")

# Windows dual-stack fix: allow :: to accept both IPv4 and IPv6 connections.
# Windows sets IPV6_V6ONLY=1 by default (unlike Linux), so AF_INET6 sockets
# ignore IPv4. Patch socket.socket to set IPV6_V6ONLY=0 on IPv6 sockets so
# localhost (→ ::1) and 127.0.0.1 both reach Flask.
# Only apply in threading mode — eventlet swaps socket.socket for its own
# coroutine-aware class and subclassing it after monkey-patching is fragile.
if _ASYNC_MODE != "eventlet":
    _orig_socket_cls = _socket.socket

    class _DualStackSocket(_orig_socket_cls):
        def __init__(self, family=_socket.AF_INET, type=_socket.SOCK_STREAM,
                     proto=0, fileno=None):
            super().__init__(family, type, proto, fileno)
            if family == _socket.AF_INET6 and fileno is None:
                try:
                    self.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 0)
                except OSError:
                    pass

    _socket.socket = _DualStackSocket

from app.api import create_app
from app.api.bootstrap import start_background_services, stop_background_services
from app.api.websocket import init_socketio
from app.infrastructure.logging_config import setup_logging

# Configuration du logging
setup_logging()
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Agentys REST API")
    # Railway sets PORT automatically; fallback to API_PORT then 5050
    default_port = int(os.getenv("PORT", os.getenv("API_PORT", 5050)))
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help="Port d'écoute (default: 5050, or $PORT for Railway)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("API_HOST", "0.0.0.0"),
        help="Host d'écoute (default: 0.0.0.0 — all IPv4 interfaces, couvre 127.0.0.1 et localhost)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mode debug avec auto-reload",
    )

    args = parser.parse_args()

    print("""
+---------------------------------------------------------------+
|                     Agentys REST API                          |
+---------------------------------------------------------------+
    """)

    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Debug: {args.debug}")
    print(f"Load test mode: {_LOAD_TEST_MODE}")
    if _LOAD_TEST_MODE:
        print(f"Load test data: {os.environ.get('AGENTYS_DATA_DIR')}")
        print(f"Load test DB: {os.environ.get('AGENTYS_DB_PATH')}")
    print()
    print(f"URL: http://{args.host}:{args.port}")
    print()
    print("Endpoints disponibles:")
    print("  GET  /api/health      - État de santé")
    print("  GET  /api/stats       - Statistiques globales")
    print("  GET  /api/emails      - Liste des emails non lus")
    print("  POST /api/emails/<id>/process - Traiter un email")
    print("  GET  /api/drafts      - Historique des brouillons")
    print("  GET  /api/followups   - Follow-ups en attente")
    print("  GET  /api/learning    - Statistiques learning")
    print("  GET  /api/costs       - Breakdown des coûts")
    print("  GET  /api/sync/status - État de la synchronisation")
    print("  POST /api/sync/trigger- Déclencher une sync manuelle")
    print("  POST /webhooks        - Enregistrer un webhook")
    print()
    print("WebSocket:")
    print("  /daemon               - Namespace pour événements temps réel")
    print()

    app = create_app()
    socketio = init_socketio(app)

    # Démarrage des services de fond — séquence partagée avec le serveur
    # gunicorn de prod (app/api/gunicorn_app.py). Cf. app/api/bootstrap.py.
    services = start_background_services(app)

    print(f"Async mode: {_ASYNC_MODE}")

    # Build kwargs defensively: allow_unsafe_werkzeug is only meaningful in
    # threading mode (eventlet / gevent use their own WSGI servers).
    _run_kwargs: dict = {
        "host": args.host,
        "port": args.port,
        "debug": args.debug,
        "use_reloader": False,  # Disable reloader to preserve in-memory cache
    }
    if _ASYNC_MODE == "threading":
        _run_kwargs["allow_unsafe_werkzeug"] = True

    # Railway / Docker / k8s envoient SIGTERM pour arrêter le container.
    # Sans handler, le default kill brutal interrompt les connexions en cours
    # → 502 chez les clients pendant la rotation deploy. On re-route SIGTERM
    # vers le path de cleanup en levant KeyboardInterrupt dans le main thread
    # (ce qui sort du `socketio.run` et exécute le bloc `except` ci-dessous,
    # qui draine les workers proprement).
    # Validé en prod : commit 6144e121+1, sentinelle WS reste verte après
    # rotation Railway.
    import signal as _signal

    def _handle_sigterm(_signum, _frame):  # pragma: no cover — runtime path
        print("\n[shutdown] SIGTERM reçu — drain en cours...")
        raise KeyboardInterrupt

    _signal.signal(_signal.SIGTERM, _handle_sigterm)

    try:
        socketio.run(app, **_run_kwargs)
    except KeyboardInterrupt:
        stop_background_services(services)


if __name__ == "__main__":
    main()
