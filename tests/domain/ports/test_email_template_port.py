# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le port EmailTemplateStorePort.

pytest tests/domain/ports/test_email_template_port.py -v
"""

import pytest
from abc import ABC
from typing import Dict, List, Optional, Any

from app.domain.entities.email_template import EmailTemplate, TemplateMatch
from app.domain.ports.email_template_port import EmailTemplateStorePort


# ============================================================================
# TESTS PORT IS ABSTRACT
# ============================================================================


class TestEmailTemplateStorePortIsAbstract:
    """Tests que le port est bien abstrait."""

    def test_inherits_from_abc(self):
        """Le port hérite de ABC."""
        assert issubclass(EmailTemplateStorePort, ABC)

    def test_cannot_instantiate_directly(self):
        """Le port ne peut pas être instancié directement."""
        with pytest.raises(TypeError) as exc_info:
            EmailTemplateStorePort()
        assert "abstract" in str(exc_info.value).lower()


class TestEmailTemplateStorePortHasMethods:
    """Tests que le port a toutes les méthodes requises."""

    def test_has_add_method(self):
        """Le port a la méthode add."""
        assert hasattr(EmailTemplateStorePort, "add")
        assert callable(getattr(EmailTemplateStorePort, "add"))

    def test_has_get_method(self):
        """Le port a la méthode get."""
        assert hasattr(EmailTemplateStorePort, "get")
        assert callable(getattr(EmailTemplateStorePort, "get"))

    def test_has_get_all_method(self):
        """Le port a la méthode get_all."""
        assert hasattr(EmailTemplateStorePort, "get_all")
        assert callable(getattr(EmailTemplateStorePort, "get_all"))

    def test_has_get_by_category_method(self):
        """Le port a la méthode get_by_category."""
        assert hasattr(EmailTemplateStorePort, "get_by_category")
        assert callable(getattr(EmailTemplateStorePort, "get_by_category"))

    def test_has_remove_method(self):
        """Le port a la méthode remove."""
        assert hasattr(EmailTemplateStorePort, "remove")
        assert callable(getattr(EmailTemplateStorePort, "remove"))

    def test_has_find_best_match_method(self):
        """Le port a la méthode find_best_match."""
        assert hasattr(EmailTemplateStorePort, "find_best_match")
        assert callable(getattr(EmailTemplateStorePort, "find_best_match"))

    def test_has_render_method(self):
        """Le port a la méthode render."""
        assert hasattr(EmailTemplateStorePort, "render")
        assert callable(getattr(EmailTemplateStorePort, "render"))

    def test_has_get_stats_method(self):
        """Le port a la méthode get_stats."""
        assert hasattr(EmailTemplateStorePort, "get_stats")
        assert callable(getattr(EmailTemplateStorePort, "get_stats"))


# ============================================================================
# FAKE IMPLEMENTATION FOR TESTING
# ============================================================================


class FakeEmailTemplateStore(EmailTemplateStorePort):
    """Implémentation fake pour tester le port."""

    def __init__(self):
        self.templates: Dict[str, EmailTemplate] = {}

    def add(self, template: EmailTemplate) -> None:
        self.templates[template.id] = template

    def get(self, template_id: str) -> Optional[EmailTemplate]:
        return self.templates.get(template_id)

    def get_all(self) -> List[EmailTemplate]:
        return list(self.templates.values())

    def get_by_category(self, category: str) -> List[EmailTemplate]:
        return [t for t in self.templates.values() if t.category == category]

    def remove(self, template_id: str) -> bool:
        if template_id in self.templates:
            del self.templates[template_id]
            return True
        return False

    def find_best_match(
        self,
        category: str,
        subject: str,
        body: str,
        language: str = "fr",
    ) -> Optional[TemplateMatch]:
        templates = self.get_by_category(category)
        if not templates:
            return None
        return TemplateMatch(template=templates[0], score=1.0)

    def render(
        self,
        template: EmailTemplate,
        variables: Dict[str, str],
    ) -> str:
        result = template.template_body
        for key, value in variables.items():
            result = result.replace(f"${{{key}}}", value)
        return result

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total": len(self.templates),
            "by_category": {},
        }


# ============================================================================
# TESTS FAKE IMPLEMENTATION
# ============================================================================


class TestFakeImplementation:
    """Tests de l'implémentation fake."""

    @pytest.fixture
    def store(self):
        """Fixture pour le store fake."""
        return FakeEmailTemplateStore()

    @pytest.fixture
    def sample_template(self):
        """Template de test."""
        return EmailTemplate(
            id="test-1",
            name="Test Template",
            category="TEST",
            template_body="Hello ${name}!",
        )

    def test_add_and_get(self, store, sample_template):
        """Ajout et récupération."""
        store.add(sample_template)
        result = store.get(sample_template.id)
        assert result is not None
        assert result.id == sample_template.id

    def test_get_not_found(self, store):
        """Récupération d'un template inexistant."""
        result = store.get("nonexistent")
        assert result is None

    def test_get_all_empty(self, store):
        """Get all sur store vide."""
        result = store.get_all()
        assert result == []

    def test_get_all_with_templates(self, store, sample_template):
        """Get all avec templates."""
        store.add(sample_template)
        result = store.get_all()
        assert len(result) == 1

    def test_get_by_category(self, store, sample_template):
        """Get par catégorie."""
        store.add(sample_template)
        result = store.get_by_category("TEST")
        assert len(result) == 1
        assert result[0].category == "TEST"

    def test_get_by_category_empty(self, store, sample_template):
        """Get par catégorie inexistante."""
        store.add(sample_template)
        result = store.get_by_category("NONEXISTENT")
        assert result == []

    def test_remove(self, store, sample_template):
        """Suppression."""
        store.add(sample_template)
        result = store.remove(sample_template.id)
        assert result is True
        assert store.get(sample_template.id) is None

    def test_remove_not_found(self, store):
        """Suppression d'un template inexistant."""
        result = store.remove("nonexistent")
        assert result is False

    def test_find_best_match(self, store, sample_template):
        """Recherche du meilleur match."""
        store.add(sample_template)
        match = store.find_best_match("TEST", "subject", "body")
        assert match is not None
        assert match.template.id == sample_template.id

    def test_find_best_match_no_match(self, store):
        """Pas de match trouvé."""
        match = store.find_best_match("NONEXISTENT", "subject", "body")
        assert match is None

    def test_render(self, store, sample_template):
        """Rendu de template."""
        store.add(sample_template)
        result = store.render(sample_template, {"name": "John"})
        assert result == "Hello John!"

    def test_render_no_variables(self, store, sample_template):
        """Rendu sans variables."""
        store.add(sample_template)
        result = store.render(sample_template, {})
        assert result == "Hello ${name}!"

    def test_get_stats(self, store, sample_template):
        """Statistiques."""
        store.add(sample_template)
        stats = store.get_stats()
        assert stats["total"] == 1


