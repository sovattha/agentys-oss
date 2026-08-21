# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Starter Quick Steps proposed to every user.

Each rule lands in the user's list with ``enabled=False`` (disabled in
Settings) but ``autoEnabled=True`` (preconfigured in automatic mode). The
intent is *ready, don't run*: ship the same 4 cards everyone could benefit
from, let the user decide which ones to enable, then run them automatically
without an extra mode toggle.

Names are the **contract** with the rest of the codebase — they're used
by:
- ``agentys-app/src/components/Settings.tsx`` (discovery surface lists 3
  of these by exact name)
- ``tools/seed_quickstep_descriptions.py`` (also keyed on these names)

Keep names stable across releases. If you need to evolve a rule's
internals, update the existing entry rather than renaming — a rename
makes the discovery surface think the rule was deleted.

IDs are derived via ``uuid5(NAMESPACE_DNS, "agentys.starter.<name>")`` so
re-running the backfill script never creates duplicate rows with new
ids — the same starter rule resolves to the same UUID across every
account. The schema validator only checks UUID *shape*, not the v4 bit,
so uuid5 is accepted.
"""
from __future__ import annotations

import uuid
from typing import Iterable


def _starter_uuid(name: str) -> str:
    """Deterministic UUID for a starter rule, keyed on its name.

    Same name → same UUID across processes and accounts. This is what
    makes the backfill script idempotent: re-runs upsert on the existing
    id rather than appending duplicates.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"agentys.starter.quicksteps.{name}"))


def _followup_body_html(
    *, greeting: str, first_name_label: str, line: str, closing: str
) -> str:
    """Build the localized follow-up draft body as editor HTML.

    The recipient's first name is a ``{x}`` placeholder *chip* (a
    ``data-ar-token`` span), so the seeded body renders exactly like one the
    user composed in the Quick Step editor — and the backend renderer
    (``_render_body`` in ``handlers/create_snoozed_followup_draft.py``) resolves
    the chip back to the first name at draft time, stripping the surrounding
    ``<div>`` / ``<br>`` structure to clean plain text.

    Unlike the rule *name* (English in the DB, localized at render via the
    ``SEEDED_NAME_TO_KEY`` overlay — see ``project_seeded_quickstep_i18n``), the
    body is editable user content that can't be overlaid at render without
    clobbering edits, so we localize it once at seed time per the account's
    ``preferred_language``.
    """
    chip = (
        '<span class="ar-token" data-ar-token="recipient_first_name" '
        f'contenteditable="false">{first_name_label}</span>'
    )
    return (
        f"<div>{greeting} {chip},</div>"
        "<div><br></div>"
        f"<div>{line}</div>"
        "<div><br></div>"
        f"<div>{closing}</div>"
    )


# Localized follow-up draft body, keyed on the account's 2-letter language.
# The chip *label* is cosmetic (the editor shows it; the backend resolves the
# chip by token, not label) so it tracks the `{x}`-menu label per locale
# (`quicksteps_snoozed_draft_var_first_name_label`).
_FOLLOWUP_BODY_BY_LANG: dict[str, str] = {
    "fr": _followup_body_html(
        greeting="Bonjour",
        first_name_label="Prénom du destinataire",
        line=(
            "Petite relance sur mon dernier email. Faites-moi signe si vous "
            "avez besoin de quoi que ce soit de mon côté."
        ),
        closing="Cordialement,",
    ),
    "en": _followup_body_html(
        greeting="Hi",
        first_name_label="First name",
        line=(
            "Just wanted to follow up on my last email. Let me know if you "
            "need anything from my side."
        ),
        closing="Sincerely,",
    ),
    "es": _followup_body_html(
        greeting="Hola",
        first_name_label="First name",
        line=(
            "Solo quería hacer un seguimiento de mi último correo. Avísame si "
            "necesitas algo de mi parte."
        ),
        closing="Atentamente,",
    ),
}


def _followup_body(language: str) -> str:
    """Pick the follow-up draft body for ``language`` (fallback: French)."""
    short = (language or "fr").strip()[:2].lower()
    return _FOLLOWUP_BODY_BY_LANG.get(short, _FOLLOWUP_BODY_BY_LANG["fr"])


