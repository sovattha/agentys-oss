# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour app/domain/entities/email_labels.py

Couvre:
- EmailLabel creation, validation, defaults, serialization
- LabelAssignment logic (default/custom labels, rebuild, remove)
- LabelingRule matching, usage recording, markdown export
"""

import pytest
from datetime import datetime
from app.domain.entities.email_labels import (
    EmailLabel,
    LabelAssignment,
    LabelingRule,
    DefaultLabel,
    DEFAULT_LABEL_NAMES,
    get_default_labels,
)


# ============================================================================
# EmailLabel Tests
# ============================================================================

class TestEmailLabelCreation:
    """Tests for EmailLabel creation and validation."""

    def test_email_label_creation(self):
        """Test creating a label with minimal parameters."""
        label = EmailLabel(name="Custom")
        assert label.name == "Custom"
        assert label.color is None
        assert label.description == ""
        assert label.is_default is False
        assert label.is_favorite is True
        assert label.created_at  # Auto-populated
        assert label.rules == []
        assert label.ai_prompt is None

    def test_email_label_creation_with_all_params(self):
        """Test creating a label with all parameters."""
        label = EmailLabel(
            name="VIP",
            color="#FF0000",
            description="VIP contacts",
            is_default=False,
            is_favorite=True,
            is_project=True,
            project_number="PRJ-123",
            rules=["high_priority"],
            ai_prompt="Treat as VIP",
        )
        assert label.name == "VIP"
        assert label.color == "#FF0000"
        assert label.description == "VIP contacts"
        assert label.is_project is True
        assert label.project_number == "PRJ-123"
        assert label.rules == ["high_priority"]
        assert label.ai_prompt == "Treat as VIP"

    def test_email_label_empty_name_raises_error(self):
        """Test that empty label name raises ValueError."""
        with pytest.raises(ValueError, match="Label name cannot be empty"):
            EmailLabel(name="")

    def test_email_label_whitespace_only_name_raises_error(self):
        """Test that whitespace-only label name raises ValueError."""
        with pytest.raises(ValueError, match="Label name cannot be empty"):
            EmailLabel(name="   ")

    def test_email_label_strips_name(self):
        """Test that label name is stripped of whitespace."""
        label = EmailLabel(name="  Custom  ")
        assert label.name == "Custom"

    def test_email_label_created_at_auto_populated(self):
        """Test that created_at is automatically set if not provided."""
        before = datetime.now().isoformat()
        label = EmailLabel(name="Test")
        after = datetime.now().isoformat()
        assert before <= label.created_at <= after

    def test_email_label_created_at_preserved_if_provided(self):
        """Test that provided created_at is preserved."""
        ts = "2025-01-01T00:00:00"
        label = EmailLabel(name="Test", created_at=ts)
        assert label.created_at == ts


class TestEmailLabelDefaults:
    """Tests for EmailLabel.create_default()."""

    def test_create_default_action_label(self):
        """Test creating default ACTION label.

        Note: since commit ac982662 (fix(labels): toggles off par défaut),
        all default labels are created with ``is_favorite=False`` — the
        user explicitly opts them into the sidebar instead of the other
        way around.
        """
        label = EmailLabel.create_default(DefaultLabel.ACTION)
        assert label.name == "Action"
        assert label.is_default is True
        assert label.color == "#dc2626"  # Red
        assert label.is_favorite is False
        assert "action" in label.description.lower()
        assert len(label.rules) > 0
        assert any("reply" in r.lower() for r in label.rules)

    def test_create_default_fyi_label(self):
        """Test creating default FYI label.

        Same as the ACTION test: default favorite is now ``False`` since
        commit ac982662.
        """
        label = EmailLabel.create_default(DefaultLabel.FYI)
        assert label.name == "FYI"
        assert label.is_default is True
        assert label.color == "#3b82f6"  # Blue
        assert label.is_favorite is False
        assert "information" in label.description.lower()
        assert len(label.rules) > 0

    def test_create_default_noise_label(self):
        """Test creating default NOISE label."""
        label = EmailLabel.create_default(DefaultLabel.NOISE)
        assert label.name == "Noise"
        assert label.is_default is True
        assert label.color == "#6b7280"  # Gray
        assert label.is_favorite is False  # Noise is not favorite by default
        # La description peut être en français ou anglais
        assert "automat" in label.description.lower() or "newsletter" in label.description.lower()
        assert len(label.rules) > 0
        assert any("newsletter" in r.lower() for r in label.rules)

    def test_create_default_has_initial_rules(self):
        """Test that default labels have initial rules for the AI."""
        for default_label in DefaultLabel:
            label = EmailLabel.create_default(default_label)
            assert label.rules, f"{default_label.value} should have initial rules"
            # Each rule should be a string
            assert all(isinstance(r, str) for r in label.rules)


class TestEmailLabelSerialization:
    """Tests for EmailLabel.to_dict() and from_dict()."""

    def test_to_dict_minimal(self):
        """Test converting minimal label to dict."""
        label = EmailLabel(name="Custom", created_at="2025-01-01T00:00:00")
        data = label.to_dict()
        assert data["name"] == "Custom"
        assert data["color"] is None
        assert data["description"] == ""
        assert data["is_default"] is False
        assert data["is_favorite"] is True
        assert data["created_at"] == "2025-01-01T00:00:00"
        assert "ai_prompt" not in data  # Omitted when None

    def test_to_dict_with_ai_prompt(self):
        """Test that ai_prompt is included in dict when set."""
        label = EmailLabel(
            name="Custom",
            created_at="2025-01-01T00:00:00",
            ai_prompt="Classify as custom"
        )
        data = label.to_dict()
        assert data["ai_prompt"] == "Classify as custom"

    def test_from_dict_minimal(self):
        """Test creating label from minimal dict."""
        data = {"name": "Custom"}
        label = EmailLabel.from_dict(data)
        assert label.name == "Custom"
        assert label.color is None
        assert label.is_default is False
        assert label.is_favorite is True
        assert label.rules == []

    def test_from_dict_full(self):
        """Test creating label from complete dict."""
        data = {
            "name": "VIP",
            "color": "#FF0000",
            "description": "VIP contacts",
            "is_default": False,
            "is_favorite": True,
            "is_project": True,
            "project_number": "PRJ-123",
            "created_at": "2025-01-01T00:00:00",
            "rules": ["rule1", "rule2"],
            "ai_prompt": "Treat as VIP",
        }
        label = EmailLabel.from_dict(data)
        assert label.name == "VIP"
        assert label.color == "#FF0000"
        assert label.is_project is True
        assert label.project_number == "PRJ-123"
        assert label.rules == ["rule1", "rule2"]
        assert label.ai_prompt == "Treat as VIP"

    def test_to_dict_from_dict_roundtrip(self):
        """Test round-trip serialization."""
        original = EmailLabel.create_default(DefaultLabel.ACTION)
        data = original.to_dict()
        restored = EmailLabel.from_dict(data)
        assert restored.name == original.name
        assert restored.color == original.color
        assert restored.is_default == original.is_default
        assert restored.rules == original.rules
        assert restored.description == original.description


# ============================================================================
# LabelAssignment Tests
# ============================================================================

class TestLabelAssignmentCreation:
    """Tests for LabelAssignment creation and validation."""

    def test_label_assignment_creation_minimal(self):
        """Test creating assignment with email_id only."""
        assignment = LabelAssignment(email_id="email-123")
        assert assignment.email_id == "email-123"
        assert assignment.default_label is None
        assert assignment.custom_labels == []
        assert assignment.labels == []
        assert assignment.confidences == {}
        assert assignment.reasons == {}
        assert assignment.is_cc is False
        assert assignment.assigned_by == "ai"
        assert assignment.assigned_at  # Auto-populated

    def test_label_assignment_creation_with_params(self):
        """Test creating assignment with all parameters."""
        assignment = LabelAssignment(
            email_id="email-123",
            default_label="Action",
            custom_labels=["VIP", "Client"],
            is_cc=True,
            assigned_by="user",
        )
        assert assignment.email_id == "email-123"
        assert assignment.default_label == "Action"
        assert assignment.custom_labels == ["VIP", "Client"]
        assert assignment.is_cc is True
        assert assignment.assigned_by == "user"

    def test_label_assignment_empty_email_id_raises_error(self):
        """Test that empty email_id raises ValueError."""
        with pytest.raises(ValueError, match="email_id cannot be empty"):
            LabelAssignment(email_id="")

    def test_label_assignment_none_email_id_raises_error(self):
        """Test that None email_id raises ValueError."""
        with pytest.raises(ValueError, match="email_id cannot be empty"):
            LabelAssignment(email_id=None)

    def test_label_assignment_assigned_at_auto_populated(self):
        """Test that assigned_at is automatically set."""
        before = datetime.now().isoformat()
        assignment = LabelAssignment(email_id="email-123")
        after = datetime.now().isoformat()
        assert before <= assignment.assigned_at <= after


class TestLabelAssignmentDefaultLabel:
    """Tests for default label operations."""

    def test_set_default_label(self):
        """Test setting a default label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action", confidence=0.95, reason="Has explicit request")
        assert assignment.default_label == "Action"
        assert assignment.confidences["Action"] == 0.95
        assert assignment.reasons["Action"] == "Has explicit request"
        assert "Action" in assignment.labels

    def test_set_default_label_replaces_previous(self):
        """Test that setting new default label replaces the previous one."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action", confidence=0.9, reason="Request")
        assert assignment.default_label == "Action"
        assert "Action" in assignment.confidences

        # Replace with FYI
        assignment.set_default_label("FYI", confidence=0.8, reason="Informational")
        assert assignment.default_label == "FYI"
        assert "FYI" in assignment.confidences
        assert "FYI" in assignment.labels
        # Old default should be removed from confidences
        assert "Action" not in assignment.confidences
        assert "Action" not in assignment.reasons
        assert "Action" not in assignment.labels

    def test_set_default_label_removes_old_from_metadata(self):
        """Test that old default label is removed from confidences/reasons."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action", confidence=1.0, reason="Important")
        assert "Action" in assignment.confidences

        assignment.set_default_label("Noise", confidence=0.5, reason="Spam-like")
        assert "Action" not in assignment.confidences
        assert "Action" not in assignment.reasons
        assert "Noise" in assignment.confidences


