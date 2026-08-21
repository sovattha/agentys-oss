"""
Shared validation for bulk email endpoints.

Extracts the repetitive ``require_json`` → ``email_ids`` validation block
that appears in every ``/emails/bulk-*`` route.
"""
from __future__ import annotations

from typing import Tuple, Optional

from flask import jsonify


def validate_bulk_email_ids(
    data: dict,
    *,
    max_ids: int = 100,
    action_label: str = "process",
    validate_id_fn=None,
    sanitize_fn=None,
) -> Tuple[Optional[list], Optional[tuple]]:
    """Validate the ``email_ids`` field from a parsed JSON body.

    Parameters
    ----------
    data:
        Parsed JSON body (dict).
    max_ids:
        Maximum number of IDs allowed in a single request.
    action_label:
        Human-readable verb used in the "Cannot {action_label} more than …"
        error message.
    validate_id_fn:
        Optional callable ``(str) -> bool``.  When provided, every ID in the
        list is checked.  Return ``False`` to reject.
    sanitize_fn:
        Optional callable ``(str) -> str`` used to sanitize an invalid ID
        before including it in the error response.

    Returns
    -------
    (email_ids, None)
        On success — the validated list and ``None`` for the error.
    (None, (response, status_code))
        On failure — ``None`` for the IDs and a Flask JSON error tuple.
    """
    email_ids = data.get("email_ids")

    if not email_ids or not isinstance(email_ids, list):
        return None, (jsonify({"error": "email_ids must be a non-empty list"}), 400)

    if len(email_ids) > max_ids:
        return None, (
            jsonify({"error": f"Cannot {action_label} more than {max_ids} emails at once"}),
            400,
        )

    if validate_id_fn is not None:
        for eid in email_ids:
            if not validate_id_fn(eid):
                display = sanitize_fn(eid) if sanitize_fn else eid
                return None, (
                    jsonify({"error": f"Invalid email_id format: {display}"}),
                    400,
                )

    return email_ids, None
