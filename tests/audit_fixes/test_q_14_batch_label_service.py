# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-14 — Post-onboarding batch labeling (audit 2026-05-06).

Pre-fix: post-onboarding label sweep was rule-only; the long tail of
emails that didn't match any rule fell back to one-Haiku-per-email at
the regular price. For 500-1000 emails per onboarding × N users, this
is real money.

Post-fix: ``submit_post_onboarding_label_batch`` enqueues all unmatched
emails into Anthropic's Message Batches API at 50 % discount.
``poll_and_apply_results`` is run later by a cron and writes the
classifications back to the per-account label_store.

Behaviour gates:
- Feature is opt-in via env POST_ONBOARDING_BATCH_LABEL=true.
  When the env is unset, ``submit`` returns None and is a complete no-op.
- Empty / invalid input returns None.
- Custom-id round-trips through parse_custom_id correctly.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("POST_ONBOARDING_BATCH_LABEL", raising=False)
    from app.services.batch_label_service import (
        submit_post_onboarding_label_batch, is_enabled,
    )
    assert is_enabled() is False
    out = submit_post_onboarding_label_batch(
        account_id=42,
        emails=[{"email_id": "x", "sender": "a@b.c", "subject": "hi", "body": "hello"}],
    )
    assert out is None, "Disabled feature must be a complete no-op"


def test_enabled_no_emails_returns_none(monkeypatch):
    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    from app.services.batch_label_service import submit_post_onboarding_label_batch
    assert submit_post_onboarding_label_batch(42, []) is None


def test_enabled_invalid_account_returns_none(monkeypatch):
    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    from app.services.batch_label_service import submit_post_onboarding_label_batch
    assert submit_post_onboarding_label_batch(0, [{"email_id": "x"}]) is None
    assert submit_post_onboarding_label_batch(-1, [{"email_id": "x"}]) is None


def test_custom_id_roundtrip():
    from app.services.batch_label_service import _custom_id_for, _parse_custom_id
    cid = _custom_id_for("abc-123", 42)
    eid, aid = _parse_custom_id(cid)
    assert eid == "abc-123"
    assert aid == 42


def test_invalid_custom_id_parses_safely():
    from app.services.batch_label_service import _parse_custom_id
    assert _parse_custom_id("garbage") == (None, None)
    assert _parse_custom_id("label::eid::not_int") == ("eid", None)


def test_submit_writes_tracking_row(monkeypatch, tmp_path):
    """When submit succeeds, a row lands in the tracking table."""
    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    # Reset the module-level connection so the new DATA_DIR takes effect.
    import app.services.batch_label_service as svc
    if hasattr(svc._local, "conn") and svc._local.conn is not None:
        svc._local.conn.close()
        svc._local.conn = None

    fake_adapter = MagicMock()
    fake_adapter.submit_batch.return_value = "batch_test_001"
    fake_container = MagicMock()
    fake_container.llm_onboarding_label.model = "claude-haiku-4-5-20251001"

    with patch(
        "app.adapters.llm.claude_batch_adapter.ClaudeBatchAdapter",
        return_value=fake_adapter,
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=fake_container,
    ):
        out = svc.submit_post_onboarding_label_batch(
            account_id=42,
            emails=[
                {"email_id": "e1", "sender": "a@b.c", "subject": "hi", "body": "hello"},
                {"email_id": "e2", "sender": "x@y.z", "subject": "test", "body": "world"},
            ],
        )

    assert out == "batch_test_001"
    pending = svc.list_pending_batches()
    assert any(p["batch_id"] == "batch_test_001" for p in pending)
    assert any(p["request_count"] == 2 for p in pending)