class TestLabelAssignmentCustomLabels:
    """Tests for custom label operations."""

    def test_add_custom_label(self):
        """Test adding a custom label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_custom_label("VIP", confidence=0.9, reason="High value")
        assert "VIP" in assignment.custom_labels
        assert "VIP" in assignment.labels
        assert assignment.confidences["VIP"] == 0.9
        assert assignment.reasons["VIP"] == "High value"

    def test_add_multiple_custom_labels(self):
        """Test adding multiple custom labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_custom_label("VIP")
        assignment.add_custom_label("Client")
        assignment.add_custom_label("Important")
        assert len(assignment.custom_labels) == 3
        assert "VIP" in assignment.labels
        assert "Client" in assignment.labels
        assert "Important" in assignment.labels

    def test_add_custom_label_does_not_duplicate(self):
        """Test that adding same custom label twice doesn't create duplicate."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_custom_label("VIP", confidence=0.9)
        assignment.add_custom_label("VIP", confidence=0.95)
        assert assignment.custom_labels.count("VIP") == 1
        assert assignment.labels.count("VIP") == 1
        # Confidence should be updated
        assert assignment.confidences["VIP"] == 0.95

    def test_add_custom_label_ignores_contradicting_default(self):
        """Test that adding a default label as custom is ignored if different default exists."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action")

        # Try to add contradicting default label
        assignment.add_custom_label("Noise")

        # Should be ignored
        assert "Noise" not in assignment.custom_labels
        assert "Noise" not in assignment.labels
        assert assignment.default_label == "Action"

    def test_add_custom_label_allows_same_default(self):
        """Test that adding the same default label as custom is allowed."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action")

        # Add the same label as custom (should be OK, no-op essentially)
        assignment.add_custom_label("Action")

        assert assignment.default_label == "Action"
        assert "Action" in assignment.labels

    def test_remove_custom_label(self):
        """Test removing a custom label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_custom_label("VIP", confidence=0.9)
        assignment.add_custom_label("Client")
        assert "VIP" in assignment.labels

        assignment.remove_custom_label("VIP")
        assert "VIP" not in assignment.custom_labels
        assert "VIP" not in assignment.labels
        assert "VIP" not in assignment.confidences
        assert "VIP" not in assignment.reasons
        assert "Client" in assignment.labels

    def test_remove_custom_label_that_does_not_exist(self):
        """Test removing a non-existent custom label is safe."""
        assignment = LabelAssignment(email_id="email-123")
        # Should not raise
        assignment.remove_custom_label("NonExistent")
        assert "NonExistent" not in assignment.labels


