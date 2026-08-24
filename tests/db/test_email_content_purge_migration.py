# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for the metadata-only email content purge migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "20260515_000001_purge_email_content_cache.py"
    )
    spec = importlib.util.spec_from_file_location("purge_email_content_cache", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_purge_email_content_nulls_body_fields_and_rebuilds_sqlite_fts(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'email-content.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE emails (
                    id INTEGER PRIMARY KEY,
                    subject TEXT,
                    sender TEXT,
                    body_text TEXT,
                    body_html TEXT,
                    snippet TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE emails_fts USING fts5(
                    subject,
                    body_text,
                    sender,
                    content='emails',
                    content_rowid='id'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO emails (id, subject, sender, body_text, body_html, snippet)
                VALUES
                    (1, 'Hello metadata', 'a@example.com', 'secret body one', '<p>secret body one</p>', 'secret one'),
                    (2, 'Other metadata', 'b@example.com', 'secret body two', '<p>secret body two</p>', 'secret two')
                """
            )
        )
        conn.execute(text("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')"))

        assert conn.execute(
            text("SELECT count(*) FROM emails_fts WHERE emails_fts MATCH 'secret'")
        ).scalar_one() == 2

        assert migration._purge_email_content(conn, batch_size=1) == 2
        migration._rebuild_sqlite_email_fts(conn)

        rows = conn.execute(
            text("SELECT body_text, body_html, snippet FROM emails ORDER BY id")
        ).all()
        assert [tuple(row) for row in rows] == [
            (None, None, None),
            (None, None, None),
        ]
        assert conn.execute(
            text("SELECT count(*) FROM emails_fts WHERE emails_fts MATCH 'secret'")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM emails_fts WHERE emails_fts MATCH 'metadata'")
        ).scalar_one() == 2

        assert migration._purge_email_content(conn, batch_size=1) == 0

    engine.dispose()


def test_purge_draft_history_content_nulls_legacy_payload(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'draft-history-content.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE draft_history (
                    id INTEGER PRIMARY KEY,
                    email_id TEXT NOT NULL,
                    email_body TEXT,
                    draft_v1 TEXT,
                    critique TEXT,
                    draft_final TEXT,
                    status TEXT,
                    tokens_used INTEGER,
                    feedback TEXT,
                    feedback_score INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO draft_history
                    (id, email_id, email_body, draft_v1, critique, draft_final,
                     status, tokens_used, feedback, feedback_score)
                VALUES
                    (1, 'email-1', 'secret body', 'draft one', 'private critique',
                     'final answer', 'V1', 123, 'positive', 5),
                    (2, 'email-2', NULL, NULL, NULL, NULL, 'V2', 456, 'neutral', 3)
                """
            )
        )

        assert migration._purge_draft_history_content(conn, batch_size=1) == 1

        rows = conn.execute(
            text(
                """
                SELECT email_body, draft_v1, critique, draft_final, status,
                       tokens_used, feedback, feedback_score
                FROM draft_history
                ORDER BY id
                """
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (None, None, None, None, "V1", 123, "positive", 5),
            (None, None, None, None, "V2", 456, "neutral", 3),
        ]
        assert migration._purge_draft_history_content(conn, batch_size=1) == 0

    engine.dispose()


def test_purge_draft_free_text_content_keeps_user_facing_draft(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'draft-free-text.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE drafts (
                    id INTEGER PRIMARY KEY,
                    subject TEXT,
                    body_text TEXT,
                    body_html TEXT,
                    generation_prompt TEXT,
                    user_edits TEXT,
                    feedback_rating INTEGER,
                    feedback_notes TEXT,
                    status TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO drafts
                    (id, subject, body_text, body_html, generation_prompt,
                     user_edits, feedback_rating, feedback_notes, status)
                VALUES
                    (1, 'Reply', 'final draft body', '<p>final draft body</p>',
                     'prompt with private email body',
                     '{"before":"private","after":"private"}',
                     4, 'private feedback note', 'reviewed'),
                    (2, 'Clean', 'already minimal', NULL,
                     NULL, NULL, 5, NULL, 'sent')
                """
            )
        )

        assert migration._purge_draft_free_text_content(conn) == 1

        rows = conn.execute(
            text(
                """
                SELECT subject, body_text, body_html, generation_prompt,
                       user_edits, feedback_rating, feedback_notes, status
                FROM drafts
                ORDER BY id
                """
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (
                "Reply",
                "final draft body",
                "<p>final draft body</p>",
                None,
                None,
                4,
                None,
                "reviewed",
            ),
            ("Clean", "already minimal", None, None, None, 5, None, "sent"),
        ]
        assert migration._purge_draft_free_text_content(conn) == 0

    engine.dispose()


def test_purge_learned_pattern_examples_keeps_abstract_rule(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'learned-patterns.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE learned_patterns (
                    id INTEGER PRIMARY KEY,
                    pattern_type TEXT NOT NULL,
                    pattern_value TEXT NOT NULL,
                    correction TEXT DEFAULT '',
                    examples TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    occurrences INTEGER DEFAULT 1
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO learned_patterns
                    (id, pattern_type, pattern_value, correction, examples,
                     confidence, occurrences)
                VALUES
                    (1, 'bad', 'too formal', 'use a warmer tone',
                     '["raw email fragment", "another private example"]', 0.8, 4),
                    (2, 'good', 'concise replies', '', '[]', 0.7, 3)
                """
            )
        )

        assert migration._purge_learned_pattern_examples(conn) == 1

        rows = conn.execute(
            text(
                """
                SELECT pattern_value, correction, examples, confidence, occurrences
                FROM learned_patterns
                ORDER BY id
                """
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            ("too formal", "use a warmer tone", "[]", 0.8, 4),
            ("concise replies", "", "[]", 0.7, 3),
        ]
        assert migration._purge_learned_pattern_examples(conn) == 0

    engine.dispose()


def test_purge_sent_email_body_previews_keeps_followup_metadata(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'sent-emails.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sent_emails (
                    id TEXT PRIMARY KEY,
                    recipient TEXT NOT NULL,
                    subject TEXT,
                    body_preview TEXT,
                    original_email_id TEXT,
                    thread_id TEXT,
                    sent_at TEXT,
                    status TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO sent_emails
                    (id, recipient, subject, body_preview, original_email_id,
                     thread_id, sent_at, status)
                VALUES
                    ('sent-1', 'client@example.com', 'Follow-up',
                     'private body preview', 'email-1', 'thread-1',
                     '2026-05-15T12:00:00', 'pending'),
                    ('sent-2', 'other@example.com', 'Already minimal',
                     NULL, 'email-2', 'thread-2',
                     '2026-05-15T12:00:00', 'replied')
                """
            )
        )

        assert migration._purge_sent_email_body_previews(conn) == 1

        rows = conn.execute(
            text(
                """
                SELECT id, recipient, subject, body_preview, original_email_id,
                       thread_id, status
                FROM sent_emails
                ORDER BY id
                """
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            ("sent-1", "client@example.com", "Follow-up", None, "email-1", "thread-1", "pending"),
            ("sent-2", "other@example.com", "Already minimal", None, "email-2", "thread-2", "replied"),
        ]
        assert migration._purge_sent_email_body_previews(conn) == 0

    engine.dispose()


def test_purge_contact_summary_content_keeps_only_abstract_labels(tmp_path):
    migration = _load_migration_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'contact-summary.db'}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    summary_json TEXT,
                    summary_last_message_id TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO contacts
                    (id, email, summary_json, summary_last_message_id)
                VALUES
                    (1, 'client@example.com',
                     '{"relation_type":"client","habitual_tone":"formal","language":"fr","recurring_topics":["deal privé"],"user_formulas_opening":["Bonjour Jean,"],"key_facts":["budget privé"],"last_interaction_summary":"Résumé privé."}',
                     'msg-1'),
                    (2, 'minimal@example.com',
                     '{"habitual_tone": "casual", "language": "en", "relation_type": "friend"}',
                     'msg-2'),
                    (3, 'invalid@example.com',
                     '{not json',
                     'msg-3')
                """
            )
        )

        assert migration._purge_contact_summary_content(conn, batch_size=2) == 2

        rows = conn.execute(
            text(
                """
                SELECT id, summary_json, summary_last_message_id
                FROM contacts
                ORDER BY id
                """
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (
                1,
                '{"habitual_tone": "formal", "language": "fr", "relation_type": "client"}',
                "msg-1",
            ),
            (
                2,
                '{"habitual_tone": "casual", "language": "en", "relation_type": "friend"}',
                "msg-2",
            ),
            (3, "{}", "msg-3"),
        ]
        assert migration._purge_contact_summary_content(conn, batch_size=2) == 0

    engine.dispose()
