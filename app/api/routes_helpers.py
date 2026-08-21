# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour Agentys.

Endpoints disponibles:
- GET /api/health - Health check léger (instantané)
- GET /api/health/deep - Health check complet (IMAP + LLM)
- GET /api/stats - Statistiques globales
- GET /api/emails - Liste des emails non lus
- GET /api/emails/<id> - Détails d'un email spécifique
- POST /api/emails/<id>/process - Traiter un email spécifique
- GET /api/drafts - Historique des brouillons
- GET /api/drafts/<id> - Détail d'un brouillon
- PATCH /api/drafts/<id>/feedback - Donner un feedback sur un brouillon
- GET /api/followups - Liste des follow-ups en attente
- GET /api/learning/stats - Statistiques d'apprentissage
- GET /api/learning/patterns - Patterns appris
- GET /api/learning/comparisons - Comparaisons avant/apres
- GET /api/costs - Breakdown des coûts
- GET /api/costs/history - Historique des coûts

Architecture:
    Ce module utilise le Container DI pour injecter les dépendances.
    Toutes les dépendances passent par le Container (Clean Architecture).
"""

import logging
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime
from flask import Blueprint, request, jsonify, g, abort
from werkzeug.exceptions import HTTPException

from app.config import should_persist_email_content
# Clean Architecture: Utiliser le Container DI
from app.infrastructure.container import get_container
from app.infrastructure.thread_pool import submit_background
from app.domain.entities import DraftInputTone

# Cache-first loading dependencies
from app.db.database import get_db_session
from app.db.repositories.email_repository import EmailRepository
from app.db.models.email import Email
from app.api.auth import is_trusted_loopback
from app.api.utils.errors import error_response
from app.utils.dates import to_naive_utc, utc_now_naive

logger = logging.getLogger(__name__)

# Pre-compiled regex for HTML stripping (used in _sync_label_emails, _strip_html_to_text)
_RE_STYLE_TAG = re.compile(r'<style[^>]*>.*?</style>', re.DOTALL)
_RE_HTML_TAG = re.compile(r'<[^>]+>')
_RE_WHITESPACE = re.compile(r'\s+')

# ---------------------------------------------------------------------------
# Module-level frozensets for O(1) membership on hot paths (inbox-stats,
# autocomplete, bulk-cleanup). Définir une seule fois au lieu de recréer des
# listes à chaque requête.
# ---------------------------------------------------------------------------
_NEWSLETTER_PATTERNS: frozenset = frozenset([
    'newsletter', 'noreply', 'no-reply', 'no_reply',
    'news@', 'digest@', 'updates@', 'marketing@',
    'promotions@', 'info@', 'notification@', 'mailer@',
    'bulk@', 'campaign@', 'announce@',
])
_NOTIFICATION_PATTERNS: frozenset = frozenset([
    'notification@', 'notifications@', 'alert@', 'alerts@',
    'noreply@', 'no-reply@', 'donotreply@',
    'system@', 'automated@', 'bot@',
])
_NOREPLY_PATTERNS: frozenset = frozenset([
    "noreply@", "no-reply@", "no_reply@", "donotreply@", "mailer-daemon@",
    "notifications@", "notification@", "newsletter@", "newsletters@",
    "updates@", "update@", "digest@", "news@", "announce@",
    "marketing@", "promo@", "promotions@", "campaigns@",
    "billing@", "receipts@", "receipt@", "invoice@", "invoices@",
    "alert@", "alerts@", "automated@", "auto@",
    "postmaster@", "bounce@", "bounces@",
    "feeds@", "feed@", "subscriptions@",
    # Support / commercial — almost never composed to
    "support@", "help@", "helpdesk@", "service@",
    "customerservice@", "customer-service@", "customer_service@",
    "info@", "contact@", "hello@", "communications@",
    "communication@", "comms@",
    # Verification / transactional
    "verify@", "verification@", "confirm@", "confirmation@",
    "welcome@", "onboarding@", "activation@", "activate@",
    "security@", "account@", "accounts@", "password@",
    # Commerce
    "orders@", "order@", "delivery@", "shipping@", "tracking@",
    "sales@", "deals@", "offers@", "rewards@", "membership@",
    # Corporate automated
    "admin@", "webmaster@", "press@", "media@",
    "jobs@", "careers@", "hiring@", "recruitment@", "talent@",
    "feedback@", "survey@", "surveys@", "reviews@",
    "events@", "event@", "rsvp@", "register@",
])
_NOISE_DOMAINS: frozenset = frozenset([
    "substack.com", "mail.instagram.com", "mail.facebook.com",
    "facebookmail.com", "e.linkedin.com", "linkedin.com",
    "email.twitter.com", "postmaster.twitter.com",
    "accounts.google.com", "googleusercontent.com",
    "youtube.com", "tiktok.com", "pinterest.com",
    "medium.com", "ghost.io", "mailchimp.com",
    "sendgrid.net", "amazonses.com", "mandrillapp.com",
    "mailgun.org", "sparkpostmail.com",
    "shopify.com", "squarespace.com",
    # Crypto
    "bitcoin.com", "binance.com", "coinbase.com", "kraken.com",
    "crypto.com", "bybit.com", "okx.com",
    # E-commerce
    "amazon.com", "amazon.ca", "amazon.fr",
    # Google services
    "calendar.google.com", "group.calendar.google.com",
    # Financial / transactional
    "questrade.com", "wealthsimple.com",
    # Wellness / AI community
    "apolloneuro.com",
    "cerebralvalley.ai", "cerebralvalley.com", "thecerebralvalley.com",
    # Marketing / transactional platforms
    "metamail.com", "constantcontact.com", "hubspot.com",
    "klaviyo.com", "brevo.com", "sendinblue.com",
    # Test / placeholder / fixture domains — never real contacts
    "example.com", "example.org", "example.net",
    "test.com", "localhost",
    # Spam-trap / devnull domains
    "webmaster.yandex.ru",
])


def _to_iso_utc(dt) -> str:
    """Convert a datetime to ISO 8601 UTC string (always ends with Z, never +00:00Z)."""
    if dt is None:
        return ""
    if hasattr(dt, 'isoformat'):
        s = dt.isoformat()
        # If timezone-aware with +00:00, replace with Z
        if s.endswith('+00:00'):
            s = s[:-6] + 'Z'
        # If naive (no tz info), append Z
        elif not s.endswith('Z') and '+' not in s[-6:] and '-' not in s[-6:]:
            s += 'Z'
        return s
    return str(dt)


# ============================================================================
# BLUEPRINT + MIDDLEWARE
# ============================================================================

api_bp = Blueprint("api", __name__)

# Routes publiques — pas d'authentification requise.
# api.health_strict (issue #577 item 1) doit y figurer car railway.toml l'utilise
# comme healthcheckPath : sans cette exemption, le before_request d'auth retourne
# 401 et Railway tue le nouveau container, ce qui a fait tomber prod le 2026-05-09
# au merge de PR #578. api.health_deep est ajouté pour cohérence (probe externe).
_PUBLIC_ENDPOINTS = frozenset({
    "api.ping",
    "api.health",
    "api.health_strict",
    "api.health_deep",
    "api.update_check",
})


@api_bp.before_request
def _enforce_auth_or_local():
    """Applique require_auth_or_local sur toutes les routes data du Blueprint.

    Les routes publiques (ping, health, update-check) sont exemptées.
    """
    from flask import request as _req, g as _g
    from app.api.auth import _decode_jwt

    if _req.endpoint in _PUBLIC_ENDPOINTS:
        return  # Route publique, pas d'auth requise

    if os.environ.get("AGENTYS_LOAD_TEST_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        _g.auth_user = None
        return

    auth_header = _req.headers.get("Authorization", "")
    remote_addr = _req.remote_addr or ""
    is_local = is_trusted_loopback()

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = _decode_jwt(token)
        if payload:
            _g.auth_user = {"id": payload["sub"], "email": payload["email"]}
        elif is_local:
            # BUG-P3-001 (résolu) : un token Bearer invalide/expiré depuis loopback était accepté
            # silencieusement, ce qui produisait un 200 trompeur lors des tests automatisés.
            # Ce comportement est INTENTIONNEL pour l'app Tauri desktop (pas de JWT en mode dev),
            # mais on loggue maintenant explicitement pour rendre le bypass traçable.
            logger.debug(
                "[auth] Bearer token invalide accepté depuis loopback (%s) — "
                "comportement Tauri desktop intentionnel (BUG-P3-001)",
                remote_addr,
            )
            _g.auth_user = None
        else:
            return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)
    else:
        # Pas de JWT — autorisé seulement en mode local (Tauri desktop)
        if not is_local:
            return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
        _g.auth_user = None


@api_bp.teardown_request
def _close_providers(exc):
    """Auto-disconnect non-pooled providers at the end of each request.

    Pooled providers (managed by ProviderPool) are kept alive for reuse.
    Only providers explicitly created outside the pool are disconnected.
    """
    from flask import g as _g
    providers = getattr(_g, '_providers_to_close', None)
    if providers:
        from app.providers.provider_pool import ProviderPool
        pool = ProviderPool.get_instance()
        pooled_providers = set(p for p, _ in pool._pool.values()) if pool._pool else set()
        for provider in providers:
            # Skip pooled providers — they are managed by the pool's idle cleanup
            if provider in pooled_providers:
                continue
            if hasattr(provider, 'disconnect'):
                try:
                    provider.disconnect()
                except Exception as e:
                    logger.debug(f"Provider disconnect on teardown failed: {e}")
        _g._providers_to_close = []


@api_bp.before_request
def _set_request_timing():
    """Initialise les ressources pour chaque requête."""
    g.start_time = datetime.now()


@api_bp.after_request
def _add_response_headers(response):
    """Ajoute des headers communs et CORS."""
    if hasattr(g, "start_time"):
        duration_ms = int((datetime.now() - g.start_time).total_seconds() * 1000)
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
    response.headers["X-API-Version"] = API_VERSION
    # Cache headers for GET responses
    if request.method == "GET" and response.status_code == 200:
        response.headers["Cache-Control"] = "private, max-age=30"
    elif request.method in ("POST", "PUT", "PATCH", "DELETE"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Path safety — allowed base directories for /save-file, /open-folder, wizard
# ---------------------------------------------------------------------------
import os as _os

# M-9 (audit security.md, issue #543): pre-fix, ``_SAFE_BASES`` contained
# ``$HOME`` which let any caller that bypassed the loopback / prod-disable
# gates write into ``~/.ssh/``, ``~/.config/``, ``~/.zshrc`` etc. Defense in
# depth: narrow the safe list to a dedicated app folder (plus the project
# root for dev/CI use). Subdirectories are accepted (e.g.
# ``~/Downloads/Agentys/MyProject/``).
#
# Read-side wizard import/export (``app/api/wizard.py``) reuses
# ``_is_safe_path`` and is already triple-gated (``@require_admin`` +
# loopback-only-in-prod + this check). After the narrow, admins must place
# KB files they want to import under ``~/Downloads/Agentys/`` — minor UX
# friction acceptable in exchange for closing the home-write surface.
_SAFE_BASES = [
    _os.path.expanduser("~/Downloads/Agentys"),  # Dedicated app folder
    _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..")),  # Project root (dev/CI)
]


def _is_safe_path(file_path: str) -> bool:
    """Validate that *file_path* resolves under an allowed base directory.

    Accepts subdirectories. Returns False if the path resolves outside
    every base in ``_SAFE_BASES`` (cf. M-9 #543).
    """
    resolved = _os.path.realpath(file_path)
    return any(
        resolved.startswith(_os.path.realpath(base) + _os.sep)
        or resolved == _os.path.realpath(base)
        for base in _SAFE_BASES
    )


@api_bp.route("/save-file", methods=["POST"])
def save_file_to_folder():
    """Save a base64-encoded file to a local folder (project folder export).

    Audit 2026-04-25 (HIGH-Backend-6 / sub-report 01 HIGH-06): zero frontend
    callsites; the endpoint exists for the Tauri desktop "Save attachment"
    flow that runs from loopback. Restrict to loopback callers + non-prod
    environments. A web caller on Railway has no legitimate need to write
    bytes onto the server's filesystem.
    """
    from app.api.auth import is_trusted_loopback
    from app.api._auth_helpers import is_production

    if is_production():
        return jsonify({"error": "Endpoint disabled in production"}), 404
    if not is_trusted_loopback():
        return jsonify({"error": "save-file is localhost-only"}), 403

    import base64
    data = request.get_json()
    folder = (data.get("folder") or "").strip()
    filename = (data.get("filename") or "").strip()
    data_b64 = data.get("data_base64") or ""

    if not folder or not filename or not data_b64:
        return jsonify({"error": "Missing folder, filename, or data_base64"}), 400

    # Security: reject path traversal and shell metacharacters
    if ".." in folder or ".." in filename:
        return jsonify({"error": "Invalid path"}), 400
    if any(c in filename for c in '<>"|?*'):
        return jsonify({"error": "Invalid filename"}), 400

    # Audit 2026-04-25: extension allow-list to prevent .py / .json / .so
    # writes that could replace runtime files. Audit hint HIGH-06.
    _BLOCKED_EXTS = {".py", ".pyc", ".pyo", ".so", ".dll", ".dylib", ".env",
                     ".sh", ".bat", ".cmd", ".ps1"}
    _filename_lower = filename.lower()
    for blocked in _BLOCKED_EXTS:
        if _filename_lower.endswith(blocked):
            return jsonify({"error": f"Filename extension not allowed: {blocked}"}), 400

    import os
    folder_path = os.path.abspath(folder)
    if not os.path.isdir(folder_path):
        return jsonify({"error": f"Folder does not exist: {folder}"}), 400

    file_path = os.path.realpath(os.path.join(folder_path, filename))

    # Security: ensure resolved path stays under allowed base directories
    if not _is_safe_path(folder_path):
        return jsonify({"error": "Path outside allowed directories"}), 403
    if not _is_safe_path(file_path):
        return jsonify({"error": "Path outside allowed directories"}), 403

    try:
        file_bytes = base64.b64decode(data_b64)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        return jsonify({"path": file_path, "message": "File saved"}), 200
    except Exception:
        # Audit 2026-04-25 (sub-report 01 MED-03): don't leak raw exception
        # strings to clients. Diagnostic context goes to logs only.
        logger.exception("save-file write failed")
        return jsonify({"error": "Could not save file"}), 500


@api_bp.route("/open-folder", methods=["POST"])
def open_folder_in_explorer():
    """Open a local folder in the system file explorer."""
    import os
    import subprocess
    import platform

    data = request.get_json()
    folder = (data.get("folder") or "").strip()

    if not folder:
        return jsonify({"error": "Missing folder"}), 400
    if ".." in folder:
        return jsonify({"error": "Invalid path"}), 400

    folder_path = os.path.realpath(os.path.abspath(folder))

    # Security: ensure resolved path stays under allowed base directories
    if not _is_safe_path(folder_path):
        return jsonify({"error": "Path outside allowed directories"}), 403
    if not os.path.isdir(folder_path):
        return jsonify({"error": "Not a directory"}), 400

    try:
        system = platform.system()
        if system == "Windows":
            # os.startfile exists only on Windows — mypy runs on Linux CI and
            # can't see it. Runtime guarded by the platform check above.
            os.startfile(folder_path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", folder_path])
        else:
            subprocess.Popen(["xdg-open", folder_path])
        return jsonify({"message": "Folder opened"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.errorhandler(HTTPException)
def _handle_http_exception(e):
    """Return JSON instead of HTML for HTTP errors."""
    return jsonify({"error": e.description}), e.code


# API Version (used in headers and health endpoint)
_BASE_VERSION = "1.0.0"


def _get_git_hash() -> str:
    """Récupère le hash court du commit git courant (au démarrage)."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Git hash retrieval failed: {e}")
    return "unknown"


API_GIT_HASH = _get_git_hash()
API_VERSION = f"{_BASE_VERSION}+{API_GIT_HASH}"

# ============================================================================
# IN-MEMORY EMAIL CACHE (fast path for slow IMAP providers)
# ============================================================================
import time as _cache_time

# Throttle: background jobs (auto-reply, follow-ups, prefetch) max once per 60s.
#
# S-03 fix (2026-04-24): the throttle is now keyed per account (oauth or DB id —
# whichever the caller has). Previously a single float was shared across all
# accounts, so account A's run silently throttled account B's run for 60s,
# starving B's auto-reply / follow-ups / secondary folder prefetch.
#
# `_last_bg_jobs_time` is kept as a legacy alias that mirrors the most recent
# write; nothing should read it directly anymore (all read sites should call
# `should_run_bg_jobs(account_id)` instead).
_last_bg_jobs_time: float = 0.0
_last_bg_jobs_time_per_account: dict[str, float] = {}
_BG_JOBS_THROTTLE_SECONDS = 60.0


def should_run_bg_jobs(account_id, now: float | None = None) -> bool:
    """Return True if the background-jobs throttle for this account has elapsed.

    Side-effect: when True, the per-account "last run" timestamp is updated to
    `now` so a follow-up call within the throttle window will return False.

    Args:
        account_id: The account scope key. Stringified internally so callers
            can pass either an oauth hash id ("ca85336e01d3bc46") or an int
            DB id (1, 2, 3) without coordinating types across call sites.
        now: Optional override for the current epoch time (for tests). When
            omitted, uses time.time().

    Returns:
        True if the bg jobs should run for this account, False if throttled.
    """
    if account_id in (None, "", -1):
        # Without a scope key, fall back to the legacy single-bucket throttle
        # (better than blindly running every call). Use the literal sentinel
        # "__global__" to keep this contained to one bucket.
        scope = "__global__"
    else:
        scope = str(account_id)
    _now = _cache_time.time() if now is None else now
    last = _last_bg_jobs_time_per_account.get(scope, 0.0)
    if _now - last <= _BG_JOBS_THROTTLE_SECONDS:
        return False
    _last_bg_jobs_time_per_account[scope] = _now
    # Mirror the most recent write into the legacy global so any straggling
    # reader sees a sane non-zero value (avoids re-introducing constant runs).
    global _last_bg_jobs_time
    _last_bg_jobs_time = _now
    return True

