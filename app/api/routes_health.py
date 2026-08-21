# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes Health & Stats pour Agentys.

Endpoints:
- GET /api/ping            - Fast startup check (no service init)
- GET /api/init            - Parallel init data (emails, labels, drafts, accounts)
- GET /api/update-check    - Check for available updates (GitHub)
- GET /api/health          - Health check léger (instantané)
- GET /api/health/capacity - Runtime capacity and backpressure snapshot
- GET /api/health/deep     - Health check complet (IMAP + LLM)
- GET /api/stats           - Statistiques globales
- GET /api/draft-quality/stats - Draft quality metrics
- GET /api/stats/activity  - Activity dashboard
- POST /api/stats/feature  - Record feature usage event
- GET /api/deep-work/summary - VIP email summary during Deep Work
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from flask import g, jsonify, request
from sqlalchemy import text as _sa_text

from app.api._auth_helpers import get_auth_user_id
from app.db.database import get_db_session
from .routes_helpers import (
    api_bp,
    API_VERSION,
    _resolve_account_id_cached,
    _to_iso_utc,
    _get_cached_email_response,
    _set_cached_email_response,
    _filter_self_sent_drafts,
)
import app.api.routes_helpers as _rh

# Cache-first loading dependencies

logger = logging.getLogger(__name__)


def _backfill_legacy_user_id(session, user_id: int, auth_email: str) -> None:
    """Attach the JWT user_id to active accounts matching the auth email.

    Pre-existing installs created accounts before the user_id column existed;
    older web rows may also have a stale truncated hash. Repair both cases so
    /api/init cannot hide a valid account from its authenticated owner.
    """
    from app.db.maintenance import repair_account_user_id

    repair_account_user_id(
        session,
        auth_email=auth_email,
        user_id=user_id,
        source="init",
    )


@api_bp.route("/ping", methods=["GET"])
def ping():
    """
    Lightweight endpoint for fast startup check (no service initialization).
    ---
    tags:
      - Health
    summary: Fast ping for connection check
    responses:
      200:
        description: Backend is reachable
    """
    return jsonify({"status": "ok", "version": API_VERSION}), 200


