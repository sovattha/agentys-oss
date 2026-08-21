# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API pour la ré-analyse du style d'écriture depuis l'outbox (issue #187).

Endpoint:
- POST /api/style/reanalyze  — déclenche l'analyse sur les N derniers emails envoyés.

Audit 2026-05-04 (P1.6) : la recommandation initiale "migrer vers Anthropic
Batch API (50% off)" était basée sur une lecture incorrecte du code.
StyleInferenceService est PUREMENT déterministe (regex + stdlib, aucun appel
LLM, cf. app/domain/services/style_inference_service.py:11). Donc Batch API
ne s'applique pas — il n'y a aucun LLM call à batcher. En revanche le vrai
problème UX (endpoint synchrone bloquant le HTTP pendant ~5-30s sur 500
emails) est résolu via le mode async ci-dessous : l'endpoint accepte
``async=true`` et lance un thread background, retourne 202 + ws task_id.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from flask import Blueprint, jsonify, request

from app.domain.entities.writing_style import WritingStyleProfile
from app.domain.services.style_inference_service import StyleInferenceService

logger = logging.getLogger(__name__)

style_inference_bp = Blueprint("style_inference", __name__)

MIN_EMAILS_REQUIRED = 20
DEFAULT_OUTBOX_LIMIT = 500


def _emit_reanalyze_event(account_id: int, payload: dict) -> None:
    """Best-effort WebSocket emission of the async reanalyze result.

    Non-fatal: if the WS infra isn't reachable, the result is still
    persisted to the DB (the next /api/style/profile fetch picks it up).

    Audit 2026-05-04 self-review : la signature canonique de emit_to_account
    est ``(event: str, data: dict, account_id: int|None)`` — facile à
    intervertir et le try/except masque l'erreur. Sentinel candidate.
    """
    try:
        from app.api.websocket import emit_to_account
        emit_to_account(
            "style:reanalyze_complete",
            payload,
            account_id,
        )
    except Exception as exc:
        logger.debug("[style/reanalyze] WS emit failed (non-fatal): %s", exc)


def _run_reanalyze_async(account_id: int, limit: int, task_id: str) -> None:
    """Background worker for async reanalyze. Persists profile + emits WS."""
    try:
        sent_emails = _get_sent_emails(account_id, limit)
        email_count = len(sent_emails)
        if email_count < MIN_EMAILS_REQUIRED:
            _emit_reanalyze_event(account_id, {
                "task_id": task_id,
                "status": "failed",
                "error": (
                    f"not enough sent emails (found {email_count}, "
                    f"need {MIN_EMAILS_REQUIRED})"
                ),
            })
            return

        service = StyleInferenceService()
        metrics = service.analyze_outbox(sent_emails)
        examples = service.select_reference_examples(sent_emails)
        safe_examples = [ex for ex in examples if ex.anonymized]
        if len(safe_examples) != len(examples):
            logger.error(
                "[style/reanalyze async] anonymization gap: %d/%d for account %d",
                len(examples) - len(safe_examples), len(examples), account_id,
            )
            _emit_reanalyze_event(account_id, {
                "task_id": task_id,
                "status": "failed",
                "error": "anonymization failed for some examples",
            })
            return

        profile = _build_profile(account_id, email_count, metrics, safe_examples)
        _persist_profile(account_id, profile)
        _emit_reanalyze_event(account_id, {
            "task_id": task_id,
            "status": "completed",
            "account_id": account_id,
            "email_count": email_count,
            "metrics": metrics,
            "examples_count": len(safe_examples),
        })
    except Exception:
        logger.exception(
            "[style/reanalyze async] worker failed for account %s", account_id,
        )
        _emit_reanalyze_event(account_id, {
            "task_id": task_id,
            "status": "failed",
            "error": "internal error",
        })


