"""
Gmail Pub/Sub push integration (N3 — event-driven sync).

Replaces the 120-second polling loop with a webhook called by Google whenever
something changes in the user's mailbox.

Three endpoints:
- ``POST /api/gmail/push``        — receives Pub/Sub push messages from Google.
- ``POST /api/gmail/watch/start`` — opens / renews a watch on the mailbox.
- ``POST /api/gmail/watch/stop``  — cancels the watch (used when disconnecting).

The one-time GCP setup is documented in
``docs/operations/gmail-push-setup.md``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Optional

from flask import Blueprint, g, jsonify, request

from app.api.admin import require_admin
from app.db.database import get_session
from app.db.models.account import Account


# F-08 (audit issue #209, 2026-04-29): allow-list for Pub/Sub topics
# accepted via the `topic` body parameter. Without this, an attacker
# could redirect a victim's Gmail watch to a topic of their choice.
# Empty list = restrict to env-default topic only (DEFAULT_TOPIC_ENV).
_ALLOWED_TOPICS_ENV = "GMAIL_PUSH_ALLOWED_TOPICS"


def _topic_is_allowed(topic: str) -> bool:
    default_topic = os.environ.get("GMAIL_PUSH_TOPIC")
    allowed_csv = os.environ.get(_ALLOWED_TOPICS_ENV, "")
    allowed = {t.strip() for t in allowed_csv.split(",") if t.strip()}
    if default_topic:
        allowed.add(default_topic)
    return topic in allowed


def _observability_token_is_valid() -> bool:
    expected = os.environ.get("OBSERVABILITY_TOKEN", "").strip()
    provided = request.headers.get("X-Observability-Token", "").strip()
    return bool(expected and provided and secrets.compare_digest(provided, expected))


def _require_admin_or_observability_token(f):
    admin_guarded = require_admin(f)

    @wraps(f)
    def decorated(*args, **kwargs):
        if _observability_token_is_valid():
            return f(*args, **kwargs)
        return admin_guarded(*args, **kwargs)

    return decorated


def _account_is_owned_by_caller(account: Account) -> bool:
    """Verify the JWT caller owns the resolved account.

    Returns True when (a) no auth context (Tauri loopback / dev), or
    (b) the JWT user_id or email matches the account row. Otherwise
    False — caller will translate that into a 404.
    """
    auth_user = getattr(g, "auth_user", None)
    if not auth_user:
        return True  # loopback / no JWT — trust the account_id

    user_id = auth_user.get("id")
    user_email = (auth_user.get("email") or "").strip().lower()

    acc_uid = getattr(account, "user_id", None)
    if user_id is not None and acc_uid is not None and int(acc_uid) == int(user_id):
        return True
    acc_email = (getattr(account, "email", "") or "").strip().lower()
    if user_email and acc_email and acc_email == user_email:
        return True
    return False

logger = logging.getLogger(__name__)

gmail_push_bp = Blueprint("gmail_push", __name__)

# Default Pub/Sub topic used by start_watch when caller doesn't override.
# Set GMAIL_PUSH_TOPIC=projects/<gcp-project>/topics/<topic> in Railway envs.
DEFAULT_TOPIC_ENV = "GMAIL_PUSH_TOPIC"
# Audience that Pub/Sub uses when signing the OIDC token attached to push
# requests. Must match the audience configured on the subscription.
PUSH_AUDIENCE_ENV = "GMAIL_PUSH_AUDIENCE"
# Service account expected as token "email" claim. Configure on the Pub/Sub
# subscription — typically a dedicated SA you grant roles/run.invoker on.
PUSH_SERVICE_ACCOUNT_ENV = "GMAIL_PUSH_SERVICE_ACCOUNT"


def _verify_pubsub_jwt(authorization_header: Optional[str]) -> Optional[dict]:
    """
    Validate the OIDC token attached to a Pub/Sub push request.

    Returns the decoded claims dict on success, ``None`` if the token is
    missing/invalid. We deliberately fail closed: an unauthenticated request
    must never trigger a sync.

    M-5 (audit security.md, issue #539) — trust model:

    1. **Crypto verification**: ``id_token.verify_oauth2_token`` (google-auth)
       performs full OIDC verification — fetches Google's RS256 public keys,
       validates signature, ``aud``, ``iss``, ``exp``, ``iat``. Forged or
       tampered tokens raise ``ValueError`` and are rejected here, not just
       presence-checked.
    2. **Audience pinning**: required (``GMAIL_PUSH_AUDIENCE`` env). Without
       it any Google-signed token would pass — refused outright.
    3. **Service-account pinning**: required *in production*
       (``GMAIL_PUSH_SERVICE_ACCOUNT`` env). Without the SA pin, any Google
       project's SA could sign a token for our audience. Locking to a single
       SA we configured on the Pub/Sub subscription is the second binding.
    4. **Tenant scoping**: the OIDC ``email`` claim is the *publisher SA*,
       NOT the Gmail user (by Gmail Pub/Sub design). The user identity comes
       from the payload's ``emailAddress`` field. We trust that field
       because the audience+SA pin proves the message came through OUR
       authorised topic, which only receives watches for accounts we
       enrolled. Defence-in-depth: ``_trigger_history_sync`` looks up the
       email in our DB and refuses unknowns (status=``ignored``).
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None

    token = authorization_header.split(" ", 1)[1].strip()
    expected_audience = os.environ.get(PUSH_AUDIENCE_ENV)
    expected_sa = os.environ.get(PUSH_SERVICE_ACCOUNT_ENV)
    if not expected_audience:
        logger.error("GMAIL_PUSH_AUDIENCE not set — refusing push (open relay risk)")
        return None

    # M-5 (#539): make the SA pin mandatory in production. Without it, any
    # Google project's SA token signed for our audience would pass — i.e.
    # "any Google account holder" given audience leaks via DNS. Dev/test
    # can omit the env to keep fixtures simple.
    try:
        from app.api._auth_helpers import is_production
        in_prod = is_production()
    except Exception:
        in_prod = False
    if in_prod and not expected_sa:
        logger.error(
            "GMAIL_PUSH_SERVICE_ACCOUNT not set in production — refusing push "
            "(would let any Google-signed OIDC through)"
        )
        return None

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError:
        logger.error("google-auth not installed — cannot verify Pub/Sub JWT")
        return None

    try:
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=expected_audience
        )
    except ValueError as e:
        logger.warning("Pub/Sub JWT verification failed: %s", e)
        return None

    if expected_sa and claims.get("email") != expected_sa:
        logger.warning(
            "Pub/Sub JWT email mismatch: got=%s expected=%s",
            claims.get("email"), expected_sa,
        )
        return None

    return claims


