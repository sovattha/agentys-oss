# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les règles de routage.

pytest tests/test_routing.py -v
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.routing import (
    RoutingAction,
    MatchType,
    RoutingRule,
    RoutingEngine,
    DEFAULT_RULES,
    route_email,
    create_routing_rule,
    should_skip_email,
    should_force_review,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def routing_engine(tmp_path):
    """Crée un moteur avec fichier temporaire."""
    filepath = tmp_path / "routing_rules.json"
    return RoutingEngine(filepath=filepath)


@pytest.fixture
def sample_rule():
    """Règle de test."""
    return RoutingRule(
        id="test-rule",
        name="Test Rule",
        conditions=[
            {"field": "sender", "match_type": "contains", "value": "@test.com"},
        ],
        action=RoutingAction.PRIORITY_HIGH.value,
        priority=50,
    )


# ============================================================================
# TESTS ENUMS
# ============================================================================

class TestEnums:
    """Tests pour les enums."""

    def test_routing_actions(self):
        """Vérification des actions."""
        assert RoutingAction.PROCESS.value == "process"
        assert RoutingAction.SKIP.value == "skip"
        assert RoutingAction.PRIORITY_HIGH.value == "priority_high"
        assert RoutingAction.REVIEW.value == "review"

    def test_match_types(self):
        """Vérification des types de matching."""
        assert MatchType.EXACT.value == "exact"
        assert MatchType.CONTAINS.value == "contains"
        assert MatchType.REGEX.value == "regex"
        assert MatchType.DOMAIN.value == "domain"


# ============================================================================
# TESTS DATACLASSES
# ============================================================================

class TestRoutingRule:
    """Tests pour RoutingRule."""

    def test_creation(self):
        """Création d'une règle."""
        rule = RoutingRule(
            id="rule-001",
            name="My Rule",
            conditions=[{"field": "sender", "match_type": "contains", "value": "test"}],
            action=RoutingAction.SKIP.value,
        )

        assert rule.id == "rule-001"
        assert rule.enabled is True
        assert rule.priority == 0

    def test_default_values(self):
        """Valeurs par défaut."""
        rule = RoutingRule(
            id="rule-002",
            name="Rule",
            conditions=[],
            action="process",
        )

        assert rule.enabled is True
        assert rule.match_count == 0
        assert rule.last_matched is None


# ============================================================================
# TESTS ROUTING ENGINE
# ============================================================================

class TestRoutingEngine:
    """Tests pour le moteur de routage."""

    def test_init_with_defaults(self, routing_engine):
        """Initialisation avec règles par défaut."""
        rules = routing_engine.get_all_rules()
        assert len(rules) >= len(DEFAULT_RULES)

    def test_add_rule(self, routing_engine, sample_rule):
        """Ajout d'une règle."""
        routing_engine.add_rule(sample_rule)

        retrieved = routing_engine.get_rule(sample_rule.id)
        assert retrieved is not None
        assert retrieved.name == sample_rule.name

    def test_remove_rule(self, routing_engine, sample_rule):
        """Suppression d'une règle."""
        routing_engine.add_rule(sample_rule)

        result = routing_engine.remove_rule(sample_rule.id)

        assert result is True
        assert routing_engine.get_rule(sample_rule.id) is None

    def test_remove_nonexistent(self, routing_engine):
        """Suppression d'une règle inexistante."""
        result = routing_engine.remove_rule("nonexistent")
        assert result is False

    def test_rules_sorted_by_priority(self, routing_engine):
        """Règles triées par priorité."""
        rule_low = RoutingRule(
            id="low", name="Low", conditions=[], action="process", priority=10
        )
        rule_high = RoutingRule(
            id="high", name="High", conditions=[], action="process", priority=90
        )

        routing_engine.add_rule(rule_low)
        routing_engine.add_rule(rule_high)

        rules = routing_engine.get_all_rules()
        # Les plus prioritaires en premier
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities, reverse=True)


