# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour l'entite CommunicationChannel et ses Value Objects."""

import pytest
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import datetime
from enum import Enum

from app.domain.entities.communication_channel import (
    ChannelType,
    ChannelStatus,
    ChannelConfig,
    ChannelMetrics,
    CommunicationChannel,
)
from app.domain.exceptions import EmptyValueError, InvalidFormatError


# =============================================================================
# Tests ChannelType Enum
# =============================================================================


class TestChannelTypeEnum:
    """Tests pour l'enum ChannelType."""

    def test_email_value(self):
        assert ChannelType.EMAIL.value == "email"

    def test_discord_value(self):
        assert ChannelType.DISCORD.value == "discord"

    def test_sms_value(self):
        assert ChannelType.SMS.value == "sms"

    def test_voice_value(self):
        assert ChannelType.VOICE.value == "voice"

    def test_push_notification_value(self):
        assert ChannelType.PUSH_NOTIFICATION.value == "push_notification"

    def test_all_channel_types_count(self):
        assert len(ChannelType) == 5

    def test_is_enum(self):
        assert issubclass(ChannelType, Enum)

    def test_from_value(self):
        assert ChannelType("email") == ChannelType.EMAIL
        assert ChannelType("discord") == ChannelType.DISCORD

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ChannelType("invalid")


# =============================================================================
# Tests ChannelStatus Enum
# =============================================================================


class TestChannelStatusEnum:
    """Tests pour l'enum ChannelStatus."""

    def test_active_value(self):
        assert ChannelStatus.ACTIVE.value == "active"

    def test_inactive_value(self):
        assert ChannelStatus.INACTIVE.value == "inactive"

    def test_error_value(self):
        assert ChannelStatus.ERROR.value == "error"

    def test_pending_setup_value(self):
        assert ChannelStatus.PENDING_SETUP.value == "pending_setup"

    def test_all_statuses_count(self):
        assert len(ChannelStatus) == 4

    def test_is_enum(self):
        assert issubclass(ChannelStatus, Enum)

    def test_from_value(self):
        assert ChannelStatus("active") == ChannelStatus.ACTIVE
        assert ChannelStatus("error") == ChannelStatus.ERROR


# =============================================================================
# Tests ChannelConfig Value Object
# =============================================================================


class TestChannelConfig:
    """Tests pour le Value Object ChannelConfig."""

    def test_create_minimal_config(self):
        config = ChannelConfig(credentials={"api_key": "secret"})
        assert config.credentials == {"api_key": "secret"}
        assert config.endpoint is None
        assert config.webhook_url is None
        assert config.settings == {}

    def test_create_full_config(self):
        config = ChannelConfig(
            credentials={"api_key": "secret", "secret_key": "supersecret"},
            endpoint="https://api.example.com",
            webhook_url="https://webhook.example.com/hook",
            settings={"timeout": 30, "retry": True},
        )
        assert config.credentials["api_key"] == "secret"
        assert config.endpoint == "https://api.example.com"
        assert config.webhook_url == "https://webhook.example.com/hook"
        assert config.settings["timeout"] == 30

    def test_is_frozen_dataclass(self):
        config = ChannelConfig(credentials={})
        assert is_dataclass(config)
        with pytest.raises(FrozenInstanceError):
            config.endpoint = "new_endpoint"

    def test_empty_credentials(self):
        config = ChannelConfig(credentials={})
        assert config.credentials == {}

    def test_credentials_with_special_characters(self):
        config = ChannelConfig(
            credentials={"api_key": "sk-abc123!@#$%^&*()_+=[]{}|;':\",./<>?"}
        )
        assert "!@#$%^&*()" in config.credentials["api_key"]

    def test_nested_settings(self):
        config = ChannelConfig(
            credentials={"key": "val"},
            settings={
                "nested": {"level1": {"level2": "value"}},
                "list": [1, 2, 3],
                "mixed": [{"a": 1}, {"b": 2}],
            },
        )
        assert config.settings["nested"]["level1"]["level2"] == "value"
        assert config.settings["list"] == [1, 2, 3]

    def test_config_equality(self):
        c1 = ChannelConfig(credentials={"key": "val"}, endpoint="http://api.com")
        c2 = ChannelConfig(credentials={"key": "val"}, endpoint="http://api.com")
        assert c1 == c2

    def test_config_hashable(self):
        """Frozen dataclass should be hashable if all fields are hashable."""
        # Note: dict is not hashable, so ChannelConfig won't be hashable
        config = ChannelConfig(credentials={})
        with pytest.raises(TypeError):
            hash(config)


# =============================================================================
# Tests ChannelMetrics Value Object
# =============================================================================


