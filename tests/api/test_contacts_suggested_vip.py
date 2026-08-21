# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for GET /api/contacts/suggested-vip — onboarding VIP suggestions.

The endpoint surfaces the contacts the user actually corresponds with so the
onboarding VIP step can offer one-click chips instead of forcing the user to
type names from memory.

Signal: qualify on `received_count >= 1` AND
`sent_count >= _MIN_SENT_FOR_VIP`. This keeps genuine two-way correspondents
while filtering received-only senders and one-off sent replies. Noise
(noreply/automated) is still dropped via `_is_noise_recipient`.

Two layers:
  * Pure-helper unit tests (`_aggregate_top_contacts`) — exhaustive, no Flask/DB.
    This is where the inclusion/exclusion/ranking contract lives.
  * Route integration tests — the 401 account guard and the VIP-exclusion
    wiring (label store + own-email), through the real Flask handler with a
    mocked DB session.

NB: fixtures use the `.test` TLD on purpose. `example.com`, `linkedin.com`,
`amazon.com` etc. live in `_NOISE_DOMAINS` and would be silently dropped.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.api.routes_contacts import (
    _aggregate_top_contacts,
    _extract_addr,
)


# ===========================================================================
# Pure helper — _extract_addr
# ===========================================================================

class TestExtractAddr:
    def test_plain_email_lowercased(self):
        assert _extract_addr("Alice@Acme.Test") == "alice@acme.test"

    def test_angle_bracket_form(self):
        assert _extract_addr("Alice Anderson <alice@acme.test>") == "alice@acme.test"

    def test_none_and_empty(self):
        assert _extract_addr(None) == ""
        assert _extract_addr("   ") == ""

    def test_garbage_without_at_rejected(self):
        assert _extract_addr("not-an-email") == ""


# ===========================================================================
# Pure helper — _aggregate_top_contacts
# ===========================================================================

def _received(*rows):
    """(sender, sender_name, freq) tuples — the inbound-side aggregation."""
    return list(rows)


def _sent(*rows):
    """(recipients_csv, cc_csv) tuples — one row per sent email."""
    return list(rows)


def _sent_n(addr, n):
    """n sent emails addressed to `addr` (To only)."""
    return [(addr, None)] * n


