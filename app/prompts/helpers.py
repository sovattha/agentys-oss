# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Prompt helper functions — style extraction, formality analysis, intent classification."""

from __future__ import annotations

import logging
import re as _re
import time as _time
from collections import OrderedDict


logger = logging.getLogger(__name__)

__all__ = [
    "extract_sent_examples", "extract_user_formulas", "compute_style_metrics",
    "classify_intent", "analyze_email_formality", "formality_to_temperature",
    "_cache_key", "_get_fewshot_section",
    "extract_cross_thread_examples",
]

# Audit M-3 + HIGH-7 (2026-04-25): cap caches via OrderedDict LRU pour éviter
# une croissance unbounded sur deploy long-vivant.
_CACHE_MAX = 512
_STYLE_CACHE: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
_EXAMPLES_CACHE: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
_CACHE_TTL = 600  # 10 minutes


def _lru_set(cache: "OrderedDict[str, tuple[str, float]]", key: str, value: tuple[str, float]) -> None:
    """LRU set : déplace la clé en queue, drop la tête si overflow."""
    if key in cache:
        cache.move_to_end(key)
    cache[key] = value
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


def _cache_key(conversation_history: list[dict] | None, user_email: str, extra: str = "") -> str:
    """Build a lightweight cache key from the first+last message ids + user.

    Note: ``user_email`` is unique per account in our model (AccountManager
    déduplique via email), donc le cache reste safely scoped par compte.
    L'audit M-3 (2026-04-25) a confirmé que ceci est suffisant — pas
    besoin de propager account_id explicitement.
    """
    if not conversation_history:
        return f"empty:{user_email}:{extra}"
    first_id = conversation_history[0].get("id", "") if conversation_history else ""
    last_id = conversation_history[-1].get("id", "") if conversation_history else ""
    return f"{first_id}:{last_id}:{len(conversation_history)}:{user_email}:{extra}"


def extract_sent_examples(
    conversation_history: list[dict] | None,
    user_email: str,
    max_examples: int = 3,
    intent: str = "",
) -> str:
    """
    Extrait les emails envoyés par l'utilisateur depuis l'historique.

    Retourne une section formatée pour injection dans le system prompt.
    Sélectionne les exemples par intent matching, fallback to most recent.

    Args:
        conversation_history: Historique des échanges avec le contact.
        user_email: Adresse email de l'utilisateur.
        max_examples: Nombre max d'exemples à retourner.
        intent: Target intent to match ('action', 'question', 'decline', 'scheduling', 'acknowledgment').

    Returns:
        Section formatée ou chaîne vide si aucun exemple.
    """
    if not conversation_history or not user_email:
        return ""

    ck = _cache_key(conversation_history, user_email, intent)
    if ck in _EXAMPLES_CACHE:
        cached, ts = _EXAMPLES_CACHE[ck]
        if _time.time() - ts < _CACHE_TTL:
            return cached

    user_email_lower = user_email.lower()
    sent_emails = []

    for email in conversation_history:
        sender = (email.get("sender") or "").lower()
        if sender == user_email_lower:
            body = (email.get("body") or "").strip()
            subject = email.get("subject", "")
            # Ignorer les emails trop courts (< 20 chars) ou vides
            if len(body) >= 20:
                email_intent = classify_intent(body, subject)
                sent_emails.append({
                    "subject": subject,
                    "body": body[:1000],
                    "date": email.get("date", ""),
                    "intent": email_intent,
                })

    if not sent_emails:
        return ""

    # Intent-aware selection: prefer emails matching current intent
    if intent:
        matched = [e for e in sent_emails if e["intent"] == intent]
        if matched:
            examples = matched[:max_examples]
        else:
            examples = sent_emails[:max_examples]
    else:
        examples = sent_emails[:max_examples]

    lines = ["<TES_RÉPONSES_PRÉCÉDENTES>"]
    lines.append("Voici tes vrais emails envoyés à ce contact. IMITE ce style exactement :")
    lines.append("longueur, salutation, clôture, structure, niveau de détail.\n")

    for i, ex in enumerate(examples, 1):
        lines.append(f"--- Ton email {i} ---")
        if ex["subject"]:
            lines.append(f"Sujet: {ex['subject']}")
        lines.append(ex["body"])
        lines.append("")

    lines.append("</TES_RÉPONSES_PRÉCÉDENTES>")
    result = "\n".join(lines)
    _lru_set(_EXAMPLES_CACHE, ck, (result, _time.time()))
    return result


