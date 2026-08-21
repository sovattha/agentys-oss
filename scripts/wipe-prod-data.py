"""Wipe toutes les données utilisateur en prod (Railway).

Usage (depuis ton Mac) :

    # Dry-run : voir ce qui serait supprimé sans rien toucher
    cat scripts/wipe-prod-data.py | railway ssh 'python3 - --dry-run'

    # Exécution réelle
    cat scripts/wipe-prod-data.py | railway ssh 'python3 - --confirm=I_UNDERSTAND'

Périmètre :
    - Purge toutes les tables SQLAlchemy (ordre FK-safe) dans /data/agentys/agentys.db
    - Supprime les fichiers JSON globaux éphémères de /app/data/
      (oauth_tokens.json, pkce_verifiers.json, email_accounts.json, etc.)
    - Préserve known_users.json (sinon il faut refaire un magic link pour
      retrouver l'accès — pas lié à la purge des données)

Ne révoque PAS les tokens OAuth côté Google/Microsoft. L'utilisateur peut
le faire manuellement sur myaccount.google.com si souhaité.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

DB_PATH = "/data/agentys/agentys.db"
APP_DATA_DIR = Path("/app/data")

# Ordre FK-safe : enfants d'abord, accounts en dernier.
# Table absente = skip silencieux (migrations non appliquées → pas critique).
TABLES_ORDERED: list[str] = [
    "email_labels",
    "faq_agent_logs",
    "pending_actions",
    "relationship_overrides",
    "onboarding_results",
    "knowledge_entries",
    "draft_edit_events",
    "recipient_profiles",
    "drafts",
    "contacts",
    "emails",
    "accounts",
]

# Fichiers JSON globaux à supprimer dans /app/data/ (filesystem éphémère).
# known_users.json est VOLONTAIREMENT exclu : sa perte forcerait un magic link
# au re-login, pas le but ici.
JSON_FILES_TO_DELETE: list[str] = [
    "oauth_tokens.json",
    "pkce_verifiers.json",
    "email_accounts.json",
    "history.json",
    ".processed_emails.json",
    "wizard_config.json",
    "contact_groups.json",
]

# Sous-répertoires à vider (on garde la structure, on supprime le contenu).
SUBDIRS_TO_CLEAR: list[str] = [
    "labels",
    "history",
    "inputs",
    "outputs",
    "followups",
    "learning",
    "realtime_edit",
]


def parse_args(argv: list[str]) -> tuple[bool, bool]:
    dry_run = "--dry-run" in argv
    confirmed = "--confirm=I_UNDERSTAND" in argv
    return dry_run, confirmed


def wipe_database(dry_run: bool) -> int:
    if not os.path.exists(DB_PATH):
        print(f"[DB] Fichier introuvable : {DB_PATH} — rien à faire")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    total = 0
    for table in TABLES_ORDERED:
        try:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
        except sqlite3.OperationalError as e:
            print(f"[DB] {table:30s} skip ({e})")
            continue

        if count == 0:
            print(f"[DB] {table:30s} 0 rows")
            continue

        if dry_run:
            print(f"[DB] {table:30s} {count} rows (dry-run — non supprimés)")
        else:
            conn.execute(f"DELETE FROM {table}")
            print(f"[DB] {table:30s} {count} rows supprimés")
        total += count

    if not dry_run:
        conn.commit()
    conn.close()
    return total


def wipe_json_files(dry_run: bool) -> int:
    if not APP_DATA_DIR.exists():
        print(f"[FS] {APP_DATA_DIR} n'existe pas — rien à faire")
        return 0

    deleted = 0
    for name in JSON_FILES_TO_DELETE:
        path = APP_DATA_DIR / name
        if not path.exists():
            print(f"[FS] {name:30s} absent")
            continue
        if dry_run:
            print(f"[FS] {name:30s} présent (dry-run — non supprimé)")
        else:
            path.unlink()
            print(f"[FS] {name:30s} supprimé")
        deleted += 1

    for subdir in SUBDIRS_TO_CLEAR:
        path = APP_DATA_DIR / subdir
        if not path.exists() or not path.is_dir():
            print(f"[FS] {subdir}/{'':28s} absent")
            continue
        file_count = sum(1 for f in path.rglob("*") if f.is_file())
        if file_count == 0:
            print(f"[FS] {subdir}/{'':28s} vide")
            continue
        if dry_run:
            print(f"[FS] {subdir}/{'':28s} {file_count} fichiers (dry-run)")
        else:
            shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            print(f"[FS] {subdir}/{'':28s} {file_count} fichiers supprimés")
        deleted += file_count

    return deleted


def main(argv: list[str]) -> int:
    dry_run, confirmed = parse_args(argv)

    if not dry_run and not confirmed:
        print("REFUS : flag manquant.")
        print("  --dry-run                 pour voir ce qui serait supprimé")
        print("  --confirm=I_UNDERSTAND    pour exécuter la purge réelle")
        return 2

    mode = "DRY-RUN" if dry_run else "WIPE RÉEL"
    print(f"=== {mode} — Purge prod Agentys ===")
    print()

    print("1) Tables DB")
    db_rows = wipe_database(dry_run)
    print()

    print("2) Fichiers JSON globaux")
    fs_items = wipe_json_files(dry_run)
    print()

    print(f"=== {mode} terminé : {db_rows} rows DB, {fs_items} fichiers FS ===")
    if dry_run:
        print("Relance sans --dry-run (avec --confirm=I_UNDERSTAND) pour appliquer.")
    else:
        print("Redémarre le backend si nécessaire : `railway restart`")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
