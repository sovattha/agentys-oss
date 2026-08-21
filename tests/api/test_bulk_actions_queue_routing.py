# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Bulk-action queue routing — `/emails/cleanup-all` and `/emails/clean-noise`.

Both endpoints used to bypass the rate-limited bulk-jobs queue:

  - `cleanup-all` emptied trash + spam with a synchronous, blocking
    `provider.permanently_delete()` loop — exactly the 429 /
    partial-silent-failure hazard the queue exists to prevent.
  - `clean-noise` trashed the de-labelled emails on a raw fire-and-forget
    `threading.Thread` (`_trash_noise_emails_bg`) — invisible in Settings
    → Background Tasks, no rate-limit, no retry, lost on a backend restart.

These tests lock in the fix: the provider-side work now goes through
`_enqueue_bulk_job` (the same path the other bulk endpoints use), while
the instant local-only parts (draft purge, Noise label removal) stay
synchronous because they are not provider operations.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ── Minimal Flask app with the shared api_bp mounted ───────────────────
@pytest.fixture
def client(monkeypatch):
    """Test client for the `/api/emails/*` routes.

    Importing `routes_emails` runs its `@api_bp.route` decorators, so the
    `/emails/clean-noise` and `/emails/cleanup-all` handlers land on the
    shared `api_bp`. Cache-invalidation + local-purge helpers are silenced
    here so the tests don't depend on the in-memory cache layer; the
    behaviour under test (queue routing) is patched per-test.
    """
    from app.api.routes_helpers import api_bp
    from app.api import routes_emails  # noqa: F401 — registers /emails/* routes

    for noop in (
        "_invalidate_folder_cache",
        "_invalidate_label_batch_cache",
        "_invalidate_pending_draft_cache",
        "_purge_local_trash_rows",
        "_purge_local_spam_rows",
    ):
        monkeypatch.setattr(
            f"app.api.routes_emails.{noop}", lambda *a, **k: 0, raising=False
        )
    # Reset the manual-cleanup guard so test ordering can't leak it.
    monkeypatch.setattr(
        "app.api.routes_emails._noise_manual_cleanup_running", False,
        raising=False,
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_bp, url_prefix="/api")
    return app.test_client()


# ── /emails/clean-noise ────────────────────────────────────────────────
def test_clean_noise_enqueues_move_to_trash_job(client):
    """Noise labels are removed synchronously; the trashing is enqueued as
    a `move_to_trash` bulk job instead of a raw background thread."""
    from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH

    noise_ids = ["n1", "n2", "n3"]
    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._enqueue_bulk_job", return_value="job-noise-1"
    ) as mock_enqueue:
        label_store = (
            mock_rh._get_container.return_value.get_label_store.return_value
        )
        label_store.get_emails_by_label.return_value = noise_ids
        resp = client.post("/api/emails/clean-noise")

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["accepted"] is True
    assert body["mode"] == "async"
    assert body["job_id"] == "job-noise-1"
    assert body["archived_count"] == 3
    assert body["target_total"] == 3

    # Labels removed synchronously (instant UI clear).
    label_store.bulk_remove_label.assert_called_once()
    # Trashing routed through the queue with the right job type + ids.
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["job_type"] == JOB_TYPE_MOVE_TO_TRASH
    assert list(mock_enqueue.call_args.kwargs["raw_ids"]) == noise_ids


def test_clean_noise_empty_inbox_enqueues_nothing(client):
    """No Noise emails → 200, no bulk job created."""
    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._enqueue_bulk_job"
    ) as mock_enqueue:
        (
            mock_rh._get_container.return_value
            .get_label_store.return_value
            .get_emails_by_label.return_value
        ) = []
        resp = client.post("/api/emails/clean-noise")

    assert resp.status_code == 200
    assert resp.get_json()["archived_count"] == 0
    mock_enqueue.assert_not_called()


def test_mark_noise_read_keeps_labels_and_updates_read_status(client):
    """Marking Noise read is non-destructive: labels stay, only read state changes."""
    noise_ids = ["n1", "n2"]
    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._get_authenticated_provider",
        return_value=MagicMock(),
    ), patch(
        "app.api.routes_emails._bulk_provider_op", return_value=2
    ) as mock_op, patch(
        "app.api.labels._invalidate_labels_cache"
    ) as mock_invalidate_label_counts:
        label_store = (
            mock_rh._get_container.return_value.get_label_store.return_value
        )
        label_store.get_emails_by_label.return_value = noise_ids
        resp = client.post("/api/emails/mark-noise-read")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["updated_count"] == 2
    assert body["is_read"] is True
    label_store.bulk_remove_label.assert_not_called()
    mock_op.assert_called_once()
    mock_rh.EmailRepository.return_value.bulk_update_read_status.assert_called_once_with(
        noise_ids, True, account_id=1
    )
    mock_invalidate_label_counts.assert_called_once_with(account_id=1)


