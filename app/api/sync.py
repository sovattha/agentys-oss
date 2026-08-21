# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Sync API Blueprint.

Provides endpoints for sync status, manual trigger, and history.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from app.api.admin import require_admin
from app.config import should_persist_email_content
from app.services.sync_service import get_sync_service

logger = logging.getLogger(__name__)

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")


def _owned_account_ids_for_caller() -> set[int] | None:
    """Return the set of DB account_ids owned by the JWT caller.

    Audit P0-002 (2026-04-28): returns None if caller is loopback / no JWT
    (Tauri desktop — keep legacy behavior, full visibility). Returns set()
    if caller is JWT-authenticated but owns no accounts (filter to empty).
    Returns the set of int ids otherwise.
    """
    from flask import has_request_context, g
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    if not has_request_context():
        return None
    auth_user = getattr(g, "auth_user", None)
    if not auth_user or not auth_user.get("email"):
        # Tauri loopback — no scope filter (legacy behavior).
        return None
    user_id = auth_user.get("id")
    try:
        with get_db_session() as session:
            repo = AccountRepository(session)
            if user_id is not None:
                accounts = repo.get_active_accounts_for_user(int(user_id))
                if accounts:
                    return {a.id for a in accounts}
            # Fallback: by email (covers legacy single-account where user_id is NULL)
            account = repo.get_by_email(auth_user["email"])
            if account:
                return {account.id}
    except Exception as e:
        logger.warning("owned_account_ids lookup failed: %s", e)
    return set()


def _safe_parse_date(value) -> datetime:
    """Parse une date reçue d'un provider, avec fallback robuste.

    Bug 2026-06-09 (liste 14:47 vs fil 18:47) : renvoie toujours de l'UTC NAÏF —
    un datetime aware stocké dans la colonne `Email.date` perd son offset au
    round-trip SQLite et l'heure murale locale se fait re-étiqueter Z ensuite.
    """
    from app.utils.dates import to_naive_utc, utc_now_naive

    normalized = to_naive_utc(value)
    if normalized is None:
        if value:
            logger.debug(f"Unparseable date '{value}', using utc now")
        return utc_now_naive()
    return normalized


@sync_bp.route("/status", methods=["GET"])
def get_sync_status() -> tuple:
    """
    Get current sync service status.

    Returns:
        JSON with sync status including:
        - is_running: Whether sync service is active
        - is_syncing: Whether a sync is in progress
        - last_sync_at: ISO timestamp of last sync
        - next_sync_at: ISO timestamp of next scheduled sync
        - sync_interval_seconds: Configured interval
    """
    sync_service = get_sync_service()

    if sync_service is None:
        return jsonify({
            "success": False,
            "error": "Sync service not initialized",
            "status": None
        }), 503

    status = sync_service.status
    # Expose les comptes dont l'OAuth est cassé (≥3 échecs consécutifs) pour
    # que l'UI puisse afficher une bannière "reconnecter" au lieu d'attendre
    # un sync qui n'arrivera jamais. Liste vide = état sain.
    reauth_required: list[int] = []
    try:
        result = sync_service.get_reauth_required_accounts()
        if isinstance(result, list):
            reauth_required = result
    except Exception as e:  # noqa: BLE001
        logger.debug("get_reauth_required_accounts failed: %s", e)

    # Audit P0-002 (2026-04-28): filter the global reauth list to the JWT
    # caller's owned account_ids so foreign tenants' OAuth state does not
    # leak via /api/sync/status.
    owned_ids = _owned_account_ids_for_caller()
    if owned_ids is not None:
        reauth_required = [aid for aid in reauth_required if aid in owned_ids]

    response: Dict[str, Any] = {
        "success": True,
        "status": {
            "is_running": status.is_running,
            "is_syncing": status.is_syncing,
            "last_sync_at": status.last_sync_at.isoformat() if status.last_sync_at else None,
            "next_sync_at": status.next_sync_at.isoformat() if status.next_sync_at else None,
            "sync_interval_seconds": status.sync_interval_seconds,
            "reauth_required_account_ids": reauth_required,
        }
    }

    return jsonify(response), 200


