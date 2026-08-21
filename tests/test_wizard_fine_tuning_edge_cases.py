# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour WizardConfig et Fine-tuning entities.

Ces tests couvrent:
- WizardConfig: sérialisation/désérialisation, méthodes métier
- AgentActivation: priorités, états
- Fine-tuning: corrections, patterns, modèles d'amélioration
- Validation des enums et valeurs limites
"""

import pytest

from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
    AgentActivation,
    KnowledgeBaseConfig,
)
from app.domain.entities.fine_tuning import (
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    FineTuningStats,
)


# ============================================================================
# TESTS - WizardConfig EDGE CASES
# ============================================================================

class TestWizardConfigEdgeCases:
    """Tests edge cases pour WizardConfig."""

    def test_minimal_wizard_config(self):
        """Configuration minimale valide."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test Company"
        )
        assert config.config_id == "cfg-001"
        assert config.company_name == "Test Company"
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB
        assert config.is_complete is False

    def test_empty_company_name(self):
        """Nom d'entreprise vide (autorisé mais edge case)."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name=""
        )
        assert config.company_name == ""

    def test_unicode_company_name(self):
        """Nom d'entreprise avec unicode."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Société Française 日本語 🏢"
        )
        assert "日本語" in config.company_name
        assert "🏢" in config.company_name

    def test_very_long_company_name(self):
        """Nom d'entreprise très long."""
        long_name = "A" * 10000
        config = WizardConfig(
            config_id="cfg-001",
            company_name=long_name
        )
        assert len(config.company_name) == 10000

    def test_all_business_sectors(self):
        """Test tous les secteurs d'activité."""
        for sector in BusinessSector:
            config = WizardConfig(
                config_id="cfg-001",
                company_name="Test",
                sector=sector
            )
            assert config.sector == sector

    def test_all_company_sizes(self):
        """Test toutes les tailles d'entreprise."""
        for size in CompanySize:
            config = WizardConfig(
                config_id="cfg-001",
                company_name="Test",
                size=size
            )
            assert config.size == size

    def test_all_config_packs(self):
        """Test tous les packs de configuration."""
        for pack in ConfigPack:
            config = WizardConfig(
                config_id="cfg-001",
                company_name="Test",
                pack=pack
            )
            assert config.pack == pack

    def test_activate_agent_new(self):
        """Activation d'un nouvel agent."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test"
        )
        initial_count = len(config.agents)

        config.activate_agent("agent-001", priority=75)

        assert len(config.agents) == initial_count + 1
        assert config.is_agent_active("agent-001") is True

    def test_activate_agent_existing(self):
        """Réactivation d'un agent existant."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test",
            agents=[AgentActivation(agent_id="agent-001", enabled=False, priority=25)]
        )

        config.activate_agent("agent-001", priority=90)

        assert len(config.agents) == 1
        assert config.is_agent_active("agent-001") is True
        agent = next(a for a in config.agents if a.agent_id == "agent-001")
        assert agent.priority == 90

    def test_deactivate_agent(self):
        """Désactivation d'un agent."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test",
            agents=[AgentActivation(agent_id="agent-001", enabled=True)]
        )

        config.deactivate_agent("agent-001")

        assert config.is_agent_active("agent-001") is False

    def test_deactivate_nonexistent_agent(self):
        """Désactivation d'un agent inexistant (no-op)."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test"
        )

        # Ne doit pas lever d'erreur
        config.deactivate_agent("nonexistent-agent")

    def test_is_agent_active_nonexistent(self):
        """Vérification d'un agent inexistant."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test"
        )

        assert config.is_agent_active("nonexistent") is False

    def test_get_active_agents_sorted(self):
        """Agents actifs triés par priorité."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="low", priority=10, enabled=True),
                AgentActivation(agent_id="high", priority=90, enabled=True),
                AgentActivation(agent_id="medium", priority=50, enabled=True),
                AgentActivation(agent_id="disabled", priority=100, enabled=False),
            ]
        )

        active = config.get_active_agents()

        assert len(active) == 3
        assert active[0].agent_id == "high"  # Priorité la plus haute en premier
        assert active[1].agent_id == "medium"
        assert active[2].agent_id == "low"

    def test_get_active_agents_all_disabled(self):
        """Tous les agents désactivés."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="a1", enabled=False),
                AgentActivation(agent_id="a2", enabled=False),
            ]
        )

        active = config.get_active_agents()
        assert active == []

    def test_mark_complete(self):
        """Marquage comme terminé."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test"
        )
        original_updated = config.updated_at

        config.mark_complete()

        assert config.is_complete is True
        assert config.updated_at >= original_updated

    def test_to_dict_complete(self):
        """Sérialisation complète."""
        config = WizardConfig(
            config_id="cfg-001",
            company_name="Test Corp",
            sector=BusinessSector.TECH,
            size=CompanySize.STARTUP,
            primary_language="en",
            supported_languages=["en", "fr", "de"],
            pack=ConfigPack.SAAS,
            agents=[AgentActivation(agent_id="a1", priority=75)],
            knowledge_base=KnowledgeBaseConfig(
                company_name="Test",
                forbidden_topics=["politics", "religion"],
                custom_signatures={"default": "Best regards"},
                faq_entries={"Q1": "A1"}
            ),
            version=2,
            is_complete=True
        )

        data = config.to_dict()

        assert data["config_id"] == "cfg-001"
        assert data["sector"] == "tech"
        assert data["size"] == "startup"
        assert len(data["agents"]) == 1
        assert data["knowledge_base"]["forbidden_topics"] == ["politics", "religion"]
        assert data["is_complete"] is True

    def test_from_dict_complete(self):
        """Désérialisation complète."""
        data = {
            "config_id": "cfg-002",
            "company_name": "Restored Corp",
            "sector": "finance",
            "size": "enterprise",
            "primary_language": "fr",
            "supported_languages": ["fr"],
            "pack": "b2b",
            "agents": [
                {"agent_id": "a1", "enabled": True, "priority": 80},
                {"agent_id": "a2", "enabled": False, "priority": 20},
            ],
            "knowledge_base": {
                "company_name": "Restored",
                "company_description": "Description",
                "tone_guidelines": "Professional",
            },
            "created_at": "2024-01-15T10:30:00",
            "updated_at": "2024-06-20T14:45:00",
            "version": 3,
            "is_complete": True
        }

        config = WizardConfig.from_dict(data)

        assert config.config_id == "cfg-002"
        assert config.sector == BusinessSector.FINANCE
        assert config.size == CompanySize.ENTERPRISE
        assert len(config.agents) == 2
        assert config.is_complete is True
        assert config.version == 3

    def test_from_dict_minimal(self):
        """Désérialisation avec champs minimaux."""
        data = {
            "config_id": "cfg-minimal"
        }

        config = WizardConfig.from_dict(data)

        assert config.config_id == "cfg-minimal"
        assert config.company_name == ""
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB

    def test_from_dict_invalid_sector(self):
        """Secteur invalide lève une erreur."""
        data = {
            "config_id": "cfg-001",
            "sector": "invalid_sector"
        }

        with pytest.raises(ValueError):
            WizardConfig.from_dict(data)

    def test_from_dict_invalid_size(self):
        """Taille invalide lève une erreur."""
        data = {
            "config_id": "cfg-001",
            "size": "huge"
        }

        with pytest.raises(ValueError):
            WizardConfig.from_dict(data)

    def test_roundtrip_serialization(self):
        """Aller-retour to_dict/from_dict."""
        original = WizardConfig(
            config_id="roundtrip-001",
            company_name="Roundtrip Corp",
            sector=BusinessSector.ECOMMERCE,
            size=CompanySize.MIDMARKET,
            agents=[
                AgentActivation(agent_id="a1", priority=80, custom_prompt_override="Custom"),
            ],
            knowledge_base=KnowledgeBaseConfig(
                company_name="RC",
                products_services="E-commerce platform",
                custom_file_path="/path/to/kb.md"
            )
        )

        data = original.to_dict()
        restored = WizardConfig.from_dict(data)

        assert restored.config_id == original.config_id
        assert restored.sector == original.sector
        assert len(restored.agents) == len(original.agents)
        assert restored.agents[0].custom_prompt_override == "Custom"


