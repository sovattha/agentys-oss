#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Étude d'ablation : la knowledge base injectée dans le critic structuré
sert-elle vraiment ?

Issue #251 phase 4c. Le `<CONTEXTE_ENTREPRISE>{knowledge_base}</CONTEXTE_ENTREPRISE>`
(souvent >1000 tokens) est injecté dans CHAQUE appel critic structuré, mais les
7 critères du prompt ne référencent jamais explicitement ce contexte — seul
le critère ERREURS dit "hallucinations, détails inventés" sans pointer vers la KB.

Hypothèse : retirer la KB ne change pas significativement les décisions du
critic. Si c'est vrai → ~$3/mois économisés (1000 tokens × 3000 calls × $1/M).

Méthode :
    Pour chaque (email, draft) du jeu de test :
      1. Appeler le critic structuré AVEC la vraie KB
      2. Appeler le critic structuré SANS KB (string vide)
      3. Comparer décision (VALID/REJECT) + scores par critère

Verdict :
    PARITY        — décision identique ≥ 90% + delta moyen < 5 → KB est dead weight
    WEAK_DIVERG   — décision identique ≥ 80% + delta moyen < 10 → KB a un effet mineur
    DIVERGENT     — sinon → KB est load-bearing, NE PAS la retirer

Usage :
    python scripts/eval_critic_kb_ablation.py                 # dry-run, 5 fixtures synthétiques (gratuit)
    python scripts/eval_critic_kb_ablation.py --smoke --live  # 5 fixtures, vrais appels LLM (~$0.015)
    python scripts/eval_critic_kb_ablation.py --n 50 --live   # 50 fixtures depuis test set (~$0.15)

Coût estimé live : ~$0.0015 par paire (2 appels Haiku critic structuré × ~$0.0007/call).

Sortie :
    tasks/critic-kb-ablation/run_<timestamp>.json   — résultats détaillés
    stdout                                          — verdict + résumé markdown
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Fixtures synthétiques — couvrent les 7 critères et 2 langues
# ---------------------------------------------------------------------------

SMOKE_FIXTURES: list[dict[str, str]] = [
    {
        # Cas net : email simple, draft net, devrait passer VALID avec ou sans KB
        "id": "smoke-1-clean-fr",
        "email": "Bonjour,\n\nPourriez-vous me confirmer le rendez-vous de mardi 14h ?\n\nMerci, Marc",
        "draft": "Bonjour Marc,\n\nLe rendez-vous de mardi 14h est confirmé.\n",
    },
    {
        # Cas casual : tutoiement court, devrait passer
        "id": "smoke-2-casual-fr",
        "email": "Salut, t'es dispo demain pour un café à 10h ?",
        "draft": "Salut,\n\nOui, ça marche pour 10h. À demain.\n",
    },
    {
        # Cas hallucination : draft invente une heure absente de l'email
        # → ERREURS criterion devrait baisser. Test : la KB aide-t-elle à le détecter ?
        "id": "smoke-3-halluc-time-fr",
        "email": "Bonjour, est-ce que vous êtes disponible la semaine prochaine pour un appel ?",
        "draft": "Bonjour,\n\nOui, je suis disponible mardi à 15h30 pour notre appel.\n\nCordialement.\n",
    },
    {
        # Cas anglais : structure multi-paragraphes
        "id": "smoke-4-multi-en",
        "email": "Hi, can you share the Q3 roadmap and the launch date for the new feature?",
        "draft": "Hi,\n\nQ3 roadmap is shared in the attached doc.\n\nLaunch date for the new feature: October 15.\n\nBest.\n",
    },
    {
        # Cas formel pro : email client demande info, draft répond bien
        "id": "smoke-5-formal-fr",
        "email": "Madame, Monsieur,\n\nJe souhaite obtenir un devis pour 50 unités du modèle Pro.\n\nCordialement, J. Tremblay",
        "draft": "Madame, Monsieur Tremblay,\n\nJe vous remercie de votre demande. Je vous transmets le devis sous 24h.\n\nCordialement.\n",
    },
]


# ---------------------------------------------------------------------------
# Fixture loader depuis tests/fixtures/drafting_eval_runs
# ---------------------------------------------------------------------------

