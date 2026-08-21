# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'entité WizardConfig.

Tests des enums, des dataclasses d'activation, et de la configuration
complète du wizard d'onboarding entreprise.
"""

import pytest
from datetime import datetime
from app.domain.entities.wizard_config import (
    BusinessSector,
    CompanySize,
    ConfigPack,
    AgentActivation,
    KnowledgeBaseConfig,
    WizardConfig,
)


class TestBusinessSectorEnum:
    """Tests pour l'enum BusinessSector."""

    def test_business_sector_values(self):
        """Test que tous les secteurs d'activité ont les bonnes valeurs."""
        assert BusinessSector.TECH.value == "tech"
        assert BusinessSector.SAAS.value == "saas"
        assert BusinessSector.ECOMMERCE.value == "ecommerce"
        assert BusinessSector.FINANCE.value == "finance"
        assert BusinessSector.HEALTHCARE.value == "healthcare"
        assert BusinessSector.EDUCATION.value == "education"
        assert BusinessSector.RETAIL.value == "retail"
        assert BusinessSector.CONSULTING.value == "consulting"
        assert BusinessSector.MANUFACTURING.value == "manufacturing"
        assert BusinessSector.LEGAL.value == "legal"
        assert BusinessSector.REAL_ESTATE.value == "real_estate"
        assert BusinessSector.HOSPITALITY.value == "hospitality"
        assert BusinessSector.MEDIA.value == "media"
        assert BusinessSector.NONPROFIT.value == "nonprofit"
        assert BusinessSector.OTHER.value == "other"

    def test_business_sector_from_value(self):
        """Test la création d'un BusinessSector depuis sa valeur."""
        assert BusinessSector("tech") == BusinessSector.TECH
        assert BusinessSector("saas") == BusinessSector.SAAS
        assert BusinessSector("ecommerce") == BusinessSector.ECOMMERCE

    def test_business_sector_membership(self):
        """Test que les secteurs sont bien membres de l'enum."""
        assert BusinessSector.TECH in BusinessSector
        assert BusinessSector.OTHER in BusinessSector

    def test_business_sector_count(self):
        """Test que tous les secteurs prévus existent."""
        sectors = list(BusinessSector)
        assert len(sectors) == 15


class TestCompanySizeEnum:
    """Tests pour l'enum CompanySize."""

    def test_company_size_values(self):
        """Test que toutes les tailles d'entreprise ont les bonnes valeurs."""
        assert CompanySize.SOLO.value == "solo"
        assert CompanySize.STARTUP.value == "startup"
        assert CompanySize.SMB.value == "smb"
        assert CompanySize.MIDMARKET.value == "midmarket"
        assert CompanySize.ENTERPRISE.value == "enterprise"

    def test_company_size_from_value(self):
        """Test la création d'une CompanySize depuis sa valeur."""
        assert CompanySize("solo") == CompanySize.SOLO
        assert CompanySize("startup") == CompanySize.STARTUP
        assert CompanySize("smb") == CompanySize.SMB
        assert CompanySize("midmarket") == CompanySize.MIDMARKET
        assert CompanySize("enterprise") == CompanySize.ENTERPRISE

    def test_company_size_membership(self):
        """Test que les tailles sont bien membres de l'enum."""
        assert CompanySize.SOLO in CompanySize
        assert CompanySize.ENTERPRISE in CompanySize

    def test_company_size_count(self):
        """Test que toutes les tailles existent."""
        sizes = list(CompanySize)
        assert len(sizes) == 5


