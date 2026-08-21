# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Agents IA pour le pipeline de réponses emails.

Ce module sert de façade pour la Clean Architecture.
Il expose une API stable tout en déléguant aux use cases internes.

Agents disponibles :
- DrafterAgent : Génère des réponses professionnelles
- CriticAgent : Audite et valide les réponses
- PrioritizationAgent : Analyse la priorité des emails

Supporte plusieurs providers LLM (Claude, Ollama) via la variable LLM_PROVIDER.
"""

import logging as _logging
import re as _re
import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, List

_logger = _logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.domain.entities.anonymization import AnonymizedResult
    from app.domain.ports.encryption import EncryptionPort

from app.config import (
    MODEL_DEFAULT,
    CLAUDE_MODEL_LABEL,
    MAX_TOKENS_DRAFT,
    MAX_TOKENS_DRAFT_RETRY,
    adaptive_draft_max_tokens,
    MAX_TOKENS_CRITIC,
    MAX_TOKENS_PRIORITIZATION,
    MAX_TOKENS_CLASSIFICATION,
    MAX_TOKENS_COMMITMENT_EXTRACTION,
    MAX_TOKENS_CONTACT_SUMMARY,
)
from app.infrastructure.container import get_container
from app.domain.entities import TokenUsage
from app.domain.entities.draft_generation import (
    DraftTone,
    DraftStatus,
    DraftRequest,
    DraftResult,
    StreamingDraftChunk,
)
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueStatus,
    CritiqueScores,
    CritiqueRequest,
    CritiqueResult,
    ToneResult,
)
from typing import Generator
from app.domain.entities.sensitive_data import (
    SensitiveDataDetection,
    SensitiveDataItem,
    SensitiveDataType,
)
from app.domain.ports import LLMPort


# Markers a draft should NEVER ship with — drives a deterministic REJECT in
# CriticAgent regardless of the LLM's own decision field. Kept in sync with
# the post-LLM strip layer's triggers (`app/smart_routing.py:_BARE_PLACEHOLDER_TRIGGER_RE`).
# Audit 2026-05-04 ground-truth eval: 5/15 bad drafts had placeholders that
# Haiku Critic was scoring 75-85 overall, missing the safety hole entirely.
_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "[À confirmer]", "[à confirmer]", "[A confirmer]", "[a confirmer]",
    "[à valider]", "[a valider]", "[À valider]",
    "[à vérifier]", "[a verifier]", "[À vérifier]",
    # Audit S-05 (2026-05-11): `[À définir]` was missing from the watchlist
    # despite being emitted by `manager.build_knowledge_markdown` when
    # onboarding fields are empty. User explicitly demanded zero injection
    # of "à définir", "à confirmer", "TBD".
    "[À définir]", "[à définir]", "[A definir]", "[a definir]",
    "[TBD]", "[tbd]", "[REDACTE]", "[redacte]",
    "[placeholder", "[X]",
)


def _draft_has_placeholder(draft: str) -> bool:
    """True iff the draft contains any of the placeholder markers above."""
    if not draft:
        return False
    return any(m in draft for m in _PLACEHOLDER_MARKERS)
from app.prompts import (
    load_knowledge_base,
    get_drafter_system_prompt,
    get_drafter_system_prompt_with_style,
    get_drafter_system_prompt_with_history_split,
    get_drafter_system_segments_with_history,
    get_drafter_system_prompt_with_context_split,
    get_drafter_user_prompt,
    get_drafter_user_prompt_with_context,
    get_drafter_correction_prompt,
    get_critic_system_prompt,
    get_critic_user_prompt,
    get_critic_structured_system_segments,
    get_critic_structured_user_prompt,
    analyze_email_formality,
    formality_to_temperature,
)
from app.utils.json_parser import extract_json_from_response


# ============================================================================
# COMPTEUR DE TOKENS (Façade pour TokenUsage du domaine)
# ============================================================================

# Alias pour backward compatibility
TokenCounter = TokenUsage

# Re-export MODEL_COSTS pour backward compatibility
from app.domain.entities.token_usage import MODEL_COSTS  # noqa: F401,E402


def _get_token_usage() -> TokenUsage:
    """Retourne le compteur de tokens partagé du Container."""
    return get_container().token_usage


def _response_token_int(value) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _track_token_usage(response) -> None:
    """Record token usage from an LLM response.

    Reads the active ``(agent, account_id)`` from the LLM-attribution context
    (cf. :mod:`app.infrastructure.llm_attribution`) so the TokenCounter
    adapter records a per-agent breakdown — answering "how much did the
    drafter cost vs the onboarding pipeline?" instead of one opaque total.

    Audit 2026-05-05: pre-fix, every completion landed in the single global
    counter with no agent dimension. The ``LegacyTokenCounterAdapter``
    already supports ``add(..., agent=)`` and ``get_breakdown_by_agent()``;
    this is the missing wiring.

    Best-effort on attribution: if ``llm_attribution`` was never set, the
    call still records (under ``agent="unknown"``) so we never lose tokens.
    """
    try:
        from app.infrastructure.llm_attribution import current_agent, current_account_id
        agent = current_agent()
        account_id = current_account_id()
    except Exception:  # pragma: no cover — never break tracking on import error
        agent = "unknown"
        account_id = None

    container = get_container()
    input_tokens = _response_token_int(getattr(response, "input_tokens", 0))
    output_tokens = _response_token_int(getattr(response, "output_tokens", 0))
    cache_read_tokens = _response_token_int(getattr(response, "cache_read_input_tokens", 0))
    cache_creation_tokens = _response_token_int(getattr(response, "cache_creation_input_tokens", 0))
    model = getattr(response, "model", "") or ""

    # Domain TokenUsage (back-compat — keeps the existing global counter).
    container.token_usage.add(
        input_tokens,
        output_tokens,
        model,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    # Per-agent breakdown adapter (was dead code in prod pre-2026-05-05).
    try:
        adapter = container.token_counter
        if adapter is not None:
            adapter.add(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model,
                agent=agent,
            )
    except Exception as _e:  # pragma: no cover — telemetry must never break call
        _logger.debug("token_counter adapter add failed: %s", _e)
    # Persistent SQLite log (audit 2026-05-06): async writer keeps the
    # LLM hot path uncoupled from DB latency. Cost is computed here from
    # the canonical MODEL_COSTS table so historical rollups stay stable
    # if Anthropic prices change later.
    if not getattr(response, "usage_recorded", False):
        try:
            from app.infrastructure.token_usage_writer import record_usage

            record_usage(
                account_id=account_id,
                agent=agent,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_tokens,
                cache_read_input_tokens=cache_read_tokens,
            )
        except Exception as _e:  # pragma: no cover — telemetry never breaks
            _logger.debug("token_usage_writer enqueue failed: %s", _e)
    # Structured log for sentinels / log-based analytics. The keys here are
    # part of the public observability contract — sentinel parsers depend
    # on them. Don't rename without updating the consumers.
    _logger.info(
        "[TOKEN_USAGE] agent=%s account=%s model=%s in=%d out=%d",
        agent,
        account_id if account_id is not None else "-",
        getattr(response, "model", "?"),
        input_tokens,
        output_tokens,
    )


# Instance globale du compteur (via Container)
token_counter = _get_token_usage()


def _attribute_to_agent(method):
    """Decorator: set the LLM-attribution context for the wrapped method.

    Reads ``self._agent_label`` (default ``"unknown"``) and ``self.account_id``
    (default None) and pushes them onto the contextvars stack for the
    duration of the call. Any LLM completions inside the call — including
    nested helper methods — see the right ``(agent, account_id)`` tuple
    when they call ``_track_token_usage``.

    Idempotent and nesting-safe: an inner method wrapped with the same
    decorator simply re-asserts the context, and on exit restores the
    outer values.
    """
    from functools import wraps

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        from app.infrastructure.llm_attribution import llm_attribution
        agent_label = getattr(self, "_agent_label", "unknown") or "unknown"
        account_id = getattr(self, "account_id", None)
        with llm_attribution(agent_label, account_id=account_id):
            return method(self, *args, **kwargs)

    return wrapper


# ============================================================================
# DRAFTER AGENT
# ============================================================================

@dataclass
class DrafterAgent:
    """
    Agent responsable de la rédaction des réponses emails.

    Utilise la base de connaissances pour générer des réponses
    cohérentes avec le contexte de l'entreprise.

    Cette classe est une façade qui délègue au LLM adapter du Container.
    """
    max_tokens: int = MAX_TOKENS_DRAFT
    knowledge_base: str = ""
    account_id: Optional[int] = None
    timeout_seconds: int = 120  # AC3: Timeout configurable (increased to 120s for complex drafts)
    max_retries: int = 3  # AC5: Maximum retry attempts for rate limiting
    _llm: Optional[LLMPort] = field(default=None, repr=False)
    # Agent label for the LLM-attribution telemetry (cf.
    # app.infrastructure.llm_attribution). Subclasses (CriticAgent…) override
    # this so per-agent cost breakdown is correct.
    _agent_label: str = field(default="drafter", repr=False)

    def __post_init__(self):
        if not self.knowledge_base:
            self.knowledge_base = self._resolve_knowledge()
        # Cost-optimized: Haiku for all drafts ($0.003 vs $0.018 Sonnet)
        # Routes to ANTHROPIC_API_KEY_DRAFTING for per-category cost tracking.
        self._llm = get_container().llm_drafting
        # Audit defense (A4): a caller that constructs DrafterAgent with
        # max_tokens >= MAX_TOKENS_DRAFT_RETRY silently disables the
        # retry-on-truncation path in `draft()` — the retry condition is
        # `stop_reason == "max_tokens" and self.max_tokens < retry_ceiling`.
        # Surface intent at construction so an accidental override is visible
        # in startup logs instead of hiding behind a silent truncation.
        if self.max_tokens >= MAX_TOKENS_DRAFT_RETRY:
            _logger.info(
                "DrafterAgent: max_tokens=%d >= retry ceiling %d — "
                "retry-on-truncation will be a no-op for this instance.",
                self.max_tokens, MAX_TOKENS_DRAFT_RETRY,
            )

    @property
    def model(self) -> str:
        """Name of the LLM model actually used at runtime.

        Reads from the bound LLM port (`Container.llm_drafting`), not from a
        cosmetic dataclass default. Until 2026-05-04 this was a `str` field
        defaulting to `MODEL_DEFAULT` (= `LLM_MODEL` env var, typically
        Sonnet) — which silently lied: at runtime `__post_init__` always
        overrides `_llm` with the categorized "label" tier (Haiku 4.5).
        Eval `tasks/eval-critic-haiku-vs-sonnet-verdict-2026-05-04.md` shows
        the honest property is the only safe surface for downstream
        readers (telemetry, eval harnesses, audit reports).
        """
        if self._llm is None:
            return ""
        return getattr(self._llm, "model", "")

    def _resolve_knowledge(self) -> str:
        """DB-first knowledge loading.

        When ``account_id`` is set (web / multi-tenant), a DB miss returns ""
        — we do NOT fall back to the process-global ``memoire.md``, which
        holds another tenant's knowledge base and would leak it into this
        draft (audit 2026-05-29). Only the no-account case (Tauri desktop
        single-user) reads the global file.
        """
        if self.account_id:
            from app.prompts import load_knowledge_from_db
            kb = load_knowledge_from_db(self.account_id)
            if kb:
                return kb
            return ""
        return load_knowledge_base()

    def _resolve_contact_summary(
        self,
        conversation_history: Optional[list[dict]],
        user_email: str,
    ) -> Optional[dict]:
        """Best-effort fetch of the pre-computed contact summary.

        Returns None on any failure so callers always fall back to the
        2-email history already present in the system prompt.
        """
        try:
            from app.config import USE_CONTACT_SUMMARY
            if not USE_CONTACT_SUMMARY:
                return None
            if not conversation_history:
                return None
            account_id = self.account_id
            if account_id is None:
                try:
                    from app.multi_accounts import get_current_account
                    from app.api.routes_helpers import _resolve_account_id_for_email
                    acct = get_current_account()
                    if acct and getattr(acct, "email", None):
                        account_id = _resolve_account_id_for_email(acct.email)
                        if not user_email:
                            user_email = acct.email or ""
                except Exception:
                    account_id = None
            if account_id is None:
                return None

            contact_email = ""
            for h in conversation_history:
                s = (h.get("sender") or "").lower()
                if s and s != (user_email or "").lower():
                    contact_email = s
                    break
            if not contact_email:
                return None

            from app.services.contact_summary_service import get_summary_for_prompt
            return get_summary_for_prompt(
                account_id=account_id,
                contact_email=contact_email,
                user_email=user_email,
            )
        except Exception as e:
            _logger.debug(f"DrafterAgent: contact summary resolve failed: {e}")
            return None

    def _resolve_recipient_profile(self, request: "DraftRequest"):
        """Best-effort lookup of the persisted DISC profile for the recipient.

        Returns None on any failure — caller should not guard separately
        because ``to_prompt_block()`` also returns "" for unreliable profiles.
        """
        try:
            account_id = request.account_id or self.account_id
            if account_id is None:
                try:
                    from app.multi_accounts import get_current_account
                    from app.api.routes_helpers import _resolve_account_id_for_email
                    acct = get_current_account()
                    if acct and getattr(acct, "email", None):
                        account_id = _resolve_account_id_for_email(acct.email)
                except Exception:
                    account_id = None
            if account_id is None:
                return None

            recipient_email = (request.recipient_email or "").lower()
            if not recipient_email and request.conversation_history:
                user_email = (getattr(request, "user_email", "") or "").lower()
                for h in request.conversation_history:
                    s = (h.get("sender") or "").lower()
                    if s and s != user_email:
                        recipient_email = s
                        break
            if not recipient_email:
                return None

            from app.db.database import get_db_session
            from app.db.repositories.recipient_profile_repository import (
                RecipientProfileRepository,
            )
            with get_db_session() as session:
                repo = RecipientProfileRepository(session)
                return repo.get(int(account_id), recipient_email)
        except Exception as e:
            _logger.debug(f"DrafterAgent: recipient profile resolve failed: {e}")
            return None

    @_attribute_to_agent
    def draft(
        self,
        email_content: str,
        style_context: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
        instructions: str = "",
        user_email: str = "",
    ) -> str:
        """
        Génère une première version de réponse à un email.

        Args:
            email_content: Le contenu de l'email reçu.
            style_context: Contexte de style optionnel (Story 4-4).
                           Si fourni, utilise le prompt avec adaptation de style.
            conversation_history: Historique réduit (2 emails récents) avec le contact.
            instructions: Instructions explicites de l'utilisateur (Reply Composer AI prompt).
            user_email: Adresse email de l'utilisateur (pour few-shot examples).

        Returns:
            La réponse rédigée.
        """
        contact_summary = self._resolve_contact_summary(conversation_history, user_email)

        # Choisir le system prompt selon les paramètres disponibles.
        # Multi-block mode (2026-05-05, behind ENABLE_MULTI_BLOCK_CACHE flag)
        # splits the system into 3 cacheable segments (persona | KB | contact
        # context). When OFF, falls back to the legacy single-string
        # _split builder. Both produce equivalent prompts — only the cache
        # structure differs.
        from app.config import ENABLE_MULTI_BLOCK_CACHE
        dynamic_prefix = ""
        system_prompt: object  # str | list[SystemSegment]
        if conversation_history:
            if ENABLE_MULTI_BLOCK_CACHE:
                system_prompt, dynamic_prefix = get_drafter_system_segments_with_history(
                    self.knowledge_base, conversation_history,
                    user_email=user_email, contact_summary=contact_summary,
                    account_id=self.account_id,
                )
            else:
                system_prompt, dynamic_prefix = get_drafter_system_prompt_with_history_split(
                    self.knowledge_base, conversation_history,
                    user_email=user_email, contact_summary=contact_summary,
                    account_id=self.account_id,
                )
        elif style_context:
            system_prompt = get_drafter_system_prompt_with_style(
                self.knowledge_base, style_context
            )
        else:
            system_prompt = get_drafter_system_prompt(self.knowledge_base)

        user_prompt = get_drafter_user_prompt(email_content, instructions=instructions)
        if dynamic_prefix:
            user_prompt = f"{dynamic_prefix}\n\n{user_prompt}"

        # Adaptive temperature based on email formality
        formality = analyze_email_formality(email_content)
        temperature = formality_to_temperature(formality)

        # Tu/vous mirror — non-negotiable. We split the reinforcement by register:
        #   formality == 1 → message à un ami (entre proches, format SMS)
        #   formality == 2 → tutoiement professionnel (consultants, freelances)
        # Pre-fix this block fired identically for both (`<= 2`), forcing
        # 1-3 line replies on professional tutoiement threads.
        if formality == 1:
            user_prompt += (
                "\n\n⚠️ ATTENTION — EMAIL TRÈS INFORMEL (entre amis/proches) :\n"
                "- Réponds comme un ami répondrait par message, PAS comme un employé de bureau.\n"
                "- PAS de \"Bonjour\", PAS de \"Cordialement\", PAS de formules.\n"
                "- Phrases courtes et naturelles. 1-3 lignes MAX.\n"
                "- Tutoiement obligatoire. Ton décontracté.\n"
                "- Exemple : \"salut mon pote, comment ca va?\" → \"Ça va et toi?\"\n"
                "- Exemple : \"hey t'es dispo ce soir?\" → \"Oui, on fait quoi?\"\n"
            )
        elif formality == 2:
            user_prompt += (
                "\n\n⚠️ TUTOIEMENT OBLIGATOIRE — le contact emploie 'tu' (ou 'ton/ta/tes/te/toi') :\n"
                "- TOUTE ta réponse doit être au tutoiement. Aucun 'vous', 'votre', 'vos'.\n"
                "- Si tu hésites, choisis 'tu' — jamais 'vous'.\n"
                "- Salutation casual permise (\"Salut Prénom,\") mais le corps reste pro.\n"
                "- Pas d'argot ni d'emojis : c'est du tutoiement professionnel, pas un SMS entre amis.\n"
            )

        # B4-lite: if the caller is using the default budget (constructor
        # default == MAX_TOKENS_DRAFT), apply the adaptive tier based on
        # incoming body length. Callers passing a custom max_tokens (e.g.
        # SmartRouter._generate_complex with max_tokens=768/800) win — we
        # only adapt when the agent is at the default budget so we don't
        # surprise callers that intentionally requested headroom.
        _effective_max_tokens = self.max_tokens
        if self.max_tokens == MAX_TOKENS_DRAFT:
            _effective_max_tokens = adaptive_draft_max_tokens(len(email_content or ""))

        response = self._llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=_effective_max_tokens,
            temperature=temperature,
        )
        _track_token_usage(response)

        # Retry-on-truncation: when the trimmed budget (default 600 tokens)
        # cuts off a legitimately long reply, retry once at MAX_TOKENS_DRAFT_RETRY.
        # Skipped if the agent is already configured at or above the retry
        # ceiling (caller wants a one-shot bigger budget) or the adapter does
        # not surface stop_reason (Ollama legacy paths return "").
        if (
            response.stop_reason == "max_tokens"
            and _effective_max_tokens < MAX_TOKENS_DRAFT_RETRY
        ):
            _logger.info(
                "DrafterAgent.draft: truncation detected at %d tokens, retrying at %d",
                _effective_max_tokens, MAX_TOKENS_DRAFT_RETRY,
            )
            response = self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=MAX_TOKENS_DRAFT_RETRY,
                temperature=temperature,
            )
            _track_token_usage(response)

        return response.content

    def revise(
        self,
        email_content: str,
        critique: str,
        style_context: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
        user_email: str = "",
    ) -> str:
        """
        Génère une version corrigée basée sur la critique.

        Args:
            email_content: Le contenu de l'email original.
            critique: La critique de la version précédente.
            style_context: Contexte de style optionnel (Story 4-4).
            conversation_history: Historique des 20 derniers échanges avec le contact.
            user_email: Adresse email de l'utilisateur (pour few-shot examples).

        Returns:
            La réponse corrigée.
        """
        contact_summary = self._resolve_contact_summary(conversation_history, user_email)

        # Variante _split : bloc system statique + historique dans le message utilisateur.
        dynamic_prefix = ""
        if conversation_history:
            system_prompt, dynamic_prefix = get_drafter_system_prompt_with_history_split(
                self.knowledge_base, conversation_history,
                user_email=user_email, contact_summary=contact_summary,
                account_id=self.account_id,
            )
        elif style_context:
            system_prompt = get_drafter_system_prompt_with_style(
                self.knowledge_base, style_context
            )
        else:
            system_prompt = get_drafter_system_prompt(self.knowledge_base)

        correction_prompt = get_drafter_correction_prompt(email_content, critique)
        if dynamic_prefix:
            correction_prompt = f"{dynamic_prefix}\n\n{correction_prompt}"

        # Adaptive temperature
        formality = analyze_email_formality(email_content)
        temperature = formality_to_temperature(formality)

        # Tu/vous mirror — split by register (1 = SMS, 2 = tutoiement pro).
        if formality == 1:
            correction_prompt += (
                "\n\n⚠️ ATTENTION — EMAIL TRÈS INFORMEL (entre amis/proches) :\n"
                "- Réponds comme un ami répondrait par message, PAS comme un employé de bureau.\n"
                "- PAS de \"Bonjour\", PAS de \"Cordialement\", PAS de formules.\n"
                "- Phrases courtes et naturelles. 1-3 lignes MAX.\n"
                "- Tutoiement obligatoire. Ton décontracté.\n"
            )
        elif formality == 2:
            correction_prompt += (
                "\n\n⚠️ TUTOIEMENT OBLIGATOIRE — le contact emploie 'tu' (ou 'ton/ta/tes/te/toi') :\n"
                "- TOUTE ta réponse doit être au tutoiement. Aucun 'vous', 'votre', 'vos'.\n"
                "- Si tu hésites, choisis 'tu' — jamais 'vous'.\n"
                "- Salutation casual permise (\"Salut Prénom,\") mais le corps reste pro.\n"
                "- Pas d'argot ni d'emojis : c'est du tutoiement professionnel, pas un SMS entre amis.\n"
            )

        response = self._llm.complete(
            system=system_prompt,
            user=correction_prompt,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )
        _track_token_usage(response)
        return response.content

    def draft_unified(
        self,
        email_content: str,
        conversation_history: Optional[list[dict]] = None,
        instructions: str = "",
        user_email: str = "",
        thread_context: Optional[list[dict]] = None,
    ) -> dict:
        """
        Pipeline unifié : classification + draft + self-critique en 1 seul appel LLM.

        Réduit 4-5 appels à 1 seul. Retourne un dict avec :
        - classification: "Action"|"FYI"|"Noise"
        - priority: 0-100
        - draft: le brouillon final (auto-vérifié)

        Fallback : si le JSON est invalide, retourne un draft brut avec classification "Action".
        """
        from app.prompts import (
            get_unified_draft_system_prompt,
            get_unified_draft_user_prompt,
        )

        system_prompt = get_unified_draft_system_prompt(
            self.knowledge_base,
            conversation_history=conversation_history,
            user_email=user_email,
            thread_context=thread_context,
        )
        user_prompt = get_unified_draft_user_prompt(
            email_content,
            instructions=instructions,
            conversation_history=conversation_history,
            user_email=user_email,
        )

        formality = analyze_email_formality(email_content)
        temperature = formality_to_temperature(formality)

        # Tu/vous mirror — split by register (1 = SMS, 2 = tutoiement pro).
        if formality == 1:
            user_prompt += (
                "\n\n⚠️ ATTENTION — EMAIL TRÈS INFORMEL (entre amis/proches) :\n"
                "- Le draft doit être une réponse d'ami, PAS une réponse professionnelle.\n"
                "- PAS de \"Bonjour\", PAS de \"Cordialement\", PAS de formules.\n"
                "- Phrases courtes et naturelles. 1-3 lignes MAX dans le champ draft.\n"
                "- Tutoiement obligatoire. Ton décontracté.\n"
            )
        elif formality == 2:
            user_prompt += (
                "\n\n⚠️ TUTOIEMENT OBLIGATOIRE — le contact emploie 'tu' (ou 'ton/ta/tes/te/toi') :\n"
                "- TOUTE ta réponse doit être au tutoiement. Aucun 'vous', 'votre', 'vos'.\n"
                "- Si tu hésites, choisis 'tu' — jamais 'vous'.\n"
                "- Salutation casual permise (\"Salut Prénom,\") mais le corps reste pro.\n"
                "- Pas d'argot ni d'emojis : c'est du tutoiement professionnel, pas un SMS entre amis.\n"
            )

        response = self._llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )
        _track_token_usage(response)

        # Parse JSON response
        raw = response.content.strip()
        try:
            result = extract_json_from_response(raw)
            if isinstance(result, dict) and "draft" in result:
                # Validate classification
                classification = result.get("classification", "Action")
                if classification not in ("Action", "FYI", "Noise"):
                    classification = "Action"
                # Guard: un email avec une question directe ne peut jamais être Noise
                if classification == "Noise" and "?" in email_content:
                    _logger.info("Classification Noise → Action (question détectée dans le corps)")
                    classification = "Action"
                return {
                    "classification": classification,
                    "classification_reason": result.get("classification_reason", ""),
                    "priority": max(0, min(100, int(result.get("priority", 50)))),
                    "draft": result["draft"],
                    "status": "UNIFIED",
                }
        except Exception as e:
            _logger.warning(f"Unified draft JSON parse failed: {e}, using raw content")

        # Fallback: raw content as draft.
        # Audit DP-failure-mode #2 (2026-04-24): a malformed Claude response can
        # leave `raw` containing JSON braces / reasoning leakage / empty string.
        # Persisting that to PendingDraft surfaces garbage to the user. We
        # validate non-emptiness AND reject content that's mostly JSON
        # structure (`{`, `}`, `"draft":`) which would never look like a
        # polite reply.
        _draft_candidate = (raw or "").strip()
        _looks_like_json = (
            _draft_candidate.startswith("{")
            or _draft_candidate.endswith("}")
            or '"draft":' in _draft_candidate[:200]
            or '"classification":' in _draft_candidate[:200]
        )
        if not _draft_candidate or _looks_like_json:
            _logger.warning(
                "Unified draft fallback: raw content rejected "
                f"(empty={not _draft_candidate}, json_like={_looks_like_json})"
            )
            return {
                "classification": "Action",
                "priority": 50,
                "draft": "",
                "status": "UNIFIED_FALLBACK_EMPTY",
            }

        return {
            "classification": "Action",
            "priority": 50,
            "draft": _draft_candidate,
            "status": "UNIFIED_FALLBACK",
        }

    def draft_with_context(self, request: DraftRequest) -> DraftResult:
        """
        Génère une réponse email avec contexte complet (Story 5-1).

        Utilise le ContextAnalysisResult pour enrichir la génération
        avec les informations de relation et de style.

        Args:
            request: DraftRequest contenant email_content, context_result, etc.

        Returns:
            DraftResult avec le brouillon généré et les métriques.
        """
        start_time = _time.time()

        # Extraire les informations de contexte
        contact_context = ""
        relationship_type = "unknown"
        style_hints: list[str] = []
        context_used = False

        if request.context_result:
            context_used = True
            contact_context = request.context_result.contact_context
            relationship_type = request.context_result.relationship_type.value
            style_hints = request.context_result.style_hints

        # Ajouter les style_hints du request si présents
        if request.get_style_hints():
            style_hints = list(set(style_hints + request.get_style_hints()))

        # Construire les prompts (avec few-shot examples + user formulas)
        user_email = getattr(request, "user_email", "") or ""
        contact_summary = self._resolve_contact_summary(
            request.conversation_history, user_email
        )
        recipient_profile = self._resolve_recipient_profile(request)
        system_prompt, dynamic_prefix = get_drafter_system_prompt_with_context_split(
            knowledge_base=self.knowledge_base,
            style_context=request.style_context or "",
            contact_context=contact_context,
            relationship_type=relationship_type,
            style_hints=style_hints,
            conversation_history=request.conversation_history,
            user_email=user_email,
            thread_context=getattr(request, "thread_context", None),
            contact_summary=contact_summary,
            recipient_profile=recipient_profile,
            account_id=self.account_id,
        )

        user_prompt = get_drafter_user_prompt_with_context(
            email_content=request.email_content,
            instructions=request.instructions,
        )
        if dynamic_prefix:
            user_prompt = f"{dynamic_prefix}\n\n{user_prompt}"

        # Adaptive temperature based on email formality
        formality = analyze_email_formality(request.email_content)
        temperature = formality_to_temperature(formality)

        # Tu/vous mirror — split by register (1 = SMS, 2 = tutoiement pro).
        if formality == 1:
            user_prompt += (
                "\n\n⚠️ ATTENTION — EMAIL TRÈS INFORMEL (entre amis/proches) :\n"
                "- Réponds comme un ami répondrait par message, PAS comme un employé de bureau.\n"
                "- PAS de \"Bonjour\", PAS de \"Cordialement\", PAS de formules.\n"
                "- Phrases courtes et naturelles. 1-3 lignes MAX.\n"
                "- Tutoiement obligatoire. Ton décontracté.\n"
            )
        elif formality == 2:
            user_prompt += (
                "\n\n⚠️ TUTOIEMENT OBLIGATOIRE — le contact emploie 'tu' (ou 'ton/ta/tes/te/toi') :\n"
                "- TOUTE ta réponse doit être au tutoiement. Aucun 'vous', 'votre', 'vos'.\n"
                "- Si tu hésites, choisis 'tu' — jamais 'vous'.\n"
                "- Salutation casual permise (\"Salut Prénom,\") mais le corps reste pro.\n"
                "- Pas d'argot ni d'emojis : c'est du tutoiement professionnel, pas un SMS entre amis.\n"
            )

        # Appel LLM
        response = self._llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )
        _track_token_usage(response)

        # Calculer les métriques
        generation_time_ms = int((_time.time() - start_time) * 1000)
        tokens_used = response.input_tokens + response.output_tokens

        # Déterminer le ton détecté (heuristique basée sur tone_hint ou style_hints)
        tone_detected = request.tone_hint or DraftTone.PROFESSIONAL
        if not request.tone_hint and style_hints:
            # Essayer de mapper un style_hint vers un DraftTone
            for hint in style_hints:
                try:
                    tone_detected = DraftTone(hint.lower())
                    break
                except ValueError:
                    continue

        # Construire le résultat
        return DraftResult(
            content=response.content,
            confidence=0.8 if context_used else 0.6,
            tone_detected=tone_detected,
            generation_time_ms=generation_time_ms,
            tokens_used=tokens_used,
            status=DraftStatus.COMPLETED,
            retry_count=0,
            context_used=context_used,
            style_applied=bool(request.style_context or style_hints),
        )

    def draft_stream(
        self, request: DraftRequest
    ) -> Generator[StreamingDraftChunk, None, None]:
        """
        Génère une réponse email en streaming (Story 5-1 AC4).

        Utilise le même contexte que draft_with_context mais yield
        des chunks au fur et à mesure de la génération.

        Args:
            request: DraftRequest contenant email_content, context_result, etc.

        Yields:
            StreamingDraftChunk avec le texte progressif et les métriques.
        """
        # Extraire les informations de contexte (même logique que draft_with_context)
        contact_context = ""
        relationship_type = "unknown"
        style_hints: list[str] = []

        if request.context_result:
            contact_context = request.context_result.contact_context
            relationship_type = request.context_result.relationship_type.value
            style_hints = request.context_result.style_hints

        if request.get_style_hints():
            style_hints = list(set(style_hints + request.get_style_hints()))

        # Construire les prompts (avec few-shot examples + user formulas)
        user_email = getattr(request, "user_email", "") or ""
        contact_summary = self._resolve_contact_summary(
            request.conversation_history, user_email
        )
        recipient_profile = self._resolve_recipient_profile(request)
        system_prompt, dynamic_prefix = get_drafter_system_prompt_with_context_split(
            knowledge_base=self.knowledge_base,
            style_context=request.style_context or "",
            contact_context=contact_context,
            relationship_type=relationship_type,
            style_hints=style_hints,
            conversation_history=request.conversation_history,
            user_email=user_email,
            thread_context=getattr(request, "thread_context", None),
            contact_summary=contact_summary,
            recipient_profile=recipient_profile,
            account_id=self.account_id,
        )

        user_prompt = get_drafter_user_prompt_with_context(
            email_content=request.email_content,
            instructions=request.instructions,
        )
        if dynamic_prefix:
            user_prompt = f"{dynamic_prefix}\n\n{user_prompt}"

        # Adaptive temperature
        formality = analyze_email_formality(request.email_content)
        temperature = formality_to_temperature(formality)

        # Streaming
        accumulated_text = ""
        chunk_index = 0
        total_tokens = 0

        for llm_chunk in self._llm.stream(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=temperature,
        ):
            # Accumuler le texte
            accumulated_text += llm_chunk.text
            total_tokens = llm_chunk.output_tokens_so_far

            # Calculer le progress (estimation basée sur max_tokens)
            progress_percent = min(
                (total_tokens / self.max_tokens) * 100.0 if self.max_tokens > 0 else 0.0,
                100.0
            )

            if llm_chunk.is_final:
                progress_percent = 100.0

            yield StreamingDraftChunk(
                chunk=llm_chunk.text,
                chunk_index=chunk_index,
                accumulated_text=accumulated_text,
                is_final=llm_chunk.is_final,
                progress_percent=progress_percent,
                tokens_so_far=llm_chunk.input_tokens + total_tokens,
            )

            chunk_index += 1

    @_attribute_to_agent
    def draft_with_retry(self, request: DraftRequest) -> DraftResult:
        """
        Génère une réponse email avec gestion du rate limiting (Story 5-1 AC5).

        Implémente un retry avec exponential backoff pour gérer les erreurs
        de rate limiting de l'API Claude.

        Args:
            request: La requête de génération de brouillon.

        Returns:
            DraftResult avec le brouillon généré ou un statut rate_limited.

        Raises:
            Exception: Si une erreur non rate-limit se produit.
        """
        import time
        from app.domain.exceptions import LLMRateLimitError

        RETRY_BACKOFF_BASE = 0.5
        retry_count = 0
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                result = self.draft_with_context(request)
                # Mettre à jour le retry_count dans le résultat
                result.retry_count = retry_count
                return result

            except LLMRateLimitError as e:
                retry_count += 1

                if attempt < self.max_retries - 1:
                    # Utiliser retry_after si disponible, sinon exponential backoff
                    if e.retry_after is not None:
                        backoff = e.retry_after
                    else:
                        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    time.sleep(backoff)
                else:
                    # Max retries atteint, retourner un résultat rate_limited
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return DraftResult.create_rate_limited(
                        retry_count=retry_count,
                        generation_time_ms=elapsed_ms,
                    )

        # Ne devrait jamais arriver, mais par sécurité
        elapsed_ms = int((time.time() - start_time) * 1000)
        return DraftResult.create_rate_limited(
            retry_count=retry_count,
            generation_time_ms=elapsed_ms,
        )

    @_attribute_to_agent
    def draft_stream_with_retry(
        self, request: DraftRequest
    ) -> Generator[StreamingDraftChunk, None, None]:
        """
        Génère une réponse email en streaming avec gestion du rate limiting (Story 5-1 AC5).

        Implémente un retry avec exponential backoff pour gérer les erreurs
        de rate limiting de l'API Claude.

        Args:
            request: La requête de génération de brouillon.

        Yields:
            StreamingDraftChunk avec les chunks de la réponse.

        Raises:
            Exception: Si une erreur non rate-limit se produit.
        """
        import time
        from app.domain.exceptions import LLMRateLimitError

        RETRY_BACKOFF_BASE = 0.5

        for attempt in range(self.max_retries):
            try:
                # Yielder tous les chunks du générateur
                yield from self.draft_stream(request)
                return  # Succès, on sort

            except LLMRateLimitError as e:
                if attempt < self.max_retries - 1:
                    # Utiliser retry_after si disponible, sinon exponential backoff
                    if e.retry_after is not None:
                        backoff = e.retry_after
                    else:
                        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    time.sleep(backoff)
                else:
                    # Max retries atteint, on remonte l'exception
                    raise

    @_attribute_to_agent
    def revise_with_critique(
        self,
        request: "DraftRequest",
        critique: "CritiqueResult",
    ) -> "DraftResult":
        """
        Révise un brouillon en intégrant le feedback du CriticAgent (Story 5-3 AC2).

        Cette méthode est appelée quand le CriticAgent a rejeté un brouillon.
        Elle utilise les scores et suggestions de la critique pour guider
        la régénération du brouillon.

        Args:
            request: La requête originale de génération de brouillon.
            critique: Le résultat de l'évaluation du CriticAgent.

        Returns:
            DraftResult avec le brouillon révisé et les métriques.
        """
        from app.prompts import get_drafter_revision_with_critique_prompt

        start_time = _time.time()

        # Extraire les informations de contexte (même logique que draft_with_context)
        contact_context = ""
        relationship_type = "unknown"
        style_hints: list[str] = []
        context_used = False

        if request.context_result:
            context_used = True
            contact_context = request.context_result.contact_context
            relationship_type = request.context_result.relationship_type.value
            style_hints = request.context_result.style_hints

        if request.get_style_hints():
            style_hints = list(set(style_hints + request.get_style_hints()))

        # Construire le system prompt (identique à draft_with_context, avec few-shot)
        user_email = getattr(request, "user_email", "") or ""
        contact_summary = self._resolve_contact_summary(
            request.conversation_history, user_email
        )
        recipient_profile = self._resolve_recipient_profile(request)
        system_prompt, dynamic_prefix = get_drafter_system_prompt_with_context_split(
            knowledge_base=self.knowledge_base,
            style_context=request.style_context or "",
            contact_context=contact_context,
            relationship_type=relationship_type,
            style_hints=style_hints,
            conversation_history=request.conversation_history,
            user_email=user_email,
            contact_summary=contact_summary,
            recipient_profile=recipient_profile,
            account_id=self.account_id,
        )

        # Construire le user prompt avec le feedback du Critic
        user_prompt = get_drafter_revision_with_critique_prompt(
            email_content=request.email_content,
            previous_draft=critique.draft_content or "",
            coherence=critique.scores.coherence,
            tone=critique.scores.tone,
            completeness=critique.scores.completeness,
            errors=critique.scores.errors,
            decision=critique.decision.value,
            suggestions=critique.suggestions,
            explanation=critique.explanation,
            instructions=request.instructions,
            conciseness=critique.scores.conciseness,
            over_commitment=critique.scores.over_commitment,
            emotional_intelligence=critique.scores.emotional_intelligence,
        )
        if dynamic_prefix:
            user_prompt = f"{dynamic_prefix}\n\n{user_prompt}"

        # Adaptive temperature
        formality = analyze_email_formality(request.email_content)
        temperature = formality_to_temperature(formality)

        # Tu/vous mirror — split by register (1 = SMS, 2 = tutoiement pro).
        if formality == 1:
            user_prompt += (
                "\n\n⚠️ ATTENTION — EMAIL TRÈS INFORMEL (entre amis/proches) :\n"
                "- Réponds comme un ami répondrait par message, PAS comme un employé de bureau.\n"
                "- PAS de \"Bonjour\", PAS de \"Cordialement\", PAS de formules.\n"
                "- Phrases courtes et naturelles. 1-3 lignes MAX.\n"
                "- Tutoiement obligatoire. Ton décontracté.\n"
            )
        elif formality == 2:
            user_prompt += (
                "\n\n⚠️ TUTOIEMENT OBLIGATOIRE — le contact emploie 'tu' (ou 'ton/ta/tes/te/toi') :\n"
                "- TOUTE ta réponse doit être au tutoiement. Aucun 'vous', 'votre', 'vos'.\n"
                "- Si tu hésites, choisis 'tu' — jamais 'vous'.\n"
                "- Salutation casual permise (\"Salut Prénom,\") mais le corps reste pro.\n"
                "- Pas d'argot ni d'emojis : c'est du tutoiement professionnel, pas un SMS entre amis.\n"
            )

        # Appel LLM
        response = self._llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )
        _track_token_usage(response)

        # Calculer les métriques
        generation_time_ms = int((_time.time() - start_time) * 1000)
        tokens_used = response.input_tokens + response.output_tokens

        # Déterminer le ton détecté
        tone_detected = request.tone_hint or DraftTone.PROFESSIONAL
        if not request.tone_hint and style_hints:
            for hint in style_hints:
                try:
                    tone_detected = DraftTone(hint.lower())
                    break
                except ValueError:
                    continue

        # Construire le résultat avec une confiance légèrement plus élevée
        # car on a intégré le feedback du Critic
        return DraftResult(
            content=response.content,
            confidence=0.85 if context_used else 0.65,
            tone_detected=tone_detected,
            generation_time_ms=generation_time_ms,
            tokens_used=tokens_used,
            status=DraftStatus.COMPLETED,
            retry_count=0,
            context_used=context_used,
            style_applied=bool(request.style_context or style_hints),
        )

    @_attribute_to_agent
    def revise_with_critique_and_retry(
        self,
        request: "DraftRequest",
        critique: "CritiqueResult",
    ) -> "DraftResult":
        """
        Révise un brouillon avec gestion du rate limiting (Story 5-3 AC2/AC4).

        Implémente un retry avec exponential backoff pour gérer les erreurs
        de rate limiting de l'API Claude.

        Args:
            request: La requête originale de génération de brouillon.
            critique: Le résultat de l'évaluation du CriticAgent.

        Returns:
            DraftResult avec le brouillon révisé ou un statut rate_limited.
        """
        import time
        from app.domain.exceptions import LLMRateLimitError

        RETRY_BACKOFF_BASE = 0.5
        retry_count = 0
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                result = self.revise_with_critique(request, critique)
                result.retry_count = retry_count
                return result

            except LLMRateLimitError as e:
                retry_count += 1

                if attempt < self.max_retries - 1:
                    if e.retry_after is not None:
                        backoff = e.retry_after
                    else:
                        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    time.sleep(backoff)
                else:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return DraftResult.create_rate_limited(
                        retry_count=retry_count,
                        generation_time_ms=elapsed_ms,
                    )

        # Ne devrait jamais arriver, mais par sécurité
        elapsed_ms = int((time.time() - start_time) * 1000)
        return DraftResult.create_rate_limited(
            retry_count=retry_count,
            generation_time_ms=elapsed_ms,
        )


# ============================================================================
# CRITIC AGENT
# ============================================================================

@dataclass
class CriticAgent:
    """
    Agent responsable de l'audit des réponses emails.

    Évalue les réponses selon des critères stricts :
    - Cohérence du ton
    - Respect du contexte
    - Absence d'hallucinations

    Cette classe est une façade qui délègue au LLM adapter du Container.

    Story 5-2: Ajoute l'évaluation structurée avec 4 critères (AC1-AC5):
    - coherence: Le brouillon répond-il correctement à l'email original?
    - tone: Le ton est-il approprié au contexte?
    - completeness: Toutes les questions/demandes sont-elles adressées?
    - errors: Absence de fautes et d'hallucinations?
    """
    max_tokens: int = MAX_TOKENS_CRITIC
    knowledge_base: str = ""
    account_id: Optional[int] = None
    quality_threshold: int = 70  # AC3: Seuil configurable (default: 70)
    max_retries: int = 3  # Maximum retry attempts for rate limiting
    _llm: Optional[LLMPort] = field(default=None, repr=False)
    # See DrafterAgent._agent_label — used by the LLM-attribution context.
    _agent_label: str = field(default="critic", repr=False)

    # Audit 2026-05-06: per-intent threshold tuning. Decline / RH /
    # complaint emails carry higher cost-of-error so the Critic must be
    # stricter; simple acks are cheaper to ship marginally below 70 than
    # to LLM-revise. Mapping picked from the same risk taxonomy used by
    # smart_routing._is_tone_sensitive().
    _INTENT_THRESHOLDS: dict = field(default_factory=lambda: {
        "decline": 78, "refus": 78,
        "complaint": 78, "plainte": 78,
        "rh": 78, "hr": 78,
        "termination": 80, "licenciement": 80,
        "negotiation": 75, "objection": 75,
        # Coarse marker emitted by smart_routing when _is_tone_sensitive
        # matches but a fine-grained intent isn't known. Same threshold as
        # decline/complaint because the underlying regex hits the same risk
        # cluster (refusal / RH / termination keywords).
        "tone_sensitive": 78,
        "scheduling": 68,
        "acknowledgment": 60, "ack": 60,
    }, repr=False)

    def _effective_threshold(
        self,
        intent: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> int:
        """Resolve the threshold to use for this critique call.

        Order: explicit env CRITIC_THRESHOLD_OVERRIDE > intent-based map
        > self.quality_threshold (default 70). Tier currently has no
        direct mapping — the COMPLEX path already uses revisions, not a
        higher threshold — but it is reserved for future tuning.
        """
        import os as _os_t
        override = _os_t.environ.get("CRITIC_THRESHOLD_OVERRIDE")
        if override:
            try:
                v = int(override)
                if 50 <= v <= 95:
                    return v
            except (TypeError, ValueError):
                pass
        if intent:
            key = intent.strip().lower()
            mapped = self._INTENT_THRESHOLDS.get(key)
            if mapped is not None:
                return int(mapped)
        return int(self.quality_threshold)

    def __post_init__(self):
        if not self.knowledge_base:
            self.knowledge_base = self._resolve_knowledge()
        # Cost-optimized: Haiku for critique ($0.003 vs $0.018 Sonnet)
        # Routes to ANTHROPIC_API_KEY_DRAFTING for per-category cost tracking.
        self._llm = get_container().llm_drafting

    @property
    def model(self) -> str:
        """Name of the LLM model actually used at runtime.

        See ``DrafterAgent.model`` — same rationale: the previous
        ``model: str = MODEL_DEFAULT`` dataclass field reported the env var
        (Sonnet by default), but ``__post_init__`` always wires the runtime
        LLM through ``Container.llm_drafting`` which is Haiku 4.5. The
        200-case eval at ``tasks/eval-critic-haiku-vs-sonnet-verdict-2026-05-04.md``
        shows that misalignment caused a wasted hour of analysis on a
        wrong premise — the honest property closes that footgun.
        """
        if self._llm is None:
            return ""
        return getattr(self._llm, "model", "")

    def _resolve_knowledge(self) -> str:
        """DB-first knowledge loading (same pattern as DrafterAgent).

        When ``account_id`` is set, a DB miss returns "" rather than falling
        back to the process-global ``memoire.md`` — that file holds another
        tenant's knowledge base and must never enter a critic prompt for a
        different account (audit 2026-05-29). No-account (Tauri) reads global.
        """
        if self.account_id:
            from app.prompts import load_knowledge_from_db
            kb = load_knowledge_from_db(self.account_id)
            if kb:
                return kb
            return ""
        return load_knowledge_base()

    @_attribute_to_agent
    def evaluate(self, email_content: str, draft: str) -> str:
        """
        Évalue une réponse email (méthode legacy).

        Args:
            email_content: L'email original reçu.
            draft: La réponse proposée à évaluer.

        Returns:
            "VALID" si acceptable, ou "REJET : [raison]" sinon.
        """
        response = self._llm.complete(
            system=get_critic_system_prompt(self.knowledge_base),
            user=get_critic_user_prompt(email_content, draft),
            max_tokens=self.max_tokens
        )
        _track_token_usage(response)
        return response.content.strip()

    def is_valid(self, evaluation: str) -> bool:
        """Vérifie si l'évaluation est positive."""
        return evaluation.strip().upper().startswith("VALID")

    @_attribute_to_agent
    def evaluate_draft(self, request: CritiqueRequest) -> CritiqueResult:
        """
        Évalue un brouillon avec notation structurée (Story 5-2).

        Args:
            request: La requête de critique contenant le brouillon et le contexte.

        Returns:
            CritiqueResult avec scores détaillés, décision et suggestions.

        AC1: Agent Python qui évalue le brouillon du DrafterAgent
        AC2: Critères: cohérence, ton, complétude, erreurs (0-100 chacun)
        AC3: Score de qualité avec seuil configurable (default: 70)
        AC4: Retour structuré avec suggestions d'amélioration
        AC5: Décision: VALID ou REJECT avec raison

        Note: LLMRateLimitError est propagée pour permettre la gestion de retry
        au niveau supérieur (evaluate_draft_with_retry).
        """
        from app.domain.exceptions import LLMRateLimitError

        start_time = _time.time()
        # Tier-/intent-aware threshold (audit 2026-05-06). Default still 70
        # if request carries no intent — preserves all pre-fix call sites.
        effective_threshold = self._effective_threshold(
            intent=getattr(request, "intent", None),
            tier=getattr(request, "tier", None),
        )
        _logger.info(
            "CriticAgent.evaluate_draft: Démarrage évaluation",
            extra={
                "email_id": request.email_id,
                "draft_length": len(request.draft_content),
                "threshold": effective_threshold,
                "intent": getattr(request, "intent", None),
                "tier": getattr(request, "tier", None),
            }
        )

        try:
            # Appel LLM avec prompts structurés.
            # Issue #682 — prompt caching: passer le system comme list[SystemSegment]
            # avec rubric+KB cacheable et règles apprises per-contact non-cacheables.
            # La cache key ne dépend plus du contact → cross-contact cache hits
            # pour le même compte. Voir `get_critic_structured_system_segments`
            # pour le détail du contrat.
            response = self._llm.complete(
                system=get_critic_structured_system_segments(
                    self.knowledge_base,
                    contact=getattr(request, "contact", ""),
                    account_id=self.account_id,
                ),
                user=get_critic_structured_user_prompt(
                    email_content=request.original_email,
                    draft=request.draft_content,
                    context=request.context,
                    threshold=effective_threshold,
                ),
                max_tokens=self.max_tokens
            )
            _track_token_usage(response)

            # Extraction et parsing JSON. Audit 2026-05-04: pass the draft
            # so the parser can apply the deterministic decision rule
            # (placeholder presence → REJECT, regardless of LLM verdict).
            result = self._parse_critique_response(
                response.content,
                evaluation_time_ms=int((_time.time() - start_time) * 1000),
                tokens_used=response.input_tokens + response.output_tokens,
                draft_content=request.draft_content,
            )

            # Story 5-5: Classification du ton basée sur le score de ton
            tone_classification = self.classify_tone(
                draft_content=request.draft_content,
                tone_score=result.scores.tone,
            )
            result.tone_classification = tone_classification

            _logger.info(
                "CriticAgent.evaluate_draft: Évaluation terminée",
                extra={
                    "email_id": request.email_id,
                    "decision": result.decision.value,
                    "overall_score": result.scores.calculate_overall(),
                    "tone_classification": tone_classification.classification.value,
                    "evaluation_time_ms": result.evaluation_time_ms,
                    "tokens_used": result.tokens_used,
                }
            )

            return result

        except LLMRateLimitError:
            # Propager les erreurs de rate limit pour gestion de retry
            _logger.warning(
                "CriticAgent.evaluate_draft: Rate limit atteint, propagation pour retry",
                extra={"email_id": request.email_id}
            )
            raise

        except Exception as e:
            _logger.error(
                f"CriticAgent.evaluate_draft: Erreur - {e}",
                extra={"email_id": request.email_id, "error": str(e)},
                exc_info=True
            )
            return CritiqueResult.create_failed(
                error_message=str(e),
                evaluation_time_ms=int((_time.time() - start_time) * 1000),
            )

    def _parse_critique_response(
        self,
        response_content: str,
        evaluation_time_ms: int = 0,
        tokens_used: int = 0,
        draft_content: str = "",
    ) -> CritiqueResult:
        """
        Parse la réponse JSON du LLM et crée un CritiqueResult.

        Args:
            response_content: Le contenu brut de la réponse LLM.
            evaluation_time_ms: Le temps d'évaluation en millisecondes.
            tokens_used: Le nombre de tokens utilisés.

        Returns:
            CritiqueResult avec les données parsées ou un résultat d'échec.
        """
        try:
            # Extraction JSON depuis la réponse (utilise le parser existant)
            data = extract_json_from_response(response_content)

            if not data:
                _logger.warning(
                    "CriticAgent._parse_critique_response: JSON non trouvé, utilisation du fallback"
                )
                return self._fallback_parse(
                    response_content, evaluation_time_ms, tokens_used
                )

            # Validation et extraction des scores
            scores = CritiqueScores(
                coherence=self._clamp_score(data.get("coherence", 50)),
                tone=self._clamp_score(data.get("tone", 50)),
                completeness=self._clamp_score(data.get("completeness", 50)),
                errors=self._clamp_score(data.get("errors", 50)),
                conciseness=self._clamp_score(data.get("conciseness", 50)),
                over_commitment=self._clamp_score(data.get("over_commitment", 50)),
                emotional_intelligence=self._clamp_score(data.get("emotional_intelligence", 50)),
            )

            # Extraction des suggestions et de l'explication (informationnels)
            suggestions = data.get("suggestions", [])
            if isinstance(suggestions, str):
                suggestions = [suggestions]
            elif not isinstance(suggestions, list):
                suggestions = []
            explanation = data.get("explanation", "")
            if not isinstance(explanation, str):
                explanation = str(explanation)

            # Audit 2026-05-04: la décision est calculée DÉTERMINISTIQUEMENT
            # à partir des scores + présence de placeholders. Le champ
            # `decision` retourné par le LLM est ignoré — l'eval ground-truth
            # 60-cas a montré que Haiku émet `decision: reject` avec
            # overall=87, sans aucune dim<50, sur la base de préférences
            # stylistiques ("ajouter signature complète"). Le bypass code
            # ramène la FP rate de 31 % → 22 % et garde la FN rate à 0 %.
            #
            # Règle :
            #   placeholder dans draft  → REJECT (peu importe les scores)
            #   une dim < 50             → REJECT
            #   moyenne < quality_threshold → REJECT
            #   sinon                    → VALID
            overall_score = scores.calculate_overall()
            has_placeholder = _draft_has_placeholder(draft_content)
            sub50_dims = [
                name for name in (
                    "coherence", "tone", "completeness", "errors",
                    "conciseness", "over_commitment", "emotional_intelligence",
                ) if getattr(scores, name) < 50
            ]
            if has_placeholder:
                decision = CritiqueDecision.REJECT
                marker_msg = "Placeholder détecté dans le brouillon — retirer [À confirmer] / [TBD] / etc."
                if not any("placeholder" in s.lower() or "à confirmer" in s.lower() for s in suggestions):
                    suggestions.insert(0, marker_msg)
            elif sub50_dims:
                decision = CritiqueDecision.REJECT
                if not any("seuil" in s.lower() or "score" in s.lower() for s in suggestions):
                    suggestions.insert(
                        0,
                        f"Dimension(s) sous le seuil 50 : {', '.join(sub50_dims)}"
                    )
            elif overall_score < self.quality_threshold:
                decision = CritiqueDecision.REJECT
                if not any("seuil" in s.lower() for s in suggestions):
                    suggestions.insert(
                        0,
                        f"Score global ({overall_score}) inférieur au seuil ({self.quality_threshold})"
                    )
            else:
                decision = CritiqueDecision.VALID

            return CritiqueResult(
                scores=scores,
                decision=decision,
                suggestions=suggestions,
                explanation=explanation,
                evaluation_time_ms=evaluation_time_ms,
                tokens_used=tokens_used,
                status=CritiqueStatus.COMPLETED,
            )

        except Exception as e:
            _logger.error(f"CriticAgent._parse_critique_response: Erreur parsing - {e}")
            return CritiqueResult.create_failed(
                error_message=f"Erreur parsing JSON: {e}",
                evaluation_time_ms=evaluation_time_ms,
            )

    def _clamp_score(self, value: any) -> int:
        """Convertit et limite un score entre 0 et 100."""
        try:
            score = int(value)
            return max(0, min(100, score))
        except (ValueError, TypeError):
            return 50  # Score par défaut si conversion impossible

    def _fallback_parse(
        self,
        response_content: str,
        evaluation_time_ms: int,
        tokens_used: int,
    ) -> CritiqueResult:
        """
        Parse de secours basé sur les mots-clés de la réponse.

        Si le parsing JSON échoue, défaut à REJECT pour forcer une passe V2.
        Audit failure-mode #3 (2026-04-24): l'ancien fallback faisait du
        keyword-matching naïf — un email contenant "VALID" dans le corps
        cité par le critique faisait passer le draft sans vraie évaluation.
        Maintenant: REJECT par défaut pour qu'une révision V2 soit générée
        plutôt que de risquer un draft non vérifié.

        Le keyword-matching reste comme fallback EN-DERNIER si la réponse
        contient un signal explicite de validation.
        """
        content = response_content or ""
        content_upper = content.upper()

        # Détection prudente: VALID accepté seulement si TRES explicite
        # (présence de la clé JSON `"decision":"VALID"` ou variantes très
        # claires) ET pas de signal de rejet. Sinon REJECT par défaut.
        explicit_valid_marker = (
            '"decision":"VALID"' in content.replace(" ", "")
            or '"decision": "VALID"' in content
            or 'DECISION:VALID' in content_upper.replace(" ", "")
            or 'DECISION: VALID' in content_upper
        )
        explicit_reject_marker = (
            "REJET" in content_upper
            or '"REJECT"' in content_upper
            or 'DECISION: REJECT' in content_upper
        )
        is_valid = explicit_valid_marker and not explicit_reject_marker

        # Scores par défaut: bas pour REJECT (force le seuil à rejeter),
        # neutres pour VALID explicite.
        default_score = 70 if is_valid else 40
        scores = CritiqueScores(
            coherence=default_score,
            tone=default_score,
            completeness=default_score,
            errors=default_score,
            conciseness=default_score,
            over_commitment=default_score,
            emotional_intelligence=default_score,
        )

        decision = CritiqueDecision.VALID if is_valid else CritiqueDecision.REJECT
        explanation = content[:500] if content else "Parsing fallback utilisé (JSON invalide)"

        suggestions = ["Évaluation basée sur le parsing de secours (JSON LLM invalide)"]
        if not is_valid:
            suggestions.append("REJECT par défaut — V2 sera générée par sécurité")

        return CritiqueResult(
            scores=scores,
            decision=decision,
            suggestions=suggestions,
            explanation=explanation,
            evaluation_time_ms=evaluation_time_ms,
            tokens_used=tokens_used,
            status=CritiqueStatus.COMPLETED,
        )

    # Mots-clés d'urgence pour la classification de ton (Story 5-5)
    URGENCY_KEYWORDS = frozenset([
        "urgent", "urgente", "urgently", "asap",
        "immédiat", "immédiate", "immediately",
        "critique", "critical", "emergency", "urgence",
        "deadline", "échéance", "avant la fin de la journée",
        "dès que possible", "au plus vite", "maintenant",
        "priorité haute", "high priority", "action requise",
        "action required", "time-sensitive", "important deadline",
    ])

    def _detect_urgency_keywords(self, text: str) -> bool:
        """Détecte la présence de mots-clés d'urgence dans le texte.

        Args:
            text: Le texte à analyser (brouillon ou email).

        Returns:
            True si des mots-clés d'urgence sont détectés.
        """
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.URGENCY_KEYWORDS)

    def classify_tone(self, draft_content: str, tone_score: int = 50) -> ToneResult:
        """Classifie le ton d'un brouillon email (Story 5-5 AC2).

        Combine le score de ton (0-100) avec la détection de mots-clés
        d'urgence pour une classification plus précise.

        Args:
            draft_content: Le contenu du brouillon à classifier.
            tone_score: Le score de ton (0-100) du CritiqueScores.

        Returns:
            ToneResult avec classification, confidence et explication.
        """
        urgency_detected = self._detect_urgency_keywords(draft_content)

        _logger.debug(
            "CriticAgent.classify_tone: Classification en cours",
            extra={
                "tone_score": tone_score,
                "urgency_detected": urgency_detected,
                "draft_length": len(draft_content),
            }
        )

        result = ToneResult.from_tone_score(
            tone_score=tone_score,
            analysis_text=draft_content[:500],  # Limite pour l'analyse
            urgency_keywords=urgency_detected,
        )

        _logger.info(
            f"CriticAgent.classify_tone: {result.classification.value}",
            extra={
                "classification": result.classification.value,
                "confidence": result.confidence,
            }
        )

        return result

    @_attribute_to_agent
    def evaluate_draft_with_retry(self, request: CritiqueRequest) -> CritiqueResult:
        """
        Évalue un brouillon avec retry automatique en cas de rate limit.

        Utilise un backoff exponentiel pour les erreurs de rate limit.
        Émet des événements WebSocket pour le suivi du statut.

        Args:
            request: La requête de critique.

        Returns:
            CritiqueResult avec le résultat de l'évaluation.
        """
        from app.domain.exceptions import LLMRateLimitError
        from app.api.websocket import (
            emit_critique_start,
            emit_critique_complete,
            emit_critique_error,
        )

        RETRY_BACKOFF_BASE = 1.0  # 1 seconde de base

        # Émettre l'événement de début
        emit_critique_start(
            email_id=request.email_id or "",
            account_id=request.account_id,
        )

        start_time = _time.time()
        retry_count = 0

        for attempt in range(self.max_retries):
            try:
                result = self.evaluate_draft(request)

                # Vérifier si le résultat est un échec (erreur non-rate-limit gérée dans evaluate_draft)
                if result.status == CritiqueStatus.FAILED:
                    emit_critique_error(
                        email_id=request.email_id or "",
                        error=result.explanation,
                        retry_count=retry_count,
                        account_id=request.account_id,
                    )
                    return result

                # Émettre l'événement de succès (Story 5-5: inclure classification de ton)
                tone_data = (
                    result.tone_classification.to_dict()
                    if result.tone_classification
                    else None
                )
                emit_critique_complete(
                    email_id=request.email_id or "",
                    decision=result.decision.value,
                    overall_score=result.scores.calculate_overall(),
                    scores={
                        "coherence": result.scores.coherence,
                        "tone": result.scores.tone,
                        "completeness": result.scores.completeness,
                        "errors": result.scores.errors,
                    },
                    suggestions=result.suggestions,
                    explanation=result.explanation,
                    evaluation_time_ms=result.evaluation_time_ms,
                    tokens_used=result.tokens_used,
                    tone_classification=tone_data,
                    account_id=request.account_id,
                )

                return result

            except LLMRateLimitError as e:
                retry_count += 1

                if attempt < self.max_retries - 1:
                    # Utiliser retry_after si disponible, sinon exponential backoff
                    if e.retry_after is not None:
                        backoff = e.retry_after
                    else:
                        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)

                    _logger.warning(
                        f"CriticAgent rate limit: tentative {attempt + 1}/{self.max_retries}, "
                        f"retry dans {backoff:.1f}s",
                        extra={
                            "email_id": request.email_id,
                            "retry_after": backoff,
                        }
                    )

                    _time.sleep(backoff)
                else:
                    # Toutes les tentatives épuisées
                    _logger.error(
                        f"CriticAgent rate limit: échec après {self.max_retries} tentatives",
                        extra={"email_id": request.email_id}
                    )

                    error_msg = f"Rate limit après {self.max_retries} tentatives"
                    emit_critique_error(
                        email_id=request.email_id or "",
                        error=error_msg,
                        retry_count=retry_count,
                        account_id=request.account_id,
                    )

                    return CritiqueResult.create_rate_limited(
                        retry_count=retry_count,
                        evaluation_time_ms=int((_time.time() - start_time) * 1000),
                    )

            except Exception as e:
                # Erreur non-rate-limit inattendue
                _logger.error(
                    f"CriticAgent error: {e}",
                    extra={"email_id": request.email_id},
                    exc_info=True
                )

                emit_critique_error(
                    email_id=request.email_id or "",
                    error=str(e),
                    retry_count=retry_count,
                    account_id=request.account_id,
                )

                return CritiqueResult.create_failed(
                    error_message=str(e),
                    evaluation_time_ms=int((_time.time() - start_time) * 1000),
                )

        # Ne devrait jamais arriver, mais au cas où
        return CritiqueResult.create_failed(
            error_message="Retry épuisé sans résultat",
            evaluation_time_ms=int((_time.time() - start_time) * 1000),
        )


