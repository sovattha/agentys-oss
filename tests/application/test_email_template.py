# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les use cases EmailTemplate.

pytest tests/application/test_email_template.py -v
"""

import pytest
from unittest.mock import Mock

from app.domain.entities.email_template import EmailTemplate, TemplateMatch
from app.domain.ports.email_template_port import EmailTemplateStorePort
from app.application.email_template import (
    CreateTemplateUseCase,
    GetTemplateUseCase,
    ListTemplatesUseCase,
    UpdateTemplateUseCase,
    DeleteTemplateUseCase,
    MatchTemplateUseCase,
    RenderTemplateUseCase,
    GetTemplateStatsUseCase,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_store():
    """Mock du store."""
    return Mock(spec=EmailTemplateStorePort)


@pytest.fixture
def sample_template():
    """Template de test."""
    return EmailTemplate(
        id="test-1",
        name="Test Template",
        category="TEST",
        template_body="Hello ${name}!",
    )


@pytest.fixture
def sample_match(sample_template):
    """Match de test."""
    return TemplateMatch(
        template=sample_template,
        score=0.85,
        variables={"name": "John"},
    )


# ============================================================================
# TESTS CREATE TEMPLATE USE CASE
# ============================================================================


class TestCreateTemplateUseCase:
    """Tests pour CreateTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = CreateTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_add(self, mock_store, sample_template):
        """Execute appelle store.add."""
        use_case = CreateTemplateUseCase(mock_store)
        use_case.execute(sample_template)
        mock_store.add.assert_called_once_with(sample_template)

    def test_execute_returns_template(self, mock_store, sample_template):
        """Execute retourne le template."""
        use_case = CreateTemplateUseCase(mock_store)
        result = use_case.execute(sample_template)
        assert result == sample_template

    def test_execute_with_minimal_template(self, mock_store):
        """Execute avec template minimal."""
        template = EmailTemplate(
            id="min", name="Min", category="C", template_body="B"
        )
        use_case = CreateTemplateUseCase(mock_store)
        result = use_case.execute(template)
        assert result.id == "min"

    def test_execute_propagates_store_exception(self, mock_store, sample_template):
        """Execute propage les exceptions du store."""
        mock_store.add.side_effect = RuntimeError("Store error")
        use_case = CreateTemplateUseCase(mock_store)
        with pytest.raises(RuntimeError, match="Store error"):
            use_case.execute(sample_template)


# ============================================================================
# TESTS GET TEMPLATE USE CASE
# ============================================================================


class TestGetTemplateUseCase:
    """Tests pour GetTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = GetTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_get(self, mock_store):
        """Execute appelle store.get."""
        use_case = GetTemplateUseCase(mock_store)
        use_case.execute("template-id")
        mock_store.get.assert_called_once_with("template-id")

    def test_execute_returns_template_when_found(self, mock_store, sample_template):
        """Execute retourne le template quand trouvé."""
        mock_store.get.return_value = sample_template
        use_case = GetTemplateUseCase(mock_store)
        result = use_case.execute("test-1")
        assert result == sample_template

    def test_execute_returns_none_when_not_found(self, mock_store):
        """Execute retourne None quand non trouvé."""
        mock_store.get.return_value = None
        use_case = GetTemplateUseCase(mock_store)
        result = use_case.execute("nonexistent")
        assert result is None

    def test_execute_with_empty_id(self, mock_store):
        """Execute avec ID vide."""
        mock_store.get.return_value = None
        use_case = GetTemplateUseCase(mock_store)
        result = use_case.execute("")
        assert result is None
        mock_store.get.assert_called_once_with("")

    def test_execute_propagates_store_exception(self, mock_store):
        """Execute propage les exceptions du store."""
        mock_store.get.side_effect = RuntimeError("Store error")
        use_case = GetTemplateUseCase(mock_store)
        with pytest.raises(RuntimeError, match="Store error"):
            use_case.execute("any-id")


# ============================================================================
# TESTS LIST TEMPLATES USE CASE
# ============================================================================


class TestListTemplatesUseCase:
    """Tests pour ListTemplatesUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = ListTemplatesUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_without_category_calls_get_all(self, mock_store):
        """Execute sans catégorie appelle get_all."""
        mock_store.get_all.return_value = []
        use_case = ListTemplatesUseCase(mock_store)
        use_case.execute()
        mock_store.get_all.assert_called_once()

    def test_execute_with_category_calls_get_by_category(self, mock_store):
        """Execute avec catégorie appelle get_by_category."""
        mock_store.get_by_category.return_value = []
        use_case = ListTemplatesUseCase(mock_store)
        use_case.execute(category="URGENT")
        mock_store.get_by_category.assert_called_once_with("URGENT")

    def test_execute_with_none_category_calls_get_all(self, mock_store):
        """Execute avec catégorie None appelle get_all."""
        mock_store.get_all.return_value = []
        use_case = ListTemplatesUseCase(mock_store)
        use_case.execute(category=None)
        mock_store.get_all.assert_called_once()

    def test_execute_returns_list_of_templates(self, mock_store, sample_template):
        """Execute retourne une liste de templates."""
        mock_store.get_all.return_value = [sample_template]
        use_case = ListTemplatesUseCase(mock_store)
        result = use_case.execute()
        assert len(result) == 1
        assert result[0] == sample_template

    def test_execute_returns_empty_list(self, mock_store):
        """Execute retourne une liste vide."""
        mock_store.get_all.return_value = []
        use_case = ListTemplatesUseCase(mock_store)
        result = use_case.execute()
        assert result == []

    def test_execute_with_empty_string_category(self, mock_store):
        """Execute avec catégorie chaîne vide (traité comme falsy -> get_all)."""
        mock_store.get_all.return_value = []
        use_case = ListTemplatesUseCase(mock_store)
        use_case.execute(category="")
        # Une chaîne vide est "falsy" en Python, donc on appelle get_all
        mock_store.get_all.assert_called_once()


