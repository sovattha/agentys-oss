# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Anti-regression tests for multi-account memory isolation (Issue #158).

These tests verify that account B NEVER sees account A's data in any
agent prompt. They must FAIL before the fix and PASS after.
"""

import json
from unittest.mock import patch, MagicMock

from app.agents import DrafterAgent, CriticAgent
from app.domain.ports.llm_port import LLMResponse


def _mock_onboarding_result(account_id: int, user_name: str):
    """Create a mock OnboardingResult for a given account."""
    result = MagicMock()
    result.profile_json = json.dumps({
        "user_name": user_name,
        "tone": {"default_tone": "casual"},
        "languages": ["fr"],
    })
    result.knowledge_json = json.dumps({
        "terminology": {"API": "Application Programming Interface"},
    })
    result.rules_json = json.dumps({
        "contact_rules": [],
        "general_rules": [],
    })
    return result


class TestMultiAccountIsolation:
    """Verify that agents load memory per-account, never cross-account."""

    def test_drafter_uses_correct_account_memory(self):
        """DrafterAgent with account_id=2 should load account 2's KB, not account 1's."""
        account_a = _mock_onboarding_result(1, "Alice Dupont")
        account_b = _mock_onboarding_result(2, "Bob Martin")

        def mock_get_completed(account_id):
            if account_id == 1:
                return account_a
            if account_id == 2:
                return account_b
            return None

        mock_llm = MagicMock()
        mock_llm.complete.return_value = LLMResponse(
            content="Draft response", input_tokens=10, output_tokens=5, model="mock"
        )

        with patch("app.agents.get_container") as mock_container:
            mock_container.return_value.llm_label = mock_llm

            # Mock the DB session and repository used by load_knowledge_from_db
            mock_repo = MagicMock()
            mock_repo.get_completed_by_account.side_effect = mock_get_completed

            with patch("app.db.database.get_db_session") as mock_session_ctx, \
                 patch("app.db.repositories.onboarding_repository.OnboardingRepository", return_value=mock_repo):
                mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

                agent = DrafterAgent(account_id=2)

                # The KB should contain Bob's data, not Alice's
                assert "Bob Martin" in agent.knowledge_base or "projet-bob" in agent.knowledge_base, \
                    f"DrafterAgent(account_id=2) loaded wrong KB: {agent.knowledge_base[:200]}"
                assert "Alice Dupont" not in agent.knowledge_base, \
                    "DrafterAgent(account_id=2) leaked account A data!"

    def test_critic_uses_account_specific_memory(self):
        """CriticAgent should support account_id and NOT use the global file."""
        # This test verifies that CriticAgent accepts account_id parameter.
        # Before fix: CriticAgent has no account_id → always loads global file.
        # After fix: CriticAgent(account_id=2) loads from DB.

        assert hasattr(CriticAgent, '__dataclass_fields__'), "CriticAgent should be a dataclass"
        fields = CriticAgent.__dataclass_fields__

        assert 'account_id' in fields, (
            "CriticAgent must have an account_id field to support per-user memory. "
            "Currently it loads the global memoire.md via default_factory=load_knowledge_base."
        )
