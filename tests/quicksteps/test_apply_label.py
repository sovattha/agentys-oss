# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the `apply_label` Quick Step action.

Covers:
  - schema validation (allowlist, payload.label required + non-empty)
  - handler adds a custom label onto a fresh assignment
  - handler preserves an existing assignment's category + custom labels
  - handler routes a default-category name onto default_label
  - missing/empty label → ok=False; no label store → ok=False
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.domain.entities.email_labels import LabelAssignment
from app.quicksteps import schema
from app.quicksteps.handlers.apply_label import handle_apply_label
from app.quicksteps.types import ExecutionContext


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #

class _FakeStore:
    """Minimal LabelStore double — only the surface handle_apply_label uses."""
    def __init__(self, existing: LabelAssignment | None = None):
        self.existing = existing
        self.saved: LabelAssignment | None = None

    def get_assignment(self, email_id: str) -> LabelAssignment | None:
        return self.existing

    def save_assignment(self, assignment: LabelAssignment) -> None:
        self.saved = assignment


class _FakeContainer:
    def __init__(self, store: _FakeStore | None):
        self._store = store

    def get_label_store(self, account_id=None):
        return self._store


def _ctx(**overrides) -> ExecutionContext:
    defaults = dict(
        provider=None,
        account_id=42,
        account_email="me@x.com",
        account_display_name="Me",
        email=None,
        email_id="msg-1",
        raw_id="msg-1",
        template_vars={},
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def _run(store: _FakeStore | None, payload: dict):
    with patch(
        "app.infrastructure.container.get_container",
        return_value=_FakeContainer(store),
    ):
        return handle_apply_label(_ctx(), payload)


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def _step(actions):
    return {"id": str(uuid.uuid4()), "name": "x", "actions": actions}


class TestApplyLabelSchema:
    def test_valid_label_round_trips(self):
        cleaned = schema.validate_quick_step(
            _step([{"type": "apply_label", "payload": {"label": "VIP"}}])
        )
        assert cleaned["actions"][0] == {
            "type": "apply_label",
            "payload": {"label": "VIP"},
        }

    def test_label_is_stripped(self):
        cleaned = schema.validate_quick_step(
            _step([{"type": "apply_label", "payload": {"label": "  Client  "}}])
        )
        assert cleaned["actions"][0]["payload"]["label"] == "Client"

    def test_missing_label_rejected(self):
        with pytest.raises(schema.ValidationError, match="apply_label.label"):
            schema.validate_quick_step(
                _step([{"type": "apply_label", "payload": {}}])
            )

    def test_empty_label_rejected(self):
        with pytest.raises(schema.ValidationError, match="apply_label.label"):
            schema.validate_quick_step(
                _step([{"type": "apply_label", "payload": {"label": "   "}}])
            )

    def test_oversized_label_rejected(self):
        too_long = "x" * (schema.LABEL_NAME_MAX_LENGTH + 1)
        with pytest.raises(schema.ValidationError, match="apply_label.label"):
            schema.validate_quick_step(
                _step([{"type": "apply_label", "payload": {"label": too_long}}])
            )


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #

class TestApplyLabelHandler:
    def test_missing_label_returns_error(self):
        store = _FakeStore()
        result = _run(store, {})
        assert result.ok is False
        assert result.error == "apply_label_missing_label"
        assert store.saved is None

    def test_empty_label_returns_error(self):
        store = _FakeStore()
        result = _run(store, {"label": "   "})
        assert result.ok is False
        assert result.error == "apply_label_missing_label"

    def test_no_label_store_returns_error(self):
        result = _run(None, {"label": "VIP"})
        assert result.ok is False
        assert result.error == "label_store_unavailable"

    def test_adds_custom_label_to_fresh_assignment(self):
        # No prior assignment → handler starts a fresh rule-assigned record.
        store = _FakeStore(existing=None)
        result = _run(store, {"label": "VIP"})
        assert result.ok is True
        assert store.saved is not None
        assert store.saved.email_id == "msg-1"
        assert "VIP" in store.saved.labels
        assert "VIP" in store.saved.custom_labels
        assert store.saved.assigned_by == "rule"

    def test_preserves_existing_assignment(self):
        # An existing assignment (classifier category + a custom label) must
        # survive — the new label is added alongside, not replacing it.
        existing = LabelAssignment(email_id="msg-1", assigned_by="ai")
        existing.set_default_label("Action", 0.9, "classifier")
        existing.add_custom_label("Client", 1.0, "classifier")
        store = _FakeStore(existing=existing)

        result = _run(store, {"label": "VIP"})
        assert result.ok is True
        assert store.saved.default_label == "Action"
        assert "Client" in store.saved.labels
        assert "VIP" in store.saved.labels

    def test_default_category_name_sets_default_label(self):
        # A default-category name routes to default_label via
        # LabelAssignment.add_label, not into custom_labels.
        store = _FakeStore(existing=None)
        result = _run(store, {"label": "Noise"})
        assert result.ok is True
        assert store.saved.default_label == "Noise"

    def test_label_is_stripped_before_apply(self):
        store = _FakeStore(existing=None)
        result = _run(store, {"label": "  Urgent  "})
        assert result.ok is True
        assert "Urgent" in store.saved.labels
        assert "  Urgent  " not in store.saved.labels
