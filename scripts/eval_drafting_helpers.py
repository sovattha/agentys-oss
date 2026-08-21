# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Helpers purs pour l'eval harness drafting (Run1 — Issue #468 Phase 1).

Ce module ne fait AUCUN appel LLM. Il regroupe :
- ``compute_latency_stats`` : stats p50/p95/mean/std sur une série de durées
- ``DraftingGold`` + ``load_golds`` : modèle gold éditable + loader json
- ``RunV1`` + ``write_run`` / ``load_run`` : schéma versionné des runs eval
- ``compare_runs`` + ``Verdict`` : détection régression latence/qualité

Le harness ``scripts/eval_drafting.py`` appelle ces helpers — ils sont
factorisés ici pour rester testables sans imports lourds (pas de
``from app.agents import …`` qui déclenche le chargement de tout le stack).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Latency stats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyStats:
    """Stats de latence (toutes en millisecondes)."""

    n: int
    p50_ms: float
    p95_ms: float
    mean_ms: float
    std_ms: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "mean_ms": self.mean_ms,
            "std_ms": self.std_ms,
        }


def compute_latency_stats(durations_ms: list[float]) -> LatencyStats:
    """Calcule p50/p95/mean/std sur une série de durées en ms.

    Pour ``n=1`` : p50 = p95 = mean = unique value, std = 0.
    Pour ``n=2`` : p50 = mean(deux), p95 = max (quantile dégénéré).
    Pour ``n >= 3`` : p50 via statistics.median, p95 via statistics.quantiles.

    Raises:
        ValueError: liste vide ou valeur négative (latence < 0 invalide).
    """
    if not durations_ms:
        raise ValueError("compute_latency_stats: empty input list")
    if any(d < 0 for d in durations_ms):
        raise ValueError("compute_latency_stats: negative duration not allowed")

    n = len(durations_ms)
    mean_ms = statistics.fmean(durations_ms)
    std_ms = statistics.pstdev(durations_ms) if n > 1 else 0.0
    p50_ms = statistics.median(durations_ms)

    # statistics.quantiles requires n >= 2. For n==1 we already returned.
    # For n==2, statistics.quantiles(method="exclusive") needs n >= 2 but
    # produces unstable p95. We fall back to max() — the conservative reading
    # of "the worst latency observed" matches user expectation when N is tiny.
    if n == 1:
        p95_ms = float(durations_ms[0])
    elif n == 2:
        p95_ms = float(max(durations_ms))
    else:
        # method="exclusive" + n=20 → 19th of 19 cut points = p95.
        # Empirically this is the most stable for small samples (n=3..30).
        # Cap to observed max: the exclusive method extrapolates beyond max
        # for small N, which would produce p95 values higher than any latency
        # actually measured. That breaks downstream alerts ("p95=1050ms" when
        # nothing was ever observed above 1000ms).
        quantiles = statistics.quantiles(durations_ms, n=20, method="exclusive")
        p95_raw = float(quantiles[18])
        p95_ms = min(p95_raw, float(max(durations_ms)))

    return LatencyStats(
        n=n,
        p50_ms=float(p50_ms),
        p95_ms=p95_ms,
        mean_ms=float(mean_ms),
        std_ms=float(std_ms),
    )


# ---------------------------------------------------------------------------
# Drafting gold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftingGold:
    """Réponse "parfaite cible" pour un cas eval, éditée à la main.

    Le ``gold_body`` est le corps idéal (sans signature/greeting). Le drafter
    n'aura jamais à matcher mot pour mot — c'est un repère qualitatif pour
    le LLM-as-judge en mode ``--with-gold``.
    """

    case_id: str
    gold_body: str
    rationale: str
    edge_cases_handled: tuple[str, ...] = field(default_factory=tuple)


