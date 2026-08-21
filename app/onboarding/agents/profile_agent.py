# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
ProfileAgent: analyses sent emails to deduce the user's communication profile.

Output: name, signature (name/title/company/department), tone preferences,
greeting/closing styles, languages, regional language variant.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.domain.ports.llm_port import LLMPort
from app.infrastructure.container import get_container
from app.onboarding.agents._usage_telemetry import record_agent_usage
from app.onboarding.agents.prompts import load_prompt
from app.onboarding.indexer import IndexedEmails
from app.utils.json_parser import extract_json_from_response

logger = logging.getLogger(__name__)

MAX_TOKENS_PROFILE = 4096
MAX_RETRIES = 2
MAX_PROFESSION_LENGTH = 120

_INVALID_NAME_TOKENS = frozenset({
    "none", "null", "n/a", "na", "undefined",
    "unknown", "inconnu", "inconnue", "user",
})
_INVALID_PROFESSION_TOKENS = _INVALID_NAME_TOKENS | frozenset({
    "job", "profession", "poste", "métier", "metier", "title",
})


def _normalize_name(raw: object) -> str:
    """Normalize an LLM-returned name, rejecting null-like strings.

    Returns an empty string when the value is None or a known invalid token
    (case-insensitive, trimmed). Keeps real names untouched.
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        return ""
    stripped = raw.strip()
    if not stripped:
        return ""
    if stripped.lower() in _INVALID_NAME_TOKENS:
        return ""
    return stripped


def _normalize_profession(raw: object) -> str:
    """Normalize the inferred profession and drop weak/null-like signals."""
    if raw is None or not isinstance(raw, str):
        return ""
    stripped = " ".join(raw.strip().split())
    if not stripped:
        return ""
    if stripped.lower() in _INVALID_PROFESSION_TOKENS:
        return ""
    return stripped[:MAX_PROFESSION_LENGTH]


@dataclass
class ProfileAgent:
    """
    Analyses sent emails to build the user's communication profile.

    Uses the LLM to extract patterns from sent emails.
    """
    # The actual model is selected by Container.llm_onboarding_worker
    # (default tier="label" / Haiku since 2026-05-05 — see container docstring).
    # Override with ONBOARDING_WORKER_TIER=smart to roll back to Sonnet.
    max_tokens: int = MAX_TOKENS_PROFILE
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Onboarding pipeline — routes to ANTHROPIC_API_KEY_ONBOARDING.
        self._llm = get_container().llm_onboarding_worker

    def analyse(self, indexed: IndexedEmails) -> dict:
        """
        Analyse indexed emails and produce a user profile.

        Args:
            indexed: The indexed email corpus.

        Returns:
            Dict matching the UserProfile schema.
        """
        sent_sample = self._select_sample(indexed)

        if not sent_sample:
            logger.warning(
                "ProfileAgent: aucun email envoyé trouvé pour %s. "
                "Génération d'un profil partiel depuis les emails reçus.",
                indexed.user_email,
            )
            return {
                "user_email": indexed.user_email,
                "user_name": "",
                "profession": "",
                "profession_confirmed": False,
                "languages": ["fr"],
                "_partial": True,
                "_reason": "no_sent_emails",
            }

        lang = indexed.primary_language.value
        user_prompt = self._build_prompt(indexed, sent_sample, lang)
        default = {
            "user_email": indexed.user_email,
            "user_name": "",
            "profession": "",
            "profession_confirmed": False,
        }

        system = load_prompt("profile", lang=lang)

        _t0 = time.perf_counter()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._llm.complete(
                    system=system,
                    user=user_prompt,
                    max_tokens=self.max_tokens,
                    temperature=0.1,
                )
            except Exception as e:
                logger.warning(
                    "ProfileAgent: erreur LLM (tentative %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    continue
                raise

            result = extract_json_from_response(
                response.content,
                default=default,
                error_context="ProfileAgent",
            )

            result["user_name"] = _normalize_name(result.get("user_name"))
            result["profession"] = _normalize_profession(result.get("profession"))
            result["profession_confirmed"] = False

            if result["user_name"]:
                break

            logger.warning(
                "ProfileAgent: user_name vide ou null-like (tentative %d/%d). "
                "Réponse LLM (%d chars) : %.500s",
                attempt, MAX_RETRIES,
                len(response.content), response.content[:500],
            )
        else:
            logger.warning("ProfileAgent: résultat vide après %d tentatives", MAX_RETRIES)

        record_agent_usage(
            "profile", response, self.max_tokens,
            (time.perf_counter() - _t0) * 1000.0, attempt,
        )

        # Ensure required fields
        result.setdefault("user_email", indexed.user_email)
        result.setdefault("profession", "")
        result["profession"] = _normalize_profession(result.get("profession"))
        result["profession_confirmed"] = False
        result.setdefault("languages", ["fr"])

        logger.info(
            "ProfileAgent: analysed %d sent emails, user=%s",
            len(sent_sample), result.get("user_name", "unknown"),
        )
        return result

    def _select_sample(self, indexed: IndexedEmails) -> list:
        """Select a representative sample of sent emails (max 15).

        Longer emails are preferred — they are more likely to contain a
        full signature block (company, title, phone) and a greeting/closing
        structure that the profile extractor needs. Anything below 150
        chars is almost always a one-liner reply with no signature.
        """
        sent = indexed.sent_emails
        if not sent:
            return []

        # Drop ultra-short replies (< 150 chars) that rarely carry signatures.
        long_enough = [e for e in sent if e.body and len(e.body) >= 150]
        pool = long_enough if len(long_enough) >= 5 else sent

        if len(pool) <= 15:
            return pool

        # Mix: first 3 (oldest — signatures are more consistent historically),
        # last 3 (most recent), plus 9 of the longest from the middle.
        first = pool[:3]
        last = pool[-3:]
        middle_candidates = sorted(
            pool[3:-3],
            key=lambda e: len(e.body or ""),
            reverse=True,
        )[:9]
        return first + middle_candidates + last

    def _build_prompt(self, indexed: IndexedEmails, sample: list, lang: str = "fr") -> str:
        """Build the user prompt with email samples.

        Bodies are included at up to 1800 chars so the signature block
        (usually in the last 5-10 lines) stays visible to the LLM. Without
        it, signature.company / signature.title are impossible to extract.
        Only name / title / company / department are persisted — full_text
        and phone are deliberately not asked for.
        """
        if lang == "en":
            reminder = (
                "REMINDER: user_name = the signer of the From: field below (= User email). "
                "Names in To/Cc, in the body (vocatives), or in forwarded signatures are "
                "CONTACTS, NOT the user."
            )
            signature_hint = (
                "SIGNATURE EXTRACTION: look CAREFULLY at the last 10 lines of each "
                "Body below. A typical signature contains name, title, company, "
                "often separated by '--', a line break, or an empty line. Extract "
                "signature.name / title / company / department as soon as any email "
                "contains a consistent one."
            )
        else:
            reminder = (
                "RAPPEL : user_name = signataire du champ From: ci-dessous (= User email).\n"
                "Les noms dans To/Cc, dans le corps (vocatifs), ou dans des signatures "
                "forwardées sont des CONTACTS, PAS l'utilisateur."
            )
            signature_hint = (
                "EXTRACTION DE LA SIGNATURE : regarde ATTENTIVEMENT les 10 dernières "
                "lignes de chaque Body ci-dessous. Une signature typique contient nom, "
                "poste, entreprise, souvent séparés par '--', un saut de ligne, ou "
                "une ligne vide. Extrais signature.name / title / company / department "
                "dès qu'un seul email en contient une cohérente."
            )

        lines = [
            f"User email: {indexed.user_email}",
            f"Total sent emails: {indexed.sent_count}",
            f"Total received emails: {indexed.received_count}",
            "",
            reminder,
            "",
            signature_hint,
            "",
            "=== SENT EMAIL SAMPLES ===",
        ]

        for i, email in enumerate(sample, 1):
            from_display = (
                f"{email.sender_name} <{email.sender_email}>"
                if email.sender_name
                else email.sender_email
            )
            lines.append(f"\n--- Email {i} ---")
            lines.append(f"From: {from_display}")
            lines.append(f"To: {', '.join(email.recipients)}")
            lines.append(f"Subject: {email.subject}")
            lines.append(f"Date: {email.date.isoformat()}")
            lines.append(f"Language: {email.language.value}")
            body_preview = email.body[:1800] if email.body else "(empty)"
            lines.append(f"Body:\n{body_preview}")
            if email.signature:
                lines.append(f"Signature:\n{email.signature}")

        lines.append("\n=== END SAMPLES ===")
        lines.append("\nAnalyse these sent emails and produce the JSON profile.")

        return "\n".join(lines)
