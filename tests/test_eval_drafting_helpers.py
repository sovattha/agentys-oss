# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour scripts/eval_drafting_helpers.py.

Run1 — Issue #468 Phase 1 : helpers purs sans appel LLM.

On teste :
- compute_latency_stats() : p50/p95/mean/std sur séries connues
- DraftingGold + load_golds() : chargement fichier json + cas absent
- RunV1 + write_run() / load_run() : sérialisation/désérialisation roundtrip
- compare_runs() : détection régression latence et qualité
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from eval_drafting_helpers import (  # noqa: E402
    DEFAULT_PERSONA_MAX_CASES,
    DraftingGold,
    RunV1,
    Verdict,
    apply_explicit_max_cases,
    compare_runs,
    compute_latency_stats,
    load_golds,
    load_run,
    resolve_persona_max_cases,
    write_run,
)


# ── compute_latency_stats ───────────────────────────────────────────────────


class TestComputeLatencyStats:
    def test_single_value_returns_p50_eq_p95_eq_mean(self):
        stats = compute_latency_stats([1500.0])
        assert stats.n == 1
        assert stats.p50_ms == 1500.0
        assert stats.p95_ms == 1500.0
        assert stats.mean_ms == 1500.0
        assert stats.std_ms == 0.0

    def test_two_values_p50_is_median(self):
        # Two identical values
        stats = compute_latency_stats([1000.0, 2000.0])
        assert stats.n == 2
        assert stats.p50_ms == 1500.0
        # p95 with n=2 falls back to max (degenerate quantile)
        assert stats.p95_ms == 2000.0

    def test_known_series_p50_p95(self):
        # 10 values evenly spaced 100, 200, ..., 1000
        # median = 550 (mean of 500 and 600)
        # p95 with n=10 → ~950 (statistics.quantiles n=20 method=exclusive)
        durations = [100.0 * i for i in range(1, 11)]
        stats = compute_latency_stats(durations)
        assert stats.n == 10
        assert stats.p50_ms == 550.0
        assert stats.p95_ms >= 900.0  # quantile method varies, just check range
        assert stats.p95_ms <= 1000.0
        assert stats.mean_ms == 550.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            compute_latency_stats([])

    def test_negative_value_raises(self):
        with pytest.raises(ValueError, match="negative"):
            compute_latency_stats([100.0, -50.0])

    def test_constant_series_std_zero(self):
        stats = compute_latency_stats([2000.0] * 5)
        assert stats.std_ms == 0.0
        assert stats.p50_ms == 2000.0


# ── DraftingGold + load_golds ───────────────────────────────────────────────


