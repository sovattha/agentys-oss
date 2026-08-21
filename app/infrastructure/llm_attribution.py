# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""LLM call attribution context (audit 2026-05-05).

Threads `(agent, account_id, user_id, feature)` through the LLM call stack via
contextvars so the token counter can record per-user and per-system-process
breakdowns without changing the LLMPort signature. Pre-fix, completions could
collapse into a single background bucket — making it hard to answer questions
like "how much did the drafter cost yesterday vs the onboarding pipeline?".

contextvars (not thread-locals) so the attribution propagates correctly
through asyncio tasks too — important for the streaming path which uses
async iterators.

Usage::

    with llm_attribution("drafter", account_id=42):
        response = self._llm.complete(system=..., user=...)

    # Inside the LLM adapter / token tracker:
    agent = current_agent() or "unknown"
    account = current_account_id()  # may be None if caller didn't set
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Optional

# Module-level vars. Default to the sentinel string ``"unknown"`` for the
# agent so unattributed calls still produce a valid log line that's easy to
# grep and trace back to a missing wrapping.
_agent_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_agent_var", default="unknown"
)
_account_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "llm_account_var", default=None
)


def current_agent() -> str:
    """Return the agent label active in the current context (or ``"unknown"``)."""
    return _agent_var.get()


def current_account_id() -> Optional[int]:
    """Return the account_id active in the current context, or None."""
    return _account_var.get()


@contextlib.contextmanager
def llm_attribution(
    agent: str,
    *,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    feature: Optional[str] = None,
) -> Iterator[None]:
    """Set LLM attribution for the duration of the wrapped block.

    Nesting is honored — the outer context is restored on exit. This matters
    when an agent calls another agent (e.g. CriticAgent invoked from the
    drafter retry loop): the inner agent's context wins inside its block,
    the outer wins after.

    If ``account_id`` is omitted, preserve the current outer account instead
    of clearing it. Background pipelines often wrap the request once and then
    instantiate helper agents without an explicit account; those helper agents
    must inherit the request attribution.
    """
    effective_account_id = account_id if account_id is not None else _account_var.get()
    a_token = _agent_var.set(agent or "unknown")
    acc_token = _account_var.set(effective_account_id)
    usage_tokens = None
    if account_id is not None or user_id is not None or feature is not None:
        try:
            from app.infrastructure.cost_manager import (
                get_usage_context,
                reset_usage_context,
                set_usage_context,
            )

            context_account_id, context_user_id, context_feature = get_usage_context()
            usage_tokens = set_usage_context(
                account_id=(
                    account_id
                    if account_id is not None
                    else context_account_id or effective_account_id
                ),
                user_id=user_id if user_id is not None else context_user_id,
                feature=feature if feature is not None else context_feature,
            )
        except Exception:  # pragma: no cover - attribution must be best-effort
            usage_tokens = None
    try:
        yield
    finally:
        if usage_tokens is not None:
            try:
                reset_usage_context(usage_tokens)
            except Exception:  # pragma: no cover - attribution must be best-effort
                pass
        _agent_var.reset(a_token)
        _account_var.reset(acc_token)
