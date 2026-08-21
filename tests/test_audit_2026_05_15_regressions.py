# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the audit findings F-01 / F-03 / F-04 / F-05 / F-06
landed 2026-05-15 in response to the audit at
`tasks/audit-reports/2026-05-14_2320_draft-pipeline-regressions/`.

Each test pins the contract the fix establishes. If a future refactor
regresses one of these contracts, the corresponding test fails — those
failures are the proof the fix held.

Layout:
  * `TestF04SelfConsistencyGateRespectsNoneDecision` — best-of-2 must fire
    when classifier passes `decision=None` (pre-P1.4 behaviour restored).
  * `TestF05StreamingComposeSanitizesProviderErrors` — the streaming
    compose `except` branch must sanitise the WS `error` payload through
    `classify_llm_error` (no `request_id=`, no `console.anthropic.com`).
  * `TestF01BlockingComposeDoubleTruncation` — when both the initial call
    AND the retry hit `stop_reason="max_tokens"`, the blocking response
    carries an explicit `truncated: true` flag.
  * `TestF03LLMStreamChunkPropagatesStopReason` — the multi-block adapter
    sets `stop_reason` on the final chunk and `_compose_stream_bg`
    propagates `truncated: true` through `emit_draft_complete`.
  * `TestF06SelfConsistencyWallClockBudget` — best-of-2 honours a SHARED
    wall-clock budget (not 60s per future); double-timeout returns within
    that budget, not 2× it.

The tests use lightweight mocks — no live LLM, no live DB, no Flask client.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# F-04 — COMPLEX self-consistency must still fire when `decision is None`.
# ─────────────────────────────────────────────────────────────────────────────


class TestF04SelfConsistencyGateRespectsNoneDecision:
    """Audit F-04 — `_generate_complex(decision=None)` must run best-of-2.

    Pre-P1.4 baseline: `if SELF_CONSISTENCY_COMPLEX_ENABLED and not instructions`.
    Post-P1.4 (pre-F-04): `... and _cscore >= 70` with `_cscore = ... if decision else 0`.
    Post-F-04: `... else 100` so a None decision still clears the 70-floor.

    Reaching `_generate_complex` already implies the upstream tier decision
    was COMPLEX; a missing `RoutingDecision` shouldn't downgrade the path.
    """

    def test_none_decision_runs_best_of_two(self):
        """With decision=None and no instructions, _generate_standard fires twice."""
        from app.smart_routing import SmartRouter

        router = SmartRouter()
        router._account_id = 1  # pretend we resolved an account

        # _generate_standard is the workhorse; counting its calls counts samples.
        call_count = {"n": 0}

        def fake_generate_standard(**kwargs):
            call_count["n"] += 1
            return (f"draft-{call_count['n']}", [])

        with patch.object(router, "_generate_standard", side_effect=fake_generate_standard):
            with patch("app.smart_routing._pick_best_complex_draft",
                       return_value=("draft-1", "a_wins_test")):
                result = router._generate_complex(
                    email_content="From: a@b.com\nSubject: s\n\nbody",
                    conversation_history=None,
                    instructions="",  # MUST be empty — instructions short-circuit best-of-2
                    user_email="u@x.com",
                    decision=None,
                    thread_context=None,
                )

        assert call_count["n"] == 2, (
            "F-04: when decision is None and no user instructions are provided, "
            "_generate_complex MUST still run best-of-2 (two samples). "
            "Pre-fix behavior treated None as `_cscore=0`, failing the >=70 gate "
            "and falling through to a single _generate_standard call — a silent "
            "quality regression on the classifier-failure path."
        )
        assert result.draft == "draft-1"

    def test_low_score_decision_skips_best_of_two(self):
        """Negative control: when decision.complexity_score < threshold, only 1 call."""
        from app.smart_routing import SmartRouter
        from app.smart_routing import RoutingDecision, RoutingTier

        router = SmartRouter()
        router._account_id = 1

        # Score 50 sits in the 50-69 "COMPLEX-ish" slice that P1.4 explicitly
        # cuts down to single-shot. A genuine decision should be honoured.
        decision = RoutingDecision(
            tier=RoutingTier.COMPLEX,
            complexity_score=50,
            reason="test",
        )

        call_count = {"n": 0}

        def fake_generate_standard(**kwargs):
            call_count["n"] += 1
            return (f"draft-{call_count['n']}", [])

        with patch.object(router, "_generate_standard", side_effect=fake_generate_standard):
            router._generate_complex(
                email_content="From: a@b.com\nSubject: s\n\nbody",
                conversation_history=None,
                instructions="",
                user_email="u@x.com",
                decision=decision,
                thread_context=None,
            )

        assert call_count["n"] == 1, (
            "Negative-control invariant for F-04: when decision exists with a "
            "complexity_score BELOW the self-consistency threshold (50 < 70), "
            "the P1.4 gate correctly takes the single-shot path. If this fails "
            "the F-04 fix over-corrected and the gate is dead."
        )

    def test_explicit_instructions_skip_best_of_two(self):
        """Negative control: explicit user instructions force single-shot regardless."""
        from app.smart_routing import SmartRouter

        router = SmartRouter()
        router._account_id = 1

        call_count = {"n": 0}

        def fake_generate_standard(**kwargs):
            call_count["n"] += 1
            return (f"draft-{call_count['n']}", [])

        with patch.object(router, "_generate_standard", side_effect=fake_generate_standard):
            router._generate_complex(
                email_content="From: a@b.com\nSubject: s\n\nbody",
                conversation_history=None,
                instructions="reply YES",  # user-driven → deterministic single-shot
                user_email="u@x.com",
                decision=None,
                thread_context=None,
            )

        assert call_count["n"] == 1, (
            "Negative-control: explicit user instructions short-circuit best-of-2 "
            "(self-consistency is for the no-instruction COMPLEX workload). "
            "F-04 fix must not regress this."
        )


