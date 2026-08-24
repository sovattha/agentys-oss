# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""WordPress REST API client — search_user, reset_password, update_email."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from app.interfaces.account_provider import AccountActionResult, AccountProvider

logger = logging.getLogger(__name__)

_WP_SITE_URL: str = os.getenv("WORDPRESS_SITE_URL", "")
_WP_USERNAME: str = os.getenv("WORDPRESS_USERNAME", "")
_WP_APP_PASSWORD: str = os.getenv("WORDPRESS_APP_PASSWORD", "")


def _load_agent_config() -> dict:
    """Lit app/data/agent_configs/account.json si present."""
    try:
        path = Path(__file__).parent.parent / "data" / "agent_configs" / "account.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _get_effective_creds() -> tuple:
    """Retourne (site_url, username, app_password) depuis la config ou l'env."""
    cfg = _load_agent_config()

    # New nested format
    if "providers" in cfg:
        wp_cfg = cfg.get("providers", {}).get("wordpress", {})
        site_url = wp_cfg.get("site_url", "") or _WP_SITE_URL
        username = wp_cfg.get("username", "") or _WP_USERNAME
        app_password = wp_cfg.get("app_password", "") or _WP_APP_PASSWORD
    else:
        # Legacy flat format
        site_url = cfg.get("wordpress_site_url", "") or _WP_SITE_URL
        username = cfg.get("wordpress_username", "") or _WP_USERNAME
        app_password = cfg.get("wordpress_app_password", "") or _WP_APP_PASSWORD

    # Filter masked values
    if site_url and "••" in site_url:
        site_url = _WP_SITE_URL
    if username and "••" in username:
        username = _WP_USERNAME
    if app_password and "••" in app_password:
        app_password = _WP_APP_PASSWORD

    return site_url.rstrip("/"), username, app_password


