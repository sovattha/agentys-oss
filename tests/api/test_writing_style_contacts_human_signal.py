# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the contact-count floor on `GET /writing-style/contacts`.

Historical context: this file originally covered a bidirectional-filter human
signal escape hatch. The current product contract is stricter: once contact
counts exist, a contact must meet the floor (`sent_count >= 2` and
`received_count >= 1`) to appear. Human signals still matter for false-positive
noise addresses and for the fresh-account fallback, but they no longer bypass
the count floor when the bidirectional set is populated.

All addresses below are synthetic fixtures. Keep real customer/contact emails
out of regression tests; the fixture names should describe the behavior under
test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


def _classified_contact(email: str, nickname: str = "Alexandra") -> dict:
    """Profile fully filled by onboarding (has all three human signals)."""
    return {
        "email": email,
        "nickname": nickname,
        "preferred_greeting": "Bonjour {first_name},",
        "preferred_closing": "À bientôt,",
        "langue": "français",
        "langue_variante": "fr-CA",
        "formality_override": "casual",
    }


def _placeholder_contact(email: str) -> dict:
    """Bidirectional backfill placeholder: no human signals at all."""
    return {"email": email}


def _signal_only_contact(email: str, *, signal: str) -> dict:
    """Contact with exactly ONE of the three human signals populated."""
    base = {"email": email}
    if signal == "nickname":
        base["nickname"] = "Sam"
    elif signal == "greeting":
        base["preferred_greeting"] = "Hi {first_name},"
    elif signal == "closing":
        base["preferred_closing"] = "Cheers,"
    return base


def _manually_added_contact(email: str) -> dict:
    """Contact created via Settings → Training "Add a contact": the PUT locks
    formality (manual_lock) but the user may set NO other human signal. This is
    the bug-2026-06-23 case — it must survive the bidirectional floor even with
    zero sent/received counts, because the user explicitly created it."""
    return {
        "email": email,
        "formality_override": "casual",
        "formality_locked": True,
    }


@pytest.fixture
def flask_app():
    """Minimal Flask app that registers the api_bp under test."""
    from app.api.routes_helpers import api_bp

    app = Flask(__name__)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _wire_endpoint(monkeypatch, account_id: int, profile_dict: dict, bidirectional_emails: list[str]):
    """Stub the dependencies of `list_contact_styles` so the route runs in
    isolation: account resolver, container/style_store, DB session for the
    bidirectional query."""
    from app.api import routes_learning as rl

    monkeypatch.setattr(rl._rh, "_resolve_account_id_cached", lambda: account_id)

    fake_profile = MagicMock()
    fake_profile.contact_profiles = profile_dict
    container = MagicMock()
    container.get_writing_style_store.return_value.load.return_value = fake_profile
    monkeypatch.setattr(rl._rh, "_get_container", lambda: container)

    rl._contact_counts_reconciled.add(account_id)

    fake_session = MagicMock()
    fake_session.__enter__ = lambda s: fake_session
    fake_session.__exit__ = lambda *a: None
    fake_session.execute.return_value.all.return_value = [
        (addr,) for addr in bidirectional_emails
    ]
    monkeypatch.setattr("app.db.database.get_db_session", lambda: fake_session)


def test_one_way_classified_contact_is_hidden_once_counts_exist(client, monkeypatch):
    """A one-way contact with a fully-classified profile is still hidden once
    the count floor is active."""
    sent_only = "sent.only.classified@example.test"
    bidirectional = "bidirectional.person@example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            sent_only: _classified_contact(sent_only),
            bidirectional: _classified_contact(bidirectional, nickname="Bidirectional"),
        },
        bidirectional_emails=[bidirectional],
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert sent_only not in surfaced
    assert bidirectional in surfaced


def test_manually_added_contact_survives_bidirectional_floor(client, monkeypatch):
    """Bug 2026-06-23: a contact the user explicitly added via Settings →
    Training (`formality_locked=True`, no counts yet, NOT in the bidirectional
    set) must still be surfaced — otherwise it vanishes on the next reload and
    'l'ajout ne s'enregistre pas'. formality_locked is the manual-intent marker
    (auto-derivation never sets it)."""
    added = "freshly.added.person@example.test"
    bidirectional = "bidirectional.person@example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            added: _manually_added_contact(added),
            bidirectional: _classified_contact(bidirectional, nickname="Bidirectional"),
        },
        bidirectional_emails=[bidirectional],  # `added` is deliberately absent
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert added in surfaced
    assert bidirectional in surfaced


def test_manually_added_noise_address_survives(client, monkeypatch):
    """A manual add whose address trips the noise heuristic (shared inbox of a
    small company) still survives once the user explicitly locked it — the noise
    filter also honours the manual-intent marker."""
    support = "support@smallcorp.example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={support: _manually_added_contact(support)},
        bidirectional_emails=[],  # empty → fresh-account fallback disables bidi filter
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert support in surfaced


def test_one_way_placeholder_stays_hidden(client, monkeypatch):
    """A one-way contact with no signals (typical newsletter) is still hidden."""
    bidirectional = "bidirectional.person@example.test"
    newsletter = "team@newsletter.example.test"
    receipt_sender = "receipt@transactional.example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            newsletter: _placeholder_contact(newsletter),
            receipt_sender: _placeholder_contact(receipt_sender),
            bidirectional: _classified_contact(bidirectional, nickname="Bidirectional"),
        },
        bidirectional_emails=[bidirectional],
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert newsletter not in surfaced
    assert receipt_sender not in surfaced
    assert bidirectional in surfaced


