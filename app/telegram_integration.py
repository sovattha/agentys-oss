# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Intégration Telegram pour Agentys.

Permet d'envoyer des notifications et de répondre aux demandes de support
via un bot Telegram.

Usage:
    from app.telegram_integration import TelegramBot, get_telegram_bot

    bot = get_telegram_bot()

    # Envoyer une notification
    bot.send_notification("Un nouveau brouillon a été créé")

    # Répondre à un message de support
    bot.handle_support_message(message, chat_id)
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.config import DATA_DIR


# ============================================================================
# CONFIGURATION
# ============================================================================

TELEGRAM_DATA_DIR = DATA_DIR / "telegram"
TELEGRAM_DATA_DIR.mkdir(parents=True, exist_ok=True)


class TelegramMessageType(Enum):
    """Types de messages Telegram."""
    NOTIFICATION = "notification"
    SUPPORT_REQUEST = "support_request"
    SUPPORT_RESPONSE = "support_response"
    ALERT = "alert"
    STATUS = "status"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TelegramConfig:
    """Configuration du bot Telegram."""
    bot_token: Optional[str] = None
    support_chat_id: Optional[str] = None
    notifications_chat_id: Optional[str] = None
    enabled: bool = True
    language: str = "fr"
    bot_name: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class TelegramMessage:
    """Représente un message Telegram."""
    id: str
    chat_id: str
    author_id: str
    author_name: str
    content: str
    message_type: str = "notification"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    responded: bool = False
    response_content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TelegramSupportTicket:
    """Ticket de support Telegram."""
    id: str
    chat_id: str
    user_id: str
    user_name: str
    subject: str
    messages: List[TelegramMessage] = field(default_factory=list)
    status: str = "open"  # open, in_progress, resolved, closed
    priority: str = "normal"  # low, normal, high, urgent
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None
    assigned_to: Optional[str] = None


# ============================================================================
# TELEGRAM BOT
# ============================================================================