def load_golds(path: Path) -> dict[str, DraftingGold]:
    """Charge un fichier ``golds.json`` en dict[case_id, DraftingGold].

    - Fichier absent → dict vide (le caller décide si c'est une erreur).
    - JSON invalide → JSONDecodeError remonté (programmer error).
    - Entry sans ``case_id`` → KeyError remonté (fichier corrompu).

    Le format attendu est une liste de dicts :
    ``[{"case_id": "...", "gold_body": "...", "rationale": "...", "edge_cases_handled": [...]}]``.
    """
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"load_golds: expected list at {path}, got {type(raw).__name__}")

    out: dict[str, DraftingGold] = {}
    for entry in raw:
        if "case_id" not in entry:
            raise KeyError(f"load_golds: entry missing 'case_id' in {path}")
        gold = DraftingGold(
            case_id=str(entry["case_id"]),
            gold_body=str(entry.get("gold_body", "")),
            rationale=str(entry.get("rationale", "")),
            edge_cases_handled=tuple(entry.get("edge_cases_handled") or ()),
        )
        out[gold.case_id] = gold
    return out


# ---------------------------------------------------------------------------
# Run schema (versioned)
# ---------------------------------------------------------------------------


_SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunV1:
    """Schéma figé v1 d'un run d'eval drafting.

    Toute évolution (ajout de champ critique, renommage) doit incrémenter
    ``_SUPPORTED_SCHEMA_VERSION`` et fournir un upgrader explicite. Sans cela
    ``--compare`` casse silencieusement entre runs.
    """

    schema_version: int
    timestamp_utc: str
    config: dict[str, Any]
    cases: list[dict[str, Any]]
    aggregate: dict[str, Any]


def write_run(run: RunV1, path: Path) -> None:
    """Sérialise ``run`` en JSON au chemin donné. Crée les dossiers parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": run.schema_version,
        "timestamp_utc": run.timestamp_utc,
        "config": run.config,
        "cases": run.cases,
        "aggregate": run.aggregate,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_run(path: Path) -> RunV1:
    """Charge un run.json. Raise sur version non supportée ou champ manquant."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"load_run: unsupported schema_version={version!r} "
            f"(supported: {_SUPPORTED_SCHEMA_VERSION})"
        )
    # Required fields — fail loud on corruption rather than silently using defaults.
    missing = [k for k in ("config", "cases", "aggregate") if k not in raw]
    if missing:
        raise KeyError(f"load_run: missing required fields {missing} in {path}")

    return RunV1(
        schema_version=version,
        timestamp_utc=str(raw.get("timestamp_utc", "")),
        config=raw["config"],
        cases=raw["cases"],
        aggregate=raw["aggregate"],
    )


# ---------------------------------------------------------------------------
# Compare runs
# ---------------------------------------------------------------------------


