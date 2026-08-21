# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
One-shot migration : copy each account's legacy
``WritingStyleProfile.contact_profiles`` dict (persisted in
``data/learning/style_profile_<account_id>.json``) into the SQLite
``contact_styles`` table managed by :class:`SqliteContactStyleStore`.

Called from :func:`app.api.app.create_app` at boot, and exposed as
:func:`migrate_all_accounts_at_boot` so a standalone admin script can
trigger the same logic without spinning up Flask.

Properties
----------
- **Idempotent** : ``replace_account`` clears all rows for an account before
  re-inserting, so re-running on every boot converges to the same state. No
  marker file or "already migrated" flag is needed.
- **Bounded boot cost** : one DB transaction per account profile JSON found.
  Typical install = 1-3 accounts → < 200ms total.
- **Non-fatal** : individual account failures are logged but the migration
  continues with the next account. The caller (Flask boot) wraps this in
  another try/except so any global failure is also non-fatal.
- **Pure read of the JSON layer** — does NOT mutate the JSON profile files.
  The next ``WritingStyleProfile.to_dict()`` cycle will re-emit the JSON
  with the same ``contact_profiles`` payload (snapshot of the SQLite state),
  so the on-disk file remains valid through the transition.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


_PROFILE_FILE_GLOB = "style_profile_*.json"


def _resolve_learning_dir() -> Optional[Path]:
    """Find the directory holding ``style_profile_<account_id>.json`` files.

    Resolves via the Container so the path matches whatever
    :class:`FileWritingStyleStore` is configured with (default
    ``<data_dir>/learning/``).
    """
    try:
        from app.infrastructure.container import get_container

        store = get_container().get_writing_style_store()
        # ``FileWritingStyleStore`` exposes ``_data_dir``. Use ``getattr`` so
        # alternative store implementations (e.g. memory-backed for tests)
        # don't break the resolution.
        return getattr(store, "_data_dir", None)
    except Exception:
        return None


def _list_profile_files(learning_dir: Path) -> List[Path]:
    if not learning_dir.exists() or not learning_dir.is_dir():
        return []
    return sorted(learning_dir.glob(_PROFILE_FILE_GLOB))


def _account_id_from_filename(path: Path) -> Optional[int]:
    """Extract the integer account_id from ``style_profile_<id>.json``.

    Returns None when the filename doesn't match the expected pattern so a
    stray file in the directory can't crash the migration.
    """
    stem = path.stem  # e.g. "style_profile_42"
    parts = stem.split("_")
    if len(parts) < 3 or parts[0] != "style" or parts[1] != "profile":
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def migrate_account(account_id: int) -> int:
    """Migrate one account's ``contact_profiles`` dict into SQLite.

    Returns the number of contact rows written. Returns 0 on any failure or
    when the account has no contacts to migrate.
    """
    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.contact_style_store_sqlite import (
            migrate_json_to_sqlite,
        )

        container = get_container()
        wstore = container.get_writing_style_store()
        cstore = container.get_contact_style_store()

        profile = wstore.load(account_id)
        if profile is None:
            return 0
        # The view's ``snapshot()`` materialises whatever the entity now
        # holds — for a freshly-loaded profile that's the JSON's
        # ``contact_profiles`` dict (passed through ``__post_init__``).
        legacy_dict = profile.contact_profiles.snapshot()
        if not legacy_dict:
            return 0
        return migrate_json_to_sqlite(
            account_id=account_id,
            contact_profiles_dict=legacy_dict,
            store=cstore,
        )
    except Exception as exc:
        logger.warning(
            "contact_profiles migration failed for account %s: %s",
            account_id, exc,
        )
        return 0


def migrate_all_accounts_at_boot() -> int:
    """Walk the learning directory, migrate every profile JSON found, and
    return the total number of contact rows written across all accounts.

    Designed to be called once from :func:`app.api.app.create_app`. Safe to
    invoke on every boot — idempotent.
    """
    learning_dir = _resolve_learning_dir()
    if learning_dir is None:
        logger.debug(
            "contact_profiles migration skipped : learning dir not resolvable"
        )
        return 0

    files = _list_profile_files(learning_dir)
    if not files:
        return 0

    total = 0
    migrated_accounts: List[int] = []
    for path in files:
        account_id = _account_id_from_filename(path)
        if account_id is None:
            logger.debug(
                "Skipping malformed profile filename : %s", path.name
            )
            continue
        n = migrate_account(account_id)
        if n > 0:
            total += n
            migrated_accounts.append(account_id)

    if total > 0:
        logger.info(
            "contact_profiles → SQLite migration : %d rows across %d account(s) %s",
            total, len(migrated_accounts), migrated_accounts,
        )
    return total
