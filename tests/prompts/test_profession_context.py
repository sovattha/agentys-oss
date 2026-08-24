# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from unittest.mock import patch

from app import _prompts_monolith as prompts_monolith
from app.prompts.builders import (
    _segments_to_text,
    get_classify_and_draft_prompts,
    get_standard_draft_prompts,
    get_unified_draft_system_prompt,
)


def test_load_knowledge_from_db_includes_profession():
    class FakeResult:
        profile_json = json.dumps({
            "user_name": "Sophie Martin",
            "profession": "courtier immobilier",
            "profession_confirmed": True,
            "tone": {"default_tone": "semi-formal"},
        }, ensure_ascii=False)
        knowledge_json = json.dumps({"contacts": []}, ensure_ascii=False)
        rules_json = json.dumps({"general_rules": []}, ensure_ascii=False)

    class FakeSessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeRepo:
        def __init__(self, session):
            self.session = session

        def get_completed_by_account(self, account_id):
            assert account_id == 7
            return FakeResult()

    prompts_monolith.invalidate_kb_db_cache()
    with (
        patch("app.db.database.get_db_session", return_value=FakeSessionContext()),
        patch("app.db.repositories.onboarding_repository.OnboardingRepository", FakeRepo),
    ):
        kb = prompts_monolith.load_knowledge_from_db(7)

    assert "- **Métier**: courtier immobilier" in kb


def test_draft_builders_include_profession_context_and_usage_rule():
    kb = "## Profil\n\n- **Nom complet**: Sophie Martin\n- **Métier**: courtier immobilier\n"

    standard_segments, _ = get_standard_draft_prompts(
        sender="client@example.com",
        subject="Estimation",
        body="Bonjour, pouvez-vous estimer mon appartement ?",
        knowledge_base=kb,
    )
    standard_system = _segments_to_text(standard_segments)

    unified_system = get_unified_draft_system_prompt(kb)
    classify_system, _ = get_classify_and_draft_prompts(
        sender="client@example.com",
        sender_name="Client",
        subject="Estimation",
        body="Bonjour, pouvez-vous estimer mon appartement ?",
        knowledge_base=kb,
    )

    assert "- **Métier**: courtier immobilier" in standard_system
    assert "Do not mention the profession just to mention it" in standard_system

    assert "- **Métier**: courtier immobilier" in unified_system
    assert "Ne mentionne pas le métier juste pour le mentionner" in unified_system

    assert "<CONTEXTE>" in classify_system
    assert "- **Métier**: courtier immobilier" in classify_system