# ============================================================================
# PRIORITIZATION AGENT
# ============================================================================

PRIORITIZATION_PROMPT = """Agent priorisation emails. Output JSON DIRECT, zéro raisonnement, zéro <thinking>, zéro explication.

Scoring :
- urgency (0-100) : mots-clés urgent/ASAP/deadline/aujourd'hui/demain
- vip (0-100) : importance expéditeur (domaine, titre signature)
- sentiment (-1..1) : -1 négatif, 0 neutre, 1 positif
- deadline : date ISO ou null

Format strict (aucun texte autour) :
{"urgency":50,"vip":30,"sentiment":0,"deadline":null,"priority_score":40}

priority_score = urgency*0.4 + vip*0.3 + (sentiment+1)*15"""


@dataclass
class PrioritizationAgent:
    """
    Agent responsable de la priorisation des emails.

    Analyse les emails pour déterminer :
    - Score d'urgence (0-100)
    - Score VIP (0-100)
    - Sentiment (-1 à 1)
    - Deadline éventuelle

    Cette classe est une façade qui délègue au LLM adapter du Container.
    """
    model: str = CLAUDE_MODEL_LABEL
    max_tokens: int = MAX_TOKENS_PRIORITIZATION
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Background per-email classifier — routes to ANTHROPIC_API_KEY_BACKGROUND.
        self._llm = get_container().llm_background

    # Valeurs par défaut pour la priorisation
    _DEFAULT_PRIORITY = {
        "urgency": 50,
        "vip": 50,
        "sentiment": 0,
        "deadline": None,
        "priority_score": 50
    }

    def analyze(self, email_content: str, sender: str = "") -> dict:
        """
        Analyse un email et retourne les scores de priorité.

        Args:
            email_content: Le contenu de l'email.
            sender: L'adresse email de l'expéditeur.

        Returns:
            Dict avec urgency, vip, sentiment, deadline, priority_score
        """
        context = f"Expéditeur: {sender}\n\n{email_content}" if sender else email_content

        try:
            response = self._llm.complete(
                system=PRIORITIZATION_PROMPT,
                user=context,
                max_tokens=self.max_tokens
            )
            _track_token_usage(response)

            return extract_json_from_response(
                response.content,
                default=self._DEFAULT_PRIORITY,
                error_context="PrioritizationAgent"
            )

        except Exception as e:
            _logger.warning(f"PrioritizationAgent.analyze failed: {e}")
            return self._DEFAULT_PRIORITY.copy()




