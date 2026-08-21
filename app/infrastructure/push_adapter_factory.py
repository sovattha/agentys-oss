# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Factory pour les adapters de notification push.

Ce module fournit la logique de sélection automatique
de l'adapter approprié (FCM, Expo, Mock) selon la configuration.
"""

import os
import logging
import threading
from typing import Optional

from app.domain.ports import NotificationPort

logger = logging.getLogger(__name__)

_push_adapter: Optional[NotificationPort] = None
_init_lock = threading.Lock()


def get_push_adapter() -> NotificationPort:
    """
    Retourne l'adapter de push notifications configuré.

    Sélectionne automatiquement FCM ou Expo selon la configuration.

    Returns:
        Adapter implémentant NotificationPort.
    """
    global _push_adapter
    # Double-checked locking : le fast path sans lock couvre 99% des appels
    # une fois le singleton initialisé. Le lock garantit qu'un seul thread
    # crée l'adapter quand plusieurs entrent simultanément.
    if _push_adapter is not None:
        return _push_adapter

    with _init_lock:
        if _push_adapter is not None:
            return _push_adapter

        # Vérifier si FCM est configuré
        if os.getenv("FIREBASE_CREDENTIALS_PATH") or os.getenv("FIREBASE_PROJECT_ID"):
            from app.adapters.push import FCMAdapter
            adapter = FCMAdapter()
            if adapter.is_available():
                logger.info("Using FCM adapter for push notifications")
                _push_adapter = adapter
                return adapter

        # Fallback sur Expo (toujours disponible)
        from app.adapters.push import ExpoAdapter
        logger.info("Using Expo adapter for push notifications")
        _push_adapter = ExpoAdapter()
        return _push_adapter


def set_push_adapter(adapter: NotificationPort) -> None:
    """
    Configure manuellement l'adapter de push notifications.

    Utile pour les tests ou pour forcer un adapter spécifique.

    Args:
        adapter: Adapter à utiliser.
    """
    global _push_adapter
    with _init_lock:
        _push_adapter = adapter
    logger.info(f"Push adapter set to: {adapter.name}")


def reset_push_adapter() -> None:
    """Réinitialise l'adapter (utile pour les tests)."""
    global _push_adapter
    with _init_lock:
        _push_adapter = None
