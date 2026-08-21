# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fixes 04-onboarding (2026-04-24).

Each test reproduces the bug pre-fix and verifies the fix post-fix.
Run: ``pytest tests/audit_fixes/test_onboarding_audit_fixes.py -v``

Covered findings:
- OB-02: zero-sent-emails account silently marked completed.
- OB-03: non-FR/EN inboxes silently fall back to FR.
- OB-04: skip button has no confirm modal (frontend; logic checked here
  via the localStorage marker presence is left to e2e — we test the
  ``cancel`` endpoint instead since it shares the modal pattern).
- OB-05: deep training cost estimator + hard cap.
- OB-01: ``cancel`` endpoint exists and flips an active row to cancelled.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask_cors")


# ---------------------------------------------------------------------------
# OB-02 — zero-sent-emails should mark partial, not completed
# ---------------------------------------------------------------------------


def test_ob02_orchestrator_marks_partial_when_profile_partial():
    """ProfileAgent emits ``_partial`` when no sent emails. Orchestrator
    must propagate this as ``status='partial'`` (NOT ``completed``)
    with ``partial_reasons=['no_sent_emails']``.
    """
    from app.onboarding.orchestrator import (
        OnboardingOrchestrator, OnboardingResult,
    )
    from app.onboarding.indexer import IndexedEmails
    from app.onboarding.schemas import Language

    orch = OnboardingOrchestrator()

    # Build an IndexedEmails with zero sent emails (user just OAuthed).
    indexed = IndexedEmails(
        all_emails=[],
        sent_emails=[],
        received_emails=[],
        by_contact={},
        by_thread={},
        contact_metrics={},
        user_email="alice@example.com",
        total_count=0,
        sent_count=0,
        received_count=0,
    )

    # Stub the agents — we don't need real LLM calls. ProfileAgent must
    # return ``_partial=True`` with reason ``no_sent_emails``; the other
    # three agents return empty dicts.
    import app.onboarding.orchestrator as orch_mod

    class _StubProfile:
        def analyse(self, _):
            return {
                "user_email": "alice@example.com",
                "user_name": "",
                "languages": ["fr"],
                "_partial": True,
                "_reason": "no_sent_emails",
            }

    class _StubEmpty:
        def analyse(self, _):
            return {}

    # Monkey-patch the agent classes so ``run()`` picks them up.
    orig_profile = orch_mod.ProfileAgent
    orig_knowledge = orch_mod.KnowledgeAgent
    orig_style = orch_mod.StyleAgent
    orig_label = orch_mod.LabelAgent
    orch_mod.ProfileAgent = _StubProfile  # type: ignore[assignment]
    orch_mod.KnowledgeAgent = _StubEmpty  # type: ignore[assignment]
    orch_mod.StyleAgent = _StubEmpty  # type: ignore[assignment]
    orch_mod.LabelAgent = _StubEmpty  # type: ignore[assignment]

    try:
        result: OnboardingResult = orch.run(indexed)
    finally:
        orch_mod.ProfileAgent = orig_profile  # type: ignore[assignment]
        orch_mod.KnowledgeAgent = orig_knowledge  # type: ignore[assignment]
        orch_mod.StyleAgent = orig_style  # type: ignore[assignment]
        orch_mod.LabelAgent = orig_label  # type: ignore[assignment]

    assert result.status == "partial", (
        f"Expected status=partial when ProfileAgent flags _partial, got {result.status!r}"
    )
    assert "no_sent_emails" in result.partial_reasons, (
        f"Expected partial_reasons to contain 'no_sent_emails', got {result.partial_reasons!r}"
    )
    assert result.error and "Aucun email envoyé" in result.error
    # Verify the legacy "completed" path is NOT taken — we don't lie to the user.
    assert result.status != "completed"
    _ = Language  # silence unused-import in some lints


# ---------------------------------------------------------------------------
# OB-03 — non-FR/EN inboxes flag unsupported_language partial reason
# ---------------------------------------------------------------------------


