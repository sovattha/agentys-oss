# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters de stockage pour le système de Fine-tuning.

Implémentations concrètes des ports pour persister les données
du fine-tuning dans des fichiers JSON.
"""

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Dict

from app.config import PROJECT_ROOT
from app.domain.entities.fine_tuning import (
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
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
# CONFIGURATION
# =============================================================================

FINE_TUNING_DIR = PROJECT_ROOT / "data" / "fine_tuning"
CORRECTIONS_FILE = FINE_TUNING_DIR / "corrections.json"
FEEDBACKS_FILE = FINE_TUNING_DIR / "feedbacks.json"
PATTERNS_FILE = FINE_TUNING_DIR / "patterns.json"
MODELS_FILE = FINE_TUNING_DIR / "models.json"
SESSIONS_FILE = FINE_TUNING_DIR / "sessions.json"


def _ensure_dir():
    """Crée le répertoire de stockage si nécessaire."""
    FINE_TUNING_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(file_path: Path) -> List[dict]:
    """Charge un fichier JSON."""
    if not file_path.exists():
        return []
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []


def _save_json(file_path: Path, data: List[dict]) -> None:
    """Sauvegarde dans un fichier JSON."""
    _ensure_dir()
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )


# =============================================================================
# USER CORRECTION STORE
# =============================================================================


class JsonUserCorrectionStore(UserCorrectionPort):
    """Stockage JSON des corrections utilisateur."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or CORRECTIONS_FILE

    def _to_dict(self, correction: UserCorrection) -> dict:
        return {
            "id": correction.id,
            "draft_id": correction.draft_id,
            "original_text": correction.original_text,
            "corrected_text": correction.corrected_text,
            "correction_types": [ct.value for ct in correction.correction_types],
            "context": correction.context,
            "created_at": correction.created_at.isoformat(),
            "user_comment": correction.user_comment,
            "account_id": correction.account_id,
        }

    def _from_dict(self, data: dict) -> UserCorrection:
        return UserCorrection(
            id=data["id"],
            draft_id=data["draft_id"],
            original_text=data["original_text"],
            corrected_text=data["corrected_text"],
            correction_types=[
                CorrectionType(ct) for ct in data.get("correction_types", [])
            ],
            context=data.get("context", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            user_comment=data.get("user_comment"),
            account_id=data.get("account_id"),
        )

    def save(self, correction: UserCorrection) -> str:
        data = _load_json(self.file_path)
        data.append(self._to_dict(correction))
        _save_json(self.file_path, data)
        return correction.id

    def get_by_id(self, correction_id: str) -> Optional[UserCorrection]:
        data = _load_json(self.file_path)
        for item in data:
            if item["id"] == correction_id:
                return self._from_dict(item)
        return None

    def get_by_draft_id(self, draft_id: str) -> List[UserCorrection]:
        data = _load_json(self.file_path)
        return [
            self._from_dict(item)
            for item in data
            if item["draft_id"] == draft_id
        ]

    def get_recent(
        self,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[UserCorrection]:
        data = _load_json(self.file_path)
        corrections = [self._from_dict(item) for item in data]

        if since:
            corrections = [c for c in corrections if c.created_at >= since]

        # Trier par date décroissante
        corrections.sort(key=lambda c: c.created_at, reverse=True)
        return corrections[:limit]

    def get_by_correction_type(
        self,
        correction_type: CorrectionType,
        limit: int = 100,
    ) -> List[UserCorrection]:
        data = _load_json(self.file_path)
        corrections = []
        for item in data:
            if correction_type.value in item.get("correction_types", []):
                corrections.append(self._from_dict(item))
        return corrections[:limit]

    def count(self) -> int:
        return len(_load_json(self.file_path))

    def delete(self, correction_id: str) -> bool:
        data = _load_json(self.file_path)
        initial_len = len(data)
        data = [item for item in data if item["id"] != correction_id]
        if len(data) < initial_len:
            _save_json(self.file_path, data)
            return True
        return False


# =============================================================================
# USER FEEDBACK STORE
# =============================================================================


class JsonUserFeedbackStore(UserFeedbackPort):
    """Stockage JSON des feedbacks utilisateur."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or FEEDBACKS_FILE

    def _to_dict(self, feedback: UserFeedback) -> dict:
        return {
            "id": feedback.id,
            "draft_id": feedback.draft_id,
            "rating": feedback.rating,
            "sentiment": feedback.sentiment.value,
            "comment": feedback.comment,
            "tags": feedback.tags,
            "created_at": feedback.created_at.isoformat(),
            "account_id": feedback.account_id,
        }

    def _from_dict(self, data: dict) -> UserFeedback:
        return UserFeedback(
            id=data["id"],
            draft_id=data["draft_id"],
            rating=data["rating"],
            sentiment=FeedbackSentiment(data["sentiment"]),
            comment=data.get("comment"),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            account_id=data.get("account_id"),
        )

    def save(self, feedback: UserFeedback) -> str:
        data = _load_json(self.file_path)
        data.append(self._to_dict(feedback))
        _save_json(self.file_path, data)
        return feedback.id

    def get_by_id(self, feedback_id: str) -> Optional[UserFeedback]:
        data = _load_json(self.file_path)
        for item in data:
            if item["id"] == feedback_id:
                return self._from_dict(item)
        return None

    def get_by_draft_id(self, draft_id: str) -> Optional[UserFeedback]:
        data = _load_json(self.file_path)
        for item in data:
            if item["draft_id"] == draft_id:
                return self._from_dict(item)
        return None

    def get_by_sentiment(
        self,
        sentiment: FeedbackSentiment,
        limit: int = 100,
    ) -> List[UserFeedback]:
        data = _load_json(self.file_path)
        feedbacks = [
            self._from_dict(item)
            for item in data
            if item["sentiment"] == sentiment.value
        ]
        return feedbacks[:limit]

    def get_by_rating_range(
        self,
        min_rating: int,
        max_rating: int,
        limit: int = 100,
    ) -> List[UserFeedback]:
        data = _load_json(self.file_path)
        feedbacks = [
            self._from_dict(item)
            for item in data
            if min_rating <= item["rating"] <= max_rating
        ]
        return feedbacks[:limit]

    def get_recent(
        self,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[UserFeedback]:
        data = _load_json(self.file_path)
        feedbacks = [self._from_dict(item) for item in data]

        if since:
            feedbacks = [f for f in feedbacks if f.created_at >= since]

        feedbacks.sort(key=lambda f: f.created_at, reverse=True)
        return feedbacks[:limit]

    def count(self) -> int:
        return len(_load_json(self.file_path))

    def get_average_rating(self) -> float:
        data = _load_json(self.file_path)
        if not data:
            return 0.0
        return sum(item["rating"] for item in data) / len(data)

    def get_sentiment_distribution(self) -> Dict[str, int]:
        data = _load_json(self.file_path)
        distribution = {s.value: 0 for s in FeedbackSentiment}
        for item in data:
            sentiment = item.get("sentiment", FeedbackSentiment.NEUTRAL.value)
            distribution[sentiment] = distribution.get(sentiment, 0) + 1
        return distribution


# =============================================================================
# CORRECTION PATTERN STORE
# =============================================================================


class JsonCorrectionPatternStore(CorrectionPatternPort):
    """Stockage JSON des patterns de correction."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or PATTERNS_FILE

    def _to_dict(self, pattern: CorrectionPattern) -> dict:
        return {
            "id": pattern.id,
            "pattern_type": pattern.pattern_type.value,
            "original_pattern": pattern.original_pattern,
            "replacement": pattern.replacement,
            "occurrences": pattern.occurrences,
            "confidence": pattern.confidence,
            "contexts": pattern.contexts,
            "examples": pattern.examples,
            "created_at": pattern.created_at.isoformat(),
            "last_used": pattern.last_used.isoformat() if pattern.last_used else None,
            "account_id": pattern.account_id,
        }

    def _from_dict(self, data: dict) -> CorrectionPattern:
        return CorrectionPattern(
            id=data["id"],
            pattern_type=CorrectionType(data["pattern_type"]),
            original_pattern=data["original_pattern"],
            replacement=data["replacement"],
            occurrences=data.get("occurrences", 1),
            confidence=data.get("confidence", 0.5),
            contexts=data.get("contexts", []),
            examples=data.get("examples", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=(
                datetime.fromisoformat(data["last_used"])
                if data.get("last_used")
                else None
            ),
            account_id=data.get("account_id"),
        )

    def save(self, pattern: CorrectionPattern) -> str:
        data = _load_json(self.file_path)
        data.append(self._to_dict(pattern))
        _save_json(self.file_path, data)
        return pattern.id

    def update(self, pattern: CorrectionPattern) -> bool:
        data = _load_json(self.file_path)
        for i, item in enumerate(data):
            if item["id"] == pattern.id:
                data[i] = self._to_dict(pattern)
                _save_json(self.file_path, data)
                return True
        return False

    def get_by_id(self, pattern_id: str) -> Optional[CorrectionPattern]:
        data = _load_json(self.file_path)
        for item in data:
            if item["id"] == pattern_id:
                return self._from_dict(item)
        return None

    def get_by_type(
        self,
        pattern_type: CorrectionType,
        limit: int = 100,
    ) -> List[CorrectionPattern]:
        data = _load_json(self.file_path)
        patterns = [
            self._from_dict(item)
            for item in data
            if item["pattern_type"] == pattern_type.value
        ]
        return patterns[:limit]

    def get_reliable_patterns(
        self,
        min_confidence: float = 0.6,
        limit: int = 100,
    ) -> List[CorrectionPattern]:
        data = _load_json(self.file_path)
        patterns = [
            self._from_dict(item)
            for item in data
            if item.get("confidence", 0) >= min_confidence
        ]
        # Trier par confiance décroissante
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns[:limit]

    def find_similar(
        self,
        original_pattern: str,
        threshold: float = 0.8,
    ) -> Optional[CorrectionPattern]:
        data = _load_json(self.file_path)
        for item in data:
            existing_pattern = item.get("original_pattern", "")
            # Utiliser la similarité de séquence
            similarity = SequenceMatcher(
                None,
                original_pattern.lower(),
                existing_pattern.lower()
            ).ratio()
            if similarity >= threshold:
                return self._from_dict(item)
        return None

    def get_all(self, limit: int = 1000) -> List[CorrectionPattern]:
        data = _load_json(self.file_path)
        return [self._from_dict(item) for item in data[:limit]]

    def count(self) -> int:
        return len(_load_json(self.file_path))

    def delete(self, pattern_id: str) -> bool:
        data = _load_json(self.file_path)
        initial_len = len(data)
        data = [item for item in data if item["id"] != pattern_id]
        if len(data) < initial_len:
            _save_json(self.file_path, data)
            return True
        return False


# =============================================================================
# IMPROVEMENT MODEL STORE
# =============================================================================


class JsonImprovementModelStore(ImprovementModelPort):
    """Stockage JSON des modèles d'amélioration."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or MODELS_FILE

    def _to_dict(self, model: ImprovementModel) -> dict:
        return {
            "id": model.id,
            "version": model.version,
            "name": model.name,
            "description": model.description,
            "patterns": model.patterns,
            "prompt_adjustments": model.prompt_adjustments,
            "status": model.status.value,
            "impact_score": model.impact_score,
            "drafts_improved": model.drafts_improved,
            "created_at": model.created_at.isoformat(),
            "updated_at": model.updated_at.isoformat(),
            # C-6 (audit, issue #526): persist tenant ownership.
            "account_id": model.account_id,
        }

    def _from_dict(self, data: dict) -> ImprovementModel:
        # C-6: legacy entries without `account_id` round-trip as None and
        # are invisible to any account-scoped lookup (cf. ImprovementModel
        # docstring). They remain visible only to global admin paths.
        _aid = data.get("account_id")
        try:
            account_id = int(_aid) if _aid is not None else None
        except (TypeError, ValueError):
            account_id = None
        return ImprovementModel(
            id=data["id"],
            version=data["version"],
            name=data["name"],
            description=data["description"],
            patterns=data.get("patterns", []),
            prompt_adjustments=data.get("prompt_adjustments", []),
            status=ImprovementStatus(data.get("status", "pending")),
            impact_score=data.get("impact_score", 0.0),
            drafts_improved=data.get("drafts_improved", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            account_id=account_id,
        )

    def save(self, model: ImprovementModel) -> str:
        data = _load_json(self.file_path)
        data.append(self._to_dict(model))
        _save_json(self.file_path, data)
        return model.id

    def update(self, model: ImprovementModel) -> bool:
        data = _load_json(self.file_path)
        for i, item in enumerate(data):
            if item["id"] == model.id:
                data[i] = self._to_dict(model)
                _save_json(self.file_path, data)
                return True
        return False

    def get_by_id(self, model_id: str) -> Optional[ImprovementModel]:
        data = _load_json(self.file_path)
        for item in data:
            if item["id"] == model_id:
                return self._from_dict(item)
        return None

    def get_active_models(self) -> List[ImprovementModel]:
        data = _load_json(self.file_path)
        return [
            self._from_dict(item)
            for item in data
            if item.get("status") == ImprovementStatus.ACTIVE.value
        ]

    def get_by_status(
        self,
        status: ImprovementStatus,
        limit: int = 100,
    ) -> List[ImprovementModel]:
        data = _load_json(self.file_path)
        models = [
            self._from_dict(item)
            for item in data
            if item.get("status") == status.value
        ]
        return models[:limit]

    def get_latest(self) -> Optional[ImprovementModel]:
        data = _load_json(self.file_path)
        if not data:
            return None
        # Trier par date de création décroissante
        data.sort(key=lambda x: x["created_at"], reverse=True)
        return self._from_dict(data[0])

    def count(self) -> int:
        return len(_load_json(self.file_path))

    def delete(self, model_id: str) -> bool:
        data = _load_json(self.file_path)
        initial_len = len(data)
        data = [item for item in data if item["id"] != model_id]
        if len(data) < initial_len:
            _save_json(self.file_path, data)
            return True
        return False


# =============================================================================
# FINE TUNING SESSION STORE
# =============================================================================


class JsonFineTuningSessionStore(FineTuningSessionPort):
    """Stockage JSON des sessions de fine-tuning."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or SESSIONS_FILE

    def _to_dict(self, session: FineTuningSession) -> dict:
        return {
            "id": session.id,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "corrections_count": session.corrections_count,
            "feedbacks_count": session.feedbacks_count,
            "patterns_extracted": session.patterns_extracted,
            "model_id": session.model_id,
            "status": session.status,
            "account_id": session.account_id,
        }

    def _from_dict(self, data: dict) -> FineTuningSession:
        return FineTuningSession(
            id=data["id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=(
                datetime.fromisoformat(data["ended_at"])
                if data.get("ended_at")
                else None
            ),
            corrections_count=data.get("corrections_count", 0),
            feedbacks_count=data.get("feedbacks_count", 0),
            patterns_extracted=data.get("patterns_extracted", 0),
            model_id=data.get("model_id"),
            status=data.get("status", "running"),
            account_id=data.get("account_id"),
        )

    def save(self, session: FineTuningSession) -> str:
        data = _load_json(self.file_path)
        data.append(self._to_dict(session))
        _save_json(self.file_path, data)
        return session.id

    def update(self, session: FineTuningSession) -> bool:
        data = _load_json(self.file_path)
        for i, item in enumerate(data):
            if item["id"] == session.id:
                data[i] = self._to_dict(session)
                _save_json(self.file_path, data)
                return True
        return False

    def get_by_id(self, session_id: str) -> Optional[FineTuningSession]:
        data = _load_json(self.file_path)
        for item in data:
            if item["id"] == session_id:
                return self._from_dict(item)
        return None

    def get_recent(self, limit: int = 10) -> List[FineTuningSession]:
        data = _load_json(self.file_path)
        sessions = [self._from_dict(item) for item in data]
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions[:limit]

    def get_running(self) -> Optional[FineTuningSession]:
        data = _load_json(self.file_path)
        for item in data:
            if item.get("status") == "running":
                return self._from_dict(item)
        return None


# =============================================================================
# FINE TUNING ANALYZER (IMPLEMENTATION)
# =============================================================================


class DefaultFineTuningAnalyzer(FineTuningAnalyzerPort):
    """
    Analyseur de corrections par défaut.

    Utilise des règles heuristiques pour détecter les types de corrections
    et extraire des patterns.
    """

    # Indicateurs de ton
    FORMAL_INDICATORS = [
        "cordialement", "sincères salutations", "veuillez",
        "je vous prie", "vous êtes prié", "je me permets",
    ]
    INFORMAL_INDICATORS = [
        "salut", "coucou", "bisou", "biz", "à plus", "tchao",
    ]

    # Patterns de formatage
    BULLET_PATTERN = r"^\s*[-•*]\s+"
    NUMBERED_PATTERN = r"^\s*\d+[.)]\s+"

    def analyze_correction(
        self,
        original: str,
        corrected: str,
    ) -> List[CorrectionType]:
        """Analyse les types de corrections."""
        types = []

        # Détecter changement de ton
        if self._tone_changed(original, corrected):
            types.append(CorrectionType.TONE)

        # Détecter corrections grammaticales
        if self._has_grammar_changes(original, corrected):
            types.append(CorrectionType.GRAMMAR)

        # Détecter changements de style
        if self._style_changed(original, corrected):
            types.append(CorrectionType.STYLE)

        # Détecter ajout/suppression de contenu
        len_diff = abs(len(corrected) - len(original)) / max(len(original), 1)
        if len_diff > 0.3:
            types.append(CorrectionType.CONTENT)

        # Détecter changement de longueur significatif
        if len_diff > 0.2:
            types.append(CorrectionType.LENGTH)

        # Détecter changements de formatage
        if self._format_changed(original, corrected):
            types.append(CorrectionType.FORMAT)

        # Détecter changements de vocabulaire
        if self._vocabulary_changed(original, corrected):
            types.append(CorrectionType.VOCABULARY)

        # Détecter changements de structure
        if self._structure_changed(original, corrected):
            types.append(CorrectionType.STRUCTURE)

        return types if types else [CorrectionType.STYLE]

    def _tone_changed(self, original: str, corrected: str) -> bool:
        """Vérifie si le ton a changé."""
        orig_lower = original.lower()
        corr_lower = corrected.lower()

        orig_formal = any(ind in orig_lower for ind in self.FORMAL_INDICATORS)
        corr_formal = any(ind in corr_lower for ind in self.FORMAL_INDICATORS)

        orig_informal = any(ind in orig_lower for ind in self.INFORMAL_INDICATORS)
        corr_informal = any(ind in corr_lower for ind in self.INFORMAL_INDICATORS)

        return (orig_formal != corr_formal) or (orig_informal != corr_informal)

    def _has_grammar_changes(self, original: str, corrected: str) -> bool:
        """Vérifie les corrections grammaticales."""
        # Différences simples de ponctuation ou casse
        orig_words = set(original.lower().split())
        corr_words = set(corrected.lower().split())
        diff_ratio = len(orig_words.symmetric_difference(corr_words)) / max(
            len(orig_words), 1
        )
        return 0.05 < diff_ratio < 0.2

    def _style_changed(self, original: str, corrected: str) -> bool:
        """Vérifie les changements de style."""
        # Moyenne de longueur des phrases
        orig_sentences = original.split(".")
        corr_sentences = corrected.split(".")

        orig_avg = sum(len(s) for s in orig_sentences) / max(len(orig_sentences), 1)
        corr_avg = sum(len(s) for s in corr_sentences) / max(len(corr_sentences), 1)

        return abs(orig_avg - corr_avg) > 20

    def _format_changed(self, original: str, corrected: str) -> bool:
        """Vérifie les changements de formatage."""
        orig_bullets = len(re.findall(self.BULLET_PATTERN, original, re.MULTILINE))
        corr_bullets = len(re.findall(self.BULLET_PATTERN, corrected, re.MULTILINE))

        orig_numbered = len(re.findall(self.NUMBERED_PATTERN, original, re.MULTILINE))
        corr_numbered = len(re.findall(self.NUMBERED_PATTERN, corrected, re.MULTILINE))

        return (orig_bullets != corr_bullets) or (orig_numbered != corr_numbered)

    def _vocabulary_changed(self, original: str, corrected: str) -> bool:
        """Vérifie les changements de vocabulaire."""
        orig_words = set(original.lower().split())
        corr_words = set(corrected.lower().split())

        new_words = corr_words - orig_words
        removed_words = orig_words - corr_words

        return len(new_words) > 3 or len(removed_words) > 3

    def _structure_changed(self, original: str, corrected: str) -> bool:
        """Vérifie les changements de structure."""
        orig_paras = original.count("\n\n")
        corr_paras = corrected.count("\n\n")
        return abs(orig_paras - corr_paras) >= 2

    def extract_patterns(
        self,
        corrections: List[UserCorrection],
    ) -> List[CorrectionPattern]:
        """Extrait des patterns des corrections."""
        patterns = []
        type_counts: Dict[CorrectionType, List[UserCorrection]] = {}

        # Grouper par type de correction
        for correction in corrections:
            for ctype in correction.correction_types:
                if ctype not in type_counts:
                    type_counts[ctype] = []
                type_counts[ctype].append(correction)

        # Pour chaque type fréquent, créer un pattern
        for ctype, type_corrections in type_counts.items():
            if len(type_corrections) >= 3:
                # Trouver le motif commun
                common_start = self._find_common_pattern(
                    [c.original_text[:100] for c in type_corrections]
                )
                replacement = self._find_common_pattern(
                    [c.corrected_text[:100] for c in type_corrections]
                )

                if common_start and len(common_start) > 10:
                    pattern = CorrectionPattern.create(
                        pattern_type=ctype,
                        original_pattern=common_start,
                        replacement=replacement or "",
                        context=type_corrections[0].context,
                    )
                    pattern.occurrences = len(type_corrections)
                    pattern.confidence = min(1.0, len(type_corrections) / 10)
                    pattern.examples = [
                        {
                            "original": c.original_text[:200],
                            "corrected": c.corrected_text[:200],
                        }
                        for c in type_corrections[:5]
                    ]
                    patterns.append(pattern)

        return patterns

    def _find_common_pattern(self, texts: List[str]) -> str:
        """Trouve le motif commun dans une liste de textes."""
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]

        # Utiliser le plus long préfixe commun
        common = texts[0]
        for text in texts[1:]:
            while not text.startswith(common) and common:
                common = common[:-1]
        return common.strip()

    def generate_prompt_adjustments(
        self,
        patterns: List[CorrectionPattern],
    ) -> List[str]:
        """Génère des ajustements de prompt."""
        adjustments = []

        for pattern in patterns:
            if pattern.confidence >= 0.6:
                adj = self._generate_adjustment(pattern)
                if adj:
                    adjustments.append(adj)

        return adjustments

    def _generate_adjustment(self, pattern: CorrectionPattern) -> Optional[str]:
        """Génère un ajustement pour un pattern."""
        if pattern.pattern_type == CorrectionType.TONE:
            return f"Préfère un ton plus adapté. Évite: '{pattern.original_pattern[:50]}...'"

        elif pattern.pattern_type == CorrectionType.LENGTH:
            if len(pattern.replacement) < len(pattern.original_pattern):
                return "Sois plus concis dans tes réponses."
            else:
                return "Développe davantage tes réponses."

        elif pattern.pattern_type == CorrectionType.VOCABULARY:
            if pattern.replacement:
                return f"Utilise plutôt '{pattern.replacement[:30]}' au lieu de '{pattern.original_pattern[:30]}'"

        elif pattern.pattern_type == CorrectionType.FORMAT:
            return "Améliore la mise en forme avec des listes ou paragraphes structurés."

        elif pattern.pattern_type == CorrectionType.GRAMMAR:
            return "Vérifie attentivement la grammaire et l'orthographe."

        elif pattern.pattern_type == CorrectionType.STYLE:
            return "Adapte le style d'écriture au contexte."

        elif pattern.pattern_type == CorrectionType.STRUCTURE:
            return "Organise mieux la structure de la réponse."

        return None

    def apply_improvements(
        self,
        text: str,
        model: ImprovementModel,
        patterns: List[CorrectionPattern],
    ) -> str:
        """Applique les améliorations au texte."""
        improved = text

        # Appliquer les remplacements des patterns
        for pattern in patterns:
            if (
                pattern.original_pattern
                and pattern.replacement
                and pattern.original_pattern.lower() in improved.lower()
            ):
                # Remplacement insensible à la casse
                import re
                improved = re.sub(
                    re.escape(pattern.original_pattern),
                    pattern.replacement,
                    improved,
                    flags=re.IGNORECASE,
                )

        return improved
