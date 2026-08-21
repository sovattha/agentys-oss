# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""rsvp_meeting handler — accept/decline/tentative for a calendar invitation.

Bridges the int DB account_id to the OAuth-storage hex id the multi_accounts
manager keys by, then sends the RSVP. Free/busy gating is NOT done here — that
is the job of the ``calendar_invite + free`` trigger condition, which checks
the connected calendar AND local deep-work / focus blocks. This handler just
sends the response.
"""
from __future__ import annotations

import logging

from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_rsvp_meeting(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Accept, decline, or tentatively accept a meeting invitation.

    Sends the RSVP unconditionally — availability gating belongs to the
    ``calendar_invite + free`` trigger condition, not to this action. If the
    target email is not an RSVP-able invite the calendar provider surfaces
    ``no_ical_uid`` / ``event_not_found`` and we return ``not_a_meeting``.
    """
    response = payload.get("response", "accepted")

    # Resolve the OAuth-storage account_id from the int DB id. Tokens and
    # the multi-account manager key by the hex id minted at OAuth time
    # (multi_accounts.py:282) — passing str(13) finds nothing. We bridge
    # via the email so background-thread auto-triggers reach the same
    # account the UI does.
    #
    # Failure modes worth distinguishing:
    #   1. ctx.account_email empty   — engine couldn't load the account row
    #      at all; nothing to RSVP with. Fail loudly.
    #   2. multi_accounts has no cfg — token revoked / re-OAuth pending.
    #      The previous behaviour silently fell back to ``str(ctx.account_id)``
    #      and would either 401 against the wrong calendar or, worse on
    #      shared infra, succeed against a different user's OAuth session
    #      that happened to key on the same int. Fail loudly.
    oauth_account_id: str | None = None
    if not ctx.account_email:
        logger.warning(
            "rsvp_meeting: no account email for DB id %s — cannot resolve OAuth account",
            ctx.account_id,
        )
        return ActionResult(ok=False, error="calendar_account_unresolved")
    try:
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account_by_email(ctx.account_email)
        if cfg and getattr(cfg, "id", None):
            oauth_account_id = cfg.id
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rsvp_meeting: multi-account lookup failed for %s: %s",
            ctx.account_email, exc,
        )
        return ActionResult(ok=False, error="calendar_account_unresolved")
    if not oauth_account_id:
        logger.warning(
            "rsvp_meeting: no OAuth account registered for %s "
            "(re-authentication required?)",
            ctx.account_email,
        )
        return ActionResult(ok=False, error="calendar_account_unresolved")

    try:
        from app.providers.calendar_factory import create_calendar_provider
        cal = create_calendar_provider(oauth_account_id)
    except Exception as exc:
        logger.warning("rsvp_meeting: calendar provider unavailable: %s", exc)
        return ActionResult(ok=False, error="calendar_not_supported")

    if not cal or not hasattr(cal, "rsvp_event"):
        return ActionResult(ok=False, error="calendar_not_supported")

    try:
        result = cal.rsvp_event(ctx.raw_id, response)
    except Exception as exc:
        logger.error("rsvp_meeting: rsvp_event raised: %s", exc)
        return ActionResult(ok=False, error=f"rsvp_error: {exc}")

    if not result.get("ok"):
        error = result.get("error", "rsvp_failed")
        # Audit Cluster B (2026-05-10) U-04: `no_ical_uid` and `event_not_found`
        # aren't "user is busy" outcomes — they mean the target email isn't
        # actually RSVP-able. Surface as failure, not a green skip-success.
        if error in ("no_ical_uid", "event_not_found"):
            return ActionResult(ok=False, error="not_a_meeting")
        return ActionResult(ok=False, error=error)

    # Post-RSVP relabel: an invitation that the user has now accepted or
    # declined is no longer actionable — flip it from Action → Noise so it
    # stops showing up in "needs my attention" surfaces. Best-effort: the
    # RSVP already went out, label drift never blocks success.
    relabel_invitation_as_noise_after_rsvp(ctx.email_id, ctx.account_id, response)

    return ActionResult(ok=True, artifact={
        "event_id": result.get("event_id"),
        "response": response,
    })


def relabel_invitation_as_noise_after_rsvp(
    email_id: str,
    account_id: int | None,
    response: str,
) -> None:
    """Demote an invitation email's default label to Noise after RSVP.

    The labeller classifies a pending invitation as Action (requires RSVP);
    once the user has actually responded, the email is just historical
    record-keeping → Noise. Exported (not prefixed) so the HTTP RSVP route
    in ``app/api/calendar_routes.py`` can call the same path the Quick Step
    handler does. Best-effort, never raises.
    """
    if not email_id:
        return
    try:
        from app.domain.entities.email_labels import DefaultLabel
        from app.infrastructure.container import get_container

        store = get_container().get_label_store(
            account_id=account_id if account_id else None,
        )
        if store is None:
            return
        assignment = store.get_assignment(email_id)
        if assignment is None:
            # No prior assignment to update — labeller hasn't run on this
            # email yet (or ran and returned no labels). Skip.
            return
        # Only demote if the current default is Action; if the user (or a
        # rule) has already moved it elsewhere, respect that choice.
        if assignment.default_label != DefaultLabel.ACTION.value:
            return
        assignment.set_default_label(
            DefaultLabel.NOISE.value,
            0.95,
            f"RSVP'd ({response}) — invitation no longer actionable",
        )
        store.save_assignment(assignment)
    except Exception as exc:  # noqa: BLE001
        logger.debug("post-rsvp relabel suppressed: %s", exc)