def _decode_pubsub_payload(envelope: dict) -> Optional[dict]:
    """Decode the base64-encoded ``message.data`` field of a Pub/Sub envelope."""
    message = envelope.get("message") or {}
    data_b64 = message.get("data")
    if not data_b64:
        return None
    try:
        raw = base64.b64decode(data_b64).decode("utf-8")
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.warning("Failed to decode Pub/Sub payload: %s", e)
        return None


def _trigger_history_sync(email_address: str, history_id: str) -> dict:
    """
    Resolve the account by email and dispatch an incremental sync.

    Returns a status dict suitable for HTTP response. Does NOT raise — Pub/Sub
    will retry on 5xx and we want to swallow internal errors so transient bugs
    don't cause infinite retry storms.
    """
    session = get_session()
    try:
        account: Optional[Account] = (
            session.query(Account).filter(Account.email == email_address).first()
        )
        if not account:
            logger.warning("Push received for unknown account: %s", email_address)
            return {"status": "ignored", "reason": "unknown_account"}

        # IMPORTANT — do NOT overwrite account.last_history_id with the push's
        # historyId here. SyncService calls users.history.list(startHistoryId=
        # account.last_history_id); if we bump the checkpoint first, the delta
        # fetch starts *after* the change and returns 0 results. SyncService
        # itself updates last_history_id after it has actually consumed the
        # delta (sync_service.py:482). When no sync can run at all (B-07), we
        # return an error so Pub/Sub redelivers — never checkpoint unconsumed.

        # Gmail push is already scoped to INBOX for one mailbox. Route it
        # through the persistent sync-job queue instead of the broad SyncService
        # account sync, which also performs sent/backfill work and can delay a
        # new inbound message behind unrelated provider calls.
        try:
            from app.services.sync_jobs import enqueue_sync_job

            job = enqueue_sync_job(
                account_id=int(account.id),
                folder="inbox",
                limit=50,
                unread_only=False,
                user_id=getattr(account, "user_id", None),
                source="gmail_push",
            )
            logger.info(
                "Push received for %s (historyId=%s) — sync job queued "
                "job_id=%s status=%s coalesced=%s",
                email_address,
                history_id,
                job.get("id"),
                job.get("status"),
                job.get("coalesced"),
            )
            return {
                "status": "ok",
                "job_id": job.get("id"),
                "coalesced": bool(job.get("coalesced")),
            }
        except Exception as e:
            logger.warning(
                "Push sync job enqueue failed for %s (historyId=%s): %s; "
                "falling back to SyncService",
                email_address,
                history_id,
                e,
            )

        # Fallback path. Lazy import to avoid a hard dep at import time (the
        # service is not initialised during some tests).
        try:
            from app.services.sync_service import get_sync_service
            svc = get_sync_service()
        except Exception:
            svc = None

        try:
            if svc is None:
                # B-07 (audit 2026-06-11): do NOT advance last_history_id here.
                # No sync ran, so checkpointing would make the next delta start
                # *after* the pushed message and silently skip it. Replaying is
                # deduplicated and harmless; return "error" so the handler
                # responds 5xx and Pub/Sub retries the push.
                logger.error(
                    "Push received for %s (historyId=%s) — sync service "
                    "unavailable, leaving checkpoint untouched for Pub/Sub retry",
                    email_address, history_id,
                )
                return {"status": "error", "reason": "sync_unavailable"}

            trigger_account_sync = getattr(svc, "trigger_account_sync", None)
            if callable(trigger_account_sync):
                trigger_account_sync(account.id)
            else:
                # Backward-compatible fallback for tests/legacy service objects.
                svc.trigger_sync()
        except Exception as e:
            logger.error(
                "Failed to dispatch sync for %s (historyId=%s): %s",
                email_address, history_id, e, exc_info=True,
            )
            return {"status": "error", "reason": "sync_dispatch_failed"}

        logger.info(
            "Push received for %s (historyId=%s) — sync triggered",
            email_address, history_id,
        )
        return {"status": "ok"}
    finally:
        session.close()


