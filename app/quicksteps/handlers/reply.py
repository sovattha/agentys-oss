# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""reply_template handler — send a templated reply with optional snippet
resolution, signature append, quoted original, and post-send auto-archive
when the user has the Action label workflow enabled.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from app.quicksteps.handlers._shared import (
    append_signature,
    emit,
    evict_caches,
)
from app.quicksteps.template import render_html
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_reply_template(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Send a templated reply to the original sender.

    ``payload`` keys (validated upstream): body (HTML), replyAll, includeQuoted.
    If ``snippet_id`` is set the body is resolved from the snippet at execution
    time so edits to the snippet propagate without re-saving the Quick Step.
    Variables in the body are interpolated with HTML escaping.

    After a successful send we mirror the regular reply path's behaviour:
    if the user has ``auto_archive_action`` enabled and the email carries
    the ``Action`` label, archive it. This matches what users expect when
    they press Ctrl+1 over an Action email — same outcome as a manual
    reply, no extra ``archive`` step required in the chain.
    """
    try:
        body = payload.get("body", "")
        snippet_id = payload.get("snippet_id")
        if snippet_id:
            snippet = _resolve_snippet(snippet_id)
            if snippet is None:
                return ActionResult(ok=False, error=f"snippet_not_found:{snippet_id}")
            body = snippet.get("content", "")
        rendered_body = render_html(body, ctx.template_vars)
        body_with_signature = append_signature(rendered_body, ctx.account_id)
        # includeQuoted is no longer user-toggleable — the editor checkbox was
        # removed (2026-05-19) and quoting the original is implicit. We ignore
        # any persisted `false` on legacy rules so the behavior matches the UI.
        body_with_signature = _append_quoted_original(body_with_signature, ctx.email)

        recipients = _build_reply_recipients(ctx, reply_all=payload.get("replyAll", False))
        if not recipients["to"]:
            return ActionResult(ok=False, error="reply_no_recipient")

        subject = _reply_subject(getattr(ctx.email, "subject", "") or "")
        thread_id = _resolve_thread_id(ctx.email)

        sent_id = _send_reply(
            ctx.provider,
            to=recipients["to"],
            cc=recipients["cc"],
            subject=subject,
            body=body_with_signature,
            reply_to_id=ctx.raw_id,
            thread_id=thread_id,
        )
        if not sent_id:
            # Audit Cluster C (2026-05-11) B-08: surface the real provider
            # cause (token revoked, quota, MIME invalide…) when available
            # instead of the generic reply_send_failed.
            last_err = getattr(ctx.provider, "_last_error", "") or ""
            error_code = f"reply_send_failed: {last_err}" if last_err else "reply_send_failed"
            return ActionResult(ok=False, error=error_code[:300])
        emit("emit_email_sent", ctx, payload={"is_reply": True, "message_id": sent_id})
        _auto_archive_if_action_label(ctx)
        _reeval_quicksteps_after_reply(ctx)
        return ActionResult(ok=True, artifact={"message_id": sent_id, "to": recipients["to"]})
    except Exception as exc:  # noqa: BLE001
        logger.error("reply_template handler failed: %s", exc)
        return ActionResult(ok=False, error=f"reply_error: {exc}")


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #

def _resolve_snippet(snippet_id: str) -> dict | None:
    try:
        from app.api.snippets import _get_snippet_by_id
        return _get_snippet_by_id(snippet_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("snippet resolve failed for %s: %s", snippet_id, exc)
        return None


def _auto_archive_if_action_label(ctx: ExecutionContext) -> None:
    """Match the standard reply path's auto-archive behaviour.

    Delegates to ``routes_helpers._auto_archive_if_action`` which checks
    both ``auto_archive_action`` (per-account setting) and the email's
    ``Action`` label assignment. We add cache eviction + websocket emit
    around it so the inbox UI updates without a refresh. Errors are
    logged and swallowed — the reply already went out, archive is best
    effort.
    """
    try:
        from app.api.routes_helpers import _auto_archive_if_action as _impl
        _impl(ctx.provider, ctx.raw_id)
        evict_caches(ctx.email_id, ctx.raw_id, folder="archived")
        emit("emit_email_archived", ctx)
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-archive after reply suppressed: %s", exc)


def _reeval_quicksteps_after_reply(ctx: ExecutionContext) -> None:
    """Re-evaluate Quick Step auto-triggers on the original inbox email.

    Lets users build rules like ``thread_has_user_reply=true → archive``
    that fire when the reply lands, without depending on the global
    ``auto_archive_action`` setting + ``Action`` label gate. Best-effort:
    the reply has already been sent, so any failure here only loses the
    auto-trigger side effects — never the reply itself. The audit-log
    dedup inside run_auto_triggers prevents the same (step, email) pair
    from firing more than once across arrival / mark-read / reply-sent.
    """
    try:
        from app.quicksteps.auto_trigger import run_auto_triggers_async
        run_auto_triggers_async(ctx.account_id, ctx.email_id, ctx.email)
    except Exception as exc:  # noqa: BLE001
        logger.debug("post-reply qs re-eval suppressed: %s", exc)


def _append_quoted_original(reply_body: str, email: Any) -> str:
    sender_name = getattr(email, "sender_name", "") or getattr(email, "sender", "") or ""
    sender_email = getattr(email, "sender", "") or ""
    when = getattr(email, "date", None)
    when_str = when.isoformat() if when else ""
    quoted_html = (getattr(email, "body_html", "") or "").strip()
    if not quoted_html:
        # Audit B-01: StandardEmail uses .body for plain text (not body_text).
        # Fall back to both for robustness against ORM Email rows that pre-date
        # the rename. Without this, plain-text replies shipped an empty quoted
        # block.
        plain = (
            getattr(email, "body", "")
            or getattr(email, "body_text", "")
            or ""
        ).strip()
        quoted_html = (
            html.escape(plain).replace("\n", "<br>") if plain else ""
        )

    # Audit B-09: sender_name / sender_email / date are attacker-controlled
    # (inbound email metadata). Escape before injecting into is_html=True MIME.
    safe_sender_name = html.escape(sender_name)
    safe_sender_email = html.escape(sender_email)
    safe_when = html.escape(when_str)
    header_bits: list[str] = []
    if safe_when:
        header_bits.append(f"Le {safe_when}")
    if safe_sender_name or safe_sender_email:
        header_bits.append(f"{safe_sender_name} &lt;{safe_sender_email}&gt;")
    header = ", ".join(header_bits) + " a écrit :" if header_bits else "Message original :"

    return (
        f"{reply_body}"
        f"<br><br>"
        f'<blockquote style="border-left:2px solid #ccc;padding-left:8px;color:#666">'
        f'<div>{header}</div>{quoted_html}'
        f'</blockquote>'
    )


def _build_reply_recipients(ctx: ExecutionContext, *, reply_all: bool) -> dict[str, list[str]]:
    sender = (getattr(ctx.email, "sender", "") or "").strip()
    if not sender:
        return {"to": [], "cc": []}
    to: list[str] = [sender]
    cc: list[str] = []
    if reply_all:
        own_email = (ctx.account_email or "").lower()
        raw_cc = (getattr(ctx.email, "cc", "") or "")
        raw_to = (getattr(ctx.email, "recipients", "") or "")
        for entry in (raw_to + "," + raw_cc).split(","):
            addr = entry.strip().lower()
            if addr and addr != own_email and addr != sender.lower() and addr not in cc:
                cc.append(addr)
    return {"to": to, "cc": cc}


def _reply_subject(original: str) -> str:
    if original.lower().startswith(("re:", "ré :", "re :")):
        return original
    return f"Re: {original}" if original else "Re:"


def _resolve_thread_id(email: Any) -> str | None:
    raw = getattr(email, "thread_id", None) or getattr(email, "conversation_id", None)
    if raw and len(raw) >= 12 and not str(raw).isdigit():
        return raw
    return None


def _send_reply(
    provider: Any,
    *,
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    reply_to_id: str,
    thread_id: str | None,
) -> str | None:
    """Audit Cluster C (2026-05-11) B-08: when both the direct path and the
    fallback fail, propagate provider._last_error so the calling handler
    can include the real reason ("token revoked" / "quota exceeded" /
    "MIME invalide") in ActionResult instead of the generic
    `reply_send_failed`. The provider stores `_last_error` itself; we only
    need to leave it intact and let the handler read it back."""
    if hasattr(provider, "send_reply_directly"):
        try:
            return provider.send_reply_directly(
                to=to,
                subject=subject,
                body=body,
                reply_to_id=reply_to_id,
                cc=cc or None,
                thread_id=thread_id,
                is_html=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Stash on the provider so the handler can surface the real
            # cause to the user via ActionResult.error.
            try:
                setattr(provider, "_last_error", str(exc))
            except Exception:
                pass
            logger.warning("send_reply_directly failed: %s — falling back", exc)

    # Fallback: 2-step create_draft + send_draft.
    if hasattr(provider, "create_draft") and hasattr(provider, "send_draft"):
        draft_id = provider.create_draft(
            to=to,
            subject=subject,
            body=body,
            cc=cc or None,
            is_html=True,
            reply_to_id=reply_to_id,
        )
        if draft_id and provider.send_draft(draft_id):
            return draft_id
    return None
