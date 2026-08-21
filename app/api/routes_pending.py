# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les Pending Drafts (brouillons en attente).

Endpoints:
- GET    /api/pending-drafts                          - Liste des brouillons en attente
- GET    /api/pending-drafts/<draft_id>               - Détail d'un brouillon
- GET    /api/pending-drafts/by-email/<email_id>      - Brouillon par email_id
- POST   /api/pending-drafts/<draft_id>/validate      - Valider et envoyer
- POST   /api/pending-drafts/<draft_id>/reject        - Rejeter un brouillon
- POST   /api/pending-drafts/<draft_id>/suggestion-clicked - Enregistrer clic suggestion
- PATCH  /api/pending-drafts/<draft_id>               - Mettre à jour contenu
- POST   /api/pending-drafts/<draft_id>/upgrade       - Legacy (410 Gone)
- DELETE /api/pending-drafts/<draft_id>               - Supprimer un brouillon
- POST   /api/pending-drafts/<draft_id>/explain       - Résumé LLM du pipeline
"""

import logging
import re
import time
from datetime import datetime, timezone

from flask import request, jsonify
from werkzeug.exceptions import HTTPException

from app.config import should_persist_email_content
from app.db.models.email import Email
from app.api.utils.errors import error_response

from .routes_helpers import (
    api_bp,
    _resolve_account_id_cached,
    _get_authenticated_provider,
    _validate_email_id,
    _sanitize_for_log,
    require_json,
    _evict_email_from_all_caches,
    _invalidate_folder_cache,
    _filter_self_sent_drafts,
    _detach_provider_from_request,
    _safe_call,
    _auto_archive_if_action,
)
import app.api.routes_helpers as _rh

logger = logging.getLogger(__name__)


def _draft_belongs_to_account(draft, current_account_id: str) -> bool:
    """Audit 2026-04-25 (CRIT-Iso-4 / sub-report 02 C-4): strict comparison.

    The previous truthy guard `if draft.account_id and str(draft.account_id) != ...`
    let drafts with `account_id is None` bypass the check entirely — letting
    any authenticated user act on legacy / daemon-path drafts that never had
    an account_id resolved. Now: empty/None account_id is treated as a
    *mismatch* (reject) so cross-account access through that hole is closed.

    Returns True when the draft is provably owned by the current account.
    """
    raw = getattr(draft, "account_id", None)
    if raw is None or str(raw).strip() == "":
        return False
    return str(raw) == str(current_account_id)


def _extract_greeting_closing(body: str) -> tuple:
    """Extrait la salutation (1re ligne) et la formule de clôture depuis un corps d'email envoyé."""
    lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
    greeting = ''
    closing = ''
    if lines:
        first = lines[0]
        if re.match(r'^(Bonjour|Bonsoir|Cher|Ch\u00e8re|Dear|Hi|Hello|Salut)\b', first, re.I) and len(first) <= 60:
            greeting = first
    for line in reversed(lines[:-1] if len(lines) > 1 else lines):
        if re.match(r'^(Cordialement|Bien \u00e0 vous|Bonne journ\u00e9e|Best regards|Kind regards|Sinc\u00e8rement|Merci|\u00c0 bient\u00f4t)\b', line, re.I):
            closing = line
            break
        if 2 <= len(line.split()) <= 5 and not re.search(r'[.!?]$', line):
            closing = line
            break
    return greeting, closing


