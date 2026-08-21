# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour Agentys — point d'entrée.

Ce module importe tous les sous-modules de routes et ré-exporte les symboles
nécessaires pour la compatibilité ascendante. Les routes sont définies dans :

- routes_helpers.py   — helpers partagés, Blueprint, middleware
- routes_health.py    — health, stats, init, ping
- routes_emails.py    — emails CRUD, actions, envoi
- routes_drafts.py    — drafts, refine, deep focus
- routes_learning.py  — followups, learning, costs, tasks
- routes_pending.py   — pending drafts
- routes_contacts.py  — contacts, relationships
- routes_misc.py      — compose, newsletters, memory, voice, reminders

IMPORTANT: Ne PAS définir de routes dans ce fichier. Toutes les routes
doivent être dans les sous-modules ci-dessus. Ce fichier ne sert que de
hub de ré-export pour la compatibilité ascendante.
"""

# ============================================================================
# Re-export api_bp + all symbols that external modules import from routes.py
# ============================================================================
# --- From routes_helpers (shared helpers, blueprint, middleware) ---
from .routes_helpers import (  # noqa: F401
    api_bp,
    API_VERSION,
    LegacyModuleLoader,
    _NO_ACCOUNT_SENTINEL,
    _account_id_cache,
    _email_cache,
    _email_cache_lock,
    _email_detail_cache,
    _email_detail_cache_lock,
    _evict_email_from_all_caches,
    _evict_sent_sqlite_cache,
    _fetch_conversation_history_for_contact,
    _filter_blocked_senders,
    _find_relevant_history_for_email,
    _get_authenticated_provider,
    _get_blocked_senders_set,
    _get_cached_email_detail,
    _get_cached_email_response,
    _get_container,
    _get_current_account_for_user,
    _get_email_by_id,
    _get_email_from_cache,
    _get_legacy_modules,
    _invalidate_folder_cache,
    _invalidate_label_batch_cache,
    _process_email_with_use_case,
    _rate_limited,
    _refresh_sent_cache_bg,
    _resolve_account_id_cached,
    _resolve_account_id_for_user,
    _set_cached_email_detail,
    _set_cached_email_response,
    _validate_email_id,
    require_json,
)

# --- From routes_emails (email routes + email-specific helpers) ---
from .routes_emails import (  # noqa: F401
    _auto_assign_labels_background,
    _get_email_labels,
    _get_pending_draft_email_ids,
    _labeling_progress,
    _start_background_sync,
)

# --- From routes_learning (learning routes + helpers) ---
from .routes_learning import (  # noqa: F401
    _extract_issues,
    _extract_improvements,
)

# --- From routes_misc (misc routes + helpers) ---
from .routes_misc import (  # noqa: F401
    _compute_intelligence_level,
)

# --- Re-export third-party symbols that tests patch via app.api.routes ---
from app.infrastructure.container import get_container  # noqa: F401
from app.infrastructure.thread_pool import submit_background  # noqa: F401
from app.db.database import get_db_session  # noqa: F401
from app.db.repositories.email_repository import EmailRepository  # noqa: F401
from app.db.models.email import Email  # noqa: F401

# ============================================================================
# Import all route sub-modules so their @api_bp.route() decorators register
# ============================================================================
from . import routes_health      # noqa: F401
from . import routes_emails      # noqa: F401
from . import routes_drafts      # noqa: F401
from . import routes_learning    # noqa: F401
from . import routes_pending     # noqa: F401
from . import routes_contacts    # noqa: F401
from . import routes_misc        # noqa: F401
