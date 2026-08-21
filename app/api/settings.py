# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les paramètres utilisateur.

Endpoints disponibles:
- GET /api/settings - Récupérer les paramètres actuels
- PATCH /api/settings - Mettre à jour les paramètres
"""

import logging
import os
import json
from pathlib import Path
from functools import wraps
from typing import Callable, Optional

from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)


SETTINGS_FILE = Path(os.environ.get("AGENTYS_SETTINGS_FILE", "data/settings.json"))

DEFAULT_SETTINGS = {
    "operation_mode": "controlled",
    "polling_interval_minutes": 5,
    "notifications_enabled": True,
    "working_hours_only": False,
    "working_hours_start": "09:00",
    "working_hours_end": "18:00",
    "auto_archive_action": True,
    "auto_empty_trash_30d": False,
    "auto_empty_spam_30d": False,
    "auto_delete_noise_30d": False,
    "hide_noise_from_inbox": True,
    "auto_reminder_on_commitment": False,
    "auto_cleanup_noise": True,
    "cleanup_noise_days": 7,
    "theme": "default",
    "ui_sounds_enabled": False,
    "undo_send_delay": 5,
    "auto_reply_enabled": False,
    "auto_reply_message": "",
    "auto_reply_start": "",
    "auto_reply_end": "",
    # Auto-transfert pendant absence
    "auto_transfer_enabled": False,
    "auto_transfer_email": "",
    # Batch API schedule (off-hours drafting at 50% discount)
    "batch_enabled": True,
    "batch_active_hours_start": "07:00",
    "batch_active_hours_end": "20:00",
    "batch_weekend_all_day": True,
    "batch_activity_timeout_min": 15,
    # Monthly recap
    "monthly_recap_email_enabled": True,
    "monthly_recap_email_sent_month": "",
    "monthly_recap_banner_month": "",
    "monthly_recap_banner_dismissed": False,
    # Deep Work mode — OFF by default. Both sub-modes start disabled so a
    # never-configured user has no focus blocks, no phantom calendar events
    # and no "Activé" badge until they explicitly turn one on.
    "deep_work_enabled": False,
    "deep_work_emails_enabled": False,
    "deep_work_work_enabled": False,
    "deep_work_check_slots": [
        {"start": "08:00", "duration": 30},
        {"start": "12:30", "duration": 30},
        {"start": "17:30", "duration": 30},
    ],
    "deep_work_vip_contacts": [],
    "deep_work_weekdays": [1, 2, 3, 4, 5],
    # Plages de travail personnel (blocs affichés dans l'agenda)
    "deep_work_personal_blocks": [],
    # format: [{"start": "09:00", "duration": 120, "label": "Travail personnel"}]
    # Spécialités (Expert Mode)
    "active_specialties": [],        # ["real-estate-qc", "legal-qc"]
    "specialty_activations": {},     # {"real-estate-qc": {"activated_at": "...", "status": "active"}}
    # Booking link (réponse automatique sans IA pour demandes de disponibilités)
    "booking_url": "",
}

VALID_OPERATION_MODES = {"magic", "controlled", "manual"}
# Seul "default" (Clarity) subsiste. Les thèmes "dark-luxury" et "futurist" ont
# été retirés : tout thème legacy persisté est coercé vers "default" au chargement
# côté frontend (useTheme.isThemeId), et un PATCH vers un thème retiré est rejeté ici.
VALID_THEMES = {"default"}


def _is_valid_time(val: str) -> bool:
    """Validate HH:MM time format (00:00-23:59)."""
    import re
    return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", val))


def _is_valid_email(val: str) -> bool:
    """Validate email address format."""
    import re
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", val))


def _is_valid_date(val: str) -> bool:
    """Validate YYYY-MM-DD date format."""
    import re
    return bool(re.match(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$", val))


def require_json(f: Callable) -> Callable:
    """Décorateur pour valider la présence d'un body JSON."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.get_json():
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


