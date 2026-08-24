# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-contact writing-style profiles must feed the compose autocomplete.

Bug (2026-05-31): a contact the user had defined a per-contact writing voice
for — ``karine.morel@gmail.com`` — never appeared in the "New message" To:
dropdown. The autocomplete is built solely from the ``Email`` table (senders +
recipients ranked by frequency), so a contact with a style profile but no synced
SENT email (fresh style, or a Gmail SENT historyId sync gap) was invisible.

Fix: after the sent_only filter, ``autocomplete_contacts`` merges in the
``WritingStyleProfile.contact_profiles`` map via ``_merge_style_contacts`` so a
style-defined contact is always suggestable.
"""

from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

from app.api.routes_contacts import _merge_style_contacts


# ── _merge_style_contacts: pure unit tests ──────────────────────────────────


def test_merge_adds_style_only_contact():
    """A style-defined contact with no mail history is added to the pool."""
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"}},
        "karine",
    )
    assert "karine.morel@gmail.com" in contacts_map
    entry = contacts_map["karine.morel@gmail.com"]
    assert entry["name"] == "Karine"
    assert entry["sent"] is True  # user-curated → gets the sent rank boost


def test_merge_matches_email_prefix_even_without_nickname():
    """Typing "k" surfaces Karine via her ADDRESS even with no nickname."""
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com"}},
        "k",
    )
    assert "karine.morel@gmail.com" in contacts_map
    assert contacts_map["karine.morel@gmail.com"]["name"] == ""


def test_merge_matches_on_nickname():
    """A query matching only the nickname still surfaces the contact."""
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"k.m@gmail.com": {"email": "k.m@gmail.com", "nickname": "Karine"}},
        "kari",
    )
    assert "k.m@gmail.com" in contacts_map


def test_merge_skips_non_matching_styles():
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"marc.tremblay@example.com": {"email": "marc.tremblay@example.com", "nickname": "Marc"}},
        "karine",
    )
    assert contacts_map == {}


def test_merge_does_not_duplicate_but_backfills_name():
    """A contact already surfaced from mail history keeps its real frequency
    and only borrows the style nickname when the mail row had no name."""
    contacts_map = {
        "karine.morel@gmail.com": {
            "email": "karine.morel@gmail.com", "name": "", "freq": 9, "sent": True,
        }
    }
    _merge_style_contacts(
        contacts_map,
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"}},
        "karine",
    )
    entry = contacts_map["karine.morel@gmail.com"]
    assert entry["freq"] == 9               # real frequency preserved (no overwrite)
    assert entry["name"] == "Karine"        # name back-filled
    assert len(contacts_map) == 1           # not duplicated


def test_merge_keeps_existing_name_over_nickname():
    contacts_map = {
        "k@x.com": {"email": "k@x.com", "name": "Karine Morel", "freq": 4, "sent": True}
    }
    _merge_style_contacts(
        contacts_map, {"k@x.com": {"email": "k@x.com", "nickname": "K"}}, "k",
    )
    assert contacts_map["k@x.com"]["name"] == "Karine Morel"


def test_merge_respects_blocked_and_own_email():
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {
            "blocked@x.com": {"email": "blocked@x.com", "nickname": "B"},
            "me@x.com": {"email": "me@x.com", "nickname": "Me"},
        },
        "x.com",
        own_email="me@x.com",
        blocked_set={"blocked@x.com"},
    )
    assert contacts_map == {}


def test_merge_empty_query_skips_signalless_contact():
    """Empty focus folds in curated-voice contacts only — a bare profile with no
    nickname/greeting/closing must NOT flood the empty dropdown."""
    contacts_map = {}
    _merge_style_contacts(contacts_map, {"k@x.com": {"email": "k@x.com"}}, "")
    assert contacts_map == {}


def test_merge_empty_query_folds_in_curated_voice_contact():
    """Empty focus (To: clicked, nothing typed) surfaces a contact the user gave
    a writing voice — bug 2026-06-01 (only the 2 indexed sent recipients showed)."""
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"}},
        "",
    )
    assert "karine.morel@gmail.com" in contacts_map
    assert contacts_map["karine.morel@gmail.com"]["sent"] is True


def test_merge_empty_query_folds_in_greeting_only_contact():
    """A curated greeting (no nickname) is also a voice signal on empty focus."""
    contacts_map = {}
    _merge_style_contacts(
        contacts_map,
        {"g@x.com": {"email": "g@x.com", "preferred_greeting": "Coucou {first_name},"}},
        "",
    )
    assert "g@x.com" in contacts_map


def test_merge_none_profiles_is_noop():
    contacts_map = {}
    _merge_style_contacts(contacts_map, None, "karine")
    assert contacts_map == {}


def test_merge_skips_malformed_email():
    contacts_map = {}
    _merge_style_contacts(contacts_map, {"not-an-email": {"nickname": "X"}}, "x")
    assert contacts_map == {}


# ── Endpoint integration ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clear_contacts_cache():
    """The route caches by (account_id, q, sent_only, include_self, limit) for
    60s. Clear before AND after so these tests don't see (or leave) stale rows."""
    from app.api import routes_contacts as _rc
    with _rc._contacts_cache_lock:
        _rc._contacts_cache.clear()
    yield
    with _rc._contacts_cache_lock:
        _rc._contacts_cache.clear()