@api_bp.route("/init", methods=["GET"])
def init_data():
    """
    Endpoint d'initialisation — charge emails, label_counts, pending_drafts et accounts
    en une seule requête parallèle.

    Remplace 4 round-trips HTTP séparés au démarrage par 1 seul appel.
    Toutes les sous-requêtes sont des lectures SQLite rapides (pas d'IMAP).
    """
    limit = request.args.get("limit", 50, type=int)
    limit = max(1, min(100, limit))

    # Lecture SQLite unique partagée entre emails et label_counts (évite le double read)
    account_id = _resolve_account_id_cached()
    _cached_mem = _get_cached_email_response("inbox", "all", limit, 0, account_id=str(account_id))
    _shared_db_emails: list = []      # rows bruts SQLite
    _shared_email_ids: set | None = None  # set de IDs pour label_counts (inbox-only)

    try:
        if _cached_mem:
            # Memory cache hit: extract IDs from cached emails for label counts
            # Avoids loading 500 rows from SQLite just for the ID set
            _cached_emails = _cached_mem.get("emails", [])
            _ids = {str(e.get("id", "")) for e in _cached_emails if e.get("id")}
            _shared_email_ids = _ids if _ids else None
        else:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                _inbox_rows = list(repo.get_by_account(account_id=account_id, limit=500))
                # Outlook (Graph API) doesn't cache emails in SQLite → empty set would filter
                # all label assignments. Use None (no filter) when DB has no inbox emails.
                _ids = {e.email_id for e in _inbox_rows}
                _shared_email_ids = _ids if _ids else None
                _shared_db_emails = _inbox_rows
    except Exception as exc:
        logger.warning(f"[init] shared SQLite read failed: {exc}")

    def _fetch_emails():
        try:
            if _cached_mem:
                return {"emails": _cached_mem.get("emails", []), "has_more": _cached_mem.get("has_more", False), "source": "memory_cache"}
            emails = []
            from app.api.routes_emails import _get_pending_draft_email_ids
            pending_email_ids = _get_pending_draft_email_ids(account_id=account_id)
            for e in _shared_db_emails[:limit]:
                has_draft = e.email_id in pending_email_ids
                emails.append({
                    "id": e.email_id,
                    "subject": e.subject or "",
                    "sender": e.sender or "",
                    "sender_name": e.sender_name or "",
                    "received_at": _to_iso_utc(e.date),
                    "is_read": e.is_read,
                    "has_attachments": bool(e.attachments_meta),
                    "has_pending_draft": has_draft,
                    "conversation_id": e.thread_id,
                    "to": [r.strip() for r in e.recipients.split(",") if r.strip()] if e.recipients else [],
                    "body_preview": e.snippet or (e.body_text[:150] if e.body_text else ""),
                    "labels": [],
                    "draft_skipped": False,
                })
            # Enrich with labels (same pattern as SQLite cache path)
            if emails:
                all_ids = [str(d["id"]) for d in emails]
                from app.api.routes_emails import _get_email_labels_batch
                labels_map = _get_email_labels_batch(all_ids)
                for d in emails:
                    d["labels"] = labels_map.get(str(d["id"]), [])
                    d["draft_skipped"] = not d["has_pending_draft"] and any(
                        lb.get("name") == "Noise" for lb in d["labels"]
                    )
                # Réchauffe le cache mémoire pour les prochains GET /api/emails
                _set_cached_email_response("inbox", "all", emails, account_id=str(account_id))
            return {"emails": emails, "has_more": False, "source": "sqlite"}
        except Exception as exc:
            logger.warning(f"[init] emails fetch failed: {exc}")
            return {"emails": [], "has_more": False, "source": "error"}

    def _fetch_label_counts():
        try:
            container = _rh._get_container()
            store = container.get_label_store()
            # Réutilise les IDs déjà lus — aucun re-read SQLite
            counts = store.get_label_counts(valid_email_ids=_shared_email_ids)
            return {"counts": counts, "total": sum(counts.values())}
        except Exception as exc:
            logger.warning(f"[init] label_counts fetch failed: {exc}")
            return {"counts": {}, "total": 0}

    def _fetch_pending_drafts():
        try:
            store = _rh._get_container().get_pending_draft_store()
            pending = store.get_pending(account_id=str(account_id), limit=100)
            pending = _filter_self_sent_drafts(pending)
            return {
                "drafts": [d.to_dict_summary() for d in pending],
                "pending_count": len(pending),
            }
        except Exception as exc:
            logger.warning(f"[init] pending_drafts fetch failed: {exc}")
            return {"drafts": [], "pending_count": 0}

    # Multi-user isolation: in web/JWT mode, scope the init bundle (accounts +
    # current_account_id) to the authenticated user so we never leak another
    # user's accounts. get_auth_user_id() already returns None on loopback
    # (Tauri desktop), which falls back to the legacy unfiltered path.
    effective_user_id = get_auth_user_id()
    auth_email = (getattr(g, "auth_user", None) or {}).get("email") if effective_user_id else None

    def _fetch_accounts():
        try:
            from app.multi_accounts import get_account_manager
            mgr = get_account_manager()
            with _rh.get_db_session() as session:
                from app.db.repositories.account_repository import AccountRepository
                repo = AccountRepository(session)
                if effective_user_id is None:
                    accounts = repo.get_active_accounts()
                else:
                    # Repair legacy/stale account.user_id rows whose email
                    # matches the JWT user before scoped lookup. Without this,
                    # a valid OAuth account can disappear from /api/init after
                    # an older hash implementation or interrupted deploy.
                    if auth_email:
                        _backfill_legacy_user_id(session, effective_user_id, auth_email)
                    accounts = repo.get_active_accounts_for_user(effective_user_id)
                out = []
                for a in accounts:
                    hash_id = None
                    try:
                        cfg = mgr.get_account_by_email(a.email) if a.email else None
                        cfg_id = getattr(cfg, "id", None) if cfg else None
                        if isinstance(cfg_id, (str, int)):
                            hash_id = str(cfg_id)
                    except Exception:
                        pass
                    out.append({
                        "id": a.id,
                        "hash_id": hash_id,
                        "email": a.email,
                        "name": getattr(a, "name", "") or "",
                        "provider": getattr(a, "provider", "") or "",
                        "status": getattr(a, "status", "active") or "active",
                    })
                return out
        except Exception as exc:
            logger.warning(f"[init] accounts fetch failed: {exc}")
            return []

    def _fetch_spam_count():
        try:
            with _rh.get_db_session() as session:
                from sqlalchemy import func, select as sa_select
                from app.db.models.email import Email as EmailModel
                count = session.scalar(
                    sa_select(func.count()).select_from(EmailModel)
                    .where(EmailModel.account_id == account_id, EmailModel.folder == "spam")
                )
                return count or 0
        except Exception:
            return 0

    # Appels séquentiels — toutes les opérations sont des lectures SQLite rapides (< 5ms chacune).
    # ThreadPoolExecutor est incompatible avec eventlet (monkey-patching) : provoque des
    # TimeoutError('timed out') sur le serveur Werkzeug/eventlet.
    # Include current_account_id so the frontend selects the right account after restart.
    # In web/JWT mode, use the per-user "current" so we don't leak the server owner's
    # Tauri account selection to remote users.
    #
    # The multi-accounts manager keys accounts by a SHA256 hash of
    # `provider:email`, but ``/api/init`` returns ``accounts[].id`` as DB
    # integers — the frontend matches by string equality on these two fields
    # (cf. ``useBackendConnection.ts``). Returning the raw hash here makes
    # every match fail and the frontend silently falls back to "first active
    # account", which mis-tags emails as "Moi" whenever the wrong account is
    # chosen. Resolve hash → email → DB int before serialising so the two
    # sides line up.
    current_account_id = None
    try:
        from app.multi_accounts import get_account_manager, get_current_account
        from app.api.routes_helpers import _resolve_account_id_for_email

        hash_id: Optional[str] = None
        email_for_lookup: Optional[str] = None
        if effective_user_id is not None:
            hash_id = get_account_manager().get_current_for_user(effective_user_id)
            if hash_id:
                acct = get_account_manager().get_account(hash_id)
                if acct:
                    email_for_lookup = acct.email
        else:
            current = get_current_account()
            if current:
                email_for_lookup = current.email

        if email_for_lookup:
            resolved = _resolve_account_id_for_email(email_for_lookup)
            if resolved and resolved > 0:
                current_account_id = resolved
    except Exception:
        pass

    result = {
        "emails": _fetch_emails(),
        "label_counts": _fetch_label_counts(),
        "pending_drafts": _fetch_pending_drafts(),
        "accounts": _fetch_accounts(),
        "spam_count": _fetch_spam_count(),
        "current_account_id": current_account_id,
    }

    return jsonify(result), 200


