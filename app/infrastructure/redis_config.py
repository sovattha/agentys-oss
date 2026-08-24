# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared Redis configuration helpers."""

from __future__ import annotations

import os


def get_redis_url() -> str:
    """Return the first Redis URL exposed by the runtime."""
    for name in ("REDIS_URL", "REDIS_PRIVATE_URL", "RAILWAY_REDIS_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""
