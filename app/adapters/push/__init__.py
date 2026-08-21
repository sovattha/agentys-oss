# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters pour les notifications push.

Ce module fournit les adapters pour différents services de push notifications:
- Firebase Cloud Messaging (FCM) pour Android/iOS/Web
- Expo Push pour les apps React Native/Expo
- Mock adapter pour les tests
"""

from .fcm_adapter import FCMAdapter
from .expo_adapter import ExpoAdapter
from .mock_adapter import MockPushAdapter

__all__ = ["FCMAdapter", "ExpoAdapter", "MockPushAdapter"]
