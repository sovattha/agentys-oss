# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Auto-trigger executor for Quick Steps.

Called from daemon.process_email once per new email — finds all Quick Steps
with autoEnabled=True whose conditions match the incoming email and executes
them via the normal engine path.

Condition shape (v2): ``{type, match_mode?, value, negate?}``. Legacy v1
conditions — where the ``type`` itself encoded the operator
(``sender_regex``, ``subject_keyword``, ``is_calendar_invite`` …) — are
upgraded by ``schema.migrate_legacy_condition`` at the top of
``_match_condition``, so the matcher only ever deals with the 15-type v2
vocabulary.

Condition types (mirror schema._TRIGGER_CONDITION_TYPES):
  sender          — match_mode is/contains/matches against the sender address
  sender_domain   — same, against the domain after '@'
  recipient       — same, against the recipients string; match_mode "is"
                    compares against each parsed To/Cc address
  email_text      — match_mode anywhere/subject/body — case-insensitive
                    substring search in the chosen part of the email
  has_label       — email carries the named label (case-insensitive)
  has_attachment  — value "true"/"false" — match emails with/without attachments
  is_read         — value "true"/"false" — match read/unread emails
                    (reads Email.is_read; negate flips to the opposite)
  has_deadline_detected — value "true"/"false" — the ingest pipeline stamped
                    `emails.deadline_at`
  has_emoji_marker — value "true"/"false" — a mark_with_emoji action already
                    stamped this email
  calendar_invite — match_mode "any": detects meeting invitations via .ics
                    attachment, subject patterns, or meeting link in body.
                    match_mode "free": additionally requires the user to be
                    free at the proposed [DTSTART, DTEND] window (reads the
                    invite time, not now). Fails closed when the calendar
                    provider is unreachable or the invite time can't be
                    extracted.
  email_older_than_days — value=N — email's received date is older than N days
  no_reply_after_days   — value=N — the thread's most recent sent email is older
                    than N days with no inbound reply after it (SQL table emails)
  previously_auto_actioned_by — value=<step UUID> — true iff the named step has
                    already auto-fired successfully on any email in the current
                    thread (joins quick_step_audit_log by email_id →
                    Email.thread_id). Unlocks reactive chains across messages.
  is_new_thread    — value "true"/"false" — the user started the thread
  thread_has_user_reply — value "true"/"false" — the user sent ≥1 message in
                    this thread AFTER the evaluated email's date (a real
                    reply to it). Earlier sends — e.g. the user initiated
                    the thread — do not count; unknown date fails closed
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.quicksteps.schema import migrate_legacy_condition
from app.utils.dates import to_naive_utc

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 50) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum or value > maximum:
        return default
    return value


# How many Quick Steps the daemon may fire on a single email. Hard cap
# protects against a misconfigured rule set firing N reply_template
# actions in a tight loop. Env-overridable; max 50 to keep daemon
# throughput bounded.
_MAX_AUTO_TRIGGERS_PER_EMAIL = _env_int("AGENTYS_QS_MAX_AUTO_TRIGGERS_PER_EMAIL", 5)


@dataclass(frozen=True)
class _EmailSnapshot:
    """Immutable copy of the email fields the trigger matcher reads.

    Auto-triggers fire up to _MAX_AUTO_TRIGGERS_PER_EMAIL chained steps in
    sequence. Each step can mutate the email (archive moves it out of
    INBOX, label changes, etc.). Without snapshotting, step N+1 sees the
    side effects of step N — a step gated on ``has_label: INBOX`` would
    silently mis-match after a prior step archived. Freezing the fields at
    function entry guarantees every step matches against the email as
    delivered.
    """
    sender: str
    subject: str
    body: str
    body_html: str
    recipients: str
    attachments_meta: str
    id: str
    labels: frozenset
    thread_id: str
    date: datetime | None
    is_read: bool
    deadline_at: datetime | None
    emoji_marker_json: str

    @classmethod
    def of(cls, email, *, account_id: int = 0) -> "_EmailSnapshot":
        # Normalise across the two email shapes this helper receives:
        #  - provider StandardEmail / DomainEmail: ``.id`` is the provider
        #    message id and ``.body`` carries the text.
        #  - SQLAlchemy Email row: ``.id`` is the int PK (useless as a
        #    message id), the provider id lives in ``.email_id`` and the
        #    text in ``.body_text``.
        # The daemon re-eval and the post-reply validate-and-send re-eval
        # both hand us a SQL row; without this remap ``body``/``id`` came
        # back blank and content_keyword / has_label / subject_or_body_keyword
        # matchers silently never fired.
        if hasattr(email, "email_id") and hasattr(email, "body_text"):
            eid = str(getattr(email, "email_id", "") or "")
            body_val = str(getattr(email, "body_text", "") or "")
        else:
            eid = str(getattr(email, "id", "") or "")
            body_val = str(getattr(email, "body", "") or "")
        date_raw = getattr(email, "date", None)
        # Normalise to UTC-aware so timedelta math against datetime.now(UTC)
        # never raises. Provider snapshots sometimes hand back naive datetimes.
        if isinstance(date_raw, datetime) and date_raw.tzinfo is None:
            date_raw = date_raw.replace(tzinfo=timezone.utc)
        deadline_raw = getattr(email, "deadline_at", None)
        emoji_marker_raw = getattr(email, "emoji_marker_json", "") or ""

        # Ingest-time scanners stamp `deadline_at` and `emoji_marker_json` on
        # the SQL Email row, not on the provider's StandardEmail. When this
        # helper is invoked from a code path that handed us the StandardEmail
        # (the daemon classifier loop is the canonical example), those two
        # columns come back blank and rules like `has_deadline_detected=true`
        # silently never match — even though the data is correctly persisted.
        #
        # Fall back to a single indexed SQL lookup keyed on (email_id,
        # account_id) when either column is missing. The lookup is a cheap
        # PK-index hit and only runs when the caller passed a non-SQL row,
        # so the hot path (engine.execute → already a SQL row) is untouched.
        if eid and account_id and (deadline_raw is None or not emoji_marker_raw):
            try:
                from app.db.database import get_db_session
                from app.db.repositories.email_repository import EmailRepository
                with get_db_session() as _ws:
                    _row = EmailRepository(_ws).get_by_email_id(
                        eid, account_id=account_id,
                    )
                    if _row is not None:
                        if deadline_raw is None:
                            deadline_raw = getattr(_row, "deadline_at", None)
                        if not emoji_marker_raw:
                            emoji_marker_raw = getattr(_row, "emoji_marker_json", "") or ""
            except Exception as _exc:  # noqa: BLE001
                logger.debug("_EmailSnapshot SQL backfill suppressed: %s", _exc)

        if isinstance(deadline_raw, datetime) and deadline_raw.tzinfo is None:
            deadline_raw = deadline_raw.replace(tzinfo=timezone.utc)
        return cls(
            sender=str(getattr(email, "sender", "") or ""),
            subject=str(getattr(email, "subject", "") or ""),
            body=body_val,
            body_html=str(getattr(email, "body_html", "") or ""),
            recipients=str(getattr(email, "recipients", "") or ""),
            attachments_meta=str(getattr(email, "attachments_meta", "") or ""),
            id=eid,
            labels=frozenset(_get_email_label_names(eid, account_id)) if eid else frozenset(),
            thread_id=str(getattr(email, "thread_id", "") or ""),
            date=date_raw if isinstance(date_raw, datetime) else None,
            is_read=bool(getattr(email, "is_read", False)),
            deadline_at=deadline_raw if isinstance(deadline_raw, datetime) else None,
            emoji_marker_json=str(emoji_marker_raw or ""),
        )


def _resolve_oauth_account_id(account_id: int) -> str | None:
    """Bridge the int DB account_id to the hex OAuth-storage id.

    Mirrors the resolution in handlers/rsvp.py — the multi_accounts manager
    keys by the hex id minted at OAuth time, not by the DB primary key.
    Returns None when the account has no OAuth tokens (calendar conditions
    silently fail-closed, like every other transient lookup here).
    """
    try:
        from app.db.database import get_db_session
        from app.db.models.account import Account
        with get_db_session() as session:
            row = session.get(Account, account_id)
            email_addr = getattr(row, "email", None) if row else None
        if not email_addr:
            return None
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account_by_email(email_addr)
        return getattr(cfg, "id", None) if cfg else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("oauth account resolve failed for %s: %s", account_id, exc)
        return None