@dataclass
class ExtractedTask:
    """Représente une tâche extraite d'un email."""
    title: str
    description: str
    priority: str
    deadline: Optional[str] = None




# ============================================================================
# COMMITMENT EXTRACTOR AGENT
# ============================================================================

COMMITMENT_EXTRACTOR_PROMPT = """Tu es un assistant spécialisé dans la détection d'engagements pris par l'expéditeur dans un email.

Analyse l'email ENVOYÉ et identifie TOUS les engagements/promesses faits par l'auteur.

Exemples d'engagements à détecter :
- "Je vous envoie le document demain"
- "Je m'en occupe cette semaine"
- "Je vous rappelle lundi"
- "Je reviens vers vous avec une proposition"
- "Je vous tiens informé"
- "Je vous confirme dès que possible"

Pour chaque engagement identifié, extrais :
- description: Description courte de l'engagement (max 100 caractères)
- deadline: Date ISO si mentionnée explicitement, sinon null

Retourne UNIQUEMENT un JSON :
{"commitments": [{"description": "...", "deadline": null}]}

Si aucun engagement n'est identifié, retourne : {"commitments": []}"""


@dataclass
class ExtractedCommitment:
    """Représente un engagement extrait d'un email."""
    description: str
    deadline: Optional[str] = None


