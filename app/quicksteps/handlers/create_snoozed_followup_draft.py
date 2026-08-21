# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""create_snoozed_followup_draft — eager-creation follow-up draft handler.

Fires from a ``firesOn="sent"`` Quick Step. When the engine matches a
sent email (typically scoped via ``is_new_thread=true``), this handler:

1. Builds a draft body from the rule's template (no LLM call — the body
   is a static Jinja-like string interpolated with ``recipient_name``,
   ``recipient_first_name`` and ``original_subject``).
2. Persists a ``PendingDraft`` with ``routing_tier="followup"`` so the
   "⚡ Auto" badge surface in ``PendingDraftDetail`` / ``PipelineDisclosure``
   picks it up for free.
3. Stores a ``draft_followup`` reminder entry with
   ``reminder_date = now + delay_days``. While the snooze is active, the
   drafts API filters this draft out of the regular Drafts list (it
   surfaces only in "Later" with a Snoozed badge). When the date passes
   the wake-time sweep does a ``get_thread_messages`` reply check and
   either deletes the draft (recipient already replied) or lets it
   promote into Drafts.

No Gmail / IMAP call at creation time — the draft is local until the
user reviews and sends. This keeps native mail clients quiet during the
snooze window.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.quicksteps import template as template_engine
from app.quicksteps.types import ActionResult, ExecutionContext
from app.utils.email_filters import is_availability_email, is_noreply_recipient

logger = logging.getLogger(__name__)

# Native-client visibility marker — applied on the user's sent message at
# wake-time when no reply has come in. Matches the legacy nudge label so
# users who switched from auto_followup don't see two different tags.
_FOLLOWUP_LABEL = "Follow up"

_TEMPLATE_VARIABLE_RE = re.compile(
    r"\{\{\s*(recipient_first_name|recipient_name|original_subject)\s*\}\}"
)

# `{x}` placeholder chips authored in the Quick Step editor: a span carrying
# the token in ``data-ar-token``. Convert them to the ``{{token}}`` form this
# handler already substitutes (double-brace here, unlike the single-brace
# quick-step template renderer).
_CHIP_SPAN_RE = re.compile(
    r'<span\b[^>]*\bdata-ar-token="([^"]+)"[^>]*>.*?</span>',
    re.IGNORECASE | re.DOTALL,
)


def _chips_to_tokens(template: str) -> str:
    if not template or "data-ar-token=" not in template:
        return template
    return _CHIP_SPAN_RE.sub(lambda m: "{{" + m.group(1) + "}}", template)

# 🔁 = "awaiting follow-up". Stamped on the PendingDraft itself so the
# Drafts row chip is reliable — see the constructor note below.
_FOLLOWUP_MARKER_EMOJI = "🔁"

# Recipient-name humaniser, shared with the unified template renderer so the
# {{recipient_name}} interpolation matches everywhere. Re-exported here because
# tests and other call sites import it from this module.
_humanise_recipient = template_engine._humanise_recipient

