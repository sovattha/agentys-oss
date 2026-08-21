# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Notifications pour Agentys.

Ce module fournit des notifications cross-platform:
- Desktop: macOS (osascript), Linux (notify-send), Windows (win10toast)
- Mobile: Push notifications via FCM/Expo

Usage:
    from app.infrastructure.notifications import notify

    notify.draft_created("john@example.com", "Meeting Tomorrow")
    notify.error("Failed to connect to Gmail")

    # Push notifications mobiles (si devices enregistres)
    notify.draft_created("john@example.com", "Meeting Tomorrow", draft_id="123")
"""

import os
import sys
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class NotificationType(Enum):
    """Types de notifications."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class NotificationConfig:
    """Configuration des notifications."""
    enabled: bool = True
    sound: bool = True
    timeout_seconds: int = 5
    app_name: str = "Agentys"
    app_icon: Optional[str] = None  # Chemin vers l'icône
    push_enabled: bool = True  # Activer les push notifications mobiles


# ============================================================================
# SECURITY HELPERS
# ============================================================================

def _sanitize_for_applescript(text: str) -> str:
    """
    Sanitize text for safe inclusion in AppleScript strings.

    Prevents command injection via osascript.
    """
    if text is None:
        return ""
    # Escape backslashes first, then quotes
    return text.replace('\\', '\\\\').replace('"', '\\"')


def _sanitize_for_powershell(text: str) -> str:
    """
    Sanitize text for safe inclusion in PowerShell strings.

    Prevents command injection via PowerShell.
    """
    if text is None:
        return ""
    # Escape PowerShell special characters
    # Order matters: backtick first as it's the escape character
    return (text
            .replace('`', '``')
            .replace('"', '`"')
            .replace('$', '`$')
            .replace("'", "`'"))


# ============================================================================
# NOTIFIERS PAR PLATEFORME
# ============================================================================

class BaseNotifier:
    """Interface de base pour les notifiers."""

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = True,
    ) -> bool:
        """Envoie une notification."""
        raise NotImplementedError


class MacOSNotifier(BaseNotifier):
    """Notifications macOS via osascript."""

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = True,
    ) -> bool:
        try:
            # Sanitize to prevent AppleScript injection
            title_safe = _sanitize_for_applescript(title)
            message_safe = _sanitize_for_applescript(message)

            sound_cmd = 'sound name "default"' if sound else ""

            script = f'''
            display notification "{message_safe}" with title "{title_safe}" {sound_cmd}
            '''

            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5
            )
            return True
        except Exception as e:
            logger.debug(f"MacOS notification failed: {e}")
            return False


class LinuxNotifier(BaseNotifier):
    """Notifications Linux via notify-send."""

    URGENCY_MAP = {
        NotificationType.INFO: "low",
        NotificationType.SUCCESS: "normal",
        NotificationType.WARNING: "normal",
        NotificationType.ERROR: "critical",
    }

    ICON_MAP = {
        NotificationType.INFO: "dialog-information",
        NotificationType.SUCCESS: "emblem-ok-symbolic",
        NotificationType.WARNING: "dialog-warning",
        NotificationType.ERROR: "dialog-error",
    }

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = True,
    ) -> bool:
        try:
            urgency = self.URGENCY_MAP.get(notification_type, "normal")
            icon = self.ICON_MAP.get(notification_type, "dialog-information")

            cmd = [
                "notify-send",
                "-u", urgency,
                "-i", icon,
                title,
                message
            ]

            subprocess.run(cmd, capture_output=True, timeout=5)
            return True
        except Exception as e:
            logger.debug(f"Linux notification failed: {e}")
            return False


