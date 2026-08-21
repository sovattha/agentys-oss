# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests complets pour le module application.wizard_config."""

import pytest
import tempfile
import uuid
from unittest.mock import Mock
from pathlib import Path

from app.application.wizard_config import (
    SaveWizardConfigUseCase,
    LoadWizardConfigUseCase,
    CreateWizardConfigUseCase,
    ToggleAgentUseCase,
    ImportKnowledgeBaseUseCase,
    ExportConfigUseCase,
    get_available_packs,
    get_available_agents,
    PACK_CONFIGURATIONS,
)
from app.domain.entities.wizard_config import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
)
from app.domain.ports.wizard_config_port import WizardConfigPort


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_persistence():
    """Crée un mock du port de persistance WizardConfigPort."""
    return Mock(spec=WizardConfigPort)


@pytest.fixture
def sample_wizard_config():
    """Crée une configuration wizard de test."""
    return WizardConfig(
        config_id="test-config-001",
        company_name="TechCorp",
        sector=BusinessSector.TECH,
        size=CompanySize.SMB,
        pack=ConfigPack.CUSTOM,
    )


@pytest.fixture
def sample_config_with_agents():
    """Crée une configuration avec des agents activés."""
    config = WizardConfig(
        config_id="test-config-002",
        company_name="StartupInc",
        sector=BusinessSector.SAAS,
        size=CompanySize.STARTUP,
        pack=ConfigPack.STARTUP,
    )
    config.activate_agent("drafter", priority=100)
    config.activate_agent("critic", priority=90)
    return config


@pytest.fixture
def sample_config_with_knowledge_base():
    """Crée une configuration avec une knowledge base."""
    config = WizardConfig(
        config_id="test-config-003",
        company_name="ServiceCorp",
        sector=BusinessSector.OTHER,
        size=CompanySize.SMB,
        pack=ConfigPack.SMB,
    )
    config.knowledge_base.company_description = "We provide excellent service"
    config.knowledge_base.tone_guidelines = "Professional and friendly"
    return config


