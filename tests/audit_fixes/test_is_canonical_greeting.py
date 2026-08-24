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
Audit fix — 2026-05-13 user-reported preferred_greeting pollution
==================================================================

A contact's WritingStyleProfile.preferred_greeting can be learned from
the first line of a previous draft. If that previous draft happened to
start with arbitrary text (e.g. user-typed notes "Je ne peux pas mais
Alexandre,", or LLM-emitted weird openings), the polluted value then
flows back as the `MANDATORY OPENING LINE` of every subsequent
refine-text / compose call for that contact — and the LLM dutifully
copies the non-greeting into every email.

Fix: validate `preferred_greeting` at read time via `is_canonical_greeting`.
A value that doesn't start with a recognised greeting prefix (or a
tokenized template) is rejected; the pipeline falls back to the
canonical "Salut {nickname}," branch.
"""

from __future__ import annotations

import pytest

from app.smart_routing import is_canonical_greeting


# -- Accepted (canonical greetings) ------------------------------------------

@pytest.mark.parametrize("value", [
    "Salut",
    "Salut Alexandre,",
    "salut alexandre,",  # case-insensitive
    "Bonjour",
    "Bonjour Marie,",
    "BONJOUR Marie,",
    "Bonsoir Alex,",
    "Coucou Léa,",
    "Hi",
    "Hi John,",
    "Hi!",
    "Hello there,",
    "Hey,",
    "Dear Mr. Smith,",
    "Cher Alexandre,",
    "Chère Marie,",
    "Monsieur Lambert,",
    "Madame,",
    "Mme Durand,",
    "M. Dupont,",
    "Mr. Smith,",
    "Mrs. Jones,",
    "Ms. Brown,",
    "Dr. Doe,",
    "Prof. Curie,",
    # Tokenized templates from after-send learning
    "{first_name},",
    "{greeting} {first_name},",
    "Bonjour {first_name},",
])
def test_canonical_values_accepted(value):
    assert is_canonical_greeting(value), f"Should accept {value!r}"


# -- Rejected (the 2026-05-13 pollution shapes) ------------------------------

@pytest.mark.parametrize("value", [
    "Je ne peux pas mais Alexandre,",
    "Je ne peux pas mais",
    "Je vais te répondre",
    "Tu as raison",
    "OK super",
    "C'est noté",
    "Merci pour ton message",
    "Désolé pour le retard",
    "Comme convenu",
    "Suite à notre échange",
])
def test_polluted_values_rejected(value):
    assert not is_canonical_greeting(value), f"Should reject {value!r}"


# -- Edge cases --------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "",                 # empty string
    "   ",              # whitespace only
    None,               # not a string
    42,                 # not a string
    [],                 # not a string
    {"x": 1},           # not a string
])
def test_invalid_inputs_rejected(value):
    assert not is_canonical_greeting(value), f"Should reject {value!r}"
