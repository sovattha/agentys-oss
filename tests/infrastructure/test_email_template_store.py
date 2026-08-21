# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour JsonEmailTemplateStore.

pytest tests/infrastructure/test_email_template_store.py -v
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.domain.entities.email_template import EmailTemplate, TemplateMatch
from app.domain.ports.email_template_port import EmailTemplateStorePort
from app.infrastructure.email_template_store import (
    JsonEmailTemplateStore,
    DEFAULT_TEMPLATES,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_store(tmp_path):
    """Store avec fichier temporaire."""
    filepath = tmp_path / "templates.json"
    return JsonEmailTemplateStore(filepath=filepath)


@pytest.fixture
def sample_template():
    """Template de test."""
    return EmailTemplate(
        id="test-template",
        name="Test Template",
        category="TEST",
        template_body="Hello ${sender_name}!",
        description="A test template",
        language="en",
        tone="professional",
        priority=50,
    )


@pytest.fixture
def sample_template_fr():
    """Template français de test."""
    return EmailTemplate(
        id="test-fr",
        name="Template Français",
        category="URGENT",
        template_body="Bonjour ${sender_name}!",
        language="fr",
        priority=80,
    )


# ============================================================================
# TESTS INITIALIZATION
# ============================================================================


class TestJsonEmailTemplateStoreInit:
    """Tests d'initialisation."""

    def test_inherits_from_port(self, temp_store):
        """Le store hérite du port."""
        assert isinstance(temp_store, EmailTemplateStorePort)

    def test_init_creates_default_templates(self, tmp_path):
        """L'init crée les templates par défaut."""
        filepath = tmp_path / "new_templates.json"
        store = JsonEmailTemplateStore(filepath=filepath)
        assert len(store.get_all()) >= len(DEFAULT_TEMPLATES)

    def test_init_loads_existing_file(self, tmp_path, sample_template):
        """L'init charge un fichier existant."""
        filepath = tmp_path / "existing.json"
        # Créer le fichier manuellement
        data = {
            "templates": [{
                "id": sample_template.id,
                "name": sample_template.name,
                "category": sample_template.category,
                "template_body": sample_template.template_body,
            }]
        }
        filepath.write_text(json.dumps(data))

        store = JsonEmailTemplateStore(filepath=filepath)
        assert store.get(sample_template.id) is not None

    def test_init_with_corrupted_file_uses_defaults(self, tmp_path):
        """L'init avec fichier corrompu utilise les défauts."""
        filepath = tmp_path / "corrupted.json"
        filepath.write_text("not valid json {{{")

        store = JsonEmailTemplateStore(filepath=filepath)
        # Doit avoir chargé les templates par défaut
        assert len(store.get_all()) >= len(DEFAULT_TEMPLATES)

    def test_init_creates_parent_directories(self, tmp_path):
        """L'init crée les répertoires parents si nécessaire."""
        filepath = tmp_path / "deep" / "nested" / "templates.json"
        JsonEmailTemplateStore(filepath=filepath)
        assert filepath.exists()


# ============================================================================
# TESTS ADD
# ============================================================================


class TestJsonEmailTemplateStoreAdd:
    """Tests pour la méthode add."""

    def test_add_new_template(self, temp_store, sample_template):
        """Ajout d'un nouveau template."""
        temp_store.add(sample_template)
        result = temp_store.get(sample_template.id)
        assert result is not None
        assert result.name == sample_template.name

    def test_add_updates_existing_template(self, temp_store, sample_template):
        """Ajout d'un template existant le met à jour."""
        temp_store.add(sample_template)
        sample_template.name = "Updated Name"
        temp_store.add(sample_template)

        result = temp_store.get(sample_template.id)
        assert result.name == "Updated Name"
        assert result.updated_at is not None

    def test_add_persists_to_file(self, tmp_path, sample_template):
        """L'ajout persiste dans le fichier."""
        filepath = tmp_path / "persist.json"
        store1 = JsonEmailTemplateStore(filepath=filepath)
        store1.add(sample_template)

        # Recharger depuis le fichier
        store2 = JsonEmailTemplateStore(filepath=filepath)
        result = store2.get(sample_template.id)
        assert result is not None

    def test_add_sets_updated_at_on_update(self, temp_store, sample_template):
        """L'ajout définit updated_at lors d'une mise à jour."""
        temp_store.add(sample_template)
        before = datetime.now().isoformat()
        temp_store.add(sample_template)
        result = temp_store.get(sample_template.id)
        assert result.updated_at is not None
        assert result.updated_at >= before[:10]  # Compare les dates


# ============================================================================
# TESTS GET
# ============================================================================


class TestJsonEmailTemplateStoreGet:
    """Tests pour la méthode get."""

    def test_get_existing_template(self, temp_store, sample_template):
        """Get d'un template existant."""
        temp_store.add(sample_template)
        result = temp_store.get(sample_template.id)
        assert result is not None
        assert result.id == sample_template.id

    def test_get_nonexistent_returns_none(self, temp_store):
        """Get d'un template inexistant retourne None."""
        result = temp_store.get("nonexistent")
        assert result is None

    def test_get_with_empty_id(self, temp_store):
        """Get avec ID vide."""
        result = temp_store.get("")
        assert result is None


# ============================================================================
# TESTS GET ALL
# ============================================================================


class TestJsonEmailTemplateStoreGetAll:
    """Tests pour la méthode get_all."""

    def test_get_all_returns_all_templates(self, temp_store, sample_template):
        """Get all retourne tous les templates."""
        initial_count = len(temp_store.get_all())
        temp_store.add(sample_template)
        result = temp_store.get_all()
        assert len(result) == initial_count + 1

    def test_get_all_returns_list(self, temp_store):
        """Get all retourne une liste."""
        result = temp_store.get_all()
        assert isinstance(result, list)


# ============================================================================
# TESTS GET BY CATEGORY
# ============================================================================


class TestJsonEmailTemplateStoreGetByCategory:
    """Tests pour la méthode get_by_category."""

    def test_get_by_category_filters(self, temp_store, sample_template):
        """Get by category filtre correctement."""
        temp_store.add(sample_template)
        result = temp_store.get_by_category("TEST")
        assert all(t.category == "TEST" for t in result)

    def test_get_by_category_excludes_disabled(self, temp_store):
        """Get by category exclut les templates désactivés."""
        template = EmailTemplate(
            id="disabled",
            name="Disabled",
            category="TEST",
            template_body="Body",
            enabled=False,
        )
        temp_store.add(template)
        result = temp_store.get_by_category("TEST")
        assert all(t.enabled for t in result)

    def test_get_by_category_empty_returns_empty_list(self, temp_store):
        """Get by category avec catégorie inexistante retourne liste vide."""
        result = temp_store.get_by_category("NONEXISTENT_CATEGORY_XYZ")
        assert result == []


# ============================================================================
# TESTS REMOVE
# ============================================================================


class TestJsonEmailTemplateStoreRemove:
    """Tests pour la méthode remove."""

    def test_remove_existing_template(self, temp_store, sample_template):
        """Remove d'un template existant."""
        temp_store.add(sample_template)
        result = temp_store.remove(sample_template.id)
        assert result is True
        assert temp_store.get(sample_template.id) is None

    def test_remove_nonexistent_returns_false(self, temp_store):
        """Remove d'un template inexistant retourne False."""
        result = temp_store.remove("nonexistent")
        assert result is False

    def test_remove_persists(self, tmp_path, sample_template):
        """La suppression persiste dans le fichier."""
        filepath = tmp_path / "persist.json"
        store1 = JsonEmailTemplateStore(filepath=filepath)
        store1.add(sample_template)
        store1.remove(sample_template.id)

        store2 = JsonEmailTemplateStore(filepath=filepath)
        assert store2.get(sample_template.id) is None


# ============================================================================
# TESTS FIND BEST MATCH
# ============================================================================


class TestJsonEmailTemplateStoreFindBestMatch:
    """Tests pour la méthode find_best_match."""

    def test_find_best_match_by_category(self, temp_store):
        """Find best match par catégorie."""
        match = temp_store.find_best_match(
            category="URGENT",
            subject="Important",
            body="Urgent matter",
        )
        assert match is not None
        assert match.template.category == "URGENT"

    def test_find_best_match_fallback_to_normal(self, temp_store):
        """Find best match fallback vers NORMAL."""
        match = temp_store.find_best_match(
            category="UNKNOWN_CATEGORY",
            subject="Subject",
            body="Body",
        )
        # Devrait tomber en fallback sur NORMAL
        assert match is not None
        assert match.template.category == "NORMAL"

    def test_find_best_match_returns_none_when_no_match(self, tmp_path):
        """Find best match retourne None quand pas de match."""
        filepath = tmp_path / "empty.json"
        filepath.write_text('{"templates": []}')
        store = JsonEmailTemplateStore(filepath=filepath)

        match = store.find_best_match(
            category="UNKNOWN",
            subject="Subject",
            body="Body",
        )
        assert match is None

    def test_find_best_match_prefers_language(self, temp_store, sample_template_fr):
        """Find best match préfère la langue demandée."""
        temp_store.add(sample_template_fr)
        match = temp_store.find_best_match(
            category="URGENT",
            subject="Subject",
            body="Body",
            language="fr",
        )
        assert match is not None
        assert match.template.language == "fr"

    def test_find_best_match_with_conditions_subject_contains(self, temp_store):
        """Find best match avec conditions subject_contains."""
        template = EmailTemplate(
            id="conditional",
            name="Conditional",
            category="URGENT",
            template_body="Body",
            priority=100,
            conditions={"subject_contains": ["urgent", "asap"]},
        )
        temp_store.add(template)

        match = temp_store.find_best_match(
            category="URGENT",
            subject="This is URGENT please",
            body="Body",
        )
        assert match is not None

    def test_find_best_match_with_conditions_body_contains(self, temp_store):
        """Find best match avec conditions body_contains."""
        template = EmailTemplate(
            id="body-cond",
            name="Body Conditional",
            category="URGENT",
            template_body="Body",
            priority=100,
            conditions={"body_contains": ["help", "assistance"]},
        )
        temp_store.add(template)

        match = temp_store.find_best_match(
            category="URGENT",
            subject="Subject",
            body="I need help with this",
        )
        assert match is not None

    def test_find_best_match_returns_template_match(self, temp_store):
        """Find best match retourne un TemplateMatch."""
        match = temp_store.find_best_match(
            category="URGENT",
            subject="Subject",
            body="Body",
        )
        assert isinstance(match, TemplateMatch)
        assert hasattr(match, "template")
        assert hasattr(match, "score")
        assert hasattr(match, "variables")


# ============================================================================
# TESTS CALCULATE MATCH SCORE
# ============================================================================


class TestJsonEmailTemplateStoreCalculateMatchScore:
    """Tests pour la méthode _calculate_match_score."""

    def test_score_includes_priority(self, temp_store):
        """Le score inclut la priorité."""
        template_high = EmailTemplate(
            id="high",
            name="High",
            category="TEST",
            template_body="B",
            priority=100,
        )
        template_low = EmailTemplate(
            id="low",
            name="Low",
            category="TEST",
            template_body="B",
            priority=10,
        )
        temp_store.add(template_high)
        temp_store.add(template_low)

        score_high = temp_store._calculate_match_score(template_high, "s", "b")
        score_low = temp_store._calculate_match_score(template_low, "s", "b")
        assert score_high > score_low

    def test_score_with_conditions_met(self, temp_store):
        """Score avec conditions remplies."""
        template = EmailTemplate(
            id="cond",
            name="Conditional",
            category="TEST",
            template_body="B",
            priority=50,
            conditions={"subject_contains": ["urgent"]},
        )
        score_matched = temp_store._calculate_match_score(
            template, "This is urgent", "body"
        )
        score_not_matched = temp_store._calculate_match_score(
            template, "Normal subject", "body"
        )
        assert score_matched > score_not_matched

    def test_score_capped_at_one(self, temp_store):
        """Le score est plafonné à 1.0."""
        template = EmailTemplate(
            id="max",
            name="Max",
            category="TEST",
            template_body="B",
            priority=200,  # Très haute priorité
            conditions={"subject_contains": ["test"]},
        )
        score = temp_store._calculate_match_score(template, "test", "body")
        assert score <= 1.0


# ============================================================================
# TESTS RENDER
# ============================================================================


class TestJsonEmailTemplateStoreRender:
    """Tests pour la méthode render."""

    def test_render_replaces_variables(self, temp_store, sample_template):
        """Render remplace les variables."""
        temp_store.add(sample_template)
        result = temp_store.render(
            sample_template,
            {"sender_name": "John"},
        )
        assert "Hello John!" in result

    def test_render_with_default_variables(self, temp_store):
        """Render avec variables par défaut."""
        template = EmailTemplate(
            id="defaults",
            name="Defaults",
            category="TEST",
            template_body="${greeting}, ${signature}",
        )
        temp_store.add(template)
        result = temp_store.render(template, {})
        assert "Bonjour" in result or "Bonsoir" in result
        assert "Cordialement" in result

    def test_render_missing_variable_safe_substitute(self, temp_store, sample_template):
        """Render avec variable manquante utilise safe_substitute."""
        temp_store.add(sample_template)
        result = temp_store.render(sample_template, {})
        assert "${sender_name}" in result

    def test_render_increments_usage_count(self, temp_store, sample_template):
        """Render incrémente le compteur d'utilisation."""
        temp_store.add(sample_template)
        initial_count = sample_template.usage_count
        temp_store.render(sample_template, {})
        temp_store.render(sample_template, {})
        assert sample_template.usage_count == initial_count + 2

    def test_render_with_custom_signature(self, temp_store):
        """Render avec signature personnalisée."""
        template = EmailTemplate(
            id="sig",
            name="Signature",
            category="TEST",
            template_body="${signature}",
        )
        temp_store.add(template)
        result = temp_store.render(template, {"signature": "Best regards"})
        assert "Best regards" in result

    def test_render_with_date_and_time(self, temp_store):
        """Render avec date et heure."""
        template = EmailTemplate(
            id="datetime",
            name="DateTime",
            category="TEST",
            template_body="Date: ${date}, Time: ${time}",
        )
        temp_store.add(template)
        result = temp_store.render(template, {})
        today = datetime.now().strftime("%d/%m/%Y")
        assert today in result


# ============================================================================
# TESTS GET GREETING
# ============================================================================


class TestJsonEmailTemplateStoreGetGreeting:
    """Tests pour la méthode _get_greeting."""

    def test_greeting_is_bonjour_before_18h(self, temp_store):
        """Greeting est Bonjour avant 18h."""
        with patch("app.infrastructure.email_template_store.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_dt.now.return_value = mock_now
            greeting = temp_store._get_greeting()
            assert greeting == "Bonjour"

    def test_greeting_is_bonsoir_after_18h(self, temp_store):
        """Greeting est Bonsoir après 18h."""
        with patch("app.infrastructure.email_template_store.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 20
            mock_dt.now.return_value = mock_now
            greeting = temp_store._get_greeting()
            assert greeting == "Bonsoir"


# ============================================================================
# TESTS GET STATS
# ============================================================================


class TestJsonEmailTemplateStoreGetStats:
    """Tests pour la méthode get_stats."""

    def test_get_stats_structure(self, temp_store):
        """Get stats retourne la bonne structure."""
        stats = temp_store.get_stats()
        assert "total" in stats
        assert "enabled" in stats
        assert "by_category" in stats
        assert "most_used" in stats
        assert "languages" in stats

    def test_get_stats_total_count(self, temp_store, sample_template):
        """Get stats compte le total."""
        initial = temp_store.get_stats()["total"]
        temp_store.add(sample_template)
        new_stats = temp_store.get_stats()
        assert new_stats["total"] == initial + 1

    def test_get_stats_by_category(self, temp_store):
        """Get stats par catégorie."""
        stats = temp_store.get_stats()
        # Les templates par défaut ont des catégories
        assert len(stats["by_category"]) > 0
        assert "URGENT" in stats["by_category"]

    def test_get_stats_most_used(self, temp_store, sample_template):
        """Get stats most used."""
        temp_store.add(sample_template)
        for _ in range(5):
            temp_store.render(sample_template, {})

        stats = temp_store.get_stats()
        assert len(stats["most_used"]) > 0
        assert stats["most_used"][0]["usage_count"] >= 5

    def test_get_stats_languages(self, temp_store, sample_template):
        """Get stats langues."""
        temp_store.add(sample_template)
        stats = temp_store.get_stats()
        assert "en" in stats["languages"]


# ============================================================================
# TESTS DEFAULT TEMPLATES
# ============================================================================


class TestDefaultTemplates:
    """Tests pour les templates par défaut."""

    def test_default_templates_not_empty(self):
        """Les templates par défaut ne sont pas vides."""
        assert len(DEFAULT_TEMPLATES) >= 5

    def test_default_templates_have_required_fields(self):
        """Les templates par défaut ont les champs requis."""
        for template in DEFAULT_TEMPLATES:
            assert template.id is not None
            assert template.name is not None
            assert template.category is not None
            assert template.template_body is not None

    def test_default_templates_have_variables(self):
        """Les templates par défaut ont des variables."""
        for template in DEFAULT_TEMPLATES:
            assert "${" in template.template_body

    def test_default_templates_categories(self):
        """Les templates par défaut couvrent les catégories principales."""
        categories = {t.category for t in DEFAULT_TEMPLATES}
        assert "URGENT" in categories
        assert "NORMAL" in categories
        assert "MEETING" in categories


# ============================================================================
# TESTS EDGE CASES
# ============================================================================


class TestJsonEmailTemplateStoreEdgeCases:
    """Tests des cas limites."""

    def test_add_template_with_unicode(self, temp_store):
        """Ajout de template avec unicode."""
        template = EmailTemplate(
            id="unicode-🎉",
            name="Événement Spécial",
            category="RÉUNION",
            template_body="Bonjour ${nom}! 日本語",
        )
        temp_store.add(template)
        result = temp_store.get("unicode-🎉")
        assert result is not None
        assert "日本語" in result.template_body

    def test_render_with_empty_body(self, temp_store):
        """Render avec corps vide."""
        template = EmailTemplate(
            id="empty",
            name="Empty",
            category="TEST",
            template_body="",
        )
        temp_store.add(template)
        result = temp_store.render(template, {})
        assert result == ""

    def test_find_best_match_with_all_disabled(self, tmp_path):
        """Find best match quand tous sont désactivés."""
        filepath = tmp_path / "disabled.json"
        data = {
            "templates": [{
                "id": "t1",
                "name": "T1",
                "category": "TEST",
                "template_body": "B",
                "enabled": False,
            }]
        }
        filepath.write_text(json.dumps(data))
        store = JsonEmailTemplateStore(filepath=filepath)

        match = store.find_best_match("TEST", "subject", "body")
        # Pas de match car désactivé
        assert match is None or match.template.category == "NORMAL"

    def test_very_long_template_body(self, temp_store):
        """Template avec corps très long."""
        long_body = "x" * 100000
        template = EmailTemplate(
            id="long",
            name="Long",
            category="TEST",
            template_body=long_body,
        )
        temp_store.add(template)
        result = temp_store.get("long")
        assert len(result.template_body) == 100000

    def test_special_characters_in_template_id(self, temp_store):
        """Caractères spéciaux dans l'ID du template."""
        template = EmailTemplate(
            id="special-@#$%^&*()",
            name="Special",
            category="TEST",
            template_body="Body",
        )
        temp_store.add(template)
        result = temp_store.get("special-@#$%^&*()")
        assert result is not None