# ============================================================================
# TESTS UPDATE TEMPLATE USE CASE
# ============================================================================


class TestUpdateTemplateUseCase:
    """Tests pour UpdateTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = UpdateTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_checks_existence_first(self, mock_store, sample_template):
        """Execute vérifie l'existence d'abord."""
        mock_store.get.return_value = sample_template
        use_case = UpdateTemplateUseCase(mock_store)
        use_case.execute(sample_template)
        mock_store.get.assert_called_once_with(sample_template.id)

    def test_execute_returns_none_when_not_found(self, mock_store, sample_template):
        """Execute retourne None quand non trouvé."""
        mock_store.get.return_value = None
        use_case = UpdateTemplateUseCase(mock_store)
        result = use_case.execute(sample_template)
        assert result is None

    def test_execute_does_not_call_add_when_not_found(self, mock_store, sample_template):
        """Execute n'appelle pas add quand non trouvé."""
        mock_store.get.return_value = None
        use_case = UpdateTemplateUseCase(mock_store)
        use_case.execute(sample_template)
        mock_store.add.assert_not_called()

    def test_execute_calls_add_when_found(self, mock_store, sample_template):
        """Execute appelle add quand trouvé."""
        mock_store.get.return_value = sample_template
        use_case = UpdateTemplateUseCase(mock_store)
        use_case.execute(sample_template)
        mock_store.add.assert_called_once_with(sample_template)

    def test_execute_returns_template_when_updated(self, mock_store, sample_template):
        """Execute retourne le template quand mis à jour."""
        mock_store.get.return_value = sample_template
        use_case = UpdateTemplateUseCase(mock_store)
        result = use_case.execute(sample_template)
        assert result == sample_template


# ============================================================================
# TESTS DELETE TEMPLATE USE CASE
# ============================================================================