@dataclass
class CommitmentExtractorAgent:
    """
    Agent responsable de l'extraction d'engagements depuis les emails envoyés.

    Identifie les promesses faites par l'utilisateur et retourne une liste structurée.

    Cette classe est une façade qui délègue au LLM adapter du Container.
    """
    max_tokens: int = MAX_TOKENS_COMMITMENT_EXTRACTION
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Background per-email extractor — routes to ANTHROPIC_API_KEY_BACKGROUND.
        self._llm = get_container().llm_background

    @property
    def model(self) -> str:
        """Honest runtime model — Haiku via container.llm_background.

        See TaskExtractorAgent.model for the pattern rationale (cosmetic
        `MODEL_FAST` field replaced 2026-05-05).
        """
        if self._llm is None:
            return ""
        return getattr(self._llm, "model", "")

    @staticmethod
    def _parse_commitment(commitment: dict) -> ExtractedCommitment:
        """Parse un dict brut en ExtractedCommitment avec valeurs par défaut."""
        return ExtractedCommitment(
            description=commitment.get("description", ""),
            deadline=commitment.get("deadline")
        )

    def extract(self, email_content: str) -> List[ExtractedCommitment]:
        """
        Extrait les engagements d'un email.

        Args:
            email_content: Le contenu de l'email à analyser.

        Returns:
            Liste d'engagements extraits (peut être vide).
        """
        try:
            response = self._llm.complete(
                system=COMMITMENT_EXTRACTOR_PROMPT,
                user=email_content,
                max_tokens=self.max_tokens
            )
            _track_token_usage(response)

            result = extract_json_from_response(
                response.content,
                default={"commitments": []},
                error_context="CommitmentExtractorAgent"
            )

            commitments = result.get("commitments", [])
            if not isinstance(commitments, list):
                return []
            return [
                self._parse_commitment(commitment)
                for commitment in commitments
                if isinstance(commitment, dict)
            ]

        except Exception as e:
            _logger.warning(f"CommitmentExtractorAgent.extract failed: {e}")
            return []


