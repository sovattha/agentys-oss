# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour CommunicationChannelPort."""

from dataclasses import replace

import pytest
from abc import ABC
from typing import List, Optional

from app.domain.ports.communication_channel_port import CommunicationChannelPort
from app.domain.entities.communication_channel import (
    CommunicationChannel,
    ChannelType,
    ChannelStatus,
    ChannelConfig,
    ChannelMetrics,
)


# =============================================================================
# Tests CommunicationChannelPort is Abstract
# =============================================================================


class TestCommunicationChannelPortIsAbstract:
    """Verifie que CommunicationChannelPort est une interface abstraite."""

    def test_inherits_from_abc(self):
        assert issubclass(CommunicationChannelPort, ABC)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            CommunicationChannelPort()


# =============================================================================
# Tests CommunicationChannelPort Has Methods
# =============================================================================


class TestCommunicationChannelPortHasMethods:
    """Verifie que le port a toutes les methodes requises."""

    def test_has_save_method(self):
        assert hasattr(CommunicationChannelPort, "save")

    def test_has_get_by_id_method(self):
        assert hasattr(CommunicationChannelPort, "get_by_id")

    def test_has_get_by_type_method(self):
        assert hasattr(CommunicationChannelPort, "get_by_type")

    def test_has_get_all_method(self):
        assert hasattr(CommunicationChannelPort, "get_all")

    def test_has_delete_method(self):
        assert hasattr(CommunicationChannelPort, "delete")

    def test_has_update_metrics_method(self):
        assert hasattr(CommunicationChannelPort, "update_metrics")

    def test_has_update_status_method(self):
        assert hasattr(CommunicationChannelPort, "update_status")


# =============================================================================
# Fake Implementation for Testing Contract
# =============================================================================


class FakeCommunicationChannelAdapter(CommunicationChannelPort):
    """Implementation fake pour tester le contrat du port."""

    def __init__(self):
        self._channels: dict[str, CommunicationChannel] = {}

    def save(self, channel: CommunicationChannel) -> CommunicationChannel:
        self._channels[channel.id] = channel
        return channel

    def get_by_id(self, channel_id: str) -> Optional[CommunicationChannel]:
        return self._channels.get(channel_id)

    def get_by_type(self, channel_type: ChannelType) -> List[CommunicationChannel]:
        return [c for c in self._channels.values() if c.channel_type == channel_type]

    def get_all(self) -> List[CommunicationChannel]:
        return list(self._channels.values())

    def delete(self, channel_id: str) -> bool:
        if channel_id in self._channels:
            del self._channels[channel_id]
            return True
        return False

    def update_metrics(self, channel_id: str, metrics: ChannelMetrics) -> bool:
        if channel_id not in self._channels:
            return False
        channel = self._channels[channel_id]
        self._channels[channel_id] = replace(channel, metrics=metrics)
        return True

    def update_status(self, channel_id: str, status: ChannelStatus) -> bool:
        if channel_id not in self._channels:
            return False
        channel = self._channels[channel_id]
        self._channels[channel_id] = replace(channel, status=status)
        return True


# =============================================================================
# Tests Fake Implementation
# =============================================================================


class TestFakeImplementation:
    """Verifie qu'une implementation concrete fonctionne."""

    @pytest.fixture
    def adapter(self):
        return FakeCommunicationChannelAdapter()

    @pytest.fixture
    def sample_channel(self):
        config = ChannelConfig(credentials={"api_key": "test"})
        return CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Gmail Test",
            config=config,
        )

    def test_save_and_get_by_id(self, adapter, sample_channel):
        adapter.save(sample_channel)
        result = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert result is not None
        assert result.id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.name == "Gmail Test"

    def test_get_by_type(self, adapter, sample_channel):
        adapter.save(sample_channel)
        result = adapter.get_by_type(ChannelType.EMAIL)
        assert len(result) == 1
        assert result[0].channel_type == ChannelType.EMAIL

    def test_get_all(self, adapter, sample_channel):
        adapter.save(sample_channel)
        result = adapter.get_all()
        assert len(result) == 1

    def test_delete(self, adapter, sample_channel):
        adapter.save(sample_channel)
        result = adapter.delete("550e8400-e29b-41d4-a716-446655440000")
        assert result is True
        assert adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000") is None

    def test_delete_not_found(self, adapter):
        result = adapter.delete("non-existent-id")
        assert result is False

    def test_update_metrics(self, adapter, sample_channel):
        adapter.save(sample_channel)
        new_metrics = ChannelMetrics(messages_sent=10, messages_received=5)
        result = adapter.update_metrics(
            "550e8400-e29b-41d4-a716-446655440000",
            new_metrics,
        )
        assert result is True
        updated = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert updated.metrics.messages_sent == 10
        assert updated.metrics.messages_received == 5

    def test_update_metrics_not_found(self, adapter):
        new_metrics = ChannelMetrics(messages_sent=10)
        result = adapter.update_metrics("non-existent-id", new_metrics)
        assert result is False

    def test_update_status(self, adapter, sample_channel):
        adapter.save(sample_channel)
        result = adapter.update_status(
            "550e8400-e29b-41d4-a716-446655440000",
            ChannelStatus.ACTIVE,
        )
        assert result is True
        updated = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert updated.status == ChannelStatus.ACTIVE

    def test_update_status_not_found(self, adapter):
        result = adapter.update_status("non-existent-id", ChannelStatus.ACTIVE)
        assert result is False


