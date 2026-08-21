# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.pending_draft."""

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus


# ============================================================================
# PendingDraftStatus
# ============================================================================

class TestPendingDraftStatus:
    def test_all_values(self):
        assert PendingDraftStatus.PENDING.value == "pending"
        assert PendingDraftStatus.VALIDATED.value == "validated"
        assert PendingDraftStatus.SENT.value == "sent"
        assert PendingDraftStatus.REJECTED.value == "rejected"
        assert PendingDraftStatus.MODIFIED.value == "modified"


# ============================================================================
# PendingDraft
# ============================================================================

class TestPendingDraft:
    def test_create_default(self):
        draft = PendingDraft()
        assert draft.id  # UUID generated
        assert draft.status == PendingDraftStatus.PENDING
        assert draft.priority == 50
        assert draft.confidence == 0.85

    def test_create_with_values(self):
        draft = PendingDraft(
            email_id="e1",
            email_sender="alice@example.com",
            email_subject="Test",
            draft_body="Bonjour",
            priority=90,
        )
        assert draft.email_id == "e1"
        assert draft.priority == 90

    # --- to_dict ---

    def test_to_dict(self):
        draft = PendingDraft(
            id="test-id",
            email_id="e1",
            email_sender="alice@example.com",
            email_subject="Subject",
            status=PendingDraftStatus.VALIDATED,
        )
        d = draft.to_dict()
        assert d["id"] == "test-id"
        assert d["email_id"] == "e1"
        assert d["status"] == "validated"
        assert d["priority"] == 50

    def test_to_dict_status_as_string(self):
        """Status stored as string should serialize correctly."""
        draft = PendingDraft(id="t1")
        draft.status = "pending"  # type: ignore  # test backward compat
        d = draft.to_dict()
        assert d["status"] == "pending"

    # --- to_dict_summary ---

    def test_to_dict_summary_excludes_heavy_fields(self):
        draft = PendingDraft(
            id="test-id",
            email_body="Very long body content...",
            draft_body="Draft body content...",
            critique="Detailed critique...",
            conversation_history=[{"role": "user", "content": "msg1"}],
        )
        summary = draft.to_dict_summary()
        assert "email_body" not in summary
        assert "draft_body" not in summary
        assert "critique" not in summary
        assert "conversation_history" not in summary
        assert summary["conversation_history_count"] == 1

    def test_to_dict_summary_empty_history(self):
        draft = PendingDraft(id="t1")
        summary = draft.to_dict_summary()
        assert summary["conversation_history_count"] == 0

    # --- from_dict ---

    def test_from_dict_basic(self):
        data = {
            "id": "pd-1",
            "email_id": "e1",
            "email_sender": "bob@example.com",
            "email_subject": "Test",
            "status": "validated",
        }
        draft = PendingDraft.from_dict(data)
        assert draft.id == "pd-1"
        assert draft.status == PendingDraftStatus.VALIDATED

    def test_from_dict_missing_fields_use_defaults(self):
        data = {}
        draft = PendingDraft.from_dict(data)
        assert draft.email_id == ""
        assert draft.priority == 50
        assert draft.confidence == 0.85
        assert draft.status == PendingDraftStatus.PENDING

    def test_from_dict_with_enum_status(self):
        data = {"status": "rejected"}
        draft = PendingDraft.from_dict(data)
        assert draft.status == PendingDraftStatus.REJECTED

    def test_from_dict_with_specialty_info(self):
        data = {
            "specialty_info": {"specialty_id": "sp1", "category": "legal"},
        }
        draft = PendingDraft.from_dict(data)
        assert draft.specialty_info["specialty_id"] == "sp1"

    # --- Roundtrip ---

    def test_to_dict_from_dict_roundtrip(self):
        original = PendingDraft(
            id="rt-1",
            email_id="e1",
            email_sender="alice@example.com",
            email_subject="Round trip test",
            draft_body="Hello",
            classification="URGENT",
            priority=85,
            status=PendingDraftStatus.MODIFIED,
        )
        d = original.to_dict()
        restored = PendingDraft.from_dict(d)
        assert restored.id == original.id
        assert restored.email_sender == original.email_sender
        assert restored.classification == original.classification
        assert restored.priority == original.priority
        assert restored.status == original.status
