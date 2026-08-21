# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les Email Labels.

Système de labellisation multi-labels:
- Labels par défaut: Action, Waiting, FYI, Noise
- Labels personnalisés
- Règles de labellisation (manuelles et apprises)

Endpoints disponibles:
- GET /api/labels - Liste tous les labels
- POST /api/labels - Crée un nouveau label
- GET /api/labels/<name> - Récupère un label
- PUT /api/labels/<name> - Met à jour un label
- DELETE /api/labels/<name> - Supprime un label (pas les defaults)
- GET /api/labels/rules - Liste toutes les règles
- POST /api/labels/rules - Crée une nouvelle règle
- DELETE /api/labels/rules/<rule_id> - Supprime une règle
- POST /api/labels/vip - Ajoute un expéditeur VIP
- GET /api/labels/vip - Liste les expéditeurs VIP
- POST /api/labels/assign - Assigne des labels à un email
- POST /api/labels/learn - Apprend d'une correction utilisateur
- POST /api/labels/classify-all - Lance l'auto-labeling sur tous les emails
- GET /api/labels/rules.md - Documentation markdown des règles
"""

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# Bounded thread pool for background tasks (max 4 concurrent)
_background_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="labels-bg")
import time
import uuid
from functools import wraps
from typing import Any, Callable, Optional, Tuple

from flask import Blueprint, jsonify, request

from app.api.utils.errors import error_response
from app.domain.entities.email_labels import (
    EmailLabel,
    LabelAssignment,
    LabelingRule,
    DEFAULT_LABEL_NAMES,
)
from app.domain.entities import Email
from app.infrastructure.container import get_container

logger = logging.getLogger(__name__)

labels_bp = Blueprint("labels", __name__)


# =========================================================================
# Regression eval corpus
# =========================================================================
#
# Every user correction is appended (best-effort) to this JSONL file so
# ``scripts/eval_label_corrections.py`` can replay them through the
# classifier whenever the prompt or rules change. A correction-driven
# eval set is the single best defence against silent prompt regressions —
# fixing one persona while breaking two others (cf. the "effet balancier"
# règle d'or in docs/onboarding-prompt-engineering.md).
#
# The path can be overridden via ``AGENTYS_LABEL_EVAL_PATH`` for tests.
# Empty path disables persistence entirely (no error logged).

_EVAL_CORPUS_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tasks", "label_corrections.jsonl",
)
_EVAL_CORPUS_LOCK = threading.Lock()


def _eval_corpus_path() -> str:
    return os.environ.get("AGENTYS_LABEL_EVAL_PATH", _EVAL_CORPUS_DEFAULT)


def _persist_label_correction_for_eval(
    *,
    account_id: Any,
    email_id: str,
    sender: str,
    subject: str,
    body: str,
    old_default: Optional[str],
    new_default: Optional[str],
) -> None:
    """Append one correction line to the regression eval corpus.

    Best-effort and non-blocking — caller must catch exceptions. PII trimming:
    body is truncated to 2 KB so the corpus stays diff-friendly and doesn't
    accidentally collect entire long emails. ``account_id`` is opaque (a hash
    in production); no real names or email addresses are normalised here.

    Schema (one JSON object per line):
        {
          "ts": "2026-05-04T...",
          "account_id": "<opaque>",
          "email_id": "...",
          "sender": "...",
          "subject": "...",
          "body": "<truncated>",
          "old_default": "Noise"|null,
          "new_default": "Action"|null
        }
    """
    path = _eval_corpus_path()
    if not path:
        return
    if old_default == new_default:
        # Custom-label tweak, not a default-label correction — skip.
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account_id": str(account_id) if account_id is not None else "",
        "email_id": email_id,
        "sender": sender,
        "subject": subject,
        "body": (body or "")[:2048],
        "old_default": old_default,
        "new_default": new_default,
    }
    line = json.dumps(record, ensure_ascii=False)
    with _EVAL_CORPUS_LOCK:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.debug("eval corpus write failed: %s", e)


def _get_active_user_email() -> str:
    """Get the email address of the JWT/loopback user (for CC detection).

    ISO-13 fix: previously returned `accounts[0].email` (alphabetical
    first), which made CC-detection during labelling treat user A as if
    they were user B. Now scoped to the actual caller via the JWT-aware
    helper.
    """
    try:
        from app.api.routes_helpers import _get_current_account_for_user
        account = _get_current_account_for_user()
        if account and getattr(account, "email", ""):
            return account.email or ""
    except Exception:
        pass
    return ""


def _get_provider_for_db_account(account_id: int):
    """Return the provider for this DB account, fail-closed for web requests."""
    try:
        from app.api import routes_helpers as _rh
        from app.providers.factory import get_email_provider, get_pooled_provider

        oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
        if oauth_account_id:
            return get_pooled_provider(account_id=oauth_account_id)
        if _rh._is_web_request_context():
            return None
        return get_email_provider()
    except Exception as exc:
        logger.warning("Could not resolve provider for account %s: %s", account_id, exc)
        return None


# ===========================================================================
# INPUT VALIDATION
# ===========================================================================

MAX_NAME_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 200
MAX_EMAIL_LENGTH = 254
MAX_CONDITION_LENGTH = 500

# Simple TTL cache for label list, keyed per account so the opt-in
# isolation that container.get_label_store(account_id=...) added with
# ISO-02 actually isolates readers. Pre-fix (cf. 2026-04-25 audit C-1)
# the cache was a single global slot, so the first caller's labels
# bled into every subsequent reader for 60 s — fine while routes still
# read the global store, but a latent bug for any route that opts in.
_labels_cache: dict[Optional[int], tuple[list, float]] = {}
_LABELS_CACHE_TTL = 60.0  # seconds

# Inbox label→email-id scan cache. `_collect_inbox_label_email_ids()` runs an
# UNBOUNDED `SELECT email_id FROM emails` inbox scan + a full `email_labels`
# JOIN + 2–3 in-memory store iterations on EVERY call. It is called on every
# `/api/labels/counts` poll (header-tab unread badges — both unread_only
# variants) AND on every label-filtered email-list open. We cache the
# (label→ids, inbox_total) result briefly, keyed by (account_id, unread_only).
# The TTL is intentionally short because background classification mutates
# labels asynchronously; user-driven mutations additionally call
# `_invalidate_labels_cache()`, which drops this cache immediately so a manual
# relabel/reassign feels instant.
_inbox_label_ids_cache: dict[
    tuple[Optional[int], bool], tuple[dict[str, set[str]], int, float]
] = {}
try:
    _INBOX_LABEL_IDS_CACHE_TTL = float(
        os.environ.get("INBOX_LABEL_IDS_CACHE_TTL_SECONDS", "10") or 10
    )
except (TypeError, ValueError):
    _INBOX_LABEL_IDS_CACHE_TTL = 10.0


def _get_labels_cached(account_id: Optional[int] = None):
    """Return labels for `account_id` from cache (60s TTL) or disk.

    `account_id=None` keeps the legacy global-store path; passing an
    explicit id routes through the per-account store at
    `data/labels/<account_id>/`.
    """
    now = time.monotonic()
    entry = _labels_cache.get(account_id)
    if entry is not None and (now - entry[1]) < _LABELS_CACHE_TTL:
        return entry[0]
    container = get_container()
    if account_id is not None:
        store = container.get_label_store(account_id=account_id)
    else:
        store = container.get_label_store()
    labels = store.get_labels()
    _labels_cache[account_id] = (labels, now)
    return labels


def _invalidate_labels_cache(account_id: Optional[int] = None) -> None:
    """Invalidate the label cache after a mutation.

    `account_id=None` clears every account's entry (matches the global
    behaviour mutations had pre-fix); passing an id only drops that
    account's slot.
    """
    if account_id is None:
        _labels_cache.clear()
        _inbox_label_ids_cache.clear()
    else:
        _labels_cache.pop(account_id, None)
        _inbox_label_ids_cache.pop((account_id, False), None)
        _inbox_label_ids_cache.pop((account_id, True), None)

# Safe pattern (alphanumeric + accented/unicode letters, spaces, underscore, dash)
SAFE_NAME_PATTERN = re.compile(r'^[\w\s\-]+$', re.UNICODE)
SAFE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


# Domaines personnels exclus de l'agrégation (trop variés pour une règle domaine)
_PERSONAL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr",
    "live.com", "live.fr", "msn.com",
    "yahoo.com", "yahoo.fr", "yahoo.ca",
    "protonmail.com", "proton.me", "pm.me",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "aol.fr",
})


def _maybe_aggregate_domain_rule(sender: str, store) -> None:
    """
    Si 3+ règles individuelles @domain → même label, crée une règle domaine agrégée.
    Priority 45 (entre learned=40 et user=50+).
    Exclut les domaines personnels.
    """
    if not sender or "@" not in sender:
        return

    domain = sender.lower().split("@")[-1]
    if domain in _PERSONAL_DOMAINS:
        return

    try:
        all_rules = store.get_rules()
        # Find learned rules (priority <= 40) that match this domain via sender condition
        domain_rules = {}
        for rule in all_rules:
            if rule.condition_type != "sender":
                continue
            if rule.priority > 44:
                continue  # Skip user rules and existing aggregated rules
            val = rule.condition_value.lower()
            if f"@{domain}" in val or val.endswith(f"@{domain}"):
                label = rule.label_name
                domain_rules.setdefault(label, []).append(rule)

        for label, rules in domain_rules.items():
            if len(rules) < 3:
                continue

            # Check if an aggregated domain rule already exists
            existing_agg = any(
                r.condition_type == "sender"
                and r.condition_value.lower() == f"@{domain}"
                and r.label_name == label
                and r.priority == 45
                for r in all_rules
            )
            if existing_agg:
                continue

            import uuid
            from datetime import datetime
            agg_rule = LabelingRule(
                rule_id=str(uuid.uuid4()),
                label_name=label,
                condition_type="sender",
                condition_value=f"@{domain}",
                priority=45,
                learned_from=f"aggregated:{domain}",
                confidence=0.90,
                created_at=datetime.now().isoformat(),
            )
            if store.add_rule(agg_rule):
                logger.info(
                    f"[LabelAggregation] Created domain rule: @{domain} → {label} "
                    f"(aggregated from {len(rules)} individual rules)"
                )
    except Exception as e:
        logger.debug(f"[LabelAggregation] Domain aggregation failed: {e}")


# ===========================================================================
# Auto-disable: precision tracking for learned rules
# ===========================================================================

PRECISION_THRESHOLD = 0.50   # Désactiver en dessous de 50% de précision
MIN_MATCHES_FOR_DISABLE = 5  # Minimum 5 matches avant évaluation


def _increment_rule_corrections(store, rule_ids: list) -> None:
    """Incrémente le compteur de corrections pour les règles qui ont mené à un mauvais label."""
    if not rule_ids:
        return
    rules = store.get_rules()
    rule_id_set = set(rule_ids)
    changed = False
    for rule in rules:
        if rule.rule_id in rule_id_set:
            rule.corrections = getattr(rule, 'corrections', 0) + 1
            changed = True
    if changed:
        store._save_rules(rules)


def _maybe_disable_bad_rules(store, rule_ids: list) -> None:
    """Auto-désactive les règles avec une précision inférieure au seuil après assez de matches."""
    if not rule_ids:
        return
    rules = store.get_rules()
    rule_id_set = set(rule_ids)
    changed = False
    for rule in rules:
        if rule.rule_id not in rule_id_set:
            continue
        if not getattr(rule, 'is_active', True):
            continue
        total = getattr(rule, 'total_matches', 0)
        corrections = getattr(rule, 'corrections', 0)
        if total < MIN_MATCHES_FOR_DISABLE:
            continue
        precision = (total - corrections) / total if total > 0 else 0
        if precision < PRECISION_THRESHOLD:
            rule.is_active = False
            rule.disabled_reason = f"low_precision:{precision:.0%}"
            changed = True
            logger.info(
                f"[AutoDisable] Règle {rule.rule_id} ({rule.condition_type}="
                f"'{rule.condition_value}' -> {rule.label_name}) désactivée: "
                f"précision {precision:.0%} ({corrections}/{total} corrections)"
            )
    if changed:
        store._save_rules(rules)


def _batch_get_email_data(email_ids: list) -> dict:
    """Batch-load email sender/subject/body depuis SQLite pour le matching de règles.

    Returns:
        {email_id: {"sender": ..., "subject": ..., "body": ..., "recipients": [], "is_cc": False}}
    """
    if not email_ids:
        return {}
    result = {}
    try:
        from app.db.database import get_db_session
        from sqlalchemy import text as _text
        with get_db_session() as session:
            # Process in chunks of 500 to avoid SQLite variable limits
            for i in range(0, len(email_ids), 500):
                chunk = email_ids[i:i + 500]
                placeholders = ",".join(f":id{j}" for j in range(len(chunk)))
                params = {f"id{j}": eid for j, eid in enumerate(chunk)}
                rows = session.execute(
                    _text(f"SELECT email_id, sender, subject, body_text "
                          f"FROM emails WHERE email_id IN ({placeholders})"),
                    params
                ).fetchall()
                for row in rows:
                    result[row[0]] = {
                        "sender": (row[1] or "").lower(),
                        "subject": (row[2] or "").lower(),
                        "body": (row[3] or "").lower()[:2000],
                        "recipients": [],
                        "is_cc": False,
                    }
    except Exception as e:
        logger.debug(f"[RulePropagation] Batch email data lookup failed: {e}")
    return result


def _apply_rules_to_existing_emails(rules, account_id: Optional[int] = None):
    """Apply new rules to all cached assignments (up to 10K) using SQLite email data.

    Much faster than IMAP-based approach: no network calls, works offline.
    Skips user-corrected assignments.

    Args:
        rules: A single LabelingRule or a list of LabelingRule objects.
        account_id: Optional account ID for per-account LabelStore isolation.
    """
    if not isinstance(rules, list):
        rules = [rules]
    try:
        container = get_container()
        label_store = container.get_label_store(account_id=account_id)
        all_assignments = label_store.get_assignments(limit=10000)

        # Batch-load email data from SQLite
        email_ids = [a.email_id for a in all_assignments if a.assigned_by != "user"]
        email_data_map = _batch_get_email_data(email_ids)

        updated = 0
        for assignment in all_assignments:
            if assignment.assigned_by == "user":
                continue
            email_data = email_data_map.get(assignment.email_id)
            if not email_data:
                continue

            changed = False
            for rule in rules:
                if not getattr(rule, 'is_active', True):
                    continue
                if rule.label_name in assignment.labels:
                    continue
                if rule.matches(email_data):
                    if rule.label_name in DEFAULT_LABEL_NAMES:
                        if assignment.assigned_by != "user":
                            assignment.set_default_label(
                                rule.label_name, rule.confidence,
                                f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                            changed = True
                    else:
                        assignment.add_custom_label(
                            rule.label_name, rule.confidence,
                            f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                        changed = True
                    if rule.rule_id not in assignment.matched_rule_ids:
                        assignment.matched_rule_ids.append(rule.rule_id)

            if changed:
                assignment._rebuild_labels()
                label_store.save_assignment(assignment)
                updated += 1

        logger.info(f"[RulePropagation] Applied rules to cached assignments: "
                     f"{updated}/{len(all_assignments)} updated")
    except Exception:
        logger.exception("Error applying rules to cached assignments")


def validate_label_name(name: str) -> Tuple[bool, Optional[str]]:
    """Validate label name."""
    if not name or not name.strip():
        return False, "Label name is required"
    if len(name) > MAX_NAME_LENGTH:
        return False, f"Label name exceeds max length ({MAX_NAME_LENGTH})"
    if not SAFE_NAME_PATTERN.match(name):
        return False, "Label name contains invalid characters"
    return True, None


def validate_email_address(email: str) -> Tuple[bool, Optional[str]]:
    """Validate email address format."""
    if not email or not email.strip():
        return False, "Email address is required"
    if len(email) > MAX_EMAIL_LENGTH:
        return False, f"Email address exceeds max length ({MAX_EMAIL_LENGTH})"
    # Basic email pattern
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return False, "Invalid email address format"
    return True, None


def require_json(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.get_json():
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


# ===========================================================================
# LABELS ENDPOINTS
# ===========================================================================

@labels_bp.route("", methods=["GET"])
def list_labels():
    """
    Liste tous les labels disponibles.

    Returns:
        JSON avec la liste des labels.
    """
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (deep audit 2026-06-02 D, CWE-639): reject the -1 pre-OAuth
        # sentinel so pre-OAuth / transient-resolution-failure callers can't read
        # or mutate the shared data/labels/-1 bucket (cross-tenant pooling).
        # Mirrors the rules/VIP handlers already guarded in this file.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        labels = _get_labels_cached(account_id=account_id)

        return jsonify({
            "labels": [label.to_dict() for label in labels],
            "count": len(labels),
        })
    except Exception as e:
        logger.exception("Error listing labels")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("", methods=["POST"])
@require_json
def create_label():
    """
    Crée un nouveau label personnalisé.

    Body:
        - name: Nom du label (requis)
        - color: Couleur hex (optionnel)
        - description: Description (optionnel)

    Returns:
        Le label créé.
    """
    try:
        # Stability (audit 2026-05-19 STAB-02): use silent=True so a missing /
        # non-JSON body returns a clean 400 instead of letting werkzeug raise
        # inside the try — where the broad `except Exception` below would
        # re-wrap it as a 500 and leak the werkzeug error string.
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400
        name = data.get("name", "").strip()

        # Validation
        valid, error = validate_label_name(name)
        if not valid:
            return jsonify({"error": error}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (deep audit 2026-06-02 D, CWE-639): reject the -1 pre-OAuth
        # sentinel so writes can't pool into the shared data/labels/-1 bucket.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401

        container = get_container()
        store = container.get_label_store(account_id=account_id)

        label = EmailLabel(
            name=name,
            color=data.get("color"),
            description=data.get("description", ""),
            is_default=False,
            is_favorite=data.get("is_favorite", False),
            is_project=data.get("is_project", False),
            project_name=data.get("project_name"),
            project_number=data.get("project_number"),
            project_abbreviation=data.get("project_abbreviation"),
            subject_prefix=data.get("subject_prefix"),
            ai_prompt=data.get("ai_prompt"),
        )

        success = store.add_label(label)
        if not success:
            return jsonify({"error": "Label already exists"}), 409
        _invalidate_labels_cache(account_id=account_id)

        return jsonify({
            "label": label.to_dict(),
            "message": "Label created successfully",
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Don't leak the raw exception string to the client (STAB-02); the
        # full traceback is already captured by logger.exception above.
        logger.exception("Error creating label")
        return jsonify({"error": "An internal error occurred"}), 500


# ===========================================================================
# RULES ENDPOINTS
# ===========================================================================

@labels_bp.route("/rules", methods=["GET"])
def list_rules():
    """Liste toutes les règles de labellisation."""
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject the -1 pre-OAuth sentinel so
        # callers without their own account can't pool into a shared data/labels/-1/ store.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        rules = store.get_rules()

        return jsonify({
            "rules": [rule.to_dict() for rule in rules],
            "count": len(rules),
        })

    except Exception as e:
        logger.exception("Error listing rules")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules/stats", methods=["GET"])
def rules_stats():
    """Statistiques de précision par règle et globales."""
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        rules = store.get_rules()

        rule_stats = []
        total_matches = 0
        total_corrections = 0
        active_count = 0
        disabled_count = 0

        for r in rules:
            tm = getattr(r, 'total_matches', 0)
            corr = getattr(r, 'corrections', 0)
            precision = round((tm - corr) / tm * 100) if tm > 0 else None
            is_active = getattr(r, 'is_active', True)

            total_matches += tm
            total_corrections += corr
            if is_active:
                active_count += 1
            else:
                disabled_count += 1

            rule_stats.append({
                "rule_id": r.rule_id,
                "label_name": r.label_name,
                "condition_type": r.condition_type,
                "condition_value": r.condition_value,
                "total_matches": tm,
                "corrections": corr,
                "precision": precision,
                "is_active": is_active,
                "disabled_reason": getattr(r, 'disabled_reason', None),
            })

        global_precision = (round((total_matches - total_corrections) / total_matches * 100)
                            if total_matches > 0 else None)

        return jsonify({
            "rules": rule_stats,
            "global": {
                "total_rules": len(rules),
                "active_rules": active_count,
                "disabled_rules": disabled_count,
                "total_matches": total_matches,
                "total_corrections": total_corrections,
                "precision": global_precision,
            }
        })
    except Exception as e:
        logger.exception("Error getting rule stats")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/cache-stats", methods=["GET"])
def cache_stats():
    """
    Template fingerprint cache metrics — use this to verify the cost-control
    pipeline is actually paying off.

    Response shape:
        {
          "entries": int,            # persisted cache entries
          "max_entries": int,        # LRU eviction threshold
          "ttl_days": int,           # entry expiry
          "lifetime_hits": int,      # cumulative hits across all entries (persisted)
          "session_hits": int,       # hits since this process started
          "session_misses": int,     # misses since this process started
          "session_llm_writes": int, # LLM classifications stored this session
          "session_lookups": int,    # hits + misses
          "hit_rate": float,         # session_hits / session_lookups (0..1)
          "llm_calls_saved": int     # same as session_hits, named for humans
        }

    A healthy cache shows hit_rate climbing toward ~0.5-0.7 after a few days of
    use (most inboxes have 5-10 recurring templates that dominate the volume).
    A stuck-near-zero hit_rate means either the inbox is all unique emails
    (unlikely) or the fingerprint keys aren't colliding — which could be a
    normalisation bug worth investigating.
    """
    try:
        container = get_container()
        cache = container.get_template_label_cache()
        return jsonify(cache.stats())
    except Exception as e:
        logger.exception("Error getting cache stats")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules", methods=["POST"])
@require_json
def create_rule():
    """
    Crée une nouvelle règle de labellisation.

    Body:
        - label_name: Nom du label à assigner (requis)
        - condition_type: Type de condition (sender, subject, body) (requis)
        - condition_value: Valeur/pattern de la condition (requis)
        - priority: Priorité de la règle (optionnel, default 50)
        - confidence: Confiance 0-1 (optionnel, default 1.0)

    Returns:
        La règle créée.
    """
    try:
        data = request.get_json()

        label_name = data.get("label_name", "").strip()
        condition_type = data.get("condition_type", "").strip()
        condition_value = data.get("condition_value", "").strip()

        # Validation
        if not label_name:
            return jsonify({"error": "label_name is required"}), 400
        if condition_type not in ["sender", "subject", "body", "cc", "recipient"]:
            return jsonify({"error": "Invalid condition_type"}), 400
        if not condition_value:
            return jsonify({"error": "condition_value is required"}), 400
        if len(condition_value) > MAX_CONDITION_LENGTH:
            return jsonify({"error": "condition_value too long"}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401

        container = get_container()
        store = container.get_label_store(account_id=account_id)

        # Vérifier que le label existe
        if not store.get_label(label_name):
            return jsonify({"error": f"Label '{label_name}' not found"}), 404

        rule = LabelingRule(
            rule_id=str(uuid.uuid4())[:8],
            label_name=label_name,
            condition_type=condition_type,
            condition_value=condition_value,
            priority=int(data.get("priority", 50)),
            confidence=float(data.get("confidence", 1.0)),
        )

        success = store.add_rule(rule)
        if not success:
            return jsonify({
                "message": "Similar rule already exists, confidence updated if higher"
            }), 200

        # Apply new rule to existing emails in background
        _bg_account_id = account_id
        _background_executor.submit(_apply_rules_to_existing_emails, [rule], _bg_account_id)

        return jsonify({
            "rule": rule.to_dict(),
            "message": "Rule created successfully",
        }), 201

    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error creating rule")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules/<rule_id>", methods=["PUT"])
@require_json
def update_rule(rule_id: str):
    """Met à jour une règle de labellisation."""
    try:
        if not SAFE_ID_PATTERN.match(rule_id):
            return jsonify({"error": "Invalid rule_id format"}), 400

        data = request.get_json()
        updates = {}
        if "label_name" in data:
            updates["label_name"] = data["label_name"]
        if "condition_type" in data:
            if data["condition_type"] not in ["sender", "subject", "body", "cc", "recipient"]:
                return jsonify({"error": "Invalid condition_type"}), 400
            updates["condition_type"] = data["condition_type"]
        if "condition_value" in data:
            val = data["condition_value"].strip()
            if not val:
                return jsonify({"error": "condition_value cannot be empty"}), 400
            if len(val) > MAX_CONDITION_LENGTH:
                return jsonify({"error": "condition_value too long"}), 400
            updates["condition_value"] = val

        if not updates:
            return jsonify({"error": "No fields to update"}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        label_store = container.get_label_store(account_id=account_id)
        success = label_store.update_rule(rule_id, updates)

        if not success:
            return jsonify({"error": "Rule not found"}), 404

        # Reload the updated rule
        rules = label_store.get_rules()
        updated = next((r for r in rules if r.rule_id == rule_id), None)

        return jsonify({
            "rule": updated.to_dict() if updated else {},
            "message": "Rule updated successfully",
        })

    except Exception as e:
        logger.exception("Error updating rule")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules/<rule_id>", methods=["DELETE"])
def delete_rule(rule_id: str):
    """Supprime une règle de labellisation."""
    try:
        if not SAFE_ID_PATTERN.match(rule_id):
            return jsonify({"error": "Invalid rule_id format"}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        success = store.delete_rule(rule_id)

        if not success:
            return jsonify({"error": "Rule not found"}), 404

        return jsonify({"message": "Rule deleted successfully"})

    except Exception as e:
        logger.exception("Error deleting rule")
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# VIP SENDERS ENDPOINTS
# ===========================================================================

@labels_bp.route("/vip", methods=["GET"])
def list_vip_senders():
    """Liste les expéditeurs VIP (haute importance)."""
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel — VIP
        # senders are real email addresses; don't pool tenants into data/labels/-1/.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        vips = store.get_vip_senders()

        return jsonify({
            "vip_senders": vips,
            "count": len(vips),
        })

    except Exception as e:
        logger.exception("Error listing VIP senders")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/vip", methods=["POST"])
@require_json
def add_vip_sender():
    """
    Ajoute un expéditeur VIP.

    Body:
        - email: Adresse email de l'expéditeur (requis)
        - name: Nom de l'expéditeur (optionnel)

    Returns:
        La règle VIP créée.
    """
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()

        valid, error = validate_email_address(email)
        if not valid:
            return jsonify({"error": error}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (audit 2026-05-29, CWE-639): reject -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        rules = store.add_vip_sender(email, data.get("name", ""))

        # Defensive: ensure rules is always a list
        if not isinstance(rules, list):
            rules = [rules]

        # Apply VIP rules to existing emails in background
        _bg_account_id = account_id
        if rules:
            _background_executor.submit(_apply_rules_to_existing_emails, rules, _bg_account_id)

        return jsonify({
            "rules": [r.to_dict() for r in rules],
            "message": f"VIP sender '{email}' added successfully (Action + VIP)",
        }), 201

    except Exception as e:
        logger.exception("Error adding VIP sender")
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# LABELING ENDPOINTS
# ===========================================================================

@labels_bp.route("/assign", methods=["POST"])
@require_json
def assign_labels():
    """
    Assigne automatiquement des labels à un email.

    Body:
        - email_id: ID de l'email (requis)
        - sender: Expéditeur (requis)
        - subject: Sujet (requis)
        - body: Corps du message (requis)
        - to: Destinataires (optionnel)
        - cc: Destinataires en copie (optionnel)
        - user_email: Email de l'utilisateur pour détecter CC (optionnel)

    Returns:
        L'assignation de labels.
    """
    try:
        data = request.get_json()

        # Validation
        email_id = data.get("email_id", "").strip()
        if not email_id:
            return jsonify({"error": "email_id is required"}), 400
        if len(email_id) > 256:
            return jsonify({"error": "email_id too long"}), 400

        body = data.get("body", "")
        if len(body) > 50000:
            return jsonify({"error": "body exceeds 50KB limit"}), 400
        subject = data.get("subject", "")
        if len(subject) > 1000:
            return jsonify({"error": "subject exceeds limit"}), 400

        # Créer l'email — validate sender format for Email entity
        import re as _re
        sender_raw = (data.get("sender") or "")[:500].strip()
        if not sender_raw or not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", sender_raw):
            # Extract email from "Name <addr@x.y>" format, or use fallback
            match = _re.search(r"<([^@\s]+@[^@\s]+\.[^@\s]+)>", sender_raw)
            sender_raw = match.group(1) if match else "unknown@unknown.invalid"

        email = Email(
            id=email_id,
            sender=sender_raw,
            subject=subject,
            body=body,
        )

        # Ajouter les champs optionnels
        if "to" in data:
            email.to = data["to"]
        if "cc" in data:
            email.cc = data["cc"]

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        container = get_container()
        user_email = data.get("user_email", "")
        use_case = container.get_label_email_use_case(
            user_email=user_email, account_id=account_id if account_id > 0 else None,
        )

        # Contact floor: pass sender_is_real_contact flag so the pipeline can
        # skip the LLM fallback and default to FYI for known contacts.
        _raw_meta = {}
        try:
            from app.api.routes_helpers import sender_is_real_contact
            _raw_meta["sender_is_real_contact"] = sender_is_real_contact(account_id, sender_raw)
        except Exception:
            pass

        assignment = use_case.execute(email, raw_metadata=_raw_meta)

        # Sauvegarder l'assignation
        store = container.get_label_store(account_id=account_id)
        store.save_assignment(assignment)

        # Invalidate in-memory email + label batch caches so next fetch returns fresh labels
        try:
            from app.api.routes import _email_cache, _email_cache_lock, _invalidate_label_batch_cache
            with _email_cache_lock:
                _email_cache.clear()
            _invalidate_label_batch_cache()
        except Exception:
            pass
        _invalidate_labels_cache(account_id=account_id)

        return jsonify({
            "assignment": assignment.to_dict(),
            "labels": assignment.labels,
        })

    except Exception:
        logger.exception("Error assigning labels")
        return jsonify({"error": "Label assignment failed"}), 500


@labels_bp.route("/learn", methods=["POST"])
@require_json
def learn_from_correction():
    """
    Apprend de nouvelles règles à partir d'une correction utilisateur.

    Body:
        - email_id: ID de l'email (requis)
        - sender: Expéditeur (requis)
        - subject: Sujet (requis)
        - body: Corps du message (requis)
        - old_labels: Labels assignés par l'IA (requis)
        - new_labels: Labels choisis par l'utilisateur (requis)

    Returns:
        Les nouvelles règles apprises.
    """
    try:
        data = request.get_json()

        email_id = data.get("email_id", "").strip()
        if not email_id:
            return jsonify({"error": "email_id is required"}), 400

        old_labels = data.get("old_labels", [])
        new_labels = data.get("new_labels", [])

        if not isinstance(old_labels, list) or not isinstance(new_labels, list):
            return jsonify({"error": "old_labels and new_labels must be arrays"}), 400

        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()

        # Validate that all custom labels exist in the label list
        known_labels = {lbl.name for lbl in _get_labels_cached(account_id=account_id)}
        unknown = [lbl for lbl in new_labels if lbl not in DEFAULT_LABEL_NAMES and lbl not in known_labels]
        if unknown:
            return jsonify({"error": f"Unknown labels: {', '.join(unknown)}. Create them first."}), 400

        # Créer l'email
        email = Email(
            id=email_id,
            sender=data.get("sender", ""),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
        )

        container = get_container()
        use_case = container.get_learn_labeling_rule_use_case()
        store = container.get_label_store(account_id=account_id)

        # Sauvegarder l'assignation IMMÉDIATEMENT (avant l'appel LLM)
        # pour éviter qu'un refresh WebSocket ne restaure l'ancien label.
        # Separate default vs custom labels for proper structure.
        existing = store.get_assignment(email_id)
        assignment = LabelAssignment(
            email_id=email_id,
            assigned_by="user",
        )

        # Preserve existing custom labels when only changing default,
        # and preserve existing default when only toggling a custom.
        if existing:
            # Start with existing state
            assignment.default_label = existing.default_label
            assignment.custom_labels = list(existing.custom_labels)
            # Copy over confidence/reason data
            assignment.confidences = dict(existing.confidences)
            assignment.reasons = dict(existing.reasons)

        # Apply the new labels from the user correction
        new_defaults = [lbl for lbl in new_labels if lbl in DEFAULT_LABEL_NAMES]
        new_customs = [lbl for lbl in new_labels if lbl not in DEFAULT_LABEL_NAMES]

        # If user chose a new default label, replace it
        if new_defaults:
            assignment.set_default_label(new_defaults[0], 1.0, "User correction")
        elif not any(lbl in DEFAULT_LABEL_NAMES for lbl in new_labels):
            # User didn't specify a default → keep existing
            pass

        # Sync custom labels: add new ones, remove ones not in new_labels
        # that were previously there
        old_customs = [lbl for lbl in old_labels if lbl not in DEFAULT_LABEL_NAMES]
        for cl in new_customs:
            if cl not in assignment.custom_labels:
                assignment.add_custom_label(cl, 1.0, "User correction")
        for cl in old_customs:
            if cl not in new_customs:
                assignment.remove_custom_label(cl)

        assignment._rebuild_labels()
        store.save_assignment(assignment)

        # Invalidate the template-label cache for this email's fingerprint.
        # If the LLM previously classified (sender_domain, subject_template,
        # body_opening) as label X and the user is now correcting to Y, we
        # don't want the next email with the same fingerprint to reuse the
        # stale X. Invalidating here forces a fresh LLM call on the next
        # matching template — which in turn feeds the corrected label back
        # into the cache once it becomes the frequent classification.
        try:
            tpl_cache = container.get_template_label_cache()
            # Scope by account_id so user A's correction only invalidates
            # user A's cached template — without this, two users sharing a
            # cache file would over-invalidate each other.
            fp = tpl_cache.fingerprint(
                data.get("sender", ""),
                data.get("subject", ""),
                data.get("body", ""),
                scope=str(account_id) if account_id is not None else "",
            )
            tpl_cache.invalidate(fp)
        except Exception as _inv_err:
            logger.debug("template cache invalidation suppressed: %s", _inv_err)

        # Track corrections on rules that caused the wrong label (auto-disable)
        old_default = existing.default_label if existing else None
        old_matched_rule_ids = getattr(existing, 'matched_rule_ids', []) if existing else []
        new_default_label = new_defaults[0] if new_defaults else None
        if (old_matched_rule_ids and old_default and new_default_label
                and old_default != new_default_label):
            _increment_rule_corrections(store, old_matched_rule_ids)
            _maybe_disable_bad_rules(store, old_matched_rule_ids)

        # Update sender reputation: invalidate old + record corrected classification
        try:
            from app.infrastructure.sender_reputation_store import get_reputation_store
            rep_store = get_reputation_store()
            sender_email = data.get("sender", "")
            rep_store.invalidate_sender(sender_email)
            new_default = assignment.default_label
            if new_default and sender_email:
                rep_store.record_classification(
                    sender=sender_email,
                    label=new_default,
                    source="user_correction",
                )
        except Exception:
            pass

        # Persist this correction to the regression eval corpus. The corpus is
        # a JSONL file used by ``scripts/eval_label_corrections.py`` to compare
        # before/after accuracy whenever the prompt or rules change. Best-effort
        # only — never block a user correction on a telemetry write failure.
        try:
            _persist_label_correction_for_eval(
                account_id=account_id,
                email_id=email_id,
                sender=data.get("sender", ""),
                subject=data.get("subject", ""),
                body=data.get("body", ""),
                old_default=old_default,
                new_default=assignment.default_label,
            )
        except Exception as _eval_err:
            logger.debug("eval corpus append suppressed: %s", _eval_err)

        # Re-apply all existing custom label rules to this email
        # so it gets proper custom labels (e.g. VIP) after manual reclassification
        all_rules = store.get_rules()
        email_data = {
            "sender": data.get("sender", "").lower(),
            "subject": data.get("subject", "").lower(),
            "body": data.get("body", "").lower()[:2000],
            "recipients": data.get("recipients", []),
            "is_cc": data.get("is_cc", False),
        }
        reclass_changed = False
        for rule in all_rules:
            if rule.label_name not in assignment.labels and rule.matches(email_data):
                if rule.label_name in DEFAULT_LABEL_NAMES:
                    # Don't override user's explicit default choice
                    pass
                else:
                    assignment.add_custom_label(
                        rule.label_name, rule.confidence,
                        f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                    reclass_changed = True
        if reclass_changed:
            assignment._rebuild_labels()
            store.save_assignment(assignment)

        # Apprendre les règles (appel LLM, peut prendre plusieurs secondes)
        reason = data.get("reason", "")
        learned_rules = []
        try:
            learned_rules = use_case.execute(email, old_labels, new_labels, reason=reason)
        except Exception as e:
            logger.warning("[LearnRule] Rule learning failed for email=%s: %s", email_id, e)

        # Sauvegarder les règles apprises
        saved_rules = []
        saved_rule_objects = []
        for rule in learned_rules:
            if store.add_rule(rule):
                saved_rules.append(rule.to_dict())
                saved_rule_objects.append(rule)

        if saved_rules:
            logger.info(
                "[LearnRule] Saved %d rules for email=%s: %s",
                len(saved_rules), email_id,
                [(r["condition_type"], r["condition_value"], r["label_name"]) for r in saved_rules],
            )
        else:
            logger.info("[LearnRule] No rules generated for email=%s", email_id)

        # Apply learned rules to other existing emails in background
        _bg_account_id = account_id
        if saved_rule_objects:
            _background_executor.submit(_apply_rules_to_existing_emails, saved_rule_objects, _bg_account_id)

        # Try to aggregate domain rules (3+ corrections @domain → same label = domain rule)
        sender_email = data.get("sender", "")
        _maybe_aggregate_domain_rule(sender_email, store)

        # Invalidate in-memory caches BEFORE WebSocket emit
        # so frontend re-fetch gets fresh data
        try:
            from app.api.routes import _email_cache, _email_cache_lock, _invalidate_label_batch_cache
            with _email_cache_lock:
                _email_cache.clear()
            _invalidate_label_batch_cache()
        except Exception:
            pass
        _invalidate_labels_cache(account_id=account_id)

        # Notify learning coordinator of the label correction.
        # Audit 2026-05-29: previously forwarded the CLIENT-supplied
        # data["account_id"]/data["user_email"], which let an authenticated
        # tenant inject a label-corrected event into another tenant's private
        # WebSocket room and trigger a knowledge-base rebuild on their account.
        # Always use the JWT-resolved identity (account_id from line 1079 +
        # g.auth_user email); ignore the body fields entirely. Non-positive
        # account → None so the coordinator's truthiness guard skips emit/refresh.
        try:
            from flask import g as _g
            from app.learning_refresh import get_refresh_coordinator
            _auth = getattr(_g, "auth_user", None) or {}
            _jwt_email = (_auth.get("email") or "").strip() or None
            coordinator = get_refresh_coordinator()
            coordinator.on_label_corrected(
                email_id=email_id,
                old_label=old_labels[0] if old_labels else "",
                new_label=new_labels[0] if new_labels else "",
                account_id=account_id if isinstance(account_id, int) and account_id > 0 else None,
                user_email=_jwt_email,
            )
        except Exception as e:
            logger.warning("[LearnRule] WebSocket emit failed for email=%s: %s", email_id, e)

        # Auto-prune stale/disabled rules periodically
        try:
            store.prune_inactive_rules()
        except Exception:
            pass

        return jsonify({
            "learned_rules": saved_rules,
            "rules_count": len(saved_rules),
            "message": f"Learned {len(saved_rules)} new rules from correction",
            "final_labels": [
                {
                    "name": lbl,
                    "color": next((lb.color for lb in store.get_labels() if lb.name == lbl), "#888"),
                    "confidence": assignment.confidences.get(lbl, 1.0),
                }
                for lbl in assignment.labels
            ],
        })

    except Exception as e:
        logger.exception("Error learning from correction")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules/prune", methods=["POST"])
def prune_rules():
    """Supprime les règles inactives ou obsolètes."""
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        container = get_container()
        store = container.get_label_store(account_id=account_id)
        pruned = store.prune_inactive_rules(max_age_days=90)
        return jsonify({"pruned": pruned, "message": f"Pruned {pruned} stale rules"})
    except Exception as e:
        logger.exception("Error pruning rules")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/rules.md", methods=["GET"])
def get_rules_markdown():
    """Retourne la documentation markdown des règles apprises."""
    try:
        container = get_container()
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        store = container.get_label_store(account_id=account_id)
        content = store.get_rules_markdown()

        return content, 200, {"Content-Type": "text/markdown; charset=utf-8"}

    except Exception as e:
        logger.exception("Error getting rules markdown")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/assignments/<email_id>", methods=["GET"])
def get_assignment(email_id: str):
    """Récupère l'assignation de labels pour un email.

    ISO-07 fix (2026-04-24): the route was in `_PUBLIC_ENDPOINTS` and the
    handler did `store.get_assignment(email_id)` with no scope, so any
    caller could enumerate IMAP / Gmail thread IDs to pull another user's
    label assignments (VIP, Noise, custom tags). The route is now behind
    the auth guard AND the handler verifies the email belongs to the
    caller's account.
    """
    try:
        if not email_id or len(email_id) > 100:
            return jsonify({"error": "Invalid email_id"}), 400

        # Scope check: the email must belong to the caller's account.
        from app.api.routes_helpers import (
            _resolve_account_id_for_user,
            _NO_ACCOUNT_SENTINEL,
        )
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "No active account"}), 401

        try:
            from app.db.database import get_db_session
            from sqlalchemy import text as _text
            with get_db_session() as session:
                row = session.execute(
                    _text(
                        "SELECT 1 FROM emails "
                        "WHERE email_id = :eid AND account_id = :aid LIMIT 1"
                    ),
                    {"eid": email_id, "aid": account_id},
                ).scalar()
                if not row:
                    # Don't disclose whether the email exists in another
                    # account — same shape as "no assignment".
                    return jsonify({"error": "Assignment not found"}), 404
        except Exception as exc:
            logger.warning(
                "Scope check failed for /labels/assignments/%s: %s",
                email_id, exc,
            )
            return jsonify({"error": "Assignment not found"}), 404

        container = get_container()
        store = container.get_label_store(account_id=account_id)
        assignment = store.get_assignment(email_id)

        if not assignment:
            return jsonify({"error": "Assignment not found"}), 404

        return jsonify({"assignment": assignment.to_dict()})

    except Exception as e:
        logger.exception("Error getting assignment")
        return jsonify({"error": str(e)}), 500


def _add_label_count(
    label_email_ids: dict[str, set[str]],
    email_id: str,
    label_name: str,
) -> None:
    """Track one email/label pair once, even if multiple stores report it."""
    if not email_id or not label_name:
        return
    label_email_ids.setdefault(str(label_name), set()).add(str(email_id))


def _count_assignments_from_store(
    label_email_ids: dict[str, set[str]],
    assigned_email_ids: set[str],
    store: Any,
    inbox_ids: set[str],
) -> None:
    """Merge counts from a LabelStore-like object using explicit email IDs."""
    assignments = store.get_assignments_batch(list(inbox_ids))
    if not isinstance(assignments, dict):
        return
    for email_id, assignment in assignments.items():
        email_id_str = str(email_id)
        if email_id_str not in inbox_ids or email_id_str in assigned_email_ids:
            continue
        labels = list(getattr(assignment, "labels", []) or [])
        if not labels:
            continue
        assigned_email_ids.add(email_id_str)
        for label_name in labels:
            _add_label_count(label_email_ids, email_id_str, label_name)


def _collect_inbox_label_email_ids(
    account_id: int,
    *,
    unread_only: bool = False,
) -> tuple[dict[str, set[str]], int]:
    """Cached wrapper over :func:`_collect_inbox_label_email_ids_uncached`.

    See ``_inbox_label_ids_cache`` for why this is cached. Returns the cached
    ``(label→ids, inbox_total)`` while fresh. Both callers treat the result as
    read-only (``/api/labels/counts`` does ``len(ids)`` per label; the email
    list does ``set(ids.get(name))``), so returning the shared objects without
    copying is safe — matching ``_get_labels_cached``'s no-copy contract.
    """
    cache_key = (account_id, unread_only)
    now = time.monotonic()
    entry = _inbox_label_ids_cache.get(cache_key)
    if entry is not None and (now - entry[2]) < _INBOX_LABEL_IDS_CACHE_TTL:
        return entry[0], entry[1]
    label_email_ids, inbox_total = _collect_inbox_label_email_ids_uncached(
        account_id, unread_only=unread_only
    )
    _inbox_label_ids_cache[cache_key] = (label_email_ids, inbox_total, now)
    return label_email_ids, inbox_total


def _collect_inbox_label_email_ids_uncached(
    account_id: int,
    *,
    unread_only: bool = False,
) -> tuple[dict[str, set[str]], int]:
    """Return inbox-scoped email IDs grouped by label across all label stores.

    When ``unread_only`` is True, the inbox scope is restricted to unread
    emails (``is_read = false``). The header tabs use that variant for
    Gmail-style unread badges; onboarding distribution and training stats
    pass the default and still see the full inbox.
    """
    from app.db.database import get_db_session
    from sqlalchemy import text

    inbox_filter = (
        "WHERE account_id = :aid AND is_sent = :is_sent "
        "AND (folder = 'inbox' OR folder IS NULL)"
    )
    join_filter = (
        "WHERE e.account_id = :aid AND e.is_sent = :is_sent "
        "AND (e.folder = 'inbox' OR e.folder IS NULL)"
    )
    params = {"aid": account_id, "is_sent": False}
    if unread_only:
        inbox_filter += " AND is_read = :is_read"
        join_filter += " AND e.is_read = :is_read"
        params["is_read"] = False

    with get_db_session() as session:
        rows = session.execute(
            text(f"SELECT email_id FROM emails {inbox_filter}"),
            params,
        ).fetchall()
        inbox_ids = {str(r[0]) for r in rows if r[0]}

        try:
            sql_label_rows = session.execute(
                text(
                    "SELECT el.email_id, el.label_name "
                    "FROM email_labels el "
                    "JOIN emails e ON e.email_id = el.email_id "
                    f"AND e.account_id = el.account_id {join_filter}"
                ),
                params,
            ).fetchall()
        except Exception as exc:
            logger.debug("SQL label count mirror unavailable: %s", exc)
            sql_label_rows = []

    label_email_ids: dict[str, set[str]] = {}
    assigned_email_ids: set[str] = set()
    container = get_container()
    account_store = None

    # One canonical assignment per email. New per-account JSON wins, then SQL
    # mirror, then legacy global JSON for emails not migrated yet.
    try:
        account_store = container.get_label_store(account_id=account_id)
        _count_assignments_from_store(
            label_email_ids,
            assigned_email_ids,
            account_store,
            inbox_ids,
        )
    except Exception as exc:
        logger.debug("Per-account label count store unavailable: %s", exc)

    sql_labels_by_email: dict[str, list[str]] = {}
    for row in sql_label_rows:
        email_id = str(row[0])
        if email_id not in inbox_ids or email_id in assigned_email_ids:
            continue
        sql_labels_by_email.setdefault(email_id, []).append(str(row[1]))
    for email_id, labels in sql_labels_by_email.items():
        if not labels:
            continue
        assigned_email_ids.add(email_id)
        for label_name in labels:
            _add_label_count(label_email_ids, email_id, label_name)

    try:
        global_store = container.get_label_store()
        if global_store is not account_store:
            _count_assignments_from_store(
                label_email_ids,
                assigned_email_ids,
                global_store,
                inbox_ids,
            )
    except Exception as exc:
        logger.debug("Legacy label count store unavailable: %s", exc)

    return label_email_ids, len(inbox_ids)


def _get_inbox_label_email_ids(account_id: int, label_name: str) -> set[str]:
    """Return the same inbox-scoped label IDs used by `/api/labels/counts`."""
    label_email_ids, _total = _collect_inbox_label_email_ids(account_id)
    return set(label_email_ids.get(label_name, set()))


def _get_inbox_label_counts(
    account_id: int,
    *,
    unread_only: bool = False,
) -> tuple[dict[str, int], int]:
    """Return inbox-scoped label counts for both legacy and per-account stores."""
    label_email_ids, total = _collect_inbox_label_email_ids(
        account_id, unread_only=unread_only,
    )
    counts = {label_name: len(email_ids) for label_name, email_ids in label_email_ids.items()}
    return counts, total


@labels_bp.route("/counts", methods=["GET"])
def get_label_counts():
    """
    Retourne le nombre d'emails par label pour l'inbox du compte courant.

    Source de vérité fusionnée : store per-account, store global legacy et
    miroir SQL `email_labels`. Les trois ont existé en production selon le
    chemin d'écriture utilisé ; agréger une seule source peut laisser Bruit
    sans compteur alors que les lignes affichent bien le label.

    Le scope inbox (`folder='inbox' OR folder IS NULL`) reproduit le
    contrat de `EmailRepository.get_by_account` pour rester cohérent
    avec ce que la liste d'emails affiche.

    Query params:
        unread_only: when truthy ("1", "true", "yes"), restrict the
            scope to unread emails (``is_read = 0``). Used by the header
            tabs (Inbox/Action/FYI/Noise/…) to show Gmail-style unread
            badges. Other callers (onboarding distribution, training
            settings) omit the flag and get total counts unchanged.
    """
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user

        account_id = _resolve_account_id_for_user()
        if account_id is None or account_id <= 0:
            return jsonify({"error": "No active account"}), 401

        unread_only = request.args.get("unread_only", "").strip().lower() in {
            "1", "true", "yes",
        }

        counts, total = _get_inbox_label_counts(account_id, unread_only=unread_only)

        # `total` = unique inbox emails. `sum(counts.values())` sur-compterait
        # les emails ayant à la fois un label par défaut et un label projet.
        return jsonify({
            "counts": counts,
            "total": total,
        })

    except Exception as e:
        logger.exception("Error getting label counts")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/emails/<label_name>", methods=["GET"])
def get_emails_by_label(label_name: str):
    """
    Retourne les IDs d'emails ayant un label donné.

    ISO-08 fix (2026-04-24): the route was in `_PUBLIC_ENDPOINTS`. The
    underlying `LabelStore.get_emails_by_label` falls back to a global
    JSON cache when no account context is available, exposing every
    user's tagged email IDs. The route is now behind the auth guard, and
    we resolve email_ids by joining `email_labels` against `emails` for
    the caller's account.

    Returns:
        JSON avec la liste des email_ids (account-scoped).
    """
    try:
        valid, error = validate_label_name(label_name)
        if not valid:
            return jsonify({"error": error}), 400

        from app.api.routes_helpers import (
            _resolve_account_id_for_user,
            _NO_ACCOUNT_SENTINEL,
        )
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "No active account"}), 401

        # Account-scoped query: join email_labels with the caller's
        # account_id directly. We DO NOT fall back to the JSON cache
        # because that branch is global and leaks across users.
        email_ids: list[str] = []
        try:
            from app.db.database import get_db_session
            from sqlalchemy import text as _text
            with get_db_session() as session:
                rows = session.execute(
                    _text(
                        "SELECT DISTINCT email_id FROM email_labels "
                        "WHERE label_name = :lbl AND account_id = :aid"
                    ),
                    {"lbl": label_name, "aid": account_id},
                ).fetchall()
                email_ids = [str(r[0]) for r in rows]
        except Exception as exc:
            logger.warning(
                "[ISO-08] SQL emails-by-label failed for label=%s account=%s: %s",
                label_name, account_id, exc,
            )

        return jsonify({
            "label": label_name,
            "email_ids": email_ids,
            "count": len(email_ids),
        })

    except Exception as e:
        logger.exception("Error getting emails by label")
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# CLASSIFY-ALL ENDPOINT
# ===========================================================================

@labels_bp.route("/classify-all", methods=["POST"])
def classify_all_emails():
    """
    Lance l'auto-labeling pour tous les emails sans labels.

    Accepts optional JSON body with:
        force (bool): If true, re-classify all emails, overwriting AI
            assignments but preserving user corrections (assigned_by == 'user').

    Returns:
        JSON avec le nombre d'emails envoyés en labeling.
    """

    provider = None
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        container = get_container()
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        label_store = container.get_label_store(account_id=account_id)

        # Check for force flag
        force = False
        if request.is_json and request.get_json(silent=True):
            force = request.get_json(silent=True).get("force", False)

        provider = _get_provider_for_db_account(account_id)
        if provider is None:
            return jsonify({"error": "No email provider for account"}), 503

        # Récupérer les emails (200 pour couvrir tout l'inbox)
        emails = provider.get_messages(limit=200)

        # Disconnect IMAP immediately after fetching
        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        # Filtrer selon le mode
        emails_to_label = []
        skipped_user = 0
        custom_updated = 0

        # Collect custom label rules to apply to user-corrected emails
        all_rules = label_store.get_rules()
        custom_rules = [r for r in all_rules if r.label_name not in DEFAULT_LABEL_NAMES]

        for email in emails:
            email_id = str(getattr(email, 'id', ''))
            if not email_id:
                continue
            existing = label_store.get_assignment(email_id)
            if existing:
                if force:
                    if existing.assigned_by == "user":
                        # User-corrected: preserve default label, but apply new custom rules
                        if custom_rules:
                            from app.application.label_email import LabelEmailUseCase
                            _is_cc = LabelEmailUseCase.detect_cc(email, _get_active_user_email())
                            email_data = {
                                "sender": getattr(email, 'sender', '').lower(),
                                "subject": getattr(email, 'subject', '').lower(),
                                "body": getattr(email, 'body', '').lower()[:2000],
                                "recipients": getattr(email, 'to', []) or getattr(email, 'recipients', []) or [],
                                "is_cc": _is_cc,
                            }
                            changed = False
                            for rule in custom_rules:
                                if rule.matches(email_data) and rule.label_name not in existing.labels:
                                    existing.add_custom_label(rule.label_name, rule.confidence,
                                        f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                                    changed = True
                            if changed:
                                label_store.save_assignment(existing)
                                custom_updated += 1
                        skipped_user += 1
                        continue
                else:
                    # Normal mode: skip all already-assigned emails
                    continue
            emails_to_label.append(email)

        if not emails_to_label and custom_updated == 0:
            return jsonify({
                "message": "All emails already labeled",
                "count": 0,
                "skipped_user": skipped_user,
            })

        # Lancer en background (bounded thread pool)
        if emails_to_label:
            from app.api.routes import _auto_assign_labels_background
            _bg_account_id = account_id
            _background_executor.submit(_auto_assign_labels_background, emails_to_label, force=force, account_id=_bg_account_id)

        return jsonify({
            "message": f"Auto-labeling started for {len(emails_to_label)} emails"
                       + (f", {custom_updated} user emails updated with new custom labels" if custom_updated else ""),
            "count": len(emails_to_label),
            "skipped_user": skipped_user,
            "custom_updated": custom_updated,
        })

    except Exception:
        logger.exception("Error classifying all emails")
        return jsonify({"error": "Classification failed"}), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


@labels_bp.route("/classify-all/progress", methods=["GET"])
def classify_all_progress():
    """Returns progress of the current classify-all background job."""
    from app.api.routes import _labeling_progress
    return jsonify(_labeling_progress)


# ===========================================================================
# RECLASSIFY ENDPOINT — re-runs built-in rules on already-classified emails
# ===========================================================================

def _reclassify_emails_background(emails: list, label_store, user_email: str, account_id: Optional[int] = None) -> int:
    """Re-classe les emails déjà labelisés par les règles built-in (pas user).

    Préserve les labels assignés manuellement (assigned_by == 'user').
    Applique aussi les règles custom même si le default label n'a pas changé.
    Retourne le nombre d'emails mis à jour.
    """
    updated = 0
    try:
        container = get_container()
        use_case = container.get_label_email_use_case(
            user_email=user_email, account_id=account_id,
        )

        # Collect custom label rules for post-reclassification
        from app.domain.entities.email_labels import DEFAULT_LABEL_NAMES
        all_rules = label_store.get_rules()
        custom_rules = [r for r in all_rules if r.label_name not in DEFAULT_LABEL_NAMES]

        for email in emails:
            email_id = str(getattr(email, 'id', ''))
            if not email_id:
                continue

            existing = label_store.get_assignment(email_id)

            # Préserver les corrections manuelles de l'utilisateur
            if existing and existing.assigned_by == "user":
                # Toujours appliquer les nouvelles règles custom aux emails user-corrected
                if custom_rules:
                    changed = _apply_custom_rules_to_existing(
                        email, existing, custom_rules, label_store
                    )
                    if changed:
                        updated += 1
                continue

            # Contact floor: pass sender_is_real_contact so the pipeline can
            # skip the LLM fallback and default to FYI for known contacts.
            _reclass_meta = {}
            try:
                from app.api.routes_helpers import sender_is_real_contact
                _acct_id = getattr(email, 'account_id', None)
                _reclass_meta["sender_is_real_contact"] = sender_is_real_contact(
                    _acct_id, getattr(email, 'sender', '')
                )
            except Exception:
                pass
            # Forward provider-extracted RFC headers (List-Unsubscribe etc.)
            # to the labelizer — without this the strongest bulk-detection
            # signal is dropped on the reclassify path.
            _src_meta = getattr(email, 'raw_metadata', None)
            if isinstance(_src_meta, dict):
                _src_headers = _src_meta.get("classification_headers")
                if isinstance(_src_headers, dict) and _src_headers:
                    _reclass_meta["classification_headers"] = _src_headers
            new_assignment = use_case.execute(
                email, existing_assignment=existing, raw_metadata=_reclass_meta
            )

            # Mettre à jour si le default label a changé OU si des custom labels diffèrent
            if existing:
                default_changed = existing.default_label != new_assignment.default_label
                custom_changed = set(existing.custom_labels) != set(new_assignment.custom_labels)
                if not default_changed and not custom_changed:
                    # Appliquer quand même les nouvelles règles custom
                    if custom_rules:
                        changed = _apply_custom_rules_to_existing(
                            email, existing, custom_rules, label_store
                        )
                        if changed:
                            updated += 1
                    continue

            label_store.save_assignment(new_assignment)
            updated += 1

        logger.info(f"[reclassify] {updated} emails re-classifiés avec les nouvelles règles")
    except Exception:
        logger.exception("[reclassify] Erreur lors de la re-classification")
    return updated


def _apply_custom_rules_to_existing(email, assignment, custom_rules, label_store) -> bool:
    """Applique les règles custom à un assignment existant sans toucher au default label."""
    email_data = {
        "sender": (getattr(email, 'sender', '') or "").lower(),
        "subject": (getattr(email, 'subject', '') or "").lower(),
        "body": (getattr(email, 'body', '') or "").lower()[:2000],
        "recipients": getattr(email, 'to', []) or getattr(email, 'recipients', []) or [],
        "is_cc": assignment.is_cc,
    }
    changed = False
    for rule in custom_rules:
        if rule.matches(email_data) and rule.label_name not in assignment.labels:
            assignment.add_custom_label(
                rule.label_name, rule.confidence,
                f"Rule: {rule.condition_type} = '{rule.condition_value}'"
            )
            changed = True
    if changed:
        assignment._rebuild_labels()
        label_store.save_assignment(assignment)
    return changed


@labels_bp.route("/reclassify", methods=["POST"])
def reclassify_emails():
    """
    Re-exécute les règles built-in sur les emails déjà classifiés par l'IA.

    Utile après une correction de règles (ex: fix spam → Bruit) pour mettre à jour
    les emails existants sans attendre les prochains nouveaux emails.

    Préserve :
    - Les labels assignés manuellement (assigned_by == 'user')
    - Les labels à confidence 1.0 (corrections explicites de l'utilisateur)

    Cost guard (audit 2026-05-05):
        Body params (all optional):
          - max_emails (int, default 200, hard cap 1000)
          - confirm_cost (bool, default False) — must be True for max_emails > 200
        Returns 400 with cost_estimate if the request would exceed the soft cap
        without confirm_cost set. Per-email cost ≈ $0.0005 (Haiku) up to ~$0.003
        (Sonnet smart-routing escalation, ~5% of emails).

    Returns:
        JSON avec le nombre d'emails re-classifiés.
    """
    provider = None
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        container = get_container()
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        label_store = container.get_label_store(account_id=account_id)

        # ----- Cost guard (audit 2026-05-05) ----------------------------------
        # Read soft body params. We don't 400 on missing JSON — legacy callers
        # POST with no body and expect the 200-email default behaviour.
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        try:
            requested_max = int(body.get("max_emails", 200))
        except (TypeError, ValueError):
            requested_max = 200
        # Hard ceiling: refuse anything over 1000 outright. At ~$0.003/email
        # worst case that is $3 — still small but already an order of magnitude
        # above what a "fix one rule" reclassify should ever need.
        if requested_max <= 0 or requested_max > 1000:
            return jsonify({
                "error": "max_emails out of range",
                "min": 1, "max": 1000,
            }), 400

        confirm_cost = bool(body.get("confirm_cost", False))
        # Per-email worst-case (Sonnet escalation) used for the gate so the
        # estimate the user confirms is always >= what they actually pay.
        _PER_EMAIL_USD = 0.003
        if requested_max > 200 and not confirm_cost:
            return jsonify({
                "error": "confirmation required",
                "reason": "max_emails > 200 requires explicit cost confirmation",
                "max_emails": requested_max,
                "cost_estimate_usd": round(requested_max * _PER_EMAIL_USD, 4),
                "hint": "Re-POST with {\"max_emails\": N, \"confirm_cost\": true}",
            }), 400

        provider = _get_provider_for_db_account(account_id)
        if provider is None:
            return jsonify({"error": "No email provider for account"}), 503

        emails = provider.get_messages(limit=requested_max)

        # Déconnecter IMAP immédiatement après la récupération
        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        user_email = _get_active_user_email()

        # Capture account_id in request context before spawning background thread
        # (g.auth_user is not available in threads — resolve here).
        _bg_account_id = account_id

        # Lancer en background
        def _bg():
            updated = 0
            try:
                from app.api.websocket import emit_to_account
                emit_to_account(
                    "labels_classification_started",
                    {"count": len(emails)},
                    _bg_account_id,
                )
            except Exception:
                pass
            try:
                updated = _reclassify_emails_background(emails, label_store, user_email, account_id=_bg_account_id)
                # Invalider les caches email après re-classification
                try:
                    from app.api.routes import _email_cache, _email_cache_lock, _invalidate_label_batch_cache
                    with _email_cache_lock:
                        _email_cache.clear()
                    _invalidate_label_batch_cache()
                except Exception:
                    pass
                # Émettre un événement WebSocket pour notifier le frontend (account-scoped)
                try:
                    from app.api.websocket import emit_to_account
                    emit_to_account("labels_updated", {"reclassified": updated}, _bg_account_id)
                except Exception:
                    pass
            finally:
                try:
                    from app.api.websocket import emit_to_account
                    emit_to_account(
                        "labels_classification_complete",
                        {"count": updated},
                        _bg_account_id,
                    )
                except Exception:
                    pass

        _background_executor.submit(_bg)

        return jsonify({
            "message": f"Re-classification started for {len(emails)} emails",
            "count": len(emails),
        })

    except Exception:
        logger.exception("Erreur lors de la re-classification")
        return jsonify({"error": "Reclassification failed"}), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass


# ===========================================================================
# BACKFILL HEADERS — repopulate raw_headers for historical emails so the
# labelizer's RFC noise rules (List-Unsubscribe → Noise) fire retroactively.
# ===========================================================================

# Tracks the latest backfill job so the frontend can poll progress.
_backfill_progress: dict = {
    "status": "idle",      # idle | running | done | error
    "total": 0,
    "fetched": 0,
    "saved": 0,
    "reclassified": 0,
    "errors": 0,
    "message": "",
}


def _run_backfill_headers_background(account_id: int, user_email: str, limit: int) -> None:
    """Background worker for /api/labels/backfill-headers.

    1. Find Email rows missing raw_headers (account-scoped).
    2. Batch-fetch the RFC headers from the provider in metadata-only mode
       (cheap — no body re-download).
    3. Persist raw_headers JSON in the DB.
    4. Re-run the labelizer on emails currently labelled Action/FYI with
       confidence < 0.85 — those are the ones most likely to flip to Noise
       once the new bulk signal becomes visible.
    """
    import json as _json_bf

    _backfill_progress.update({
        "status": "running", "total": 0, "fetched": 0,
        "saved": 0, "reclassified": 0, "errors": 0, "message": "",
    })

    try:
        from app.db.database import get_db_session
        from app.db.models.email import Email as EmailModel
        from sqlalchemy import select
        from app.domain.entities import Email as DomainEmail
        from app.services.email_metadata import sanitize_classification_headers

        # Step 1 — collect IDs of emails missing raw_headers, scoped to account.
        with get_db_session() as session:
            stmt = (
                select(EmailModel.email_id)
                .where(EmailModel.account_id == account_id)
                .where(EmailModel.raw_headers.is_(None))
                .where(EmailModel.is_sent == False)  # noqa: E712
                .order_by(EmailModel.date.desc())
                .limit(limit)
            )
            missing_ids = [row[0] for row in session.execute(stmt).all() if row[0]]

        _backfill_progress["total"] = len(missing_ids)
        if not missing_ids:
            _backfill_progress["status"] = "done"
            _backfill_progress["message"] = "Aucun email à backfiller — tous les headers sont déjà persistés."
            return

        # Step 2 — fetch headers via the account-scoped provider. Currently
        # Gmail-only; IMAP/Outlook backfill is left as future work because
        # their batch APIs differ.
        provider = _get_provider_for_db_account(account_id)
        if provider is None:
            _backfill_progress["status"] = "error"
            _backfill_progress["message"] = "No email provider for account"
            return

        try:
            if not hasattr(provider, "fetch_classification_headers_batch"):
                _backfill_progress["status"] = "done"
                _backfill_progress["message"] = (
                    f"Provider {type(provider).__name__} ne supporte pas le backfill "
                    "metadata-only — backfill ignoré (Gmail uniquement pour l'instant)."
                )
                return

            BATCH = 100
            headers_by_id: dict = {}
            for i in range(0, len(missing_ids), BATCH):
                chunk = missing_ids[i : i + BATCH]
                try:
                    chunk_headers = provider.fetch_classification_headers_batch(chunk)
                    headers_by_id.update(chunk_headers)
                    _backfill_progress["fetched"] += len(chunk)
                except Exception as e:
                    logger.warning("Backfill chunk fetch failed (i=%d): %s", i, e)
                    _backfill_progress["errors"] += len(chunk)
        finally:
            try:
                if hasattr(provider, "disconnect"):
                    provider.disconnect()
            except Exception:
                pass

        # Step 3 — persist raw_headers. Emails returning empty headers are still
        # marked with `{}` so the next backfill skips them (NULL → "{}").
        with get_db_session() as session:
            for msg_id in missing_ids:
                row = session.execute(
                    select(EmailModel).where(
                        EmailModel.account_id == account_id,
                        EmailModel.email_id == msg_id,
                    )
                ).scalar_one_or_none()
                if row is None:
                    continue
                hdrs = sanitize_classification_headers(headers_by_id.get(msg_id) or {})
                try:
                    row.raw_headers = _json_bf.dumps(hdrs, ensure_ascii=False, separators=(",", ":"))
                    _backfill_progress["saved"] += 1
                except (TypeError, ValueError) as e:
                    logger.debug("Could not serialize headers for %s: %s", msg_id, e)
                    _backfill_progress["errors"] += 1
            session.commit()

        # Step 4 — reclassify the emails that just gained headers and currently
        # carry a low-confidence Action/FYI assignment. Skip user-corrected rows.
        try:
            container = get_container()
            label_store = container.get_label_store(account_id=account_id)
            use_case = container.get_label_email_use_case(user_email=user_email)
            from app.domain.entities.email_labels import DefaultLabel

            # Only target the emails we just touched.
            ids_with_real_headers = [mid for mid in missing_ids if headers_by_id.get(mid)]
            with get_db_session() as session:
                rows = session.execute(
                    select(EmailModel).where(
                        EmailModel.account_id == account_id,
                        EmailModel.email_id.in_(ids_with_real_headers) if ids_with_real_headers else False,
                    )
                ).scalars().all() if ids_with_real_headers else []

                for row in rows:
                    existing = label_store.get_assignment(row.email_id)
                    if existing and existing.assigned_by == "user":
                        continue
                    if existing and existing.default_label == DefaultLabel.NOISE.value:
                        continue  # already Noise — nothing to flip
                    try:
                        confidence = float(getattr(existing, "default_confidence", 0.0)) if existing else 0.0
                    except (TypeError, ValueError):
                        confidence = 0.0
                    if existing and confidence >= 0.85:
                        continue  # high-confidence non-Noise — leave alone

                    try:
                        parsed_hdrs = _json_bf.loads(row.raw_headers) if row.raw_headers else {}
                    except (TypeError, ValueError):
                        parsed_hdrs = {}
                    if not parsed_hdrs:
                        continue

                    domain_email = DomainEmail(
                        id=row.email_id,
                        sender=row.sender or "",
                        subject=row.subject or "",
                        body=(row.body_text or row.body_html or ""),
                        recipients=[r.strip() for r in (row.recipients or "").split(",") if r.strip()],
                        cc=[c.strip() for c in (row.cc or "").split(",") if c.strip()],
                        received_at=row.date,
                    )
                    raw_meta = {"classification_headers": parsed_hdrs}
                    try:
                        from app.api.routes_helpers import sender_is_real_contact
                        raw_meta["sender_is_real_contact"] = sender_is_real_contact(
                            account_id, row.sender or ""
                        )
                    except Exception:
                        pass

                    new_assignment = use_case.execute(
                        domain_email,
                        existing_assignment=existing,
                        raw_metadata=raw_meta,
                    )

                    if not existing or new_assignment.default_label != existing.default_label:
                        label_store.save_assignment(new_assignment)
                        _backfill_progress["reclassified"] += 1

            # Invalidate caches so the UI immediately reflects the new labels.
            try:
                from app.api.routes import _email_cache, _email_cache_lock, _invalidate_label_batch_cache
                with _email_cache_lock:
                    _email_cache.clear()
                _invalidate_label_batch_cache()
            except Exception:
                pass
            try:
                from app.api.websocket import emit_to_account
                emit_to_account(
                    "labels_updated",
                    {"reclassified": _backfill_progress["reclassified"], "source": "backfill_headers"},
                    account_id,
                )
            except Exception:
                pass
        except Exception:
            logger.exception("Backfill: reclassify step failed")

        _backfill_progress["status"] = "done"
        _backfill_progress["message"] = (
            f"Backfill terminé: {_backfill_progress['saved']}/{len(missing_ids)} emails enrichis, "
            f"{_backfill_progress['reclassified']} reclassifiés Action/FYI → Noise."
        )

    except Exception as e:
        logger.exception("Backfill headers job crashed")
        _backfill_progress["status"] = "error"
        _backfill_progress["message"] = str(e)


@labels_bp.route("/backfill-headers", methods=["POST"])
def backfill_headers():
    """Repopule la colonne raw_headers pour les emails synchronisés avant
    l'introduction du stockage des headers RFC, puis relance la
    classification pour ceux qui étaient Action/FYI à faible confiance.

    Body JSON optionnel: ``{"limit": 5000}`` (défaut 5000, max 20000).

    Réponse immédiate; suivi via ``GET /api/labels/backfill-headers/progress``.
    """
    try:
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 400

        if _backfill_progress.get("status") == "running":
            return error_response(
                "LABELS_BACKFILL_IN_PROGRESS",
                "A backfill is already in progress",
                409,
                extra={"progress": _backfill_progress},
            )

        body = request.get_json(silent=True) or {}
        try:
            limit = int(body.get("limit", 5000))
        except (TypeError, ValueError):
            limit = 5000
        limit = max(1, min(limit, 20000))

        user_email = _get_active_user_email()
        _background_executor.submit(
            _run_backfill_headers_background, account_id, user_email, limit
        )
        return jsonify({
            "message": f"Backfill started (limit: {limit} emails)",
            "limit": limit,
        })
    except Exception:
        logger.exception("Failed to start backfill")
        return jsonify({"error": "Backfill failed to start"}), 500


@labels_bp.route("/backfill-headers/progress", methods=["GET"])
def backfill_headers_progress():
    """Progression du job de backfill courant (idle / running / done / error)."""
    return jsonify(_backfill_progress)


# ===========================================================================
# SINGLE LABEL ENDPOINTS (catch-all /<name> - MUST be registered LAST)
# ===========================================================================

@labels_bp.route("/<name>", methods=["GET"])
def get_label(name: str):
    """Récupère un label par son nom."""
    try:
        valid, error = validate_label_name(name)
        if not valid:
            return jsonify({"error": error}), 400

        container = get_container()
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (deep audit 2026-06-02 D, CWE-639): reject the -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        store = container.get_label_store(account_id=account_id)
        label = store.get_label(name)

        if not label:
            return jsonify({"error": "Label not found"}), 404

        return jsonify({"label": label.to_dict()})

    except Exception as e:
        logger.exception("Error getting label")
        return jsonify({"error": str(e)}), 500


@labels_bp.route("/<name>", methods=["PUT"])
@require_json
def update_label(name: str):
    """Met à jour un label existant."""
    try:
        valid, error = validate_label_name(name)
        if not valid:
            return jsonify({"error": error}), 400

        data = request.get_json()
        updates = {}

        if "color" in data:
            updates["color"] = data["color"]
        if "description" in data:
            updates["description"] = data["description"][:MAX_DESCRIPTION_LENGTH]
        if "is_favorite" in data:
            updates["is_favorite"] = bool(data["is_favorite"])
        if "ai_prompt" in data:
            updates["ai_prompt"] = data["ai_prompt"]
        if "is_project" in data:
            updates["is_project"] = bool(data["is_project"])
        if "project_name" in data:
            updates["project_name"] = data["project_name"]
        if "project_number" in data:
            updates["project_number"] = data["project_number"]
        if "project_abbreviation" in data:
            updates["project_abbreviation"] = data["project_abbreviation"]
        if "subject_prefix" in data:
            updates["subject_prefix"] = data["subject_prefix"]
        container = get_container()
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (deep audit 2026-06-02 D, CWE-639): reject the -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        store = container.get_label_store(account_id=account_id)
        success = store.update_label(name, updates)
        _invalidate_labels_cache(account_id=account_id)

        if not success:
            return jsonify({"error": "Label not found"}), 404

        label = store.get_label(name)
        return jsonify({
            "label": label.to_dict(),
            "message": "Label updated successfully",
        })

    except Exception as e:
        logger.exception("Error updating label")
        return jsonify({"error": str(e)}), 500


def _clear_label_from_contact_groups(label_name: str, account_id: int) -> int:
    """Unlink any contact group pointing to a deleted label.

    Contact groups store label_name as a free string (no FK), so deleting a
    label leaves dangling references. Post-migration 039 le scrub se fait en
    DB — et SCOPÉ PAR COMPTE : l'ancien parcours du JSON global effaçait
    aussi le label_name homonyme des groupes des AUTRES tenants (effet de
    bord cross-tenant, classe d'anti-patterns de l'audit 2026-05-29).

    Returns the number of groups updated.
    """
    try:
        from sqlalchemy import select

        from app.api.contact_groups import _ensure_legacy_import
        from app.db.database import get_db_session
        from app.db.models.contact_group import ContactGroupRow

        _ensure_legacy_import()
        with get_db_session() as session:
            rows = list(session.execute(
                select(ContactGroupRow).where(
                    ContactGroupRow.account_id == account_id,
                    ContactGroupRow.label_name == label_name,
                )
            ).scalars())
            for row in rows:
                row.label_name = None
            if rows:
                session.commit()
            return len(rows)
    except Exception as e:
        logger.warning(f"[LABEL-DELETE] failed to clear contact_groups for '{label_name}': {e}")
        return 0


@labels_bp.route("/<name>", methods=["DELETE"])
def delete_label(name: str):
    """Supprime un label (impossible pour les labels par défaut)."""
    try:
        valid, error = validate_label_name(name)
        if not valid:
            return jsonify({"error": error}), 400

        container = get_container()
        from app.api.routes_helpers import _resolve_account_id_for_user
        account_id = _resolve_account_id_for_user()
        # SECURITY (deep audit 2026-06-02 D, CWE-639): reject the -1 pre-OAuth sentinel.
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401
        store = container.get_label_store(account_id=account_id)
        result = store.delete_label(name)
        _invalidate_labels_cache(account_id=account_id)

        if result == 'is_default':
            return jsonify({"error": "Cannot delete a default label"}), 400

        # Clear stale references from the contact_groups table — label_name is
        # a free string, not a FK, so groups pointing to this label keep the
        # old value unless we scrub it here (scopé au compte courant).
        cleared = _clear_label_from_contact_groups(name, account_id)
        if cleared:
            logger.info(f"[LABEL-DELETE] cleared label '{name}' from {cleared} contact group(s)")

        # 'deleted' or 'not_found' both mean the label is now absent — success
        return jsonify({"message": "Label deleted successfully"})

    except Exception as e:
        logger.exception("Error deleting label")
        return jsonify({"error": str(e)}), 500
