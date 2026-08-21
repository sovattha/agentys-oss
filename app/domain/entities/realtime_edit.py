# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités du domaine pour l'édition temps réel des brouillons.

Cette fonctionnalité permet à un agent IA de corriger/améliorer le texte
d'un utilisateur en temps réel pendant qu'il écrit un nouveau courriel.

Les modifications se font "devant ses yeux" comme dans Gmail, sans devoir
quitter la zone de texte.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional
import uuid
import difflib


class ChangeType(Enum):
    """Type de changement de texte."""

    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"


class TriggerType(Enum):
    """Type de déclencheur pour la suggestion IA."""

    NONE = "none"  # Pas de déclenchement
    BLUR = "blur"  # Curseur quitte la zone
    TYPING_PAUSE = "typing_pause"  # Pause de frappe
    SENTENCE_END = "sentence_end"  # Fin de phrase
    MANUAL = "manual"  # Demande explicite


class SuggestionType(Enum):
    """Type de suggestion IA."""

    GRAMMAR = "grammar"
    SPELLING = "spelling"
    STYLE = "style"
    TONE = "tone"
    CAPITALIZATION = "capitalization"
    PUNCTUATION = "punctuation"
    CLARITY = "clarity"


class SuggestionStatus(Enum):
    """Statut d'une suggestion."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class TextDiff:
    """Représente une différence entre deux textes."""

    start: int
    end: int
    original: str
    replacement: str

    @property
    def is_insertion(self) -> bool:
        """Vérifie si c'est une insertion."""
        return len(self.original) == 0 and len(self.replacement) > 0

    @property
    def is_deletion(self) -> bool:
        """Vérifie si c'est une suppression."""
        return len(self.original) > 0 and len(self.replacement) == 0


@dataclass
class TextChange:
    """Représente un changement de texte effectué par l'utilisateur."""

    old_text: str
    new_text: str
    cursor_position: int
    change_type: ChangeType
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_typing(
        cls,
        old_text: str,
        new_text: str,
        cursor_position: int,
    ) -> "TextChange":
        """
        Crée un TextChange à partir d'une modification de texte.

        Détermine automatiquement le type de changement (INSERT, DELETE, REPLACE).
        """
        change_type = cls._detect_change_type(old_text, new_text)

        return cls(
            old_text=old_text,
            new_text=new_text,
            cursor_position=cursor_position,
            change_type=change_type,
        )

    @staticmethod
    def _detect_change_type(old_text: str, new_text: str) -> ChangeType:
        """Détecte le type de changement."""
        old_len = len(old_text)
        new_len = len(new_text)

        if new_len > old_len and new_text.startswith(old_text):
            return ChangeType.INSERT
        elif new_len < old_len and old_text.startswith(new_text):
            return ChangeType.DELETE
        else:
            return ChangeType.REPLACE


@dataclass
class EditTrigger:
    """Conditions de déclenchement pour la suggestion IA."""

    trigger_type: TriggerType
    pause_duration_ms: Optional[int] = None

    @property
    def should_process(self) -> bool:
        """Vérifie si le trigger doit déclencher une suggestion."""
        return self.trigger_type != TriggerType.NONE

    @classmethod
    def from_string(cls, trigger_str: str) -> "EditTrigger":
        """
        Crée un EditTrigger à partir d'une chaîne.

        Args:
            trigger_str: Nom du trigger (blur, typing_pause, sentence_end, manual, none).

        Returns:
            EditTrigger correspondant.
        """
        trigger_map = {
            "blur": TriggerType.BLUR,
            "typing_pause": TriggerType.TYPING_PAUSE,
            "sentence_end": TriggerType.SENTENCE_END,
            "manual": TriggerType.MANUAL,
            "none": TriggerType.NONE,
        }
        trigger_type = trigger_map.get(trigger_str.lower(), TriggerType.NONE)
        return cls(trigger_type=trigger_type)


