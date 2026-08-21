# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour la gestion multi-comptes email.

Endpoints disponibles:
- GET /api/accounts - Liste tous les comptes
- GET /api/accounts/<id> - Détails d'un compte
- POST /api/accounts - Créer un nouveau compte
- PATCH /api/accounts/<id> - Modifier un compte
- DELETE /api/accounts/<id> - Supprimer un compte
- POST /api/accounts/<id>/activate - Activer/sélectionner un compte
- GET /api/accounts/<id>/stats - Statistiques d'un compte
- POST /api/accounts/<id>/test - Tester la connexion d'un compte
"""

import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Optional
from flask import Blueprint, request, jsonify, send_file, g

from app.multi_accounts import (
    get_account_manager,
    ProviderType,
    AccountStatus,
)
from app.db.database import get_db_session
from app.db.repositories import AccountRepository, EmailRepository
from app.services.cache_manager import get_cache_manager
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

accounts_bp = Blueprint("accounts", __name__)

# Security: Input validation constants
MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254  # RFC 5321
MAX_PATH_LENGTH = 500
MAX_SIGNATURE_LENGTH = 2000
MAX_SENDER_LIST_LENGTH = 100
MAX_DOMAIN_LIST_LENGTH = 100

# Email validation pattern
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


def _validate_account_id(account_id: str) -> bool:
    """Valide le format d'un ID de compte."""
    if not account_id or not isinstance(account_id, str):
        return False
    return bool(ACCOUNT_ID_PATTERN.match(account_id))


def _purge_contact_groups_for_account(db_account_id: int) -> None:
    """Remove every contact group attached to a deleted account (RGPD purge).

    Post-migration 039 les groupes vivent dans la table ``contact_groups``.
    On force d'abord l'import du JSON legacy : un groupe encore dans le
    fichier non importé survivrait sinon à la suppression du compte.
    """
    from app.api.contact_groups import _ensure_legacy_import
    from app.db.database import get_db_session
    from app.db.repositories.contact_group_repository import ContactGroupRepository

    _ensure_legacy_import()
    with get_db_session() as session:
        removed = ContactGroupRepository(session).delete_all_for_account(db_account_id)
        session.commit()
    if removed:
        logger.info(
            f"[CLEANUP] Removed {removed} contact groups "
            f"for account_id={db_account_id}"
        )


def _purge_snippets_for_account(db_account_id: int, owner_email: str) -> None:
    """Remove snippets and shares attached to a deleted account.

    Snippets are scoped softly: `owner_email` isolates between users and
    `account_id` is an optional refinement for multi-account users. When the
    last account of an owner_email is deleted, all of their snippets go too.
    Otherwise we only remove the ones explicitly tagged with this account_id.
    """
    from app.api.snippets import _ensure_legacy_import
    from app.db.database import get_db_session
    from app.db.repositories.snippet_repository import SnippetRepository

    # Post-migration 040 les snippets vivent en DB. Import legacy forcé
    # d'abord : un snippet encore dans le JSON non importé survivrait sinon
    # à la suppression du compte.
    _ensure_legacy_import()

    # Are there any other accounts still using this owner_email?
    manager = get_account_manager()
    remaining_for_owner = [
        a for a in manager.get_all_accounts()
        if (a.email or "").lower() == (owner_email or "").lower()
    ]
    owner_has_no_more_accounts = len(remaining_for_owner) == 0

    with get_db_session() as session:
        removed, shares_removed = SnippetRepository(session).purge_for_account(
            db_account_id, owner_email, owner_has_no_more_accounts
        )
        session.commit()
    if removed:
        logger.info(
            f"[CLEANUP] Removed {removed} snippets for "
            f"account_id={db_account_id} owner={owner_email}"
        )
    if shares_removed:
        logger.info(f"[CLEANUP] Removed {shares_removed} snippet shares")


def _validate_email(email: str) -> bool:
    """Valide le format d'une adresse email."""
    if not email or not isinstance(email, str):
        return False
    if len(email) > MAX_EMAIL_LENGTH:
        return False
    return bool(EMAIL_PATTERN.match(email))


def _purge_followups_for_account(account_hash_id: str) -> None:
    """Remove all followups belonging to a deleted account.

    Post-migration 041 les followups vivent dans la table ``followups``
    (clé = string OAuth hash). L'import legacy est forcé d'abord — un
    followup encore dans le JSON non importé survivrait sinon à la
    suppression. NB l'ancien code lisait ``data/followups.json`` en chemin
    relatif (ignorait AGENTYS_DATA_DIR) — incohérence éliminée par la DB.
    """
    from app.services import followup_store

    removed = followup_store.delete_all_for_account(account_hash_id)
    if removed:
        logger.info(
            f"[CLEANUP] Removed {removed} followups for account {account_hash_id}"
        )


def _purge_label_assignments_for_account(db_account_id: int) -> None:
    """Remove label assignments tied to emails of a deleted account.

    Two storages are involved:
    - `assignments.json` (LabelStore JSON) — flat dict keyed by email_id, with
      no account_id field. We need to cross-reference deleted email_ids.
      Since emails are CASCADE-deleted before this runs, we instead purge any
      assignment whose email_id no longer exists in the SQLite emails table.
    - `email_labels` SQL table — now CASCADE-protected by FK from the
      Alembic migration, but we explicitly DELETE here as well to cover the
      window where the migration hasn't run yet on this user's database.
    """
    import json as _json
    import os as _os

    # SQL table cleanup (defensive — CASCADE FK should handle it, but the
    # migration may not have run yet on existing DBs).
    try:
        from sqlalchemy import text as _text
        with get_db_session() as session:
            session.execute(
                _text("DELETE FROM email_labels WHERE account_id = :aid"),
                {"aid": db_account_id},
            )
            session.commit()
    except Exception as e:
        logger.debug(f"[CLEANUP] SQL email_labels purge failed: {e}")

    # JSON file cleanup — drop entries whose email_id no longer exists in DB
    assignments_file = _os.path.join("data", "assignments.json")
    if not _os.path.exists(assignments_file):
        return
    try:
        with open(assignments_file, "r", encoding="utf-8") as f:
            assignments = _json.load(f)
    except (_json.JSONDecodeError, IOError):
        return

    if not isinstance(assignments, dict) or not assignments:
        return

    try:
        from sqlalchemy import text as _text
        with get_db_session() as session:
            existing_ids = set(
                row[0] for row in session.execute(
                    _text("SELECT email_id FROM emails")
                ).fetchall()
            )
    except Exception:
        existing_ids = None  # type: ignore[assignment]

    if existing_ids is None:
        return

    before = len(assignments)
    kept = {eid: a for eid, a in assignments.items() if eid in existing_ids}
    if len(kept) != before:
        with open(assignments_file, "w", encoding="utf-8") as f:
            _json.dump(kept, f, indent=2, default=str)
        logger.info(
            f"[CLEANUP] Removed {before - len(kept)} orphan label assignments "
            f"after deleting account_id={db_account_id}"
        )


