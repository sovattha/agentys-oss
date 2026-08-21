"""
FAQ Agent — auto-replies to emails matching FAQ knowledge base entries.

Flow:
1. Load FAQ entries for the account
2. Score email body against each FAQ entry (word-overlap)
3. If best match confidence >= threshold → generate response via Haiku → auto-send
4. If below threshold → skip (email treated normally)
5. Log the decision for dashboard stats
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FaqMatch:
    entry_id: str
    entry_title: str
    entry_content: str
    score: float  # 0.0 – 100.0


@dataclass
class FaqResult:
    action: str  # "auto_sent" | "skipped"
    confidence: float
    matched_entry_id: Optional[str] = None
    matched_entry_title: Optional[str] = None
    draft_body: Optional[str] = None
    sent_message_id: Optional[str] = None  # ID of the sent reply (for labeling)


# ── Word-overlap scoring ─────────────────────────────────────────────────────

_STOP_WORDS_FR = frozenset([
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en",
    "je", "tu", "il", "nous", "vous", "ils", "ce", "qui", "que", "est",
    "sont", "a", "au", "aux", "par", "pour", "dans", "sur", "avec", "ne",
    "pas", "se", "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
    "cette", "ces", "mais", "si", "bien", "plus", "aussi", "très", "tout",
    "on", "me", "te", "lui", "leur", "dont", "où", "quand", "comme",
])

_STOP_WORDS_EN = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "because", "but", "and", "or", "if",
    "it", "its", "i", "me", "my", "we", "you", "your", "he", "she",
    "they", "them", "this", "that", "these", "those", "what", "which",
])

_STOP_WORDS = frozenset(
    w.replace("è", "e").replace("é", "e").replace("ê", "e").replace("à", "a").replace("ù", "u").replace("ô", "o").replace("î", "i").replace("ç", "c")
    for w in (_STOP_WORDS_FR | _STOP_WORDS_EN)
)

_WORD_RE = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)


def _normalize_accents(text: str) -> str:
    """Strip diacritics so modèle == modele, derrière == derriere."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokenize(text: str) -> set[str]:
    normalized = _normalize_accents(text.lower())
    words = set(_WORD_RE.findall(normalized))
    return words - _STOP_WORDS


def score_faq_match(email_text: str, faq_title: str, faq_content: str) -> float:
    """
    Score how well an email matches a FAQ entry using word-overlap.

    Returns a score 0–100.
    Uses separate title/content ratios to avoid penalising rich FAQ answers:
    a perfect title match always scores ≥70 regardless of content length.
    """
    email_words = _tokenize(email_text)
    if not email_words:
        return 0.0

    title_words = _tokenize(faq_title)
    content_words = _tokenize(faq_content)

    if not title_words and not content_words:
        return 0.0

    title_overlap = len(email_words & title_words)
    content_overlap = len(email_words & content_words)

    # Independent ratios (0-1) — not penalised by the other field's size
    title_ratio = title_overlap / len(title_words) if title_words else 0.0
    content_ratio = content_overlap / len(content_words) if content_words else 0.0

    # Combine: title 70 %, content 30 %
    if title_words and content_words:
        raw_score = title_ratio * 0.7 + content_ratio * 0.3
    elif title_words:
        raw_score = title_ratio
    else:
        raw_score = content_ratio

    # High-component boost: if email is a near-perfect match of EITHER the
    # title OR the content (≥ 80 % of words overlap), boost score to 75 %.
    # This handles emails that paraphrase the FAQ answer as a question
    # (e.g., body = "Agentys utilise Claude comme intelligence artificielle?").
    # The "?" question bonus then pushes the score above the 80 % threshold.
    high_component = max(title_ratio, content_ratio)
    if high_component >= 0.8:
        raw_score = max(raw_score, high_component * 0.75)

    # Bonus: if email contains a question mark and FAQ title is a question
    if "?" in email_text and "?" in faq_title:
        raw_score = min(1.0, raw_score * 1.15)

    return round(raw_score * 100, 1)