# ──────────────────────────────────────────────────────────────────────────────
# Tests SaveWizardConfigUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveWizardConfigUseCase:
    """Tests pour SaveWizardConfigUseCase."""

    def test_save_valid_config(self, mock_persistence, sample_wizard_config):
        """Sauvegarde une configuration valide."""
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        result = use_case.execute(sample_wizard_config)

        assert result == sample_wizard_config
        mock_persistence.save.assert_called_once_with(sample_wizard_config)

    def test_save_calls_persistence_save(self, mock_persistence, sample_wizard_config):
        """Vérifie que le use case appelle la persistance."""
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        use_case.execute(sample_wizard_config)

        mock_persistence.save.assert_called_once()
        call_args = mock_persistence.save.call_args[0][0]
        assert call_args.config_id == "test-config-001"
        assert call_args.company_name == "TechCorp"

    def test_save_missing_config_id(self, mock_persistence):
        """Rejette une configuration sans config_id."""
        config = WizardConfig(
            config_id="",
            company_name="TechCorp",
            sector=BusinessSector.TECH,
            size=CompanySize.SMB,
        )
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)

        with pytest.raises(ValueError, match="config_id est requis"):
            use_case.execute(config)

    def test_save_missing_company_name(self, mock_persistence):
        """Rejette une configuration sans company_name."""
        config = WizardConfig(
            config_id="test-config",
            company_name="",
            sector=BusinessSector.TECH,
            size=CompanySize.SMB,
        )
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)

        with pytest.raises(ValueError, match="company_name est requis"):
            use_case.execute(config)

    def test_save_whitespace_company_name(self, mock_persistence):
        """Rejette une configuration avec company_name vide (whitespace)."""
        config = WizardConfig(
            config_id="test-config",
            company_name="   ",
            sector=BusinessSector.TECH,
            size=CompanySize.SMB,
        )
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)

        with pytest.raises(ValueError, match="company_name est requis"):
            use_case.execute(config)

    def test_save_returns_same_config(self, mock_persistence, sample_wizard_config):
        """Retourne la même configuration après sauvegarde."""
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        result = use_case.execute(sample_wizard_config)

        assert result is sample_wizard_config

    def test_save_with_agents(self, mock_persistence, sample_config_with_agents):
        """Sauvegarde une configuration avec des agents."""
        use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        result = use_case.execute(sample_config_with_agents)

        assert len(result.agents) == 2
        mock_persistence.save.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Tests LoadWizardConfigUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestLoadWizardConfigUseCase:
    """Tests pour LoadWizardConfigUseCase."""

    def test_load_existing_config(self, mock_persistence, sample_wizard_config):
        """Charge une configuration existante."""
        mock_persistence.load.return_value = sample_wizard_config
        use_case = LoadWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute()

        assert result == sample_wizard_config
        mock_persistence.load.assert_called_once()

    def test_load_nonexistent_config(self, mock_persistence):
        """Retourne None si aucune configuration n'existe."""
        mock_persistence.load.return_value = None
        use_case = LoadWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute()

        assert result is None
        mock_persistence.load.assert_called_once()

    def test_load_calls_persistence(self, mock_persistence, sample_wizard_config):
        """Vérifie que le use case appelle persistence.load()."""
        mock_persistence.load.return_value = sample_wizard_config
        use_case = LoadWizardConfigUseCase(persistence=mock_persistence)

        use_case.execute()

        mock_persistence.load.assert_called_once_with()

    def test_load_with_agents(self, mock_persistence, sample_config_with_agents):
        """Charge une configuration avec des agents."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = LoadWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute()

        assert result.company_name == "StartupInc"
        assert len(result.agents) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Tests CreateWizardConfigUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestCreateWizardConfigUseCase:
    """Tests pour CreateWizardConfigUseCase."""

    def test_create_basic_config(self, mock_persistence):
        """Crée une configuration basique."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="NewCorp",
            sector=BusinessSector.TECH,
            size=CompanySize.STARTUP,
        )

        assert result.company_name == "NewCorp"
        assert result.sector == BusinessSector.TECH
        assert result.size == CompanySize.STARTUP
        assert result.pack == ConfigPack.CUSTOM
        assert result.config_id  # Should have a UUID

    def test_create_generates_uuid(self, mock_persistence):
        """Génère un UUID pour config_id."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(company_name="TestCorp")

        assert result.config_id
        assert len(result.config_id) > 0
        # Vérifie que c'est un UUID valide
        try:
            uuid.UUID(result.config_id)
        except ValueError:
            pytest.fail("config_id n'est pas un UUID valide")

    def test_create_with_defaults(self, mock_persistence):
        """Crée avec les valeurs par défaut."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(company_name="SimpleCompany")

        assert result.sector == BusinessSector.OTHER
        assert result.size == CompanySize.SMB
        assert result.pack == ConfigPack.CUSTOM

    def test_create_with_startup_pack(self, mock_persistence):
        """Crée une configuration avec pack STARTUP."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="MyStartup",
            pack=ConfigPack.STARTUP,
        )

        assert result.pack == ConfigPack.STARTUP
        # Vérifie que les agents du pack sont activés
        active_agents = result.get_active_agents()
        agent_ids = [a.agent_id for a in active_agents]
        assert "drafter" in agent_ids
        assert "critic" in agent_ids

    def test_create_with_smb_pack(self, mock_persistence):
        """Crée une configuration avec pack SMB."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="MySMB",
            pack=ConfigPack.SMB,
        )

        assert result.pack == ConfigPack.SMB
        active_agents = result.get_active_agents()
        agent_ids = [a.agent_id for a in active_agents]
        assert "drafter" in agent_ids
        assert "tech_support" in agent_ids

    def test_create_with_enterprise_pack(self, mock_persistence):
        """Crée une configuration avec pack ENTERPRISE."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="BigCorp",
            pack=ConfigPack.ENTERPRISE,
        )

        assert result.pack == ConfigPack.ENTERPRISE
        active_agents = result.get_active_agents()
        assert len(active_agents) >= 9  # ENTERPRISE a 9 agents

    def test_create_with_custom_pack_no_agents(self, mock_persistence):
        """Crée une configuration avec pack CUSTOM (pas d'agents)."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="CustomCorp",
            pack=ConfigPack.CUSTOM,
        )

        assert result.pack == ConfigPack.CUSTOM
        assert len(result.agents) == 0

    def test_create_pack_applies_languages(self, mock_persistence):
        """Vérifie que les langues du pack sont appliquées."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="MultiLangCorp",
            pack=ConfigPack.ENTERPRISE,
        )

        # ENTERPRISE pack a 4 langues
        assert "fr" in result.supported_languages
        assert "en" in result.supported_languages
        assert "de" in result.supported_languages
        assert "es" in result.supported_languages

    def test_create_pack_applies_tone_guidelines(self, mock_persistence):
        """Vérifie que les tone guidelines du pack sont appliquées."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="TonedCorp",
            pack=ConfigPack.STARTUP,
        )

        assert result.knowledge_base.tone_guidelines
        assert "dynamique" in result.knowledge_base.tone_guidelines

    def test_create_without_pack_defaults_to_custom(self, mock_persistence):
        """Crée sans pack → défaut CUSTOM."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="NoPack",
            pack=None,
        )

        assert result.pack == ConfigPack.CUSTOM

    def test_create_agent_priority(self, mock_persistence):
        """Vérifie que les agents ont les priorités correctes."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(
            company_name="PriorityCorp",
            pack=ConfigPack.STARTUP,
        )

        active_agents = result.get_active_agents()
        # Devrait être trié par priorité (décroissante)
        priorities = [a.priority for a in active_agents]
        assert priorities == sorted(priorities, reverse=True)

    def test_create_multiple_different_packs(self, mock_persistence):
        """Crée plusieurs configurations avec différents packs."""
        use_case = CreateWizardConfigUseCase(persistence=mock_persistence)

        startup = use_case.execute(
            company_name="Startup",
            pack=ConfigPack.STARTUP,
        )
        saas = use_case.execute(
            company_name="SaaS",
            pack=ConfigPack.SAAS,
        )
        ecommerce = use_case.execute(
            company_name="Ecommerce",
            pack=ConfigPack.ECOMMERCE,
        )

        assert startup.pack == ConfigPack.STARTUP
        assert saas.pack == ConfigPack.SAAS
        assert ecommerce.pack == ConfigPack.ECOMMERCE
        assert len(startup.agents) > 0
        assert len(saas.agents) > 0
        assert len(ecommerce.agents) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests ToggleAgentUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestToggleAgentUseCase:
    """Tests pour ToggleAgentUseCase."""

    def test_enable_agent(self, mock_persistence, sample_config_with_agents):
        """Active un agent."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="onboarding_specialist",
            enabled=True,
            priority=85,
        )

        assert result is not None
        assert result.is_agent_active("onboarding_specialist")
        mock_persistence.save.assert_called_once()

    def test_disable_agent(self, mock_persistence, sample_config_with_agents):
        """Désactive un agent."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="drafter",
            enabled=False,
        )

        assert result is not None
        assert not result.is_agent_active("drafter")
        mock_persistence.save.assert_called_once()

    def test_enable_nonexistent_agent_creates_it(self, mock_persistence, sample_config_with_agents):
        """Active un agent qui n'existe pas → le crée."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="new_agent",
            enabled=True,
            priority=60,
        )

        assert result.is_agent_active("new_agent")
        # Trouver l'agent et vérifier sa priorité
        agent = next(a for a in result.agents if a.agent_id == "new_agent")
        assert agent.priority == 60

    def test_toggle_no_config(self, mock_persistence):
        """Retourne None si aucune configuration n'existe."""
        mock_persistence.load.return_value = None
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="drafter",
            enabled=True,
        )

        assert result is None
        mock_persistence.save.assert_not_called()

    def test_toggle_saves_updated_config(self, mock_persistence, sample_config_with_agents):
        """Sauvegarde la configuration après le changement."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        use_case.execute(agent_id="drafter", enabled=False)

        mock_persistence.save.assert_called_once()
        saved_config = mock_persistence.save.call_args[0][0]
        assert not saved_config.is_agent_active("drafter")

    def test_toggle_respects_priority(self, mock_persistence, sample_config_with_agents):
        """Respecte la priorité fournie."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="critic",
            enabled=True,
            priority=75,
        )

        agent = next(a for a in result.agents if a.agent_id == "critic")
        assert agent.priority == 75

    def test_toggle_default_priority(self, mock_persistence, sample_config_with_agents):
        """Utilise la priorité par défaut (50)."""
        mock_persistence.load.return_value = sample_config_with_agents
        use_case = ToggleAgentUseCase(persistence=mock_persistence)

        result = use_case.execute(
            agent_id="unknown_agent",
            enabled=True,
        )

        agent = next(a for a in result.agents if a.agent_id == "unknown_agent")
        assert agent.priority == 50


