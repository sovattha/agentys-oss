# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter Telegram pour la messagerie.

Ce module fournit une implémentation de MessageProvider pour Telegram
en utilisant python-telegram-bot.
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
    from telegram import Update, Bot
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot non installé. Installer avec: pip install python-telegram-bot")


class TelegramAdapter(MessageProvider):
    """
    Adapter pour Telegram utilisant python-telegram-bot.

    Permet de recevoir et envoyer des messages Telegram via un bot.
    """

    def __init__(self, bot_token: Optional[str] = None):
        """
        Initialise le TelegramAdapter.

        Args:
            bot_token: Token du bot Telegram. Si None, utilise TELEGRAM_BOT_TOKEN.

        Raises:
            ValueError: Si le token n'est pas fourni.
        """
        self._bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")

        if not self._bot_token:
            raise ValueError(
                "Token Telegram requis. Définir TELEGRAM_BOT_TOKEN ou passer bot_token."
            )

        self._bot: Optional["Bot"] = None
        self._application: Optional["Application"] = None
        self._connected = False
        self._message_handlers: List[Callable[[StandardMessage], None]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._known_chats: List[dict] = []

    @property
    def provider_name(self) -> str:
        return "telegram"

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.TELEGRAM

    def connect(self) -> bool:
        """
        Établit la connexion au bot Telegram (synchrone).

        Lance le client dans un thread séparé.

        Returns:
            True si le démarrage réussit, False sinon.
        """
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot non disponible")
            return False

        if self._connected:
            return True

        try:
            self._loop = asyncio.new_event_loop()
            self._thread = Thread(target=self._run_client, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            logger.error(f"Erreur connexion Telegram: {e}")
            return False

    async def connect_async(self) -> bool:
        """
        Établit la connexion au bot Telegram (asynchrone).

        Returns:
            True si la connexion réussit, False sinon.
        """
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot non disponible")
            return False

        if self._connected:
            return True

        try:
            return await self._start_client()
        except Exception as e:
            logger.error(f"Erreur connexion Telegram: {e}")
            return False

    def _run_client(self) -> None:
        """Exécute le client Telegram dans la boucle d'événements."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_client())

    async def _start_client(self) -> bool:
        """Démarre le client Telegram."""
        if not TELEGRAM_AVAILABLE:
            return False

        try:
            self._application = Application.builder().token(self._bot_token).build()
            self._bot = self._application.bot

            async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not update.message or not update.message.from_user:
                    return

                bot_info = await self._bot.get_me()
                if update.message.from_user.id == bot_info.id:
                    return

                std_msg = self._to_standard_message(update.message)

                chat_info = {
                    "id": str(update.message.chat.id),
                    "name": update.message.chat.title or update.message.chat.username or "Private",
                    "type": update.message.chat.type,
                }
                if chat_info not in self._known_chats:
                    self._known_chats.append(chat_info)

                for handler in self._message_handlers:
                    try:
                        handler(std_msg)
                    except Exception as e:
                        logger.error(f"Erreur handler message: {e}")

            self._application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
            )

            self._connected = True
            bot_info = await self._bot.get_me()
            logger.info(f"Bot Telegram connecté: @{bot_info.username}")

            await self._application.initialize()
            await self._application.start()
            await self._application.updater.start_polling()

            return True
        except Exception as e:
            logger.error(f"Erreur démarrage Telegram: {e}")
            return False

    def disconnect(self) -> bool:
        """
        Ferme la connexion au bot Telegram.

        Returns:
            True si la déconnexion réussit, False sinon.
        """
        if not self._connected or not self._application:
            return True

        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._stop_application(),
                    self._loop
                )
            self._connected = False
            logger.info("Bot Telegram déconnecté")
            return True
        except Exception as e:
            logger.error(f"Erreur déconnexion Telegram: {e}")
            return False

    async def _stop_application(self) -> None:
        """Arrête proprement l'application Telegram."""
        if self._application:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()

    def is_connected(self) -> bool:
        return self._connected

    def _to_standard_message(self, message) -> StandardMessage:
        """
        Convertit un message Telegram en StandardMessage.

        Args:
            message: Message Telegram natif.

        Returns:
            StandardMessage normalisé.
        """
        reply_to_id = None
        if message.reply_to_message:
            reply_to_id = str(message.reply_to_message.message_id)

        attachments = []
        if message.document:
            attachments.append(message.document.file_id)
        if message.photo:
            attachments.append(message.photo[-1].file_id if message.photo else None)

        is_dm = message.chat.type == "private"

        display_name = None
        if message.from_user.first_name:
            display_name = message.from_user.first_name
            if message.from_user.last_name:
                display_name += f" {message.from_user.last_name}"

        channel_name = message.chat.title
        if not channel_name and is_dm:
            channel_name = f"DM-{message.from_user.username or message.from_user.id}"

        return StandardMessage(
            id=str(message.message_id),
            channel_id=str(message.chat.id),
            channel_name=channel_name,
            author_id=str(message.from_user.id),
            author_name=message.from_user.username or str(message.from_user.id),
            author_display_name=display_name,
            content=message.text or "",
            created_at=message.date,
            is_bot=message.from_user.is_bot,
            is_mention=False,
            is_dm=is_dm,
            reply_to_id=reply_to_id,
            attachments=[a for a in attachments if a],
            provider_source=ChannelType.TELEGRAM,
            raw_metadata={
                "chat_type": message.chat.type,
            }
        )

    def get_recent_messages(
        self,
        channel_id: str,
        limit: int = 10
    ) -> List[StandardMessage]:
        """
        Récupère les messages récents d'un chat.

        Note: Telegram ne permet pas de récupérer l'historique des messages
        via l'API Bot. Cette méthode retourne une liste vide.

        Args:
            channel_id: ID du chat Telegram.
            limit: Nombre maximum de messages.

        Returns:
            Liste vide (limitation API Telegram Bot).
        """
        if not self._connected or not self._bot:
            return []
        return []

    def get_unread_mentions(self, limit: int = 10) -> List[StandardMessage]:
        """
        Récupère les mentions non lues du bot.

        Note: Telegram ne gère pas les "non lus" de cette façon.

        Returns:
            Liste vide.
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
        Envoie un message dans un chat Telegram.

        Args:
            channel_id: ID du chat.
            content: Contenu du message.
            reply_to_id: ID du message auquel répondre.

        Returns:
            ID du message envoyé ou None.
        """
        if not self._connected or not self._bot:
            return None

        try:
            async def _send():
                reply_to = int(reply_to_id) if reply_to_id else None
                msg = await self._bot.send_message(
                    chat_id=int(channel_id),
                    text=content,
                    reply_to_message_id=reply_to
                )
                return str(msg.message_id)

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_send(), self._loop)
                return future.result(timeout=10)
            return None
        except Exception as e:
            logger.error(f"Erreur envoi message Telegram: {e}")
            return None

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str
    ) -> bool:
        """
        Modifie un message Telegram.

        Args:
            channel_id: ID du chat.
            message_id: ID du message.
            content: Nouveau contenu.

        Returns:
            True si succès, False sinon.
        """
        if not self._connected or not self._bot:
            return False

        try:
            async def _edit():
                await self._bot.edit_message_text(
                    chat_id=int(channel_id),
                    message_id=int(message_id),
                    text=content
                )
                return True

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_edit(), self._loop)
                return future.result(timeout=10)
            return False
        except Exception as e:
            logger.error(f"Erreur édition message Telegram: {e}")
            return False

    def delete_message(
        self,
        channel_id: str,
        message_id: str
    ) -> bool:
        """
        Supprime un message Telegram.

        Args:
            channel_id: ID du chat.
            message_id: ID du message.

        Returns:
            True si succès, False sinon.
        """
        if not self._connected or not self._bot:
            return False

        try:
            async def _delete():
                await self._bot.delete_message(
                    chat_id=int(channel_id),
                    message_id=int(message_id)
                )
                return True

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(_delete(), self._loop)
                return future.result(timeout=10)
            return False
        except Exception as e:
            logger.error(f"Erreur suppression message Telegram: {e}")
            return False

    def get_channels(self) -> List[dict]:
        """
        Récupère la liste des chats connus.

        Note: Telegram ne permet pas de lister tous les chats.
        Cette méthode retourne les chats avec lesquels le bot a interagi.

        Returns:
            Liste de dictionnaires {id, name, type}.
        """
        if not self._connected or not self._bot:
            return []

        return self._known_chats.copy()

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

_telegram_adapter: Optional["TelegramAdapter"] = None


def get_telegram_adapter() -> Optional["TelegramAdapter"]:
    """
    Retourne l'instance singleton du TelegramAdapter.

    Returns:
        Instance du TelegramAdapter ou None si non configuré.
    """
    global _telegram_adapter
    if _telegram_adapter is None:
        try:
            _telegram_adapter = TelegramAdapter()
        except ValueError:
            logger.warning("Telegram adapter non configuré (token manquant)")
            return None
    return _telegram_adapter


def reset_telegram_adapter() -> None:
    """Réinitialise le singleton (pour les tests)."""
    global _telegram_adapter
    if _telegram_adapter:
        _telegram_adapter.disconnect()
    _telegram_adapter = None