# ============================================================================
# TESTS EDGE CASES
# ============================================================================


class TestEdgeCasesEmptyStore:
    """Tests sur un store vide."""

    @pytest.fixture
    def store(self):
        return FakeEmailTemplateStore()

    def test_get_all_empty(self, store):
        """Get all sur store vide."""
        result = store.get_all()
        assert result == []
        assert isinstance(result, list)

    def test_get_by_category_empty(self, store):
        """Get by category sur store vide."""
        result = store.get_by_category("ANY")
        assert result == []

    def test_get_not_found_empty(self, store):
        """Get sur ID inexistant dans store vide."""
        result = store.get("nonexistent")
        assert result is None

    def test_remove_from_empty(self, store):
        """Remove sur store vide."""
        result = store.remove("any-id")
        assert result is False

    def test_find_best_match_empty(self, store):
        """Find best match sur store vide."""
        match = store.find_best_match("ANY", "subject", "body")
        assert match is None


class TestEdgeCasesMultipleTemplates:
    """Tests avec plusieurs templates."""

    @pytest.fixture
    def store(self):
        store = FakeEmailTemplateStore()
        for i in range(5):
            store.add(EmailTemplate(
                id=f"tpl-{i}",
                name=f"Template {i}",
                category="CAT_A" if i % 2 == 0 else "CAT_B",
                template_body=f"Body {i}",
            ))
        return store

    def test_get_all_returns_all(self, store):
        """Get all retourne tous les templates."""
        result = store.get_all()
        assert len(result) == 5

    def test_get_by_category_filters(self, store):
        """Get by category filtre correctement."""
        cat_a = store.get_by_category("CAT_A")
        cat_b = store.get_by_category("CAT_B")
        assert len(cat_a) == 3  # 0, 2, 4
        assert len(cat_b) == 2  # 1, 3

    def test_remove_one_leaves_others(self, store):
        """Remove un template laisse les autres."""
        store.remove("tpl-0")
        result = store.get_all()
        assert len(result) == 4
        assert store.get("tpl-1") is not None


class TestEdgeCasesSpecialValues:
    """Tests avec valeurs spéciales."""

    @pytest.fixture
    def store(self):
        return FakeEmailTemplateStore()

    def test_add_with_empty_id(self, store):
        """Ajout avec ID vide."""
        template = EmailTemplate(
            id="", name="T", category="C", template_body="B"
        )
        store.add(template)
        result = store.get("")
        assert result is not None

    def test_get_with_empty_string(self, store):
        """Get avec chaîne vide."""
        result = store.get("")
        assert result is None

    def test_remove_with_empty_string(self, store):
        """Remove avec chaîne vide."""
        result = store.remove("")
        assert result is False

    def test_get_by_category_with_empty_string(self, store):
        """Get by category avec chaîne vide."""
        template = EmailTemplate(
            id="t1", name="T", category="", template_body="B"
        )
        store.add(template)
        result = store.get_by_category("")
        assert len(result) == 1

    def test_render_with_empty_body(self, store):
        """Render avec corps vide."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body=""
        )
        result = store.render(template, {"name": "John"})
        assert result == ""

    def test_render_with_unicode(self, store):
        """Render avec unicode."""
        template = EmailTemplate(
            id="t1", name="T", category="C",
            template_body="Bonjour ${nom}! 🎉"
        )
        result = store.render(template, {"nom": "Jérémie"})
        assert "Jérémie" in result
        assert "🎉" in result

    def test_find_best_match_with_empty_strings(self, store):
        """Find best match avec chaînes vides."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        store.add(template)
        match = store.find_best_match("C", "", "")
        assert match is not None
