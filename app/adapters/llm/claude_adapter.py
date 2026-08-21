# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter LLM pour Claude (Anthropic).
"""

import logging
import os

from typing import Generator
from app.domain.ports import LLMPort, LLMResponse, LLMStreamChunk
from app.domain.ports.llm_port import SystemSegment
from app.domain.exceptions import (
    LLMAuthenticationError,
    LLMBillingError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMContextLengthError,
    LLMResponseError,
    LLMModelNotFoundError,
    InvalidBoundsError,
)

_logger = logging.getLogger(__name__)


# Anthropic limits cache_control breakpoints to 4 per request. Callers that
# pass a SystemSegment list with more cacheable=True entries get the FIRST
# four marked and the rest collapsed into the last marked block (so prefix
# caching still works, just with coarser granularity than the caller asked
# for). We log once per process when a request hits the cap so ops can
# surface it.
_MAX_CACHE_BREAKPOINTS = 4
_MAX_BREAKPOINT_WARNED = False


def _safe_int(value, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_anthropic_system_blocks(system) -> list[dict]:
    """Convert the LLMPort `system` argument into the Anthropic API shape.

    Args:
        system: Either a `str` (legacy single-block path) or an iterable of
            `SystemSegment` objects (multi-block path).

    Returns:
        List of `{type, text, cache_control?}` dicts ready to pass as the
        Anthropic `system` field. Always at least one block. At most 4
        cache_control markers across the list.

    Backward-compat: when `system` is a `str`, output is exactly the
    single-block-with-cache-control list the adapter has emitted since
    the prompt-caching wiring landed (audit 2026-05-04 P0.2).
    """
    global _MAX_BREAKPOINT_WARNED

    # Legacy path: bare string → one cacheable block. Same shape as before.
    if isinstance(system, str):
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    # Multi-block path: iterable of SystemSegment.
    segments = list(system)
    if not segments:
        # Defensive: empty list is a caller bug, but treat as empty system
        # rather than crashing — Anthropic accepts an empty string.
        return [{"type": "text", "text": "", "cache_control": {"type": "ephemeral"}}]

    # Validate types — fail loud rather than silently passing wrong shape.
    for seg in segments:
        if not isinstance(seg, SystemSegment):
            raise TypeError(
                f"Expected SystemSegment, got {type(seg).__name__}. "
                f"Pass a SystemSegment list (multi-block) or a plain str (single block)."
            )

    # Count requested breakpoints and clamp to the API limit.
    cacheable_indices = [i for i, s in enumerate(segments) if s.cacheable]
    if len(cacheable_indices) > _MAX_CACHE_BREAKPOINTS:
        # Keep the first 3 markers exactly as requested and shift the 4th
        # marker to the LAST cacheable segment (so the trailing prefix is
        # still cached as one chunk). This degrades gracefully without
        # throwing — the over-marked path is over-engineering, not a bug.
        keep = set(cacheable_indices[: _MAX_CACHE_BREAKPOINTS - 1])
        keep.add(cacheable_indices[-1])
        if not _MAX_BREAKPOINT_WARNED:
            _logger.warning(
                "ClaudeAdapter: %d cache breakpoints requested, capped at %d. "
                "Caller should pre-merge segments. (Warned once per process.)",
                len(cacheable_indices), _MAX_CACHE_BREAKPOINTS,
            )
            _MAX_BREAKPOINT_WARNED = True
    else:
        keep = set(cacheable_indices)

    blocks: list[dict] = []
    for i, seg in enumerate(segments):
        block = {"type": "text", "text": seg.text}
        if i in keep:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


def _log_usage(model: str, usage, kind: str) -> bool:
    """Emit a single grep-friendly ``[USAGE_STATS]`` line per LLM call.

    Audit 2026-05-04: prompt caching is wired (`cache_control: ephemeral`)
    on every system block, but we have no observability on whether it
    actually fires in prod. This log line surfaces the four fields a
    sentinel needs to compute cache hit rate, mean cost-per-call, and
    truncation rate without scraping API responses.

    Audit 2026-05-06: in addition to the log line, the call now updates
    a module-level rolling-window counter (`_cache_stats_*`) so the admin
    dashboard / `/api/admin/llm-stats` endpoint can serve cache hit rate
    without scraping logs.

    Fields:
        model        : actual model used
        kind         : ``complete`` | ``stream`` (different cache behaviour
                       expected — stream has lower hit rate empirically)
        in           : non-cached input tokens
        cache_w      : cached_creation_input_tokens (cache write, 1.25x cost)
        cache_r      : cached_read_input_tokens (cache hit, 0.10x cost)
        out          : output tokens
        cache_hit_rate : cache_r / (cache_r + cache_w + in), or 0.0 if no input
    """
    if usage is None:
        return False
    try:
        in_tok = _safe_int(getattr(usage, "input_tokens", 0))
        cache_w = _safe_int(getattr(usage, "cache_creation_input_tokens", 0))
        cache_r = _safe_int(getattr(usage, "cache_read_input_tokens", 0))
        out_tok = _safe_int(getattr(usage, "output_tokens", 0))
        denom = in_tok + cache_w + cache_r
        hit_rate = (cache_r / denom) if denom else 0.0
        _logger.info(
            "[USAGE_STATS] model=%s kind=%s in=%d cache_w=%d cache_r=%d out=%d cache_hit_rate=%.3f",
            model, kind, in_tok, cache_w, cache_r, out_tok, hit_rate,
        )
        _record_cache_stats(in_tok, cache_w, cache_r, out_tok)
        try:
            from app.infrastructure.cost_manager import get_cost_manager

            get_cost_manager().record_usage(
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                agent_name=f"claude_{kind}",
                cache_creation_input_tokens=cache_w,
                cache_read_input_tokens=cache_r,
                persist=False,
            )
        except Exception:
            pass
        try:
            from app.infrastructure.llm_attribution import current_agent
            from app.infrastructure.token_usage_writer import record_usage

            agent = current_agent()
            if agent == "unknown":
                agent = f"claude_{kind}"
            record_usage(
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_creation_input_tokens=cache_w,
                cache_read_input_tokens=cache_r,
                agent=agent,
            )
            return True
        except Exception:
            pass
    except Exception:  # pragma: no cover — telemetry must never break the call
        pass
    return False


# ----------------------------------------------------------------------------
# Cache hit-rate counters (audit 2026-05-06)
# ----------------------------------------------------------------------------
# Bounded history of recent calls. Counts and tokens are aggregated for the
# entire process lifetime; rolling-window stats use the last N entries
# (default 1000) so a transient cache-busting deploy is observable without
# being amplified by ancient samples.
import threading as _cache_threading
import collections as _cache_collections

_cache_stats_lock = _cache_threading.Lock()
_cache_stats_total: dict = {"in": 0, "cache_w": 0, "cache_r": 0, "out": 0, "calls": 0}
_cache_stats_recent: _cache_collections.deque = _cache_collections.deque(maxlen=1000)
_cache_stats: dict[str, dict[str, int]] = {}
_cache_stats_last_log_at = 0.0

# P0.3 (2026-05-14) — periodic cache-health emission.
#
# The per-call `[USAGE_STATS]` line gives you visibility on a single request.
# That's the wrong signal to alert on (any one short prompt can legitimately
# under-cache). What ops actually wants to know is: *over the last N calls
# of meaningful size, is the cache earning its keep?*
#
# We emit two log lines for that:
#   * `[CACHE_HEALTH]`  — every `_CACHE_ALERT_PERIOD` calls, an INFO line
#     with the rolling stats. Heartbeat for dashboards.
#   * `[CACHE_HIT_ALERT]` — same cadence, WARNING level, ONLY when the
#     rolling sample is large enough AND the hit rate has collapsed.
#     This is the line a sentinel grep should fire on.
#
# Thresholds picked from the P0.1 telemetry: pre-fix prod was 0.000 across
# 64/64 calls; post-fix we expect ≥ 0.30 on a steady-state workload (every
# draft after #1 in a 5-min session). 0.10 as the alarm bar leaves room
# for cold starts and short prompts without false-firing on regressions.
_CACHE_ALERT_PERIOD = 100        # emit health line every N calls
_CACHE_ALERT_MIN_SAMPLE = 50     # but only after at least N tail entries
_CACHE_ALERT_LOW_THRESHOLD = 0.10  # rolling hit-rate floor


def _record_cache_stats(in_tok: int, cache_w: int, cache_r: int, out_tok: int) -> None:
    with _cache_stats_lock:
        _cache_stats_total["in"] += in_tok
        _cache_stats_total["cache_w"] += cache_w
        _cache_stats_total["cache_r"] += cache_r
        _cache_stats_total["out"] += out_tok
        _cache_stats_total["calls"] += 1
        _cache_stats_recent.append((in_tok, cache_w, cache_r, out_tok))

        # Snapshot under the same lock so the periodic emission can't race
        # with another writer mid-compute.
        if _cache_stats_total["calls"] % _CACHE_ALERT_PERIOD != 0:
            return
        recent_in = sum(r[0] for r in _cache_stats_recent)
        recent_w = sum(r[1] for r in _cache_stats_recent)
        recent_r = sum(r[2] for r in _cache_stats_recent)
        recent_calls = len(_cache_stats_recent)

    # Emit OUTSIDE the lock — logging can block on a slow stderr / file
    # handler and we don't want every adapter thread queued behind it.
    denom = recent_in + recent_w + recent_r
    rolling = (recent_r / denom) if denom else 0.0
    _logger.info(
        "[CACHE_HEALTH] window=%d calls cache_hit_rate=%.3f in=%d cache_w=%d cache_r=%d",
        recent_calls, rolling, recent_in, recent_w, recent_r,
    )
    if recent_calls >= _CACHE_ALERT_MIN_SAMPLE and rolling < _CACHE_ALERT_LOW_THRESHOLD:
        _logger.warning(
            "[CACHE_HIT_ALERT] rolling cache hit rate %.3f over last %d calls "
            "is below floor %.2f — prompt caching may be broken. "
            "Verify segment[0] of get_standard_draft_prompts is stable and "
            "above the model's prompt-cache token floor.",
            rolling, recent_calls, _CACHE_ALERT_LOW_THRESHOLD,
        )


def _record_cache_usage(model: str, fresh_in: int, cache_read: int, cache_creation: int) -> None:
    with _cache_stats_lock:
        bucket = _cache_stats.setdefault(model, {
            "calls": 0,
            "fresh_in": 0,
            "cache_read_in": 0,
            "cache_creation_in": 0,
        })
        bucket["calls"] += 1
        bucket["fresh_in"] += _safe_int(fresh_in)
        bucket["cache_read_in"] += _safe_int(cache_read)
        bucket["cache_creation_in"] += _safe_int(cache_creation)


def _get_cache_stats_snapshot() -> dict[str, dict[str, int]]:
    with _cache_stats_lock:
        return {model: dict(bucket) for model, bucket in _cache_stats.items()}


def get_cache_hit_stats() -> dict:
    """Snapshot of cache-hit telemetry.

    Returns rolling stats over the last `_cache_stats_recent.maxlen` calls
    (1000 default) plus the all-time totals. The ratio is intentionally
    over the rolling window so an alert can fire when *current* hit rate
    drops, even if the all-time average hides it.
    """
    with _cache_stats_lock:
        total = dict(_cache_stats_total)
        recent_in = sum(r[0] for r in _cache_stats_recent)
        recent_w = sum(r[1] for r in _cache_stats_recent)
        recent_r = sum(r[2] for r in _cache_stats_recent)
        recent_out = sum(r[3] for r in _cache_stats_recent)
        recent_calls = len(_cache_stats_recent)
    denom_recent = recent_in + recent_w + recent_r
    rolling = (recent_r / denom_recent) if denom_recent else 0.0
    denom_total = total["in"] + total["cache_w"] + total["cache_r"]
    lifetime = (total["cache_r"] / denom_total) if denom_total else 0.0
    return {
        "rolling": {
            "calls": recent_calls,
            "input_tokens": recent_in,
            "cache_write_tokens": recent_w,
            "cache_read_tokens": recent_r,
            "output_tokens": recent_out,
            "cache_hit_rate": round(rolling, 4),
        },
        "lifetime": {
            "calls": total["calls"],
            "input_tokens": total["in"],
            "cache_write_tokens": total["cache_w"],
            "cache_read_tokens": total["cache_r"],
            "output_tokens": total["out"],
            "cache_hit_rate": round(lifetime, 4),
        },
    }


# ----------------------------------------------------------------------------
# Truncation telemetry
# ----------------------------------------------------------------------------
# Counts how often a call hit max_tokens (response.stop_reason == "max_tokens").
# For structured-output agents (Critic / Classifier / Prioritizer /
# TaskExtractor) this silently corrupts JSON → fallback parser → default
# scores. See config.py:259-268 for the prod regression this guards against.
# Per-budget breakdown lets ops see which max_tokens cap is the bottleneck.
_trunc_stats_lock = _cache_threading.Lock()
_trunc_stats_total: dict = {"calls": 0, "truncated": 0}
_trunc_stats_recent: _cache_collections.deque = _cache_collections.deque(maxlen=1000)
_trunc_by_budget: dict = {}  # f"{model}:{max_tokens}" -> {"calls", "truncated"}


def _record_truncation(model: str, max_tokens: int, stop_reason: str) -> None:
    """Record one call's truncation outcome and emit a WARNING on truncation."""
    truncated = stop_reason == "max_tokens"
    key = f"{model}:{max_tokens}"
    with _trunc_stats_lock:
        _trunc_stats_total["calls"] += 1
        _trunc_stats_recent.append(1 if truncated else 0)
        bucket = _trunc_by_budget.setdefault(key, {"calls": 0, "truncated": 0})
        bucket["calls"] += 1
        if truncated:
            _trunc_stats_total["truncated"] += 1
            bucket["truncated"] += 1
    if truncated:
        _logger.warning(
            "[TRUNCATION] model=%s max_tokens=%d stop_reason=max_tokens — "
            "structured outputs may parse to defaults; review the cap",
            model, max_tokens,
        )