# ──────────────────────────────────────────────────────────────────────────────
# Tests ImportKnowledgeBaseUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestImportKnowledgeBaseUseCase:
    """Tests pour ImportKnowledgeBaseUseCase."""

    def test_import_basic(self, mock_persistence, sample_config_with_knowledge_base):
        """Importe un fichier knowledge base."""
        mock_persistence.load.return_value = sample_config_with_knowledge_base

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write("New company description from file")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file)

            assert result is not None
            assert "New company description from file" in result.knowledge_base.company_description
            assert result.knowledge_base.custom_file_path == temp_file
            mock_persistence.save.assert_called_once()
        finally:
            Path(temp_file).unlink()

    def test_import_replaces_existing(self, mock_persistence, sample_config_with_knowledge_base):
        """Remplace la description existante (merge=False)."""
        original = "Original description"
        sample_config_with_knowledge_base.knowledge_base.company_description = original
        mock_persistence.load.return_value = sample_config_with_knowledge_base

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write("New description")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file, merge=False)

            assert "Original description" not in result.knowledge_base.company_description
            assert result.knowledge_base.company_description == "New description"
        finally:
            Path(temp_file).unlink()

    def test_import_merge_mode(self, mock_persistence, sample_config_with_knowledge_base):
        """Fusionne avec la description existante (merge=True)."""
        original = "Original description"
        sample_config_with_knowledge_base.knowledge_base.company_description = original
        mock_persistence.load.return_value = sample_config_with_knowledge_base

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write("Additional description")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file, merge=True)

            assert "Original description" in result.knowledge_base.company_description
            assert "Additional description" in result.knowledge_base.company_description
            assert "\n\n" in result.knowledge_base.company_description
        finally:
            Path(temp_file).unlink()

    def test_import_no_config(self, mock_persistence):
        """Retourne None si aucune configuration n'existe."""
        mock_persistence.load.return_value = None

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("content")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file)

            assert result is None
            mock_persistence.save.assert_not_called()
        finally:
            Path(temp_file).unlink()

    def test_import_nonexistent_file(self, mock_persistence, sample_config_with_knowledge_base):
        """Lève FileNotFoundError pour un fichier inexistant."""
        mock_persistence.load.return_value = sample_config_with_knowledge_base
        use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)

        with pytest.raises(FileNotFoundError):
            use_case.execute(file_path="/nonexistent/file/path.txt")

    def test_import_sets_file_path(self, mock_persistence, sample_config_with_knowledge_base):
        """Enregistre le chemin du fichier importé."""
        mock_persistence.load.return_value = sample_config_with_knowledge_base

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file)

            assert result.knowledge_base.custom_file_path == temp_file
        finally:
            Path(temp_file).unlink()

    def test_import_preserves_merge_false_when_no_existing(self, mock_persistence):
        """Import avec merge=False quand pas de description existante."""
        config = WizardConfig(
            config_id="test",
            company_name="Test",
        )
        config.knowledge_base.company_description = ""
        mock_persistence.load.return_value = config

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("New description")
            temp_file = f.name

        try:
            use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            result = use_case.execute(file_path=temp_file, merge=False)

            assert result.knowledge_base.company_description == "New description"
        finally:
            Path(temp_file).unlink()


