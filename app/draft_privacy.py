# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Privacy helpers for persisted draft diagnostics."""

from __future__ import annotations

from typing import Any

DRAFT_FREE_TEXT_FIELDS = (
    "generation_prompt",
    "user_edits",
    "feedback_notes",
)


def minimize_draft_free_text_fields(draft: Any) -> Any:
    """Drop durable free-text diagnostics from a Draft-like object."""
    for field in DRAFT_FREE_TEXT_FIELDS:
        if hasattr(draft, field):
            setattr(draft, field, None)
    return draft


def hide_draft_free_text_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Mask free-text diagnostics in serialized Draft output."""
    for field in DRAFT_FREE_TEXT_FIELDS:
        if field in data:
            data[field] = None
    return data