def _purge_account_scoped_trackers(account_hash_id: str) -> None:
    """Remove the per-account auto-reply and auto-transfer tracker files.

    These trackers are now scoped per-account (one file per account_id) so a
    delete is just a file unlink. The legacy global files are left alone — they
    are no longer written to and will be purged by the global reset path.
    """
    import os as _os
    for name in ("auto_reply_tracker", "auto_transfer_tracker"):
        path = _os.path.join("data", f"{name}_{account_hash_id}.json")
        try:
            if _os.path.exists(path):
                _os.remove(path)
                logger.info(f"[CLEANUP] Removed {name} for {account_hash_id}")
        except OSError as e:
            logger.warning(f"[CLEANUP] Failed to remove {path}: {e}")


def _validate_provider(provider: str) -> bool:
    """Valide le type de provider."""
    valid_providers = {p.value for p in ProviderType}
    return provider in valid_providers


from app.api._auth_helpers import get_auth_user_id as _get_auth_user_id  # noqa: E402
from app.api._auth_helpers import check_account_ownership as _check_account_ownership_impl  # noqa: E402


def _get_auth_email():
    """Extrait l'email du JWT (g.auth_user) ou None."""
    from flask import has_request_context
    auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
    if auth_user:
        return auth_user.get("email")
    return None


def _check_account_ownership(account, auth_user_id):
    """Alias local — délègue à _auth_helpers.check_account_ownership."""
    return _check_account_ownership_impl(account, auth_user_id)


def _ensure_db_account(email: str, provider: str, display_name: str = "", user_id=None) -> None:
    """Crée un Account dans SQLite s'il n'existe pas encore (idempotent)."""
    _did_mutate = False
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        from app.db.models.account import Account
        with get_db_session() as session:
            repo = AccountRepository(session)
            existing = repo.get_by_email(email)
            if not existing:
                db_account = Account(
                    email=email,
                    provider=provider,
                    display_name=display_name,
                    is_active=False,
                    user_id=user_id,
                )
                session.add(db_account)
                session.commit()
                _did_mutate = True
                logger.info(f"Created DB account for {email} (id={db_account.id}, user_id={user_id})")
            elif user_id is not None and existing.user_id != user_id:
                # Backfill/migrate user_id on existing account
                existing.user_id = user_id
                session.commit()
                _did_mutate = True
    except Exception as e:
        logger.warning(f"Failed to ensure DB account for {email}: {e}")
    # ISO-12 symmetry (2026-04-24): a fresh DB id was just minted (or user_id
    # backfilled) for this email — drop resolver cache so the next JWT-routed
    # request picks up the new id immediately instead of waiting 60s for TTL.
    if _did_mutate:
        try:
            from app.api.routes_helpers import _invalidate_account_id_cache
            _invalidate_account_id_cache(email)
        except Exception:
            pass


def _account_to_dict(account) -> dict:
    """Convertit un AccountConfig en dictionnaire."""
    sig_html = account.signature_html
    sig_text = account.signature
    try:
        from app.api.signatures import get_default_signature_for_account
        lib = get_default_signature_for_account(account.id)
        if lib is not None:
            sig_html, sig_text = lib
    except Exception:
        pass
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "provider": account.provider,
        "status": account.status,
        "check_interval_minutes": account.check_interval_minutes,
        "max_emails_per_batch": account.max_emails_per_batch,
        "auto_reply_enabled": account.auto_reply_enabled,
        "draft_only": account.draft_only,
        "default_language": account.default_language,
        "signature": sig_text,
        "signature_html": sig_html,
        "created_at": account.created_at,
        "last_sync": account.last_sync,
        "last_error": account.last_error,
        "email_count": account.email_count,
    }


def _account_to_summary_dict(account, is_current: bool = False) -> dict:
    """Convertit un AccountConfig en dictionnaire résumé."""
    sig_html = getattr(account, "signature_html", None)
    sig_text = account.signature
    try:
        from app.api.signatures import get_default_signature_for_account
        lib = get_default_signature_for_account(account.id)
        if lib is not None:
            sig_html, sig_text = lib
    except Exception:
        pass
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "provider": account.provider,
        "status": account.status,
        "is_current": is_current,
        "last_sync": account.last_sync,
        "signature": sig_text,
        "signature_html": sig_html,
        "avatar_url": getattr(account, "avatar_url", None),
    }


SIGNATURE_IMAGES_DIR = Path(__file__).parent.parent.parent / 'data' / 'signature_images'
AVATARS_DIR = Path(__file__).parent.parent.parent / 'data' / 'avatars'


def _save_avatar_bytes(data: bytes, content_type: str, account_id_str: str) -> str:
    """Save raw image bytes to AVATARS_DIR, return relative API URL."""
    ext = 'png' if 'png' in content_type else ('webp' if 'webp' in content_type else 'jpg')
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{account_id_str}_avatar.{ext}"
    (AVATARS_DIR / filename).write_bytes(data)
    return f"/api/accounts/avatars/{filename}"


# Magic-byte image-type detection (audit M-6, 2026-05-29, CWE-434). NEVER trust
# the client Content-Type or filename for the stored extension — a crafted
# `Content-Type: image/svg+xml` (or image/html) otherwise lets an attacker store
# active markup that the same-origin serve endpoint returns. We sniff the real
# bytes and map to a fixed raster allowlist; SVG and anything unrecognised are
# rejected.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _detect_image_ext(data: bytes) -> str | None:
    """Return a safe raster extension from the file's magic bytes, else None.

    Rejects SVG (text/markup → XSS vector) and any non-raster content.
    """
    for sig, ext in _IMAGE_MAGIC:
        if data.startswith(sig):
            return ext
    # WEBP: 'RIFF'<size>'WEBP'
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


_AVATAR_ALLOWED_HOSTS = (
    "lh3.googleusercontent.com",
    "googleusercontent.com",
    "graph.microsoft.com",
    "people.googleapis.com",
)


def _is_allowed_avatar_url(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in _AVATAR_ALLOWED_HOSTS)


def _save_avatar_from_url(url: str, account_id_str: str) -> Optional[str]:
    """Download image from URL, save to AVATARS_DIR, return relative API URL or None."""
    import requests as _req
    if not _is_allowed_avatar_url(url):
        from urllib.parse import urlparse
        logger.warning("[AVATAR] URL host not in allowlist, skipping: %s", urlparse(url).hostname)
        return None
    resp = _req.get(url, timeout=10)
    if not resp.ok or len(resp.content) > 5 * 1024 * 1024:
        return None
    # Guard against redirect chains to off-allowlist hosts (SSRF mitigation)
    if not _is_allowed_avatar_url(resp.url):
        logger.warning("[AVATAR] Redirect target not in allowlist, discarding: %s", resp.url)
        return None
    return _save_avatar_bytes(resp.content, resp.headers.get('Content-Type', 'image/jpeg'), account_id_str)