class _FakeProfile:
    def __init__(self, contact_profiles):
        self.contact_profiles = contact_profiles


class _FakeStyleStore:
    def __init__(self, profile):
        self._p = profile

    def load(self, account_id):
        return self._p


class _FakeContainer:
    def __init__(self, profile):
        self._p = profile

    def get_writing_style_store(self):
        return _FakeStyleStore(self._p)


class _PerAccountStyleStore:
    """load(account_id) returns a DIFFERENT profile per account — models the
    real per-account contact_profiles silos (bug 2026-06-24)."""

    def __init__(self, by_account):
        self._by = by_account  # {account_id: {email: profile_dict}}

    def load(self, account_id):
        return _FakeProfile(self._by.get(account_id, {}))


class _PerAccountContainer:
    def __init__(self, by_account):
        self._by = by_account

    def get_writing_style_store(self):
        return _PerAccountStyleStore(self._by)


def _multi_account_session(owner_uid, sibling_ids):
    """get_db_session() mock: mail queries return no rows, but the new
    sibling-account lookup resolves the resolved account's user_id and the set
    of account ids owned by that user (so the cross-account style merge runs)."""
    session = MagicMock()

    def _query(*args):
        q = MagicMock()
        for m in ("filter", "group_by", "order_by", "limit", "distinct", "join"):
            getattr(q, m).return_value = q
        q.all.return_value = []
        q.scalar.return_value = None
        # Match the resolved column regardless of SQLAlchemy's string form
        # ("Account.id" vs "accounts.id"). Check user_id before id.
        col = str(args[0]) if args else ""
        if col.endswith("user_id"):
            q.scalar.return_value = owner_uid
        elif col.endswith(".id"):
            q.all.return_value = [(sid,) for sid in sibling_ids]
        return q

    session.query.side_effect = _query

    @contextmanager
    def _cm():
        yield session

    return _cm


def _empty_db_session():
    """get_db_session() context-manager mock whose every query returns no rows
    (no senders, no recipients) — isolates the style-merge path."""
    session = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.group_by.return_value = q
    q.all.return_value = []
    session.query.return_value = q

    @contextmanager
    def _cm():
        yield session

    return _cm


def _base_patches(account_id=1):
    """Mocks that let the autocomplete handler run with an empty mailbox."""
    fake_active = MagicMock()
    fake_active.email = "me@example.com"
    fake_mgr = MagicMock()
    fake_mgr.get_account.return_value = fake_active
    fake_mgr.get_all_accounts.return_value = [fake_active]
    db = _empty_db_session()
    return [
        patch("app.api.routes_contacts._resolve_account_id_for_user", return_value=account_id),
        patch("app.api.routes_contacts._resolve_account_id_cached", return_value=account_id),
        patch("app.api.routes_contacts._get_current_account_for_user", return_value=fake_active),
        patch("app.api.routes_contacts._get_blocked_senders_set", return_value=set()),
        patch("app.api.routes_contacts._rh.get_db_session", db),
        patch("app.multi_accounts.get_account_manager", return_value=fake_mgr),
    ]


def _run(client, url, extra_patches):
    entered = []
    try:
        for p in _base_patches() + extra_patches:
            p.__enter__()
            entered.append(p)
        return client.get(url)
    finally:
        for p in reversed(entered):
            p.__exit__(None, None, None)


