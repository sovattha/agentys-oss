# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Helpers d'authentification partagés entre les blueprints.

Extraits de accounts.py pour réutilisation dans calendar_routes.py,
calendar.py, et tout autre blueprint nécessitant l'isolation multi-user.
"""
from __future__ import annotations

import os
from typing import Optional

from flask import g


def is_production() -> bool:
    """Detect production environment across all known indicators.

    Centralizes the env detection that was previously duplicated in
    `oauth.py`, `auth.py`, `oauth_ads.py`, `app.py`, and elsewhere.
    Audit 2026-04-25 (sub-report 05 F-HIGH-2 / F-HIGH-3) flagged that
    Railway's canonical var is `RAILWAY_ENVIRONMENT_NAME` but most
    detectors only check `RAILWAY_ENVIRONMENT` — if Railway ever
    deprecates the legacy var, every guard silently turns off.
    """
    return (
        os.environ.get("FLASK_ENV", "").lower() == "production"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
        or os.environ.get("RAILWAY_ENVIRONMENT", "").lower() == "production"
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production"
    )


def get_auth_user_id() -> Optional[int]:
    """Extrait le user_id du JWT (g.auth_user) ou None en mode Tauri.

    Returns None for loopback connections so that ownership checks are
    bypassed in Tauri desktop mode — even when a JWT token is present
    (e.g. a token left over from a previous web session).
    """
    from flask import has_request_context

    auth_user = getattr(g, "auth_user", None) if has_request_context() else None
    if auth_user and auth_user.get("id"):
        # Loopback connections = Tauri desktop: no user isolation
        if has_request_context():
            from app.api.auth import is_trusted_loopback

            if is_trusted_loopback():
                return None
        uid = auth_user["id"]
        try:
            return int(uid)
        except (ValueError, TypeError):
            return None
    return None


def check_account_ownership(account, auth_user_id: Optional[int]) -> bool:
    """Vérifie que le compte appartient au user JWT. Retourne True si OK."""
    if auth_user_id is None:
        return True  # Mode Tauri desktop — pas de restriction
    if account.user_id is None:
        return False  # Compte sans user_id (legacy) — refuser en mode web authentifié
    return account.user_id == auth_user_id
