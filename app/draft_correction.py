# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Auto-correction de brouillons modifiés par l'utilisateur.

Détecte les modifications utilisateur sur les brouillons et apprend
à appliquer des corrections similaires à l'avenir.

Usage:
    from app.draft_correction import DraftCorrectionManager, get_correction_manager

    manager = get_correction_manager()

    # Enregistrer une correction utilisateur
    manager.record_correction(original_draft, user_modified_draft, email_context)

    # Appliquer les corrections apprises à un nouveau brouillon
    corrected = manager.apply_learned_corrections(new_draft, email_context)
"""

import json
import re
import difflib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from app.config import (
    DATA_DIR,
    get_ai_artifact_retention_days,
    should_persist_email_content,
)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class DraftCorrection:
    """Représente une correction apportée par l'utilisateur."""
    id: str
    original_text: str
    corrected_text: str
    correction_type: str  # tone, grammar, content, format, length
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    applied_count: int = 0


@dataclass
class CorrectionPattern:
    """Pattern de correction appris."""
    id: str
    pattern_type: str  # phrase_replacement, tone_adjustment, format_change
    original_pattern: str
    replacement: str
    confidence: float = 0.0
    occurrences: int = 0
    applied_count: int = 0
    contexts: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: Optional[str] = None
    notified: bool = False


@dataclass
class CorrectionStats:
    """Statistiques des corrections."""
    total_corrections: int = 0
    patterns_learned: int = 0
    corrections_applied: int = 0
    accuracy_rate: float = 0.0
    by_type: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# CORRECTION ANALYZER
# ============================================================================

class CorrectionAnalyzer:
    """Analyse les différences entre brouillon original et corrigé."""

    # Indicateurs de type de correction
    TONE_INDICATORS = {
        "formal": ["cordialement", "sincères salutations", "veuillez agréer"],
        "informal": ["à bientôt", "salut", "ciao", "bisous"],
        "professional": ["je vous prie", "nous vous informons", "conformément"],
        "friendly": ["merci beaucoup", "avec plaisir", "n'hésite pas"]
    }

    FORMAT_PATTERNS = {
        "bullet_list": r"^[\-\*•]\s",
        "numbered_list": r"^\d+\.\s",
        "paragraph_break": r"\n\n",
        "signature": r"(?:cordialement|regards|best|--)",
    }

    def analyze_diff(
        self,
        original: str,
        corrected: str
    ) -> Dict[str, Any]:
        """
        Analyse les différences entre l'original et la correction.

        Returns:
            Dict avec le type de correction et les détails
        """
        analysis = {
            "correction_type": "unknown",
            "changes": [],
            "tone_change": None,
            "length_change": 0,
            "format_changes": [],
            "word_replacements": [],
            "additions": [],
            "deletions": []
        }

        # Calcul du changement de longueur
        analysis["length_change"] = len(corrected) - len(original)

        # Analyse ligne par ligne
        original_lines = original.splitlines()
        corrected_lines = corrected.splitlines()

        differ = difflib.unified_diff(
            original_lines,
            corrected_lines,
            lineterm=""
        )

        additions = []
        deletions = []

        for line in differ:
            if line.startswith("+") and not line.startswith("+++"):
                additions.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                deletions.append(line[1:])

        analysis["additions"] = additions
        analysis["deletions"] = deletions

        # Détection du type de correction
        analysis["correction_type"] = self._detect_correction_type(
            original, corrected, additions, deletions
        )

        # Détection du changement de ton
        analysis["tone_change"] = self._detect_tone_change(original, corrected)

        # Extraction des remplacements de mots
        analysis["word_replacements"] = self._extract_word_replacements(
            original, corrected
        )

        return analysis

    def _detect_correction_type(
        self,
        original: str,
        corrected: str,
        additions: List[str],
        deletions: List[str]
    ) -> str:
        """Détecte le type principal de correction."""

        # Vérifier le changement de longueur significatif
        length_ratio = len(corrected) / max(len(original), 1)
        if length_ratio < 0.5:
            return "length_reduction"
        elif length_ratio > 1.5:
            return "content_addition"

        # Vérifier les changements de structure (réorganisation paragraphes, listes)
        orig_has_bullets = bool(re.search(self.FORMAT_PATTERNS["bullet_list"], original, re.MULTILINE))
        corr_has_bullets = bool(re.search(self.FORMAT_PATTERNS["bullet_list"], corrected, re.MULTILINE))
        orig_paras = len([p for p in original.split('\n\n') if p.strip()])
        corr_paras = len([p for p in corrected.split('\n\n') if p.strip()])
        if orig_has_bullets != corr_has_bullets or abs(orig_paras - corr_paras) >= 2:
            return "structure"

        # Vérifier les changements de ton
        for tone, indicators in self.TONE_INDICATORS.items():
            orig_count = sum(1 for ind in indicators if ind.lower() in original.lower())
            corr_count = sum(1 for ind in indicators if ind.lower() in corrected.lower())
            if abs(orig_count - corr_count) > 0:
                return "tone"

        # Vérifier les remplacements de vocabulaire (mots substitués, longueur similaire)
        if len(additions) == len(deletions) and 1 <= len(additions) <= 10:
            # Si la longueur globale est similaire, c'est probablement du vocabulaire
            if 0.8 <= len(corrected) / max(len(original), 1) <= 1.2:
                return "vocabulary"

        # Vérifier les corrections grammaticales (petits changements)
        if len(additions) == len(deletions) and len(additions) < 5:
            return "grammar"

        # Par défaut, c'est une modification de contenu
        return "content"

    def _detect_tone_change(
        self,
        original: str,
        corrected: str
    ) -> Optional[Dict[str, str]]:
        """Détecte si le ton a changé."""

        def get_tone(text: str) -> str:
            text_lower = text.lower()
            scores = {}
            for tone, indicators in self.TONE_INDICATORS.items():
                scores[tone] = sum(1 for ind in indicators if ind in text_lower)
            if max(scores.values()) == 0:
                return "neutral"
            return max(scores, key=scores.get)

        orig_tone = get_tone(original)
        corr_tone = get_tone(corrected)

        if orig_tone != corr_tone:
            return {"from": orig_tone, "to": corr_tone}
        return None

    def _extract_word_replacements(
        self,
        original: str,
        corrected: str
    ) -> List[Dict[str, str]]:
        """Extrait les remplacements de mots/phrases."""

        replacements = []

        # Tokenization simple
        orig_words = original.split()
        corr_words = corrected.split()

        # Utiliser SequenceMatcher pour trouver les remplacements
        matcher = difflib.SequenceMatcher(None, orig_words, corr_words)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                orig_phrase = " ".join(orig_words[i1:i2])
                corr_phrase = " ".join(corr_words[j1:j2])
                if orig_phrase and corr_phrase:
                    replacements.append({
                        "original": orig_phrase,
                        "replacement": corr_phrase
                    })

        return replacements