def extract_cross_thread_examples(
    account_id: int | None,
    max_examples: int = 2,
    intent: str = "",
) -> str:
    """Cross-thread few-shot fallback from WritingStyleProfile.reference_examples.

    Used when the current thread has no prior user-sent emails (new contact,
    forwarded thread). Without this fallback, the drafter sees no concrete
    user-style example and defaults to a generic Haiku tone.

    Strict safety:
    - Only anonymized examples are surfaced (filter via _filter_anonymized_examples).
      A non-anonymized reference is silently dropped, never leaked.
    - Fail-cheap: any exception → "" so the drafter call still works.

    Audit 2026-05-05: drafter_system_prompt.txt has BAD/GOOD anti-patterns but
    zero positive few-shot. Cross-thread fallback closes the gap on cold-start
    drafts (first reply to a new contact, where extract_sent_examples returns
    "" because no in-thread user message exists yet).

    Audit 2026-05-06: optional ``intent`` parameter. When provided, the picker
    classifies each anonymized example with ``classify_intent`` and prefers
    examples matching the same intent — same behaviour as the in-thread
    variant. Falls back to length-bucket selection if no examples match.
    """
    if not account_id or account_id <= 0:
        return ""
    try:
        from app.infrastructure.container import get_container
        from app.prompts.style_guidance import _filter_anonymized_examples

        profile = get_container().get_writing_style_profile(account_id=account_id)
        if not profile or not profile.reference_examples:
            return ""

        safe = _filter_anonymized_examples(profile.reference_examples)
        if not safe:
            return ""

        # Intent-aware selection: when intent is provided, classify each
        # anonymized example with the same regex classifier the in-thread
        # path uses. Examples matching the current intent rank first.
        picked: list = []
        if intent:
            target = intent.strip().lower()
            for ex in safe:
                ex_subject = getattr(ex, "subject", "") or ""
                ex_body = getattr(ex, "body_excerpt", "") or ""
                try:
                    ex_intent = classify_intent(ex_body, ex_subject).lower()
                except Exception:
                    ex_intent = ""
                if ex_intent == target:
                    picked.append(ex)
                    if len(picked) >= max_examples:
                        break

        # Length-bucket fallback: prefer one short + one medium for
        # representative coverage. Skipped if intent-matching already
        # filled the quota.
        if len(picked) < max_examples:
            by_bucket: dict[str, list] = {"short": [], "medium": [], "long": []}
            for ex in safe:
                bucket = getattr(ex, "length_bucket", "medium")
                if bucket in by_bucket:
                    by_bucket[bucket].append(ex)
            seen = {id(e) for e in picked}
            for bucket in ("short", "medium", "long"):
                for ex in by_bucket[bucket]:
                    if id(ex) in seen:
                        continue
                    picked.append(ex)
                    seen.add(id(ex))
                    if len(picked) >= max_examples:
                        break
                if len(picked) >= max_examples:
                    break
        # Top up with the original order if buckets didn't yield enough.
        if len(picked) < max_examples:
            seen = {id(e) for e in picked}
            for ex in safe:
                if id(ex) in seen:
                    continue
                picked.append(ex)
                if len(picked) >= max_examples:
                    break

        if not picked:
            return ""

        lines = ["<TES_RÉPONSES_PRÉCÉDENTES>"]
        lines.append(
            "Exemples anonymisés de tes vrais emails envoyés (style général). "
            "IMITE le ton, la longueur et la structure ; ne reprends pas les détails."
        )
        lines.append("")
        for i, ex in enumerate(picked, 1):
            lines.append(f"--- Exemple {i} ---")
            subject = getattr(ex, "subject", "") or ""
            if subject:
                lines.append(f"Sujet: {subject}")
            body = getattr(ex, "body_excerpt", "") or ""
            if body:
                lines.append(body[:1000])
            lines.append("")
        lines.append("</TES_RÉPONSES_PRÉCÉDENTES>")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("extract_cross_thread_examples: fail-cheap due to %s", e)
        return ""


