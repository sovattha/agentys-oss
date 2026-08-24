# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression test for the Deepgram total-deadline fix (user report 2026-05-13).

Production observation: one transcribe call dragged out to 30s while
Deepgram was sub-second from elsewhere — Railway↔Deepgram path occasionally
keeps a TCP connection open but stalls between bytes, so requests'
per-byte read timeout never fires. The fix wraps the POST in a hard
threading.Timer deadline that closes the socket past 10s, surfacing the
slowness as an exception so the OpenAI Whisper fallback kicks in.
"""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

import time
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_session():
    """Drop any cached Session between tests so deadline state doesn't leak."""
    from app.api import routes_misc
    routes_misc._dg_session = None
    yield
    routes_misc._dg_session = None


class TestDeepgramDeadline:
    def test_slow_call_triggers_deadline_and_raises(self, monkeypatch):
        """A POST that exceeds the total deadline must raise RuntimeError
        with 'deadline' in the message — letting transcribe_audio fall back
        to OpenAI Whisper instead of making the user wait."""
        from app.api import routes_misc

        # Shrink deadline to 0.3s so the test runs fast.
        monkeypatch.setattr(routes_misc, "_DEEPGRAM_TOTAL_DEADLINE_SEC", 0.3)

        def slow_post(*args, **kwargs):
            # Simulate a request that takes longer than the deadline.
            # The deadline timer will fire and call session.close() which
            # in real life raises a ConnectionError; we mimic that here.
            time.sleep(0.6)
            raise ConnectionError("session closed by deadline")

        with patch("requests.Session.post", side_effect=slow_post):
            with pytest.raises(RuntimeError, match="deadline"):
                routes_misc._call_deepgram(
                    api_key="dg_test",
                    audio_bytes=b"\x00" * 16,
                    content_type="audio/wav",
                    language="fr",
                )

    def test_fast_call_succeeds_and_does_not_reset_session(self, monkeypatch):
        """The happy path must NOT cycle the session — connection pooling
        is meant to be reused across calls when Deepgram is responsive."""
        from app.api import routes_misc

        monkeypatch.setattr(routes_misc, "_DEEPGRAM_TOTAL_DEADLINE_SEC", 5.0)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": {
                "channels": [
                    {"alternatives": [{"transcript": "Bonjour Alex"}]}
                ]
            }
        }

        with patch("requests.Session.post", return_value=mock_response) as mock_post:
            text = routes_misc._call_deepgram(
                api_key="dg_test",
                audio_bytes=b"\x00" * 16,
                content_type="audio/wav",
                language="fr",
            )

        assert text == "Bonjour Alex"
        assert mock_post.called
        # Session reused — same singleton instance.
        assert routes_misc._dg_session is not None

    def test_deadline_resets_session_for_next_call(self, monkeypatch):
        """After a deadline-killed call, the cached session must be
        dropped so the next call opens a fresh TCP pool."""
        from app.api import routes_misc

        monkeypatch.setattr(routes_misc, "_DEEPGRAM_TOTAL_DEADLINE_SEC", 0.2)

        def slow_post(*args, **kwargs):
            time.sleep(0.5)
            raise ConnectionError("session closed by deadline")

        with patch("requests.Session.post", side_effect=slow_post):
            with pytest.raises(RuntimeError, match="deadline"):
                routes_misc._call_deepgram(
                    api_key="dg_test",
                    audio_bytes=b"\x00" * 16,
                    content_type="audio/wav",
                    language="fr",
                )

        # After deadline trip, session must be reset to None.
        assert routes_misc._dg_session is None, (
            "Deepgram session must be reset after deadline trip so the "
            "next call doesn't reuse a broken connection pool"
        )

    def test_non_deadline_exception_propagates(self, monkeypatch):
        """If the request fails fast (e.g. 401, DNS error), the deadline
        timer does NOT fire and the original exception bubbles up — we
        only reset the session when the deadline path actually triggered."""
        from app.api import routes_misc

        monkeypatch.setattr(routes_misc, "_DEEPGRAM_TOTAL_DEADLINE_SEC", 5.0)

        def fast_fail(*args, **kwargs):
            # Fail immediately — not a deadline issue.
            raise ConnectionError("DNS lookup failed")

        with patch("requests.Session.post", side_effect=fast_fail):
            with pytest.raises(ConnectionError, match="DNS lookup failed"):
                routes_misc._call_deepgram(
                    api_key="dg_test",
                    audio_bytes=b"\x00" * 16,
                    content_type="audio/wav",
                    language="fr",
                )

        # Session NOT reset for non-deadline failures (fast errors are
        # likely caller-induced — bad key, no audio — not a stuck pool).
        assert routes_misc._dg_session is not None
