# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Décorateur @account_scoped pour routes Flask.

Résout l'account_id de l'utilisateur authentifié (JWT ou singleton Tauri)
et l'injecte dans `g.account_id`. Court-circuite la vue avec 401/404 si
aucun compte ne peut être résolu, au lieu de retourner des données fuitées
ou une erreur vague.

Usage:
    from app.api.account_scope import account_scoped

    @api_bp.route("/drafts", methods=["GET"])
    @account_scoped
    def list_drafts():
        # g.account_id est garanti > 0 ici
        drafts = get_draft_history().get_all_for_account(g.account_id)
        ...

Pattern: le décorateur DOIT être appliqué APRÈS @api_bp.route() dans le
stack (donc placé juste en dessous), sinon Flask enregistre la vue non
décorée.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, jsonify


def account_scoped(view: Callable) -> Callable:
    """Injecte `g.account_id` depuis le JWT (ou singleton Tauri).

    Renvoie 401 JSON si aucun compte n'est résolu — safer default que
    laisser la vue retourner des données fuitées. Les ressources
    account-scoped DOIVENT utiliser `g.account_id` dans leurs queries.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        # Import tardif pour éviter les cycles d'import.
        import app.api.routes_helpers as _rh

        account_id = _rh._resolve_account_id_for_user()
        if not account_id or account_id <= 0:
            # Audit Cluster C (2026-05-11) U-11: distinguish "JWT valid but
            # user has no account yet" (just-signed-up, needs to run the
            # wizard) from "no auth at all". The frontend used to see
            # NO_ACCOUNT_SCOPE for both and could not tell whether to
            # redirect to /wizard or to /login. ONBOARDING_REQUIRED lets
            # the UI branch on first paint without a flash of 401 toasts.
            auth_user = getattr(g, "auth_user", None)
            if auth_user and auth_user.get("email"):
                return jsonify({
                    "error": "Onboarding required",
                    "code": "ONBOARDING_REQUIRED",
                }), 401
            return jsonify({
                "error": "Account not found",
                "code": "NO_ACCOUNT_SCOPE",
            }), 401

        g.account_id = account_id
        return view(*args, **kwargs)

    return wrapper


def require_matching_account_header(view: Callable) -> Callable:
    """Double-vérification : le header X-Account-Id DOIT correspondre au JWT.

    À combiner avec @account_scoped. Empêche les attaques de type
    "JWT de A + header X-Account-Id de B" où un client malveillant
    tenterait de tromper le backend en mixant les deux sources de vérité.

    Comportement :
      - Si X-Account-Id est absent : laisse passer (compat ascendante).
      - Si présent et différent de g.account_id : 403.

    À activer strictement après que tous les clients frontend envoient
    systématiquement le header (voir Phase 4).
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        from flask import request

        header_value = request.headers.get("X-Account-Id")
        if header_value:
            try:
                header_id = int(header_value)
            except (TypeError, ValueError):
                return jsonify({
                    "error": "Invalid X-Account-Id header",
                    "code": "INVALID_ACCOUNT_HEADER",
                }), 400
            if getattr(g, "account_id", None) != header_id:
                return jsonify({
                    "error": "Account mismatch between JWT and X-Account-Id",
                    "code": "ACCOUNT_HEADER_MISMATCH",
                }), 403

        return view(*args, **kwargs)

    return wrapper
