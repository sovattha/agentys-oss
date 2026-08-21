# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
OnboardingManager: orchestrates the full onboarding knowledge base process.

Steps: load emails -> index -> analyse (profile, knowledge, rules) -> store results.
Emits WebSocket events at each step.
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Optional, Sequence, TypedDict

if TYPE_CHECKING:
    from app.db.models.email import Email

from app.db.models.onboarding_result import OnboardingResult as OnboardingResultModel
from app.db.repositories.onboarding_repository import OnboardingRepository
from app.db.repositories.email_repository import EmailRepository
from app.onboarding.loader import RepositoryLoader
from app.onboarding.indexer import EmailIndexer
from app.onboarding.orchestrator import OnboardingOrchestrator, OnboardingProgress, OnboardingDiscovery

logger = logging.getLogger(__name__)

# Module-level watchdog state. Each /api/onboarding/* request spawns a fresh
# OnboardingManager instance via _get_manager(), so per-instance dicts would
# vanish between the worker thread (which keeps a reference to the manager
# that started it) and the cleanup_stale_onboardings call (which sees a
# different instance). Sharing the heartbeat dict at module scope makes the
# watchdog observable from any instance in the same process.
_LAST_HEARTBEAT: dict[int, float] = {}
_HEARTBEAT_LOCK = threading.Lock()
# P0-005: cap the heartbeat dict so a flood of start requests (or zombie threads
# whose finally block never ran) cannot grow it unboundedly and OOM the process.
# FIFO eviction mirrors the pattern used for _status_rate_buckets.
_HEARTBEAT_MAX_KEYS = 5_000


class _SentCachePopulateResult(TypedDict):
    stored: int
    attempted: bool
    failed: bool
    via: Optional[str]


def _bump_heartbeat_global(onboarding_id: int) -> None:
    with _HEARTBEAT_LOCK:
        if onboarding_id not in _LAST_HEARTBEAT and len(_LAST_HEARTBEAT) >= _HEARTBEAT_MAX_KEYS:
            try:
                oldest_key = next(iter(_LAST_HEARTBEAT))
                _LAST_HEARTBEAT.pop(oldest_key, None)
            except StopIteration:
                pass
        _LAST_HEARTBEAT[onboarding_id] = time.monotonic()


def _clear_heartbeat_global(onboarding_id: int) -> None:
    with _HEARTBEAT_LOCK:
        _LAST_HEARTBEAT.pop(onboarding_id, None)


def _snapshot_heartbeats_global() -> dict[int, float]:
    with _HEARTBEAT_LOCK:
        return dict(_LAST_HEARTBEAT)


def _heartbeat_age_seconds_global(onboarding_id: int) -> Optional[float]:
    with _HEARTBEAT_LOCK:
        last_seen = _LAST_HEARTBEAT.get(onboarding_id)
    if last_seen is None:
        return None
    return max(0.0, time.monotonic() - last_seen)


# Target number of synced emails that's considered "comfortable" before running
# the full analysis. This is aspirational — the analysis also works on partial
# inbox because _run_analysis populates its own sent cache directly from the
# provider (up to 200 sent emails), which is the actual source of truth for
# writing-style inference.
MIN_EMAILS_FOR_ANALYSIS = 15

# Fast-start threshold: after MIN_EMAILS_FOR_FAST_START emails AND
# FAST_START_AFTER_SECONDS elapsed, proceed with analysis even if full
# MIN_EMAILS_FOR_ANALYSIS isn't reached.
#
# Historical note (2026-04-24): these used to be (5 emails, 30s). In prod we
# observed users stuck at "1/15 emails" for 5 minutes whenever Gmail's
# batch-fetch endpoint returned 429s without a Retry-After header — the
# provider adapter backs off to 60s between fetches, so the inbox count was
# still at 1-2 emails when the fast-start elapsed kicked in. Since the
# analysis pipeline doesn't actually need inbox emails (it pulls sent emails
# directly), we lower the fast-start threshold to 1 email so a single synced
# email is enough to unblock onboarding.
MIN_EMAILS_FOR_FAST_START = 1
FAST_START_AFTER_SECONDS = 15

# Stale-count threshold: if current_count has not increased for this many
# seconds AND we have at least one email, proceed with analysis. This is the
# Gmail-rate-limit short-circuit — if the sync is demonstrably stuck (Gmail
# 429s, auth hiccup, provider slowness), we don't make the user wait for the
# hard timeout. The analysis pipeline will use whatever inbox context is
# available plus the sent-cache fetch it runs independently.
SYNC_STALE_THRESHOLD_SECONDS = 45

# Max time we wait for the initial email sync to populate the inbox
# before proceeding with partial data (if count > 0) or failing with a clear
# error (if count == 0). Lowered from 300s → 120s because the fast-start and
# stale-threshold paths cover the happy cases; anything past 2 minutes means
# the provider itself is broken and more waiting won't help.
SYNC_WAIT_TIMEOUT_SECONDS = 120

# How often we re-check the email count while waiting for sync.
SYNC_WAIT_POLL_INTERVAL_SECONDS = 3

# Retry grace for an active DB row with no live worker heartbeat. A fresh row may
# briefly have no observable heartbeat during startup/reload races; after this
# window, a user retry should be allowed to replace the orphaned row.
ACTIVE_ONBOARDING_RETRY_GRACE_SECONDS = 60

# Cold-onboarding sent-email fetch size. _populate_sent_cache pulls this many of
# the user's most recent sent emails from the provider when the DB sent cache is
# empty. The analysis agents consume far fewer (the loader caps the sent slice at
# ~100; Profile uses 15, Knowledge 40, Style 20×5), so 150 fully saturates them
# while cutting ~25% off the cold first-scan provider fetch + indexing vs the
# previous 200. Warm re-runs skip this fetch entirely (cache already populated).
ONBOARDING_SENT_FETCH_LIMIT = 150


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write `content` to `path` atomically.

    OB-R3 (audit 2026-04-25 onboarding-residual): a plain
    ``Path.write_text(...)`` opens, writes, and closes in three steps.
    If the process is killed mid-write (OOM, SIGTERM, full disk) the
    file is left half-written and the next read of memoire.md surfaces
    a corrupted KB to DrafterAgent. Writing to a sibling tempfile and
    then ``Path.replace()`` makes the swap atomic on every supported
    filesystem (POSIX rename(2), NTFS MoveFileExW), so a crashed write
    leaves the previous good copy untouched. The temp file is best-
    effort cleaned on exception so we don't accumulate ``*.tmp`` debris.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise


def _flatten_profile_styles(profile: dict) -> dict:
    """Expose a singular greeting/closing next to the plural maps.

    ProfileAgent emits ``tone.greeting_styles`` / ``tone.closing_styles`` as
    dicts keyed by ``<formality>_<lang>`` (cf. ``prompts/profile.txt``).
    The frontend and DB consumers read singular ``greeting_style`` /
    ``closing_style``; without this flattening the fields render empty in
    the insights screen even though the data is present.

    Picks the value matching ``default_tone`` + primary language first,
    falls back to the first non-empty entry. Leaves the plural maps intact
    so backend consumers (memoire.md builder, WritingStyleProfile) keep
    their full choice set.
    """
    if not isinstance(profile, dict):
        return profile

    tone = profile.get("tone")
    if not isinstance(tone, dict):
        return profile

    default_tone = (tone.get("default_tone") or "semi-formal").strip().lower()
    languages = profile.get("languages") or []
    primary_lang = (languages[0] if languages else "fr").lower()
    formality_key = default_tone.replace("-", "_")
    preferred_key = f"{formality_key}_{primary_lang}"

    def _pick(plural: dict) -> str:
        from app.prompts.identity import is_placeholder_style_value

        if not isinstance(plural, dict) or not plural:
            return ""
        value = plural.get(preferred_key)
        if value and not is_placeholder_style_value(value):
            return str(value)
        # Same formality, any language.
        for k, v in plural.items():
            if v and k.startswith(f"{formality_key}_") and not is_placeholder_style_value(v):
                return str(v)
        # First non-empty.
        for v in plural.values():
            if v and not is_placeholder_style_value(v):
                return str(v)
        return ""

    if not tone.get("greeting_style"):
        tone["greeting_style"] = _pick(tone.get("greeting_styles") or {})
    if not tone.get("closing_style"):
        tone["closing_style"] = _pick(tone.get("closing_styles") or {})

    return profile


def _order_styles_by_formality(styles: dict, primary_lang: str) -> list:
    """Flatten a ``greeting_styles`` / ``closing_styles`` map into a list with
    ``[0]`` = most-formal and ``[1]`` = casual.

    The ProfileAgent emits these maps keyed by formality+language
    (``formal_fr`` / ``casual_fr`` / ``semi_formal_fr`` / ``*_en``). Every
    downstream consumer treats ``preferred_greetings[0]`` as the FORMAL slot
    and ``[1]`` as the CASUAL slot (see ``smart_routing._compute_greeting_hint``
    convention "index 0 = formal, index 1 = casual", and the Default Writing
    Style settings panel). The previous flatten took ``dict.values()`` in
    insertion order — and the prompt's own example lists ``casual_fr`` FIRST —
    so the casual greeting ("Salut {first_name},") landed in the formal slot.
    Order by the formality KEYS the LLM already classified, not by emission
    order.

    Remaining distinct values (other languages / unused registers) are appended
    so the example pool and the ``/writing-style`` listing stay complete.
    """
    if not isinstance(styles, dict) or not styles:
        return []
    lang = str(getattr(primary_lang, "value", primary_lang) or "fr").lower()
    from app.prompts.identity import is_placeholder_style_value

    # Slot 0 — most formal available (prefer primary language, then any).
    formal_order = [
        f"formal_{lang}", f"semi_formal_{lang}",
        "formal_fr", "formal_en", "semi_formal_fr", "semi_formal_en",
    ]
    # Slot 1 — casual (prefer primary language, then any).
    casual_order = [f"casual_{lang}", "casual_fr", "casual_en"]
    ordered: list = []

    def _take(keys: list) -> None:
        for k in keys:
            v = styles.get(k)
            if v and not is_placeholder_style_value(v) and str(v) not in ordered:
                ordered.append(str(v))
                return

    _take(formal_order)   # → index 0 (formal)
    _take(casual_order)   # → index 1 (casual)
    for v in styles.values():
        if v and not is_placeholder_style_value(v) and str(v) not in ordered:
            ordered.append(str(v))
    return ordered


def build_knowledge_markdown(profile: dict, knowledge: dict, rules: dict) -> str:
    """Convert onboarding results (profile/knowledge/rules) to markdown.

    This is a pure function that can be called from:
    - OnboardingManager._apply_to_knowledge_base() (writes to memoire.md)
    - DrafterAgent._resolve_knowledge() (loads KB from DB without file I/O)
    """
    lines = []

    # ── Profil section ──
    lines.append("## Profil")
    lines.append("")
    # Audit S-05 (2026-05-11): do NOT emit `[À définir]` placeholder lines
    # into the KB markdown. The Drafter reads this markdown verbatim into
    # its `<CONTEXTE>` block, and Rule 5 (ZÉRO INVENTION) says to omit a
    # line entirely rather than fabricate. The previous default
    # `[À définir]` was a forbidden bracket marker that escaped the
    # `_universal_rules.txt` strip layer because it wasn't in the
    # placeholder regex family (only `[À confirmer]` / `[TBD]` / `[REDACTE]`).
    # The user said: "je ne veux pas d'injection à définir, à confirmer, TBD".
    _user_name = (profile.get("user_name") or "").strip()
    if _user_name:
        lines.append(f"- **Nom complet**: {_user_name}")

    sig = profile.get("signature") or {}
    _company = (sig.get("company") or "").strip()
    if _company:
        lines.append(f"- **Entreprise**: {_company}")
    _title = (sig.get("title") or "").strip()
    if _title:
        lines.append(f"- **Poste**: {_title}")
    _profession = (profile.get("profession") or "").strip()
    if _profession:
        lines.append(f"- **Métier**: {_profession}")

    tone = profile.get("tone") or {}
    ton_map = {"formal": "Formel", "semi-formal": "Semi-formel", "casual": "Décontracté"}
    ton_label = ton_map.get(tone.get("default_tone", ""), "Semi-formel")
    lines.append(f"- **Ton par défaut**: {ton_label}")

    langs = profile.get("languages", [])
    if langs:
        lang_map = {"fr": "Français", "en": "Anglais"}
        if len(langs) > 1:
            lines.append("- **Langue**: Auto (détecté)")
        else:
            lines.append(f"- **Langue**: {lang_map.get(langs[0], langs[0])}")
    else:
        lines.append("- **Langue**: Auto")

    variant = (profile.get("language_variant") or "").strip()
    if variant:
        lines.append(f"- **Variante linguistique**: {variant}")

    # ── Format section ──
    # User-controlled writing format (Concise/Medium/Detailed × Simple/Standard/Sophisticated).
    # Persisted in profile_json so it survives the parse→DB→build round-trip.
    fmt = profile.get("writing_format") or {}
    longueur = (fmt.get("longueur") or "").strip().lower()
    complexite = (fmt.get("complexite") or "").strip().lower()
    if longueur in {"concis", "moyen", "detaille"} or complexite in {"accessible", "standard", "elabore"}:
        lines.append("")
        lines.append("## Format")
        lines.append("")
        if longueur in {"concis", "moyen", "detaille"}:
            lines.append(f"- **Longueur préférée**: {longueur}")
        if complexite in {"accessible", "standard", "elabore"}:
            lines.append(f"- **Vocabulaire**: {complexite}")

    # ── Savoir section ──
    # Each knowledge item becomes an individual ### entry (Q&A card in the UI).
    # Plain text only — no markdown formatting (**, [], - lists).
    lines.append("")
    lines.append("## Savoir")
    lines.append("")

    has_savoir = False

    # FAQ → individual Q&A entries (SavoirEntry format)
    faq_items = knowledge.get("faq", [])
    if isinstance(faq_items, list):
        for faq in faq_items[:15]:
            if not isinstance(faq, dict) or not faq.get("question"):
                continue
            has_savoir = True
            category = faq.get("category", "GENERAL")
            lines.append(f"### {category} : {faq['question']}")
            lines.append("")
            lines.append(str(faq.get("answer", "")))
            context = faq.get("context")
            if context:
                lines.append(f"Contexte : {context}")
            lines.append("")

    if not has_savoir:
        lines.append("_Aucun savoir enregistré._")
        lines.append("")

    # ── Règles section ──
    lines.append("## Règles")
    lines.append("")

    # General rules from analysis
    general_rules = rules.get("general_rules", [])
    contact_rules = rules.get("contact_rules", [])
    forbidden = rules.get("forbidden_phrases", [])

    if general_rules:
        for r in general_rules:
            if isinstance(r, dict):
                desc = r.get("description", r.get("name", ""))
            else:
                desc = str(r)
            lines.append(f"- {desc}")

    # Add tone rules from contact analysis
    if contact_rules:
        lines.append(f"- Adapter le ton selon le contact ({len(contact_rules)} contacts configurés)")

    # Greeting/closing style from profile
    greeting = tone.get("greeting_style")
    closing = tone.get("closing_style")
    if greeting:
        lines.append(f"- Formule d'ouverture typique : « {greeting} »")
    if closing:
        lines.append(f"- Formule de fermeture typique : « {closing} »")

    if forbidden:
        lines.append(f"- Expressions à éviter : {', '.join(forbidden)}")

    # Default rules if none found
    if not general_rules and not contact_rules and not greeting:
        lines.append("- Adapter le tutoiement/vouvoiement selon l'apprentissage du contact")
        lines.append("- Adapter le ton selon l'apprentissage")

    lines.append("")
    return "\n".join(lines)


