# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Utilitaires partagés pour Agentys.

Modules disponibles :
- email_cleaner : Nettoyage et validation des contenus email
- json_parser : Parsing JSON sécurisé avec gestion d'erreurs
- signature : Gestion des signatures email
"""

from app.utils.json_parser import (
    safe_json_parse,
    safe_json_parse_list,
    extract_json_from_response,
    to_json_string,
)
from app.utils.signature import (
    get_account_signature,
    get_contact_signature,
    append_signature,
    fetch_and_store_signature,
)

__all__ = [
    "safe_json_parse",
    "safe_json_parse_list",
    "extract_json_from_response",
    "to_json_string",
    "get_account_signature",
    "get_contact_signature",
    "append_signature",
    "fetch_and_store_signature",
]
