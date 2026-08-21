# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Issue #682 — compose + refine prompt-cache contract.

Both `/api/emails/compose` (legacy blocking inline path) and `/api/refine-text`
build their system prompt by concatenating a fixed rules block with one or
more per-call directives (style_context / mandatory_opening / tone_directive /
expertise). Pre-#682 those concatenated strings were marked cacheable as a
single Anthropic content block — the per-call suffix invalidated the cache
prefix on every request, producing the 0% cache_hit_rate observed in
`[USAGE_STATS]`. Post-#682 the same content is shipped as a `list[SystemSegment]`
with the static rules cacheable and the dynamic suffix non-cacheable.

The Anthropic adapter (`_build_anthropic_system_blocks`) maps each
SystemSegment 1:1 onto a content block and places `cache_control: ephemeral`
on the ones marked cacheable. These tests verify the route handlers send the
right shape — they do NOT exercise Anthropic itself.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import jwt as _pyjwt
import pytest

from app.domain.ports.llm_port import LLMResponse, SystemSegment


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """Mint a JWT Bearer header — required by /refine-text and /compose."""
    from app.api.auth import JWT_ALGORITHM, JWT_SECRET
    token = _pyjwt.encode(
        {
            "sub": sub,
            "email": email,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@dataclass
class _CapturedCall:
    """One call to the mock LLM. `system` may be `str` or `list[SystemSegment]`."""
    system: object = None
    user: str = ""
    kwargs: dict = field(default_factory=dict)


@pytest.fixture
def mock_llm_capture():
    """Capture each `complete(...)` call so a test can assert on the shape.

    Returns a `(captured_calls, mock_llm)` tuple. Tests append-only — they
    read the list after firing the route.
    """
    captured: list[_CapturedCall] = []

    def _complete(system=None, user="", **kw):
        captured.append(_CapturedCall(system=system, user=user, kwargs=kw))
        return LLMResponse(
            content="OK", input_tokens=10, output_tokens=5, model="mock-haiku",
        )

    mock_llm = MagicMock()
    mock_llm.complete.side_effect = _complete

    from app.infrastructure.container import get_container
    container = get_container()
    container._llm_drafting = mock_llm
    container._llm_label = mock_llm
    # Surgical refine routes to llm_drafting_smart — stub the same mock so
    # both the standard and surgical paths populate `captured`.
    container._llm_drafting_smart = mock_llm
    yield captured, mock_llm
    container._llm_drafting = None
    container._llm_label = None
    container._llm_drafting_smart = None


# ---------------------------------------------------------------------------
# /api/emails/compose — legacy blocking inline path
# ---------------------------------------------------------------------------


class TestComposeSystemSegments:
    def test_blocking_compose_sends_system_as_segment_list(
        self, client, mock_llm_capture
    ):
        """The blocking compose path must pass `system=list[SystemSegment]`
        so the Anthropic adapter places `cache_control: ephemeral` on the
        static rules + COMPOSE_QUALITY_GUARDRAILS prefix only."""
        captured, _ = mock_llm_capture
        resp = client.post(
            "/api/emails/compose",
            json={
                "to": "alice@example.com",
                "subject": "Hello",
                "instructions": "Confirm the meeting",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        assert captured, "LLM was not called"

        system_arg = captured[-1].system
        assert isinstance(system_arg, list), (
            f"compose must pass `system` as list[SystemSegment]; got "
            f"{type(system_arg).__name__}. Without this the cache key "
            f"changes per recipient and prompt caching is dead."
        )
        assert all(isinstance(s, SystemSegment) for s in system_arg)
        assert system_arg[0].cacheable is True
        # The first segment is the byte-stable rules + guardrails block. It
        # must contain a marker from the COMPOSE_QUALITY_GUARDRAILS template
        # to confirm we snapshotted AFTER the guardrails were appended (the
        # whole point of #682 is to widen the cached prefix).
        from app.prompts import COMPOSE_QUALITY_GUARDRAILS
        # We pick a substring stable across template edits — the leading
        # rule of the guardrails block. If COMPOSE_QUALITY_GUARDRAILS is
        # itself heavily reworked, update this assertion to match.
        assert COMPOSE_QUALITY_GUARDRAILS[:200] in system_arg[0].text

    def test_blocking_compose_dynamic_block_is_not_cacheable(
        self, client, mock_llm_capture
    ):
        """If per-call directives are present they must live in a separate
        non-cacheable segment. Marking them cacheable would create a cache
        breakpoint that almost never hits — wasted writes."""
        captured, _ = mock_llm_capture
        client.post(
            "/api/emails/compose",
            json={
                "to": "alice@example.com",
                "subject": "Hello",
                "instructions": "Hi there",
            },
            headers=_auth_headers(),
        )
        system_arg = captured[-1].system
        # In the test environment there's no per-contact style_context or
        # mandatory_opening, so a fresh recipient produces only the static
        # segment. We still assert the second segment, when present, is
        # non-cacheable — guard against a regression that flips it.
        for seg in system_arg[1:]:
            assert seg.cacheable is False, (
                "Dynamic segment must be cacheable=False so per-call values "
                "don't pollute the cache prefix."
            )

    def test_blocking_compose_static_prefix_byte_stable_across_recipients(
        self, client, mock_llm_capture
    ):
        """Two compose calls to DIFFERENT recipients must produce the SAME
        segment 0 text — that's the property that lets cross-recipient
        cache reuse fire. The dynamic segment (if any) is allowed to differ.
        """
        captured, _ = mock_llm_capture
        for recipient in ("a@example.com", "b@example.com"):
            client.post(
                "/api/emails/compose",
                json={
                    "to": recipient,
                    "subject": "S",
                    "instructions": "Body",
                },
                headers=_auth_headers(),
            )

        assert len(captured) == 2
        sys_a, sys_b = captured[0].system, captured[1].system
        assert isinstance(sys_a, list) and isinstance(sys_b, list)
        assert sys_a[0].text == sys_b[0].text, (
            "Static compose prefix must not depend on the recipient address. "
            "If this regresses, recipient-derived content has leaked back "
            "into segment 0 and cross-recipient cache hits are gone."
        )


# ---------------------------------------------------------------------------
# /api/refine-text
# ---------------------------------------------------------------------------


class TestRefineTextSystemSegments:
    def test_refine_text_sends_system_as_segment_list(
        self, client, mock_llm_capture
    ):
        """Standard refine must also use the segment list shape."""
        captured, _ = mock_llm_capture
        resp = client.post(
            "/api/refine-text",
            json={
                "text": "Mes notes brutes pour un email.",
                "instruction": "Transforme en email professionnel.",
                "to": "alice@example.com",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        assert captured, "LLM was not called"

        system_arg = captured[-1].system
        assert isinstance(system_arg, list), (
            f"refine-text must pass `system` as list[SystemSegment]; got "
            f"{type(system_arg).__name__}."
        )
        assert all(isinstance(s, SystemSegment) for s in system_arg)
        assert system_arg[0].cacheable is True
        # Non-surgical rules block starts with the text-transformation engine
        # header. Asserting on a unique substring pins the cacheable content
        # to the static rules — not a per-call directive.
        assert "text transformation engine" in system_arg[0].text

    def test_refine_text_surgical_sends_system_as_segment_list(
        self, client, mock_llm_capture
    ):
        """Surgical refine bypasses style/opening/tone directives entirely
        (per the existing `if not surgical and …` guards). The resulting
        system is segment-list of length 1 — still cacheable, still typed
        as SystemSegment so the contract is uniform across both branches.
        """
        captured, _ = mock_llm_capture
        resp = client.post(
            "/api/refine-text",
            json={
                "text": "Je veux te voir demain à 20h.",
                "instruction": "remplace 20h par 21h",
                "to": "alice@example.com",
                "surgical": True,
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        assert captured
        system_arg = captured[-1].system
        assert isinstance(system_arg, list)
        assert len(system_arg) == 1, (
            f"Surgical mode bypasses dynamic directives, so the system list "
            f"must collapse to a single cacheable segment. Got {len(system_arg)}."
        )
        assert system_arg[0].cacheable is True
        assert "SURGICAL text editor" in system_arg[0].text

    def test_refine_text_static_prefix_byte_stable_across_recipients(
        self, client, mock_llm_capture
    ):
        """Cross-recipient invariance for refine-text — same property as
        compose. Two refines of different recipients (no per-contact data
        in the test env, so dynamic stays empty) must yield identical
        segment 0 so the cache prefix matches.
        """
        captured, _ = mock_llm_capture
        for recipient in ("a@example.com", "b@example.com"):
            client.post(
                "/api/refine-text",
                json={
                    "text": "Notes",
                    "instruction": "Rédige un email",
                    "to": recipient,
                },
                headers=_auth_headers(),
            )
        assert len(captured) == 2
        sys_a, sys_b = captured[0].system, captured[1].system
        assert sys_a[0].text == sys_b[0].text
