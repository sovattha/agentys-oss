#!/usr/bin/env python3
"""Migrate the shared draft_corrections.json into per-account files.

Post-#349, each account_id gets its own file under
~/.agentys/draft_corrections/<account_id>.json (matches `_path_for_account`
in app/draft_learning.py — ISO-03 seam from commit 9bfe3c9b).

The legacy single-tenant file `~/.agentys/draft_corrections.json` is kept
for entries without an account_id (Tauri desktop / pre-multi-tenant data).

Usage:
    python scripts/migrate_draft_corrections.py          # dry-run
    python scripts/migrate_draft_corrections.py --apply   # actually split
"""

import argparse
import json
import os
import shutil
import sys

_DEFAULT_PATH = os.path.expanduser("~/.agentys/draft_corrections.json")


def load_shared() -> dict | None:
    if not os.path.exists(_DEFAULT_PATH):
        print(f"[SKIP] Shared file not found: {_DEFAULT_PATH}")
        return None
    with open(_DEFAULT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def report(data: dict):
    corrections = data.get("corrections", [])
    rules = data.get("rules", [])
    positives = data.get("positive_examples", [])
    print(f"  Corrections:      {len(corrections)}")
    print(f"  Rules:            {len(rules)}")
    print(f"  Positive examples:{len(positives)}")
    print(f"  Edit patterns:    {dict(data.get('edit_patterns', {}))}")

    # Check if any entries have account_id metadata
    acct_ids = set()
    for c in corrections:
        aid = c.get("account_id")
        if aid is not None:
            acct_ids.add(aid)
    if acct_ids:
        print(f"  Found account_ids in corrections: {sorted(acct_ids)}")
    else:
        print("  No account_id metadata in corrections — cannot auto-split.")
        print("  Legacy shared file will retain all existing data (Tauri desktop path).")


def backup(path: str) -> str:
    bak = path + ".bak"
    shutil.copy2(path, bak)
    print(f"[BACKUP] Created {bak}")
    return bak


def split_and_save(data: dict):
    """Split data by account_id if present, else keep all in legacy file."""
    corrections = data.get("corrections", [])

    # Group corrections by account_id (positive ints only — None / -1 / 0
    # belong to the legacy single-tenant path).
    by_account: dict[int, list[dict]] = {}
    shared_corrections: list[dict] = []
    for c in corrections:
        aid = c.get("account_id")
        if isinstance(aid, int) and aid > 0:
            by_account.setdefault(aid, []).append(c)
        else:
            shared_corrections.append(c)

    basedir = os.path.dirname(_DEFAULT_PATH)
    per_account_dir = os.path.join(basedir, "draft_corrections")
    os.makedirs(per_account_dir, exist_ok=True)

    # Save legacy shared file — strip migrated corrections
    shared_data = dict(data)
    shared_data["corrections"] = shared_corrections
    with open(_DEFAULT_PATH, "w", encoding="utf-8") as f:
        json.dump(shared_data, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] Legacy → {_DEFAULT_PATH} ({len(shared_corrections)} corrections)")

    # Save per-account files under draft_corrections/<id>.json
    for aid, acct_corrections in sorted(by_account.items()):
        acct_path = os.path.join(per_account_dir, f"{aid}.json")
        acct_data = {
            "corrections": acct_corrections,
            "positive_count": 0,
            "positive_examples": [],
            "rules": [],
            "last_extracted_index": len(acct_corrections),
            "suggestion_clicks": [],
            "refine_instructions": [],
            "edit_patterns": {},
        }
        with open(acct_path, "w", encoding="utf-8") as f:
            json.dump(acct_data, f, ensure_ascii=False, indent=2)
        print(f"[SAVE] Account {aid} → {acct_path} ({len(acct_corrections)} corrections)")


def main():
    parser = argparse.ArgumentParser(description="Migrate draft_corrections.json to per-account files")
    parser.add_argument("--apply", action="store_true", help="Apply migration (default: dry-run)")
    args = parser.parse_args()

    print("=== DraftLearningStore Migration (ISO-03 / #349) ===\n")

    data = load_shared()
    if data is None:
        sys.exit(0)

    print(f"Shared file: {_DEFAULT_PATH}")
    report(data)
    print()

    if not args.apply:
        print("[DRY-RUN] Pass --apply to execute the migration.")
        sys.exit(0)

    if input("Proceed with migration? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        sys.exit(0)

    backup(_DEFAULT_PATH)
    split_and_save(data)

    print("\n[DONE] Migration complete.")
    print("  - Legacy shared file retains entries without account_id (Tauri desktop).")
    print("  - Per-account files created under ~/.agentys/draft_corrections/<id>.json")


if __name__ == "__main__":
    main()
