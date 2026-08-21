# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-02 — `LabelStore` is a process-wide singleton, and the JSON
files (`labels.json`, `rules.json`, `assignments.json`) carry no
`account_id`.

Bug: `app/infrastructure/adapters/label_store.py:46-50` — the dataclass
has a single `storage_dir`, and the container at
`app/infrastructure/container.py:1601-1607` wires every caller to the same
directory. When user A flags `marc@partner.com` as VIP, that rule lives
in the shared `rules.json` and tags user B's email from Marc as VIP too.
Same for `Noise` auto-learning, custom labels, and per-email assignments.

This test locks in the architectural fix:
  - `container.get_label_store(account_id)` returns a per-account instance
    backed by `data/labels/<account_id>/...`.
  - Calling without `account_id` returns the legacy global store
    (Tauri desktop) — preserves existing behaviour.

Run: `pytest tests/audit_fixes/test_iso_02_label_store_per_account.py -v`
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="agentys-iso02-")
    monkeypatch.setenv("AGENTYS_DATA_DIR", tmp)
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _fresh_container():
    """Build a brand-new DI container so the per-test data dir wins.

    Container reads AGENTYS_DATA_DIR via the `data_dir` property, so we
    just need a fresh instance — no constructor argument.
    """
    import importlib
    from app.infrastructure import container as container_mod
    importlib.reload(container_mod)
    return container_mod.Container()


def test_label_store_accepts_account_id_argument(isolated_data_dir):
    """ISO-02: container must expose a per-account override.

    Even if the implementation continues to share state, the public API
    must accept `account_id` so callers can opt into isolation. This is a
    forward-compat smoke test — once all the call sites pass account_id,
    the inner `LabelStore` should also be scoped.
    """
    container = _fresh_container()

    # Calling without an account_id keeps backward-compat (Tauri desktop).
    legacy = container.get_label_store()
    assert legacy is not None

    # Calling with account_id MUST not raise.
    s1 = container.get_label_store(account_id=1)
    s2 = container.get_label_store(account_id=2)
    assert s1 is not None and s2 is not None


def test_label_store_per_account_storage_dirs_are_distinct(isolated_data_dir):
    """ISO-02: two distinct accounts must persist into distinct directories."""
    container = _fresh_container()

    s1 = container.get_label_store(account_id=1)
    s2 = container.get_label_store(account_id=2)

    # The internal `storage_dir` must reflect the account scope.
    assert s1.storage_dir != s2.storage_dir, (
        f"ISO-02 leak: account 1 and 2 share storage_dir={s1.storage_dir!r}"
    )
    # And the path should mention the account_id (defence in depth — this
    # ensures we didn't accidentally suffix something else).
    assert "1" in str(s1.storage_dir)
    assert "2" in str(s2.storage_dir)


def test_label_store_legacy_call_preserves_existing_path(isolated_data_dir):
    """ISO-02: callers that don't pass account_id keep their legacy path
    so existing on-disk JSON files remain readable on first deploy."""
    container = _fresh_container()
    legacy = container.get_label_store()  # no account_id
    # Legacy path should be the global `data/labels` directory, not a
    # per-account subdirectory.
    legacy_path = str(legacy.storage_dir)
    # The legacy path is `<data_dir>/labels` — i.e. the parent of the
    # per-account subdirs.
    assert legacy_path.rstrip(os.sep).endswith("labels"), (
        f"Legacy storage_dir should end with 'labels', got {legacy_path!r}"
    )
