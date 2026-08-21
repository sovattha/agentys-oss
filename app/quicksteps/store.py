# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""DB persistence for per-account Quick Steps.

Stored on ``Account.quick_steps_json`` as a JSON list, mirroring the
``settings_json`` pattern. We keep this thin: load returns a list,
save replaces the list. No partial updates — the engine is the only
read-time consumer and re-validates anyway.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Optional

from app.db.database import get_db_session
from app.db.repositories.account_repository import AccountRepository
from app.quicksteps.schema import migrate_legacy_condition

logger = logging.getLogger(__name__)


# Audit 2026-05-11 (B-05): transact_quick_steps does a read-modify-write on
# `account.quick_steps_json` with no row lock. Two concurrent POSTs from the
# same account (e.g. user clicks "Save" rapidly, or the new drag-handle
# revamp PATCHes order then PATCHes a step in quick succession) could both
# observe state X, mutate to X+A and X+B, and one would silently overwrite
# the other. Process-wide per-account threading.Lock serializes the
# read+write inside a single Python process. (Agentys backend is single-
# process today; if it ever scales out we'd need to upgrade to a DB-level
# advisory lock or an optimistic version column.)
_account_locks_guard = threading.Lock()
_per_account_locks: dict[int, threading.Lock] = {}


def _get_account_lock(account_id: int) -> threading.Lock:
    with _account_locks_guard:
        lock = _per_account_locks.get(account_id)
        if lock is None:
            lock = threading.Lock()
            _per_account_locks[account_id] = lock
        return lock


class QuickStepsConflict(Exception):
    """Raised inside the mutator passed to transact_quick_steps to abort with a structured error."""
    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