# ============================================================================
# ACCOUNT ID CACHE (60s TTL — per-email dict for multi-user isolation)
# ============================================================================
_account_id_cache: dict[str, dict] = {}  # {email: {"value": int, "timestamp": float}}
_account_id_cache_lock = threading.Lock()
_ACCOUNT_ID_TTL = 60


_NO_ACCOUNT_SENTINEL = -1  # Impossible DB ID — SQL queries with this will always return empty

# Self-heal cooldown (bug Karine 2026-06-09) : un heal qui échoue (ex: INSERT
# refusé par la DB) ne doit pas re-tenter un write à chaque requête.
_heal_attempts: dict[str, float] = {}  # {email: last_attempt_timestamp}
_HEAL_ATTEMPT_COOLDOWN_SECONDS = 300


def _suppress_account_heal(email: str, duration_seconds: float = 3600.0) -> None:
    """Block `_heal_missing_db_account` for `email` during a deletion flow.

    Account deletion removes the DB row FIRST (slow privacy purge, >20s) and
    the AccountManager entry LAST. In that window the FE keeps polling
    /api/emails, which would re-trigger the self-heal and resurrect the row
    as an orphan ghost account. Callers deleting an account must invoke this
    right after `_invalidate_account_id_cache(email)` (which clears any prior
    suppression). A later OAuth re-connect lifts the block via the same
    invalidation helper.
    """
    if not email:
        return
    # Push the "last attempt" into the future so the cooldown gate holds
    # for the requested duration.
    until = _cache_time.time() + max(0.0, duration_seconds) - _HEAL_ATTEMPT_COOLDOWN_SECONDS
    with _account_id_cache_lock:
        _heal_attempts[email] = until
        _heal_attempts[email.lower()] = until


def _invalidate_account_id_cache(email: str | None = None) -> None:
    """Invalidate the per-email account-id resolution cache.

    ISO-12 fix (2026-04-24): the cache had a 60s TTL but no explicit
    invalidation, so deleting an account or remapping email→account_id
    (e.g. a user re-registers with the same address) could return the
    stale id for up to a minute. Callers that mutate the accounts table
    or the multi_accounts.json file should call this helper.

    Args:
        email: Specific email to evict. Pass None to clear the entire
            cache (useful on bulk import / account-table reset).
    """
    with _account_id_cache_lock:
        if email is None:
            _account_id_cache.clear()
            _heal_attempts.clear()
            return
        _account_id_cache.pop(email, None)
        _account_id_cache.pop(email.lower(), None)
        _heal_attempts.pop(email, None)
        _heal_attempts.pop(email.lower(), None)


def _heal_missing_db_account(email: str) -> int | None:
    """Re-create a missing `accounts` row from the OAuth AccountManager config.

    Bug Karine 2026-06-09 (onglets Corbeille/Spam morts) : quand la ligne
    `accounts` disparaît (DB recréée après corruption, `db_sync_failed` au
    callback OAuth, désync accounts.json↔DB) alors que le compte OAuth reste
    pleinement fonctionnel, tous les resolvers renvoient le sentinel -1. Les
    dossiers servis exclusivement depuis SQLite (trash/spam/archived/sent)
    deviennent alors définitivement vides : la sync d'arrière-plan récupère les
    emails du provider puis les jette ("invalid account_id=-1 — aborting SQLite
    writes") et /api/emails répond `sync_in_progress: true` pour toujours.

    Garde-fous :
      - heal uniquement si l'AccountManager connaît l'email (un JWT arbitraire
        pré-OAuth ne peut pas minter de ligne accounts) ;
      - ownership = user_id de la config manager (pas l'appelant) ;
      - cooldown 5 min par email quand l'INSERT échoue (ex: PG saturé) ;
      - course avec le callback OAuth : UNIQUE(email) → re-lecture.

    Returns the new (or raced-existing) DB id, or None when no heal is possible.
    """
    now = _cache_time.time()
    with _account_id_cache_lock:
        last = _heal_attempts.get(email, 0.0)
        if now - last < _HEAL_ATTEMPT_COOLDOWN_SECONDS:
            return None
        _heal_attempts[email] = now

    try:
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account_by_email(email)
    except Exception as exc:
        logger.debug("[ACCOUNT-HEAL] manager lookup failed for %s: %s", email, exc)
        return None
    if cfg is None:
        return None

    try:
        from app.api.auth import user_id_from_email
        from app.db.models.account import Account as AccountModel
        from app.db.repositories.account_repository import AccountRepository

        owner_user_id = getattr(cfg, "user_id", None) or user_id_from_email(email)
        with get_db_session() as session:
            repo = AccountRepository(session)
            existing = repo.get_by_email(email)
            if existing is not None:
                # Raced with the OAuth callback / another worker — reuse.
                if not existing.is_active:
                    existing.is_active = True
                session.commit()
                return existing.id
            row = AccountModel(
                email=email,
                provider=getattr(cfg, "provider", None) or "gmail",
                display_name=getattr(cfg, "name", None) or email.split("@")[0],
                is_active=True,
                user_id=owner_user_id,
            )
            session.add(row)
            session.flush()
            new_id = row.id
            session.commit()
        logger.warning(
            "[ACCOUNT-HEAL] accounts row was missing for %s — recreated from "
            "AccountManager config (id=%s, user_id=%s). Folder caches will "
            "repopulate on the next background sync.",
            email, new_id, owner_user_id,
        )
        with _account_id_cache_lock:
            _heal_attempts.pop(email, None)
        return new_id
    except Exception as exc:
        # UNIQUE(email) race or DB write failure — try a fresh read before
        # giving up (the row may have been inserted concurrently).
        try:
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                raced = AccountRepository(session).get_by_email(email)
                if raced is not None:
                    return raced.id
        except Exception:
            pass
        logger.warning("[ACCOUNT-HEAL] failed for %s: %s", email, exc)
        return None


def _resolve_account_id_for_email(email: str) -> int:
    """Resolve the DB account ID for a given email address.

    Uses a per-email cache with 60s TTL.
    Returns -1 (sentinel) if no matching DB account exists.
    """
    if not email:
        return _NO_ACCOUNT_SENTINEL

    now = _cache_time.time()
    with _account_id_cache_lock:
        cached = _account_id_cache.get(email)
        if (cached
                and now - cached["timestamp"] < _ACCOUNT_ID_TTL
                and cached["value"] is not None):
            return cached["value"]

    account_id = None
    try:
        with get_db_session() as session:
            from app.db.repositories.account_repository import AccountRepository
            acct_repo = AccountRepository(session)
            db_account = acct_repo.get_by_email(email)
            if db_account:
                account_id = db_account.id
    except Exception as e:
        logger.warning(f"Account ID resolution failed for {email}: {e}")

    if account_id is None:
        # Bug Karine 2026-06-09 : ligne accounts absente alors que le compte
        # OAuth existe → self-heal au lieu de propager le sentinel -1 (qui
        # rendait Corbeille/Spam définitivement vides, cf. _heal_missing_db_account).
        account_id = _heal_missing_db_account(email)

    if account_id is not None:
        with _account_id_cache_lock:
            _account_id_cache[email] = {"value": account_id, "timestamp": now}
        return account_id

    return _NO_ACCOUNT_SENTINEL


def _resolve_account_id_for_user() -> int:
    """Resolve the DB account ID from JWT auth (g.auth_user) or fallback to global singleton.

    Multi-user safe: when g.auth_user is set (JWT), resolves by email.
    Returns -1 (sentinel) if JWT user has no account — this impossible ID
    guarantees SQL queries like `WHERE account_id = -1` return zero rows,
    preventing cross-user data leaks across all 25+ call sites.
    Fallback to get_current_account() for Tauri desktop mode (single user).
    """
    from flask import has_request_context
    auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
    is_jwt_user = bool(auth_user and auth_user.get("email"))

    if is_jwt_user:
        return _resolve_account_id_for_email(auth_user["email"])

    from app.multi_accounts import get_current_account
    current = get_current_account()
    if current and current.email:
        return _resolve_account_id_for_email(current.email)

    return _NO_ACCOUNT_SENTINEL


def _resolve_account_id_cached() -> int:
    """Alias rétrocompatible — délègue à _resolve_account_id_for_user()."""
    return _resolve_account_id_for_user()


def _per_caller_bucket_key(prefix: str) -> str:
    """Build a per-caller rate-limit bucket key.

    Resolves the DB account id; falls back to a JWT-identity-keyed bucket
    when the resolver returns ``_NO_ACCOUNT_SENTINEL`` (-1) so all pre-
    OAuth users on the cloud install don't collapse into one shared
    ``"<prefix>:-1"`` bucket.

    Audit F-03 (2026-05-16): the prior pattern interpolated the resolver
    output directly (`f"{prefix}:{aid}"`), which produced literal
    ``"refine_text:-1"`` for any JWT user without a DB account row yet.
    One pre-OAuth attacker (or a single noisy user) could burn the 15-
    call/minute bucket for every other newly-signed-up user in the same
    cohort — reopening the cross-tenant LLM cost drain that audit
    H-8/#534 was supposed to close.
    """
    try:
        aid = _resolve_account_id_for_user()
    except Exception:
        aid = _NO_ACCOUNT_SENTINEL
    if isinstance(aid, int) and aid > 0:
        return f"{prefix}:{aid}"
    try:
        from flask import g, has_request_context
        if has_request_context():
            au = getattr(g, "auth_user", None) or {}
            ident = au.get("email") or au.get("sub") or au.get("id")
            if ident:
                return f"{prefix}:jwt:{ident}"
    except Exception:
        pass
    return f"{prefix}:anonymous"


def _resolve_account_id_for_provider(provider) -> int:
    """Resolve the DB account id from the provider selected for this request.

    Long send/draft requests can overlap with an account switch in the UI. In
    that case reading the global "current account" again later may return a
    different mailbox than the provider already authenticated against.
    """
    provider_account_id = getattr(provider, "account_id", None)
    if provider_account_id:
        try:
            from app.multi_accounts import get_account_manager
            account = get_account_manager().get_account(str(provider_account_id))
            if account and account.email:
                return _resolve_account_id_for_email(account.email)
        except Exception as e:
            logger.warning(
                "Provider account_id resolution failed for %s: %s",
                _sanitize_for_log(str(provider_account_id)),
                e,
            )
    return _resolve_account_id_cached()


def _resolve_oauth_account_id_for_db_account(account_id: int | None) -> str | None:
    """Resolve DB account id -> OAuth AccountManager hash id."""
    if not account_id or account_id <= 0:
        return None
    try:
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            db_account = AccountRepository(session).get(int(account_id))
            email = getattr(db_account, "email", None) if db_account else None
        if not email:
            return None
        from app.multi_accounts import get_account_manager
        account = get_account_manager().get_account_by_email(email)
        return getattr(account, "id", None) if account else None
    except Exception as e:
        logger.warning(
            "OAuth account id resolution failed for db account %s: %s",
            account_id,
            e,
        )
        return None


def require_owned_account_id(header_value: str | None) -> int:
    """Resolve the X-Account-Id header to a DB account_id owned by the JWT caller.

    Audit P1-005 (2026-04-28): the previous behavior fell back to the
    caller's "current" account when the header was bogus, so a request
    with `X-Account-Id: DEADBEEF` returned the JWT user's own data
    silently — masking client bugs and providing zero defense against
    confused-deputy scenarios where a malicious frontend tries to
    address a foreign tenant's resource.

    Behavior:
      - No header (None / empty): resolve via the normal JWT path
        (`_resolve_account_id_for_user`). Returns -1 sentinel if no
        owned account.
      - Header is a DB int: validated directly against owned accounts.
      - Header is a hash (multi_accounts.json key, e.g. "458130f56b9bb6f0"):
        resolved via `AccountManager.get_account(hash)` → email →
        DB int, then validated against owned accounts. The frontend's
        `/api/accounts` endpoint returns hash IDs while `/api/init`
        returns int IDs (cf. CLAUDE.md "Multi-compte — Résolution des
        IDs"); both must be accepted to avoid a false-404 when
        AccountManager.tsx sets X-Account-Id from listAccounts().
      - Header present but not resolvable, or maps to an account not
        owned by the JWT caller: return -1 sentinel. Callers MUST
        translate the sentinel into a 404 (not a fallthrough to
        current account).

    Returns the int account_id on success, or `_NO_ACCOUNT_SENTINEL`
    (-1) on any failure.
    """
    from flask import has_request_context
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    if header_value is None or str(header_value).strip() == "":
        return _resolve_account_id_for_user()

    try:
        header_id = int(header_value)
    except (TypeError, ValueError):
        # Hash form: resolve via AccountManager (hash → AccountConfig.email)
        # then via _resolve_account_id_for_email (email → DB int). The
        # ownership check below still applies, so unowned hashes 404.
        try:
            from app.multi_accounts import get_account_manager
            acct = get_account_manager().get_account(str(header_value).strip())
        except Exception as e:
            logger.warning("require_owned_account_id hash lookup failed: %s", e)
            return _NO_ACCOUNT_SENTINEL
        if not acct or not getattr(acct, "email", None):
            return _NO_ACCOUNT_SENTINEL
        resolved = _resolve_account_id_for_email(acct.email)
        if resolved == _NO_ACCOUNT_SENTINEL:
            return _NO_ACCOUNT_SENTINEL
        header_id = resolved

    auth_user = getattr(g, "auth_user", None) if has_request_context() else None

    # Loopback / Tauri / local dev: trust the header even if a JWT is present.
    # The dev-login endpoint mints arbitrary JWTs from any email on loopback,
    # so a strict ownership check against a fake identity is meaningless and
    # produces false 404s on the user's own inbox when they switch dev users
    # without clearing the cached JWT in localStorage. The audit P1-005
    # protection targets cloud / multi-tenant flows; gate the relaxation
    # behind `not _is_production_env` so prod stays strict.
    if has_request_context():
        try:
            from app.api.auth import is_trusted_loopback, _is_production_env
            if (not _is_production_env) and is_trusted_loopback():
                return header_id
        except Exception as e:
            logger.debug("loopback gate evaluation failed: %s", e)

    # No JWT: trust the header (Tauri desktop default path, no auth context).
    if not auth_user or not auth_user.get("email"):
        return header_id

    user_id = auth_user.get("id")
    user_email = (auth_user.get("email") or "").strip().lower()
    try:
        with get_db_session() as session:
            repo = AccountRepository(session)
            owned: set[int] = set()
            if user_id is not None:
                owned = {a.id for a in repo.get_active_accounts_for_user(int(user_id))}
            # Always include the email-matched account, not just as fallback.
            # Handles the legitimate case where an account was created in
            # single-tenant mode (user_id=None) or linked to a stale user_id
            # while the JWT email still matches. The DB enforces a UNIQUE
            # index on accounts.email, so two callers can't share an email
            # — the email-match is therefore an authoritative ownership
            # signal. Defensive belt: only trust the match when the
            # account's user_id is NULL (legacy / unlinked) or equals the
            # JWT user_id, so a hypothetical schema regression that drops
            # the unique constraint can't immediately become an auth bug.
            if user_email:
                acc = repo.get_by_email(user_email)
                if acc:
                    _acc_uid = getattr(acc, "user_id", None)
                    if _acc_uid is None or (
                        user_id is not None and int(_acc_uid) == int(user_id)
                    ):
                        owned.add(acc.id)
            if header_id in owned:
                return header_id
    except Exception as e:
        logger.warning("require_owned_account_id lookup failed: %s", e)

    logger.warning(
        "X-Account-Id ownership check failed: header=%s user=%s",
        header_id, user_email,
    )
    return _NO_ACCOUNT_SENTINEL


def _get_current_account_for_user():
    """Retourne le AccountConfig du user courant (JWT-aware).

    Utilise g.auth_user si dispo (multi-user), sinon fallback get_current_account() (Tauri).
    Returns None if JWT user has no matching account (prevents cross-user leaks).

    Pour les connexions loopback (Tauri desktop), on ignore le JWT et on utilise
    directement get_current_account() — même comportement que les autres endpoints.

    Defense-in-depth (ISO C-2, issue #522): in a non-loopback request without
    a JWT we now return ``None`` instead of falling back to the singleton.
    The auth guard normally 401s those callers before they reach a handler,
    but if a future blueprint is forgotten in ``_guarded_blueprints`` (which
    is exactly what shipped C-2 for ``scheduled_emails_bp``), this function
    must not silently expose the singleton account to a remote attacker.
    """
    from app.multi_accounts import get_current_account, get_account_manager
    from flask import has_request_context
    # Loopback = Tauri desktop mode: bypass JWT lookup to use the pooled account
    if has_request_context():
        from app.api.auth import is_trusted_loopback
        if is_trusted_loopback():
            return get_current_account()
    auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
    if auth_user and auth_user.get("email"):
        account = get_account_manager().get_account_by_email(auth_user["email"])
        if account:
            return account
        # JWT email not found — return None (do NOT fallback to another user's account)
        return None
    # In-request, non-loopback, no JWT: regression-resistant refusal — see
    # docstring. CLI / out-of-request callers (no request context at all) keep
    # the singleton fallback because they are trusted by construction.
    if has_request_context():
        return None
    return get_current_account()


