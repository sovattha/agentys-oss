# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3
c = sqlite3.connect("/data/agentys/agentys.db").cursor()

print("=== Label distribution of today's inbox emails ===")
rows = c.execute("""
  SELECT COALESCE(el.label_name, 'UNLABELED') as lbl, COUNT(*)
  FROM emails e
  LEFT JOIN email_labels el ON el.email_id=e.email_id AND el.account_id=e.account_id
  WHERE e.account_id=5 AND e.folder='inbox' AND DATE(e.date)='2026-04-24'
  GROUP BY lbl ORDER BY 2 DESC
""").fetchall()
for r in rows:
    print("  %-12s: %d" % (r[0], r[1]))

print()
print("=== Today unlabeled — details ===")
rows = c.execute("""
  SELECT e.email_id, e.date, e.sender, substr(e.subject, 1, 60), e.created_at
  FROM emails e
  LEFT JOIN email_labels el ON el.email_id=e.email_id AND el.account_id=e.account_id
  WHERE e.account_id=5 AND e.folder='inbox' AND DATE(e.date)='2026-04-24' AND el.label_name IS NULL
  ORDER BY e.date DESC
""").fetchall()
for r in rows:
    sender = (r[2] or "")[:35]
    subj = r[3] or ""
    print("  date=%s created=%s | %-35s | %s" % (r[1][:16], r[4][:16], sender, subj))