def _normalize_emoji_marker(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


# =============================================================================
# PENDING DRAFTS ENDPOINTS
# =============================================================================


@api_bp.route("/pending-drafts", methods=["GET"])
def list_pending_drafts():
    """
    Liste les brouillons en attente de validation.
    ---
    tags:
      - Pending Drafts
    summary: Liste les brouillons générés automatiquement en attente
    parameters:
      - name: limit
        in: query
        description: Nombre maximum de brouillons à retourner
        schema:
          type: integer
          minimum: 1
          maximum: 100
          default: 50
    responses:
      200:
        description: Liste des brouillons en attente
    """
    limit = request.args.get("limit", 50, type=int)
    limit = max(1, min(100, limit))

    try:
        store = _rh._get_container().get_pending_draft_store()
        account_id_int = _resolve_account_id_cached()
        current_account_id = str(account_id_int)
        pending = store.get_pending(limit=limit, account_id=current_account_id)
        pending = _filter_self_sent_drafts(pending)
        # User policy 2026-05-13: the Drafts panel should ONLY surface
        # drafts the user explicitly opted into (Quick Step rules that
        # produce ``routing_tier="followup"``). The legacy AI reply-
        # suggestion pipeline (``routing_tier`` simple/standard/complex)
        # creates a PendingDraft every time the user hits "AI Generate"
        # in the reply composer, and those clutter the Drafts panel
        # forever even though they're context-bound to one inbox email.
        # User-typed compose drafts come from the FRONTEND saved-drafts
        # store and are unaffected by this filter.
        pending = [d for d in pending if (d.routing_tier or "") == "followup"]
        # Hide follow-up drafts whose snooze hasn't elapsed yet: while
        # snoozed they live in "Later" (SnoozedView / /pending-drafts/snoozed).
        # The wake-sweep flips the reminder to notified=True once delay_days
        # passes with no reply, which is what surfaces the draft here — with
        # its 🔁 chip. (Replied threads get the draft deleted, not surfaced.)
        pending = _filter_snoozed_followup_drafts(pending, account_id_int)
        snoozed_map = _build_snoozed_until_map(account_id_int)
        # Inherit the source thread's emoji marker so a `mark_with_emoji`
        # action that ran alongside `create_snoozed_followup_draft` shows
        # the same chip on the resulting draft row. Single source of truth:
        # `emails.emoji_marker_json`. Batch-fetch by (email_id, account_id)
        # so list rendering stays O(1) DB hits regardless of draft count.
        emoji_marker_map = _build_emoji_marker_map(
            account_id_int, [d.email_id for d in pending if d.email_id]
        )

        out: list[dict] = []
        for d in pending:
            summary = d.to_dict_summary()
            wake_at = snoozed_map.get(d.id)
            if wake_at:
                summary["snoozed_until"] = wake_at
            # Prefer the marker carried on the draft itself (set by
            # `create_snoozed_followup_draft` — reliable, timing-independent).
            # Fall back to the source thread's `mark_with_emoji` marker for
            # drafts that don't carry their own (e.g. a received-rule chain
            # that stamped the thread before a follow-up was queued).
            own_marker = _normalize_emoji_marker(getattr(d, "emoji_marker", None))
            source_marker = _normalize_emoji_marker(
                emoji_marker_map.get(d.email_id) if d.email_id else None
            )
            marker = own_marker or source_marker
            if marker:
                summary["emoji_marker"] = marker
            out.append(summary)

        return jsonify({
            "count": len(out),
            "pending_count": len(out),
            "drafts": out,
        })
    except Exception as e:
        logger.error(f"Error listing pending drafts: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


def _build_emoji_marker_map(
    account_id: int, email_ids: list[str]
) -> dict[str, dict]:
    """Return ``{draft.email_id: {emoji, text?, include_deadline?}}`` for the
    follow-up drafts whose source thread carries an `emoji_marker_json`.

    A follow-up draft's ``email_id`` is the **thread_id** (see
    ``create_snoozed_followup_draft``). ``mark_with_emoji`` stamps the
    *sent message* row — whose own ``email_id`` equals the thread_id for a
    cold send (first message of the thread) but DIFFERS from it on a reply.
    So we resolve by thread_id (falling back to email_id for legacy drafts
    that stored a bare message id), preferring the sent row's marker, and
    key the result back to the value the caller passes (the draft's
    ``email_id``). This makes the 🔁 chip surface on the draft row for both
    cold sends and replies.

    Single batched SELECT so the Drafts list payload pays one query no
    matter how many drafts. Missing/empty markers are simply absent.
    """
    if account_id <= 0 or not email_ids:
        return {}
    try:
        import json
        from sqlalchemy import select, or_
        from app.api.routes_helpers import get_db_session
        from app.db.models.email import Email

        id_set = set(email_ids)
        # best[key] = (is_sent, parsed) — prefer the sent row's marker so a
        # user-applied marker on the inbound message never shadows the 🔁
        # the follow-up chain stamped on the sent reply.
        best: dict[str, tuple[bool, dict]] = {}
        with get_db_session() as session:
            stmt = (
                select(
                    Email.thread_id,
                    Email.email_id,
                    Email.is_sent,
                    Email.emoji_marker_json,
                )
                .where(Email.account_id == account_id)
                .where(
                    or_(
                        Email.thread_id.in_(email_ids),
                        Email.email_id.in_(email_ids),
                    )
                )
                .where(Email.emoji_marker_json.is_not(None))
            )
            for thread_id, eid, is_sent, marker_json in session.execute(stmt):
                if not marker_json:
                    continue
                # Map this row back to the draft key the caller will look up.
                key = thread_id if thread_id in id_set else (
                    eid if eid in id_set else None
                )
                if key is None:
                    continue
                try:
                    parsed = json.loads(marker_json)
                except (TypeError, ValueError):
                    continue
                if not (isinstance(parsed, dict) and parsed.get("emoji")):
                    continue
                prev = best.get(key)
                # First marker wins, except a sent-row marker upgrades a
                # previously-recorded non-sent one.
                if prev is None or (bool(is_sent) and not prev[0]):
                    best[key] = (bool(is_sent), parsed)
        return {key: parsed for key, (_sent, parsed) in best.items()}
    except Exception as exc:  # noqa: BLE001
        # Belt-and-suspenders: a DB hiccup here MUST NOT break the Drafts list.
        # Worst case the chip is missing; the followup draft itself still renders.
        logger.debug(f"_build_emoji_marker_map failed: {exc}")
        return {}


def _build_snoozed_until_map(account_id: int) -> dict[str, str]:
    """Return ``{draft_id: wake_at_iso}`` for un-promoted draft_followup
    reminders owned by ``account_id``. Drafts NOT in this map have no
    active snooze (either never had one, or the wake sweep already
    promoted/cleaned it).
    """
    if account_id <= 0:
        return {}
    try:
        from app.services.reminder_service import list_draft_followups
        entries = list_draft_followups(account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"list_draft_followups failed in snoozed-until build: {exc}")
        return {}
    return {
        e.get("email_id", ""): e.get("reminder_date", "")
        for e in entries
        if not e.get("notified", False) and e.get("email_id")
    }


def _filter_snoozed_followup_drafts(drafts: list, account_id: int) -> list:
    """Hide PendingDrafts whose draft_followup reminder is still un-promoted.

    A draft created by `create_snoozed_followup_draft` is gated by a
    reminder entry with ``type="draft_followup"``. While ``notified=False``
    the draft is "in Later" — invisible in the main Drafts panel. The
    wake-time sweep (``sweep_woken_draft_followups``) flips ``notified=True``
    when the snooze elapses and the recipient hasn't replied, which is
    what surfaces the draft here.

    Drafts that have NO matching reminder entry (the common case for
    legacy / non-followup pending drafts) pass through unchanged.
    """
    if account_id <= 0 or not drafts:
        return drafts
    try:
        from app.services.reminder_service import list_draft_followups
        entries = list_draft_followups(account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"list_draft_followups failed in filter: {exc}")
        return drafts

    if not entries:
        return drafts

    snoozed_draft_ids: set[str] = {
        e.get("email_id", "")
        for e in entries
        if not e.get("notified", False)
    }
    if not snoozed_draft_ids:
        return drafts
    return [d for d in drafts if d.id not in snoozed_draft_ids]


@api_bp.route("/pending-drafts/snoozed", methods=["GET"])
def list_snoozed_followup_drafts():
    """Liste les pending drafts encore "in Later" (snoozed follow-ups).

    Used by the SnoozedView frontend to surface draft_followup-tier
    pending drafts that haven't reached their wake date yet. Returns both
    the draft summary and the wake date so the UI can render the
    "Snoozed" badge with a relative-time hint.

    Empty list when the account has no snoozed follow-ups — same shape as
    `/api/pending-drafts` so the frontend can render it identically.
    """
    try:
        account_id = _resolve_account_id_cached()
        if account_id <= 0:
            return jsonify({"count": 0, "drafts": []})

        from app.services.reminder_service import list_draft_followups
        entries = [
            e for e in list_draft_followups(account_id=account_id)
            if not e.get("notified", False)
        ]
        if not entries:
            return jsonify({"count": 0, "drafts": []})

        store = _rh._get_container().get_pending_draft_store()
        wake_by_draft_id = {e["email_id"]: e.get("reminder_date", "") for e in entries}

        from app.domain.entities.pending_draft import PendingDraftStatus
        out: list[dict] = []
        for draft_id, wake_at in wake_by_draft_id.items():
            draft = store.get_by_id(draft_id)
            if draft is None:
                continue
            if str(draft.account_id or "") != str(account_id):
                continue
            # Skip drafts the user already rejected/sent — the reject path
            # leaves the row in the store with status=REJECTED instead of
            # hard-deleting it. Without this filter the X button on a
            # snoozed-draft row would appear to do nothing (frontend filter
            # works locally but on next refresh the row reappears).
            if draft.status in (
                PendingDraftStatus.REJECTED,
                PendingDraftStatus.SENT,
                PendingDraftStatus.VALIDATED,
            ):
                continue
            # Use to_dict() (not to_dict_summary): the list is small —
            # typically a handful of in-flight snoozed drafts — and the
            # frontend clicks straight into PendingDraftDetail which needs
            # draft_body + email_body to render the editor. Using summary
            # here would force a second /api/pending-drafts/<id> roundtrip
            # on every click and render an "empty draft" splash in the
            # meantime.
            full = draft.to_dict()
            full["wake_at"] = wake_at
            out.append(full)

        out.sort(key=lambda d: d.get("wake_at", ""))
        return jsonify({"count": len(out), "drafts": out})
    except Exception as exc:
        logger.error(f"Error listing snoozed followup drafts: {exc}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/<draft_id>", methods=["GET"])
def get_pending_draft(draft_id: str):
    """
    Récupère un brouillon en attente par son ID.
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    try:
        store = _rh._get_container().get_pending_draft_store()
        draft = store.get_by_id(draft_id)

        if not draft:
            return jsonify({"error": "Pending draft not found"}), 404

        current_account_id = str(_resolve_account_id_cached())
        if not _draft_belongs_to_account(draft, current_account_id):
            return jsonify({"error": "Pending draft not found"}), 404

        return jsonify(draft.to_dict())
    except Exception as e:
        logger.error(f"Error getting pending draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/by-email/<email_id>", methods=["GET"])
def get_pending_draft_by_email(email_id: str):
    """
    Récupère un brouillon en attente par l'ID de l'email original.
    ---
    tags:
      - Pending Drafts
    summary: Récupère le brouillon associé à un email
    parameters:
      - name: email_id
        in: path
        required: true
        description: ID de l'email original
        schema:
          type: string
    responses:
      200:
        description: 'Réponse contenant le brouillon (ou {"draft": null} si aucun)'
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email ID format"}), 400

    try:
        store = _rh._get_container().get_pending_draft_store()
        current_account_id = str(_resolve_account_id_cached())
        # O(1) index lookup — avoids loading all drafts into memory (P1-002)
        draft = store.get_by_email_id(email_id, account_id=current_account_id)

        if draft:
            # Optional subject verification to prevent stale draft collisions
            # (IMAP UIDs can be reassigned after mailbox compaction)
            expected_subject = request.args.get("subject")
            if expected_subject and draft.email_subject:
                draft_subj = re.sub(r'^Re:\s*', '', draft.email_subject, flags=re.IGNORECASE).strip()
                expected_subj = re.sub(r'^Re:\s*', '', expected_subject, flags=re.IGNORECASE).strip()
                if draft_subj != expected_subj:
                    logger.warning(
                        f"Stale draft detected: draft subject '{draft.email_subject}' "
                        f"does not match expected '{expected_subject}' for email_id {email_id}"
                    )
                    return jsonify({"draft": None})
            return jsonify({"draft": draft.to_dict()})

        # L'absence de brouillon est un état normal (pas une erreur).
        # On renvoie 200 + draft: null pour éviter de polluer la console du navigateur.
        return jsonify({"draft": None})
    except Exception as e:
        logger.error(f"Error getting pending draft by email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/<draft_id>/validate", methods=["POST"])
def validate_pending_draft(draft_id: str):
    """
    Valide un brouillon en attente, le crée dans Gmail et l'envoie.

    Story 6-7: "Approuver et Envoyer" doit créer ET envoyer le brouillon.
    Le flux complet: Create Draft -> Send Draft -> Update Status to SENT.
    """
    _validate_total_t0 = time.perf_counter()
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    try:
        _load_t0 = time.perf_counter()
        store = _rh._get_container().get_pending_draft_store()
        pending = store.get_by_id(draft_id)

        if not pending:
            return jsonify({"error": "Pending draft not found"}), 404

        current_account_id = str(_resolve_account_id_cached())
        if not _draft_belongs_to_account(pending, current_account_id):
            return jsonify({"error": "Pending draft not found"}), 404
        logger.info(
            "[PERF-SEND] phase=validate_load_draft draft_id=%s account_id=%s "
            "email_id=%s ms=%s",
            _sanitize_for_log(draft_id),
            current_account_id,
            _sanitize_for_log(getattr(pending, "email_id", "")),
            int((time.perf_counter() - _load_t0) * 1000),
        )

        # Audit P1-015 (2026-04-28): capture account_id + provider AT REQUEST
        # START — before any lock acquisition or BG thread spawn — so that
        # background side-effects (mark_as_read, archive, learning, sent
        # cache insert) target the SAME mailbox the user authenticated
        # against. The previous code re-resolved "current account" inside
        # the BG thread; if the user switched accounts mid-flight, the BG
        # thread would use the NEW account's adapter against the OLD
        # account's UID → wrong mailbox marked read.
        _captured_account_id = int(current_account_id)
        _provider_t0 = time.perf_counter()
        provider = _get_authenticated_provider()
        logger.info(
            "[PERF-SEND] phase=validate_provider_ready draft_id=%s account_id=%s "
            "provider=%s ms=%s",
            _sanitize_for_log(draft_id),
            _captured_account_id,
            getattr(provider, "PROVIDER_NAME", provider.__class__.__name__),
            int((time.perf_counter() - _provider_t0) * 1000),
        )

        _prepare_t0 = time.perf_counter()
        # Append signature to draft body
        from app.utils.signature import append_signature
        body_with_signature = append_signature(
            pending.draft_body,
            account_id=_captured_account_id,
            recipient_email=pending.email_sender,
        )

        # Parse optional attachments from request body
        request_data_early = request.get_json(silent=True) or {}
        raw_attachments = request_data_early.get("attachments", [])
        attachments = None
        if raw_attachments:
            import base64
            attachments = []
            for att in raw_attachments:
                filename = att.get("filename", "attachment")
                data_b64 = att.get("data_base64", "")
                content_type = att.get("content_type", "application/octet-stream")
                try:
                    data_bytes = base64.b64decode(data_b64)
                except Exception:
                    continue
                attachments.append((filename, data_bytes, content_type))
            if not attachments:
                attachments = None

        # Parse optional CC/BCC from request body
        cc_raw = request_data_early.get("cc", [])
        bcc_raw = request_data_early.get("bcc", [])
        cc_list = [c.strip() for c in cc_raw if isinstance(c, str) and c.strip()] if cc_raw else None
        bcc_list = [b.strip() for b in bcc_raw if isinstance(b, str) and b.strip()] if bcc_raw else None
        logger.info(
            "[PERF-SEND] phase=validate_prepare draft_id=%s account_id=%s "
            "body_chars=%s attachments=%s cc_count=%s bcc_count=%s ms=%s",
            _sanitize_for_log(draft_id),
            _captured_account_id,
            len(body_with_signature or ""),
            len(attachments or []),
            len(cc_list or []),
            len(bcc_list or []),
            int((time.perf_counter() - _prepare_t0) * 1000),
        )

        # ── FAST PATH: single messages.send() instead of create_draft + send_draft ──
        gmail_draft_id = "sent-directly"
        send_success = False

        # BCC parity with routes_emails.py: Outlook's send_reply_directly handles
        # BCC, so don't fall through to the slower 2-step path on that provider
        # (audit Reply-MEDIUM-6 "BCC degrades to 2-step on Outlook").
        _provider_name = getattr(provider, 'PROVIDER_NAME', '')
        _provider_supports_bcc = _provider_name in ('outlook',)

        # Load the original inbox email before sending so providers can reuse
        # the provider thread_id. Gmail still fetches Message-ID metadata if
        # the row does not carry RFC reply headers.
        _orig_row = None
        _orig_row_t0 = time.perf_counter()
        try:
            from app.db.models.email import Email as _OrigEmail
            with _rh.get_db_session() as _qs_sess:
                _orig_row = (
                    _qs_sess.query(_OrigEmail)
                    .filter(
                        _OrigEmail.email_id == pending.email_id,
                        _OrigEmail.account_id == _captured_account_id,
                    )
                    .first()
                )
                if _orig_row is not None:
                    # Detach so later cache insert and re-eval code can read
                    # attributes safely after this session closes.
                    _qs_sess.expunge(_orig_row)
        except Exception as _orig_err:
            logger.debug(f"orig-row load suppressed: {_orig_err}")
        finally:
            logger.info(
                "[PERF-SEND] phase=validate_orig_row draft_id=%s account_id=%s "
                "found=%s ms=%s",
                _sanitize_for_log(draft_id),
                _captured_account_id,
                _orig_row is not None,
                int((time.perf_counter() - _orig_row_t0) * 1000),
            )

        # Acquire the per-draft lock that /refine writes through, so a refine
        # in flight can't be overwritten by a stale-body send mid-call
        # (audit Reply-HIGH-4 "refine/send race").
        _draft_lock = _rh._get_container().get_pending_draft_store().get_draft_lock(draft_id)
        _lock_wait_t0 = time.perf_counter()
        with _draft_lock:
            logger.info(
                "[PERF-SEND] phase=validate_lock_acquired draft_id=%s "
                "account_id=%s ms=%s",
                _sanitize_for_log(draft_id),
                _captured_account_id,
                int((time.perf_counter() - _lock_wait_t0) * 1000),
            )
            # Re-read draft body inside the lock — a concurrent /refine may have
            # finished and written a new body between our store.get_by_id above
            # and now.
            _fresh = store.get_by_id(draft_id)
            if _fresh:
                pending = _fresh
                body_with_signature = append_signature(
                    pending.draft_body,
                    account_id=_captured_account_id,
                    recipient_email=pending.email_sender,
                )

            # RACE-002: idempotency guard — if a concurrent validate already sent this
            # draft, return 409 instead of double-sending.
            from app.domain.entities.pending_draft import PendingDraftStatus as _PDS
            if pending.status not in (
                _PDS.PENDING, _PDS.MODIFIED, _PDS.VALIDATED
            ):
                return error_response(
                    "DRAFT_ALREADY_PROCESSED",
                    "This draft has already been processed",
                    409,
                    extra={"status": pending.status.value},
                )

            if hasattr(provider, 'send_reply_directly') and (not bcc_list or _provider_supports_bcc):
                _send_kwargs = dict(
                    to=[pending.email_sender],
                    subject=pending.draft_subject,
                    body=body_with_signature,
                    reply_to_id=pending.email_id,
                    cc=cc_list,
                    attachments=attachments,
                    thread_id=_orig_row.thread_id if _orig_row is not None else None,
                    is_html=True,
                )
                if _provider_supports_bcc and bcc_list:
                    _send_kwargs["bcc"] = bcc_list
                _direct_send_t0 = time.perf_counter()
                fast_result = provider.send_reply_directly(**_send_kwargs)
                logger.info(
                    "[PERF-SEND] phase=validate_send_direct draft_id=%s "
                    "account_id=%s success=%s ms=%s",
                    _sanitize_for_log(draft_id),
                    _captured_account_id,
                    bool(fast_result),
                    int((time.perf_counter() - _direct_send_t0) * 1000),
                )
                if fast_result:
                    send_success = True
                    gmail_draft_id = fast_result  # actual message ID from provider

            if not send_success:
                # Fallback: 2-step create_draft + send_draft (still inside the
                # draft lock so refine can't overwrite mid-send).
                _create_t0 = time.perf_counter()
                gmail_draft_id = provider.create_draft(
                    to=[pending.email_sender],
                    subject=pending.draft_subject,
                    body=body_with_signature,
                    reply_to_id=pending.email_id,
                    cc=cc_list,
                    bcc=bcc_list,
                    is_html=True,
                    attachments=attachments,
                )
                logger.info(
                    "[PERF-SEND] phase=validate_create_draft draft_id=%s "
                    "account_id=%s success=%s ms=%s",
                    _sanitize_for_log(draft_id),
                    _captured_account_id,
                    bool(gmail_draft_id),
                    int((time.perf_counter() - _create_t0) * 1000),
                )
                if not gmail_draft_id:
                    # Retry without reply_to_id — thread may have been archived/moved
                    logger.warning(f"create_draft with reply_to_id failed for {_sanitize_for_log(pending.email_id)}, retrying without thread context")
                    _create_retry_t0 = time.perf_counter()
                    gmail_draft_id = provider.create_draft(
                        to=[pending.email_sender],
                        subject=pending.draft_subject,
                        body=body_with_signature,
                        cc=cc_list,
                        bcc=bcc_list,
                        is_html=True,
                        attachments=attachments,
                    )
                    logger.info(
                        "[PERF-SEND] phase=validate_create_draft_retry "
                        "draft_id=%s account_id=%s success=%s ms=%s",
                        _sanitize_for_log(draft_id),
                        _captured_account_id,
                        bool(gmail_draft_id),
                        int((time.perf_counter() - _create_retry_t0) * 1000),
                    )
                if not gmail_draft_id:
                    last_err = getattr(provider, '_last_error', '') or ''
                    err_msg = f"Échec d'envoi: {last_err}" if last_err else "Failed to create draft"
                    return jsonify({"error": err_msg}), 500
                _send_draft_t0 = time.perf_counter()
                send_success = provider.send_draft(gmail_draft_id)
                logger.info(
                    "[PERF-SEND] phase=validate_send_draft draft_id=%s "
                    "account_id=%s success=%s ms=%s",
                    _sanitize_for_log(draft_id),
                    _captured_account_id,
                    bool(send_success),
                    int((time.perf_counter() - _send_draft_t0) * 1000),
                )

            # Audit P0-003 + P1-013 (2026-04-28): commit the SENT status
            # transition INSIDE the lock, BEFORE releasing it. The previous
            # layout released the lock immediately after send_email returned,
            # then updated status outside. Two concurrent /validate calls
            # could both pass the line-287 idempotency check (status still
            # PENDING/MODIFIED/VALIDATED), both call send_reply_directly
            # serialized by the lock, but the second one would only see
            # SENT *after* it had already issued a duplicate provider call.
            # Now: status flips to SENT before the next thread can acquire
            # the lock + re-read; the second thread will hit the 409 guard.
            from app.domain.entities.pending_draft import PendingDraftStatus
            if send_success:
                _status_emit_t0 = time.perf_counter()
                store.update_status(draft_id, PendingDraftStatus.SENT, gmail_draft_id=gmail_draft_id)
                # P1-013: emit the completion-signaling WS event INSIDE the
                # lock + AFTER update_status commits, so the UI cannot
                # receive "validated/sent" while Redux still considers the
                # draft eligible for /validate.
                try:
                    from app.api.websocket import emit_email_sent
                    emit_email_sent(
                        pending.email_id,
                        account_id=_captured_account_id,
                        is_reply=True,
                    )
                except Exception as _ws_err:
                    logger.debug(f"emit_email_sent failed: {_ws_err}")
                logger.info(
                    "[PERF-SEND] phase=validate_status_emit draft_id=%s "
                    "account_id=%s ms=%s",
                    _sanitize_for_log(draft_id),
                    _captured_account_id,
                    int((time.perf_counter() - _status_emit_t0) * 1000),
                )

        if not send_success:
            from app.domain.entities.pending_draft import PendingDraftStatus
            # SIL-001: revert to PENDING so the user can retry from Agentys.
            # VALIDATED was previously set here but is excluded from the daemon
            # view, orphaning the draft indefinitely.
            store.update_status(draft_id, PendingDraftStatus.PENDING)
            logger.error(f"Draft created but send failed: {_sanitize_for_log(gmail_draft_id)}")
            logger.info(
                "[PERF-SEND] phase=validate_total draft_id=%s account_id=%s "
                "success=False ms=%s",
                _sanitize_for_log(draft_id),
                _captured_account_id,
                int((time.perf_counter() - _validate_total_t0) * 1000),
            )
            return jsonify({
                "error": "Email created as draft but failed to send",
                "draft_id": draft_id,
                "gmail_draft_id": gmail_draft_id,
            }), 500

        # ── SUCCESS: status already flipped to SENT inside the lock above.
        #    Remaining side-effects (sent cache insert, BG mark-read, etc.)
        #    are NOT race-critical for double-send and stay outside the lock.
        request_data = request.get_json(silent=True) or {}
        archive_requested = request_data.get("archive", False)
        _evict_email_from_all_caches(pending.email_id)

        # Follow-up relance just sent → drop its pin so the woken follow-up
        # leaves the "Pinned" section of both inbox and Drafts. The pin id is
        # the thread_id, which is exactly pending.email_id for these drafts.
        if getattr(pending, "routing_tier", "") == "followup" and pending.email_id:
            from app.services.pinned_emails import remove_pinned_email_id
            remove_pinned_email_id(_captured_account_id, pending.email_id)

        # Insert sent reply into SQLite for immediate visibility in "Envoyés".
        # P1-015: use _captured_account_id, not a fresh re-resolution, so an
        # account switch mid-flight does not insert into the wrong mailbox.
        _cache_insert_t0 = time.perf_counter()
        try:
            _account_id = _captured_account_id
            with _rh.get_db_session() as _sess:
                _repo = _rh.EmailRepository(_sess)
                _now = datetime.now(timezone.utc).replace(tzinfo=None)
                _persist_content = should_persist_email_content()
                _sent_email = Email(
                    email_id=f"reply-{int(_now.timestamp())}",
                    account_id=_account_id,
                    # Stamp the original thread so thread_has_user_reply and
                    # other thread-scoped Quick Step triggers see this reply.
                    thread_id=_orig_row.thread_id if _orig_row is not None else None,
                    subject=pending.draft_subject or '',
                    sender=getattr(provider, '_email', '') or '',
                    sender_name='',
                    recipients=pending.email_sender or '',
                    date=_now,
                    body_text=(pending.draft_body or '') if _persist_content else None,
                    body_html='' if _persist_content else None,
                    snippet=(pending.draft_body or '')[:200] if _persist_content else None,
                    is_read=True,
                    is_starred=False,
                    is_sent=True,
                    attachments_meta=None,
                )
                _repo.create(_sent_email)
                # Collapse rapid double-fires (same thread, same minute) so the
                # frontend's thread badge doesn't show (2) for a single reply.
                try:
                    _repo.dedupe_sent_by_content(_account_id)
                except Exception as _dedup_err:
                    logger.debug(f"reply dedupe failed: {_dedup_err}")
                _sess.commit()
        except Exception as _ins_err:
            # SIL-002: log as ERROR so operators see it; email was delivered but
            # won't appear in Sent folder until next sync — risk of duplicate send.
            logger.error(f"Failed to insert sent reply into cache: {_ins_err}")
        finally:
            logger.info(
                "[PERF-SEND] phase=validate_cache_insert draft_id=%s "
                "account_id=%s ms=%s",
                _sanitize_for_log(draft_id),
                _captured_account_id,
                int((time.perf_counter() - _cache_insert_t0) * 1000),
            )

        _invalidate_folder_cache("sent")

        # Quick Steps: re-evaluate auto-triggers on the original inbox email
        # so a rule like ``thread_has_user_reply=true → archive`` fires once
        # the reply has been sent. Per-(step, email) dedup in run_auto_triggers
        # prevents double-fires across arrival / mark-read / reply-sent.
        try:
            from app.quicksteps.auto_trigger import run_auto_triggers_async
            if _orig_row is not None:
                run_auto_triggers_async(
                    _captured_account_id, pending.email_id, _orig_row
                )
        except Exception as _qs_err:
            logger.debug(f"post-reply qs re-eval suppressed: {_qs_err}")

        # Status was already updated to SENT inside the lock above
        # (audit P0-003). Do NOT update again here — the prior duplicate
        # call was harmless but obscured the race-fix locality.
        logger.info(f"Email sent successfully: {_sanitize_for_log(draft_id)}")

        # Record recap metrics (reply time + activity)
        try:
            from app.services.recap_tracker import get_recap_tracker
            _rt = get_recap_tracker()
            # Scope recap metrics to the sending account (audit 2026-05-29) so
            # one tenant's reply-times / active-days don't bleed into another's
            # monthly recap.
            _recap_aid = getattr(pending, "account_id", None)
            _rt.record_reply_time(pending.email_received_at or "", account_id=_recap_aid)
            _rt.record_activity(account_id=_recap_aid)
        except Exception:
            pass

        # Build response immediately — all remaining work in background
        response_data = {
            "success": True,
            "draft_id": draft_id,
            "gmail_draft_id": gmail_draft_id,
            "sent": True,
            "message": "Email sent successfully"
        }

        # Jargon detection: suggest terms the user added that the AI didn't know
        try:
            if pending.draft_v1 and pending.draft_body:
                from app.jargon_detection import detect_jargon_from_correction
                jargon_hits = detect_jargon_from_correction(
                    original_draft=pending.draft_v1,
                    sent_body=pending.draft_body,
                )
                if jargon_hits:
                    response_data["knowledge_suggestions"] = [
                        {
                            "question": h.term,
                            "answer": h.term,
                            "context": h.context,
                            "category": "FAQ",
                        }
                        for h in jargon_hits
                    ]
        except Exception:
            pass  # Never block send for jargon detection

        # ── BACKGROUND: mark_as_read + archive + learning + commitments + followup ──
        _peid = pending.email_id
        _do_archive = archive_requested
        _pending = pending
        _draft_id = draft_id
        _req_data = request_data

        # P1-015 (2026-04-28): use the account_id captured at request entry,
        # not a fresh re-resolution. If the user switched accounts between
        # request entry and now, _resolve_account_id_cached() would return
        # the NEW account, but `provider` (closure-captured below) is still
        # bound to the OLD one — leading to wrong-mailbox writes.
        _resolved_acct_id = _captured_account_id

        _detach_provider_from_request(provider)

        def _post_send_all_bg():
            try:
                # 0. Bump Contact.sent_count + ensure ContactStyleProfile for recipient.
                # account_id falls back to _resolved_acct_id (audit Reply-MEDIUM-5
                # "account_id plumbing inconsistent in 6 call sites") — the
                # frontend doesn't always pass account_id in the request body.
                try:
                    from app.api.routes_helpers import record_sent_recipients
                    _rcpt = _pending.email_sender
                    _all_rcpts = [_rcpt] if _rcpt else []
                    _extra_cc = _req_data.get("cc")
                    if _extra_cc:
                        _all_rcpts.extend(_extra_cc)
                    _extra_bcc = _req_data.get("bcc")
                    if _extra_bcc:
                        _all_rcpts.extend(_extra_bcc)
                    # TRUST-001: always use the server-resolved account_id.
                    _rc_acct = _resolved_acct_id
                    record_sent_recipients(_rc_acct, _all_rcpts)
                except Exception as _rc_err:
                    logger.debug(f"record_sent_recipients (pending-send) failed: {_rc_err}")

                # 1. Mark as read + archive (parallel)
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as pool:
                    pool.submit(_safe_call, provider.mark_as_read, _peid)
                    if _do_archive:
                        pool.submit(_safe_call, provider.archive_email, _peid)
                    else:
                        pool.submit(_auto_archive_if_action, provider, _peid)

                # Re-evict cache after archive completes (prevents stale cache race)
                _evict_email_from_all_caches(_peid)
                try:
                    from app.api.websocket import emit_email_archived
                    # S-07 parity (audit Reply-HIGH-1): pass account_id so the
                    # event routes via emit_to_account instead of falling
                    # through to the no-op "no per-user room" branch.
                    emit_email_archived(_peid, account_id=_resolved_acct_id)
                except Exception as _wa_err:
                    logger.debug(f"emit_email_archived failed: {_wa_err}")

                # 2. Learning recording
                try:
                    from app.draft_learning import get_draft_learning_store
                    learning_store = get_draft_learning_store(account_id=_resolved_acct_id if _resolved_acct_id and _resolved_acct_id > 0 else None)
                    if _pending.draft_v1 and _pending.draft_body:
                        recorded = learning_store.record_correction(
                            email_id=_pending.email_id,
                            original_draft=_pending.draft_v1,
                            sent_body=_pending.draft_body,
                            contact=_pending.email_sender,
                        )
                        if not recorded:
                            learning_store.record_positive(
                                email_id=_pending.email_id,
                                draft_body=_pending.draft_body,
                                contact=_pending.email_sender or "",
                                email_subject=_pending.email_subject or "",
                                routing_tier=_pending.routing_tier or "",
                            )
                        else:
                            # Incrémenter le compteur et lancer extraction si seuil atteint
                            learning_store._corrections_since_extraction += 1
                            if learning_store.should_extract_rules():
                                def _extract_rules_bg():
                                    try:
                                        from app.draft_learning import extract_rules_from_corrections
                                        added = extract_rules_from_corrections(learning_store)
                                        if added:
                                            from app.api.websocket import emit_learning_rule_extracted
                                            for rule in added:
                                                emit_learning_rule_extracted(
                                                    rule_id=rule["id"],
                                                    rule_text=rule["rule_text"],
                                                    category=rule.get("category", "contenu"),
                                                    account_id=_resolved_acct_id,
                                                )
                                    except Exception as _re_err:
                                        # SIL-007: was silently swallowed; now visible in logs.
                                        logger.warning("Rule extraction failed: %s", _re_err)
                                _rh.submit_background(_extract_rules_bg)
                        sent_unmodified = not recorded
                        orig_len = max(len(_pending.draft_v1.strip()), 1)
                        diff_len = abs(len(_pending.draft_v1.strip()) - len(_pending.draft_body.strip()))
                        edit_ratio = min(diff_len / orig_len, 1.0) if recorded else 0.0
                    else:
                        sent_unmodified = False
                        edit_ratio = 0.0
                except Exception:
                    sent_unmodified = False
                    edit_ratio = 0.0

                # 2a-bis. Mise à jour incrémentale du profil de style.
                # Use an explicit None check — `or` would wrongly fall through on
                # a legitimate account_id of 0/"" (shouldn't happen, but the
                # explicit form keeps the intent unambiguous).
                # TRUST-001: ignore client-supplied account_id; always use the
                # server-resolved value so a crafted request body cannot write
                # style data into another user's profile.
                _bg_account_id = _resolved_acct_id
                try:
                    if _pending.draft_body and _bg_account_id:
                        from app.domain.entities.email import Email as DomainEmail
                        import asyncio
                        container = _rh._get_container()
                        style_svc = container.get_writing_style_service()
                        sent_email = DomainEmail(
                            id=_pending.email_id,
                            subject=_pending.draft_subject or "",
                            body=_pending.draft_body,
                            sender=_req_data.get("user_email", ""),
                            recipients=[_pending.email_sender or ""],
                        )
                        asyncio.run(style_svc.update_with_sent_email(
                            account_id=_bg_account_id,
                            email=sent_email,
                        ))
                        logger.info("Style profile updated incrementally after send")
                except Exception as exc:
                    logger.debug("Style profile incremental update skipped: %s", exc)

                # 2a-ter. Auto-apprentissage salutation/signature par contact
                # + auto-derivation of `formality_override` from the just-sent
                # body. Both passes share the same load/save round-trip so
                # we only hit the writing-style store once per send.
                try:
                    if _pending.draft_body and _pending.email_sender and _bg_account_id:
                        container = _rh._get_container()
                        style_svc2 = container.get_writing_style_service()
                        if style_svc2:
                            profile2 = style_svc2.get_profile(account_id=_bg_account_id)
                            if profile2:
                                contact2 = None
                                raw = profile2.contact_profiles.get(_pending.email_sender.lower())
                                if raw:
                                    from app.domain.entities.writing_style import ContactStyleProfile as _CSP
                                    contact2 = _CSP.from_dict(raw)
                                changed = False
                                if contact2:
                                    g, cl = _extract_greeting_closing(_pending.draft_body)
                                    if g and not contact2.preferred_greeting:
                                        # Tokenize the recipient's first name → {first_name}
                                        # so the stored greeting is a reusable template
                                        # (expanded at draft time via to_prompt_hint).
                                        if contact2.nickname:
                                            from app.prompts.identity import _tokenize_greeting
                                            g = _tokenize_greeting(g, contact2.nickname)
                                        from app.smart_routing import is_canonical_greeting_for_contact
                                        if is_canonical_greeting_for_contact(
                                            g, contact2.nickname or ""
                                        ):
                                            contact2.preferred_greeting = g
                                            changed = True
                                        else:
                                            logger.warning(
                                                "Auto greeting learning rejected "
                                                "preferred_greeting %r for contact %s",
                                                g[:80], _pending.email_sender,
                                            )
                                    if cl and not contact2.preferred_closing:
                                        contact2.preferred_closing = cl
                                        changed = True
                                    if changed:
                                        profile2.contact_profiles[_pending.email_sender.lower()] = contact2.to_dict()
                                # Formality auto-derivation (separate path —
                                # the helper handles the "locked" + "no-op
                                # when same level" cases internally).
                                from app.services.contact_formality import (
                                    update_contact_formality_from_send,
                                )
                                if update_contact_formality_from_send(
                                    profile2,
                                    _pending.email_sender,
                                    _pending.draft_body,
                                ):
                                    changed = True
                                if changed:
                                    style_svc2._store.save(profile2)
                                    logger.info(
                                        "Auto greeting/closing/formality learned for %s",
                                        _pending.email_sender,
                                    )
                except Exception as exc:
                    logger.debug("Auto greeting/closing/formality learning skipped: %s", exc)

                # 2b. Notifier le coordinateur de refresh automatique. account_id
                # falls back to _resolved_acct_id (audit Reply-MEDIUM-5).
                try:
                    from app.learning_refresh import get_refresh_coordinator
                    get_refresh_coordinator().on_email_sent(
                        email_id=_peid,
                        contact=_pending.email_sender,
                        had_correction=not sent_unmodified,
                        edit_ratio=edit_ratio,
                        account_id=_bg_account_id,
                        user_email=_req_data.get("user_email"),
                    )
                except Exception:
                    pass

                # 3. Quality tracking
                try:
                    from app.draft_quality_tracker import get_tracker
                    tracker = get_tracker()
                    tracker.record_send(
                        email_id=_pending.email_id,
                        contact=_pending.email_sender or "",
                        tier=_pending.routing_tier or "",
                        sent_unmodified=sent_unmodified,
                        edit_ratio=edit_ratio,
                        account_id=str(_bg_account_id or ""),
                    )
                    # Record interaction with length + CC for learning
                    _cc_str = ",".join(_req_data.get("cc", [])) if _req_data.get("cc") else ""
                    tracker.record_interaction(
                        email_id=_pending.email_id,
                        contact=_pending.email_sender or "",
                        action="reply",
                        sent_length=len(_pending.draft_body or ""),
                        cc_added=_cc_str,
                        account_id=str(_bg_account_id or ""),
                    )
                except Exception:
                    pass

                # 4. Commitment extraction. account_id falls back to
                # _resolved_acct_id (audit Reply-MEDIUM-5) so suggestions are
                # not orphaned to "" when the frontend omits account_id.
                try:
                    from app.agents import CommitmentExtractorAgent
                    from app.api.calendar import add_suggestion
                    extractor = CommitmentExtractorAgent()
                    commitments = extractor.extract(_pending.draft_body)
                    _commit_aid = _bg_account_id
                    for c in commitments:
                        add_suggestion(
                            email_id=_pending.email_id,
                            account_id=str(_commit_aid) if _commit_aid is not None else "",
                            description=c.description,
                            deadline=c.deadline,
                            email_subject=_pending.email_subject or _pending.draft_subject,
                            email_sender=_pending.email_sender,
                            draft_body=_pending.draft_body,
                        )
                except Exception:
                    pass

            finally:
                try:
                    provider.disconnect()
                except Exception as _disc_err:
                    logger.debug(f"provider.disconnect() failed in post-send bg: {_disc_err}")

        _rh.submit_background(_post_send_all_bg)

        logger.info(
            "[PERF-SEND] phase=validate_total draft_id=%s account_id=%s "
            "success=True archive=%s ms=%s",
            _sanitize_for_log(draft_id),
            _captured_account_id,
            bool(archive_requested),
            int((time.perf_counter() - _validate_total_t0) * 1000),
        )

        return jsonify(response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.info(
            "[PERF-SEND] phase=validate_total draft_id=%s account_id=%s "
            "success=False error=%s ms=%s",
            _sanitize_for_log(draft_id),
            locals().get("_captured_account_id", "unknown"),
            type(e).__name__,
            int((time.perf_counter() - _validate_total_t0) * 1000),
        )
        logger.error(f"Error validating/sending pending draft {_sanitize_for_log(draft_id)}: {e}", exc_info=True)
        return jsonify({"error": f"Erreur d'envoi: {type(e).__name__}"}), 500


@api_bp.route("/pending-drafts/<draft_id>/reject", methods=["POST"])
def reject_pending_draft(draft_id: str):
    """
    Rejette un brouillon en attente.
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    try:
        store = _rh._get_container().get_pending_draft_store()
        pending = store.get_by_id(draft_id)

        if not pending:
            return jsonify({"error": "Pending draft not found"}), 404

        current_account_id = str(_resolve_account_id_cached())
        if not _draft_belongs_to_account(pending, current_account_id):
            return jsonify({"error": "Pending draft not found"}), 404

        from app.domain.entities.pending_draft import PendingDraftStatus
        # SIL-003: guard against race with /validate — reject is only valid on PENDING.
        if pending.status not in (PendingDraftStatus.PENDING, PendingDraftStatus.MODIFIED):
            return jsonify({
                "error": "Ce brouillon n'est plus en attente",
                "status": pending.status.value,
            }), 409
        if not store.update_status(draft_id, PendingDraftStatus.REJECTED):
            return jsonify({
                "error": "Ce brouillon n'est plus en attente",
                "status": "conflict",
            }), 409

        # If this was a snoozed follow-up draft, also dismiss its
        # ``draft_followup`` reminder so the wake sweep doesn't keep
        # processing the rejected row.
        try:
            from app.services.reminder_service import (
                dismiss_reminder,
                get_draft_followup_entry,
            )
            _aid_int = int(current_account_id) if str(current_account_id).isdigit() else None
            _entry = get_draft_followup_entry(draft_id, account_id=_aid_int)
            if _entry and _entry.get("id"):
                dismiss_reminder(_entry["id"], account_id=_aid_int)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"draft_followup reminder cleanup on reject failed: {exc}")

        # Drop the pin (if the follow-up had woken and been pinned) so a
        # rejected follow-up leaves the "Pinned" section of both inbox and
        # Drafts. Pin id == thread_id == pending.email_id. Gated on the tier,
        # not the reminder, because a woken draft's reminder is notified, not
        # active. Idempotent: a no-op when the draft was never pinned.
        if getattr(pending, "routing_tier", "") == "followup" and pending.email_id:
            try:
                from app.services.pinned_emails import remove_pinned_email_id
                _aid_pin = int(current_account_id) if str(current_account_id).isdigit() else None
                if _aid_pin:
                    remove_pinned_email_id(_aid_pin, pending.email_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"unpin on reject failed: {exc}")

        # Learning: enregistrer le rejet comme signal négatif
        try:
            from app.draft_learning import get_draft_learning_store
            learning_store = get_draft_learning_store(account_id=int(current_account_id))
            learning_store.record_rejection(
                email_id=pending.email_id,
                draft_body=pending.draft_body or pending.draft_v1 or "",
                contact=pending.email_sender or "",
            )
        except Exception as exc:
            logger.warning(f"Failed to record rejection learning: {exc}")

        # PR4 follow-up — the `record_draft_rejection()` counter was incremented
        # here on every rejection but never read anywhere downstream (pure
        # write-only state). Learning still happens via `draft_learning` above,
        # which is the consumed pipeline.

        return jsonify({
            "success": True,
            "draft_id": draft_id,
        })

    except Exception as e:
        logger.error(f"Error rejecting pending draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/<draft_id>/suggestion-clicked", methods=["POST"])
def record_suggestion_click(draft_id: str):
    """
    Enregistre qu'une Smart Suggestion a été cliquée par l'utilisateur.
    Body JSON: { suggestion_text: str, suggestion_index: int }
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    suggestion_text = (data.get("suggestion_text") or "").strip()
    suggestion_index = data.get("suggestion_index", 0)

    try:
        from app.draft_quality_tracker import get_tracker
        get_tracker().record_feature("suggestion_click")
    except Exception:
        pass

    try:
        # Resolve account_id first — needed both for the per-account learning
        # store and for the ownership check on the pending draft below.
        _cur = str(_resolve_account_id_cached())
        try:
            _store_acct = int(_cur) if _cur and int(_cur) > 0 else None
        except (TypeError, ValueError):
            _store_acct = None

        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=_store_acct)

        # Récupérer le pending draft pour le contexte (account check soft — lecture seule).
        # Strict ownership: drop the draft on either mismatch OR missing account_id
        # (audit 2026-04-25 CRIT-Iso-4 hardening — zero tolerance for unscoped drafts).
        pd_store = _rh._get_container().get_pending_draft_store()
        pending = pd_store.get_by_id(draft_id)
        if pending and not _draft_belongs_to_account(pending, _cur):
            pending = None  # Ignore cross-account draft silently
        contact = pending.email_sender if pending else ""

        store.record_suggestion_click(
            email_id=pending.email_id if pending else draft_id,
            suggestion_text=suggestion_text,
            suggestion_index=suggestion_index,
            contact=contact,
        )
    except Exception as exc:
        logger.debug("Suggestion click recording skipped: %s", exc)

    return jsonify({"success": True})


@api_bp.route("/pending-drafts/<draft_id>", methods=["PATCH"])
def update_pending_draft(draft_id: str):
    """
    Met à jour le contenu d'un brouillon en attente.
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    subject = data.get("subject")
    body = data.get("body")

    if subject is not None and not isinstance(subject, str):
        return jsonify({"error": "subject must be a string"}), 400

    if body is not None and not isinstance(body, str):
        return jsonify({"error": "body must be a string"}), 400

    try:
        store = _rh._get_container().get_pending_draft_store()
        pending = store.get_by_id(draft_id)

        if not pending:
            return jsonify({"error": "Pending draft not found"}), 404

        current_account_id = str(_resolve_account_id_cached())
        if not _draft_belongs_to_account(pending, current_account_id):
            return jsonify({"error": "Pending draft not found"}), 404

        # Mettre à jour le contenu
        new_subject = subject if subject is not None else pending.draft_subject
        new_body = body if body is not None else pending.draft_body
        store.update_content(draft_id, new_subject, new_body)

        return jsonify({
            "success": True,
            "draft_id": draft_id,
        })

    except Exception as e:
        logger.error(f"Error updating pending draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/<draft_id>/upgrade", methods=["POST"])
def upgrade_quick_reply(draft_id: str):
    """Legacy endpoint — Quick Reply tier has been removed. Returns 410 Gone."""
    return jsonify({"error": "Quick Reply tier has been removed. Use smart suggestions instead."}), 410


@api_bp.route("/pending-drafts/<draft_id>", methods=["DELETE"])
def delete_pending_draft(draft_id: str):
    """
    Supprime définitivement un brouillon en attente.
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    try:
        from app.domain.entities.pending_draft import PendingDraftStatus
        store = _rh._get_container().get_pending_draft_store()

        # Account ownership check before delete
        _draft_check = store.get_by_id(draft_id)
        if _draft_check:
            current_account_id = str(_resolve_account_id_cached())
            if not _draft_belongs_to_account(_draft_check, current_account_id):
                return jsonify({"error": "Pending draft not found"}), 404

        # Mark as REJECTED instead of deleting — prevents daemon from regenerating
        rejected = store.update_status(draft_id, PendingDraftStatus.REJECTED)
        if not rejected:
            # Draft not found — already gone, treat as success
            pass

        # Invalidate pending draft IDs cache so badge disappears immediately.
        # Scope the invalidation to the caller's account so we don't drop
        # other users' cached entries (cf. 2026-04-25 isolation audit C-2).
        from app.api.routes_emails import _invalidate_pending_draft_cache
        try:
            _aid = int(_resolve_account_id_cached())
        except Exception:
            _aid = None
        _invalidate_pending_draft_cache(account_id=_aid)

        return jsonify({"success": True, "draft_id": draft_id})

    except Exception as e:
        logger.error(f"Error deleting pending draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/purge-all", methods=["POST"])
def purge_all_pending_drafts():
    """
    Supprime tous les brouillons en attente (marque comme REJECTED).

    Supports `?count_only=true` to return `{count, will_be_async: false}`
    without mutating — drives the count in the confirmation dialog. Drafts
    cleanup is local-only (no provider call), so `will_be_async` is always
    false: it's sync regardless of count.
    """
    try:
        from app.domain.entities.pending_draft import PendingDraftStatus
        store = _rh._get_container().get_pending_draft_store()
        current_account_id = str(_resolve_account_id_cached())

        # count_only short-circuit — peek at the count without mutating.
        if request.args.get('count_only', '').lower() in ('true', '1', 'yes'):
            cnt = 0
            try:
                # Loop in batches of 500 to handle large pending pools.
                offset = 0
                while True:
                    batch = store.get_pending(limit=500, account_id=current_account_id)
                    if not batch:
                        break
                    cnt += len(batch)
                    # get_pending without offset semantics returns the
                    # same batch each time once we'd "consume" via update.
                    # In count mode we just peek once — break after first
                    # call. (Reading get_pending shows it has no offset
                    # param, so a single 500-batch read is the cheapest
                    # count proxy; for >500 we cap at 500+ for UX.)
                    if len(batch) < 500:
                        break
                    offset += len(batch)
                    # Safety: avoid infinite loop if store yields same batch.
                    if offset >= 5000:
                        break
            except Exception as e:
                logger.debug(f"[purge-all count_only] suppressed: {e}")
            return jsonify({"count": int(cnt), "will_be_async": False}), 200
        # Use get_pending (not get_all) to only target PENDING drafts.
        # Loop until all are purged (handles >500 pending drafts).
        #
        # Stability (audit 2026-05-19 STAB-01): get_pending() has no offset and
        # re-reads disk each call, so a draft that fails to leave the PENDING set
        # (update_status no-ops) OR a concurrent writer re-injecting rows could
        # make `batch` never empty → the request worker spins forever (livelock,
        # not catchable by the surrounding try/except). Track ids we've already
        # attempted so each pass only processes *fresh* drafts (guarantees
        # forward progress), and hard-cap total passes as a backstop against a
        # pathological concurrent producer.
        deleted = 0
        seen: set[str] = set()
        MAX_PURGE_PASSES = 200  # 200 * 500 = 100k drafts, far beyond any real pool
        for _ in range(MAX_PURGE_PASSES):
            batch = store.get_pending(limit=500, account_id=current_account_id)
            fresh = [d for d in batch if d.id not in seen]
            if not fresh:
                break
            for draft in fresh:
                seen.add(draft.id)
                try:
                    if store.update_status(draft.id, PendingDraftStatus.REJECTED):
                        deleted += 1
                except Exception:
                    continue

        # Invalidate cache for the caller's account only (purge-all only
        # touches that account's drafts via get_pending(account_id=...)).
        from app.api.routes_emails import _invalidate_pending_draft_cache
        try:
            _aid = int(current_account_id)
        except Exception:
            _aid = None
        _invalidate_pending_draft_cache(account_id=_aid)

        return jsonify({"success": True, "deleted_count": deleted})
    except Exception as e:
        logger.error(f"Error purging all pending drafts: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/pending-drafts/<draft_id>/explain", methods=["POST"])
def explain_pending_draft(draft_id: str):
    """
    Génère un résumé narratif LLM du pipeline de rédaction.
    Résultat mis en cache dans pipeline_summary.
    """
    try:
        store = _rh._get_container().get_pending_draft_store()
        draft = store.get_by_id(draft_id)
        if not draft:
            return jsonify({"error": "Draft not found"}), 404

        # Ownership check — prevent cross-account explain
        account_id = _resolve_account_id_cached()
        if not _draft_belongs_to_account(draft, str(account_id)):
            return jsonify({"error": "Draft not found"}), 404

        # Return cached summary if available
        if draft.pipeline_summary:
            return jsonify({"success": True, "summary": draft.pipeline_summary})

        # Build context for LLM
        import os
        _template_path = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates", "pipeline_summary_prompt.txt"
        )
        with open(_template_path, encoding="utf-8") as f:
            template = f.read()

        # Memory summary
        mem = draft.memory_trace or {}
        mem_parts = []
        if mem.get("profil"):
            mem_parts.append(f"Profil : {', '.join(f'{k}={v}' for k, v in mem['profil'].items() if v)}")
        if mem.get("style_default"):
            sd = mem["style_default"]
            mem_parts.append(f"Style : formalité={sd.get('formality_level', '?')}")
        if mem.get("savoir"):
            mem_parts.append(f"{len(mem['savoir'])} connaissances consultées")
        if mem.get("rules"):
            mem_parts.append(f"{len(mem['rules'])} règles apprises")
        memory_summary = "\n".join(f"- {p}" for p in mem_parts) if mem_parts else "Aucune mémoire utilisée"

        # Critique summary
        critique_summary = draft.critique[:300] if draft.critique else "Aucune critique (pipeline simplifié)"

        # Corrections summary
        corr = draft.correction_details or []
        if corr:
            # Map correction keys to human labels
            _LABELS = {
                "html_cleanup": "Nettoyage HTML",
                "prompt_leakage": "Fuite de prompt supprimée",
                "markdown_cleanup": "Artefacts Markdown retirés",
                "clarification_removed": "Draft de clarification supprimé",
                "filler_removed": "Phrases de remplissage supprimées",
                "signature_cleaned": "Signature nettoyée",
                "truncated_short": "Réponse raccourcie",
                "subject_echo": "Écho du sujet retiré",
                "technical_echo": "Écho technique retiré",
                "parroting": "Reformulation du contenu original retirée",
                "hallucinated_facts": "Faits inventés supprimés",
                "invented_contacts": "Contacts inventés supprimés",
                "ungrounded_nouns": "Termes non fondés retirés",
                "novel_situation": "Situation inventée retirée",
                "hallucinated_context": "Contexte halluciné retiré",
                "process_language": "Langage procédural supprimé",
                "hedging": "Hésitations retirées",
                "placeholder_removed": "Placeholders retirés",
                "sycophancy": "Flatterie supprimée",
                "unnecessary_questions": "Questions inutiles retirées",
                "excessive_apologies": "Excuses excessives retirées",
                "redundant_affirmations": "Affirmations redondantes retirées",
                "contrast_simplified": "Tournures contrastives simplifiées",
                "slop_words": "Mots vagues retirés",
                "recap_removed": "Résumés superflus retirés",
                "repetitive_openings": "Ouvertures répétitives corrigées",
                "duplicate_greetings": "Salutations dupliquées retirées",
                "learned_corrections": "Corrections apprises appliquées",
            }
            corrections_summary = "\n".join(f"- {_LABELS.get(c, c)}" for c in corr)
        else:
            corrections_summary = "Aucune correction nécessaire"

        prompt = template.format(
            sender=draft.email_sender_name or draft.email_sender,
            subject=draft.email_subject,
            body_excerpt=(draft.email_body or "")[:300],
            classification=draft.classification,
            routing_tier=draft.routing_tier or "standard",
            classification_reason=draft.classification_reason or "Non spécifiée",
            memory_summary=memory_summary,
            critique_summary=critique_summary,
            corrections_summary=corrections_summary,
        )

        # Call LLM (Haiku for cost efficiency)
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        from app.config import CLAUDE_MODEL_LABEL
        llm = ClaudeAdapter(model=CLAUDE_MODEL_LABEL)
        response = llm.complete(
            system="Tu es un assistant qui rédige des résumés concis et factuels.",
            user=prompt,
            max_tokens=400,
            temperature=0.3,
        )
        summary = response.content.strip()

        # Cache the result in the draft object (persists in-memory + disk)
        draft.pipeline_summary = summary
        store._save_to_disk()

        return jsonify({"success": True, "summary": summary})
    except Exception as e:
        logger.error(f"Error explaining draft {draft_id}: {e}")
        return jsonify({"error": "Failed to generate summary"}), 500
