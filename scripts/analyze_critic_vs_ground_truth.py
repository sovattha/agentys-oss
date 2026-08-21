#!/usr/bin/env python
"""Analyse the prod Critic against hand-labelled ground truth.

Audit 2026-05-04 step 4 : every prior eval was Critic-vs-Critic agreement.
This run pits the current prod Critic (Haiku 4.5 via the structured rubric)
against actual human verdicts from
``tasks/ground-truth-drafts-2026-05-04.json`` and surfaces the dimensions
where Critic systematically disagrees with humans.

Output :
    tasks/critic-vs-ground-truth-2026-05-04.json — per-case raw data
    tasks/critic-vs-ground-truth-2026-05-04.md   — verdict summary

Cost : 60 Haiku Critic calls × ~$0.0023 = ~$0.14. ~1 min wall at parallel=4.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

import anthropic  # noqa: E402

from app.prompts.builders import (  # noqa: E402
    get_critic_structured_system_prompt,
    get_critic_structured_user_prompt,
)
from app.utils.json_parser import extract_json_from_response  # noqa: E402

_LABELS_FILE = _REPO / "tasks" / "ground-truth-drafts-2026-05-04.json"
_OUT_JSON = _REPO / "tasks" / "critic-vs-ground-truth-2026-05-04.json"
_OUT_MD = _REPO / "tasks" / "critic-vs-ground-truth-2026-05-04.md"

# Match the deployed prod Critic exactly.
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 250  # matches MAX_TOKENS_CRITIC

_PERSONAS = [
    "consultant_intl", "default", "hr_director",
    "lawyer_paris", "sales_director", "startup_ceo",
]

_SCORE_KEYS = (
    "coherence", "tone", "completeness", "errors",
    "conciseness", "over_commitment", "emotional_intelligence",
)

# Markers that should always force decision=reject regardless of LLM output.
# Mirror of the post-LLM `_strip_a_confirmer` triggers — kept in sync with
# `app/smart_routing.py:_BARE_PLACEHOLDER_TRIGGER_RE` and friends.
_PLACEHOLDER_MARKERS = (
    "[À confirmer]", "[à confirmer]", "[A confirmer]", "[a confirmer]",
    "[à valider]", "[à vérifier]", "[a verifier]",
    "[TBD]", "[REDACTE]", "[redacte]",
    "[placeholder", "[X]",
)


def _draft_has_placeholder(draft: str) -> bool:
    if not draft:
        return False
    return any(m in draft for m in _PLACEHOLDER_MARKERS)


def _deterministic_decision(scores: dict, draft: str, threshold: int = 70) -> str:
    """Compute decision from scores + placeholder presence, ignoring the LLM's
    own ``decision`` field.

    Audit 2026-05-04 step 5 : we observed Haiku Critic emit `decision: reject`
    with `overall=87, no dim<50` because of stylistic preferences ("ajouter
    signature complète"). The LLM's decision call is unreliable. Score-based
    determinism removes the variance.
    """
    if _draft_has_placeholder(draft):
        return "reject"
    if any(s < 50 for s in scores.values()):
        return "reject"
    overall = sum(scores.values()) / max(1, len(scores))
    return "valid" if overall >= threshold else "reject"


@dataclass
class CriticVerdict:
    decision: str            # "valid" | "reject" | "parse_failed"
    overall: int
    scores: dict
    suggestions: list = field(default_factory=list)
    raw_excerpt: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CaseAnalysis:
    case_id: str
    persona: str
    run: str
    human_verdict: str       # "good" | "bad"
    human_note: str
    subject: str
    draft: str
    email_body: str
    critic: CriticVerdict
    error: str = ""

    @property
    def disagreement(self) -> str:
        """Type of disagreement between human and Critic."""
        if self.human_verdict == "good" and self.critic.decision == "reject":
            return "FP"   # human says good, Critic falsely rejects
        if self.human_verdict == "bad" and self.critic.decision == "valid":
            return "FN"   # human says bad, Critic falsely validates
        if self.human_verdict == "good" and self.critic.decision == "valid":
            return "TP"
        if self.human_verdict == "bad" and self.critic.decision == "reject":
            return "TN"
        return "?"


def _load_email_index() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for persona in _PERSONAS:
        fname = "test_emails.json" if persona == "default" else f"test_emails_{persona}.json"
        path = _REPO / "tests" / "fixtures" / fname
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in (payload.get("emails") if isinstance(payload, dict) else payload) or []:
            if isinstance(e, dict):
                cid = e.get("id") or e.get("case_id")
                if cid:
                    out[(persona, cid)] = e
    return out


def _parse_critique(raw: str, draft: str) -> tuple[str, int, dict, list]:
    """Parse the LLM's critique JSON and override the decision field with
    a deterministic computation from the scores + placeholder check."""
    data = extract_json_from_response(raw)
    if not data:
        return "parse_failed", 0, {}, []
    scores = {}
    for k in _SCORE_KEYS:
        v = data.get(k, 50)
        try:
            scores[k] = max(0, min(100, int(v)))
        except (TypeError, ValueError):
            scores[k] = 50
    overall = sum(scores.values()) // len(scores)
    decision = _deterministic_decision(scores, draft)
    return decision, overall, scores, data.get("suggestions") or []


def _run_critic(client, kb: str, email_body: str, draft: str) -> CriticVerdict:
    system = get_critic_structured_system_prompt(kb, contact="", account_id=None)
    user = get_critic_structured_user_prompt(
        email_content=email_body, draft=draft, context=None, threshold=70,
    )
    t0 = time.time()
    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    latency_ms = int((time.time() - t0) * 1000)
    raw = response.content[0].text if response.content else ""
    decision, overall, scores, suggestions = _parse_critique(raw, draft)
    return CriticVerdict(
        decision=decision,
        overall=overall,
        scores=scores,
        suggestions=suggestions if isinstance(suggestions, list) else [],
        raw_excerpt=raw[:300],
        latency_ms=latency_ms,
        input_tokens=getattr(response.usage, "input_tokens", 0),
        cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        output_tokens=getattr(response.usage, "output_tokens", 0),
    )


def _evaluate_one(client, kb: str, label: dict, email_index: dict) -> CaseAnalysis:
    persona = label["persona"]
    case_id = label["case_id"]
    email = email_index.get((persona, case_id), {})
    body = (email.get("body") or email.get("content") or "")
    out = CaseAnalysis(
        case_id=case_id,
        persona=persona,
        run=label["run"],
        human_verdict=label["verdict"],
        human_note=label.get("note", ""),
        subject=label.get("subject", ""),
        draft=label["draft"],
        email_body=body,
        critic=CriticVerdict(decision="parse_failed", overall=0, scores={}),
    )
    try:
        out.critic = _run_critic(client, kb, body, label["draft"])
    except Exception as e:
        out.error = f"{type(e).__name__}: {e}"
    return out


def _render_report(analyses: list[CaseAnalysis]) -> str:
    """Build a human-readable diagnosis."""
    actionable = [a for a in analyses if not a.error]
    n = len(actionable)
    fp = [a for a in actionable if a.disagreement == "FP"]
    fn = [a for a in actionable if a.disagreement == "FN"]
    tp = [a for a in actionable if a.disagreement == "TP"]
    tn = [a for a in actionable if a.disagreement == "TN"]

    accuracy = (len(tp) + len(tn)) / n if n else 0.0
    fp_rate = len(fp) / max(1, len(tp) + len(fp))   # of all "actually good"
    fn_rate = len(fn) / max(1, len(tn) + len(fn))   # of all "actually bad"

    lines = [
        "# Critic vs ground-truth verdict — 2026-05-04",
        "",
        f"**Corpus** : {n} hand-labelled drafts from "
        f"`tasks/ground-truth-drafts-2026-05-04.json`",
        f"**Critic** : prod (`{_MODEL}`) via the deployed structured rubric "
        f"(`app/prompts/templates/critic_structured_system_prompt.txt`)",
        "",
        "## Confusion matrix",
        "",
        "| | Critic VALID | Critic REJECT |",
        "|---|---|---|",
        f"| **Human good** | {len(tp)} TP | **{len(fp)} FP** ⚠️ |",
        f"| **Human bad**  | **{len(fn)} FN** ⚠️ | {len(tn)} TN |",
        "",
        f"- **Accuracy** : {accuracy:.1%} ({len(tp) + len(tn)}/{n})",
        f"- **FP rate** (good drafts wrongly rejected) : "
        f"{fp_rate:.1%} ({len(fp)}/{len(tp) + len(fp)})  "
        f"← the prod symptom : V2 cycles for nothing",
        f"- **FN rate** (bad drafts wrongly accepted) : "
        f"{fn_rate:.1%} ({len(fn)}/{len(tn) + len(fn)})  "
        f"← the safety risk : ships unedited bad drafts",
        "",
    ]

    # Per-dimension analysis on FP cases — which scores forced REJECT?
    if fp:
        lines += [
            "## FP analysis — dimensions that wrongly forced REJECT",
            "",
            "When a `good` draft is rejected, the deployed `CritiqueScores` "
            "rule auto-rejects on ANY dimension < 50. So the FP cases are "
            "drafts where *exactly one* dimension dragged the otherwise-good "
            "verdict to REJECT. The histogram below shows which dimensions "
            "are the chronic FP triggers.",
            "",
        ]
        sub50_counts: Counter[str] = Counter()
        for a in fp:
            for k in _SCORE_KEYS:
                if a.critic.scores.get(k, 100) < 50:
                    sub50_counts[k] += 1
        lines.append("| Dimension | Times scored <50 across FP cases |")
        lines.append("|---|---|")
        for k in _SCORE_KEYS:
            n_sub = sub50_counts.get(k, 0)
            mark = " ← chronic" if n_sub >= max(1, len(fp) // 3) else ""
            lines.append(f"| **{k}** | {n_sub}/{len(fp)}{mark} |")
        lines.append("")

        # Show 5 worst offenders for hand-inspection.
        lines.append("### 5 sample FP cases (human=good, Critic=reject)")
        lines.append("")
        for a in fp[:5]:
            sub50 = [f"{k}={v}" for k, v in a.critic.scores.items() if v < 50]
            lines.append(
                f"- **{a.persona}/{a.case_id}** — Critic overall={a.critic.overall}, "
                f"sub50: {', '.join(sub50) or 'none'}, "
                f"suggestions: {a.critic.suggestions[:2]}"
            )
            lines.append(f"  - Draft excerpt: `{a.draft[:160].replace(chr(10), ' / ')}`")
            if a.human_note:
                lines.append(f"  - Human note: `{a.human_note}`")
        lines.append("")

    # FN cases — what did Critic miss?
    if fn:
        lines += [
            "## FN analysis — bad drafts the Critic falsely validated",
            "",
        ]
        for a in fn:
            top_dims = sorted(a.critic.scores.items(), key=lambda x: x[1])[:3]
            lines.append(
                f"- **{a.persona}/{a.case_id}** — Critic overall={a.critic.overall}, "
                f"weakest dims: {top_dims}"
            )
            lines.append(f"  - Draft excerpt: `{a.draft[:160].replace(chr(10), ' / ')}`")
            if a.human_note:
                lines.append(f"  - Human note (what's wrong): `{a.human_note}`")
        lines.append("")

    # User notes — pattern mining
    notes_with_text = [a for a in actionable if a.human_note.strip()]
    if notes_with_text:
        lines += [
            "## Human notes — recurring patterns",
            "",
        ]
        # Crude keyword bucket counter — looks for known complaint roots.
        buckets = {
            "[À confirmer] / placeholder": ("confirmer", "placeholder", "tbd", "[à"),
            "tone (formal/casual mismatch)": ("formel", "casual", "vouvoi", "tutoi", "tone"),
            "missing greeting/closing": ("greeting", "closing", "salutation", "cordial"),
            "too long / fluff": ("long", "fluff", "verbose", "filler"),
            "hallucination / invented": ("hallucination", "invent", "fabric"),
        }
        for label, kws in buckets.items():
            matches = [a for a in notes_with_text
                       if any(kw in a.human_note.lower() for kw in kws)]
            if matches:
                lines.append(f"- **{label}** : {len(matches)}/{len(notes_with_text)} notes")
                for a in matches[:2]:
                    lines.append(f"  - `{a.human_note[:120]}` ({a.persona}/{a.case_id})")
        lines.append("")

    # Cache stats
    cr_total = sum(a.critic.cache_read_input_tokens for a in actionable)
    cw_total = sum(a.critic.cache_creation_input_tokens for a in actionable)
    in_total = sum(a.critic.input_tokens for a in actionable)
    denom = cr_total + cw_total + in_total
    hit_rate = (cr_total / denom) if denom else 0.0
    p50 = int(statistics.median([a.critic.latency_ms for a in actionable])) if actionable else 0
    lines += [
        "## Side-channel observations",
        "",
        f"- Cache hit rate over the 60-call run : **{hit_rate:.1%}** "
        f"({cr_total}/{denom} input tokens). The 2026-05-04 prompt "
        f"restructure puts the static prefix first, so cross-account hits "
        f"are now possible — but Haiku's 2048-token cache floor is taller "
        f"than Sonnet's 1024 — re-run at scale to confirm.",
        f"- Latency p50 : **{p50} ms** per Critic call.",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    if not _LABELS_FILE.exists():
        print(f"missing {_LABELS_FILE}", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (and not picked up from .env)", file=sys.stderr)
        return 1

    payload = json.loads(_LABELS_FILE.read_text(encoding="utf-8"))
    labels = [
        lbl for lbl in payload.get("labels", [])
        if lbl.get("verdict") in ("good", "bad")
    ]
    print(f"[start] {len(labels)} actionable labels", file=sys.stderr)

    kb_path = _REPO / "knowledge" / "memoire.md"
    kb = kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""
    email_index = _load_email_index()
    client = anthropic.Anthropic()

    analyses: list[CaseAnalysis] = []
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {
            ex.submit(_evaluate_one, client, kb, lbl, email_index): lbl
            for lbl in labels
        }
        for fut in as_completed(futures):
            a = fut.result()
            analyses.append(a)
            done = len(analyses)
            if done % 10 == 0 or done == len(labels):
                err_n = sum(1 for x in analyses if x.error)
                print(f"  {done}/{len(labels)} ({err_n} errors) "
                      f"elapsed={time.time() - t_start:.0f}s",
                      file=sys.stderr)

    # Persist raw + report
    _OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUT_JSON.write_text(json.dumps([
        {**asdict(a), "disagreement": a.disagreement} for a in analyses
    ], indent=2, ensure_ascii=False), encoding="utf-8")
    _OUT_MD.write_text(_render_report(analyses), encoding="utf-8")

    print(file=sys.stderr)
    print(f"[ok] wrote {_OUT_JSON}", file=sys.stderr)
    print(f"[ok] wrote {_OUT_MD}", file=sys.stderr)

    # Console summary so user sees verdict immediately
    print()
    print(_OUT_MD.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
