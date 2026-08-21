# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les brouillons (drafts) — Agentys.

Endpoints:
- GET  /api/drafts                      - Liste des brouillons générés
- GET  /api/drafts/<id>                 - Détail d'un brouillon
- PATCH /api/drafts/<id>/feedback       - Feedback sur un brouillon
- PATCH /api/drafts/<id>/edit           - Éditer le contenu d'un brouillon
- POST /api/drafts/<id>/refine          - Affiner un brouillon via instruction IA
- POST /api/refine-text                 - Affiner du texte libre via instruction IA
- POST /api/drafts/<id>/regenerate      - Regénérer un brouillon complètement
"""

import logging
import re
import unicodedata
from typing import Optional

from flask import request, jsonify
from werkzeug.exceptions import HTTPException

from app.api.utils.errors import error_response
from app.utils.draft_cleanup import strip_terminal_parenthetical_note
from app.api.routes_helpers import (
    api_bp,
    _validate_limit,
    _validate_optional_string,
    _validate_email_id,
    _sanitize_for_log,
    _rate_limited,
    require_json,
    _get_authenticated_provider,
    LegacyModuleLoader,
)
import app.api.routes_helpers as _rh

logger = logging.getLogger(__name__)


class _NoLockCM:
    """No-op context manager for the case where a per-draft lock is not
    available (e.g. refine on a draft_history record without a
    PendingDraft). Audit concurrency C4 fix (2026-04-24)."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# ============================================================================
# DRAFTS
# ============================================================================

# Security: Input validation constants for list_drafts
LIST_DRAFTS_MIN_LIMIT = 1
LIST_DRAFTS_MAX_LIMIT = 500
LIST_DRAFTS_DEFAULT_LIMIT = 50
LIST_DRAFTS_MAX_OFFSET = 100000
MAX_CATEGORY_LENGTH = 100


@api_bp.route("/drafts", methods=["GET"])
def list_drafts():
    """
    Liste les brouillons générés.
    ---
    tags:
      - Drafts
    summary: Liste les brouillons générés
    parameters:
      - name: limit
        in: query
        description: Nombre maximum de brouillons à retourner
        schema:
          type: integer
          minimum: 1
          maximum: 500
          default: 50
      - name: offset
        in: query
        description: Offset pour pagination
        schema:
          type: integer
          minimum: 0
          default: 0
      - name: category
        in: query
        description: Filtrer par catégorie
        schema:
          type: string
    responses:
      200:
        description: Liste paginée des brouillons
        content:
          application/json:
            schema:
              type: object
              properties:
                total:
                  type: integer
                  description: Nombre total de brouillons
                limit:
                  type: integer
                offset:
                  type: integer
                drafts:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                      email_id:
                        type: string
                      subject:
                        type: string
                      category:
                        type: string
                      created_at:
                        type: string
                        format: date-time
      400:
        description: Paramètre invalide
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
    """
    # Security: Validate limit parameter
    limit, error = _validate_limit(
        LIST_DRAFTS_MIN_LIMIT,
        LIST_DRAFTS_MAX_LIMIT,
        LIST_DRAFTS_DEFAULT_LIMIT
    )
    if error:
        return error

    # Security: Validate offset parameter
    offset = request.args.get("offset", 0, type=int)
    if offset < 0 or offset > LIST_DRAFTS_MAX_OFFSET:
        return jsonify({
            "error": f"Offset must be between 0 and {LIST_DRAFTS_MAX_OFFSET}"
        }), 400

    category = request.args.get("category")

    # Security: Validate category parameter to prevent DoS/injection
    _, error = _validate_optional_string(category, "category", MAX_CATEGORY_LENGTH)
    if error:
        return error

    # Phase 0 — Feature flag de mitigation : si
    # AGENTYS_DRAFT_HISTORY_ENABLED=false, on court-circuite entièrement la
    # lecture de l'historique des brouillons (renvoie liste vide). Utilisé en
    # cas de fuite avérée le temps de la migration.
    import os as _os
    if _os.environ.get("AGENTYS_DRAFT_HISTORY_ENABLED", "true").lower() in (
        "0", "false", "no", "off"
    ):
        return jsonify({"total": 0, "limit": limit, "offset": offset, "drafts": []})

    try:
        # Isolation multi-compte: résoudre l'int account_id depuis le JWT
        # (ou singleton Tauri en loopback). -1 = utilisateur sans compte.
        account_id = _rh._resolve_account_id_for_user()
        if account_id <= 0:
            return jsonify({"total": 0, "limit": limit, "offset": offset, "drafts": []})

        # Clean Architecture: utiliser le port via Container DI — méthode scoped.
        draft_history = _rh._get_container().get_draft_history()
        all_drafts = draft_history.get_all_for_account(account_id)

        # Filtrer par categorie si specifie
        if category:
            all_drafts = [d for d in all_drafts if d.category == category]

        # Pagination
        total = len(all_drafts)
        drafts = all_drafts[offset:offset + limit]

        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "drafts": [_draft_to_summary_dict(d) for d in drafts],
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing drafts: {e}")
        return jsonify({"error": "An internal error occurred while listing drafts"}), 500


def _draft_to_summary_dict(draft) -> dict:
    """Convertit un draft en dictionnaire résumé."""
    return {
        "id": draft.id,
        "timestamp": draft.timestamp,
        "email_sender": draft.email_sender,
        "email_subject": draft.email_subject,
        "email_body": draft.email_body,
        "status": draft.status,
        "category": draft.category,
        "priority_score": draft.priority_score,
        "tokens_used": draft.tokens_used,
        "processing_time_ms": draft.processing_time_ms,
        "feedback": draft.feedback,
        "feedback_comment": draft.feedback_comment,
        # Include content for frontend display
        "draft_v1": draft.draft_v1,
        "draft_final": draft.draft_final,
        "critique": draft.critique,
        "draft_id": draft.draft_id,
    }


@api_bp.route("/drafts/<draft_id>", methods=["GET"])
def get_draft(draft_id: str):
    """
    Recupere un brouillon par son ID.

    Utilise DraftHistoryPort via le Container DI.

    Args:
        draft_id: ID du brouillon.

    Returns:
        Details complets du brouillon.
    """
    # Security: Validate draft_id format to prevent injection attacks
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    # Isolation multi-compte
    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    # Clean Architecture: utiliser le port via Container DI — méthode scoped.
    draft = _rh._get_container().get_draft_history().get_by_id_for_account(draft_id, account_id)

    if not draft:
        return jsonify({"error": "Draft not found"}), 404

    return jsonify(_draft_to_full_dict(draft))


def _draft_to_full_dict(draft) -> dict:
    """Convertit un draft en dictionnaire complet."""
    return {
        "id": draft.id,
        "timestamp": draft.timestamp,
        "email_id": draft.email_id,
        "email_sender": draft.email_sender,
        "email_subject": draft.email_subject,
        "email_body": draft.email_body,
        "draft_v1": draft.draft_v1,
        "critique": draft.critique,
        "draft_final": draft.draft_final,
        "status": draft.status,
        "draft_id": draft.draft_id,
        "tokens_used": draft.tokens_used,
        "model": draft.model,
        "processing_time_ms": draft.processing_time_ms,
        "priority_score": draft.priority_score,
        "category": draft.category,
        "feedback": draft.feedback,
        "feedback_comment": draft.feedback_comment,
    }


VALID_FEEDBACK_VALUES = frozenset(("positive", "negative", "neutral"))
# Security: Max length for feedback comment to prevent abuse
MAX_FEEDBACK_COMMENT_LENGTH = 1000


@api_bp.route("/drafts/<draft_id>/feedback", methods=["PATCH"])
def update_draft_feedback(draft_id: str):
    """
    Met à jour le feedback d'un brouillon.

    Args:
        draft_id: ID du brouillon.

    Body JSON:
        feedback: "positive" | "negative" | "neutral"
        comment: Commentaire optionnel (max 1000 chars)

    Returns:
        Brouillon mis à jour.
    """
    # Security: Validate draft_id format to prevent injection attacks
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    feedback = data.get("feedback")
    comment = data.get("comment", "")

    if feedback not in VALID_FEEDBACK_VALUES:
        return jsonify({"error": "feedback must be 'positive', 'negative', or 'neutral'"}), 400

    # Security: Validate comment length to prevent abuse
    if comment and len(comment) > MAX_FEEDBACK_COMMENT_LENGTH:
        return jsonify({
            "error": f"Comment exceeds maximum length of {MAX_FEEDBACK_COMMENT_LENGTH} characters"
        }), 400

    # Isolation multi-compte
    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    # Clean Architecture: utiliser le port via Container DI — méthode scoped.
    success = _rh._get_container().get_draft_history().update_feedback_for_account(
        draft_id, account_id, feedback, comment
    )

    if not success:
        return jsonify({"error": "Draft not found"}), 404

    return jsonify({
        "success": True,
        "draft_id": draft_id,
        "feedback": feedback,
        "comment": comment,
    })


# ----------------------------------------------------------------------------
# Structured feedback verdict endpoint (audit 2026-05-05).
# ----------------------------------------------------------------------------
# The PATCH /feedback above stores a thumbs-up/down sentiment on the draft
# history record. This POST is an APPEND-ONLY audit log of explicit user
# verdicts that the Critic threshold tuner consumes:
#
#   action ∈ {accept, edit, reject}
#   edit_distance ∈ [0,1]  — only meaningful for 'edit'
#   intent : optional intent label (decline / scheduling / ...) for analytics
#   note   : optional free-text rejection reason (≤ 1024 chars)
#
# The two endpoints serve different consumers and intentionally don't share
# state — the audit log is immutable, the legacy thumbs is mutable on the
# draft record. Co-existing on (PATCH, POST) at the same path is by design.
# ----------------------------------------------------------------------------
_VALID_FEEDBACK_ACTIONS = {"accept", "edit", "reject"}
_MAX_FEEDBACK_NOTE_LENGTH = 1024