# ============================================================================
# TESTS - AgentActivation EDGE CASES
# ============================================================================

class TestAgentActivationEdgeCases:
    """Tests edge cases pour AgentActivation."""

    def test_priority_zero(self):
        """Priorité à zéro."""
        agent = AgentActivation(agent_id="a1", priority=0)
        assert agent.priority == 0

    def test_priority_maximum(self):
        """Priorité à 100."""
        agent = AgentActivation(agent_id="a1", priority=100)
        assert agent.priority == 100

    def test_priority_negative(self):
        """Priorité négative (edge case, pas de validation)."""
        agent = AgentActivation(agent_id="a1", priority=-10)
        assert agent.priority == -10

    def test_priority_over_100(self):
        """Priorité > 100 (edge case, pas de validation)."""
        agent = AgentActivation(agent_id="a1", priority=150)
        assert agent.priority == 150

    def test_empty_agent_id(self):
        """ID agent vide."""
        agent = AgentActivation(agent_id="", enabled=True)
        assert agent.agent_id == ""

    def test_custom_prompt_override(self):
        """Override de prompt personnalisé."""
        custom_prompt = "Tu es un assistant spécialisé en vente"
        agent = AgentActivation(
            agent_id="sales-agent",
            custom_prompt_override=custom_prompt
        )
        assert agent.custom_prompt_override == custom_prompt


