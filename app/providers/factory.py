# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Factory pour la sélection du fournisseur d'email.

Ce module fournit une fonction factory qui retourne l'implémentation
appropriée de EmailProvider selon la configuration.
"""

import os
import logging
from typing import Optional

from app.interfaces.email_provider import EmailProvider

logger = logging.getLogger(__name__)

# Types de providers supportés
PROVIDER_OUTLOOK = "OUTLOOK"
PROVIDER_GMAIL = "GMAIL"
PROVIDER_IMAP = "IMAP"
PROVIDER_SMTP = "SMTP"
PROVIDER_IMAP_SMTP = "IMAP_SMTP"

# Provider par défaut
DEFAULT_PROVIDER = PROVIDER_OUTLOOK


class ProviderNotImplementedError(NotImplementedError):
    """Exception levée quand un provider n'est pas encore implémenté."""
    pass


class ProviderConfigurationError(ValueError):
    """Exception levée quand la configuration du provider est invalide."""
    pass


def get_email_provider(
    provider_type: Optional[str] = None,
    **kwargs
) -> EmailProvider:
    """
    Factory pour obtenir une instance du fournisseur d'email.

    Le type de provider est déterminé par :
    1. Le paramètre provider_type s'il est fourni
    2. La variable d'environnement EMAIL_PROVIDER_TYPE
    3. Le provider par défaut (OUTLOOK)

    Args:
        provider_type: Type de provider ("OUTLOOK", "GMAIL", etc.)
        **kwargs: Arguments supplémentaires passés au constructeur du provider

    Returns:
        Instance de EmailProvider configurée

    Raises:
        ProviderNotImplementedError: Si le provider n'est pas encore implémenté
        ProviderConfigurationError: Si la configuration est invalide

    Examples:
        >>> provider = get_email_provider()  # Utilise EMAIL_PROVIDER_TYPE ou défaut
        >>> provider = get_email_provider("OUTLOOK")
        >>> provider = get_email_provider("OUTLOOK", use_device_code=True)
    """
    # Déterminer le type de provider
    if provider_type is None:
        provider_type = os.getenv("EMAIL_PROVIDER_TYPE", DEFAULT_PROVIDER)

    provider_type = provider_type.upper().strip()

    logger.info(f"[INIT] Initialisation du provider: {provider_type}")

    # Sélection du provider
    if provider_type == PROVIDER_OUTLOOK:
        return _create_outlook_provider(**kwargs)

    elif provider_type == PROVIDER_GMAIL:
        return _create_gmail_provider(**kwargs)

    elif provider_type == PROVIDER_IMAP:
        return _create_imap_provider(**kwargs)

    elif provider_type == PROVIDER_SMTP:
        return _create_smtp_provider(**kwargs)

    elif provider_type == PROVIDER_IMAP_SMTP:
        return _create_imap_smtp_provider(**kwargs)

    else:
        available = [PROVIDER_OUTLOOK, PROVIDER_GMAIL, PROVIDER_IMAP, PROVIDER_SMTP, PROVIDER_IMAP_SMTP]
        raise ProviderConfigurationError(
            f"Provider inconnu: '{provider_type}'. "
            f"Providers disponibles: {available}"
        )


def _create_outlook_provider(**kwargs) -> EmailProvider:
    """
    Crée et configure une instance de OutlookAdapter.

    Args:
        **kwargs: Arguments passés au constructeur de OutlookAdapter

    Returns:
        Instance de OutlookAdapter configurée
    """
    from app.providers.outlook_adapter import OutlookAdapter

    try:
        provider = OutlookAdapter(**kwargs)
        logger.info("[OK] OutlookAdapter créé avec succès")
        return provider

    except ValueError as e:
        raise ProviderConfigurationError(
            f"Configuration Outlook invalide: {e}. "
            "Vérifiez les variables AZURE_TENANT_ID, AZURE_CLIENT_ID, etc."
        )


def _create_gmail_provider(**kwargs) -> EmailProvider:
    """
    Crée et configure une instance de GmailAdapter.

    Args:
        **kwargs: Arguments passés au constructeur de GmailAdapter

    Returns:
        Instance de GmailAdapter configurée
    """
    from app.providers.gmail_adapter import GmailAdapter

    try:
        provider = GmailAdapter(**kwargs)
        logger.info("[OK] GmailAdapter créé avec succès")
        return provider

    except ValueError as e:
        raise ProviderConfigurationError(
            f"Configuration Gmail invalide: {e}. "
            "Vérifiez les variables GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, etc."
        )


def _create_imap_provider(**kwargs) -> EmailProvider:
    """
    Crée et configure une instance de IMAPAdapter.

    Args:
        **kwargs: Arguments passés au constructeur de IMAPAdapter

    Returns:
        Instance de IMAPAdapter configurée
    """
    from app.providers.imap_adapter import IMAPAdapter

    try:
        provider = IMAPAdapter(**kwargs)
        logger.info("[OK] IMAPAdapter créé avec succès")
        return provider

    except ValueError as e:
        raise ProviderConfigurationError(
            f"Configuration IMAP invalide: {e}. "
            "Vérifiez les variables IMAP_HOST, IMAP_USER, IMAP_PASSWORD, etc."
        )


def _create_smtp_provider(**kwargs) -> EmailProvider:
    """
    Crée et configure une instance de SMTPAdapter.

    Args:
        **kwargs: Arguments passés au constructeur de SMTPAdapter

    Returns:
        Instance de SMTPAdapter configurée
    """
    from app.providers.smtp_adapter import SMTPAdapter

    try:
        provider = SMTPAdapter(**kwargs)
        logger.info("[OK] SMTPAdapter créé avec succès")
        return provider

    except ValueError as e:
        raise ProviderConfigurationError(
            f"Configuration SMTP invalide: {e}. "
            "Vérifiez les variables SMTP_HOST, SMTP_USER, SMTP_PASSWORD, etc."
        )


