# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Conftest for integration tests — overrides autouse fixtures from parent conftest.

These tests hit the REAL backend (localhost:5050) and real Gmail/IMAP providers.
Parent fixtures (mock_container_llm, mock_notifications, clear_legacy_module_cache)
are overridden to be no-ops so real services are used.
"""

import pytest


@pytest.fixture(autouse=True)
def mock_container_llm():
    """Override parent: allow real LLM calls."""
    yield None


@pytest.fixture(autouse=True)
def mock_notifications():
    """Override parent: allow real notifications."""
    yield None


@pytest.fixture(autouse=True)
def clear_legacy_module_cache():
    """Override parent: skip legacy cache clearing."""
    yield None
