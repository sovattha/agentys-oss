# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Envoyer des notifications push mobiles.

Ce use case orchestre l'envoi de notifications push vers les appareils
mobiles des utilisateurs en utilisant un adapter de notification.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from app.domain.entities import (
    PushNotification,
    PushNotificationCategory,
    PushNotificationStatus,
    PushNotificationRecord,
)
from app.domain.ports import NotificationPort, NotificationPriority, PushNotificationResult

logger = logging.getLogger(__name__)


@dataclass
class SendPushNotificationUseCase:
    """
    Envoie des notifications push aux appareils mobiles.

    Ce use case :
    - Envoie des notifications via l'adapter configuré (FCM, Expo, etc.)
    - Supporte l'envoi individuel et en batch
    - Maintient un historique des notifications envoyées
    - Gère les tokens invalides
    """
    notification_adapter: NotificationPort
    records: List[PushNotificationRecord] = field(default_factory=list)

    def execute(
        self,
        device_token: str,
        title: str,
        body: str,
        category: PushNotificationCategory = PushNotificationCategory.INFO,
        data: Optional[dict] = None,
        priority: str = "normal",
    ) -> PushNotificationResult:
        """
        Envoie une notification push à un device.

        Args:
            device_token: Token du device cible.
            title: Titre de la notification.
            body: Corps du message.
            category: Catégorie de la notification.
            data: Données additionnelles (payload).
            priority: Priorité (low, normal, high).

        Returns:
            Résultat de l'envoi.
        """
        # Créer l'entité notification
        notification = PushNotification(
            title=title,
            body=body,
            category=category,
            data=data,
            priority=priority,
        )

        # Mapper la priorité
        notification_priority = self._map_priority(priority)

        # Envoyer via l'adapter
        result = self.notification_adapter.send(
            device_token=device_token,
            title=title,
            body=body,
            data=self._prepare_data(notification, data),
            priority=notification_priority,
        )

        # Enregistrer l'envoi
        status = PushNotificationStatus.SENT if result.success else PushNotificationStatus.FAILED
        record = PushNotificationRecord(
            notification=notification,
            device_token=device_token,
            status=status,
            message_id=result.message_id,
            error_message=result.error_message,
        )
        self.records.append(record)

        if result.success:
            logger.info(f"Push notification sent to {device_token[:20]}...: {title}")
        else:
            logger.warning(f"Push notification failed: {result.error_message}")

        return result

    def execute_batch(
        self,
        device_tokens: List[str],
        title: str,
        body: str,
        category: PushNotificationCategory = PushNotificationCategory.INFO,
        data: Optional[dict] = None,
        priority: str = "normal",
    ) -> List[PushNotificationResult]:
        """
        Envoie une notification à plusieurs devices.

        Args:
            device_tokens: Liste des tokens des devices cibles.
            title: Titre de la notification.
            body: Corps du message.
            category: Catégorie de la notification.
            data: Données additionnelles.
            priority: Priorité.

        Returns:
            Liste des résultats (un par device).
        """
        if not device_tokens:
            return []

        # Créer l'entité notification
        notification = PushNotification(
            title=title,
            body=body,
            category=category,
            data=data,
            priority=priority,
        )

        # Mapper la priorité
        notification_priority = self._map_priority(priority)

        # Envoyer en batch via l'adapter
        results = self.notification_adapter.send_batch(
            device_tokens=device_tokens,
            title=title,
            body=body,
            data=self._prepare_data(notification, data),
            priority=notification_priority,
        )

        # Enregistrer chaque envoi
        for i, (token, result) in enumerate(zip(device_tokens, results)):
            status = PushNotificationStatus.SENT if result.success else PushNotificationStatus.FAILED
            record = PushNotificationRecord(
                notification=notification,
                device_token=token,
                status=status,
                message_id=result.message_id,
                error_message=result.error_message,
            )
            self.records.append(record)

        success_count = sum(1 for r in results if r.success)
        logger.info(f"Batch push: {success_count}/{len(results)} sent successfully")

        return results

    def notify_draft_created(
        self,
        device_tokens: List[str],
        recipient: str,
        subject: str,
        draft_id: str,
        priority_score: int = 50,
    ) -> List[PushNotificationResult]:
        """
        Notifie qu'un brouillon a été créé.

        Args:
            device_tokens: Liste des tokens.
            recipient: Destinataire de l'email.
            subject: Sujet de l'email.
            draft_id: ID du brouillon créé.
            priority_score: Score de priorité (0-100).

        Returns:
            Liste des résultats.
        """
        priority = "high" if priority_score >= 80 else "normal"

        return self.execute_batch(
            device_tokens=device_tokens,
            title="Brouillon cr\u00e9\u00e9",
            body=f"R\u00e9ponse \u00e0 {recipient}: {subject[:50]}",
            category=PushNotificationCategory.DRAFT_CREATED,
            data={
                "type": "draft_created",
                "draft_id": draft_id,
                "recipient": recipient,
                "subject": subject,
                "priority_score": priority_score,
            },
            priority=priority,
        )

    def notify_followup_sent(
        self,
        device_tokens: List[str],
        recipient: str,
        days_since: int,
    ) -> List[PushNotificationResult]:
        """
        Notifie qu'une relance a été envoyée.

        Args:
            device_tokens: Liste des tokens.
            recipient: Destinataire de la relance.
            days_since: Nombre de jours depuis le dernier contact.

        Returns:
            Liste des résultats.
        """
        return self.execute_batch(
            device_tokens=device_tokens,
            title="Relance envoy\u00e9e",
            body=f"Relance \u00e0 {recipient} ({days_since}j sans r\u00e9ponse)",
            category=PushNotificationCategory.FOLLOWUP_SENT,
            data={
                "type": "followup_sent",
                "recipient": recipient,
                "days_since": days_since,
            },
            priority="normal",
        )

    def notify_error(
        self,
        device_tokens: List[str],
        error_message: str,
        context: Optional[dict] = None,
    ) -> List[PushNotificationResult]:
        """
        Notifie une erreur.

        Args:
            device_tokens: Liste des tokens.
            error_message: Message d'erreur.
            context: Contexte additionnel.

        Returns:
            Liste des résultats.
        """
        return self.execute_batch(
            device_tokens=device_tokens,
            title="Erreur Agentys",
            body=error_message[:100],
            category=PushNotificationCategory.ERROR,
            data={
                "type": "error",
                "message": error_message,
                **(context or {}),
            },
            priority="high",
        )

    def notify_budget_warning(
        self,
        device_tokens: List[str],
        current_spend: float,
        budget_limit: float,
    ) -> List[PushNotificationResult]:
        """
        Notifie un avertissement de budget.

        Args:
            device_tokens: Liste des tokens.
            current_spend: Dépenses actuelles.
            budget_limit: Limite de budget.

        Returns:
            Liste des résultats.
        """
        percent = (current_spend / budget_limit * 100) if budget_limit > 0 else 0

        return self.execute_batch(
            device_tokens=device_tokens,
            title="Alerte budget",
            body=f"{percent:.0f}% du budget utilis\u00e9 (${current_spend:.2f}/${budget_limit:.2f})",
            category=PushNotificationCategory.BUDGET_WARNING,
            data={
                "type": "budget_warning",
                "current_spend": current_spend,
                "budget_limit": budget_limit,
                "percent_used": percent,
            },
            priority="normal",
        )

    def get_records(self, limit: int = 100) -> List[PushNotificationRecord]:
        """
        Récupère les derniers enregistrements de notifications.

        Args:
            limit: Nombre maximum d'enregistrements.

        Returns:
            Liste des enregistrements les plus récents.
        """
        return sorted(
            self.records,
            key=lambda r: r.sent_at,
            reverse=True
        )[:limit]

    def get_stats(self) -> dict:
        """
        Retourne des statistiques sur les notifications envoyées.

        Returns:
            Dictionnaire de statistiques.
        """
        total = len(self.records)
        sent = sum(1 for r in self.records if r.status == PushNotificationStatus.SENT)
        failed = sum(1 for r in self.records if r.status == PushNotificationStatus.FAILED)

        by_category = {}
        for record in self.records:
            cat = record.notification.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "success_rate": (sent / total * 100) if total > 0 else 0,
            "by_category": by_category,
        }

    def _map_priority(self, priority: str) -> NotificationPriority:
        """Mappe une priorité string vers NotificationPriority."""
        mapping = {
            "low": NotificationPriority.LOW,
            "normal": NotificationPriority.NORMAL,
            "high": NotificationPriority.HIGH,
        }
        return mapping.get(priority, NotificationPriority.NORMAL)

    def _prepare_data(self, notification: PushNotification, extra_data: Optional[dict]) -> dict:
        """Prépare les données à envoyer avec la notification."""
        data = {
            "category": notification.category.value,
            "timestamp": datetime.now().isoformat(),
        }
        if extra_data:
            data.update(extra_data)
        return data