# ============================================================================
# SENSITIVE DATA DETECTOR AGENT
# ============================================================================

SENSITIVE_DATA_DETECTOR_PROMPT = """Tu es un expert en sécurité des données chargé d'analyser les brouillons d'emails avant leur envoi.

Ta mission est de détecter toute donnée sensible ou confidentielle qui ne devrait PAS être partagée avec des destinataires externes.

Types de données sensibles à détecter :
1. FINANCIAL : Chiffres d'affaires, profits, marges, budgets, salaires, revenus
2. PERSONAL : Données personnelles (RGPD), numéros SS, adresses personnelles, données de santé
3. COMMERCIAL : Secrets commerciaux, stratégies, projets confidentiels, informations sur les concurrents
4. CREDENTIAL : Mots de passe, tokens API, clés d'accès, identifiants

Pour chaque donnée sensible détectée, fournis :
- data_type: Le type (financial, personal, commercial, credential)
- description: Une brève description du problème
- snippet: L'extrait exact du texte contenant la donnée sensible

Retourne UNIQUEMENT un JSON :
{
    "is_sensitive": true/false,
    "confidence": 0.0-1.0,
    "detected_items": [{"data_type": "...", "description": "...", "snippet": "..."}],
    "analysis_summary": "Résumé de l'analyse"
}

Si aucune donnée sensible n'est détectée :
{"is_sensitive": false, "confidence": 0.1, "detected_items": [], "analysis_summary": "Aucune donnée sensible détectée"}"""


