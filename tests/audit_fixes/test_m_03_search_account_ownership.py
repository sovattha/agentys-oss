# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-3 (2026-05-05) — `/api/emails/search` trustait `account_id` query.

Bug : `search_emails` (`app/api/search.py:280`) parsait `account_id` depuis
`request.args` avec une seule validation (`int>=1`) puis le passait à
`search_service.search_emails(account_id=...)`. Le blueprint guard
`apply_auth_guard` (`auth.py:254-314`) settait `g.auth_user` mais ne
cross-checkait jamais le JWT email vs le query param. Conséquence : un
JWT user pouvait énumérer tout autre tenant en variant
`?account_id=<other>` → réponse contenait subject+sender+body[:200] des
emails de l'autre tenant.

Sibling `/search/suggestions` (`:386`) avait le même trou (sender/subject
auto-completion exposait les contacts/sujets cross-tenant).

Fix : aligner sur le pattern `agent_marketplace.py:487` (faq_stats /
faq_history) :
  - Header/query empty → résout via `_resolve_account_id_for_user()` (JWT).
  - Header/query supplied → `require_owned_account_id()` ; sentinel ≠ owned
    → 404 "account not found".

Run: `pytest tests/audit_fixes/test_m_03_search_account_ownership.py -v`
"""

from __future__ import annotations

import inspect
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


@pytest.fixture
def stub_search_service():
    """Make the search service succeed cheaply — the ownership gate must
    be the deciding factor, not a 500 from a missing dependency."""
    fake_resp = MagicMock()
    fake_resp.results = []
    fake_resp.total = 0
    fake_resp.duration_ms = 0.0
    fake_resp.has_more = False
    fake_resp.to_dict.return_value = {
        "query": "",
        "total": 0,
        "results": [],
        "duration_ms": 0.0,
        "has_more": False,
    }

    fake_svc = MagicMock()
    fake_svc.search_emails.return_value = fake_resp
    fake_svc.get_suggestions.return_value = {"senders": [], "subjects": [], "labels": []}
    with patch("app.api.search.get_search_service", return_value=fake_svc):
        yield fake_svc


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# 1. Source-level lock — keep the fix shape against future refactors.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fn_name", ["search_emails", "search_suggestions"])
def test_search_handler_calls_require_owned_account_id(fn_name):
    """The handler body MUST resolve account_id via require_owned_account_id
    when a value is supplied — never trust the raw query string."""
    from app.api import search as search_mod

    src = inspect.getsource(search_mod)
    start = src.find(f"def {fn_name}(")
    assert start > 0, f"{fn_name} not found in app.api.search"
    next_def = src.find("\ndef ", start + 1)
    if next_def < 0:
        next_def = len(src)
    body = src[start:next_def]

    assert "require_owned_account_id" in body, (
        f"M-3 regression: {fn_name} no longer calls `require_owned_account_id` — "
        "any JWT user can supply ?account_id=<other> and read another tenant's "
        "emails. Mirror the agent_marketplace.py:487 pattern."
    )
    assert "_NO_ACCOUNT_SENTINEL" in body, (
        f"M-3: {fn_name} must compare the result of require_owned_account_id "
        "against `_NO_ACCOUNT_SENTINEL` and 404 on mismatch (not silently "
        "fall through to the JWT-resolved account)."
    )


# --------------------------------------------------------------------------- #
# 2. Behavioural — cross-tenant `account_id` must be rejected with 404.
# --------------------------------------------------------------------------- #


def test_search_rejects_unowned_account_id_query(client, stub_search_service):
    """User B (JWT bob) tries `?account_id=<alice's id>`. The handler must
    NOT call `search_service.search_emails(account_id=alice_id)` — it must
    short-circuit with 404 before any data is read."""
    fake_payload = {"sub": "42", "email": "bob@example.com", "id": 42}

    # require_owned_account_id() returns -1 (sentinel) when the JWT user
    # doesn't own the account. We patch it directly because the real
    # resolver requires a populated DB.
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.routes_helpers.require_owned_account_id",
        return_value=-1,  # _NO_ACCOUNT_SENTINEL
    ):
        resp = client.get(
            "/api/emails/search?q=invoice&account_id=999",
            headers={"Authorization": "Bearer bob-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    # Either 404 (preferred — explicit "not yours") or 403 acceptable;
    # the critical assertion is that the search service was NOT called.
    assert resp.status_code in (403, 404), (
        f"M-3 leak: cross-tenant account_id got {resp.status_code}, expected 404. "
        f"Body: {resp.get_data(as_text=True)[:200]}"
    )
    stub_search_service.search_emails.assert_not_called(), (
        "M-3 P0: handler called search_emails with an unowned account_id — "
        "the cross-tenant data leak is still open."
    )


def test_suggestions_rejects_unowned_account_id_query(client, stub_search_service):
    """Same shape — `/search/suggestions` must also enforce ownership.
    Pre-fix it leaked sender/subject autocompletes from any tenant."""
    fake_payload = {"sub": "42", "email": "bob@example.com", "id": 42}

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.routes_helpers.require_owned_account_id",
        return_value=-1,
    ):
        resp = client.get(
            "/api/emails/search/suggestions?q=meet&account_id=999",
            headers={"Authorization": "Bearer bob-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code in (403, 404)
    stub_search_service.get_suggestions.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. Owned account_id must still work (regression guard for the happy path).
# --------------------------------------------------------------------------- #


def test_search_allows_owned_account_id(client, stub_search_service):
    """Owner of `account_id=5` calling `?account_id=5` must succeed (200).
    `require_owned_account_id` returns the int → handler proceeds."""
    fake_payload = {"sub": "5", "email": "alice@example.com", "id": 5}

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.routes_helpers.require_owned_account_id",
        return_value=5,  # owned
    ):
        resp = client.get(
            "/api/emails/search?q=invoice&account_id=5",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, (
        f"Owner lost access to her own search: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
    stub_search_service.search_emails.assert_called_once()
    # Critical: the int passed downstream is the resolved owned id (5),
    # NEVER the raw query-string string.
    call_kwargs = stub_search_service.search_emails.call_args.kwargs
    assert call_kwargs.get("account_id") == 5


def test_search_falls_back_to_jwt_when_no_account_id(client, stub_search_service):
    """No `account_id` in query → resolve from JWT. Pre-fix this path also
    used the raw query string (None), losing the ownership guarantee."""
    fake_payload = {"sub": "5", "email": "alice@example.com", "id": 5}

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.routes_helpers._resolve_account_id_for_user",
        return_value=5,
    ):
        resp = client.get(
            "/api/emails/search?q=meet",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    call_kwargs = stub_search_service.search_emails.call_args.kwargs
    assert call_kwargs.get("account_id") == 5, (
        "M-3 regression: empty account_id must resolve from JWT, not pass None."
    )


# --------------------------------------------------------------------------- #
# 4. Bad-format account_id should still return a 400 — NOT silently use JWT.
# --------------------------------------------------------------------------- #


def test_search_rejects_malformed_account_id(client, stub_search_service):
    """Malformed `account_id=abc` → 400 (not silent JWT-fallback). Avoids
    masking client bugs."""
    fake_payload = {"sub": "5", "email": "alice@example.com", "id": 5}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.get(
            "/api/emails/search?q=meet&account_id=abc",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 400
    stub_search_service.search_emails.assert_not_called()
