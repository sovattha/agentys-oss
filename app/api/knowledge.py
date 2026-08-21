# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API pour les entrées de la base de connaissances (Knowledge Entries).

Endpoints:
- GET    /api/knowledge/entries              — Lister les entrées (filtre par catégorie)
- POST   /api/knowledge/entries              — Créer une entrée
- PATCH  /api/knowledge/entries/<id>         — Modifier une entrée
- DELETE /api/knowledge/entries/<id>         — Supprimer une entrée
- POST   /api/knowledge/entries/import       — Import bulk depuis onboarding_results
"""

import json
import logging
import uuid

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

knowledge_bp = Blueprint("knowledge", __name__)


def _resolve_account_id() -> str | None:
    """Resolve the active account ID from the authenticated user (never from query params)."""
    from flask import has_request_context
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        aid = _resolve_account_id_for_user()
        return aid if aid and aid > 0 else None
    except Exception:
        # In-request callers must NOT fall back to the first active tenant
        # (accounts[0]) — that singleton fallback would expose another user's
        # knowledge base in a multi-tenant request. Mirrors routes_helpers
        # `_get_current_account_for_user` (ISO C-2, #522): refuse the singleton
        # in request context so a forgotten guard can't leak cross-tenant data.
        if has_request_context():
            return None
    # Fallback for non-request contexts (e.g. background tasks / CLI) only.
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            accounts = AccountRepository(session).get_active_accounts()
            return accounts[0].id if accounts else None
    except Exception:
        return None


def _invalidate_faq_cache_if_relevant(category: str | None) -> None:
    """Invalidate the smart_routing FAQ cache when a FAQ entry is modified.

    Only fires for FAQ category since other categories are not used as
    drafter grounding via the FAQ pipeline.
    """
    if (category or "").upper() != "FAQ":
        return
    try:
        from app.smart_routing import invalidate_faq_cache
        invalidate_faq_cache()
    except Exception as exc:
        logger.debug("FAQ cache invalidation failed: %s", exc)


@knowledge_bp.route("/entries", methods=["GET"])
def list_entries():
    """
    Liste les entrées de la base de connaissances.
    ---
    tags:
      - Knowledge
    parameters:
      - name: category
        in: query
        type: string
        required: false
        description: Filtre par catégorie (FAQ, TECHNIQUE, CONTACT, etc.)
    responses:
      200:
        description: Liste des entrées
    """
    category = request.args.get("category")
    # NEVER trust account_id from query params — resolve from authenticated user
    account_id = _resolve_account_id()

    if not account_id:
        return jsonify([]), 200

    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository

        with get_db_session() as session:
            repo = KnowledgeRepository(session)
            entries = repo.get_by_account(account_id, category=category)
            return jsonify([e.to_dict() for e in entries]), 200
    except Exception as exc:
        logger.error("[Knowledge] List error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@knowledge_bp.route("/entries", methods=["POST"])
def create_entry():
    """
    Crée une nouvelle entrée de savoir.
    ---
    tags:
      - Knowledge
    responses:
      201:
        description: Entrée créée
    """
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    category = data.get("category", "GENERAL").upper()
    source = data.get("source", "manual")
    # NEVER trust account_id from request body — resolve from authenticated user
    account_id = _resolve_account_id()

    if not title or not content:
        return jsonify({"error": "title and content are required"}), 400

    if not account_id:
        return jsonify({"error": "no active account"}), 400

    valid_categories = {"FAQ", "TECHNIQUE", "CONTACT", "PROJET", "REGLE", "GENERAL"}
    if category not in valid_categories:
        category = "GENERAL"

    try:
        from app.db.database import get_db_session
        from app.db.models.knowledge_entry import KnowledgeEntry

        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            account_id=account_id,
            title=title,
            content=content,
            category=category,
            source=source,
        )

        with get_db_session() as session:
            session.add(entry)
            session.flush()
            result = entry.to_dict()

        _invalidate_faq_cache_if_relevant(category)
        logger.info("[Knowledge] Created entry: %s (%s)", title[:40], category)
        return jsonify(result), 201
    except Exception as exc:
        logger.error("[Knowledge] Create error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@knowledge_bp.route("/entries/<entry_id>", methods=["PATCH"])
def update_entry(entry_id: str):
    """
    Modifie une entrée existante.
    ---
    tags:
      - Knowledge
    responses:
      200:
        description: Entrée mise à jour
    """
    data = request.get_json(silent=True) or {}

    account_id = _resolve_account_id()
    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository

        with get_db_session() as session:
            repo = KnowledgeRepository(session)
            entry = repo.get(entry_id)
            if not entry:
                return jsonify({"error": "Entry not found"}), 404

            # Ownership check — prevent cross-account modification.
            # Audit 2026-04-25 CRIT-Iso-4: legacy entries with account_id=None
            # were silently editable by anyone — reject them in strict mode.
            _entry_aid = getattr(entry, "account_id", None)
            if account_id:
                if _entry_aid is None or str(_entry_aid).strip() == "" or str(_entry_aid) != str(account_id):
                    return jsonify({"error": "Forbidden"}), 403

            old_category = entry.category
            if "title" in data:
                entry.title = data["title"].strip()
            if "content" in data:
                entry.content = data["content"].strip()
            if "category" in data:
                entry.category = data["category"].upper()

            session.flush()
            result = entry.to_dict()
            new_category = entry.category

        # Invalidate if the entry was, is, or became a FAQ
        _invalidate_faq_cache_if_relevant(old_category)
        _invalidate_faq_cache_if_relevant(new_category)
        logger.info("[Knowledge] Updated entry: %s", entry_id)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("[Knowledge] Update error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@knowledge_bp.route("/entries/<entry_id>", methods=["DELETE"])
def delete_entry(entry_id: str):
    """
    Supprime une entrée.
    ---
    tags:
      - Knowledge
    responses:
      200:
        description: Entrée supprimée
    """
    account_id = _resolve_account_id()
    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository

        with get_db_session() as session:
            repo = KnowledgeRepository(session)
            entry = repo.get(entry_id)
            if not entry:
                return jsonify({"error": "Entry not found"}), 404

            # Ownership check — prevent cross-account deletion.
            # Audit 2026-04-25 CRIT-Iso-4: strict comparison rejects None/empty.
            _entry_aid = getattr(entry, "account_id", None)
            if account_id:
                if _entry_aid is None or str(_entry_aid).strip() == "" or str(_entry_aid) != str(account_id):
                    return jsonify({"error": "Forbidden"}), 403

            deleted_category = entry.category
            session.delete(entry)

        _invalidate_faq_cache_if_relevant(deleted_category)
        logger.info("[Knowledge] Deleted entry: %s", entry_id)
        return jsonify({"ok": True}), 200
    except Exception as exc:
        logger.error("[Knowledge] Delete error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@knowledge_bp.route("/entries/import", methods=["POST"])
def import_entries():
    """
    Import bulk depuis les onboarding_results existants.
    Parse knowledge_json et crée des KnowledgeEntry individuelles.
    ---
    tags:
      - Knowledge
    responses:
      200:
        description: Import terminé
    """
    # NEVER trust account_id from query params — resolve from authenticated user
    account_id = _resolve_account_id()
    if not account_id:
        return jsonify({"error": "no active account"}), 400

    try:
        from app.db.database import get_db_session
        from app.db.models.knowledge_entry import KnowledgeEntry
        from app.db.repositories.onboarding_repository import OnboardingRepository

        created = 0
        with get_db_session() as session:
            onb_repo = OnboardingRepository(session)
            onb = onb_repo.get_by_account(account_id)
            if not onb or not onb.knowledge_json:
                return jsonify({"ok": True, "created": 0, "message": "No onboarding data found"}), 200

            knowledge = json.loads(onb.knowledge_json) if isinstance(onb.knowledge_json, str) else onb.knowledge_json

            # Parse different formats of knowledge_json
            items = []
            if isinstance(knowledge, list):
                items = knowledge
            elif isinstance(knowledge, dict):
                # Could be {"items": [...]} or {"key": "value", ...}
                if "items" in knowledge:
                    items = knowledge["items"]
                else:
                    for key, value in knowledge.items():
                        if isinstance(value, str):
                            items.append({"title": key, "content": value})
                        elif isinstance(value, list):
                            for v in value:
                                if isinstance(v, str):
                                    items.append({"title": key, "content": v})
                                elif isinstance(v, dict):
                                    items.append(v)

            for item in items:
                if isinstance(item, str):
                    # Simple string entry
                    title = item[:80] if len(item) > 80 else item
                    content = item
                elif isinstance(item, dict):
                    title = item.get("title", item.get("question", ""))
                    content = item.get("content", item.get("answer", item.get("value", "")))
                else:
                    continue

                if not title or not content:
                    continue

                entry = KnowledgeEntry(
                    id=str(uuid.uuid4()),
                    account_id=account_id,
                    title=title.strip(),
                    content=content.strip(),
                    category="GENERAL",
                    source="import",
                )
                session.add(entry)
                created += 1

        logger.info("[Knowledge] Imported %d entries from onboarding for account %s", created, account_id)
        return jsonify({"ok": True, "created": created}), 200
    except Exception as exc:
        logger.error("[Knowledge] Import error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@knowledge_bp.route("/scan-url", methods=["POST"])
def scan_url():
    """
    Scanne une URL pour extraire les FAQ (3 niveaux : Schema.org, HTML, LLM).
    Retourne un aperçu — aucune écriture en base.
    ---
    tags:
      - Knowledge
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required:
            - url
          properties:
            url:
              type: string
    responses:
      200:
        description: FAQ extraites (aperçu)
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "URL requise"}), 400

    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        from app.services.faq_scanner import scan_url as do_scan
        result = do_scan(url)
        return jsonify(result.to_dict()), 200
    except Exception as exc:
        logger.error("[Knowledge] scan-url error: %s", exc)
        return jsonify({"error": str(exc), "faq": []}), 500


