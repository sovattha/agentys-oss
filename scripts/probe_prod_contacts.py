# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os
import sqlite3

DB = "/data/agentys/agentys.db"
db = sqlite3.connect(DB)
row = db.execute("SELECT knowledge_json, rules_json FROM onboarding_results WHERE id=5").fetchone()
k = json.loads(row[0] or "{}")
rr = json.loads(row[1] or "{}")

print("=== ONBOARDING #5 ===")
print(f"contacts ({len(k.get('contacts', []))}):")
for c in k.get("contacts", []):
    print(f"  email={c.get('email')!r:40} name={c.get('name')!r:30} tone={c.get('preferred_tone')!r:15} variant={c.get('language_variant')!r}")

print(f"\ncontact_rules ({len(rr.get('contact_rules', []))}):")
for c in rr.get("contact_rules", []):
    print(f"  email={c.get('contact_email')!r:40} tone={c.get('tone')!r:12} addr={c.get('addressing')!r:8} greet={c.get('greeting')!r:40}")

print("\n=== STYLE_PROFILE_2.JSON ===")
for fname in os.listdir("/app/data/learning"):
    if fname.startswith("style_profile_"):
        path = os.path.join("/app/data/learning", fname)
        mt = os.path.getmtime(path)
        d = json.load(open(path))
        print(f"FILE {fname} mtime={mt} analyzed_at={d.get('analyzed_at')} email_count={d.get('email_count')}")
        cp = d.get("contact_profiles", {})
        print(f"  contact_profiles ({len(cp)}):")
        for k2, v in cp.items():
            nonzero = {kk:vv for kk,vv in v.items() if vv}
            print(f"    {k2}: {nonzero if nonzero else '(all null)'}")
