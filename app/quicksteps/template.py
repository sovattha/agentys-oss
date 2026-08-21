# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Deterministic template variable interpolation for Quick Step bodies.

ONE renderer for every Quick Step body (``reply_template``, ``forward`` and
``create_snoozed_followup_draft``). Historically the follow-up handler shipped
its own ``{{double-brace}}`` renderer with a different vocabulary, so a body
authored with the reply syntax (``{sender.firstname}``) silently produced
literal text in a follow-up — and vice-versa. This module removes that footgun:

- **Both syntaxes resolve** — ``{token}`` and ``{{token}}`` are equivalent.
- **One vocabulary** (canonical keys), with legacy aliases mapped on lookup:

    {sender.firstname} {sender.lastname} {sender.name} {sender.email}
    {recipient.firstname} {recipient.lastname} {recipient.name} {recipient.email}
    {me.firstname} {me.name} {me.email}
    {subject}   {date}

  Legacy aliases (the old follow-up names): ``recipient_name``,
  ``recipient_first_name``, ``recipient_last_name`` → ``recipient.*`` ;
  ``original_subject`` → ``subject``.

- ``recipient.*`` is the explicit recipient on the sent-side follow-up; on the
  inbound reply/forward path (no explicit recipient) it falls back to the
  sender, i.e. the person you are replying to.

Unknown placeholders follow the ``on_unknown`` policy:
- ``"blank"`` (default — reply/forward): render empty + debug log. Pairs with
  ``collect_unknown_variables`` to surface typos before hitting the mail API.
- ``"literal"`` (follow-up): leave the original ``{token}`` untouched, so a
  pasted ``{shipping_id}`` survives instead of being blanked.

``render_html`` HTML-escapes substituted values so user input never breaks the
surrounding markup (XSS guard); ``render_plain`` does not escape.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape
from typing import Callable

logger = logging.getLogger(__name__)

# Matches ``{{ token }}`` first (so it is consumed whole) then ``{ token }``.
# Token: a dotted/underscored identifier — sender.firstname, recipient_name…
_PLACEHOLDER_PATTERN = re.compile(
    r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}"   # {{ token }}
    r"|\{\s*([a-zA-Z_][\w.]*)\s*\}"      # { token }
)

# Legacy placeholder names → canonical context key. Applied on lookup so a body
# authored with either spelling resolves to the same value.
_ALIASES: dict[str, str] = {
    "recipient_name": "recipient.name",
    "recipient_first_name": "recipient.firstname",
    "recipient_last_name": "recipient.lastname",
    "recipient_email": "recipient.email",
    "original_subject": "subject",
}

# `{x}` placeholder chips authored in the editors: a span carrying the token in
# ``data-ar-token``. Convert them back to ``{token}`` so the substitution below
# resolves them exactly like plain-text tokens (works for both syntaxes since
# the resulting single-brace token matches the pattern above).
_CHIP_SPAN_PATTERN = re.compile(
    r'<span\b[^>]*\bdata-ar-token="([^"]+)"[^>]*>.*?</span>',
    re.IGNORECASE | re.DOTALL,
)


def _chips_to_tokens(template: str) -> str:
    if not template or "data-ar-token=" not in template:
        return template
    return _CHIP_SPAN_PATTERN.sub(lambda m: "{" + m.group(1) + "}", template)


def _local_part(email: str) -> str:
    return email.split("@", 1)[0] if "@" in email else email


def _split_first_last(name: str) -> tuple[str, str]:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "", ""
    return parts[0], (parts[-1] if len(parts) > 1 else "")


def _humanise_recipient(addr: str) -> str:
    """``alex.doe@acme.com`` → ``Alex Doe`` ; ``support@stripe.com`` → ``Support``.

    Derives a display name from a bare email address by title-casing the
    local-part tokens (split on ``. _ - +``). Mirrors ``formatRecipientDisplay``
    in ``SnoozedView.tsx`` so the interpolation matches what the user sees in
    the Later view. Used for ``recipient.*`` when only an address is known.
    """
    if not addr:
        return ""
    local = addr.split("@")[0].strip()
    if not local:
        return addr
    parts = [p for p in re.split(r"[._\-+]", local) if p]
    return " ".join(p[:1].upper() + p[1:].lower() for p in parts) or local


def _format_date(now: datetime, locale: str) -> str:
    if locale.lower().startswith("fr"):
        months = [
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        ]
        return f"{now.day} {months[now.month - 1]} {now.year}"
    return now.strftime("%B %d, %Y")


