#!/usr/bin/env python
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI tool for hand-labelling AI drafts to build a ground-truth set.

Audit 2026-05-04: every Critic / SelfCritique / gate metric we have is
gate-vs-Critic agreement, never gate-vs-truth. The runbook flagged this
as bloquant for rigorous validation. This tool unblocks it.

Corpus: 60 real-style drafts from
``tests/fixtures/drafting_eval_runs/<run>/<persona>.json``, joined to
their source emails in ``tests/fixtures/test_emails_<persona>.json``
via ``case_id`` ↔ ``id``. The drafts cover 6 personas (consultant,
HR director, lawyer, sales director, startup CEO, default) across 2
eval runs from 2026-04-17, so the distribution is closer to prod than
the 50-good / 150-risky synthetic dataset.

Labelling workflow:
    python scripts/label_drafts_for_ground_truth.py
    # → for each case:
    #   - shows the original email body + AI draft
    #   - asks "would you send this draft AS-IS to the recipient?"
    #   - records [g]ood / [b]ad / [s]kip / [n]ote / [q]uit
    #   - saves to tasks/ground-truth-drafts-2026-05-04.json after EVERY label

Resume support: re-running picks up where you left off. Already-labelled
cases are skipped automatically. ``--review`` mode lets you re-visit
cases you already labelled.

Once 50+ cases are labelled, downstream analysis lives in
``scripts/analyze_critic_vs_ground_truth.py`` (separate, runs the prod
Critic on each labelled case and reports per-dimension disagreement
patterns — that's what informs the rubric tuning).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO / "tasks" / "ground-truth-drafts-2026-05-04.json"

# 6 personas × 2 runs × ~5 cases each = ~60 unique drafts.
_RUNS = [
    "run_20260417_153024",
    "run_20260417_161839",
]
_PERSONAS = [
    "consultant_intl", "default", "hr_director",
    "lawyer_paris", "sales_director", "startup_ceo",
]


def _load_email_corpus() -> dict[tuple[str, str], dict]:
    """Index emails by (persona, case_id) so we can look up the source email."""
    index: dict[tuple[str, str], dict] = {}
    for persona in _PERSONAS:
        # `default.json` corresponds to `test_emails.json` (no persona suffix)
        fname = "test_emails.json" if persona == "default" else f"test_emails_{persona}.json"
        path = _REPO / "tests" / "fixtures" / fname
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] could not load {path}: {e}", file=sys.stderr)
            continue
        emails = payload.get("emails") if isinstance(payload, dict) else payload
        if not isinstance(emails, list):
            continue
        for e in emails:
            if not isinstance(e, dict):
                continue
            cid = e.get("id") or e.get("case_id")
            if cid:
                index[(persona, cid)] = e
    return index


def _load_draft_cases() -> list[dict]:
    """Return list of {persona, run, case_id, subject, draft, critic, judge}."""
    cases: list[dict] = []
    for run in _RUNS:
        for persona in _PERSONAS:
            path = _REPO / "tests" / "fixtures" / "drafting_eval_runs" / run / f"{persona}.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[warn] could not load {path}: {e}", file=sys.stderr)
                continue
            for c in payload.get("cases", []):
                if not isinstance(c, dict):
                    continue
                cases.append({
                    "persona": persona,
                    "run": run,
                    "case_id": c.get("case_id", ""),
                    "subject": c.get("subject", ""),
                    "draft": c.get("draft", ""),
                    "critic": c.get("critic", {}),
                    # We deliberately do NOT show ``judge`` to the labeller
                    # — they'd bias toward the LLM judge's verdict rather
                    # than expressing their own.
                })
    return cases


def _load_existing_labels() -> dict[str, dict]:
    """Return labels indexed by stable key (persona+run+case_id)."""
    if not _OUTPUT.exists():
        return {}
    try:
        payload = json.loads(_OUTPUT.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] could not parse existing labels at {_OUTPUT}: {e}", file=sys.stderr)
        return {}
    return {r["key"]: r for r in payload.get("labels", []) if "key" in r}


def _save_labels(labels: dict[str, dict]) -> None:
    """Write labels to disk atomically — write tmp + rename."""
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = _OUTPUT.with_suffix(".json.tmp")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labels": list(labels.values()),
    }
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_OUTPUT)


def _key_for(case: dict) -> str:
    return f"{case['persona']}|{case['run']}|{case['case_id']}"