class TestDraftingGold:
    def test_dataclass_immutable(self):
        gold = DraftingGold(
            case_id="c1",
            gold_body="Hello world",
            rationale="Polite reply",
            edge_cases_handled=("greet", "ack"),
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            gold.gold_body = "Modified"  # type: ignore[misc]

    def test_load_golds_returns_dict(self, tmp_path: Path):
        golds_file = tmp_path / "golds.json"
        golds_file.write_text(
            json.dumps(
                [
                    {
                        "case_id": "c1",
                        "gold_body": "Bonjour, voici la réponse.",
                        "rationale": "ton formel attendu",
                        "edge_cases_handled": ["formal", "fr"],
                    },
                    {
                        "case_id": "c2",
                        "gold_body": "Hi, here is the reply.",
                        "rationale": "casual EN",
                        "edge_cases_handled": [],
                    },
                ]
            ),
            encoding="utf-8",
        )
        golds = load_golds(golds_file)
        assert isinstance(golds, dict)
        assert set(golds.keys()) == {"c1", "c2"}
        assert golds["c1"].gold_body == "Bonjour, voici la réponse."
        assert golds["c2"].edge_cases_handled == ()

    def test_load_golds_missing_file_returns_empty_dict(self, tmp_path: Path):
        golds = load_golds(tmp_path / "nonexistent.json")
        assert golds == {}

    def test_load_golds_invalid_json_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_golds(bad)

    def test_load_golds_missing_case_id_raises(self, tmp_path: Path):
        bad = tmp_path / "missing_id.json"
        bad.write_text(json.dumps([{"gold_body": "x"}]), encoding="utf-8")
        with pytest.raises(KeyError, match="case_id"):
            load_golds(bad)


# ── RunV1 + write_run / load_run ────────────────────────────────────────────


def _make_run(judge_overall_mean: float = 84.0, p50_ms: float = 2300.0) -> RunV1:
    return RunV1(
        schema_version=1,
        timestamp_utc="2026-05-04T01:00:00Z",
        config={
            "drafter_model": "claude-haiku-4-5",
            "self_critique": "shadow",
            "critic": "off",
            "judge_model": "sonnet-4-6",
            "prompt_hash": "abc123",
            "repeat": 3,
        },
        cases=[
            {
                "case_id": "c1",
                "persona": "lawyer_paris",
                "runs": [
                    {"latency_ms": 2200, "judge_overall": 85},
                    {"latency_ms": 2400, "judge_overall": 82},
                    {"latency_ms": 2300, "judge_overall": 86},
                ],
            }
        ],
        aggregate={
            "p50_ms": p50_ms,
            "p95_ms": 2400.0,
            "judge_overall_mean": judge_overall_mean,
            "judge_overall_p25": 82.0,
        },
    )


class TestRunSchema:
    def test_write_then_load_roundtrip(self, tmp_path: Path):
        run = _make_run()
        target = tmp_path / "run.json"
        write_run(run, target)
        loaded = load_run(target)
        assert loaded.schema_version == 1
        assert loaded.config == run.config
        assert loaded.aggregate == run.aggregate
        assert loaded.cases == run.cases

    def test_write_creates_parent_dir(self, tmp_path: Path):
        target = tmp_path / "nested" / "subdir" / "run.json"
        write_run(_make_run(), target)
        assert target.exists()

    def test_load_run_with_unsupported_schema_raises(self, tmp_path: Path):
        target = tmp_path / "run.json"
        target.write_text(
            json.dumps({"schema_version": 99, "config": {}, "cases": [], "aggregate": {}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="schema_version"):
            load_run(target)

    def test_load_run_missing_required_field_raises(self, tmp_path: Path):
        target = tmp_path / "run.json"
        target.write_text(
            json.dumps({"schema_version": 1, "config": {}}),  # no cases / aggregate
            encoding="utf-8",
        )
        with pytest.raises(KeyError):
            load_run(target)


# ── compare_runs ────────────────────────────────────────────────────────────


class TestCompareRuns:
    def test_no_regression_returns_pass(self):
        baseline = _make_run(judge_overall_mean=84.0, p50_ms=2300.0)
        current = _make_run(judge_overall_mean=84.5, p50_ms=2280.0)
        verdict = compare_runs(baseline=baseline, current=current)
        assert verdict.status == Verdict.PASS
        assert verdict.judge_delta == pytest.approx(0.5)
        assert verdict.p50_delta_pct == pytest.approx(-(20 / 2300) * 100, abs=0.5)

    def test_quality_regression_fails(self):
        # judge drops by 6 → fails (default threshold = -5)
        baseline = _make_run(judge_overall_mean=84.0, p50_ms=2300.0)
        current = _make_run(judge_overall_mean=78.0, p50_ms=2300.0)
        verdict = compare_runs(baseline=baseline, current=current)
        assert verdict.status == Verdict.FAIL
        assert "quality" in verdict.reasons[0].lower()

    def test_latency_regression_fails(self):
        # p50 +21% → fails (default threshold = +20%)
        baseline = _make_run(judge_overall_mean=84.0, p50_ms=2000.0)
        current = _make_run(judge_overall_mean=84.0, p50_ms=2420.0)
        verdict = compare_runs(baseline=baseline, current=current)
        assert verdict.status == Verdict.FAIL
        assert "latency" in verdict.reasons[0].lower()

    def test_warning_within_thresholds(self):
        # quality drops 3 (within ±5) → warn but not fail
        baseline = _make_run(judge_overall_mean=84.0, p50_ms=2300.0)
        current = _make_run(judge_overall_mean=81.0, p50_ms=2300.0)
        verdict = compare_runs(baseline=baseline, current=current)
        assert verdict.status == Verdict.WARN
        assert verdict.judge_delta == pytest.approx(-3.0)

    def test_custom_thresholds(self):
        baseline = _make_run(judge_overall_mean=84.0, p50_ms=2000.0)
        current = _make_run(judge_overall_mean=82.0, p50_ms=2200.0)
        # Tighter quality threshold : -1 fails
        verdict = compare_runs(
            baseline=baseline,
            current=current,
            quality_fail_delta=-1.0,
            latency_fail_pct=5.0,
        )
        assert verdict.status == Verdict.FAIL
        # Both quality AND latency failing
        assert any("quality" in r.lower() for r in verdict.reasons)
        assert any("latency" in r.lower() for r in verdict.reasons)


# ── CLI wiring smoke tests (no LLM) ─────────────────────────────────────────


class TestCLIWiring:
    """Smoke tests on eval_drafting.py CLI surface — no actual drafting.

    These tests verify the new --repeat / --with-gold / --gold-dir flags are
    parsed correctly and that the v1+all-personas guardrail exits cleanly.
    """

    def test_help_lists_new_flags(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_drafting.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert result.returncode == 0
        out = result.stdout
        assert "--repeat" in out
        assert "--with-gold" in out
        assert "--gold-dir" in out
        # Guardrail message must mention Run2
        # (validated separately in test_v1_with_all_personas_exits_2)

    def test_load_cases_file_returns_drafting_cases(self):
        """load_cases_file lit cases.json et retourne list[DraftingCase].

        Indispensable pour étendre la baseline à tous les personas via le
        cases.json curé sans passer par les fixtures persona une à une.
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        from eval_drafting import DraftingCase, load_cases_file

        cases_path = ROOT / "tests" / "fixtures" / "drafting_eval" / "cases.json"
        if not cases_path.exists():
            pytest.skip("cases.json not generated yet (run curate_drafting_cases.py)")

        cases = load_cases_file(cases_path)
        assert isinstance(cases, list)
        assert len(cases) >= 2
        assert all(isinstance(c, DraftingCase) for c in cases)
        # Verify essential fields
        c = cases[0]
        assert c.case_id
        assert c.user_email
        assert c.incoming_email.get("body")
        # instructions field defaults to "" for cases without keywords
        assert isinstance(c.instructions, str)

    def test_load_cases_file_missing_required_field_raises(self, tmp_path: Path):
        """Manque case_id ou incoming_email → KeyError loud."""
        sys.path.insert(0, str(ROOT / "scripts"))
        from eval_drafting import load_cases_file

        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps([{"persona": "x"}]), encoding="utf-8")
        with pytest.raises(KeyError):
            load_cases_file(bad)

    def test_format_instructions_section_empty_when_no_instructions(self):
        """Sans instructions, la section judge doit être vide.

        Garantit la rétrocompat : les baselines figées sans `instructions`
        ne voient PAS de bloc supplémentaire dans le prompt user du judge
        (sinon la baseline serait incomparable aux runs Run2+).
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        from eval_drafting import _format_instructions_section

        assert _format_instructions_section("") == ""
        assert _format_instructions_section("   ") == ""
        assert _format_instructions_section("\n\t  \n") == ""

    def test_format_instructions_section_includes_keywords(self):
        """Avec instructions, la section doit contenir le texte + cadre clair."""
        sys.path.insert(0, str(ROOT / "scripts"))
        from eval_drafting import _format_instructions_section

        out = _format_instructions_section("décliner poliment, proposer mardi 14h")
        assert "MOTS-CLÉS UTILISATEUR" in out
        assert "Reply Composer" in out
        assert "décliner poliment, proposer mardi 14h" in out
        # Cadre judge : ne doit pas pénaliser les choix guidés
        assert "Ne pénalise pas" in out

    def test_drafting_case_supports_instructions_field(self):
        """DraftingCase doit accepter un champ `instructions` optionnel.

        En prod, `drafter.draft(..., instructions=user_keywords)` reçoit les
        mots-clés tapés dans Reply Composer. Le harness sans ce champ teste
        un cas dégénéré (auto-draft) qui ne reflète pas la majorité du
        trafic. Sans cette régression-test, on retomberait dans le même gap.
        """
        # Import depuis eval_drafting — DraftingCase y est défini, pas dans helpers.
        # Lazy import car charger eval_drafting tire app.agents (~20MB stack).
        sys.path.insert(0, str(ROOT / "scripts"))
        from eval_drafting import DraftingCase  # noqa: WPS433 (intentional lazy)

        case = DraftingCase(
            case_id="c1",
            user_email="x@y.z",
            user_name="X",
            incoming_email={"from": "a@b.c", "subject": "s", "body": "b"},
            conversation_history=[],
            reference_reply=None,
            thread_id="t1",
            user_signature=None,
            instructions="décliner poliment, proposer mardi 14h",
        )
        assert case.instructions == "décliner poliment, proposer mardi 14h"

        # Default empty string when not provided (prod default in agents.py:253)
        case2 = DraftingCase(
            case_id="c2",
            user_email="x@y.z",
            user_name="X",
            incoming_email={"from": "a@b.c", "subject": "s", "body": "b"},
            conversation_history=[],
            reference_reply=None,
            thread_id="t2",
            user_signature=None,
        )
        assert case2.instructions == ""

    def test_use_orchestrator_flag_visible_in_help(self):
        """--use-orchestrator + --gate-mode doivent apparaître dans --help."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_drafting.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert result.returncode == 0
        out = result.stdout
        assert "--use-orchestrator" in out
        assert "--gate-mode" in out

    def test_gate_mode_flag_validates_choices(self):
        """--gate-mode rejette les valeurs invalides (cas typo)."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval_drafting.py"),
                "--persona",
                "lawyer_paris",
                "--use-orchestrator",
                "--gate-mode",
                "banana",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        # argparse exit 2 on invalid choice
        assert result.returncode == 2
        assert "banana" in result.stderr or "invalid choice" in result.stderr.lower()

    def test_v1_with_all_personas_exits_2(self):
        """Combining v1 mode (--with-gold) with --all-personas must fail loudly.

        Run1 only supports v1 single-persona; the combined path is tracked
        for Run2 alongside gold curation. Guardrail prevents silent fallback.
        """
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval_drafting.py"),
                "--persona",
                "lawyer_paris",
                "--all-personas",
                "--with-gold",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert result.returncode == 2, f"Expected exit 2, got {result.returncode}. stdout={result.stdout!r}"
        # Either points to --cases-file (new, preferred) or mentions persona requirement.
        combined = result.stdout + result.stderr
        assert "--cases-file" in combined or "--persona" in combined


# ── resolve_persona_max_cases / apply_explicit_max_cases ────────────────────
# Régression 2026-06-10 : --max-cases avait default=5 dans argparse, donc le
# mode --cases-file tronquait silencieusement la liste curée à 5/15 cas et
# les agrégats étaient comparés à une baseline complète sans avertissement.


class TestResolvePersonaMaxCases:
    def test_none_resolves_to_historical_default(self):
        assert resolve_persona_max_cases(None) == DEFAULT_PERSONA_MAX_CASES

    def test_explicit_value_passes_through(self):
        assert resolve_persona_max_cases(3) == 3
        assert resolve_persona_max_cases(15) == 15


class TestApplyExplicitMaxCases:
    def test_omitted_keeps_all_cases(self):
        cases = list(range(15))
        out, truncated = apply_explicit_max_cases(cases, None)
        assert out == cases
        assert truncated is False

    def test_explicit_truncates_and_flags(self):
        cases = list(range(15))
        out, truncated = apply_explicit_max_cases(cases, 5)
        assert out == list(range(5))
        assert truncated is True

    def test_explicit_above_length_is_noop(self):
        cases = list(range(3))
        out, truncated = apply_explicit_max_cases(cases, 10)
        assert out == cases
        assert truncated is False

    def test_zero_or_negative_means_all(self):
        cases = list(range(4))
        for value in (0, -1):
            out, truncated = apply_explicit_max_cases(cases, value)
            assert out == cases
            assert truncated is False

    def test_returns_copy_not_alias(self):
        cases = list(range(4))
        out, _ = apply_explicit_max_cases(cases, None)
        out.append(99)
        assert len(cases) == 4