# =============================================================================
# Tests Edge Cases - Empty Adapter
# =============================================================================


class TestEdgeCasesEmptyAdapter:
    """Tests des cas limites avec un adapter vide."""

    @pytest.fixture
    def adapter(self):
        return FakeCommunicationChannelAdapter()

    def test_get_all_empty(self, adapter):
        result = adapter.get_all()
        assert result == []
        assert isinstance(result, list)

    def test_get_by_id_not_found(self, adapter):
        result = adapter.get_by_id("non-existent-id")
        assert result is None

    def test_get_by_type_empty(self, adapter):
        result = adapter.get_by_type(ChannelType.DISCORD)
        assert result == []
        assert isinstance(result, list)


# =============================================================================
# Tests Edge Cases - Multiple Channels
# =============================================================================


class TestEdgeCasesMultipleChannels:
    """Tests avec plusieurs canaux."""

    @pytest.fixture
    def adapter(self):
        return FakeCommunicationChannelAdapter()

    @pytest.fixture
    def multiple_channels(self, adapter):
        config = ChannelConfig(credentials={"key": "val"})
        channels = [
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440001",
                channel_type=ChannelType.EMAIL,
                name="Gmail 1",
                config=config,
            ),
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440002",
                channel_type=ChannelType.EMAIL,
                name="Gmail 2",
                config=config,
            ),
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440003",
                channel_type=ChannelType.DISCORD,
                name="Discord Bot",
                config=config,
            ),
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440004",
                channel_type=ChannelType.SMS,
                name="Twilio",
                config=config,
            ),
        ]
        for c in channels:
            adapter.save(c)
        return channels

    def test_get_all_returns_all(self, adapter, multiple_channels):
        result = adapter.get_all()
        assert len(result) == 4

    def test_get_by_type_filters_correctly(self, adapter, multiple_channels):
        emails = adapter.get_by_type(ChannelType.EMAIL)
        assert len(emails) == 2
        for c in emails:
            assert c.channel_type == ChannelType.EMAIL

    def test_get_by_type_discord(self, adapter, multiple_channels):
        discord = adapter.get_by_type(ChannelType.DISCORD)
        assert len(discord) == 1
        assert discord[0].name == "Discord Bot"

    def test_get_by_type_no_match(self, adapter, multiple_channels):
        voice = adapter.get_by_type(ChannelType.VOICE)
        assert voice == []

    def test_delete_one_preserves_others(self, adapter, multiple_channels):
        adapter.delete("550e8400-e29b-41d4-a716-446655440001")
        result = adapter.get_all()
        assert len(result) == 3
        assert adapter.get_by_id("550e8400-e29b-41d4-a716-446655440001") is None


# =============================================================================
# Tests Edge Cases - Update Operations
# =============================================================================


class TestEdgeCasesUpdateOperations:
    """Tests des operations de mise a jour."""

    @pytest.fixture
    def adapter(self):
        return FakeCommunicationChannelAdapter()

    @pytest.fixture
    def channel(self, adapter):
        config = ChannelConfig(credentials={"key": "val"})
        c = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test Channel",
            config=config,
            status=ChannelStatus.PENDING_SETUP,
        )
        adapter.save(c)
        return c

    def test_save_overwrites_existing(self, adapter, channel):
        config = ChannelConfig(credentials={"key": "new_val"})
        updated_channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Updated Name",
            config=config,
            status=ChannelStatus.ACTIVE,
        )
        adapter.save(updated_channel)
        result = adapter.get_by_id("550e8400-e29b-41d4-a716-446655440000")
        assert result.name == "Updated Name"
        assert result.status == ChannelStatus.ACTIVE

    def test_update_status_transition(self, adapter, channel):
        adapter.update_status(channel.id, ChannelStatus.ACTIVE)
        result = adapter.get_by_id(channel.id)
        assert result.status == ChannelStatus.ACTIVE

        adapter.update_status(channel.id, ChannelStatus.ERROR)
        result = adapter.get_by_id(channel.id)
        assert result.status == ChannelStatus.ERROR

        adapter.update_status(channel.id, ChannelStatus.INACTIVE)
        result = adapter.get_by_id(channel.id)
        assert result.status == ChannelStatus.INACTIVE

    def test_update_metrics_accumulates(self, adapter, channel):
        metrics1 = ChannelMetrics(messages_sent=5, messages_received=3)
        adapter.update_metrics(channel.id, metrics1)
        result = adapter.get_by_id(channel.id)
        assert result.metrics.messages_sent == 5

        metrics2 = ChannelMetrics(messages_sent=10, messages_received=8)
        adapter.update_metrics(channel.id, metrics2)
        result = adapter.get_by_id(channel.id)
        assert result.metrics.messages_sent == 10
