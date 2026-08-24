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

"""
Migration one-shot : memoire.md → DB structurée per-user.

Ce script :
1. Lit knowledge/memoire.md
2. Parse via parse_knowledge_markdown()
3. Écrit en DB pour le compte principal (premier compte)
4. Renomme memoire.md en memoire.md.migrated.bak

Usage:
    python scripts/migrate_memoire_to_db.py
    python scripts/migrate_memoire_to_db.py --dry-run
    python scripts/migrate_memoire_to_db.py --account-id 2

Epic #134, issue #158.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import KNOWLEDGE_DIR
from app.onboarding.manager import parse_knowledge_markdown, build_knowledge_markdown

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_primary_account_id() -> int | None:
    """Find the first account in the DB."""
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    with get_db_session() as session:
        repo = AccountRepository(session)
        accounts = repo.get_all()
        if accounts:
            return accounts[0].id
    return None


def migrate(account_id: int | None = None, dry_run: bool = False) -> bool:
    """Run the migration."""
    memoire_path = Path(KNOWLEDGE_DIR) / "memoire.md"

    if not memoire_path.exists():
        logger.warning("memoire.md not found at %s — nothing to migrate", memoire_path)
        return False

    # Step 1: Read
    content = memoire_path.read_text(encoding="utf-8")
    logger.info("Read memoire.md: %d chars, %d lines", len(content), content.count("\n"))

    # Step 2: Parse
    profile, knowledge, rules = parse_knowledge_markdown(content)
    logger.info(
        "Parsed: profile=%d keys, knowledge=%d keys, rules=%d keys",
        len(profile), len(knowledge), len(rules),
    )

    # Verify round-trip
    rebuilt = build_knowledge_markdown(profile, knowledge, rules)
    logger.info("Round-trip rebuild: %d chars (original: %d)", len(rebuilt), len(content))

    # Step 3: Resolve account
    if not account_id:
        account_id = get_primary_account_id()
    if not account_id:
        logger.error("No account found in DB. Run onboarding first or use --account-id.")
        return False

    logger.info("Target account_id: %d", account_id)

    if dry_run:
        logger.info("[DRY RUN] Would write to DB and rename memoire.md")
        logger.info("[DRY RUN] Profile: %s", json.dumps(profile, ensure_ascii=False)[:200])
        logger.info("[DRY RUN] Knowledge keys: %s", list(knowledge.keys()))
        logger.info("[DRY RUN] Rules keys: %s", list(rules.keys()))
        return True

    # Step 4: Write to DB
    from app.db.database import get_db_session
    from app.db.repositories.onboarding_repository import OnboardingRepository

    with get_db_session() as session:
        repo = OnboardingRepository(session)
        result = repo.get_completed_by_account(account_id)

        if result:
            result.profile_json = json.dumps(profile, ensure_ascii=False)
            result.knowledge_json = json.dumps(knowledge, ensure_ascii=False)
            result.rules_json = json.dumps(rules, ensure_ascii=False)
            session.commit()
            logger.info("Updated existing onboarding result in DB for account %d", account_id)
        else:
            logger.warning(
                "No completed onboarding found for account %d. "
                "The data will be available next time onboarding runs.",
                account_id,
            )

    # Step 5: Rename file
    backup_path = memoire_path.with_suffix(".md.migrated.bak")
    memoire_path.rename(backup_path)
    logger.info("Renamed %s → %s", memoire_path.name, backup_path.name)

    logger.info("Migration complete for account %d", account_id)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate memoire.md to DB")
    parser.add_argument("--dry-run", action="store_true", help="Parse and show results without writing")
    parser.add_argument("--account-id", type=int, default=None, help="Target account ID (default: first account)")
    args = parser.parse_args()

    success = migrate(account_id=args.account_id, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