def _load_fixtures_from_eval_runs(n: int) -> list[dict[str, str]]:
    """Charge des paires (email, draft) depuis le dernier eval run."""
    eval_root = _REPO / "tests" / "fixtures" / "drafting_eval_runs"
    if not eval_root.exists():
        return []

    runs = sorted([p for p in eval_root.iterdir() if p.is_dir()], reverse=True)
    if not runs:
        return []
    latest = runs[0]

    fixtures: list[dict[str, str]] = []
    for json_path in sorted(latest.glob("*.json")):
        if json_path.name in {"summary.json", "config.json"}:
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for case in data.get("cases", []):
            email = case.get("email") or case.get("user_message") or case.get("subject", "")
            draft = case.get("draft", "")
            if not email or not draft:
                continue
            fixtures.append({
                "id": f"{json_path.stem}-{case.get('case_id', len(fixtures))}",
                "email": email,
                "draft": draft,
            })
            if len(fixtures) >= n:
                return fixtures
    return fixtures


# ---------------------------------------------------------------------------
# Single-pair ablation
# ---------------------------------------------------------------------------

def _evaluate_one(
    email: str,
    draft: str,
    kb: str,
    critic_factory,
) -> dict:
    """Construit un CriticAgent avec la KB donnée, lance evaluate_draft, retourne le résultat.

    Raises:
        RuntimeError: Si l'appel LLM échoue (CritiqueAgent retourne create_failed avec
            scores par défaut → on lève pour que le caller exclue cette rep du dataset
            au lieu de la traiter comme une vraie observation.
    """
    from app.domain.entities.critique import CritiqueRequest

    agent = critic_factory(kb)
    request = CritiqueRequest(
        draft_content=draft,
        original_email=email,
        email_id="kb-ablation-eval",
    )
    t0 = time.time()
    result = agent.evaluate_draft(request)
    elapsed = time.time() - t0

    # Detect failed evaluations : CriticAgent.evaluate_draft retourne create_failed()
    # avec default scores (50 pour tous) en cas d'exception. On veut PROPAGER l'échec
    # plutôt que d'agréger des données fictives.
    decision_value = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
    if decision_value.upper() in {"FAILED", "ERROR"} or result.tokens_used == 0:
        raise RuntimeError(f"critic call failed (decision={decision_value}, tokens={result.tokens_used})")

    return {
        "decision": decision_value,
        "scores": asdict(result.scores),
        "overall": result.scores.calculate_overall(),
        "tokens_used": result.tokens_used,
        "elapsed_s": round(elapsed, 3),
    }


def _make_critic_factory(account_id: Optional[int]):
    """Retourne une factory CriticAgent qui ne ré-évalue pas la KB.

    `CriticAgent.__post_init__` remplace une `knowledge_base=""` par une
    KB chargée depuis la DB / file. Pour tester "without KB" on doit
    passer un sentinel non-vide puis le réécrire.

    SAFETY (2026-05-03) : `account_id=None` est obligatoire. `get_critic_structured_system_prompt`
    (builders.py:579-612) injecte des règles apprises via `get_draft_learning_store(account_id=...)`
    INDÉPENDAMMENT du paramètre KB. Passer un account_id casserait l'invariant d'ablation
    (les rules apprises seraient présentes dans les 2 conditions, biaisant le résultat
    si un account a beaucoup de rules — typiquement +500 tokens/call non contrôlés).
    """
    from app.agents import CriticAgent

    assert account_id is None, (
        "Ablation invariant violation: account_id must be None to prevent "
        "learning-rules leakage through get_draft_learning_store. "
        "If you need per-account ablation, also gate the learning store."
    )

    def _factory(kb: str):
        # kb="" déclenche le fallback DB → on construit avec un placeholder
        # puis on overwrite. C'est le seul moyen propre de bypass.
        agent = CriticAgent(knowledge_base=kb if kb else "(__ABLATION_EMPTY__)", account_id=account_id)
        if not kb:
            agent.knowledge_base = ""  # vraie absence de KB
        return agent

    return _factory


# ---------------------------------------------------------------------------
# Run + summarize
# ---------------------------------------------------------------------------