class TestAggregateTopContacts:
    def test_contact_with_repeated_outreach_included(self):
        out = _aggregate_top_contacts(
            _received(("alice@acme.test", "Alice", 3)),
            _sent_n("alice@acme.test", 2),
            exclude_emails=set(),
            limit=6,
        )
        assert out == [{
            "email": "alice@acme.test",
            "name": "Alice",
            "sent_count": 2,
            "received_count": 3,
        }]

    def test_single_send_excluded(self):
        """One email to someone — even if they replied — is not enough. This is
        exactly the one-off reply to a SaaS/transactional sender we must drop."""
        out = _aggregate_top_contacts(
            _received(("svc@acme.test", "Service", 5)),
            _sent(("svc@acme.test", None)),  # sent once
            exclude_emails=set(),
            limit=6,
        )
        assert out == []

    def test_sent_only_contact_excluded_even_when_repeated(self):
        """VIP suggestions require both directions: received >= 1 and sent >= 2."""
        out = _aggregate_top_contacts(
            _received(),  # her replies are not in the local cache
            _sent_n("karine@acme.test", 12),
            exclude_emails=set(),
            limit=6,
        )
        assert out == []

    def test_received_only_contact_excluded(self):
        """Someone who emailed us but we never wrote to (sent=0) is not a contact
        we correspond with — newsletters / cold inbound."""
        out = _aggregate_top_contacts(
            _received(("bob@acme.test", "Bob", 9)),
            _sent(),  # nothing sent
            exclude_emails=set(),
            limit=6,
        )
        assert out == []

    def test_noise_sender_excluded_even_above_gate(self):
        """A noreply@ address can clear the sent gate (auto-reply loops / you
        replied twice), but must never be offered as a VIP."""
        out = _aggregate_top_contacts(
            _received(("noreply@acme.test", "No Reply", 5)),
            _sent_n("noreply@acme.test", 3),
            exclude_emails=set(),
            limit=6,
        )
        assert out == []

    def test_exclude_emails_applied(self):
        """own-email / already-VIP / blocked addresses are filtered out."""
        out = _aggregate_top_contacts(
            _received(("dave@acme.test", "Dave", 4)),
            _sent_n("dave@acme.test", 3),
            exclude_emails={"dave@acme.test"},
            limit=6,
        )
        assert out == []

    def test_ranking_by_sent_then_received(self):
        # sent_count dominates: a low-sent/high-received contact ranks BELOW a
        # high-sent/low-received one (writing TO someone is the strong signal).
        #   heavy: sent5 recv1   mid: sent3 recv10   low: sent2 recv50
        out = _aggregate_top_contacts(
            _received(
                ("heavy@acme.test", "Heavy", 1),
                ("mid@acme.test", "Mid", 10),
                ("low@acme.test", "Low", 50),
            ),
            _sent(*(
                _sent_n("heavy@acme.test", 5)
                + _sent_n("mid@acme.test", 3)
                + _sent_n("low@acme.test", 2)
            )),
            exclude_emails=set(),
            limit=6,
        )
        assert [c["email"] for c in out] == [
            "heavy@acme.test", "mid@acme.test", "low@acme.test",
        ]

    def test_received_breaks_sent_ties(self):
        # equal sent_count (3 each) → higher received_count wins.
        out = _aggregate_top_contacts(
            _received(("a@acme.test", "A", 2), ("b@acme.test", "B", 8)),
            _sent(*(_sent_n("a@acme.test", 3) + _sent_n("b@acme.test", 3))),
            exclude_emails=set(),
            limit=6,
        )
        assert [c["email"] for c in out] == ["b@acme.test", "a@acme.test"]

    def test_limit_respected(self):
        out = _aggregate_top_contacts(
            _received(
                ("a@acme.test", "A", 1),
                ("b@acme.test", "B", 1),
                ("c@acme.test", "C", 1),
            ),
            _sent(*(
                _sent_n("a@acme.test", 4)
                + _sent_n("b@acme.test", 3)
                + _sent_n("c@acme.test", 2)
            )),
            exclude_emails=set(),
            limit=2,
        )
        assert [c["email"] for c in out] == ["a@acme.test", "b@acme.test"]

    def test_to_and_cc_dedup_per_email(self):
        """The same address in both To and Cc of ONE email counts once: here
        email#1 has alice in To+Cc and email#2 in To → sent_count == 2, not 3."""
        out = _aggregate_top_contacts(
            _received(("alice@acme.test", "Alice", 2)),
            _sent(("alice@acme.test", "alice@acme.test"), ("alice@acme.test", None)),
            exclude_emails=set(),
            limit=6,
        )
        assert out[0]["sent_count"] == 2

    def test_name_from_sent_recipients_when_received_name_missing(self):
        """When the received row has no display name, pull it from
        'Name <addr>' in the recipients field so the chip isn't a bare email."""
        out = _aggregate_top_contacts(
            _received(("karine@acme.test", "", 1)),
            _sent(("Karine M <karine@acme.test>", None), ("karine@acme.test", None)),
            exclude_emails=set(),
            limit=6,
        )
        assert out[0]["email"] == "karine@acme.test"
        assert out[0]["name"] == "Karine M"
        assert out[0]["sent_count"] == 2

    def test_received_name_and_addr_normalised(self):
        out = _aggregate_top_contacts(
            _received(("Alice A <Alice@Acme.Test>", "Alice A", 1)),
            _sent(("alice@acme.test", None), ("ALICE@acme.test", None)),
            exclude_emails=set(),
            limit=6,
        )
        assert out == [{
            "email": "alice@acme.test",
            "name": "Alice A",
            "sent_count": 2,
            "received_count": 1,
        }]

    def test_empty_inputs_return_empty(self):
        assert _aggregate_top_contacts(
            [], [], exclude_emails=set(), limit=6
        ) == []