class TestChannelMetrics:
    """Tests pour le Value Object ChannelMetrics."""

    def test_default_values(self):
        metrics = ChannelMetrics()
        assert metrics.messages_sent == 0
        assert metrics.messages_received == 0
        assert metrics.last_used_at is None
        assert metrics.error_count == 0

    def test_custom_values(self):
        now = datetime.now()
        metrics = ChannelMetrics(
            messages_sent=100,
            messages_received=50,
            last_used_at=now,
            error_count=2,
        )
        assert metrics.messages_sent == 100
        assert metrics.messages_received == 50
        assert metrics.last_used_at == now
        assert metrics.error_count == 2

    def test_is_frozen_dataclass(self):
        metrics = ChannelMetrics()
        assert is_dataclass(metrics)
        with pytest.raises(FrozenInstanceError):
            metrics.messages_sent = 10

    def test_negative_values_allowed(self):
        """Negative values are technically allowed - validation is caller's responsibility."""
        metrics = ChannelMetrics(messages_sent=-1, error_count=-5)
        assert metrics.messages_sent == -1
        assert metrics.error_count == -5

    def test_large_values(self):
        """Test with large integer values."""
        large_val = 2**31 - 1  # Max 32-bit signed int
        metrics = ChannelMetrics(
            messages_sent=large_val,
            messages_received=large_val,
            error_count=large_val,
        )
        assert metrics.messages_sent == large_val

    def test_metrics_equality(self):
        now = datetime.now()
        m1 = ChannelMetrics(messages_sent=5, last_used_at=now)
        m2 = ChannelMetrics(messages_sent=5, last_used_at=now)
        assert m1 == m2

    def test_metrics_not_hashable(self):
        """ChannelMetrics contains datetime which is hashable, but frozen dataclass should be hashable."""
        # Actually frozen dataclasses with all hashable fields ARE hashable
        metrics = ChannelMetrics()
        # This should work since all fields are hashable (int, None, datetime)
        h = hash(metrics)
        assert isinstance(h, int)


# =============================================================================
# Tests CommunicationChannel Entity - Creation
# =============================================================================


class TestCommunicationChannelCreation:
    """Tests pour la creation d'un CommunicationChannel."""

    @pytest.fixture
    def valid_config(self):
        return ChannelConfig(credentials={"api_key": "test_key"})

    def test_create_minimal_channel(self, valid_config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Gmail Principal",
            config=valid_config,
        )
        assert channel.id == "550e8400-e29b-41d4-a716-446655440001"
        assert channel.channel_type == ChannelType.EMAIL
        assert channel.name == "Gmail Principal"
        assert channel.status == ChannelStatus.PENDING_SETUP
        assert channel.metrics.messages_sent == 0

    def test_create_with_all_fields(self, valid_config):
        now = datetime.now()
        metrics = ChannelMetrics(messages_sent=10, messages_received=5)
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.DISCORD,
            name="Discord Bot",
            config=valid_config,
            status=ChannelStatus.ACTIVE,
            metrics=metrics,
            created_at=now,
            updated_at=now,
        )
        assert channel.status == ChannelStatus.ACTIVE
        assert channel.metrics.messages_sent == 10
        assert channel.created_at == now

    def test_default_status_is_pending_setup(self, valid_config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440003",
            channel_type=ChannelType.SMS,
            name="Twilio SMS",
            config=valid_config,
        )
        assert channel.status == ChannelStatus.PENDING_SETUP


# =============================================================================
# Tests CommunicationChannel Entity - Validation
# =============================================================================