def fetch_and_store_provider_avatar(email: str, access_token: str, provider: str, account_id_str: str) -> Optional[str]:
    """Fetch profile photo from Gmail or Outlook and store locally. Returns relative URL or None."""
    import requests as _req
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        if provider == 'gmail':
            # Try userinfo first (works with userinfo.email scope, may include picture)
            ui = _req.get('https://www.googleapis.com/oauth2/v2/userinfo', headers=headers, timeout=10)
            if ui.ok:
                pic = ui.json().get('picture')
                if pic:
                    return _save_avatar_from_url(pic, account_id_str)
            # Fallback: People API (requires profile scope)
            pr = _req.get(
                'https://people.googleapis.com/v1/people/me?personFields=photos',
                headers=headers, timeout=10,
            )
            if pr.ok:
                photos = pr.json().get('photos', [])
                photo_url = next(
                    (p.get('url') for p in photos if p.get('metadata', {}).get('primary')),
                    next((p.get('url') for p in photos), None),
                )
                if photo_url:
                    return _save_avatar_from_url(photo_url, account_id_str)
        elif provider == 'outlook':
            resp = _req.get(
                'https://graph.microsoft.com/v1.0/me/photo/$value',
                headers=headers, timeout=10,
            )
            if resp.ok and len(resp.content) <= 5 * 1024 * 1024:
                return _save_avatar_bytes(resp.content, resp.headers.get('Content-Type', 'image/jpeg'), account_id_str)
    except Exception as e:
        logger.warning(f"[AVATAR] Provider import failed ({provider}): {e}")
    return None


def _persist_avatar_url(account_email: str, account_id_str: str, url: str) -> None:
    """Update avatar_url in both AccountConfig and DB (best-effort)."""
    manager = get_account_manager()
    manager.update_account(account_id_str, avatar_url=url)
    try:
        with get_db_session() as session:
            from app.db.models.account import Account as AccountModel
            db_acc = session.query(AccountModel).filter_by(email=account_email).first()
            if db_acc:
                db_acc.avatar_url = url
                session.commit()
    except Exception as e:
        logger.warning(f"[AVATAR] DB persist failed: {e}")


@accounts_bp.route("/signature-images/<filename>")
def serve_signature_image(filename: str):
    """Sert une image de signature depuis data/signature_images/."""
    safe_name = Path(filename).name
    image_path = SIGNATURE_IMAGES_DIR / safe_name
    if not image_path.exists():
        return jsonify({"error": "Image not found"}), 404
    return send_file(str(image_path), max_age=86400)


@accounts_bp.route("/avatars/<filename>")
def serve_avatar(filename: str):
    """Sert un avatar depuis data/avatars/."""
    safe_name = Path(filename).name
    path = AVATARS_DIR / safe_name
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return send_file(str(path), max_age=86400)


