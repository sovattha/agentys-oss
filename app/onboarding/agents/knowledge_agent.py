# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
KnowledgeAgent: analyses email content to extract business knowledge.

Output: contacts with types/roles/language_variant.

NOTE: This agent does NOT extract FAQ, projects, or terminology.
FAQ entries are provided by the user via website scan or document upload
(see app/services/faq_scanner.py). Projects were removed because downstream
Step4SmartOrg would auto-create labels without user consent. Terminology was
removed because LLMs already know sector jargon. Any such key returned by
the LLM is filtered out below.
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
from app.utils.signature import extract_signature_zone

logger = logging.getLogger(__name__)

MAX_TOKENS_KNOWLEDGE = 8192
MAX_RETRIES = 2

# #960 — fenêtre de signature contact (extraits des emails REÇUS).
# Bornes volontairement serrées : on expose la zone de signature d'un
# contact, jamais son corps d'email (cf. règle d'isolation 24d2e3e5).
_SIG_EXCERPT_MAX_CHARS = 350
_SIG_MAX_LINES = 8
_SIG_MAX_LINE_LEN = 80

# Clés alternatives connues → clé attendue
_KEY_ALIASES = {
    "contact_metrics": "contacts",
    "contact_list": "contacts",
}

# Clés hallucinées que le LLM peut renvoyer spontanément et qu'on veut
# toujours écarter — voir le commentaire en tête du fichier.
# FAQ is now user-provided (via scan/upload), not AI-guessed from emails.
_FORBIDDEN_KEYS = ("projects", "project_list", "project_metrics", "project_names",
                   "terminology", "terms", "glossary",
                   "faq", "faqs", "faq_entries")

SCHEMA_REPAIR_PROMPT = """Tu reçois un JSON qui contient des données de contacts extraits d'emails, mais les clés ne correspondent pas au schéma attendu.

Schéma attendu :
{
  "contacts": [{"email": "...", "name": "...", "company": "...", "title": "...", "preferred_language": "...", "preferred_tone": "...", "language_variant": "fr-FR"}]
}

Convertis le JSON fourni vers ce schéma. Mappe les données existantes vers les bonnes clés.
Supprime toute clé "terminology", "terms", "glossary", "faq", "projects", "type", "topics" — elles ne font pas partie du schéma.
CRITIQUE : Produis UNIQUEMENT un objet JSON valide. Pas de markdown, pas d'explication."""


def _try_remap_keys(result: dict) -> dict:
    """Remappe les clés alternatives connues vers le schéma attendu."""
    if not result or not isinstance(result, dict):
        return result

    remapped = False
    for alias, expected in _KEY_ALIASES.items():
        if alias in result and expected not in result:
            result[expected] = result.pop(alias)
            remapped = True

    if remapped:
        logger.info("KnowledgeAgent: clés remappées vers le schéma attendu")

    return result


