# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Audit fix — 2026-05-13 user-reported duplicate-greeting regression
==================================================================

When a contact's `preferred_greeting` is a non-canonical phrase (learned
from a previous draft that happened to start with arbitrary text), the
refine-text path computes `mandatory_opening` as something like
"Je ne peux pas mais Alexandre," and passes it (a) to the LLM system
prompt as the MANDATORY OPENING LINE rule and (b) to
`_ensure_starts_with_greeting` post-LLM.

The LLM correctly opened with the hint. But the post-LLM function only
recognises lines starting with `_GREETING_PREFIXES` ("Salut", "Bonjour",
…) as existing greetings — a non-canonical hint slipped through and got
prepended a SECOND time → user-visible duplicate first line.

Fix: also treat a first-line match against the hint itself as
"already greeted".
"""

from __future__ import annotations

from app.smart_routing import _ensure_starts_with_greeting


def test_non_canonical_hint_match_does_not_duplicate():
    """Reproduce the 2026-05-13 user screenshot scenario."""
    mandatory_opening = "Je ne peux pas mais Alexandre,"
    draft = (
        "Je ne peux pas mais Alexandre,\n\n"
        "C'est un test pour savoir si ma fonction follow-up "
        "fonctionne bien. Réponds-moi si tu veux, sinon "
        "j'aurai un suivi.\n\n"
        "À+"
    )

    result = _ensure_starts_with_greeting(draft, mandatory_opening)

    # The hint MUST appear exactly once at the top.
    assert result.count("Je ne peux pas mais Alexandre,") == 1, (
        f"Hint duplicated. Got:\n{result}"
    )
    # And the body must be preserved.
    assert "C'est un test" in result
    assert "À+" in result


def test_canonical_hint_still_works():
    """Sanity: standard greeting flow not affected."""
    mandatory_opening = "Bonjour Marie,"
    draft = "Bonjour Marie,\n\nOui je confirme.\n\nÀ bientôt,"

    result = _ensure_starts_with_greeting(draft, mandatory_opening)

    assert result.count("Bonjour Marie,") == 1
    assert result == draft  # no modification needed


def test_missing_greeting_still_prepends():
    """Sanity: when LLM dropped the greeting entirely, hint is added."""
    mandatory_opening = "Bonjour Marie,"
    draft = "Oui je confirme la réunion de demain.\n\nÀ bientôt,"

    result = _ensure_starts_with_greeting(draft, mandatory_opening)

    assert result.startswith("Bonjour Marie,")
    assert "Oui je confirme" in result


def test_case_insensitive_hint_match():
    """Hint match accepts case variations from the LLM output."""
    mandatory_opening = "Bonjour Marie,"
    draft = "BONJOUR Marie,\n\nOui je confirme.\n\nÀ bientôt,"

    result = _ensure_starts_with_greeting(draft, mandatory_opening)

    # "BONJOUR Marie," starts with "bonjour" which is in _GREETING_PREFIXES,
    # so this also passes via the canonical-prefix branch — but the hint
    # match is the backstop and it should be idempotent either way.
    assert result.lower().count("bonjour marie,") == 1


def test_empty_mandatory_opening_is_noop():
    """When no hint is provided, draft passes through untouched."""
    draft = "Oui je confirme.\n\nÀ bientôt,"
    assert _ensure_starts_with_greeting(draft, None) == draft
    assert _ensure_starts_with_greeting(draft, "") == draft