def _load_global_settings() -> dict:
    """Charge les paramètres globaux depuis le fichier JSON."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                return {**DEFAULT_SETTINGS, **settings}
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Error loading settings file: %s", e)
    return DEFAULT_SETTINGS.copy()


def _save_global_settings(settings: dict) -> bool:
    """Sauvegarde les paramètres globaux dans le fichier JSON (atomic write)."""
    try:
        import tempfile
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(SETTINGS_FILE.parent),
            suffix=".tmp",
            prefix="settings_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            tmp = Path(tmp_path)
            if os.name == "nt" and SETTINGS_FILE.exists():
                SETTINGS_FILE.unlink()
            tmp.rename(SETTINGS_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return True
    except (IOError, OSError) as e:
        logger.error("Error saving settings file: %s", e)
        return False


def _load_account_settings_overrides(account_id: int) -> dict:
    """Charge les overrides de settings per-compte depuis la DB."""
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            account = AccountRepository(session).get(account_id)
            if account and account.settings_json:
                return json.loads(account.settings_json)
    except Exception as e:
        logger.warning("Could not load per-account settings for account %d: %s", account_id, e)
    return {}


def _save_account_settings(settings: dict, account_id: int) -> bool:
    """Sauvegarde les settings per-compte dans la DB."""
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            account = AccountRepository(session).get(account_id)
            if account:
                account.settings_json = json.dumps(settings, ensure_ascii=False)
                session.commit()
                return True
        logger.warning("Account %d not found for settings save", account_id)
    except Exception as e:
        logger.error("Could not save per-account settings for account %d: %s", account_id, e)
    return False


def load_settings(account_id: Optional[int] = None) -> dict:
    """
    Charge les paramètres.

    Avec account_id : overrides per-compte (DB) mergés sur les defaults globaux.
    Sans account_id  : defaults globaux uniquement (data/settings.json).
    """
    base = _load_global_settings()
    if account_id and account_id > 0:
        overrides = _load_account_settings_overrides(account_id)
        if overrides:
            base.update(overrides)
    return base


def save_settings(settings: dict, account_id: Optional[int] = None) -> bool:
    """
    Sauvegarde les paramètres.

    Avec account_id : sauvegarde per-compte dans la DB.
    Sans account_id  : sauvegarde globale dans data/settings.json.
    """
    if account_id and account_id > 0:
        return _save_account_settings(settings, account_id)
    return _save_global_settings(settings)


def _get_current_account_id() -> Optional[int]:
    """Résout l'account_id courant pour les routes settings."""
    try:
        from app.api.routes_helpers import _resolve_account_id_cached
        aid = _resolve_account_id_cached()
        return aid if aid and aid > 0 else None
    except Exception:
        return None


@settings_bp.route("/settings", methods=["GET"])
def get_settings():
    """
    Récupère les paramètres utilisateur.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Paramètres actuels
        content:
          application/json:
            schema:
              type: object
              properties:
                operation_mode:
                  type: string
                  enum: [magic, controlled, manual]
                polling_interval_minutes:
                  type: integer
                notifications_enabled:
                  type: boolean
                working_hours_only:
                  type: boolean
                working_hours_start:
                  type: string
                working_hours_end:
                  type: string
    """
    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    return jsonify(settings), 200


