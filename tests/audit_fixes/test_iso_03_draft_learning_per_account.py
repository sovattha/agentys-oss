# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-03 — `DraftLearningStore` is a process-wide singleton that
persists draft corrections to `~/.agentys/draft_corrections.json` *unkeyed*
by account.

Bug: `app/draft_learning.py:24` defines `_DEFAULT_PATH` and the singleton
`get_draft_learning_store()` returns the same instance for every caller,
so user A's "Salut Marie," correction ends up in user B's drafter prompt.

Fix: `get_draft_learning_store(account_id: int)` returns a per-account
instance that persists at `~/.agentys/draft_corrections/<account_id>.json`.

Run: `pytest tests/audit_fixes/test_iso_03_draft_learning_per_account.py -v`
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(monkeypatch):
    """Redirect the default `~/.agentys` path to a temp dir so tests don't
    pollute the developer's home or each other."""
    tmpdir = tempfile.mkdtemp(prefix="agentys-iso03-")
    monkeypatch.setenv("HOME", tmpdir)
    monkeypatch.setenv("USERPROFILE", tmpdir)  # Windows
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_two_accounts_have_separate_correction_files(isolated_data_dir):
    """ISO-03: a correction recorded under account A MUST NOT appear in the
    corrections list of account B."""
    # Reload module so it picks up the patched HOME (the singleton state
    # also has to be reset between accounts).
    import importlib
    import app.draft_learning as dl
    importlib.reload(dl)

    store_a = dl.get_draft_learning_store(account_id=1)
    store_b = dl.get_draft_learning_store(account_id=2)

    # Different identities — not the same process-wide singleton.
    assert store_a is not store_b, (
        "ISO-03 leak: get_draft_learning_store(1) and (2) returned the SAME "
        "object — corrections are shared across accounts."
    )

    store_a.record_correction(
        email_id="email_alice_1",
        original_draft="Bonjour Madame, Comment allez-vous? Cordialement.",
        sent_body="Salut Marie! Ca va? Bisous.",
        contact="alice-recipient@example.com",
    )

    # The correction was recorded on store_a (sanity check).
    a_section = store_a.get_recent_corrections(
        contact="alice-recipient@example.com", limit=10,
    )
    assert "Salut Marie" in a_section, (
        f"Sanity: store_a should hold the correction, got {a_section!r}"
    )

    # Bob's store must NOT see Alice's correction text.
    b_section = store_b.get_recent_corrections(
        contact="alice-recipient@example.com", limit=10,
    )
    assert "Salut Marie" not in b_section, (
        f"ISO-03 leak: Bob's draft store sees Alice's correction: "
        f"{b_section!r}"
    )


def test_per_account_persistence_paths_are_distinct(isolated_data_dir):
    """ISO-03: the on-disk file path must include the account_id so two
    accounts running on the same host don't overwrite each other."""
    import importlib
    import app.draft_learning as dl
    importlib.reload(dl)

    store_a = dl.get_draft_learning_store(account_id=1)
    store_b = dl.get_draft_learning_store(account_id=2)

    assert store_a._path != store_b._path, (
        f"ISO-03 leak: both accounts persist to the same path "
        f"{store_a._path!r} → corrections will overwrite each other."
    )


def test_singleton_per_account_is_idempotent(isolated_data_dir):
    """Calling `get_draft_learning_store(1)` twice returns the same
    instance (we don't want to lose in-memory state on each lookup)."""
    import importlib
    import app.draft_learning as dl
    importlib.reload(dl)

    s1 = dl.get_draft_learning_store(account_id=1)
    s2 = dl.get_draft_learning_store(account_id=1)
    assert s1 is s2


def test_legacy_no_account_id_still_works(isolated_data_dir):
    """Backward-compat: callers that pass no account_id (Tauri desktop
    legacy) still get a working store. We don't want to break the desktop
    flow during a refactor."""
    import importlib
    import app.draft_learning as dl
    importlib.reload(dl)

    legacy = dl.get_draft_learning_store()
    recorded = legacy.record_correction(
        email_id="legacy_1",
        original_draft="Bonjour Madame, Cordialement.",
        sent_body="Salut, Bisous.",
        contact="x@y.com",
    )
    assert recorded is True
    section = legacy.get_recent_corrections(contact="x@y.com")
    assert "Salut" in section
