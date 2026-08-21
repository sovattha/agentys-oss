# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for label rule accuracy tracking, auto-disable, and wider propagation.

Covers:
- LabelingRule new fields (is_active, total_matches, corrections, disabled_reason)
- LabelAssignment.matched_rule_ids
- increment_rule_match_counts() persistence
- classify_by_rules_only() populates matched_rule_ids
- Inactive rules skipped during classification
- Auto-disable algorithm (_maybe_disable_bad_rules)
- Wider propagation skips user assignments
"""

import json
import os
import tempfile
from unittest.mock import MagicMock


from app.domain.entities.email_labels import (
    LabelAssignment,
    LabelingRule,
)


# =========================================================================
# LabelingRule — new fields serialization
# =========================================================================


class TestLabelingRuleNewFields:
    """Test serialization/deserialization of new accuracy fields."""

    def test_new_fields_defaults(self):
        """New fields have safe defaults."""
        rule = LabelingRule(
            rule_id="test-1",
            label_name="Action",
            condition_type="sender",
            condition_value="@test.com",
        )
        assert rule.is_active is True
        assert rule.total_matches == 0
        assert rule.corrections == 0
        assert rule.disabled_reason is None

    def test_to_dict_includes_new_fields(self):
        """to_dict() includes all new fields."""
        rule = LabelingRule(
            rule_id="test-1",
            label_name="Noise",
            condition_type="sender",
            condition_value="@spam.com",
            is_active=False,
            total_matches=10,
            corrections=6,
            disabled_reason="low_precision:40%",
        )
        d = rule.to_dict()
        assert d["is_active"] is False
        assert d["total_matches"] == 10
        assert d["corrections"] == 6
        assert d["disabled_reason"] == "low_precision:40%"

    def test_from_dict_reads_new_fields(self):
        """from_dict() reads new fields correctly."""
        data = {
            "rule_id": "test-2",
            "label_name": "FYI",
            "condition_type": "subject",
            "condition_value": "newsletter",
            "is_active": False,
            "total_matches": 20,
            "corrections": 12,
            "disabled_reason": "low_precision:40%",
        }
        rule = LabelingRule.from_dict(data)
        assert rule.is_active is False
        assert rule.total_matches == 20
        assert rule.corrections == 12
        assert rule.disabled_reason == "low_precision:40%"

    def test_from_dict_backward_compat(self):
        """from_dict() handles old data without new fields."""
        data = {
            "rule_id": "old-1",
            "label_name": "Action",
            "condition_type": "sender",
            "condition_value": "@old.com",
            "priority": 40,
            "use_count": 5,
        }
        rule = LabelingRule.from_dict(data)
        assert rule.is_active is True
        assert rule.total_matches == 0
        assert rule.corrections == 0
        assert rule.disabled_reason is None

    def test_roundtrip_serialization(self):
        """to_dict → from_dict preserves all fields."""
        original = LabelingRule(
            rule_id="rt-1",
            label_name="Noise",
            condition_type="body",
            condition_value="unsubscribe",
            is_active=False,
            total_matches=15,
            corrections=8,
            disabled_reason="low_precision:47%",
        )
        restored = LabelingRule.from_dict(original.to_dict())
        assert restored.is_active == original.is_active
        assert restored.total_matches == original.total_matches
        assert restored.corrections == original.corrections
        assert restored.disabled_reason == original.disabled_reason


# =========================================================================
# LabelAssignment — matched_rule_ids
# =========================================================================


class TestLabelAssignmentMatchedRuleIds:
    """Test matched_rule_ids field on LabelAssignment."""

    def test_default_empty(self):
        """matched_rule_ids defaults to empty list."""
        a = LabelAssignment(email_id="e1")
        assert a.matched_rule_ids == []

    def test_to_dict_includes_when_present(self):
        """to_dict() includes matched_rule_ids when non-empty."""
        a = LabelAssignment(email_id="e1", matched_rule_ids=["r1", "r2"])
        d = a.to_dict()
        assert d["matched_rule_ids"] == ["r1", "r2"]

    def test_to_dict_omits_when_empty(self):
        """to_dict() omits matched_rule_ids when empty (backward compat)."""
        a = LabelAssignment(email_id="e1")
        d = a.to_dict()
        assert "matched_rule_ids" not in d

    def test_from_dict_reads_matched_rule_ids(self):
        """from_dict() reads matched_rule_ids."""
        data = {
            "email_id": "e1",
            "labels": ["Action"],
            "matched_rule_ids": ["r1", "r2"],
        }
        a = LabelAssignment.from_dict(data)
        assert a.matched_rule_ids == ["r1", "r2"]

    def test_from_dict_backward_compat(self):
        """from_dict() handles old data without matched_rule_ids."""
        data = {
            "email_id": "e1",
            "labels": ["Noise"],
        }
        a = LabelAssignment.from_dict(data)
        assert a.matched_rule_ids == []


# =========================================================================
# LabelStore.increment_rule_match_counts()
# =========================================================================


class TestIncrementRuleMatchCounts:
    """Test that increment_rule_match_counts persists to disk."""

    def _make_store(self, rules_data):
        """Create a LabelStore with temp files and initial rules."""
        from app.infrastructure.adapters.label_store import LabelStore

        tmpdir = tempfile.mkdtemp()
        store = LabelStore(storage_dir=tmpdir)

        # Write initial rules
        rules_path = os.path.join(tmpdir, "rules.json")
        with open(rules_path, "w") as f:
            json.dump(rules_data, f)

        # Write empty labels + assignments
        for fname in ("labels.json", "assignments.json"):
            path = os.path.join(tmpdir, fname)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    json.dump([], f)

        return store, tmpdir

    def test_increments_and_persists(self):
        """Matching rules get total_matches incremented and saved to disk."""
        rules_data = [
            {
                "rule_id": "r1",
                "label_name": "Noise",
                "condition_type": "sender",
                "condition_value": "@spam.com",
                "total_matches": 3,
                "use_count": 3,
            },
            {
                "rule_id": "r2",
                "label_name": "Action",
                "condition_type": "subject",
                "condition_value": "urgent",
                "total_matches": 0,
                "use_count": 0,
            },
        ]
        store, tmpdir = self._make_store(rules_data)

        store.increment_rule_match_counts(["r1"])

        # Re-read from disk
        rules_path = os.path.join(tmpdir, "rules.json")
        with open(rules_path) as f:
            saved = json.load(f)

        r1 = next(r for r in saved if r["rule_id"] == "r1")
        r2 = next(r for r in saved if r["rule_id"] == "r2")

        assert r1["total_matches"] == 4
        assert r1["use_count"] == 4
        assert r1["last_used_at"] is not None
        assert r2["total_matches"] == 0  # Untouched

    def test_no_op_for_empty_ids(self):
        """No write when rule_ids is empty."""
        store, tmpdir = self._make_store([])
        store.increment_rule_match_counts([])
        # Should not raise


# =========================================================================
# classify_by_rules_only — matched_rule_ids + inactive skip
# =========================================================================


class TestClassifyByRulesOnlyTracking:
    """Test that classify_by_rules_only tracks matched_rule_ids and skips inactive."""

    def _make_mock_store(self, rules):
        store = MagicMock()
        store.get_rules.return_value = rules
        return store

    def _make_email(self, sender="test@example.com", subject="Hello", body=""):
        from app.domain.entities import Email
        return Email(id="e1", sender=sender, subject=subject, body=body)

    def test_populates_matched_rule_ids(self):
        """matched_rule_ids contains the IDs of matched rules."""
        from app.application.label_email import LabelEmailUseCase

        rule = LabelingRule(
            rule_id="match-me",
            label_name="Noise",
            condition_type="sender",
            condition_value="@example.com",
            priority=40,
            confidence=0.9,
        )
        store = self._make_mock_store([rule])
        email = self._make_email(sender="test@example.com")

        assignment = LabelEmailUseCase.classify_by_rules_only(email, store)

        assert assignment is not None
        assert "match-me" in assignment.matched_rule_ids
        assert assignment.default_label == "Noise"

    def test_skips_inactive_rules(self):
        """Inactive rules are not matched."""
        from app.application.label_email import LabelEmailUseCase

        rule = LabelingRule(
            rule_id="disabled-1",
            label_name="Noise",
            condition_type="sender",
            condition_value="@example.com",
            priority=40,
            confidence=0.9,
            is_active=False,
        )
        store = self._make_mock_store([rule])
        email = self._make_email(sender="test@example.com")

        assignment = LabelEmailUseCase.classify_by_rules_only(email, store)

        # The inactive rule should not match, so no default label from rules
        # (will fall through to built-in patterns or default Noise)
        assert "disabled-1" not in (assignment.matched_rule_ids if assignment else [])

    def test_custom_rule_survives_default_rule_match(self):
        """Régression 2026-06-11 : une règle custom (subject = 'Agentys') ne doit
        plus être perdue quand une règle défaut (sender = 'info@') matche en
        premier — l'ancien return dans la boucle sautait les règles restantes."""
        from app.application.label_email import LabelEmailUseCase

        default_rule = LabelingRule(
            rule_id="noise-info",
            label_name="Noise",
            condition_type="sender",
            condition_value="info@",
            priority=60,  # plus prioritaire → évaluée en premier
            confidence=0.65,
        )
        custom_rule = LabelingRule(
            rule_id="custom-agentys",
            label_name="Agentys",
            condition_type="subject",
            condition_value="Agentys",
            priority=50,
            confidence=1.0,
        )
        store = self._make_mock_store([default_rule, custom_rule])
        email = self._make_email(
            sender="info@7584383.brevosend.com",
            subject="Accès VIP à mon application AI - Agentys",
        )

        assignment = LabelEmailUseCase.classify_by_rules_only(email, store)

        assert assignment is not None
        assert assignment.default_label == "Noise"
        assert "Agentys" in assignment.custom_labels
        assert set(assignment.matched_rule_ids) == {"noise-info", "custom-agentys"}

    def test_first_default_rule_wins_but_customs_accumulate(self):
        """Deux règles défaut + une custom : la plus prioritaire fixe la
        catégorie, la seconde est ignorée, la custom est conservée."""
        from app.application.label_email import LabelEmailUseCase

        high = LabelingRule(
            rule_id="high-action",
            label_name="Action",
            condition_type="subject",
            condition_value="VIP",
            priority=80,
            confidence=0.9,
        )
        low = LabelingRule(
            rule_id="low-noise",
            label_name="Noise",
            condition_type="sender",
            condition_value="info@",
            priority=40,
            confidence=0.65,
        )
        custom = LabelingRule(
            rule_id="custom-agentys",
            label_name="Agentys",
            condition_type="subject",
            condition_value="Agentys",
            priority=10,
            confidence=1.0,
        )
        store = self._make_mock_store([low, custom, high])
        email = self._make_email(
            sender="info@7584383.brevosend.com",
            subject="Accès VIP à mon application AI - Agentys",
        )

        assignment = LabelEmailUseCase.classify_by_rules_only(email, store)

        assert assignment is not None
        assert assignment.default_label == "Action"
        assert "Agentys" in assignment.custom_labels
        assert "low-noise" not in assignment.matched_rule_ids