class TestRoutingEvaluation:
    """Tests pour l'évaluation des règles."""

    def test_evaluate_no_match(self, routing_engine):
        """Aucune règle ne matche."""
        result = routing_engine.evaluate(
            sender="normal@example.com",
            subject="Normal subject",
            body="Normal body",
        )

        assert result.action == RoutingAction.PROCESS
        assert result.rule is None

    def test_evaluate_skip_noreply(self, routing_engine):
        """Match de la règle noreply."""
        result = routing_engine.evaluate(
            sender="noreply@company.com",
            subject="Notification",
            body="Auto-generated message",
        )

        assert result.action == RoutingAction.SKIP

    def test_evaluate_contains_match(self, routing_engine, sample_rule):
        """Match avec contains."""
        routing_engine.add_rule(sample_rule)

        result = routing_engine.evaluate(
            sender="user@test.com",
            subject="Hello",
            body="Body",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH
        assert result.rule.id == sample_rule.id

    def test_evaluate_exact_match(self, routing_engine):
        """Match exact."""
        rule = RoutingRule(
            id="exact",
            name="Exact Match",
            conditions=[
                {"field": "sender", "match_type": "exact", "value": "ceo@company.com"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=100,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="ceo@company.com",
            subject="Important",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_regex_match(self, routing_engine):
        """Match regex."""
        rule = RoutingRule(
            id="regex",
            name="Regex Match",
            conditions=[
                {"field": "subject", "match_type": "regex", "value": r"urgent|asap"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=80,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="user@example.com",
            subject="This is URGENT please",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_domain_match(self, routing_engine):
        """Match par domaine."""
        rule = RoutingRule(
            id="domain",
            name="Domain Match",
            conditions=[
                {"field": "domain", "match_type": "domain", "value": "vip.com"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=70,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="user@vip.com",
            subject="Hello",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_starts_with(self, routing_engine):
        """Match starts_with."""
        rule = RoutingRule(
            id="starts",
            name="Starts With",
            conditions=[
                {"field": "subject", "match_type": "starts_with", "value": "[URGENT]"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=75,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="user@example.com",
            subject="[URGENT] Please respond",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_ends_with(self, routing_engine):
        """Match ends_with."""
        rule = RoutingRule(
            id="ends",
            name="Ends With",
            conditions=[
                {"field": "sender", "match_type": "ends_with", "value": "@company.com"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=60,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="ceo@company.com",
            subject="Meeting",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_case_insensitive(self, routing_engine):
        """Match insensible à la casse."""
        rule = RoutingRule(
            id="case",
            name="Case Insensitive",
            conditions=[
                {"field": "subject", "match_type": "contains", "value": "urgent", "case_sensitive": False},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=65,
        )
        routing_engine.add_rule(rule)

        result = routing_engine.evaluate(
            sender="user@example.com",
            subject="This is URGENT",
            body="",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_evaluate_multiple_conditions_or(self, routing_engine):
        """Plusieurs conditions sur le même champ (OR)."""
        rule = RoutingRule(
            id="or",
            name="OR Conditions",
            conditions=[
                {"field": "sender", "match_type": "contains", "value": "noreply@"},
                {"field": "sender", "match_type": "contains", "value": "no-reply@"},
            ],
            action=RoutingAction.SKIP.value,
            priority=90,
        )
        routing_engine.add_rule(rule)

        result1 = routing_engine.evaluate(
            sender="noreply@company.com",
            subject="Test",
            body="",
        )
        result2 = routing_engine.evaluate(
            sender="no-reply@company.com",
            subject="Test",
            body="",
        )

        assert result1.action == RoutingAction.SKIP
        assert result2.action == RoutingAction.SKIP

    def test_evaluate_increments_match_count(self, routing_engine, sample_rule):
        """Le match incrémente le compteur."""
        routing_engine.add_rule(sample_rule)
        initial_count = sample_rule.match_count

        routing_engine.evaluate(
            sender="user@test.com",
            subject="Test",
            body="",
        )

        updated = routing_engine.get_rule(sample_rule.id)
        assert updated.match_count == initial_count + 1

    def test_evaluate_disabled_rule(self, routing_engine, sample_rule):
        """Les règles désactivées sont ignorées."""
        sample_rule.enabled = False
        routing_engine.add_rule(sample_rule)

        result = routing_engine.evaluate(
            sender="user@test.com",
            subject="Test",
            body="",
        )

        # Ne devrait pas matcher la règle désactivée
        assert result.rule is None or result.rule.id != sample_rule.id


class TestRoutingStats:
    """Tests pour les statistiques."""

    def test_get_stats(self, routing_engine):
        """Statistiques de routage."""
        stats = routing_engine.get_stats()

        assert "total_rules" in stats
        assert "enabled_rules" in stats
        assert "by_action" in stats
        assert "most_matched" in stats

    def test_most_matched(self, routing_engine, sample_rule):
        """Règles les plus matchées."""
        routing_engine.add_rule(sample_rule)

        # Matcher plusieurs fois
        for _ in range(5):
            routing_engine.evaluate(
                sender="user@test.com",
                subject="Test",
                body="",
            )

        stats = routing_engine.get_stats()
        most_matched = stats["most_matched"]

        assert len(most_matched) > 0


# ============================================================================
# TESTS PERSISTENCE
# ============================================================================

class TestPersistence:
    """Tests pour la persistance."""

    def test_save_and_load(self, tmp_path, sample_rule):
        """Sauvegarde et rechargement."""
        filepath = tmp_path / "rules.json"

        engine1 = RoutingEngine(filepath=filepath)
        engine1.add_rule(sample_rule)
        rule_id = sample_rule.id

        engine2 = RoutingEngine(filepath=filepath)
        loaded = engine2.get_rule(rule_id)

        assert loaded is not None
        assert loaded.name == sample_rule.name

    def test_persistence_match_count(self, tmp_path, sample_rule):
        """Persistance du compteur de match."""
        filepath = tmp_path / "rules.json"

        engine1 = RoutingEngine(filepath=filepath)
        engine1.add_rule(sample_rule)
        engine1.evaluate(sender="user@test.com", subject="Test", body="")
        engine1.evaluate(sender="user@test.com", subject="Test2", body="")

        engine2 = RoutingEngine(filepath=filepath)
        loaded = engine2.get_rule(sample_rule.id)

        assert loaded.match_count == 2


# ============================================================================
# TESTS HELPERS
# ============================================================================

class TestHelpers:
    """Tests pour les fonctions helper."""

    def test_route_email(self, tmp_path):
        """Fonction route_email."""
        with patch("app.routing._routing_engine", None):
            with patch("app.routing.ROUTING_RULES_FILE", tmp_path / "rules.json"):
                with patch("app.routing.ROUTING_ENABLED", True):
                    result = route_email(
                        sender="noreply@company.com",
                        subject="Test",
                        body="",
                    )

                    # Devrait matcher la règle noreply par défaut
                    assert result.action == RoutingAction.SKIP

    def test_route_email_disabled(self):
        """Routage désactivé."""
        with patch("app.routing.ROUTING_ENABLED", False):
            result = route_email(
                sender="noreply@company.com",
                subject="Test",
                body="",
            )

            assert result.action == RoutingAction.PROCESS

    def test_should_skip_email(self, tmp_path):
        """Fonction should_skip_email."""
        with patch("app.routing._routing_engine", None):
            with patch("app.routing.ROUTING_RULES_FILE", tmp_path / "rules.json"):
                with patch("app.routing.ROUTING_ENABLED", True):
                    skip = should_skip_email(
                        sender="noreply@company.com",
                        subject="Notification",
                    )
                    assert skip is True

                    no_skip = should_skip_email(
                        sender="user@example.com",
                        subject="Hello",
                    )
                    assert no_skip is False

    def test_should_force_review(self, tmp_path):
        """Fonction should_force_review."""
        with patch("app.routing._routing_engine", None):
            with patch("app.routing.ROUTING_RULES_FILE", tmp_path / "rules.json"):
                with patch("app.routing.ROUTING_ENABLED", True):
                    review = should_force_review(
                        sender="legal@company.com",
                        subject="Contrat à signer",
                    )
                    assert review is True

    def test_create_routing_rule(self, tmp_path):
        """Création rapide de règle."""
        with patch("app.routing._routing_engine", None):
            with patch("app.routing.ROUTING_RULES_FILE", tmp_path / "rules.json"):
                rule = create_routing_rule(
                    name="Quick Rule",
                    conditions=[
                        {"field": "sender", "match_type": "contains", "value": "@vip.com"},
                    ],
                    action=RoutingAction.PRIORITY_HIGH,
                    priority=80,
                )

                assert rule.id is not None
                assert rule.name == "Quick Rule"


# ============================================================================
# TESTS DEFAULT RULES
# ============================================================================

class TestDefaultRules:
    """Tests pour les règles par défaut."""

    def test_default_rules_valid(self):
        """Validation des règles par défaut."""
        assert len(DEFAULT_RULES) >= 6

        for rule in DEFAULT_RULES:
            assert rule.id is not None
            assert rule.name is not None
            assert rule.conditions is not None
            assert rule.action is not None

    def test_default_rules_actions(self):
        """Actions des règles par défaut."""
        actions = {r.action for r in DEFAULT_RULES}

        assert RoutingAction.SKIP.value in actions
        assert RoutingAction.PRIORITY_HIGH.value in actions

    def test_urgent_keywords_rule_exists(self):
        """La règle pour les mots-clés urgents doit exister."""
        rule_ids = {r.id for r in DEFAULT_RULES}
        assert "priority-urgent-keywords" in rule_ids

        urgent_rule = next(r for r in DEFAULT_RULES if r.id == "priority-urgent-keywords")
        assert urgent_rule.action == RoutingAction.PRIORITY_HIGH.value
        assert urgent_rule.priority >= 80


class TestUrgentKeywords:
    """Tests pour les mots-clés urgents."""

    def test_urgent_keyword_in_subject(self, routing_engine):
        """Email avec 'urgent' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="client@example.com",
            subject="Demande URGENTE de devis",
            body="Merci de me répondre rapidement.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH
        assert result.rule is not None
        assert result.rule.id == "priority-urgent-keywords"

    def test_asap_keyword_in_subject(self, routing_engine):
        """Email avec 'ASAP' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="manager@company.com",
            subject="Need response ASAP",
            body="Please reply quickly.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_prioritaire_keyword_in_subject(self, routing_engine):
        """Email avec 'prioritaire' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="client@example.com",
            subject="Dossier prioritaire - Réponse attendue",
            body="Cordialement",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_critique_keyword_in_subject(self, routing_engine):
        """Email avec 'critique' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="ops@company.com",
            subject="Incident critique en production",
            body="Le serveur est down.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_emergency_keyword_in_subject(self, routing_engine):
        """Email avec 'emergency' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="support@vendor.com",
            subject="EMERGENCY: System outage",
            body="Immediate attention required.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_important_keyword_in_subject(self, routing_engine):
        """Email avec 'important' dans le sujet doit être priorisé."""
        result = routing_engine.evaluate(
            sender="hr@company.com",
            subject="Message important concernant votre dossier",
            body="Veuillez prendre connaissance.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_urgent_keyword_in_body(self, routing_engine):
        """Email avec 'urgent' dans le body doit aussi être priorisé."""
        result = routing_engine.evaluate(
            sender="client@example.com",
            subject="Demande de renseignements",
            body="C'est urgent, merci de répondre au plus vite.",
        )

        assert result.action == RoutingAction.PRIORITY_HIGH

    def test_normal_email_not_prioritized(self, routing_engine):
        """Email sans mots-clés urgents ne doit pas être priorisé par cette règle."""
        result = routing_engine.evaluate(
            sender="friend@example.com",
            subject="Salut, comment vas-tu ?",
            body="J'espère que tout va bien.",
        )

        # Ne devrait pas matcher la règle urgente (mais peut matcher d'autres règles)
        if result.rule:
            assert result.rule.id != "priority-urgent-keywords"

    def test_case_insensitive_matching(self, routing_engine):
        """Le matching doit être insensible à la casse."""
        result_lower = routing_engine.evaluate(
            sender="client@example.com",
            subject="demande urgent",
            body="",
        )
        result_upper = routing_engine.evaluate(
            sender="client@example.com",
            subject="DEMANDE URGENT",
            body="",
        )
        result_mixed = routing_engine.evaluate(
            sender="client@example.com",
            subject="Demande UrGeNt",
            body="",
        )

        assert result_lower.action == RoutingAction.PRIORITY_HIGH
        assert result_upper.action == RoutingAction.PRIORITY_HIGH
        assert result_mixed.action == RoutingAction.PRIORITY_HIGH


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

# ============================================================================
# TESTS VIP NOTIFICATION
# ============================================================================

class TestVIPNotification:
    """Tests pour la fonctionnalité VIP avec notification immédiate."""

    def test_vip_notify_action_exists(self):
        """L'action VIP_NOTIFY doit exister."""
        assert RoutingAction.VIP_NOTIFY.value == "vip_notify"

    def test_vip_rule_matches_sender(self, routing_engine):
        """Une règle VIP matche un expéditeur spécifique."""
        vip_rule = RoutingRule(
            id="vip-ceo",
            name="VIP CEO",
            conditions=[
                {"field": "sender", "match_type": "exact", "value": "ceo@company.com"},
            ],
            action=RoutingAction.VIP_NOTIFY.value,
            priority=200,
            description="Notification immédiate pour le CEO",
        )
        routing_engine.add_rule(vip_rule)

        result = routing_engine.evaluate(
            sender="ceo@company.com",
            subject="Meeting tomorrow",
            body="",
        )

        assert result.action == RoutingAction.VIP_NOTIFY
        assert result.rule.id == "vip-ceo"

    def test_vip_rule_matches_domain(self, routing_engine):
        """Une règle VIP peut matcher un domaine entier."""
        vip_rule = RoutingRule(
            id="vip-domain",
            name="VIP Partner Domain",
            conditions=[
                {"field": "domain", "match_type": "domain", "value": "vip-partner.com"},
            ],
            action=RoutingAction.VIP_NOTIFY.value,
            priority=150,
            description="Notification immédiate pour les partenaires VIP",
        )
        routing_engine.add_rule(vip_rule)

        result = routing_engine.evaluate(
            sender="anyone@vip-partner.com",
            subject="New deal",
            body="",
        )

        assert result.action == RoutingAction.VIP_NOTIFY

    def test_vip_priority_over_other_rules(self, routing_engine):
        """Les règles VIP ont priorité sur les autres."""
        priority_rule = RoutingRule(
            id="priority-rule",
            name="Priority Rule",
            conditions=[
                {"field": "sender", "match_type": "contains", "value": "@company.com"},
            ],
            action=RoutingAction.PRIORITY_HIGH.value,
            priority=90,
        )
        vip_rule = RoutingRule(
            id="vip-cto",
            name="VIP CTO",
            conditions=[
                {"field": "sender", "match_type": "exact", "value": "cto@company.com"},
            ],
            action=RoutingAction.VIP_NOTIFY.value,
            priority=200,
        )
        routing_engine.add_rule(priority_rule)
        routing_engine.add_rule(vip_rule)

        result = routing_engine.evaluate(
            sender="cto@company.com",
            subject="Important",
            body="",
        )

        assert result.action == RoutingAction.VIP_NOTIFY


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_conditions(self, routing_engine):
        """Règle sans conditions."""
        rule = RoutingRule(
            id="empty",
            name="Empty Conditions",
            conditions=[],
            action=RoutingAction.SKIP.value,
            priority=1,
        )
        routing_engine.add_rule(rule)

        # Devrait matcher car pas de conditions à vérifier
        result = routing_engine.evaluate(
            sender="anyone@example.com",
            subject="Any",
            body="",
        )

        # Règles par défaut ont priorité plus haute
        assert result is not None

    def test_invalid_regex(self, routing_engine):
        """Regex invalide."""
        rule = RoutingRule(
            id="bad-regex",
            name="Bad Regex",
            conditions=[
                {"field": "subject", "match_type": "regex", "value": "[invalid"},
            ],
            action=RoutingAction.SKIP.value,
            priority=50,
        )
        routing_engine.add_rule(rule)

        # Ne devrait pas crasher
        result = routing_engine.evaluate(
            sender="user@example.com",
            subject="Test",
            body="",
        )

        assert result is not None

    def test_extract_domain(self, routing_engine):
        """Extraction de domaine."""
        assert routing_engine._extract_domain("user@example.com") == "example.com"
        assert routing_engine._extract_domain("user@sub.example.com") == "sub.example.com"
        assert routing_engine._extract_domain("invalid") == ""