# ─────────────────────────────────────────────────────────────────────────────
# F-05 — Streaming compose error path must sanitise provider-info leaks.
# ─────────────────────────────────────────────────────────────────────────────


class TestF05StreamingComposeSanitizesProviderErrors:
    """Audit F-05 — the WS `draft_error` payload must NOT carry the raw
    Anthropic exception string (which includes `request_id=`,
    `console.anthropic.com`, model name, and sometimes a prompt prefix).

    Pre-fix: `emit_draft_error(error=str(e))`. Post-fix: classify via
    `classify_llm_error()` and emit the safe FR user_msg, mirroring the
    blocking-branch convention at routes_misc.py:843-853.
    """

    def _fake_llm_raising(self, exc_to_raise):
        """A minimal LLM stand-in whose `.stream()` raises the given exception
        on the first iteration."""
        llm = MagicMock()

        def _stream(*args, **kwargs):
            raise exc_to_raise
            yield  # pragma: no cover — make this a generator for the consumer

        llm.stream = _stream
        return llm

    def test_llmbillingerror_does_not_leak_provider_details(self):
        """LLMBillingError carrying request_id + console URL → safe FR message."""
        from app.api.routes_misc import _compose_stream_bg
        from app.domain.exceptions import LLMBillingError

        # Provider-info-laden message — exactly the shape Anthropic SDK
        # emits on a 402 (insufficient credits). The fix MUST scrub this.
        leaky_message = (
            "Your credit balance is too low to access the Anthropic API. "
            "Please add credits at https://console.anthropic.com/settings/billing. "
            "request_id=req_01abc234DEF567"
        )
        exc = LLMBillingError(provider="claude", message=leaky_message)
        llm = self._fake_llm_raising(exc)

        captured = {"error": None}

        def fake_emit_draft_error(*, email_id, error, retry_count=0, account_id=None):
            captured["error"] = error

        with patch("app.api.websocket.emit_draft_error",
                   side_effect=fake_emit_draft_error):
            _compose_stream_bg(
                compose_id="test-f05-billing",
                system_prompt="sys",
                user_prompt="usr",
                llm=llm,
                typical_signature=None,
                account_id=1,
            )

        emitted = captured["error"]
        assert emitted is not None, "emit_draft_error must be called on exception"

        # Hard invariants — provider-info markers MUST NOT survive.
        assert "request_id" not in emitted, (
            f"F-05: request_id leaked through emit_draft_error → {emitted!r}"
        )
        assert "console.anthropic.com" not in emitted, (
            f"F-05: console.anthropic.com leaked → {emitted!r}"
        )
        assert "req_01abc234" not in emitted, (
            f"F-05: SDK request_id token leaked → {emitted!r}"
        )
        # And the user_msg from classify_llm_error must reach the frontend.
        assert "Credit IA insuffisant" in emitted or "Crédit" in emitted or "indisponible" in emitted, (
            f"F-05: expected the safe FR user_msg, got {emitted!r}"
        )

    def test_non_llm_exception_falls_back_to_generic_message(self):
        """A non-LLMError exception (e.g. a sudden KeyError inside the stream)
        must emit the generic 'Erreur interne du serveur.' — NEVER raw str(e)."""
        from app.api.routes_misc import _compose_stream_bg

        leaky_exc = RuntimeError(
            "Internal connection-string corrupted: postgres://user:secretpw@host:5432/db"
        )
        llm = self._fake_llm_raising(leaky_exc)

        captured = {"error": None}

        def fake_emit_draft_error(*, email_id, error, retry_count=0, account_id=None):
            captured["error"] = error

        with patch("app.api.websocket.emit_draft_error",
                   side_effect=fake_emit_draft_error):
            _compose_stream_bg(
                compose_id="test-f05-runtime",
                system_prompt="sys",
                user_prompt="usr",
                llm=llm,
                typical_signature=None,
                account_id=1,
            )

        emitted = captured["error"]
        assert emitted == "Erreur interne du serveur.", (
            f"F-05: non-LLMError must fall back to a generic message, not the "
            f"raw exception (which may carry secrets). Got: {emitted!r}"
        )
        assert "secretpw" not in emitted, "F-05: secrets must not leak"
        assert "postgres://" not in emitted, "F-05: connection strings must not leak"


