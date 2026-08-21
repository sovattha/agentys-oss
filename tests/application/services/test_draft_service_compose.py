"""Tests Phase 2b — DraftService.generate(ctx, mode='compose').

Couvre la première implémentation réelle de la logique métier dans
DraftService (Phase 2a livrait juste le squelette qui levait NotImplementedError).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.application.dto.draft_context import DraftContext
from app.application.dto.draft_result import DraftServiceResult
from app.application.services.draft_service import DraftService
from app.domain.entities.self_critique import SelfCritique
from app.domain.ports.llm_port import LLMResponse, LLMStreamChunk


# ---------------------------------------------------------------------------
# FakeLLM — minimal implementation of LLMPort for unit tests
# ---------------------------------------------------------------------------

@dataclass
class FakeDrafterLLM:
    """Drafter LLM mock — paramaterizable response + streaming support."""
    response_content: str = "Bonjour Alice, voici la proposition demandée. Cordialement,"
    input_tokens: int = 600
    output_tokens: int = 80
    raise_on_call: Optional[Exception] = None
    stream_chunks: list[str] = field(default_factory=list)
    # Phase 2c (cache breakpoints): system peut être str (legacy) ou SystemSegment[].
    last_system: Optional[object] = None
    last_user: Optional[str] = None
    call_count: int = 0

    @property
    def last_system_text(self) -> str:
        """Normalise last_system en string concaténée pour les assertions tests."""
        if self.last_system is None:
            return ""
        if isinstance(self.last_system, str):
            return self.last_system
        return "\n\n".join(getattr(s, "text", str(s)) for s in self.last_system if s)

    @property
    def name(self) -> str:
        return "fake-drafter"

    @property
    def model(self) -> str:
        return "fake-haiku-drafter"

    def complete(self, system, user, max_tokens=1024, temperature=None):
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        if self.raise_on_call:
            raise self.raise_on_call
        return LLMResponse(
            content=self.response_content,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=self.model,
        )

    def stream(self, system, user, max_tokens=1024, temperature=None):
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        if self.raise_on_call:
            raise self.raise_on_call
        # If stream_chunks provided, yield them; else split response_content
        chunks = self.stream_chunks or [self.response_content]
        cumulative_out = 0
        for i, chunk in enumerate(chunks):
            cumulative_out += len(chunk.split())
            is_final = (i == len(chunks) - 1)
            yield LLMStreamChunk(
                text=chunk,
                input_tokens=self.input_tokens if i == 0 else 0,
                output_tokens_so_far=cumulative_out,
                is_final=is_final,
                model=self.model,
            )

    def is_available(self) -> bool:
        return True


@dataclass
class FakeSelfCritiqueLLM:
    """Self-critique LLM mock."""
    response_content: str = '{"self_score": 85, "risks": [], "a_confirmer_count": 0, "confidence": "high"}'
    input_tokens: int = 200
    output_tokens: int = 50
    call_count: int = 0

    @property
    def name(self) -> str:
        return "fake-sc"

    @property
    def model(self) -> str:
        return "fake-haiku-sc"

    def complete(self, system, user, max_tokens=200, temperature=None):
        self.call_count += 1
        return LLMResponse(
            content=self.response_content,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=self.model,
        )

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    drafter_llm: Optional[FakeDrafterLLM] = None,
    self_critique_llm: Optional[FakeSelfCritiqueLLM] = None,
) -> DraftService:
    """Build a DraftService with injected fake LLMs (bypasses Container)."""
    drafter_llm = drafter_llm or FakeDrafterLLM()
    self_critique_llm = self_critique_llm or FakeSelfCritiqueLLM()

    def drafter_factory():
        return drafter_llm

    def self_critique_factory():
        from app.self_critique_agent import SelfCritiqueAgent
        agent = SelfCritiqueAgent.__new__(SelfCritiqueAgent)
        agent._llm = self_critique_llm  # type: ignore[attr-defined]
        return agent

    return DraftService(
        drafter_factory=drafter_factory,
        self_critique_factory=self_critique_factory,
    )


def _make_compose_ctx(
    knowledge_base: str = "",
    style_profile: Optional[str] = None,
    instructions: str = "Propose 3 options de tarification.",
    compose_id: Optional[str] = None,
) -> DraftContext:
    return DraftContext(
        recipient_email="alice@example.com",
        subject="Proposition tarifaire",
        instructions=instructions,
        knowledge_base=knowledge_base,
        user_email="me@example.com",
        style_profile=style_profile,
        compose_id=compose_id,
        account_id=1,
    )


# ---------------------------------------------------------------------------
# Test : compose blocking mode
# ---------------------------------------------------------------------------

class TestComposeBlockingMode:
    def test_returns_draft_service_result(self):
        service = _make_service()
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        assert isinstance(result, DraftServiceResult)
        assert result.body  # non-empty
        assert "Alice" in result.body or "Cordialement" in result.body

    def test_calls_drafter_once_in_blocking_mode(self):
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(compose_id=None)  # no streaming
        service.generate(ctx, mode="compose")
        assert drafter.call_count == 1

    def test_user_prompt_contains_instructions(self):
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(instructions="VERY_SPECIFIC_INSTRUCTION_TOKEN")
        service.generate(ctx, mode="compose")
        assert "VERY_SPECIFIC_INSTRUCTION_TOKEN" in (drafter.last_user or "")

    def test_user_prompt_contains_recipient_and_subject(self):
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx()
        service.generate(ctx, mode="compose")
        full = (drafter.last_user or "") + drafter.last_system_text
        assert "alice@example.com" in full
        assert "Proposition tarifaire" in full

    def test_compose_does_not_set_escalated(self):
        # Per locked decision : Critic+V2 jamais en compose
        service = _make_service()
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        assert result.escalated is False
        assert result.version_index == 1
        assert result.critique is None  # No external Critic in compose

    def test_returns_pipeline_info_dict(self):
        service = _make_service()
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        assert isinstance(result.pipeline_info, dict)


# ---------------------------------------------------------------------------
# Test : Self-Critique shadow mode
# ---------------------------------------------------------------------------

class TestSelfCritiqueShadow:
    """Shadow mode is gated behind SELF_CRITIQUE_SHADOW_ENABLED=true (F-05,
    audit 2026-04-30). All tests in this class enable the flag — the
    no-flag path is covered by `test_self_critique_skipped_when_flag_off`
    below.
    """

    @pytest.fixture(autouse=True)
    def _enable_shadow_mode(self, monkeypatch):
        monkeypatch.setenv("SELF_CRITIQUE_SHADOW_ENABLED", "true")
        monkeypatch.setenv("SELF_CRITIQUE_SAMPLE_RATE", "1.0")

    def test_self_critique_is_called_after_draft(self):
        sc_llm = FakeSelfCritiqueLLM()
        service = _make_service(self_critique_llm=sc_llm)
        ctx = _make_compose_ctx()
        service.generate(ctx, mode="compose")
        # Self-Critique should have been invoked exactly once
        assert sc_llm.call_count == 1

    def test_self_critique_result_attached_to_result(self):
        service = _make_service()
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        assert result.self_critique is not None
        assert isinstance(result.self_critique, SelfCritique)
        assert result.self_critique.self_score == 85  # default mock value

    def test_self_critique_in_pipeline_info(self):
        # Must be present in pipeline_info for the frontend AIDraftingPanel to display
        service = _make_service()
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        assert "self_critique" in result.pipeline_info
        sc_info = result.pipeline_info["self_critique"]
        assert sc_info["self_score"] == 85
        assert sc_info["confidence"] == "high"

    def test_self_critique_failure_does_not_block_draft(self):
        # If self-critique LLM crashes, the draft must still be returned
        # (shadow mode = best-effort, never blocks)
        bad_sc = FakeSelfCritiqueLLM(response_content="not valid json {")
        service = _make_service(self_critique_llm=bad_sc)
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        # Draft generated normally
        assert result.body
        # Self-critique returns a "failed" verdict (self_score=0 forces escalation
        # in reply mode, but compose ignores it — escalated still False)
        assert result.self_critique is not None
        assert result.self_critique.self_score == 0  # parse failed → 0
        assert result.escalated is False  # COMPOSE NEVER ESCALATES


class TestSelfCritiqueShadowGate:
    """F-05 (audit 2026-04-30): shadow mode is gated by
    SELF_CRITIQUE_SHADOW_ENABLED env (default OFF). Until Phase 4 sentinel
    consumes the telemetry, paying the 2× Haiku cost is wasted budget.
    """

    def test_shadow_skipped_when_flag_unset(self, monkeypatch):
        monkeypatch.delenv("SELF_CRITIQUE_SHADOW_ENABLED", raising=False)
        sc_llm = FakeSelfCritiqueLLM()
        service = _make_service(self_critique_llm=sc_llm)
        ctx = _make_compose_ctx()
        result = service.generate(ctx, mode="compose")
        # Shadow gate OFF → self-critique LLM never invoked
        assert sc_llm.call_count == 0
        # Result still returns successfully — shadow is not load-bearing
        assert result.body
        assert result.self_critique is None

    def test_shadow_skipped_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("SELF_CRITIQUE_SHADOW_ENABLED", "false")
        sc_llm = FakeSelfCritiqueLLM()
        service = _make_service(self_critique_llm=sc_llm)
        ctx = _make_compose_ctx()
        service.generate(ctx, mode="compose")
        assert sc_llm.call_count == 0

    def test_shadow_runs_when_flag_truthy(self, monkeypatch):
        monkeypatch.setenv("SELF_CRITIQUE_SAMPLE_RATE", "1.0")
        for truthy in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("SELF_CRITIQUE_SHADOW_ENABLED", truthy)
            sc_llm = FakeSelfCritiqueLLM()
            service = _make_service(self_critique_llm=sc_llm)
            ctx = _make_compose_ctx()
            service.generate(ctx, mode="compose")
            assert sc_llm.call_count == 1, f"value {truthy!r} should enable shadow"

    def test_compose_never_calls_critic_external(self):
        # No critic factory should be invoked in compose mode
        critic_called = {"yes": False}

        def critic_factory():
            critic_called["yes"] = True

        service = DraftService(
            drafter_factory=lambda: FakeDrafterLLM(),
            self_critique_factory=lambda: _build_real_sc(),
            critic_factory=critic_factory,
        )
        ctx = _make_compose_ctx()
        service.generate(ctx, mode="compose")
        assert critic_called["yes"] is False, "Critic must NOT be called in compose mode"


def _build_real_sc():
    from app.self_critique_agent import SelfCritiqueAgent
    agent = SelfCritiqueAgent.__new__(SelfCritiqueAgent)
    agent._llm = FakeSelfCritiqueLLM()  # type: ignore[attr-defined]
    return agent


# ---------------------------------------------------------------------------
# Test : KB Savoir injection
# ---------------------------------------------------------------------------

class TestSavoirInjection:
    def test_savoir_section_injected_when_present(self):
        kb = """## Profil