@api_bp.route("/update-check", methods=["GET"])
def update_check():
    """
    Check for available updates.

    Compares current version with latest release from GitHub.
    Falls back gracefully if GitHub is unreachable.
    """
    import urllib.request
    import json as _json

    current = API_VERSION
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/agentys-ai/agentys/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "Agentys"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())

        latest = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", "")
        release_notes = data.get("body", "")[:500]

        has_update = _compare_versions(latest, current)

        return jsonify({
            "has_update": has_update,
            "current_version": current,
            "latest_version": latest,
            "release_url": release_url,
            "release_notes": release_notes,
        })
    except Exception:
        return jsonify({
            "has_update": False,
            "current_version": current,
            "latest_version": current,
            "release_url": "",
            "release_notes": "",
        })


def _compare_versions(latest: str, current: str) -> bool:
    """Return True if latest > current using semver comparison."""
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


# ============================================================================
# HEALTH & STATS
# ============================================================================

@api_bp.route("/health", methods=["GET"])
def health():
    """
    Health check léger — répond instantanément sans I/O externe.
    Utilisé par Docker, Railway, load balancers et le frontend.
    ---
    tags:
      - System
    summary: Health check léger (pas de connexion IMAP/LLM)
    responses:
      200:
        description: Serveur opérationnel
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                version:
                  type: string
                timestamp:
                  type: string
                  format: date-time
      503:
        description: Service indisponible (réservé — jamais retourné par ce léger check ; /health/deep l'utilise)
    """
    return jsonify({
        "status": "ok",
        "version": API_VERSION,
        "timestamp": _to_iso_utc(datetime.now()),
    }), 200


def _capacity_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


