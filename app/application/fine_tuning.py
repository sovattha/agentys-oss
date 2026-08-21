# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Cases pour le système de Fine-tuning avec feedback utilisateur.

Cette couche contient la logique métier pour :
- Enregistrer les corrections utilisateur
- Collecter et analyser les feedbacks
- Extraire des patterns des corrections
- Créer et gérer les modèles d'amélioration
- Appliquer les améliorations aux drafts

Règle : Cette couche dépend uniquement du domaine (entities + ports).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from app.domain.entities.fine_tuning import (
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    FineTuningStats,
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
)
from app.domain.ports.fine_tuning_port import (
    UserCorrectionPort,
    UserFeedbackPort,
    CorrectionPatternPort,
    ImprovementModelPort,
    FineTuningSessionPort,
    FineTuningAnalyzerPort,
)


# =============================================================================
# RECORD CORRECTION USE CASE
# =============================================================================


@dataclass
class RecordCorrectionResult:
    """Résultat de l'enregistrement d'une correction."""
    correction_id: str
    correction_types: List[CorrectionType]
    has_significant_changes: bool
    patterns_found: int


class RecordCorrectionUseCase:
    """
    Use case pour enregistrer une correction utilisateur.

    Analyse la correction, détecte les types de changements,
    et cherche des patterns existants à renforcer.
    """

    def __init__(
        self,
        correction_store: UserCorrectionPort,
        pattern_store: CorrectionPatternPort,
        analyzer: FineTuningAnalyzerPort,
    ):
        self.correction_store = correction_store
        self.pattern_store = pattern_store
        self.analyzer = analyzer

    def execute(
        self,
        draft_id: str,
        original_text: str,
        corrected_text: str,
        context: Optional[Dict[str, Any]] = None,
        user_comment: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> RecordCorrectionResult:
        """
        Enregistre une correction et analyse les changements.

        Args:
            draft_id: ID du draft corrigé.
            original_text: Texte original.
            corrected_text: Texte corrigé par l'utilisateur.
            context: Contexte optionnel (expéditeur, catégorie, etc.).
            user_comment: Commentaire optionnel.

        Returns:
            Résultat avec l'ID et les types de corrections détectés.
        """
        # Analyser les types de corrections
        correction_types = self.analyzer.analyze_correction(
            original_text, corrected_text
        )

        # Créer et sauvegarder la correction
        correction = UserCorrection.create(
            draft_id=draft_id,
            original_text=original_text,
            corrected_text=corrected_text,
            context=context,
            user_comment=user_comment,
            account_id=account_id,
        )
        correction.correction_types = correction_types

        correction_id = self.correction_store.save(correction)

        # Chercher des patterns existants à renforcer
        patterns_found = 0
        if correction.has_significant_changes():
            patterns_found = self._reinforce_existing_patterns(correction)

        return RecordCorrectionResult(
            correction_id=correction_id,
            correction_types=correction_types,
            has_significant_changes=correction.has_significant_changes(),
            patterns_found=patterns_found,
        )

    def _reinforce_existing_patterns(self, correction: UserCorrection) -> int:
        """Renforce les patterns existants si des similarités sont trouvées."""
        count = 0
        # Pour chaque type de correction détecté
        for correction_type in correction.correction_types:
            # Chercher un pattern similaire
            similar = self.pattern_store.find_similar(
                correction.original_text[:100]  # Utiliser le début du texte
            )
            if similar and similar.pattern_type == correction_type:
                similar.increment_occurrence()
                similar.examples.append({
                    "original": correction.original_text[:200],
                    "corrected": correction.corrected_text[:200],
                })
                self.pattern_store.update(similar)
                count += 1

        return count


# =============================================================================
# RECORD FEEDBACK USE CASE
# =============================================================================


@dataclass
class RecordFeedbackResult:
    """Résultat de l'enregistrement d'un feedback."""
    feedback_id: str
    sentiment: FeedbackSentiment
    requires_analysis: bool


class RecordFeedbackUseCase:
    """
    Use case pour enregistrer un feedback utilisateur.

    Sauvegarde le feedback et détermine s'il nécessite une analyse approfondie.
    """

    def __init__(self, feedback_store: UserFeedbackPort):
        self.feedback_store = feedback_store

    def execute(
        self,
        draft_id: str,
        rating: int,
        comment: Optional[str] = None,
        tags: Optional[List[str]] = None,
        account_id: Optional[int] = None,
    ) -> RecordFeedbackResult:
        """
        Enregistre un feedback utilisateur.

        Args:
            draft_id: ID du draft évalué.
            rating: Note de 1 à 5.
            comment: Commentaire optionnel.
            tags: Tags optionnels.

        Returns:
            Résultat avec l'ID et le sentiment.
        """
        feedback = UserFeedback.create(
            draft_id=draft_id,
            rating=rating,
            comment=comment,
            tags=tags,
            account_id=account_id,
        )

        feedback_id = self.feedback_store.save(feedback)

        # Analyse requise si feedback négatif avec commentaire
        requires_analysis = (
            feedback.sentiment == FeedbackSentiment.NEGATIVE
            and feedback.comment is not None
            and len(feedback.comment) > 10
        )

        return RecordFeedbackResult(
            feedback_id=feedback_id,
            sentiment=feedback.sentiment,
            requires_analysis=requires_analysis,
        )


# =============================================================================
# EXTRACT PATTERNS USE CASE
# =============================================================================


@dataclass
class ExtractPatternsResult:
    """Résultat de l'extraction de patterns."""
    patterns_extracted: int
    patterns_reinforced: int
    new_patterns: List[CorrectionPattern]


class ExtractPatternsUseCase:
    """
    Use case pour extraire des patterns des corrections récentes.

    Analyse les corrections accumulées et identifie les patterns récurrents.
    """

    def __init__(
        self,
        correction_store: UserCorrectionPort,
        pattern_store: CorrectionPatternPort,
        analyzer: FineTuningAnalyzerPort,
    ):
        self.correction_store = correction_store
        self.pattern_store = pattern_store
        self.analyzer = analyzer

    def execute(
        self,
        since: Optional[datetime] = None,
        min_corrections: int = 5,
        account_id: Optional[int] = None,
    ) -> ExtractPatternsResult:
        """
        Extrait des patterns des corrections récentes.

        Args:
            since: Date à partir de laquelle analyser (défaut: 7 jours).
            min_corrections: Nombre minimum de corrections pour extraire.

        Returns:
            Résultat avec les patterns extraits.
        """
        if since is None:
            since = datetime.now() - timedelta(days=7)

        # Récupérer les corrections récentes
        corrections = self.correction_store.get_recent(limit=500, since=since)
        if account_id is not None:
            # Per-tenant extraction (2026-05-30 isolation): build patterns only
            # from this account's corrections so they can be stamped + filtered.
            corrections = [c for c in corrections if c.account_id == account_id]

        if len(corrections) < min_corrections:
            return ExtractPatternsResult(
                patterns_extracted=0,
                patterns_reinforced=0,
                new_patterns=[],
            )

        # Extraire les patterns
        extracted_patterns = self.analyzer.extract_patterns(corrections)

        new_patterns = []
        reinforced = 0

        for pattern in extracted_patterns:
            # Chercher un pattern similaire existant
            existing = self.pattern_store.find_similar(pattern.original_pattern)

            if existing:
                # Renforcer le pattern existant
                existing.increment_occurrence()
                existing.contexts.extend(pattern.contexts)
                existing.examples.extend(pattern.examples)
                self.pattern_store.update(existing)
                reinforced += 1
            else:
                # Créer un nouveau pattern (stamped with the tenant for isolation)
                pattern.account_id = account_id
                self.pattern_store.save(pattern)
                new_patterns.append(pattern)

        return ExtractPatternsResult(
            patterns_extracted=len(extracted_patterns),
            patterns_reinforced=reinforced,
            new_patterns=new_patterns,
        )


# =============================================================================
# CREATE IMPROVEMENT MODEL USE CASE
# =============================================================================


@dataclass
class CreateModelResult:
    """Résultat de la création d'un modèle."""
    model_id: str
    model_name: str
    patterns_included: int
    prompt_adjustments: int


class CreateImprovementModelUseCase:
    """
    Use case pour créer un modèle d'amélioration.

    Agrège les patterns fiables et génère des ajustements de prompt.
    """

    def __init__(
        self,
        model_store: ImprovementModelPort,
        pattern_store: CorrectionPatternPort,
        analyzer: FineTuningAnalyzerPort,
    ):
        self.model_store = model_store
        self.pattern_store = pattern_store
        self.analyzer = analyzer

    def execute(
        self,
        name: str,
        description: str,
        min_confidence: float = 0.6,
        version: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> CreateModelResult:
        """
        Crée un nouveau modèle d'amélioration.

        Args:
            name: Nom du modèle.
            description: Description.
            min_confidence: Confiance minimale des patterns à inclure.
            version: Version du modèle (auto-générée si non fournie).
            account_id: Tenant propriétaire du modèle (C-6, audit issue
                #526). Quand fourni, le modèle est stamped et invisible
                aux autres tenants. None est toléré pour les chemins
                admin/scripts uniquement — les routes API doivent toujours
                résoudre et passer l'`account_id` du JWT caller.

        Returns:
            Résultat avec les détails du modèle créé.
        """
        # Générer la version si non fournie
        if version is None:
            latest = self.model_store.get_latest()
            if latest:
                # Incrémenter la version mineure
                parts = latest.version.split(".")
                parts[-1] = str(int(parts[-1]) + 1)
                version = ".".join(parts)
            else:
                version = "1.0.0"

        # Récupérer les patterns fiables
        reliable_patterns = self.pattern_store.get_reliable_patterns(
            min_confidence=min_confidence
        )

        # Générer les ajustements de prompt
        prompt_adjustments = self.analyzer.generate_prompt_adjustments(
            reliable_patterns
        )

        # Créer le modèle
        model = ImprovementModel.create(
            name=name,
            description=description,
            version=version,
            account_id=account_id,
        )

        # Ajouter les patterns et ajustements
        for pattern in reliable_patterns:
            model.add_pattern(pattern.id)

        for adjustment in prompt_adjustments:
            model.add_prompt_adjustment(adjustment)

        # Sauvegarder
        model_id = self.model_store.save(model)

        return CreateModelResult(
            model_id=model_id,
            model_name=name,
            patterns_included=len(reliable_patterns),
            prompt_adjustments=len(prompt_adjustments),
        )


# =============================================================================
# ACTIVATE MODEL USE CASE
# =============================================================================


class ActivateModelUseCase:
    """
    Use case pour activer un modèle d'amélioration.

    Désactive les anciens modèles et active le nouveau.
    """

    def __init__(self, model_store: ImprovementModelPort):
        self.model_store = model_store

    def execute(self, model_id: str, account_id: Optional[int] = None) -> bool:
        """
        Active un modèle.

        Args:
            model_id: ID du modèle à activer.
            account_id: Tenant du caller (C-6, audit issue #526). Quand
                fourni : (1) le modèle est introuvable si son `account_id`
                ne match pas (raise ValueError, traduit en 404 par la route
                pour ne pas devenir un oracle d'existence) ; (2) la
                déprécation des « autres modèles actifs » est SCOPÉE au
                tenant — sans ça, activer son propre modèle dépréciait
                aussi celui d'un autre user (cross-tenant takeover).

        Returns:
            True si activé avec succès.

        Raises:
            ValueError: Si le modèle n'existe pas OU n'appartient pas au
                tenant fourni.
        """
        model = self.model_store.get_by_id(model_id)
        if not model:
            raise ValueError(f"Model {model_id} not found")

        # C-6 ownership check : un caller scopé ne peut pas toucher un modèle
        # qui n'est pas le sien (ni les modèles legacy `account_id=None`).
        if account_id is not None and model.account_id != account_id:
            raise ValueError(f"Model {model_id} not found")

        # Désactiver les autres modèles actifs DU MÊME TENANT.
        active_models = self.model_store.get_active_models()
        for active in active_models:
            if active.id == model_id:
                continue
            if account_id is not None and active.account_id != account_id:
                # Pas le sien, pas touche.
                continue
            active.deprecate()
            self.model_store.update(active)

        # Activer le nouveau modèle
        model.activate()
        return self.model_store.update(model)


# =============================================================================
# APPLY IMPROVEMENTS USE CASE
# =============================================================================


@dataclass
class ApplyImprovementsResult:
    """Résultat de l'application des améliorations."""
    improved_text: str
    improvements_applied: int
    patterns_used: List[str]


class ApplyImprovementsUseCase:
    """
    Use case pour appliquer les améliorations à un draft.

    Utilise le modèle actif et les patterns pour améliorer le texte.
    """

    def __init__(
        self,
        model_store: ImprovementModelPort,
        pattern_store: CorrectionPatternPort,
        analyzer: FineTuningAnalyzerPort,
    ):
        self.model_store = model_store
        self.pattern_store = pattern_store
        self.analyzer = analyzer

    def execute(
        self,
        text: str,
        model_id: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> ApplyImprovementsResult:
        """
        Applique les améliorations à un texte.

        Args:
            text: Texte à améliorer.
            model_id: ID du modèle à utiliser (défaut: modèle actif).
            account_id: Tenant du caller (C-6, audit issue #526). Quand
                fourni : (1) `model_id` explicite est rejeté s'il
                n'appartient pas au caller (no-op silencieux), (2) la
                résolution « modèle actif » est filtrée à l'`account_id`
                — empêche un modèle « actif » d'un autre tenant de shape
                les drafts du caller.

        Returns:
            Résultat avec le texte amélioré.
        """
        # Récupérer le modèle
        if model_id:
            model = self.model_store.get_by_id(model_id)
            # C-6 ownership : un model_id étranger est traité comme
            # introuvable (pas d'oracle, pas de takeover).
            if model is not None and account_id is not None:
                if model.account_id != account_id:
                    model = None
        else:
            active_models = self.model_store.get_active_models()
            if account_id is not None:
                active_models = [
                    m for m in active_models if m.account_id == account_id
                ]
            model = active_models[0] if active_models else None

        if not model:
            return ApplyImprovementsResult(
                improved_text=text,
                improvements_applied=0,
                patterns_used=[],
            )

        # Récupérer les patterns du modèle
        patterns = []
        for pattern_id in model.patterns:
            pattern = self.pattern_store.get_by_id(pattern_id)
            if pattern and pattern.is_reliable():
                patterns.append(pattern)

        # Appliquer les améliorations
        improved_text = self.analyzer.apply_improvements(text, model, patterns)

        # Enregistrer l'utilisation
        model.record_improvement()
        self.model_store.update(model)

        # Compter les améliorations
        improvements = 0
        if improved_text != text:
            improvements = sum(
                1 for p in patterns
                if p.original_pattern.lower() in text.lower()
            )

        return ApplyImprovementsResult(
            improved_text=improved_text,
            improvements_applied=improvements,
            patterns_used=[p.id for p in patterns if p.original_pattern.lower() in text.lower()],
        )


# =============================================================================
# GET PROMPT ENHANCEMENTS USE CASE
# =============================================================================


class GetPromptEnhancementsUseCase:
    """
    Use case pour obtenir les améliorations de prompt.

    Retourne les ajustements à ajouter au prompt du Drafter.
    """

    def __init__(
        self,
        model_store: ImprovementModelPort,
        pattern_store: CorrectionPatternPort,
    ):
        self.model_store = model_store
        self.pattern_store = pattern_store

    def execute(self, account_id: Optional[int] = None) -> List[str]:
        """
        Récupère les ajustements de prompt actifs.

        Args:
            account_id: Tenant du caller (C-6, audit issue #526). Quand
                fourni, filtre les modèles actifs au tenant — empêche
                un modèle « actif » créé par un autre user de shape les
                prompts du caller.

        Returns:
            Liste des ajustements à ajouter au prompt.
        """
        active_models = self.model_store.get_active_models()
        if account_id is not None:
            active_models = [
                m for m in active_models if m.account_id == account_id
            ]
        if not active_models:
            return []

        adjustments = []
        for model in active_models:
            adjustments.extend(model.prompt_adjustments)

        return adjustments


# =============================================================================
# RUN FINE TUNING SESSION USE CASE
# =============================================================================


@dataclass
class FineTuningSessionResult:
    """Résultat d'une session de fine-tuning."""
    session_id: str
    corrections_analyzed: int
    feedbacks_analyzed: int
    patterns_extracted: int
    model_created: Optional[str]
    duration_seconds: float


class RunFineTuningSessionUseCase:
    """
    Use case pour exécuter une session complète de fine-tuning.

    Orchestration complète : analyse corrections, extrait patterns, crée modèle.
    """

    def __init__(
        self,
        session_store: FineTuningSessionPort,
        correction_store: UserCorrectionPort,
        feedback_store: UserFeedbackPort,
        pattern_store: CorrectionPatternPort,
        model_store: ImprovementModelPort,
        analyzer: FineTuningAnalyzerPort,
    ):
        self.session_store = session_store
        self.correction_store = correction_store
        self.feedback_store = feedback_store
        self.pattern_store = pattern_store
        self.model_store = model_store
        self.analyzer = analyzer

    def execute(
        self,
        auto_activate: bool = False,
        min_corrections: int = 10,
        account_id: Optional[int] = None,
    ) -> FineTuningSessionResult:
        """
        Exécute une session complète de fine-tuning.

        Args:
            auto_activate: Activer automatiquement le modèle créé.
            min_corrections: Minimum de corrections pour créer un modèle.
            account_id: Tenant propriétaire (C-6, audit issue #526). Le
                modèle créé est stamped avec cet `account_id` ; sans ça
                un user peut produire un modèle « actif » global qui
                shape les drafts des autres tenants.

        Returns:
            Résultat de la session.
        """
        start_time = datetime.now()

        # Créer la session
        session = FineTuningSession.create(account_id=account_id)
        self.session_store.save(session)

        try:
            # 1. Récupérer et analyser les corrections
            corrections = self.correction_store.get_recent(limit=500)
            session.corrections_count = len(corrections)

            # 2. Récupérer et analyser les feedbacks
            feedbacks = self.feedback_store.get_recent(limit=500)
            session.feedbacks_count = len(feedbacks)

            model_id = None

            if len(corrections) >= min_corrections:
                # 3. Extraire les patterns
                patterns = self.analyzer.extract_patterns(corrections)
                session.patterns_extracted = len(patterns)

                # Sauvegarder les nouveaux patterns
                for pattern in patterns:
                    existing = self.pattern_store.find_similar(pattern.original_pattern)
                    if existing:
                        existing.increment_occurrence()
                        self.pattern_store.update(existing)
                    else:
                        self.pattern_store.save(pattern)

                # 4. Créer un nouveau modèle si assez de patterns fiables
                reliable_patterns = self.pattern_store.get_reliable_patterns()
                if len(reliable_patterns) >= 3:
                    adjustments = self.analyzer.generate_prompt_adjustments(
                        reliable_patterns
                    )

                    model = ImprovementModel.create(
                        name=f"Fine-tuning {datetime.now().strftime('%Y-%m-%d')}",
                        description=f"Modèle auto-généré avec {len(reliable_patterns)} patterns",
                        account_id=account_id,
                    )

                    for pattern in reliable_patterns:
                        model.add_pattern(pattern.id)
                    for adj in adjustments:
                        model.add_prompt_adjustment(adj)

                    model_id = self.model_store.save(model)

                    if auto_activate:
                        model.activate()
                        self.model_store.update(model)

            # Compléter la session
            session.complete(model_id)
            self.session_store.update(session)

            duration = (datetime.now() - start_time).total_seconds()

            return FineTuningSessionResult(
                session_id=session.id,
                corrections_analyzed=session.corrections_count,
                feedbacks_analyzed=session.feedbacks_count,
                patterns_extracted=session.patterns_extracted,
                model_created=model_id,
                duration_seconds=duration,
            )

        except Exception as e:
            session.fail(str(e))
            self.session_store.update(session)
            raise


# =============================================================================
# GET FINE TUNING STATS USE CASE
# =============================================================================


class GetFineTuningStatsUseCase:
    """
    Use case pour obtenir les statistiques de fine-tuning.
    """

    def __init__(
        self,
        correction_store: UserCorrectionPort,
        feedback_store: UserFeedbackPort,
        pattern_store: CorrectionPatternPort,
        model_store: ImprovementModelPort,
    ):
        self.correction_store = correction_store
        self.feedback_store = feedback_store
        self.pattern_store = pattern_store
        self.model_store = model_store

    def execute(self) -> FineTuningStats:
        """
        Calcule les statistiques complètes.

        Returns:
            Statistiques de fine-tuning.
        """
        # Compter les éléments
        total_corrections = self.correction_store.count()
        total_feedbacks = self.feedback_store.count()
        total_patterns = self.pattern_store.count()
        active_models = len(self.model_store.get_active_models())

        # Distribution des types de correction
        correction_types: Dict[str, int] = {}
        corrections = self.correction_store.get_recent(limit=1000)
        for correction in corrections:
            for ctype in correction.correction_types:
                correction_types[ctype.value] = correction_types.get(ctype.value, 0) + 1

        # Distribution des sentiments
        sentiment_dist = self.feedback_store.get_sentiment_distribution()

        # Distribution des patterns par confiance
        patterns = self.pattern_store.get_all()
        patterns_by_confidence = {
            "high": len([p for p in patterns if p.confidence >= 0.8]),
            "medium": len([p for p in patterns if 0.5 <= p.confidence < 0.8]),
            "low": len([p for p in patterns if p.confidence < 0.5]),
        }

        # Calculer l'impact moyen
        models = self.model_store.get_active_models()
        avg_impact = 0.0
        if models:
            avg_impact = sum(m.impact_score for m in models) / len(models)

        # Calculer le taux d'amélioration
        total_drafts = total_corrections + total_feedbacks
        improved_drafts = sum(m.drafts_improved for m in models)
        improvement_rate = improved_drafts / max(total_drafts, 1) * 100

        return FineTuningStats(
            total_corrections=total_corrections,
            total_feedbacks=total_feedbacks,
            total_patterns=total_patterns,
            active_models=active_models,
            average_impact=avg_impact,
            top_correction_types=correction_types,
            feedback_sentiment_distribution=sentiment_dist,
            patterns_by_confidence=patterns_by_confidence,
            improvement_rate=improvement_rate,
        )


# =============================================================================
# LIST PATTERNS USE CASE
# =============================================================================


class ListPatternsUseCase:
    """
    Use case pour lister les patterns de correction.
    """

    def __init__(self, pattern_store: CorrectionPatternPort):
        self.pattern_store = pattern_store

    def execute(
        self,
        pattern_type: Optional[CorrectionType] = None,
        min_confidence: Optional[float] = None,
        limit: int = 100,
    ) -> List[CorrectionPattern]:
        """
        Liste les patterns selon les critères.

        Args:
            pattern_type: Filtrer par type.
            min_confidence: Confiance minimale.
            limit: Nombre maximum.

        Returns:
            Liste des patterns.
        """
        if min_confidence is not None:
            return self.pattern_store.get_reliable_patterns(
                min_confidence=min_confidence,
                limit=limit,
            )
        elif pattern_type is not None:
            return self.pattern_store.get_by_type(
                pattern_type=pattern_type,
                limit=limit,
            )
        else:
            return self.pattern_store.get_all(limit=limit)


# =============================================================================
# LIST MODELS USE CASE
# =============================================================================


class ListModelsUseCase:
    """
    Use case pour lister les modèles d'amélioration.
    """

    def __init__(self, model_store: ImprovementModelPort):
        self.model_store = model_store

    def execute(
        self,
        status: Optional[ImprovementStatus] = None,
        limit: int = 100,
        account_id: Optional[int] = None,
    ) -> List[ImprovementModel]:
        """
        Liste les modèles selon les critères.

        Args:
            status: Filtrer par statut.
            limit: Nombre maximum.
            account_id: Tenant du caller (C-6, audit issue #526). Quand
                fourni, post-filtre la liste pour ne renvoyer QUE les
                modèles owned par ce tenant. Les modèles legacy
                (`account_id=None`) sont exclus — un caller multi-tenant
                ne doit jamais voir un modèle non-revendiqué. None
                désactive le filtrage (chemins admin / scripts).

        Returns:
            Liste des modèles.
        """
        if status is not None:
            models = self.model_store.get_by_status(status=status, limit=limit)
        else:
            models = []
            for s in ImprovementStatus:
                models.extend(self.model_store.get_by_status(status=s, limit=limit))
            models = models[:limit]

        if account_id is not None:
            models = [m for m in models if m.account_id == account_id]

        return models


# =============================================================================
# DISABLE MODEL USE CASE
# =============================================================================


class DisableModelUseCase:
    """
    Use case pour désactiver un modèle d'amélioration.
    """

    def __init__(self, model_store: ImprovementModelPort):
        self.model_store = model_store

    def execute(self, model_id: str, account_id: Optional[int] = None) -> bool:
        """
        Désactive un modèle.

        Args:
            model_id: ID du modèle à désactiver.
            account_id: Tenant du caller (C-6, audit issue #526). Quand
                fourni, le modèle est introuvable si son `account_id` ne
                match pas — empêche un attaquant de disable le modèle
                actif d'un autre tenant pour dégrader son drafting.

        Returns:
            True si désactivé avec succès.

        Raises:
            ValueError: Si le modèle n'existe pas OU n'appartient pas au
                tenant fourni.
        """
        model = self.model_store.get_by_id(model_id)
        if not model:
            raise ValueError(f"Model {model_id} not found")

        # C-6 ownership check.
        if account_id is not None and model.account_id != account_id:
            raise ValueError(f"Model {model_id} not found")

        model.disable()
        return self.model_store.update(model)