def _create_imap_smtp_provider(**kwargs) -> EmailProvider:
    """
    Crée et configure une instance de IMAPSMTPAdapter (combiné).

    Args:
        **kwargs: Arguments passés au constructeur de IMAPSMTPAdapter

    Returns:
        Instance de IMAPSMTPAdapter configurée
    """
    from app.providers.smtp_adapter import IMAPSMTPAdapter

    # Filter out OAuth/account-specific parameters that IMAP/SMTP doesn't need
    filtered_kwargs = {
        k: v for k, v in kwargs.items()
        if k not in ('account_id', 'refresh_token', 'access_token', 'token_expires_at', 'credentials_path')
    }

    try:
        provider = IMAPSMTPAdapter(**filtered_kwargs)
        logger.info("[OK] IMAPSMTPAdapter créé avec succès")
        return provider

    except ValueError as e:
        raise ProviderConfigurationError(
            f"Configuration IMAP/SMTP invalide: {e}. "
            "Vérifiez les variables IMAP_* et SMTP_*."
        )


def get_pooled_provider(
    account_id: str = "default",
    provider_type: Optional[str] = None,
    **kwargs
) -> EmailProvider:
    """
    Get an email provider from the connection pool.

    All providers (including IMAP) are pooled with health checks.
    IMAP uses a shorter TTL (120s) and SELECT-based health checking
    to detect buffer desync issues.

    Args:
        account_id: Unique identifier for the account (for multi-account support).
        provider_type: Type of provider (OUTLOOK, GMAIL, IMAP, etc.).
        **kwargs: Additional arguments passed to provider constructor.

    Returns:
        Authenticated EmailProvider.
    """
    from app.providers.provider_pool import ProviderPool

    pool = ProviderPool.get_instance()

    def factory_fn() -> EmailProvider:
        # Try OAuth account lookup when account_id is provided without explicit provider_type
        if account_id != "default" and provider_type is None:
            try:
                from app.multi_accounts import get_account_manager, create_provider_for_account
                mgr = get_account_manager()
                account = mgr.get_account(account_id)
                if account:
                    logger.info(f"[POOL] Création provider OAuth pour compte {account_id} (type={account.provider})")
                    return create_provider_for_account(account)
            except Exception as e:
                # Do NOT fallback to env provider — would cache wrong provider under this account_id
                raise RuntimeError(f"Cannot create provider for account {account_id}: {e}") from e
            raise RuntimeError(f"Account {account_id} not found — refusing to fallback to env provider")
        # Default/legacy: use environment-based provider (only for account_id="default")
        return get_email_provider(provider_type=provider_type, **kwargs)

    return pool.get_or_create(account_id, factory_fn)


def list_available_providers() -> dict:
    """
    Liste les providers disponibles et leur statut.

    Returns:
        Dictionnaire {nom: statut} des providers
    """
    return {
        PROVIDER_OUTLOOK: "disponible",
        PROVIDER_GMAIL: "disponible",
        PROVIDER_IMAP: "disponible (lecture seule)",
        PROVIDER_SMTP: "disponible (envoi seul)",
        PROVIDER_IMAP_SMTP: "disponible (lecture + envoi)",
    }


def validate_provider_config(provider_type: str) -> dict:
    """
    Valide la configuration pour un type de provider.

    Args:
        provider_type: Type de provider à valider

    Returns:
        Dictionnaire avec le statut de chaque variable requise
    """
    provider_type = provider_type.upper().strip()

    from app.config import is_env_set
    if provider_type == PROVIDER_OUTLOOK:
        return {
            "AZURE_TENANT_ID": is_env_set("AZURE_TENANT_ID"),
            "AZURE_CLIENT_ID": is_env_set("AZURE_CLIENT_ID"),
            "AZURE_CLIENT_SECRET": is_env_set("AZURE_CLIENT_SECRET"),
            "OUTLOOK_USER_ID": is_env_set("OUTLOOK_USER_ID"),
        }

    elif provider_type == PROVIDER_GMAIL:
        return {
            "GOOGLE_CLIENT_ID": is_env_set("GOOGLE_CLIENT_ID"),
            "GOOGLE_CLIENT_SECRET": is_env_set("GOOGLE_CLIENT_SECRET"),
            "GOOGLE_REFRESH_TOKEN": is_env_set("GOOGLE_REFRESH_TOKEN"),
        }

    elif provider_type == PROVIDER_IMAP:
        return {
            "IMAP_HOST": bool(os.getenv("IMAP_HOST")),
            "IMAP_USER": bool(os.getenv("IMAP_USER")),
            "IMAP_PASSWORD": bool(os.getenv("IMAP_PASSWORD")),
        }

    elif provider_type == PROVIDER_SMTP:
        return {
            "SMTP_HOST": bool(os.getenv("SMTP_HOST")),
            "SMTP_USER": bool(os.getenv("SMTP_USER")),
            "SMTP_PASSWORD": bool(os.getenv("SMTP_PASSWORD")),
        }

    elif provider_type == PROVIDER_IMAP_SMTP:
        return {
            "IMAP_HOST": bool(os.getenv("IMAP_HOST")),
            "IMAP_USER": bool(os.getenv("IMAP_USER")),
            "IMAP_PASSWORD": bool(os.getenv("IMAP_PASSWORD")),
            "SMTP_HOST": bool(os.getenv("SMTP_HOST")),
            "SMTP_USER": bool(os.getenv("SMTP_USER")),
            "SMTP_PASSWORD": bool(os.getenv("SMTP_PASSWORD")),
        }

    return {}