class TestLabelAssignmentAddLabel:
    """Tests for add_label routing logic."""

    def test_add_label_default_routes_to_set_default(self):
        """Test that add_label with default label name routes to set_default_label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_label("Action", confidence=0.95, reason="Explicit request")
        assert assignment.default_label == "Action"
        assert assignment.confidences["Action"] == 0.95
        assert "Action" in assignment.labels

    def test_add_label_custom_routes_to_add_custom(self):
        """Test that add_label with custom label name routes to add_custom_label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_label("VIP", confidence=0.9, reason="Important")
        assert "VIP" in assignment.custom_labels
        assert assignment.confidences["VIP"] == 0.9
        assert "VIP" in assignment.labels

    def test_add_label_with_default_labels(self):
        """Test add_label routes correctly for all default labels."""
        for default_label in DefaultLabel:
            assignment = LabelAssignment(email_id=f"email-{default_label.value}")
            assignment.add_label(default_label.value)
            assert assignment.default_label == default_label.value
            assert default_label.value in assignment.labels


class TestLabelAssignmentRemoveLabel:
    """Tests for remove_label method."""

    def test_remove_default_label(self):
        """Test removing the default label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action")
        assert "Action" in assignment.labels

        assignment.remove_label("Action")
        assert assignment.default_label is None
        assert "Action" not in assignment.labels
        assert "Action" not in assignment.confidences

    def test_remove_custom_label_via_remove_label(self):
        """Test removing a custom label via remove_label."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.add_custom_label("VIP")
        assignment.add_custom_label("Client")

        assignment.remove_label("VIP")
        assert "VIP" not in assignment.labels
        assert "Client" in assignment.labels

    def test_remove_label_that_does_not_exist(self):
        """Test removing a non-existent label is safe."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action")
        # Should not raise
        assignment.remove_label("NonExistent")
        assert "Action" in assignment.labels


class TestLabelAssignmentHasLabel:
    """Tests for has_label method."""

    def test_has_label_default(self):
        """Test checking for default label."""
        assignment = LabelAssignment(email_id="email-123")
        assert not assignment.has_label("Action")

        assignment.set_default_label("Action")
        assert assignment.has_label("Action")

    def test_has_label_custom(self):
        """Test checking for custom label."""
        assignment = LabelAssignment(email_id="email-123")
        assert not assignment.has_label("VIP")

        assignment.add_custom_label("VIP")
        assert assignment.has_label("VIP")

    def test_has_label_multiple(self):
        """Test checking multiple labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action")
        assignment.add_custom_label("VIP")
        assignment.add_custom_label("Client")

        assert assignment.has_label("Action")
        assert assignment.has_label("VIP")
        assert assignment.has_label("Client")
        assert not assignment.has_label("NonExistent")