def _get_blocked_senders_set() -> set:
    """Retourne l'ensemble des expéditeurs bloqués (en minuscules) pour le compte courant."""
    try:
        current = _get_current_account_for_user()
        if current and current.blocked_senders:
            return {s.lower() for s in current.blocked_senders}
    except Exception as e:
        logger.debug(f"Failed to load blocked senders: {e}")
    return set()


def _filter_blocked_senders(emails: list, blocked: set) -> list:
    """Filtre les emails provenant d'expéditeurs bloqués.

    Args:
        emails: Liste de dicts email (avec clé 'sender').
        blocked: Ensemble d'adresses email bloquées (en minuscules).

    Returns:
        Liste filtrée (sans les emails bloqués).
    """
    if not blocked:
        return emails
    from app.multi_accounts import AccountManager
    return [
        e for e in emails
        if AccountManager._extract_email(e.get("sender", "")) not in blocked
    ]


def _get_spammed_senders_set() -> set:
    """Retourne l'ensemble des expéditeurs appris comme spam (en minuscules) pour le compte courant."""
    try:
        current = _get_current_account_for_user()
        if current and current.spammed_senders:
            return {s.lower() for s in current.spammed_senders}
    except Exception as e:
        logger.debug(f"Failed to load spammed senders: {e}")
    return set()


def _filter_spammed_senders(emails: list, spammed_senders: set, spammed_domains: set = None) -> list:
    """Filtre les emails provenant d'expéditeurs ou domaines appris comme spam (inbox uniquement).

    Args:
        emails: Liste de dicts email (avec clé 'sender').
        spammed_senders: Ensemble d'adresses email apprises comme spam (en minuscules).
        spammed_domains: Ensemble de domaines appris comme spam (en minuscules).

    Returns:
        Liste filtrée (sans les emails spam appris).
    """
    if not spammed_senders and not spammed_domains:
        return emails
    from app.multi_accounts import AccountManager
    _domains = spammed_domains or set()

    def _is_spammed(sender: str) -> bool:
        email_addr = AccountManager._extract_email(sender)
        if email_addr in spammed_senders:
            return True
        if _domains and "@" in email_addr:
            domain = email_addr.split("@")[1].lower()
            if domain in _domains:
                return True
        return False

    return [e for e in emails if not _is_spammed(e.get("sender", ""))]


def _learn_spam_pattern(sender_email: str, email_id: str) -> None:
    """Auto-analyse un email marqué spam et crée des règles d'apprentissage.

    1. Ajoute le sender aux spammed_senders (filtrage inbox + daemon auto-move)
    2. Crée une LabelingRule sender → Noise
    3. Si signaux de masse détectés (noreply, bulk headers, unsubscribe links),
       apprend aussi le domaine pour attraper les variantes futures
    """
    try:
        from app.multi_accounts import get_account_manager, AccountManager

        clean_email = AccountManager._extract_email(sender_email)
        if not clean_email:
            return
        account_id = _resolve_account_id_for_user()

        # 1. Ajouter le sender à spammed_senders
        current = _get_current_account_for_user()
        manager = None
        if current:
            manager = get_account_manager()
            spammed = current.spammed_senders or []
            if clean_email not in [s.lower() for s in spammed]:
                spammed.append(clean_email)
                manager.update_account(current.id, spammed_senders=spammed)

        # 2. Récupérer les données de l'email pour analyse automatique
        email_subject = ""
        email_body = ""
        try:
            from app.db.database import get_db_session
            from app.db.repositories.email_repository import EmailRepository
            with get_db_session() as session:
                repo = EmailRepository(session)
                raw_id = email_id[5:] if email_id.startswith("sent:") else email_id
                record = repo.get_by_email_id(raw_id, account_id=account_id)
                if record:
                    email_subject = record.subject or ""
                    email_body = record.body_text or record.body_html or ""
        except Exception as e:
            logger.warning(f"[SPAM-LEARN] Failed to fetch email details for spam analysis: {e}")

        # 3. Créer des LabelingRules basées sur l'analyse
        try:
            from app.infrastructure.container import get_container
            from app.domain.entities.email_labels import LabelingRule
            import uuid

            container = get_container()
            store = container.get_label_store(account_id=account_id if account_id > 0 else None)

            # Règle sender → Noise (toujours)
            store.add_rule(LabelingRule(
                rule_id=str(uuid.uuid4()),
                label_name="Noise",
                condition_type="sender",
                condition_value=clean_email,
                priority=70,
                learned_from=email_id,
                confidence=0.9,
            ))

            # 4. Détecter si c'est un email de masse → apprendre le domaine
            _is_bulk = False
            if "@" in clean_email:
                domain = clean_email.split("@")[1].lower()
                sender_local = clean_email.split("@")[0].lower()

                # Signaux sender : préfixes automatisés
                _bulk_prefixes = (
                    "noreply", "no-reply", "donotreply", "notifications",
                    "marketing", "news", "newsletter", "promo", "info",
                    "support", "team", "hello", "contact", "sales",
                    "updates", "alerts", "mailer", "digest", "bulletin",
                )
                if any(sender_local.startswith(p) for p in _bulk_prefixes):
                    _is_bulk = True

                # Signaux domaine : plateformes d'envoi en masse
                _bulk_domains = (
                    "substack.com", "mailchimp.com", "sendgrid.net",
                    "brevo.com", "hubspot.com", "constantcontact.com",
                    "mailgun.org", "amazonses.com", "mandrillapp.com",
                    "sendinblue.com", "mailjet.com", "campaign-archive.com",
                )
                if any(domain.endswith(d) for d in _bulk_domains):
                    _is_bulk = True

                # Signaux contenu : liens de désabonnement, "view in browser"
                if not _is_bulk and (email_subject or email_body):
                    _text = (email_subject + " " + email_body[:1000]).lower()
                    _unsub_signals = (
                        "unsubscribe", "se désabonner", "opt-out", "opt out",
                        "manage preferences", "view in browser", "voir dans le navigateur",
                        "email preferences", "update your preferences",
                        "you are receiving this", "this email was sent to",
                        "do not reply", "ne pas répondre",
                    )
                    if sum(1 for sig in _unsub_signals if sig in _text) >= 2:
                        _is_bulk = True

                if _is_bulk:
                    # Apprendre le domaine → attrape les variantes (sales@, news@, etc.)
                    store.add_rule(LabelingRule(
                        rule_id=str(uuid.uuid4()),
                        label_name="Noise",
                        condition_type="sender",
                        condition_value=f"@{domain}",
                        priority=60,
                        learned_from=email_id,
                        confidence=0.8,
                    ))
                    # Ajouter aux spammed_domains
                    if current and manager:
                        spammed_domains = current.spammed_domains or []
                        if domain not in [d.lower() for d in spammed_domains]:
                            spammed_domains.append(domain)
                            manager.update_account(current.id, spammed_domains=spammed_domains)

            logger.info(f"[SPAM-LEARN] Règles créées pour {clean_email} (bulk={_is_bulk})")
        except Exception as e:
            logger.warning(f"[SPAM-LEARN] Échec création règle pour {clean_email}: {e}")

    except Exception as e:
        logger.warning(f"[SPAM-LEARN] Échec apprentissage spam pour {sender_email}: {e}")


def _get_spammed_domains_set() -> set:
    """Retourne l'ensemble des domaines appris comme spam (en minuscules) pour le compte courant."""
    try:
        current = _get_current_account_for_user()
        if current and current.spammed_domains:
            return {d.lower() for d in current.spammed_domains}
    except Exception as e:
        logger.debug(f"Failed to load spammed domains: {e}")
    return set()


def _unlearn_spammed_sender(sender_email: str) -> None:
    """Retire un expéditeur de la liste d'apprentissage spam du compte courant."""
    try:
        current = _get_current_account_for_user()
        if not current:
            return
        from app.multi_accounts import get_account_manager, AccountManager
        clean_email = AccountManager._extract_email(sender_email)
        if not clean_email:
            return
        manager = get_account_manager()
        # Remove from senders list
        spammed = current.spammed_senders or []
        new_spammed = [s for s in spammed if s.lower() != clean_email]
        if len(new_spammed) != len(spammed):
            manager.update_account(current.id, spammed_senders=new_spammed)
            logger.info(f"[SPAM-LEARN] Expéditeur retiré du spam appris : {clean_email}")
        # Also remove domain if present
        if "@" in clean_email:
            domain = clean_email.split("@")[1].lower()
            spammed_domains = current.spammed_domains or []
            new_domains = [d for d in spammed_domains if d.lower() != domain]
            if len(new_domains) != len(spammed_domains):
                manager.update_account(current.id, spammed_domains=new_domains)
                logger.info(f"[SPAM-LEARN] Domaine retiré du spam appris : {domain}")
    except Exception as e:
        logger.warning(f"[SPAM-LEARN] Échec suppression spam pour {sender_email}: {e}")


# ============================================================================
# LIGHTWEIGHT RATE LIMITER (per-endpoint, in-memory)
# ============================================================================
_rate_limit_buckets = {}  # Key: endpoint_name -> {"calls": [(timestamp, ...)], "lock": Lock}
_rate_limit_global_lock = threading.Lock()


def _rate_limited(endpoint_name: str, max_calls: int = 5, window_seconds: int = 60):
    """
    Check if an endpoint has exceeded its rate limit.
    Returns (allowed: bool, retry_after: int).
    """
    from flask import current_app
    if current_app.testing:
        return True, 0
    now = _cache_time.time()
    with _rate_limit_global_lock:
        if endpoint_name not in _rate_limit_buckets:
            _rate_limit_buckets[endpoint_name] = []
        bucket = _rate_limit_buckets[endpoint_name]
        # Prune old entries
        cutoff = now - window_seconds
        _rate_limit_buckets[endpoint_name] = [t for t in bucket if t > cutoff]
        bucket = _rate_limit_buckets[endpoint_name]
        if len(bucket) >= max_calls:
            retry_after = int(bucket[0] - cutoff) + 1
            return False, retry_after
        bucket.append(now)
        return True, 0


_email_cache: OrderedDict = OrderedDict()  # Key: (account_id, folder, filter) -> {"data": response_dict, "timestamp": float}
_email_cache_lock = threading.Lock()
EMAIL_CACHE_TTL_SECONDS = 120  # Default TTL (inbox)
# Slower-changing folders get longer TTL to avoid repeated IMAP fetches
# WS new_email invalidates inbox cache on new arrivals, so 120s is safe.
_EMAIL_CACHE_TTL_BY_FOLDER: dict[str, int] = {
    "inbox": 120,  # 120 s — le WS new_email invalide le cache pour les nouveaux emails
    "sent": 180,
    "archived": 180,
    "spam": 180,
    "trash": 180,
}

# Maximum pagination offset to prevent DoS (20 pages × 50)
MAX_OFFSET = 1000


def _get_cached_email_response(folder: str, email_filter: str, limit: int, offset: int, label_email_ids: set = None, account_id: str = "", exclude_label_name: str = ""):
    """Get cached email response if fresh."""
    cache_key = (account_id, folder.lower(), email_filter)  # Exclude_label filtering happens at read time (lines below)
    with _email_cache_lock:
        entry = _email_cache.get(cache_key)
        ttl = _EMAIL_CACHE_TTL_BY_FOLDER.get(folder.lower(), EMAIL_CACHE_TTL_SECONDS)
        if entry and (_cache_time.time() - entry["timestamp"]) < ttl:
            data = entry["data"]
            # Apply label filter before pagination
            emails = data.get("emails", [])
            # Don't serve a near-empty cache (e.g. after backend restart,
            # only a couple of emails may have been synced so far).
            # Threshold is skipped when paginating (offset > 0) since the
            # user already saw a full first page.
            MIN_MEMORY_CACHE_THRESHOLD = 3
            if len(emails) < MIN_MEMORY_CACHE_THRESHOLD and offset == 0:
                return None
            if label_email_ids is not None:
                emails = [e for e in emails if str(e.get("id", "")) in label_email_ids]
                # Cache is bounded (most-recent-N inbox snapshot); the label store
                # is authoritative across the whole DB. If the cache has fewer
                # matching emails than the label store, defer to SQLite so the
                # user can paginate to the older matches the cache hasn't seen.
                if len(emails) < len(label_email_ids):
                    return None
            if exclude_label_name:
                _excl = exclude_label_name.lower()
                _pre_excl_count = len(emails)
                emails = [e for e in emails if not any(
                    lbl.get("name", "").lower() == _excl for lbl in (e.get("labels") or [])
                )]
                # If memory cache emails don't have labels yet, skip exclusion
                # (they'll be filtered client-side)
                if not emails and data.get("emails"):
                    first = data["emails"][0]
                    if not first.get("labels"):
                        emails = data.get("emails", [])
                # If exclusion removed too many emails (filtered < limit but
                # pre-filter had enough), the memory cache doesn't have enough
                # non-excluded emails. Fall through to SQLite which fetches
                # extra rows to compensate (limit * 5).
                if len(emails) - offset < limit and _pre_excl_count >= limit:
                    return None
            # Filter blocked senders
            emails = _filter_blocked_senders(emails, _get_blocked_senders_set())
            # Filter spammed senders (inbox only — spam folder must still show them)
            if folder == "inbox":
                emails = _filter_spammed_senders(emails, _get_spammed_senders_set(), _get_spammed_domains_set())
            has_more = len(emails) > offset + limit
            return {
                "count": min(limit, max(0, len(emails) - offset)),
                "offset": offset,
                "has_more": has_more,
                "filter": email_filter,
                "source": "memory_cache",
                "emails": emails[offset:offset + limit],
            }
    return None


MAX_EMAIL_CACHE_ENTRIES = 50


def _set_cached_email_response(folder: str, email_filter: str, emails: list, account_id: str = ""):
    """Cache email response with LRU eviction (OrderedDict O(1))."""
    cache_key = (account_id, folder.lower(), email_filter)  # Stores full unfiltered list; exclude_label filtered at read time
    with _email_cache_lock:
        # Move to end if updating existing key
        if cache_key in _email_cache:
            _email_cache.move_to_end(cache_key)
        elif len(_email_cache) >= MAX_EMAIL_CACHE_ENTRIES:
            _email_cache.popitem(last=False)  # O(1) eviction of oldest
        _email_cache[cache_key] = {
            "data": {"emails": emails},
            "timestamp": _cache_time.time(),
        }


def _invalidate_folder_cache(*folders: str) -> None:
    """Invalidate cache entries for specific folders. Pass no args to clear all."""
    with _email_cache_lock:
        if not folders:
            _email_cache.clear()
            return
        folder_set = {f.lower() for f in folders}
        keys_to_remove = [k for k in _email_cache if k[1] in folder_set]
        for k in keys_to_remove:
            del _email_cache[k]


# ============================================================================
# EMAIL DETAIL CACHE (for individual email fetches)
# ============================================================================
_email_detail_cache: OrderedDict = OrderedDict()  # Key: (account_id, email_id) -> {"data": email_dict, "timestamp": float}
_email_detail_cache_lock = threading.Lock()
EMAIL_DETAIL_CACHE_TTL_SECONDS = 300  # Cache for 5 minutes


def _get_cached_email_detail(email_id: str, account_id: int | None = None):
    """Get cached email detail if fresh. Uses (account_id, email_id) as key to prevent cross-user leaks."""
    if account_id is None:
        account_id = _resolve_account_id_for_user()
    cache_key = (account_id, email_id)
    with _email_detail_cache_lock:
        entry = _email_detail_cache.get(cache_key)
        if entry and (_cache_time.time() - entry["timestamp"]) < EMAIL_DETAIL_CACHE_TTL_SECONDS:
            return entry["data"]
    return None


def _set_cached_email_detail(email_id: str, email_data: dict, account_id: int | None = None):
    """Cache email detail (OrderedDict O(1) eviction). Key includes account_id for multi-user isolation."""
    if account_id is None:
        account_id = _resolve_account_id_for_user()
    cache_key = (account_id, email_id)
    with _email_detail_cache_lock:
        if cache_key in _email_detail_cache:
            _email_detail_cache.move_to_end(cache_key)
        _email_detail_cache[cache_key] = {
            "data": email_data,
            "timestamp": _cache_time.time(),
        }
        # Limit cache size (keep last 150 emails)
        if len(_email_detail_cache) > 150:
            _email_detail_cache.popitem(last=False)  # O(1) eviction of oldest


# ============================================================================
# LABEL BATCH CACHE (avoid repeated SQLite reads on every /api/emails request)
# ============================================================================
_label_batch_cache: dict = {}  # Key: (account_id, frozenset(email_ids)) -> {"data": dict, "timestamp": float}
_label_batch_cache_lock = threading.Lock()
LABEL_BATCH_CACHE_TTL = 120  # 120s — labels rarely change mid-session; WS events invalidate


def _get_label_batch_cached(email_ids: list) -> dict | None:
    """Return cached label map if fresh, else None. Key includes account_id for multi-user isolation."""
    account_id = _resolve_account_id_for_user()
    key = (account_id, frozenset(email_ids))
    with _label_batch_cache_lock:
        entry = _label_batch_cache.get(key)
        if entry and (_cache_time.time() - entry["timestamp"]) < LABEL_BATCH_CACHE_TTL:
            return entry["data"]
    return None


