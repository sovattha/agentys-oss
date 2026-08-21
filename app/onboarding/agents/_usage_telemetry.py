# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Per-agent LLM usage telemetry for the onboarding pipeline.

Each onboarding worker agent (Profile / Knowledge / Style / Label) makes a
single Haiku call (plus rare empty-result retries). The ``LLMResponse``
already carries ``input_tokens`` / ``output_tokens`` / ``stop_reason`` (see
``app/domain/ports/llm_port.py``) — the agents just used to discard them.

``record_agent_usage`` surfaces them per-agent so we can:

  - **right-size ``max_tokens``**: ``out`` well below ``max`` with
    ``stop=end_turn`` means there is headroom to lower the cap; ``stop=
    max_tokens`` means the call was *truncated* and the cap must NOT be
    lowered (ideally raised). This is the single signal that makes cutting
    the cap safe instead of guesswork.
  - **find the latency-dominating agent**: the four agents run in a
    parallel pool (``orchestrator.run``), so the scan's analysis latency is
    ``max(per-agent duration)`` — knowing which agent that is tells us where
    to spend effort.
  - **catch retry / timeout waste**: ``attempts > 1`` doubles an agent's
    latency and cost for that run.

It emits one grep-friendly ``[ONBOARDING_AGENT_USAGE]`` INFO line per agent
in every environment (prod included). When capture is enabled — by the
measurement harness ``scripts/measure_onboarding_tokens.py`` — it also
records a structured dict so the harness can tabulate without parsing logs.

Telemetry must never break the pipeline: every public function swallows its
own errors.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Opt-in capture sink. ``None`` (default) = capture disabled; a list = the
# harness wants structured records. Guarded by a lock because the agents run
# in a ThreadPoolExecutor and may append concurrently.
_capture_lock = threading.Lock()
_capture: Optional[List[dict]] = None


def enable_capture() -> None:
    """Start collecting structured usage records (replaces any prior buffer)."""
    global _capture
    with _capture_lock:
        _capture = []


def reset_capture() -> None:
    """Stop collecting and drop the buffer."""
    global _capture
    with _capture_lock:
        _capture = None


def get_capture() -> List[dict]:
    """Return a snapshot copy of the captured records (empty if disabled)."""
    with _capture_lock:
        return list(_capture) if _capture is not None else []


def record_agent_usage(
    agent: str,
    response: Any,
    max_tokens: int,
    duration_ms: float,
    attempts: int = 1,
) -> Optional[dict]:
    """Log + optionally capture one agent's LLM usage. Never raises.

    Args:
        agent: short agent name ("profile" | "knowledge" | "style" | "label").
        response: the ``LLMResponse`` returned by ``LLMPort.complete`` (only
            duck-typed attributes are read, so a mock/None is tolerated).
        max_tokens: the cap that was passed to ``complete`` for this call.
        duration_ms: wall-clock time spent in the agent's LLM call(s).
        attempts: how many ``complete`` attempts ran (retries included).

    Returns:
        The structured record dict (also appended to the capture buffer when
        enabled), or ``None`` if telemetry failed.
    """
    try:
        out_tok = int(getattr(response, "output_tokens", 0) or 0)
        in_tok = int(getattr(response, "input_tokens", 0) or 0)
        cache_r = int(getattr(response, "cache_read_input_tokens", 0) or 0)
        stop = str(getattr(response, "stop_reason", "") or "?")
        model = str(getattr(response, "model", "") or "?")
        max_tokens = int(max_tokens or 0)
        # used_pct = how much of the budget the model actually consumed. Low %
        # with stop=end_turn => safe to shrink max_tokens. Near 100% or
        # stop=max_tokens => truncated, leave the cap alone (or raise it).
        used_pct = round(100.0 * out_tok / max_tokens, 1) if max_tokens else 0.0
        truncated = stop == "max_tokens"

        record = {
            "agent": agent,
            "model": model,
            "input_tokens": in_tok,
            "cache_read_input_tokens": cache_r,
            "output_tokens": out_tok,
            "max_tokens": max_tokens,
            "used_pct": used_pct,
            "stop_reason": stop,
            "truncated": truncated,
            "attempts": int(attempts or 1),
            "duration_ms": int(duration_ms),
        }

        logger.info(
            "[ONBOARDING_AGENT_USAGE] agent=%s model=%s in=%d cache_r=%d out=%d "
            "max=%d used_pct=%.1f stop=%s truncated=%s attempts=%d dur_ms=%d",
            agent, model, in_tok, cache_r, out_tok, max_tokens, used_pct,
            stop, truncated, record["attempts"], record["duration_ms"],
        )

        with _capture_lock:
            if _capture is not None:
                _capture.append(record)

        return record
    except Exception:  # telemetry must never break the analysis pipeline
        logger.debug("record_agent_usage failed", exc_info=True)
        return None