@dataclass
class SensitiveDataDetectorAgent:
    """
    Agent responsable de la détection de données sensibles dans les brouillons.

    Analyse les brouillons avant envoi pour bloquer la transmission
    d'informations confidentielles aux destinataires externes.

    Cette classe est une façade qui délègue au LLM adapter du Container.
    """
    max_tokens: int = MAX_TOKENS_CLASSIFICATION
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Background per-email sensitive-data detector — routes to ANTHROPIC_API_KEY_BACKGROUND.
        self._llm = get_container().llm_background

    @property
    def model(self) -> str:
        """Honest runtime model — Haiku via container.llm_background.

        See TaskExtractorAgent.model for the pattern rationale (cosmetic
        `MODEL_FAST` field replaced 2026-05-05).
        """
        if self._llm is None:
            return ""
        return getattr(self._llm, "model", "")

    def _parse_detection(self, data: dict) -> SensitiveDataDetection:
        """Convertit un dict JSON en SensitiveDataDetection."""
        detected_items = []
        for item_data in data.get("detected_items", []):
            try:
                data_type = SensitiveDataType(item_data.get("data_type", "personal"))
            except ValueError:
                data_type = SensitiveDataType.PERSONAL
            detected_items.append(SensitiveDataItem(
                data_type=data_type,
                description=item_data.get("description", ""),
                snippet=item_data.get("snippet", ""),
            ))

        confidence = data.get("confidence", 0.0)
        # Clamp confidence to [0, 1] to avoid validation errors
        confidence = max(0.0, min(1.0, confidence))

        return SensitiveDataDetection(
            is_sensitive=data.get("is_sensitive", False),
            confidence=confidence,
            detected_items=detected_items,
            analysis_summary=data.get("analysis_summary", ""),
        )

    # Pre-filter regex: PII categories that ALWAYS show as one of these signals.
    # If the draft has zero matches, there is nothing for the LLM to find.
    # Tuned conservatively — we'd rather call the LLM unnecessarily than miss
    # real PII. Patterns:
    #   - digits run of length ≥ 4   (phone, ID number, credit card fragments, IBAN parts)
    #   - @ followed by a domain     (email addresses)
    #   - http(s):// or www.         (URLs that may contain credentials)
    #   - common credential prefixes (AKIA, sk-, pk_, ghp_, xox?, Bearer )
    #   - "password"/"mot de passe"/"secret" tokens
    #   - IBAN / SIRET / SSN-like patterns with letters+digits
    _PII_PRE_FILTER = _re.compile(
        r"""
        \d{4,}                                      # 4+ consecutive digits
        | [A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}   # email
        | https?://\S+                              # URL
        | www\.\S+                                  # URL (no scheme)
        | \b(AKIA|ASIA|sk-|pk_|ghp_|gho_|github_pat_|xox[abprs]|Bearer)\w{6,}  # credential
        | \b(?:password|mot\s+de\s+passe|secret|api[_\s-]?key|token)\b        # secret keyword
        | \b[A-Z]{2}\d{2}[A-Z0-9]{4,}\b              # IBAN-like (FR76…)
        """,
        _re.IGNORECASE | _re.VERBOSE,
    )

    # Drafts shorter than this are very unlikely to leak PII ("ok merci", "à demain", …).
    # Set conservatively — even an "OK 4242 4242 4242 4242" message would be > 35 chars
    # and the regex above would catch the digit run anyway.
    _SENTINEL_MIN_DRAFT_LEN = 50

    # Mapping from regex-detector categories → SensitiveDataType vocabulary.
    # Bug fix 2026-05-05: previous version mapped IP_ADDRESS to "technical",
    # which is NOT a member of the SensitiveDataType enum. The valid values
    # are {financial, personal, commercial, credential}. Mapping was silently
    # falling back to PERSONAL for IP — wrong category but not a crash.
    # Now mapped correctly per GDPR (IP is personal data) and SIRET is a
    # commercial registration number (commercial-secret-adjacent).
    _REGEX_CATEGORY_TO_TYPE = {
        "EMAIL": "personal",
        "PHONE": "personal",
        "CREDIT_CARD": "financial",
        "IBAN": "financial",
        "SSN_US": "personal",
        "SIN_CA": "personal",
        "SIRET": "commercial",
        "IP_ADDRESS": "personal",
        "API_KEY": "credential",
        "SECRET_KEYWORD": "credential",
        "FINANCIAL": "financial",
        "COMMERCIAL": "commercial",
    }

    def _detection_from_regex(self, pii_matches) -> SensitiveDataDetection:
        """Build a SensitiveDataDetection from regex-detector hits.

        Each PIIMatch becomes a SensitiveDataItem with:
          - data_type: derived from `_REGEX_CATEGORY_TO_TYPE`
          - description: short human label ("email address", "credit card", ...)
          - snippet: the matched substring (truncated to 80 chars for safety)
        """
        items: list[SensitiveDataItem] = []
        seen_spans: set[tuple[int, int]] = set()
        for m in pii_matches:
            span = (m.start, m.end)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            type_str = self._REGEX_CATEGORY_TO_TYPE.get(m.category, "personal")
            try:
                data_type = SensitiveDataType(type_str)
            except ValueError:
                data_type = SensitiveDataType.PERSONAL
            items.append(SensitiveDataItem(
                data_type=data_type,
                description=m.category.lower().replace("_", " "),
                snippet=(m.snippet[:80] + "…") if len(m.snippet) > 80 else m.snippet,
            ))
        return SensitiveDataDetection(
            is_sensitive=bool(items),
            confidence=0.95 if items else 0.0,  # regex hits are high-confidence
            detected_items=items,
            analysis_summary=f"Regex detector: {', '.join(m.category for m in pii_matches)}" if items else "",
        )

    def detect(self, draft_content: str, recipient: str) -> SensitiveDataDetection:
        """
        Analyse un brouillon pour détecter les données sensibles.

        Strategy (2026-05-05):
          1. Drafts shorter than `_SENTINEL_MIN_DRAFT_LEN` → safe (no LLM, no regex).
          2. When `USE_REGEX_PII_DETECTOR=true` (default), the pure-regex detector
             at `app.services.pii_detector` runs first:
              - Zero matches → safe (no LLM call).
              - Matches → return a structured detection built from regex hits.
                **No LLM call** — regex categories already cover what the
                downstream Cryptographer needs to redact.
          3. Legacy LLM fallback fires when the flag is off OR when the regex
             path raises (defensive — `re.error` from a future edit).

        Net result: the LLM call (formerly fired on every draft) is now
        invoked only via the rollback flag — eliminating ~$0.0003/draft
        and ~800ms/draft on the user-facing path.

        Args:
            draft_content: Le contenu du brouillon à analyser.
            recipient: L'adresse email du destinataire.

        Returns:
            SensitiveDataDetection avec le résultat de l'analyse.
        """
        if not draft_content:
            return SensitiveDataDetection.default()

        # Regex-first path. Run before the length gate so short but explicit
        # secrets/financial metrics are still blocked.
        try:
            from app.config import USE_REGEX_PII_DETECTOR as _use_regex
        except Exception:  # pragma: no cover — defensive only
            _use_regex = True

        if _use_regex:
            try:
                from app.services.pii_detector import detect_pii
                pii_matches = detect_pii(draft_content)
                if not pii_matches:
                    return SensitiveDataDetection.default()
                return self._detection_from_regex(pii_matches)
            except Exception as exc:
                # Defensive: a future regex edit could raise re.error or similar.
                # Fall through to the LLM legacy path so detection still happens.
                _logger.warning(
                    "SensitiveDataDetectorAgent: regex detector raised, "
                    "falling back to LLM path: %s", exc,
                )

        # Pre-filter: too short to leak meaningful data once deterministic
        # regex signals have been ruled out.
        if len(draft_content) < self._SENTINEL_MIN_DRAFT_LEN:
            return SensitiveDataDetection.default()

        # Legacy LLM fallback (USE_REGEX_PII_DETECTOR=false OR regex path raised).
        if not self._PII_PRE_FILTER.search(draft_content):
            return SensitiveDataDetection.default()

        user_context = f"Destinataire: {recipient}\n\nBrouillon à analyser:\n{draft_content}"

        try:
            response = self._llm.complete(
                system=SENSITIVE_DATA_DETECTOR_PROMPT,
                user=user_context,
                max_tokens=self.max_tokens
            )
            _track_token_usage(response)

            json_data = extract_json_from_response(
                response.content,
                default={"is_sensitive": False, "confidence": 0.0, "detected_items": [], "analysis_summary": ""},
                error_context="SensitiveDataDetectorAgent"
            )
            return self._parse_detection(json_data)

        except Exception as e:
            _logger.warning(f"SensitiveDataDetectorAgent.detect failed: {e}")
            return SensitiveDataDetection.default()


