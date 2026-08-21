"""
Port pour la gestion des canaux de communication.

Interface abstraite definissant les operations CRUD et les mises a jour
des canaux de communication.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.communication_channel import (
    CommunicationChannel,
    ChannelType,
    ChannelStatus,
    ChannelMetrics,
)


class CommunicationChannelPort(ABC):
    """
    Interface abstraite pour la persistance des canaux de communication.

    Responsabilites:
    - Persister les canaux de communication
    - Recuperer les canaux par ID ou par type
    - Mettre a jour les metriques et statuts
    - Supprimer les canaux
    """

    # =========================================================================
    # Operations CRUD
    # =========================================================================

    @abstractmethod
    def save(self, channel: CommunicationChannel) -> CommunicationChannel:
        """
        Cree ou met a jour un canal.

        Args:
            channel: Canal a persister.

        Returns:
            Le canal persiste.
        """
        pass

    @abstractmethod
    def get_by_id(self, channel_id: str) -> Optional[CommunicationChannel]:
        """
        Recupere un canal par son ID.

        Args:
            channel_id: ID du canal.

        Returns:
            Le canal ou None si non trouve.
        """
        pass

    @abstractmethod
    def get_by_type(self, channel_type: ChannelType) -> List[CommunicationChannel]:
        """
        Recupere tous les canaux d'un type donne.

        Args:
            channel_type: Type de canal recherche.

        Returns:
            Liste des canaux correspondants.
        """
        pass

    @abstractmethod
    def get_all(self) -> List[CommunicationChannel]:
        """
        Recupere tous les canaux.

        Returns:
            Liste de tous les canaux.
        """
        pass

    @abstractmethod
    def delete(self, channel_id: str) -> bool:
        """
        Supprime un canal.

        Args:
            channel_id: ID du canal a supprimer.

        Returns:
            True si la suppression a reussi.
        """
        pass

    # =========================================================================
    # Operations de mise a jour
    # =========================================================================

    @abstractmethod
    def update_metrics(self, channel_id: str, metrics: ChannelMetrics) -> bool:
        """
        Met a jour les metriques d'un canal.

        Args:
            channel_id: ID du canal.
            metrics: Nouvelles metriques.

        Returns:
            True si la mise a jour a reussi.
        """
        pass

    @abstractmethod
    def update_status(self, channel_id: str, status: ChannelStatus) -> bool:
        """
        Met a jour le statut d'un canal.

        Args:
            channel_id: ID du canal.
            status: Nouveau statut.

        Returns:
            True si la mise a jour a reussi.
        """
        pass