@gmail_push_bp.route("/api/gmail/push", methods=["POST"])
def gmail_push():
    """Pub/Sub push handler. Always returns 2xx unless we want a Pub/Sub retry.

    Security: see ``_verify_pubsub_jwt`` for the full M-5 (#539) trust model.
    The OIDC ``email`` claim is the publisher SA — NOT the Gmail user. User
    identity comes from the decoded payload below ; we trust it because the
    audience+SA pin already proves the message came through our authorised
    topic. Tenant scoping happens in ``_trigger_history_sync`` via DB lookup.
    """
    claims = _verify_pubsub_jwt(request.headers.get("Authorization"))
    if claims is None:
        return jsonify({"error": "unauthorized"}), 401

    envelope = request.get_json(silent=True) or {}
    payload = _decode_pubsub_payload(envelope)
    if not payload:
        # Malformed payload: ack so Pub/Sub stops retrying.
        return jsonify({"status": "ignored", "reason": "no_payload"}), 200

    email_address = payload.get("emailAddress")
    history_id = payload.get("historyId")
    if not email_address or history_id is None:
        return jsonify({"status": "ignored", "reason": "missing_fields"}), 200

    result = _trigger_history_sync(email_address, str(history_id))
    # Map internal statuses to HTTP codes Pub/Sub will/won't retry on:
    # - "error" → 500 (retry, transient backend issue)
    # - everything else → 200 (ack, don't replay)
    status_code = 500 if result.get("status") == "error" else 200
    return jsonify(result), status_code


class WatchAuthError(RuntimeError):
    """Raised by ``_enroll_watch`` when the Gmail adapter cannot authenticate.

    Distinct type so the ``/watch/start`` endpoint can map it to 401 while
    other Gmail API failures bubble up to the generic 500 handler.
    """