def _get_email_label_names(email_id: str, account_id: int) -> set[str]:
    """Return lowercased label names for the email.

    Layered read with JSON as the authoritative source of truth:
    1. ``email_labels`` SQL table (mirror of the JSON store, faster + can be
       joined). Populated by ``LabelStore.save_assignment`` dual-write.
    2. Fallback to ``assignments.json`` via ``LabelStore.get_assignment`` when
       SQL returns empty. The dual-write can skip when the ``emails`` row is
       not yet persisted (race with sync), or fail silently — JSON always has
       the truth (cf. lessons.md 2026-05-07 incident).

    Returning the JSON labels when SQL is empty was the missing piece that
    caused ``has_label`` triggers to silently miss after mark-as-read,
    despite the UI showing the label correctly (UI reads JSON directly).
    """
    sql_labels: set[str] = set()
    try:
        from app.db.database import get_db_session
        from app.db.models.email_label_record import EmailLabelRecord
        with get_db_session() as session:
            q = session.query(EmailLabelRecord).filter_by(email_id=email_id)
            if account_id:
                q = q.filter_by(account_id=account_id)
            sql_labels = {row.label_name.strip().lower() for row in q.all() if row.label_name}
    except Exception as exc:  # noqa: BLE001
        # Audit B-07 (2026-05-12): elevated to .warning. has_label is the
        # primary condition operator for label-gated Quick Steps; a silent
        # set() makes "if label = Noise" rules never fire without any signal.
        logger.warning(
            "[has_label] SQL lookup failed for email_id=%s account_id=%s: %s",
            email_id, account_id, exc,
        )
    if sql_labels:
        return sql_labels

    # SQL miss → fall back to the JSON LabelStore (authoritative).
    try:
        from app.infrastructure.container import get_container
        store = get_container().get_label_store(account_id=account_id if account_id else None)
        if store is None:
            return set()
        assignment = store.get_assignment(email_id)
        if assignment is None:
            return set()
        return {str(name).strip().lower() for name in (assignment.labels or []) if name}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[has_label] JSON fallback failed for email_id=%s account_id=%s: %s",
            email_id, account_id, exc,
        )
    return set()


# B-08 (audit 2026-06-11): patterns already reported as invalid — warn once
# per pattern, not once per email × condition (the daemon evaluates triggers
# on every incoming message).
_warned_invalid_regex_patterns: set[str] = set()


def _regex_search(pattern: str, target: str, *, step_id: str = "") -> bool:
    """``re.search`` wrapper that fails closed on a bad stored pattern.

    Schema validation rejects invalid / ReDoS-prone regexes at save time,
    but a pattern persisted before validation tightened (or hand-edited
    JSON) must never crash the auto-trigger daemon.
    """
    try:
        return bool(re.search(pattern, target, re.IGNORECASE))
    except re.error as exc:
        # B-08: fail-closed is right, but stay diagnosable — a condition that
        # can never match again deserves one warning per pattern.
        if pattern not in _warned_invalid_regex_patterns:
            _warned_invalid_regex_patterns.add(pattern)
            logger.warning(
                "[auto-trigger] invalid stored regex %r (step_id=%s): %s — "
                "condition will never match",
                pattern, step_id or "?", exc,
            )
        return False