class TestLabelAssignmentRebuild:
    """Tests for _rebuild_labels method."""

    def test_rebuild_labels_combines_default_and_custom(self):
        """Test that rebuild combines default and custom labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.default_label = "Action"
        assignment.custom_labels = ["VIP", "Client"]
        assignment._rebuild_labels()

        assert assignment.labels == ["Action", "VIP", "Client"]

    def test_rebuild_labels_purges_contradicting_defaults(self):
        """Test that rebuild purges contradicting default labels from custom_labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.default_label = "Action"
        # Simulate corrupted state: both Action and Noise in custom_labels
        assignment.custom_labels = ["VIP", "Noise", "Client"]
        assignment._rebuild_labels()

        # Noise should be purged
        assert "Noise" not in assignment.custom_labels
        assert assignment.custom_labels == ["VIP", "Client"]
        assert assignment.labels == ["Action", "VIP", "Client"]

    def test_rebuild_labels_no_duplicates(self):
        """Test that rebuild doesn't create duplicate labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.default_label = "Action"
        assignment.custom_labels = ["VIP", "Action"]  # Action appears in both
        assignment._rebuild_labels()

        assert assignment.labels == ["Action", "VIP"]
        assert assignment.labels.count("Action") == 1

    def test_rebuild_labels_empty(self):
        """Test rebuild with no labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment._rebuild_labels()
        assert assignment.labels == []