@knowledge_bp.route("/scan-document", methods=["POST"])
def scan_document():
    """
    Extrait les FAQ d'un document uploadé (PDF, TXT, DOCX).
    Retourne un aperçu — aucune écriture en base.
    ---
    tags:
      - Knowledge
    responses:
      200:
        description: FAQ extraites (aperçu)
    """
    # F-07 (audit issue #209, 2026-04-29): unbounded multipart upload
    # could OOM the worker on Railway's 512MB container. Mirror the
    # tts.py / routes_misc.py:transcribe pattern: content-length check
    # then bounded read. Plus a rate limit on the LLM-fed scanner.
    from app.api.routes_helpers import _rate_limited, _resolve_account_id_cached
    _MAX_SCAN_BYTES = 10 * 1024 * 1024  # 10 MB

    # Per-tenant bucket (H-8 follow-up #534) — bare literal mutualisait le
    # quota cross-tenant.
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(
        f"knowledge_scan_document:{_aid}", max_calls=5, window_seconds=300
    )
    if not allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": retry_after}), 429

    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nom de fichier manquant"}), 400

    content_length = request.content_length
    if content_length is not None and content_length > _MAX_SCAN_BYTES:
        return jsonify({"error": f"fichier trop volumineux (>{_MAX_SCAN_BYTES // (1024 * 1024)} MB)"}), 413

    try:
        file_bytes = file.stream.read(_MAX_SCAN_BYTES + 1)
        if len(file_bytes) > _MAX_SCAN_BYTES:
            return jsonify({"error": f"fichier trop volumineux (>{_MAX_SCAN_BYTES // (1024 * 1024)} MB)"}), 413
        from app.services.faq_scanner import scan_document as do_scan
        result = do_scan(file_bytes, file.filename)
        return jsonify(result.to_dict()), 200
    except Exception as exc:
        logger.error("[Knowledge] scan-document error: %s", exc)
        return jsonify({"error": str(exc), "faq": []}), 500


@knowledge_bp.route("/categories", methods=["GET"])
def get_categories():
    """
    Retourne les compteurs par catégorie.
    """
    # NEVER trust account_id from query params — resolve from authenticated user
    account_id = _resolve_account_id()
    if not account_id:
        return jsonify({}), 200

    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository

        with get_db_session() as session:
            counts = KnowledgeRepository(session).get_category_counts(account_id)
        return jsonify(counts), 200
    except Exception as exc:
        logger.error("[Knowledge] Categories error: %s", exc)
        return jsonify({}), 200