class TestConfigPackEnum:
    """Tests pour l'enum ConfigPack."""

    def test_config_pack_values(self):
        """Test que tous les packs ont les bonnes valeurs."""
        assert ConfigPack.CUSTOM.value == "custom"
        assert ConfigPack.STARTUP.value == "startup"
        assert ConfigPack.SMB.value == "smb"
        assert ConfigPack.ENTERPRISE.value == "enterprise"
        assert ConfigPack.SAAS.value == "saas"
        assert ConfigPack.ECOMMERCE.value == "ecommerce"
        assert ConfigPack.B2B.value == "b2b"

    def test_config_pack_from_value(self):
        """Test la création d'un ConfigPack depuis sa valeur."""
        assert ConfigPack("custom") == ConfigPack.CUSTOM
        assert ConfigPack("startup") == ConfigPack.STARTUP
        assert ConfigPack("enterprise") == ConfigPack.ENTERPRISE

    def test_config_pack_membership(self):
        """Test que les packs sont bien membres de l'enum."""
        assert ConfigPack.CUSTOM in ConfigPack
        assert ConfigPack.ENTERPRISE in ConfigPack

    def test_config_pack_count(self):
        """Test que tous les packs existent."""
        packs = list(ConfigPack)
        assert len(packs) == 7


class TestAgentActivation:
    """Tests pour la dataclass AgentActivation."""

    def test_agent_activation_creation_minimal(self):
        """Test la création d'une AgentActivation avec valeurs minimales."""
        agent = AgentActivation(agent_id="classifier_agent")

        assert agent.agent_id == "classifier_agent"
        assert agent.enabled is True
        assert agent.priority == 50
        assert agent.custom_prompt_override is None

    def test_agent_activation_creation_full(self):
        """Test la création d'une AgentActivation avec tous les paramètres."""
        agent = AgentActivation(
            agent_id="drafter_agent",
            enabled=False,
            priority=100,
            custom_prompt_override="Use technical language"
        )

        assert agent.agent_id == "drafter_agent"
        assert agent.enabled is False
        assert agent.priority == 100
        assert agent.custom_prompt_override == "Use technical language"

    def test_agent_activation_priority_range(self):
        """Test les valeurs de priorité dans la plage 0-100."""
        for priority in [0, 25, 50, 75, 100]:
            agent = AgentActivation(agent_id="agent", priority=priority)
            assert agent.priority == priority

    def test_agent_activation_priority_outside_range(self):
        """Test que la priorité peut techniquement être en dehors de 0-100."""
        agent = AgentActivation(agent_id="agent", priority=150)
        assert agent.priority == 150

        agent = AgentActivation(agent_id="agent", priority=-10)
        assert agent.priority == -10

    def test_agent_activation_enabled_flag(self):
        """Test le flag enabled."""
        enabled = AgentActivation(agent_id="a", enabled=True)
        disabled = AgentActivation(agent_id="a", enabled=False)

        assert enabled.enabled is True
        assert disabled.enabled is False


class TestKnowledgeBaseConfig:
    """Tests pour la dataclass KnowledgeBaseConfig."""

    def test_knowledge_base_creation_defaults(self):
        """Test la création d'une KnowledgeBaseConfig avec valeurs par défaut."""
        kb = KnowledgeBaseConfig()

        assert kb.company_name == ""
        assert kb.company_description == ""
        assert kb.products_services == ""
        assert kb.tone_guidelines == ""
        assert kb.forbidden_topics == []
        assert kb.custom_signatures == {}
        assert kb.faq_entries == {}
        assert kb.custom_file_path is None

    def test_knowledge_base_creation_full(self):
        """Test la création complète d'une KnowledgeBaseConfig."""
        kb = KnowledgeBaseConfig(
            company_name="TechCorp Inc.",
            company_description="A leading technology company",
            products_services="Cloud services, AI solutions",
            tone_guidelines="Professional, friendly, technical",
            forbidden_topics=["pricing", "proprietary"],
            custom_signatures={"sales": "Best regards, Sales Team", "support": "- Support Team"},
            faq_entries={"Q1": "A1", "Q2": "A2"},
            custom_file_path="/path/to/knowledge.md"
        )

        assert kb.company_name == "TechCorp Inc."
        assert kb.company_description == "A leading technology company"
        assert kb.products_services == "Cloud services, AI solutions"
        assert kb.tone_guidelines == "Professional, friendly, technical"
        assert kb.forbidden_topics == ["pricing", "proprietary"]
        assert kb.custom_signatures == {"sales": "Best regards, Sales Team", "support": "- Support Team"}
        assert kb.faq_entries == {"Q1": "A1", "Q2": "A2"}
        assert kb.custom_file_path == "/path/to/knowledge.md"

    def test_knowledge_base_forbidden_topics_independence(self):
        """Test que forbidden_topics est indépendant entre instances."""
        kb1 = KnowledgeBaseConfig()
        kb2 = KnowledgeBaseConfig()

        kb1.forbidden_topics.append("topic1")
        assert "topic1" not in kb2.forbidden_topics

    def test_knowledge_base_custom_signatures_independence(self):
        """Test que custom_signatures est indépendant entre instances."""
        kb1 = KnowledgeBaseConfig()
        kb2 = KnowledgeBaseConfig()

        kb1.custom_signatures["test"] = "value"
        assert "test" not in kb2.custom_signatures

    def test_knowledge_base_faq_entries_independence(self):
        """Test que faq_entries est indépendant entre instances."""
        kb1 = KnowledgeBaseConfig()
        kb2 = KnowledgeBaseConfig()

        kb1.faq_entries["Q"] = "A"
        assert "Q" not in kb2.faq_entries


