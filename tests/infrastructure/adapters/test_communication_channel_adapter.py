# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests TDD pour CommunicationChannelAdapter (SQLite).

Ce module teste:
1. Implementation du port CommunicationChannelPort
2. Operations CRUD (save, get_by_id, get_all, delete)
3. Filtres (get_by_type)
4. Mises a jour (update_metrics, update_status)
5. Serialisation/deserialisation des enums et JSON
6. Edge cases et gestion des erreurs

TDD: Tests ecrits AVANT l'implementation.
Clean Architecture: Infrastructure layer (Adapters).
"""

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.domain.entities.communication_channel import (
    CommunicationChannel,
    ChannelConfig,
    ChannelMetrics,
    ChannelType,
    ChannelStatus,
)
from app.domain.ports.communication_channel_port import CommunicationChannelPort


# =============================================================================
# MODULE LOADING HELPER
# =============================================================================


def _load_communication_channel_adapter_class():
    """
    Charge CommunicationChannelAdapter sans passer par app.infrastructure.__init__.py.

    Cela evite les effets de bord (chargement du container, config, etc.)
    qui requierent des variables d'environnement.
    """
    spec = importlib.util.spec_from_file_location(
        "communication_channel_adapter",
        "app/infrastructure/adapters/communication_channel_adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CommunicationChannelAdapter


CommunicationChannelAdapter = _load_communication_channel_adapter_class()


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_db(tmp_path) -> Path:
    """Cree une base de donnees temporaire."""
    return tmp_path / "test_channels.db"


@pytest.fixture
def adapter():
    """Cree un adapter avec base en memoire."""
    return CommunicationChannelAdapter()


@pytest.fixture
def sample_config() -> ChannelConfig:
    """Cree une configuration de test."""
    return ChannelConfig(
        credentials={"api_key": "test-key-123", "secret": "secret-456"},
        endpoint="https://api.example.com",
        webhook_url="https://webhook.example.com/hook",
        settings={"timeout": 30, "retry": True},
    )


@pytest.fixture
def sample_channel(sample_config) -> CommunicationChannel:
    """Cree un canal de test."""
    return CommunicationChannel(
        id="550e8400-e29b-41d4-a716-446655440000",
        channel_type=ChannelType.EMAIL,
        name="Canal Email Principal",
        config=sample_config,
        status=ChannelStatus.ACTIVE,
        metrics=ChannelMetrics(
            messages_sent=100,
            messages_received=50,
            last_used_at=datetime(2024, 1, 15, 10, 30, 0),
            error_count=2,
        ),
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 15, 12, 0, 0),
    )


@pytest.fixture
def minimal_channel() -> CommunicationChannel:
    """Canal avec configuration minimale."""
    return CommunicationChannel(
        id="660e8400-e29b-41d4-a716-446655440001",
        channel_type=ChannelType.DISCORD,
        name="Discord Bot",
        config=ChannelConfig(credentials={"token": "discord-token"}),
    )


# =============================================================================
# TESTS - IMPLEMENTS PORT
# =============================================================================


class TestCommunicationChannelAdapterImplementsPort:
    """Tests pour verifier l'implementation du port."""

    def test_implements_communication_channel_port(self, adapter):
        """CommunicationChannelAdapter implemente CommunicationChannelPort."""
        assert isinstance(adapter, CommunicationChannelPort)

    def test_has_all_required_methods(self, adapter):
        """A toutes les methodes abstraites requises."""
        assert hasattr(adapter, "save")
        assert hasattr(adapter, "get_by_id")
        assert hasattr(adapter, "get_by_type")
        assert hasattr(adapter, "get_all")
        assert hasattr(adapter, "delete")
        assert hasattr(adapter, "update_metrics")
        assert hasattr(adapter, "update_status")


# =============================================================================
# TESTS - SAVE
# =============================================================================


