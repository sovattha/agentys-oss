# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les entités EmailTemplate et TemplateMatch.

pytest tests/domain/entities/test_email_template.py -v
"""

import pytest
from dataclasses import fields, is_dataclass
from datetime import datetime

from app.domain.entities.email_template import (
    EmailTemplate,
    TemplateMatch,
    TemplateVariables,
)


# ============================================================================
# TESTS EMAIL TEMPLATE DATACLASS
# ============================================================================


class TestEmailTemplateCreation:
    """Tests de création d'EmailTemplate."""

    def test_create_with_required_fields_only(self):
        """Création avec champs obligatoires uniquement."""
        template = EmailTemplate(
            id="tpl-001",
            name="Test Template",
            category="URGENT",
            template_body="Hello ${sender_name}",
        )

        assert template.id == "tpl-001"
        assert template.name == "Test Template"
        assert template.category == "URGENT"
        assert template.template_body == "Hello ${sender_name}"

    def test_create_with_all_fields(self):
        """Création avec tous les champs."""
        template = EmailTemplate(
            id="full-template",
            name="Full Template",
            category="MEETING",
            template_body="Body",
            description="A full template",
            language="en",
            tone="casual",
            enabled=False,
            priority=50,
            conditions={"key": "value"},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-02T00:00:00",
            usage_count=10,
        )

        assert template.description == "A full template"
        assert template.language == "en"
        assert template.tone == "casual"
        assert template.enabled is False
        assert template.priority == 50
        assert template.conditions == {"key": "value"}
        assert template.created_at == "2024-01-01T00:00:00"
        assert template.updated_at == "2024-01-02T00:00:00"
        assert template.usage_count == 10


class TestEmailTemplateDefaults:
    """Tests des valeurs par défaut."""

    def test_default_description_is_none(self):
        """Description par défaut est None."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.description is None

    def test_default_language_is_fr(self):
        """Langue par défaut est français."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.language == "fr"

    def test_default_tone_is_professional(self):
        """Ton par défaut est professionnel."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.tone == "professional"

    def test_default_enabled_is_true(self):
        """Template activé par défaut."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.enabled is True

    def test_default_priority_is_zero(self):
        """Priorité par défaut est 0."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.priority == 0

    def test_default_conditions_is_none(self):
        """Conditions par défaut est None."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.conditions is None

    def test_default_updated_at_is_none(self):
        """Updated_at par défaut est None."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.updated_at is None

    def test_default_usage_count_is_zero(self):
        """Usage_count par défaut est 0."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.usage_count == 0

    def test_default_created_at_is_set_automatically(self):
        """Created_at est défini automatiquement."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        assert template.created_at is not None
        # Doit être parseable comme ISO date
        datetime.fromisoformat(template.created_at)


class TestEmailTemplateEdgeCases:
    """Tests des cas limites pour EmailTemplate."""

    def test_empty_id(self):
        """ID vide est accepté."""
        template = EmailTemplate(
            id="", name="T", category="C", template_body="B"
        )
        assert template.id == ""

    def test_empty_name(self):
        """Nom vide est accepté."""
        template = EmailTemplate(
            id="t1", name="", category="C", template_body="B"
        )
        assert template.name == ""

    def test_empty_category(self):
        """Catégorie vide est acceptée."""
        template = EmailTemplate(
            id="t1", name="T", category="", template_body="B"
        )
        assert template.category == ""

    def test_empty_template_body(self):
        """Corps vide est accepté."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body=""
        )
        assert template.template_body == ""

    def test_very_long_template_body(self):
        """Corps très long est accepté."""
        long_body = "x" * 100000
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body=long_body
        )
        assert len(template.template_body) == 100000

    def test_unicode_in_all_fields(self):
        """Unicode dans tous les champs."""
        template = EmailTemplate(
            id="émoji-🎉",
            name="Prénom Événement",
            category="RÉUNION",
            template_body="Bonjour ${nom}! 🎊",
            description="Événement spécial 日本語",
        )
        assert "🎉" in template.id
        assert "Événement" in template.name
        assert "日本語" in template.description

    def test_special_characters_in_template_body(self):
        """Caractères spéciaux dans le corps."""
        template = EmailTemplate(
            id="t1",
            name="T",
            category="C",
            template_body="<script>alert('XSS')</script> & ${var} \"quotes\"",
        )
        assert "<script>" in template.template_body
        assert "&" in template.template_body

    def test_negative_priority(self):
        """Priorité négative est acceptée."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B", priority=-100
        )
        assert template.priority == -100

    def test_very_high_priority(self):
        """Priorité très haute est acceptée."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B", priority=999999
        )
        assert template.priority == 999999

    def test_complex_conditions(self):
        """Conditions complexes."""
        conditions = {
            "subject_contains": ["urgent", "asap", "important"],
            "body_contains": ["help", "assistance"],
            "nested": {"level1": {"level2": "value"}},
        }
        template = EmailTemplate(
            id="t1",
            name="T",
            category="C",
            template_body="B",
            conditions=conditions,
        )
        assert template.conditions["subject_contains"] == ["urgent", "asap", "important"]
        assert template.conditions["nested"]["level1"]["level2"] == "value"