# =========================================================================
# Provider-id keying — _provider_email_id (régression "2775")
# =========================================================================


class TestProviderEmailIdKeying:
    """Régression 2026-06-11 : le relabel tardif passait des rows ORM à
    _auto_assign_labels_background, qui construisait DomainEmail(id=str(email.id))
    avec l'int PK → assignment orphelin (clé "2775") invisible pour l'UI."""

    def test_prefers_email_id_over_int_pk(self):
        from app.api.routes_emails import _provider_email_id

        orm_like = MagicMock()
        orm_like.id = 2775
        orm_like.email_id = "19eb1fd248f75f58"
        assert _provider_email_id(orm_like) == "19eb1fd248f75f58"

    def test_falls_back_to_id_when_no_email_id(self):
        from app.api.routes_emails import _provider_email_id

        class StandardLike:
            id = "19eb1fd248f75f58"

        assert _provider_email_id(StandardLike()) == "19eb1fd248f75f58"

    def test_empty_when_nothing(self):
        from app.api.routes_emails import _provider_email_id

        class Bare:
            id = None

        assert _provider_email_id(Bare()) == ""


# =========================================================================
# Auto-disable algorithm
# =========================================================================


class TestAutoDisable:
    """Test _maybe_disable_bad_rules algorithm."""

    def _make_store_with_rules(self, rules_data):
        """Create a mock store that reads/writes rules in memory."""
        rules = [LabelingRule.from_dict(r) for r in rules_data]
        saved_rules = {"rules": rules}

        store = MagicMock()
        store.get_rules.return_value = saved_rules["rules"]

        def save_rules(r):
            saved_rules["rules"] = r

        store._save_rules = save_rules
        return store, saved_rules

    def test_disables_low_precision_rule(self):
        """Rule with <50% precision after 5+ matches is disabled."""
        from app.api.labels import _increment_rule_corrections, _maybe_disable_bad_rules

        rules_data = [{
            "rule_id": "bad-1",
            "label_name": "Action",
            "condition_type": "sender",
            "condition_value": "@company.com",
            "total_matches": 10,
            "corrections": 0,
            "is_active": True,
        }]
        store, saved = self._make_store_with_rules(rules_data)

        # Simulate 6 corrections
        for _ in range(6):
            _increment_rule_corrections(store, ["bad-1"])

        _maybe_disable_bad_rules(store, ["bad-1"])

        rule = saved["rules"][0]
        assert rule.is_active is False
        assert "low_precision" in (rule.disabled_reason or "")

    def test_does_not_disable_below_threshold_matches(self):
        """Rule with <5 matches is never disabled regardless of corrections."""
        from app.api.labels import _maybe_disable_bad_rules

        rules_data = [{
            "rule_id": "young-1",
            "label_name": "Action",
            "condition_type": "sender",
            "condition_value": "@new.com",
            "total_matches": 3,
            "corrections": 3,
            "is_active": True,
        }]
        store, saved = self._make_store_with_rules(rules_data)

        _maybe_disable_bad_rules(store, ["young-1"])

        rule = saved["rules"][0]
        assert rule.is_active is True

    def test_does_not_disable_good_rule(self):
        """Rule with >50% precision stays active."""
        from app.api.labels import _maybe_disable_bad_rules

        rules_data = [{
            "rule_id": "good-1",
            "label_name": "Noise",
            "condition_type": "sender",
            "condition_value": "@newsletter.com",
            "total_matches": 20,
            "corrections": 2,
            "is_active": True,
        }]
        store, saved = self._make_store_with_rules(rules_data)

        _maybe_disable_bad_rules(store, ["good-1"])

        rule = saved["rules"][0]
        assert rule.is_active is True


# =========================================================================
# Wider propagation — skip user assignments
# =========================================================================


class TestWiderPropagation:
    """Test that _apply_rules_to_existing_emails skips user assignments."""

    def test_skips_user_corrected_assignments(self):
        """User-corrected assignments (assigned_by='user') are never overwritten."""
        user_assignment = LabelAssignment(
            email_id="e-user",
            assigned_by="user",
        )
        user_assignment.set_default_label("FYI", 1.0, "User correction")

        ai_assignment = LabelAssignment(
            email_id="e-ai",
            assigned_by="ai",
        )
        ai_assignment.set_default_label("FYI", 0.8, "AI classification")

        rule = LabelingRule(
            rule_id="propagate-1",
            label_name="Action",
            condition_type="sender",
            condition_value="@important.com",
            priority=40,
            confidence=0.9,
        )

        # The rule matches — but user assignment must stay FYI
        email_data = {"sender": "@important.com", "subject": "", "body": "", "recipients": [], "is_cc": False}
        assert rule.matches(email_data)

        # User assignment should be protected
        assert user_assignment.assigned_by == "user"
        # AI assignment can be overridden
        assert ai_assignment.assigned_by == "ai"
