"""Replay user label-corrections through the classifier and report accuracy.

This is the regression-eval companion to ``app/api/labels.py``'s correction
hook (which appends each user correction to ``tasks/label_corrections.jsonl``).

Run before/after any prompt or rules change to see the accuracy delta:

    # Baseline (current code)
    python scripts/eval_label_corrections.py --report tasks/eval-baseline.json

    # ... edit prompts/rules ...

    # New (compare to baseline)
    python scripts/eval_label_corrections.py --baseline tasks/eval-baseline.json

The corpus path defaults to ``tasks/label_corrections.jsonl`` and can be
overridden via ``AGENTYS_LABEL_EVAL_PATH`` or ``--corpus``.

By default this script DOES NOT call the LLM — it runs the rules-only
classifier (``LabelEmailUseCase.classify_by_rules_only``) which is fast,
deterministic, and sufficient to catch rule regressions. Pass ``--with-llm``
to also exercise the LLM path (costs ~$0.001 per correction at Haiku rates).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _default_corpus_path() -> str:
    return os.environ.get("AGENTYS_LABEL_EVAL_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tasks", "label_corrections.jsonl",
    )


def _load_corpus(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _evaluate_one(record: Dict[str, Any], use_llm: bool = False) -> Optional[str]:
    """Run the classifier on one corpus record. Return the predicted label."""
    from app.application.label_email import LabelEmailUseCase
    from app.domain.entities import Email
    from unittest.mock import Mock

    email = Email(
        id=record.get("email_id", "eval"),
        sender=record.get("sender", ""),
        subject=record.get("subject", ""),
        body=record.get("body", ""),
    )

    if use_llm:
        # Real LLM path — caller must have ANTHROPIC_API_KEY set.
        from app.infrastructure.container import Container
        c = Container()
        uc = c.get_label_email_use_case(user_email="")
        a = uc.execute(email)
        return a.default_label if a else None

    # Rules-only path (fast, free, no LLM)
    label_store = Mock()
    label_store.get_rules.return_value = []
    label_store.get_labels.return_value = []
    a = LabelEmailUseCase.classify_by_rules_only(email, label_store, user_email="")
    return a.default_label if (a and a.default_label) else None


def _compute_metrics(records: List[Dict[str, Any]], predictions: List[Optional[str]]) -> Dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"total": 0, "accuracy": 0.0, "per_label": {}, "confusions": []}
    correct = 0
    per_label_correct: Counter = Counter()
    per_label_total: Counter = Counter()
    confusions: Counter = Counter()
    unhandled = 0
    for r, p in zip(records, predictions):
        truth = r.get("new_default") or ""
        if not truth:
            continue
        per_label_total[truth] += 1
        if p is None:
            unhandled += 1
            confusions[(truth, "<rules-no-match>")] += 1
            continue
        if p == truth:
            correct += 1
            per_label_correct[truth] += 1
        else:
            confusions[(truth, p)] += 1

    per_label = {
        truth: {
            "total": per_label_total[truth],
            "correct": per_label_correct[truth],
            "accuracy": round(per_label_correct[truth] / per_label_total[truth], 4)
            if per_label_total[truth] else 0.0,
        }
        for truth in per_label_total
    }
    confusion_rows = [
        {"truth": t, "predicted": p, "count": c}
        for (t, p), c in confusions.most_common()
    ]
    return {
        "total": n,
        "correct": correct,
        "accuracy": round(correct / n, 4),
        "unhandled": unhandled,
        "per_label": per_label,
        "confusions": confusion_rows,
    }


def _diff_metrics(baseline: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "accuracy_delta": round(current["accuracy"] - baseline["accuracy"], 4),
        "unhandled_delta": current.get("unhandled", 0) - baseline.get("unhandled", 0),
        "baseline_accuracy": baseline["accuracy"],
        "current_accuracy": current["accuracy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=_default_corpus_path(),
                        help="path to label_corrections.jsonl")
    parser.add_argument("--report", help="write metrics JSON to this path")
    parser.add_argument("--baseline", help="compare against a previous report")
    parser.add_argument("--with-llm", action="store_true",
                        help="exercise the LLM path (costs ~$0.001/record)")
    parser.add_argument("--limit", type=int, default=0,
                        help="evaluate at most N records (0 = all)")
    args = parser.parse_args()

    records = _load_corpus(args.corpus)
    if args.limit:
        records = records[: args.limit]
    if not records:
        print(f"No records in corpus at {args.corpus} — nothing to evaluate.")
        return 0

    print(f"Evaluating {len(records)} corrections from {args.corpus}"
          f" ({'LLM' if args.with_llm else 'rules-only'} path)...")
    predictions = [_evaluate_one(r, use_llm=args.with_llm) for r in records]
    metrics = _compute_metrics(records, predictions)

    print(f"\nAccuracy: {metrics['accuracy']:.4f} ({metrics['correct']}/{metrics['total']})")
    if metrics.get("unhandled"):
        print(f"Unhandled (rules returned None): {metrics['unhandled']}")
    print("Per-label accuracy:")
    for label, stats in sorted(metrics["per_label"].items()):
        print(f"  {label:<10} {stats['accuracy']:.4f}  ({stats['correct']}/{stats['total']})")
    if metrics["confusions"][:10]:
        print("Top confusions:")
        for c in metrics["confusions"][:10]:
            print(f"  truth={c['truth']:<10} predicted={c['predicted']:<20} n={c['count']}")

    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        diff = _diff_metrics(baseline, metrics)
        print(f"\nDiff vs baseline: accuracy {diff['baseline_accuracy']:.4f}"
              f" → {diff['current_accuracy']:.4f}  (Δ {diff['accuracy_delta']:+.4f})")

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        print(f"\nReport written to {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
