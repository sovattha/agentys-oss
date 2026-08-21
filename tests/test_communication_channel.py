"""
Tests for communication_channel.py entity.

Tests for:
- ChannelType enum
- ChannelStatus enum
- ChannelConfig value object
- ChannelMetrics value object
- CommunicationChannel aggregate root (validation + methods)
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from app.domain.entities.communication_channel import (
    ChannelType,
    ChannelStatus,
    ChannelConfig,
    ChannelMetrics,
    CommunicationChannel,
    UUID_PATTERN,
)
from app.domain.exceptions import EmptyValueError, InvalidFormatError


# =============================================================================
# ChannelType Enum Tests
# =============================================================================


class TestChannelType:
    """Tests for ChannelType enum."""

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

    def test_channel_type_from_value(self):
        assert ChannelType("email") == ChannelType.EMAIL
        assert ChannelType("discord") == ChannelType.DISCORD

    def test_invalid_channel_type_raises(self):
        with pytest.raises(ValueError):
            ChannelType("invalid_type")


# =============================================================================
# ChannelStatus Enum Tests
# =============================================================================


class TestChannelStatus:
    """Tests for ChannelStatus enum."""

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

    def test_status_from_value(self):
        assert ChannelStatus("active") == ChannelStatus.ACTIVE
        assert ChannelStatus("error") == ChannelStatus.ERROR

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            ChannelStatus("unknown")


# =============================================================================
# ChannelConfig Value Object Tests
# =============================================================================


class TestChannelConfig:
    """Tests for ChannelConfig value object."""

    def test_create_minimal_config(self):
        config = ChannelConfig(credentials={"api_key": "secret"})
        assert config.credentials == {"api_key": "secret"}
        assert config.endpoint is None
        assert config.webhook_url is None
        assert config.settings == {}

    def test_create_full_config(self):
        config = ChannelConfig(
            credentials={"user": "admin", "pass": "secret"},
            endpoint="https://api.example.com",
            webhook_url="https://webhook.example.com/hook",
            settings={"timeout": 30, "retries": 3},
        )
        assert config.credentials == {"user": "admin", "pass": "secret"}
        assert config.endpoint == "https://api.example.com"
        assert config.webhook_url == "https://webhook.example.com/hook"
        assert config.settings == {"timeout": 30, "retries": 3}

    def test_config_is_frozen(self):
        config = ChannelConfig(credentials={"key": "value"})
        with pytest.raises(Exception):  # FrozenInstanceError
            config.endpoint = "new_endpoint"

    def test_config_equality(self):
        config1 = ChannelConfig(credentials={"key": "val"}, endpoint="ep1")
        config2 = ChannelConfig(credentials={"key": "val"}, endpoint="ep1")
        assert config1 == config2

    def test_config_inequality(self):
        config1 = ChannelConfig(credentials={"key": "val1"})
        config2 = ChannelConfig(credentials={"key": "val2"})
        assert config1 != config2

    def test_empty_credentials(self):
        config = ChannelConfig(credentials={})
        assert config.credentials == {}


# =============================================================================
# ChannelMetrics Value Object Tests
# =============================================================================


class TestChannelMetrics:
    """Tests for ChannelMetrics value object."""

    def test_create_default_metrics(self):
        metrics = ChannelMetrics()
        assert metrics.messages_sent == 0
        assert metrics.messages_received == 0
        assert metrics.last_used_at is None
        assert metrics.error_count == 0

    def test_create_with_values(self):
        now = datetime.now()
        metrics = ChannelMetrics(
            messages_sent=100,
            messages_received=50,
            last_used_at=now,
            error_count=3,
        )
        assert metrics.messages_sent == 100
        assert metrics.messages_received == 50
        assert metrics.last_used_at == now
        assert metrics.error_count == 3

    def test_metrics_is_frozen(self):
        metrics = ChannelMetrics()
        with pytest.raises(Exception):  # FrozenInstanceError
            metrics.messages_sent = 10

    def test_metrics_equality(self):
        now = datetime.now()
        m1 = ChannelMetrics(messages_sent=10, last_used_at=now)
        m2 = ChannelMetrics(messages_sent=10, last_used_at=now)
        assert m1 == m2

    def test_metrics_inequality(self):
        m1 = ChannelMetrics(messages_sent=10)
        m2 = ChannelMetrics(messages_sent=20)
        assert m1 != m2


# =============================================================================
# UUID_PATTERN Tests
# =============================================================================


class TestUUIDPattern:
    """Tests for UUID validation pattern."""

    def test_valid_uuid_lowercase(self):
        assert UUID_PATTERN.match("550e8400-e29b-41d4-a716-446655440000") is not None

    def test_valid_uuid_uppercase(self):
        assert UUID_PATTERN.match("550E8400-E29B-41D4-A716-446655440000") is not None

    def test_valid_uuid_mixed_case(self):
        assert UUID_PATTERN.match("550e8400-E29B-41d4-A716-446655440000") is not None

    def test_invalid_uuid_too_short(self):
        assert UUID_PATTERN.match("550e8400-e29b-41d4-a716") is None

    def test_invalid_uuid_no_dashes(self):
        assert UUID_PATTERN.match("550e8400e29b41d4a716446655440000") is None

    def test_invalid_uuid_wrong_format(self):
        assert UUID_PATTERN.match("not-a-valid-uuid") is None

    def test_invalid_uuid_invalid_chars(self):
        assert UUID_PATTERN.match("550e8400-e29b-41d4-a716-44665544000g") is None

    def test_empty_string(self):
        assert UUID_PATTERN.match("") is None


# =============================================================================
# CommunicationChannel Aggregate Root Tests - Validation
# =============================================================================


class TestCommunicationChannelValidation:
    """Tests for CommunicationChannel validation rules."""

    @pytest.fixture
    def valid_config(self):
        return ChannelConfig(credentials={"key": "secret"})

    @pytest.fixture
    def valid_uuid(self):
        return "550e8400-e29b-41d4-a716-446655440000"

    def test_create_valid_channel(self, valid_uuid, valid_config):
        channel = CommunicationChannel(
            id=valid_uuid,
            channel_type=ChannelType.EMAIL,
            name="My Email Channel",
            config=valid_config,
        )
        assert channel.id == valid_uuid
        assert channel.channel_type == ChannelType.EMAIL
        assert channel.name == "My Email Channel"
        assert channel.status == ChannelStatus.PENDING_SETUP

    def test_empty_id_raises_empty_value_error(self, valid_config):
        with pytest.raises(EmptyValueError) as exc:
            CommunicationChannel(
                id="",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )
        assert "id" in str(exc.value)

    def test_whitespace_id_raises_empty_value_error(self, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id="   ",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )

    def test_invalid_uuid_format_raises_invalid_format_error(self, valid_config):
        with pytest.raises(InvalidFormatError) as exc:
            CommunicationChannel(
                id="not-a-valid-uuid",
                channel_type=ChannelType.EMAIL,
                name="Test",
                config=valid_config,
            )
        assert "id" in str(exc.value)
        assert "UUID" in str(exc.value)

    def test_empty_name_raises_empty_value_error(self, valid_uuid, valid_config):
        with pytest.raises(EmptyValueError) as exc:
            CommunicationChannel(
                id=valid_uuid,
                channel_type=ChannelType.EMAIL,
                name="",
                config=valid_config,
            )
        assert "nom" in str(exc.value)

    def test_whitespace_name_raises_empty_value_error(self, valid_uuid, valid_config):
        with pytest.raises(EmptyValueError):
            CommunicationChannel(
                id=valid_uuid,
                channel_type=ChannelType.EMAIL,
                name="   ",
                config=valid_config,
            )

    def test_name_too_long_raises_value_error(self, valid_uuid, valid_config):
        long_name = "a" * 101
        with pytest.raises(ValueError) as exc:
            CommunicationChannel(
                id=valid_uuid,
                channel_type=ChannelType.EMAIL,
                name=long_name,
                config=valid_config,
            )
        assert "100 caracteres" in str(exc.value)

    def test_name_exactly_100_chars_is_valid(self, valid_uuid, valid_config):
        name = "a" * 100
        channel = CommunicationChannel(
            id=valid_uuid,
            channel_type=ChannelType.EMAIL,
            name=name,
            config=valid_config,
        )
        assert len(channel.name) == 100

    def test_default_status_is_pending_setup(self, valid_uuid, valid_config):
        channel = CommunicationChannel(
            id=valid_uuid,
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.status == ChannelStatus.PENDING_SETUP

    def test_default_metrics_is_empty(self, valid_uuid, valid_config):
        channel = CommunicationChannel(
            id=valid_uuid,
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.metrics.messages_sent == 0
        assert channel.metrics.messages_received == 0
        assert channel.metrics.error_count == 0

    def test_created_at_and_updated_at_optional(self, valid_uuid, valid_config):
        channel = CommunicationChannel(
            id=valid_uuid,
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=valid_config,
        )
        assert channel.created_at is None
        assert channel.updated_at is None

    def test_all_channel_types_can_be_created(self, valid_uuid, valid_config):
        for channel_type in ChannelType:
            channel = CommunicationChannel(
                id=valid_uuid,
                channel_type=channel_type,
                name=f"Test {channel_type.value}",
                config=valid_config,
            )
            assert channel.channel_type == channel_type


# =============================================================================
# CommunicationChannel Aggregate Root Tests - Status Methods
# =============================================================================


class TestCommunicationChannelStatusMethods:
    """Tests for CommunicationChannel status change methods."""

    @pytest.fixture
    def channel(self):
        return CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test Channel",
            config=ChannelConfig(credentials={"key": "secret"}),
        )

    def test_activate_returns_new_channel(self, channel):
        activated = channel.activate()
        assert activated is not channel
        assert activated.status == ChannelStatus.ACTIVE

    def test_activate_preserves_other_fields(self, channel):
        activated = channel.activate()
        assert activated.id == channel.id
        assert activated.channel_type == channel.channel_type
        assert activated.name == channel.name
        assert activated.config == channel.config

    def test_deactivate_returns_new_channel(self, channel):
        activated = channel.activate()
        deactivated = activated.deactivate()
        assert deactivated is not activated
        assert deactivated.status == ChannelStatus.INACTIVE

    def test_deactivate_preserves_other_fields(self, channel):
        deactivated = channel.deactivate()
        assert deactivated.id == channel.id
        assert deactivated.name == channel.name

    def test_mark_error_returns_new_channel(self, channel):
        errored = channel.mark_error()
        assert errored is not channel
        assert errored.status == ChannelStatus.ERROR

    def test_mark_error_preserves_other_fields(self, channel):
        errored = channel.mark_error()
        assert errored.id == channel.id
        assert errored.name == channel.name

    def test_status_transitions(self, channel):
        # PENDING_SETUP -> ACTIVE -> INACTIVE -> ERROR -> ACTIVE
        assert channel.status == ChannelStatus.PENDING_SETUP

        active = channel.activate()
        assert active.status == ChannelStatus.ACTIVE

        inactive = active.deactivate()
        assert inactive.status == ChannelStatus.INACTIVE

        error = inactive.mark_error()
        assert error.status == ChannelStatus.ERROR

        reactivated = error.activate()
        assert reactivated.status == ChannelStatus.ACTIVE


# =============================================================================
# CommunicationChannel Aggregate Root Tests - Metrics Methods
# =============================================================================


class TestCommunicationChannelMetricsMethods:
    """Tests for CommunicationChannel metrics recording methods."""

    @pytest.fixture
    def channel(self):
        return CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.DISCORD,
            name="Discord Bot",
            config=ChannelConfig(credentials={"token": "bot_token"}),
        )

    def test_record_message_sent_increments_counter(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            updated = channel.record_message_sent()
        assert updated.metrics.messages_sent == 1
        assert updated.metrics.messages_received == 0

    def test_record_message_sent_updates_last_used_at(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            updated = channel.record_message_sent()
        assert updated.metrics.last_used_at == fixed_time

    def test_record_message_received_increments_counter(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            updated = channel.record_message_received()
        assert updated.metrics.messages_received == 1
        assert updated.metrics.messages_sent == 0

    def test_record_message_received_updates_last_used_at(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            updated = channel.record_message_received()
        assert updated.metrics.last_used_at == fixed_time

    def test_record_error_increments_error_count(self, channel):
        updated = channel.record_error()
        assert updated.metrics.error_count == 1
        assert updated.metrics.messages_sent == 0

    def test_record_error_does_not_update_last_used_at(self, channel):
        updated = channel.record_error()
        assert updated.metrics.last_used_at is None

    def test_multiple_message_sent_increments(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            c1 = channel.record_message_sent()
            c2 = c1.record_message_sent()
            c3 = c2.record_message_sent()
        assert c3.metrics.messages_sent == 3

    def test_mixed_operations(self, channel):
        fixed_time = datetime(2026, 1, 5, 10, 0, 0)
        with patch(
            "app.domain.entities.communication_channel.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fixed_time
            updated = (
                channel.record_message_sent()
                .record_message_received()
                .record_message_sent()
                .record_error()
                .record_message_received()
            )
        assert updated.metrics.messages_sent == 2
        assert updated.metrics.messages_received == 2
        assert updated.metrics.error_count == 1

    def test_metrics_returns_new_channel(self, channel):
        sent = channel.record_message_sent()
        received = channel.record_message_received()
        errored = channel.record_error()

        assert sent is not channel
        assert received is not channel
        assert errored is not channel

    def test_original_channel_unchanged(self, channel):
        _ = channel.record_message_sent()
        _ = channel.record_message_received()
        _ = channel.record_error()

        assert channel.metrics.messages_sent == 0
        assert channel.metrics.messages_received == 0
        assert channel.metrics.error_count == 0


# =============================================================================
# CommunicationChannel Integration Tests
# =============================================================================


class TestCommunicationChannelIntegration:
    """Integration tests for CommunicationChannel with realistic scenarios."""

    def test_email_channel_lifecycle(self):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Work Email",
            config=ChannelConfig(
                credentials={"user": "work@example.com", "password": "secret"},
                endpoint="imap.example.com",
                settings={"port": 993, "ssl": True},
            ),
            created_at=datetime(2026, 1, 1),
        )

        # Activate after setup
        active_channel = channel.activate()
        assert active_channel.status == ChannelStatus.ACTIVE

        # Simulate receiving and sending messages
        after_receive = active_channel.record_message_received()
        after_send = after_receive.record_message_sent()

        assert after_send.metrics.messages_received == 1
        assert after_send.metrics.messages_sent == 1

        # Simulate error
        after_error = after_send.record_error().mark_error()
        assert after_error.status == ChannelStatus.ERROR
        assert after_error.metrics.error_count == 1

        # Recover
        recovered = after_error.activate()
        assert recovered.status == ChannelStatus.ACTIVE

    def test_discord_channel_with_webhook(self):
        channel = CommunicationChannel(
            id="660e8400-e29b-41d4-a716-446655440001",
            channel_type=ChannelType.DISCORD,
            name="Server Notifications",
            config=ChannelConfig(
                credentials={"bot_token": "discord_token"},
                webhook_url="https://discord.com/api/webhooks/123/abc",
            ),
        )

        assert channel.config.webhook_url is not None
        assert channel.channel_type == ChannelType.DISCORD

    def test_sms_channel_creation(self):
        channel = CommunicationChannel(
            id="770e8400-e29b-41d4-a716-446655440002",
            channel_type=ChannelType.SMS,
            name="SMS Alerts",
            config=ChannelConfig(
                credentials={"api_sid": "twilio_sid", "api_token": "twilio_token"},
                endpoint="https://api.twilio.com/2010-04-01",
            ),
        )

        assert channel.channel_type == ChannelType.SMS

    def test_voice_channel_creation(self):
        channel = CommunicationChannel(
            id="880e8400-e29b-41d4-a716-446655440003",
            channel_type=ChannelType.VOICE,
            name="Voice Calls",
            config=ChannelConfig(
                credentials={"api_key": "voice_api_key"},
            ),
        )

        assert channel.channel_type == ChannelType.VOICE

    def test_push_notification_channel(self):
        channel = CommunicationChannel(
            id="990e8400-e29b-41d4-a716-446655440004",
            channel_type=ChannelType.PUSH_NOTIFICATION,
            name="Mobile Notifications",
            config=ChannelConfig(
                credentials={"fcm_key": "firebase_key"},
                settings={"priority": "high", "ttl": 86400},
            ),
        )

        assert channel.channel_type == ChannelType.PUSH_NOTIFICATION
        assert channel.config.settings["priority"] == "high"


# =============================================================================
# Edge Cases
# =============================================================================


class TestCommunicationChannelEdgeCases:
    """Edge case tests for CommunicationChannel."""

    def test_single_char_name(self):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="A",
            config=ChannelConfig(credentials={}),
        )
        assert channel.name == "A"

    def test_name_with_special_chars(self):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Email @work (Primary) - 2026",
            config=ChannelConfig(credentials={}),
        )
        assert "@" in channel.name
        assert "(" in channel.name

    def test_name_with_unicode(self):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Email professionnel",
            config=ChannelConfig(credentials={}),
        )
        assert channel.name == "Email professionnel"

    def test_config_with_nested_settings(self):
        config = ChannelConfig(
            credentials={"key": "value"},
            settings={
                "nested": {"deep": {"value": 42}},
                "list": [1, 2, 3],
            },
        )
        assert config.settings["nested"]["deep"]["value"] == 42
        assert config.settings["list"] == [1, 2, 3]

    def test_uuid_case_insensitive(self):
        upper_uuid = "550E8400-E29B-41D4-A716-446655440000"
        channel = CommunicationChannel(
            id=upper_uuid,
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=ChannelConfig(credentials={}),
        )
        assert channel.id == upper_uuid

    def test_custom_initial_status(self):
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=ChannelConfig(credentials={}),
            status=ChannelStatus.ACTIVE,
        )
        assert channel.status == ChannelStatus.ACTIVE

    def test_custom_initial_metrics(self):
        metrics = ChannelMetrics(
            messages_sent=100,
            messages_received=50,
            error_count=5,
        )
        channel = CommunicationChannel(
            id="550e8400-e29b-41d4-a716-446655440000",
            channel_type=ChannelType.EMAIL,
            name="Test",
            config=ChannelConfig(credentials={}),
            metrics=metrics,
        )
        assert channel.metrics.messages_sent == 100