class TestSave:
    """Tests pour save."""

    def test_save_persists_channel(self, adapter, sample_channel):
        """save persiste le canal."""
        adapter.save(sample_channel)
        result = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert result is not None
        assert result.id == "550e8400-e29b-41d4-a716-446655440000"

    def test_save_returns_channel(self, adapter, sample_channel):
        """save retourne le canal persiste."""
        result = adapter.save(sample_channel)
        assert isinstance(result, CommunicationChannel)
        assert result.id == sample_channel.id

    def test_save_stores_all_fields(self, adapter, sample_channel):
        """Tous les champs sont persistes."""
        adapter.save(sample_channel)
        result = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")

        assert result.channel_type == ChannelType.EMAIL
        assert result.name == "Canal Email Principal"
        assert result.status == ChannelStatus.ACTIVE
        assert result.config.credentials == {"api_key": "test-key-123", "secret": "secret-456"}
        assert result.config.endpoint == "https://api.example.com"
        assert result.config.webhook_url == "https://webhook.example.com/hook"
        assert result.config.settings == {"timeout": 30, "retry": True}
        assert result.metrics.messages_sent == 100
        assert result.metrics.messages_received == 50
        assert result.metrics.error_count == 2
        assert result.created_at == datetime(2024, 1, 1, 0, 0, 0)
        assert result.updated_at == datetime(2024, 1, 15, 12, 0, 0)

    def test_save_minimal_channel(self, adapter, minimal_channel):
        """Fonctionne avec configuration minimale."""
        adapter.save(minimal_channel)
        result = adapter.get_by_id("660e8400-e29b-41d4-a716-446655440001")

        assert result is not None
        assert result.channel_type == ChannelType.DISCORD
        assert result.config.endpoint is None
        assert result.config.webhook_url is None
        assert result.config.settings == {}
        assert result.metrics.messages_sent == 0
        assert result.metrics.messages_received == 0
        assert result.metrics.last_used_at is None
        assert result.metrics.error_count == 0
        assert result.status == ChannelStatus.PENDING_SETUP

    def test_save_multiple_channels(self, adapter, sample_channel, minimal_channel):
        """Sauvegarde plusieurs canaux."""
        adapter.save(sample_channel)
        adapter.save(minimal_channel)

        assert len(adapter.get_all()) == 2

    def test_save_updates_existing(self, adapter, sample_channel):
        """save met a jour un canal existant."""
        adapter.save(sample_channel)

        updated_channel = CommunicationChannel(
            id=sample_channel.id,
            channel_type=sample_channel.channel_type,
            name="Nouveau Nom",
            config=sample_channel.config,
            status=ChannelStatus.INACTIVE,
            metrics=sample_channel.metrics,
        )
        adapter.save(updated_channel)

        result = adapter.get_by_id(sample_channel.id)
        assert result.name == "Nouveau Nom"
        assert result.status == ChannelStatus.INACTIVE
        assert len(adapter.get_all()) == 1


# =============================================================================
# TESTS - GET BY ID
# =============================================================================


class TestGetById:
    """Tests pour get_by_id."""

    def test_get_by_id_returns_channel(self, adapter, sample_channel):
        """Retourne le canal trouve."""
        adapter.save(sample_channel)
        result = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert result is not None
        assert isinstance(result, CommunicationChannel)

    def test_get_by_id_returns_none_if_not_found(self, adapter):
        """Retourne None si non trouve."""
        result = adapter.get_by_id("non-existent-id")
        assert result is None

    def test_get_by_id_returns_correct_channel(self, adapter, sample_channel, minimal_channel):
        """Retourne le bon canal parmi plusieurs."""
        adapter.save(sample_channel)
        adapter.save(minimal_channel)

        result = adapter.get_by_id(minimal_channel.id)
        assert result.name == "Discord Bot"


# =============================================================================
# TESTS - GET BY TYPE
# =============================================================================


