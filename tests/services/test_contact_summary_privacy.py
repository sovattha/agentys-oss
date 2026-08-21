"""Tests for contact summary minimization helpers."""

from __future__ import annotations

import json

from app.contact_summary_privacy import (
    minimize_contact_summary,
    minimize_contact_summary_json,
)


def test_minimize_contact_summary_drops_free_text_memory():
    summary = {
        "relation_type": "client",
        "habitual_tone": "formal",
        "language": "fr",
        "recurring_topics": ["projet confidentiel"],
        "user_formulas_opening": ["Bonjour Jean,"],
        "contact_formulas_opening": ["Salut Nat,"],
        "key_facts": ["vit à Montréal"],
        "last_interaction_summary": "A demandé une information privée.",
    }

    assert minimize_contact_summary(summary) == {
        "relation_type": "client",
        "habitual_tone": "formal",
        "language": "fr",
    }


def test_minimize_contact_summary_json_drops_invalid_labels_and_bad_json():
    assert minimize_contact_summary_json("{not json") == "{}"
    payload = json.dumps(
        {
            "relation_type": "VIP client with confidential deal",
            "habitual_tone": "formal",
            "language": "fr",
            "key_facts": ["secret"],
        }
    )

    assert json.loads(minimize_contact_summary_json(payload)) == {
        "habitual_tone": "formal",
        "language": "fr",
    }