def _enroll_watch(session, account: Account, topic: str, label_ids=None) -> dict:
    """Open/refresh a Gmail watch for ``account`` and persist the new
    expiration / topic / history checkpoint on the row. Caller commits.

    Shared by the manual ``/watch/start`` endpoint and the on-connect
    auto-enrolment path. Raises ``WatchAuthError`` on auth failure and lets
    other Gmail API errors propagate — callers decide whether that is fatal
    (endpoint → 500) or best-effort (async enrolment swallows it).
    """
    import hashlib
    from app.providers.gmail_adapter import GmailAdapter

    # OAuth tokens are stored under sha256("gmail:<email>")[:16] (oauth.py),
    # which is what GmailAdapter(account_id=...) expects — not the DB int id.
    token_hash_id = hashlib.sha256(f"gmail:{account.email}".encode()).hexdigest()[:16]
    adapter = GmailAdapter(account_id=token_hash_id)
    if not adapter.authenticate():
        raise WatchAuthError("gmail authentication failed")
    response = adapter.start_watch(topic_name=topic, label_ids=label_ids or ["INBOX"])
    response = response if isinstance(response, dict) else {}

    expiration_ms = response.get("expiration")
    if expiration_ms is not None:
        account.gmail_watch_expiration = datetime.fromtimestamp(
            int(expiration_ms) / 1000.0, tz=timezone.utc
        )
    account.gmail_watch_topic = topic
    if response.get("historyId"):
        account.last_history_id = str(response["historyId"])
    return response


def enroll_gmail_watch_async(email: str) -> None:
    """Best-effort: open a Gmail Pub/Sub watch for a freshly-connected account
    in a background thread.

    No-op when ``GMAIL_PUSH_TOPIC`` is unset. Never raises — a failed enrolment
    just leaves the account on polling until the daily renew-due cron or the 6h
    internal scheduler picks it up. Wired into the OAuth success paths so a new
    Gmail account gets near-realtime push immediately instead of waiting up to
    24h for the renewal cron (the only thing that used to enrol watch-less
    accounts). 2026-07 fix.
    """
    topic = os.environ.get(DEFAULT_TOPIC_ENV)
    if not topic:
        logger.debug("enroll_gmail_watch_async skip: %s not set", DEFAULT_TOPIC_ENV)
        return

    def _worker(_email: str = email, _topic: str = topic) -> None:
        session = None
        try:
            session = get_session()
            account = (
                session.query(Account).filter(Account.email == _email).first()
            )
            if not account or account.provider != "gmail":
                return
            _enroll_watch(session, account, _topic)
            session.commit()
            logger.info("Gmail watch enrolled on connect for %s", _email)
        except Exception as e:
            logger.warning("Auto Gmail watch enrolment failed for %s: %s", _email, e)
        finally:
            if session is not None:
                session.close()

    threading.Thread(target=_worker, daemon=True, name="GmailWatchEnroll").start()


@gmail_push_bp.route("/api/gmail/watch/start", methods=["POST"])
def start_gmail_watch():
    """Open or renew a Gmail watch on the given account."""
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    topic = data.get("topic") or os.environ.get(DEFAULT_TOPIC_ENV)
    label_ids = data.get("label_ids") or ["INBOX"]

    if not account_id:
        return jsonify({"error": "account_id required"}), 400
    if not topic:
        return jsonify({
            "error": "no Pub/Sub topic configured",
            "hint": f"set {DEFAULT_TOPIC_ENV} env var or pass 'topic' in body",
        }), 400

    # F-08 (audit issue #209, 2026-04-29): reject `topic` values not on
    # the server-side allow-list. Without this, an attacker with any
    # JWT could redirect a victim's Gmail Pub/Sub stream to a topic
    # they control.
    if not _topic_is_allowed(topic):
        logger.warning("Gmail watch start rejected: topic %s not in allow-list", topic)
        return jsonify({"error": "topic not permitted"}), 403

    session = get_session()
    try:
        account: Optional[Account] = session.query(Account).get(int(account_id))
        if not account:
            return jsonify({"error": "account not found"}), 404
        if account.provider != "gmail":
            return jsonify({"error": "watch only supported for gmail provider"}), 400
        # F-08: verify the JWT caller owns this account before issuing
        # a watch. Previously any authenticated user could issue or
        # cancel a watch on any account by passing its int id.
        if not _account_is_owned_by_caller(account):
            return jsonify({"error": "account not found"}), 404

        try:
            response = _enroll_watch(session, account, topic, label_ids)
        except WatchAuthError:
            return jsonify({"error": "gmail authentication failed"}), 401
        session.commit()

        return jsonify({
            "status": "ok",
            "history_id": response.get("historyId"),
            "expiration": (
                account.gmail_watch_expiration.isoformat()
                if account.gmail_watch_expiration else None
            ),
            "topic": topic,
        }), 200
    except Exception:
        # Audit 2026-04-25 (sub-report 01 MED-03): don't leak Google API
        # error internals (project IDs, scopes, token states) to clients.
        logger.exception("Failed to start Gmail watch for account %s", account_id)
        return jsonify({"error": "Could not start Gmail watch"}), 500
    finally:
        session.close()