class Verdict(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CompareVerdict:
    """Résultat d'un compare_runs(). ``status`` est l'agrégat."""

    status: Verdict
    judge_delta: float  # current - baseline (positif = amélioration qualité)
    p50_delta_pct: float  # (current - baseline) / baseline * 100 (positif = régression latence)
    reasons: list[str]


# Default thresholds. Tunable via compare_runs() args. The choice -5 / +20%
# matches the LLM-as-judge variability noise floor (mémoire onboarding ±5pts)
# and a 20% latence margin keeps p99 alerts useful while ignoring ms jitter.
_DEFAULT_QUALITY_FAIL_DELTA = -5.0
_DEFAULT_LATENCY_FAIL_PCT = 20.0
_DEFAULT_QUALITY_WARN_DELTA = -2.0
_DEFAULT_LATENCY_WARN_PCT = 10.0


def compare_runs(
    *,
    baseline: RunV1,
    current: RunV1,
    quality_fail_delta: float = _DEFAULT_QUALITY_FAIL_DELTA,
    latency_fail_pct: float = _DEFAULT_LATENCY_FAIL_PCT,
    quality_warn_delta: float = _DEFAULT_QUALITY_WARN_DELTA,
    latency_warn_pct: float = _DEFAULT_LATENCY_WARN_PCT,
) -> CompareVerdict:
    """Compare deux runs et retourne PASS/WARN/FAIL.

    ``judge_delta`` : (current.judge_overall_mean - baseline.judge_overall_mean).
                      Négatif = qualité régresse.
    ``p50_delta_pct`` : variation relative de la latence p50.
                       Positif = latence empire.

    Ordre de severité (du pire au meilleur) : FAIL > WARN > PASS.
    Une raison FAIL latence ET FAIL qualité produit deux entrées dans ``reasons``.
    """
    baseline_judge = float(baseline.aggregate.get("judge_overall_mean", 0.0))
    current_judge = float(current.aggregate.get("judge_overall_mean", 0.0))
    judge_delta = current_judge - baseline_judge

    baseline_p50 = float(baseline.aggregate.get("p50_ms", 0.0))
    current_p50 = float(current.aggregate.get("p50_ms", 0.0))
    if baseline_p50 <= 0:
        # Pathological baseline; we cannot compute a percentage. Conservative read:
        # consider latency unchanged. This branch only triggers on hand-written
        # or malformed baselines.
        p50_delta_pct = 0.0
    else:
        p50_delta_pct = ((current_p50 - baseline_p50) / baseline_p50) * 100.0

    reasons: list[str] = []
    fail = False
    warn = False

    if judge_delta <= quality_fail_delta:
        reasons.append(
            f"quality regression: judge_overall_mean {judge_delta:+.1f} "
            f"(threshold {quality_fail_delta:+.1f})"
        )
        fail = True
    elif judge_delta <= quality_warn_delta:
        reasons.append(
            f"quality warn: judge_overall_mean {judge_delta:+.1f} "
            f"(warn threshold {quality_warn_delta:+.1f})"
        )
        warn = True

    if p50_delta_pct >= latency_fail_pct:
        reasons.append(
            f"latency regression: p50 {p50_delta_pct:+.1f}% "
            f"(threshold {latency_fail_pct:+.1f}%)"
        )
        fail = True
    elif p50_delta_pct >= latency_warn_pct:
        reasons.append(
            f"latency warn: p50 {p50_delta_pct:+.1f}% "
            f"(warn threshold {latency_warn_pct:+.1f}%)"
        )
        warn = True

    if fail:
        status = Verdict.FAIL
    elif warn:
        status = Verdict.WARN
    else:
        status = Verdict.PASS

    return CompareVerdict(
        status=status,
        judge_delta=judge_delta,
        p50_delta_pct=p50_delta_pct,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Résolution --max-cases (défaut per-persona vs troncature explicite)
# ---------------------------------------------------------------------------

# Défaut historique des chemins per-persona (extract_cases sur une fixture).
DEFAULT_PERSONA_MAX_CASES = 5


def resolve_persona_max_cases(max_cases: int | None) -> int:
    """Défaut 5 pour les chemins per-persona quand --max-cases est omis.

    Le défaut ne vit plus dans argparse : en mode --cases-file, un défaut
    silencieux tronquait la liste curée à 5/15 cas et faussait toute
    comparaison d'agrégats contre une baseline complète.
    """
    return DEFAULT_PERSONA_MAX_CASES if max_cases is None else max_cases


def apply_explicit_max_cases(
    cases: list[Any], max_cases: int | None
) -> tuple[list[Any], bool]:
    """Tronque ``cases`` UNIQUEMENT sur demande explicite (mode --cases-file).

    ``max_cases`` à ``None`` (omis) ou ``<= 0`` = aucune troncature.
    Returns ``(cases, truncated)`` — ``truncated=True`` seulement si une vraie
    troncature a eu lieu, pour que l'appelant l'affiche en clair.
    """
    if max_cases is not None and 0 < max_cases < len(cases):
        return list(cases[:max_cases]), True
    return list(cases), False