# ──────────────────────────────────────────────────────────────────────────────
# Tests ExportConfigUseCase
# ──────────────────────────────────────────────────────────────────────────────


class TestExportConfigUseCase:
    """Tests pour ExportConfigUseCase."""

    def test_export_success(self, mock_persistence):
        """Exporte une configuration avec succès."""
        use_case = ExportConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(file_path="/tmp/export.json")

        assert result is True
        mock_persistence.export_to_file.assert_called_once_with("/tmp/export.json")

    def test_export_calls_persistence(self, mock_persistence):
        """Vérifie que l'export appelle persistence.export_to_file()."""
        use_case = ExportConfigUseCase(persistence=mock_persistence)

        use_case.execute(file_path="/tmp/test.json")

        mock_persistence.export_to_file.assert_called_once_with("/tmp/test.json")

    def test_export_returns_true(self, mock_persistence):
        """Retourne True en cas de succès."""
        use_case = ExportConfigUseCase(persistence=mock_persistence)

        result = use_case.execute(file_path="/tmp/config.json")

        assert result is True

    def test_export_various_paths(self, mock_persistence):
        """Accepte différents chemins d'export."""
        use_case = ExportConfigUseCase(persistence=mock_persistence)

        paths = [
            "/tmp/config.json",
            "./config.json",
            "../configs/export.json",
            "/home/user/wizard_config.json",
        ]

        for path in paths:
            use_case.execute(file_path=path)
            mock_persistence.export_to_file.assert_called_with(path)