class TestLabelAssignmentSerialization:
    """Tests for LabelAssignment serialization."""

    def test_to_dict_minimal(self):
        """Test converting minimal assignment to dict."""
        assignment = LabelAssignment(
            email_id="email-123",
            assigned_at="2025-01-01T00:00:00"
        )
        data = assignment.to_dict()
        assert data["email_id"] == "email-123"
        assert data["default_label"] is None
        assert data["custom_labels"] == []
        assert data["labels"] == []
        assert data["assigned_by"] == "ai"
        assert "matched_rule_ids" not in data  # Omitted when empty

    def test_to_dict_with_labels(self):
        """Test to_dict with labels."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.set_default_label("Action", confidence=0.95)
        assignment.add_custom_label("VIP", confidence=0.9)

        data = assignment.to_dict()
        assert data["default_label"] == "Action"
        assert data["custom_labels"] == ["VIP"]
        assert data["labels"] == ["Action", "VIP"]
        assert data["confidences"]["Action"] == 0.95
        assert data["confidences"]["VIP"] == 0.9

    def test_to_dict_with_matched_rule_ids(self):
        """Test that matched_rule_ids is included when non-empty."""
        assignment = LabelAssignment(email_id="email-123")
        assignment.matched_rule_ids = ["rule-1", "rule-2"]
        data = assignment.to_dict()
        assert data["matched_rule_ids"] == ["rule-1", "rule-2"]

    def test_from_dict_minimal(self):
        """Test creating assignment from minimal dict."""
        data = {
            "email_id": "email-123",
            "assigned_at": "2025-01-01T00:00:00"
        }
        assignment = LabelAssignment.from_dict(data)
        assert assignment.email_id == "email-123"
        assert assignment.default_label is None
        assert assignment.custom_labels == []
        assert assignment.labels == []

    def test_from_dict_with_labels(self):
        """Test creating assignment from dict with labels."""
        data = {
            "email_id": "email-123",
            "default_label": "Action",
            "custom_labels": ["VIP", "Client"],
            "labels": ["Action", "VIP", "Client"],
            "confidences": {"Action": 0.95, "VIP": 0.9, "Client": 0.8},
            "reasons": {"Action": "Has request", "VIP": "Important", "Client": "Work"},
        }
        assignment = LabelAssignment.from_dict(data)
        assert assignment.default_label == "Action"
        assert assignment.custom_labels == ["VIP", "Client"]
        assert assignment.confidences["Action"] == 0.95
        assert assignment.reasons["Action"] == "Has request"

    def test_from_dict_legacy_migration_no_default_label(self):
        """Test legacy migration when default_label is missing."""
        # Old format: only `labels` flat list
        data = {
            "email_id": "email-123",
            "labels": ["Action", "VIP", "Client"],
        }
        assignment = LabelAssignment.from_dict(data)

        # Should infer default_label and custom_labels
        assert assignment.default_label == "Action"
        assert "VIP" in assignment.custom_labels
        assert "Client" in assignment.custom_labels
        assert assignment.labels == ["Action", "VIP", "Client"]

    def test_from_dict_legacy_migration_multiple_defaults_last_wins(self):
        """Test legacy migration when multiple default labels exist (last default wins)."""
        data = {
            "email_id": "email-123",
            "labels": ["Noise", "Action", "VIP"],  # Both Noise and Action are defaults
        }
        assignment = LabelAssignment.from_dict(data)

        # Le code itère la liste et écrase default_label à chaque default trouvé
        # => le dernier default label dans la liste l'emporte (Action)
        assert assignment.default_label == "Action"
        assert "VIP" in assignment.custom_labels
        # Noise est purgé de custom_labels par _rebuild_labels (contradict default)
        assert "Noise" not in assignment.custom_labels

    def test_to_dict_from_dict_roundtrip(self):
        """Test round-trip serialization."""
        original = LabelAssignment(email_id="email-123")
        original.set_default_label("Action", confidence=0.95, reason="Request")
        original.add_custom_label("VIP", confidence=0.9, reason="Important")
        original.add_custom_label("Client")
        original.is_cc = True
        original.assigned_by = "user"

        data = original.to_dict()
        restored = LabelAssignment.from_dict(data)

        assert restored.email_id == original.email_id
        assert restored.default_label == original.default_label
        assert restored.custom_labels == original.custom_labels
        assert restored.labels == original.labels
        assert restored.confidences == original.confidences
        assert restored.reasons == original.reasons
        assert restored.is_cc == original.is_cc
        assert restored.assigned_by == original.assigned_by


# ============================================================================
# LabelingRule Tests
# ============================================================================

class TestLabelingRuleCreation:
    """Tests for LabelingRule creation."""

    def test_labeling_rule_creation_minimal(self):
        """Test creating a rule with required fields."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="sender",
            condition_value="john@example.com"
        )
        assert rule.rule_id == "rule-1"
        assert rule.label_name == "Action"
        assert rule.condition_type == "sender"
        assert rule.condition_value == "john@example.com"
        assert rule.priority == 50
        assert rule.learned_from is None
        assert rule.confidence == 1.0
        assert rule.use_count == 0
        assert rule.is_active is True
        assert rule.created_at  # Auto-populated

    def test_labeling_rule_creation_with_all_params(self):
        """Test creating a rule with all parameters."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="important@example.com",
            priority=100,
            learned_from="email-123",
            confidence=0.95,
            use_count=5,
            is_active=True,
        )
        assert rule.priority == 100
        assert rule.learned_from == "email-123"
        assert rule.confidence == 0.95
        assert rule.use_count == 5
        assert rule.is_active is True


class TestLabelingRuleMatches:
    """Tests for LabelingRule.matches()."""

    def test_matches_sender_exact_substring(self):
        """Test sender matching with substring."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com"
        )
        email = {"sender": "john@example.com"}
        assert rule.matches(email)

    def test_matches_sender_case_insensitive(self):
        """Test sender matching is case-insensitive."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com"
        )
        email = {"sender": "JOHN@EXAMPLE.COM"}
        assert rule.matches(email)

    def test_matches_sender_substring(self):
        """Test sender matching with partial match."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john"
        )
        email = {"sender": "john@example.com"}
        assert rule.matches(email)

    def test_matches_sender_no_match(self):
        """Test sender matching when no match."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="jane@example.com"
        )
        email = {"sender": "john@example.com"}
        assert not rule.matches(email)

    def test_matches_subject_regex(self):
        """Test subject matching with regex.

        ``condition_type="subject"`` is literal-substring only — regex
        semantics require ``subject_regex`` explicitly. This was changed
        to prevent the footgun where a rule with value ``[Newsletter]``
        becomes the regex character class ``[Newsletter]`` and matches
        any subject containing N, e, w, s, l, t, or r.
        """
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="subject_regex",
            condition_value=r"(approval|review|sign)"
        )
        assert rule.matches({"subject": "Please review this document"})
        assert rule.matches({"subject": "Need your approval"})
        assert rule.matches({"subject": "Please sign the contract"})
        assert not rule.matches({"subject": "Just an FYI"})

    def test_matches_subject_plain_text(self):
        """Test subject matching with plain text fallback."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="subject",
            condition_value="invoice"
        )
        assert rule.matches({"subject": "Monthly invoice attached"})
        assert rule.matches({"subject": "INVOICE DUE TODAY"})

    def test_matches_subject_invalid_regex_fallback(self):
        """Invalid regex in ``subject_regex`` must not crash, just not match."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="subject_regex",
            condition_value="[invalid(regex"  # Invalid regex
        )
        # Invalid regex → returns False (does not fall back to substring)
        assert not rule.matches({"subject": "Please [invalid(regex"})
        assert not rule.matches({"subject": "Something else"})

    def test_matches_body_regex(self):
        """Test body matching with regex via ``body_regex``.

        As with subject, ``condition_type="body"`` is literal substring
        only — use ``body_regex`` for regex semantics.
        """
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="body_regex",
            condition_value=r"(urgent|asap|immediately)"
        )
        assert rule.matches({"body": "This is urgent, please handle it"})
        assert rule.matches({"body": "Need ASAP"})
        assert not rule.matches({"body": "Standard request"})

    def test_matches_body_case_insensitive(self):
        """Test body matching is case-insensitive."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="body",
            condition_value="urgent"
        )
        assert rule.matches({"body": "This is URGENT"})

    def test_matches_cc_true(self):
        """Test CC matching when user is in CC."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="FYI",
            condition_type="cc",
            condition_value=""  # Not used for CC
        )
        assert rule.matches({"is_cc": True})

    def test_matches_cc_false(self):
        """Test CC matching when user is not in CC."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="cc",
            condition_value=""
        )
        assert not rule.matches({"is_cc": False})

    def test_matches_recipient_substring(self):
        """Test recipient matching."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="recipient",
            condition_value="team@example.com"
        )
        assert rule.matches({"recipients": ["team@example.com", "other@example.com"]})
        assert rule.matches({"recipients": ["TEAM@EXAMPLE.COM"]})
        assert not rule.matches({"recipients": ["john@example.com"]})

    def test_matches_recipient_multiple_recipients(self):
        """Test recipient matching with multiple recipients."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="recipient",
            condition_value="jane"
        )
        email = {
            "recipients": ["john@example.com", "jane@example.com", "bob@example.com"]
        }
        assert rule.matches(email)

    def test_matches_unknown_condition_type(self):
        """Test that unknown condition type returns False."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="unknown_type",
            condition_value="something"
        )
        assert not rule.matches({"subject": "Test"})

    def test_matches_missing_email_field(self):
        """Test matching when email field is missing."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com"
        )
        # Empty dict has no sender
        assert not rule.matches({})


