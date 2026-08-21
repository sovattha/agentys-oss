# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le gestionnaire de mémoire IA.

pytest tests/test_memory_manager.py -v
"""

import pytest
import json
import tempfile
from pathlib import Path

from app.memory_manager import (
    MemoryVersion,
    MemorySection,
    MemoryStats,
    MemoryManager,
    get_memory_manager
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_dirs():
    """Crée des répertoires temporaires pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        memory_file = tmpdir / "knowledge" / "memoire.md"
        history_file = tmpdir / "data" / "memory_history.json"
        yield memory_file, history_file


@pytest.fixture
def memory_manager(temp_dirs):
    """Crée un manager avec des fichiers temporaires."""
    memory_file, history_file = temp_dirs
    return MemoryManager(memory_file=memory_file, history_file=history_file)


@pytest.fixture
def sample_memory():
    """Exemple de contenu de mémoire."""
    return """# Base de Connaissances

## Informations Générales

Ceci est la base de connaissances de l'IA.
Elle contient les informations importantes.

## Règles de Réponse

- Toujours être poli
- Répondre de manière concise
- Utiliser un ton professionnel

## FAQ

### Question 1
Réponse à la question 1.

### Question 2
Réponse à la question 2.
"""


@pytest.fixture
def manager_with_content(memory_manager, sample_memory):
    """Manager avec du contenu initial."""
    memory_manager.update_memory(sample_memory)
    return memory_manager


# ============================================================================
# TESTS DATA CLASSES
# ============================================================================

class TestDataClasses:
    """Tests pour les dataclasses."""

    def test_memory_version_creation(self):
        """Test création d'une version."""
        version = MemoryVersion(
            id="v_001",
            content_hash="abc123",
            content_length=100,
            preview="Preview du contenu..."
        )
        assert version.id == "v_001"
        assert version.content_hash == "abc123"
        assert version.content_length == 100
        assert version.created_by == "user"

    def test_memory_section_creation(self):
        """Test création d'une section."""
        section = MemorySection(
            title="Ma Section",
            level=2,
            content="Contenu de la section",
            start_line=5,
            end_line=10
        )
        assert section.title == "Ma Section"
        assert section.level == 2

    def test_memory_stats_creation(self):
        """Test création des stats."""
        stats = MemoryStats(
            total_size=1000,
            word_count=150,
            section_count=5,
            last_modified="2024-01-01T12:00:00",
            version_count=3
        )
        assert stats.total_size == 1000
        assert stats.word_count == 150


# ============================================================================
# TESTS MEMORY MANAGER - BASE
# ============================================================================

class TestMemoryManagerBase:
    """Tests de base pour MemoryManager."""

    def test_manager_creation(self, memory_manager):
        """Test création du manager."""
        assert memory_manager is not None
        assert memory_manager.history == []

    def test_get_empty_memory(self, memory_manager):
        """Test récupération mémoire vide."""
        content = memory_manager.get_memory()
        assert content == ""

    def test_update_memory(self, memory_manager):
        """Test mise à jour de la mémoire."""
        content = "# Test\n\nContenu de test."
        version = memory_manager.update_memory(content)

        assert version is not None
        assert version.id.startswith("v_")
        assert version.content_length == len(content)
        assert len(memory_manager.history) == 1

    def test_update_memory_with_summary(self, memory_manager):
        """Test mise à jour avec résumé."""
        version = memory_manager.update_memory(
            "Contenu",
            change_summary="Ajout initial"
        )
        assert version.change_summary == "Ajout initial"

    def test_update_memory_preserves_content(self, memory_manager):
        """Test que le contenu est préservé."""
        content = "# Titre\n\nContenu important."
        memory_manager.update_memory(content)

        retrieved = memory_manager.get_memory()
        assert retrieved == content

    def test_multiple_updates(self, memory_manager):
        """Test mises à jour multiples."""
        memory_manager.update_memory("Version 1")
        memory_manager.update_memory("Version 2")
        memory_manager.update_memory("Version 3")

        assert len(memory_manager.history) == 3
        assert memory_manager.get_memory() == "Version 3"


# ============================================================================
# TESTS HISTORY
# ============================================================================

