# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.push_notification."""

import pytest
from app.domain.entities.push_notification import (
    DevicePlatform,
    PushNotificationStatus,
    PushNotificationCategory,
    DeviceToken,
    PushNotification,
    PushNotificationRecord,
)


# ============================================================================
# Enums
# ============================================================================

class TestDevicePlatform:
    def test_values(self):
        assert DevicePlatform.IOS.value == "ios"
        assert DevicePlatform.ANDROID.value == "android"
        assert DevicePlatform.WEB.value == "web"


class TestPushNotificationStatus:
    def test_values(self):
        assert PushNotificationStatus.PENDING.value == "pending"
        assert PushNotificationStatus.SENT.value == "sent"
        assert PushNotificationStatus.DELIVERED.value == "delivered"
        assert PushNotificationStatus.FAILED.value == "failed"


class TestPushNotificationCategory:
    def test_values(self):
        assert PushNotificationCategory.DRAFT_CREATED.value == "draft.created"
        assert PushNotificationCategory.BUDGET_WARNING.value == "budget.warning"
        assert PushNotificationCategory.INFO.value == "info"


# ============================================================================
# DeviceToken
# ============================================================================

class TestDeviceToken:
    def test_create_valid_token(self):
        token = DeviceToken(token="abc123", platform=DevicePlatform.IOS)
        assert token.token == "abc123"
        assert token.platform == DevicePlatform.IOS
        assert token.is_active is True

    def test_empty_token_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.ANDROID)

    def test_whitespace_token_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="   ", platform=DevicePlatform.ANDROID)

    def test_string_platform_auto_converted(self):
        token = DeviceToken(token="abc", platform="ios")  # type: ignore
        assert token.platform == DevicePlatform.IOS

    def test_to_dict(self):
        token = DeviceToken(
            token="tok123",
            platform=DevicePlatform.ANDROID,
            user_id="user1",
            device_name="Pixel 7",
        )
        d = token.to_dict()
        assert d["token"] == "tok123"
        assert d["platform"] == "android"
        assert d["user_id"] == "user1"
        assert d["device_name"] == "Pixel 7"
        assert d["is_active"] is True

    def test_from_dict(self):
        data = {
            "token": "tok-abc",
            "platform": "web",
            "user_id": "u1",
            "created_at": "2026-03-24T10:00:00",
            "is_active": False,
        }
        token = DeviceToken.from_dict(data)
        assert token.token == "tok-abc"
        assert token.platform == DevicePlatform.WEB
        assert token.is_active is False

    def test_from_dict_roundtrip(self):
        original = DeviceToken(
            token="round-trip",
            platform=DevicePlatform.IOS,
            user_id="u1",
            device_name="iPhone 15",
            app_version="2.0.1",
        )
        d = original.to_dict()
        restored = DeviceToken.from_dict(d)
        assert restored.token == original.token
        assert restored.platform == original.platform
        assert restored.user_id == original.user_id


# ============================================================================
# PushNotification
# ============================================================================

class TestPushNotification:
    def test_create_valid_notification(self):
        notif = PushNotification(title="New Draft", body="A draft is ready")
        assert notif.title == "New Draft"
        assert notif.body == "A draft is ready"
        assert notif.category == PushNotificationCategory.INFO
        assert notif.sound is True
        assert notif.ttl == 86400

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="content")

    def test_empty_body_raises(self):
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="")

    def test_whitespace_title_raises(self):
        with pytest.raises(ValueError):
            PushNotification(title="   ", body="content")

    def test_string_category_auto_converted(self):
        notif = PushNotification(title="Test", body="Body", category="draft.created")  # type: ignore
        assert notif.category == PushNotificationCategory.DRAFT_CREATED

    def test_to_dict(self):
        notif = PushNotification(
            title="Alert",
            body="Budget exceeded",
            category=PushNotificationCategory.BUDGET_WARNING,
            badge=3,
            priority="high",
        )
        d = notif.to_dict()
        assert d["title"] == "Alert"
        assert d["category"] == "budget.warning"
        assert d["badge"] == 3
        assert d["priority"] == "high"
        assert d["data"] == {}

    def test_to_dict_with_data(self):
        notif = PushNotification(
            title="Draft",
            body="Ready",
            data={"email_id": "e1", "draft_id": "d1"},
        )
        d = notif.to_dict()
        assert d["data"]["email_id"] == "e1"


# ============================================================================
# PushNotificationRecord
# ============================================================================

class TestPushNotificationRecord:
    def test_create_record(self):
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="tok-abc",
        )
        assert record.status == PushNotificationStatus.PENDING
        assert record.message_id is None

    def test_to_dict(self):
        notif = PushNotification(title="Test", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="tok-abc",
            status=PushNotificationStatus.SENT,
            message_id="msg-1",
        )
        d = record.to_dict()
        assert d["device_token"] == "tok-abc"
        assert d["status"] == "sent"
        assert d["message_id"] == "msg-1"
        assert d["notification"]["title"] == "Test"