@api_bp.route("/health/capacity", methods=["GET"])
def health_capacity():
    """Runtime capacity snapshot for draft generation backpressure."""
    from app.infrastructure.draft_job_queue import get_draft_queue_stats

    stats = get_draft_queue_stats()
    queue_max = max(1, int(stats.get("queue_max", 1)))
    max_workers = max(1, int(stats.get("max_workers", 1)))
    queue_utilization = stats.get("queue_depth", 0) / queue_max
    worker_utilization = stats.get("active_workers", 0) / max_workers
    warn_utilization = _capacity_float_env("DRAFT_QUEUE_WARN_UTILIZATION", 0.75)
    critical_utilization = _capacity_float_env("DRAFT_QUEUE_CRITICAL_UTILIZATION", 0.95)

    reasons: list[str] = []
    status = "ok"
    if queue_utilization >= critical_utilization:
        status = "saturated"
        reasons.append("draft_queue_critical")
    elif queue_utilization >= warn_utilization:
        status = "degraded"
        reasons.append("draft_queue_high")

    if worker_utilization >= critical_utilization and status != "saturated":
        status = "degraded"
        reasons.append("draft_workers_busy")

    return jsonify({
        "status": status,
        "reasons": reasons,
        "version": API_VERSION,
        "timestamp": _to_iso_utc(datetime.now()),
        "draft_queue": {
            **stats,
            "queue_utilization": round(queue_utilization, 4),
            "worker_utilization": round(worker_utilization, 4),
        },
        "slo": {
            "queue_utilization_warn": warn_utilization,
            "queue_utilization_critical": critical_utilization,
            "http_p95_ms": int(_capacity_float_env("DRAFT_SLO_HTTP_P95_MS", 250)),
            "draft_ready_p95_ms": int(_capacity_float_env("DRAFT_SLO_READY_P95_MS", 5000)),
            "backpressure_rate_max": _capacity_float_env("DRAFT_SLO_BACKPRESSURE_RATE", 0.01),
        },
    }), 200


# Timestamp de boot du process — figé à l'import, utilisé pour mesurer uptime
# côté monitoring externe (la date d'un redeploy Railway coïncide avec cet
# instant-là).
_PROCESS_STARTED_AT = _to_iso_utc(datetime.now(timezone.utc))


