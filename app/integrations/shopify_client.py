# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shopify Admin API client — search customers, send password reset, update email."""

import logging
from typing import Optional

from app.interfaces.account_provider import AccountActionResult, AccountProvider

logger = logging.getLogger(__name__)


class ShopifyAccountProvider(AccountProvider):
    """Fournisseur de gestion de comptes Shopify via Admin API."""

    def __init__(self, shop_domain: str = "", admin_api_token: str = ""):
        self._shop_domain = shop_domain.rstrip("/")
        self._token = admin_api_token

    @property
    def provider_name(self) -> str:
        return "shopify"

    @property
    def _base_url(self) -> str:
        domain = self._shop_domain
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return f"{domain}/admin/api/2024-01"

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
        }

    def test_connection(self) -> AccountActionResult:
        """Teste la connexion en recuperant les infos du shop."""
        try:
            import requests
            resp = requests.get(
                f"{self._base_url}/shop.json",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            shop = resp.json().get("shop", {})
            return AccountActionResult(
                success=True,
                message=f"Connecte a {shop.get('name', self._shop_domain)}",
            )
        except Exception as exc:
            logger.error("[Shopify] test_connection failed: %s", exc)
            return AccountActionResult(success=False, message=str(exc))

    def search_user(self, email: str) -> Optional[dict]:
        """Recherche un client Shopify par email."""
        try:
            import requests
            resp = requests.get(
                f"{self._base_url}/customers/search.json",
                headers=self._headers(),
                params={"query": f"email:{email}"},
                timeout=15,
            )
            resp.raise_for_status()
            customers = resp.json().get("customers", [])
            for c in customers:
                if c.get("email", "").lower() == email.lower():
                    return {
                        "id": c["id"],
                        "username": c.get("email", ""),
                        "email": c.get("email", ""),
                        "display_name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                        "slug": c.get("email", ""),
                    }
            if customers:
                c = customers[0]
                return {
                    "id": c["id"],
                    "username": c.get("email", ""),
                    "email": c.get("email", ""),
                    "display_name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                    "slug": c.get("email", ""),
                }
        except Exception as exc:
            logger.error("[Shopify] search_user(%s) failed: %s", email, exc)
        return None

    def reset_password(self, user_id, new_password: str) -> AccountActionResult:
        """Envoie un lien de réinitialisation (Shopify ne permet pas de definir un mdp directement)."""
        try:
            import requests
            resp = requests.post(
                f"{self._base_url}/customers/{user_id}/send_invite.json",
                headers=self._headers(),
                json={"customer_invite": {}},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("[Shopify] Password reset invite sent for customer_id=%s", user_id)
            return AccountActionResult(
                success=True,
                message="Lien de réinitialisation envoyé par email",
                method="reset_link",
            )
        except Exception as exc:
            logger.error("[Shopify] reset_password(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))

    def update_email(self, user_id, new_email: str) -> AccountActionResult:
        """Met a jour l'email d'un client Shopify."""
        try:
            import requests
            resp = requests.put(
                f"{self._base_url}/customers/{user_id}.json",
                headers=self._headers(),
                json={"customer": {"email": new_email}},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("[Shopify] Email updated for customer_id=%s -> %s", user_id, new_email)
            return AccountActionResult(
                success=True,
                message=f"Email mis a jour vers {new_email}",
            )
        except Exception as exc:
            logger.error("[Shopify] update_email(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))
