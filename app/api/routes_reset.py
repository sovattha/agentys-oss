"""
API Blueprint pour la réinitialisation complète des données Agentys.

Endpoint:
  POST /api/dev/reset-all-data — Supprime toutes les données utilisateur

Usage développeur uniquement. Protégé par :
  - Vérification localhost (loopback)
  - Confirmation explicite requise dans le body
"""

import logging
import shutil
from pathlib import Path
from typing import Any

from flask import Blueprint, request, jsonify

from sqlalchemy import text as sql_text

from app.config import DATA_DIR
from app.db.database import get_db_session
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

reset_bp = Blueprint("reset", __name__)

CONFIRMATION_TOKEN = "RESET_ALL_DATA"

# Tables SQLAlchemy ORM (nouvelle base via get_db_session)
SQLALCHEMY_TABLES = [
    "active_batches",
    "batch_queue",
    "calendar_suggestions",
    "commitments",
    "contact_groups",
    "followups",
    "scheduled_emails",
    "snippet_shares",
    "snippets",
    "email_labels",
    "faq_agent_logs",
    "pending_actions",
    "relationship_overrides",
    "onboarding_results",
    "knowledge_entries",
    "drafts",
    "contacts",
    "emails",
    "accounts",
]

# Tables legacy (ancienne base via app.infrastructure.database)
LEGACY_TABLES = [
    "processed_emails",
    "draft_history",
    "sent_emails",
    "learned_patterns",
    "prompt_adjustments",
    "audit_log",
    "cost_tracking",
    "extracted_tasks",
    "user_activity",
    "revenue_events",
    "referrals",
]

# Fichiers JSON dans data/
# IMPORTANT: oauth_tokens.json DOIT être dans cette liste. Sinon, après un reset,
# le GmailAdapter/OutlookAdapter lit les tokens chiffrés de ce fichier et
# re-crée automatiquement un compte en DB au premier sync — ce qui annule
# silencieusement la moitié du reset. Ne pas retirer.
DATA_DIR_FILES = [
    "email_accounts.json",
    "pkce_verifiers.json",
    "oauth_tokens.json",
    "history.json",
    ".processed_emails.json",
    "wizard_config.json",
    "contact_groups.json",
    # Backups laissés par les imports one-shot JSON→DB (migrations 039/040) —
    # un full reset doit aussi purger ces copies, sinon elles seraient
    # ré-importées et ressusciteraient les données effacées. NB snippets.json
    # n'était PAS purgé par le reset pré-migration (trou comblé ici).
    "contact_groups.json.imported",
    "snippets.json",
    "snippets.json.imported",
    "snippet_shares.json",
    "snippet_shares.json.imported",
    "followups.json",
    "followups.json.imported",
    "calendar_suggestions.json",
    "calendar_suggestions.json.imported",
    # Side-SQLite absorbée par la DB principale (migration 043) — purger le
    # fichier legacy et son backup d'import, sinon ré-import à la résurrection.
    "scheduled_emails.db",
    "scheduled_emails.db.imported",
    "batch_queue.db",
    "batch_queue.db.imported",
    "commitments.db",
    "commitments.db.imported",
    # Audit 2026-05-26: the pending-draft store moved from ~/.agentys/ to
    # DATA_DIR (co-located with reminders.json). A full reset must purge it
    # at its NEW home — otherwise stale snoozed/pending drafts survive the
    # wipe. (Still listed in HOME_AGENTYS_FILES too, to clean the legacy
    # leftover left behind by the one-time migration copy.)
    "pending_drafts.json",
]

# Sous-répertoires de data/ à vider
DATA_DIR_SUBDIRS = [
    "labels",
    "history",
    "inputs",
    "outputs",
    "discord",
    "telegram",
    "fine_tuning",
    "marketplace",
    "mobile",
    "learning",
    "realtime_edit",
    "followups",
]

# Fichiers dans ~/.agentys/
HOME_AGENTYS_FILES = [
    "draft_cache.json",
    "draft_corrections.json",
    "draft_quality.db",
    "learning_refresh_state.json",
    # Legacy location only (the live store now lives in DATA_DIR — see
    # DATA_DIR_FILES). Kept here to purge the migration leftover on reset.
    "pending_drafts.json",
]