def _print_case(idx: int, total: int, case: dict, email: Optional[dict]) -> None:
    print()
    print("=" * 78)
    print(f"  CASE {idx} / {total}    persona={case['persona']}    case_id={case['case_id']}")
    print("=" * 78)
    if email:
        sender = email.get("from", "?")
        subject = email.get("subject", "")
        body = (email.get("body") or email.get("content") or "")[:1500]
        print("\n--- INCOMING EMAIL ---")
        print(f"From:    {sender}")
        print(f"Subject: {subject}")
        print()
        print(body)
        if len(email.get("body", "")) > 1500:
            print(f"... [truncated, full body is {len(email['body'])} chars]")
    else:
        print(f"\n--- (no source email indexed for case_id={case['case_id']}) ---")
        print(f"Subject: {case.get('subject', '')}")
    print()
    print("--- AI DRAFT ---")
    print(case.get("draft", "(empty)"))
    print()
    print("=" * 78)


def _prompt(idx: int, total: int) -> tuple[str, str]:
    """Returns (verdict, note). verdict ∈ {good, bad, skip, back, quit}."""
    while True:
        print()
        print(f"[{idx}/{total}]  Would you SEND this draft AS-IS to the recipient?")
        print("  [g] yes — would send unchanged")
        print("  [b] no  — needs revision before sending")
        print("  [n] no  — and add a free-text note")
        print("  [s] skip (re-show later)")
        print("  [<] go back (re-label previous case)")
        print("  [q] save & quit")
        choice = input("> ").strip().lower()
        if choice in ("g", "good"):
            return "good", ""
        if choice in ("b", "bad"):
            return "bad", ""
        if choice in ("n", "note"):
            print("Note (single line, what's wrong / what to fix): ", end="")
            return "bad", input().strip()
        if choice in ("s", "skip"):
            return "skip", ""
        if choice in ("<", "back"):
            return "back", ""
        if choice in ("q", "quit", "exit"):
            return "quit", ""
        print("Unknown choice. Use g / b / n / s / < / q.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Label AI drafts for ground truth")
    parser.add_argument("--review", action="store_true",
                        help="Re-visit already-labelled cases (default: skip them)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after labelling N new cases (for short sessions)")
    args = parser.parse_args()

    email_index = _load_email_corpus()
    cases = _load_draft_cases()
    labels = _load_existing_labels()

    total_cases = len(cases)
    print(f"[init] {total_cases} drafts available, {len(labels)} already labelled")

    if total_cases == 0:
        print("No cases found — check that drafting_eval_runs/ fixtures exist.",
              file=sys.stderr)
        return 1

    pending: list[dict] = [
        c for c in cases
        if args.review or _key_for(c) not in labels
        or labels[_key_for(c)].get("verdict") == "skip"
    ]
    if not pending:
        print("All cases already labelled. Use --review to re-visit.")
        return 0

    print(f"[start] {len(pending)} pending — saving to {_OUTPUT}")
    print("        Tip: hit `q` any time, your progress is auto-saved per case.\n")

    i = 0
    new_count = 0
    while i < len(pending):
        if args.limit is not None and new_count >= args.limit:
            print(f"[stop] hit --limit {args.limit}")
            break

        case = pending[i]
        email = email_index.get((case["persona"], case["case_id"]))
        _print_case(i + 1, len(pending), case, email)

        verdict, note = _prompt(i + 1, len(pending))

        if verdict == "quit":
            print(f"[saved] {len(labels)} labels in {_OUTPUT}")
            return 0
        if verdict == "back":
            i = max(0, i - 1)
            continue
        if verdict == "skip":
            # Record skip so re-runs surface it again.
            labels[_key_for(case)] = {
                "key": _key_for(case),
                "case_id": case["case_id"],
                "persona": case["persona"],
                "run": case["run"],
                "verdict": "skip",
                "labelled_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_labels(labels)
            i += 1
            continue

        # verdict ∈ {good, bad}
        critic = case.get("critic") or {}
        labels[_key_for(case)] = {
            "key": _key_for(case),
            "case_id": case["case_id"],
            "persona": case["persona"],
            "run": case["run"],
            "subject": case.get("subject", ""),
            "draft": case.get("draft", ""),
            "verdict": verdict,
            "note": note,
            "critic_decision_at_eval_time": critic.get("decision", ""),
            "critic_overall_at_eval_time": critic.get("overall", -1),
            "labelled_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_labels(labels)
        new_count += 1
        i += 1

    print(f"\n[done] labelled {new_count} new cases this session")
    print(f"[total] {sum(1 for v in labels.values() if v.get('verdict') in ('good', 'bad'))} "
          f"actionable labels in {_OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