# ===========================================================================
# Route integration — 401 guard + VIP-exclusion wiring
# ===========================================================================

@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _session_with(received_rows, sent_rows):
    """MagicMock session dispatching by column count: the received query has
    3 selected columns (sender, sender_name, count), the sent query has 2
    (recipients, cc)."""
    session = MagicMock()

    def query_factory(*cols):
        rows = received_rows if len(cols) >= 3 else sent_rows
        q = MagicMock()
        q.filter.return_value = q
        q.group_by.return_value = q
        q.all.return_value = rows
        return q

    session.query.side_effect = query_factory
    return session


def test_route_401_when_account_unresolved(client):
    with patch(
        "app.api.routes_contacts._resolve_account_id_cached",
        return_value=-1,
    ):
        resp = client.get("/api/contacts/suggested-vip")
    assert resp.status_code == 401
    assert "Authentication" in resp.get_json()["error"]


def test_route_returns_top_contacts_and_excludes_vip_and_own(client):
    received = [
        ("alice@acme.test", "Alice", 3),     # written-to ≥2 → kept
        ("bob@acme.test", "Bob", 9),          # received-only (sent=0) → dropped
        ("vipguy@acme.test", "VIP Guy", 5),   # written-to but already VIP
        ("me@myco.test", "Me", 4),            # written-to but own email
    ]
    # alice + vipguy each appear in 2 sent emails; me in 2; bob in none.
    sent = [
        ("alice@acme.test, vipguy@acme.test", None),
        ("alice@acme.test, vipguy@acme.test", None),
        ("me@myco.test", None),
        ("me@myco.test", None),
    ]
    session = _session_with(received, sent)

    @contextmanager
    def fake_db_session():
        yield session

    fake_acct = MagicMock()
    fake_acct.email = "me@myco.test"
    fake_mgr = MagicMock()
    fake_mgr.get_account.return_value = fake_acct

    fake_store = MagicMock()
    fake_store.get_vip_senders.return_value = ["vipguy@acme.test"]
    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_store

    with patch("app.api.routes_contacts._resolve_account_id_cached", return_value=7), \
         patch("app.api.routes_contacts._rh.get_db_session", fake_db_session), \
         patch("app.api.routes_contacts._get_blocked_senders_set", return_value=set()), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_mgr), \
         patch("app.infrastructure.container.get_container", return_value=fake_container):
        resp = client.get("/api/contacts/suggested-vip")

    assert resp.status_code == 200
    contacts = resp.get_json()["contacts"]
    emails = [c["email"] for c in contacts]
    assert emails == ["alice@acme.test"], (
        "only alice is a non-VIP, non-self contact written to ≥2×"
    )
    assert contacts[0]["sent_count"] == 2
    assert contacts[0]["received_count"] == 3


def test_route_excludes_blocked_senders(client):
    """A sender the user explicitly hid from autocomplete must not resurface
    as a VIP suggestion."""
    received = [("blocked@acme.test", "Blocked", 4), ("good@acme.test", "Good", 2)]
    sent = [
        ("blocked@acme.test, good@acme.test", None),
        ("blocked@acme.test, good@acme.test", None),
    ]
    session = _session_with(received, sent)

    @contextmanager
    def fake_db_session():
        yield session

    fake_mgr = MagicMock()
    fake_mgr.get_account.return_value = MagicMock(email="me@myco.test")
    fake_store = MagicMock()
    fake_store.get_vip_senders.return_value = []
    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_store

    with patch("app.api.routes_contacts._resolve_account_id_cached", return_value=7), \
         patch("app.api.routes_contacts._rh.get_db_session", fake_db_session), \
         patch("app.api.routes_contacts._get_blocked_senders_set", return_value={"blocked@acme.test"}), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_mgr), \
         patch("app.infrastructure.container.get_container", return_value=fake_container):
        resp = client.get("/api/contacts/suggested-vip")

    assert resp.status_code == 200
    emails = [c["email"] for c in resp.get_json()["contacts"]]
    assert emails == ["good@acme.test"]