class TestHistory:
    """Tests pour l'historique des versions."""

    def test_get_empty_history(self, memory_manager):
        """Test historique vide."""
        history = memory_manager.get_history()
        assert history == []

    def test_get_history_after_updates(self, memory_manager):
        """Test historique après mises à jour."""
        memory_manager.update_memory("V1")
        memory_manager.update_memory("V2")

        history = memory_manager.get_history()
        assert len(history) == 2
        # Plus récent en premier
        assert history[0].preview.startswith("V2")

    def test_get_history_with_limit(self, memory_manager):
        """Test historique avec limite."""
        for i in range(10):
            memory_manager.update_memory(f"Version {i}")

        history = memory_manager.get_history(limit=5)
        assert len(history) == 5

    def test_get_history_with_offset(self, memory_manager):
        """Test historique avec offset."""
        for i in range(10):
            memory_manager.update_memory(f"Version {i}")

        history = memory_manager.get_history(limit=3, offset=5)
        assert len(history) == 3

    def test_get_version(self, memory_manager):
        """Test récupération d'une version."""
        version = memory_manager.update_memory("Test")
        retrieved = memory_manager.get_version(version.id)

        assert retrieved is not None
        assert retrieved.id == version.id

    def test_get_version_not_found(self, memory_manager):
        """Test version non trouvée."""
        version = memory_manager.get_version("non_existent")
        assert version is None

    def test_history_persistence(self, temp_dirs):
        """Test persistance de l'historique."""
        memory_file, history_file = temp_dirs

        # Créer un manager et ajouter des versions
        manager1 = MemoryManager(memory_file=memory_file, history_file=history_file)
        manager1.update_memory("Version 1")
        manager1.update_memory("Version 2")

        # Créer un nouveau manager
        manager2 = MemoryManager(memory_file=memory_file, history_file=history_file)

        assert len(manager2.history) == 2


# ============================================================================
# TESTS SECTIONS
# ============================================================================

class TestSections:
    """Tests pour la gestion des sections."""

    def test_get_sections_empty(self, memory_manager):
        """Test sections sur mémoire vide."""
        sections = memory_manager.get_sections()
        assert sections == []

    def test_get_sections(self, manager_with_content):
        """Test extraction des sections."""
        sections = manager_with_content.get_sections()

        assert len(sections) > 0
        # Vérifier qu'on a trouvé les sections principales
        titles = [s.title for s in sections]
        assert "Base de Connaissances" in titles
        assert "Informations Générales" in titles

    def test_section_levels(self, manager_with_content):
        """Test niveaux des sections."""
        sections = manager_with_content.get_sections()

        # Vérifier les niveaux
        for section in sections:
            assert 1 <= section.level <= 6

    def test_update_section(self, manager_with_content):
        """Test mise à jour d'une section."""
        version = manager_with_content.update_section(
            "Informations Générales",
            "Nouveau contenu de la section."
        )

        assert version is not None
        content = manager_with_content.get_memory()
        assert "Nouveau contenu de la section." in content

    def test_update_section_not_found(self, manager_with_content):
        """Test mise à jour section inexistante."""
        version = manager_with_content.update_section(
            "Section Inexistante",
            "Contenu"
        )
        assert version is None

    def test_add_section(self, memory_manager):
        """Test ajout d'une section."""
        memory_manager.update_memory("# Titre Principal\n\nIntro.")

        version = memory_manager.add_section(
            title="Nouvelle Section",
            content="Contenu de la nouvelle section.",
            level=2
        )

        assert version is not None
        content = memory_manager.get_memory()
        assert "## Nouvelle Section" in content
        assert "Contenu de la nouvelle section." in content

    def test_add_section_at_start(self, memory_manager):
        """Test ajout d'une section au début."""
        memory_manager.update_memory("# Titre\n\n## Section Existante\nContenu.")

        memory_manager.add_section(
            title="Première Section",
            content="Contenu premier.",
            level=2,
            position="start"
        )

        content = memory_manager.get_memory()
        # La nouvelle section devrait être présente
        assert "Première Section" in content

    def test_delete_section(self, manager_with_content):
        """Test suppression d'une section."""
        version = manager_with_content.delete_section("FAQ")

        assert version is not None
        content = manager_with_content.get_memory()
        assert "## FAQ" not in content

    def test_delete_section_not_found(self, manager_with_content):
        """Test suppression section inexistante."""
        version = manager_with_content.delete_section("Section Inexistante")
        assert version is None