class TestGetByType:
    """Tests pour get_by_type."""

    def test_get_by_type_filters_correctly(self, adapter):
        """Filtre par type de canal."""
        email1 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Email 1",
            config=ChannelConfig(credentials={"key": "1"}),
        )
        email2 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.EMAIL,
            name="Email 2",
            config=ChannelConfig(credentials={"key": "2"}),
        )
        discord = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440003",
            channel_type=ChannelType.DISCORD,
            name="Discord",
            config=ChannelConfig(credentials={"token": "abc"}),
        )

        adapter.save(email1)
        adapter.save(email2)
        adapter.save(discord)

        result = adapter.get_by_type(ChannelType.EMAIL)
        assert len(result) == 2
        assert all(c.channel_type == ChannelType.EMAIL for c in result)

    def test_get_by_type_returns_empty_if_no_match(self, adapter, sample_channel):
        """Retourne liste vide si aucun match."""
        adapter.save(sample_channel)
        result = adapter.get_by_type(ChannelType.SMS)
        assert result == []

    def test_get_by_type_all_types(self, adapter):
        """Teste tous les types de canaux."""
        for i, channel_type in enumerate(ChannelType):
            channel = CommunicationChannel(
                id=f"550e8400-e29b-41d4-a716-44665544000{i}",
                channel_type=channel_type,
                name=f"Canal {channel_type.value}",
                config=ChannelConfig(credentials={"key": str(i)}),
            )
            adapter.save(channel)

        for channel_type in ChannelType:
            result = adapter.get_by_type(channel_type)
            assert len(result) == 1
            assert result[0].channel_type == channel_type


# =============================================================================
# TESTS - GET ALL
# =============================================================================


class TestGetAll:
    """Tests pour get_all."""

    def test_get_all_returns_empty_list_initially(self, adapter):
        """Retourne une liste vide si aucun canal."""
        assert adapter.get_all() == []

    def test_get_all_returns_all_channels(self, adapter):
        """Retourne tous les canaux."""
        for i in range(5):
            channel = CommunicationChannel(
                id=f"550e8400-e29b-41d4-a716-44665544000{i}",
                channel_type=ChannelType.EMAIL,
                name=f"Canal {i}",
                config=ChannelConfig(credentials={"key": str(i)}),
            )
            adapter.save(channel)

        result = adapter.get_all()
        assert len(result) == 5

    def test_get_all_returns_channel_instances(self, adapter, sample_channel):
        """Retourne des instances de CommunicationChannel."""
        adapter.save(sample_channel)
        result = adapter.get_all()
        assert all(isinstance(c, CommunicationChannel) for c in result)


# =============================================================================
# TESTS - DELETE
# =============================================================================


class TestDelete:
    """Tests pour delete."""

    def test_delete_removes_channel(self, adapter, sample_channel):
        """delete supprime le canal."""
        adapter.save(sample_channel)
        result = adapter.delete(sample_channel.id)

        assert result is True
        assert adapter.get_by_id(sample_channel.id) is None

    def test_delete_returns_false_if_not_found(self, adapter):
        """delete retourne False si non trouve."""
        result = adapter.delete("non-existent-id")
        assert result is False

    def test_delete_only_removes_specified(self, adapter, sample_channel, minimal_channel):
        """delete ne supprime que le canal specifie."""
        adapter.save(sample_channel)
        adapter.save(minimal_channel)

        adapter.delete(sample_channel.id)

        assert adapter.get_by_id(minimal_channel.id) is not None
        assert len(adapter.get_all()) == 1


# =============================================================================
# TESTS - UPDATE METRICS
# =============================================================================


class TestUpdateMetrics:
    """Tests pour update_metrics."""

    def test_update_metrics_success(self, adapter, sample_channel):
        """update_metrics met a jour les metriques."""
        adapter.save(sample_channel)

        new_metrics = ChannelMetrics(
            messages_sent=200,
            messages_received=100,
            last_used_at=datetime(2024, 1, 20, 15, 0, 0),
            error_count=5,
        )
        result = adapter.update_metrics(sample_channel.id, new_metrics)

        assert result is True
        channel = adapter.get_by_id(sample_channel.id)
        assert channel.metrics.messages_sent == 200
        assert channel.metrics.messages_received == 100
        assert channel.metrics.last_used_at == datetime(2024, 1, 20, 15, 0, 0)
        assert channel.metrics.error_count == 5

    def test_update_metrics_returns_false_if_not_found(self, adapter):
        """update_metrics retourne False si non trouve."""
        new_metrics = ChannelMetrics(messages_sent=1)
        result = adapter.update_metrics("non-existent", new_metrics)
        assert result is False

    def test_update_metrics_preserves_other_fields(self, adapter, sample_channel):
        """update_metrics ne modifie que les metriques."""
        adapter.save(sample_channel)

        new_metrics = ChannelMetrics(messages_sent=999)
        adapter.update_metrics(sample_channel.id, new_metrics)

        channel = adapter.get_by_id(sample_channel.id)
        assert channel.name == sample_channel.name
        assert channel.status == sample_channel.status
        assert channel.config.credentials == sample_channel.config.credentials


