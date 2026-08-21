# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Construction du bloc de guidance de style pour le DrafterAgent (issue #187).

Ce module produit un bloc de contexte combinant :
- Un bloc few-shot <STYLE_EXAMPLES> avec les exemples-référence anonymisés
- Un bloc narratif de métriques observées (longueur phrases, formalité, emojis)

Remplace les anciens labels caricaturaux (ton=formel, emotion=chaleureux) par
une description factuelle du style réel observé dans l'outbox utilisateur.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.domain.entities.writing_style import ReferenceExample, WritingStyleProfile


# ---------------------------------------------------------------------------
# Locales pour les labels narratifs (F16 — évite le mélange de langues dans le prompt)
# ---------------------------------------------------------------------------

_LOCALES: Dict[str, Dict[str, str]] = {
    "fr": {
        "heading": "STYLE OBSERVÉ DEPUIS L'OUTBOX :",
        "sentence_avg": "- Phrases de ~{avg:.0f} mots en moyenne{variance}.",
        "variance_note": " (écart-type {v:.1f})",
        "vocab_rich": "vocabulaire riche et varié",
        "vocab_narrow": "vocabulaire resserré et récurrent",
        "vocab_balanced": "vocabulaire équilibré",
        "vocab_line": "- Densité lexicale {d:.2f} — {label}.",
        "emoji_frequent": "- Emojis utilisés fréquemment (~{r:.1f}/email).",
        "emoji_occasional": "- Emojis occasionnels (~{r:.1f}/email).",
        "emoji_none": "- Aucun emoji.",
        "exclamation_frequent": "- Points d'exclamation fréquents ({r:.1f}/email).",
        "formality_formal": "style formel (vouvoiement, formules complètes)",
        "formality_casual": "style décontracté (tutoiement, registre parlé)",
        "formality_mixed": "style mixte, adapté au contexte",
        "formality_line": "- Formalité {s:.2f} — {label}.",
        "fewshot_intro": "Voici 3 exemples anonymisés d'emails que l'utilisateur a déjà envoyés.",
        "fewshot_instruction": "Écris dans le MÊME STYLE (longueur, rythme, registre), pas dans le même thème.",
        "fewshot_header": "--- Exemple {i} ({bucket}, ~{wc} mots) ---",
        "fewshot_subject": "Sujet : {s}",
        "fewshot_body": "Corps :\n{b}",
        # PR3 — per-contact hint (port localisé de ContactStyleProfile.to_prompt_hint).
        "contact_nickname": "SURNOM/PRÉNOM D'APPEL : «{n}» — Utilise ce surnom pour t'adresser à ce contact (ex: si salutation = «Salut», écrire «Salut {n},»)",
        "contact_formality": "Formalité spécifique: {f}",
        "contact_greeting": "Salutation habituelle: {g}",
        "contact_closing": "Clôture habituelle: {c}",
        "contact_language": "LANGUE : Réponds en {l} à ce contact.",
        "contact_variant": "VARIANTE RÉGIONALE : {v}. Adapte vocabulaire, orthographe et expressions régionales.",
    },
    "en": {
        "heading": "STYLE OBSERVED FROM OUTBOX:",
        "sentence_avg": "- Sentences ~{avg:.0f} words on average{variance}.",
        "variance_note": " (std dev {v:.1f})",
        "vocab_rich": "rich and varied vocabulary",
        "vocab_narrow": "narrow and repetitive vocabulary",
        "vocab_balanced": "balanced vocabulary",
        "vocab_line": "- Lexical density {d:.2f} — {label}.",
        "emoji_frequent": "- Emojis used frequently (~{r:.1f}/email).",
        "emoji_occasional": "- Emojis occasional (~{r:.1f}/email).",
        "emoji_none": "- No emojis.",
        "exclamation_frequent": "- Exclamation marks frequent ({r:.1f}/email).",
        "formality_formal": "formal style (formal address, full phrasing)",
        "formality_casual": "casual style (informal, spoken register)",
        "formality_mixed": "mixed style, context-adapted",
        "formality_line": "- Formality {s:.2f} — {label}.",
        "fewshot_intro": "Below are 3 anonymized examples of emails the user has already sent.",
        "fewshot_instruction": "Write in the SAME STYLE (length, rhythm, register), not the same topic.",
        "fewshot_header": "--- Example {i} ({bucket}, ~{wc} words) ---",
        "fewshot_subject": "Subject: {s}",
        "fewshot_body": "Body:\n{b}",
        # PR3 — per-contact hint (localized port of ContactStyleProfile.to_prompt_hint).
        "contact_nickname": "NICKNAME / FIRST NAME: «{n}» — Use this name to address this contact (e.g. if greeting = «Hi», write «Hi {n},»)",
        "contact_formality": "Specific formality: {f}",
        "contact_greeting": "Habitual greeting: {g}",
        "contact_closing": "Habitual closing: {c}",
        "contact_language": "LANGUAGE: Reply in {l} to this contact.",
        "contact_variant": "REGIONAL VARIANT: {v}. Adapt vocabulary, spelling, and regional expressions accordingly.",
    },
}


