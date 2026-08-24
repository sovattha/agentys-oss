# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for the deep audit of 2026-06-02.

Report: tasks/audit-reports/deep-audit-2026-06-02.md

Each test pins a confirmed P1 fix so it can't silently regress:
  B — auto-transfer loop unpacked 3 names from new_replies' 4-tuples.
  D — custom-label CRUD lacked the -1 sentinel guard (cross-tenant pooling).
  E — scheduled_emails create/list/cancel/patch lacked the -1 sentinel guard.
"""

import ast
import inspect
import textwrap
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

import app.api.routes_emails as routes_emails_mod

pytest.importorskip("flask_cors")

# A valid Bearer + decoded JWT so requests pass the global auth guard and reach
# the handler under test. Using the real create_app (not a bare Flask app) keeps
# these tests isolation-safe: create_app activates a global auth before_request,
# so a bare app would get 401'd once any other test in the suite has built the
# full app. Authenticating reaches MY -1 guard regardless of suite ordering.
REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
_BEARER = {"Authorization": "Bearer stub-token"}


def _decode_jwt_ok():
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": 1, "email": "split@example.com"},
    )


# ===========================================================================
# B — auto-transfer 3-tuple unpack (routes_emails.py:768)
# ===========================================================================

def test_auto_transfer_loop_unpacks_full_new_replies_tuple():
    """B (P1): the auto-transfer loop did ``for email_obj, sender, eid in
    new_replies`` while new_replies holds 4-tuples (the F-02 dedup fix added a
    4th element, ``_sender_addr``, but only updated the auto-reply loop). That
    raised ``ValueError: too many values to unpack`` on the first iteration,
    was swallowed by the function-level ``except`` at WARNING, and the
    auto-forward feature silently never fired for any user with both vacation
    auto-reply and auto-forward enabled.

    ``_send_auto_replies_bg`` has heavy I/O dependencies (settings, the provider
    pool, tracker files), so we guard the exact structural contract the bug
    violated — for BOTH loops over new_replies — via AST. This mirrors the
    existing ``inspect.getsource`` guards on this same function in
    test_medlow_fixes.py and re-breaks if either the tuple arity or any loop
    unpacking drifts again.
    """
    src = textwrap.dedent(inspect.getsource(routes_emails_mod._send_auto_replies_bg))
    tree = ast.parse(src)

    # Arity of every tuple appended to new_replies.
    append_arities = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "new_replies"
            and node.args
            and isinstance(node.args[0], ast.Tuple)
        ):
            append_arities.add(len(node.args[0].elts))
    assert append_arities == {4}, (
        f"new_replies should be built from 4-tuples; found arities {append_arities}"
    )

    # Every `for ... in new_replies` must tuple-unpack that same arity.
    loop_arities = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "new_replies"
        ):
            assert isinstance(node.target, ast.Tuple), (
                "a loop over new_replies must tuple-unpack it"
            )
            loop_arities.append(len(node.target.elts))

    assert len(loop_arities) >= 2, (
        f"expected the auto-reply AND auto-transfer loops over new_replies; "
        f"found {len(loop_arities)}"
    )
    for arity in loop_arities:
        assert arity == 4, (
            f"a loop unpacks {arity} names but new_replies holds 4-tuples "
            f"(the B regression)"
        )


# ===========================================================================
# D — custom-label CRUD -1 sentinel guard (labels.py)
# ===========================================================================

@pytest.fixture
def full_client():
    from app.api.app import create_app
    return create_app(config={"TESTING": True}).test_client()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/labels", None),
        ("post", "/api/labels", {"name": "Projet"}),
        ("get", "/api/labels/Projet", None),
        ("put", "/api/labels/Projet", {"color": "#ffffff"}),
        ("delete", "/api/labels/Projet", None),
    ],
)
def test_labels_crud_rejects_sentinel_account(full_client, method, path, body):
    """D (P1, CWE-639): the 5 custom-label handlers lacked the -1 sentinel guard
    its rules/VIP siblings have, so a JWT-authenticated pre-OAuth caller (no DB
    account row -> account_id resolves to -1) pooled into the shared
    data/labels/-1 store — a cross-tenant read/create/update/delete. Each handler
    must now 401 on account_id<=0.
    """
    # Authenticate (pass the global auth guard), then force the DB resolver to the
    # -1 sentinel. labels handlers do a call-time `from app.api.routes_helpers
    # import _resolve_account_id_for_user`, so patching the source module works.
    with ExitStack() as stack:
        stack.enter_context(_decode_jwt_ok())
        stack.enter_context(
            patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1)
        )
        fn = getattr(full_client, method)
        kwargs = {"headers": _BEARER, "environ_base": REMOTE}
        if body is not None:
            kwargs["json"] = body
        resp = fn(path, **kwargs)
    assert resp.status_code == 401, (
        f"{method.upper()} {path} returned {resp.status_code}, expected 401 "
        f"(body: {resp.get_data(as_text=True)[:200]})"
    )


# ===========================================================================
# E — scheduled_emails -1 sentinel guard (create/list/cancel/patch)
# ===========================================================================

@pytest.fixture
def sched_store(tmp_path):
    from app.services.scheduled_email_store import (
        ScheduledEmailStore,
        reset_default_store,
    )
    s = ScheduledEmailStore(db_path=str(tmp_path / "sched.db"))
    reset_default_store(s)
    yield s
    reset_default_store(None)


@pytest.fixture
def sched_client(sched_store):
    from app.api.app import create_app
    return create_app(config={"TESTING": True}).test_client()


def _sentinel_patches(stack):
    """Authenticated JWT caller whose multi_accounts None-gate passes (non-None
    account) but whose DB-resolved account_id is the -1 sentinel — the exact
    divergence E describes. Enters the patches on the given ExitStack."""
    stack.enter_context(_decode_jwt_ok())
    stack.enter_context(patch(
        "app.api.scheduled_emails._get_current_account_for_user",
        return_value=Mock(id="split", email="split@example.com"),
    ))
    stack.enter_context(patch(
        "app.api.scheduled_emails._resolve_account_id_cached",
        return_value=-1,
    ))


def _future_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_schedule_create_rejects_sentinel_account(sched_client, sched_store):
    """E (P1): a divergent caller must not enqueue a send under account_id=-1."""
    with ExitStack() as stack:
        _sentinel_patches(stack)
        resp = sched_client.post(
            "/api/emails/schedule",
            json={
                "to": "victim@example.com",
                "subject": "s",
                "body": "b",
                "send_at": _future_iso(),
            },
            headers=_BEARER, environ_base=REMOTE,
        )
    assert resp.status_code == 401, resp.get_data(as_text=True)
    # No row landed in the shared -1 bucket.
    assert sched_store.list_by_account(account_id=-1, statuses=("pending",)) == []


def test_schedule_list_does_not_leak_sentinel_bucket(sched_client, sched_store):
    """E (P1): GET must not return another tenant's rows pooled under -1."""
    # Seed a row directly under the -1 bucket (simulating a pre-existing pooled row).
    sched_store.insert(
        account_id=-1,
        payload={"to": ["x@example.com"], "subject": "leak", "body": "b"},
        send_at=datetime.now(timezone.utc) + timedelta(hours=3),
    )
    with ExitStack() as stack:
        _sentinel_patches(stack)
        resp = sched_client.get("/api/emails/scheduled", headers=_BEARER, environ_base=REMOTE)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"items": [], "count": 0}, f"leaked -1 bucket: {data}"


