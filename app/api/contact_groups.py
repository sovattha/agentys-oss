# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour la gestion des groupes de contacts.

Endpoints:
- GET /api/contact-groups - Liste tous les groupes
- GET /api/contact-groups/<id> - Récupère un groupe
- POST /api/contact-groups - Crée un nouveau groupe
- PUT /api/contact-groups/<id> - Met à jour un groupe
- DELETE /api/contact-groups/<id> - Supprime un groupe
- POST /api/contact-groups/<id>/use - Enregistre l'utilisation d'un groupe

Persistance : table ``contact_groups`` (SQLAlchemy) — source de vérité unique
depuis la migration 039 (chantier « web tier stateless », audit scalabilité
2026-05-29 rank-6). L'ancien store ``data/contact_groups.json`` est importé
UNE fois, paresseusement, au premier accès (``_ensure_legacy_import``), puis
renommé ``contact_groups.json.imported`` (backup conservé, ré-import court-
circuité). Le contrat de réponse JSON est inchangé.
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from app.api.routes_helpers import _resolve_account_id_for_user
from app.db.models.contact_group import ContactGroupRow
from app.db.repositories.contact_group_repository import ContactGroupRepository

logger = logging.getLogger(__name__)

contact_groups_bp = Blueprint("contact_groups", __name__, url_prefix="/api/contact-groups")

# Legacy storage path — lu UNIQUEMENT par l'import one-shot ci-dessous.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
GROUPS_FILE = os.path.join(DATA_DIR, "contact_groups.json")

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def _ensure_legacy_import() -> None:
    """Importe le JSON legacy dans la table ``contact_groups`` (one-shot).

    Idempotent par PK (un groupe déjà importé est sauté), thread-safe, et
    sans perte : le fichier n'est renommé ``.imported`` qu'après commit. Un
    JSON corrompu est loggé et laissé en place (l'import re-tentera au
    prochain process) — il ne bloque pas l'API, la table reste la vérité.
    """
    global _legacy_import_done
    if _legacy_import_done:
        return
    with _legacy_import_lock:
        if _legacy_import_done:
            return
        if not os.path.exists(GROUPS_FILE):
            _legacy_import_done = True
            return
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                legacy = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(
                "contact-groups: JSON legacy illisible, import différé: %s", e
            )
            _legacy_import_done = True
            return
        if not isinstance(legacy, list):
            legacy = []

        imported = 0
        skipped = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                repo = ContactGroupRepository(session)
                for grp in legacy:
                    if not isinstance(grp, dict):
                        continue
                    gid = str(grp.get("id") or "") or f"grp_{uuid.uuid4().hex[:12]}"
                    if repo.get(gid) is not None:
                        skipped += 1
                        continue
                    repo.add(ContactGroupRepository.row_from_legacy_dict(grp, gid))
                    imported += 1
                session.commit()
        except Exception as e:
            # DB indisponible : ne PAS marquer fait ni toucher le fichier —
            # l'import sera retenté au prochain appel.
            logger.error("contact-groups: import legacy échoué: %s", e)
            return

        try:
            os.replace(GROUPS_FILE, GROUPS_FILE + ".imported")
        except OSError as e:
            logger.warning(
                "contact-groups: impossible de renommer le JSON importé: %s", e
            )
        _legacy_import_done = True
        if imported or skipped:
            logger.info(
                "contact-groups: import legacy terminé (%d importés, %d déjà présents)",
                imported, skipped,
            )


def _get_group_by_id(group_id: str) -> Optional[Dict[str, Any]]:
    """Get a contact group by ID (dict au format legacy).

    Conservé tel quel pour les consommateurs hors blueprint (quicksteps
    ``forward._expand_contact_groups``) — l'appelant vérifie ``account_id``.
    """
    _ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = ContactGroupRepository(session).get(group_id)
        return row.to_dict() if row else None


