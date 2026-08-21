# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les templates de réponse email.

pytest tests/test_email_templates.py -v
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domain.entities.email_template import EmailTemplate, TemplateVariables
from app.infrastructure.email_template_store import (
    DEFAULT_TEMPLATES,
    JsonEmailTemplateStore as EmailTemplateManager,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def template_manager(tmp_path):
    """Crée un manager avec fichier temporaire."""
    filepath = tmp_path / "templates.json"
    return EmailTemplateManager(filepath=filepath)


@pytest.fixture
def sample_template():
    """Template de test."""
    return EmailTemplate(
        id="test-template",
        name="Test Template",
        category="TEST",
        template_body="Hello ${sender_name}, your request about ${subject} has been received.",
        description="A test template",
        language="en",
        tone="professional",
        priority=50,
    )


# ============================================================================
# TESTS EMAIL TEMPLATE DATACLASS
# ============================================================================

class TestEmailTemplate:
    """Tests pour EmailTemplate."""

    def test_creation(self):
        """Création d'un template."""
        template = EmailTemplate(
            id="tpl-001",
            name="My Template",
            category="URGENT",
            template_body="Hello ${sender_name}",
        )

        assert template.id == "tpl-001"
        assert template.name == "My Template"
        assert template.category == "URGENT"
        assert template.enabled is True

    def test_default_values(self):
        """Valeurs par défaut."""
        template = EmailTemplate(
            id="tpl-002",
            name="Template",
            category="NORMAL",
            template_body="Body",
        )

        assert template.language == "fr"
        assert template.tone == "professional"
        assert template.priority == 0
        assert template.usage_count == 0


class TestTemplateVariables:
    """Tests pour les variables."""

    def test_get_all_variables(self):
        """Liste des variables disponibles."""
        variables = TemplateVariables.get_all()

        assert TemplateVariables.SENDER_NAME in variables
        assert TemplateVariables.SENDER_EMAIL in variables
        assert TemplateVariables.SUBJECT in variables
        assert len(variables) >= 10


# ============================================================================
# TESTS EMAIL TEMPLATE MANAGER
# ============================================================================

class TestEmailTemplateManager:
    """Tests pour le gestionnaire de templates."""

    def test_init_with_defaults(self, template_manager):
        """Initialisation avec templates par défaut."""
        # Doit avoir chargé les templates par défaut
        templates = template_manager.get_all()
        assert len(templates) >= len(DEFAULT_TEMPLATES)

    def test_add_template(self, template_manager, sample_template):
        """Ajout d'un template."""
        template_manager.add(sample_template)

        retrieved = template_manager.get(sample_template.id)
        assert retrieved is not None
        assert retrieved.name == sample_template.name

    def test_update_template(self, template_manager, sample_template):
        """Mise à jour d'un template."""
        template_manager.add(sample_template)

        # Modifier et sauvegarder
        sample_template.name = "Updated Name"
        template_manager.add(sample_template)

        retrieved = template_manager.get(sample_template.id)
        assert retrieved.name == "Updated Name"
        assert retrieved.updated_at is not None

    def test_remove_template(self, template_manager, sample_template):
        """Suppression d'un template."""
        template_manager.add(sample_template)

        result = template_manager.remove(sample_template.id)

        assert result is True
        assert template_manager.get(sample_template.id) is None

    def test_remove_nonexistent(self, template_manager):
        """Suppression d'un template inexistant."""
        result = template_manager.remove("nonexistent")
        assert result is False

    def test_get_by_category(self, template_manager):
        """Récupération par catégorie."""
        urgent_templates = template_manager.get_by_category("URGENT")

        assert len(urgent_templates) >= 1
        assert all(t.category == "URGENT" for t in urgent_templates)

    def test_get_by_category_empty(self, template_manager):
        """Catégorie sans templates."""
        templates = template_manager.get_by_category("NONEXISTENT")
        assert templates == []


class TestTemplateMatching:
    """Tests pour le matching de templates."""

    def test_find_best_match_by_category(self, template_manager):
        """Match par catégorie."""
        match = template_manager.find_best_match(
            category="URGENT",
            subject="Important matter",
            body="This is urgent",
            language="fr",
        )

        assert match is not None
        assert match.template.category == "URGENT"

    def test_find_best_match_fallback_to_normal(self, template_manager):
        """Fallback vers NORMAL si pas de match."""
        match = template_manager.find_best_match(
            category="UNKNOWN_CATEGORY",
            subject="Some subject",
            body="Some body",
            language="fr",
        )

        # Devrait retourner un template NORMAL
        assert match is not None
        assert match.template.category == "NORMAL"

    def test_find_best_match_language_preference(self, template_manager, sample_template):
        """Préférence de langue."""
        # Ajouter un template anglais
        sample_template.category = "URGENT"
        sample_template.language = "en"
        template_manager.add(sample_template)

        match_en = template_manager.find_best_match(
            category="URGENT",
            subject="Test",
            body="Test",
            language="en",
        )

        match_fr = template_manager.find_best_match(
            category="URGENT",
            subject="Test",
            body="Test",
            language="fr",
        )

        assert match_en is not None
        assert match_fr is not None

    def test_find_best_match_with_conditions(self, template_manager):
        """Match avec conditions."""
        # Créer un template avec conditions
        conditional_template = EmailTemplate(
            id="conditional",
            name="Conditional",
            category="NORMAL",
            template_body="Conditional response",
            priority=90,
            conditions={
                "subject_contains": ["urgent", "asap"],
            },
        )
        template_manager.add(conditional_template)

        match = template_manager.find_best_match(
            category="NORMAL",
            subject="This is URGENT please",
            body="Need help ASAP",
            language="fr",
        )

        # Le template conditionnel devrait avoir un meilleur score
        assert match is not None


class TestTemplateRendering:
    """Tests pour le rendu des templates."""

    def test_render_basic(self, template_manager, sample_template):
        """Rendu basique."""
        template_manager.add(sample_template)

        rendered = template_manager.render(
            sample_template,
            {
                "sender_name": "John",
                "subject": "meeting request",
            },
        )

        assert "Hello John" in rendered
        assert "meeting request" in rendered

    def test_render_with_defaults(self, template_manager):
        """Rendu avec variables par défaut."""
        template = EmailTemplate(
            id="defaults-test",
            name="Defaults Test",
            category="TEST",
            template_body="${greeting}, today is ${date}. ${signature}",
        )
        template_manager.add(template)

        rendered = template_manager.render(template, {})

        assert "Bonjour" in rendered or "Bonsoir" in rendered
        assert datetime.now().strftime("%d/%m/%Y") in rendered
        assert "Cordialement" in rendered

    def test_render_missing_variable(self, template_manager, sample_template):
        """Rendu avec variable manquante."""
        template_manager.add(sample_template)

        rendered = template_manager.render(
            sample_template,
            {"subject": "test"},  # sender_name manquant
        )

        # safe_substitute garde les variables non remplacées
        assert "${sender_name}" in rendered

    def test_render_increments_usage(self, template_manager, sample_template):
        """Le rendu incrémente le compteur d'utilisation."""
        template_manager.add(sample_template)
        initial_count = sample_template.usage_count

        template_manager.render(sample_template, {"sender_name": "Test"})
        template_manager.render(sample_template, {"sender_name": "Test2"})

        assert sample_template.usage_count == initial_count + 2


class TestTemplateStats:
    """Tests pour les statistiques."""

    def test_get_stats(self, template_manager):
        """Statistiques des templates."""
        stats = template_manager.get_stats()

        assert "total" in stats
        assert "enabled" in stats
        assert "by_category" in stats
        assert "most_used" in stats
        assert "languages" in stats

    def test_stats_by_category(self, template_manager):
        """Stats par catégorie."""
        stats = template_manager.get_stats()

        # Doit avoir au moins la catégorie URGENT des templates par défaut
        assert "URGENT" in stats["by_category"]

    def test_most_used(self, template_manager, sample_template):
        """Templates les plus utilisés."""
        template_manager.add(sample_template)

        # Utiliser plusieurs fois
        for _ in range(5):
            template_manager.render(sample_template, {})

        stats = template_manager.get_stats()
        most_used = stats["most_used"]

        assert len(most_used) > 0
        # Le template le plus utilisé devrait être en premier
        assert most_used[0]["usage_count"] >= 5


# ============================================================================
# TESTS PERSISTENCE
# ============================================================================

class TestPersistence:
    """Tests pour la persistance."""

    def test_save_and_load(self, tmp_path, sample_template):
        """Sauvegarde et rechargement."""
        filepath = tmp_path / "templates.json"

        # Créer et sauvegarder
        manager1 = EmailTemplateManager(filepath=filepath)
        manager1.add(sample_template)
        template_id = sample_template.id

        # Recharger
        manager2 = EmailTemplateManager(filepath=filepath)
        loaded = manager2.get(template_id)

        assert loaded is not None
        assert loaded.name == sample_template.name

    def test_persistence_usage_count(self, tmp_path, sample_template):
        """Persistance du compteur d'utilisation."""
        filepath = tmp_path / "templates.json"

        manager1 = EmailTemplateManager(filepath=filepath)
        manager1.add(sample_template)
        manager1.render(sample_template, {})
        manager1.render(sample_template, {})

        manager2 = EmailTemplateManager(filepath=filepath)
        loaded = manager2.get(sample_template.id)

        assert loaded.usage_count == 2


# ============================================================================
# TESTS DEFAULT TEMPLATES
# ============================================================================

class TestDefaultTemplates:
    """Tests pour les templates par défaut."""

    def test_default_templates_valid(self):
        """Validation des templates par défaut."""
        assert len(DEFAULT_TEMPLATES) >= 5

        for template in DEFAULT_TEMPLATES:
            assert template.id is not None
            assert template.name is not None
            assert template.category is not None
            assert template.template_body is not None
            assert "${" in template.template_body  # Doit avoir des variables

    def test_default_templates_categories(self):
        """Catégories couvertes par défaut."""
        categories = {t.category for t in DEFAULT_TEMPLATES}

        assert "URGENT" in categories
        assert "NORMAL" in categories
        assert "MEETING" in categories


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_template_body(self, template_manager):
        """Template avec corps vide."""
        template = EmailTemplate(
            id="empty-body",
            name="Empty",
            category="TEST",
            template_body="",
        )
        template_manager.add(template)

        rendered = template_manager.render(template, {"name": "Test"})
        assert rendered == ""

    def test_unicode_in_template(self, template_manager):
        """Unicode dans le template."""
        template = EmailTemplate(
            id="unicode",
            name="Unicode Test",
            category="TEST",
            template_body="Bonjour ${sender_name}! 🎉 Votre demande: ${subject}",
        )
        template_manager.add(template)

        rendered = template_manager.render(
            template,
            {"sender_name": "Jérémie", "subject": "Réservation été"},
        )

        assert "Jérémie" in rendered
        assert "🎉" in rendered
        assert "été" in rendered

    def test_special_characters_in_variables(self, template_manager, sample_template):
        """Caractères spéciaux dans les variables."""
        template_manager.add(sample_template)

        rendered = template_manager.render(
            sample_template,
            {
                "sender_name": "John O'Brien",
                "subject": "Test & Debug <script>",
            },
        )

        assert "O'Brien" in rendered
        assert "&" in rendered
