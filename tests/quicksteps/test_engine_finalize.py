# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the engine's `finalize()` cache contract.

The first ship of the engine cached the report only on post-execution
outcomes (chain-success or action-failure). Pre-execute exits — empty
actions, provider unavailable, email not found, template typo — bypassed
the cache, so the same idempotency key replayed the failure path instead
of returning a cached report. Caught by a live PowerShell probe during the
2026-05-06 audit; these tests lock in the fix.
"""
from __future__ import annotations

from unittest.mock import MagicMock


from app.quicksteps import engine
from app.quicksteps.idempotency import MemoryIdempotencyStore


def _step(actions=None):
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "test",
        "actions": actions if actions is not None else [{"type": "archive"}],
        "enabled": True,
    }


def _run(*, step, store, idem_key="K", email_loader=None, provider_factory=None):
    return engine.execute(
        account_id=1,
        step=step,
        email_id="msg-1",
        idempotency_key=idem_key,
        provider_factory=provider_factory or (lambda: MagicMock()),
        email_loader=email_loader or (lambda *_: MagicMock()),
        account_loader=lambda _aid: ("u@x", "U"),
        idempotency_store=store,
    )


# --------------------------------------------------------------------------- #
# Each pre-execute exit path must cache so a retry replays.
# --------------------------------------------------------------------------- #

class TestPreExecuteFailuresCached:
    def test_no_actions_replays(self):
        store = MemoryIdempotencyStore()
        first = _run(step=_step(actions=[]), store=store)
        second = _run(step=_step(actions=[]), store=store)
        assert first.error == "no_actions"
        assert second.idempotent_replay is True
        assert second.error == "no_actions"

    def test_provider_unavailable_replays(self):
        store = MemoryIdempotencyStore()

        def boom():
            raise RuntimeError("no token")

        first = _run(step=_step(), store=store, provider_factory=boom)
        second = _run(step=_step(), store=store, provider_factory=boom)
        assert "provider_unavailable" in (first.error or "")
        assert second.idempotent_replay is True

    def test_email_not_found_replays(self):
        store = MemoryIdempotencyStore()
        first = _run(step=_step(), store=store, email_loader=lambda *_: None)
        second = _run(step=_step(), store=store, email_loader=lambda *_: None)
        assert first.error == "email_not_found"
        assert second.idempotent_replay is True

    def test_email_load_exception_replays(self):
        store = MemoryIdempotencyStore()

        def loader(*_):
            raise ConnectionError("imap down")

        first = _run(step=_step(), store=store, email_loader=loader)
        second = _run(step=_step(), store=store, email_loader=loader)
        assert (first.error or "").startswith("email_load_failed")
        assert second.idempotent_replay is True

    def test_template_unknown_var_replays(self):
        # Variable typo — engine pre-flight rejects without hitting providers.
        store = MemoryIdempotencyStore()
        bad_step = _step(actions=[{
            "type": "reply_template",
            "payload": {
                "body": "Hi {sendr.firstname}",  # typo
                "replyAll": False,
                "includeQuoted": True,
            },
        }])
        first = _run(step=bad_step, store=store)
        second = _run(step=bad_step, store=store)
        assert (first.error or "").startswith("template_unknown_variables")
        assert second.idempotent_replay is True


# --------------------------------------------------------------------------- #
# HTTPException(404) raised by the provider must be classified as
# email_not_found, not as a generic email_load_failed.
# --------------------------------------------------------------------------- #

class TestHTTPException404Classification:
    def test_werkzeug_404_translates_to_email_not_found(self):
        from werkzeug.exceptions import HTTPException

        class Notfound(HTTPException):
            code = 404
            description = "??? Unknown Error: None"

        store = MemoryIdempotencyStore()

        def loader(*_):
            raise Notfound()

        report = _run(step=_step(), store=store, email_loader=loader)
        assert report.error == "email_not_found"

    def test_abort_with_response_translates_to_email_not_found(self):
        # The shape `_get_email_by_id` actually raises in production:
        # `abort(make_response(jsonify(...), 404))` — HTTPException.code is None
        # and the 404 lives on exc.response.status_code.
        from werkzeug.exceptions import HTTPException
        from werkzeug.wrappers import Response

        class WrappedAbort(HTTPException):
            code = None  # ← intentionally None, mirroring the prod shape

        store = MemoryIdempotencyStore()

        def loader(*_):
            exc = WrappedAbort()
            exc.response = Response(b'{"error":"Email not found"}', status=404)
            raise exc

        report = _run(step=_step(), store=store, email_loader=loader)
        assert report.error == "email_not_found"

    def test_generic_exception_keeps_email_load_failed(self):
        store = MemoryIdempotencyStore()

        def loader(*_):
            raise RuntimeError("ssl handshake failed")

        report = _run(step=_step(), store=store, email_loader=loader)
        assert (report.error or "").startswith("email_load_failed")

    def test_string_not_found_in_message_also_translates(self):
        store = MemoryIdempotencyStore()

        def loader(*_):
            raise RuntimeError("Message not found")

        report = _run(step=_step(), store=store, email_loader=loader)
        assert report.error == "email_not_found"
