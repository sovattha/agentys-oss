# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from types import SimpleNamespace
from unittest.mock import Mock


class _FakeQuery:
    def __init__(self, account):
        self._account = account

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._account


class _FakeSession:
    def __init__(self, account):
        self._account = account

    def query(self, *_args):
        return _FakeQuery(self._account)


class _FakeSessionContext:
    def __init__(self, account):
        self._account = account

    def __enter__(self):
        return _FakeSession(self._account)

    def __exit__(self, *_args):
        return False


def test_db_account_without_signature_does_not_fallback_to_current_account(monkeypatch):
    """A scoped DB account with no signature must not inherit another account's signature."""
    from app.utils.signature import get_account_signature

    account = Mock()
    account.get_signature.return_value = None

    monkeypatch.setattr(
        "app.db.database.get_db_session",
        lambda: _FakeSessionContext(account),
    )
    monkeypatch.setattr(
        "app.multi_accounts.get_account_manager",
        lambda: SimpleNamespace(
            get_current_account=lambda: SimpleNamespace(
                signature="Wrong account",
                signature_html="<p>Wrong account</p>",
            )
        ),
    )

    assert get_account_signature(account_id=6, html=True) is None
    account.get_signature.assert_called_once_with(html=True)


def test_append_signature_prefers_contact_signature(monkeypatch):
    """Une signature explicitement mémorisée pour un contact prime sur le compte."""
    from app.utils import signature as signature_utils

    monkeypatch.setattr(
        signature_utils,
        "get_contact_signature",
        lambda account_id, recipient_email: "Soso\nAgentys",
    )
    monkeypatch.setattr(
        signature_utils,
        "get_account_signature",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("account signature should not be used")),
    )

    result = signature_utils.append_signature(
        "<p>Merci.</p>",
        account_id=6,
        recipient_email="alex@example.com",
    )

    assert "Soso<br>Agentys" in result


def test_append_signature_falls_back_to_account_signature_without_contact(monkeypatch):
    """Sans préférence contact, le comportement historique reste inchangé."""
    from app.utils import signature as signature_utils

    monkeypatch.setattr(
        signature_utils,
        "get_contact_signature",
        lambda account_id, recipient_email: None,
    )
    monkeypatch.setattr(
        signature_utils,
        "get_account_signature",
        lambda account_id, html=False: "Nathan",
    )

    result = signature_utils.append_signature(
        "Merci.",
        account_id=6,
        is_html=False,
        recipient_email="alex@example.com",
    )

    assert result.endswith("--\nNathan")


def test_append_signature_does_not_duplicate_contact_signature(monkeypatch):
    """Si l'UI a déjà sauvegardé la signature contact en fin de corps, ne pas doubler."""
    from app.utils import signature as signature_utils

    monkeypatch.setattr(
        signature_utils,
        "get_contact_signature",
        lambda account_id, recipient_email: "Soso",
    )

    body = "Merci pour ton message.\n\nSoso"
    result = signature_utils.append_signature(
        body,
        account_id=6,
        recipient_email="alex@example.com",
    )

    assert result == body


def test_append_signature_adds_once_on_clean_html_body(monkeypatch):
    """Un body HTML propre (sans signature) reçoit la signature exactement une fois."""
    from app.utils import signature as signature_utils

    monkeypatch.setattr(signature_utils, "get_contact_signature", lambda *args, **kwargs: None)
    monkeypatch.setattr(signature_utils, "get_account_signature", lambda *a, **kw: "<p>Nathan</p>")

    result = signature_utils.append_signature("<p>Merci.</p>", account_id=1)
    assert result.count('agentys-signature') == 1
    assert result.count('Nathan') == 1


def test_append_signature_html_not_doubled_when_class_marker_present(monkeypatch):
    """Le guard class='agentys-signature' empêche le double ajout serveur → serveur."""
    from app.utils import signature as signature_utils

    monkeypatch.setattr(signature_utils, "get_contact_signature", lambda *args, **kwargs: None)
    monkeypatch.setattr(signature_utils, "get_account_signature", lambda *a, **kw: "<p>Nathan</p>")

    # Corps déjà estampillé par le backend (class="agentys-signature")
    body_server_sig = (
        '<p>Merci.</p>'
        '<div class="agentys-signature" style="margin-top:16px;"><p style="margin:0;line-height:1.4">Nathan</p></div>'
    )
    result = signature_utils.append_signature(body_server_sig, account_id=1)
    assert result.count('agentys-signature') == 1
    assert result.count('Nathan') == 1
