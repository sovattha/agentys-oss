# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.infrastructure.audit."""

import json
import pytest
from datetime import datetime
from app.infrastructure.audit import (
    AuditEventType,
    AuditEvent,
    AuditLogger,
)


# ============================================================================
# AuditEventType
# ============================================================================

class TestAuditEventType:
    def test_all_types_have_values(self):
        assert AuditEventType.DRAFT_CREATED.value == "draft_created"
        assert AuditEventType.DRAFT_COMPLETED.value == "draft_completed"
        assert AuditEventType.DRAFT_FAILED.value == "draft_failed"
        assert AuditEventType.EMAIL_PROCESSED.value == "email_processed"
        assert AuditEventType.EMAIL_SKIPPED.value == "email_skipped"
        assert AuditEventType.LLM_CALL.value == "llm_call"
        assert AuditEventType.LLM_ERROR.value == "llm_error"
        assert AuditEventType.AUTH_SUCCESS.value == "auth_success"
        assert AuditEventType.AUTH_FAILURE.value == "auth_failure"
        assert AuditEventType.DAEMON_START.value == "daemon_start"
        assert AuditEventType.DAEMON_STOP.value == "daemon_stop"
        assert AuditEventType.LEARNING_ANALYSIS.value == "learning_analysis"
        assert AuditEventType.FOLLOWUP_SENT.value == "followup_sent"
        assert AuditEventType.CONFIG_CHANGE.value == "config_change"


# ============================================================================
# AuditEvent
# ============================================================================

class TestAuditEvent:
    def test_create_event(self):
        event = AuditEvent(
            timestamp="2026-03-24T10:00:00",
            event_type="draft_created",
            success=True,
            details={"key": "value"},
        )
        assert event.success is True
        assert event.details == {"key": "value"}

    def test_to_dict_excludes_none(self):
        event = AuditEvent(
            timestamp="2026-03-24T10:00:00",
            event_type="llm_call",
            success=True,
            details={},
        )
        d = event.to_dict()
        assert "email_id" not in d
        assert "draft_id" not in d
        assert "error" not in d

    def test_to_dict_includes_optional_fields_when_set(self):
        event = AuditEvent(
            timestamp="2026-03-24T10:00:00",
            event_type="draft_created",
            success=True,
            details={},
            email_id="e1",
            draft_id="d1",
            duration_ms=150,
        )
        d = event.to_dict()
        assert d["email_id"] == "e1"
        assert d["draft_id"] == "d1"
        assert d["duration_ms"] == 150


# ============================================================================
# AuditLogger
# ============================================================================

class TestAuditLogger:
    @pytest.fixture
    def audit_file(self, tmp_path):
        return tmp_path / "test_audit.json"

    @pytest.fixture
    def logger(self, audit_file):
        return AuditLogger(filepath=audit_file, max_events=100)

    def test_log_creates_event(self, logger):
        event = logger.log(AuditEventType.DRAFT_CREATED, success=True, details={"test": True})
        assert event.success is True
        assert event.event_type == "draft_created"

    def test_log_persists_to_file(self, logger, audit_file):
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        assert audit_file.exists()
        data = json.loads(audit_file.read_text())
        assert data["event_count"] == 1

    def test_log_draft_created_shortcut(self, logger):
        event = logger.log_draft_created(
            email_id="e1",
            draft_id="d1",
            recipient="alice@example.com",
            subject="Test Subject That Is Very Long And Should Be Truncated To 50 Characters Max",
            duration_ms=200,
            status="V1",
        )
        assert event.event_type == "draft_created"
        assert event.email_id == "e1"
        assert event.draft_id == "d1"
        # Subject should be truncated in details
        assert len(event.details["subject"]) <= 50

    def test_log_draft_failed_shortcut(self, logger):
        event = logger.log_draft_failed(
            email_id="e1",
            recipient="bob@example.com",
            error="LLM timeout",
        )
        assert event.success is False
        assert event.error == "LLM timeout"

    def test_log_email_skipped_shortcut(self, logger):
        event = logger.log_email_skipped(
            email_id="e1",
            reason="SPAM",
            category="SPAM",
        )
        assert event.event_type == "email_skipped"
        assert event.details["reason"] == "SPAM"

    def test_get_events_all(self, logger):
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        logger.log(AuditEventType.DRAFT_CREATED, success=True, details={})
        events = logger.get_events()
        assert len(events) == 2

    def test_get_events_filtered_by_type(self, logger):
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        logger.log(AuditEventType.DRAFT_CREATED, success=True, details={})
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        events = logger.get_events(event_type=AuditEventType.LLM_CALL)
        assert len(events) == 2

    def test_get_events_limited(self, logger):
        for _ in range(10):
            logger.log(AuditEventType.LLM_CALL, success=True, details={})
        events = logger.get_events(limit=5)
        assert len(events) == 5

    def test_get_events_since_date(self, logger):
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        # All events should be recent
        events = logger.get_events(since=datetime(2020, 1, 1))
        assert len(events) >= 1

    def test_get_stats(self, logger):
        logger.log(AuditEventType.DRAFT_CREATED, success=True, details={})
        logger.log(AuditEventType.DRAFT_FAILED, success=False, details={}, error="err")
        stats = logger.get_stats()
        assert stats["total_events"] == 2
        assert stats["success_count"] == 1
        assert stats["failure_count"] == 1
        assert "draft_created" in stats["by_type"]
        assert "draft_failed" in stats["by_type"]

    def test_get_stats_empty(self, logger):
        stats = logger.get_stats()
        assert stats["total_events"] == 0
        assert stats["first_event"] is None
        assert stats["last_event"] is None

    def test_clear(self, logger):
        logger.log(AuditEventType.LLM_CALL, success=True, details={})
        logger.clear()
        events = logger.get_events()
        assert len(events) == 0

    def test_max_events_truncation(self, audit_file):
        logger = AuditLogger(filepath=audit_file, max_events=5)
        for i in range(10):
            logger.log(AuditEventType.LLM_CALL, success=True, details={"i": i})
        events = logger.get_events(limit=100)
        assert len(events) == 5

    def test_load_from_existing_file(self, audit_file):
        # Write some events
        logger1 = AuditLogger(filepath=audit_file)
        logger1.log(AuditEventType.DAEMON_START, success=True, details={})
        # Create new logger from same file
        logger2 = AuditLogger(filepath=audit_file)
        events = logger2.get_events()
        assert len(events) == 1

    def test_load_from_corrupted_file(self, audit_file):
        audit_file.write_text("not valid json")
        logger = AuditLogger(filepath=audit_file)
        # Should handle gracefully
        events = logger.get_events()
        assert len(events) == 0

    def test_log_with_all_optional_fields(self, logger):
        event = logger.log(
            event_type=AuditEventType.DRAFT_CREATED,
            success=True,
            details={"key": "val"},
            user="user1",
            email_id="e1",
            draft_id="d1",
            duration_ms=100,
        )
        assert event.user == "user1"
        assert event.email_id == "e1"
        assert event.duration_ms == 100
