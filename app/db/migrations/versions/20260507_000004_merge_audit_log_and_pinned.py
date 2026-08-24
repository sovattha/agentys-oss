# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Merge ``024_add_quick_step_audit_log`` with the orphan ``018_add_pinned_email_ids``.

The Alembic graph carried two parallel heads since 2026-05-07:

  - 017_add_recipient_profiles → 018_add_pinned_email_ids
  - 020_add_draft_feedback → 021_*  → 022_merge_021_heads → 023_add_quick_step_executions → 024_add_quick_step_audit_log

The 018 revision was authored on the same day as the 022 merge but never
folded back in. ``alembic upgrade head`` refuses to proceed while the
graph has multiple heads, blocking the next deploy. This is a no-op
merge: both upgrades have already run on every environment that's
current — only the metadata needs reconciling.

Revision ID: 025_merge_audit_log_and_pinned
Revises: 024_add_quick_step_audit_log, 018_add_pinned_email_ids
Create Date: 2026-05-07 00:00:04
"""
from typing import Sequence, Union


revision: str = "025_merge_audit_log_and_pinned"
down_revision: Union[str, Sequence[str], None] = (
    "024_add_quick_step_audit_log",
    "018_add_pinned_email_ids",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
