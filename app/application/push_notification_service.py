# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service applicatif pour les notifications push.

Ce service orchestre l'envoi de notifications push en combinant
le DeviceStore (infrastructure) et le SendPushNotificationUseCase.
"""

import logging
from typing import List, Optional

from app.domain.ports import DeviceStorePort, NotificationPort, PushNotificationResult
from app.domain.entities import PushNotificationCategory
from app.application.send_push_notification import SendPushNotificationUseCase

logger = logging.getLogger(__name__)


class PushNotificationService:
    """
    Service de haut niveau pour les notifications push.

    Combine le stockage des devices et l'envoi de notifications
    pour fournir une API simple à utiliser par les autres parties
    de l'application.
    """

    def __init__(
        self,
        device_store: DeviceStorePort,
        notification_adapter: NotificationPort,
    ):
        """
        Initialise le service.

        Args:
            device_store: Adapter pour le stockage des device tokens.
            notification_adapter: Adapter pour l'envoi de notifications (FCM, Expo, etc.).
        """
        self._device_store = device_store
        self._use_case = SendPushNotificationUseCase(
            notification_adapter=notification_adapter
        )

    def _notify_all(
        self,
        notify_fn,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> int:
        """
        Helper générique pour notifier tous les devices.

        Args:
            notify_fn: Fonction du use case à appeler.
            user_id: Filtrer par utilisateur (optionnel).
            **kwargs: Arguments à passer à la fonction de notification.

        Returns:
            Nombre de notifications envoyées avec succès.
        """
        tokens = self._device_store.get_tokens(user_id)
        if not tokens:
            return 0

        results = notify_fn(device_tokens=tokens, **kwargs)
        self._update_last_used_for_successes(tokens, results)
        return sum(1 for r in results if r.success)

    def notify_all_draft_created(
        self,
        recipient: str,
        subject: str,
        draft_id: str,
        priority_score: int = 50,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Notifie tous les devices qu'un brouillon a été créé.

        Args:
            recipient: Destinataire de l'email.
            subject: Sujet de l'email.
            draft_id: ID du brouillon.
            priority_score: Score de priorité.
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Nombre de notifications envoyées avec succès.
        """
        return self._notify_all(
            self._use_case.notify_draft_created,
            user_id=user_id,
            recipient=recipient,
            subject=subject,
            draft_id=draft_id,
            priority_score=priority_score,
        )

    def notify_all_followup_sent(
        self,
        recipient: str,
        days_since: int,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Notifie tous les devices qu'une relance a été envoyée.

        Args:
            recipient: Destinataire de la relance.
            days_since: Jours depuis le dernier contact.
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Nombre de notifications envoyées avec succès.
        """
        return self._notify_all(
            self._use_case.notify_followup_sent,
            user_id=user_id,
            recipient=recipient,
            days_since=days_since,
        )

    def notify_all_error(
        self,
        error_message: str,
        context: Optional[dict] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Notifie tous les devices d'une erreur.

        Args:
            error_message: Message d'erreur.
            context: Contexte additionnel.
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Nombre de notifications envoyées avec succès.
        """
        return self._notify_all(
            self._use_case.notify_error,
            user_id=user_id,
            error_message=error_message,
            context=context,
        )

    def notify_all_budget_warning(
        self,
        current_spend: float,
        budget_limit: float,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Notifie tous les devices d'un avertissement de budget.

        Args:
            current_spend: Dépenses actuelles.
            budget_limit: Limite de budget.
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Nombre de notifications envoyées avec succès.
        """
        return self._notify_all(
            self._use_case.notify_budget_warning,
            user_id=user_id,
            current_spend=current_spend,
            budget_limit=budget_limit,
        )

    def send_to_token(
        self,
        token: str,
        title: str,
        body: str,
        category: PushNotificationCategory = PushNotificationCategory.INFO,
        data: Optional[dict] = None,
        priority: str = "normal",
    ) -> PushNotificationResult:
        """
        Envoie une notification à un token spécifique.

        Args:
            token: Token du device cible.
            title: Titre de la notification.
            body: Corps du message.
            category: Catégorie de la notification.
            data: Données additionnelles.
            priority: Priorité.

        Returns:
            Résultat de l'envoi.
        """
        result = self._use_case.execute(
            device_token=token,
            title=title,
            body=body,
            category=category,
            data=data,
            priority=priority,
        )

        if result.success:
            self._device_store.update_last_used(token)

        return result

    def send_to_tokens(
        self,
        tokens: List[str],
        title: str,
        body: str,
        category: PushNotificationCategory = PushNotificationCategory.INFO,
        data: Optional[dict] = None,
        priority: str = "normal",
    ) -> List[PushNotificationResult]:
        """
        Envoie une notification à plusieurs tokens.

        Args:
            tokens: Liste des tokens cibles.
            title: Titre de la notification.
            body: Corps du message.
            category: Catégorie de la notification.
            data: Données additionnelles.
            priority: Priorité.

        Returns:
            Liste des résultats.
        """
        results = self._use_case.execute_batch(
            device_tokens=tokens,
            title=title,
            body=body,
            category=category,
            data=data,
            priority=priority,
        )

        self._update_last_used_for_successes(tokens, results)
        return results

    def broadcast(
        self,
        title: str,
        body: str,
        category: PushNotificationCategory = PushNotificationCategory.INFO,
        data: Optional[dict] = None,
        priority: str = "normal",
        user_id: Optional[str] = None,
    ) -> List[PushNotificationResult]:
        """
        Envoie une notification à tous les devices enregistrés.

        Args:
            title: Titre de la notification.
            body: Corps du message.
            category: Catégorie de la notification.
            data: Données additionnelles.
            priority: Priorité.
            user_id: Filtrer par utilisateur (optionnel).

        Returns:
            Liste des résultats.
        """
        tokens = self._device_store.get_tokens(user_id)
        if not tokens:
            return []

        return self.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            category=category,
            data=data,
            priority=priority,
        )

    def get_stats(self) -> dict:
        """Retourne les statistiques des notifications."""
        return self._use_case.get_stats()

    def get_records(self, limit: int = 100) -> list:
        """Retourne l'historique des notifications."""
        return self._use_case.get_records(limit=limit)

    def _update_last_used_for_successes(
        self,
        tokens: List[str],
        results: List[PushNotificationResult],
    ) -> None:
        """Met à jour last_used pour les envois réussis."""
        for token, result in zip(tokens, results):
            if result.success:
                self._device_store.update_last_used(token)


# NOTE: Factory functions supprimées pour respecter la Clean Architecture.
# Les factories sont maintenant dans app/infrastructure/container.py
# Utiliser: get_container().get_push_notification_service()
