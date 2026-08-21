# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Interface abstraite pour les fournisseurs de messaging (Discord, Telegram, Slack).

Cette abstraction permet de découpler le code métier des implémentations
spécifiques. Les agents ne voient que des StandardMessage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Callable


class ChannelType(str, Enum):
    """Type de canal de communication."""
    DISCORD = "discord"
    TELEGRAM = "telegram"
    SLACK = "slack"


@dataclass
class StandardMessage:
    """
    Représentation normalisée d'un message.

    Peu importe le fournisseur source (Discord, Telegram, Slack),
    tous les messages sont convertis vers ce format standard.
    """
    id: str
    channel_id: str
    channel_name: Optional[str] = None
    author_id: str = ""
    author_name: str = ""
    author_display_name: Optional[str] = None
    content: str = ""
    created_at: Optional[datetime] = None
    is_bot: bool = False
    is_mention: bool = False
    is_dm: bool = False
    reply_to_id: Optional[str] = None
    attachments: List[str] = field(default_factory=list)
    provider_source: ChannelType = ChannelType.DISCORD

    raw_metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.provider_source.value}] {self.author_display_name or self.author_name}: {self.content[:50]}..."

    @property
    def author_display(self) -> str:
        return self.author_display_name or self.author_name

    @property
    def preview(self) -> str:
        if not self.content:
            return ""
        return self.content[:100] + "..." if len(self.content) > 100 else self.content


class MessageProvider(ABC):
    """
    Interface abstraite pour les fournisseurs de messaging.

    Toutes les implémentations concrètes (DiscordAdapter, TelegramAdapter, etc.)
    doivent hériter de cette classe et implémenter ses méthodes abstraites.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retourne le nom du fournisseur (ex: 'discord', 'telegram')."""
        pass

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Retourne le type de canal."""
        pass

    @abstractmethod
    def connect(self) -> bool:
        """
        Établit la connexion au service.

        Returns:
            True si la connexion réussit, False sinon.
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        Ferme la connexion au service.

        Returns:
            True si la déconnexion réussit, False sinon.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Vérifie si la connexion est active.

        Returns:
            True si connecté, False sinon.
        """
        pass

    @abstractmethod
    def get_recent_messages(
        self,
        channel_id: str,
        limit: int = 10
    ) -> List[StandardMessage]:
        """
        Récupère les messages récents d'un canal.

        Args:
            channel_id: Identifiant du canal.
            limit: Nombre maximum de messages à récupérer.

        Returns:
            Liste de messages normalisés (StandardMessage).
        """
        pass

    @abstractmethod
    def get_unread_mentions(self, limit: int = 10) -> List[StandardMessage]:
        """
        Récupère les mentions non lues.

        Args:
            limit: Nombre maximum de messages à récupérer.

        Returns:
            Liste de messages où le bot est mentionné.
        """
        pass

    @abstractmethod
    def send_message(
        self,
        channel_id: str,
        content: str,
        reply_to_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Envoie un message dans un canal.

        Args:
            channel_id: Identifiant du canal.
            content: Contenu du message.
            reply_to_id: ID du message auquel répondre (optionnel).

        Returns:
            L'ID du message envoyé, ou None en cas d'échec.
        """
        pass

    @abstractmethod
    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str
    ) -> bool:
        """
        Modifie un message existant.

        Args:
            channel_id: Identifiant du canal.
            message_id: Identifiant du message.
            content: Nouveau contenu.

        Returns:
            True si la modification réussit, False sinon.
        """
        pass

    @abstractmethod
    def delete_message(
        self,
        channel_id: str,
        message_id: str
    ) -> bool:
        """
        Supprime un message.

        Args:
            channel_id: Identifiant du canal.
            message_id: Identifiant du message.

        Returns:
            True si la suppression réussit, False sinon.
        """
        pass

    @abstractmethod
    def get_channels(self) -> List[dict]:
        """
        Récupère la liste des canaux accessibles.

        Returns:
            Liste de dictionnaires avec id, name, type.
        """
        pass

    def register_message_handler(
        self,
        handler: Callable[[StandardMessage], None]
    ) -> None:
        """
        Enregistre un callback pour les nouveaux messages.

        Args:
            handler: Fonction appelée à chaque nouveau message.
        """
        pass

    def start_listening(self) -> bool:
        """
        Démarre l'écoute des nouveaux messages (mode event-driven).

        Returns:
            True si le démarrage réussit, False sinon.
        """
        return False

    def stop_listening(self) -> bool:
        """
        Arrête l'écoute des nouveaux messages.

        Returns:
            True si l'arrêt réussit, False sinon.
        """
        return False
