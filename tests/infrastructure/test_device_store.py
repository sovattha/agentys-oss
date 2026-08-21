# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le module device_store."""

import json
import pytest
from datetime import datetime

from app.infrastructure.device_store import (
    JsonFileDeviceStore,
    get_device_store,
    reset_device_store,
)
from app.domain.entities.push_notification import DeviceToken, DevicePlatform


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def store_file(tmp_path):
    return tmp_path / "devices.json"


@pytest.fixture
def store(store_file):
    return JsonFileDeviceStore(store_file)


@pytest.fixture(autouse=True)
def clean_singleton():
    reset_device_store()
    yield
    reset_device_store()


# ============================================================================
# TESTS — Register
# ============================================================================

class TestRegister:
    def test_register_returns_device_token(self, store):
        device = store.register("tok123", "ios", user_id="u1", device_name="iPhone")
        assert isinstance(device, DeviceToken)
        assert device.token == "tok123"
        assert device.platform == DevicePlatform.IOS
        assert device.user_id == "u1"

    def test_register_persists_to_file(self, store, store_file):
        store.register("tok123", "android")
        data = json.loads(store_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["token"] == "tok123"

    def test_register_multiple_devices(self, store):
        store.register("tok1", "ios")
        store.register("tok2", "android")
        store.register("tok3", "web")
        assert len(store.get_all()) == 3

    def test_register_overwrites_same_token(self, store):
        store.register("tok1", "ios", device_name="Old")
        store.register("tok1", "ios", device_name="New")
        devices = store.get_all()
        assert len(devices) == 1
        assert devices[0].device_name == "New"


# ============================================================================
# TESTS — Unregister
# ============================================================================

class TestUnregister:
    def test_unregister_existing(self, store):
        store.register("tok1", "ios")
        assert store.unregister("tok1") is True
        assert store.get_all() == []

    def test_unregister_nonexistent(self, store):
        assert store.unregister("nonexistent") is False

    def test_unregister_persists(self, store, store_file):
        store.register("tok1", "ios")
        store.unregister("tok1")
        data = json.loads(store_file.read_text())
        assert len(data["devices"]) == 0


# ============================================================================
# TESTS — Get
# ============================================================================

class TestGet:
    def test_get_existing(self, store):
        store.register("tok1", "ios")
        device = store.get("tok1")
        assert device is not None
        assert device.token == "tok1"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent") is None


# ============================================================================
# TESTS — Get All
# ============================================================================

class TestGetAll:
    def test_get_all_returns_active_only(self, store):
        store.register("tok1", "ios")
        store.register("tok2", "android")
        store.deactivate("tok2")
        active = store.get_all()
        assert len(active) == 1
        assert active[0].token == "tok1"

    def test_get_all_filter_by_user(self, store):
        store.register("tok1", "ios", user_id="user_a")
        store.register("tok2", "android", user_id="user_b")
        store.register("tok3", "web", user_id="user_a")
        devices = store.get_all(user_id="user_a")
        assert len(devices) == 2
        assert all(d.user_id == "user_a" for d in devices)

    def test_get_all_empty(self, store):
        assert store.get_all() == []


# ============================================================================
# TESTS — Get Tokens
# ============================================================================

class TestGetTokens:
    def test_returns_token_strings(self, store):
        store.register("tok1", "ios")
        store.register("tok2", "android")
        tokens = store.get_tokens()
        assert set(tokens) == {"tok1", "tok2"}

    def test_filter_by_user(self, store):
        store.register("tok1", "ios", user_id="a")
        store.register("tok2", "ios", user_id="b")
        tokens = store.get_tokens(user_id="a")
        assert tokens == ["tok1"]


# ============================================================================
# TESTS — Update Last Used
# ============================================================================

class TestUpdateLastUsed:
    def test_updates_last_used(self, store):
        store.register("tok1", "ios")
        assert store.get("tok1").last_used_at is None
        store.update_last_used("tok1")
        assert store.get("tok1").last_used_at is not None

    def test_update_nonexistent_no_error(self, store):
        store.update_last_used("nonexistent")  # Should not raise


# ============================================================================
# TESTS — Deactivate
# ============================================================================

class TestDeactivate:
    def test_deactivate_existing(self, store):
        store.register("tok1", "ios")
        assert store.deactivate("tok1") is True
        device = store.get("tok1")
        assert device.is_active is False

    def test_deactivate_nonexistent(self, store):
        assert store.deactivate("nonexistent") is False

    def test_deactivated_excluded_from_get_all(self, store):
        store.register("tok1", "ios")
        store.deactivate("tok1")
        assert store.get_all() == []


# ============================================================================
# TESTS — Persistance & Chargement
# ============================================================================

class TestPersistence:
    def test_load_from_existing_file(self, store_file):
        # Écrire un fichier valide
        data = {
            "devices": [{
                "token": "existing_tok",
                "platform": "android",
                "user_id": "u1",
                "device_name": "Pixel",
                "app_version": "1.0",
                "created_at": datetime.now().isoformat(),
                "last_used_at": None,
                "is_active": True,
            }],
            "updated_at": datetime.now().isoformat(),
        }
        store_file.write_text(json.dumps(data))

        store = JsonFileDeviceStore(store_file)
        assert len(store.get_all()) == 1
        assert store.get("existing_tok").device_name == "Pixel"

    def test_load_corrupted_file(self, store_file):
        store_file.write_text("not valid json")
        store = JsonFileDeviceStore(store_file)
        assert store.get_all() == []

    def test_load_nonexistent_file(self, tmp_path):
        store = JsonFileDeviceStore(tmp_path / "nonexistent.json")
        assert store.get_all() == []

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "path" / "devices.json"
        store = JsonFileDeviceStore(nested)
        store.register("tok1", "web")
        assert nested.exists()


# ============================================================================
# TESTS — Singleton
# ============================================================================

class TestSingleton:
    def test_get_device_store_with_path(self, tmp_path):
        store = get_device_store(tmp_path / "test_devices.json")
        assert store is not None

    def test_reset_clears_singleton(self, tmp_path):
        store1 = get_device_store(tmp_path / "d1.json")
        reset_device_store()
        store2 = get_device_store(tmp_path / "d2.json")
        assert store1 is not store2
