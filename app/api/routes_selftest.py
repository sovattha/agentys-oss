"""Internal self-test endpoints for external sentinels (cron jobs).

These endpoints are NOT part of the public API. They exist so an off-box
cron (GitHub Actions) can probe the live stack for regressions of the
silent-failure class — the exact family of bugs that caused #290 (room
resolution + WS emission path).

Auth: `X-Observability-Token` header must match `OBSERVABILITY_TOKEN` env
var. No JWT, no account binding — the sentinel is a non-human caller.

Scope: keep these endpoints cheap (<200ms) and idempotent so the cron
can hit them every N minutes without side-effects beyond the self-test
account row.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

selftest_bp = Blueprint("selftest", __name__)

# Mock account used only by the self-test. Email chosen to be obviously
# non-routable (invalid TLD, internal namespace) so a human glancing at
# the DB immediately recognises it as synthetic.
_SELFTEST_EMAIL = "__selftest__@agentys.internal"
_SELFTEST_PROVIDER = "selftest"
_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_SCHEDULER_BOOT_GRACE_SECONDS = int(
    os.environ.get("SCHEDULER_HEALTH_BOOT_GRACE_SECONDS", "1800")
)
_BOOT_GRACE_SCHEDULERS = {
    "scheduled_email_scheduler",
    "recap_scheduler",
    "bulk_jobs_scheduler",
    "batch_worker",
    "learning_refresh_scheduler",
}
_EMAIL_RETENTION_AUDIT_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_email_content_retention.py"
)


def _check_token() -> bool:
    """Return True iff the request header matches the configured token.

    If the env var is unset, reject unconditionally — a missing secret
    must never degrade to an open endpoint.
    """
    expected = os.environ.get("OBSERVABILITY_TOKEN", "").strip()
    if not expected:
        return False
    provided = request.headers.get("X-Observability-Token", "").strip()
    return bool(provided) and provided == expected


def _query_int(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _email_retention_data_dir() -> str:
    explicit = os.environ.get("EMAIL_RETENTION_AUDIT_DATA_DIR", "").strip()
    if explicit:
        return explicit

    data_dir = os.environ.get("AGENTYS_DATA_DIR", "").strip()
    if data_dir:
        return data_dir

    railway_volume = Path("/data/agentys")
    if railway_volume.exists():
        return railway_volume.as_posix()

    return "data"


def _load_email_retention_audit_module() -> Any:
    if not _EMAIL_RETENTION_AUDIT_SCRIPT.exists():
        raise FileNotFoundError(
            f"retention audit script missing at {_EMAIL_RETENTION_AUDIT_SCRIPT}"
        )

    module_name = "_agentys_email_retention_audit"
    spec = importlib.util.spec_from_file_location(
        module_name,
        _EMAIL_RETENTION_AUDIT_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load email retention audit script")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run_email_retention_audit(
    *,
    min_json_files: int = 0,
    min_database_checks: int = 1,
) -> dict[str, Any]:
    audit = _load_email_retention_audit_module()
    argv = [
        "--data-dir",
        _email_retention_data_dir(),
        "--snippet-max-chars",
        os.environ.get("EMAIL_RETENTION_AUDIT_SNIPPET_MAX_CHARS", "150"),
    ]

    database_url = os.environ.get("EMAIL_RETENTION_AUDIT_DATABASE_URL", "").strip()
    if database_url:
        argv.extend(["--database-url", database_url])

    sqlite_db_path = os.environ.get("EMAIL_RETENTION_AUDIT_SQLITE_DB_PATH", "").strip()
    if sqlite_db_path:
        argv.extend(["--sqlite-db-path", sqlite_db_path])

    report = audit.build_report(audit.parse_args(argv)).to_dict()
    counts = report.get("counts", {})
    coverage_errors: list[str] = []
    if int(counts.get("json_files_scanned") or 0) < min_json_files:
        coverage_errors.append(
            "json_files_scanned below required minimum "
            f"({counts.get('json_files_scanned', 0)}<{min_json_files})"
        )
    if int(counts.get("database_checks") or 0) < min_database_checks:
        coverage_errors.append(
            "database_checks below required minimum "
            f"({counts.get('database_checks', 0)}<{min_database_checks})"
        )

    status = "ok" if report.get("ok") and not coverage_errors else "degraded"
    report["status"] = status
    report["coverage_errors"] = coverage_errors
    report["data_dir"] = _email_retention_data_dir()
    return report


def _ensure_selftest_account() -> int | None:
    """Upsert the synthetic self-test account and return its id.

    The account row exists solely to exercise `_resolve_room_for_account`
    — it is never synced, never sent mail to. Returns None if the DB
    layer refuses insertion (which is itself a diagnostic signal).
    """
    from app.db.database import get_db_session
    from app.db.models.account import Account
    from app.db.repositories.account_repository import AccountRepository

    with get_db_session() as session:
        repo = AccountRepository(session)
        existing = repo.get_by_email(_SELFTEST_EMAIL)
        if existing:
            return int(existing.id)

        account = Account(
            email=_SELFTEST_EMAIL,
            provider=_SELFTEST_PROVIDER,
            display_name="Agentys Self-Test",
            is_active=False,  # never picked up by sync loops
        )
        session.add(account)
        session.commit()
        return int(account.id)


def _percentiles(
    values: list[float], pcts: tuple[float, ...]
) -> Dict[str, float | None]:
    """Type-7 quantile (Excel/numpy default) for a small sample.

    Returns ``{f"p{int(p)}": value}`` with ``None`` when the sample is
    empty — empty != 0; a 0 in JSON would falsely mean "we measured
    rooms but none were old", which is not the same diagnostic signal.
    """
    keys = tuple(f"p{int(p)}" for p in pcts)
    if not values:
        return {k: None for k in keys}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    out: Dict[str, float | None] = {}
    for p, key in zip(pcts, keys):
        idx = (n - 1) * (p / 100.0)
        lo = int(idx)
        frac = idx - lo
        if lo + 1 < n:
            v = sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])
        else:
            v = sorted_vals[lo]
        out[key] = round(v, 1)
    return out


@selftest_bp.route("/ws-stats", methods=["GET"])
def ws_stats() -> Any:
    """WebSocket rooms observability — issue #577 item 3.

    Token-protected (same OBSERVABILITY_TOKEN as ws-selftest). Polled
    daily by the sentinel layer 4 in nightly.yml; thresholds breach
    triggers an auto-sentinelle issue.

    Payload contract — DO NOT rename keys without updating the GH
    Actions parser; renames silently break monitoring.
        pending_rooms_count          int
        pending_events_total         int
        pending_room_age_seconds_p50 float | null
        pending_room_age_seconds_p95 float | null
        cache_warmup_rooms_count     int
        total_emits                  int  (lifetime, since process boot)

    Why "pending rooms" and not "active rooms": Flask-SocketIO does not
    expose a stable cross-eventlet API for the active room registry.
    `_pending_events` is the dict we own and GC ourselves; counting it
    is the leak signal we control.
    """
    if not _check_token():
        # Same body as ws-selftest 401 — never disclose env-var-vs-bad-header.
        return jsonify({"error": "unauthorized"}), 401

    from app.api.websocket import (
        get_cache_warmup_rooms_count,
        get_emit_count,
        get_pending_rooms_stats,
    )

    pending = get_pending_rooms_stats()
    age_pcts = _percentiles(pending["ages_seconds"], (50.0, 95.0))
    return jsonify({
        "pending_rooms_count": pending["rooms_count"],
        "pending_events_total": pending["events_total"],
        "pending_room_age_seconds_p50": age_pcts["p50"],
        "pending_room_age_seconds_p95": age_pcts["p95"],
        "cache_warmup_rooms_count": get_cache_warmup_rooms_count(),
        "total_emits": get_emit_count(),
    }), 200


@selftest_bp.route("/scheduler-health", methods=["GET"])
def scheduler_health() -> Any:
    """Return the freshness of every background scheduler heartbeat.

    Issue #577 item 4. Polled daily by the sentinel layer 4 in
    ``nightly.yml``. The sentinel relies on the HTTP status code:
        200  every scheduler has beaten within its declared interval
        503  at least one scheduler is stale (auto-sentinelle fires)
        401  unauthorized (token missing/wrong)

    The body always contains the full ``schedulers`` list so a human
    reading the issue can see which scheduler died and how long ago.

    A fresh deploy with no rows yet returns 200 — staleness only
    applies to schedulers that have at least beaten once. Known rows
    from the previous process get a short boot grace so the sentinel
    does not fire while the new process is still starting its threads.
    """
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401

    from app.services.scheduler_heartbeat import get_all_heartbeats, is_stale

    now = datetime.now(timezone.utc)
    within_boot_grace = (
        (now - _PROCESS_STARTED_AT).total_seconds()
        < _SCHEDULER_BOOT_GRACE_SECONDS
    )
    rows = get_all_heartbeats()
    schedulers = []
    stale_list = []
    for row in rows:
        last_run = row.last_run_at
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        elapsed = (now - last_run).total_seconds()
        stale = is_stale(row, now)
        boot_grace = (
            stale
            and within_boot_grace
            and row.name in _BOOT_GRACE_SCHEDULERS
            and last_run < _PROCESS_STARTED_AT
        )
        if boot_grace:
            stale = False
        entry = {
            "name": row.name,
            "last_run_at": last_run.isoformat(),
            "last_status": row.last_status,
            "expected_interval_seconds": row.expected_interval_seconds,
            "elapsed_seconds": int(elapsed),
            "stale": stale,
        }
        if boot_grace:
            entry["boot_grace"] = True
        schedulers.append(entry)
        if stale:
            stale_list.append(entry)

    overall = "degraded" if stale_list else "ok"
    body = {
        "status": overall,
        "schedulers": schedulers,
        "stale_schedulers": stale_list,
    }
    return jsonify(body), (503 if stale_list else 200)


@selftest_bp.route("/email-retention-audit", methods=["GET"])
def email_retention_audit() -> Any:
    """Run the metadata-only retention audit inside the live backend.

    This is the production bridge for ``scripts/audit_email_content_retention.py``:
    external cron runners cannot safely see Railway's volume or ``DATABASE_URL``,
    so the protected endpoint executes the audit in the backend process that owns
    those resources.
    """
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401

    try:
        report = _run_email_retention_audit(
            min_json_files=_query_int("min_json_files", 0),
            min_database_checks=_query_int("min_database_checks", 1),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("email-retention-audit failed")
        return jsonify({
            "status": "error",
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }), 500

    return jsonify(report), (200 if report.get("status") == "ok" else 503)


@selftest_bp.route("/ws-selftest", methods=["POST"])
def ws_selftest() -> Any:
    """Probe the WS account-scoped emission path end-to-end (server-side).

    Exercises the exact sequence that silently broke in #290:
        _resolve_room_for_account(account_id) → emit_to_account(...)

    Does NOT open a Socket.IO client — we assert that the server-side
    path runs to completion (room resolves to non-None, emit returns
    True). This is the failure mode #290 produced; richer end-to-end
    coverage (actual packet delivery) is left to the nightly E2E canary.
    """
    if not _check_token():
        # Do not reveal whether the env var is missing vs. the header is
        # wrong — both return 401 with the same body.
        return jsonify({"error": "unauthorized"}), 401

    started = time.monotonic()
    result: Dict[str, Any] = {
        "delivered": False,
        "room_resolved": False,
        "account_upserted": False,
        "latency_ms": 0,
        "reason": None,
    }

    try:
        account_id = _ensure_selftest_account()
    except Exception as e:
        logger.warning("ws-selftest: account upsert failed: %s", e)
        result["reason"] = f"account_upsert_failed:{type(e).__name__}"
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        return jsonify(result), 500

    if account_id is None:
        result["reason"] = "account_upsert_returned_none"
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        return jsonify(result), 500

    result["account_upserted"] = True

    from app.api.websocket import _resolve_room_for_account, emit_to_account

    room = _resolve_room_for_account(account_id)
    if room is None:
        # This is the #290 failure signature. The fix for #290 made sure
        # this returns the account email; if it ever returns None again,
        # the sentinel catches it within 10 minutes.
        result["reason"] = "room_resolution_returned_none"
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        return jsonify(result), 503

    result["room_resolved"] = True

    emitted = emit_to_account(
        "_selftest:ping",
        {"ts": time.time(), "probe": "ws-selftest"},
        account_id,
    )
    result["delivered"] = bool(emitted)
    result["latency_ms"] = int((time.monotonic() - started) * 1000)

    if not emitted:
        # Room resolved but emit_to_account returned False — socketio is
        # probably not initialised or the room buffer rejected the event.
        result["reason"] = "emit_returned_false"
        return jsonify(result), 503

    return jsonify(result), 200