def find_relevant_faqs_for_drafter(
    email_subject: str,
    email_body: str,
    faq_entries: list[dict],
    threshold: float = 30.0,
    max_entries: int = 3,
) -> list[FaqMatch]:
    """
    Return top FAQ matches for drafter grounding (NOT for auto-reply).

    Uses the same word-overlap scoring as match_faq_entries() but with a
    much more permissive threshold (30 vs 80). Rationale:
    - Auto-reply (80%): "I'm SURE, I'll send without review" → strict
    - Drafter grounding (30%): "this MIGHT be relevant, the LLM will judge" → permissive

    Capped at max_entries to control prompt token budget. Sorted by score desc.
    """
    matches = match_faq_entries(email_body, email_subject, faq_entries, threshold)
    return matches[:max_entries]


def match_faq_entries(
    email_body: str,
    email_subject: str,
    faq_entries: list[dict],
    threshold: float = 80.0,
) -> list[FaqMatch]:
    """
    Match email against FAQ entries and return sorted matches above threshold.
    """
    email_text = f"{email_subject} {email_body}"
    matches = []

    for entry in faq_entries:
        score = score_faq_match(
            email_text,
            entry.get("title", ""),
            entry.get("content", ""),
        )
        if score >= threshold:
            matches.append(FaqMatch(
                entry_id=entry["id"],
                entry_title=entry.get("title", ""),
                entry_content=entry.get("content", ""),
                score=score,
            ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def match_and_generate_faq_with_llm(
    email_body: str,
    email_subject: str,
    sender_name: str,
    faq_entries: list[dict],
    tone: str = "professional",
    threshold: float = 80.0,
) -> tuple[Optional[FaqMatch], Optional[str]]:
    """Match + generate response in 1 LLM call (P1.5 fusion).

    Audit 2026-05-04 : avant cette fusion, `process_faq_email` faisait 2 appels
    Haiku séquentiels (`match_faq_with_llm` puis `generate_faq_response`),
    soit 2 RTT + 2 system prompts. La fusion économise :
      - 1 RTT (~400-800ms gagnés sur le path FAQ)
      - 1 system prompt à payer en input tokens (~150 tokens × 2 → 1)
      - Mieux exploite le cache : un seul system prompt stable est cacheable

    Le LLM retourne directement {faq_index, confidence, response} en JSON.
    Si match=NONE → on retombe sur match_faq_entries (word-overlap) sans
    appeler le générateur (puisqu'aucun match → pas de response à générer).

    Returns:
        (FaqMatch | None, response_body | None) : matched entry + body if
        the LLM matched. (None, None) if no match. Falls back to None on
        LLM failure — caller should treat as "skipped".
    """
    if not faq_entries or not (email_body or email_subject):
        return None, None

    tone_instructions = {
        "professional": "Réponds de manière professionnelle et courtoise.",
        "friendly": "Réponds de manière amicale et chaleureuse.",
        "concise": "Réponds de manière très concise et directe.",
    }
    tone_instruction = tone_instructions.get(tone, tone_instructions["professional"])

    faq_lines = []
    for i, entry in enumerate(faq_entries, 1):
        title = entry.get("title", "")
        content = entry.get("content", "")
        faq_lines.append(f"{i}. {title}\n   Réponse : {content}")

    system_prompt = (
        "Tu reçois un email entrant et une liste de FAQ numérotées (avec leur réponse). "
        "Ta tâche en UN SEUL appel : (1) identifier la FAQ qui correspond le mieux, "
        "(2) si match : rédiger la réponse email basée UNIQUEMENT sur la réponse FAQ. "
        f"{tone_instruction} "
        "Ne jamais inventer d'info hors FAQ. Réponds dans la même langue que l'email reçu. "
        "Pas de formule de politesse excessive, va droit au but.\n\n"
        "Format JSON STRICT (rien avant/après) :\n"
        '{"faq_index": <int 1..N ou 0 si aucun match>, "confidence": <0.0-1.0>, '
        '"response": "<corps de l\'email, ou chaîne vide si faq_index=0>"}'
    )

    user_prompt = (
        f"Email reçu :\n"
        f"De : {sender_name}\n"
        f"Sujet : {email_subject}\n"
        f"Corps : {email_body}\n\n"
        f"FAQ disponibles :\n" + "\n\n".join(faq_lines)
    )

    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        from app.utils.json_parser import extract_json_from_response

        llm = get_container().llm_background
        with llm_attribution("faq_match_generate", feature="faq_auto_reply"):
            response = llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=512,
                temperature=0.0,
            )
        data = extract_json_from_response(
            response.content,
            default={"faq_index": 0, "confidence": 0.0, "response": ""},
            error_context="FaqAgent.match_and_generate",
        )

        idx = int(data.get("faq_index", 0) or 0)
        if idx < 1 or idx > len(faq_entries):
            return None, None

        confidence = float(data.get("confidence", 0.0) or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        # Confidence is reported 0-1 by the LLM; FaqMatch.score is 0-100.
        score = round(confidence * 100, 1)

        # Apply threshold consistently with the legacy 2-call path.
        if score < threshold:
            return None, None

        entry = faq_entries[idx - 1]
        match = FaqMatch(
            entry_id=entry["id"],
            entry_title=entry.get("title", ""),
            entry_content=entry.get("content", ""),
            score=score,
        )
        body = (data.get("response") or "").strip()
        if not body:
            # LLM matched but didn't produce a body — trust the match,
            # fall back to raw FAQ content (safer than re-prompting).
            body = entry.get("content", "")
        return match, body

    except Exception as exc:
        logger.warning("[FaqAgent] match_and_generate failed, falling back: %s", exc)
        return None, None


def match_faq_with_llm(
    email_body: str,
    email_subject: str,
    faq_entries: list[dict],
    threshold: float = 80.0,
) -> list[FaqMatch]:
    """
    Match email against FAQ entries using LLM semantic understanding.
    Falls back to word-overlap (match_faq_entries) if LLM call fails.

    Returns list of FaqMatch (0 or 1 element) with score=95.0 on LLM match.

    .. deprecated:: 2026-05-04
        Use :func:`match_and_generate_faq_with_llm` instead — combines this
        call with :func:`generate_faq_response` to save 1 RTT + 1 system
        prompt. Kept for callers that need match-only (no body generation).
    """
    if not faq_entries or not (email_body or email_subject):
        return []

    # Build numbered FAQ list for the prompt
    faq_lines = []
    for i, entry in enumerate(faq_entries, 1):
        faq_lines.append(f"{i}. {entry.get('title', '')}")

    system_prompt = (
        "Tu reçois un email et une liste de questions FAQ numérotées. "
        "Réponds UNIQUEMENT avec le numéro de la FAQ qui correspond le mieux "
        "à la question posée dans l'email. "
        "Si aucune FAQ ne correspond, réponds NONE. "
        "Pas d'explication, juste le numéro ou NONE."
    )

    user_prompt = (
        f'Email: "{email_subject} {email_body}"\n\n'
        f"FAQ:\n" + "\n".join(faq_lines)
    )

    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        # Background FAQ matcher — routes to ANTHROPIC_API_KEY_BACKGROUND.
        llm = get_container().llm_background
        with llm_attribution("faq_match", feature="faq_auto_reply"):
            response = llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=8,
                temperature=0.0,
            )
        raw = response.content.strip() if hasattr(response, "content") else str(response).strip()
        logger.info("[FaqAgent] LLM match response: %s", raw)

        if "NONE" in raw.upper():
            # LLM found no match — fall back to word-overlap as safety net
            return match_faq_entries(email_body, email_subject, faq_entries, threshold)

        # Extract first number from response
        match = re.search(r"(\d+)", raw)
        if not match:
            return []

        idx = int(match.group(1))
        if idx < 1 or idx > len(faq_entries):
            logger.warning("[FaqAgent] LLM returned out-of-range index: %d", idx)
            return []

        entry = faq_entries[idx - 1]
        return [FaqMatch(
            entry_id=entry["id"],
            entry_title=entry.get("title", ""),
            entry_content=entry.get("content", ""),
            score=95.0,
        )]

    except Exception as exc:
        logger.warning("[FaqAgent] LLM matching failed, falling back to word-overlap: %s", exc)
        return match_faq_entries(email_body, email_subject, faq_entries, threshold)


def generate_faq_response(
    email_subject: str,
    email_body: str,
    sender_name: str,
    matched_entry: FaqMatch,
    tone: str = "professional",
    user_email: str = "",
) -> str:
    """
    Generate a FAQ response using Haiku LLM.
    Falls back to direct content if LLM unavailable.
    """
    tone_instructions = {
        "professional": "Réponds de manière professionnelle et courtoise.",
        "friendly": "Réponds de manière amicale et chaleureuse.",
        "concise": "Réponds de manière très concise et directe.",
    }
    tone_instruction = tone_instructions.get(tone, tone_instructions["professional"])

    system_prompt = (
        "Tu es un assistant email qui répond aux questions fréquentes. "
        f"{tone_instruction} "
        "Utilise UNIQUEMENT les informations fournies dans la réponse FAQ. "
        "Ne jamais inventer d'informations. "
        "Réponds dans la même langue que l'email reçu. "
        "Pas de formule de politesse excessive. Va droit au but."
    )

    user_prompt = (
        f"Email reçu :\n"
        f"De : {sender_name}\n"
        f"Sujet : {email_subject}\n"
        f"Corps : {email_body}\n\n"
        f"Réponse FAQ à utiliser :\n"
        f"Question : {matched_entry.entry_title}\n"
        f"Réponse : {matched_entry.entry_content}\n\n"
        f"Génère une réponse email naturelle basée sur cette FAQ."
    )

    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        # Background FAQ response generator — routes to ANTHROPIC_API_KEY_BACKGROUND.
        llm = get_container().llm_background
        with llm_attribution("faq_response", feature="faq_auto_reply"):
            response = llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=384,
            )
        text = response.content.strip() if hasattr(response, "content") else str(response).strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("[FaqAgent] LLM generation failed, using raw FAQ content: %s", exc)

    # Fallback: direct content
    return matched_entry.entry_content


