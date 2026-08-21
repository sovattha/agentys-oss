#!/usr/bin/env python3
"""
Benchmark spaCy fr_core_news_md NER contre la ground truth du CSV annoté.

Calcule precision / recall / F1 par type d'entité (PER, ORG, LOC) et par catégorie d'email.
Produit aussi une liste détaillée des erreurs pour review manuelle.

Usage:
    python scripts/benchmark_spacy_ner.py [--csv PATH] [--model MODEL] [--verbose]

Dépendances :
    pip install spacy
    python -m spacy download fr_core_news_md

Convention de matching :
    - Exact match case-insensitive sur la forme normalisée (strip punct + whitespace)
    - Comparaison par type : un "Google" spaCy-ORG vs "Google" GT-ORG → match ; vs "Google" GT-LOC → type error
    - Dédoublonnage par (type, forme normalisée) pour matcher notre GT dédoublonnée

Output :
    - Rapport console : métriques globales + par type + par catégorie
    - docs/spacy-ner-benchmark.md : rapport markdown persistant
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


# spaCy label → notre label GT
SPACY_LABEL_MAP: dict[str, str] = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "ORG": "ORG",
    "LOC": "LOC",
    "GPE": "LOC",  # Geopolitical entity — souvent pays/ville
    # "MISC" ignoré volontairement (pas dans notre ground truth)
}


@dataclass
class Entity:
    """Entité normalisée pour comparaison."""
    text: str
    label: str  # PERSON|ORG|LOC

    def key(self) -> tuple[str, str]:
        return (self.label, normalize(self.text))


def normalize(text: str) -> str:
    """Normalisation pour matching : lowercase, strip punct aux extrémités, collapse spaces."""
    text = text.strip()
    # strip punctuation at extremities: . , ; ! ? : etc.
    text = re.sub(r"^[\s\.,;:!?'\"()\[\]]+", "", text)
    text = re.sub(r"[\s\.,;:!?'\"()\[\]]+$", "", text)
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def parse_gt_entities(row: dict) -> set[tuple[str, str]]:
    """Parse ground truth entities from a CSV row. Returns set of (label, normalized_text)."""
    entities: set[tuple[str, str]] = set()
    for col, label in [("entities_person", "PERSON"),
                       ("entities_org", "ORG"),
                       ("entities_loc", "LOC")]:
        raw = row.get(col, "").strip()
        if not raw:
            continue
        for token in raw.split("|"):
            token = token.strip()
            if token:
                entities.add((label, normalize(token)))
    return entities


def extract_spacy_entities(nlp, text: str) -> set[tuple[str, str]]:
    """Run spaCy on text, return set of (label, normalized_text)."""
    doc = nlp(text)
    entities: set[tuple[str, str]] = set()
    for ent in doc.ents:
        mapped = SPACY_LABEL_MAP.get(ent.label_)
        if mapped is None:
            continue
        entities.add((mapped, normalize(ent.text)))
    return entities


@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class RowComparison:
    row_id: str
    category: str
    gt: set[tuple[str, str]]
    pred: set[tuple[str, str]]

    @property
    def tp(self) -> set[tuple[str, str]]:
        return self.gt & self.pred

    @property
    def fp(self) -> set[tuple[str, str]]:
        return self.pred - self.gt

    @property
    def fn(self) -> set[tuple[str, str]]:
        return self.gt - self.pred


def run_benchmark(csv_path: Path, model_name: str, verbose: bool) -> dict:
    """Load model, read CSV, compare, compute metrics."""
    try:
        import spacy
    except ImportError:
        print("[ERROR] spacy not installed. Run: pip install spacy", file=sys.stderr)
        sys.exit(1)

    print(f"Loading spaCy model {model_name}...")
    try:
        nlp = spacy.load(model_name)
    except OSError:
        print(f"[ERROR] Model {model_name} not installed. Run: python -m spacy download {model_name}",
              file=sys.stderr)
        sys.exit(1)

    comparisons: list[RowComparison] = []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = f"{row.get('subject', '')}. {row.get('body_preview', '')}"
            gt = parse_gt_entities(row)
            pred = extract_spacy_entities(nlp, text)
            comparisons.append(RowComparison(
                row_id=row["id"],
                category=row.get("category", "unknown"),
                gt=gt,
                pred=pred,
            ))

    # --- Metrics calculation ---
    metrics_by_type: dict[str, Metrics] = defaultdict(Metrics)
    metrics_by_cat: dict[str, Metrics] = defaultdict(Metrics)
    metrics_overall = Metrics()

    for comp in comparisons:
        for ent in comp.tp:
            metrics_by_type[ent[0]].tp += 1
            metrics_by_cat[comp.category].tp += 1
            metrics_overall.tp += 1
        for ent in comp.fp:
            metrics_by_type[ent[0]].fp += 1
            metrics_by_cat[comp.category].fp += 1
            metrics_overall.fp += 1
        for ent in comp.fn:
            metrics_by_type[ent[0]].fn += 1
            metrics_by_cat[comp.category].fn += 1
            metrics_overall.fn += 1

    # --- Type confusion ---
    # Pour chaque FN (entity in GT but not in pred), vérifier si spaCy l'a trouvée sous un autre type
    type_confusions: dict[tuple[str, str], int] = defaultdict(int)  # (gt_type, pred_type) -> count
    for comp in comparisons:
        pred_texts_by_type: dict[str, set[str]] = defaultdict(set)
        for label, text in comp.pred:
            pred_texts_by_type[label].add(text)
        for gt_label, gt_text in comp.fn:
            # Cherche si spaCy a cette string sous un autre type
            for pred_label, texts in pred_texts_by_type.items():
                if pred_label != gt_label and gt_text in texts:
                    type_confusions[(gt_label, pred_label)] += 1

    return {
        "comparisons": comparisons,
        "metrics_overall": metrics_overall,
        "metrics_by_type": dict(metrics_by_type),
        "metrics_by_cat": dict(metrics_by_cat),
        "type_confusions": dict(type_confusions),
    }


def format_metrics(m: Metrics, label: str = "") -> str:
    return (f"{label:12s} P={m.precision:5.1%} R={m.recall:5.1%} F1={m.f1:5.1%} "
            f"(TP={m.tp}, FP={m.fp}, FN={m.fn})")


def print_console_report(results: dict) -> None:
    print("\n" + "=" * 70)
    print("  Benchmark spaCy fr_core_news_md — Ground Truth CSV")
    print("=" * 70)

    print("\n### Métriques globales")
    print(format_metrics(results["metrics_overall"], "ALL"))

    print("\n### Par type d'entité")
    for label in ["PERSON", "ORG", "LOC"]:
        m = results["metrics_by_type"].get(label, Metrics())
        print(format_metrics(m, label))

    print("\n### Par catégorie d'email")
    for cat in sorted(results["metrics_by_cat"]):
        m = results["metrics_by_cat"][cat]
        print(format_metrics(m, cat))

    print("\n### Confusion de type (entité trouvée par spaCy mais mal typée)")
    if results["type_confusions"]:
        for (gt, pred), count in sorted(results["type_confusions"].items(),
                                         key=lambda x: -x[1]):
            print(f"  GT={gt:7s} → spaCy={pred:7s} : {count}")
    else:
        print("  (aucune)")


def write_markdown_report(results: dict, out_path: Path, model_name: str) -> None:
    lines: list[str] = []
    lines.append("# Benchmark spaCy NER — fr_core_news_md\n")
    lines.append(f"**Model** : `{model_name}`\n")
    lines.append("**Date** : 2026-04-12\n")
    lines.append("**Dataset** : `tmp/ner_benchmark/emails.csv` (106 emails annotés)\n")
    lines.append("\n---\n")

    # Overall
    m = results["metrics_overall"]
    lines.append("## Métriques globales\n")
    lines.append("| Métrique | Valeur |\n|----------|-------:|\n")
    lines.append(f"| Precision | {m.precision:.1%} |\n")
    lines.append(f"| Recall | {m.recall:.1%} |\n")
    lines.append(f"| F1 | {m.f1:.1%} |\n")
    lines.append(f"| TP / FP / FN | {m.tp} / {m.fp} / {m.fn} |\n")

    # Par type
    lines.append("\n## Par type d'entité\n")
    lines.append("| Type | Precision | Recall | F1 | TP | FP | FN |\n")
    lines.append("|------|----------:|-------:|---:|---:|---:|---:|\n")
    for label in ["PERSON", "ORG", "LOC"]:
        m = results["metrics_by_type"].get(label, Metrics())
        lines.append(f"| {label} | {m.precision:.1%} | {m.recall:.1%} | "
                     f"{m.f1:.1%} | {m.tp} | {m.fp} | {m.fn} |\n")

    # Par catégorie
    lines.append("\n## Par catégorie d'email\n")
    lines.append("| Catégorie | Precision | Recall | F1 | TP | FP | FN |\n")
    lines.append("|-----------|----------:|-------:|---:|---:|---:|---:|\n")
    for cat in sorted(results["metrics_by_cat"]):
        m = results["metrics_by_cat"][cat]
        lines.append(f"| {cat} | {m.precision:.1%} | {m.recall:.1%} | "
                     f"{m.f1:.1%} | {m.tp} | {m.fp} | {m.fn} |\n")

    # Type confusions
    lines.append("\n## Confusions de type\n")
    if results["type_confusions"]:
        lines.append("Entités présentes dans la GT mais taggées sous un autre type par spaCy :\n\n")
        lines.append("| GT type | spaCy type | Count |\n|---------|-----------|------:|\n")
        for (gt, pred), count in sorted(results["type_confusions"].items(),
                                         key=lambda x: -x[1]):
            lines.append(f"| {gt} | {pred} | {count} |\n")
    else:
        lines.append("Aucune confusion de type détectée.\n")

    # Top FP et FN à examiner
    lines.append("\n## Échantillon d'erreurs (10 premières par type)\n")

    fps: list[tuple[str, str, str]] = []  # (row_id, label, text)
    fns: list[tuple[str, str, str]] = []
    for comp in results["comparisons"]:
        for (label, text) in comp.fp:
            fps.append((comp.row_id, label, text))
        for (label, text) in comp.fn:
            fns.append((comp.row_id, label, text))

    lines.append("### False positives (spaCy tag, GT ne tag pas)\n")
    lines.append("| Row | Type | Entité |\n|-----|------|--------|\n")
    for row_id, label, text in fps[:15]:
        lines.append(f"| {row_id} | {label} | {text} |\n")
    if len(fps) > 15:
        lines.append(f"\n...et {len(fps) - 15} autres.\n")

    lines.append("\n### False negatives (GT tag, spaCy rate)\n")
    lines.append("| Row | Type | Entité |\n|-----|------|--------|\n")
    for row_id, label, text in fns[:15]:
        lines.append(f"| {row_id} | {label} | {text} |\n")
    if len(fns) > 15:
        lines.append(f"\n...et {len(fns) - 15} autres.\n")

    # Décision gate
    lines.append("\n## Décision gate\n")
    per_m = results["metrics_by_type"].get("PERSON", Metrics())
    if per_m.recall >= 0.95:
        lines.append(f"✅ **spaCy seul OK** — PERSON recall = {per_m.recall:.1%} ≥ 95%.\n")
    elif per_m.recall >= 0.85:
        lines.append(f"🟡 **spaCy + whitelist INSEE requis** — PERSON recall = {per_m.recall:.1%} "
                     f"(85-95%). Ajouter une liste de 500 prénoms FR fréquents pour compenser.\n")
    else:
        lines.append(f"🔴 **spaCy insuffisant** — PERSON recall = {per_m.recall:.1%} < 85%. "
                     f"Évaluer alternatives (fr_core_news_lg, flair/ner-french, XLM-R) ou review 100% "
                     f"des fixtures avant commit.\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines), encoding="utf-8")
    print(f"\nRapport écrit : {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", type=Path, default=Path("tmp/ner_benchmark/emails.csv"))
    parser.add_argument("--model", default="fr_core_news_md")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("docs/spacy-ner-benchmark.md"))
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"[ERROR] CSV not found : {args.csv}", file=sys.stderr)
        return 1

    results = run_benchmark(args.csv, args.model, args.verbose)
    print_console_report(results)
    write_markdown_report(results, args.out, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
