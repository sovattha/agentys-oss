# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Text-only emoji marker — wires up the "No emoji" picker tile end-to-end.

The picker (`QuickStepsManager.tsx`) lets users build chips with just text
by selecting the slashed-circle "No emoji" tile. That ships emoji="" in the
payload. Three pieces have to cooperate or the chip silently vanishes:

  1. ``schema.validate_quick_step`` — accept empty emoji when text is present
     (covered by ``test_schema.py``).
  2. ``handle_mark_with_emoji`` — write the marker without an "emoji" key
     when emoji is empty (this file).
  3. ``Email._decode_emoji_marker`` — surface the text-only marker in API
     responses instead of dropping it (this file).

Both (2) and (3) used to require a truthy ``emoji`` and would have rejected
or dropped a text-only marker, so this is the contract we lock in here.
"""
from __future__ import annotations

import json
import threading

import pytest

from app.db.models.email import _decode_emoji_marker
from app.quicksteps.handlers.mark_with_emoji import handle_mark_with_emoji
from app.quicksteps.types import ExecutionContext


# --------------------------------------------------------------------------- #
# Handler — text-only marker round-trips through the SQL write
# --------------------------------------------------------------------------- #

class _FakeRow:
    emoji_marker_json = None


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        return None


class _FakeRepoForWrite:
    last_row: _FakeRow | None = None

    def __init__(self, _session):
        pass

    def get_by_email_id(self, eid, account_id=None):
        row = _FakeRow()
        _FakeRepoForWrite.last_row = row
        return row


@pytest.fixture
def _patched_io(monkeypatch):
    """Stub the SQL + cache + websocket I/O so the handler runs in isolation."""
    import app.api.routes_helpers as _rh
    import app.db.repositories.email_repository as _er
    import app.api.websocket as _ws

    _FakeRepoForWrite.last_row = None
    monkeypatch.setattr(_rh, "get_db_session", lambda: _FakeSession())
    monkeypatch.setattr(_er, "EmailRepository", _FakeRepoForWrite)
    monkeypatch.setattr(_ws, "emit_email_updated", lambda *a, **kw: None)
    monkeypatch.setattr(_rh, "_invalidate_folder_cache", lambda: None)
    monkeypatch.setattr(_rh, "_invalidate_label_batch_cache", lambda: None)
    monkeypatch.setattr(_rh, "_email_detail_cache", {})
    monkeypatch.setattr(_rh, "_email_detail_cache_lock", threading.Lock())
    return _FakeRepoForWrite


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        provider=None,
        account_id=42,
        account_email="me@x.com",
        account_display_name="Me",
        email=None,
        email_id="msg-1",
        raw_id="msg-1",
    )


class TestHandlerTextOnly:
    def test_empty_emoji_with_text_writes_text_only_marker(self, _patched_io):
        result = handle_mark_with_emoji(_ctx(), {"emoji": "", "text": "Follow-up"})

        assert result.ok is True, f"handler should succeed: {result.error}"
        row = _FakeRepoForWrite.last_row
        assert row is not None
        parsed = json.loads(row.emoji_marker_json)
        assert "emoji" not in parsed, "text-only marker should omit the emoji key"
        assert parsed["text"] == "Follow-up"

    def test_missing_emoji_key_with_text_works(self, _patched_io):
        # Payload from a client that doesn't even send `emoji` — still valid.
        result = handle_mark_with_emoji(_ctx(), {"text": "Follow-up"})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert "emoji" not in parsed
        assert parsed["text"] == "Follow-up"

    def test_text_only_with_include_deadline_preserved(self, _patched_io):
        result = handle_mark_with_emoji(
            _ctx(), {"emoji": "", "text": "Due", "include_deadline": True}
        )

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed == {"text": "Due", "include_deadline": True}

    def test_both_empty_rejected(self, _patched_io):
        # Schema already rejects this at save, but the handler is the last
        # gate — a hand-crafted payload reaching it must not stamp nothing.
        result = handle_mark_with_emoji(_ctx(), {"emoji": "", "text": ""})

        assert result.ok is False
        assert "empty_marker" in (result.error or "")
        assert _FakeRepoForWrite.last_row is None, "no row write on rejection"

    def test_emoji_only_still_writes_unchanged(self, _patched_io):
        # Regression lock: pre-existing emoji-only path must keep working.
        result = handle_mark_with_emoji(_ctx(), {"emoji": "🔄"})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed == {"emoji": "🔄"}


# --------------------------------------------------------------------------- #
# Handler — color + chip toggle ride along in the stamped marker JSON
# --------------------------------------------------------------------------- #

class TestHandlerColorAndChip:
    def test_color_written_to_marker(self, _patched_io):
        result = handle_mark_with_emoji(_ctx(), {"emoji": "💰", "color": "#dc2626"})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed["color"] == "#dc2626"

    def test_chip_false_written_to_marker(self, _patched_io):
        result = handle_mark_with_emoji(_ctx(), {"emoji": "💰", "chip": False})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed["chip"] is False

    def test_chip_true_is_omitted_from_marker(self, _patched_io):
        # Default chip=True is the existing rendering — keep the JSON minimal
        # so legacy rows and chip=True rows decode identically.
        result = handle_mark_with_emoji(_ctx(), {"emoji": "💰", "chip": True})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert "chip" not in parsed

    def test_color_and_chip_with_text(self, _patched_io):
        result = handle_mark_with_emoji(
            _ctx(),
            {"emoji": "💰", "text": "Stripe", "color": "#3b82f6", "chip": False},
        )

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed == {
            "emoji": "💰", "text": "Stripe", "color": "#3b82f6", "chip": False,
        }

    def test_no_color_no_chip_keys_when_absent(self, _patched_io):
        result = handle_mark_with_emoji(_ctx(), {"emoji": "💰"})

        assert result.ok is True
        parsed = json.loads(_FakeRepoForWrite.last_row.emoji_marker_json)
        assert parsed == {"emoji": "💰"}


# --------------------------------------------------------------------------- #
# Decoder — API response surfaces text-only markers instead of dropping them
# --------------------------------------------------------------------------- #

class TestDecodeEmojiMarker:
    def test_text_only_marker_round_trips(self):
        raw = json.dumps({"text": "Follow-up"})
        assert _decode_emoji_marker(raw) == {"text": "Follow-up"}

    def test_empty_emoji_with_text_surfaces_text_only(self):
        # Defensive: a stored row that explicitly carries emoji=""
        # behaves the same as one with the key omitted.
        raw = json.dumps({"emoji": "", "text": "Follow-up"})
        assert _decode_emoji_marker(raw) == {"text": "Follow-up"}

    def test_both_empty_returns_none(self):
        raw = json.dumps({"emoji": "", "text": ""})
        assert _decode_emoji_marker(raw) is None

    def test_text_only_with_include_deadline(self):
        raw = json.dumps({"text": "Due", "include_deadline": True})
        assert _decode_emoji_marker(raw) == {"text": "Due", "include_deadline": True}

    def test_emoji_only_still_decodes(self):
        # Regression lock — pre-existing single-emoji marker stays unchanged.
        raw = json.dumps({"emoji": "🔄"})
        assert _decode_emoji_marker(raw) == {"emoji": "🔄"}

    def test_malformed_json_returns_none(self):
        assert _decode_emoji_marker("not-json{{{") is None

    def test_non_dict_payload_returns_none(self):
        # JSON array, JSON number, JSON string — none are valid marker shapes.
        assert _decode_emoji_marker(json.dumps(["text", "Follow-up"])) is None
        assert _decode_emoji_marker(json.dumps("Follow-up")) is None

    def test_text_whitespace_only_treated_as_empty(self):
        # The handler trims; the decoder should match so a stale row with a
        # whitespace-only text doesn't render an empty pill.
        raw = json.dumps({"text": "   "})
        assert _decode_emoji_marker(raw) is None


class TestDecodeEmojiMarkerColorAndChip:
    def test_palette_color_surfaced(self):
        raw = json.dumps({"emoji": "💰", "color": "#dc2626"})
        assert _decode_emoji_marker(raw) == {"emoji": "💰", "color": "#dc2626"}

    def test_text_only_with_color(self):
        raw = json.dumps({"text": "VIP", "color": "#3b82f6"})
        assert _decode_emoji_marker(raw) == {"text": "VIP", "color": "#3b82f6"}

    def test_chip_false_surfaced(self):
        raw = json.dumps({"emoji": "💰", "chip": False})
        assert _decode_emoji_marker(raw) == {"emoji": "💰", "chip": False}

    def test_chip_true_is_omitted(self):
        # True is the default rendering — decode it the same as a legacy row
        # that never carried the key.
        raw = json.dumps({"emoji": "💰", "chip": True})
        assert _decode_emoji_marker(raw) == {"emoji": "💰"}

    def test_non_hex_color_dropped(self):
        # A malformed/legacy color must not reach the inbox style attribute.
        raw = json.dumps({"emoji": "💰", "color": "red"})
        assert _decode_emoji_marker(raw) == {"emoji": "💰"}

    def test_css_injection_color_dropped(self):
        # Defense-in-depth: a corrupt row carrying CSS past the hex must be
        # rejected by the format-check so it can't inject into style="".
        raw = json.dumps({"emoji": "💰", "color": "#dc2626;position:fixed"})
        assert _decode_emoji_marker(raw) == {"emoji": "💰"}

    def test_color_with_trailing_newline_dropped(self):
        # `$` anchors match before a trailing newline — fullmatch must not.
        raw = json.dumps({"emoji": "💰", "color": "#dc2626\n"})
        assert _decode_emoji_marker(raw) == {"emoji": "💰"}