def extract_user_formulas(
    conversation_history: list[dict] | None,
    user_email: str,
) -> str:
    """
    Extrait les formules de salutation et clôture réelles de l'utilisateur.

    Analyse les emails envoyés pour détecter les patterns de greeting/closing.

    Returns:
        Section formatée ou chaîne vide si pas assez de données.
    """
    if not conversation_history or not user_email:
        return ""

    user_email_lower = user_email.lower()
    greetings = []
    closings = []

    for email in conversation_history:
        sender = (email.get("sender") or "").lower()
        if sender != user_email_lower:
            continue

        body = (email.get("body") or "").strip()
        if not body:
            continue

        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        if not lines:
            continue

        # Première ligne non vide = greeting candidate
        first_line = lines[0]
        if len(first_line) < 60:  # Les greetings sont courts
            greetings.append(first_line)

        # Dernières lignes = closing candidates (avant signature)
        # Chercher la dernière ligne courte qui ressemble à une clôture
        for line in reversed(lines[-5:]):
            line_clean = line.rstrip(",.")
            if 2 < len(line_clean) < 40:
                closings.append(line)
                break

    if not greetings and not closings:
        return ""

    # Compter les fréquences et garder les plus courants
    def top_items(items: list[str], n: int = 3) -> list[str]:
        freq: dict[str, int] = {}
        for item in items:
            key = item.lower().rstrip(",!. ")
            freq[key] = freq.get(key, 0) + 1
        sorted_items = sorted(freq.items(), key=lambda x: -x[1])
        # Retrouver la forme originale
        seen = set()
        result = []
        for key, _ in sorted_items:
            for item in items:
                if item.lower().rstrip(",!. ") == key and key not in seen:
                    result.append(item)
                    seen.add(key)
                    break
            if len(result) >= n:
                break
        return result

    parts = ["<TES_FORMULES_HABITUELLES>"]
    parts.append("Formules que tu utilises RÉELLEMENT (extraites de tes emails envoyés) :")

    top_greetings = top_items(greetings)
    top_closings = top_items(closings)

    if top_greetings:
        parts.append(f"Salutations : {' | '.join(top_greetings)}")
    if top_closings:
        parts.append(f"Clôtures : {' | '.join(top_closings)}")

    parts.append("Utilise UNIQUEMENT ces formules, pas des formules IA génériques.")
    parts.append("</TES_FORMULES_HABITUELLES>")
    return "\n".join(parts)


# ============================================================================
# QUANTITATIVE STYLE METRICS (Axe 3)
# ============================================================================

def compute_style_metrics(
    conversation_history: list[dict] | None,
    user_email: str,
    contact: str = "",
) -> str:
    """
    Compute quantitative writing style metrics from user's sent emails.

    Returns a compact one-line instruction for the LLM, or empty string.
    """
    if not conversation_history or not user_email:
        return ""

    ck = _cache_key(conversation_history, user_email, contact)
    if ck in _STYLE_CACHE:
        cached, ts = _STYLE_CACHE[ck]
        if _time.time() - ts < _CACHE_TTL:
            return cached

    user_email_lower = user_email.lower()
    sentence_lengths: list[int] = []
    reply_word_counts: list[int] = []
    tu_count = 0
    vous_count = 0
    excl_count = 0
    total_sentences = 0
    greetings: dict[str, int] = {}

    for email in conversation_history:
        sender = (email.get("sender") or "").lower()
        if sender != user_email_lower:
            continue

        body = (email.get("body") or "").strip()
        if not body or len(body) < 20:
            continue

        words = body.split()
        reply_word_counts.append(len(words))

        # Tu/Vous ratio — count morphological markers, not just bare pronouns.
        # "ton retour" / "te laisse" carry the same tutoiement signal as "tu";
        # mirroring relies on these to detect the user's habitual register
        # with this specific contact. We exclude hyphenated compounds
        # ("rendez-vous", "passe-partout") so they don't pollute the count.
        body_lower = body.lower()
        tu_count += len(_re.findall(r'(?<![\w-])tu(?![\w-])', body_lower))
        tu_count += len(_re.findall(r'(?<![\w-])(ton|ta|tes|toi|te)(?![\w-])', body_lower))
        tu_count += len(_re.findall(r"(?<![\w-])t['’](?=[aeiouhéèêàâôîï])", body_lower))
        vous_count += len(_re.findall(r'(?<![\w-])vous(?![\w-])', body_lower))
        vous_count += len(_re.findall(r'(?<![\w-])(votre|vos)(?![\w-])', body_lower))

        # Exclamation ratio
        excl_count += body.count("!")
        total_sentences_in_email = max(1, body.count(".") + body.count("!") + body.count("?"))
        total_sentences += total_sentences_in_email

        # Sentence lengths
        sentences = _re.split(r'[.!?]+', body)
        for s in sentences:
            ws = s.split()
            if len(ws) >= 2:
                sentence_lengths.append(len(ws))

        # Greeting tracking
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        if lines and len(lines[0]) < 40:
            g = lines[0].rstrip(",!. ").lower()
            greetings[g] = greetings.get(g, 0) + 1

    if not reply_word_counts:
        return ""

    # Compute metrics
    avg_sentence = round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1) if sentence_lengths else 0
    avg_reply = round(sum(reply_word_counts) / len(reply_word_counts))
    excl_ratio = round(excl_count / max(total_sentences, 1), 2)

    # Build compact instruction
    parts = []
    if avg_sentence > 0:
        parts.append(f"sentences ~{avg_sentence} words")
    if avg_reply > 0:
        parts.append(f"reply ~{avg_reply} words")
    if excl_ratio < 0.05:
        parts.append("avoid '!'")
    elif excl_ratio > 0.3:
        parts.append("use '!' freely")

    # Tu/vous for this contact
    if tu_count > 0 or vous_count > 0:
        if tu_count > vous_count * 2:
            parts.append("always use 'tu'")
        elif vous_count > tu_count * 2:
            parts.append("always use 'vous'")

    # Dominant greeting
    if greetings:
        top_greeting = max(greetings, key=greetings.get)
        top_count = greetings[top_greeting]
        total_emails = len(reply_word_counts)
        if top_count >= total_emails * 0.5 and total_emails >= 2:
            parts.append(f"greeting: '{top_greeting},'")

    if not parts:
        return ""

    result = f"TARGET STYLE: {', '.join(parts)}."
    _lru_set(_STYLE_CACHE, ck, (result, _time.time()))
    return result


