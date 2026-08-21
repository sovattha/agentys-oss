# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Sequential executor for Quick Step action chains.

Responsibilities:
- Resolve provider + email + template context once per execution
- Walk the action list, dispatching each through ``ACTION_HANDLERS``
- Stop on the first failure (best-effort: previous side-effects stay)
- Surface a structured ``ExecutionReport`` so the UI can render
  per-action ✓/✗ status
- Idempotency: a 60-second cache keyed by (account_id, idempotency_key)
  dedupes accidental double-clicks. Backed by SQLite in production so it
  survives across gunicorn workers; tests inject the in-memory backend.

The engine never raises — every error path lands in the report. Routes
turn the report into a 200/4xx/5xx response.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Any

from app.quicksteps.idempotency import (
    DEFAULT_TTL_SECONDS,
    IdempotencyStore,
    MemoryIdempotencyStore,
    get_default_store,
    set_default_store,
)
from app.quicksteps.registry import (
    ACTION_HANDLERS,
    ActionResult,
    ExecutionContext,
)
from app.quicksteps.template import build_context, collect_unknown_variables

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_SECONDS = DEFAULT_TTL_SECONDS


@dataclass
class ActionStatus:
    type: str
    ok: bool
    error: str | None = None


@dataclass
class ExecutionReport:
    success: bool
    step_id: str
    email_id: str
    executed: int = 0
    actions: list[ActionStatus] = field(default_factory=list)
    error: str | None = None
    idempotent_replay: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "step_id": self.step_id,
            "email_id": self.email_id,
            "executed": self.executed,
            "actions": [asdict(a) for a in self.actions],
            "error": self.error,
            "idempotent_replay": self.idempotent_replay,
        }


# --------------------------------------------------------------------------- #
# Test hook — kept so existing tests that imported it keep working. New tests
# should pass an explicit MemoryIdempotencyStore via the ``idempotency_store``
# parameter on ``execute`` instead of mutating module state.
# --------------------------------------------------------------------------- #

def _idem_clear_for_tests() -> None:
    set_default_store(MemoryIdempotencyStore())


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #

def execute(
    *,
    account_id: int,
    step: dict,
    email_id: str,
    idempotency_key: str | None = None,
    provider_factory: Any = None,
    email_loader: Any = None,
    account_loader: Any = None,
    idempotency_store: IdempotencyStore | None = None,
    source: str = "manual",
    audit_recorder: Any = None,
) -> ExecutionReport:
    """Run ``step['actions']`` sequentially against ``email_id``.

    Injection points keep the engine testable without booting Flask:
    - ``provider_factory`` / ``email_loader`` / ``account_loader`` stub the
      providers and DB.
    - ``idempotency_store`` swaps the SQLite-backed dedupe cache for an
      in-memory one (fast, isolated across tests).
    - ``audit_recorder`` swaps the persistent audit-log writer; pass a
      no-op (e.g. ``lambda **kw: None``) in unit tests to skip DB I/O.
    - ``source`` is recorded on the audit row to distinguish manual user
      runs from daemon auto-triggers; replays are not re-audited.
    """
    store = idempotency_store or get_default_store()
    step_id = step.get("id", "")

    cached_dict = store.get(account_id, idempotency_key or "")
    if cached_dict is not None:
        # Replays don't get a new audit row: the original execution already
        # wrote one, and double-counting would inflate "step X ran N times"
        # by however many times the user double-clicked.
        return _replay_from_dict(cached_dict)

    report = ExecutionReport(success=False, step_id=step_id, email_id=email_id)

    def finalize(error: str | None = None) -> ExecutionReport:
        """Cache the report and return it. Every exit path goes through here so
        that retrying with the same idempotency key always replays the first
        outcome — pre-execute failures included (HTTP idempotency-key spec)."""
        if error is not None:
            report.error = error
        recorder = audit_recorder if audit_recorder is not None else _default_audit_recorder
        try:
            recorder(
                account_id=account_id,
                step=step,
                email_id=email_id,
                report=report,
                source=source,
            )
        except Exception:  # noqa: BLE001
            # Audit Cluster C (2026-05-11) B-11 + audit 2026-05-12 B-04 + F-06
            # (audit-2026-05-12_2129): a missing audit row breaks idempotency
            # replay AND auto-trigger deduplication — the same chain can
            # re-execute on the same email because the audit entry is absent.
            # Integrity-critical: surface the failure to the caller so it can
            # decide retry/alert instead of silently dropping the audit row.
            logger.error(
                "audit recorder raised — chain integrity at risk",
                exc_info=True,
            )
            report.success = False
            report.error = "audit_record_failed"
        # Cache MUST run after the recorder mutates report on failure — F-06
        # regression (audit-2026-05-12_2129): caching the success=True dict
        # BEFORE the recorder ran left a stale cache for 60s when the recorder
        # failed; subsequent replays returned success=True with no audit row,
        # silently disarming _step_fired_on_email dedup.
        store.put(account_id, idempotency_key or "", report.to_dict())
        return report

    actions = step.get("actions") or []
    if not actions:
        return finalize("no_actions")

    try:
        if provider_factory:
            provider = provider_factory()
        else:
            provider = _default_provider_factory(account_id)
    except Exception as exc:  # noqa: BLE001
        return finalize(f"provider_unavailable: {exc}")

    try:
        email = (email_loader or _default_email_loader)(provider, email_id, account_id)
    except Exception as exc:  # noqa: BLE001
        # Werkzeug HTTPException raised by `_get_email_by_id` — translate to
        # a clean signal so the route maps it to HTTP 404 (not a generic 502).
        # Two shapes: `abort(404)` (code on the exception) or
        # `abort(make_response(jsonify(...), 404))` (code lives on
        # ``exc.response.status_code`` because HTTPException's own ``code``
        # is None when it's wrapping a custom Response).
        code = getattr(exc, "code", None)
        response = getattr(exc, "response", None)
        if response is not None and not code:
            code = getattr(response, "status_code", None)
        if code == 404 or "not found" in str(exc).lower():
            return finalize("email_not_found")
        return finalize(f"email_load_failed: {exc}")
    if email is None:
        return finalize("email_not_found")

    raw_id = email_id[5:] if email_id.startswith("sent:") else email_id

    try:
        account_email, account_display_name = (account_loader or _default_account_loader)(account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("account_loader failed: %s", exc)
        account_email, account_display_name = "", ""

    template_vars = build_context(
        sender_email=getattr(email, "sender", "") or "",
        sender_name=getattr(email, "sender_name", "") or "",
        subject=getattr(email, "subject", "") or "",
        me_email=account_email,
        me_display_name=account_display_name,
    )

    unknown = _collect_template_problems(actions, template_vars)
    if unknown:
        return finalize(f"template_unknown_variables: {', '.join(unknown)}")

    ctx = ExecutionContext(
        provider=provider,
        account_id=account_id,
        account_email=account_email,
        account_display_name=account_display_name,
        email=email,
        email_id=email_id,
        raw_id=raw_id,
        template_vars=template_vars,
    )

    for index, action in enumerate(actions):
        action_type = action.get("type", "")
        handler = ACTION_HANDLERS.get(action_type)
        if handler is None:
            report.actions.append(ActionStatus(type=action_type, ok=False, error="unknown_action"))
            return finalize(f"unknown_action:{action_type}")

        # Per-action ``if`` guard — when present and not satisfied, skip this
        # action and continue the chain. Counted as ok=True with error="skipped"
        # so the UI can render a "skipped" pill without surfacing as a failure.
        guard = action.get("if")
        if guard and not _evaluate_action_guard(guard, ctx):
            report.actions.append(ActionStatus(type=action_type, ok=True, error="skipped"))
            report.executed = index + 1
            continue

        result = _safe_dispatch(handler, ctx, action.get("payload") or {})
        report.actions.append(ActionStatus(
            type=action_type,
            ok=result.ok,
            error=result.error,
        ))
        if result.ok:
            report.executed = index + 1
        else:
            return finalize(result.error or f"{action_type}_failed")

    report.success = True
    return finalize()


def _replay_from_dict(cached: dict) -> ExecutionReport:
    """Reconstruct an ExecutionReport from the persisted JSON form, marking
    the result as a replay so the UI can hint that nothing actually ran."""
    actions = [
        ActionStatus(
            type=a.get("type", ""),
            ok=bool(a.get("ok")),
            error=a.get("error"),
        )
        for a in cached.get("actions", [])
    ]
    return ExecutionReport(
        success=bool(cached.get("success")),
        step_id=cached.get("step_id", ""),
        email_id=cached.get("email_id", ""),
        executed=int(cached.get("executed", 0)),
        actions=actions,
        error=cached.get("error"),
        idempotent_replay=True,
    )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _evaluate_action_guard(guard: dict, ctx: ExecutionContext) -> bool:
    """Evaluate a per-action ``if`` guard against the current email.

    Reuses ``auto_trigger._match_condition`` so action guards and step-level
    triggers share one matching implementation.
    """
    triggers = guard.get("triggers") or []
    if not triggers:
        return True
    from app.quicksteps.auto_trigger import _match_condition
    operator = guard.get("operator", "AND")
    results = [
        _match_condition(c, ctx.email, account_id=ctx.account_id, email_id=ctx.email_id)
        for c in triggers
    ]
    return all(results) if operator == "AND" else any(results)


def _safe_dispatch(handler, ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Belt-and-suspenders — handlers already swallow their own exceptions
    and return ActionResult(ok=False), but if a future handler regresses,
    the engine still produces a report instead of a 500."""
    try:
        return handler(ctx, payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Quick Step handler %s raised", handler.__name__)
        return ActionResult(ok=False, error=f"handler_crash: {exc}")


def _collect_template_problems(actions: list[dict], ctx_vars: dict[str, str]) -> list[str]:
    unknown: set[str] = set()
    for action in actions:
        payload = action.get("payload") or {}
        if action.get("type") == "reply_template":
            # When snippet_id is set the body is resolved at dispatch time —
            # skip validation here; unknown variables surface on first execution.
            if not payload.get("snippet_id"):
                unknown.update(collect_unknown_variables(payload.get("body", ""), ctx_vars))
        elif action.get("type") == "forward":
            unknown.update(collect_unknown_variables(payload.get("body", ""), ctx_vars))
            unknown.update(collect_unknown_variables(payload.get("subject_prefix", ""), ctx_vars))
    return sorted(unknown)


def _default_provider_factory(account_id: int = 0):
    """Resolve the email provider for the engine.

    Two-tier resolution:
      1. ``_get_authenticated_provider`` — works in a Flask request with a
         JWT or on Tauri loopback. The normal path when a user clicks a
         Quick Step from the UI.
      2. Account-id fallback — used by background threads (auto_trigger
         from daemon polling or from the API sync labelling pipeline)
         where there is no request context and the JWT-aware lookup
         returns ``None``. We resolve the account email from the DB,
         find the matching ``AccountConfig`` in the multi-account
         manager, and build a provider directly. Same end provider as
         the JWT path; only the discovery shortcut differs.
    """
    from app.api.routes_helpers import _get_authenticated_provider
    try:
        return _get_authenticated_provider()
    except Exception:
        # JWT-path failed (no request context or aborted with 503).
        # Fall through to the account-id fallback below.
        if account_id <= 0:
            raise
    # Account-id fallback. We're outside a Flask request, so look up the
    # account by id in the DB, then find the AccountConfig by email and
    # build the provider directly via the multi-account factory.
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository
    from app.multi_accounts import get_account_manager, create_provider_for_account
    with get_db_session() as session:
        db_acct = AccountRepository(session).get(account_id)
        if not db_acct or not db_acct.email:
            raise RuntimeError(f"account {account_id} not found in DB")
        email = db_acct.email
    cfg = get_account_manager().get_account_by_email(email)
    if not cfg:
        raise RuntimeError(f"account {email} not in multi-account manager")
    provider = create_provider_for_account(cfg)
    if not provider.authenticate():
        raise RuntimeError(f"provider auth failed for account {account_id} ({email})")
    return provider


def _default_email_loader(provider, email_id: str, account_id: int):
    """Fetch the email scoped to ``account_id`` so tenant A cannot run a Quick
    Step on tenant B's email by passing a colliding provider id (regression
    guard for the 2026-04-24 cross-tenant fix)."""
    from app.api.routes_helpers import _get_email_by_id
    return _get_email_by_id(provider, email_id, account_id=account_id)


def _default_account_loader(account_id: int) -> tuple[str, str]:
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository
    with get_db_session() as session:
        account = AccountRepository(session).get(account_id)
        if not account:
            return "", ""
        return account.email or "", account.display_name or ""


def _default_audit_recorder(**kwargs) -> None:
    """Lazy import keeps the engine module importable in environments where
    the audit table hasn't been migrated yet (e.g. older test fixtures)."""
    from app.quicksteps.audit import record_execution
    record_execution(**kwargs)