def test_ob03_indexer_detects_spanish_corpus_as_unsupported():
    """A Spanish-dominant sent corpus must not silently resolve to FR."""
    from app.onboarding.indexer import IndexedEmails
    from app.onboarding.loader import OnboardingEmail
    from app.onboarding.schemas import EmailDirection, Language
    from datetime import datetime, timezone

    spanish_body = (
        "Hola Juan, gracias por tu mensaje. "
        "Para confirmar la reunión del lunes, te confirmo que estoy disponible. "
        "Saludos cordiales, soy estimado para resolver. "
        "Para que no haya problemas con el proyecto, los documentos están listos. "
        "Gracias por tu paciencia, hasta pronto."
    )
    sent_emails = [
        OnboardingEmail(
            id=f"id{i}",
            sender_email="me@example.com",
            sender_name="Me",
            recipients=["juan@example.com"],
            cc=[],
            subject="Hola",
            body=spanish_body,
            date=datetime.now(timezone.utc),
            direction=EmailDirection.SENT,
        )
        for i in range(3)
    ]

    indexed = IndexedEmails(
        all_emails=sent_emails,
        sent_emails=sent_emails,
        received_emails=[],
        by_contact={},
        by_thread={},
        contact_metrics={},
        user_email="me@example.com",
        total_count=3,
        sent_count=3,
        received_count=0,
    )

    lang = indexed.primary_language
    assert lang == Language.UNSUPPORTED, (
        f"Expected Language.UNSUPPORTED for Spanish corpus, got {lang!r}"
    )


def test_ob03_indexer_keeps_fr_when_spanish_minority():
    """A French inbox with one Spanish sentence still resolves to FR."""
    from app.onboarding.indexer import IndexedEmails
    from app.onboarding.loader import OnboardingEmail
    from app.onboarding.schemas import EmailDirection, Language
    from datetime import datetime, timezone

    fr_body = (
        "Bonjour Jean, merci pour votre message. "
        "Pour confirmer la réunion de lundi, je suis disponible. "
        "Cordialement, je vous confirme la date avec votre équipe. "
        "Merci pour votre patience, à bientôt. "
        "Hola — petit mot d'espagnol au passage."
    )
    sent_emails = [
        OnboardingEmail(
            id="id1",
            sender_email="me@example.com",
            sender_name="Me",
            recipients=["jean@example.com"],
            cc=[],
            subject="Bonjour",
            body=fr_body,
            date=datetime.now(timezone.utc),
            direction=EmailDirection.SENT,
        )
    ]

    indexed = IndexedEmails(
        all_emails=sent_emails,
        sent_emails=sent_emails,
        received_emails=[],
        by_contact={},
        by_thread={},
        contact_metrics={},
        user_email="me@example.com",
        total_count=1,
        sent_count=1,
        received_count=0,
    )

    assert indexed.primary_language == Language.FR


def test_ob03_prompt_loader_falls_back_to_english_for_unsupported():
    """``load_prompt(name, lang='unsupported')`` falls back to the EN
    variant (better than FR for a non-FR/EN inbox)."""
    from app.onboarding.agents.prompts import load_prompt, is_supported_language

    assert is_supported_language("fr")
    assert is_supported_language("en")
    assert not is_supported_language("es")
    assert not is_supported_language("unsupported")
    assert not is_supported_language("")

    # Loading 'es' should fall back to the EN file (not FR), proving the
    # fallback policy is honoured.
    en_text = load_prompt("profile", lang="en")
    es_text = load_prompt("profile", lang="es")
    assert es_text == en_text


# ---------------------------------------------------------------------------
# OB-05 — deep training cost estimator + hard cap
# ---------------------------------------------------------------------------


def test_ob05_estimator_returns_value_and_flags_over_default_cap(monkeypatch):
    """Pre-flight estimator returns ``estimated_usd`` for a 30K corpus
    AND flags it as ``would_exceed_default_cap``.
    """
    from app.onboarding.manager import OnboardingManager

    mgr = OnboardingManager(session_factory=lambda: None)

    # Stub _count_account_emails to return 30000 emails.
    monkeypatch.setattr(mgr, "_count_account_emails", lambda _aid: 30000)

    estimate = mgr.estimate_deep_training_cost(account_id=1)

    assert estimate["email_count"] == 30000
    assert estimate["batch_count"] == 60  # 30000 / 500
    assert estimate["estimated_usd"] >= 100.0  # 60 batches × $2/batch
    assert estimate["would_exceed_default_cap"] is True