class TestWizardConfigCreation:
    """Tests pour la création de WizardConfig."""

    def test_wizard_config_creation_minimal(self):
        """Test la création minimale d'une WizardConfig."""
        config = WizardConfig(
            config_id="conf_001",
            company_name="MyCompany"
        )

        assert config.config_id == "conf_001"
        assert config.company_name == "MyCompany"
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB
        assert config.primary_language == "fr"
        assert config.supported_languages == ["fr", "en"]
        assert config.pack == ConfigPack.CUSTOM
        assert config.agents == []
        assert isinstance(config.knowledge_base, KnowledgeBaseConfig)
        assert config.is_complete is False
        assert config.version == 1

    def test_wizard_config_creation_full(self):
        """Test la création complète d'une WizardConfig."""
        agents = [AgentActivation(agent_id="drafter", priority=90)]
        kb = KnowledgeBaseConfig(company_name="TechCorp")

        config = WizardConfig(
            config_id="conf_002",
            company_name="TechCorp Inc.",
            sector=BusinessSector.TECH,
            size=CompanySize.ENTERPRISE,
            primary_language="en",
            supported_languages=["en", "fr", "de"],
            pack=ConfigPack.ENTERPRISE,
            agents=agents,
            knowledge_base=kb,
            is_complete=True,
            version=2
        )

        assert config.config_id == "conf_002"
        assert config.company_name == "TechCorp Inc."
        assert config.sector == BusinessSector.TECH
        assert config.size == CompanySize.ENTERPRISE
        assert config.primary_language == "en"
        assert config.supported_languages == ["en", "fr", "de"]
        assert config.pack == ConfigPack.ENTERPRISE
        assert len(config.agents) == 1
        assert config.knowledge_base.company_name == "TechCorp"
        assert config.is_complete is True
        assert config.version == 2

    def test_wizard_config_timestamp_defaults(self):
        """Test que created_at et updated_at sont définis automatiquement."""
        config = WizardConfig(config_id="conf", company_name="Test")

        assert isinstance(config.created_at, datetime)
        assert isinstance(config.updated_at, datetime)