def _normalize_step_for_read(raw: dict) -> dict:
    """Fill in optional fields that older records may have omitted.

    The schema validator (``validate_quick_step``) already injects these
    defaults on write, but accounts created before those fields existed
    have rows persisted without them. The frontend editor reads
    ``step.triggers.length`` unconditionally, so a missing key crashes
    the UI. Normalizing on read closes that gap permanently — even for
    clients that haven't shipped the matching defensive code.

    Best-effort only: if a record is malformed in deeper ways we leave
    those fields alone and let the editor's validation surface the issue
    on the user's next save.
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    out.setdefault("triggers", [])
    if not isinstance(out["triggers"], list):
        out["triggers"] = []
    # Read-path migration: upgrade legacy {type-encodes-operator}
    # conditions to the v2 {type, match_mode} shape. Idempotent + total,
    # so already-migrated rows pass through untouched. Keeps stored rows
    # readable by the v2 matcher/editor even before the next save
    # re-canonicalises them (cf. validate_quick_step on the write path).
    out["triggers"] = [migrate_legacy_condition(c) for c in out["triggers"]]
    out.setdefault("triggerOperator", "OR")
    if out["triggerOperator"] not in ("AND", "OR"):
        out["triggerOperator"] = "OR"
    out.setdefault("autoEnabled", False)
    # ⚡ Auto badge defaults to True on legacy rows (UX request 2026-05-12) —
    # users created their pre-feature rules expecting transparency. The
    # toggle in the editor lets them opt out per-rule afterwards.
    out.setdefault("showAutoBadge", True)
    out.setdefault("enabled", True)
    out.setdefault("confirmBeforeRun", False)
    out.setdefault("icon", None)
    out.setdefault("shortcut", None)
    # firesOn defaults to "received" so every legacy step keeps its
    # pre-feature behavior of running against incoming emails only.
    out.setdefault("firesOn", "received")
    if out["firesOn"] not in ("received", "sent"):
        out["firesOn"] = "received"

    # Per-action guards: ensure ``if.triggers`` is always a list so the
    # frontend can read its ``.length`` without a defensive null check.
    actions = out.get("actions")
    if isinstance(actions, list):
        normalized_actions: list[dict] = []
        for action in actions:
            if not isinstance(action, dict):
                # BS1-002: drop non-dict actions; engine.execute crashes on
                # them (`.get("type")` on a non-dict raises AttributeError),
                # and validate_quick_step would have rejected the whole step
                # anyway. Preserving a malformed element here just shifts
                # the crash to a worse spot.
                continue
            guard = action.get("if")
            if isinstance(guard, dict):
                guard = dict(guard)
                if not isinstance(guard.get("triggers"), list):
                    guard["triggers"] = []
                # Per-action guard conditions get the same legacy → v2
                # migration as the step-level triggers above.
                guard["triggers"] = [
                    migrate_legacy_condition(c) for c in guard["triggers"]
                ]
                if guard.get("operator") not in ("AND", "OR"):
                    guard["operator"] = "AND"
                action = {**action, "if": guard}
            normalized_actions.append(action)
        out["actions"] = normalized_actions

    return out


def _seed_starter_pack_if_unseeded(account_id: int) -> None:
    """First-time seed of the starter Quick Steps for ``account_id``.

    Behaviour:
    - ``quick_steps_json IS NULL`` → never seeded → write the starter pack
      (disabled cards, auto mode preselected) and commit. The next read
      returns them.
    - ``quick_steps_json = '[]'`` or any non-NULL value → already touched
      (by previous seed OR by user save) → no-op. Preserves user's empty
      state if they cleared, and respects existing rules otherwise.

    Wrapped in the per-account lock so two concurrent first-loads from
    the same account don't both try to write.
    """
    with _get_account_lock(account_id):
        try:
            with get_db_session() as session:
                account = AccountRepository(session).get(account_id)
                if not account:
                    return
                if account.quick_steps_json is not None:
                    return
                from app.quicksteps.defaults import build_default_quick_steps
                rules = build_default_quick_steps(
                    account_email=account.email or "",
                    language=account.preferred_language or "fr",
                )
                account.quick_steps_json = json.dumps(rules, ensure_ascii=False)
                session.commit()
                logger.info(
                    "Seeded %d starter Quick Steps for account %d (%s)",
                    len(rules), account_id, account.email,
                )
        except Exception as exc:  # noqa: BLE001
            # Best-effort: a failed seed shouldn't break the read path.
            # The user will see no quick steps once, refresh, and it'll
            # try again next load.
            logger.warning(
                "Starter Quick Steps seed failed for account %d: %s",
                account_id, exc,
            )


def load_quick_steps(account_id: int) -> list[dict]:
    """Return the saved Quick Steps for ``account_id`` or ``[]`` if none.

    Always returns a list — never raises. DB transients, JSON corruption,
    or unexpected shapes degrade to ``[]`` with a logged warning so the
    settings UI can render an empty list rather than crashing on a 500.

    On the first call for an account that has never had Quick Steps
    (``quick_steps_json IS NULL``), seeds the starter pack defined in
    ``app/quicksteps/defaults.py`` — all rules land disabled, with automatic
    mode preselected, so they're inert until the user enables them.
    """
    if not account_id or account_id <= 0:
        return []
    _seed_starter_pack_if_unseeded(account_id)
    try:
        with get_db_session() as session:
            account = AccountRepository(session).get(account_id)
            if not account or not account.quick_steps_json:
                return []
            data = json.loads(account.quick_steps_json)
            if not isinstance(data, list):
                logger.warning(
                    "Account %d quick_steps_json is not a list — ignoring",
                    account_id,
                )
                return []
            return [_normalize_step_for_read(s) for s in data]
    except json.JSONDecodeError as exc:
        logger.warning("quick_steps_json is invalid JSON for account %d: %s", account_id, exc)
        return []
    except Exception as exc:
        # DB connection blip, SQLAlchemy pool exhaustion, etc. Don't let
        # this propagate as a bare 500 — the settings panel will show
        # "Server error (500)" with no body, which the user just sees as
        # a permanent stuck state.
        logger.error(
            "Unexpected error loading quick_steps for account %d: %s",
            account_id, exc, exc_info=True,
        )
        return []


def save_quick_steps(account_id: int, steps: list[dict]) -> bool:
    """Replace the Quick Steps list for ``account_id``. Returns True on success."""
    if not account_id or account_id <= 0:
        return False
    try:
        with get_db_session() as session:
            account = AccountRepository(session).get(account_id)
            if not account:
                logger.warning("Account %d not found for quick_steps save", account_id)
                return False
            account.quick_steps_json = json.dumps(steps, ensure_ascii=False)
            session.commit()
            return True
    except Exception as exc:
        logger.error("Could not save quick_steps for account %d: %s", account_id, exc)
        return False


def transact_quick_steps(
    account_id: int,
    mutator: Callable[[list[dict]], list[dict]],
) -> list[dict]:
    """Load, validate, and save Quick Steps atomically in one DB session.

    mutator(steps) → new_steps.  Raise QuickStepsConflict to abort with a
    structured validation error.  Any other exception propagates as-is.
    """
    if not account_id or account_id <= 0:
        raise ValueError("Invalid account_id")
    # Audit B-05: serialize read-modify-write per account so concurrent
    # saves from the same user can't lose a Quick Step.
    with _get_account_lock(account_id):
        with get_db_session() as session:
            account = AccountRepository(session).get(account_id)
            if not account:
                raise ValueError(f"Account {account_id} not found")
            try:
                steps: list[dict] = json.loads(account.quick_steps_json or "[]")
            except json.JSONDecodeError:
                steps = []
            if not isinstance(steps, list):
                steps = []
            new_steps = mutator(steps)  # raises QuickStepsConflict on validation failure
            account.quick_steps_json = json.dumps(new_steps, ensure_ascii=False)
            session.commit()
            return new_steps


def find_step(steps: list[dict], step_id: str) -> Optional[dict]:
    """Linear search by id. Lists are bounded at 50 items so O(n) is fine."""
    for s in steps:
        if s.get("id") == step_id:
            return s
    return None


def remove_step(steps: list[dict], step_id: str) -> list[dict]:
    return [s for s in steps if s.get("id") != step_id]


def upsert_step(steps: list[dict], step: dict) -> list[dict]:
    """Replace the matching id or append. Preserves ordering of existing items."""
    out: list[dict] = []
    found = False
    for existing in steps:
        if existing.get("id") == step["id"]:
            out.append(step)
            found = True
        else:
            out.append(existing)
    if not found:
        out.append(step)
    return out
