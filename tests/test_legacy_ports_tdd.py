# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les nouveaux ports de migration des modules legacy.

Ces tests vérifient les contrats des ports:
- DraftHistoryPort : stockage des brouillons générés
- AnalyticsPort : métriques de qualité
- TokenCounterPort : comptage des tokens

Architecture Clean: Ces ports définissent les abstractions
que les adapters legacy doivent implémenter.
"""

from abc import ABC

import pytest


# Allow unscoped draft history methods in tests
@pytest.fixture(autouse=True)
def allow_unscoped_draft_history(monkeypatch):
    """Allow legacy unscoped DraftHistory methods during tests."""
    monkeypatch.setenv("ALLOW_UNSCOPED_DRAFT_HISTORY", "1")


# =============================================================================
# TESTS ENTITIES
# =============================================================================

class TestDraftRecordEntity:
    """Tests pour l'entité DraftRecord (domaine)."""

    def test_draft_record_creation(self):
        """Création d'un enregistrement de brouillon."""
        from app.domain.entities.draft_history import DraftRecord

        record = DraftRecord(
            id="draft-001",
            timestamp="2025-01-01T10:00:00",
            email_id="email-123",
            email_sender="sender@example.com",
            email_subject="Test Subject",
            email_preview="This is a preview...",
            draft_v1="First draft version",
            critique="VALID: Good response",
            draft_final="Final draft version",
            status="V1",
        )

        assert record.id == "draft-001"
        assert record.email_sender == "sender@example.com"
        assert record.status == "V1"

    def test_draft_record_optional_fields(self):
        """Les champs optionnels ont des valeurs par défaut."""
        from app.domain.entities.draft_history import DraftRecord

        record = DraftRecord(
            id="draft-002",
            timestamp="2025-01-01T10:00:00",
            email_id="email-456",
            email_sender="test@example.com",
            email_subject="Subject",
            email_preview="Preview...",
            draft_v1="Draft V1",
            critique="VALID",
            draft_final="Draft Final",
            status="V2",
        )

        assert record.draft_id is None
        assert record.tokens_used == 0
        assert record.feedback is None
        assert record.priority_score is None
        assert record.category is None

    def test_draft_record_with_feedback(self):
        """Enregistrement avec feedback utilisateur."""
        from app.domain.entities.draft_history import DraftRecord

        record = DraftRecord(
            id="draft-003",
            timestamp="2025-01-01T10:00:00",
            email_id="email-789",
            email_sender="feedback@example.com",
            email_subject="Feedback Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="VALID",
            draft_final="Final",
            status="V1",
            feedback="positive",
            feedback_comment="Great response!",
        )

        assert record.feedback == "positive"
        assert record.feedback_comment == "Great response!"


class TestAnalyticsEntities:
    """Tests pour les entités analytics (domaine)."""

    def test_quality_score_creation(self):
        """Création d'un score de qualité."""
        from app.domain.entities.analytics import QualityScore

        score = QualityScore(
            draft_id="draft-001",
            overall_score=85.0,
            tone_score=90.0,
            completeness_score=80.0,
        )

        assert score.overall_score == 85.0
        assert score.tone_score == 90.0

    def test_quality_level_excellent(self):
        """Score >= 90 = 'excellent'."""
        from app.domain.entities.analytics import QualityScore

        score = QualityScore(draft_id="test", overall_score=92.0)
        assert score.quality_level == "excellent"

    def test_quality_level_good(self):
        """Score >= 75 = 'good'."""
        from app.domain.entities.analytics import QualityScore

        score = QualityScore(draft_id="test", overall_score=80.0)
        assert score.quality_level == "good"

    def test_quality_level_acceptable(self):
        """Score >= 50 = 'acceptable'."""
        from app.domain.entities.analytics import QualityScore

        score = QualityScore(draft_id="test", overall_score=60.0)
        assert score.quality_level == "acceptable"

    def test_quality_level_needs_improvement(self):
        """Score < 50 = 'needs_improvement'."""
        from app.domain.entities.analytics import QualityScore

        score = QualityScore(draft_id="test", overall_score=40.0)
        assert score.quality_level == "needs_improvement"


# =============================================================================
# TESTS PORTS (INTERFACES)
# =============================================================================

