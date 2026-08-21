# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-06 — Prompt-cache warmup on /daemon WebSocket connect (2026-05-05).

Anthropic's prompt cache TTL is 5 minutes. Without warmup, the first draft
of a session pays a full cache-miss on the static system prefix
(~1.5–2k tokens of input billing + 100–200ms TTFT). This handler fires a
tiny dummy completion right after `join_room` so the user's first real
draft hits a cache.

Contract pinned by this test:
- Default ON, env var WS_CACHE_WARMUP=false disables.
- Debounced: a second connect inside _CACHE_WARMUP_DEBOUNCE seconds is a no-op.
- Best-effort: any exception is swallowed.
- Background thread (must not block the WS connect handshake).
"""
from __future__ import annotations

import threading
from unittest.mock import patch, MagicMock


def test_default_enabled(monkeypatch):
    monkeypatch.delenv("WS_CACHE_WARMUP", raising=False)
    from app.api.websocket import _cache_warmup_enabled
    assert _cache_warmup_enabled() is True


def test_disabled_via_env(monkeypatch):
    from app.api.websocket import _cache_warmup_enabled
    for val in ("false", "0", "no", "off"):
        monkeypatch.setenv("WS_CACHE_WARMUP", val)
        assert _cache_warmup_enabled() is False


def test_debounce_blocks_repeated_warmups(monkeypatch):
    """Two warmups for the same room within debounce window → second is a no-op."""
    monkeypatch.setenv("WS_CACHE_WARMUP", "true")
    import app.api.websocket as ws
    # Reset state for a clean slate
    with ws._cache_warmup_lock:
        ws._cache_warmup_last_at.clear()

    threads_started: list[threading.Thread] = []
    real_thread = threading.Thread

    def _spy_thread(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        threads_started.append(t)
        return t

    with patch.object(ws.threading, "Thread", side_effect=_spy_thread):
        ws._maybe_warm_prompt_cache("room-A")
        ws._maybe_warm_prompt_cache("room-A")  # debounced

    # Only one thread should have been spawned (the second call no-ops).
    assert len(threads_started) == 1, (
        "Debounce broken — both warmups fired threads. Anthropic billing "
        "would compound on every reconnect."
    )


def test_disabled_env_fires_zero_threads(monkeypatch):
    monkeypatch.setenv("WS_CACHE_WARMUP", "false")
    import app.api.websocket as ws
    with ws._cache_warmup_lock:
        ws._cache_warmup_last_at.clear()

    started = []
    real_thread = threading.Thread

    with patch.object(ws.threading, "Thread", side_effect=lambda *a, **k: started.append(real_thread(*a, **k)) or started[-1]):
        ws._maybe_warm_prompt_cache("room-disabled")

    assert started == [], "WS_CACHE_WARMUP=false must short-circuit before spawn"


def test_warmup_swallows_llm_exception():
    """A failing LLM call must not bubble out — the WS handshake cannot fail."""
    import app.api.websocket as ws
    with ws._cache_warmup_lock:
        ws._cache_warmup_last_at.clear()

    # Patch get_container to raise — the worker should swallow.
    fake_container = MagicMock()
    fake_container.llm_drafting.complete.side_effect = RuntimeError("boom")
    with patch("app.infrastructure.container.get_container", return_value=fake_container):
        ws._maybe_warm_prompt_cache("room-err")
        # Wait briefly for daemon thread to finish (best-effort)
        import time
        time.sleep(0.05)
    # If we reached here without raising, the swallow worked.


def test_warmup_records_system_feature(monkeypatch):
    """Warmup calls should be identifiable in token_usage_log."""
    monkeypatch.setenv("WS_CACHE_WARMUP", "true")
    import app.api.websocket as ws

    with ws._cache_warmup_lock:
        ws._cache_warmup_last_at.clear()

    captured = []

    class _SyncThread:
        def __init__(self, *args, **kwargs):
            self._target = kwargs["target"]

        def start(self):
            self._target()

    class _FakeLLM:
        def complete(self, **_kwargs):
            from app.infrastructure.token_usage_writer import record_usage

            record_usage(
                model="claude-haiku-4-5-20251001",
                input_tokens=133,
                output_tokens=1,
            )
            return MagicMock(content="")

    fake_container = MagicMock()
    fake_container.llm_drafting = _FakeLLM()

    with patch.object(ws.threading, "Thread", side_effect=lambda *a, **k: _SyncThread(*a, **k)):
        with patch("app.infrastructure.container.get_container", return_value=fake_container):
            with patch("app.prompts.load_knowledge_base", return_value="kb"):
                with patch(
                    "app.infrastructure.token_usage_writer.enqueue",
                    side_effect=lambda record: captured.append(record),
                ):
                    ws._maybe_warm_prompt_cache("room-system")

    assert len(captured) == 1
    row = captured[0]
    assert row.agent == "ws_cache_warmup"
    assert row.feature == "ws_cache_warmup"
