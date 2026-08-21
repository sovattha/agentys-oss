# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Cases pour l'édition temps réel des brouillons.

Ces use cases orchestrent la logique métier pour:
- Démarrer/fermer une session d'édition
- Traiter les changements de texte
- Générer et appliquer des suggestions IA
"""

from dataclasses import dataclass
from typing import Optional
import time

from app.domain.entities.realtime_edit import (
    EditSession,
    TextChange,
    EditTrigger,
    Suggestion,
    SuggestionResult,
    SuggestionType,
)
from app.domain.ports.realtime_edit_port import EditSessionStorePort
from app.domain.ports.llm_port import LLMPort


# Prompt système par défaut pour la correction de texte
DEFAULT_CORRECTION_PROMPT = """Tu es un assistant de rédaction d'emails professionnels.
Ta tâche est de corriger et améliorer le texte fourni par l'utilisateur.

Règles:
1. Corrige les fautes d'orthographe et de grammaire
2. Améliore la ponctuation et les majuscules
3. Garde le sens et le ton original
4. Ne modifie PAS le contenu ou le message principal
5. Retourne UNIQUEMENT le texte corrigé, sans explication
6. Si le texte est déjà correct, retourne-le tel quel

Le texte doit rester naturel et dans la même langue que l'original."""


@dataclass
class StartEditSessionUseCase:
    """
    Use case pour démarrer une session d'édition temps réel.

    Crée une nouvelle session et la sauvegarde dans le store.
    """

    session_store: EditSessionStorePort

    def execute(
        self,
        user_id: str,
        initial_text: str = "",
    ) -> EditSession:
        """
        Démarre une nouvelle session d'édition.

        Args:
            user_id: ID de l'utilisateur.
            initial_text: Texte initial optionnel.

        Returns:
            La nouvelle session créée.
        """
        session = EditSession.create(
            user_id=user_id,
            initial_text=initial_text,
        )

        self.session_store.save(session)

        return session


@dataclass
class ProcessTextChangeUseCase:
    """
    Use case pour traiter un changement de texte.

    Met à jour le texte de la session avec le nouveau contenu.
    """

    session_store: EditSessionStorePort

    def execute(
        self,
        session_id: str,
        change: TextChange,
    ) -> Optional[EditSession]:
        """
        Traite un changement de texte.

        Args:
            session_id: ID de la session.
            change: Le changement à appliquer.

        Returns:
            La session mise à jour, None si non trouvée.
        """
        session = self.session_store.get(session_id)

        if session is None:
            return None

        if not session.is_active:
            return None

        session.update_text(change.new_text)
        self.session_store.save(session)

        return session


@dataclass
class GetSuggestionUseCase:
    """
    Use case pour obtenir une suggestion de correction IA.

    Génère une suggestion basée sur le texte courant de la session
    si les conditions de déclenchement sont remplies.
    """

    session_store: EditSessionStorePort
    llm: LLMPort
    max_text_length: int = 5000
    system_prompt: str = DEFAULT_CORRECTION_PROMPT

    def execute(
        self,
        session_id: str,
        trigger: EditTrigger,
    ) -> Optional[SuggestionResult]:
        """
        Génère une suggestion pour le texte courant.

        Args:
            session_id: ID de la session.
            trigger: Le déclencheur de la suggestion.

        Returns:
            Le résultat de suggestion, None si pas applicable.
        """
        # Vérifier le trigger
        if not trigger.should_process:
            return None

        # Récupérer la session
        session = self.session_store.get(session_id)
        if session is None:
            return None

        if not session.is_active:
            return None

        # Pas de suggestion pour texte vide
        original_text = session.current_text.strip()
        if not original_text:
            return None

        # Mesurer le temps de traitement
        start_time = time.time()

        # Tronquer si nécessaire
        text_to_process = original_text
        if len(text_to_process) > self.max_text_length:
            text_to_process = text_to_process[: self.max_text_length]

        # Appeler le LLM pour obtenir la correction
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                user=text_to_process,
                max_tokens=len(text_to_process) + 500,
            )
        except Exception:
            return None

        suggested_text = response.content.strip()

        # Calculer le temps de traitement
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Créer les suggestions individuelles
        suggestions = []
        if suggested_text != original_text:
            # Créer une suggestion globale
            suggestion = Suggestion(
                original_text=original_text,
                suggested_text=suggested_text,
                confidence=0.9,  # Confiance par défaut
                suggestion_types=[SuggestionType.GRAMMAR, SuggestionType.SPELLING],
            )
            suggestions.append(suggestion)

        # Créer le résultat
        result = SuggestionResult(
            session_id=session_id,
            original_full_text=original_text,
            suggested_full_text=suggested_text,
            suggestions=suggestions,
            processing_time_ms=processing_time_ms,
        )

        # Marquer le texte comme traité
        session.mark_processed()
        self.session_store.save(session)

        return result


@dataclass
class ApplySuggestionUseCase:
    """
    Use case pour appliquer ou rejeter une suggestion.

    Met à jour le texte de la session si la suggestion est acceptée.
    """

    session_store: EditSessionStorePort

    def execute(
        self,
        session_id: str,
        suggestion: Suggestion,
        accept: bool,
    ) -> Optional[EditSession]:
        """
        Applique ou rejette une suggestion.

        Args:
            session_id: ID de la session.
            suggestion: La suggestion à traiter.
            accept: True pour accepter, False pour rejeter.

        Returns:
            La session mise à jour.
        """
        session = self.session_store.get(session_id)
        if session is None:
            return None

        if accept:
            # Appliquer la suggestion
            suggestion.accept()

            # Remplacer le texte original par le texte suggéré
            new_text = session.current_text.replace(
                suggestion.original_text,
                suggestion.suggested_text,
            )
            session.update_text(new_text)
        else:
            suggestion.reject()

        self.session_store.save(session)

        return session


@dataclass
class CloseEditSessionUseCase:
    """
    Use case pour fermer une session d'édition.
    """

    session_store: EditSessionStorePort

    def execute(self, session_id: str) -> Optional[EditSession]:
        """
        Ferme une session d'édition.

        Args:
            session_id: ID de la session.

        Returns:
            La session fermée, None si non trouvée.
        """
        session = self.session_store.get(session_id)
        if session is None:
            return None

        session.close()
        self.session_store.save(session)

        return session


@dataclass
class GetEditSessionUseCase:
    """
    Use case pour récupérer une session d'édition.

    Permet de consulter l'état d'une session existante.
    """

    session_store: EditSessionStorePort

    def execute(self, session_id: str) -> Optional[EditSession]:
        """
        Récupère une session par son ID.

        Args:
            session_id: ID de la session.

        Returns:
            La session si trouvée, None sinon.
        """
        return self.session_store.get(session_id)


@dataclass
class CleanupExpiredSessionsUseCase:
    """
    Use case pour nettoyer les sessions expirées.
    """

    session_store: EditSessionStorePort
    timeout_minutes: int = 30

    def execute(self) -> int:
        """
        Nettoie les sessions expirées.

        Returns:
            Nombre de sessions supprimées.
        """
        return self.session_store.cleanup_expired(self.timeout_minutes)