@gmail_push_bp.route("/api/gmail/watch/stop", methods=["POST"])
def stop_gmail_watch():
    """Cancel any active Gmail Pub/Sub watch on the given account."""
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    if not account_id:
        return jsonify({"error": "account_id required"}), 400

    session = get_session()
    try:
        account: Optional[Account] = session.query(Account).get(int(account_id))
        if not account:
            return jsonify({"error": "account not found"}), 404
        # F-08 (audit issue #209, 2026-04-29): ownership check.
        # Previously any authenticated user could cancel a watch on any
        # other Gmail account by passing its int id, knocking the
        # victim off near-realtime sync.
        if not _account_is_owned_by_caller(account):
            return jsonify({"error": "account not found"}), 404

        import hashlib
        token_hash_id = hashlib.sha256(f"gmail:{account.email}".encode()).hexdigest()[:16]

        from app.providers.gmail_adapter import GmailAdapter
        adapter = GmailAdapter(account_id=token_hash_id)
        if not adapter.authenticate():
            return jsonify({"error": "gmail authentication failed"}), 401
        ok = adapter.stop_watch()
        account.gmail_watch_expiration = None
        account.gmail_watch_topic = None
        session.commit()
        return jsonify({"status": "ok" if ok else "failed"}), 200
    except Exception:
        logger.exception("Failed to stop Gmail watch for account %s", account_id)
        return jsonify({"error": "Could not stop Gmail watch"}), 500
    finally:
        session.close()


@gmail_push_bp.route("/api/gmail/watch/renew-due", methods=["POST"])
@_require_admin_or_observability_token
def renew_due_watches():
    """
    Renew every Gmail watch that expires within the next 24 hours.

    Designed to be hit by a daily scheduler (GitHub Actions cron). Idempotent:
    re-issuing watch() within the validity period is explicitly supported by
    Gmail and just resets the expiration.

    H-4 (audit security.md, issue #530): admin-only. Avant le fix, l'endpoint
    était auth-gated mais ouvert à tout user authentifié — un attaquant
    pouvait force-refresh tous les watches Gmail au choix du topic Pub/Sub
    du serveur, déclenchant des dépenses Pub/Sub dupliquées et drainant le
    quota Google de renew. Les sibling endpoints `start_gmail_watch` et
    `stop_gmail_watch` ont déjà un check `_account_is_owned_by_caller` ;
    ici l'iteration sur TOUS les comptes ne peut pas être ownership-scopée
    par construction (c'est un cron op). `@require_admin` est la garde
    naturelle, cohérente avec `/push/broadcast` (#523) et `/api/sync/trigger`
    (#535). Le workflow `.github/workflows/gmail-watch-renew.yml` utilise le
    token interne `OBSERVABILITY_TOKEN`, comme les sentinelles L3.
    """
    if request.args.get("async", "").lower() in {"1", "true", "yes"}:
        _start_renew_due_watches_background()
        return jsonify({"status": "queued"}), 202

    payload, status_code = _renew_due_watches_payload()
    return jsonify(payload), status_code


def _start_renew_due_watches_background() -> None:
    thread = threading.Thread(
        target=_run_renew_due_watches_background,
        daemon=True,
        name="GmailWatchRenewDue",
    )
    thread.start()


def _run_renew_due_watches_background() -> None:
    payload, status_code = _renew_due_watches_payload()
    if status_code >= 400 or payload.get("failed"):
        logger.warning(
            "Gmail watch renew async completed with status=%s payload=%s",
            status_code,
            payload,
        )


