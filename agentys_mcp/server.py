# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Serveur MCP (Model Context Protocol) pour Agentys.

Ce serveur expose les fonctionnalités email de manière agnostique.
Il utilise la factory pour obtenir le provider configuré, sans jamais
importer directement les adaptateurs spécifiques.

Les outils exposés :
- list_emails : Liste les emails non lus
- get_email : Récupère un email par ID
- draft_reply : Crée un brouillon de réponse
- send_email : Envoie un email
- mark_read : Marque un email comme lu
"""

import logging
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import via la factory - JAMAIS d'import direct des adaptateurs
from app.providers.factory import get_email_provider, ProviderConfigurationError
from app.interfaces.email_provider import EmailProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Instance du serveur MCP
server = Server("agentys-email")

# Provider email (initialisé au démarrage)
_email_provider: Optional[EmailProvider] = None


def get_provider() -> EmailProvider:
    """
    Retourne le provider email, l'initialise si nécessaire.

    Le provider est créé via la factory, garantissant le découplage.
    """
    global _email_provider

    if _email_provider is None:
        try:
            _email_provider = get_email_provider()
            _email_provider.authenticate()
        except ProviderConfigurationError as e:
            logger.error(f"Configuration provider invalide: {e}")
            raise

    return _email_provider


# ============================================================================
# DÉFINITION DES OUTILS MCP
# ============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Liste les outils disponibles."""
    return [
        Tool(
            name="list_emails",
            description="Liste les emails non lus de la boîte de réception",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximum d'emails à récupérer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50
                    }
                }
            }
        ),
        Tool(
            name="get_email",
            description="Récupère le contenu complet d'un email par son ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "ID unique de l'email"
                    }
                },
                "required": ["message_id"]
            }
        ),
        Tool(
            name="draft_reply",
            description="Crée un brouillon de réponse à un email",
            inputSchema={
                "type": "object",
                "properties": {
                    "reply_to_id": {
                        "type": "string",
                        "description": "ID de l'email auquel répondre"
                    },
                    "body": {
                        "type": "string",
                        "description": "Corps de la réponse"
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Adresses email en copie (optionnel)"
                    }
                },
                "required": ["reply_to_id", "body"]
            }
        ),
        Tool(
            name="send_email",
            description="Envoie un nouvel email",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Adresses email des destinataires"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Sujet de l'email"
                    },
                    "body": {
                        "type": "string",
                        "description": "Corps de l'email"
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Adresses en copie (optionnel)"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        ),
        Tool(
            name="mark_read",
            description="Marque un email comme lu",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "ID de l'email à marquer comme lu"
                    }
                },
                "required": ["message_id"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Exécute un outil MCP.

    Le provider est obtenu via la factory, jamais via import direct.
    Toutes les données retournées sont des StandardEmail normalisés.
    """
    provider = get_provider()

    try:
        if name == "list_emails":
            return await _handle_list_emails(provider, arguments)

        elif name == "get_email":
            return await _handle_get_email(provider, arguments)

        elif name == "draft_reply":
            return await _handle_draft_reply(provider, arguments)

        elif name == "send_email":
            return await _handle_send_email(provider, arguments)

        elif name == "mark_read":
            return await _handle_mark_read(provider, arguments)

        else:
            return [TextContent(
                type="text",
                text=f"Outil inconnu: {name}"
            )]

    except Exception as e:
        logger.error(f"Erreur outil {name}: {e}")
        return [TextContent(
            type="text",
            text=f"Erreur: {str(e)}"
        )]


# ============================================================================
# HANDLERS DES OUTILS
# ============================================================================

async def _handle_list_emails(
    provider: EmailProvider,
    arguments: dict
) -> list[TextContent]:
    """Handler pour list_emails."""
    limit = arguments.get("limit", 10)

    emails = provider.get_unread_messages(limit=limit)

    if not emails:
        return [TextContent(
            type="text",
            text="Aucun email non lu trouvé."
        )]

    # Formater la liste des emails
    result = f"📬 {len(emails)} email(s) non lu(s) [{provider.provider_name}]:\n\n"

    for email in emails:
        result += "---\n"
        result += f"ID: {email.id}\n"
        result += f"De: {email.sender_display} <{email.sender}>\n"
        result += f"Sujet: {email.subject}\n"
        result += f"Reçu: {email.received_at}\n"
        result += f"Aperçu: {email.preview}\n"

    return [TextContent(type="text", text=result)]


async def _handle_get_email(
    provider: EmailProvider,
    arguments: dict
) -> list[TextContent]:
    """Handler pour get_email."""
    message_id = arguments["message_id"]

    email = provider.get_message_by_id(message_id)

    if not email:
        return [TextContent(
            type="text",
            text=f"Email non trouvé: {message_id}"
        )]

    # Formater l'email complet
    result = f"📧 Email [{provider.provider_name}]\n\n"
    result += f"ID: {email.id}\n"
    result += f"De: {email.sender_display} <{email.sender}>\n"
    result += f"À: {', '.join(email.to)}\n"
    if email.cc:
        result += f"CC: {', '.join(email.cc)}\n"
    result += f"Sujet: {email.subject}\n"
    result += f"Reçu: {email.received_at}\n"
    result += f"Lu: {'Oui' if email.is_read else 'Non'}\n"
    result += f"Pièces jointes: {'Oui' if email.has_attachments else 'Non'}\n"
    result += f"\n--- Corps ---\n\n{email.body}"

    return [TextContent(type="text", text=result)]


async def _handle_draft_reply(
    provider: EmailProvider,
    arguments: dict
) -> list[TextContent]:
    """Handler pour draft_reply."""
    reply_to_id = arguments["reply_to_id"]
    body = arguments["body"]
    cc = arguments.get("cc", [])

    # Récupérer l'email original pour avoir les destinataires
    original = provider.get_message_by_id(reply_to_id)

    if not original:
        return [TextContent(
            type="text",
            text=f"Email original non trouvé: {reply_to_id}"
        )]

    # Créer le brouillon de réponse
    draft_id = provider.create_draft(
        to=[original.sender],
        subject=f"Re: {original.subject}",
        body=body,
        reply_to_id=reply_to_id,
        cc=cc if cc else None
    )

    if draft_id:
        return [TextContent(
            type="text",
            text=f"✓ Brouillon créé avec succès\n"
                 f"ID: {draft_id}\n"
                 f"En réponse à: {original.sender}\n"
                 f"Sujet: Re: {original.subject}"
        )]
    else:
        return [TextContent(
            type="text",
            text="✗ Échec de la création du brouillon"
        )]


async def _handle_send_email(
    provider: EmailProvider,
    arguments: dict
) -> list[TextContent]:
    """Handler pour send_email.

    FIX AUX-006 (audit P1): the MCP stdio transport has no per-caller
    auth — any local process able to write to the server's stdin can
    invoke this tool and dispatch email as the authenticated mailbox
    owner. Gate the destructive action behind two layers:

      1. AGENTYS_MCP_ALLOW_SEND env var must be truthy. Operators
         opt in explicitly when they want the LLM to send mail.
      2. Optional AGENTYS_MCP_SEND_TO_ALLOWLIST env var (comma-
         separated list of allowed recipient domains). When set,
         any recipient whose domain is not in the list is refused.

    These are best-effort mitigations on a fundamentally local-trust
    transport — the proper fix is a network MCP with mutual auth.
    """
    import os as _os

    if (_os.environ.get("AGENTYS_MCP_ALLOW_SEND", "") or "").lower() not in ("1", "true", "yes"):
        return [TextContent(
            type="text",
            text=(
                "✗ send_email refused: set AGENTYS_MCP_ALLOW_SEND=true in the "
                "MCP server's environment to enable email dispatch via this "
                "transport. (Audit AUX-006: stdio MCP has no per-caller auth.)"
            ),
        )]

    to = arguments["to"]
    subject = arguments["subject"]
    body = arguments["body"]
    cc = arguments.get("cc", [])

    # Optional recipient-domain allowlist.
    raw_allowlist = (_os.environ.get("AGENTYS_MCP_SEND_TO_ALLOWLIST", "") or "").strip()
    if raw_allowlist:
        allowed_domains = {
            d.strip().lower().lstrip("@")
            for d in raw_allowlist.split(",")
            if d.strip()
        }
        all_recipients = list(to) + list(cc or [])
        for addr in all_recipients:
            if "@" not in addr:
                return [TextContent(type="text", text=f"✗ Adresse invalide: {addr}")]
            domain = addr.split("@", 1)[-1].lower()
            if domain not in allowed_domains:
                return [TextContent(
                    type="text",
                    text=(
                        f"✗ send_email refused: recipient domain '{domain}' "
                        "is not in AGENTYS_MCP_SEND_TO_ALLOWLIST."
                    ),
                )]

    success = provider.send_email(
        to=to,
        subject=subject,
        body=body,
        cc=cc if cc else None
    )

    if success:
        return [TextContent(
            type="text",
            text=f"✓ Email envoyé avec succès\n"
                 f"À: {', '.join(to)}\n"
                 f"Sujet: {subject}"
        )]
    else:
        return [TextContent(
            type="text",
            text="✗ Échec de l'envoi de l'email"
        )]


async def _handle_mark_read(
    provider: EmailProvider,
    arguments: dict
) -> list[TextContent]:
    """Handler pour mark_read."""
    message_id = arguments["message_id"]

    success = provider.mark_as_read(message_id)

    if success:
        return [TextContent(
            type="text",
            text=f"✓ Email marqué comme lu: {message_id}"
        )]
    else:
        return [TextContent(
            type="text",
            text=f"✗ Échec du marquage: {message_id}"
        )]


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

async def main():
    """Point d'entrée du serveur MCP."""
    import os as _os

    logger.info("🚀 Démarrage du serveur MCP Agentys...")

    # FIX AUX-006 (audit P1): the stdio transport has no per-caller
    # authentication — any local process able to write to this server's
    # stdin gets full tool access. Surface the trust assumption loudly
    # at startup so operators can't miss it, and reject silently-
    # destructive defaults.
    if (_os.environ.get("AGENTYS_MCP_ALLOW_SEND", "") or "").lower() in ("1", "true", "yes"):
        logger.warning(
            "⚠ AGENTYS_MCP_ALLOW_SEND is enabled — send_email is callable by "
            "any local process able to write to this server's stdin. "
            "If unintended, unset the variable."
        )
    else:
        logger.info(
            "send_email tool is REFUSED at runtime (set AGENTYS_MCP_ALLOW_SEND=true to enable). "
            "Read-only tools (list, get, mark_read, draft) remain available."
        )

    try:
        # Pré-initialiser le provider pour valider la config
        get_provider()
        logger.info("✓ Provider email initialisé")
    except Exception as e:
        logger.warning(f"⚠ Provider non initialisé: {e}")
        logger.info("  Le provider sera initialisé au premier appel")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