class TelegramBot:
    """
    Bot Telegram pour Agentys.

    Gère les notifications et le support via Telegram.
    """

    def __init__(
        self,
        config: Optional[TelegramConfig] = None,
        account_id: Optional[str] = None,
    ):
        """Construct a TelegramBot.

        F-11 (audit issue #209, 2026-04-29): per-tenant scoping. When
        `account_id` is supplied, config + history live under
        `TELEGRAM_DATA_DIR/<account_id>/`, isolating each tenant from
        the others. Legacy callers (`account_id=None`) keep the original
        flat file layout under `TELEGRAM_DATA_DIR/` — that bot is now
        the "default" admin-pool used by background notifications and
        cron alerts that have no JWT context.

        Use `get_telegram_bot(account_id)` to get a per-tenant bot from
        the API layer; use `get_telegram_bot()` for background callers.
        """
        self.config = config or TelegramConfig()
        self.account_id = account_id

        if account_id:
            base = TELEGRAM_DATA_DIR / str(account_id)
            base.mkdir(parents=True, exist_ok=True)
            self.config_file = base / "config.json"
            self.tickets_file = base / "tickets.json"
            self.history_file = base / "history.json"
        else:
            self.config_file = TELEGRAM_DATA_DIR / "config.json"
            self.tickets_file = TELEGRAM_DATA_DIR / "tickets.json"
            self.history_file = TELEGRAM_DATA_DIR / "history.json"

        self.tickets: Dict[str, TelegramSupportTicket] = {}
        self.history: List[TelegramMessage] = []
        self.message_handlers: List[Callable[[TelegramMessage], Awaitable[Optional[str]]]] = []

        self._load()

    def _load(self) -> None:
        """Charge la configuration et l'historique."""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                self.config = TelegramConfig(**data)
            except Exception:
                pass

        if self.tickets_file.exists():
            try:
                data = json.loads(self.tickets_file.read_text(encoding="utf-8"))
                self.tickets = {
                    tid: TelegramSupportTicket(**{
                        **ticket,
                        "messages": [TelegramMessage(**m) for m in ticket.get("messages", [])]
                    })
                    for tid, ticket in data.items()
                }
            except Exception:
                self.tickets = {}

        if self.history_file.exists():
            try:
                data = json.loads(self.history_file.read_text(encoding="utf-8"))
                self.history = [TelegramMessage(**m) for m in data]
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
        bot_token: Optional[str] = None,
        **kwargs
    ) -> None:
        """Configure le bot Telegram."""
        if bot_token:
            self.config.bot_token = bot_token

        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        self._save()

    def is_configured(self) -> bool:
        """Vérifie si le bot est configuré."""
        return bool(self.config.bot_token)

    def send_notification(
        self,
        message: str,
        title: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Envoie une notification Telegram.

        Args:
            message: Le message à envoyer
            title: Titre du message (optionnel)
            chat_id: ID du chat (utilise notifications_chat_id par défaut)

        Returns:
            True si envoyé avec succès
        """
        if not self.config.enabled or not self.is_configured():
            return False

        target_chat = chat_id or self.config.notifications_chat_id
        if not target_chat:
            return False

        try:
            from app.providers.telegram_adapter import get_telegram_adapter

            adapter = get_telegram_adapter()
            if not adapter or not adapter.is_connected():
                return False

            full_message = message
            if title:
                full_message = f"*{title}*\n\n{message}"

            result = adapter.send_message(target_chat, full_message)

            # Enregistrer dans l'historique
            msg = TelegramMessage(
                id=f"notif_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                chat_id=target_chat,
                author_id="bot",
                author_name="Agentys",
                content=message,
                message_type=TelegramMessageType.NOTIFICATION.value
            )
            self.history.append(msg)
            self._save()

            return result is not None
        except Exception:
            return False

    def send_alert(
        self,
        message: str,
        severity: str = "warning"
    ) -> bool:
        """
        Envoie une alerte Telegram.

        Args:
            message: Message d'alerte
            severity: warning, error, critical

        Returns:
            True si envoyé avec succès
        """
        emoji = {
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨"
        }.get(severity, "⚠️")

        title = {
            "warning": "Avertissement",
            "error": "Erreur",
            "critical": "Alerte Critique"
        }.get(severity, "Alerte")

        return self.send_notification(
            message=message,
            title=f"{emoji} {title}"
        )

    def send_draft_created(
        self,
        subject: str,
        recipient: str,
        category: str = "NORMAL",
        confidence: Optional[float] = None
    ) -> bool:
        """Notifie qu'un brouillon a été créé."""
        message = f"📧 Destinataire: {recipient}\n📂 Catégorie: {category}"

        if confidence is not None:
            message += f"\n📊 Confiance: {confidence:.0%}"

        message += f"\n\n*{subject}*"

        return self.send_notification(
            message=message,
            title="✉️ Nouveau brouillon créé"
        )

    def send_followup_sent(
        self,
        subject: str,
        recipient: str,
        days_since: int
    ) -> bool:
        """Notifie qu'un follow-up a été envoyé."""
        message = (
            f"📧 Destinataire: {recipient}\n"
            f"⏱️ Délai: {days_since} jours\n\n"
            f"*{subject}*\n\n"
            f"Relance envoyée après {days_since} jours sans réponse."
        )

        return self.send_notification(
            message=message,
            title="🔄 Follow-up envoyé"
        )

    def send_status_update(
        self,
        status: str,
        details: Optional[str] = None
    ) -> bool:
        """Envoie une mise à jour de statut."""
        message = status
        if details:
            message += f"\n\nDétails: {details}"

        return self.send_notification(
            message=message,
            title="📊 Statut Agentys"
        )

    def create_support_ticket(
        self,
        user_id: str,
        user_name: str,
        subject: str,
        initial_message: str,
        chat_id: str = ""
    ) -> TelegramSupportTicket:
        """
        Crée un nouveau ticket de support.

        Args:
            user_id: ID Telegram de l'utilisateur
            user_name: Nom de l'utilisateur
            subject: Sujet du ticket
            initial_message: Premier message
            chat_id: ID du chat

        Returns:
            Le ticket créé
        """
        ticket_id = f"ticket_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.tickets)}"

        message = TelegramMessage(
            id=f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_0",
            chat_id=chat_id,
            author_id=user_id,
            author_name=user_name,
            content=initial_message,
            message_type=TelegramMessageType.SUPPORT_REQUEST.value
        )

        ticket = TelegramSupportTicket(
            id=ticket_id,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            subject=subject,
            messages=[message]
        )

        self.tickets[ticket_id] = ticket
        self._save()

        # Notifier le support
        self.send_notification(
            message=f"*{subject}*\n\n{initial_message[:200]}...\n\n"
                    f"Utilisateur: {user_name}\nID Ticket: {ticket_id}",
            title="🎫 Nouveau ticket de support"
        )

        return ticket

    def add_message_to_ticket(
        self,
        ticket_id: str,
        author_id: str,
        author_name: str,
        content: str,
        is_response: bool = False
    ) -> Optional[TelegramMessage]:
        """Ajoute un message à un ticket."""
        if ticket_id not in self.tickets:
            return None

        ticket = self.tickets[ticket_id]

        message = TelegramMessage(
            id=f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(ticket.messages)}",
            chat_id=ticket.chat_id,
            author_id=author_id,
            author_name=author_name,
            content=content,
            message_type=(
                TelegramMessageType.SUPPORT_RESPONSE.value if is_response
                else TelegramMessageType.SUPPORT_REQUEST.value
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

    def get_ticket(self, ticket_id: str) -> Optional[TelegramSupportTicket]:
        """Récupère un ticket."""
        return self.tickets.get(ticket_id)

    def get_open_tickets(self) -> List[TelegramSupportTicket]:
        """Récupère les tickets ouverts."""
        return [t for t in self.tickets.values() if t.status in ("open", "in_progress")]

    def get_user_tickets(self, user_id: str) -> List[TelegramSupportTicket]:
        """Récupère les tickets d'un utilisateur."""
        return [t for t in self.tickets.values() if t.user_id == user_id]

    def register_message_handler(
        self,
        handler: Callable[[TelegramMessage], Awaitable[Optional[str]]]
    ) -> None:
        """Enregistre un handler pour les messages."""
        self.message_handlers.append(handler)

    async def handle_incoming_message(self, message: TelegramMessage) -> Optional[str]:
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

# F-05 (regression audit, 2026-04-29): the original F-11 dict-based
# registry grew unboundedly with the tenant count — each TelegramBot
# carries config + tickets + history (~100KB-1MB depending on history
# size). On a long-running 512MB Railway worker that's an OOM after
# ~200-500 distinct tenants. OrderedDict + manual LRU eviction keeps
# the registry capped without adding a new dependency.
#
# F-06 (regression audit, 2026-04-29) — KNOWN MULTI-WORKER LIMITATION:
# this registry lives in process memory, so each gunicorn/uvicorn
# worker holds its own copy. Today this is acceptable because Agentys
# prod is single-process Werkzeug (`python run_api.py`, see
# railway.toml). If we ever migrate to gunicorn N>1 workers, the
# per-tenant histories may diverge across workers (tenant A's webhook
# lands on worker 1, tenant A's API read lands on worker 2 → empty).
# Mitigation when that happens: switch to file-backed reads on every
# call (the JSON files under TELEGRAM_DATA_DIR/<account_id>/ are the
# source of truth) or add Redis pubsub for cache invalidation.
_TELEGRAM_REGISTRY_MAX = 200
_telegram_bots: "_OrderedDict[str, TelegramBot]" = _OrderedDict()
_telegram_bots_lock = _threading.Lock()


def get_telegram_bot(account_id: Optional[str] = None) -> TelegramBot:
    """Retourne le TelegramBot pour `account_id` (ou le bot par défaut).

    F-11 (audit issue #209): the previous singleton aggregated DM
    content across every tenant, so any authenticated user could read
    every other tenant's Telegram messages via /api/telegram/messages.
    Now keyed: each tenant has their own config (separate bot_token,
    chat_ids), tickets, and history under
    `TELEGRAM_DATA_DIR/<account_id>/`.

    F-05 (regression audit, 2026-04-29): registry is bounded by
    `_TELEGRAM_REGISTRY_MAX` (LRU eviction on overflow). The default
    pool entry is pinned (never evicted) because background callers
    rely on it.

    - `account_id` set    → tenant-isolated bot. Used by the API layer.
    - `account_id is None` → "default" pool at `TELEGRAM_DATA_DIR/`.
      Used for background notifications, cron alerts, and admin
      operational reads (where there is no JWT context).
    """
    key = str(account_id) if account_id is not None else "__default__"
    with _telegram_bots_lock:
        bot = _telegram_bots.get(key)
        if bot is not None:
            # LRU touch — move to end so eviction targets stale tenants first.
            _telegram_bots.move_to_end(key)
            return bot

        bot = TelegramBot(account_id=account_id)
        _telegram_bots[key] = bot

        # Evict oldest non-default entries when over cap. Bounded loop
        # is safe because we only insert one entry per call.
        while len(_telegram_bots) > _TELEGRAM_REGISTRY_MAX:
            evict_key, _ = next(iter(_telegram_bots.items()))
            if evict_key == "__default__":
                # Pinned. Move to end and evict the next oldest instead.
                _telegram_bots.move_to_end("__default__")
                continue
            _telegram_bots.pop(evict_key, None)
        return bot


def evict_telegram_bot(account_id: str) -> bool:
    """Drop a specific tenant's bot from the registry.

    F-05: callable from account-deletion paths so the tenant's bot
    state doesn't linger in worker memory after they leave. Returns
    True if a bot was evicted, False otherwise.
    """
    if account_id is None:
        return False
    key = str(account_id)
    with _telegram_bots_lock:
        return _telegram_bots.pop(key, None) is not None