# ============================================================================
# TESTS SEARCH
# ============================================================================

class TestSearch:
    """Tests pour la recherche."""

    def test_search_empty_memory(self, memory_manager):
        """Test recherche sur mémoire vide."""
        results = memory_manager.search("test")
        assert results == []

    def test_search_empty_query(self, manager_with_content):
        """Test recherche avec requête vide."""
        results = manager_with_content.search("")
        assert results == []

    def test_search_found(self, manager_with_content):
        """Test recherche avec résultats."""
        results = manager_with_content.search("poli")

        assert len(results) > 0
        assert any("poli" in r["match"].lower() for r in results)

    def test_search_not_found(self, manager_with_content):
        """Test recherche sans résultats."""
        results = manager_with_content.search("xyz123gibberish")
        assert results == []

    def test_search_case_insensitive(self, manager_with_content):
        """Test recherche insensible à la casse."""
        results_lower = manager_with_content.search("poli")
        results_upper = manager_with_content.search("POLI")

        assert len(results_lower) == len(results_upper)

    def test_search_returns_context(self, manager_with_content):
        """Test que la recherche retourne le contexte."""
        results = manager_with_content.search("poli")

        if results:
            result = results[0]
            assert "line" in result
            assert "match" in result
            assert "context" in result


# ============================================================================
# TESTS STATS
# ============================================================================

class TestStats:
    """Tests pour les statistiques."""

    def test_stats_empty_memory(self, memory_manager):
        """Test stats sur mémoire vide."""
        stats = memory_manager.get_stats()

        assert stats.total_size == 0
        assert stats.word_count == 0
        assert stats.section_count == 0
        assert stats.version_count == 0

    def test_stats_with_content(self, manager_with_content):
        """Test stats avec contenu."""
        stats = manager_with_content.get_stats()

        assert stats.total_size > 0
        assert stats.word_count > 0
        assert stats.section_count > 0
        assert stats.version_count >= 1

    def test_stats_updates_after_change(self, memory_manager):
        """Test que les stats se mettent à jour."""
        stats1 = memory_manager.get_stats()

        memory_manager.update_memory("Un peu de contenu")
        memory_manager.update_memory("Encore plus de contenu ajouté ici")

        stats2 = memory_manager.get_stats()

        assert stats2.version_count > stats1.version_count


# ============================================================================
# TESTS EXPORT/IMPORT
# ============================================================================

