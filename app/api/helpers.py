# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Helpers communs pour les routes API.

Ce module contient des utilitaires partagés entre les différents
blueprints de l'API (mobile, push_notifications, etc.).
"""

import logging
from functools import wraps
from typing import Any, Callable, Tuple

from flask import request, jsonify

_logger = logging.getLogger(__name__)


def require_json(f: Callable) -> Callable:
    """
    Décorateur pour valider la présence d'un body JSON.

    Retourne une erreur 400 si le body JSON est absent ou invalide.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # silent=True so a missing/non-JSON body yields a clean 400 here rather
        # than letting werkzeug raise (which, if the wrapped handler is itself
        # inside a try/except, would surface as a 500) — audit 2026-05-19 STAB-02.
        # Also require an OBJECT: a JSON array/scalar body used to pass the old
        # truthiness check and then blow up on `data.get(...)` inside the handler
        # (AttributeError → 500). Decorated handlers all expect an object body.
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not body:
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


def sanitize_500(
    log_label: str,
    exc: Exception | None = None,
    user_message: str = "Internal server error",
) -> Tuple[Any, int]:
    """Audit 2026-04-25 (sub-report 01 MED-03): generic 500 helper.

    50+ handlers used to return `{"error": str(e)}` which leaks SQLAlchemy
    column names, Anthropic SDK internals, OAuth client_ids, etc. This helper
    logs the full exception (with traceback) and returns a sanitized message
    safe for clients.

    Usage:
        try:
            ...
        except Exception as exc:
            return sanitize_500("update_settings", exc)
    """
    if exc is not None:
        _logger.exception("[%s] %s", log_label, type(exc).__name__)
    else:
        _logger.exception("[%s] unhandled error", log_label)
    return jsonify({"error": user_message}), 500