- Nom : Alex

## Savoir

### TARIFS : Quel est le prix du plan Premium ?

99€/mois HT pour 5 utilisateurs.

## Règles

- bla
"""
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(knowledge_base=kb)
        service.generate(ctx, mode="compose")
        # The Savoir section should appear in the system prompt
        sp = drafter.last_system_text
        assert "TARIFS" in sp
        assert "99€/mois HT" in sp
        # The non-Savoir sections should NOT (doublons profile)
        assert "Nom : Alex" not in sp

    def test_no_savoir_no_injection(self):
        kb = """## Profil
- Nom : Alex

## Règles

- Tutoiement
"""
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(knowledge_base=kb)
        service.generate(ctx, mode="compose")
        sp = drafter.last_system_text
        # No Savoir mention since it's absent from KB
        assert "## Savoir" not in sp

    def test_empty_kb_does_not_break(self):
        drafter = FakeDrafterLLM()
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(knowledge_base="")
        result = service.generate(ctx, mode="compose")
        assert result.body  # No crash


# ---------------------------------------------------------------------------
# Test : streaming mode (compose_id present)
# ---------------------------------------------------------------------------

class TestComposeStreamingMode:
    def test_streaming_yields_via_generator(self):
        # When compose_id is set, the service should use the LLM stream() method.
        # Phase 2b implementation : service runs stream synchronously and accumulates,
        # WebSocket emission is handled by the wrapper endpoint (Pass C).
        drafter = FakeDrafterLLM(stream_chunks=["Bonjour ", "Alice, ", "voici."])
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(compose_id="compose-session-123")
        result = service.generate(ctx, mode="compose")
        # The body should equal the concatenation of chunks
        assert "Bonjour" in result.body
        assert "Alice" in result.body
        # Drafter was called via stream() — at least once
        assert drafter.call_count == 1

    def test_streaming_does_not_drop_token_in_final_chunk(self):
        # Review R4 : the last chunk may carry text AND is_final=True.
        # The accumulator must capture that token before exiting the loop.
        drafter = FakeDrafterLLM(stream_chunks=["A", "B", "C"])
        service = _make_service(drafter_llm=drafter)
        ctx = _make_compose_ctx(compose_id="cid")
        result = service.generate(ctx, mode="compose")
        assert result.body == "ABC", f"Last token dropped : got {result.body!r}"


class TestNoAccountIdResilience:
    def test_compose_with_no_account_id_does_not_crash(self):
        # Review R6 : account_id None must not break the flow
        service = _make_service()
        ctx = DraftContext(
            recipient_email="alice@example.com",
            subject="Test",
            instructions="Write something",
            knowledge_base="",
            user_email="me@example.com",
            account_id=None,
        )
        result = service.generate(ctx, mode="compose")
        assert isinstance(result, DraftServiceResult)
        assert result.body


# ---------------------------------------------------------------------------
# Test : reply mode still raises (Phase 2c)
# ---------------------------------------------------------------------------

class TestReplyModeNotImplemented:
    def test_reply_mode_still_raises_not_implemented(self):
        service = _make_service()
        ctx = _make_compose_ctx()
        with pytest.raises(NotImplementedError) as exc_info:
            service.generate(ctx, mode="reply")
        assert "Phase 2c" in str(exc_info.value) or "reply" in str(exc_info.value).lower()

    def test_invalid_mode_still_raises_value_error(self):
        service = _make_service()
        ctx = _make_compose_ctx()
        with pytest.raises(ValueError):
            service.generate(ctx, mode="banana")  # type: ignore[arg-type]