class TestDraftHistoryPort:
    """Tests pour le port DraftHistoryPort."""

    def test_port_is_abstract(self):
        """Le port est une classe abstraite."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert issubclass(DraftHistoryPort, ABC)

    def test_port_has_add_method(self):
        """Le port définit la méthode add."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert hasattr(DraftHistoryPort, "add")
        assert callable(getattr(DraftHistoryPort, "add"))

    def test_port_has_get_by_id_method(self):
        """Le port définit la méthode get_by_id."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert hasattr(DraftHistoryPort, "get_by_id")

    def test_port_has_get_all_method(self):
        """Le port définit la méthode get_all."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert hasattr(DraftHistoryPort, "get_all")

    def test_port_has_update_feedback_method(self):
        """Le port définit la méthode update_feedback."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert hasattr(DraftHistoryPort, "update_feedback")

    def test_port_has_count_method(self):
        """Le port définit la méthode count."""
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert hasattr(DraftHistoryPort, "count")


class TestAnalyticsPort:
    """Tests pour le port AnalyticsPort."""

    def test_port_is_abstract(self):
        """Le port est une classe abstraite."""
        from app.domain.ports.analytics_port import AnalyticsPort

        assert issubclass(AnalyticsPort, ABC)

    def test_port_has_get_quality_metrics_method(self):
        """Le port définit get_quality_metrics."""
        from app.domain.ports.analytics_port import AnalyticsPort

        assert hasattr(AnalyticsPort, "get_quality_metrics")

    def test_port_has_get_ai_vs_human_comparison_method(self):
        """Le port définit get_ai_vs_human_comparison."""
        from app.domain.ports.analytics_port import AnalyticsPort

        assert hasattr(AnalyticsPort, "get_ai_vs_human_comparison")

    def test_port_has_record_quality_score_method(self):
        """Le port définit record_quality_score."""
        from app.domain.ports.analytics_port import AnalyticsPort

        assert hasattr(AnalyticsPort, "record_quality_score")


class TestTokenCounterPort:
    """Tests pour le port TokenCounterPort."""

    def test_port_is_abstract(self):
        """Le port est une classe abstraite."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert issubclass(TokenCounterPort, ABC)

    def test_port_has_add_method(self):
        """Le port définit la méthode add."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert hasattr(TokenCounterPort, "add")

    def test_port_has_get_total_method(self):
        """Le port définit get_total."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert hasattr(TokenCounterPort, "get_total")

    def test_port_has_get_breakdown_method(self):
        """Le port définit get_breakdown."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert hasattr(TokenCounterPort, "get_breakdown")

    def test_port_has_reset_method(self):
        """Le port définit reset."""
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert hasattr(TokenCounterPort, "reset")


# =============================================================================
# TESTS INTEGRATION CONTAINER
# =============================================================================

class TestContainerIntegration:
    """Tests d'intégration avec le Container DI."""

    def test_container_has_draft_history_port(self):
        """Le Container fournit un DraftHistoryPort."""
        from app.infrastructure.container import get_container, reset_container
        from app.domain.ports.draft_history_port import DraftHistoryPort

        reset_container()
        container = get_container()

        draft_history = container.get_draft_history()
        assert isinstance(draft_history, DraftHistoryPort)

    def test_container_has_analytics_port(self):
        """Le Container fournit un AnalyticsPort."""
        from app.infrastructure.container import get_container, reset_container
        from app.domain.ports.analytics_port import AnalyticsPort

        reset_container()
        container = get_container()

        analytics = container.get_analytics()
        assert isinstance(analytics, AnalyticsPort)

    def test_container_has_token_counter_port(self):
        """Le Container fournit un TokenCounterPort."""
        from app.infrastructure.container import get_container, reset_container
        from app.domain.ports.token_counter_port import TokenCounterPort

        reset_container()
        container = get_container()

        token_counter = container.get_token_counter()
        assert isinstance(token_counter, TokenCounterPort)


# =============================================================================
# TESTS ADAPTERS (IMPLEMENTATION DES PORTS)
# =============================================================================