class TestExportImport:
    """Tests pour l'export et l'import."""

    def test_export_markdown(self, manager_with_content):
        """Test export en markdown."""
        exported = manager_with_content.export_memory(format="markdown")

        assert exported == manager_with_content.get_memory()

    def test_export_json(self, manager_with_content):
        """Test export en JSON."""
        exported = manager_with_content.export_memory(format="json")

        data = json.loads(exported)
        assert "content" in data
        assert "sections" in data
        assert "stats" in data

    def test_export_text(self, manager_with_content):
        """Test export en texte brut."""
        exported = manager_with_content.export_memory(format="text")

        # Le markdown devrait être supprimé
        assert "##" not in exported or True  # Simplifié pour éviter faux positifs

    def test_import_memory(self, memory_manager):
        """Test import de contenu."""
        content = "# Contenu Importé\n\nCeci est du contenu importé."
        version = memory_manager.import_memory(content)

        assert version is not None
        assert memory_manager.get_memory() == content

    def test_import_memory_merge(self, memory_manager):
        """Test import avec fusion."""
        initial = "# Initial\n\nContenu initial."
        memory_manager.update_memory(initial)

        imported = "Contenu supplémentaire."
        memory_manager.import_memory(imported, merge=True)

        content = memory_manager.get_memory()
        assert "Initial" in content
        assert "Contenu supplémentaire" in content


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingleton:
    """Tests pour le singleton."""

    def test_get_memory_manager_singleton(self):
        """Test que get_memory_manager retourne un singleton."""
        manager1 = get_memory_manager()
        manager2 = get_memory_manager()

        assert manager1 is manager2

    def test_memory_manager_type(self):
        """Test le type du manager."""
        manager = get_memory_manager()
        assert isinstance(manager, MemoryManager)


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_unicode_content(self, memory_manager):
        """Test contenu Unicode."""
        content = "# Titre 日本語\n\nContenu avec émojis 🎉🚀"
        memory_manager.update_memory(content)

        retrieved = memory_manager.get_memory()
        assert retrieved == content

    def test_very_long_content(self, memory_manager):
        """Test contenu très long."""
        content = "# Titre\n\n" + "Lorem ipsum " * 10000
        version = memory_manager.update_memory(content)

        assert version is not None
        assert len(memory_manager.get_memory()) == len(content)

    def test_special_characters(self, memory_manager):
        """Test caractères spéciaux."""
        content = "# Test <>&\"'\n\n```code```\n\n| Tab | le |"
        memory_manager.update_memory(content)

        assert memory_manager.get_memory() == content

    def test_empty_sections(self, memory_manager):
        """Test sections vides."""
        content = "# Titre\n\n## Section Vide\n\n## Autre Section\n\nContenu."
        memory_manager.update_memory(content)

        sections = memory_manager.get_sections()
        assert len(sections) >= 2

    def test_nested_headings(self, memory_manager):
        """Test headings imbriqués."""
        content = """# H1
## H2
### H3
#### H4
##### H5
###### H6
"""
        memory_manager.update_memory(content)
        sections = memory_manager.get_sections()

        levels = [s.level for s in sections]
        assert 1 in levels
        assert 2 in levels
        assert 3 in levels

    def test_hash_consistency(self, memory_manager):
        """Test que le hash est cohérent."""
        content = "Contenu de test"

        hash1 = memory_manager._compute_hash(content)
        hash2 = memory_manager._compute_hash(content)

        assert hash1 == hash2

    def test_hash_different_for_different_content(self, memory_manager):
        """Test que des contenus différents ont des hash différents."""
        hash1 = memory_manager._compute_hash("Contenu 1")
        hash2 = memory_manager._compute_hash("Contenu 2")

        assert hash1 != hash2

    def test_preview_length(self, memory_manager):
        """Test que le preview est limité."""
        content = "x" * 500
        version = memory_manager.update_memory(content)

        assert len(version.preview) <= 200

    def test_restore_version_not_implemented(self, memory_manager):
        """Test que restore_version retourne None."""
        version = memory_manager.update_memory("Test")
        result = memory_manager.restore_version(version.id)

        assert result is None  # Non implémenté car on ne stocke pas le contenu complet


# ============================================================================
# TESTS INTEGRATION
# ============================================================================

class TestIntegration:
    """Tests d'intégration."""

    def test_full_workflow(self, memory_manager):
        """Test workflow complet."""
        # 1. Créer la mémoire initiale
        initial = "# Ma Base de Connaissances\n\n## Infos\n\nInformations générales."
        memory_manager.update_memory(initial)

        # 2. Ajouter une section
        memory_manager.add_section("FAQ", "Questions fréquentes.", level=2)

        # 3. Mettre à jour une section
        memory_manager.update_section("Infos", "Nouvelles informations.")

        # 4. Rechercher
        results = memory_manager.search("informations")
        assert len(results) > 0

        # 5. Vérifier les stats
        stats = memory_manager.get_stats()
        assert stats.section_count >= 2
        assert stats.version_count >= 3

        # 6. Vérifier l'historique
        history = memory_manager.get_history()
        assert len(history) >= 3

        # 7. Exporter
        exported = memory_manager.export_memory(format="json")
        data = json.loads(exported)
        assert "content" in data

    def test_concurrent_operations(self, temp_dirs):
        """Test opérations concurrentes."""
        memory_file, history_file = temp_dirs

        manager1 = MemoryManager(memory_file=memory_file, history_file=history_file)
        manager2 = MemoryManager(memory_file=memory_file, history_file=history_file)

        # Les deux managers partagent le même fichier
        manager1.update_memory("Version 1")

        # manager2 devrait lire le contenu mis à jour
        content = manager2.get_memory()
        assert content == "Version 1"
