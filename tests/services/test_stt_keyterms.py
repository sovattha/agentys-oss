# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour app/services/stt_keyterms.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import stt_keyterms


@pytest.fixture
def db_path(tmp_path):
    """DB SQLite isolée par test."""
    return str(tmp_path / "stt_keyterms.db")


@pytest.fixture(autouse=True)
def _isolate_thread_local():
    """Reset the module-level thread-local connection between tests so
    each test's tmp_path DB is honoured."""
    import threading
    stt_keyterms._local = threading.local()
    yield


def _label(name, *, is_project=True):
    lbl = MagicMock()
    lbl.name = name
    lbl.is_project = is_project
    return lbl


class TestCustomCRUD:
    def test_add_returns_true_then_false_on_duplicate(self, db_path):
        assert stt_keyterms.add_keyterm(1, "Agentys", db_path=db_path) is True
        assert stt_keyterms.add_keyterm(1, "Agentys", db_path=db_path) is False

    def test_dedup_is_case_insensitive(self, db_path):
        assert stt_keyterms.add_keyterm(1, "Agentys", db_path=db_path) is True
        # "agentys" lowercase should hit the unique index COLLATE NOCASE.
        assert stt_keyterms.add_keyterm(1, "agentys", db_path=db_path) is False

    def test_empty_term_rejected(self, db_path):
        assert stt_keyterms.add_keyterm(1, "", db_path=db_path) is False
        assert stt_keyterms.add_keyterm(1, "   ", db_path=db_path) is False
        assert stt_keyterms.list_custom(1, db_path=db_path) == []

    def test_remove_returns_true_when_deleted(self, db_path):
        stt_keyterms.add_keyterm(1, "Atlas", db_path=db_path)
        assert stt_keyterms.remove_keyterm(1, "Atlas", db_path=db_path) is True
        assert stt_keyterms.list_custom(1, db_path=db_path) == []

    def test_remove_case_insensitive(self, db_path):
        stt_keyterms.add_keyterm(1, "Atlas", db_path=db_path)
        assert stt_keyterms.remove_keyterm(1, "ATLAS", db_path=db_path) is True

    def test_remove_unknown_returns_false(self, db_path):
        assert stt_keyterms.remove_keyterm(1, "Nope", db_path=db_path) is False

    def test_account_isolation(self, db_path):
        """Account A's terms must not leak to account B."""
        stt_keyterms.add_keyterm(1, "Atlas", db_path=db_path)
        stt_keyterms.add_keyterm(2, "Phoenix", db_path=db_path)
        assert stt_keyterms.list_custom(1, db_path=db_path) == ["Atlas"]
        assert stt_keyterms.list_custom(2, db_path=db_path) == ["Phoenix"]


class TestListAuto:
    def test_filters_to_is_project_true(self):
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = [
                _label("Atlas", is_project=True),
                _label("FYI", is_project=False),
                _label("Phoenix", is_project=True),
            ]
            gc.return_value.get_label_store.return_value = store
            assert stt_keyterms.list_auto(1) == ["Atlas", "Phoenix"]

    def test_returns_empty_on_invalid_account(self):
        assert stt_keyterms.list_auto(-1) == []
        assert stt_keyterms.list_auto(None) == []  # type: ignore[arg-type]

    def test_returns_empty_on_container_error(self):
        with patch("app.infrastructure.container.get_container", side_effect=RuntimeError("boom")):
            assert stt_keyterms.list_auto(1) == []

    def test_empty_label_names_skipped(self):
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = [
                _label("", is_project=True),
                _label("   ", is_project=True),
                _label("Atlas", is_project=True),
            ]
            gc.return_value.get_label_store.return_value = store
            assert stt_keyterms.list_auto(1) == ["Atlas"]


class TestGetKeytermsForAccount:
    def test_base_product_vocabulary_always_included(self, db_path):
        """Device 2026-08-04 : « nouveau test depuis agentys » transcrit sans
        le dernier mot — « Agentys » est un nom propre inconnu du décodeur.
        Le vocabulaire produit de base est TOUJOURS boosté, même sans terme
        custom ni label projet."""
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = []
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path)
            assert "Agentys" in merged

    def test_merges_custom_then_auto(self, db_path):
        stt_keyterms.add_keyterm(1, "Nat", db_path=db_path)
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = [_label("Atlas")]
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path)
            # Custom first (user-curated wins the budget), then auto labels,
            # then base product vocabulary (2026-08-04).
            assert merged == ["Nat", "Atlas", "Agentys"]

    def test_dedup_across_sources(self, db_path):
        """If a project label has the same name as a custom term, dedup keeps
        the custom one (first source now that custom leads the merge)."""
        stt_keyterms.add_keyterm(1, "atlas", db_path=db_path)  # lowercase
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = [_label("Atlas")]
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path)
            # "atlas" une fois — original casing from the custom term wins —
            # plus le vocabulaire produit de base.
            assert merged == ["atlas", "Agentys"]

    def test_truncation_favors_custom_over_auto(self, db_path):
        """When custom + auto exceed the cap, custom words are never dropped in
        favour of auto-seeded labels — auto fills only the leftover slots."""
        for i in range(3):
            stt_keyterms.add_keyterm(1, f"custom{i}", db_path=db_path)
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = [_label(f"auto{i}") for i in range(3)]
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path, cap=4)
            # All 3 custom survive; only 1 auto slot remains.
            assert merged == ["custom0", "custom1", "custom2", "auto0"]

    def test_cap_enforced(self, db_path):
        """Cap=3 → only first 3 terms are kept."""
        for i in range(5):
            stt_keyterms.add_keyterm(1, f"term{i}", db_path=db_path)
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = []
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path, cap=3)
            assert len(merged) == 3
            assert merged == ["term0", "term1", "term2"]

    def test_default_cap_is_50(self, db_path):
        for i in range(60):
            stt_keyterms.add_keyterm(1, f"term{i:02d}", db_path=db_path)
        with patch("app.infrastructure.container.get_container") as gc:
            store = MagicMock()
            store.get_labels.return_value = []
            gc.return_value.get_label_store.return_value = store
            merged = stt_keyterms.get_keyterms_for_account(1, db_path=db_path)
            assert len(merged) == stt_keyterms.KEYTERM_CAP == 50

    def test_invalid_account_returns_empty(self, db_path):
        assert stt_keyterms.get_keyterms_for_account(-1, db_path=db_path) == []
        assert stt_keyterms.get_keyterms_for_account(None, db_path=db_path) == []


class TestNormalize:
    def test_strips_whitespace(self):
        assert stt_keyterms._normalize("  Atlas  ") == "Atlas"

    def test_collapses_internal_whitespace(self):
        assert stt_keyterms._normalize("Atlas  Renovation") == "Atlas Renovation"

    def test_clamps_length(self):
        long = "a" * 200
        result = stt_keyterms._normalize(long)
        assert len(result) == stt_keyterms._MAX_TERM_LEN
