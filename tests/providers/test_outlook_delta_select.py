# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Outlook delta `$select` regression — empty subject/sender on first connect.

Bug (reported 2026-06-23): right after connecting an Outlook account, the inbox
showed every message with an empty sender ("destinataire") and "(No subject)".

Root cause: ``get_current_history_id`` initialised the Microsoft Graph delta
checkpoint with ``$select=id`` only. Microsoft Graph BAKES the original
``$select`` into the ``@odata.deltaLink`` it returns (and into every subsequent
``@odata.nextLink``) — you cannot change it afterwards. So every delta sync
performed via that link came back with **only the message id**: no ``from``, no
``subject``, no ``toRecipients``, no ``receivedDateTime``. ``get_history_changes``
then mapped those id-only dicts through ``_map_raw_dict_to_standard_email``,
producing ``StandardEmail`` rows with ``subject=""`` and ``sender=""`` that
``sync_service`` happily persisted.

These tests model the real Graph contract: the fake transport echoes whatever
``$select`` the caller used into the deltaLink it returns, and a delta resync
projects each message down to exactly the selected fields. With the buggy
``$select=id`` init the resulting emails are blank; with the metadata ``$select``
they carry subject/sender/recipients/date.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

import pytest

from app.providers.outlook_adapter import OutlookAdapter


# A full Graph message dict as the raw delta endpoint would return it when ALL
# fields are selected. The fake transport below projects this down to whatever
# the request's $select actually asks for.
FULL_MSG = {
    "id": "AAMkAGI2THE_ID",
    "from": {"emailAddress": {"address": "alice@contoso.com", "name": "Alice Example"}},
    "toRecipients": [{"emailAddress": {"address": "me@contoso.com", "name": "Me"}}],
    "ccRecipients": [{"emailAddress": {"address": "bob@contoso.com", "name": "Bob"}}],
    "subject": "Quarterly report",
    "body": {"contentType": "html", "content": "<p>Hello there</p>"},
    "receivedDateTime": "2026-06-22T10:30:00Z",
    "isRead": False,
    "hasAttachments": False,
    "conversationId": "conv-1",
    "importance": "normal",
    "categories": [],
    "webLink": "https://outlook.office365.com/owa/?ItemID=THE_ID",
}


class _FakeResponse:
    def __init__(self, status_code=200, json_payload=None):
        self.status_code = status_code
        self.headers = {}
        self._json = json_payload or {}

    def json(self):
        return self._json


def _select_fields(url: str) -> list[str]:
    """Extract the $select field list from a Graph URL (query key '$select')."""
    q = parse_qs(urlparse(url).query)
    raw = q.get("$select", q.get("select", ["id"]))[0]
    return [f.strip() for f in raw.split(",") if f.strip()]


def _make_fake_graph(messages):
    """Build a fake `_graph_request_with_retry` that honours the Graph contract.

    - The delta *init* request (no token) returns an empty page plus an
      ``@odata.deltaLink`` that ECHOES the request's ``$select`` — exactly what
      real Graph does.
    - A delta *resync* (URL carries a deltatoken) returns the supplied messages,
      each PROJECTED down to the fields named in the link's ``$select`` (Graph
      always includes ``id``). This is the behaviour that turned id-only links
      into blank emails.
    """
    base = "https://graph.microsoft.com/v1.0/users/me/mailFolders/inbox/messages/delta"

    def fake(method, url, *, headers=None, timeout=10, max_retries=2, **kwargs):
        fields = _select_fields(url)
        select_qs = ",".join(fields)
        is_resync = ("deltatoken" in url) or ("$deltatoken" in url) or ("skiptoken" in url)
        if not is_resync:
            # INIT: hand back the checkpoint link carrying this $select.
            delta_link = f"{base}?$deltatoken=TOKEN_INIT&$select={select_qs}"
            return _FakeResponse(json_payload={"value": [], "@odata.deltaLink": delta_link})
        # RESYNC: project each message to the requested fields (id always kept).
        projected = [
            {k: v for k, v in m.items() if k == "id" or k in fields}
            for m in messages
        ]
        next_link = f"{base}?$deltatoken=TOKEN_NEXT&$select={select_qs}"
        return _FakeResponse(
            json_payload={"value": projected, "@odata.deltaLink": next_link}
        )

    return fake


