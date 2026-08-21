# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
# Railway cache-bust 2026-04-14T15-00Z: force reupload of /writing-style/* sub-routes
"""
Routes API REST — Follow-ups, Learning, Costs, Analytics, Draft Completion, Tasks.

Extracted from routes.py for maintainability.
"""

import logging
import re
from datetime import datetime
from flask import request, jsonify

from app.api.admin import require_admin
from app.domain.entities import DraftInputTone

from .routes_helpers import (
    api_bp,
    _get_legacy_modules,
    _invalid_tone_response,
    _validate_limit,
    _validate_optional_string,
    require_json,
    _resolve_account_id_for_user,
    _NOREPLY_PATTERNS,
    _NOISE_DOMAINS,
)
import app.api.routes_helpers as _rh

logger = logging.getLogger(__name__)

# Per-process cache of account_id → last reconciliation timestamp (float).
# Reconciliation reruns if > 6 hours have elapsed, so new emails synced
# after the first reconciliation are eventually picked up without a restart.
import time as _time


class _ReconcileCache(dict[int, float]):
    """TTL cache with set-like add() compatibility for older tests/helpers."""

    def add(self, account_id: int) -> None:
        self[int(account_id)] = _time.time()


_contact_counts_reconciled: _ReconcileCache = _ReconcileCache()
_RECONCILE_TTL_SECONDS = 6 * 3600


# ============================================================================
# FOLLOW-UPS
# ============================================================================

@api_bp.route("/followups/check", methods=["POST"])
def trigger_followup_check():
    """
    Déclenche manuellement le check des follow-ups (bypass cooldown).
    Utile pour tests et débogage.
    """
    account_id = _resolve_account_id_for_user()
    import app.api.quicksteps_scheduler as af
    af._scheduler_last_run.clear()  # Reset throttle so the tick fires now

    oauth_account_id = str(account_id) if account_id > 0 else ""

    # Run synchronously for immediate feedback
    from app.api.quicksteps_scheduler import run_quicksteps_scheduled
    run_quicksteps_scheduled(oauth_account_id, [])

    # Count nudges that just landed: reminders for the resolved account
    # whose date is in the past (i.e. surfaced to the user) and that
    # didn't already exist before the trigger.
    from app.services.reminder_service import _read as _read_reminders
    reminders = [
        r for r in _read_reminders()
        if r.get("account_id") == account_id
    ]
    return jsonify({
        "triggered": True,
        "nudges_active": len(reminders),
        "reminder_ids": [r.get("id") for r in reminders],
    })


# ============================================================================
# LEARNING
# ============================================================================

@api_bp.route("/learning/stats", methods=["GET"])
@require_admin
def learning_stats():
    """
    Statistiques du module learning. **Admin only (transition).**

    Audit H-7 (security.md, issue #533): `LearningService.get_stats()`
    agrège les feedbacks de TOUS les tenants — `LearningStats` n'a pas
    de notion d'account_id, et `LearnedPattern` non plus. Tant que le
    schéma n'est pas refait, on gate sur `@require_admin` plutôt que de
    retourner des compteurs cross-tenant aux end users.

    Returns:
        Metriques d'apprentissage.
    """
    _resolve_account_id_for_user()
    # Clean Architecture: utiliser le service via Container DI
    # TODO: pass account_id to get_stats() once LearningService supports it
    stats = _rh._get_container().get_learning_service().get_stats()
    return jsonify(stats.__dict__ if hasattr(stats, '__dict__') else stats)


@api_bp.route("/learning/patterns", methods=["GET"])
@require_admin
def learning_patterns():
    """
    Liste les patterns appris. **Admin only (transition).**

    Audit H-7 (issue #533): `LearnedPattern` est partagé globalement (pas
    de colonne `account_id`), donc `list_all()` exposait les triggers /
    corrections appris depuis les feedbacks de tous les tenants. Gate
    `@require_admin` jusqu'à ce que le store soit scoped.

    Returns:
        Patterns extraits du feedback.
    """
    _resolve_account_id_for_user()
    # Clean Architecture: utiliser le store via Container DI
    # TODO: pass account_id to list_all() once LearningPatternStore supports it
    patterns = _rh._get_container().get_learning_pattern_store().list_all()

    return jsonify({
        "count": len(patterns),
        "patterns": [_pattern_to_dict(p) for p in patterns],
    })


def _pattern_to_dict(pattern) -> dict:
    """Convertit un pattern en dictionnaire."""
    pattern_type = pattern.pattern_type
    if hasattr(pattern_type, 'value'):
        pattern_type = pattern_type.value
    return {
        "id": pattern.id,
        "pattern_type": pattern_type,
        "description": pattern.description,
        "confidence": pattern.confidence,
        "examples": pattern.examples[:3] if pattern.examples else [],
        "created_at": pattern.created_at,
    }


MIN_FEEDBACK_FOR_PATTERNS = 5


@api_bp.route("/learning/comparisons", methods=["GET"])
@require_admin
def learning_comparisons():
    """
    Comparaisons avant/apres pour montrer l'evolution de l'apprentissage.
    **Admin only (transition).**

    Audit H-7 (issue #533): la route lit `feedback_store.list_all()` et
    matche les ratings positifs/négatifs sans aucun filtre par tenant.
    Le code est dormant aujourd'hui (`getattr(container,
    'get_feedback_store', lambda: None)()` retourne None car le
    container expose `get_user_feedback_store`, pas `get_feedback_store`)
    mais reste un trou de sécurité latent — un futur câblage du store
    réveillerait le leak. On gate `@require_admin` en transition.

    Returns:
        Exemples de reponses generees avant et apres l'apprentissage.
    """
    _resolve_account_id_for_user()
    container = _rh._get_container()
    feedback_store = getattr(container, 'get_feedback_store', lambda: None)()
    draft_store = getattr(container, 'get_draft_store', lambda: None)()

    comparisons = []
    # TODO: pass account_id to list_all() once FeedbackStore supports it
    all_feedback = feedback_store.list_all() if (feedback_store and hasattr(feedback_store, 'list_all')) else []

    positive_feedback = [f for f in all_feedback if getattr(f, 'rating', 0) >= 4]
    negative_feedback = [f for f in all_feedback if getattr(f, 'rating', 0) <= 2]

    if negative_feedback and positive_feedback:
        negative_feedback = sorted(negative_feedback, key=lambda x: getattr(x, 'created_at', ''))[:3]
        positive_feedback = sorted(positive_feedback, key=lambda x: getattr(x, 'created_at', ''), reverse=True)[:3]

        # O(N) : chercher le 1er négatif avec draft, puis le 1er positif avec draft
        neg_item, neg_draft = None, None
        for neg in negative_feedback:
            d = draft_store.get(neg.draft_id) if hasattr(neg, 'draft_id') and draft_store else None
            if d:
                neg_item, neg_draft = neg, d
                break

        pos_item, pos_draft = None, None
        if neg_item:
            for pos in positive_feedback:
                d = draft_store.get(pos.draft_id) if hasattr(pos, 'draft_id') and draft_store else None
                if d:
                    pos_item, pos_draft = pos, d
                    break

        if neg_item and pos_item and neg_draft and pos_draft:
            comparisons.append({
                "id": f"{neg_item.draft_id}-{pos_item.draft_id}",
                "email_subject": getattr(neg_draft, 'email_subject', 'Email'),
                "before": {
                    "date": getattr(neg_item, 'created_at', None),
                    "response": getattr(neg_draft, 'content', '')[:500],
                    "score": getattr(neg_item, 'rating', 1),
                    "issues": _extract_issues(neg_item),
                },
                "after": {
                    "date": getattr(pos_item, 'created_at', None),
                    "response": getattr(pos_draft, 'content', '')[:500],
                    "score": getattr(pos_item, 'rating', 5),
                    "improvements": _extract_improvements(pos_item),
                },
            })

    improvement_summary = None
    if len(all_feedback) >= 5:
        scores = [getattr(f, 'rating', 3) for f in all_feedback if hasattr(f, 'rating')]
        if scores:
            old_scores = scores[:len(scores)//2] if len(scores) >= 4 else scores[:2]
            new_scores = scores[len(scores)//2:] if len(scores) >= 4 else scores[-2:]

            avg_before = sum(old_scores) / len(old_scores) if old_scores else 0
            avg_after = sum(new_scores) / len(new_scores) if new_scores else 0

            improvement = ((avg_after - avg_before) / avg_before * 100) if avg_before > 0 else 0

            improvement_summary = {
                "average_score_before": round(avg_before, 1),
                "average_score_after": round(avg_after, 1),
                "improvement_percentage": round(improvement),
                "top_improvements": ["Personnalisation", "Ton adapte", "Signature"],
            }

    return jsonify({
        "comparisons": comparisons,
        "improvement_summary": improvement_summary,
    })


def _extract_issues(feedback) -> list:
    """Extrait les problemes mentionnes dans le feedback."""
    issues = []
    comment = getattr(feedback, 'comment', '') or ''
    if 'formel' in comment.lower():
        issues.append('Ton trop formel')
    if 'court' in comment.lower() or 'bref' in comment.lower():
        issues.append('Trop court')
    if 'signature' in comment.lower():
        issues.append('Pas de signature')
    if 'generique' in comment.lower():
        issues.append('Trop generique')
    if not issues:
        issues.append('A ameliorer')
    return issues


def _extract_improvements(feedback) -> list:
    """Extrait les ameliorations du feedback positif."""
    improvements = []
    comment = getattr(feedback, 'comment', '') or ''
    if 'personnalis' in comment.lower():
        improvements.append('Personnalise')
    if 'ton' in comment.lower():
        improvements.append('Ton adapte')
    if 'signature' in comment.lower():
        improvements.append('Signature ajoutee')
    if not improvements:
        improvements.append('Qualite amelioree')
    return improvements


@api_bp.route("/learning/analyze", methods=["POST"])
@require_admin
def trigger_learning():
    """
    Declenche une analyse learning manuellement. **Admin only (transition).**

    Audit (issue #533 follow-up, 2026-05-05): cette route appelait
    `_resolve_account_id_for_user()` puis droppait la valeur.
    `LearningService.analyze_feedback()` agrège les feedbacks de tous
    les tenants et `extract_patterns()`/`generate_adjustment()` mutent
    le `pattern_store` global — user B pouvait poisonner le drafter
    prompt de user A. Gate `@require_admin` jusqu'à ce que le service
    accepte un account_id.

    Utilise LearningService via le Container DI.

    Returns:
        Resultat de l'analyse.
    """
    _resolve_account_id_for_user()
    # Clean Architecture: utiliser le service via Container DI
    # TODO: pass account_id to analyze_feedback() once LearningService supports it
    learning_service = _rh._get_container().get_learning_service()
    insights = learning_service.analyze_feedback()

    patterns, adjustment = [], None
    total_with_feedback = getattr(insights, 'total_with_feedback', 0)
    if total_with_feedback >= MIN_FEEDBACK_FOR_PATTERNS:
        patterns = learning_service.extract_patterns()
        adjustment = learning_service.generate_adjustment()

    return jsonify({
        "insights": insights.__dict__ if hasattr(insights, '__dict__') else insights,
        "new_patterns": len(patterns) if patterns else 0,
        "new_adjustment": bool(adjustment),
    })


@api_bp.route("/learning/rules", methods=["GET"])
def learning_rules_list():
    """Liste toutes les règles de brouillon apprises."""
    try:
        account_id = _resolve_account_id_for_user()
        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=account_id)
        rules = store.get_rules(active_only=False)
        return jsonify({"rules": rules})
    except Exception as e:
        logger.error(f"learning/rules GET error: {e}")
        return jsonify({"rules": []})


@api_bp.route("/learning/rules/<rule_id>", methods=["DELETE"])
def learning_rules_delete(rule_id: str):
    """Supprime une règle de brouillon apprise."""
    try:
        account_id = _resolve_account_id_for_user()
        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=account_id)
        deleted = store.delete_rule(rule_id)
        if deleted:
            return jsonify({"status": "deleted"})
        return jsonify({"error": "Rule not found"}), 404
    except Exception as e:
        logger.error(f"learning/rules DELETE error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/learning/rules/<rule_id>", methods=["PATCH"])
def learning_rules_update(rule_id: str):
    """Met à jour une règle (rule_text, active, category, etc.)."""
    try:
        account_id = _resolve_account_id_for_user()
        from app.draft_learning import get_draft_learning_store
        data = request.get_json(silent=True) or {}
        store = get_draft_learning_store(account_id=account_id)
        updated = store.update_rule(rule_id, **data)
        if updated:
            return jsonify({"status": "updated"})
        return jsonify({"error": "Rule not found"}), 404
    except Exception as e:
        logger.error(f"learning/rules PATCH error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/training/reset-all", methods=["DELETE"])
def training_reset_all():
    """
    Supprime les données d'apprentissage et d'entraînement DU TENANT authentifié.

    SCOPED par account_id : le handler n'opère QUE sur le slice du caller.
    Les fichiers globalement partagés (`memoire.md`, `learned_patterns.json`)
    ne sont volontairement pas touchés ici — ils n'ont pas de colonne
    account_id et un wipe écraserait les données des autres tenants
    (audit security.md C-5, issue #525). Pour réinitialiser les fichiers
    globaux côté dev, utiliser POST /api/dev/reset-all-data (loopback-only).

    RGPD: permet à l'utilisateur d'effacer ses données personnelles. La
    suppression de la base globale partagée n'a pas sa place dans cet
    endpoint multi-tenant.
    """
    from pathlib import Path

    account_id = _resolve_account_id_for_user()

    # Garde-fou cross-tenant : sans account résolu (sentinel -1, JWT sans
    # compte mappé), on refuse plutôt que de no-op silencieusement. Avant le
    # fix #525, un caller sans account passait quand même et touchait les
    # branches non-scopées (memoire.md, learned_patterns.json, label_store
    # global) — d'où le wipe cross-tenant.
    if account_id <= 0:
        logger.warning(
            "training/reset-all rejected: caller has no resolved account "
            f"(account_id={account_id})"
        )
        return jsonify({
            "error": "No account resolved for caller",
            "code": "NO_ACCOUNT_SCOPE",
        }), 401

    container = _rh._get_container()
    results = {}

    # 1. Draft corrections & règles apprises (scoped par account_id)
    try:
        from app.draft_learning import get_draft_learning_store
        get_draft_learning_store(account_id=account_id).clear()
        results["draft_corrections"] = "cleared"
    except Exception as e:
        logger.error(f"reset-all: draft_corrections error: {e}")
        results["draft_corrections"] = f"error: {e}"

    # 2. Knowledge entries (SQLite) — scoped by account_id
    try:
        from sqlalchemy import delete as sa_delete
        from app.db.models.knowledge_entry import KnowledgeEntry
        with _rh.get_db_session() as session:
            session.execute(
                sa_delete(KnowledgeEntry).where(
                    KnowledgeEntry.account_id == str(account_id)
                )
            )
            session.commit()
        results["knowledge_entries"] = "cleared"
    except Exception as e:
        logger.error(f"reset-all: knowledge_entries error: {e}")
        results["knowledge_entries"] = f"error: {e}"

    # 3. memoire.md — pas de wipe ici. `container.config.knowledge_path`
    # pointe sur `knowledge/memoire.md`, un fichier global partagé entre
    # tous les tenants. Les données sémantiquement par-compte vivent dans
    # `knowledge_entries` (déjà nettoyé en (2)) et `style_profiles` (4).
    # Re-activer ce branch exigerait un fichier par account_id (à créer
    # avant) — sinon on régresse sur l'audit C-5 (#525).
    results["memoire_md"] = "skipped (global file, not tenant-scoped)"

    # 4. Profils de style — only delete THIS account's profile.
    # NB: ne plus remettre `container._writing_style_store = None` ici —
    # l'instance est partagée entre tous les tenants, son cache de profils
    # est déjà keyed par (account_id, mtime), donc `delete(account_id)`
    # invalide proprement les seules entrées de ce tenant. Le reset
    # singleton incluait les autres tenants par effet de bord.
    try:
        style_store = container.get_writing_style_store()
        deleted = style_store.delete(account_id)
        results["style_profiles"] = "cleared" if deleted else "no profile found"
    except Exception as e:
        logger.error(f"reset-all: style_profiles error: {e}")
        results["style_profiles"] = f"error: {e}"

    # 5. Patterns appris — pas de wipe ici. `learned_patterns.json` (legacy
    # JSON dans data/learning/) et la table SQLite `learned_patterns` n'ont
    # pas de colonne account_id : un unlink supprimait les patterns de tous
    # les tenants. Tant que le schéma n'expose pas account_id, ce branch
    # reste inactif (audit C-5, #525).
    results["learned_patterns"] = "skipped (schema lacks account_id, not tenant-scoped)"

    # 6. Règles de labels apprises + historique d'assignations
    # SCOPED: `get_label_store(account_id=...)` renvoie un store par compte
    # adossé à `data/labels/<account_id>/` — `delete_rule` et le wipe
    # `assignments.json` opèrent strictement à l'intérieur de ce dossier.
    # Avant le fix, on tapait le store global `data/labels/` qui agrège
    # plusieurs tenants pour les anciennes installations.
    try:
        label_store = container.get_label_store(account_id=account_id)
        learned = [r for r in label_store.get_rules() if getattr(r, "learned_from", None)]
        for rule in learned:
            label_store.delete_rule(rule.rule_id)
        # Vider l'historique d'assignations DE CE TENANT uniquement.
        assignments_path = Path(label_store.storage_dir) / "assignments.json"
        assignments_path.write_text("[]", encoding="utf-8")
        label_store._assign_cache = {}
        results["label_rules"] = f"cleared {len(learned)} learned rule(s) + assignments"
    except Exception as e:
        logger.error(f"reset-all: label_rules error: {e}")
        results["label_rules"] = f"error: {e}"

    logger.info(f"[OK] training/reset-all (account_id={account_id}): {results}")
    return jsonify({"status": "ok", "results": results})


@api_bp.route("/learning/all", methods=["GET"])
def learning_all():
    """
    Toutes les donnees d'apprentissage groupees par categorie.

    Account-scoped (issue #533 resolved, 2026-05-21): chaque catégorie ne lit
    que le slice du caller — auto-label rules via
    ``get_label_store(account_id=...)``, ``by_label`` via ``valid_email_ids``,
    draft-ai & draft-rules via leurs stores scopés, et Savoirs via
    ``load_knowledge_from_db(account_id)`` (sans fallback sur le ``memoire.md``
    global). Le gate ``@require_admin`` de transition — posé pour la fuite
    cross-tenant où user B voyait les règles auto-label / domaines de contacts
    de user A — est donc retiré ; le before_request de ``api_bp`` exige toujours
    un utilisateur authentifié. Un caller sans compte résolu (sentinel -1)
    obtient des catégories vides, jamais les données d'un autre tenant.
    ---
    tags:
      - Learning
    responses:
      200:
        description: Categories Auto-Label et Draft AI
    """
    account_id = _resolve_account_id_for_user()
    categories = []

    # ── Auto-Label: learned rules ──
    try:
        container = _rh._get_container()
        # Account-scoped store (data/labels/<account_id>/). For an unresolved
        # caller (sentinel -1) we keep the global store only to read the
        # by_label volume below — which self-scopes via valid_email_ids — and
        # expose zero learned rules, never another tenant's rule conditions
        # (the #533 leak: sender domains are encoded in rule values).
        scoped = bool(account_id and account_id > 0)
        label_store = (container.get_label_store(account_id=account_id)
                       if scoped else container.get_label_store())
        all_rules = label_store.get_rules() if scoped else []
        learned = [r for r in all_rules if getattr(r, "learned_from", None)]

        items = []
        total_rule_matches = 0
        total_rule_corrections = 0
        for r in learned:
            tm = getattr(r, 'total_matches', 0)
            corr = getattr(r, 'corrections', 0)
            precision = round((tm - corr) / tm * 100) if tm > 0 else None
            total_rule_matches += tm
            total_rule_corrections += corr
            items.append({
                "id": r.rule_id,
                "label": r.label_name,
                "type": r.condition_type,
                "value": r.condition_value,
                "use_count": r.use_count,
                "total_matches": tm,
                "corrections": corr,
                "precision": precision,
                "is_active": getattr(r, 'is_active', True),
                "disabled_reason": getattr(r, 'disabled_reason', None),
                "created_at": r.created_at,
            })

        # Per-label email volume — how many emails actually carry each label,
        # across ALL folders (inbox + archived + trash), not just the inbox and
        # not the count of *learned-rule* firings. This is the auto-sorter's
        # total observable output. assignments.json is a process-global store,
        # so account isolation is enforced entirely by valid_email_ids: an
        # empty set yields {} (never an unscoped cross-tenant count), so we
        # always pass a real set even when the account can't be resolved.
        by_label = []
        try:
            from app.db.database import get_db_session
            from sqlalchemy import text

            account_email_ids: set[str] = set()
            if account_id and account_id > 0:
                with get_db_session() as session:
                    rows = session.execute(
                        text(
                            "SELECT email_id FROM emails "
                            "WHERE account_id = :aid AND is_sent = 0"
                        ),
                        {"aid": account_id},
                    ).fetchall()
                    account_email_ids = {str(row[0]) for row in rows if row[0]}

            label_counts = label_store.get_label_counts(valid_email_ids=account_email_ids)
            by_label = [
                {"label": label, "email_count": count}
                for label, count in sorted(
                    label_counts.items(), key=lambda kv: (-kv[1], kv[0])
                )
            ]
        except Exception as e:
            logger.debug("learning/all - by_label counts error: %s", e)
            by_label = []

        # Precision over the labelled population (account-scoped via by_label),
        # not over learned-rule firings. With zero corrections this reads 100 %
        # and it never sits empty while there are labelled emails — the old
        # rule-match denominator stayed None until a learned rule re-fired, so a
        # user who had corrected nothing saw a blank instead of the intuitive
        # 100 %. Caveat: total_rule_corrections only counts rule-attributed
        # corrections; a base-classifier label corrected before any rule existed
        # is not yet subtracted (needs a per-account corrections counter — the
        # learned-rule store is global/admin-gated today, issue #533).
        total_labeled = sum(s["email_count"] for s in by_label)
        global_accuracy = (
            max(0, round((total_labeled - total_rule_corrections) / total_labeled * 100))
            if total_labeled > 0 else None
        )

        categories.append({
            "id": "auto-label",
            "name": "Auto-Label",
            "description": "Règles apprises via corrections de labels",
            "count": len(items),
            "accuracy": global_accuracy,
            "total_matches": total_rule_matches,
            "total_corrections": total_rule_corrections,
            "by_label": by_label,
            "items": items,
        })
    except Exception as e:
        logger.debug("learning/all - label rules error: %s", e)
        categories.append({
            "id": "auto-label",
            "name": "Auto-Label",
            "description": "Règles apprises via corrections de labels",
            "count": 0,
            "by_label": [],
            "items": [],
        })

    # ── Draft AI: corrections & positives ──
    try:
        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=account_id)
        corrections = list(store._corrections)
        positive_count = store._positive_count

        items = []
        for c in corrections:
            items.append({
                "id": c.get("email_id", c.get("timestamp", "")),
                "contact": c.get("contact", ""),
                "diff_summary": c.get("diff_summary", ""),
                "timestamp": c.get("timestamp", ""),
            })

        total_drafts = len(items) + positive_count
        accuracy = round(positive_count / total_drafts * 100) if total_drafts > 0 else 0

        categories.append({
            "id": "draft-ai",
            "name": "Draft AI",
            "description": "Corrections de brouillons et signaux positifs",
            "count": len(items),
            "positive_count": positive_count,
            "total_drafts": total_drafts,
            "accuracy": accuracy,
            "items": items,
        })
    except Exception as e:
        logger.debug("learning/all - draft learning error: %s", e)
        categories.append({
            "id": "draft-ai",
            "name": "Draft AI",
            "description": "Corrections de brouillons et signaux positifs",
            "count": 0,
            "positive_count": 0,
            "total_drafts": 0,
            "accuracy": 0,
            "items": [],
        })

    # ── Draft Rules: règles extraites par LLM ──
    try:
        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=account_id)
        rules = store.get_rules(active_only=False)
        items = []
        for r in rules:
            items.append({
                "id": r.get("id", ""),
                "rule_text": r.get("rule_text", ""),
                "category": r.get("category", "contenu"),
                "scope": r.get("scope", "global"),
                "contact": r.get("contact", ""),
                "confidence": r.get("confidence", 0.5),
                "active": r.get("active", True),
                "created_at": r.get("created_at", ""),
            })
        categories.append({
            "id": "draft-rules",
            "name": "Règles de rédaction",
            "description": "Règles extraites des corrections de brouillons",
            "count": len(items),
            "items": items,
        })
    except Exception as e:
        logger.debug("learning/all - draft rules error: %s", e)
        categories.append({
            "id": "draft-rules",
            "name": "Règles de rédaction",
            "description": "Règles extraites des corrections de brouillons",
            "count": 0,
            "items": [],
        })

    # ── Savoirs: per-account knowledge from DB onboarding ──
    # Was the global ``container.config.knowledge_path`` (knowledge/memoire.md),
    # a single file shared across tenants — the #533 leak. We read the caller's
    # own KB via ``load_knowledge_from_db(account_id)`` and deliberately do NOT
    # fall back to the global file (unlike ``MemoryManager.get_memory``), so an
    # unresolved account (sentinel -1) yields zero Savoir instead of another
    # tenant's. ``build_knowledge_markdown`` emits the same "## Savoir" / "### "
    # structure the parser below expects.
    try:
        kb_text = ""
        if account_id and account_id > 0:
            from app._prompts_monolith import load_knowledge_from_db
            kb_text = load_knowledge_from_db(account_id) or ""

        savoir_items = []
        # Parse chaque section "## Savoir" (et sous-sections ### …)
        in_savoir = False
        current_block: list[str] = []

        def _flush_block(lines: list[str]) -> None:
            content = "\n".join(lines).strip()
            if content:
                # The id MUST match the slug that DELETE /learning/savoirs/<id>
                # derives from the block heading, or deletion silently 404s
                # (audit 2026-05-29: list emitted index ids `savoir-0…` while
                # delete matched `savoir-<question-slug>` → they never agreed).
                question_line = (lines[0].strip() if lines else "")
                slug = re.sub(r'[^a-z0-9]+', '-', question_line.lower())[:40].strip('-')
                savoir_items.append({
                    "id": f"savoir-{slug}" if slug else f"savoir-{len(savoir_items)}",
                    "text": content,
                })

        for line in kb_text.splitlines():
            if line.startswith("## Savoir"):
                in_savoir = True
                _flush_block(current_block)
                current_block = []
            elif line.startswith("## ") and in_savoir:
                # Nouvelle section de niveau 2 → fin du bloc Savoir
                _flush_block(current_block)
                current_block = []
                in_savoir = False
            elif in_savoir:
                if line.startswith("### "):
                    # Sous-section → flush le bloc précédent et démarrer un nouveau
                    _flush_block(current_block)
                    heading = line[4:].strip()
                    # Skip Contact/Projet entries — not useful as knowledge
                    if re.match(r'^(Contact|Projet)\s*:', heading, re.IGNORECASE):
                        current_block = []
                    else:
                        current_block = [heading]
                else:
                    current_block.append(line)

        _flush_block(current_block)

        categories.append({
            "id": "savoirs",
            "name": "Savoirs",
            "description": "Connaissances enregistrées dans la base de connaissances",
            "count": len(savoir_items),
            "items": savoir_items,
        })
    except Exception as e:
        logger.debug("learning/all - savoirs error: %s", e)
        categories.append({
            "id": "savoirs",
            "name": "Savoirs",
            "description": "Connaissances enregistrées dans la base de connaissances",
            "count": 0,
            "items": [],
        })

    return jsonify({"categories": categories})


@api_bp.route("/writing-style", methods=["GET"])
def writing_style():
    """Profil de style d'écriture détecté."""
    try:
        account_id = _resolve_account_id_for_user()
        container = _rh._get_container()
        style_store = container.get_writing_style_store()

        # Only load the current user's profile, not all accounts
        items = []
        profile = style_store.load(account_id)
        if profile:
            aid = account_id
            if profile.preferred_greetings:
                for g in profile.preferred_greetings[:3]:
                    items.append({
                        "id": f"greeting-{aid}-{g}",
                        "kind": "greeting",
                        "value": g,
                        "account_id": aid,
                    })
            if profile.preferred_closings:
                for c in profile.preferred_closings[:3]:
                    items.append({
                        "id": f"closing-{aid}-{c}",
                        "kind": "closing",
                        "value": c,
                        "account_id": aid,
                    })
            if profile.typical_signature:
                items.append({
                    "id": f"signature-{aid}",
                    "kind": "signature",
                    "value": profile.typical_signature,
                    "account_id": aid,
                })
            formality = getattr(profile.formality_level, "value", str(profile.formality_level)) if profile.formality_level else None
            if formality:
                items.append({
                    "id": f"formality-{aid}",
                    "kind": "formality",
                    "value": formality,
                    "account_id": aid,
                })

        email_count = 0
        defaults = {}
        if profile:
            email_count = profile.email_count
            defaults = {
                "formality_level": getattr(profile.formality_level, "value", str(profile.formality_level)) if profile.formality_level else "mixed",
                "preferred_greetings": profile.preferred_greetings or [],
                "preferred_closings": profile.preferred_closings or [],
                "typical_signature": profile.typical_signature,
            }

        return jsonify({
            "items": items,
            "defaults": defaults,
            "email_count": email_count,
        })
    except Exception as e:
        logger.debug("writing-style error: %s", e)
        return jsonify({"items": [], "email_count": 0})


@api_bp.route("/writing-style/profile", methods=["GET"])
def writing_style_profile():
    """Métriques de style observées (lecture seule) pour le widget « Style
    observé depuis l'outbox ».

    Avant ce endpoint, le widget (`StyleObservedFromOutbox.tsx`) appelait
    `GET /api/writing-style/profile` — une route inexistante (404 silencieux) —
    et n'affichait donc AUCUNE métrique au chargement de la page : il fallait
    cliquer « Re-analyser » pour voir des chiffres. Les 4 métriques sont
    pourtant déjà persistées dans le `WritingStyleProfile` ; on les ré-expose
    ici pour un affichage stable. Account scoping par le JWT.
    """
    try:
        account_id = _resolve_account_id_for_user()
        style_store = _rh._get_container().get_writing_style_store()
        profile = style_store.load(account_id)
        if not profile:
            return jsonify({"profile": None})

        def _f(name: str, default: float = 0.0) -> float:
            v = getattr(profile, name, None)
            return float(v) if isinstance(v, (int, float)) else default

        return jsonify({
            "profile": {
                "avg_sentence_length": _f("avg_sentence_length"),
                "sentence_length_variance": _f("sentence_length_variance"),
                "vocabulary_density": _f("vocabulary_density"),
                # formality_score has no neutral 0 — default to 0.5 (mixed) so
                # the gauge doesn't read "0% formal" for an unmeasured profile.
                "formality_score": _f("formality_score", 0.5),
                "emoji_frequency": _f("emoji_frequency"),
                "exclamation_rate": _f("exclamation_rate"),
                "avg_paragraph_count": _f("avg_paragraph_count"),
                "email_count": int(getattr(profile, "email_count", 0) or 0),
            }
        })
    except Exception as e:
        logger.debug("writing-style/profile error: %s", e)
        return jsonify({"profile": None})


@api_bp.route("/learning/corrections/<correction_id>", methods=["DELETE"])
def delete_draft_correction(correction_id: str):
    """
    Supprime une correction de brouillon par son email_id/timestamp.
    """
    try:
        account_id = _resolve_account_id_for_user()
        from app.draft_learning import get_draft_learning_store
        store = get_draft_learning_store(account_id=account_id)
        with store._lock:
            before = len(store._corrections)
            store._corrections = [
                c for c in store._corrections
                if c.get("email_id", c.get("timestamp", "")) != correction_id
            ]
            removed = before - len(store._corrections)
            if removed > 0:
                store._save()
        if removed == 0:
            return jsonify({"error": "Correction not found"}), 404
        return jsonify({"message": "Correction deleted"}), 200
    except Exception as e:
        logger.error(f"Failed to delete draft correction: {e}")
        return jsonify({"error": str(e)}), 500


_AUTOMATED_LOCAL_PREFIXES = (
    "invoice", "billing", "receipt", "statement", "notification",
)


def _is_noise_contact(email_addr: str) -> bool:
    """Return True for noreply / automated / known-noise addresses.

    Mirrors the filters used by routes_contacts.py so the Training screen
    doesn't display newsletter/noreply/transactional senders that leaked
    into WritingStyleProfile.contact_profiles.
    """
    addr = (email_addr or "").strip().lower()
    if not addr or "@" not in addr:
        return True
    local, _, domain = addr.partition("@")
    if any(addr.startswith(p) for p in _NOREPLY_PATTERNS):
        return True
    if "noreply" in local or "no-reply" in local or "donotreply" in local or "do-not-reply" in local:
        return True
    if any(domain == nd or domain.endswith("." + nd) for nd in _NOISE_DOMAINS):
        return True
    if local.startswith(_AUTOMATED_LOCAL_PREFIXES):
        return True
    return False


@api_bp.route("/writing-style/contacts", methods=["GET"])
def list_contact_styles():
    """Liste tous les profils de style per-contact (filtre noise/noreply).

    One-shot backfill: if contact_profiles is empty but the onboarding
    detected contacts, rehydrate from onboarding_results before returning.
    Repairs accounts whose onboarding ran before the lazy-create fix shipped.
    """
    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        if not account_id:
            return jsonify({"contacts": [], "account_id": None})

        profile = style_store.load(account_id)

        def _has_any_enrichment(cp_dict: dict) -> bool:
            """True if at least one contact has a non-null style field.

            Placeholder-only contacts (just `{email: {...all None...}}`) count
            as no enrichment — the backfill should rehydrate from the latest
            onboarding_results to repair that state.
            """
            if not cp_dict:
                return False
            for data in cp_dict.values():
                if not isinstance(data, dict):
                    continue
                if any(data.get(k) for k in (
                    "formality_override", "preferred_greeting", "preferred_closing",
                    "langue", "langue_variante", "nickname",
                )):
                    return True
            return False

        if not profile or not _has_any_enrichment(profile.contact_profiles):
            try:
                from app.onboarding.manager import rehydrate_contact_profiles_from_onboarding
                if rehydrate_contact_profiles_from_onboarding(account_id) > 0:
                    profile = style_store.load(account_id)
            except Exception as e:
                logger.warning("Contact profile backfill skipped for account %s: %s", account_id, e)

        # Reconcile Contact counters against the Email table once per process.
        # Historical sent emails never bumped sent_count (pre-fix sync ignored
        # recipients), so without this step karine@gmail.com — received from +
        # replied to via Gmail — would look one-way and get filtered out.
        from sqlalchemy import select, and_
        from app.db.database import get_db_session
        from app.db.models.contact import Contact
        from app.db.repositories.contact_repository import ContactRepository
        acct_id_int = int(account_id)
        last_run = _contact_counts_reconciled.get(acct_id_int, 0.0)
        if _time.time() - last_run > _RECONCILE_TTL_SECONDS:
            try:
                with get_db_session() as sess:
                    stats = ContactRepository(sess).recompute_counts_from_emails(acct_id_int)
                    sess.commit()
                logger.info(
                    "Reconciled contact counts for account %s: %s", acct_id_int, stats
                )
                _contact_counts_reconciled[acct_id_int] = _time.time()
            except Exception as e:
                logger.warning(
                    "Contact counts reconciliation failed for account %s: %s",
                    acct_id_int, e,
                )

        # True bidirectional filter: show contacts the user has both written to
        # AND received from. One-way senders (newsletters, cold outreach) and
        # one-way recipients (fire-and-forget pings) are excluded. Both counts
        # come from the Email table via the reconciliation above, so they
        # include Gmail/Outlook/IMAP sends — not just Agentys sends.
        # SEC-004: cap at 5 000 to avoid OOM on large contact lists.
        #
        # Fresh-account fallback: just after onboarding, the sent folder may
        # not be synced yet (only INBOX has been ingested) so sent_count=0
        # for every contact and bidirectional={} — wiping the entire
        # onboarding-derived list and showing "no contacts" even though the
        # scan succeeded. When the filter is empty AND we have profile
        # contacts to show, fall through to no-filter mode rather than
        # silently zeroing the UI. The reconciliation TTL (6h) ensures the
        # filter kicks in once the sent folder catches up.
        bidirectional: set[str] | None = set()
        # The account's own address: a self-send must never become a
        # per-contact "writing style for yourself". _is_noise_contact doesn't
        # catch it (it's a normal personal address), so resolve it explicitly.
        self_email = ""
        try:
            with get_db_session() as sess:
                rows = sess.execute(
                    select(Contact.email).where(
                        and_(
                            Contact.account_id == acct_id_int,
                            Contact.sent_count >= 2,
                            Contact.received_count >= 1,
                        )
                    ).limit(5000)
                ).all()
                bidirectional = {(r[0] or "").lower() for r in rows if r[0]}
                try:
                    from app.db.repositories.account_repository import AccountRepository
                    _acct_row = AccountRepository(sess).get(acct_id_int)
                    self_email = (getattr(_acct_row, "email", "") or "").strip().lower()
                except Exception:
                    self_email = ""
        except Exception as e:
            logger.warning("Failed to load bidirectional contacts for account %s: %s", account_id, e)
            bidirectional = None

        if bidirectional == set() and profile is not None and profile.contact_profiles:
            # No bidirectional evidence yet (sent folder not synced or one-way
            # mailbox) but onboarding extracted contacts we can show. Disable
            # the filter so the user sees the scan output instead of an empty
            # list. Noise heuristic still applies below.
            bidirectional = None

        from app.domain.entities.writing_style import ContactStyleProfile
        if profile is None and bidirectional:
            # Reconciliation may have created brand-new contacts that were never
            # in the onboarding-derived profile. Materialise an empty profile so
            # the placeholder loop below can add them.
            try:
                profile = style_store.get_or_create_empty(acct_id_int)
            except Exception as e:
                logger.warning("Could not create empty WritingStyleProfile: %s", e)

        # Ensure every bidirectional contact has a ContactStyleProfile entry,
        # even if onboarding never saw them (e.g. new correspondents since
        # onboarding ran). Without this, a valid bidirectional contact like
        # karine@gmail.com would pass the filter but have no profile entry to
        # iterate over, and never reach the UI.
        profile_changed = False
        if profile is not None and bidirectional:
            existing_keys = {k.lower() for k in profile.contact_profiles.keys()}
            for addr in bidirectional:
                if _is_noise_contact(addr):
                    continue
                if addr not in existing_keys:
                    profile.contact_profiles[addr] = ContactStyleProfile(email=addr).to_dict()
                    profile_changed = True
            if profile_changed:
                try:
                    style_store.save(profile)
                except Exception as e:
                    logger.warning("Failed to persist ContactStyleProfile placeholders: %s", e)

        if profile is None or not profile.contact_profiles:
            return jsonify({"contacts": [], "account_id": acct_id_int})

        contacts = []
        for _key, data in profile.contact_profiles.items():
            try:
                cp = ContactStyleProfile.from_dict(data)
            except Exception:
                continue
            has_human_signal = bool(
                cp.nickname
                or cp.preferred_greeting
                or cp.preferred_closing
                or cp.preferred_signature
            )
            # Un contact AJOUTÉ/ÉDITÉ à la main dans Settings → Entraînement ne
            # doit JAMAIS être filtré comme « non bidirectionnel » : le PUT
            # n'écrit que profile.contact_profiles et ne crée aucune ligne
            # Contact, donc un contact fraîchement saisi n'a aucun compteur
            # sent/received et disparaîtrait au prochain GET alors que
            # l'utilisateur vient de le créer (bug 2026-06-23 « j'ajoute un
            # contact mais il ne s'enregistre pas »).
            # On se fonde UNIQUEMENT sur formality_locked : ce flag n'est posé
            # QUE par un PUT manuel (l'auto-dérivation par envoi le laisse à
            # False). On ne réutilise PAS has_human_signal ici — un surnom /
            # une salutation peuvent être auto-dérivés, et le contrat produit
            # veut qu'un contact à sens unique reste filtré malgré ces signaux.
            manually_set = bool(cp.formality_locked)
            # Self-exclusion: never list the account's own address (self-sends).
            if self_email and _key.lower() == self_email:
                continue
            if (
                bidirectional is not None
                and _key.lower() not in bidirectional
                and not manually_set
            ):
                # Contact floor requested in Notion: received >= 1 AND sent >= 2.
                # Keep the fresh-account fallback above, but once counts exist,
                # don't let classified one-way contacts bypass the threshold
                # (sauf ajout/édition manuelle — voir manually_set ci-dessus).
                continue
            if _is_noise_contact(_key):
                # The noise heuristic (support@, info@, …) has false positives
                # for small companies where a real person uses a shared inbox.
                # Trust the KnowledgeAgent + StyleAgent classification when we
                # have a human signal (nickname, greeting, or closing) — ou un
                # ajout manuel explicite (formality_locked).
                if not has_human_signal and not manually_set:
                    continue
            contacts.append(cp.to_dict())

        return jsonify({"contacts": contacts, "account_id": acct_id_int})
    except Exception as e:
        logger.error("Error listing contact styles: %s", e)
        return jsonify({"contacts": []})


@api_bp.route("/writing-style/contact-style", methods=["GET"])
def get_contact_style():
    """Retourne le style mémorisé pour un contact."""
    contact_email = (request.args.get("contact_email") or "").strip().lower()
    if not contact_email:
        return jsonify({"error": "contact_email required"}), 400

    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        if not account_id:
            return jsonify({"error": "No account"}), 403

        profile = style_store.load(account_id)
        contact_data = profile.contact_profiles.get(contact_email) if profile else None
        if not contact_data:
            return jsonify({
                "contact_email": contact_email,
                "style": None,
                "preferred_signature": None,
            })

        from app.domain.entities.writing_style import ContactStyleProfile
        contact = ContactStyleProfile.from_dict(contact_data)
        return jsonify({
            "contact_email": contact_email,
            "style": contact.to_dict(),
            "preferred_signature": contact.preferred_signature,
        })
    except Exception as e:
        logger.error("Error getting contact style: %s", e)
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/writing-style/contact-style", methods=["PUT"])
def upsert_contact_style():
    """Crée ou met à jour le style per-contact complet."""
    data, err = require_json()
    if err:
        return err
    contact_email = data.get("contact_email", "").strip().lower()
    if not contact_email:
        return jsonify({"error": "contact_email required"}), 400

    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        if not account_id:
            return jsonify({"error": "No account"}), 403

        # Filtrage bloqué/spam
        try:
            from app.multi_accounts import get_account_manager
            manager = get_account_manager()
            if not manager.is_sender_allowed(account_id, contact_email):
                return jsonify({"error": "contact_blocked"}), 400
        except Exception:
            pass  # Si le manager n'est pas disponible, on continue

        # Filtrage noise
        try:
            from app.infrastructure.sender_reputation_store import get_reputation_store
            rep_store = get_reputation_store()
            reputation = rep_store.get_sender_reputation(contact_email, account_id=account_id)
            if reputation and reputation.get("dominant_label") == "Noise" and reputation.get("confidence", 0) > 0.7:
                return jsonify({"error": "contact_noise"}), 400
        except Exception:
            pass  # Si le store n'est pas disponible, on continue

        profile = style_store.load(account_id)
        if not profile:
            from app.domain.entities.writing_style import WritingStyleProfile
            profile = WritingStyleProfile.create_empty(account_id)

        # Résoudre la formalité
        from app.domain.entities.writing_style import FormalityLevel
        form_override = None
        form_str = data.get("formality_override")
        if form_str is not None:
            if form_str == "" or form_str is None:
                form_override = None  # Clear
            else:
                try:
                    form_override = FormalityLevel(form_str.strip().lower())
                except ValueError:
                    valid = [f.value for f in FormalityLevel]
                    return jsonify({"error": f"Invalid formality. Valid: {valid}"}), 400

        # Manual edits via the Training UI always lock formality so the
        # per-send auto-derivation path doesn't quietly overwrite them.
        # The frontend can also pass `formality_locked=false` explicitly to
        # release the lock (the "Back to auto" button).
        manual_lock = data.get("formality_locked")
        if manual_lock is None:
            # Default: lock when the user touched formality_override in
            # the request body (treats a successful PUT as intent).
            manual_lock = "formality_override" in data
        signature = data.get("preferred_signature")
        if signature is not None:
            if not isinstance(signature, str):
                return jsonify({"error": "preferred_signature must be a string"}), 400
            signature = signature.replace("\r\n", "\n").replace("\r", "\n").strip()
            if len(signature) > 2000:
                return jsonify({"error": "preferred_signature too long (max 2000 chars)"}), 400
        profile.update_contact_profile(
            email=contact_email,
            formality_override=form_override,
            greeting=data.get("preferred_greeting"),
            closing=data.get("preferred_closing"),
            signature=signature,
            langue_variante=data.get("langue_variante"),
            langue=data.get("langue"),
            nickname=data.get("nickname"),
            formality_locked=bool(manual_lock) if manual_lock is not None else None,
        )
        style_store.save(profile)

        return jsonify({"success": True, "contact_email": contact_email})
    except Exception as e:
        logger.error("Error upserting contact style: %s", e)
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/writing-style/contact-style", methods=["DELETE"])
def delete_contact_style():
    """Supprime un profil de style per-contact."""
    data, err = require_json()
    if err:
        return err
    contact_email = data.get("contact_email", "").strip().lower()
    if not contact_email:
        return jsonify({"error": "contact_email required"}), 400

    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        if not account_id:
            return jsonify({"error": "No account"}), 403

        profile = style_store.load(account_id)
        if not profile:
            return jsonify({"error": "Profile not found"}), 404

        if contact_email not in profile.contact_profiles:
            return jsonify({"error": "Contact style not found"}), 404

        del profile.contact_profiles[contact_email]
        style_store.save(profile)

        return jsonify({"success": True, "contact_email": contact_email})
    except Exception as e:
        logger.error("Error deleting contact style: %s", e)
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/contact-language", methods=["GET"])
def get_contact_language():
    """Retourne le code langue (ISO 639-1) à utiliser pour la dictée Whisper.

    Source : ``ContactStyleProfile.langue`` ou les 2 premiers caractères de
    ``langue_variante`` (`fr-CA` → `fr`). Sert au frontend pour passer un hint
    `lang=` à `/api/transcribe` au lieu d'utiliser auto-detect (qui ajoute
    2-4s de latence sur audio court et biaise EN sur français court).

    Renvoie ``{"language": null}`` quand le contact est inconnu, le profil
    n'a pas de langue persistée, ou l'account_id ne peut pas être résolu —
    le frontend retombera alors sur ``navigator.language`` ou auto-detect.

    Query params:
        email (str): destinataire — case-insensitive, trim.
    """
    # F-04 (audit 2026-04-30): mirror frontend `_normalize` — strip the
    # display-name wrapper if present ("Alex Smith <alex@example.com>" →
    # "alex@example.com"). The frontend hook does this too, but keeping
    # both sides robust means the endpoint is also correct when called
    # directly (curl, mobile app, future integrations).
    raw_email = (request.args.get("email") or "").strip()
    import re as _re
    _bracketed = _re.search(r"<([^>]+)>", raw_email)
    contact_email = (_bracketed.group(1) if _bracketed else raw_email).strip().lower()
    if not contact_email or "@" not in contact_email:
        return jsonify({"language": None})

    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        # F-03 (audit 2026-04-30): _resolve_account_id_cached returns int -1
        # sentinel when no JWT account is resolved (routes_helpers.py:541).
        # `not -1` is False (truthy), so the legacy `if not account_id`
        # never fired and the call to load(-1) was relied upon for accidental
        # safety. Use the same guard the rest of the codebase uses
        # (websocket.py:419, _compose_path.py:148).
        if not account_id or account_id <= 0:
            return jsonify({"language": None})

        profile = style_store.load(account_id)
        if not profile or not profile.contact_profiles:
            return jsonify({"language": None})

        contact_data = profile.contact_profiles.get(contact_email)
        if not isinstance(contact_data, dict):
            return jsonify({"language": None})

        # Priorité : langue_variante (`fr-CA`) → langue (`fr`).
        # On extrait toujours le code à 2 lettres, c'est ce que Whisper attend.
        variant = (contact_data.get("langue_variante") or "").strip().lower()
        langue = (contact_data.get("langue") or "").strip().lower()
        code = (variant.split("-")[0] if variant else langue) or None

        # Whitelist : seulement les codes que /api/transcribe accepte. Évite
        # qu'un champ DB corrompu (`xx`, `??`) ne fasse exploser Whisper.
        _SUPPORTED = {"fr", "en", "es", "de", "it", "pt", "ja", "zh", "ar"}
        if code not in _SUPPORTED:
            code = None

        return jsonify({"language": code})
    except Exception as e:
        logger.warning("Error fetching contact language for %s: %s", contact_email, e)
        return jsonify({"language": None})


@api_bp.route("/writing-style/defaults", methods=["PATCH"])
def update_style_defaults():
    """Met à jour les réglages de style par défaut (salutation, clôture, signature)."""
    data, err = require_json()
    if err:
        return err

    try:
        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        account_id = _rh._resolve_account_id_cached()
        if not account_id:
            return jsonify({"error": "No account"}), 403

        profile = style_store.load(account_id)
        if not profile:
            from app.domain.entities.writing_style import WritingStyleProfile
            profile = WritingStyleProfile.create_empty(account_id)

        # Salutation FORMELLE par défaut → slot [0] (positional set).
        # NE PAS faire insert(0, …) : cela décalerait l'ancien formel vers [1]
        # (le slot DÉCONTRACTÉ) et corromprait la salutation casual de
        # l'utilisateur. Les consommateurs (smart_routing._compute_greeting_hint :
        # « index 0 = formel, index 1 = casual ») et le panneau Style traitent
        # ces slots comme POSITIONNELS. Le slot [1] est géré séparément ci-dessous.
        greeting = data.get("preferred_greeting")
        if greeting is not None:
            greeting = greeting.strip()
            if greeting:
                if not profile.preferred_greetings:
                    profile.preferred_greetings.append(greeting)
                else:
                    profile.preferred_greetings[0] = greeting

        # Clôture FORMELLE par défaut → slot [0] (positional set, même raison).
        closing = data.get("preferred_closing")
        if closing is not None:
            closing = closing.strip()
            if closing:
                if not profile.preferred_closings:
                    profile.preferred_closings.append(closing)
                else:
                    profile.preferred_closings[0] = closing

        # Salutation décontractée (index 1)
        greeting_casual = data.get("preferred_greeting_casual")
        if greeting_casual is not None:
            greeting_casual = greeting_casual.strip()
            if greeting_casual:
                # Ensure slot [1] exists
                while len(profile.preferred_greetings) < 2:
                    profile.preferred_greetings.append("")
                profile.preferred_greetings[1] = greeting_casual

        # Clôture décontractée (index 1)
        closing_casual = data.get("preferred_closing_casual")
        if closing_casual is not None:
            closing_casual = closing_casual.strip()
            if closing_casual:
                while len(profile.preferred_closings) < 2:
                    profile.preferred_closings.append("")
                profile.preferred_closings[1] = closing_casual

        # Signature
        signature = data.get("typical_signature")
        if signature is not None:
            profile.typical_signature = signature.strip() or None

        style_store.save(profile)

        return jsonify({
            "success": True,
            "defaults": {
                "preferred_greetings": profile.preferred_greetings,
                "preferred_closings": profile.preferred_closings,
                "typical_signature": profile.typical_signature,
            },
        })
    except Exception as e:
        logger.error("Error updating style defaults: %s", e)
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/learning/savoirs/<savoir_id>", methods=["DELETE"])
def delete_savoir(savoir_id: str):
    """
    Supprime un savoir (Q&A) de la base de connaissances.
    Retire le bloc ### Question / Reponse correspondant de memoire.md.
    """
    try:
        from app.memory_manager import get_memory_manager
        from app.api.routes_helpers import _resolve_account_id_for_user
        _aid = _resolve_account_id_for_user()
        mm = get_memory_manager(account_id=_aid if _aid > 0 else None)
        content = mm.get_memory()

        # Find ## Savoir section and parse Q&A blocks
        savoir_match = re.search(r'((?:^|\n)## Savoir\s*\n)(.*?)(?=\n## |\Z)', content, re.DOTALL)
        if not savoir_match:
            return jsonify({"error": "Savoir section not found"}), 404

        savoir_text = savoir_match.group(2)

        # Find the block matching this savoir_id
        qa_blocks = re.split(r'(\n### )', savoir_text)
        new_blocks = []
        removed = False

        i = 0
        while i < len(qa_blocks):
            block = qa_blocks[i]
            if block.strip() == '### ' or block == '\n### ':
                # Next element is the content after ###
                if i + 1 < len(qa_blocks):
                    full_block = block + qa_blocks[i + 1]
                    question_line = qa_blocks[i + 1].split('\n', 1)[0].strip()
                    slug = re.sub(r'[^a-z0-9]+', '-', question_line.lower())[:40].strip('-')
                    block_id = f"savoir-{slug}"
                    if block_id == savoir_id:
                        removed = True
                        i += 2
                        continue
                    new_blocks.append(full_block)
                    i += 2
                    continue
            new_blocks.append(block)
            i += 1

        if not removed:
            return jsonify({"error": "Savoir not found"}), 404

        new_savoir = ''.join(new_blocks).strip()
        new_content = content[:savoir_match.start(2)] + ('\n' + new_savoir + '\n' if new_savoir else '\n') + content[savoir_match.end(2):]
        mm.update_memory(new_content, change_summary=f"Deleted savoir: {savoir_id}")

        return jsonify({"message": "Savoir deleted"}), 200
    except Exception as e:
        logger.error(f"Failed to delete savoir: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# COSTS
# ============================================================================

@api_bp.route("/costs", methods=["GET"])
@require_admin
def costs():
    """
    Breakdown des couts actuels. **Admin only (transition).

    Note: CostManager reste en legacy pour l'instant.

    Returns:
        Statistiques de couts.
    """
    _resolve_account_id_for_user()
    # CostManager reste en legacy (a migrer dans une future iteration)
    # TODO: scope cost data by account_id once cost_tracking table has account_id column
    from app.infrastructure.cost_manager import get_cost_manager
    manager = get_cost_manager()

    return jsonify({
        "current_month": manager.get_current_month_stats(),
        "by_agent": manager.get_breakdown_by_agent(),
        "budget": {
            "monthly_limit": manager.monthly_budget,
            "alert_threshold": manager.alert_threshold,
        },
    })


@api_bp.route("/costs/history", methods=["GET"])
@require_admin
def cost_history():
    """
    Historique des couts. **Admin only (transition).

    Note: CostManager reste en legacy pour l'instant.

    Query params:
        days: Nombre de jours (default: 30)

    Returns:
        Historique quotidien des couts.
    """
    _resolve_account_id_for_user()
    days = request.args.get("days", 30, type=int)

    # CostManager reste en legacy (a migrer dans une future iteration)
    # TODO: scope cost history by account_id once cost_tracking table has account_id column
    from app.infrastructure.cost_manager import get_cost_manager
    return jsonify({
        "days": days,
        "history": get_cost_manager().get_daily_costs(days=days),
    })


# ============================================================================
# ANALYTICS
# ============================================================================

@api_bp.route("/analytics/quality", methods=["GET"])
@require_admin
def analytics_quality():
    """
    Metriques de qualite des reponses. **Admin only (transition).

    Utilise AnalyticsPort via le Container DI.

    Returns:
        Scores de qualite.
    """
    _resolve_account_id_for_user()
    # Clean Architecture: utiliser le port via Container DI
    # TODO: pass account_id to get_quality_metrics() once Analytics supports it
    return jsonify(_rh._get_container().get_analytics().get_quality_metrics())


@api_bp.route("/analytics/comparison", methods=["GET"])
@require_admin
def analytics_comparison():
    """
    Comparaison IA vs humain. **Admin only (transition).

    Utilise AnalyticsPort via le Container DI.

    Returns:
        Metriques comparatives.
    """
    _resolve_account_id_for_user()
    # Clean Architecture: utiliser le port via Container DI
    # TODO: pass account_id to get_ai_vs_human_comparison() once Analytics supports it
    return jsonify(_rh._get_container().get_analytics().get_ai_vs_human_comparison())


# ============================================================================
# DRAFT COMPLETION
# ============================================================================

# Security: Input validation constants for complete_draft
MAX_RAW_INPUT_LENGTH = 10000
MAX_RECIPIENT_LENGTH = 200
MAX_SUBJECT_HINT_LENGTH = 500


def _truncate_text(text: str, max_length: int) -> str:
    """Tronque le texte à la longueur maximale avec ellipse."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


@api_bp.route("/drafts/complete", methods=["POST"])
def complete_draft():
    """
    Complète un brouillon à partir d'idées brèves.

    Transforme des bullet points, notes ou idées courtes
    en email professionnel complet et structuré.

    Body JSON:
        raw_input: str - Les idées brèves (requis, max 10000 chars)
        recipient: str - Le destinataire (optionnel, max 200 chars)
        tone: str - Le ton souhaité: formal, friendly, urgent, conciliatory, neutral (optionnel)
        subject_hint: str - Indice sur le sujet (optionnel, max 500 chars)

    Returns:
        JSON avec le brouillon complété.

    Example:
        POST /api/drafts/complete
        {
            "raw_input": "Brouillon:\\n- Remercier Sophie pour son retour rapide\\n- Proposer réunion mardi ou jeudi",
            "recipient": "Sophie",
            "tone": "friendly"
        }
    """
    data, error = require_json()
    if error:
        return error

    raw_input = data.get("raw_input")
    if not raw_input:
        return jsonify({"error": "raw_input is required"}), 400

    # Security: Validate input lengths to prevent DoS/resource exhaustion
    if not isinstance(raw_input, str):
        return jsonify({"error": "raw_input must be a string"}), 400
    # Security: Reject whitespace-only input as invalid
    if not raw_input.strip():
        return jsonify({"error": "raw_input cannot be empty or whitespace only"}), 400
    if len(raw_input) > MAX_RAW_INPUT_LENGTH:
        return jsonify({
            "error": f"raw_input exceeds maximum length of {MAX_RAW_INPUT_LENGTH} characters"
        }), 400

    # Paramètres optionnels
    recipient = data.get("recipient")
    subject_hint = data.get("subject_hint")
    tone_str = data.get("tone")

    # Security: Validate optional parameter lengths
    _, error = _validate_optional_string(recipient, "recipient", MAX_RECIPIENT_LENGTH)
    if error:
        return error

    _, error = _validate_optional_string(subject_hint, "subject_hint", MAX_SUBJECT_HINT_LENGTH)
    if error:
        return error

    # Convertir le ton en enum
    tone = None
    if tone_str is not None:
        # Security: Validate tone is a non-empty string before processing
        if not isinstance(tone_str, str):
            return jsonify({"error": "tone must be a string"}), 400
        if not tone_str.strip():
            return _invalid_tone_response()
        try:
            tone = DraftInputTone(tone_str.lower())
        except ValueError:
            return _invalid_tone_response()

    try:
        # Utiliser le Container DI pour obtenir le use case
        container = _rh._get_container()
        use_case = container.get_complete_draft_use_case()

        # Créer l'input pour le use case
        from app.domain.entities import DraftInput
        draft_input = DraftInput(
            raw_input=raw_input,
            recipient=recipient,
            tone=tone if tone is not None else DraftInputTone.NEUTRAL,
            subject_hint=subject_hint,
        )

        result = use_case.execute(draft_input)

        return jsonify({
            "success": True,
            "subject": result.subject,
            "body": result.body,
            "recipient": result.recipient,
            "tone_used": result.tone_used.value,
            "formatted_output": result.formatted_output,
        })

    except Exception as e:
        logger.error(f"Error completing draft: {type(e).__name__}")
        return jsonify({"error": "An internal error occurred while completing draft"}), 500


# Security: Max length for detect text to prevent DoS
MAX_DETECT_TEXT_LENGTH = 5000


@api_bp.route("/drafts/detect", methods=["POST"])
def detect_draft_request():
    """
    Détecte si un texte est une demande de complétion de brouillon.

    Body JSON:
        text: str - Le texte à analyser (max 5000 chars)

    Returns:
        JSON avec is_draft_request: bool
    """
    data, error = require_json()
    if error:
        return error

    text = data.get("text")
    if not text:
        return jsonify({"error": "text is required"}), 400

    # Security: Validate text type and length to prevent DoS
    if not isinstance(text, str):
        return jsonify({"error": "text must be a string"}), 400
    if len(text) > MAX_DETECT_TEXT_LENGTH:
        return jsonify({
            "error": f"text exceeds maximum length of {MAX_DETECT_TEXT_LENGTH} characters"
        }), 400

    is_draft_fn = _get_legacy_modules()["is_draft_request"]
    is_draft = is_draft_fn(text)

    return jsonify({
        "is_draft_request": is_draft,
        "text_preview": _truncate_text(text, 100),
    })


# ============================================================================
# TASKS
# ============================================================================

# Security: Input validation constants for list_tasks
LIST_TASKS_MIN_LIMIT = 1
LIST_TASKS_MAX_LIMIT = 1000
LIST_TASKS_DEFAULT_LIMIT = 100

VALID_TASK_STATUSES = frozenset({"pending", "completed", "all"})
VALID_PRIORITIES = frozenset({"low", "medium", "high"})

# Security: Input length limits to prevent DoS
MAX_TITLE_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 5000
MAX_SUBJECT_LENGTH = 998  # RFC 5322 recommends max 78 chars, but allows up to 998
MAX_BODY_LENGTH = 1_000_000  # 1MB reasonable max for email body

# Security: Regex for ISO 8601 date format validation (YYYY-MM-DD)
DEADLINE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_deadline(deadline: str) -> bool:
    """Validate deadline is a valid ISO 8601 date (YYYY-MM-DD)."""
    if not DEADLINE_PATTERN.match(deadline):
        return False
    try:
        year, month, day = map(int, deadline.split("-"))
        # Basic date validation
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        # More precise validation using datetime
        datetime(year, month, day)
        return True
    except (ValueError, TypeError):
        return False


@api_bp.route("/tasks", methods=["GET"])
def list_tasks():
    status = request.args.get("status", "pending")
    if status not in VALID_TASK_STATUSES:
        return jsonify({"error": f"Invalid status. Allowed: {', '.join(VALID_TASK_STATUSES)}"}), 400

    limit, error = _validate_limit(
        LIST_TASKS_MIN_LIMIT,
        LIST_TASKS_MAX_LIMIT,
        LIST_TASKS_DEFAULT_LIMIT
    )
    if error:
        return error

    # AUTHZ-VULN-04 (Shannon pentest 2026-05-05, issue #557): scope by
    # caller's account_id so each tenant only sees their own tasks.
    account_id = _resolve_account_id_for_user()
    task_repo = _rh._get_container().get_task_repository()
    tasks = task_repo.get_all(status=status, limit=limit, account_id=account_id)
    return jsonify({"tasks": tasks, "count": len(tasks)})


@api_bp.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id: int):
    # AUTHZ-VULN-04 (issue #557): pre-fix, any JWT user could read any
    # other user's task by ID. Fix: scope get_by_id to the caller's
    # account_id; tasks owned by another account return 404
    # (anti-enumeration, no leak of "task exists but isn't yours").
    account_id = _resolve_account_id_for_user()
    task = _rh._get_container().get_task_repository().get_by_id(
        task_id, account_id=account_id
    )
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@api_bp.route("/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id: int):
    # AUTHZ-VULN-04 (issue #557): same scoping. Pre-fix: a foreign user
    # could mark other tenants' tasks completed.
    account_id = _resolve_account_id_for_user()
    data, error = require_json()
    if error:
        return error
    if data.get("status") == "completed":
        success = _rh._get_container().get_task_repository().mark_completed(
            task_id, account_id=account_id
        )
        if not success:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"success": True, "task_id": task_id, "status": "completed"})
    return jsonify({"error": "Only status=completed is supported"}), 400


@api_bp.route("/tasks", methods=["POST"])
def create_task():
    data, error = require_json()
    if error:
        return error

    title = data.get("title")
    if not title or not isinstance(title, str) or not title.strip():
        return jsonify({"error": "Title is required"}), 400

    title = title.strip()
    if len(title) > MAX_TITLE_LENGTH:
        return jsonify({"error": f"Title exceeds maximum length of {MAX_TITLE_LENGTH} characters"}), 400

    priority = data.get("priority", "medium")
    if isinstance(priority, str):
        priority = priority.lower()
    if priority not in VALID_PRIORITIES:
        return jsonify({"error": f"Invalid priority. Allowed: {', '.join(VALID_PRIORITIES)}"}), 400

    description = data.get("description")
    if description is not None:
        if not isinstance(description, str):
            return jsonify({"error": "Description must be a string"}), 400
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return jsonify({"error": f"Description exceeds maximum length of {MAX_DESCRIPTION_LENGTH} characters"}), 400

    deadline = data.get("deadline")
    if deadline is not None:
        if not isinstance(deadline, str) or not _validate_deadline(deadline):
            return jsonify({"error": "Deadline must be a valid date in YYYY-MM-DD format"}), 400

    # AUTHZ-VULN-04 (issue #557): persist account_id at creation so the
    # row isn't stuck in NULL-quarantine and is reachable by its owner.
    account_id = _resolve_account_id_for_user()
    task_repo = _rh._get_container().get_task_repository()
    task = task_repo.create(
        title=title,
        description=description,
        priority=priority,
        deadline=deadline,
        account_id=account_id,
    )
    return jsonify(task), 201
