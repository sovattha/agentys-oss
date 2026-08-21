# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Email indexer for the onboarding pipeline.

Sorts, groups, and analyses emails to prepare structured data
for the analysis agents (ProfileAgent, KnowledgeAgent, StyleAgent, LabelAgent).
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.onboarding.loader import OnboardingEmail
from app.onboarding.schemas import EmailDirection, Language

# Common word markers used to infer the dominant language of a corpus.
# Kept small and high-signal on purpose: we want fast, accent-insensitive
# heuristics that cover the bulk of real business correspondence.
_FR_MARKERS: frozenset[str] = frozenset({
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou",
    "au", "aux", "je", "tu", "il", "elle", "nous", "vous", "ils",
    "est", "sont", "pour", "avec", "que", "qui", "dans", "sur", "pas",
    "plus", "mais", "votre", "notre", "bonjour", "merci", "cordialement",
    "salut", "suis", "avons", "avez", "serait", "fait",
})
_EN_MARKERS: frozenset[str] = frozenset({
    "the", "an", "to", "of", "and", "or", "is", "are", "was", "were",
    "you", "he", "she", "we", "they", "for", "with", "that", "this",
    "in", "on", "at", "but", "not", "have", "has", "had", "will",
    "would", "hello", "hi", "thanks", "regards", "dear", "your", "our",
    "please", "kind", "best", "cheers",
})

# OB-03 (audit 2026-04-24): markers for "third-party" languages so the
# detector can recognize a dominant non-FR/non-EN inbox and flag the run
# instead of silently picking FR. We only need *enough* signal to beat the
# FR/EN counts — we do NOT plan to load Spanish/Italian/PT prompts here.
_ES_MARKERS: frozenset[str] = frozenset({
    "el", "los", "las", "una", "unos", "unas", "y", "es", "son",
    "para", "con", "por", "que", "como", "pero", "muy", "este", "esta",
    "hola", "gracias", "saludos", "estimado", "buenos", "soy",
})
_PT_MARKERS: frozenset[str] = frozenset({
    "o", "a", "os", "as", "um", "uma", "e", "ou", "que", "para",
    "com", "por", "está", "estão", "são", "olá", "obrigado", "obrigada",
    "atenciosamente", "saudações", "prezado", "caro", "cara",
})
_IT_MARKERS: frozenset[str] = frozenset({
    "il", "lo", "gli", "una", "uno", "e", "o", "di", "che", "per",
    "con", "su", "ma", "non", "ciao", "grazie", "cordiali", "saluti",
    "buongiorno", "buonasera", "egregio", "gentile",
})

_TOKEN_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)
# Broader unicode regex for the multi-language detector (also catches
# Spanish/Portuguese accented chars and umlauts in residual foreign text).
_UNICODE_TOKEN_RE = re.compile(r"[a-zà-ÿäöüßñ]+", re.IGNORECASE | re.UNICODE)

logger = logging.getLogger(__name__)

# Local-part substrings that mark an address as automated/noise rather than
# a real human contact. Matched case-insensitive against the part before '@'.
_NOISE_LOCAL_PART_SUBSTRINGS: tuple[str, ...] = (
    "noreply", "no-reply", "no_reply", "do-not-reply", "donotreply",
    "mailer-daemon", "postmaster", "newsletter", "news-letter",
    "notifications", "notification", "notify",
    "unsubscribe", "bounce", "bounces",
    "auto-confirm", "automated", "autoreply", "auto-reply",
    "mailinglist", "mailing-list", "mail-list",
    "alert", "alerts", "updates", "digest",
    "invoice", "billing-noreply", "receipts",
)

# Full domains that are almost always noise (transactional, tracking…).
_NOISE_DOMAINS: frozenset[str] = frozenset({
    "notifications.google.com",
    "accounts.google.com",
    "mail-noreply.google.com",
    "noreply.github.com",
    "noreply.linkedin.com",
    "notifications.slack.com",
    "updates.slack.com",
    "em.linkedin.com",
    "bounce.linkedin.com",
})


def _is_noise_sender(email_addr: str) -> bool:
    """Return True if an email address looks like an automated/bulk sender.

    We keep the heuristic intentionally simple: it runs on thousands of
    emails during indexing and false negatives are acceptable (the LLM can
    still cope with a bit of noise), while false positives on real humans
    would be actively harmful.
    """
    if not email_addr or "@" not in email_addr:
        return False
    local, _, domain = email_addr.lower().partition("@")
    if domain in _NOISE_DOMAINS:
        return True
    return any(substr in local for substr in _NOISE_LOCAL_PART_SUBSTRINGS)


def _contact_rank_key(m: "ContactMetrics") -> tuple:
    """Ordering key for top contacts.

    Priorities (highest first):
    1. Bidirectional conversation (user has BOTH sent and received). This is
       the strongest signal of a real, active relationship.
    2. Raw total interaction count.
    3. Sent count alone (as tiebreaker — writing TO someone is a stronger
       authorship signal than passively receiving from them).
    """
    is_bidirectional = 1 if (m.sent_count > 0 and m.received_count > 0) else 0
    return (is_bidirectional, m.total_count, m.sent_count)


