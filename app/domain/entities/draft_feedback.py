# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Domain entity for explicit user feedback on AI drafts (audit 2026-05-05).

Pure POPO — no DB dependencies. The repository layer (
:mod:`app.db.repositories.draft_feedback_repository`) is responsible for
persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class FeedbackAction(str, Enum):
    """User's explicit verdict on a generated draft.

    - ``ACCEPT`` : sent as-is. Strongest positive signal.
    - ``EDIT``   : sent a modified version. ``edit_distance`` quantifies how much.
    - ``REJECT`` : dismissed without sending (or sent something unrelated).
                   Strongest negative signal — Critic tuner weighs these higher
                   than edits.
    """

    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


@dataclass
class DraftFeedback:
    account_id: int
    draft_id: str
    action: FeedbackAction
    edit_distance: Optional[float] = None
    intent: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Defensive: route programmatic strings through the enum.
        if isinstance(self.action, str) and not isinstance(self.action, FeedbackAction):
            self.action = FeedbackAction(self.action)
        if self.edit_distance is not None:
            # Clamp to [0, 1]. Out-of-range values are a calling-side bug —
            # we'd rather store a clamped-but-truthful value than reject.
            self.edit_distance = max(0.0, min(1.0, float(self.edit_distance)))
        if self.note is not None and len(self.note) > 1024:
            self.note = self.note[:1024]
