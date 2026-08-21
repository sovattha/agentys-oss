#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Measure per-agent LLM token usage + latency for the onboarding scan.

Runs the four REAL onboarding worker agents (Profile / Knowledge / Style /
Label) on a fixture corpus through the real container — i.e. the actual Haiku
worker tier, the real prompts, and the real ``max_tokens`` caps the agents use
in production. No live Gmail account needed: it reads ``tests/fixtures/*.json``.

It prints, per agent:
  - input / output tokens (output is ~5x the price of input on Haiku),
  - ``used_pct`` = output / max_tokens (how much of the cap was consumed),
  - ``stop`` / ``trunc`` — ``max_tokens`` means the reply was truncated, so the
    cap must NOT be lowered; ``end_turn`` with a low used_pct means there is
    safe headroom to shrink it,
  - per-agent wall-clock latency.

And per run: the parallel wall-clock (the scan's analysis-phase latency floor,
since the agents run in a ThreadPoolExecutor) vs the sequential sum.

Usage:
    python scripts/measure_onboarding_tokens.py                  # default persona
    python scripts/measure_onboarding_tokens.py --persona startup_ceo
    python scripts/measure_onboarding_tokens.py --all-personas
    python scripts/measure_onboarding_tokens.py --fixture path/to/emails.json
    python scripts/measure_onboarding_tokens.py --all-personas --save
"""

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.onboarding.loader import FixtureLoader
from app.onboarding.indexer import EmailIndexer
from app.onboarding.agents.profile_agent import ProfileAgent
from app.onboarding.agents.knowledge_agent import KnowledgeAgent
from app.onboarding.agents.style_agent import StyleAgent
from app.onboarding.agents.label_agent import LabelAgent
from app.onboarding.agents import _usage_telemetry as tel

FIXTURES_DIR = ROOT / "tests" / "fixtures"
RESULTS_DIR = FIXTURES_DIR / "onboarding_token_runs"

# persona id -> fixture filename. "default" is the Sophie Martin corpus.
PERSONAS = {
    "default": "test_emails.json",
    "lawyer_paris": "test_emails_lawyer_paris.json",
    "sales_director": "test_emails_sales_director.json",
    "startup_ceo": "test_emails_startup_ceo.json",
    "hr_director": "test_emails_hr_director.json",
    "consultant_intl": "test_emails_consultant_intl.json",
}

# The four worker agents, in orchestrator order.
AGENTS = {
    "profile": ProfileAgent,
    "knowledge": KnowledgeAgent,
    "style": StyleAgent,
    "label": LabelAgent,
}


def _suggested_cap(max_out: int, truncated: bool) -> str:
    """Suggest a max_tokens cap from the observed output.

    Conservative: keep the cap when any run truncated, otherwise 1.5x the
    observed max output rounded up to the next 256, with a 256 floor. This is
    a *fixture-based* hint — real mailboxes vary, so apply with judgement.
    """
    if truncated:
        return "KEEP/RAISE (truncated)"
    if max_out <= 0:
        return "n/a"
    cap = int(math.ceil(max_out * 1.5 / 256.0)) * 256
    return str(max(256, cap))


def run_one(persona: str, fixture_path: Path) -> dict:
    """Run the 4 agents once on a fixture; return capture + timings."""
    emails, metadata = FixtureLoader(fixture_path).load()
    indexer = EmailIndexer(metadata.get("user_email", "user@example.com"))
    indexed = indexer.index(emails)

    print(f"\n=== {persona} ===  ({fixture_path.name})")
    print(f"  emails={len(emails)} sent={indexed.sent_count} "
          f"received={indexed.received_count} contacts={len(indexed.contact_metrics)} "
          f"threads={len(indexed.by_thread)} lang={indexed.primary_language.value}")

    tel.enable_capture()
    durations: dict[str, float] = {}
    errors: dict[str, str] = {}

    def _run(name: str):
        t0 = time.monotonic()
        try:
            AGENTS[name]().analyse(indexed)
        except Exception as e:  # capture-but-continue so one failure isn't fatal
            errors[name] = f"{type(e).__name__}: {e}"
        return name, (time.monotonic() - t0) * 1000.0

    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
        futures = {pool.submit(_run, n): n for n in AGENTS}
        for fut in as_completed(futures):
            name, dur = fut.result()
            durations[name] = dur
    wall_ms = (time.monotonic() - wall_start) * 1000.0

    records = tel.get_capture()
    tel.reset_capture()

    # Attach persona + wall-clock duration (telemetry's dur_ms is the LLM-call
    # time inside the agent; durations[] is the agent's full analyse() wall-time).
    by_agent = {r["agent"]: r for r in records}
    for name in AGENTS:
        rec = by_agent.get(name)
        if rec is None:
            by_agent[name] = {
                "agent": name, "error": errors.get(name, "no usage recorded"),
                "output_tokens": 0, "input_tokens": 0, "max_tokens": 0,
                "used_pct": 0.0, "stop_reason": "?", "truncated": False, "attempts": 0,
                "duration_ms": int(durations.get(name, 0)),
            }
        else:
            rec["persona"] = persona

    _print_table(by_agent, durations, wall_ms)
    return {
        "persona": persona,
        "fixture": fixture_path.name,
        "wall_ms": int(wall_ms),
        "agents": by_agent,
        "errors": errors,
    }


def _print_table(by_agent: dict, durations: dict, wall_ms: float) -> None:
    hdr = (f"  {'agent':<10} {'in':>6} {'out':>6} {'max':>6} {'used%':>6} "
           f"{'stop':>10} {'trunc':>6} {'try':>4} {'llm_ms':>7} {'wall_ms':>8}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    seq_sum = 0.0
    for name in AGENTS:
        r = by_agent[name]
        seq_sum += durations.get(name, 0)
        if "error" in r and r.get("attempts", 0) == 0:
            print(f"  {name:<10} {'ERROR: ' + r['error'][:60]}")
            continue
        print(f"  {name:<10} {r['input_tokens']:>6} {r['output_tokens']:>6} "
              f"{r['max_tokens']:>6} {r['used_pct']:>6.1f} {r['stop_reason']:>10} "
              f"{str(r['truncated']):>6} {r['attempts']:>4} {r['duration_ms']:>7} "
              f"{int(durations.get(name, 0)):>8}")
    print("  " + "-" * (len(hdr) - 2))
    print(f"  parallel wall-clock (latency floor): {int(wall_ms)} ms   "
          f"| sequential sum: {int(seq_sum)} ms")


def print_aggregate(runs: list[dict]) -> None:
    """Cross-persona summary used to right-size each agent's max_tokens."""
    print("\n\n================ AGGREGATE (across runs) ================")
    print(f"  {'agent':<10} {'max_out':>8} {'max_used%':>9} {'cur_max':>8} "
          f"{'truncated?':>11} {'suggested_max':>22}")
    print("  " + "-" * 74)
    for name in AGENTS:
        outs = [r["agents"][name]["output_tokens"] for r in runs if name in r["agents"]]
        useds = [r["agents"][name]["used_pct"] for r in runs if name in r["agents"]]
        caps = [r["agents"][name]["max_tokens"] for r in runs
                if name in r["agents"] and r["agents"][name]["max_tokens"]]
        trunc = any(r["agents"][name].get("truncated") for r in runs if name in r["agents"])
        max_out = max(outs) if outs else 0
        max_used = max(useds) if useds else 0.0
        cur_max = caps[0] if caps else 0
        print(f"  {name:<10} {max_out:>8} {max_used:>9.1f} {cur_max:>8} "
              f"{str(trunc):>11} {_suggested_cap(max_out, trunc):>22}")
    walls = [r["wall_ms"] for r in runs]
    print("  " + "-" * 74)
    if walls:
        print(f"  analysis-phase latency floor: min={min(walls)}ms "
              f"max={max(walls)}ms mean={int(sum(walls)/len(walls))}ms")
    print("  NOTE: fixture-based. Real mailboxes vary — the suggested cap is")
    print("        1.5x observed max output (next 256), only when never truncated.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persona", choices=list(PERSONAS.keys()))
    parser.add_argument("--all-personas", action="store_true")
    parser.add_argument("--fixture", metavar="PATH", help="custom fixture path")
    parser.add_argument("--save", action="store_true",
                        help="save JSON to tests/fixtures/onboarding_token_runs/")
    args = parser.parse_args()

    # Windows consoles default to cp1252 and choke on the table's box chars /
    # arrows; force UTF-8 so a run never crashes on output encoding.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    targets: list[tuple[str, Path]] = []
    if args.fixture:
        targets.append((Path(args.fixture).stem, Path(args.fixture)))
    elif args.all_personas:
        for pid, fname in PERSONAS.items():
            targets.append((pid, FIXTURES_DIR / fname))
    else:
        pid = args.persona or "default"
        targets.append((pid, FIXTURES_DIR / PERSONAS[pid]))

    runs = []
    for persona, path in targets:
        if not path.exists():
            print(f"  SKIP {persona}: fixture not found ({path})")
            continue
        runs.append(run_one(persona, path))

    if len(runs) > 1:
        print_aggregate(runs)
    elif runs:
        print_aggregate(runs)

    if args.save and runs:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  saved -> {out}")


if __name__ == "__main__":
    main()