def test_schedule_list_degraded_flag_on_store_error(sched_client, sched_store):
    """U (P2, BS-01): a store read failure must surface as degraded (200) so the
    FE shows a retry banner — NOT a silent empty list presented as success, and
    NOT a 5xx (which would trip the apiClient connection-lost interceptor)."""
    boom = Mock()
    boom.list_by_account.side_effect = RuntimeError("database is locked")
    with ExitStack() as stack:
        stack.enter_context(_decode_jwt_ok())
        stack.enter_context(patch(
            "app.api.scheduled_emails._get_current_account_for_user",
            return_value=Mock(id="ok", email="ok@example.com"),
        ))
        # Valid positive account_id (passes the E guard) so we reach the store call.
        stack.enter_context(patch(
            "app.api.scheduled_emails._resolve_account_id_cached", return_value=42
        ))
        stack.enter_context(patch("app.api.scheduled_emails._store", return_value=boom))
        resp = sched_client.get("/api/emails/scheduled", headers=_BEARER, environ_base=REMOTE)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {"items": [], "count": 0, "degraded": True}


def test_schedule_cancel_rejects_sentinel_account(sched_client, sched_store):
    """E (P1): a divergent caller must not cancel another tenant's -1 send."""
    with ExitStack() as stack:
        _sentinel_patches(stack)
        resp = sched_client.delete(
            "/api/emails/scheduled/some-id", headers=_BEARER, environ_base=REMOTE
        )
    assert resp.status_code == 401, resp.get_data(as_text=True)