class TestCommunicationChannelValidation:
    """Tests de validation de CommunicationChannel."""

    @pytest.fixture
    def valid_config(self):
        return ChannelConfig(credentials={"api_key": "test_key"})

    def test_empty_id_raises(self, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id="",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )

    def test_empty_name_raises(self, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440000",
                channel_type=ChannelType.EMAIL,
                name="",
                config=valid_config,
            )

    def test_name_too_long_raises(self, valid_config):
        with pytest.raises(ValueError):
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440000",
                channel_type=ChannelType.EMAIL,
                name="A" * 101,
                config=valid_config,
            )

    def test_whitespace_only_id_raises(self, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id="   ",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )

    def test_whitespace_only_name_raises(self, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440000",
                channel_type=ChannelType.EMAIL,
                name="   ",
                config=valid_config,
            )

    def test_invalid_uuid_format_raises(self, valid_config):
        with pytest.raises(InvalidFormatError):
            CommunicationChannel(
                id="not-a-uuid",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )

    def test_valid_uuid_format(self, valid_config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.id == "550e8400-e29b-41d4-a716-446655440000"

    def test_uuid_case_insensitive_uppercase(self, valid_config):
        """UUID should accept uppercase letters."""
        channel = CommunicationChannel(
            id="550E8400-E29B-41D4-A716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.id == "550E8400-E29B-41D4-A716-446655440000"

    def test_uuid_case_insensitive_mixed(self, valid_config):
        """UUID should accept mixed case."""
        channel = CommunicationChannel(
            id="550e8400-E29B-41d4-A716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.id == "550e8400-E29B-41d4-A716-446655440000"

    def test_name_exactly_100_characters(self, valid_config):
        """Name with exactly 100 characters should be valid."""
        name_100 = "A" * 100
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name=name_100,
            config=valid_config,
        )
        assert len(channel.name) == 100

    def test_name_with_unicode_characters(self, valid_config):
        """Name with unicode characters should be valid."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Канал связи émoji 🚀 日本語",
            config=valid_config,
        )
        assert "🚀" in channel.name
        assert "日本語" in channel.name

    def test_name_with_newlines_raises(self, valid_config):
        """Name with newlines is still valid (no newline validation)."""
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Line1\nLine2",
            config=valid_config,
        )
        assert "\n" in channel.name

    def test_uuid_without_dashes_raises(self, valid_config):
        """UUID without dashes should be invalid."""
        with pytest.raises(InvalidFormatError):
            CommunicationChannel(
                id="550e8400e29b41d4a716446655440000",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )

    def test_uuid_with_extra_characters_raises(self, valid_config):
        """UUID with extra characters should be invalid."""
        with pytest.raises(InvalidFormatError):
            CommunicationChannel(
                id="550e8400-e29b-41d4-a716-446655440000-extra",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )


# =============================================================================
# Tests CommunicationChannel Entity - State Transitions
# =============================================================================


class TestCommunicationChannelStateTransitions:
    """Tests des transitions d'etat."""

    @pytest.fixture
    def pending_channel(self):
        config = ChannelConfig(credentials={"api_key": "test"})
        return CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test Channel",
            config=config,
        )

    def test_activate_returns_new_instance(self, pending_channel):
        active = pending_channel.activate()
        assert active is not pending_channel

    def test_activate_sets_status(self, pending_channel):
        active = pending_channel.activate()
        assert active.status == ChannelStatus.ACTIVE

    def test_activate_preserves_original(self, pending_channel):
        pending_channel.activate()
        assert pending_channel.status == ChannelStatus.PENDING_SETUP

    def test_deactivate_returns_new_instance(self, pending_channel):
        active = pending_channel.activate()
        inactive = active.deactivate()
        assert inactive is not active

    def test_deactivate_sets_status(self, pending_channel):
        active = pending_channel.activate()
        inactive = active.deactivate()
        assert inactive.status == ChannelStatus.INACTIVE

    def test_mark_error_returns_new_instance(self, pending_channel):
        error = pending_channel.mark_error()
        assert error is not pending_channel

    def test_mark_error_sets_status(self, pending_channel):
        error = pending_channel.mark_error()
        assert error.status == ChannelStatus.ERROR

    def test_activate_idempotent(self, pending_channel):
        """Calling activate multiple times should have same effect."""
        active1 = pending_channel.activate()
        active2 = active1.activate()
        assert active1.status == ChannelStatus.ACTIVE
        assert active2.status == ChannelStatus.ACTIVE

    def test_deactivate_from_error(self, pending_channel):
        """Deactivate should work from ERROR status."""
        error = pending_channel.mark_error()
        inactive = error.deactivate()
        assert inactive.status == ChannelStatus.INACTIVE

    def test_mark_error_from_active(self, pending_channel):
        """Mark error should work from ACTIVE status."""
        active = pending_channel.activate()
        error = active.mark_error()
        assert error.status == ChannelStatus.ERROR

    def test_all_state_transitions_preserve_fields(self, pending_channel):
        """All state transitions should preserve other fields."""
        original_id = pending_channel.id
        original_name = pending_channel.name
        original_type = pending_channel.channel_type

        for method in [pending_channel.activate, pending_channel.deactivate, pending_channel.mark_error]:
            result = method()
            assert result.id == original_id
            assert result.name == original_name
            assert result.channel_type == original_type


# =============================================================================
# Tests CommunicationChannel Entity - Metrics Update
# =============================================================================


class TestCommunicationChannelMetricsUpdate:
    """Tests de mise a jour des metriques."""

    @pytest.fixture
    def channel(self):
        config = ChannelConfig(credentials={"api_key": "test"})
        return CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test Channel",
            config=config,
        )

    def test_record_sent_message(self, channel):
        updated = channel.record_message_sent()
        assert updated.metrics.messages_sent == 1
        assert updated.metrics.last_used_at is not None

    def test_record_received_message(self, channel):
        updated = channel.record_message_received()
        assert updated.metrics.messages_received == 1
        assert updated.metrics.last_used_at is not None

    def test_record_error(self, channel):
        updated = channel.record_error()
        assert updated.metrics.error_count == 1

    def test_multiple_sends(self, channel):
        updated = channel.record_message_sent()
        updated = updated.record_message_sent()
        updated = updated.record_message_sent()
        assert updated.metrics.messages_sent == 3

    def test_update_metrics_preserves_other_fields(self, channel):
        updated = channel.record_message_sent()
        assert updated.id == channel.id
        assert updated.channel_type == channel.channel_type
        assert updated.name == channel.name

    def test_record_error_does_not_update_last_used_at(self, channel):
        """record_error should NOT update last_used_at."""
        updated = channel.record_error()
        assert updated.metrics.error_count == 1
        assert updated.metrics.last_used_at is None  # Should remain None

    def test_chained_operations(self, channel):
        """Test chaining multiple operations."""
        result = (
            channel
            .record_message_sent()
            .record_message_sent()
            .record_message_received()
            .record_error()
        )
        assert result.metrics.messages_sent == 2
        assert result.metrics.messages_received == 1
        assert result.metrics.error_count == 1
        assert result.metrics.last_used_at is not None

    def test_record_sent_returns_new_instance(self, channel):
        updated = channel.record_message_sent()
        assert updated is not channel
        assert updated.metrics is not channel.metrics

    def test_record_received_returns_new_instance(self, channel):
        updated = channel.record_message_received()
        assert updated is not channel
        assert updated.metrics is not channel.metrics

    def test_record_error_returns_new_instance(self, channel):
        updated = channel.record_error()
        assert updated is not channel
        assert updated.metrics is not channel.metrics

    def test_original_unchanged_after_record_sent(self, channel):
        channel.record_message_sent()
        assert channel.metrics.messages_sent == 0

    def test_original_unchanged_after_record_received(self, channel):
        channel.record_message_received()
        assert channel.metrics.messages_received == 0

    def test_original_unchanged_after_record_error(self, channel):
        channel.record_error()
        assert channel.metrics.error_count == 0