# ============================================================================
# FEW-SHOT EXAMPLES — Intent-based positive examples for Haiku
# ============================================================================

_FEWSHOT_EXAMPLES: dict[str, list[dict]] = {
    "action_casual_fr": [
        {"email": "Tu peux checker le build? Y'a un bug sur staging.",
         "reply": "Salut,\n\nJe regarde ça maintenant."},
        {"email": "On se fait un call demain pour le sprint planning?",
         "reply": "Salut,\n\nOui, demain ça me va. Tu proposes quelle heure ?"},
    ],
    "action_formal_fr": [
        {"email": "Pourriez-vous nous transmettre le rapport mensuel ?",
         "reply": "Bonjour,\n\nJe vous l'envoie d'ici la fin de journée."},
    ],
    "action_casual_en": [
        {"email": "Can you review the PR when you get a chance?",
         "reply": "Hi,\n\nI'll take a look this afternoon."},
    ],
    "action_formal_en": [
        {"email": "Could you please share the Q4 report?",
         "reply": "Hello,\n\nI'll send it over by end of day."},
    ],
    "question_casual_fr": [
        {"email": "T'as les chiffres du mois dernier ?",
         "reply": "Salut,\n\nOui, les chiffres sont [données de l'historique]. Dis-moi si tu veux le détail."},
    ],
    "question_formal_fr": [
        {"email": "Pourriez-vous me confirmer les disponibilités pour la semaine prochaine ?",
         "reply": "Bonjour,\n\nJe suis disponible mardi et jeudi."},
    ],
    "decline_casual_fr": [
        {"email": "Tu viens au team building vendredi ?",
         "reply": "Salut,\n\nDésolé, je ne pourrai pas cette fois-ci. Amusez-vous bien."},
    ],
    "decline_formal_fr": [
        {"email": "Nous souhaiterions planifier une réunion lundi à 9h.",
         "reply": "Bonjour,\n\nMalheureusement je ne suis pas disponible lundi matin. Seriez-vous disponible mardi ?"},
    ],
    "decline_casual_en": [
        {"email": "Want to join the sync at 3pm?",
         "reply": "Hi,\n\nI can't make it at 3pm. Can we do 4pm instead?"},
    ],
    "decline_formal_en": [
        {"email": "We would like to schedule a call for Monday at 9am.",
         "reply": "Hello,\n\nUnfortunately I'm not available Monday morning. Would Tuesday work instead?"},
    ],
    "scheduling_casual_fr": [
        {"email": "On se fait un call demain à 14h ?",
         "reply": "Salut,\n\nOui, 14h ça me va."},
        {"email": "Tu es dispo mercredi pour un point projet ?",
         "reply": "Salut,\n\nMercredi c'est bon pour moi. Tu proposes quelle heure ?"},
    ],
    "scheduling_formal_fr": [
        {"email": "Seriez-vous disponible pour une réunion jeudi à 10h ?",
         "reply": "Bonjour,\n\nJe suis disponible jeudi à 10h. Je vous confirme ma présence."},
    ],
    "scheduling_casual_en": [
        {"email": "Can we do a quick sync tomorrow at 2pm?",
         "reply": "Hi,\n\nYes, 2pm works for me."},
    ],
    "scheduling_formal_en": [
        {"email": "Would you be available for a meeting on Thursday at 10am?",
         "reply": "Hello,\n\nI'm available Thursday at 10am. I confirm my attendance."},
    ],
    "acknowledgment_casual_fr": [
        {"email": "C'est envoyé, tu devrais avoir reçu le fichier.",
         "reply": "Salut,\n\nBien reçu, merci."},
    ],
    "acknowledgment_formal_fr": [
        {"email": "Veuillez trouver ci-joint le rapport demandé.",
         "reply": "Bonjour,\n\nBien reçu, merci."},
    ],
    "acknowledgment_casual_en": [
        {"email": "Just sent you the file.",
         "reply": "Hi,\n\nGot it, thanks."},
    ],
    "acknowledgment_formal_en": [
        {"email": "Please find attached the requested report.",
         "reply": "Hello,\n\nReceived, thank you."},
    ],
}