class TestDeleteTemplateUseCase:
    """Tests pour DeleteTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = DeleteTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_remove(self, mock_store):
        """Execute appelle store.remove."""
        mock_store.remove.return_value = True
        use_case = DeleteTemplateUseCase(mock_store)
        use_case.execute("template-id")
        mock_store.remove.assert_called_once_with("template-id")

    def test_execute_returns_true_when_deleted(self, mock_store):
        """Execute retourne True quand supprimé."""
        mock_store.remove.return_value = True
        use_case = DeleteTemplateUseCase(mock_store)
        result = use_case.execute("template-id")
        assert result is True

    def test_execute_returns_false_when_not_found(self, mock_store):
        """Execute retourne False quand non trouvé."""
        mock_store.remove.return_value = False
        use_case = DeleteTemplateUseCase(mock_store)
        result = use_case.execute("nonexistent")
        assert result is False

    def test_execute_with_empty_id(self, mock_store):
        """Execute avec ID vide."""
        mock_store.remove.return_value = False
        use_case = DeleteTemplateUseCase(mock_store)
        result = use_case.execute("")
        assert result is False


# ============================================================================
# TESTS MATCH TEMPLATE USE CASE
# ============================================================================


class TestMatchTemplateUseCase:
    """Tests pour MatchTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = MatchTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_find_best_match(self, mock_store):
        """Execute appelle store.find_best_match."""
        mock_store.find_best_match.return_value = None
        use_case = MatchTemplateUseCase(mock_store)
        use_case.execute("URGENT", "subject", "body")
        mock_store.find_best_match.assert_called_once_with(
            "URGENT", "subject", "body", "fr"
        )

    def test_execute_with_custom_language(self, mock_store):
        """Execute avec langue personnalisée."""
        mock_store.find_best_match.return_value = None
        use_case = MatchTemplateUseCase(mock_store)
        use_case.execute("URGENT", "subject", "body", language="en")
        mock_store.find_best_match.assert_called_once_with(
            "URGENT", "subject", "body", "en"
        )

    def test_execute_returns_match_when_found(self, mock_store, sample_match):
        """Execute retourne le match quand trouvé."""
        mock_store.find_best_match.return_value = sample_match
        use_case = MatchTemplateUseCase(mock_store)
        result = use_case.execute("TEST", "subject", "body")
        assert result == sample_match

    def test_execute_returns_none_when_not_found(self, mock_store):
        """Execute retourne None quand pas de match."""
        mock_store.find_best_match.return_value = None
        use_case = MatchTemplateUseCase(mock_store)
        result = use_case.execute("UNKNOWN", "subject", "body")
        assert result is None

    def test_execute_with_empty_strings(self, mock_store):
        """Execute avec chaînes vides."""
        mock_store.find_best_match.return_value = None
        use_case = MatchTemplateUseCase(mock_store)
        use_case.execute("", "", "")
        mock_store.find_best_match.assert_called_once_with("", "", "", "fr")


# ============================================================================
# TESTS RENDER TEMPLATE USE CASE
# ============================================================================


class TestRenderTemplateUseCase:
    """Tests pour RenderTemplateUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = RenderTemplateUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_render(self, mock_store, sample_template):
        """Execute appelle store.render."""
        mock_store.render.return_value = "Rendered"
        variables = {"name": "John"}
        use_case = RenderTemplateUseCase(mock_store)
        use_case.execute(sample_template, variables)
        mock_store.render.assert_called_once_with(sample_template, variables)

    def test_execute_returns_rendered_string(self, mock_store, sample_template):
        """Execute retourne la chaîne rendue."""
        mock_store.render.return_value = "Hello John!"
        use_case = RenderTemplateUseCase(mock_store)
        result = use_case.execute(sample_template, {"name": "John"})
        assert result == "Hello John!"

    def test_execute_with_empty_variables(self, mock_store, sample_template):
        """Execute avec variables vides."""
        mock_store.render.return_value = "Hello ${name}!"
        use_case = RenderTemplateUseCase(mock_store)
        use_case.execute(sample_template, {})
        mock_store.render.assert_called_once_with(sample_template, {})

    def test_execute_propagates_store_exception(self, mock_store, sample_template):
        """Execute propage les exceptions du store."""
        mock_store.render.side_effect = RuntimeError("Render error")
        use_case = RenderTemplateUseCase(mock_store)
        with pytest.raises(RuntimeError, match="Render error"):
            use_case.execute(sample_template, {})


# ============================================================================
# TESTS GET TEMPLATE STATS USE CASE
# ============================================================================


class TestGetTemplateStatsUseCase:
    """Tests pour GetTemplateStatsUseCase."""

    def test_init_stores_store(self, mock_store):
        """L'initialisation stocke le store."""
        use_case = GetTemplateStatsUseCase(mock_store)
        assert use_case.store == mock_store

    def test_execute_calls_store_get_stats(self, mock_store):
        """Execute appelle store.get_stats."""
        mock_store.get_stats.return_value = {}
        use_case = GetTemplateStatsUseCase(mock_store)
        use_case.execute()
        mock_store.get_stats.assert_called_once()

    def test_execute_returns_stats_dict(self, mock_store):
        """Execute retourne le dict de stats."""
        expected_stats = {
            "total": 10,
            "enabled": 8,
            "by_category": {"URGENT": 3, "NORMAL": 5},
        }
        mock_store.get_stats.return_value = expected_stats
        use_case = GetTemplateStatsUseCase(mock_store)
        result = use_case.execute()
        assert result == expected_stats

    def test_execute_returns_empty_stats(self, mock_store):
        """Execute retourne stats vides."""
        mock_store.get_stats.return_value = {"total": 0}
        use_case = GetTemplateStatsUseCase(mock_store)
        result = use_case.execute()
        assert result["total"] == 0


