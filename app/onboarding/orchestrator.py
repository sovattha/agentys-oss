# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Onboarding orchestrator: runs the 3 analysis agents and aggregates results.

Emits WebSocket progress events during analysis.
"""

import logging
import time
import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.onboarding.agents.profile_agent import ProfileAgent
from app.onboarding.agents.knowledge_agent import KnowledgeAgent
from app.onboarding.agents.style_agent import StyleAgent
from app.onboarding.agents.label_agent import LabelAgent
from app.onboarding.indexer import IndexedEmails

logger = logging.getLogger(__name__)


@dataclass
class OnboardingProgress:
    """Progress state emitted via WebSocket."""
    step: str
    status: str  # "running", "completed", "failed"
    progress: int  # 0-100
    message: str = ""            # Legacy FR string (backward compat)
    message_key: str = ""        # i18n key (preferred by frontend)
    message_params: dict = field(default_factory=dict)  # interpolation args
    error: Optional[str] = None
    error_key: str = ""


@dataclass
class OnboardingDiscovery:
    """A single narrative finding surfaced to the UI during the scan.

    Each discovery maps to an i18n key + params that the frontend renders
    in the rolling DiscoveryFeed. Discoveries are derived from the real
    data an agent extracted — never fabricated — so the user always sees
    something the pipeline actually learned about them.

    ``kind`` drives the visual treatment (icon + weight):
      - ``starting`` : we're about to do X (discreet arrow)
      - ``finding``  : we confirmed X (checkmark, most common)
      - ``insight``  : unexpected/high-signal observation (spark, rare)
    """
    kind: str                                        # starting | finding | insight
    message_key: str                                 # e.g. "onboarding.discovery_signature_found"
    message_params: dict = field(default_factory=dict)
    agent: str = ""                                  # profile | knowledge | style | label
    fallback_message: str = ""                       # FR fallback if frontend can't translate


def _anon_contact_name(raw: str) -> str:
    """Turn a full contact name into a privacy-safe label.

    'Alice Dupont'  -> 'Alice D.'
    'Alice'         -> 'Alice'
    'alice@x.com'   -> 'Alice' (local-part title-cased)
    Empty/None      -> ''
    """
    if not raw:
        return ""
    raw = str(raw).strip()
    if not raw:
        return ""
    # If we were handed an email address, derive from the local part.
    if "@" in raw:
        local = raw.split("@", 1)[0]
        # Split on common email name separators and title-case the first
        # chunk — keeps the wow factor ('Alice') without surfacing the
        # full local part which may contain numbers/hyphens/dots.
        parts = [p for p in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if p]
        return parts[0].capitalize() if parts else ""
    parts = raw.split()
    if len(parts) == 1:
        return parts[0]
    # First name + initial of last name. Accent-safe via slice.
    last_initial = parts[-1][:1].upper()
    return f"{parts[0]} {last_initial}."


_TONE_KEY = {
    "casual": "onboarding.discovery_tone_casual",
    "semi-formal": "onboarding.discovery_tone_semi_formal",
    "semi_formal": "onboarding.discovery_tone_semi_formal",
    "formal": "onboarding.discovery_tone_formal",
}

def _extract_profile_discoveries(result: dict) -> list[OnboardingDiscovery]:
    """Derive narrative findings from a ProfileAgent result.

    Emits only for fields that are truly populated — never sends a
    discovery for ``title = None`` so the UI doesn't show empty strings.
    """
    out: list[OnboardingDiscovery] = []
    if not isinstance(result, dict):
        return out

    sig = result.get("signature") or {}
    if isinstance(sig, dict):
        name = (sig.get("name") or "").strip()
        company = (sig.get("company") or "").strip()
        title = (sig.get("title") or "").strip()
        if name and company:
            out.append(OnboardingDiscovery(
                kind="finding", agent="profile",
                message_key="onboarding.discovery_signature_found",
                message_params={"name": name, "company": company},
                fallback_message=f"Signature détectée : {name} · {company}",
            ))
        elif name:
            out.append(OnboardingDiscovery(
                kind="finding", agent="profile",
                message_key="onboarding.discovery_signature_only_name",
                message_params={"name": name},
                fallback_message=f"Signature détectée : {name}",
            ))
        if title:
            out.append(OnboardingDiscovery(
                kind="finding", agent="profile",
                message_key="onboarding.discovery_signature_title",
                message_params={"title": title},
                fallback_message=f"Poste extrait : {title}",
            ))

    preferred_name = (result.get("preferred_name") or "").strip()
    user_name = (result.get("user_name") or "").strip()
    # Emit a discovery only when the short form differs from the full name —
    # otherwise we'd repeat the signature finding with less information.
    if preferred_name and preferred_name != user_name:
        out.append(OnboardingDiscovery(
            kind="insight", agent="profile",
            message_key="onboarding.discovery_preferred_name",
            message_params={"preferred_name": preferred_name},
            fallback_message=f"Vous signez « {preferred_name} »",
        ))

    tone = result.get("tone") or {}
    if isinstance(tone, dict):
        dt = (tone.get("default_tone") or "").strip().lower()
        tone_key = _TONE_KEY.get(dt)
        if tone_key:
            out.append(OnboardingDiscovery(
                kind="finding", agent="profile",
                message_key=tone_key,
                fallback_message=f"Ton par défaut : {dt}",
            ))

        addressing = (tone.get("addressing") or "").strip().lower()
        if addressing in ("tu", "vous", "mixed"):
            out.append(OnboardingDiscovery(
                kind="insight", agent="profile",
                message_key=f"onboarding.discovery_addressing_{addressing}",
                fallback_message={
                    "tu": "Vous tutoyez la plupart de vos contacts",
                    "vous": "Vous vouvoyez la plupart de vos contacts",
                    "mixed": "Adressage mixte (tu/vous selon les contacts)",
                }[addressing],
            ))

    variant = (result.get("language_variant") or "").strip()
    if variant:
        out.append(OnboardingDiscovery(
            kind="insight", agent="profile",
            message_key="onboarding.discovery_language_variant",
            message_params={"variant": variant},
            fallback_message=f"Variante linguistique : {variant}",
        ))

    langs = result.get("languages") or []
    if isinstance(langs, list) and len(langs) > 1:
        joined = ", ".join(str(lang) for lang in langs if lang)
        if joined:
            out.append(OnboardingDiscovery(
                kind="finding", agent="profile",
                message_key="onboarding.discovery_languages_multi",
                message_params={"langs": joined},
                fallback_message=f"Vous écrivez en {joined}",
            ))
    return out


def _extract_knowledge_discoveries(result: dict) -> list[OnboardingDiscovery]:
    """Derive narrative findings from a KnowledgeAgent result."""
    out: list[OnboardingDiscovery] = []
    if not isinstance(result, dict):
        return out

    contacts = result.get("contacts") or []
    if not isinstance(contacts, list):
        return out

    count = len(contacts)
    if count > 0:
        out.append(OnboardingDiscovery(
            kind="finding", agent="knowledge",
            message_key="onboarding.discovery_contacts_count",
            message_params={"count": count},
            fallback_message=f"{count} contacts récurrents cartographiés",
        ))

    # Top contact by interaction_count — the real headline of the scan.
    ranked = [c for c in contacts if isinstance(c, dict)]
    ranked.sort(key=lambda c: int(c.get("interaction_count") or 0), reverse=True)
    if ranked:
        top = ranked[0]
        threads = int(top.get("interaction_count") or 0)
        anon = _anon_contact_name(top.get("name") or top.get("email") or "")
        if anon and threads > 0:
            out.append(OnboardingDiscovery(
                kind="insight", agent="knowledge",
                message_key="onboarding.discovery_top_contact",
                message_params={"name": anon, "count": threads},
                fallback_message=f"Top contact : {anon} ({threads} threads)",
            ))

    # Language distribution — replacement for the dropped `type` bucket
    # discovery. Uses per-contact ``preferred_language`` which the LLM
    # still extracts (it's a useful, real signal — unlike the sociological
    # `type` classification which was only UI-cosmetic and got removed).
    by_lang: dict[str, int] = {}
    for c in contacts:
        if not isinstance(c, dict):
            continue
        lang = (c.get("preferred_language") or "").strip().lower()
        if lang:
            by_lang[lang] = by_lang.get(lang, 0) + 1
    if len(by_lang) >= 2:
        parts = [f"{n} {lang.upper()}" for lang, n in sorted(by_lang.items(), key=lambda x: -x[1])]
        out.append(OnboardingDiscovery(
            kind="finding", agent="knowledge",
            message_key="onboarding.discovery_contacts_by_language",
            message_params={"distribution": " · ".join(parts)},
            fallback_message=f"Contacts multilingues : {' · '.join(parts)}",
        ))
    return out


def _extract_style_discoveries(result: dict) -> list[OnboardingDiscovery]:
    """Derive narrative findings from a StyleAgent result."""
    out: list[OnboardingDiscovery] = []
    if not isinstance(result, dict):
        return out

    contact_rules = result.get("contact_rules") or []
    general_rules = result.get("general_rules") or []
    total = len(contact_rules) + len(general_rules)
    if total > 0:
        out.append(OnboardingDiscovery(
            kind="finding", agent="style",
            message_key="onboarding.discovery_rules_count",
            message_params={
                "contact_count": len(contact_rules),
                "general_count": len(general_rules),
            },
            fallback_message=f"{len(contact_rules)} règles par contact · {len(general_rules)} générales",
        ))

    # Casual cluster: how many contacts does the user address informally?
    casual_count = sum(
        1 for r in contact_rules
        if isinstance(r, dict) and (r.get("tone") or "").strip().lower() == "casual"
    )
    if casual_count >= 2:
        out.append(OnboardingDiscovery(
            kind="insight", agent="style",
            message_key="onboarding.discovery_first_name_cluster",
            message_params={"count": casual_count},
            fallback_message=f"{casual_count} contacts en tutoiement",
        ))

    # First general rule = standout observed pattern. The LLM already
    # wrote the description in the user's language, so pass it through.
    for rule in general_rules:
        if not isinstance(rule, dict):
            continue
        desc = (rule.get("description") or "").strip()
        if desc:
            out.append(OnboardingDiscovery(
                kind="finding", agent="style",
                message_key="onboarding.discovery_rule_described",
                message_params={"description": desc},
                fallback_message=desc,
            ))
            break
    return out


def _extract_label_discoveries(result: dict) -> list[OnboardingDiscovery]:
    """Derive narrative findings from a LabelAgent result."""
    out: list[OnboardingDiscovery] = []
    if not isinstance(result, dict):
        return out

    stats = result.get("statistics") or {}
    if not isinstance(stats, dict):
        return out

    action = int(stats.get("action") or 0)
    fyi = int(stats.get("fyi") or 0)
    noise = int(stats.get("noise") or 0)
    if (action + fyi + noise) > 0:
        out.append(OnboardingDiscovery(
            kind="finding", agent="label",
            message_key="onboarding.discovery_stats_distribution",
            message_params={"action": action, "fyi": fyi, "noise": noise},
            fallback_message=f"{action}% action · {fyi}% info · {noise}% bruit",
        ))
    return out


def _extract_discoveries(agent_name: str, result: dict) -> list[OnboardingDiscovery]:
    """Dispatch an agent result to its extraction helper.

    Returning an empty list is fine — the orchestrator simply won't emit
    a burst for agents that produced nothing meaningful (e.g. an empty
    inbox corpus)."""
    if agent_name == "profile":
        return _extract_profile_discoveries(result)
    if agent_name == "knowledge":
        return _extract_knowledge_discoveries(result)
    if agent_name == "style":
        return _extract_style_discoveries(result)
    if agent_name == "label":
        return _extract_label_discoveries(result)
    return []


@dataclass
class OnboardingResult:
    """Aggregated result of all three agents."""
    profile: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    label: dict = field(default_factory=dict)
    emails_analysed: int = 0
    duration_seconds: float = 0.0
    status: str = "completed"
    error: Optional[str] = None
    # Detected primary language of the user's sent corpus ("fr" or "en").
    # Propagated into the agent prompts and persisted so downstream consumers
    # (DrafterAgent, ClassifierAgent) can match the user's language.
    primary_language: str = "fr"
    # Machine-readable reasons why the run is ``partial`` even though every
    # agent succeeded. Filled by the orchestrator from each agent's
    # ``_partial``/``_reason`` flags (e.g. ``"no_sent_emails"``,
    # ``"unsupported_language"``). The UI uses these to show a precise
    # banner instead of a generic "partial" warning.
    partial_reasons: list = field(default_factory=list)


class OnboardingOrchestrator:
    """
    Orchestrates the three analysis agents sequentially.

    Emits progress events via a callback function, which can be
    wired to WebSocket emission.
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[OnboardingProgress], None]] = None,
        on_discovery: Optional[Callable[[OnboardingDiscovery], None]] = None,
    ):
        """
        Args:
            on_progress: Optional callback for progress events.
                Signature: (OnboardingProgress) -> None
            on_discovery: Optional callback for discovery events — real
                findings extracted from agent results, streamed to the UI
                as a rolling narrative feed. Signature:
                (OnboardingDiscovery) -> None
        """
        self.on_progress = on_progress or (lambda p: None)
        self.on_discovery = on_discovery or (lambda d: None)

    def run(self, indexed: IndexedEmails, faq_entries: list[dict] | None = None) -> OnboardingResult:
        """
        Run all four agents on the indexed emails in parallel.

        Args:
            indexed: The indexed email corpus.
            faq_entries: Optional pre-scanned FAQ entries from user-provided
                source (website or document). When provided, these replace
                any FAQ the KnowledgeAgent might extract from emails.

        Returns:
            OnboardingResult with aggregated analysis.

        Audit 2026-05-04 (P0.3) : la parallélisation 4 agents Sonnet via
        ThreadPoolExecutor(max_workers=4) — implémentée à la ligne 486
        ci-dessous — délivre déjà la latence ~4× plus rapide que séquentiel.
        Le cache_control: ephemeral est wrappé automatiquement par
        ClaudeAdapter (claude_adapter.py:177) sur tous les system prompts.
        Le partage d'un PRÉFIXE-CORPUS commun aux 4 agents (qui économiserait
        ~60% de tokens input via cache hits) n'est PAS implémenté car les 4
        agents construisent des user prompts structurellement différents
        depuis IndexedEmails (Profile = 15 emails × 1800ch, Style = top 20
        contacts groupés, Knowledge = 40 emails × 400ch + threads, Label =
        folders only). Refactor pour préfixe commun = risque de régression
        sur 6 personas calibrés (cf. docs/onboarding-prompt-engineering.md).
        """
        from app.onboarding.agents.prompts import is_supported_language

        start_time = time.monotonic()
        primary_lang = indexed.primary_language.value
        # OB-03: when the indexer flags the corpus as UNSUPPORTED, we still
        # run the pipeline (English prompt fallback) but propagate a
        # ``unsupported_language`` partial reason so the UI can warn the user
        # that training quality is degraded until we add their language.
        language_unsupported = (
            primary_lang == "unsupported"
            or (primary_lang and not is_supported_language(primary_lang) and primary_lang != "mixed")
        )
        if language_unsupported:
            logger.warning(
                "Onboarding: language %r not in supported set %r — "
                "running on English prompt fallback, run will be marked partial",
                primary_lang, ("fr", "en"),
            )
        result = OnboardingResult(
            emails_analysed=indexed.total_count,
            primary_language=primary_lang,
        )
        logger.info(
            "Onboarding starting: emails=%d, primary_language=%s",
            indexed.total_count, primary_lang,
        )

        agents = {
            "profile": (ProfileAgent(), "Analyse du profil de communication...", "onboarding.scan_phase_profile"),
            "knowledge": (KnowledgeAgent(), "Extraction des connaissances métier...", "onboarding.scan_phase_knowledge"),
            "style": (StyleAgent(), "Extraction du style d'écriture...", "onboarding.scan_phase_style"),
            "label": (LabelAgent(), "Catégorisation des emails reçus...", "onboarding.scan_phase_label"),
        }

        try:
            self._emit(OnboardingProgress(
                step="all", status="running", progress=5,
                message="Lancement des 4 agents en parallèle...",
                message_key="onboarding.scan_phase_launching",
            ))

            completed = 0

            # Emit "running" for all steps BEFORE spawning executor threads,
            # so emissions happen from the main background thread (safer with threading async_mode).
            for name, (agent, msg, msg_key) in agents.items():
                self._emit(OnboardingProgress(
                    step=name, status="running", progress=10,
                    message=msg,
                    message_key=msg_key,
                ))

            # Narrative starting announcements — give the user a concrete
            # sense of what we're about to do, with real counts from the
            # indexed corpus. These show up in the DiscoveryFeed BEFORE
            # any agent completes, filling the initial wait with signal.
            sent_count = indexed.sent_count
            received_count = indexed.received_count
            contact_count = len(indexed.contact_metrics or {})
            self._emit_discovery(OnboardingDiscovery(
                kind="starting", agent="profile",
                message_key="onboarding.discovery_starting_profile",
                message_params={"count": sent_count},
                fallback_message=f"Lecture de {sent_count} emails envoyés...",
            ))
            self._emit_discovery(OnboardingDiscovery(
                kind="starting", agent="knowledge",
                message_key="onboarding.discovery_starting_knowledge",
                message_params={"count": contact_count},
                fallback_message=f"Cartographie de {contact_count} contacts...",
            ))
            self._emit_discovery(OnboardingDiscovery(
                kind="starting", agent="style",
                message_key="onboarding.discovery_starting_style",
                message_params={},
                fallback_message="Extraction des patterns d'écriture...",
            ))
            self._emit_discovery(OnboardingDiscovery(
                kind="starting", agent="label",
                message_key="onboarding.discovery_starting_label",
                message_params={"count": received_count},
                fallback_message=f"Analyse de {received_count} emails reçus...",
            ))

            def _run_agent(name: str):
                agent, _, _ = agents[name]
                from app.infrastructure.llm_attribution import llm_attribution

                with llm_attribution(
                    f"onboarding_{name}",
                    feature="onboarding",
                ):
                    return name, agent.analyse(indexed)

            failed_agents = []

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {}
                for name in agents:
                    ctx = contextvars.copy_context()
                    futures[pool.submit(ctx.run, _run_agent, name)] = name

                for future in as_completed(futures):
                    agent_name = futures[future]
                    try:
                        name, output = future.result()
                    except Exception as agent_err:
                        logger.warning(
                            "Agent %s failed: %s", agent_name, agent_err,
                        )
                        failed_agents.append(agent_name)
                        self._emit(OnboardingProgress(
                            step=agent_name, status="failed", progress=0,
                            message=f"L'agent {agent_name} a échoué.",
                            message_key="onboarding.scan_error_agent_failed",
                            message_params={"agent": agent_name},
                            error=str(agent_err),
                        ))
                        continue

                    setattr(result, name, output)
                    completed += 1
                    progress = round(completed / len(agents) * 100)

                    step_labels = {
                        "profile": ("Profil terminé.", "onboarding.scan_done_profile"),
                        "knowledge": ("Connaissances terminées.", "onboarding.scan_done_knowledge"),
                        "style": ("Style d'écriture terminé.", "onboarding.scan_done_style"),
                        "label": ("Catégorisation terminée.", "onboarding.scan_done_label"),
                    }
                    fallback_msg, fallback_key = step_labels.get(
                        name, (f"{name.capitalize()} terminé.", "onboarding.scan_done_generic")
                    )

                    # Discovery counters — passés via message_params et extraits
                    # par manager.py pour devenir des pills live dans le ScanNarrator.
                    # Cascade naturelle : chaque agent ajoute SON bucket au UI dès
                    # qu'il termine, plutôt que d'attendre la consolidation finale.
                    discovery_params: dict = {}
                    try:
                        if name == "knowledge" and isinstance(output, dict):
                            discovery_params["new_contacts"] = len(output.get("contacts") or [])
                        elif name == "style" and isinstance(output, dict):
                            rules = (output.get("contact_rules") or []) + (output.get("general_rules") or [])
                            discovery_params["new_rules"] = len(rules)
                    except Exception:
                        pass

                    self._emit(OnboardingProgress(
                        step=name, status="completed", progress=progress,
                        message=fallback_msg,
                        message_key=fallback_key,
                        message_params=discovery_params,
                    ))

                    # Narrative findings extracted from the agent's real
                    # output — never fabricated. Empty list = nothing
                    # worth surfacing for this agent (e.g. empty corpus),
                    # no feed entry emitted.
                    try:
                        for d in _extract_discoveries(name, output):
                            self._emit_discovery(d)
                    except Exception as disc_err:
                        logger.debug(
                            "Discovery extraction failed for agent %s: %s",
                            name, disc_err,
                        )

            # OB-02 (audit 2026-04-24): detect "no sent emails" partial via the
            # ``_partial`` flag the ProfileAgent emits when ``_select_sample``
            # returns []. Without this, an account with 0 sent emails completes
            # with a blank profile + empty contact_rules and is marked
            # ``completed`` — the user thinks the AI is trained but every draft
            # downstream is generic. We mark it ``partial`` with a dedicated
            # reason so the UI can show a "we couldn't train on outgoing
            # replies yet — send some emails and retry" banner instead of
            # claiming success.
            partial_reasons: list[str] = []
            if isinstance(result.profile, dict) and result.profile.get("_partial"):
                reason = str(result.profile.get("_reason") or "no_sent_emails")
                partial_reasons.append(reason)
            elif isinstance(result.profile, dict) and not result.profile.get("user_name", "").strip():
                # P1-014: agent returned without _partial flag but with a blank
                # user_name — treat as partial so the run isn't silently marked
                # "completed" with a generic, untrained profile.
                if "empty_profile" not in partial_reasons:
                    partial_reasons.append("empty_profile")

            # OB-C-3 (audit 2026-04-25 onboarding-flawless): surface the
            # _partial flags now emitted by knowledge / style / label
            # agents when their retries exhaust with empty outputs. Pre-fix
            # those agents silently returned empty defaults and onboarding
            # was marked completed despite zero personalised content.
            for agent_name, agent_result in (
                ("knowledge", result.knowledge),
                ("style", result.style),
                ("label", result.label),
            ):
                if isinstance(agent_result, dict) and agent_result.get("_partial"):
                    reason = str(agent_result.get("_reason") or f"empty_{agent_name}")
                    if reason not in partial_reasons:
                        partial_reasons.append(reason)

            # OB-03: surface unsupported-language flag from the indexer.
            if language_unsupported:
                partial_reasons.append("unsupported_language")

            if failed_agents:
                if completed == 0:
                    result.status = "failed"
                    result.error = "L'analyse a échoué. Veuillez réessayer."
                    err_key = "onboarding.scan_error_generic"
                    err_params = {}
                else:
                    result.status = "partial"
                    result.error = f"Analyse partielle : {', '.join(failed_agents)} en échec."
                    err_key = "onboarding.scan_error_partial"
                    err_params = {"agents": ", ".join(failed_agents)}
                self._emit(OnboardingProgress(
                    step="error", status="failed" if completed == 0 else "partial",
                    progress=round(completed / len(agents) * 100),
                    message=result.error, error=result.error,
                    message_key=err_key, error_key=err_key,
                    message_params=err_params,
                ))
            elif partial_reasons:
                # No agent crashed but the pipeline flagged the run as
                # under-trained (zero sent emails, or unsupported language).
                # Surface this explicitly so the user gets the truth instead
                # of a green "completed" badge over a blank profile. Frontend
                # matches on ``partial_reasons`` to show the appropriate
                # banner.
                result.status = "partial"
                # Prioritise the most actionable reason for the legacy
                # ``message`` field; the frontend can still read the full
                # list from ``partial_reasons``.
                if "no_sent_emails" in partial_reasons:
                    result.error = (
                        "Aucun email envoyé n'a été trouvé : nous n'avons pas pu apprendre "
                        "votre style. Envoyez quelques emails et relancez l'entraînement "
                        "depuis les Réglages."
                    )
                    err_key = "onboarding.scan_partial_no_sent"
                elif "unsupported_language" in partial_reasons:
                    result.error = (
                        f"La langue détectée ({primary_lang}) n'est pas encore prise en charge. "
                        "L'analyse a été lancée en anglais : la qualité des suggestions sera "
                        "réduite jusqu'à ce qu'une variante de prompts soit ajoutée."
                    )
                    err_key = "onboarding.scan_partial_unsupported_language"
                else:
                    result.error = "Analyse partielle : données insuffisantes."
                    err_key = "onboarding.scan_partial_insufficient_data"
                self._emit(OnboardingProgress(
                    step="error", status="partial",
                    progress=round(completed / len(agents) * 100),
                    message=result.error, error=result.error,
                    message_key=err_key, error_key=err_key,
                    message_params={
                        "reasons": ",".join(partial_reasons),
                        "language": primary_lang,
                    },
                ))
            else:
                result.status = "completed"

            # Expose the partial reasons on the result so the manager can
            # propagate them in the WebSocket completion payload + persist
            # them in OnboardingResult.error_message for /insights consumers.
            if partial_reasons and not result.error:
                result.error = ",".join(partial_reasons)
            result.partial_reasons = partial_reasons

        except Exception as e:
            logger.error("Onboarding orchestrator failed: %s", str(e), exc_info=True)
            result.status = "failed"

            from app.domain.exceptions import LLMTimeoutError
            if isinstance(e, LLMTimeoutError):
                user_msg = "L'analyse a pris trop de temps. Réessayez avec moins d'emails ou vérifiez votre connexion."
                user_msg_key = "onboarding.scan_error_timeout"
            else:
                user_msg = "L'analyse a échoué. Veuillez réessayer."
                user_msg_key = "onboarding.scan_error_generic"
            result.error = user_msg

            self._emit(OnboardingProgress(
                step="error", status="failed", progress=0,
                message=user_msg, error=user_msg,
                message_key=user_msg_key, error_key=user_msg_key,
            ))

        result.duration_seconds = round(time.monotonic() - start_time, 2)

        # Inject user-provided FAQ entries into the knowledge result.
        # These come from the pre-scan step (website or document) and replace
        # any AI-guessed FAQ from the KnowledgeAgent.
        if faq_entries:
            formatted_faq = []
            for entry in faq_entries:
                if isinstance(entry, dict) and entry.get("question") and entry.get("answer"):
                    formatted_faq.append({
                        "question": entry["question"],
                        "answer": entry["answer"],
                        "category": "FAQ",
                        "context": entry.get("context", ""),
                    })
            result.knowledge["faq"] = formatted_faq
            logger.info(
                "Injected %d user-provided FAQ entries (replaced AI-guessed FAQ)",
                len(formatted_faq),
            )

        # Initial onboarding intentionally produces NO projects: the
        # KnowledgeAgent prompt forbids them, but we also actively scrub
        # any leakage here so that downstream consumers (memoire.md,
        # suggested_labels, LearningInsights, ScanNarrator chips) never
        # surface auto-detected projects. Refresh paths are unaffected —
        # they instantiate KnowledgeAgent directly without this orchestrator.
        if isinstance(result.knowledge, dict):
            result.knowledge["projects"] = []

        # Surface the detected primary language on the profile dict so
        # downstream consumers (drafter, classifier, UI) have a single
        # source of truth without having to re-run detection.
        if isinstance(result.profile, dict):
            result.profile.setdefault("primary_language", primary_lang)

        logger.info(
            "Onboarding complete: status=%s, emails=%d, duration=%.1fs",
            result.status, result.emails_analysed, result.duration_seconds,
        )
        return result

    def _emit(self, progress: OnboardingProgress) -> None:
        """Emit a progress event."""
        try:
            self.on_progress(progress)
        except Exception as e:
            logger.warning("Failed to emit progress event: %s", e)

    def _emit_discovery(self, discovery: OnboardingDiscovery) -> None:
        """Emit a discovery (narrative finding) event.

        Never raises — a broken discovery pipeline must not crash the
        underlying agent pipeline. Worst case we just miss a UI wow
        moment, the analysis still completes.
        """
        try:
            self.on_discovery(discovery)
        except Exception as e:
            logger.warning("Failed to emit discovery event: %s", e)