# =============================================================================
# TESTS - UPDATE STATUS
# =============================================================================


class TestUpdateStatus:
    """Tests pour update_status."""

    def test_update_status_success(self, adapter, sample_channel):
        """update_status met a jour le statut."""
        adapter.save(sample_channel)

        result = adapter.update_status(sample_channel.id, ChannelStatus.ERROR)

        assert result is True
        channel = adapter.get_by_id(sample_channel.id)
        assert channel.status == ChannelStatus.ERROR

    def test_update_status_returns_false_if_not_found(self, adapter):
        """update_status retourne False si non trouve."""
        result = adapter.update_status("non-existent", ChannelStatus.ACTIVE)
        assert result is False

    def test_update_status_all_statuses(self, adapter, minimal_channel):
        """Teste tous les statuts."""
        adapter.save(minimal_channel)

        for status in ChannelStatus:
            result = adapter.update_status(minimal_channel.id, status)
            assert result is True
            channel = adapter.get_by_id(minimal_channel.id)
            assert channel.status == status


# =============================================================================
# TESTS - SERIALIZATION
# =============================================================================


class TestSerialization:
    """Tests pour la serialisation/deserialisation."""

    def test_channel_type_roundtrip(self, adapter):
        """Roundtrip pour tous les ChannelType."""
        for i, channel_type in enumerate(ChannelType):
            channel = CommunicationChannel(
                id=f"550e8400-e29b-41d4-a716-44665544{i:04d}",
                channel_type=channel_type,
                name=f"Test {channel_type.value}",
                config=ChannelConfig(credentials={"key": "value"}),
            )
            adapter.save(channel)
            result = adapter.get_by_id(channel.id)
            assert result.channel_type == channel_type

    def test_channel_status_roundtrip(self, adapter):
        """Roundtrip pour tous les ChannelStatus."""
        for i, status in enumerate(ChannelStatus):
            channel = CommunicationChannel(
                id=f"550e8400-e29b-41d4-a716-44665544{i:04d}",
                channel_type=ChannelType.EMAIL,
                name=f"Test {status.value}",
                config=ChannelConfig(credentials={"key": "value"}),
                status=status,
            )
            adapter.save(channel)
            result = adapter.get_by_id(channel.id)
            assert result.status == status

    def test_json_credentials_roundtrip(self, adapter):
        """Roundtrip pour credentials JSON complexes."""
        complex_credentials = {
            "api_key": "key-123",
            "nested": {"level1": {"level2": "value"}},
            "list": [1, 2, 3],
            "boolean": True,
            "null_value": None,
        }
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440099",
            channel_type=ChannelType.EMAIL,
            name="Complex Config",
            config=ChannelConfig(credentials=complex_credentials),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.credentials == complex_credentials

    def test_json_settings_roundtrip(self, adapter):
        """Roundtrip pour settings JSON complexes."""
        complex_settings = {
            "timeout": 30,
            "retries": {"max": 3, "delay": 1.5},
            "features": ["a", "b", "c"],
        }
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440098",
            channel_type=ChannelType.EMAIL,
            name="Complex Settings",
            config=ChannelConfig(
                credentials={"key": "value"},
                settings=complex_settings,
            ),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.settings == complex_settings

    def test_datetime_roundtrip(self, adapter):
        """Roundtrip pour les datetime."""
        now = datetime(2024, 6, 15, 14, 30, 45)
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440097",
            channel_type=ChannelType.EMAIL,
            name="Datetime Test",
            config=ChannelConfig(credentials={"key": "value"}),
            metrics=ChannelMetrics(last_used_at=now),
            created_at=now,
            updated_at=now,
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.metrics.last_used_at == now
        assert result.created_at == now
        assert result.updated_at == now


