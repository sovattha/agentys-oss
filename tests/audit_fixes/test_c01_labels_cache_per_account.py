# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix C-1 (2026-04-25 isolation report) — `_labels_cache` was a single
process-global slot. Pre-fix, the first caller filled it; every other
account's `GET /api/labels` then returned the first caller's labels for
60 s, even though `container.get_label_store(account_id=...)` already
supported per-account stores via the ISO-02 seam.

This test locks in:
  - The cache is keyed by `account_id` (None still works for the legacy
    global path, but the entry is its own bucket).
  - Two distinct `account_id` values get distinct cached payloads even
    when the underlying stores hand back different label sets.
  - `_invalidate_labels_cache(account_id=X)` only drops X's slot.

Run: `pytest tests/audit_fixes/test_c01_labels_cache_per_account.py -v`
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache between tests so order doesn't leak."""
    from app.api import labels as labels_mod
    labels_mod._labels_cache.clear()
    yield
    labels_mod._labels_cache.clear()


def _fake_label(name: str):
    obj = MagicMock()
    obj.name = name
    return obj


def test_cache_is_keyed_per_account_id():
    """Different account_id arguments must not share cached label lists."""
    from app.api import labels as labels_mod

    store_a = MagicMock()
    store_a.get_labels.return_value = [_fake_label("a-only")]
    store_b = MagicMock()
    store_b.get_labels.return_value = [_fake_label("b-only")]

    def fake_get_label_store(account_id=None):
        if account_id == 1:
            return store_a
        if account_id == 2:
            return store_b
        raise AssertionError(f"Unexpected account_id {account_id!r}")

    with patch.object(labels_mod, "get_container") as mock_container:
        mock_container.return_value.get_label_store.side_effect = fake_get_label_store
        labels_a = labels_mod._get_labels_cached(account_id=1)
        labels_b = labels_mod._get_labels_cached(account_id=2)

    names_a = {lbl.name for lbl in labels_a}
    names_b = {lbl.name for lbl in labels_b}
    assert names_a == {"a-only"}, "account 1 must see its own labels"
    assert names_b == {"b-only"}, "account 2 must see its own labels"
    assert names_a.isdisjoint(names_b), "no cross-account leak"


def test_second_call_for_same_account_hits_cache():
    """Repeat calls for the same account_id should not re-read the store."""
    from app.api import labels as labels_mod

    store = MagicMock()
    store.get_labels.return_value = [_fake_label("x")]

    with patch.object(labels_mod, "get_container") as mock_container:
        mock_container.return_value.get_label_store.return_value = store
        labels_mod._get_labels_cached(account_id=42)
        labels_mod._get_labels_cached(account_id=42)

    assert store.get_labels.call_count == 1, "second call must hit cache"


def test_invalidation_is_scoped_to_one_account():
    """`_invalidate_labels_cache(X)` must NOT drop other accounts' entries."""
    from app.api import labels as labels_mod

    store_a = MagicMock()
    store_a.get_labels.return_value = [_fake_label("a")]
    store_b = MagicMock()
    store_b.get_labels.return_value = [_fake_label("b")]

    def fake_get_label_store(account_id=None):
        return store_a if account_id == 1 else store_b

    with patch.object(labels_mod, "get_container") as mock_container:
        mock_container.return_value.get_label_store.side_effect = fake_get_label_store
        labels_mod._get_labels_cached(account_id=1)
        labels_mod._get_labels_cached(account_id=2)

        # Drop only account 1
        labels_mod._invalidate_labels_cache(account_id=1)

        labels_mod._get_labels_cached(account_id=1)
        labels_mod._get_labels_cached(account_id=2)

    assert store_a.get_labels.call_count == 2, "account 1 should refetch"
    assert store_b.get_labels.call_count == 1, "account 2 must stay cached"


def test_invalidation_with_none_clears_everything():
    """The legacy `_invalidate_labels_cache()` (no arg) must drop every slot."""
    from app.api import labels as labels_mod

    store = MagicMock()
    store.get_labels.return_value = []

    with patch.object(labels_mod, "get_container") as mock_container:
        mock_container.return_value.get_label_store.return_value = store
        labels_mod._get_labels_cached(account_id=1)
        labels_mod._get_labels_cached(account_id=2)
        assert len(labels_mod._labels_cache) == 2

        labels_mod._invalidate_labels_cache()  # no arg → clear all

    assert labels_mod._labels_cache == {}
