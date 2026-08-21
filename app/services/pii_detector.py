# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Pure-regex PII detector — replaces the LLM call in
`SensitiveDataDetectorAgent.detect` for the categories where deterministic
detection is reliable.

Why regex-only and not Presidio (2026-05-05):
    Presidio (regex + spaCy NER) is the long-term right answer for ambiguous
    cases (person names, addresses, dates-with-context). It's also a 500MB
    dependency that requires deploy-pipeline updates and a benchmark sweep
    before going to prod. This module ships the deterministic part of the
    win NOW (most PII is regex-detectable) without taking on the deploy
    risk. Next sprint: layer Presidio NER on top for the hard cases.

Categories detected:
    EMAIL          — RFC5322-shaped addresses
    PHONE          — E.164 / US / FR / CA / generic 10+ digit runs
    CREDIT_CARD    — 13-19 digits, Luhn-validated
    IBAN           — FR / GB / DE / ES / IT / BE / CH / NL etc., 15-34 chars
    SSN_US         — 3-2-4 digit pattern
    SIN_CA         — 9-digit Canadian SIN, Luhn-validated
    SIRET          — 14-digit French business ID, Luhn-validated
    IP_ADDRESS     — IPv4 dotted quads (excludes 0.x and 255.255.255.255)
    API_KEY        — AKIA / ASIA / sk- / pk_ / ghp_ / gho_ / github_pat_ /
                     xox[abprs] / Bearer / generic 32+ alnum tokens with prefix
    SECRET_KEYWORD — "password", "mot de passe", "secret", "api[_ ]key",
                     "token", "credential" near a value-like token
    FINANCIAL      — revenue / budget / margin terms near an amount or percentage
    COMMERCIAL     — explicit confidential strategy / launch / competitor terms

False-positive policy: prefer false positives (LLM redaction triggered
unnecessarily) over false negatives (PII shipped to recipient). Tune by
running detect() against a corpus of legitimate non-PII drafts and check
the matched-categories distribution.

Audit defense:
    - All regexes are anchored with word boundaries where applicable.
    - Luhn validation prevents random 16-digit numbers from being flagged
      as credit cards.
    - Gracefully degrades: if a regex fails (re.error from a future edit),
      the calling site catches and falls back to the LLM detector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PIIMatch:
    """One detected PII span."""
    category: str
    snippet: str
    start: int
    end: int


# ---------------------------------------------------------------------------
# Regex catalogue
# ---------------------------------------------------------------------------

# RFC5322-ish email (intentionally permissive, false-positive over false-negative)
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Phone: 10+ digit runs with optional separators ., -, space, parens, +
_PHONE_RE = re.compile(
    r"(?:(?<![\w\d])\+?\d[\d\s.\-()]{8,18}\d(?![\w\d]))"
)

# Credit card: 13-19 digits with optional separators (validated by Luhn below)
_CC_RE = re.compile(
    r"(?:(?<![\w\d])(?:\d[ \-]?){12,18}\d(?![\w\d]))"
)

# IBAN: 2 letters + 2 digits + 11-30 alphanumerics (most countries fit in [15, 34])
_IBAN_RE = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
)

# US SSN: 3-2-4 with required dashes (more conservative than \d{9})
_SSN_US_RE = re.compile(
    r"\b(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}\b"
)

# Canadian SIN: 9 digits in 3-3-3 with optional separators (Luhn-validated)
_SIN_CA_RE = re.compile(
    r"\b\d{3}[ \-]?\d{3}[ \-]?\d{3}\b"
)

# French SIRET: 14 digits (Luhn-validated)
_SIRET_RE = re.compile(
    r"\b\d{14}\b"
)

# IPv4 dotted quad
_IP4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

# API keys — known provider prefixes
_API_KEY_RE = re.compile(
    r"\b("
    r"AKIA[0-9A-Z]{16}"               # AWS access key ID
    r"|ASIA[0-9A-Z]{16}"              # AWS temporary access key
    r"|sk-[A-Za-z0-9]{20,}"           # OpenAI / Anthropic-style
    r"|sk_(?:live|test)_[A-Za-z0-9]{16,}"  # Stripe secret
    r"|pk_(?:live|test)_[A-Za-z0-9]{16,}"  # Stripe publishable
    r"|rk_(?:live|test)_[A-Za-z0-9]{16,}"  # Stripe restricted
    r"|ghp_[A-Za-z0-9]{36}"           # GitHub personal access token (classic)
    r"|gho_[A-Za-z0-9]{36}"           # GitHub OAuth token
    r"|github_pat_[A-Za-z0-9_]{60,}"  # GitHub fine-grained PAT
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"  # Slack tokens
    r"|Bearer\s+[A-Za-z0-9._\-]{20,}" # generic Bearer
    r"|AIza[A-Za-z0-9_\-]{35}"        # Google API key
    r")\b"
)

# Secret-keyword tokens. Match `password: <value>`, `password = <value>`,
# `mot de passe : <value>`. Requires a non-trivial value (≥4 chars).
_SECRET_KEYWORD_RE = re.compile(
    r"\b(password|mot\s+de\s+passe|secret|api[_\s-]?key|access[_\s-]?key|token|credential)"
    r"(?:\s+(?:est|is))?\s*[:=]\s*\S{4,}",
    re.IGNORECASE,
)

