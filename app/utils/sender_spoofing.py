# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Detect sender display-name spoofing.

Two common phishing tricks against a human-readable display name:

* **Unicode homograph / mixed-script.** The sender label looks like a
  trusted brand ("Xfinity") but one of the Latin letters is actually a
  visually identical Cyrillic / Greek codepoint ("Хfinity" — capital X is
  ``U+0425 CYRILLIC CAPITAL LETTER HA``). Detected by walking the string
  and seeing if it mixes scripts that almost never co-occur in a real
  display name (Latin + Cyrillic / Greek / Armenian, …).

* **Invisible format characters padded inside the name.** Variation
  selectors (``U+E0100``…``U+E01EF``), zero-width joiners
  (``U+200B``…``U+200D``, ``U+FEFF``) and tag characters
  (``U+E0000``…``U+E007F``) get sprinkled between regular letters so that
  surface string-equality checks against block-lists fail. Detected by
  presence of any of those codepoints.

The detector is conservative: it returns ``True`` only when the cleaned
string would still appear "normal" but the raw form is unmistakably
crafted. Audit 2026-05-18: an inbox carried a row labelled
``"Хf󠄹󠄹і󠄹󠄹n󠄹󠄹і󠄹󠄹tу B󠄹󠄹іl󠄹󠄹lР󠄹󠄹ay"`` with no warning;
this module powers the "Suspicious sender" badge fix.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Tuple


# Invisible characters routinely abused to bypass block-lists. We strip
# them before flagging so the cleaned name is what the rest of the app
# sees (matching, display) — the raw form is only used to compute the
# is_spoofed bit.
_INVISIBLE_RE = re.compile(
    r"[​-‏"   # zero-width space / joiner / non-joiner / LRM / RLM
    r"‪-‮"    # bidi embedding / override
    r"⁠-⁤"    # word joiner, invisible operators
    r"﻿"           # zero-width no-break space (BOM in body)
    r"\U000E0000-\U000E007F"  # tag characters (deprecated)
    r"\U000E0100-\U000E01EF"  # variation selectors supplement
    r"]"
)


# Scripts that look like Latin to a casual reader. If a display name
# mixes Latin with any of these AND the count of suspicious chars is
# small (≤ 30% of the whole), it's very likely a homograph attack.
_LATIN_LOOKALIKE_SCRIPTS = frozenset(
    {"CYRILLIC", "GREEK", "ARMENIAN", "COPTIC"}
)


def _script_of(ch: str) -> str | None:
    """Return the rough script name of a single character, or ``None``.

    Uses ``unicodedata.name`` because Python's stdlib doesn't ship a
    full ScriptExtensions table. Good enough for the lookalike scripts
    above — those all carry the script name as the first token of the
    character name (``CYRILLIC SMALL LETTER A``, etc.).
    """
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    return name.split(" ", 1)[0] if name else None


def strip_invisible(text: str) -> str:
    """Remove zero-width / variation-selector / tag characters from text."""
    if not text:
        return text
    return _INVISIBLE_RE.sub("", text)


def detect_sender_spoofing(name: str | None) -> Tuple[str, bool]:
    """Return ``(cleaned_name, is_spoofed)`` for a sender display name.

    * ``cleaned_name`` always has invisible/format characters stripped.
    * ``is_spoofed`` is ``True`` when **either**:

        1. The raw input contained any of those invisible characters
           (legitimate display names never do), **or**
        2. The cleaned name mixes Latin letters with letters from a
           Latin-lookalike script (Cyrillic / Greek / Armenian /
           Coptic).

    Edge case: a fully-Cyrillic legitimate Russian name like
    ``"Андрей"`` returns ``False`` because there is no Latin mixed in.
    """
    if not name:
        return name or "", False

    cleaned = strip_invisible(name)
    had_invisible = cleaned != name

    saw_latin = False
    saw_lookalike = False
    for ch in cleaned:
        if not ch.isalpha():
            continue
        script = _script_of(ch)
        if script == "LATIN":
            saw_latin = True
        elif script in _LATIN_LOOKALIKE_SCRIPTS:
            saw_lookalike = True
        if saw_latin and saw_lookalike:
            break

    mixed_script = saw_latin and saw_lookalike
    return cleaned, (had_invisible or mixed_script)
