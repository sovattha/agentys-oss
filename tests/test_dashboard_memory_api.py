# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les endpoints API Memory du module Dashboard.

Ces tests couvrent les paths de succès (happy paths) pour :
- GET /api/memory
- POST /api/memory
- GET /api/memory/sections
- PUT /api/memory/sections/<section_title>
- POST /api/memory/sections
- DELETE /api/memory/sections/<section_title>
- GET /api/memory/search
- GET /api/memory/history
- GET /api/memory/export
- POST /api/memory/import

Principes Clean Architecture respectés :
- Tests du module sans dépendances externes réelles
- Injection de dépendances via mocks
- Tests unitaires isolés
"""

import pytest
import json
from unittest.mock import Mock, patch
from dataclasses import dataclass


# =============================================================================
# MOCK CLASSES FOR MEMORY MANAGER
# =============================================================================


@dataclass
class MockMemoryStats:
    """Mock pour les statistiques de mémoire."""
    total_size: int = 1000
    word_count: int = 200
    section_count: int = 5
    last_modified: str = "2024-01-15T10:30:00"
    version_count: int = 10


@dataclass
class MockMemoryVersion:
    """Mock pour une version de mémoire."""
    id: str = "version-123"
    content_hash: str = "abc123def456"
    created_at: str = "2024-01-15T10:30:00"
    change_summary: str = ""
    created_by: str = "user"


@dataclass
class MockMemorySection:
    """Mock pour une section de mémoire."""
    title: str = "Section 1"
    level: int = 2
    content: str = "Section content"
    start_line: int = 1
    end_line: int = 10


class MockMemoryManager:
    """Mock complet pour MemoryManager."""

    def __init__(self):
        self._stats = MockMemoryStats()
        self._memory = "# Test Memory\nSome content here."
        self._sections = [
            MockMemorySection(title="Section 1", level=2, content="Content 1"),
            MockMemorySection(title="Section 2", level=2, content="Content 2"),
        ]
        self.history = [
            MockMemoryVersion(id="v1"),
            MockMemoryVersion(id="v2"),
            MockMemoryVersion(id="v3"),
        ]

    def get_memory(self) -> str:
        return self._memory

    def get_stats(self) -> MockMemoryStats:
        return self._stats

    def update_memory(self, content: str, change_summary: str = "", created_by: str = "dashboard") -> MockMemoryVersion:
        self._memory = content
        return MockMemoryVersion(id="new-version-123", content_hash="newhash", change_summary=change_summary, created_by=created_by)

    def get_sections(self) -> list:
        return self._sections

    def update_section(self, section_title: str, new_content: str, change_summary: str = "") -> MockMemoryVersion | None:
        for section in self._sections:
            if section.title == section_title:
                section.content = new_content
                return MockMemoryVersion(id="updated-version", change_summary=change_summary)
        return None

    def add_section(self, title: str, content: str, level: int = 2, position: str = "end") -> MockMemoryVersion:
        self._sections.append(MockMemorySection(title=title, level=level, content=content))
        return MockMemoryVersion(id="added-section-version")

    def delete_section(self, section_title: str) -> MockMemoryVersion | None:
        for i, section in enumerate(self._sections):
            if section.title == section_title:
                self._sections.pop(i)
                return MockMemoryVersion(id="deleted-section-version")
        return None

    def search(self, query: str) -> list:
        results = []
        if query.lower() in self._memory.lower():
            results.append({"match": query, "context": "Some context around the match"})
        return results

    def get_history(self, limit: int = 20, offset: int = 0) -> list:
        return self.history[offset:offset + limit]

    def export_memory(self, format: str = "markdown") -> str:
        if format == "json":
            return json.dumps({"content": self._memory, "sections": len(self._sections)})
        elif format == "text":
            return self._memory.replace("#", "")
        else:
            return self._memory

    def import_memory(self, content: str, merge: bool = False) -> MockMemoryVersion:
        if merge:
            self._memory = self._memory + "\n" + content
        else:
            self._memory = content
        return MockMemoryVersion(id="imported-version")


# =============================================================================
# TESTS API MEMORY GET
# =============================================================================


class TestApiMemoryGet:
    """Tests pour GET /api/memory."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_get_success(self, client):
        """GET /api/memory retourne le contenu et les stats."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "content" in data
            assert "stats" in data
            assert data["content"] == "# Test Memory\nSome content here."
            assert data["stats"]["total_size"] == 1000
            assert data["stats"]["word_count"] == 200
            assert data["stats"]["section_count"] == 5

    def test_api_memory_get_empty_memory(self, client):
        """GET /api/memory avec mémoire vide."""
        mock_manager = MockMemoryManager()
        mock_manager._memory = ""
        mock_manager._stats = MockMemoryStats(total_size=0, word_count=0, section_count=0)

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["content"] == ""
            assert data["stats"]["total_size"] == 0


# =============================================================================
# TESTS API MEMORY UPDATE
# =============================================================================


class TestApiMemoryUpdate:
    """Tests pour POST /api/memory."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_update_success(self, client):
        """POST /api/memory met à jour le contenu."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory',
                data=json.dumps({
                    "content": "# New Memory Content\nUpdated content.",
                    "change_summary": "Updated memory",
                    "created_by": "test-user"
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "version" in data
            assert data["version"]["id"] == "new-version-123"

    def test_api_memory_update_minimal_params(self, client):
        """POST /api/memory avec seulement le contenu."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory',
                data=json.dumps({"content": "Minimal update"}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True


# =============================================================================
# TESTS API MEMORY SECTIONS
# =============================================================================


class TestApiMemorySections:
    """Tests pour GET /api/memory/sections."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_sections_success(self, client):
        """GET /api/memory/sections retourne les sections."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/sections')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "sections" in data
            assert len(data["sections"]) == 2
            assert data["sections"][0]["title"] == "Section 1"

    def test_api_memory_sections_empty(self, client):
        """GET /api/memory/sections avec aucune section."""
        mock_manager = MockMemoryManager()
        mock_manager._sections = []

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/sections')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["sections"] == []


# =============================================================================
# TESTS API MEMORY SECTION UPDATE
# =============================================================================


class TestApiMemorySectionUpdate:
    """Tests pour PUT /api/memory/sections/<title>."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_section_update_success(self, client):
        """PUT /api/memory/sections/<title> met à jour la section."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.put(
                '/api/memory/sections/Section%201',
                data=json.dumps({
                    "content": "Updated section content",
                    "change_summary": "Updated section 1"
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "version_id" in data

    def test_api_memory_section_update_not_found(self, client):
        """PUT /api/memory/sections/<title> retourne 404 si non trouvée."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.put(
                '/api/memory/sections/NonexistentSection',
                data=json.dumps({"content": "New content"}),
                content_type='application/json'
            )

            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data


# =============================================================================
# TESTS API MEMORY SECTION ADD
# =============================================================================


class TestApiMemorySectionAdd:
    """Tests pour POST /api/memory/sections."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_section_add_success(self, client):
        """POST /api/memory/sections ajoute une nouvelle section."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory/sections',
                data=json.dumps({
                    "title": "New Section",
                    "content": "New section content",
                    "level": 2,
                    "position": "end"
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "version_id" in data

    def test_api_memory_section_add_minimal_params(self, client):
        """POST /api/memory/sections avec paramètres minimaux."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory/sections',
                data=json.dumps({
                    "title": "Minimal Section",
                    "content": "Content"
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True


# =============================================================================
# TESTS API MEMORY SECTION DELETE
# =============================================================================


class TestApiMemorySectionDelete:
    """Tests pour DELETE /api/memory/sections/<title>."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_section_delete_success(self, client):
        """DELETE /api/memory/sections/<title> supprime la section."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.delete('/api/memory/sections/Section%201')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "version_id" in data

    def test_api_memory_section_delete_not_found(self, client):
        """DELETE /api/memory/sections/<title> retourne 404 si non trouvée."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.delete('/api/memory/sections/NonexistentSection')

            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data


# =============================================================================
# TESTS API MEMORY SEARCH
# =============================================================================


class TestApiMemorySearch:
    """Tests pour GET /api/memory/search."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_search_success(self, client):
        """GET /api/memory/search retourne les résultats."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/search?q=Memory')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "results" in data
            assert "count" in data
            assert data["count"] >= 1

    def test_api_memory_search_no_results(self, client):
        """GET /api/memory/search sans résultats."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/search?q=nonexistent_xyz_123')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["results"] == []
            assert data["count"] == 0


# =============================================================================
# TESTS API MEMORY HISTORY
# =============================================================================


class TestApiMemoryHistory:
    """Tests pour GET /api/memory/history."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_history_success(self, client):
        """GET /api/memory/history retourne l'historique."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/history')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "history" in data
            assert "total" in data
            assert len(data["history"]) == 3
            assert data["total"] == 3

    def test_api_memory_history_with_pagination(self, client):
        """GET /api/memory/history avec limite et offset."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/history?limit=2&offset=1')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert len(data["history"]) == 2

    def test_api_memory_history_empty(self, client):
        """GET /api/memory/history avec historique vide."""
        mock_manager = MockMemoryManager()
        mock_manager.history = []

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/history')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["history"] == []
            assert data["total"] == 0


# =============================================================================
# TESTS API MEMORY EXPORT
# =============================================================================


class TestApiMemoryExport:
    """Tests pour GET /api/memory/export."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_export_markdown(self, client):
        """GET /api/memory/export format markdown."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/export?format=markdown')

            assert response.status_code == 200
            assert response.content_type == 'text/markdown; charset=utf-8'
            assert b"# Test Memory" in response.data

    def test_api_memory_export_json(self, client):
        """GET /api/memory/export format JSON."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/export?format=json')

            assert response.status_code == 200
            assert 'application/json' in response.content_type
            data = json.loads(response.data)
            assert "content" in data

    def test_api_memory_export_text(self, client):
        """GET /api/memory/export format text."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/export?format=text')

            assert response.status_code == 200
            assert response.content_type == 'text/plain; charset=utf-8'

    def test_api_memory_export_default_format(self, client):
        """GET /api/memory/export sans format spécifié (défaut markdown)."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.get('/api/memory/export')

            assert response.status_code == 200
            assert response.content_type == 'text/markdown; charset=utf-8'


# =============================================================================
# TESTS API MEMORY IMPORT
# =============================================================================


class TestApiMemoryImport:
    """Tests pour POST /api/memory/import."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_import_success(self, client):
        """POST /api/memory/import importe le contenu."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory/import',
                data=json.dumps({
                    "content": "# Imported Memory\nImported content.",
                    "merge": False
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "version_id" in data

    def test_api_memory_import_merge(self, client):
        """POST /api/memory/import avec merge=True."""
        mock_manager = MockMemoryManager()

        with patch('app.memory_manager.get_memory_manager', return_value=mock_manager):
            response = client.post(
                '/api/memory/import',
                data=json.dumps({
                    "content": "Additional content to merge.",
                    "merge": True
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True


# =============================================================================
# TESTS API EXPORT TRAINING & CSV
# =============================================================================


class TestApiExportEndpoints:
    """Tests pour les endpoints d'export."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_export_training_success(self, client):
        """GET /api/export-training retourne les données d'entraînement."""
        mock_history = Mock()
        mock_history.export_for_training.return_value = {
            "pairs": [
                {"input": "Email 1", "output": "Response 1"},
                {"input": "Email 2", "output": "Response 2"}
            ],
            "count": 2
        }

        with patch('app.dashboard.get_container') as mock_container:
            mock_c = Mock()
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.get('/api/export-training')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "pairs" in data
            assert data["count"] == 2

    def test_api_export_csv_success(self, client):
        """GET /api/export-csv retourne un fichier CSV."""
        mock_history = Mock()
        mock_history.export_csv.return_value = "id,subject,status\n1,Test,V1\n2,Test2,V2"

        with patch('app.dashboard.get_container') as mock_container:
            mock_c = Mock()
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.get('/api/export-csv')

            assert response.status_code == 200
            assert response.content_type == 'text/csv; charset=utf-8'
            assert b"id,subject,status" in response.data
            assert response.headers["Content-Disposition"] == "attachment; filename=agentys_export.csv"


# =============================================================================
# TESTS API DRAFT SUCCESS PATH
# =============================================================================


@dataclass
class MockDraftRecord:
    """Mock pour un enregistrement de brouillon."""
    id: str = "test-draft-123"
    email_subject: str = "Test Subject"
    email_preview: str = "Preview text..."
    draft_final: str = "Draft content"
    critique: str = "Critique text"
    feedback: str = "User feedback"
    feedback_rating: int = 5


class TestApiDraftSuccessPath:
    """Tests pour GET /api/draft/<id> - cas de succès."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_draft_found(self, client):
        """GET /api/draft/<id> retourne le draft si trouvé."""
        mock_draft = MockDraftRecord()

        mock_history = Mock()
        # Route utilise get_by_id_for_account (scoped), cf dashboard.py:1520
        mock_history.get_by_id_for_account.return_value = mock_draft
        mock_history.get_by_id.return_value = mock_draft

        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.get('/api/draft/test-draft-123')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["id"] == "test-draft-123"
            assert data["email_subject"] == "Test Subject"


# =============================================================================
# TESTS RETENTION STATS SUCCESS PATH
# =============================================================================


class TestRetentionStatsSuccessPath:
    """Tests pour get_retention_stats - cas de succès."""

    def test_retention_stats_success(self):
        """get_retention_stats retourne les stats du manager."""
        mock_manager = Mock()
        mock_manager.get_retention_stats.return_value = {
            "retention_days": 30,
            "total_items": 100,
            "expired_items": 5
        }

        with patch('app.dashboard.get_data_retention_manager', return_value=mock_manager):
            from app.dashboard import get_retention_stats

            stats = get_retention_stats()

            assert stats["retention_days"] == 30
            assert stats["total_items"] == 100
            assert stats["expired_items"] == 5


# =============================================================================
# TESTS BROADCAST STATS UPDATE SUCCESS PATH
# =============================================================================


class TestBroadcastStatsUpdateSuccessPath:
    """Tests pour broadcast_stats_update - cas de succès."""

    def test_broadcast_stats_update_success(self):
        """broadcast_stats_update émet les stats via socketio."""
        mock_socketio = Mock()
        mock_history = Mock()
        mock_history.get_stats.return_value = {
            "total": 100,
            "validated_v1": 80,
            "corrected_v2": 20
        }

        with patch('app.dashboard.socketio', mock_socketio):
            with patch('app.dashboard.get_container') as mock_container:
                mock_c = Mock()
                mock_c.get_draft_history.return_value = mock_history
                mock_container.return_value = mock_c

                from app.dashboard import broadcast_stats_update

                broadcast_stats_update()

                mock_socketio.emit.assert_called_once_with("stats_update", {
                    "total": 100,
                    "validated_v1": 80,
                    "corrected_v2": 20
                })


# =============================================================================
# TESTS VALIDATION FUNCTIONS
# =============================================================================


class TestValidationFunctions:
    """Tests pour les fonctions de validation."""

    def test_validate_draft_id_empty(self):
        """_validate_draft_id retourne False pour chaîne vide."""
        from app.dashboard import _validate_draft_id

        assert _validate_draft_id("") is False

    def test_validate_draft_id_none(self):
        """_validate_draft_id retourne False pour None."""
        from app.dashboard import _validate_draft_id

        assert _validate_draft_id(None) is False

    def test_validate_draft_id_too_long(self):
        """_validate_draft_id retourne False pour ID trop long."""
        from app.dashboard import _validate_draft_id

        long_id = "a" * 257
        assert _validate_draft_id(long_id) is False

    def test_validate_draft_id_valid(self):
        """_validate_draft_id retourne True pour ID valide."""
        from app.dashboard import _validate_draft_id

        assert _validate_draft_id("valid-id-123") is True
        assert _validate_draft_id("valid_id_123") is True
        assert _validate_draft_id("UPPERCASE") is True

    def test_validate_feedback_not_string(self):
        """_validate_feedback retourne False si pas une string."""
        from app.dashboard import _validate_feedback

        assert _validate_feedback(123) is False
        assert _validate_feedback(None) is False
        assert _validate_feedback(["list"]) is False

    def test_validate_feedback_too_long(self):
        """_validate_feedback retourne False si trop long."""
        from app.dashboard import _validate_feedback

        long_feedback = "a" * 10001
        assert _validate_feedback(long_feedback) is False

    def test_validate_feedback_valid(self):
        """_validate_feedback retourne True pour feedback valide."""
        from app.dashboard import _validate_feedback

        assert _validate_feedback("Valid feedback") is True
        assert _validate_feedback("a" * 10000) is True
        assert _validate_feedback("") is True  # Empty string is valid