@settings_bp.route("/settings", methods=["PATCH"])
@require_json
def update_settings():
    """
    Met à jour les paramètres utilisateur.
    ---
    tags:
      - Settings
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              operation_mode:
                type: string
                enum: [magic, controlled, manual]
              polling_interval_minutes:
                type: integer
                minimum: 1
                maximum: 60
              notifications_enabled:
                type: boolean
              working_hours_only:
                type: boolean
              working_hours_start:
                type: string
                pattern: "^[0-2][0-9]:[0-5][0-9]$"
              working_hours_end:
                type: string
                pattern: "^[0-2][0-9]:[0-5][0-9]$"
    responses:
      200:
        description: Paramètres mis à jour
        content:
          application/json:
            schema:
              type: object
              properties:
                success:
                  type: boolean
      400:
        description: Paramètres invalides
    """
    data = request.get_json()
    account_id = _get_current_account_id()

    # Audit 2026-05-30 (settings global-write leak): when an AUTHENTICATED
    # (JWT) caller has no resolved account yet — just-signed-up, hasn't run
    # the wizard — `_get_current_account_id()` returns None. Falling through
    # to `save_settings(..., account_id=None)` would write the shared global
    # `data/settings.json`, seeding every other tenant's defaults. Refuse with
    # ONBOARDING_REQUIRED (mirrors @account_scoped, account_scope.py:54-58).
    # Loopback/Tauri no-JWT callers are unaffected: they have no `g.auth_user`,
    # so they keep the legitimate global-settings write (local desktop mode).
    from flask import g as _g
    _auth_user = getattr(_g, "auth_user", None)
    if (account_id is None) and _auth_user and _auth_user.get("email"):
        return jsonify({
            "error": "Onboarding required",
            "code": "ONBOARDING_REQUIRED",
        }), 401

    current_settings = load_settings(account_id=account_id)

    # Audit 2026-04-25 (sub-report 01 MED-06): defensive belt-and-suspenders
    # to back the de-facto allow-list below. If any future caller refactors
    # this handler to use `current_settings.update(data)` directly, the
    # explicit denylist below will reject sensitive keys. Today's handler
    # is fine — every settable key has its own validated branch — but a
    # future copy-paste must not silently allow `admin_emails`, `api_key`,
    # `OAUTH_TOKEN_ENCRYPTION_KEY`, etc. to land here.
    _DENYLIST_KEYS = frozenset({
        "admin_emails",
        "api_key",
        "secret_key",
        "jwt_secret",
        "oauth_token_encryption_key",
        "encryption_key",
        "user_id",
        "owner_email",
        "is_admin",
    })
    if data and any(key.lower() in _DENYLIST_KEYS for key in data.keys()):
        return jsonify({"error": "Setting key not allowed"}), 400

    if "operation_mode" in data:
        mode = data["operation_mode"]
        if mode not in VALID_OPERATION_MODES:
            return jsonify({
                "error": f"Invalid operation_mode. Must be one of: {', '.join(VALID_OPERATION_MODES)}"
            }), 400
        current_settings["operation_mode"] = mode

    if "polling_interval_minutes" in data:
        interval = data["polling_interval_minutes"]
        if not isinstance(interval, int) or interval < 1 or interval > 60:
            return jsonify({
                "error": "polling_interval_minutes must be an integer between 1 and 60"
            }), 400
        current_settings["polling_interval_minutes"] = interval

    if "notifications_enabled" in data:
        current_settings["notifications_enabled"] = bool(data["notifications_enabled"])

    if "working_hours_only" in data:
        current_settings["working_hours_only"] = bool(data["working_hours_only"])

    if "working_hours_start" in data:
        val = data["working_hours_start"]
        if not isinstance(val, str) or not _is_valid_time(val):
            return jsonify({"error": "working_hours_start must be HH:MM format"}), 400
        current_settings["working_hours_start"] = val

    if "working_hours_end" in data:
        val = data["working_hours_end"]
        if not isinstance(val, str) or not _is_valid_time(val):
            return jsonify({"error": "working_hours_end must be HH:MM format"}), 400
        current_settings["working_hours_end"] = val

    if "auto_archive_action" in data:
        current_settings["auto_archive_action"] = bool(data["auto_archive_action"])

    if "auto_empty_trash_30d" in data:
        current_settings["auto_empty_trash_30d"] = bool(data["auto_empty_trash_30d"])

    if "auto_empty_spam_30d" in data:
        current_settings["auto_empty_spam_30d"] = bool(data["auto_empty_spam_30d"])

    if "auto_delete_noise_30d" in data:
        current_settings["auto_delete_noise_30d"] = bool(data["auto_delete_noise_30d"])

    if "hide_noise_from_inbox" in data:
        current_settings["hide_noise_from_inbox"] = bool(data["hide_noise_from_inbox"])

    if "auto_reminder_on_commitment" in data:
        current_settings["auto_reminder_on_commitment"] = bool(data["auto_reminder_on_commitment"])

    if "theme" in data:
        t = data["theme"]
        if t not in VALID_THEMES:
            return jsonify({
                "error": f"Invalid theme. Must be one of: {', '.join(VALID_THEMES)}"
            }), 400
        current_settings["theme"] = t

    if "ui_sounds_enabled" in data:
        current_settings["ui_sounds_enabled"] = bool(data["ui_sounds_enabled"])

    # undo_send_delay is now hardcoded to 15s in the frontend — ignore if sent

    if "auto_reply_enabled" in data:
        current_settings["auto_reply_enabled"] = bool(data["auto_reply_enabled"])

    if "auto_reply_message" in data:
        msg = data["auto_reply_message"]
        if not isinstance(msg, str) or len(msg) > 5000:
            return jsonify({"error": "auto_reply_message must be a string (max 5000 chars)"}), 400
        current_settings["auto_reply_message"] = msg

    if "auto_reply_start" in data:
        val = data["auto_reply_start"]
        if val and (not isinstance(val, str) or not _is_valid_date(val)):
            return jsonify({"error": "auto_reply_start must be YYYY-MM-DD format or empty"}), 400
        current_settings["auto_reply_start"] = val if val else ""

    if "auto_reply_end" in data:
        val = data["auto_reply_end"]
        if val and (not isinstance(val, str) or not _is_valid_date(val)):
            return jsonify({"error": "auto_reply_end must be YYYY-MM-DD format or empty"}), 400
        current_settings["auto_reply_end"] = val if val else ""

    # Cross-field validation: end date must be >= start date
    _start = current_settings.get("auto_reply_start", "")
    _end = current_settings.get("auto_reply_end", "")
    if _start and _end and _end < _start:
        return jsonify({"error": "auto_reply_end must be on or after auto_reply_start"}), 400

    # Auto-transfert settings
    if "auto_transfer_enabled" in data:
        current_settings["auto_transfer_enabled"] = bool(data["auto_transfer_enabled"])

    if "auto_transfer_email" in data:
        val = data["auto_transfer_email"]
        if not isinstance(val, str) or len(val) > 254:
            return jsonify({"error": "auto_transfer_email must be a string (max 254 chars)"}), 400
        val = val.strip().lower()
        if val and not _is_valid_email(val):
            return jsonify({"error": "auto_transfer_email must be a valid email address"}), 400
        current_settings["auto_transfer_email"] = val

    # Batch API schedule settings
    if "batch_enabled" in data:
        current_settings["batch_enabled"] = bool(data["batch_enabled"])

    if "batch_active_hours_start" in data:
        val = data["batch_active_hours_start"]
        if not isinstance(val, str) or not _is_valid_time(val):
            return jsonify({"error": "batch_active_hours_start must be HH:MM format"}), 400
        current_settings["batch_active_hours_start"] = val

    if "batch_active_hours_end" in data:
        val = data["batch_active_hours_end"]
        if not isinstance(val, str) or not _is_valid_time(val):
            return jsonify({"error": "batch_active_hours_end must be HH:MM format"}), 400
        current_settings["batch_active_hours_end"] = val

    if "batch_weekend_all_day" in data:
        current_settings["batch_weekend_all_day"] = bool(data["batch_weekend_all_day"])

    if "batch_activity_timeout_min" in data:
        val = data["batch_activity_timeout_min"]
        if not isinstance(val, int) or val < 0 or val > 120:
            return jsonify({"error": "batch_activity_timeout_min must be 0-120"}), 400
        current_settings["batch_activity_timeout_min"] = val

    # Monthly recap settings
    if "monthly_recap_email_enabled" in data:
        current_settings["monthly_recap_email_enabled"] = bool(data["monthly_recap_email_enabled"])

    if "monthly_recap_email_sent_month" in data:
        current_settings["monthly_recap_email_sent_month"] = str(data["monthly_recap_email_sent_month"])

    if "monthly_recap_banner_month" in data:
        current_settings["monthly_recap_banner_month"] = str(data["monthly_recap_banner_month"])

    if "monthly_recap_banner_dismissed" in data:
        current_settings["monthly_recap_banner_dismissed"] = bool(data["monthly_recap_banner_dismissed"])

    # Deep Work mode settings
    if "deep_work_enabled" in data:
        current_settings["deep_work_enabled"] = bool(data["deep_work_enabled"])

    if "deep_work_emails_enabled" in data:
        current_settings["deep_work_emails_enabled"] = bool(data["deep_work_emails_enabled"])

    if "deep_work_work_enabled" in data:
        current_settings["deep_work_work_enabled"] = bool(data["deep_work_work_enabled"])

    if "deep_work_check_slots" in data:
        val = data["deep_work_check_slots"]
        if not isinstance(val, list):
            return jsonify({"error": "deep_work_check_slots must be a list"}), 400
        cleaned_slots = []
        for slot in val[:10]:  # max 10 check windows
            if not isinstance(slot, dict):
                continue
            start = slot.get("start", "")
            duration = slot.get("duration", 30)
            if not isinstance(start, str) or not _is_valid_time(start):
                continue
            try:
                duration = max(15, min(120, int(duration)))
            except (TypeError, ValueError):
                continue
            cleaned_slots.append({"start": start, "duration": duration})
        current_settings["deep_work_check_slots"] = cleaned_slots

    if "deep_work_vip_contacts" in data:
        val = data["deep_work_vip_contacts"]
        if not isinstance(val, list):
            return jsonify({"error": "deep_work_vip_contacts must be a list"}), 400
        cleaned = [str(c).lower().strip() for c in val if isinstance(c, str) and c.strip()][:50]
        current_settings["deep_work_vip_contacts"] = cleaned

    if "deep_work_weekdays" in data:
        val = data["deep_work_weekdays"]
        if not isinstance(val, list):
            return jsonify({"error": "deep_work_weekdays must be a list of integers 1-7"}), 400
        days = [int(d) for d in val if isinstance(d, (int, float)) and 1 <= int(d) <= 7]
        current_settings["deep_work_weekdays"] = sorted(set(days))

    if "deep_work_personal_blocks" in data:
        val = data["deep_work_personal_blocks"]
        if not isinstance(val, list):
            return jsonify({"error": "deep_work_personal_blocks must be a list"}), 400
        cleaned_blocks = []
        for block in val[:10]:  # max 10 personal blocks
            if not isinstance(block, dict):
                continue
            start = block.get("start", "")
            duration = block.get("duration", 60)
            label = block.get("label", "Travail personnel")
            if not isinstance(start, str) or not _is_valid_time(start):
                continue
            duration = max(15, min(480, int(duration)))
            label = str(label)[:100] if label else "Travail personnel"
            cleaned_blocks.append({"start": start, "duration": duration, "label": label})
        current_settings["deep_work_personal_blocks"] = cleaned_blocks

    # Specialty settings
    if "active_specialties" in data:
        val = data["active_specialties"]
        if not isinstance(val, list):
            return jsonify({"error": "active_specialties must be a list"}), 400
        cleaned = [str(s).strip() for s in val if isinstance(s, str) and s.strip()]
        current_settings["active_specialties"] = cleaned

    if "specialty_activations" in data:
        val = data["specialty_activations"]
        if not isinstance(val, dict):
            return jsonify({"error": "specialty_activations must be an object"}), 400
        current_settings["specialty_activations"] = val

    if "booking_url" in data:
        val = data["booking_url"]
        if not isinstance(val, str) or len(val) > 500:
            return jsonify({"error": "booking_url must be a string (max 500 chars)"}), 400
        val = val.strip()
        if val and not (val.startswith("http://") or val.startswith("https://")):
            return jsonify({"error": "booking_url must start with http:// or https://"}), 400
        current_settings["booking_url"] = val

    if save_settings(current_settings, account_id=account_id):
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Failed to save settings"}), 500