def _build_version_info() -> dict:
    """Collecte les env vars Railway + version app au moment de l'appel.

    Lu à chaque GET /api/version (coût négligeable : quelques dict lookups)
    plutôt qu'un snapshot au boot, ce qui permet aux tests de monkeypatcher
    les env vars sans reloader le module.
    """
    sha = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "").strip()
    return {
        "version": API_VERSION,
        "commit_sha": sha[:40] or None,
        "commit_short": sha[:8] or None,
        "branch": os.environ.get("RAILWAY_GIT_BRANCH") or None,
        "commit_message": (os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE") or "")[:200] or None,
        "commit_author": os.environ.get("RAILWAY_GIT_AUTHOR") or None,
        "deployment_id": os.environ.get("RAILWAY_DEPLOYMENT_ID") or None,
        "environment": (
            os.environ.get("RAILWAY_ENVIRONMENT_NAME")
            or os.environ.get("RAILWAY_ENVIRONMENT")
            or os.environ.get("ENVIRONMENT")
            or "local"
        ),
        "started_at": _PROCESS_STARTED_AT,
    }


@api_bp.route("/version", methods=["GET"])
def version():
    """
    Retourne la version + SHA git déployés. Public, pas d'auth.

    Utile pour :
      - Vérifier quel commit tourne en prod depuis un script externe
      - Corréler un bug à un déploiement sans creuser Railway UI
      - Monitoring tiers (Sentry release tracking, statuspage)

    Les champs `commit_*` et `branch` sont populés automatiquement par
    Railway via les env vars `RAILWAY_GIT_*`. En local ils sont `null`.
    ---
    tags:
      - System
    summary: Infos version + commit git déployé
    responses:
      200:
        description: Snapshot version (recomputed à chaque appel, ~10µs)
    """
    return jsonify(_build_version_info()), 200


def _probe_db() -> tuple[bool, str | None]:
    """Cheap DB liveness probe used by /api/health/strict.

    Returns (healthy, reason). Reason is the short error class name on
    failure (never a path or traceback) so the JSON response stays safe to
    expose publicly to Railway / load balancers.

    Issue #577 item 1: this is the assertion Railway needs to refuse a
    promotion when the DB is broken. The probe must NEVER raise — bubbling
    would Flask-500 and Railway would still flip traffic.
    """
    try:
        with get_db_session() as session:
            session.execute(_sa_text("SELECT 1"))
        return True, None
    except Exception as exc:
        return False, type(exc).__name__


@api_bp.route("/health/strict", methods=["GET"])
def health_strict():
    """
    Strict health check — probes the DB with SELECT 1.

    Used by Railway as the deployment healthcheck (see ``railway.toml``).
    Returns 503 if the DB is unreachable so Railway holds the previous
    container instead of promoting a broken one.

    Distinct from /api/health (always 200, used as a presence ping by load
    balancers and the frontend) and /api/health/deep (multi-second IMAP +
    LLM probe, unsuitable for fast bascule decisions).
    ---
    tags:
      - System
    summary: DB-aware healthcheck for deployment promotion
    responses:
      200:
        description: DB reachable
      503:
        description: DB unreachable — do not promote this container
    """
    healthy, reason = _probe_db()
    body = {
        "status": "ok" if healthy else "unhealthy",
        "db": "ok" if healthy else "down",
        "version": API_VERSION,
        "timestamp": _to_iso_utc(datetime.now()),
    }
    if not healthy:
        body["reason"] = reason
    status_code = 200 if healthy else 503
    return jsonify(body), status_code


@api_bp.route("/health/deep", methods=["GET"])
def health_deep():
    """
    Health check complet — teste IMAP + LLM (peut prendre plusieurs secondes).
    ---
    tags:
      - System
    summary: Health check complet (IMAP auth + LLM ping)
    responses:
      200:
        description: Système healthy
      503:
        description: Système dégradé
    """
    container = _rh._get_container()
    health_check = container.get_health_check_use_case()
    result = health_check.execute()

    response_data = {
        "status": result.status,
        "version": API_VERSION,
        "services": {
            "email": "connected" if result.email_provider.healthy else "disconnected",
            "llm": "connected" if result.llm.healthy else "disconnected",
        },
        "timestamp": _to_iso_utc(datetime.now()),
    }

    # Always return 200 for infrastructure healthchecks (Railway, Docker).
    # Degraded status is reported in the JSON body, not via HTTP status code.
    return jsonify(response_data), 200


@api_bp.route("/stats", methods=["GET"])
def stats():
    """
    Retourne les statistiques globales.
    ---
    tags:
      - Statistics
    summary: Retourne les statistiques globales du système
    responses:
      200:
        description: Métriques du système
        content:
          application/json:
            schema:
              type: object
              properties:
                drafts:
                  type: object
                  description: Statistiques des brouillons
                followups:
                  type: object
                  description: Statistiques des suivis
                learning:
                  type: object
                  description: Statistiques d'apprentissage
                costs:
                  type: object
                  description: Statistiques des coûts
                tokens:
                  type: object
                  description: Statistiques des tokens
                timestamp:
                  type: string
                  format: date-time
    """
    container = _rh._get_container()

    # Ports DI (Clean Architecture)
    draft_history = container.get_draft_history()
    token_counter = container.get_token_counter()
    learning_service = container.get_learning_service()

    # Stats des drafts via le port (scoped par compte — isolation multi-compte)
    _stats_account_id = _rh._resolve_account_id_for_user()
    if _stats_account_id > 0:
        all_drafts = draft_history.get_all_for_account(_stats_account_id, limit=10000)
    else:
        all_drafts = []
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    draft_stats = _build_draft_stats(all_drafts, today_prefix)

    # Stats learning via le service DI
    learning_stats = learning_service.get_stats()

    # Stats couts - toujours via legacy pour l'instant
    from app.infrastructure.cost_manager import get_cost_manager
    cost_stats = get_cost_manager().get_current_month_stats()

    # Token counter via le port
    token_stats = {
        "total_tokens": token_counter.get_total(),
        "model": token_counter.get_model(),
        "breakdown": token_counter.get_history(10),
    }

    return jsonify({
        "drafts": draft_stats,
        "learning": learning_stats.__dict__ if hasattr(learning_stats, '__dict__') else learning_stats,
        "costs": cost_stats,
        "tokens": token_stats,
        "timestamp": datetime.now().isoformat(),
    })


@api_bp.route("/draft-quality/stats", methods=["GET"])
def draft_quality_stats():
    """Returns draft quality metrics (unmodified rate, by intent/tier)."""
    # Audit 2026-05-29: scope draft-quality stats to the caller's account so the
    # "unmodified rate" / by-tier metrics on the Learning dashboard don't blend
    # every tenant's send events. Non-positive / Tauri desktop → None = global.
    _aid = _rh._resolve_account_id_for_user()
    _scoped_aid = str(_aid) if isinstance(_aid, int) and _aid > 0 else None
    from app.draft_quality_tracker import get_tracker
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))
    return jsonify(get_tracker().get_stats(days=days, account_id=_scoped_aid))


