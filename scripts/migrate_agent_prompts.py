#!/usr/bin/env python3
"""One-shot migration : extract hardcoded cron prompts → `agent_prompts` table.

Part of issue #261 Phase 2.

The 7 static cron prompts (muse, espion, journaliste, marketing, alpha_pro,
alpha_idiot, security_scan) are currently inlined as `issue.body` literals
inside their respective .py files in `ai_team/agents/cron/`. This script
extracts them (by importing each cron and introspecting the payload it would
enqueue) and writes them to the shared `agent_prompts` table in the graph
SQLite DB.

After migration, each cron will call `ai_team.lib.agent_prompts.load_prompt()`
at runtime. If the DB read fails, the hardcoded string remains as a safety net.

Idempotent: running twice bumps the version counter but keeps the same content.

Usage::

    python scripts/migrate_agent_prompts.py           # extract + write
    python scripts/migrate_agent_prompts.py --dry-run # print what would be written
    python scripts/migrate_agent_prompts.py --verify  # read back and diff
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# Ensure project root on sys.path so `ai_team.*` imports resolve regardless
# of where the script is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# These 7 crons have a static `issue.body` string that's a pure prompt.
# Others (ecrivain, support, pr_watcher, github_watcher, monitors, report)
# either build their body dynamically from GH/mailbox data, or don't call
# an LLM at all — they're out of scope for this migration.
_CRONS_WITH_STATIC_PROMPT: list[str] = [
    "muse",
    "espion",
    "journaliste",
    "marketing",
    "alpha_pro",
    "alpha_idiot",
    "security_scan",
]

# Role name in the DB (kebab-case, matches the `target_agent` convention).
_DB_ROLE_NAME: dict[str, str] = {
    "muse": "muse",
    "espion": "espion",
    "journaliste": "journaliste",
    "marketing": "marketing",
    "alpha_pro": "alpha-pro",
    "alpha_idiot": "alpha-idiot",
    "security_scan": "security",
}


def _extract_body_from_cron(cron_name: str) -> str | None:
    """Monkey-patch `queue.enqueue` to capture the payload `.issue.body`.

    We invoke the cron's `run()` once with a stubbed queue that records the
    payload instead of pushing to Redis. This avoids duplicating the prompt
    strings into this script (single source of truth = the cron file).

    Returns the body string, or None if extraction failed.
    """
    import importlib

    from ai_team.lib import queue as q

    captured: dict[str, str | None] = {"body": None}

    def _fake_enqueue(job_id: str, target_agent: str, payload: dict) -> int:  # noqa: ARG001
        issue = payload.get("issue", {}) if isinstance(payload, dict) else {}
        captured["body"] = (issue or {}).get("body")
        return 0  # bypass Redis

    original_enqueue = q.enqueue
    q.enqueue = _fake_enqueue  # type: ignore[assignment]

    # Also stub GitHub fetch calls inside ecrivain if we ever include it.
    try:
        mod = importlib.import_module(f"ai_team.agents.cron.{cron_name}")
        run_fn = getattr(mod, "run", None)
        if not callable(run_fn):
            return None
        run_fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  [error] {cron_name}: {exc}", file=sys.stderr)
        return None
    finally:
        q.enqueue = original_enqueue  # restore

    return captured["body"]


def _extract_all() -> dict[str, str]:
    """Extract prompts for all 7 crons. Returns {role: prompt}."""
    out: dict[str, str] = {}
    for cron_name in _CRONS_WITH_STATIC_PROMPT:
        body = _extract_body_from_cron(cron_name)
        if not body:
            print(f"  [skip] {cron_name}: no body extracted", file=sys.stderr)
            continue
        role = _DB_ROLE_NAME[cron_name]
        out[role] = body
    return out


def _write_all(prompts: dict[str, str]) -> int:
    """Write all prompts via the adapter's `set_role_prompt()`.

    Requires the `app` package to be importable (it is, since we added
    PROJECT_ROOT to sys.path at module top).
    """
    from app.config import SECOND_BRAIN_GRAPH_DB
    from app.infrastructure.second_brain_adapter import (
        SecondBrainAdapter,
        SecondBrainConfig,
    )

    adapter = SecondBrainAdapter(config=SecondBrainConfig(
        mempalace_graph_path=SECOND_BRAIN_GRAPH_DB,
    ))

    written = 0
    for role, prompt in prompts.items():
        ok = adapter.set_role_prompt(role, prompt, source="migrated")
        status = "ok" if ok else "fail"
        print(f"  [{status}] {role} ({len(prompt)} chars)")
        if ok:
            written += 1
    return written


def _verify(expected: dict[str, str]) -> int:
    """Read back and diff against expected. Return count of mismatches."""
    from ai_team.lib.agent_prompts import load_prompt

    mismatches = 0
    for role, want in expected.items():
        got = load_prompt(role)
        if got == want:
            print(f"  [match] {role}")
        else:
            print(
                f"  [MISMATCH] {role}: "
                f"expected {len(want)} chars, got {len(got)} chars",
                file=sys.stderr,
            )
            mismatches += 1
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print without writing")
    parser.add_argument("--verify", action="store_true", help="read back and diff")
    args = parser.parse_args()

    # Make sure ANTHROPIC_API_KEY is set (cron modules may reference it via
    # app.config, but we never call the LLM here — a placeholder is fine).
    os.environ.setdefault("ANTHROPIC_API_KEY", "migrate-placeholder")

    print("== Extraction ==")
    prompts = _extract_all()
    print(f"Extracted {len(prompts)} prompts from {len(_CRONS_WITH_STATIC_PROMPT)} crons\n")

    if args.dry_run:
        print("== Dry run preview ==")
        for role, prompt in prompts.items():
            preview = textwrap.shorten(prompt.replace("\n", " "), width=120)
            print(f"  {role:20s}  {preview}")
        return 0

    print("== Write ==")
    written = _write_all(prompts)
    print(f"\nWrote {written}/{len(prompts)} prompts to agent_prompts table\n")

    if args.verify or written == len(prompts):
        print("== Verify ==")
        mismatches = _verify(prompts)
        if mismatches:
            print(f"\n[FAIL] {mismatches} mismatch(es)", file=sys.stderr)
            return 1
        print("\n[OK] all prompts round-tripped cleanly")

    return 0


if __name__ == "__main__":
    sys.exit(main())