def get_truncation_stats() -> dict:
    """Snapshot of truncation telemetry — rolling window + lifetime + per-budget."""
    with _trunc_stats_lock:
        total = dict(_trunc_stats_total)
        recent_truncated = sum(_trunc_stats_recent)
        recent_calls = len(_trunc_stats_recent)
        per_budget = {
            key: {
                "calls": v["calls"],
                "truncated": v["truncated"],
                "rate": round(v["truncated"] / v["calls"], 4) if v["calls"] else 0.0,
            }
            for key, v in _trunc_by_budget.items()
        }
    rolling_rate = (recent_truncated / recent_calls) if recent_calls else 0.0
    lifetime_rate = (total["truncated"] / total["calls"]) if total["calls"] else 0.0
    return {
        "rolling": {
            "calls": recent_calls,
            "truncated": recent_truncated,
            "rate": round(rolling_rate, 4),
        },
        "lifetime": {
            "calls": total["calls"],
            "truncated": total["truncated"],
            "rate": round(lifetime_rate, 4),
        },
        "by_budget": per_budget,
    }


def _reset_truncation_stats_for_tests() -> None:
    """Test-only: clear all truncation counters for clean isolation."""
    with _trunc_stats_lock:
        _trunc_stats_total["calls"] = 0
        _trunc_stats_total["truncated"] = 0
        _trunc_stats_recent.clear()
        _trunc_by_budget.clear()