@dataclass
class ContactMetrics:
    """Aggregated metrics for a single contact."""
    email: str
    name: Optional[str] = None
    sent_count: int = 0
    received_count: int = 0
    total_count: int = 0
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    threads: List[str] = field(default_factory=list)
    subjects: List[str] = field(default_factory=list)


@dataclass
class ThreadGroup:
    """A group of emails sharing the same thread_id."""
    thread_id: str
    subject: str
    emails: List[OnboardingEmail] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    date_range: Optional[tuple] = None


@dataclass
class IndexedEmails:
    """
    The fully indexed email corpus, ready for analysis agents.
    """
    # Core data
    all_emails: List[OnboardingEmail]
    sent_emails: List[OnboardingEmail]
    received_emails: List[OnboardingEmail]

    # Grouped views
    by_contact: Dict[str, List[OnboardingEmail]]
    by_thread: Dict[str, ThreadGroup]

    # Aggregated metrics
    contact_metrics: Dict[str, ContactMetrics]

    # Metadata
    user_email: str
    total_count: int
    sent_count: int
    received_count: int
    date_range: Optional[tuple] = None
    top_contacts: List[str] = field(default_factory=list)
    # OB-C-2 (audit 2026-04-25 onboarding-flawless): account_id is needed
    # by agents that read per-account stores during analysis (LabelAgent
    # reads existing labels via container.get_label_store(account_id=…)).
    # Optional[int] with default 0 keeps the dataclass backward-compatible
    # for callers that don't yet pass it.
    account_id: int = 0

    @property
    def primary_language(self) -> Language:
        """Dominant language of the user's writing.

        Aggregates word markers across the sent corpus (the user's own
        output is the authoritative signal — inbox contents may be in
        any language and would bias the result). Falls back to FR when
        there is too little text to decide.

        OB-03 (audit 2026-04-24): when a non-FR/non-EN language clearly
        dominates the corpus (Spanish, Portuguese, Italian) we
        return ``Language.UNSUPPORTED`` so the orchestrator can flag the
        run as partial instead of silently feeding a French prompt to a
        Spanish-only mailbox. The threshold is conservative — a tiny
        Spanish minority in a French inbox still resolves to FR.
        """
        combined = "\n".join(e.body for e in self.sent_emails if e.body)
        if len(combined) < 100:
            return Language.FR
        tokens = _UNICODE_TOKEN_RE.findall(combined.lower())
        if not tokens:
            return Language.FR
        fr = sum(1 for t in tokens if t in _FR_MARKERS)
        en = sum(1 for t in tokens if t in _EN_MARKERS)
        es = sum(1 for t in tokens if t in _ES_MARKERS)
        pt = sum(1 for t in tokens if t in _PT_MARKERS)
        it = sum(1 for t in tokens if t in _IT_MARKERS)

        # Pick the strongest non-FR/EN signal. We only flag UNSUPPORTED if
        # it (a) has a meaningful absolute count (>=10 marker hits) so
        # isolated borrowings don't trigger, and (b) outranks both FR and
        # EN (one comparison via max so a 0/0 FR/EN corpus with 9 IT
        # markers also routes here once the threshold is met — H-9 fix
        # 2026-04-25 collapsed the previous double-compare which left
        # Italian-only corpora silently falling back to FR).
        third_party = max(es, pt, it)
        if third_party >= 10 and third_party > max(fr, en):
            return Language.UNSUPPORTED

        if fr == 0 and en == 0:
            return Language.FR
        return Language.EN if en > fr else Language.FR


