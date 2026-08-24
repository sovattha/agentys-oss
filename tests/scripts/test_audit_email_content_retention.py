# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_email_content_retention.py"
SPEC = importlib.util.spec_from_file_location("audit_email_content_retention", SCRIPT_PATH)
audit_email_content_retention = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = audit_email_content_retention
SPEC.loader.exec_module(audit_email_content_retention)


def test_json_scan_flags_style_reference_email_text(tmp_path: Path) -> None:
    path = tmp_path / "learning" / "style_profile_1.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "reference_examples": [
                    {
                        "body_excerpt": "Bonjour Alice, voici le contrat secret",
                        "subject": "Contrat ACME",
                        "length_bucket": "medium",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _, findings = audit_email_content_retention.scan_json_paths([tmp_path])

    locations = {finding.location for finding in findings}
    assert "reference_examples[0].body_excerpt" in locations
    assert "reference_examples[0].subject" in locations


def test_json_scan_allows_minimized_style_reference_metadata(tmp_path: Path) -> None:
    path = tmp_path / "learning" / "style_profile_1.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "reference_examples": [
                    {
                        "body_excerpt": "",
                        "subject": "",
                        "length_bucket": "medium",
                        "word_count": 42,
                        "source_email_id": "provider-id",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _, findings = audit_email_content_retention.scan_json_paths([tmp_path])

    assert findings == []


def test_database_scan_flags_cached_email_content_and_free_text() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE emails (body_text TEXT, body_html TEXT, snippet TEXT)"))
        conn.execute(
            text(
                "INSERT INTO emails (body_text, body_html, snippet) "
                "VALUES ('raw body', '<p>raw</p>', :snippet)"
            ),
            {"snippet": "x" * 151},
        )
        conn.execute(text("CREATE TABLE drafts (generation_prompt TEXT, user_edits TEXT, feedback_notes TEXT)"))
        conn.execute(
            text(
                "INSERT INTO drafts (generation_prompt, user_edits, feedback_notes) "
                "VALUES ('reply to this private email', '', NULL)"
            )
        )
        conn.execute(text("CREATE TABLE contacts (id INTEGER, summary_json TEXT)"))
        conn.execute(
            text(
                "INSERT INTO contacts (id, summary_json) VALUES "
                "(7, :summary_json)"
            ),
            {"summary_json": json.dumps({"relation_type": "client", "last_topic": "secret launch"})},
        )

    _, findings = audit_email_content_retention.scan_database(engine)

    locations = {finding.location for finding in findings}
    assert "emails.body_text" in locations
    assert "emails.body_html" in locations
    assert "emails.snippet" in locations
    assert "drafts.generation_prompt" in locations
    assert "contacts[7].summary_json" in locations


def test_database_scan_allows_minimized_contact_summary() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE contacts (id INTEGER, summary_json TEXT)"))
        conn.execute(
            text("INSERT INTO contacts (id, summary_json) VALUES (1, :summary_json)"),
            {
                "summary_json": json.dumps(
                    {
                        "relation_type": "client",
                        "habitual_tone": "direct",
                        "language": "fr",
                    }
                )
            },
        )

    _, findings = audit_email_content_retention.scan_database(engine)

    assert findings == []