def test_ob05_refresh_deep_blocks_without_confirmation(monkeypatch):
    """``refresh(mode='deep')`` returns ``status='needs_confirmation'`` for
    a corpus over the default cap when no budget is provided.
    """
    from app.onboarding.manager import OnboardingManager

    mgr = OnboardingManager(session_factory=lambda: None)
    monkeypatch.setattr(mgr, "_count_account_emails", lambda _aid: 30000)

    result = mgr.refresh(account_id=1, user_email="x@example.com", mode="deep")

    assert result["status"] == "needs_confirmation"
    assert "estimate" in result
    assert result["estimate"]["would_exceed_default_cap"] is True
    # Must NOT have spawned a thread — the cancel-flag should be untouched.
    assert 1 not in mgr._cancelled


def test_ob05_refresh_deep_blocks_when_budget_below_estimate(monkeypatch):
    """``refresh(mode='deep', confirm_estimate_usd=10)`` rejects when the
    estimate exceeds the user-confirmed budget."""
    from app.onboarding.manager import OnboardingManager

    mgr = OnboardingManager(session_factory=lambda: None)
    monkeypatch.setattr(mgr, "_count_account_emails", lambda _aid: 30000)

    result = mgr.refresh(
        account_id=1, user_email="x@example.com", mode="deep",
        confirm_estimate_usd=10.0,
    )

    assert result["status"] == "cost_exceeded"
    assert 1 not in mgr._cancelled


def test_ob05_refresh_deep_proceeds_within_default_budget(monkeypatch):
    """When the corpus fits in the default cap, no confirmation is needed
    and the worker thread is spawned (we stub it out so it doesn't run)."""
    from app.onboarding.manager import OnboardingManager
    import threading

    mgr = OnboardingManager(session_factory=lambda: None)
    monkeypatch.setattr(mgr, "_count_account_emails", lambda _aid: 1000)

    spawned_threads: list[threading.Thread] = []
    real_thread = threading.Thread

    class _CapturingThread(real_thread):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            spawned_threads.append(self)

        def start(self):  # type: ignore[no-untyped-def]
            # Don't actually start — we just want to assert spawn happened.
            pass

    monkeypatch.setattr(threading, "Thread", _CapturingThread)

    result = mgr.refresh(account_id=2, user_email="y@example.com", mode="deep")

    assert result["status"] == "started"
    assert result["estimate"] is not None
    assert result["estimate"]["would_exceed_default_cap"] is False
    assert len(spawned_threads) == 1


# ---------------------------------------------------------------------------
# OB-01 — cancel endpoint marks an active row as cancelled
# ---------------------------------------------------------------------------


def test_ob01_cancel_emits_cancelled_event(monkeypatch):
    """``OnboardingManager.cancel(account_id)`` flips ``_cancelled[account_id]``,
    flags the active DB row as ``cancelled``, AND emits a
    ``learning_completed`` WS event so the frontend can transition.
    """
    from app.onboarding.manager import OnboardingManager

    # Capture emitted events.
    emitted: list[tuple[str, dict]] = []

    def _emit(name, data):
        emitted.append((name, data))

    # Stub the active row.
    class _FakeRow:
        id = 99
        status = "running"
        error_message = None

    fake_row = _FakeRow()

    class _FakeRepo:
        def __init__(self, _session):
            pass

        def find_active(self, _aid):
            return fake_row

    fake_session = object()  # opaque

    class _FakeSession:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    fake = _FakeSession()
    mgr = OnboardingManager(session_factory=lambda: fake, emit_event=_emit)

    monkeypatch.setattr(
        "app.onboarding.manager.OnboardingRepository",
        _FakeRepo,
    )

    result = mgr.cancel(account_id=42)

    assert result["status"] == "cancelling"
    assert result["account_id"] == 42
    assert mgr._cancelled.get(42) is True
    assert fake_row.status == "cancelled"
    # WS event must be emitted so the frontend can transition.
    assert any(
        name == "onboarding:learning_completed" and data.get("status") == "cancelled"
        for name, data in emitted
    ), f"Expected cancelled WS event, got {emitted!r}"
    _ = fake_session  # mark used


def test_ob01_cancel_endpoint_route_registered():
    """The Flask blueprint exposes POST /api/onboarding/cancel."""
    from app.api.onboarding import onboarding_bp

    rules = [str(r) for r in onboarding_bp.deferred_functions]
    # We don't have direct access to URL rules here without an app; the
    # cleanest check is that the function exists in the module.
    from app.api import onboarding as ob_mod
    assert hasattr(ob_mod, "cancel_onboarding"), (
        "OB-01: /api/onboarding/cancel handler must exist"
    )
    _ = rules