def test_schedule_patch_rejects_sentinel_account(sched_client, sched_store):
    """E (P1): a divergent caller must not edit another tenant's -1 send."""
    with ExitStack() as stack:
        _sentinel_patches(stack)
        resp = sched_client.patch(
            "/api/emails/scheduled/some-id", json={"subject": "x"},
            headers=_BEARER, environ_base=REMOTE,
        )
    assert resp.status_code == 401, resp.get_data(as_text=True)


# ===========================================================================
# J — auto-reply tracker FS-error must not cause duplicate sends (BS-09)
# ===========================================================================

def test_persist_auto_reply_tracker_returns_true_on_success(tmp_path):
    """J: the persist now reports success so the pre-mark caller can gate the send."""
    ok = routes_emails_mod._persist_auto_reply_tracker(
        {"a@example.com": {"status": "sent"}}, str(tmp_path / "tracker.json")
    )
    assert ok is True
    assert (tmp_path / "tracker.json").exists()


def test_persist_auto_reply_tracker_returns_false_on_write_error():
    """J: a failed write returns False (was None) so the caller can skip the send
    instead of risking a duplicate auto-reply on the next 60s cycle."""
    import tempfile as _tf
    with patch.object(_tf, "NamedTemporaryFile", side_effect=OSError("disk full")):
        ok = routes_emails_mod._persist_auto_reply_tracker(
            {"a@example.com": {"status": "pending"}}, "tracker.json"
        )
    assert ok is False


def test_auto_reply_skips_send_when_premark_persist_fails():
    """J (BS-09): the pre-mark persist return value MUST gate send_draft — a failed
    pre-mark skips the send (dedup not guaranteed on disk) rather than firing and
    letting the next cycle re-send a duplicate."""
    src = inspect.getsource(routes_emails_mod._send_auto_replies_bg)
    assert "if not _persist_auto_reply_tracker(" in src, (
        "the pre-mark persist return value must gate the send"
    )
    # The skip (continue) must occur between the persist-guard and the send_draft
    # call — i.e. a failed pre-mark short-circuits BEFORE the email is sent.
    guard_idx = src.index("if not _persist_auto_reply_tracker(")
    send_idx = src.index("send_provider.send_draft(", guard_idx)
    assert "continue" in src[guard_idx:send_idx], (
        "the failed-persist branch must `continue` before send_draft (skip this cycle)"
    )


# ===========================================================================
# F — N+1 in _sync_emails_to_cache (routes_emails.py)
# ===========================================================================

def test_sync_emails_to_cache_uses_batch_row_fetch_not_per_row():
    """F (P1): the inbox-sync loop batch-checks existence (get_existing_ids) and
    must then batch-fetch the rows via get_by_email_ids — NOT call get_by_email_id
    once per already-cached email (the N+1 that defeated the batch check on every
    per-account sync tick). Guard the exact function so the N+1 can't creep back.
    """
    src = inspect.getsource(routes_emails_mod._sync_emails_to_cache)
    assert "get_by_email_ids(" in src, (
        "_sync_emails_to_cache should batch-fetch existing rows via get_by_email_ids"
    )
    # NB: 'get_by_email_id(' is NOT a substring of 'get_by_email_ids(' (the char
    # after 'id' is 's', not '('), so this catches a reintroduced per-row call.
    assert "get_by_email_id(" not in src, (
        "_sync_emails_to_cache calls get_by_email_id per row again — the F N+1 is back"
    )