# ============================================================================
# CORRECTION MANAGER
# ============================================================================

class DraftCorrectionManager:
    """
    Gestionnaire des corrections de brouillons.

    Enregistre les corrections utilisateur, apprend des patterns,
    et applique les corrections apprises aux nouveaux brouillons.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DATA_DIR / "corrections"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.corrections_file = self.data_dir / "corrections.json"
        self.patterns_file = self.data_dir / "patterns.json"

        self.corrections: List[DraftCorrection] = []
        self.patterns: List[CorrectionPattern] = []
        self.analyzer = CorrectionAnalyzer()

        self._load()

    def _load(self) -> None:
        """Charge les corrections et patterns depuis le disque."""
        if self.corrections_file.exists():
            try:
                data = json.loads(self.corrections_file.read_text(encoding="utf-8"))
                self.corrections = [DraftCorrection(**c) for c in data]
            except Exception:
                self.corrections = []

        if self.patterns_file.exists():
            try:
                data = json.loads(self.patterns_file.read_text(encoding="utf-8"))
                self.patterns = [CorrectionPattern(**p) for p in data]
            except Exception:
                self.patterns = []

        self._minimize_loaded_content()
        self._prune_expired_artifacts()

    @staticmethod
    def _safe_scalar(value: Any) -> Any:
        """Conserve uniquement des scalaires courts pour les contextes persistés."""
        if isinstance(value, (bool, int, float)):
            return value
        return str(value)[:120]

    def _context_for_storage(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Retire les champs de contexte qui peuvent contenir le contenu de l'email."""
        context = context or {}
        if should_persist_email_content():
            return dict(context)

        safe_context: Dict[str, Any] = {}
        for key in ("account_id", "category", "domain", "intent", "label", "provider"):
            if key in context and context[key] is not None:
                safe_context[key] = self._safe_scalar(context[key])

        sender = context.get("sender") or context.get("from") or context.get("email_sender")
        if isinstance(sender, str) and "@" in sender:
            domain = sender.rsplit("@", 1)[1].strip().lower()
            if domain:
                safe_context["sender_domain"] = domain[:120]

        return safe_context

    @staticmethod
    def _context_to_json(context: Dict[str, Any]) -> str:
        """Sérialise un contexte de manière stable pour éviter les doublons."""
        return json.dumps(context, ensure_ascii=False, sort_keys=True)

    def _sanitize_contexts(self, contexts: List[str]) -> List[str]:
        """Minimise les contextes déjà chargés depuis un fichier legacy."""
        sanitized: List[str] = []
        for context_str in contexts:
            try:
                parsed = json.loads(context_str)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            safe_context = self._context_for_storage(parsed)
            if not safe_context:
                continue
            encoded = self._context_to_json(safe_context)
            if encoded not in sanitized:
                sanitized.append(encoded)
        return sanitized

    def _minimize_loaded_content(self) -> None:
        """Applique la minimisation aux fichiers legacy chargés en mémoire."""
        if should_persist_email_content():
            return

        for correction in self.corrections:
            correction.original_text = ""
            correction.corrected_text = ""
            correction.context = self._context_for_storage(correction.context)

        for pattern in self.patterns:
            if pattern.pattern_type == "phrase_replacement":
                pattern.original_pattern = ""
                pattern.replacement = ""
            pattern.contexts = self._sanitize_contexts(pattern.contexts)

    def _correction_to_dict(self, correction: DraftCorrection) -> Dict[str, Any]:
        """Retourne la version persistable d'une correction."""
        payload = asdict(correction)
        if not should_persist_email_content():
            payload["original_text"] = ""
            payload["corrected_text"] = ""
            payload["context"] = self._context_for_storage(correction.context)
        return payload

    def _pattern_to_dict(self, pattern: CorrectionPattern) -> Dict[str, Any]:
        """Retourne la version persistable d'un pattern."""
        payload = asdict(pattern)
        if not should_persist_email_content():
            if pattern.pattern_type == "phrase_replacement":
                payload["original_pattern"] = ""
                payload["replacement"] = ""
            payload["contexts"] = self._sanitize_contexts(pattern.contexts)
        return payload

    @staticmethod
    def _is_recent_iso(value: str | None, *, retention_days: int) -> bool:
        if not value:
            return True
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return parsed >= now - timedelta(days=retention_days)

    def _prune_expired_artifacts(self) -> None:
        if should_persist_email_content():
            return

        retention_days = get_ai_artifact_retention_days()
        self.corrections = [
            correction for correction in self.corrections
            if self._is_recent_iso(correction.created_at, retention_days=retention_days)
        ]

    def prune_expired(self) -> int:
        """Applique la rétention configurée et persiste si nécessaire."""
        before = len(self.corrections)
        self._prune_expired_artifacts()
        removed = max(before - len(self.corrections), 0)
        if removed:
            self._save()
        return removed

    @staticmethod
    def _context_matches_account(context: Dict[str, Any], account_id: int) -> bool:
        return str(context.get("account_id") or "") == str(account_id)

    def delete_by_account(self, account_id: int) -> Dict[str, int]:
        """Supprime les corrections/pattern contexts associés à un compte."""
        before_corrections = len(self.corrections)
        self.corrections = [
            correction for correction in self.corrections
            if not self._context_matches_account(correction.context, account_id)
        ]

        removed_contexts = 0
        kept_patterns: List[CorrectionPattern] = []
        for pattern in self.patterns:
            original_contexts = list(pattern.contexts)
            if original_contexts:
                pattern.contexts = [
                    context_str for context_str in original_contexts
                    if not self._context_string_matches_account(context_str, account_id)
                ]
                removed_contexts += len(original_contexts) - len(pattern.contexts)
                if not pattern.contexts:
                    continue
            kept_patterns.append(pattern)
        before_patterns = len(self.patterns)
        self.patterns = kept_patterns

        removed = {
            "corrections": before_corrections - len(self.corrections),
            "patterns": before_patterns - len(self.patterns),
            "pattern_contexts": removed_contexts,
        }
        if any(removed.values()):
            self._save()
        return removed

    @staticmethod
    def _context_string_matches_account(context_str: str, account_id: int) -> bool:
        try:
            parsed = json.loads(context_str)
        except Exception:
            return False
        return isinstance(parsed, dict) and str(parsed.get("account_id") or "") == str(account_id)

    def _save(self) -> None:
        """Sauvegarde les corrections et patterns."""
        self._prune_expired_artifacts()
        self.corrections_file.write_text(
            json.dumps([self._correction_to_dict(c) for c in self.corrections], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        self.patterns_file.write_text(
            json.dumps([self._pattern_to_dict(p) for p in self.patterns], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def record_correction(
        self,
        original_draft: str,
        corrected_draft: str,
        context: Optional[Dict[str, Any]] = None
    ) -> DraftCorrection:
        """
        Enregistre une correction utilisateur et apprend de celle-ci.

        Args:
            original_draft: Le brouillon original généré par l'IA
            corrected_draft: Le brouillon modifié par l'utilisateur
            context: Contexte additionnel (expéditeur, sujet, catégorie, etc.)

        Returns:
            La correction enregistrée
        """
        # Analyser les différences
        analysis = self.analyzer.analyze_diff(original_draft, corrected_draft)

        # Créer la correction
        persist_content = should_persist_email_content()
        correction = DraftCorrection(
            id=f"corr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.corrections)}",
            original_text=original_draft if persist_content else "",
            corrected_text=corrected_draft if persist_content else "",
            correction_type=analysis["correction_type"],
            context=self._context_for_storage(context)
        )

        self.corrections.append(correction)

        # Apprendre les patterns
        self._learn_patterns(analysis, context)

        self._save()
        return correction

    def _learn_patterns(
        self,
        analysis: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Apprend des patterns à partir de l'analyse."""

        # Apprendre les remplacements de mots/phrases
        for replacement in analysis.get("word_replacements", []):
            self._add_or_update_pattern(
                pattern_type="phrase_replacement",
                original=replacement["original"],
                replacement=replacement["replacement"],
                context=context
            )

        # Apprendre les changements de ton
        if analysis.get("tone_change"):
            tone_change = analysis["tone_change"]
            self._add_or_update_pattern(
                pattern_type="tone_adjustment",
                original=tone_change["from"],
                replacement=tone_change["to"],
                context=context
            )

    def _add_or_update_pattern(
        self,
        pattern_type: str,
        original: str,
        replacement: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Ajoute ou met à jour un pattern."""
        if pattern_type == "phrase_replacement" and not should_persist_email_content():
            return

        storage_context = self._context_for_storage(context)
        context_str = self._context_to_json(storage_context) if storage_context else None

        # Chercher un pattern existant
        existing = None
        for p in self.patterns:
            if (p.pattern_type == pattern_type and
                p.original_pattern == original and
                p.replacement == replacement):
                existing = p
                break

        if existing:
            existing.occurrences += 1
            existing.confidence = min(1.0, existing.occurrences / 5)
            existing.last_used = datetime.now().isoformat()
            if context_str and context_str not in existing.contexts:
                existing.contexts.append(context_str)
        else:
            pattern = CorrectionPattern(
                id=f"pat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.patterns)}",
                pattern_type=pattern_type,
                original_pattern=original,
                replacement=replacement,
                confidence=0.2,
                occurrences=1,
                contexts=[context_str] if context_str else []
            )
            self.patterns.append(pattern)

    def apply_learned_corrections(
        self,
        draft: str,
        context: Optional[Dict[str, Any]] = None,
        min_confidence: float = 0.6
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Applique les corrections apprises à un brouillon.

        Args:
            draft: Le brouillon à corriger
            context: Contexte pour filtrer les patterns pertinents
            min_confidence: Confiance minimale pour appliquer un pattern

        Returns:
            Tuple (brouillon corrigé, liste des corrections appliquées)
        """
        corrected = draft
        applied = []

        # Filtrer les patterns par confiance
        applicable_patterns = [
            p for p in self.patterns
            if p.confidence >= min_confidence
        ]

        # Trier par confiance (plus confiant d'abord)
        applicable_patterns.sort(key=lambda p: -p.confidence)

        # Appliquer les remplacements de phrases
        for pattern in applicable_patterns:
            if pattern.pattern_type == "phrase_replacement":
                if pattern.original_pattern and pattern.original_pattern in corrected:
                    corrected = corrected.replace(
                        pattern.original_pattern,
                        pattern.replacement
                    )
                    applied.append({
                        "pattern_id": pattern.id,
                        "type": pattern.pattern_type,
                        "original": pattern.original_pattern,
                        "replacement": pattern.replacement,
                        "confidence": pattern.confidence
                    })
                    pattern.applied_count += 1
                    pattern.last_used = datetime.now().isoformat()

        if applied:
            self._save()

        return corrected, applied

    def detect_user_modification(
        self,
        original_draft: str,
        current_draft: str,
        threshold: float = 0.1
    ) -> bool:
        """
        Détecte si l'utilisateur a modifié le brouillon.

        Args:
            original_draft: Le brouillon original
            current_draft: Le brouillon actuel
            threshold: Seuil de différence (0.1 = 10% de changement)

        Returns:
            True si le brouillon a été modifié significativement
        """
        if original_draft == current_draft:
            return False

        # Calculer le ratio de similarité
        ratio = difflib.SequenceMatcher(
            None, original_draft, current_draft
        ).ratio()

        # Si la similarité est en dessous de (1 - threshold), c'est modifié
        return ratio < (1 - threshold)

    def get_stats(self) -> CorrectionStats:
        """Retourne les statistiques des corrections."""
        by_type = defaultdict(int)
        for c in self.corrections:
            by_type[c.correction_type] += 1

        total_applied = sum(p.applied_count for p in self.patterns)

        return CorrectionStats(
            total_corrections=len(self.corrections),
            patterns_learned=len(self.patterns),
            corrections_applied=total_applied,
            accuracy_rate=0.0,  # À calculer avec feedback
            by_type=dict(by_type)
        )

    def get_patterns_for_context(
        self,
        context: Dict[str, Any],
        min_confidence: float = 0.5
    ) -> List[CorrectionPattern]:
        """Retourne les patterns pertinents pour un contexte donné."""
        relevant = []
        safe_context = self._context_for_storage(context)
        match_values = [
            value
            for source in (context, safe_context)
            for value in source.values()
            if isinstance(value, str)
        ]

        for pattern in self.patterns:
            if pattern.confidence < min_confidence:
                continue

            # Vérifier si le contexte correspond
            for ctx in pattern.contexts:
                if any(v in ctx for v in match_values):
                    relevant.append(pattern)
                    break

        return relevant

    def clear_patterns(self, min_occurrences: int = 1) -> int:
        """Supprime les patterns avec peu d'occurrences."""
        initial = len(self.patterns)
        self.patterns = [
            p for p in self.patterns
            if p.occurrences >= min_occurrences
        ]
        removed = initial - len(self.patterns)
        if removed > 0:
            self._save()
        return removed


    def get_newly_reliable_patterns(self, min_occurrences: int = 3) -> List[CorrectionPattern]:
        """
        Retourne les patterns fiables qui n'ont pas encore été notifiés.

        Un pattern est considéré fiable quand il atteint le seuil minimum
        d'occurrences (défaut: 3 selon la config LEARNING_CONFIG).

        Args:
            min_occurrences: Seuil minimum d'occurrences pour être fiable.

        Returns:
            Liste des patterns fiables non notifiés.
        """
        return [
            p for p in self.patterns
            if p.occurrences >= min_occurrences and not p.notified
        ]

    def mark_patterns_as_notified(self, pattern_ids: List[str]) -> None:
        """
        Marque les patterns comme notifiés pour éviter les doublons.

        Args:
            pattern_ids: Liste des IDs de patterns à marquer.
        """
        for pattern in self.patterns:
            if pattern.id in pattern_ids:
                pattern.notified = True
        self._save()

    def get_pattern_summaries(self, patterns: List[CorrectionPattern]) -> List[str]:
        """
        Génère des résumés lisibles pour les notifications.

        Args:
            patterns: Liste des patterns à résumer.

        Returns:
            Liste de descriptions lisibles.
        """
        summaries = []
        for p in patterns:
            if p.pattern_type == "phrase_replacement":
                if p.original_pattern:
                    summary = f"Remplacement: '{p.original_pattern}' → '{p.replacement}'"
                else:
                    summary = "Remplacement de phrase non persisté"
            elif p.pattern_type == "tone_adjustment":
                summary = f"Ton: de {p.original_pattern} vers {p.replacement}"
            else:
                summary = f"{p.pattern_type}: {p.original_pattern} → {p.replacement}"
            summaries.append(summary)
        return summaries


# ============================================================================
# SINGLETON
# ============================================================================

_correction_manager: Optional[DraftCorrectionManager] = None


def get_correction_manager() -> DraftCorrectionManager:
    """Retourne l'instance singleton du DraftCorrectionManager."""
    global _correction_manager
    if _correction_manager is None:
        _correction_manager = DraftCorrectionManager()
    return _correction_manager