# ============================================================================
# UNIFIED EMAIL ANALYZER AGENT (P0.1 — Fusion pipeline per-email)
# ============================================================================

UNIFIED_EMAIL_ANALYZER_PROMPT = """Tu analyses un email entrant et retournes EN UN SEUL APPEL toutes les classifications utiles au pipeline downstream.

Output JSON STRICT (rien avant/après, pas de <thinking>, pas de paraphrase) :

{
  "category": "URGENT" | "IMPORTANT" | "NORMAL" | "NEWSLETTER" | "PROMO" | "CC_ONLY" | "SPAM",
  "category_confidence": 0.0-1.0,
  "intent": "INQUIRY" | "NEGOTIATION" | "FOLLOW_UP" | "OBJECTION" | "ESCALATION" | "INFORMATIONAL" | "OTHER",
  "intent_confidence": 0.0-1.0,
  "urgency": 0-100,
  "vip": 0-100,
  "sentiment": -1.0..1.0,
  "deadline": "<ISO date>" | null,
  "priority_score": 0-100,
  "tasks": [
    {"title": "...", "description": "...", "priority": "high"|"medium"|"low", "deadline": "<ISO>"|null}
  ]
}

Règles rapides :
- category : User en CC pas destinataire → CC_ONLY ; "unsubscribe"/diffusion → NEWSLETTER ou PROMO ; mot-clé urgence → URGENT ; demande client/business → IMPORTANT ; sinon NORMAL.
- intent : INQUIRY = question pricing/scope ; NEGOTIATION = budget/remise/contre-proposition ; FOLLOW_UP = relance ; OBJECTION = hésitation/sentiment négatif ; ESCALATION = demande humain explicite ; INFORMATIONAL = info factuelle sans action attendue ; OTHER sinon.
- urgency 0-100 : mots-clés urgent/ASAP/deadline/aujourd'hui/demain.
- vip 0-100 : importance expéditeur (domaine, titre signature).
- sentiment -1..1 : -1 négatif, 0 neutre, 1 positif.
- deadline : date ISO si mentionnée explicitement, sinon null.
- priority_score = urgency*0.4 + vip*0.3 + (sentiment+1)*15 (clamper 0..100).
- tasks : TOUTES les actions/tâches demandées (max 5). title verbe à l'infinitif ≤50 chars ; priority HIGH si "urgent"/deadline<24h, MEDIUM si demande client/<1 sem, LOW sinon. Si aucune tâche → tableau vide [].

Format strict, exécution déterministe (temperature=0)."""