@pytest.fixture
def adapter():
    a = OutlookAdapter(account_id="test-account", user_id="me@contoso.com")
    a._access_token = "fake-token"
    # Pretend we are already authenticated so the coroutines skip the OAuth
    # token reload (which would fail with no server-side tokens in tests).
    a._authenticated = True
    a._client = MagicMock()
    return a


def test_delta_synced_email_keeps_subject_and_sender(adapter, monkeypatch):
    """End-to-end: init the delta checkpoint, then resync — the new email must
    arrive with its subject, sender and recipients intact (not blank)."""
    monkeypatch.setattr(
        "app.providers.outlook_adapter._graph_request_with_retry",
        _make_fake_graph([FULL_MSG]),
    )

    # 1. First connect: initialise the delta checkpoint (stored as last_history_id).
    delta_link = adapter.get_current_history_id()
    assert delta_link and delta_link.startswith("http")

    # 2. Next sync tick: pull changes through that exact checkpoint link.
    changes = adapter.get_history_changes(delta_link)
    added = changes["added"]
    assert len(added) == 1
    email = added[0]

    # The regression: these were "" because the deltaLink carried $select=id.
    assert email.subject == "Quarterly report"
    assert email.sender == "alice@contoso.com"
    assert email.sender_name == "Alice Example"
    assert email.to == ["me@contoso.com"]
    assert email.cc == ["bob@contoso.com"]
    assert email.received_at is not None
    assert email.received_at.year == 2026 and email.received_at.month == 6


def test_delta_returns_fresh_checkpoint(adapter, monkeypatch):
    """A healthy delta resync hands back the next checkpoint link (not None)."""
    monkeypatch.setattr(
        "app.providers.outlook_adapter._graph_request_with_retry",
        _make_fake_graph([FULL_MSG]),
    )
    delta_link = adapter.get_current_history_id()
    changes = adapter.get_history_changes(delta_link)
    assert changes["new_history_id"] and changes["new_history_id"].startswith("http")


def test_poisoned_id_only_checkpoint_self_heals(adapter, monkeypatch):
    """A legacy id-only checkpoint (created before the fix) must NOT persist
    blank emails: the resync drops them and returns new_history_id=None so
    sync_service falls back to a full re-init."""
    monkeypatch.setattr(
        "app.providers.outlook_adapter._graph_request_with_retry",
        _make_fake_graph([FULL_MSG]),
    )
    # A deltaLink whose baked-in $select is id-only (the poisoned legacy token).
    poisoned = (
        "https://graph.microsoft.com/v1.0/users/me/mailFolders/inbox/messages/"
        "delta?$deltatoken=LEGACY_TOKEN&$select=id"
    )
    changes = adapter.get_history_changes(poisoned)
    assert changes["new_history_id"] is None, "must force a full re-init"
    assert changes["added"] == [], "blank id-only rows must not be stored"
    assert changes.get("poisoned") is True, "must flag the heal for an inbox backfill"


def test_delta_init_select_includes_message_metadata(adapter, monkeypatch):
    """Guard: the checkpoint link must request the metadata fields, not id-only,
    so the baked-in $select yields usable rows on every later delta sync."""
    captured = {}

    def capturing_fake(method, url, *, headers=None, timeout=10, max_retries=2, **kwargs):
        if ("deltatoken" not in url) and ("$deltatoken" not in url):
            captured["init_url"] = url
        return _make_fake_graph([FULL_MSG])(
            method, url, headers=headers, timeout=timeout, max_retries=max_retries, **kwargs
        )

    monkeypatch.setattr(
        "app.providers.outlook_adapter._graph_request_with_retry", capturing_fake
    )

    delta_link = adapter.get_current_history_id()
    init_fields = set(_select_fields(captured["init_url"]))
    # Must carry the human-visible metadata, otherwise the deltaLink is poisoned.
    for required in ("id", "from", "subject", "toRecipients", "receivedDateTime"):
        assert required in init_fields, f"delta init $select missing '{required}'"

    # And the link Graph hands back inherits that same $select.
    assert "subject" in set(_select_fields(delta_link))
