"""
Tests for the per-label email-volume breakdown (`by_label`) on
GET /api/learning/all — the auto-label category.

`by_label` reports how many emails carry each label, counted **across all
folders** (inbox + archived + trash) — the auto-sorter's total observable
output, not the count of learned-rule firings and not inbox-only.

Covers: the `[{label, email_count}]` shape sourced from
`LabelStore.get_label_counts`, biggest-first ordering, the all-folders SQL
scope (no `folder` filter), strict account scoping via `valid_email_ids`
(never an unscoped `None`), the no-account / empty / DB-error fallbacks,
custom labels, and that the existing learned-rules fields are untouched.

Copyright (C) 2026 Agentys - All Rights Reserved.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_auth():
    """`/learning/all` is admin-gated (audit H-7 / #533). Inject an admin JWT."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        yield


def _rule(label, *, total_matches=4, corrections=0):
    """A learned label rule, shaped like `LabelStore.get_rules()` entries."""
    return SimpleNamespace(
        rule_id=f"rule-{label}",
        label_name=label,
        condition_type="sender_domain",
        condition_value="example.com",
        use_count=total_matches,
        total_matches=total_matches,
        corrections=corrections,
        is_active=True,
        disabled_reason=None,
        created_at="2026-05-01T00:00:00",
        learned_from="correction",
    )


def _call_learning_all(
    client,
    *,
    label_counts,
    email_ids=("e1", "e2", "e3"),
    account_id=1,
    rules=None,
    db_raises=False,
):
    """Hit /api/learning/all and return (auto_label_category, label_store, session).

    `label_counts` is what LabelStore.get_label_counts returns; `email_ids` is
    what the all-folders SQL query yields. The draft-ai / draft-rules sections
    are isolated to a clean empty store.
    """
    label_store = Mock()
    label_store.get_rules.return_value = rules or []
    label_store.get_label_counts.return_value = label_counts
    container = Mock()
    container.get_label_store.return_value = label_store

    draft_store = Mock()
    draft_store._corrections = []
    draft_store._positive_count = 0
    draft_store.get_rules.return_value = []

    session = Mock()
    session.execute.return_value.fetchall.return_value = [(eid,) for eid in email_ids]
    db_cm = MagicMock()
    db_cm.__enter__.return_value = session

    get_db_session = MagicMock(side_effect=RuntimeError("db down")) if db_raises \
        else MagicMock(return_value=db_cm)

    with patch("app.api.routes_helpers._get_container", return_value=container), \
         patch("app.api.routes_learning._resolve_account_id_for_user", return_value=account_id), \
         patch("app.db.database.get_db_session", get_db_session), \
         patch("app.draft_learning.get_draft_learning_store", return_value=draft_store):
        resp = client.get(
            "/api/learning/all",
            headers={"Authorization": "Bearer admin-jwt"},
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    auto_label = next(c for c in resp.get_json()["categories"] if c["id"] == "auto-label")
    return auto_label, label_store, session


@pytest.mark.usefixtures("admin_auth")
class TestLearningAllByLabel:
    def test_by_label_reflects_label_counts(self, client):
        """by_label mirrors get_label_counts as [{label, email_count}]."""
        cat, _, _ = _call_learning_all(
            client, label_counts={"Noise": 376, "Action": 105, "FYI": 16},
        )
        assert cat["by_label"] == [
            {"label": "Noise", "email_count": 376},
            {"label": "Action", "email_count": 105},
            {"label": "FYI", "email_count": 16},
        ]

    def test_sorted_by_count_desc_ties_by_name(self, client):
        """Rows are ordered by email_count desc; ties broken by label name."""
        cat, _, _ = _call_learning_all(
            client, label_counts={"Zeta": 5, "Alpha": 5, "Mid": 10},
        )
        assert [e["label"] for e in cat["by_label"]] == ["Mid", "Alpha", "Zeta"]

    def test_counts_all_folders_not_just_inbox(self, client):
        """The email-id query scopes by account + is_sent only — no folder filter."""
        _, _, session = _call_learning_all(client, label_counts={"Noise": 3})

        sql = str(session.execute.call_args[0][0]).lower()
        assert "folder" not in sql, f"expected no folder filter, got: {sql}"
        assert "is_sent = 0" in sql
        assert "account_id = :aid" in sql

    def test_label_counts_scoped_to_account_email_ids(self, client):
        """get_label_counts is called with the account's email-id set — never None."""
        _, label_store, _ = _call_learning_all(
            client, label_counts={"Noise": 3}, email_ids=("a", "b", "c"),
        )
        kwargs = label_store.get_label_counts.call_args.kwargs
        assert kwargs["valid_email_ids"] == {"a", "b", "c"}
        assert kwargs["valid_email_ids"] is not None

    def test_no_account_passes_empty_set_never_none(self, client):
        """Unresolved account -> empty set (yields {}), query skipped — no leak."""
        _, label_store, session = _call_learning_all(
            client, label_counts={}, account_id=None,
        )
        # The all-folders query must not run without a resolved account...
        session.execute.assert_not_called()
        # ...and get_label_counts must still be scoped (empty set, not None).
        assert label_store.get_label_counts.call_args.kwargs["valid_email_ids"] == set()

    def test_custom_labels_included(self, client):
        """Custom (non-default) labels appear in by_label, not just Action/FYI/Noise."""
        cat, _, _ = _call_learning_all(
            client, label_counts={"Noise": 50, "Projet Alpha": 12},
        )
        assert {"label": "Projet Alpha", "email_count": 12} in cat["by_label"]

    def test_empty_label_counts_yields_empty_list(self, client):
        """No assignments -> by_label is an empty list (shape stays stable)."""
        cat, _, _ = _call_learning_all(client, label_counts={})
        assert cat["by_label"] == []

    def test_by_label_empty_on_db_error(self, client):
        """A DB failure degrades by_label to [] without dropping the category."""
        cat, _, _ = _call_learning_all(
            client, label_counts={"Noise": 3}, db_raises=True,
        )
        assert cat["by_label"] == []
        # The rest of the category still renders.
        assert cat["id"] == "auto-label"
        assert "items" in cat

    def test_existing_learned_rule_fields_untouched(self, client):
        """The learned-rules path (items, global accuracy) is unchanged."""
        cat, _, _ = _call_learning_all(
            client,
            label_counts={"Noise": 3},
            rules=[
                _rule("Noise", total_matches=20, corrections=2),
                _rule("Action", total_matches=10, corrections=0),
            ],
        )
        assert cat["count"] == 2
        assert len(cat["items"]) == 2
        assert cat["total_matches"] == 30
        assert cat["total_corrections"] == 2
        # Precision is labelled-population-based (audit autolabel-precision change):
        # (labelled 3 - corrections 2) / 3 = 33%, NOT rule-matches-based (30).
        assert cat["accuracy"] == 33
