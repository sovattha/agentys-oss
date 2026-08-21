#!/usr/bin/env python
"""Run the SelfCritique eval via `claude -p` subprocess (uses Claude Code budget).

This is a fallback runner used when the Anthropic API key has no credit. It
shells out to `claude -p --bare` for each case instead of going through
`Container.llm_label`. Every other piece of the eval is identical to
`scripts/eval_self_critique.py` — same dataset, same prompts, same per-case
JSON shape — so the output can be replayed through
`scripts/eval_replay_deployed_gate.py` to derive the deployed gate verdict.

CRITICAL CAVEAT — model substitution: `claude -p` uses the user's CLI default
model (typically Sonnet or Opus), NOT the Haiku 4.5 the prod SelfCritique
agent uses. The verdict therefore answers "is the gate rule sound on these
cases?" but NOT "does Haiku produce the right rubric outputs?". The
2026-04-30 eval already validated Haiku-the-model on this dataset.

Usage:
    python scripts/eval_self_critique_via_claude_pipe.py --limit 5         # smoke
    python scripts/eval_self_critique_via_claude_pipe.py --limit 200       # full
    python scripts/eval_self_critique_via_claude_pipe.py --limit 200 --parallel 4

Output : a JSON file matching the shape of
`tasks/eval-self-critique-live-2026-04-30.json` so the replay script just works.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from app.prompts.self_critique import (  # noqa: E402
    get_self_critique_system_prompt,
    get_self_critique_user_prompt,
)
from eval_dataset import ALL_CASES, EvalCase  # noqa: E402


# Reuse the existing 2026-04-30 critic decisions instead of re-running them —
# Critic was already paid for on Haiku, and we want apples-to-apples with the
# replay script.
_PRIOR_EVAL = _REPO / "tasks" / "eval-self-critique-live-2026-04-30.json"

# Per CLAUDE.md docs/claude-pipe-mode.md guidance: filter CLAUDE_* and
# ANTHROPIC_API_KEY from the env, set tools to none, strict MCP, /tmp cwd.
_SUBPROCESS_TIMEOUT_S = 90


def _build_subprocess_env() -> dict[str, str]:
    """Strip everything that would leak parent-session config into claude -p.

    Audit F-05 (2026-05-03): the previous filter only dropped
    ``ANTHROPIC_API_KEY``, leaving routing vars (``ANTHROPIC_BASE_URL``,
    ``ANTHROPIC_MODEL``, ``ANTHROPIC_VERTEX_PROJECT_ID`` …) intact. A
    miscalibrated eval determinism feeds the wrong gate rollout decision,
    so we drop the entire ``ANTHROPIC_*`` and ``CLAUDE*`` prefix.
    """
    out = {
        k: v for k, v in os.environ.items()
        if not k.startswith("CLAUDE") and not k.startswith("ANTHROPIC_")
    }
    return out


def _safe_cwd() -> str:
    """A directory with no CLAUDE.md / settings.json that could pollute context."""
    # On Windows, Python's tempdir is a safe analogue to /tmp.
    import tempfile
    return tempfile.gettempdir()


_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a `claude -p` response.

    `--bare` should give us pure JSON, but Sonnet/Opus occasionally still wrap
    output in code fences or add a trailing newline. Be tolerant.
    """
    if not text:
        return None
    # Try the easy case first.
    s = text.strip()
    if s.startswith("```"):
        # Strip ```json fences if any.
        s = s.lstrip("`").lstrip("json").strip()
        if s.endswith("```"):
            s = s[:-3].rstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fallback : grab the first {...} blob.
    m = _JSON_OBJECT_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _run_claude_pipe(system_prompt: str, user_prompt: str) -> tuple[str, int, str]:
    """Single claude -p invocation. Returns (stdout, returncode, stderr)."""
    cmd = [
        "claude", "-p",
        "--bare",
        "--strict-mcp-config",
        "--allowedTools", "",
        "--append-system-prompt", system_prompt,
        user_prompt,
    ]
    try:
        result = subprocess.run(
            cmd,
            env=_build_subprocess_env(),
            cwd=_safe_cwd(),
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout, result.returncode, result.stderr
    except subprocess.TimeoutExpired:
        return "", -1, f"timeout after {_SUBPROCESS_TIMEOUT_S}s"
    except Exception as e:
        return "", -2, f"subprocess error: {e}"


@dataclass
class CaseResult:
    case_id: str
    category: str
    mode: str
    expected_risks: list[str]
    expected_a_confirmer_count: int
    self_score: int = 0
    self_risks: list[str] = field(default_factory=list)
    self_a_confirmer: int = 0
    self_confidence: str = "low"
    self_failure_reason: str = ""
    self_latency_ms: int = 0
    would_escalate: bool = True
    # Filled from prior 2026-04-30 eval — apples-to-apples Critic decision.
    critic_decision: str = ""
    critic_score: int = 0
    critic_latency_ms: int = 0


def _load_prior_critic_map() -> dict[str, dict]:
    """Load the 2026-04-30 eval results, indexed by case_id, for Critic fields."""
    if not _PRIOR_EVAL.exists():
        return {}
    try:
        payload = json.loads(_PRIOR_EVAL.read_text(encoding="utf-8"))
        return {r["case_id"]: r for r in payload.get("results", [])}
    except Exception as e:
        print(f"[WARN] could not load prior eval: {e}", file=sys.stderr)
        return {}


def _evaluate_one(case: EvalCase, prior_critic: dict[str, dict]) -> CaseResult:
    cr = CaseResult(
        case_id=case.case_id,
        category=case.category,
        mode=case.mode,
        expected_risks=list(case.expected_risks),
        expected_a_confirmer_count=case.expected_a_confirmer_count,
    )

    sys_p = get_self_critique_system_prompt()
    user_p = get_self_critique_user_prompt(case.draft_v1, case.email_in, mode=case.mode)

    t0 = time.time()
    stdout, rc, stderr = _run_claude_pipe(sys_p, user_p)
    cr.self_latency_ms = int((time.time() - t0) * 1000)

    if rc != 0:
        cr.self_failure_reason = f"claude -p exit={rc} stderr={stderr.strip()[:200]}"
    else:
        parsed = _extract_json(stdout)
        if parsed is None:
            cr.self_failure_reason = f"json_parse_failed: {stdout.strip()[:200]}"
        else:
            try:
                cr.self_score = max(0, min(100, int(parsed.get("self_score", 0))))
            except (TypeError, ValueError):
                cr.self_score = 0
            risks = parsed.get("risks") or []
            if isinstance(risks, list):
                from app.domain.entities.self_critique import RISK_CATEGORIES
                cr.self_risks = [r for r in risks if isinstance(r, str) and r in RISK_CATEGORIES]
            try:
                cr.self_a_confirmer = max(0, int(parsed.get("a_confirmer_count", 0)))
            except (TypeError, ValueError):
                cr.self_a_confirmer = 0
            conf = parsed.get("confidence", "low")
            cr.self_confidence = conf if conf in ("low", "med", "high") else "low"

    # Copy Critic decision from prior eval — same case_id, same draft, so the
    # decision is reusable. This is what makes the run only ½ as expensive.
    prior = prior_critic.get(case.case_id)
    if prior:
        cr.critic_decision = prior.get("critic_decision", "")
        cr.critic_score = prior.get("critic_score", 0)
        cr.critic_latency_ms = prior.get("critic_latency_ms", 0)

    return cr


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SelfCritique eval via claude -p")
    parser.add_argument("--limit", type=int, default=None, help="Limit cases (smoke test)")
    parser.add_argument("--parallel", type=int, default=4, help="Concurrent claude -p calls")
    parser.add_argument(
        "--out", type=Path,
        default=_REPO / "tasks" / "eval-self-critique-via-claude-pipe-2026-05-03.json",
    )
    args = parser.parse_args()

    prior_critic = _load_prior_critic_map()
    if not prior_critic:
        print("[WARN] no prior critic decisions found — verdict will lack Critic comparison",
              file=sys.stderr)

    cases = ALL_CASES[:args.limit] if args.limit else ALL_CASES
    n = len(cases)
    print(f"[start] {n} cases via claude -p, parallel={args.parallel}", file=sys.stderr)

    results: list[CaseResult] = []
    t_start = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(_evaluate_one, c, prior_critic): c for c in cases}
        for fut in as_completed(futures):
            try:
                cr = fut.result()
            except Exception as e:
                c = futures[fut]
                print(f"[FAIL] {c.case_id}: {e}", file=sys.stderr)
                continue
            results.append(cr)
            done += 1
            if done % 10 == 0 or done == n:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed else 0
                eta = (n - done) / rate if rate else 0
                fail_count = sum(1 for r in results if r.self_failure_reason)
                print(
                    f"  {done}/{n} done ({elapsed:.0f}s elapsed, ETA {eta:.0f}s, "
                    f"{fail_count} failures so far)",
                    file=sys.stderr,
                )

    # Aggregates (only the fields the replay script actually reads)
    successes = [r for r in results if not r.self_failure_reason]
    payload = {
        "aggregates": {
            "total": len(results),
            "successes": len(successes),
            "failures": len(results) - len(successes),
            "self_avg_score": round(statistics.mean(r.self_score for r in successes), 1) if successes else 0,
            "self_p50_latency_ms": int(statistics.median(r.self_latency_ms for r in results)) if results else 0,
            "self_p95_latency_ms": int(_pct((r.self_latency_ms for r in results), 95)) if results else 0,
            "model": "claude-cli-default (Sonnet/Opus, not Haiku)",
            "method": "claude -p subprocess",
            "wall_time_s": round(time.time() - t_start, 1),
        },
        "results": [asdict(r) for r in results],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {args.out}", file=sys.stderr)
    print(f"[ok] {len(successes)}/{len(results)} successful, "
          f"{payload['aggregates']['self_avg_score']} avg self_score, "
          f"{payload['aggregates']['wall_time_s']}s wall", file=sys.stderr)
    return 0


def _pct(values, p):
    s = sorted(values)
    if not s:
        return 0
    k = (len(s) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


if __name__ == "__main__":
    sys.exit(main())