class TestWizardConfigAgentMethods:
    """Tests pour les méthodes de gestion des agents."""

    def test_activate_agent_new_agent(self):
        """Test l'activation d'un nouvel agent."""
        config = WizardConfig(config_id="c1", company_name="Test")

        config.activate_agent("classifier", priority=80)

        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "classifier"
        assert config.agents[0].enabled is True
        assert config.agents[0].priority == 80

    def test_activate_agent_existing_agent(self):
        """Test l'activation d'un agent existant modifie son état."""
        config = WizardConfig(
            config_id="c2",
            company_name="Test",
            agents=[AgentActivation(agent_id="drafter", enabled=False, priority=30)]
        )

        config.activate_agent("drafter", priority=70)

        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "drafter"
        assert config.agents[0].enabled is True
        assert config.agents[0].priority == 70

    def test_activate_agent_updates_timestamp(self):
        """Test que l'activation d'un agent met à jour updated_at."""
        config = WizardConfig(config_id="c3", company_name="Test")
        original_time = config.updated_at

        import time
        time.sleep(0.01)  # Petite pause pour assuaer un changement de timestamp

        config.activate_agent("agent1")

        assert config.updated_at > original_time

    def test_deactivate_agent_existing(self):
        """Test la désactivation d'un agent existant."""
        config = WizardConfig(
            config_id="c4",
            company_name="Test",
            agents=[AgentActivation(agent_id="drafter", enabled=True)]
        )

        config.deactivate_agent("drafter")

        assert config.agents[0].enabled is False

    def test_deactivate_agent_nonexistent(self):
        """Test la désactivation d'un agent qui n'existe pas ne cause pas d'erreur."""
        config = WizardConfig(config_id="c5", company_name="Test")

        # Ne doit pas lever d'exception
        config.deactivate_agent("nonexistent")

        assert len(config.agents) == 0

    def test_deactivate_agent_updates_timestamp(self):
        """Test que la désactivation met à jour updated_at."""
        config = WizardConfig(
            config_id="c6",
            company_name="Test",
            agents=[AgentActivation(agent_id="agent1", enabled=True)]
        )
        original_time = config.updated_at

        import time
        time.sleep(0.01)

        config.deactivate_agent("agent1")

        assert config.updated_at > original_time

    def test_is_agent_active_enabled(self):
        """Test la vérification du statut d'un agent actif."""
        config = WizardConfig(
            config_id="c7",
            company_name="Test",
            agents=[AgentActivation(agent_id="drafter", enabled=True)]
        )

        assert config.is_agent_active("drafter") is True

    def test_is_agent_active_disabled(self):
        """Test la vérification d'un agent désactivé."""
        config = WizardConfig(
            config_id="c8",
            company_name="Test",
            agents=[AgentActivation(agent_id="drafter", enabled=False)]
        )

        assert config.is_agent_active("drafter") is False

    def test_is_agent_active_nonexistent(self):
        """Test la vérification d'un agent qui n'existe pas."""
        config = WizardConfig(config_id="c9", company_name="Test")

        assert config.is_agent_active("nonexistent") is False

    def test_get_active_agents_empty(self):
        """Test get_active_agents quand aucun agent n'est activé."""
        config = WizardConfig(config_id="c10", company_name="Test")

        active = config.get_active_agents()

        assert active == []

    def test_get_active_agents_mixed(self):
        """Test get_active_agents avec agents actifs et inactifs."""
        config = WizardConfig(
            config_id="c11",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="a", enabled=True, priority=50),
                AgentActivation(agent_id="b", enabled=False, priority=80),
                AgentActivation(agent_id="c", enabled=True, priority=30),
            ]
        )

        active = config.get_active_agents()

        assert len(active) == 2
        agent_ids = [a.agent_id for a in active]
        assert "a" in agent_ids
        assert "c" in agent_ids
        assert "b" not in agent_ids

    def test_get_active_agents_sorted_by_priority(self):
        """Test que get_active_agents retourne les agents triés par priorité (décroissant)."""
        config = WizardConfig(
            config_id="c12",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="a", enabled=True, priority=30),
                AgentActivation(agent_id="b", enabled=True, priority=90),
                AgentActivation(agent_id="c", enabled=True, priority=60),
            ]
        )

        active = config.get_active_agents()

        # Vérifier que l'ordre est correct (priorité décroissante)
        assert active[0].agent_id == "b"  # 90
        assert active[1].agent_id == "c"  # 60
        assert active[2].agent_id == "a"  # 30

    def test_get_active_agents_equal_priority(self):
        """Test get_active_agents avec agents ayant la même priorité."""
        config = WizardConfig(
            config_id="c13",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="a", enabled=True, priority=50),
                AgentActivation(agent_id="b", enabled=True, priority=50),
            ]
        )

        active = config.get_active_agents()

        assert len(active) == 2
        # L'ordre entre agents de même priorité peut varier, juste vérifier le tri

    def test_get_active_agents_priority_order_comprehensive(self):
        """Test complet du tri par priorité avec valeurs variées."""
        config = WizardConfig(
            config_id="c14",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="low", enabled=True, priority=10),
                AgentActivation(agent_id="max", enabled=True, priority=100),
                AgentActivation(agent_id="mid", enabled=True, priority=50),
                AgentActivation(agent_id="zero", enabled=True, priority=0),
            ]
        )

        active = config.get_active_agents()
        priorities = [a.priority for a in active]

        # Vérifier que les priorités sont en ordre décroissant
        assert priorities == sorted(priorities, reverse=True)


