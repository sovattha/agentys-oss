# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Shared draft post-processing utilities.

Until 2026-05-03 this lived in `app/application/refine_email.py` and ran only
on refined drafts. The audit (2026-05-03 Q7) showed that initial drafts emitted
by `SmartRouter` could also leak chain-of-thought lines (e.g. "Je dois prioriser
le besoin client → réponse courte"), but the strip never ran there. Extracted
here so both call sites — refine path and the SmartRouter post-LLM pipelines —
share the exact same regexes and the exact same safety net.
"""

from __future__ import annotations

import re


# Patterns that indicate chain-of-thought reasoning leaked into the output.
#
# Every pattern is line-anchored (`^…$` with re.MULTILINE) and matched against
# the *stripped* line — so a legitimate sentence that just happens to contain
# the trigger words mid-line is not affected. The patterns are deliberately
# conservative: we'd rather miss a leak than strip a real sentence.
_REASONING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Je dois X:" / "I need to X:" / "I must X:" / "Let me X:" — meta-narration
    # where the colon is at the END of the line (the model announcing its own
    # next move, with the actual reply on the following line).
    #
    # Audit 2026-06-02 I: the colon MUST terminate the line. The old pattern
    # (`.*?[:\n]`) matched any colon anywhere on the line, so a legitimate
    # composed sentence like "Let me summarize: we agreed on the budget." or
    # "Je dois vous confirmer ceci : la réunion est avancée." was silently
    # deleted (compose-from-scratch is exactly where such openings appear). A
    # real reasoning header is its own paragraph ("Je dois adopter un ton
    # formel :") with no content after the colon — content-bearing sentences
    # keep text after the colon and are now preserved.
    re.compile(
        r"^(?:Je dois|I need to|I must|Let me)\b[^:\n]*:\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Section-header form: "**Résolution :**", "Note: …", "Analysis - …", etc.
    re.compile(
        r"^\*{0,2}(?:Résolution|Resolution|Note|Clarification|Contradiction|Analyse|Analysis)\*{0,2}\s*[:—–-].*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Meta-prose explicitly referring to the directives the model just received.
    re.compile(
        r"^(?:Ces deux directives|L'instruction originale|La critique stipule).*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^(?:Cependant|However|Toutefois),?\s+(?:l'instruction|the instruction|la critique|the critique).*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^(?:Selon les règles|According to the rules).*$",
        re.IGNORECASE | re.MULTILINE,
    ),
)

# Vocabulary used to keep skipping bullet-point reasoning lines that follow a
# header line — these are the words that show up in the *body* of a reasoning
# block ("- Vérifier le contexte instruction", "- Adapter la critique...").
_REASONING_BULLET_KEYWORDS: tuple[str, ...] = (
    "instruction", "critique", "règle", "langue",
    "contradiction", "résolution", "profil",
)


def strip_reasoning_leakage(text: str) -> str:
    """Remove chain-of-thought reasoning that leaked into LLM output.

    Operates line-by-line:

    1. When a reasoning pattern matches on a line, drop that line and enter a
       reasoning block.
    2. While inside a reasoning block, also drop bullet-point lines that
       contain reasoning vocabulary — these are the model's enumeration of its
       own constraints.
    3. The first non-empty line that does *not* look like reasoning ends the
       block; everything after it is preserved.

    Safety net: if stripping removes everything, return the original text. We
    would rather ship a draft that contains some reasoning prose than ship an
    empty body — the model can be told to do better, an empty draft cannot.
    """
    if not text:
        return text

    lines = text.split("\n")
    clean_lines: list[str] = []
    in_reasoning_block = False

    for line in lines:
        stripped = line.strip()

        if any(p.search(stripped) for p in _REASONING_PATTERNS):
            in_reasoning_block = True
            continue

        # Empty line ends a reasoning block (paragraph break = back to content).
        if in_reasoning_block and not stripped:
            in_reasoning_block = False
            continue

        if in_reasoning_block:
            looks_like_reasoning_bullet = (
                stripped.startswith(("- ", "* ", "**"))
                and any(kw in stripped.lower() for kw in _REASONING_BULLET_KEYWORDS)
            )
            if looks_like_reasoning_bullet:
                continue
            # Anything else means we're back in real content.
            in_reasoning_block = False

        clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    return result if result else text.strip()


# ---------------------------------------------------------------------------
# AI-dash normalisation
# ---------------------------------------------------------------------------
#
# LLMs pepper prose with em dashes (—), en dashes (–), double hyphens (--) and
# spaced hyphens ( - ) used as clause connectors. A person writing a normal
# email almost never types these (the em dash isn't even on a standard
# keyboard), so they read as a tell that a machine wrote the message. The user
# flagged it directly: "never write with - in emails, humans don't do that".
#
# This pass rewrites those connectors to the punctuation a human actually uses
# (a comma, or nothing right after sentence-ending punctuation) while leaving
# hyphens that belong INSIDE a word untouched — "Co-fondateur", "rendez-vous",
# "week-end", "Jean-Pierre", "9h-17h", "2024-2025" all stay exactly as written.

# A dash sitting directly after sentence punctuation is pure decoration: drop
# it (keep a single space). "...le coût. — Voici" -> "...le coût. Voici".
_DASH_AFTER_PUNCT_RE = re.compile(r"(?<=[.!?:;,])[ \t]*(?:[—–]|--)[ \t]*")

# An em/en dash (or spaced --) BETWEEN TWO DIGITS is a range, not a connector:
# keep it a plain hyphen. "9 – 17" -> "9-17", "2024 — 2025" -> "2024-2025".
# Runs before the connector rule so a range never becomes "9, 17".
_DASH_NUMERIC_RANGE_RE = re.compile(r"(?<=\d)[ \t]*(?:[—–]|--)[ \t]*(?=\d)")

# An em/en dash (or spaced --) used as a mid-sentence connector: comma. The \S
# look-behind requires a real character before the dash, so a line that STARTS
# with "— " / "-- " (a bullet) is left intact.
_DASH_CONNECTOR_RE = re.compile(r"(?<=\S)[ \t]*(?:[—–]|--)[ \t]*")

# A single ASCII hyphen used as a spaced connector: comma. Deliberately
# conservative — BOTH neighbours must be a non-space, non-digit character, so
# numeric ranges ("9 - 17"), option flags, and indented "- " bullets are never
# touched; only prose like "Telegram - je pense" / "qualité - rapidité".
_HYPHEN_CONNECTOR_RE = re.compile(r"(?<=[^\d\s])[ \t]+-[ \t]+(?=[^\d\s])")


def strip_ai_dashes(text: str) -> str:
    """Replace em/en dashes and spaced-hyphen connectors with human punctuation.

    Runs as a post-LLM pass on every generated email body (compose, refine, and
    the reply pipelines). See the module-level comment above for the rationale
    and the exact rules. Hyphens inside words and numeric ranges are preserved;
    only a dash used as a clause connector is rewritten — to a comma, or to a
    space when it directly follows sentence punctuation.

    Idempotent: running it twice yields the same result as running it once.
    """
    if not text:
        return text

    # Order matters: drop decorative post-punctuation dashes and protect
    # numeric ranges BEFORE the broad connector->comma rules.
    out = _DASH_AFTER_PUNCT_RE.sub(" ", text)
    out = _DASH_NUMERIC_RANGE_RE.sub("-", out)
    out = _DASH_CONNECTOR_RE.sub(", ", out)
    out = _HYPHEN_CONNECTOR_RE.sub(", ", out)

    # Tidy the artefacts the substitutions can leave behind: a space before a
    # comma, or a doubled comma ("word —, x" -> "word, , x" -> "word, x").
    out = re.sub(r"[ \t]+,", ",", out)
    out = re.sub(r",[ \t]*,", ",", out)
    return out


_TERMINAL_PARENTHETICAL_RE = re.compile(r"(?:\n\s*)*\([^()\n]{8,180}\)\s*$")


def strip_terminal_parenthetical_note(text: str) -> str:
    """Remove a final standalone parenthetical note from generated email text.

    Keeps inline legal/source parentheses intact; only a trailing paragraph like
    ``(happy to adjust...)`` is stripped.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    cleaned = _TERMINAL_PARENTHETICAL_RE.sub("", text).rstrip()
    return cleaned or text
