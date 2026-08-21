# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Flask application factory pour l'API REST Agentys.
"""

import logging
import os
import re as _re_module

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from flask import Flask, request
from flask_cors import CORS
from flask_compress import Compress
from flasgger import Swagger
from sentry_sdk.integrations.flask import FlaskIntegration
from werkzeug.middleware.proxy_fix import ProxyFix


# CASA V7.1 / V8.3 (#210) — module-level secret patterns so both the LogRecord
# factory (installed in create_app) AND Sentry's `before_send` consume the same
# definition. Adding a pattern in one place protects all log/Sentry surfaces.
_SECRET_PATTERNS = [
    # ?token=... / &token=... in URLs (magic links)
    _re_module.compile(r"([?&]token=)[^\s&\"'<>]+", _re_module.IGNORECASE),
    # OAuth ?code=... / &code=... (authorization codes — single-use but still
    # sensitive in logs because they grant tokens)
    _re_module.compile(r"([?&]code=)[^\s&\"'<>]{10,}", _re_module.IGNORECASE),
    # access_token / refresh_token / id_token assignments (OAuth bodies)
    _re_module.compile(r"((?:access|refresh|id)_token['\"]?\s*[:=]\s*['\"]?)[^\s,\"'}\)]+", _re_module.IGNORECASE),
    # client_secret, api_key, secret_key assignments
    _re_module.compile(r"((?:client_secret|api_key|secret_key|private_key)['\"]?\s*[:=]\s*['\"]?)[^\s,\"'}\)]+", _re_module.IGNORECASE),
    # Authorization: Bearer <jwt> (≥16 chars after Bearer)
    _re_module.compile(r"(Bearer\s+)[A-Za-z0-9._\-+/=]{16,}", _re_module.IGNORECASE),
    # Bare JWT (3 base64url segments). The bare form often appears in upstream
    # error responses or debug dumps without an explicit "Bearer " prefix.
    # Wrapped in a non-content prefix group "()" so `\1[REDACTED]` in
    # `_redact_text` substitutes successfully (sub validates the template
    # eagerly; a missing group raises `re.error: invalid group reference 1`
    # on every log line, blocking the entire LogRecord factory).
    _re_module.compile(r"()\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b"),
    # password=... assignments (only when a value follows; literal "password"
    # word in prose is left alone)
    _re_module.compile(r"(password['\"]?\s*[:=]\s*['\"]?)[^\s,\"'}\)]+", _re_module.IGNORECASE),
    # API key prefixes: sk-/sk_/AIza/ghp_/xoxb-/re_ followed by ≥12 chars
    _re_module.compile(r"\b((?:sk[-_]|AIza|ghp_|xoxb-|re_)[A-Za-z0-9_\-]{12})[A-Za-z0-9_\-]+"),
]

# Email PII redaction — preserves the domain (useful for triage / multi-tenant
# debugging) while masking the local-part. `john.doe@example.com` →
# `j***@example.com`. Run as a separate pass because we keep the @domain
# (the prefix-only redaction pattern can't express that).
_EMAIL_PII_RE = _re_module.compile(
    r"\b([A-Za-z0-9])[A-Za-z0-9._%+\-]*@([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.[A-Za-z]{2,})\b"
)

_EMAIL_CONTENT_KEYS = {
    "body",
    "body_text",
    "body_html",
    "snippet",
    "email_body",
    "conversation_history",
    "draft_v1",
    "draft_final",
    "critique",
    "generation_prompt",
    "user_edits",
    "feedback_notes",
}

_EMAIL_CONTENT_KEY_RE = "|".join(_re_module.escape(k) for k in sorted(_EMAIL_CONTENT_KEYS, key=len, reverse=True))
_EMAIL_CONTENT_KV_QUOTED_RE = _re_module.compile(
    rf"(?P<prefix>(?:['\"])?(?:{_EMAIL_CONTENT_KEY_RE})(?:['\"])?\s*[:=]\s*)"
    r"(?P<quote>['\"])(?P<value>[^\r\n]{12,}?)(?P=quote)",
    _re_module.IGNORECASE,
)
_EMAIL_CONTENT_KV_INLINE_RE = _re_module.compile(
    rf"(?P<prefix>\b(?:{_EMAIL_CONTENT_KEY_RE})\s*=\s*)"
    r"(?P<value>[^\r\n,;]{32,})",
    _re_module.IGNORECASE,
)
_EMAIL_CONTENT_HEADER_RE = _re_module.compile(
    rf"(?P<prefix>\b(?:{_EMAIL_CONTENT_KEY_RE})\s*:\s*)"
    r"(?P<value>[^\r\n]{32,})",
    _re_module.IGNORECASE,
)
_EMAIL_CONTENT_REDACTION = "[EMAIL_CONTENT_REDACTED]"


def _redact_email_content_values(text: str) -> str:
    """Redact known email-content fields embedded in log/Sentry strings."""
    if not isinstance(text, str) or not text:
        return text

    def _quoted(match: _re_module.Match) -> str:
        return f"{match.group('prefix')}{match.group('quote')}{_EMAIL_CONTENT_REDACTION}{match.group('quote')}"

    def _inline(match: _re_module.Match) -> str:
        return f"{match.group('prefix')}{_EMAIL_CONTENT_REDACTION}"

    out = _EMAIL_CONTENT_KV_QUOTED_RE.sub(_quoted, text)
    out = _EMAIL_CONTENT_KV_INLINE_RE.sub(_inline, out)
    out = _EMAIL_CONTENT_HEADER_RE.sub(_inline, out)
    return out


def _redact_text(text: str) -> str:
    """Apply all secret patterns + email PII mask to a free-text string.

    Reused by `_sentry_before_send` (event["exception"]["values"][*]["value"])
    and the LogRecord factory in `create_app`. CASA V7.1+V8.3.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for _p in _SECRET_PATTERNS:
        out = _p.sub(r"\1[REDACTED]", out)
    out = _EMAIL_PII_RE.sub(r"\1***@\2", out)
    out = _redact_email_content_values(out)
    return out