# ============================================================================
# TESTS - KnowledgeBaseConfig EDGE CASES
# ============================================================================

class TestKnowledgeBaseConfigEdgeCases:
    """Tests edge cases pour KnowledgeBaseConfig."""

    def test_empty_config(self):
        """Configuration vide."""
        kb = KnowledgeBaseConfig()
        assert kb.company_name == ""
        assert kb.forbidden_topics == []
        assert kb.custom_signatures == {}

    def test_forbidden_topics_with_duplicates(self):
        """Topics interdits avec doublons (pas de déduplication automatique)."""
        kb = KnowledgeBaseConfig(
            forbidden_topics=["politics", "politics", "religion"]
        )
        assert len(kb.forbidden_topics) == 3

    def test_faq_entries_special_keys(self):
        """FAQ avec clés spéciales."""
        kb = KnowledgeBaseConfig(
            faq_entries={
                "Question avec accents é à ü?": "Réponse",
                "🤔 Question emoji?": "Réponse emoji 🎉",
                "": "Clé vide",
            }
        )
        assert len(kb.faq_entries) == 3

    def test_custom_file_path_none(self):
        """Chemin personnalisé None."""
        kb = KnowledgeBaseConfig(custom_file_path=None)
        assert kb.custom_file_path is None

    def test_custom_file_path_with_spaces(self):
        """Chemin avec espaces."""
        kb = KnowledgeBaseConfig(
            custom_file_path="/path/with spaces/knowledge base.md"
        )
        assert " " in kb.custom_file_path


# ============================================================================
# TESTS - UserCorrection EDGE CASES
# ============================================================================