# =============================================================================
# TESTS - EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests des cas limites."""

    def test_unicode_in_name(self, adapter):
        """Supporte l'Unicode dans le nom."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Canal avec emojis et japonais",
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert "japonais" in result.name

    def test_special_characters_in_credentials(self, adapter):
        """Supporte les caracteres speciaux dans credentials."""
        credentials = {
            "api_key": "key'with\"quotes",
            "path": "C:\\Users\\test",
            "html": "<script>alert('xss')</script>",
        }
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.EMAIL,
            name="Special Chars",
            config=ChannelConfig(credentials=credentials),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.credentials == credentials

    def test_empty_settings(self, adapter):
        """Supporte des settings vides."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440003",
            channel_type=ChannelType.EMAIL,
            name="Empty Settings",
            config=ChannelConfig(credentials={"key": "value"}, settings={}),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.settings == {}

    def test_null_optional_fields(self, adapter):
        """Gere correctement les champs optionnels null."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440004",
            channel_type=ChannelType.EMAIL,
            name="Null Fields",
            config=ChannelConfig(
                credentials={"key": "value"},
                endpoint=None,
                webhook_url=None,
            ),
            created_at=None,
            updated_at=None,
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.endpoint is None
        assert result.config.webhook_url is None
        assert result.created_at is None
        assert result.updated_at is None

    def test_sql_injection_in_name(self, adapter):
        """Protege contre l'injection SQL dans le nom."""
        malicious_name = "'; DROP TABLE communication_channels; --"
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440005",
            channel_type=ChannelType.EMAIL,
            name=malicious_name,
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)

        result = adapter.get_by_id(channel.id)
        assert result is not None
        assert result.name == malicious_name
        assert adapter.get_all() is not None

    def test_sql_injection_in_id(self, adapter):
        """Protege contre l'injection SQL dans l'ID."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440006",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)

        malicious_id = "test'; DELETE FROM communication_channels WHERE '1'='1"
        result = adapter.get_by_id(malicious_id)
        assert result is None
        assert len(adapter.get_all()) == 1

    def test_very_long_name(self, adapter):
        """Supporte des noms de 100 caracteres (limite de l'entite)."""
        long_name = "A" * 100
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440007",
            channel_type=ChannelType.EMAIL,
            name=long_name,
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)

        result = adapter.get_by_id(channel.id)
        assert len(result.name) == 100

    def test_large_credentials_dict(self, adapter):
        """Supporte de gros dictionnaires de credentials."""
        large_credentials = {f"key_{i}": f"value_{i}" for i in range(100)}
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440008",
            channel_type=ChannelType.EMAIL,
            name="Large Credentials",
            config=ChannelConfig(credentials=large_credentials),
        )
        adapter.save(channel)

        result = adapter.get_by_id(channel.id)
        assert len(result.config.credentials) == 100


# =============================================================================
# TESTS - TABLE CREATION
# =============================================================================


class TestTableCreation:
    """Tests pour la creation de table."""

    def test_creates_table_on_init(self, adapter):
        """La table est creee a l'initialisation."""
        conn = adapter._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='communication_channels'"
        )
        result = cursor.fetchone()
        assert result is not None

    def test_table_has_correct_columns(self, adapter):
        """La table a les bonnes colonnes."""
        conn = adapter._get_connection()
        cursor = conn.execute("PRAGMA table_info(communication_channels)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "channel_type", "name",
            "config_credentials", "config_endpoint", "config_webhook_url", "config_settings",
            "status",
            "messages_sent", "messages_received", "last_used_at", "error_count",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)


# =============================================================================
# TESTS - DB PATH PARAMETER
# =============================================================================