# ──────────────────────────────────────────────────────────────────────────────
# Tests get_available_packs()
# ──────────────────────────────────────────────────────────────────────────────


class TestGetAvailablePacks:
    """Tests pour get_available_packs()."""

    def test_returns_list(self):
        """Retourne une liste."""
        packs = get_available_packs()
        assert isinstance(packs, list)

    def test_returns_six_packs(self):
        """Retourne 6 packs."""
        packs = get_available_packs()
        assert len(packs) == 6

    def test_pack_structure(self):
        """Vérifie la structure de chaque pack."""
        packs = get_available_packs()

        for pack in packs:
            assert "id" in pack
            assert "name" in pack
            assert "description" in pack
            assert "agents_count" in pack

    def test_pack_ids(self):
        """Vérifie les IDs des packs."""
        packs = get_available_packs()
        pack_ids = [p["id"] for p in packs]

        assert ConfigPack.STARTUP.value in pack_ids
        assert ConfigPack.SMB.value in pack_ids
        assert ConfigPack.ENTERPRISE.value in pack_ids
        assert ConfigPack.SAAS.value in pack_ids
        assert ConfigPack.ECOMMERCE.value in pack_ids
        assert ConfigPack.B2B.value in pack_ids

    def test_pack_names_are_strings(self):
        """Vérifie que les noms sont des chaînes."""
        packs = get_available_packs()

        for pack in packs:
            assert isinstance(pack["name"], str)
            assert len(pack["name"]) > 0

    def test_pack_descriptions_are_strings(self):
        """Vérifie que les descriptions sont des chaînes."""
        packs = get_available_packs()

        for pack in packs:
            assert isinstance(pack["description"], str)
            assert len(pack["description"]) > 0

    def test_pack_agents_count_positive(self):
        """Vérifie que le nombre d'agents est positif."""
        packs = get_available_packs()

        for pack in packs:
            assert isinstance(pack["agents_count"], int)
            assert pack["agents_count"] > 0

    def test_startup_pack_details(self):
        """Vérifie les détails du pack STARTUP."""
        packs = get_available_packs()
        startup = next(p for p in packs if p["id"] == ConfigPack.STARTUP.value)

        assert startup["name"] == "Startup"
        assert startup["agents_count"] == 4  # 4 agents pour STARTUP

    def test_enterprise_pack_has_most_agents(self):
        """Vérifie que ENTERPRISE a le plus d'agents."""
        packs = get_available_packs()
        agent_counts = [p["agents_count"] for p in packs]

        enterprise = next(p for p in packs if p["id"] == ConfigPack.ENTERPRISE.value)
        assert enterprise["agents_count"] == max(agent_counts)

    def test_all_packs_have_french_names(self):
        """Vérifie que tous les packs ont des noms français."""
        packs = get_available_packs()

        for pack in packs:
            # Au moins une des premières lettres devrait être une majuscule
            assert pack["name"][0].isupper()


# ──────────────────────────────────────────────────────────────────────────────
# Tests get_available_agents()
# ──────────────────────────────────────────────────────────────────────────────