# The follow-up body is rendered/sent as PLAIN TEXT, but the seeded default
# (and any body the user edits in the rich Quick Step editor) is HTML: `{x}`
# chips plus `<div>`/`<br>` line structure. ``render_plain`` resolves the chip
# spans to text but leaves the block tags, so without this pass the stored
# ``draft_body`` would carry literal `<div>` markup. Kept in lockstep with
# ``stripHtmlTags`` in ``PendingDraftDetail.tsx`` so the in-app preview and the
# stored body agree on line breaks.
_HAS_TAG_RE = re.compile(r"<[a-z][\s\S]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_CLOSE_BLOCK_RE = re.compile(r"</(?:p|div)>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(value: str) -> str:
    """Flatten editor HTML (chips already resolved) to plain text.

    Mirrors the frontend ``stripHtmlTags``: ``<br>`` and closing
    ``</div>`` / ``</p>`` become newlines, every other tag is dropped, the
    common entities are unescaped, runs of 3+ newlines collapse to 2. No-op
    for tag-free bodies (the legacy plain-text templates) so their rendered
    output is byte-for-byte unchanged.
    """
    if not value or not _HAS_TAG_RE.search(value):
        return value
    text = _BR_RE.sub("\n", value)
    text = _CLOSE_BLOCK_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub("", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _render_body(template: str, *, recipient_addr: str, original_subject: str) -> str:
    """Render the follow-up body via the unified Quick Step template engine.

    Delegates to :mod:`app.quicksteps.template` so the follow-up body shares
    one renderer + vocabulary with reply/forward templates. Resolves both the
    legacy ``{{recipient_name}}`` / ``{{recipient_first_name}}`` /
    ``{{original_subject}}`` names and the canonical ``{recipient.name}`` /
    ``{subject}`` forms. ``on_unknown="literal"`` keeps the old behaviour of
    leaving unrecognised braces (e.g. a pasted ``{shipping_id}``) untouched
    rather than blanking them.

    The template engine resolves chip spans (``data-ar-token``) to text but
    leaves block-level ``<div>`` / ``<br>`` tags; ``_html_to_text`` flattens
    those so the stored draft body is clean plain text.
    """
    ctx = template_engine.build_context(
        recipient_email=recipient_addr,
        subject=original_subject,
    )
    rendered = template_engine.render_plain(template or "", ctx, on_unknown="literal")
    return _html_to_text(rendered)


def _reply_subject(original: str) -> str:
    if original.lower().startswith(("re:", "ré :", "re :")):
        return original
    return f"Re: {original}" if original else "Re:"


def handle_create_snoozed_followup_draft(
    ctx: ExecutionContext,
    payload: dict,
) -> ActionResult:
    """Eager-create a follow-up draft and snooze it for ``delay_days``.

    Payload (validated upstream by schema.py):
      - body: str — template body, supports {{recipient_name}},
        {{recipient_first_name}} and {{original_subject}} placeholders.
        Required.
      - delay_days: int 1..365 — how long the draft stays in "Later"
        before being eligible to surface in Drafts. Default 7.
    """
    template = payload.get("body", "") or ""
    delay_days = int(payload.get("delay_days") or 7)

    recipient = (getattr(ctx.email, "recipient", "") or "").strip()
    if not recipient:
        # Defensive: an unaddressed sent email can't get a follow-up.
        # Skipped rather than crashed if a malformed entry slipped through.
        return ActionResult(ok=False, error="snoozed_draft_missing_recipient")

    # Inherited from the legacy nudge loop: never queue a follow-up to an
    # unmanned mailbox — no human reads it, so no reply will ever come.
    if is_noreply_recipient(recipient):
        return ActionResult(ok=False, error="snoozed_draft_noreply_recipient")

    original_subject = getattr(ctx.email, "subject", "") or ""
    thread_id = (getattr(ctx.email, "thread_id", "") or "").strip()

    # If the just-sent email is itself sharing availability (booking link,
    # listed slots, "here are my times"), the recipient is expected to pick
    # — a follow-up from our side would be noise. Inherited from the legacy
    # nudge loop.
    sent_body = (
        getattr(ctx.email, "body", "")
        or getattr(ctx.email, "body_html", "")
        or ""
    )
    if is_availability_email(sent_body):
        return ActionResult(ok=False, error="snoozed_draft_availability_email")

    draft_body = _render_body(
        template,
        recipient_addr=recipient,
        original_subject=original_subject,
    )
    if not draft_body.strip():
        return ActionResult(ok=False, error="snoozed_draft_empty_body")

    draft_subject = _reply_subject(original_subject)

    # Persist the local PendingDraft. account_id on PendingDraft is str
    # (matches the hex multi-accounts id everywhere else in the store);
    # we coerce defensively because firesOn="sent" plumbing passes the
    # int Account.id.
    #
    # ``email_sender`` = the recipient of the *original* send, i.e. the
    # conversation partner we're following up with. Matches the convention
    # for inbound pending drafts (where email_sender is the other party,
    # never the user). Setting it to the user's address would trip
    # ``_filter_self_sent_drafts`` and hide the draft from /api/pending-drafts.
    pending = PendingDraft(
        email_id=thread_id or ctx.email_id or ctx.raw_id or "",
        email_sender=recipient,
        email_subject=original_subject,
        draft_subject=draft_subject,
        draft_body=draft_body,
        routing_tier="followup",
        classification="followup",
        status=PendingDraftStatus.PENDING,
        account_id=str(ctx.account_id) if ctx.account_id else None,
        created_at=datetime.now(timezone.utc).isoformat(),
        # Carried on the draft itself rather than inherited from the sent
        # email row: a sibling `mark_with_emoji` action on a firesOn="sent"
        # rule races send-time persistence and returns email_not_found (the
        # real sent row isn't in the DB yet), so the email-row path never
        # lands. Setting it here makes the Drafts-row chip reliable and
        # timing-independent — rendered via `EmojiMarkerChip`
        # (PendingDraftList.tsx), surfaced by routes_pending.list_pending_drafts.
        emoji_marker={"emoji": _FOLLOWUP_MARKER_EMOJI},
    )

    try:
        from app.infrastructure.container import get_container
        store = get_container().get_pending_draft_store()
        store.add(pending)
    except Exception as exc:  # noqa: BLE001
        logger.error("[SNOOZED_DRAFT] PendingDraftStore.add failed: %s", exc)
        return ActionResult(ok=False, error=f"snoozed_draft_store_error: {exc}")

    wake_at = datetime.now(timezone.utc) + timedelta(days=delay_days)
    reminder_account = ctx.account_id if ctx.account_id and ctx.account_id > 0 else None
    try:
        from app.services.reminder_service import add_reminder
        reminder_id = add_reminder(
            email_id=pending.id,
            subject=draft_subject,
            reminder_date_iso=wake_at.isoformat(),
            account_id=reminder_account,
            reminder_type="draft_followup",
        )
    except Exception as exc:  # noqa: BLE001
        # Reminder is the load-bearing surface: without it the draft would
        # immediately appear in Drafts. Roll back the PendingDraft to keep
        # the system consistent — half-applied state would be worse than
        # a failed rule firing.
        logger.error("[SNOOZED_DRAFT] reminder add failed, rolling back draft: %s", exc)
        try:
            store.delete(pending.id)
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.error("[SNOOZED_DRAFT] rollback failed: %s", cleanup_exc)
        return ActionResult(ok=False, error=f"snoozed_draft_reminder_error: {exc}")

    logger.info(
        "[SNOOZED_DRAFT] created draft %s (snoozed until %s) for thread %s → %s",
        pending.id, wake_at.isoformat(), thread_id or "(no-thread)", recipient,
    )
    return ActionResult(
        ok=True,
        artifact={
            "pending_draft_id": pending.id,
            "reminder_id": reminder_id,
            "wake_at": wake_at.isoformat(),
            "delay_days": delay_days,
            "recipient": recipient,
        },
    )


# ---------------------------------------------------------------------------
# Wake-time sweep
# ---------------------------------------------------------------------------

def _recipient_replied(messages: list, account_email: str) -> bool:
    """True iff the thread contains a message NOT sent by ``account_email``.

    Pure string compare on the ``sender`` field — no LLM. Robust against
    capitalisation and the ``"Name" <addr>`` envelope shape Gmail returns:
    we just check substring containment of the bare address.
    """
    if not messages or not account_email:
        return False
    me = account_email.strip().lower()
    if not me:
        return False
    for msg in messages:
        sender = (getattr(msg, "sender", "") or "").strip().lower()
        if not sender:
            continue
        if me not in sender:
            return True
    return False


def sweep_woken_draft_followups(
    *,
    account_id: int,
    account_email: str,
    provider,
) -> dict:
    """Process all draft_followup reminders past their wake date.

    For each expired-and-not-yet-notified entry:
      - If the underlying PendingDraft is gone (manually deleted by the
        user) → mark the reminder notified so we stop revisiting it.
      - Else → call ``provider.get_thread_messages(thread_id)``. If the
        recipient has replied (any non-self sender in the thread), delete
        the PendingDraft AND the reminder (no zombie relance). Otherwise
        mark the reminder notified — this is what surfaces the draft in
        the regular Drafts list (the API filter only hides drafts whose
        reminder is ``notified=False``).

    Returns a dict ``{checked, promoted, deleted, errors}`` for logging.

    Idempotent: re-running after all entries are processed is a no-op
    (everything is already ``notified=True``).
    """
    from app.services.reminder_service import (
        _mark_notified,
        dismiss_reminder,
        list_draft_followups,
    )
    from app.infrastructure.container import get_container

    counters = {"checked": 0, "promoted": 0, "deleted": 0, "errors": 0}
    if account_id is None or account_id <= 0:
        return counters

    entries = list_draft_followups(account_id=account_id)
    if not entries:
        return counters

    now_iso = datetime.now(timezone.utc).isoformat()
    store = get_container().get_pending_draft_store()

    for entry in entries:
        if entry.get("notified", False):
            continue
        if (entry.get("reminder_date") or "") > now_iso:
            continue

        counters["checked"] += 1
        draft_id = entry.get("email_id", "")
        reminder_id = entry.get("id", "")

        pending = store.get_by_id(draft_id) if draft_id else None
        if pending is None:
            # Draft was deleted out-of-band; clean up the orphan reminder.
            if reminder_id:
                dismiss_reminder(reminder_id, account_id=account_id)
            continue

        # Draft was rejected/sent by the user before its snooze elapsed —
        # the reject endpoint flips the status but leaves the row in the
        # store. Treat as a clean cancellation: drop the reminder so the
        # sweep doesn't keep evaluating it forever, and don't waste a
        # provider API call on it.
        try:
            status_val = pending.status.value if hasattr(pending.status, "value") else pending.status
        except Exception:  # noqa: BLE001
            status_val = ""
        if status_val in ("rejected", "sent", "validated"):
            if reminder_id:
                dismiss_reminder(reminder_id, account_id=account_id)
            continue

        thread_id = (pending.email_id or "").strip()
        if not thread_id or provider is None:
            # No thread to check against (legacy or no-thread send) — fall
            # back to promotion. The user can still delete the draft
            # manually if they don't want it.
            _mark_notified(reminder_id)
            counters["promoted"] += 1
            continue

        try:
            messages = provider.get_thread_messages(thread_id)
        except Exception as exc:  # noqa: BLE001
            # Provider error → leave the entry unprocessed so the next
            # sweep retries. Don't crash the whole loop.
            logger.warning(
                "[SNOOZED_DRAFT] get_thread_messages failed for %s: %s",
                thread_id, exc,
            )
            counters["errors"] += 1
            continue

        if _recipient_replied(messages or [], account_email):
            try:
                store.delete(draft_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[SNOOZED_DRAFT] store.delete(%s) failed: %s", draft_id, exc
                )
                counters["errors"] += 1
                continue
            dismiss_reminder(reminder_id, account_id=account_id)
            counters["deleted"] += 1
            logger.info(
                "[SNOOZED_DRAFT] reply detected on thread %s → deleted draft %s",
                thread_id, draft_id,
            )
        else:
            # TOCTOU re-check (chaos audit 2026-06-02): the concurrent
            # _kill_snoozed_followup_for_thread task (also fired on sync-complete)
            # may have deleted this draft DURING the get_thread_messages call
            # above. Re-fetch before surfacing/pinning so we don't leave a pinned
            # inbox thread + reminder for a draft that no longer exists.
            if store.get_by_id(draft_id) is None:
                logger.info(
                    "[SNOOZED_DRAFT] draft %s deleted concurrently during sweep "
                    "→ skipping surface/pin", draft_id,
                )
                if reminder_id:
                    dismiss_reminder(reminder_id, account_id=account_id)
                continue
            _mark_notified(reminder_id)
            _surface_thread_to_inbox(
                thread_id=thread_id,
                subject=pending.email_subject or pending.draft_subject or "",
                account_id=account_id,
            )
            # Pin the woken follow-up. The same id (thread_id) drives both
            # surfaces: the surfaced inbox thread (EmailList "Pinned" section)
            # and the promoted draft, whose email_id == thread_id (Drafts
            # "Pinned" section). Auto-unpinned by the validate/reject draft
            # paths so it doesn't linger like the old Sent label did.
            if thread_id:
                from app.services.pinned_emails import add_pinned_email_id
                add_pinned_email_id(account_id, thread_id)
            counters["promoted"] += 1
            logger.info(
                "[SNOOZED_DRAFT] no reply on thread %s → promoted draft %s + surfaced to inbox",
                thread_id, draft_id,
            )

    return counters


def _surface_thread_to_inbox(*, thread_id: str, subject: str, account_id: int) -> None:
    """Surface the original sent thread to the inbox top on draft wake.

    Same plumbing as ``handle_follow_up``: an immediate-date reminder
    (``reminder_type="followup"``) that ``useSnooze`` syncs and treats as
    a woken thread, bubbling it back into the inbox view. The draft
    auto-loads in the email-detail modal via the existing
    ``getPendingDraftByEmailId`` lookup keyed on the same ``thread_id`` —
    so opening the surfaced thread shows the relance ready to send.

    Failure is non-fatal: the draft is already promoted in the Drafts
    panel, so a missing inbox surface just means the user reaches it via
    Drafts instead of inbox. Log and continue.
    """
    try:
        from app.services.reminder_service import add_reminder
        add_reminder(
            email_id=thread_id,
            subject=subject or "(no subject)",
            reminder_date_iso=datetime.now(timezone.utc).isoformat(),
            account_id=account_id if account_id and account_id > 0 else None,
            reminder_type="followup",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[SNOOZED_DRAFT] inbox surface failed for thread %s: %s",
            thread_id, exc,
        )
