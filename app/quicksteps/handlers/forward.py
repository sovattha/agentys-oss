# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""forward handler — forward the email to recipients (incl. contact-group
expansion) with an optional user note rendered above the quoted original."""
from __future__ import annotations

import html
import logging
from typing import Any

from app.quicksteps.handlers._shared import append_signature, emit
from app.quicksteps.template import render_html, render_plain
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_forward(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Forward the original email to one or more recipients.

    ``payload`` keys: to (list[str]), to_groups (optional list[str] — expanded
    to member emails at execution time), subject_prefix (optional str),
    body (optional HTML — user-supplied note rendered above the forwarded body).
    """
    try:
        recipients = list(payload.get("to") or [])
        group_ids = list(payload.get("to_groups") or [])
        if group_ids:
            expanded = _expand_contact_groups(group_ids, ctx.account_id)
            for addr in expanded:
                if addr not in recipients:
                    recipients.append(addr)
        if not recipients:
            return ActionResult(ok=False, error="forward_no_recipient")

        prefix = render_plain(payload.get("subject_prefix") or "Tr: ", ctx.template_vars)
        original_subject = getattr(ctx.email, "subject", "") or ""
        subject = (
            f"{prefix.strip()} {original_subject}".strip()
            if prefix
            else (original_subject or "(Sans objet)")
        )

        user_note_html = ""
        if payload.get("body"):
            user_note_html = render_html(payload["body"], ctx.template_vars)

        forwarded_body = _build_forward_body(user_note_html, ctx.email)
        body_with_signature = append_signature(forwarded_body, ctx.account_id)

        sent_id = _send_new(
            ctx.provider,
            to=recipients,
            subject=subject,
            body=body_with_signature,
            from_name=ctx.account_display_name or None,
        )
        if not sent_id:
            return ActionResult(ok=False, error="forward_send_failed")
        emit("emit_email_sent", ctx, payload={"is_reply": False, "message_id": sent_id})
        return ActionResult(ok=True, artifact={"message_id": sent_id, "to": recipients})
    except Exception as exc:  # noqa: BLE001
        logger.error("forward handler failed: %s", exc)
        return ActionResult(ok=False, error=f"forward_error: {exc}")


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #

def _build_forward_body(user_note_html: str, email: Any) -> str:
    sender_name = getattr(email, "sender_name", "") or ""
    sender_email = getattr(email, "sender", "") or ""
    subject = getattr(email, "subject", "") or ""
    when = getattr(email, "date", None)
    when_str = when.isoformat() if when else ""
    recipients = getattr(email, "recipients", "") or ""
    original_html = (getattr(email, "body_html", "") or "").strip()
    if not original_html:
        # Audit B-02: StandardEmail uses .body (not body_text). Forwards of
        # plain-text emails were shipping header-only with an empty body.
        plain = (
            getattr(email, "body", "")
            or getattr(email, "body_text", "")
            or ""
        ).strip()
        original_html = (
            html.escape(plain).replace("\n", "<br>") if plain else ""
        )

    # Audit B-09: escape attacker-controlled metadata before injecting into
    # is_html=True MIME. original_html stays unescaped (would break legit
    # content) but the quoting metadata MUST be escaped.
    safe_sender_name = html.escape(sender_name)
    safe_sender_email = html.escape(sender_email)
    safe_subject = html.escape(subject)
    safe_recipients = html.escape(recipients)
    safe_when = html.escape(when_str)
    header = (
        '<div style="border-top:1px solid #ccc;margin-top:16px;padding-top:8px">'
        '<b>---------- Message transféré ----------</b><br>'
        f"<b>De :</b> {safe_sender_name} &lt;{safe_sender_email}&gt;<br>"
        f"<b>Date :</b> {safe_when}<br>"
        f"<b>Objet :</b> {safe_subject}<br>"
        f"<b>À :</b> {safe_recipients}<br><br>"
        f"{original_html}"
        '</div>'
    )
    return f"{user_note_html}<br><br>{header}" if user_note_html else header


def _expand_contact_groups(group_ids: list[str], account_id: int) -> list[str]:
    try:
        from app.api.contact_groups import _get_group_by_id
        emails: list[str] = []
        for gid in group_ids:
            group = _get_group_by_id(gid)
            if group and group.get("account_id") == account_id:
                for member in group.get("members", []):
                    addr = member.get("email", "").strip().lower()
                    if addr and addr not in emails:
                        emails.append(addr)
        return emails
    except Exception as exc:  # noqa: BLE001
        logger.warning("group expansion failed: %s", exc)
        return []


def _send_new(
    provider: Any,
    *,
    to: list[str],
    subject: str,
    body: str,
    from_name: str | None,
) -> str | None:
    if hasattr(provider, "send_new_directly"):
        try:
            return provider.send_new_directly(
                to=to,
                subject=subject,
                body=body,
                is_html=True,
                from_name=from_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("send_new_directly failed: %s — falling back", exc)

    if hasattr(provider, "create_draft") and hasattr(provider, "send_draft"):
        draft_id = provider.create_draft(
            to=to,
            subject=subject,
            body=body,
            is_html=True,
            from_name=from_name,
        )
        if draft_id and provider.send_draft(draft_id):
            return draft_id
    return None