def _get_locale(language: str) -> Dict[str, str]:
    """Retourne les labels pour la langue demandée, fallback FR."""
    return _LOCALES.get((language or "").lower(), _LOCALES["fr"])


def build_style_guidance_from_profile(
    profile: Optional[WritingStyleProfile],
    language: str = "fr",
    recipient_email: Optional[str] = None,
) -> str:
    """
    Produit le bloc de style observé à injecter dans le system prompt.

    Args:
        profile: Profil de style observé, ou None si pas encore analysé.
        language: Code locale ISO 2 lettres ("fr" ou "en") pour les labels
            narratifs — évite le mélange de langues dans le prompt (F16).
            Default "fr" pour rétrocompat.
        recipient_email: Adresse du destinataire pour adaptation par contact
            (PR3). Si fourni ET le profile contient un ``ContactStyleProfile``
            matché (clé lower-case), un bloc per-contact (nickname / formalité
            / greeting / closing / langue / variante) est appendu au bloc
            métriques+few-shot. Émis indépendamment du gate examples — un
            contact match a de la valeur même sans corpus d'exemples.

    Retourne une chaîne vide si :
    - profile est None
    - profile.reference_examples est vide ET aucun contact match
    - tous les exemples sont non anonymisés ET aucun contact match (sécurité)

    Sinon retourne le concatenat des blocs disponibles (métriques+few-shot,
    puis hint per-contact), séparés par double-newline.
    """
    if profile is None:
        return ""

    locale = _get_locale(language)
    parts: List[str] = []

    safe_examples = _filter_anonymized_examples(profile.reference_examples)
    # The observed-style METRICS (formality / sentence length / vocabulary /
    # emoji) are emitted whenever they were actually measured — independently
    # of whether anonymized reference examples survived (a profile can keep its
    # statistics after the example shells are pruned by the retention policy).
    # Only the FEW-SHOT block still requires safe examples. Pre-fix, both were
    # gated on `safe_examples`, so a stats-only profile silently injected no
    # style guidance at all.
    try:
        metrics_narrative = _build_metrics_narrative(profile, locale)
    except Exception:
        # A malformed/partial profile (non-numeric metric field) must never
        # crash draft generation — degrade to "no metrics" instead.
        metrics_narrative = ""
    if metrics_narrative:
        parts.append(metrics_narrative)
    if safe_examples:
        parts.append(_build_few_shot_block(safe_examples, locale))

    if recipient_email:
        contact_hint = _build_contact_hint_for_recipient(profile, recipient_email, language)
        if contact_hint:
            parts.append(contact_hint)

    return "\n\n".join(p for p in parts if p) if parts else ""


def build_contact_hint_block(contact, language: str = "fr") -> str:
    """Build a localized per-contact directive block.

    Port of :meth:`ContactStyleProfile.to_prompt_hint` — same fields, same
    formatting, but locale-aware (the entity method is hardcoded French and
    will be deleted once all callsites migrate to this function).

    Args:
        contact: A ``ContactStyleProfile`` instance.
        language: ``"fr"`` or ``"en"``. Unknown codes fall back to French.

    Returns:
        Multi-line directive block, or empty string when the contact has no
        actionable hints (no nickname, no overrides, no preferred phrases).
    """
    locale = _get_locale(language)
    lines: List[str] = []

    if contact.nickname:
        lines.append(locale["contact_nickname"].format(n=contact.nickname))

    if contact.formality_override:
        lines.append(locale["contact_formality"].format(f=contact.formality_override.value))

    if contact.preferred_greeting:
        greeting = contact.preferred_greeting
        from app.smart_routing import is_canonical_greeting_for_contact
        if not is_canonical_greeting_for_contact(greeting, contact.nickname or ""):
            greeting = ""
        if "{" in greeting:
            # Lazy import: `_expand_greeting_template` lives in `smart_routing`
            # (heavy module) and is only needed for templated greetings.
            from app.smart_routing import _expand_greeting_template
            spoken = (contact.langue or "").lower()
            template_lang = "ENGLISH" if spoken.startswith("anglais") else "FRENCH"
            greeting = _expand_greeting_template(
                greeting, contact.nickname or "", template_lang
            )
        if greeting:
            lines.append(locale["contact_greeting"].format(g=greeting))

    if contact.preferred_closing:
        # Guard against the onboarding "no closing or just name" sentinel
        # leaking into the per-contact hint — same defence as
        # _compute_closing_hint in identity.py. Bug fix 2026-05-11.
        from app.prompts.identity import _is_no_closing_marker
        if not _is_no_closing_marker(contact.preferred_closing):
            lines.append(locale["contact_closing"].format(c=contact.preferred_closing))

    if contact.langue:
        lines.append(locale["contact_language"].format(l=contact.langue))

    if contact.langue_variante:
        lines.append(locale["contact_variant"].format(v=contact.langue_variante))

    return "\n".join(lines)