# ===========================================================================
# G — save_assignments_batch (label_store.py)
# ===========================================================================

def _no_db():
    """Make the best-effort SQL dual-write a hermetic no-op so the test exercises
    only the JSON/cache path (label_store imports get_db_session inside the
    method, so patching the source module is seen at call time)."""
    return patch("app.db.database.get_db_session", side_effect=RuntimeError("no db in test"))


def test_save_assignments_batch_persists_all_to_cache_and_disk(tmp_path):
    """G (P1): save_assignments_batch must persist every assignment to the
    in-memory cache AND the assignments.json file — equivalent to calling
    save_assignment per email, but in one file rewrite + one DB transaction."""
    from app.infrastructure.adapters.label_store import LabelStore
    from app.domain.entities.email_labels import LabelAssignment

    store = LabelStore(storage_dir=str(tmp_path))
    a1 = LabelAssignment(email_id="e1", labels=["Action"])
    a2 = LabelAssignment(email_id="e2", labels=["FYI"])
    with _no_db():
        store.save_assignments_batch([a1, a2])

    assert store.get_assignment("e1").labels == ["Action"]
    assert store.get_assignment("e2").labels == ["FYI"]

    # Persisted to disk: a fresh store reads them back.
    store2 = LabelStore(storage_dir=str(tmp_path))
    assert store2.get_assignment("e1") is not None
    assert store2.get_assignment("e2") is not None


def test_save_assignments_batch_empty_is_noop(tmp_path):
    from app.infrastructure.adapters.label_store import LabelStore

    store = LabelStore(storage_dir=str(tmp_path))
    with _no_db():
        store.save_assignments_batch([])  # must not raise
    assert store.get_assignment("whatever") is None


# ===========================================================================
# L — route() defers smart_suggestions instead of an inline Haiku call
# ===========================================================================

def test_route_defers_smart_suggestions_no_inline_haiku():
    """L (P2): non-streaming route() must NOT call _generate_smart_suggestions
    inline (an extra Haiku round-trip that /drafts/<id>/regenerate discards). It
    defers like route_streaming; the REST consumer populates async on `is None`."""
    from app.smart_routing import SmartRouter

    src = inspect.getsource(SmartRouter.route)
    assert "_generate_smart_suggestions(" not in src, (
        "route() still calls _generate_smart_suggestions inline (the L regression)"
    )
    assert "smart_suggestions_deferred" in src, (
        "route() should set smart_suggestions_deferred to defer to async populate"
    )


# ===========================================================================
# M — token refresh writes back to the canonical DB account row (oauth.py)
# ===========================================================================

def test_store_tokens_server_writes_db_account():
    """M (P2): the refresh path routes through store_tokens_server, which must
    now write the refreshed tokens back to the canonical DB account row (resolve
    by email; update refresh_token guarded; update expiry) — else a multi-service
    worker reads a stale rotated Outlook refresh_token from the DB (the documented
    cross-service source of truth) and silently logs out. The function previously
    touched neither get_by_email nor token_expires_at."""
    from app.api import oauth as oauth_mod

    src = inspect.getsource(oauth_mod.store_tokens_server)
    assert "get_by_email" in src, (
        "store_tokens_server must resolve + write the DB account row"
    )
    assert "token_expires_at" in src, (
        "store_tokens_server must update the DB token expiry"
    )
    # The refresh_token DB write must be guarded — a refresh response often omits
    # it (old one stays valid); nulling it would itself cause invalid_grant.
    assert "if _new_refresh" in src, (
        "the refresh_token DB write must be guarded against an omitted token"
    )
