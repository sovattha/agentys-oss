# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the 2026-05-30 launch-hardening fix batch.

Each test FAILS if the corresponding fix is reverted.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Tier-0 #2 — deleting a Savoir / saving /api/memory must NOT wipe the FAQ KB.
# Root cause: parse_knowledge_markdown was not the inverse of
# build_knowledge_markdown for FAQ blocks, so _save_to_db's wholesale
# knowledge_json overwrite dropped every FAQ entry on any memory save.
# ---------------------------------------------------------------------------

def _build():
    from app.onboarding.manager import build_knowledge_markdown
    return build_knowledge_markdown


def _parse():
    from app.onboarding.manager import parse_knowledge_markdown
    return parse_knowledge_markdown


def test_faq_survives_knowledge_markdown_roundtrip():
    knowledge = {
        "contacts": [],
        "faq": [
            {"category": "BILLING", "question": "How do I get a refund?",
             "answer": "Email support within 30 days.", "context": "EU customers"},
            {"category": "GENERAL", "question": "What are your hours?",
             "answer": "9-5 CET."},
        ],
    }
    md = _build()({"user_name": "Alex"}, knowledge, {})
    _profile, parsed, _rules = _parse()(md)

    faq = parsed.get("faq", [])
    assert len(faq) == 2, f"FAQ wiped on round-trip — got {len(faq)}/2"
    by_q = {f["question"]: f for f in faq}
    assert "How do I get a refund?" in by_q
    assert "What are your hours?" in by_q
    billing = by_q["How do I get a refund?"]
    assert billing["answer"] == "Email support within 30 days."
    assert billing["category"] == "BILLING"
    assert billing.get("context") == "EU customers"


def test_deleting_one_faq_block_keeps_the_rest():
    """Simulates delete_savoir → update_memory → _save_to_db re-parse: the
    full updated markdown (minus one block) must still yield the remaining FAQ,
    never collapse to zero."""
    knowledge = {"contacts": [], "faq": [
        {"category": "BILLING", "question": "Refund?", "answer": "Yes within 30d."},
        {"category": "GENERAL", "question": "Hours?", "answer": "9-5."},
    ]}
    md = _build()({}, knowledge, {})
    # Drop the BILLING block the way delete_savoir splices it out: keep only the
    # GENERAL ### block region. Easiest faithful sim — re-parse full md (both
    # present) then assert the parser kept both (so a later single-delete leaves one).
    _p, k, _r = _parse()(md)
    assert len(k["faq"]) == 2
    # Now remove the first FAQ block from the rendered markdown and re-parse.
    lines = md.split("\n")
    # find the two "### " FAQ headers
    idxs = [i for i, ln in enumerate(lines) if ln.startswith("### ") and " : " in ln]
    assert len(idxs) == 2
    # delete from the first ### header up to (not including) the second
    del lines[idxs[0]:idxs[1]]
    _p2, k2, _r2 = _parse()("\n".join(lines))
    assert len(k2["faq"]) == 1, "deleting one FAQ block should leave exactly one"
    assert k2["faq"][0]["question"] == "Hours?"