class TestLabelingRuleRecordUse:
    """Tests for LabelingRule.record_use()."""

    def test_record_use_increments_count(self):
        """Test that record_use increments use_count."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="sender",
            condition_value="john@example.com"
        )
        assert rule.use_count == 0

        rule.record_use()
        assert rule.use_count == 1

        rule.record_use()
        assert rule.use_count == 2

    def test_record_use_sets_last_used_at(self):
        """Test that record_use updates last_used_at."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="sender",
            condition_value="john@example.com"
        )
        assert rule.last_used_at is None

        before = datetime.now().isoformat()
        rule.record_use()
        after = datetime.now().isoformat()

        assert rule.last_used_at is not None
        assert before <= rule.last_used_at <= after


class TestLabelingRuleMarkdown:
    """Tests for LabelingRule.to_markdown()."""

    def test_to_markdown_format(self):
        """Test markdown output format."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com",
            confidence=0.95,
            learned_from="email-123"
        )
        rule.use_count = 5

        markdown = rule.to_markdown()
        assert "### Règle: VIP" in markdown
        assert "**Type**: sender" in markdown
        assert "**Condition**: `john@example.com`" in markdown
        assert "95%" in markdown  # confidence * 100
        assert "**Utilisations**: 5" in markdown
        assert "email-123" in markdown

    def test_to_markdown_manual_rule(self):
        """Test markdown for manually defined rule."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="subject",
            condition_value="invoice",
            learned_from=None
        )

        markdown = rule.to_markdown()
        assert "Définie manuellement" in markdown


