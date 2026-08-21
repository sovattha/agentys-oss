#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
One-shot SQLCipher migration: convert a plaintext SQLite DB to SQLCipher
in-place.

Use case
--------
GitHub #206 (CASA V6.2 — encryption at rest). The Railway production DB at
/data/agentys/agentys.db is plaintext because the keychain fallback in
app/db/encryption.py:get_encryption_key kicks in on Linux containers.
Setting AGENTYS_ENCRYPTION_KEY env var directly would brick the boot:
db.database._create_connection runs `SELECT count(*) FROM sqlite_master`
right after `PRAGMA key`, which fails on a plaintext file with
"file is not a database" → WrongKeyError.

The fix is an out-of-band migration using SQLCipher's `sqlcipher_export()`:
  1. PRAGMA wal_checkpoint(FULL) on the live DB so all WAL writes are in
     the main file
  2. Open the plaintext DB, ATTACH a new encrypted DB with the target key
  3. SELECT sqlcipher_export('encrypted') copies every row across
  4. Verify row counts on a few tables
  5. The orchestrator (the runbook) then atomically swaps the files and
     sets the env var

Usage
-----
    python3 scripts/encrypt_existing_db.py \\
        --plaintext /data/agentys/agentys.db \\
        --encrypted /data/agentys/agentys.db.encrypted \\
        --key-file /tmp/encryption-key.hex

The key file must contain a single line: a 64-character lowercase hex string
(32 bytes). Generate one with:
    python3 -c "import secrets; print(secrets.token_hex(32))"

Safety
------
- Aborts if --encrypted already exists (won't overwrite — call --force to
  override; the orchestrator should NEVER need this)
- Validates hex key format before passing it to PRAGMA (defends against
  PRAGMA injection — same regex as app/db/encryption.py)
- Reports row counts on all tables before/after so a human can spot
  divergence
- Read-only on the plaintext source: it does NOT modify it. The runbook
  is responsible for the eventual `mv` swap.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

# Strict hex validation — same as app/db/encryption.py to prevent PRAGMA
# injection. Lowercase or uppercase, 32 bytes (= 64 hex chars) required.
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _validate_hex_key(key: str) -> str:
    """Reject anything that isn't a 64-char hex string."""
    key = key.strip()
    if not _HEX_KEY_RE.match(key):
        raise ValueError(
            f"Encryption key must be 64 hex chars (32 bytes). Got len={len(key)}."
        )
    return key


