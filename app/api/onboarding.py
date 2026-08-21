# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour l'onboarding Knowledge Base.

Endpoints:
- POST /api/onboarding/start     - Start onboarding analysis for an account
- GET  /api/onboarding/status    - Get current onboarding status
- GET  /api/onboarding/insights  - Get generated insights (profile, knowledge, rules)
- POST /api/onboarding/feedback  - Submit user feedback on insights
"""

import logging
import threading
import time
from collections import deque
from functools import wraps
from typing import Callable

from flask import Blueprint, request, jsonify

from app.billing.entitlements import BillingEntitlementService, EntitlementRequiredError

logger = logging.getLogger(__name__)

onboarding_bp = Blueprint("onboarding", __name__)


# OB-R5 (audit 2026-04-25 onboarding-residual): in-memory rate limiter
# for /api/onboarding/status. Frontend polls this every 4 s and the
# C-6 hydration mount effect adds a one-shot fetch per tab — under
# normal use that's well under 30 req/min/account, but a buggy client
# or malicious caller could hammer the endpoint and pin a Flask worker.
# Custom limiter (Flask-Limiter is not in requirements.txt) keyed by
# account_id with a sliding 60 s window and a 60-request budget. Cap
# the registry at 10 k keys with FIFO eviction so a flood of made-up
# account_ids can't blow up memory either.
_STATUS_RATE_WINDOW_SEC = 60.0
_STATUS_RATE_BUDGET = 60
_STATUS_RATE_MAX_KEYS = 10_000
_MAX_PROFESSION_LENGTH = 120
_status_rate_lock = threading.Lock()
_status_rate_buckets: "dict[str, deque[float]]" = {}


def _status_rate_check(key: str) -> tuple[bool, float]:
    """Return ``(allowed, retry_after_sec)``.

    Defense-in-depth only: never raises. On internal error we fail open
    (allow the request) — the rate limiter must not be the reason a
    legitimate caller can't read their own status.
    """
    try:
        now = time.monotonic()
        cutoff = now - _STATUS_RATE_WINDOW_SEC
        with _status_rate_lock:
            bucket = _status_rate_buckets.get(key)
            if bucket is None:
                if len(_status_rate_buckets) >= _STATUS_RATE_MAX_KEYS:
                    # FIFO evict the oldest key — unbounded growth is the
                    # real risk on a flood of fabricated account_ids.
                    try:
                        oldest_key = next(iter(_status_rate_buckets))
                        _status_rate_buckets.pop(oldest_key, None)
                    except StopIteration:
                        pass
                # FIX COMMIT-004 (audit P1): NO `maxlen` here. With
                # `maxlen=N+1`, the deque silently auto-evicts the oldest
                # timestamp when the (N+2)th request arrives, so under a
                # sustained flood `bucket[0]` no longer points at the true
                # oldest in-window request. The Retry-After computation
                # then returns ~60s when the legitimate caller is
                # actually under budget, locking onboarding polling out
                # for the full window. Rely solely on the manual
                # popleft-by-cutoff loop below for sliding-window eviction.
                bucket = deque()
                _status_rate_buckets[key] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= _STATUS_RATE_BUDGET:
                retry = max(0.5, _STATUS_RATE_WINDOW_SEC - (now - bucket[0]))
                return False, retry
            bucket.append(now)
            return True, 0.0
    except Exception:
        return True, 0.0


def _resolve_db_account_id(account_id_or_hash, user_email: str = "") -> int:
    """Resolve a multi-account hash ID or email to the DB integer account ID.

    ISO-09 fix (2026-04-24): the previous version's ownership check was
    gated on `if effective_user_email:`. A caller with neither a JWT nor
    a loopback session that resolved to an account would get
    `effective_user_email = ""`, the check was skipped, and the function
    returned whatever int ID the attacker passed (1, 2, 3 — enumerable).
    Onboarding then ran on someone else's mailbox, overwriting
    `onboarding_results` and KB rows.

    Security: validates that the resolved account belongs to the
    authenticated user. If no caller identity can be established AND no
    explicit user_email was provided, refuses to resolve.
    """
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    # Resolve effective_user_email from explicit param OR current auth session.
    effective_user_email = (user_email or "").strip().lower()
    if not effective_user_email:
        try:
            # Routed through routes_helpers so the patch in the test
            # suite intercepts correctly.
            from app.api import routes_helpers as _rh
            current = _rh._get_current_account_for_user()
            if current and getattr(current, "email", ""):
                effective_user_email = current.email.strip().lower()
        except Exception:
            pass

    # ISO-09: refuse to resolve when no caller identity is known.
    # Without this guard, the int-id fall-through below would return any
    # existing account_id, letting an unauthenticated caller hijack
    # someone else's onboarding.
    if not effective_user_email:
        raise PermissionError(
            "Cannot resolve account_id without an authenticated caller. "
            "Pass user_email explicitly or authenticate."
        )

    with get_db_session() as session:
        repo = AccountRepository(session)
        db_accounts = repo.get_active_accounts()

        resolved = None
        # Try matching by email first (authoritative when provided).
        resolved = next(
            (a for a in db_accounts if (a.email or "").strip().lower() == effective_user_email),
            None,
        )
        # Try matching by integer ID — but ONLY after we have a caller
        # identity to compare against (handled by the ownership check
        # below, which now ALWAYS fires).
        if resolved is None:
            try:
                int_id = int(account_id_or_hash)
                resolved = next((a for a in db_accounts if a.id == int_id), None)
            except (ValueError, TypeError):
                pass
        # Try matching by multi-account hash ID → resolve email → match DB
        if resolved is None:
            try:
                from app.multi_accounts import get_account_manager
                mgr = get_account_manager()
                acct_config = mgr.get_account(str(account_id_or_hash))
                if acct_config and acct_config.email:
                    resolved = next(
                        (a for a in db_accounts if a.email == acct_config.email),
                        None,
                    )
            except Exception:
                pass

        if resolved is None:
            raise ValueError(f"No account found for id={account_id_or_hash}, email={user_email}")

        # Ownership check — now ALWAYS fires (no longer gated on a
        # truthy `effective_user_email`, which we guaranteed above).
        resolved_email = (resolved.email or "").strip().lower()
        if resolved_email != effective_user_email:
            logger.warning(
                "Cross-account access blocked: user=%s tried to resolve id=%s "
                "(belongs to %s)",
                effective_user_email, account_id_or_hash, resolved_email,
            )
            raise PermissionError(
                f"Account id={account_id_or_hash} does not belong to {effective_user_email}"
            )

        return resolved.id


def _get_manager(account_id: int | None = None):
    """Lazy-load the OnboardingManager to avoid circular imports.

    If account_id is provided, WebSocket events are scoped to that account's
    room. Otherwise they are silently skipped (safer default than broadcast).
    """
    from app.db.database import get_session_factory
    from app.onboarding.manager import OnboardingManager

    emit_fn = None
    if account_id is not None:
        from app.api.websocket import emit_to_account
        def emit_fn(event_name, data):
            emit_to_account(event_name, data, account_id)

    # Wire the sync service so the manager can trigger an immediate sync
    # while waiting for the initial inbox to populate.
    sync_trigger_fn = None
    try:
        from app.services.sync_service import get_sync_service
        sync_service = get_sync_service()
        if sync_service:
            sync_trigger_fn = sync_service.trigger_sync
    except Exception:
        pass

    return OnboardingManager(
        session_factory=get_session_factory(),
        emit_event=emit_fn,
        sync_trigger=sync_trigger_fn,
    )


def _sanitize_faq_entries(raw) -> list[dict]:
    """Validate and sanitise faq_entries from the request body.

    P1-007: faq_entries are injected verbatim into the knowledge base and later
    consumed by DrafterAgent's LLM prompt. Without sanitisation an attacker can
    smuggle prompt-injection payloads into memoire.md via the /start endpoint.

    Rules: must be a list of dicts with non-empty question+answer strings, each
    capped at 500 chars. Max 50 entries total. context capped at 200 chars.
    """
    if not isinstance(raw, list):
        return []
    result: list[dict] = []
    for entry in raw[:50]:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()[:500]
        answer = str(entry.get("answer") or "").strip()[:500]
        context = str(entry.get("context") or "").strip()[:200]
        if question and answer:
            result.append({"question": question, "answer": answer, "context": context})
    return result


def _sanitize_profession(raw) -> tuple[str, str | None]:
    if not isinstance(raw, str):
        return "", "profession must be a string"
    value = " ".join(raw.strip().split())
    if not value:
        return "", "profession is required"
    if len(value) > _MAX_PROFESSION_LENGTH:
        return "", f"profession must be at most {_MAX_PROFESSION_LENGTH} characters"
    return value, None


def require_json(f: Callable) -> Callable:
    """Decorator to validate JSON body presence."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.get_json(silent=True):
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