def test_fresh_account_fallback_keeps_contacts_with_single_signal(client, monkeypatch):
    """Without bidirectional evidence yet, the fresh-account fallback keeps
    contacts with at least one human signal."""
    nickname_only = "nickname.only@example.test"
    greeting_only = "greeting.only@example.test"
    closing_only = "closing.only@example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            nickname_only: _signal_only_contact(nickname_only, signal="nickname"),
            greeting_only: _signal_only_contact(greeting_only, signal="greeting"),
            closing_only: _signal_only_contact(closing_only, signal="closing"),
        },
        bidirectional_emails=[],
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert surfaced == {nickname_only, greeting_only, closing_only}


def test_noise_address_with_human_signal_still_passes(client, monkeypatch):
    """The noise-filter exception (pre-existing) still works."""
    support_sender = "support@automated.example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            support_sender: _classified_contact(support_sender, nickname="Sam"),
        },
        bidirectional_emails=[],
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert support_sender in surfaced


def test_noise_placeholder_still_hidden(client, monkeypatch):
    """A noise address WITHOUT signals (genuine automated sender) stays hidden."""
    no_reply = "noreply@notifications.example.test"
    _wire_endpoint(
        monkeypatch,
        account_id=13,
        profile_dict={
            no_reply: _placeholder_contact(no_reply),
        },
        bidirectional_emails=[],
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert no_reply not in surfaced


# --------------------------------------------------------------------------- #
# Audit 2026-05-27: self-exclusion + sent>=2 one-shot trim.
# These need independent control of the bidirectional set, the sent>=2 set and
# the account's own email, so they use a side_effect-based wiring (2 ordered
# queries: bidirectional, then sent>=2) + a stubbed AccountRepository.get.
# A profile must carry >=1 enriched contact so the endpoint skips its
# onboarding rehydrate path (which would fire an extra DB query).
# --------------------------------------------------------------------------- #

def _wire_endpoint_split(
    monkeypatch, account_id, profile_dict, *, bidirectional_emails, sent_ge2_emails, self_email
):
    from types import SimpleNamespace
    from app.api import routes_learning as rl
    from app.db.repositories import account_repository as ar

    monkeypatch.setattr(rl._rh, "_resolve_account_id_cached", lambda: account_id)

    fake_profile = MagicMock()
    fake_profile.contact_profiles = profile_dict
    container = MagicMock()
    container.get_writing_style_store.return_value.load.return_value = fake_profile
    monkeypatch.setattr(rl._rh, "_get_container", lambda: container)

    rl._contact_counts_reconciled.add(account_id)

    def _result(emails):
        m = MagicMock()
        m.all.return_value = [(e,) for e in emails]
        return m

    fake_session = MagicMock()
    fake_session.__enter__ = lambda s: fake_session
    fake_session.__exit__ = lambda *a: None
    # Ordered: 1) bidirectional query, 2) sent>=2 query.
    fake_session.execute.side_effect = [_result(bidirectional_emails), _result(sent_ge2_emails)]
    monkeypatch.setattr("app.db.database.get_db_session", lambda: fake_session)

    # AccountRepository(sess).get(account_id).email -> the account's own address.
    monkeypatch.setattr(
        ar.AccountRepository, "get", lambda self, _id: SimpleNamespace(email=self_email)
    )


def test_self_address_excluded_even_when_classified_and_bidirectional(client, monkeypatch):
    """The account's own address must never appear — even with a full profile,
    bidirectional evidence and sent>=2. (You don't write to yourself.)"""
    self_addr = "owner@example.test"
    real_contact = "real.person@example.test"
    _wire_endpoint_split(
        monkeypatch,
        account_id=13,
        profile_dict={
            self_addr: _classified_contact(self_addr, nickname="Moi"),
            real_contact: _classified_contact(real_contact, nickname="Réel"),
        },
        bidirectional_emails=[self_addr, real_contact],
        sent_ge2_emails=[self_addr, real_contact],
        self_email=self_addr,
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert self_addr not in surfaced
    assert real_contact in surfaced


def test_empty_bidirectional_evidence_uses_fresh_account_fallback(client, monkeypatch):
    """If no bidirectional evidence exists yet, keep the fresh-account fallback:
    surface the onboarding profile instead of rendering an empty contact list."""
    one_shot = "one.shot.placeholder@example.test"
    recurring = "recurring.person@example.test"
    classified_one_shot = "classified.oneshot@example.test"
    _wire_endpoint_split(
        monkeypatch,
        account_id=13,
        profile_dict={
            one_shot: _placeholder_contact(one_shot),
            recurring: _placeholder_contact(recurring),
            classified_one_shot: _classified_contact(classified_one_shot, nickname="Ami"),
        },
        bidirectional_emails=[],
        sent_ge2_emails=[recurring],
        self_email="owner@account.test",
    )
    resp = client.get("/api/writing-style/contacts")
    assert resp.status_code == 200
    surfaced = {c["email"].lower() for c in resp.get_json()["contacts"]}
    assert one_shot in surfaced
    assert recurring in surfaced
    assert classified_one_shot in surfaced
