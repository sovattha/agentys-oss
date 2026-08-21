# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
LabelAgent: analyses user folders/labels to produce default label rules.

Output: default label rules (Action/FYI/Noise) and volume statistics.
Aligns with Pillar 4 (Auto-Label) of the training UI.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List

from app.config import MODEL_FAST
from app.domain.ports.llm_port import LLMPort
from app.infrastructure.container import get_container
from app.onboarding.agents._usage_telemetry import record_agent_usage
from app.onboarding.agents.prompts import load_prompt
from app.onboarding.indexer import IndexedEmails
from app.utils.json_parser import extract_json_from_response

logger = logging.getLogger(__name__)

MAX_TOKENS_LABEL = 8192
MAX_RETRIES = 2
MAX_RECEIVED_EMAILS = 40

_KEY_ALIASES = {
    "rules": "default_label_rules",
    "label_rules": "default_label_rules",
    "stats": "statistics",
}

SCHEMA_REPAIR_PROMPT = """Tu reçois un JSON qui contient des données de catégorisation d'emails, mais les clés ne correspondent pas au schéma attendu.

Schéma attendu :
{
  "default_label_rules": [{"label_name": "...", "condition_type": "...", "condition_value": "...", "confidence": 0.0, "reason": "..."}],
  "statistics": {"noise": 0, "fyi": 0, "action": 0, "waiting": 0}
}

Convertis le JSON fourni vers ce schéma. Mappe les données existantes vers les bonnes clés.
Supprime toute clé "suggested_labels", "custom_label_rules" — elles ne font pas partie du schéma.
CRITIQUE : Produis UNIQUEMENT un objet JSON valide. Pas de markdown, pas d'explication."""

# System folder names to ignore when suggesting labels
_SYSTEM_FOLDERS = {
    "inbox", "sent", "sent items", "sent mail", "drafts", "draft",
    "trash", "deleted items", "spam", "junk", "archive", "outbox",
    "all mail", "starred", "important", "chats", "scheduled",
    "[gmail]", "[gmail]/all mail", "[gmail]/sent mail", "[gmail]/drafts",
    "[gmail]/spam", "[gmail]/trash", "[gmail]/starred", "[gmail]/important",
    "notes", "journal", "contacts", "calendar", "tasks",
    "conversation history", "sync issues",
}


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
        logger.info("LabelAgent: clés remappées vers le schéma attendu")

    return result


