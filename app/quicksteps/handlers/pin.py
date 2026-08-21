# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""pin handler — server-side pin list so daemon-fired pins survive UI reload."""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_pin(ctx: ExecutionContext, _payload: dict) -> ActionResult:
    """Add the email to the account's persisted pinned list.

    Daemon-triggered pins are stored server-side so the frontend merges them
    on next load (localStorage is unreachable from the backend).
    """
    try:
        import json
        from app.api.routes_helpers import get_db_session
        from app.db.models.account import Account
        with get_db_session() as session:
            account = session.get(Account, ctx.account_id)
            if not account:
                return ActionResult(ok=False, error="account_not_found")
            pinned: list[str] = json.loads(account.pinned_email_ids_json or "[]")
            if ctx.email_id not in pinned:
                pinned.append(ctx.email_id)
                account.pinned_email_ids_json = json.dumps(pinned)
                session.commit()
        emit("emit_email_pinned", ctx)
        return ActionResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("pin handler failed: %s", exc)
        return ActionResult(ok=False, error=f"pin_error: {exc}")