@dataclass
class UnifiedEmailAnalyzerAgent:
    """Agent unifié qui fait classification + intent + prio + tasks en 1 appel.

    Audit 2026-05-04 (P0.1) : remplace 4 appels Haiku séquentiels (Classifier,
    classify_intent, Prioritizer, TaskExtractor) par 1 seul appel multi-output.

    Gains :
      - Latence : 4 RTT → 1 RTT (~3-5s gagnées par email)
      - Coût : ~75% sur les agents background (1 system prompt vs 4)
      - Cache : prompt fusionné ~600 tokens — sous le floor Haiku 2048t,
                donc cache_control n'augmente pas l'efficacité ici, mais le
                gain principal vient de la réduction du nombre d'appels.

    Note opérationnelle : actuellement le pipeline daemon.process_email()
    short-circuit à `daemon.py:2042-2044` (auto-draft désactivé), donc le
    gain immédiat est nul tant que le pipeline n'est pas réactivé. L'agent
    est implémenté pour être prêt quand auto-draft revient (et pour les
    callers qui invoquent classification + intent + prio en parallèle —
    ex: routes_emails.py:/analyze).
    """
    max_tokens: int = 1024
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Routes to ANTHROPIC_API_KEY_BACKGROUND like the legacy 4 agents.
        self._llm = get_container().llm_background

    _DEFAULT_RESULT = {
        "category": "NORMAL",
        "category_confidence": 0.5,
        "intent": "OTHER",
        "intent_confidence": 0.3,
        "urgency": 50,
        "vip": 50,
        "sentiment": 0.0,
        "deadline": None,
        "priority_score": 50,
        "tasks": [],
    }

    def analyze(
        self,
        email_content: str,
        sender: str = "",
        is_cc: bool = False,
    ) -> dict:
        """Analyse un email et retourne tous les outputs en 1 appel.

        Args:
            email_content : corps de l'email (sujet + body de préférence).
            sender : adresse de l'expéditeur (utile pour le scoring VIP).
            is_cc : True si l'utilisateur est en copie (force CC_ONLY).

        Returns:
            Dict avec category, intent, urgency, vip, sentiment, deadline,
            priority_score, tasks. Sur erreur LLM/parse, retourne les
            valeurs par défaut (NORMAL/OTHER/50/50/0/None/50/[]).
        """
        context_lines = []
        if is_cc:
            context_lines.append("[L'utilisateur est en COPIE, pas destinataire principal]")
        if sender:
            context_lines.append(f"Expéditeur : {sender}")
        context_lines.append("")
        context_lines.append(email_content)
        context = "\n".join(context_lines)

        try:
            response = self._llm.complete(
                system=UNIFIED_EMAIL_ANALYZER_PROMPT,
                user=context,
                max_tokens=self.max_tokens,
                temperature=0.0,
            )
            _track_token_usage(response)

            data = extract_json_from_response(
                response.content,
                default=self._DEFAULT_RESULT,
                error_context="UnifiedEmailAnalyzerAgent",
            )

            return self._sanitize(data)

        except Exception as e:
            _logger.warning(f"UnifiedEmailAnalyzerAgent.analyze failed: {e}")
            return dict(self._DEFAULT_RESULT)

    def _sanitize(self, data: dict) -> dict:
        """Clamp + valeurs par défaut sur tous les champs (defensive)."""
        out = dict(self._DEFAULT_RESULT)
        if not isinstance(data, dict):
            return out

        # Closed-vocabulary fields — drop unknown values
        cat = data.get("category")
        if cat in ("URGENT", "IMPORTANT", "NORMAL", "NEWSLETTER", "PROMO", "CC_ONLY", "SPAM"):
            out["category"] = cat
        intent = data.get("intent")
        if intent in ("INQUIRY", "NEGOTIATION", "FOLLOW_UP", "OBJECTION",
                      "ESCALATION", "INFORMATIONAL", "OTHER"):
            out["intent"] = intent

        # Numeric clamps
        def _clamp(v, lo, hi, default):
            try:
                return max(lo, min(hi, float(v)))
            except (TypeError, ValueError):
                return default

        out["category_confidence"] = _clamp(data.get("category_confidence"), 0.0, 1.0, 0.5)
        out["intent_confidence"] = _clamp(data.get("intent_confidence"), 0.0, 1.0, 0.3)
        out["urgency"] = int(_clamp(data.get("urgency"), 0, 100, 50))
        out["vip"] = int(_clamp(data.get("vip"), 0, 100, 50))
        out["sentiment"] = _clamp(data.get("sentiment"), -1.0, 1.0, 0.0)
        out["priority_score"] = int(_clamp(data.get("priority_score"), 0, 100, 50))

        # Deadline — accept string only, anything else → None
        dl = data.get("deadline")
        out["deadline"] = dl if isinstance(dl, str) and dl.strip() else None

        # Tasks list — keep at most 5, validate shape
        raw_tasks = data.get("tasks") or []
        if isinstance(raw_tasks, list):
            tasks = []
            for t in raw_tasks[:5]:
                if not isinstance(t, dict):
                    continue
                title = str(t.get("title", "")).strip()
                if not title:
                    continue
                prio = str(t.get("priority", "medium")).lower()
                if prio not in ("high", "medium", "low"):
                    prio = "medium"
                tasks.append({
                    "title": title[:50],
                    "description": str(t.get("description", "")).strip(),
                    "priority": prio,
                    "deadline": t.get("deadline") if isinstance(t.get("deadline"), str) else None,
                })
            out["tasks"] = tasks

        return out

    # Adapters for legacy callers — same return shape as the 4 individual agents
    def to_classification(self, result: dict) -> dict:
        """Adapter vers le format ClassifierAgent.classify()."""
        return {
            "category": result.get("category", "NORMAL"),
            "confidence": result.get("category_confidence", 0.5),
            "reason": "unified analyzer",
        }

    def to_priority(self, result: dict) -> dict:
        """Adapter vers le format PrioritizationAgent.analyze()."""
        return {
            "urgency": result.get("urgency", 50),
            "vip": result.get("vip", 50),
            "sentiment": result.get("sentiment", 0),
            "deadline": result.get("deadline"),
            "priority_score": result.get("priority_score", 50),
        }

    def to_tasks(self, result: dict) -> List[dict]:
        """Adapter vers le format TaskExtractorAgent.extract() raw dicts."""
        return list(result.get("tasks") or [])


@dataclass
class CryptographerAgent:
    """
    Agent orchestrateur pour l'anonymisation et la restauration de contenu.

    Combine le SensitiveDataDetectorAgent pour la détection et
    l'EncryptionPort pour le chiffrement du mapping de restauration.
    """

    _encryption: Optional["EncryptionPort"] = field(default=None, repr=False)
    _detector: Optional[SensitiveDataDetectorAgent] = field(default=None, repr=False)

    def __post_init__(self):
        if self._encryption is None:
            from app.infrastructure.adapters.encryption_adapter import FernetEncryptionAdapter
            object.__setattr__(self, "_encryption", FernetEncryptionAdapter())
        if self._detector is None:
            object.__setattr__(self, "_detector", SensitiveDataDetectorAgent())

    def anonymize(self, content: str, recipient: str) -> "AnonymizedResult":
        from app.application.anonymize_content import AnonymizeContentUseCase

        use_case = AnonymizeContentUseCase(
            detector=self._detector,
            encryption=self._encryption,
        )
        return use_case.execute(content, recipient)

    def restore(self, anonymized_content: str, encrypted_token: str) -> str:
        from app.application.restore_content import RestoreContentUseCase

        use_case = RestoreContentUseCase(encryption=self._encryption)
        return use_case.execute(anonymized_content, encrypted_token)


# ============================================================================
# PIPELINE DE TRAITEMENT
# ============================================================================

@dataclass
class EmailResult:
    """Résultat du traitement d'un email."""
    numero: int
    email_content: str
    human_response: str
    draft_v1: str
    critique: str
    draft_final: str
    status: str


def process_single_email(
    drafter: DrafterAgent,
    critic: CriticAgent,
    numero: int,
    email_content: str,
    human_response: str = ""
) -> EmailResult:
    """
    Traite un seul email avec le pipeline Drafter -> Critic -> Correction.

    Args:
        drafter: L'agent Drafter.
        critic: L'agent Critic.
        numero: Le numéro de l'email.
        email_content: Le contenu de l'email.
        human_response: La réponse humaine (pour comparaison).

    Returns:
        Le résultat du traitement.
    """
    # Étape 1 : Générer Draft V1
    draft_v1 = drafter.draft(email_content)

    # Étape 2 : Évaluation par le Critic
    critique = critic.evaluate(email_content, draft_v1)

    # Étape 3 : Correction si nécessaire
    if critic.is_valid(critique):
        draft_final = draft_v1
        status = "VALIDÉ V1"
    else:
        draft_final = drafter.revise(email_content, critique)
        status = "CORRIGÉ V2"

    return EmailResult(
        numero=numero,
        email_content=email_content,
        human_response=human_response,
        draft_v1=draft_v1,
        critique=critique,
        draft_final=draft_final,
        status=status
    )


# ============================================================================
# CONTEXT ANALYZER AGENT — REMOVED 2026-05-05
#
# `ContextAnalyzerAgent` was defined for ~6 months but never wired into any
# production code path. Per the audit grep on 2026-05-05, the only
# instantiations were in `tests/agents/test_context_analyzer.py` (deleted
# alongside this section). The actual relational-context capture is done
# by `ContactSummarizerAgent` (lazy summary, called from drafter prompt
# builders) and `WritingStyleAnalyzerAdapter` (style profile pre-computed
# during onboarding).
#
# The passive entity at `app/domain/entities/context_analysis.py` is kept
# because two TYPE_CHECKING imports reference it from
# `app/domain/entities/draft_generation.py` and `orchestration.py`. If we
# untangle those, the entity can also be removed in a follow-up.
# ============================================================================
# ============================================================================
# CONTACT SUMMARIZER AGENT
# ============================================================================

_ALLOWED_RELATION_TYPES = {
    "client", "colleague", "manager", "friend", "vendor", "prospect", "other"
}
_ALLOWED_TONES = {"formal", "semi_formal", "casual", "very_casual"}


@dataclass
class ContactSummarizerAgent:
    """Pre-computes a structured long-term summary of a contact relationship.

    Called lazily from the background post-draft thread when the summary
    is missing or stale. The output replaces the bulk of the conversation
    history in the drafter prompt, cutting ~9k tokens per draft.

    Uses Haiku (label LLM) and outputs strict JSON. On any error the
    agent returns None so callers can fall back to raw history.
    """

    model: str = MODEL_DEFAULT
    max_tokens: int = MAX_TOKENS_CONTACT_SUMMARY
    account_id: Optional[int] = None
    _llm: Optional[LLMPort] = field(default=None, repr=False)
    _agent_label: str = field(default="contact_summary", repr=False)

    def __post_init__(self):
        # Background contact summarizer — routes to ANTHROPIC_API_KEY_BACKGROUND.
        self._llm = get_container().llm_background

    @_attribute_to_agent
    def summarize(self, emails: list[dict], user_email: str = "") -> Optional[dict]:
        """Generate a structured summary from a list of past emails.

        Args:
            emails: Raw email dicts (sender, subject, date, body). Ideally
                    10-30 items — the most you have of the contact.
            user_email: User's own address, used to tag sent vs received.

        Returns:
            Dict matching the summary schema, or None if parsing fails
            or the email list is too small to be meaningful.
        """
        if not emails or len(emails) < 3:
            return None

        try:
            from app.prompts import get_contact_summarizer_prompts
            system, user = get_contact_summarizer_prompts(emails, user_email=user_email)

            response = self._llm.complete(
                system=system,
                user=user,
                max_tokens=self.max_tokens,
                temperature=0.2,
            )
            _track_token_usage(response)

            parsed = extract_json_from_response(response.content or "")
            if not isinstance(parsed, dict):
                _logger.warning("ContactSummarizerAgent: JSON parse did not yield a dict")
                return None

            return self._validate_and_clean(parsed)
        except Exception as e:
            _logger.warning(f"ContactSummarizerAgent: summarization failed: {e}")
            return None

    @staticmethod
    def _validate_and_clean(data: dict) -> dict:
        """Coerce the LLM output into the strict schema with safe defaults."""
        def _str_list(key: str, max_items: int) -> list[str]:
            raw = data.get(key) or []
            if not isinstance(raw, list):
                return []
            return [str(x).strip() for x in raw if x and isinstance(x, (str, int, float))][:max_items]

        relation = str(data.get("relation_type") or "other").lower().strip()
        if relation not in _ALLOWED_RELATION_TYPES:
            relation = "other"

        tone = str(data.get("habitual_tone") or "semi_formal").lower().strip()
        if tone not in _ALLOWED_TONES:
            tone = "semi_formal"

        language = str(data.get("language") or "").lower().strip()[:5]

        last = data.get("last_interaction_summary") or ""
        if not isinstance(last, str):
            last = ""

        return {
            "relation_type": relation,
            "habitual_tone": tone,
            "language": language,
            "recurring_topics": _str_list("recurring_topics", 5),
            "user_formulas_opening": _str_list("user_formulas_opening", 3),
            "user_formulas_closing": _str_list("user_formulas_closing", 3),
            "contact_formulas_opening": _str_list("contact_formulas_opening", 3),
            "key_facts": _str_list("key_facts", 6),
            "last_interaction_summary": last[:500],
        }
