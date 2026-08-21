# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour la gestion des snippets (templates de texte).

Endpoints:
- GET /api/snippets - Liste les snippets de l'utilisateur
- GET /api/snippets/shared-with-me - Liste les snippets partagés avec moi
- GET /api/snippets/<id> - Récupère un snippet
- POST /api/snippets - Crée un nouveau snippet
- PUT /api/snippets/<id> - Met à jour un snippet
- DELETE /api/snippets/<id> - Supprime un snippet
- POST /api/snippets/<id>/use - Enregistre l'utilisation d'un snippet
- POST /api/snippets/<id>/share - Partage un snippet avec un utilisateur
- DELETE /api/snippets/<id>/share - Révoque un partage
- GET /api/snippets/<id>/shares - Liste les partages d'un snippet
- POST /api/snippets/<id>/duplicate - Duplique un snippet partagé

Persistance : tables ``snippets`` + ``snippet_shares`` (SQLAlchemy) — source
de vérité unique depuis la migration 040 (chantier « web tier stateless »,
même recette que contact_groups/039). Les anciens stores
``data/snippets.json`` et ``data/snippet_shares.json`` sont importés UNE
fois, paresseusement, au premier accès (``_ensure_legacy_import``), puis
parqués en ``.imported``. Le contrat de réponse JSON est inchangé — épinglé
par ``tests/api/test_snippets_contract.py`` (suite de caractérisation écrite
sur l'ancien backend, qui doit passer telle quelle sur celui-ci).
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, g

from app.db.models.snippet import SnippetRow, SnippetShareRow
from app.db.repositories.snippet_repository import SnippetRepository

from .auth import require_auth, is_known_user
from .utils.errors import error_response

logger = logging.getLogger(__name__)

snippets_bp = Blueprint("snippets", __name__, url_prefix="/api/snippets")

# Legacy storage paths — lus UNIQUEMENT par l'import one-shot ci-dessous.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
SNIPPETS_FILE = os.path.join(DATA_DIR, "snippets.json")
SHARES_FILE = os.path.join(DATA_DIR, "snippet_shares.json")

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def _norm(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def _enc_json(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _import_one_file(path: str, importer) -> bool:
    """Importe un fichier legacy via ``importer(payload)`` puis le parque.

    Retourne False si l'import doit être retenté (DB indisponible) — un JSON
    corrompu est loggé et laissé en place mais ne bloque pas l'API.
    """
    if not os.path.exists(path):
        return True
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("snippets: JSON legacy illisible (%s), import différé: %s", path, e)
        return True
    if not isinstance(payload, list):
        payload = []
    try:
        importer(payload)
    except Exception as e:
        logger.error("snippets: import legacy échoué (%s): %s", path, e)
        return False
    try:
        os.replace(path, path + ".imported")
    except OSError as e:
        logger.warning("snippets: impossible de parquer %s: %s", path, e)
    return True


def _ensure_legacy_import() -> None:
    """Import one-shot de snippets.json + snippet_shares.json vers la DB.

    Idempotent par PK, thread-safe ; chaque fichier est parqué en
    ``.imported`` après commit. Même contrat de robustesse que l'import
    contact_groups (migration 039).
    """
    global _legacy_import_done
    if _legacy_import_done:
        return
    with _legacy_import_lock:
        if _legacy_import_done:
            return

        from app.db.database import get_db_session

        def _import_snippets(payload):
            with get_db_session() as session:
                repo = SnippetRepository(session)
                imported = 0
                for s in payload:
                    if not isinstance(s, dict):
                        continue
                    sid = str(s.get("id") or "") or f"snippet_{uuid.uuid4().hex[:12]}"
                    if repo.get(sid) is not None:
                        continue
                    repo.add(SnippetRepository.snippet_from_legacy_dict(s, sid))
                    imported += 1
                session.commit()
                if imported:
                    logger.info("snippets: %d snippets legacy importés", imported)

        def _import_shares(payload):
            with get_db_session() as session:
                repo = SnippetRepository(session)
                imported = 0
                for sh in payload:
                    if not isinstance(sh, dict):
                        continue
                    share_id = str(sh.get("id") or "") or f"share_{uuid.uuid4().hex[:12]}"
                    if session.get(SnippetShareRow, share_id) is not None:
                        continue
                    repo.add_share(SnippetRepository.share_from_legacy_dict(sh, share_id))
                    imported += 1
                session.commit()
                if imported:
                    logger.info("snippets: %d partages legacy importés", imported)

        ok_snippets = _import_one_file(SNIPPETS_FILE, _import_snippets)
        ok_shares = _import_one_file(SHARES_FILE, _import_shares)
        if ok_snippets and ok_shares:
            _legacy_import_done = True


def _get_snippet_by_id(snippet_id: str) -> Optional[Dict[str, Any]]:
    """Get a snippet by ID (dict au format legacy) — consommateurs externes."""
    _ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = SnippetRepository(session).get(snippet_id)
        return row.to_dict() if row else None


# ---------------------------------------------------------------------------
# Route: /shared-with-me MUST be defined BEFORE /<snippet_id> routes
# ---------------------------------------------------------------------------

@snippets_bp.route("/shared-with-me", methods=["GET"])
@require_auth
def list_shared_with_me():
    """
    Liste les snippets partagés avec l'utilisateur courant.

    Returns:
        200: {snippets: [...], total: N}
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        result = []
        for share in repo.list_shares_for_user(email):
            row = repo.get(share.snippet_id)
            if row is None:
                continue
            result.append({
                **row.to_dict(),
                "share_id": share.id,
                "shared_by": share.shared_by,
                "shared_at": share.shared_at,
            })

    result.sort(key=lambda s: s.get("shared_at", ""), reverse=True)

    return jsonify({"snippets": result, "total": len(result)})


# ---------------------------------------------------------------------------
# Existing CRUD routes — now with @require_auth + ownership
# ---------------------------------------------------------------------------

@snippets_bp.route("", methods=["GET"])
@require_auth
def list_snippets():
    """
    Liste les snippets de l'utilisateur courant (propres + legacy sans owner).

    Returns:
        200: {snippets: [...], total: N}
    """
    email = _norm(g.auth_user["email"])
    account_id_param = request.args.get("account_id", type=int)
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = SnippetRepository(session).list_visible(email, account_id_param)
        visible = [row.to_dict() for row in rows]

    return jsonify({
        "snippets": visible,
        "total": len(visible)
    })


@snippets_bp.route("/<snippet_id>", methods=["GET"])
@require_auth
def get_snippet(snippet_id: str):
    """
    Récupère un snippet par son ID.
    Accessible si propriétaire, legacy, ou partagé avec l'utilisateur.
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email) and repo.get_share(snippet_id, email) is None:
            return error_response("ACCESS_DENIED", "Access denied", 403)
        return jsonify({"snippet": row.to_dict()})


@snippets_bp.route("", methods=["POST"])
@require_auth
def create_snippet():
    """
    Crée un nouveau snippet avec owner_email.
    """
    email = _norm(g.auth_user["email"])

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    name = data.get("name", "").strip()
    content = data.get("content", "").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not content:
        return jsonify({"error": "Content is required"}), 400

    _ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        if repo.name_exists_for_owner(email, name):
            return jsonify({"error": "A snippet with this name already exists"}), 400

        now = _now_iso()
        row = SnippetRow(
            id=f"snippet_{uuid.uuid4().hex[:12]}",
            name=name,
            content=content,
            subject=data.get("subject", "").strip() or None,
            to_json=_enc_json(data.get("to") or None),
            cc_json=_enc_json(data.get("cc") or None),
            bcc_json=_enc_json(data.get("bcc") or None),
            category=data.get("category", "").strip() or None,
            is_private=bool(data.get("is_private", True)),
            owner_email=email,
            account_id=data.get("account_id") or None,
            created_at=now,
            updated_at=now,
            use_count=0,
        )
        repo.add(row)
        session.commit()
        snippet = row.to_dict()

    logger.info(f"Created snippet: {snippet['id']} - {snippet['name']} by {email}")

    return jsonify({
        "snippet": snippet,
        "message": "Snippet created successfully"
    }), 201


@snippets_bp.route("/<snippet_id>", methods=["PUT"])
@require_auth
def update_snippet(snippet_id: str):
    """
    Met à jour un snippet existant (propriétaire uniquement).
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email):
            return error_response("ACCESS_DENIED", "Access denied", 403)

        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        if "name" in data:
            name = data["name"].strip()
            if not name:
                return jsonify({"error": "Name cannot be empty"}), 400
            if repo.name_exists_for_owner(email, name, exclude_id=snippet_id):
                return jsonify({"error": "A snippet with this name already exists"}), 400
            row.name = name

        if "content" in data:
            content = data["content"].strip()
            if not content:
                return jsonify({"error": "Content cannot be empty"}), 400
            row.content = content

        if "subject" in data:
            row.subject = data["subject"].strip() or None

        if "to" in data:
            row.to_json = _enc_json(data["to"] or None)

        if "cc" in data:
            row.cc_json = _enc_json(data["cc"] or None)

        if "bcc" in data:
            row.bcc_json = _enc_json(data["bcc"] or None)

        if "category" in data:
            row.category = data["category"].strip() or None

        if "is_private" in data:
            row.is_private = bool(data["is_private"])

        row.updated_at = _now_iso()
        session.commit()
        snippet = row.to_dict()

    logger.info(f"Updated snippet: {snippet_id}")

    return jsonify({
        "snippet": snippet,
        "message": "Snippet updated successfully"
    })


@snippets_bp.route("/<snippet_id>", methods=["DELETE"])
@require_auth
def delete_snippet(snippet_id: str):
    """
    Supprime un snippet (propriétaire uniquement). Cascade les partages.
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email):
            return error_response("ACCESS_DENIED", "Access denied", 403)

        repo.delete_shares_for_snippet(snippet_id)
        repo.delete(row)
        session.commit()

    logger.info(f"Deleted snippet: {snippet_id} (+ cascade shares)")

    return jsonify({"message": "Snippet deleted successfully"})


@snippets_bp.route("/<snippet_id>/use", methods=["POST"])
@require_auth
def record_usage(snippet_id: str):
    """
    Enregistre l'utilisation d'un snippet (incrémente use_count).
    """
    _ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        row.use_count = (row.use_count or 0) + 1
        session.commit()
        return jsonify({"snippet": row.to_dict()})


# ---------------------------------------------------------------------------
# Sharing endpoints
# ---------------------------------------------------------------------------

@snippets_bp.route("/<snippet_id>/share", methods=["POST"])
@require_auth
def share_snippet(snippet_id: str):
    """
    Partage un snippet avec un autre utilisateur Agentys.

    Body JSON:
        - email: string (requis)

    Returns:
        201: {share: {...}, message: "..."}
        400: Email invalide
        403: Pas propriétaire
        404: Snippet ou utilisateur non trouvé
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email):
            return error_response("ACCESS_DENIED", "Access denied", 403)

        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        target_email = _norm(data.get("email", ""))
        if not target_email or "@" not in target_email:
            return jsonify({"error": "Email invalide"}), 400

        if target_email == email:
            return error_response("SNIPPET_CANNOT_SHARE_WITH_SELF", "You can't share a snippet with yourself", 400)

        if not is_known_user(target_email):
            return error_response("SNIPPET_EMAIL_NOT_USER", "This email doesn't match an Agentys user", 404)

        if repo.get_share(snippet_id, target_email) is not None:
            return error_response("SNIPPET_ALREADY_SHARED", "This snippet is already shared with this user", 400)

        share_row = SnippetShareRow(
            id=f"share_{uuid.uuid4().hex[:12]}",
            snippet_id=snippet_id,
            shared_by=email,
            shared_with=target_email,
            shared_at=_now_iso(),
        )
        repo.add_share(share_row)
        session.commit()
        share = share_row.to_dict()

    logger.info(f"Shared snippet {snippet_id} with {target_email}")

    return jsonify({
        "share": share,
        "message": f"Snippet shared with {target_email}"
    }), 201


@snippets_bp.route("/<snippet_id>/share", methods=["DELETE"])
@require_auth
def unshare_snippet(snippet_id: str):
    """
    Révoque le partage d'un snippet avec un utilisateur.

    Query params:
        - email: string (requis)
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email):
            return error_response("ACCESS_DENIED", "Access denied", 403)

        target_email = _norm(request.args.get("email", ""))
        if not target_email:
            return error_response("EMAIL_PARAM_REQUIRED", "Email parameter required", 400)

        share = repo.get_share(snippet_id, target_email)
        if share is None:
            return error_response("SNIPPET_SHARE_NOT_FOUND", "Share not found", 404)
        repo.delete_share(share)
        session.commit()

    logger.info(f"Unshared snippet {snippet_id} from {target_email}")

    # The message is mostly diagnostic — the FE drives the user-facing
    # "share revoked" toast from the 200 status, not from this field.
    return jsonify({"message": f"Share revoked for {target_email}"})


