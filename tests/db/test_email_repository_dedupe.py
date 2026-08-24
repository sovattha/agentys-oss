# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for EmailRepository.dedupe_sent_by_content + thread-count semantics.

Bug surface : a single send produced a ``(2)`` thread badge in the Sent
folder. Root cause was a synthetic ``compose-<ts>`` placeholder row left
behind when the post-send IMAP refresh raced a DB lock and failed to
clean it up. Variants also surface with ``reply-<ts>`` rows on the reply
path. This file pins both the dedupe helper and the thread-count
exclusion to those same shapes so the regression cannot come back.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Email
from app.db.repositories.email_repository import EmailRepository


def _mk_sent(
    session,
    account_id: int,
    *,
    email_id: str,
    subject: str = "Relance Adgen 6 bientôt",
    recipients: str = "ops@adgen.example",
    date: datetime | None = None,
    created_at: datetime | None = None,
    thread_id: str | None = None,
) -> Email:
    """Helper : insert a sent Email row with controlled fields."""
    row = Email(
        email_id=email_id,
        thread_id=thread_id,
        account_id=account_id,
        subject=subject,
        sender="me@example.com",
        sender_name="Me",
        recipients=recipients,
        date=date or datetime.utcnow(),
        body_text="…",
        snippet="…",
        is_read=True,
        is_starred=False,
        is_sent=True,
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    session.flush()
    return row


class TestDedupeSentByContent:
    """Repository-level dedupe across compose-*, reply-*, and provider dupes."""

    def test_compose_synthetic_loses_to_real_provider_row(self, session, sample_account):
        """Synthetic compose-<ts> + real provider row → only real survives."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id=f"compose-{int(ts.timestamp())}", date=ts)
        real = _mk_sent(session, sample_account.id, email_id="19e1efdf70d91d30", date=ts + timedelta(seconds=2))
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 1
        survivors = session.scalars(select(Email).where(Email.account_id == sample_account.id)).all()
        assert [s.email_id for s in survivors] == [real.email_id]

    def test_reply_synthetic_loses_to_real_provider_row(self, session, sample_account):
        """Synthetic reply-<ts> + real provider row → only real survives."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id=f"reply-{int(ts.timestamp())}", date=ts)
        real = _mk_sent(session, sample_account.id, email_id="AQMkADAwATY0MDABLWE2N", date=ts + timedelta(seconds=5))
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 1
        survivors = session.scalars(select(Email).where(Email.account_id == sample_account.id)).all()
        assert [s.email_id for s in survivors] == [real.email_id]

    def test_two_real_rows_keep_newest_by_created_at(self, session, sample_account):
        """Provider double-send (label propagation) → newest created_at wins."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(
            session, sample_account.id, email_id="real-A", date=ts,
            created_at=datetime(2026, 5, 12, 18, 40, 19),
        )
        _mk_sent(
            session, sample_account.id, email_id="real-B", date=ts,
            created_at=datetime(2026, 5, 12, 18, 41, 30),
        )
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 1
        survivors = [s.email_id for s in session.scalars(select(Email)).all()]
        assert survivors == ["real-B"]

    def test_distinct_subjects_are_not_collapsed(self, session, sample_account):
        """Same minute, same recipients, different subjects → both survive."""
        ts = datetime(2026, 5, 12, 18, 40, 0)
        _mk_sent(session, sample_account.id, email_id="m1", subject="Subject A", date=ts)
        _mk_sent(session, sample_account.id, email_id="m2", subject="Subject B", date=ts)
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 0
        assert session.scalar(select(func.count(Email.id))) == 2

    def test_grouping_uses_minute_resolution_not_second(self, session, sample_account):
        """Two rows 30s apart in the same minute → collapsed."""
        _mk_sent(session, sample_account.id, email_id="compose-X", date=datetime(2026, 5, 12, 18, 40, 5))
        real = _mk_sent(session, sample_account.id, email_id="real-X", date=datetime(2026, 5, 12, 18, 40, 35))
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 1
        survivors = session.scalars(select(Email)).all()
        assert [s.email_id for s in survivors] == [real.email_id]

    def test_grouping_does_not_cross_minute_boundary(self, session, sample_account):
        """Two rows 5s apart but spanning a minute boundary → not collapsed."""
        _mk_sent(session, sample_account.id, email_id="r1", date=datetime(2026, 5, 12, 18, 40, 58))
        _mk_sent(session, sample_account.id, email_id="r2", date=datetime(2026, 5, 12, 18, 41, 3))
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 0
        assert session.scalar(select(func.count(Email.id))) == 2

    def test_dedupe_is_scoped_to_account(self, session, sample_account, sample_account_outlook):
        """Rows on a different account never get collapsed together."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id="acct-13-row", date=ts)
        _mk_sent(session, sample_account_outlook.id, email_id="acct-14-row", date=ts)
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 0
        assert session.scalar(select(func.count(Email.id))) == 2

    def test_dedupe_skips_rows_with_null_date(self, session, sample_account):
        """Without a ``date`` we can't safely group — leave the row alone."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id="dated", date=ts)
        _mk_sent(session, sample_account.id, email_id="undated", date=None)
        session.commit()

        removed = EmailRepository(session).dedupe_sent_by_content(sample_account.id)
        session.commit()

        assert removed == 0
        assert session.scalar(select(func.count(Email.id))) == 2

    def test_dedupe_is_idempotent(self, session, sample_account):
        """Running dedupe twice on a clean DB is a no-op."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id=f"compose-{int(ts.timestamp())}", date=ts)
        _mk_sent(session, sample_account.id, email_id="real-Y", date=ts + timedelta(seconds=2))
        session.commit()

        repo = EmailRepository(session)
        assert repo.dedupe_sent_by_content(sample_account.id) == 1
        session.commit()
        assert repo.dedupe_sent_by_content(sample_account.id) == 0


class TestThreadCountExclusion:
    """``_compute_thread_counts`` must ignore synthetic compose-* / reply-* rows."""

    def test_synthetic_rows_excluded_from_thread_count(self, session, sample_account):
        """3 rows on one thread, 2 synthetic — count returns 1."""
        from app.api.routes_emails import _compute_thread_counts
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id="compose-A", thread_id="T1", date=ts)
        _mk_sent(session, sample_account.id, email_id="reply-B", thread_id="T1", date=ts + timedelta(seconds=10))
        _mk_sent(
            session, sample_account.id, email_id="19e1efdf70d91d30",
            thread_id="T1", date=ts + timedelta(seconds=20),
        )
        session.commit()

        counts = _compute_thread_counts(session, sample_account.id, ["T1"])
        assert counts == {"T1": 1}

    def test_thread_count_real_rows_only(self, session, sample_account):
        """4 real provider rows on one thread → count = 4."""
        from app.api.routes_emails import _compute_thread_counts
        ts = datetime(2026, 5, 12, 18, 40, 18)
        for i in range(4):
            _mk_sent(
                session, sample_account.id,
                email_id=f"real-{i:02d}", thread_id="T2",
                date=ts + timedelta(minutes=i),
            )
        session.commit()

        counts = _compute_thread_counts(session, sample_account.id, ["T2"])
        assert counts == {"T2": 4}

    def test_thread_count_scoped_to_account(self, session, sample_account, sample_account_outlook):
        """Same thread_id on two accounts → counted independently."""
        from app.api.routes_emails import _compute_thread_counts
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id="r1", thread_id="shared", date=ts)
        _mk_sent(session, sample_account.id, email_id="r2", thread_id="shared", date=ts + timedelta(minutes=1))
        _mk_sent(session, sample_account_outlook.id, email_id="r3", thread_id="shared", date=ts)
        session.commit()

        assert _compute_thread_counts(session, sample_account.id, ["shared"]) == {"shared": 2}
        assert _compute_thread_counts(session, sample_account_outlook.id, ["shared"]) == {"shared": 1}

    def test_thread_count_empty_input(self, session, sample_account):
        """No thread ids requested → empty dict, no SQL."""
        from app.api.routes_emails import _compute_thread_counts
        assert _compute_thread_counts(session, sample_account.id, []) == {}
        assert _compute_thread_counts(session, sample_account.id, [None, "", None]) == {}


