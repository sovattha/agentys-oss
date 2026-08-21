# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Shared dataclasses used across the Quick Step engine + handlers.

Lives in its own module to break the circular dependency between
``registry`` (the dispatch table) and ``handlers/*`` (the implementations
that need to declare their signatures in terms of these types).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ExecutionContext:
    """Per-execution state shared across handlers in one chain.

    Built once by the engine before the chain runs, never mutated by handlers
    (handlers may read; the engine owns lifecycle).
    """
    provider: Any
    account_id: int
    account_email: str
    account_display_name: str
    email: Any            # SQLA Email row OR provider Email object
    email_id: str         # original id (may have "sent:" prefix)
    raw_id: str           # provider-stripped id
    template_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Outcome of one action. ``ok=False`` halts the chain unless the engine
    is configured to continue past failures (current default: stop)."""
    ok: bool
    error: str | None = None
    artifact: dict | None = None


@dataclass
class SentEmailRef:
    """Lightweight shape of a freshly-sent email, passed to the sent-side
    Quick Step pass (``fire_sent_quicksteps_immediate`` → matchers).

    Replaces the legacy ``SentEmail`` domain entity that doubled as a
    FollowupTracker row. Carries only the fields the sent-side condition
    matchers read: ``subject``/``body_preview`` (email_text), ``thread_id``
    + ``subject`` (is_new_thread via the "Re:" prefix), ``recipient``
    (no-reply guard) and ``id`` (in-memory fire dedup).
    """
    id: str
    recipient: str
    subject: str
    body_preview: str
    thread_id: str


ActionHandler = Callable[[ExecutionContext, dict], ActionResult]


__all__ = ["ExecutionContext", "ActionResult", "ActionHandler", "SentEmailRef"]