def _match_condition(
    condition: dict, email, *, account_id: int = 0, email_id: str = "", step_id: str = ""
) -> bool:
    # Upgrade legacy v1 conditions (where the type encoded the operator)
    # to the v2 {type, match_mode} shape before matching. Idempotent and
    # total, so this is safe on already-migrated input and on the dry-run
    # path where the condition may not have passed through the read
    # normaliser. MUST run before the empty-value guard and the if/elif.
    condition = migrate_legacy_condition(condition)
    ctype = condition.get("type", "")
    match_mode = condition.get("match_mode", "")
    raw_value = condition.get("value") or ""
    value = raw_value.lower().strip()
    # Regex match_modes keep the original case of the pattern — re.IGNORECASE
    # handles case-insensitivity at match time. The empty-value guard still
    # applies to all types since an empty regex matches everything (likely
    # a config mistake, not the user's intent).
    if not value:
        return False

    sender = (getattr(email, "sender", "") or "").lower()
    subject = (getattr(email, "subject", "") or "").lower()
    # Sent-side: the SentEmailRef carries `body_preview`, not a full
    # `body` field. Fall back so the email_text
    # body/anywhere scopes can still match question marks / keywords in
    # the user-written portion of the outbound email. Inbound emails have
    # the full `body` and the preview attribute is absent; the fallback is
    # a no-op there.
    body = (
        getattr(email, "body", "")
        or getattr(email, "body_preview", "")
        or ""
    ).lower()

    raw_match = False
    if ctype == "sender":
        if match_mode == "is":
            raw_match = sender == value
        elif match_mode == "contains":
            raw_match = value in sender
        elif match_mode == "matches":
            raw_match = _regex_search(raw_value, sender, step_id=step_id)
    elif ctype == "sender_domain":
        domain = sender.split("@")[-1] if "@" in sender else ""
        if match_mode == "is":
            raw_match = domain == value
        elif match_mode == "contains":
            raw_match = value in domain
        elif match_mode == "matches":
            raw_match = _regex_search(raw_value, domain, step_id=step_id)
    elif ctype == "recipient":
        recipients = (getattr(email, "recipients", "") or "").lower()
        if match_mode == "is":
            # "is" = value equals one of the parsed To/Cc addresses;
            # comparing against the whole joined string would only ever
            # match single-recipient mail.
            raw_match = any(a.strip() == value for a in recipients.split(","))
        elif match_mode == "contains":
            raw_match = value in recipients
        elif match_mode == "matches":
            raw_match = _regex_search(raw_value, recipients, step_id=step_id)
    elif ctype == "email_text":
        if match_mode == "subject":
            raw_match = value in subject
        elif match_mode == "body":
            raw_match = value in body
        else:  # "anywhere"
            raw_match = (value in subject) or (value in body)
    elif ctype == "has_label":
        # Snapshot labels at chain entry so step N+1 does not see labels
        # mutated by step N (archive/relabel) and silently skip.
        snapshot_labels = getattr(email, "labels", None)
        if isinstance(snapshot_labels, frozenset):
            raw_match = value in snapshot_labels
        else:
            raw_match = value in _get_email_label_names(email_id or getattr(email, "id", ""), account_id)
    elif ctype == "has_attachment":
        # value is "true"/"false"/"yes"/"no" — compare against the email's
        # attachments_meta column which is non-empty when attachments exist.
        wants_attachment = value in ("true", "yes", "1", "oui")
        has_att = bool(getattr(email, "attachments_meta", "") or False)
        raw_match = has_att == wants_attachment
    elif ctype == "is_read":
        wants_read = value in ("true", "yes", "1", "oui")
        is_read = bool(getattr(email, "is_read", False))
        raw_match = is_read == wants_read
    elif ctype == "has_deadline_detected":
        # True iff the ingest-time deadline extractor stamped `deadline_at`
        # on the email. value is "true"/"false" — supports both polarities
        # so a rule like "no deadline detected → archive" stays expressible.
        wants_deadline = value in ("true", "yes", "1", "oui")
        has_deadline = bool(getattr(email, "deadline_at", None))
        raw_match = has_deadline == wants_deadline
    elif ctype == "has_emoji_marker":
        # True iff the `mark_with_emoji` action already stamped a marker
        # on this email. Lets users chain rules off a prior marking step
        # (e.g. "if marked 💰 → label 'Billing'"). Boolean value.
        wants_marker = value in ("true", "yes", "1", "oui")
        has_marker = bool(getattr(email, "emoji_marker_json", "") or False)
        raw_match = has_marker == wants_marker
    elif ctype == "previously_auto_actioned_by":
        # Match if the referenced step has already auto-fired (successfully)
        # on any email in the current thread. raw_value preserves UUID case.
        thread_id = (getattr(email, "thread_id", "") or "").strip()
        if account_id > 0 and thread_id and raw_value:
            raw_match = _step_fired_on_thread(account_id, raw_value.strip(), thread_id)
    elif ctype == "calendar_invite":
        if match_mode == "free":
            # "free": the email is a calendar invitation AND the user has
            # no event overlapping the proposed [DTSTART, DTEND]. Fails
            # closed when no invite window can be extracted (not an invite,
            # or ICS missing) or the calendar provider is unreachable, so
            # the QuickStep doesn't fire on bogus inputs.
            window = _extract_invite_window(account_id, email, email_id)
            if window is None:
                raw_match = False
            else:
                start_dt, end_dt = window
                is_busy = _is_user_busy_window(account_id, start_dt, end_dt)
                raw_match = (is_busy is False)  # None → fail closed
        else:
            # "any": match every calendar invitation. Mirrors
            # isMeetingInvite() in EmailDetailModal.tsx and stays in sync
            # with the labelling pipeline's 0-cal-ics rule (label_email.py:443).
            #
            # Detection sources, in order of reliability:
            #   1. .ics attachment listed in attachments_meta (only set on
            #      the DB row, often missing from the dataclass passed here).
            #   2. iCal markers anywhere in the body (text/calendar mime,
            #      BEGIN:VCALENDAR raw block).
            #   3. Subject patterns commonly emitted by Outlook/Google.
            #   4. HTML-rendered meeting links in the body. Hotmail uses
            #      `teams.live.com/meet/` while M365 uses
            #      `teams.microsoft.com/l/meetup-join` — both must match.
            #   5. Brand mentions ("microsoft teams", "google meet", …) —
            #      broad but trusted when the rule fires; false positives go
            #      through normal labelling anyway.
            body_html = (getattr(email, "body_html", "") or "").lower()
            body_full = body + " " + body_html  # already lowercased upstream
            meta = (getattr(email, "attachments_meta", "") or "").lower()
            # 1. ics
            has_ics = (
                ".ics" in meta
                or "text/calendar" in body_full
                or "begin:vcalendar" in body_full
            )
            # 2. subject patterns
            subj_match = bool(
                re.search(r"invitation\s*:", subject, re.IGNORECASE)
                or re.search(r"nouvelle\s+invitation\s*:", subject, re.IGNORECASE)
                or re.search(r"(?:zoom|teams|google\s+meet)\s+meeting\s+invitation", subject, re.IGNORECASE)
                or re.search(r"microsoft\s+teams\s+meeting", subject, re.IGNORECASE)
            )
            # 3. URL/brand patterns in body — covers Hotmail (teams.live.com/meet/),
            #    M365 (teams.microsoft.com/l/meetup-join), Google Meet, Zoom, Webex.
            url_match = any(s in body_full for s in (
                "teams.microsoft.com/l/meetup-join",
                "teams.microsoft.com/l/meetup",
                "teams.microsoft.com/meet/",
                "teams.live.com/meet/",
                "join.microsoft.com/meet/",
                "meet.google.com/",
                "zoom.us/j/",
                "zoom.us/meeting",
                "webex.com/meet",
                "webex.com/join",
            ))
            # 4. Brand mentions (broader; intentionally ASCII-only to survive
            #    mangled UTF-8 in stored HTML bodies — see label_email.py:443).
            brand_match = any(s in body_full for s in (
                "microsoft teams",
                "google meet",
                "zoom meeting",
                "webex meeting",
                "join the meeting",
                "meeting id:",
            ))
            raw_match = has_ics or subj_match or url_match or brand_match
    elif ctype == "email_older_than_days":
        # ``value`` is a positive int (validated by the schema). True when the
        # email's received-at is older than N days. Useful in a future
        # housekeeping sweep ("auto-archive inbox older than 30d"); in the
        # default daemon path that fires on freshly-arrived emails this is
        # trivially false unless the provider is back-filling.
        try:
            days = int(raw_value)
        except (TypeError, ValueError):
            days = 0
        email_date = getattr(email, "date", None)
        if days >= 1 and isinstance(email_date, datetime):
            if email_date.tzinfo is None:
                email_date = email_date.replace(tzinfo=timezone.utc)
            raw_match = (datetime.now(timezone.utc) - email_date) > timedelta(days=days)
    elif ctype == "no_reply_after_days":
        # True when the thread's most recent sent email is older than N days
        # and no inbound message arrived after it — i.e. an outbound email
        # still awaiting a reply. SQL-backed (table ``emails``), no tracker
        # dependency. Account-scoped to avoid cross-tenant thread-id
        # collisions; mirrors the ``thread_has_user_reply`` SQL approach.
        try:
            days = int(raw_value)
        except (TypeError, ValueError):
            days = 0
        thread_id = (
            getattr(email, "thread_id", "")
            or getattr(email, "conversation_id", "")
            or ""
        ).strip()
        if days >= 1 and thread_id and account_id > 0:
            try:
                from app.db.database import get_db_session
                from app.db.models.email import Email as _EmailModel
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                with get_db_session() as session:
                    last_sent = session.query(_EmailModel.date).filter(
                        _EmailModel.account_id == account_id,
                        _EmailModel.thread_id == thread_id,
                        _EmailModel.is_sent.is_(True),
                    ).order_by(_EmailModel.date.desc()).limit(1).first()
                    if last_sent and last_sent[0] is not None:
                        sent_date = last_sent[0]
                        if sent_date.tzinfo is None:
                            sent_date = sent_date.replace(tzinfo=timezone.utc)
                        if sent_date < cutoff:
                            # An inbound message after that send = it was replied to.
                            inbound_after = session.query(_EmailModel.id).filter(
                                _EmailModel.account_id == account_id,
                                _EmailModel.thread_id == thread_id,
                                _EmailModel.is_sent.is_(False),
                                _EmailModel.date > last_sent[0],
                            ).limit(1).first()
                            raw_match = inbound_after is None
            except Exception as exc:  # noqa: BLE001
                logger.debug("no_reply_after_days lookup failed for thread %s: %s", thread_id, exc)
    elif ctype == "is_new_thread":
        # True when the user initiated the thread (no In-Reply-To / no
        # references), not when they replied to someone. Boolean value:
        # "true" → matches new threads; "false" → matches replies.
        # The negation toggle on the editor row handles the reverse
        # ("reply / thread continuation") via condition["negate"] without
        # needing a separate `is_reply` condition type.
        wants_new = value in ("true", "yes", "1", "oui")
        raw_match = _is_thread_initiator(email) == wants_new
    elif ctype == "thread_has_user_reply":
        # True iff the user has sent at least one message in this thread
        # AFTER the evaluated email's date — i.e. the user actually replied
        # to it. A sent message that merely precedes the inbound email (the
        # user started the thread) must NOT count, otherwise rules like the
        # seeded "Archive after reply" archive every answer to user-initiated
        # outreach the moment it arrives (bug 2026-06-11). Combined with the
        # post-reply re-eval hook this turns "reply then archive" into a
        # normal Quick Step rule. We read directly from the ``emails`` SQL
        # table (``is_sent=True`` + ``thread_id``) — every reply send path
        # inserts there, so SQL is the source of truth for reply detection.
        # Account-scoped to prevent cross-tenant false positives on
        # thread-id collisions.
        wants_reply = value in ("true", "yes", "1", "oui")
        # StandardEmail (gmail/outlook providers) exposes ``conversation_id``,
        # not ``thread_id`` — only the SQL Email model uses the ``thread_id``
        # name. Without the fallback this trigger silently never matched for
        # any email loaded straight from a provider (the common path: reply
        # send → post-reply re-eval passes the StandardEmail it just fetched).
        thread_id = (
            getattr(email, "thread_id", "")
            or getattr(email, "conversation_id", "")
            or ""
        ).strip()
        # The SQL column is naive-UTC (app/utils/dates.py convention) while
        # the snapshot hands back an aware datetime — normalize before the
        # comparison. No usable date → the order is unknowable → fail closed
        # (has_reply stays False): never treat a message as replied-to when
        # we cannot prove the reply came after it.
        email_date = to_naive_utc(getattr(email, "date", None))
        has_reply = False
        if thread_id and account_id > 0 and email_date is not None:
            try:
                from app.db.database import get_db_session
                from app.db.models.email import Email as _EmailModel
                with get_db_session() as session:
                    has_reply = session.query(_EmailModel.id).filter(
                        _EmailModel.account_id == account_id,
                        _EmailModel.thread_id == thread_id,
                        _EmailModel.is_sent.is_(True),
                        _EmailModel.date > email_date,
                    ).limit(1).first() is not None
            except Exception as exc:  # noqa: BLE001
                logger.debug("thread_has_user_reply lookup failed for thread %s: %s", thread_id, exc)
        raw_match = has_reply == wants_reply

    return (not raw_match) if condition.get("negate") else raw_match