def test_poll_partial_failures_counted_and_surfaced(monkeypatch, tmp_path, caplog):
    """B-05 (audit 2026-06-11): per-email apply failures and non-succeeded LLM
    results are counted (out.failed / out.skipped), surfaced via an aggregate
    WARNING, and feed get_batch_summary()'s `errored` — the batch itself stays
    in status 'applied' (no state-machine change)."""
    import json
    import logging
    from types import SimpleNamespace

    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    import app.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)

    # Reset the module-level connection so the new DATA_DIR takes effect.
    import app.services.batch_label_service as svc
    if hasattr(svc._local, "conn") and svc._local.conn is not None:
        svc._local.conn.close()
        svc._local.conn = None

    conn = svc._get_conn()
    conn.execute(
        f"INSERT INTO {svc._TABLE_NAME} "
        "(batch_id, account_id, request_count, status, submitted_at) "
        "VALUES (?, ?, ?, 'in_progress', ?)",
        ("batch_b05", 42, 3, "2026-06-11T00:00:00+00:00"),
    )
    conn.commit()

    results = [
        SimpleNamespace(
            status="succeeded", custom_id="label::e1::42",
            content=json.dumps({"label": "Action", "confidence": 0.9}),
        ),
        SimpleNamespace(
            status="succeeded", custom_id="label::e2::42",
            content=json.dumps({"label": "Noise", "confidence": 0.8}),
        ),
        # Résultat LLM non-succeeded → doit être COMPTÉ comme skipped.
        SimpleNamespace(status="errored", custom_id="label::e3::42", content=""),
    ]
    fake_adapter = MagicMock()
    fake_adapter.get_batch_status.return_value = SimpleNamespace(processing_status="ended")
    fake_adapter.fetch_batch_results.return_value = iter(results)

    fake_store = MagicMock()
    fake_store.get_assignment.return_value = None

    def _save(assignment):
        # e2 échoue à l'écriture → doit être COMPTÉ comme failed.
        if assignment.email_id == "e2":
            raise RuntimeError("store write failed")

    fake_store.save_assignment.side_effect = _save
    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_store

    with patch(
        "app.adapters.llm.claude_batch_adapter.ClaudeBatchAdapter",
        return_value=fake_adapter,
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=fake_container,
    ), caplog.at_level(logging.WARNING, logger="app.services.batch_label_service"):
        out = svc.poll_and_apply_results("batch_b05")

    assert out["status"] == "applied"
    assert out["applied"] == 1
    assert out["failed"] == 1
    assert out["skipped"] == 1

    warnings = [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and "partial apply" in r.getMessage()
    ]
    assert warnings, "expected an aggregate partial-apply WARNING"
    assert "applied=1" in warnings[0]
    assert "failed=1" in warnings[0]
    assert "skipped=1" in warnings[0]

    summary = svc.get_batch_summary(42)
    assert summary["applied"] == 1       # le batch reste en statut applied
    assert summary["errored"] == 1       # ... mais l'erreur est désormais visible
    assert summary["total_applied"] == 1


def test_poll_full_success_reports_no_errors(monkeypatch, tmp_path):
    """Contre-cas B-05 : aucun échec → errored reste 0 et pas de note d'erreur."""
    import json
    from types import SimpleNamespace

    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    import app.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)

    import app.services.batch_label_service as svc
    if hasattr(svc._local, "conn") and svc._local.conn is not None:
        svc._local.conn.close()
        svc._local.conn = None

    conn = svc._get_conn()
    conn.execute(
        f"INSERT INTO {svc._TABLE_NAME} "
        "(batch_id, account_id, request_count, status, submitted_at) "
        "VALUES (?, ?, ?, 'in_progress', ?)",
        ("batch_b05_ok", 43, 1, "2026-06-11T00:00:00+00:00"),
    )
    conn.commit()

    fake_adapter = MagicMock()
    fake_adapter.get_batch_status.return_value = SimpleNamespace(processing_status="ended")
    fake_adapter.fetch_batch_results.return_value = iter([
        SimpleNamespace(
            status="succeeded", custom_id="label::e1::43",
            content=json.dumps({"label": "FYI", "confidence": 0.7}),
        ),
    ])
    fake_store = MagicMock()
    fake_store.get_assignment.return_value = None
    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_store

    with patch(
        "app.adapters.llm.claude_batch_adapter.ClaudeBatchAdapter",
        return_value=fake_adapter,
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=fake_container,
    ):
        out = svc.poll_and_apply_results("batch_b05_ok")

    assert out["applied"] == 1
    assert out["failed"] == 0
    assert out["skipped"] == 0
    summary = svc.get_batch_summary(43)
    assert summary["applied"] == 1
    assert summary["errored"] == 0


def test_submit_failure_returns_none(monkeypatch):
    monkeypatch.setenv("POST_ONBOARDING_BATCH_LABEL", "true")
    fake_adapter = MagicMock()
    fake_adapter.submit_batch.return_value = None  # API failure
    fake_container = MagicMock()
    fake_container.llm_onboarding_label.model = "claude-haiku-4-5-20251001"
    import app.services.batch_label_service as svc

    with patch(
        "app.adapters.llm.claude_batch_adapter.ClaudeBatchAdapter",
        return_value=fake_adapter,
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=fake_container,
    ):
        out = svc.submit_post_onboarding_label_batch(
            42,
            [{"email_id": "e1", "sender": "a@b.c", "subject": "hi", "body": "hello"}],
        )
    assert out is None