class ClaudeAdapter(LLMPort):
    """Adapter utilisant l'API Claude d'Anthropic."""

    def __init__(self, model: str = None, api_key: str = None, timeout: float = 60.0):
        """
        Initialise l'adapter Claude.

        Args:
            model: Le modèle à utiliser (défaut: claude-sonnet-4-6)
            api_key: Clé API Anthropic (défaut: ANTHROPIC_API_KEY)
            timeout: Timeout SDK en secondes (défaut 60 s). Les chemins
                latence-critiques (ex: agent vocal en voiture, abandonné par
                le client à ~4 s) peuvent passer un timeout court pour ne pas
                immobiliser un worker sur un résultat déjà jeté.
        """
        import anthropic

        self._model = model or os.getenv("LLM_MODEL", "claude-sonnet-4-6")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY requise pour l'adapter Claude")

        # Audit HIGH-6 (2026-04-25): explicit 60 s timeout. The SDK default
        # is 600 s (10 min) — long enough to wedge the bg-pool's 8 workers
        # on a single bad round-trip. 60 s covers Sonnet completions with
        # margin while keeping background reactivity.
        self._client = anthropic.Anthropic(api_key=self._api_key, timeout=timeout)
        self._anthropic = anthropic

    @property
    def name(self) -> str:
        return "claude"

    @property
    def model(self) -> str:
        return self._model

    def _raise_mapped_exception(self, e: Exception) -> None:
        """Mappe les exceptions Anthropic SDK vers les exceptions domaine."""
        exc_type = type(e).__name__
        error_msg = str(e).lower() if e else ""

        # Détecter les erreurs de billing/crédits
        is_billing = any(kw in error_msg for kw in [
            "billing", "credit", "insufficient", "payment",
            "subscription", "quota", "exceeded your",
        ])

        if exc_type == "AuthenticationError":
            if is_billing:
                raise LLMBillingError(provider="claude", message=str(e))
            raise LLMAuthenticationError(provider="claude")

        if exc_type == "RateLimitError":
            if is_billing:
                raise LLMBillingError(provider="claude", message=str(e))
            retry_after = None
            if hasattr(e, "response") and e.response and hasattr(e.response, "headers"):
                retry_after_str = e.response.headers.get("retry-after")
                if retry_after_str:
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        pass
            raise LLMRateLimitError(provider="claude", retry_after=retry_after)

        if exc_type == "InternalServerError":
            raise LLMUnavailableError(provider="claude")

        if exc_type == "APITimeoutError":
            raise LLMTimeoutError(provider="claude")

        if exc_type == "APIConnectionError":
            raise LLMConnectionError(provider="claude")

        if exc_type == "BadRequestError":
            if "context" in error_msg or "token" in error_msg or "too long" in error_msg:
                raise LLMContextLengthError(provider="claude")
            raise LLMResponseError(provider="claude", message=str(e))

        if exc_type == "NotFoundError":
            raise LLMModelNotFoundError(provider="claude", model=self._model)

        if exc_type == "APIStatusError":
            if hasattr(e, "response") and e.response:
                status = e.response.status_code
                if status in (402, 403) and is_billing:
                    raise LLMBillingError(provider="claude", message=str(e))
                if status in (500, 502, 503, 504):
                    raise LLMUnavailableError(provider="claude")
            raise LLMUnavailableError(provider="claude")

        raise

    def complete(
        self,
        system,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Génère une complétion via l'API Claude.

        `system` accepte :
          - str → un seul bloc cacheable (chemin legacy, équivalent au
            comportement avant 2026-05-05)
          - Iterable[SystemSegment] → multi-block, jusqu'à 4 cache
            breakpoints. Permet de découper le prompt système en sections
            (ex: KB stable | profil voix | historique) pour que les
            sections inchangées hit le cache même quand une section change.
        """
        if max_tokens is not None and max_tokens <= 0:
            raise InvalidBoundsError(
                field="max_tokens",
                value=max_tokens,
                min_val=1
            )

        try:
            # P0.2 (2026-05-04) verification: every agent consumes LLMPort
            # via Container so they all pass through this wrapper. cache_control
            # is universally applied. Anthropic only WRITES the cache when a
            # block exceeds ~1024 tokens; below the floor the marker is a
            # no-op write. The multi-block path (added 2026-05-05) lets a
            # caller split a single prompt into stable + dynamic segments
            # so each segment caches independently.
            system_block = _build_anthropic_system_blocks(system)

            kwargs = dict(
                model=self._model,
                max_tokens=max_tokens,
                system=system_block,
                messages=[{"role": "user", "content": user}],
            )
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = self._client.messages.create(**kwargs)

            if not response.content:
                raise LLMResponseError(
                    provider="claude",
                    message="Empty content in response"
                )

            if not hasattr(response.content[0], "text"):
                raise LLMResponseError(
                    provider="claude",
                    message="Missing text attribute in response content"
                )

            usage_recorded = _log_usage(self._model, response.usage, kind="complete")
            cache_w = _safe_int(getattr(response.usage, "cache_creation_input_tokens", 0))
            cache_r = _safe_int(getattr(response.usage, "cache_read_input_tokens", 0))
            input_tok = _safe_int(getattr(response.usage, "input_tokens", 0))
            output_tok = _safe_int(getattr(response.usage, "output_tokens", 0))

            # Anthropic stop_reason values: "end_turn" (normal), "max_tokens"
            # (truncated — caller may want to retry with a larger budget),
            # "stop_sequence", "tool_use". Surfaced for retry-on-truncation
            # in DrafterAgent.draft (see #4 trim from MAX_TOKENS_DRAFT 1024→600).
            stop_reason = getattr(response, "stop_reason", "") or ""
            _record_truncation(self._model, max_tokens, stop_reason)
            return LLMResponse(
                content=response.content[0].text,
                input_tokens=input_tok,
                output_tokens=output_tok,
                model=self._model,
                stop_reason=stop_reason,
                cache_read_input_tokens=cache_r,
                cache_creation_input_tokens=cache_w,
                usage_recorded=usage_recorded,
            )

        except Exception as e:
            self._raise_mapped_exception(e)

    def stream(
        self,
        system,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> Generator[LLMStreamChunk, None, None]:
        """
        Génère une complétion en streaming via l'API Claude.

        Args:
            system: Le prompt système définissant le comportement.
            user: Le message utilisateur.
            max_tokens: Nombre maximum de tokens en sortie.
            temperature: Température de sampling (0.0-1.0). None = défaut.

        Yields:
            LLMStreamChunk avec le texte et les métadonnées.
        """
        if max_tokens is not None and max_tokens <= 0:
            raise InvalidBoundsError(
                field="max_tokens",
                value=max_tokens,
                min_val=1
            )

        output_tokens_so_far = 0
        input_tokens = 0
        cache_w = 0
        cache_r = 0

        try:
            # Same multi-block-aware helper as complete() — keeps streaming
            # and non-streaming paths in lockstep on cache structure.
            system_block = _build_anthropic_system_blocks(system)

            kwargs = dict(
                model=self._model,
                max_tokens=max_tokens,
                system=system_block,
                messages=[{"role": "user", "content": user}],
            )
            if temperature is not None:
                kwargs["temperature"] = temperature

            # F-03 (audit 2026-05-14): track stop_reason across the stream
            # so the final chunk can carry it. Anthropic emits stop_reason
            # on the `message_delta` event (during streaming) and again on
            # the final accumulated `message` object — we capture from
            # either source. The compose stream consumer reads this on the
            # final chunk to flag truncated drafts on the WS payload.
            _stop_reason: str | None = None
            usage_recorded = False
            with self._client.messages.stream(**kwargs) as stream:
                for event in stream:
                    # Les événements peuvent être de différents types
                    if hasattr(event, "type"):
                        if event.type == "message_start":
                            # Premier événement: contient les input tokens
                            if hasattr(event, "message") and hasattr(event.message, "usage"):
                                usage = event.message.usage
                                input_tokens = _safe_int(getattr(usage, "input_tokens", 0))
                                cache_w = _safe_int(getattr(usage, "cache_creation_input_tokens", 0))
                                cache_r = _safe_int(getattr(usage, "cache_read_input_tokens", 0))
                        elif event.type == "content_block_delta":
                            # Delta de contenu
                            if hasattr(event, "delta") and hasattr(event.delta, "text"):
                                text = event.delta.text
                                output_tokens_so_far += 1  # Approximation
                                yield LLMStreamChunk(
                                    text=text,
                                    input_tokens=input_tokens,
                                    output_tokens_so_far=output_tokens_so_far,
                                    is_final=False,
                                    model=self._model,
                                    cache_read_input_tokens=cache_r,
                                    cache_creation_input_tokens=cache_w,
                                )
                        elif event.type == "message_delta":
                            # SDK reports stop_reason here when the model
                            # finishes streaming (including truncation).
                            _sr = getattr(getattr(event, "delta", None),
                                          "stop_reason", None)
                            if _sr:
                                _stop_reason = _sr
                        elif event.type == "message_stop":
                            # Some SDK versions only set stop_reason on the
                            # final message object surfaced at message_stop.
                            # Fall back to that when message_delta didn't.
                            if _stop_reason is None:
                                _final_msg = getattr(event, "message", None)
                                if _final_msg is not None:
                                    _stop_reason = getattr(_final_msg, "stop_reason", None)
                            # Dernier événement
                            yield LLMStreamChunk(
                                text="",
                                input_tokens=input_tokens,
                                output_tokens_so_far=output_tokens_so_far,
                                is_final=True,
                                model=self._model,
                                cache_read_input_tokens=cache_r,
                                cache_creation_input_tokens=cache_w,
                                usage_recorded=usage_recorded,
                                stop_reason=_stop_reason,
                            )
                # Audit 2026-05-04: cache stats live on the final message,
                # not the per-event stream. `get_final_message()` is a no-op
                # if streaming completed normally — it just returns the
                # accumulated message object the SDK already built.
                try:
                    final = stream.get_final_message()
                    if final is not None:
                        if getattr(final, "usage", None) is not None:
                            usage_recorded = _log_usage(self._model, final.usage, kind="stream")
                        _record_truncation(
                            self._model,
                            max_tokens,
                            getattr(final, "stop_reason", "") or "",
                        )
                except Exception:  # pragma: no cover — telemetry never breaks
                    pass

        except Exception as e:
            self._raise_mapped_exception(e)

    def is_available(self) -> bool:
        """Vérifie si la clé API est configurée."""
        return bool(self._api_key)
