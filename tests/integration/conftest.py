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
