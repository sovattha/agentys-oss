# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Gestion des prompts et de la base de connaissances.

Ce module charge le fichier memoire.md et fournit les templates
de prompts pour les agents Drafter et Critic.
"""

import re as _re
import time as _time
from functools import lru_cache as _lru_cache

from app.config import KNOWLEDGE_DIR
from app.prompts.loader import load_template
from app.prompts.identity import (  # noqa: F401
    _user_identity_cache, _extract_user_identity, _extract_user_name,
    _extract_language_variant,
    _variant_to_rule,
    _extract_preferred_language,
    invalidate_identity_cache, _is_person_name, _is_likely_feminine,
    _clean_sender_name, _compute_greeting_hint,
    _UNDEFINED_PLACEHOLDERS, _NON_PERSON_WORDS,
)
from app.prompts.helpers import (  # noqa: F401
    extract_sent_examples, extract_user_formulas, compute_style_metrics,
    classify_intent, analyze_email_formality, formality_to_temperature,
    _cache_key, _get_fewshot_section,
)

# Pre-compiled regex for knowledge base entry extraction (compile once at module load)
_KB_ENTRIES_RE = _re.compile(
    r'^###\s+(.+?)\s*\n((?:(?!^##).+\n?)*)',
    _re.MULTILINE,
)

# Cache for _extract_knowledge_answer results: key → (answer, timestamp)
_KB_ANSWER_CACHE: dict = {}
_KB_ANSWER_CACHE_TTL = 300  # 5 minutes

# ============================================================================
# CONTENU PAR DÉFAUT DE LA MÉMOIRE
# ============================================================================

DEFAULT_KNOWLEDGE = load_template("default_knowledge")

# ============================================================================
# CHARGEMENT DE LA BASE DE CONNAISSANCES
# ============================================================================

_kb_cache = {"content": None, "timestamp": 0}
_KB_CACHE_TTL = 300  # 5 minutes


def load_knowledge_base() -> str:
    """
    Charge le fichier memoire.md depuis le dossier /knowledge.

    .. deprecated::
        Utiliser ``load_knowledge_from_db(account_id)`` à la place.
        Cette fonction charge un fichier global partagé entre tous les comptes
        et sera supprimée après la migration complète vers la DB (#158).

    Returns:
        Le contenu de la base de connaissances (global, tous comptes confondus).
    """
    import warnings
    warnings.warn(
        "load_knowledge_base() charge le fichier global memoire.md. "
        "Utiliser load_knowledge_from_db(account_id) pour isoler les données par compte.",
        DeprecationWarning,
        stacklevel=2,
    )
    now = _time.time()
    if _kb_cache["content"] is not None and (now - _kb_cache["timestamp"]) < _KB_CACHE_TTL:
        return _kb_cache["content"]

    knowledge_file = KNOWLEDGE_DIR / "memoire.md"

    # Créer le dossier si nécessaire
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    # Si le fichier n'existe pas, créer avec contenu par défaut
    if not knowledge_file.exists():
        knowledge_file.write_text(DEFAULT_KNOWLEDGE, encoding="utf-8")
        print(f"[OK] Fichier mémoire.md créé avec contenu par défaut dans {KNOWLEDGE_DIR}")

    content = knowledge_file.read_text(encoding="utf-8")
    _kb_cache["content"] = content
    _kb_cache["timestamp"] = now
    return content


_KB_DB_CACHE: dict[int, tuple[str | None, float]] = {}
_KB_DB_CACHE_TTL = 600  # 10 minutes


def invalidate_kb_db_cache(account_id: int | None = None) -> None:
    """Clear the in-memory KB cache for one account or all accounts."""
    if account_id is None:
        _KB_DB_CACHE.clear()
    else:
        _KB_DB_CACHE.pop(account_id, None)


def load_knowledge_from_db(account_id: int) -> str | None:
    """Load knowledge base from completed onboarding results in DB.

    Memoized in-process for 10 min per account to avoid repeated DB hits
    on the hot draft path. Invalidated via invalidate_kb_db_cache() when
    onboarding is refreshed.

    Returns the markdown KB string, or None if no completed onboarding exists.
    """
    now = _time.time()
    cached = _KB_DB_CACHE.get(account_id)
    if cached is not None:
        value, ts = cached
        if now - ts < _KB_DB_CACHE_TTL:
            return value

    import json
    from app.db.database import get_db_session
    from app.db.repositories.onboarding_repository import OnboardingRepository
    from app.onboarding.manager import build_knowledge_markdown

    try:
        with get_db_session() as session:
            repo = OnboardingRepository(session)
            result = repo.get_completed_by_account(account_id)
            if not result:
                _KB_DB_CACHE[account_id] = (None, now)
                return None
            profile = json.loads(result.profile_json or "{}")
            knowledge = json.loads(result.knowledge_json or "{}")
            rules = json.loads(result.rules_json or "{}")
            value = build_knowledge_markdown(profile, knowledge, rules)
            _KB_DB_CACHE[account_id] = (value, now)
            return value
    except Exception:
        return None


def load_account_knowledge(account_id: int | None) -> str:
    """Load tenant-scoped KB; use global memoire.md only for legacy callers."""
    if account_id:
        return load_knowledge_from_db(account_id) or ""
    return load_knowledge_base() or ""


# ============================================================================
# TEMPLATES DE PROMPTS - DRAFTER AGENT
# ============================================================================

DRAFTER_SYSTEM_PROMPT = load_template("drafter_system_prompt")




DRAFTER_USER_PROMPT = load_template("drafter_user_prompt")


DRAFTER_USER_PROMPT_WITH_INSTRUCTIONS = load_template("drafter_user_prompt_with_instructions")


DRAFTER_CORRECTION_PROMPT = load_template("drafter_correction_prompt")


# ============================================================================
# TEMPLATES DE PROMPTS - CRITIC AGENT
# ============================================================================

CRITIC_SYSTEM_PROMPT = load_template("critic_system_prompt")


CRITIC_USER_PROMPT = load_template("critic_user_prompt")


# ============================================================================
# DRAFTER INTELLIGENCE — Extraction & Analysis helpers
# ============================================================================

import re as _re

# ── TTL cache for heavy per-draft computations ─────────────────────────
DRAFTER_USER_PROMPT_WITH_CONTEXT = load_template("drafter_user_prompt_with_context")






# ============================================================================
# TEMPLATES DE PROMPTS - CRITIC STRUCTURED EVALUATION (Story 5-2)
# ============================================================================

CRITIC_STRUCTURED_SYSTEM_PROMPT = load_template("critic_structured_system_prompt")

CRITIC_STRUCTURED_USER_PROMPT = load_template("critic_structured_user_prompt")




# ============================================================================
# TEMPLATES DE PROMPTS - DRAFTER REVISION WITH CRITIQUE (Story 5-3)
# ============================================================================

DRAFTER_REVISION_WITH_CRITIQUE_PROMPT = load_template("drafter_revision_with_critique_prompt")



# ============================================================================
# UNIFIED DRAFT PIPELINE — Classification + Draft + Self-Critique in 1 call
# ============================================================================

UNIFIED_DRAFT_SYSTEM_PROMPT = load_template("unified_draft_system_prompt")


UNIFIED_DRAFT_USER_PROMPT = load_template("unified_draft_user_prompt")




# ============================================================================
# STANDARD TIER PROMPTS — Smart Routing (Haiku-optimized, compact)
# ============================================================================

STANDARD_DRAFT_SYSTEM_PROMPT = load_template("standard_draft_system_prompt")

# Audit 2026-05-14 (P0.1): proven anti-slop guardrails extracted from the
# Drafter legacy prompt. Loaded as a standalone block so the SmartRouter
# STANDARD path can attach it to a stable, prompt-cacheable system segment.
# Three concurrent purposes:
#   1. Cache enablement — the STANDARD skeleton alone (~100 tok) sat below
#      Haiku's ~1024-tok prompt-cache floor (`cache_w=0` in prod telemetry).
#      Skeleton + KB + this block reliably crosses the floor.
#   2. Quality lift — the STANDARD path historically lacked the 12-pattern
#      anti-slop calibration the Drafter path had; that gap let regression
#      slop (sycophancy, recap, slop words) survive into the draft and get
#      stripped post-LLM, which leaves whitespace artefacts.
#   3. Source-of-truth — the post-LLM pipeline strips the same patterns; if
#      the prompt prevents them at the source, the pipeline is a safety net
#      rather than a primary cleaning step.
REPLY_QUALITY_GUARDRAILS = load_template("reply_quality_guardrails")

# P1.5 (2026-05-14): focused anti-slop guardrails for the compose path
# (`/api/emails/compose`). The reply guardrails reference "incoming email"
# and have CALIBRATION/MIRROR sections that are inert on cold-start
# compose; this template is the compose-applicable subset. Loaded as a
# stable constant so future compose-prompt revisions don't drift away
# from the proven anti-pattern list.
COMPOSE_QUALITY_GUARDRAILS = load_template("compose_quality_guardrails")

# ============================================================================
# INTENT-SPECIFIC RULE BLOCKS (Axe 4)
# ============================================================================
# Each intent gets only the FORBIDDEN rules it needs (6-10 instead of 27).
# Universal rules (language, hallucination, pronouns) are always included.

_UNIVERSAL_RULES = load_template("_universal_rules")

_LENGTH_RULE_MAP = {
    "concis":   "- Max ~50 words. Be direct and brief.",
    "moyen":    "- Max ~100 words. Cover what is needed, nothing more.",
    "detaille": "- Max ~150 words. Provide full context when required.",
}
_LENGTH_RULE_FALLBACK = (
    "- VERY CASUAL: a few words, like texting. No greeting.\n"
    "- CASUAL: 1-2 sentences.\n"
    "- FORMAL: 2-4 sentences."
)


def _build_length_rule(knowledge_base: str = "", has_context: bool = False) -> str:
    """Return RULE 4 length constraint.

    Priority: user's trained length preference (from memoire.md ## Format section)
    > context-aware fallback (stricter when replying with history/thread)
    > tone-based fallback (CASUAL/FORMAL sentence counts).
    """
    if knowledge_base:
        m = _re.search(
            r'\*\*Longueur pr[eé]f[eé]r[eé]e\*\*\s*:\s*(\w+)',
            knowledge_base,
            _re.IGNORECASE,
        )
        if m:
            rule = _LENGTH_RULE_MAP.get(m.group(1).lower())
            if rule:
                return rule
    if has_context:
        return (
            "- VERY CASUAL: a few words, like texting. No greeting.\n"
            "- CASUAL: 1-2 sentences.\n"
            "- FORMAL: 2-3 sentences.\n"
            "- Do NOT summarize or repeat what the sender wrote."
        )
    return _LENGTH_RULE_FALLBACK


# Vocabulary / complexity directive. Wires the Training "Complexité" control
# (simple/standard/avancé → accessible/standard/elabore) into the live draft
# rules. Before this, the value was stored in the KB (## Format /
# **Vocabulaire**) and round-tripped on every save but never read into any
# prompt — a control the UI implied affected style yet did nothing. "standard"
# is the neutral default and intentionally emits NO directive (no prompt bloat).
_VOCAB_RULE_MAP = {
    "accessible": (
        "- VOCABULARY: short, plain sentences (aim < 12 words). "
        "Everyday words — avoid jargon and elaborate constructions."
    ),
    "elabore": (
        "- VOCABULARY: richer, more structured prose is welcome; "
        "precise or technical vocabulary is fine when it fits the topic."
    ),
}


def _build_vocab_rule(knowledge_base: str = "") -> str:
    """Return the vocabulary/complexity directive from the user's trained
    ``**Vocabulaire**`` preference (memoire.md ## Format), or ``""`` when unset
    or set to the neutral "standard". Mirrors :func:`_build_length_rule`.
    """
    if knowledge_base:
        m = _re.search(
            r'\*\*Vocabulaire\*\*\s*:\s*(\w+)',
            knowledge_base,
            _re.IGNORECASE,
        )
        if m:
            return _VOCAB_RULE_MAP.get(m.group(1).lower(), "")
    return ""

_INTENT_RULES = {
    "action": """ANTI-ECHO rules:
- If the email lists N items → say "I acknowledge the N items" or answer each in ≤5 words. Do NOT copy the list.
- For requests → say yes/no + your next step. Do NOT describe the request back.
- NEVER start a sentence with "Regarding your...", "Concerning...", "As for your...".

FORBIDDEN:
- Filler: "C'est parti", "Voici ma réponse", "Sure thing!", "Super !"
- Meta-commentary: "Regarding your email...", "In response to..."
- AI self-reference: "I'd be happy to help", "Happy to help"
- Corporate bloat: "Thank you for reaching out", "Looking forward to hearing from you"
- Sentences that describe what the sender said instead of what YOU will do
- Copying enumerated lists from the email
- Sycophancy: "That's a great question", "Excellent point"
- Empty promises: "I'll get back to you soon"
- Signature or sign-off name""",

    "question": """DATA RECALL rules:
- If the sender asks a question and the answer is in the conversation history, answer with EXACT data (copy numbers, names, dates VERBATIM).
- ANSWER NATURALLY: GIVE the answer in your first sentence. Do NOT say "Je vais vérifier" or "I'll look into".
- Do NOT describe your search ("Je trouve", "J'ai trouvé"). Reference the SENDER ("tu m'avais mentionné"), not the email.
- Financial metrics from knowledge base or history → use them confidently. Only hedge if you are INVENTING numbers.

FORBIDDEN:
- Process-description: "Je trouve", "J'ai trouvé", "I found", "After reviewing"
- Email-object references: "du mail du", "de l'email du", "from the email of"
- Hedging: "I think", "perhaps", "maybe", "it might be" — be DIRECT
- AI slop: "delve", "navigate", "leverage", "tapestry", "pivotal"
- Invented data (numbers, dates, prices not in the original email)
- Recap/summary: never end with "In summary..." or "Pour résumer..."
- Signature or sign-off name""",

    "decline": """DECLINE rules:
- Decline politely but clearly. No excessive apologizing.
- Suggest an alternative when possible.
- Keep it brief — 2-3 sentences max.

FORBIDDEN:
- Excessive apologies: max 1 "sorry/désolé" per email
- Sycophancy: "That's a great question", "You're absolutely right"
- False empathy: "I understand your frustration", "I can imagine"
- Corporate bloat: "I appreciate your patience", "Thank you for your understanding"
- Redundant affirmations: max 1 "absolutely/certainly" per email
- "Not just X, but also Y" — write simply: "X and Y"
- Signature or sign-off name""",

    "scheduling": """SCHEDULING rules:
- USE the exact dates, times, and locations from the email. Do NOT replace them with placeholders.
- Confirm availability clearly. Propose alternative if not available.
- Keep it ultra-short: 1-2 sentences.

FORBIDDEN:
- Invented times/dates/locations not in the email
- Placeholders for facts that ARE in the email (dates, times)
- Filler: "C'est parti", "Looking forward to it"
- Over-promising: do not add agenda items or preparation not asked
- Empty promises: "I'll get back to you soon"
- Unnecessary questions about details already in the email
- Signature or sign-off name""",

    "acknowledgment": """ACKNOWLEDGMENT rules:
- Ultra-short: 1 sentence max. "Bien reçu, merci." / "Got it, thanks."
- No filler, no elaboration, no questions.

FORBIDDEN:
- Any sentence beyond the acknowledgment itself
- Filler: "C'est parti", "Super !", "Great!"
- Meta-commentary: "Regarding your email..."
- AI self-reference: "Happy to help"
- Questions of any kind
- Signature or sign-off name""",
}


def _get_intent_rules(intent: str) -> str:
    """Get the intent-specific FORBIDDEN rules block."""
    return _INTENT_RULES.get(intent, _INTENT_RULES["action"])

STANDARD_DRAFT_USER_PROMPT = load_template("standard_draft_user_prompt")


def _extract_data_hint(history_items: list[dict], question_body: str) -> str:
    """
    Extract key data points from conversation history that likely answer the question.

    Pulls numbers, amounts, dates, sequences from history email bodies and returns
    them as a compact hint string the LLM can reference directly.

    Returns empty string if no useful data found.
    """
    import re as _re

    if not history_items:
        return ""

    q_lower = question_body.lower()
    hints = []

    for h in history_items:
        body = (h.get("body") or h.get("body_preview") or "").strip()
        if not body or body.endswith("?"):
            continue  # Skip items that are themselves questions

        subj = h.get("subject", "")

        # Extract sequences of numbers (e.g. "1 2 3", "10, 20, 30")
        number_sequences = _re.findall(r'(?:\d+(?:[.,]\d+)?[\s,;-]+){1,}\d+(?:[.,]\d+)?', body)
        for seq in number_sequences:
            nums = _re.findall(r'\d+(?:[.,]\d+)?', seq)
            if len(nums) >= 2:
                hints.append(f"from '{subj}': {', '.join(nums)}")

        # Extract standalone numbers not in a sequence (amounts, codes)
        all_nums = _re.findall(r'\b\d+(?:[.,]\d+)?\b', body)
        # Also extract dollar/euro amounts
        amounts = _re.findall(r'[\$€]\s*[\d,]+(?:\.\d{2})?', body)
        for a in amounts:
            hints.append(f"from '{subj}': {a}")

        # If asking about "chiffres" / "numbers" and we found numbers, include them in order
        if ("chiffre" in q_lower or "number" in q_lower or "code" in q_lower) and all_nums:
            ordered = ", ".join(all_nums)
            hint = f"from '{subj}': {ordered} (in this order)"
            if hint not in hints:
                hints.append(hint)

    # Deduplicate and limit
    seen = set()
    unique = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            unique.append(h)

    return " | ".join(unique[:3]) if unique else ""


def _build_answer_template(data_hint: str, language: str) -> str:
    """
    Build a natural-language answer sentence from extracted data.

    Converts "from 'test 1': 1, 2, 3 (in this order)" into
    "Les chiffres sont 1, 2 et 3." (FR) or "The numbers are 1, 2 and 3." (EN).

    Returns empty string if the hint is too complex to template.
    """
    import re as _re

    # Extract the actual data values from the first hint segment
    # Format: "from 'subject': value1, value2, ..."
    match = _re.search(r":\s*(.+?)(?:\s*\(|$|\s*\|)", data_hint)
    if not match:
        return ""

    data_part = match.group(1).strip().rstrip(",")
    # Check it's a simple comma-separated list of values
    values = [v.strip() for v in data_part.split(",") if v.strip()]
    if not values or len(values) > 10:
        return ""

    # Build natural list: "1, 2 et 3" or "1, 2 and 3"
    if language == "FRENCH":
        if len(values) == 1:
            natural = values[0]
        elif len(values) == 2:
            natural = f"{values[0]} et {values[1]}"
        else:
            natural = ", ".join(values[:-1]) + f" et {values[-1]}"
        return f"Les chiffres sont {natural}."
    else:
        if len(values) == 1:
            natural = values[0]
        elif len(values) == 2:
            natural = f"{values[0]} and {values[1]}"
        else:
            natural = ", ".join(values[:-1]) + f" and {values[-1]}"
        return f"The numbers are {natural}."


def _extract_knowledge_answer(knowledge_base: str, question_body: str) -> str:
    """
    Search knowledge base for entries matching the email content.

    Supports two knowledge base formats:
        1. Q&A format:  ### Question heading?  \\n  Answer text
        2. Topic format: ### Topic : Label  \\n  Description text

    Returns the best matching answer/description, empty string otherwise.
    Uses word overlap between the email body and each knowledge heading+answer.
    Results are cached for 5 minutes (TTL) to avoid repeated KB scans.
    """
    if not knowledge_base:
        return ""

    q_lower = question_body.lower().strip()
    q_words = set(_re.findall(r'\b\w{3,}\b', q_lower))
    if not q_words:
        return ""

    # Cache lookup — key combines KB hash + first 100 chars of question
    cache_key = f"{hash(knowledge_base)}:{q_lower[:100]}"
    cached = _KB_ANSWER_CACHE.get(cache_key)
    if cached is not None:
        answer, ts = cached
        if _time.time() - ts < _KB_ANSWER_CACHE_TTL:
            return answer

    best_answer = ""
    best_score = 0.0
    # Q&A entries (heading ends with ?) get a threshold of 0.4
    # Topic entries (no ?) get a higher threshold of 0.5 to avoid false matches
    matched_entries = []

    for m in _KB_ENTRIES_RE.finditer(knowledge_base):
        heading = m.group(1).strip()
        answer = m.group(2).strip()
        if not answer:
            continue

        heading_lower = heading.lower()
        is_qa = heading.endswith("?")

        # Match against heading AND answer text for broader relevance
        h_words = set(_re.findall(r'\b\w{3,}\b', heading_lower))
        a_words = set(_re.findall(r'\b\w{3,}\b', answer.lower()))
        combined_words = h_words | a_words

        # Also include context metadata if present (<!-- context: ... -->)
        ctx_match = _re.search(r'<!--\s*context:\s*(.+?)-->', answer)
        if ctx_match:
            ctx_words = set(_re.findall(r'\b\w{3,}\b', ctx_match.group(1).lower()))
            combined_words |= ctx_words

        if not combined_words:
            continue

        overlap = len(q_words & combined_words)
        score = overlap / max(len(q_words), len(combined_words))

        # Q&A entries have lower threshold (more likely to be direct answers)
        threshold = 0.3 if is_qa else 0.35
        if score > best_score and score >= threshold:
            best_score = score
            best_answer = answer
            matched_entries.append((heading, answer, score))

    # If multiple entries matched, combine them for richer context
    if len(matched_entries) > 1:
        # Sort by score descending, take top 3
        matched_entries.sort(key=lambda x: x[2], reverse=True)
        parts = []
        for heading, answer, _score in matched_entries[:3]:
            parts.append(f"[{heading}] {answer}")
        result = "\n".join(parts)
    else:
        result = best_answer

    _KB_ANSWER_CACHE[cache_key] = (result, _time.time())
    return result


_EN_MARKERS = (
    "dear ", "hi ", "hey ", "hello ", "thanks", "thank you",
    "please ", "would you", "could you", "can you",
    "best regards", "sincerely", "kind regards", "cheers",
    " the ", " is ", " are ", " was ", " have ", " has ",
    " this ", " that ", " with ", " for ", " from ",
    " i ", " we ", " you ", " my ", " your ", " our ",
    " am ", " do ", " will ", " be ", " an ", " it ",
    "meeting", "available", "schedule", "follow",
    "dude", "wanna", "gonna", "yeah", "sure",
    " next ", " think", " want", " know", " get ",
)
_FR_MARKERS = (
    "bonjour", "salut", "cher ", "chere ", "merci",
    "cordialement", "s'il vous", "pourriez", "pouvez",
    " le ", " la ", " les ", " des ", " est ", " sont ",
    " avec ", " pour ", " dans ", " que ", " qui ",
    " tu ", " nous ", " vous ", " je ", " mon ", " ton ",
    "bonne ", "bien ", "aussi",
)


def _detect_language(text: str, fallback_language: str = "FRENCH") -> str:
    """
    Simple heuristic language detection for email text.

    Returns 'ENGLISH' or 'FRENCH'. When the text is empty or the marker
    counts are tied, returns ``fallback_language`` — intended to be set to
    the user's onboarding-detected primary language ('ENGLISH' for EN
    clients) so ambiguous short emails don't default to French.
    """
    text_lower = text.lower()

    en_count = sum(1 for m in _EN_MARKERS if m in text_lower)
    fr_count = sum(1 for m in _FR_MARKERS if m in text_lower)

    if en_count > fr_count:
        return "ENGLISH"
    if fr_count > en_count:
        return "FRENCH"
    return fallback_language


def load_primary_language_for_account(account_id: int | None) -> str:
    """Return the user's onboarding-detected primary language as a drafter
    label ('ENGLISH' or 'FRENCH'). Falls back to 'FRENCH' on any failure so
    callers can use the result unconditionally as a ``fallback_language``.

    Reads from ``onboarding_results.profile_json`` where the orchestrator
    persists ``primary_language``. Short-circuits on missing ``account_id``.
    """
    if not account_id:
        return "FRENCH"
    try:
        import json as _json
        from app.db.database import get_db_session
        from app.db.models.onboarding_result import OnboardingResult
        with get_db_session() as session:
            row = (
                session.query(OnboardingResult)
                .filter(OnboardingResult.account_id == int(account_id))
                .order_by(OnboardingResult.id.desc())
                .first()
            )
            if not row or not row.profile_json:
                return "FRENCH"
            profile = _json.loads(row.profile_json) or {}
            lang = str(profile.get("primary_language") or "fr").lower()
            return "ENGLISH" if lang == "en" else "FRENCH"
    except Exception:
        return "FRENCH"


import re as _re_prompts
from app.prompts.loader import load_template

_TRANSLATION_RE = _re_prompts.compile(
    r"(?:"
    r"tradui(?:s|re|t|sez)\s+(?:(?:le\s+|la\s+|l'|ce\s+|cet?\s+)?(?:email|mail|message|réponse|brouillon|draft|texte)\s+)?en\s+"
    r"|translate\s+(?:(?:the\s+|this\s+)?(?:email|mail|message|reply|draft|text)\s+)?(?:to|into)\s+"
    r"|(?:écri[st]|rédige[sz]?|répond[sz]?|write|reply|respond)\s+(?:(?:le|la|en|in|the)\s+)?(?:email\s+|mail\s+|message\s+|réponse\s+|draft\s+)?(?:en|in)\s+"
    r"|(?:en|in)\s+(?=(?:anglais|français|english|french|spanish|espagnol|italian|italien|portuguese|portugais))"
    r")",
    _re_prompts.IGNORECASE,
)

_LANG_NAMES = {
    "anglais": "ENGLISH", "english": "ENGLISH",
    "français": "FRENCH", "francais": "FRENCH", "french": "FRENCH",
    "espagnol": "SPANISH", "spanish": "SPANISH",
    "italien": "ITALIAN", "italian": "ITALIAN",
    "portugais": "PORTUGUESE", "portuguese": "PORTUGUESE",
}


def _detect_language_override(instructions: str) -> str | None:
    """
    Detect if user instructions explicitly request a language change (translation).

    Returns the target language (e.g. "ENGLISH") if found, or None if no
    translation was requested. This allows the user to override the default
    behaviour of matching the email's language.
    """
    if not instructions:
        return None

    m = _TRANSLATION_RE.search(instructions)
    if not m:
        return None

    # Extract what follows the match to find the target language
    after = instructions[m.end():].strip().split()[0].lower().rstrip(".,;:!?") if instructions[m.end():].strip() else ""
    if after in _LANG_NAMES:
        return _LANG_NAMES[after]

    # Also check if the matched group itself ended with the language name
    # e.g. "en anglais" where "en" is part of the regex and "anglais" is after
    return None


@_lru_cache(maxsize=1000)
def _extract_display_name(sender: str) -> str:
    """
    Extract a human-readable display name from a sender string.

    Handles formats like:
      - "John Doe <john@example.com>" -> "John Doe"
      - "john.doe@example.com" -> "John Doe"
      - "alexandre.simon@hotmail.com" -> "Alexandre Simon"
      - "noreply@example.com" -> ""

    Memoized (LRU 1000) — same `sender` is parsed up to three times per
    drafted email today (DrafterAgent.draft_with_context, _generate_standard,
    _compute_greeting_hint), so the cache hit-rate is high. The function
    is pure, so the cache is correct in all cases. 1000 entries × ~80 bytes
    each ≈ 80kB resident max — negligible.
    """
    # Try to extract name before <email>
    if "<" in sender:
        name = sender.split("<")[0].strip().strip('"').strip("'")
        if name and "@" not in name:
            return name

    # Extract from email prefix: john.doe@ -> John Doe
    email = sender.strip().lower()
    if "@" in email:
        prefix = email.split("@")[0]
        # Skip automated senders
        if prefix in ("noreply", "no-reply", "notifications", "info", "contact", "support"):
            return ""
        # Replace separators with spaces and capitalize
        name = prefix.replace(".", " ").replace("-", " ").replace("_", " ")
        parts = [p.capitalize() for p in name.split() if p]
        return " ".join(parts)

    return sender.strip()



# ============================================================================
# COMBINED LABEL + DRAFT PROMPT — Smart Routing (single Haiku call)
# ============================================================================

CLASSIFY_AND_DRAFT_SYSTEM_PROMPT = load_template("classify_and_draft_system_prompt")

CLASSIFY_AND_DRAFT_USER_PROMPT = load_template("classify_and_draft_user_prompt")

