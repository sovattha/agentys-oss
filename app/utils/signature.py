# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Email signature utilities.

This module provides functions for managing and appending email signatures
to drafts, replies, and new messages.
"""

import logging
import re
import base64
import mimetypes
from html import escape, unescape
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default account ID (will be replaced with multi-account support)
DEFAULT_ACCOUNT_ID = 1


def extract_signature_zone(text: str) -> str:
    """
    Extract the probable signature zone from an email body.

    Looks for common signature delimiters (-- ___ etc.), then falls back to
    heuristics over the trailing lines.
    """
    lines = text.splitlines()

    DELIMITERS = {'--', '---', '————', '___', '____', '_____'}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in DELIMITERS or (stripped.startswith('___') and len(stripped) >= 3):
            return '\n'.join(lines[i:])

    for i in range(len(lines) - 1, max(len(lines) - 40, 0), -1):
        chunk = '\n'.join(lines[i:])
        if len(chunk.strip()) > 10:
            return chunk

    return '\n'.join(lines[-30:])


def get_account_signature(account_id: int = DEFAULT_ACCOUNT_ID, html: bool = False) -> Optional[str]:
    """
    Get the email signature for an account.

    Args:
        account_id: The account ID to get signature for.
        html: If True, return HTML signature; otherwise return plain text.

    Returns:
        The signature string or None if not set.
    """
    try:
        from app.db.database import get_db_session
        from app.db.models.account import Account

        with get_db_session() as session:
            account = session.query(Account).filter_by(id=account_id).first()
            if account:
                # Account-scoped DB data is authoritative. Falling back to the
                # AccountManager singleton when this account has no signature
                # can inject another mailbox's signature in web multi-account
                # requests.
                return account.get_signature(html=html) or None
    except Exception as e:
        logger.warning(f"Could not fetch signature for account {account_id}: {e}")

    # Fallback: AccountManager (JSON config) — covers case where SQLite save failed
    try:
        from app.multi_accounts import get_account_manager
        manager = get_account_manager()
        acc = manager.get_current_account()
        if acc:
            if html and getattr(acc, 'signature_html', None):
                return acc.signature_html
            if getattr(acc, 'signature', None):
                return acc.signature
    except Exception as e:
        logger.warning(f"AccountManager signature fallback failed for {account_id}: {e}")

    return None


_SIGNATURE_IMAGES_DIR = Path(__file__).parent.parent.parent / 'data' / 'signature_images'


def _inline_signature_images(html: str) -> str:
    """
    Remplace les URLs d'images de signature par leur base64 inline.
    Nécessaire pour l'envoi d'emails (les destinataires ne peuvent pas
    accéder à http://localhost:5050).
    """
    def replace_src(match: re.Match) -> str:
        src = match.group(1)
        if '/api/accounts/signature-images/' in src:
            filename = src.split('/')[-1]
            image_path = _SIGNATURE_IMAGES_DIR / Path(filename).name
            if image_path.exists():
                try:
                    mime = mimetypes.guess_type(str(image_path))[0] or 'image/jpeg'
                    data = base64.b64encode(image_path.read_bytes()).decode()
                    return f'data:{mime};base64,{data}'
                except Exception as e:
                    logger.warning(f"Could not inline signature image {filename}: {e}")
        return src

    return re.sub(r'src="([^"]+)"', lambda m: f'src="{replace_src(m)}"', html)


def get_contact_signature(account_id: int, recipient_email: Optional[str]) -> Optional[str]:
    """Return the explicit per-contact signature override, if any."""
    if not recipient_email:
        return None

    contact_email = recipient_email.strip().lower()
    if not contact_email:
        return None

    try:
        from app.infrastructure.container import get_container
        from app.domain.entities.writing_style import ContactStyleProfile

        profile = get_container().get_writing_style_store().load(account_id)
        if not profile:
            return None
        data = profile.contact_profiles.get(contact_email)
        if not data:
            return None
        contact = ContactStyleProfile.from_dict(data)
        return (contact.preferred_signature or "").strip() or None
    except Exception as e:
        logger.warning(
            "Could not fetch contact signature for account %s recipient %s: %s",
            account_id,
            recipient_email,
            e,
        )
        return None


def append_signature(
    body: str,
    account_id: int = DEFAULT_ACCOUNT_ID,
    is_html: bool = True,
    recipient_email: Optional[str] = None,
) -> str:
    """
    Append the account's email signature to a message body.

    Args:
        body: The email body content.
        account_id: The account ID to get signature from.
        is_html: If True, treat body as HTML and use HTML signature (default True since drafts are HTML MIME).

    Returns:
        The body with signature appended, or original body if no signature.
    """
    contact_signature = get_contact_signature(account_id, recipient_email)
    signature = contact_signature or get_account_signature(account_id, html=is_html)

    if not signature:
        return body

    def _body_text_tail(value: str) -> str:
        text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
        text = re.sub(r'</(?:p|div|li)>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        return unescape(text).replace("\r\n", "\n").replace("\r", "\n").strip()

    # Pour l'envoi email : convertir URLs image → base64 inline. Une signature
    # per-contact est du texte saisi dans le composeur, jamais du HTML riche.
    if is_html and contact_signature:
        signature = "<br>".join(escape(line) for line in signature.splitlines())
    elif is_html:
        signature = _inline_signature_images(signature)

    # Don't add signature if it's already present (avoid duplicates)
    if contact_signature:
        already_present = _body_text_tail(body).endswith(contact_signature)
    elif is_html:
        # Only rely on the CSS class marker — content-based check causes false positives
        # when the email body legitimately mentions the same text as the signature.
        already_present = 'class="agentys-signature"' in body
    else:
        already_present = "\n\n--\n" in body
    if already_present:
        logger.debug("Signature already present in body, skipping")
        return body

    # BUG-N001 fix: strip LLM-generated sign-off lines from the end of the body.
    # The drafter prompt forbids closings, but the LLM occasionally generates them anyway
    # (e.g. "Cordialement,\nAlex"). Without this step, the body ends up with the LLM
    # closing followed by the real system signature — a visible duplicate.
    _CLOSING_PATTERNS = re.compile(
        r'\s*(?:cordialement|bien\s+à\s+vous|salutations?|avec\s+mes\s+salutations?'
        r'|best\s+regards?|kind\s+regards?|regards?|sincerely|cheers|yours\s+truly'
        r'|à\s+bientôt|amicalement|cdlt|bonne\s+journée|bonne\s+soirée'
        r'|merci\s+d.avance|warmly|with\s+appreciation'
        r')[\s,.]?(?:\s*\S+)*\s*$',
        re.IGNORECASE | re.MULTILINE,
    )

    def _strip_html_tags(html: str) -> str:
        return re.sub(r'<[^>]+>', '', html)

    def _strip_llm_closing(text: str) -> str:
        """Remove any trailing LLM-generated closing from plain-text content."""
        cleaned = _CLOSING_PATTERNS.sub('', text)
        return cleaned.rstrip()

    if is_html:
        # For HTML bodies, check the plain-text tail for a closing phrase and strip
        # the last <p>/<div> block that only contains a closing salutation.
        _CLOSING_BLOCK_RE = re.compile(
            r'<(?:p|div)[^>]*>\s*(?:cordialement|bien\s+à\s+vous|salutations?'
            r'|best\s+regards?|kind\s+regards?|regards?|sincerely|cheers|yours\s+truly'
            r'|à\s+bientôt|amicalement|cdlt|bonne\s+journée|bonne\s+soirée'
            r'|merci\s+d.avance|warmly|with\s+appreciation'
            r')[\s,.\S]*?</(?:p|div)>\s*$',
            re.IGNORECASE | re.DOTALL,
        )
        stripped_body = _CLOSING_BLOCK_RE.sub('', body).rstrip()
        if stripped_body != body:
            logger.debug("Stripped LLM-generated HTML closing block before appending signature")
            body = stripped_body
    else:
        stripped_body = _strip_llm_closing(body)
        if stripped_body != body:
            logger.debug("Stripped LLM-generated plain-text closing before appending signature")
            body = stripped_body

    if is_html:
        # Normalize signature line spacing so it survives TipTap's HTML parsing.
        # TipTap (StarterKit) converts <div>/<p> to its own paragraph nodes and
        # strips wrapper divs, so `.agentys-signature p { margin:0 }` never fires.
        # Fix: flatten to one tight <p style="margin:0"> per content line so that
        # TipTap receives <p> elements with inline styles it will preserve as-is.
        has_blocks = bool(re.search(r'<(?:p|div)[^>]*>', signature))
        if has_blocks:
            # Split on closing block tags to isolate each content segment
            segments = re.split(r'</(?:p|div)>', signature)
            # Strip remaining opening block tags, collect non-empty lines
            lines = []
            for seg in segments:
                line = re.sub(r'<(?:p|div)[^>]*>', '', seg)
                if re.sub(r'<[^>]+>', '', line).strip():
                    lines.append(line.strip())
            if lines:
                signature = ''.join(
                    f'<p style="margin:0;line-height:1.4">{line}</p>'
                    for line in lines
                )

        # HTML format: wrap in a styled div for clean separation
        return (
            f'{body}'
            f'<div class="agentys-signature" style="margin-top:16px;">{signature}</div>'
        )
    else:
        # Plain text format
        return f"{body}\n\n--\n{signature}"


def fetch_and_store_signature(provider, account_id=DEFAULT_ACCOUNT_ID, email: Optional[str] = None) -> bool:
    """
    Fetch signature from email provider and store it in the account.

    This should be called when connecting a new account or refreshing
    the signature from provider settings.

    Args:
        provider: The email provider instance (Gmail, Outlook, IMAP).
        account_id: The account ID (int DB pk, or string config id — used as fallback).
        email: Email address to look up the DB account by (preferred over account_id).

    Returns:
        True if signature was successfully fetched and stored.
    """
    try:
        # Check if provider supports get_signature
        if not hasattr(provider, 'get_signature'):
            logger.debug(f"Provider {type(provider).__name__} doesn't support signature fetching")
            return False

        signature_data = provider.get_signature()

        if not signature_data:
            logger.debug("No signature returned from provider")
            return False

        html_signature = signature_data.get("html", "")
        text_signature = signature_data.get("text", "")

        if not html_signature and not text_signature:
            logger.debug("Empty signature returned from provider")
            return False

        # Store in database
        from app.db.database import get_db_session
        from app.db.models.account import Account

        with get_db_session() as session:
            # Prefer email lookup (works with OAuth string account_ids)
            account = None
            if email:
                account = session.query(Account).filter_by(email=email).first()
            if not account:
                account = session.query(Account).filter_by(id=account_id).first()

            if account:
                account.signature_html = html_signature
                account.signature_text = text_signature
                session.commit()
                logger.info(f"Signature stored for account {email or account_id}")
                return True
            else:
                logger.warning(f"Account not found (email={email}, id={account_id})")
                return False

    except Exception as e:
        logger.error(f"Error fetching/storing signature: {e}")
        return False