_DECLINE_RE = _re.compile(
    r'\b(non|no|decline|refuse|cannot|can\'t|pas possible|impossible|ne (?:pourr|peux|puis))\b',
    _re.IGNORECASE,
)

_SCHEDULING_RE = _re.compile(
    r'\b(meeting|réunion|reunion|rendez-vous|rdv|call|appel|sync|standup|stand-up'
    r'|demain|tomorrow|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche'
    r'|monday|tuesday|wednesday|thursday|friday|saturday|sunday'
    r'|disponible|available|availability|disponibilit[ée]s?'
    r'|planifier|schedule|calendrier|calendar|book|réserver|reserver'
    r'|\d{1,2}h\d{0,2}|\d{1,2}:\d{2}\s*(am|pm)?)\b',
    _re.IGNORECASE,
)

_ACK_RE = _re.compile(
    r'^(ok|oui|yes|merci|thanks|thank you|parfait|perfect|super|got it|bien reçu|noted|entendu|compris|reçu|c\'est bon)\s*[.!]?\s*$',
    _re.IGNORECASE | _re.MULTILINE,
)


def classify_intent(body: str, subject: str = "", instructions: str = "") -> str:
    """
    Classify the email reply intent using heuristics (no LLM).

    Returns one of: 'action', 'question', 'decline', 'scheduling', 'acknowledgment'
    """
    combined = f"{subject} {body}"

    # Instructions override: if user says to decline, it's a decline
    if instructions and _DECLINE_RE.search(instructions):
        return "decline"

    # Very short body + ack pattern → acknowledgment
    if len(body.strip()) < 60 and _ACK_RE.search(body):
        return "acknowledgment"

    # Scheduling: date/time/meeting keywords
    scheduling_matches = len(_SCHEDULING_RE.findall(combined))
    if scheduling_matches >= 2:
        return "scheduling"

    # Question: contains "?"
    if "?" in body:
        return "question"

    # Decline: keywords in body or instructions
    if _DECLINE_RE.search(body):
        return "decline"

    return "action"


def _get_fewshot_section(
    body: str,
    formality: int,
    detected_language: str,
    instructions: str = "",
    subject: str = "",
) -> str:
    """
    Build a few-shot examples section based on intent, formality, and language.

    Returns formatted section for injection into user prompt, or empty string.
    """
    intent_type = classify_intent(body, subject, instructions)

    # Determine casual/formal
    tone = "casual" if formality <= 2 else "formal"

    # Determine language
    lang = "fr" if detected_language == "FRENCH" else "en"

    key = f"{intent_type}_{tone}_{lang}"
    examples = _FEWSHOT_EXAMPLES.get(key, [])
    if not examples:
        # Fallback: try action with same tone/lang
        fallback_key = f"action_{tone}_{lang}"
        examples = _FEWSHOT_EXAMPLES.get(fallback_key, [])
    if not examples:
        return ""

    lines = ["STYLE EXAMPLES (write like these, but adapted to THIS email):"]
    for ex in examples[:2]:
        lines.append("---")
        lines.append(f"Email: {ex['email']}")
        lines.append(f"Reply: {ex['reply']}")
    lines.append("---")
    return "\n".join(lines)


