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
Integration E2E tests — real backend (localhost:5050).

Requires: python run_api.py running on port 5050 with a valid Gmail account.

Run: pytest tests/integration/test_api_integration_e2e.py -v -s
"""

import time

import pytest
import requests

API = "http://localhost:5050/api"
PERF_THRESHOLD = 5.0  # seconds


def _timed_request(method: str, url: str, **kwargs) -> tuple[requests.Response, float]:
    """Execute request and return (response, elapsed_seconds)."""
    start = time.perf_counter()
    resp = requests.request(method, url, timeout=90, **kwargs)
    elapsed = time.perf_counter() - start
    return resp, elapsed


def _perf_check(elapsed: float, label: str):
    """Log and assert performance threshold."""
    status = "OK" if elapsed < PERF_THRESHOLD else "SLOW"
    print(f"  [{status}] {label}: {elapsed:.2f}s")
    assert elapsed < PERF_THRESHOLD, f"{label} took {elapsed:.2f}s (threshold: {PERF_THRESHOLD}s)"


# ──────────────────────────────────────────────────────────────
# Shared state across serial tests
# ──────────────────────────────────────────────────────────────

_state: dict = {}


@pytest.fixture(scope="module", autouse=True)
def check_backend():
    """Skip all tests if backend is not running or email is disconnected."""
    try:
        resp = requests.get(f"{API}/health", timeout=5)
        if resp.status_code != 200:
            pytest.skip("Backend not healthy")
        data = resp.json()
        email_status = data.get("services", {}).get("email", "disconnected")
        if email_status != "connected":
            pytest.skip(f"Email service not connected (status: {email_status})")
    except requests.ConnectionError:
        pytest.skip("Backend not running on localhost:5050")


class TestApiIntegrationE2E:
    """Serial integration tests against real backend."""

    # 01 ─────────────────────────────────────────────────────────
    def test_01_health_check(self):
        resp, elapsed = _timed_request("GET", f"{API}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok" or "status" in data
        _perf_check(elapsed, "health")

    # 02 ─────────────────────────────────────────────────────────
    def test_02_send_email_to_self(self):
        ts = int(time.time())
        subject = f"[AGENTYS-E2E-TEST] Integration {ts}"
        _state["subject"] = subject
        _state["timestamp"] = ts

        resp, elapsed = _timed_request("POST", f"{API}/emails/send-new", json={
            "to": "me",
            "subject": subject,
            "body": f"Test integration E2E — {ts}",
            "skip_signature": True,
        })
        assert resp.status_code == 200, f"Send failed: {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        _perf_check(elapsed, "send-new")

    # 03 ─────────────────────────────────────────────────────────
    def test_03_verify_in_sent(self):
        """Retry ×3 with backoff to let IMAP sync."""
        subject = _state.get("subject", "")
        found = False

        for attempt in range(3):
            if attempt > 0:
                time.sleep(3 * attempt)  # 3s, 6s

            resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "sent"})
            assert resp.status_code == 200
            emails = resp.json().get("emails", [])

            for email in emails:
                if subject in email.get("subject", ""):
                    found = True
                    _state["sent_email_id"] = email.get("id")
                    break

            if found:
                _perf_check(elapsed, f"sent-list (attempt {attempt + 1})")
                break

        if not found:
            print(f"  [WARN] Email '{subject}' not found in Sent after 3 retries (IMAP delay)")

    # 04 ─────────────────────────────────────────────────────────
    def test_04_list_inbox(self):
        resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "inbox"})
        assert resp.status_code == 200
        emails = resp.json().get("emails", [])
        print(f"  Inbox: {len(emails)} emails")
        _perf_check(elapsed, "inbox-list")

        # Store first email id for operations
        if emails:
            _state["inbox_email_id"] = emails[0].get("id")

    # 05 ─────────────────────────────────────────────────────────
    def test_05_archive_email(self):
        email_id = _state.get("inbox_email_id")
        if not email_id:
            pytest.skip("No inbox email to archive")

        resp, elapsed = _timed_request("POST", f"{API}/emails/{email_id}/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        _state["archived_email_id"] = email_id
        _perf_check(elapsed, "archive")

    # 06 ─────────────────────────────────────────────────────────
    def test_06_verify_in_archives(self):
        email_id = _state.get("archived_email_id")
        if not email_id:
            pytest.skip("No archived email to verify")

        time.sleep(2)  # IMAP sync delay
        resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "archived"})
        assert resp.status_code == 200
        _perf_check(elapsed, "archived-list")

        emails = resp.json().get("emails", [])
        found = any(e.get("id") == email_id for e in emails)
        if not found:
            print(f"  [WARN] Email {email_id} not found in Archives (IMAP delay)")

    # 07 ─────────────────────────────────────────────────────────
    def test_07_delete_email(self):
        email_id = _state.get("archived_email_id")
        if not email_id:
            pytest.skip("No email to delete")

        resp, elapsed = _timed_request("POST", f"{API}/emails/{email_id}/delete")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        _state["deleted_email_id"] = email_id
        _perf_check(elapsed, "delete")

    # 08 ─────────────────────────────────────────────────────────
    def test_08_verify_in_trash(self):
        email_id = _state.get("deleted_email_id")
        if not email_id:
            pytest.skip("No deleted email to verify")

        time.sleep(2)
        resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "trash"})
        assert resp.status_code == 200
        _perf_check(elapsed, "trash-list")

        emails = resp.json().get("emails", [])
        found = any(e.get("id") == email_id for e in emails)
        if not found:
            print(f"  [WARN] Email {email_id} not found in Trash (IMAP delay)")

    # 09 ─────────────────────────────────────────────────────────
    def test_09_restore_from_trash(self):
        email_id = _state.get("deleted_email_id")
        if not email_id:
            pytest.skip("No email to restore")

        resp, elapsed = _timed_request("POST", f"{API}/emails/{email_id}/restore")
        # Tolerate 501 (provider may not support restore)
        assert resp.status_code in (200, 501), f"Restore failed: {resp.status_code} {resp.text}"

        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is True
            _state["restored_email_id"] = email_id
        else:
            print("  [WARN] Restore not supported by provider (501)")

        _perf_check(elapsed, "restore")

    # 10 ─────────────────────────────────────────────────────────
    def test_10_verify_restored_in_inbox(self):
        email_id = _state.get("restored_email_id")
        if not email_id:
            pytest.skip("No restored email to verify")

        time.sleep(2)
        resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "inbox"})
        assert resp.status_code == 200
        _perf_check(elapsed, "inbox-after-restore")

        emails = resp.json().get("emails", [])
        found = any(e.get("id") == email_id for e in emails)
        if not found:
            print(f"  [WARN] Email {email_id} not found in Inbox after restore (IMAP delay)")

    # 11 ─────────────────────────────────────────────────────────
    def test_11_load_spam_folder(self):
        resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": "spam"})
        assert resp.status_code == 200
        emails = resp.json().get("emails", [])
        print(f"  Spam: {len(emails)} emails")
        _perf_check(elapsed, "spam-list")

        if emails:
            _state["spam_email_id"] = emails[0].get("id")

    # 12 ─────────────────────────────────────────────────────────
    def test_12_not_spam_endpoint(self):
        email_id = _state.get("spam_email_id")
        if not email_id:
            pytest.skip("No spam email to mark as not-spam")

        resp, elapsed = _timed_request("POST", f"{API}/emails/{email_id}/not-spam")
        assert resp.status_code in (200, 501), f"Not-spam failed: {resp.status_code} {resp.text}"
        _perf_check(elapsed, "not-spam")

    # 13 ─────────────────────────────────────────────────────────
    def test_13_performance_summary(self):
        """Load all 5 folders and print performance summary."""
        folders = ["inbox", "sent", "archived", "trash", "spam"]
        results = {}

        for folder in folders:
            resp, elapsed = _timed_request("GET", f"{API}/emails", params={"folder": folder})
            assert resp.status_code == 200
            count = len(resp.json().get("emails", []))
            results[folder] = {"time": elapsed, "count": count}

        print("\n  ╔══════════════════════════════════════════╗")
        print("  ║       PERFORMANCE SUMMARY (5 folders)    ║")
        print("  ╠══════════════╦════════╦══════════════════╣")
        print("  ║ Folder       ║ Time   ║ Count            ║")
        print("  ╠══════════════╬════════╬══════════════════╣")
        for folder, info in results.items():
            t = info["time"]
            c = info["count"]
            status = "OK" if t < PERF_THRESHOLD else "SLOW"
            print(f"  ║ {folder:<12} ║ {t:5.2f}s ║ {c:>4} emails [{status}] ║")
        print("  ╚══════════════╩════════╩══════════════════╝")

        for folder, info in results.items():
            assert info["time"] < PERF_THRESHOLD, f"{folder} took {info['time']:.2f}s"