def _assert_paid_onboarding(account_id: int) -> None:
    """Require active paid AI entitlement before exposing onboarding value."""
    BillingEntitlementService().assert_ai_allowed(account_id=account_id)


def _billing_required_response(exc: EntitlementRequiredError):
    return jsonify({
        "error_code": "BILLING_REQUIRED",
        "error": "Onboarding requires an active subscription",
        "billing": exc.entitlement.to_dict(),
    }), 402


# ============================================================================
# POST /api/onboarding/start
# ============================================================================

@onboarding_bp.route("/start", methods=["POST"])
@require_json
def start_onboarding():
    """
    Start the onboarding knowledge base analysis.
    ---
    tags:
      - Onboarding
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - account_id
            - user_email
          properties:
            account_id:
              type: integer
              description: Account ID to analyse
            user_email:
              type: string
              description: User's email address
    responses:
      200:
        description: Onboarding started
      400:
        description: Missing required fields
    """
    import time as _time
    t0 = _time.perf_counter()
    data = request.get_json()
    raw_account_id = data.get("account_id")
    user_email = data.get("user_email")
    # Optional knobs to keep onboarding cost / Gmail pressure under control.
    # since_days=30, max_emails=500 → "fast" onboarding profile.
    since_days = data.get("since_days")
    max_emails = data.get("max_emails")
    # FAQ entries from the pre-scan step (website or document).
    # Sanitised before use — see _sanitize_faq_entries (P1-007).
    faq_entries = _sanitize_faq_entries(data.get("faq_entries"))

    if not raw_account_id or not user_email:
        return jsonify({"error": "account_id and user_email are required"}), 400

    try:
        db_account_id = _resolve_db_account_id(raw_account_id, user_email)
        _assert_paid_onboarding(db_account_id)
        t_resolve = _time.perf_counter()
        manager = _get_manager(db_account_id)
        t_manager = _time.perf_counter()
        result = manager.start(
            account_id=db_account_id,
            user_email=user_email,
            since_days=since_days,
            max_emails=max_emails,
            faq_entries=faq_entries,
        )
        t_start = _time.perf_counter()
        logger.info(
            "[ONBOARDING-START] account=%s resolve=%dms manager=%dms start=%dms total=%dms",
            db_account_id,
            int((t_resolve - t0) * 1000),
            int((t_manager - t_resolve) * 1000),
            int((t_start - t_manager) * 1000),
            int((t_start - t0) * 1000),
        )
        return jsonify(result), 200
    except EntitlementRequiredError as exc:
        return _billing_required_response(exc)
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error("Failed to start onboarding: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# POST /api/onboarding/refresh
# ============================================================================

@onboarding_bp.route("/refresh", methods=["POST"])
@require_json
def refresh_onboarding():
    """
    Start an incremental knowledge base refresh.

    Analyses recent emails (default 7 days) and merges new knowledge
    and rules into the existing memoire.md without overwriting.
    ---
    tags:
      - Onboarding
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - account_id
            - user_email
          properties:
            account_id:
              type: integer
            user_email:
              type: string
            days:
              type: integer
              default: 7
    responses:
      200:
        description: Refresh started
      400:
        description: Missing required fields
    """
    data = request.get_json()
    raw_account_id = data.get("account_id")
    user_email = data.get("user_email")
    days = data.get("days", 7)
    mode = data.get("mode", "incremental")

    if not raw_account_id or not user_email:
        return jsonify({"error": "account_id and user_email are required"}), 400

    logger.info("Refresh requested: mode=%s, days=%s, account=%s", mode, days, raw_account_id)

    if mode not in ("incremental", "deep"):
        return jsonify({"error": "mode must be 'incremental' or 'deep'"}), 400

    try:
        db_account_id = _resolve_db_account_id(raw_account_id, user_email)
        _assert_paid_onboarding(db_account_id)
        manager = _get_manager(db_account_id)
        result = manager.refresh(account_id=db_account_id, user_email=user_email, days=days, mode=mode)
        return jsonify(result), 200
    except EntitlementRequiredError as exc:
        return _billing_required_response(exc)
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error("Failed to start refresh: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# POST /api/onboarding/deep-training/cancel
# ============================================================================

@onboarding_bp.route("/deep-training/cancel", methods=["POST"])
@require_json
def cancel_deep_training():
    """Cancel a running deep training session."""
    data = request.get_json()
    raw_account_id = data.get("account_id")
    user_email = data.get("user_email", "")

    if not raw_account_id:
        return jsonify({"error": "account_id is required"}), 400

    try:
        db_account_id = _resolve_db_account_id(raw_account_id, user_email)
        manager = _get_manager(db_account_id)
        manager.cancel_deep(db_account_id)
        return jsonify({"status": "cancelling", "account_id": db_account_id}), 200
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error("Failed to cancel deep training: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# POST /api/onboarding/cancel  (OB-01)
# ============================================================================

@onboarding_bp.route("/cancel", methods=["POST"])
@require_json
def cancel_onboarding():
    """OB-01: cancel a running standard (or deep) onboarding session.

    Unlike ``/deep-training/cancel`` (which only flags deep refresh
    batches), this endpoint also patches the active OnboardingResult row
    to status='cancelled' so the user-facing /status endpoint immediately
    reflects the change. The frontend should bounce the user back to the
    welcome step on success.
    ---
    tags:
      - Onboarding
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - account_id
          properties:
            account_id:
              type: string
              description: Hash or integer account id
            user_email:
              type: string
    responses:
      200:
        description: Cancellation flagged
      400:
        description: Missing account_id
      403:
        description: Account does not belong to authenticated user
      404:
        description: Account not found
    """
    data = request.get_json()
    raw_account_id = data.get("account_id")
    user_email = data.get("user_email", "")

    if not raw_account_id:
        return jsonify({"error": "account_id is required"}), 400

    try:
        db_account_id = _resolve_db_account_id(raw_account_id, user_email)
        manager = _get_manager(db_account_id)
        result = manager.cancel(db_account_id)
        return jsonify(result), 200
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error("Failed to cancel onboarding: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# GET /api/onboarding/status
# ============================================================================

@onboarding_bp.route("/status", methods=["GET"])
def get_onboarding_status():
    """
    Get the current onboarding status for an account.
    ---
    tags:
      - Onboarding
    parameters:
      - name: account_id
        in: query
        type: integer
        required: true
    responses:
      200:
        description: Onboarding status (status='not_started' si le compte existe
          mais n'a pas encore d'onboarding — état fonctionnel normal, pas une erreur).
      400:
        description: Missing account_id
      404:
        description: Account not found
    """
    raw_account_id = request.args.get("account_id")
    if not raw_account_id:
        return jsonify({"error": "account_id query parameter required"}), 400

    # OB-R5: rate-limit by account_id BEFORE doing any DB resolution so a
    # flood doesn't translate to a flood of SQL lookups. Key is the raw
    # param string (so a bogus id flooded by the same attacker still hits
    # the same bucket). The legit polling cadence (4 s) plus the C-6
    # mount fetch fits comfortably under the 60/min budget.
    _allowed, _retry_after = _status_rate_check(str(raw_account_id))
    if not _allowed:
        resp = jsonify({"error": "Too many status requests, slow down."})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(int(_retry_after) + 1)
        return resp

    try:
        db_account_id = _resolve_db_account_id(raw_account_id)
    except PermissionError as pe:
        # Caller is authenticated but does not own this account. Surface as
        # 403 so frontend polling stops treating it as a transient 500.
        return jsonify({"error": str(pe)}), 403
    except ValueError as e:
        # Compte introuvable : 404 légitime — la ressource parent n'existe pas.
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error("Failed to resolve account_id: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500

    try:
        manager = _get_manager(db_account_id)
        status = manager.get_status(db_account_id)
        if status is None:
            # Compte OK mais pas d'onboarding encore — état normal, 200 avec
            # status:'not_started'. Évite au client de catcher un 404 pour un
            # flow standard et aligne la sémantique sur GitHub/Stripe APIs.
            return jsonify({
                "status": "not_started",
                "account_id": db_account_id,
                "version_ms": 0,
            }), 200
        # Enrichit la réponse avec la progression de sync : sans ça, un client
        # qui recharge la page pendant `waiting_for_sync` rate l'unique WS
        # event initial et reste figé sur "Initializing analysis..." alors
        # que le backend attend légitimement plus d'emails.
        if status.get("status") == "waiting_for_sync":
            try:
                from app.onboarding.manager import MIN_EMAILS_FOR_ANALYSIS
                status["current_email_count"] = manager._count_account_emails(db_account_id)
                status["min_emails_required"] = MIN_EMAILS_FOR_ANALYSIS
            except Exception as e:
                logger.warning("Failed to enrich waiting_for_sync status: %s", e)
        # P1-NEW-005: add version_ms derived from completed_at so the frontend
        # can discard stale REST responses that arrive after a WS event with a
        # higher version_ms (prevents a brief "completed → waiting_for_sync" flicker).
        if "completed_at" in status and status["completed_at"]:
            try:
                from datetime import datetime as _dt
                ct_str = status["completed_at"]
                ct = _dt.fromisoformat(ct_str.replace("Z", "+00:00"))
                status["version_ms"] = int(ct.timestamp() * 1000)
            except Exception:
                status.setdefault("version_ms", 0)
        else:
            status.setdefault("version_ms", 0)
        return jsonify(status), 200
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error("Failed to get onboarding status: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# GET /api/onboarding/insights
# ============================================================================

@onboarding_bp.route("/insights", methods=["GET"])
def get_onboarding_insights():
    """
    Get the generated insights for an account.
    ---
    tags:
      - Onboarding
    parameters:
      - name: account_id
        in: query
        type: string
        required: true
    responses:
      200:
        description: Generated insights (profile, knowledge, rules)
      400:
        description: Missing account_id
      404:
        description: No completed onboarding found
    """
    raw_account_id = request.args.get("account_id")
    if not raw_account_id:
        return jsonify({"error": "account_id query parameter required"}), 400

    try:
        db_account_id = _resolve_db_account_id(raw_account_id)
        _assert_paid_onboarding(db_account_id)
        manager = _get_manager(db_account_id)
        insights = manager.get_insights(db_account_id)
        if insights is None:
            return jsonify({"error": "No completed onboarding found for this account"}), 404
        return jsonify(insights), 200
    except EntitlementRequiredError as exc:
        return _billing_required_response(exc)
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error("Failed to get onboarding insights: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# POST /api/onboarding/feedback
# ============================================================================

@onboarding_bp.route("/learning-status", methods=["GET"])
def get_learning_status():
    """
    Get the current learning refresh coordinator status.

    Returns the unified event counter, threshold, and next refresh info.
    ---
    tags:
      - Onboarding
    responses:
      200:
        description: Learning status with counter and threshold
    """
    try:
        from app.learning_refresh import get_refresh_coordinator
        coordinator = get_refresh_coordinator()
        return jsonify(coordinator.get_status()), 200
    except Exception as e:
        logger.error("Failed to get learning status: %s", str(e))
        return jsonify({"error": str(e)}), 500


@onboarding_bp.route("/feedback", methods=["POST"])
@require_json
def submit_onboarding_feedback():
    """
    Submit user feedback on generated insights.
    ---
    tags:
      - Onboarding
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - account_id
          properties:
            account_id:
              type: integer
            approved:
              type: boolean
              description: Whether the user approves the insights
            corrections:
              type: object
              description: User corrections to profile/rules
    responses:
      200:
        description: Feedback recorded
      400:
        description: Missing required fields
    """
    data = request.get_json()
    raw_account_id = data.get("account_id")

    if not raw_account_id:
        return jsonify({"error": "account_id is required"}), 400

    approved = data.get("approved", False)
    corrections = data.get("corrections", {})
    profile_corrections = corrections.get("profile", {}) if isinstance(corrections, dict) else {}

    try:
        db_account_id = _resolve_db_account_id(raw_account_id)
        _assert_paid_onboarding(db_account_id)
    except EntitlementRequiredError as exc:
        return _billing_required_response(exc)
    except PermissionError:
        return jsonify({"error": "Account does not belong to authenticated user"}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404

    confirmed_profile = None
    if isinstance(profile_corrections, dict) and "profession" in profile_corrections:
        profession, profession_error = _sanitize_profession(profile_corrections.get("profession"))
        if profession_error:
            return jsonify({"error": profession_error}), 400
        try:
            manager = _get_manager(db_account_id)
            confirmed_profile = manager.confirm_profession(db_account_id, profession)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 404
        except Exception as e:
            logger.error("Failed to persist onboarding profession feedback: %s", str(e), exc_info=True)
            return jsonify({"error": str(e)}), 500

    # Store feedback (for now, log it; can be persisted later)
    logger.info(
        "Onboarding feedback: account=%s, approved=%s, corrections=%s",
        db_account_id, approved, bool(corrections),
    )

    payload = {
        "status": "recorded",
        "account_id": db_account_id,
        "approved": approved,
    }
    if confirmed_profile:
        payload["profile"] = confirmed_profile

    return jsonify(payload), 200
