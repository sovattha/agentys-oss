# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Persistent audit logger for Quick Step executions.

Single public entrypoint :func:`record_execution`. Called by the engine on
every execute path (success, failure, idempotent replay) and by the auto-
trigger daemon. Failures are swallowed — audit must never break the
execution itself.

Why a dedicated module: the engine should not import SQLAlchemy directly.
Keeping the DB write here means tests can monkeypatch ``record_execution``
without touching engine internals, and the engine stays a pure-Python
function suitable for unit tests.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def record_execution(
    *,
    account_id: int,
    step: dict,
    email_id: str,
    report: Any,
    source: str = "manual",
) -> None:
    """Insert one audit row for the given execution.

    Failures are caught and logged at debug — the audit log is best-effort.
    Never propagate an audit failure to the caller; the caller has already
    finished its real work and just wants a forensic trail.
    """
    if not account_id or account_id <= 0:
        return
    try:
        from app.db.database import get_db_session
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        actions_payload = []
        for action in getattr(report, "actions", []) or []:
            actions_payload.append({
                "type": getattr(action, "type", ""),
                "ok": bool(getattr(action, "ok", False)),
                "error": getattr(action, "error", None),
            })
        row = QuickStepAuditLog(
            account_id=account_id,
            step_id=str(step.get("id", ""))[:64],
            step_name=(step.get("name") or "")[:255] or None,
            email_id=str(email_id or "")[:255],
            source=source if source in ("manual", "auto") else "manual",
            success=bool(getattr(report, "success", False)),
            executed=int(getattr(report, "executed", 0) or 0),
            error=getattr(report, "error", None),
            actions_json=json.dumps(actions_payload, ensure_ascii=False) if actions_payload else None,
            replay=bool(getattr(report, "idempotent_replay", False)),
        )
        with get_db_session() as session:
            session.add(row)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("audit record_execution suppressed: %s", exc)
