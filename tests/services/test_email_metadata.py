# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for minimised email metadata persistence helpers."""

from app.services.email_metadata import (
    sanitize_classification_headers,
    serialize_classification_headers,
)


def test_sanitize_classification_headers_allowlists_and_redacts_presence_headers():
    headers = {
        "List-Unsubscribe": "<https://unsubscribe.example/?token=SECRET>",
        "Precedence": "  bulk  ",
        "X-Auto-Response-Suppress": "All",
        "X-Mailer": "Mailchimp Transactional",
        "Reply-To": "Campaign <reply@marketing.example>",
        "X-Original-To": "private@example.com",
    }

    sanitized = sanitize_classification_headers(headers)

    assert sanitized == {
        "list-unsubscribe": "present",
        "precedence": "bulk",
        "x-auto-response-suppress": "present",
        "x-mailer": "Mailchimp Transactional",
        "reply-to": "Campaign <reply@marketing.example>",
    }


def test_serialize_classification_headers_never_persists_unsubscribe_tokens():
    serialized = serialize_classification_headers(
        {
            "list-unsubscribe": "<mailto:u+token@example.com>, <https://u.example/t/SECRET>",
            "x-unknown": "must not persist",
        }
    )

    assert serialized == '{"list-unsubscribe":"present"}'
    assert "SECRET" not in serialized