def analyze_email_formality(email_content: str) -> int:
    """
    Détecte heuristiquement le niveau de formalité d'un email.

    Returns:
        Score de 1 (très casual) à 5 (très formel).
    """
    text = email_content.lower()

    formal_indicators = [
        "dear sir", "dear madam", "dear mr", "dear ms",
        "cher monsieur", "chère madame", "cher collègue",
        "monsieur ", "madame ",
        "cordialement", "respectueusement", "best regards", "kind regards", "sincerely",
        "veuillez agréer", "je vous prie", "yours faithfully",
        "je me permets de", "nous avons l'honneur",
        "pourriez-vous", "pourriez vous", "s il vous", "s'il vous",
        "nous accusons", "nous avons le plaisir",
        "dear ",
    ]
    casual_indicators = [
        "hey", "salut!", "salut ", "salut,", "salut\n",
        "yo ", "coucou", "à+", "a+", "cheers",
        "bisou", "biz", "xo", "lol", "haha", "😊", "👍", "🙂",
        "!!!", "mon pote", "mon ami", "mec ", "mec,",
        "ça va", "ca va", "comment vas", "fréro", "frère",
        "wesh", "tkt", "slt ", "slt,",
        "t'inquiète", "tranquille", "cool", "nickel",
        "what's up", "wassup", "sup ", "howdy",
        "hey!", "mate", "bro ", "bro,", "dude",
        # FR tutoiement patterns (strong casual signal)
        "tu veux", "tu peux", "tu as ", "tu es ", "tu fais",
        "tu sais", "tu crois", "tu penses", "tu connais",
        "t'as ", "t'es ", "t'en ", "t'y ",
        "on se ", "on va ", "on fait",
    ]

    formal_count = sum(1 for f in formal_indicators if f in text)
    casual_count = sum(1 for c in casual_indicators if c in text)

    # Tutoiement vs vouvoiement — strong formality signal (double weight).
    # We track all the morphological markers, not just the bare nominative
    # pronouns: a single "ton retour" / "te laisse" / "vos préférences"
    # carries the same informational weight as a literal "tu" / "vous".
    # We use `(?<![\w-])`/`(?![\w-])` instead of `\b` so that "rendez-vous"
    # / "passe-partout" / hyphenated compounds don't pollute the count.
    vous_count = len(_re.findall(r'(?<![\w-])vous(?![\w-])', text))
    vous_count += len(_re.findall(r'(?<![\w-])(votre|vos)(?![\w-])', text))
    tu_count = len(_re.findall(r'(?<![\w-])tu(?![\w-])', text))
    tu_count += len(_re.findall(r'(?<![\w-])(ton|ta|tes|toi|te)(?![\w-])', text))
    tu_count += len(_re.findall(r"(?<![\w-])t['’](?=[aeiouhéèêàâôîï])", text))  # t'aime, t'envoie
    # Tutoiement is the marked register in business French — using it at all
    # is a strong informality signal, even when the email also slips into
    # vouvoiement. We treat ≥ 2 tu markers as casual regardless of vous count.
    if tu_count >= 2:
        casual_count += 2
    elif vous_count > tu_count:
        formal_count += 2
    elif tu_count > vous_count:
        casual_count += 2

    if casual_count > 0 and casual_count > formal_count:
        return 1 if casual_count >= 3 else 2
    if formal_count > 0 and formal_count > casual_count:
        return 5 if formal_count >= 3 else 4

    # Very short emails (<40 chars) with no formal markers → treat as casual
    if len(text.strip()) < 40 and formal_count == 0:
        return 2

    return 3


def formality_to_temperature(formality: int) -> float:
    """
    Convertit un score de formalité (1-5) en température LLM.

    Casual → température plus haute (plus créatif).
    Formel → température plus basse (plus précis).
    """
    mapping = {1: 0.45, 2: 0.4, 3: 0.35, 4: 0.3, 5: 0.25}
    return mapping.get(formality, 0.45)


# ============================================================================
# PRE-COMPUTED HINTS — Explicit instructions for Haiku
# ============================================================================