def process_faq_email(
    email_id: str,
    email_subject: str,
    email_body: str,
    sender: str,
    sender_name: str,
    account_id: str,
    config: dict,
) -> Optional[FaqResult]:
    """
    Main FAQ agent entry point.

    Returns FaqResult if FAQ agent is active and has something to say,
    None if FAQ agent is not installed or has no entries.
    """
    threshold = config.get("confidence_threshold", 80)
    tone = config.get("reply_tone", "professional")
    auto_send = config.get("auto_send", True)
    test_mode = config.get("test_mode", False)

    # Load FAQ entries from DB
    try:
        from app.db.database import get_db_session
        from app.db.repositories.knowledge_repository import KnowledgeRepository

        with get_db_session() as session:
            repo = KnowledgeRepository(session)
            entries_db = repo.get_faq_entries(int(str(account_id)))
            faq_entries = [e.to_dict() for e in entries_db]
    except Exception as exc:
        logger.error("[FaqAgent] Failed to load FAQ entries: %s", exc)
        return None

    if not faq_entries:
        logger.debug("[FaqAgent] No FAQ entries for account %s", account_id)
        return None

    try:
        usage_account_id = int(str(account_id))
    except (TypeError, ValueError):
        usage_account_id = None

    from app.infrastructure.llm_attribution import llm_attribution

    # P1.5 — Fusion match+generate en 1 appel LLM. Si l'appel fusionné échoue
    # (LLM 5xx, parse JSON, etc.), on retombe sur le path historique 2-call
    # (word-overlap match → generate_faq_response) pour préserver la
    # disponibilité de l'auto-reply FAQ.
    with llm_attribution(
        "faq_agent",
        account_id=usage_account_id,
        feature="faq_auto_reply",
    ):
        best, draft_body = match_and_generate_faq_with_llm(
            email_body=email_body,
            email_subject=email_subject,
            sender_name=sender_name,
            faq_entries=faq_entries,
            tone=tone,
            threshold=threshold,
        )

        if best is None or not draft_body:
            # Fusion path returned no match — fall back to word-overlap.
            # Note: we don't retry the LLM matcher here because the fusion call
            # already consulted the LLM; a second LLM call would defeat the win.
            matches = match_faq_entries(email_body, email_subject, faq_entries, threshold)
            if not matches:
                _log_faq_action(account_id, email_id, "skipped", 0.0, None, None)
                return FaqResult(action="skipped", confidence=0.0)
            best = matches[0]
            # Word-overlap matched; generate body via the legacy 2-call generator.
            draft_body = generate_faq_response(
                email_subject, email_body, sender_name, best, tone,
            )

    logger.info(
        "[FaqAgent] Match: '%s' score=%.1f (threshold=%d)",
        best.entry_title, best.score, threshold,
    )

    # Auto-send (unless disabled/test mode). Disabled auto-send must stay a
    # draft; reporting "auto_sent" here made manual draft generation look like
    # a delivered email even when no send happened.
    actual_action = "draft_only"
    sent_message_id = None
    if auto_send and not test_mode:
        try:
            sent_message_id = _auto_send_faq(email_id, sender, email_subject, draft_body, account_id, original_body=email_body, original_sender=sender)
            logger.info("[FaqAgent] Auto-sent FAQ response for email %s", email_id)
            actual_action = "auto_sent"
        except Exception as exc:
            logger.error("[FaqAgent] Auto-send failed: %s", exc)
            actual_action = "send_failed"
    elif test_mode:
        logger.info("[FaqAgent] TEST MODE — draft generated but not sent for email %s", email_id)
        actual_action = "draft_only"

    _log_faq_action(
        account_id, email_id, actual_action, best.score,
        best.entry_id, best.entry_title,
    )

    return FaqResult(
        action=actual_action,
        confidence=best.score,
        matched_entry_id=best.entry_id,
        matched_entry_title=best.entry_title,
        draft_body=draft_body,
        sent_message_id=sent_message_id,
    )