@sync_bp.route("/trigger", methods=["POST"])
@require_admin
def trigger_sync() -> tuple:
    """
    Trigger an immediate sync of ALL configured accounts. **Admin only**.

    Audit M-1 (issue #535, 2026-05-05): the endpoint was Bearer-gated but
    open to any authenticated user. `sync_service.trigger_sync()` iterates
    every configured mailbox in the singleton, so a single user could call
    this in a loop and amplify into a multi-tenant DoS that hits Gmail /
    Outlook rate limits for everybody. `@require_admin` is the simplest fix
    given the endpoint isn't called from the user-facing frontend (only from
    a dev e2e helper that is itself dead code, and the keyboard shortcut
    test which mocks the response). A per-caller `account_ids` refactor
    would be the right answer if/when a real "sync my accounts" UX appears.

    Returns:
        JSON indicating whether sync was triggered.
    """
    sync_service = get_sync_service()

    if sync_service is None:
        return jsonify({
            "success": False,
            "error": "Sync service not initialized"
        }), 503

    if not sync_service.is_running:
        return jsonify({
            "success": False,
            "error": "Sync service is not running"
        }), 503

    triggered = sync_service.trigger_sync()

    if triggered:
        logger.info("Manual sync triggered via API")
        return jsonify({
            "success": True,
            "message": "Sync triggered"
        }), 202
    else:
        return jsonify({
            "success": False,
            "error": "Sync already in progress"
        }), 409


@sync_bp.route("/jobs", methods=["POST"])
def create_sync_job() -> tuple:
    """Queue a provider sync for the caller's active account.

    This is the web-safe replacement for `GET /api/emails?force_refresh=true`:
    the request returns immediately and provider I/O runs in a bounded
    background job.
    """
    from flask import g
    from app.api.routes_helpers import (
        _NO_ACCOUNT_SENTINEL,
        require_owned_account_id,
    )
    from app.services.sync_jobs import enqueue_sync_job

    data = request.get_json(silent=True) or {}
    account_header = data.get("account_id") or request.headers.get("X-Account-Id")
    account_id = require_owned_account_id(account_header)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({
            "success": False,
            "error": "Account not found or not owned by caller",
            "code": "INVALID_ACCOUNT",
        }), 404

    folder = str(data.get("folder") or "inbox").lower()
    if folder not in {"inbox", "sent", "archived", "spam", "trash", "draft"}:
        return jsonify({
            "success": False,
            "error": f"Unknown folder: {folder}",
        }), 400

    try:
        limit = max(1, min(int(data.get("limit") or 50), 500))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit must be an integer"}), 400

    auth_user = getattr(g, "auth_user", None)
    user_id = None
    if auth_user and auth_user.get("id") is not None:
        try:
            user_id = int(auth_user["id"])
        except (TypeError, ValueError):
            user_id = None

    job = enqueue_sync_job(
        account_id=account_id,
        folder=folder,
        limit=limit,
        unread_only=bool(data.get("unread_only")),
        user_id=user_id,
        source=str(data.get("source") or "manual")[:32],
    )
    return jsonify({"success": True, "job": job}), 202


@sync_bp.route("/history", methods=["GET"])
def get_sync_history() -> tuple:
    """
    Get recent sync results.

    Query params:
        limit: Maximum number of results (default 10, max 100)

    Returns:
        JSON with last sync results per account.
    """
    sync_service = get_sync_service()

    if sync_service is None:
        return jsonify({
            "success": False,
            "error": "Sync service not initialized",
            "history": []
        }), 503

    # Get limit from query params
    try:
        limit = min(int(request.args.get("limit", 10)), 100)
    except (ValueError, TypeError):
        limit = 10

    status = sync_service.status
    # Audit P0-002 (2026-04-28): SyncStatus.last_results is a process-wide
    # global list. Filter to the JWT caller's owned account_ids so /history
    # does not leak foreign tenants' sync results.
    owned_ids = _owned_account_ids_for_caller()
    if owned_ids is not None:
        all_results = [r for r in status.last_results if r.account_id in owned_ids]
    else:
        all_results = list(status.last_results)
    results = all_results[:limit]

    # Convert SyncResult dataclasses to dicts
    history: List[Dict[str, Any]] = []
    for result in results:
        history.append({
            "account_id": result.account_id,
            "account_email": result.account_email,
            "success": result.success,
            "new_emails_count": result.new_emails_count,
            "error_message": result.error_message,
            "duration_ms": result.duration_ms,
        })

    response = {
        "success": True,
        "last_sync_at": status.last_sync_at.isoformat() if status.last_sync_at else None,
        "history": history
    }

    return jsonify(response), 200