class WordPressAccountProvider(AccountProvider):
    """Fournisseur de gestion de comptes WordPress via REST API."""

    def __init__(self, site_url: str = "", username: str = "", app_password: str = ""):
        self._site_url = site_url.rstrip("/")
        self._username = username
        self._app_password = app_password

    @property
    def provider_name(self) -> str:
        return "wordpress"

    def _get_session(self):
        import base64
        import requests

        if not self._site_url or not self._username or not self._app_password:
            raise RuntimeError("WordPress credentials not configured")
        if "•" in self._app_password:
            raise RuntimeError(
                "WordPress app_password contient des caractères masqués (•). "
                "Veuillez saisir le vrai mot de passe d'application dans les paramètres."
            )

        # Encode as UTF-8 base64 to support all characters (HTTPBasicAuth uses latin-1 by default)
        credentials = base64.b64encode(
            f"{self._username}:{self._app_password}".encode("utf-8")
        ).decode("ascii")

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        })
        return session

    def test_connection(self) -> AccountActionResult:
        """Teste la connexion en recuperant /wp-json/wp/v2/users/me."""
        try:
            session = self._get_session()
            resp = session.get(
                f"{self._site_url}/wp-json/wp/v2/users/me",
                params={"context": "edit"},
                timeout=15,
            )
            resp.raise_for_status()
            user_data = resp.json()
            return AccountActionResult(
                success=True,
                message=f"Connecte en tant que {user_data.get('slug', self._username)}",
                details={"username": user_data.get("slug", self._username)},
            )
        except Exception as exc:
            logger.error("[WordPress] test_connection failed: %s", exc)
            return AccountActionResult(success=False, message=str(exc))

    def _is_configured(self) -> bool:
        return bool(self._site_url and self._username and self._app_password)

    def search_user(self, email: str) -> Optional[dict]:
        """Search WordPress user by email. Returns normalized user dict or None."""
        if not self._is_configured():
            return None
        try:
            session = self._get_session()
            resp = session.get(
                f"{self._site_url}/wp-json/wp/v2/users",
                params={"search": email, "per_page": 5, "context": "edit"},
                timeout=15,
            )
            resp.raise_for_status()
            users = resp.json()
            # Exact email match (context=edit retourne le champ email)
            for user in users:
                if user.get("email", "").lower() == email.lower():
                    return user
            # Fallback : n'utiliser users[0] que si un seul résultat (sinon trop risqué)
            if len(users) == 1:
                return users[0]
        except Exception as exc:
            logger.error("[WordPress] search_user(%s) failed: %s", email, exc)
        return None

    def search_user_by_username(self, username: str) -> Optional[dict]:
        """Fallback search by username/slug."""
        if not self._is_configured():
            return None
        try:
            session = self._get_session()
            resp = session.get(
                f"{self._site_url}/wp-json/wp/v2/users",
                params={"search": username, "per_page": 5},
                timeout=15,
            )
            resp.raise_for_status()
            users = resp.json()
            for user in users:
                if user.get("slug", "").lower() == username.lower():
                    return user
            if users:
                return users[0]
        except Exception as exc:
            logger.error("[WordPress] search_user_by_username(%s) failed: %s", username, exc)
        return None

    def reset_password(self, user_id, new_password: str) -> AccountActionResult:
        """Reset a WordPress user's password."""
        if not self._is_configured():
            return AccountActionResult(success=False, message="WordPress credentials not configured")
        try:
            session = self._get_session()
            resp = session.post(
                f"{self._site_url}/wp-json/wp/v2/users/{user_id}",
                json={"password": new_password},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("[WordPress] Password reset for user_id=%s", user_id)
            return AccountActionResult(success=True, message="Mot de passe reinitialise")
        except Exception as exc:
            logger.error("[WordPress] reset_password(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))

    def update_email(self, user_id, new_email: str) -> AccountActionResult:
        """Update a WordPress user's email."""
        if not self._is_configured():
            return AccountActionResult(success=False, message="WordPress credentials not configured")
        try:
            session = self._get_session()
            resp = session.post(
                f"{self._site_url}/wp-json/wp/v2/users/{user_id}",
                json={"email": new_email},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("[WordPress] Email updated for user_id=%s -> %s", user_id, new_email)
            return AccountActionResult(success=True, message=f"Email mis a jour vers {new_email}")
        except Exception as exc:
            logger.error("[WordPress] update_email(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))

    def get_user_details(self, user_id: int) -> Optional[dict]:
        """Fetch full user profile."""
        if not self._is_configured():
            return None
        try:
            session = self._get_session()
            resp = session.get(
                f"{self._site_url}/wp-json/wp/v2/users/{user_id}",
                params={"context": "edit"},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("[WordPress] get_user_details(%d) failed: %s", user_id, exc)
            return None


# ── Module-level backward-compatible functions ────────────────────────────────
# Used by existing imports in account_agent.py and smart_routing.py

def _get_legacy_provider() -> WordPressAccountProvider:
    """Create a provider from legacy config/env."""
    site_url, username, app_password = _get_effective_creds()
    return WordPressAccountProvider(site_url, username, app_password)


def search_user(email: str) -> Optional[dict]:
    """Backward-compatible module-level function."""
    return _get_legacy_provider().search_user(email)


def search_user_by_username(username: str) -> Optional[dict]:
    """Backward-compatible module-level function."""
    return _get_legacy_provider().search_user_by_username(username)


def reset_password(user_id: int, new_password: str) -> bool:
    """Backward-compatible module-level function (returns bool for compat)."""
    result = _get_legacy_provider().reset_password(user_id, new_password)
    return result.success


def update_email(user_id: int, new_email: str) -> bool:
    """Backward-compatible module-level function (returns bool for compat)."""
    result = _get_legacy_provider().update_email(user_id, new_email)
    return result.success


def get_user_details(user_id: int) -> Optional[dict]:
    """Backward-compatible module-level function."""
    return _get_legacy_provider().get_user_details(user_id)
