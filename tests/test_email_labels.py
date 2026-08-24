# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests unitaires pour app.domain.entities.email_labels."""

import pytest
from datetime import datetime

from app.domain.entities.email_labels import (
    DefaultLabel,
    DEFAULT_LABEL_NAMES,
    LABEL_COLORS,
    EmailLabel,
    LabelAssignment,
    LabelingRule,
    get_default_labels,
)


# ── DefaultLabel Enum ────────────────────────────────────────────────────────


class TestDefaultLabel:
    def test_action_value(self):
        assert DefaultLabel.ACTION.value == "Action"

    def test_fyi_value(self):
        assert DefaultLabel.FYI.value == "FYI"

    def test_noise_value(self):
        assert DefaultLabel.NOISE.value == "Noise"

    def test_default_label_names_set(self):
        assert DEFAULT_LABEL_NAMES == {"Action", "FYI", "Noise"}

    def test_label_colors_keys(self):
        assert set(LABEL_COLORS.keys()) == {"Action", "FYI", "Noise"}

    def test_label_colors_have_background_and_text(self):
        for name, colors in LABEL_COLORS.items():
            assert "backgroundColor" in colors
            assert "textColor" in colors


# ── EmailLabel ───────────────────────────────────────────────────────────────


class TestEmailLabel:
    def test_creation_basic(self):
        label = EmailLabel(name="Test")
        assert label.name == "Test"
        assert label.is_default is False
        assert label.is_favorite is True
        assert label.rules == []

    def test_name_stripped(self):
        label = EmailLabel(name="  Spaces  ")
        assert label.name == "Spaces"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            EmailLabel(name="")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            EmailLabel(name="   ")

    def test_created_at_auto_set(self):
        label = EmailLabel(name="Auto")
        assert label.created_at != ""
        # Should be parseable as ISO format
        datetime.fromisoformat(label.created_at)

    def test_created_at_preserved_if_set(self):
        label = EmailLabel(name="Test", created_at="2024-01-01T00:00:00")
        assert label.created_at == "2024-01-01T00:00:00"

    def test_create_default_action(self):
        label = EmailLabel.create_default(DefaultLabel.ACTION)
        assert label.name == "Action"
        assert label.is_default is True
        # Default labels are NOT favorites — they're the 3 core sidebar labels
        # (Action / FYI / Noise). Marking them as favorites would duplicate
        # them in the favorites row rendered after the core labels.
        assert label.is_favorite is False
        assert label.color == "#dc2626"
        assert len(label.rules) > 0

    def test_create_default_fyi(self):
        label = EmailLabel.create_default(DefaultLabel.FYI)
        assert label.name == "FYI"
        assert label.is_default is True
        assert label.is_favorite is False
        assert label.color == "#3b82f6"

    def test_create_default_noise_not_favorite(self):
        label = EmailLabel.create_default(DefaultLabel.NOISE)
        assert label.name == "Noise"
        assert label.is_default is True
        assert label.is_favorite is False

    def test_to_dict(self):
        label = EmailLabel(
            name="Custom",
            color="#ff0000",
            description="A custom label",
            is_project=True,
            project_number="P-123",
            rules=["rule1"],
        )
        d = label.to_dict()
        assert d["name"] == "Custom"
        assert d["color"] == "#ff0000"
        assert d["description"] == "A custom label"
        assert d["is_project"] is True
        assert d["project_number"] == "P-123"
        assert d["rules"] == ["rule1"]

    def test_to_dict_no_ai_prompt_when_none(self):
        label = EmailLabel(name="NoPrompt")
        d = label.to_dict()
        assert "ai_prompt" not in d

    def test_to_dict_includes_ai_prompt_when_set(self):
        label = EmailLabel(name="WithPrompt", ai_prompt="classify this")
        d = label.to_dict()
        assert d["ai_prompt"] == "classify this"

    def test_from_dict_roundtrip(self):
        original = EmailLabel(
            name="Roundtrip",
            color="#00ff00",
            description="Test",
            is_default=False,
            is_favorite=False,
            is_project=True,
            project_number="P-1",
            rules=["r1", "r2"],
            ai_prompt="do stuff",
        )
        d = original.to_dict()
        d["ai_prompt"] = original.ai_prompt  # ai_prompt is in to_dict when set
        restored = EmailLabel.from_dict(d)
        assert restored.name == original.name
        assert restored.color == original.color
        assert restored.is_project == original.is_project
        assert restored.rules == original.rules

    def test_from_dict_defaults(self):
        label = EmailLabel.from_dict({"name": "Minimal"})
        assert label.name == "Minimal"
        assert label.is_default is False
        assert label.rules == []