class TestEmailTemplateTypeChecks:
    """Tests de vérification des types."""

    def test_is_dataclass(self):
        """EmailTemplate est une dataclass."""
        assert is_dataclass(EmailTemplate)

    def test_required_fields_count(self):
        """Nombre de champs requis."""
        [
            f for f in fields(EmailTemplate)
            if f.default is f.default_factory is None
            or (f.default is None and f.default_factory is None)
        ]
        # id, name, category, template_body sont requis
        assert len([f for f in fields(EmailTemplate) if f.name in ["id", "name", "category", "template_body"]]) == 4

    def test_missing_required_field_raises(self):
        """Champ requis manquant lève une erreur."""
        with pytest.raises(TypeError):
            EmailTemplate(id="t1", name="T", category="C")  # template_body manquant


class TestEmailTemplateEquality:
    """Tests d'égalité pour EmailTemplate."""

    def test_equal_templates(self):
        """Templates égaux (avec même created_at)."""
        created_at = "2024-01-01T00:00:00"
        t1 = EmailTemplate(id="t1", name="T", category="C", template_body="B", created_at=created_at)
        t2 = EmailTemplate(id="t1", name="T", category="C", template_body="B", created_at=created_at)
        assert t1 == t2

    def test_different_id_not_equal(self):
        """Templates avec ID différent ne sont pas égaux."""
        t1 = EmailTemplate(id="t1", name="T", category="C", template_body="B")
        t2 = EmailTemplate(id="t2", name="T", category="C", template_body="B")
        assert t1 != t2

    def test_different_name_not_equal(self):
        """Templates avec nom différent ne sont pas égaux."""
        t1 = EmailTemplate(id="t1", name="T1", category="C", template_body="B")
        t2 = EmailTemplate(id="t1", name="T2", category="C", template_body="B")
        assert t1 != t2


# ============================================================================
# TESTS TEMPLATE MATCH DATACLASS
# ============================================================================


class TestTemplateMatchCreation:
    """Tests de création de TemplateMatch."""

    def test_create_with_required_fields(self):
        """Création avec champs obligatoires."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=0.85)

        assert match.template == template
        assert match.score == 0.85

    def test_create_with_all_fields(self):
        """Création avec tous les champs."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        variables = {"sender_name": "John", "subject": "Test"}
        match = TemplateMatch(template=template, score=0.95, variables=variables)

        assert match.variables == variables


class TestTemplateMatchDefaults:
    """Tests des valeurs par défaut de TemplateMatch."""

    def test_default_variables_is_empty_dict(self):
        """Variables par défaut est un dict vide."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=0.5)
        assert match.variables == {}


class TestTemplateMatchEdgeCases:
    """Tests des cas limites pour TemplateMatch."""

    def test_score_zero(self):
        """Score à zéro."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=0.0)
        assert match.score == 0.0

    def test_score_one(self):
        """Score à 1."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=1.0)
        assert match.score == 1.0

    def test_score_negative(self):
        """Score négatif (edge case)."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=-0.5)
        assert match.score == -0.5

    def test_score_above_one(self):
        """Score supérieur à 1 (edge case)."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=1.5)
        assert match.score == 1.5

    def test_empty_variables(self):
        """Variables vide explicitement."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        match = TemplateMatch(template=template, score=0.5, variables={})
        assert match.variables == {}

    def test_variables_with_special_characters(self):
        """Variables avec caractères spéciaux."""
        template = EmailTemplate(
            id="t1", name="T", category="C", template_body="B"
        )
        variables = {
            "name": "O'Brien & Co.",
            "email": "test@example.com",
            "special": "<html>🎉</html>",
        }
        match = TemplateMatch(template=template, score=0.5, variables=variables)
        assert match.variables["name"] == "O'Brien & Co."
        assert "🎉" in match.variables["special"]