class TestDbPathParameter:
    """Tests pour le parametre db_path du constructeur."""

    def test_adapter_with_file_db(self, tmp_path):
        """L'adapter fonctionne avec un fichier DB."""
        db_path = tmp_path / "test.db"
        adapter = CommunicationChannelAdapter(db_path=db_path)

        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="File Test",
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)

        assert db_path.exists()

        adapter2 = CommunicationChannelAdapter(db_path=db_path)
        result = adapter2.get_by_id(channel.id)
        assert result is not None
        assert result.name == "File Test"

    def test_adapter_memory_db_isolated(self):
        """Chaque adapter avec :memory: est isole."""
        adapter1 = CommunicationChannelAdapter()
        adapter2 = CommunicationChannelAdapter()

        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Isolated Test",
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter1.save(channel)

        assert adapter2.get_by_id(channel.id) is None


# =============================================================================
# TESTS - CONCURRENT ACCESS
# =============================================================================


class TestConcurrentAccess:
    """Tests pour l'acces concurrent."""

    def test_multiple_saves_same_adapter(self, adapter):
        """Sauvegardes multiples sur le meme adapter."""
        for i in range(100):
            channel = CommunicationChannel(
                id=f"550e8400-e29b-41d4-a716-4466554{i:05d}",
                channel_type=ChannelType.EMAIL,
                name=f"Channel {i}",
                config=ChannelConfig(credentials={"key": str(i)}),
            )
            adapter.save(channel)

        assert len(adapter.get_all()) == 100

    def test_mixed_operations(self, adapter):
        """Operations mixtes (save, get, update, delete)."""
        channel1 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Channel 1",
            config=ChannelConfig(credentials={"key": "1"}),
        )
        adapter.save(channel1)

        result = adapter.get_by_id(channel1.id)
        assert result is not None

        adapter.update_status(channel1.id, ChannelStatus.ERROR)

        channel2 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.DISCORD,
            name="Channel 2",
            config=ChannelConfig(credentials={"key": "2"}),
        )
        adapter.save(channel2)

        adapter.delete(channel1.id)

        assert len(adapter.get_all()) == 1
        assert adapter.get_by_id(channel2.id) is not None


# =============================================================================
# TESTS - INVALID DATA HANDLING
# =============================================================================


class TestInvalidDataHandling:
    """Tests pour la gestion des donnees invalides."""

    def test_invalid_channel_type_in_db_raises(self, adapter):
        """Un channel_type invalide dans la DB leve une exception."""
        conn = adapter._get_connection()
        # Les credentials doivent etre chiffres via l'encryption manager
        encrypted_creds = adapter._encryption.encrypt_dict({"key": "value"})
        conn.execute(
            """
            INSERT INTO communication_channels
            (id, channel_type, name, config_credentials, status,
             messages_sent, messages_received, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-type-id",
                "INVALID_TYPE",
                "Test",
                encrypted_creds,
                "active",
                0, 0, 0,
            ),
        )
        conn.commit()

        with pytest.raises(ValueError):
            adapter.get_by_id("invalid-type-id")

    def test_invalid_status_in_db_raises(self, adapter):
        """Un status invalide dans la DB leve une exception."""
        conn = adapter._get_connection()
        # Les credentials doivent etre chiffres via l'encryption manager
        encrypted_creds = adapter._encryption.encrypt_dict({"key": "value"})
        conn.execute(
            """
            INSERT INTO communication_channels
            (id, channel_type, name, config_credentials, status,
             messages_sent, messages_received, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-status-id",
                "email",
                "Test",
                encrypted_creds,
                "BOGUS_STATUS",
                0, 0, 0,
            ),
        )
        conn.commit()

        with pytest.raises(ValueError):
            adapter.get_by_id("invalid-status-id")

    def test_invalid_json_credentials_raises(self, adapter):
        """Des credentials non-chiffres/invalides levent une exception."""
        from cryptography.fernet import InvalidToken
        conn = adapter._get_connection()
        # Insertion de donnees non-chiffrees (simulation de corruption)
        conn.execute(
            """
            INSERT INTO communication_channels
            (id, channel_type, name, config_credentials, status,
             messages_sent, messages_received, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-json-id",
                "email",
                "Test",
                "not valid encrypted data",
                "active",
                0, 0, 0,
            ),
        )
        conn.commit()

        # Les donnees non-chiffrees levent InvalidToken lors du dechiffrement
        with pytest.raises((InvalidToken, Exception)):
            adapter.get_by_id("invalid-json-id")

    def test_invalid_json_settings_raises(self, adapter):
        """Des settings JSON invalides levent une exception."""
        conn = adapter._get_connection()
        # Les credentials doivent etre chiffres via l'encryption manager
        encrypted_creds = adapter._encryption.encrypt_dict({"key": "value"})
        conn.execute(
            """
            INSERT INTO communication_channels
            (id, channel_type, name, config_credentials, config_settings, status,
             messages_sent, messages_received, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-settings-json-id",
                "email",
                "Test",
                encrypted_creds,
                "not valid json{",
                "active",
                0, 0, 0,
            ),
        )
        conn.commit()

        with pytest.raises(json.JSONDecodeError):
            adapter.get_by_id("invalid-settings-json-id")


