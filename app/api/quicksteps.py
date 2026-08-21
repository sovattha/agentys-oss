# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Routes API REST pour les Quick Steps.

Endpoints (tous account-scoped via JWT) :

    GET    /api/quicksteps                 — liste les Quick Steps du compte
    POST   /api/quicksteps                 — crée (ou remplace par id) un Quick Step
    PATCH  /api/quicksteps/<step_id>       — met à jour un Quick Step existant
    DELETE /api/quicksteps/<step_id>       — supprime un Quick Step
    POST   /api/quicksteps/<step_id>/execute  — exécute la chaîne sur un email

L'exécution est déterministe et n'invoque AUCUN appel LLM.
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from app.api.account_scope import account_scoped
from app.quicksteps import engine as engine_module
from app.quicksteps import schema as schema_module
from app.quicksteps import store as store_module

logger = logging.getLogger(__name__)

quicksteps_bp = Blueprint("quicksteps", __name__)


def _bad_request(message: str, code: str = "VALIDATION_ERROR"):
    return jsonify({"error": message, "code": code}), 400


@quicksteps_bp.route("/quicksteps", methods=["GET"])
@account_scoped
def list_quick_steps():
    """Retourne la liste des Quick Steps de l'utilisateur authentifié.

    The store already swallows transient failures and returns ``[]``,
    but we wrap the call defensively too: GET on this endpoint must
    never produce a body-less 500 — the settings panel renders that as
    a permanent error banner that bleeds across editor sessions.
    """
    try:
        steps = store_module.load_quick_steps(g.account_id)
    except Exception:
        logger.error(
            "Unexpected error in list_quick_steps for account %d",
            g.account_id, exc_info=True,
        )
        return jsonify({"quick_steps": [], "warning": "transient_load_failure"}), 200
    return jsonify({"quick_steps": steps}), 200


@quicksteps_bp.route("/quicksteps", methods=["POST"])
@account_scoped
def create_quick_step():
    """Crée un Quick Step. Si un Quick Step avec le même id existe, il est
    remplacé (idempotent — utile si le client retry après un timeout réseau)."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _bad_request("JSON body required")

    try:
        cleaned = schema_module.validate_quick_step(payload)
    except schema_module.ValidationError as exc:
        return _bad_request(str(exc))

    def _mutate(steps: list) -> list:
        if not store_module.find_step(steps, cleaned["id"]) and len(steps) >= schema_module.MAX_QUICK_STEPS_PER_ACCOUNT:
            raise store_module.QuickStepsConflict(
                f"Cannot create more than {schema_module.MAX_QUICK_STEPS_PER_ACCOUNT} Quick Steps",
                code="LIMIT_REACHED",
            )
        if cleaned["shortcut"]:
            for s in steps:
                if s.get("id") != cleaned["id"] and s.get("shortcut") == cleaned["shortcut"]:
                    raise store_module.QuickStepsConflict(
                        f"Shortcut '{cleaned['shortcut']}' is already used by '{s.get('name')}'",
                        code="SHORTCUT_CONFLICT",
                    )
        return store_module.upsert_step(steps, cleaned)

    try:
        store_module.transact_quick_steps(g.account_id, _mutate)
    except store_module.QuickStepsConflict as exc:
        return _bad_request(str(exc), code=exc.code)
    except Exception:
        logger.error("Failed to save Quick Step for account %d", g.account_id, exc_info=True)
        return jsonify({"error": "Failed to save Quick Step"}), 500
    return jsonify(cleaned), 201


@quicksteps_bp.route("/quicksteps/order", methods=["PUT"])
@account_scoped
def reorder_quick_steps():
    """Réordonne les Quick Steps selon la liste d'IDs fournie.
    Body: {"ids": ["uuid1", "uuid2", ...]}
    """
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return _bad_request("ids must be a list of Quick Step id strings")

    def _mutate(steps: list) -> list:
        by_id = {s["id"]: s for s in steps}
        ordered = [by_id[i] for i in ids if i in by_id]
        mentioned = set(ids)
        for s in steps:
            if s["id"] not in mentioned:
                ordered.append(s)
        return ordered

    try:
        new_steps = store_module.transact_quick_steps(g.account_id, _mutate)
    except Exception:
        logger.error("Failed to reorder Quick Steps for account %d", g.account_id, exc_info=True)
        return jsonify({"error": "Failed to reorder Quick Steps"}), 500
    return jsonify({"quick_steps": new_steps}), 200


@quicksteps_bp.route("/quicksteps/<step_id>", methods=["PATCH"])
@account_scoped
def update_quick_step(step_id: str):
    """Met à jour un Quick Step existant. ``step_id`` dans l'URL est
    autoritaire — un body avec un id différent est rejeté."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _bad_request("JSON body required")

    if "id" in payload and payload["id"] != step_id:
        return _bad_request("Body 'id' does not match URL id")

    _result: list = []  # captures the validated step from inside _mutate

    def _mutate(steps: list) -> list:
        existing = store_module.find_step(steps, step_id)
        if existing is None:
            raise store_module.QuickStepsConflict("Quick Step not found", code="NOT_FOUND")
        merged = {**existing, **{k: v for k, v in payload.items() if k != "id"}}
        try:
            cleaned = schema_module.validate_quick_step(merged, existing_id=step_id)
        except schema_module.ValidationError as exc:
            raise store_module.QuickStepsConflict(str(exc))
        if cleaned["shortcut"]:
            for s in steps:
                if s.get("id") != step_id and s.get("shortcut") == cleaned["shortcut"]:
                    raise store_module.QuickStepsConflict(
                        f"Shortcut '{cleaned['shortcut']}' is already used by '{s.get('name')}'",
                        code="SHORTCUT_CONFLICT",
                    )
        _result.append(cleaned)
        return store_module.upsert_step(steps, cleaned)

    try:
        store_module.transact_quick_steps(g.account_id, _mutate)
    except store_module.QuickStepsConflict as exc:
        if exc.code == "NOT_FOUND":
            return jsonify({"error": "Quick Step not found"}), 404
        return _bad_request(str(exc), code=exc.code)
    except Exception:
        logger.error("Failed to update Quick Step for account %d", g.account_id, exc_info=True)
        return jsonify({"error": "Failed to save Quick Step"}), 500
    return jsonify(_result[0]), 200