def test_mark_noise_read_async_invalidates_label_counts(client):
    """Large Noise read waves update SQLite optimistically and refresh badges."""
    from app.db.models.bulk_job import JOB_TYPE_MARK_READ

    noise_ids = [f"n{i}" for i in range(12)]
    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._enqueue_bulk_if_above_threshold",
        return_value="job-noise-read-1",
    ) as mock_enqueue, patch(
        "app.api.labels._invalidate_labels_cache"
    ) as mock_invalidate_label_counts:
        label_store = (
            mock_rh._get_container.return_value.get_label_store.return_value
        )
        label_store.get_emails_by_label.return_value = noise_ids
        resp = client.post("/api/emails/mark-noise-read")

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["accepted"] is True
    assert body["mode"] == "async"
    assert body["job_id"] == "job-noise-read-1"
    assert body["target_total"] == len(noise_ids)
    label_store.bulk_remove_label.assert_not_called()
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["job_type"] == JOB_TYPE_MARK_READ
    assert list(mock_enqueue.call_args.kwargs["raw_ids"]) == noise_ids
    mock_rh.EmailRepository.return_value.bulk_update_read_status.assert_called_once_with(
        noise_ids, True, account_id=1
    )
    mock_invalidate_label_counts.assert_called_once_with(account_id=1)


def test_clean_noise_falls_back_to_sync_when_enqueue_unavailable(client):
    """If enqueue can't run (no resolvable account, enqueue raised), the
    emails are still trashed inline so the action completes."""
    noise_ids = ["n1", "n2"]
    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._enqueue_bulk_job", return_value=None
    ), patch(
        "app.api.routes_emails._get_authenticated_provider",
        return_value=MagicMock(),
    ), patch(
        "app.api.routes_emails._bulk_provider_op", return_value=2
    ) as mock_op:
        (
            mock_rh._get_container.return_value
            .get_label_store.return_value
            .get_emails_by_label.return_value
        ) = noise_ids
        resp = client.post("/api/emails/clean-noise")

    assert resp.status_code == 200
    assert resp.get_json()["archived_count"] == 2
    mock_op.assert_called_once()


def test_legacy_trash_noise_thread_helper_is_gone(client):
    """Regression guard: the fire-and-forget `_trash_noise_emails_bg`
    thread helper must not be reintroduced — clean-noise routes through
    the bulk-jobs queue now."""
    from app.api import routes_emails

    assert not hasattr(routes_emails, "_trash_noise_emails_bg")


# ── /emails/cleanup-all ────────────────────────────────────────────────
def test_cleanup_all_enqueues_trash_and_spam_jobs(client):
    """Above INLINE_THRESHOLD (combined), trash → `delete_forever` job and
    spam → `move_to_trash` job; the request answers 202 with both ids."""
    from app.db.models.bulk_job import (
        JOB_TYPE_DELETE_FOREVER,
        JOB_TYPE_MOVE_TO_TRASH,
    )

    trash_ids = [f"t{i}" for i in range(8)]
    spam_ids = [f"s{i}" for i in range(5)]  # 13 combined > INLINE_THRESHOLD (10)

    def _enumerate(account_id, folder):
        return trash_ids if folder == "trash" else spam_ids

    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch(
        "app.api.routes_emails._list_all_email_ids_in_folder",
        side_effect=_enumerate,
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._enqueue_bulk_job",
        side_effect=["job-trash", "job-spam"],
    ) as mock_enqueue:
        (
            mock_rh._get_container.return_value
            .get_pending_draft_store.return_value
            .get_all.return_value
        ) = []
        resp = client.post("/api/emails/cleanup-all")

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["accepted"] is True
    assert body["mode"] == "async"
    assert body["trash_job_id"] == "job-trash"
    assert body["spam_job_id"] == "job-spam"
    assert body["target_total"] == 13

    assert mock_enqueue.call_count == 2
    first, second = mock_enqueue.call_args_list
    assert first.kwargs["job_type"] == JOB_TYPE_DELETE_FOREVER
    assert first.kwargs["raw_ids"] == trash_ids
    assert second.kwargs["job_type"] == JOB_TYPE_MOVE_TO_TRASH
    assert second.kwargs["raw_ids"] == spam_ids


def test_cleanup_all_purges_drafts_synchronously(client):
    """Drafts are local PendingDraft rows, not provider messages — they're
    purged inline and never enqueued, even when trash/spam are empty."""
    draft_a, draft_b = MagicMock(), MagicMock()
    # A plain non-SENT sentinel: `== PendingDraftStatus.SENT` is False, so
    # both drafts proceed to update_status. (A MagicMock status would make
    # the equality check truthy and wrongly skip them.)
    draft_a.status = "draft"
    draft_b.status = "draft"
    draft_a.id, draft_b.id = "d1", "d2"

    with patch(
        "app.api.routes_emails._resolve_account_id_cached", return_value=1
    ), patch(
        "app.api.routes_emails._list_all_email_ids_in_folder", return_value=[]
    ), patch("app.api.routes_emails._rh") as mock_rh, patch(
        "app.api.routes_emails._get_authenticated_provider",
        return_value=MagicMock(),
    ), patch(
        "app.api.routes_emails._enqueue_bulk_job"
    ) as mock_enqueue:
        store = (
            mock_rh._get_container.return_value
            .get_pending_draft_store.return_value
        )
        store.get_all.return_value = [draft_a, draft_b]
        store.update_status.return_value = True
        resp = client.post("/api/emails/cleanup-all")

    assert resp.status_code == 200
    assert resp.get_json()["drafts_deleted"] == 2
    assert store.update_status.call_count == 2
    mock_enqueue.assert_not_called()  # empty folders → nothing to queue
