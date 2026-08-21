#!/usr/bin/env python
"""Évaluation comparative SelfCritiqueAgent vs CriticAgent sur 200 cas synthétiques.

Phase 1 du pipeline draft unifié : valide que le seuil self_score=75 attrape
correctement les drafts à risque, et compare coût/latence vs CriticAgent existant.

Modes :
    --mock  : utilise un mock LLM déterministe (logique seulement, $0)
    --live  : appels Haiku réels via Container.llm_label (~$0.02 self-only,
              ~$0.14 si --include-critic, à 200 cas)

Output : rapport markdown structuré (agreement rate, precision/recall par
catégorie, distribution scores, coût/latence comparaison).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Path setup so the script runs from any cwd
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from eval_dataset import ALL_CASES, EvalCase  # noqa: E402


# ---------------------------------------------------------------------------
# Mock LLM — produces deterministic verdicts driven by case category
# ---------------------------------------------------------------------------

class MockLLM:
    """Returns a self-critique JSON shaped like what an ideal Haiku would produce.

    The mock is wired to the case's `expected_risks` — useful to validate the
    aggregator/reporting logic without LLM cost. It does NOT validate that
    real Haiku is good at applying the rubric (that's --live).
    """

    name = "mock"
    model = "mock-haiku"

    def __init__(self) -> None:
        self.last_case_hint: EvalCase | None = None
        self.call_count = 0

    def hint(self, case: EvalCase) -> None:
        self.last_case_hint = case

    def complete(self, system, user, max_tokens=200, temperature=0.0):
        from app.domain.ports.llm_port import LLMResponse
        self.call_count += 1
        c = self.last_case_hint
        if c is None or c.category == "good":
            payload = {"self_score": 88, "risks": [], "a_confirmer_count": 0, "confidence": "high"}
        else:
            risks = list(c.expected_risks)
            payload = {
                "self_score": 50 if len(risks) > 0 else 88,
                "risks": risks,
                "a_confirmer_count": c.expected_a_confirmer_count,
                "confidence": "med",
            }
        return LLMResponse(
            content=json.dumps(payload),
            input_tokens=200, output_tokens=50, model=self.model,
        )

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    category: str
    mode: str
    expected_risks: list[str]
    expected_a_confirmer_count: int
    self_score: int
    self_risks: list[str]
    self_a_confirmer: int
    self_confidence: str
    self_failure_reason: str
    self_latency_ms: int
    would_escalate: bool
    # Filled when --include-critic
    critic_decision: str = ""
    critic_score: int = 0
    critic_latency_ms: int = 0


@dataclass
class Aggregates:
    total: int = 0
    by_category: dict = field(default_factory=dict)
    self_avg_score: float = 0.0
    self_p50_latency: int = 0
    self_p95_latency: int = 0
    self_failures: int = 0
    self_escalation_rate: float = 0.0
    cost_self_usd: float = 0.0
    cost_critic_usd: float = 0.0
    critic_p50_latency: int = 0
    critic_p95_latency: int = 0


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def _gate_would_escalate(self_score: int, risks: list[str], a_count: int, confidence: str,
                         threshold: int = 75) -> bool:
    """Replicates the Phase 3 escalation gate logic for offline eval."""
    if self_score < threshold:
        return True
    if a_count > 0:
        return True
    risky_set = {"hallucination", "placeholder", "tone_mismatch"}
    if any(r in risky_set for r in risks):
        return True
    if confidence == "low":
        return True
    return False


def run_eval(cases: list[EvalCase], live: bool, include_critic: bool, threshold: int) -> tuple[list[CaseResult], Aggregates]:
    if live:
        from app.infrastructure.container import get_container
        from app.self_critique_agent import SelfCritiqueAgent
        agent = SelfCritiqueAgent()  # Container.llm_label
        critic_agent = None
        if include_critic:
            from app.agents import CriticAgent  # type: ignore
            critic_agent = CriticAgent()
        get_container()  # warm
    else:
        from app.self_critique_agent import SelfCritiqueAgent
        mock = MockLLM()
        agent = SelfCritiqueAgent.__new__(SelfCritiqueAgent)
        agent._llm = mock  # type: ignore[attr-defined]
        critic_agent = None  # mock doesn't support critic (no need — logic only)

    results: list[CaseResult] = []
    self_costs = []
    critic_costs = []
    self_latencies = []
    critic_latencies = []

    for i, case in enumerate(cases):
        if not live and isinstance(getattr(agent, "_llm", None), MockLLM):
            agent._llm.hint(case)  # type: ignore[union-attr]

        t0 = time.time()
        try:
            critique = agent.evaluate(
                draft=case.draft_v1, context=case.email_in, mode=case.mode  # type: ignore[arg-type]
            )
        except Exception as e:
            print(f"[WARN] case {case.case_id}: agent crashed: {e}", file=sys.stderr)
            continue
        latency_ms = int((time.time() - t0) * 1000)

        # Cost estimate (Haiku 4.5: input $1/M, output $5/M)
        cost_self = (200 * 1e-6) + (50 * 5e-6)  # ~$0.00045
        self_costs.append(cost_self)
        self_latencies.append(latency_ms)

        would = _gate_would_escalate(
            critique.self_score, list(critique.risks),
            critique.a_confirmer_count, critique.confidence, threshold
        )

        cr = CaseResult(
            case_id=case.case_id,
            category=case.category, mode=case.mode,
            expected_risks=list(case.expected_risks),
            expected_a_confirmer_count=case.expected_a_confirmer_count,
            self_score=critique.self_score,
            self_risks=list(critique.risks),
            self_a_confirmer=critique.a_confirmer_count,
            self_confidence=critique.confidence,
            self_failure_reason=critique.failure_reason,
            self_latency_ms=latency_ms,
            would_escalate=would,
        )

        if include_critic and critic_agent is not None:
            from app.domain.entities.critique import CritiqueRequest
            t1 = time.time()
            try:
                req = CritiqueRequest(
                    draft_content=case.draft_v1,
                    original_email=case.email_in,
                    email_id=case.case_id,
                )
                critic_result = critic_agent.evaluate_draft(req)
                cr.critic_decision = critic_result.decision.value
                cr.critic_score = critic_result.scores.calculate_overall()
            except Exception as e:
                print(f"[WARN] case {case.case_id}: critic crashed: {e}", file=sys.stderr)
            cr.critic_latency_ms = int((time.time() - t1) * 1000)
            critic_latencies.append(cr.critic_latency_ms)
            # Critic costs ~$0.0006 per call (Sonnet/Haiku ~700/200 tokens)
            critic_costs.append(0.0006)

        results.append(cr)

        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(cases)} cases done", file=sys.stderr)

    # Aggregate
    by_cat: dict[str, dict] = {}
    for r in results:
        b = by_cat.setdefault(r.category, {
            "count": 0, "would_escalate": 0, "scores": [],
            "expected_caught": 0, "expected_total": 0,
        })
        b["count"] += 1
        if r.would_escalate:
            b["would_escalate"] += 1
        b["scores"].append(r.self_score)
        if r.expected_risks:
            b["expected_total"] += 1
            if any(er in r.self_risks for er in r.expected_risks):
                b["expected_caught"] += 1

    for cat, b in by_cat.items():
        b["avg_score"] = round(statistics.mean(b["scores"]), 1) if b["scores"] else 0
        b["escalation_rate"] = round(b["would_escalate"] / b["count"], 3) if b["count"] else 0
        b["risk_recall"] = round(b["expected_caught"] / b["expected_total"], 3) if b["expected_total"] else None
        del b["scores"]

    agg = Aggregates(
        total=len(results),
        by_category=by_cat,
        self_avg_score=round(statistics.mean([r.self_score for r in results]), 1) if results else 0,
        self_p50_latency=int(statistics.median(self_latencies)) if self_latencies else 0,
        self_p95_latency=int(_percentile(self_latencies, 95)) if self_latencies else 0,
        self_failures=sum(1 for r in results if r.self_failure_reason),
        self_escalation_rate=round(sum(1 for r in results if r.would_escalate) / len(results), 3) if results else 0,
        cost_self_usd=round(sum(self_costs), 4),
        cost_critic_usd=round(sum(critic_costs), 4),
        critic_p50_latency=int(statistics.median(critic_latencies)) if critic_latencies else 0,
        critic_p95_latency=int(_percentile(critic_latencies, 95)) if critic_latencies else 0,
    )
    return results, agg


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def render_report(results: list[CaseResult], agg: Aggregates, mode_label: str, threshold: int) -> str:
    from datetime import datetime, timezone
    lines = []
    lines.append(f"# Évaluation SelfCritiqueAgent — {mode_label}")
    lines.append("")
    lines.append(f"**Généré** : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Cas évalués** : {agg.total} / 200")
    lines.append(f"**Seuil testé** : `self_score < {threshold}` → escalade")
    lines.append("")
    lines.append("## Résumé exécutif")
    lines.append("")
    lines.append(f"- **Score moyen** : {agg.self_avg_score}/100")
    lines.append(f"- **Taux d'escalade global** : {agg.self_escalation_rate:.1%}")
    lines.append(f"- **Échecs LLM** (parse, timeout, etc.) : {agg.self_failures}/{agg.total}")
    lines.append(f"- **Latence p50 SelfCritique** : {agg.self_p50_latency} ms")
    lines.append(f"- **Latence p95 SelfCritique** : {agg.self_p95_latency} ms")
    lines.append(f"- **Coût total SelfCritique** : ${agg.cost_self_usd:.4f}")
    if agg.cost_critic_usd:
        lines.append(f"- **Latence p50 Critic** : {agg.critic_p50_latency} ms")
        lines.append(f"- **Latence p95 Critic** : {agg.critic_p95_latency} ms")
        lines.append(f"- **Coût total Critic** : ${agg.cost_critic_usd:.4f}")
    lines.append("")

    lines.append("## Performance par catégorie")
    lines.append("")
    lines.append("| Catégorie | Cas | Score moyen | Escalade | Recall risks |")
    lines.append("|---|---|---|---|---|")
    for cat in ("good", "hallucination", "placeholder", "tone_mismatch", "filler", "off_topic"):
        b = agg.by_category.get(cat)
        if not b:
            continue
        recall = f"{b['risk_recall']:.0%}" if b.get("risk_recall") is not None else "N/A"
        lines.append(
            f"| `{cat}` | {b['count']} | {b['avg_score']} | "
            f"{b['escalation_rate']:.0%} | {recall} |"
        )
    lines.append("")

    lines.append("## Lecture")
    lines.append("")
    lines.append("- **good** : taux d'escalade IDÉAL = bas (false positives = drafts corrects qu'on")
    lines.append("  envoie quand même au Critic externe → coût additionnel inutile)")
    lines.append("- **autres catégories** : taux d'escalade IDÉAL = haut (true positives = drafts à")
    lines.append("  risque attrapés avant envoi)")
    lines.append("- **Recall risks** : pourcentage de drafts d'une catégorie où l'agent a effectivement")
    lines.append("  identifié le risque attendu dans ses `risks[]`")
    lines.append("")

    # Recommandation seuil
    good_b = agg.by_category.get("good", {})
    risky_cats = ["hallucination", "placeholder", "tone_mismatch", "filler", "off_topic"]
    risky_avg = statistics.mean([
        agg.by_category[c]["escalation_rate"]
        for c in risky_cats if c in agg.by_category
    ]) if any(c in agg.by_category for c in risky_cats) else 0

    lines.append("## Recommandation seuil")
    lines.append("")
    lines.append(f"- Faux positifs sur drafts sains : **{good_b.get('escalation_rate', 0):.0%}**")
    lines.append(f"- True positives sur drafts à risque : **{risky_avg:.0%}**")
    lines.append("")

    fp = good_b.get("escalation_rate", 0)
    if fp > 0.30:
        lines.append(f"⚠️ Faux positifs élevés ({fp:.0%}). Le seuil {threshold} est trop strict — ")
        lines.append("baisser à 65-70 ou simplifier la rubrique.")
    elif fp < 0.05 and risky_avg > 0.85:
        lines.append(f"✅ Excellent compromis. Seuil {threshold} validé pour Phase 3.")
    elif risky_avg < 0.70:
        lines.append(f"⚠️ Recall faible ({risky_avg:.0%}). L'agent rate trop de drafts à risque.")
        lines.append("Réviser la rubrique ou augmenter le seuil à 80.")
    else:
        lines.append(f"Seuil {threshold} acceptable. Précision/rappel équilibrés.")
    lines.append("")

    lines.append("## Détails par cas (échantillon)")
    lines.append("")
    lines.append("| ID | Cat | Score | Risks détectés | Escalade |")
    lines.append("|---|---|---|---|---|")
    # 5 par catégorie
    seen_per_cat: dict[str, int] = {}
    for r in results:
        n = seen_per_cat.get(r.category, 0)
        if n >= 5:
            continue
        seen_per_cat[r.category] = n + 1
        risks_str = ", ".join(r.self_risks) if r.self_risks else "—"
        esc = "✓" if r.would_escalate else " "
        lines.append(f"| `{r.case_id}` | {r.category} | {r.self_score} | {risks_str} | {esc} |")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Eval SelfCritiqueAgent on 200 synthetic cases")
    p.add_argument("--live", action="store_true",
                   help="Real Haiku calls (~$0.02-0.14). Default: mock.")
    p.add_argument("--include-critic", action="store_true",
                   help="Also run CriticAgent for direct comparison (--live only).")
    p.add_argument("--threshold", type=int, default=75,
                   help="Self-score escalation threshold (default: 75).")
    p.add_argument("--limit", type=int, default=200,
                   help="Limit number of cases (for smoke testing).")
    p.add_argument("--out", default="tasks/eval-self-critique-{mode}-2026-04-30.md")
    args = p.parse_args(argv)

    if args.include_critic and not args.live:
        print("[FATAL] --include-critic requires --live", file=sys.stderr)
        return 2

    cases = ALL_CASES[:args.limit]
    mode_label = "LIVE" if args.live else "MOCK"
    print(f"[OK] Démarrage évaluation : {len(cases)} cas, mode {mode_label}, "
          f"seuil={args.threshold}, include_critic={args.include_critic}")

    t0 = time.time()
    results, agg = run_eval(cases, args.live, args.include_critic, args.threshold)
    elapsed = int(time.time() - t0)

    out_path = Path(args.out.format(mode=mode_label.lower())).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md = render_report(results, agg, mode_label, args.threshold)
    out_path.write_text(md, encoding="utf-8")

    # Also dump raw JSON for downstream analysis
    json_out = out_path.with_suffix(".json")
    json_out.write_text(
        json.dumps(
            {"aggregates": asdict(agg), "results": [asdict(r) for r in results]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Évaluation terminée en {elapsed}s")
    print(f"     {len(results)} cas évalués, {agg.self_failures} échecs LLM")
    print(f"     Score moyen : {agg.self_avg_score}/100")
    print(f"     Escalade : {agg.self_escalation_rate:.1%}")
    print(f"     Coût SelfCritique : ${agg.cost_self_usd:.4f}")
    if agg.cost_critic_usd:
        print(f"     Coût Critic : ${agg.cost_critic_usd:.4f}")
    print(f"     Rapport : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