def _set_label_batch_cached(email_ids: list, data: dict) -> None:
    """Cache label map for the given email IDs. Key includes account_id for multi-user isolation."""
    account_id = _resolve_account_id_for_user()
    key = (account_id, frozenset(email_ids))
    with _label_batch_cache_lock:
        _label_batch_cache[key] = {"data": data, "timestamp": _cache_time.time()}
        # Evict old entries if cache grows too large (keep latest 20 batches)
        if len(_label_batch_cache) > 20:
            oldest = min(_label_batch_cache, key=lambda k: _label_batch_cache[k]["timestamp"])
            del _label_batch_cache[oldest]


def _invalidate_label_batch_cache() -> None:
    """Invalidate label batch cache (call after label assignment changes)."""
    with _label_batch_cache_lock:
        _label_batch_cache.clear()


def _cleanup_expired_caches() -> None:
    """Remove expired entries from all global caches to prevent memory creep."""
    now = _cache_time.time()
    # Email list cache
    with _email_cache_lock:
        expired = [
            k for k, v in _email_cache.items()
            if (now - v["timestamp"]) >= _EMAIL_CACHE_TTL_BY_FOLDER.get(k[1], EMAIL_CACHE_TTL_SECONDS)
        ]
        for k in expired:
            del _email_cache[k]
    # Email detail cache
    with _email_detail_cache_lock:
        expired = [
            k for k, v in _email_detail_cache.items()
            if (now - v["timestamp"]) >= EMAIL_DETAIL_CACHE_TTL_SECONDS
        ]
        for k in expired:
            del _email_detail_cache[k]
    # Label batch cache
    with _label_batch_cache_lock:
        expired = [
            k for k, v in _label_batch_cache.items()
            if (now - v["timestamp"]) >= LABEL_BATCH_CACHE_TTL
        ]
        for k in expired:
            del _label_batch_cache[k]
    # Account ID cache — RACE-008: use lock so cleanup doesn't race with readers/writers.
    with _account_id_cache_lock:
        expired_accounts = [
            k for k, v in _account_id_cache.items()
            if (now - v["timestamp"]) >= _ACCOUNT_ID_TTL
        ]
        for k in expired_accounts:
            _account_id_cache.pop(k, None)


# Periodic cleanup every 10 minutes via background thread
_cache_cleanup_timer: threading.Timer | None = None


def _schedule_cache_cleanup() -> None:
    """Schedule periodic cache cleanup (runs every 10 minutes)."""
    global _cache_cleanup_timer
    _cleanup_expired_caches()
    _cache_cleanup_timer = threading.Timer(600, _schedule_cache_cleanup)
    _cache_cleanup_timer.daemon = True
    _cache_cleanup_timer.start()


_schedule_cache_cleanup()


def _find_sent_email_in_list_cache(email_id: str, account_key: str | None = None):
    """Search in-memory list cache for a sent email by ID. Returns dict or None."""
    return _find_email_in_list_cache(email_id, folder_filter="sent", account_key=account_key)


def _find_email_in_list_cache(email_id: str, folder_filter: str | None = None, account_key: str | None = None):
    """Search in-memory list cache for any email by ID across all folders.

    Returns dict or None.

    Args:
        account_key: Cache-key form of the caller's account identifier (the
            same string passed to `_get_cached_email_response`, i.e.
            AccountConfig.id hash or `str(db_account_id)`). When provided,
            only cache entries keyed by this value are inspected — prevents
            returning another user's cached email that happens to share an
            email_id (Gmail ID overlap, same newsletter, etc.). `None` is a
            legacy unsafe path kept for non-user-facing callers; pass the
            caller's key whenever authentication context is available.
    """
    try:
        with _email_cache_lock:
            for _ck, _cv in _email_cache.items():
                if account_key is not None and _ck[0] != account_key:
                    continue
                if folder_filter and _ck[1] != folder_filter:
                    continue
                for _em in _cv.get("data", {}).get("emails", []):
                    if str(_em.get("id", "")) == email_id:
                        result = dict(_em)
                        result.setdefault("body", "")
                        result.setdefault("body_html", None)
                        result.setdefault("body_text", "")
                        result.setdefault("cc", [])
                        return result
    except Exception as e:
        logger.debug(f"Email detail lookup from conversation cache failed: {e}")
    return None