class TestTemplateMatchTypeChecks:
    """Tests de vérification des types pour TemplateMatch."""

    def test_is_dataclass(self):
        """TemplateMatch est une dataclass."""
        assert is_dataclass(TemplateMatch)


# ============================================================================
# TESTS TEMPLATE VARIABLES
# ============================================================================


class TestTemplateVariablesConstants:
    """Tests des constantes TemplateVariables."""

    def test_sender_name_constant(self):
        """Constante SENDER_NAME."""
        assert TemplateVariables.SENDER_NAME == "sender_name"

    def test_sender_email_constant(self):
        """Constante SENDER_EMAIL."""
        assert TemplateVariables.SENDER_EMAIL == "sender_email"

    def test_subject_constant(self):
        """Constante SUBJECT."""
        assert TemplateVariables.SUBJECT == "subject"

    def test_date_constant(self):
        """Constante DATE."""
        assert TemplateVariables.DATE == "date"

    def test_time_constant(self):
        """Constante TIME."""
        assert TemplateVariables.TIME == "time"

    def test_greeting_constant(self):
        """Constante GREETING."""
        assert TemplateVariables.GREETING == "greeting"

    def test_signature_constant(self):
        """Constante SIGNATURE."""
        assert TemplateVariables.SIGNATURE == "signature"

    def test_company_constant(self):
        """Constante COMPANY."""
        assert TemplateVariables.COMPANY == "company"

    def test_priority_constant(self):
        """Constante PRIORITY."""
        assert TemplateVariables.PRIORITY == "priority"

    def test_category_constant(self):
        """Constante CATEGORY."""
        assert TemplateVariables.CATEGORY == "category"

    def test_thread_count_constant(self):
        """Constante THREAD_COUNT."""
        assert TemplateVariables.THREAD_COUNT == "thread_count"


class TestTemplateVariablesGetAll:
    """Tests de la méthode get_all."""

    def test_get_all_returns_list(self):
        """get_all retourne une liste."""
        result = TemplateVariables.get_all()
        assert isinstance(result, list)

    def test_get_all_contains_all_constants(self):
        """get_all contient toutes les constantes."""
        result = TemplateVariables.get_all()
        assert TemplateVariables.SENDER_NAME in result
        assert TemplateVariables.SENDER_EMAIL in result
        assert TemplateVariables.SUBJECT in result
        assert TemplateVariables.DATE in result
        assert TemplateVariables.TIME in result
        assert TemplateVariables.GREETING in result
        assert TemplateVariables.SIGNATURE in result
        assert TemplateVariables.COMPANY in result
        assert TemplateVariables.PRIORITY in result
        assert TemplateVariables.CATEGORY in result
        assert TemplateVariables.THREAD_COUNT in result

    def test_get_all_returns_at_least_11_variables(self):
        """get_all retourne au moins 11 variables."""
        result = TemplateVariables.get_all()
        assert len(result) >= 11

    def test_get_all_returns_new_list_each_call(self):
        """get_all retourne une nouvelle liste à chaque appel."""
        result1 = TemplateVariables.get_all()
        result2 = TemplateVariables.get_all()
        # Contenus égaux
        assert result1 == result2
        # Mais pas le même objet
        assert result1 is not result2

    def test_get_all_all_strings(self):
        """Toutes les valeurs sont des chaînes."""
        result = TemplateVariables.get_all()
        assert all(isinstance(v, str) for v in result)

    def test_get_all_no_duplicates(self):
        """Pas de doublons dans la liste."""
        result = TemplateVariables.get_all()
        assert len(result) == len(set(result))
