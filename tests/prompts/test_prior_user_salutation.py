# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for `_extract_prior_user_salutation` — protects bug #G-Aubert.

Bug summary: a contact whose `From:` display name is just the LAST name
("Aubert") triggered "Bonjour Aubert," because email-prefix extraction
fed `_compute_greeting_hint` with a single token treated as first_name.

The thread already contained a previous outgoing message from the user
addressed "Bonjour Alexandra,". Mirroring THAT salutation is the
deterministic fix — exercised by the cases below.
"""

from __future__ import annotations

from app.prompts.identity import _extract_prior_user_salutation


def test_returns_empty_on_missing_inputs():
    assert _extract_prior_user_salutation(None, "u@x.com", "c@y.com") == ("", "")
    assert _extract_prior_user_salutation([], "", "c@y.com") == ("", "")
    assert _extract_prior_user_salutation([{"sender": "u@x.com", "body": ""}], "u@x.com", "") == ("", "")


def test_extracts_first_name_from_user_outgoing_message():
    history = [
        {
            "sender": "Crypto Université <user@x.com>",
            "to": "Alexandra <contact@y.com>",
            "body": "Bonjour Alexandra,\n\nÇa fonctionne toujours pour moi vendredi 10h.\n\nÀ bientôt,\nAlexandre",
        },
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "contact@y.com")
    assert salut == "Bonjour Alexandra,"
    assert first == "Alexandra"


def test_normalizes_punctuation_to_comma():
    """Salutation ending with `!` or `.` is rebuilt with `,`."""
    history = [
        {"sender": "user@x.com", "to": "c@y.com", "body": "Salut Alex!\n\nMerci."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert salut == "Salut Alex,"
    assert first == "Alex"


def test_skips_messages_from_other_senders():
    """Only the user's own outgoing messages are scanned."""
    history = [
        {"sender": "Alexandra <contact@y.com>", "body": "Bonjour Aubert,\n\nMerci."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "contact@y.com")
    assert (salut, first) == ("", "")


def test_skips_messages_to_other_contacts_when_to_field_present():
    history = [
        {
            "sender": "user@x.com",
            "to": "stranger@elsewhere.com",
            "body": "Bonjour Stranger,\n\nMerci.",
        },
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "contact@y.com")
    assert (salut, first) == ("", "")


def test_skips_when_to_field_is_a_list():
    """`to` may be a list of recipients — must still match correctly."""
    history = [
        {
            "sender": "user@x.com",
            "to": ["contact@y.com", "cc@z.com"],
            "body": "Bonjour Alexandra,\n\nOK.",
        },
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "contact@y.com")
    assert salut == "Bonjour Alexandra,"


def test_ignores_generic_salutations():
    """`Bonjour vous,` / `Hi all,` / `Dear team,` carry no first-name signal."""
    history = [
        {"sender": "user@x.com", "to": "c@y.com", "body": "Hi all,\n\nMerci."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert (salut, first) == ("", "")


def test_only_looks_at_first_content_line():
    """Salutations live on the first line — `Bonjour X,` mid-body must not match."""
    history = [
        {
            "sender": "user@x.com",
            "to": "c@y.com",
            "body": "Comme prévu.\n\nBonjour Alex, juste un détail.",
        },
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert (salut, first) == ("", "")


def test_handles_accented_first_name():
    history = [
        {"sender": "user@x.com", "to": "c@y.com", "body": "Bonjour Hélène,\nOK."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert salut == "Bonjour Hélène,"
    assert first == "Hélène"


def test_returns_empty_when_user_email_not_in_any_sender():
    history = [
        {"sender": "other@x.com", "body": "Bonjour Alex,\nHey."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert (salut, first) == ("", "")


def test_picks_first_matching_message_when_multiple_present():
    history = [
        {"sender": "user@x.com", "to": "c@y.com", "body": "Bonjour Alexandra,\nOK."},
        {"sender": "user@x.com", "to": "c@y.com", "body": "Salut Alex,\nplus tard."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    # The first match wins (the function does not re-rank by recency).
    assert salut == "Bonjour Alexandra,"
    assert first == "Alexandra"


def test_handles_english_salutations():
    history = [
        {"sender": "user@x.com", "to": "c@y.com", "body": "Hi Sarah,\n\nThanks."},
    ]
    salut, first = _extract_prior_user_salutation(history, "user@x.com", "c@y.com")
    assert salut == "Hi Sarah,"
    assert first == "Sarah"
