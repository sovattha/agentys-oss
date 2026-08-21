# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
StyleAgent: analyses communication patterns to extract writing style rules.

Output: per-contact rules (tone, language, greeting, closing),
general response rules, forbidden phrases.
Aligns with Pillar 2 (Style d'écriture) of the training UI.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import MODEL_FAST
from app.domain.ports.llm_port import LLMPort
from app.infrastructure.container import get_container
from app.onboarding.agents._usage_telemetry import record_agent_usage
from app.onboarding.agents.prompts import load_prompt
from app.onboarding.indexer import IndexedEmails
from app.utils.json_parser import extract_json_from_response

logger = logging.getLogger(__name__)

MAX_TOKENS_STYLE = 8192
MAX_RETRIES = 2


@dataclass
class StyleAgent:
    """
    Analyses communication patterns to extract writing style rules.

    Uses the LLM to identify per-contact and general style rules.
    Aligns with Pillar 2 (Style d'écriture) of the training UI.
    """
    model: str = MODEL_FAST
    max_tokens: int = MAX_TOKENS_STYLE
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        if self._llm is None:
            # Onboarding pipeline — Haiku worker tier by default (2026-05-05).
            self._llm = get_container().llm_onboarding_worker

    def analyse(self, indexed: IndexedEmails) -> dict:
        """
        Analyse indexed emails and extract writing style rules.

        Args:
            indexed: The indexed email corpus.

        Returns:
            Dict matching the RulesSet schema.
        """
        lang = indexed.primary_language.value
        user_prompt = self._build_prompt(indexed, lang)
        default = {"contact_rules": [], "general_rules": [], "forbidden_phrases": []}

        system = load_prompt("style", lang=lang)

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
                    "StyleAgent: erreur LLM (tentative %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    continue
                raise

            result = extract_json_from_response(
                response.content,
                default=default,
                error_context="StyleAgent",
            )

            if result.get("contact_rules") or result.get("general_rules"):
                break

            logger.warning(
                "StyleAgent: résultat vide (tentative %d/%d). "
                "Réponse LLM (%d chars) : %.500s",
                attempt, MAX_RETRIES,
                len(response.content), response.content[:500],
            )
        else:
            logger.warning("StyleAgent: résultat vide après %d tentatives", MAX_RETRIES)

        record_agent_usage(
            "style", response, self.max_tokens,
            (time.perf_counter() - _t0) * 1000.0, attempt,
        )

        # OB-C-3 (audit 2026-04-25): mark partial when all retries
        # exhausted with empty rule sets so the orchestrator routes the
        # run to status="partial" — the user sees an actionable banner
        # instead of a "completed" run with zero personalised style.
        if not result.get("contact_rules") and not result.get("general_rules"):
            result["_partial"] = True
            result.setdefault("_reason", "empty_style")
        result.setdefault("contact_rules", [])
        result.setdefault("general_rules", [])
        result.setdefault("forbidden_phrases", [])

        logger.info(
            "StyleAgent: extracted %d contact rules, %d general rules",
            len(result["contact_rules"]), len(result["general_rules"]),
        )
        return result

    def _build_prompt(self, indexed: IndexedEmails, lang: str = "fr") -> str:
        """Build the user prompt with sent emails grouped by contact.

        For each contact we keep the 3-5 most informative sent emails
        (long enough to contain a full greeting+body+closing structure),
        not the arbitrary first 5, so the LLM can spot real stylistic
        patterns instead of being misled by one-line acknowledgements.
        """
        lines = [
            f"User email: {indexed.user_email}",
            f"Total sent emails: {indexed.sent_count}",
            "",
            "=== SENT EMAILS GROUPED BY CONTACT ===",
        ]

        # Group sent emails by primary recipient
        by_recipient: dict[str, list] = {}
        for email in indexed.sent_emails:
            if email.recipients:
                key = email.recipients[0].lower()
                by_recipient.setdefault(key, []).append(email)

        # Sort contacts by email count and take top 20.
        # NOTE (2026-05-26): trimming this 20 → 12 was measured + eval'd as a
        # latency lever and REJECTED — it regressed the eval rules score
        # (default 100 → 71, sales 100 → 86) by dropping per-contact rules the
        # ground truth wants. Style emits ~16 rules from 20 contacts, so any cap
        # ≥ 16 yields no output reduction and any cap < 16 regresses quality.
        # The contact count is not a usable speed knob; do not re-trim it.
        sorted_contacts = sorted(
            by_recipient.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:20]

        for contact_email, emails in sorted_contacts:
            metrics = indexed.contact_metrics.get(contact_email)
            contact_name = metrics.name if metrics else "unknown"
            lines.append(
                f"\n--- Contact: {contact_name} <{contact_email}> "
                f"({len(emails)} sent) ---"
            )

            # Rank: longer bodies first (more likely to show full structure
            # greeting + body + closing). Drop zero/one-line replies that
            # would skew StyleAgent toward a fake "ultra-casual" register.
            ranked = sorted(
                emails,
                key=lambda e: len(e.body or ""),
                reverse=True,
            )[:5]

            for email in ranked:
                lines.append(f"\nSubject: {email.subject}")
                lines.append(f"Date: {email.date.isoformat()}")
                body_preview = email.body[:800] if email.body else "(empty)"
                lines.append(f"Body:\n{body_preview}")

        lines.append("\n=== END ===")
        lines.append(
            "\nAnalyse the sent emails above. Extract per-contact rules "
            "and general communication patterns. Produce the JSON rules."
        )

        return "\n".join(lines)