def _aggregate_reps(reps: list[dict]) -> dict:
    """Agrège N réplicats d'une même condition : moyenne, std-dev, modal decision."""
    if not reps:
        return {}
    overalls = [r["overall"] for r in reps]
    elapsed = [r["elapsed_s"] for r in reps]
    decisions = [r["decision"] for r in reps]
    # Modal decision (le plus fréquent)
    modal_decision = max(set(decisions), key=decisions.count)
    decision_consistency = decisions.count(modal_decision) / len(decisions)
    # Per-criterion mean + std
    criterion_keys = list(reps[0]["scores"].keys())
    scores_mean = {k: statistics.mean(r["scores"][k] for r in reps) for k in criterion_keys}
    scores_std = {
        k: statistics.stdev(r["scores"][k] for r in reps) if len(reps) > 1 else 0.0
        for k in criterion_keys
    }
    return {
        "n_reps": len(reps),
        "modal_decision": modal_decision,
        "decision_consistency": round(decision_consistency, 3),
        "overall_mean": round(statistics.mean(overalls), 2),
        "overall_std": round(statistics.stdev(overalls), 2) if len(reps) > 1 else 0.0,
        "elapsed_mean_s": round(statistics.mean(elapsed), 3),
        "elapsed_p95_s": round(sorted(elapsed)[int(0.95 * (len(elapsed) - 1))], 3) if len(elapsed) > 1 else round(elapsed[0], 3),
        "scores_mean": {k: round(v, 1) for k, v in scores_mean.items()},
        "scores_std": {k: round(v, 2) for k, v in scores_std.items()},
        "raw_reps": reps,
    }


def run_ablation(
    fixtures: list[dict[str, str]],
    real_kb: str,
    live: bool,
    reps: int = 1,
    sleep_between: float = 0.4,
) -> list[dict]:
    """Pour chaque fixture, appelle le critic `reps` fois × 2 conditions (avec/sans KB).

    Si reps > 1, calcule moyenne + std-dev par condition pour estimer la variance
    intra-condition. La variance intra-condition permet de juger si les deltas
    inter-conditions sont du bruit ou un vrai effet.
    """
    if not live:
        return [{
            "id": f["id"],
            "email_preview": f["email"][:80],
            "draft_preview": f["draft"][:80],
            "with_kb": "(dry-run)",
            "without_kb": "(dry-run)",
            "decision_match": None,
            "score_delta_overall": None,
            "score_delta_per_criterion": None,
        } for f in fixtures]

    factory = _make_critic_factory(account_id=None)
    results: list[dict] = []
    for i, fix in enumerate(fixtures):
        print(f"  [{i+1}/{len(fixtures)}] {fix['id']}", end=" ", flush=True)
        try:
            with_kb_reps: list[dict] = []
            without_kb_reps: list[dict] = []
            for r in range(reps):
                with_kb_reps.append(_evaluate_one(fix["email"], fix["draft"], real_kb, factory))
                time.sleep(sleep_between)
                without_kb_reps.append(_evaluate_one(fix["email"], fix["draft"], "", factory))
                time.sleep(sleep_between)
                if reps > 1:
                    print(".", end="", flush=True)

            with_kb = _aggregate_reps(with_kb_reps)
            without_kb = _aggregate_reps(without_kb_reps)

            score_delta = {
                k: abs(with_kb["scores_mean"][k] - without_kb["scores_mean"][k])
                for k in with_kb["scores_mean"]
            }
            # Pooled standard deviation across both conditions (per criterion)
            pooled_std = {
                k: round(((with_kb["scores_std"][k] ** 2 + without_kb["scores_std"][k] ** 2) / 2) ** 0.5, 2)
                for k in with_kb["scores_std"]
            }
            results.append({
                "id": fix["id"],
                "email_preview": fix["email"][:80],
                "draft_preview": fix["draft"][:80],
                "with_kb": with_kb,
                "without_kb": without_kb,
                "decision_match": with_kb["modal_decision"] == without_kb["modal_decision"],
                "score_delta_overall": round(abs(with_kb["overall_mean"] - without_kb["overall_mean"]), 2),
                "score_delta_per_criterion": score_delta,
                "pooled_std_per_criterion": pooled_std,
                "elapsed_delta_s": round(with_kb["elapsed_mean_s"] - without_kb["elapsed_mean_s"], 3),
            })
            print(f" Doverall={results[-1]['score_delta_overall']:.1f} (sigma_pool={pooled_std.get('coherence', 0):.1f})")
        except Exception as e:
            print(f"FAIL ({e})")
            results.append({"id": fix["id"], "error": str(e)})
    return results


