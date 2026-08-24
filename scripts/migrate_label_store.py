#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migrate LabelStore data into per-account directories.

Post-#348 (ISO-02), each account_id gets its own directory under
data/labels/<account_id>/ (matches container.py `get_label_store(account_id)`
seam from 9bfe3c9b).

The legacy data/labels/ directory is kept intact for backward compat (Tauri
desktop / callers that don't pass account_id).

Usage:
    python scripts/migrate_label_store.py          # dry-run
    python scripts/migrate_label_store.py --apply   # actually copy
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LABELS_DIR = DATA_DIR / "labels"
APP_DB = Path.home() / "Library/Application Support/agentys/agentys_encrypted.db"

LABEL_FILES = [
    "labels.json",
    "rules.json",
    "assignments.json",
    "RULES.md",
    "template_label_cache.json",
]


# ── helpers ──────────────────────────────────────────────────────────────

def get_accounts() -> list[dict]:
    """Query numeric account IDs from the app database."""
    if not APP_DB.exists():
        print(f"[SKIP] App database not found: {APP_DB}")
        print("  (this is normal on CI / fresh install — nothing to migrate)")
        return []
    conn = sqlite3.connect(str(APP_DB))
    try:
        cursor = conn.execute(
            "SELECT id, email, provider FROM accounts ORDER BY id"
        )
        return [
            {"id": row[0], "email": row[1], "provider": row[2]}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def file_size(path: Path) -> str:
    """Human-readable file size."""
    if not path.exists():
        return "(missing)"
    b = path.stat().st_size
    if b < 1024:
        return f"{b} B"
    elif b < 1024**2:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / 1024**2:.1f} MB"


def report(accounts: list[dict]):
    """Print a report of what would be migrated."""
    print(f"  Accounts: {len(accounts)}\n")

    for a in accounts:
        print(f"    [{a['id']}] {a['email']} ({a['provider']})")

    print()
    print("  Legacy files in data/labels/:")
    for fn in LABEL_FILES:
        print(f"    {fn:<35s} {file_size(LABELS_DIR / fn)}")

    # Check if any per-account dirs already exist
    existing = sorted(LABELS_DIR.glob("*/")) if LABELS_DIR.is_dir() else []
    acct_dirs = [d for d in existing if d.name.isdigit()]
    if acct_dirs:
        print(f"\n  Per-account dirs already present: {[d.name for d in acct_dirs]}")
        print("  (migration may have been partially run)")


def backup(src: Path) -> str | None:
    """Backup the labels directory."""
    if not src.is_dir():
        return None
    bak = src.parent / (src.name + ".bak")
    if bak.exists():
        print(f"[WARN] Backup already exists: {bak} — removing")
        shutil.rmtree(bak)
    shutil.copytree(src, bak)
    print(f"[BACKUP] {src} → {bak}")
    return str(bak)


def migrate(accounts: list[dict]):
    """Copy legacy label files into per-account directories."""
    if not LABELS_DIR.is_dir():
        print(f"[SKIP] Labels directory not found: {LABELS_DIR}")
        return

    for a in accounts:
        acct_dir = LABELS_DIR / str(a["id"])
        acct_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for fn in LABEL_FILES:
            src = LABELS_DIR / fn
            if not src.exists():
                continue
            dst = acct_dir / fn
            shutil.copy2(src, dst)
            copied += 1

        print(f"[SAVE] Account {a['id']} ({a['email']}) → {acct_dir}/ ({copied} files)")

    # Legacy files stay untouched
    print(f"\n  Legacy data/labels/ preserved ({LABELS_DIR})")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate LabelStore data to per-account directories"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply migration (default: dry-run)",
    )
    args = parser.parse_args()

    print("=== LabelStore Migration (ISO-02 / #348) ===\n")

    accounts = get_accounts()
    if not accounts:
        print("No accounts found — nothing to migrate.")
        sys.exit(0)

    report(accounts)
    print()

    if not args.apply:
        print("[DRY-RUN] Pass --apply to execute the migration.")
        sys.exit(0)

    confirm = input("Proceed with migration? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    backup(LABELS_DIR)
    migrate(accounts)

    print("\n[DONE] Migration complete.")
    print("  - Legacy data/labels/ preserved for backward compat.")
    print("  - Per-account data written to data/labels/<id>/")
    print("\n  Next step: update call sites to pass account_id to")
    print("  container.get_label_store(account_id) (Phase 3 / #348).")


if __name__ == "__main__":
    main()
