# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Privacy retention and deletion helpers for metadata-only email storage."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import LOGS_DIR

logger = logging.getLogger(__name__)


@dataclass
class PrivacyMaintenanceResult:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def incr(self, key: str, value: int | bool | None = 1) -> None:
        if value is None:
            return
        self.counts[key] = self.counts.get(key, 0) + int(value)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)

    def to_dict(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "warnings": list(self.warnings)}


def _known_account_ids() -> set[int]:
    account_ids: set[int] = set()

    try:
        from app.db.database import get_db_session
        from app.db.models.account import Account

        with get_db_session() as session:
            for row in session.query(Account.id).all():
                account_ids.add(int(row[0]))
    except Exception as exc:
        logger.debug("Privacy retention DB account scan skipped: %s", exc)

    try:
        from app.infrastructure.writing_style_store import FileWritingStyleStore

        account_ids.update(FileWritingStyleStore().list_all())
    except Exception as exc:
        logger.debug("Privacy retention style profile scan skipped: %s", exc)

    try:
        learning_dir = Path(os.path.expanduser("~")) / ".agentys" / "draft_corrections"
        for path in learning_dir.glob("*.json"):
            try:
                account_ids.add(int(path.stem))
            except ValueError:
                continue
    except Exception as exc:
        logger.debug("Privacy retention draft learning scan skipped: %s", exc)

    return account_ids


def redact_application_logs(
    *,
    logs_dir: Path | str = LOGS_DIR,
    max_file_bytes: int = 20 * 1024 * 1024,
) -> int:
    """Rewrite text log files through the same redactor as runtime logs."""
    from app.api.app import _redact_text

    redacted_files = 0
    base = Path(logs_dir)
    if not base.exists():
        return 0

    for path in base.glob("*.log*"):
        if not path.is_file() or path.suffix == ".gz":
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                logger.warning("Skipping large log file during privacy redaction: %s", path)
                continue
            original = path.read_text(encoding="utf-8", errors="replace")
            redacted = _redact_text(original)
            if redacted != original:
                path.write_text(redacted, encoding="utf-8")
                redacted_files += 1
        except OSError as exc:
            logger.warning("Failed to redact log file %s: %s", path, exc)
    return redacted_files


def run_privacy_retention(*, redact_logs: bool = False) -> PrivacyMaintenanceResult:
    """Apply retention across privacy-sensitive file-backed stores."""
    result = PrivacyMaintenanceResult()

    try:
        from app.infrastructure.container import get_container

        store = get_container().get_pending_draft_store()
        prune = getattr(store, "prune_expired", None)
        if callable(prune):
            result.incr("pending_drafts_pruned", prune())
    except Exception as exc:
        result.warn(f"Privacy retention pending drafts skipped: {exc}")

    try:
        from app.draft_correction import get_correction_manager

        result.incr("draft_corrections_pruned", get_correction_manager().prune_expired())
    except Exception as exc:
        result.warn(f"Privacy retention draft corrections skipped: {exc}")

    account_ids = _known_account_ids()
    try:
        from app.draft_learning import get_draft_learning_store

        for account_id in account_ids:
            result.incr(
                "draft_learning_pruned",
                get_draft_learning_store(account_id).prune_expired(),
            )
    except Exception as exc:
        result.warn(f"Privacy retention draft learning skipped: {exc}")

    try:
        from app.infrastructure.writing_style_store import FileWritingStyleStore

        style_store = FileWritingStyleStore()
        for account_id in account_ids:
            profile = style_store.load(account_id)
            if profile is not None and style_store.save(profile):
                result.incr("style_profiles_rewritten", 1)
    except Exception as exc:
        result.warn(f"Privacy retention writing style skipped: {exc}")

    if redact_logs:
        result.incr("log_files_redacted", redact_application_logs())

    return result


def delete_account_privacy_artifacts(
    account_id: int,
    *,
    redact_logs: bool = True,
) -> PrivacyMaintenanceResult:
    """Delete file-backed privacy artifacts for a DB account id."""
    result = PrivacyMaintenanceResult()

    try:
        from app.infrastructure.container import get_container

        store = get_container().get_pending_draft_store()
        delete_by_account = getattr(store, "delete_by_account", None)
        if callable(delete_by_account):
            result.incr("pending_drafts_deleted", delete_by_account(account_id))
    except Exception as exc:
        result.warn(f"Privacy delete pending drafts skipped for account {account_id}: {exc}")

    try:
        from app.infrastructure.writing_style_store import FileWritingStyleStore

        result.incr(
            "style_profiles_deleted",
            FileWritingStyleStore().delete(account_id),
        )
    except Exception as exc:
        result.warn(f"Privacy delete writing style skipped for account {account_id}: {exc}")

    try:
        from app.draft_learning import delete_draft_learning_store

        result.incr(
            "draft_learning_files_deleted",
            delete_draft_learning_store(account_id),
        )
    except Exception as exc:
        result.warn(f"Privacy delete draft learning skipped for account {account_id}: {exc}")

    try:
        from app.draft_correction import get_correction_manager

        deleted = get_correction_manager().delete_by_account(account_id)
        for key, value in deleted.items():
            result.incr(f"draft_correction_{key}_deleted", value)
    except Exception as exc:
        result.warn(f"Privacy delete draft corrections skipped for account {account_id}: {exc}")

    try:
        from app.batch_queue import get_batch_queue

        result.incr("batch_queue_deleted", get_batch_queue().delete_by_account(account_id))
    except Exception as exc:
        result.warn(f"Privacy delete batch queue skipped for account {account_id}: {exc}")

    try:
        from app.services.scheduled_email_store import get_default_store

        result.incr("scheduled_emails_deleted", get_default_store().delete_by_account(account_id))
    except Exception as exc:
        result.warn(f"Privacy delete scheduled emails skipped for account {account_id}: {exc}")

    try:
        from app.infrastructure.container import get_container

        tracker = get_container().get_commitment_tracker()
        delete_by_account = getattr(tracker, "delete_by_account", None)
        if callable(delete_by_account):
            result.incr("commitments_deleted", delete_by_account(account_id))
    except Exception as exc:
        result.warn(f"Privacy delete commitments skipped for account {account_id}: {exc}")

    if redact_logs:
        result.incr("log_files_redacted", redact_application_logs())

    return result


def result_to_json(result: PrivacyMaintenanceResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