def summarize(results: list[dict], reps: int = 1) -> dict:
    """Aggrégation : verdict ablation KB + verdict méta sur la nécessité de hardening.

    Le verdict ablation utilise les deltas MOYENS entre conditions.
    Le verdict hardening regarde la variance INTRA-condition (pooled std-dev) :
    si la variance intra-condition est >= aux deltas inter-conditions, le signal est noyé
    dans le bruit et il faut plus de reps / fixtures pour décider de manière fiable.
    """
    valid = [r for r in results if r.get("decision_match") is not None]
    if not valid:
        return {"verdict": "NO_LIVE_DATA", "n": 0}

    n = len(valid)
    decision_match_rate = sum(1 for r in valid if r["decision_match"]) / n
    avg_overall_delta = statistics.mean(r["score_delta_overall"] for r in valid)

    # Per-criterion deltas
    criterion_deltas: dict[str, list[float]] = {}
    pooled_stds: dict[str, list[float]] = {}
    elapsed_deltas: list[float] = []
    for r in valid:
        for k, v in r["score_delta_per_criterion"].items():
            criterion_deltas.setdefault(k, []).append(v)
        if "pooled_std_per_criterion" in r:
            for k, v in r["pooled_std_per_criterion"].items():
                pooled_stds.setdefault(k, []).append(v)
        if "elapsed_delta_s" in r:
            elapsed_deltas.append(r["elapsed_delta_s"])

    avg_delta_per_criterion = {k: statistics.mean(v) for k, v in criterion_deltas.items()}
    avg_pooled_std = {k: statistics.mean(v) for k, v in pooled_stds.items()} if pooled_stds else {}

    # Ablation verdict (KB removal decision)
    if decision_match_rate >= 0.90 and avg_overall_delta < 5:
        ablation_verdict = "PARITY - KB injection n'impacte pas les decisions critic. SAFE to remove."
    elif decision_match_rate >= 0.80 and avg_overall_delta < 10:
        ablation_verdict = "WEAK_DIVERGENCE - KB a un effet mineur. Garder par securite ou benchmark plus large."
    else:
        ablation_verdict = "DIVERGENT - KB est load-bearing pour les decisions critic. KEEP."

    # Hardening verdict (meta : faut-il plus de rigueur ?)
    hardening_verdict = "N/A - single-rep mode (use --reps 3+ for variance estimation)"
    signal_to_noise_ratio = None
    if reps >= 2 and avg_pooled_std:
        # Critere : si la variance intra-condition (bruit) >= delta inter-condition (signal),
        # le resultat actuel est dans le bruit -> hardening necessaire pour decider.
        max_pooled_std = max(avg_pooled_std.values())
        signal_to_noise_ratio = round(avg_overall_delta / max_pooled_std, 2) if max_pooled_std > 0 else float("inf")
        if max_pooled_std >= 5.0:
            hardening_verdict = (
                f"HARDENING ESSENTIAL - variance intra-condition elevee (max sigma={max_pooled_std:.1f} >= 5). "
                f"Single-rep verdicts seraient dans le bruit. Methodologie actuelle insuffisante : "
                f"il faut +stress fixtures + reps >= 5 pour conclure."
            )
        elif max_pooled_std >= 3.0:
            hardening_verdict = (
                f"HARDENING OPTIONAL - variance moderee (max sigma={max_pooled_std:.1f}, 3-5). "
                f"Reps >= 3 suffisent ; stress fixtures recommandees si verdict ablation est PARITY."
            )
        else:
            hardening_verdict = (
                f"HARDENING NOT NEEDED - variance faible (max sigma={max_pooled_std:.1f} < 3). "
                f"Single-rep est fiable, le harness actuel suffit pour decider."
            )

    out = {
        "n": n,
        "reps_per_condition": reps,
        "decision_match_rate": round(decision_match_rate, 3),
        "avg_overall_delta": round(avg_overall_delta, 2),
        "avg_delta_per_criterion": {k: round(v, 2) for k, v in avg_delta_per_criterion.items()},
        "ablation_verdict": ablation_verdict,
        "hardening_verdict": hardening_verdict,
    }
    if avg_pooled_std:
        out["avg_pooled_std_per_criterion"] = {k: round(v, 2) for k, v in avg_pooled_std.items()}
        out["signal_to_noise_ratio"] = signal_to_noise_ratio
    if elapsed_deltas:
        out["avg_elapsed_delta_s"] = round(statistics.mean(elapsed_deltas), 3)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="Utilise les 5 fixtures synthétiques (par défaut si --n absent)")
    parser.add_argument("--n", type=int, default=0, help="Charge N fixtures depuis tests/fixtures/drafting_eval_runs")
    parser.add_argument("--live", action="store_true", help="Lance les vrais appels LLM (coûte ~$0.0015 par paire). Défaut : dry-run.")
    parser.add_argument("--reps", type=int, default=1, help="Réplicats par condition (défaut 1). Utiliser ≥3 pour estimer la variance intra-condition et obtenir un verdict de hardening.")
    parser.add_argument("--out", default=None, help="Chemin JSON résultats (défaut auto-généré)")
    args = parser.parse_args()

    # Pick fixtures
    if args.n > 0:
        fixtures = _load_fixtures_from_eval_runs(args.n)
        if len(fixtures) < args.n:
            print(f"[warn] only loaded {len(fixtures)}/{args.n} fixtures from eval runs")
        if not fixtures:
            print("[warn] no fixtures found from eval runs, falling back to smoke set")
            fixtures = SMOKE_FIXTURES
    else:
        fixtures = SMOKE_FIXTURES

    # Load real KB
    real_kb = ""
    if args.live:
        try:
            from app.prompts import load_knowledge_base
            real_kb = load_knowledge_base()
        except Exception as e:
            print(f"[error] failed to load knowledge base: {e}")
            return 1

    print(f"Mode: {'LIVE (real LLM calls)' if args.live else 'DRY-RUN (no LLM calls)'}")
    print(f"Fixtures: {len(fixtures)}  x  Conditions: 2 (with_kb / without_kb)  x  Reps: {args.reps}")
    if args.live:
        print(f"Real KB length: {len(real_kb)} chars (~{len(real_kb)//3.5:.0f} tokens)")
        n_calls = len(fixtures) * 2 * args.reps
        est_cost_usd = n_calls * 0.0015
        print(f"Total LLM calls: {n_calls} -> estimated cost: ~${est_cost_usd:.3f}")
    print()

    results = run_ablation(fixtures, real_kb, live=args.live, reps=args.reps)
    summary = summarize(results, reps=args.reps)

    # Write JSON
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else _REPO / "tasks" / "critic-kb-ablation" / f"run_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp": timestamp,
        "live": args.live,
        "reps": args.reps,
        "kb_length_chars": len(real_kb),
        "summary": summary,
        "results": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown summary to stdout
    print("=" * 70)
    print(f"ABLATION VERDICT  : {summary.get('ablation_verdict', summary.get('verdict', 'N/A'))}")
    print(f"HARDENING VERDICT : {summary.get('hardening_verdict', 'N/A')}")
    print("=" * 70)
    if summary.get("n", 0) > 0:
        print(f"  n fixtures            : {summary['n']}")
        print(f"  reps per condition    : {summary.get('reps_per_condition', 1)}")
        print(f"  Decision match rate   : {summary['decision_match_rate']:.1%}")
        print(f"  Avg overall delta     : {summary['avg_overall_delta']}")
        if "signal_to_noise_ratio" in summary and summary["signal_to_noise_ratio"] is not None:
            print(f"  Signal/noise (Δ/σ)    : {summary['signal_to_noise_ratio']}")
        if "avg_elapsed_delta_s" in summary:
            print(f"  Avg elapsed delta (s) : {summary['avg_elapsed_delta_s']:+.3f}  (with_kb − without_kb)")
        print(f"  Per-criterion delta (signal) | pooled std (noise):")
        for k, v in sorted(summary["avg_delta_per_criterion"].items(), key=lambda kv: -kv[1]):
            sigma = summary.get("avg_pooled_std_per_criterion", {}).get(k, "-")
            sigma_str = f"{sigma:5.2f}" if isinstance(sigma, (int, float)) else "  -  "
            print(f"    {k:28s} D={v:5.2f} | sigma={sigma_str}")
    print(f"\nDetailed report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