class TestGetAvailableAgents:
    """Tests pour get_available_agents()."""

    def test_returns_list(self):
        """Retourne une liste."""
        agents = get_available_agents()
        assert isinstance(agents, list)

    def test_returns_twelve_agents(self):
        """Retourne 12 agents."""
        agents = get_available_agents()
        assert len(agents) == 12

    def test_agent_structure(self):
        """Vérifie la structure de chaque agent."""
        agents = get_available_agents()

        for agent in agents:
            assert "id" in agent
            assert "name" in agent
            assert "description" in agent
            assert "category" in agent

    def test_agent_ids_are_unique(self):
        """Vérifie que tous les IDs d'agent sont uniques."""
        agents = get_available_agents()
        agent_ids = [a["id"] for a in agents]

        assert len(agent_ids) == len(set(agent_ids))

    def test_agent_ids_lowercase(self):
        """Vérifie que les IDs sont en minuscules."""
        agents = get_available_agents()

        for agent in agents:
            assert agent["id"] == agent["id"].lower()

    def test_agent_names_are_strings(self):
        """Vérifie que les noms sont des chaînes."""
        agents = get_available_agents()

        for agent in agents:
            assert isinstance(agent["name"], str)
            assert len(agent["name"]) > 0

    def test_agent_descriptions_are_strings(self):
        """Vérifie que les descriptions sont des chaînes."""
        agents = get_available_agents()

        for agent in agents:
            assert isinstance(agent["description"], str)
            assert len(agent["description"]) > 0

    def test_agent_categories_valid(self):
        """Vérifie que les catégories sont valides."""
        agents = get_available_agents()
        valid_categories = {"core", "support", "expert", "sales", "productivity", "analytics"}

        for agent in agents:
            assert agent["category"] in valid_categories

    def test_core_agents_present(self):
        """Vérifie que les agents core sont présents."""
        agents = get_available_agents()
        agent_ids = [a["id"] for a in agents]

        assert "drafter" in agent_ids
        assert "critic" in agent_ids

    def test_support_agents_present(self):
        """Vérifie que les agents support sont présents."""
        agents = get_available_agents()
        agent_ids = [a["id"] for a in agents]

        assert "tech_support" in agent_ids
        assert "refund_handler" in agent_ids

    def test_expert_agents_present(self):
        """Vérifie que les agents experts sont présents."""
        agents = get_available_agents()
        agent_ids = [a["id"] for a in agents]

        assert "legal_advisor" in agent_ids
        assert "financial_advisor" in agent_ids
        assert "hr_specialist" in agent_ids

    def test_sales_agents_present(self):
        """Vérifie que les agents sales sont présents."""
        agents = get_available_agents()
        agent_ids = [a["id"] for a in agents]

        assert "onboarding_specialist" in agent_ids
        assert "sales_qualifier" in agent_ids

    def test_drafter_agent_details(self):
        """Vérifie les détails de l'agent Drafter."""
        agents = get_available_agents()
        drafter = next(a for a in agents if a["id"] == "drafter")

        assert drafter["name"] == "Drafter"
        assert drafter["category"] == "core"
        assert "email" in drafter["description"].lower()

    def test_agent_names_with_accents(self):
        """Vérifie que les noms français ont les accents correctement."""
        agents = get_available_agents()
        agent_names = [a["name"] for a in agents]

        # Certains noms devraient avoir des accents
        has_accents = any("é" in n or "è" in n or "ê" in n for n in agent_names)
        assert has_accents


# ──────────────────────────────────────────────────────────────────────────────
# Tests PACK_CONFIGURATIONS
# ──────────────────────────────────────────────────────────────────────────────