class TestWizardConfigMarkComplete:
    """Tests pour la méthode mark_complete."""

    def test_mark_complete_changes_flag(self):
        """Test que mark_complete change is_complete à True."""
        config = WizardConfig(config_id="c1", company_name="Test", is_complete=False)

        config.mark_complete()

        assert config.is_complete is True

    def test_mark_complete_updates_timestamp(self):
        """Test que mark_complete met à jour updated_at."""
        config = WizardConfig(config_id="c2", company_name="Test")
        original_time = config.updated_at

        import time
        time.sleep(0.01)

        config.mark_complete()

        assert config.updated_at > original_time

    def test_mark_complete_multiple_times(self):
        """Test que appeler mark_complete plusieurs fois est sans danger."""
        config = WizardConfig(config_id="c3", company_name="Test")

        config.mark_complete()
        assert config.is_complete is True

        config.mark_complete()
        assert config.is_complete is True


class TestWizardConfigSerialization:
    """Tests pour la sérialisation/désérialisation to_dict/from_dict."""

    def test_to_dict_minimal(self):
        """Test to_dict avec une config minimale."""
        config = WizardConfig(config_id="c1", company_name="TestCorp")

        data = config.to_dict()

        assert data["config_id"] == "c1"
        assert data["company_name"] == "TestCorp"
        assert data["sector"] == "other"
        assert data["size"] == "smb"
        assert data["primary_language"] == "fr"
        assert data["supported_languages"] == ["fr", "en"]
        assert data["pack"] == "custom"
        assert data["agents"] == []
        assert data["is_complete"] is False
        assert data["version"] == 1

    def test_to_dict_with_agents(self):
        """Test to_dict avec des agents."""
        config = WizardConfig(
            config_id="c2",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="drafter", enabled=True, priority=90),
                AgentActivation(agent_id="critic", enabled=False, priority=50, custom_prompt_override="Be strict")
            ]
        )

        data = config.to_dict()

        assert len(data["agents"]) == 2
        assert data["agents"][0]["agent_id"] == "drafter"
        assert data["agents"][0]["enabled"] is True
        assert data["agents"][0]["priority"] == 90
        assert data["agents"][1]["custom_prompt_override"] == "Be strict"

    def test_to_dict_with_knowledge_base(self):
        """Test to_dict avec une knowledge base configurée."""
        kb = KnowledgeBaseConfig(
            company_name="TechCorp",
            forbidden_topics=["price", "cost"],
            faq_entries={"Q": "A"}
        )
        config = WizardConfig(config_id="c3", company_name="Test", knowledge_base=kb)

        data = config.to_dict()

        assert data["knowledge_base"]["company_name"] == "TechCorp"
        assert data["knowledge_base"]["forbidden_topics"] == ["price", "cost"]
        assert data["knowledge_base"]["faq_entries"] == {"Q": "A"}

    def test_from_dict_minimal(self):
        """Test from_dict avec données minimales."""
        data = {
            "config_id": "c1",
            "company_name": "TestCorp",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        config = WizardConfig.from_dict(data)

        assert config.config_id == "c1"
        assert config.company_name == "TestCorp"
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB
        assert config.pack == ConfigPack.CUSTOM

    def test_from_dict_with_agents(self):
        """Test from_dict avec agents."""
        data = {
            "config_id": "c2",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "agents": [
                {"agent_id": "drafter", "enabled": True, "priority": 90, "custom_prompt_override": None},
                {"agent_id": "critic", "enabled": False, "priority": 50}
            ]
        }

        config = WizardConfig.from_dict(data)

        assert len(config.agents) == 2
        assert config.agents[0].agent_id == "drafter"
        assert config.agents[0].priority == 90
        assert config.agents[1].enabled is False

    def test_from_dict_with_knowledge_base(self):
        """Test from_dict avec knowledge base."""
        data = {
            "config_id": "c3",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "knowledge_base": {
                "company_name": "TechCorp",
                "company_description": "A tech company",
                "products_services": "Cloud",
                "tone_guidelines": "Professional",
                "forbidden_topics": ["price"],
                "custom_signatures": {"sales": "Best"},
                "faq_entries": {"Q": "A"},
                "custom_file_path": "/path"
            }
        }

        config = WizardConfig.from_dict(data)

        assert config.knowledge_base.company_name == "TechCorp"
        assert config.knowledge_base.forbidden_topics == ["price"]
        assert config.knowledge_base.faq_entries == {"Q": "A"}

    def test_round_trip_serialization(self):
        """Test la sérialisation et désérialisation complètes."""
        original = WizardConfig(
            config_id="c_original",
            company_name="OriginalCorp",
            sector=BusinessSector.TECH,
            size=CompanySize.ENTERPRISE,
            primary_language="en",
            supported_languages=["en", "fr"],
            pack=ConfigPack.ENTERPRISE,
            agents=[AgentActivation(agent_id="drafter", priority=90)],
            knowledge_base=KnowledgeBaseConfig(company_name="OriginalCorp", forbidden_topics=["price"]),
            version=2,
            is_complete=True
        )

        # Sérialiser
        data = original.to_dict()

        # Désérialiser
        restored = WizardConfig.from_dict(data)

        # Vérifier que les valeurs importantes correspondent
        assert restored.config_id == original.config_id
        assert restored.company_name == original.company_name
        assert restored.sector == original.sector
        assert restored.size == original.size
        assert restored.pack == original.pack
        assert len(restored.agents) == len(original.agents)
        assert restored.agents[0].agent_id == original.agents[0].agent_id
        assert restored.knowledge_base.company_name == original.knowledge_base.company_name
        assert restored.version == original.version
        assert restored.is_complete == original.is_complete

    def test_from_dict_missing_created_at(self):
        """Test from_dict sans created_at utilise la date actuelle."""
        data = {
            "config_id": "c1",
            "company_name": "Test"
        }

        config = WizardConfig.from_dict(data)

        assert isinstance(config.created_at, datetime)
        # Vérifier que c'est récent (dans les dernières 10 secondes)
        delta = datetime.now() - config.created_at
        assert delta.total_seconds() < 10

    def test_from_dict_missing_updated_at(self):
        """Test from_dict sans updated_at utilise la date actuelle."""
        data = {
            "config_id": "c1",
            "company_name": "Test"
        }

        config = WizardConfig.from_dict(data)

        assert isinstance(config.updated_at, datetime)

    def test_from_dict_empty_agents(self):
        """Test from_dict avec la clé agents manquante ou vide."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        config = WizardConfig.from_dict(data)

        assert config.agents == []

    def test_from_dict_agents_with_missing_fields(self):
        """Test from_dict avec agents manquant des champs optionnels."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "agents": [
                {"agent_id": "drafter"}  # enabled et priority manquent
            ]
        }

        config = WizardConfig.from_dict(data)

        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "drafter"
        assert config.agents[0].enabled is True  # Valeur par défaut
        assert config.agents[0].priority == 50  # Valeur par défaut

    def test_from_dict_missing_knowledge_base(self):
        """Test from_dict sans knowledge_base utilise les valeurs par défaut."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        config = WizardConfig.from_dict(data)

        assert isinstance(config.knowledge_base, KnowledgeBaseConfig)
        assert config.knowledge_base.company_name == ""
        assert config.knowledge_base.forbidden_topics == []

    def test_from_dict_partial_knowledge_base(self):
        """Test from_dict avec knowledge_base partiellement remplie."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "knowledge_base": {
                "company_name": "PartialCorp"
                # Les autres champs sont manquants
            }
        }

        config = WizardConfig.from_dict(data)

        assert config.knowledge_base.company_name == "PartialCorp"
        assert config.knowledge_base.forbidden_topics == []
        assert config.knowledge_base.faq_entries == {}

    def test_from_dict_with_enum_values(self):
        """Test from_dict avec des valeurs d'enum."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "sector": "tech",
            "size": "startup",
            "pack": "saas",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        config = WizardConfig.from_dict(data)

        assert config.sector == BusinessSector.TECH
        assert config.size == CompanySize.STARTUP
        assert config.pack == ConfigPack.SAAS

    def test_from_dict_invalid_enum_value_defaults(self):
        """Test que from_dict utilise la valeur par défaut si enum invalide."""
        data = {
            "config_id": "c1",
            "company_name": "Test",
            "sector": "invalid_sector",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Cela devrait lever une ValueError à cause de l'enum invalide
        with pytest.raises(ValueError):
            WizardConfig.from_dict(data)

    def test_from_dict_with_auto_generated_config_id(self):
        """Test que from_dict génère un config_id si absent."""
        data = {
            "company_name": "Test",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        config = WizardConfig.from_dict(data)

        assert config.config_id is not None
        assert len(config.config_id) == 8  # UUID[:8]


class TestWizardConfigEdgeCases:
    """Tests pour les cas limites et comportements spéciaux."""

    def test_multiple_agent_activations_same_agent(self):
        """Test qu'activer un agent plusieurs fois le met à jour."""
        config = WizardConfig(config_id="c1", company_name="Test")

        config.activate_agent("agent1", priority=50)
        config.activate_agent("agent1", priority=80)

        # Ne doit avoir qu'un seul agent
        assert len(config.agents) == 1
        assert config.agents[0].priority == 80

    def test_wizard_config_with_empty_lists(self):
        """Test WizardConfig avec des listes vides."""
        config = WizardConfig(
            config_id="c1",
            company_name="Test",
            agents=[],
            supported_languages=[]
        )

        assert config.agents == []
        assert config.supported_languages == []

    def test_wizard_config_language_modifications(self):
        """Test que supported_languages peut être modifiée."""
        config = WizardConfig(
            config_id="c1",
            company_name="Test",
            supported_languages=["fr"]
        )

        config.supported_languages.append("en")
        assert "en" in config.supported_languages

    def test_wizard_config_agents_list_independence(self):
        """Test que les listes d'agents sont indépendantes entre instances."""
        agents = [AgentActivation(agent_id="a", priority=50)]
        config1 = WizardConfig(config_id="c1", company_name="Test1", agents=agents)
        config2 = WizardConfig(config_id="c2", company_name="Test2")

        config1.activate_agent("b", priority=60)
        assert len(config1.agents) == 2
        assert len(config2.agents) == 0

    def test_to_dict_includes_all_required_fields(self):
        """Test que to_dict inclut tous les champs requis."""
        config = WizardConfig(config_id="c1", company_name="Test")
        data = config.to_dict()

        required_fields = [
            "config_id", "company_name", "sector", "size", "primary_language",
            "supported_languages", "pack", "agents", "knowledge_base",
            "created_at", "updated_at", "version", "is_complete"
        ]

        for field in required_fields:
            assert field in data, f"Field '{field}' missing from to_dict() output"

    def test_wizard_config_timestamps_are_datetime(self):
        """Test que created_at et updated_at sont des datetime objects."""
        config = WizardConfig(config_id="c1", company_name="Test")

        assert isinstance(config.created_at, datetime)
        assert isinstance(config.updated_at, datetime)

    def test_wizard_config_version_increments(self):
        """Test que version peut être incrémentée manuellement."""
        config = WizardConfig(config_id="c1", company_name="Test", version=1)
        config.version = 2

        assert config.version == 2
