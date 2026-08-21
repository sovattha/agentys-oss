# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix H-7 (issue #533) — `routes_learning` GETs leak training data
cross-tenant.

Bug: ces endpoints calculaient `_resolve_account_id_for_user()` puis
droppaient la valeur — les stores sous-jacents (`LearningPatternStore`,
`LearningService`, legacy `feedback_store`) n'ont aucun paramètre
`account_id`. User A pouvait lire les patterns appris et les
comparaisons feedback de User B :

- `GET /api/learning/stats`        (`routes_learning.py:142-156`)
- `GET /api/learning/patterns`     (`:159-177`)
- `GET /api/learning/comparisons`  (`:198-313`)

Fix (transition recommandée par l'audit) : `@require_admin` sur ces
routes. Un magic-link standard ne donne plus accès à ces vues
cross-tenant. La fix structurelle (ajouter `account_id` au schéma de
`LearnedPattern`/`LearningStats`/etc. + filtrer côté store) sera traitée
quand le store sera refait.

(Les routes `/api/followups` et `/api/followups/stats`, gardées par le
même vecteur à l'origine, ont depuis été supprimées avec le système de
relances legacy.)

Run: `pytest tests/audit_fixes/test_h_07_routes_learning_cross_tenant.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


GUARDED_GET_ROUTES = [
    "/api/learning/stats",
    "/api/learning/patterns",
    "/api/learning/comparisons",
    # NOTE: `/api/learning/all` was admin-gated here for the #533 leak (its
    # auto-label rules + Savoirs read global, cross-tenant files). It was
    # un-gated 2026-05-21 once every category became account-scoped, so it must
    # NOT be asserted to 403 for normal users anymore — they now legitimately
    # receive their own slice. Per-account isolation is covered in
    # tests/api/test_learning_all_accuracy.py.
    # 2026-05-30 follow-up: these legacy aggregate endpoints still resolve an
    # account then drop it because the underlying stores are global. Gate them
    # until CostManager/Analytics accept account_id.
    "/api/costs",
    "/api/costs/history",
    "/api/analytics/quality",
    "/api/analytics/comparison",
]

# POST `/learning/analyze` (line 345) was the second site missed by #533:
# the handler resolved `account_id` then dropped it, calling
# `LearningService.analyze_feedback()` (zero-arg, aggregates feedbacks from
# all tenants) → `extract_patterns()` and `generate_adjustment()` mutate the
# global `pattern_store` so user B's POST poisons user A's drafter prompts.
GUARDED_POST_ROUTES = [
    "/api/learning/analyze",
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


class _FakeStats:
    """Plain object so `stats.__dict__ if hasattr(stats, '__dict__') else stats`
    in routes_learning.learning_stats serializes cleanly to JSON."""

    def __init__(self):
        self.total = 0


class _FakeContainer:
    """Hand-rolled stub so the routes can read what they need without
    MagicMock's attribute auto-vivification getting in the way (e.g. it
    auto-creates `get_feedback_store` which would un-dead the dormant
    code path in learning_comparisons)."""

    def __init__(self):
        ls = MagicMock()
        ls.get_stats.return_value = _FakeStats()
        ls.analyze_feedback.return_value = _FakeStats()
        ls.extract_patterns.return_value = []
        ls.generate_adjustment.return_value = None
        self._ls = ls

        ps = MagicMock()
        ps.list_all.return_value = []
        self._ps = ps

        # `/learning/all` reads label_store.get_rules() — must return [] so
        # the admin-OK regression test gets 200 (not a 500 from a missing
        # method on the stub).
        labs = MagicMock()
        labs.get_rules.return_value = []
        self._labs = labs

        analytics = MagicMock()
        analytics.get_quality_metrics.return_value = {}
        analytics.get_ai_vs_human_comparison.return_value = {}
        self._analytics = analytics

    def get_learning_service(self):
        return self._ls

    def get_learning_pattern_store(self):
        return self._ps

    def get_draft_store(self):
        return None

    def get_label_store(self, account_id=None):
        return self._labs

    def get_analytics(self):
        return self._analytics
    # Intentionally no `get_feedback_store` — `learning_comparisons` does
    # `getattr(container, 'get_feedback_store', lambda: None)()` and the
    # route must keep its safe empty-return path in production.


@pytest.fixture
def stub_container():
    """Make the routes' container calls succeed cheaply — we want the
    admin gate to be the deciding factor in the response code, not a
    spurious 500 from a missing dependency."""
    fake_container = _FakeContainer()
    with patch(
        "app.api.routes_helpers._get_container", return_value=fake_container
    ), patch(
        "app.api.routes_helpers.get_container", return_value=fake_container
    ):
        yield fake_container


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: a non-admin authenticated user MUST NOT receive training data
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", GUARDED_GET_ROUTES)
def test_route_rejects_non_admin_jwt(client, stub_container, route):
    """H-7: a normal magic-link JWT must hit 403 on each guarded route."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=False,
    ):
        resp = client.get(
            route,
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, (
        f"H-7 leak on {route}: non-admin JWT got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )


@pytest.mark.parametrize("route", GUARDED_GET_ROUTES)
def test_route_rejects_anonymous_remote(client, stub_container, route):
    """Anonymous remote caller (no Bearer) must be rejected — the api_bp
    auth guard already 401s these, but the parameter test ensures the
    admin decorator's @require_auth wrapper doesn't accidentally let
    something through if the bp guard is later relaxed."""
    resp = client.get(route, environ_base=REMOTE_ATTACKER)
    assert resp.status_code in (401, 403), (
        f"H-7 leak on {route}: anonymous remote got {resp.status_code}"
    )


# --------------------------------------------------------------------------- #
# Sanity: a real admin keeps access
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", GUARDED_GET_ROUTES)
def test_route_allows_admin_jwt(client, stub_container, route):
    """Regression: admin JWT must still pass the gate (200)."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=True,
    ):
        resp = client.get(
            route,
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, (
        f"Admin GET {route} unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )


# --------------------------------------------------------------------------- #
# Defense-in-depth: routes that should NOT have been gated still work for
# normal users (i.e., we didn't accidentally over-gate the whole module)
# --------------------------------------------------------------------------- #


def test_learning_rules_still_works_for_non_admin(client, app):
    """`/api/learning/rules` is account-scoped at the route layer (uses
    `get_draft_learning_store(account_id=...)`). It must NOT have been
    swept up by the H-7 admin gate — non-admin users still need it for
    the Training UI."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}

    fake_store = MagicMock()
    fake_store.get_rules.return_value = []

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=False,
    ), patch(
        "app.draft_learning.get_draft_learning_store",
        return_value=fake_store,
    ):
        resp = client.get(
            "/api/learning/rules",
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, (
        "Non-admin lost access to /learning/rules — H-7 fix over-gated."
    )


# --------------------------------------------------------------------------- #
# Source-grep guard: prevents a future refactor from silently dropping the
# decorator (functools.wraps masks runtime introspection)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fn_name", [
    "learning_stats",
    "learning_patterns",
    "learning_comparisons",
    # 2026-05-05 audit follow-up — #533 also missed POST /learning/analyze:
    "trigger_learning",   # POST /learning/analyze
    # NOTE: learning_all (GET /learning/all) was un-gated 2026-05-21 once every
    # category became account-scoped; it must NOT be asserted to carry
    # @require_admin anymore (isolation covered in test_learning_all_accuracy).
    # 2026-05-30 follow-up — aggregate stores remain global:
    "costs",
    "cost_history",
    "analytics_quality",
    "analytics_comparison",
])
def test_route_source_has_require_admin(fn_name):
    import inspect
    from app.api import routes_learning
    fn = getattr(routes_learning, fn_name)
    src = routes_learning  # source of the module
    module_src = inspect.getsource(src)
    # Find the def line and inspect ~400 chars above for the decorator
    idx = module_src.find(f"def {fn_name}(")
    assert idx > 0, f"{fn_name} not found in routes_learning source"
    preamble = module_src[max(0, idx - 400) : idx]
    assert "@require_admin" in preamble, (
        f"@require_admin missing immediately above {fn_name} — "
        f"the H-7 fix has been regressed.\nPreamble:\n{preamble}"
    )
    # Sanity: function still callable (not removed)
    assert callable(fn)


# --------------------------------------------------------------------------- #
# 2026-05-05 audit follow-up — POST `/learning/analyze` admin gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", GUARDED_POST_ROUTES)
def test_post_route_rejects_non_admin_jwt(client, stub_container, route):
    """Non-admin JWT must hit 403 on POST /learning/analyze. Pre-fix, a
    normal user could POST and (a) read aggregate insights from all
    tenants, (b) trigger global pattern_store mutation that contaminates
    every tenant's drafter prompt."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}
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
        f"learning/analyze leak on {route}: non-admin JWT got "
        f"{resp.status_code} with body {resp.get_data(as_text=True)[:200]}"
    )
    # The service must NOT have been called — the admin gate must intercept
    # before any global state mutation.
    stub_container._ls.analyze_feedback.assert_not_called()
    stub_container._ls.extract_patterns.assert_not_called()


@pytest.mark.parametrize("route", GUARDED_POST_ROUTES)
def test_post_route_allows_admin_jwt(client, stub_container, route):
    """Admin JWT must still pass (200) — regression guard so the fix
    doesn't accidentally lock admins out of the introspection path."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=True,
    ):
        resp = client.post(
            route,
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, (
        f"Admin POST {route} unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