class TestLabelingRuleSerialization:
    """Tests for LabelingRule serialization."""

    def test_to_dict(self):
        """Test converting rule to dict."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com",
            priority=100,
            learned_from="email-123",
            confidence=0.95,
        )
        rule.use_count = 3
        rule.last_used_at = "2025-01-15T10:00:00"

        data = rule.to_dict()
        assert data["rule_id"] == "rule-1"
        assert data["label_name"] == "VIP"
        assert data["condition_type"] == "sender"
        assert data["condition_value"] == "john@example.com"
        assert data["priority"] == 100
        assert data["learned_from"] == "email-123"
        assert data["confidence"] == 0.95
        assert data["use_count"] == 3
        assert data["last_used_at"] == "2025-01-15T10:00:00"

    def test_from_dict(self):
        """Test creating rule from dict."""
        data = {
            "rule_id": "rule-1",
            "label_name": "VIP",
            "condition_type": "sender",
            "condition_value": "john@example.com",
            "priority": 100,
            "learned_from": "email-123",
            "confidence": 0.95,
            "use_count": 3,
        }
        rule = LabelingRule.from_dict(data)
        assert rule.rule_id == "rule-1"
        assert rule.label_name == "VIP"
        assert rule.priority == 100
        assert rule.confidence == 0.95

    def test_from_dict_defaults(self):
        """Test from_dict applies correct defaults."""
        data = {
            "rule_id": "rule-1",
            "label_name": "Action",
            "condition_type": "subject",
            "condition_value": "urgent",
        }
        rule = LabelingRule.from_dict(data)
        assert rule.priority == 50
        assert rule.confidence == 1.0
        assert rule.is_active is True
        assert rule.use_count == 0

    def test_to_dict_from_dict_roundtrip(self):
        """Test round-trip serialization."""
        original = LabelingRule(
            rule_id="rule-1",
            label_name="VIP",
            condition_type="sender",
            condition_value="john@example.com",
            priority=100,
            learned_from="email-123",
            confidence=0.95,
            use_count=5,
            is_active=True,
            total_matches=10,
            corrections=1,
        )

        data = original.to_dict()
        restored = LabelingRule.from_dict(data)

        assert restored.rule_id == original.rule_id
        assert restored.label_name == original.label_name
        assert restored.condition_type == original.condition_type
        assert restored.priority == original.priority
        assert restored.learned_from == original.learned_from
        assert restored.confidence == original.confidence


# ============================================================================
# Module-Level Functions Tests
# ============================================================================

class TestGetDefaultLabels:
    """Tests for get_default_labels() function."""

    def test_get_default_labels_returns_three(self):
        """Test that get_default_labels returns exactly 3 labels."""
        labels = get_default_labels()
        assert len(labels) == 3

    def test_get_default_labels_contains_action(self):
        """Test that default labels include Action."""
        labels = get_default_labels()
        label_names = [label.name for label in labels]
        assert "Action" in label_names

    def test_get_default_labels_contains_fyi(self):
        """Test that default labels include FYI."""
        labels = get_default_labels()
        label_names = [label.name for label in labels]
        assert "FYI" in label_names

    def test_get_default_labels_contains_noise(self):
        """Test that default labels include Noise."""
        labels = get_default_labels()
        label_names = [label.name for label in labels]
        assert "Noise" in label_names

    def test_get_default_labels_all_are_default(self):
        """Test that all returned labels are marked as default."""
        labels = get_default_labels()
        assert all(label.is_default for label in labels)

    def test_get_default_labels_have_rules(self):
        """Test that all default labels have rules."""
        labels = get_default_labels()
        assert all(label.rules for label in labels)

    def test_get_default_labels_have_colors(self):
        """Test that all default labels have colors."""
        labels = get_default_labels()
        assert all(label.color for label in labels)


class TestDefaultLabelNames:
    """Tests for DEFAULT_LABEL_NAMES constant."""

    def test_default_label_names_is_set(self):
        """Test that DEFAULT_LABEL_NAMES is a set."""
        assert isinstance(DEFAULT_LABEL_NAMES, set)

    def test_default_label_names_contains_three(self):
        """Test that DEFAULT_LABEL_NAMES has 3 entries."""
        assert len(DEFAULT_LABEL_NAMES) == 3

    def test_default_label_names_contains_action(self):
        """Test that DEFAULT_LABEL_NAMES includes 'Action'."""
        assert "Action" in DEFAULT_LABEL_NAMES

    def test_default_label_names_contains_fyi(self):
        """Test that DEFAULT_LABEL_NAMES includes 'FYI'."""
        assert "FYI" in DEFAULT_LABEL_NAMES

    def test_default_label_names_contains_noise(self):
        """Test that DEFAULT_LABEL_NAMES includes 'Noise'."""
        assert "Noise" in DEFAULT_LABEL_NAMES

    def test_default_label_names_matches_enum(self):
        """Test that DEFAULT_LABEL_NAMES matches DefaultLabel enum values."""
        enum_values = {label.value for label in DefaultLabel}
        assert DEFAULT_LABEL_NAMES == enum_values
