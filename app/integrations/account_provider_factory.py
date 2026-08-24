# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Factory pour creer le bon AccountProvider selon la configuration."""

import logging

from app.interfaces.account_provider import AccountProvider

logger = logging.getLogger(__name__)


def create_account_provider(config: dict) -> AccountProvider:
    """
    Cree un AccountProvider selon le provider actif dans la config.

    Args:
        config: Configuration de l'agent account (avec cle "provider" et "providers").

    Returns:
        Instance du provider correspondant.

    Raises:
        ValueError: Si le provider est inconnu.
    """
    provider = config.get("provider", "wordpress")
    providers_cfg = config.get("providers", {})
    provider_cfg = providers_cfg.get(provider, {})

    if provider == "wordpress":
        from app.integrations.wordpress_client import WordPressAccountProvider
        return WordPressAccountProvider(
            site_url=provider_cfg.get("site_url", ""),
            username=provider_cfg.get("username", ""),
            app_password=provider_cfg.get("app_password", ""),
        )

    if provider == "shopify":
        from app.integrations.shopify_client import ShopifyAccountProvider
        return ShopifyAccountProvider(
            shop_domain=provider_cfg.get("shop_domain", ""),
            admin_api_token=provider_cfg.get("admin_api_token", ""),
        )

    if provider == "custom":
        from app.integrations.custom_api_client import CustomAPIAccountProvider
        return CustomAPIAccountProvider(provider_cfg)

    raise ValueError(f"Fournisseur inconnu : {provider}")
