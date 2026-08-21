# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Intégration Discord pour Agentys.

Permet d'envoyer des notifications et de répondre aux demandes de support
via un bot Discord. Supporte les webhooks et l'API Discord Bot.

Usage:
    from app.discord_integration import DiscordBot, get_discord_bot

    bot = get_discord_bot()

    # Envoyer une notification
    bot.send_notification("Un nouveau brouillon a été créé")

    # Répondre à un message de support
    bot.handle_support_message(message, channel_id)
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum
import urllib.request
import urllib.error

from app.config import DATA_DIR


# ============================================================================
# CONFIGURATION
# ============================================================================

DISCORD_DATA_DIR = DATA_DIR / "discord"
try:
    DISCORD_DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


class MessageType(Enum):
    """Types de messages Discord."""
    NOTIFICATION = "notification"
    SUPPORT_REQUEST = "support_request"
    SUPPORT_RESPONSE = "support_response"
    ALERT = "alert"
    STATUS = "status"


class EmbedColor(Enum):
    """Couleurs pour les embeds Discord."""
    SUCCESS = 0x00FF00  # Vert
    ERROR = 0xFF0000    # Rouge
    WARNING = 0xFFFF00  # Jaune
    INFO = 0x00BFFF     # Bleu clair
    DEFAULT = 0x7289DA  # Bleu Discord


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class DiscordConfig:
    """Configuration du bot Discord."""
    webhook_url: Optional[str] = None
    bot_token: Optional[str] = None
    guild_id: Optional[str] = None
    support_channel_id: Optional[str] = None
    notifications_channel_id: Optional[str] = None
    enabled: bool = True
    mention_role_id: Optional[str] = None
    language: str = "fr"


@dataclass
class DiscordMessage:
    """Représente un message Discord."""
    id: str
    channel_id: str
    author_id: str
    author_name: str
    content: str
    message_type: str = "notification"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    responded: bool = False
    response_content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscordEmbed:
    """Représente un embed Discord."""
    title: Optional[str] = None
    description: Optional[str] = None
    color: int = EmbedColor.DEFAULT.value
    fields: List[Dict[str, Any]] = field(default_factory=list)
    footer: Optional[Dict[str, str]] = None
    timestamp: Optional[str] = None
    thumbnail: Optional[Dict[str, str]] = None
    author: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour l'API Discord."""
        embed = {}
        if self.title:
            embed["title"] = self.title
        if self.description:
            embed["description"] = self.description
        embed["color"] = self.color
        if self.fields:
            embed["fields"] = self.fields
        if self.footer:
            embed["footer"] = self.footer
        if self.timestamp:
            embed["timestamp"] = self.timestamp
        if self.thumbnail:
            embed["thumbnail"] = self.thumbnail
        if self.author:
            embed["author"] = self.author
        return embed


@dataclass
class SupportTicket:
    """Ticket de support Discord."""
    id: str
    channel_id: str
    user_id: str
    user_name: str
    subject: str
    messages: List[DiscordMessage] = field(default_factory=list)
    status: str = "open"  # open, in_progress, resolved, closed
    priority: str = "normal"  # low, normal, high, urgent
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None
    assigned_to: Optional[str] = None


# ============================================================================
# DISCORD BOT
# ============================================================================

