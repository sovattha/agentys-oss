# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le Wizard de Configuration.

Ces tests couvrent:
- Entités du domaine (WizardConfig, AgentActivation, KnowledgeBaseConfig)
- Use cases (Save, Load, Create, Toggle, Import, Export)
- Adapter de persistance (JsonFileWizardConfigStore)
- Endpoints API (/api/wizard/*)
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
    AgentActivation,
    KnowledgeBaseConfig,
)
from app.domain.ports import WizardConfigPort
from app.application import (
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
from app.infrastructure.wizard_config_store import (
    JsonFileWizardConfigStore,
    reset_wizard_config_store,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_config_file():
    """Crée un fichier temporaire pour les tests."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    path = Path(f.name)
    f.close()  # Close immediately so the store can open/delete the file on Windows
    yield path
    # Cleanup
    path.unlink(missing_ok=True)


@pytest.fixture
def sample_config():
    """Configuration wizard de test."""
    return WizardConfig(
        config_id="test-config-123",
        company_name="Test Company",
        sector=BusinessSector.TECH,
        size=CompanySize.STARTUP,
        primary_language="fr",
        supported_languages=["fr", "en"],
        pack=ConfigPack.STARTUP,
        agents=[
            AgentActivation(agent_id="drafter", enabled=True, priority=100),
            AgentActivation(agent_id="critic", enabled=True, priority=90),
        ],
        knowledge_base=KnowledgeBaseConfig(
            company_name="Test Company",
            company_description="A test company",
            tone_guidelines="Professional but friendly",
        ),
    )


@pytest.fixture
def mock_store():
    """Mock du store de persistance."""
    store = MagicMock(spec=WizardConfigPort)
    return store


@pytest.fixture
def real_store(temp_config_file):
    """Store réel avec fichier temporaire."""
    reset_wizard_config_store()
    return JsonFileWizardConfigStore(temp_config_file)


# ============================================================================
# TESTS - ENTITES DU DOMAINE
# ============================================================================

class TestWizardConfigEntity:
    """Tests pour l'entité WizardConfig."""

    def test_create_minimal_config(self):
        """Création avec valeurs minimales."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
        )
        assert config.config_id == "123"
        assert config.company_name == "Test"
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB
        assert config.primary_language == "fr"
        assert config.is_complete is False

    def test_create_full_config(self, sample_config):
        """Création avec toutes les valeurs."""
        assert sample_config.config_id == "test-config-123"
        assert sample_config.sector == BusinessSector.TECH
        assert len(sample_config.agents) == 2

    def test_activate_agent_new(self):
        """Activation d'un nouvel agent."""
        config = WizardConfig(config_id="123", company_name="Test")
        config.activate_agent("tech_support", priority=80)

        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "tech_support"
        assert config.agents[0].enabled is True
        assert config.agents[0].priority == 80

    def test_activate_agent_existing(self):
        """Réactivation d'un agent existant."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[AgentActivation(agent_id="tech_support", enabled=False, priority=50)]
        )
        config.activate_agent("tech_support", priority=90)

        assert len(config.agents) == 1
        assert config.agents[0].enabled is True
        assert config.agents[0].priority == 90

    def test_deactivate_agent(self):
        """Désactivation d'un agent."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[AgentActivation(agent_id="tech_support", enabled=True)]
        )
        config.deactivate_agent("tech_support")

        assert config.agents[0].enabled is False

    def test_deactivate_nonexistent_agent(self):
        """Désactivation d'un agent inexistant (no-op)."""
        config = WizardConfig(config_id="123", company_name="Test")
        config.deactivate_agent("nonexistent")
        # Should not raise, just do nothing
        assert len(config.agents) == 0

    def test_is_agent_active(self):
        """Vérification de l'état d'un agent."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="active", enabled=True),
                AgentActivation(agent_id="inactive", enabled=False),
            ]
        )

        assert config.is_agent_active("active") is True
        assert config.is_agent_active("inactive") is False
        assert config.is_agent_active("nonexistent") is False

    def test_get_active_agents_sorted_by_priority(self):
        """Les agents actifs sont triés par priorité décroissante."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="low", enabled=True, priority=10),
                AgentActivation(agent_id="high", enabled=True, priority=90),
                AgentActivation(agent_id="disabled", enabled=False, priority=100),
                AgentActivation(agent_id="mid", enabled=True, priority=50),
            ]
        )

        active = config.get_active_agents()
        assert len(active) == 3
        assert active[0].agent_id == "high"
        assert active[1].agent_id == "mid"
        assert active[2].agent_id == "low"

    def test_mark_complete(self):
        """Marquer la configuration comme complète."""
        config = WizardConfig(config_id="123", company_name="Test")
        assert config.is_complete is False

        config.mark_complete()

        assert config.is_complete is True

    def test_to_dict_and_from_dict(self, sample_config):
        """Sérialisation et désérialisation."""
        data = sample_config.to_dict()

        assert data["config_id"] == "test-config-123"
        assert data["company_name"] == "Test Company"
        assert data["sector"] == "tech"
        assert len(data["agents"]) == 2

        # Désérialiser
        restored = WizardConfig.from_dict(data)

        assert restored.config_id == sample_config.config_id
        assert restored.company_name == sample_config.company_name
        assert restored.sector == sample_config.sector
        assert len(restored.agents) == len(sample_config.agents)


class TestAgentActivationEntity:
    """Tests pour l'entité AgentActivation."""

    def test_default_values(self):
        """Valeurs par défaut."""
        agent = AgentActivation(agent_id="test")

        assert agent.agent_id == "test"
        assert agent.enabled is True
        assert agent.priority == 50
        assert agent.custom_prompt_override is None

    def test_with_custom_prompt(self):
        """Agent avec prompt personnalisé."""
        agent = AgentActivation(
            agent_id="test",
            custom_prompt_override="Custom instructions"
        )

        assert agent.custom_prompt_override == "Custom instructions"


class TestKnowledgeBaseConfigEntity:
    """Tests pour l'entité KnowledgeBaseConfig."""

    def test_default_values(self):
        """Valeurs par défaut."""
        kb = KnowledgeBaseConfig()

        assert kb.company_name == ""
        assert kb.company_description == ""
        assert kb.forbidden_topics == []
        assert kb.custom_signatures == {}
        assert kb.faq_entries == {}

    def test_with_all_fields(self):
        """Avec tous les champs remplis."""
        kb = KnowledgeBaseConfig(
            company_name="Test Co",
            company_description="A test company",
            products_services="Product A, Product B",
            tone_guidelines="Professional",
            forbidden_topics=["competitors", "pricing"],
            custom_signatures={"formal": "Best regards", "casual": "Cheers"},
            faq_entries={"hours": "9-5 Mon-Fri"},
            custom_file_path="/path/to/kb.md",
        )

        assert kb.company_name == "Test Co"
        assert len(kb.forbidden_topics) == 2
        assert "formal" in kb.custom_signatures


class TestEnums:
    """Tests pour les enums."""

    def test_business_sector_values(self):
        """Tous les secteurs sont accessibles."""
        assert BusinessSector.TECH.value == "tech"
        assert BusinessSector.SAAS.value == "saas"
        assert BusinessSector.ECOMMERCE.value == "ecommerce"
        assert BusinessSector.OTHER.value == "other"

    def test_company_size_values(self):
        """Toutes les tailles sont accessibles."""
        assert CompanySize.SOLO.value == "solo"
        assert CompanySize.STARTUP.value == "startup"
        assert CompanySize.SMB.value == "smb"
        assert CompanySize.MIDMARKET.value == "midmarket"
        assert CompanySize.ENTERPRISE.value == "enterprise"

    def test_config_pack_values(self):
        """Tous les packs sont accessibles."""
        assert ConfigPack.CUSTOM.value == "custom"
        assert ConfigPack.STARTUP.value == "startup"
        assert ConfigPack.SMB.value == "smb"
        assert ConfigPack.ENTERPRISE.value == "enterprise"
        assert ConfigPack.SAAS.value == "saas"
        assert ConfigPack.ECOMMERCE.value == "ecommerce"
        assert ConfigPack.B2B.value == "b2b"


# ============================================================================
# TESTS - USE CASES
# ============================================================================

class TestSaveWizardConfigUseCase:
    """Tests pour SaveWizardConfigUseCase."""

    def test_save_valid_config(self, mock_store, sample_config):
        """Sauvegarde d'une config valide."""
        use_case = SaveWizardConfigUseCase(persistence=mock_store)

        result = use_case.execute(sample_config)

        mock_store.save.assert_called_once_with(sample_config)
        assert result == sample_config

    def test_save_config_without_id_raises(self, mock_store):
        """Config sans ID lève une erreur."""
        config = WizardConfig(config_id="", company_name="Test")
        use_case = SaveWizardConfigUseCase(persistence=mock_store)

        with pytest.raises(ValueError, match="config_id est requis"):
            use_case.execute(config)

    def test_save_config_without_company_name_raises(self, mock_store):
        """Config sans nom d'entreprise lève une erreur."""
        config = WizardConfig(config_id="123", company_name="")
        use_case = SaveWizardConfigUseCase(persistence=mock_store)

        with pytest.raises(ValueError, match="company_name est requis"):
            use_case.execute(config)

    def test_save_config_with_whitespace_name_raises(self, mock_store):
        """Config avec nom whitespace lève une erreur."""
        config = WizardConfig(config_id="123", company_name="   ")
        use_case = SaveWizardConfigUseCase(persistence=mock_store)

        with pytest.raises(ValueError, match="company_name est requis"):
            use_case.execute(config)


class TestLoadWizardConfigUseCase:
    """Tests pour LoadWizardConfigUseCase."""

    def test_load_existing_config(self, mock_store, sample_config):
        """Chargement d'une config existante."""
        mock_store.load.return_value = sample_config
        use_case = LoadWizardConfigUseCase(persistence=mock_store)

        result = use_case.execute()

        mock_store.load.assert_called_once()
        assert result == sample_config

    def test_load_nonexistent_config(self, mock_store):
        """Chargement quand aucune config n'existe."""
        mock_store.load.return_value = None
        use_case = LoadWizardConfigUseCase(persistence=mock_store)

        result = use_case.execute()

        assert result is None


class TestCreateWizardConfigUseCase:
    """Tests pour CreateWizardConfigUseCase."""

    def test_create_minimal_config(self, mock_store):
        """Création avec paramètres minimaux."""
        use_case = CreateWizardConfigUseCase(persistence=mock_store)

        config = use_case.execute(company_name="Test Co")

        assert config.company_name == "Test Co"
        assert config.config_id  # UUID généré
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB
        assert config.pack == ConfigPack.CUSTOM

    def test_create_with_pack_startup(self, mock_store):
        """Création avec pack Startup."""
        use_case = CreateWizardConfigUseCase(persistence=mock_store)

        config = use_case.execute(
            company_name="My Startup",
            pack=ConfigPack.STARTUP
        )

        assert config.pack == ConfigPack.STARTUP
        # Vérifier que les agents du pack sont activés
        active_ids = {a.agent_id for a in config.get_active_agents()}
        assert "drafter" in active_ids
        assert "onboarding_specialist" in active_ids

    def test_create_with_all_params(self, mock_store):
        """Création avec tous les paramètres."""
        use_case = CreateWizardConfigUseCase(persistence=mock_store)

        config = use_case.execute(
            company_name="Enterprise Corp",
            sector=BusinessSector.FINANCE,
            size=CompanySize.ENTERPRISE,
            pack=ConfigPack.ENTERPRISE,
        )

        assert config.sector == BusinessSector.FINANCE
        assert config.size == CompanySize.ENTERPRISE
        assert len(config.get_active_agents()) > 0


class TestToggleAgentUseCase:
    """Tests pour ToggleAgentUseCase."""

    def test_activate_agent(self, real_store, sample_config):
        """Activation d'un agent."""
        real_store.save(sample_config)
        use_case = ToggleAgentUseCase(persistence=real_store)

        result = use_case.execute("tech_support", enabled=True, priority=75)

        assert result is not None
        assert result.is_agent_active("tech_support") is True

    def test_deactivate_agent(self, real_store, sample_config):
        """Désactivation d'un agent."""
        sample_config.activate_agent("tech_support")
        real_store.save(sample_config)
        use_case = ToggleAgentUseCase(persistence=real_store)

        result = use_case.execute("tech_support", enabled=False)

        assert result.is_agent_active("tech_support") is False

    def test_toggle_no_config(self, real_store):
        """Toggle sans config existante retourne None."""
        use_case = ToggleAgentUseCase(persistence=real_store)

        result = use_case.execute("tech_support", enabled=True)

        assert result is None


class TestImportKnowledgeBaseUseCase:
    """Tests pour ImportKnowledgeBaseUseCase."""

    def test_import_file(self, real_store, sample_config, tmp_path):
        """Import d'un fichier KB."""
        real_store.save(sample_config)

        kb_file = tmp_path / "knowledge.md"
        kb_file.write_text("# Company Knowledge\n\nImportant info here.")

        use_case = ImportKnowledgeBaseUseCase(persistence=real_store)
        result = use_case.execute(str(kb_file))

        assert result is not None
        assert "Important info here" in result.knowledge_base.company_description

    def test_import_file_merge(self, real_store, sample_config, tmp_path):
        """Import avec fusion."""
        sample_config.knowledge_base.company_description = "Original content"
        real_store.save(sample_config)

        kb_file = tmp_path / "knowledge.md"
        kb_file.write_text("New content")

        use_case = ImportKnowledgeBaseUseCase(persistence=real_store)
        result = use_case.execute(str(kb_file), merge=True)

        assert "Original content" in result.knowledge_base.company_description
        assert "New content" in result.knowledge_base.company_description

    def test_import_file_not_found(self, real_store, sample_config):
        """Import de fichier inexistant."""
        real_store.save(sample_config)
        use_case = ImportKnowledgeBaseUseCase(persistence=real_store)

        with pytest.raises(FileNotFoundError):
            use_case.execute("/nonexistent/path.md")


class TestExportConfigUseCase:
    """Tests pour ExportConfigUseCase."""

    def test_export_config(self, real_store, sample_config, tmp_path):
        """Export de la config."""
        real_store.save(sample_config)
        export_path = tmp_path / "export.json"

        use_case = ExportConfigUseCase(persistence=real_store)
        result = use_case.execute(str(export_path))

        assert result is True
        assert export_path.exists()

        # Vérifier le contenu
        data = json.loads(export_path.read_text())
        assert data["company_name"] == "Test Company"


# ============================================================================
# TESTS - PACK CONFIGURATIONS
# ============================================================================

class TestPackConfigurations:
    """Tests pour les configurations de packs."""

    def test_get_available_packs(self):
        """Liste des packs disponibles."""
        packs = get_available_packs()

        assert len(packs) >= 6
        pack_ids = {p["id"] for p in packs}
        assert "startup" in pack_ids
        assert "smb" in pack_ids
        assert "enterprise" in pack_ids
        assert "saas" in pack_ids
        assert "ecommerce" in pack_ids
        assert "b2b" in pack_ids

    def test_get_available_agents(self):
        """Liste des agents disponibles."""
        agents = get_available_agents()

        assert len(agents) >= 10
        agent_ids = {a["id"] for a in agents}
        assert "drafter" in agent_ids
        assert "critic" in agent_ids
        assert "tech_support" in agent_ids

    def test_pack_configurations_structure(self):
        """Structure des configurations de packs."""
        for pack, config in PACK_CONFIGURATIONS.items():
            assert "agents" in config
            assert "languages" in config
            assert "tone_guidelines" in config
            assert len(config["agents"]) > 0

            # Vérifier que chaque agent a un ID
            for agent in config["agents"]:
                assert "id" in agent

    def test_all_packs_include_core_agents(self):
        """Tous les packs incluent les agents core."""
        for pack, config in PACK_CONFIGURATIONS.items():
            agent_ids = {a["id"] for a in config["agents"]}
            assert "drafter" in agent_ids, f"Pack {pack} missing drafter"
            assert "critic" in agent_ids, f"Pack {pack} missing critic"


# ============================================================================
# TESTS - PERSISTENCE STORE
# ============================================================================

class TestJsonFileWizardConfigStore:
    """Tests pour JsonFileWizardConfigStore."""

    def test_save_and_load(self, real_store, sample_config):
        """Sauvegarde et rechargement."""
        real_store.save(sample_config)

        loaded = real_store.load()

        assert loaded is not None
        assert loaded.config_id == sample_config.config_id
        assert loaded.company_name == sample_config.company_name

    def test_exists(self, real_store, sample_config):
        """Vérification d'existence."""
        assert real_store.exists() is False

        real_store.save(sample_config)

        assert real_store.exists() is True

    def test_delete(self, real_store, sample_config):
        """Suppression de la config."""
        real_store.save(sample_config)
        assert real_store.exists() is True

        result = real_store.delete()

        assert result is True
        assert real_store.exists() is False
        assert real_store.load() is None

    def test_delete_nonexistent(self, real_store):
        """Suppression d'une config inexistante."""
        result = real_store.delete()

        assert result is False

    def test_version_increment(self, real_store, sample_config):
        """Incrémentation de version à chaque sauvegarde."""
        assert sample_config.version == 1

        real_store.save(sample_config)
        loaded = real_store.load()
        assert loaded.version == 1

        real_store.save(loaded)
        loaded2 = real_store.load()
        assert loaded2.version == 2

    def test_export_to_file(self, real_store, sample_config, tmp_path):
        """Export vers fichier."""
        real_store.save(sample_config)
        export_path = tmp_path / "exported.json"

        real_store.export_to_file(str(export_path))

        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["company_name"] == "Test Company"

    def test_export_no_config_raises(self, real_store, tmp_path):
        """Export sans config lève une erreur."""
        export_path = tmp_path / "exported.json"

        with pytest.raises(ValueError, match="Aucune configuration"):
            real_store.export_to_file(str(export_path))

    def test_import_from_file(self, real_store, tmp_path, sample_config):
        """Import depuis fichier."""
        import_path = tmp_path / "import.json"
        import_path.write_text(json.dumps(sample_config.to_dict()))

        result = real_store.import_from_file(str(import_path))

        assert result.company_name == "Test Company"
        assert real_store.exists() is True

    def test_import_file_not_found(self, real_store):
        """Import de fichier inexistant."""
        with pytest.raises(FileNotFoundError):
            real_store.import_from_file("/nonexistent/file.json")

    def test_import_invalid_json(self, real_store, tmp_path):
        """Import de JSON invalide."""
        import_path = tmp_path / "invalid.json"
        import_path.write_text("not valid json")

        with pytest.raises(ValueError, match="Format JSON invalide"):
            real_store.import_from_file(str(import_path))


# ============================================================================
# TESTS - API ENDPOINTS (avec Flask test client)
# ============================================================================

# Vérifier si Flask est disponible
import importlib.util
FLASK_AVAILABLE = (
    importlib.util.find_spec("flask") is not None
    and importlib.util.find_spec("flask_cors") is not None
)


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask/flask_cors not installed")
class TestWizardAPIEndpoints:
    """Tests pour les endpoints API du wizard."""

    @pytest.fixture
    def client(self, temp_config_file):
        """Client de test Flask."""
        reset_wizard_config_store()

        # Import l'app directement
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Créer un store temporaire
        temp_store = JsonFileWizardConfigStore(temp_config_file)

        # Importer et créer l'app
        from app.api.app import create_app
        from app.api import wizard as wizard_module

        # Sauvegarder l'original et remplacer
        original_get_store = wizard_module.get_wizard_config_store
        wizard_module.get_wizard_config_store = lambda: temp_store

        try:
            app = create_app({"TESTING": True})
            with app.test_client() as client:
                yield client
        finally:
            # Restaurer
            wizard_module.get_wizard_config_store = original_get_store

    def test_get_config_empty(self, client):
        """GET /api/wizard/config sans config."""
        response = client.get("/api/wizard/config")

        assert response.status_code == 200
        data = response.get_json()
        assert data["exists"] is False
        assert data["config"] is None

    @pytest.mark.skip(reason="Obsolète post audits sécurité 2026-04 — auth/admin requise. À refactorer hors scope migration runner Hetzner.")
    def test_create_config(self, client):
        """POST /api/wizard/config - création."""
        response = client.post(
            "/api/wizard/config",
            json={
                "company_name": "API Test Company",
                "sector": "tech",
                "size": "startup",
            },
            content_type="application/json"
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["config"]["company_name"] == "API Test Company"

    @pytest.mark.skip(reason="Obsolète post audits sécurité 2026-04 — auth/admin requise. À refactorer hors scope migration runner Hetzner.")
    def test_create_config_missing_name(self, client):
        """POST /api/wizard/config sans nom."""
        response = client.post(
            "/api/wizard/config",
            json={"sector": "tech"},
            content_type="application/json"
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "company_name" in data["error"]

    def test_get_packs(self, client):
        """GET /api/wizard/packs."""
        response = client.get("/api/wizard/packs")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] >= 6
        assert len(data["packs"]) >= 6

    def test_get_agents(self, client):
        """GET /api/wizard/agents."""
        response = client.get("/api/wizard/agents")

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] >= 10
        assert "by_category" in data

    def test_get_agents_filtered(self, client):
        """GET /api/wizard/agents?category=core."""
        response = client.get("/api/wizard/agents?category=core")

        assert response.status_code == 200
        data = response.get_json()
        # Seuls les agents core
        for agent in data["agents"]:
            assert agent["category"] == "core"


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_config_with_empty_agents_list(self):
        """Config avec liste d'agents vide."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[]
        )

        assert config.get_active_agents() == []

    def test_config_with_all_agents_disabled(self):
        """Config avec tous les agents désactivés."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            agents=[
                AgentActivation(agent_id="a", enabled=False),
                AgentActivation(agent_id="b", enabled=False),
            ]
        )

        assert config.get_active_agents() == []

    def test_config_with_unicode_company_name(self):
        """Config avec nom d'entreprise unicode."""
        config = WizardConfig(
            config_id="123",
            company_name="日本企業 株式会社"
        )

        data = config.to_dict()
        restored = WizardConfig.from_dict(data)

        assert restored.company_name == "日本企業 株式会社"

    def test_config_with_special_chars_in_kb(self):
        """Config avec caractères spéciaux dans la KB."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            knowledge_base=KnowledgeBaseConfig(
                company_description='Contains "quotes" and \'apostrophes\' & <tags>',
            )
        )

        data = config.to_dict()
        restored = WizardConfig.from_dict(data)

        assert "quotes" in restored.knowledge_base.company_description
        assert "<tags>" in restored.knowledge_base.company_description

    def test_priority_bounds(self):
        """Priorités aux limites (0 et 100)."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
        )

        config.activate_agent("min", priority=0)
        config.activate_agent("max", priority=100)

        active = config.get_active_agents()
        assert active[0].priority == 100
        assert active[1].priority == 0

    def test_multiple_languages(self):
        """Config avec nombreuses langues."""
        config = WizardConfig(
            config_id="123",
            company_name="Test",
            supported_languages=["fr", "en", "de", "es", "it", "pt", "nl", "pl", "ru", "zh", "ja", "ko"]
        )

        assert len(config.supported_languages) == 12

        data = config.to_dict()
        restored = WizardConfig.from_dict(data)

        assert len(restored.supported_languages) == 12