class TestLegacyDraftHistoryAdapter:
    """Tests pour l'adapter de l'historique legacy."""

    def test_adapter_implements_port(self):
        """L'adapter implémente le port."""
        from app.infrastructure.adapters.draft_history_adapter import LegacyDraftHistoryAdapter
        from app.domain.ports.draft_history_port import DraftHistoryPort

        assert issubclass(LegacyDraftHistoryAdapter, DraftHistoryPort)

    def test_adapter_wraps_legacy_module(self, tmp_path):
        """L'adapter wrappe le module legacy existant."""
        from app.infrastructure.adapters.draft_history_adapter import LegacyDraftHistoryAdapter
        from app.domain.entities.draft_history import DraftRecord

        adapter = LegacyDraftHistoryAdapter(history_file=tmp_path / "test_history.json")

        record = DraftRecord(
            id="test-001",
            timestamp="2025-01-01T10:00:00",
            email_id="email-123",
            email_sender="test@example.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="VALID",
            draft_final="Final",
            status="V1",
            account_id=1,
        )

        adapter.add(record)

        retrieved = adapter.get_by_id_for_account("test-001", account_id=1)
        assert retrieved is not None
        assert retrieved.email_sender == "test@example.com"

    def test_adapter_get_all(self, tmp_path):
        """Récupération de tous les brouillons."""
        from app.infrastructure.adapters.draft_history_adapter import LegacyDraftHistoryAdapter
        from app.domain.entities.draft_history import DraftRecord

        adapter = LegacyDraftHistoryAdapter(history_file=tmp_path / "test_history.json")

        for i in range(3):
            record = DraftRecord(
                id=f"draft-{i}",
                timestamp="2025-01-01T10:00:00",
                email_id=f"email-{i}",
                email_sender=f"sender{i}@example.com",
                email_subject="Subject",
                email_preview="Preview",
                draft_v1="V1",
                critique="VALID",
                draft_final="Final",
                status="V1",
                account_id=1,
            )
            adapter.add(record)

        all_drafts = adapter.get_all_for_account(account_id=1)
        assert len(all_drafts) == 3

    def test_adapter_update_feedback(self, tmp_path):
        """Mise à jour du feedback sur un brouillon."""
        from app.infrastructure.adapters.draft_history_adapter import LegacyDraftHistoryAdapter
        from app.domain.entities.draft_history import DraftRecord

        adapter = LegacyDraftHistoryAdapter(history_file=tmp_path / "test_history.json")

        record = DraftRecord(
            id="feedback-test",
            timestamp="2025-01-01T10:00:00",
            email_id="email-fb",
            email_sender="feedback@example.com",
            email_subject="Feedback",
            email_preview="Preview",
            draft_v1="V1",
            critique="VALID",
            draft_final="Final",
            status="V1",
            account_id=1,
        )
        adapter.add(record)

        success = adapter.update_feedback_for_account("feedback-test", account_id=1, feedback="positive", rating=5)
        assert success is True

        updated = adapter.get_by_id_for_account("feedback-test", account_id=1)
        assert updated.feedback == "positive"
        assert updated.feedback_rating == 5


class TestLegacyAnalyticsAdapter:
    """Tests pour l'adapter analytics legacy."""

    def test_adapter_implements_port(self):
        """L'adapter implémente le port."""
        from app.infrastructure.adapters.analytics_adapter import LegacyAnalyticsAdapter
        from app.domain.ports.analytics_port import AnalyticsPort

        assert issubclass(LegacyAnalyticsAdapter, AnalyticsPort)

    def test_adapter_get_quality_metrics(self, tmp_path):
        """Récupération des métriques de qualité."""
        from app.infrastructure.adapters.analytics_adapter import LegacyAnalyticsAdapter

        adapter = LegacyAnalyticsAdapter(data_dir=tmp_path)

        metrics = adapter.get_quality_metrics()
        assert "avg_score" in metrics
        assert "total_drafts" in metrics

    def test_adapter_get_ai_vs_human(self, tmp_path):
        """Comparaison IA vs humain."""
        from app.infrastructure.adapters.analytics_adapter import LegacyAnalyticsAdapter

        adapter = LegacyAnalyticsAdapter(data_dir=tmp_path)

        comparison = adapter.get_ai_vs_human_comparison()
        assert "edit_rate" in comparison
        assert "avg_edit_ratio" in comparison


class TestLegacyTokenCounterAdapter:
    """Tests pour l'adapter du compteur de tokens legacy."""

    def test_adapter_implements_port(self):
        """L'adapter implémente le port."""
        from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter
        from app.domain.ports.token_counter_port import TokenCounterPort

        assert issubclass(LegacyTokenCounterAdapter, TokenCounterPort)

    def test_adapter_add_tokens(self):
        """Ajout de tokens."""
        from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter

        adapter = LegacyTokenCounterAdapter()

        adapter.add(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")

        total = adapter.get_total()
        assert total >= 150

    def test_adapter_get_breakdown(self):
        """Breakdown par modèle."""
        from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter

        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")

        breakdown = adapter.get_breakdown()
        assert isinstance(breakdown, dict)

    def test_adapter_reset(self):
        """Reset du compteur."""
        from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter

        adapter = LegacyTokenCounterAdapter()
        adapter.add(100, 50, "claude-sonnet-4-20250514")
        adapter.reset()

        assert adapter.get_total() == 0
