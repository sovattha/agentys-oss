# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""`/api/learning/all` — Auto-Label accuracy + per-account scoping.

Two concerns covered here:

1. **"Précision globale" semantics.** It used to be computed over learned-rule
   firings (`total_rule_matches`), so a user who had corrected nothing saw a
   *blank* instead of the intuitive 100 %. It is now measured over the labelled
   population (`by_label`): zero corrections → 100 %; never empty while there is
   labelled mail; None only when nothing is labelled.

2. **Account scoping + un-gating (#533).** The endpoint was `@require_admin`
   because its auto-label rules and Savoirs read global, cross-tenant files.
   Every category is now account-scoped — rules via `get_label_store(account_id)`,
   Savoirs via `load_knowledge_from_db(account_id)` with NO global memoire.md
   fallback — so the gate was removed (2026-05-21). These tests pin both the
   non-admin access and the "unresolved account (-1) leaks nothing" guarantee.
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}


def _make_client():
    """A fresh test client per case keeps each patched context isolated."""
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def _rule(**kw):
    """A learned LabelingRule stand-in (SimpleNamespace → JSON-serializable
    attribute reads, unlike MagicMock auto-vivification)."""
    base = dict(
        rule_id="r1",
        label_name="Action",
        condition_type="from",
        condition_value="boss@corp.com",
        use_count=3,
        total_matches=0,
        corrections=0,
        is_active=True,
        disabled_reason=None,
        created_at="2026-05-01T00:00:00Z",
        learned_from="correction",  # truthy → counted as a *learned* rule
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _Container:
    def __init__(self, rules, label_counts):
        labs = MagicMock()
        labs.get_rules.return_value = rules
        labs.get_label_counts.return_value = label_counts
        self._labs = labs
        # Other categories run in their own try/except; keep them cheap/empty.
        self._ls = MagicMock()
        self._ps = MagicMock()
        self._ps.list_all.return_value = []

    def get_label_store(self, account_id=None):
        return self._labs

    def get_learning_service(self):
        return self._ls

    def get_learning_pattern_store(self):
        return self._ps

    def get_draft_store(self):
        return None


def _call(client, *, account_id, rules, label_counts,
          is_admin=True, kb_loader=None):
    """Hit GET /api/learning/all with everything stubbed.

    ``kb_loader`` is the patched ``load_knowledge_from_db`` (a MagicMock when a
    test needs to assert call behaviour); defaults to a no-KB stub.
    """
    container = _Container(rules, label_counts)
    empty_draft_store = MagicMock()
    empty_draft_store.get_rules.return_value = []
    if kb_loader is None:
        kb_loader = MagicMock(return_value=None)
    with ExitStack() as stack:
        for p in (
            patch("app.api.auth._decode_jwt",
                  return_value={"sub": str(account_id), "email": "u@example.com"}),
            patch("app.api.admin._is_admin", return_value=is_admin),
            patch("app.api.routes_learning._resolve_account_id_for_user",
                  return_value=account_id),
            patch("app.api.routes_helpers._get_container", return_value=container),
            patch("app.api.routes_helpers.get_container", return_value=container),
            patch("app.draft_learning.get_draft_learning_store",
                  return_value=empty_draft_store),
            patch("app._prompts_monolith.load_knowledge_from_db", kb_loader),
        ):
            stack.enter_context(p)
        resp = client.get(
            "/api/learning/all",
            headers={"Authorization": "Bearer jwt"},
            environ_base=REMOTE,
        )
    return resp


def _category(resp, cat_id):
    return next(c for c in resp.get_json()["categories"] if c["id"] == cat_id)


def _auto_label(rules, label_counts, account_id=7):
    resp = _call(_make_client(), account_id=account_id,
                 rules=rules, label_counts=label_counts)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return _category(resp, "auto-label")


# --------------------------------------------------------------------------- #
# 1. "Précision globale" — labelled-population semantics
# --------------------------------------------------------------------------- #


def test_accuracy_is_100_when_no_corrections():
    """Labelled mail + zero corrections → 100 %, even though the rule has never
    re-fired (total_matches=0). The old denominator returned None here."""
    cat = _auto_label(
        rules=[_rule(total_matches=0, corrections=0)],
        label_counts={"Action": 12, "Noise": 8, "FYI": 5},
    )
    assert cat["accuracy"] == 100


def test_accuracy_drops_with_corrections():
    """5 corrections out of 25 labelled → (25-5)/25 = 80 %."""
    cat = _auto_label(
        rules=[_rule(total_matches=10, corrections=5)],
        label_counts={"Action": 12, "Noise": 8, "FYI": 5},
    )
    assert cat["accuracy"] == 80


def test_accuracy_none_when_no_labelled_mail():
    """No labelled emails → nothing to evaluate → None (not 0, not 100)."""
    cat = _auto_label(rules=[], label_counts={})
    assert cat["accuracy"] is None


def test_accuracy_floored_at_zero():
    """Corrections exceeding the per-account labelled count must clamp to 0."""
    cat = _auto_label(
        rules=[_rule(total_matches=50, corrections=50)],
        label_counts={"Action": 3},
    )
    assert cat["accuracy"] == 0


# --------------------------------------------------------------------------- #
# 2. Un-gating (#533) — non-admin access + per-account isolation
# --------------------------------------------------------------------------- #


def test_non_admin_gets_200_not_403():
    """The @require_admin gate is gone: an authenticated non-admin with a
    resolved account receives 200 (their own slice), not 403."""
    resp = _call(_make_client(), account_id=7, is_admin=False,
                 rules=[_rule()], label_counts={"Action": 4})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


def test_savoirs_come_from_account_db():
    """Savoirs are parsed from the caller's own DB knowledge, not memoire.md."""
    kb = (
        "## Profil\nName\n\n"
        "## Savoir\n"
        "### Domaine : Crypto\n"
        "Bitcoin halving every 4 years.\n"
        "## Règles\nBe concise.\n"
    )
    resp = _call(_make_client(), account_id=7, is_admin=False,
                 rules=[], label_counts={},
                 kb_loader=MagicMock(return_value=kb))
    savoirs = _category(resp, "savoirs")
    assert savoirs["count"] == 1
    assert "Bitcoin halving" in savoirs["items"][0]["text"]


def test_savoirs_empty_for_unresolved_account_no_global_fallback():
    """Sentinel account (-1): we must NOT read the per-account loader at all
    (and therefore never the global memoire.md it would fall back to) — the
    Savoirs category is empty rather than another tenant's knowledge."""
    kb_loader = MagicMock(return_value="## Savoir\n### X : leak\nshould not show\n")
    resp = _call(_make_client(), account_id=-1, is_admin=False,
                 rules=[], label_counts={}, kb_loader=kb_loader)
    savoirs = _category(resp, "savoirs")
    assert savoirs["count"] == 0
    kb_loader.assert_not_called()


def test_rules_empty_for_unresolved_account():
    """Sentinel account (-1): learned auto-label rules (whose conditions encode
    contact domains) must not be exposed — items is empty even when the stubbed
    store would return rules."""
    cat = _auto_label(
        rules=[_rule(rule_id="leaky", condition_value="ceo@othertenant.com")],
        label_counts={"Action": 2},
        account_id=-1,
    )
    assert cat["count"] == 0
    assert cat["items"] == []
    # by_label still works (it self-scopes via valid_email_ids upstream).
    assert cat["accuracy"] == 100  # 2 labelled, 0 corrections counted