def _sample_received_emails(indexed: IndexedEmails, max_count: int = MAX_RECEIVED_EMAILS) -> list:
    """Sample received emails: first 10 + last 10 + distributed from the middle."""
    received = indexed.received_emails
    if len(received) <= max_count:
        return received

    first = received[:10]
    last = received[-10:]
    middle = received[10:-10]

    remaining = max_count - 20
    if remaining > 0 and middle:
        step = max(1, len(middle) // remaining)
        distributed = middle[::step][:remaining]
    else:
        distributed = []

    return first + distributed + last


@dataclass
class FolderInfo:
    """Lightweight folder info for the LabelAgent prompt."""
    name: str
    display_name: str
    type: str  # "inbox", "sent", "custom", etc.
    total_count: int = 0


@dataclass
class LabelAgent:
    """
    Analyses user folders and existing labels to suggest personalized labels.
    """
    model: str = MODEL_FAST
    max_tokens: int = MAX_TOKENS_LABEL
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        if self._llm is None:
            # Onboarding pipeline — Haiku worker tier by default (2026-05-05).
            self._llm = get_container().llm_onboarding_worker

    def analyse(self, indexed: IndexedEmails, folders: Optional[List[FolderInfo]] = None) -> dict:
        """
        Analyse folders/labels to suggest personalized labels.

        Args:
            indexed: The indexed email corpus (used for metadata like user_email).
            folders: Optional list of user's email folders from the provider.

        Returns:
            Dict matching the CategoryAnalysis schema.
        """
        lang = indexed.primary_language.value
        user_prompt = self._build_prompt(indexed, folders, lang)
        default = {
            "default_label_rules": [],
            "statistics": {},
        }

        system = load_prompt("label", lang=lang)
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
                    "LabelAgent: erreur LLM (tentative %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    continue
                raise
            last_raw_response = response.content

            result = extract_json_from_response(
                response.content,
                default=default,
                error_context="LabelAgent",
            )

            result = _try_remap_keys(result)

            if result.get("default_label_rules"):
                break

            logger.warning(
                "LabelAgent: résultat vide (tentative %d/%d). "
                "Réponse LLM (%d chars) : %.500s",
                attempt, MAX_RETRIES,
                len(response.content), response.content[:500],
            )
        else:
            if last_raw_response and len(last_raw_response) > 50:
                logger.info("LabelAgent: tentative de réparation du schéma via LLM")
                repaired = self._repair_schema_with_llm(last_raw_response)
                if repaired and repaired.get("default_label_rules"):
                    result = repaired
                    logger.info("LabelAgent: schéma réparé avec succès via LLM fallback")
                else:
                    logger.warning("LabelAgent: résultat vide après %d tentatives + fallback LLM", MAX_RETRIES)
            else:
                logger.warning("LabelAgent: résultat vide après %d tentatives", MAX_RETRIES)

        record_agent_usage(
            "label", response, self.max_tokens,
            (time.perf_counter() - _t0) * 1000.0, attempt,
        )

        # OB-C-3 (audit 2026-04-25): mark partial when retries exhaust
        # with no default_label_rules so onboarding doesn't silently
        # complete with zero auto-labelling rules — user would otherwise
        # see no badges on incoming emails and assume the AI is broken.
        if not result.get("default_label_rules"):
            result["_partial"] = True
            result.setdefault("_reason", "empty_label_rules")
        result.setdefault("default_label_rules", [])
        result.setdefault("statistics", {})

        # Defense in depth: strip any suggested_labels / custom_label_rules the
        # LLM may have returned. The prompt forbids them; Step4SmartOrg does not
        # consume them; keeping them would bloat categories_json for nothing.
        result.pop("suggested_labels", None)
        result.pop("custom_label_rules", None)

        logger.info(
            "LabelAgent: found %d default rules",
            len(result["default_label_rules"]),
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
                error_context="LabelAgent.repair",
            )
            if result:
                result = _try_remap_keys(result)
            return result
        except Exception as e:
            logger.warning("LabelAgent: erreur lors du fallback LLM : %s", e)
            return None

    def _get_existing_labels_text(self, lang: str = "fr", account_id: int = 0) -> str:
        """Get existing labels (default + custom) for the prompt.

        OB-C-1 (audit 2026-04-25 onboarding-flawless): when account_id is
        passed, read from the per-account store at
        `data/labels/<account_id>/`. Otherwise fall back to the global
        store (legacy single-account install). Without this scoping User
        A's custom labels appeared in User B's prompt on a multi-user
        deploy and biased the LabelAgent toward A's categories.
        """
        is_en = lang == "en"
        # P1-008: never fall back to the global store when account_id is
        # missing — that would include every other tenant's custom labels
        # in this account's prompt and bias LabelAgent across users.
        if not account_id:
            logger.warning(
                "LabelAgent._get_existing_labels_text called with account_id=0 "
                "— returning defaults to prevent cross-tenant label leak"
            )
            return "Default labels: Action, FYI, Noise." if is_en else "Labels par défaut : Action, FYI, Noise."
        try:
            container = get_container()
            store = container.get_label_store(account_id=account_id)
            labels = store.get_labels()
            if not labels:
                return "No existing label." if is_en else "Aucun label existant."
            lines = []
            for lbl in labels:
                tag = (" (default)" if is_en else " (défaut)") if lbl.is_default else " (custom)"
                lines.append(f"  - {lbl.name}{tag}")
            return "\n".join(lines)
        except Exception:
            return (
                "Default labels: Action, FYI, Noise." if is_en
                else "Labels par défaut : Action, FYI, Noise."
            )

    def _build_prompt(self, indexed: IndexedEmails, folders: Optional[List[FolderInfo]] = None, lang: str = "fr") -> str:
        # OB-C-1: derive account_id from the indexed corpus so the
        # existing-labels list comes from the per-account store. The
        # IndexedEmails dataclass carries account_id since the audit's
        # OB-C-2 fix.
        """Build the user prompt from folders and existing labels."""
        is_en = lang == "en"
        header_existing = "=== EXISTING AGENTYS LABELS ===" if is_en else "=== LABELS EXISTANTS DANS AGENTYS ==="
        total_line = (
            f"Total emails in inbox: {indexed.received_count}" if is_en
            else f"Total emails dans la boîte: {indexed.received_count}"
        )
        header_folders = "=== MAILBOX FOLDERS/LABELS ===" if is_en else "=== DOSSIERS/LABELS DU COMPTE EMAIL ==="
        none_custom = "  No custom folder found." if is_en else "  Aucun dossier custom trouvé."
        none_available = "  (Not available)" if is_en else "  (Non disponible)"
        instruction = (
            "Analyse these folders and labels. Generate categorisation rules "
            "Action/FYI/Noise. Do not propose custom labels. Produce the JSON."
            if is_en else
            "Analyse ces dossiers et labels. Génère des règles de catégorisation "
            "Action/FYI/Noise. Ne propose pas de labels custom. Produis le JSON."
        )

        lines = [
            f"User email: {indexed.user_email}",
            total_line,
            "",
            header_existing,
            self._get_existing_labels_text(lang=lang, account_id=getattr(indexed, "account_id", 0) or 0),
            "",
        ]

        # Folders from the email provider
        if folders:
            custom_folders = [
                f for f in folders
                if f.name.lower() not in _SYSTEM_FOLDERS
                and f.type == "custom"
            ]
            lines.append(header_folders)
            if custom_folders:
                for f in custom_folders:
                    count_str = f" ({f.total_count} emails)" if f.total_count > 0 else ""
                    lines.append(f"  - {f.display_name}{count_str}")
            else:
                lines.append(none_custom)
            lines.append("")
        else:
            lines.append(header_folders)
            lines.append(none_available)
            lines.append("")

        lines.append(instruction)

        return "\n".join(lines)
