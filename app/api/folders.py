# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API pour les dossiers/labels email.

Endpoints disponibles:
- GET /api/folders - Liste des dossiers/labels de l'utilisateur
"""

import logging
from flask import Blueprint, jsonify

from app.providers.factory import get_email_provider, get_pooled_provider
from app.api import routes_helpers as _rh

logger = logging.getLogger(__name__)

folders_bp = Blueprint("folders", __name__)


@folders_bp.route("", methods=["GET"])
def list_folders():
    """
    Liste les dossiers/labels de l'utilisateur.
    ---
    tags:
      - Folders
    summary: Liste les dossiers email
    responses:
      200:
        description: Liste des dossiers
        content:
          application/json:
            schema:
              type: object
              properties:
                provider:
                  type: string
                  description: Type de provider (gmail, outlook, imap)
                count:
                  type: integer
                  description: Nombre de dossiers
                folders:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                      name:
                        type: string
                      display_name:
                        type: string
                      type:
                        type: string
                        enum: [system, user]
                      parent_id:
                        type: string
                        nullable: true
                      unread_count:
                        type: integer
                      total_count:
                        type: integer
      500:
        description: Erreur interne
    """
    provider = None
    try:
        account_id = _rh._resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            return jsonify({"error": "No active account"}), 401

        oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
        if oauth_account_id:
            provider = get_pooled_provider(account_id=oauth_account_id)
        elif _rh._is_web_request_context():
            return jsonify({"error": "No email provider for account"}), 503
        else:
            provider = get_email_provider(account_id=str(account_id))

        # Get folders from provider
        if hasattr(provider, 'list_folders'):
            folders = provider.list_folders()
        else:
            logger.warning(f"Provider {provider.provider_name} does not support list_folders")
            folders = []

        provider_name = provider.provider_name

        return jsonify({
            "provider": provider_name,
            "count": len(folders),
            "folders": [
                {
                    "id": f.id,
                    "name": f.name,
                    "display_name": f.display_name,
                    "type": f.type,
                    "parent_id": f.parent_id,
                    "unread_count": f.unread_count,
                    "total_count": f.total_count,
                }
                for f in folders
            ],
        })

    except Exception as e:
        logger.warning(f"Error listing folders: {e}")
        return jsonify({"error": "Failed to list folders"}), 500
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception:
                pass