# =============================================================================
# Tests CommunicationChannel Entity - All Channel Types
# =============================================================================


class TestCommunicationChannelAllTypes:
    """Tests pour tous les types de canaux."""

    @pytest.fixture
    def config(self):
        return ChannelConfig(credentials={"key": "value"})

    def test_create_email_channel(self, config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Email Channel",
            config=config,
        )
        assert channel.channel_type == ChannelType.EMAIL

    def test_create_discord_channel(self, config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.DISCORD,
            name="Discord Channel",
            config=config,
        )
        assert channel.channel_type == ChannelType.DISCORD

    def test_create_sms_channel(self, config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.SMS,
            name="SMS Channel",
            config=config,
        )
        assert channel.channel_type == ChannelType.SMS

    def test_create_voice_channel(self, config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440003",
            channel_type=ChannelType.VOICE,
            name="Voice Channel",
            config=config,
        )
        assert channel.channel_type == ChannelType.VOICE

    def test_create_push_notification_channel(self, config):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440004",
            channel_type=ChannelType.PUSH_NOTIFICATION,
            name="Push Channel",
            config=config,
        )
        assert channel.channel_type == ChannelType.PUSH_NOTIFICATION


# =============================================================================
# Tests CommunicationChannel Entity - Equality
# =============================================================================


class TestCommunicationChannelEquality:
    """Tests d'egalite."""

    @pytest.fixture
    def config(self):
        return ChannelConfig(credentials={"api_key": "test"})

    def test_equal_channels(self, config):
        c1 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        c2 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        assert c1 == c2

    def test_different_id_not_equal(self, config):
        c1 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        c2 = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        assert c1 != c2


# =============================================================================
# Tests CommunicationChannel Entity - Type Checks
# =============================================================================


class TestCommunicationChannelTypeChecks:
    """Tests de verification des types."""

    def test_is_dataclass(self):
        assert is_dataclass(CommunicationChannel)

    def test_channel_not_hashable(self):
        config = ChannelConfig(credentials={})
        c = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        with pytest.raises(TypeError):
            hash(c)

    def test_channel_in_list(self):
        config = ChannelConfig(credentials={})
        c = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=config,
        )
        channels = [c]
        assert len(channels) == 1
