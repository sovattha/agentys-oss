# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter Discord pour la messagerie.

Ce module fournit une implémentation de MessageProvider pour Discord
en utilisant discord.py.
"""

import os
import logging
import asyncio
from typing import List, Optional, Callable
from threading import Thread

from app.interfaces.message_provider import (
    MessageProvider,
    StandardMessage,
    ChannelType,
)

logger = logging.getLogger(__name__)

try:
    import discord
    from discord import Intents
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("discord.py non installé. Installer avec: pip install discord.py")


class DiscordAdapter(MessageProvider):
    """
    Adapter pour Discord utilisant discord.py.

    Permet de recevoir et envoyer des messages Discord via un bot.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        intents: Optional["Intents"] = None
    ):
        """
        Initialise le DiscordAdapter.

        Args:
            bot_token: Token du bot Discord. Si None, utilise DISCORD_BOT_TOKEN.
            intents: Intents Discord personnalisés. Si None, utilise les defaults.

        Raises:
            ValueError: Si le token n'est pas fourni.
        """
        self._bot_token = bot_token or os.getenv("DISCORD_BOT_TOKEN", "")

        if not self._bot_token:
            raise ValueError(
                "Token Discord requis. Définir DISCORD_BOT_TOKEN ou passer bot_token."
            )

        self._client: Optional["discord.Client"] = None
        self._connected = False
        self._message_handlers: List[Callable[[StandardMessage], None]] = []
        self._intents = intents
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None

    @property
    def provider_name(self) -> str:
        return "discord"

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.DISCORD

    def connect(self) -> bool:
        """
        Établit la connexion au bot Discord (synchrone).

        Lance le client dans un thread séparé.

        Returns:
            True si le démarrage réussit, False sinon.
        """
        if not DISCORD_AVAILABLE:
            logger.error("discord.py non disponible")
            return False

        if self._connected:
            return True

        try:
            self._loop = asyncio.new_event_loop()
            self._thread = Thread(target=self._run_client, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            logger.error(f"Erreur connexion Discord: {e}")
            return False

    async def connect_async(self) -> bool:
        """
        Établit la connexion au bot Discord (asynchrone).

        Returns:
            True si la connexion réussit, False sinon.
        """
        if not DISCORD_AVAILABLE:
            logger.error("discord.py non disponible")
            return False

        if self._connected:
            return True

        try:
            return await self._start_client()
        except Exception as e:
            logger.error(f"Erreur connexion Discord: {e}")
            return False

    def _run_client(self) -> None:
        """Exécute le client Discord dans la boucle d'événements."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_client())

    async def _start_client(self) -> bool:
        """Démarre le client Discord."""
        if not DISCORD_AVAILABLE:
            return False

        intents = self._intents or Intents.default()
        intents.message_content = True
        intents.guilds = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            self._connected = True
            logger.info(f"Bot Discord connecté: {self._client.user}")

        @self._client.event
        async def on_message(message: "discord.Message"):
            if message.author == self._client.user:
                return

            std_msg = self._to_standard_message(message)
            for handler in self._message_handlers:
                try:
                    handler(std_msg)
                except Exception as e:
                    logger.error(f"Erreur handler message: {e}")

        try:
            await self._client.start(self._bot_token)
            return True
        except Exception as e:
            logger.error(f"Erreur démarrage Discord: {e}")
            return False

    def disconnect(self) -> bool:
        """
        Ferme la connexion au bot Discord.

        Returns:
            True si la déconnexion réussit, False sinon.
        """
        if not self._connected or not self._client:
            return True

        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._client.close(),
                    self._loop
                )
            self._connected = False
            logger.info("Bot Discord déconnecté")
            return True
        except Exception as e:
            logger.error(f"Erreur déconnexion Discord: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def _to_standard_message(
        self,
        message: "discord.Message",
        is_dm: bool = False
    ) -> StandardMessage:
        """
        Convertit un message Discord en StandardMessage.

        Args:
            message: Message Discord natif.
            is_dm: True si c'est un message privé.

        Returns:
            StandardMessage normalisé.
        """
        reply_to_id = None
        if message.reference and message.reference.message_id:
            reply_to_id = str(message.reference.message_id)

        attachments = [att.url for att in message.attachments]

        channel_name = getattr(message.channel, 'name', None)
        if not channel_name and hasattr(message.channel, 'recipient'):
            channel_name = f"DM-{message.channel.recipient.name}"

        is_dm_channel = False
        if hasattr(message.channel, 'type'):
            is_dm_channel = message.channel.type.name == "private"

        return StandardMessage(
            id=str(message.id),
            channel_id=str(message.channel.id),
            channel_name=channel_name,
            author_id=str(message.author.id),
            author_name=message.author.name,
            author_display_name=message.author.display_name,
            content=message.content,
            created_at=message.created_at,
            is_bot=message.author.bot,
            is_mention=self._client and self._client.user in message.mentions if hasattr(message, 'mentions') else False,
            is_dm=is_dm or is_dm_channel,
            reply_to_id=reply_to_id,
            attachments=attachments,
            provider_source=ChannelType.DISCORD,
            raw_metadata={
                "guild_id": str(message.guild.id) if message.guild else None,
                "guild_name": message.guild.name if message.guild else None,
            }
        )

    def get_recent_messages(
        self,
        channel_id: str,
        limit: int = 10
    ) -> List[StandardMessage]:
        """
        Récupère les messages récents d'un canal.

        Args:
            channel_id: ID du canal Discord.
            limit: Nombre maximum de messages.

        Returns:
            Liste de StandardMessage.
        """
        if not self._connected or not self._client:
            return []

        try:
            channel = self._client.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Canal Discord non trouvé: {channel_id}")
                return []

            messages = []
            if self._loop:
                future = asyncio.run_coroutine_threadsafe(
                    channel.history(limit=limit).flatten(),
                    self._loop
                )
                discord_messages = future.result(timeout=10)
                messages = [self._to_standard_message(m) for m in discord_messages]

            return messages
        except Exception as e:
            logger.error(f"Erreur récupération messages Discord: {e}")
            return []

    def get_unread_mentions(self, limit: int = 10) -> List[StandardMessage]:
        """
        Récupère les mentions non lues du bot.

        Note: Discord ne gère pas les "non lus" de la même façon.
        Cette méthode est un placeholder pour compatibilité.

        Returns:
            Liste vide (à implémenter selon les besoins).
        """
        if not self._connected:
            return []
        return []

    def send_message(
        self,
        channel_id: str,
        content: str,
        reply_to_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Envoie un message dans un canal Discord.

        Args:
            channel_id: ID du canal.
            content: Contenu du message.
            reply_to_id: ID du message auquel répondre.

        Returns:
            ID du message envoyé ou None.
        """
        if not self._connected or not self._client:
            return None

        try:
            channel = self._client.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Canal non trouvé: {channel_id}")
                return None

            async def _send():
                reference = None
                if reply_to_id:
                    try:
                        ref_msg = await channel.fetch_message(int(reply_to_id))
                        reference = ref_msg.to_reference()
                    except Exception:
                        pass
                msg = await channel.send(content, reference=reference)
                return str(msg.id)

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_send(), self._loop)
                return future.result(timeout=10)
            return None
        except Exception as e:
            logger.error(f"Erreur envoi message Discord: {e}")
            return None

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str
    ) -> bool:
        """
        Modifie un message Discord.

        Args:
            channel_id: ID du canal.
            message_id: ID du message.
            content: Nouveau contenu.

        Returns:
            True si succès, False sinon.
        """
        if not self._connected or not self._client:
            return False

        try:
            channel = self._client.get_channel(int(channel_id))
            if not channel:
                return False

            async def _edit():
                message = await channel.fetch_message(int(message_id))
                await message.edit(content=content)
                return True

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_edit(), self._loop)
                return future.result(timeout=10)
            return False
        except Exception as e:
            logger.error(f"Erreur édition message Discord: {e}")
            return False

    def delete_message(
        self,
        channel_id: str,
        message_id: str
    ) -> bool:
        """
        Supprime un message Discord.

        Args:
            channel_id: ID du canal.
            message_id: ID du message.

        Returns:
            True si succès, False sinon.
        """
        if not self._connected or not self._client:
            return False

        try:
            channel = self._client.get_channel(int(channel_id))
            if not channel:
                return False

            async def _delete():
                message = await channel.fetch_message(int(message_id))
                await message.delete()
                return True

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_delete(), self._loop)
                return future.result(timeout=10)
            return False
        except Exception as e:
            logger.error(f"Erreur suppression message Discord: {e}")
            return False

    def get_channels(self) -> List[dict]:
        """
        Récupère la liste des canaux accessibles.

        Returns:
            Liste de dictionnaires {id, name, type, guild}.
        """
        if not self._connected or not self._client:
            return []

        try:
            channels = []
            for guild in self._client.guilds:
                for channel in guild.text_channels:
                    channels.append({
                        "id": str(channel.id),
                        "name": channel.name,
                        "type": "text",
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                    })
            return channels
        except Exception as e:
            logger.error(f"Erreur récupération canaux Discord: {e}")
            return []

    def register_message_handler(
        self,
        handler: Callable[[StandardMessage], None]
    ) -> None:
        """
        Enregistre un callback pour les nouveaux messages.

        Args:
            handler: Fonction appelée à chaque nouveau message.
        """
        self._message_handlers.append(handler)

    def start_listening(self) -> bool:
        """
        Démarre l'écoute des messages (équivalent à connect).

        Returns:
            True si succès.
        """
        return self.connect()

    def stop_listening(self) -> bool:
        """
        Arrête l'écoute des messages (équivalent à disconnect).

        Returns:
            True si succès.
        """
        return self.disconnect()


# ============================================================================
# SINGLETON
# ============================================================================

_discord_adapter: Optional["DiscordAdapter"] = None


def get_discord_adapter() -> Optional["DiscordAdapter"]:
    """
    Retourne l'instance singleton du DiscordAdapter.

    Returns:
        Instance du DiscordAdapter ou None si non configuré.
    """
    global _discord_adapter
    if _discord_adapter is None:
        try:
            _discord_adapter = DiscordAdapter()
        except ValueError:
            logger.warning("Discord adapter non configuré (token manquant)")
            return None
    return _discord_adapter


def reset_discord_adapter() -> None:
    """Réinitialise le singleton (pour les tests)."""
    global _discord_adapter
    if _discord_adapter:
        _discord_adapter.disconnect()
    _discord_adapter = None