def _purge_sqlalchemy_tables() -> dict[str, Any]:
    """Vide toutes les tables SQLAlchemy ORM (FK-safe order)."""
    results: dict[str, int] = {}
    try:
        with get_db_session() as session:
            for table_name in SQLALCHEMY_TABLES:
                count = session.execute(
                    sql_text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar() or 0
                if count > 0:
                    session.execute(
                        sql_text(f"DELETE FROM {table_name}")
                    )
                results[table_name] = count
            session.commit()
        return {"success": True, "deleted": results}
    except Exception as e:
        logger.error(f"[RESET] Erreur purge SQLAlchemy: {e}")
        return {"success": False, "error": str(e)}


def _purge_legacy_tables() -> dict[str, Any]:
    """Vide toutes les tables de la base legacy."""
    results: dict[str, int] = {}
    try:
        from app.infrastructure.database import db
        for table_name in LEGACY_TABLES:
            try:
                row = db.fetchone(f"SELECT COUNT(*) as cnt FROM {table_name}")
                count = row["cnt"] if row else 0
                if count > 0:
                    db.execute(f"DELETE FROM {table_name}")
                results[table_name] = count
            except Exception:
                results[table_name] = -1
        db.commit()
        return {"success": True, "deleted": results}
    except Exception as e:
        logger.error(f"[RESET] Erreur purge legacy: {e}")
        return {"success": False, "error": str(e)}


def _purge_data_dir_files() -> dict[str, Any]:
    """Supprime/réinitialise les fichiers JSON dans data/."""
    results: dict[str, str] = {}
    for filename in DATA_DIR_FILES:
        filepath = DATA_DIR / filename
        if filepath.exists():
            filepath.unlink()
            results[filename] = "deleted"
        else:
            results[filename] = "not_found"

    for subdir_name in DATA_DIR_SUBDIRS:
        subdir = DATA_DIR / subdir_name
        if subdir.exists() and subdir.is_dir():
            file_count = sum(1 for f in subdir.iterdir() if f.is_file())
            shutil.rmtree(subdir)
            subdir.mkdir(parents=True, exist_ok=True)
            results[f"{subdir_name}/"] = f"cleared ({file_count} files)"
        else:
            results[f"{subdir_name}/"] = "not_found"

    return {"success": True, "files": results}


def _purge_home_agentys() -> dict[str, Any]:
    """Supprime les fichiers de cache dans ~/.agentys/."""
    home_dir = Path.home() / ".agentys"
    results: dict[str, str] = {}

    if not home_dir.exists():
        return {"success": True, "files": {}, "note": "~/.agentys/ not found"}

    for filename in HOME_AGENTYS_FILES:
        filepath = home_dir / filename
        if filepath.exists():
            filepath.unlink()
            results[filename] = "deleted"
        else:
            results[filename] = "not_found"

    return {"success": True, "files": results}


def _invalidate_caches() -> dict[str, Any]:
    """Invalide les caches mémoire du backend."""
    invalidated = []
    try:
        from app.services.cache_manager import get_cache_manager
        cache = get_cache_manager()
        cache.clear_all()
        invalidated.append("cache_manager")
    except Exception as e:
        logger.warning(f"[RESET] cache_manager clear failed: {e}")

    try:
        from app.api.routes import _invalidate_folder_cache
        _invalidate_folder_cache()
        invalidated.append("folder_cache")
    except Exception as e:
        logger.warning(f"[RESET] folder_cache clear failed: {e}")

    try:
        from app.infrastructure.container import get_container
        container = get_container()
        container._label_store = None
        container._wizard_config_store = None
        container._device_store = None
        container._marketplace_agent_store = None
        container._agent_pack_store = None
        container._agent_installation_store = None
        container._agent_review_store = None
        container._publisher_store = None
        container._user_correction_store = None
        container._user_feedback_store = None
        container._correction_pattern_store = None
        container._improvement_model_store = None
        container._fine_tuning_session_store = None
        container._mobile_session_store = None
        container._mobile_sync_store = None
        container._mobile_draft_action_store = None
        container._mobile_analytics_store = None
        container._mobile_preferences_store = None
        container._mobile_config_store = None
        container._learning_pattern_store = None
        container._adjustment_store = None
        container._processed_emails_tracker = None
        container._processed_drafts_tracker = None
        container._analytics = None
        container._pending_draft_store = None
        container._realtime_edit_store = None
        container._commitment_tracker = None
        invalidated.append("container_stores")
    except Exception as e:
        logger.warning(f"[RESET] container reset failed: {e}")

    return {"success": True, "invalidated": invalidated}


@reset_bp.route("/reset-all-data", methods=["POST"])
def reset_all_data():
    """
    Supprime TOUTES les données utilisateur d'Agentys.

    Requiert :
    - Appel depuis localhost uniquement
    - Body JSON : {"confirm": "RESET_ALL_DATA"}

    Supprime :
    - Comptes email connectés + tokens OAuth
    - Emails en cache (SQLite)
    - Contacts, brouillons, knowledge base
    - Labels, règles de labellisation
    - Historique d'apprentissage (patterns, corrections, prompts)
    - Caches de brouillons (~/.agentys/)
    - Analytics, audit logs, cost tracking
    - Données marketplace, mobile, fine-tuning
    """
    from app.api.auth import is_trusted_loopback
    from app.api._auth_helpers import is_production

    # Audit 2026-04-25 (sub-report 01 CRIT-01): /reset-all-data was reachable
    # via the webhooks SSRF chain (loopback request from inside the container
    # passed _is_loopback). Now that webhooks_bp validates outbound URLs we've
    # closed the chain, but defense in depth: refuse outright in production.
    if is_production():
        return jsonify({"error": "Endpoint disabled in production"}), 404

    if not is_trusted_loopback():
        return error_response("ADMIN_DEV_ONLY", "Reserved for local development", 403)

    body = request.get_json(silent=True) or {}
    if body.get("confirm") != CONFIRMATION_TOKEN:
        return error_response(
            "CONFIRMATION_REQUIRED",
            "Confirmation required",
            400,
            extra={"usage": {"confirm": CONFIRMATION_TOKEN}},
        )

    logger.warning("[RESET] === RÉINITIALISATION COMPLÈTE DES DONNÉES ===")

    report: dict[str, Any] = {}

    report["sqlalchemy"] = _purge_sqlalchemy_tables()
    report["legacy"] = _purge_legacy_tables()
    report["data_files"] = _purge_data_dir_files()
    report["home_agentys"] = _purge_home_agentys()
    report["caches"] = _invalidate_caches()

    all_ok = all(
        section.get("success", False)
        for section in report.values()
    )

    logger.warning(f"[RESET] Terminé — succès global: {all_ok}")

    return jsonify({
        "success": all_ok,
        "message": "All data has been deleted" if all_ok
                   else "Réinitialisation partielle — voir le rapport",
        "report": report,
    }), 200 if all_ok else 207
