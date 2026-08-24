# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for incremental refresh: parse_knowledge_markdown, merge logic."""

import json
from unittest.mock import MagicMock, patch

from app.onboarding.manager import (
    OnboardingManager,
    build_knowledge_markdown,
    parse_knowledge_markdown,
    _merge_knowledge,
    _merge_rules,
)


# ── Fixtures ──

SAMPLE_PROFILE = {
    "user_name": "Jean Dupont",
    "profession": "directeur commercial",
    "profession_confirmed": True,
    "signature": {"company": "Acme Corp", "title": "Directeur"},
    "tone": {
        "default_tone": "semi-formal",
        "greeting_style": "Bonjour",
        "closing_style": "Cordialement",
    },
}

SAMPLE_KNOWLEDGE = {
    "contacts": [
        {"name": "Marie Martin", "type": "colleague", "title": "Dev Lead", "company": "Acme Corp"},
        {"name": "Pierre Durand", "type": "client"},
    ],
    "projects": [
        {"name": "Projet Alpha", "description": "Refonte du site web"},
    ],
    "terminology": {"KPI": "Indicateur clé de performance"},
}

SAMPLE_RULES = {
    "general_rules": [
        {"description": "Toujours vouvoyer les clients"},
    ],
    "contact_rules": [
        {"email": "marie@acme.com", "tone": "casual"},
    ],
    "forbidden_phrases": ["Pas de souci"],
}