# ── LabelAssignment ──────────────────────────────────────────────────────────


class TestLabelAssignment:
    def test_creation_basic(self):
        la = LabelAssignment(email_id="e1")
        assert la.email_id == "e1"
        assert la.default_label is None
        assert la.custom_labels == []
        assert la.labels == []

    def test_empty_email_id_raises(self):
        with pytest.raises(ValueError, match="email_id cannot be empty"):
            LabelAssignment(email_id="")

    def test_assigned_at_auto_set(self):
        la = LabelAssignment(email_id="e1")
        assert la.assigned_at != ""

    def test_set_default_label(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action", confidence=0.9, reason="test")
        assert la.default_label == "Action"
        assert la.labels == ["Action"]
        assert la.confidences["Action"] == 0.9
        assert la.reasons["Action"] == "test"

    def test_set_default_label_replaces_previous(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action", confidence=0.8)
        la.set_default_label("FYI", confidence=0.9)
        assert la.default_label == "FYI"
        assert "Action" not in la.confidences
        assert la.labels == ["FYI"]

    def test_add_custom_label(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action")
        la.add_custom_label("VIP", confidence=1.0, reason="important")
        assert "VIP" in la.custom_labels
        assert la.labels == ["Action", "VIP"]

    def test_add_custom_label_ignores_conflicting_default(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action")
        la.add_custom_label("Noise")  # Conflicting default label
        assert "Noise" not in la.custom_labels
        assert la.default_label == "Action"

    def test_remove_custom_label(self):
        la = LabelAssignment(email_id="e1")
        la.add_custom_label("VIP")
        la.remove_custom_label("VIP")
        assert "VIP" not in la.custom_labels
        assert "VIP" not in la.labels

    def test_remove_default_label(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action")
        la.remove_label("Action")
        assert la.default_label is None
        assert la.labels == []

    def test_add_label_routes_to_default(self):
        la = LabelAssignment(email_id="e1")
        la.add_label("FYI", confidence=0.7)
        assert la.default_label == "FYI"

    def test_add_label_routes_to_custom(self):
        la = LabelAssignment(email_id="e1")
        la.add_label("VIP", confidence=0.7)
        assert "VIP" in la.custom_labels

    def test_has_label(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action")
        la.add_custom_label("VIP")
        assert la.has_label("Action") is True
        assert la.has_label("VIP") is True
        assert la.has_label("Noise") is False

    def test_to_dict(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("Action", confidence=0.9, reason="urgent")
        la.add_custom_label("VIP")
        d = la.to_dict()
        assert d["email_id"] == "e1"
        assert d["default_label"] == "Action"
        assert "VIP" in d["custom_labels"]
        assert "Action" in d["labels"]

    def test_to_dict_no_matched_rules_when_empty(self):
        la = LabelAssignment(email_id="e1")
        d = la.to_dict()
        assert "matched_rule_ids" not in d

    def test_to_dict_includes_matched_rules(self):
        la = LabelAssignment(email_id="e1", matched_rule_ids=["r1"])
        d = la.to_dict()
        assert d["matched_rule_ids"] == ["r1"]

    def test_from_dict_roundtrip(self):
        la = LabelAssignment(email_id="e1")
        la.set_default_label("FYI", confidence=0.8)
        la.add_custom_label("Client")
        d = la.to_dict()
        restored = LabelAssignment.from_dict(d)
        assert restored.default_label == "FYI"
        assert "Client" in restored.custom_labels

    def test_from_dict_legacy_migration(self):
        """Legacy format: only labels list, no default_label/custom_labels."""
        data = {
            "email_id": "e1",
            "labels": ["Action", "VIP"],
        }
        la = LabelAssignment.from_dict(data)
        assert la.default_label == "Action"
        assert "VIP" in la.custom_labels
        assert la.labels == ["Action", "VIP"]

    def test_rebuild_labels_purges_contradictions(self):
        la = LabelAssignment(email_id="e1")
        la.default_label = "Action"
        la.custom_labels = ["Noise", "VIP"]  # Noise contradicts Action
        la._rebuild_labels()
        assert "Noise" not in la.labels
        assert la.labels == ["Action", "VIP"]


# ── LabelingRule ─────────────────────────────────────────────────────────────


class TestLabelingRule:
    def test_creation(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="Action",
            condition_type="sender",
            condition_value="boss@company.com",
        )
        assert rule.rule_id == "r1"
        assert rule.use_count == 0
        assert rule.is_active is True

    def test_created_at_auto(self):
        rule = LabelingRule(
            rule_id="r1", label_name="X", condition_type="sender", condition_value="x"
        )
        assert rule.created_at != ""

    def test_matches_sender(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="VIP",
            condition_type="sender",
            condition_value="boss@company.com",
        )
        assert rule.matches({"sender": "boss@company.com"}) is True
        assert rule.matches({"sender": "Boss@Company.com"}) is True
        assert rule.matches({"sender": "other@company.com"}) is False

    def test_matches_subject_regex(self):
        # ``subject_regex`` condition type uses regex semantics. Plain ``subject``
        # treats the value as a literal substring (see LabelingRule.matches docstring).
        rule = LabelingRule(
            rule_id="r1",
            label_name="Urgent",
            condition_type="subject_regex",
            condition_value=r"urgent|asap",
        )
        assert rule.matches({"subject": "URGENT: Review needed"}) is True
        assert rule.matches({"subject": "Please do ASAP"}) is True
        assert rule.matches({"subject": "Normal email"}) is False

    def test_matches_subject_invalid_regex_falls_back(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="X",
            condition_type="subject",
            condition_value="[invalid",  # Invalid regex
        )
        assert rule.matches({"subject": "contains [invalid"}) is True
        assert rule.matches({"subject": "something else"}) is False

    def test_matches_body(self):
        # Plain ``body`` condition = literal substring match (not regex).
        rule = LabelingRule(
            rule_id="r1",
            label_name="Invoice",
            condition_type="body",
            condition_value="invoice",
        )
        assert rule.matches({"body": "Please pay invoice #123"}) is True
        assert rule.matches({"body": "Hello there"}) is False

    def test_matches_body_regex(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="Invoice",
            condition_type="body_regex",
            condition_value=r"invoice|facture",
        )
        assert rule.matches({"body": "Please pay invoice #123"}) is True
        assert rule.matches({"body": "Merci de régler la facture"}) is True
        assert rule.matches({"body": "Hello there"}) is False

    def test_matches_cc(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="FYI",
            condition_type="cc",
            condition_value="",
        )
        assert rule.matches({"is_cc": True}) is True
        assert rule.matches({"is_cc": False}) is False

    def test_matches_recipient(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="Team",
            condition_type="recipient",
            condition_value="team@company.com",
        )
        assert rule.matches({"recipients": ["team@company.com", "other@x.com"]}) is True
        assert rule.matches({"recipients": ["solo@x.com"]}) is False

    def test_matches_unknown_type(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="X",
            condition_type="unknown",
            condition_value="x",
        )
        assert rule.matches({"sender": "x"}) is False

    def test_record_use(self):
        rule = LabelingRule(
            rule_id="r1", label_name="X", condition_type="sender", condition_value="x"
        )
        assert rule.use_count == 0
        rule.record_use()
        assert rule.use_count == 1
        assert rule.last_used_at is not None

    def test_to_dict_from_dict_roundtrip(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="Action",
            condition_type="sender",
            condition_value="test@test.com",
            priority=80,
            confidence=0.95,
            is_active=True,
            total_matches=5,
            corrections=1,
        )
        d = rule.to_dict()
        restored = LabelingRule.from_dict(d)
        assert restored.rule_id == rule.rule_id
        assert restored.priority == 80
        assert restored.confidence == 0.95
        assert restored.total_matches == 5

    def test_to_markdown(self):
        rule = LabelingRule(
            rule_id="r1",
            label_name="VIP",
            condition_type="sender",
            condition_value="ceo@co.com",
            confidence=0.9,
            use_count=3,
        )
        md = rule.to_markdown()
        assert "VIP" in md
        assert "sender" in md
        assert "90%" in md


# ── get_default_labels ───────────────────────────────────────────────────────


class TestGetDefaultLabels:
    def test_returns_three_labels(self):
        labels = get_default_labels()
        assert len(labels) == 3

    def test_all_are_default(self):
        labels = get_default_labels()
        assert all(label.is_default for label in labels)

    def test_names_match_enum(self):
        labels = get_default_labels()
        names = {label.name for label in labels}
        assert names == {"Action", "FYI", "Noise"}