# ============================================================================
# TESTS EDGE CASES
# ============================================================================


class TestUseCasesEdgeCases:
    """Tests des cas limites pour tous les use cases."""

    def test_create_with_unicode(self, mock_store):
        """Create avec unicode."""
        template = EmailTemplate(
            id="émoji-🎉",
            name="Prénom Événement",
            category="RÉUNION",
            template_body="Bonjour ${nom}! 🎊",
        )
        use_case = CreateTemplateUseCase(mock_store)
        result = use_case.execute(template)
        assert "🎉" in result.id

    def test_get_with_special_characters_in_id(self, mock_store, sample_template):
        """Get avec caractères spéciaux dans l'ID."""
        mock_store.get.return_value = sample_template
        use_case = GetTemplateUseCase(mock_store)
        use_case.execute("id-with-special-chars-@#$%")
        mock_store.get.assert_called_once_with("id-with-special-chars-@#$%")

    def test_list_with_large_result(self, mock_store):
        """List avec beaucoup de templates."""
        templates = [
            EmailTemplate(id=f"t-{i}", name=f"T{i}", category="C", template_body="B")
            for i in range(1000)
        ]
        mock_store.get_all.return_value = templates
        use_case = ListTemplatesUseCase(mock_store)
        result = use_case.execute()
        assert len(result) == 1000

    def test_render_with_many_variables(self, mock_store, sample_template):
        """Render avec beaucoup de variables."""
        variables = {f"var_{i}": f"value_{i}" for i in range(100)}
        mock_store.render.return_value = "Rendered"
        use_case = RenderTemplateUseCase(mock_store)
        use_case.execute(sample_template, variables)
        mock_store.render.assert_called_once_with(sample_template, variables)

    def test_match_with_very_long_body(self, mock_store):
        """Match avec body très long."""
        long_body = "x" * 100000
        mock_store.find_best_match.return_value = None
        use_case = MatchTemplateUseCase(mock_store)
        use_case.execute("CAT", "subject", long_body)
        mock_store.find_best_match.assert_called_once()


class TestUseCasesExceptionHandling:
    """Tests de gestion des exceptions."""

    def test_create_propagates_exception(self, mock_store, sample_template):
        """Create propage les exceptions."""
        mock_store.add.side_effect = ValueError("Invalid template")
        use_case = CreateTemplateUseCase(mock_store)
        with pytest.raises(ValueError):
            use_case.execute(sample_template)

    def test_get_propagates_exception(self, mock_store):
        """Get propage les exceptions."""
        mock_store.get.side_effect = ConnectionError("DB error")
        use_case = GetTemplateUseCase(mock_store)
        with pytest.raises(ConnectionError):
            use_case.execute("id")

    def test_list_propagates_exception(self, mock_store):
        """List propage les exceptions."""
        mock_store.get_all.side_effect = IOError("IO error")
        use_case = ListTemplatesUseCase(mock_store)
        with pytest.raises(IOError):
            use_case.execute()

    def test_update_propagates_get_exception(self, mock_store, sample_template):
        """Update propage les exceptions de get."""
        mock_store.get.side_effect = RuntimeError("Get failed")
        use_case = UpdateTemplateUseCase(mock_store)
        with pytest.raises(RuntimeError):
            use_case.execute(sample_template)

    def test_update_propagates_add_exception(self, mock_store, sample_template):
        """Update propage les exceptions de add."""
        mock_store.get.return_value = sample_template
        mock_store.add.side_effect = RuntimeError("Add failed")
        use_case = UpdateTemplateUseCase(mock_store)
        with pytest.raises(RuntimeError):
            use_case.execute(sample_template)

    def test_delete_propagates_exception(self, mock_store):
        """Delete propage les exceptions."""
        mock_store.remove.side_effect = PermissionError("Not allowed")
        use_case = DeleteTemplateUseCase(mock_store)
        with pytest.raises(PermissionError):
            use_case.execute("id")

    def test_match_propagates_exception(self, mock_store):
        """Match propage les exceptions."""
        mock_store.find_best_match.side_effect = TimeoutError("Timeout")
        use_case = MatchTemplateUseCase(mock_store)
        with pytest.raises(TimeoutError):
            use_case.execute("cat", "subj", "body")

    def test_stats_propagates_exception(self, mock_store):
        """Stats propage les exceptions."""
        mock_store.get_stats.side_effect = MemoryError("OOM")
        use_case = GetTemplateStatsUseCase(mock_store)
        with pytest.raises(MemoryError):
            use_case.execute()
