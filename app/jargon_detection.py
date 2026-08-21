"""
Jargon detection from user draft corrections.

When a user corrects an AI draft by adding domain-specific terms,
acronyms, or jargon that the AI didn't use, this module detects them
and returns suggestions for the knowledge glossary.

Detection strategy:
1. Word-level diff between original AI draft and user-sent version
2. Filter for jargon patterns: acronyms (ALL CAPS), compound terms, unknown words
3. Only suggest terms that appear 2+ times in the user's sent history (frequency guard)
"""

import re
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional

logger = logging.getLogger(__name__)

# Acronym: 2-6 uppercase letters, optionally with digits (e.g., ARR, KPI, SLA, B2B)
ACRONYM_RE = re.compile(r'^[A-Z][A-Z0-9]{1,5}$')

# Common French/English words to exclude (not jargon)
STOP_WORDS = frozenset({
    # French
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux",
    "et", "ou", "mais", "donc", "car", "ni", "que", "qui", "quoi",
    "ce", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "notre", "votre", "leur", "leurs",
    "ne", "pas", "plus", "rien", "jamais", "bien", "très", "aussi",
    "avec", "pour", "dans", "sur", "sous", "par", "entre", "chez",
    "est", "sont", "sera", "été", "avoir", "être", "fait", "faire",
    "bon", "bonne", "merci", "bonjour", "cordialement", "bonsoir",
    # English
    "the", "is", "are", "was", "were", "have", "has", "had",
    "will", "would", "could", "should", "can", "may", "might",
    "and", "but", "or", "not", "with", "for", "from", "this", "that",
    "hello", "thanks", "regards", "best", "dear", "please",
})

# Words that look like acronyms but aren't jargon
FALSE_POSITIVE_ACRONYMS = frozenset({
    "OK", "PS", "NB", "CC", "BCC", "RE", "FW", "FYI",
    "AM", "PM", "TV", "PC", "USB", "PDF", "URL", "HTTP", "HTTPS",
    "CEO", "CTO", "CFO", "COO", "VP", "RH", "IT", "AI", "IA",
})

MIN_TERM_LENGTH = 2
MAX_SUGGESTIONS = 2


@dataclass
class JargonSuggestion:
    term: str       # The detected jargon term (e.g., "ARR")
    context: str    # Surrounding sentence from the user's version


def _extract_added_words(original: str, sent: str) -> List[str]:
    """Extract words that the user added (not in the original draft)."""
    orig_words = original.split()
    sent_words = sent.split()

    matcher = SequenceMatcher(None, orig_words, sent_words)
    added: List[str] = []

    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(sent_words[j1:j2])

    return added


def _is_jargon_candidate(word: str) -> bool:
    """Check if a word looks like domain jargon."""
    clean = word.strip(".,;:!?()[]{}\"'«»—–-")

    if len(clean) < MIN_TERM_LENGTH:
        return False

    if clean.lower() in STOP_WORDS:
        return False

    # Acronym pattern (strongest signal)
    if ACRONYM_RE.match(clean) and clean not in FALSE_POSITIVE_ACRONYMS:
        return True

    return False


def _extract_sentence(text: str, word: str) -> str:
    """Extract the sentence containing the word for context."""
    sentences = re.split(r'[.!?\n]+', text)
    for sentence in sentences:
        if word in sentence:
            return sentence.strip()[:150]
    return ""


def _count_in_sent_history(term: str, sent_emails: Optional[List[str]] = None) -> int:
    """Count how many sent emails contain this term."""
    if not sent_emails:
        return 0
    count = 0
    term_lower = term.lower()
    for body in sent_emails:
        if term_lower in body.lower():
            count += 1
    return count


def detect_jargon_from_correction(
    original_draft: str,
    sent_body: str,
    existing_terms: Optional[List[str]] = None,
    sent_emails: Optional[List[str]] = None,
) -> List[JargonSuggestion]:
    """
    Detect jargon/acronyms the user added when correcting an AI draft.

    Args:
        original_draft: The AI-generated draft
        sent_body: The version the user actually sent
        existing_terms: Terms already in the glossary (to avoid duplicates)
        sent_emails: Recent sent email bodies (for frequency validation)

    Returns:
        List of jargon suggestions (max MAX_SUGGESTIONS)
    """
    if not original_draft or not sent_body:
        return []

    # Quick exit: no significant changes
    if abs(len(original_draft) - len(sent_body)) < 3:
        ratio = SequenceMatcher(None, original_draft, sent_body).quick_ratio()
        if ratio > 0.95:
            return []

    existing_set = {t.upper() for t in (existing_terms or [])}

    added_words = _extract_added_words(original_draft, sent_body)
    if not added_words:
        return []

    seen: set[str] = set()
    suggestions: List[JargonSuggestion] = []

    for word in added_words:
        clean = word.strip(".,;:!?()[]{}\"'«»—–-")

        if not _is_jargon_candidate(clean):
            continue

        upper = clean.upper()
        if upper in seen or upper in existing_set:
            continue

        # Frequency guard: term should appear in 2+ sent emails (if history available)
        if sent_emails and _count_in_sent_history(clean, sent_emails) < 2:
            continue

        seen.add(upper)
        context = _extract_sentence(sent_body, clean)

        suggestions.append(JargonSuggestion(
            term=clean,
            context=context,
        ))

        if len(suggestions) >= MAX_SUGGESTIONS:
            break

    return suggestions