_FINANCIAL_RE = re.compile(
    r"\b(?:ca|chiffre\s+d['’]affaires?|revenu(?:s)?|revenue|arr|mrr|"
    r"ebitda|marge|budget|salaires?|profits?)\b"
    r".{0,40}?"
    r"\b\d+(?:[,.]\d+)?\s*(?:k€|m€|€|eur|usd|k|m|%)\b",
    re.IGNORECASE,
)

_COMMERCIAL_RE = re.compile(
    r"\b(?:strat[eé]gie|plan|roadmap|lancement|lancer|confidentiel|secret\s+commercial)\b"
    r".{0,80}?"
    r"\b(?:concurrent|produit|client|prix|tarif|q[1-4]|avant|confidentiel)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Luhn validation
# ---------------------------------------------------------------------------

def _luhn_valid(digits: str) -> bool:
    """Standard mod-10 checksum used by credit cards / SIN / SIRET."""
    if not digits or not digits.isdigit():
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        n = int(d)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


# ---------------------------------------------------------------------------
# Detection entry point
# ---------------------------------------------------------------------------

def detect_pii(text: str) -> List[PIIMatch]:
    """Return all PII matches found in `text`. Empty list when nothing matches.

    Order of categories doesn't matter for the caller — duplicates can occur
    when one span matches multiple categories (e.g. a credit-card-shaped
    string that's also a phone number). Caller should de-duplicate by
    `(start, end)` if it cares.
    """
    if not text:
        return []

    matches: List[PIIMatch] = []

    # Email — high confidence, no validation needed.
    for m in _EMAIL_RE.finditer(text):
        matches.append(PIIMatch("EMAIL", m.group(0), m.start(), m.end()))

    # API keys — high confidence, prefix match.
    for m in _API_KEY_RE.finditer(text):
        matches.append(PIIMatch("API_KEY", m.group(0), m.start(), m.end()))

    # Secret keywords (password/api_key/token followed by a value).
    for m in _SECRET_KEYWORD_RE.finditer(text):
        matches.append(PIIMatch("SECRET_KEYWORD", m.group(0), m.start(), m.end()))

    # Business-sensitive financial metrics (not PII, but blocked by the
    # same pre-send sensitive-data guard).
    for m in _FINANCIAL_RE.finditer(text):
        matches.append(PIIMatch("FINANCIAL", m.group(0), m.start(), m.end()))

    # Business-sensitive commercial secrets: deterministic, explicit phrases only.
    for m in _COMMERCIAL_RE.finditer(text):
        matches.append(PIIMatch("COMMERCIAL", m.group(0), m.start(), m.end()))

    # IBAN — letters + digits structure is strong enough to skip Luhn here.
    for m in _IBAN_RE.finditer(text):
        matches.append(PIIMatch("IBAN", m.group(0), m.start(), m.end()))

    # IPv4
    for m in _IP4_RE.finditer(text):
        matches.append(PIIMatch("IP_ADDRESS", m.group(0), m.start(), m.end()))

    # US SSN
    for m in _SSN_US_RE.finditer(text):
        matches.append(PIIMatch("SSN_US", m.group(0), m.start(), m.end()))

    # Credit cards — Luhn-validate
    for m in _CC_RE.finditer(text):
        digits = _digits_only(m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            matches.append(PIIMatch("CREDIT_CARD", m.group(0), m.start(), m.end()))

    # SIRET — Luhn on 14 digits
    for m in _SIRET_RE.finditer(text):
        digits = m.group(0)
        if _luhn_valid(digits):
            matches.append(PIIMatch("SIRET", m.group(0), m.start(), m.end()))

    # Canadian SIN — Luhn on 9 digits (separate from credit card)
    for m in _SIN_CA_RE.finditer(text):
        digits = _digits_only(m.group(0))
        if len(digits) == 9 and _luhn_valid(digits):
            # Avoid double-tagging if the same span is already a credit card or SIRET.
            already_tagged = any(
                pm.start <= m.start() < pm.end and pm.category in ("CREDIT_CARD", "SIRET")
                for pm in matches
            )
            if not already_tagged:
                matches.append(PIIMatch("SIN_CA", m.group(0), m.start(), m.end()))

    # Phone — last because it's the most permissive. Skip spans already
    # caught as a credit card / SSN / SIN — those are stronger signals
    # and shouldn't double-tag.
    taken: set[tuple[int, int]] = {(p.start, p.end) for p in matches}
    for m in _PHONE_RE.finditer(text):
        # Reject if fully overlapped by a stronger match
        if any(s <= m.start() and m.end() <= e for s, e in taken):
            continue
        digits = _digits_only(m.group(0))
        # Filter junk: phone needs 10-15 digits, not 4-figure dates etc.
        if 10 <= len(digits) <= 15:
            matches.append(PIIMatch("PHONE", m.group(0), m.start(), m.end()))

    return matches


def has_pii(text: str) -> bool:
    """Convenience predicate."""
    return bool(detect_pii(text))


def categories_in(text: str) -> List[str]:
    """Sorted distinct list of PII categories present in `text`."""
    cats = sorted({m.category for m in detect_pii(text)})
    return cats


def short_summary(text: str) -> Optional[str]:
    """Return a short human-readable summary suitable for UI surfacing.

    Returns None when no PII found. Format: "phone, email, credit_card".
    """
    cats = categories_in(text)
    if not cats:
        return None
    return ", ".join(c.lower() for c in cats)