@accounts_bp.route("/<account_id>/avatar", methods=["POST"])
def upload_avatar(account_id: str):
    """Upload manuel d'un avatar, retourne l'URL."""
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id"}), 400
    if 'image' not in request.files:
        return jsonify({"error": "Champ 'image' manquant"}), 400

    file = request.files['image']
    if not file.content_type or not file.content_type.startswith('image/'):
        return jsonify({"error": "Type MIME invalide, image/* requis"}), 400

    data = file.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({"error": "Image trop grande (max 5MB)"}), 400
    # SECURITY (audit M-6, 2026-05-29): validate real magic bytes, reject SVG/markup.
    if _detect_image_ext(data) is None:
        return jsonify({"error": "Unsupported image type (png/jpg/webp/gif only)"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    url = _save_avatar_bytes(data, file.content_type, account_id)
    _persist_avatar_url(account.email, account_id, url)
    logger.info(f"[AVATAR] Uploaded for {account.email}")
    return jsonify({"url": url})


@accounts_bp.route("/<account_id>/avatar/import", methods=["POST"])
def import_avatar(account_id: str):
    """Importe la photo de profil depuis Gmail ou Outlook."""
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    if account.provider not in ('gmail', 'outlook'):
        return jsonify({"error": "Import disponible uniquement pour Gmail et Outlook"}), 400

    # Prefer the live server token store (kept fresh by the sync service)
    # over the raw DB field which may be stale.
    access_token = None
    try:
        from app.api.oauth import get_tokens_server
        tokens = get_tokens_server(account_id)
        if tokens:
            access_token = tokens.get('access_token')
    except Exception:
        pass

    if not access_token:
        try:
            with get_db_session() as session:
                from app.db.models.account import Account as AccountModel
                db_acc = session.query(AccountModel).filter_by(email=account.email).first()
                if db_acc:
                    access_token = db_acc.access_token
        except Exception as e:
            logger.warning(f"[AVATAR] Token lookup failed: {e}")

    if not access_token:
        return jsonify({"error": "Token introuvable — reconnectez votre compte Gmail ou Outlook pour importer la photo"}), 404

    url = fetch_and_store_provider_avatar(account.email, access_token, account.provider, account_id)
    if not url:
        return error_response(
            "ACCOUNT_NO_AVATAR",
            "No profile photo found for this account. Reconnect to sync.",
            502,
        )

    _persist_avatar_url(account.email, account_id, url)
    logger.info(f"[AVATAR] Imported from {account.provider} for {account.email}")
    return jsonify({"url": url})


@accounts_bp.route("", methods=["GET"])
def list_accounts():
    """
    Liste tous les comptes email.
    ---
    tags:
      - Accounts
    summary: Liste tous les comptes email configurés
    responses:
      200:
        description: Liste des comptes
        content:
          application/json:
            schema:
              type: object
              properties:
                count:
                  type: integer
                current_account_id:
                  type: string
                  nullable: true
                accounts:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                      name:
                        type: string
                      email:
                        type: string
                      provider:
                        type: string
                      status:
                        type: string
                      is_current:
                        type: boolean
    """
    manager = get_account_manager()
    manager.deduplicate_accounts()  # Clean up any duplicate email entries
    auth_user_id = _get_auth_user_id()
    accounts = manager.get_all_accounts()

    # Multi-user isolation: only apply on remote connections, not localhost
    from app.api.auth import is_trusted_loopback
    is_local = is_trusted_loopback()
    if auth_user_id is not None and not is_local:
        auth_email = _get_auth_email()
        backfilled = False
        for a in accounts:
            if auth_email and a.email and a.email.lower() == auth_email.lower() and a.user_id != auth_user_id:
                a.user_id = auth_user_id
                backfilled = True
                logger.info(f"Backfilled user_id={auth_user_id} on account {a.id} ({a.email})")
        if backfilled:
            manager._save()
        accounts = [a for a in accounts if a.user_id == auth_user_id]

    # On loopback (Tauri desktop), always use the desktop current account (user_id=None key)
    # even when a JWT is present — the JWT user may not have a separate current_account entry.
    current_id = manager.get_current_for_user(None if is_local else auth_user_id)

    # Auto-select first account if none is current (e.g. after fresh OAuth)
    if not current_id and accounts:
        current_id = accounts[0].id
        manager.set_current_for_user(current_id, None if is_local else auth_user_id)
        logger.info(f"Auto-selected account {current_id} as current")

    return jsonify({
        "count": len(accounts),
        "current_account_id": current_id,
        "accounts": [
            _account_to_summary_dict(a, a.id == current_id)
            for a in accounts
        ],
    })


@accounts_bp.route("/<account_id>", methods=["GET"])
def get_account(account_id: str):
    """
    Récupère les détails d'un compte.
    ---
    tags:
      - Accounts
    summary: Récupère les détails d'un compte spécifique
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Détails du compte
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)

    if not account:
        return jsonify({"error": "Account not found"}), 404

    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    auth_user_id = _get_auth_user_id()
    result = _account_to_dict(account)
    result["is_current"] = account_id == manager.get_current_for_user(auth_user_id)

    stats = manager.stats.get(account_id)
    if stats:
        result["stats"] = {
            "emails_processed": stats.emails_processed,
            "drafts_created": stats.drafts_created,
            "drafts_sent": stats.drafts_sent,
            "errors": stats.errors,
            "avg_response_time_seconds": stats.avg_response_time_seconds,
        }

    return jsonify(result)


@accounts_bp.route("", methods=["POST"])
def create_account():
    """
    Crée un nouveau compte email.
    ---
    tags:
      - Accounts
    summary: Crée un nouveau compte email
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - name
              - email
              - provider
            properties:
              name:
                type: string
                description: Nom du compte (ex. "Travail", "Personnel")
                example: "Travail"
              email:
                type: string
                format: email
                example: "john@example.com"
              provider:
                type: string
                enum: [gmail, outlook, imap_smtp]
                example: "imap_smtp"
              credentials_path:
                type: string
                description: Chemin vers le fichier credentials (optionnel)
              check_interval_minutes:
                type: integer
                default: 5
              auto_reply_enabled:
                type: boolean
                default: true
              draft_only:
                type: boolean
                default: false
              signature:
                type: string
    responses:
      201:
        description: Compte créé
      400:
        description: Données invalides
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    name = data.get("name")
    email = data.get("email")
    provider = data.get("provider")

    if not name or not isinstance(name, str) or not name.strip():
        return jsonify({"error": "name is required"}), 400
    if len(name) > MAX_NAME_LENGTH:
        return jsonify({"error": f"name exceeds max length of {MAX_NAME_LENGTH}"}), 400

    if not _validate_email(email):
        return jsonify({"error": "Valid email is required"}), 400

    if not _validate_provider(provider):
        valid = [p.value for p in ProviderType]
        return jsonify({"error": f"Invalid provider. Must be one of: {', '.join(valid)}"}), 400

    manager = get_account_manager()
    existing = manager.get_account_by_email(email)
    if existing:
        return jsonify({"error": "Account with this email already exists"}), 400

    optional_fields = {}

    if "credentials_path" in data:
        cred_path = data["credentials_path"]
        if cred_path and len(cred_path) > MAX_PATH_LENGTH:
            return jsonify({"error": f"credentials_path exceeds max length of {MAX_PATH_LENGTH}"}), 400
        optional_fields["credentials_path"] = cred_path

    if "check_interval_minutes" in data:
        interval = data["check_interval_minutes"]
        if not isinstance(interval, int) or interval < 1 or interval > 1440:
            return jsonify({"error": "check_interval_minutes must be between 1 and 1440"}), 400
        optional_fields["check_interval_minutes"] = interval

    if "max_emails_per_batch" in data:
        max_batch = data["max_emails_per_batch"]
        if not isinstance(max_batch, int) or max_batch < 1 or max_batch > 100:
            return jsonify({"error": "max_emails_per_batch must be between 1 and 100"}), 400
        optional_fields["max_emails_per_batch"] = max_batch

    if "auto_reply_enabled" in data:
        optional_fields["auto_reply_enabled"] = bool(data["auto_reply_enabled"])

    if "draft_only" in data:
        optional_fields["draft_only"] = bool(data["draft_only"])

    if "signature" in data:
        sig = data["signature"]
        if sig and len(sig) > MAX_SIGNATURE_LENGTH:
            return jsonify({"error": f"signature exceeds max length of {MAX_SIGNATURE_LENGTH}"}), 400
        optional_fields["signature"] = sig

    if "default_language" in data:
        lang = data["default_language"]
        if lang and len(lang) > 10:
            return jsonify({"error": "default_language must be a valid language code"}), 400
        optional_fields["default_language"] = lang

    # IMAP/SMTP fields (strip whitespace to avoid auth failures)
    if data.get("imap_host"):
        optional_fields["imap_host"] = data["imap_host"].strip()
    if data.get("imap_port"):
        optional_fields["imap_port"] = int(data["imap_port"])
    if data.get("imap_user"):
        optional_fields["imap_user"] = data["imap_user"].strip()
    if data.get("imap_password"):
        optional_fields["imap_password"] = data["imap_password"].strip()
    if data.get("smtp_host"):
        optional_fields["smtp_host"] = data["smtp_host"].strip()
    if data.get("smtp_port"):
        optional_fields["smtp_port"] = int(data["smtp_port"])
    if data.get("smtp_user"):
        optional_fields["smtp_user"] = data["smtp_user"].strip()
    if data.get("smtp_password"):
        optional_fields["smtp_password"] = data["smtp_password"].strip()

    try:
        auth_user_id = _get_auth_user_id()
        provider_type = ProviderType(provider)
        account = manager.add_account(
            name=name.strip(),
            email=email,
            provider=provider_type,
            user_id=auth_user_id,
            **optional_fields,
        )

        # Ensure a DB Account row exists (needed for SQLite email cache scoping)
        _ensure_db_account(email, provider, name.strip(), user_id=auth_user_id)

        return jsonify({
            "success": True,
            "account": _account_to_dict(account),
        }), 201

    except Exception as e:
        logger.error(f"Error creating account: {e}")
        return jsonify({"error": "Failed to create account"}), 500


@accounts_bp.route("/<account_id>", methods=["PATCH"])
def update_account(account_id: str):
    """
    Met à jour un compte existant.
    ---
    tags:
      - Accounts
    summary: Met à jour un compte existant
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              name:
                type: string
              check_interval_minutes:
                type: integer
              auto_reply_enabled:
                type: boolean
              draft_only:
                type: boolean
              signature:
                type: string
    responses:
      200:
        description: Compte mis à jour
      400:
        description: Données invalides
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)

    if not account:
        return jsonify({"error": "Account not found"}), 404

    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    updates = {}

    if "name" in data:
        name = data["name"]
        if not name or not isinstance(name, str) or not name.strip():
            return jsonify({"error": "name cannot be empty"}), 400
        if len(name) > MAX_NAME_LENGTH:
            return jsonify({"error": f"name exceeds max length of {MAX_NAME_LENGTH}"}), 400
        updates["name"] = name.strip()

    if "check_interval_minutes" in data:
        interval = data["check_interval_minutes"]
        if not isinstance(interval, int) or interval < 1 or interval > 1440:
            return jsonify({"error": "check_interval_minutes must be between 1 and 1440"}), 400
        updates["check_interval_minutes"] = interval

    if "max_emails_per_batch" in data:
        max_batch = data["max_emails_per_batch"]
        if not isinstance(max_batch, int) or max_batch < 1 or max_batch > 100:
            return jsonify({"error": "max_emails_per_batch must be between 1 and 100"}), 400
        updates["max_emails_per_batch"] = max_batch

    if "auto_reply_enabled" in data:
        updates["auto_reply_enabled"] = bool(data["auto_reply_enabled"])

    if "draft_only" in data:
        updates["draft_only"] = bool(data["draft_only"])

    if "signature" in data:
        sig = data["signature"]
        if sig and len(sig) > MAX_SIGNATURE_LENGTH:
            return jsonify({"error": f"signature exceeds max length of {MAX_SIGNATURE_LENGTH}"}), 400
        updates["signature"] = sig

    if "signature_html" in data:
        sig_html = data["signature_html"]
        if sig_html and len(sig_html) > 512000:
            return jsonify({"error": "signature_html trop longue (max 500ko)"}), 400
        updates["signature_html"] = sig_html

    if "default_language" in data:
        lang = data["default_language"]
        if lang and len(lang) > 10:
            return jsonify({"error": "default_language must be a valid language code"}), 400
        updates["default_language"] = lang

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    updated = manager.update_account(account_id, **updates)
    if not updated:
        return jsonify({"error": "Failed to update account"}), 500

    # Persist signature fields to SQLite DB (used by append_signature for drafts).
    # Audit e2e 2026-06-10 B-01 : un échec ici était avalé en warning avec
    # success:true sec — or get_account_signature lit la row DB en priorité,
    # donc les ENVOIS gardaient l'ancienne signature, et la perte du flag
    # signature_user_modified laissait le prochain OAuth re-login écraser la
    # signature custom. On remonte `signature_db_persisted: false` pour que le
    # FE puisse avertir, et on logge en error (panne réelle, pas du bruit).
    signature_db_persisted = True
    if "signature" in updates or "signature_html" in updates:
        try:
            account = manager.get_account(account_id)
            if account:
                with get_db_session() as session:
                    db_acc = AccountRepository(session).get_by_email(account.email)
                    if not db_acc:
                        db_acc = AccountRepository(session).get_by_email(account.email.lower())
                    if db_acc:
                        if "signature" in updates:
                            db_acc.signature_text = updates["signature"]
                        if "signature_html" in updates:
                            db_acc.signature_html = updates["signature_html"]
                        db_acc.signature_user_modified = True
                        session.commit()
                        logger.info(f"Signature saved to DB for {account.email} (user_modified=True)")
                    else:
                        signature_db_persisted = False
                        logger.warning(f"Account {account.email} not found in SQLite — signature in JSON config only")
        except Exception as db_err:
            signature_db_persisted = False
            logger.error(f"Could not persist signature to DB for {account_id}: {db_err}")

    payload = {
        "success": True,
        "account": _account_to_dict(updated),
    }
    if ("signature" in updates or "signature_html" in updates) and not signature_db_persisted:
        payload["signature_db_persisted"] = False
    return jsonify(payload)


@accounts_bp.route("/<account_id>", methods=["DELETE"])
def delete_account(account_id: str):
    """
    Supprime un compte.
    ---
    tags:
      - Accounts
    summary: Supprime un compte email
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Compte supprimé
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()

    account = manager.get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404

    from app.api.auth import is_trusted_loopback
    _auth_uid = _get_auth_user_id()
    _is_local = is_trusted_loopback()
    if _auth_uid is not None and not _is_local:
        if not _check_account_ownership(account, _auth_uid):
            return jsonify({"error": "Account not found"}), 404

    # --- Cleanup cached data before removing account config ---
    db_account_id: int | None = None
    _deleted_email = account.email
    try:
        with get_db_session() as session:
            account_repo = AccountRepository(session)
            db_account = account_repo.get_by_email(account.email)
            if db_account:
                db_account_id = db_account.id
                # Delete cached emails for this account
                email_repo = EmailRepository(session)
                deleted_count = email_repo.delete_by_account(db_account.id)
                logger.info(f"[CLEANUP] Deleted {deleted_count} cached emails for {account.email}")

                # Delete the account row (CASCADE handles remaining FKs)
                account_repo.delete(db_account)
                logger.info(f"[CLEANUP] Deleted SQLite account row for {account.email}")

            session.commit()
    except Exception as e:
        logger.warning(f"[CLEANUP] DB cleanup failed for {account_id}: {e}")
    # ISO-12 symmetry (2026-04-24): the DB account row was just deleted —
    # drop resolver cache so we don't return the dead id for 60s. Critical
    # path: without this, requests after delete still resolve to the old id
    # and may hit cascade-deleted rows.
    try:
        from app.api.routes_helpers import _invalidate_account_id_cache, _suppress_account_heal
        if _deleted_email:
            _invalidate_account_id_cache(_deleted_email)
            # Bug Karine follow-up (2026-06-09): the resolver now self-heals a
            # missing accounts row from the AccountManager config. The manager
            # entry is only removed at the END of this (slow) deletion flow, so
            # without suppression a concurrent /api/emails poll would resurrect
            # the row we just deleted as an orphan ghost account. A future OAuth
            # re-connect lifts the block via _invalidate_account_id_cache.
            _suppress_account_heal(_deleted_email)
    except Exception:
        pass

    # Cleanup JSON-backed per-account data (contact groups + snippets +
    # label assignments). These are stored in flat files keyed by the int
    # DB account_id, so we only run them when we successfully resolved
    # db_account_id above.
    if db_account_id is not None:
        try:
            _purge_contact_groups_for_account(db_account_id)
        except Exception as e:
            logger.warning(f"[CLEANUP] contact_groups purge failed for {account_id}: {e}")
        try:
            _purge_snippets_for_account(db_account_id, account.email)
        except Exception as e:
            logger.warning(f"[CLEANUP] snippets purge failed for {account_id}: {e}")
        try:
            _purge_label_assignments_for_account(db_account_id)
        except Exception as e:
            logger.warning(f"[CLEANUP] label_assignments purge failed for {account_id}: {e}")
        try:
            from app.services.privacy_retention import delete_account_privacy_artifacts

            privacy_result = delete_account_privacy_artifacts(db_account_id)
            logger.info(
                "[CLEANUP] Privacy artifacts purged for account_id=%s: %s",
                db_account_id,
                privacy_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[CLEANUP] privacy artifact purge failed for {account_id}: {e}")

    # Hash-id-scoped cleanup (uses the URL account_id, not the DB id)
    try:
        _purge_followups_for_account(account_id)
    except Exception as e:
        logger.warning(f"[CLEANUP] followups purge failed for {account_id}: {e}")
    try:
        # Trou RGPD comblé par la migration 042 : rien ne purgeait les
        # suggestions IA d'un compte supprimé.
        from app.services import calendar_suggestion_store
        removed_suggestions = calendar_suggestion_store.delete_all_for_account(account_id)
        if removed_suggestions:
            logger.info(
                f"[CLEANUP] Removed {removed_suggestions} calendar suggestions "
                f"for account {account_id}"
            )
    except Exception as e:
        logger.warning(f"[CLEANUP] suggestions purge failed for {account_id}: {e}")
    try:
        _purge_account_scoped_trackers(account_id)
    except Exception as e:
        logger.warning(f"[CLEANUP] tracker purge failed for {account_id}: {e}")

    # SECURITY/RGPD (audit 2026-05-29, CWE-212): purge per-account Discord/Telegram
    # integration data (live bot token, webhook URL, notification + ticket history)
    # and evict the in-memory bots holding the loaded token. Without this a deleted
    # tenant's credential + message history survive on disk (right-to-erasure gap).
    # Keyed by both the URL account id and the resolved DB id to cover either scheme.
    try:
        import shutil as _shutil
        from app.discord_integration import DISCORD_DATA_DIR as _DDIR
        from app.telegram_integration import TELEGRAM_DATA_DIR as _TDIR
        _ids = {str(account_id)}
        if db_account_id is not None:
            _ids.add(str(db_account_id))
        for _key in _ids:
            for _root in (_DDIR, _TDIR):
                _d = _root / _key
                if _d.exists():
                    _shutil.rmtree(_d, ignore_errors=True)
            try:
                from app.discord_integration import evict_discord_bot as _evd
                _evd(_key)
            except Exception:
                pass
            try:
                from app.telegram_integration import evict_telegram_bot as _evt
                _evt(_key)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[CLEANUP] integration data purge failed for {account_id}: {e}")

    # Clear in-memory email cache
    try:
        from app.api.routes import _invalidate_folder_cache
        _invalidate_folder_cache()
        logger.info("[CLEANUP] In-memory email cache cleared")
    except Exception as e:
        logger.warning(f"[CLEANUP] Cache invalidation failed: {e}")

    # Delete OAuth tokens. Without this the encrypted refresh_token remains in
    # oauth_tokens.json / _server_tokens, and the next sync silently recreates
    # a DB account from the still-valid token — undoing the delete.
    # FIX MIGRATE-002 (audit P0): revoke at the provider FIRST so a captured
    # refresh_token (logs / backup / memory dump) cannot be replayed against
    # Google/Microsoft after this delete completes.
    try:
        from app.api.oauth import (
            delete_tokens_server,
            get_tokens_server,
            revoke_token_at_provider,
        )
        try:
            _captured_token_data = get_tokens_server(account_id)
            if _captured_token_data:
                revoke_token_at_provider(_captured_token_data)
        except Exception as e:
            logger.warning(
                f"[CLEANUP] OAuth provider-side revoke failed for {account_id}: {e}"
            )
        delete_tokens_server(account_id)
    except Exception as e:
        logger.warning(f"[CLEANUP] OAuth token cleanup failed for {account_id}: {e}")

    # FIX MIGRATE-003 (audit P1): cancel any pending/in-flight scheduled
    # emails for this account_id BEFORE removing the AccountManager
    # entry. Otherwise the scheduler tick after delete sees
    # `_load_account(db_id)=None`, marks every claimed row failed, no
    # WebSocket notification is emitted, and the user has no idea their
    # outgoing email was silently dropped.
    if db_account_id is not None:
        try:
            from app.services.scheduled_email_store import get_default_store
            _store = get_default_store()
            _pending_sched = _store.list_by_account(
                account_id=db_account_id,
                statuses=("pending",),
            )
            for _row in _pending_sched:
                _store.cancel(_row["id"], account_id=db_account_id)
            if _pending_sched:
                logger.info(
                    f"[CLEANUP] Cancelled {len(_pending_sched)} pending "
                    f"scheduled email(s) for {_deleted_email}"
                )
        except Exception as e:
            logger.warning(
                f"[CLEANUP] scheduled emails cancel failed for {account_id}: {e}"
            )

    success = manager.remove_account(account_id)

    if not success:
        # Race (2026-06-09 incident): the cleanup above can take >20s (privacy
        # log redaction), long enough for the user to re-trigger the delete.
        # The faster duplicate request removes the manager entry first, so this
        # one finds it gone. The end state is exactly what the caller asked
        # for — report success instead of a misleading 500.
        if manager.get_account(account_id) is None:
            return jsonify({
                "success": True,
                "account_id": account_id,
                "message": "Account already deleted",
            })
        return jsonify({"error": "Failed to delete account"}), 500

    return jsonify({
        "success": True,
        "account_id": account_id,
        "message": "Account deleted",
    })


def _purge_orphaned_labels_bg(db_account_id: int) -> None:
    """Remove label assignments for emails not in the current account's SQLite cache.

    Runs in a background thread after account switch to prevent old account's
    labels from leaking into the new account's views.
    """
    try:
        from app.infrastructure.container import get_container
        from app.db.models.email import Email
        from sqlalchemy import select

        container = get_container()
        label_store = container.get_label_store()

        # Get valid email IDs for this account from SQLite.
        # SEC-003: cap at 50 000 to avoid OOM on large mailboxes.
        with get_db_session() as session:
            valid_ids = set(
                row[0] for row in session.execute(
                    select(Email.email_id)
                    .where(Email.account_id == db_account_id)
                    .limit(50000)
                )
            )

        if not valid_ids:
            return  # No emails cached yet -- skip purge

        # Get all assigned email_ids from label store assignments
        all_assignments = label_store.get_assignments(limit=10000)
        all_assigned = set(a.email_id for a in all_assignments)
        orphaned = all_assigned - valid_ids

        if orphaned:
            for label in label_store.get_labels():
                label_store.bulk_remove_label(orphaned, label.name)
            logger.info(f"[PURGE] Removed labels for {len(orphaned)} orphaned emails")
    except Exception as e:
        logger.warning(f"[PURGE] Orphaned label cleanup failed: {e}")


@accounts_bp.route("/<account_id>/activate", methods=["POST"])
def activate_account(account_id: str):
    """
    Active/sélectionne un compte comme compte courant.
    ---
    tags:
      - Accounts
    summary: Active un compte comme compte courant
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Compte activé
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()
    auth_user_id = _get_auth_user_id()

    # On loopback (Tauri desktop), always switch using user_id=None
    # so _current_per_user[None] is updated (the desktop key)
    from app.api.auth import is_trusted_loopback
    effective_user_id = None if is_trusted_loopback() else auth_user_id

    # Ownership check before switching
    account_check = manager.get_account(account_id)
    if account_check and not _check_account_ownership(account_check, effective_user_id):
        return jsonify({"error": "Account not found"}), 404

    # Audit follow-up 2026-04-29 (F-08 hardening): refuse first-time bind via
    # this API endpoint. The legitimate first-time bind path is the OAuth
    # callback (which has just confirmed the user owns the email). A JWT
    # user calling /activate on a legacy unbound account should NOT be
    # silently granted ownership — `check_account_ownership` already returns
    # False for that case (handled above), but pass the explicit flag for
    # belt-and-suspenders + clear intent.
    context = manager.switch_to(
        account_id,
        user_id=effective_user_id,
        allow_first_time_bind=False,
    )

    if not context:
        return jsonify({"error": "Account not found"}), 404

    # Enforce single active account in DB too
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        account_obj = manager.get_account(account_id)
        if account_obj:
            # Ensure DB row exists (may be missing for accounts created before this fix)
            _ensure_db_account(account_obj.email, account_obj.provider, account_obj.name)
            with get_db_session() as session:
                repo = AccountRepository(session)
                db_account = repo.get_by_email(account_obj.email)
                if db_account:
                    repo.activate_exclusive(db_account.id)
                    session.commit()
    except Exception as e:
        logger.warning(f"Failed to enforce single active account in DB: {e}")

    # Clear email caches so the new account's emails are fetched fresh
    from app.api.routes import _email_cache, _email_cache_lock, _email_detail_cache, _email_detail_cache_lock
    with _email_cache_lock:
        _email_cache.clear()
    with _email_detail_cache_lock:
        _email_detail_cache.clear()

    # Clear calendar cache so the new account's events are fetched fresh
    try:
        from app.api.calendar_routes import _calendar_events_cache, _calendar_events_cache_lock
        with _calendar_events_cache_lock:
            _calendar_events_cache.clear()  # Clear ALL accounts' calendar cache on switch
    except Exception:
        pass

    # Clear label batch cache so label counts are recalculated for the new account
    try:
        from app.api.routes_helpers import _invalidate_label_batch_cache
        _invalidate_label_batch_cache()
    except Exception as e:
        logger.warning(f"Failed to invalidate label batch cache on account switch: {e}")

    # Clear account ID resolution cache to prevent stale account_id leaking
    try:
        from app.api.routes_helpers import _account_id_cache
        _account_id_cache.clear()
    except Exception as e:
        logger.warning(f"Failed to clear account ID cache on account switch: {e}")

    # Clear global TTL cache (knowledge base, prompt caches, etc.)
    try:
        from app.infrastructure.cache import get_cache
        get_cache().clear()
    except Exception as e:
        logger.warning(f"Failed to clear global TTL cache on account switch: {e}")

    # Purge orphaned label assignments in background (labels from old account's emails)
    try:
        account_obj_for_purge = manager.get_account(account_id)
        if account_obj_for_purge:
            with get_db_session() as session:
                repo = AccountRepository(session)
                db_acct = repo.get_by_email(account_obj_for_purge.email)
                if db_acct:
                    threading.Thread(
                        target=_purge_orphaned_labels_bg,
                        args=(db_acct.id,),
                        daemon=True,
                    ).start()
    except Exception as e:
        logger.warning(f"Failed to launch orphaned label purge: {e}")

    account = manager.get_account(account_id)

    return jsonify({
        "success": True,
        "account_id": account_id,
        "account_name": account.name if account else None,
        "message": f"Switched to account: {account.name if account else account_id}",
    })


@accounts_bp.route("/<account_id>/stats", methods=["GET"])
def get_account_stats(account_id: str):
    """
    Récupère les statistiques d'un compte incluant les stats du cache.
    ---
    tags:
      - Accounts
    summary: Statistiques d'un compte
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Statistiques du compte avec cache info
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()
    account_config = manager.get_account(account_id)

    if not account_config:
        return jsonify({"error": "Account not found"}), 404

    if not _check_account_ownership(account_config, _get_auth_user_id()):
        return jsonify({"error": "Access denied"}), 403

    stats = manager.get_stats(account_id)

    # Get cache stats from database
    cache_stats = None
    try:
        with get_db_session() as session:
            account_repo = AccountRepository(session)
            db_account = account_repo.get_by_email(account_config.email)

            if db_account:
                cache_manager = get_cache_manager()
                cache_stats = cache_manager.get_cache_stats(session, db_account.id)
    except Exception as e:
        logger.warning(f"Failed to get cache stats for account {account_id}: {e}")

    return jsonify({
        "account_id": account_id,
        "stats": stats,
        "cache": cache_stats,
    })


@accounts_bp.route("/<account_id>/test", methods=["POST"])
def test_account_connection(account_id: str):
    """
    Teste la connexion d'un compte.
    ---
    tags:
      - Accounts
    summary: Teste la connexion email d'un compte
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Résultat du test de connexion
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)

    if not account:
        return jsonify({"error": "Account not found"}), 404

    # Audit 2026-05-29: this was the only path-id handler in accounts.py
    # missing the ownership check. Without it, any authenticated user could
    # force-authenticate another tenant's stored credentials and flip their
    # account status (status tampering + credential-validity oracle). 404
    # (not 403) mirrors the sibling handlers and avoids confirming existence.
    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    provider = None
    try:
        from app.multi_accounts import create_provider_for_account
        provider = create_provider_for_account(account)

        if provider.authenticate():
            manager.update_account_status(account_id, AccountStatus.ACTIVE)
            return jsonify({
                "success": True,
                "account_id": account_id,
                "message": "Connection successful",
            })
        else:
            manager.update_account_status(
                account_id,
                AccountStatus.ERROR,
                "Authentication failed"
            )
            return jsonify({
                "success": False,
                "error": "Authentication failed",
                "account_id": account_id,
                "message": "Authentication failed",
            }), 401

    except Exception as e:
        logger.error(f"Error testing account {account_id}: {e}")
        manager.update_account_status(
            account_id,
            AccountStatus.ERROR,
            str(e)
        )
        return jsonify({
            "success": False,
            "error": f"Connection error: {str(e)}",
            "account_id": account_id,
            "message": f"Connection error: {str(e)}",
        }), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


@accounts_bp.route("/stats", methods=["GET"])
def get_global_stats():
    """
    Récupère les statistiques globales de tous les comptes.
    ---
    tags:
      - Accounts
    summary: Statistiques globales multi-comptes
    responses:
      200:
        description: Statistiques globales
    """
    manager = get_account_manager()
    stats = manager.get_stats()

    return jsonify(stats)


@accounts_bp.route("/<account_id>/signature-image", methods=["POST"])
def upload_signature_image(account_id: str):
    """Upload une image de signature, retourne l'URL."""
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    if 'image' not in request.files:
        return jsonify({"error": "Champ 'image' manquant"}), 400

    file = request.files['image']
    if not file.content_type or not file.content_type.startswith('image/'):
        return jsonify({"error": "Type MIME invalide, image/* requis"}), 400

    data = file.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({"error": "Image trop grande (max 5MB)"}), 400

    # SECURITY (audit M-6, 2026-05-29): require ownership (was missing) and derive
    # the stored extension from real magic bytes, not the client Content-Type —
    # rejects SVG/markup so the serve endpoint can never return active content.
    manager = get_account_manager()
    account = manager.get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Account not found"}), 404

    ext = _detect_image_ext(data)
    if ext is None:
        return jsonify({"error": "Unsupported image type (png/jpg/webp/gif only)"}), 400
    filename = f"{account_id}_{uuid.uuid4().hex}.{ext}"

    SIGNATURE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (SIGNATURE_IMAGES_DIR / filename).write_bytes(data)

    logger.info(f"Signature image uploaded: {filename}")
    return jsonify({"url": f"/api/accounts/signature-images/{filename}"})


@accounts_bp.route("/<account_id>/sync-signature", methods=["POST"])
def sync_signature(account_id: str):
    """
    Synchronise la signature depuis le provider email (Gmail, etc.).
    ---
    tags:
      - Accounts
    summary: Importe la signature depuis Gmail/Outlook
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Signature synchronisée
      400:
        description: ID invalide
      404:
        description: Compte non trouvé
      500:
        description: Erreur lors de la synchronisation
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    manager = get_account_manager()
    account = manager.get_account(account_id)

    if not account:
        return jsonify({"error": "Account not found"}), 404

    if not _check_account_ownership(account, _get_auth_user_id()):
        return jsonify({"error": "Access denied"}), 403

    provider = None
    try:
        from app.multi_accounts import create_provider_for_account
        provider = create_provider_for_account(account)

        if not provider.authenticate():
            return jsonify({
                "success": False,
                "error": "Email provider authentication failed",
            }), 503

        # Récupérer la signature depuis le provider
        if not hasattr(provider, 'get_signature'):
            return jsonify({
                "success": False,
                "error": "Provider does not support signature sync",
            }), 400

        signature_data = provider.get_signature()

        if not signature_data:
            return jsonify({
                "success": True,
                "message": "No signature found in email account",
                "signature": None,
            })

        # Extraire les versions texte et HTML de la signature
        signature_text = signature_data.get("text", "")
        signature_html = signature_data.get("html", "")

        # dry_run : la bibliothèque multi-signatures importe le contenu dans
        # son ÉDITEUR sans toucher la signature active du compte — la
        # persistance n'arrive qu'au Save de l'entrée (sinon un import puis
        # Annuler changerait silencieusement la signature de tous les envois).
        if request.args.get("dry_run") in ("1", "true"):
            return jsonify({
                "success": True,
                "message": "Signature fetched (dry run, not persisted)",
                "signature": signature_text,
                "signature_html": signature_html or None,
            })

        # Mettre à jour le compte avec les deux versions (JSON config)
        updates = {"signature": signature_text}
        if signature_html:
            updates["signature_html"] = signature_html

        updated = manager.update_account(account_id, **updates)

        if not updated:
            return jsonify({
                "success": False,
                "error": "Failed to update account signature",
            }), 500

        # Also store in SQLite DB (used by append_signature for drafts).
        # Audit e2e 2026-06-10 B-01 : même contrat que le PUT — un échec de
        # persist DB signifie que les envois n'utiliseront PAS la signature
        # affichée ; le signaler au lieu d'un success sec.
        signature_db_persisted = True
        try:
            with get_db_session() as session:
                db_acc = AccountRepository(session).get_by_email(account.email)
                if db_acc:
                    if signature_html:
                        db_acc.signature_html = signature_html
                    if signature_text:
                        db_acc.signature_text = signature_text
                    db_acc.signature_user_modified = False  # Voluntary re-import resets the flag
                    session.commit()
                else:
                    signature_db_persisted = False
        except Exception as db_err:
            signature_db_persisted = False
            logger.error(f"Could not store signature in DB: {db_err}")

        sync_payload = {
            "success": True,
            "message": "Signature synchronized successfully",
            "signature": signature_text,
            "signature_html": signature_html or None,
            "account": _account_to_dict(updated),
        }
        if not signature_db_persisted:
            sync_payload["signature_db_persisted"] = False
        return jsonify(sync_payload)

    except PermissionError as e:
        logger.warning(f"Permission error syncing signature for {account_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
        }), 403
    except Exception as e:
        logger.error(f"Error syncing signature for account {account_id}: {e}")
        return jsonify({
            "success": False,
            "error": f"Sync error: {str(e)}",
        }), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


@accounts_bp.route("/<account_id>/share-signature", methods=["POST"])
def share_signature(account_id: str):
    """
    Partage la signature d'un compte avec un collègue via son email Agentys.
    ---
    tags:
      - Accounts
    summary: Copie la signature vers le compte d'un collègue
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: string
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [target_email]
            properties:
              target_email:
                type: string
    responses:
      200:
        description: Signature partagée avec succès
      400:
        description: Données invalides
      404:
        description: Compte source ou cible introuvable
      500:
        description: Erreur lors du partage
    """
    if not _validate_account_id(account_id):
        return jsonify({"error": "Invalid account_id format"}), 400

    data = request.get_json()
    if not data or not data.get("target_email"):
        return jsonify({"error": "target_email requis"}), 400

    target_email = data["target_email"].strip().lower()
    if not EMAIL_PATTERN.match(target_email):
        return jsonify({"error": "Adresse email invalide"}), 400

    manager = get_account_manager()
    source_account = manager.get_account(account_id)
    if not source_account:
        return jsonify({"error": "Compte source introuvable"}), 404

    if not _check_account_ownership(source_account, _get_auth_user_id()):
        return jsonify({"error": "Access denied"}), 403

    # Récupérer la signature depuis la config du compte source
    source_signature = getattr(source_account, "signature", None) or ""
    source_signature_html = getattr(source_account, "signature_html", None) or ""

    # Chercher aussi dans la DB SQLite (source of truth pour append_signature)
    try:
        with get_db_session() as session:
            repo = AccountRepository(session)

            source_db = repo.get_by_email(source_account.email)
            if source_db:
                source_signature = source_db.signature_text or source_signature
                source_signature_html = source_db.signature_html or source_signature_html

            if not source_signature and not source_signature_html:
                return error_response(
                    "ACCOUNT_NO_SIGNATURE_TO_SHARE",
                    "No signature to share on this account",
                    400,
                )

            target_db = repo.get_by_email(target_email)
            if not target_db:
                return error_response(
                    "ACCOUNT_NO_TARGET_EMAIL",
                    f"No Agentys account found for {target_email}",
                    404,
                    context={"target_email": target_email},
                    extra={"not_found": True},
                )

            # Audit 2026-05-29: source ownership was checked but the TARGET was
            # resolved purely from the client-supplied email — any user could
            # inject arbitrary signature HTML into ANY other tenant's outgoing
            # mail (phishing/tracking pixel). Restrict to accounts owned by the
            # same user. Cross-user "share with a colleague" would need an
            # explicit opt-in/consent flow from the target, not a silent write.
            # Return the same not-found shape to avoid an existence oracle.
            if not _check_account_ownership(target_db, _get_auth_user_id()):
                return error_response(
                    "ACCOUNT_NO_TARGET_EMAIL",
                    f"No Agentys account found for {target_email}",
                    404,
                    context={"target_email": target_email},
                    extra={"not_found": True},
                )

            if source_signature_html:
                target_db.signature_html = source_signature_html
            if source_signature:
                target_db.signature_text = source_signature
            session.commit()
    except Exception as e:
        logger.error(f"Error sharing signature from {account_id} to {target_email}: {e}")
        return jsonify({"error": f"Erreur lors du partage : {str(e)}"}), 500

    # Mettre aussi à jour la config JSON du compte cible si trouvé dans le manager
    target_accounts = manager.get_all_accounts()
    for acc in target_accounts:
        if acc.email.lower() == target_email:
            updates = {}
            if source_signature:
                updates["signature"] = source_signature
            if source_signature_html:
                updates["signature_html"] = source_signature_html
            if updates:
                try:
                    manager.update_account(acc.id, **updates)
                except Exception:
                    pass
            break

    logger.info(f"[OK] Signature partagée de {source_account.email} vers {target_email}")
    return jsonify({
        "success": True,
        # FE constructs its own localized success toast — this field is
        # mostly diagnostic. Kept English to prevent French leakage.
        "message": f"Signature shared with {target_email}",
    })
