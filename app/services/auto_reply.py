"""
Auto-reply service (out-of-office).

Sends a configured out-of-office reply on incoming emails whenever
``auto_reply_enabled`` is on and today falls within the configured
window. Standalone so it can be invoked from BOTH ingestion paths:

- ``daemon.process_email`` (legacy IMAP polling).
- ``sync_service._store_emails`` (Gmail OAuth + Outlook delta sync).

Before this extraction the logic lived on the Daemon class and was only
reachable from the legacy path — Gmail OAuth users never received an
auto-reply (GH#622, audit live 2026-05-11).

State (``_REPLIED_SENDERS``) is a module-level set keyed by
``(account_id, sender_lower)`` so the two pipelines share dedupe and
the daemon doesn't reply twice to the same sender when both paths run
for the same account.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Iterable, Optional, Protocol, Set, Tuple

logger = logging.getLogger(__name__)


# Shared dedupe set. Keyed by (account_id, sender_lower) so the same
# sender can still receive an auto-reply for a different account
# (multi-account user with distinct OOO windows).
_REPLIED_SENDERS: Set[Tuple[Optional[int], str]] = set()
_REPLIED_LOCK = threading.Lock()


class _ProviderLike(Protocol):
    """Minimal surface we need from an email provider adapter."""

    def create_draft(
        self,
        to,
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
    ) -> Optional[str]: ...

    def send_draft(self, draft_id: str) -> bool: ...


def _get_reply_subject(subject: str) -> str:
    """Prefix the subject with ``Re:`` if not already present."""
    if not subject:
        return "Re: (sans sujet)"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def _already_replied(account_id: Optional[int], sender_lower: str) -> bool:
    with _REPLIED_LOCK:
        return (account_id, sender_lower) in _REPLIED_SENDERS


def _remember_reply(account_id: Optional[int], sender_lower: str) -> None:
    with _REPLIED_LOCK:
        _REPLIED_SENDERS.add((account_id, sender_lower))


def reset_replied_senders() -> None:
    """Clear the dedupe set. For test isolation."""
    with _REPLIED_LOCK:
        _REPLIED_SENDERS.clear()


def _extract_addr(raw: str) -> str:
    """Extract bare ``addr@host`` from a ``"Name <addr@host>"`` header."""
    s = (raw or "").strip().lower()
    if "<" in s and ">" in s:
        s = s.split("<", 1)[1].split(">", 1)[0].strip()
    return s


def _sender_names(sender_raw: str) -> Tuple[str, str]:
    """``(full_name, first_name)`` for the person who emailed us.

    ``"Alex Doe" <a@x.com>`` → ``("Alex Doe", "Alex")``.
    ``alex.doe@acme.com``    → ``("Alex Doe", "Alex")`` (humanised local part,
    mirrors the QuickSteps ``_humanise_recipient`` convention).
    """
    raw = (sender_raw or "").strip()
    display = ""
    if "<" in raw and ">" in raw:
        # Display-name part before the angle brackets, minus surrounding quotes.
        display = raw.split("<", 1)[0].strip().strip('"').strip()
    if not display:
        addr = _extract_addr(raw) or raw
        local = addr.split("@", 1)[0]
        parts = [p for p in re.split(r"[._\-+]", local) if p]
        display = " ".join(p[:1].upper() + p[1:].lower() for p in parts)
    full = display.strip()
    first = full.split(" ", 1)[0] if full else ""
    return full, first


# Dynamic-field chips authored in AutoReplyModal: a contenteditable=false span
# tagged with ``data-ar-token``. ``name``/``first_name`` resolve per-recipient
# here; any other token (e.g. ``absence_period``, already formatted on the
# client) is unwrapped to its inner text so the recipient gets clean HTML.
_AR_TOKEN_SPAN_RE = re.compile(
    r'<span\b[^>]*\bdata-ar-token="(?P<token>[^"]+)"[^>]*>(?P<inner>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


def _resolve_message_tokens(html: str, *, full_name: str, first_name: str) -> str:
    """Resolve ``data-ar-token`` chips in the stored auto-reply message."""
    if not html or "data-ar-token=" not in html:
        return html

    def _sub(m: "re.Match[str]") -> str:
        token = (m.group("token") or "").strip().lower()
        if token == "name":
            return full_name
        if token == "first_name":
            return first_name
        # absence_period + anything unknown: drop the wrapper, keep inner text.
        return m.group("inner")

    return _AR_TOKEN_SPAN_RE.sub(_sub, html)


def send_auto_reply_if_needed(
    provider: _ProviderLike,
    account_id: Optional[int],
    email,
    is_auto_reply: bool = False,
    account_email: Optional[str] = None,
    own_account_emails: Optional[Iterable[str]] = None,
) -> bool:
    """Send the configured OOO reply for ``email`` if all checks pass.

    Args:
        provider: Authenticated email provider adapter (Gmail/Outlook/IMAP).
            Must expose ``create_draft`` + ``send_draft``.
        account_id: DB account_id used to scope per-account settings and
            the dedupe set. May be ``None`` for legacy paths that never
            wired an account id; in that case dedupe is process-global.
        email: ``StandardEmail`` for the incoming message.
        is_auto_reply: True if the incoming email is itself an auto-reply
            (set by ``email_cleaner.detect_auto_reply``). When True we
            refuse to send to avoid auto-reply loops.
        account_email: The account's own address. When provided we skip
            self-sends (sender == account) — otherwise a user testing the
            feature by emailing themselves would auto-reply to themselves,
            which is pure noise.
        own_account_emails: All of the user's connected account addresses
            (this account + any others linked in the same Agentys install).
            When provided, the sender is matched against the full set —
            preventing the cross-account loop where Gmail auto-replies to
            Hotmail's inbox and Hotmail then auto-replies back to Gmail
            (both belonging to the same user). Supersedes ``account_email``
            for the skip decision when both are set.

    Returns:
        True if an auto-reply was actually dispatched, False otherwise
        (disabled, out of window, sender filtered, already replied, error).
    """
    try:
        from app.api.settings import load_settings

        settings = load_settings(account_id=account_id)

        if not settings.get("auto_reply_enabled", False):
            return False

        message = (settings.get("auto_reply_message") or "").strip()
        if not message:
            return False

        start_date = settings.get("auto_reply_start", "")
        end_date = settings.get("auto_reply_end", "")
        if not start_date or not end_date:
            return False

        today = datetime.now().strftime("%Y-%m-%d")
        if today < start_date or today > end_date:
            return False

        if is_auto_reply:
            logger.debug("  [SKIP] Auto-reply: skip (email entrant est un auto-reply)")
            return False

        sender_raw = getattr(email, "sender", "") or ""
        sender = sender_raw.lower().strip()
        if not sender:
            return False

        # Dedupe on the bare addr@host, never the full envelope: the same
        # sender oscillating between "addr@host" and "Name <addr@host>"
        # forms (mail clients add/drop the display name freely) must not
        # bypass the once-per-window dedupe and trigger a second OOO send.
        sender_addr = _extract_addr(sender_raw) or sender

        # Skip sends from any of the user's own connected accounts —
        # replying to yourself (or to your other linked inboxes) is pure
        # noise and produces cross-account loops (Gmail → Hotmail → Gmail).
        # Compare the bare addr part so a display-name form like
        # "Alex <me@x>" still matches "me@x".
        own_addrs: Set[str] = set()
        if own_account_emails:
            own_addrs = {a.strip().lower() for a in own_account_emails if a}
        elif account_email:
            own_addrs = {account_email.strip().lower()}
        if own_addrs:
            if sender_addr and sender_addr in own_addrs:
                logger.debug(
                    f"  [SKIP] Auto-reply: sender is user's own account ({sender_addr})"
                )
                return False

        # Skip auto-generated senders (noreply@, notifications@, etc.).
        try:
            from app.smart_routing import _SKIP_SENDER_PATTERNS

            if _SKIP_SENDER_PATTERNS.search(sender):
                logger.debug(
                    f"  [SKIP] Auto-reply: skip sender automatique ({sender[:40]})"
                )
                return False
        except ImportError:
            pass

        if _already_replied(account_id, sender_addr):
            logger.debug(f"  [SKIP] Auto-reply: déjà envoyé à {sender_addr}")
            return False

        subject = _get_reply_subject(getattr(email, "subject", "") or "")

        # Resolve per-recipient placeholders ({{name}}/{{first_name}} chips
        # authored in AutoReplyModal) now that we know who the sender is. The
        # absence-period chip is already formatted client-side; it's just
        # unwrapped to plain text here.
        full_name, first_name = _sender_names(sender_raw)
        message = _resolve_message_tokens(
            message, full_name=full_name, first_name=first_name
        )

        # Append the account's signature so the recipient sees the same
        # closing as on every other email the user sends. The frontend
        # (AutoReplyModal) renders a non-editable signature footer below
        # the message editor — appending it here makes that promise true.
        # Best-effort: any failure falls back to the bare message rather
        # than blocking the auto-reply send.
        body_with_signature = message
        try:
            from app.utils.signature import append_signature
            body_with_signature = append_signature(message, account_id=account_id)
        except Exception as _sig_exc:  # noqa: BLE001
            logger.debug(f"auto-reply signature append suppressed: {_sig_exc}")

        draft_id = provider.create_draft(
            to=[sender_raw],
            subject=subject,
            body=body_with_signature,
            reply_to_id=getattr(email, "id", None),
        )

        if not draft_id:
            logger.warning(f"  [WARN] Auto-reply: échec création draft pour {sender}")
            return False

        if not provider.send_draft(draft_id):
            logger.warning(f"  [WARN] Auto-reply: échec envoi du draft à {sender}")
            return False

        _remember_reply(account_id, sender_addr)
        logger.info(f"  Auto-reply envoyé à {sender_addr}")
        return True

    except Exception as e:
        logger.warning(f"  [WARN] Erreur auto-reply: {e}")
        return False