@style_inference_bp.route("/reanalyze", methods=["POST"])
def reanalyze_style() -> Any:
    """Ré-analyse le style à partir de l'outbox du compte authentifié.

    Body JSON (optionnel): {limit?: int, async?: bool}
    Response sync (default): 200 {status, email_count, metrics, examples_count}
    Response async (P1.6, async=true): 202 {status: "started", task_id}.
        Le résultat arrive via WebSocket event ``style:reanalyze_complete``
        (status="completed"|"failed").

    L'account_id est toujours résolu depuis la session authentifiée (g.auth_user)
    via _resolve_account_id_for_user — jamais depuis le body client, pour éviter
    les data leaks cross-account (issue #187 review findings F1+F7).
    """
    payload = request.get_json(silent=True) or {}

    # Sécurité (F1+F7) : résolution de l'account_id depuis la session auth,
    # jamais depuis le body client (qui pourrait cibler un autre utilisateur).
    from app.api.routes_helpers import _resolve_account_id_for_user

    account_id = _resolve_account_id_for_user()
    if account_id < 0:
        return jsonify({"error": "no account associated with this session"}), 403

    # F3 : cap explicite sur `limit` — évite DoS + rejette type invalide proprement.
    raw_limit = payload.get("limit", DEFAULT_OUTBOX_LIMIT)
    try:
        limit = max(1, min(int(raw_limit), DEFAULT_OUTBOX_LIMIT))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be a positive integer"}), 400

    # P1.6 — async path: drop the heavy compute off the request thread.
    # Returns 202 immediately; the result lands via WebSocket on completion.
    if bool(payload.get("async", False)):
        task_id = str(uuid4())
        worker = threading.Thread(
            target=_run_reanalyze_async,
            args=(account_id, limit, task_id),
            daemon=True,
            name=f"style-reanalyze-{account_id}",
        )
        worker.start()
        return jsonify({
            "status": "started",
            "task_id": task_id,
            "account_id": account_id,
        }), 202

    # F2 : messages d'erreur génériques — le détail de l'exception reste
    # dans les logs, jamais exposé au client.
    try:
        sent_emails = _get_sent_emails(account_id, limit)
    except Exception:
        logger.exception("Failed to fetch sent emails for account %s", account_id)
        return jsonify({"error": "failed to fetch outbox"}), 500

    email_count = len(sent_emails)
    if email_count < MIN_EMAILS_REQUIRED:
        return (
            jsonify(
                {
                    "error": (
                        f"not enough sent emails to infer style "
                        f"(found {email_count}, need at least {MIN_EMAILS_REQUIRED})"
                    )
                }
            ),
            400,
        )

    service = StyleInferenceService()

    try:
        metrics = service.analyze_outbox(sent_emails)
        examples = service.select_reference_examples(sent_emails)
    except Exception:
        logger.exception("Style inference failed for account %s", account_id)
        return jsonify({"error": "style inference failed"}), 500

    # Garde-fou : aucun exemple non anonymisé ne doit être persisté.
    safe_examples = [ex for ex in examples if ex.anonymized]
    if len(safe_examples) != len(examples):
        logger.error(
            "Blocked %s non-anonymized examples for account %s",
            len(examples) - len(safe_examples),
            account_id,
        )
        return jsonify({"error": "anonymization failed for some examples"}), 500

    # Construit le profil enrichi. Garde les champs existants si un profil
    # précédent existe (merge avec les nouveaux champs issue #187).
    profile = _build_profile(account_id, email_count, metrics, safe_examples)

    try:
        _persist_profile(account_id, profile)
    except Exception:
        logger.exception("Failed to persist profile for account %s", account_id)
        return jsonify({"error": "failed to persist profile"}), 500

    return jsonify(
        {
            "status": "completed",
            "account_id": account_id,
            "email_count": email_count,
            "metrics": metrics,
            "examples_count": len(safe_examples),
        }
    ), 200


# ---------------------------------------------------------------------------
# Helpers (testables via patch)
# ---------------------------------------------------------------------------


def _get_sent_emails(account_id: int, limit: int) -> Sequence[Any]:
    """Charge les emails envoyés depuis la DB. Surface de patch pour les tests."""
    from app.db.database import get_db_session
    from app.db.repositories.email_repository import EmailRepository

    with get_db_session() as session:
        repo = EmailRepository(session)
        return list(repo.get_sent_emails(account_id=account_id, limit=limit))


def _persist_profile(account_id: int, profile: WritingStyleProfile) -> None:
    """Persiste le profil enrichi via le container DI. Surface de patch pour tests."""
    from app.infrastructure.container import get_container

    store = get_container().get_writing_style_store()
    store.save(profile)


def _build_profile(
    account_id: int,
    email_count: int,
    metrics: Dict[str, float],
    examples: List[Any],
) -> WritingStyleProfile:
    """
    Construit un NOUVEAU profil enrichi (immutabilité — pas de mutation en place).

    Si un profil précédent existe, ses champs legacy (formality_level, humor_level,
    etc.) sont conservés via merge du dict — migration silencieuse. En cas de
    panne de persistance en aval, l'objet en mémoire de l'appelant reste intact.
    """
    try:
        from app.infrastructure.container import get_container

        store = get_container().get_writing_style_store()
        existing = store.load(account_id)
    except Exception:
        existing = None

    base = existing.to_dict() if existing is not None else (
        WritingStyleProfile.create_empty(account_id).to_dict()
    )

    _fscore = max(0.0, min(1.0, metrics.get("formality_score", 0.5)))
    # Keep the legacy `formality_level` enum (the value GET /api/writing-style
    # shows, and the one greeting/closing formality defaults read) consistent
    # with the freshly measured continuous score, instead of preserving the
    # stale enum merged in from `base`. Thresholds mirror the widget's
    # describeFormality mapping (>=0.75 formal, <=0.30 casual, else mixed).
    if _fscore >= 0.75:
        _flevel = "formal"
    elif _fscore <= 0.30:
        _flevel = "casual"
    else:
        _flevel = "mixed"

    merged = {
        **base,
        "account_id": account_id,
        "email_count": email_count,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "avg_sentence_length": metrics.get("avg_sentence_length", 0.0),
        "sentence_length_variance": metrics.get("sentence_length_variance", 0.0),
        "vocabulary_density": metrics.get("vocabulary_density", 0.0),
        "formality_score": _fscore,
        "formality_level": _flevel,
        "emoji_frequency": metrics.get("emoji_rate", 0.0),
        "exclamation_rate": metrics.get("exclamation_rate", 0.0),
        # PR4 follow-up — `bullet_list_ratio` removed from the entity. The
        # underlying `bullet_usage_rate` metric still exists in
        # StyleInferenceService output but is no longer persisted.
        "avg_paragraph_count": metrics.get("avg_paragraph_count", 0.0),
        "reference_examples": [
            ex.to_dict() if hasattr(ex, "to_dict") else ex for ex in examples
        ],
    }
    return WritingStyleProfile.from_dict(merged)