@sync_bp.route("/full", methods=["GET", "POST"])
def full_sync_emails():
    """
    Force a full re-sync of emails from provider to cache.

    Phase 1 (fast, synchronous): Fetch headers only (~5-10s for 2000 emails)
      → store in SQLite, return immediately.
    Phase 2 (background): Fetch full bodies in a daemon thread
      → update SQLite records, notify frontend when done.
    """
    import threading
    from app.config import DEFAULT_CACHE_CONFIG
    from app.providers.factory import get_email_provider
    from app.db.database import get_db_session
    from app.db.repositories.email_repository import EmailRepository
    from app.db.repositories.account_repository import AccountRepository
    from app.db.models import Email

    fetch_limit = DEFAULT_CACHE_CONFIG.initial_sync_limit  # 2000

    provider = None
    try:
        # ISO-04 fix: scope to the JWT caller instead of "first active
        # account". Picking accounts[0] meant a request from user B could
        # trigger a full IMAP re-fetch into user A's emails table.
        from app.api.routes_helpers import (
            _resolve_account_id_for_user,
            _NO_ACCOUNT_SENTINEL,
            _is_web_request_context,
        )
        scoped_account_id = _resolve_account_id_for_user()
        if scoped_account_id is None or scoped_account_id == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "No active account for caller"}), 400

        # Get account provider type from DB (using the scoped account_id).
        with get_db_session() as session:
            account_repo = AccountRepository(session)
            account_row = account_repo.get(scoped_account_id)
            if account_row is None:
                return jsonify({"error": "No active account for caller"}), 400
            account_id = account_row.id
            provider_type = account_row.provider
            account_email = account_row.email

        # Audit P1-A6 (mother-of-all 2026-04-25) : `get_email_provider(provider_type=...)`
        # utilise les credentials du provider depuis l'environnement — donc si
        # deux comptes Gmail sont configurés, on tombe systématiquement sur
        # celui des ENV, pas celui du caller. Fix : router via l'AccountManager
        # qui a les OAuth tokens du compte spécifique. Fallback gracieux sur
        # env-based si le compte n'est pas dans l'AccountManager (legacy
        # single-user install, IMAP avec env-only).
        provider = None
        oauth_account_id = None
        try:
            from app.multi_accounts import get_account_manager, create_provider_for_account
            _mgr = get_account_manager()
            _config = _mgr.get_account_by_email(account_email) if account_email else None
            if _config is not None:
                oauth_account_id = getattr(_config, "id", None)
                provider = create_provider_for_account(_config)
                logger.info(
                    f"[ISO P1-A6] full_sync provider routed via AccountManager "
                    f"for account_id={account_id} email={account_email}"
                )
        except Exception as e:
            logger.warning(
                f"[ISO P1-A6] AccountManager lookup failed for {account_email}: {e}. "
                f"Falling back to env-based provider"
            )
        if provider is None:
            if _is_web_request_context():
                return jsonify({"error": "No email provider for account"}), 503
            provider = get_email_provider(provider_type=provider_type)

        if not provider.authenticate():
            return jsonify({"error": "Email provider authentication failed"}), 503

        # Try fetching from All Mail / Archive to include archived emails
        all_mail_folder = None
        imap_adapter = getattr(provider, '_imap', provider)
        conn = getattr(imap_adapter, '_connection', None)
        if conn:
            # Try Gmail names first, then Outlook/generic IMAP names
            _all_mail_candidates = [
                "[Gmail]/All Mail", "[Gmail]/Tous les messages",
                "Archive", "Archives", "INBOX.Archive",
            ]
            for folder_name in _all_mail_candidates:
                try:
                    test_status, _ = conn.select(f'"{folder_name}"', readonly=True)
                    if test_status == "OK":
                        all_mail_folder = folder_name
                        break
                except Exception:
                    continue

        # Phase 1: Header-only fetch (10-30x faster than full RFC822)
        headers_only = False
        if all_mail_folder:
            logger.info(f"Full sync: fetching {fetch_limit} headers from {all_mail_folder}")
            if hasattr(imap_adapter, 'get_message_headers'):
                emails = imap_adapter.get_message_headers(limit=fetch_limit, unread_only=False, folder=all_mail_folder)
                headers_only = True
            else:
                emails = imap_adapter.get_messages(limit=fetch_limit, unread_only=False, folder=all_mail_folder)
        else:
            logger.info(f"Full sync: fetching {fetch_limit} headers from INBOX")
            if hasattr(provider, 'get_message_headers'):
                emails = provider.get_message_headers(limit=fetch_limit, unread_only=False)
                headers_only = True
            else:
                emails = provider.get_messages(limit=fetch_limit, unread_only=False)

        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        # Store in cache
        with get_db_session() as session:
            repo = EmailRepository(session)
            synced_count = 0
            persist_content = should_persist_email_content()

            from app.utils.dates import cached_date_needs_heal, to_naive_utc

            for email in emails:
                # Audit 2026-04-25 (HIGH-Iso-3): scope by account_id so we
                # don't skip an email just because another tenant has the
                # same provider UID cached.
                existing_row = repo.get_by_email_id(email.id, account_id=account_id)
                if existing_row is not None:
                    # Bug 2026-06-09 (liste 14:47 vs fil 18:47) : les lignes écrites
                    # avant la normalisation UTC portent l'heure murale locale et ne
                    # se réparent jamais (les syncs incrémentaux ne les revisitent
                    # pas). Le full sync est LE levier de réparation explicite :
                    # réaligner la date cachée sur l'heure provider quand elle dérive.
                    _provider_date = to_naive_utc(getattr(email, 'received_at', None))
                    if cached_date_needs_heal(existing_row.date, _provider_date):
                        logger.info(
                            "Full sync: healing cached date for %s (%s -> %s)",
                            email.id, existing_row.date, _provider_date,
                        )
                        existing_row.date = _provider_date
                        session.flush()
                    continue

                cached_email = Email(
                    email_id=email.id,
                    account_id=account_id,
                    thread_id=getattr(email, 'conversation_id', None),
                    subject=email.subject,
                    sender=email.sender,
                    sender_name=email.sender_name,
                    recipients=None,
                    date=_safe_parse_date(email.received_at),
                    body_text=(getattr(email, 'body', None) or None) if persist_content else None,
                    # body_html=None means "never checked", "" means "confirmed no HTML"
                    # For headers_only sync, leave as None; for full sync, store "" if absent
                    body_html=(getattr(email, 'body_html', None) if headers_only else (getattr(email, 'body_html', None) or "")) if persist_content else None,
                    snippet=(getattr(email, 'body', '')[:200] if getattr(email, 'body', None) else '') if persist_content else None,
                    is_read=getattr(email, 'is_read', False) if isinstance(getattr(email, 'is_read', False), bool) else False,
                    is_starred=False,
                    attachments_meta='[{"has":true}]' if getattr(email, 'has_attachments', False) else None,
                    folder="inbox",
                )
                repo.create(cached_email)
                synced_count += 1

        logger.info(f"Full sync phase 1 complete: {synced_count} new emails cached (fetched {len(emails)} total, headers_only={headers_only})")

        if synced_count > 0:
            # Invalidate in-memory email cache so the next request hits SQLite
            try:
                from app.api.routes import _email_cache, _email_cache_lock
                with _email_cache_lock:
                    _email_cache.clear()
                logger.info("Full sync: cleared in-memory email cache")
            except Exception as _e:
                logger.warning("Full sync: failed to clear in-memory cache: %s", _e)

            try:
                # Isolation multi-compte : emit uniquement au propriétaire du sync.
                from app.api.websocket import emit_to_account
                emit_to_account("new_email", {"count": synced_count}, account_id)
            except Exception as _e:
                logger.warning(
                    "Full sync: failed to emit new_email WS to account=%s (%d email(s) synced but UI won't refresh): %s",
                    account_id, synced_count, _e,
                )

        # Phase 2: Background body fetch (only needed if phase 1 was headers-only)
        if headers_only and synced_count > 0:
            threading.Thread(
                target=_backfill_bodies,
                args=(provider_type, all_mail_folder, fetch_limit, account_id, oauth_account_id),
                daemon=True,
            ).start()

        return jsonify({
            "status": "completed",
            "fetched": len(emails),
            "new_cached": synced_count,
            "headers_only": headers_only,
            "message": f"Full sync complete: {synced_count} new emails cached ({len(emails)} fetched)",
        }), 200

    except Exception as e:
        logger.error(f"Full sync error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


def _backfill_bodies(
    provider_type: str,
    folder_name: str,
    fetch_limit: int,
    account_id: int,
    oauth_account_id: str | None = None,
):
    """
    Background: fetch full email bodies and update SQLite records.

    Runs after a header-only full sync to populate body_text/body_html
    for email detail views and body previews in the list.
    """
    from app.providers.factory import get_email_provider, get_pooled_provider
    from app.db.database import get_db_session
    from app.db.repositories.email_repository import EmailRepository

    if not should_persist_email_content():
        logger.info("Body backfill skipped in metadata-only mode")
        return

    provider = None
    try:
        provider = (
            get_pooled_provider(account_id=oauth_account_id)
            if oauth_account_id
            else get_email_provider(provider_type=provider_type)
        )
        if not provider.authenticate():
            logger.warning("Body backfill: authentication failed")
            return

        imap_adapter = getattr(provider, '_imap', provider)
        if folder_name:
            full_emails = imap_adapter.get_messages(limit=fetch_limit, unread_only=False, folder=folder_name)
        else:
            full_emails = provider.get_messages(limit=fetch_limit, unread_only=False)

        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        # Update SQLite records that have empty bodies
        with get_db_session() as session:
            repo = EmailRepository(session)
            updated = 0
            for em in full_emails:
                db_email = repo.get_by_email_id(em.id, account_id=account_id)
                if db_email and (not db_email.body_text or db_email.body_html is None):
                    if not db_email.body_text:
                        db_email.body_text = getattr(em, 'body', None)
                        if db_email.body_text:
                            db_email.snippet = db_email.body_text[:200]
                    if db_email.body_html is None:
                        db_email.body_html = getattr(em, 'body_html', None) or ""
                    updated += 1

            logger.info(f"Body backfill complete: {updated}/{len(full_emails)} emails updated")

        # Invalidate in-memory cache + notify frontend so previews appear
        if updated > 0:
            try:
                from app.api.routes import _email_cache, _email_cache_lock
                with _email_cache_lock:
                    _email_cache.clear()
            except Exception:
                pass
            try:
                from app.api.websocket import emit_to_account
                emit_to_account("new_email", {"count": updated}, account_id)
            except Exception:
                pass

        # Notify frontend that body backfill is complete (scoped au compte)
        try:
            from app.api.websocket import emit_to_account
            emit_to_account("sync_status", {
                "phase": "body_backfill",
                "status": "completed",
                "updated": updated,
                "total": len(full_emails),
            }, account_id)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Body backfill error: {type(e).__name__}: {e}")
        # Notify frontend of failure (scoped au compte)
        try:
            from app.api.websocket import emit_to_account
            emit_to_account("sync_status", {
                "phase": "body_backfill",
                "status": "error",
                "error": str(e),
            }, account_id)
        except Exception:
            pass
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass
