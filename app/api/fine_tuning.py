# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour le système de Fine-tuning avec feedback utilisateur.

Endpoints pour :
- Enregistrer des corrections et feedbacks
- Extraire des patterns
- Gérer les modèles d'amélioration
- Lancer des sessions de fine-tuning
- Obtenir des statistiques
"""

import logging

from flask import Blueprint, request, jsonify

from app.api.routes_helpers import (
    _get_container,
    _resolve_account_id_for_user,
    _validate_email_id,
)
from app.application.fine_tuning import (
    ActivateModelUseCase,
    ApplyImprovementsUseCase,
    CreateImprovementModelUseCase,
    DisableModelUseCase,
    ExtractPatternsUseCase,
    GetFineTuningStatsUseCase,
    GetPromptEnhancementsUseCase,
    ListModelsUseCase,
    ListPatternsUseCase,
    RecordCorrectionUseCase,
    RecordFeedbackUseCase,
    RunFineTuningSessionUseCase,
)
from app.domain.entities.fine_tuning import (
    CorrectionType,
    ImprovementStatus,
)
from app.infrastructure.fine_tuning_store import (
    DefaultFineTuningAnalyzer,
    JsonCorrectionPatternStore,
    JsonFineTuningSessionStore,
    JsonImprovementModelStore,
    JsonUserCorrectionStore,
    JsonUserFeedbackStore,
)

logger = logging.getLogger(__name__)


# =============================================================================
# BLUEPRINT
# =============================================================================

fine_tuning_bp = Blueprint("fine_tuning", __name__, url_prefix="/api/fine-tuning")


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================


def _get_stores():
    """Retourne les stores initialisés."""
    return {
        "correction_store": JsonUserCorrectionStore(),
        "feedback_store": JsonUserFeedbackStore(),
        "pattern_store": JsonCorrectionPatternStore(),
        "model_store": JsonImprovementModelStore(),
        "session_store": JsonFineTuningSessionStore(),
        "analyzer": DefaultFineTuningAnalyzer(),
    }


# =============================================================================
# CORRECTIONS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/corrections", methods=["POST"])
def record_correction():
    """
    Enregistre une correction utilisateur.

    Body JSON:
    {
        "draft_id": "string",
        "original_text": "string",
        "corrected_text": "string",
        "context": {"key": "value"},  // optionnel
        "user_comment": "string"  // optionnel
    }

    Returns:
        201: Correction enregistrée avec succès
        400: Données invalides
    """
    data = request.get_json(silent=True)  # silent: missing body -> custom 400 below (STAB-02)

    if not data:
        return jsonify({"error": "No data provided"}), 400

    required = ["draft_id", "original_text", "corrected_text"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    # H-6 (audit security.md, issue #532): cross-tenant draft poisoning
    # check. The route used to accept any draft_id from the body — User A
    # could enumerate User B's draft_ids and ship adversarial corrections
    # that would land in the global pattern_store and shape B's future
    # drafts. We now require the JWT caller to actually own the draft.
    # Pattern aligned with routes_drafts.py:245 (`get_by_id_for_account`).
    draft_id = data["draft_id"]
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404
    draft = _get_container().get_draft_history().get_by_id_for_account(
        draft_id, account_id
    )
    if draft is None:
        return jsonify({"error": "Draft not found"}), 404

    stores = _get_stores()
    use_case = RecordCorrectionUseCase(
        correction_store=stores["correction_store"],
        pattern_store=stores["pattern_store"],
        analyzer=stores["analyzer"],
    )

    result = use_case.execute(
        draft_id=draft_id,
        original_text=data["original_text"],
        corrected_text=data["corrected_text"],
        context=data.get("context"),
        user_comment=data.get("user_comment"),
        account_id=account_id,
    )

    return jsonify({
        "correction_id": result.correction_id,
        "correction_types": [ct.value for ct in result.correction_types],
        "has_significant_changes": result.has_significant_changes,
        "patterns_found": result.patterns_found,
    }), 201


@fine_tuning_bp.route("/corrections", methods=["GET"])
def list_corrections():
    """
    Liste les corrections récentes.

    Query params:
    - limit: nombre max (default: 50)
    - type: filtrer par type de correction

    Returns:
        200: Liste des corrections
    """
    stores = _get_stores()
    _aid = _resolve_account_id_for_user()
    _scoped = _aid if isinstance(_aid, int) and _aid > 0 else None
    limit = request.args.get("limit", 50, type=int)
    correction_type = request.args.get("type")

    if correction_type:
        try:
            ctype = CorrectionType(correction_type)
            corrections = stores["correction_store"].get_by_correction_type(
                ctype, limit=limit
            )
        except ValueError:
            return jsonify({"error": f"Invalid correction type: {correction_type}"}), 400
    else:
        corrections = stores["correction_store"].get_recent(limit=limit)

    # Audit 2026-05-30: scope to caller — these reads were cross-tenant.
    if _scoped is not None:
        corrections = [c for c in corrections if c.account_id == _scoped]

    return jsonify({
        "corrections": [
            {
                "id": c.id,
                "draft_id": c.draft_id,
                "correction_types": [ct.value for ct in c.correction_types],
                "has_significant_changes": c.has_significant_changes(),
                "created_at": c.created_at.isoformat(),
            }
            for c in corrections
        ],
        "total": len(corrections),
    })


# =============================================================================
# FEEDBACKS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/feedbacks", methods=["POST"])
def record_feedback():
    """
    Enregistre un feedback utilisateur.

    Body JSON:
    {
        "draft_id": "string",
        "rating": 1-5,
        "comment": "string",  // optionnel
        "tags": ["tag1", "tag2"]  // optionnel
    }

    Returns:
        201: Feedback enregistré
        400: Données invalides
    """
    data = request.get_json(silent=True)  # silent: missing body -> custom 400 below (STAB-02)

    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "draft_id" not in data or "rating" not in data:
        return jsonify({"error": "Missing draft_id or rating"}), 400

    rating = data["rating"]
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        return jsonify({"error": "Rating must be between 1 and 5"}), 400

    # H-6 (audit security.md, issue #532): same cross-tenant guard as
    # /corrections — a low-rating feedback on someone else's draft_id
    # poisons the feedback_store (and triggers `requires_analysis` paths
    # downstream). Owner check via `get_by_id_for_account`.
    draft_id = data["draft_id"]
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Draft not found"}), 404
    draft = _get_container().get_draft_history().get_by_id_for_account(
        draft_id, account_id
    )
    if draft is None:
        return jsonify({"error": "Draft not found"}), 404

    stores = _get_stores()
    use_case = RecordFeedbackUseCase(feedback_store=stores["feedback_store"])

    result = use_case.execute(
        draft_id=draft_id,
        rating=rating,
        comment=data.get("comment"),
        tags=data.get("tags"),
        account_id=account_id,
    )

    return jsonify({
        "feedback_id": result.feedback_id,
        "sentiment": result.sentiment.value,
        "requires_analysis": result.requires_analysis,
    }), 201


@fine_tuning_bp.route("/feedbacks", methods=["GET"])
def list_feedbacks():
    """
    Liste les feedbacks récents.

    Query params:
    - limit: nombre max (default: 50)

    Returns:
        200: Liste des feedbacks
    """
    stores = _get_stores()
    _aid = _resolve_account_id_for_user()
    _scoped = _aid if isinstance(_aid, int) and _aid > 0 else None
    limit = request.args.get("limit", 50, type=int)

    feedbacks = stores["feedback_store"].get_recent(limit=limit)
    if _scoped is not None:
        feedbacks = [f for f in feedbacks if f.account_id == _scoped]

    return jsonify({
        "feedbacks": [
            {
                "id": f.id,
                "draft_id": f.draft_id,
                "rating": f.rating,
                "sentiment": f.sentiment.value,
                "comment": f.comment,
                "created_at": f.created_at.isoformat(),
            }
            for f in feedbacks
        ],
        "total": len(feedbacks),
        "average_rating": stores["feedback_store"].get_average_rating(),
    })


# =============================================================================
# PATTERNS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/patterns", methods=["GET"])
def list_patterns():
    """
    Liste les patterns de correction.

    Query params:
    - limit: nombre max (default: 100)
    - type: filtrer par type
    - min_confidence: confiance minimale

    Returns:
        200: Liste des patterns
    """
    stores = _get_stores()
    limit = request.args.get("limit", 100, type=int)
    pattern_type = request.args.get("type")
    min_confidence = request.args.get("min_confidence", type=float)

    use_case = ListPatternsUseCase(pattern_store=stores["pattern_store"])

    ctype = None
    if pattern_type:
        try:
            ctype = CorrectionType(pattern_type)
        except ValueError:
            return jsonify({"error": f"Invalid pattern type: {pattern_type}"}), 400

    patterns = use_case.execute(
        pattern_type=ctype,
        min_confidence=min_confidence,
        limit=limit,
    )
    _aid = _resolve_account_id_for_user()
    _scoped = _aid if isinstance(_aid, int) and _aid > 0 else None
    if _scoped is not None:
        patterns = [p for p in patterns if p.account_id == _scoped]

    return jsonify({
        "patterns": [
            {
                "id": p.id,
                "pattern_type": p.pattern_type.value,
                "original_pattern": p.original_pattern[:100],
                "replacement": p.replacement[:100] if p.replacement else None,
                "occurrences": p.occurrences,
                "confidence": p.confidence,
                "is_reliable": p.is_reliable(),
                "created_at": p.created_at.isoformat(),
            }
            for p in patterns
        ],
        "total": len(patterns),
    })


@fine_tuning_bp.route("/patterns/extract", methods=["POST"])
def extract_patterns():
    """
    Extrait des patterns des corrections récentes.

    Body JSON (optionnel):
    {
        "min_corrections": 5  // nombre minimum de corrections
    }

    Returns:
        200: Patterns extraits
    """
    data = request.get_json() or {}
    min_corrections = data.get("min_corrections", 5)
    _aid = _resolve_account_id_for_user()
    _scoped = _aid if isinstance(_aid, int) and _aid > 0 else None

    stores = _get_stores()
    use_case = ExtractPatternsUseCase(
        correction_store=stores["correction_store"],
        pattern_store=stores["pattern_store"],
        analyzer=stores["analyzer"],
    )

    result = use_case.execute(min_corrections=min_corrections, account_id=_scoped)

    return jsonify({
        "patterns_extracted": result.patterns_extracted,
        "patterns_reinforced": result.patterns_reinforced,
        "new_patterns": [
            {
                "id": p.id,
                "pattern_type": p.pattern_type.value,
                "confidence": p.confidence,
            }
            for p in result.new_patterns
        ],
    })


# =============================================================================
# MODELS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/models", methods=["GET"])
def list_models():
    """
    Liste les modèles d'amélioration DU TENANT.

    C-6 (audit security.md, issue #526) : avant le fix, l'endpoint
    énumérait les modèles de tous les tenants — un user pouvait scanner
    les `model_id` du voisin pour ensuite les /activate ou /disable. La
    réponse est désormais filtrée à `account_id == JWT caller`.

    Query params:
    - status: filtrer par statut (pending, active, disabled, deprecated)

    Returns:
        200: Liste des modèles owned par le caller
    """
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "No account resolved for caller"}), 401

    stores = _get_stores()
    status_param = request.args.get("status")

    use_case = ListModelsUseCase(model_store=stores["model_store"])

    status = None
    if status_param:
        try:
            status = ImprovementStatus(status_param)
        except ValueError:
            return jsonify({"error": f"Invalid status: {status_param}"}), 400

    models = use_case.execute(status=status, account_id=account_id)

    return jsonify({
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "status": m.status.value,
                "patterns_count": len(m.patterns),
                "adjustments_count": len(m.prompt_adjustments),
                "impact_score": m.impact_score,
                "drafts_improved": m.drafts_improved,
                "created_at": m.created_at.isoformat(),
            }
            for m in models
        ],
        "total": len(models),
    })


@fine_tuning_bp.route("/models", methods=["POST"])
def create_model():
    """
    Crée un nouveau modèle d'amélioration.

    Body JSON:
    {
        "name": "string",
        "description": "string",
        "min_confidence": 0.6,  // optionnel
        "version": "1.0.0"  // optionnel
    }

    Returns:
        201: Modèle créé
        400: Données invalides
    """
    data = request.get_json(silent=True)  # silent: missing body -> custom 400 below (STAB-02)

    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "name" not in data or "description" not in data:
        return jsonify({"error": "Missing name or description"}), 400

    # C-6 (audit, issue #526): stamp the new model with the caller's tenant.
    # Without this, modèles créés sont sans owner et invisibles aux lookups
    # scopées (admin-only de fait).
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "No account resolved for caller"}), 401

    stores = _get_stores()
    use_case = CreateImprovementModelUseCase(
        model_store=stores["model_store"],
        pattern_store=stores["pattern_store"],
        analyzer=stores["analyzer"],
    )

    result = use_case.execute(
        name=data["name"],
        description=data["description"],
        min_confidence=data.get("min_confidence", 0.6),
        version=data.get("version"),
        account_id=account_id,
    )

    return jsonify({
        "model_id": result.model_id,
        "model_name": result.model_name,
        "patterns_included": result.patterns_included,
        "prompt_adjustments": result.prompt_adjustments,
    }), 201


@fine_tuning_bp.route("/models/<model_id>", methods=["GET"])
def get_model(model_id: str):
    """
    Récupère les détails d'un modèle owned par le caller.

    C-6 (audit, issue #526) : ownership check via `account_id`. Réponse
    uniforme 404 entre « inexistant » et « pas le tien » pour éviter
    l'oracle d'existence.

    Returns:
        200: Détails du modèle
        404: Modèle non trouvé OU non possédé par le caller
    """
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Model not found"}), 404

    stores = _get_stores()
    model = stores["model_store"].get_by_id(model_id)

    if not model or model.account_id != account_id:
        return jsonify({"error": "Model not found"}), 404

    return jsonify({
        "id": model.id,
        "name": model.name,
        "version": model.version,
        "description": model.description,
        "status": model.status.value,
        "patterns": model.patterns,
        "prompt_adjustments": model.prompt_adjustments,
        "impact_score": model.impact_score,
        "drafts_improved": model.drafts_improved,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
    })


@fine_tuning_bp.route("/models/<model_id>/activate", methods=["POST"])
def activate_model(model_id: str):
    """
    Active un modèle d'amélioration owned par le caller.

    C-6 (audit, issue #526) : avant le fix, l'endpoint flippait le statut
    de N'IMPORTE quel `model_id` — un user pouvait activer le modèle d'un
    autre tenant et déprécier ses propres actifs au passage. Désormais
    `account_id` est validé inside le use case (404 uniforme si étranger).

    Returns:
        200: Modèle activé
        404: Modèle non trouvé OU non possédé par le caller
    """
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Model not found"}), 404

    stores = _get_stores()
    use_case = ActivateModelUseCase(model_store=stores["model_store"])

    try:
        use_case.execute(model_id, account_id=account_id)
        return jsonify({"message": "Model activated", "model_id": model_id})
    except ValueError:
        # Don't leak the underlying message — uniform 404 between "not
        # found" and "owned by someone else".
        return jsonify({"error": "Model not found"}), 404


@fine_tuning_bp.route("/models/<model_id>/disable", methods=["POST"])
def disable_model(model_id: str):
    """
    Désactive un modèle d'amélioration owned par le caller.

    C-6 (audit, issue #526) : ownership-checked via `account_id`. Refuse
    qu'un user désactive le modèle actif d'un autre tenant pour dégrader
    son drafting.

    Returns:
        200: Modèle désactivé
        404: Modèle non trouvé OU non possédé par le caller
    """
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "Model not found"}), 404

    stores = _get_stores()
    use_case = DisableModelUseCase(model_store=stores["model_store"])

    try:
        use_case.execute(model_id, account_id=account_id)
        return jsonify({"message": "Model disabled", "model_id": model_id})
    except ValueError:
        return jsonify({"error": "Model not found"}), 404


# =============================================================================
# IMPROVEMENTS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/improve", methods=["POST"])
def apply_improvements():
    """
    Applique les améliorations à un texte.

    Body JSON:
    {
        "text": "string",
        "model_id": "string"  // optionnel, utilise le modèle actif par défaut
    }

    Returns:
        200: Texte amélioré
        400: Données invalides
    """
    data = request.get_json(silent=True)  # silent: missing body -> custom 400 below (STAB-02)

    if not data or "text" not in data:
        return jsonify({"error": "Missing text"}), 400

    # C-6 (audit, issue #526): resolve caller's tenant — un `model_id`
    # explicite étranger est traité comme introuvable, et la sélection
    # « modèle actif » est filtrée au tenant.
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "No account resolved for caller"}), 401

    stores = _get_stores()
    use_case = ApplyImprovementsUseCase(
        model_store=stores["model_store"],
        pattern_store=stores["pattern_store"],
        analyzer=stores["analyzer"],
    )

    result = use_case.execute(
        text=data["text"],
        model_id=data.get("model_id"),
        account_id=account_id,
    )

    return jsonify({
        "improved_text": result.improved_text,
        "improvements_applied": result.improvements_applied,
        "patterns_used": result.patterns_used,
        "was_improved": result.improved_text != data["text"],
    })


@fine_tuning_bp.route("/prompt-enhancements", methods=["GET"])
def get_prompt_enhancements():
    """
    Récupère les améliorations de prompt actives.

    Returns:
        200: Liste des ajustements de prompt
    """
    # C-6 (audit, issue #526) : scope les modèles actifs au tenant.
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"adjustments": [], "count": 0})

    stores = _get_stores()
    use_case = GetPromptEnhancementsUseCase(
        model_store=stores["model_store"],
        pattern_store=stores["pattern_store"],
    )

    adjustments = use_case.execute(account_id=account_id)

    return jsonify({
        "adjustments": adjustments,
        "count": len(adjustments),
    })


# =============================================================================
# SESSIONS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/sessions", methods=["POST"])
def run_session():
    """
    Lance une session de fine-tuning.

    Body JSON (optionnel):
    {
        "auto_activate": false,  // activer automatiquement le modèle créé
        "min_corrections": 10  // nombre minimum de corrections
    }

    Returns:
        200: Session terminée avec succès
        500: Erreur durant la session
    """
    data = request.get_json() or {}

    # C-6 (audit, issue #526): le modèle créé par la session est stamped
    # avec ce tenant — sans ça, un user pouvait produire un modèle
    # « actif » global qui shape les drafts d'un autre tenant.
    account_id = _resolve_account_id_for_user()
    if account_id <= 0:
        return jsonify({"error": "No account resolved for caller"}), 401

    stores = _get_stores()
    use_case = RunFineTuningSessionUseCase(
        session_store=stores["session_store"],
        correction_store=stores["correction_store"],
        feedback_store=stores["feedback_store"],
        pattern_store=stores["pattern_store"],
        model_store=stores["model_store"],
        analyzer=stores["analyzer"],
    )

    try:
        result = use_case.execute(
            auto_activate=data.get("auto_activate", False),
            min_corrections=data.get("min_corrections", 10),
            account_id=account_id,
        )

        return jsonify({
            "session_id": result.session_id,
            "corrections_analyzed": result.corrections_analyzed,
            "feedbacks_analyzed": result.feedbacks_analyzed,
            "patterns_extracted": result.patterns_extracted,
            "model_created": result.model_created,
            "duration_seconds": result.duration_seconds,
        })
    except Exception as e:
        logger.error(f"Error starting fine-tuning session: {e}")
        return jsonify({"error": "An internal error occurred while starting fine-tuning session"}), 500


@fine_tuning_bp.route("/sessions", methods=["GET"])
def list_sessions():
    """
    Liste les sessions de fine-tuning récentes.

    Query params:
    - limit: nombre max (default: 10)

    Returns:
        200: Liste des sessions
    """
    stores = _get_stores()
    _aid = _resolve_account_id_for_user()
    _scoped = _aid if isinstance(_aid, int) and _aid > 0 else None
    limit = request.args.get("limit", 10, type=int)

    sessions = stores["session_store"].get_recent(limit=limit)
    if _scoped is not None:
        sessions = [s for s in sessions if getattr(s, "account_id", None) == _scoped]

    return jsonify({
        "sessions": [
            {
                "id": s.id,
                "status": s.status,
                "corrections_count": s.corrections_count,
                "feedbacks_count": s.feedbacks_count,
                "patterns_extracted": s.patterns_extracted,
                "model_id": s.model_id,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            }
            for s in sessions
        ],
        "total": len(sessions),
    })


# =============================================================================
# STATS ENDPOINTS
# =============================================================================


@fine_tuning_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Récupère les statistiques de fine-tuning.

    Returns:
        200: Statistiques complètes
    """
    stores = _get_stores()
    use_case = GetFineTuningStatsUseCase(
        correction_store=stores["correction_store"],
        feedback_store=stores["feedback_store"],
        pattern_store=stores["pattern_store"],
        model_store=stores["model_store"],
    )

    stats = use_case.execute()

    return jsonify({
        "total_corrections": stats.total_corrections,
        "total_feedbacks": stats.total_feedbacks,
        "total_patterns": stats.total_patterns,
        "active_models": stats.active_models,
        "average_impact": stats.average_impact,
        "improvement_rate": stats.improvement_rate,
        "top_correction_types": stats.top_correction_types,
        "feedback_sentiment_distribution": stats.feedback_sentiment_distribution,
        "patterns_by_confidence": stats.patterns_by_confidence,
    })