def parse_knowledge_markdown(content: str) -> tuple[dict, dict, dict]:
    """Parse memoire.md back into (profile, knowledge, rules) dicts.

    This is the inverse of build_knowledge_markdown(). It extracts structured
    data from the markdown so it can be merged with fresh analysis results.
    """
    profile: dict = {}
    knowledge: dict = {"contacts": [], "faq": []}
    rules: dict = {"general_rules": [], "contact_rules": [], "forbidden_phrases": []}

    # Split into sections by ## headers
    sections: dict[str, str] = {}
    current_section = ""
    section_lines: list[str] = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(section_lines)
            current_section = line[3:].strip()
            section_lines = []
        else:
            section_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(section_lines)

    # ── Parse Profil ──
    profil_text = sections.get("Profil", "")
    for line in profil_text.split("\n"):
        line = line.strip()
        if line.startswith("- **Nom complet**:"):
            profile["user_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("- **Entreprise**:"):
            val = line.split(":", 1)[1].strip()
            profile.setdefault("signature", {})["company"] = val if val != "[À définir]" else None
        elif line.startswith("- **Poste**:"):
            val = line.split(":", 1)[1].strip()
            profile.setdefault("signature", {})["title"] = val if val != "[À définir]" else None
        elif line.startswith("- **Métier**:") or line.startswith("- **Metier**:"):
            profile["profession"] = line.split(":", 1)[1].strip()
        elif line.startswith("- **Ton par défaut**:"):
            ton_label = line.split(":", 1)[1].strip()
            reverse_map = {"Formel": "formal", "Semi-formel": "semi-formal", "Professionnel": "semi-formal", "Décontracté": "casual"}
            profile.setdefault("tone", {})["default_tone"] = reverse_map.get(ton_label, "semi-formal")
        elif line.startswith("- **Variante linguistique**:"):
            profile["language_variant"] = line.split(":", 1)[1].strip()

    # ── Parse Format ──
    # Round-trips the user's writing-format choice (Concise/Medium/Detailed × Simple/Standard/Sophisticated).
    # Without this, ## Format was dropped on save, then rebuilt without it, so the UI reverted to defaults.
    format_text = sections.get("Format", "")
    fmt: dict = {}
    for line in format_text.split("\n"):
        line = line.strip()
        if line.startswith("- **Longueur préférée**:") or line.startswith("- **Longueur preferee**:"):
            val = line.split(":", 1)[1].strip().lower()
            if val in ("concis", "moyen", "detaille"):
                fmt["longueur"] = val
        elif line.startswith("- **Vocabulaire**:"):
            val = line.split(":", 1)[1].strip().lower()
            if val in ("accessible", "standard", "elabore"):
                fmt["complexite"] = val
    if fmt:
        profile["writing_format"] = fmt

    # ── Parse Savoir ──
    savoir_text = sections.get("Savoir", "")
    # Split by ### subsections
    subsections = re.split(r"^### ", savoir_text, flags=re.MULTILINE)
    for sub in subsections[1:]:  # skip text before first ###
        header_line, *body_lines = sub.strip().split("\n")
        body = "\n".join(line.strip() for line in body_lines if line.strip())

        if header_line.startswith("Contact : "):
            name = header_line[len("Contact : "):]
            # Parse positional "Title — Company — Type" format. The third
            # ``Type`` segment of legacy memoire.md is dropped on the
            # floor: the sociological ``type`` field is no longer
            # extracted or consumed downstream. Positional (not
            # content-based) parsing is required because legitimate
            # titles like "Manager" or "Client" can collide with the
            # legacy label vocabulary.
            contact: dict = {"name": name}
            if body:
                parts = [s.strip() for s in body.split(" — ")]
                if len(parts) >= 1 and parts[0]:
                    contact["title"] = parts[0]
                if len(parts) >= 2 and parts[1]:
                    contact["company"] = parts[1]
                # parts[2] = legacy type — intentionally ignored.
            knowledge["contacts"].append(contact)

        elif " : " in header_line and not header_line.startswith(
            ("Projet", "Terme", "Expression")
        ):
            # FAQ Q&A block — inverse of build_knowledge_markdown's
            # "### {CATEGORY} : {question}" + answer (+ "Contexte : …"). Without
            # this, FAQ entries round-tripped to nothing, so EVERY memory save
            # (delete a savoir, edit profile, save writing format) silently
            # wiped the FAQ knowledge base via _save_to_db's wholesale
            # knowledge_json overwrite (launch audit 2026-05-30, Tier-0).
            category, question = header_line.split(" : ", 1)
            _answer_lines: list[str] = []
            _faq_context = None
            for _bl in body_lines:
                _s = _bl.strip()
                if not _s:
                    continue
                if _s.startswith("Contexte : "):
                    _faq_context = _s[len("Contexte : "):].strip()
                else:
                    _answer_lines.append(_s)
            _faq_entry: dict = {
                "category": category.strip(),
                "question": question.strip(),
                "answer": "\n".join(_answer_lines).strip(),
            }
            if _faq_context:
                _faq_entry["context"] = _faq_context
            knowledge["faq"].append(_faq_entry)

        # Legacy: skip "Projet :", "Terme" and "Expressions régionales" headers
        # from older memoire.md files — these categories are no longer extracted
        # by the onboarding pipeline and are not rehydrated on refresh.

    # ── Parse Règles ──
    regles_text = sections.get("Règles", "")
    for line in regles_text.split("\n"):
        line = line.strip()
        if not line.startswith("- "):
            continue
        rule_text = line[2:].strip()
        if rule_text.startswith("Adapter le ton selon le contact"):
            # This is a contact_rules summary — count is embedded but not individual rules
            pass
        elif rule_text.startswith("Formule d'ouverture typique"):
            m = re.search(r"[«»](.+?)[«»]", rule_text) or re.search(r": (.+)", rule_text)
            if m:
                profile.setdefault("tone", {})["greeting_style"] = m.group(1).strip().strip("« »")
        elif rule_text.startswith("Formule de fermeture typique"):
            m = re.search(r"[«»](.+?)[«»]", rule_text) or re.search(r": (.+)", rule_text)
            if m:
                profile.setdefault("tone", {})["closing_style"] = m.group(1).strip().strip("« »")
        elif rule_text.startswith("Expressions à éviter"):
            phrases_str = rule_text.split(":", 1)[1].strip() if ":" in rule_text else ""
            rules["forbidden_phrases"] = [p.strip() for p in phrases_str.split(",") if p.strip()]
        else:
            rules["general_rules"].append({"description": rule_text})

    return profile, knowledge, rules


def _merge_knowledge(existing: dict, new: dict) -> dict:
    """Merge new knowledge into existing knowledge (additive, contacts only)."""
    merged = {
        "contacts": list(existing.get("contacts", [])),
    }

    # Contacts: union by name (case-insensitive)
    existing_names = {c.get("name", "").lower() for c in merged["contacts"]}
    for c in new.get("contacts", []):
        name = c.get("name") or ""
        if not name:
            continue
        if name.lower() not in existing_names:
            merged["contacts"].append(c)
            existing_names.add(name.lower())

    return merged


def _merge_rules(existing: dict, new: dict) -> dict:
    """Merge new rules into existing rules."""
    merged = {
        "general_rules": list(existing.get("general_rules", [])),
        "contact_rules": list(existing.get("contact_rules", [])),
        "forbidden_phrases": list(existing.get("forbidden_phrases", [])),
    }

    # General rules: union by description
    existing_descs = set()
    for r in merged["general_rules"]:
        desc = r.get("description", str(r)) if isinstance(r, dict) else str(r)
        existing_descs.add(desc.lower())
    for r in new.get("general_rules", []):
        desc = r.get("description", str(r)) if isinstance(r, dict) else str(r)
        if desc.lower() not in existing_descs:
            merged["general_rules"].append(r)
            existing_descs.add(desc.lower())

    # Contact rules: new replace existing (by email)
    existing_emails = {}
    for i, r in enumerate(merged["contact_rules"]):
        email = r.get("email", "") if isinstance(r, dict) else ""
        if email:
            existing_emails[email.lower()] = i
    for r in new.get("contact_rules", []):
        email = r.get("email", "") if isinstance(r, dict) else ""
        if email and email.lower() in existing_emails:
            merged["contact_rules"][existing_emails[email.lower()]] = r
        else:
            merged["contact_rules"].append(r)

    # Forbidden phrases: union (set)
    existing_phrases = {p.lower() for p in merged["forbidden_phrases"]}
    for p in new.get("forbidden_phrases", []):
        if p.lower() not in existing_phrases:
            merged["forbidden_phrases"].append(p)
            existing_phrases.add(p.lower())

    return merged


class OnboardingManager:
    """
    Manages the full onboarding process for an account.

    Wires together the loader, indexer, orchestrator, and storage.
    Can run synchronously or in a background thread.
    """

    def __init__(
        self,
        session_factory: Callable,
        emit_event: Optional[Callable] = None,
        sync_trigger: Optional[Callable[[], bool]] = None,
    ):
        """
        Args:
            session_factory: Callable that returns a new SQLAlchemy Session.
            emit_event: Optional callable to emit WebSocket events.
                Signature: (event_name: str, data: dict) -> None
            sync_trigger: Optional callable that triggers an immediate email sync.
                Returns True if a sync was triggered, False if one was already
                running. Used to wait for the initial inbox sync before analysis.
        """
        self.session_factory = session_factory
        self.emit_event = emit_event or (lambda name, data: None)
        self.sync_trigger = sync_trigger
        self._cancelled: dict[int, bool] = {}
        # P0-010: protect _cancelled from concurrent read/write between the
        # Flask request thread (cancel/cancel_deep) and the worker thread
        # (_run_deep_refresh). Use a dedicated lock so heartbeat operations
        # are not blocked by cancellation flag access.
        self._cancel_lock = threading.Lock()
        # Per-account locks that serialise the check-and-spawn phase of
        # ``start()``. Without these, 4 concurrent POSTs to /api/onboarding/
        # start (as we've seen from the frontend polling + retry logic)
        # would all pass the "any active row?" check before any of them
        # committed a new row — spawning 4 parallel orchestrators with
        # duplicate LLM calls and racing file writes. The inner guard lock
        # protects the dict itself from its own concurrency.
        self._start_locks: dict[int, threading.Lock] = {}
        self._start_locks_guard = threading.Lock()

    def _bump_heartbeat(self, onboarding_id: int) -> None:
        """Mark this onboarding as alive — read by cleanup_stale_onboardings.

        Delegates to the module-level dict so that the watchdog (which may
        run on a different OnboardingManager instance, see _get_manager)
        observes the same state as the worker thread that bumps it.
        """
        _bump_heartbeat_global(onboarding_id)

    def _clear_heartbeat(self, onboarding_id: int) -> None:
        """Drop the heartbeat once the onboarding has reached a terminal state.

        Otherwise the dict grows unbounded across the process lifetime.
        """
        _clear_heartbeat_global(onboarding_id)

    def _active_row_has_no_live_worker(self, result_model: OnboardingResultModel) -> bool:
        """Return True when an active DB row is old enough and has no heartbeat."""
        heartbeat_age = _heartbeat_age_seconds_global(result_model.id)
        if heartbeat_age is not None:
            return False

        created_at = getattr(result_model, "created_at", None)
        if created_at is None:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        return bool(age_seconds >= ACTIVE_ONBOARDING_RETRY_GRACE_SECONDS)

    # P0-010: thread-safe helpers for the _cancelled flag dict.
    def _is_cancelled(self, account_id: int) -> bool:
        with self._cancel_lock:
            return bool(self._cancelled.get(account_id, False))

    def _set_cancelled(self, account_id: int, value: bool) -> None:
        with self._cancel_lock:
            self._cancelled[account_id] = value

    def _clear_cancelled(self, account_id: int) -> None:
        with self._cancel_lock:
            self._cancelled.pop(account_id, None)

    def _get_start_lock(self, account_id: int) -> threading.Lock:
        """Return (lazily creating) the per-account lock used by ``start()``."""
        with self._start_locks_guard:
            lock = self._start_locks.get(account_id)
            if lock is None:
                lock = threading.Lock()
                self._start_locks[account_id] = lock
            return lock

    def _populate_sent_cache(self, account_id: int, user_email: str, session) -> _SentCachePopulateResult:
        """Fetch sent emails from the provider and populate the DB sent cache.

        Called when the sent cache is empty at onboarding time so that StyleAgent
        can produce contact_rules. Without sent emails, indexed.sent_emails=[] and
        the StyleAgent LLM receives no per-contact data → contact_rules stays empty.

        Wraps the work in a SAVEPOINT (session.begin_nested()) so a provider
        failure rolls back ONLY the sent-cache inserts — the outer transaction
        keeps any prior state (result_model update, etc.) intact. The savepoint
        is committed on success so the emails are visible to the subsequent
        loader.load() query, and are flushed to disk when the outer session
        commits.

        Returns:
            Dict with keys:
              - ``stored`` (int): rows inserted across all attempts
              - ``attempted`` (bool): True if the provider was actually called
                (vs. config missing / method missing — those return attempted=False)
              - ``failed`` (bool): True if every call timed out / raised. Used
                by the caller to distinguish "user has no sent emails" from
                "we couldn't reach the sent folder right now" so the partial
                reason emitted to the UI is accurate.
              - ``via`` (str | None): "get_sent_emails", "get_sent_backfill",
                or None — which provider call ultimately stored rows.
        """
        from app.multi_accounts import get_account_manager
        from app.providers.factory import get_pooled_provider
        from app.db.models.email import Email as EmailModel
        from app.config import should_persist_email_content
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout

        result: _SentCachePopulateResult = {
            "stored": 0,
            "attempted": False,
            "failed": False,
            "via": None,
        }

        try:
            mgr = get_account_manager()
            account_config = mgr.get_account_by_email(user_email)
            if not account_config:
                logger.warning(
                    "No account config found for %s — sent cache stays empty", user_email,
                )
                return result

            provider = get_pooled_provider(account_id=account_config.id)
            if not hasattr(provider, 'get_sent_emails'):
                logger.warning(
                    "Provider has no get_sent_emails for account %d — contact rules may be empty",
                    account_id,
                )
                return result

            persist_content = should_persist_email_content()

            def _with_usage_context(fn):
                """Run ``fn()`` inside the onboarding cost-tracking context.

                The shared accountant attributes the LLM calls fired by sent
                indexing to ``feature=onboarding`` so we don't get billed-against
                inbox usage. Same pattern as the original implementation, just
                hoisted so both fetch paths reuse it.
                """
                tokens = None
                try:
                    from app.infrastructure.cost_manager import set_usage_context

                    tokens = set_usage_context(account_id=account_id, feature="onboarding")
                except Exception:
                    tokens = None
                try:
                    return fn()
                finally:
                    try:
                        from app.infrastructure.cost_manager import reset_usage_context

                        reset_usage_context(tokens)
                    except Exception:
                        pass

            def _store_batch(raw_sent: list, via: str) -> int:
                """Insert a fetched batch under a savepoint. Returns count stored."""
                if not raw_sent:
                    return 0
                stored = 0
                with session.begin_nested():
                    repo = EmailRepository(session)
                    for email_obj in raw_sent:
                        eid = str(getattr(email_obj, 'id', ''))
                        if not eid or repo.get_by_email_id(eid, account_id=account_id):
                            continue
                        cached = EmailModel(
                            email_id=eid,
                            account_id=account_id,
                            thread_id=getattr(email_obj, 'conversation_id', None),
                            subject=email_obj.subject,
                            sender=email_obj.sender,
                            sender_name=email_obj.sender_name,
                            recipients=",".join(getattr(email_obj, 'to', []) or []),
                            cc=",".join(getattr(email_obj, 'cc', []) or []),
                            date=(
                                email_obj.received_at
                                if isinstance(email_obj.received_at, datetime)
                                else datetime.now(timezone.utc)
                            ),
                            body_text=getattr(email_obj, 'body', None) if persist_content else None,
                            body_html=getattr(email_obj, 'body_html', None) if persist_content else None,
                            snippet=(getattr(email_obj, 'body', '') or '')[:200] if persist_content else None,
                            is_read=True,
                            is_sent=True,
                            folder=None,
                        )
                        session.add(cached)
                        stored += 1
                session.flush()
                if stored:
                    logger.info(
                        "Pre-onboarding sent cache (%s): stored %d/%d emails for account %d",
                        via, stored, len(raw_sent), account_id,
                    )
                return stored

            # ─── Attempt 1: get_sent_emails(limit=ONBOARDING_SENT_FETCH_LIMIT) ──

            # OB-C-7 (audit 2026-04-25): bound the fetch so a Gmail 429
            # backoff can't hold the SAVEPOINT for 60s. Two attempts with
            # a 5s pause between them — Gmail's per-method quota typically
            # recovers within a few seconds, and an empty page during a
            # rate-limit window is the failure mode this fix targets.
            raw_sent = None
            for attempt in (1, 2):
                result["attempted"] = True
                try:
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="onboarding-sent-fetch") as _ex:
                        raw_sent = _ex.submit(
                            _with_usage_context,
                            lambda: provider.get_sent_emails(limit=ONBOARDING_SENT_FETCH_LIMIT),

                        ).result(timeout=30)
                except _FuturesTimeout:
                    logger.warning(
                        "Sent-folder fetch timed out (30s, attempt %d) for account %d",
                        attempt, account_id,
                    )
                    raw_sent = None
                except Exception as e:
                    logger.warning(
                        "Sent-folder fetch raised (attempt %d) for account %d: %s",
                        attempt, account_id, e,
                    )
                    raw_sent = None

                if raw_sent:
                    break
                if attempt == 1:
                    time.sleep(5)

            if raw_sent:
                stored = _store_batch(raw_sent, "get_sent_emails")
                result["stored"] += stored
                if stored:
                    result["via"] = "get_sent_emails"

            # ─── Attempt 2: get_sent_backfill fallback ─────────────────
            # ``get_sent_emails`` is one ``messages.list`` page. When Gmail
            # rate-limits that single call we still might land rows via the
            # paginated backfill API (different quota bucket; each page is a
            # cheaper-per-message call). Only Gmail implements this today;
            # IMAP/Outlook silently skip.
            if not result["stored"] and hasattr(provider, "get_sent_backfill"):
                try:
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="onboarding-sent-backfill") as _ex:
                        raw_backfill = _ex.submit(
                            _with_usage_context,
                            lambda: provider.get_sent_backfill(limit=ONBOARDING_SENT_FETCH_LIMIT),

                        ).result(timeout=45)
                except _FuturesTimeout:
                    logger.warning(
                        "Sent backfill fallback timed out (45s) for account %d",
                        account_id,
                    )
                    raw_backfill = None
                except Exception as e:
                    logger.warning(
                        "Sent backfill fallback raised for account %d: %s",
                        account_id, e,
                    )
                    raw_backfill = None

                if raw_backfill:
                    stored = _store_batch(raw_backfill, "get_sent_backfill")
                    result["stored"] += stored
                    if stored:
                        result["via"] = "get_sent_backfill"

            # Mark failure only when all attempts ran AND none stored anything.
            # Without this, the caller can't distinguish "user has no sent
            # emails" from "provider transient failure" — the wizard error
            # messages differ between the two cases.
            if result["attempted"] and result["stored"] == 0:
                result["failed"] = True
                logger.warning(
                    "Sent cache fetch produced 0 rows for account %d (%s) — "
                    "treating as transient failure so the wizard can retry",
                    account_id, user_email,
                )

            return result
        except Exception as e:
            logger.warning(
                "Failed to populate sent cache before onboarding (non-fatal): %s", e,
            )
            result["failed"] = True
            return result
            # The savepoint (begin_nested) auto-rolls back on exception within
            # its `with` block; no need to rollback the outer session.

    def _fetch_provider_folders(self, account_id: int):
        """Fetch folders from the email provider for label suggestions."""
        try:
            from app.api import routes_helpers as _rh
            from app.providers.factory import get_pooled_provider
            from app.onboarding.agents.label_agent import FolderInfo
            oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
            if not oauth_account_id:
                return None
            provider = get_pooled_provider(account_id=oauth_account_id)
            if hasattr(provider, 'list_folders'):
                raw_folders = provider.list_folders()
                return [
                    FolderInfo(
                        name=f.name,
                        display_name=f.display_name,
                        type=f.type,
                        total_count=f.total_count,
                    )
                    for f in raw_folders
                ]
        except Exception as e:
            logger.warning("Failed to fetch provider folders for category suggestions: %s", e)
        return None

    def start(
        self,
        account_id: int,
        user_email: str,
        since_days: Optional[int] = None,
        max_emails: Optional[int] = None,
        faq_entries: Optional[list[dict]] = None,
    ) -> dict:
        """
        Start the onboarding process in a background thread.

        Args:
            account_id: The account to analyse.
            user_email: The user's email address.
            since_days: If provided, only analyse emails received in the last N
                days (cuts LLM cost and avoids tugging on the full corpus).
            max_emails: Hard cap on the number of emails fed to the analysis
                pipeline. ``None`` means "use the loader's default" (5000).
            faq_entries: Optional list of FAQ Q&A pairs from the pre-scan step
                (website or document). Format: [{"question": "...", "answer": "..."}].
                When provided, KnowledgeAgent skips email-based FAQ guessing
                and these entries are injected directly into the knowledge result.

        Returns:
            Dict with status and onboarding_id. When a concurrent call
            finds an already-active run, ``already_running: True`` is set
            and the existing onboarding_id is returned — no new row, no
            new thread, no duplicate LLM work.
        """
        # Serialise the entire check-and-spawn sequence per account. Inside
        # the lock we: (1) look for an already-active row, (2) if none,
        # create the row + spawn the worker thread. This is the dedupe
        # guarantee that prevents 4× parallel orchestrators when the
        # frontend fires multiple rapid POSTs to /api/onboarding/start.
        with self._get_start_lock(account_id):
            session = self.session_factory()
            try:
                repo = OnboardingRepository(session)
                active = repo.find_active(account_id)
                if active is not None:
                    if not self._active_row_has_no_live_worker(active):
                        current_count = self._count_account_emails(account_id)
                        logger.info(
                            "Onboarding already active for account=%d (id=%d, status=%s) "
                            "— returning existing instead of spawning a new run",
                            account_id, active.id, active.status,
                        )
                        return {
                            "status": active.status,
                            "onboarding_id": active.id,
                            "account_id": account_id,
                            "current_email_count": current_count,
                            "min_emails_required": MIN_EMAILS_FOR_ANALYSIS,
                            "already_running": True,
                        }

                    old_id = active.id
                    old_status = active.status
                    logger.warning(
                        "Onboarding active row has no live worker for account=%d "
                        "(id=%d, status=%s) — marking failed so retry can spawn a new run",
                        account_id, old_id, old_status,
                    )
                    active.status = "failed"
                    active.error_message = (
                        "Onboarding interrompu pendant la synchronisation. "
                        "Relancez l'analyse depuis l'écran d'entraînement."
                    )
                    session.commit()
                    self._clear_heartbeat(old_id)
                    logger.info(
                        "Onboarding retry replacing orphaned active row for account=%d "
                        "(old_id=%d)",
                        account_id, old_id,
                    )

                # No active run — create a pending result row.
                result_model = OnboardingResultModel(
                    account_id=account_id,
                    status="pending",
                )
                repo.create(result_model)
                session.commit()
                onboarding_id = result_model.id
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

            # Decide whether to wait for sync or run analysis immediately.
            # If the inbox already has enough emails, skip the wait.
            current_count = self._count_account_emails(account_id)
            needs_sync_wait = current_count < MIN_EMAILS_FOR_ANALYSIS

            if needs_sync_wait:
                target = threading.Thread(
                    target=self._run_with_usage_context,
                    args=(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries),
                    kwargs={"fn": self._wait_for_sync_then_run},
                    daemon=True,
                )
            else:
                target = threading.Thread(
                    target=self._run_with_usage_context,
                    args=(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries),
                    kwargs={"fn": self._run_analysis},
                    daemon=True,
                )
            # P1-NEW-003: bump heartbeat BEFORE thread.start() so the watchdog
            # never sees an unheartbeated active row during the startup window.
            # If the thread crashes before its own first bump, the watchdog will
            # eventually mark the row stale — but it won't create a false zombie
            # immediately since the heartbeat is already present.
            _bump_heartbeat_global(onboarding_id)
            target.start()

        # Emit learning_started OUTSIDE the lock (it's a network fan-out —
        # we don't want WS emission to block the next caller waiting on
        # the lock, especially since the frontend reconnect handler may
        # itself re-trigger /start).
        self._emit("onboarding:learning_started", {
            "account_id": account_id,
            "onboarding_id": onboarding_id,
            "total_emails": current_count,
            "waiting_for_sync": needs_sync_wait,
        })

        return {
            "status": "waiting_for_sync" if needs_sync_wait else "started",
            "onboarding_id": onboarding_id,
            "account_id": account_id,
            "current_email_count": current_count,
            "min_emails_required": MIN_EMAILS_FOR_ANALYSIS,
            "already_running": False,
        }

    def _resolve_usage_user_id(self, account_id: int) -> Optional[int]:
        try:
            from app.db.repositories.account_repository import AccountRepository

            session = self.session_factory()
            try:
                account = AccountRepository(session).get(account_id)
                raw_user_id = getattr(account, "user_id", None) if account else None
                return int(raw_user_id) if raw_user_id is not None else None
            finally:
                session.close()
        except Exception:
            return None

    def _run_with_usage_context(
        self,
        onboarding_id: int,
        account_id: int,
        user_email: str,
        since_days: Optional[int],
        max_emails: Optional[int],
        faq_entries: Optional[list[dict]],
        *,
        fn,
    ) -> None:
        tokens = None
        try:
            from app.infrastructure.cost_manager import set_usage_context

            tokens = set_usage_context(
                account_id=account_id,
                user_id=self._resolve_usage_user_id(account_id),
                feature="onboarding",
            )
        except Exception:
            tokens = None
        try:
            fn(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries)
        finally:
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(tokens)
            except Exception:
                pass

    def _run_refresh_with_usage_context(
        self,
        account_id: int,
        user_email: str,
        days: int | None,
        *,
        feature: str,
        fn,
        include_days: bool = True,
    ) -> None:
        tokens = None
        try:
            from app.infrastructure.cost_manager import set_usage_context

            tokens = set_usage_context(
                account_id=account_id,
                user_id=self._resolve_usage_user_id(account_id),
                feature=feature,
            )
        except Exception:
            tokens = None
        try:
            if include_days:
                fn(account_id, user_email, days)
            else:
                fn(account_id, user_email)
        finally:
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(tokens)
            except Exception:
                pass

    def _count_account_emails(self, account_id: int) -> int:
        """Return the number of emails currently in the DB for this account."""
        session = self.session_factory()
        try:
            email_repo = EmailRepository(session)
            return email_repo.count_by_account(account_id)
        finally:
            session.close()

    def _wait_for_sync_then_run(
        self,
        onboarding_id: int,
        account_id: int,
        user_email: str,
        since_days: Optional[int] = None,
        max_emails: Optional[int] = None,
        faq_entries: Optional[list[dict]] = None,
    ):
        """
        Wait for the initial email sync to populate the inbox, then run analysis.

        Triggers an immediate sync, polls the email count, and emits progress
        events so the UI can display "Synchronisation en cours...".
        Times out after SYNC_WAIT_TIMEOUT_SECONDS.
        """
        import time as _time

        # Mark as waiting in DB so /status reflects the right state
        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result_model = repo.get(onboarding_id)
            if result_model:
                result_model.status = "waiting_for_sync"
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        # First heartbeat — signals to cleanup_stale_onboardings that the
        # thread is alive. Without it, a row created just before the watchdog
        # tick could be marked failed during its grace window if the wait
        # loop hasn't yet reached its first iteration.
        self._bump_heartbeat(onboarding_id)

        # Kick off an immediate sync. Best-effort: trigger_sync() returns False
        # if a sync cycle is ALREADY running, in which case that in-flight sync
        # took its accounts snapshot before this fresh OAuth completed and will
        # therefore skip the new account entirely. We compensate by retrying
        # the trigger every SYNC_RETRIGGER_INTERVAL_SECONDS while we wait, so
        # eventually a fresh sync (whose snapshot includes the new account)
        # runs. Without this, an unlucky timing collision between oauth/complete
        # and the periodic 120s sync loop produced exactly the symptom we hit
        # in incognito: count_account_emails stays at 0 for the full 5 minutes,
        # then the user sees the misleading "no emails synced" error.
        SYNC_RETRIGGER_INTERVAL_SECONDS = 30
        last_trigger_at = 0.0
        sync_trigger_errors: list[str] = []

        def _maybe_retrigger_sync() -> None:
            nonlocal last_trigger_at
            if not self.sync_trigger:
                return
            now = _time.monotonic()
            if now - last_trigger_at < SYNC_RETRIGGER_INTERVAL_SECONDS:
                return
            last_trigger_at = now
            try:
                self.sync_trigger()
            except Exception as e:
                sync_trigger_errors.append(str(e))
                logger.warning("Failed to trigger sync from onboarding wait: %s", e)

        _maybe_retrigger_sync()

        start_time = _time.monotonic()
        deadline = start_time + SYNC_WAIT_TIMEOUT_SECONDS
        last_emitted_count = -1
        last_known_count = 0
        # Track the wall-clock instant at which `current_count` last increased.
        # Used by the stale-detection short-circuit below so we can unblock
        # onboarding when Gmail rate-limits the sync (count stops moving).
        # Initialized to start_time so a count that never increases still has
        # a meaningful elapsed-stale value from the first iteration.
        last_change_at = start_time

        while _time.monotonic() < deadline:
            try:
                current_count = self._count_account_emails(account_id)
                if current_count > last_known_count:
                    last_change_at = _time.monotonic()
                last_known_count = current_count
            except Exception as e:  # noqa: BLE001
                # DB transient error : ne PAS figer le row en waiting_for_sync
                # à vie. On réutilise le dernier count connu et on continue
                # la boucle (le prochain tick retentera la query). Sans ça,
                # le thread crashe silencieusement → seul recover_orphaned_waiting
                # au prochain reboot backend rattrape.
                logger.warning(
                    "count_account_emails DB error (account=%d): %s — reusing last_known=%d",
                    account_id, e, last_known_count,
                )
                current_count = last_known_count

            # Only emit when count changes — avoids WS spam
            if current_count != last_emitted_count:
                self._emit("onboarding:waiting_for_sync", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "current": current_count,
                    "target": MIN_EMAILS_FOR_ANALYSIS,
                    "phase": f"Synchronisation de votre boîte mail ({current_count} emails reçus)...",
                })
                last_emitted_count = current_count

            if current_count >= MIN_EMAILS_FOR_ANALYSIS:
                logger.info(
                    "Sync wait completed for account %d: %d emails ready (threshold=%d)",
                    account_id, current_count, MIN_EMAILS_FOR_ANALYSIS,
                )
                self._run_analysis(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries)
                return

            now_elapsed = _time.monotonic() - start_time

            # Fast-start : après FAST_START_AFTER_SECONDS, si on a au moins
            # MIN_EMAILS_FOR_FAST_START emails, on lance l'analyse plutôt que
            # d'attendre plus longtemps. Sent-cache fetch run independently
            # inside _run_analysis gives us hundreds of sent emails to analyse
            # regardless of inbox depth.
            if now_elapsed >= FAST_START_AFTER_SECONDS and current_count >= MIN_EMAILS_FOR_FAST_START:
                logger.info(
                    "Sync wait fast-start for account %d: %d emails after %.0fs (fast_threshold=%d)",
                    account_id, current_count, now_elapsed, MIN_EMAILS_FOR_FAST_START,
                )
                self._run_analysis(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries)
                return

            # Stale-count short-circuit : if we have at least one email AND
            # the count has not increased for SYNC_STALE_THRESHOLD_SECONDS, the
            # sync is almost certainly throttled (Gmail 429 with no Retry-After
            # cascades to a 60s provider backoff). Don't make the user wait
            # for the hard timeout — _run_analysis's sent-cache path can
            # proceed with whatever inbox context is currently available.
            stale_duration = _time.monotonic() - last_change_at
            if current_count > 0 and stale_duration >= SYNC_STALE_THRESHOLD_SECONDS:
                logger.info(
                    "Sync wait stale short-circuit for account %d: count=%d stuck for %.0fs "
                    "(likely provider rate-limit) — proceeding with partial inbox",
                    account_id, current_count, stale_duration,
                )
                self._run_analysis(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries)
                return

            # Heartbeat *before* the sleep so cleanup_stale_onboardings sees
            # an up-to-date timestamp even during the idle phase between polls.
            self._bump_heartbeat(onboarding_id)

            _time.sleep(SYNC_WAIT_POLL_INTERVAL_SECONDS)
            # Retrigger sync periodically — covers the "new account joined
            # mid-cycle" race where the first trigger no-op'd because the
            # already-running sync had a stale account snapshot.
            _maybe_retrigger_sync()

        # Timed out
        final_count = self._count_account_emails(account_id)
        logger.warning(
            "Sync wait timed out for account %d after %ds (final count=%d)",
            account_id, SYNC_WAIT_TIMEOUT_SECONDS, final_count,
        )

        if final_count > 0:
            # Some emails arrived but below threshold — run analysis anyway
            logger.info("Running analysis on partial inbox (%d emails)", final_count)
            self._run_analysis(onboarding_id, account_id, user_email, since_days, max_emails, faq_entries)
            return

        # Truly empty mailbox or sync failure — try to surface the actual root
        # cause from the sync_service's last results (auth failure, rate limit,
        # provider error…) instead of the generic "no emails synced" wall that
        # leaves the user with no actionable info.
        sync_error_detail = self._extract_sync_error_for(account_id)
        if sync_error_detail:
            user_message = (
                f"Échec de la synchronisation : {sync_error_detail}. "
                "Vérifiez votre connexion ou reconnectez votre compte email."
            )
        elif sync_trigger_errors:
            user_message = (
                f"Le service de synchronisation est injoignable ({sync_trigger_errors[-1]}). "
                "Réessayez dans quelques instants."
            )
        else:
            user_message = (
                "Aucun email synchronisé après 5 minutes. "
                "Vérifiez que votre compte est bien connecté ou que votre boîte n'est pas vide."
            )

        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result_model = repo.get(onboarding_id)
            if result_model:
                result_model.status = "failed"
                result_model.error_message = user_message
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
            # This path does not enter _run_analysis(), so its finally block
            # cannot clean the heartbeat. Without this, /start retries can see
            # a stale waiting_for_sync row as active even after the worker ended.
            self._clear_heartbeat(onboarding_id)
            # P1-006: clean up the _cancelled flag on the timeout/failure path —
            # _run_analysis is NOT called from here, so its finally won't do it.
            self._clear_cancelled(account_id)

        self._emit("onboarding:learning_completed", {
            "account_id": account_id,
            "status": "failed",
            "error": user_message,
        })

    def _extract_sync_error_for(self, account_id: int) -> Optional[str]:
        """Best-effort lookup of the last sync result for this account.

        Returns a short human-readable error string, or None if the sync
        service isn't reachable / has no result for this account yet.

        OB-H-1 (audit 2026-04-25 onboarding-flawless): when the account
        is in auth backoff (≥ 3 failures via M-2 fix), short-circuit with
        a dedicated "reconnect your account" message so the user knows
        the issue is credentials, not network. Without this signal users
        wait the full 120s timeout and then get a generic message.

        Strictly defensive — the sync_service module shape may evolve and
        a missing attribute here must never crash the onboarding thread.
        """
        try:
            from app.services.sync_service import get_sync_service, _is_missing_oauth_scope_error_message
            svc = get_sync_service()
            if not svc:
                return None
            # Auth-backoff signal wins over the last_results message.
            try:
                reauth_ids = svc.get_reauth_required_accounts(threshold=3)
                if account_id in (reauth_ids or []):
                    return (
                        "Reconnexion requise — votre compte a échoué l'authentification "
                        "plusieurs fois. Reconnectez-le depuis les Réglages."
                    )
            except Exception:
                pass
            status = getattr(svc, "_status", None)
            results = getattr(status, "last_results", None) or []
            for r in results:
                if getattr(r, "account_id", None) == account_id and not getattr(r, "success", True):
                    error_message = (getattr(r, "error_message", None) or "").strip()
                    if _is_missing_oauth_scope_error_message(error_message):
                        return (
                            "Autorisations Gmail incomplètes — reconnectez Gmail "
                            "et acceptez toutes les autorisations demandées."
                        )
                    return error_message or None
            return None
        except Exception:
            return None

    def get_status(self, account_id: int) -> Optional[dict]:
        """
        Get the current onboarding status for an account.

        Args:
            account_id: The account to check.

        Returns:
            Status dict or None if no onboarding exists.
        """
        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result = repo.get_by_account(account_id)
            if result:
                return result.to_dict()
            return None
        finally:
            session.close()

    def recover_orphaned_waiting(self) -> int:
        """Marque comme failed les onboardings orphelins après un crash/restart.

        Le thread _wait_for_sync_then_run vit uniquement en mémoire. Si le
        backend crash/restart pendant qu'il attend la sync, la ligne DB reste
        coincée en 'waiting_for_sync' ou 'running' indéfiniment — le front
        affiche 'En attente...' sans fin.

        À appeler au démarrage (run_api.py après sync_service.start()) pour
        nettoyer les lignes orphelines. Le frontend (ou l'utilisateur) peut
        ensuite relancer POST /onboarding/start proprement.

        Returns:
            Nombre d'onboardings marqués comme failed.
        """
        from sqlalchemy import or_ as _or
        from app.db.models.onboarding_result import OnboardingResult

        session = self.session_factory()
        count = 0
        try:
            orphans = session.query(OnboardingResult).filter(
                _or(
                    OnboardingResult.status == "waiting_for_sync",
                    OnboardingResult.status == "running",
                )
            ).all()
            for row in orphans:
                row.status = "failed"
                row.error_message = (
                    "Onboarding interrompu par un redémarrage du serveur. "
                    "Relancez l'analyse depuis l'écran d'entraînement."
                )
                count += 1
            if count:
                session.commit()
                logger.warning(
                    "Onboarding recovery: marked %d orphaned row(s) as failed",
                    count,
                )
        except Exception as e:
            session.rollback()
            logger.error("Onboarding recovery failed: %s", e, exc_info=True)
        finally:
            session.close()
        return count

    def cleanup_stale_onboardings(
        self,
        stale_seconds: float = 600.0,
        grace_seconds: float = 60.0,
    ) -> list[int]:
        """Watchdog : flip stuck onboarding rows to ``failed``.

        Rationale: ``recover_orphaned_waiting`` is one-shot at boot. While the
        process is running, a thread crash (e.g. ``database is locked`` mid-
        commit) leaves the row pinned to ``waiting_for_sync`` / ``running``
        with a dead worker that nobody will revive. The frontend keeps polling
        ``/status`` and shows "Initialising..." forever.

        We use the in-memory heartbeat dict that ``_wait_for_sync_then_run``
        and ``_run_analysis`` bump at every step (and that ``_emit`` bumps on
        every WS progress event). Two failure modes are caught:

        1. **No heartbeat at all** + row created more than ``grace_seconds``
           ago → the worker thread either never ran or died before its first
           bump (this is the exact pattern of the original incident).
        2. **Heartbeat older than ``stale_seconds``** → the worker is stuck in
           a long blocking call (Anthropic SDK hung, IMAP frozen, …). We
           prefer a false-positive failure that the user can retry over a
           silent forever-spinner.

        ``stale_seconds=600`` (10 min) is well above any legitimate single
        step in the pipeline. ``grace_seconds=60`` lets a freshly-created row
        survive the brief gap between INSERT and the worker's first heartbeat.

        Returns the list of onboarding ids that were flipped — useful for
        tests and for emitting ``onboarding:learning_completed`` so the
        frontend transitions out of the spinner immediately.
        """
        from app.db.models.onboarding_result import OnboardingResult

        now_mono = time.monotonic()
        flipped: list[tuple[int, int]] = []
        session = self.session_factory()
        try:
            stuck_rows = session.query(OnboardingResult).filter(
                OnboardingResult.status.in_(("waiting_for_sync", "running"))
            ).all()
            if not stuck_rows:
                return []

            # Snapshot heartbeats under lock — releases before DB writes.
            heartbeats = _snapshot_heartbeats_global()

            for row in stuck_rows:
                hb = heartbeats.get(row.id)
                created_at = row.created_at
                if created_at is None:
                    # Defensive: a row without created_at can't be aged out
                    # safely. Skip it — recover_orphaned_waiting at next boot
                    # will catch it if it's truly orphaned.
                    continue
                # SQLite returns created_at as a naive datetime in UTC. Treat
                # it as UTC explicitly so the subtraction with the aware
                # ``now`` does not raise.
                created_at_utc = (
                    created_at if created_at.tzinfo is not None
                    else created_at.replace(tzinfo=timezone.utc)
                )
                age_seconds = (datetime.now(timezone.utc) - created_at_utc).total_seconds()

                is_stale = False
                reason = ""
                if hb is None:
                    if age_seconds > grace_seconds:
                        is_stale = True
                        reason = (
                            f"no heartbeat after {age_seconds:.0f}s "
                            f"(grace={grace_seconds:.0f}s) — worker thread dead"
                        )
                else:
                    elapsed = now_mono - hb
                    if elapsed > stale_seconds:
                        is_stale = True
                        reason = (
                            f"last heartbeat {elapsed:.0f}s ago "
                            f"(threshold={stale_seconds:.0f}s) — worker stuck"
                        )

                if is_stale:
                    row.status = "failed"
                    row.error_message = (
                        "L'analyse semble bloquée. Le serveur a interrompu "
                        "automatiquement le processus pour vous permettre de "
                        "le relancer depuis l'écran d'entraînement."
                    )
                    flipped.append((row.id, row.account_id))
                    logger.warning(
                        "Onboarding watchdog: flipping id=%d account=%d to failed (%s)",
                        row.id, row.account_id, reason,
                    )

            if flipped:
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error("cleanup_stale_onboardings failed: %s", e, exc_info=True)
            return []
        finally:
            session.close()

        # Notify clients OUTSIDE the DB session — emission is best-effort and
        # we never want a dropped WS to roll back the DB state. Also clears
        # the now-meaningless heartbeats.
        for onboarding_id, account_id in flipped:
            self._clear_heartbeat(onboarding_id)
            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "onboarding_id": onboarding_id,
                "status": "failed",
                "error": "L'analyse semble bloquée — vous pouvez la relancer.",
            })

        return [oid for oid, _ in flipped]

    def get_insights(self, account_id: int) -> Optional[dict]:
        """
        Get the generated insights for an account.

        Args:
            account_id: The account to check.

        Returns:
            Insights dict or None if not completed.
        """
        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result = repo.get_completed_by_account(account_id)
            if not result:
                return None

            insights = result.to_dict()
            if result.profile_json:
                insights["profile"] = _flatten_profile_styles(
                    json.loads(result.profile_json)
                )
            if result.knowledge_json:
                insights["knowledge"] = json.loads(result.knowledge_json)
            if result.rules_json:
                insights["rules"] = json.loads(result.rules_json)
            if result.categories_json:
                insights["categories"] = json.loads(result.categories_json)

            return insights
        finally:
            session.close()

    def confirm_profession(self, account_id: int, profession: str) -> dict:
        """Persist the user-confirmed profession on the latest completed run."""
        cleaned = " ".join(str(profession or "").strip().split())[:120]
        if not cleaned:
            raise ValueError("profession is required")

        def _loads_object(raw: str | None) -> dict:
            if not raw:
                return {}
            try:
                value = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result = repo.get_completed_by_account(account_id)
            if not result:
                raise ValueError(f"No completed onboarding found for account_id={account_id}")

            profile = _loads_object(result.profile_json)
            knowledge = _loads_object(result.knowledge_json)
            rules = _loads_object(result.rules_json)

            profile["profession"] = cleaned
            profile["profession_confirmed"] = True
            result.profile_json = json.dumps(profile, ensure_ascii=False)
            session.commit()

            self._apply_to_knowledge_base(
                profile,
                knowledge,
                rules,
                account_id=account_id,
                email_count=result.emails_analysed,
            )

            from app._prompts_monolith import invalidate_kb_db_cache
            invalidate_kb_db_cache(account_id)

            return {
                "profession": cleaned,
                "profession_confirmed": True,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # OB-05 (audit 2026-04-24): hard caps for deep-training cost. Without
    # these, a 50K-email account triggers 100 batches × 3 Opus agents ≈
    # 300 Opus calls (~$30-60) with no user-visible estimate. We cap at
    # ``DEEP_TRAINING_MAX_EMAILS`` by default; the user can opt into a
    # higher cap by passing ``confirm_estimate_usd >= estimate``.
    DEEP_TRAINING_MAX_EMAILS_DEFAULT = 5000  # ~10 batches × 3 = 30 Opus calls
    DEEP_TRAINING_HARD_CEILING = 50000        # absolute hard limit
    # Conservative per-batch (500 emails × 3 Opus agents) cost in USD.
    # Opus 4 input ~$15/M, output ~$75/M; per-batch ~ 25K in + 4K out
    # ≈ $0.65 per agent × 3 agents = ~$1.95/batch. Round to $2.
    DEEP_TRAINING_USD_PER_BATCH = 2.0
    DEEP_TRAINING_BATCH_SIZE = 500
    DEEP_TRAINING_DEFAULT_BUDGET_USD = 5.0

    def estimate_deep_training_cost(self, account_id: int) -> dict:
        """Pre-flight estimate for the deep-training cost.

        Returns a dict with:
        - ``email_count``: emails currently synced for this account
        - ``batch_count``: number of 500-email batches that would run
        - ``estimated_usd``: rough Opus cost (input+output, 3 agents/batch)
        - ``hard_cap_usd``: budget above which the job will refuse to start
        - ``hard_cap_emails``: enforced email cap (returns this many at
          most, even if more exist)
        - ``would_exceed_default_cap``: True iff the user must confirm

        The numbers are intentionally conservative — a $5 budget is a
        sensible default that covers ~5K emails. If a user wants the
        full corpus they pass ``confirm_estimate_usd >= estimated_usd``
        when calling refresh().
        """
        try:
            email_count = self._count_account_emails(account_id)
        except Exception as e:
            logger.warning("estimate_deep_training_cost: count failed: %s", e)
            email_count = 0

        capped = min(email_count, self.DEEP_TRAINING_HARD_CEILING)
        batch_count = (capped + self.DEEP_TRAINING_BATCH_SIZE - 1) // self.DEEP_TRAINING_BATCH_SIZE
        estimated_usd = round(batch_count * self.DEEP_TRAINING_USD_PER_BATCH, 2)
        would_exceed = email_count > self.DEEP_TRAINING_MAX_EMAILS_DEFAULT
        return {
            "email_count": int(email_count),
            "batch_count": int(batch_count),
            "estimated_usd": estimated_usd,
            "hard_cap_emails": int(self.DEEP_TRAINING_HARD_CEILING),
            "default_cap_emails": int(self.DEEP_TRAINING_MAX_EMAILS_DEFAULT),
            "default_budget_usd": float(self.DEEP_TRAINING_DEFAULT_BUDGET_USD),
            "would_exceed_default_cap": bool(would_exceed),
        }

    def refresh(
        self,
        account_id: int,
        user_email: str,
        days: int | None = 7,
        mode: str = "incremental",
        confirm_estimate_usd: float | None = None,
    ) -> dict:
        """Start a refresh in a background thread.

        Only runs Knowledge + Rules agents on recent emails, then merges
        the results into the existing memoire.md without overwriting.

        Args:
            days: Number of days to look back, or None for full corpus.
            mode: "incremental" (default) or "deep" (all emails, Opus model, batched).
            confirm_estimate_usd: For ``mode="deep"``, the user-confirmed
                budget. If the estimated cost exceeds this value, the call
                is rejected (status="cost_exceeded"). Required for runs
                above ``DEEP_TRAINING_MAX_EMAILS_DEFAULT``. If ``None`` we
                auto-confirm runs that fit within the default budget.
        """
        is_deep = mode == "deep"

        # OB-05: pre-flight cost gate for deep training.
        if is_deep:
            estimate = self.estimate_deep_training_cost(account_id)
            # If the run is over the soft cap and the user hasn't given an
            # explicit budget, refuse — caller must show a confirmation
            # modal and re-call with ``confirm_estimate_usd``.
            if estimate["would_exceed_default_cap"]:
                if confirm_estimate_usd is None:
                    return {
                        "status": "needs_confirmation",
                        "account_id": account_id,
                        "estimate": estimate,
                        "message": (
                            "Deep training on this corpus is estimated at "
                            f"${estimate['estimated_usd']} — "
                            "user confirmation required."
                        ),
                    }
                if confirm_estimate_usd < estimate["estimated_usd"]:
                    return {
                        "status": "cost_exceeded",
                        "account_id": account_id,
                        "estimate": estimate,
                        "message": (
                            f"Confirmed budget ${confirm_estimate_usd} below "
                            f"estimated ${estimate['estimated_usd']}."
                        ),
                    }
            # Even within default cap, log the estimate for observability.
            logger.info(
                "Deep training pre-flight: account=%d emails=%d batches=%d est=$%.2f",
                account_id, estimate["email_count"],
                estimate["batch_count"], estimate["estimated_usd"],
            )

        if is_deep:
            thread = threading.Thread(
                target=self._run_refresh_with_usage_context,
                args=(account_id, user_email, None),
                kwargs={
                    "feature": "learning_refresh_deep",
                    "fn": self._run_deep_refresh,
                    "include_days": False,
                },
                daemon=True,
            )
        else:
            refresh_feature = (
                "learning_refresh_full" if days is None else "learning_refresh"
            )
            thread = threading.Thread(
                target=self._run_refresh_with_usage_context,
                args=(account_id, user_email, days),
                kwargs={
                    "feature": refresh_feature,
                    "fn": self._run_refresh,
                },
                daemon=True,
            )
        thread.start()

        self._emit("onboarding:learning_started", {
            "account_id": account_id,
            "total_emails": 0,
            "refresh": True,
            "deep": is_deep,
        })

        return {
            "status": "started",
            "account_id": account_id,
            "refresh": True,
            "deep": is_deep,
            "days": days if not is_deep else None,
            "estimate": self.estimate_deep_training_cost(account_id) if is_deep else None,
        }

    def cancel_deep(self, account_id: int):
        """Signal cancellation for a running deep training."""
        self._set_cancelled(account_id, True)

    def cancel(self, account_id: int) -> dict:
        """OB-01: cancel any running onboarding session for an account.

        Marks the in-memory cancellation flag (consumed by
        _run_deep_refresh between batches) AND patches the active DB row
        to ``cancelled`` so the user-facing /status endpoint reflects the
        change immediately, even if the LLM call is mid-flight and
        cannot be physically interrupted.

        We don't try to actually kill the in-flight ``_run_analysis``
        thread (Anthropic's SDK doesn't expose cancellable futures here)
        — but we do guarantee that:
          1. the user sees the run as ``cancelled`` immediately
          2. the next batch of deep-training will short-circuit
          3. any subsequent /status poll returns ``cancelled``, so the
             frontend can transition the user back to the welcome state.
        """
        self._set_cancelled(account_id, True)
        cancelled_count = 0

        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            active = repo.find_active(account_id)
            if active is not None:
                active.status = "cancelled"
                active.error_message = (
                    "Onboarding annulé par l'utilisateur. "
                    "Vous pouvez relancer l'analyse depuis l'écran d'entraînement."
                )
                session.commit()
                cancelled_count = 1
                # Drop the watchdog heartbeat so it does not keep the dead
                # entry alive in memory.
                self._clear_heartbeat(active.id)
                # Notify the frontend immediately so it can transition the
                # UI without waiting for the (possibly stuck) worker thread
                # to emit on its own.
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "onboarding_id": active.id,
                    "status": "cancelled",
                    "error": "Onboarding annulé par l'utilisateur.",
                })
        except Exception as e:
            session.rollback()
            logger.warning(
                "OB-01 cancel: DB rollback for account=%d (%s)", account_id, e,
            )
        finally:
            session.close()

        return {
            "status": "cancelling",
            "account_id": account_id,
            "active_rows_marked_cancelled": cancelled_count,
        }

    def _create_opus_llm(self):
        """Create an LLM adapter configured for Opus."""
        from app.infrastructure.container import get_container
        container = get_container()
        if container.config.llm_provider == "claude-code":
            from app.adapters.llm.claude_code_adapter import ClaudeCodeAdapter
            return ClaudeCodeAdapter(model="opus")
        elif container.config.llm_provider == "ollama":
            return container.llm
        else:
            from app.config import CLAUDE_MODEL_OPUS
            from app.adapters.llm.claude_adapter import ClaudeAdapter
            return ClaudeAdapter(
                model=CLAUDE_MODEL_OPUS,
                api_key=container.config.anthropic_api_key or "",
            )

    def _run_deep_refresh(self, account_id: int, user_email: str):
        """Run deep training: emails (capped at hard ceiling), batched by 500, Opus.

        OB-05: cap loader at ``DEEP_TRAINING_HARD_CEILING`` emails. The
        previous unbounded ``limit=50000`` could yield 100+ batches × 3
        Opus calls = $30-60 per run with no user-visible pre-flight.
        ``refresh()`` already gates this with cost confirmation; the cap
        here is defense in depth.
        """
        self._set_cancelled(account_id, False)

        try:
            # Load up to the hard ceiling. ``refresh()`` requires user
            # confirmation when the count exceeds the soft cap, but we
            # re-enforce here so a direct call into _run_deep_refresh
            # (e.g. tests, scripts) cannot skip the bound.
            session = self.session_factory()
            try:
                email_repo = EmailRepository(session)
                loader = RepositoryLoader(email_repo, account_id, user_email)
                emails, metadata = loader.load(
                    limit=self.DEEP_TRAINING_HARD_CEILING,
                    since_date=None,
                )
            finally:
                session.close()

            if not emails:
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "status": "completed",
                    "refresh": True,
                    "deep": True,
                    "new_contacts": 0, "new_rules": 0,
                })
                return

            total_emails = len(emails)
            batch_size = 500
            batches = [emails[i:i + batch_size] for i in range(0, total_emails, batch_size)]
            batch_total = len(batches)

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": 0,
                "total": total_emails,
                "confidence": 2,
                "phase": f"Entraînement approfondi : {total_emails} emails en {batch_total} lots",
                "phase_key": "scan_phase_deep_intro",
                "phase_params": {"emails": total_emails, "batches": batch_total},
                "deep": True,
                "batch_current": 0,
                "batch_total": batch_total,
                "refresh": True,
            })

            opus_llm = self._create_opus_llm()
            indexer = EmailIndexer(user_email, account_id=account_id)
            accumulated_counts = {"new_contacts": 0, "new_rules": 0}

            for batch_idx, batch_emails in enumerate(batches):
                # Check cancellation
                if self._is_cancelled(account_id):
                    self._emit("onboarding:learning_completed", {
                        "account_id": account_id,
                        "status": "cancelled",
                        "refresh": True,
                        "deep": True,
                        "emails_analysed": batch_idx * batch_size,
                        "batch_completed": batch_idx,
                        "batch_total": batch_total,
                        **accumulated_counts,
                    })
                    return

                batch_num = batch_idx + 1
                emails_so_far = batch_idx * batch_size

                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "emails_processed": emails_so_far,
                    "total": total_emails,
                    "confidence": int(5 + (batch_idx / batch_total) * 85),
                    "phase": f"Lot {batch_num}/{batch_total} — Extraction des connaissances...",
                    "phase_key": "scan_phase_batch_knowledge",
                    "phase_params": {"current": batch_num, "total": batch_total},
                    "step": "knowledge",
                    "step_status": "running",
                    "deep": True,
                    "batch_current": batch_num,
                    "batch_total": batch_total,
                    "refresh": True,
                })

                # Index this batch
                indexed = indexer.index(batch_emails)

                # Knowledge agent (Opus, doubled max_tokens)
                from app.onboarding.agents.knowledge_agent import KnowledgeAgent
                from app.infrastructure.llm_attribution import llm_attribution
                knowledge_agent = KnowledgeAgent(max_tokens=16384, _llm=opus_llm)
                try:
                    with llm_attribution("learning_refresh_deep_knowledge", account_id=account_id):
                        new_knowledge = knowledge_agent.analyse(indexed)
                except Exception as e:
                    logger.error("Deep training knowledge agent failed (batch %d): %s", batch_num, e)
                    new_knowledge = {}

                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "emails_processed": emails_so_far + len(batch_emails) // 3,
                    "total": total_emails,
                    "confidence": int(5 + ((batch_idx + 0.33) / batch_total) * 85),
                    "phase": f"Lot {batch_num}/{batch_total} — Extraction des règles...",
                    "phase_key": "scan_phase_batch_style",
                    "phase_params": {"current": batch_num, "total": batch_total},
                    "step": "style",
                    "step_status": "running",
                    "deep": True,
                    "batch_current": batch_num,
                    "batch_total": batch_total,
                    "refresh": True,
                })

                # Rules agent (Opus, doubled max_tokens)
                from app.onboarding.agents.style_agent import StyleAgent
                style_agent = StyleAgent(max_tokens=16384, _llm=opus_llm)
                try:
                    with llm_attribution("learning_refresh_deep_style", account_id=account_id):
                        new_rules = style_agent.analyse(indexed)
                except Exception as e:
                    logger.error("Deep training rules agent failed (batch %d): %s", batch_num, e)
                    new_rules = {}

                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "emails_processed": emails_so_far + 2 * len(batch_emails) // 3,
                    "total": total_emails,
                    "confidence": int(5 + ((batch_idx + 0.66) / batch_total) * 85),
                    "phase": f"Lot {batch_num}/{batch_total} — Catégorisation...",
                    "phase_key": "scan_phase_batch_label",
                    "phase_params": {"current": batch_num, "total": batch_total},
                    "step": "label",
                    "step_status": "running",
                    "deep": True,
                    "batch_current": batch_num,
                    "batch_total": batch_total,
                    "refresh": True,
                })

                # Category agent (Opus)
                from app.onboarding.agents.label_agent import LabelAgent
                try:
                    label_agent = LabelAgent(max_tokens=16384, _llm=opus_llm)
                    folders = self._fetch_provider_folders(account_id)
                    with llm_attribution("learning_refresh_deep_label", account_id=account_id):
                        new_categories = label_agent.analyse(indexed, folders=folders)
                except Exception as e:
                    logger.error("Deep training category agent failed (batch %d): %s", batch_num, e)
                    new_categories = {}

                # Merge batch results into KB
                batch_counts = self._merge_into_knowledge_base(new_knowledge, new_rules, account_id)
                self._persist_contact_profiles(new_knowledge, new_rules, account_id, indexed.by_contact)
                if new_categories:
                    self._save_category_results(new_categories)

                accumulated_counts["new_contacts"] += batch_counts.get("new_contacts", 0)
                accumulated_counts["new_rules"] += batch_counts.get("new_rules", 0)

                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "emails_processed": emails_so_far + len(batch_emails),
                    "total": total_emails,
                    "confidence": int(5 + ((batch_idx + 1) / batch_total) * 85),
                    "phase": f"Lot {batch_num}/{batch_total} terminé",
                    "phase_key": "scan_phase_batch_done",
                    "phase_params": {"current": batch_num, "total": batch_total},
                    "step": "label",
                    "step_status": "completed",
                    "deep": True,
                    "batch_current": batch_num,
                    "batch_total": batch_total,
                    "refresh": True,
                })

            # All batches done — apply labeling
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": total_emails,
                "total": total_emails,
                "confidence": 92,
                "phase": "Application des labels intelligents...",
                "phase_key": "scan_phase_finishing",
                "phase_params": {},
                "step": "label",
                "step_status": "running",
                "deep": True,
                "batch_current": batch_total,
                "batch_total": batch_total,
                "refresh": True,
            })

            labeling_count = 0
            try:
                labeling_count = self._apply_rules_from_db(account_id, user_email)
            except Exception as e:
                logger.error("Deep training auto-labeling failed: %s", e)

            # Mark refresh done
            try:
                from app.learning_refresh import get_refresh_coordinator
                get_refresh_coordinator().mark_refresh_done()
            except Exception:
                pass

            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "status": "completed",
                "refresh": True,
                "deep": True,
                "emails_analysed": total_emails,
                "batch_total": batch_total,
                "labeling_rules_applied": labeling_count,
                **accumulated_counts,
            })

        except Exception as e:
            logger.error("Deep training failed: %s", str(e), exc_info=True)
            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "status": "failed",
                "refresh": True,
                "deep": True,
                "error": str(e),
            })
        finally:
            self._clear_cancelled(account_id)

    def _run_refresh(self, account_id: int, user_email: str, days: int | None):
        """Run incremental refresh (Knowledge + Rules only, merge results)."""
        try:
            # days=None → deep refresh (full corpus, higher limit)
            if days is not None:
                since_date = datetime.now(timezone.utc) - timedelta(days=days)
                limit = 200
            else:
                since_date = None
                limit = 500

            # Step 1: Load emails
            session = self.session_factory()
            try:
                email_repo = EmailRepository(session)
                loader = RepositoryLoader(email_repo, account_id, user_email)
                load_kwargs: dict = {"limit": limit}
                if since_date is not None:
                    load_kwargs["since_date"] = since_date
                emails, metadata = loader.load(**load_kwargs)
            finally:
                session.close()

            if not emails:
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "status": "completed",
                    "refresh": True,
                    "new_contacts": 0,
                    "new_rules": 0,
                })
                return

            # Step 2: Index
            indexer = EmailIndexer(user_email, account_id=account_id)
            indexed = indexer.index(emails)

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": 0,
                "total": indexed.total_count,
                "confidence": 5,
                "phase": "Indexation terminée, rafraîchissement...",
                "phase_key": "scan_phase_refresh_intro",
                "phase_params": {},
                "refresh": True,
            })

            # Step 3: Run only Knowledge + Rules agents (no Profile)
            from app.onboarding.agents.knowledge_agent import KnowledgeAgent
            from app.onboarding.agents.style_agent import StyleAgent
            from app.infrastructure.llm_attribution import llm_attribution

            new_knowledge = {}
            new_rules = {}

            def on_progress(progress: OnboardingProgress):
                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "emails_processed": int(indexed.total_count * progress.progress / 100),
                    "total": indexed.total_count,
                    "confidence": progress.progress,
                    "phase": progress.message or progress.step,
                    "phase_key": progress.message_key or "",
                    "phase_params": progress.message_params or {},
                    "step": progress.step,
                    "step_status": progress.status,
                    "refresh": True,
                })

            # Knowledge agent
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": 0,
                "total": indexed.total_count,
                "confidence": 10,
                "phase": "Extraction des nouvelles connaissances...",
                "phase_key": "scan_phase_refresh_knowledge",
                "phase_params": {},
                "step": "knowledge",
                "step_status": "running",
                "refresh": True,
            })
            try:
                knowledge_agent = KnowledgeAgent()
                with llm_attribution("learning_refresh_knowledge", account_id=account_id):
                    new_knowledge = knowledge_agent.analyse(indexed)
            except Exception as e:
                logger.error("Refresh knowledge agent failed: %s", e)
                new_knowledge = {}

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count // 2,
                "total": indexed.total_count,
                "confidence": 50,
                "phase": "Connaissances extraites, analyse des règles...",
                "phase_key": "scan_phase_refresh_knowledge_done",
                "phase_params": {},
                "step": "knowledge",
                "step_status": "completed",
                "refresh": True,
            })

            # Rules agent
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count // 2,
                "total": indexed.total_count,
                "confidence": 55,
                "phase": "Extraction des nouvelles règles...",
                "phase_key": "scan_phase_refresh_style",
                "phase_params": {},
                "step": "style",
                "step_status": "running",
                "refresh": True,
            })
            try:
                style_agent = StyleAgent()
                with llm_attribution("learning_refresh_style", account_id=account_id):
                    new_rules = style_agent.analyse(indexed)
            except Exception as e:
                logger.error("Refresh rules agent failed: %s", e)
                new_rules = {}

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count,
                "total": indexed.total_count,
                "confidence": 75,
                "phase": "Règles extraites, catégorisation...",
                "phase_key": "scan_phase_refresh_style_done",
                "phase_params": {},
                "step": "style",
                "step_status": "completed",
                "refresh": True,
            })

            # Category agent
            new_categories = {}
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count,
                "total": indexed.total_count,
                "confidence": 80,
                "phase": "Mise à jour des catégories...",
                "phase_key": "scan_phase_refresh_label",
                "phase_params": {},
                "step": "label",
                "step_status": "running",
                "refresh": True,
            })
            try:
                from app.onboarding.agents.label_agent import LabelAgent
                label_agent = LabelAgent()
                folders = self._fetch_provider_folders(account_id)
                with llm_attribution("learning_refresh_label", account_id=account_id):
                    new_categories = label_agent.analyse(indexed, folders=folders)
            except Exception as e:
                logger.error("Refresh category agent failed: %s", e)
                new_categories = {}

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count,
                "total": indexed.total_count,
                "confidence": 90,
                "phase": "Fusion avec les connaissances existantes...",
                "phase_key": "scan_phase_refresh_merge",
                "phase_params": {},
                "step": "label",
                "step_status": "completed",
                "refresh": True,
            })

            # Step 4: Merge with existing KB
            counts = self._merge_into_knowledge_base(new_knowledge, new_rules, account_id)

            # Persist per-contact style profiles (formality, greeting, closing, language, variant, nickname)
            self._persist_contact_profiles(new_knowledge, new_rules, account_id, indexed.by_contact)

            # Persist category results (labels + rules)
            if new_categories:
                self._save_category_results(new_categories)

            # Step 5: Auto-label existing emails with updated rules
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count,
                "total": indexed.total_count,
                "confidence": 92,
                "phase": "Application des labels intelligents aux emails...",
                "phase_key": "scan_phase_refresh_apply_labels",
                "phase_params": {},
                "step": "label",
                "step_status": "running",
                "refresh": True,
            })
            labeling_count = 0
            try:
                labeling_count = self._apply_rules_from_db(account_id, user_email)
            except Exception as e:
                logger.error("Refresh auto-labeling failed: %s", e)

            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": indexed.total_count,
                "total": indexed.total_count,
                "confidence": 95,
                "phase": "Labels appliqués, finalisation...",
                "phase_key": "scan_phase_refresh_done",
                "phase_params": {},
                "step": "label",
                "step_status": "completed",
                "refresh": True,
            })

            # Step 6: Update the learning coordinator so it knows about this refresh
            try:
                from app.learning_refresh import get_refresh_coordinator
                get_refresh_coordinator().mark_refresh_done()
            except Exception:
                pass

            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "status": "completed",
                "refresh": True,
                "emails_analysed": indexed.total_count,
                "labeling_rules_applied": labeling_count,
                **counts,
            })

        except Exception as e:
            logger.error("Refresh failed: %s", str(e), exc_info=True)
            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "status": "failed",
                "refresh": True,
                "error": str(e),
            })

    def _merge_into_knowledge_base(self, new_knowledge: dict, new_rules: dict, account_id: int) -> dict:
        """Merge new analysis results into existing KB (DB-first, file fallback)."""
        from app.memory_manager import get_memory_manager

        mm = get_memory_manager(account_id=account_id if account_id > 0 else None)
        content = mm.get_memory()

        # Read existing KB
        existing_profile: dict = {}
        existing_knowledge: dict = {"contacts": []}
        existing_rules: dict = {"general_rules": [], "contact_rules": [], "forbidden_phrases": []}

        if content:
            existing_profile, existing_knowledge, existing_rules = parse_knowledge_markdown(content)

        # Count new items before merge
        existing_contact_names = {c.get("name", "").lower() for c in existing_knowledge.get("contacts", [])}
        existing_rule_descs = set()
        for r in existing_rules.get("general_rules", []):
            desc = r.get("description", str(r)) if isinstance(r, dict) else str(r)
            existing_rule_descs.add(desc.lower())

        # Merge
        merged_knowledge = _merge_knowledge(existing_knowledge, new_knowledge)
        merged_rules = _merge_rules(existing_rules, new_rules)

        # Count additions
        new_contact_names = {c.get("name", "").lower() for c in merged_knowledge.get("contacts", [])}
        new_rule_descs = set()
        for r in merged_rules.get("general_rules", []):
            desc = r.get("description", str(r)) if isinstance(r, dict) else str(r)
            new_rule_descs.add(desc.lower())

        counts = {
            "new_contacts": len(new_contact_names - existing_contact_names),
            "new_rules": len(new_rule_descs - existing_rule_descs),
        }

        # Rebuild markdown and save (MemoryManager handles DB vs file)
        md_content = build_knowledge_markdown(existing_profile, merged_knowledge, merged_rules)
        mm.save_memory(md_content, change_summary=f"Refresh: +{counts['new_contacts']}c, +{counts['new_rules']}r")

        logger.info(
            "KB refreshed: +%d contacts, +%d règles (account_id=%d)",
            counts["new_contacts"], counts["new_rules"], account_id,
        )

        return counts

    def _run_analysis(
        self,
        onboarding_id: int,
        account_id: int,
        user_email: str,
        since_days: Optional[int] = None,
        max_emails: Optional[int] = None,
        faq_entries: Optional[list[dict]] = None,
    ):
        """Run the full analysis pipeline (called in background thread).

        Args:
            since_days: Restrict the corpus to the last N days (None = full corpus).
            max_emails: Hard cap on the number of emails (None = loader default).
            faq_entries: Pre-scanned FAQ entries from user-provided source.
        """
        # Heartbeat early so the watchdog sees the run is alive even if the
        # initial DB commits below contend with sync_service and slow down.
        # This is the exact crash path that triggered this watchdog: a
        # 'database is locked' on the status='running' UPDATE killed the
        # thread, leaving the row pinned to waiting_for_sync forever.
        self._bump_heartbeat(onboarding_id)
        session = self.session_factory()
        try:
            repo = OnboardingRepository(session)
            result_model = repo.get(onboarding_id)
            if not result_model:
                logger.error("OnboardingResult %d not found — emitting failure", onboarding_id)
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "status": "failed",
                    "error": f"Enregistrement d'onboarding introuvable (id={onboarding_id})",
                })
                return

            # Mark as running
            result_model.status = "running"
            result_model.started_at = datetime.now(timezone.utc)
            session.commit()
            self._bump_heartbeat(onboarding_id)

            # Step 1: Ensure sent cache is populated — critical for contact_rules.
            # If the volatile sent cache was evicted (e.g. after an auto-send), StyleAgent
            # receives indexed.sent_emails=[] and produces contact_rules=[].
            email_repo = EmailRepository(session)
            sent_in_cache = email_repo.get_sent_emails(account_id, limit=1)
            # Tracks whether the sent-cache fetch was attempted and failed —
            # used later to swap the agent's ``no_sent_emails`` partial reason
            # for ``sent_fetch_failed`` so the UI shows a transient-retry
            # message instead of "you have no sent emails".
            sent_fetch_failed = False
            if not sent_in_cache:
                logger.warning(
                    "Onboarding: sent cache is empty for account %d — fetching from provider",
                    account_id,
                )
                # Visible côté UI : sans event ici, le frontend reste bloqué sur
                # "Initialisation..." pendant 30-60s pendant que provider.get_sent_emails
                # récupère 200 emails. On signale la phase pour que le narrateur
                # affiche "Récupération de vos emails envoyés...".
                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "emails_processed": 0,
                    "total": 0,
                    "confidence": 2,
                    "phase": "Récupération de vos emails envoyés...",
                    "phase_key": "onboarding.scan_phase_fetching_sent",
                    "phase_params": {},
                })
                # The sent-cache fetch can spend 30-90s inside Gmail/Outlook.
                # End the read transaction opened by the cache probe above so
                # Postgres does not kill this session as idle-in-transaction
                # before RepositoryLoader.load() runs.
                session.rollback()

                populate_result = self._populate_sent_cache(account_id, user_email, session)
                sent_fetch_failed = bool(populate_result.get("failed"))

            # Step 2: Load emails
            loader = RepositoryLoader(email_repo, account_id, user_email)
            load_kwargs: dict = {}
            if max_emails is not None and max_emails > 0:
                load_kwargs["limit"] = max_emails
            if since_days is not None and since_days > 0:
                load_kwargs["since_date"] = datetime.now(timezone.utc) - timedelta(days=since_days)
            if load_kwargs:
                logger.info(
                    "Onboarding _run_analysis: targeted load (%s) for account=%d",
                    load_kwargs, account_id,
                )
            emails, metadata = loader.load(**load_kwargs)

            if not emails:
                result_model.status = "failed"
                result_model.error_message = (
                    "Aucun email exploitable trouvé. "
                    "La synchronisation a peut-être échoué — réessayez dans quelques minutes."
                )
                session.commit()
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "status": "failed",
                    "error": "Aucun email exploitable trouvé",
                })
                return

            # Step 2: Index
            indexer = EmailIndexer(user_email, account_id=account_id)
            indexed = indexer.index(emails)

            result_model.emails_analysed = indexed.total_count
            session.commit()

            # OB-H-2 (audit 2026-04-25 onboarding-flawless): defensive
            # check for the worst-case "empty mailbox" — emails were
            # loaded but indexer ended up with no sent AND no received
            # (e.g. all filtered out by the indexer's deduper). Without
            # this, the agents run on 0 input and silently produce
            # generic defaults, with the run marked "completed" despite
            # zero personalised content. Mark partial so the UI surfaces
            # an actionable banner.
            if indexed.sent_count == 0 and indexed.received_count == 0:
                logger.warning(
                    "Onboarding indexer returned empty corpus for account %d "
                    "(loader had %d emails but indexer kept 0)",
                    account_id, len(emails),
                )

            # Notify frontend of total emails count
            self._emit("onboarding:progress_updated", {
                "account_id": account_id,
                "emails_processed": 0,
                "total": indexed.total_count,
                "confidence": 5,
                "phase": "Indexation terminée, lancement de l'analyse...",
                "phase_key": "scan_phase_launching",
                "phase_params": {},
            })

            # Step 3: Analyse with orchestrator
            def on_progress(progress: OnboardingProgress):
                # Extraire les compteurs de découverte du message_params s'ils
                # y ont été mis par l'orchestrateur (cascade per-agent : chaque
                # agent complété pousse SON bucket — contacts, règles).
                params = dict(progress.message_params or {})
                discovery_payload: dict = {}
                for key in ("new_contacts", "new_rules"):
                    if key in params:
                        discovery_payload[key] = params.pop(key)

                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "emails_processed": int(indexed.total_count * progress.progress / 100),
                    "total": indexed.total_count,
                    "confidence": progress.progress,
                    "phase": progress.message or progress.step,
                    "phase_key": progress.message_key or "",
                    "phase_params": params,
                    "step": progress.step,
                    "step_status": progress.status,
                    **discovery_payload,
                })

            # Bridge the orchestrator's discovery stream to the WebSocket.
            # Each real finding becomes one `onboarding:discovery` event
            # so the DiscoveryFeed can surface it as a rolling narrative.
            def on_discovery(d: OnboardingDiscovery) -> None:
                self._emit("onboarding:discovery", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "kind": d.kind,
                    "agent": d.agent,
                    "message_key": d.message_key,
                    "message_params": d.message_params or {},
                    "fallback_message": d.fallback_message,
                    "timestamp_ms": int(time.time() * 1000),
                })

            orchestrator = OnboardingOrchestrator(
                on_progress=on_progress,
                on_discovery=on_discovery,
            )
            analysis_result = orchestrator.run(indexed, faq_entries=faq_entries)

            # Swap "no_sent_emails" → "sent_fetch_failed" when we know the
            # provider call failed (rate-limit / timeout / exception) rather
            # than the user truly having no sent history. Without this, the
            # wizard tells the user to "send some emails and retry" — useless
            # advice when they already have 749 sent emails in Gmail and we
            # just couldn't pull them in this 30-second window. The
            # ``sent_fetch_failed`` reason renders a "couldn't reach your
            # provider, retry in a couple of minutes" message instead.
            if (
                sent_fetch_failed
                and analysis_result.status == "partial"
                and "no_sent_emails" in (analysis_result.partial_reasons or [])
            ):
                analysis_result.partial_reasons = [
                    "sent_fetch_failed" if r == "no_sent_emails" else r
                    for r in analysis_result.partial_reasons
                ]
                analysis_result.error = (
                    "Nous n'avons pas pu récupérer vos emails envoyés — "
                    "votre fournisseur (Gmail/Outlook) limite peut-être nos "
                    "requêtes en ce moment. Réessayez dans quelques minutes."
                )

            # Step 3b: Live discovery counters — extrait du résultat final et émis
            # juste avant `learning_completed` pour que les pills apparaissent
            # dans le narrateur (contacts/projets/règles détectés).
            try:
                knowledge = analysis_result.knowledge or {}
                style = analysis_result.style or {}
                contacts_count = len(knowledge.get("contacts") or [])
                rules_count = (
                    len(style.get("contact_rules") or [])
                    + len(style.get("general_rules") or [])
                )
                self._emit("onboarding:progress_updated", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "emails_processed": indexed.total_count,
                    "total": indexed.total_count,
                    "confidence": 98,
                    "phase": "Consolidation des découvertes...",
                    "phase_key": "onboarding.scan_phase_consolidating",
                    "phase_params": {},
                    "new_contacts": contacts_count,
                    "new_rules": rules_count,
                })
            except Exception as _discovery_err:
                logger.debug("Discovery counters emit skipped: %s", _discovery_err)

            # Step 4: Store results
            if analysis_result.status in ("completed", "partial"):
                result_model.status = analysis_result.status
                result_model.profile_json = json.dumps(analysis_result.profile, ensure_ascii=False)
                result_model.knowledge_json = json.dumps(analysis_result.knowledge, ensure_ascii=False)
                result_model.rules_json = json.dumps(analysis_result.style, ensure_ascii=False)
                result_model.categories_json = json.dumps(analysis_result.label, ensure_ascii=False)
                result_model.completed_at = datetime.now(timezone.utc)
                # OB-02: persist the partial reason in error_message even when
                # status == 'partial' (downstream get_status reads this field
                # to render the user-facing banner).
                if analysis_result.status == "partial" and analysis_result.error:
                    result_model.error_message = analysis_result.error

                # P1-003: write to memoire.md and contact profiles BEFORE
                # session.commit() — prevents the DB row showing "completed"
                # while the knowledge base is in a partial or corrupted state.
                # If either KB write raises, the outer except marks the run
                # as "failed" and the row was never committed as "completed".
                self._apply_to_knowledge_base(
                    analysis_result.profile or {},
                    analysis_result.knowledge or {},
                    analysis_result.style or {},
                    categories=analysis_result.label or {},
                    account_id=account_id,
                    email_count=indexed.total_count,
                )

                # Persist per-contact style profiles (formality, greeting, closing, language, variant, nickname)
                self._persist_contact_profiles(
                    analysis_result.knowledge or {},
                    analysis_result.style or {},
                    account_id,
                    indexed.by_contact,
                )

                session.commit()

                # Update learning coordinator so manual refreshes know the baseline
                try:
                    from app.learning_refresh import get_refresh_coordinator
                    get_refresh_coordinator().mark_refresh_done()
                except Exception:
                    pass

                # P1-NEW-005: include version_ms so the frontend can discard
                # stale REST /status responses that arrive after this WS event.
                _completed_version_ms = int(time.time() * 1000)
                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "onboarding_id": onboarding_id,
                    "status": analysis_result.status,
                    "emails_analysed": indexed.total_count,
                    "error": analysis_result.error,
                    # OB-02: surface the structured partial reasons so the
                    # frontend can render the right banner ("no sent emails",
                    # "unsupported language", ...) instead of a generic
                    # "Erreur inconnue".
                    "partial_reasons": list(getattr(analysis_result, "partial_reasons", []) or []),
                    "version_ms": _completed_version_ms,
                })

                # Build insights summary for frontend
                profile = analysis_result.profile or {}
                knowledge = analysis_result.knowledge or {}
                rules = analysis_result.style or {}

                strengths = []
                if profile.get("role"):
                    strengths.append(f"Rôle identifié : {profile['role']}")
                if knowledge.get("contacts"):
                    strengths.append(f"{len(knowledge['contacts'])} contacts analysés")
                if rules.get("contact_rules"):
                    strengths.append(f"{len(rules['contact_rules'])} règles de communication détectées")

                self._emit("onboarding:insights_generated", {
                    "account_id": account_id,
                    "writing_style": profile.get("tone", "Semi-formel"),
                    "tone_profile": profile.get("formality", ""),
                    "strengths": strengths,
                    "topics": [],
                    "categories": [],
                })
            else:
                result_model.status = "failed"
                result_model.error_message = analysis_result.error
                session.commit()

                self._emit("onboarding:learning_completed", {
                    "account_id": account_id,
                    "status": "failed",
                    "error": analysis_result.error,
                })

        except Exception as e:
            logger.error("Onboarding analysis failed: %s", str(e), exc_info=True)
            try:
                if result_model:
                    result_model.status = "failed"
                    result_model.error_message = str(e)
                    session.commit()
            except Exception:
                session.rollback()

            self._emit("onboarding:learning_completed", {
                "account_id": account_id,
                "status": "failed",
                "error": str(e),
            })
        finally:
            session.close()
            # P1-006: clear the cancel flag — cancel() sets it for standard
            # onboarding but _run_analysis doesn't poll it (only _run_deep_refresh
            # does). Without this the entry leaks in self._cancelled forever.
            self._clear_cancelled(account_id)
            # Drop the heartbeat — the run reached a terminal state
            # (success, failed, or exception). Otherwise the dict accumulates
            # stale entries across the process lifetime.
            self._clear_heartbeat(onboarding_id)

    def _apply_to_knowledge_base(
        self, profile: dict, knowledge: dict, rules: dict,
        categories: dict | None = None,
        account_id: int = 0, email_count: int = 0,
    ):
        """Convert onboarding results to memoire.md and writing style profile.

        This bridges the onboarding analysis with:
        - memoire.md (TrainingPanel Profil/Savoir/Règles + DrafterAgent)
        - WritingStyleStore (Apprentissages → Style d'écriture)
        - LabelStore (labels custom + LabelingRules from LabelAgent)
        """
        md_content = build_knowledge_markdown(profile, knowledge, rules)

        # Write to memoire.md (legacy fallback — DB is now the source of truth via
        # OnboardingResult.*_json, written in _run_analysis before this method).
        # Kept for backward compat with daemon.py and code that reads the file directly.
        try:
            from app.config import KNOWLEDGE_DIR
            knowledge_dir = Path(KNOWLEDGE_DIR)
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            knowledge_file = knowledge_dir / "memoire.md"
            _atomic_write_text(knowledge_file, md_content, encoding="utf-8")
            logger.info("Knowledge base written to memoire.md (legacy fallback, %d chars)", len(md_content))
        except Exception as e:
            # Non-fatal: DB is the primary store, file is optional fallback
            logger.warning("Failed to write memoire.md fallback (non-fatal): %s", e)

        # Write writing style profile for Apprentissages panel
        if account_id > 0:
            self._save_writing_style_profile(profile, account_id, email_count)

        # Persist suggested labels and labeling rules from LabelAgent
        if categories:
            self._save_category_results(categories, account_id=account_id)

    def _save_category_results(self, categories: dict, account_id: int = 0):
        """Persist default labeling rules (Action/FYI/Noise) from LabelAgent.

        Never auto-creates labels — only the user can create labels explicitly.

        OB-C-1 (audit 2026-04-25 onboarding-flawless): scoped to a
        per-account label store so onboarding-learned rules don't leak
        into the global store and apply to other users' emails on a
        multi-user deploy. account_id=0 keeps the legacy global path for
        any caller that still passes nothing — those will be migrated.
        """
        try:
            import uuid
            from app.infrastructure.container import get_container
            from app.domain.entities.email_labels import LabelingRule

            container = get_container()
            store = (
                container.get_label_store(account_id=account_id)
                if account_id
                else container.get_label_store()
            )

            # Only save default label rules (Action/FYI/Noise)
            # No project labels or custom rules — user creates labels explicitly
            default_rules = categories.get("default_label_rules", [])
            saved = 0
            skipped_overbroad = 0
            for cr in default_rules:
                if not isinstance(cr, dict) or not cr.get("label_name"):
                    continue
                condition_type = cr.get("condition_type", "subject")
                condition_value = (cr.get("condition_value") or "").strip()
                label_name = cr["label_name"]

                too_short_text = (
                    condition_type in {"subject", "subject_keyword", "body", "body_keyword"}
                    and len(condition_value) < 4
                )
                wildcard_recipient = (
                    condition_type == "recipient_type"
                    and condition_value.lower() == "to"
                    and label_name.lower() == "action"
                )
                if too_short_text or wildcard_recipient:
                    skipped_overbroad += 1
                    logger.warning(
                        "[onboarding] Rejected overbroad learned rule %s='%s' -> %s",
                        condition_type,
                        condition_value,
                        label_name,
                    )
                    continue

                rule = LabelingRule(
                    rule_id=str(uuid.uuid4()),
                    label_name=label_name,
                    condition_type=condition_type,
                    condition_value=condition_value,
                    confidence=cr.get("confidence", 0.5),
                    learned_from="onboarding_label_agent",
                )
                store.add_rule(rule)
                saved += 1

            if skipped_overbroad:
                logger.info(
                    "[onboarding] Skipped %d overbroad rule(s); kept %d",
                    skipped_overbroad,
                    saved,
                )
            logger.info("Category results saved: %d default rules (no auto-created labels)", saved)
            # OB-H-10 (audit 2026-04-25): mark partial so the orchestrator
            # surfaces an actionable error to the user. We tag it on the
            # incoming `categories` dict because the orchestrator scans
            # `result.label.get("_partial")` (cf. C-3 fix) — `categories`
            # is the same dict that gets attached to `result.label`.
            if saved == 0 and default_rules:
                categories["_partial"] = True
                categories.setdefault("_reason", "label_rules_save_skipped")
        except Exception as e:
            logger.error("Failed to save category results: %s", e, exc_info=True)
            # OB-H-10: don't silently swallow — propagate the partial flag
            # so the run is downgraded to status="partial" with a clear
            # reason instead of a green "completed" badge over no rules.
            try:
                categories["_partial"] = True
                categories.setdefault("_reason", "label_rules_save_failed")
            except Exception:
                pass

    def _apply_rules_from_db(self, account_id: int, user_email: str) -> int:
        """Apply all labeling rules to emails from the DB (no provider needed)."""
        from app.infrastructure.container import get_container
        from app.db.database import get_db_session
        from app.db.repositories.email_repository import EmailRepository
        from app.domain.entities.email_labels import LabelAssignment, DEFAULT_LABEL_NAMES

        container = get_container()
        # OB-C-1 (audit 2026-04-25): rules + assignments must come from
        # the caller's per-account store, otherwise rules learned during
        # User A's onboarding (in the global store) would label User B's
        # emails on the next sync.
        label_store = (
            container.get_label_store(account_id=account_id)
            if account_id
            else container.get_label_store()
        )
        all_rules = label_store.get_rules()
        if not all_rules:
            return 0

        updated = 0
        with get_db_session() as db_session:
            repo = EmailRepository(db_session)
            db_emails = repo.get_by_account(account_id=account_id, limit=200)

            for email in db_emails:
                email_id = email.email_id
                if not email_id:
                    continue

                is_cc = False
                recipients = []
                if email.recipients:
                    recipients = email.recipients.split(",") if isinstance(email.recipients, str) else email.recipients
                    is_cc = user_email.lower() not in [r.strip().lower() for r in recipients] if recipients else False

                sender_str = email.sender or ""
                subject_str = email.subject or ""
                body_str = email.body_text or email.snippet or ""
                email_data = {
                    "sender": sender_str.lower() if sender_str else "",
                    "subject": subject_str.lower() if subject_str else "",
                    "body": body_str.lower()[:2000] if body_str else "",
                    "recipients": recipients,
                    "is_cc": is_cc,
                }

                existing = label_store.get_assignment(email_id)
                if not existing:
                    existing = LabelAssignment(email_id=email_id, assigned_by="rule")

                changed = False
                for rule in all_rules:
                    if rule.matches(email_data) and rule.label_name not in existing.labels:
                        if rule.label_name in DEFAULT_LABEL_NAMES:
                            if existing.assigned_by != "user":
                                existing.set_default_label(
                                    rule.label_name, rule.confidence,
                                    f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                                changed = True
                        else:
                            existing.add_custom_label(
                                rule.label_name, rule.confidence,
                                f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                            changed = True

                if changed:
                    existing._rebuild_labels()
                    label_store.save_assignment(existing)
                    updated += 1

        logger.info("Refresh auto-labeling: %d emails updated with %d rules", updated, len(all_rules))

        # Audit 2026-05-06: post-onboarding batch labeling for the long
        # tail (emails that no rule matched). Opt-in via env
        # POST_ONBOARDING_BATCH_LABEL=true. Submits one Anthropic batch
        # at the 50% discount tier; a Hetzner cron (see scripts/poll_batch_labels.py
        # follow-up) polls the batch later and applies the labels. Fail-cheap.
        try:
            from app.services.batch_label_service import (
                submit_post_onboarding_label_batch,
                is_enabled as _batch_enabled,
            )
            if _batch_enabled() and account_id and updated < 200:
                # Only submit if rules left a meaningful tail unlabeled.
                with get_db_session() as _bsession:
                    _brepo = EmailRepository(_bsession)
                    _bemails = _brepo.get_by_account(account_id=account_id, limit=500)
                _payload = []
                for _e in _bemails:
                    eid = getattr(_e, "email_id", None)
                    if not eid:
                        continue
                    # Skip emails the rules already labeled (cheap re-check).
                    _existing = label_store.get_assignment(eid)
                    if _existing and _existing.labels:
                        continue
                    _payload.append({
                        "email_id": eid,
                        "sender": getattr(_e, "sender", "") or "",
                        "subject": getattr(_e, "subject", "") or "",
                        "body": (getattr(_e, "body_text", None)
                                 or getattr(_e, "snippet", "") or ""),
                    })
                if _payload:
                    submit_post_onboarding_label_batch(account_id, _payload)
        except Exception as _e:  # pragma: no cover — never break onboarding
            logger.debug("post-onboarding batch labeling skipped: %s", _e)

        return updated

    def _save_writing_style_profile(self, profile: dict, account_id: int, email_count: int):
        """Populate WritingStyleStore from onboarding profile data."""
        try:
            from datetime import datetime as dt
            from app.domain.entities.writing_style import WritingStyleProfile, FormalityLevel
            from app.infrastructure.container import get_container

            tone = profile.get("tone", {})
            sig = profile.get("signature", {})

            # Map onboarding tone → FormalityLevel
            tone_map = {
                "formal": FormalityLevel.FORMAL,
                "semi-formal": FormalityLevel.MIXED,
                "casual": FormalityLevel.CASUAL,
            }
            formality = tone_map.get(tone.get("default_tone", ""), FormalityLevel.MIXED)

            # Extract greetings/closings ordered by FORMALITY (formal → [0],
            # casual → [1]), the convention every consumer assumes. Ordering by
            # the formality-keyed map (not dict insertion order) is what keeps
            # "Salut …" out of the formal slot — see _order_styles_by_formality.
            _languages = profile.get("languages") or []
            _primary_lang = _languages[0] if _languages else "fr"
            greetings = _order_styles_by_formality(tone.get("greeting_styles") or {}, _primary_lang)
            closings = _order_styles_by_formality(tone.get("closing_styles") or {}, _primary_lang)
            # Never store LLM "no signal" placeholders ("Unknown (forwarded
            # content)", "Salut Unknown") as the default style — they leak into
            # drafts. Mirror of the analyzer-adapter filter (2026-06-01 fix).
            from app.prompts.identity import is_placeholder_style_value
            greetings = [g for g in greetings if not is_placeholder_style_value(g)]
            closings = [c for c in closings if not is_placeholder_style_value(c)]

            # Build signature text
            sig_text = None
            if sig and sig.get("name"):
                parts = [sig["name"]]
                if sig.get("title"):
                    parts.append(sig["title"])
                if sig.get("company"):
                    parts.append(sig["company"])
                sig_text = ", ".join(parts)

            # Auto-detect format preferences from sent emails
            avg_email_length = 0
            avg_sentence_length = 0.0
            detected_variant = ""
            try:
                avg_email_length, avg_sentence_length, detected_variant = self._compute_sent_metrics(account_id)
            except Exception as e:
                logger.debug("Format auto-detect skipped: %s", e)

            # Prefer ProfileAgent's language_variant (already extracted by the LLM
            # that analyzed the same emails — no extra API call needed).
            profile_variant = profile.get("language_variant") or ""
            if profile_variant:
                normalized = self._normalize_variant(profile_variant)
                if normalized:
                    detected_variant = normalized

            store = get_container().get_writing_style_store()

            # Preserve contact_profiles + reference_examples from the existing
            # file if present — `_save_writing_style_profile` only updates the
            # account-wide fields (formality, greetings, signature, etc).
            # Without this carry-over, a rebuild wipes every per-contact
            # enrichment (formality_override, greeting, closing, nickname,
            # variante) that `_persist_contact_profiles` had written just
            # before — which was the "Per-contact writing style is empty"
            # regression after re-onboarding.
            existing = store.load(account_id)
            preserved_contact_profiles = dict(existing.contact_profiles) if existing else {}
            preserved_reference_examples = list(existing.reference_examples) if existing else []

            # Issue #187: run statistical inference on the outbox to populate
            # continuous metrics + anonymized few-shot examples. Without this,
            # every onboarded account stayed with default zeros (formality_score=0.5,
            # vocabulary_density=0.0, reference_examples=[]) and the
            # <STYLE_EXAMPLES> block was never injected — the entire
            # `build_style_guidance_from_profile` feature was dormant.
            # Fail-open: any exception falls back to existing values, never
            # blocks the onboarding pipeline.
            inferred_metrics, inferred_examples = self._compute_inferred_style_metrics(account_id)

            # Re-onboarding: keep existing examples if the new inference
            # produced none (e.g. transient DB error, empty outbox).
            reference_examples = inferred_examples or preserved_reference_examples

            style_profile = WritingStyleProfile(
                account_id=account_id,
                analyzed_at=dt.utcnow(),
                email_count=email_count,
                formality_level=formality,
                preferred_greetings=greetings[:5],
                preferred_closings=closings[:5],
                typical_signature=sig_text,
                avg_email_length=avg_email_length,
                avg_sentence_length=inferred_metrics.get("avg_sentence_length", avg_sentence_length),
                # Optional[float] (PR2 sentinel) : .get() returning None means
                # "never measured" — preferred over a defaulted 0.5/0.0 which
                # would gaslight the LLM into asserting "style mixte" or
                # "0 emoji" with no empirical basis.
                sentence_length_variance=inferred_metrics.get("sentence_length_variance"),
                vocabulary_density=inferred_metrics.get("vocabulary_density"),
                formality_score=inferred_metrics.get("formality_score"),
                emoji_frequency=inferred_metrics.get("emoji_rate"),
                exclamation_rate=inferred_metrics.get("exclamation_rate"),
                # PR4 follow-up — `uses_emojis` and `bullet_list_ratio` removed
                # from the entity (never read in any prompt after PR3 fusion).
                avg_paragraph_count=inferred_metrics.get("avg_paragraph_count"),
                contact_profiles=preserved_contact_profiles,
                reference_examples=reference_examples,
            )

            store.save(style_profile)

            # Auto-set format and variant in memoire.md
            self._auto_set_format_preferences(avg_email_length, avg_sentence_length, detected_variant, account_id=account_id)

            logger.info(
                "Writing style profile saved for account %d (%d greetings, %d closings, avg_length=%d words, avg_sentence=%.1f)",
                account_id, len(greetings), len(closings), avg_email_length, avg_sentence_length,
            )
        except Exception as e:
            logger.error("Failed to save writing style profile: %s", e)

    # Salutation prefixes to strip when extracting a first name from a greeting.
    _SALUTATION_PREFIX_RE = re.compile(
        r"^(?:salut|bonjour|bonsoir|hello|hi|hey|dear|cher[e]?|chere)\s+",
        re.IGNORECASE,
    )
    # Honorifics that indicate the following word is a family name, not a first name.
    _HONORIFICS: frozenset = frozenset({
        "monsieur", "m.", "madame", "mme", "mademoiselle", "mlle",
        "mr", "mrs", "ms", "miss", "dr", "dr.", "prof", "maître", "maitre",
        "sir",
    })
    # Bare salutation words — present when no name follows (e.g. "Bonjour,").
    _SALUTATION_WORDS: frozenset = frozenset({
        "salut", "bonjour", "bonsoir", "hello", "hi", "hey",
        "dear", "cher", "chère", "chere",
    })

    @classmethod
    def _extract_name_from_greeting(cls, greeting: str) -> str | None:
        """Extract the first name actually used in a greeting.

        Examples:
          "Salut Alice,"       → "Alice"
          "Hi James,"          → "James"
          "Bonjour Sophie,"    → "Sophie"
          "Bonjour Monsieur Dupont," → None  (family name after honorific)
          "Salut,"             → None  (no name present)
          "(none)"             → None
        """
        if not greeting or greeting.startswith("("):
            return None
        # Take the primary variant only (before " / ")
        primary = greeting.split(" / ")[0].strip().rstrip(" ,.")
        # Strip leading salutation word
        stripped = cls._SALUTATION_PREFIX_RE.sub("", primary).strip().rstrip(" ,.")
        if not stripped:
            return None
        words = stripped.split()
        if not words:
            return None
        candidate = words[0].rstrip(".,")
        cl = candidate.lower()
        # If first word is an honorific, the next word is a family name — skip entirely
        if cl in cls._HONORIFICS:
            return None
        # If the regex didn't strip the salutation (e.g. "Bonjour," with no space after),
        # the candidate is the salutation word itself — return None (no name present)
        if cl in cls._SALUTATION_WORDS:
            return None
        # Must look like a proper name: capitalized, length > 1
        if len(candidate) > 1 and candidate[0].isupper():
            return candidate
        return None

    def _persist_contact_profiles(self, knowledge: dict, rules: dict, account_id: int, emails_by_contact: Optional[Dict[str, list]] = None) -> None:
        """Persist ALL per-contact style fields from onboarding into WritingStyleProfile.

        Merges KnowledgeAgent + StyleAgent outputs per contact:
        - StyleAgent (contact_rules): tone → formality, greeting, closing, language
        - KnowledgeAgent (contacts): language_variant, name → nickname, preferred_tone/language (fallback)

        Semantics: None values are no-ops — manual user settings are preserved.
        Only non-empty scan-detected values overwrite existing data.
        """
        # Index StyleAgent contact_rules by email (primary source for greeting/closing/tone)
        style_by_email: dict = {}
        for rule in (rules.get("contact_rules") or []):
            if isinstance(rule, dict) and rule.get("contact_email"):
                style_by_email[rule["contact_email"].lower()] = rule

        # Index KnowledgeAgent contacts by email (primary source for variant/nickname)
        knowledge_by_email: dict = {}
        for contact in (knowledge.get("contacts") or []):
            if isinstance(contact, dict) and contact.get("email"):
                knowledge_by_email[contact["email"].lower()] = contact

        all_emails = set(style_by_email) | set(knowledge_by_email)
        if not all_emails:
            return

        try:
            from app.domain.entities.writing_style import FormalityLevel, WritingStyleProfile
            from app.infrastructure.container import get_container

            store = get_container().get_writing_style_store()
            profile = store.load(account_id)
            if not profile:
                # Lazy-create a blank profile so per-contact enrichment is never
                # silently dropped. The base profile built from sent-email metrics
                # may not exist yet (new account with zero outbox, crash during
                # _save_writing_style_profile, or a refresh path that skips it).
                # Without this, the per-contact editor stayed empty even though
                # the KnowledgeAgent had correctly detected every contact.
                profile = WritingStyleProfile.create_empty(account_id)

            _tone_to_formality = {
                "formal": FormalityLevel.FORMAL,
                "semi-formal": FormalityLevel.MIXED,
                "casual": FormalityLevel.CASUAL,
            }
            _lang_to_langue = {"fr": "français", "en": "anglais"}

            for email in all_emails:
                style = style_by_email.get(email, {})
                kn = knowledge_by_email.get(email, {})

                # Formality: StyleAgent takes precedence (based on actual sent emails)
                tone_str = style.get("tone") or kn.get("preferred_tone", "")
                formality = _tone_to_formality.get(tone_str) if tone_str else None

                # Greeting: take primary variant (before " / "), skip placeholder values
                raw_greeting = style.get("greeting") or None
                if raw_greeting:
                    primary = raw_greeting.split(" / ")[0].strip()
                    greeting = primary if primary and not primary.startswith("(") else None
                else:
                    greeting = None

                # Closing: take primary variant (before " / "), skip placeholder values
                raw_closing = style.get("closing") or None
                if raw_closing:
                    primary = raw_closing.split(" / ")[0].strip()
                    closing = primary if primary and not primary.startswith("(") else None
                else:
                    closing = None

                # Spoken language: StyleAgent first, KnowledgeAgent fallback; "mixed" → None (auto)
                lang_raw = style.get("language") or kn.get("preferred_language", "")
                langue = _lang_to_langue.get(lang_raw) if lang_raw else None

                # Language variant: KnowledgeAgent (LLM + domain heuristics), normalized to ISO
                raw_variant = kn.get("language_variant")
                langue_variante = self._normalize_variant(raw_variant) if raw_variant else None
                # Fallback 1: read the contact's received emails and ask the LLM —
                # more accurate than TLD for .com/.org contacts, multilingual,
                # and jargon-safe (only the ISO tag is kept, content is discarded).
                if not langue_variante and emails_by_contact is not None:
                    langue_variante = self._detect_variant_from_contact_emails(
                        email, emails_by_contact.get(email, [])
                    )
                # Fallback 2: derive variant from the TLD when no emails are available.
                if not langue_variante:
                    langue_variante = self._detect_variant_from_domain(email)

                # Infer spoken language from the variant when KnowledgeAgent did
                # not provide one (fr-* → français, en-* → anglais).
                if not langue and langue_variante:
                    if langue_variante.startswith("fr-"):
                        langue = "français"
                    elif langue_variante.startswith("en-"):
                        langue = "anglais"

                # Nickname: prefer the first name extracted from the actual greeting
                # (what the user really writes, e.g. "Salut Ali," → "Ali") and fall
                # back to the first capitalized word of the KnowledgeAgent full name.
                nickname = self._extract_name_from_greeting(raw_greeting or "")
                if not nickname:
                    full_name = (kn.get("name") or "").strip()
                    email_prefix = email.split("@")[0].lower()
                    if full_name and full_name.lower() != email_prefix:
                        first_word = full_name.split()[0]
                        if len(first_word) > 1 and first_word[0].isupper():
                            nickname = first_word

                # Tokenize: strip the recipient's first name so the greeting
                # becomes a reusable template (e.g. "Bonjour Alexandra," →
                # "Bonjour {first_name},"). Expansion happens at draft time
                # via ContactStyleProfile.to_prompt_hint().
                if greeting and nickname:
                    from app.prompts.identity import _tokenize_greeting
                    greeting = _tokenize_greeting(greeting, nickname)

                # update_contact_profile: None = no-op, "" = clear, value = set
                profile.update_contact_profile(
                    email=email,
                    formality_override=formality,
                    greeting=greeting,
                    closing=closing,
                    langue=langue,
                    langue_variante=langue_variante,
                    nickname=nickname,
                )

            store.save(profile)
            logger.info(
                "Contact profiles enriched: %d contacts (account %d) — formalité, salutation, clôture, langue, variante, surnom",
                len(all_emails), account_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to persist contact profiles for account %s: %s",
                account_id, e, exc_info=True,
            )

    def _compute_inferred_style_metrics(self, account_id: int) -> tuple[dict, list]:
        """Run :class:`StyleInferenceService` on the outbox (issue #187).

        Returns ``(metrics_dict, reference_examples_list)``. Both are empty on:
            - empty outbox,
            - DB / repository error,
            - inference failure,
            - account without sent emails synced yet.

        Fail-open : any exception is logged and swallowed — onboarding must
        never fail because the *enrichment* metrics path errors out. The base
        WritingStyleProfile (greetings, closings, signature, formality_level)
        is built from LLM extractions and stays valid without these metrics.
        """
        try:
            from app.db.database import get_session_factory
            from app.db.repositories.email_repository import EmailRepository
            from app.domain.services.style_inference_service import StyleInferenceService

            session = get_session_factory()()
            try:
                repo = EmailRepository(session)
                sent_emails = list(repo.get_sent_emails(account_id, limit=500))
            finally:
                session.close()

            if not sent_emails:
                return {}, []

            service = StyleInferenceService()
            metrics = service.analyze_outbox(sent_emails)
            examples = service.select_reference_examples(sent_emails)

            # Defence in depth : `select_reference_examples` is the only producer
            # in the codebase and always sets `anonymized=True`, but we re-filter
            # here so a future regression (e.g. a non-anonymizing fast path)
            # cannot leak unredacted text into the prompt. Mirrors the same
            # check in `app/api/style_inference.py:_build_profile`.
            safe_examples = [ex for ex in examples if ex.anonymized]
            if len(safe_examples) != len(examples):
                logger.error(
                    "Onboarding blocked %d non-anonymized style examples for account %s",
                    len(examples) - len(safe_examples), account_id,
                )

            logger.info(
                "Style inference for account %s: %d emails analyzed, %d reference examples",
                account_id, len(sent_emails), len(safe_examples),
            )
            return metrics, safe_examples
        except Exception as e:
            logger.warning(
                "Style inference skipped for account %s (%s) — onboarding continues with default metrics",
                account_id, e,
            )
            return {}, []

    def _compute_sent_metrics(self, account_id: int) -> tuple:
        """Compute avg word count, avg sentence length, and language variant from sent emails."""
        import re
        from app.db.database import get_session_factory
        from app.db.repositories.email_repository import EmailRepository

        session = get_session_factory()()
        try:
            repo = EmailRepository(session)
            sent_emails = repo.get_sent_emails(account_id, limit=50)

            word_counts = []
            sentence_lengths = []
            all_text = []

            for email in sent_emails:
                body = getattr(email, 'body', '') or ''
                if len(body) < 20:
                    continue

                words = body.split()
                word_counts.append(len(words))
                all_text.append(body.lower())

                sentences = re.split(r'[.!?]+', body)
                for s in sentences:
                    ws = s.split()
                    if len(ws) >= 2:
                        sentence_lengths.append(len(ws))

            if not word_counts:
                return 0, 0.0, ""

            avg_words = round(sum(word_counts) / len(word_counts))
            avg_sentence = round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1)

            # Detect language variant from vocabulary
            variant = self._detect_language_variant(all_text, sent_emails)

            return avg_words, avg_sentence, variant
        finally:
            session.close()

    # ISO code → display label mapping (used by identity.py and frontend)
    VARIANT_DISPLAY = {
        "fr-CA": "Québec", "fr-FR": "France", "fr-BE": "Belgique",
        "fr-CH": "Suisse", "en-US": "États-Unis", "en-GB": "Royaume-Uni",
        "en-AU": "Australie", "pt-BR": "Brésil", "pt-PT": "Portugal",
        "es-ES": "Espagne", "es-MX": "Mexique", "ja-JP": "Japon",
    }

    # Reverse: display label → ISO code (for legacy migration)
    _LABEL_TO_ISO = {v: k for k, v in VARIANT_DISPLAY.items()}
    _LABEL_TO_ISO.update({"Canada": "fr-CA", "Québec": "fr-CA"})

    _VALID_ISO_PATTERN = re.compile(r"^[a-z]{2}-[A-Z]{2}$")

    def _detect_language_variant(self, texts: list, emails: "Sequence[Email]") -> str:
        """Detect regional language variant via signature address + LLM body analysis.

        Returns an ISO language-region tag (e.g. 'fr-CA', 'fr-FR', 'en-US') or ''.
        """
        body_sample = " ".join(texts)[:3000]
        if len(body_sample) < 50:
            return ""

        address_hint = self._extract_signature_address(emails)

        try:
            from app.infrastructure.container import get_container
            # Onboarding language-variant detection — routes to ANTHROPIC_API_KEY_ONBOARDING.
            llm = get_container().llm_onboarding_label

            prompt = (
                "Detect the regional language variant of this email author.\n"
                f"Signature address: {address_hint or 'not found'}\n\n"
                f"Email body sample:\n{body_sample}\n\n"
                "Return ONLY an ISO language-region tag (e.g. fr-CA, fr-FR, fr-BE, fr-CH, "
                "en-US, en-GB, en-AU, pt-BR, pt-PT, es-ES, es-MX, ja-JP).\n"
                "If not enough signal, return the most likely tag based on the language detected."
            )

            response = llm.complete(system="", user=prompt, max_tokens=20, temperature=0.0)
            raw = response.content.strip().split()[0] if response.content else ""
            return self._normalize_variant(raw)
        except Exception as e:
            logger.warning("Language variant detection failed: %s", e)
            return ""

    @staticmethod
    def _extract_signature_address(emails: "Sequence[Email]") -> str:
        """Extract postal address from the user's email signatures."""
        for email in reversed(emails[-20:]):
            body = getattr(email, 'body', '') or ''
            if len(body) < 30:
                continue
            lines = body.strip().split('\n')
            tail = lines[-8:]
            for line in tail:
                line = line.strip()
                if re.search(r'\b\d{5}\b', line) or re.search(r'\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b', line):
                    return line
                if re.search(r'\b(?:France|Canada|Québec|Belgique|Suisse|USA|Brasil|México|Australia|UK)\b', line, re.IGNORECASE):
                    return line
        return ""

    @classmethod
    def _normalize_variant(cls, raw: str) -> str:
        """Normalize a variant string to an ISO code (e.g. 'fr-CA')."""
        raw = raw.strip().strip('"').strip("'")
        if cls._VALID_ISO_PATTERN.match(raw):
            return raw
        if raw in cls._LABEL_TO_ISO:
            return cls._LABEL_TO_ISO[raw]
        return ""

    # TLD → ISO variant fallback, used when the KnowledgeAgent cannot infer it
    # (typical for RECV-only contacts whose bodies are hidden from its prompt).
    # Aligned with agentys-app/src/components/ContactStyleEditor.tsx:51.
    # Longest suffixes MUST come first so `.gouv.qc.ca` wins over `.ca`.
    _DOMAIN_VARIANT_SUFFIXES = (
        (".gouv.qc.ca", "fr-CA"),
        (".qc.ca", "fr-CA"),
        (".gouv.fr", "fr-FR"),
        (".com.br", "pt-BR"),
        (".com.au", "en-AU"),
        (".co.uk", "en-GB"),
        (".fr", "fr-FR"),
        (".be", "fr-BE"),
        (".ch", "fr-CH"),
        (".es", "es-ES"),
        (".br", "pt-BR"),
        (".au", "en-AU"),
        (".uk", "en-GB"),
        (".mx", "es-MX"),
    )

    def _detect_variant_from_contact_emails(
        self,
        contact_email: str,
        all_contact_emails: list,
    ) -> Optional[str]:
        """Detect language variant by reading emails received from this contact.

        Runs once per contact during onboarding. The body sample is discarded
        after the LLM returns the ISO tag — no jargon leaks into drafts.
        Returns None when there is not enough signal (the caller falls through
        to the domain-TLD heuristic).
        """
        from app.onboarding.schemas import EmailDirection

        received = [
            e for e in all_contact_emails
            if (getattr(e, "direction", None) == EmailDirection.RECEIVED
                and getattr(e, "sender_email", "").lower() == contact_email.lower()
                and getattr(e, "body", ""))
        ]
        if not received:
            return None

        sample = received[-5:]
        body_sample = " ".join(e.body[:500] for e in sample)[:2500]
        if len(body_sample.strip()) < 30:
            return None

        try:
            from app.infrastructure.container import get_container
            llm = get_container().llm_onboarding_label

            prompt = (
                "Detect the regional language variant used by the author of these emails.\n\n"
                f"Email samples:\n{body_sample}\n\n"
                "Return ONLY an ISO language-region tag such as: fr-FR, fr-BE, fr-CH, fr-CA, "
                "en-US, en-GB, en-AU, pt-BR, pt-PT, es-ES, es-MX, "
                "it-IT, ja-JP, zh-CN, zh-TW, ar-SA, ru-RU.\n"
                "If there is not enough signal to determine the variant with confidence, "
                "return empty string."
            )

            response = llm.complete(system="", user=prompt, max_tokens=20, temperature=0.0)
            raw = response.content.strip().split()[0] if response.content else ""
            return self._normalize_variant(raw) or None
        except Exception as e:
            logger.warning("Contact variant detection failed for %s: %s", contact_email, e)
            return None

    @classmethod
    def _detect_variant_from_domain(cls, email: str) -> str | None:
        """Infer an ISO language variant from the contact's email domain."""
        domain = email.split("@", 1)[1].lower() if "@" in email else ""
        if not domain:
            return None
        for suffix, variant in cls._DOMAIN_VARIANT_SUFFIXES:
            if domain.endswith(suffix):
                return variant
        return None

    def _auto_set_format_preferences(self, avg_word_count: int, avg_sentence_length: float, variant: str = "", account_id: int = 0):
        """Auto-set format preferences and language variant in memoire.md."""
        try:
            import re
            from app.memory_manager import get_memory_manager

            # Longueur: concis (<50 words avg), moyen (50-120), detaille (>120)
            if avg_word_count > 0:
                if avg_word_count < 50:
                    longueur = "concis"
                elif avg_word_count > 120:
                    longueur = "detaille"
                else:
                    longueur = "moyen"
            else:
                longueur = "moyen"

            # Vocabulaire: accessible (short sentences <10 words), standard (10-18), elabore (>18)
            if avg_sentence_length > 0:
                if avg_sentence_length < 10:
                    complexite = "accessible"
                elif avg_sentence_length > 18:
                    complexite = "elabore"
                else:
                    complexite = "standard"
            else:
                complexite = "standard"

            # Update memoire.md with format section (per-account if available)
            mm = get_memory_manager(account_id=account_id if account_id > 0 else None)
            content = mm.get_memory()

            format_block = f"- **Longueur préférée**: {longueur}\n- **Vocabulaire**: {complexite}"

            if "## Format" in content:
                content = re.sub(
                    r'(## Format\s*\n).*?(?=\n## |\Z)',
                    f'\\1\n{format_block}\n',
                    content,
                    flags=re.DOTALL,
                )
            else:
                if "## Règles" in content or "## Regles" in content:
                    content = re.sub(
                        r'(\n## R[eè]gles)',
                        f'\n## Format\n\n{format_block}\n\\1',
                        content,
                    )
                else:
                    content += f"\n\n## Format\n\n{format_block}\n"

            # Auto-set language variant in Profil section
            if variant:
                if "**Variante linguistique**" in content:
                    content = re.sub(
                        r'\*\*Variante linguistique\*\*\s*:\s*.*',
                        f'**Variante linguistique**: {variant}',
                        content,
                    )
                elif "## Profil" in content:
                    content = re.sub(
                        r'(## Profil\s*\n)',
                        f'\\1- **Variante linguistique**: {variant}\n',
                        content,
                    )

            # Write memoire.md directly instead of going through
            # ``mm.save_memory(content)``. save_memory → update_memory →
            # _save_to_db which parse_knowledge_markdown's the content and
            # OVERWRITES ``onboarding_results.{profile,knowledge,rules}_json``
            # with the lossy parsed version — wiping the full dicts the
            # orchestrator just stored (user_email, languages, language_variant,
            # primary_language, full signature, tone structure, contacts,
            # contact_rules, general_rules.name/trigger/action).
            # Format metadata is display-only — it belongs in the markdown
            # file, not in the structured DB source of truth.
            try:
                from app.config import KNOWLEDGE_DIR
                knowledge_dir = Path(KNOWLEDGE_DIR)
                knowledge_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(knowledge_dir / "memoire.md", content, encoding="utf-8")
            except Exception as _write_err:
                logger.debug("memoire.md write skipped (non-fatal): %s", _write_err)
            logger.info("Format auto-detected: longueur=%s, vocabulaire=%s, variant=%s (avg_words=%d, avg_sentence=%.1f)",
                        longueur, complexite, variant or "none", avg_word_count, avg_sentence_length)
        except Exception as e:
            logger.debug("Failed to auto-set format preferences: %s", e)

    # Terminal events that should NOT bump the watchdog — emitting them
    # signals the run has reached a final state, so a heartbeat would
    # immediately resurrect a just-cleared entry (and confuse the watchdog
    # into thinking the worker is alive again).
    _TERMINAL_EVENTS = frozenset({"onboarding:learning_completed"})

    def _emit(self, event_name: str, data: dict):
        """Emit a WebSocket event.

        Side effect: if the payload carries an ``onboarding_id`` and the
        event is not terminal, bump the watchdog heartbeat. Every progress
        emission in the pipeline already includes that field, so this single
        hook keeps the watchdog warm through the full _run_analysis pipeline
        without sprinkling explicit bumps in every step.
        """
        if event_name not in self._TERMINAL_EVENTS:
            onboarding_id = data.get("onboarding_id") if isinstance(data, dict) else None
            if isinstance(onboarding_id, int):
                self._bump_heartbeat(onboarding_id)
        try:
            self.emit_event(event_name, data)
        except Exception as e:
            logger.warning("Failed to emit event %s: %s", event_name, e)


def rehydrate_contact_profiles_from_onboarding(account_id: int) -> int:
    """Backfill WritingStyleProfile.contact_profiles from the latest completed
    onboarding_results row.

    Used to repair accounts whose onboarding ran before the lazy-create fix
    shipped (the per-contact editor stayed empty even though KnowledgeAgent
    had correctly detected every contact). Idempotent — update_contact_profile
    merges, so manual edits are preserved.

    Returns the number of contacts newly added to contact_profiles.
    Swallows all errors: this is best-effort backfill, never raise.
    """
    import json as _json

    try:
        from app.db.database import get_db_session, get_session_factory
        from app.db.repositories.onboarding_repository import OnboardingRepository
        from app.infrastructure.container import get_container
    except Exception as e:
        logger.warning("Rehydrate: imports failed for account %s: %s", account_id, e)
        return 0

    try:
        with get_db_session() as session:
            repo = OnboardingRepository(session)
            result = repo.get_completed_by_account(account_id)
            if not result:
                return 0
            knowledge = _json.loads(result.knowledge_json or "{}")
            rules = _json.loads(result.rules_json or "{}")
    except Exception as e:
        logger.warning("Rehydrate: failed to load onboarding_results for account %s: %s", account_id, e)
        return 0

    if not knowledge.get("contacts") and not rules.get("contact_rules"):
        return 0

    try:
        store = get_container().get_writing_style_store()
        before = 0
        existing = store.load(account_id)
        if existing:
            before = len(existing.contact_profiles)

        manager = OnboardingManager(session_factory=get_session_factory())
        manager._persist_contact_profiles(knowledge, rules, account_id)

        after_profile = store.load(account_id)
        after = len(after_profile.contact_profiles) if after_profile else 0
        added = max(0, after - before)
        if added > 0:
            logger.info(
                "Rehydrate: added %d contact profiles for account %s (from onboarding_results)",
                added, account_id,
            )
        return added
    except Exception as e:
        logger.warning("Rehydrate: persist failed for account %s: %s", account_id, e)
        return 0