def _validated_members(members: Any) -> List[Dict[str, str]]:
    """Filtre les membres au même contrat que le store historique."""
    valid_members: List[Dict[str, str]] = []
    if not isinstance(members, list):
        return valid_members
    for m in members:
        if not isinstance(m, dict):
            continue
        email = (m.get("email") or "").strip()
        if not email or "@" not in email:
            continue
        valid_members.append({
            "name": (m.get("name") or "").strip(),
            "email": email,
        })
    return valid_members


def _require_scoped_account_id():
    """Resolve the caller's JWT account_id for contact-group scoping.

    Returns ``(account_id, None)`` when a real tenant is resolved
    (``account_id > 0``), or ``(None, (response, status))`` to short-circuit
    the handler.

    Pre-OAuth web users resolve to the ``-1`` sentinel (routes_helpers
    ``_NO_ACCOUNT_SENTINEL``). Les groupes legacy pré-isolation sont tagués
    ``account_id = -1`` ; laisser un appelant ``-1`` matcher ces lignes
    mettrait en commun les groupes de tous les tenants pré-OAuth (fuite PII
    cross-tenant, audit 2026-05-29). Reject non-positive callers unless the
    request is loopback (Tauri desktop, trusted single-user). Mirrors the
    guard in ``routes_contacts._block_cross_account_or_none`` (Audit F-02/F-05).
    """
    try:
        account_id = _resolve_account_id_for_user()
    except Exception:
        account_id = -1
    if isinstance(account_id, int) and account_id > 0:
        return account_id, None
    try:
        from app.api.auth import is_trusted_loopback
        if is_trusted_loopback():
            return account_id, None
    except Exception:
        pass
    logger.warning(
        "contact-groups: blocked non-positive account scope "
        "(account_id=%s, remote=%s)",
        account_id, getattr(request, "remote_addr", None),
    )
    return None, (jsonify({"error": "Authentication required"}), 401)


@contact_groups_bp.route("", methods=["GET"])
def list_groups():
    """
    Liste tous les groupes de contacts du compte actif.

    Returns:
        200: {groups: [...], total: N}
    """
    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = ContactGroupRepository(session).list_for_account(account_id)
        groups = [row.to_dict() for row in rows]

    return jsonify({
        "groups": groups,
        "total": len(groups)
    })


@contact_groups_bp.route("/<group_id>", methods=["GET"])
def get_group(group_id: str):
    """
    Récupère un groupe de contacts par son ID.

    Args:
        group_id: ID du groupe

    Returns:
        200: {group: {...}}
        404: Groupe non trouvé
    """
    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        row = ContactGroupRepository(session).get_for_account(group_id, account_id)
        if row is None:
            return jsonify({"error": "Contact group not found"}), 404
        return jsonify({"group": row.to_dict()})