class DiscordBot:
    """
    Bot Discord pour Agentys.

    Gère les notifications et le support via Discord.
    """

    def __init__(
        self,
        config: Optional[DiscordConfig] = None,
        account_id: Optional[str] = None,
    ):
        """Construct a DiscordBot.

        F-11 (audit issue #209, 2026-04-29): per-tenant scoping. See
        `TelegramBot.__init__` for design rationale; this is the same
        pattern. `account_id` keys the file paths so each tenant has
        isolated config + history; `None` keeps the legacy flat layout
        for background callers / admin pool.
        """
        self.config = config or DiscordConfig()
        self.account_id = account_id

        if account_id:
            base = DISCORD_DATA_DIR / str(account_id)
            base.mkdir(parents=True, exist_ok=True)
            self.config_file = base / "config.json"
            self.tickets_file = base / "tickets.json"
            self.history_file = base / "history.json"
        else:
            self.config_file = DISCORD_DATA_DIR / "config.json"
            self.tickets_file = DISCORD_DATA_DIR / "tickets.json"
            self.history_file = DISCORD_DATA_DIR / "history.json"

        self.tickets: Dict[str, SupportTicket] = {}
        self.history: List[DiscordMessage] = []
        self.message_handlers: List[Callable[[DiscordMessage], Awaitable[Optional[str]]]] = []

        self._load()

    def _load(self) -> None:
        """Charge la configuration et l'historique."""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                self.config = DiscordConfig(**data)
            except Exception:
                pass

        if self.tickets_file.exists():
            try:
                data = json.loads(self.tickets_file.read_text(encoding="utf-8"))
                self.tickets = {
                    tid: SupportTicket(**{
                        **ticket,
                        "messages": [DiscordMessage(**m) for m in ticket.get("messages", [])]
                    })
                    for tid, ticket in data.items()
                }
            except Exception:
                self.tickets = {}

        if self.history_file.exists():
            try:
                data = json.loads(self.history_file.read_text(encoding="utf-8"))
                self.history = [DiscordMessage(**m) for m in data]
            except Exception:
                self.history = []

    def _save(self) -> None:
        """Sauvegarde la configuration et l'historique."""
        self.config_file.write_text(
            json.dumps(asdict(self.config), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        tickets_data = {
            tid: {
                **asdict(ticket),
                "messages": [asdict(m) for m in ticket.messages]
            }
            for tid, ticket in self.tickets.items()
        }
        self.tickets_file.write_text(
            json.dumps(tickets_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # Limiter l'historique
        self.history = self.history[-500:]
        self.history_file.write_text(
            json.dumps([asdict(m) for m in self.history], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def configure(
        self,
        webhook_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        **kwargs
    ) -> None:
        """Configure le bot Discord."""
        if webhook_url:
            self.config.webhook_url = webhook_url
        if bot_token:
            self.config.bot_token = bot_token

        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        self._save()

    def is_configured(self) -> bool:
        """Vérifie si le bot est configuré."""
        return bool(self.config.webhook_url or self.config.bot_token)

    def _send_webhook(
        self,
        content: Optional[str] = None,
        embeds: Optional[List[DiscordEmbed]] = None,
        username: str = "Agentys"
    ) -> bool:
        """Envoie un message via webhook."""
        if not self.config.webhook_url:
            return False

        # M-8 (audit security.md, issue #542) : valider le host avant
        # l'outbound POST. Sans cette gate, un user pouvait configurer un
        # `webhook_url` interne (`http://localhost:5050/...`) et déclencher
        # une SSRF dès qu'une notification est produite. Allow-list :
        # `discord.com` + `discordapp.com` (legacy).
        from app.infrastructure.webhook_security import (
            DISCORD_HOSTS,
            is_allowed_webhook_url,
        )
        if not is_allowed_webhook_url(self.config.webhook_url, DISCORD_HOSTS):
            return False

        payload: Dict[str, Any] = {"username": username}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = [e.to_dict() for e in embeds]

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.config.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310 - URL already validated against DISCORD_HOSTS allow-list
                return response.status in (200, 204)
        except Exception:
            return False

    def send_notification(
        self,
        message: str,
        title: Optional[str] = None,
        color: EmbedColor = EmbedColor.INFO,
        fields: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Envoie une notification Discord.

        Args:
            message: Le message à envoyer
            title: Titre de l'embed (optionnel)
            color: Couleur de l'embed
            fields: Champs additionnels

        Returns:
            True si envoyé avec succès
        """
        if not self.config.enabled or not self.is_configured():
            return False

        embed = DiscordEmbed(
            title=title or "Notification Agentys",
            description=message,
            color=color.value,
            fields=fields or [],
            timestamp=datetime.now().isoformat(),
            footer={"text": "Agentys • Notification automatique"}
        )

        success = self._send_webhook(embeds=[embed])

        # Enregistrer dans l'historique
        msg = DiscordMessage(
            id=f"notif_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            channel_id=self.config.notifications_channel_id or "",
            author_id="bot",
            author_name="Agentys",
            content=message,
            message_type=MessageType.NOTIFICATION.value
        )
        self.history.append(msg)
        self._save()

        return success

    def send_alert(
        self,
        message: str,
        severity: str = "warning"
    ) -> bool:
        """
        Envoie une alerte Discord.

        Args:
            message: Message d'alerte
            severity: warning, error, critical

        Returns:
            True si envoyé avec succès
        """
        color = {
            "warning": EmbedColor.WARNING,
            "error": EmbedColor.ERROR,
            "critical": EmbedColor.ERROR
        }.get(severity, EmbedColor.WARNING)

        title = {
            "warning": "⚠️ Avertissement",
            "error": "❌ Erreur",
            "critical": "🚨 Alerte Critique"
        }.get(severity, "⚠️ Alerte")

        # Mention si configurée et critique
        mention = ""
        if severity == "critical" and self.config.mention_role_id:
            mention = f"<@&{self.config.mention_role_id}> "

        return self.send_notification(
            message=mention + message,
            title=title,
            color=color
        )

    def send_draft_created(
        self,
        subject: str,
        recipient: str,
        category: str = "NORMAL",
        confidence: Optional[float] = None
    ) -> bool:
        """Notifie qu'un brouillon a été créé."""
        fields = [
            {"name": "📧 Destinataire", "value": recipient, "inline": True},
            {"name": "📂 Catégorie", "value": category, "inline": True}
        ]

        if confidence is not None:
            fields.append({
                "name": "📊 Confiance",
                "value": f"{confidence:.0%}",
                "inline": True
            })

        return self.send_notification(
            message=f"**{subject}**",
            title="✉️ Nouveau brouillon créé",
            color=EmbedColor.SUCCESS,
            fields=fields
        )

    def send_followup_sent(
        self,
        subject: str,
        recipient: str,
        days_since: int
    ) -> bool:
        """Notifie qu'un follow-up a été envoyé."""
        return self.send_notification(
            message=f"**{subject}**\n\nRelance envoyée après {days_since} jours sans réponse.",
            title="🔄 Follow-up envoyé",
            color=EmbedColor.INFO,
            fields=[
                {"name": "📧 Destinataire", "value": recipient, "inline": True},
                {"name": "⏱️ Délai", "value": f"{days_since} jours", "inline": True}
            ]
        )

    def send_status_update(
        self,
        status: str,
        details: Optional[str] = None
    ) -> bool:
        """Envoie une mise à jour de statut."""
        embed = DiscordEmbed(
            title="📊 Statut Agentys",
            description=status,
            color=EmbedColor.DEFAULT.value,
            timestamp=datetime.now().isoformat()
        )

        if details:
            embed.fields = [{"name": "Détails", "value": details, "inline": False}]

        return self._send_webhook(embeds=[embed])

    def create_support_ticket(
        self,
        user_id: str,
        user_name: str,
        subject: str,
        initial_message: str,
        channel_id: str = ""
    ) -> SupportTicket:
        """
        Crée un nouveau ticket de support.

        Args:
            user_id: ID Discord de l'utilisateur
            user_name: Nom de l'utilisateur
            subject: Sujet du ticket
            initial_message: Premier message
            channel_id: ID du channel

        Returns:
            Le ticket créé
        """
        ticket_id = f"ticket_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.tickets)}"

        message = DiscordMessage(
            id=f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_0",
            channel_id=channel_id,
            author_id=user_id,
            author_name=user_name,
            content=initial_message,
            message_type=MessageType.SUPPORT_REQUEST.value
        )

        ticket = SupportTicket(
            id=ticket_id,
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
            subject=subject,
            messages=[message]
        )

        self.tickets[ticket_id] = ticket
        self._save()

        # Notifier le support
        self.send_notification(
            message=f"**{subject}**\n\n{initial_message[:200]}...",
            title="🎫 Nouveau ticket de support",
            color=EmbedColor.WARNING,
            fields=[
                {"name": "Utilisateur", "value": user_name, "inline": True},
                {"name": "ID Ticket", "value": ticket_id, "inline": True}
            ]
        )

        return ticket

    def add_message_to_ticket(
        self,
        ticket_id: str,
        author_id: str,
        author_name: str,
        content: str,
        is_response: bool = False
    ) -> Optional[DiscordMessage]:
        """Ajoute un message à un ticket."""
        if ticket_id not in self.tickets:
            return None

        ticket = self.tickets[ticket_id]

        message = DiscordMessage(
            id=f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(ticket.messages)}",
            channel_id=ticket.channel_id,
            author_id=author_id,
            author_name=author_name,
            content=content,
            message_type=(
                MessageType.SUPPORT_RESPONSE.value if is_response
                else MessageType.SUPPORT_REQUEST.value
            )
        )

        ticket.messages.append(message)
        self._save()

        return message

    def resolve_ticket(
        self,
        ticket_id: str,
        resolution_message: Optional[str] = None
    ) -> bool:
        """Marque un ticket comme résolu."""
        if ticket_id not in self.tickets:
            return False

        ticket = self.tickets[ticket_id]
        ticket.status = "resolved"
        ticket.resolved_at = datetime.now().isoformat()

        if resolution_message:
            self.add_message_to_ticket(
                ticket_id,
                author_id="bot",
                author_name="Agentys",
                content=resolution_message,
                is_response=True
            )

        self._save()
        return True

    def get_ticket(self, ticket_id: str) -> Optional[SupportTicket]:
        """Récupère un ticket."""
        return self.tickets.get(ticket_id)

    def get_open_tickets(self) -> List[SupportTicket]:
        """Récupère les tickets ouverts."""
        return [t for t in self.tickets.values() if t.status in ("open", "in_progress")]

    def get_user_tickets(self, user_id: str) -> List[SupportTicket]:
        """Récupère les tickets d'un utilisateur."""
        return [t for t in self.tickets.values() if t.user_id == user_id]

    def register_message_handler(
        self,
        handler: Callable[[DiscordMessage], Awaitable[Optional[str]]]
    ) -> None:
        """Enregistre un handler pour les messages."""
        self.message_handlers.append(handler)

    async def handle_incoming_message(self, message: DiscordMessage) -> Optional[str]:
        """
        Gère un message entrant.

        Args:
            message: Le message reçu

        Returns:
            La réponse générée ou None
        """
        self.history.append(message)
        self._save()

        # Appeler les handlers enregistrés
        for handler in self.message_handlers:
            try:
                response = await handler(message)
                if response:
                    return response
            except Exception:
                pass

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques."""
        open_tickets = len([t for t in self.tickets.values() if t.status == "open"])
        resolved_tickets = len([t for t in self.tickets.values() if t.status == "resolved"])

        return {
            "total_tickets": len(self.tickets),
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "total_messages": len(self.history),
            "configured": self.is_configured(),
            "enabled": self.config.enabled
        }


# ============================================================================
# REGISTRY (F-11 audit issue #209, 2026-04-29 — per-tenant scoping)
# ============================================================================

import threading as _threading
from collections import OrderedDict as _OrderedDict

# F-05 (regression audit, 2026-04-29): bounded LRU registry. See
# `app/telegram_integration.py` for the design rationale; this is the
# same pattern.
_DISCORD_REGISTRY_MAX = 200
_discord_bots: "_OrderedDict[str, DiscordBot]" = _OrderedDict()
_discord_bots_lock = _threading.Lock()


def get_discord_bot(account_id: Optional[str] = None) -> DiscordBot:
    """Retourne le DiscordBot pour `account_id` (ou le bot par défaut).

    F-11 (audit issue #209): same per-tenant scoping as
    `get_telegram_bot`.

    F-05 (regression audit, 2026-04-29): registry capped at 200
    entries; default pool is pinned and excluded from eviction.
    """
    key = str(account_id) if account_id is not None else "__default__"
    with _discord_bots_lock:
        bot = _discord_bots.get(key)
        if bot is not None:
            _discord_bots.move_to_end(key)
            return bot

        bot = DiscordBot(account_id=account_id)
        _discord_bots[key] = bot

        while len(_discord_bots) > _DISCORD_REGISTRY_MAX:
            evict_key, _ = next(iter(_discord_bots.items()))
            if evict_key == "__default__":
                _discord_bots.move_to_end("__default__")
                continue
            _discord_bots.pop(evict_key, None)
        return bot


def evict_discord_bot(account_id: str) -> bool:
    """Drop a specific tenant's Discord bot from the registry. F-05."""
    if account_id is None:
        return False
    key = str(account_id)
    with _discord_bots_lock:
        return _discord_bots.pop(key, None) is not None