def _make_rule(
    *,
    name: str,
    description: str,
    actions: list[dict],
    triggers: list[dict],
    fires_on: str = "received",
    trigger_operator: str = "AND",
) -> dict:
    """Build one starter rule with safe defaults (disabled, auto-ready)."""
    return {
        "id": _starter_uuid(name),
        "name": name,
        "description": description,
        "icon": None,
        "shortcut": None,
        "actions": actions,
        "enabled": False,
        "confirmBeforeRun": False,
        # Ready, don't run — the rule is preconfigured as automatic, but the
        # disabled card cannot fire until the user enables it in Settings.
        "autoEnabled": True,
        # The ⚡ Auto badge on rows this rule auto-actioned. Default True
        # mirrors the validator's default (cf. schema.py:514) — the user
        # can toggle it off per rule.
        "showAutoBadge": True,
        "triggerOperator": trigger_operator,
        "triggers": triggers,
        "firesOn": fires_on,
    }


def build_default_quick_steps(
    account_email: str = "", language: str = "fr"
) -> list[dict]:
    """Return the starter pack proposed to every new account.

    ``account_email`` is kept in the signature for backward compatibility
    with callers (``store.py``, the backfill script, tests) — none of the
    current starter rules need it. Reintroduce a use here if a future
    starter rule has to interpolate the account's own address.

    ``language`` (the account's ``preferred_language``) localizes the
    follow-up draft body so a FR account doesn't get an English draft seeded
    into its DB. Rule *names* stay English (the discovery-surface contract —
    see ``project_seeded_quickstep_i18n``); only the editable body is
    localized here.
    """
    _ = account_email  # reserved for future per-account interpolation
    followup_body = _followup_body(language)
    return [
        _make_rule(
            name="Follow-up new thread",
            description=(
                "When you start a brand-new thread, schedule a follow-up "
                "draft in case the recipient doesn't reply within a week."
            ),
            triggers=[
                {"type": "is_new_thread", "value": "true"},
            ],
            actions=[
                {
                    "type": "create_snoozed_followup_draft",
                    "payload": {
                        "body": followup_body,
                        "delay_days": 7,
                    },
                },
            ],
            fires_on="sent",
        ),
        _make_rule(
            name="Follow-up existing thread",
            description=(
                "When you reply with a question to an ongoing thread, queue "
                "a follow-up nudge so unanswered questions don't disappear."
            ),
            triggers=[
                # body contains '?' may also match quoted text from the
                # other party — acceptable false-positive: the snoozed draft
                # lands in Later and is deletable. False negatives (reply
                # with no '?' at all) are the design goal.
                {"type": "email_text", "match_mode": "body", "value": "?"},
                {"type": "is_new_thread", "value": "false"},
            ],
            actions=[
                {
                    "type": "create_snoozed_followup_draft",
                    "payload": {
                        "body": followup_body,
                        "delay_days": 7,
                    },
                },
            ],
            fires_on="sent",
        ),
        _make_rule(
            name="Archive after reply",
            description=(
                "After you reply to a thread, archive it — your inbox view "
                "stays focused on conversations that still need attention."
            ),
            triggers=[
                {"type": "thread_has_user_reply", "value": "true"},
            ],
            actions=[
                {"type": "archive", "payload": {}},
            ],
        ),
        _make_rule(
            name="Accept meeting invitation",
            description=(
                "Auto-accept calendar invites when you're free at that time "
                "slot — the response goes out as soon as the invite lands, "
                "no back-and-forth."
            ),
            triggers=[
                {"type": "calendar_invite", "match_mode": "any", "value": "true"},
                {"type": "calendar_invite", "match_mode": "free", "value": "true"},
            ],
            actions=[
                {
                    "type": "rsvp_meeting",
                    "payload": {"response": "accepted"},
                },
            ],
        ),
    ]


def starter_pack_names() -> Iterable[str]:
    """Names of every starter rule — used by the backfill script to
    detect which rules are missing on a given account.
    """
    return (s["name"] for s in build_default_quick_steps())


__all__ = [
    "build_default_quick_steps",
    "starter_pack_names",
]