def _build_contact_hint_for_recipient(
    profile: WritingStyleProfile, recipient_email: str, language: str
) -> str:
    """Look up `recipient_email` in `profile.contact_profiles` and return its
    hint block. Empty string if the contact is unknown."""
    contact_profiles = getattr(profile, "contact_profiles", None) or {}
    contact_data = contact_profiles.get(recipient_email.lower())
    if not contact_data:
        return ""

    # Lazy import to avoid a domain → prompts cycle.
    from app.domain.entities.writing_style import ContactStyleProfile
    contact = ContactStyleProfile.from_dict(contact_data)
    return build_contact_hint_block(contact, language)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_anonymized_examples(
    examples: List[ReferenceExample],
) -> List[ReferenceExample]:
    """Filtre sécuritaire : n'injecte que des exemples anonymisés."""
    return [ex for ex in examples if ex.anonymized]


def _build_metrics_narrative(
    profile: WritingStyleProfile, locale: Dict[str, str]
) -> str:
    """Décrit les métriques observées en langage naturel pour le LLM.

    Sémantique des champs Optional[float] (issue #187 sentinel migration) :
        - ``None``  → métrique jamais mesurée → la ligne est omise pour ne PAS
          fabriquer une affirmation ("style mixte", "0 emoji") qui n'a aucun
          fondement empirique.
        - valeur   → la ligne est émise (y compris quand la valeur est 0.0,
          qui est une mesure réelle, pas un default).
    """
    lines = [locale["heading"]]

    # Longueur de phrases (avg_sentence_length reste float non-Optional ; il
    # est aussi peuplé par `_compute_sent_metrics` côté legacy onboarding).
    if profile.avg_sentence_length > 0:
        variance = ""
        if profile.sentence_length_variance is not None and profile.sentence_length_variance > 0:
            variance = locale["variance_note"].format(v=profile.sentence_length_variance)
        lines.append(
            locale["sentence_avg"].format(
                avg=profile.avg_sentence_length, variance=variance
            )
        )

    # Formalité (score continu) — skip si jamais mesuré
    if profile.formality_score is not None:
        lines.append(_formality_narrative(profile.formality_score, locale))

    # Densité lexicale — None = jamais mesuré (ligne omise). 0.0 EST une mesure
    # réelle (corpus très répétitif) et doit être émis : seul le sentinel None
    # justifie l'omission. Pré-fix, le garde `> 0` confondait les deux.
    if profile.vocabulary_density is not None:
        if profile.vocabulary_density > 0.5:
            richness = locale["vocab_rich"]
        elif profile.vocabulary_density < 0.3:
            richness = locale["vocab_narrow"]
        else:
            richness = locale["vocab_balanced"]
        lines.append(
            locale["vocab_line"].format(d=profile.vocabulary_density, label=richness)
        )

    # Emojis — distinguer "jamais mesuré" (None) de "mesuré à 0" (assert "no emoji")
    if profile.emoji_frequency is not None:
        if profile.emoji_frequency > 0.5:
            lines.append(locale["emoji_frequent"].format(r=profile.emoji_frequency))
        elif profile.emoji_frequency > 0:
            lines.append(locale["emoji_occasional"].format(r=profile.emoji_frequency))
        else:
            lines.append(locale["emoji_none"])

    # Exclamations
    if profile.exclamation_rate is not None and profile.exclamation_rate > 0.5:
        lines.append(
            locale["exclamation_frequent"].format(r=profile.exclamation_rate)
        )

    # Only a heading, no measured metric → return "" so the caller doesn't
    # inject a lone "Observed style:" header with nothing under it.
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _formality_narrative(score: float, locale: Dict[str, str]) -> str:
    """Description textuelle du formality_score continu."""
    if score >= 0.75:
        label = locale["formality_formal"]
    elif score <= 0.3:
        label = locale["formality_casual"]
    else:
        label = locale["formality_mixed"]
    return locale["formality_line"].format(s=score, label=label)


def _build_few_shot_block(
    examples: List[ReferenceExample], locale: Dict[str, str]
) -> str:
    """Bloc few-shot avec exemples anonymisés, délimité par balises XML."""
    lines = [
        "<STYLE_EXAMPLES>",
        locale["fewshot_intro"],
        locale["fewshot_instruction"],
        "",
    ]
    for i, ex in enumerate(examples, 1):
        lines.append(
            locale["fewshot_header"].format(i=i, bucket=ex.length_bucket, wc=ex.word_count)
        )
        if ex.subject:
            lines.append(locale["fewshot_subject"].format(s=ex.subject))
        lines.append(locale["fewshot_body"].format(b=ex.body_excerpt))
        lines.append("")
    lines.append("</STYLE_EXAMPLES>")
    return "\n".join(lines)