def _redact_payload(value, key: str = ""):
    """Recursively scrub Sentry payloads, including structured email fields."""
    key_l = key.lower() if isinstance(key, str) else ""
    if key_l in _EMAIL_CONTENT_KEYS:
        return _EMAIL_CONTENT_REDACTION
    if isinstance(value, dict):
        for k in list(value.keys()):
            value[k] = _redact_payload(value[k], str(k))
        return value
    if isinstance(value, list):
        for idx, item in enumerate(value):
            value[idx] = _redact_payload(item, key)
        return value
    if isinstance(value, tuple):
        return tuple(_redact_payload(item, key) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value

# Audit 2026-04-25 (sub-report 05 F-HIGH-2): centralized prod detection so
# guards no longer drift between files (oauth.py / auth.py / oauth_ads.py).
from app.api._auth_helpers import is_production as _is_production_env

# Sentry must be initialized before Flask app creation
# Detect test environment: pytest sets PYTEST_CURRENT_TEST automatically
import sys as _sys
_is_testing = (
    "PYTEST_CURRENT_TEST" in os.environ
    or os.environ.get("PYTEST_RUNNING") == "1"
    or any("pytest" in arg for arg in _sys.argv)
)


def _sentry_before_send(event, hint):
    """Filter out noisy errors that are not actionable bugs.

    CASA V7.1+V8.3 (#210): also redacts secrets and email PII from exception
    values before Sentry persists the event. Captured via FlaskIntegration the
    record never goes through our LogRecord factory, so this is the only place
    to scrub the exception payload.
    """
    # Double-check: ignore events from pytest runs
    if _is_testing or any("pytest" in arg for arg in _sys.argv):
        return None

    # Check all possible message locations in a Sentry event
    logentry = event.get("logentry") or {}
    parts = [
        logentry.get("message", ""),
        # params can hold the formatted traceback when werkzeug logs "Error on request:\n%s"
        str(logentry.get("params") or ""),
        str(event.get("message") or ""),
    ]
    # Also check exception values
    for entry in (event.get("exception") or {}).get("values", []):
        parts.append(entry.get("value") or "")
    # Also check the raw hint exception (catches cases before serialization)
    exc_info = (hint or {}).get("exc_info")
    if exc_info and exc_info[1]:
        parts.append(str(exc_info[1]))

    message = " ".join(parts)

    # Werkzeug: client disconnected before response (not a bug)
    if "write() before start_response" in message:
        return None
    # Windows: client abruptly closed WebSocket (tab closed, refresh, etc.) — not a bug
    if "ConnectionAbortedError" in message or "WinError 10053" in message:
        return None
    # IMAP auth failure (expired/invalid credentials) — expected, user must re-auth
    if "Authentification IMAP requise" in message or "Reconnexion IMAP échouée" in message:
        return None
    # Transient network retries exhausted during email fetch — expected on flaky connections
    if "All " in message and "attempts failed for _fetch_emails" in message:
        return None
    # python-socketio: stale session id after client reconnect (tab closed, sleep/resume) — benign race
    # Raised by engineio.base_server._get_socket when sid is no longer in self.sockets
    if "Session is disconnected" in message:
        return None

    # CASA V7.1+V8.3: redact secrets / email PII before persisting.
    try:
        if event.get("logentry"):
            if isinstance(event["logentry"].get("message"), str):
                event["logentry"]["message"] = _redact_text(event["logentry"]["message"])
            if event["logentry"].get("params"):
                _params = event["logentry"]["params"]
                if isinstance(_params, (list, tuple)):
                    event["logentry"]["params"] = type(_params)(
                        _redact_text(str(p)) for p in _params
                    )
                elif isinstance(_params, str):
                    event["logentry"]["params"] = _redact_text(_params)
        if isinstance(event.get("message"), str):
            event["message"] = _redact_text(event["message"])
        for entry in (event.get("exception") or {}).get("values", []):
            if isinstance(entry.get("value"), str):
                entry["value"] = _redact_text(entry["value"])
        # Request body is rarely useful and frequently leaks. Drop it entirely.
        if "request" in event and isinstance(event["request"], dict):
            event["request"].pop("data", None)
            event["request"].pop("cookies", None)
        event = _redact_payload(event)
    except Exception:
        # Never block Sentry on redactor failures — return the original event.
        pass
    return event


# Disable Sentry entirely during tests — pass empty DSN.
# Audit 2026-04-25 (HIGH-Backend-... sub-report 05 F-HIGH-1): default to "" so
# the Agentys Sentry org isn't pinged from forked deployments. Operators set
# SENTRY_DSN explicitly in their own Railway/Hetzner env.
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
sentry_sdk.init(
    dsn="" if _is_testing else _SENTRY_DSN,
    traces_sample_rate=0.0 if _is_testing else 0.2,
    profiles_sample_rate=0.0 if _is_testing else 0.1,
    environment="testing" if _is_testing else os.environ.get("FLASK_ENV", "production"),
    before_send=_sentry_before_send,
    # SECURITY (audit 2026-05-29, CWE-532): scrub performance transactions too, not
    # just error events — 20%-sampled traces can otherwise carry token-bearing
    # request URLs/query params to Sentry un-redacted.
    before_send_transaction=_sentry_before_send,
    send_default_pii=False,
    # Disable auto-enabling integrations: Sentry 2.x probes every installed package
    # to auto-detect frameworks.  On Windows, importing aiohttp and sqlalchemy hangs
    # indefinitely (C-extension .pyd loading issue), blocking the entire startup.
    # We explicitly list only the integrations we need.
    auto_enabling_integrations=False,
    integrations=[
        FlaskIntegration(),
        # Disable the logging integration: it patches Python's logging with a C extension
        # that segfaults under concurrent thread load (SSL errors + SQLite locks firing
        # simultaneously from background threads).
        LoggingIntegration(level=None, event_level=None),
    ],
)

from .routes import api_bp
from .push_notifications import push_bp
from .gmail_push import gmail_push_bp
from .wizard import wizard_bp
from .marketplace import marketplace_bp
from .fine_tuning import fine_tuning_bp
from .mobile import mobile_bp
from .realtime_edit import realtime_edit_bp
from .email_templates import email_templates_bp
from .accounts import accounts_bp
from .oauth import oauth_bp
from .settings import settings_bp
from .quicksteps import quicksteps_bp
from .discord import discord_bp
from .telegram import telegram_bp
from .labels import labels_bp
from .sync import sync_bp
from .connectivity import connectivity_bp
from .search import search_alias_bp, search_bp
from .folders import folders_bp
from .calendar import calendar_bp
from .calendar_routes import calendar_routes_bp
from .snippets import snippets_bp
from .signatures import signatures_bp
from .account_actions import account_actions_bp
from .onboarding import onboarding_bp
from .contact_groups import contact_groups_bp
from .auth import auth_bp
from .billing import billing_bp
from .ambassador import ambassador_bp
from .specialties import specialties_bp
from .admin import admin_bp
from .routes_selftest import selftest_bp
from .routes_reset import reset_bp
from app.db import init_db
from .agent_marketplace import agent_marketplace_bp
from .knowledge import knowledge_bp
from .style_inference import style_inference_bp
from .tts import tts_bp
from .scheduled_emails import scheduled_emails_bp
from .routes_stt import stt_bp
from .voice_session import voice_session_bp
from .privacy import privacy_bp
from .auth import apply_auth_guard

logger = logging.getLogger(__name__)


def create_app(config: dict = None) -> Flask:
    """
    Crée et configure l'application Flask.

    Args:
        config: Configuration optionnelle à injecter.

    Returns:
        Flask app configurée.
    """
    app = Flask(__name__)

    # Configuration par défaut
    app.config.update({
        "JSON_SORT_KEYS": False,
        "JSON_AS_ASCII": False,
    })

    # Configuration personnalisée
    if config:
        app.config.update(config)

    # #551 follow-up: process-wide outbound API usage probes. Installed early
    # so SDKs created during boot (Gmail/Outlook/Anthropic/etc.) are covered.
    try:
        from app.infrastructure.api_usage_probe import install_api_usage_probes

        install_api_usage_probes()
    except Exception as exc:
        logger.debug("API usage probes skipped: %s", exc)

    # Audit 2026-04-25 (HIGH-Backend-4 / sub-report 01 HIGH-04): trust the
    # Railway reverse-proxy headers so request.remote_addr reflects the real
    # client IP. Without this, every per-IP rate limit shares one bucket
    # across all users (the proxy IP).
    #
    # x_for=1: Trust exactly one X-Forwarded-For hop (Railway adds one).
    # If we ever change the deploy topology to add another proxy hop,
    # bump this to 2 — but never blindly trust X-Forwarded-For with
    # x_for=N for unbounded N (spoofing risk).
    # NB: ProxyFix is applied AFTER the method-override shim below so it stays
    # the OUTERMOST WSGI layer (X-Forwarded-* normalized first; security test
    # asserts isinstance(app.wsgi_app, ProxyFix)).

    # ── HTTP method-override shim (2026-06-23) ──
    # Some embedded-webview HTTP stacks and endpoint-security/AV software
    # silently drop non-GET/POST methods, so PATCH/PUT/DELETE never reach the
    # server (the client sees a network error → "Enregistrement échoué" while
    # cached GET reads still render). The frontend retries such a request as a
    # POST carrying `X-HTTP-Method-Override: PATCH|PUT|DELETE`; we rewrite
    # REQUEST_METHOD here — BEFORE Flask's URL-map matching — so the original
    # method-scoped route runs unchanged. Strictly additive: only a POST with a
    # whitelisted override header is touched; everything else passes verbatim.
    _OVERRIDE_METHODS = frozenset({"PATCH", "PUT", "DELETE"})

    def _method_override_middleware(wsgi_app):
        def _wrapped(environ, start_response):
            if environ.get("REQUEST_METHOD", "").upper() == "POST":
                override = environ.get("HTTP_X_HTTP_METHOD_OVERRIDE", "").strip().upper()
                if override in _OVERRIDE_METHODS:
                    environ["REQUEST_METHOD"] = override
            return wsgi_app(environ, start_response)

        return _wrapped

    app.wsgi_app = _method_override_middleware(app.wsgi_app)
    # ProxyFix wraps last → outermost layer (see note at the x_for comment above).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Session cookie configuration for cross-domain OAuth (Issue #293) ──
    # When the frontend and API are on different domains (Vercel + Railway),
    # SESSION_COOKIE_DOMAIN must match the parent domain so the session cookie
    # set during the OAuth callback (on api.agentys.io) is also sent when the
    # browser follows the redirect back to app.agentys.io.
    # Chrome Enhanced Safe Browsing blocks cross-domain cookies by default.
    _session_domain = os.environ.get("SESSION_COOKIE_DOMAIN")
    if _session_domain:
        app.config["SESSION_COOKIE_DOMAIN"] = _session_domain
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get(
        "SESSION_COOKIE_SAMESITE", "Lax"
    )
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
        "SESSION_COOKIE_SECURE", "False"
    ).lower() in ("true", "1", "yes")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    _server_name = os.environ.get("SERVER_NAME")
    if _server_name:
        app.config["SERVER_NAME"] = _server_name

    # CORS pour permettre les appels cross-origin
    # En production, configurer API_CORS_ORIGINS avec les origines autorisées
    # Defaults include the prod web origins so that a missing
    # API_CORS_ORIGINS env var on Railway ne bloque pas silencieusement
    # tout le frontend (symptôme constaté : onboarding figé à 0% avec
    # "No 'Access-Control-Allow-Origin' header" sur /api/onboarding/status).
    cors_origins = os.environ.get(
        "API_CORS_ORIGINS",
        "http://127.0.0.1:5050,http://localhost:5050,http://127.0.0.1:1420,http://localhost:1420,http://[::1]:1420,http://localhost:5173,http://localhost:5174,tauri://localhost,https://tauri.localhost,https://app.agentys.io,https://agentys.io,https://www.agentys.io"
    ).split(",")
    # Strip whitespace from origins
    cors_origins = [origin.strip() for origin in cors_origins if origin.strip()]
    # Audit 2026-04-25 (sub-report 01 LOW-04): reject the wildcard when we
    # also intend to send Access-Control-Allow-Credentials: true. The CORS
    # spec forbids that combination — chrome/firefox will block but, more
    # importantly, the wildcard reflection of Origin into ACAO with
    # credentials enabled is a credential-leak setup. Fail loud at boot.
    if "*" in cors_origins:
        raise RuntimeError(
            "API_CORS_ORIGINS contains '*' but supports_credentials=True is "
            "configured. The CORS spec forbids this combo (credential leak). "
            "Replace '*' with an explicit origin allow-list."
        )
    # CORS: Use configured origins (env API_CORS_ORIGINS or defaults above).
    # allow_headers DOIT inclure X-Account-Id (envoyé par le frontend pour
    # l'isolation multi-compte — voir services/authToken.ts). Sans ça,
    # Flask-CORS répond au preflight sans X-Account-Id et le browser bloque
    # toutes les requêtes API.
    CORS(
        app,
        resources={r"/*": {"origins": cors_origins, "supports_credentials": True}},
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Account-Id", "X-Admin-Token", "X-Admin-Actor", "X-HTTP-Method-Override"],
        # Miroir de add_cors_and_security_headers ci-dessous, qui prime sur
        # flask-cors (il pose Allow-Origin en premier, flask-cors se retire) —
        # garder les deux listes synchronisées (review F7).
        expose_headers=["Content-Type", "Authorization", "X-Failed-Attachments"],
    )

    # Enable gzip compression for API responses
    app.config["COMPRESS_ALGORITHM"] = "gzip"
    app.config["COMPRESS_LEVEL"] = 6  # Balance between speed and compression
    app.config["COMPRESS_MIN_SIZE"] = 2048  # Only compress responses > 2KB (avoid CPU overhead on small payloads)
    Compress(app)

    # Audit 2026-05-11 P1: werkzeug.MemoryError on rfile.read(10MB) burst
    # — the dev server happily accepted oversized POSTs until the OS
    # process ran out of memory. Cap request body size; legitimate
    # attachment uploads stream through a different path and still fit.
    app.config.setdefault("MAX_CONTENT_LENGTH", 25 * 1024 * 1024)  # 25 MB

    # Configuration Swagger/OpenAPI
    # Security (audit 2026-04-25 HIGH-05 F-HIGH-3): use the central
    # is_production() helper which now also honors RAILWAY_ENVIRONMENT_NAME.
    # Previous detection missed the canonical Railway var, leaving Swagger
    # UI exposed at /api/docs/ in prod whenever FLASK_ENV/ENVIRONMENT were
    # absent from the deploy env.
    is_production = _is_production_env()
    enable_swagger_ui = not is_production

    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/api/apispec.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": enable_swagger_ui,
        "specs_route": "/api/docs/"
    }

    swagger_template = {
        "openapi": "3.0.3",
        "info": {
            "title": "Agentys API",
            "description": "API REST pour le pipeline multi-agents de réponses emails automatiques",
            "version": "1.0.0",
            "contact": {"name": "Agentys Team"}
        },
        "servers": [{"url": "/api", "description": "API principale"}]
    }

    Swagger(app, config=swagger_config, template=swagger_template)

    if is_production:
        logger.info("Swagger UI disabled in production mode")
        # Gate the raw spec endpoint too — swagger_ui=False hides the UI but
        # Flasgger still registers /api/apispec.json which exposes all 400+
        # route names, params, and auth schemes to unauthenticated callers.
        @app.before_request
        def _block_apispec_in_prod():
            if request.path == "/api/apispec.json":
                from flask import abort
                abort(404)

    # Global CORS handler for all routes (Flask-SocketIO bypasses Flask-CORS)
    @app.after_request
    def add_cors_and_security_headers(response):
        origin = request.headers.get("Origin", "")
        allowed_origins = cors_origins
        # Audit 2026-04-25 (sub-report 01 LOW-04): the boot guard above
        # rejects "*"; this branch only matches explicit origins.
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Account-Id, X-Admin-Token, X-Admin-Actor, X-HTTP-Method-Override"
            # Sans exposition explicite, le browser cache les headers custom
            # aux appels fetch() cross-origin (Vite 1420 → API 5050) — le
            # manifeste d'échecs partiels du download-all serait invisible.
            response.headers["Access-Control-Expose-Headers"] = "Content-Type, Authorization, X-Failed-Attachments"
            response.headers["Access-Control-Max-Age"] = "600"

        # CASA report 2026-04-30 (CWE-204 Proxy Disclosure): mask infra
        # fingerprint. Werkzeug/gunicorn would otherwise leak its banner
        # (`Werkzeug/3.x Python/3.13`) and Railway's edge proxy adds
        # `Server: railway-edge`. Override with a generic value at the
        # origin — Railway *may* re-write on egress but our origin no
        # longer leaks. Drop X-Powered-By (some middlewares set it).
        response.headers["Server"] = "Agentys"
        response.headers.pop("X-Powered-By", None)

        # Security headers (applied to ALL responses)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CASA V14.4: HSTS, CSP, Permissions-Policy
        # Backend is JSON-API + OAuth redirects only (no HTML rendering — see
        # oauth.py: every callback returns redirect()). CSP can be strict:
        # default-src 'none' blocks everything, base-uri 'none' kills <base>
        # injection, frame-ancestors 'none' is XFO-DENY parity.
        # CASA V14.4 — `preload` required for HSTS preload list submission
        # (matches frontend `vercel.json`). Without it, securityheaders.com
        # caps the score at A and CASA scanners flag this as a configuration
        # gap. `max-age=31536000` (1 year) is the minimum for preload eligibility.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
            "magnetometer=(), gyroscope=(), accelerometer=(), interest-cohort=()"
        )

        # CASA report 2026-04-30 (CWE-524 Storable Content / CWE-525 Cache-Control
        # missing): backend is JSON-API + OAuth redirects only — zero static
        # assets that would benefit from caching. Apply no-cache to ALL
        # responses (not just /api/*) so the index `/`, error pages, and any
        # auxiliary route (e.g. /robots.txt 404) never get stored by shared
        # proxies. `private` blocks shared/proxy caches in addition to the
        # browser's own cache; `Expires: 0` and `Pragma: no-cache` keep
        # HTTP/1.0 caches honest.
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, private, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response

    # CASA report 2026-04-30 (CWE-204 Proxy Disclosure): hard-block
    # fingerprintable methods at the application boundary. ZAP and similar
    # scanners use TRACE/TRACK to detect XST-vulnerable proxies and to
    # enumerate the upstream stack via reflected headers. CONNECT is for
    # HTTPS tunneling and never legitimate on a JSON-API backend. Returning
    # 405 with a fixed Allow header keeps the response shape uniform across
    # routes (no per-route enumeration leakage).
    _BLOCKED_METHODS = ("TRACE", "TRACK", "CONNECT")
    _ALLOW_HEADER = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    @app.before_request
    def _block_disclosure_methods():
        if request.method in _BLOCKED_METHODS:
            return ("Method Not Allowed", 405, {"Allow": _ALLOW_HEADER})

    # Handle preflight OPTIONS requests
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            origin = request.headers.get("Origin", "")
            # Audit 2026-04-25: explicit origin only (no wildcard).
            if origin in cors_origins:
                response = app.make_default_options_response()
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Account-Id, X-Admin-Token, X-Admin-Actor, X-HTTP-Method-Override"
                # Cache preflight 10 min. Sans ça chaque requête API déclenche
                # un OPTIONS — pendant une rotation Railway (~15-30s), un burst
                # de preflights tombe sur l'edge proxy et prend 502/CORS fails,
                # alors que le deploy précédent fonctionnait parfaitement.
                response.headers["Access-Control-Max-Age"] = "600"
                return response
            # CASA report 2026-04-30 (CWE-204): non-CORS OPTIONS probes leak
            # per-route method lists via Werkzeug's auto-generated `Allow:`
            # header (e.g. `Allow: HEAD, OPTIONS, GET`). Reject with a fixed
            # Allow string so scanners can't fingerprint specific routes.
            return ("Method Not Allowed", 405, {"Allow": _ALLOW_HEADER})

    # ── User activity tracker ──
    # Lets the background sync service defer its cycle when a user request
    # has just been handled, so heavy multi-account polling doesn't compete
    # with user-facing endpoints (transcribe, compose, refine).
    @app.before_request
    def _record_user_activity():
        # Skip health checks (warmup pings shouldn't count as user activity)
        # and CORS preflights (they're not real interactions).
        if request.method == "OPTIONS":
            return
        if request.path in ("/api/health", "/api/health/deep"):
            return
        try:
            from app.services.user_activity import record_activity
            record_activity()
        except Exception:
            pass

    # ── Sentry context enrichment ──
    # Tag each request with route/folder context so that crashes (especially
    # the nightly 2026-04-11 Flask-crash-on-Archives) surface with enough
    # breadcrumbs to diagnose. No PII added — only path + folder + method.
    @app.before_request
    def _tag_sentry_scope():
        try:
            import sentry_sdk as _sentry
            scope = _sentry.get_current_scope()
            if scope is None:
                return
            scope.set_tag("http.method", request.method)
            scope.set_tag("http.path", request.path)
            folder = request.args.get("folder")
            if folder:
                scope.set_tag("email.folder", folder)
                # Extra flag: archives is the crash-prone code path
                if folder == "archived":
                    scope.set_tag("risk.archives", "true")
        except Exception:
            # Never let Sentry instrumentation break a request
            pass

    # ── Security: Apply auth guard BEFORE registration ──
    # routes.py (api_bp) already has its own before_request auth guard.
    # snippets_bp uses @require_auth on each route.
    # admin_bp uses @require_admin on each route.
    # auth_bp is an auth endpoint itself (magic link, dev login) — public by design.
    # oauth_bp is now guarded with selective public_endpoints (cf. ISO-01) —
    # callbacks/PKCE remain reachable, token endpoints require Bearer.
    _guarded_blueprints = [
        push_bp, wizard_bp, marketplace_bp, fine_tuning_bp,
        mobile_bp, realtime_edit_bp, email_templates_bp, accounts_bp,
        signatures_bp,
        settings_bp, quicksteps_bp, discord_bp, telegram_bp, sync_bp,
        connectivity_bp, search_bp, search_alias_bp, folders_bp, calendar_bp,
        calendar_routes_bp, account_actions_bp, onboarding_bp, contact_groups_bp,
        specialties_bp, agent_marketplace_bp, knowledge_bp,
        style_inference_bp, tts_bp, stt_bp,
        # ISO C-2 (audit security.md, issue #522): scheduled_emails_bp routes
        # (POST /api/emails/schedule, GET /api/emails/scheduled, DELETE/PATCH
        # /api/emails/scheduled/<id>) were reachable without a Bearer and fell
        # through to the singleton account — letting a remote attacker enqueue,
        # list, hijack and cancel outbound sends on the singleton's identity.
        scheduled_emails_bp,
    ]
    for bp in _guarded_blueprints:
        apply_auth_guard(bp)
    # Privacy lifecycle is protected except the legal-consent receipt captured
    # before the OAuth redirect. Without this public endpoint, the web app
    # cannot record explicit consent until after it has already started OAuth.
    apply_auth_guard(privacy_bp, public_endpoints=frozenset([
        "privacy.record_legal_consent",
    ]))
    # gmail_push: the /api/gmail/push webhook is authenticated by the Pub/Sub
    # OIDC token (verified inside the handler). watch start/stop/renew remain
    # behind the standard auth guard so they require a Bearer like every other
    # admin endpoint.
    apply_auth_guard(gmail_push_bp, public_endpoints=frozenset([
        "gmail_push.gmail_push",
    ]))
    # OAuth: the /api/oauth/* endpoints power the OAuth dance, so several MUST
    # remain reachable without a Bearer (callbacks from Google/Microsoft, the
    # public client config, the PKCE/session ferries the popup uses to bridge
    # state to the parent window). Token-bearing endpoints (status/refresh/
    # access) ARE protected — they additionally enforce an ownership check
    # inside the handler (cf. ISO-01 audit fix).
    apply_auth_guard(oauth_bp, public_endpoints=frozenset([
        "oauth.get_oauth_config",
        "oauth.gmail_oauth_callback",
        "oauth.gmail_oauth_complete",
        "oauth.outlook_oauth_callback",
        "oauth.complete_outlook_oauth",
        # Audit 2026-04-25 (HIGH-Backend-5 / sub-report 01 HIGH-05):
        # store_code_verifier was made non-public to prevent unauth callers
        # from filling the on-disk PKCE store. That assumption ("PKCE happens
        # after login") only holds for the webapp — on mobile, OAuth IS the
        # initial login, no JWT exists yet. Re-exposing it here; abuse is
        # bounded by the FIFO dict cap (_OAUTH_PENDING_MAX in oauth.py)
        # which evicts oldest entries above 10k pending verifiers.
        "oauth.store_code_verifier",
        "oauth.get_code_verifier",
        "oauth.store_oauth_session",
        "oauth.poll_oauth_session",
    ]))
    # Labels:
    # - Read-only label TAXONOMY endpoints stay public (the list of
    #   "Action / Waiting / FYI / Noise / VIP / custom-label" is not
    #   user-secret).
    # - Endpoints that read PER-EMAIL data are now guarded (ISO-07 / ISO-08
    #   audit fix): they previously let an unauthenticated remote caller
    #   guess email_ids and pull another user's labels / VIP-tagged email
    #   list.
    apply_auth_guard(labels_bp, public_endpoints=frozenset([
        "labels.list_labels", "labels.get_label", "labels.list_rules",
        "labels.get_rules_markdown", "labels.list_vip_senders",
        "labels.classify_all_progress",
    ]))
    apply_auth_guard(billing_bp, public_endpoints=frozenset([
        "billing.stripe_webhook",
    ]))
    # Routes admin protégées par require_admin_or_token (X-Admin-Token serveur-à-
    # serveur sans JWT) → exemptées du guard JWT-user, comme le webhook Stripe.
    apply_auth_guard(ambassador_bp, public_endpoints=frozenset([
        "ambassador.admin_commissions",
        "ambassador.admin_mark_paid",
    ]))

    # Enregistrer les blueprints
    app.register_blueprint(api_bp, url_prefix="/api")
    # webhooks_bp removed 2026-04-25 (audit P0-5 / sub-report 01 CRIT-01).
    # The blueprint exposed an outbound-fetch SSRF chain via /test, had zero
    # frontend/mobile/ai_team callers (verified by grep), and the admin gate
    # added during the audit was a stop-gap. Deletion is the cleaner fix.
    # Internal observability probes (see routes_selftest.py) — off-box
    # cron hits /api/_internal/ws-selftest to detect #290-class regressions.
    app.register_blueprint(selftest_bp, url_prefix="/api/_internal")
    app.register_blueprint(push_bp, url_prefix="/push")
    # gmail_push owns its own URL prefixes (/api/gmail/push, /api/gmail/watch/*)
    app.register_blueprint(gmail_push_bp)
    app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
    app.register_blueprint(marketplace_bp, url_prefix="/api/marketplace")
    app.register_blueprint(fine_tuning_bp)
    app.register_blueprint(mobile_bp, url_prefix="/api/mobile")
    app.register_blueprint(realtime_edit_bp, url_prefix="/api/realtime-edit")
    app.register_blueprint(email_templates_bp, url_prefix="/api")
    app.register_blueprint(accounts_bp, url_prefix="/api/accounts")
    app.register_blueprint(signatures_bp, url_prefix="/api/accounts")
    app.register_blueprint(oauth_bp, url_prefix="/api/oauth")
    app.register_blueprint(settings_bp, url_prefix="/api")
    app.register_blueprint(quicksteps_bp, url_prefix="/api")
    app.register_blueprint(discord_bp, url_prefix="/api/discord")
    app.register_blueprint(telegram_bp, url_prefix="/api/telegram")
    app.register_blueprint(labels_bp, url_prefix="/api/labels")
    app.register_blueprint(folders_bp, url_prefix="/api/folders")
    app.register_blueprint(calendar_bp, url_prefix="/api/calendar")
    app.register_blueprint(calendar_routes_bp, url_prefix="/api/calendar")
    app.register_blueprint(snippets_bp)
    app.register_blueprint(account_actions_bp, url_prefix="/api")
    app.register_blueprint(sync_bp)
    app.register_blueprint(connectivity_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(search_alias_bp)
    app.register_blueprint(onboarding_bp, url_prefix="/api/onboarding")
    app.register_blueprint(contact_groups_bp)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(billing_bp, url_prefix="/api/billing")
    app.register_blueprint(ambassador_bp, url_prefix="/api")
    app.register_blueprint(specialties_bp, url_prefix="/api")
    app.register_blueprint(agent_marketplace_bp, url_prefix="/api/agent-marketplace")
    app.register_blueprint(knowledge_bp, url_prefix="/api/knowledge")
    app.register_blueprint(style_inference_bp, url_prefix="/api/style")
    app.register_blueprint(tts_bp, url_prefix="/api/tts")
    app.register_blueprint(stt_bp, url_prefix="/api/stt")
    app.register_blueprint(voice_session_bp, url_prefix="/api/voice")
    app.register_blueprint(privacy_bp, url_prefix="/api/privacy")
    app.register_blueprint(scheduled_emails_bp, url_prefix="/api/emails")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(reset_bp, url_prefix="/api/dev")

    # Initialize database tables on first startup
    try:
        init_db()
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization warning: {e}")

    # Nettoyage one-time : supprimer les attachments_meta incorrects issus de
    # l'ancienne heuristique multipart/mixed (valeur sentinelle '[{"has":true}]').
    # Les vrais attachments_meta ont des champs filename/size et ne sont pas affectés.
    try:
        from app.db.database import get_db_session
        from sqlalchemy import text as _sql_text
        with get_db_session() as _sess:
            result = _sess.execute(
                _sql_text("UPDATE emails SET attachments_meta = NULL WHERE attachments_meta = '[{\"has\":true}]'")
            )
            if result.rowcount > 0:
                logger.info(f"[OK] Nettoyage attachments_meta: {result.rowcount} entrées heuristiques supprimées")
    except Exception as _e:
        logger.debug(f"Nettoyage attachments_meta ignoré: {_e}")

    # Route de base
    @app.route("/")
    def index():
        return {
            "name": "Agentys API",
            "version": "1.0.0",
            "endpoints": {
                "health": "/api/health",
                "stats": "/api/stats",
                "emails": "/api/emails",
                "drafts": "/api/drafts",
                "followups": "/api/followups",
                "learning": "/api/learning",
                "costs": "/api/costs",
                "wizard": "/api/wizard",
                "marketplace": "/api/marketplace",
                "fine_tuning": "/api/fine-tuning",
                "mobile": "/api/mobile",
                "realtime_edit": "/api/realtime-edit",
                "templates": "/api/templates",
                "accounts": "/api/accounts",
                "settings": "/api/settings",
                "discord": "/api/discord",
                "telegram": "/api/telegram",
                "labels": "/api/labels",
                "folders": "/api/folders",
                "sync": "/api/sync",
                "connectivity": "/api/connectivity",
                "search": "/api/emails/search",
                "calendar": "/api/calendar",
                "webhooks": "/webhooks",
                "push": "/push",
            },
            "websocket": {
                "daemon": "/daemon (namespace pour événements temps réel)",
            }
        }

    # Error handlers — CASA V7.4 (#210): canonical JSON envelope
    # `{"success": false, "error": <generic-message>, "code": <STABLE_CODE>}`.
    # The `error` key is kept for backwards compatibility with the existing
    # frontend; `success`+`code` are additive so new clients can branch
    # without parsing prose.
    def _err_response(message: str, code: str, status: int):
        return {
            "success": False,
            "error": message,
            "code": code,
        }, status

    @app.errorhandler(400)
    def bad_request(error):
        message = getattr(error, 'description', 'Bad request')
        return _err_response(message, "BAD_REQUEST", 400)

    @app.errorhandler(404)
    def not_found(error):
        message = getattr(error, 'description', 'Not found')
        return _err_response(message, "NOT_FOUND", 404)

    @app.errorhandler(403)
    def forbidden(error):
        message = getattr(error, 'description', 'Forbidden')
        return _err_response(message, "FORBIDDEN", 403)

    @app.errorhandler(422)
    def unprocessable(error):
        message = getattr(error, 'description', 'Unprocessable entity')
        return _err_response(message, "UNPROCESSABLE", 422)

    from app.billing.entitlements import EntitlementRequiredError as _EntitlementRequiredError
    from app.api.utils.errors import error_response as _localized_error_response

    @app.errorhandler(_EntitlementRequiredError)
    def entitlement_required(error):
        return _localized_error_response(
            "FEATURE_REQUIRES_PAID_PLAN",
            "A paid active subscription is required for AI features",
            402,
            extra={"billing": error.entitlement.to_dict()},
        )

    @app.errorhandler(500)
    def internal_error(error):
        # Server-side log retains diagnostic detail (subject to redactor);
        # client receives only the generic envelope to avoid V7.4 disclosure.
        logger.error(f"Internal error: {error}")
        return _err_response("Internal server error", "INTERNAL_ERROR", 500)

    @app.errorhandler(503)
    def service_unavailable(error):
        message = getattr(error, 'description', 'Service unavailable')
        logger.error(f"Service unavailable: {message}")
        return _err_response(message, "SERVICE_UNAVAILABLE", 503)

    # CASA V7.4 (#210) global catch-all. Without this, an unhandled non-HTTPException
    # bubbles to Flask's default which serves the full traceback in development
    # (FLASK_ENV != production with propagate_exceptions). The handler logs
    # the full exception server-side but returns the same generic envelope.
    from werkzeug.exceptions import HTTPException as _HTTPException

    @app.errorhandler(Exception)
    def _generic_exception_handler(error):
        # Re-raise HTTPException so Flask's specific handlers (registered above)
        # still match — the generic Exception handler must NOT swallow them.
        if isinstance(error, _HTTPException):
            return error
        # The redactor (LogRecord factory below) scrubs secrets from the
        # logged repr. Sentry capture happens via FlaskIntegration too.
        logger.exception(f"Unhandled exception on {request.method} {request.path}")
        return _err_response("Internal server error", "INTERNAL_ERROR", 500)

    # Validate configuration at startup (log errors, don't block)
    try:
        from app.config import validate_config
        config_errors = validate_config(raise_on_error=False)
        for err in config_errors:
            logger.error(f"Configuration error: {err}")
    except Exception as e:
        logger.warning(f"Config validation failed: {e}")

    # Start provider pool cleanup scheduler
    try:
        from app.providers.provider_pool import start_cleanup_scheduler
        start_cleanup_scheduler(interval_seconds=60)
    except Exception as e:
        logger.warning(f"Failed to start provider pool cleanup scheduler: {e}")

    # Suppress werkzeug client-disconnect noise from console logs
    # "write() before start_response" = client closed connection before Flask responded (not a bug)
    import logging as _logging

    class _WerkzeugNoiseFilter(_logging.Filter):
        _NOISY = ("write() before start_response", "ConnectionAbortedError", "WinError 10053")

        def filter(self, record: _logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(n in msg for n in self._NOISY)

    _logging.getLogger("werkzeug").addFilter(_WerkzeugNoiseFilter())

    # CASA V7.1 (#210) — redact secrets + email PII in every log record
    # (defense-in-depth). Even if a developer accidentally logs a token,
    # password, magic-link URL, or full email address, the value is scrubbed
    # before any handler (Sentry, stdout, Railway) sees it.
    #
    # Implementation note: we use setLogRecordFactory rather than a Logger.filter
    # because Python only invokes filters on the originating logger — propagated
    # records bypass ancestor logger filters (cf. CPython logging.Logger.callHandlers).
    # The factory runs at record creation, so handler chains and pytest's caplog
    # both observe the redacted message.
    #
    # Patterns are defined at module level (`_SECRET_PATTERNS`, `_EMAIL_PII_RE`)
    # so `_sentry_before_send` consumes the same definitions.
    if not getattr(_logging, "_agentys_redactor_installed", False):
        _previous_factory = _logging.getLogRecordFactory()
        import traceback as _traceback

        def _agentys_redacting_factory(*args, **kwargs):
            record = _previous_factory(*args, **kwargs)
            try:
                msg = record.getMessage()
            except Exception:
                msg = None

            if msg is not None:
                redacted = _redact_text(msg)
                if redacted != msg:
                    # Overwrite both .msg and .args so getMessage() returns redacted
                    # and downstream formatters can't reconstruct the original.
                    record.msg = redacted
                    record.args = ()

            # Pre-format and redact the exception traceback if present.
            # Formatter.format() reuses `record.exc_text` when set, so writing
            # a redacted version here propagates to every handler (incl. Sentry's
            # logging integration, when enabled) without a separate filter.
            if record.exc_info and not record.exc_text:
                try:
                    record.exc_text = _redact_text(
                        "".join(_traceback.format_exception(*record.exc_info))
                    )
                except Exception:
                    pass
            elif record.exc_text:
                try:
                    record.exc_text = _redact_text(record.exc_text)
                except Exception:
                    pass

            return record

        _logging.setLogRecordFactory(_agentys_redacting_factory)
        _logging._agentys_redactor_installed = True

    # PR6 boot hook : migrate existing per-account ``contact_profiles`` JSON
    # dicts to the SQLite ``contact_styles`` table so the unified runtime
    # path (``WritingStyleProfile.contact_profiles`` view) reads from the
    # row-locked store instead of the legacy file blob. Idempotent —
    # ``replace_account`` clears each account's rows before re-inserting,
    # so re-running on every boot is safe and the boot cost is bounded by
    # the number of accounts (one transaction per profile).
    try:
        from app.infrastructure.contact_profiles_migration import (
            migrate_all_accounts_at_boot,
        )

        migrate_all_accounts_at_boot()
    except Exception as exc:
        # Migration must NEVER block API startup. The view falls back to
        # in-memory mode for accounts whose contacts haven't migrated yet,
        # and a manual run of ``scripts/migrate_contact_profiles_to_sqlite.py``
        # can recover later.
        logger.warning(
            "contact_profiles → SQLite boot migration skipped (non-fatal): %s",
            exc,
        )

    # Dedupe sent-side rows accumulated before the (account, subject, recipients,
    # date-minute) collapse landed. Idempotent : a clean cache returns 0. The
    # post-send + post-refresh hooks keep the cache clean afterwards ; this
    # boot pass exists to clear historical orphans without requiring users to
    # trigger a refresh manually.
    try:
        from app.db.database import get_db_session
        from app.db.models import Account
        from app.db.repositories.email_repository import EmailRepository
        from sqlalchemy import select as _sa_select

        with get_db_session() as _boot_sess:
            _account_ids = list(_boot_sess.scalars(_sa_select(Account.id)).all())
            _total_removed = 0
            _accounts_touched = 0
            for _aid in _account_ids:
                try:
                    _removed = EmailRepository(_boot_sess).dedupe_sent_by_content(_aid)
                    if _removed:
                        _total_removed += _removed
                        _accounts_touched += 1
                except Exception as _per_acct_err:
                    logger.debug(
                        "Boot dedupe skipped for account %s: %s", _aid, _per_acct_err,
                    )
            if _total_removed:
                _boot_sess.commit()
                logger.info(
                    "Boot sent-dedupe: removed %d duplicate row(s) across %d account(s)",
                    _total_removed, _accounts_touched,
                )
    except Exception as exc:
        logger.warning("Boot sent-dedupe skipped (non-fatal): %s", exc)

    logger.info("API Flask créée avec succès")
    return app
