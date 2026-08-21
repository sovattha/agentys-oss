# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""HTTP error response helper.

Audit 2026-05-18 sweep: the codebase used to scatter
``jsonify({"error": "<hardcoded French>"})`` across ~30 sites in
``app/api/**``. The frontend at ``agentys-app/src/services/api.ts``
surfaces ``data.error`` directly to user-visible error toasts, so those
French strings leaked into the en/es/de UIs.

This helper makes every backend error response carry both:

  - ``error_code``  — an UPPER_SNAKE_CASE identifier the frontend uses
    to look up the localized message via ``i18n.t("errors:<code>")``.
  - ``error``       — an English fallback. Old FE deploys that don't
    know to look at ``error_code`` show English instead of French,
    which is still better than the legacy.
  - ``error_context`` (optional) — a JSON-serializable dict of
    interpolation values for the i18n template (e.g. ``{status: "sent"}``
    feeds into ``"Status {{status}}: not editable"``).

The status code is unchanged from the previous ``jsonify(...), status``
contract, so error-status assertions in tests still pass.

Usage:

    from app.api.utils.errors import error_response

    return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    return error_response(
        "SCHEDULED_STATUS_NOT_EDITABLE",
        f"Status {status}: not editable",
        409,
        context={"status": status},
    )
"""
from __future__ import annotations

from typing import Any, Mapping

from flask import jsonify


def error_response(
    code: str,
    message_en: str,
    status: int,
    *,
    context: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
):
    """Build a Flask ``(jsonify(...), status)`` tuple with a localizable error.

    Args:
        code: UPPER_SNAKE_CASE identifier matching an i18n key in
            ``agentys-app/src/i18n/locales/<lng>/errors.json``. Lowercased
            by the FE for the lookup.
        message_en: English fallback message — what old FE deploys (or
            non-Tauri API consumers) will display verbatim.
        status: HTTP status code.
        context: Optional interpolation values for the i18n template
            (e.g. ``{"status": "sent"}`` for ``"Status {{status}}..."``).
        extra: Optional extra fields to merge into the JSON body
            (e.g. ``{"retryable": False, "email_id": "abc"}``).

    Returns:
        ``(Response, status)`` tuple suitable for ``return error_response(...)``
        from a Flask route.
    """
    payload: dict[str, Any] = {"error_code": code, "error": message_en}
    if context:
        payload["error_context"] = dict(context)
    if extra:
        payload.update(extra)
    return jsonify(payload), status