@api_bp.route("/drafts/<draft_id>/feedback", methods=["POST"])
def post_draft_feedback_event(draft_id: str):
    """Append an explicit user verdict on a draft to the audit log.

    Body JSON:
        action        : "accept" | "edit" | "reject"           (required)
        edit_distance : float in [0, 1]                         (optional, edit only)
        intent        : str ≤ 32                                (optional)
        note          : str ≤ 1024                              (optional)

    Distinct from the PATCH endpoint above, which sets the legacy thumbs
    field on the draft record. Both can fire for the same draft.
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    action = (data.get("action") or "").strip().lower()
    if action not in _VALID_FEEDBACK_ACTIONS:
        return jsonify({
            "error": "action must be 'accept', 'edit', or 'reject'",
            "got": action,
        }), 400

    edit_distance = data.get("edit_distance")
    if edit_distance is not None:
        try:
            edit_distance = float(edit_distance)
        except (TypeError, ValueError):
            return jsonify({"error": "edit_distance must be a number in [0, 1]"}), 400
        if not 0.0 <= edit_distance <= 1.0:
            return jsonify({"error": "edit_distance must be in [0, 1]"}), 400

    intent_raw = data.get("intent")
    intent = str(intent_raw).strip()[:32] if intent_raw else None

    note_raw = data.get("note")
    note = str(note_raw)[:_MAX_FEEDBACK_NOTE_LENGTH] if note_raw else None

    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Account not resolvable"}), 401

    # Persist via repository inside a managed session.
    try:
        from app.db.database import get_db_session
        from app.db.repositories.draft_feedback_repository import DraftFeedbackRepository
        from app.domain.entities.draft_feedback import DraftFeedback, FeedbackAction

        feedback_entity = DraftFeedback(
            account_id=account_id,
            draft_id=draft_id,
            action=FeedbackAction(action),
            edit_distance=edit_distance,
            intent=intent,
            note=note,
        )
        with get_db_session() as session:
            repo = DraftFeedbackRepository(session)
            new_id = repo.add(feedback_entity)
        # Telemetry line — Sentinel L3 reads the rolling rejection_rate from
        # this log. Do NOT change the prefix / fields without updating the
        # sentinel that consumes it.
        logger.info(
            "[DRAFT_FEEDBACK] account=%d draft=%s action=%s "
            "edit_distance=%s intent=%s",
            account_id, _sanitize_for_log(draft_id), action,
            edit_distance if edit_distance is not None else "n/a",
            intent or "-",
        )
        return jsonify({
            "success": True,
            "id": new_id,
            "draft_id": draft_id,
            "action": action,
        }), 201
    except Exception:
        logger.exception("[DRAFT_FEEDBACK] persist failed for draft=%s", draft_id)
        return jsonify({"error": "Failed to record feedback"}), 500


# Security: Max length for draft content to prevent abuse
MAX_DRAFT_BODY_LENGTH = 50000
MAX_DRAFT_SUBJECT_LENGTH = 500


@api_bp.route("/drafts/<draft_id>/edit", methods=["PATCH"])
def edit_draft_content(draft_id: str):
    """
    Édite le contenu d'un brouillon.

    Args:
        draft_id: ID du brouillon (format Agentys).

    Body JSON:
        subject: Nouveau sujet (optionnel)
        body: Nouveau corps du message (optionnel)

    Returns:
        Résultat de la mise à jour.
    """
    # Security: Validate draft_id format to prevent injection attacks
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    subject = data.get("subject")
    body = data.get("body")

    if subject is None and body is None:
        return jsonify({"error": "At least one of 'subject' or 'body' is required"}), 400

    # Security: Validate content length
    if subject and len(subject) > MAX_DRAFT_SUBJECT_LENGTH:
        return jsonify({
            "error": f"Subject exceeds maximum length of {MAX_DRAFT_SUBJECT_LENGTH} characters"
        }), 400

    if body and len(body) > MAX_DRAFT_BODY_LENGTH:
        return jsonify({
            "error": f"Body exceeds maximum length of {MAX_DRAFT_BODY_LENGTH} characters"
        }), 400

    # Isolation multi-compte
    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    # Get the draft record to find the provider draft ID (scoped)
    container = _rh._get_container()
    draft_record = container.get_draft_history().get_by_id_for_account(draft_id, account_id)

    if not draft_record:
        return jsonify({"error": "Draft not found"}), 404

    provider_draft_id = draft_record.draft_id
    if not provider_draft_id:
        return jsonify({"error": "No provider draft ID associated with this draft"}), 400

    # Update the draft in provider (Gmail/Outlook/IMAP)
    try:
        provider = _get_authenticated_provider()
        success = provider.update_draft(
            draft_id=provider_draft_id,
            subject=subject,
            body=body,
        )

        if not success:
            return jsonify({"error": "Failed to update draft"}), 500

        # Also update the draft in local history if body changed.
        # account_id est préservé depuis la lecture scoped ci-dessus.
        if body:
            draft_record.draft_final = body
            container.get_draft_history().add(draft_record)

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "provider_draft_id": provider_draft_id,
        })

    except Exception as e:
        logger.error(f"Error updating draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# Security: Max length for refine instruction
MAX_REFINE_INSTRUCTION_LENGTH = 1000

# Patterns for chain-of-thought reasoning leaked into refine output
_REASONING_RE = re.compile(
    r"^(?:"
    r"(?:Je dois|I need to|I must|Let me|I'?ll|I will|Here'?s|Here is)\b.*|"
    r"\*{0,2}(?:Résolution|Resolution|Note|Clarification|Contradiction|Analyse|Analysis|"
    r"Plan|Context|Transformation|Verification|Intended Output|Note content|Language|Tone|"
    r"First name|Nature)\*{0,2}\s*[:—–-].*|"
    r"(?:Ces deux directives|L'instruction originale|La critique stipule).*|"
    r"(?:Selon les règles|According to the rules).*"
    r")$",
    re.IGNORECASE | re.MULTILINE,
)

_MARKDOWN_HEADER_RE = re.compile(r"^\s*#{1,6}\s+.*$", re.MULTILINE)
_FENCE_LINE_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)

# Standalone structural placeholders Haiku occasionally emits as the last
# line of a draft when it gets confused about whether it's writing the body
# or a schema. Observed in prod 2026-05-18: `Reply body,` shipped between the
# real prose and the signature. Match only as a whole line so we never strip
# legitimate prose like "I'll reply with the body of the contract."
#
# Audit 2026-05-19 round-2: the `\s` class on its own caught ASCII whitespace
# only — Haiku's actual prod output occasionally pads the placeholder with
# Unicode whitespace (NBSP U+00A0, zero-width U+200B, soft hyphen U+00AD)
# that bypassed the strip. The `_WS` class below covers those variants. Also
# added `re.UNICODE` so `\s` itself picks up Unicode line terminators.
_WS = r"[\s ​‌‍­﻿]"
_PLACEHOLDER_STRUCTURAL_RE = re.compile(
    rf"^{_WS}*\[?{_WS}*(?:"
    r"(?:Reply|Email|Message)\s+body"
    r"|Body\s+of\s+(?:the\s+)?(?:reply|email|message)"
    r"|Corps\s+(?:de\s+(?:la\s+|l['’]\s*))?(?:réponse|reponse|email|message)"
    r"|Corps\s+du\s+(?:message|courriel|courrier)"
    rf"){_WS}*\]?{_WS}*[,.;:]*{_WS}*$",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Audit 2026-05-20 — bare leaked schema *value*. User report: a lone
# "unknown." line shipped where the closing belongs (FR casual draft after
# Ctrl+G). Distinct from `_PLACEHOLDER_STRUCTURAL_RE` (leaked *labels* like
# "Reply body") and `_REASONING_RE` ("Label: value" lines): here Haiku
# emits ONLY the unfilled schema sentinel, with no label, when the
# over-constrained Ctrl+G prompt tips it into "fill a schema" mode. Nothing
# downstream catches it — the route tail-trim only fires on lines carrying
# body/corps/message/reply/email/content/draft, and `_enforce_closing`
# leaves a non-closing tail line intact (neither replaced nor stripped).
# Scope: the closed set of schema-null sentinels an LLM emits for an
# undetermined field; none is ever a legitimate standalone line in a real
# email body. Whole-line + anchored so prose that merely *contains* the
# word ("Unknown error occurred.") is untouched.
_LEAKED_SCHEMA_VALUE_RE = re.compile(
    rf"^{_WS}*\[?{_WS}*(?:unknown|undefined|unspecified){_WS}*\]?{_WS}*[,.;:]*{_WS}*$",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


def _strip_refine_reasoning(text: str) -> str:
    """Remove chain-of-thought reasoning and plan leakage from LLM refine output.

    Handles two common failure modes:
      1. Inline meta-commentary ("Je dois…", "Résolution:…", "I'll create a plan…")
      2. Full structured plans with markdown headers (# Plan, ## Context, ## Transformation)
         where the actual output is wrapped in --- fences at the end.
    """
    if not text:
        return text

    cleaned = text.strip()

    # Strategy 1: if the model emitted a structured plan, the real output is
    # often wrapped between the LAST pair of "---" fence lines. Extract it.
    fence_matches = list(_FENCE_LINE_RE.finditer(cleaned))
    if len(fence_matches) >= 2:
        start = fence_matches[-2].end()
        end = fence_matches[-1].start()
        candidate = cleaned[start:end].strip()
        # Only trust the extracted block when it's substantially shorter than the
        # full response (otherwise --- may be part of the user's original text).
        if candidate and len(candidate) < len(cleaned) * 0.6:
            cleaned = candidate

    # Strategy 2: if a "Transformation" / "Output" / "Résultat" section is
    # present, extract what follows (up to the next header or end of text).
    elif re.search(r"#{1,4}\s*(?:Transformation|Output|Résultat|Final|Result)", cleaned, re.IGNORECASE):
        section_match = re.search(
            r"#{1,4}\s*(?:Transformation|Output|Résultat|Final|Result)[^\n]*\n+"
            r"(?:```\w*\s*\n)?"
            r"(.+?)"
            r"(?:\n\s*```|\n\s*#{1,4}\s|\Z)",
            cleaned,
            re.DOTALL | re.IGNORECASE,
        )
        if section_match:
            candidate = section_match.group(1).strip()
            candidate = _FENCE_LINE_RE.sub("", candidate).strip()
            if candidate:
                cleaned = candidate

    # Strategy 3: strip leftover markdown headers anywhere in the text
    cleaned = _MARKDOWN_HEADER_RE.sub("", cleaned)

    # Strategy 4: strip line-based reasoning/plan patterns (existing behavior, extended)
    cleaned = _REASONING_RE.sub("", cleaned)

    # Strategy 5: strip residual --- fence lines
    cleaned = _FENCE_LINE_RE.sub("", cleaned)

    # Strategy 6: strip structural placeholder lines ("Reply body,", etc.)
    cleaned = _PLACEHOLDER_STRUCTURAL_RE.sub("", cleaned)

    # Collapse multiple blank lines left by removal
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned if cleaned else text.strip()


@api_bp.route("/drafts/<draft_id>/refine", methods=["POST"])
def refine_draft_content(draft_id: str):
    """
    Affine le contenu d'un brouillon via une instruction en langage naturel.

    Utilise le LLM pour modifier le brouillon selon l'instruction de l'utilisateur
    (ex: "raccourcir", "être plus formel", "corriger l'orthographe").

    Args:
        draft_id: ID du brouillon (format Agentys).

    Body JSON:
        instruction: L'instruction pour affiner le brouillon (requis, max 1000 chars)

    Returns:
        Résultat avec le nouveau contenu affiné.
    """
    # Security: Validate draft_id format to prevent injection attacks
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    instruction = data.get("instruction")

    if not instruction or not isinstance(instruction, str):
        return jsonify({"error": "instruction is required and must be a string"}), 400

    instruction = instruction.strip()
    if not instruction:
        return jsonify({"error": "instruction cannot be empty"}), 400

    if len(instruction) > MAX_REFINE_INSTRUCTION_LENGTH:
        return jsonify({
            "error": f"instruction exceeds maximum length of {MAX_REFINE_INSTRUCTION_LENGTH} characters"
        }), 400

    # Isolation multi-compte
    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    # Get the draft record — try PendingDraftStore first, then DraftHistory
    container = _rh._get_container()
    pending_draft = container.get_pending_draft_store().get_by_id(draft_id)
    draft_record = None

    if pending_draft:
        # Ownership check — prevent cross-account refine.
        # Audit 2026-04-25 CRIT-Iso-4: reject draft if account_id is None/empty
        # (legacy / pre-resolution drafts) instead of falling through.
        _pd_aid = getattr(pending_draft, "account_id", None)
        if _pd_aid is None or str(_pd_aid).strip() == "" or str(_pd_aid) != str(account_id):
            return jsonify({"error": "Draft not found"}), 404
        # Found in pending drafts — use its data
        gmail_draft_id = getattr(pending_draft, 'gmail_draft_id', None)
        current_body = pending_draft.draft_body
    else:
        # Fallback to draft history (scoped)
        draft_record = container.get_draft_history().get_by_id_for_account(draft_id, account_id)
        if not draft_record:
            return jsonify({"error": "Draft not found"}), 404
        gmail_draft_id = draft_record.draft_id
        current_body = draft_record.draft_final

    # Audit concurrency C4 (2026-04-24): serialize /refine vs /validate-and-send
    # for the same draft. Without this lock, a fast user can click "Send"
    # while /refine is still running — last writer wins, refined content
    # may be silently dropped from the sent email or the cached refine
    # may overwrite the freshly-sent content.
    _store = container.get_pending_draft_store()
    _draft_lock = _store.get_draft_lock(draft_id) if pending_draft else None

    # Audit P0-4 (mother-of-all 2026-04-25): empêche deux /refine concurrents
    # sur le même draft. Le `_draft_lock` ci-dessus est acquis uniquement
    # autour de l'écriture finale (l'appel LLM tourne hors-lock pour ne pas
    # bloquer /validate). Sans ce try-acquire, spammer Ctrl+G lance N
    # générations LLM en parallèle, dont la dernière écrase silencieusement
    # les autres. On réserve un slot non-bloquant : si déjà pris → 409.
    _refining_acquired = False
    if pending_draft:
        _refining_acquired = _store.try_acquire_refining_lock(draft_id)
        if not _refining_acquired:
            return jsonify({
                "success": False,
                "error": "Refine already in progress for this draft. Wait for the current run to finish.",
            }), 409

    try:
        # Use the full pipeline: Refine → Critique → (V2 if needed)
        refine_use_case = container.get_refine_use_case()

        # Audit 2026-05-04 — refine parity : enrich the use case with the
        # same context the initial-draft path consumes (few-shot, style
        # metrics, learned rules, contact summary). All fields are
        # optional — populate best-effort, refine still works if any
        # individual lookup fails.
        try:
            contact_email_for_refine = (pending_draft.email_sender if pending_draft else "") or ""
            user_email_for_refine = ""
            try:
                from app.db.repositories.account_repository import AccountRepository
                with _rh.get_db_session() as _sess:
                    _acct = AccountRepository(_sess).get(account_id)
                    user_email_for_refine = (getattr(_acct, "email", "") or "") if _acct else ""
            except Exception:
                pass

            conv_history_for_refine: list = []
            if contact_email_for_refine and account_id and account_id > 0:
                try:
                    from app.api.routes_helpers import _fetch_conversation_history_for_contact
                    # provider=None forces SQLite-only path (already
                    # cached by the sync service). Limit 10 — refine
                    # benefits from richer context than initial draft's
                    # default of 2.
                    conv_history_for_refine = _fetch_conversation_history_for_contact(
                        provider=None,
                        sender_email=contact_email_for_refine,
                        limit=10,
                        account_id=account_id,
                    )
                except Exception as _hist_err:
                    logger.debug(f"refine: conv history lookup failed: {_hist_err}")

            refine_use_case.account_id = account_id if account_id and account_id > 0 else None
            refine_use_case.user_email = user_email_for_refine
            refine_use_case.contact_email = contact_email_for_refine
            refine_use_case.conversation_history = conv_history_for_refine or None
        except Exception as _ctx_err:
            logger.debug(f"refine: rich-context wiring failed (degrades to legacy prompt): {_ctx_err}")

        # Build email context from pending draft data (needed for auto-reply)
        source_email = None
        if pending_draft and pending_draft.email_body:
            try:
                from app.domain.entities.email import Email as DomainEmail
                source_email = DomainEmail(
                    id=pending_draft.email_id or "unknown",
                    subject=pending_draft.email_subject or "",
                    body=pending_draft.email_body,
                    sender=pending_draft.email_sender or "unknown@unknown.com",
                )
            except Exception:
                pass  # Proceed without email context if construction fails

        # Execute the pipeline (LLM call — outside the per-draft lock to
        # avoid blocking /validate for the duration of the LLM round-trip).
        result = refine_use_case.execute(
            current_draft=current_body,
            instruction=instruction,
            email=source_email,
        )

        refined_body = _strip_refine_reasoning(result.draft_final.content.strip())

        # Ensure greeting stands alone on its own line
        from app.smart_routing import _separate_greeting_from_body, _enforce_closing
        refined_body = _separate_greeting_from_body(refined_body)

        # Guarantee a closing formula on the refined draft. We use
        # replace_existing=False so that user-authored closings are kept
        # intact — we only add one when the LLM (or user) dropped it.
        try:
            from app.prompts import (
                _compute_closing_hint, analyze_email_formality, _detect_language,
                load_primary_language_for_account,
            )
            _source_text = ""
            if pending_draft and pending_draft.email_body:
                _source_text = f"{pending_draft.email_subject or ''}\n{pending_draft.email_body}"
            _formality = analyze_email_formality(_source_text) if _source_text else 3
            try:
                _account_id = _rh._resolve_account_id_for_user()
            except Exception:
                _account_id = None
            _primary_lang = load_primary_language_for_account(_account_id)
            _language = (
                _detect_language(_source_text, fallback_language=_primary_lang)
                if _source_text else _primary_lang
            )
            _preferred: list[str] | None = None
            try:
                if _account_id and _account_id > 0:
                    _profile = container.get_writing_style_profile(account_id=_account_id)
                    if _profile and _profile.preferred_closings:
                        _preferred = _profile.preferred_closings
            except Exception as _pe:
                logger.debug(f"refine: preferred_closings lookup failed: {_pe}")
            _closing_hint = _compute_closing_hint(_formality, _language, _preferred)
            refined_body = _enforce_closing(
                refined_body, _closing_hint, replace_existing=False,
            )
        except Exception as _ce:
            logger.debug(f"refine: closing enforcement skipped: {_ce}")

        if not refined_body:
            return jsonify({"error": "Failed to generate refined content"}), 500

        # Update the draft in Gmail if there's a Gmail draft ID
        if gmail_draft_id:
            try:
                provider = LegacyModuleLoader.email_provider()
                if provider.authenticate():
                    success = provider.update_draft(
                        draft_id=gmail_draft_id,
                        body=refined_body,
                    )
                    if not success:
                        logger.warning(f"Failed to update Gmail draft {gmail_draft_id}")
            except Exception as gmail_err:
                logger.warning(f"Error updating Gmail draft: {gmail_err}")

        # Update local stores with pipeline results — guarded by the
        # per-draft lock (audit C4 fix). The lock keeps /validate-and-send
        # from racing the write below; if the user already clicked Send,
        # /validate completes its mutation first and our refine sees the
        # updated state on the next read (callers reload via /refresh).
        if pending_draft:
            _draft_cm = _draft_lock if _draft_lock is not None else _NoLockCM()
            with _draft_cm:
                # Re-read to pick up any /validate-side changes that landed
                # while the LLM was running.
                _fresh = _store.get_by_id(draft_id)
                if _fresh is None:
                    # Draft was deleted (rejected/sent) during refine —
                    # don't resurrect it.
                    logger.info(f"refine: draft {draft_id} disappeared during LLM call — skipping write")
                    return jsonify({
                        "success": False,
                        "error": "Draft no longer exists (deleted, sent, or rejected)",
                    }), 410
                pending_draft = _fresh
                pending_draft.draft_v1 = result.draft_v1.content
                pending_draft.critique = result.critique.raw_response
                pending_draft.draft_body = refined_body
                # DP-04 fix: assign enum, not the bare string. `get_unsent` filters
                # by enum tuple — string assignment briefly hides the draft from
                # the list until JSON round-trip coerces it back.
                from app.domain.entities.pending_draft import PendingDraftStatus as _PDStatus
                pending_draft.status = _PDStatus.MODIFIED
                _store.add(pending_draft)
        if draft_record:
            draft_record.draft_v1 = result.draft_v1.content
            draft_record.critique = result.critique.raw_response
            draft_record.draft_final = refined_body
            draft_record.status = result.status.value
            container.get_draft_history().add(draft_record)

        # Track refine AI usage
        try:
            from app.draft_quality_tracker import get_tracker
            get_tracker().record_feature("refine_ai", account_id=str(account_id or ""))
        except Exception:
            pass

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "refined_body": refined_body,
            "pipeline_details": {
                "draft_v1": result.draft_v1.content,
                "critique": {
                    "is_valid": result.critique.is_valid,
                    "feedback": result.critique.reason or result.critique.raw_response,
                },
                "was_corrected": result.was_corrected,
            },
        })

    except Exception as e:
        logger.error(f"Error refining draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
    finally:
        # Audit P0-4 : release du verrou refine, idempotent. Doit tourner même
        # si le 410 (draft disparu) ou un return inattendu sort du try plus tôt.
        if _refining_acquired and pending_draft:
            _store.release_refining_lock(draft_id)


# ── Refine user-written text via AI instruction ──────────────────────────

MAX_REFINE_TEXT_LENGTH = 10000
MAX_REFINE_INSTRUCTION_LENGTH = 1000

# Audit 2026-05-20 — Ctrl+G language anchor (round-4) regression guard.
# `langdetect` is a coin-flip on short / abbreviation-heavy notes: a 5-word
# French note like "rdv demain 14h confirmer agenda" returns "en", which
# then flips the WHOLE draft (greeting, closing, body) to English. We only
# trust a switch AWAY from the user's primary language when the note carries
# enough signal to be reliable; below this word count we keep the primary
# language (the safe default — almost every short note a user writes is in
# their own primary language). Tunable in one place; grounded in langdetect's
# documented unreliability under ~1 full sentence rather than persona-tuned.
_MIN_WORDS_FOR_NONPRIMARY_LANG = 8
# `load_primary_language_for_account` returns the drafter label
# ('FRENCH'/'ENGLISH'); map to the iso code `detected_lang` uses.
_PRIMARY_LANG_TO_ISO = {"FRENCH": "fr", "ENGLISH": "en", "SPANISH": "es"}

# ── Instruction intent classification (used to gate contact-style tone adaptation)
# ─────────────────────────────────────────────────────────────────────────────
# Transformative instructions ask the LLM to create/expand/rewrite an email.
# When these fire AND the recipient has a ContactStyleProfile with a
# formality_override, we force Haiku to match that formality (tutoiement
# casual or vouvoiement formel) instead of preserving the user's input style.
_TRANSFORMATIVE_INSTRUCTION_RE = re.compile(
    r"\b(transforme(r|z)?|d[ée]veloppe(r|z)?|r[ée]dige(r|z)?|[ée]cri(s|re|vez)|"
    r"email\s+complet|mail\s+complet|courriel\s+complet|formule(r|z)?|"
    r"g[ée]n[ée]re(r|z)?|fais[- ]?en\s+un\s+email|fais[- ]?en\s+un\s+mail|"
    r"transforme\s+en\s+(email|mail|courriel)|"
    r"write|compose|draft|expand|flesh\s+out|turn\s+into|make\s+into|rewrite|"
    r"reformule(r|z)?)\b",
    re.IGNORECASE,
)

# Pure syntactic edits — we must NOT override the user's wording/tone here.
# These win over transformative triggers if both match.
_EDIT_ONLY_INSTRUCTION_RE = re.compile(
    r"\b(corrige(r|z)?|correct|corriger|typo|typos|faute|fautes|orthographe|"
    r"grammaire|traduis|traduire|translate|raccourcis|raccourcir|r[ée]sume(r|z)?|"
    r"abr[èe]ge(r|z)?|shorten|proofread|fix\s+(the\s+)?typo)\b",
    re.IGNORECASE,
)


def _should_enforce_contact_tone(instruction: str) -> bool:
    """Option-2 gating: apply contact-style tone adaptation only when the
    instruction is transformative (compose/draft/expand/rewrite) — never for
    pure syntactic edits (typo fix, translation, shortening). This protects
    /corrige, /traduis, /raccourcis flows from having their wording rewritten
    by Haiku for tone-matching purposes.
    """
    if not instruction:
        return False
    if _EDIT_ONLY_INSTRUCTION_RE.search(instruction):
        return False
    return bool(_TRANSFORMATIVE_INSTRUCTION_RE.search(instruction))


# ── Explicit target-language extraction from the user's instruction ──────────
# Audit 2026-06-17 — a free-text « Generate from notes » instruction like
# « traduit en anglais » must drive the draft's OUTPUT language. Without this,
# `detected_lang` keys on the DRAFT body (the SOURCE language) and the LANGUAGE
# HARD CONSTRAINT (rule-7 override) then forbids the very switch the user asked
# for — so every translate-this-draft request was silently ignored (user
# report). Bounded to the 3 languages the LANGUAGE directive supports
# (fr/en/es); any other target returns None and the draft keeps its language.
_TARGET_LANG_NAME_TO_ISO = {
    "anglais": "en", "english": "en", "ingles": "en",
    "francais": "fr", "french": "fr", "frances": "fr",
    "espagnol": "es", "spanish": "es", "espanol": "es",
}
# A supported language name immediately preceded by a directional marker
# (into/in/to/en/vers/au/al/a). The marker is what disambiguates a genuine
# translation target ("en anglais", "to English") from an incidental mention
# ("voyage en Angleterre" — no supported language name follows the marker).
_TARGET_LANG_RE = re.compile(
    r"\b(?:into|in|to|en|vers|au|al|a)\s+(?:l['’]\s*)?"
    r"(anglais|english|ingles|francais|french|frances|espagnol|spanish|espanol)\b",
    re.IGNORECASE,
)


def _detect_requested_target_language(instruction: str) -> Optional[str]:
    """Return 'fr' | 'en' | 'es' when `instruction` explicitly asks to write /
    translate the email in that language, else None.

    Accent-insensitive (« français » == « francais ») and bounded to the
    languages the LANGUAGE directive can enforce — an unsupported target
    (e.g. « en allemand ») returns None so the draft keeps its language rather
    than being half-translated.
    """
    if not instruction:
        return None
    norm = unicodedata.normalize("NFD", instruction)
    norm = "".join(c for c in norm if unicodedata.category(c) != "Mn").lower()
    match = _TARGET_LANG_RE.search(norm)
    if match:
        return _TARGET_LANG_NAME_TO_ISO.get(match.group(1))
    return None


def _strip_trailing_signature(body: str, typical_signature: Optional[str] = None) -> str:
    """Remove a LLM-emitted signature block from the end of a generated email
    body. Signature is never wanted in the pipeline output because the
    frontend renders it as a separate footer (see useAccountSignature) —
    otherwise the compose window shows the signature twice.

    Strategy: walk backwards from the end of the body, dropping trailing
    lines as long as they match any of:
      - a token from ``typical_signature`` (split on whitespace/commas/dashes)
      - a common "title" line (Co-fondateur, Founder, CEO, Président…)
      - a bare sender name (2-4 capitalized words, no verb)
    Stop as soon as we hit the closing line (Cordialement, À bientôt, Merci,
    Salut, Bonne journée, …) or any line that looks like real body content.
    """
    if not body or not body.strip():
        return body

    sig_tokens: set[str] = set()
    if typical_signature:
        for tok in re.split(r"[\s,;\-]+", typical_signature):
            tok = tok.strip().lower()
            if len(tok) >= 3:
                sig_tokens.add(tok)

    _CLOSING_WORDS = (
        r"cordialement|bien\s+à\s+(?:toi|vous)|bien\s+cordialement|"
        r"à\s+bientôt|à\s+très\s+bientôt|à\s+plus|à\s+tantôt|"
        r"merci(?:\s+(?:encore|beaucoup|d['’]avance))?|thanks|thank\s+you|"
        r"best(?:\s+regards)?|regards|sincerely|salut|bonne\s+journée|"
        r"bonne\s+soirée|bonne\s+semaine|au\s+plaisir|amicalement|"
        r"amitiés|cheers|ciao|talk\s+soon|see\s+you\s+soon|see\s+you"
    )
    # Pure closing line (nothing after the closing word besides punctuation).
    _CLOSING_RE = re.compile(
        rf"^\s*(?:{_CLOSING_WORDS})\s*[,\.!]?\s*$",
        re.IGNORECASE,
    )
    # Closing at the start of a line followed by more content — in that case
    # we want to truncate the line at the end of the punctuation, so the
    # signature that shares the same line as the closing (e.g.
    # "À bientôt, Alexandre Simon Co-fondateur, Agentys") gets cut off
    # cleanly at the comma after "À bientôt".
    _CLOSING_PREFIX_RE = re.compile(
        rf"^(\s*(?:{_CLOSING_WORDS})\s*[,\.!])\s+\S",
        re.IGNORECASE,
    )
    _TITLE_RE = re.compile(
        r"(co-?fondateur|founder|ceo|cto|pdg|président|director|directeur|"
        r"manager|lead|head\s+of|vp\s+of|owner|propriétaire|freelance|"
        r"consultant|agentys)",
        re.IGNORECASE,
    )
    _NAME_ONLY_RE = re.compile(
        r"^\s*[A-ZÉÈÊÀÂÔÎÏŒÇ][a-zéèêàâôîïœç'’\-]+"
        r"(\s+[A-ZÉÈÊÀÂÔÎÏŒÇ][a-zéèêàâôîïœç'’\-]+){0,3}\s*$"
    )

    lines = body.rstrip().split("\n")
    # Walk backwards; drop trailing signature-like lines until closing or content.
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        # Case A: closing word at the start of the line followed by more
        # content (signature glued to closing). Truncate the line at the
        # closing punctuation and stop.
        prefix_match = _CLOSING_PREFIX_RE.match(last)
        if prefix_match:
            lines[-1] = prefix_match.group(1).rstrip()
            break
        # Case B: pure closing line on its own — stop, we're at the boundary.
        if _CLOSING_RE.match(last):
            break
        low = last.lower()
        is_title = bool(_TITLE_RE.search(last))
        is_name_only = bool(_NAME_ONLY_RE.match(last)) and len(last.split()) <= 4
        has_sig_token = any(tok in low for tok in sig_tokens) if sig_tokens else False
        if is_title or is_name_only or has_sig_token:
            lines.pop()
            continue
        # Line looks like real body content — stop.
        break

    # Safety-net pass: strip a closing phrase glued to the end of a body
    # sentence when the body ALSO has a standalone closing line below. This
    # catches the LLM's habit of writing "...vendredi à 10h. À très bientôt!\n\nÀ bientôt,"
    # — two sign-offs where the user expects exactly one. We trust the
    # standalone closing line as authoritative and remove the inline one.
    has_standalone_closing = any(
        _CLOSING_RE.match(ln.strip()) for ln in lines if ln.strip()
    )
    if has_standalone_closing:
        # Match: any non-empty character (the body sentence), followed by
        # sentence punctuation, followed by an inline closing phrase that
        # ends with !/./, — strip just that trailing phrase.
        _INLINE_CLOSING_RE = re.compile(
            rf"(?<=[\.\!\?])\s+(?:{_CLOSING_WORDS})\s*[!\.,]?\s*$",
            re.IGNORECASE,
        )
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped:
                continue
            # Skip the standalone closing line itself.
            if _CLOSING_RE.match(stripped):
                continue
            new_ln = _INLINE_CLOSING_RE.sub("", ln).rstrip()
            if new_ln != ln:
                lines[i] = new_ln

    return "\n".join(lines).rstrip()


def _build_tone_directive(formality: Optional[str]) -> Optional[str]:
    """Render a non-negotiable tone directive from a ContactStyleProfile's
    ``formality_override``. Returns None when no formality is set."""
    if not formality:
        return None
    fm = formality.strip().lower()
    if fm == "casual":
        return (
            "TUTOIEMENT OBLIGATOIRE : ce destinataire est un contact casual. "
            "Écris EN TUTOYANT (tu, te, ton, ta, tes, toi, t'). Remplace "
            "systématiquement «vous/votre/vos/Désirez-vous/Pourriez-vous/"
            "Auriez-vous/Voulez-vous» par la forme tutoyée équivalente. "
            "Si l'input est une note courte en vouvoiement, reformule "
            "intégralement en tutoiement et développe en 1-3 phrases "
            "chaleureuses sans inventer d'informations factuelles nouvelles."
        )
    if fm == "formal":
        return (
            "VOUVOIEMENT OBLIGATOIRE : ce destinataire est un contact formel. "
            "Utilise «vous/votre/vos» partout. Aucune tournure familière, "
            "aucun tutoiement, aucune contraction orale (pas de «ça te», "
            "«t'as», «dis-moi»). Si l'input est tutoyé, reformule-le en "
            "vouvoiement sans inventer d'informations factuelles nouvelles."
        )
    return None


@api_bp.route("/refine-text", methods=["POST"])
def refine_text():
    """
    Apply an AI instruction to user-written text (e.g. fix typos, translate).

    Lightweight endpoint: single LLM call, no Critique pipeline.

    Body JSON:
        text: The user-written text to refine (required, max 10000 chars)
        instruction: What to do with the text (required, max 1000 chars)
        email_id: Optional context email ID (unused for now, reserved)

    Returns:
        { success: true, refined_text: "..." }
    """
    # Per-tenant bucket (H-8 follow-up #534): bare "refine_text" mutualisait
    # le quota de 15 req/min sur tous les tenants ; un user saturait la
    # quota et DoS-ait Anthropic paid pour les autres.
    # Audit F-03 (2026-05-16): switched to `_per_caller_bucket_key` so the
    # `-1` sentinel (JWT users pre-OAuth) no longer collapses all such
    # callers into one shared bucket. JWT identity (email/sub) is used
    # as the salt when no DB account is resolved yet.
    from app.api.routes_helpers import _per_caller_bucket_key
    allowed, retry_after = _rate_limited(
        _per_caller_bucket_key("refine_text"), max_calls=15, window_seconds=60,
    )
    if not allowed:
        return jsonify({"error": "Rate limit exceeded", "retry_after": retry_after}), 429

    data, error = require_json()
    if error:
        return error

    text = data.get("text")
    instruction = data.get("instruction")
    to_field = (data.get("to") or "").strip()
    sender_name_hint = (data.get("sender_name") or "").strip()
    target_language = (data.get("target_language") or "").strip().lower().split("-")[0]
    if target_language not in ("fr", "en", "es"):
        target_language = ""
    use_specialty = bool(data.get("use_specialty"))
    subject_field = (data.get("subject") or "").strip()
    # Surgical mode (bouton crayon "Modifier le brouillon") — applique
    # UNIQUEMENT la modification ciblée et préserve tout le reste byte-for-
    # byte. Bypass des enrichissements style/tone qui réécriraient le texte
    # non-ciblé (mandatory_opening, tone_directive, contact-style, closing
    # enforcement, signature stripping, greeting separation).
    surgical = bool(data.get("surgical"))

    if not text or not isinstance(text, str):
        return jsonify({"error": "text is required and must be a string"}), 400
    if not instruction or not isinstance(instruction, str):
        return jsonify({"error": "instruction is required and must be a string"}), 400

    text = text.strip()
    instruction = instruction.strip()

    if not text:
        return jsonify({"error": "text cannot be empty"}), 400
    if not instruction:
        return jsonify({"error": "instruction cannot be empty"}), 400
    if len(text) > MAX_REFINE_TEXT_LENGTH:
        return jsonify({"error": f"text exceeds maximum length of {MAX_REFINE_TEXT_LENGTH} characters"}), 400
    if len(instruction) > MAX_REFINE_INSTRUCTION_LENGTH:
        return jsonify({"error": f"instruction exceeds maximum length of {MAX_REFINE_INSTRUCTION_LENGTH} characters"}), 400

    # Issue #457 (Phase 1) — sanitize the SHORT user→AI command. `text` is
    # NOT chevron-sanitized at intake : it can legitimately contain URLs,
    # HTML, code snippets, and `surgical` mode is contractually byte-for-
    # byte preserving — mangling chevrons there would degrade UX. The
    # wrapper at the prompt-construction site auto-escapes the closing tag
    # so `text` cannot break out from inside the envelope either.
    from app.prompts.builders import sanitize_user_input
    instruction = sanitize_user_input(instruction)

    # Audit Round-4 (2026-05-19): detect the language of the user's notes
    # so the system prompt, style guidance, and mandatory opening can
    # anchor the draft to the right language. Pre-fix: `build_style_
    # guidance_from_profile` was called with `language="fr"` hard-coded
    # and `mandatory_opening` always produced "Salut/Bonjour {name},",
    # forcing 100% of English-note Ctrl+G drafts back to French. Same
    # detection shape as /compose/suggest-subject (routes_misc.py:1322-
    # 1329). The blob includes subject too so a single-line "Hi Alex"
    # subject can anchor language when the body is short.
    # Resolve the user's onboarding primary language first: it is both the
    # safe fallback when detection is unreliable and the baseline the switch
    # below is measured against.
    try:
        from app.prompts import load_primary_language_for_account
        _primary_lang = _PRIMARY_LANG_TO_ISO.get(
            load_primary_language_for_account(_rh._resolve_account_id_for_user()), "fr"
        )
    except Exception:
        _primary_lang = "fr"
    _lang_blob = ((text or "") + "\n" + (subject_field or "")).strip()
    try:
        from app.application.detect_language import DetectLanguage
        detected_lang = DetectLanguage().run(_lang_blob) if _lang_blob else _primary_lang
    except Exception:
        detected_lang = _primary_lang
    if detected_lang not in ("fr", "en", "es"):
        detected_lang = _primary_lang
    # Audit 2026-05-20 (round-4 regression): ignore a low-confidence switch
    # AWAY from the primary language on a too-short note — langdetect flips
    # short FR notes to "en" and drags the whole draft into English. A switch
    # TO, or agreement with, the primary language is always safe to keep.
    if (
        detected_lang != _primary_lang
        and len(_lang_blob.split()) < _MIN_WORDS_FOR_NONPRIMARY_LANG
    ):
        logger.debug(
            "refine-text: ignoring low-confidence '%s' detection on a %d-word "
            "note; keeping primary language '%s'",
            detected_lang, len(_lang_blob.split()), _primary_lang,
        )
        detected_lang = _primary_lang
    if target_language and not surgical:
        detected_lang = target_language

    # Audit 2026-06-17 — an explicit language-change instruction ("traduit en
    # anglais", "translate to French") must drive the output language and win
    # over BOTH the draft's detected source language AND the thread
    # target_language hint above (which can point the other way). Without this,
    # the LANGUAGE HARD CONSTRAINT below forbids the very switch the user asked
    # for and the translation is silently dropped (user report).
    lang_from_instruction = False
    if not surgical:
        _instr_target = _detect_requested_target_language(instruction)
        if _instr_target:
            detected_lang = _instr_target
            lang_from_instruction = True

    # Stricter rate limit for expert mode (Sonnet plan + Haiku draft ≈ 30x
    # more expensive per call). Independent bucket so the standard Ctrl+G
    # path is unaffected.
    if use_specialty:
        # Per-tenant expert bucket — same shape as the standard refine_text
        # path (already per-tenant above). Also via `_per_caller_bucket_key`
        # so the `-1` sentinel is salted with JWT identity (F-03).
        allowed_expert, retry_expert = _rate_limited(
            _per_caller_bucket_key("refine_text_expert"),
            max_calls=3, window_seconds=60,
        )
        if not allowed_expert:
            return jsonify({
                "error": "Rate limit exceeded for expert mode",
                "retry_after": retry_expert,
                "hint": "Use Ctrl+G (standard mode) in the meantime",
            }), 429

    try:
        container = _rh._get_container()
        # Refine standard = user-triggered draft retouch → drafting key (Haiku).
        # Surgical = chirurgie sur un détail précis → llm_drafting_smart (Sonnet).
        # Sonnet obéit beaucoup mieux aux instructions strictes "ne change que X" ;
        # Haiku a tendance à templater les noms et reformuler. Coût négligeable
        # car surgical = edits ponctuels, pas des batches.
        llm = container.llm_drafting_smart if surgical else container.llm_drafting

        # Load the user's WritingStyleProfile and dispatch to the ContactStyleProfile
        # matching the recipient (if known). This is critical for the "Rédiger à partir
        # de notes" flow: the Drafter can then use the recipient's nickname, habitual
        # greeting, closing, and formality — just like the reply/compose pipelines.
        style_context = ""
        first_to = (to_field.split(",")[0] if "," in to_field else to_field).strip().lower()
        contact_nickname: Optional[str] = None
        contact_greeting: Optional[str] = None
        contact_formality: Optional[str] = None
        contact_preferred_closing: Optional[str] = None
        contact_formality_locked: bool = False
        typical_signature: Optional[str] = None
        # Resolve the INT DB account_id — NOT AccountConfig.id, which is a
        # hash string like "458130f56b9bb6f0" and does not match the
        # style_profile_<int>.json file naming scheme. Hoisted outside the
        # try so specialty classification (below) can reuse it to load
        # per-account active_specialties from the DB — without that, the
        # Ctrl+Shift+G mode only reads global settings.json (empty on
        # Railway) and always reports no_active_specialty.
        _account_id = _rh._resolve_account_id_for_user()
        try:
            if _account_id and _account_id > 0:
                _profile = container.get_writing_style_profile(account_id=_account_id)
                if _profile:
                    typical_signature = getattr(_profile, "typical_signature", None)
                    if first_to:
                        from app.prompts.style_guidance import build_style_guidance_from_profile
                        # Audit Round-4 (2026-05-19): when detected lang != fr,
                        # SKIP the few-shot style block. `build_style_guidance_
                        # from_profile` only localizes the LABELS — the example
                        # emails inside the few-shot block stay in the user's
                        # native language (FR for this user). Those raw FR
                        # examples then out-prime the LANGUAGE OVERRIDE
                        # directive and the model produces FR bodies even
                        # with explicit "write in English" instructions
                        # (verified on en_apology_01 and en_jargon_saas_01 in
                        # the round-4 20-case retest). Losing personalisation
                        # for non-FR drafts is the lesser evil vs producing
                        # wrong-language drafts.
                        if detected_lang == "fr":
                            style_context = build_style_guidance_from_profile(
                                _profile, language=detected_lang, recipient_email=first_to
                            )
                        else:
                            style_context = ""
                        # Resolve by PERSON: an override stored on one of a
                        # contact's addresses (e.g. the work email) backfills a
                        # draft to their other address (e.g. the gmail). This is
                        # the LIVE generation path — "expand my notes" Generate
                        # hits /api/refine-text, not /api/emails/compose — so the
                        # per-person resolution must apply here too.
                        from app.application.services._compose_path import (
                            resolve_contact_override_data,
                        )
                        _contact_data = resolve_contact_override_data(
                            _profile.contact_profiles, first_to
                        )
                        if _contact_data:
                            _nick_val = _contact_data.get("nickname")
                            if isinstance(_nick_val, str) and _nick_val.strip():
                                contact_nickname = _nick_val.strip()
                            _greet_val = _contact_data.get("preferred_greeting")
                            # Validate before adopting: a polluted profile may
                            # have learned a non-greeting first line from a
                            # previous draft (2026-05-13 incident). Reject
                            # silently and let `mandatory_opening` fall back
                            # to the canonical "Salut {nickname}," branch.
                            from app.smart_routing import is_canonical_greeting_for_contact
                            if (
                                isinstance(_greet_val, str)
                                and is_canonical_greeting_for_contact(
                                    _greet_val, contact_nickname or ""
                                )
                            ):
                                contact_greeting = _greet_val.strip()
                            elif isinstance(_greet_val, str) and _greet_val.strip():
                                logger.warning(
                                    "refine-text: rejecting non-canonical "
                                    "preferred_greeting %r for contact %s",
                                    _greet_val[:80], first_to,
                                )
                            _form_val = _contact_data.get("formality_override")
                            if isinstance(_form_val, str) and _form_val.strip():
                                contact_formality = _form_val.strip().lower()
                            # Bug fix 2026-05-13: read per-contact preferred_closing
                            # so we can override the user-level closing when the
                            # user has explicitly chosen a closing for this contact
                            # (e.g. "À bientôt," on a Casual-locked contact). The
                            # onboarding "(no closing)" sentinel and empty/whitespace
                            # values are filtered out — same defence as
                            # build_contact_hint_block in style_guidance.py.
                            _close_val = _contact_data.get("preferred_closing")
                            if isinstance(_close_val, str) and _close_val.strip():
                                from app.prompts.identity import _is_no_closing_marker
                                if not _is_no_closing_marker(_close_val):
                                    contact_preferred_closing = _close_val.strip()
                            contact_formality_locked = bool(
                                _contact_data.get("formality_locked", False)
                            )
        except Exception as _style_err:
            logger.debug(f"refine-text: writing style profile load failed: {_style_err}")

        # Audit 2026-05-19 (T31.1): when the writing-style profile lacks a
        # `typical_signature`, `_strip_trailing_signature` falls back to
        # generic role-keyword detection only — a bare "Alexandre Simon,"
        # leaked by the LLM (rule 10 violation) slips through and renders
        # as a name doublon next to the signature widget. Hydrate from the
        # account's stored signature_text (or display_name) so the stripper's
        # token-matching branch always has fuel.
        if not typical_signature and _account_id and _account_id > 0:
            try:
                from app.db.database import get_db_session
                from app.db.repositories.account_repository import AccountRepository
                with get_db_session() as _sess:
                    _acc = AccountRepository(_sess).get(_account_id)
                    if _acc:
                        _sig_text = _acc.signature_text
                        _disp_name = _acc.display_name
                        _candidate = ""
                        if isinstance(_sig_text, str):
                            _candidate = _sig_text.strip()
                        if not _candidate and isinstance(_disp_name, str):
                            _candidate = _disp_name.strip()
                        if _candidate:
                            typical_signature = _candidate
            except Exception as _sig_err:
                logger.debug(f"refine-text: typical_signature account-fallback failed: {_sig_err}")

        # ── Specialty forced on explicit user intent (Ctrl+Shift+G) ─────────
        # UNIQUE CONDITION to apply the specialty : use_specialty=True.
        # Le raccourci Ctrl+Shift+G signale une demande explicite de
        # l'utilisateur — on ne filtre plus par keyword matching sur le
        # sujet/corps (source antérieure de frustration : un sujet typoé
        # comme "vis caché" au lieu de "vice caché" faisait tomber en
        # no_match et dégradait en génération standard sans expertise).
        #
        # Stratégie :
        #   1. Résoudre les spécialités actives (per-compte via DB).
        #   2. Si au moins une → forcer le match sur la première avec ses
        #      experts de priorité 1 (build_default_match), en laissant le
        #      classifier raffiner la catégorie si le contenu s'y prête.
        #   3. Si aucune active → surface "no_active_specialty" (le
        #      frontend doit proposer d'en activer une).
        specialty_info: Optional[dict] = None
        specialty_context_text: str = ""
        specialty_name_for_plan: str = ""
        if use_specialty:
            try:
                from app.specialty_engine import get_specialty_engine
                from app.api.settings import load_settings
                # account_id pour que les activations per-compte (DB)
                # remontent — data/settings.json est éphémère sur Railway.
                _settings_account_id = _account_id if _account_id and _account_id > 0 else None
                active = load_settings(account_id=_settings_account_id).get("active_specialties", []) or []
                if not active:
                    specialty_info = {"warning": "no_active_specialty"}
                else:
                    engine = get_specialty_engine()
                    # Le classifier reste utile pour choisir la MEILLEURE
                    # catégorie dans la spécialité matchée (pour que les
                    # experts chargés collent au contenu). Mais il ne peut
                    # plus bloquer : si rien ne match, on force la 1re
                    # active avec les experts de priorité 1.
                    match = engine.classify_email(
                        subject=subject_field,
                        body=text,
                        active_specialties=active,
                    )
                    if match is None and len(active) == 1:
                        # Only force the default specialty when the user has a
                        # SINGLE active expertise (unambiguous). With 2+ active
                        # specialties, forcing active[0] injected wrong-domain
                        # expert guidance into unrelated emails (launch audit
                        # 2026-05-30). No match + multiple specialties => no
                        # specialty context, rather than the wrong one.
                        match = engine.build_default_match(active[0])
                    if match:
                        specialty_context_text = engine.build_specialty_context(match)
                        specialty_info = match.to_dict()
                        specialty_name_for_plan = match.specialty_name
                    else:
                        # active[0] introuvable sur disque (spec supprimée
                        # sans nettoyer settings). Très rare.
                        specialty_info = {"warning": "specialty_unavailable"}
            except Exception as _spec_err:
                logger.warning("refine-text specialty classification failed: %s", _spec_err)
                specialty_info = {"warning": "classification_error"}

        # Safety net (2026-05-14): a stale or cross-contaminated ContactStyleProfile
        # row can carry a *different* contact's nickname. Since the nickname is
        # enforced as the mandatory opening, that poisons EVERY draft to this
        # recipient (incident: alexandre.simon@hotmail.com held "Nat"). Drop a
        # nickname with no plausible link to the recipient address — and log it.
        if contact_nickname:
            from app.prompts.identity import _nickname_matches_recipient
            if not _nickname_matches_recipient(contact_nickname, first_to):
                logger.warning(
                    "refine-text: stored nickname %r looks unrelated to recipient "
                    "%s — ignoring it (possible stale/corrupt contact profile)",
                    contact_nickname, first_to,
                )
                contact_nickname = None

        # Hard opening directive — Haiku treats the inline "e.g. Salut Kiki,"
        # hint in to_prompt_hint() as optional. Restate it as a non-negotiable
        # rule so the refined text opens with exactly the right greeting.
        #
        # Audit Round-4 (2026-05-19): localize the FR-stored greeting to the
        # input language so an English note doesn't get forced to "Salut Alex,"
        # which then pulled the whole body to French (100% of EN inputs in the
        # 2026-05-19 audit). Stored contact greetings remain FR-canonical;
        # we translate only at the prompt-construction site.
        def _localize_greeting(g: Optional[str]) -> Optional[str]:
            if not g or detected_lang == "fr":
                return g
            lower = g.lower()
            if detected_lang == "en":
                if lower.startswith("salut "):
                    return "Hi " + g[6:]
                if lower.startswith("bonjour "):
                    return "Hi " + g[8:]
                if lower.startswith("coucou "):
                    return "Hey " + g[7:]
            if detected_lang == "es":
                if lower.startswith("salut "):
                    return "Hola " + g[6:]
                if lower.startswith("bonjour "):
                    return "Hola " + g[8:]
            return g

        mandatory_opening: Optional[str] = None
        if contact_nickname:
            # Single source of truth shared with both compose paths. Handles
            # tokenized templates ("Bonjour {first_name},"), literal-with-name
            # ("Salut Nathan," → "Salut Nat,", not "Salut Nathan, Nat,"),
            # and bare-word-with-comma ("Bonjour," → "Bonjour Nat,", NOT the
            # double-comma "Bonjour, Nat," the old inline logic here produced).
            from app.application.services._compose_path import build_mandatory_opening
            mandatory_opening = build_mandatory_opening(contact_greeting, contact_nickname)
            if mandatory_opening:
                mandatory_opening = _localize_greeting(mandatory_opening)
        elif sender_name_hint:
            # No contact profile found — use the sender_name passed by the client
            # as a fallback to avoid the LLM inferring names from Gmail + aliases
            # (e.g. user+Invoice+statements@gmail.com → "Invoice statements").
            _first = sender_name_hint.split()[0] if sender_name_hint.split() else sender_name_hint
            mandatory_opening = _localize_greeting(f"Bonjour {_first},")
        elif first_to and _account_id and _account_id > 0:
            # New-compose mode without a sender_name_hint from the client (the
            # NewMessageModal didn't track the display name from autocomplete
            # selection, or the user typed the email directly). Last-resort
            # safety net: look up the recipient in the contacts DB and use the
            # stored display name. Without this, the LLM falls back to the
            # email-username heuristic and ships "Hi contact," or
            # similar awkward greetings on every new-compose draft to a
            # recipient that isn't in the writing-style contact_profiles map.
            try:
                from app.db.database import get_db_session
                from app.db.repositories.contact_repository import ContactRepository
                with get_db_session() as _sess:
                    _ct = ContactRepository(_sess).get_by_email(first_to, _account_id)
                    _ct_name = (_ct.name or "").strip() if _ct else ""
                if _ct_name:
                    _first = _ct_name.split()[0] if _ct_name.split() else _ct_name
                    mandatory_opening = _localize_greeting(f"Bonjour {_first},")
            except Exception as _ct_err:
                logger.debug(
                    "refine-text: contacts DB display-name fallback failed: %s",
                    _ct_err,
                )

        # Multi-recipient override: when expanding notes into an email addressed
        # to 2+ people, a single-contact greeting (e.g. "Salut Alex,") is
        # exclusionary regardless of what the per-contact profile says. Replace
        # it with a group greeting derived from the To field.
        # Issue #592: pass contact_profiles so 2 recipients with mixed or
        # unknown formality fall back to a register-neutral group greeting
        # instead of "Bonjour Alice et Bob," (forces a tone on a contact
        # whose signal is unknown).
        from app.application.services._compose_path import _multi_recipient_greeting_hint
        _cp = None
        try:
            if '_profile' in locals() and _profile is not None:
                _cp = _profile.contact_profiles
        except Exception:
            _cp = None
        _multi_greeting = _multi_recipient_greeting_hint(to_field, None, _cp)
        if _multi_greeting:
            mandatory_opening = _localize_greeting(_multi_greeting)

        # Option-2 gating: apply contact-style tone adaptation only for
        # transformative instructions ("transforme en email complet", "rédige",
        # "développe", …). Pure syntactic edits (/corrige, /traduis, /raccourcis)
        # keep the user's wording intact — we don't want "Corrige les typos"
        # to rewrite the whole email in tutoiement.
        tone_directive: Optional[str] = None
        if contact_formality and _should_enforce_contact_tone(instruction):
            tone_directive = _build_tone_directive(contact_formality)

        if surgical:
            # Surgical : édition à diff minimal. L'utilisateur veut changer
            # UNE chose précise dans le brouillon (ex: "remplace 20h par 21h",
            # "enlève la mention de Marc", "rends le ton plus casual"). Tout
            # ce qui n'est pas explicitement ciblé par l'instruction DOIT
            # rester byte-for-byte identique.
            logger.info(
                "refine-text: surgical mode ON (text_len=%d, instruction=%r)",
                len(text), instruction[:80],
            )
            system_prompt = (
                "You are a SURGICAL text editor. Apply ONLY the change the user "
                "explicitly asks for. Output the full modified text.\n"
                "\n"
                "ABSOLUTE RULES (violations cause rejection):\n"
                "1. Identify exactly what the instruction targets. Modify ONLY that.\n"
                "2. Every word, sentence, and paragraph NOT targeted MUST be preserved "
                "verbatim — same wording, same punctuation, same casing, same line "
                "breaks, same blank lines.\n"
                "3. NEVER reformulate, NEVER 'improve', NEVER change the tone or "
                "register, NEVER fix unrelated typos, NEVER change the greeting or "
                "closing unless the instruction explicitly targets them.\n"
                "4. NEVER add new sentences, ideas, or details that aren't required "
                "by the instruction. NEVER remove sentences unless the instruction "
                "asks.\n"
                "5. If the instruction is ambiguous about scope, apply it at the "
                "STRICTEST minimum (one phrase, one word) — never broader.\n"
                "6. NEVER insert template placeholders or variable syntax like "
                "`{name}`, `{first_name}`, `[X]`, `<var>`, `${{var}}`, `%recipient%`, "
                "etc. If a name like \"Alexandre\" appears in the original, KEEP IT "
                "verbatim — do NOT \"templatize\" it. Names, dates, places stay as "
                "literal strings.\n"
                "7. NEVER replace proper nouns (people, companies, cities) with "
                "anything else — they are part of the protected verbatim region.\n"
                "8. The closing formula (\"À bientôt,\", \"Cordialement,\", "
                "\"Bien à toi,\", etc.) MUST remain byte-identical unless the user "
                "instruction explicitly says \"change le closing\" / \"replace the "
                "closing\". Different closing formula = rejection.\n"
                "9. NO planning, analysis, reasoning, explanation, meta-commentary.\n"
                "10. NO markdown headers, NO code fences, NO 'Here is', 'I'll', etc.\n"
                "11. The FIRST character of your response is the first character of "
                "the modified text. The LAST character is the last character.\n"
                "12. Preserve the original language exactly.\n"
                "13. NO SIGNATURE BLOCK appended.\n"
                "\n"
                "EXAMPLE of CORRECT surgical edit:\n"
                "  ORIGINAL: \"Bonjour Alexandre,\\n\\nJe veux te voir demain à 20h.\\n\\nÀ bientôt,\"\n"
                "  INSTRUCTION: \"remplace 20h par 21h\"\n"
                "  CORRECT OUTPUT: \"Bonjour Alexandre,\\n\\nJe veux te voir demain à 21h.\\n\\nÀ bientôt,\"\n"
                "  WRONG OUTPUT (rejected): \"Bonjour {first_name},\\n\\nJ'aimerais te rencontrer demain à 21h.\\n\\nCordialement,\"\n"
                "  Why wrong: replaced \"Alexandre\" with \"{first_name}\" (rule 6+7), "
                "rephrased \"Je veux te voir\" → \"J'aimerais te rencontrer\" (rule 3), "
                "changed \"À bientôt\" → \"Cordialement\" (rule 8)."
            )
            # Bypass volontaire : style_context, mandatory_opening, tone_directive
            # — ils pousseraient Haiku à réécrire, ce qui est l'inverse du but.
        else:
            system_prompt = (
                "You are a text transformation engine. Output the final text ONLY.\n"
                "\n"
                "ABSOLUTE RULES (violations cause automatic rejection):\n"
                "1. NO planning, analysis, reasoning, or explanation.\n"
                "2. NO markdown headers (#, ##, ###).\n"
                "3. NO triple-dash fences (---) or code fences (```) around the output.\n"
                "4. NO phrases like \"I'll\", \"I will\", \"Let me\", \"Here is\", \"Here's\", "
                "\"Plan:\", \"Context:\", \"Analysis:\", \"Transformation:\", \"Output:\", "
                "\"Verification:\", \"Note content:\", \"Intended Output:\".\n"
                "5. The FIRST character of your response is the first character of the final text.\n"
                "6. If the instruction is to transform notes into an email, output the email body directly "
                "(greeting, content, closing) — nothing before, nothing after.\n"
                "7. Preserve the original language unless explicitly asked to translate.\n"
                "8. NEVER refuse — always produce a usable result, even from minimal input.\n"
                "9. NEVER emit meta-commentary like \"Je dois\", \"Note:\", \"Résolution\", \"Contradiction\".\n"
                "10. NO SIGNATURE BLOCK. Never append the sender's name, title, or "
                "company after the closing. The body ends at the closing line "
                "(«À bientôt,», «Cordialement,», etc.) and NOT one line further. "
                "The signature is rendered separately by the client UI as a footer "
                "— duplicating it here creates a visible doublon in the compose window.\n"
                "11. STRUCTURE RULES (for emails with multiple ideas):\n"
                "    • If the output has ≥2 distinct ideas, use bullet points (•) "
                "or numbered lists (1. 2. 3.) for enumerations.\n"
                "    • One idea = one paragraph. Paragraphs MUST be 1-3 lines maximum.\n"
                "    • Separate every paragraph (and every list block) by a BLANK line.\n"
                "    • Use inline labels when relevant (e.g. \"Ma recommandation :\", "
                "\"Next steps:\").\n"
                "    • For short emails (1 idea), 1-2 lines is enough — do not inflate.\n"
                "12. The body ends at the closing line («À bientôt,», «Cordialement,», "
                "«Best,», etc.). Output absolutely nothing after the closing — no "
                "schema label, no bracketed token, no role description, no caption. "
                "The body IS the body; never append a meta-label naming what you "
                "just produced.\n"
                "13. NEVER emit template placeholders or variable syntax like "
                "`{name}`, `{prénom}`, `[Name]`, `${var}`, `%recipient%`. Write the "
                "literal greeting and name — or a neutral greeting if no name is "
                "known — never a bracketed token. Leaked placeholders are an "
                "embarrassing AI tell in a real outgoing email.\n"
                "14. The output is addressed to the RECIPIENT only. NEVER embed an "
                "aside or question to the USER about the source text or the "
                "instruction (completeness, ambiguity, formatting). If the notes "
                "trail off (\"et...\", \"etc.\"), keep the items that were given and "
                "stop — no parenthetical like \"(la liste semble incomplète, "
                "peux-tu compléter ?)\" inside the email body."
            )
        # Issue #682 — prompt caching: track the static rules separately
        # from per-recipient / per-call directives so the LLMPort adapter can
        # place `cache_control: ephemeral` only on the byte-stable prefix.
        # Pre-fix: `system_prompt` was one growing string and a per-contact
        # `mandatory_opening` change busted the entire cached prefix on every
        # refine. Post-fix: the rules-block segment is identical across all
        # refine calls of the same user (surgical xor non-surgical), so it
        # caches cross-recipient as soon as it clears the model's prompt-cache
        # token floor.
        static_rules = system_prompt
        dynamic_directives: list[str] = []
        # Audit Round-4 (2026-05-19): explicit language anchor. Rule 7 of the
        # non-surgical system prompt ("Preserve the original language unless
        # explicitly asked to translate") is too soft — the LLM treats it as
        # optional in the presence of any FR-leaning signal (FR mandatory
        # opening, FR style context, FR recipient nickname). Hardening as a
        # dedicated directive after rule 12 plus a label in the detected lang.
        if not surgical:
            _LANG_LABELS = {
                "fr": ("FRENCH (français)", "Écris l'email entièrement en français."),
                "en": ("ENGLISH", "Write the entire email in English. Use English greetings (Hi, Hello), English closings (Best, Thanks, Cheers, Talk soon, Sincerely), and English vocabulary throughout."),
                "es": ("SPANISH (español)", "Escribe el correo entero en español. Usa saludos y despedidas españoles."),
            }
            _lang_label, _lang_instr = _LANG_LABELS.get(detected_lang, _LANG_LABELS["fr"])
            _closing_warn = ""
            if detected_lang != "fr":
                # Static rule 12 above mentions «À bientôt,», «Cordialement,»,
                # «Best,» as closing examples. Few-shot bias pulls EN drafts
                # back to a FR closing on ~10% of attempts even with the
                # LANGUAGE OVERRIDE (round-4 retest: en_casual_short_01).
                # Explicitly null the FR examples for non-FR drafts.
                _closing_warn = (
                    " The French closing examples in rule 12 («À bientôt,», "
                    "«Cordialement,») apply ONLY when writing French — "
                    "IGNORE them entirely for this draft and end with a "
                    f"{_lang_label} closing."
                )
            # When the target language came from an explicit translate
            # instruction, the SOURCE text is in another language on purpose —
            # say so, otherwise "the user's notes are in {lang}" contradicts the
            # (differently-languaged) draft sitting in the prompt.
            _lang_lead = (
                f"the user explicitly asked to write the email in {_lang_label}"
                if lang_from_instruction
                else f"the user's notes are in {_lang_label}"
            )
            dynamic_directives.append(
                f"LANGUAGE (HARD CONSTRAINT — overrides rule 7): {_lang_lead}. "
                f"{_lang_instr} Do NOT switch to French if "
                f"the detected language is English/Spanish, and do NOT switch to "
                f"English if the detected language is French. The closing line "
                f"MUST be in the same language as the body (e.g. \"Best,\" / "
                f"\"Talk soon,\" for English, NOT \"À bientôt,\").{_closing_warn}"
            )
        if not surgical and style_context:
            dynamic_directives.append(
                f"{style_context}\n\n"
                "When expanding notes into an email, apply the recipient's style above: "
                "match the habitual tone/formality and use the habitual closing. "
                "For purely syntactic edits (typo fixes, translation, shortening), keep the "
                "user's wording intact and only apply contact style when it does not contradict."
            )
        if not surgical and mandatory_opening:
            dynamic_directives.append(
                f"MANDATORY OPENING LINE: when the output is an email body "
                f"(i.e. not a pure typo-fix or translation of a single phrase), "
                f"the FIRST line of the output MUST be exactly «{mandatory_opening}» — "
                f"not «Bonjour,», not «Salut,», not a full first name, this exact nickname. "
                "Replace any other greeting the user may have written with this one. "
                "This rule is non-negotiable."
            )
        if not surgical and tone_directive:
            dynamic_directives.append(tone_directive)
        # Issue #457 (Phase 1) — wrap both user-controlled values in
        # untrust envelopes. `instruction` is already chevron-sanitized at
        # intake ; `text` (up to 10k chars, may contain legitimate URLs /
        # HTML / code) is auto-escaped by wrap_untrusted on the closing
        # tag only — preserves byte-for-byte content for surgical mode.
        from app.prompts.builders import wrap_untrusted
        user_prompt = (
            "INSTRUCTION :\n"
            + wrap_untrusted(instruction, tag="user-instruction")
            + "\n\nTEXT :\n"
            + wrap_untrusted(text, tag="user-text")
        )
        if not surgical and mandatory_opening:
            user_prompt += (
                f"\n\nREMINDER: start the refined email with exactly this line: "
                f"{mandatory_opening}"
            )

        # ── Two-call flow: Sonnet PLAN → Haiku DRAFT ──────────────────────
        # When expert context was loaded, Sonnet reasons about applicable
        # laws/rules and produces a structured plan. Haiku then writes the
        # email following that plan verbatim, citing articles INLINE in the
        # prose (e.g. "(arts. 1726-1733 CCQ)") — no footnote anymore. If the
        # Sonnet call fails, we degrade gracefully by injecting the raw
        # expert context directly into Haiku's system prompt.
        draft_max_tokens = 800
        if specialty_context_text:
            try:
                from app.prompts.specialty_plan import (
                    build_specialty_plan_prompt,
                    extract_sources_from_plan,
                    build_draft_augmentation,
                )
                plan_system, plan_user = build_specialty_plan_prompt(
                    notes=text,
                    subject=subject_field,
                    specialty_context=specialty_context_text,
                    style_context=style_context,
                    instruction=instruction,
                    specialty_name=specialty_name_for_plan or "expertise",
                )
                plan_response = container.llm_drafting_smart.complete(
                    system=plan_system,
                    user=plan_user,
                    max_tokens=1500,
                    temperature=0.3,
                )
                plan_text = (plan_response.content or "").strip()
                if plan_text and specialty_info is not None:
                    applied_sources = extract_sources_from_plan(plan_text)
                    specialty_info["applied_sources"] = applied_sources
                    specialty_info["plan_preview"] = plan_text
                    # Issue #682: expertise plan is per-call (Sonnet output
                    # varies on every refine), so it lives in the dynamic
                    # segment — never part of the cached prefix.
                    dynamic_directives.append(
                        build_draft_augmentation(plan_text, applied_sources).lstrip()
                    )
                    # Higher cap for expert mode: prose is denser when articles
                    # are cited inline + 3-4 paragraphs vs short refine.
                    draft_max_tokens = 1100
                else:
                    logger.warning(
                        "refine-text: Sonnet plan returned empty — "
                        "degrading to direct expertise injection"
                    )
                    dynamic_directives.append(
                        f"<EXPERTISE>\n{specialty_context_text}\n</EXPERTISE>"
                    )
                    if specialty_info is not None:
                        specialty_info["warning"] = "plan_empty_fallback"
            except Exception as _plan_err:
                logger.warning(
                    "refine-text: Sonnet plan call failed (%s) — "
                    "degrading to direct expertise injection",
                    _plan_err,
                )
                dynamic_directives.append(
                    f"<EXPERTISE>\n{specialty_context_text}\n</EXPERTISE>"
                )
                if specialty_info is not None:
                    specialty_info["warning"] = "plan_failed_fallback"

        # Issue #682 — assemble the system as `[static_rules cacheable,
        # dynamic_directives non-cacheable]`. Adapter wraps each SystemSegment
        # in an Anthropic content block; only the cacheable one carries
        # `cache_control: ephemeral`. Below the model's prompt-cache token
        # floor the marker is a no-op write — no regression vs the pre-fix
        # single-string path. Above the floor (most non-trivial refines),
        # the static rules are byte-stable across recipients and across calls
        # for the same user, so cache hits compound.
        #
        # Adjacent content blocks are presented to the model with no
        # separator inserted between them. The pre-fix path glued sections
        # with an explicit "\n\n" (e.g. `system_prompt += f"\n\n{style_context}…"`),
        # so we prepend the same separator to the dynamic block to preserve
        # byte-identical prompt text — zero behavioural drift.
        from app.domain.ports.llm_port import SystemSegment as _SS
        system_blocks: list = [_SS(text=static_rules, cacheable=True)]
        dynamic_text = "\n\n".join(p for p in dynamic_directives if p)
        if dynamic_text:
            system_blocks.append(_SS(text="\n\n" + dynamic_text, cacheable=False))

        # max_tokens=800 covers 99% of refine cases (refine operates on existing
        # text ±30%). Lower cap prevents ClaudeCodeAdapter from generating full
        # markdown plans before the final output and speeds generation 2-3x.
        # Expert mode raises the cap (1100) for denser prose with inline citations.
        response = llm.complete(
            system=system_blocks,
            user=user_prompt,
            max_tokens=draft_max_tokens,
            temperature=0.2,
        )

        refined = response.content.strip()
        if not refined:
            return jsonify({"error": "LLM returned empty result"}), 500

        # Strip chain-of-thought reasoning leakage
        refined = _strip_refine_reasoning(refined)

        # ─── Validation post-LLM en mode surgical ────────────────────────
        # Mode chirurgical : detect 2 patterns d'over-edit fréquents quand le
        # LLM ignore le prompt strict :
        #
        # 1. **Templatization** : le LLM remplace un nom propre ("Alexandre")
        #    par un placeholder ("{first_name}"). Détecté en cherchant des
        #    patterns {var}, [var], ${var}, %var% qui n'étaient pas dans
        #    l'input.
        # 2. **Suppression de noms propres** : un mot capitalisé dans l'input
        #    qui disparaît du output sans être mentionné dans l'instruction.
        #    Heuristique simple : capture les mots Capitalisés (≥3 lettres,
        #    pas en début de phrase trivial type "Bonjour"/"Merci").
        #
        # Si l'un fire → on rejette avec un message clair. L'utilisateur
        # peut réessayer avec une instruction plus précise. Mieux vaut un
        # refus visible qu'un draft fucked-up silencieusement.
        # ─── Anti-templating (both modes) ───────────────────────────────
        # Detect template placeholders the LLM introduced that were NOT in the
        # input ({first_name}, [Name], ${var}, %recipient%). Diffing against the
        # input avoids false positives on brackets the user authored themselves.
        template_re = re.compile(
            r"(\{[a-zA-Z_]\w*\}|\[[a-zA-Z_]\w*\]|\$\{[a-zA-Z_]\w*\}|%[a-zA-Z_]\w*%)"
        )
        input_placeholders = set(template_re.findall(text))
        output_placeholders = set(template_re.findall(refined))
        new_placeholders = output_placeholders - input_placeholders

        if not surgical and new_placeholders:
            # Non-surgical legitimately rewrites, so STRIP the leaked tokens
            # rather than 422-rejecting — the user still gets a usable draft.
            # ("Bonjour {prénom}," → "Bonjour," after cleanup.) The later
            # non-surgical greeting normalization repairs anything left ragged.
            logger.warning(
                "[refine] Stripping leaked template placeholders %r from non-surgical output",
                sorted(new_placeholders),
            )
            for _ph in new_placeholders:
                refined = refined.replace(_ph, "")
            # Tidy the artefacts a bare removal leaves behind: "Bonjour ," and
            # doubled spaces.
            refined = re.sub(r"[ \t]+([,.;:!?])", r"\1", refined)
            refined = re.sub(r"[ \t]{2,}", " ", refined)

        if surgical:
            if new_placeholders:
                logger.warning(
                    "[surgical] Rejected: LLM introduced template placeholders %r "
                    "not present in input. Input snippet: %r, output snippet: %r",
                    sorted(new_placeholders), text[:120], refined[:120],
                )
                _placeholders = ", ".join(sorted(new_placeholders))
                return error_response(
                    "AI_SURGICAL_TEMPLATE_LEAK",
                    f"The AI tried to template the draft (placeholder {_placeholders} introduced). Try again with a more precise instruction.",
                    422,
                    context={"placeholders": _placeholders},
                    extra={"code": "surgical_template_leak"},
                )

            # Détection de noms propres disparus. On extrait les mots de 3+
            # lettres commençant par une majuscule, hors stopwords français
            # courants en début de phrase et hors mots de l'instruction
            # (qui peuvent légitimement contenir des noms à modifier).
            _CAP_STOPWORDS = {
                "Bonjour", "Salut", "Hello", "Hi", "Cordialement", "Bien",
                "Merci", "À", "Je", "Tu", "Il", "Elle", "Nous", "Vous", "Ils",
                "Elles", "Le", "La", "Les", "Un", "Une", "Des", "Mon", "Ma",
                "Mes", "Ton", "Ta", "Tes", "Son", "Sa", "Ses", "Notre", "Votre",
                "Leur", "Ce", "Cette", "Ces", "Ainsi", "Donc", "Mais", "Alors",
                "Demain", "Hier", "Aujourd'hui", "Lundi", "Mardi", "Mercredi",
                "Jeudi", "Vendredi", "Samedi", "Dimanche", "Janvier", "Février",
                "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre",
                "Octobre", "Novembre", "Décembre",
            }
            cap_re = re.compile(r"\b[A-ZÀ-Ý][a-zà-ÿ]{2,}\b")
            input_caps = set(cap_re.findall(text)) - _CAP_STOPWORDS
            output_caps = set(cap_re.findall(refined)) - _CAP_STOPWORDS
            instruction_caps = set(cap_re.findall(instruction))
            # Un nom propre est "perdu" s'il était dans l'input, n'est plus
            # dans l'output, ET n'est pas explicitement mentionné dans
            # l'instruction (l'utilisateur peut légitimement demander
            # "remplace Alexandre par Bertrand").
            lost_caps = input_caps - output_caps - instruction_caps
            if lost_caps:
                logger.warning(
                    "[surgical] Rejected: proper nouns disappeared without being "
                    "mentioned in instruction. Lost: %r, instruction: %r",
                    sorted(lost_caps), instruction[:80],
                )
                _names = ", ".join(sorted(lost_caps))
                return error_response(
                    "AI_SURGICAL_PROPER_NOUN_LOST",
                    f"The AI removed an unmentioned name ({_names}). Try again with a more precise instruction.",
                    422,
                    context={"names": _names},
                    extra={"code": "surgical_proper_noun_lost"},
                )

        # Ensure greeting stands alone on its own line
        from app.smart_routing import (
            _separate_greeting_from_body,
            _enforce_closing,
            _strip_duplicate_greetings,
            _strip_malformed_opening,
            _ensure_starts_with_greeting,
        )
        # Surgical mode bypasse les passes de normalisation parce qu'elles
        # toucheraient des parties que l'utilisateur n'a pas demandé de
        # changer (séparation de greeting, dédoublonnage, signature, closing).
        # _rt_account_id reste calculé pour le tracking learning ci-dessous.
        _rt_account_id = _rh._resolve_account_id_for_user()
        if not surgical:
            # Rip out the "Je ne peux pas mais Je," anti-pattern Haiku
            # occasionally produces from dictated notes when squeezed by
            # the "Never refuse" rule. Done BEFORE greeting enforcement so
            # the prepended greeting lands on a clean first line, not on
            # top of a mangled stub. See user report 2026-05-12.
            refined = _strip_malformed_opening(refined)

            refined = _separate_greeting_from_body(refined)

            # Strip duplicate greetings and bare-name vocatives ("Bonjour Alexandre,\nAlexandre,")
            # that Haiku emits when the user's notes start with their own vocative.
            refined = _strip_duplicate_greetings(refined)

            # Guarantee the draft opens with mandatory_opening when the LLM
            # ignored both the system-prompt rule AND the user-prompt
            # REMINDER. Refine-text previously had no post-LLM greeting
            # enforcement (unlike the reply pipeline which calls
            # `_enforce_greeting`), so an opening like "demain je ne suis
            # pas dispo..." shipped without a salutation. Prepend now —
            # surgical mode stays untouched.
            #
            # `strict_replace`: when the contact has an explicit override
            # (nickname / preferred_greeting / formality_locked), the user
            # has already declared "always greet this contact like X". Even
            # if Haiku copied a different greeting from the user's dictated
            # notes (e.g. "M. Simon," on a Casual-locked contact), the
            # per-contact rule wins. Without strict mode, the legacy
            # behaviour silently keeps whatever greeting the LLM emitted —
            # which is the 2026-05-13 Simon bug.
            _strict_greeting = bool(
                contact_nickname or contact_greeting or contact_formality_locked
            )
            refined = _ensure_starts_with_greeting(
                refined, mandatory_opening, strict_replace=_strict_greeting,
            )

            # Belt-and-suspenders: strip any trailing signature block Haiku
            # emitted in spite of the NO SIGNATURE directive in the system prompt.
            refined = _strip_trailing_signature(refined, typical_signature)

            # Guarantee a closing formula. /refine-text has no source email
            # (free-form refine), so we derive formality + language from the
            # draft text itself. replace_existing=False preserves any closing
            # the user had already written.
            try:
                from app.prompts import (
                    _compute_closing_hint, analyze_email_formality, _detect_language,
                    load_primary_language_for_account,
                )
                _formality_rt = analyze_email_formality(text)
                _language_rt = _detect_language(
                    text,
                    fallback_language=load_primary_language_for_account(_rt_account_id),
                )
                # Audit Round-4 (2026-05-19): the marker-based `_detect_language`
                # returns "FRENCH" by default on short / marker-poor inputs
                # ("ping him to confirm friday 2pm call still on" yields 0
                # EN markers and 0 FR markers → fallback to user's primary
                # language = FRENCH). That fed an FR closing hint downstream
                # and let the LLM-leaked «À bientôt,» survive _enforce_closing
                # even after the round-4 LANGUAGE OVERRIDE forced an EN body.
                # `detected_lang` (computed above via langdetect) is the
                # authoritative input-language signal — apply it as an
                # override so the closing hint matches the body language.
                # Audit 2026-05-19 (F-03): "es" must map to SPANISH, not FRENCH.
                # The old "es":"FRENCH" forced a French closing ("Cordialement,")
                # onto Spanish drafts. _compute_closing_hint now has a SPANISH
                # branch ("Atentamente,"/"Saludos cordiales,"/"Un saludo,").
                _DETECTED_TO_DRAFTER = {"fr": "FRENCH", "en": "ENGLISH", "es": "SPANISH"}
                _drafter_lang_from_detect = _DETECTED_TO_DRAFTER.get(detected_lang)
                if _drafter_lang_from_detect and _drafter_lang_from_detect != _language_rt:
                    logger.debug(
                        "refine-text: closing-language override %s -> %s (detected_lang=%s)",
                        _language_rt, _drafter_lang_from_detect, detected_lang,
                    )
                    _language_rt = _drafter_lang_from_detect
                _preferred_rt: list[str] | None = None
                try:
                    if '_profile' in locals() and _profile and _profile.preferred_closings:
                        _preferred_rt = list(_profile.preferred_closings)
                except Exception:
                    pass
                # Bug fix 2026-05-13: when the contact has an explicit
                # preferred_closing (e.g. "À bientôt," on a Casual-locked
                # contact), it MUST take priority over the user-level list.
                # Without this, the user's most-frequent closing leaks
                # into a draft addressed to a contact for whom the user
                # explicitly chose something else ("Merci!," instead of
                # "À bientôt,").
                if contact_preferred_closing:
                    _preferred_rt = [contact_preferred_closing] + (_preferred_rt or [])
                _closing_hint_rt = _compute_closing_hint(
                    _formality_rt, _language_rt, _preferred_rt,
                )
                # When the contact has an explicit preferred_closing we
                # also force replacement of whatever closing the LLM kept
                # from the user's dictated notes. Otherwise (no per-contact
                # signal) we keep the permissive behaviour so /corrige et
                # /traduis don't rewrite a user-written closing.
                #
                # Audit Round-4 (2026-05-19): ALSO force replacement when
                # the detected input language differs from the closing's
                # language. Even with the LANGUAGE OVERRIDE in the system
                # prompt, Haiku sometimes leaks «À bientôt,» as a sticky
                # FR-canonical closing on EN drafts (round-4 retest:
                # en_casual_short_01 reproduced this on 2/2 attempts).
                # `_language_rt` was overridden above to match the
                # langdetect-based `detected_lang`, so the closing hint is
                # in the right language — we just need to actually let it
                # replace the leaked FR closing. The previous version of
                # this check compared lowercase "fr" against the uppercase
                # "FRENCH" return value and silently always evaluated True.
                # Also force the swap for ES (audit F-03): Haiku can leak a
                # sticky FR/EN closing onto a Spanish draft; _language_rt is now
                # "SPANISH", so the hint is in the right language and should
                # replace the leaked one.
                _force_lang_swap = detected_lang in ("en", "es")
                refined = _enforce_closing(
                    refined,
                    _closing_hint_rt,
                    replace_existing=bool(contact_preferred_closing) or _force_lang_swap,
                )
            except Exception as _ce:
                logger.debug(f"refine-text: closing enforcement skipped: {_ce}")

            # Issue #592: collapse stacked contextual + canonical closings
            # ("À ce vendredi !" above "À bientôt,", or "À bientôt, à ce
            # vendredi" on the same line). Runs after _enforce_closing so
            # the canonical line is in its normalized form first.
            try:
                from app.smart_routing import _strip_stacked_contextual_closing
                refined = _strip_stacked_contextual_closing(refined)
            except Exception as _stack_err:
                logger.debug(f"refine-text: stacked closing strip failed: {_stack_err}")

            # Humanize AI-style dashes (em/en dash, spaced hyphen) the model
            # used as connectors — a comma reads like something a person typed.
            # Gated on `not surgical` so a targeted edit stays byte-for-byte
            # and never rewrites a dash the user wrote on purpose.
            from app.utils.draft_cleanup import strip_ai_dashes
            refined = strip_ai_dashes(refined)

        # Backstop: re-run the structural-placeholder strip one more time
        # after ALL passes. PR #744 hardened the regex for Unicode whitespace
        # but the leak persisted in round-3 R3.1 — the LLM keeps emitting
        # "Reply body," at the tail despite system-prompt rule 12. The
        # earlier strip in `_strip_refine_reasoning` runs BEFORE the
        # signature strip / closing enforce / stacked-closing strip, so any
        # placeholder line those passes shifts to a new tail position
        # would survive. Running the strip again here catches that.
        refined = _PLACEHOLDER_STRUCTURAL_RE.sub("", refined)
        # Same backstop for a bare leaked schema VALUE ("unknown", …) that
        # Haiku drops where the closing belongs. Global/multiline so it also
        # catches the value when `_enforce_closing` appended a real closing
        # AFTER it (pushing it off the tail); the blank-line collapse below
        # tidies the gap left behind.
        refined = _LEAKED_SCHEMA_VALUE_RE.sub("", refined)

        # Last-resort tail trim: if the body still ends with a 1-3-word
        # ALL-Latin-letters line that doesn't look like a real closing word
        # (and isn't a known proper noun in the body), drop it. Handles
        # variants the regex misses ("Final reply", "End of message",
        # numbered debug markers, etc.) without touching legitimate prose.
        _CLOSING_TAIL_WORDS = {
            "cordialement", "merci", "thanks", "regards", "best", "bien",
            "amicalement", "respectueusement", "sincerely", "cheers", "salut",
            "ciao", "au plaisir",
        }
        _tail_lines = refined.rstrip().split("\n")
        if _tail_lines:
            _last_clean = _tail_lines[-1].strip().rstrip(",.;:!?").lower()
            _word_count = len(_last_clean.split())
            if (
                _word_count > 0
                and _word_count <= 3
                and _last_clean not in _CLOSING_TAIL_WORDS
                and not any(_last_clean.startswith(w + " ") for w in _CLOSING_TAIL_WORDS)
                and re.fullmatch(r"[A-Za-zÀ-ÿ '\-]+", _last_clean) is not None
                and re.search(r"\b(body|corps|message|reply|email|content|draft)\b",
                              _last_clean) is not None
            ):
                _tail_lines.pop()
                refined = "\n".join(_tail_lines).rstrip()

        # Final blank-line collapse — the post-LLM passes
        # (_strip_trailing_signature, _enforce_closing, …) each leave stray
        # blank lines around the chunks they remove or insert. Without this
        # pass, the ProseMirror editor renders 4–5 consecutive empty
        # paragraphs between greeting/body/closing (audit 2026-05-19
        # round-2 R1 + R2 reproduction).
        refined = re.sub(r"\n{3,}", "\n\n", refined).strip()
        refined = strip_terminal_parenthetical_note(refined)

        # Track refine AI usage
        try:
            from app.draft_quality_tracker import get_tracker
            get_tracker().record_feature("refine_ai", account_id=str(_rt_account_id or ""))
        except Exception:
            pass

        # Learning: enregistrer l'instruction de refine pour apprendre les préférences
        try:
            from app.draft_learning import get_draft_learning_store
            learning_store = get_draft_learning_store(account_id=_rt_account_id if _rt_account_id and _rt_account_id > 0 else None)
            learning_store.record_refine_instruction(
                instruction=instruction,
                before_text=text,
                after_text=refined,
                contact=data.get("contact", "") or first_to,
            )
        except Exception:
            pass

        # NOTE — la footnote "--- Sources : ..." server-side a été retirée.
        # Elle sentait l'output académique et trahissait l'origine LLM. Le
        # nouveau prompt (specialty_plan.py + response-guidelines.md) demande
        # au rédacteur de citer les articles INLINE, en parenthèse dans la
        # prose ("(arts. 1726-1733 CCQ)") — c'est plus naturel et garde
        # l'email lisible comme une vraie correspondance.
        #
        # `specialty_info["applied_sources"]` reste exposé dans la réponse
        # pour audit/observabilité côté frontend (badge debug, eval harness),
        # mais n'est plus collé en footnote du corps.

        response_payload: dict = {"success": True, "refined_text": refined}
        if specialty_info is not None:
            response_payload["specialty_info"] = specialty_info
        return jsonify(response_payload)

    except Exception as e:
        logger.error(f"Error refining text: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# Security: Max length for regenerate instruction
MAX_REGENERATE_INSTRUCTION_LENGTH = 2000


@api_bp.route("/drafts/<draft_id>/regenerate", methods=["POST"])
def regenerate_draft_content(draft_id: str):
    """
    Regenere un brouillon completement avec de nouvelles instructions.

    Relance le pipeline complet : Draft V1 -> Critique -> (V2 si necessaire)
    avec les nouvelles instructions fournies par l'utilisateur.

    Args:
        draft_id: ID du brouillon (format Agentys).

    Body JSON:
        instructions: Les nouvelles instructions pour regenerer le brouillon (requis, max 2000 chars)

    Returns:
        Resultat avec le nouveau brouillon et les details du pipeline.
    """
    # Security: Validate draft_id format to prevent injection attacks
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    instructions = data.get("instructions", "")

    if not isinstance(instructions, str):
        return jsonify({"error": "instructions must be a string"}), 400

    instructions = instructions.strip()

    if len(instructions) > MAX_REGENERATE_INSTRUCTION_LENGTH:
        return jsonify({
            "error": f"instructions exceeds maximum length of {MAX_REGENERATE_INSTRUCTION_LENGTH} characters"
        }), 400

    # Isolation multi-compte
    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    # Get the draft record and original email (scoped)
    container = _rh._get_container()
    draft_record = container.get_draft_history().get_by_id_for_account(draft_id, account_id)

    # The frontend sends a PendingDraft.id (UUID) for the PRIMARY draft path,
    # which lives in the PendingDraftStore — not DraftHistory. Without this
    # fallback, regenerate 404'd on every main draft (launch audit 2026-05-30).
    _pending = None
    if not draft_record:
        from types import SimpleNamespace
        _pd = container.get_pending_draft_store().get_by_id(draft_id)
        if _pd is not None and str(getattr(_pd, "account_id", "")) == str(account_id):
            _pending = _pd
            draft_record = SimpleNamespace(
                email_id=_pd.email_id,
                email_sender=_pd.email_sender,
                email_subject=_pd.email_subject,
                email_preview=(_pd.email_body or ""),
                email_sender_name=getattr(_pd, "email_sender_name", "") or "",
                draft_id=getattr(_pd, "gmail_draft_id", None),
                draft_final=_pd.draft_body,
            )

    if not draft_record:
        return jsonify({"error": "Draft not found"}), 404

    # Get the original email for context
    email_id = draft_record.email_id
    email = None
    if email_id:
        from app.providers.factory import get_pooled_provider as _get_pooled
        provider = _get_pooled()
        try:
            email = provider.get_email(email_id)
        finally:
            if hasattr(provider, 'disconnect'):
                try:
                    provider.disconnect()
                except Exception:
                    pass

    if not email:
        return jsonify({"error": "Original email not found"}), 404

    gmail_draft_id = draft_record.draft_id

    try:
        previous_body = draft_record.draft_final

        if not instructions:
            # No instructions → run full SmartRouter pipeline (account agent, FAQ, etc.)
            from app.smart_routing import SmartRouter
            router = SmartRouter()
            _sender = email.get("sender", draft_record.email_sender or "")
            _subject = email.get("subject", draft_record.email_subject or "")
            _body = email.get("body", draft_record.email_preview or "")
            _sender_name = email.get("sender_name") or draft_record.email_sender_name or None
            email_content = f"De: {_sender_name or _sender} <{_sender}>\nSujet: {_subject}\n\n{_body}"
            try:
                from app.smart_routing import evict_draft_cache
                evict_draft_cache(email_id, account_id=account_id)
            except Exception:
                pass
            routing_result = router.route(
                email_id=email_id,
                email_content=email_content,
                sender=_sender,
                subject=_subject,
                body=_body,
                sender_name=_sender_name,
                force=True,
            )
            regenerated_body = routing_result.draft.strip() if routing_result.draft else ""
            draft_v1_content = routing_result.draft_v1 or regenerated_body
            critique_feedback = ""
            critique_is_valid = True
            _regen_account_info = None
            if routing_result.critique_info:
                critique_feedback = routing_result.critique_info.get("feedback", "")
                critique_is_valid = routing_result.critique_info.get("is_valid", True)
                _regen_account_info = routing_result.critique_info.get("account_info")
            was_corrected = bool(draft_v1_content and regenerated_body and draft_v1_content != regenerated_body)

            # Inject password if account_info carries a generated password
            if _regen_account_info and _regen_account_info.get("action") == "password_reset":
                _regen_pw_full = _regen_account_info.get("_generated_password_full")
                if _regen_pw_full:
                    _regen_brand = _regen_account_info.get("brand_name") or ""
                    _regen_brand_label = f" sur {_regen_brand}" if _regen_brand else ""
                    _regen_pw_line = f"Votre nouveau mot de passe{_regen_brand_label} : {_regen_pw_full}"
                    if "[MOT_DE_PASSE]" in regenerated_body:
                        regenerated_body = regenerated_body.replace("[MOT_DE_PASSE]", _regen_pw_line)
                        logger.info("[AccountAgent] Regenerate: mot de passe injecté (placeholder)")
                    else:
                        _rg_lines = regenerated_body.split("\n")
                        _rg_last = len(_rg_lines) - 1
                        while _rg_last > 0 and not _rg_lines[_rg_last].strip():
                            _rg_last -= 1
                        _rg_lines.insert(_rg_last, "")
                        _rg_lines.insert(_rg_last, _regen_pw_line)
                        regenerated_body = "\n".join(_rg_lines)
                        logger.info("[AccountAgent] Regenerate: placeholder absent — mot de passe injecté en position finale")
                    # Store secure password for Confirm button
                    try:
                        _regen_account_info.pop("_generated_password_full", None)
                        _rh._get_container().get_pending_draft_store().store_secure_password(draft_id, _regen_pw_full)
                    except Exception:
                        pass
        else:
            # Instructions provided → use the dedicated regenerate pipeline
            regenerate_use_case = container.get_regenerate_use_case()
            from app.domain.entities import Email as DomainEmail
            domain_email = DomainEmail(
                id=email.get("id", email_id),
                sender=email.get("sender", draft_record.email_sender),
                subject=email.get("subject", draft_record.email_subject),
                body=email.get("body", draft_record.email_preview),
                received_at=email.get("received_at"),
            )
            result = regenerate_use_case.execute(
                email=domain_email,
                instructions=instructions,
                context_summary=None,
            )
            regenerated_body = result.draft_final.content.strip()
            draft_v1_content = result.draft_v1.content
            critique_feedback = result.critique.reason or result.critique.raw_response
            critique_is_valid = result.critique.is_valid
            was_corrected = result.was_corrected

        if not regenerated_body:
            return jsonify({"error": "Failed to generate content"}), 500

        # Update the draft in Gmail if there's a Gmail draft ID
        if gmail_draft_id:
            try:
                provider = LegacyModuleLoader.email_provider()
                if provider.authenticate():
                    success = provider.update_draft(
                        draft_id=gmail_draft_id,
                        body=regenerated_body,
                    )
                    if not success:
                        logger.warning(f"Failed to update Gmail draft {gmail_draft_id}")
            except Exception as gmail_err:
                logger.warning(f"Error updating Gmail draft: {gmail_err}")

        # Persist the regenerated body. For a PendingDraft (the primary path)
        # write back to the pending-draft store via update_content; for a
        # DraftHistory record, append the updated record to history.
        if _pending is not None:
            container.get_pending_draft_store().update_content(
                draft_id, _pending.draft_subject, regenerated_body
            )
        else:
            draft_record.draft_v1 = draft_v1_content
            draft_record.critique = critique_feedback
            draft_record.draft_final = regenerated_body
            container.get_draft_history().add(draft_record)

        # Learning: enregistrer le regenerate comme signal négatif enrichi
        try:
            from app.draft_learning import get_draft_learning_store
            learning_store = get_draft_learning_store(account_id=account_id)
            learning_store.record_regeneration(
                email_id=email_id,
                previous_body=previous_body or "",
                instructions=instructions,
                contact=draft_record.email_sender or "",
            )
        except Exception:
            pass

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "regenerated_body": regenerated_body,
            "previous_body": previous_body,
            "instructions_used": instructions,
            "pipeline_details": {
                "draft_v1": draft_v1_content,
                "critique": {
                    "is_valid": critique_is_valid,
                    "feedback": critique_feedback,
                },
                "was_corrected": was_corrected,
            },
        })

    except Exception as e:
        logger.error(f"Error regenerating draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# ============================================================================
# EDIT FEEDBACK LOOP (#196)
# ============================================================================

MAX_EDIT_TELEMETRY_CONTENT = 50_000


@api_bp.route("/drafts/<draft_id>/edit-telemetry", methods=["POST"])
def record_edit_telemetry(draft_id: str):
    """Enregistre un événement d'édition utilisateur sur un draft.

    Body JSON:
        initial: Contenu initial (draft IA).
        final: Contenu final (envoyé par l'utilisateur).
        intent: Intent structurel (voir IntentCategory, optionnel).
        recipient_email: Destinataire (optionnel).
        original_email_id: ID numérique de l'email original (optionnel).

    Retour:
        {"success": true, "event_id": 42, "category": "length_adjustment", "magnitude": 0.35}
    """
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    data, error = require_json()
    if error:
        return error

    initial = data.get("initial", "")
    final = data.get("final", "")
    if not isinstance(initial, str) or not isinstance(final, str):
        return jsonify({"error": "initial and final must be strings"}), 400
    if len(initial) > MAX_EDIT_TELEMETRY_CONTENT or len(final) > MAX_EDIT_TELEMETRY_CONTENT:
        return jsonify({
            "error": f"content exceeds {MAX_EDIT_TELEMETRY_CONTENT} chars"
        }), 400

    if initial == final:
        # Pas d'édition — ne pas polluer la DB.
        return jsonify({"success": True, "skipped": "no_change"})

    account_id = _rh._resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404

    from app.services.edit_analyzer_service import build_event
    from app.db.database import get_db_session
    from app.db.repositories.draft_edit_event_repository import DraftEditEventRepository

    intent = data.get("intent")
    recipient_email = data.get("recipient_email")
    original_email_id = data.get("original_email_id")
    if original_email_id is not None:
        try:
            original_email_id = int(original_email_id)
        except (TypeError, ValueError):
            original_email_id = None

    event = build_event(
        draft_id=draft_id,
        account_id=account_id,
        initial=initial,
        final=final,
        intent=intent if isinstance(intent, str) else None,
        recipient_email=recipient_email if isinstance(recipient_email, str) else None,
        original_email_id=original_email_id,
    )

    try:
        with get_db_session() as session:
            repo = DraftEditEventRepository(session)
            event_id = repo.add(event)
    except Exception as e:
        logger.error("Failed to persist edit telemetry: %s", _sanitize_for_log(str(e)))
        return jsonify({"error": "An internal error occurred"}), 500

    return jsonify({
        "success": True,
        "event_id": event_id,
        "category": event.category.value,
        "magnitude": round(event.magnitude, 4),
    })


# ============================================================================
# DELIVERABILITY SCORING (#192)
# ============================================================================

MAX_DELIVERABILITY_CONTENT = 50_000


@api_bp.route("/deliverability/score", methods=["POST"])
def score_deliverability():
    """Score la deliverability d'un draft (patterns spam, subject health, liens).

    Body JSON:
        subject: Sujet du mail.
        body: Corps du mail (texte plain).

    Retour:
        {"score": 85, "issues": [{"code": "...", "severity": "warn", "message": "..."}]}

    Endpoint stateless (pas de persistance) — destiné au scoring live en UI.
    Aucun appel réseau : calcul heuristique synchrone.
    """
    data, error = require_json()
    if error:
        return error

    subject = data.get("subject", "")
    body = data.get("body", "")
    if not isinstance(subject, str):
        subject = ""
    if not isinstance(body, str):
        body = ""
    if len(subject) > 1000 or len(body) > MAX_DELIVERABILITY_CONTENT:
        return jsonify({"error": "content too large"}), 400

    from app.services.deliverability_service import score_draft

    report = score_draft(subject, body)
    return jsonify(report.to_dict())
