# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour la bibliothèque de signatures multiples (per-account).

La signature ACTIVE d'un compte reste le couple accounts.signature /
signature_html (JSON config + miroir DB) — c'est lui que lisent
append_signature, useAccountSignature et tous les composeurs. Cette
bibliothèque est une couche additive : « définir par défaut » copie la
signature choisie dans ce couple canonique via le même chemin de
persistance que PATCH /api/accounts/<id>, donc le chemin d'envoi
n'est jamais touché.

Endpoints (préfixe /api/accounts) :
- GET    /<account_id>/signatures                     — liste (+ seed auto depuis la signature compte)
- POST   /<account_id>/signatures                     — crée {name, html[, text]}
- PUT    /<account_id>/signatures/<sig_id>            — met à jour (propage si défaut)
- DELETE /<account_id>/signatures/<sig_id>            — supprime (promotion / clear compte si dernier)
- POST   /<account_id>/signatures/<sig_id>/set-default — défaut exclusif + propagation
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from app.multi_accounts import get_account_manager
from app.api._auth_helpers import get_auth_user_id as _get_auth_user_id
from app.api._auth_helpers import check_account_ownership as _check_account_ownership

logger = logging.getLogger(__name__)

signatures_bp = Blueprint("signatures", __name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
SIGNATURES_FILE = os.path.join(DATA_DIR, "signatures.json")

_signatures_lock = threading.Lock()

# Mêmes plafonds que PATCH /api/accounts (accounts.py)
MAX_NAME_LENGTH = 100
MAX_TEXT_LENGTH = 2000
MAX_HTML_LENGTH = 500_000
# Borne le store (les caps par champ ne bornent pas le cardinal)
MAX_SIGNATURES_PER_ACCOUNT = 20

# Même format d'ID que accounts.py (alphanumerique + _ -, ≤ 50)
_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _html_to_text(html: str) -> str:
    """Version texte d'une signature HTML (même approche que Account.get_signature)."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(div|p|li|tr|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:MAX_TEXT_LENGTH]


def _load_signatures() -> List[Dict[str, Any]]:
    if not os.path.exists(SIGNATURES_FILE):
        return []
    try:
        with open(SIGNATURES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _save_signatures(signatures: List[Dict[str, Any]]) -> None:
    # Écriture atomique (temp + replace) : un crash mid-write laisserait un
    # JSON tronqué que _load_signatures avalerait en [], et le GET suivant
    # re-seederait silencieusement en perdant toutes les signatures custom.
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = f"{SIGNATURES_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(signatures, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, SIGNATURES_FILE)


def _account_entries(signatures: List[Dict[str, Any]], account_id: str) -> List[Dict[str, Any]]:
    return [s for s in signatures if s.get("account_id") == account_id]


def _resolve_account(account_id: str) -> Tuple[Optional[Any], Optional[Tuple[Any, int]]]:
    """Valide l'id, charge le compte et vérifie l'ownership JWT.

    Returns (account, None) en succès, (None, (response, status)) en erreur.
    """
    if not _ACCOUNT_ID_PATTERN.match(account_id or ""):
        return None, (jsonify({"error": "Invalid account ID"}), 400)
    manager = get_account_manager()
    account = manager.get_account(account_id)
    if not account:
        return None, (jsonify({"error": "Account not found"}), 404)
    if not _check_account_ownership(account, _get_auth_user_id()):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return account, None


def _persist_account_signature(account_id: str, text: str, html: str) -> None:
    """Propage la signature par défaut vers le couple canonique du compte.

    Réplique le chemin PATCH /api/accounts/<id> : store JSON (AccountManager)
    puis miroir best-effort vers la DB SQL (lue par append_signature à l'envoi).
    """
    manager = get_account_manager()
    manager.update_account(account_id, signature=text, signature_html=html)
    try:
        from app.db.database import get_db_session
        from app.db.repositories import AccountRepository

        account = manager.get_account(account_id)
        if account:
            with get_db_session() as session:
                repo = AccountRepository(session)
                db_acc = repo.get_by_email(account.email) or repo.get_by_email(account.email.lower())
                if db_acc:
                    db_acc.signature_text = text
                    db_acc.signature_html = html
                    db_acc.signature_user_modified = True
                    session.commit()
                else:
                    logger.warning(
                        "Account %s not found in SQLite — default signature in JSON config only",
                        account.email,
                    )
    except Exception as db_err:  # pragma: no cover - best-effort mirror
        logger.warning("Could not persist default signature to DB for %s: %s", account_id, db_err)


def _set_exclusive_default(entries: List[Dict[str, Any]], sig_id: str) -> None:
    for entry in entries:
        entry["is_default"] = entry["id"] == sig_id


def _serialize(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entry["id"],
        "name": entry.get("name", ""),
        "html": entry.get("html", ""),
        "text": entry.get("text", ""),
        "is_default": bool(entry.get("is_default")),
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
    }


def get_default_signature_for_account(account_id: str) -> Optional[Tuple[str, str]]:
    """Retourne (html, text) de la signature par défaut de la bibliothèque, ou None.

    Utilisé par GET /api/accounts pour préférer signatures.json (toujours
    à jour) sur le JSON config AccountManager (peut être stale après
    re-import OAuth).
    """
    try:
        with _signatures_lock:
            sigs = _load_signatures()
        for s in sigs:
            if s.get("account_id") == account_id and s.get("is_default"):
                return s.get("html") or "", s.get("text") or ""
    except Exception:
        pass
    return None


def _validate_payload(data: Dict[str, Any], require_all: bool) -> Optional[Tuple[Any, int]]:
    if require_all or "name" in data:
        name = data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            return jsonify({"error": "name is required"}), 400
        if len(name) > MAX_NAME_LENGTH:
            return jsonify({"error": f"name exceeds max length of {MAX_NAME_LENGTH}"}), 400
    if require_all or "html" in data:
        html = data.get("html")
        if not html or not isinstance(html, str) or not html.strip():
            return jsonify({"error": "html is required"}), 400
        if len(html) > MAX_HTML_LENGTH:
            return jsonify({"error": "html too large (max 500kb)"}), 400
    if "text" in data and data.get("text") is not None:
        text = data["text"]
        if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
            return jsonify({"error": f"text exceeds max length of {MAX_TEXT_LENGTH}"}), 400
    return None


@signatures_bp.route("/<account_id>/signatures", methods=["GET"])
def list_signatures(account_id: str):
    """Liste les signatures du compte. Seed automatique au premier appel :
    si la bibliothèque est vide et que le compte a déjà une signature
    (l'unique signature legacy), elle devient l'entrée « Signature 1 » par défaut."""
    account, err = _resolve_account(account_id)
    if err:
        return err

    with _signatures_lock:
        signatures = _load_signatures()
        entries = _account_entries(signatures, account_id)

        if not entries and (account.signature_html or account.signature):
            seeded = {
                "id": f"sig_{uuid.uuid4().hex[:12]}",
                "account_id": account_id,
                "name": "Signature 1",
                "html": account.signature_html or "",
                "text": account.signature or _html_to_text(account.signature_html or ""),
                "is_default": True,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            signatures.append(seeded)
            _save_signatures(signatures)
            entries = [seeded]

    default_id = next((s["id"] for s in entries if s.get("is_default")), None)
    return jsonify({
        "signatures": [_serialize(s) for s in entries],
        "default_id": default_id,
    })


@signatures_bp.route("/<account_id>/signatures", methods=["POST"])
def create_signature(account_id: str):
    account, err = _resolve_account(account_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    invalid = _validate_payload(data, require_all=True)
    if invalid:
        return invalid

    html = data["html"]
    text = (data.get("text") or "").strip() or _html_to_text(html)

    with _signatures_lock:
        signatures = _load_signatures()
        entries = _account_entries(signatures, account_id)
        if len(entries) >= MAX_SIGNATURES_PER_ACCOUNT:
            return jsonify({"error": f"signature limit reached (max {MAX_SIGNATURES_PER_ACCOUNT})"}), 400
        # Première signature d'un compte qui n'en avait aucune → défaut immédiat
        is_default = not entries and not (account.signature_html or account.signature)
        entry = {
            "id": f"sig_{uuid.uuid4().hex[:12]}",
            "account_id": account_id,
            "name": data["name"].strip(),
            "html": html,
            "text": text,
            "is_default": is_default,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        signatures.append(entry)
        _save_signatures(signatures)

    if entry["is_default"]:
        _persist_account_signature(account_id, text, html)

    return jsonify({"success": True, "signature": _serialize(entry)}), 201


@signatures_bp.route("/<account_id>/signatures/<sig_id>", methods=["PUT"])
def update_signature(account_id: str, sig_id: str):
    _account, err = _resolve_account(account_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    invalid = _validate_payload(data, require_all=False)
    if invalid:
        return invalid

    with _signatures_lock:
        signatures = _load_signatures()
        entry = next(
            (s for s in signatures if s["id"] == sig_id and s.get("account_id") == account_id),
            None,
        )
        if not entry:
            return jsonify({"error": "Signature not found"}), 404

        if "name" in data:
            entry["name"] = data["name"].strip()
        if "html" in data:
            entry["html"] = data["html"]
            entry["text"] = (data.get("text") or "").strip() or _html_to_text(data["html"])
        elif "text" in data and data.get("text") is not None:
            entry["text"] = data["text"]
        entry["updated_at"] = _now_iso()
        _save_signatures(signatures)
        is_default = bool(entry.get("is_default"))
        text, html = entry["text"], entry["html"]

    # La signature par défaut est le couple canonique du compte : la modifier
    # doit se refléter immédiatement dans les emails.
    if is_default:
        _persist_account_signature(account_id, text, html)

    return jsonify({"success": True, "signature": _serialize(entry)})


@signatures_bp.route("/<account_id>/signatures/<sig_id>", methods=["DELETE"])
def delete_signature(account_id: str, sig_id: str):
    _account, err = _resolve_account(account_id)
    if err:
        return err

    with _signatures_lock:
        signatures = _load_signatures()
        entry = next(
            (s for s in signatures if s["id"] == sig_id and s.get("account_id") == account_id),
            None,
        )
        if not entry:
            return jsonify({"error": "Signature not found"}), 404

        was_default = bool(entry.get("is_default"))
        signatures = [s for s in signatures if s is not entry]
        remaining = _account_entries(signatures, account_id)

        promoted = None
        if was_default and remaining:
            promoted = remaining[0]
            _set_exclusive_default(remaining, promoted["id"])
        _save_signatures(signatures)

    if was_default:
        if promoted:
            _persist_account_signature(account_id, promoted.get("text", ""), promoted.get("html", ""))
        else:
            # Dernière signature supprimée : la bibliothèque est LA source de
            # vérité de l'UI — on efface aussi la signature active du compte
            # pour que les emails cessent d'être signés (cohérence visible).
            _persist_account_signature(account_id, "", "")

    return jsonify({"success": True})


@signatures_bp.route("/<account_id>/signatures/<sig_id>/set-default", methods=["POST"])
def set_default_signature(account_id: str, sig_id: str):
    _account, err = _resolve_account(account_id)
    if err:
        return err

    with _signatures_lock:
        signatures = _load_signatures()
        entries = _account_entries(signatures, account_id)
        entry = next((s for s in entries if s["id"] == sig_id), None)
        if not entry:
            return jsonify({"error": "Signature not found"}), 404
        _set_exclusive_default(entries, sig_id)
        entry["updated_at"] = _now_iso()
        _save_signatures(signatures)
        text, html = entry.get("text", ""), entry.get("html", "")

    _persist_account_signature(account_id, text, html)

    return jsonify({"success": True, "signature": _serialize(entry)})