def build_context(
    *,
    sender_email: str = "",
    sender_name: str = "",
    subject: str = "",
    me_email: str = "",
    me_display_name: str = "",
    recipient_email: str = "",
    recipient_name: str = "",
    locale: str = "fr",
    now: datetime | None = None,
) -> dict[str, str]:
    """Assemble the variable map a template can pull from.

    All values are strings (never None) so the renderer never has to guard.

    ``recipient_*`` is the explicit conversation partner on the sent-side
    follow-up. When omitted (the reply/forward path), ``recipient.*`` falls
    back to the sender — the person you are replying to — so a body that
    references the recipient still resolves sensibly.
    """
    sender_email = (sender_email or "").strip()
    sender_name = (sender_name or "").strip()
    me_email = (me_email or "").strip()
    me_display_name = (me_display_name or "").strip()
    recipient_email = (recipient_email or "").strip()
    recipient_name = (recipient_name or "").strip()

    sender_first, sender_last = _split_first_last(sender_name or _local_part(sender_email))
    me_first, _me_last = _split_first_last(me_display_name or _local_part(me_email))

    # Recipient resolution: explicit name > humanised explicit address >
    # fall back to the sender (inbound reply: the recipient is the sender).
    r_email = recipient_email or sender_email
    if recipient_name:
        r_name = recipient_name
    elif recipient_email:
        r_name = _humanise_recipient(recipient_email)
    else:
        r_name = sender_name or _local_part(sender_email)
    r_first, r_last = _split_first_last(r_name)

    return {
        "sender.firstname": sender_first,
        "sender.lastname": sender_last,
        "sender.name": sender_name or sender_email,
        "sender.email": sender_email,
        "recipient.firstname": r_first,
        "recipient.lastname": r_last,
        "recipient.name": r_name,
        "recipient.email": r_email,
        "subject": subject or "",
        "date": _format_date(now or datetime.now(), locale),
        "me.firstname": me_first,
        "me.name": me_display_name or me_email,
        "me.email": me_email,
    }


def _resolve_key(raw_key: str) -> str:
    """Map a legacy placeholder name onto its canonical context key."""
    return _ALIASES.get(raw_key, raw_key)


def _render(
    template: str,
    ctx: dict[str, str],
    transform: Callable[[str], str],
    *,
    on_unknown: str = "blank",
) -> str:
    if not template:
        return ""

    template = _chips_to_tokens(template)

    def replace(match: re.Match[str]) -> str:
        raw_key = match.group(1) if match.group(1) is not None else match.group(2)
        key = _resolve_key(raw_key)
        if key in ctx:
            return transform(ctx[key])
        if on_unknown == "literal":
            # Leave the original token (braces included) untouched — protects
            # pasted content like {shipping_id} from being silently blanked.
            return match.group(0)
        logger.debug("Quick Step template references unknown variable: %s", raw_key)
        return ""

    return _PLACEHOLDER_PATTERN.sub(replace, template)


def render_plain(template: str, ctx: dict[str, str], *, on_unknown: str = "blank") -> str:
    """Render a plain-text template (e.g. forward.subject_prefix, follow-up body).

    No HTML escaping. ``on_unknown`` controls unknown-placeholder handling
    ("blank" → empty, "literal" → leave the token intact).
    """
    return _render(template, ctx, transform=lambda v: v, on_unknown=on_unknown)


def render_html(template: str, ctx: dict[str, str], *, on_unknown: str = "blank") -> str:
    """Render an HTML template (reply_template.body, forward.body).

    Variable values are HTML-escaped so a sender called ``Bob & <script>``
    cannot break the surrounding markup.
    """
    return _render(template, ctx, transform=escape, on_unknown=on_unknown)


def collect_unknown_variables(template: str, ctx: dict[str, str]) -> list[str]:
    """Return the placeholders the template uses that the context does not know.

    Aliases are resolved before the membership check, so ``{{recipient_name}}``
    is not flagged when ``recipient.name`` is present. Used by the validation
    step before sending — surfaces template typos (``{sendr.firstname}``)
    before we hit the mail API.
    """
    if not template:
        return []
    template = _chips_to_tokens(template)
    found: set[str] = set()
    for match in _PLACEHOLDER_PATTERN.finditer(template):
        raw_key = match.group(1) if match.group(1) is not None else match.group(2)
        if _resolve_key(raw_key) not in ctx:
            found.add(raw_key)
    return sorted(found)


__all__ = [
    "build_context",
    "render_plain",
    "render_html",
    "collect_unknown_variables",
    "_humanise_recipient",
]