@contact_groups_bp.route("", methods=["POST"])
def create_group():
    """
    Crée un nouveau groupe de contacts.

    Body JSON:
        - name: string (requis)
        - emoji: string (optionnel, ex: "👥")
        - members: [{name, email}] (requis, au moins 1)
        - description: string (optionnel)

    Returns:
        201: {group: {...}, message: "..."}
        400: Erreur de validation
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    # Les champs optionnels peuvent arriver en JSON null (le front envoie
    # label_name: null quand aucun projet n'est sélectionné). `data.get(k, "")`
    # ne convertit PAS None en "", donc `.strip()` crash en AttributeError.
    # `(data.get(k) or "").strip()` neutralise None, string vide et absence.
    name = (data.get("name") or "").strip()
    members = data.get("members", [])

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not members or not isinstance(members, list):
        return jsonify({"error": "At least one member is required"}), 400

    valid_members = _validated_members(members)
    if not valid_members:
        return jsonify({"error": "At least one valid email is required"}), 400

    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    now = datetime.now()
    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = ContactGroupRepository(session)
        if repo.name_exists(account_id, name):
            return jsonify({"error": "A group with this name already exists"}), 400

        row = ContactGroupRow(
            id=f"grp_{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            name=name,
            emoji=(data.get("emoji") or "").strip() or None,
            description=(data.get("description") or "").strip() or None,
            label_name=(data.get("label_name") or "").strip() or None,
            members_json=json.dumps(valid_members, ensure_ascii=False),
            virtual_meeting=bool(data.get("virtual_meeting", False)),
            use_count=0,
            created_at=now,
            updated_at=now,
        )
        repo.add(row)
        session.commit()
        group = row.to_dict()

    logger.info(f"Created contact group: {group['id']} - {group['name']} ({len(valid_members)} members)")

    return jsonify({
        "group": group,
        "message": "Contact group created successfully"
    }), 201


@contact_groups_bp.route("/<group_id>", methods=["PUT"])
def update_group(group_id: str):
    """
    Met à jour un groupe de contacts existant.

    Args:
        group_id: ID du groupe

    Body JSON (tous optionnels):
        - name: string
        - emoji: string
        - members: [{name, email}]
        - description: string

    Returns:
        200: {group: {...}, message: "..."}
        404: Groupe non trouvé
    """
    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = ContactGroupRepository(session)
        row = repo.get_for_account(group_id, account_id)
        if row is None:
            return jsonify({"error": "Contact group not found"}), 404

        # Idem create_group : tous les champs optionnels peuvent arriver en
        # JSON null. `(value or "").strip()` normalise None/""/absence → "".
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                return jsonify({"error": "Name cannot be empty"}), 400
            if repo.name_exists(account_id, name, exclude_id=group_id):
                return jsonify({"error": "A group with this name already exists"}), 400
            row.name = name

        if "emoji" in data:
            row.emoji = (data["emoji"] or "").strip() or None

        if "description" in data:
            row.description = (data["description"] or "").strip() or None

        if "label_name" in data:
            row.label_name = (data["label_name"] or "").strip() or None

        if "virtual_meeting" in data:
            row.virtual_meeting = bool(data["virtual_meeting"])

        if "members" in data:
            members = data["members"]
            if not isinstance(members, list) or len(members) == 0:
                return jsonify({"error": "At least one member is required"}), 400
            valid_members = _validated_members(members)
            if not valid_members:
                return jsonify({"error": "At least one valid email is required"}), 400
            row.members_json = json.dumps(valid_members, ensure_ascii=False)

        row.updated_at = datetime.now()
        session.commit()
        group = row.to_dict()

    logger.info(f"Updated contact group: {group_id}")

    return jsonify({
        "group": group,
        "message": "Contact group updated successfully"
    })


@contact_groups_bp.route("/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    """
    Supprime un groupe de contacts.

    Args:
        group_id: ID du groupe

    Returns:
        200: {message: "..."}
        404: Groupe non trouvé
    """
    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = ContactGroupRepository(session)
        row = repo.get_for_account(group_id, account_id)
        if row is None:
            return jsonify({"error": "Contact group not found"}), 404
        repo.delete(row)
        session.commit()

    logger.info(f"Deleted contact group: {group_id}")

    return jsonify({"message": "Contact group deleted successfully"})


@contact_groups_bp.route("/<group_id>/use", methods=["POST"])
def record_usage(group_id: str):
    """
    Enregistre l'utilisation d'un groupe (incrémente use_count).

    Args:
        group_id: ID du groupe

    Returns:
        200: {group: {...}}
        404: Groupe non trouvé
    """
    account_id, _scope_err = _require_scoped_account_id()
    if _scope_err is not None:
        return _scope_err
    _ensure_legacy_import()

    from app.db.database import get_db_session
    with get_db_session() as session:
        repo = ContactGroupRepository(session)
        row = repo.get_for_account(group_id, account_id)
        if row is None:
            return jsonify({"error": "Contact group not found"}), 404
        row.use_count = (row.use_count or 0) + 1
        session.commit()
        return jsonify({"group": row.to_dict()})
