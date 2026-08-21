# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for `DELETE /api/training/reset-all` cross-tenant wipe.

Issue #525 (audit security.md C-5): the handler was authenticated but had no
per-tenant scoping. A single authenticated DELETE wiped, for ALL tenants:

  * `knowledge/memoire.md` (global file at `container.config.knowledge_path`)
  * `data/learning/learned_patterns.json` (no `account_id` column)
  * `LabelStore` rules + `assignments.json` (the global label store at
    `data/labels/`, used by Tauri-singleton installs and any caller that
    doesn't pass an account_id)
  * The `_writing_style_store` singleton in the container — reset to None,
    forcing every other tenant in the same process to re-instantiate the
    store on its next access (a cross-tenant cache invalidation).

These tests lock in the fix:

  1. Caller without a resolved account → 401 (no silent no-op against the
     global state).
  2. The global file `memoire.md` is NOT written from this endpoint.
  3. `learned_patterns.json` is NOT deleted from this endpoint.
  4. `container._writing_style_store` is NOT reset to None.
  5. `container.get_label_store(account_id=...)` is called WITH the caller's
     account_id (per-account store at `data/labels/<account_id>/`), never
     with the global default.

pytest tests/api/test_training_reset_all_scope.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def app_client():
    from app.api.app import create_app
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield app, client


def _fake_container(tmp_path: Path) -> MagicMock:
    """Build a container double for the reset-all handler.

    `knowledge_path` points inside tmp_path so a regression that re-enables
    the wipe would surface as the file losing content. `data_dir` similarly
    redirects `learned_patterns.json` away from the real project state.
    """
    container = MagicMock(name="container")
    container.config.knowledge_path = tmp_path / "knowledge" / "memoire.md"
    container.data_dir = tmp_path / "data"

    # Seed the supposed-to-survive files with sentinel content.
    container.config.knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    container.config.knowledge_path.write_text(
        "GLOBAL DO NOT WIPE", encoding="utf-8"
    )
    learned = container.data_dir / "learning" / "learned_patterns.json"
    learned.parent.mkdir(parents=True, exist_ok=True)
    learned.write_text('{"global":"do-not-wipe"}', encoding="utf-8")

    # Per-account label store — the fix routes through this code path.
    label_store = MagicMock(name="label_store")
    label_store.get_rules.return_value = []
    label_store.storage_dir = str(tmp_path / "labels" / "42")
    Path(label_store.storage_dir).mkdir(parents=True, exist_ok=True)
    container.get_label_store.return_value = label_store

    # Writing-style store: `delete()` returns True (had a profile).
    style_store = MagicMock(name="style_store")
    style_store.delete.return_value = True
    container.get_writing_style_store.return_value = style_store

    # Sentinel to detect cross-tenant cache invalidation: if anyone sets
    # `_writing_style_store = None`, the assertion catches it.
    container._writing_style_store = style_store
    return container


# --------------------------------------------------------------------------- #
# 1. Caller without a resolved account is rejected.
# --------------------------------------------------------------------------- #

def test_reset_all_rejects_caller_without_resolved_account(app_client, tmp_path):
    """No JWT-mapped account → 401; never silently runs against global state."""
    _, client = app_client

    container = _fake_container(tmp_path)

    with patch(
        "app.api.routes_learning._resolve_account_id_for_user",
        return_value=-1,
    ), patch("app.api.routes_learning._rh._get_container", return_value=container):
        resp = client.delete("/api/training/reset-all")

    assert resp.status_code == 401, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "NO_ACCOUNT_SCOPE"

    # And critically: none of the global state was touched.
    assert (
        container.config.knowledge_path.read_text(encoding="utf-8")
        == "GLOBAL DO NOT WIPE"
    )
    learned = container.data_dir / "learning" / "learned_patterns.json"
    assert learned.exists()
    container.get_label_store.assert_not_called()


# --------------------------------------------------------------------------- #
# 2. Authenticated tenant: global files are NOT touched.
# --------------------------------------------------------------------------- #

def test_reset_all_does_not_wipe_global_memoire_md(app_client, tmp_path):
    """`knowledge/memoire.md` is shared across tenants — must not be rewritten."""
    _, client = app_client
    container = _fake_container(tmp_path)

    with patch(
        "app.api.routes_learning._resolve_account_id_for_user",
        return_value=42,
    ), patch("app.api.routes_learning._rh._get_container", return_value=container), \
         patch("app.api.routes_learning._rh.get_db_session") as gd, \
         patch("app.draft_learning.get_draft_learning_store"):
        gd.return_value.__enter__.return_value = MagicMock()
        gd.return_value.__exit__.return_value = False
        resp = client.delete("/api/training/reset-all")

    assert resp.status_code == 200, resp.get_json()
    # File content must be unchanged — no write happened.
    assert (
        container.config.knowledge_path.read_text(encoding="utf-8")
        == "GLOBAL DO NOT WIPE"
    )
    body = resp.get_json()
    assert body["results"]["memoire_md"].startswith("skipped")


def test_reset_all_does_not_unlink_global_learned_patterns(app_client, tmp_path):
    """`learned_patterns.json` has no account_id column — must not be deleted."""
    _, client = app_client
    container = _fake_container(tmp_path)

    with patch(
        "app.api.routes_learning._resolve_account_id_for_user",
        return_value=42,
    ), patch("app.api.routes_learning._rh._get_container", return_value=container), \
         patch("app.api.routes_learning._rh.get_db_session") as gd, \
         patch("app.draft_learning.get_draft_learning_store"):
        gd.return_value.__enter__.return_value = MagicMock()
        gd.return_value.__exit__.return_value = False
        resp = client.delete("/api/training/reset-all")

    assert resp.status_code == 200, resp.get_json()
    learned = container.data_dir / "learning" / "learned_patterns.json"
    assert learned.exists(), "learned_patterns.json must NOT be unlinked"
    assert learned.read_text(encoding="utf-8") == '{"global":"do-not-wipe"}'
    body = resp.get_json()
    assert body["results"]["learned_patterns"].startswith("skipped")


# --------------------------------------------------------------------------- #
# 3. The label store call is per-account-scoped (not global).
# --------------------------------------------------------------------------- #

def test_reset_all_uses_per_account_label_store(app_client, tmp_path):
    """`get_label_store` must be called WITH `account_id=<caller>`."""
    _, client = app_client
    container = _fake_container(tmp_path)

    with patch(
        "app.api.routes_learning._resolve_account_id_for_user",
        return_value=42,
    ), patch("app.api.routes_learning._rh._get_container", return_value=container), \
         patch("app.api.routes_learning._rh.get_db_session") as gd, \
         patch("app.draft_learning.get_draft_learning_store"):
        gd.return_value.__enter__.return_value = MagicMock()
        gd.return_value.__exit__.return_value = False
        resp = client.delete("/api/training/reset-all")

    assert resp.status_code == 200, resp.get_json()
    container.get_label_store.assert_called_once_with(account_id=42)


# --------------------------------------------------------------------------- #
# 4. The writing-style store singleton is NOT reset (cross-tenant cache).
# --------------------------------------------------------------------------- #

def test_reset_all_does_not_invalidate_writing_style_store_singleton(
    app_client, tmp_path
):
    """`container._writing_style_store` must survive — `delete(account_id)`
    invalidates per-account cache by mtime; dropping the singleton would
    force every OTHER tenant in the process to rebuild its store too."""
    _, client = app_client
    container = _fake_container(tmp_path)
    style_store_before = container._writing_style_store

    with patch(
        "app.api.routes_learning._resolve_account_id_for_user",
        return_value=42,
    ), patch("app.api.routes_learning._rh._get_container", return_value=container), \
         patch("app.api.routes_learning._rh.get_db_session") as gd, \
         patch("app.draft_learning.get_draft_learning_store"):
        gd.return_value.__enter__.return_value = MagicMock()
        gd.return_value.__exit__.return_value = False
        resp = client.delete("/api/training/reset-all")

    assert resp.status_code == 200, resp.get_json()
    # Per-account delete still happens.
    container.get_writing_style_store.return_value.delete.assert_called_once_with(42)
    # Singleton is intact (was style_store_before, still IS).
    assert container._writing_style_store is style_store_before
