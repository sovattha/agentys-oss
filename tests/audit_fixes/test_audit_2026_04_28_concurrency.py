"""Regression tests for the 2026-04-28 audit fix batch (concurrency / WS routing).

Covers:
- P0-003: /pending-drafts/<id>/validate releases per-draft lock before SENT
  status update → double-send race. Now: status flips to SENT inside the lock.
- P1-006: _compose_stream_bg emits without account_id → events dropped.
  Now: account_id resolved in request context, threaded through and forwarded
  to emit_draft_chunk/complete/error.
- P1-013: WS completion event must fire AFTER status update, inside lock.
- P1-015: BG thread re-resolved current account → wrong mailbox marked read.
  Now: account_id (and provider via closure) captured at request entry.

Each test is meant to FAIL if the corresponding fix is reverted.
"""

from __future__ import annotations

from unittest.mock import patch



# ---------------------------------------------------------------------------
# P0-003 / P1-013 — /validate flips SENT inside the lock
# ---------------------------------------------------------------------------

def test_p0_003_validate_status_update_inside_lock():
    """The source of /pending-drafts/<id>/validate must update status to SENT
    BEFORE the `with _draft_lock:` block ends. We assert this structurally
    by reading the function source."""
    import inspect
    from app.api.routes_pending import validate_pending_draft

    src = inspect.getsource(validate_pending_draft)
    # Find the lock block boundaries by indentation.
    lines = src.splitlines()
    lock_idx = next(i for i, line in enumerate(lines) if "with _draft_lock:" in line)

    # Find the SENT update inside or right after the lock block.
    sent_inside = False
    indent = len(lines[lock_idx]) - len(lines[lock_idx].lstrip())
    for line in lines[lock_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent and stripped:
            # We've left the with block.
            break
        if "PendingDraftStatus.SENT" in stripped and "update_status" in stripped:
            sent_inside = True
            break
    assert sent_inside, (
        "PendingDraftStatus.SENT update must happen INSIDE the `with _draft_lock:` "
        "block to prevent the double-send race (audit P0-003)."
    )


# ---------------------------------------------------------------------------
# P1-006 — _compose_stream_bg accepts and forwards account_id
# ---------------------------------------------------------------------------

def test_p1_006_compose_stream_bg_signature_has_account_id():
    """_compose_stream_bg must accept an account_id parameter."""
    import inspect
    from app.api.routes_misc import _compose_stream_bg
    sig = inspect.signature(_compose_stream_bg)
    assert "account_id" in sig.parameters, (
        "_compose_stream_bg must accept account_id (audit P1-006)."
    )


def test_p1_006_compose_stream_bg_forwards_account_id_to_emits():
    """Verify the BG thread forwards account_id to emit_draft_chunk/complete."""
    from app.api import routes_misc as rm

    chunks: list[dict] = []
    completes: list[dict] = []

    def fake_chunk(**kwargs):
        chunks.append(kwargs)

    def fake_complete(**kwargs):
        completes.append(kwargs)

    class FakeChunk:
        def __init__(self, text, is_final=False):
            self.text = text
            self.is_final = is_final

    class FakeLLM:
        def stream(self, system, user, max_tokens):
            yield FakeChunk("hello ")
            yield FakeChunk("world")
            yield FakeChunk("", is_final=True)

    with patch("app.api.websocket.emit_draft_chunk", side_effect=fake_chunk), \
         patch("app.api.websocket.emit_draft_complete", side_effect=fake_complete), \
         patch("app.api.websocket.emit_draft_error"), \
         patch("app.api.routes_drafts._strip_trailing_signature", side_effect=lambda x, _s=None: x):
        rm._compose_stream_bg(
            compose_id="cmp-1",
            system_prompt="sys",
            user_prompt="usr",
            llm=FakeLLM(),
            typical_signature=None,
            account_id=99,
        )

    assert chunks, "expected at least one chunk emit"
    for c in chunks:
        assert c.get("account_id") == 99, f"chunk emit missing account_id: {c}"
    assert completes, "expected a complete emit"
    assert completes[0].get("account_id") == 99


def test_p1_006_compose_stream_bg_error_path_forwards_account_id():
    from app.api import routes_misc as rm

    errors: list[dict] = []

    class BoomLLM:
        def stream(self, system, user, max_tokens):
            raise RuntimeError("boom")

    with patch("app.api.websocket.emit_draft_chunk"), \
         patch("app.api.websocket.emit_draft_complete"), \
         patch("app.api.websocket.emit_draft_error", side_effect=lambda **kw: errors.append(kw)):
        rm._compose_stream_bg(
            compose_id="cmp-2",
            system_prompt="sys",
            user_prompt="usr",
            llm=BoomLLM(),
            typical_signature=None,
            account_id=77,
        )

    assert errors and errors[0].get("account_id") == 77


# ---------------------------------------------------------------------------
# P1-015 — provider/account_id captured at request entry
# ---------------------------------------------------------------------------

def test_p1_015_validate_captures_account_id_before_lock():
    """Read the source: _captured_account_id must be assigned BEFORE the
    `with _draft_lock:` block, and the BG closure must use it (not a fresh
    re-resolution) for downstream side-effects."""
    import inspect
    from app.api.routes_pending import validate_pending_draft
    src = inspect.getsource(validate_pending_draft)

    lines = src.splitlines()
    resolve_idx = next(
        (
            i for i, line in enumerate(lines)
            if "current_account_id" in line
            and "=" in line
            and "_resolve_account_id_cached" in line
        ),
        -1,
    )
    cap_idx = next(
        (
            i for i, line in enumerate(lines)
            if "_captured_account_id" in line
            and "=" in line
            and "current_account_id" in line
        ),
        -1,
    )
    lock_idx = next(i for i, line in enumerate(lines) if "with _draft_lock:" in line)
    assert resolve_idx >= 0, "missing account_id resolution before capture"
    assert cap_idx >= 0, "missing _captured_account_id assignment"
    assert resolve_idx < cap_idx, (
        "_captured_account_id must be derived from the request-entry resolution"
    )
    assert cap_idx < lock_idx, (
        "_captured_account_id must be assigned BEFORE the lock block (audit P1-015)."
    )

    # And the BG-closure resolved id must come from the captured value, not
    # a fresh _resolve_account_id_cached() call.
    assert "_resolved_acct_id = _captured_account_id" in src, (
        "BG closure must reuse _captured_account_id (audit P1-015)."
    )