def _list_tables_with_counts(conn) -> dict[str, int]:
    """Return {table_name: row_count} for every user table."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    tables = [row[0] for row in cur.fetchall()]
    counts: dict[str, int] = {}
    for tbl in tables:
        # Identifier from sqlite_master — already validated (no injection).
        cur.execute(f"SELECT count(*) FROM \"{tbl}\"")
        counts[tbl] = cur.fetchone()[0]
    cur.close()
    return counts


def _checkpoint_wal(plaintext_path: Path) -> None:
    """Force any WAL writes into the main DB file before snapshotting.

    Safe to run while the original Flask process holds the file: WAL
    checkpoint cooperates via the SHM lock, and a FULL checkpoint is best-
    effort under contention (it returns busy if a writer is mid-transaction
    rather than corrupting state).
    """
    import sqlite3  # plain sqlite3 is fine — file is plaintext

    conn = sqlite3.connect(str(plaintext_path), timeout=30)
    try:
        cur = conn.cursor()
        # FULL = block until WAL fully merged into main DB; the result row
        # is (busy, log_pages, checkpointed_pages).
        result = cur.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
        print(f"[checkpoint] busy={result[0]} log_pages={result[1]} checkpointed={result[2]}")
        if result[0] == 1:
            print(
                "[checkpoint] WARNING: checkpoint reported busy. "
                "Some WAL frames may not be merged. Recent writes will live "
                "in agentys.db-wal; you can recover them from the plaintext "
                "backup if the migration window lost data.",
                file=sys.stderr,
            )
        cur.close()
    finally:
        conn.close()


def encrypt_db(plaintext_path: Path, encrypted_path: Path, key_hex: str) -> None:
    """
    Use SQLCipher's sqlcipher_export to copy plaintext → encrypted.

    The idiom (per SQLCipher docs):
      1. Open the plaintext DB via sqlcipher3 *without* a PRAGMA key
         (plaintext is the default, no key required)
      2. ATTACH a new encrypted database file with the target key
      3. SELECT sqlcipher_export('encrypted') — atomically copies every
         table, index, trigger, and view from main to the attached schema
      4. DETACH and close

    The PRAGMA values must match what app/db/encryption.py applies on every
    connection (kdf_iter, hmac_algorithm, kdf_algorithm) so that the running
    backend can open the resulting file.
    """
    from sqlcipher3 import dbapi2 as sqlite

    if encrypted_path.exists():
        raise FileExistsError(
            f"{encrypted_path} already exists. Refusing to overwrite. "
            f"Delete it manually if you really want to redo the migration."
        )

    print(f"[encrypt] opening plaintext: {plaintext_path}")
    conn = sqlite.connect(str(plaintext_path))
    try:
        cur = conn.cursor()
        # Plaintext source → no PRAGMA key here.
        # Attach a fresh encrypted target. The KEY is validated above.
        attach_sql = (
            f"ATTACH DATABASE '{encrypted_path}' AS encrypted "
            f"KEY \"x'{key_hex}'\""
        )
        print(f"[encrypt] attaching encrypted target: {encrypted_path}")
        cur.execute(attach_sql)

        # Apply the same SQLCipher PRAGMAs that app/db/encryption.py uses,
        # to the attached schema. Without these, the file would be encrypted
        # with SQLCipher defaults (kdf_iter=256000 in modern SQLCipher,
        # HMAC_SHA512 by default) but we pin them explicitly so a future
        # SQLCipher upgrade doesn't drift.
        cur.execute("PRAGMA encrypted.cipher_page_size = 4096")
        cur.execute("PRAGMA encrypted.kdf_iter = 256000")
        cur.execute("PRAGMA encrypted.cipher_hmac_algorithm = HMAC_SHA512")
        cur.execute("PRAGMA encrypted.cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")

        # Copy everything across.
        print("[encrypt] running sqlcipher_export (this may take 30-60s on 100+ MB)...")
        t0 = time.time()
        cur.execute("SELECT sqlcipher_export('encrypted')")
        cur.fetchall()  # consume any result row
        elapsed = time.time() - t0
        print(f"[encrypt] sqlcipher_export done in {elapsed:.1f}s")

        cur.execute("DETACH DATABASE encrypted")
        cur.close()
    finally:
        conn.close()


def verify_encrypted(encrypted_path: Path, key_hex: str) -> dict[str, int]:
    """Open the freshly-encrypted DB with the key and return row counts."""
    from sqlcipher3 import dbapi2 as sqlite

    print(f"[verify] re-opening encrypted DB: {encrypted_path}")
    conn = sqlite.connect(str(encrypted_path))
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        cur.execute("PRAGMA cipher_page_size = 4096")
        cur.execute("PRAGMA kdf_iter = 256000")
        cur.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
        cur.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
        # Force a read to validate the key works.
        cur.execute("SELECT count(*) FROM sqlite_master").fetchone()
        cur.close()
        return _list_tables_with_counts(conn)
    finally:
        conn.close()


def _read_key_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Key file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    return _validate_hex_key(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plaintext", required=True, type=Path, help="Path to existing plaintext SQLite DB")
    parser.add_argument("--encrypted", required=True, type=Path, help="Path to write the encrypted output")
    parser.add_argument("--key-file", required=True, type=Path, help="File containing the 64-char hex key")
    parser.add_argument("--skip-checkpoint", action="store_true", help="Skip PRAGMA wal_checkpoint(FULL) — only safe when the source is offline")
    parser.add_argument("--force", action="store_true", help="Overwrite --encrypted if it exists")
    args = parser.parse_args(argv)

    if not args.plaintext.exists():
        print(f"ERROR: plaintext DB does not exist: {args.plaintext}", file=sys.stderr)
        return 2

    key_hex = _read_key_file(args.key_file)
    print(f"[main] key loaded from {args.key_file} (len={len(key_hex)} hex chars)")

    if args.encrypted.exists():
        if not args.force:
            print(f"ERROR: encrypted target already exists: {args.encrypted} (use --force to overwrite)", file=sys.stderr)
            return 3
        print(f"[main] --force: removing existing target {args.encrypted}")
        args.encrypted.unlink()

    if not args.skip_checkpoint:
        _checkpoint_wal(args.plaintext)

    # Snapshot row counts BEFORE encryption so we can compare AFTER.
    import sqlite3
    src_conn = sqlite3.connect(str(args.plaintext), timeout=30)
    try:
        before_counts = _list_tables_with_counts(src_conn)
    finally:
        src_conn.close()
    print(f"[main] plaintext has {len(before_counts)} tables, total rows = {sum(before_counts.values())}")

    encrypt_db(args.plaintext, args.encrypted, key_hex)
    after_counts = verify_encrypted(args.encrypted, key_hex)

    # Compare. Any table with mismatched count is a HARD FAIL.
    mismatches: list[str] = []
    only_in_before = sorted(set(before_counts) - set(after_counts))
    only_in_after = sorted(set(after_counts) - set(before_counts))
    for tbl in sorted(set(before_counts) & set(after_counts)):
        b, a = before_counts[tbl], after_counts[tbl]
        marker = " " if b == a else "✗"
        print(f"  {marker} {tbl:30s}  before={b:>8d}  after={a:>8d}")
        if b != a:
            mismatches.append(f"{tbl}: {b} → {a}")
    for tbl in only_in_before:
        print(f"  ✗ {tbl:30s}  before={before_counts[tbl]:>8d}  after=MISSING")
        mismatches.append(f"{tbl}: dropped (was {before_counts[tbl]} rows)")
    for tbl in only_in_after:
        print(f"  ! {tbl:30s}  before=MISSING  after={after_counts[tbl]:>8d}")

    if mismatches:
        print("\nERROR: row count mismatches detected:", file=sys.stderr)
        for m in mismatches:
            print(f"  - {m}", file=sys.stderr)
        print(
            "\nThe encrypted DB is INCOMPLETE — DO NOT swap it in. "
            "Investigate before retrying.",
            file=sys.stderr,
        )
        return 4

    plaintext_size = args.plaintext.stat().st_size
    encrypted_size = args.encrypted.stat().st_size
    print(
        f"\n[main] DONE. plaintext={plaintext_size:,} bytes  encrypted={encrypted_size:,} bytes  "
        f"({len(after_counts)} tables, {sum(after_counts.values())} total rows)"
    )
    print("[main] Next step: orchestrator swaps the files + sets AGENTYS_ENCRYPTION_KEY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
