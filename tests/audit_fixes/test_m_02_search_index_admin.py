# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-2 (issue #536) — `/search/rebuild-index` & `/search/optimize-index`
admin-only manquant.

Bug: la docstring de ``rebuild_search_index`` (``app/api/search.py:411``)
disait explicitement "This is an admin endpoint" mais le décorateur
``@require_admin`` n'avait jamais été ajouté. Sibling
``optimize_search_index`` (``:437``) avait le même trou. Les deux
opérations sont CPU-bound sur la table ``emails`` complète et tiennent
le SQLite write lock pendant plusieurs minutes — DoS trivial : un user
authentifié spammait l'endpoint et starvait toutes les écritures.

Fix: ``@require_admin`` sur les deux routes. Pattern aligné sur
``/sync/trigger`` (#535), ``/push/broadcast`` (#523),
``/gmail/watch/renew-due`` (#530). Lesson de référence :
`tasks/lessons.md` → "Auth ≠ Admin".

Run: ``pytest tests/audit_fixes/test_m_02_search_index_admin.py -v``
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


GUARDED_POST_ROUTES = [
    "/api/emails/search/rebuild-index",
    "/api/emails/search/optimize-index",
]


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
    """Make rebuild/optimize succeed cheaply — admin gate must be the
    deciding factor, not a missing dependency producing a 500 that would
    mask a 403 regression."""
    fake_svc = MagicMock()
    fake_svc.rebuild_index.return_value = True
    fake_svc.optimize_index.return_value = True
    with patch("app.api.search.get_search_service", return_value=fake_svc):
        yield fake_svc


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: a non-admin authenticated user MUST NOT trigger the rebuild
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", GUARDED_POST_ROUTES)
def test_route_rejects_non_admin_jwt(client, stub_search_service, route):
    """M-2: a normal magic-link JWT must hit 403 on each guarded route.
    The CPU-bound rebuild must NEVER fire for non-admins."""
    fake_payload = {"sub": "42", "email": "attacker@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=False,
    ):
        resp = client.post(
            route,
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, (
        f"M-2 leak on {route}: non-admin JWT got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    # Critical: the underlying service must NOT have been called even once.
    stub_search_service.rebuild_index.assert_not_called()
    stub_search_service.optimize_index.assert_not_called()


@pytest.mark.parametrize("route", GUARDED_POST_ROUTES)
def test_route_rejects_anonymous_remote(client, stub_search_service, route):
    """Anonymous remote caller (no Bearer) must be rejected — the
    blueprint auth guard already 401s these, but the parameter test
    locks in defence-in-depth if the guard is ever relaxed."""
    resp = client.post(route, environ_base=REMOTE_ATTACKER)
    assert resp.status_code in (401, 403), (
        f"M-2 leak on {route}: anonymous remote got {resp.status_code}"
    )
    stub_search_service.rebuild_index.assert_not_called()
    stub_search_service.optimize_index.assert_not_called()


# --------------------------------------------------------------------------- #
# Sanity: a real admin keeps access
# --------------------------------------------------------------------------- #


def test_rebuild_allows_admin_jwt(client, stub_search_service):
    """Admin JWT must still trigger the rebuild (200)."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=True,
    ):
        resp = client.post(
            "/api/emails/search/rebuild-index",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    stub_search_service.rebuild_index.assert_called_once()


def test_optimize_allows_admin_jwt(client, stub_search_service):
    """Admin JWT must still trigger the optimize (200)."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=True,
    ):
        resp = client.post(
            "/api/emails/search/optimize-index",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    stub_search_service.optimize_index.assert_called_once()


# --------------------------------------------------------------------------- #
# Loopback Tauri WITHOUT a JWT is rejected (admin gate isn't host-relaxed).
# Pattern aligned with `/push/broadcast` (#523, cf. test_c_03_push_broadcast_*).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", GUARDED_POST_ROUTES)
def test_loopback_no_jwt_must_be_rejected(client, stub_search_service, route):
    """Tauri loopback callers are NOT exempt from @require_admin. Without
    a Bearer the @require_auth wrapper inside @require_admin rejects the
    call — desktop must not bypass admin gating either. Mirrors the
    `/push/broadcast` decision (#523)."""
    resp = client.post(route)  # no Authorization, default REMOTE_ADDR=127.0.0.1
    assert resp.status_code == 401
    stub_search_service.rebuild_index.assert_not_called()
    stub_search_service.optimize_index.assert_not_called()