@api_bp.route("/stats/activity", methods=["GET"])
def stats_activity():
    """Activity dashboard: this week + today with refined time savings per tier."""
    # Audit 2026-05-29: previously resolved the account but discarded it and
    # returned get_activity() unscoped — every tenant saw the COMBINED
    # time-saved of ALL users in the live indicator / Learning dashboard /
    # achievements. Scope to the caller's account (non-positive / Tauri
    # desktop → None = global single-user behaviour, unchanged).
    _aid = _rh._resolve_account_id_for_user()
    _scoped_aid = str(_aid) if isinstance(_aid, int) and _aid > 0 else None
    from app.draft_quality_tracker import get_tracker
    return jsonify(get_tracker().get_activity(account_id=_scoped_aid))


@api_bp.route("/stats/feature", methods=["POST"])
def stats_record_feature():
    """Record a feature usage event for time-saved tracking.

    Body JSON:
        feature (str): Feature name (compose_ai, refine_ai, attachment_reminder, shortcut)
        count (int, optional): Number of occurrences (default 1)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    feature = data.get("feature", "").strip()
    if not feature:
        return jsonify({"error": "feature is required"}), 400

    count = data.get("count", 1)
    if not isinstance(count, int) or count < 1:
        count = 1

    _aid = _rh._resolve_account_id_for_user()
    _scoped_aid = str(_aid) if isinstance(_aid, int) and _aid > 0 else ""

    from app.draft_quality_tracker import get_tracker
    get_tracker().record_feature(feature, count, account_id=_scoped_aid)
    return jsonify({"success": True})


def _build_draft_stats(all_drafts: list, today_prefix: str) -> dict:
    """Construit les statistiques des drafts."""
    stats = {
        "total": len(all_drafts),
        "today": sum(1 for d in all_drafts if d.timestamp.startswith(today_prefix)),
        "by_status": {},
        "by_category": {},
    }

    for d in all_drafts:
        status = d.status or "UNKNOWN"
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        category = d.category or "UNKNOWN"
        stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

    return stats


# ============================================================================
# DEEP WORK
# ============================================================================


@api_bp.route("/deep-work/summary", methods=["GET"])
def deep_work_summary():
    """Get VIP email summary during Deep Work mode.

    Returns count of VIP emails received since a given time.
    Query params:
        since (str): ISO timestamp for cutoff (defaults to start of day)
    """
    from app.api.settings import load_settings

    # VIP contacts live in the caller's per-account settings overrides, not the
    # process-global settings.json (audit 2026-05-29: the VIP summary was
    # account-blind and always read the empty global default).
    _dw_aid = _resolve_account_id_cached()
    settings = load_settings(account_id=_dw_aid if isinstance(_dw_aid, int) and _dw_aid > 0 else None)
    vip_contacts = settings.get("deep_work_vip_contacts", [])

    since_param = request.args.get("since", "")
    if since_param:
        try:
            since_dt = datetime.fromisoformat(since_param.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            since_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    else:
        since_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)

    try:
        # Use SQLite cached emails instead of live IMAP fetch to avoid
        # pool deadlock on repeated calls (IMAP connection never released).
        account_id = _dw_aid

        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            emails = repo.get_by_account(
                account_id=account_id,
                limit=50,
                since_date=since_dt,
            )

        vip_count = 0
        vip_senders: list[str] = []
        total_count = len(emails)

        for email in emails:
            sender = (email.sender or "").lower()
            if any(vip in sender for vip in vip_contacts):
                vip_count += 1
                sender_name = email.sender_name or sender
                if sender_name not in vip_senders:
                    vip_senders.append(sender_name)

        return jsonify({
            "vip_count": vip_count,
            "vip_senders": vip_senders[:5],
            "total_count": total_count,
        })

    except Exception as e:
        logger.warning(f"deep-work/summary failed: {e}")
        return jsonify({"vip_count": 0, "vip_senders": [], "total_count": 0})
