# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Debug SEO scan history — ship to Railway and run there."""
import os
import sqlite3

db = os.environ.get("AGENTYS_DB_PATH", "/data/agentys/agentys.db")
if not os.path.exists(db):
    for cand in ("/data/agentys.db", "/app/data/agentys.db"):
        if os.path.exists(cand):
            db = cand
            break

print("DB:", db, "exists:", os.path.exists(db))
if not os.path.exists(db):
    import sys
    sys.exit(1)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, action, tier, result, metadata, created_at "
    "FROM agent_actions WHERE agent='seo' "
    "ORDER BY created_at DESC LIMIT 30"
).fetchall()

print(f"\n{len(rows)} SEO actions:")
for r in rows:
    meta = (r["metadata"] or "")[:150]
    print(f"  {r['created_at']} | {r['action']:35s} | {r['result']:10s} | {meta}")

print("\n--- Env check ---")
for k in ("GSC_SERVICE_ACCOUNT_JSON", "GSC_SITE_URL", "BING_WEBMASTER_API_KEY",
          "BING_SITE_URL", "GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"):
    v = os.environ.get(k, "")
    print(f"  {k:30s} = {'SET (' + str(len(v)) + ' chars)' if v else 'EMPTY'}")
