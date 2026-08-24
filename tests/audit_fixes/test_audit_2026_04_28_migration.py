# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""P1-010 — migration 018 cleanup predicate must reject non-pure-digit IDs.

The original GLOB '[0-9]*' matched '1abc' (starts with a digit), and the
subsequent CAST AS INTEGER silently truncated it to 1, reassigning the row
to account 1. The fix tightens the predicate to pure-digit strings only.
"""
from __future__ import annotations

import sqlite3


# Replicate the production cleanup predicate verbatim so a regression in the
# migration immediately fails this test.
CLEANUP_SQL = (
    "DELETE FROM faq_agent_logs "
    "WHERE account_id IS NULL "
    "OR account_id = '' "
    "OR account_id NOT GLOB '[0-9]*' "
    "OR CAST(account_id AS INTEGER) || '' <> account_id"
)


def test_p1010_cleanup_drops_only_non_pure_digit_rows():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE faq_agent_logs (id INTEGER PRIMARY KEY, account_id TEXT)")
    rows = [
        ("42",),       # keep — pure digits
        ("1",),        # keep
        ("1abc",),     # drop — starts with digit but contains letters
        ("",),         # drop — empty
        ("7xyz",),     # drop — letters tail
        (None,),       # drop — null
        ("abc",),      # drop — no leading digit
        ("12 3",),     # drop — space
        ("0",),        # keep
    ]
    cur.executemany("INSERT INTO faq_agent_logs (account_id) VALUES (?)", rows)
    conn.commit()

    cur.execute(CLEANUP_SQL)
    conn.commit()

    survivors = sorted(r[0] for r in cur.execute("SELECT account_id FROM faq_agent_logs"))
    assert survivors == ["0", "1", "42"], (
        f"Expected only pure-digit account_ids to survive, got {survivors!r}"
    )

    # Sanity: no row reassigned via CAST truncation
    for (aid,) in cur.execute("SELECT account_id FROM faq_agent_logs"):
        assert aid.isdigit() and aid != "", aid