# =============================================================================
# TESTS - ADDITIONAL EDGE CASES
# =============================================================================


class TestAdditionalEdgeCases:
    """Tests supplementaires pour les cas limites."""

    def test_empty_string_id_get_by_id(self, adapter):
        """get_by_id avec ID vide retourne None."""
        result = adapter.get_by_id("")
        assert result is None

    def test_empty_string_id_delete(self, adapter):
        """delete avec ID vide retourne False."""
        result = adapter.delete("")
        assert result is False

    def test_empty_credentials_dict(self, adapter):
        """Supporte un dictionnaire credentials vide."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440010",
            channel_type=ChannelType.EMAIL,
            name="Empty Credentials",
            config=ChannelConfig(credentials={}),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.credentials == {}

    def test_update_metrics_with_null_last_used_at(self, adapter, sample_channel):
        """update_metrics peut mettre last_used_at a None."""
        adapter.save(sample_channel)
        assert adapter.get_by_id(sample_channel.id).metrics.last_used_at is not None

        new_metrics = ChannelMetrics(
            messages_sent=0,
            messages_received=0,
            last_used_at=None,
            error_count=0,
        )
        result = adapter.update_metrics(sample_channel.id, new_metrics)

        assert result is True
        channel = adapter.get_by_id(sample_channel.id)
        assert channel.metrics.last_used_at is None

    def test_metrics_with_zero_values(self, adapter):
        """Supporte des metriques a zero."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440012",
            channel_type=ChannelType.EMAIL,
            name="Zero Metrics",
            config=ChannelConfig(credentials={"key": "value"}),
            metrics=ChannelMetrics(
                messages_sent=0,
                messages_received=0,
                error_count=0,
            ),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.metrics.messages_sent == 0
        assert result.metrics.messages_received == 0
        assert result.metrics.error_count == 0

    def test_metrics_with_large_values(self, adapter):
        """Supporte des metriques avec de grandes valeurs."""
        large_value = 2**31 - 1  # Max 32-bit signed int
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440013",
            channel_type=ChannelType.EMAIL,
            name="Large Metrics",
            config=ChannelConfig(credentials={"key": "value"}),
            metrics=ChannelMetrics(
                messages_sent=large_value,
                messages_received=large_value,
                error_count=large_value,
            ),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.metrics.messages_sent == large_value
        assert result.metrics.messages_received == large_value
        assert result.metrics.error_count == large_value

    def test_save_overwrites_existing_channel(self, adapter):
        """save ecrase completement un canal existant avec le meme ID."""
        original = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440014",
            channel_type=ChannelType.EMAIL,
            name="Original",
            config=ChannelConfig(
                credentials={"original": "creds"},
                endpoint="https://original.com",
                webhook_url="https://webhook.original.com",
                settings={"original": True},
            ),
            status=ChannelStatus.ACTIVE,
            metrics=ChannelMetrics(messages_sent=100),
        )
        adapter.save(original)

        replacement = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440014",
            channel_type=ChannelType.DISCORD,
            name="Replacement",
            config=ChannelConfig(
                credentials={"new": "creds"},
                endpoint=None,
                webhook_url=None,
                settings={},
            ),
            status=ChannelStatus.INACTIVE,
            metrics=ChannelMetrics(messages_sent=0),
        )
        adapter.save(replacement)

        result = adapter.get_by_id(original.id)
        assert result.channel_type == ChannelType.DISCORD
        assert result.name == "Replacement"
        assert result.config.credentials == {"new": "creds"}
        assert result.config.endpoint is None
        assert result.status == ChannelStatus.INACTIVE
        assert result.metrics.messages_sent == 0
        assert len(adapter.get_all()) == 1

    def test_special_unicode_characters(self, adapter):
        """Supporte les caracteres Unicode speciaux."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440015",
            channel_type=ChannelType.EMAIL,
            name="Canal avec emoji \U0001f600 et japonais \u3053\u3093\u306b\u3061\u306f",
            config=ChannelConfig(
                credentials={"emoji_key": "\U0001f511", "japanese": "\u65e5\u672c\u8a9e"},
                endpoint="https://\u4f8b.jp/api",
            ),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert "\U0001f600" in result.name
        assert "\u3053\u3093\u306b\u3061\u306f" in result.name
        assert result.config.credentials["emoji_key"] == "\U0001f511"

    def test_null_in_json_credentials(self, adapter):
        """Supporte null comme valeur dans credentials."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440016",
            channel_type=ChannelType.EMAIL,
            name="Null Values",
            config=ChannelConfig(
                credentials={"key": None, "nested": {"also_null": None}},
            ),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert result.config.credentials["key"] is None
        assert result.config.credentials["nested"]["also_null"] is None

    def test_update_status_preserves_other_fields(self, adapter, sample_channel):
        """update_status ne modifie que le statut."""
        adapter.save(sample_channel)

        adapter.update_status(sample_channel.id, ChannelStatus.ERROR)

        channel = adapter.get_by_id(sample_channel.id)
        assert channel.status == ChannelStatus.ERROR
        assert channel.name == sample_channel.name
        assert channel.metrics.messages_sent == sample_channel.metrics.messages_sent
        assert channel.config.credentials == sample_channel.config.credentials

    def test_get_by_type_with_mixed_types(self, adapter):
        """get_by_type retourne uniquement le type demande parmi plusieurs types."""
        for i, channel_type in enumerate(ChannelType):
            for j in range(2):
                channel = CommunicationChannel(
                    id=f"550e8400-e29b-41d4-a716-4466554400{i}{j}",
                    channel_type=channel_type,
                    name=f"Canal {channel_type.value} {j}",
                    config=ChannelConfig(credentials={"key": str(j)}),
                )
                adapter.save(channel)

        for channel_type in ChannelType:
            result = adapter.get_by_type(channel_type)
            assert len(result) == 2
            assert all(c.channel_type == channel_type for c in result)

    def test_newlines_in_name(self, adapter):
        """Supporte les retours a la ligne dans le nom."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440017",
            channel_type=ChannelType.EMAIL,
            name="Line1\nLine2\rLine3\r\nLine4",
            config=ChannelConfig(credentials={"key": "value"}),
        )
        adapter.save(channel)
        result = adapter.get_by_id(channel.id)
        assert "\n" in result.name
        assert "\r" in result.name

    def test_get_all_order_is_consistent(self, adapter):
        """get_all retourne les canaux dans un ordre reproductible."""
        ids = [f"550e8400-e29b-41d4-a716-4466554400{i:02d}" for i in range(10)]
        for id_ in ids:
            channel = CommunicationChannel(
                id=id_,
                channel_type=ChannelType.EMAIL,
                name=f"Canal {id_}",
                config=ChannelConfig(credentials={"key": "value"}),
            )
            adapter.save(channel)

        result1 = [c.id for c in adapter.get_all()]
        result2 = [c.id for c in adapter.get_all()]
        assert result1 == result2
