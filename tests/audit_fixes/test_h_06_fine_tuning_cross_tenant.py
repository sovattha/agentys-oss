# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix H-6 (issue #532) — `/corrections` & `/feedbacks` model-poisoning
cross-tenant via `draft_id`.

Bug: `POST /api/fine-tuning/corrections` (`app/api/fine_tuning.py:78-126`)
et `POST /api/fine-tuning/feedbacks` (`:176-220`) acceptaient un `draft_id`
arbitraire dans le body sans vérifier que le caller en était propriétaire.
`UserCorrection.create(...)` puis `correction_store.save(correction)`
landait l'enregistrement dans le pattern_store global et alimentait
`_reinforce_existing_patterns` — User A pouvait empoisonner les drafts
futurs de User B en flouant des "corrections" sur les `draft_id` de B.

Fix: avant le save, on résout l'`account_id` du JWT caller via
`_resolve_account_id_for_user()` puis on appelle
`container.get_draft_history().get_by_id_for_account(draft_id, account_id)`.
404 si la draft n'appartient pas au caller. Pattern aligné sur
`routes_drafts.py:245`.

Run: `pytest tests/audit_fixes/test_h_06_fine_tuning_cross_tenant.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# Aliases for clarity in test bodies.
USER_A = {"sub": "1", "email": "alice@example.com"}
USER_B = {"sub": "2", "email": "bob@example.com"}
ACCOUNT_A = 11
ACCOUNT_B = 22

USER_A_DRAFT_ID = "draft-A-001"
USER_B_DRAFT_ID = "draft-B-999"


def _draft_for(account_id: int):
    """Build a stub draft owned by `account_id` (only the fields the route
    happens to read are populated)."""
    return MagicMock(id="stub", account_id=account_id)


def _history_returning_drafts_owned_by(account_id_to_drafts: dict):
    """Build a fake draft_history that mimics `get_by_id_for_account`'s
    contract: returns the draft only if (draft_id, account_id) matches a
    seeded entry. This lets us assert the route invokes the helper with
    the caller's account_id, not with the body's claim."""

    def get_by_id_for_account(draft_id, account_id):
        for owner, drafts in account_id_to_drafts.items():
            if account_id != owner:
                continue
            for d in drafts:
                if d == draft_id:
                    return _draft_for(owner)
        return None

    fake_history = MagicMock()
    fake_history.get_by_id_for_account.side_effect = get_by_id_for_account
    return fake_history


@pytest.fixture
def stub_two_user_world():
    """Set up a 2-tenant world: account A owns USER_A_DRAFT_ID, account B
    owns USER_B_DRAFT_ID. JWT decoding is stubbed: A's bearer maps to
    account A, B's bearer maps to account B."""
    fake_history = _history_returning_drafts_owned_by({
        ACCOUNT_A: [USER_A_DRAFT_ID],
        ACCOUNT_B: [USER_B_DRAFT_ID],
    })
    fake_container = MagicMock()
    fake_container.get_draft_history.return_value = fake_history

    def fake_resolve():
        from flask import g
        email = (getattr(g, "auth_user", None) or {}).get("email", "")
        if email == USER_A["email"]:
            return ACCOUNT_A
        if email == USER_B["email"]:
            return ACCOUNT_B
        return -1

    def fake_decode(token):
        if token == "user-a-token":
            return USER_A
        if token == "user-b-token":
            return USER_B
        return None

    with patch(
        "app.api.fine_tuning._get_container",
        return_value=fake_container,
    ), patch(
        "app.api.fine_tuning._resolve_account_id_for_user",
        side_effect=fake_resolve,
    ), patch(
        "app.api.auth._decode_jwt",
        side_effect=fake_decode,
    ):
        yield fake_history


# --------------------------------------------------------------------------- #
# Reproduction of the audit attack: User A targets User B's draft_id
# --------------------------------------------------------------------------- #


def test_correction_against_other_users_draft_id_is_404(client, stub_two_user_world):
    """H-6: User A POSTs a correction targeting User B's draft_id. The
    route must respond 404 and `correction_store.save` must NOT run."""
    with patch(
        "app.api.fine_tuning.RecordCorrectionUseCase"
    ) as use_case_cls:
        resp = client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": USER_B_DRAFT_ID,
                "original_text": "Bonjour",
                "corrected_text": "ATTACK_PAYLOAD",
                "user_comment": "poisoning attempt",
            },
            headers={"Authorization": "Bearer user-a-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 404, (
        f"H-6 leak: cross-tenant correction returned {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    # The use-case must never have been instantiated → no save, no
    # pattern reinforcement, nothing landed in the global stores.
    use_case_cls.assert_not_called()


def test_feedback_against_other_users_draft_id_is_404(client, stub_two_user_world):
    """H-6: same vector via the rating channel."""
    with patch(
        "app.api.fine_tuning.RecordFeedbackUseCase"
    ) as use_case_cls:
        resp = client.post(
            "/api/fine-tuning/feedbacks",
            json={
                "draft_id": USER_B_DRAFT_ID,
                "rating": 1,
                "comment": "this draft sucks",
            },
            headers={"Authorization": "Bearer user-a-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 404, (
        f"H-6 leak: cross-tenant feedback returned {resp.status_code}"
    )
    use_case_cls.assert_not_called()


def test_lookup_uses_callers_account_not_body_claim(client, stub_two_user_world):
    """The handler must call get_by_id_for_account with the JWT caller's
    own account_id — never the body's claim. Probe the helper to make
    sure we don't accidentally pass attacker-controlled ids in a future
    refactor."""
    client.post(
        "/api/fine-tuning/corrections",
        json={
            "draft_id": USER_B_DRAFT_ID,
            "original_text": "x",
            "corrected_text": "y",
        },
        headers={"Authorization": "Bearer user-a-token"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    # Helper should have been called with USER_A's account, not USER_B's.
    args_seen = stub_two_user_world.get_by_id_for_account.call_args_list
    assert any(
        call.args == (USER_B_DRAFT_ID, ACCOUNT_A) for call in args_seen
    ), f"expected lookup with caller's account ({ACCOUNT_A}), saw: {args_seen}"
    assert not any(
        call.args == (USER_B_DRAFT_ID, ACCOUNT_B) for call in args_seen
    ), "lookup leaked ACCOUNT_B — handler trusted body claim"


# --------------------------------------------------------------------------- #
# Sanity: legitimate same-user corrections / feedbacks still work
# --------------------------------------------------------------------------- #


def test_same_user_correction_still_works(client, stub_two_user_world):
    """Regression: a user posting a correction on their OWN draft must
    still succeed (201)."""
    fake_use_case_result = MagicMock(
        correction_id="ok",
        correction_types=[],
        has_significant_changes=False,
        patterns_found=0,
    )
    with patch(
        "app.api.fine_tuning.RecordCorrectionUseCase"
    ) as use_case_cls:
        use_case_cls.return_value.execute.return_value = fake_use_case_result
        resp = client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": USER_A_DRAFT_ID,
                "original_text": "Bonjour",
                "corrected_text": "Salut",
            },
            headers={"Authorization": "Bearer user-a-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 201, (
        f"Same-user correction unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
    use_case_cls.return_value.execute.assert_called_once()


def test_same_user_feedback_still_works(client, stub_two_user_world):
    """Regression: a user posting feedback on their OWN draft → 201."""
    fake_result = MagicMock()
    fake_result.feedback_id = "fb-1"
    fake_result.sentiment.value = "positive"
    fake_result.requires_analysis = False

    with patch(
        "app.api.fine_tuning.RecordFeedbackUseCase"
    ) as use_case_cls:
        use_case_cls.return_value.execute.return_value = fake_result
        resp = client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": USER_A_DRAFT_ID, "rating": 5},
            headers={"Authorization": "Bearer user-a-token"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert resp.status_code == 201, (
        f"Same-user feedback unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )


# --------------------------------------------------------------------------- #
# Defense-in-depth: malformed draft_ids are rejected before reaching the DB
# --------------------------------------------------------------------------- #


def test_malformed_draft_id_is_400(client, stub_two_user_world):
    """`_validate_email_id` matches `^[a-zA-Z0-9_\\-@.+:=]+$` — a draft_id
    containing a SQL wildcard or a path separator should be rejected with
    400 before the ownership lookup runs."""
    resp = client.post(
        "/api/fine-tuning/corrections",
        json={
            "draft_id": "../etc/passwd",
            "original_text": "x",
            "corrected_text": "y",
        },
        headers={"Authorization": "Bearer user-a-token"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert resp.status_code == 400
    assert "Invalid draft ID format" in resp.get_data(as_text=True)
    # The ownership lookup must NOT have been touched (early return).
    stub_two_user_world.get_by_id_for_account.assert_not_called()


# --------------------------------------------------------------------------- #
# Source-grep guard: the ownership check must not silently get refactored away
# --------------------------------------------------------------------------- #


def test_record_correction_calls_ownership_helper():
    """If a future refactor moves things around, this test fails loud."""
    import inspect
    from app.api import fine_tuning
    src = inspect.getsource(fine_tuning.record_correction)
    assert "get_by_id_for_account" in src, (
        "record_correction is missing the H-6 ownership check"
    )


def test_record_feedback_calls_ownership_helper():
    import inspect
    from app.api import fine_tuning
    src = inspect.getsource(fine_tuning.record_feedback)
    assert "get_by_id_for_account" in src, (
        "record_feedback is missing the H-6 ownership check"
    )