class TestParseKnowledgeMarkdown:
    """Test that parse_knowledge_markdown is the inverse of build_knowledge_markdown."""

    def test_roundtrip_profile(self):
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        profile, _, _ = parse_knowledge_markdown(md)

        assert profile["user_name"] == "Jean Dupont"
        assert profile["signature"]["company"] == "Acme Corp"
        assert profile["signature"]["title"] == "Directeur"
        assert profile["profession"] == "directeur commercial"
        assert profile["tone"]["default_tone"] == "semi-formal"

    def test_roundtrip_writing_format(self):
        """The user-controlled Format section (Concise/Medium/Detailed × Simple/Standard/Sophisticated)
        must survive build → parse → build. Regression: silently dropped on save before #(this fix),
        so picking Concise+Simple in the Training UI reverted to defaults on reload."""
        profile = {**SAMPLE_PROFILE, "writing_format": {"longueur": "concis", "complexite": "accessible"}}
        md = build_knowledge_markdown(profile, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        assert "## Format" in md
        assert "Longueur préférée**: concis" in md
        assert "Vocabulaire**: accessible" in md

        parsed_profile, _, _ = parse_knowledge_markdown(md)
        assert parsed_profile.get("writing_format") == {
            "longueur": "concis",
            "complexite": "accessible",
        }

        # Second roundtrip — values must be stable (no drift from defaults injection).
        md2 = build_knowledge_markdown(parsed_profile, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        parsed_profile2, _, _ = parse_knowledge_markdown(md2)
        assert parsed_profile2.get("writing_format") == {
            "longueur": "concis",
            "complexite": "accessible",
        }

    def test_roundtrip_writing_format_absent_when_unset(self):
        """No ## Format section emitted when profile.writing_format is missing — keeps the
        markdown lean for accounts that never customized format."""
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        assert "## Format" not in md
        parsed, _, _ = parse_knowledge_markdown(md)
        assert "writing_format" not in parsed

    def test_roundtrip_contacts_not_written(self):
        """Contacts are intentionally not written to memoire.md anymore
        (managed via contact nicknames in the Style pillar)."""
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        _, knowledge, _ = parse_knowledge_markdown(md)
        assert knowledge["contacts"] == []

    def test_roundtrip_projects_not_written(self):
        """Projects are intentionally neither written nor rehydrated anymore —
        the parser no longer exposes a `projects` key at all."""
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        _, knowledge, _ = parse_knowledge_markdown(md)
        assert "projects" not in knowledge
        assert "Projet :" not in md

    def test_terminology_no_longer_in_savoir(self):
        """Terminology is no longer written to memoire.md."""
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        assert "### Terme" not in md

    def test_roundtrip_rules(self):
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        _, _, rules = parse_knowledge_markdown(md)

        rule_descs = [r.get("description", "") for r in rules["general_rules"]]
        assert "Toujours vouvoyer les clients" in rule_descs

    def test_roundtrip_forbidden_phrases(self):
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        _, _, rules = parse_knowledge_markdown(md)

        assert "Pas de souci" in rules["forbidden_phrases"]

    def test_roundtrip_greeting_closing(self):
        md = build_knowledge_markdown(SAMPLE_PROFILE, SAMPLE_KNOWLEDGE, SAMPLE_RULES)
        profile, _, _ = parse_knowledge_markdown(md)

        assert profile["tone"]["greeting_style"] == "Bonjour"
        assert profile["tone"]["closing_style"] == "Cordialement"

    def test_empty_content(self):
        profile, knowledge, rules = parse_knowledge_markdown("")
        assert profile == {}
        assert knowledge["contacts"] == []
        assert rules["general_rules"] == []


class TestConfirmProfession:
    """Tests for persisting the user-confirmed profession."""

    def test_confirm_profession_updates_profile_and_invalidates_cache(self, monkeypatch):
        class FakeResult:
            profile_json = json.dumps({"user_name": "Jean Dupont"}, ensure_ascii=False)
            knowledge_json = json.dumps({"contacts": []}, ensure_ascii=False)
            rules_json = json.dumps({"general_rules": []}, ensure_ascii=False)
            emails_analysed = 12

        class FakeSession:
            def __init__(self):
                self.result = FakeResult()
                self.committed = False
                self.closed = False

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        class FakeRepo:
            def __init__(self, session):
                self.session = session

            def get_completed_by_account(self, account_id):
                assert account_id == 42
                return self.session.result

        import app.onboarding.manager as manager_module

        session = FakeSession()
        monkeypatch.setattr(manager_module, "OnboardingRepository", FakeRepo)
        manager = OnboardingManager(session_factory=lambda: session)
        manager._apply_to_knowledge_base = MagicMock()

        with patch("app._prompts_monolith.invalidate_kb_db_cache") as invalidate:
            result = manager.confirm_profession(42, " courtier immobilier ")

        saved_profile = json.loads(session.result.profile_json)
        assert saved_profile["profession"] == "courtier immobilier"
        assert saved_profile["profession_confirmed"] is True
        assert session.committed is True
        assert session.closed is True
        assert result == {"profession": "courtier immobilier", "profession_confirmed": True}
        invalidate.assert_called_once_with(42)
        manager._apply_to_knowledge_base.assert_called_once()


class TestMergeKnowledge:
    """Test the _merge_knowledge function."""

    def test_adds_new_contacts(self):
        existing = {"contacts": [{"name": "Alice"}], "projects": []}
        new = {"contacts": [{"name": "Bob"}]}
        merged = _merge_knowledge(existing, new)

        names = {c["name"] for c in merged["contacts"]}
        assert names == {"Alice", "Bob"}

    def test_deduplicates_contacts_by_name(self):
        existing = {"contacts": [{"name": "Alice", "type": "client"}], "projects": []}
        new = {"contacts": [{"name": "alice", "type": "colleague"}]}  # same name, different case
        merged = _merge_knowledge(existing, new)

        assert len(merged["contacts"]) == 1
        assert merged["contacts"][0]["type"] == "client"  # existing kept

    def test_projects_key_ignored(self):
        """Legacy `projects` key on input is silently dropped — the merger
        only handles contacts. Projects are no longer produced or persisted."""
        existing = {"contacts": [], "projects": [{"name": "Alpha", "description": "Short"}]}
        new = {"projects": [{"name": "Beta", "description": "New project"}]}
        merged = _merge_knowledge(existing, new)

        assert "projects" not in merged

    def test_terminology_key_ignored(self):
        """Terminology is no longer merged — key should not appear in output."""
        existing = {"contacts": [], "projects": []}
        new = {"terminology": {"KPI": "Key performance indicator"}}
        merged = _merge_knowledge(existing, new)

        assert "terminology" not in merged

class TestMergeRules:
    """Test the _merge_rules function."""

    def test_adds_new_general_rules(self):
        existing = {"general_rules": [{"description": "Rule A"}], "contact_rules": [], "forbidden_phrases": []}
        new = {"general_rules": [{"description": "Rule B"}]}
        merged = _merge_rules(existing, new)

        descs = {r["description"] for r in merged["general_rules"]}
        assert descs == {"Rule A", "Rule B"}

    def test_deduplicates_general_rules(self):
        existing = {"general_rules": [{"description": "Rule A"}], "contact_rules": [], "forbidden_phrases": []}
        new = {"general_rules": [{"description": "rule a"}]}  # same rule, different case
        merged = _merge_rules(existing, new)

        assert len(merged["general_rules"]) == 1

    def test_union_forbidden_phrases(self):
        existing = {"general_rules": [], "contact_rules": [], "forbidden_phrases": ["Pas de souci"]}
        new = {"forbidden_phrases": ["Pas de souci", "No worries"]}
        merged = _merge_rules(existing, new)

        assert set(merged["forbidden_phrases"]) == {"Pas de souci", "No worries"}

    def test_contact_rules_replaced_by_email(self):
        existing = {"general_rules": [], "contact_rules": [{"email": "a@b.com", "tone": "formal"}], "forbidden_phrases": []}
        new = {"contact_rules": [{"email": "a@b.com", "tone": "casual"}]}
        merged = _merge_rules(existing, new)

        assert len(merged["contact_rules"]) == 1
        assert merged["contact_rules"][0]["tone"] == "casual"