class WindowsNotifier(BaseNotifier):
    """Notifications Windows via win10toast ou fallback."""

    def __init__(self):
        self._toaster = None
        try:
            from win10toast import ToastNotifier
            self._toaster = ToastNotifier()
        except ImportError:
            pass

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = True,
    ) -> bool:
        try:
            if self._toaster:
                self._toaster.show_toast(
                    title,
                    message,
                    duration=5,
                    threaded=True,
                )
                return True
            else:
                # Fallback: PowerShell toast
                # Sanitize to prevent PowerShell injection
                title_safe = _sanitize_for_powershell(title)
                message_safe = _sanitize_for_powershell(message)

                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $textNodes = $template.GetElementsByTagName("text")
                $textNodes.Item(0).AppendChild($template.CreateTextNode("{title_safe}"))
                $textNodes.Item(1).AppendChild($template.CreateTextNode("{message_safe}"))
                $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
                $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Agentys")
                $notifier.Show($toast)
                '''
                subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True,
                    timeout=10
                )
                return True
        except Exception as e:
            logger.debug(f"Windows notification failed: {e}")
            return False


class FallbackNotifier(BaseNotifier):
    """Notifier de fallback qui log simplement."""

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = True,
    ) -> bool:
        # Afficher dans la console avec emoji
        icons = {
            NotificationType.INFO: "ℹ️",
            NotificationType.SUCCESS: "✅",
            NotificationType.WARNING: "⚠️",
            NotificationType.ERROR: "❌",
        }
        icon = icons.get(notification_type, "📢")
        logger.info(f"{icon} {title}: {message}")
        return True


# ============================================================================
# NOTIFICATION MANAGER
# ============================================================================

@dataclass
class NotificationManager:
    """
    Gestionnaire de notifications cross-platform.

    Détecte automatiquement la plateforme et utilise le notifier approprié.

    Pour les push notifications mobiles, utilise un callback injecté depuis
    la couche application afin de respecter la Dependency Rule de Clean Architecture.
    """

    config: NotificationConfig = field(default_factory=NotificationConfig)
    _notifier: BaseNotifier = field(default=None, init=False)
    _callbacks: Dict[NotificationType, list] = field(default_factory=dict, init=False)
    _push_service_getter: Optional[Callable] = field(default=None, init=False)

    def __post_init__(self):
        self._notifier = self._get_platform_notifier()
        self._callbacks = {nt: [] for nt in NotificationType}

    def set_push_service_getter(self, getter: Callable) -> None:
        """
        Configure le callback pour obtenir le service de push notifications.

        Cette méthode permet l'injection de dépendance depuis la couche application,
        évitant que l'infrastructure importe directement la couche application.

        Args:
            getter: Fonction qui retourne le PushNotificationService.
        """
        self._push_service_getter = getter

    def _get_push_service(self):
        """Retourne le service de push notifications via le getter injecté."""
        if self._push_service_getter is None:
            return None
        try:
            return self._push_service_getter()
        except Exception as e:
            logger.debug(f"Could not get push service: {e}")
            return None

    def _get_platform_notifier(self) -> BaseNotifier:
        """Retourne le notifier adapté à la plateforme."""
        if sys.platform == "darwin":
            return MacOSNotifier()
        elif sys.platform.startswith("linux"):
            return LinuxNotifier()
        elif sys.platform == "win32":
            return WindowsNotifier()
        else:
            return FallbackNotifier()

    def send(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        sound: bool = None,
    ) -> bool:
        """
        Envoie une notification.

        Args:
            title: Titre de la notification.
            message: Corps du message.
            notification_type: Type de notification.
            sound: Jouer un son (None = config par défaut).

        Returns:
            True si la notification a été envoyée.
        """
        if not self.config.enabled:
            return False

        if sound is None:
            sound = self.config.sound

        # Exécuter les callbacks
        for callback in self._callbacks.get(notification_type, []):
            try:
                callback(title, message)
            except Exception as e:
                logger.debug(f"Callback error: {e}")

        return self._notifier.send(title, message, notification_type, sound)

    def register_callback(
        self,
        notification_type: NotificationType,
        callback: Callable[[str, str], None]
    ) -> None:
        """Enregistre un callback pour un type de notification."""
        if notification_type not in self._callbacks:
            self._callbacks[notification_type] = []
        self._callbacks[notification_type].append(callback)

    # ========================================================================
    # MÉTHODES PRATIQUES POUR L'APPLICATION
    # ========================================================================

    def draft_created(
        self,
        recipient: str,
        subject: str,
        priority: Optional[int] = None,
        draft_id: Optional[str] = None,
    ) -> bool:
        """Notification: brouillon créé."""
        priority_info = f" [P{priority}]" if priority else ""
        title = f"Brouillon créé{priority_info}"
        message = f"Réponse à {recipient}: {subject[:50]}"

        # Notification desktop
        desktop_result = self.send(title, message, NotificationType.SUCCESS)

        # Notification push mobile
        if self.config.push_enabled and draft_id:
            self._send_push_draft_created(recipient, subject, draft_id, priority or 50)

        return desktop_result

    def draft_failed(self, recipient: str, error: str) -> bool:
        """Notification: échec création brouillon."""
        title = "Échec brouillon"
        message = f"Impossible de répondre à {recipient}: {error[:50]}"
        return self.send(title, message, NotificationType.ERROR)

    def followup_created(self, recipient: str, days: int) -> bool:
        """Notification: relance créée."""
        title = "Relance créée"
        message = f"Relance à {recipient} (sans réponse depuis {days}j)"

        # Notification desktop
        desktop_result = self.send(title, message, NotificationType.INFO)

        # Notification push mobile
        if self.config.push_enabled:
            self._send_push_followup(recipient, days)

        return desktop_result

    def learning_complete(self, patterns_count: int, adjustments: int) -> bool:
        """Notification: apprentissage terminé."""
        title = "Apprentissage terminé"
        message = f"{patterns_count} patterns extraits, {adjustments} ajustements actifs"
        return self.send(title, message, NotificationType.INFO, sound=False)

    def health_check_failed(self, component: str) -> bool:
        """Notification: health check échoué."""
        title = "Health Check Échoué"
        message = f"Composant en erreur: {component}"
        return self.send(title, message, NotificationType.ERROR)

    def rate_limit_warning(self, remaining_percent: float) -> bool:
        """Notification: quota API presque atteint."""
        title = "Quota API"
        message = f"Attention: {remaining_percent:.0f}% du quota restant"
        return self.send(title, message, NotificationType.WARNING)

    def budget_warning(self, current: float, limit: float) -> bool:
        """Notification: budget presque atteint."""
        title = "Budget API"
        percent = (current / limit) * 100 if limit > 0 else 0
        message = f"Attention: {percent:.0f}% du budget utilisé (${current:.2f}/${limit:.2f})"
        return self.send(title, message, NotificationType.WARNING)

    def error(self, error_message: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Notification générique d'erreur."""
        title = "Erreur Agentys"

        # Notification desktop
        desktop_result = self.send(title, error_message[:100], NotificationType.ERROR)

        # Notification push mobile
        if self.config.push_enabled:
            self._send_push_error(error_message, context)

        return desktop_result

    def info(self, message: str) -> bool:
        """Notification générique d'info."""
        return self.send("Agentys", message[:100], NotificationType.INFO)

    def vip_email_received(
        self,
        sender: str,
        subject: str,
        vip_name: Optional[str] = None,
        email_id: Optional[str] = None,
    ) -> bool:
        """
        Notification immédiate pour un email VIP reçu.

        Cette notification est prioritaire et envoyée immédiatement.

        Args:
            sender: Adresse email de l'expéditeur VIP.
            subject: Sujet de l'email.
            vip_name: Nom du VIP (optionnel, pour affichage).
            email_id: ID de l'email (pour deep link).

        Returns:
            True si la notification a été envoyée.
        """
        display_name = vip_name or sender.split("@")[0]
        title = f"VIP: {display_name}"
        message = f"{subject[:50]}"

        desktop_result = self.send(title, message, NotificationType.SUCCESS, sound=True)

        if self.config.push_enabled and email_id:
            self._execute_push(
                "notify_all_vip_email",
                sender=sender,
                subject=subject,
                email_id=email_id,
            )

        return desktop_result

    # ========================================================================
    # MÉTHODES PUSH NOTIFICATIONS (PRIVÉES)
    # ========================================================================

    def _execute_push(self, method_name: str, **kwargs) -> None:
        """
        Exécute une méthode du service push de manière sécurisée.

        Args:
            method_name: Nom de la méthode à appeler sur le service push.
            **kwargs: Arguments à passer à la méthode.
        """
        service = self._get_push_service()
        if service is None:
            return
        try:
            method = getattr(service, method_name, None)
            if method:
                method(**kwargs)
        except Exception as e:
            logger.debug(f"Push notification failed ({method_name}): {e}")

    def _send_push_draft_created(
        self,
        recipient: str,
        subject: str,
        draft_id: str,
        priority_score: int,
    ) -> None:
        """Envoie une push notification pour un brouillon créé."""
        self._execute_push(
            "notify_all_draft_created",
            recipient=recipient,
            subject=subject,
            draft_id=draft_id,
            priority_score=priority_score,
        )

    def _send_push_followup(self, recipient: str, days_since: int) -> None:
        """Envoie une push notification pour une relance."""
        self._execute_push(
            "notify_all_followup_sent",
            recipient=recipient,
            days_since=days_since,
        )

    def _send_push_error(
        self,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Envoie une push notification pour une erreur."""
        self._execute_push(
            "notify_all_error",
            error_message=error_message,
            context=context,
        )


# ============================================================================
# SINGLETON
# ============================================================================

_notification_manager: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """Retourne l'instance singleton du notification manager."""
    global _notification_manager
    if _notification_manager is None:
        # Configuration depuis variables d'environnement
        config = NotificationConfig(
            enabled=os.getenv("NOTIFICATIONS_ENABLED", "true").lower() == "true",
            sound=os.getenv("NOTIFICATIONS_SOUND", "true").lower() == "true",
            timeout_seconds=int(os.getenv("NOTIFICATIONS_TIMEOUT", "5")),
            push_enabled=os.getenv("PUSH_NOTIFICATIONS_ENABLED", "true").lower() == "true",
        )
        _notification_manager = NotificationManager(config=config)
    return _notification_manager


def configure_push_notifications(push_service_getter: Callable) -> None:
    """
    Configure les push notifications en injectant le service depuis la couche application.

    Cette fonction doit être appelée au démarrage de l'application (par ex. dans daemon.py)
    après que toutes les dépendances sont initialisées.

    Respecte la Dependency Rule de Clean Architecture : le getter est injecté depuis
    l'extérieur, l'infrastructure ne dépend pas de la couche application.

    Args:
        push_service_getter: Fonction qui retourne le PushNotificationService.
                            Doit être fournie par la couche application/composition root.

    Example:
        from app.infrastructure.container import get_container
        configure_push_notifications(lambda: get_container().get_push_notification_service())
    """
    manager = get_notification_manager()
    manager.set_push_service_getter(push_service_getter)


# Raccourci pour accès direct
notify = get_notification_manager()


# ============================================================================
# EXEMPLE D'UTILISATION
# ============================================================================

if __name__ == "__main__":
    # Test des notifications
    print("Test des notifications...")

    notif = get_notification_manager()

    # Test info
    notif.info("Le daemon a démarré")

    # Test succès
    notif.draft_created("john@example.com", "Meeting Tomorrow at 3pm")

    # Test warning
    notif.budget_warning(45.50, 50.00)

    # Test erreur
    notif.error("Impossible de se connecter à l'API Gmail")

    print("Notifications envoyées!")