@snippets_bp.route("/<snippet_id>/shares", methods=["GET"])
@require_auth
def list_snippet_shares(snippet_id: str):
    """
    Liste les personnes avec qui un snippet est partagé (propriétaire uniquement).
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        row = repo.get(snippet_id)
        if row is None:
            return jsonify({"error": "Snippet not found"}), 404
        if not repo.is_owner(row, email):
            return error_response("ACCESS_DENIED", "Access denied", 403)

        snippet_shares = [
            {"email": s.shared_with, "shared_at": s.shared_at, "share_id": s.id}
            for s in repo.list_shares_for_snippet(snippet_id)
        ]

    return jsonify({"shares": snippet_shares, "total": len(snippet_shares)})


@snippets_bp.route("/<snippet_id>/duplicate", methods=["POST"])
@require_auth
def duplicate_snippet(snippet_id: str):
    """
    Duplique un snippet partagé dans la bibliothèque de l'utilisateur.
    """
    email = _norm(g.auth_user["email"])
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = SnippetRepository(session)
        source = repo.get(snippet_id)
        if source is None:
            return jsonify({"error": "Snippet not found"}), 404

        # Must be shared with user (or owner)
        if not repo.is_owner(source, email) and repo.get_share(snippet_id, email) is None:
            return error_response("ACCESS_DENIED", "Access denied", 403)

        # Generate unique name (contrat historique : « (copie) », « (copie 2) »…)
        base_name = f"{source.name} (copie)"
        name = base_name
        counter = 2
        while repo.name_exists_for_owner(email, name):
            name = f"{source.name} (copie {counter})"
            counter += 1

        now = _now_iso()
        data = request.get_json() or {}
        new_row = SnippetRow(
            id=f"snippet_{uuid.uuid4().hex[:12]}",
            name=name,
            content=source.content,
            subject=source.subject,
            to_json=source.to_json,
            cc_json=source.cc_json,
            bcc_json=source.bcc_json,
            category=source.category,
            is_private=True,
            owner_email=email,
            account_id=data.get("account_id") or None,
            created_at=now,
            updated_at=now,
            use_count=0,
        )
        repo.add(new_row)
        session.commit()
        new_snippet = new_row.to_dict()

    logger.info(f"Duplicated snippet {snippet_id} -> {new_snippet['id']} for {email}")

    return jsonify({
        "snippet": new_snippet,
        "message": "Snippet duplicated successfully"
    }), 201