class TestGetByThreadSyntheticSuppression:
    """``get_by_thread`` hides synthetic rows once a real row covers them."""

    def test_synthetic_hidden_when_real_exists(self, session, sample_account):
        """Synthetic + real in same thread + same content → only real returned."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id=f"compose-{int(ts.timestamp())}", thread_id="T1", date=ts)
        _mk_sent(session, sample_account.id, email_id="real-1", thread_id="T1", date=ts + timedelta(seconds=2))
        session.commit()

        result = EmailRepository(session).get_by_thread("T1", sample_account.id)
        assert [r.email_id for r in result] == ["real-1"]

    def test_synthetic_kept_when_alone(self, session, sample_account):
        """Synthetic with no real counterpart → user must still see their send."""
        ts = datetime(2026, 5, 12, 18, 40, 18)
        _mk_sent(session, sample_account.id, email_id=f"compose-{int(ts.timestamp())}", thread_id="T2", date=ts)
        session.commit()

        result = EmailRepository(session).get_by_thread("T2", sample_account.id)
        assert len(result) == 1
        assert result[0].email_id.startswith("compose-")

    def test_real_thread_unaffected(self, session, sample_account):
        """No synthetic rows → return everything unchanged."""
        ts = datetime(2026, 5, 12, 18, 40, 0)
        _mk_sent(session, sample_account.id, email_id="r1", thread_id="T3", date=ts)
        _mk_sent(session, sample_account.id, email_id="r2", thread_id="T3", date=ts + timedelta(minutes=5))
        _mk_sent(session, sample_account.id, email_id="r3", thread_id="T3", date=ts + timedelta(minutes=10))
        session.commit()

        result = EmailRepository(session).get_by_thread("T3", sample_account.id)
        assert [r.email_id for r in result] == ["r1", "r2", "r3"]

    def test_synthetic_with_different_content_survives(self, session, sample_account):
        """Synthetic whose content doesn't match any real row stays visible."""
        ts = datetime(2026, 5, 12, 18, 40, 0)
        _mk_sent(
            session, sample_account.id, email_id=f"compose-{int(ts.timestamp())}",
            thread_id="T4", date=ts, subject="Pending send",
        )
        _mk_sent(
            session, sample_account.id, email_id="r1",
            thread_id="T4", date=ts + timedelta(minutes=2), subject="Different reply",
        )
        session.commit()

        result = EmailRepository(session).get_by_thread("T4", sample_account.id)
        # Both survive — synthetic isn't a duplicate of the real row.
        assert sorted(r.email_id for r in result) == ["compose-" + str(int(ts.timestamp())), "r1"]