@quicksteps_bp.route("/quicksteps/<step_id>", methods=["DELETE"])
@account_scoped
def delete_quick_step(step_id: str):
    """Supprime un Quick Step. Renvoie 404 si introuvable."""
    def _mutate(steps: list) -> list:
        if store_module.find_step(steps, step_id) is None:
            raise store_module.QuickStepsConflict("Quick Step not found", code="NOT_FOUND")
        return store_module.remove_step(steps, step_id)

    try:
        store_module.transact_quick_steps(g.account_id, _mutate)
    except store_module.QuickStepsConflict as exc:
        if exc.code == "NOT_FOUND":
            return jsonify({"error": "Quick Step not found"}), 404
        return _bad_request(str(exc), code=exc.code)
    except Exception:
        logger.error("Failed to delete Quick Step for account %d", g.account_id, exc_info=True)
        return jsonify({"error": "Failed to delete Quick Step"}), 500
    return jsonify({"success": True}), 200


# Hard cap on `ids` per call : one inbox page (~50) plus headroom for
# multi-page prefetches. Higher than that and we degrade the read path
# without a real product reason — the UI doesn't badge invisible rows.
_AUTO_BADGES_MAX_IDS = 200


@quicksteps_bp.route("/quicksteps/auto-badges", methods=["GET"])
@account_scoped
def get_auto_badges():
    """Return the ⚡ Auto badge map for a list of email IDs.

    Query :
        ids — comma-separated email IDs, max ``_AUTO_BADGES_MAX_IDS``.

    Response :
        {"badges": {"<email_id>": {"stepId": str, "stepName": str,
                                    "executedAt": ISO-8601}}}

    Empty map for emails that : (a) were never auto-actioned, (b) only
    matched a step whose owner toggled ``showAutoBadge=false``, (c) only
    matched manual / failed executions. Best-effort : DB transients
    degrade to ``{}`` so the inbox keeps rendering without the badge.
    """
    raw_ids = (request.args.get("ids") or "").strip()
    if not raw_ids:
        return jsonify({"badges": {}}), 200
    ids = [eid.strip() for eid in raw_ids.split(",") if eid.strip()][:_AUTO_BADGES_MAX_IDS]
    if not ids:
        return jsonify({"badges": {}}), 200

    # Step 1 — gather which of the user's current steps STILL want a badge.
    # We filter by current showAutoBadge (not snapshot at execution time) so
    # toggling the rule off retroactively hides existing badges. That's the
    # natural UX expectation : "I turned the badge off, please stop showing it".
    #
    # F-04 (audit-2026-05-12_2129): in a Tauri multi-mailbox session,
    # run_auto_triggers aggregates rules across all linked accounts (see
    # app/quicksteps/auto_trigger.py:622), but files the audit row under the
    # EMAIL'S account_id, not the rule-owning account. The previous lookup
    # was scoped to `g.account_id`'s steps only — rules owned by another
    # session account were missing from `allowed_step_ids`, so the badge
    # never rendered. Walk the AccountManager to pull steps from every
    # session account (same set used by the cross-account aggregator).
    try:
        steps = list(store_module.load_quick_steps(g.account_id))
    except Exception:  # noqa: BLE001
        steps = []
    try:
        from app.multi_accounts import get_account_manager
        from app.api.routes_helpers import _resolve_account_id_for_email
        seen_step_ids = {s.get("id") for s in steps if s.get("id")}
        seen_account_ids = {g.account_id}
        for cfg in get_account_manager().get_all_accounts():
            other_email = getattr(cfg, "email", None)
            if not other_email:
                continue
            other_id = _resolve_account_id_for_email(other_email)
            if not other_id or other_id <= 0 or other_id in seen_account_ids:
                continue
            seen_account_ids.add(other_id)
            try:
                extra = store_module.load_quick_steps(other_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("auto-badges: cross-account load skipped for %d: %s", other_id, exc)
                continue
            for s in extra or []:
                sid = s.get("id")
                if not sid or sid in seen_step_ids:
                    continue
                seen_step_ids.add(sid)
                steps.append(s)
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-badges: cross-account aggregation failed: %s", exc)

    allowed_step_ids = {
        s["id"] for s in steps
        if s.get("id") and s.get("showAutoBadge", True)
    }
    if not allowed_step_ids:
        return jsonify({"badges": {}}), 200

    # Prefer the current step name (rules can be renamed). Fall back to the
    # denormalized step_name on the audit row for steps that no longer exist
    # but had their badge toggle on at execution time.
    step_name_by_id = {s["id"]: s.get("name") or "" for s in steps}

    # Step 2 — pull successful auto-executions for these emails, most-recent
    # first. We dedupe per-email in Python (we only need ONE badge per row).
    try:
        from app.db.database import get_db_session
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        with get_db_session() as session:
            rows = (
                session.query(
                    QuickStepAuditLog.email_id,
                    QuickStepAuditLog.step_id,
                    QuickStepAuditLog.step_name,
                    QuickStepAuditLog.created_at,
                )
                .filter(
                    QuickStepAuditLog.account_id == g.account_id,
                    QuickStepAuditLog.email_id.in_(ids),
                    QuickStepAuditLog.source == "auto",
                    QuickStepAuditLog.success.is_(True),
                    QuickStepAuditLog.step_id.in_(allowed_step_ids),
                )
                .order_by(QuickStepAuditLog.created_at.desc())
                .all()
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("get_auto_badges query failed for account %d: %s", g.account_id, exc)
        return jsonify({"badges": {}, "warning": "transient_query_failure"}), 200

    badges: dict[str, dict] = {}
    for row in rows:
        if row.email_id in badges:
            continue  # already grabbed the most-recent thanks to ORDER BY DESC
        ts = row.created_at
        # `default=datetime.utcnow` stores NAIVE UTC ; tag explicitly so the
        # frontend can parse without guessing tz.
        ts_iso = (ts.isoformat() + "Z") if ts and ts.tzinfo is None else (ts.isoformat() if ts else None)
        badges[row.email_id] = {
            "stepId": row.step_id,
            "stepName": step_name_by_id.get(row.step_id) or (row.step_name or ""),
            "executedAt": ts_iso,
        }
    return jsonify({"badges": badges}), 200


@quicksteps_bp.route("/quicksteps/dry-run", methods=["POST"])
@account_scoped
def dry_run_quick_step():
    """Match the provided trigger conditions against the last ~100 emails.

    No side effects — purely evaluates conditions and returns counts + a
    handful of matching subjects so the user can sanity-check filters
    before enabling auto-trigger on real mail.
    """
    payload = request.get_json(silent=True) or {}
    triggers = payload.get("triggers") or []
    operator = payload.get("triggerOperator", "OR")
    if not isinstance(triggers, list):
        return _bad_request("triggers must be a list")
    if operator not in ("AND", "OR"):
        return _bad_request("triggerOperator must be 'AND' or 'OR'")
    # Audit Cluster C (2026-05-11) U-06: manual-only steps (bound to a
    # keyboard shortcut, no auto-trigger predicate) used to be blocked
    # from the dry-run preview because `triggers` was always empty. Now
    # an empty list returns examined=0, matched=0, no_triggers=true so
    # the UI can render a clean "this step has no trigger to test"
    # message instead of a 400.
    if not triggers:
        return jsonify({
            "examined": 0,
            "matched": 0,
            "matches": [],
            "no_triggers": True,
        }), 200

    # BS1-001: validate each trigger structurally before reaching
    # _match_condition, which assumes a string `value` and would otherwise
    # AttributeError into a generic 500 on dict/list payloads.
    from app.quicksteps import schema as schema_module
    try:
        triggers = [
            schema_module._validate_trigger_condition(t, i)
            for i, t in enumerate(triggers)
        ]
    except schema_module.ValidationError as exc:
        return _bad_request(str(exc))

    from sqlalchemy import select

    from app.db.database import get_db_session
    from app.db.models import Email
    from app.quicksteps.auto_trigger import _match_condition

    matches: list[dict] = []
    examined = 0
    try:
        with get_db_session() as session:
            stmt = (
                select(Email)
                .where(Email.account_id == g.account_id)
                .order_by(Email.date.desc())
                .limit(100)
            )
            for email in session.scalars(stmt).all():
                examined += 1
                results = [
                    _match_condition(
                        c,
                        email,
                        account_id=g.account_id,
                        email_id=email.email_id or "",
                    )
                    for c in triggers
                ]
                ok = all(results) if operator == "AND" else any(results)
                if ok and len(matches) < 10:
                    matches.append({
                        "subject": email.subject or "(no subject)",
                        "sender": email.sender or "",
                        "date": email.date.isoformat() if email.date else None,
                    })
                elif ok:
                    matches.append({})  # count only past 10
    except Exception:
        logger.error("Quick Step dry-run failed for account %d", g.account_id, exc_info=True)
        return jsonify({"error": "dry-run failed"}), 500

    # Audit 2026-05-11 (Agent 5 P2): empty-trigger branch above returns
    # `matches`; the success branch returned `samples`. FE consumers got
    # `undefined` half the time. Pick one name (`matches`) for both.
    return jsonify({
        "examined": examined,
        "matched": len(matches),
        "matches": [m for m in matches if m][:10],
    }), 200


@quicksteps_bp.route("/quicksteps/<step_id>/execute", methods=["POST"])
@account_scoped
def execute_quick_step(step_id: str):
    """Exécute la chaîne d'actions du Quick Step ``step_id`` sur un email.

    Body JSON: ``{"email_id": "<provider_id>"}``.
    Header optionnel: ``Idempotency-Key`` (UUID) — dédupe les double-clics
    pendant 60 s.
    """
    payload = request.get_json(silent=True) or {}
    email_id = payload.get("email_id")
    if not isinstance(email_id, str) or not email_id.strip():
        return _bad_request("email_id is required")

    steps = store_module.load_quick_steps(g.account_id)
    step = store_module.find_step(steps, step_id)
    if step is None:
        return jsonify({"error": "Quick Step not found"}), 404
    if not step.get("enabled", True):
        return jsonify({"error": "Quick Step is disabled", "code": "STEP_DISABLED"}), 409

    idem_key = request.headers.get("Idempotency-Key", "").strip()

    report = engine_module.execute(
        account_id=g.account_id,
        step=step,
        email_id=email_id.strip(),
        idempotency_key=idem_key or None,
    )

    status = 200 if report.success else 502
    if report.error in ("email_not_found",):
        status = 404
    elif report.error and report.error.startswith("template_unknown_variables"):
        status = 400
    return jsonify(report.to_dict()), status