def _is_terminal_auth_failure(token_hash_id: str, reason: str) -> bool:
    """L'échec d'auth est-il DÉFINITIF (par opposition à transitoire) ?

    `GmailAdapter.authenticate()` renvoie False aussi bien pour un refresh
    token révoqué que pour un 500 de Google. Les traiter pareil serait le
    pire des deux mondes : soit on désactive des comptes sains lors d'un
    incident Google, soit le cron reste rouge à vie sur un compte mort (12
    jours consécutifs constatés au 2026-08-07) et n'alerte donc plus de rien.

    Deux signaux définitifs, tous deux hors du contrôle d'un retry :
      - `invalid_grant` : l'utilisateur a retiré l'accès depuis son compte
        Google, ou le refresh token a expiré. Aucune reconnexion automatique
        n'est possible.
      - plus aucun token en base pour ce compte : rien à rafraîchir.

    Tout le reste (réseau, 5xx, timeout) est transitoire et doit continuer à
    faire échouer le cron.
    """
    if "invalid_grant" in reason:
        return True
    try:
        from app.api.oauth import get_tokens_server
        tokens = get_tokens_server(token_hash_id)
    except Exception:
        # Store injoignable : on ne peut RIEN conclure — surtout pas
        # désactiver. On laisse le cron échouer, c'est son rôle.
        logger.warning("Token store unreachable while classifying auth failure", exc_info=True)
        return False
    return not (tokens and (tokens.get("refresh_token") or tokens.get("access_token")))


def _deactivate_unauthenticable_account(account) -> None:
    """Remet le compte dans le même état qu'une déconnexion explicite.

    Miroir de `app/api/oauth.py` (flow DISCONNECT) : sans ce reset,
    `sync_service` continue de poller un compte sans token toutes les 2 min
    (auth-backoff burn + log spam) et `last_history_id` d'une session morte
    serait rejoué à la reconnexion → historyExpired + lignes email_labels
    fantômes.
    """
    account.is_active = False
    account.last_history_id = None
    account.gmail_watch_expiration = None
    account.gmail_watch_topic = None


def _renew_due_watches_payload() -> tuple[dict, int]:
    from datetime import timedelta

    session = get_session()
    renewed: list[dict] = []
    failed: list[dict] = []
    deactivated: list[dict] = []
    try:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=24)
        accounts = (
            session.query(Account)
            .filter(Account.provider == "gmail")
            .filter(Account.is_active.is_(True))
            .filter(
                (Account.gmail_watch_expiration.is_(None))
                | (Account.gmail_watch_expiration <= cutoff)
            )
            .all()
        )

        topic = os.environ.get(DEFAULT_TOPIC_ENV)
        if not topic:
            return {"error": f"{DEFAULT_TOPIC_ENV} not set"}, 400

        import hashlib
        from app.providers.gmail_adapter import GmailAdapter
        for account in accounts:
            try:
                token_hash_id = hashlib.sha256(f"gmail:{account.email}".encode()).hexdigest()[:16]
                adapter = GmailAdapter(account_id=token_hash_id)
                if not adapter.authenticate():
                    reason = adapter.auth_failure_reason or "gmail authentication failed"
                    if _is_terminal_auth_failure(token_hash_id, reason):
                        # Compte irrécupérable sans action de l'utilisateur :
                        # on le sort du périmètre au lieu de le réessayer
                        # chaque nuit pour l'éternité.
                        _deactivate_unauthenticable_account(account)
                        logger.warning(
                            "Account %s (%s) deactivated — unauthenticable: %s",
                            account.id, account.email, reason,
                        )
                        deactivated.append({
                            "account_id": account.id,
                            "email": account.email,
                            "reason": reason,
                        })
                        continue
                    raise RuntimeError(f"gmail authentication failed: {reason}")
                response = adapter.start_watch(topic_name=topic, label_ids=["INBOX"])
                exp_ms = response.get("expiration")
                if exp_ms is not None:
                    account.gmail_watch_expiration = datetime.fromtimestamp(
                        int(exp_ms) / 1000.0, tz=timezone.utc
                    )
                account.gmail_watch_topic = topic
                renewed.append({"account_id": account.id, "email": account.email})
            except Exception as e:
                logger.error("Renew failed for account %s: %s", account.id, e)
                failed.append({"account_id": account.id, "email": account.email, "error": str(e)})
        session.commit()

        return {"renewed": renewed, "failed": failed, "deactivated": deactivated}, 200
    except Exception as e:
        logger.exception("renew_due_watches failed")
        failed.append({"account_id": None, "email": None, "error": str(e)})
        return {"renewed": renewed, "failed": failed, "deactivated": deactivated}, 200
    finally:
        session.close()
