# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Factory pour créer les adaptateurs calendrier.

Permet de créer le bon adaptateur calendrier en fonction du type de compte
(Gmail/Outlook) et réutilise les tokens OAuth existants.
"""

import logging
from typing import Optional

from app.interfaces.calendar_provider import CalendarProvider, CalendarScopeError
from app.providers.gmail_calendar import GmailCalendarAdapter
from app.providers.outlook_calendar import OutlookCalendarAdapter

# Calendar scopes we check for in stored tokens
GOOGLE_CALENDAR_SCOPES = {
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar",
}
OUTLOOK_CALENDAR_SCOPES = {
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Calendars.ReadWrite",
}

logger = logging.getLogger(__name__)


def create_calendar_provider(
    account_id: str,
    provider_type: Optional[str] = None
) -> Optional[CalendarProvider]:
    """
    Crée un adaptateur calendrier pour un compte donné.

    Args:
        account_id: ID du compte (utilisé pour récupérer les tokens).
        provider_type: Type de provider ('gmail' ou 'outlook').
                       Si None, sera déduit des tokens stockés.

    Returns:
        Instance de CalendarProvider ou None si non supporté.
    """
    try:
        # Si le type n'est pas spécifié, le déduire des tokens
        if not provider_type:
            from app.api.oauth import get_tokens_server
            token_data = get_tokens_server(account_id)
            if token_data:
                provider_type = token_data.get("provider")

        if not provider_type:
            logger.warning(f"Impossible de déterminer le provider pour {account_id}")
            return None

        # Pre-check: verify tokens contain calendar scopes
        from app.api.oauth import get_tokens_server
        token_data = get_tokens_server(account_id)
        if token_data:
            scopes_str = token_data.get("scope", "")
            scope_set = set(scopes_str.split()) if scopes_str else set()

            required = GOOGLE_CALENDAR_SCOPES if provider_type == "gmail" else OUTLOOK_CALENDAR_SCOPES
            if not scope_set & required:
                logger.warning(
                    f"Account {account_id} ({provider_type}) missing calendar scopes. "
                    f"Has: {scope_set}, needs one of: {required}"
                )
                raise CalendarScopeError(account_id=account_id, provider=provider_type)

        # Créer l'adaptateur approprié
        if provider_type == "gmail":
            provider = GmailCalendarAdapter(account_id=account_id)
        elif provider_type == "outlook":
            provider = OutlookCalendarAdapter(account_id=account_id)
        else:
            logger.warning(f"Provider calendrier non supporté: {provider_type}")
            return None

        # Authentifier
        if provider.authenticate():
            return provider
        else:
            logger.warning(f"Échec authentification calendrier pour {account_id}")
            return None

    except CalendarScopeError:
        raise  # Let CalendarScopeError propagate
    except Exception as e:
        logger.warning(f"Erreur création provider calendrier: {e}")
        return None


def get_calendar_provider_for_account(account_id: str) -> Optional[CalendarProvider]:
    """
    Raccourci pour obtenir un provider calendrier authentifié.

    Args:
        account_id: ID du compte.

    Returns:
        CalendarProvider authentifié ou None.
    """
    return create_calendar_provider(account_id)


def supports_calendar(provider_type: str) -> bool:
    """
    Vérifie si un type de provider supporte le calendrier.

    Args:
        provider_type: Type de provider (gmail, outlook, imap_smtp).

    Returns:
        True si le calendrier est supporté.
    """
    return provider_type in ("gmail", "outlook")
