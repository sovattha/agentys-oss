# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reconcile the SQL email_labels table with the global JSON assignments
store for one account.

Background (2026-04-25): the LLM auto-labeler writes to the shared
`data/labels/assignments.json` file. The dual-write in
`LabelStore.save_assignment` only touches `email_labels` when the message
row is already in `emails`; sync race conditions left the SQL side stale.
For the affected account, 42 inbox noise rows lived in JSON only,
so the Noise tab silently rendered empty (the route reads from SQL).

Idempotent. Safe under the live Flask backend — it goes through
`get_db_session()` so it shares the connection pool and avoids the
"database is locked" we hit when poking SQLite directly.

Usage on Railway:
    railway ssh "cd /app && PYTHONPATH=/app python3 \\
        scripts/backfill_email_labels.py --account-email user@x.com"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-email", required=True)
    parser.add_argument(
        "--assignments",
        default="/data/agentys/labels/assignments.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    assignments_path = Path(args.assignments)
    if not assignments_path.exists():
        print(f"ERROR: {assignments_path} missing", file=sys.stderr)
        return 1

    with assignments_path.open(encoding="utf-8") as f:
        assignments = json.load(f)
    print(f"Loaded {len(assignments)} assignments", flush=True)

    from sqlalchemy import text
    from app.db.database import get_db_session

    with get_db_session() as session:
        row = session.execute(
            text("SELECT id FROM accounts WHERE email = :email"),
            {"email": args.account_email},
        ).first()
        if not row:
            print(f"ERROR: account {args.account_email} missing", file=sys.stderr)
            return 1
        account_id = int(row[0])
        print(f"account_id = {account_id}", flush=True)

        rows = session.execute(
            text("SELECT email_id FROM emails WHERE account_id = :aid"),
            {"aid": account_id},
        ).all()
        account_email_ids = {r[0] for r in rows}
        print(f"Account has {len(account_email_ids)} emails", flush=True)

        relevant: list[tuple[str, list[str]]] = []
        for entry in assignments:
            eid = entry.get("email_id")
            labels = entry.get("labels") or []
            if not eid or not labels:
                continue
            if eid in account_email_ids:
                relevant.append((eid, labels))

        dist = Counter(lbl for _, ls in relevant for lbl in ls)
        print(f"Relevant: {len(relevant)} assignments, dist: {dict(dist)}", flush=True)

        before = {
            r[0]: r[1]
            for r in session.execute(
                text(
                    "SELECT label_name, COUNT(*) FROM email_labels "
                    "WHERE account_id = :aid GROUP BY label_name"
                ),
                {"aid": account_id},
            ).all()
        }
        print(f"BEFORE: {before}", flush=True)

        if args.dry_run:
            print("--dry-run: no writes")
            return 0

        session.execute(
            text("DELETE FROM email_labels WHERE account_id = :aid"),
            {"aid": account_id},
        )
        params = [
            {"eid": eid, "aid": account_id, "lbl": lbl}
            for eid, labels in relevant
            for lbl in labels
        ]
        if params:
            session.execute(
                text(
                    "INSERT INTO email_labels (email_id, account_id, label_name) "
                    "VALUES (:eid, :aid, :lbl)"
                ),
                params,
            )
        session.commit()
        print(f"Inserted {len(params)} rows", flush=True)

        after = {
            r[0]: r[1]
            for r in session.execute(
                text(
                    "SELECT label_name, COUNT(*) FROM email_labels "
                    "WHERE account_id = :aid GROUP BY label_name"
                ),
                {"aid": account_id},
            ).all()
        }
        print(f"AFTER: {after}", flush=True)

        inbox_dist = {
            r[0]: r[1]
            for r in session.execute(
                text(
                    "SELECT el.label_name, COUNT(*) FROM email_labels el "
                    "INNER JOIN emails e ON e.email_id = el.email_id "
                    "AND e.account_id = el.account_id "
                    "WHERE el.account_id = :aid AND e.folder = 'inbox' "
                    "GROUP BY el.label_name"
                ),
                {"aid": account_id},
            ).all()
        }
        print(f"Inbox by label: {inbox_dist}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
