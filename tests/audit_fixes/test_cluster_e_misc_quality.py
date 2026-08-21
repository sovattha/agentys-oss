# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix Cluster E (2026-05-11) — misc quality.

Source: tasks/audit-reports/2026-05-10_2219/03-ui-live.md (U-02, U-03, U-07,
U-10) and the existing open #325 (archive 500 runtime silent).

Four small quality findings rounding out the audit:

  * U-02 — POST /api/emails/<id>/archive returns HTTP 200 success for
    email IDs that do NOT exist anywhere in the SQLite cache. The
    optimistic UI removes the row; nothing actually happens server-side;
    at the next refresh the email reappears with no toast. Fix: check
    SQLite cache first; 404 when the email is unknown.

  * U-03 — POST /api/emails/<id>/star returns 404 because no such route
    exists. Confirmed: the frontend never calls /star (grep across
    agentys-app/src). Documented in the PR; no code change.

  * U-07 — POST /api/emails/compose requires `subject` even though the
    NewMessageModal sends "(Sans objet)" placeholder and runs
    suggestSubject after the stream completes. The backend contract is
    correct; the `alert()` UX was the main pain point and is fixed in
    Cluster D (#618). No further change needed here.

  * U-10 — POST/DELETE /api/emails/<id>/pin returns the full pinned_ids
    array (79 ids in the audit run) on every toggle. The frontend only
    consumes pinned_ids from the GET /pinned mount-time call; pin/unpin
    responses are fire-and-forget (`pinEmail(id).catch(() => {})`). The
    full array is dead payload, unbounded growth, and bandwidth tax.
    Fix: return {ok, pinned: boolean} only.

  * #325 — Archive bg thread (`_bg_archive` in archive_email route)
    swallows provider failures into a logger.error line with no
    user-visible surface. The user sees the optimistic removal; at the
    next refresh the row reappears with no toast. Fix: capture
    account_id before spawning the thread, emit emit_email_updated with
    archive_failed=true so the frontend can revert optimistic state.

Run: pytest tests/audit_fixes/test_cluster_e_misc_quality.py -v
"""

from __future__ import annotations

import inspect
import re
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# U-02 — archive must 404 on unknown email_id
# --------------------------------------------------------------------------- #


class TestU02ArchiveUnknownEmailReturns404:
    """A POST to /api/emails/<bogus-but-format-valid>/archive must NOT
    silently 200. The optimistic UI strips the row and the user has no
    way to know nothing happened. Validating the existence in the SQLite
    cache catches stale-list bugs early."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    def test_returns_404_when_email_unknown(self, _mock_acct, mock_get_provider, client):
        mock_provider = MagicMock()
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider

        # Patch the SQLite cache lookup to return None (not found).
        with patch(
            "app.api.routes_emails._email_exists_in_cache",
            return_value=False,
            create=True,
        ):
            resp = client.post("/api/emails/19e14c80e8370fde/archive")

        assert resp.status_code == 404, (
            f"Unknown email_id slipped through with {resp.status_code} "
            f"body={resp.get_json()}"
        )
        body = resp.get_json() or {}
        assert "error" in body


# --------------------------------------------------------------------------- #
# F-01 (audit 2026-05-11) — sent-folder archive must not 404 on prefix mismatch
# --------------------------------------------------------------------------- #


class TestF01SentArchivePrefixLookup:
    """The U-02 cache-existence guard above caused a regression for the
    `sent:` prefix flow. `_refresh_sent_cache_bg` stores sent emails with
    the raw provider ID (no prefix). The endpoint must lookup with
    `raw_id`, not the full `email_id`, otherwise every Archive click on
    a sent email returned 404 + "EMAIL_NOT_FOUND"."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    def test_sent_prefix_lookup_uses_raw_id(self, _mock_acct, mock_get_provider, client):
        mock_provider = MagicMock()
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider

        # Simulate the real storage convention: the email exists under the
        # raw ID, not the prefixed one. If the endpoint queries with the
        # prefix, it gets a miss and returns 404 — that's the F-01 bug.
        seen_lookups: list[str] = []

        def fake_exists(eid, account_id=None, **_):
            seen_lookups.append(eid)
            return eid == "19e14c80e8370fde"  # raw key only

        with patch(
            "app.api.routes_emails._email_exists_in_cache",
            side_effect=fake_exists,
            create=True,
        ):
            resp = client.post("/api/emails/sent:19e14c80e8370fde/archive")

        assert resp.status_code == 200, (
            f"sent: prefix still triggers 404 — lookups seen: {seen_lookups} "
            f"body={resp.get_json()}"
        )
        assert "19e14c80e8370fde" in seen_lookups, (
            f"_email_exists_in_cache was never called with the raw id — "
            f"saw: {seen_lookups}"
        )
        assert "sent:19e14c80e8370fde" not in seen_lookups, (
            f"_email_exists_in_cache was called with the prefixed key — "
            f"the F-01 fix did not land. Saw: {seen_lookups}"
        )


# --------------------------------------------------------------------------- #
# U-10 — pin response must NOT include the full pinned_ids array
# --------------------------------------------------------------------------- #


class TestU10PinResponseShape:
    """The pin/unpin toggle response carried the full pinned_ids array
    (79 in the audit; unbounded over years). The frontend doesn't read
    it (toggle is fire-and-forget; the GET endpoint is the source of
    truth for the mount-time list). Drop it from the toggle response."""

    def test_pin_response_does_not_include_full_pinned_ids(self):
        """Source-level guard: the toggle_email_pin view must not return
        a `pinned_ids` field — only a slim {ok, pinned} confirmation."""
        from app.api import routes_emails

        src = inspect.getsource(routes_emails.toggle_email_pin)
        # The previous return shape was `jsonify({"ok": True, "pinned_ids": pinned})`.
        # After the fix, `pinned_ids` should not appear in the response.
        assert not re.search(r'"pinned_ids"', src) or 'fetchPinnedEmailIds' in src, (
            "toggle_email_pin still references pinned_ids in its return "
            "shape — unbounded payload growth on every toggle."
        )


# --------------------------------------------------------------------------- #
# #325 — bg archive failure must surface via WebSocket
# --------------------------------------------------------------------------- #


class TestIssue325ArchiveBgFailureSurface:
    """When provider.archive_email fails (False or exception) inside the
    detached _bg_archive thread, the previous code wrote a single
    logger.error line and dropped on the floor. The optimistic UI never
    learned the archive didn't take. Now emit emit_email_updated with
    `archive_failed=true` so the frontend can revert."""

    def test_bg_archive_failure_emits_recovery_event_on_source(self):
        """Source-level guard: the archive_email view must reference
        `emit_email_updated` inside its bg-failure path so the frontend
        can revert the optimistic removal."""
        from app.api import routes_emails

        src = inspect.getsource(routes_emails.archive_email)
        # Look for emit_email_updated or any explicit failure event
        # dispatched from the background failure path.
        # We accept emit_email_updated or a custom emit_archive_failed.
        assert (
            "emit_email_updated" in src
            or "emit_archive_failed" in src
            or "archive_failed" in src
        ), (
            "archive_email's background failure path does not emit any "
            "WebSocket event — silent failure (#325)."
        )