# ─────────────────────────────────────────────────────────────────────────────
# F-01 — Blocking compose double-truncation must surface `truncated: true`.
# ─────────────────────────────────────────────────────────────────────────────


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """JWT Bearer header for @require_auth-gated endpoints (matches the
    pattern in tests/test_api_compose_email.py)."""
    import time as _time
    import jwt as _pyjwt
    from app.api.auth import JWT_ALGORITHM, JWT_SECRET
    token = _pyjwt.encode(
        {"sub": sub, "email": email,
         "iat": int(_time.time()), "exp": int(_time.time()) + 3600},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def flask_client():
    """A Flask test client wired to the production app factory."""
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


class TestF01BlockingComposeDoubleTruncation:
    """Audit F-01 — when the blocking compose retry's response ALSO has
    `stop_reason="max_tokens"`, the JSON body must carry `truncated: true`
    and a structured `code: COMPOSE_TRUNCATED` so the frontend can render
    "réponse tronquée — réessayer" instead of silently committing a half-word.

    Pre-fix (P2.9 surgical retry): the second response was committed at
    line 816 unconditionally, returning HTTP 200 with a half-word body and
    no signal.
    """

    def _patch_drafting_llm(self, monkeypatch, complete_side_effect):
        """Replace container.llm_drafting.complete with `complete_side_effect`.

        Bypasses the autouse compose fixture by directly assigning a fresh
        MagicMock to the private container slots, so this test stays
        independent of `tests/test_api_compose_email.py`'s autouse.
        """
        from app.infrastructure.container import get_container
        container = get_container()
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=complete_side_effect)
        container._llm_label = mock_llm
        container._llm_drafting = mock_llm
        return mock_llm

    def test_double_truncation_flags_truncated_true(self, flask_client, monkeypatch):
        from app.domain.ports.llm_port import LLMResponse

        # BOTH calls return stop_reason="max_tokens" — the exact scenario the
        # P2.9 retry is supposed to handle but pre-F-01 just committed silently.
        truncated_response = LLMResponse(
            content="Réponse coupée mi-",
            input_tokens=200, output_tokens=500,
            model="claude-haiku-4-5", stop_reason="max_tokens",
        )
        mock_llm = self._patch_drafting_llm(
            monkeypatch, complete_side_effect=[truncated_response, truncated_response],
        )

        resp = flask_client.post(
            "/api/emails/compose",
            json={"to": "x@y.com", "subject": "long",
                  "instructions": "rédige un email de 1500 mots"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["truncated"] is True, (
            f"F-01: double-truncation must set `truncated: true` in the JSON. "
            f"Got {data!r}"
        )
        assert data.get("code") == "COMPOSE_TRUNCATED", (
            f"F-01: must also set code='COMPOSE_TRUNCATED' so the frontend can "
            f"key off a stable machine-readable signal. Got {data!r}"
        )
        # The retry must have fired — second call at max_tokens=1024.
        assert mock_llm.complete.call_count == 2, (
            "F-01: P2.9 retry-on-truncation must have fired (2 LLM calls). "
            "If this drops to 1, the retry path itself broke."
        )
        # The retry's max_tokens must be 1024 (raised from 500).
        retry_kwargs = mock_llm.complete.call_args_list[1].kwargs
        assert retry_kwargs.get("max_tokens") == 1024, (
            f"F-01: retry must use max_tokens=1024, got {retry_kwargs.get('max_tokens')!r}"
        )

    def test_single_truncation_then_clean_retry_no_flag(self, flask_client, monkeypatch):
        """Negative control: first call truncates, retry succeeds → no flag."""
        from app.domain.ports.llm_port import LLMResponse

        truncated = LLMResponse(
            content="Coupé mi-", input_tokens=200, output_tokens=500,
            model="claude-haiku-4-5", stop_reason="max_tokens",
        )
        clean = LLMResponse(
            content="Complet et terminé.\n\nCordialement,",
            input_tokens=200, output_tokens=300,
            model="claude-haiku-4-5", stop_reason="end_turn",
        )
        mock_llm = self._patch_drafting_llm(
            monkeypatch, complete_side_effect=[truncated, clean],
        )

        resp = flask_client.post(
            "/api/emails/compose",
            json={"to": "x@y.com", "subject": "ok",
                  "instructions": "petite question"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "truncated" not in data or data["truncated"] is False, (
            f"F-01 negative control: when the retry returns stop_reason=end_turn "
            f"(clean), the truncated flag MUST NOT be set. Got {data!r}"
        )
        assert data.get("code") != "COMPOSE_TRUNCATED"
        assert mock_llm.complete.call_count == 2  # retry still fired

    def test_no_truncation_first_call_only_no_flag(self, flask_client, monkeypatch):
        """Negative control: first call already clean → no retry, no flag."""
        from app.domain.ports.llm_port import LLMResponse

        clean = LLMResponse(
            content="Salut Alex,\n\nC'est bon pour mardi.\n\nÀ bientôt,",
            input_tokens=180, output_tokens=80,
            model="claude-haiku-4-5", stop_reason="end_turn",
        )
        mock_llm = self._patch_drafting_llm(monkeypatch, complete_side_effect=[clean])

        resp = flask_client.post(
            "/api/emails/compose",
            json={"to": "x@y.com", "subject": "ok",
                  "instructions": "confirme rendez-vous mardi"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "truncated" not in data or data["truncated"] is False
        assert data["final_draft"]["content"]  # body actually present
        assert mock_llm.complete.call_count == 1, "no retry when first call is clean"


# ─────────────────────────────────────────────────────────────────────────────
# F-03 — Streaming compose truncation contract.
#   * LLMStreamChunk carries stop_reason.
#   * ClaudeAdapter.stream() populates it on the final chunk.
#   * _compose_stream_bg propagates it to emit_draft_complete(truncated=True).
# ─────────────────────────────────────────────────────────────────────────────


class TestF03LLMStreamChunkPropagatesStopReason:
    """Audit F-03 — when the streaming Anthropic call ends because the model
    hit `max_tokens`, every layer must propagate that signal:

      1. `LLMStreamChunk` schema carries `stop_reason: str | None = None`.
      2. The Claude adapter sets it on the FINAL chunk.
      3. `_compose_stream_bg` reads the final chunk's `stop_reason` and
         passes `truncated=True` to `emit_draft_complete`.
      4. `emit_draft_complete`'s WS payload carries `truncated: true`.

    Pre-fix, none of layers 1-4 existed and a half-word body was streamed
    to the user with no signal. P2.9 explicitly punted on streaming
    truncation; F-03 closes the gap.
    """

    def test_llmstreamchunk_schema_has_stop_reason_field(self):
        """Layer 1: the dataclass schema MUST carry stop_reason."""
        from app.domain.ports.llm_port import LLMStreamChunk
        # Default value: None (legacy chunks don't carry it).
        c = LLMStreamChunk(text="hello", is_final=True)
        assert hasattr(c, "stop_reason")
        assert c.stop_reason is None
        # Explicit set must round-trip.
        c2 = LLMStreamChunk(text="", is_final=True, stop_reason="max_tokens")
        assert c2.stop_reason == "max_tokens"

    def test_compose_stream_bg_propagates_truncated_to_emit(self):
        """Layers 3+4: when the final chunk carries stop_reason="max_tokens",
        emit_draft_complete is called with truncated=True."""
        from app.api.routes_misc import _compose_stream_bg
        from app.domain.ports.llm_port import LLMStreamChunk

        # Fake LLM emits a few text chunks then a final chunk with
        # stop_reason="max_tokens" (the regression scenario).
        def _fake_stream(*args, **kwargs):
            yield LLMStreamChunk(text="Salut Alex, ", is_final=False)
            yield LLMStreamChunk(text="merci pour ton message. ", is_final=False)
            yield LLMStreamChunk(text="Je voulais te dire que", is_final=False)
            yield LLMStreamChunk(
                text="", is_final=True, stop_reason="max_tokens",
            )

        llm = MagicMock()
        llm.stream = _fake_stream

        captured = {"call": None}

        def fake_emit_draft_complete(**kwargs):
            captured["call"] = kwargs

        # Stub emit_draft_chunk too so the bg thread can write chunks
        # without going through the real WS layer.
        def fake_emit_draft_chunk(**kwargs):
            pass

        with patch("app.api.websocket.emit_draft_chunk",
                   side_effect=fake_emit_draft_chunk), \
             patch("app.api.websocket.emit_draft_complete",
                   side_effect=fake_emit_draft_complete):
            _compose_stream_bg(
                compose_id="test-f03-trunc",
                system_prompt="sys",
                user_prompt="usr",
                llm=llm,
                typical_signature=None,
                account_id=1,
            )

        call = captured["call"]
        assert call is not None, "emit_draft_complete must be called on stream end"
        assert call.get("truncated") is True, (
            f"F-03: when the final chunk has stop_reason='max_tokens', "
            f"_compose_stream_bg MUST pass truncated=True to emit_draft_complete. "
            f"Got kwargs: {call!r}"
        )
        # Body should still be the accumulated text (we don't drop it — the
        # user can keep the partial if it's good enough).
        assert "Salut Alex" in call.get("draft_content", ""), (
            "F-03: truncation must not discard the partial body — the user "
            "can still use what was generated."
        )

    def test_compose_stream_bg_clean_finish_no_truncated_flag(self):
        """Negative control: stop_reason='end_turn' → no truncated flag."""
        from app.api.routes_misc import _compose_stream_bg
        from app.domain.ports.llm_port import LLMStreamChunk

        def _fake_stream(*args, **kwargs):
            yield LLMStreamChunk(text="Salut Alex,\n\nC'est OK.\n\nÀ bientôt,",
                                 is_final=False)
            yield LLMStreamChunk(text="", is_final=True, stop_reason="end_turn")

        llm = MagicMock()
        llm.stream = _fake_stream

        captured = {"call": None}

        def fake_emit_draft_complete(**kwargs):
            captured["call"] = kwargs

        with patch("app.api.websocket.emit_draft_chunk", new=MagicMock()), \
             patch("app.api.websocket.emit_draft_complete",
                   side_effect=fake_emit_draft_complete):
            _compose_stream_bg(
                compose_id="test-f03-clean",
                system_prompt="sys",
                user_prompt="usr",
                llm=llm,
                typical_signature=None,
                account_id=1,
            )

        call = captured["call"]
        assert call is not None
        assert call.get("truncated") is False, (
            "F-03 negative control: a clean end_turn finish must NOT set "
            f"truncated=True. Got kwargs: {call!r}"
        )

    def test_emit_draft_complete_payload_carries_truncated_only_when_true(self):
        """Layer 4: the WS payload includes `truncated: true` only when the
        flag is true (legacy subscribers see no new field on clean drafts).
        """
        from app.api import websocket as ws_mod

        captured_payloads = []

        # Stub the SocketIO emit layer to capture the payload that would have
        # gone over the wire.
        fake_socketio = MagicMock()
        fake_socketio.emit = lambda event, payload, namespace, to: captured_payloads.append(
            ("emit", event, payload, namespace, to)
        )

        with patch.object(ws_mod, "get_socketio", return_value=fake_socketio), \
             patch.object(ws_mod, "_resolve_ws_room", return_value="user_1"), \
             patch.object(ws_mod, "emit_to_account", return_value=False):
            # Truncated path → payload carries truncated:true
            ws_mod.emit_draft_complete(
                email_id="e1", draft_content="half-w",
                confidence=0.85, generation_time_ms=1000,
                tokens_used=500, truncated=True,
            )
            # Clean path → no truncated key in payload
            ws_mod.emit_draft_complete(
                email_id="e2", draft_content="clean",
                confidence=0.85, generation_time_ms=1000,
                tokens_used=100, truncated=False,
            )

        # Both emits captured.
        emits = [p for p in captured_payloads if p[0] == "emit" and p[1] == "draft_complete"]
        assert len(emits) == 2, captured_payloads
        truncated_payload = emits[0][2]
        clean_payload = emits[1][2]

        assert truncated_payload.get("truncated") is True, (
            f"F-03 layer 4: truncated:true must reach the WS payload. "
            f"Got: {truncated_payload!r}"
        )
        assert "truncated" not in clean_payload, (
            f"F-03 backward-compat: a clean payload must NOT carry the new "
            f"`truncated` key (else legacy subscribers see an unexpected "
            f"field). Got: {clean_payload!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# F-06 — COMPLEX self-consistency must honour a SHARED wall-clock budget.
# ─────────────────────────────────────────────────────────────────────────────


class TestF06SelfConsistencyWallClockBudget:
    """Audit F-06 — the best-of-2 self-consistency path must NOT serialise
    its per-future timeouts. Pre-fix two `.result(timeout=60)` calls ran
    sequentially, so a double-timeout produced an empty draft after 120s
    wall-clock. Post-fix `wait((fut_a, fut_b), timeout=BUDGET)` shares a
    single budget.

    Tests use a small monkeypatched budget (2s) and short sleeps so the
    suite stays fast.
    """

    def _short_budget(self, monkeypatch, seconds: float = 2.0):
        """Force the module-level budget down to keep tests under 5s."""
        import app.smart_routing as smart_routing_mod
        monkeypatch.setattr(
            smart_routing_mod, "_COMPLEX_SC_WALL_CLOCK_BUDGET_SEC", seconds
        )

    def test_double_timeout_respects_shared_budget(self, monkeypatch):
        """Both samples hang past the budget → wall-clock ≈ budget, not 2× budget."""
        from app.smart_routing import SmartRouter, RoutingDecision, RoutingTier

        self._short_budget(monkeypatch, seconds=2.0)

        router = SmartRouter()
        router._account_id = 1
        decision = RoutingDecision(
            tier=RoutingTier.COMPLEX,
            complexity_score=80,  # clears the >=70 self-consistency floor
            reason="test",
        )

        def slow_generate_standard(**kwargs):
            time.sleep(5.0)  # 5s > 2s budget — both samples will time out
            return ("never-returned", [])

        with patch.object(router, "_generate_standard",
                          side_effect=slow_generate_standard):
            t_start = time.monotonic()
            result = router._generate_complex(
                email_content="From: a@b.com\nSubject: s\n\nbody",
                conversation_history=None,
                instructions="",
                user_email="u@x.com",
                decision=decision,
                thread_context=None,
            )
            t_elapsed = time.monotonic() - t_start

        # Pre-F-06 worst case: ~10s (2 × 5s sequential sleeps).
        # Post-F-06: ≈ 2s (shared budget — both timeouts fold together).
        assert t_elapsed < 3.5, (
            f"F-06: wall-clock for double-timeout MUST be ≤ budget(2s)+tolerance(1.5s). "
            f"Got {t_elapsed:.2f}s. Pre-fix this was ~10s (2x sequential per-future timeouts). "
            f"If this assert trips, the wait()/cancel pattern regressed back to sequential .result()."
        )
        # Both timed out → empty draft. The existing empty-handler at the
        # caller layer surfaces this; F-06 explicitly does NOT add another
        # single-shot fallback that would re-introduce the 120s pathology.
        assert result.draft == "", (
            f"F-06: when both samples time out, result.draft must be empty (let "
            f"caller's empty-handler kick in). Got draft={result.draft!r}"
        )

    def test_one_succeeds_one_times_out_uses_winner(self, monkeypatch):
        """When one sample completes and the other doesn't, use the winner."""
        from app.smart_routing import SmartRouter, RoutingDecision, RoutingTier

        self._short_budget(monkeypatch, seconds=2.0)

        router = SmartRouter()
        router._account_id = 1
        decision = RoutingDecision(
            tier=RoutingTier.COMPLEX, complexity_score=80, reason="test",
        )

        # First call returns fast and clean; second call hangs past the budget.
        call_count = {"n": 0}

        def mixed_generate_standard(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ("fast clean draft", [])
            time.sleep(5.0)  # second one hangs > 2s budget
            return ("never-returned", [])

        with patch.object(router, "_generate_standard",
                          side_effect=mixed_generate_standard), \
             patch("app.smart_routing._pick_best_complex_draft",
                   return_value=("fast clean draft", "a_wins_only_a_done")):
            t_start = time.monotonic()
            result = router._generate_complex(
                email_content="From: a@b.com\nSubject: s\n\nbody",
                conversation_history=None,
                instructions="",
                user_email="u@x.com",
                decision=decision,
                thread_context=None,
            )
            t_elapsed = time.monotonic() - t_start

        assert t_elapsed < 3.5, (
            f"F-06: single-success path still bounded by budget. Got {t_elapsed:.2f}s"
        )
        assert result.draft == "fast clean draft", (
            f"F-06: when one sample completes (other times out), use the winner. "
            f"Got draft={result.draft!r}"
        )

    def test_both_fast_succeeds_normally(self, monkeypatch):
        """Positive control: both fast → wall-clock minimal, best-of-2 fires."""
        from app.smart_routing import SmartRouter, RoutingDecision, RoutingTier

        self._short_budget(monkeypatch, seconds=2.0)

        router = SmartRouter()
        router._account_id = 1
        decision = RoutingDecision(
            tier=RoutingTier.COMPLEX, complexity_score=80, reason="test",
        )

        call_count = {"n": 0}

        def fast_generate_standard(**kwargs):
            call_count["n"] += 1
            return (f"draft-{call_count['n']}", [])

        with patch.object(router, "_generate_standard",
                          side_effect=fast_generate_standard), \
             patch("app.smart_routing._pick_best_complex_draft",
                   return_value=("draft-1", "a_wins_test")):
            t_start = time.monotonic()
            result = router._generate_complex(
                email_content="From: a@b.com\nSubject: s\n\nbody",
                conversation_history=None,
                instructions="",
                user_email="u@x.com",
                decision=decision,
                thread_context=None,
            )
            t_elapsed = time.monotonic() - t_start

        assert t_elapsed < 1.5, (
            f"F-06 positive control: fast both should complete in <1s. Got {t_elapsed:.2f}s"
        )
        assert call_count["n"] == 2, "best-of-2: must run TWO samples"
        assert result.draft == "draft-1"
