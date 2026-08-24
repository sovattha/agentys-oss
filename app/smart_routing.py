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
Smart Routing Engine — Cost-Optimized Draft Generation.

Routes emails to the cheapest capable model tier:
  - SKIP: auto-generated senders, self-sent -> no processing
  - SIMPLE: short acknowledgments -> template fill ($0.00)
  - STANDARD: normal business replies -> Haiku ($0.003)
  - COMPLEX: multi-question negotiations -> Haiku + higher tokens ($0.003)

Rule-based complexity classifier (no LLM call). All drafts use Haiku.
"""

import re
import json
import logging
import os
import time
import threading
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app._fixture_capture import capture_if_enabled
from app.config import FAQ_AUTO_REPLY_ENABLED
from app.utils.draft_cleanup import strip_ai_dashes, strip_reasoning_leakage

logger = logging.getLogger(__name__)


# ============================================================================
# FRENCH DETECTION — module-level tuples (avoid per-call list allocation)
# ============================================================================
_FR_DETECT_WORDS = ('je ', 'nous ', 'bonjour', 'merci', 'salut')
_FR_DETECT_FORMAL = ('bonjour', 'cher ', 'monsieur')

# Product-generated prompts used by the compose UI. They guide the drafter but
# are not explicit user instructions, so they should not force STANDARD routing
# or block the critic skip gate on otherwise low-risk drafts.
_AUTO_DRAFT_INSTRUCTION_BASES = frozenset({
    "reply appropriately",
    "reply appropriately to this email",
    "reply to this meeting invitation",
    "reply to the availability request",
    "reply to this urgent request",
    "reply to the document request",
    "confirm or reply to the request",
    "reply to the question asked",
    "reply in a friendly way with a few words it is just a greeting between friends no need to invent details about your life",
    "reply to the issue report",
    "reply to this follow-up",
    "reply to this introduction",
    "reply courteously to the thank-you",
    "write a short introduction message to forward this email e g for your information i am forwarding this email",
    "réponds de façon concise et professionnelle",
    "reponds de facon concise et professionnelle",
})

_AUTO_DRAFT_INSTRUCTION_QUALIFIERS = (
    "only mention what is in the email",
    "reply in maximum 2 short sentences",
    "reply briefly 3 sentences maximum",
    "if dates times availability or commitments are missing do not invent them say you will check and come back",
)


def _normalize_draft_instruction(instructions: str) -> str:
    text = unicodedata.normalize("NFKC", instructions or "").strip().lower()
    text = text.replace("’", "'").replace("—", " ").replace("–", " ")
    text = re.sub(r"[\s.?!;:(),]+", " ", text)
    for qualifier in _AUTO_DRAFT_INSTRUCTION_QUALIFIERS:
        text = text.replace(qualifier, " ")
    return re.sub(r"\s+", " ", text).strip()


def _has_meaningful_user_instructions(instructions: Optional[str]) -> bool:
    """True only for instructions typed/chosen by the user.

    The frontend sends default guardrail prompts even for a plain Ctrl+G.
    Treating those as user instructions made every automatic draft skip SIMPLE
    routing and forced the LLM critic, which is exactly the slow path users saw.
    """
    if not instructions or not instructions.strip():
        return False
    return _normalize_draft_instruction(instructions) not in _AUTO_DRAFT_INSTRUCTION_BASES


_UNKNOWN_BODY_ARTIFACT_RE = re.compile(
    r"^\s*Unknown\s*\(\s*(?:empty\s+bodies?|forwarded\s+content)\s*\)\s*[,.;:]?\s*$",
    re.IGNORECASE,
)


def strip_unknown_body_artifacts(text: str) -> str:
    """Remove provider/thread placeholders that are not email content."""
    if not text:
        return text
    lines = [
        line
        for line in str(text).splitlines()
        if not _UNKNOWN_BODY_ARTIFACT_RE.match(line.strip())
    ]
    return "\n".join(lines).strip()

# ============================================================================
# CENTRALIZED FILLER & META-COMMENTARY PATTERNS
# ============================================================================
# Single source of truth — used by _clean_prompt_leakage, _strip_filler_mid_draft,
# and _strip_meta_commentary. No more duplicate lists.

# Exact filler phrases (lowercased). Line must match exactly (after stripping punctuation).
_FILLER_EXACT = frozenset([
    "c'est parti", "c'est parti !", "c'est parti!",
    "super", "super !", "super!", "génial !", "genial !",
    "awesome", "awesome!", "great", "great!", "let's go", "let's go!",
    "n'hésitez pas", "n'hesitez pas",
    "je reste à votre disposition", "je reste a votre disposition",
    "je reste à votre entière disposition", "je reste a votre entiere disposition",
    "je me tiens à votre disposition", "je me tiens a votre disposition",
    "n'hésitez pas à me contacter", "n'hesitez pas a me contacter",
    "n'hésitez pas si vous avez des questions", "n'hesitez pas si vous avez des questions",
    "feel free to reach out", "feel free to contact me",
    "don't hesitate to reach out", "don't hesitate to contact me",
    "please don't hesitate", "do not hesitate",
    "i remain at your disposal",
    "stop", "stop.",
    "c'est confirmé", "c'est confirme",
    # AI meta-commentary (#3)
    "i'd be happy to help", "i would be happy to help",
    "i'm happy to help", "happy to help", "happy to assist",
    "i'm here to help", "i'm here to assist",
    "let me help you with that",
    "i hope this helps", "j'espère que cela aide",
    "i hope this answers your question",
    "i hope this email finds you well",
    "j'espère que ce message vous trouve bien",
    # Corporate bloat (#2, #7)
    "thank you for reaching out", "thanks for reaching out",
    "thank you for your email", "thank you for your message",
    "merci pour votre email", "merci pour votre message",
    "merci pour ton email", "merci pour ton message",
    "i appreciate your patience", "j'apprécie votre patience",
    "i appreciate your understanding", "j'apprécie votre compréhension",
    "looking forward to hearing from you",
    "au plaisir de vous lire", "au plaisir de te lire",
    # Empty promises (#12)
    "i'll get back to you", "i will get back to you",
    "je vous reviens sous peu", "je reviendrai vers vous",
])

# Casual filler that's ACCEPTABLE at formality ≤ 2 (#10 — tone-aware)
_CASUAL_FILLER_OK = frozenset([
    "super", "super !", "super!", "génial !", "genial !",
    "awesome", "awesome!", "great", "great!",
    "c'est parti", "c'est parti !", "c'est parti!",
    "let's go", "let's go!",
])

# Filler prefixes (lowercased). If a line STARTS with any of these, it's filler.
_FILLER_PREFIX = (
    "c'est parti", "c est parti",
    "let's go", "let's do this",
    "allez ", "allons-y",
    "voici ma réponse", "voici ma reponse", "here is my reply", "here's my reply",
    "bien sûr", "bien sur", "sure thing",
    # AI meta-commentary prefixes (#3)
    "i'd be happy to", "i would be happy to", "i'm happy to",
    "i'm here to",
    # Corporate bloat prefixes (#2, #7)
    "thank you for your ", "merci pour votre ", "merci pour ton ",
    "i appreciate ", "j'apprécie ",
    "looking forward to", "au plaisir de",
    "i hope this ", "j'espère que ",
)

# Meta-commentary patterns — lines ABOUT the email rather than the actual reply.
# These reference the email/question/test itself instead of answering.
_META_COMMENTARY_RE = re.compile(
    r"^("
    r"(pour|en réponse à|en reponse a|regarding|in response to|about|concerning)\s+"
    r"(ton|ta|votre|your|the|this|ce|cet|cette|l[ea'])\s+"
    r"(email|courriel|message|question|demande|request|test|mail)"
    r"|"
    r"(voici|here\s*is|here\s*are|ci-dessous|below\s*is)\s+"
    r"(ma|my|la|the|les|notre|our)\s+"
    r"(réponse|reponse|reply|answer|response)"
    r")",
    re.IGNORECASE,
)


def _is_filler_line(line: str) -> bool:
    """Check if a line is filler/meta-commentary. Single function, single source of truth."""
    stripped = line.strip()
    if not stripped:
        return False
    normalized = stripped.lower().rstrip("!.,;").strip()

    # Exact match
    if normalized in _FILLER_EXACT or stripped.lower() in _FILLER_EXACT:
        return True

    # Prefix match
    if any(normalized.startswith(p) for p in _FILLER_PREFIX):
        return True

    # Meta-commentary regex
    if _META_COMMENTARY_RE.search(normalized):
        return True

    return False


# ============================================================================
# CRITIC SKIP GATE (Lever 2)
# ============================================================================
# Heuristic check to bypass the CriticAgent on high-confidence drafts.
# Saves ~1-2s per draft (and avoids a potential 2-3s V2 revision) on the
# ~70% of drafts where V1 already meets quality bars. Conservative by
# design — any doubt → run the full critic.

import os as _os_gate

_A_CONFIRMER_GATE_RE = re.compile(r"\[\s*(À|A)\s*(confirmer|valider)", re.IGNORECASE)
_HALLUCINATION_GATE_RE = re.compile(
    r"(\b\d{1,2}[h:]\d{2}\b|\b\d{1,2}\s*(?:€|\$|eur|usd)\b|\bj'ai (?:réservé|appelé|contacté|envoyé)\b)",
    re.IGNORECASE,
)
_TU_RE = re.compile(r"\btu\b|\bt'", re.IGNORECASE)
_VOUS_RE = re.compile(r"\bvous\b", re.IGNORECASE)


def _skip_critic_gate_enabled() -> bool:
    """Feature flag: default ON, disable via SKIP_CRITIC_GATE=false."""
    return _os_gate.environ.get("SKIP_CRITIC_GATE", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )


# P1.4 (2026-05-14): complexity-score floor below which the COMPLEX self-
# consistency 2-sample best-of-2 is skipped in favour of a single Haiku call.
# The 50-69 slice ("COMPLEX-ish") rarely benefits enough from best-of-2 over
# the post-LLM cleanup pipeline to justify the +1 LLM call. Kept module-local
# (not in app/config.py) per audit-day convention.
_SELF_CONSISTENCY_COMPLEX_THRESHOLD = int(
    _os_gate.environ.get("SELF_CONSISTENCY_COMPLEX_THRESHOLD", "70")
)

# F-06 (audit 2026-05-14): SHARED wall-clock budget for COMPLEX self-
# consistency best-of-2. Pre-fix the two `fut.result(timeout=60)` calls
# were SEQUENTIAL — fut_a waited up to 60s, then fut_b waited up to
# ANOTHER 60s, so a double-timeout produced an empty draft after 120s
# wall-clock. Worse, the user spent 120s staring at a spinner with
# no signal. 45s is < the adapter's 60s timeout (claude_adapter.py:247),
# so we trip BEFORE the SDK gives up — fast failure on Anthropic 5xx
# storms, plenty of room for the typical 5-15s successful generation.
# When one future succeeds and the other doesn't, we use the winner;
# when neither, we surface an empty draft (existing empty-handler
# path) — we DO NOT compound with another 60s single-shot fallback,
# which would re-introduce the 120s pathology.
_COMPLEX_SC_WALL_CLOCK_BUDGET_SEC = float(
    _os_gate.environ.get("COMPLEX_SC_WALL_CLOCK_BUDGET_SEC", "45")
)


# ----------------------------------------------------------------------------
# Critic skip-rate stats (audit 2026-05-05)
# ----------------------------------------------------------------------------
# Counters incremented by `_run_critic` to surface the actual ratio of drafts
# that bypass the LLM critic via the heuristic gate. Logged every
# _CRITIC_STATS_LOG_EVERY drafts with `[CRITIC_SKIP_STATS]` so a sentinel can
# alert if the rate drops below ~50% (gate became too strict, latency rises).
# Audit doc claimed ~70% skip rate without measurement — this is the proof.
_critic_stats_lock = threading.Lock()
_critic_skip_count: int = 0
_critic_full_count: int = 0
_CRITIC_STATS_LOG_EVERY = 50


def _record_critic_outcome(skipped: bool) -> None:
    """Increment skip/full counter and log periodic stats."""
    global _critic_skip_count, _critic_full_count
    with _critic_stats_lock:
        if skipped:
            _critic_skip_count += 1
        else:
            _critic_full_count += 1
        total = _critic_skip_count + _critic_full_count
        if total > 0 and total % _CRITIC_STATS_LOG_EVERY == 0:
            ratio = (_critic_skip_count / total) if total else 0.0
            logger.info(
                "[CRITIC_SKIP_STATS] total=%d skipped=%d full=%d skip_rate=%.2f",
                total, _critic_skip_count, _critic_full_count, ratio,
            )


def get_critic_skip_stats() -> dict:
    """Snapshot of skip stats for tests and the /api/health/llm endpoint."""
    with _critic_stats_lock:
        total = _critic_skip_count + _critic_full_count
        ratio = (_critic_skip_count / total) if total else 0.0
        return {
            "total": total,
            "skipped": _critic_skip_count,
            "full": _critic_full_count,
            "skip_rate": round(ratio, 4),
        }


_CRITIC_GATE_SAVED_MS_ESTIMATE = 1500
_critic_gate_lock = _critic_stats_lock
_critic_gate_stats: dict[str, int] = {
    "skipped_heuristic": 0,
    "skipped_complex_user_notes": 0,
    "skipped_unified": 0,
    "ran": 0,
    "estimated_ms_saved": 0,
}
_critic_gate_last_log_at = 0.0


def _record_critic_gate(outcome: str) -> None:
    if outcome not in _critic_gate_stats:
        return
    with _critic_gate_lock:
        _critic_gate_stats[outcome] += 1
        if outcome.startswith("skipped"):
            _critic_gate_stats["estimated_ms_saved"] += _CRITIC_GATE_SAVED_MS_ESTIMATE


def _get_critic_gate_snapshot() -> dict[str, int]:
    with _critic_gate_lock:
        return dict(_critic_gate_stats)


# ----------------------------------------------------------------------------
# Draft latency histogram (audit 2026-05-06)
# ----------------------------------------------------------------------------
# Rolling buffer of the last N draft end-to-end latencies, bucketed by tier
# so the admin dashboard can serve "P50 / P95 latency by tier" without
# scraping logs. The samples are bounded to keep memory predictable on a
# long-running daemon.

_LATENCY_MAX_SAMPLES = 2000
_latency_lock = threading.Lock()
_latency_samples: dict[str, list[float]] = {
    "simple": [],
    "standard": [],
    "complex": [],
    "skip": [],
    "compose": [],
    "other": [],
}


def record_draft_latency(tier: str, latency_seconds: float) -> None:
    """Append a latency sample for the given tier label.

    No-op if `latency_seconds` is negative or NaN. Tier label is normalised
    to lower case; unknown labels go into the ``other`` bucket so we never
    silently drop samples.
    """
    if latency_seconds is None:
        return
    try:
        v = float(latency_seconds)
    except (TypeError, ValueError):
        return
    if v != v or v < 0:  # NaN or negative
        return
    label = (tier or "other").strip().lower()
    if label not in _latency_samples:
        label = "other"
    with _latency_lock:
        bucket = _latency_samples[label]
        bucket.append(v)
        # Trim oldest if we go past the cap. Append+trim instead of deque
        # because we want a fixed-size window for percentile math.
        if len(bucket) > _LATENCY_MAX_SAMPLES:
            del bucket[: len(bucket) - _LATENCY_MAX_SAMPLES]


def _percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    if len(sorted_samples) == 1:
        return float(sorted_samples[0])
    k = (len(sorted_samples) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_samples) - 1)
    frac = k - lo
    return sorted_samples[lo] * (1 - frac) + sorted_samples[hi] * frac


def get_draft_latency_stats() -> dict:
    """Snapshot of latency percentiles per tier.

    Returns ``{"simple": {"count": N, "p50": …, "p95": …, "p99": …}, …}``
    with values in seconds. Buckets with no samples report 0 so the dashboard
    can render zeroed bars without special-casing missing data.
    """
    out: dict[str, dict] = {}
    with _latency_lock:
        snapshots = {k: list(v) for k, v in _latency_samples.items()}
    for tier, samples in snapshots.items():
        s = sorted(samples)
        out[tier] = {
            "count": len(s),
            "p50": round(_percentile(s, 0.50), 3),
            "p95": round(_percentile(s, 0.95), 3),
            "p99": round(_percentile(s, 0.99), 3),
            "max": round(s[-1], 3) if s else 0.0,
        }
    return out


def _critic_spot_check_rate() -> float:
    """P2.7 — sampling rate for spot-checking the heuristic skip-gate.

    On skipped drafts, run the LLM critic on this fraction (default 5%) to
    detect drift in the heuristic gate's accuracy. The result is logged via
    [CRITIC_SPOT_CHECK] but does NOT affect the user-facing draft (which is
    already returned valid by the gate). Pure observability.

    Tunable via env CRITIC_SPOT_CHECK_RATE (set to 0 to disable sampling).
    Cost : 0.05 × ~$0.0003/critic = ~$0.000015 per skipped draft. Negligible.
    """
    raw = _os_gate.environ.get("CRITIC_SPOT_CHECK_RATE", "0.05")
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = 0.05
    return max(0.0, min(1.0, rate))


def _use_unified_draft_enabled() -> bool:
    """Feature flag: if ON, the external critic + revision loop is skipped
    entirely for every draft. The drafter's V1 is trusted as-is (relies on
    the self-critique baked into its own prompt). Most aggressive mode —
    saves ~1-3 s per draft. Default OFF.
    """
    return _os_gate.environ.get("USE_UNIFIED_DRAFT", "false").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _draft_passes_quality_gate(
    draft: str,
    email_content: str,
    formality: int = 3,
    has_instructions: bool = False,
    tier: Optional["RoutingTier"] = None,
    body_length: Optional[int] = None,
) -> bool:
    """Heuristic quality check — returns True if the draft is confidently
    good enough to skip the LLM critic.

    Tier-aware:
    - COMPLEX → generic gate returns False; dedicated fast paths are separate
    - STANDARD with short body → aggressive bypass (skip critic if basic
      sanity checks pass)
    - STANDARD with long body → conservative checks (full gate)

    All rules are conservative: any "I don't know" → return False → run critic.
    """
    if not draft:
        return False

    # Tier-aware hard veto for the generic gate. COMPLEX usually benefits from
    # review; the manual-notes fast path is handled explicitly elsewhere.
    if tier is not None and tier == RoutingTier.COMPLEX:
        return False

    length = len(draft.strip())

    # 1. Length sanity (too short = suspect, too long = likely padding)
    if length < 20 or length > 2500:
        return False

    # 2. No placeholders or hedging markers
    if _A_CONFIRMER_GATE_RE.search(draft):
        return False
    if "[REDACTE]" in draft or "[TBD]" in draft or "[placeholder" in draft.lower():
        return False

    # 3. No obvious hallucination triggers (times, amounts, "j'ai X")
    # Only applies if the email itself didn't mention these
    if _HALLUCINATION_GATE_RE.search(draft) and not _HALLUCINATION_GATE_RE.search(email_content):
        return False

    # 4. Pronoun consistency (tu/vous mix = failure)
    has_tu = bool(_TU_RE.search(draft))
    has_vous = bool(_VOUS_RE.search(draft))
    if has_tu and has_vous:
        return False

    # 5. User had explicit instructions — trust the critic to verify compliance
    if has_instructions:
        return False

    # 6. Draft starts with obvious filler / meta-commentary
    first_line = draft.strip().split("\n", 1)[0].lower()
    if first_line.startswith(("here is", "voici", "je vais rédiger", "let me draft", "i'll write")):
        return False

    # 7. Short STANDARD fast-path: if both the input email and the draft are
    #    short (low surface area for hallucinations), the basic checks above
    #    already cover the risk envelope. No additional checks needed.
    #    This is a no-op (we'd return True anyway) but kept explicit for clarity
    #    in logs and future tier-specific tightening.
    if (
        tier == RoutingTier.STANDARD
        and body_length is not None
        and body_length < 300
        and length < 500
    ):
        return True

    # All conservative checks passed → confident enough to skip critic
    return True


def _complex_user_notes_fast_path_passes(
    *,
    draft: str,
    email_content: str,
    instructions: str,
    complexity_score: Optional[int],
    greeting_hint: str = "",
    closing_hint: str = "",
    specialty_context: str = "",
    body_length: Optional[int] = None,
) -> bool:
    """Skip the critic for manual notes on borderline complex replies.

    The 50-69 score band is usually "long email + user notes", not a truly
    high-risk negotiation. Keep the local cleanup gates, but avoid turning a
    manual notes draft into 3-4 LLM calls.
    """
    if not _has_meaningful_user_instructions(instructions):
        return False
    if specialty_context:
        return False
    if complexity_score is None or complexity_score >= _SELF_CONSISTENCY_COMPLEX_THRESHOLD:
        return False
    if not _draft_passes_quality_gate(
        draft=draft,
        email_content=email_content,
        has_instructions=False,
        tier=RoutingTier.STANDARD,
        body_length=body_length,
    ):
        return False

    lines = [line.strip() for line in (draft or "").splitlines() if line.strip()]
    if not lines:
        return False
    if greeting_hint and not _is_greeting_line(lines[0], greeting_hint):
        return False
    if closing_hint and not any(
        _is_closing_line(line)
        or line.lower().rstrip(",.;:!") == closing_hint.lower().rstrip(",.;:!")
        for line in lines[-3:]
    ):
        return False
    return _has_substantive_body_line(draft, greeting_hint, closing_hint)


# ============================================================================
# SELF-CONSISTENCY (best-of-2) — COMPLEX tier
# ============================================================================


def _multi_draft_enabled_for(instructions: Optional[str]) -> bool:
    """Return whether best-of-2 generation should run for this request."""
    from app.config import MULTI_DRAFT_ENABLED

    if instructions and instructions.strip():
        return False
    return bool(MULTI_DRAFT_ENABLED)


_PLACEHOLDER_RE = re.compile(
    r"\[(REDACTE|TBD|placeholder|à confirmer|a confirmer|à compléter|a completer)\]",
    re.IGNORECASE,
)
# Phrases that hedge instead of answering. Match against the lowercased
# first line of the draft. Expanded 2026-05-05 to cover EN+FR variants.
# Adding to this list is safe (more inputs penalized → picker more strict);
# removing requires re-validating against the eval suite.
_HEDGING_OPENERS = (
    # FR — verification / promise to check
    "je vais vérifier", "je vais verifier", "je vais regarder",
    "je vais voir", "je vais y jeter un œil", "je vais y jeter un oeil",
    "je vais en discuter", "je vais me renseigner",
    # FR — promise to come back
    "je reviens vers vous", "je reviens vers toi",
    "je vous reviens", "je te reviens",
    "je vous recontacte", "je te recontacte",
    "je m'en occupe", "je m'en charge",
    # FR — vague affirmations
    "ça devrait être", "ca devrait etre",
    "on va voir", "on verra",
    # EN — verification / promise to check
    "let me check", "let me verify", "let me look", "let me see",
    "let me get back", "let me find out", "let me confirm",
    "i'll check", "i will check", "i'll verify", "i will verify",
    "i'll confirm", "i will confirm", "i'll look", "i will look",
    # EN — promise to come back
    "i'll get back to you", "i will get back to you",
    "i'll follow up", "i will follow up",
    "i'll circle back", "i will circle back",
    "will follow up", "will get back",
    "i'll be in touch", "i will be in touch",
)


def _score_complex_candidate(draft: str) -> tuple[int, int]:
    """Score a COMPLEX draft for self-consistency picking.

    Returns (placeholder_penalty, hedging_penalty) — lower is better. The
    caller breaks ties by length (longer = more thorough on COMPLEX, which
    by definition has multiple questions to address). Heuristic-only — no
    LLM call — so the cost of self-consistency stays at +1 generation, not
    +1 generation +1 critic.
    """
    if not draft or not draft.strip():
        return (10, 10)  # max penalty — empty string loses to anything
    placeholder = len(_PLACEHOLDER_RE.findall(draft))
    first_line = draft.strip().split("\n", 1)[0].lower()
    hedging = 1 if any(first_line.startswith(p) for p in _HEDGING_OPENERS) else 0
    # "À confirmer" patterns we already strip mid-pipeline — but if they
    # survived (multi-line variant), they still count as hedging.
    if "à confirmer" in draft.lower() or "a confirmer" in draft.lower():
        hedging += 1
    return (placeholder, hedging)


def _pick_best_complex_draft(draft_a: str, draft_b: str) -> tuple[str, str]:
    """Pick the better of two COMPLEX-tier samples.

    Returns (winner_draft, reason). Reason is a short label for telemetry.
    Order of preference: fewer placeholders > fewer hedging openers > longer.
    """
    if not draft_a and not draft_b:
        return "", "both_empty"
    if not draft_a:
        return draft_b, "a_empty"
    if not draft_b:
        return draft_a, "b_empty"
    score_a = _score_complex_candidate(draft_a)
    score_b = _score_complex_candidate(draft_b)
    if score_a < score_b:
        return draft_a, f"a_wins_score={score_a}_vs_{score_b}"
    if score_b < score_a:
        return draft_b, f"b_wins_score={score_b}_vs_{score_a}"
    # Tie on heuristic — prefer the longer draft (more thorough on COMPLEX).
    if len(draft_a) >= len(draft_b):
        return draft_a, f"a_wins_length={len(draft_a)}_vs_{len(draft_b)}"
    return draft_b, f"b_wins_length={len(draft_b)}_vs_{len(draft_a)}"


# ============================================================================
# DRAFT DEDUP CACHE (Task #16)
# ============================================================================

# Key shape (audit 2026-04-25, C-3): (account_id, email_id). Pre-fix the
# cache was keyed by email_id alone with a 1-hour TTL and disk persistence,
# so two accounts whose IMAP UIDs collided served each other's generated
# drafts. account_id=None preserves the legacy bucket for callers that
# can't resolve a caller (background paths) — those entries are scoped by
# the cache being process-local, but should be migrated to explicit ids.
_draft_cache: dict[tuple[Optional[int], str], tuple[str, float]] = {}
# Side index: (account_id, content_hash) → email_id of the cached draft.
# Lets the cache HIT when the same email arrives with a different IMAP UID
# (resync, multi-folder delivery). Populated alongside _draft_cache writes;
# rebuilt empty at process start (no disk persistence — the canonical store
# is _draft_cache, this is just a reverse lookup).
_content_hash_index: dict[tuple[Optional[int], str], str] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour (was 10 minutes)
_CACHE_FILE = None  # Set lazily to ~/.agentys/draft_cache.json
_cache_lock = threading.Lock()


def _compute_content_hash(subject: str, body: str) -> str:
    """Stable 16-char content hash for SmartRouter cache cross-UID dedup.

    Uses the first 500 chars of normalized body so trailing signature/quote
    drift between forwarded copies of the same email still hashes the same.
    Subject is normalized lowercased + Re/Fwd-prefix stripped.
    """
    import hashlib
    import re as _re_local

    subj = (subject or "").strip().lower()
    subj = _re_local.sub(r"^(re|fwd?|tr)\s*:\s*", "", subj)
    body_norm = (body or "").strip()[:500]
    return hashlib.sha256(f"{subj}|{body_norm}".encode("utf-8", errors="ignore")).hexdigest()[:16]


def _draft_cache_key(account_id: Optional[int], email_id: str) -> tuple[Optional[int], str]:
    """Normalise the cache key so all callsites share one shape."""
    aid = int(account_id) if account_id is not None else None
    return (aid, email_id)


def _get_cache_path():
    """Get persistent cache file path."""
    global _CACHE_FILE
    if _CACHE_FILE is None:
        from pathlib import Path
        explicit_path = os.environ.get("AGENTYS_DRAFT_CACHE_PATH")
        if explicit_path:
            _CACHE_FILE = Path(explicit_path)
        else:
            data_dir = os.environ.get("AGENTYS_DATA_DIR")
            cache_dir = Path(data_dir) if data_dir else Path.home() / ".agentys"
            _CACHE_FILE = cache_dir / "draft_cache.json"
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _CACHE_FILE


def _load_persistent_cache() -> None:
    """Load draft cache from disk on startup.

    Disk format is `{"<aid>|<email_id>": [draft, ts]}` where `<aid>` is the
    int account_id or `_` when unknown. Legacy entries keyed by email_id
    only are silently dropped (regenerated on next request) — see
    isolation audit C-3 for why we can't trust them across accounts.
    """
    try:
        path = _get_cache_path()
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        cutoff = time.time() - _CACHE_TTL_SECONDS
        loaded = 0
        for raw_key, entry in data.items():
            if not (isinstance(entry, list) and len(entry) == 2):
                continue
            if "|" not in raw_key:
                # Legacy email-only key — drop, can't safely attribute to an account.
                continue
            aid_str, email_id = raw_key.split("|", 1)
            aid: Optional[int]
            if aid_str == "_" or aid_str == "":
                aid = None
            else:
                try:
                    aid = int(aid_str)
                except ValueError:
                    continue
            draft, ts = entry
            if ts > cutoff:
                _draft_cache[_draft_cache_key(aid, email_id)] = (draft, ts)
                loaded += 1
        if loaded:
            logger.info(f"SmartRouter: loaded {loaded} cached drafts from disk")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")


def _save_persistent_cache() -> None:
    """Save draft cache to disk (debounced — only after every 10 writes)."""
    try:
        path = _get_cache_path()
        cutoff = time.time() - _CACHE_TTL_SECONDS
        with _cache_lock:
            data: dict[str, list] = {}
            for (aid, email_id), v in _draft_cache.items():
                if v[1] <= cutoff:
                    continue
                aid_str = str(aid) if aid is not None else "_"
                data[f"{aid_str}|{email_id}"] = list(v)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")


# Counter for debounced persistence
_cache_write_count = 0


_cache_loaded = False


def _get_cached_draft(
    email_id: str,
    account_id: Optional[int] = None,
    content_hash: Optional[str] = None,
) -> str | None:
    """Return cached draft for `(account_id, email_id)` if not expired.

    When `content_hash` is provided and the primary `(account_id, email_id)`
    lookup misses, we try the content-hash side index — that surfaces a
    cache hit when the same email arrives with a different IMAP UID
    (resync, label move, multi-folder delivery).
    """
    global _cache_loaded
    if not email_id:
        return None

    # Load from disk on first access (locked to prevent double-load)
    if not _cache_loaded:
        with _cache_lock:
            if not _cache_loaded:
                _load_persistent_cache()
                _cache_loaded = True

    key = _draft_cache_key(account_id, email_id)
    entry = _draft_cache.get(key)
    if entry:
        draft, ts = entry
        if time.time() - ts < _CACHE_TTL_SECONDS:
            logger.info(f"SmartRouter: cache HIT for {email_id} (account_id={account_id})")
            return draft
        with _cache_lock:
            _draft_cache.pop(key, None)

    # Content-hash fallback: same email, different UID.
    if content_hash:
        aid = int(account_id) if account_id is not None else None
        peer_email_id = _content_hash_index.get((aid, content_hash))
        if peer_email_id and peer_email_id != email_id:
            peer_entry = _draft_cache.get(_draft_cache_key(aid, peer_email_id))
            if peer_entry:
                draft, ts = peer_entry
                if time.time() - ts < _CACHE_TTL_SECONDS:
                    logger.info(
                        f"SmartRouter: cache HIT via content_hash for {email_id} "
                        f"(peer UID={peer_email_id}, account_id={aid})"
                    )
                    return draft
    return None


def evict_draft_cache(email_id: str, account_id: Optional[int] = None) -> None:
    """Remove a specific email from the SmartRouter draft cache (memory + disk).

    When `account_id` is None, evict every account's entry for that email
    (used by callers that don't know the account, e.g. orphan cleanup).
    """
    global _cache_loaded
    if not _cache_loaded:
        with _cache_lock:
            if not _cache_loaded:
                _load_persistent_cache()
                _cache_loaded = True
    removed_any = False
    if account_id is None:
        with _cache_lock:
            stale_keys = [k for k in _draft_cache if k[1] == email_id]
            for k in stale_keys:
                _draft_cache.pop(k, None)
                removed_any = True
    else:
        key = _draft_cache_key(account_id, email_id)
        removed_any = _draft_cache.pop(key, None) is not None
    if removed_any:
        logger.info(f"SmartRouter: evicted cache for {email_id} (account_id={account_id})")
        _save_persistent_cache()


def _cache_draft(
    email_id: str,
    draft: str,
    account_id: Optional[int] = None,
    content_hash: Optional[str] = None,
) -> None:
    """Cache a generated draft (memory + periodic disk persistence).

    When `content_hash` is provided, also populate the side index so a future
    arrival of the same email under a different UID hits the cache. The side
    index is bounded by the same 500-entry policy as `_draft_cache` so it
    can't drift unbounded when many distinct emails are processed.
    """
    global _cache_write_count
    if not email_id or not draft:
        return
    _draft_cache[_draft_cache_key(account_id, email_id)] = (draft, time.time())
    if content_hash:
        aid = int(account_id) if account_id is not None else None
        _content_hash_index[(aid, content_hash)] = email_id
        # Bound the index. When _draft_cache evicts, the side index loses
        # its referent anyway, so this cap matches behavior. Drop oldest
        # half (FIFO via insertion order — Python 3.7+ dicts preserve it).
        if len(_content_hash_index) > 500:
            _drop = len(_content_hash_index) - 250
            for _k in list(_content_hash_index.keys())[:_drop]:
                _content_hash_index.pop(_k, None)

    # Evict expired entries when cache grows
    if len(_draft_cache) > 500:
        cutoff = time.time() - _CACHE_TTL_SECONDS
        expired = [k for k, (_, ts) in _draft_cache.items() if ts < cutoff]
        for k in expired:
            del _draft_cache[k]

    # Persist to disk every 5 writes
    _cache_write_count += 1
    if _cache_write_count % 5 == 0:
        _save_persistent_cache()


def _check_existing_draft(email_id: str) -> str | None:
    """Check PendingDraft store for an existing draft."""
    if not email_id:
        return None
    try:
        from app.infrastructure.container import get_container
        container = get_container()
        store = container.get_pending_draft_store()
        existing = store.get_by_email_id(email_id)
        if existing and existing.draft_body:
            logger.info(f"SmartRouter: existing PendingDraft found for {email_id}")
            return existing.draft_body
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    return None


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class RoutingTier(Enum):
    SKIP = "skip"
    FAQ_AUTO = "faq_auto"
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


@dataclass
class ComplexitySignals:
    body_length: int = 0
    question_count: int = 0
    technical_content: int = 0  # Count of unique technical keywords matched
    thread_depth: int = 0
    topic_count: int = 1
    multiple_requests: bool = False
    user_instructions: bool = False
    has_attachments: bool = False


@dataclass
class RoutingDecision:
    tier: RoutingTier
    complexity_score: int
    reason: str
    max_tokens: int = 512
    signals: ComplexitySignals = field(default_factory=ComplexitySignals)


@dataclass
class RoutingResult:
    draft: str
    decision: RoutingDecision
    classification: str = "Action"
    priority: int = 50
    status: str = "ROUTED"
    critique_info: Optional[dict] = None
    draft_v1: Optional[str] = None  # Original V1 before critique revision
    faq_sent_message_id: Optional[str] = None  # Sent reply ID for FAQ badge
    correction_details: Optional[list] = None  # Names of post-processing steps that fired


# ============================================================================
# PREFILTER PATTERNS (Step 0)
# ============================================================================

_SKIP_SENDER_PATTERNS = re.compile(
    r"(?:^|<)"
    r"(?:noreply|no-reply|no\.reply|donotreply|do-not-reply"
    r"|notifications?|notification-"
    r"|mailer-daemon|postmaster"
    r"|calendar-notification|calendar-server"
    r"|bounce[sd]?|auto-?"
    r"|feedback@|survey@"
    r"|alerts?@|monitoring@"
    r"|billing@.*\.com|invoice@"
    r"|support@.*\.zendesk|jira@"
    r"|github\.com|gitlab\.com|bitbucket\.org"
    r"|slack\.com|trello\.com|asana\.com|notion\.so"
    r"|linkedin\.com|facebook\.com|twitter\.com)"
    r"(?:@|>|$)",
    re.IGNORECASE,
)

_SKIP_SUBJECT_PATTERNS = re.compile(
    r"(?:invitation|calendar|accepted|declined|tentative)"
    r".*(?:meeting|event|rdv|reunion|rendez.?vous)"
    r"|^(?:out of office|absence|auto.?reply|automatic reply)"
    r"|^(?:undeliverable|delivery.?status|mail delivery)"
    r"|^(?:votre commande|order confirmation|shipping notification)",
    re.IGNORECASE,
)


def should_skip_prefilter(
    sender: str,
    user_email: str = "",
    subject: str = "",
    label: str = "",
) -> Optional[str]:
    """
    Rule-based pre-filter: returns skip reason or None.

    Checks: auto-generated senders, self-sent, calendar notifications,
    and non-Action labels.
    """
    sender_lower = sender.lower().strip()

    # Self-sent
    if user_email and sender_lower == user_email.lower().strip():
        return "self-sent"

    # Auto-generated sender patterns
    if _SKIP_SENDER_PATTERNS.search(sender_lower):
        return f"auto-sender ({sender_lower[:40]})"

    # Calendar / delivery / OOO subjects
    if subject and _SKIP_SUBJECT_PATTERNS.search(subject):
        return f"auto-subject ({subject[:40]})"

    # Non-action labels don't need drafts
    if label and label.lower() not in ("action", ""):
        return f"non-action label ({label})"

    return None


# ============================================================================
# COMPLEXITY CLASSIFIER (Step 3)
# ============================================================================

_QUESTION_PHRASE_RE = re.compile(
    r"(?:^|\.\s+)(?:est-ce que|pouvez-vous|pourriez-vous|peux-tu|as-tu"
    r"|is there|could you|can you|would you|do you|are you|will you"
    r"|how (?:do|can|should)|what (?:is|are)|when (?:is|will|can)"
    r"|quand|comment|combien|quel(?:le)?s?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _count_questions(text: str) -> int:
    """Compte les questions uniques par phrase (évite le double-comptage '?' + phrase interrogative)."""
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
    count = 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if '?' in s:
            count += 1
        elif _QUESTION_PHRASE_RE.search(s):
            count += 1
    return count

_TECHNICAL_PATTERNS = re.compile(
    r"\b(?:API|SDK|SQL|JSON|XML|CSV|HTTP|HTTPS|REST|GraphQL|OAuth"
    r"|deploy|rollback|release|staging|production|CI/CD"
    r"|bug|debug|stack\s*trace|exception|error|crash"
    r"|refactor|migration|database|schema|endpoint"
    r"|SLA|NDA|RGPD|GDPR|DPIA|DPO|KPI|ROI"
    r"|clause|contrat|avenant|renouvellement|résiliation"
    r"|tarif|facturation|licensing|licences?"
    r"|docker|kubernetes|terraform|aws|azure|gcp"
    r"|sprint|jira|confluence|pull\s*request|merge|branch)\b",
    re.IGNORECASE,
)

_LIST_PATTERNS = re.compile(
    r"(?:^|\n)\s*(?:\d+[\.\)]\s|[-*]\s|[a-z][\.\)]\s)",
    re.MULTILINE,
)

_TOPIC_SEPARATORS = re.compile(
    r"\n\s*\n"
    r"|(?:^|\n)(?:par ailleurs|d'autre part|concernant|regarding|also|additionally|de plus)\b",
    re.IGNORECASE | re.MULTILINE,
)


def analyze_complexity(
    body: str,
    subject: str = "",
    thread_depth: int = 0,
    has_instructions: bool = False,
    has_attachments: bool = False,
) -> ComplexitySignals:
    """Analyze email signals for complexity scoring."""
    text = body or ""
    full_text = f"{subject}\n{text}"

    questions = _count_questions(full_text)
    technical = len(set(_TECHNICAL_PATTERNS.findall(full_text)))
    has_lists = bool(_LIST_PATTERNS.search(text))
    paragraphs = len(_TOPIC_SEPARATORS.findall(text))
    topic_count = max(1, min(paragraphs, 5))

    return ComplexitySignals(
        body_length=len(text),
        question_count=questions,
        technical_content=technical,
        thread_depth=thread_depth,
        topic_count=topic_count,
        multiple_requests=has_lists or questions >= 3,
        user_instructions=has_instructions,
        has_attachments=has_attachments,
    )


def calculate_complexity_score(signals: ComplexitySignals) -> int:
    """
    Weighted complexity score (0-100).

    Weights:
      body_length: 0.20, question_count: 0.20, technical: 0.15,
      thread_depth: 0.10, topics: 0.10, multiple_requests: 0.10,
      user_instructions: 0.10, attachments: 0.05
    """
    # body_length: 0 at <200, 50 at ~1000, 100 at >2000
    bl = signals.body_length
    if bl < 200:
        body_score = 0
    elif bl < 1000:
        body_score = int((bl - 200) / 800 * 50)
    elif bl < 2000:
        body_score = int(50 + (bl - 1000) / 1000 * 50)
    else:
        body_score = 100

    # question_count: 0->0, 1->35, 2->70, 3+->100
    qc = signals.question_count
    if qc == 0:
        q_score = 0
    elif qc == 1:
        q_score = 35
    elif qc == 2:
        q_score = 70
    else:
        q_score = 100

    # technical: graduated 0/40/70/100 by keyword count
    tc_count = signals.technical_content
    if tc_count == 0:
        tech_score = 0
    elif tc_count == 1:
        tech_score = 40
    elif tc_count <= 3:
        tech_score = 70
    else:
        tech_score = 100

    # thread_depth: 0->0, 1->20, 2-3->40, 4->60, 5+->100
    td = signals.thread_depth
    if td == 0:
        thread_score = 0
    elif td == 1:
        thread_score = 20
    elif td <= 3:
        thread_score = 40
    elif td == 4:
        thread_score = 60
    else:
        thread_score = 100

    # topic_count: 1->0, 2->50, 3+->100
    tc = signals.topic_count
    if tc <= 1:
        topic_score = 0
    elif tc == 2:
        topic_score = 50
    else:
        topic_score = 100

    multi_score = 100 if signals.multiple_requests else 0
    instr_score = 100 if signals.user_instructions else 0
    attach_score = 100 if signals.has_attachments else 0

    score = int(
        body_score * 0.20
        + q_score * 0.20
        + tech_score * 0.15
        + thread_score * 0.10
        + topic_score * 0.10
        + multi_score * 0.10
        + instr_score * 0.10
        + attach_score * 0.05
    )

    score = max(0, min(100, score))
    logger.debug(
        "Complexity score=%d: body=%d q=%d tech=%d thread=%d topic=%d multi=%d instr=%d attach=%d",
        score,
        int(body_score * 0.20), int(q_score * 0.20), int(tech_score * 0.15),
        int(thread_score * 0.10), int(topic_score * 0.10), int(multi_score * 0.10),
        int(instr_score * 0.10), int(attach_score * 0.05),
    )
    return score


# ============================================================================
# DYNAMIC MAX_TOKENS
# ============================================================================

def calculate_dynamic_max_tokens(signals: ComplexitySignals, tier: RoutingTier) -> int:
    """
    Calculate the minimum max_tokens needed for the shortest effective reply.

    Instead of fixed 512 (STANDARD) or 1024 (COMPLEX), we size the token
    budget to the email's actual complexity — producing shorter, more direct
    responses and saving generation time + cost.

    Heuristic per tier:
      SKIP   -> 0
      SIMPLE -> 150 (template fill)
      STANDARD:
        - Ultra-short (<150 chars, 0 questions) -> 128  (ack / confirmation)
        - Short (<300 chars, <=1 question)      -> 256
        - Medium (<500 chars, <=2 questions)    -> 384
        - Long (<1000 chars, <=3 questions)     -> 512
        - Very long                             -> 768
      COMPLEX:
        - score 50-69                           -> 768
        - score 70-89                           -> 896
        - score 90+                             -> 1024
    """
    if tier == RoutingTier.SKIP:
        return 0
    if tier == RoutingTier.SIMPLE:
        return 150

    bl = signals.body_length
    qc = signals.question_count

    if tier == RoutingTier.STANDARD:
        if bl < 150 and qc == 0:
            return 128   # Ultra-short ack/confirmation
        if bl < 300 and qc <= 1:
            return 256   # Short single-question
        if bl < 500 and qc <= 2:
            return 384
        if bl < 1000 and qc <= 3:
            return 512
        return 768

    # COMPLEX — scale with complexity score (higher base for thorough replies)
    from app.smart_routing import calculate_complexity_score
    score = calculate_complexity_score(signals)
    if score >= 90:
        return 1024
    if score >= 70:
        return 896
    return 768


# ============================================================================
# FAQ KNOWLEDGE CACHE — used as drafter grounding (NOT for auto-reply)
# ============================================================================
# Cached per account_id with 5-minute TTL. Invalidated when user edits any FAQ
# entry via the training/savoir API (see invalidate_faq_cache below).

_faq_cache: dict[int, tuple[float, list[dict]]] = {}
_faq_cache_lock = threading.Lock()
_FAQ_CACHE_TTL = 300  # 5 minutes


def _load_faq_entries_cached(account_id: int) -> list[dict]:
    """
    Load FAQ entries for an account, with TTL cache.
    Returns [] on any failure (best-effort, never raises).
    """
    if not account_id:
        return []
    now = time.time()
    with _faq_cache_lock:
        cached = _faq_cache.get(account_id)
        if cached and (now - cached[0]) < _FAQ_CACHE_TTL:
            return cached[1]
    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository
        with get_db_session() as session:
            entries = KnowledgeRepository(session).get_faq_entries(account_id)
            data = [e.to_dict() for e in entries]
            with _faq_cache_lock:
                _faq_cache[account_id] = (now, data)
            return data
    except Exception as e:
        logger.debug(f"FAQ cache load failed for account {account_id}: {e}")
        return []


def invalidate_faq_cache(account_id: Optional[int] = None) -> None:
    """
    Invalidate the FAQ cache. Call when user edits/adds/removes a FAQ entry.
    Pass account_id to invalidate just one account, or None to clear all.
    """
    with _faq_cache_lock:
        if account_id is None:
            _faq_cache.clear()
        else:
            _faq_cache.pop(account_id, None)


# ============================================================================
# PARALLEL PROMPT LOADER POOL — used by _build_prompts (Lever 5)
# ============================================================================
# Shared ThreadPoolExecutor for the independent loaders called in _build_prompts:
#   - writing style profile (DB query)
#   - knowledge base (file read)
#   - FAQ entries (cached DB query + scoring)
#   - conversation history filtering (CPU)
# Running these in parallel saves ~30-80ms per draft compared to sequential.
# Workers=4 because there are exactly 4 independent loaders.

from concurrent.futures import ThreadPoolExecutor as _PromptExecutor

_prompt_loader_pool = _PromptExecutor(
    max_workers=4,
    thread_name_prefix="cgm-prompt-loader",
)


# ============================================================================
# SMART ROUTER
# ============================================================================

def _try_faq_agent(
    email_id: str,
    subject: str,
    body: str,
    sender: str,
    sender_name: str,
    user_email: str,
    allow_auto_send: bool = True,
) -> Optional["RoutingResult"]:
    """
    Shared FAQ agent check — called from route(), route_streaming(), classify_and_draft().

    Returns a RoutingResult if the FAQ agent matched. It auto-sends only when
    allow_auto_send is True and the FAQ config permits it; manual draft
    generation passes False so "generate draft" can never deliver mail.
    """
    try:
        from app.api.settings import load_settings

        # Resolve account_id + owning user_id from user_email FIRST so install
        # state and agent config are read per-tenant, not from the process-global
        # settings.json / loopback config (audit 2026-05-29: FAQ install/config
        # desync — the gate previously read global state with no account_id).
        _faq_account_id = ""
        _faq_user_id = None
        if user_email:
            try:
                from app.db.database import get_db_session
                from app.db.repositories.account_repository import AccountRepository
                with get_db_session() as _s:
                    _acct = AccountRepository(_s).get_by_email(user_email)
                    if _acct:
                        _faq_account_id = _acct.id
                        _faq_user_id = _acct.user_id
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        if not _faq_account_id:
            return None

        _settings = load_settings(account_id=_faq_account_id)
        _installed = _settings.get("installed_agents", [])
        if "faq" not in _installed:
            return None

        from app.faq_agent import process_faq_email
        from app.api.agent_marketplace import _load_agent_config

        faq_config = dict(_load_agent_config("faq", user_id=_faq_user_id) or {})
        if not allow_auto_send:
            faq_config["auto_send"] = False

        faq_result = process_faq_email(
            email_id=email_id,
            email_subject=subject or "",
            email_body=body or "",
            sender=sender or "",
            sender_name=sender_name or "",
            account_id=_faq_account_id,
            config=faq_config,
        )
        if faq_result and faq_result.action in ("auto_sent", "draft_only"):
            decision = RoutingDecision(
                tier=RoutingTier.FAQ_AUTO,
                complexity_score=0,
                reason=f"FAQ match: {faq_result.matched_entry_title} ({faq_result.confidence:.0f}%)",
                max_tokens=0,
            )
            logger.info(
                "[SmartRouter] FAQ_AUTO: entry='%s' confidence=%.1f",
                faq_result.matched_entry_title, faq_result.confidence,
            )
            return RoutingResult(
                draft=faq_result.draft_body or "",
                decision=decision,
                classification="Action",
                priority=30,
                status="FAQ_AUTO_SENT" if faq_result.action == "auto_sent" else "FAQ_DRAFT",
                faq_sent_message_id=(
                    faq_result.sent_message_id
                    if faq_result.action == "auto_sent"
                    else None
                ),
            )
    except Exception as _faq_exc:
        logger.debug("[SmartRouter] FaqAgent error (non-blocking): %s", _faq_exc)

    return None


class SmartRouter:
    """
    Routes emails to the optimal model tier based on complexity.

    Tiers:
      SKIP    -> no draft (pre-filter matched)
      SIMPLE  -> template engine ($0.00)
      STANDARD -> Haiku draft ($0.003)
      COMPLEX  -> Haiku draft with higher tokens ($0.003)
    """

    # Audit concurrency C1+C2 (2026-04-24): per-(account_id, email_id) lock
    # to dedupe simultaneous SmartRouter invocations for the same email.
    # Without this, two `/process` calls (or daemon + relabel firing in
    # parallel) both ran the full LLM pipeline and the last writer to
    # `pending_draft_store.add()` won — duplicating Haiku token spend and
    # producing UI flicker between the two drafts.
    #
    # Strategy: short-lived `threading.Lock` per (account, email_id)
    # acquired at the very top of `route` / `route_streaming`. The lock
    # registry is cleaned up automatically as soon as the lock is released
    # to avoid unbounded growth.
    import threading as _threading
    _entry_locks: dict = {}
    _entry_locks_master_lock = _threading.Lock()

    @classmethod
    def _acquire_entry_lock(cls, account_id, email_id: str):
        """Acquire a per-(account, email) lock; non-blocking sentinel.

        Returns the acquired Lock (caller must release) or None when the
        email_id is empty (no dedup keying possible).
        """
        if not email_id:
            return None
        key = (str(account_id) if account_id is not None else None, email_id)
        with cls._entry_locks_master_lock:
            lock = cls._entry_locks.get(key)
            if lock is None:
                lock = cls._threading.Lock()
                cls._entry_locks[key] = lock
        lock.acquire()
        return (key, lock)

    @classmethod
    def _release_entry_lock(cls, handle) -> None:
        if not handle:
            return
        try:
            key, lock = handle
        except Exception:
            return
        try:
            lock.release()
        except Exception:
            pass
        # Best-effort cleanup of unused locks (avoid unbounded dict growth)
        with cls._entry_locks_master_lock:
            existing = cls._entry_locks.get(key)
            if existing is lock and not lock.locked():
                cls._entry_locks.pop(key, None)

    class _EntryLockGuard:
        """RAII-style guard that ensures the per-(account, email) lock is
        released regardless of how `route()` / `route_streaming()` exits.

        Both the `__exit__` (when used as `with`) AND `__del__` (when used
        as a plain local) release the lock. CPython's reference counting
        runs `__del__` deterministically when the function returns by any
        path. This is intentional: we cannot easily wrap the 700+ line
        `route()` body in a context manager without a huge refactor.

        Audit concurrency C1+C2 fix (2026-04-24).
        """
        def __init__(self, owner_cls: type, account_id, email_id: str):
            self._owner_cls = owner_cls
            self._handle = owner_cls._acquire_entry_lock(account_id, email_id)

        @property
        def acquired(self) -> bool:
            return self._handle is not None

        def release(self) -> None:
            if self._handle is not None:
                self._owner_cls._release_entry_lock(self._handle)
                self._handle = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.release()
            return False  # don't suppress

        def __del__(self):
            try:
                self.release()
            except Exception:
                pass

    def _primary_language_fallback(self) -> str:
        """Return the account's onboarding-detected primary language
        ('ENGLISH' or 'FRENCH') for use as a ``_detect_language`` fallback.
        Cached per ``route()`` call (the cache is reset at route() start)."""
        cached = getattr(self, "_cached_primary_lang", None)
        if cached:
            return cached
        from app.prompts import load_primary_language_for_account
        value = load_primary_language_for_account(
            getattr(self, "_account_id", None)
        )
        self._cached_primary_lang = value
        return value

    def route(
        self,
        email_content: str,
        sender: str,
        subject: str,
        body: str,
        label: str = "Action",
        user_email: str = "",
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        force: bool = False,
        thread_depth: int = 0,
        contact_strength: float = 0.0,
        email_id: str = "",
        sender_name: str = "",
        thread_context: list[dict] | None = None,
        has_attachments: bool = False,
        account_id: int = 1,
        allow_faq_auto_send: bool = True,
    ) -> RoutingResult:
        """
        Route an email to the optimal draft generation tier.

        Args:
            email_content: Formatted "De: ...\nSujet: ...\n\n..." string.
            sender: Sender email address.
            subject: Email subject.
            body: Email body text.
            label: Assigned label (Action/Waiting/FYI/Noise).
            user_email: Current user's email for self-sent detection.
            conversation_history: Thread history for context.
            instructions: User instructions for the draft.
            force: If True, skip pre-filter (manual request).
            thread_depth: Number of messages in thread.
            contact_strength: Contact importance score (>=70 boosts to at least STANDARD).

        Returns:
            RoutingResult with draft, decision, classification, priority, status.
        """
        self._account_id = account_id  # Used by internal methods (style profile, etc.)
        body = strip_unknown_body_artifacts(body or "")
        # Reset the per-request primary-language cache — each route() call
        # may target a different account with a different onboarding result.
        self._cached_primary_lang: str | None = None
        from app.config import (
            ROUTING_SIMPLE_THRESHOLD,
            ROUTING_COMPLEX_THRESHOLD,
        )

        # Content hash for cross-UID dedup (resync, label move, multi-folder).
        # Computed once and threaded through all cache lookups + writes below.
        self._content_hash = _compute_content_hash(subject, body)

        # Audit concurrency C1+C2 (2026-04-24): serialize duplicate calls
        # for the same (account_id, email_id). The lock guard releases
        # automatically through the GC's __del__ on the local variable
        # when the function returns by any path (early SKIP, CACHE_HIT,
        # exception, or normal return). Python guarantees this for any
        # local that owns the only strong reference.
        _entry_lock = SmartRouter._EntryLockGuard(SmartRouter, account_id, email_id)

        # Post-lock cache re-check: if a peer call held the lock and
        # produced a draft while we waited, it's now cached. Skip the
        # full pipeline.
        if _entry_lock.acquired and email_id and not instructions and not force:
            _peer_cached = _get_cached_draft(
                email_id,
                account_id=getattr(self, "_account_id", None),
                content_hash=self._content_hash,
            )
            if _peer_cached:
                logger.info(
                    f"SmartRouter dedup (post-lock cache hit) for {email_id}"
                )
                return RoutingResult(
                    draft=_peer_cached,
                    decision=RoutingDecision(
                        tier=RoutingTier.SKIP,
                        complexity_score=0,
                        reason="post-lock cache hit",
                    ),
                    classification=label or "Action",
                    priority=50,
                    status="CACHE_HIT",
                )

        # Step 0: Pre-filter (skip unless forced)
        if not force:
            skip_reason = should_skip_prefilter(sender, user_email, subject, label)
            if skip_reason:
                decision = RoutingDecision(
                    tier=RoutingTier.SKIP,
                    complexity_score=0,
                    reason=f"Pre-filter: {skip_reason}",
                    max_tokens=0,
                )
                logger.info(f"SmartRouter SKIP: {skip_reason}")
                return RoutingResult(
                    draft="",
                    decision=decision,
                    classification=label or "Noise",
                    priority=0,
                    status="SKIPPED",
                )

        # Step 1.5: Dedup — check cache + PendingDraft store
        if email_id and not instructions and not force:
            cached = _get_cached_draft(
                email_id,
                account_id=getattr(self, "_account_id", None),
                content_hash=self._content_hash,
            )
            if cached:
                decision = RoutingDecision(
                    tier=RoutingTier.SKIP,
                    complexity_score=0,
                    reason="cache hit (in-memory)",
                    max_tokens=0,
                )
                return RoutingResult(
                    draft=cached, decision=decision,
                    classification="Action", priority=50, status="CACHE_HIT",
                )

            existing = _check_existing_draft(email_id)
            if existing:
                _cache_draft(
                    email_id, existing,
                    account_id=getattr(self, "_account_id", None),
                    content_hash=self._content_hash,
                )
                decision = RoutingDecision(
                    tier=RoutingTier.SKIP,
                    complexity_score=0,
                    reason="existing PendingDraft",
                    max_tokens=0,
                )
                return RoutingResult(
                    draft=existing, decision=decision,
                    classification="Action", priority=50, status="EXISTING_DRAFT",
                )

        has_instructions = _has_meaningful_user_instructions(instructions)
        has_raw_instructions = bool(instructions and instructions.strip())

        # Step 2a: FAQ Agent — checked before all other specialty agents
        # FAQ Agent (auto-reply) — disabled by default. FAQ entries are still
        # injected into the drafter prompt as grounding context (see _build_prompts).
        if not has_raw_instructions and FAQ_AUTO_REPLY_ENABLED:
            faq_hit = _try_faq_agent(
                email_id=email_id, subject=subject, body=body,
                sender=sender, sender_name=sender_name, user_email=user_email,
                allow_auto_send=allow_faq_auto_send,
            )
            if faq_hit:
                return faq_hit

        # Specialty pre-classification agents (account) ont été déliés du pipeline
        # (2026-04-30); le Refund Agent + intégrations Stripe/PayPal ont été retirés
        # (2026-05-29). app/account_agent.py reste utilisable via app/api/account_actions.py.

        # Step 3: Classify complexity
        signals = analyze_complexity(
            body=body,
            subject=subject,
            thread_depth=thread_depth,
            has_instructions=has_instructions,
            has_attachments=has_attachments,
        )
        score = calculate_complexity_score(signals)

        # Boost: question + conversation history = needs data recall → COMPLEX
        _needs_recall = (
            "?" in body
            and conversation_history
            and len(conversation_history) > 0
        )
        if _needs_recall and score < ROUTING_COMPLEX_THRESHOLD:
            logger.info(f"SmartRouter: boosting score {score}→{ROUTING_COMPLEX_THRESHOLD} (question + history = data recall)")
            score = ROUTING_COMPLEX_THRESHOLD

        # Boost: high-importance contact → at least STANDARD
        if contact_strength >= 70 and score < ROUTING_COMPLEX_THRESHOLD:
            boosted = max(score, ROUTING_SIMPLE_THRESHOLD)
            if boosted != score:
                logger.info(f"SmartRouter: contact_strength={contact_strength:.0f} boosting score {score}→{boosted}")
                score = boosted

        # Boost: historically high edit_ratio for this contact → upgrade tier
        if sender and email_id:
            try:
                from app.draft_quality_tracker import get_tracker
                hist = get_tracker().get_contact_edit_stats(sender)
                if hist and hist["avg_edit_ratio"] > 0.4 and hist["count"] >= 3:
                    if score < ROUTING_COMPLEX_THRESHOLD:
                        logger.info(
                            f"SmartRouter: contact {sender} has high edit_ratio "
                            f"({hist['avg_edit_ratio']:.2f} over {hist['count']} sends), "
                            f"boosting score {score}→{ROUTING_COMPLEX_THRESHOLD}"
                        )
                        score = ROUTING_COMPLEX_THRESHOLD
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        # Determine tier
        if score < ROUTING_SIMPLE_THRESHOLD and not has_instructions:
            tier = RoutingTier.SIMPLE
        elif score >= ROUTING_COMPLEX_THRESHOLD:
            tier = RoutingTier.COMPLEX
        else:
            tier = RoutingTier.STANDARD

        # User instructions force at least STANDARD
        if has_instructions and tier == RoutingTier.SIMPLE:
            tier = RoutingTier.STANDARD

        # Dynamic max_tokens: sized to email complexity, not fixed per tier
        max_tokens = calculate_dynamic_max_tokens(signals, tier)

        decision = RoutingDecision(
            tier=tier,
            complexity_score=score,
            reason=f"score={score}, questions={signals.question_count}, body={signals.body_length}chars",
            max_tokens=max_tokens,
            signals=signals,
        )

        logger.info(f"SmartRouter {tier.value.upper()} (score={score}): {decision.reason}")

        # Step 3.5: Specialty detection (Expert Mode, $0 keyword classification)
        # Only for COMPLEX emails — avoids token starvation on STANDARD (512 max)
        _specialty_match = None
        _specialty_context_for_critic = ""
        if tier == RoutingTier.COMPLEX:
            try:
                from app.specialty_engine import get_specialty_engine
                engine = get_specialty_engine()
                _active_specs = engine.get_active_specialties(account_id=getattr(self, "_account_id", None))
                if _active_specs:
                    _specialty_match = engine.classify_email(subject, body, _active_specs)
                    if _specialty_match:
                        logger.info(
                            f"SmartRouter SPECIALTY: {_specialty_match.specialty_name} "
                            f"/ {_specialty_match.category} (risk={_specialty_match.risk_level}, "
                            f"hits={_specialty_match.keyword_hits})"
                        )
                        # HIGH risk: abort draft, return empty with alert
                        if _specialty_match.risk_level == "high":
                            return RoutingResult(
                                draft="",
                                decision=decision,
                                classification="Action",
                                priority=90,
                                status="SPECIALTY_HIGH_RISK",
                                critique_info={"specialty": _specialty_match.to_dict()},
                            )
                        # Build context for both Drafter and Critic
                        _specialty_context_for_critic = engine.build_specialty_context(_specialty_match)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
        else:
            logger.debug(f"SmartRouter: specialty skipped (tier={tier.value}, score={score})")

        # Step 4a: Pre-compute greeting + closing hints for post-LLM enforcement
        greeting_hint = ""
        closing_hint = ""
        try:
            from app.prompts import (
                analyze_email_formality, _compute_greeting_hint,
                _detect_language, _extract_display_name,
            )
            formality = analyze_email_formality(f"{subject}\n{body}")
            detected_language = _detect_language(f"{subject} {body}", fallback_language=self._primary_language_fallback())
            if instructions:
                from app.prompts import _detect_language_override
                lang_override = _detect_language_override(instructions)
                if lang_override:
                    detected_language = lang_override
            effective_sender = sender_name or _extract_display_name(sender)
            greeting_hint = _compute_greeting_hint(
                effective_sender or "",
                _email_reply_greeting_formality(formality, instructions),
                detected_language,
                sender_email=sender,
                signature_text=body,
            )
            closing_hint = self._closing_hint_for(formality, detected_language)
            # Hot-thread detection: in an active back-and-forth (<24h since
            # the last prior message), re-greeting feels robotic — skip
            # the "Bonjour X," line but keep the closing.
            if (
                not _has_user_reply_instructions(instructions)
                and _is_hot_thread_continuation(thread_context, conversation_history)
            ):
                if greeting_hint:
                    logger.info(
                        f"SmartRouter: hot-thread continuation — skipping greeting "
                        f"(was: {greeting_hint!r})"
                    )
                greeting_hint = ""
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        # Step 4: Generate draft based on tier
        try:
            if tier == RoutingTier.SIMPLE:
                draft = self._generate_simple(sender, subject, body)
                if draft:
                    # Defensive post-LLM cleanup: strip [À confirmer]
                    # placeholders, markdown artifacts, prompt leakage, then
                    # enforce closing. Previously only _enforce_closing was
                    # applied, which let template drift leak to end users.
                    draft = _finalize_simple_draft(draft, closing_hint)
                    _cache_draft(email_id, draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
                    return RoutingResult(
                        draft=draft,
                        decision=decision,
                        classification="Action",
                        priority=50,
                        status="SIMPLE_TEMPLATE",
                    )
                # Fallback to STANDARD if no template match
                logger.info("SmartRouter: no template match, falling back to STANDARD")
                decision.tier = RoutingTier.STANDARD
                tier = RoutingTier.STANDARD
                max_tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
                decision.max_tokens = max_tokens

            # Step 4.5: Batch check — queue for off-hours 50% discount
            if should_use_batch(tier, force) and email_id:
                batch_instructions = instructions
                if tier == RoutingTier.COMPLEX:
                    complex_hint = (
                        "COMPLEX EMAIL — Be thorough. "
                        "Address EACH question or topic individually. "
                        "Use 3-6 sentences. Structure your reply clearly."
                    )
                    batch_instructions = (
                        f"{instructions}\n{complex_hint}" if instructions
                        else complex_hint
                    )
                system_prompt, user_prompt = self._build_prompts(
                    sender=sender, subject=subject, body=body,
                    conversation_history=conversation_history,
                    instructions=batch_instructions,
                    sender_name=sender_name,
                    thread_context=thread_context,
                    specialty_context=_specialty_context_for_critic,
                )
                # P0.1 (2026-05-14): _build_prompts now returns the system
                # as a list[SystemSegment] (cacheable prefix + dynamic).
                # enqueue_for_batch's BatchRequest.system_prompt is `str`,
                # so flatten here. The batch path loses the fine-grained
                # cache breakpoint but Anthropic's batch API still caches
                # the single block when it crosses the floor — and batch
                # is already half-priced, so further optimisation can wait.
                from app.prompts import _segments_to_text
                batch_system_prompt = _segments_to_text(system_prompt)
                # Use formality-based temperature (same as realtime)
                from app.prompts import analyze_email_formality, formality_to_temperature
                batch_formality = analyze_email_formality(f"{subject}\n{body}")
                batch_temperature = formality_to_temperature(batch_formality)

                item_id = enqueue_for_batch(
                    email_id=email_id, tier=tier,
                    sender=sender, subject=subject, body=body,
                    system_prompt=batch_system_prompt, user_prompt=user_prompt,
                    max_tokens=max_tokens, temperature=batch_temperature,
                    account_id=getattr(self, "_account_id", None),
                )
                logger.info(
                    f"SmartRouter BATCH: queued {email_id} ({tier.value}, "
                    f"max_tokens={max_tokens}) -> {item_id[:8]}"
                )
                return RoutingResult(
                    draft="",
                    decision=decision,
                    classification="Action",
                    priority=50,
                    status="BATCH_QUEUED",
                )

            if tier == RoutingTier.STANDARD:
                _effective_instructions = instructions or ""

                draft, _std_correction_details = self._generate_standard(
                    email_content=email_content,
                    sender=sender,
                    subject=subject,
                    body=body,
                    conversation_history=conversation_history,
                    instructions=_effective_instructions,
                    max_tokens=max_tokens,
                    sender_name=sender_name,
                    thread_context=thread_context,
                    specialty_context=_specialty_context_for_critic,
                )
                # Critique + revise
                final_draft, critique_info = self._validate_and_revise(
                    draft=draft,
                    email_content=email_content,
                    email_id=email_id,
                    conversation_history=conversation_history,
                    instructions=_effective_instructions,
                    user_email=user_email,
                    max_tokens=max_tokens,
                    sender_name=sender_name,
                    greeting_hint=greeting_hint,
                    closing_hint=closing_hint,
                    specialty_context=_specialty_context_for_critic,
                    tier=tier,
                    body_length=len(body or ""),
                    account_id=getattr(self, "_account_id", None),
                )
                final_draft = strip_reasoning_leakage(final_draft)
                final_draft = _strip_a_confirmer(final_draft)

                _cache_draft(email_id, final_draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
                was_revised = critique_info.get("was_revised", False)

                # Inject specialty match into critique_info
                if _specialty_match:
                    critique_info["specialty"] = _specialty_match.to_dict()

                # DP-01 smart_suggestions (Haiku chips) are useful but NOT required
                # to display the draft. Audit 2026-06-02 L: route() used to run this
                # extra Haiku call inline, adding a full round-trip to every
                # non-streaming response — and the /drafts/<id>/regenerate caller
                # discards the result outright. Defer it exactly like route_streaming
                # (smart_suggestions_deferred): the REST consumer already populates
                # it asynchronously when `smart_suggestions is None`
                # (routes_emails.py _populate_smart_suggestions_bg). No behavior
                # change — the value is recomputed in the background or ignored.
                critique_info["smart_suggestions_deferred"] = True

                _status = "STANDARD_V2" if was_revised else "STANDARD_HAIKU"

                return RoutingResult(
                    draft=final_draft,
                    decision=decision,
                    classification="Action",
                    priority=50,
                    status=_status,
                    critique_info=critique_info,
                    draft_v1=draft if was_revised else None,
                    correction_details=_std_correction_details,
                )

            if tier == RoutingTier.COMPLEX:
                _complex_instructions = instructions or ""
                result = self._generate_complex(
                    email_content=email_content,
                    conversation_history=conversation_history,
                    instructions=_complex_instructions,
                    user_email=user_email,
                    decision=decision,
                    thread_context=thread_context,
                )
                if result.draft:
                    # Critique + revise, except borderline COMPLEX + user notes
                    # where _validate_and_revise can take the fast path.
                    final_draft, critique_info = self._validate_and_revise(
                        draft=result.draft,
                        email_content=email_content,
                        email_id=email_id,
                        conversation_history=conversation_history,
                        instructions=_complex_instructions,
                        user_email=user_email,
                        max_tokens=decision.max_tokens or 768,
                        sender_name=sender_name,
                        greeting_hint=greeting_hint,
                        closing_hint=closing_hint,
                        specialty_context=_specialty_context_for_critic,
                        tier=tier,
                        body_length=len(body or ""),
                        account_id=getattr(self, "_account_id", None),
                        complexity_score=decision.complexity_score,
                    )
                    if email_id:
                        _cache_draft(email_id, final_draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
                    was_revised = critique_info.get("was_revised", False)
                    # Inject specialty match into critique_info
                    if _specialty_match:
                        critique_info["specialty"] = _specialty_match.to_dict()
                    result.draft = final_draft
                    result.critique_info = critique_info
                    if was_revised:
                        result.status = "COMPLEX_V2"
                    return result
                # Inject specialty match for drafts without critique
                if _specialty_match and result.critique_info:
                    result.critique_info["specialty"] = _specialty_match.to_dict()
                elif _specialty_match:
                    result.critique_info = {"specialty": _specialty_match.to_dict()}
                return result

        except Exception as e:
            logger.error(f"SmartRouter error in {tier.value}: {e}", exc_info=True)
            # Fallback: try Sonnet unified if not already COMPLEX
            if tier != RoutingTier.COMPLEX:
                logger.info("SmartRouter: falling back to COMPLEX after error")
                try:
                    return self._generate_complex(
                        email_content=email_content,
                        conversation_history=conversation_history,
                        instructions=instructions,
                        user_email=user_email,
                        decision=decision,
                    )
                except Exception as e2:
                    logger.error(f"SmartRouter COMPLEX fallback also failed: {e2}")

            return RoutingResult(
                draft="",
                decision=decision,
                classification="Action",
                priority=50,
                status="ERROR",
            )

        # Should not reach here
        return RoutingResult(draft="", decision=decision, status="ERROR")

    # =========================================================================
    # SMART SUGGESTIONS: 2-3 short reply candidates (5-15 words)
    # =========================================================================
    # DP-01 fix (2026-04-24): MEMORY.md Phase 18 declared this feature but it
    # was never wired. Frontend `PendingDraftDetail.tsx:1973` renders the
    # suggestions as clickable chips. Producer is one Haiku call (~$0.0001).
    # Always returns either a list[str] (1-3 entries) or None on failure —
    # never raises.

    _SMART_SUGG_MAX_TOKENS = 200  # ~50-60 words total (3 suggestions × 15 words + JSON overhead)

    def _generate_smart_suggestions(
        self,
        subject: str,
        body: str,
        sender_name: str = "",
        language: str = "FRENCH",
        account_id: int | None = None,
    ) -> Optional[list[str]]:
        """Generate 2-3 short reply suggestions via Haiku.

        Returns:
            list[str] (1-3 entries, each 5-15 words) or None on error/empty body.
        """
        # Guard: empty/very-short body — no useful suggestions to generate.
        if not body or len(body.strip()) < 20:
            return None

        try:
            from app.infrastructure.container import get_container
            from app.infrastructure.llm_attribution import llm_attribution
            container = get_container()
            llm = container.llm_drafting  # Haiku — cheap
            effective_account_id = account_id or getattr(self, "_account_id", None)

            is_fr = (language or "").upper() != "ENGLISH"
            if is_fr:
                system_prompt = (
                    "Tu es un assistant qui propose 2-3 suggestions de réponse courtes (5-15 mots chacune) "
                    "pour un email. Réponds STRICTEMENT en JSON: {\"suggestions\": [\"...\", \"...\"]}. "
                    "Pas de markdown, pas d'explication."
                )
                user_prompt = (
                    f"Email reçu (sujet: {subject or '(sans sujet)'}):\n\n{body[:1500]}\n\n"
                    "Propose 2-3 réponses courtes possibles (5-15 mots chacune), naturelles, sans formule de politesse."
                )
            else:
                system_prompt = (
                    "You are an assistant that proposes 2-3 short reply suggestions (5-15 words each) "
                    "for an email. Reply STRICTLY in JSON: {\"suggestions\": [\"...\", \"...\"]}. "
                    "No markdown, no explanation."
                )
                user_prompt = (
                    f"Received email (subject: {subject or '(no subject)'}):\n\n{body[:1500]}\n\n"
                    "Propose 2-3 short possible replies (5-15 words each), natural, no greeting or closing."
                )

            with llm_attribution(
                "smart_suggestions",
                account_id=effective_account_id,
                feature="drafting",
            ):
                resp = llm.complete(
                    system=system_prompt,
                    user=user_prompt,
                    max_tokens=self._SMART_SUGG_MAX_TOKENS,
                    temperature=0.7,
                )
            raw = (resp.content or "").strip() if resp else ""
            if not raw:
                return None

            # Strip markdown fences defensively
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            data = json.loads(raw)
            sugs = data.get("suggestions") if isinstance(data, dict) else None
            if not isinstance(sugs, list):
                return None

            # Filter: must be non-empty strings, 1-30 words.
            cleaned: list[str] = []
            for s in sugs:
                if not isinstance(s, str):
                    continue
                s = s.strip()
                if not s:
                    continue
                wc = len(s.split())
                if 1 <= wc <= 30:
                    cleaned.append(s)

            cleaned = cleaned[:3]
            return cleaned if cleaned else None

        except Exception as e:
            # Audit Cluster D (2026-05-17) B-09: see also the route-level
            # caller above. Promoted to .warning + exc_info so prompt-
            # template or JSON-parse regressions actually surface in logs.
            logger.warning(
                "_generate_smart_suggestions failed (non-blocking): %s",
                e, exc_info=True,
            )
            return None

    # =========================================================================
    # CRITIQUE: Validate draft via CriticAgent, revise if rejected
    # =========================================================================

    def _validate_and_revise(
        self,
        draft: str,
        email_content: str,
        email_id: str,
        conversation_history: list[dict] | None,
        instructions: str,
        user_email: str,
        max_tokens: int,
        sender_name: str,
        greeting_hint: str = "",
        closing_hint: str = "",
        formality: int = 2,
        specialty_context: str = "",
        tier: Optional["RoutingTier"] = None,
        body_length: Optional[int] = None,
        account_id: int | None = None,
        complexity_score: int | None = None,
    ) -> tuple[str, dict]:
        """Run CriticAgent on draft, revise if rejected. Returns (final_draft, critique_info).

        tier/body_length/complexity_score are passed to bounded skip gates:
        short STANDARD drafts and borderline COMPLEX drafts with user notes can
        bypass the critic when local sanity checks pass.
        """
        from app.agents import CriticAgent, DrafterAgent
        from app.domain.entities.critique import CritiqueRequest, CritiqueDecision
        from app.domain.entities.draft_generation import DraftRequest
        from app.infrastructure.llm_attribution import llm_attribution

        critique_info: dict = {}

        # Guard: empty draft means generation failed upstream — skip critique
        if not draft or not draft.strip():
            logger.warning(f"SmartRouter skipping critique for {email_id}: draft is empty")
            return draft, critique_info

        # Aggressive bypass: USE_UNIFIED_DRAFT mode trusts V1 unconditionally
        # (relies on the drafter's built-in self-critique). Saves the full
        # critic + revision loop for every draft.
        if _use_unified_draft_enabled():
            logger.info(
                f"SmartRouter critic BYPASSED for {email_id} "
                f"(USE_UNIFIED_DRAFT mode, saved ~1-3s)"
            )
            _record_critic_outcome(skipped=True)
            _record_critic_gate("skipped_unified")
            return draft, {
                "is_valid": True,
                "decision": "valid",
                "overall_score": 80,
                "skipped": True,
                "skip_reason": "use_unified_draft",
                "evaluation_time_ms": 0,
                "tokens_used": 0,
            }

        if (
            tier is not None
            and tier == RoutingTier.COMPLEX
            and _complex_user_notes_fast_path_passes(
                draft=draft,
                email_content=email_content,
                instructions=instructions,
                complexity_score=complexity_score,
                greeting_hint=greeting_hint,
                closing_hint=closing_hint,
                specialty_context=specialty_context,
                body_length=body_length,
            )
        ):
            logger.info(
                f"SmartRouter critic SKIPPED for {email_id} "
                f"(complex user-notes fast path, score={complexity_score}, saved ~2-6s)"
            )
            _record_critic_outcome(skipped=True)
            _record_critic_gate("skipped_complex_user_notes")
            return draft, {
                "is_valid": True,
                "decision": "valid",
                "overall_score": 82,
                "skipped": True,
                "skip_reason": "complex_user_notes_fast_path",
                "evaluation_time_ms": 0,
                "tokens_used": 0,
            }

        # Heuristic confidence gate — skip the LLM critic (-1 to -2s) on drafts
        # that pass all quality rules. Controlled by env var SKIP_CRITIC_GATE
        # (default: enabled). A rejected draft still goes through the full
        # critic + revise loop.
        # Tier-aware: COMPLEX never bypasses; short STANDARD gets fast-path.
        if _skip_critic_gate_enabled() and _draft_passes_quality_gate(
            draft=draft,
            email_content=email_content,
            formality=formality,
            has_instructions=_has_meaningful_user_instructions(instructions),
            tier=tier,
            body_length=body_length,
        ):
            tier_label = tier.value if tier else "?"
            logger.info(
                f"SmartRouter critic SKIPPED for {email_id} "
                f"(heuristic gate passed, tier={tier_label}, saved ~1-2s)"
            )
            critique_info = {
                "is_valid": True,
                "decision": "valid",
                "overall_score": 85,
                "skipped": True,
                "skip_reason": "heuristic_gate_passed",
                "evaluation_time_ms": 0,
                "tokens_used": 0,
            }
            _record_critic_outcome(skipped=True)
            _record_critic_gate("skipped_heuristic")

            # P2.7 — Spot-check 5% of skipped drafts via the LLM critic to
            # detect drift in the heuristic gate. Background-only: the user
            # already got `valid` above; the spot-check log is for ops, not
            # user UX. We don't await — fire-and-forget on a background
            # thread so latency is unaffected.
            try:
                import random as _random
                _spot_rate = _critic_spot_check_rate()
                if _spot_rate > 0.0 and _random.random() < _spot_rate:
                    import threading as _threading

                    def _spot_check_worker(_draft, _email_content, _email_id, _specialty, _tier_label):
                        try:
                            critique_request = CritiqueRequest(
                                draft_content=_draft,
                                original_email=_email_content,
                                email_id=_email_id,
                                context=_specialty or None,
                            )
                            critic = CriticAgent(account_id=account_id)
                            with llm_attribution(
                                "critic_spot_check",
                                account_id=account_id,
                                feature="drafting",
                            ):
                                res = critic.evaluate_draft(critique_request)
                            score = res.scores.calculate_overall()
                            decision = getattr(res, "decision", None)
                            decision_val = getattr(decision, "value", str(decision))
                            # Disagreement = heuristic said valid but critic said reject
                            disagreement = decision_val.lower().startswith("reject") if isinstance(decision_val, str) else False
                            logger.info(
                                "[CRITIC_SPOT_CHECK] email_id=%s tier=%s heuristic=valid "
                                "critic_decision=%s critic_score=%d disagreement=%s "
                                "risks=%s",
                                _email_id, _tier_label, decision_val, score, disagreement,
                                ",".join(res.suggestions[:3]) if res.suggestions else "",
                            )
                        except Exception as _e:  # pragma: no cover — telemetry never breaks
                            logger.debug(f"[CRITIC_SPOT_CHECK] worker failed: {_e}")

                    _t = _threading.Thread(
                        target=_spot_check_worker,
                        args=(draft, email_content, email_id, specialty_context, tier_label),
                        daemon=True,
                        name=f"critic-spot-check-{email_id[:8] if email_id else 'unk'}",
                    )
                    _t.start()
            except Exception as _spot_e:  # pragma: no cover — never break the gate
                logger.debug(f"[CRITIC_SPOT_CHECK] dispatch failed: {_spot_e}")

            return draft, critique_info

        # Reaching here = full LLM critic path. Record before the call so the
        # counter is correct even if the critic raises and falls into the
        # exception handler below.
        _record_critic_outcome(skipped=False)
        _record_critic_gate("ran")

        try:
            # Build critique request — propagate tier+intent so CriticAgent
            # picks an effective_threshold tuned to the email's risk profile
            # (audit 2026-05-06).
            _tier_str = (tier.value if tier is not None else None)
            _intent_marker = (
                "tone_sensitive"
                if _is_tone_sensitive(email_content, "", instructions or "")
                else None
            )
            critique_request = CritiqueRequest(
                draft_content=draft,
                original_email=email_content,
                email_id=email_id,
                context=specialty_context or None,
                tier=_tier_str,
                intent=_intent_marker,
            )

            # Evaluate — this emits critique_start / critique_complete WebSocket events
            critic = CriticAgent(account_id=account_id)
            with llm_attribution("critic", account_id=account_id, feature="drafting"):
                critique_result = critic.evaluate_draft_with_retry(critique_request)

            # Audit failure-mode #4 (2026-04-24): when the critic LLM call
            # fails (timeout, rate-limit, malformed JSON), evaluate_draft
            # returns CritiqueResult.create_failed which has decision=REJECT
            # and status=FAILED. We expose `critique_failed` so downstream
            # code (and the UI) can distinguish "real REJECT" from
            # "evaluation could not run". Without this flag, a double
            # timeout (critic + V2) leaves the user looking at V1 with no
            # visible warning that quality was never verified.
            from app.domain.entities.critique import CritiqueStatus as _CS
            _critique_failed = getattr(critique_result, "status", None) in (
                _CS.FAILED, _CS.RATE_LIMITED,
            )
            critique_info = {
                "is_valid": critique_result.decision == CritiqueDecision.VALID,
                "decision": critique_result.decision.value,
                "overall_score": critique_result.scores.calculate_overall(),
                "scores": {
                    "coherence": critique_result.scores.coherence,
                    "tone": critique_result.scores.tone,
                    "completeness": critique_result.scores.completeness,
                    "errors": critique_result.scores.errors,
                    "conciseness": critique_result.scores.conciseness,
                    "over_commitment": critique_result.scores.over_commitment,
                    "emotional_intelligence": critique_result.scores.emotional_intelligence,
                },
                "suggestions": critique_result.suggestions,
                "explanation": critique_result.explanation,
                "evaluation_time_ms": critique_result.evaluation_time_ms,
                "tokens_used": critique_result.tokens_used,
                "critique_failed": _critique_failed,
                "critique_status": getattr(critique_result, "status", _CS.COMPLETED).value
                    if hasattr(getattr(critique_result, "status", _CS.COMPLETED), "value")
                    else "completed",
            }

            if critique_result.decision == CritiqueDecision.VALID:
                logger.info(
                    f"SmartRouter critique VALID for {email_id} "
                    f"(score={critique_info['overall_score']})"
                )
                return draft, critique_info

            # REJECT → revise
            logger.info(
                f"SmartRouter critique REJECT for {email_id} "
                f"(score={critique_info['overall_score']}), generating V2"
            )
            draft_request = DraftRequest(
                email_content=email_content,
                instructions=instructions or None,
                conversation_history=conversation_history,
                user_email=user_email or None,
            )
            drafter = DrafterAgent(account_id=account_id)
            with llm_attribution("drafter", account_id=account_id, feature="drafting"):
                revised = drafter.revise_with_critique_and_retry(
                    draft_request,
                    critique_result,
                )

            if revised.content:
                critique_info["was_revised"] = True
                v2_draft = revised.content
                # Post-LLM cleanup on V2 (same pipeline as V1)
                v2_draft = _strip_html_tags(v2_draft)
                v2_draft = _clean_prompt_leakage(v2_draft)
                v2_draft = _strip_markdown_artifacts(v2_draft)
                v2_draft = _strip_clarification_draft(v2_draft)
                v2_draft = _strip_filler_mid_draft(v2_draft, formality)
                v2_draft = _strip_signature(v2_draft)
                if greeting_hint:
                    v2_draft = _enforce_greeting(v2_draft, greeting_hint)
                v2_draft = _enforce_closing(v2_draft, closing_hint)
                # Issue #592: collapse stacked contextual + canonical closings.
                v2_draft = _strip_stacked_contextual_closing(v2_draft)

                capture_if_enabled(
                    mode="v2_partial",
                    raw_draft=revised.content,
                    pipeline_input={
                        "body": email_content,
                        "sender_name": sender_name,
                        "greeting_hint": greeting_hint,
                        "formality": formality,
                        "conversation_history": conversation_history or [],
                    },
                    cleaned_draft=v2_draft,
                    corrections=0,
                    correction_details=[],
                    learned_corrections_applied=[],
                    extra={"email_id": email_id},
                )

                # Guard: if V2 post-processing destroyed the content, keep V1
                v2_len = len(v2_draft.strip())
                v1_len = len(draft.strip())
                if v2_len < 50 or (v1_len > 0 and v2_len < v1_len * 0.3):
                    logger.warning(
                        f"V2 draft too short after cleanup ({v2_len} chars vs V1 {v1_len} chars) "
                        f"for {email_id}, keeping V1"
                    )
                    critique_info["was_revised"] = False
                    critique_info["v2_discarded"] = True
                    return draft, critique_info

                # ----- V3 revision for COMPLEX / tone-sensitive (audit 2026-05-05) ---
                # Currently the loop is V1 → V2 and stops. For high-stakes drafts
                # (COMPLEX tier or decline / RH / complaint patterns), allow a
                # second revise iteration if V2 still fails the critic AND its
                # score improved over V1 by ≥ 5 pts (above LLM-judge variance —
                # otherwise the next pass is a coin flip, not a fix).
                # Hard cap = 2 revisions total. Cost: +2 Haiku calls (~$0.0006)
                # on the ~5–10% of drafts that qualify. Scoped tightly so the
                # average draft cost is unaffected.
                #
                # Audit 2026-05-06: gated by CRITIC_MAX_REVISIONS env (default 2).
                # Set to 1 to disable V3 entirely without a redeploy — used as
                # the rollback knob if V2-vs-V3 eval shows V3 isn't measurably
                # better, or if total spend creeps up.
                try:
                    _max_revisions = int(_os_gate.environ.get("CRITIC_MAX_REVISIONS", "2"))
                except (TypeError, ValueError):
                    _max_revisions = 2
                is_high_stakes = (
                    _max_revisions >= 2
                    and (
                        (tier is not None and tier == RoutingTier.COMPLEX)
                        or _is_tone_sensitive(email_content, "", instructions or "")
                    )
                )
                if is_high_stakes:
                    try:
                        v2_request = CritiqueRequest(
                            draft_content=v2_draft,
                            original_email=email_content,
                            email_id=email_id,
                            context=specialty_context or None,
                            tier=_tier_str,
                            intent=_intent_marker,
                        )
                        with llm_attribution(
                            "critic",
                            account_id=account_id,
                            feature="drafting",
                        ):
                            v2_critique = critic.evaluate_draft_with_retry(v2_request)
                        v2_score = v2_critique.scores.calculate_overall()
                        v1_score = critique_info["overall_score"]
                        critique_info["v2_score"] = v2_score
                        if (
                            v2_critique.decision == CritiqueDecision.REJECT
                            and v2_score - v1_score >= 5
                        ):
                            logger.info(
                                f"SmartRouter HIGH-STAKES re-critique REJECT for {email_id} "
                                f"(V1={v1_score} V2={v2_score}, +{v2_score - v1_score}pts) — "
                                f"generating V3"
                            )
                            with llm_attribution(
                                "drafter",
                                account_id=account_id,
                                feature="drafting",
                            ):
                                v3 = drafter.revise_with_critique_and_retry(
                                    draft_request,
                                    v2_critique,
                                )
                            if v3.content:
                                v3_draft = _strip_html_tags(v3.content)
                                v3_draft = _clean_prompt_leakage(v3_draft)
                                v3_draft = _strip_markdown_artifacts(v3_draft)
                                v3_draft = _strip_clarification_draft(v3_draft)
                                v3_draft = _strip_filler_mid_draft(v3_draft, formality)
                                v3_draft = _strip_signature(v3_draft)
                                if greeting_hint:
                                    v3_draft = _enforce_greeting(v3_draft, greeting_hint)
                                v3_draft = _enforce_closing(v3_draft, closing_hint)
                                # Issue #592: drop stacked contextual + canonical closings.
                                v3_draft = _strip_stacked_contextual_closing(v3_draft)
                                v3_len = len(v3_draft.strip())
                                # Same shrinkage guard as V2 — if cleanup ate
                                # the body, keep V2 instead of shipping a stub.
                                if v3_len >= 50 and v3_len >= v2_len * 0.5:
                                    critique_info["was_revised_v3"] = True
                                    critique_info["revise_iterations"] = 2
                                    return v3_draft, critique_info
                                logger.warning(
                                    f"V3 draft too short after cleanup "
                                    f"({v3_len} chars vs V2 {v2_len}), keeping V2"
                                )
                        elif v2_critique.decision == CritiqueDecision.REJECT:
                            logger.info(
                                f"SmartRouter HIGH-STAKES re-critique REJECT but no "
                                f"improvement (V1={v1_score} V2={v2_score}) — "
                                f"shipping V2 (V3 unlikely to help)"
                            )
                    except Exception as v3_err:  # pragma: no cover — telemetry
                        logger.debug(f"HIGH-STAKES V3 attempt failed: {v3_err}")

                critique_info.setdefault("revise_iterations", 1)
                return v2_draft, critique_info

            # Revision failed — return original draft but signal the failure
            logger.warning(f"SmartRouter V2 revision empty for {email_id}, keeping V1")
            critique_info["revision_failed"] = True
            return draft, critique_info

        except Exception as e:
            logger.error(f"SmartRouter critique error for {email_id}: {e}", exc_info=True)
            # Critique failure is non-fatal — return original draft with error info
            critique_info = {
                "is_valid": True,
                "feedback": f"Critique skipped (error: {e})",
                "error": True,
            }
            return draft, critique_info

    # =========================================================================
    # SIMPLE: Template engine
    # =========================================================================

    def _closing_hint_for(self, formality: int, language: str) -> str:
        """Resolve a closing hint for (formality, language), honouring the
        user's preferred_closings from their writing style profile."""
        from app.prompts import _compute_closing_hint
        _preferred: list[str] | None = None
        try:
            from app.infrastructure.container import get_container
            _profile = get_container().get_writing_style_profile(
                account_id=getattr(self, "_account_id", 1)
            )
            if _profile and _profile.preferred_closings:
                _preferred = list(_profile.preferred_closings)
                # Formality-based slot selection: in the DEFAULT closings list
                # index 0 = formal, index 1 = casual (same convention as
                # preferred_greetings). For a casual reply (formality <= 2) put
                # the casual slot first so _compute_closing_hint returns it —
                # otherwise the formal slot always won and the trained casual
                # closing ("À bientôt,") was effectively dead.
                if (
                    formality <= 2
                    and len(_preferred) >= 2
                    and (_preferred[1] or "").strip()
                ):
                    _preferred = [_preferred[1], _preferred[0]] + _preferred[2:]
        except Exception as _e:
            logger.debug(f"Suppressed: {_e}")
        return _compute_closing_hint(formality, language, _preferred)

    def _generate_simple(
        self,
        sender: str,
        subject: str,
        body: str,
    ) -> str:
        """
        Try to generate a response without calling the LLM.

        Strategy:
          1. Automated senders → match existing templates
          2. Human senders with very simple emails → micro-templates ($0.00)
          3. Otherwise → return "" (fallback to STANDARD/Haiku)
        """
        sender_lower = sender.lower().strip()
        is_automated = _SKIP_SENDER_PATTERNS.search(sender_lower)

        # --- Path A: Automated senders → existing template engine ---
        if is_automated:
            try:
                from app.infrastructure.container import get_container
                container = get_container()
                match_uc = container.get_match_template_use_case()
                match = match_uc.execute(
                    category="reply", subject=subject or "", body=body or "",
                )
                if match:
                    variables = {"sender_name": _extract_first_name(sender)}
                    try:
                        profile = container.get_writing_style_profile(account_id=getattr(self, "_account_id", 1))
                        if profile:
                            if profile.preferred_greetings:
                                variables["greeting"] = profile.preferred_greetings[0]
                            if profile.preferred_closings:
                                # Audit S-01 (2026-05-11): filter the
                                # `(no closing or just name)` sentinel before
                                # template render. Path A bypasses the LLM
                                # entirely, so the sentinel would leak raw
                                # into the body of any custom template that
                                # uses ${sign_off}. _is_no_closing_marker is
                                # the same helper used by _compute_closing_hint
                                # post-PR #634.
                                from app.prompts.identity import _is_no_closing_marker
                                _first_closing = profile.preferred_closings[0]
                                if not _is_no_closing_marker(_first_closing):
                                    variables["sign_off"] = _first_closing
                                # else: leave variables["sign_off"] unset —
                                # the template engine substitutes "" for
                                # missing keys via safe_substitute.
                            if profile.typical_signature:
                                variables["signature"] = profile.typical_signature
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                    render_uc = container.get_render_template_use_case()
                    rendered = render_uc.execute(template=match.template, variables=variables)
                    logger.info(f"SmartRouter SIMPLE: template '{match.template.name}' (score={match.score:.0%})")
                    return rendered
            except Exception as e:
                logger.warning(f"SmartRouter SIMPLE template error: {e}")
            return ""

        # --- Path B: Human senders → micro-templates for very simple emails ---
        return self._try_micro_template(sender, subject, body)

    def _try_micro_template(
        self,
        sender: str,
        subject: str,
        body: str,
    ) -> str:
        """
        For very simple human emails, generate a style-aware response
        without calling the LLM. Returns "" if no pattern matches.

        Patterns matched:
          - Meeting/availability confirmations
          - Simple acknowledgments (received, thanks)
          - Info sharing (FYI, no response needed)
        """
        text = f"{subject}\n{body}".lower()
        first_name = _extract_first_name(sender, signature_text=body)

        # Detect formality + language (single source of truth for both
        # greeting computation and pattern selection).
        from app.prompts import (
            analyze_email_formality, _detect_language,
            _compute_greeting_hint, _extract_display_name,
        )
        formality = analyze_email_formality(f"{subject}\n{body}")
        lang = _detect_language(f"{subject} {body}", fallback_language=self._primary_language_fallback())
        is_fr = lang != "ENGLISH"

        # Canonical greeting — same logic as the LLM tiers. We used to hard-code
        # formality→word mapping here; now we defer to the single function so
        # STANDARD, STREAMING, COMBINED and SIMPLE all produce
        # identical greetings for the same contact.
        _display_sender = _extract_display_name(sender) or sender
        # Pass raw `sender` so the email-prefix tiebreaker fires when the
        # display name only carries the last name (e.g. `"Aubert" <alexandra…>`).
        greeting = _compute_greeting_hint(
            _display_sender,
            formality,
            lang,
            sender_email=sender,
            signature_text=body,
        )

        # User-level override: if the writing style profile has a preferred
        # greeting template (e.g. "Bonjour {first_name}," or
        # "Bonjour {civility} {last_name},"), expand the supported tokens
        # against the current recipient.
        _template_used = False
        try:
            from app.infrastructure.container import get_container
            profile = get_container().get_writing_style_profile(account_id=getattr(self, "_account_id", 1))
            if profile and profile.preferred_greetings:
                # Convention: index 0 = formal, index 1 = casual.
                # Pick casual when the incoming email signals tutoiement / low
                # formality (score 1-2). Fall back to formal otherwise — and to
                # the formal slot if casual is empty.
                casual_template = (
                    profile.preferred_greetings[1].strip()
                    if len(profile.preferred_greetings) >= 2
                    else ""
                )
                formal_template = profile.preferred_greetings[0].strip()
                preferred = casual_template if (formality <= 2 and casual_template) else formal_template
                if preferred:
                    # Pass the raw `sender` (with "<email>") so the tiebreaker
                    # inside `_expand_greeting_template` can fall back to the
                    # email prefix when the display name only carries the last
                    # name (e.g. `"Aubert" <alexandra.aubert@…>`).
                    expanded = _expand_greeting_template(preferred, sender, lang)
                    if expanded:
                        greeting = expanded
                        _template_used = True
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        # Defensive: ensure first name is present when we have one and the
        # greeting doesn't already carry it (only when we did NOT use a user
        # template — the template is the source of truth).
        if not _template_used and first_name and first_name not in greeting:
            greeting = greeting.rstrip(',') + f" {first_name},"

        # --- Pattern: Direct "call me" request ---
        call_me_kw = ['appelle-moi', 'appelle moi', 'rappelle-moi', 'rappelle moi',
                      'call me', 'call me back', 'give me a call']
        if any(k in text for k in call_me_kw) and len(body) < 50:
            if is_fr:
                if formality >= 4:
                    return f"{greeting}\n\nJe vous appelle dans un instant."
                else:
                    return f"{greeting}\n\nJe t'appelle dans un instant."
            else:
                return f"{greeting}\n\nI'll call you in a moment."

        # --- Pattern: Safe confirmation question ---
        # Short "can you confirm X?" emails are common and low-risk when the
        # answer explicitly says we will check before confirming. This avoids a
        # Haiku call without inventing availability, dates, deadlines or next
        # steps.
        confirm_question_kw = [
            'confirmer', 'confirm', 'confirmation', 'disponibilité',
            'disponibilités', 'availability', 'délai', 'delai', 'deadline',
            'timeline', 'échéance', 'echeance', 'prochaine étape',
            'prochaine etape', 'next step',
        ]
        is_question = '?' in body or any(
            marker in text
            for marker in (
                'pouvez-vous', 'pouvez vous', 'peux-tu', 'peux tu',
                'can you', 'could you', 'would you',
            )
        )
        if (
            is_question
            and len(body) < 260
            and _count_questions(body) <= 1
            and any(k in text for k in confirm_question_kw)
        ):
            if is_fr:
                formal_request = any(
                    marker in text
                    for marker in ('pouvez-vous', 'pouvez vous', ' pourriez-vous', ' pourriez vous')
                )
                pronoun = "vous" if formality >= 4 or formal_request else "te"
                response_greeting = greeting
                if formal_request and response_greeting.lower().startswith(("salut", "coucou")):
                    response_greeting = "Bonjour,"
                if any(k in text for k in ('disponibilité', 'disponibilités', 'dispo')):
                    return f"{response_greeting}\n\nJe vérifie mes disponibilités et je {pronoun} confirme rapidement."
                if any(k in text for k in ('délai', 'delai', 'deadline', 'timeline', 'échéance', 'echeance', 'prochaine étape', 'prochaine etape')):
                    return f"{response_greeting}\n\nJe vérifie la prochaine étape et le délai prévu, puis je {pronoun} confirme rapidement."
                return f"{response_greeting}\n\nJe vérifie et je {pronoun} confirme rapidement."
            if any(k in text for k in ('availability', 'available')):
                return f"{greeting}\n\nI'll check my availability and confirm shortly."
            if any(k in text for k in ('deadline', 'timeline', 'next step')):
                return f"{greeting}\n\nI'll check the next step and expected timeline, then confirm shortly."
            return f"{greeting}\n\nI'll check and confirm shortly."

        # --- Pattern: Meeting/availability request ---
        # Guard: only simple confirmations (short body, at most 1 question)
        meeting_kw = ['réunion', 'reunion', 'meeting', 'rendez-vous', 'rdv',
                      'dispo', 'disponible', 'available', 'call', 'appel']
        if (any(k in text for k in meeting_kw)
                and len(body) < 120
                and '?' not in body):
            if is_fr:
                return f"{greeting}\n\nJe confirme ma disponibilité. On se cale ça rapidement."
            else:
                return f"{greeting}\n\nI confirm my availability. Let's schedule it soon."

        # --- Pattern: Simple acknowledgment (received, noted) ---
        ack_kw = ['bien reçu', 'bien recu', 'recu', 'reçu', 'noted', 'got it',
                  'received', 'ci-joint', 'en pièce jointe', 'attached', 'voici',
                  'pour info', 'fyi', 'pour information']
        if any(k in text for k in ack_kw) and len(body) < 150:
            if is_fr:
                return f"{greeting}\n\nBien reçu, merci ! Je prends note."
            else:
                return f"{greeting}\n\nReceived, thank you! I'll take note."

        # --- Pattern: Thanks/gratitude (no action needed) ---
        thanks_kw = ['merci pour', 'merci beaucoup', 'thank you for',
                     'thanks for', 'thanks a lot', 'thanks so much']
        if any(k in text for k in thanks_kw) and len(body) < 120 and '?' not in body:
            if is_fr:
                return f"{greeting}\n\nAvec plaisir ! N'hésitez pas si vous avez besoin d'autre chose."
            else:
                return f"{greeting}\n\nYou're welcome! Let me know if you need anything else."

        # No micro-template match → fallback to STANDARD
        return ""

    # =========================================================================
    # PROMPT BUILDER (shared by realtime + batch)
    # =========================================================================

    def _build_prompts(
        self,
        sender: str,
        subject: str,
        body: str,
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        sender_name: str = "",
        thread_context: list[dict] | None = None,
        specialty_context: str = "",
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) for LLM draft generation.

        Shared by both real-time (_generate_standard) and batch (enqueue_for_batch).
        specialty_context is passed by the caller (computed in route() only for non-SIMPLE tiers).
        """
        from app.infrastructure.container import get_container
        from app.prompts import get_standard_draft_prompts, load_account_knowledge

        container = get_container()
        account_id_attr = getattr(self, "_account_id", 1)

        # ── Lever 5: parallel loading of independent prompt inputs ─────────
        # 4 loaders, all I/O-bound (DB / file / scoring), submitted to the
        # shared pool and joined below. Saves ~30-80ms vs sequential.
        def _load_style() -> str:
            try:
                profile = container.get_writing_style_profile(account_id=account_id_attr)
                if profile:
                    from app.prompts.style_guidance import build_style_guidance_from_profile
                    return build_style_guidance_from_profile(
                        profile, language="fr", recipient_email=sender
                    )
            except Exception as e:
                logger.debug(f"style profile load failed: {e}")
            return ""

        def _load_kb() -> str:
            try:
                # P0.1 (2026-05-14): prefer the per-account KB built from
                # onboarding over the deprecated global memoire.md. The
                # per-account KB is the user's actual profile + FAQs + rules.
                # Two effects:
                #   1. Quality — the reply path now sees the user's real
                #      facts instead of a generic placeholder.
                #   2. Caching — the per-account KB is substantial, which
                #      lets segment 1 of the segmented system prompt clear
                #      the Haiku prompt-cache floor reliably.
                return load_account_knowledge(account_id_attr)
            except Exception as e:
                logger.debug(f"knowledge base load failed: {e}")
                return ""

        def _load_faq() -> str:
            try:
                if not account_id_attr:
                    return ""
                faq_entries = _load_faq_entries_cached(account_id_attr)
                if not faq_entries:
                    return ""
                from app.faq_agent import find_relevant_faqs_for_drafter
                relevant = find_relevant_faqs_for_drafter(subject, body, faq_entries)
                if not relevant:
                    return ""
                logger.info(
                    "_build_prompts: %d FAQ injected as grounding (top score=%.0f%%)",
                    len(relevant), relevant[0].score,
                )
                return "\n\n".join(
                    f"Q: {m.entry_title}\nR: {m.entry_content}" for m in relevant
                )
            except Exception as e:
                logger.debug(f"FAQ grounding load failed: {e}")
                return ""

        def _load_filtered_history() -> Optional[list[dict]]:
            if not conversation_history or len(conversation_history) <= 3:
                return conversation_history
            try:
                from app.api.routes import _find_relevant_history_for_email
                relevant = _find_relevant_history_for_email(body, conversation_history)
                if relevant:
                    logger.info(
                        f"_build_prompts: filtered history {len(conversation_history)} -> {len(relevant)} relevant items"
                    )
                    return relevant
            except Exception as e:
                logger.debug(f"history filter failed: {e}")
            return conversation_history

        # Submit all 4 loaders to the shared pool; gather results.
        _f_style = _prompt_loader_pool.submit(_load_style)
        _f_kb = _prompt_loader_pool.submit(_load_kb)
        _f_faq = _prompt_loader_pool.submit(_load_faq)
        _f_history = _prompt_loader_pool.submit(_load_filtered_history)

        style_context = _f_style.result()
        knowledge_base = _f_kb.result()
        faq_context = _f_faq.result()
        filtered_history = _f_history.result()

        return get_standard_draft_prompts(
            sender=sender,
            subject=subject,
            body=body,
            style_context=style_context,
            conversation_history=filtered_history,
            instructions=instructions,
            contact=sender,
            sender_name=sender_name,
            knowledge_base=knowledge_base,
            thread_context=thread_context,
            specialty_context=specialty_context,
            faq_context=faq_context,
            account_id=getattr(self, "_account_id", None),
        )

    # =========================================================================
    # STANDARD: Haiku drafter (compact prompt)
    # =========================================================================

    def _generate_standard(
        self,
        email_content: str,
        sender: str,
        subject: str,
        body: str,
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        max_tokens: int = 512,
        sender_name: str = "",
        thread_context: list[dict] | None = None,
        specialty_context: str = "",
        temperature_override: float | None = None,
    ) -> tuple[str, list]:
        """Generate draft using Haiku with compressed prompt.

        Returns (final_draft, correction_details) — the cleanup-pipeline
        labels applied (`html_cleanup`, `parroting`, ...) so callers can
        surface them in PendingDraft.correction_details.

        `temperature_override` lets the COMPLEX self-consistency path produce
        two diverse samples (e.g. 0.4 + 0.7) for best-of-2 picking. None
        preserves the formality-derived temperature (default behavior).
        """
        from app.infrastructure.container import get_container

        container = get_container()

        system_prompt, user_prompt = self._build_prompts(
            sender=sender, subject=subject, body=body,
            conversation_history=conversation_history,
            instructions=instructions, sender_name=sender_name,
            thread_context=thread_context,
            specialty_context=specialty_context,
        )

        # Use formality-based temperature for better tone matching
        from app.prompts import (
            analyze_email_formality, formality_to_temperature,
            _compute_greeting_hint, _detect_language,
        )
        formality = analyze_email_formality(f"{subject}\n{body}")
        temperature = (
            float(temperature_override)
            if temperature_override is not None
            else formality_to_temperature(formality)
        )

        # Pre-compute greeting hint for post-LLM enforcement
        detected_language = _detect_language(f"{subject} {body}", fallback_language=self._primary_language_fallback())

        # Check if user explicitly requests a translation to a different language
        from app.prompts import _detect_language_override
        language_override = _detect_language_override(instructions) if instructions else None
        if language_override:
            detected_language = language_override

        # Extract sender name from email if not provided (must match prompt builder)
        effective_sender_name = sender_name
        if not effective_sender_name:
            from app.prompts import _extract_display_name
            effective_sender_name = _extract_display_name(sender)
        greeting_hint = _compute_greeting_hint(
            effective_sender_name or "",
            _email_reply_greeting_formality(formality, instructions),
            detected_language,
            sender_email=sender,
            signature_text=body,
        )
        closing_hint = self._closing_hint_for(formality, detected_language)

        # Use Haiku (drafting key), upgrade to Sonnet for tone-sensitive
        llm = container.llm_drafting
        from app.config import SONNET_ROUTING_ENABLED
        if SONNET_ROUTING_ENABLED and _is_tone_sensitive(body, subject, instructions):
            llm = container.llm_drafting_smart
            logger.info("SmartRouter STANDARD: upgrading to Sonnet (tone-sensitive email)")

        def _llm_generate(temp: float) -> tuple[str, int]:
            """Generate a draft at given temperature and return (raw_draft, output_tokens).

            Transient LLM failures (provider timeout, 5xx, rate-limit blip) return
            an empty draft so the tier router can fall back gracefully.

            PERMANENT errors (credits exhausted, invalid API key, model not found,
            invalid_request) are RE-RAISED so the bg thread's `except Exception`
            handler can surface a `draft_error` WebSocket event instead of
            silently saving a NULL-body draft. This was bug #1 in the audit
            2026-05-03 : retries on a 400 invalid_request burned 3 LLM calls
            before falling back to the canned "Je vous recontacte rapidement.",
            which then got persisted with a null body and no failure signal
            to the frontend (infinite spinner UX).
            """
            from app.domain.exceptions import classify_llm_error
            from app.infrastructure.llm_attribution import llm_attribution

            try:
                with llm_attribution(
                    "smart_router",
                    account_id=getattr(self, "_account_id", None),
                    feature="drafting",
                ):
                    resp = llm.complete(
                        system=system_prompt,
                        user=user_prompt,
                        max_tokens=max_tokens,
                        temperature=temp,
                    )
            except Exception as _llm_err:
                is_permanent, code, _ = classify_llm_error(_llm_err)
                logger.error(
                    "SmartRouter STANDARD: LLM call failed (%s, permanent=%s, code=%s): %s",
                    type(_llm_err).__name__, is_permanent, code, _llm_err,
                )
                if is_permanent:
                    # Don't retry, don't fall back to canned text — surface to
                    # bg thread so it emits draft_error and the user sees a
                    # retry CTA instead of an infinite spinner.
                    raise
                return "", 0
            if hasattr(resp, "input_tokens"):
                container.token_usage.add(
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    model=getattr(llm, "model", "haiku"),
                )
            out_tokens = getattr(resp, "output_tokens", 0)
            raw = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
            return raw, out_tokens

        def _apply_pipeline(raw_draft: str) -> tuple[str, int, list]:
            """Apply post-LLM pipeline. Returns (cleaned_draft, corrections_count, correction_details)."""
            corrections = 0
            correction_details: list[str] = []
            learned_applied: list = []  # populated by the learned_corrections hook below
            d = raw_draft
            _pipeline_start = time.monotonic()

            def _track(before, after, label: str):
                nonlocal corrections
                if before != after:
                    corrections += 1
                    correction_details.append(label)
                return after

            d = _track(d, _strip_html_tags(d), "html_cleanup")
            d = _track(d, _clean_prompt_leakage(d), "prompt_leakage")
            d = _track(d, strip_unknown_body_artifacts(d), "unknown_body_artifact")
            # Reasoning leakage MUST run before _strip_markdown_artifacts —
            # the leakage detector relies on intact `- ` / `* ` bullet
            # markers to drop enumerated reasoning lines. Stripping the
            # markers first leaves bare-text reasoning that no later step
            # can recognize. See 2026-05-13 stress test, Bug C.
            d = _track(d, strip_reasoning_leakage(d), "reasoning_leakage")
            d = _track(d, _strip_markdown_artifacts(d), "markdown_cleanup")
            d = _track(d, _strip_clarification_draft(d), "clarification_removed")
            d = _track(d, _strip_filler_mid_draft(d, formality), "filler_removed")
            d = _track(d, _strip_signature(d), "signature_cleaned")
            d = _track(d, _truncate_for_short_body(d, body, user_context=instructions or ""), "truncated_short")
            d = _track(d, _strip_subject_echo(d, subject), "subject_echo")
            d = _track(d, _strip_technical_echo(d, body), "technical_echo")
            if len(body) >= 300:
                d = _track(d, _strip_parroting(d, body), "parroting")
            else:
                d = _track(d, _strip_leading_parrot(d, body), "parroting")
            d = _track(d, _scrub_hallucinated_facts(d, body), "hallucinated_facts")
            d = _track(d, _scrub_invented_contacts(d, body), "invented_contacts")
            d = _track(d, _scrub_ungrounded_nouns(d, body, subject=subject, sender=sender, user_context=instructions or ""), "ungrounded_nouns")
            d = _track(d, _scrub_novel_situation(d, body, subject=subject, user_context=instructions or ""), "novel_situation")
            has_history = bool(conversation_history)
            d = _track(d, _scrub_hallucinated_context(d, body, has_history=has_history), "hallucinated_context")
            d = _track(d, _scrub_process_language(d), "process_language")
            d = _track(d, _strip_hedging(d), "hedging")
            d = _track(d, _strip_a_confirmer(d), "placeholder_removed")
            d = _track(d, _strip_sycophancy(d), "sycophancy")
            d = _track(d, _strip_unnecessary_questions(d, body), "unnecessary_questions")
            d = _track(d, _strip_excessive_apologies(d), "excessive_apologies")
            d = _track(d, _strip_redundant_affirmations(d), "redundant_affirmations")
            d = _track(d, _simplify_contrast_patterns(d), "contrast_simplified")
            d = _track(d, _strip_slop_words(d), "slop_words")
            d = _track(d, strip_ai_dashes(d), "ai_dashes")
            d = _track(d, _strip_recap_sentences(d), "recap_removed")
            d = _track(d, _fix_repetitive_openings(d), "repetitive_openings")
            d = _track(d, _strip_duplicate_greetings(d), "duplicate_greetings")

            try:
                from app.draft_correction import get_correction_manager
                corrected, applied = get_correction_manager().apply_learned_corrections(
                    d, context={"sender": sender, "subject": subject}
                )
                if applied:
                    d = corrected
                    corrections += len(applied)
                    correction_details.append("learned_corrections")
                    learned_applied = list(applied)
                    logger.info(f"SmartRouter STANDARD: {len(applied)} learned correction(s) applied")
                    d = _strip_filler_mid_draft(d, formality)
                    d = _scrub_hallucinated_facts(d, body)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            d = _detect_misdirected(d, body, sender_name or sender)
            d = _detect_social_engineering(d, body)
            d = _detect_blackmail(d, body)
            d = _ensure_legal_caution(d, body)
            d = _clean_language_artifacts(d)
            d = _detect_language_drift(d, detected_language)
            d = _fix_pronoun_consistency(d, formality)
            d = _fix_closing_tone(d, formality)
            d = _fix_name_overuse(d, effective_sender_name or "")
            d = _enforce_greeting(d, greeting_hint)
            d = _enforce_closing(d, closing_hint)
            # Issue #592: drop stacked contextual closings like
            # "À ce vendredi !\n\nÀ bientôt," that the LLM ignored despite
            # RULE 6 in the prompt.
            d = _strip_stacked_contextual_closing(d)
            d = _track(
                d,
                _fallback_for_greeting_closing_stub(
                    d, subject, body, greeting_hint, closing_hint,
                    detected_language, formality,
                ),
                "stub_fallback",
            )

            _pipeline_ms = int((time.monotonic() - _pipeline_start) * 1000)
            if _pipeline_ms > 50:
                logger.warning(
                    f"SmartRouter STANDARD: post-LLM pipeline took {_pipeline_ms}ms "
                    f"({corrections} corrections, body={len(body)}chars)"
                )
            else:
                logger.debug(f"SmartRouter STANDARD: post-LLM pipeline {_pipeline_ms}ms ({corrections} corrections)")

            capture_if_enabled(
                mode="standard",
                raw_draft=raw_draft,
                pipeline_input={
                    "body": body,
                    "subject": subject,
                    "sender": sender,
                    "sender_name": sender_name,
                    "effective_sender_name": effective_sender_name,
                    "greeting_hint": greeting_hint,
                    "detected_language": detected_language,
                    "formality": formality,
                    "conversation_history": conversation_history or [],
                },
                cleaned_draft=d,
                corrections=corrections,
                correction_details=list(correction_details),
                learned_corrections_applied=learned_applied,
                extra={"pipeline_ms": _pipeline_ms},
            )

            return d, corrections, correction_details

        # Axe 5: Multi-draft selection (optional, disabled by default)
        _correction_details: list[str] = []
        if _multi_draft_enabled_for(instructions):
            raw_a, _ = _llm_generate(max(temperature - 0.10, 0.15))
            raw_b, _ = _llm_generate(min(temperature + 0.10, 0.55))
            draft_a, corr_a, details_a = _apply_pipeline(raw_a)
            draft_b, corr_b, details_b = _apply_pipeline(raw_b)
            if corr_a <= corr_b:
                draft = draft_a
                _correction_details = details_a
                logger.info(f"SmartRouter MULTI-DRAFT: picked A ({corr_a} corrections vs {corr_b})")
            else:
                draft = draft_b
                _correction_details = details_b
                logger.info(f"SmartRouter MULTI-DRAFT: picked B ({corr_b} corrections vs {corr_a})")
        else:
            raw, out_tokens = _llm_generate(temperature)
            if out_tokens and out_tokens < max_tokens * 0.3:
                logger.debug(
                    f"SmartRouter: token budget waste — used {out_tokens}/{max_tokens} "
                    f"({out_tokens/max_tokens:.0%}), body={len(body)}chars"
                )
            draft, _, _correction_details = _apply_pipeline(raw)

        # Safety net: if draft is empty after pipeline (e.g. clarification stripped), retry once
        if not draft or not draft.strip():
            logger.warning("SmartRouter STANDARD: draft empty after pipeline, retrying with fallback prompt")
            try:
                raw_retry, _ = _llm_generate(min(temperature + 0.1, 0.6))
                draft_retry, _, _correction_details = _apply_pipeline(raw_retry)
                if draft_retry and draft_retry.strip():
                    draft = draft_retry
                    logger.info("SmartRouter STANDARD: retry succeeded")
                else:
                    draft = "Je vous recontacte rapidement."
                    logger.warning("SmartRouter STANDARD: retry also empty, using fallback")
            except Exception as e:
                logger.error(f"SmartRouter STANDARD: retry failed: {e}")
                draft = "Je vous recontacte rapidement."

        logger.info(f"SmartRouter STANDARD: Haiku draft generated ({len(draft)} chars, formality={formality}, temp={temperature})")
        return draft, _correction_details

    # =========================================================================
    # STREAMING: Progressive draft generation via WebSocket (Task #18)
    # =========================================================================

    def route_streaming(
        self,
        email_id: str,
        email_content: str,
        sender: str,
        subject: str,
        body: str,
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        user_email: str = "",
        thread_depth: int = 0,
        sender_name: str = "",
        thread_context: list[dict] | None = None,
        account_id: int = 1,
        force: bool = False,
        label: str = "Action",
        allow_faq_auto_send: bool = True,
    ) -> RoutingResult:
        """
        Route + generate draft with streaming via WebSocket.

        For STANDARD tier: streams chunks via draft_chunk events (~0.5s TTFB).
        For SIMPLE tier: returns template immediately (no streaming needed).
        For COMPLEX tier: delegates to unified pipeline (no streaming yet).

        Args:
            force: If True, skip the noreply/auto-reply pre-filter
                (manual /process call). Audit failure-mode #21
                (2026-04-24): the streaming path used to skip the
                pre-filter unconditionally, so triggering /process on a
                noreply email handed the full prompt to Haiku and burned
                tokens. Now mirrors `route()`.
            label: Pre-classified label (Action/Waiting/FYI/Noise) to
                feed `should_skip_prefilter`. Default `"Action"`
                preserves existing call sites.

        Returns:
            RoutingResult with completed draft.
        """
        self._account_id = account_id  # Used by internal methods (style profile, etc.)
        _route_t0 = time.perf_counter()
        body = strip_unknown_body_artifacts(body or "")
        # Content hash for cross-UID dedup (mirrors route()).
        self._content_hash = _compute_content_hash(subject, body)
        from app.config import ROUTING_SIMPLE_THRESHOLD, ROUTING_COMPLEX_THRESHOLD

        # Audit concurrency C1+C2 (2026-04-24): per-(account, email) lock.
        # Same approach as `route()` — RAII guard releases via __del__ when
        # the local goes out of scope, no matter which return path fires.
        _lock_t0 = time.perf_counter()
        _entry_lock = SmartRouter._EntryLockGuard(SmartRouter, account_id, email_id)
        _lock_ms = int((time.perf_counter() - _lock_t0) * 1000)
        if _lock_ms >= 500:
            logger.warning(
                "[PERF-DRAFT] phase=smart_router_lock email_id=%s account_id=%s ms=%s",
                email_id,
                account_id,
                _lock_ms,
            )

        # Post-lock cache re-check: if a peer SmartRouter call held the
        # lock and produced a draft while we waited, it's now cached.
        if _entry_lock.acquired and email_id and not (instructions and instructions.strip()) and not force:
            _peer_cached = _get_cached_draft(
                email_id,
                account_id=getattr(self, "_account_id", None),
                content_hash=self._content_hash,
            )
            if _peer_cached:
                logger.info(
                    f"SmartRouter streaming dedup (post-lock cache hit) for {email_id}"
                )
                self._emit_instant_draft(email_id, _peer_cached)
                return RoutingResult(
                    draft=_peer_cached,
                    decision=RoutingDecision(
                        tier=RoutingTier.SKIP,
                        complexity_score=0,
                        reason="post-lock cache hit",
                    ),
                    classification=label or "Action",
                    priority=50,
                    status="CACHE_HIT",
                )

        # Step 0: Pre-filter (audit failure-mode #21, 2026-04-24).
        # Mirrors `route()` L959-976. Skip on noreply / auto-reply senders
        # unless caller forces (manual `/process` button on a noise email).
        if not force:
            try:
                skip_reason = should_skip_prefilter(sender, user_email, subject, label)
            except Exception as _pf_err:
                logger.debug(f"prefilter (streaming) error: {_pf_err}")
                skip_reason = None
            if skip_reason:
                decision = RoutingDecision(
                    tier=RoutingTier.SKIP,
                    complexity_score=0,
                    reason=f"Pre-filter: {skip_reason}",
                    max_tokens=0,
                )
                logger.info(f"SmartRouter streaming SKIP: {skip_reason}")
                return RoutingResult(
                    draft="",
                    decision=decision,
                    classification=label or "Noise",
                    priority=0,
                    status="SKIPPED",
                )

        # Empty-body guard (audit failure-mode #5, 2026-04-24).
        # Image-only / attachment-only emails have effectively empty bodies.
        # Without this guard the LLM hallucinates from the subject alone.
        # Threshold matches the standard handling — body of < 10 non-whitespace
        # characters is too short to ground a reply.
        _stripped_body = (body or "").strip()
        if len(_stripped_body) < 10 and not (instructions and instructions.strip()):
            decision = RoutingDecision(
                tier=RoutingTier.SKIP,
                complexity_score=0,
                reason="empty_body",
                max_tokens=0,
            )
            logger.info(f"SmartRouter streaming SKIP: empty_body (email_id={email_id})")
            return RoutingResult(
                draft="",
                decision=decision,
                classification=label or "Action",
                priority=0,
                status="EMPTY_BODY",
            )

        # Dedup check
        cached = _get_cached_draft(email_id, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
        if cached:
            self._emit_instant_draft(email_id, cached)
            return RoutingResult(
                draft=cached,
                decision=RoutingDecision(tier=RoutingTier.SKIP, complexity_score=0, reason="cache hit"),
                classification="Action", priority=50, status="CACHE_HIT",
            )

        has_instructions = _has_meaningful_user_instructions(instructions)
        has_raw_instructions = bool(instructions and instructions.strip())

        # FAQ Agent (auto-reply) — disabled by default; gated by FAQ_AUTO_REPLY_ENABLED
        if not has_raw_instructions and FAQ_AUTO_REPLY_ENABLED:
            faq_hit = _try_faq_agent(
                email_id=email_id, subject=subject, body=body,
                sender=sender, sender_name=sender_name, user_email=user_email,
                allow_auto_send=allow_faq_auto_send,
            )
            if faq_hit:
                return faq_hit

        # Refund detection (audit failure-mode #22, 2026-04-24).
        # Refund detection délié du pipeline streaming (2026-04-30) — cf. note dans route().

        # Classify
        from app.api.websocket import emit_draft_stage
        emit_draft_stage(email_id, "classification", 0, 4, 0.0)

        signals = analyze_complexity(body=body, subject=subject, thread_depth=thread_depth, has_instructions=has_instructions)
        score = calculate_complexity_score(signals)

        if score < ROUTING_SIMPLE_THRESHOLD and not has_instructions:
            tier = RoutingTier.SIMPLE
        elif score >= ROUTING_COMPLEX_THRESHOLD:
            tier = RoutingTier.COMPLEX
        else:
            tier = RoutingTier.STANDARD

        if has_instructions and tier == RoutingTier.SIMPLE:
            tier = RoutingTier.STANDARD

        max_tokens = calculate_dynamic_max_tokens(signals, tier)
        decision = RoutingDecision(tier=tier, complexity_score=score, reason=f"streaming, score={score}", max_tokens=max_tokens, signals=signals)
        logger.info(
            "[PERF-DRAFT] phase=smart_router_classify email_id=%s account_id=%s "
            "tier=%s score=%s body_chars=%s has_history=%s has_instructions=%s ms=%s",
            email_id,
            account_id,
            tier.value,
            score,
            len(body or ""),
            bool(conversation_history),
            has_instructions,
            int((time.perf_counter() - _route_t0) * 1000),
        )

        # Compute greeting hint for V2 enforcement (V1 computes its own in _generate_standard_streaming)
        from app.prompts import analyze_email_formality, _extract_display_name, _detect_language, _compute_greeting_hint as _cgh
        _effective_sender = sender_name or _extract_display_name(sender)
        _formality = analyze_email_formality(f"{subject}\n{body}")
        _lang = _detect_language(f"{subject}\n{body}", fallback_language=self._primary_language_fallback())
        greeting_hint = _cgh(
            _effective_sender,
            _email_reply_greeting_formality(_formality, instructions),
            _lang,
            sender_email=sender,
            signature_text=body,
        )
        closing_hint = self._closing_hint_for(_formality, _lang)

        # Specialty detection (Expert Mode, $0 keyword classification)
        # Only for COMPLEX emails — avoids token starvation on STANDARD (512 max)
        _specialty_match_stream = None
        _specialty_ctx_stream = ""
        if tier == RoutingTier.COMPLEX:
            try:
                from app.specialty_engine import get_specialty_engine
                engine = get_specialty_engine()
                _active_specs = engine.get_active_specialties(account_id=getattr(self, "_account_id", None))
                if _active_specs:
                    _specialty_match_stream = engine.classify_email(subject, body, _active_specs)
                    if _specialty_match_stream and _specialty_match_stream.risk_level == "high":
                        return RoutingResult(
                            draft="",
                            decision=decision,
                            classification="Action",
                            priority=90,
                            status="SPECIALTY_HIGH_RISK",
                            critique_info={"specialty": _specialty_match_stream.to_dict()},
                        )
                    if _specialty_match_stream:
                        _specialty_ctx_stream = engine.build_specialty_context(_specialty_match_stream)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
        else:
            logger.debug(f"SmartRouter streaming: specialty skipped (tier={tier.value}, score={score})")

        # Specialty pre-classification (subscription / account) délié du pipeline streaming
        # (2026-04-30). Cf. note dans route() pour réintégrer.

        # SIMPLE: instant template
        if tier == RoutingTier.SIMPLE:
            draft = self._generate_simple(sender, subject, body)
            if draft:
                # Same defensive cleanup as route() to keep SIMPLE/STREAMING
                # paths in parity — strip placeholders + enforce closing.
                draft = _finalize_simple_draft(draft, closing_hint)
                _cache_draft(email_id, draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
                self._emit_instant_draft(email_id, draft)
                return RoutingResult(draft=draft, decision=decision, classification="Action", priority=50, status="SIMPLE_TEMPLATE")
            tier = RoutingTier.STANDARD
            decision.tier = tier

        # Batch check — route_streaming is used by both user-visible and
        # background paths. `force=True` is set by user-triggered /process, so
        # this only queues non-interactive off-hours work.
        if should_use_batch(tier, force) and email_id:
            batch_instructions = instructions
            if tier == RoutingTier.COMPLEX:
                complex_hint = (
                    "COMPLEX EMAIL — Be thorough. "
                    "Address EACH question or topic individually. "
                    "Use 3-6 sentences. Structure your reply clearly."
                )
                batch_instructions = (
                    f"{instructions}\n{complex_hint}" if instructions
                    else complex_hint
                )
            system_prompt, user_prompt = self._build_prompts(
                sender=sender, subject=subject, body=body,
                conversation_history=conversation_history,
                instructions=batch_instructions,
                sender_name=sender_name,
                thread_context=thread_context,
                specialty_context=_specialty_ctx_stream,
            )
            from app.prompts import _segments_to_text, formality_to_temperature
            batch_system_prompt = _segments_to_text(system_prompt)
            batch_temperature = formality_to_temperature(_formality)
            item_id = enqueue_for_batch(
                email_id=email_id, tier=tier,
                sender=sender, subject=subject, body=body,
                system_prompt=batch_system_prompt, user_prompt=user_prompt,
                max_tokens=max_tokens, temperature=batch_temperature,
                account_id=account_id,
            )
            logger.info(
                f"SmartRouter STREAMING BATCH: queued {email_id} ({tier.value}, "
                f"max_tokens={max_tokens}) -> {item_id[:8]}"
            )
            emit_draft_stage(email_id, "batch_queued", 4, 4, 100.0)
            return RoutingResult(
                draft="",
                decision=decision,
                classification="Action",
                priority=50,
                status="BATCH_QUEUED",
            )

        # STANDARD: stream via Haiku, then critique
        if tier == RoutingTier.STANDARD:
            _stream_instructions = instructions

            _standard_t0 = time.perf_counter()
            draft = self._generate_standard_streaming(
                email_id=email_id,
                email_content=email_content,
                sender=sender, subject=subject, body=body,
                conversation_history=conversation_history,
                instructions=_stream_instructions,
                max_tokens=max_tokens,
                sender_name=sender_name,
                thread_context=thread_context,
                specialty_context=_specialty_ctx_stream,
            )
            logger.info(
                "[PERF-DRAFT] phase=standard_streaming email_id=%s account_id=%s "
                "draft_chars=%s ms=%s",
                email_id,
                account_id,
                len(draft or ""),
                int((time.perf_counter() - _standard_t0) * 1000),
            )
            # Critique + revise (V2 silently replaces V1 if rejected)
            _critic_t0 = time.perf_counter()
            final_draft, critique_info = self._validate_and_revise(
                draft=draft,
                email_content=email_content,
                email_id=email_id,
                conversation_history=conversation_history,
                instructions=_stream_instructions,
                user_email=user_email,
                max_tokens=max_tokens,
                sender_name=sender_name,
                greeting_hint=greeting_hint,
                closing_hint=closing_hint,
                specialty_context=_specialty_ctx_stream,
                tier=tier,
                body_length=len(body or ""),
                account_id=account_id,
                complexity_score=decision.complexity_score,
            )
            logger.info(
                "[PERF-DRAFT] phase=validate_revise email_id=%s account_id=%s "
                "was_revised=%s ms=%s",
                email_id,
                account_id,
                bool(critique_info.get("was_revised", False)),
                int((time.perf_counter() - _critic_t0) * 1000),
            )
            final_draft = strip_reasoning_leakage(final_draft)
            final_draft = _strip_a_confirmer(final_draft)
            was_revised = critique_info.get("was_revised", False)
            # Emit final draft after critique. Two paths:
            # - Legacy (default): `_emit_instant_draft` silently swaps V1→V2.
            #   Risk: user editing V1 during the ~1.5s critic window loses
            #   their edits when V2 lands.
            # - Non-destructive (STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE flag):
            #   when V2 actually differs from V1, emit `draft_revised` with
            #   BOTH versions + critique summary so the frontend can render
            #   a toggle instead of mutating the editor in place.
            # The non-destructive flag is OFF by default (frontend toggle UI
            # ships next sprint). Until then, the new event is dormant.
            try:
                from app.config import STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE as _NONDESTR
            except Exception:
                _NONDESTR = False

            if was_revised and _NONDESTR and final_draft != draft:
                # Non-destructive path. Always emit `draft_complete(V1)` first
                # so the frontend gets the standard "draft ready" signal
                # (sound, list refresh, isComplete=true). THEN emit
                # `draft_revised(V1, V2)` which the frontend uses to render
                # a "View improved version" toggle WITHOUT mutating the
                # editor — preserves any edits the user made during the
                # critic window.
                self._emit_instant_draft(email_id, draft)  # V1, what user already sees
                try:
                    from app.api.websocket import emit_draft_revised
                    _summary = ""
                    _suggestions = critique_info.get("suggestions") or []
                    if isinstance(_suggestions, list) and _suggestions:
                        _summary = ", ".join(str(s) for s in _suggestions[:2])
                    emit_draft_revised(
                        email_id=email_id,
                        v1_draft=draft,
                        v2_draft=final_draft,
                        critique_summary=_summary,
                        account_id=getattr(self, "_account_id", None),
                    )
                except Exception as _rev_err:  # pragma: no cover — defensive
                    # Already emitted V1 above — if the revised event fails
                    # to fire, the user is left with V1 displayed (no harm,
                    # no V2 toggle, but the editor still works).
                    logger.warning(
                        f"emit_draft_revised failed; user keeps V1: {_rev_err}"
                    )
            else:
                # Legacy / non-revised path — emit final (V1 if accepted,
                # or V2 if revised but the flag is off).
                self._emit_instant_draft(email_id, final_draft)

            _cache_draft(email_id, final_draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))

            # Inject specialty match into critique_info
            if _specialty_match_stream:
                critique_info["specialty"] = _specialty_match_stream.to_dict()

            # Smart suggestions are useful chips, not required to display the
            # draft. Keep them out of the streaming critical path; the REST
            # /process caller populates them asynchronously after the draft is
            # saved and emitted.
            critique_info["smart_suggestions_deferred"] = True
            logger.info(
                "[PERF-DRAFT] phase=smart_suggestions email_id=%s account_id=%s "
                "deferred=True ms=0",
                email_id,
                account_id,
            )

            _s_status = "STANDARD_STREAMING_V2" if was_revised else "STANDARD_STREAMING"
            logger.info(
                "[PERF-DRAFT] phase=smart_router_total email_id=%s account_id=%s "
                "status=%s tier=%s ms=%s",
                email_id,
                account_id,
                _s_status,
                tier.value,
                int((time.perf_counter() - _route_t0) * 1000),
            )
            return RoutingResult(
                draft=final_draft, decision=decision,
                classification="Action", priority=50,
                status=_s_status,
                critique_info=critique_info,
                draft_v1=draft if was_revised else None,
                # DP-23 fix (audit row #23): plumb correction_details from the
                # streaming pipeline. Previously route_streaming set this to
                # default (None), so REST `/process` always saw
                # `PendingDraft.correction_details = None` and the pipeline
                # transparency card showed empty.
                correction_details=getattr(self, "_last_streaming_correction_details", None),
            )

        # COMPLEX: non-streaming fallback; the critic can be skipped for
        # borderline user-notes drafts by _validate_and_revise.
        emit_draft_stage(email_id, "redaction", 1, 4, 5.0)
        _complex_stream_instructions = instructions or ""
        result = self._generate_complex(
            email_content=email_content,
            conversation_history=conversation_history,
            instructions=_complex_stream_instructions,
            user_email=user_email,
            decision=decision,
            thread_context=thread_context,
        )
        if result.draft:
            emit_draft_stage(email_id, "optimisation", 2, 4, 90.0)
            final_draft, critique_info = self._validate_and_revise(
                draft=result.draft,
                email_content=email_content,
                email_id=email_id,
                conversation_history=conversation_history,
                instructions=instructions,
                user_email=user_email,
                max_tokens=decision.max_tokens or 768,
                sender_name=sender_name,
                greeting_hint=greeting_hint,
                closing_hint=closing_hint,
                specialty_context=_specialty_ctx_stream,
                tier=tier,
                body_length=len(body or ""),
                account_id=account_id,
                complexity_score=decision.complexity_score,
            )
            was_revised = critique_info.get("was_revised", False)
            emit_draft_stage(email_id, "finalisation", 3, 4, 95.0)
            self._emit_instant_draft(email_id, final_draft)
            if email_id:
                _cache_draft(email_id, final_draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
            if was_revised:
                result.draft_v1 = result.draft  # Preserve original V1
            result.draft = final_draft
            result.critique_info = critique_info
            if was_revised:
                result.status = "COMPLEX_V2"
        return result

    def _generate_standard_streaming(
        self,
        email_id: str,
        email_content: str,
        sender: str,
        subject: str,
        body: str,
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        max_tokens: int = 512,
        sender_name: str = "",
        thread_context: list[dict] | None = None,
        specialty_context: str = "",
    ) -> str:
        """Generate draft via Haiku streaming, emitting WebSocket chunks."""
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        from app.prompts import (
            get_standard_draft_prompts, analyze_email_formality,
            formality_to_temperature, _compute_greeting_hint, _detect_language,
            load_account_knowledge,
        )
        from app.api.websocket import emit_draft_chunk, emit_draft_complete

        container = get_container()
        _standard_total_t0 = time.perf_counter()

        # Style profile (uncached JSON disk read) and KB (DB, 10-min memo)
        # are independent inputs. Load them concurrently on the shared prompt
        # pool instead of serially so the style read overlaps a cold KB read,
        # trimming a few ms off TTFT. Mirrors the proven pattern in
        # _build_prompts. Each loader returns its own duration so the
        # [PERF-DRAFT] log keeps style_ms/kb_ms. (reply-latency quick win,
        # 2026-06-23.)
        def _load_style_ctx() -> "tuple[str, int]":
            _t0 = time.perf_counter()
            ctx = ""
            try:
                profile = container.get_writing_style_profile(account_id=getattr(self, "_account_id", 1))
                if profile:
                    from app.prompts.style_guidance import build_style_guidance_from_profile
                    ctx = build_style_guidance_from_profile(
                        profile, language="fr", recipient_email=sender
                    )
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            return ctx, int((time.perf_counter() - _t0) * 1000)

        def _load_kb_ctx() -> "tuple[str, int]":
            # P0.1 (2026-05-14): prefer per-account onboarding KB over the
            # deprecated global memoire.md — same rationale as _build_prompts.
            _t0 = time.perf_counter()
            kb = ""
            try:
                kb = load_account_knowledge(getattr(self, "_account_id", None))
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            return kb, int((time.perf_counter() - _t0) * 1000)

        _f_style = _prompt_loader_pool.submit(_load_style_ctx)
        _f_kb = _prompt_loader_pool.submit(_load_kb_ctx)
        style_context, _style_ms = _f_style.result()
        knowledge_base, _kb_ms = _f_kb.result()

        # Specialty context passed by caller (only for non-SIMPLE tiers)

        _prompt_t0 = time.perf_counter()
        system_prompt, user_prompt = get_standard_draft_prompts(
            sender=sender, subject=subject, body=body,
            style_context=style_context,
            conversation_history=conversation_history,
            instructions=instructions,
            contact=sender,
            sender_name=sender_name,
            knowledge_base=knowledge_base,
            thread_context=thread_context,
            specialty_context=specialty_context,
            account_id=getattr(self, "_account_id", None),
        )
        _prompt_ms = int((time.perf_counter() - _prompt_t0) * 1000)

        # Pre-compute greeting hint for post-LLM enforcement
        _language_t0 = time.perf_counter()
        formality = analyze_email_formality(f"{subject}\n{body}")
        temperature = formality_to_temperature(formality)
        detected_language = _detect_language(f"{subject} {body}", fallback_language=self._primary_language_fallback())

        # Check if user explicitly requests a translation to a different language
        from app.prompts import _detect_language_override
        language_override = _detect_language_override(instructions) if instructions else None
        if language_override:
            detected_language = language_override

        greeting_hint = _compute_greeting_hint(
            sender_name or "",
            _email_reply_greeting_formality(formality, instructions),
            detected_language,
            sender_email=sender,
            signature_text=body,
        )
        closing_hint = self._closing_hint_for(formality, detected_language)
        _language_ms = int((time.perf_counter() - _language_t0) * 1000)
        logger.info(
            "[PERF-DRAFT] phase=standard_prompt_prep email_id=%s account_id=%s "
            "style_ms=%s kb_ms=%s prompt_ms=%s language_ms=%s prep_ms=%s "
            "body_chars=%s prompt_chars=%s",
            email_id,
            getattr(self, "_account_id", None),
            _style_ms,
            _kb_ms,
            _prompt_ms,
            _language_ms,
            int((time.perf_counter() - _standard_total_t0) * 1000),
            len(body or ""),
            len(system_prompt or "") + len(user_prompt or ""),
        )

        llm = container.llm_drafting
        from app.config import SONNET_ROUTING_ENABLED
        if SONNET_ROUTING_ENABLED and _is_tone_sensitive(body, subject, instructions):
            llm = container.llm_drafting_smart
            logger.info("SmartRouter STREAMING: upgrading to Sonnet (tone-sensitive email)")

        accumulated = ""
        chunk_index = 0
        start_ms = int(time.time() * 1000)

        from app.api.websocket import emit_draft_stage
        emit_draft_stage(email_id, "redaction", 1, 4, 5.0)

        try:
            with llm_attribution(
                "smart_router_stream",
                account_id=getattr(self, "_account_id", None),
                feature="drafting",
            ):
                for chunk in llm.stream(
                    system=system_prompt,
                    user=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    if chunk.text:
                        accumulated += chunk.text
                        chunk_index += 1
                        progress = min(95.0, (chunk_index / max(max_tokens // 4, 1)) * 100)
                        emit_draft_chunk(
                            account_id=getattr(self, "_account_id", None),  # FIX WS-003 (audit P1)
                            email_id=email_id,
                            chunk=chunk.text,
                            chunk_index=chunk_index,
                            accumulated_text=accumulated,
                            progress_percent=progress,
                            is_final=chunk.is_final,
                        )

                    if chunk.is_final:
                        break

            elapsed_ms = int(time.time() * 1000) - start_ms
            draft = accumulated.strip()
            _cleanup_t0 = time.perf_counter()

            emit_draft_stage(email_id, "optimisation", 2, 4, 90.0)

            # DP-23 fix (audit row #23, 2026-04-24): track which post-LLM
            # cleanup steps fired so REST `/process` can render the pipeline
            # transparency card. Previously the streaming path passed `[]`
            # to capture_if_enabled at L3098 and never reported the labels.
            _streaming_corrections: list[str] = []

            def _track_s(before: str, after: str, label: str) -> str:
                if before != after:
                    _streaming_corrections.append(label)
                return after

            # Post-LLM cleanup pipeline (same order as _generate_standard)
            draft = _track_s(draft, _clean_prompt_leakage(draft), "prompt_leakage")
            draft = _track_s(draft, strip_unknown_body_artifacts(draft), "unknown_body_artifact")
            # Reasoning leakage runs BEFORE markdown stripping — see Bug C
            # comment in _generate_standard.
            draft = _track_s(draft, strip_reasoning_leakage(draft), "reasoning_leakage")  # audit Q7 + stress 2026-05-13
            draft = _track_s(draft, _strip_markdown_artifacts(draft), "markdown_cleanup")  # P14
            draft = _track_s(draft, _strip_clarification_draft(draft), "clarification_removed")
            draft = _track_s(draft, _strip_filler_mid_draft(draft, formality), "filler_removed")  # #10: tone-aware
            draft = _track_s(draft, _strip_signature(draft), "signature_cleaned")
            draft = _track_s(draft, _truncate_for_short_body(draft, body, user_context=instructions or ""), "truncated_short")
            draft = _track_s(draft, _strip_subject_echo(draft, subject), "subject_echo")  # #4
            draft = _track_s(draft, _strip_technical_echo(draft, body), "technical_echo")
            if len(body) >= 300:
                draft = _track_s(draft, _strip_parroting(draft, body), "parroting")
            else:
                draft = _track_s(draft, _strip_leading_parrot(draft, body), "parroting")
            draft = _track_s(draft, _scrub_hallucinated_facts(draft, body), "hallucinated_facts")
            draft = _track_s(draft, _scrub_invented_contacts(draft, body), "invented_contacts")  # P8
            draft = _track_s(draft, _scrub_ungrounded_nouns(draft, body, subject=subject, sender=sender, user_context=instructions or ""), "ungrounded_nouns")  # L3
            draft = _track_s(draft, _scrub_novel_situation(draft, body, subject=subject, user_context=instructions or ""), "novel_situation")  # L3b
            has_history = bool(conversation_history)
            draft = _track_s(draft, _scrub_hallucinated_context(draft, body, has_history=has_history), "hallucinated_context")
            draft = _track_s(draft, _scrub_process_language(draft), "process_language")
            draft = _track_s(draft, _strip_hedging(draft), "hedging")  # #1
            draft = _track_s(draft, _strip_a_confirmer(draft), "placeholder_removed")  # #1b
            draft = _track_s(draft, _strip_sycophancy(draft), "sycophancy")  # P9
            draft = _track_s(draft, _strip_unnecessary_questions(draft, body), "unnecessary_questions")  # #9
            draft = _track_s(draft, _strip_excessive_apologies(draft), "excessive_apologies")  # P3
            draft = _track_s(draft, _strip_redundant_affirmations(draft), "redundant_affirmations")  # P4
            draft = _track_s(draft, _simplify_contrast_patterns(draft), "contrast_simplified")  # P7
            draft = _track_s(draft, _strip_slop_words(draft), "slop_words")  # P6
            draft = _track_s(draft, strip_ai_dashes(draft), "ai_dashes")
            draft = _track_s(draft, _strip_recap_sentences(draft), "recap_removed")  # P12
            draft = _track_s(draft, _fix_repetitive_openings(draft), "repetitive_openings")  # P2
            draft = _track_s(draft, _strip_duplicate_greetings(draft), "duplicate_greetings")

            # Apply learned correction patterns post-LLM
            streaming_learned_applied: list = []
            try:
                from app.draft_correction import get_correction_manager
                corrected, applied = get_correction_manager().apply_learned_corrections(
                    draft, context={"sender": sender, "subject": subject}
                )
                if applied:
                    draft = corrected
                    streaming_learned_applied = list(applied)
                    _streaming_corrections.append("learned_corrections")
                    logger.info(f"SmartRouter STREAMING: {len(applied)} learned correction(s) applied")
                    # #13: Re-validate after corrections
                    draft = _strip_filler_mid_draft(draft, formality)
                    draft = _scrub_hallucinated_facts(draft, body)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            # Safety overrides
            draft = _detect_misdirected(draft, body, sender_name or sender)
            draft = _detect_social_engineering(draft, body)
            draft = _detect_blackmail(draft, body)
            draft = _ensure_legal_caution(draft, body)
            draft = _clean_language_artifacts(draft)
            draft = _detect_language_drift(draft, detected_language)  # #6
            draft = _fix_pronoun_consistency(draft, formality)  # P1
            draft = _fix_closing_tone(draft, formality)  # P5
            draft = _fix_name_overuse(draft, sender_name or "")  # P13

            # Greeting + closing enforcement LAST
            draft = _enforce_greeting(draft, greeting_hint)
            draft = _enforce_closing(draft, closing_hint)
            # Issue #592: collapse stacked contextual + canonical closings.
            draft = _strip_stacked_contextual_closing(draft)
            draft = _track_s(
                draft,
                _fallback_for_greeting_closing_stub(
                    draft, subject, body, greeting_hint, closing_hint,
                    detected_language, formality,
                ),
                "stub_fallback",
            )

            capture_if_enabled(
                mode="streaming",
                raw_draft=accumulated.strip(),
                pipeline_input={
                    "body": body,
                    "subject": subject,
                    "sender": sender,
                    "sender_name": sender_name,
                    "greeting_hint": greeting_hint,
                    "detected_language": detected_language,
                    "formality": formality,
                    "conversation_history": conversation_history or [],
                },
                cleaned_draft=draft,
                corrections=len(_streaming_corrections),
                correction_details=list(_streaming_corrections),
                learned_corrections_applied=streaming_learned_applied,
                extra={"email_id": email_id, "elapsed_ms": elapsed_ms},
            )
            logger.info(
                "[PERF-DRAFT] phase=standard_cleanup email_id=%s account_id=%s "
                "corrections=%s draft_chars=%s ms=%s",
                email_id,
                getattr(self, "_account_id", None),
                len(_streaming_corrections),
                len(draft or ""),
                int((time.perf_counter() - _cleanup_t0) * 1000),
            )

            # DP-23 fix: stash correction_details so route_streaming() can
            # propagate them to RoutingResult / PendingDraft (audit row #23).
            try:
                self._last_streaming_correction_details = list(_streaming_corrections)
            except Exception:
                pass

            emit_draft_stage(email_id, "finalisation", 3, 4, 95.0)

            # FIX WS-003 (audit P1): pass account_id so the bg-thread emit
            # is routed via emit_to_account instead of falling back to
            # _resolve_ws_room (which always returns None outside a
            # request context, silently dropping the event).
            emit_draft_complete(
                email_id=email_id,
                draft_content=draft,
                confidence=0.80,
                generation_time_ms=elapsed_ms,
                tokens_used=chunk_index,
                account_id=getattr(self, "_account_id", None),
            )

            logger.info(f"SmartRouter STREAMING: {len(draft)} chars in {elapsed_ms}ms ({chunk_index} chunks)")
            return draft

        except Exception as e:
            from app.api.websocket import emit_draft_error
            from app.domain.exceptions import LLMBillingError, LLMAuthenticationError

            # Audit R-001 (2026-04-27): pass account_id (set on the router)
            # so BG-thread errors reach the user instead of being dropped.
            _aid = getattr(self, "_account_id", None)

            # Erreurs permanentes : ne pas fallback, signaler clairement
            if isinstance(e, LLMBillingError):
                emit_draft_error(email_id=email_id, error="Crédits IA épuisés. Veuillez vérifier votre abonnement.", retry_count=-1, account_id=_aid)
                logger.error(f"SmartRouter: crédits épuisés — {e}")
                raise
            if isinstance(e, LLMAuthenticationError):
                emit_draft_error(email_id=email_id, error="Clé API IA invalide. Veuillez vérifier la configuration.", retry_count=-1, account_id=_aid)
                logger.error(f"SmartRouter: auth error — {e}")
                raise

            emit_draft_error(email_id=email_id, error=str(e), account_id=_aid)
            logger.error(f"SmartRouter streaming error: {e}", exc_info=True)
            # Fallback to non-streaming
            draft_fb, corr_fb = self._generate_standard(
                email_content=email_content, sender=sender, subject=subject,
                body=body, conversation_history=conversation_history,
                instructions=instructions, max_tokens=max_tokens,
            )
            return RoutingResult(
                draft=draft_fb, decision=RoutingDecision(tier=RoutingTier.STANDARD, complexity_score=0, reason="streaming fallback"),
                classification="Action", priority=50, status="STREAMING_FALLBACK", correction_details=corr_fb,
            )

    def _emit_instant_draft(self, email_id: str, draft: str) -> None:
        """Emit a pre-generated draft instantly as a single chunk + complete."""
        try:
            from app.api.websocket import emit_draft_chunk, emit_draft_complete
            # FIX WS-003 (audit P1): scope to this account explicitly —
            # bg-thread context has no Flask request and would otherwise
            # silently drop the event.
            _aid = getattr(self, "_account_id", None)
            emit_draft_chunk(
                email_id=email_id, chunk=draft, chunk_index=0,
                accumulated_text=draft, progress_percent=100.0, is_final=True,
                account_id=_aid,
            )
            emit_draft_complete(
                email_id=email_id, draft_content=draft,
                confidence=0.85, generation_time_ms=0, tokens_used=0,
                account_id=_aid,
            )
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

    # =========================================================================
    # COMPLEX: Haiku with higher token budget (cost-optimized)
    # =========================================================================

    def _generate_complex(
        self,
        email_content: str,
        conversation_history: list[dict] | None = None,
        instructions: str = "",
        user_email: str = "",
        decision: RoutingDecision | None = None,
        thread_context: list[dict] | None = None,
    ) -> RoutingResult:
        """
        Generate COMPLEX drafts using Haiku (same as STANDARD) with higher
        max_tokens. Cost: ~$0.003 vs $0.018 with Sonnet (-83%).

        The post-LLM cleanup pipeline handles quality enforcement.
        """
        if decision is None:
            decision = RoutingDecision(
                tier=RoutingTier.COMPLEX,
                complexity_score=70,
                reason="complex fallback",
            )

        # Parse sender/subject/body from email_content
        sender, subject, body = _parse_email_content(email_content)

        max_tokens = decision.max_tokens or 768

        # For simple data-recall questions, reduce max_tokens to prevent filler
        if "?" in body and len(body) < 100 and conversation_history:
            max_tokens = min(max_tokens, 128)

        # Enrich instructions for complex emails: guide Haiku to be thorough
        complex_hint = (
            "COMPLEX EMAIL — Answer EVERY question with concrete data. "
            "Address EACH question or topic individually. "
            "Give answers, not promises to check."
        )
        if instructions:
            enriched = f"{instructions}\n{complex_hint}"
        else:
            enriched = complex_hint

        # Self-consistency: generate 2 samples in parallel at different
        # temperatures and keep the cleaner one. Skipped when the user
        # provided explicit `instructions` — those callers expect a
        # deterministic single-shot draft, not best-of-2.
        # P1.4 (2026-05-14): also gated by complexity score — the
        # 50-69 slice ("COMPLEX-ish") rarely benefits from best-of-2
        # over the post-LLM cleanup pipeline, but pays full 2x cost.
        # Threshold kept module-local (see _SELF_CONSISTENCY_COMPLEX_THRESHOLD
        # near the top of this file) rather than in app/config.py per
        # audit-day convention.
        #
        # F-04 (audit 2026-05-14): if `decision` is None (classifier 5xx /
        # env-disabled / fallback path), the previous `else 0` evaluated
        # the gate against 0, silently SKIPPING best-of-2 on COMPLEX-tier
        # emails — a regression vs pre-P1.4 behaviour, which ran self-
        # consistency unconditionally on COMPLEX (modulo `not instructions`).
        # Reaching `_generate_complex` already proves the upstream tier
        # decision was COMPLEX, so a missing `decision` should default
        # to the highest-complexity score (passes the threshold), not 0.
        from app.config import SELF_CONSISTENCY_COMPLEX_ENABLED
        _cscore = decision.complexity_score if decision else 100
        if (
            SELF_CONSISTENCY_COMPLEX_ENABLED
            and not instructions
            and _cscore >= _SELF_CONSISTENCY_COMPLEX_THRESHOLD
        ):
            from concurrent.futures import ThreadPoolExecutor, wait as _fut_wait
            kwargs = dict(
                email_content=email_content,
                sender=sender,
                subject=subject,
                body=body,
                conversation_history=conversation_history,
                instructions=enriched,
                max_tokens=max_tokens,
                sender_name="",
                thread_context=thread_context,
            )
            # F-06 (audit 2026-05-14): SHARED wall-clock budget instead of
            # sequential per-future timeouts. Pre-fix: fut_a.result(timeout=60)
            # could block 60s, then fut_b.result(timeout=60) blocked ANOTHER
            # 60s — worst case 120s for an empty draft. Now: one wait() with
            # a single budget; cancel the laggard; do NOT block on shutdown.
            # Local pool — 2 workers, lifecycle bounded by this method.
            # Avoids contending with the daemon's _CLASSIFY_EXECUTOR.
            ex = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agentys-complex-sc")
            _sc_start = time.monotonic()
            try:
                fut_a = ex.submit(self._generate_standard, **kwargs, temperature_override=0.4)
                fut_b = ex.submit(self._generate_standard, **kwargs, temperature_override=0.7)
                done, not_done = _fut_wait(
                    (fut_a, fut_b),
                    timeout=_COMPLEX_SC_WALL_CLOCK_BUDGET_SEC,
                )
                # Best-effort cancel for futures that didn't make the budget.
                # `cancel()` only succeeds on futures still in the pool's
                # work queue (not on those already running) — that's fine,
                # we just need to not_block_on them at shutdown.
                for fut in not_done:
                    fut.cancel()
                    logger.warning(
                        "SmartRouter COMPLEX self-consistency: future timed out "
                        "after %.1fs wall-clock budget (cancelled)",
                        _COMPLEX_SC_WALL_CLOCK_BUDGET_SEC,
                    )

                def _safe_get(fut):
                    """Pull result for a completed future, or return empty
                    tuple. timeout=0 because we know `done` are already
                    finished."""
                    if fut not in done:
                        return ("", [])
                    try:
                        return fut.result(timeout=0)
                    except Exception as exc:
                        logger.warning(
                            "SmartRouter COMPLEX self-consistency: future raised: %s",
                            exc,
                        )
                        return ("", [])

                res_a = _safe_get(fut_a)
                res_b = _safe_get(fut_b)
            finally:
                # `wait=False` + `cancel_futures=True` so the with-block
                # exit doesn't re-introduce a hidden 60s block waiting on
                # the laggards. The running futures will self-terminate
                # once the adapter's 60s timeout (claude_adapter.py:247)
                # fires; we just don't block on them.
                ex.shutdown(wait=False, cancel_futures=True)
            _sc_elapsed = time.monotonic() - _sc_start
            logger.info(
                "SmartRouter COMPLEX SC: wall-clock=%.1fs, completed=%d/2, "
                "budget=%.0fs",
                _sc_elapsed, len(done), _COMPLEX_SC_WALL_CLOCK_BUDGET_SEC,
            )
            draft_a, corr_a = res_a if isinstance(res_a, tuple) else (res_a, [])
            draft_b, corr_b = res_b if isinstance(res_b, tuple) else (res_b, [])
            draft, pick_reason = _pick_best_complex_draft(draft_a, draft_b)
            # Use the pick reason prefix instead of `is` identity — strings can
            # be interned (Python intern pool for short literals, "" in particular)
            # which would make `draft is draft_a` flaky when both samples are
            # empty. The picker tags every return with "a_*" or "b_*".
            _complex_corr = corr_a if pick_reason.startswith("a_") else corr_b
            logger.info(
                f"SmartRouter COMPLEX self-consistency: pick={pick_reason} "
                f"(a={len(draft_a)} chars, b={len(draft_b)} chars, winner={len(draft)} chars)"
            )
        else:
            draft, _complex_corr = self._generate_standard(
                email_content=email_content,
                sender=sender,
                subject=subject,
                body=body,
                conversation_history=conversation_history,
                instructions=enriched,
                max_tokens=max_tokens,
                sender_name="",
                thread_context=thread_context,
            )

        logger.info(f"SmartRouter COMPLEX: Haiku draft ({len(draft)} chars, max_tokens={max_tokens})")
        return RoutingResult(
            draft=draft,
            decision=decision,
            correction_details=_complex_corr,
            classification="Action",
            priority=50,
            status="COMPLEX_HAIKU",
        )


    # =========================================================================
    # COMBINED: Label + Draft in one Haiku call (Task #17)
    # =========================================================================

    def classify_and_draft(
        self,
        sender: str,
        subject: str,
        body: str,
        email_id: str = "",
        user_email: str = "",
        sender_name: str = "",
        conversation_history: list[dict] | None = None,
        raw_metadata: dict = None,
        allow_faq_auto_send: bool = True,
    ) -> RoutingResult:
        """
        Combined Label + Draft in one Haiku call for STANDARD-eligible emails.

        During auto-labeling, if the email is STANDARD-eligible, this method
        classifies AND drafts in a single LLM call, saving 1 API call.

        For COMPLEX emails (score >= 70), returns classification only with
        empty draft — caller should use separate COMPLEX pipeline.

        Returns:
            RoutingResult with classification, draft (may be empty), and decision.
        """
        from app.config import ROUTING_COMPLEX_THRESHOLD

        body = strip_unknown_body_artifacts(body or "")

        # Content hash for cross-UID cache dedup (mirrors route()).
        self._content_hash = _compute_content_hash(subject, body)

        # Pre-filter
        skip_reason = should_skip_prefilter(sender, user_email, subject)
        if skip_reason:
            decision = RoutingDecision(
                tier=RoutingTier.SKIP, complexity_score=0,
                reason=f"Pre-filter: {skip_reason}", max_tokens=0,
            )
            return RoutingResult(
                draft="", decision=decision,
                classification="Noise", priority=0, status="SKIPPED",
            )

        # FAQ Agent (auto-reply) — disabled by default; gated by FAQ_AUTO_REPLY_ENABLED
        if FAQ_AUTO_REPLY_ENABLED:
            faq_hit = _try_faq_agent(
                email_id=email_id, subject=subject, body=body,
                sender=sender, sender_name=sender_name, user_email=user_email,
                allow_auto_send=allow_faq_auto_send,
            )
            if faq_hit:
                return faq_hit

        # AccountAgent pre-routing délié du pipeline classify_and_draft (2026-04-30) —
        # cf. note dans route() pour réintégrer.

        # Dedup check
        if email_id:
            cached = _get_cached_draft(email_id, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))
            if cached:
                return RoutingResult(
                    draft=cached,
                    decision=RoutingDecision(tier=RoutingTier.SKIP, complexity_score=0, reason="cache hit"),
                    classification="Action", priority=50, status="CACHE_HIT",
                )

        # Pre-LLM rule-based classification (instant, $0)
        # If rules confidently say Noise or FYI, skip the LLM call entirely.
        try:
            from app.application.label_email import LabelEmailUseCase
            from app.domain.entities.email import Email as DomainEmail

            _rule_email = DomainEmail(
                id=email_id or "tmp",
                sender=sender,
                subject=subject,
                body=body,
            )
            from app.infrastructure.container import get_container as _get_ctn
            _label_store = _get_ctn().get_label_store(account_id=getattr(self, "_account_id", None))
            _rule_assignment = LabelEmailUseCase.classify_by_rules_only(
                _rule_email, _label_store, user_email=user_email,
                raw_metadata=raw_metadata,
            )
            if _rule_assignment:
                if _rule_assignment.matched_rule_ids:
                    _label_store.increment_rule_match_counts(_rule_assignment.matched_rule_ids)
            if _rule_assignment and _rule_assignment.default_label in ("Noise", "FYI") \
                    and _rule_assignment.confidences.get(_rule_assignment.default_label, 0) >= 0.80:
                _rule_label = _rule_assignment.default_label
                _rule_reason = _rule_assignment.reasons.get(_rule_label, "")
                logger.info("[classify_and_draft] Rule-based fast exit: %s (email_id=%s, reason=%s)",
                            _rule_label, email_id, _rule_reason)
                decision = RoutingDecision(
                    tier=RoutingTier.SKIP, complexity_score=0,
                    reason=f"Rule-based: {_rule_label}",
                )
                return RoutingResult(
                    draft="", decision=decision,
                    classification=_rule_label, priority=0,
                    status=f"RULE_{_rule_label.upper()}",
                )
        except Exception as _rule_exc:
            logger.debug("[classify_and_draft] Rule-based pre-check failed (non-blocking): %s", _rule_exc)

        # Complexity check: only use combined for STANDARD-eligible
        signals = analyze_complexity(body=body, subject=subject)
        score = calculate_complexity_score(signals)

        if score >= ROUTING_COMPLEX_THRESHOLD:
            # Too complex for Haiku — return with empty draft, let caller use COMPLEX pipeline
            decision = RoutingDecision(
                tier=RoutingTier.COMPLEX, complexity_score=score,
                reason=f"score={score}, needs separate COMPLEX pipeline",
                signals=signals,
            )
            return RoutingResult(
                draft="", decision=decision,
                classification="", priority=0, status="NEEDS_COMPLEX",
            )

        # Combined Haiku call
        from app.infrastructure.container import get_container
        from app.prompts import get_classify_and_draft_prompts, load_account_knowledge

        container = get_container()

        style_context = ""
        try:
            profile = container.get_writing_style_profile(account_id=getattr(self, "_account_id", 1))
            if profile:
                from app.prompts.style_guidance import build_style_guidance_from_profile
                style_context = build_style_guidance_from_profile(
                    profile, language="fr", recipient_email=sender
                )
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        # Load knowledge base for grounded answers.
        # P0.1 (2026-05-14): prefer per-account onboarding KB over the
        # deprecated global memoire.md — same rationale as _build_prompts.
        knowledge_base = ""
        try:
            knowledge_base = load_account_knowledge(getattr(self, "_account_id", None))
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        # Specialty context (Expert Mode) — only for COMPLEX emails
        specialty_context = ""
        if score >= ROUTING_COMPLEX_THRESHOLD:
            try:
                from app.specialty_engine import get_specialty_engine
                engine = get_specialty_engine()
                # Resolve the caller's account so specialty activations come from
                # the per-account DB overrides, not the process-global file
                # (audit 2026-05-29). classify_and_draft has no request context,
                # so derive the account_id from user_email.
                _spec_aid = None
                if user_email:
                    try:
                        from app.db.database import get_db_session
                        from app.db.repositories.account_repository import AccountRepository
                        with get_db_session() as _s:
                            _a = AccountRepository(_s).get_by_email(user_email)
                            if _a:
                                _spec_aid = _a.id
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                active = engine.get_active_specialties(account_id=_spec_aid)
                if active:
                    match = engine.classify_email(subject, body, active)
                    if match:
                        specialty_context = engine.build_specialty_context(match)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        # Filter conversation history to most relevant items if possible
        filtered_history = conversation_history
        if conversation_history:
            try:
                from app.api.routes import _find_relevant_history_for_email
                relevant = _find_relevant_history_for_email(body, conversation_history)
                if relevant:
                    filtered_history = relevant
                    logger.info(f"SmartRouter COMBINED: filtered history {len(conversation_history)} -> {len(relevant)} relevant items")
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        system_prompt, user_prompt = get_classify_and_draft_prompts(
            sender=sender, subject=subject, body=body,
            style_context=style_context,
            contact=sender,
            sender_name=sender_name,
            conversation_history=filtered_history,
            knowledge_base=knowledge_base,
            specialty_context=specialty_context,
            account_id=getattr(self, "_account_id", None),
        )

        # Pre-compute greeting hint for post-LLM enforcement
        from app.prompts import (
            analyze_email_formality, _compute_greeting_hint, _detect_language,
        )
        formality = analyze_email_formality(f"{subject}\n{body}")
        detected_language = _detect_language(f"{subject} {body}", fallback_language=self._primary_language_fallback())
        greeting_hint = _compute_greeting_hint(
            sender_name or "",
            formality,
            detected_language,
            sender_email=sender,
            signature_text=body,
        )
        closing_hint = self._closing_hint_for(formality, detected_language)

        max_tokens = 32  # classification only — {"label": "..."} ~20 tokens
        # Per-email classification — routes to ANTHROPIC_API_KEY_BACKGROUND.
        llm = container.llm_background

        try:
            from app.infrastructure.llm_attribution import llm_attribution

            with llm_attribution(
                "smart_router_classify",
                account_id=getattr(self, "_account_id", None),
                feature="classify",
            ):
                response = llm.complete(
                    system=system_prompt,
                    user=user_prompt,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
        except Exception as _llm_err:
            logger.error(
                "SmartRouter classify_and_draft: LLM call failed (%s): %s",
                type(_llm_err).__name__, _llm_err,
            )
            # Bail out gracefully — caller should treat this as "classification
            # failed" and fall back to the default label/route.
            return RoutingResult(
                draft="",
                decision=RoutingDecision(
                    tier=RoutingTier.STANDARD,
                    complexity_score=0,
                    reason="llm_error",
                    max_tokens=max_tokens,
                    signals=ComplexitySignals(),
                ),
                classification="Action",
                priority=50,
                status="LLM_ERROR",
            )

        # Track tokens
        if hasattr(response, "input_tokens"):
            container.token_usage.add(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                model=getattr(llm, "model", "haiku"),
            )

        content = response.content.strip() if hasattr(response, "content") else str(response).strip()
        classification, draft = _parse_combined_response(content)
        _classify_raw_draft = draft  # capture raw draft before pipeline for fixture logging

        # Post-LLM cleanup pipeline (same order as _generate_standard)
        if draft:
            draft = _clean_prompt_leakage(draft)
            draft = strip_unknown_body_artifacts(draft)
            # Reasoning leakage runs BEFORE markdown stripping — see Bug C
            # comment in _generate_standard.
            draft = strip_reasoning_leakage(draft)  # audit Q7 + stress 2026-05-13
            draft = _strip_markdown_artifacts(draft)  # P14
            draft = _strip_clarification_draft(draft)
            draft = _strip_filler_mid_draft(draft, formality)  # #10: tone-aware
            draft = _strip_signature(draft)
            draft = _truncate_for_short_body(draft, body)
            draft = _strip_subject_echo(draft, subject)  # #4
            draft = _strip_technical_echo(draft, body)
            if len(body) >= 300:
                draft = _strip_parroting(draft, body)
            else:
                draft = _strip_leading_parrot(draft, body)
            draft = _scrub_hallucinated_facts(draft, body)
            draft = _scrub_invented_contacts(draft, body)  # P8
            draft = _scrub_ungrounded_nouns(draft, body, subject=subject, sender=sender)  # L3
            draft = _scrub_novel_situation(draft, body, subject=subject)  # L3b
            draft = _scrub_hallucinated_context(draft, body, has_history=bool(conversation_history))
            draft = _scrub_process_language(draft)
            draft = _strip_hedging(draft)  # #1
            draft = _strip_a_confirmer(draft)  # #1b
            draft = _strip_sycophancy(draft)  # P9
            draft = _strip_unnecessary_questions(draft, body)  # #9
            draft = _strip_excessive_apologies(draft)  # P3
            draft = _strip_redundant_affirmations(draft)  # P4
            draft = _simplify_contrast_patterns(draft)  # P7
            draft = _strip_slop_words(draft)  # P6
            draft = strip_ai_dashes(draft)
            draft = _strip_recap_sentences(draft)  # P12
            draft = _fix_repetitive_openings(draft)  # P2
            draft = _strip_duplicate_greetings(draft)

        # Apply learned correction patterns post-LLM
        classify_learned_applied: list = []
        if draft:
            try:
                from app.draft_correction import get_correction_manager
                corrected, applied = get_correction_manager().apply_learned_corrections(
                    draft, context={"sender": sender, "subject": subject}
                )
                if applied:
                    draft = corrected
                    classify_learned_applied = list(applied)
                    logger.info(f"SmartRouter COMBINED: {len(applied)} learned correction(s) applied")
                    # #13: Re-validate after corrections
                    draft = _strip_filler_mid_draft(draft, formality)
                    draft = _scrub_hallucinated_facts(draft, body)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        # Safety overrides
        if draft:
            draft = _detect_misdirected(draft, body, sender_name or sender)
            draft = _detect_social_engineering(draft, body)
            draft = _detect_blackmail(draft, body)
            draft = _ensure_legal_caution(draft, body)
            draft = _clean_language_artifacts(draft)
            draft = _detect_language_drift(draft, detected_language)  # #6
            draft = _fix_pronoun_consistency(draft, formality)  # P1
            draft = _fix_closing_tone(draft, formality)  # P5
            draft = _fix_name_overuse(draft, sender_name or "")  # P13

        # Greeting + closing enforcement LAST
        if draft:
            draft = _enforce_greeting(draft, greeting_hint)
            draft = _enforce_closing(draft, closing_hint)
            # Issue #592: collapse stacked contextual + canonical closings.
            draft = _strip_stacked_contextual_closing(draft)

        capture_if_enabled(
            mode="classify",
            raw_draft=_classify_raw_draft or "",
            pipeline_input={
                "body": body,
                "subject": subject,
                "sender": sender,
                "sender_name": sender_name,
                "greeting_hint": greeting_hint,
                "detected_language": detected_language,
                "formality": formality,
                "conversation_history": conversation_history or [],
            },
            cleaned_draft=draft or "",
            corrections=0,
            correction_details=[],
            learned_corrections_applied=classify_learned_applied,
            extra={"email_id": email_id, "classification": classification},
        )

        if email_id and draft:
            _cache_draft(email_id, draft, account_id=getattr(self, "_account_id", None), content_hash=getattr(self, "_content_hash", None))

        tier = RoutingTier.STANDARD if draft else RoutingTier.SIMPLE
        decision = RoutingDecision(
            tier=tier, complexity_score=score,
            reason=f"combined label+draft ({classification})",
            max_tokens=max_tokens, signals=signals,
        )

        priority = 70 if classification == "Action" else 20

        logger.info(f"SmartRouter COMBINED: {classification}, draft={'yes' if draft else 'no'} ({len(draft)} chars)")
        critique_info = None
        return RoutingResult(
            draft=draft, decision=decision,
            classification=classification, priority=priority,
            status="COMBINED_HAIKU",
            critique_info=critique_info,
        )


# ============================================================================
# HELPERS
# ============================================================================

def _parse_combined_response(content: str) -> tuple[str, str]:
    """
    Parse classification-only JSON response.

    Expected format: {"label": "Action|FYI|Noise"}

    Returns:
        (classification, draft) tuple where draft is always "".
    """
    # Try JSON parse
    try:
        # Strip markdown code fences if present
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        label = data.get("label", "FYI")
        draft = data.get("draft") or ""
        if draft == "null":
            draft = ""
        return label, draft
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"Suppressed: {e}")

    # Fallback: look for label keyword at start
    for label in ("Action", "FYI", "Noise"):
        if content.startswith(label):
            parts = content.split("\n", 1)
            return label, parts[1].strip() if len(parts) > 1 else ""

    return "FYI", ""


def _parse_email_content(email_content: str) -> tuple[str, str, str]:
    """Parse formatted email string into (sender, subject, body)."""
    sender = ""
    subject = ""
    body = ""
    lines = email_content.split('\n')
    body_start = 0
    for i, line in enumerate(lines):
        lower = line.lower().strip()
        if lower.startswith('de:') or lower.startswith('from:'):
            sender = line.split(':', 1)[1].strip()
        elif lower.startswith('sujet:') or lower.startswith('subject:'):
            subject = line.split(':', 1)[1].strip()
        elif not line.strip() and i > 0:
            body_start = i + 1
            break
    if body_start:
        body = '\n'.join(lines[body_start:]).strip()
    return sender, subject, body


def _expand_greeting_template(template: str, sender: str, language: str) -> str:
    """Expand `{first_name}`, `{last_name}`, `{civility}` tokens in a user-defined
    greeting template against the current recipient.

    Fallback rules:
      - `{first_name}` missing → empty string
      - `{last_name}` missing → falls back to `{first_name}` (keeps the email friendly)
      - `{civility}` missing / non-person → empty string (whitespace is collapsed)

    The language is used to localize civility (FR: M./Mme, EN: Mr./Ms.).
    """
    if not template or "{" not in template:
        return template.strip()

    import re as _re
    from app.prompts.identity import _is_likely_feminine, _is_person_name

    # Extract display name ("John Doe <x@y>" → "John Doe").
    raw_name = sender.split("<")[0].strip().strip('"').strip("'")
    if not raw_name or "@" in raw_name:
        raw_name = ""

    # Handle "Last, First" and "LAST First" variants (mirrors identity.py:387-406).
    name = raw_name
    if name and "," in name:
        a, b = [p.strip() for p in name.split(",", 1)]
        if a and b:
            name = f"{b} {a}"
    parts = name.split() if name else []
    if (len(parts) >= 2 and parts[0] == parts[0].upper()
            and parts[0] != parts[0].lower() and len(parts[0]) > 1):
        first_name, last_name = parts[1], parts[0]
    else:
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else ""

    # Tiebreaker: when the display name is a single word ("Aubert") but the
    # email address exposes a richer "firstname.lastname" pair, the lone word
    # is almost always the LAST name. We only swap if the email prefix has
    # multiple tokens AND the display word matches the LAST token (i.e. the
    # first token is the missing first name) — never the other way around,
    # which would corrupt cases where the display already holds the first name.
    if len(parts) == 1 and "<" in sender and "@" in sender:
        sole = parts[0]
        sole_lower = sole.lower()
        email_part = sender.split("<", 1)[1].split(">", 1)[0]
        email_prefix = email_part.split("@", 1)[0]
        tokens = [t for t in _re.split(r"[._\-+]", email_prefix.lower()) if t.isalpha() and len(t) >= 2]
        if len(tokens) >= 2 and tokens[-1] == sole_lower and tokens[0] != sole_lower:
            first_name = tokens[0].capitalize()
            last_name = sole

    # Civility only makes sense for actual person names.
    if raw_name and _is_person_name(raw_name):
        feminine = _is_likely_feminine(first_name)
        if language == "ENGLISH":
            civility = "Ms." if feminine else "Mr."
        else:
            civility = "Mme" if feminine else "M."
    else:
        civility = ""

    # Fallback: if template references {last_name} but we only have a first
    # name, substitute the first name so we don't produce "Bonjour M. ,".
    if "{last_name}" in template and not last_name and first_name:
        last_name = first_name
        civility = ""  # avoid "M. Alexandre"

    rendered = (
        template
        .replace("{first_name}", first_name)
        .replace("{last_name}", last_name)
        .replace("{civility}", civility)
    )
    # Collapse whitespace introduced by empty tokens, and normalize trailing comma.
    rendered = _re.sub(r"\s+", " ", rendered).strip()
    rendered = _re.sub(r"\s+,", ",", rendered)
    return rendered


def _extract_first_name(sender: str, signature_text: str = "") -> str:
    """Extract first name from sender string like 'John Doe <john@example.com>'."""
    # Strip email part
    name = sender.split("<")[0].strip().strip('"').strip("'")
    try:
        from app.prompts.identity import (
            _display_name_conflicts_with_email_tokens,
            _display_has_explicit_service_word,
            _email_local_name_tokens,
            _is_person_name,
            _name_words,
            _signature_name_matching_email,
            _signature_person_name,
            _name_token_matches,
        )
        email_tokens = _email_local_name_tokens(sender)
        signature_name = _signature_name_matching_email(signature_text, sender)
        signature_person = (
            "" if _display_has_explicit_service_word(name)
            else _signature_person_name(signature_text)
        )
        if not name or "@" in name:
            if signature_name:
                return signature_name.split()[0]
            if signature_person:
                return signature_person.split()[0]
            return email_tokens[0].capitalize() if len(email_tokens) >= 2 else ""
        if not _is_person_name(name):
            if _display_has_explicit_service_word(name):
                return ""
            if signature_name:
                return signature_name.split()[0]
            if len(email_tokens) >= 2:
                return email_tokens[0].capitalize()
            if signature_person:
                return signature_person.split()[0]
            return ""
        signature_words = _name_words(signature_name)
        display_words = _name_words(name)
        display_is_signature_last_name = (
            bool(signature_words)
            and len(display_words) == 1
            and len(signature_words) >= 2
            and any(_name_token_matches(display_words[0], word) for word in signature_words[1:])
            and not _name_token_matches(display_words[0], signature_words[0])
        )
        if signature_name and (
            _display_name_conflicts_with_email_tokens(name, email_tokens)
            or display_is_signature_last_name
        ):
            return signature_name.split()[0]
        if _display_name_conflicts_with_email_tokens(name, email_tokens):
            return email_tokens[0].capitalize()
    except Exception:
        pass
    if not name or "@" in name:
        return ""
    # Take first word as first name
    parts = name.split()
    return parts[0] if parts else ""


def _strip_signature(draft: str) -> str:
    """Remove trailing signature/sign-off lines that the LLM may have invented."""
    _signoffs = [
        'cordialement', 'best', 'regards', 'sincerely',
        'a bientot', 'à bientôt', 'bien à', 'amicalement',
        'kind regards', 'yours', 'cheers', 'thanks', 'thank you',
        'merci', 'merci,', 'cdlt',
        'à plus', 'a plus', 'à bientôt', 'a bientôt', 'à+',
    ]

    lines = draft.split('\n')

    # Strip trailing empty lines
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return draft

    # Pattern: [sign-off]\n[name] at end → strip both
    if len(lines) >= 2:
        last = lines[-1].strip()
        above = lines[-2].strip().lower().rstrip(',. ')
        if (len(last) < 30 and not last.endswith('?')
                and any(above.startswith(p) for p in _signoffs)):
            lines.pop()  # name
            lines.pop()  # sign-off

    # Strip remaining trailing sign-off/empty lines
    while lines:
        last = lines[-1].strip()
        if not last or last == ',':
            lines.pop()
            continue
        if len(last) >= 40 or last.endswith('?'):
            break
        last_lower = last.lower()
        if any(last_lower.startswith(p) for p in _signoffs):
            lines.pop()
            continue
        break

    # Strip the user's own name and/or title/role lines from the tail of the draft.
    # Handles all orders: [name], [title], [name][title], [title][name], and
    # one-line variants like "Name / Title" or "Name, Title".
    _title_hints = ('fondateur', 'co-fondateur', 'cofondateur', 'ceo', 'cto', 'coo', 'cfo',
                    'directeur', 'directrice', 'manager', 'président', 'presidente',
                    'vp', 'lead', 'head', 'chief', 'associate', 'consultant', 'partner',
                    'analyst', 'engineer', 'developer', 'designer', 'architecte',
                    'responsable', 'coordonnateur', 'chef', 'owner', 'founder')

    def _looks_like_title(line: str) -> bool:
        s = line.strip()
        if not (3 < len(s) < 80) or s.endswith('?') or s.endswith('.'):
            return False
        return any(h in s.lower() for h in _title_hints)

    try:
        from app.prompts import _extract_user_name
        user_name = _extract_user_name()
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
        user_name = None

    name_variants: set[str] = set()
    if user_name:
        name_variants.add(user_name.lower())
        parts = user_name.split()
        if parts:
            name_variants.add(parts[0].lower())
            last_part = parts[-1].lower() if len(parts) > 1 else parts[0].lower()
            for title in ("m.", "mme", "mr.", "mrs.", "ms.", "dr."):
                name_variants.add(f"{title} {last_part}")
                name_variants.add(f"{title} {user_name.lower()}")

    def _looks_like_name(line: str) -> bool:
        s = line.strip().lower().rstrip(',. ')
        return bool(name_variants) and s in name_variants

    def _looks_like_name_title_inline(line: str) -> bool:
        """Match 'Name / Title' or 'Name, Title' or 'Name - Title' on one line,
        or a bare 'Title of Company' single-line signature."""
        s = line.strip()
        if not (3 < len(s) < 120):
            return False
        for sep in ('/', '|', ',', ' - ', ' — ', ' – '):
            if sep in s:
                left, _, right = s.partition(sep)
                if _looks_like_name(left) and any(h in right.lower() for h in _title_hints):
                    return True
                if _looks_like_name(right) and any(h in left.lower() for h in _title_hints):
                    return True
                if any(h in left.lower() for h in _title_hints) and any(h in right.lower() for h in _title_hints):
                    return True
        return False

    # Up to 4 passes: peel off the last signature-like line at a time. Handles all
    # orders: [name], [title], [name]\n[title], [title]\n[name], and inline variants.
    for _ in range(4):
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        last_line = lines[-1]
        if (_looks_like_name(last_line)
                or _looks_like_title(last_line)
                or _looks_like_name_title_inline(last_line)):
            lines.pop()
            continue
        break

    # Strip trailing artifacts (e.g. "YES," or isolated words)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        last_stripped = lines[-1].strip()
        if last_stripped in ('YES,', 'YES', 'NO,', 'NO', 'OUI,', 'NON,') or (
            len(last_stripped) < 5 and last_stripped.endswith(',')
        ):
            lines.pop()

    return '\n'.join(lines).strip()


import re as _re


_GREETING_INLINE_RE = _re.compile(
    r'^((?:Bonjour|Salut|Hello|Hi|Hey|Cher|Chère|Dear|Monsieur|Madame|Mme|M\.|Mr\.|Mrs\.|Dr\.|Prof\.)\b[^,\n]*,)\s+(\S.+)$',
    _re.IGNORECASE,
)


# Greeting prefixes used to decide whether the LLM produced a salutation
# at all. Kept private to this module — the corresponding regex variant
# lives in `_strip_duplicate_greetings` and `_separate_greeting_from_body`.
_GREETING_PREFIXES = (
    'salut', 'bonjour', 'bonsoir', 'coucou', 'hello', 'hi ', 'hi,', 'hi!',
    'hey', 'dear', 'cher ', 'chere ', 'chère ', 'monsieur', 'madame',
    'm.', 'mr.', 'mr ', 'mrs.', 'mrs ', 'ms.', 'ms ',
    'dr.', 'dr ', 'mme.', 'mme ', 'prof.', 'prof ',
)


# Bare greeting words accepted by `is_canonical_greeting` in addition to
# the prefix-based matches in `_GREETING_PREFIXES`. The latter requires a
# trailing space/comma/exclamation to avoid catching "High" / "History"
# when matching the START of a body line — but here we're matching the
# WHOLE value of a profile field, so bare "Hi" or "Salut" are legitimate.
_BARE_GREETINGS = frozenset({
    "hi", "hey", "salut", "bonjour", "bonsoir", "coucou", "hello",
    "cher", "chère", "chere", "monsieur", "madame", "mademoiselle",
})


def is_canonical_greeting(value: object) -> bool:
    """True iff ``value`` looks like a real email greeting.

    Used to validate a contact's learned ``preferred_greeting`` before
    feeding it as the mandatory opening of a refine/compose call. A
    WritingStyleProfile can pick up arbitrary first-line text from a
    polluted previous draft ("Je ne peux pas mais ...", "OK super, ...",
    etc.). Without this guard, such polluted phrases land in the system
    prompt's `MANDATORY OPENING LINE` rule and the LLM dutifully copies
    them into every generated email for the contact (2026-05-13 incident).

    Accepts:
      - Canonical prefixes from ``_GREETING_PREFIXES`` (Salut, Bonjour,
        Hi, Hello, Cher, Monsieur, M., Mme, Dr., ...).
      - Bare greeting words from ``_BARE_GREETINGS`` ("Hi", "Salut", ...).
      - Tokenized template form starting with ``{`` (e.g.
        ``"{first_name},"`` or ``"Bonjour {first_name},"``).

    Rejects everything else, including the empty / whitespace string.
    """
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    if not cleaned:
        return False
    if cleaned.startswith("{"):
        return True
    low = cleaned.lower()
    if any(low.startswith(p) for p in _GREETING_PREFIXES):
        return True
    return low in _BARE_GREETINGS


_GREETING_ADDRESSEE_RE = _re.compile(
    r"^\s*(?:bonjour|bonsoir|salut|coucou|hello|hi|hey|dear|cher|chère|chere)\s+([^,\n!?]+)",
    _re.IGNORECASE,
)
_GREETING_GENERIC_ADDRESSEES = frozenset({
    "all", "everyone", "there", "team", "tous", "toutes", "equipe", "équipe",
})
_GREETING_TITLE_TOKENS = frozenset({
    "maitre", "maître", "monsieur", "madame", "mademoiselle", "mr", "mrs",
    "ms", "dr", "prof", "professor",
})


def _normalise_name_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", (value or "").lower())
    without_accents = "".join(
        ch for ch in normalized if not unicodedata.combining(ch)
    )
    return _re.findall(r"[a-z0-9]+", without_accents)


def _name_word_matches(left: str, right: str) -> bool:
    if left == right:
        return True
    return min(len(left), len(right)) >= 3 and (
        left.startswith(right) or right.startswith(left)
    )


def is_canonical_greeting_for_contact(
    value: object,
    contact_name: object,
) -> bool:
    """Validate a learned greeting against the contact it is meant to address.

    ``is_canonical_greeting("Salut Nat,")`` is structurally true, but it is
    unsafe for Alex's contact profile. This helper rejects canonical greetings
    whose explicit addressee conflicts with the known contact name, while still
    allowing generic/title openings such as "Bonjour," or "Bonjour Maître,".
    """
    if not is_canonical_greeting(value):
        return False
    if not isinstance(value, str):
        return False
    if not isinstance(contact_name, str) or not contact_name.strip():
        return True

    cleaned = value.strip()
    if "{" in cleaned:
        return True

    match = _GREETING_ADDRESSEE_RE.match(cleaned)
    if not match:
        return True

    addressee_words = _normalise_name_words(match.group(1))
    contact_words = _normalise_name_words(contact_name)
    if not addressee_words or not contact_words:
        return True
    if addressee_words[0] in _GREETING_GENERIC_ADDRESSEES:
        return True
    if addressee_words[0] in _GREETING_TITLE_TOKENS:
        return True

    return any(
        _name_word_matches(addressee, contact)
        for addressee in addressee_words
        for contact in contact_words
    )


# Malformed-opening sentinels. Haiku occasionally produces broken French
# sentence starts like "Je ne peux pas mais Je," or "Je dois mais je,"
# when squeezed between the system prompt's "Never refuse" rule and a
# short/casual dictation. The double-pronoun + trailing comma is the
# tell. We don't try to rewrite the whole sentence — just rip out the
# unsalvageable prefix so the rest of the email (which is usually fine)
# reads naturally.
_MALFORMED_OPENING_RE = _re.compile(
    r"^\s*(?:Je|I)\s+(?:ne\s+peux\s+pas|peux\s+pas|cannot|can'?t|dois|doit|must|will|shall)"
    r"(?:\s+\w+){0,3}\s+(?:mais|but)\s+(?:Je|I)\s*,\s*",
    _re.IGNORECASE,
)


def _strip_malformed_opening(draft: str) -> str:
    """Strip the leading "Je [verb] mais Je," anti-pattern when the LLM
    produced it. The trailing comma plus the repeated pronoun is the
    unique signature; bare "Je ne peux pas" prose in the middle of a
    paragraph is left alone."""
    if not draft:
        return draft
    new = _MALFORMED_OPENING_RE.sub("", draft, count=1)
    if new is not draft and new != draft:
        # If we stripped, the next character is now lowercase-suspect (the
        # original was mid-sentence). Capitalize the very first letter so
        # the body starts with a proper sentence.
        new = new.lstrip()
        if new:
            new = new[0].upper() + new[1:]
        return new
    return draft


def _ensure_starts_with_greeting(
    draft: str,
    mandatory_opening: str | None,
    *,
    strict_replace: bool = False,
) -> str:
    """Guarantee the draft opens with a greeting line.

    Some LLM passes (notably Haiku refining short / dictated notes) emit
    a body that starts mid-thought without any salutation. If we have a
    `mandatory_opening` hint and the first non-empty line is NOT a
    recognised greeting, prepend the hint + a blank line.

    ``strict_replace`` (added 2026-05-13 for the Simon bug): when True,
    a first line that IS a greeting but does NOT match ``mandatory_opening``
    is REPLACED. This is the right behaviour when the contact has an
    explicit per-contact override (nickname, ``preferred_greeting``,
    ``formality_locked``) — those signals encode "always greet this contact
    like X" and must win over whatever the LLM copied from the user's
    dictated source notes. The default (False) preserves the legacy
    permissive behaviour so the reply path and other callsites are not
    changed silently.
    """
    if not draft or not mandatory_opening:
        return draft
    lines = draft.split('\n')
    # Locate the first non-empty line.
    first_idx = -1
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            break
    if first_idx < 0:
        return draft
    first_line = lines[first_idx].strip()
    first_lower = first_line.lower()
    # Bug 2026-05-13: when `mandatory_opening` is a non-canonical phrase
    # (e.g. a contact's learned `preferred_greeting` like "Je ne peux pas
    # mais Alexandre,"), it does NOT start with any prefix in
    # `_GREETING_PREFIXES`. If the LLM correctly opens the body with that
    # exact hint per the system-prompt rule, this function used to fall
    # through and prepend the hint again → duplicate first line. Treat a
    # first-line match against the hint itself as "already greeted".
    hint_lower = mandatory_opening.strip().lower()
    if hint_lower and first_lower.startswith(hint_lower):
        return draft  # already opens with the mandatory hint, no duplicate
    is_greeting = any(first_lower.startswith(p) for p in _GREETING_PREFIXES)
    if is_greeting:
        if not strict_replace:
            return draft  # legacy soft mode — keep the LLM's greeting choice
        # Strict mode: the contact has explicit overrides, so the LLM's
        # disagreeing greeting must be overwritten — not appended to.
        lines[first_idx] = mandatory_opening.rstrip()
        return '\n'.join(lines)
    # Prepend mandatory_opening as a standalone first line + blank line.
    return mandatory_opening.rstrip() + "\n\n" + draft.lstrip('\n')


def _separate_greeting_from_body(draft: str) -> str:
    """Ensure greeting is on its own line with a blank line before the body."""
    lines = draft.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Only process the first non-empty line
        # Case 1: Greeting + body on same line → split them
        m = _GREETING_INLINE_RE.match(stripped)
        if m:
            lines[i] = m.group(1)
            lines.insert(i + 1, '')
            lines.insert(i + 2, m.group(2))
            break
        # Case 2: Greeting on its own line but no blank line after
        lower = stripped.lower()
        _greet_starts = [
            'salut', 'bonjour', 'hello', 'hi', 'hey', 'dear',
            'monsieur', 'madame', 'cher', 'chere', 'chère',
            'm.', 'mr.', 'mrs.', 'ms.', 'dr.', 'mme.', 'prof.',
        ]
        is_greeting = any(lower.startswith(p) for p in _greet_starts)
        if is_greeting and i + 1 < len(lines) and lines[i + 1].strip():
            lines.insert(i + 1, '')
        break
    return '\n'.join(lines)


def _enforce_greeting(draft: str, greeting_hint: str) -> str:
    """
    Post-LLM pass: ensure the draft starts with the expected greeting,
    on its own line with a blank line before the body.

    If the LLM ignored the START WITH instruction, replace the first line
    (which is typically a greeting) with the correct one.
    """
    if not draft:
        return draft

    # Empty greeting_hint = VERY CASUAL or hot-thread continuation —
    # strip any greeting the LLM added.
    if not greeting_hint:
        lines = draft.split('\n')
        _strip_patterns = [
            'salut', 'bonjour', 'hello', 'hi ', 'hi,', 'hey', 'dear',
            'bonsoir', 'coucou',
        ]
        _stripped_any = False
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if stripped and any(stripped.startswith(p) for p in _strip_patterns):
                lines[i] = ''
                _stripped_any = True
                break
            elif stripped:
                break  # first non-empty line is not a greeting
        _bump("greeting_stripped" if _stripped_any else "greeting_skipped")
        return '\n'.join(lines).lstrip('\n')

    # Normalize: remove trailing comma/space from hint for comparison
    hint_clean = greeting_hint.strip().rstrip(',').lower()
    lines = draft.split('\n')

    # Find the first non-empty line
    first_idx = 0
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            break

    first_line = lines[first_idx].strip()
    first_clean = first_line.rstrip(',').lower()

    # Check if the first line is a greeting that differs from hint
    _greeting_patterns = [
        'salut', 'bonjour', 'bonsoir', 'coucou', 'hello', 'hi', 'hey', 'dear', 'monsieur',
        'madame', 'cher', 'chere', 'chère',
        'm.', 'mr.', 'mr ', 'mrs.', 'mrs ', 'ms.', 'ms ', 'dr.', 'dr ',
        'mme.', 'mme ', 'prof.', 'prof ',
    ]
    # Formal greetings that should NEVER be replaced by informal ones
    _formal_greetings = ['monsieur', 'madame', 'cher ', 'chere ', 'chère ', 'dear ',
                          'm.', 'mr.', 'mr ', 'mrs.', 'mrs ', 'ms.', 'ms ',
                          'dr.', 'dr ', 'mme.', 'mme ', 'prof.', 'prof ']

    first_is_greeting = any(first_clean.startswith(p) for p in _greeting_patterns)

    if first_is_greeting and not first_clean.startswith(hint_clean):
        # Don't replace formal greetings (Monsieur/Madame/Cher) with informal ones
        first_is_formal = any(first_clean.startswith(f) for f in _formal_greetings)
        hint_is_informal = any(hint_clean.startswith(p) for p in ['salut', 'bonjour', 'hello', 'hi', 'hey'])
        hint_is_formal_title = any(hint_clean.startswith(f) for f in _formal_greetings)
        first_is_strong_casual = first_clean.startswith("coucou ")
        if first_is_strong_casual and hint_is_formal_title:
            _bump("greeting_ok")
        elif not (first_is_formal and hint_is_informal):
            # Replace the greeting line with the correct one
            lines[first_idx] = greeting_hint
            _bump("greeting_fixed")
            logger.info(
                f"_enforce_greeting: fixed (LLM wrote {first_line!r}, "
                f"expected {greeting_hint!r})"
            )
        else:
            _bump("greeting_ok")
    elif not first_is_greeting:
        # No greeting at all — prepend one
        lines.insert(first_idx, greeting_hint + '\n')
        _bump("greeting_added")
        logger.info("_enforce_greeting: added (LLM dropped the greeting)")
    else:
        _bump("greeting_ok")

    draft = '\n'.join(lines)

    # Final: ensure greeting stands alone with blank line before body
    return _separate_greeting_from_body(draft)


# Known closing formulas used to detect an existing closing at the end of a
# draft. Lowercase, stripped of trailing punctuation. Order does not matter.
_CLOSING_FORMULAS = (
    'cordialement', 'bien cordialement', 'sincèrement', 'sincerement',
    'bien à vous', 'bien a vous', 'bien à toi', 'bien a toi',
    'respectueusement', 'avec mes salutations', 'salutations distinguées',
    'salutations distinguees', 'à bientôt', 'a bientot', 'à très bientôt',
    'a tres bientot', 'à plus', 'a plus', 'à+', 'a+', 'amicalement',
    'bises', 'bisous', 'tendrement', 'je t\'embrasse', 'je vous embrasse',
    'merci encore', 'merci beaucoup', 'merci',
    'best regards', 'kind regards', 'warm regards', 'regards',
    'sincerely', 'sincerely yours', 'yours truly', 'yours sincerely',
    'best', 'cheers', 'thanks', 'thank you', 'many thanks', 'ta',
    'take care', 'talk soon', 'speak soon', 'see you soon', 'see you',
    'looking forward', 'all the best',
    # Spanish — so a Spanish draft's own closing is recognized (no double
    # append) and a leaked FR/EN closing can be swapped for the ES hint
    # (audit 2026-05-19 F-03).
    'atentamente', 'saludos cordiales', 'un cordial saludo', 'cordial saludo',
    'saludos', 'un saludo', 'un abrazo', 'abrazos', 'muchas gracias', 'gracias',
)


def _enforce_closing(
    draft: str,
    closing_hint: str,
    replace_existing: bool = True,
) -> str:
    """
    Post-LLM pass: ensure the draft ends with the expected closing formula
    on its own line, preceded by a blank line.

    Behavior:
      - Empty closing_hint (VERY CASUAL): strip any closing the LLM added
        and return the body as-is.
      - Draft already ends with a known closing:
          * `replace_existing=True` (drafting): replace with closing_hint
            to normalize spelling and guarantee blank-line separation.
          * `replace_existing=False` (refine/edit paths): keep the user's
            existing closing as-is, only normalize the blank line before.
      - Draft does not end with a closing → append closing_hint with a
        blank line separator.
    """
    if not draft:
        return draft

    lines = draft.split('\n')

    # Trim trailing empty lines (we'll re-add blank line + closing ourselves).
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return draft

    # Empty closing_hint = VERY CASUAL — strip any closing the LLM wrote.
    if not closing_hint:
        last_clean = lines[-1].strip().lower().rstrip(',.;:!')
        # Word-count cap: real closings are ≤ 6 words. Without this guard,
        # a body sentence starting with "Merci ..." (a closing formula
        # prefix) gets falsely detected and stripped — see _enforce_closing
        # bug below and 2026-05-13 incident.
        if (
            len(last_clean.split()) <= 6
            and any(last_clean == c or last_clean.startswith(c + ' ')
                    for c in _CLOSING_FORMULAS)
        ):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
            _bump("closing_stripped")
        return '\n'.join(lines)

    # Does the draft already end with a closing-like line?
    # IMPORTANT: cap line length at 6 words. The `_CLOSING_FORMULAS` set
    # includes short prefixes like 'merci', 'best', 'thanks' that match
    # the start of perfectly valid BODY sentences ("Merci de l'invitation.
    # Je vais être présent..."). Without the cap, the body was treated as
    # a closing and replaced by the `closing_hint` (which could be a
    # learned "Merci!,") — that's how 12-word body lines vanished into a
    # 1-word "Merci!," (2026-05-13 incident). All canonical closings in
    # `_CLOSING_FORMULAS` are ≤ 4 words, so 6 leaves headroom for a name
    # suffix ("Best regards, Alex,") without admitting body sentences.
    last_clean = lines[-1].strip().lower().rstrip(',.;:!')
    last_is_closing = (
        len(last_clean.split()) <= 6
        and any(
            last_clean == c or last_clean.startswith(c + ' ') or
            last_clean.startswith(c + ',')
            for c in _CLOSING_FORMULAS
        )
    )

    if last_is_closing:
        if replace_existing:
            _existing = lines[-1]
            if _existing.strip().lower().rstrip(',.;:!') == closing_hint.strip().lower().rstrip(',.;:!'):
                _bump("closing_ok")
            else:
                # Replace with canonical hint (normalizes spelling + punctuation).
                lines[-1] = closing_hint
                _bump("closing_fixed")
                logger.info(
                    f"_enforce_closing: fixed (LLM wrote {_existing.strip()!r}, "
                    f"expected {closing_hint!r})"
                )
        else:
            # Refine path: keep the user's existing closing as-is.
            _bump("closing_preserved")
    else:
        # Append closing_hint as a new line.
        lines.append(closing_hint)
        _bump("closing_added")
        logger.info("_enforce_closing: added (draft ended without a closing)")

    # Guarantee a blank line between body and closing.
    closing_idx = len(lines) - 1
    if closing_idx > 0 and lines[closing_idx - 1].strip():
        lines.insert(closing_idx, '')

    return '\n'.join(lines)


def _is_closing_line(line: str) -> bool:
    cleaned = (line or "").strip().lower().rstrip(",.;:!")
    return (
        bool(cleaned)
        and len(cleaned.split()) <= 6
        and any(
            cleaned == formula
            or cleaned.startswith(formula + " ")
            or cleaned.startswith(formula + ",")
            for formula in _CLOSING_FORMULAS
        )
    )


def _is_greeting_line(line: str, greeting_hint: str = "") -> bool:
    cleaned = (line or "").strip().lower().rstrip(",.;:!")
    if not cleaned:
        return False
    expected = (greeting_hint or "").strip().lower().rstrip(",.;:!")
    if expected and cleaned == expected:
        return True
    if len(cleaned.split()) > 6:
        return False
    return cleaned.startswith((
        "bonjour", "bonsoir", "salut", "hello", "hi", "dear", "coucou",
    ))


def _has_substantive_body_line(draft: str, greeting_hint: str, closing_hint: str) -> bool:
    for raw in (draft or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_greeting_line(line, greeting_hint):
            continue
        if _is_closing_line(line):
            continue
        if closing_hint and line.lower().rstrip(",.;:!") == closing_hint.lower().rstrip(",.;:!"):
            continue
        if len(line) >= 12:
            return True
    return False


def _fallback_for_greeting_closing_stub(
    draft: str,
    subject: str,
    body: str,
    greeting_hint: str,
    closing_hint: str,
    detected_language: str,
    formality: int,
) -> str:
    """Replace salutation-only drafts for scheduling asks with a usable reply."""
    if _has_substantive_body_line(draft, greeting_hint, closing_hint):
        return draft

    text = f"{subject}\n{body}".lower()
    scheduling_terms = (
        "disponibilité", "disponibilités", "dispo", "rdv", "rendez-vous",
        "meeting", "créneau", "creneau", "call", "appel", "available",
        "availability",
    )
    if not any(term in text for term in scheduling_terms):
        return draft

    is_english = detected_language == "ENGLISH"
    if is_english:
        core = (
            "I can make time this week. Send me two slots you have in mind "
            "and I'll confirm the one that works."
        )
    elif formality >= 4:
        core = (
            "Je peux prévoir un court point cette semaine. Proposez-moi deux "
            "créneaux et je vous confirme celui qui convient."
        )
    else:
        core = (
            "Je peux prévoir un court point cette semaine. Propose-moi deux "
            "créneaux et je te confirme celui qui convient."
        )

    parts = []
    if greeting_hint:
        parts.append(greeting_hint)
    parts.append(core)
    if closing_hint:
        parts.append(closing_hint)
    logger.warning("SmartRouter: replaced greeting/closing-only scheduling draft with fallback")
    return "\n\n".join(parts)


# Issue #592 — "contextual closing" patterns. Short, conversational "see you
# [time]" lines that read as a sign-off in isolation but become a doublon
# when stacked with a generic canonical closing ("À bientôt,", "Best,").
# Intentionally narrow — the regex anchors end-of-string so it does NOT
# match body sentences like "Je te confirme à vendredi pour le call."
_CONTEXTUAL_CLOSING_RE = _re.compile(
    r"^(?:"
    # FR — "à [ce/cet/cette] <day-or-time-token>"
    r"à\s+(?:ce\s+|cet\s+|cette\s+)?"
    r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    r"|demain|tantôt|midi|tout\s+à\s+l['']?heure|tout\s+de\s+suite"
    r"|ce\s+soir|cet?\s+matin|cet?\s+après[-\s]?midi"
    r"|la\s+semaine\s+prochaine|la\s+prochaine|une\s+autre\s+fois)"
    # FR — "on se voit/parle/reparle/tient au courant (demain/vendredi/...)"
    r"|on\s+se\s+(?:voit|parle|reparle|appelle|rappelle|tient\s+au\s+courant|recontacte)"
    r"(?:\s+(?:demain|tantôt|bientôt|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    r"|ce\s+soir|cette\s+semaine|la\s+semaine\s+prochaine))?"
    # EN — "See you Monday/tomorrow/next week/..."
    r"|see\s+you\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|tomorrow|tonight|next\s+week|then|in\s+the\s+morning)"
    # EN — "Talk/Chat/Speak (to you) Monday/tomorrow/..."
    r"|(?:talk|chat|speak)\s+(?:to\s+you\s+)?"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next\s+week|then)"
    # EN — "Catch up Monday/.../next week"
    r"|catch\s+up\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next\s+week)"
    r")"
    r"\s*[!.…]?\s*$",  # end-anchor with optional terminal punctuation
    _re.IGNORECASE,
)


def _is_contextual_closing_line(line: str) -> bool:
    """Return True when `line` looks like a short conversational sign-off
    that should not stack with a canonical closing. Conservative — limits
    length + word count so body sentences containing similar phrases are
    not mistaken for a closing."""
    stripped = (line or "").strip()
    if not stripped or len(stripped) > 60:
        return False
    if len(stripped.split()) > 6:
        return False
    return bool(_CONTEXTUAL_CLOSING_RE.match(stripped))


def _strip_stacked_contextual_closing(draft: str) -> str:
    """Issue #592 — collapse a stacked contextual + canonical closing.

    Two patterns get cleaned up:

    1. Two distinct lines — the last line is a canonical sign-off and the
       previous non-blank line is a short contextual closing:
         "...body.\\n\\nÀ ce vendredi !\\n\\nÀ bientôt,"
         → "...body.\\n\\nÀ bientôt,"
    2. Same line — the canonical line carries a trailing contextual phrase
       after a comma:
         "À bientôt, à ce vendredi"
         → "À bientôt,"

    No-op when the last line is not a canonical closing — we never strip
    the user's only closing line, and never touch the body when only one
    closing is present.
    """
    if not draft:
        return draft

    lines = draft.split("\n")

    # Drop trailing blanks for analysis (re-attach when joining).
    trailing_blanks = 0
    while lines and not lines[-1].strip():
        lines.pop()
        trailing_blanks += 1
    if not lines:
        return draft

    last_idx = len(lines) - 1
    last_line = lines[last_idx]
    last_stripped = last_line.strip()
    last_clean = last_stripped.lower().rstrip(",.;:!")

    last_is_canonical = any(
        last_clean == c
        or last_clean.startswith(c + " ")
        or last_clean.startswith(c + ",")
        for c in _CLOSING_FORMULAS
    )
    if not last_is_canonical:
        return draft

    changed = False

    # Case 2 — same-line "X, contextual"
    comma_idx = last_stripped.find(",")
    if comma_idx > 0:
        head = last_stripped[: comma_idx + 1].rstrip()  # "À bientôt,"
        tail = last_stripped[comma_idx + 1 :].strip()  # "à ce vendredi"
        head_clean = head.lower().rstrip(",.;:!")
        head_is_canonical = any(
            head_clean == c or head_clean.startswith(c + " ")
            for c in _CLOSING_FORMULAS
        )
        if head_is_canonical and tail and _is_contextual_closing_line(tail):
            # Preserve original leading whitespace on the line.
            leading_ws = last_line[: len(last_line) - len(last_line.lstrip())]
            lines[last_idx] = leading_ws + head
            changed = True

    # Case 1 — line above the canonical is a contextual closing
    prev_idx = last_idx - 1
    while prev_idx >= 0 and not lines[prev_idx].strip():
        prev_idx -= 1
    if prev_idx >= 0 and _is_contextual_closing_line(lines[prev_idx]):
        # Drop the contextual line; collapse the now-double blank.
        del lines[prev_idx]
        # If we now have two consecutive blanks, drop one to keep a clean
        # body→blank→closing rhythm.
        if (
            prev_idx > 0
            and prev_idx < len(lines)
            and not lines[prev_idx - 1].strip()
            and not lines[prev_idx].strip()
        ):
            del lines[prev_idx]
        changed = True

    if not changed:
        return draft

    # Restore trailing blanks the original draft had after the closing.
    if trailing_blanks:
        lines.extend([""] * trailing_blanks)

    result = "\n".join(lines)
    # Collapse any stray triple blank we may have introduced.
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result


def _finalize_simple_draft(draft: str, closing_hint: str = "") -> str:
    """
    Minimal post-LLM cleanup for SIMPLE tier drafts.

    The SIMPLE tier returns templates or micro-replies without invoking an
    LLM, so most of the heavy cleanup pipeline (reasoning leakage, filler,
    parroting, etc.) is unnecessary. But defensive cleanup is still needed:

    - `_strip_a_confirmer`: templates should not contain `[À confirmer]` /
      `[TBD]` placeholders, but future changes could reintroduce them.
    - `_clean_prompt_leakage`: defensive — in case a template is fed LLM
      output upstream.
    - `_strip_markdown_artifacts`: strip stray `**` / `##` / leading `-`.
    - `_enforce_closing`: ensure a proper sign-off line.

    Without these, the SIMPLE tier could ship raw `[À confirmer]` markers or
    markdown artifacts directly to end users. All strips run under a single
    guard — any failure falls back to the untouched draft, which is still
    a safer default than propagating the exception up the tier router.
    """
    if not draft:
        return draft
    try:
        cleaned = _clean_prompt_leakage(draft)
        cleaned = _strip_markdown_artifacts(cleaned)
        cleaned = strip_reasoning_leakage(cleaned)
        cleaned = _strip_a_confirmer(cleaned)
        cleaned = strip_ai_dashes(cleaned)
        if closing_hint is not None:
            cleaned = _enforce_closing(cleaned, closing_hint)
        # Issue #592: collapse stacked contextual + canonical closings.
        cleaned = _strip_stacked_contextual_closing(cleaned)
        return cleaned
    except Exception as _err:
        logger.debug(f"_finalize_simple_draft: pipeline failed: {_err}")
        return draft


_HOT_THREAD_WINDOW_HOURS = 24


# ----------------------------------------------------------------------------
# Format enforcement telemetry — measures LLM disobedience rate to format
# rules. Aggregated in-memory counters, readable via get_enforce_stats().
# Use this data to iterate on prompt rules: a persistently high
# "greeting_fixed" rate means the model is ignoring our START WITH directive.
# ----------------------------------------------------------------------------
_ENFORCE_STATS: dict[str, int] = {
    "greeting_ok": 0,        # LLM produced the correct greeting
    "greeting_fixed": 0,     # Wrong/mismatched greeting, replaced
    "greeting_added": 0,     # No greeting at all, one was prepended
    "greeting_stripped": 0,  # Very-casual override, stripped LLM greeting
    "greeting_skipped": 0,   # Hot thread continuation — no greeting wanted
    "closing_ok": 0,         # Correct closing already present
    "closing_fixed": 0,      # Wrong closing, replaced (drafting)
    "closing_added": 0,      # No closing, appended
    "closing_preserved": 0,  # Existing closing kept (refine paths)
    "closing_stripped": 0,   # Very-casual override, stripped LLM closing
}


def get_enforce_stats() -> dict[str, int]:
    """Return a snapshot of the enforcement counters."""
    return dict(_ENFORCE_STATS)


def _bump(key: str) -> None:
    _ENFORCE_STATS[key] = _ENFORCE_STATS.get(key, 0) + 1


def _parse_history_date(raw: str):
    """
    Parse a date string from a conversation_history / thread_context entry.

    Handles both ISO-8601 (`2026-04-15T11:35:00+00:00`) and the
    whitespace-separated form Python's `str(datetime)` produces
    (`2026-04-15 11:35:00`). Returns None on failure.
    """
    if not raw or not isinstance(raw, str):
        return None
    from datetime import datetime as _dt
    # Normalize "YYYY-MM-DD HH:MM:SS..." → ISO by swapping the first space
    candidate = raw.strip()
    if 'T' not in candidate and ' ' in candidate:
        candidate = candidate.replace(' ', 'T', 1)
    # Python 3.11+ tolerates trailing "Z" in fromisoformat, earlier does not
    if candidate.endswith('Z'):
        candidate = candidate[:-1] + '+00:00'
    try:
        return _dt.fromisoformat(candidate)
    except (ValueError, TypeError):
        return None


def _is_hot_thread_continuation(
    thread_context: list[dict] | None,
    conversation_history: list[dict] | None,
    window_hours: int = _HOT_THREAD_WINDOW_HOURS,
) -> bool:
    """
    Decide whether the current email is part of an ongoing "hot" thread
    where re-greeting the contact would feel robotic.

    A thread is hot when there is at least one prior message (same
    thread_id via `thread_context`, or same sender via
    `conversation_history` as a fallback) whose date is less than
    `window_hours` ago.

    Returns False on any ambiguity — we only skip the greeting when we
    have strong evidence that a recent exchange already took place.
    """
    candidates: list[dict] = []
    if thread_context:
        candidates.extend(thread_context)
    if not candidates and conversation_history:
        # conversation_history is sender-scoped, so it's a weaker signal.
        # Only trust it when we have at least 2 entries (real back-and-forth)
        # to avoid skipping the greeting on a brand-new email from a known
        # contact.
        if len(conversation_history) >= 2:
            candidates.extend(conversation_history)

    if not candidates:
        return False

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    now = _dt.now(_tz.utc)
    cutoff = now - _td(hours=window_hours)

    for entry in candidates:
        raw_date = entry.get("date") if isinstance(entry, dict) else None
        parsed = _parse_history_date(raw_date or "")
        if parsed is None:
            continue
        # Normalize to UTC-aware for comparison
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_tz.utc)
        if parsed >= cutoff:
            return True

    return False


def _has_user_reply_instructions(instructions: str | None) -> bool:
    return bool(instructions and instructions.strip())


def _email_reply_greeting_formality(formality: int, instructions: str | None) -> int:
    """Keep user-triggered email replies from opening cold.

    ``formality == 1`` still means the body should stay very casual, but in a
    reply composer the user expects an email salutation. The no-greeting mode is
    reserved for automatic/hot-thread paths without explicit user instructions.
    """
    if _has_user_reply_instructions(instructions):
        return max(formality, 2)
    return formality


_EMAIL_HEADER_RE = _re.compile(
    r'^(?:De|From|À|To|Cc|Date|Sujet|Subject|Objet)\s*:\s*.+',
    _re.IGNORECASE,
)


def _clean_prompt_leakage(draft: str) -> str:
    """Remove prompt structure fragments that leaked into the output."""
    lines = draft.split('\n')

    # Strip echoed email headers at the top of the draft (De:, Date:, Sujet:, etc.)
    while lines:
        stripped = lines[0].strip()
        if not stripped:
            lines.pop(0)
            continue
        if _EMAIL_HEADER_RE.match(stripped):
            lines.pop(0)
            continue
        break

    # Cut at first "---" separator that appears after the greeting (model alternatives)
    for i, line in enumerate(lines):
        if i > 0 and line.strip() == '---':
            lines = lines[:i]
            break

    # Remove trailing empty lines and standalone placeholders
    while lines:
        last = lines[-1].strip()
        if not last or last == ',':
            lines.pop()
            continue
        # Standalone placeholder at end (not inline) — remove
        if last in ('[A confirmer]', '[To be confirmed]', '[À confirmer]', '[REDACTE]'):
            lines.pop()
            continue
        break

    # Strip trailing filler / meta-commentary (uses centralized _is_filler_line)
    while lines and _is_filler_line(lines[-1]):
        lines.pop()

    return '\n'.join(lines).strip()


def _strip_filler_mid_draft(draft: str, formality: int = 3) -> str:
    """
    Post-LLM pass: remove AI filler/meta-commentary anywhere in the draft.

    Uses centralized _is_filler_line for full-line detection,
    plus inline removal for filler phrases embedded in sentences.

    Args:
        formality: 1-5 score. If ≤ 2, casual filler ("Super!", "Let's go!") is preserved.
    """
    if not draft:
        return draft

    # Inline filler phrases to strip from within sentences
    _INLINE_STRIP = [
        "je reste à votre disposition", "je reste a votre disposition",
        "je reste à votre entière disposition", "je reste a votre entiere disposition",
        "n'hésitez pas à me contacter", "n'hesitez pas a me contacter",
        "n'hésitez pas si vous avez des questions", "n'hesitez pas si vous avez des questions",
        "n'hésitez pas", "n'hesitez pas",
        "feel free to reach out", "feel free to contact me",
        "don't hesitate to reach out", "don't hesitate to contact me",
        "please don't hesitate", "do not hesitate",
        "je me tiens à votre disposition", "je me tiens a votre disposition",
        "i remain at your disposal",
        # False empathy (#5)
        "i understand your frustration", "je comprends votre frustration",
        "je comprends ta frustration",
        "i understand how frustrating", "je comprends à quel point",
        "i know how annoying", "i can imagine how",
        "i'm sorry to hear that", "je suis désolé d'apprendre",
        "i'm sorry you're going through",
        # Corporate filler inline (#2)
        "i hope this helps", "j'espère que cela aide",
        "i hope this answers your question",
        "please let me know if you have any questions",
        "let me know if you need anything else",
        "if you have any questions", "si vous avez des questions",
        "si tu as des questions",
        "looking forward to hearing from you",
        "au plaisir de vous lire", "au plaisir de te lire",
        "i appreciate your patience", "j'apprécie votre patience",
        "i appreciate your understanding", "j'apprécie votre compréhension",
    ]

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Full-line filler or meta-commentary: skip entirely
        if _is_filler_line(stripped):
            # #10: Preserve casual filler at formality ≤ 2
            if formality <= 2:
                normalized = stripped.lower().rstrip("!.,;").strip()
                if normalized in _CASUAL_FILLER_OK or stripped.lower() in _CASUAL_FILLER_OK:
                    cleaned.append(stripped)
                    continue
            continue
        # Inline filler: remove the phrase from within the line
        modified = stripped
        for filler in _INLINE_STRIP:
            idx = modified.lower().find(filler)
            if idx != -1:
                before = modified[:idx].rstrip(' ,;.')
                after = modified[idx + len(filler):].lstrip(' ,;.!')
                modified = f"{before} {after}".strip() if before and after else (before or after).strip()
        # If the line became empty after stripping, skip it
        if not modified and stripped:
            continue
        cleaned.append(modified if stripped else line)

    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


_BARE_VOCATIVE_RE = _re.compile(
    r"^([A-ZÀ-ÖØ-Þ][\wà-öø-ÿ'\-]{1,20}(?:\s+[A-ZÀ-ÖØ-Þ][\wà-öø-ÿ'\-]{1,20})?)\s*[,.]?\s*$"
)


def _is_bare_name_vocative(line: str) -> bool:
    """Detect a short standalone name like 'Alexandre,' or 'Mme Martin.'.

    Used to strip redundant vocatives the LLM leaves right after its greeting
    (e.g. 'Bonjour Alexandre,\\nAlexandre,\\nJe voulais...').
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 30:
        return False
    return bool(_BARE_VOCATIVE_RE.match(stripped))


def _strip_duplicate_greetings(draft: str) -> str:
    """
    Post-LLM pass: remove duplicate greeting lines that appear mid-draft.

    Haiku sometimes generates a second greeting (e.g., "Hi Alexandre") after an
    initial "Hi DevOps,". Only the first greeting should remain; subsequent greeting
    lines are stripped. Also catches bare name vocatives ("Alexandre,") inserted
    between the main greeting and the body.
    """
    if not draft:
        return draft

    _greeting_starts = [
        'salut', 'bonjour', 'hello', 'hi ', 'hi,', 'hey', 'dear',
        'cher ', 'chere ', 'chère ', 'monsieur', 'madame',
        'm.', 'mr.', 'mr ', 'mrs.', 'mrs ', 'ms.', 'ms ',
        'dr.', 'dr ', 'mme.', 'mme ', 'prof.', 'prof ',
    ]

    lines = draft.split('\n')
    if len(lines) < 3:
        return draft

    # Find the first greeting line
    first_greeting_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped and any(stripped.startswith(g) for g in _greeting_starts):
            first_greeting_idx = i
            break

    if first_greeting_idx < 0:
        return draft

    cleaned = list(lines)

    # Pass 1: strip bare-name vocatives in the first 2 non-blank lines after the greeting.
    # Conservative: limited to the intro zone to avoid mangling lists or name-only body lines.
    vocative_checks = 0
    for i in range(first_greeting_idx + 1, len(lines)):
        if vocative_checks >= 2:
            break
        stripped_raw = lines[i].strip()
        if not stripped_raw:
            continue
        stripped_lower = stripped_raw.lower()
        if any(stripped_lower.startswith(g) for g in _greeting_starts):
            vocative_checks += 1
            continue
        if _is_bare_name_vocative(stripped_raw):
            cleaned[i] = ''
            vocative_checks += 1
            continue
        break  # First non-greeting non-vocative line = body has started

    # Pass 2: strip duplicate greeting words anywhere after the first greeting
    for i in range(first_greeting_idx + 1, len(lines)):
        stripped = lines[i].strip().lower()
        if not stripped:
            continue
        if any(stripped.startswith(g) for g in _greeting_starts):
            # This is a duplicate greeting — only remove if it's a short standalone line
            if len(lines[i].strip()) < 50:
                cleaned[i] = ''

    result = '\n'.join(cleaned)
    # Clean up extra blank lines left behind
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')
    return result.strip()


_LEGAL_KEYWORDS = _re.compile(
    r'\b(?:mise en demeure|demeure|procédures? judiciaires?|tribunal|poursuites?|avocat|'
    r'juridique|clause de non-concurrence|violation|infraction|litige|injonction|'
    r'propriété intellectuelle|droits? d\'auteur|compensation|vol de|copié|'
    r'assignation|assigne a comparaitre|assigné à comparaître|comparaitre|comparaître|'
    r'cour sup[eé]rieure|greffe|jugement par d[eé]faut|d[eé]faut de comparaitre|'
    r'legal notice|cease and desist|lawsuit|litigation|intellectual property|'
    r'subpoena|summons|court order|appear before)\b',
    _re.IGNORECASE
)

_LEGAL_RESPONSE_WORDS = _re.compile(
    r'\b(?:avocat|conseil juridique|conseiller juridique|lawyer|legal counsel|attorney)\b',
    _re.IGNORECASE
)


_DANGEROUS_LEGAL_PHRASES = [
    # French
    (r"(?:je\s+)?(?:vous\s+)?réponds?\s+en\s+acceptant\s+la\s+mise\s+en\s+demeure",
     "accuse réception de votre mise en demeure"),
    (r"j'accepte\s+(?:la|votre)\s+mise\s+en\s+demeure",
     "j'accuse réception de votre mise en demeure"),
    (r"(?:nous\s+)?acceptons?\s+(?:la|votre)\s+mise\s+en\s+demeure",
     "accusons réception de votre mise en demeure"),
    (r"j'accepte\s+(?:les?\s+)?(?:termes?|conditions?|demandes?|exigences?)",
     "j'ai pris note de vos demandes"),
    # English
    (r"I\s+accept\s+(?:the|your)\s+(?:legal\s+)?(?:demand|notice|terms)",
     "I acknowledge receipt of your notice"),
]


def _ensure_legal_caution(draft: str, body: str) -> str:
    """
    Post-LLM pass: if the email contains legal threats/keywords:
    1. Fix dangerous wording (accepter → accuser réception)
    2. If draft doesn't mention consulting a lawyer, append caution line.
    """
    if not body or not draft:
        return draft
    if not _LEGAL_KEYWORDS.search(body):
        return draft  # Not a legal email

    # Fix dangerous legal wording
    for pattern, replacement in _DANGEROUS_LEGAL_PHRASES:
        draft = _re.sub(pattern, replacement, draft, flags=_re.IGNORECASE)

    if _LEGAL_RESPONSE_WORDS.search(draft):
        return draft  # Already mentions lawyer

    # Detect language
    is_french = any(w in draft.lower() for w in _FR_DETECT_WORDS)
    if is_french:
        caution = "\n\nJe vais consulter mon avocat avant de répondre plus en détail sur le fond."
    else:
        caution = "\n\nI will consult with my legal counsel before providing a more detailed response."
    return draft.rstrip() + caution


_BLACKMAIL_KEYWORDS = _re.compile(
    r'\b(?:chantage|extorsion|journalistes?|presse|arrangement|notes? détaillées?|'
    r'indemnité de départ|sinon|menace|menacer|blackmail|extortion|threatening)\b',
    _re.IGNORECASE
)

_BLACKMAIL_DEMAND = _re.compile(
    r'(?:genre\s+\d+[KkMm$€]|\d+\s*(?:000|K)\s*[$€]|indemnité.*\d)', _re.IGNORECASE
)


def _detect_blackmail(draft: str, body: str) -> str:
    """
    Post-LLM pass: if email contains blackmail/extortion patterns,
    override the draft to never negotiate and redirect to lawyer.
    """
    if not body or not draft:
        return draft
    body.lower()
    # Need at least one blackmail keyword + a financial demand
    if not _BLACKMAIL_KEYWORDS.search(body):
        return draft
    if not _BLACKMAIL_DEMAND.search(body):
        return draft
    # Already mentions lawyer → OK
    if _LEGAL_RESPONSE_WORDS.search(draft):
        return draft
    # Detect language
    is_french = any(w in draft.lower() for w in _FR_DETECT_WORDS)
    if is_french:
        return draft.rstrip() + "\n\nJe transmets ce message à mon avocat."
    else:
        return draft.rstrip() + "\n\nI am forwarding this message to my legal counsel."


_FORWARDED_PATTERN = _re.compile(
    r'(?:forwarded message|message transféré|message transf[eé]r[eé])',
    _re.IGNORECASE
)


def _detect_misdirected(draft: str, body: str, sender: str) -> str:
    """
    Post-LLM pass: if email appears to be a forwarded internal document
    sent by mistake, override draft to inform sender of wrong delivery.
    Do NOT engage with confidential content.
    """
    if not body or not draft:
        return draft
    if not _FORWARDED_PATTERN.search(body):
        return draft
    # Check if there's an internal "De:/From:" + "À:/To:" in the forwarded block
    body_lower = body.lower()
    has_internal_headers = (
        ('de:' in body_lower or 'from:' in body_lower) and
        ('à:' in body_lower or 'to:' in body_lower or 'a:' in body_lower)
    )
    if not has_internal_headers:
        return draft
    # Check if the forwarded To: matches the sender (internal forward leaked out)
    # If the original To: is not the sender, this was likely misdelivered
    # Simple heuristic: if "confidentiel" or "confidential" in body, flag it
    if 'confidentiel' not in body_lower and 'confidential' not in body_lower:
        return draft
    # Detect language
    is_french = any(w in draft.lower() for w in _FR_DETECT_WORDS)
    # Extract sender first name for greeting
    greeting = ""
    if sender:
        parts = sender.strip().split()
        if parts:
            greeting = f"Bonjour {parts[0]},\n\n" if is_french else f"Hello {parts[0]},\n\n"
    if is_french:
        return (
            f"{greeting}Il semble que cet email m'ait été envoyé par erreur. "
            "Je n'ai pas pris connaissance de son contenu.\n\n"
            "Je vous laisse le soin de le renvoyer au bon destinataire."
        )
    else:
        return (
            f"{greeting}It appears this email was sent to me by mistake. "
            "I have not reviewed its contents.\n\n"
            "Please resend it to the intended recipient."
        )


def _clean_language_artifacts(draft: str) -> str:
    """
    Post-LLM pass: remove English artifacts (YES, NO) appearing in French drafts.
    Haiku sometimes inserts YES/NO mid-text in French responses.
    """
    if not draft:
        return draft
    # Only apply to French drafts
    is_french = any(w in draft.lower() for w in _FR_DETECT_WORDS)
    if not is_french:
        return draft
    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Remove standalone "YES," or "YES" or "NO," lines
        if stripped.upper() in ('YES,', 'YES', 'YES.', 'NO,', 'NO', 'NO.'):
            continue
        # Remove "YES, " at start of sentence (e.g. "YES, nous examinerons...")
        if stripped.startswith('YES, ') or stripped.startswith('YES,'):
            line = stripped[4:].strip().capitalize() if len(stripped) > 4 else ''
        elif stripped.startswith('NO, ') or stripped.startswith('NO,'):
            line = stripped[3:].strip().capitalize() if len(stripped) > 3 else ''
        cleaned.append(line)
    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


_SENSITIVE_ASSET_REQUEST = _re.compile(
    r'\b(?:codebase|code source|source code|repo|repository|training data|datasets?|'
    r'proprietary|propriétaire|accès complet|full access|NDA|données d\'entraînement)\b',
    _re.IGNORECASE
)

_ACCEPT_SHARING_PATTERNS = _re.compile(
    r'\b(?:i accept|i agree|je confirme|j\'accepte|i acknowledge|'
    r'provide full access|fournir l\'accès|proceed with)\b',
    _re.IGNORECASE
)


def _detect_social_engineering(draft: str, body: str) -> str:
    """
    Post-LLM pass: if email requests sensitive assets (codebase, datasets, NDA)
    and draft appears to accept, override with a refusal.
    """
    if not body or not draft:
        return draft
    # Only trigger if body asks for sensitive assets
    if not _SENSITIVE_ASSET_REQUEST.search(body):
        return draft
    # Only override if draft seems to accept/comply
    if not _ACCEPT_SHARING_PATTERNS.search(draft):
        return draft
    # Detect language
    is_french = any(w in body.lower() for w in _FR_DETECT_FORMAL)
    if is_french:
        return (
            "Bonjour,\n\n"
            "Je vous remercie de votre intérêt, mais nous ne sommes pas en mesure "
            "de partager notre code source, nos données propriétaires ou de signer "
            "un NDA dans ces conditions.\n\n"
            "Si vous souhaitez explorer un partenariat, je vous invite à passer "
            "par les canaux officiels."
        )
    else:
        return (
            "Hello,\n\n"
            "Thank you for your interest, but we are unable to share our codebase, "
            "proprietary datasets, or sign an NDA under these conditions.\n\n"
            "If you would like to explore a partnership, please reach out through "
            "official channels."
        )


def _strip_leading_parrot(draft: str, body: str) -> str:
    """
    Lightweight parroting check for short bodies (< 300 chars).
    Only removes lines at the START of the draft that are near-copies of the body.
    """
    if not draft or not body:
        return draft
    body_lower = body.strip().lower()
    lines = draft.split('\n')
    cleaned = []
    stripping = True
    for line in lines:
        stripped = line.strip().lower()
        if stripping and stripped and len(stripped) >= 15:
            # Check if this line is a near-copy of the body or part of it
            if stripped in body_lower or body_lower.startswith(stripped):
                continue  # skip this parroted line
        if stripped:
            stripping = False  # stop stripping after first non-parrot content
        cleaned.append(line)
    result = '\n'.join(cleaned).strip()
    # Safety: don't return empty
    if len(result) < 10:
        return draft
    return result


# ── Module-level constants for _strip_parroting (avoid per-call allocation) ──
_PARROTING_STOP_WORDS = frozenset([
    'les', 'des', 'une', 'que', 'qui', 'est', 'dans', 'pour', 'avec',
    'par', 'sur', 'pas', 'plus', 'son', 'ses', 'aux', 'the', 'and',
    'for', 'you', 'your', 'with', 'this', 'that', 'are', 'was', 'not',
    'have', 'has', 'will', 'been', 'from', 'but', 'our', 'all', 'also',
    'nous', 'vous', 'votre', 'vos', 'mon', 'mes', 'ces', 'comme',
])

_PARROTING_ACTION_STARTS = _re.compile(
    r'^(?:'
    r"(?:je|j'|nous)\s+(?:vais|confirme|accepte|refuse|prépare|envoie|vérifie|transmets|"
    r"m'occupe|vous (?:remercie|informe|confirme|contacte|envoie|transmets|propose)|"
    r"suis (?:disponible|prêt|d'accord|intéressé|ouvert))|"
    r"(?:i(?:'ll| will| am| can| would| have| accept| confirm| decline| agree))|"
    r"(?:we(?:'ll| will| are| can| have| accept| confirm))|"
    r"(?:yes|oui|d'accord|entendu|parfait|bien reçu|merci)"
    r')',
    _re.IGNORECASE,
)


def _strip_parroting(draft: str, body: str) -> str:
    """
    Post-LLM pass: structural ACTION/ECHO/NOVEL scoring.

    Classifies each draft sentence:
      ACTION    = starts with "I will", "Je vais", "Je confirme", etc. → KEEP
      REFERENCE = contains body date/name inside an action → KEEP (max 2)
      ECHO      = >60% words from body, no action verb → REMOVE
      NOVEL     = <20% words from body → KEEP (hallucination check elsewhere)

    Also detects list echo: if body has N enumerated items and draft
    repeats >60% of them, compresses to summary.
    """
    if not body or not draft:
        return draft

    body_lower = body.lower().strip()

    # ── Extract body word set (for coverage scoring) ──
    body_words = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', body_lower))
    # Remove stop words from body word set (use module-level constant)
    body_words -= _PARROTING_STOP_WORDS

    # ── Extract enumerated list items from body (P2 — list detection) ──
    list_items = _re.findall(
        r'(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•*]\s+)(.+)',
        body, _re.MULTILINE,
    )
    list_item_words = []
    for item in list_items:
        words = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', item.lower())) - _PARROTING_STOP_WORDS
        if words:
            list_item_words.append(words)

    # ── Extract body questions (for echo detection) ──
    body_questions = set()
    for part in body_lower.split('?'):
        q = part.strip().rstrip('?!.').strip()
        if len(q) >= 12:
            body_questions.add(q)

    # ── Classify each line ──
    lines = draft.split('\n')
    classified = []  # (line, tag)
    ref_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            classified.append((line, 'BLANK'))
            continue

        stripped_lower = stripped.lower()
        line_words = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', stripped_lower)) - _PARROTING_STOP_WORDS

        # Check if line is an action
        is_action = bool(_PARROTING_ACTION_STARTS.search(stripped_lower))

        # Check word overlap with body
        if line_words:
            overlap = len(line_words & body_words) / len(line_words)
        else:
            overlap = 0.0

        # Check if line echoes a body question
        is_question_echo = False
        if stripped.endswith('?'):
            for bq in body_questions:
                if bq in stripped_lower:
                    coverage = len(bq) / max(len(stripped_lower.rstrip('?!. ')), 1)
                    if coverage > 0.50:
                        is_question_echo = True
                        break

        # Classification
        if is_question_echo:
            classified.append((line, 'ECHO'))
        elif is_action:
            if overlap > 0.5:
                ref_count += 1
                classified.append((line, 'REFERENCE' if ref_count <= 2 else 'ECHO'))
            else:
                classified.append((line, 'ACTION'))
        elif overlap > 0.6 and len(stripped) >= 20:
            classified.append((line, 'ECHO'))
        elif len(stripped_lower) >= 15:
            # Check exact substring containment
            clean_lower = stripped_lower.rstrip('?!., ')
            if clean_lower in body_lower and len(clean_lower) >= 20:
                classified.append((line, 'ECHO'))
            else:
                classified.append((line, 'NOVEL'))
        else:
            classified.append((line, 'KEEP'))

    # ── P2: List echo compression ──
    if len(list_item_words) >= 3:
        # Count how many list items are echoed in draft
        echoed_count = 0
        for item_words in list_item_words:
            for line, tag in classified:
                line_words_l = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', line.lower())) - _PARROTING_STOP_WORDS
                if item_words and line_words_l:
                    item_overlap = len(item_words & line_words_l) / len(item_words)
                    if item_overlap > 0.5:
                        echoed_count += 1
                        break

        if echoed_count / len(list_item_words) > 0.6:
            # Too many list items echoed → mark all ECHO lines for removal
            # They will be filtered out below, and the summary is already
            # in the ACTION lines (e.g., "I acknowledge receipt")
            pass  # ECHOs already tagged, will be removed

    # ── Build result: keep ACTION, REFERENCE, NOVEL, BLANK; drop ECHO ──
    cleaned = []
    for line, tag in classified:
        if tag != 'ECHO':
            cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    # Collapse multiple blank lines
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')

    # Safety: don't return empty/too-short
    if len(result) < 20:
        return draft
    return result


def _truncate_for_short_body(
    draft: str, body: str, user_context: str = "",
) -> str:
    """
    Post-LLM pass: if the original email body is short (<100 chars),
    truncate the draft to prevent AI filler/hallucination.
      - <50 chars  → greeting + 1 sentence max
      - 50-99 chars → greeting + 2 sentences max

    When `user_context` is non-empty (user passed notes via the /expand
    flow), skip truncation entirely — the source-body length no longer
    predicts the intended reply length, and aggressively truncating
    would strip the very content the user asked the AI to expand on.
    See 2026-05-13 stress test, Bug B.
    """
    if not body or not draft:
        return draft

    # User-provided notes override the short-source heuristic.
    if user_context and user_context.strip():
        return draft

    body_clean = (body or "").strip()
    if len(body_clean) >= 100:
        return draft  # Not short, no truncation

    max_content = 1 if len(body_clean) < 50 else 2

    # Keep only the greeting + max_content content sentences
    lines = draft.split('\n')
    result_lines = []
    content_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result_lines.append(line)
            continue
        result_lines.append(line)
        # Check if this line looks like a greeting (short, ends with comma)
        if stripped.endswith(',') and len(stripped) < 40:
            continue  # This is the greeting, keep going
        content_count += 1
        if content_count >= max_content:
            break

    result = '\n'.join(result_lines).strip()
    # Safety: if truncation left only a greeting (no content), return full draft
    if content_count == 0:
        return draft
    return result


def _strip_technical_echo(draft: str, body: str) -> str:
    """
    Post-LLM pass: when a draft sentence echoes specific technical details from
    the body (file paths, line numbers), simplify it to the confirmation intent.

    Haiku tends to repeat file names, line references, and technical terms back
    to the sender. A human wouldn't — the sender already knows what they asked.

    Example:
      Body:  "Can you look at worker/email_parser.py lines 145-180?"
      Draft: "I'll take a look at worker/email_parser.py lines 145-180 and add cleanup."
      Fixed: "I'll take a look."
    """
    if not body or not draft:
        return draft

    # Extract file paths from body (anything with a code file extension)
    _file_ext = r'\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|cpp|c|h|cs|php|sh|yml|yaml|json|xml|html|css|sql|md)\b'
    body_files = set(m.lower() for m in re.findall(r'[\w./\\-]+' + _file_ext, body, re.IGNORECASE))

    # Extract line number references from body (EN "lines" + FR "lignes")
    body_line_refs = set(m.lower() for m in re.findall(r'(?:lines?|lignes?)\s+\d+(?:\s*[-\u2013]\s*\d+)?', body, re.IGNORECASE))

    if not body_files and not body_line_refs:
        return draft

    # Confirm phrases → suffix to complete the sentence naturally
    # Sorted longest-first so greedy matching works correctly.
    _CONFIRM_PAIRS = [
        # EN
        ("i'll take a look", "."),
        ("i will take a look", "."),
        ("i'll look into it", "."),
        ("i'll look into", " it."),
        ("i'll check it out", "."),
        ("i'll check on it", "."),
        ("i'll check on", " it."),
        ("i'll look at it", "."),
        ("i'll look at", " it."),
        ("i will look at", " it."),
        ("i'll check", " on it."),
        ("i will check", " on it."),
        ("i'll review", " it."),
        ("i will review", " it."),
        ("i'll investigate", "."),
        ("i will investigate", "."),
        ("i'll handle", " it."),
        ("i will handle", " it."),
        ("i'll fix", " it."),
        ("i will fix", " it."),
        # FR
        ("je vais regarder", " ça."),
        ("je regarde", " ça."),
        ("je vais vérifier", " ça."),
        ("je vérifie", " ça."),
        ("je vais checker", " ça."),
        ("je m'en occupe", "."),
        ("je vais m'en occuper", "."),
        ("je vais y jeter un oeil", "."),
        ("je vais y jeter un œil", "."),
    ]

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        stripped_lower = stripped.lower()
        has_file = any(fp in stripped_lower for fp in body_files)
        has_line = any(lr in stripped_lower for lr in body_line_refs)

        if not has_file and not has_line:
            cleaned.append(line)
            continue

        # This line echoes body technical details → simplify to confirm phrase
        replaced = False
        for pattern, suffix in _CONFIRM_PAIRS:
            idx = stripped_lower.find(pattern)
            if idx != -1:
                prefix = stripped[:idx + len(pattern)]
                new_line = prefix + suffix
                cleaned.append(new_line)
                replaced = True
                break

        if not replaced:
            # No confirm phrase — keep line as-is (conservative)
            cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


# ── Module-level patterns for _scrub_hallucinated_facts (avoid per-call compile) ──
_HALLUCINATED_PRICE_RE = _re.compile(
    r'(\d[\d\s,.]*)\s*'
    r'(euros?|eur|\$|usd|cad|£|gbp|€'
    r'|/(?:mois|month|user|utilisateur|an|year)'
    r'|(?:requests?\s+per\s+minute|req/min|requêtes?\s+par\s+minute))',
    _re.IGNORECASE,
)
_HALLUCINATED_DOLLAR_RE = _re.compile(
    r'\$\s*(\d[\d\s,.]*[MmKkBb]?\b)',
    _re.IGNORECASE,
)
_HALLUCINATED_PCT_RE = _re.compile(
    r'(\d[\d\s,.]*)\s*%',
)


def _scrub_hallucinated_facts(draft: str, body: str) -> str:
    """
    Post-LLM pass: detect and replace likely hallucinated numbers/prices
    that were NOT present in the original email body.

    Catches patterns like "500 EUR", "100 requests per minute", "25$/user".
    Replaces with [A confirmer] or [To be confirmed] based on draft language.
    """
    # Detect draft language for correct placeholder
    draft_lower = draft.lower()
    fr_words = sum(1 for w in [' le ', ' la ', ' les ', ' des ', ' est ', ' je ', ' tu ', ' nous '] if w in draft_lower)
    en_words = sum(1 for w in [' the ', ' is ', ' are ', ' we ', ' our ', ' my ', ' will '] if w in draft_lower)
    placeholder = "[A confirmer]" if fr_words >= en_words else "[To be confirmed]"

    body_lower = (body or "").lower()

    # Extract all numbers from the original body for comparison
    body_numbers = set(_re.findall(r'\d[\d\s,.]*\d|\d+', body_lower))
    # Normalize: remove spaces/dots in numbers for flexible matching
    body_numbers_clean = set()
    for n in body_numbers:
        body_numbers_clean.add(n.strip())
        body_numbers_clean.add(n.replace(' ', '').replace('.', '').replace(',', '').strip())

    def _number_in_body(number_str: str) -> bool:
        """Check if a number was present in the original email (word-boundary match)."""
        n = number_str.strip()
        n_clean = n.replace(' ', '').replace('.', '').replace(',', '')
        # Use word-boundary regex to avoid "25" matching inside "825"
        if _re.search(r'(?<!\d)' + _re.escape(n) + r'(?!\d)', body_lower):
            return True
        if n_clean and n_clean in body_numbers_clean:
            return True
        return False

    def _replacement(m: _re.Match) -> str:
        full = m.group(0).strip()
        if full.lower() in body_lower:
            return full
        number = m.group(1).strip()
        if _number_in_body(number):
            return full
        return placeholder

    result = _HALLUCINATED_PRICE_RE.sub(_replacement, draft)

    # Scrub $X.XM patterns not from body
    def _dollar_replacement(m: _re.Match) -> str:
        full = m.group(0).strip()
        if full.lower() in body_lower:
            return full
        number = m.group(1).strip().rstrip('MmKkBb')
        if _number_in_body(number):
            return full
        return placeholder

    result = _HALLUCINATED_DOLLAR_RE.sub(_dollar_replacement, result)

    # Scrub percentages not from body
    def _pct_replacement(m: _re.Match) -> str:
        full = m.group(0).strip()
        if full in body_lower or full.lower() in body_lower:
            return full
        number = m.group(1).strip()
        if _number_in_body(number):
            return full
        return placeholder

    result = _HALLUCINATED_PCT_RE.sub(_pct_replacement, result)

    return result


# ── P3: Hallucinated context & status detection ──────────────────────────

# False context references — phrases that imply prior agreement/discussion
_FALSE_CONTEXT_PATTERNS = _re.compile(
    r'(?:'
    r'comme (?:convenu|discuté|mentionné|prévu|évoqué|indiqué)'
    r'|suite [àa] (?:notre|nos|votre) (?:appel|discussion|conversation|rencontre|échange|entretien)'
    r'|(?:as|like) (?:we )?(?:discussed|agreed|mentioned|talked about|spoke about)'
    r'|per our (?:conversation|discussion|call|meeting|agreement)'
    r'|following (?:up on )?our (?:conversation|discussion|call|meeting)'
    r'|nous avions (?:convenu|discuté|prévu|établi)'
    r'|on avait (?:convenu|discuté|prévu|dit|parlé)'
    r'|(?:dans|lors de) notre (?:précédente?|dernière?) (?:conversation|discussion|rencontre)'
    r')',
    _re.IGNORECASE,
)

# Invented status changes — verbs that flip a state without evidence
_STATUS_FLIP_PATTERNS = [
    # (pattern_in_draft, conflicting_body_pattern) — if body has the conflict, draft is hallucinating
    (_re.compile(r'\b(?:résolu|réglé|corrigé|fixé|resolved|fixed|corrected)\b', _re.IGNORECASE),
     _re.compile(r'\b(?:problème|bug|erreur|panne|issue|error|broken|down|bloqué|blocked)\b', _re.IGNORECASE)),
    (_re.compile(r'\b(?:envoyé|transmis|sent|delivered|forwarded)\b', _re.IGNORECASE),
     _re.compile(r'\b(?:en attente|pending|waiting|attendons|awaiting)\b', _re.IGNORECASE)),
    (_re.compile(r'\b(?:terminé|complété|fini|completed|finished|done)\b', _re.IGNORECASE),
     _re.compile(r'\b(?:en cours|in progress|ongoing|working on)\b', _re.IGNORECASE)),
]


def _scrub_hallucinated_context(draft: str, body: str, has_history: bool = False) -> str:
    """
    Post-LLM pass: detect and remove two types of non-numeric hallucinations:

    1. False context references ("comme convenu", "as discussed") when there is
       no conversation history to justify them.
    2. Invented status flips ("résolu" when body says "problème", "sent" when
       body says "pending").
    """
    if not draft or not body:
        return draft

    body_lower = body.lower()

    # ── 1. False context references ──
    if not has_history:
        # No conversation history → any "as discussed" / "comme convenu" is hallucinated
        lines = draft.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if stripped and _FALSE_CONTEXT_PATTERNS.search(stripped):
                # Remove the false context phrase from the line
                cleaned_line = _FALSE_CONTEXT_PATTERNS.sub('', stripped).strip()
                # Clean up leftover punctuation/connectors
                cleaned_line = _re.sub(r'^[,;\s]+', '', cleaned_line)
                cleaned_line = _re.sub(r'\s*,\s*,', ',', cleaned_line)
                if cleaned_line and len(cleaned_line) >= 5:
                    # Capitalize first letter
                    cleaned_line = cleaned_line[0].upper() + cleaned_line[1:]
                    cleaned.append(cleaned_line)
                # else: line was entirely a false context → drop it
            else:
                cleaned.append(line)
        draft = '\n'.join(cleaned)

    # ── 2. Status flip detection ──
    for draft_pattern, body_conflict in _STATUS_FLIP_PATTERNS:
        if draft_pattern.search(draft) and body_conflict.search(body_lower):
            # Draft claims something is resolved but body says it's broken
            # Remove the offending sentence
            lines = draft.split('\n')
            cleaned = []
            for line in lines:
                if draft_pattern.search(line) and len(line.strip()) < 120:
                    continue  # Drop the status-flip line
                cleaned.append(line)
            draft = '\n'.join(cleaned)

    # Safety
    result = draft.strip()
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')
    return result if len(result) >= 10 else draft


# ── #1: Hedging/uncertainty stripper ───────────────────────────────────────

_HEDGING_RE = _re.compile(
    r'\b(?:'
    r'i think\s+(?:that\s+)?'
    r"|i believe\s+(?:that\s+)?"
    r"|it (?:might|could)\s+(?:be\s+)?"
    r"|it (?:seems?|appears?)\s+(?:that\s+|to\s+|like\s+)?"
    r"|perhaps\s+"
    r"|maybe\s+"
    r"|possibly\s+"
    r"|hopefully[\s,]+"
    r"|if i understand correctly[,\s]+"
    r"|i'?m not (?:entirely |completely |totally )?sure[,\s]+(?:but\s+)?"
    r"|je pense que\s+"
    r"|je crois que\s+"
    r"|il me semble que\s+"
    r"|peut-[eê]tre\s+(?:que\s+)?"
    r"|il se pourrait que\s+"
    r"|si j'ai bien compris[,\s]+"
    r")",
    _re.IGNORECASE,
)


def _strip_hedging(draft: str) -> str:
    """
    Post-LLM pass (#1): remove hedging/uncertainty qualifiers.

    'I think the price is $50' → 'The price is $50'
    'Perhaps we could meet' → 'We could meet'
    'Je pense que c'est bon' → 'C'est bon'
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        modified = _HEDGING_RE.sub('', stripped)
        # Capitalize first char after hedge removal
        modified = modified.lstrip(' ,;')
        if modified and modified[0].islower():
            modified = modified[0].upper() + modified[1:]
        cleaned.append(modified if modified else line)
    return '\n'.join(cleaned)


# ── #3b: "[À confirmer]" marker stripper ─────────────────────────────────

_A_CONFIRMER_RE = _re.compile(
    # Bracketed placeholders (FR + EN, accented + non-accented).
    # Per-2026-04-24 audit (failure-mode #7): the previous regex missed a
    # large family of LLM-emitted markers, leaving raw placeholders in user-
    # facing drafts. The expanded alternation now covers the variants we
    # observed leaking through.
    r'\s*\[[^\]]*confirmer[^\]]*\]'        # [À confirmer], [À confirmer - date...]
    r'|\s*\[[^\]]*valider[^\]]*\]'         # [À valider - x]
    r'|\s*\[[^\]]*v[ée]rifier[^\]]*\]'     # [à vérifier], [À VERIFIER], [verifier]
    r'|\s*\[[^\]]*compl[ée]ter[^\]]*\]'    # [à compléter], [À completer]
    r'|\s*\[[^\]]*to verify[^\]]*\]'       # [to verify], [TO VERIFY: amount]
    r'|\s*\[[^\]]*to confirm[^\]]*\]'      # [to confirm date]
    r'|\s*\[[^\]]*to complete[^\]]*\]'     # [to complete with X]
    r'|\s*\[[^\]]*placeholder[^\]]*\]'     # [PLACEHOLDER], [placeholder: name]
    r'|\s*\[[^\]]*todo[^\]]*\]'            # [TODO], [todo: insert price]
    r'|\s*\[[^\]]*to be (?:filled|added|provided|determined)[^\]]*\]'  # [TO BE FILLED]
    r'|\s*\[[^\]]*[àa] (?:remplir|ajouter|pr[ée]ciser|d[ée]finir)[^\]]*\]'  # [à remplir], [à préciser]
    r'|\s*\[To be confirmed[^\]]*\]'
    r'|\s*\[TBD\]'
    r'|\s*\[TBA\]'                         # [TBA] = to be announced
    r'|\s*\[FIXME[^\]]*\]'
    r'|\s*\[XXX\]'
    r'|\s*\[REDACTE\]'
    r'|\s*\[REDACTED\]'
    # Bare-phrase markers (without brackets) — anchored on word boundary.
    r'|\s*[ÀàAa] confirmer(?!\w)'
    r'|\s*[ÀàAa] valider(?!\w)'
    r'|\s*[ÀàAa] v[ée]rifier(?!\w)'
    r'|\s*[ÀàAa] compl[ée]ter(?!\w)'
    r'|\s*[ÀàAa] pr[ée]ciser(?!\w)'
    r'|\s*[ÀàAa] remplir(?!\w)'
    r'|\s*to be (?:confirmed|verified|completed|filled|added|determined)(?!\w)',
    _re.IGNORECASE,
)

# Cheap pre-check for the fast-path inside `_strip_a_confirmer`. If a draft
# contains none of these substrings (and no `[`), we can skip the regex
# entirely. Order matches the bare-phrase alternation in `_A_CONFIRMER_RE`.
_BARE_PLACEHOLDER_TRIGGER_RE = _re.compile(
    r'(?:[àaA] (?:confirmer|valider|v[ée]rifier|compl[ée]ter|pr[ée]ciser|remplir)'
    r'|to be (?:confirmed|verified|completed|filled|added|determined))',
    _re.IGNORECASE,
)


_CLARIFICATION_PATTERNS = _re.compile(
    r"(je remarque une confusion|il n'y a pas de r[eé]ponse [àa] r[eé]diger"
    r"|pourriez.vous clarifier|pourriez.vous pr[eé]ciser|could you clarify"
    r"|pouvez.vous clarifier|veuillez pr[eé]ciser|please clarify"
    r"|peux.tu clarifier|peux.tu pr[eé]ciser|can you clarify"
    r"|je ne peux pas r[eé]diger|je suis incapable de r[eé]diger"
    r"|qui est le destinataire|who is the recipient"
    r"|il semble y avoir une confusion|there seems to be a confusion"
    r"|je ne dois pas r[eé]pondre|je dois clarifier"
    r"|(?:cet? )?email ne n[eé]cessite (?:pas )?(?:de |une )?r[eé]ponse"
    r"|il n.y a rien [àa] r[eé]pondre|there.s nothing to (?:reply|respond)"
    r"|aucune (?:demande|question|action) (?:claire )?(?:n.est |n.a [eé]t[eé] )?(?:pos[eé]e|demand[eé]e|identifi[eé]e|identifiable|requise)"
    r"|no reply (?:is )?needed|no response (?:is )?(?:needed|required|necessary)"
    r"|this email does(?:n't| not) require a (?:reply|response)"
    r"|toute r[eé]ponse (?:serait|violerait)"
    r"|il ne convient pas de r[eé]pondre"
    r"|(?:il s'agit|c'est) d'un(?:e)? (?:newsletter|notification|courriel automatique|email automatique|infolettre)"
    r"|ne n[eé]cessite? (?:pas |aucune )?r[eé]ponse)",
    _re.IGNORECASE,
)

def _strip_clarification_draft(draft: str) -> str:
    """
    Post-LLM safety net: if the draft is a clarification request instead of
    an actual email, return empty string so the pipeline can handle it gracefully.
    """
    if not draft:
        return draft
    # If the draft contains clarification patterns, it leaked agent reasoning
    if _CLARIFICATION_PATTERNS.search(draft):
        return ""
    return draft


def _strip_a_confirmer(draft: str) -> str:
    """
    Post-LLM pass: remove "[À confirmer]" / "À valider" / "[à vérifier]" /
    "[TODO]" / "[placeholder]" markers from the draft.

    Fast-path: skip the full line-by-line loop if the draft contains
    none of the trigger characters/keywords. We must guard both the
    bracket family ("[...]") and the bare-phrase family ("à vérifier",
    "to be confirmed", etc.) — the previous fast-path checked only `[`,
    so bracket-less placeholders like "Le rendez-vous est à vérifier."
    silently bypassed the regex (audit failure-mode #7, 2026-04-24).
    """
    if not draft:
        return draft
    # Cheap broad-pass detection: bracket OR any known bare-phrase trigger.
    # The substring scan is O(n) but ~10x faster than the full regex
    # apply on long, placeholder-free drafts (the common case).
    if "[" not in draft and not _BARE_PLACEHOLDER_TRIGGER_RE.search(draft):
        return draft

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        modified = _A_CONFIRMER_RE.sub('', line)
        # Clean up trailing punctuation artifacts: "data . " → "data."
        modified = _re.sub(r'\s+([.,;:!?])', r'\1', modified)
        # Remove lines that became empty or just punctuation after stripping
        stripped = modified.strip()
        if stripped and stripped not in ('.', ',', ';', ':', '-', '—'):
            cleaned.append(modified)
        elif not line.strip():
            cleaned.append(line)  # Preserve blank lines
    return '\n'.join(cleaned)


# ── #4: Subject-line echo stripper ────────────────────────────────────────

def _strip_subject_echo(draft: str, subject: str) -> str:
    """
    Post-LLM pass (#4): remove opening line that echoes the email subject.

    Subject: 'Meeting reschedule?'
    Draft: 'Regarding the meeting reschedule, ...' → line removed
    """
    if not draft or not subject:
        return draft

    _STOP = frozenset([
        'the', 'and', 'for', 'les', 'des', 'une', 'que', 'pour', 'avec',
        'this', 'that', 'your', 'our', 'ton', 'votre', 'mon',
    ])
    subject_words = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', subject.lower())) - _STOP
    if len(subject_words) < 2:
        return draft

    lines = draft.split('\n')
    _echo_prefixes = [
        'regarding', 'concerning', 'about the', 'about your',
        'en ce qui concerne', 'au sujet de', 'à propos de', 'a propos de',
        'pour ce qui est de', 'concernant',
    ]

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip greeting lines (short, ends with comma)
        if stripped.endswith(',') and len(stripped) < 50:
            continue
        # Check if line starts with subject-echo prefix AND has high overlap
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _echo_prefixes):
            line_words = set(_re.findall(r'\b[a-zà-ÿ]{3,}\b', lower)) - _STOP
            if line_words and len(subject_words & line_words) / len(subject_words) > 0.4:
                lines[i] = ''
        break  # Only check first content line

    result = '\n'.join(lines).lstrip('\n')
    return result if len(result.strip()) >= 10 else draft


# ── #6: Language mid-drift detector ───────────────────────────────────────

def _detect_language_drift(draft: str, expected_language: str) -> str:
    """
    Post-LLM pass (#6): remove sentences in the wrong language.

    E.g., in a French draft: 'Bonjour, ... By the way, here's the code. Merci.'
    → removes the English sentence.
    """
    if not draft or not expected_language:
        return draft

    _EN_MARKERS = [' the ', ' is ', ' are ', ' i ', ' my ', ' you ', ' we ', ' will ', ' have ']
    _FR_MARKERS = [' le ', ' la ', ' les ', ' je ', ' tu ', ' nous ', ' est ', ' des ', ' une ']

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 20:
            cleaned.append(line)
            continue

        padded = f' {stripped.lower()} '
        en_score = sum(1 for w in _EN_MARKERS if w in padded)
        fr_score = sum(1 for w in _FR_MARKERS if w in padded)

        # Only drop if strong signal of wrong language (≥3 markers difference)
        if expected_language == "FRENCH" and en_score > fr_score + 2 and en_score >= 3:
            continue  # Drop English line in French draft
        elif expected_language == "ENGLISH" and fr_score > en_score + 2 and fr_score >= 3:
            continue  # Drop French line in English draft

        cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    if len(result) < 10:
        result = draft

    # The line-drop pass above skips short lines (< 20 chars), so a one-word
    # sign-off in the wrong language — e.g. "Merci," at the end of an English
    # reply — slips through. Deterministically rewrite that trailing closing to
    # the expected language (2026-06-23, same root cause as the compose path).
    _closing_lang = {"ENGLISH": "en", "FRENCH": "fr"}.get(
        str(expected_language).upper()
    )
    if _closing_lang:
        try:
            from app.prompts.identity import normalize_closing_to_language
            result = normalize_closing_to_language(result, _closing_lang)
        except Exception:
            pass
    return result


# ── #9: Unnecessary questions stripper ────────────────────────────────────

_UNNECESSARY_Q_RE = _re.compile(
    r'^(?:'
    r"(?:would|do|did) you (?:like|want|mean|prefer|need) "
    r"|(?:just |)(?:to clarify|to confirm)[,:\s]"
    r"|(?:shall|should) (?:i|we) "
    r"|(?:est-ce que |)(?:tu |vous )(?:vou(?:drais|lez)|préfère[sz]?|souhait[ez]) "
    r"|si (?:tu |vous )(?:voul|préfér|souhait)"
    r"|n'est-ce pas"
    r"|(?:is|are) (?:you|there) (?:sure|certain|available|ok|okay|interested)"
    r"|any (?:other |)questions"
    r"|avez.vous (?:des |d'autres )questions"
    r"|as.tu (?:des |d'autres )questions"
    r").*\?$",
    _re.IGNORECASE,
)


def _strip_unnecessary_questions(draft: str, body: str) -> str:
    """
    Post-LLM pass (#9): remove questions the LLM added that the sender didn't ask.

    Compares ? count in body vs draft. If draft adds significantly more,
    strips LLM-invented clarification/follow-up questions.
    """
    if not draft or not body:
        return draft

    body_questions = body.count('?')
    draft_questions = draft.count('?')

    # Allow max 1 added question
    if draft_questions <= body_questions + 1:
        return draft

    max_to_remove = draft_questions - body_questions - 1
    lines = draft.split('\n')
    cleaned = []
    questions_removed = 0

    # Process in reverse to remove trailing questions first
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.endswith('?') and questions_removed < max_to_remove:
            if _UNNECESSARY_Q_RE.match(stripped):
                questions_removed += 1
                continue
        cleaned.append(line)

    cleaned.reverse()
    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


# ── Process-language scrubber ──────────────────────────────────────────────
# Catches meta-process verbs ("Je trouve", "J'ai trouvé") and email-object
# references ("du mail du 2 février") that make answers sound robotic.

_PROCESS_VERB_RE = _re.compile(
    r"^("
    r"je trouve|j'ai trouv[eé]|je vois|je constate"
    r"|je vais (?:te |vous )?(?:v[eé]rifier|chercher|regarder|consulter|trouver|donner|fournir|envoyer|rechercher)"
    r"|i find|i found|i can see"
    r"|i(?:'ll| will) (?:check|look|verify|find|get|send|provide)"
    r"|(?:here are|voici) (?:the|les)"
    r")\s+",
    _re.IGNORECASE,
)

# Mid-sentence process language (#8) — "after reviewing your email, I..."
_PROCESS_MID_RE = _re.compile(
    r"(?:after |upon |après avoir |en )"
    r"(?:reviewing?|checking?|examining|looking at|analy[sz]ing|inspecting|reading|vérifiant|consultant|examinant|lisant|regardant)"
    r"(?:\s+(?:your|the|ton|votre|cette?|le|la|les))?"
    r"(?:\s+(?:email|e-?mail|message|request|demande|question|dossier|code|file|fichier))?"
    r"[,\s]+",
    _re.IGNORECASE,
)

_EMAIL_OBJECT_RE = _re.compile(
    r"\s*"
    r"("
    r"(?:du|de\s+(?:ton|votre|l'|mon))\s*(?:mail|e?-?mail|courriel|message)\s+du\s+\d{1,2}\s+\w+"
    r"|dans\s+(?:ton|votre|le|l')\s*(?:mail|e?-?mail|courriel|message)\s+du\s+\d{1,2}\s+\w+"
    r"|from\s+(?:the|your)\s+(?:email|message)\s+(?:of|dated|from)\s+\w+\s+\d{1,2}"
    r"|from\s+(?:the|your)\s+\w+\s+\d{1,2}\s+(?:email|message)"
    r"|in\s+(?:the|your)\s+(?:email|message)\s+(?:of|from|dated)\s+\w+\s+\d{1,2}"
    r")"
    r"(?:\s+\d{4})?"  # optional year
    r"\s*",
    _re.IGNORECASE,
)


_TRAILING_PROCESS_RE = _re.compile(
    r"("
    r"(?:les\s+)?(?:emails?|courriels?|messages?)\s+(?:pr[eé]c[eé]dents?|ant[eé]rieurs?)"
    r"|(?:je\s+)?(?:vais\s+)?(?:v[eé]rifier|chercher|rechercher|consulter|regarder)"
    r"|(?:si\s+(?:tout|c'est|ça)\s+(?:ça\s+)?(?:est\s+)?(?:correct|bon|ok))"
    r"|n'h[eé]site[sz]?\s+pas"
    r"|pour\s+(?:trouver|v[eé]rifier|chercher|confirmer|[eê]tre\s+s[uû]r)"
    r"|(?:à|a)\s+confirmer\.?$"
    r"|les\s+dates?\s+(?:pour|correspondantes?)"
    r"|(?:à|a)\s+(?:bient[oô]t|plus\s+tard)"
    r")",
    _re.IGNORECASE,
)

# Matches trailing stub sentences that reference "ton/votre/your email" without
# providing content.  E.g. ". Les dates de ton email." / ". The dates from your email."
_TRAILING_EMAIL_STUB_RE = _re.compile(
    r"\.\s+"                                      # after a sentence-ending period
    r"[A-ZÀ-Ÿ][^.]{0,50}"                       # short fragment (≤50 chars)
    r"\b(?:de\s+|d'|from\s+|of\s+|in\s+)"        # preposition
    r"(?:(?:ton|votre|son|your|the|this)\s+|l')"  # possessive / article
    r"(?:e?-?mail|mail|courriel|message)"         # email reference
    r"\.?\s*$",                                   # trailing period
    _re.IGNORECASE,
)

# Matches KEY DATA hint echoes: "Chiffres du 2 février : 02." or "Data from email: ..."
_DATA_HINT_ECHO_RE = _re.compile(
    r"\.\s+"  # after a sentence-ending period
    r"[A-ZÀ-Ÿ][a-zà-ÿ]*"  # capitalized word
    r"(?:\s+\w+)*?"  # optional words
    r"\s+(?:du|de|from)\s+\d"  # date/source reference
    r"[^.]*"  # rest of the echo
    r"\s*:\s*"  # colon separator
    r"[^.]*"  # value part
    r"\.?\s*$",  # trailing period
    _re.IGNORECASE,
)

# Matches standalone data hint echo lines: "Chiffres du 2 février : 02."
# Value after colon must be purely numeric to avoid false positives on legit content.
_DATA_HINT_ECHO_LINE_RE = _re.compile(
    r"^[A-ZÀ-Ÿ][a-zà-ÿ]*"       # capitalized word
    r"(?:\s+\w+){0,6}"            # up to 6 words
    r"\s+(?:du|de|from)\s+\d"     # date/source reference
    r"[^:]*"                       # rest before colon
    r":\s*"                        # colon separator
    r"\d[\d\s,./]*"               # purely numeric value
    r"\.?\s*$",                    # trailing period
    _re.IGNORECASE,
)


def _scrub_process_language(draft: str) -> str:
    """
    Post-LLM pass: remove meta-process language from draft.

    1. Start-of-sentence process verbs: "Je trouve les 3 chiffres" → "Les 3 chiffres"
    2. Email-object references: "du mail du 2 février" → removed
    3. Trailing process lines: "Les emails précédents pour trouver..." → removed
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        # 1. Strip process verbs at start of line
        m = _PROCESS_VERB_RE.match(stripped)
        if m:
            rest = stripped[m.end():].lstrip()
            # Skip if remainder starts with "que/that" — stripping leaves broken grammar
            if rest and not rest.lower().startswith(("que ", "qu'", "that ")):
                stripped = rest[0].upper() + rest[1:]

        # 1b. Strip mid-sentence process language (#8)
        m2 = _PROCESS_MID_RE.search(stripped)
        if m2:
            before = stripped[:m2.start()].rstrip(' ,;')
            after = stripped[m2.end():]
            if after:
                after = after[0].upper() + after[1:] if after[0].islower() else after
            stripped = f"{before} {after}".strip() if before and after else (after or before).strip()
            if not stripped:
                continue

        # 2. Strip email-object references mid-sentence
        stripped = _EMAIL_OBJECT_RE.sub(' ', stripped).strip()
        # Clean double spaces left behind
        while '  ' in stripped:
            stripped = stripped.replace('  ', ' ')
        # Clean ": :" patterns left from removing context between colons
        stripped = _re.sub(r'\s*:\s*:', ':', stripped)

        cleaned.append(stripped)

    # 2b. Strip KEY DATA hint echoes within lines (e.g., "bonne réponse. Chiffres du 2 février : 02.")
    #     AND standalone lines that are pure data hint echoes (e.g., "Chiffres du 2 février : 02.")
    for i, line in enumerate(cleaned):
        stripped = line.strip()
        if stripped:
            # Inline echo after a period
            cleaned[i] = _DATA_HINT_ECHO_RE.sub('.', stripped)
            # Standalone echo line with numeric value
            if _DATA_HINT_ECHO_LINE_RE.match(cleaned[i].strip()):
                cleaned[i] = ''

    # 3. Remove trailing process/meta lines from the end
    while cleaned:
        last = cleaned[-1].strip()
        if not last:
            cleaned.pop()
            continue
        # Only remove full trailing process/meta lines. A substantive sentence
        # can legitimately contain a later phrase such as "N'hésite pas à me
        # proposer un créneau"; dropping the whole line would erase the user's
        # requested content from expanded notes.
        if _TRAILING_PROCESS_RE.match(last):
            cleaned.pop()
        else:
            break

    result = '\n'.join(cleaned)

    # 4. Strip trailing email-reference stubs inline (". Les dates de ton email.")
    result = _TRAILING_EMAIL_STUB_RE.sub('.', result)

    return result if len(result.strip()) >= 10 else draft


# ── P1: Vous/Tu consistency checker ──────────────────────────────────────

_VOUS_MARKERS = _re.compile(r'\b(?:vous|votre|vos|voulez|pourriez|veuillez|souhaitez|auriez)\b', _re.IGNORECASE)
_TU_MARKERS = _re.compile(r'\b(?:(?<![a-zà-ÿ])tu(?![a-zà-ÿ])|(?<![a-zà-ÿ])ton(?![a-zà-ÿ])|(?<![a-zà-ÿ])ta(?![a-zà-ÿ])|(?<![a-zà-ÿ])tes(?![a-zà-ÿ])|(?<![a-zà-ÿ])toi(?![a-zà-ÿ])|peux|veux|fais(?![a-zà-ÿ]))\b', _re.IGNORECASE)


def _fix_pronoun_consistency(draft: str, formality: int = 3) -> str:
    """
    Post-LLM pass (P1): fix vous/tu mixing within a single draft.

    Counts vous-markers vs tu-markers. If both present, normalizes
    to the majority form (or to the one matching formality).
    """
    if not draft:
        return draft

    # Only applies to French drafts
    is_french = any(w in draft.lower() for w in _FR_DETECT_WORDS)
    if not is_french:
        return draft

    vous_count = len(_VOUS_MARKERS.findall(draft))
    tu_count = len(_TU_MARKERS.findall(draft))

    # No mixing → nothing to fix
    if vous_count == 0 or tu_count == 0:
        return draft

    # Decide target: formality ≥ 3 → vous, else → tu. If ambiguous, use majority.
    if formality >= 3:
        target = "vous"
    elif formality <= 2:
        target = "tu"
    else:
        target = "vous" if vous_count >= tu_count else "tu"

    if target == "vous" and tu_count > 0:
        # Convert tu→vous (pronouns, determiners, AND verb conjugations)
        draft = _re.sub(r'\btu\b', 'vous', draft)
        draft = _re.sub(r'\bTu\b', 'Vous', draft)
        draft = _re.sub(r'\bton\b', 'votre', draft)
        draft = _re.sub(r'\bTon\b', 'Votre', draft)
        draft = _re.sub(r'\bta\b', 'votre', draft)
        draft = _re.sub(r'\bTa\b', 'Votre', draft)
        draft = _re.sub(r'\btes\b', 'vos', draft)
        draft = _re.sub(r'\bTes\b', 'Vos', draft)
        draft = _re.sub(r'\btoi\b', 'vous', draft)
        # Verb conjugations tu→vous
        draft = _re.sub(r'\bpeux\b', 'pouvez', draft)
        draft = _re.sub(r'\bPeux\b', 'Pouvez', draft)
        draft = _re.sub(r'\bveux\b', 'voulez', draft)
        draft = _re.sub(r'\bVeux\b', 'Voulez', draft)
        draft = _re.sub(r'\bfais\b', 'faites', draft)
        draft = _re.sub(r'\bFais\b', 'Faites', draft)
        draft = _re.sub(r'\bvas\b', 'allez', draft)
        draft = _re.sub(r'\bVas\b', 'Allez', draft)
        draft = _re.sub(r'\bvous as\b', 'vous avez', draft)
        draft = _re.sub(r'\bVous as\b', 'Vous avez', draft)
        draft = _re.sub(r'\bvous es\b', 'vous êtes', draft)
        draft = _re.sub(r'\bVous es\b', 'Vous êtes', draft)
        draft = _re.sub(r'\bdois\b', 'devez', draft)
        draft = _re.sub(r'\bDois\b', 'Devez', draft)
        draft = _re.sub(r'\bsais\b', 'savez', draft)
        draft = _re.sub(r'\bSais\b', 'Savez', draft)
    elif target == "tu" and vous_count > 0:
        # Convert vous→tu (pronouns, determiners, AND verb conjugations)
        draft = _re.sub(r'\bvous\b', 'tu', draft)
        draft = _re.sub(r'\bVous\b', 'Tu', draft)
        draft = _re.sub(r'\bvotre\b', 'ton', draft)
        draft = _re.sub(r'\bVotre\b', 'Ton', draft)
        draft = _re.sub(r'\bvos\b', 'tes', draft)
        draft = _re.sub(r'\bVos\b', 'Tes', draft)
        # Verb conjugations vous→tu
        draft = _re.sub(r'\bvoulez\b', 'veux', draft)
        draft = _re.sub(r'\bVoulez\b', 'Veux', draft)
        draft = _re.sub(r'\bpouvez\b', 'peux', draft)
        draft = _re.sub(r'\bPouvez\b', 'Peux', draft)
        draft = _re.sub(r'\bfaites\b', 'fais', draft)
        draft = _re.sub(r'\bFaites\b', 'Fais', draft)
        draft = _re.sub(r'\ballez\b', 'vas', draft)
        draft = _re.sub(r'\bAllez\b', 'Vas', draft)
        draft = _re.sub(r'\btu avez\b', 'tu as', draft)
        draft = _re.sub(r'\bTu avez\b', 'Tu as', draft)
        draft = _re.sub(r'\btu [êe]tes\b', 'tu es', draft)
        draft = _re.sub(r'\bTu [êe]tes\b', 'Tu es', draft)
        draft = _re.sub(r'\bdevez\b', 'dois', draft)
        draft = _re.sub(r'\bDevez\b', 'Dois', draft)
        draft = _re.sub(r'\bsavez\b', 'sais', draft)
        draft = _re.sub(r'\bSavez\b', 'Sais', draft)
        draft = _re.sub(r'\bveuillez\b', '', draft)

    return draft


# ── P2: Sentence-opening diversity checker ───────────────────────────────

def _fix_repetitive_openings(draft: str) -> str:
    """
    Post-LLM pass (P2): fix repetitive sentence openings.

    If >50% of sentences start with the same word (e.g., "Je... Je... Je..."),
    rephrase the duplicate openers to vary the structure.
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    # Collect non-empty content lines (skip greeting)
    content_lines = []
    content_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip greeting line (short, ends with comma)
        if stripped.endswith(',') and len(stripped) < 50 and i < 3:
            continue
        content_lines.append(stripped)
        content_indices.append(i)

    if len(content_lines) < 3:
        return draft

    # Count first-word frequency
    from collections import Counter
    first_words = [ln.split()[0].lower().rstrip(',.;:!') for ln in content_lines if ln.split()]
    counts = Counter(first_words)
    if not counts:
        return draft

    most_common_word, most_common_count = counts.most_common(1)[0]
    # Only fix if >50% of sentences start with same word
    if most_common_count / len(content_lines) <= 0.5:
        return draft

    # Rephrase: for repeated openings, remove every other occurrence
    # by restructuring the sentence
    seen_count = 0
    for idx, cl in zip(content_indices, content_lines):
        first = cl.split()[0].lower().rstrip(',.;:!')
        if first == most_common_word:
            seen_count += 1
            if seen_count > 1 and seen_count % 2 == 0:
                # Try to rephrase by removing the subject pronoun
                stripped = cl
                # "Je confirme" → "Confirmé", "Je vais" → keep (can't rephrase easily)
                # "I will check" → "Will check", "I can help" → "Can help"
                for pattern, replacement in [
                    (r'^Je\s+', ''), (r'^I\s+', ''),
                    (r'^Nous\s+', ''), (r'^We\s+', ''),
                ]:
                    m = _re.match(pattern, stripped, _re.IGNORECASE)
                    if m:
                        rest = stripped[m.end():]
                        if rest and len(rest) > 5:
                            stripped = rest[0].upper() + rest[1:]
                            break
                lines[idx] = stripped

    return '\n'.join(lines)


# ── P3: Excessive apologies stripper ─────────────────────────────────────

_APOLOGY_RE = _re.compile(
    r'\b(?:'
    r"(?:i'?m |i am )?(?:really |truly |sincerely |very )?sorry\b"
    r"|(?:i |we )?apologize\b"
    r"|my apologies\b"
    r"|pardon(?:nez)?(?:-moi)?\b"
    r"|(?:je suis |)d[eé]sol[eé](?:e)?\b"
    r"|(?:je |nous )(?:m'|nous )excuse(?:z|nt|s)?\b"
    r"|toutes? (?:mes |nos )?excuses?\b"
    r"|navr[eé](?:e)?\b"
    r")",
    _re.IGNORECASE,
)


def _strip_excessive_apologies(draft: str) -> str:
    """
    Post-LLM pass (P3): keep at most 1 apology per draft.

    LLMs pile up "sorry", "I apologize", "pardon" — keep only the first.
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    apology_count = 0
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        matches = list(_APOLOGY_RE.finditer(stripped))
        if not matches:
            cleaned.append(line)
            continue

        if apology_count == 0 and len(matches) == 1:
            # Line has exactly 1 apology and it's the first → keep as-is
            apology_count += 1
            cleaned.append(line)
        else:
            # Strip all apologies except the global first one
            modified = stripped
            for m in reversed(matches):
                if apology_count == 0:
                    apology_count += 1
                    continue  # Keep this one (first global apology)
                before = modified[:m.start()].rstrip(' ,;.')
                after = modified[m.end():].lstrip(' ,;.!')
                modified = f"{before} {after}".strip() if before and after else (before or after).strip()
            # Clean up double spaces
            modified = _re.sub(r'\s{2,}', ' ', modified).strip()
            if modified and len(modified) >= 5:
                if modified[0].islower():
                    modified = modified[0].upper() + modified[1:]
                cleaned.append(modified)
            elif not modified and stripped:
                continue  # Line was entirely apology → drop
            else:
                cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


# ── P4: Redundant affirmations stripper ──────────────────────────────────

_AFFIRMATION_RE = _re.compile(
    r'\b(?:'
    r"absolutely|certainly|definitely|of course|sure(?:ly)?|indeed"
    r"|bien s[uû]r|certainement|absolument|tout [aà] fait|effectivement|evidemment|évidemment"
    r"|sans aucun doute|assur[eé]ment"
    r")[!,\s]*",
    _re.IGNORECASE,
)


def _strip_redundant_affirmations(draft: str) -> str:
    """
    Post-LLM pass (P4): keep at most 1 strong affirmation per draft.

    "Absolutely, I will. Certainly, no problem. Of course!" → keep only first.
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    affirmation_count = 0
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        matches = list(_AFFIRMATION_RE.finditer(stripped))
        if not matches:
            cleaned.append(line)
            continue

        if affirmation_count == 0:
            # Keep first affirmation
            affirmation_count += 1
            cleaned.append(line)
        else:
            # Strip additional affirmations
            modified = stripped
            for m in reversed(matches):
                before = modified[:m.start()].rstrip(' ,;.')
                after = modified[m.end():].lstrip(' ,;.!')
                modified = f"{before} {after}".strip() if before and after else (before or after).strip()
            if modified and len(modified) >= 5:
                if modified[0].islower():
                    modified = modified[0].upper() + modified[1:]
                cleaned.append(modified)
            elif not modified and stripped:
                continue  # Line was entirely affirmation → drop
            else:
                cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


# ── P5: Closing tone mismatch fixer ─────────────────────────────────────

_FORMAL_CLOSINGS_RE = _re.compile(
    r'^(?:cordialement|sincèrement|sincerely|kind regards|best regards|'
    r'respectueusement|bien [àa] vous|veuillez agréer|yours (?:truly|faithfully))',
    _re.IGNORECASE,
)
_CASUAL_CLOSINGS_RE = _re.compile(
    r'^(?:[àa] bient[oô]t|[àa] plus|[àa]\+|cheers|later|take care|'
    r'bye|ciao|salut|bises|bisous)',
    _re.IGNORECASE,
)


def _fix_closing_tone(draft: str, formality: int = 3) -> str:
    """
    Post-LLM pass (P5): ensure closing matches formality level.

    Formal closing in casual email → strip it. Casual closing in formal → strip it.
    The _strip_signature() already removes most closings, but this catches remainders.
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    # Check last non-empty lines for closing tone
    for i in range(len(lines) - 1, max(0, len(lines) - 4), -1):
        stripped = lines[i].strip()
        if not stripped:
            continue

        if formality <= 2 and _FORMAL_CLOSINGS_RE.match(stripped):
            # Formal closing in casual context → remove
            lines[i] = ''
        elif formality >= 4 and _CASUAL_CLOSINGS_RE.match(stripped):
            # Casual closing in formal context → remove
            lines[i] = ''
        break  # Only check first non-empty line from bottom

    result = '\n'.join(lines).rstrip()
    while result.endswith('\n\n'):
        result = result[:-1]
    return result


# ── P6: Slop words detector ─────────────────────────────────────────────

_SLOP_WORDS_RE = _re.compile(
    r'\b(?:'
    r"delve|tapestry|testament|landscape|kaleidoscope|symphony|interplay"
    r"|multifaceted|intricate(?:ly)?|pivotal|nuanced|comprehensive(?:ly)?"
    r"|leverage|utilize|facilitate|endeavor|embark|navigate"
    r"|realm|crucial|robust|paradigm|synergy|holistic"
    r"|streamline|spearhead|foster"
    # FR equivalents
    r"|approfondir|tapisserie|paysage|kaléidoscope|symphonie"
    r"|multifacette|complexe(?:ment)?|essentiel(?:lement)?"
    r"|exploiter|faciliter|entreprendre"
    r")\b",
    _re.IGNORECASE,
)


def _strip_slop_words(draft: str) -> str:
    """
    Post-LLM pass (P6): remove 'AI slop' words statistically overrepresented in LLM text.

    Words like 'delve', 'tapestry', 'navigate', 'leverage' appear 10x+ more in
    LLM output than human text. Remove them or replace with simpler alternatives.
    """
    if not draft:
        return draft

    # Simple approach: remove slop words that appear as standalone adjectives/verbs
    # Only strip if the word is non-essential (not the main verb)
    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        modified = stripped
        for m in reversed(list(_SLOP_WORDS_RE.finditer(modified))):
            word = m.group().lower()
            # Replace with simpler alternatives
            replacements = {
                'delve': 'look', 'navigate': 'handle', 'leverage': 'use',
                'utilize': 'use', 'facilitate': 'help', 'endeavor': 'try',
                'embark': 'start', 'robust': 'strong', 'streamline': 'simplify',
                'spearhead': 'lead', 'foster': 'encourage', 'holistic': 'complete',
                'pivotal': 'key', 'crucial': 'important', 'nuanced': 'detailed',
                'comprehensive': 'full', 'comprehensively': 'fully',
                'multifaceted': 'varied', 'intricate': 'complex',
                'intricately': 'closely',
                # FR
                'approfondir': 'examiner', 'exploiter': 'utiliser',
                'faciliter': 'aider',
            }
            replacement = replacements.get(word, '')
            if replacement:
                modified = modified[:m.start()] + replacement + modified[m.end():]
            # For decorative words (tapestry, kaleidoscope, etc.), just remove
            elif word in ('tapestry', 'kaleidoscope', 'symphony', 'interplay',
                         'landscape', 'testament', 'realm', 'paradigm', 'synergy',
                         'tapisserie', 'kaléidoscope', 'symphonie', 'paysage',
                         'multifacette'):
                before = modified[:m.start()].rstrip(' ,')
                after = modified[m.end():].lstrip(' ,')
                modified = f"{before} {after}".strip() if before and after else (before or after).strip()

        cleaned.append(modified if modified else line)

    return '\n'.join(cleaned)


# ── P7: Not-X-But-Y pattern stripper ────────────────────────────────────

_NOT_X_BUT_Y_RE = _re.compile(
    r'\b(?:not\s+(?:just|only|merely|simply)\s+[^,]{3,40},?\s+but\s+(?:also\s+)?'
    r"|pas\s+(?:seulement|uniquement|simplement)\s+[^,]{3,40},?\s+mais\s+(?:aussi\s+|également\s+)?)",
    _re.IGNORECASE,
)


def _simplify_contrast_patterns(draft: str) -> str:
    """
    Post-LLM pass (P7): simplify 'not just X, but also Y' constructions.

    This pattern appears 6.3x more in LLM text than human writing.
    Simplify to direct statement.
    """
    if not draft:
        return draft

    # Replace "not just X, but also Y" → "X and Y" or just remove the pattern
    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        # Remove the "not just/only" part, keep the assertion
        modified = _re.sub(
            r'\bnot\s+(?:just|only|merely|simply)\s+',
            '', stripped, flags=_re.IGNORECASE
        )
        modified = _re.sub(
            r',?\s+but\s+(?:also|equally)\s+',
            ' and ', modified, flags=_re.IGNORECASE
        )
        modified = _re.sub(
            r'\bpas\s+(?:seulement|uniquement|simplement)\s+',
            '', modified, flags=_re.IGNORECASE
        )
        modified = _re.sub(
            r',?\s+mais\s+(?:aussi|[eé]galement)\s+',
            ' et ', modified, flags=_re.IGNORECASE
        )
        cleaned.append(modified)

    return '\n'.join(cleaned)


# ── P8: Contact detail invention detector ────────────────────────────────

_PHONE_RE = _re.compile(r'(?:\+?\d[\d\s\-.]{7,15}\d)')
_EMAIL_ADDR_RE = _re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_URL_RE = _re.compile(r'https?://\S+|www\.\S+')


def _scrub_invented_contacts(draft: str, body: str) -> str:
    """
    Post-LLM pass (P8): remove phone numbers, email addresses, and URLs
    that appear in the draft but NOT in the original email body.
    """
    if not draft or not body:
        return draft

    body_phones = set(_PHONE_RE.findall(body))
    body_emails = set(_EMAIL_ADDR_RE.findall(body.lower()))
    body_urls = set(_URL_RE.findall(body.lower()))

    def is_grounded(match_text, body_set):
        """Check if a match exists in the body (fuzzy: ignore spacing/dashes)."""
        normalized = _re.sub(r'[\s\-.]', '', match_text)
        for b in body_set:
            if _re.sub(r'[\s\-.]', '', b) == normalized:
                return True
        return False

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        modified = line
        # Check phone numbers
        for m in reversed(list(_PHONE_RE.finditer(modified))):
            if not is_grounded(m.group(), body_phones):
                modified = modified[:m.start()] + '[phone]' + modified[m.end():]
        # Check email addresses
        for m in reversed(list(_EMAIL_ADDR_RE.finditer(modified))):
            if m.group().lower() not in body_emails:
                modified = modified[:m.start()] + '[email]' + modified[m.end():]
        # Check URLs
        for m in reversed(list(_URL_RE.finditer(modified))):
            if m.group().lower() not in body_urls:
                modified = modified[:m.start()] + '[link]' + modified[m.end():]
        cleaned.append(modified)

    return '\n'.join(cleaned)


# ── Ungrounded noun scrubber (Level 3 anti-hallucination) ────────────────

# Words that are commonly capitalized but are NOT proper nouns.
# Kept small & targeted — only words that would cause false positives.
_COMMON_CAPITALIZED_WORDS = frozenset({
    # French common sentence starters / greetings / closings
    "bonjour", "salut", "bonsoir", "coucou", "merci", "cordialement",
    "sincèrement", "amicalement", "respectueusement", "cdlt",
    "oui", "non", "bien", "super", "parfait", "exactement",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
    # English common
    "hello", "hi", "hey", "thanks", "regards", "sincerely", "cheers",
    "yes", "no", "ok", "sure", "great", "perfect",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    # Very common nouns that can appear capitalized after line breaks
    "email", "mail", "message", "sujet", "objet", "réunion", "meeting",
    "projet", "project", "document", "fichier", "file", "équipe", "team",
    "bureau", "office", "entreprise", "company", "client", "service",
    # Placeholder tokens
    "confirmer", "confirmed", "tbd",
    # AI/tech brand names commonly used as common nouns in context
    "claude", "chatgpt", "gemini", "mistral", "llama", "openai", "anthropic",
})

# Sentence-ending punctuation that resets capitalization expectation
_SENTENCE_END_RE = _re.compile(r'[.!?:]\s*$')

# Contractions like "I'll" become "Ill" after punctuation stripping and
# can be mistaken for hallucinated proper nouns mid-sentence.
_ENGLISH_CONTRACTION_RE = _re.compile(
    r"^(?:i|you|we|they|he|she|it|that|there|what|who|where|when|why|how|let|"
    r"don|doesn|didn|can|cannot|won|wouldn|shouldn|couldn|isn|aren|wasn|"
    r"weren|haven|hasn|hadn|mustn|needn)['’](?:ll|ve|re|d|m|s|t)$",
    _re.IGNORECASE,
)


def _scrub_ungrounded_nouns(
    draft: str, body: str, subject: str = "", sender: str = "",
    user_context: str = "",
) -> str:
    """
    Post-LLM pass: remove sentences containing proper nouns (names, places, etc.)
    that do NOT appear anywhere in the source email, subject, or sender.

    Catches hallucinated names like 'David', 'Marcus', invented project names, etc.
    Conservative: only flags mid-sentence capitalized words ≥3 chars that aren't
    common words, month/day names, or words from the source email.

    `user_context` carries any user-provided instructions/notes (e.g. the body
    of an `/expand` request). Words from there are treated as grounded, since
    the user explicitly authored them. Without this, expanding notes that
    mention "Marcus" or "Pinterest" would have the scrubber wipe the very
    sentences the user asked the AI to write — see 2026-05-13 incident.
    """
    if not draft or not body:
        return draft

    # Build grounding set: all words from source email + subject + sender
    # (+ any user-authored context like /expand notes).
    source_text = f"{subject} {body} {sender} {user_context}"
    # Extract all words ≥2 chars (lowercased) from the source
    source_words = set(
        w.lower() for w in _re.findall(r'[a-zA-ZÀ-ÿ]{2,}', source_text)
    )

    # Also allow the user's own name
    try:
        from app.prompts import _extract_user_name
        user_name = _extract_user_name()
        if user_name:
            for part in user_name.lower().split():
                source_words.add(part)
    except Exception as e:
        logger.debug(f"Suppressed: {e}")

    lines = draft.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue

        words = stripped.split()
        ungrounded_found = False
        after_sentence_end = True  # first word of line is always "sentence start"

        for word in words:
            # Clean punctuation from word
            clean = _re.sub(r'[^\w\u00C0-\u024F]', '', word)
            if not clean:
                # Check if word was punctuation that ends a sentence
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            # Skip words at the start of a sentence (naturally capitalized)
            if after_sentence_end:
                after_sentence_end = False
                # Check if this word ends a sentence too (single-word sentence)
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            contraction = _re.sub(r"^[^A-Za-zÀ-ÿ]+|[^A-Za-zÀ-ÿ'’]+$", "", word)
            if _ENGLISH_CONTRACTION_RE.match(contraction):
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            # Only check words that start with uppercase (potential proper nouns)
            if not clean[0].isupper():
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            # Skip short words (abbreviations: OK, RH, HR, CV, etc.)
            if len(clean) < 3:
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            # Skip known common capitalized words
            if clean.lower() in _COMMON_CAPITALIZED_WORDS:
                if _SENTENCE_END_RE.search(word):
                    after_sentence_end = True
                continue

            # Check grounding: is this word in the source email?
            if clean.lower() not in source_words:
                ungrounded_found = True
                logger.info(
                    "_scrub_ungrounded_nouns: removing line with ungrounded "
                    "noun '%s': '%s'", clean, stripped[:80],
                )
                break

            if _SENTENCE_END_RE.search(word):
                after_sentence_end = True

        if not ungrounded_found:
            result.append(line)

    cleaned = '\n'.join(result).strip()
    # Safety: never return empty draft
    return cleaned if cleaned else draft


# ── L3b: Novel-situation scrubber (common-noun hallucinations) ───────────

# Patterns that introduce a personal situation the sender never mentioned.
# Each group captures the "keyword noun" to ground-check against the source.
_NOVEL_SITUATION_FR_RE = _re.compile(
    r'(?:'
    r'\b(?:mon|ma|mes)\s+(\w{3,})'            # mon congé, ma réunion, mes vacances
    r'|\bje\s+suis\s+en\s+(\w{3,})'           # je suis en congé/vacances/déplacement
    r"|\bj['\u2019]ai\s+\w+\s+(?:le|la|les|un|une)\s+(\w{3,})"  # j'ai reçu le rapport
    r'|\b(?:le|la|les)\s+(\w{3,})\s+(?:est|sont)\s+(?:en\s+)?\w+'  # le rapport est prêt
    r')',
    _re.IGNORECASE,
)

_NOVEL_SITUATION_EN_RE = _re.compile(
    r'(?:'
    r"\bmy\s+(\w{3,})\s+(?:is|are|was|were|has|have)\b"  # my vacation is...
    r"|\bI['\u2019]m\s+on\s+(\w{3,})"                    # I'm on vacation
    r"|\bI\s+have\s+\w+\s+the\s+(\w{3,})"                # I have received the report
    r')',
    _re.IGNORECASE,
)

# Common stopwords that should never be flagged (too generic).
_NOVEL_SITUATION_STOPWORDS = frozenset({
    'côté', 'côte', 'cote', 'mieux', 'bien', 'tout', 'rien', 'fait',
    'moment', 'suite', 'cours', 'place', 'part', 'point', 'cas',
    'side', 'part', 'way', 'time', 'best', 'back', 'end',
})


def _scrub_novel_situation(
    draft: str, body: str, subject: str = "", user_context: str = "",
) -> str:
    """
    Post-LLM pass for SHORT emails (<150 chars): remove lines that introduce
    a personal situation using common nouns not grounded in the source email.

    Complements _scrub_ungrounded_nouns (which only catches proper nouns).

    `user_context` carries any user-provided notes/instructions (e.g. /expand
    flow). Words from there count as grounded — the user explicitly authored
    them, so they are not hallucinations even when the source email is short
    and does not mention them. See 2026-05-13 incident: a user typed
    "j'ai eu mon accès VIP" as notes, the drafter expanded them, then this
    scrubber deleted the sentence because "accès" wasn't in the 16-char
    source email.
    """
    if not draft or not body:
        return draft

    body_clean = (body or "").strip()
    if len(body_clean) >= 150:
        return draft  # Long emails → LLM has enough context

    # Build grounding set from source (+ any user-authored context).
    source_text = f"{subject} {body} {user_context}"
    source_words = set(
        w.lower() for w in _re.findall(r'[a-zA-ZÀ-ÿ]{2,}', source_text)
    )

    lines = draft.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue

        flagged = False
        for pattern in (_NOVEL_SITUATION_FR_RE, _NOVEL_SITUATION_EN_RE):
            for m in pattern.finditer(stripped):
                # Extract the captured noun (first non-None group)
                keyword = next((g for g in m.groups() if g), None)
                if not keyword:
                    continue
                kw = keyword.lower()
                if kw in _NOVEL_SITUATION_STOPWORDS:
                    continue
                if kw not in source_words:
                    logger.info(
                        "_scrub_novel_situation: removing line with "
                        "ungrounded noun '%s': '%s'", keyword, stripped[:80],
                    )
                    flagged = True
                    break
            if flagged:
                break

        if not flagged:
            result.append(line)

    cleaned = '\n'.join(result).strip()
    # Safety: never return empty draft
    return cleaned if cleaned else draft


# ── P9: Sycophancy pattern stripper ──────────────────────────────────────

_SYCOPHANCY_RE = _re.compile(
    r'^(?:'
    r"(?:that'?s |what )?(?:a |an )?(?:great|excellent|wonderful|fantastic|brilliant|amazing|outstanding|superb) "
    r"(?:question|point|idea|suggestion|observation|thought|insight)"
    r"|(?:quelle |c'est une )?(?:excellente|très bonne|super|magnifique|brillante) "
    r"(?:question|remarque|idée|suggestion|observation)"
    r"|you(?:'re| are) (?:absolutely |completely )?right"
    r"|(?:tu as|vous avez) (?:tout [àa] fait |absolument |enti[èe]rement )?raison"
    r"|i (?:really |truly )?appreciate (?:you|your|the)"
    r"|j'apprécie (?:vraiment |sincèrement )?(?:ta|votre|cette)"
    r")",
    _re.IGNORECASE | _re.MULTILINE,
)


def _strip_sycophancy(draft: str) -> str:
    """
    Post-LLM pass (P9): remove sycophantic patterns.

    "That's a great question!" → removed
    "You're absolutely right" → removed
    "I really appreciate your insight" → removed
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        if _SYCOPHANCY_RE.match(stripped):
            # Check if there's useful content after the sycophancy
            rest = _SYCOPHANCY_RE.sub('', stripped).strip().lstrip('!.,;: ')
            if rest and len(rest) >= 10:
                if rest[0].islower():
                    rest = rest[0].upper() + rest[1:]
                cleaned.append(rest)
            # else: line was entirely sycophantic → drop
            continue
        cleaned.append(line)

    result = '\n'.join(cleaned).strip()
    return result if len(result) >= 10 else draft


# ── P12: Recap/summary stripper ─────────────────────────────────────────

_RECAP_PREFIXES_RE = _re.compile(
    r'^(?:'
    r"(?:in |to )?summar(?:y|ize|ise)|to (?:recap|sum up)|in (?:short|conclusion|brief)"
    r"|(?:en |pour )résumé|pour (?:conclure|récapituler)|en somme|bref"
    r"|as (?:mentioned|noted|stated) (?:above|earlier|previously)"
    r"|comme (?:mentionné|dit|indiqué) (?:ci-dessus|plus haut|précédemment)"
    r")",
    _re.IGNORECASE,
)


def _strip_recap_sentences(draft: str) -> str:
    """
    Post-LLM pass (P12): remove concluding recap sentences that restate content.

    'In summary, I will check the report and send it.' → removed if already said above.
    """
    if not draft:
        return draft

    lines = draft.split('\n')
    if len(lines) < 3:
        return draft

    # Only check last 2 non-empty lines
    cleaned = list(lines)
    for i in range(len(lines) - 1, max(0, len(lines) - 3), -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if _RECAP_PREFIXES_RE.match(stripped):
            cleaned[i] = ''

    result = '\n'.join(cleaned).rstrip()
    while result.endswith('\n\n'):
        result = result[:-1]
    return result.strip() if len(result.strip()) >= 10 else draft


# ── P13: Sender name overuse detector ───────────────────────────────────

# Cache for per-name regex patterns (avoid re-compile on repeated calls for same sender)
_NAME_PATTERN_CACHE: dict[str, _re.Pattern] = {}


def _fix_name_overuse(draft: str, sender_name: str) -> str:
    """
    Post-LLM pass (P13): remove excessive uses of the sender's name.

    Keep the name in the greeting + at most 1 more occurrence in the body.
    """
    if not draft or not sender_name:
        return draft

    # Extract first name
    first_name = sender_name.split()[0] if sender_name.split() else sender_name
    if len(first_name) < 2:
        return draft

    name_pattern = _NAME_PATTERN_CACHE.get(first_name)
    if name_pattern is None:
        name_pattern = _re.compile(r'\b' + _re.escape(first_name) + r'\b', _re.IGNORECASE)
        # Limit cache size to avoid unbounded growth
        if len(_NAME_PATTERN_CACHE) < 256:
            _NAME_PATTERN_CACHE[first_name] = name_pattern

    lines = draft.split('\n')
    body_occurrences = 0
    max_body_uses = 1  # Allow 1 use in body (beyond greeting)

    cleaned = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip greeting line
        if stripped.endswith(',') and len(stripped) < 50 and i < 3:
            cleaned.append(line)
            continue

        # Count individual occurrences on this line
        matches = list(name_pattern.finditer(stripped))
        if not matches:
            cleaned.append(line)
            continue

        # Process each match: keep up to max_body_uses total, strip the rest
        # Build list of match indices to remove (skip first N)
        to_remove = []
        for m in matches:
            if body_occurrences < max_body_uses:
                body_occurrences += 1  # Keep this one
            else:
                to_remove.append(m)

        modified = stripped
        for m in reversed(to_remove):
            before = modified[:m.start()].rstrip(' ,')
            after = modified[m.end():].lstrip(' ,')
            modified = f"{before} {after}".strip() if before and after else (before or after).strip()

        modified = _re.sub(r'\s{2,}', ' ', modified).strip()
        cleaned.append(modified if modified else line)

    return '\n'.join(cleaned)


# ── P14: Markdown artifacts cleaner ──────────────────────────────────────

_MARKDOWN_RE = _re.compile(
    r'^#{1,6}\s'           # Markdown headings
    r'|^\*\*[^*]+\*\*\s*$'  # Bold-only lines
    r'|^[-*]\s'            # Bullet points
    r'|```'                # Code fences
    r'|^\s*>\s'            # Blockquotes
    r'|^---+\s*$'          # Horizontal rules (already caught but belt-and-suspenders)
)

_INLINE_MARKDOWN_RE = _re.compile(r'\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`')

# ── Pre-compiled patterns for _strip_html_tags ──
_HTML_BR_RE = _re.compile(r'<br\s*/?>', _re.IGNORECASE)
_HTML_P_RE = _re.compile(r'<p[^>]*>(.*?)</p>', _re.IGNORECASE | _re.DOTALL)
_HTML_DIV_RE = _re.compile(r'<div[^>]*>(.*?)</div>', _re.IGNORECASE | _re.DOTALL)
_HTML_TAG_RE = _re.compile(r'<[^>]+>')
_TRIPLE_NEWLINE_RE = _re.compile(r'\n{3,}')


def _strip_html_tags(draft: str) -> str:
    """Remove HTML tags that leaked from the LLM into plain-text drafts.

    Fast-path: if no `<` in the text, there can't be any HTML tag — skip
    all regex work immediately. This saves ~50-100 ms on typical drafts
    that contain no HTML (the vast majority).
    """
    if not draft or "<" not in draft:
        return draft.strip() if draft else draft
    d = _HTML_BR_RE.sub('\n', draft)
    d = _HTML_P_RE.sub(r'\1\n', d)
    d = _HTML_DIV_RE.sub(r'\1\n', d)
    d = _HTML_TAG_RE.sub('', d)
    d = _TRIPLE_NEWLINE_RE.sub('\n\n', d)
    return d.strip()


def _strip_markdown_artifacts(draft: str) -> str:
    """
    Post-LLM pass (P14): remove markdown formatting that leaked into the draft.

    Fast-path: if none of the common markdown markers are present, skip
    the full line-by-line loop. Saves ~30-80 ms on typical drafts.
    """
    if not draft:
        return draft
    if not any(marker in draft for marker in ("**", "##", "```", "- ", "* ", "> ", "__", "---")):
        return draft

    lines = draft.split('\n')
    cleaned = []
    in_code_block = False
    for line in lines:
        stripped = line.strip()

        # Handle code blocks
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Skip pure-markdown structural lines
        if _MARKDOWN_RE.match(stripped):
            # For bullet points, keep the content without the bullet
            if stripped.startswith('- ') or stripped.startswith('* '):
                cleaned.append(stripped[2:])
            elif stripped.startswith('> '):
                cleaned.append(stripped[2:])
            # Drop headings, bold-only lines, rules
            continue

        # Convert inline markdown to plain text
        modified = _INLINE_MARKDOWN_RE.sub(
            lambda m: m.group(1) or m.group(2) or m.group(3), stripped
        )
        cleaned.append(modified)

    return '\n'.join(cleaned)


# ============================================================================
# BATCH ROUTING — Off-hours batch queue integration
# ============================================================================

def should_use_batch(tier: RoutingTier, force: bool = False) -> bool:
    """
    Decide whether to queue this draft for batch processing.

    Batch is used when ALL conditions are met:
      1. BATCH_API_ENABLED is True
      2. Current time is within batch window (off-hours / sleep / weekend)
      3. Tier is STANDARD or COMPLEX (SIMPLE uses templates, no LLM)
      4. Not a forced/manual request (user is waiting)
      5. LLM provider is Claude (batch API is Anthropic-specific)

    Returns:
        True if this draft should be queued for batch processing.
    """
    if force:
        return False

    if tier == RoutingTier.SIMPLE or tier == RoutingTier.SKIP:
        return False

    from app.config import BATCH_API_ENABLED, LLM_PROVIDER
    if not BATCH_API_ENABLED:
        return False

    if LLM_PROVIDER.lower() != "claude":
        return False

    from app.batch_queue import is_batch_window
    return is_batch_window()


def enqueue_for_batch(
    email_id: str,
    tier: RoutingTier,
    sender: str,
    subject: str,
    body: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    model: str = "",
    temperature: float = 0.35,
    account_id: int | str | None = None,
) -> str:
    """
    Enqueue a draft request for batch processing.

    Builds the prompt and adds it to the SQLite batch queue.
    The BatchWorker will submit it during the next micro-batch cycle.

    Returns:
        Queue item ID.
    """
    from app.batch_queue import get_batch_queue
    from app.config import CLAUDE_MODEL_LABEL

    if not model:
        model = CLAUDE_MODEL_LABEL  # Haiku for all tiers (cost-optimized)

    queue = get_batch_queue()
    item_id = queue.enqueue(
        email_id=email_id,
        account_id=str(account_id or ""),
        tier=tier.value,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        metadata={
            "sender": sender,
            "subject": subject,
            "body": body[:2000],
        },
    )

    logger.info(
        f"SmartRouter: queued {email_id} for batch ({tier.value}, model={model})"
    )
    return item_id


# ── Tone-sensitive detection for Sonnet routing ──────────────────────────

_TONE_SENSITIVE_RE = re.compile(
    r'\b('
    # Refus / déclin
    r'decline|refuse|cannot attend|regret(?:tably|fully)?|unfortunately'
    r'|d[ée]clin|refus|malheureusement|impossible|ne (?:pourr|peux|puis)'
    # Mauvaises nouvelles
    r'|bad news|sad to inform|regret to inform'
    r'|mauvaise nouvelle|triste|d[ée]c[èe]s|condol[ée]ances'
    # Conflit / plainte
    r'|complaint|disappointed|unacceptable|escalat'
    r'|plainte|d[ée][çc]u|inacceptable|r[ée]clamation'
    # Sensible RH
    r'|terminat|dismissal|resignation|disciplin'
    r'|licenciement|d[ée]mission|disciplinaire|avertissement'
    r')\b', re.IGNORECASE
)


def _is_tone_sensitive(body: str, subject: str, instructions: str = "") -> bool:
    """Detect emails that need nuanced emotional tone (refusal, bad news, HR, conflict)."""
    text = f"{subject} {body} {instructions}"
    return bool(_TONE_SENSITIVE_RE.search(text))