def _auto_send_faq(
    email_id: str,
    recipient: str,
    subject: str,
    body: str,
    account_id: str,
    original_body: str = "",
    original_sender: str = "",
) -> Optional[str]:
    """Send the FAQ response via the account's email provider.

    Returns the sent message ID on success (may be None for non-Gmail providers).
    """
    from app.multi_accounts import get_account_manager, create_provider_for_account

    manager = get_account_manager()
    account_key = str(account_id)
    account_config = manager.accounts.get(account_key)
    db_account = None
    db_account_id = None
    try:
        db_account_id = int(account_key)
    except (TypeError, ValueError):
        db_account_id = None

    if db_account_id is not None:
        try:
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                db_account = AccountRepository(session).get(db_account_id)
        except Exception as exc:
            logger.debug("[FaqAgent] Could not load DB account %s: %s", account_key, exc)

    if not account_config and db_account and getattr(db_account, "email", None):
        account_config = manager.get_account_by_email(db_account.email)

    if not account_config:
        raise ValueError(f"Account {account_id} not found in account manager")

    # Append user signature
    try:
        if db_account_id is not None:
            from app.utils.signature import append_signature
            body = append_signature(body, account_id=db_account_id, is_html=False)
    except Exception as exc:
        logger.debug("[FaqAgent] Could not load signature: %s", exc)

    # Append quoted original email
    if original_body:
        quoted = "\n".join(f"> {line}" for line in original_body.splitlines())
        attribution = f"De : {original_sender}" if original_sender else ""
        body = f"{body}\n\n---\n{attribution}\n\n{quoted}".strip()

    # Build reply subject
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    provider = create_provider_for_account(account_config)

    if hasattr(provider, "send_reply_directly"):
        return provider.send_reply_directly(
            to=[recipient],
            subject=reply_subject,
            body=body,
            reply_to_id=email_id,
        ) or None
    elif hasattr(provider, "create_draft"):
        draft_id = provider.create_draft(
            to=[recipient],
            subject=reply_subject,
            body=body,
            reply_to_id=email_id,
        )
        if draft_id and hasattr(provider, "send_draft"):
            provider.send_draft(draft_id)

    return None