@dataclass
class Suggestion:
    """Une suggestion de correction/amélioration par l'IA."""

    original_text: str
    suggested_text: str
    confidence: float
    suggestion_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    explanation: Optional[str] = None
    suggestion_types: List[SuggestionType] = field(default_factory=list)
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)

    def get_diffs(self) -> List[TextDiff]:
        """
        Retourne les différences entre le texte original et suggéré.

        Utilise difflib pour identifier précisément les changements.
        """
        diffs = []

        # Utiliser SequenceMatcher pour trouver les différences
        matcher = difflib.SequenceMatcher(
            None,
            self.original_text.split(),
            self.suggested_text.split(),
        )

        original_words = self.original_text.split()
        suggested_words = self.suggested_text.split()

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                original = " ".join(original_words[i1:i2])
                replacement = " ".join(suggested_words[j1:j2])
                diffs.append(
                    TextDiff(
                        start=i1,
                        end=i2,
                        original=original,
                        replacement=replacement,
                    )
                )
            elif tag == "delete":
                original = " ".join(original_words[i1:i2])
                diffs.append(
                    TextDiff(
                        start=i1,
                        end=i2,
                        original=original,
                        replacement="",
                    )
                )
            elif tag == "insert":
                replacement = " ".join(suggested_words[j1:j2])
                diffs.append(
                    TextDiff(
                        start=i1,
                        end=i1,
                        original="",
                        replacement=replacement,
                    )
                )

        return diffs

    def accept(self) -> None:
        """Marque la suggestion comme acceptée."""
        self.status = SuggestionStatus.ACCEPTED

    def reject(self) -> None:
        """Marque la suggestion comme rejetée."""
        self.status = SuggestionStatus.REJECTED


@dataclass
class SuggestionResult:
    """Résultat global d'une demande de suggestion."""

    session_id: str
    original_full_text: str
    suggestions: List[Suggestion] = field(default_factory=list)
    suggested_full_text: Optional[str] = None
    processing_time_ms: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    suggestion_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def has_changes(self) -> bool:
        """Vérifie si des changements sont suggérés."""
        return (
            self.suggested_full_text is not None
            and self.suggested_full_text != self.original_full_text
        )


@dataclass
class EditSession:
    """
    Représente une session d'édition temps réel.

    Une session suit le texte courant de l'utilisateur et permet
    de générer des suggestions d'amélioration.
    """

    session_id: str
    user_id: str
    current_text: str
    is_active: bool
    created_at: datetime
    closed_at: Optional[datetime] = None
    _last_activity_at: datetime = field(default=None, repr=False)
    _last_processed_text: str = field(default="", repr=False)
    version: int = 1

    def __post_init__(self):
        if self._last_activity_at is None:
            self._last_activity_at = self.created_at

    @classmethod
    def create(
        cls,
        user_id: str,
        initial_text: str = "",
    ) -> "EditSession":
        """
        Crée une nouvelle session d'édition.

        Args:
            user_id: ID de l'utilisateur.
            initial_text: Texte initial (optionnel).

        Returns:
            Une nouvelle instance de EditSession.
        """
        now = datetime.now()
        return cls(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            current_text=initial_text,
            is_active=True,
            created_at=now,
            _last_activity_at=now,
        )

    @property
    def last_activity_at(self) -> datetime:
        """Retourne le timestamp de la dernière activité."""
        return self._last_activity_at

    def update_text(self, new_text: str) -> None:
        """
        Met à jour le texte courant.

        Args:
            new_text: Le nouveau texte.

        Raises:
            TypeError: Si new_text est None.
        """
        if new_text is None:
            raise TypeError("new_text cannot be None")
        self.current_text = new_text
        self._last_activity_at = datetime.now()
        self.version += 1

    def close(self) -> None:
        """Ferme la session."""
        self.is_active = False
        self.closed_at = datetime.now()

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """
        Vérifie si la session a expiré.

        Args:
            timeout_minutes: Durée d'inactivité avant expiration (défaut: 30 min).
                Une valeur ≤ 0 force l'expiration immédiate.

        Returns:
            True si la session a expiré.
        """
        if not self.is_active:
            return True
        # timeout_minutes ≤ 0 : pas de grace period → expiration immédiate.
        if timeout_minutes <= 0:
            return True

        timeout = timedelta(minutes=timeout_minutes)
        now = datetime.now(timezone.utc) if self._last_activity_at.tzinfo else datetime.now()
        return now - self._last_activity_at > timeout

    def has_conflict(self, base_text: str) -> bool:
        """
        Vérifie s'il y a un conflit avec le texte de base.

        Utilisé pour détecter les modifications concurrentes.

        Args:
            base_text: Le texte de référence attendu.

        Returns:
            True s'il y a un conflit.
        """
        # Si le texte actuel n'est pas égal au texte de base,
        # il y a eu une modification concurrente
        return self.current_text != base_text and base_text != ""

    def mark_processed(self) -> None:
        """Marque le texte actuel comme traité."""
        self._last_processed_text = self.current_text

    @property
    def needs_processing(self) -> bool:
        """Vérifie si le texte a changé depuis le dernier traitement."""
        return self.current_text != self._last_processed_text