class TestUserCorrectionEdgeCases:
    """Tests edge cases pour UserCorrection."""

    def test_create_minimal(self):
        """Création minimale."""
        correction = UserCorrection.create(
            draft_id="draft-001",
            original_text="Original",
            corrected_text="Corrected"
        )
        assert correction.draft_id == "draft-001"
        assert correction.id is not None  # UUID généré

    def test_has_significant_changes_empty_original(self):
        """Changements significatifs avec original vide."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text="New content"
        )
        assert correction.has_significant_changes() is True

    def test_has_significant_changes_empty_both(self):
        """Les deux vides."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text=""
        )
        assert correction.has_significant_changes() is False

    def test_has_significant_changes_minimal_diff(self):
        """Différence minimale."""
        original = "Hello World"
        corrected = "Hello world"  # Juste une majuscule
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text=original,
            corrected_text=corrected
        )
        # Un seul caractère différent sur 11 = ~9% -> selon min_diff_ratio=5%, significant
        assert correction.has_significant_changes(min_diff_ratio=0.05) is True

    def test_has_significant_changes_custom_ratio(self):
        """Ratio personnalisé."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="Hello World",
            corrected_text="Hello world"
        )
        # Avec ratio très élevé, pas significant
        assert correction.has_significant_changes(min_diff_ratio=0.50) is False

    def test_correction_types_list(self):
        """Liste des types de correction."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="Test",
            corrected_text="Test modifié",
            correction_types=[CorrectionType.TONE, CorrectionType.GRAMMAR]
        )
        assert len(correction.correction_types) == 2
        assert CorrectionType.TONE in correction.correction_types

    def test_context_complex_structure(self):
        """Contexte avec structure complexe."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="a",
            corrected_text="b",
            context={
                "sender": "client@example.com",
                "category": "support",
                "priority": 5,
                "metadata": {"tags": ["urgent", "vip"]}
            }
        )
        assert correction.context["priority"] == 5
        assert "urgent" in correction.context["metadata"]["tags"]


# ============================================================================
# TESTS - UserFeedback EDGE CASES
# ============================================================================

class TestUserFeedbackEdgeCases:
    """Tests edge cases pour UserFeedback."""

    def test_rating_boundary_1(self):
        """Rating minimum (1)."""
        feedback = UserFeedback.create(draft_id="d1", rating=1)
        assert feedback.rating == 1
        assert feedback.sentiment == FeedbackSentiment.NEGATIVE

    def test_rating_boundary_5(self):
        """Rating maximum (5)."""
        feedback = UserFeedback.create(draft_id="d1", rating=5)
        assert feedback.rating == 5
        assert feedback.sentiment == FeedbackSentiment.POSITIVE

    def test_rating_neutral(self):
        """Rating neutre (3)."""
        feedback = UserFeedback.create(draft_id="d1", rating=3)
        assert feedback.sentiment == FeedbackSentiment.NEUTRAL

    def test_rating_0_raises(self):
        """Rating 0 lève une erreur."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=0)

    def test_rating_6_raises(self):
        """Rating 6 lève une erreur."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=6)

    def test_rating_negative_raises(self):
        """Rating négatif lève une erreur."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=-1)

    def test_tags_list(self):
        """Liste de tags."""
        feedback = UserFeedback.create(
            draft_id="d1",
            rating=4,
            tags=["professional", "clear", "concise"]
        )
        assert len(feedback.tags) == 3

    def test_comment_unicode(self):
        """Commentaire avec unicode."""
        feedback = UserFeedback.create(
            draft_id="d1",
            rating=5,
            comment="Excellent travail 🎉 日本語テスト"
        )
        assert "🎉" in feedback.comment


# ============================================================================
# TESTS - CorrectionPattern EDGE CASES
# ============================================================================

class TestCorrectionPatternEdgeCases:
    """Tests edge cases pour CorrectionPattern."""

    def test_create_minimal(self):
        """Création minimale."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="Cordialement",
            replacement="Bien cordialement"
        )
        assert pattern.occurrences == 1
        assert pattern.confidence == 0.5

    def test_increment_occurrence(self):
        """Incrémentation des occurrences."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="Cher",
            replacement="Bonjour"
        )

        for _ in range(5):
            pattern.increment_occurrence()

        assert pattern.occurrences == 6
        assert pattern.confidence == 0.6  # 6/10

    def test_confidence_max_at_10(self):
        """Confiance maximale à 10 occurrences."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="a",
            replacement="b"
        )

        for _ in range(15):
            pattern.increment_occurrence()

        assert pattern.occurrences == 16
        assert pattern.confidence == 1.0  # Plafonné

    def test_is_reliable_threshold(self):
        """Seuil de fiabilité."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="a",
            replacement="b",
            confidence=0.5
        )

        assert pattern.is_reliable(min_confidence=0.6) is False
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.4) is True

    def test_examples_list(self):
        """Liste d'exemples."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.CONTENT,
            original_pattern="Veuillez",
            replacement="Merci de",
            examples=[
                {"original": "Veuillez répondre", "corrected": "Merci de répondre"},
                {"original": "Veuillez noter", "corrected": "Merci de noter"},
            ]
        )
        assert len(pattern.examples) == 2


# ============================================================================
# TESTS - ImprovementModel EDGE CASES
# ============================================================================

class TestImprovementModelEdgeCases:
    """Tests edge cases pour ImprovementModel."""

    def test_create_minimal(self):
        """Création minimale."""
        model = ImprovementModel.create(
            name="Tone Improvements",
            description="Améliore le ton des emails"
        )
        assert model.status == ImprovementStatus.PENDING
        assert model.version == "1.0.0"
        assert model.patterns == []

    def test_lifecycle_activate_disable(self):
        """Cycle de vie: activation et désactivation."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

        model.disable()
        assert model.status == ImprovementStatus.DISABLED

        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED

    def test_add_pattern_unique(self):
        """Ajout de patterns (sans doublons)."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_pattern("pattern-001")
        model.add_pattern("pattern-002")
        model.add_pattern("pattern-001")  # Doublon ignoré

        assert len(model.patterns) == 2

    def test_add_prompt_adjustment(self):
        """Ajout d'ajustements de prompt."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_prompt_adjustment("Utilise un ton plus formel")
        model.add_prompt_adjustment("Évite les emojis")

        assert len(model.prompt_adjustments) == 2

    def test_record_improvement(self):
        """Enregistrement d'amélioration."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.record_improvement()
        model.record_improvement()

        assert model.drafts_improved == 2

    def test_update_impact_score_initial(self):
        """Mise à jour score d'impact initial."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.update_impact_score(0.8)

        assert model.impact_score == 0.8

    def test_update_impact_score_average(self):
        """Moyenne mobile du score d'impact."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.drafts_improved = 2
        model.impact_score = 0.6

        # Nouvelle moyenne: (0.6 * 1 + 0.9) / 2 = 0.75
        model.update_impact_score(0.9)

        assert model.impact_score == pytest.approx(0.75)


# ============================================================================
# TESTS - FineTuningSession EDGE CASES
# ============================================================================

class TestFineTuningSessionEdgeCases:
    """Tests edge cases pour FineTuningSession."""

    def test_create_generates_uuid(self):
        """Création génère un UUID."""
        session1 = FineTuningSession.create()
        session2 = FineTuningSession.create()

        assert session1.id != session2.id
        assert session1.status == "running"

    def test_complete_with_model(self):
        """Complétion avec ID de modèle."""
        session = FineTuningSession.create()
        session.corrections_count = 50
        session.patterns_extracted = 10

        session.complete(model_id="model-001")

        assert session.status == "completed"
        assert session.model_id == "model-001"
        assert session.ended_at is not None

    def test_complete_without_model(self):
        """Complétion sans modèle."""
        session = FineTuningSession.create()

        session.complete()

        assert session.status == "completed"
        assert session.model_id is None

    def test_fail_with_error(self):
        """Échec avec message d'erreur."""
        session = FineTuningSession.create()

        session.fail("Not enough data for training")

        assert "failed" in session.status
        assert "Not enough data" in session.status