@dataclass
class KnowledgeAgent:
    """
    Analyses email content to extract business knowledge.

    Uses the LLM to identify contacts and recurring FAQ.
    Projects are NOT extracted — see module docstring for why.
    """
    model: str = MODEL_FAST
    max_tokens: int = MAX_TOKENS_KNOWLEDGE
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        if self._llm is None:
            # Onboarding pipeline — Haiku worker tier by default (2026-05-05).
            self._llm = get_container().llm_onboarding_worker

    def analyse(self, indexed: IndexedEmails) -> dict:
        """
        Analyse indexed emails and extract business knowledge.

        Args:
            indexed: The indexed email corpus.

        Returns:
            Dict matching the KnowledgeBase schema.
        """
        lang = indexed.primary_language.value
        user_prompt = self._build_prompt(indexed, lang)
        default = {"contacts": []}

        system = load_prompt("knowledge", lang=lang)

        last_raw_response = ""

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
                    "KnowledgeAgent: erreur LLM (tentative %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    continue
                raise
            last_raw_response = response.content

            result = extract_json_from_response(
                response.content,
                default=default,
                error_context="KnowledgeAgent",
            )

            # Essayer le remapping de clés si le schéma ne correspond pas
            result = _try_remap_keys(result)

            if result.get("contacts"):
                break

            logger.warning(
                "KnowledgeAgent: résultat vide (tentative %d/%d). "
                "Réponse LLM (%d chars) : %.500s",
                attempt, MAX_RETRIES,
                len(response.content), response.content[:500],
            )
        else:
            # Toutes les tentatives ont échoué — essayer le fallback LLM
            if last_raw_response and len(last_raw_response) > 50:
                logger.info("KnowledgeAgent: tentative de réparation du schéma via LLM")
                repaired = self._repair_schema_with_llm(last_raw_response)
                if repaired and repaired.get("contacts"):
                    result = repaired
                    logger.info("KnowledgeAgent: schéma réparé avec succès via LLM fallback")
                else:
                    logger.warning("KnowledgeAgent: résultat vide après %d tentatives + fallback LLM", MAX_RETRIES)
            else:
                logger.warning("KnowledgeAgent: résultat vide après %d tentatives", MAX_RETRIES)

        record_agent_usage(
            "knowledge", response, self.max_tokens,
            (time.perf_counter() - _t0) * 1000.0, attempt,
        )

        # OB-C-3 (audit 2026-04-25 onboarding-flawless): if every retry +
        # LLM repair fallback came back empty, mark the result partial so
        # the orchestrator can route the run to status="partial" instead
        # of silently completing with an empty knowledge base. The UI then
        # surfaces "we couldn't extract contacts from your mailbox —
        # retry from Settings" instead of a green checkmark over nothing.
        if not result.get("contacts"):
            result["_partial"] = True
            result.setdefault("_reason", "empty_knowledge")
        result.setdefault("contacts", [])

        # Defense in depth: drop any project-like keys the LLM may still
        # have hallucinated. Downstream code (Step4SmartOrg) must never
        # see auto-generated projects — the user opted out explicitly.
        dropped = [k for k in _FORBIDDEN_KEYS if k in result]
        for k in dropped:
            result.pop(k, None)
        if dropped:
            logger.info(
                "KnowledgeAgent: dropped hallucinated keys from LLM response: %s",
                ", ".join(dropped),
            )

        # Per-contact scrub: `type`, `topics` and `interaction_count` were
        # removed from the prompt schema — they cost LLM tokens but weren't
        # consumed by the drafter pipeline. `interaction_count` is now filled
        # server-side from the indexer metrics (no LLM hallucination of
        # numbers). Defense-in-depth scrub here catches any stray output.
        _scrubbed = 0
        for contact in result.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            for forbidden in ("type", "topics", "interaction_count"):
                if forbidden in contact:
                    contact.pop(forbidden, None)
                    _scrubbed += 1
        if _scrubbed:
            logger.debug(
                "KnowledgeAgent: scrubbed %d deprecated per-contact keys",
                _scrubbed,
            )

        # Server-side fill: copy total_interactions from the indexer metrics
        # into each contact. The orchestrator and downstream consumers expect
        # this field; we compute it deterministically instead of asking the
        # LLM to echo the number we already have.
        metrics_by_email = {
            email.lower(): m for email, m in indexed.contact_metrics.items()
        }
        for contact in result.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            email_key = (contact.get("email") or "").lower()
            m = metrics_by_email.get(email_key)
            if m is not None:
                contact["interaction_count"] = m.sent_count + m.received_count
            else:
                contact["interaction_count"] = 0

        logger.info(
            "KnowledgeAgent: found %d contacts",
            len(result["contacts"]),
        )
        return result

    def _repair_schema_with_llm(self, raw_response: str) -> Optional[dict]:
        """Envoie la réponse brute au LLM pour corriger le schéma JSON."""
        try:
            response = self._llm.complete(
                system=SCHEMA_REPAIR_PROMPT,
                user=raw_response,
                max_tokens=self.max_tokens,
                temperature=0.0,
            )
            result = extract_json_from_response(
                response.content,
                default=None,
                error_context="KnowledgeAgent.repair",
            )
            if result:
                result = _try_remap_keys(result)
            # P1-009: return {} instead of None so orchestrator never receives
            # NoneType and crashes on result.get("contacts").
            return result or {}
        except Exception as e:
            logger.warning("KnowledgeAgent: erreur lors du fallback LLM : %s", e)
            return {}

    @staticmethod
    def _contact_signature_excerpt(indexed: IndexedEmails, contact_email: str) -> str:
        """Extrait borné de la signature d'un contact depuis ses emails REÇUS.

        #960 — le titre et l'entreprise d'un contact vivent dans SA signature,
        donc dans les corps REÇUS que la règle d'isolation masque du prompt :
        le prompt système exige « titre du poste (null si non visible dans une
        signature) » mais le builder ne montrait aucune signature de contact →
        ``title`` était structurellement null. On rouvre une fenêtre minimale
        sans abandonner l'isolation :

        * champ ``signature`` explicite de l'email s'il est renseigné,
        * sinon la zone de signature (``extract_signature_zone``) filtrée aux
          lignes courtes (la prose dépasse ``_SIG_MAX_LINE_LEN``),
        * jamais un corps entier : si l'extrait recouvre le début du corps
          (email court), il est rejeté.
        """
        contact = contact_email.lower()
        received = [
            m
            for m in reversed(indexed.by_contact.get(contact, []))
            if m.sender_email.lower() == contact
        ]
        for msg in received:  # by_contact est trié par date → plus récent d'abord
            if msg.signature and msg.signature.strip():
                return msg.signature.strip()[:_SIG_EXCERPT_MAX_CHARS]
        for msg in received:
            body = (msg.body or "").strip()
            if not body:
                continue
            zone = extract_signature_zone(body)
            tail_lines = [ln.strip() for ln in zone.splitlines() if ln.strip()]
            sig_lines = [
                ln for ln in tail_lines[-_SIG_MAX_LINES:] if len(ln) <= _SIG_MAX_LINE_LEN
            ]
            excerpt = "\n".join(sig_lines).strip()
            if not excerpt:
                continue
            if len(body) - len(excerpt) < 40:
                # Email court : l'« extrait » serait quasi le corps entier —
                # refusé, la règle d'isolation prime sur le titre manquant.
                continue
            return excerpt[:_SIG_EXCERPT_MAX_CHARS]
        return ""

    def _build_prompt(self, indexed: IndexedEmails, lang: str = "fr") -> str:
        """Build the user prompt with contact metrics and email samples.

        CRITICAL isolation rule: bodies of RECEIVED emails are NEVER shown
        to the LLM — only SENT bodies (written by the user) are included.
        This prevents the model from hallucinating content or signatures
        from third-party correspondents as if they were the user's own.
        Sole bounded exception (#960): per-contact SIGNATURE excerpts,
        explicitly labelled as third-party, so title/company can be read —
        see ``_contact_signature_excerpt``.
        """
        user_email = indexed.user_email.lower()
        lines = [
            f"User email: {indexed.user_email}",
            f"Total emails: {indexed.total_count}",
            f"Sent by user: {indexed.sent_count} | Received: {indexed.received_count}",
            "",
            "=== CONTACT METRICS ===",
        ]

        # Rank contacts by how much the USER writes to them (sent_count), then
        # received as a tiebreaker — consistent with the VIP suggestion endpoint
        # (`routes_contacts._aggregate_top_contacts`). The previous
        # "bidirectional > total volume" key over-weighted the inbound side,
        # which a shallow inbound sync makes unreliable: it floated
        # received-heavy senders (notifications that slip past the noise filter)
        # above the real correspondents the user actually writes to but whose
        # replies aren't all cached (cf. the VIP "Karine" diagnostic). The top-25
        # cap and the indexer's noise filtering are unchanged.
        sorted_contacts = sorted(
            indexed.contact_metrics.items(),
            key=lambda kv: (-kv[1].sent_count, -kv[1].received_count, kv[0]),
        )

        for email, metrics in sorted_contacts[:25]:
            total = metrics.sent_count + metrics.received_count
            lines.append(
                f"- {email} (name: {metrics.name or 'unknown'}, "
                f"total_interactions: {total}, "
                f"sent: {metrics.sent_count}, received: {metrics.received_count}, "
                f"threads: {len(metrics.threads)})"
            )
            if metrics.subjects:
                subj_sample = metrics.subjects[:5]
                lines.append(f"  Subjects: {'; '.join(subj_sample)}")

        # #960 — fenêtre bornée sur les signatures des contacts (et rien
        # d'autre des corps REÇUS) : c'est la seule source possible pour
        # company/title que le prompt système exige déjà de lire « dans une
        # signature ».
        sig_blocks: list[str] = []
        for email, _metrics in sorted_contacts[:25]:
            excerpt = self._contact_signature_excerpt(indexed, email)
            if excerpt:
                sig_blocks.append(f"\n[{email}]")
                sig_blocks.append(excerpt)
        if sig_blocks:
            lines.append(
                "\n=== CONTACT SIGNATURES (third-party excerpts from RECEIVED emails) ==="
            )
            lines.append(
                "Signature zones written by the CONTACTS themselves (NOT the user). "
                "Use them ONLY to fill that contact's name/company/title/"
                "language_variant. Never attribute their content to the user."
            )
            lines.extend(sig_blocks)

        # Transverse sample of the USER's own writing (SENT only).
        # Contact analysis and FAQ detection are based on these — NEVER
        # from received emails.
        lines.append("\n=== USER SENT SAMPLE (this is the user's OWN writing) ===")
        sent_sample = indexed.sent_emails[-40:]  # most recent 40 sent
        for email in sent_sample:
            body_preview = email.body[:400] if email.body else "(empty)"
            lines.append(f"\n[SENT] Subject: {email.subject}")
            lines.append(f"To: {', '.join(email.recipients[:3])}")
            lines.append(body_preview)

        # Threads are included only for structural context (who talked to
        # whom, thread length, subjects). Bodies of RECV emails are
        # deliberately omitted so the LLM cannot paraphrase third-party
        # content as if it were the user's own.
        lines.append("\n=== THREAD STRUCTURE (context only — RECV bodies omitted) ===")
        thread_items = sorted(
            indexed.by_thread.values(),
            key=lambda t: len(t.emails),
            reverse=True,
        )[:10]

        for thread in thread_items:
            lines.append(f"\n--- Thread: {thread.subject} ({len(thread.emails)} emails) ---")
            lines.append(f"Participants: {', '.join(thread.participants)}")
            for email in thread.emails[:4]:
                is_sent = email.sender_email.lower() == user_email
                if is_sent:
                    body_preview = email.body[:300] if email.body else "(empty)"
                    lines.append(
                        f"[SENT by user] -> {', '.join(email.recipients[:3])}"
                    )
                    lines.append(body_preview)
                else:
                    lines.append(
                        f"[RECV from {email.sender_email}] "
                        f"(body omitted — not the user's content)"
                    )

        lines.append("\n=== END ===")
        lines.append(
            "\nAnalyse the contacts and the USER SENT SAMPLE. "
            "For each contact, fill company and title from its CONTACT SIGNATURES "
            "excerpt when present (keep title null when absent — never invent), and "
            "detect their language_variant (ISO code like fr-CA, fr-FR, en-US) "
            "from their vocabulary and signature address. "
            "Produce the JSON knowledge base."
        )

        return "\n".join(lines)