def _log_faq_action(
    account_id: object,  # accepts str|int — coerced to int below (FI-001)
    email_id: str,
    action: str,
    confidence: float,
    entry_id: Optional[str],
    entry_title: Optional[str],
) -> None:
    """Persist FAQ action log for stats dashboard."""
    try:
        from app.db.database import get_db_session
        from app.db.models.faq_agent_log import FaqAgentLog

        # Audit FI-001: column is now Integer + FK; the legacy callers
        # still type the parameter as str ("account hash"), so coerce.
        # `account_id: object` accepts str|int — wrap via str() so mypy
        # accepts the int() call (mypy strict refuses int(object) since
        # neither overload covers the bare `object` type).
        try:
            aid_int = int(str(account_id))
        except (TypeError, ValueError):
            logger.warning(
                "[FaqAgent] Skipping log: non-numeric account_id=%r",
                account_id,
            )
            return

        with get_db_session() as session:
            log = FaqAgentLog(
                id=str(uuid.uuid4()),
                account_id=aid_int,
                email_id=email_id,
                action=action,
                confidence_score=confidence,
                matched_entry_id=entry_id,
                matched_entry_title=entry_title,
            )
            session.add(log)
    except Exception as exc:
        logger.warning("[FaqAgent] Failed to log action: %s", exc)
