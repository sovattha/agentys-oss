# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for Outlook display-name mojibake repair.

Audit 2026-05-18: Microsoft Graph returns ``message.from_.email_address.name``
already double-decoded UTF-8 → Latin-1 ("Crypto UniversitÃ©" instead of
"Crypto Université"). The IMAP/Gmail paths repair this inside
_parse_email_address; the Outlook path didn't — every accented sender name in
the inbox rendered as mojibake.
"""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from datetime import datetime
from types import SimpleNamespace

from app.providers.outlook_adapter import OutlookAdapter


def _make_message(name: str, subject: str = "Hello") -> SimpleNamespace:
    """Minimal stub matching the msgraph Message shape used by the adapter."""
    return SimpleNamespace(
        id="msg-1",
        from_=SimpleNamespace(
            email_address=SimpleNamespace(
                address="cours.universite@gmail.com",
                name=name,
            )
        ),
        to_recipients=[],
        cc_recipients=[],
        subject=subject,
        body=None,
        received_date_time=datetime(2026, 5, 18, 12, 0, 0),
        is_read=False,
        has_attachments=False,
        conversation_id="conv-1",
        flag=None,
        importance=None,
        categories=[],
        web_link=None,
    )


class TestOutlookSenderNameRepair:
    def setup_method(self) -> None:
        # Bypass the network setup — we only exercise _map_to_standard_email.
        self.adapter = OutlookAdapter.__new__(OutlookAdapter)

    def test_repairs_double_encoded_accent(self) -> None:
        msg = _make_message("Crypto UniversitÃ©")
        out = self.adapter._map_to_standard_email(msg)
        assert out.sender_name == "Crypto Université"

    def test_repairs_french_diaeresis(self) -> None:
        # "MichaËl Müller" round-tripped through UTF-8 → Latin-1: every
        # multibyte glyph collapses to a Ã-pair so the input is pure mojibake.
        original = "MichaËl Müller"
        mojibake = original.encode("utf-8").decode("latin-1")
        msg = _make_message(mojibake)
        out = self.adapter._map_to_standard_email(msg)
        assert out.sender_name == original

    def test_leaves_clean_french_alone(self) -> None:
        msg = _make_message("François Müller")
        out = self.adapter._map_to_standard_email(msg)
        assert out.sender_name == "François Müller"

    def test_leaves_ascii_alone(self) -> None:
        msg = _make_message("savagecrypto22")
        out = self.adapter._map_to_standard_email(msg)
        assert out.sender_name == "savagecrypto22"

    def test_repairs_subject_too(self) -> None:
        original = "Re: Reçu pour votre commande à Paris"
        mojibake = original.encode("utf-8").decode("latin-1")
        msg = _make_message("Alice", subject=mojibake)
        out = self.adapter._map_to_standard_email(msg)
        assert out.subject == original

    def test_none_sender_name_does_not_crash(self) -> None:
        msg = _make_message("")
        msg.from_.email_address.name = None
        out = self.adapter._map_to_standard_email(msg)
        assert out.sender_name is None