def _is_thread_initiator(email) -> bool:
    """Return True iff the user started the thread (no In-Reply-To header).

    We accept several plausible attribute names because the sent-side
    pass hands a lightweight SentEmailRef while the engine also runs on
    SQLA Email rows — both shapes are valid input.
    """
    # Direct hint: original_email_id is the message the email is replying
    # to. When set, this is NOT a new thread.
    orig = getattr(email, "original_email_id", None)
    if orig:
        return False
    # Header fallback: emails that have an In-Reply-To header are replies.
    headers = getattr(email, "headers", None) or {}
    if isinstance(headers, dict):
        if headers.get("In-Reply-To") or headers.get("in-reply-to"):
            return False
        if headers.get("References") or headers.get("references"):
            return False
    in_reply_to = getattr(email, "in_reply_to", None)
    if in_reply_to:
        return False
    references = getattr(email, "references", None)
    if references:
        return False
    # Subject hint: emails starting with "Re:" or "Fwd:" are not new threads
    # even if the headers are missing (common for IMAP-fallback shapes).
    subject = (getattr(email, "subject", "") or "").lstrip().lower()
    if subject.startswith(("re:", "ré:", "fwd:", "fw:", "tr:")):
        return False
    return True


def _step_fired_on_email(account_id: int, step_id: str, email_id: str) -> bool:
    """Return True iff ``step_id`` has already auto-fired successfully on
    this specific ``email_id``.

    Used to dedupe re-evaluations: an email's state can change after arrival
    (mark-as-read, label added, etc.) and each state change re-invokes
    `run_auto_triggers`. Without this guard, a rule whose triggers were
    already satisfied at arrival would fire a second time and double-execute
    its actions (e.g. send two replies). Failure-closed: any DB error
    returns False so a transient SQLite hiccup doesn't silently block
    legitimate fires.
    """
    if not (account_id and step_id and email_id):
        return False
    try:
        from app.db.database import get_db_session
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        with get_db_session() as session:
            q = (
                session.query(QuickStepAuditLog.id)
                .filter(
                    QuickStepAuditLog.account_id == account_id,
                    QuickStepAuditLog.step_id == step_id,
                    QuickStepAuditLog.email_id == email_id,
                    QuickStepAuditLog.source == "auto",
                    QuickStepAuditLog.success.is_(True),
                )
                .limit(1)
            )
            return q.first() is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("_step_fired_on_email lookup failed: %s", exc)
        return False