class EmailIndexer:
    """
    Indexes a list of OnboardingEmails into structured views.
    """

    def __init__(self, user_email: str, account_id: int = 0):
        self.user_email = user_email.lower()
        # OB-C-2 (audit 2026-04-25): account_id is propagated to the
        # IndexedEmails dataclass so agents (esp. LabelAgent) can scope
        # their per-account store reads. Default 0 keeps existing
        # callers working — they get an unscoped read which is a no-op
        # (no leak) on a single-account install but flagged in tests.
        self.account_id = int(account_id) if account_id else 0

    def index(self, emails: List[OnboardingEmail]) -> IndexedEmails:
        """
        Index all emails and produce structured data.

        Args:
            emails: List of OnboardingEmail to index.

        Returns:
            IndexedEmails with sorted, grouped, and aggregated data.
        """
        # Sort by date — defensive: although OnboardingEmail.date is typed
        # `datetime` (loader.py:39), some legacy IMAP rows have surfaced
        # with a None date in the past (corrupted Exchange Date headers).
        # `sorted()` with a key returning None vs datetime raises TypeError
        # and aborts the whole onboarding pipeline. Using a sentinel
        # epoch keeps dateless rows at the front and lets the indexer
        # finish.
        from datetime import datetime as _dt, timezone as _tz
        _epoch = _dt(1970, 1, 1, tzinfo=_tz.utc)
        sorted_emails = sorted(emails, key=lambda e: getattr(e, "date", None) or _epoch)

        sent = [e for e in sorted_emails if e.direction == EmailDirection.SENT]
        received = [e for e in sorted_emails if e.direction == EmailDirection.RECEIVED]

        by_contact = self._group_by_contact(sorted_emails)
        by_thread = self._group_by_thread(sorted_emails)
        contact_metrics = self._compute_contact_metrics(sorted_emails)

        # Rank contacts: bidirectional conversations (both sent AND received)
        # are far stronger signal than one-way flows, so they get a boost.
        top = sorted(
            contact_metrics.values(),
            key=_contact_rank_key,
            reverse=True,
        )
        top_contacts = [m.email for m in top[:20]]

        # Date range
        date_range = None
        if sorted_emails:
            date_range = (sorted_emails[0].date, sorted_emails[-1].date)

        result = IndexedEmails(
            all_emails=sorted_emails,
            sent_emails=sent,
            received_emails=received,
            by_contact=by_contact,
            by_thread=by_thread,
            contact_metrics=contact_metrics,
            user_email=self.user_email,
            total_count=len(sorted_emails),
            sent_count=len(sent),
            received_count=len(received),
            date_range=date_range,
            top_contacts=top_contacts,
            account_id=self.account_id,
        )

        logger.info(
            "Indexed %d emails: %d sent, %d received, %d contacts, %d threads",
            result.total_count, result.sent_count, result.received_count,
            len(contact_metrics), len(by_thread),
        )
        return result

    def _group_by_contact(
        self, emails: List[OnboardingEmail]
    ) -> Dict[str, List[OnboardingEmail]]:
        """Group emails by contact email (excluding the user).

        Both sent and received emails are considered so that users who mainly
        receive (and reply occasionally) still get a populated contact list.
        Automated senders (noreply, newsletters, bounces…) are filtered out.
        """
        groups: Dict[str, List[OnboardingEmail]] = defaultdict(list)

        for email in emails:
            contacts = self._extract_contacts(email)
            for contact in contacts:
                if _is_noise_sender(contact):
                    continue
                groups[contact].append(email)

        return dict(groups)

    def _group_by_thread(
        self, emails: List[OnboardingEmail]
    ) -> Dict[str, ThreadGroup]:
        """Group emails by thread_id."""
        groups: Dict[str, ThreadGroup] = {}

        for email in emails:
            tid = email.thread_id
            if not tid:
                continue

            if tid not in groups:
                groups[tid] = ThreadGroup(
                    thread_id=tid,
                    subject=email.subject,
                )

            group = groups[tid]
            group.emails.append(email)

        # Finalise each group
        for group in groups.values():
            group.emails.sort(key=lambda e: e.date)
            participants = set()
            for e in group.emails:
                participants.add(e.sender_email.lower())
                participants.update(r.lower() for r in e.recipients)
            group.participants = sorted(participants)
            if group.emails:
                group.date_range = (group.emails[0].date, group.emails[-1].date)

        return groups

    def _compute_contact_metrics(
        self, emails: List[OnboardingEmail]
    ) -> Dict[str, ContactMetrics]:
        """Compute interaction metrics per contact.

        Both sent and received emails are counted so that contacts who
        mostly write TO the user still surface. Automated senders (noreply,
        newsletters, bounces…) are filtered via _is_noise_sender. The
        ``sent_count`` / ``received_count`` split is preserved so downstream
        ranking can favour bidirectional conversations.
        """
        metrics: Dict[str, ContactMetrics] = {}

        for email in emails:
            contacts = self._extract_contacts(email)
            is_sent = email.direction == EmailDirection.SENT

            for contact in contacts:
                if _is_noise_sender(contact):
                    continue

                if contact not in metrics:
                    metrics[contact] = ContactMetrics(email=contact)

                m = metrics[contact]
                m.total_count += 1
                if is_sent:
                    m.sent_count += 1
                else:
                    m.received_count += 1

                if email.thread_id and email.thread_id not in m.threads:
                    m.threads.append(email.thread_id)

                if email.subject and email.subject not in m.subjects:
                    m.subjects.append(email.subject)

                if m.first_interaction is None or email.date < m.first_interaction:
                    m.first_interaction = email.date
                if m.last_interaction is None or email.date > m.last_interaction:
                    m.last_interaction = email.date

        # Capture names from received emails (sender_name when contact sent us an email)
        for email in emails:
            if email.direction == EmailDirection.RECEIVED:
                sender = email.sender_email.lower()
                if sender in metrics and not metrics[sender].name and email.sender_name:
                    metrics[sender].name = email.sender_name

        return metrics

    def _extract_contacts(self, email: OnboardingEmail) -> List[str]:
        """Extract non-user contact emails from an email."""
        contacts = set()

        sender = email.sender_email.lower()
        if sender != self.user_email:
            contacts.add(sender)

        for r in email.recipients:
            r_lower = r.lower()
            if r_lower != self.user_email:
                contacts.add(r_lower)

        for c in email.cc:
            c_lower = c.lower()
            if c_lower != self.user_email:
                contacts.add(c_lower)

        return list(contacts)