def _safe_call(fn, *args, **kwargs):
    """Call fn(*args) swallowing exceptions (for background ThreadPoolExecutor)."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Background {fn.__name__} failed: {e}")


def _detach_provider_from_request(provider):
    """Remove provider from flask.g teardown list so background threads can use it."""
    from flask import g
    providers = getattr(g, '_providers_to_close', [])
    if provider in providers:
        providers.remove(provider)


def _evict_sent_sqlite_cache() -> None:
    """Clear SQLite sent cache so next request fetches fresh from provider."""
    try:
        account_id = _resolve_account_id_cached()
        with get_db_session() as session:
            repo = EmailRepository(session)
            deleted = repo.delete_by_is_sent(account_id)
            session.commit()
            if deleted > 0:
                logger.info(f"Evicted {deleted} sent emails from SQLite after send")
    except Exception as e:
        logger.warning(f"Failed to evict sent SQLite cache: {e}")


def _purge_stale_sent_placeholders(account_id: int) -> int:
    """Delete ``compose-*`` / ``reply-*`` placeholder rows that have a real twin.

    These ids are transient — written optimistically at send-time, meant to
    be superseded by the provider-synced real-id row. The delete-rebuild in
    ``_refresh_sent_cache_bg`` normally clears them, but it early-returns on
    auth failure / empty provider responses, so placeholders leak and show
    up as duplicate Sent rows.

    A placeholder is purged only when a real (non-placeholder) ``is_sent``
    row with the same subject + recipients exists — that row is the
    authoritative synced copy (same content, plus a real id and thread_id),
    so dropping the placeholder loses nothing. We match on content rather
    than the id's timestamp because that ``<ts>`` suffix's timezone is
    inconsistent across rows (some paths used ``utcnow().timestamp()`` and
    are offset-skewed). Returns rows removed.
    """
    if not account_id or account_id <= 0:
        return 0
    try:
        from sqlalchemy import or_ as _or
        removed = 0
        with get_db_session() as session:
            placeholders = (
                session.query(Email)
                .filter(
                    Email.account_id == account_id,
                    Email.is_sent.is_(True),
                    _or(
                        Email.email_id.like("compose-%"),
                        Email.email_id.like("reply-%"),
                    ),
                )
                .all()
            )
            for ph in placeholders:
                twin = (
                    session.query(Email.id)
                    .filter(
                        Email.account_id == account_id,
                        Email.is_sent.is_(True),
                        Email.subject == ph.subject,
                        Email.recipients == ph.recipients,
                        ~Email.email_id.like("compose-%"),
                        ~Email.email_id.like("reply-%"),
                    )
                    .first()
                )
                if twin is not None:
                    session.delete(ph)
                    removed += 1
            if removed:
                session.commit()
        if removed:
            logger.info(
                "Purged %d duplicate sent placeholder row(s) for account %d",
                removed, account_id,
            )
        return removed
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Sent-placeholder purge failed for account %d: %s",
            account_id, exc,
        )
        return 0


def _refresh_sent_cache_bg(account_id: int, oauth_account_id: str, limit: int = 51) -> int:
    """Background: re-fetch sent emails from IMAP and refresh SQLite cache.

    Called when the sent cache is stale (> 5 min). Returns immediately to
    the caller (stale-while-revalidate) while this runs in the thread pool.

    Returns the count of sent emails persisted (post-skipped-misclassified
    pass) so ``_run_sync_job`` can plumb a truthful ``new_emails`` into the
    ``sync_complete`` WS event.
    """
    try:
        # Safety-net sweep first — runs even when the delete-rebuild below
        # early-returns (auth failure / 0 emails), so leaked placeholders
        # don't accumulate as duplicate Sent rows.
        _purge_stale_sent_placeholders(account_id)
        from app.providers.factory import get_pooled_provider
        if not oauth_account_id:
            logger.warning("Background sent refresh skipped without OAuth account for db account %s", account_id)
            return 0
        provider = get_pooled_provider(account_id=oauth_account_id)
        if not provider.authenticate():
            logger.warning("Background sent refresh: auth failed")
            return 0
        emails = provider.get_sent_emails(limit=limit)
        if not emails:
            logger.info("Background sent refresh: provider returned 0 emails — keeping existing cache")
            return 0
        for e in emails:
            if not str(getattr(e, 'id', '')).startswith("sent:"):
                e.id = f"sent:{e.id}"

        # Sender-vs-account guard mirror of sync_service._store_emails (2026-05-05).
        # provider.get_sent_emails() can leak received messages (Gmail label
        # propagation, IMAP shared-mailbox rules). Skip rows whose From: doesn't
        # match the account so the inbox view doesn't lose them.
        _account_addr = ""
        try:
            _account_addr = (getattr(provider, "_email", "") or "").strip().lower()
        except Exception as _addr_err:
            logger.debug(f"sent-cache refresh guard: provider._email lookup failed: {_addr_err}")

        with get_db_session() as session:
            repo = EmailRepository(session)
            # Delete only after confirming we have fresh data to replace with.
            # NOTE: this drops both synthetic ``compose-<ts>`` placeholders and
            # any existing real rows ; the loop below re-creates them from the
            # provider's authoritative Sent list. Dedup pass after the loop
            # handles the rare case where the provider itself returned the
            # same logical message twice (label propagation, conversationId
            # echo). Without the dedup we'd ship a (2) badge on a single send.
            repo.delete_by_is_sent(account_id)
            _skipped = 0
            persist_content = should_persist_email_content()
            for email_obj in emails:
                eid = str(getattr(email_obj, 'id', ''))
                raw_eid = eid[5:] if eid.startswith("sent:") else eid
                if not raw_eid:
                    continue
                _sender_raw = (getattr(email_obj, 'sender', '') or '').strip().lower()
                if "<" in _sender_raw and ">" in _sender_raw:
                    _sender_raw = _sender_raw.split("<", 1)[1].split(">", 1)[0].strip()
                if _account_addr and _sender_raw and _sender_raw != _account_addr:
                    logger.warning(
                        "Sent-cache refresh: skipping %s — sender %s != account %s",
                        raw_eid, _sender_raw, _account_addr,
                    )
                    _skipped += 1
                    continue
                existing = repo.get_by_email_id(raw_eid, account_id=account_id)
                if existing is not None:
                    logger.info(
                        "Sent-cache refresh: skipping %s — already cached for account %d as %s",
                        raw_eid,
                        account_id,
                        "sent" if getattr(existing, "is_sent", False) else "inbox",
                    )
                    _skipped += 1
                    continue
                cached_email = Email(
                    email_id=raw_eid,
                    account_id=account_id,
                    thread_id=getattr(email_obj, 'conversation_id', None),
                    subject=email_obj.subject,
                    sender=email_obj.sender,
                    sender_name=email_obj.sender_name,
                    recipients=",".join(getattr(email_obj, 'to', []) or []),
                    # Bug 2026-06-09 (liste 14:47 vs fil 18:47) : normaliser en UTC
                    # naïf — un datetime aware stocké tel quel perd son offset au
                    # round-trip SQLite et l'heure murale locale se fait ensuite
                    # re-étiqueter Z par _to_iso_utc.
                    date=to_naive_utc(getattr(email_obj, 'received_at', None)) or utc_now_naive(),
                    body_text=getattr(email_obj, 'body', None) if persist_content else None,
                    body_html=(getattr(email_obj, 'body_html', None) or None) if persist_content else None,
                    snippet=(getattr(email_obj, 'body', '')[:200] if getattr(email_obj, 'body', None) else '') if persist_content else None,
                    is_read=True,
                    is_starred=False,
                    is_sent=True,
                    attachments_meta=None,
                )
                repo.create(cached_email)
            # Dedupe content-collisions BEFORE the commit so the row count
            # logged below reflects what callers will actually see. Catches
            # provider double-sends (Gmail label propagation, Outlook
            # conversationId echo) and stale synthetic ``compose-*`` rows
            # that may have been re-inserted by a concurrent send between
            # delete_by_is_sent and the loop above.
            try:
                _dedup_removed = repo.dedupe_sent_by_content(account_id)
                if _dedup_removed:
                    logger.info(
                        "Background sent refresh: deduped %d duplicate sent rows for account %d",
                        _dedup_removed, account_id,
                    )
            except Exception as _dedup_err:
                logger.debug(f"sent dedupe pass failed: {_dedup_err}")
            session.commit()
            if _skipped:
                logger.info(
                    f"Background sent refresh: cached {len(emails) - _skipped} emails "
                    f"(skipped {_skipped} misclassified) for account {account_id}"
                )
            else:
                logger.info(f"Background sent refresh: cached {len(emails)} emails for account {account_id}")

        # Invalidate memory cache so next request gets the freshly cached data
        _invalidate_folder_cache()
        _persisted = max(0, len(emails) - _skipped)
    except Exception as e:
        logger.warning(f"Background sent cache refresh failed: {e}")
        _persisted = 0

    # Prefetch bodies for sent emails that are missing body in SQLite
    try:
        _prefetch_sent_bodies(account_id, limit=50)
    except Exception as e:
        logger.warning(f"Background sent body prefetch failed: {e}")
    return _persisted


def _prefetch_sent_bodies(account_id: int, limit: int = 15) -> None:
    """Batch-fetch bodies for recent sent emails missing body in SQLite.

    Opens 1 standalone IMAP connection and fetches all missing bodies in a single
    UID FETCH command (~5-8s total in background, invisible to user).
    """
    if not should_persist_email_content():
        logger.debug("Sent body prefetch skipped in metadata-only mode")
        return

    # Find sent emails with no body in SQLite
    missing_uids = []
    try:
        with get_db_session() as session:
            repo = EmailRepository(session)
            sent_emails = repo.get_sent_emails(account_id, limit=limit)
            if not sent_emails:
                return
            for db_email in sent_emails:
                body_ready = (
                    db_email.body_text
                    and db_email.body_html is not None
                    and db_email.body_html != ""
                )
                if not body_ready:
                    missing_uids.append(db_email.email_id)
    except Exception as e:
        logger.debug(f"Sent body prefetch: error reading SQLite: {e}")
        return

    if not missing_uids:
        logger.debug("Sent body prefetch: all recent sent emails have bodies")
        return

    logger.info(f"Sent body prefetch: {len(missing_uids)} emails missing body, fetching...")

    try:
        from app.providers.factory import get_pooled_provider as _get_pp_prefetch
        oauth_account_id = _resolve_oauth_account_id_for_db_account(account_id)
        if not oauth_account_id:
            logger.warning(
                "Sent body prefetch: no OAuth account for db account %s — skipping",
                account_id,
            )
            return
        provider = _get_pp_prefetch(account_id=oauth_account_id)
        if hasattr(provider, "authenticate") and not provider.authenticate():
            logger.debug("Sent body prefetch: provider auth failed for account %s", account_id)
            return

        fetched_count = 0
        for uid in missing_uids:
            try:
                std_email = provider.get_message_by_id(uid)
                if not std_email:
                    continue
                body_text = getattr(std_email, 'body', None) or ''
                body_html = getattr(std_email, 'body_html', None) or ''
                if not body_text and not body_html:
                    continue

                # Persist to SQLite
                with get_db_session() as session:
                    repo = EmailRepository(session)
                    db_email = repo.get_by_email_id(uid, account_id=account_id)
                    if db_email:
                        updated = False
                        if not db_email.body_text and body_text:
                            db_email.body_text = body_text
                            updated = True
                        if (db_email.body_html is None or db_email.body_html == "") and body_html:
                            db_email.body_html = body_html
                            updated = True
                        if not db_email.snippet and body_text:
                            db_email.snippet = body_text[:200]
                            updated = True
                        if updated:
                            session.commit()
                            fetched_count += 1
            except Exception as parse_err:
                logger.debug(f"Sent body prefetch: error for UID {uid}: {parse_err}")
                continue

        logger.info(f"Sent body prefetch: persisted {fetched_count}/{len(missing_uids)} bodies")
    except Exception as e:
        logger.warning(f"Sent body prefetch: failed: {e}")


def _resolve_folder_for_provider(provider, folder: str) -> str:
    """Map logical folder name to provider-native folder ID.

    - Outlook (Graph API): well-known folder names (inbox, junkemail, deleteditems…)
    - Gmail (API): label IDs (INBOX, SPAM, TRASH…)
    - IMAP: try provider.resolve_folder_name(), fallback to [Gmail]/ names.
    """
    _OUTLOOK_FOLDERS = {
        "inbox": "inbox", "sent": "sentitems", "archived": "archive",
        "spam": "junkemail", "trash": "deleteditems", "draft": "drafts",
    }
    _GMAIL_LABELS = {
        "inbox": "INBOX", "sent": "[Gmail]/Sent Mail", "archived": "[Gmail]/All Mail",
        "spam": "[Gmail]/Spam", "trash": "[Gmail]/Trash", "draft": "[Gmail]/Drafts",
    }

    provider_name = getattr(provider, 'PROVIDER_NAME', '')
    if provider_name == 'outlook':
        return _OUTLOOK_FOLDERS.get(folder, folder)
    if provider_name == 'gmail':
        return _GMAIL_LABELS.get(folder, folder)

    # IMAP: try resolve_folder_name, then detect host for correct fallback
    if hasattr(provider, 'resolve_folder_name'):
        try:
            resolved = provider.resolve_folder_name(folder)
            if resolved:
                return resolved
        except Exception as e:
            logger.debug(f"IMAP resolve_folder_name failed for '{folder}': {e}")

    # Fallback: pick correct folder names based on IMAP host
    _imap_host = getattr(provider, 'host', '') or ''
    if 'gmail' in _imap_host.lower():
        return _GMAIL_LABELS.get(folder, folder)

    # Outlook/Hotmail/generic IMAP fallback
    _IMAP_FOLDERS = {
        "inbox": "INBOX", "sent": "Sent Items", "archived": "Archive",
        "spam": "Junk", "trash": "Deleted Items", "draft": "Drafts",
    }
    return _IMAP_FOLDERS.get(folder, folder)


# --- Per-(account, folder) outcome of the last completed secondary-folder
# refresh. An empty SQLite cache is otherwise indistinguishable from a
# never-synced folder, so /api/emails answered `sync_in_progress: true`
# forever for a genuinely empty Trash/Spam (or one whose refresh silently
# fails) and the frontend skeleton never terminated (bug "les onglets
# Corbeille/Indésirables ne s'ouvrent pas", 2026-06-09). In-memory on
# purpose: same lifetime/worker assumptions as the sync debounce dict.
SECONDARY_SYNC_FOLDERS = ("trash", "spam", "archived")
_folder_sync_outcome_lock = threading.Lock()
_folder_sync_outcomes: dict = {}


def record_folder_sync_outcome(account_id: int, folder: str, ok: bool) -> None:
    """Record the terminal outcome of a secondary-folder background refresh."""
    if not isinstance(account_id, int) or account_id <= 0:
        return
    if folder not in SECONDARY_SYNC_FOLDERS:
        return
    with _folder_sync_outcome_lock:
        _folder_sync_outcomes[(account_id, folder)] = {
            "ok": bool(ok),
            "timestamp": _cache_time.time(),
        }


def get_folder_sync_outcome(account_id: int, folder: str):
    """Latest completed refresh outcome for (account, folder), or None."""
    with _folder_sync_outcome_lock:
        outcome = _folder_sync_outcomes.get((account_id, folder))
        return dict(outcome) if outcome else None


def clear_folder_sync_outcome(account_id: int, folder: str) -> None:
    """Forget the recorded outcome so a user-requested retry reports the NEW attempt."""
    with _folder_sync_outcome_lock:
        _folder_sync_outcomes.pop((account_id, folder), None)


def _refresh_folder_cache_bg(folder: str, account_id: int, oauth_account_id: str, limit: int = 51) -> int:
    """Background: re-fetch secondary folder emails from IMAP and refresh SQLite cache.

    Called when trash/spam/archived cache is stale. Returns immediately to the caller
    (stale-while-revalidate) while this runs in the thread pool.

    Returns the number of rows persisted (0 on auth failure / unknown folder /
    empty provider response). Used by ``_run_sync_job`` to populate the
    ``new_emails`` field of the ``sync_complete`` WS event so the FE can refresh
    the current folder view immediately instead of waiting on the 12 s
    cold-start fallback timer.

    Every exit records a success/failure outcome via
    ``record_folder_sync_outcome`` so the list route can answer with a terminal
    state (empty folder vs sync error) instead of `sync_in_progress` forever.
    """
    if folder not in SECONDARY_SYNC_FOLDERS:
        logger.warning(f"Background {folder} refresh: unknown folder — skipping")
        return 0

    try:
        from app.providers.factory import get_pooled_provider
        if not oauth_account_id:
            logger.warning("Background %s refresh skipped without OAuth account for db account %s", folder, account_id)
            record_folder_sync_outcome(account_id, folder, ok=False)
            return 0
        provider = get_pooled_provider(account_id=oauth_account_id)
        if not provider.authenticate():
            logger.warning(f"Background {folder} refresh: auth failed")
            record_folder_sync_outcome(account_id, folder, ok=False)
            return 0

        # Provider-aware folder resolution (handles Gmail, Outlook, IMAP)
        resolved_folder = _resolve_folder_for_provider(provider, folder)

        if hasattr(provider, 'get_message_headers'):
            emails = provider.get_message_headers(limit=limit, unread_only=False, folder=resolved_folder)
        else:
            emails = provider.get_messages(limit=limit, unread_only=False, folder=resolved_folder)

        if not emails:
            logger.info(f"Background {folder} refresh: provider returned 0 emails — keeping existing cache")
            record_folder_sync_outcome(account_id, folder, ok=True)
            return 0

        with get_db_session() as session:
            repo = EmailRepository(session)
            repo.delete_by_folder(account_id, folder)
            persist_content = should_persist_email_content()
            for email_obj in emails:
                eid = str(getattr(email_obj, 'id', ''))
                if not eid:
                    continue
                cached_email = Email(
                    email_id=eid,
                    account_id=account_id,
                    thread_id=getattr(email_obj, 'conversation_id', None),
                    subject=email_obj.subject,
                    sender=email_obj.sender,
                    sender_name=email_obj.sender_name,
                    recipients=",".join(getattr(email_obj, 'to', []) or []),
                    # Bug 2026-06-09 (liste 14:47 vs fil 18:47) : normaliser en UTC
                    # naïf — un datetime aware stocké tel quel perd son offset au
                    # round-trip SQLite et l'heure murale locale se fait ensuite
                    # re-étiqueter Z par _to_iso_utc.
                    date=to_naive_utc(getattr(email_obj, 'received_at', None)) or utc_now_naive(),
                    body_text=getattr(email_obj, 'body', None) if persist_content else None,
                    body_html=(getattr(email_obj, 'body_html', None) or None) if persist_content else None,
                    snippet=(getattr(email_obj, 'body', '')[:200] if getattr(email_obj, 'body', None) else '') if persist_content else None,
                    is_read=getattr(email_obj, 'is_read', True),
                    is_starred=getattr(email_obj, 'is_starred', False),
                    is_sent=False,
                    folder=folder,
                    attachments_meta=None,
                )
                try:
                    repo.create(cached_email)
                except Exception as e:
                    logger.debug(f"SQLite cache insert skipped (likely duplicate): {e}")
            session.commit()
            logger.info(f"Background {folder} refresh: cached {len(emails)} emails for account {account_id}")

        _invalidate_folder_cache()
        record_folder_sync_outcome(account_id, folder, ok=True)
        return len(emails)
    except Exception as e:
        logger.warning(f"Background {folder} cache refresh failed: {e}")
        record_folder_sync_outcome(account_id, folder, ok=False)
        return 0


def _evict_email_from_all_caches(
    email_id: str,
    move_to_folder: str | None = None,
    account_id: int | None = None,
) -> None:
    """Remove an email from in-memory cache, detail cache, and SQLite cache.

    If move_to_folder is provided, the email is moved to that folder in SQLite
    instead of being deleted (so the target folder cache stays accurate).

    Audit 2026-04-25 (HIGH-Iso-3): account_id parameter so the SQLite mutation
    only touches rows owned by the caller. None preserves legacy single-tenant
    behavior; new callers should always pass it.
    """
    # In-memory list cache
    _invalidate_folder_cache()  # Clear all folders — email removed entirely
    _invalidate_label_batch_cache()  # Clear label batch cache
    # In-memory detail cache
    with _email_detail_cache_lock:
        _email_detail_cache.pop(str(email_id), None)

    # Capture account_id for the closure — at request time we still have a
    # context; resolve it now so the bg thread doesn't need it.
    _bg_aid = account_id
    if _bg_aid is None:
        try:
            from flask import has_request_context
            if has_request_context():
                _bg_aid = _resolve_account_id_for_user()
        except Exception:
            _bg_aid = None

    # SQLite cache — submit to bounded thread pool instead of an unbounded
    # daemon thread (audit Reply-HIGH-2 "_evict daemon thread bypasses pool").
    def _bg_evict_sqlite():
        try:
            with get_db_session() as session:
                repo = EmailRepository(session)
                if move_to_folder:
                    updated = repo.update_folder_by_email_id(
                        str(email_id), move_to_folder, account_id=_bg_aid,
                    )
                    if updated:
                        logger.debug(f"SQLite: moved {_sanitize_for_log(email_id)} → folder='{move_to_folder}'")
                    else:
                        logger.debug(f"SQLite: {_sanitize_for_log(email_id)} not cached — skip folder move to '{move_to_folder}'")
                else:
                    repo.delete_by_email_id(str(email_id), account_id=_bg_aid)
                session.commit()
        except Exception as _e:
            logger.warning(f"_evict_email_from_all_caches failed for {_sanitize_for_log(email_id)}: {_e}")
    submit_background(_bg_evict_sqlite)


# Security: Email ID validation pattern (alphanumeric, dash, underscore, common chars)
EMAIL_ID_MAX_LENGTH = 256
EMAIL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-@.+:=]+$")


# ============================================================================
# HELPERS
# ============================================================================

def require_json() -> tuple:
    """
    Récupère et valide les données JSON du body de la requête.

    Returns:
        Tuple (data, error_response) où error_response est None si OK,
        sinon un tuple (response, status_code).
    """
    # silent=True so a missing/non-JSON body returns a clean 400 instead of
    # raising werkzeug's BadRequest/UnsupportedMediaType — which, when this
    # helper is called inside a handler's try/except, gets re-wrapped as a 500
    # that leaks the exception string (audit 2026-05-19 STAB-02).
    data = request.get_json(silent=True)
    if not data:
        return None, (jsonify({"error": "JSON body required"}), 400)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "JSON body must be an object"}), 400)
    return data, None


def _get_container():
    """Retourne le container DI global."""
    return get_container()


def _filter_self_sent_drafts(drafts: list) -> list:
    """Exclut les pending drafts dont l'expéditeur est l'utilisateur lui-même.

    ISO-13 fix: scope to the JWT/loopback caller. Previously used
    `accounts[0].email` which would filter user B's drafts using user A's
    own-email, hiding/showing the wrong items.
    """
    try:
        account = _get_current_account_for_user()
        own_email = (getattr(account, "email", "") or "").lower().strip()
        if not own_email:
            return drafts
        return [d for d in drafts if (d.email_sender or "").lower().strip() != own_email]
    except Exception as e:
        logger.debug(f"Filter own-email from drafts failed: {e}")
        return drafts


def _auto_archive_if_action(provider, email_id: str) -> None:
    """Archive l'email si auto_archive_action est activé et l'email a le label Action."""
    try:
        from app.api.settings import load_settings
        settings = load_settings()
        if not settings.get("auto_archive_action", False):
            return

        label_store = _get_container().get_label_store()
        assignment = label_store.get_assignment(email_id)
        if not assignment or "Action" not in assignment.labels:
            return

        if hasattr(provider, "archive_email"):
            provider.archive_email(email_id)
            _invalidate_folder_cache("inbox")
            logger.info(f"Auto-archived Action email: {_sanitize_for_log(email_id)}")
            try:
                from app.draft_quality_tracker import get_tracker
                get_tracker().record_feature("auto_archive_action")
            except Exception as _trk_err:
                logger.debug(f"Time-saved tracking (auto_archive_action) suppressed: {_trk_err}")
    except Exception as e:
        logger.warning(f"Auto-archive failed for {_sanitize_for_log(email_id)}: {e}")


def _get_authenticated_provider():
    """
    Retourne un provider email authentifié.

    Uses the current OAuth account if available, otherwise falls back
    to environment-based configuration.

    The provider is stored in flask.g and automatically disconnected
    at the end of the request via teardown_appcontext.

    Returns:
        Le provider email si l'authentification réussit.

    Raises:
        Abort 401 si l'authentification échoue.
    """
    from flask import g
    from app.multi_accounts import create_provider_for_account

    if os.getenv("AGENTYS_MOCK_EMAIL_PROVIDER", "").strip().lower() in {"1", "true", "yes", "on"}:
        from app.providers.mock_load_provider import LoadTestEmailProvider

        provider = LoadTestEmailProvider()
        if not hasattr(g, '_providers_to_close'):
            g._providers_to_close = []
        g._providers_to_close.append(provider)
        return provider

    # Try to use the current OAuth account (JWT-aware)
    current_account = _get_current_account_for_user()

    if current_account:
        try:
            provider = create_provider_for_account(current_account)
            if provider.authenticate():
                # Track for auto-disconnect at end of request
                if not hasattr(g, '_providers_to_close'):
                    g._providers_to_close = []
                g._providers_to_close.append(provider)
                return provider
            logger.warning(f"OAuth account {current_account.id} auth failed")
            if _is_web_request_context():
                abort(503, description="Email provider authentication failed")
        except Exception as e:
            logger.warning(f"OAuth provider creation failed: {e}")
            if _is_web_request_context():
                abort(503, description="Email provider authentication failed")

    if _is_web_request_context():
        abort(401, description="No email account configured for authenticated user")

    # Fallback to legacy environment-based provider
    try:
        provider = LegacyModuleLoader.email_provider()
    except Exception as e:
        logger.warning(f"Legacy provider creation failed: {e}")
        abort(503, description="No email provider configured")
    if not provider.authenticate():
        abort(503, description="Email provider authentication failed")
    # Track for auto-disconnect at end of request
    from flask import g
    if not hasattr(g, '_providers_to_close'):
        g._providers_to_close = []
    g._providers_to_close.append(provider)
    return provider


def _is_web_request_context() -> bool:
    """True when legacy env fallback would cross tenant boundaries.

    In remote/JWT-served requests, falling back to the process-global/env
    provider can use another customer's mailbox. The fallback is kept only for
    trusted loopback/Tauri or out-of-request legacy jobs.
    """
    from flask import has_request_context
    if not has_request_context():
        return False
    auth_user = getattr(g, 'auth_user', None)
    if auth_user:
        return True
    return not is_trusted_loopback()


def _validate_email_id(email_id: str) -> bool:
    """
    Valide le format d'un email ID.

    Security: Empêche les injections et limite la taille.

    Args:
        email_id: L'ID de l'email à valider.

    Returns:
        True si l'ID est valide, False sinon.
    """
    if not email_id or not isinstance(email_id, str):
        return False
    if len(email_id) > EMAIL_ID_MAX_LENGTH:
        return False
    return bool(EMAIL_ID_PATTERN.match(email_id))


def _sanitize_for_log(value: str, max_length: int = 100) -> str:
    """
    Sanitize une valeur pour le logging.

    Security: Empêche les log injection attacks.

    Args:
        value: La valeur à sanitizer.
        max_length: Longueur maximale de sortie.

    Returns:
        Valeur sanitizée pour les logs.
    """
    if not value:
        return "<empty>"
    # Remove control characters and limit length
    sanitized = "".join(c if c.isprintable() else "?" for c in str(value)[:max_length])
    return sanitized


def _get_email_by_id(provider, email_id: str, account_id: int | None = None):
    """
    Récupère un email par son ID — scoped to the caller's account.

    Args:
        provider: Le provider email authentifié (already bound to caller's mailbox).
        email_id: L'ID de l'email à récupérer.
        account_id: DB account ID of the caller. If None, resolves from the JWT
            via `_resolve_account_id_for_user()`. Every SQLite/cache fallback
            is filtered by this ID, preventing another tenant's email from
            leaking when two accounts happen to share a provider email_id.
            Only the provider fetch path is inherently scoped (provider is
            authenticated to the caller's mailbox).

    Returns:
        L'email correspondant à l'ID.

    Raises:
        Abort 400 si l'ID est invalide.
        Abort 404 si l'email n'est pas trouvé OU appartient à un autre tenant.
    """
    # Strip "sent:" prefix — providers and cache use plain IDs
    lookup_id = email_id[5:] if email_id.startswith("sent:") else email_id

    if not _validate_email_id(lookup_id):
        abort(400, description="Invalid email_id format")

    # Resolve the caller's account context once. `-1` sentinel on JWT miss
    # propagates into every WHERE clause below, returning zero SQLite rows.
    if account_id is None:
        account_id = _resolve_account_id_for_user()

    # `account_key` mirrors the string form used as cache key[0] when the
    # email list was populated (AccountConfig.id hash, or str(db_id) fallback).
    # Cache writers are in routes_emails.py:589 / :1146 — see `oauth_account_id`.
    try:
        _current = _get_current_account_for_user()
    except Exception:
        _current = None
    account_key: str | None
    if _current and getattr(_current, "id", None):
        account_key = str(_current.id)
    elif account_id is not None and account_id != _NO_ACCOUNT_SENTINEL:
        account_key = str(account_id)
    else:
        account_key = None

    # BUG-003 fix: if a numeric DB primary key was sent instead of the hash email_id,
    # resolve it to the correct email_id via SQLite before doing any further lookups.
    # MUST be account-scoped — without the filter, a numeric ID from user A could
    # resolve to user B's hash email_id and leak the wrong email.
    if lookup_id.isdigit():
        try:
            from sqlalchemy import select as _sa_select
            from app.db.models.email import Email as _EmailModel
            with get_db_session() as _s:
                _stmt = _sa_select(_EmailModel).where(_EmailModel.id == int(lookup_id))
                if account_id is not None:
                    _stmt = _stmt.where(_EmailModel.account_id == account_id)
                _row = _s.execute(_stmt).scalar_one_or_none()
                if _row is not None and getattr(_row, "email_id", None):
                    logger.warning(
                        f"BUG-003: numeric DB PK '{lookup_id}' received for /process — "
                        f"resolving to hash email_id '{_row.email_id}'"
                    )
                    lookup_id = _row.email_id
        except Exception as _resolve_err:
            logger.debug(f"Numeric ID resolution failed for '{lookup_id}': {_resolve_err}")

    # BUG-G001 telemetry: track which fallback layer resolves (or none)
    _lookup_trace: list[str] = []

    # Try SQLite cache first (instant, covers [Gmail]/All Mail emails)
    email = _get_email_from_cache(lookup_id, account_id=account_id)
    if email:
        _lookup_trace.append("sqlite_cache:hit")
    else:
        _lookup_trace.append("sqlite_cache:miss")
        # Fallback: fetch from IMAP provider (slower). Provider is authenticated
        # to the caller's mailbox, so this path is inherently account-scoped.
        try:
            email = provider.get_message_by_id(lookup_id)
            _lookup_trace.append("provider:hit" if email else "provider:miss")
        except HTTPException:
            raise
        except Exception as e:
            if getattr(e, "code", None) == "GMAIL_QUOTA_BACKOFF":
                raise
            logger.warning(f"Provider error fetching email {lookup_id}: {e}")
            _lookup_trace.append(f"provider:err({type(e).__name__})")
            email = None
    if not email:
        # Last resort: build a minimal email from SQLite headers even without body.
        # This avoids a 404 when the email was cached via header-only IMAP fetch
        # but the provider is temporarily unreachable (common in dev/staging).
        email = _get_email_from_cache(lookup_id, account_id=account_id, allow_bodyless=True)
        _lookup_trace.append("bodyless:hit" if email else "bodyless:miss")
    if not email:
        # Ultra last resort: check in-memory list cache.
        # Race condition: _save_headers_to_sqlite background task may not have run yet
        # when /process is called immediately after the email list is loaded.
        # Also handles emails that have been archived/moved since the list was fetched.
        email = _get_email_from_memory_list_cache(lookup_id, account_key=account_key)
        _lookup_trace.append("memcache:hit" if email else "memcache:miss")
    if not email:
        # BUG-G001 fix (5th fallback): direct SQLite query by email_id column,
        # bypassing the in-memory cache TTL. Handles long QA sessions or
        # deployments where the email cache has expired. MUST be account-scoped.
        try:
            from sqlalchemy import select as _sa_sel5
            from app.db.models.email import Email as _EmailModel5
            from app.db.database import get_db_session as _gds5
            with _gds5() as _s5:
                _stmt5 = _sa_sel5(_EmailModel5).where(_EmailModel5.email_id == lookup_id)
                if account_id is not None:
                    _stmt5 = _stmt5.where(_EmailModel5.account_id == account_id)
                _row5 = _s5.execute(_stmt5).scalar_one_or_none()
                if _row5:
                    from app.interfaces.email_provider import StandardEmail as _SE5
                    logger.warning(
                        f"BUG-G001 fallback: email {lookup_id!r} found via direct SQLite query "
                        f"(all cache layers missed — likely cache expiry or long session)"
                    )
                    email = _SE5(
                        id=_row5.email_id or lookup_id,
                        sender=_row5.sender or "",
                        sender_name=getattr(_row5, "sender_name", None),
                        to=getattr(_row5, "to_addresses", None) or [],
                        subject=_row5.subject or "",
                        body=_row5.body_text or _row5.snippet or "",
                        body_html=getattr(_row5, "body_html", None),
                        received_at=_row5.date,
                        is_read=bool(_row5.is_read),
                        has_attachments=bool(getattr(_row5, "attachments_meta", None)),
                        conversation_id=getattr(_row5, "conversation_id", None),
                        provider_source="sqlite_direct",
                    )
                    _lookup_trace.append("sqlite_direct:hit")
                else:
                    _lookup_trace.append("sqlite_direct:miss")
        except Exception as _fb5_err:
            logger.debug(f"BUG-G001 5th fallback failed for {lookup_id!r}: {_fb5_err}")
            _lookup_trace.append(f"sqlite_direct:err({type(_fb5_err).__name__})")
    if not email:
        logger.warning(
            f"Email introuvable après 5 tentatives — id={lookup_id!r} trace={_lookup_trace}"
        )
        from flask import jsonify, make_response
        resp = make_response(jsonify({
            "error": "Email not found",
            "error_code": "EMAIL_NOT_FOUND",
            "email_id": lookup_id,
            "retryable": False,
        }), 404)
        abort(resp)
    return email


def _get_email_from_memory_list_cache(email_id: str, account_key: str | None = None):
    """Reconstruit un StandardEmail depuis le cache mémoire de la liste des emails.

    Utilisé en dernier recours quand SQLite et IMAP échouent (race condition
    _save_headers_to_sqlite pas encore terminé, ou email archivé/déplacé).

    Retourne un StandardEmail avec les métadonnées disponibles (sans body complet),
    ce qui permet au pipeline de démarrer et à l'IA de générer un brouillon.

    Args:
        account_key: Cache-key form of the caller's account identifier. Only
            cache entries whose key[0] matches are searched. Prevents returning
            another user's cached email on email_id collisions.
    """
    try:
        from app.interfaces.email_provider import StandardEmail

        # Scan in-memory cache entries scoped to this user's account
        with _email_cache_lock:
            if account_key is None:
                all_entries = list(_email_cache.values())
            else:
                all_entries = [v for k, v in _email_cache.items() if k[0] == account_key]

        for entry in all_entries:
            emails_list = entry.get("data", {}).get("emails", [])
            for email_dict in emails_list:
                # Match on either 'id' (hash) or 'email_id' (some adapters use this field name)
                dict_id = str(email_dict.get("id", "") or email_dict.get("email_id", ""))
                if dict_id == email_id:
                    # Found in memory cache — reconstruct StandardEmail
                    received_raw = email_dict.get("received_at", "")
                    received_at = None
                    if received_raw:
                        try:
                            from datetime import datetime as _dt
                            received_at = _dt.fromisoformat(received_raw.replace("Z", "+00:00"))
                        except Exception:
                            pass

                    # Use body_preview as a minimal body (first 200 chars — better than nothing)
                    body_preview = email_dict.get("body_preview") or ""

                    std_email = StandardEmail(
                        id=email_id,
                        sender=email_dict.get("sender", ""),
                        sender_name=email_dict.get("sender_name"),
                        to=email_dict.get("to") or [],
                        subject=email_dict.get("subject", ""),
                        body=body_preview,  # Partial body — pipeline will still run
                        body_html=None,
                        received_at=received_at,
                        is_read=email_dict.get("is_read", False),
                        has_attachments=email_dict.get("has_attachments", False),
                        conversation_id=email_dict.get("conversation_id"),
                        provider_source="memory_cache",
                    )
                    logger.warning(
                        f"[get_email_by_id] Email {email_id} served from memory list cache "
                        f"(SQLite+IMAP miss) — body may be truncated to preview"
                    )
                    return std_email

        # Also check the email detail cache (full body if available).
        # Canonical key format is (account_id, email_id) — but historically some
        # writers (e.g. background body fetch in routes_emails.py) used a bare
        # email_id string as the key. Skip anything that isn't a 2-tuple rather
        # than crashing the whole lookup with ValueError: too many values to unpack.
        # Bare-string keys are legacy / cross-tenant-unsafe: only trust them when
        # the caller passed no account_key (single-user / Tauri path).
        detail_dict = None
        with _email_detail_cache_lock:
            for key, entry in _email_detail_cache.items():
                if isinstance(key, tuple) and len(key) == 2:
                    if account_key is not None and str(key[0]) != account_key:
                        continue
                    eid = key[1]
                elif isinstance(key, str):
                    if account_key is not None:
                        # Skip untagged legacy keys when account scoping is enforced
                        continue
                    eid = key
                else:
                    continue
                if eid != email_id:
                    continue
                if (_cache_time.time() - entry.get("timestamp", 0)) < EMAIL_DETAIL_CACHE_TTL_SECONDS:
                    detail_dict = entry.get("data", {})
                break
        if detail_dict:
            email_dict = detail_dict
            received_raw = email_dict.get("received_at", "")
            received_at = None
            if received_raw:
                try:
                    from datetime import datetime as _dt
                    received_at = _dt.fromisoformat(received_raw.replace("Z", "+00:00"))
                except Exception:
                    pass
            body = email_dict.get("body") or email_dict.get("body_text") or ""
            body_html = email_dict.get("body_html")
            std_email = StandardEmail(
                id=email_id,
                sender=email_dict.get("sender", ""),
                sender_name=email_dict.get("sender_name"),
                to=email_dict.get("to") or [],
                subject=email_dict.get("subject", ""),
                body=body,
                body_html=body_html,
                received_at=received_at,
                is_read=email_dict.get("is_read", False),
                has_attachments=email_dict.get("has_attachments", False),
                conversation_id=email_dict.get("conversation_id"),
                provider_source="detail_cache",
            )
            logger.info(f"[get_email_by_id] Email {email_id} served from detail cache (SQLite+IMAP miss)")
            return std_email

        return None
    except Exception as e:
        logger.error(f"[get_email_by_id] Memory cache fallback failed for {email_id}: {e}", exc_info=True)
        return None


def _extract_text_from_html(html: str) -> str:
    """Extract plain text from HTML content (for cache fallback when body_text is empty)."""
    if not html:
        return ""
    import re
    import html as html_module
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html_module.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()


def _get_email_from_cache(email_id: str, account_id: int, allow_bodyless: bool = False):
    """Build a StandardEmail from SQLite cache if available — scoped to the caller's account.

    Returns cached email when body_text or body_html exists.
    Serves partial data (body_text without body_html) to avoid triggering
    expensive provider fetches — body_html is populated by background prefetch.

    Args:
        email_id: Provider's unique message ID.
        account_id: DB account ID of the authenticated caller. SQLite row is
            only returned when its `account_id` matches — prevents cross-tenant
            leaks when two accounts happen to share an `email_id`. Pass
            `_NO_ACCOUNT_SENTINEL` (-1) to force an empty result.
        allow_bodyless: If True, return the email even with no body content
            (headers-only). Used as a last-resort fallback when the provider
            is unreachable, to avoid a spurious 404 on /process.
    """
    try:
        from app.interfaces.email_provider import StandardEmail
        with get_db_session() as session:
            repo = EmailRepository(session)
            cached = repo.get_by_email_id(email_id, account_id=account_id)
            if not cached:
                return None
            # Need at least some body content to serve from cache,
            # unless allow_bodyless=True (last-resort fallback).
            if not cached.body_text and not cached.body_html:
                if not allow_bodyless:
                    return None
                logger.info(
                    "Serving header-only cache for email %s — body unavailable; "
                    "continuing with cached metadata",
                    _sanitize_for_log(email_id),
                )
            body = cached.body_text or _extract_text_from_html(cached.body_html)
            body_html = cached.body_html if cached.body_html else None
            # Parse attachment metadata if available
            _attachments = []
            if cached.attachments_meta:
                try:
                    import json as _json
                    _att_parsed = _json.loads(cached.attachments_meta)
                    if _att_parsed and any(a.get("filename") for a in _att_parsed):
                        _attachments = _att_parsed
                except Exception as e:
                    logger.debug(f"Failed to parse attachment metadata JSON: {e}")
            email_obj = StandardEmail(
                id=cached.email_id,
                sender=cached.sender or "",
                sender_name=cached.sender_name,
                to=[r.strip() for r in cached.recipients.split(",") if r.strip()] if cached.recipients else [],
                subject=cached.subject or "",
                body=body,
                body_html=body_html,
                received_at=cached.date,
                is_read=cached.is_read or False,
                has_attachments=bool(_attachments),
                attachments=_attachments,
                conversation_id=cached.thread_id,
                provider_source="cache",
            )
            return email_obj
    except Exception as e:
        logger.error(f"Cache fallback failed for email {email_id}: {e}", exc_info=True)
        return None


def _validate_limit(
    min_limit: int,
    max_limit: int,
    default_limit: int
) -> tuple:
    """
    Valide le paramètre 'limit' de la query string.

    Security: Empêche les DoS par resource exhaustion.

    Args:
        min_limit: Valeur minimale autorisée.
        max_limit: Valeur maximale autorisée.
        default_limit: Valeur par défaut si non spécifié.

    Returns:
        Tuple (limit, error_response) où error_response est None si OK,
        sinon un tuple (response, status_code).
    """
    limit_str = request.args.get("limit")
    if limit_str is None:
        return default_limit, None

    try:
        limit = int(limit_str)
    except ValueError:
        return None, (jsonify({"error": "Limit must be a valid integer"}), 400)

    if limit < min_limit or limit > max_limit:
        return None, (jsonify({
            "error": f"Limit must be between {min_limit} and {max_limit}"
        }), 400)

    return limit, None


def _invalid_tone_response():
    """
    Génère une réponse d'erreur pour un tone invalide.

    Returns:
        Tuple (response, status_code) pour une erreur 400.
    """
    valid_tones = [t.value for t in DraftInputTone]
    return jsonify({
        "error": f"Invalid tone. Must be one of: {', '.join(valid_tones)}"
    }), 400


def _validate_optional_string(value, field_name: str, max_length: int) -> tuple:
    """
    Valide un champ string optionnel.

    Security: Vérifie le type et la longueur pour prévenir DoS/injection.

    Args:
        value: La valeur à valider (peut être None).
        field_name: Nom du champ pour le message d'erreur.
        max_length: Longueur maximale autorisée.

    Returns:
        Tuple (is_valid, error_response) où error_response est None si OK,
        sinon un tuple (response, status_code).
    """
    if value is None:
        return True, None

    if not isinstance(value, str):
        return False, (jsonify({"error": f"{field_name} must be a string"}), 400)

    if len(value) > max_length:
        return False, (jsonify({
            "error": f"{field_name} exceeds maximum length of {max_length} characters"
        }), 400)

    return True, None


def _create_draft_and_mark_read_no_bg(
    provider, email, subject: str, body: str,
    to: list[str] | None = None, cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    account_id: int | None = None,
) -> str | None:
    """Create draft only — no background mark_as_read/archive (caller handles it)."""
    from app.utils.signature import append_signature
    body_with_signature = append_signature(
        body,
        account_id=account_id if account_id is not None else _resolve_account_id_for_provider(provider),
        recipient_email=email.sender,
    )
    recipients = to if to else [email.sender]
    return provider.create_draft(
        to=recipients,
        subject=subject,
        body=body_with_signature,
        reply_to_id=email.id,
        cc=cc,
        bcc=bcc,
        is_html=True,
        attachments=attachments,
    )


def _create_draft_and_mark_read(
    provider, email, subject: str, body: str,
    to: list[str] | None = None, cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    archive: bool = False,
    account_id: int | None = None,
) -> str | None:
    """
    Crée un brouillon de réponse et marque l'email comme lu.

    Cette fonction encapsule la logique commune de création de brouillon
    suivie du marquage de l'email original comme lu en cas de succès.
    La signature du compte est automatiquement ajoutée au corps du brouillon.

    Args:
        provider: Le provider email authentifié.
        email: L'email original auquel répondre.
        subject: Le sujet du brouillon.
        body: Le corps du brouillon.
        to: Liste d'adresses destinataires (défaut: [email.sender]).
        cc: Liste d'adresses en copie (défaut: None).
        bcc: Liste d'adresses en copie cachée (défaut: None).
        attachments: Liste de tuples (filename, data, content_type) (optionnel).
        archive: Si True, archive l'email après envoi (background).

    Returns:
        L'ID du brouillon créé, ou None si échec.
    """
    # Append account signature to draft body
    from app.utils.signature import append_signature
    body_with_signature = append_signature(
        body,
        account_id=account_id if account_id is not None else _resolve_account_id_for_provider(provider),
        recipient_email=email.sender,
    )

    recipients = to if to else [email.sender]

    draft_id = provider.create_draft(
        to=recipients,
        subject=subject,
        body=body_with_signature,
        reply_to_id=email.id,
        cc=cc,
        bcc=bcc,
        is_html=True,
        attachments=attachments,
    )
    if draft_id:
        # Mark as read (+ archive) in background to avoid blocking on slow IMAP auth
        email_id = email.id
        do_archive = archive
        def _bg_imap_ops():
            try:
                provider.mark_as_read(email_id)
                if do_archive:
                    provider.archive_email(email_id)
                    logger.info(f"Background archive completed for {_sanitize_for_log(email_id)}")
            except Exception as e:
                logger.warning(f"Background IMAP ops failed: {e}")
        submit_background(_bg_imap_ops)
    return draft_id


class LegacyModuleLoader:
    """
    Gestionnaire des modules legacy restants.

    Note: La plupart des modules ont ete migres vers le Container DI.
    Il ne reste que:
    - email_provider: A migrer dans une future iteration
    - is_draft_request: Utilitaire simple

    Architecture: Ces modules seront migres vers des ports/adapters
    injectes via le Container DI dans de futures iterations.
    """

    _cache = None

    @classmethod
    def get(cls):
        """Retourne les modules legacy (singleton avec lazy loading)."""
        if cls._cache is None:
            cls._cache = cls._load_modules()
        return cls._cache

    @classmethod
    def _load_modules(cls):
        """Charge les modules legacy restants."""
        from app.providers.factory import get_pooled_provider
        from app.draft_completion import is_draft_request

        return {
            "get_email_provider": get_pooled_provider,  # Use pooled provider for connection reuse
            "is_draft_request": is_draft_request,
        }

    @classmethod
    def clear_cache(cls):
        """Vide le cache (utile pour les tests)."""
        cls._cache = None

    @classmethod
    def email_provider(cls):
        """Retourne le provider email."""
        return cls.get()["get_email_provider"]()


def _get_legacy_modules():
    """Retourne les modules legacy (compatibilite avec l'ancienne API)."""
    return LegacyModuleLoader.get()


def _find_relevant_history_for_email(email_body: str, history: list[dict]) -> list[dict]:
    """
    Cherche dans l'historique les emails pertinents par rapport aux références
    dans le body de l'email (dates, chiffres, mots-clés).

    Retourne une liste d'emails de l'historique qui semblent pertinents.
    """
    import re
    from datetime import datetime

    if not email_body or not history:
        return []

    body_lower = email_body.lower()

    # 1. Détecter les références à des dates (ex: "du 2 février", "le 3 janvier")
    mois_map = {
        "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    date_pattern = re.compile(r"(\d{1,2})\s+([\wéû]+)")
    target_dates = []
    for match in date_pattern.finditer(body_lower):
        day_str, month_str = match.group(1), match.group(2)
        if month_str in mois_map:
            try:
                day = int(day_str)
                month = mois_map[month_str]
                year = datetime.now().year
                target_dates.append(datetime(year, month, day))
            except (ValueError, OverflowError):
                pass

    # 2. Détecter les références à des chiffres
    asks_for_numbers = any(kw in body_lower for kw in ["chiffre", "nombre", "number", "digit"])

    # 3. Détecter mots-clés de référence à un email précédent
    references_previous = any(kw in body_lower for kw in [
        "email", "courriel", "message", "envoyé", "dernier", "précédent",
        "mentionné", "dit", "parlé", "écrit",
    ])

    if not target_dates and not asks_for_numbers and not references_previous:
        return []

    scored = []
    for h in history:
        h_date_str = h.get("date", "")
        h_body = h.get("body", "")
        score = 0

        # Score par correspondance de date (±3 jours)
        if target_dates and h_date_str:
            try:
                h_date = datetime.fromisoformat(h_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
                for td in target_dates:
                    delta = abs((h_date - td).days)
                    if delta <= 3:
                        score += 10 - delta  # Plus c'est proche, plus le score est élevé
            except (ValueError, TypeError):
                pass

        # Score si le body contient des chiffres et on en demande (seulement si date match)
        if asks_for_numbers and h_body and score > 0:
            if re.search(r"\d", h_body):
                score += 5

        # Exclure les emails qui posent eux-mêmes une question (pas la réponse)
        if score > 0 and h_body and h_body.rstrip().endswith("?"):
            score = 0

        if score > 0:
            scored.append((score, h))

    # Trier par score décroissant et retourner les 3 meilleurs avec score >= 7
    # Exclure les emails avec body vide (inutiles dans une réponse programmatique)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for s, h in scored if s >= 7 and h.get("body", "").strip()][:3]


# Borne du fallback IMAP de _fetch_conversation_history_for_contact —
# valeur historique d'avant #957 (le pool large est DB-only).
_IMAP_HISTORY_LIMIT = 2


def _fetch_conversation_history_for_contact(provider, sender_email: str, limit: int = 10, account_id: int = None) -> list[dict]:
    """
    Récupère l'historique des échanges avec un contact.

    DB-first: reads from local SQLite (instant, both received AND sent
    directions via `get_with_contact`). IMAP fallback only when the DB has
    nothing (rare — first-time contact never seen by the daemon yet) and is
    bounded to 3s so it cannot tank the draft pipeline P95.

    #957 Phase 1 — limit par défaut 2 → 10. Avec 2 emails toutes directions
    confondues (souvent l'entrant lui-même + un seul autre),
    `extract_sent_examples` ne trouvait presque jamais ses 2-3 exemples
    ENVOYÉS au contact : le few-shot par contact était affamé à la source.
    Élargir le pool DB n'enfle pas les prompts — les rendus bruts restent
    plafonnés côté builders (`format_conversation_history` max_emails=1-2,
    exemples few-shot cap 1000 chars). Le fallback IMAP (premier contact,
    donc de toute façon sans historique riche) reste borné à
    `_IMAP_HISTORY_LIMIT` pour ne pas allonger le budget 3 s.

    Args:
        provider: Le provider email authentifié.
        sender_email: L'adresse email du contact.
        limit: Nombre maximum d'emails à récupérer côté DB (default: 10).
        account_id: ID du compte (résolu dynamiquement si None).

    Returns:
        Liste des emails formatés pour le contexte (sender, subject, date, body).
    """
    try:
        if not provider and not sender_email:
            return []

        logger.info(f"Fetching conversation history with {sender_email}")

        _account_id = account_id if account_id is not None else _resolve_account_id_cached()

        # DB-first: includes sent emails to this contact, not just received.
        # `get_with_contact` covers sender == contact OR recipients/cc contains
        # contact, ordered by date desc — exactly what the prompt context needs.
        try:
            from app.db.database import get_db_session
            from app.db.repositories import EmailRepository
            with get_db_session() as session:
                repo = EmailRepository(session)
                cached_emails = repo.get_with_contact(
                    sender_email, account_id=_account_id, limit=limit,
                )
                if cached_emails:
                    logger.info(
                        "DB conversation history: %d emails (received+sent) with %s",
                        len(cached_emails), sender_email,
                    )
                    history = []
                    seen = set()
                    for em in cached_emails:
                        key = (em.sender or "", em.subject or "", em.date.isoformat() if em.date else "")
                        if key in seen:
                            continue
                        seen.add(key)
                        body_preview = (em.body_text or em.snippet or "")[:2000]
                        history.append({
                            "sender": em.sender or "",
                            "subject": em.subject or "",
                            "date": em.date.isoformat() if em.date else "",
                            "body": body_preview,
                        })
                    return history
        except Exception as e:
            logger.debug("DB conversation history lookup failed: %s", e)

        # Fallback: IMAP with short timeout. We only get here on first-ever
        # contact (no row in `emails` table yet) or after a DB error. 3 s is
        # an honest budget — the draft pipeline can't afford the legacy 15 s.
        if not provider:
            return []

        import concurrent.futures

        # Le pool large (#957) est réservé à la DB : sur le réseau, on garde
        # la petite borne historique pour tenir le budget 3 s.
        imap_limit = min(limit, _IMAP_HISTORY_LIMIT)

        def _imap_fetch():
            emails = []
            if hasattr(provider, 'search_emails'):
                try:
                    query = f"from:{sender_email} OR to:{sender_email}"
                    emails = provider.search_emails(query, limit=imap_limit)
                    logger.info(f"search_emails returned {len(emails)} emails")
                except Exception as e:
                    logger.warning(f"search_emails failed: {e}")

            if not emails and hasattr(provider, 'get_messages'):
                try:
                    all_emails = provider.get_messages(limit=100, unread_only=False)
                    emails = [
                        e for e in all_emails
                        if e.sender == sender_email or sender_email in (getattr(e, 'to', []) or [])
                    ][:imap_limit]
                    logger.info(f"Filtered to {len(emails)} emails with {sender_email}")
                except Exception as e:
                    logger.warning(f"get_messages fallback failed: {e}")
            return emails

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_imap_fetch)
                emails = future.result(timeout=3)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "IMAP conversation history fetch timed out after 3s for %s "
                "(DB had no history; draft will proceed without it)",
                sender_email,
            )
            return []

        if not emails:
            logger.info(f"No conversation history found with {sender_email}")
            return []

        history = []
        seen = set()
        for em in emails:
            key = (em.sender, em.subject, em.received_at.isoformat() if em.received_at else "")
            if key in seen:
                continue
            seen.add(key)
            body_preview = (em.body or "")[:2000]
            history.append({
                "sender": em.sender,
                "subject": em.subject,
                "date": em.received_at.isoformat() if em.received_at else "",
                "body": body_preview,
            })

        logger.info(f"Built conversation history with {len(history)} emails for {sender_email}")
        return history

    except Exception as e:
        logger.error(f"Failed to fetch conversation history: {e}", exc_info=True)
        return []


def _fetch_thread_context(thread_id: str | None, account_id: int | None, exclude_email_id: str | None = None) -> list[dict]:
    """
    Récupère le contexte du fil de discussion (tous les participants).

    Utilise EmailRepository.get_by_thread() pour obtenir tous les messages
    du même thread_id, puis les formate pour injection dans le prompt.

    Args:
        thread_id: ID du thread (conversation_id). Si None, retourne [].
        account_id: ID du compte email en base.
        exclude_email_id: email_id de l'email courant à exclure.

    Returns:
        Liste de dicts au format conversation_history (max 10, 1500 chars/msg).
    """
    if not thread_id or not account_id:
        return []

    try:
        from app.db.database import get_db_session
        from app.db.repositories.email_repository import EmailRepository

        with get_db_session() as session:
            repo = EmailRepository(session)
            thread_emails = repo.get_by_thread(thread_id, account_id)

        if not thread_emails:
            return []

        # Exclure l'email courant
        if exclude_email_id:
            thread_emails = [e for e in thread_emails if e.email_id != exclude_email_id]

        # Limiter aux 10 plus récents (la requête est ordonnée par date ASC)
        thread_emails = thread_emails[-10:]

        context = []
        for e in thread_emails:
            body = e.body_text or e.snippet or ""
            if len(body) > 1500:
                body = body[:1500] + "..."
            context.append({
                "sender": e.sender or "",
                "subject": e.subject or "",
                "date": str(e.date) if e.date else "",
                "body": body,
            })

        if context:
            logger.info(f"Thread context: {len(context)} messages from thread {thread_id[:20]}...")

        return context

    except Exception as e:
        logger.warning(f"Failed to fetch thread context: {e}")
        return []


_BOOKING_PATTERNS = re.compile(
    r"disponib|dispo\b|cr[eé]neau|rendez.?vous|rdv\b"
    r"|se (voir|retrouver|appeler|caller)"
    r"|call\b|meeting\b|schedule|availab"
    r"|when (are|can) you|book (a|an|time)"
    r"|plan (a|une|un)|on (se|peut) (voir|call|parler)",
    re.IGNORECASE,
)


def _is_booking_request(email) -> bool:
    """Détecte si un email demande des disponibilités/rendez-vous."""
    text = f"{email.subject or ''} {email.body or ''}"
    return bool(_BOOKING_PATTERNS.search(text))


def _build_booking_reply(sender_name: str, booking_url: str) -> str:
    """Construit la réponse template avec le lien de réservation."""
    return (
        f"Bonjour {sender_name},\n\n"
        f"Merci pour votre message. Vous pouvez réserver directement un créneau "
        f"selon mes disponibilités via ce lien :\n\n"
        f"{booking_url}\n\n"
        f"À bientôt,"
    )


def _process_email_with_use_case(email, is_cc: bool = False, include_details: bool = False, provider=None, instructions: str = "", conversation_history: list | None = None, use_streaming: bool = True, _user_email: str | None = None, _account_id: int | None = None, force: bool = False, allow_faq_auto_send: bool = True):
    """
    Traite un email avec le use case ProcessEmailUseCase.

    Utilise le Container DI pour obtenir le use case correctement câblé.
    Quand Claude est le LLM, utilise le pipeline unifié (1 appel au lieu de 4-5).
    Sinon, utilise le pipeline multi-étapes classique.

    Args:
        email: L'email à traiter (Email entity).
        is_cc: True si l'utilisateur est en copie de l'email.
        include_details: Si True, retourne aussi les détails du pipeline.
        provider: Le provider email pour récupérer l'historique (optionnel).
        conversation_history: Pre-fetched conversation history (avoids duplicate IMAP calls).

    Returns:
        Si include_details=False: Tuple (final_draft, status, classification, priority).
        Si include_details=True: Tuple (final_draft, status, classification, priority, details).
    """
    import time as _time
    from app.domain.entities import Email
    from app.agents import DrafterAgent, CriticAgent

    _t0 = _time.perf_counter()
    container = _get_container()
    from app.config import USE_CONVERSATION_HISTORY as _UCH

    # Récupérer l'historique de conversation avec le contact (si pas pré-fetché)
    if conversation_history is None:
        conversation_history = []
        if _UCH and provider and email.sender:
            conversation_history = _fetch_conversation_history_for_contact(provider, email.sender)
    if not _UCH:
        conversation_history = []
    if conversation_history:
        email_subject = email.subject or ""
        email_body_start = (email.body or "")[:100]
        conversation_history = [
            h for h in conversation_history
            if not (h.get("subject") == email_subject and h.get("body", "")[:100] == email_body_start)
        ]

    from app.smart_routing import strip_unknown_body_artifacts

    email_body = getattr(email, "body", "") or ""
    cleaned_body = strip_unknown_body_artifacts(email_body)
    if cleaned_body != email_body:
        email.body = cleaned_body
        logger.info("Draft input: stripped provider Unknown body artifact")

    # Récupérer l'email de l'utilisateur pour le few-shot learning
    # _user_email/_account_id can be pre-captured before background thread start
    if _user_email is not None:
        user_email = _user_email
    else:
        current_account = _get_current_account_for_user()
        user_email = current_account.email if current_account else ""

    # Résoudre account_id pour charger la KB d'onboarding depuis la DB
    db_account_id = _account_id if _account_id is not None else _resolve_account_id_cached()

    # Récupérer le contexte du fil de discussion (tous les participants)
    thread_id = getattr(email, 'conversation_id', None) or getattr(email, 'thread_id', None)
    if _UCH:
        thread_context = _fetch_thread_context(
            thread_id=thread_id,
            account_id=db_account_id,
            exclude_email_id=email.id,
        )
    else:
        thread_context = []
    # Dédupliquer : retirer de conversation_history les emails déjà dans thread_context
    if thread_context and conversation_history:
        thread_senders_dates = {
            (tc.get("sender", ""), tc.get("date", ""))
            for tc in thread_context
        }
        conversation_history = [
            h for h in conversation_history
            if (h.get("sender", h.get("from", "")), h.get("date", h.get("received_at", ""))) not in thread_senders_dates
        ]

    # Formater l'email pour les agents
    email_content = f"De: {email.sender}\nSujet: {email.subject}\n\n{email.body}"

    if instructions:
        logger.info(f"User instructions will be passed to drafter: {instructions[:100]}")

    if conversation_history:
        logger.info(f"Generating draft with {len(conversation_history)} emails in conversation history")
    else:
        logger.warning("No conversation history available for draft generation")

    # =========================================================================
    # BOOKING TEMPLATE — détection disponibilités/rendez-vous, $0, ~0ms
    # =========================================================================
    from app.api.settings import load_settings as _load_settings_local
    _booking_url = _load_settings_local().get("booking_url", "").strip()
    if _booking_url and _is_booking_request(email):
        sender_name = (getattr(email, 'sender_name', '') or '').split()[0] or "vous"
        draft_body = _build_booking_reply(sender_name, _booking_url)
        logger.info("[BOOKING] Booking template used (no LLM call)")
        if include_details:
            details = {
                "draft_v1": draft_body,
                "critique": {"is_valid": True, "feedback": "Booking template"},
                "was_corrected": False,
                "conversation_history_count": 0,
                "pipeline": "booking_template",
                "routing_tier": "booking",
                "complexity_score": 0.0,
            }
            return draft_body, "generated", "booking", "normal", "booking", details
        return draft_body, "generated", "booking", "normal", "booking"

    # =========================================================================
    # SMART ROUTING PIPELINE — uses Claude API directly (independent of container LLM)
    # =========================================================================
    from app.config import SMART_ROUTING_ENABLED
    is_claude = container.llm.name == "claude"

    if SMART_ROUTING_ENABLED:
            logger.info("Using SMART ROUTING pipeline (cost-optimized)")
            from app.smart_routing import SmartRouter

            router = SmartRouter()
            if use_streaming:
                # Streaming: emits WebSocket draft_chunk events (for frontend).
                # `force` propagates from the /process endpoint so an
                # explicit user-initiated draft (e.g. mobile drive-mode
                # dictation on a no-reply sender) bypasses the auto-sender
                # prefilter — without it the prefilter discards the draft
                # in 4ms and the client polls 90s for nothing.
                result = router.route_streaming(
                    email_id=email.id,
                    email_content=email_content,
                    sender=email.sender,
                    subject=email.subject or "",
                    body=email.body or "",
                    conversation_history=conversation_history,
                    instructions=instructions,
                    user_email=user_email,
                    thread_depth=len(conversation_history) if conversation_history else 0,
                    sender_name=getattr(email, 'sender_name', '') or '',
                    thread_context=thread_context,
                    account_id=db_account_id,
                    force=force or bool(instructions and instructions.strip()),
                    allow_faq_auto_send=allow_faq_auto_send,
                )
            else:
                # Non-streaming: avoids WebSocket deadlock from HTTP context
                result = router.route(
                    email_id=email.id,
                    email_content=email_content,
                    sender=email.sender,
                    subject=email.subject or "",
                    body=email.body or "",
                    conversation_history=conversation_history,
                    instructions=instructions,
                    user_email=user_email,
                    thread_depth=len(conversation_history) if conversation_history else 0,
                    sender_name=getattr(email, 'sender_name', '') or '',
                    force=True,
                    thread_context=thread_context,
                    has_attachments=bool(getattr(email, 'attachments_meta', None)),
                    account_id=db_account_id,
                    allow_faq_auto_send=allow_faq_auto_send,
                )

            final_draft = result.draft
            classification = result.classification
            priority = result.priority
            status = result.status
            tier = result.decision.tier.value

            logger.info(f"SmartRouter result: tier={tier}, classification={classification}, priority={priority}, status={status}")

            if include_details:
                # Use real critique info from CriticAgent if available
                critique_data = result.critique_info or {
                    "is_valid": True,
                    "feedback": f"Smart routing ({tier})",
                }
                details = {
                    "draft_v1": result.draft_v1 or final_draft,
                    "critique": critique_data,
                    "was_corrected": critique_data.get("was_revised", False),
                    "conversation_history_count": len(conversation_history),
                    "pipeline": f"smart_routing_{tier}",
                    "routing_tier": tier,
                    "complexity_score": result.decision.complexity_score,
                    "routing_reason": result.decision.reason,
                    "faq_sent_message_id": result.faq_sent_message_id,
                    "correction_details": result.correction_details or [],
                }
                _elapsed = _time.perf_counter() - _t0
                logger.info(f"[TIMING] _process_email_with_use_case: {int(_elapsed * 1000)}ms (history={_UCH}, tier={tier})")
                try:
                    from app.smart_routing import record_draft_latency
                    record_draft_latency(tier, _elapsed)
                except Exception:  # pragma: no cover — telemetry never breaks
                    pass
                return final_draft, status, classification, priority, tier, details

            _elapsed = _time.perf_counter() - _t0
            logger.info(f"[TIMING] _process_email_with_use_case: {int(_elapsed * 1000)}ms (history={_UCH}, tier={tier})")
            try:
                from app.smart_routing import record_draft_latency
                record_draft_latency(tier, _elapsed)
            except Exception:  # pragma: no cover — telemetry never breaks
                pass
            return final_draft, status, classification, priority, tier

    elif is_claude:
        logger.info("Using UNIFIED pipeline (Claude optimized: 1 LLM call)")

        drafter = DrafterAgent(account_id=db_account_id)
        # draft_unified returns dict (not RoutingResult). Use a distinct
        # variable name to avoid mypy unifying with the RoutingResult branch
        # above — they are parallel code paths, not a shared shape.
        unified_result: dict = drafter.draft_unified(
            email_content,
            conversation_history=conversation_history,
            instructions=instructions,
            user_email=user_email,
            thread_context=thread_context,
        )

        final_draft = unified_result["draft"]
        classification = unified_result["classification"]
        classification_reason = unified_result.get("classification_reason", "")
        priority = unified_result["priority"]
        status = unified_result["status"]

        logger.info(f"Unified result: classification={classification}, priority={priority}, status={status}")

        if include_details:
            details = {
                "draft_v1": final_draft,
                "critique": {"is_valid": True, "feedback": "Self-reviewed (unified pipeline)"},
                "was_corrected": False,
                "conversation_history_count": len(conversation_history),
                "pipeline": "unified",
                "classification_reason": classification_reason,
            }
            try:
                from app.smart_routing import record_draft_latency
                record_draft_latency("standard", _time.perf_counter() - _t0)
            except Exception:
                pass
            return final_draft, status, classification, priority, "standard", details

        try:
            from app.smart_routing import record_draft_latency
            record_draft_latency("standard", _time.perf_counter() - _t0)
        except Exception:
            pass
        return final_draft, status, classification, priority, "standard"

    else:
        # =========================================================================
        # MULTI-STEP PIPELINE (Ollama/other) — 4-5 appels LLM
        # =========================================================================
        logger.info("Using MULTI-STEP pipeline (Ollama/other: 4-5 LLM calls)")

        analyze_use_case = container.get_analyze_email_use_case()

        # Créer l'entité Email si ce n'est pas déjà le cas
        if not isinstance(email, Email):
            email_entity = Email(
                id=email.id,
                sender=email.sender,
                subject=email.subject,
                body=email.body,
                recipients=getattr(email, 'to', []) or [],
                cc=getattr(email, 'cc', []) or [],
                received_at=getattr(email, 'received_at', None),
                thread_id=getattr(email, 'conversation_id', None),
            )
        else:
            email_entity = email

        # Analyser l'email (classification + priorité)
        analysis = analyze_use_case.execute(email_entity, is_cc)
        classification = analysis.classification.category.value
        priority = analysis.priority.priority_score

        drafter = DrafterAgent(account_id=db_account_id)
        critic = CriticAgent(account_id=db_account_id)

        # Pré-traitement : injection d'historique pertinent (pour petits modèles)
        relevant_history_injected = False
        if conversation_history:
            relevant = _find_relevant_history_for_email(email.body or "", conversation_history)
            if relevant:
                relevant_history_injected = True
                email_content += "\n\n*** RÉPONSE À INCLURE — DONNÉES TROUVÉES ***"
                email_content += "\nVoici les emails trouvés qui contiennent la réponse à la question:"
                for r in relevant:
                    email_content += f"\n→ Email reçu le {r['date']}, sujet: \"{r['subject']}\""
                    email_content += f"\n  Contenu exact: \"{r['body'][:500]}\""
                email_content += "\n\nTu DOIS utiliser ces données ci-dessus pour répondre. Ne dis JAMAIS que tu n'as pas l'information."
                email_content += "\n*** FIN DES DONNÉES ***"
                logger.info(f"Injected {len(relevant)} relevant history items into email content")

        # LLM generates draft
        # When relevant history is already injected into email_content, don't pass full
        # conversation_history again — it overwhelms small models with noise
        draft_history = None if relevant_history_injected else conversation_history
        draft_v1 = drafter.draft(email_content, conversation_history=draft_history, instructions=instructions, user_email=user_email)

        if relevant_history_injected:
            # History was injected — skip critic (factual answer, not style)
            final_draft = draft_v1
            status = "V1"
            critique_is_valid = True
            critique = "VALID (history-based, critic skipped)"
        else:
            critic_email_content = email_content
            if conversation_history:
                history_summary = "\n\n[CONTEXTE: L'agent a accès à l'historique de conversation suivant]\n"
                for h in conversation_history[:5]:
                    h_date = h.get("date", "")
                    h_subject = h.get("subject", "")
                    h_body = h.get("body", "")[:200]
                    history_summary += f"- {h_date} | {h_subject} | {h_body}\n"
                critic_email_content = email_content + history_summary
            critique = critic.evaluate(critic_email_content, draft_v1)
            logger.info(f"CRITIQUE: {critique[:300]}")

            if critic.is_valid(critique):
                final_draft = draft_v1
                status = "V1"
                critique_is_valid = True
            else:
                final_draft = drafter.revise(email_content, critique, conversation_history=conversation_history, user_email=user_email)
                status = "V2"
                critique_is_valid = False

        if include_details:
            details = {
                "draft_v1": draft_v1,
                "critique": {
                    "is_valid": critique_is_valid,
                    "feedback": critique,
                },
                "was_corrected": status == "V2",
                "conversation_history_count": len(conversation_history),
                "pipeline": "multi-step",
            }
            try:
                from app.smart_routing import record_draft_latency
                record_draft_latency("complex", _time.perf_counter() - _t0)
            except Exception:
                pass
            return final_draft, status, classification, priority, "complex", details

        try:
            from app.smart_routing import record_draft_latency
            record_draft_latency("complex", _time.perf_counter() - _t0)
        except Exception:
            pass
        return final_draft, status, classification, priority, "complex"


# ---------------------------------------------------------------------------
# Sent-contact recording
# ---------------------------------------------------------------------------
# When the user sends an email we must:
#   1. Bump Contact.sent_count so "real contact" detection (used by the
#      labeling contact-floor and writing-style gating) reflects reality in
#      real time, not only after the next IMAP sync of the Sent folder.
#   2. Ensure a ContactStyleProfile entry exists for each recipient so the
#      "Writing style per contact" settings list every person the user has
#      ever written to, not only those manually added.
# ---------------------------------------------------------------------------

_AUTOMATED_LOCAL_PREFIXES_BACKFILL = (
    "invoice", "billing", "receipt", "statement", "notification",
)


def _is_noise_recipient(email_addr: str) -> bool:
    """Return True for noreply / automated / known-noise recipient addresses.

    Used by the writing-style backfill to keep noreply/transactional senders
    out of the per-contact style profile, even when the user has technically
    sent a reply to one of them.
    """
    addr = (email_addr or "").strip().lower()
    if not addr or "@" not in addr:
        return True
    local, _, domain = addr.partition("@")
    if any(addr.startswith(p) for p in _NOREPLY_PATTERNS):
        return True
    if "noreply" in local or "no-reply" in local or "donotreply" in local or "do-not-reply" in local:
        return True
    if any(domain == nd or domain.endswith("." + nd) for nd in _NOISE_DOMAINS):
        return True
    if local.startswith(_AUTOMATED_LOCAL_PREFIXES_BACKFILL):
        return True
    return False


def _clean_recipient_emails(recipients) -> list[str]:
    """Normalize recipient strings into a deduped lower-cased list of addresses."""
    if not recipients:
        return []
    if isinstance(recipients, str):
        raw = [recipients]
    else:
        raw = list(recipients)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not item:
            continue
        s = str(item).strip()
        # Handle "Name <addr@host>" format
        if "<" in s and ">" in s:
            s = s.split("<", 1)[1].split(">", 1)[0]
        # Handle comma-separated strings
        for piece in s.split(","):
            addr = piece.strip().lower()
            if addr and "@" in addr and addr not in seen:
                seen.add(addr)
                out.append(addr)
    return out


def record_sent_recipients(account_id: int | None, recipients, now: datetime | None = None) -> int:
    """
    Record that the user just sent an email to these recipients.

    - Bumps Contact.sent_count (creating the Contact row if missing).
    - Ensures a ContactStyleProfile entry exists in the WritingStyleProfile.

    Safe to call from background threads — opens its own DB session. Swallows
    exceptions (logs as warning) so a storage hiccup never breaks the send.

    Returns the number of recipients processed.
    """
    if not account_id:
        return 0
    clean = _clean_recipient_emails(recipients)
    if not clean:
        return 0
    ts = now or datetime.utcnow()

    # 1. Bump Contact.sent_count / create rows
    try:
        from app.db.repositories.contact_repository import ContactRepository
        with get_db_session() as sess:
            repo = ContactRepository(sess)
            for addr in clean:
                try:
                    contact, _ = repo.get_or_create(email=addr, account_id=int(account_id))
                    repo.increment_email_count(
                        contact_id=contact.id, is_sent=True, contacted_at=ts
                    )
                except Exception as per_err:
                    logger.debug("sent_contact: per-recipient bump failed for %s: %s", addr, per_err)
            sess.commit()
    except Exception as exc:
        logger.warning("sent_contact: failed to bump sent_count: %s", exc)

    # 2. Ensure ContactStyleProfile placeholders exist (skip noise senders).
    try:
        from app.domain.entities.writing_style import ContactStyleProfile
        container = get_container()
        svc = container.get_writing_style_service()
        if svc is not None:
            profile = svc.get_or_create_profile(int(account_id))
            if profile is not None:
                changed = False
                for addr in clean:
                    if _is_noise_recipient(addr):
                        continue
                    if addr not in profile.contact_profiles:
                        profile.contact_profiles[addr] = ContactStyleProfile(email=addr).to_dict()
                        changed = True
                if changed:
                    svc._store.save(profile)
    except Exception as exc:
        logger.warning("sent_contact: failed to ensure ContactStyleProfile: %s", exc)

    return len(clean)


def sender_is_real_contact(account_id: int | None, sender_email: str | None) -> bool:
    """
    Return True if the sender is a "real contact" — defined as someone the
    user has sent at least one email to (Contact.sent_count > 0).

    Used by the labeling contact-floor: a real contact should never be
    auto-classified as Noise by soft heuristics or the LLM fallback.
    """
    if not account_id or not sender_email:
        return False
    addr = sender_email.strip().lower()
    if "<" in addr and ">" in addr:
        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
    if not addr or "@" not in addr:
        return False
    try:
        from app.db.repositories.contact_repository import ContactRepository
        with get_db_session() as sess:
            repo = ContactRepository(sess)
            contact = repo.get_by_email(email=addr, account_id=int(account_id))
            return bool(contact and (contact.sent_count or 0) > 0)
    except Exception as exc:
        logger.debug("sender_is_real_contact lookup failed for %s: %s", addr, exc)
        return False


def backfill_contact_style_profiles_from_sent(account_id: int) -> dict:
    """
    Scan past sent emails and ensure every recipient has a
    ContactStyleProfile entry in the WritingStyleProfile settings.

    Source of truth: the `emails` table filtered by `is_sent=True` for this
    account. This is more reliable than Contact.sent_count which may be
    stale if the user never synced the Sent folder.

    Also bumps Contact.sent_count for any recipient whose Contact row is
    missing or has sent_count == 0, so labeling can trust the flag.

    Returns: {"contacts_added": int, "contact_rows_bumped": int, "total_recipients": int}
    """
    result = {"contacts_added": 0, "contact_rows_bumped": 0, "total_recipients": 0}
    if not account_id:
        return result

    # Step 1: collect unique recipients from all sent emails
    unique_recipients: set[str] = set()
    try:
        with get_db_session() as sess:
            from sqlalchemy import select, and_
            stmt = select(Email.recipients).where(
                and_(Email.account_id == int(account_id), Email.is_sent.is_(True))
            )
            for row in sess.execute(stmt).all():
                raw = row[0] if row else None
                for addr in _clean_recipient_emails(raw):
                    unique_recipients.add(addr)
    except Exception as exc:
        logger.warning("backfill_contact_style: failed to enumerate sent emails: %s", exc)
        return result

    result["total_recipients"] = len(unique_recipients)
    if not unique_recipients:
        return result

    # Step 2: ensure Contact.sent_count > 0 for each recipient
    try:
        from app.db.repositories.contact_repository import ContactRepository
        with get_db_session() as sess:
            repo_c = ContactRepository(sess)
            for addr in unique_recipients:
                try:
                    contact, created = repo_c.get_or_create(email=addr, account_id=int(account_id))
                    if created or (contact.sent_count or 0) == 0:
                        repo_c.increment_email_count(
                            contact_id=contact.id, is_sent=True, contacted_at=datetime.utcnow()
                        )
                        result["contact_rows_bumped"] += 1
                except Exception as per_err:
                    logger.debug("backfill_contact_style: bump failed for %s: %s", addr, per_err)
            sess.commit()
    except Exception as exc:
        logger.warning("backfill_contact_style: Contact bump phase failed: %s", exc)

    # Step 3: ensure a ContactStyleProfile entry exists per recipient.
    # Skip noreply / noise / automated addresses — even if the user has
    # technically replied to one, it has no business being a "real contact"
    # in the writing-style profile (and would clutter the Training screen).
    try:
        from app.domain.entities.writing_style import ContactStyleProfile
        container = get_container()
        svc = container.get_writing_style_service()
        if svc is not None:
            profile = svc.get_or_create_profile(int(account_id))
            if profile is not None:
                for addr in unique_recipients:
                    if _is_noise_recipient(addr):
                        continue
                    if addr not in profile.contact_profiles:
                        profile.contact_profiles[addr] = ContactStyleProfile(email=addr).to_dict()
                        result["contacts_added"] += 1
                if result["contacts_added"] > 0:
                    svc._store.save(profile)
    except Exception as exc:
        logger.warning("backfill_contact_style: style profile phase failed: %s", exc)

    logger.info(
        "backfill_contact_style: account=%s, recipients=%d, bumped=%d, style_added=%d",
        account_id, result["total_recipients"], result["contact_rows_bumped"], result["contacts_added"],
    )
    return result


def repair_noise_for_real_contacts(account_id: int, user_email: str = "") -> dict:
    """
    Re-classify all emails currently labeled NOISE where the sender is now a
    real contact (sent_count > 0). Meant to fix past misclassifications once
    the contact-floor rule is in place.

    Returns {"scanned": int, "fixed": int}.
    """
    stats = {"scanned": 0, "fixed": 0}
    if not account_id:
        return stats
    try:
        from app.domain.entities.email_labels import DefaultLabel
        from app.infrastructure.container import get_container
        container = get_container()
        label_store = container.get_label_store(account_id=account_id)
        use_case = container.get_label_email_use_case(
            user_email=user_email, account_id=account_id,
        )

        # Load all assignments (LabelStore keeps an in-memory cache — large limit
        # effectively returns everything).
        assignments = label_store.get_assignments(limit=100000)
    except Exception as exc:
        logger.warning("repair_noise: failed to bootstrap: %s", exc)
        return stats

    from app.domain.entities import Email as DomainEmail
    for assignment in assignments or []:
        try:
            if assignment.default_label != DefaultLabel.NOISE.value:
                continue
            # Only touch auto-assigned noise — never user corrections
            if getattr(assignment, "assigned_by", None) == "user":
                continue
            email_id = assignment.email_id

            # Load the email from DB
            with get_db_session() as sess:
                repo = EmailRepository(sess)
                email_row = repo.get_by_email_id(email_id, int(account_id))
                if not email_row:
                    continue
                sender = email_row.sender or ""
                if not sender_is_real_contact(int(account_id), sender):
                    continue
                stats["scanned"] += 1

                domain_email = DomainEmail(
                    id=email_id,
                    sender=sender,
                    subject=email_row.subject or "",
                    body=email_row.body_text or "",
                    recipients=[],
                )
                new_assignment = use_case.execute(
                    domain_email,
                    existing_assignment=assignment,
                    raw_metadata={"sender_is_real_contact": True},
                )
                if new_assignment.default_label != assignment.default_label:
                    label_store.save_assignment(new_assignment)
                    stats["fixed"] += 1
        except Exception as per_err:
            logger.debug("repair_noise: per-email failure: %s", per_err)

    logger.info(
        "repair_noise: account=%s, scanned=%d, fixed=%d",
        account_id, stats["scanned"], stats["fixed"],
    )
    return stats