def _fired_pairs(account_id: int, step_ids, email_ids) -> set:
    """Batched form of ``_step_fired_on_email`` for the housekeeping sweep.

    Returns the set of ``(step_id, email_id)`` that already auto-fired
    successfully, across the given steps × emails — ONE query instead of one
    per (step, email).

    Returns ``None`` (NOT an empty set) on DB error, so the caller falls back
    to the per-pair ``_step_fired_on_email`` query rather than treating an
    empty result as "nothing fired" — a single batch failure must not bypass
    dedup for the WHOLE candidate set and re-fire every already-actioned rule.
    An empty *set* is reserved for the legitimate "queried, nothing fired" and
    "empty inputs" cases.

    ``email_ids`` is bounded by ``_HOUSEKEEPING_MAX_CANDIDATES`` (300) at the
    only call site — well under SQLite's ~999 bound-parameter ceiling.
    """
    step_ids = [s for s in step_ids if s]
    email_ids = [e for e in email_ids if e]
    if not (account_id and step_ids and email_ids):
        return set()
    try:
        from app.db.database import get_db_session
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        with get_db_session() as session:
            rows = (
                session.query(QuickStepAuditLog.step_id, QuickStepAuditLog.email_id)
                .filter(
                    QuickStepAuditLog.account_id == account_id,
                    QuickStepAuditLog.step_id.in_(step_ids),
                    QuickStepAuditLog.email_id.in_(email_ids),
                    QuickStepAuditLog.source == "auto",
                    QuickStepAuditLog.success.is_(True),
                )
                .all()
            )
            return {(r[0], r[1]) for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fired_pairs batch lookup failed: %s", exc)
        return None  # signal failure → caller falls back to per-pair dedup


def _step_fired_on_thread(account_id: int, step_id: str, thread_id: str) -> bool:
    """Return True iff ``step_id`` has a successful auto-fire row whose
    email belongs to ``thread_id``.

    Queries quick_step_audit_log JOIN emails on email_id. Fails closed on any
    DB error — auto-trigger paths must never raise.
    """
    try:
        import sqlalchemy as sa
        from app.db.database import get_db_session
        from app.db.models.email import Email
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        with get_db_session() as session:
            # F-01 + F-05 (audit-2026-05-12_2129): the JOIN previously compared
            # Email.id (int PK) to QuickStepAuditLog.email_id (str provider id)
            # — SQLite type-affinity returns False for any non-numeric provider
            # id, so the trigger silently never fires. Pair the column-name fix
            # (email_id <-> email_id) with the account_id pin so cross-account
            # email_id collisions don't false-positive.
            q = (
                session.query(QuickStepAuditLog.id)
                .join(
                    Email,
                    sa.and_(
                        Email.email_id == QuickStepAuditLog.email_id,
                        Email.account_id == QuickStepAuditLog.account_id,
                    ),
                )
                .filter(
                    QuickStepAuditLog.account_id == account_id,
                    QuickStepAuditLog.step_id == step_id,
                    QuickStepAuditLog.source == "auto",
                    QuickStepAuditLog.success.is_(True),
                    Email.thread_id == thread_id,
                )
                .limit(1)
            )
            return q.first() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("previously_auto_actioned_by lookup failed: %s", exc)
        return False


def _extract_invite_window(account_id: int, email, email_id: str) -> tuple[datetime, datetime] | None:
    """Pull (DTSTART, DTEND) UTC-aware from the email's calendar invitation.

    Routes through the same calendar provider as ``handlers/rsvp.py`` so we
    pick up the same parsing of .ics attachments / inline calendar payloads.
    Returns None when:
      - the account has no OAuth-linked calendar (no provider to ask)
      - the email is not a calendar invitation (no meeting time on it)
      - either DTSTART or DTEND is missing or unparseable

    Each polarity treats None as fail-closed: the QuickStep won't fire on
    an email we couldn't classify as a real invite with a real time window.
    """
    oauth_id = _resolve_oauth_account_id(account_id)
    if not oauth_id:
        return None
    try:
        from app.providers.calendar_factory import create_calendar_provider
        cal = create_calendar_provider(oauth_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("calendar provider creation failed: %s", exc)
        return None
    if not cal or not hasattr(cal, "get_meeting_time_from_email"):
        return None
    raw_id = email_id or str(getattr(email, "id", "") or "")
    if not raw_id:
        return None
    try:
        meeting_time = cal.get_meeting_time_from_email(raw_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_meeting_time_from_email failed for %s: %s", raw_id, exc)
        return None
    if not meeting_time:
        return None
    dtstart = meeting_time.get("dtstart")
    dtend = meeting_time.get("dtend")
    if not isinstance(dtstart, datetime) or not isinstance(dtend, datetime):
        return None
    # Normalise tzinfo so the busy-window helper can do arithmetic safely.
    if dtstart.tzinfo is None:
        dtstart = dtstart.replace(tzinfo=timezone.utc)
    if dtend.tzinfo is None:
        dtend = dtend.replace(tzinfo=timezone.utc)
    if dtstart >= dtend:
        return None
    return (dtstart, dtend)


def _has_deepwork_conflict(account_id: int, dtstart: datetime, dtend: datetime) -> bool:
    """Return True if [dtstart, dtend) overlaps a deep-work block.

    Covers both ``deep_work_personal_blocks`` (e.g. "Travail personnel") and
    ``deep_work_check_slots`` (the email-processing windows). Both are local
    user settings — not on the provider calendar — so FreeBusy alone misses
    them and an auto-accept Quick Action would walk over the user's focus
    time. Moved here from handlers/rsvp.py (2026-05-14): the free/busy gate
    now lives in the ``calendar_invite + free`` trigger condition, not in the
    rsvp action.
    """
    from datetime import timedelta
    from app.api.settings import load_settings
    settings = load_settings(account_id=account_id)
    if not settings.get("deep_work_enabled"):
        return False

    weekdays = settings.get("deep_work_weekdays") or [1, 2, 3, 4, 5]
    blocks: list[dict] = []
    if settings.get("deep_work_work_enabled", False):
        for b in settings.get("deep_work_personal_blocks") or []:
            blocks.append(b)
    if settings.get("deep_work_emails_enabled", False):
        for s in settings.get("deep_work_check_slots") or []:
            blocks.append(s)
    if not blocks:
        return False

    # Settings store HH:MM in the user's local time; the provider hands us
    # UTC (or zoned) datetimes. Convert to the user's configured timezone
    # before comparing — without that, a server in UTC and a user in Paris
    # would silently shift block boundaries by 1-2 hours and miss conflicts.
    user_tz = None
    tz_name = (settings.get("user_timezone") or "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo(tz_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "deep_work: invalid user_timezone '%s' (%s); falling back to host TZ",
                tz_name, exc,
            )

    def _to_local(dt):
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt.astimezone(user_tz) if user_tz is not None else dt.astimezone()
        return dt

    ds = _to_local(dtstart)
    de = _to_local(dtend)
    if not hasattr(ds, "isoweekday"):
        return False

    # Iterate every day touched by the meeting (a single 30-min meeting only
    # has one day; defensive loop handles edge cases like overnight blocks).
    cur_day = ds.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = de.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur_day <= end_day:
        if cur_day.isoweekday() in weekdays:
            for b in blocks:
                start_str = b.get("start") or ""
                duration = int(b.get("duration") or 0)
                try:
                    hh, mm = start_str.split(":")
                    block_start = cur_day.replace(hour=int(hh), minute=int(mm))
                except (ValueError, AttributeError):
                    continue
                block_end = block_start + timedelta(minutes=duration)
                # half-open interval overlap
                if not (block_end <= ds or block_start >= de):
                    return True
        cur_day = cur_day + timedelta(days=1)
    return False


def _is_user_busy_window(account_id: int, start: datetime, end: datetime) -> bool | None:
    """Return True iff the user is unavailable during [start, end).

    "Busy" means EITHER a deep-work / focus block (local settings the calendar
    provider never sees) OR a real event on the connected calendar. The
    deep-work check runs first — it is local and cannot fail with a provider
    error, so a focus-time conflict is still caught when the calendar API is
    unreachable.

    Returns None on provider failure so the caller can fail closed instead of
    guessing. start and end must be timezone-aware datetimes.
    """
    if account_id <= 0 or start >= end:
        return None
    # Deep-work / focus blocks first — local, cheap, never raises a provider
    # error. Best-effort: a malformed settings file must not break the matcher.
    try:
        if _has_deepwork_conflict(account_id, start, end):
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("deep-work conflict check failed (continuing): %s", exc)
    oauth_id = _resolve_oauth_account_id(account_id)
    if not oauth_id:
        return None
    try:
        from app.providers.calendar_factory import create_calendar_provider
        cal = create_calendar_provider(oauth_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("calendar provider creation failed: %s", exc)
        return None
    if not cal or not hasattr(cal, "get_freebusy"):
        return None
    try:
        fb = cal.get_freebusy([], start, end)
        # ``get_freebusy`` returns {"calendars": {email_or_id: [{start, end}, ...]}}.
        # When the attendees list is empty the providers we ship default to
        # the primary calendar — flatten the values rather than assuming a
        # specific key.
        calendars = (fb or {}).get("calendars") or {}
        # F-01: fail closed when the provider returned NO calendars at all.
        # Outlook's get_freebusy can land here when the inner /me probe throws
        # (token refresh, Graph throttle, DNS blip) — `schedules` stays empty,
        # the chunk loop short-circuits, and we get back {"calendars": {}}.
        # Treating that as "free" silently auto-RSVPs onto conflicting meetings.
        if not calendars:
            return None
        for slots in calendars.values():
            if slots:
                return True
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_freebusy(window) failed: %s", exc)
        return None


def _evaluate_triggers(step: dict, email, *, account_id: int = 0, email_id: str = "") -> bool:
    """Return True if the step's trigger conditions match the email."""
    triggers = step.get("triggers") or []
    if not triggers:
        return False
    operator = step.get("triggerOperator", "OR")
    step_id = str(step.get("id") or "")
    results = [
        _match_condition(
            c, email, account_id=account_id, email_id=email_id, step_id=step_id
        )
        for c in triggers
    ]
    return all(results) if operator == "AND" else any(results)


def run_auto_triggers(account_id: int, email_id: str, email) -> None:
    """Find and execute all auto-enabled Quick Steps whose conditions match email.

    Failures are logged and swallowed — auto-triggers are best-effort and must
    never block or abort the main daemon processing pipeline.
    """
    if not account_id or account_id <= 0:
        return

    try:
        from app.quicksteps import store
        steps = list(store.load_quick_steps(account_id))
    except Exception as exc:
        logger.warning("auto_trigger: load_quick_steps failed for account %d: %s", account_id, exc)
        return

    # Cross-account aggregation: a single Tauri/desktop session can have
    # multiple linked accounts (Gmail + Outlook). Quick Steps are stored
    # per-account, so a rule built while looking at account A would never
    # fire on an email owned by account B. Walk the multi_accounts manager
    # and pull `firesOn="received"` auto-rules from every other account
    # so a user-perceived "my rule" applies across all their mailboxes.
    #
    # Audit F-01 (2026-05-16): the prior implementation walked the global
    # process-wide manager singleton unconditionally. The inline comment
    # claimed "cloud-JWT installs only have one account per session here"
    # — factually wrong. The manager is process-global, so on a cloud
    # multi-tenant deploy (Railway) User B's `firesOn=received +
    # autoEnabled` rule was pulled into User A's evaluation and fired via
    # User A's authenticated provider on User A's incoming email →
    # cross-tenant data exfiltration via `forward`/`reply_template`/
    # `apply_label`. Fix: resolve the caller's `user_id` once from DB and
    # filter foreign-user configs out of the walk. Tauri loopback
    # (caller_user_id=None) keeps the legacy aggregate-all behaviour.
    caller_user_id = None
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as _sess:
            _caller_acct = AccountRepository(_sess).get(account_id)
            if _caller_acct is not None:
                caller_user_id = getattr(_caller_acct, "user_id", None)
    except Exception as _exc:  # noqa: BLE001
        logger.debug("auto_trigger: caller user_id lookup failed: %s", _exc)

    try:
        from app.multi_accounts import get_account_manager
        from app.api.routes_helpers import _resolve_account_id_for_email
        seen_step_ids = {s.get("id") for s in steps if s.get("id")}
        seen_account_ids = {account_id}
        for cfg in get_account_manager().get_all_accounts():
            # F-01 multi-tenant guard: in cloud deploys the caller is
            # bound to a user_id; foreign-user configs MUST NOT contribute
            # rules. Loopback (caller_user_id=None) preserves legacy
            # behaviour. Configs without `user_id` (legacy unbound rows)
            # are kept ONLY in loopback mode — in cloud, treat them as
            # foreign and skip.
            cfg_user_id = getattr(cfg, "user_id", None)
            if caller_user_id is not None and cfg_user_id != caller_user_id:
                continue
            other_email = getattr(cfg, "email", None)
            if not other_email:
                continue
            other_id = _resolve_account_id_for_email(other_email)
            if not other_id or other_id <= 0 or other_id in seen_account_ids:
                continue
            seen_account_ids.add(other_id)
            try:
                extra = store.load_quick_steps(other_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("auto_trigger: cross-account load skipped for %d: %s", other_id, exc)
                continue
            for s in extra or []:
                if not (s.get("autoEnabled") and s.get("firesOn", "received") == "received"):
                    continue
                sid = s.get("id")
                if sid and sid in seen_step_ids:
                    continue  # dedup by step id — same rule shared across accounts
                seen_step_ids.add(sid)
                steps.append(s)
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto_trigger: cross-account aggregation failed: %s", exc)

    # Snapshot the email at entry so chained steps can't see each other's
    # side effects via the live object (e.g. archive on step 1 → step 2's
    # has_label match would silently flip if it read the live object).
    snapshot = _EmailSnapshot.of(email, account_id=account_id)

    logger.info(
        "auto_trigger: scan account=%s email=%s steps=%d snapshot.is_read=%s snapshot.labels=%s",
        account_id, email_id, len(steps), snapshot.is_read, sorted(snapshot.labels),
    )
    _apply_steps_to_snapshot(account_id, email_id, snapshot, steps)


def _apply_steps_to_snapshot(
    account_id: int, email_id: str, snapshot, steps: list, *, fired_pairs=None,
) -> int:
    """Evaluate ``steps`` against ``snapshot`` and execute the matches.

    ``fired_pairs`` (optional): a pre-computed set of already-fired
    ``(step_id, email_id)`` tuples. When provided, the per-(step, email)
    dedup is an O(1) set lookup instead of a SQL query per step — the
    housekeeping sweep passes one batched set for all its candidates. When
    None (the event path), dedup falls back to the per-pair
    ``_step_fired_on_email`` query, behaviour-identical to before.

    Owns the uniform per-step gate shared by every received-flow entry
    point: enabled + autoEnabled + ``firesOn=="received"`` filtering,
    per-(step, email) audit-log dedup, trigger evaluation, then
    ``engine.execute(source="auto")`` with the fired-event emit. Returns the
    number of steps that fired (capped at ``_MAX_AUTO_TRIGGERS_PER_EMAIL``).

    Callers own step *selection*:
    - ``run_auto_triggers`` passes the full received-rule set on a state
      change (arrival / mark-read / reply-sent).
    - ``run_housekeeping_sweep`` passes only the time-based subset on a
      timer, so passive ``email_older_than_days`` / ``no_reply_after_days``
      rules finally re-evaluate as wall-clock advances.

    Both paths share this body so their dedup + execution semantics can
    never drift apart.
    """
    fired = 0
    for step in steps:
        step_name = step.get("name", "?")
        if fired >= _MAX_AUTO_TRIGGERS_PER_EMAIL:
            logger.warning(
                "auto_trigger: cap %d reached for email %s — remaining steps skipped",
                _MAX_AUTO_TRIGGERS_PER_EMAIL,
                email_id,
            )
            break
        if not step.get("enabled", True):
            logger.info("auto_trigger: skip '%s' (disabled)", step_name)
            continue
        if not step.get("autoEnabled", False):
            logger.info("auto_trigger: skip '%s' (autoEnabled=false)", step_name)
            continue
        # Skip sent-side rules — `run_auto_triggers` is the received-flow
        # entry. Sent rules are handled by `run_auto_triggers_on_sent`
        # below, called from app/api/auto_followup.py.
        if step.get("firesOn", "received") != "received":
            logger.info("auto_trigger: skip '%s' (firesOn=%s)", step_name, step.get("firesOn"))
            continue
        # Per-(step, email) dedup. `run_auto_triggers` is now invoked on
        # every state change (arrival, mark-as-read, …) so the same rule
        # can be evaluated multiple times across an email's lifetime.
        # Without this guard, a rule already-fired at arrival would
        # double-execute its actions on the next state change.
        step_id_for_dedup = step.get("id") or ""
        if step_id_for_dedup:
            already_fired = (
                (step_id_for_dedup, email_id) in fired_pairs
                if fired_pairs is not None
                else _step_fired_on_email(account_id, step_id_for_dedup, email_id)
            )
            if already_fired:
                logger.info("auto_trigger: skip '%s' (already-fired audit row)", step_name)
                continue
        matched = _evaluate_triggers(step, snapshot, account_id=account_id, email_id=email_id)
        if not matched:
            logger.info(
                "auto_trigger: skip '%s' (triggers no match) operator=%s triggers=%s",
                step_name, step.get("triggerOperator"), step.get("triggers"),
            )
            continue

        try:
            from app.quicksteps import engine as engine_module
            report = engine_module.execute(
                account_id=account_id,
                step=step,
                email_id=email_id,
                source="auto",
            )
            if report.success:
                logger.info(
                    "auto_trigger: step '%s' executed on %s",
                    step.get("name"), email_id,
                )
                _emit_quickstep_fired_event(
                    account_id=account_id,
                    step_name=step.get("name", ""),
                    action_type=(step.get("actions") or [{}])[0].get("type", ""),
                    subject=getattr(snapshot, "subject", "") or "",
                    email_id=email_id,
                )
            else:
                logger.warning(
                    "auto_trigger: step '%s' failed on %s — %s",
                    step.get("name"), email_id, report.error,
                )
                _emit_quickstep_failed_event(
                    account_id=account_id,
                    step_name=step.get("name", ""),
                    email_id=email_id,
                    error=report.error,
                )
            fired += 1
        except Exception as exc:
            logger.error(
                "auto_trigger: step '%s' raised on %s: %s",
                step.get("name"), email_id, exc,
            )
            _emit_quickstep_failed_event(
                account_id=account_id,
                step_name=step.get("name", ""),
                email_id=email_id,
                error=str(exc),
            )
    return fired


# --------------------------------------------------------------------------- #
# Housekeeping sweep — timer-driven re-evaluation of passive time rules
# --------------------------------------------------------------------------- #

# Conditions whose truth value changes purely as wall-clock advances. They
# never re-trigger on the event path once an email is sitting in the inbox,
# so the timer-driven sweep re-evaluates them.
_TIME_CONDITION_TYPES = frozenset({"email_older_than_days", "no_reply_after_days"})

# Upper bound on inbox emails evaluated per account per sweep tick. Keeps the
# 5-min scheduler bounded on large mailboxes; oldest-first ordering means the
# emails most likely to match an age threshold are covered first.
_HOUSEKEEPING_MAX_CANDIDATES = 300


def _step_has_time_condition(step: dict) -> bool:
    """True iff any trigger on the step is a wall-clock time condition."""
    return any(
        t.get("type") in _TIME_CONDITION_TYPES
        for t in (step.get("triggers") or [])
    )


def _min_email_age_days(steps: list) -> int | None:
    """Smallest ``email_older_than_days`` threshold across ``steps``.

    Returns None when no step carries that condition — then no SQL date
    floor can be applied to candidate selection (the only other time
    condition, ``no_reply_after_days``, doesn't key on the candidate
    email's own age)."""
    ages: list[int] = []
    for step in steps:
        for trig in (step.get("triggers") or []):
            if trig.get("type") == "email_older_than_days":
                try:
                    ages.append(int(trig.get("value")))
                except (TypeError, ValueError):
                    continue
    return min(ages) if ages else None


def _load_housekeeping_candidates(account_id: int, time_steps: list, max_candidates: int) -> list:
    """Bounded set of inbox-resident received emails to re-evaluate.

    Scopes to ``account_id``, non-sent / non-draft, still carrying the Gmail
    ``INBOX`` label (archived mail is intentionally excluded — re-archiving
    it would be wasted work; the per-(step,email) dedup makes inclusion
    harmless but the filter keeps the scan bounded). Oldest first. When every
    time-rule keys on email age we apply a SQL date floor (the smallest
    threshold) so we only scan emails old enough to possibly match; a
    ``no_reply_after_days`` rule (whose truth depends on the thread's last
    send, not this email's own age) disables that floor.

    Two deliberate looseness notes (both safe under the dedup guarantee):
    - The ``INBOX`` filter reads the provider-sync ``Email.labels`` text
      column, which lags an archive until the next sync — and is a different
      source than the ``email_labels`` store that ``_EmailSnapshot`` /
      ``has_label`` triggers read. So this is a cheap *pre-screen* only; the
      authoritative label check for a rule's ``has_label`` condition still
      happens in the snapshot during evaluation. A briefly-stale inbox flag
      at worst re-evaluates an already-actioned email, which the
      per-(step, email) audit dedup turns into a no-op.
    - ``LIKE '%INBOX%'`` is a substring match (a custom label containing the
      substring would slip through); acceptable for the same dedup reason.
    """
    from datetime import timedelta
    from app.db.database import get_db_session
    from app.db.models.email import Email as _EmailModel

    has_no_reply_rule = any(
        t.get("type") == "no_reply_after_days"
        for s in time_steps for t in (s.get("triggers") or [])
    )
    min_age = _min_email_age_days(time_steps)
    try:
        with get_db_session() as session:
            query = session.query(_EmailModel).filter(
                _EmailModel.account_id == account_id,
                _EmailModel.is_sent.is_(False),
                _EmailModel.is_draft.is_(False),
                _EmailModel.labels.like("%INBOX%"),
            )
            if min_age is not None and not has_no_reply_rule:
                cutoff = datetime.now(timezone.utc) - timedelta(days=min_age)
                query = query.filter(_EmailModel.date < cutoff)
            return list(query.order_by(_EmailModel.date.asc()).limit(max_candidates))
    except Exception as exc:  # noqa: BLE001
        logger.warning("housekeeping: candidate load failed for %s: %s", account_id, exc)
        return []


def run_housekeeping_sweep(
    account_id: int, *, max_candidates: int = _HOUSEKEEPING_MAX_CANDIDATES
) -> dict:
    """Re-evaluate passive time-based Quick Steps over the stored inbox.

    The event path (``run_auto_triggers``) only fires on arrival / state
    change, so a rule like ``email_older_than_days=30 → archive`` never
    triggers on mail that ages past 30 days while just sitting in the inbox.
    This sweep — driven by the existing 5-min scheduler tick — closes that
    gap: it loads the account's enabled, auto, received-flow rules that carry
    a time condition, gathers bounded inbox candidates, and runs them through
    the SAME ``_apply_steps_to_snapshot`` helper as the event path. The
    per-(step, email) audit-log dedup in that helper guarantees a rule that
    already fired on an email is never re-applied, so repeated sweeps are
    idempotent.

    Returns counters ``{steps, candidates, fired}`` for logging. Best-effort:
    swallows internal errors so a single bad account never breaks the tick.
    """
    counters = {"steps": 0, "candidates": 0, "fired": 0}
    if not account_id or account_id <= 0:
        return counters

    try:
        from app.quicksteps import store
        all_steps = list(store.load_quick_steps(account_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("housekeeping: load_quick_steps failed for %s: %s", account_id, exc)
        return counters

    time_steps = [
        s for s in all_steps
        if s.get("enabled", True)
        and s.get("autoEnabled", False)
        and s.get("firesOn", "received") == "received"
        and _step_has_time_condition(s)
    ]
    if not time_steps:
        return counters
    counters["steps"] = len(time_steps)

    candidates = _load_housekeeping_candidates(account_id, time_steps, max_candidates)
    counters["candidates"] = len(candidates)
    if not candidates:
        return counters

    # Batch the per-(step, email) dedup into ONE audit-log query for the whole
    # candidate set instead of one query per candidate per step (the N+1 the
    # event path doesn't hit because it only ever has a single email).
    candidate_ids = [str(getattr(r, "email_id", "") or "") for r in candidates]
    step_ids = [s.get("id") for s in time_steps if s.get("id")]
    fired_pairs = _fired_pairs(account_id, step_ids, candidate_ids)

    for row in candidates:
        email_id = str(getattr(row, "email_id", "") or "")
        if not email_id:
            continue
        try:
            snapshot = _EmailSnapshot.of(row, account_id=account_id)
            counters["fired"] += _apply_steps_to_snapshot(
                account_id, email_id, snapshot, time_steps, fired_pairs=fired_pairs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("housekeeping: eval failed for %s: %s", email_id, exc)

    if counters["candidates"]:
        logger.info("housekeeping sweep account=%s: %s", account_id, counters)
    return counters


def run_auto_triggers_async(account_id: int, email_id: str, email) -> None:
    """Fire-and-forget wrapper around ``run_auto_triggers``.

    Used by reply send paths to re-evaluate Quick Step auto-triggers on the
    original inbox email after the user replied, so a rule like
    ``thread_has_user_reply=true → archive`` fires once the reply lands.

    Spawns a daemon thread so the caller (a Flask request) returns its
    response without blocking on rule evaluation. Per-(step, email) dedup
    in ``run_auto_triggers`` prevents the same rule from re-firing on the
    same email across multiple state-change re-evals (arrival, mark-read,
    reply-sent). The Flask app context is propagated so DB sessions and
    request-scoped lookups (label store, settings) still resolve from
    inside the worker thread.
    """
    if not (account_id and account_id > 0 and email_id and email is not None):
        return
    try:
        from flask import has_app_context, current_app
        flask_app = current_app._get_current_object() if has_app_context() else None
    except Exception:
        flask_app = None

    def _worker() -> None:
        try:
            if flask_app is not None:
                with flask_app.app_context():
                    run_auto_triggers(account_id, email_id, email)
            else:
                run_auto_triggers(account_id, email_id, email)
        except Exception as exc:  # noqa: BLE001
            logger.error("run_auto_triggers_async worker failed: %s", exc, exc_info=True)

    import threading
    threading.Thread(target=_worker, daemon=True, name="qs-reeval-reply").start()


# Codes ok=False qui sont des refus de configuration voulus, pas des pannes :
# pas d'événement quickstep_failed pour eux (audit e2e 2026-06-10 B-02). Les
# vraies pannes (snoozed_draft_store_error, snoozed_draft_reminder_error,
# crash handler) doivent, elles, remonter à l'UI.
_BENIGN_SENT_SKIP_PREFIXES = (
    "snoozed_draft_missing_recipient",
    "snoozed_draft_noreply_recipient",
    "snoozed_draft_availability_email",
    "snoozed_draft_empty_body",
)


def run_auto_triggers_on_sent(
    account_id: int,
    sent_email,
    *,
    _already_fired=None,
    _mark_fired=None,
) -> list[str]:
    """Evaluate `firesOn="sent"` Quick Steps against a sent-email record.

    The caller is the immediate post-send hook in
    app/api/quicksteps_scheduler.py (``fire_sent_quicksteps_immediate``),
    which passes the freshly-sent email straight through.

    For each matching Quick Step, invokes the registered handler directly
    with a minimal ExecutionContext. We bypass engine.execute on purpose:
    - the sent-side has no provider-loaded Email row (the sent-email
      dataclass IS the canonical shape here)
    - the allowed sent-side actions (create_snoozed_followup_draft,
      mark_with_emoji) are pure side-effects, not provider mutations
    - the audit/idempotency machinery in engine.execute assumes the
      provider can load the email, which isn't true for the sent record

    Returns the list of fired step UUIDs so the caller can record an
    in-memory idempotency mark (``_sent_quickstep_fired`` in
    quicksteps_scheduler.py) to prevent re-firing the same rule on the
    same send.
    """
    if not account_id or account_id <= 0:
        return []
    if sent_email is None:
        return []

    try:
        from app.quicksteps import store
        steps = store.load_quick_steps(account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "auto_trigger(sent): load_quick_steps failed for account %d: %s",
            account_id, exc,
        )
        return []

    sent_steps = [
        s for s in steps
        if s.get("enabled", True)
        and s.get("autoEnabled", False)
        and s.get("firesOn") == "sent"
    ]
    if not sent_steps:
        return []

    fired: list[str] = []
    for step in sent_steps:
        try:
            step_id = step.get("id", "")
            if _already_fired is not None and step_id and _already_fired(step_id):
                continue
            if not _evaluate_triggers(step, sent_email, account_id=account_id, email_id=getattr(sent_email, "id", "")):
                continue
            # Audit (2026-05-17): claim the (sent_id, step_id) BEFORE running
            # the action handlers so a concurrent caller (immediate post-send
            # hook racing the scheduler tick) sees it as already fired and
            # short-circuits. Previously the marking happened in the caller
            # AFTER this function returned, leaving a race window in which
            # both callers passed the `_already_fired` check and emitted two
            # `quickstep_fired` toasts for the same sent email.
            if _mark_fired is not None and step_id:
                try:
                    _mark_fired(step_id)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("auto_trigger(sent): _mark_fired raised: %s", exc)
            for action in step.get("actions", []):
                handler = _SENT_ACTION_DISPATCH.get(action.get("type", ""))
                if handler is None:
                    logger.warning(
                        "auto_trigger(sent): action '%s' has no sent-side handler — skipping",
                        action.get("type"),
                    )
                    continue
                ctx = _build_sent_context(account_id, sent_email)
                result = handler(ctx, action.get("payload") or {})
                if result.ok:
                    logger.info(
                        "auto_trigger(sent): step '%s' fired %s on sent %s",
                        step.get("name"), action.get("type"),
                        getattr(sent_email, "id", "?"),
                    )
                    _emit_quickstep_fired_event(
                        account_id=account_id,
                        step_name=step.get("name", ""),
                        action_type=action.get("type", ""),
                        subject=getattr(sent_email, "subject", "") or "",
                        email_id=getattr(sent_email, "id", "") or "",
                    )
                else:
                    logger.warning(
                        "auto_trigger(sent): step '%s' action '%s' failed on sent %s — %s",
                        step.get("name"), action.get("type"),
                        getattr(sent_email, "id", "?"), result.error,
                    )
                    # Audit e2e 2026-06-10 B-02 : parité avec le chemin
                    # received (lignes ~1081/1093) — sans cet événement,
                    # l'échec réel d'un brouillon de relance 🔁 n'était
                    # visible nulle part et l'utilisateur croyait sa relance
                    # armée. Les skips de config (destinataire no-reply,
                    # corps vide…) restent silencieux : ce sont des refus
                    # voulus, pas des pannes. Pas de dé-claim : le claim
                    # avant exécution protège la course immediate-hook /
                    # scheduler (audit 2026-05-17), on ne la rouvre pas.
                    if not (result.error or "").startswith(_BENIGN_SENT_SKIP_PREFIXES):
                        _emit_quickstep_failed_event(
                            account_id=account_id,
                            step_name=step.get("name", ""),
                            email_id=getattr(sent_email, "id", "") or "",
                            error=result.error or "",
                        )
            fired.append(step.get("id", ""))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "auto_trigger(sent): step '%s' raised on sent %s: %s",
                step.get("name"), getattr(sent_email, "id", "?"), exc,
            )
            _emit_quickstep_failed_event(
                account_id=account_id,
                step_name=step.get("name", ""),
                email_id=getattr(sent_email, "id", "") or "",
                error=str(exc),
            )

    return fired


def _build_sent_context(account_id: int, sent_email):
    """Build a minimal ExecutionContext for the sent-side handler.

    `provider` is best-effort (used by handle_follow_up only for the label
    apply, which itself is best-effort). `email` carries the SentEmail
    dataclass fields directly so handlers can read thread_id / subject /
    id without conversion.
    """
    from app.quicksteps.types import ExecutionContext
    provider = None
    try:
        # Resolve via the same path the daemon uses so the label apply,
        # if attempted, hits the right account.
        oauth_id = _resolve_oauth_account_id(account_id)
        if oauth_id:
            from app.providers.factory import get_pooled_provider
            provider = get_pooled_provider(account_id=str(oauth_id))
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto_trigger(sent): provider resolution skipped: %s", exc)
    email_id = getattr(sent_email, "id", "") or ""
    return ExecutionContext(
        provider=provider,
        account_id=account_id,
        account_email="",
        account_display_name="",
        email=sent_email,
        email_id=email_id,
        raw_id=email_id,
        template_vars={},
    )


# Audit (2026-05-18): the previous `_ACTION_TOAST_LABEL: dict[str, str]`
# held French labels that the frontend used as a fallback whenever a new
# `action_type` slipped through without a matching entry in
# `QUICKSTEP_VERB_KEY` (agentys-app/src/services/websocket.ts). Result :
# any forgotten FE-side entry leaked French ("Brouillon de relance préparé",
# "Archivé", …) onto en/es/de UIs. Removing the dict entirely makes
# the backend payload language-agnostic — the frontend now owns 100 %
# of the translation surface for this toast, and unknown action types
# render their English-y `action_type` identifier as a clear fallback
# instead of stealth French.


def _emit_quickstep_fired_event(
    *,
    account_id: int,
    step_name: str,
    action_type: str,
    subject: str,
    email_id: str,
) -> None:
    """Emit a ``quickstep_fired`` daemon event to the user's WebSocket
    room so the frontend surfaces a bottom-right toast confirming the
    rule fired.

    Best-effort: any failure swallows silently (the action itself
    already succeeded — failing the notification shouldn't break the
    user-facing chain).
    """
    if not account_id or account_id <= 0:
        return
    try:
        from app.api.websocket import emit_to_account
    except Exception:  # noqa: BLE001
        return
    try:
        emit_to_account(
            "daemon_event",
            {
                "type": "quickstep_fired",
                "email_id": email_id,
                "payload": {
                    "step_name": step_name or "Quick Step",
                    "action_type": action_type,
                    # No `action_label` field anymore — see comment on the
                    # removed `_ACTION_TOAST_LABEL` dict above. The frontend
                    # translates `action_type` via QUICKSTEP_VERB_KEY +
                    # inbox locale keys.
                    "subject": subject[:120] if subject else "",
                },
            },
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("quickstep_fired emit failed: %s", exc)


def _emit_quickstep_failed_event(
    *,
    account_id: int,
    step_name: str,
    email_id: str,
    error: str | None,
) -> None:
    """Emit a ``quickstep_failed`` daemon event to the user's WebSocket
    room so the frontend surfaces a toast when an auto-fired rule errors
    out — symmetric to ``_emit_quickstep_fired_event``.

    Best-effort: any failure swallows silently (the rule already failed;
    failing the notification shouldn't break the background sweep).
    """
    if not account_id or account_id <= 0:
        return
    try:
        from app.api.websocket import emit_to_account
    except Exception:  # noqa: BLE001
        return
    # Keep the surfaced error short and free of internal detail.
    safe_error = (error or "").strip()[:160]
    try:
        emit_to_account(
            "daemon_event",
            {
                "type": "quickstep_failed",
                "email_id": email_id,
                "payload": {
                    "step_name": step_name or "Quick Step",
                    "error": safe_error,
                },
            },
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("quickstep_failed emit failed: %s", exc)


# Sent-side actions are deliberately a tiny whitelist. The engine's full
# action grammar (archive, delete, mark_read…) does not apply to messages
# the user sent — schema validation rejects pairing them with firesOn=sent.
_SENT_ACTION_DISPATCH: dict = {}


def _init_sent_action_dispatch():
    """Lazy registration so the import graph stays cycle-free."""
    if _SENT_ACTION_DISPATCH:
        return
    from app.quicksteps.handlers import (
        handle_create_snoozed_followup_draft,
        handle_mark_with_emoji,
    )
    _SENT_ACTION_DISPATCH["create_snoozed_followup_draft"] = handle_create_snoozed_followup_draft
    # mark_with_emoji is shape-agnostic — its handler writes
    # `emails.emoji_marker_json` on any row matched by (email_id, account_id),
    # which works for sent rows too. Schema validation already accepts it on
    # firesOn='sent' steps; without this dispatch entry the executor would
    # skip the action at run time with "no sent-side handler".
    _SENT_ACTION_DISPATCH["mark_with_emoji"] = handle_mark_with_emoji


_init_sent_action_dispatch()
