# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stable account identity helpers shared by auth and OAuth paths."""

from __future__ import annotations

import hashlib


def user_id_from_email(email: str) -> int:
    """Stable user_id derived from sha256(email)[:8] interpreted as int.

    Returns a 32-bit unsigned integer (range 0 .. 2**32 - 1). Idempotent
    on lowercase normalization. The previous implementation truncated
    further to ``% 100000`` which gave only ~17 bits of effective space; the
    audit found this could yield cross-user data leakage by birthday paradox
    once the install reached ~316 active users.
    """
    return int(hashlib.sha256(email.lower().encode()).hexdigest()[:8], 16)