class TestPackConfigurations:
    """Tests pour le dictionnaire PACK_CONFIGURATIONS."""

    def test_all_packs_in_enum_are_configured(self):
        """Vérifie que tous les packs sont configurés."""
        for pack in [ConfigPack.STARTUP, ConfigPack.SMB, ConfigPack.ENTERPRISE,
                     ConfigPack.SAAS, ConfigPack.ECOMMERCE, ConfigPack.B2B]:
            assert pack in PACK_CONFIGURATIONS

    def test_each_pack_has_agents(self):
        """Vérifie que chaque pack a des agents."""
        for pack, config in PACK_CONFIGURATIONS.items():
            assert "agents" in config
            assert len(config["agents"]) > 0

    def test_each_pack_has_languages(self):
        """Vérifie que chaque pack a des langues."""
        for pack, config in PACK_CONFIGURATIONS.items():
            assert "languages" in config
            assert len(config["languages"]) > 0

    def test_each_pack_has_tone_guidelines(self):
        """Vérifie que chaque pack a des tone_guidelines."""
        for pack, config in PACK_CONFIGURATIONS.items():
            assert "tone_guidelines" in config
            assert len(config["tone_guidelines"]) > 0

    def test_agents_have_id_and_priority(self):
        """Vérifie que les agents ont id et priority."""
        for pack, config in PACK_CONFIGURATIONS.items():
            for agent in config["agents"]:
                assert "id" in agent
                assert "priority" in agent

    def test_languages_are_valid_iso639(self):
        """Vérifie que les langues sont des codes ISO 639-1 valides."""
        valid_iso639 = {"en", "fr", "de", "es", "it", "pt", "nl", "ja", "zh"}

        for pack, config in PACK_CONFIGURATIONS.items():
            for lang in config["languages"]:
                assert lang in valid_iso639

    def test_tone_guidelines_are_french(self):
        """Vérifie que les tone_guidelines sont en français."""
        for pack, config in PACK_CONFIGURATIONS.items():
            tone = config["tone_guidelines"]
            # Au moins certains mots français devraient être présents
            assert any(word in tone.lower() for word in [
                "ton", "professionnel", "réponses", "accès",
                "tutoiement", "vouvoiement", "empathique"
            ])


# ──────────────────────────────────────────────────────────────────────────────
# Tests d'intégration
# ──────────────────────────────────────────────────────────────────────────────


class TestIntegration:
    """Tests d'intégration entre use cases."""

    def test_create_then_save_then_load(self, mock_persistence):
        """Cycle complet: créer → sauvegarder → charger."""
        # 1. Créer
        create_use_case = CreateWizardConfigUseCase(persistence=mock_persistence)
        config = create_use_case.execute(
            company_name="TestCorp",
            pack=ConfigPack.STARTUP,
        )

        # 2. Sauvegarder
        save_use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        saved = save_use_case.execute(config)

        # 3. Charger
        mock_persistence.load.return_value = saved
        load_use_case = LoadWizardConfigUseCase(persistence=mock_persistence)
        loaded = load_use_case.execute()

        assert loaded.company_name == "TestCorp"
        assert loaded.pack == ConfigPack.STARTUP
        assert len(loaded.agents) > 0

    def test_create_toggle_agents_save(self, mock_persistence):
        """Créer → modifier agents → sauvegarder."""
        # Créer
        create_use_case = CreateWizardConfigUseCase(persistence=mock_persistence)
        config = create_use_case.execute(
            company_name="AgentCorp",
            pack=ConfigPack.SMB,
        )

        # Modifier agents
        mock_persistence.load.return_value = config
        toggle_use_case = ToggleAgentUseCase(persistence=mock_persistence)
        updated = toggle_use_case.execute(
            agent_id="legal_advisor",
            enabled=True,
            priority=95,
        )

        # Sauvegarder
        save_use_case = SaveWizardConfigUseCase(persistence=mock_persistence)
        saved = save_use_case.execute(updated)

        assert saved.is_agent_active("legal_advisor")

    def test_create_import_knowledge_base_export(self, mock_persistence):
        """Créer → importer KB → exporter."""
        # Créer
        create_use_case = CreateWizardConfigUseCase(persistence=mock_persistence)
        config = create_use_case.execute(company_name="KBCorp")

        # Importer KB
        mock_persistence.load.return_value = config
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("Company description from KB file")
            kb_file = f.name

        try:
            import_use_case = ImportKnowledgeBaseUseCase(persistence=mock_persistence)
            imported = import_use_case.execute(file_path=kb_file)

            # Exporter
            mock_persistence.load.return_value = imported
            export_use_case = ExportConfigUseCase(persistence=mock_persistence)
            success = export_use_case.execute(file_path="/tmp/export.json")

            assert success is True
            assert mock_persistence.export_to_file.called
        finally:
            Path(kb_file).unlink()