# ============================================================================
# TESTS - FineTuningStats EDGE CASES
# ============================================================================

class TestFineTuningStatsEdgeCases:
    """Tests edge cases pour FineTuningStats."""

    def test_default_values(self):
        """Valeurs par défaut."""
        stats = FineTuningStats()

        assert stats.total_corrections == 0
        assert stats.total_feedbacks == 0
        assert stats.average_impact == 0.0
        assert stats.improvement_rate == 0.0

    def test_top_correction_types_dict(self):
        """Dictionnaire des types de correction les plus fréquents."""
        stats = FineTuningStats(
            top_correction_types={
                "tone": 50,
                "grammar": 30,
                "style": 20
            }
        )
        assert stats.top_correction_types["tone"] == 50

    def test_feedback_sentiment_distribution(self):
        """Distribution des sentiments."""
        stats = FineTuningStats(
            feedback_sentiment_distribution={
                "positive": 100,
                "neutral": 30,
                "negative": 10
            }
        )
        total = sum(stats.feedback_sentiment_distribution.values())
        assert total == 140


# ============================================================================
# TESTS - ENUM COMPLETENESS
# ============================================================================

class TestEnumCompleteness:
    """Tests de complétude des enums."""

    def test_correction_type_all_values(self):
        """Tous les types de correction."""
        expected = [
            "tone", "grammar", "style", "content",
            "format", "length", "vocabulary", "structure"
        ]
        actual = [t.value for t in CorrectionType]
        assert set(expected) == set(actual)

    def test_improvement_status_all_values(self):
        """Tous les statuts d'amélioration."""
        expected = ["pending", "active", "disabled", "deprecated"]
        actual = [s.value for s in ImprovementStatus]
        assert set(expected) == set(actual)

    def test_feedback_sentiment_all_values(self):
        """Tous les sentiments."""
        expected = ["positive", "neutral", "negative"]
        actual = [s.value for s in FeedbackSentiment]
        assert set(expected) == set(actual)

    def test_business_sector_count(self):
        """Nombre de secteurs."""
        assert len(list(BusinessSector)) == 15

    def test_company_size_count(self):
        """Nombre de tailles."""
        assert len(list(CompanySize)) == 5

    def test_config_pack_count(self):
        """Nombre de packs."""
        assert len(list(ConfigPack)) == 7