def test_autocomplete_surfaces_style_only_contact_end_to_end(client):
    """No mail rows at all, but a style profile for Karine → she appears in
    /api/contacts/autocomplete?q=karine (the reported bug)."""
    profile = _FakeProfile(
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"}}
    )
    resp = _run(
        client, "/api/contacts/autocomplete?q=karine",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "karine.morel@gmail.com" in emails


def test_autocomplete_style_contact_works_with_sent_only(client):
    """The compose picker calls with sent_only=true; a style-only contact must
    survive that filter (it's merged AFTER the filter, tagged sent=True)."""
    profile = _FakeProfile(
        {"karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"}}
    )
    resp = _run(
        client, "/api/contacts/autocomplete?q=karine&sent_only=true",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "karine.morel@gmail.com" in emails


def test_autocomplete_empty_focus_surfaces_curated_style_contact(client):
    """Empty focus (no query) — the compose To: field just clicked, sent_only=true
    like the real picker — surfaces a curated-voice style contact, while a bare
    (signalless) profile stays hidden (bug 2026-06-01: only the 2 indexed sent
    recipients showed despite several per-contact styles)."""
    profile = _FakeProfile({
        "karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"},
        "bare@example.com": {"email": "bare@example.com"},  # no voice → must NOT show
    })
    resp = _run(
        client, "/api/contacts/autocomplete?sent_only=true",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "karine.morel@gmail.com" in emails
    assert "bare@example.com" not in emails


def test_autocomplete_empty_focus_orders_richest_curation_first(client):
    """On empty focus the style contacts are ordered most-curated first
    (nickname+greeting+closing > nickname only), then alphabetically — so the
    bounded dropdown is deterministic (user choice 2026-06-01)."""
    profile = _FakeProfile({
        "zoe@x.com": {"email": "zoe@x.com", "nickname": "Zoe"},  # signal 1
        "amy@x.com": {  # signal 3 → first
            "email": "amy@x.com", "nickname": "Amy",
            "preferred_greeting": "Coucou", "preferred_closing": "Bisous",
        },
        "bob@x.com": {"email": "bob@x.com", "nickname": "Bob", "preferred_greeting": "Yo"},  # signal 2
    })
    resp = _run(
        client, "/api/contacts/autocomplete?sent_only=true",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert emails == ["amy@x.com", "bob@x.com", "zoe@x.com"]


def test_autocomplete_empty_focus_caps_at_twelve(client):
    """Empty focus is bounded (~12) even when more style contacts exist — the
    rest are reachable by typing."""
    profile = _FakeProfile({
        f"c{i:02d}@x.com": {"email": f"c{i:02d}@x.com", "nickname": f"C{i:02d}"}
        for i in range(20)
    })
    resp = _run(
        client, "/api/contacts/autocomplete?sent_only=true",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    assert len(resp.get_json()) == 12


def test_autocomplete_empty_focus_excludes_own_account_emails(client):
    """The user's own account addresses must never be suggested, even via the
    style merge on the sent_only path (multi-account: own_email alone may miss a
    profiled other-account address)."""
    profile = _FakeProfile({
        "me@example.com": {"email": "me@example.com", "nickname": "Me"},  # own account
        "karine.morel@gmail.com": {"email": "karine.morel@gmail.com", "nickname": "Karine"},
    })
    resp = _run(
        client, "/api/contacts/autocomplete?sent_only=true",
        [patch("app.api.routes_contacts._rh._get_container", return_value=_FakeContainer(profile))],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "me@example.com" not in emails
    assert "karine.morel@gmail.com" in emails


def test_autocomplete_style_store_failure_does_not_break(client):
    """A style-store exception must never 500 the autocomplete endpoint."""
    boom = MagicMock()
    boom.get_writing_style_store.side_effect = RuntimeError("style store down")
    resp = _run(
        client, "/api/contacts/autocomplete?q=karine",
        [patch("app.api.routes_contacts._rh._get_container", return_value=boom)],
    )
    assert resp.status_code == 200
    assert resp.get_json() == []


# ── Cross-account style merge (bug 2026-06-24) ──────────────────────────────


def test_autocomplete_merges_style_contacts_across_user_accounts(client):
    """Composing from account 1 (no style for Karine) still surfaces her when
    she is styled under the user's OTHER account 2. Per-contact styles are
    siloed per account, but a contact you've given a voice to is "your contact"
    regardless of which of your own accounts you compose from."""
    by_account = {
        1: {},  # compose/resolved account — no style for Karine
        2: {  # the user's other account — Karine lives here
            "karine.morel@gmail.com": {
                "email": "karine.morel@gmail.com", "nickname": "Karine",
            }
        },
    }
    resp = _run(
        client, "/api/contacts/autocomplete?q=karine&sent_only=true",
        [
            patch("app.api.routes_contacts._rh.get_db_session",
                  _multi_account_session(owner_uid=5, sibling_ids=[1, 2])),
            patch("app.api.routes_contacts._rh._get_container",
                  return_value=_PerAccountContainer(by_account)),
        ],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "karine.morel@gmail.com" in emails


def test_autocomplete_loopback_merges_across_null_user_accounts(client):
    """Loopback/Tauri: accounts carry user_id NULL. The sibling set is the other
    NULL-user accounts, so the cross-account merge still works for the single
    local user (the desktop case that surfaced the bug)."""
    by_account = {
        8: {},  # compose/resolved account (empty styles)
        13: {
            "karine.morel@gmail.com": {
                "email": "karine.morel@gmail.com", "nickname": "Karine",
            }
        },
    }
    resp = _run(
        client, "/api/contacts/autocomplete?q=karine&sent_only=true",
        [
            patch("app.api.routes_contacts._resolve_account_id_for_user", return_value=8),
            patch("app.api.routes_contacts._resolve_account_id_cached", return_value=8),
            patch("app.api.routes_contacts._rh.get_db_session",
                  _multi_account_session(owner_uid=None, sibling_ids=[8, 13])),
            patch("app.api.routes_contacts._rh._get_container",
                  return_value=_PerAccountContainer(by_account)),
        ],
    )
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()]
    assert "karine.morel@gmail.com" in emails
