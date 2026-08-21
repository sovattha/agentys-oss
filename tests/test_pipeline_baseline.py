"""Tests for scripts/pipeline_baseline.py — Phase 0 of unified draft pipeline."""

import json
import sys
from pathlib import Path


# Allow `import pipeline_baseline` from the scripts/ directory.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import pipeline_baseline as pb  # noqa: E402


# ---------------------------------------------------------------------------
# parse_critique_json
# ---------------------------------------------------------------------------

class TestParseCritiqueJson:
    def test_returns_empty_dict_on_none(self):
        assert pb.parse_critique_json(None) == {}

    def test_returns_empty_dict_on_blank(self):
        assert pb.parse_critique_json("") == {}
        assert pb.parse_critique_json("   ") == {}

    def test_returns_empty_dict_on_invalid_json(self):
        assert pb.parse_critique_json("not json {") == {}

    def test_returns_dict_on_valid_json(self):
        raw = '{"overall_score": 87, "skipped": true, "skip_reason": "heuristic_gate_passed"}'
        out = pb.parse_critique_json(raw)
        assert out["overall_score"] == 87
        assert out["skipped"] is True
        assert out["skip_reason"] == "heuristic_gate_passed"

    def test_handles_double_encoded_json(self):
        # Some legacy rows are stringified twice — parser must unwrap
        raw = json.dumps(json.dumps({"overall_score": 80}))
        out = pb.parse_critique_json(raw)
        assert out == {"overall_score": 80}

    def test_double_encoded_garbage_returns_empty(self):
        # Outer wraps a non-JSON string — must NOT raise, returns {}
        raw = json.dumps("not json at all {")
        out = pb.parse_critique_json(raw)
        assert out == {}


# ---------------------------------------------------------------------------
# aggregate_metrics
# ---------------------------------------------------------------------------

def _row(
    *,
    model="claude-haiku-4-5",
    status="DRAFT",
    processing_time_ms=1500,
    tokens_used=1200,
    critique=None,
    days_ago=1,
):
    """Build a draft_history-like row dict."""
    from datetime import datetime, timedelta, timezone
    return {
        "id": 1,
        "account_id": 1,
        "email_id": "msg-1",
        "model": model,
        "status": status,
        "processing_time_ms": processing_time_ms,
        "tokens_used": tokens_used,
        "critique": json.dumps(critique) if critique is not None else None,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }


class TestAggregateMetrics:
    def test_empty_input_returns_zeroed_report(self):
        m = pb.aggregate_metrics([], [])
        assert m["total_drafts"] == 0
        assert m["latency_p50_ms"] == 0
        assert m["latency_p95_ms"] == 0
        assert m["cost_total_usd"] == 0.0

    def test_counts_drafts_and_models(self):
        rows = [
            _row(model="claude-haiku-4-5"),
            _row(model="claude-haiku-4-5"),
            _row(model="claude-sonnet-4-6"),
        ]
        m = pb.aggregate_metrics(rows, [])
        assert m["total_drafts"] == 3
        assert m["by_model"]["claude-haiku-4-5"]["count"] == 2
        assert m["by_model"]["claude-sonnet-4-6"]["count"] == 1

    def test_proxy_tier_classification(self):
        rows = [
            _row(model="claude-haiku-4-5"),
            _row(model="claude-3-5-haiku-20241022"),  # different naming variant
            _row(model="claude-sonnet-4-6"),
            _row(model="claude-opus-4-7"),
            _row(model="gpt-4o"),  # unknown
        ]
        m = pb.aggregate_metrics(rows, [])
        assert m["by_model"]["claude-haiku-4-5"]["proxy_tier"].startswith("STANDARD")
        assert m["by_model"]["claude-3-5-haiku-20241022"]["proxy_tier"].startswith("STANDARD")
        assert m["by_model"]["claude-sonnet-4-6"]["proxy_tier"] == "COMPLEX (Sonnet)"
        assert m["by_model"]["claude-opus-4-7"]["proxy_tier"] == "COMPLEX (Opus)"
        assert m["by_model"]["gpt-4o"]["proxy_tier"].startswith("OTHER")

    def test_zero_tokens_counts_as_data_not_missing(self):
        # tokens_used=0 is a valid cached call; must NOT be filtered out
        rows = [_row(tokens_used=0), _row(tokens_used=1000)]
        m = pb.aggregate_metrics(rows, [])
        assert m["tokens_avg"] == 500  # (0 + 1000) / 2

    def test_active_days_counts_distinct_dates(self):
        rows = [
            _row(days_ago=1),
            _row(days_ago=1),  # same day
            _row(days_ago=3),
            _row(days_ago=5),
        ]
        m = pb.aggregate_metrics(rows, [])
        assert m["active_days"] == 3

    def test_latency_percentiles(self):
        rows = [_row(processing_time_ms=t) for t in [100, 500, 1000, 2000, 5000]]
        m = pb.aggregate_metrics(rows, [])
        # p50 of [100,500,1000,2000,5000] is 1000, p95 ≈ 5000
        assert m["latency_p50_ms"] == 1000
        assert m["latency_p95_ms"] >= 4000

    def test_skipped_critic_rate(self):
        rows = [
            _row(critique={"skipped": True, "skip_reason": "heuristic_gate_passed"}),
            _row(critique={"skipped": True, "skip_reason": "heuristic_gate_passed"}),
            _row(critique={"skipped": False, "overall_score": 60, "was_revised": True}),
        ]
        m = pb.aggregate_metrics(rows, [])
        # 2/3 skipped — gate skip rate ≈ 0.667
        assert 0.6 < m["gate_skip_rate"] < 0.7

    def test_was_revised_rate(self):
        rows = [
            _row(critique={"skipped": False, "was_revised": True, "overall_score": 60}),
            _row(critique={"skipped": False, "was_revised": False, "overall_score": 85}),
            _row(critique={"skipped": False, "was_revised": False, "overall_score": 88}),
        ]
        m = pb.aggregate_metrics(rows, [])
        # Of the 3 drafts that ran the critic, 1 was revised → 1/3
        assert 0.3 < m["critic_revision_rate"] < 0.4

    def test_cost_total_from_cost_tracking(self):
        cost_rows = [
            {"date": "2026-04-29", "model": "claude-haiku-4-5", "cost_usd": 0.50, "request_count": 1000},
            {"date": "2026-04-30", "model": "claude-haiku-4-5", "cost_usd": 0.30, "request_count": 600},
            {"date": "2026-04-30", "model": "claude-sonnet-4-6", "cost_usd": 0.20, "request_count": 20},
        ]
        m = pb.aggregate_metrics([], cost_rows)
        assert abs(m["cost_total_usd"] - 1.00) < 0.001
        assert abs(m["cost_by_model"]["claude-haiku-4-5"] - 0.80) < 0.001

    def test_critique_score_distribution(self):
        rows = [
            _row(critique={"skipped": False, "overall_score": s, "was_revised": False})
            for s in [60, 70, 75, 80, 85, 90, 95]
        ]
        m = pb.aggregate_metrics(rows, [])
        # p50 of [60,70,75,80,85,90,95] is 80
        assert m["critique_score_p50"] == 80


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

class TestRenderMarkdown:
    def test_renders_required_sections(self):
        metrics = pb.aggregate_metrics(
            [_row(critique={"skipped": True, "skip_reason": "heuristic_gate_passed"})],
            [{"date": "2026-04-30", "model": "claude-haiku-4-5", "cost_usd": 0.001, "request_count": 1}],
        )
        md = pb.render_markdown(metrics, days=14)

        # Required headers (accents enforced — règle CLAUDE.md)
        assert "# Pipeline draft baseline" in md
        assert "## Distribution par modèle" in md
        assert "## Coûts mensuels projetés" in md
        assert "## Recommandation seuil initial self_score" in md
        assert "## Résumé exécutif" in md

        # Required metrics
        assert "Total drafts" in md
        assert "p50" in md.lower()
        assert "p95" in md.lower()

    def test_recommends_threshold_75_when_revision_rate_low(self):
        # Revision rate < 10% → keep conservative seuil 75
        rows = [_row(critique={"skipped": False, "was_revised": False, "overall_score": 88})] * 19
        rows.append(_row(critique={"skipped": False, "was_revised": True, "overall_score": 65}))
        metrics = pb.aggregate_metrics(rows, [])
        # Sanity: the fixture really is < 10%
        assert metrics["critic_revision_rate"] < 0.10
        md = pb.render_markdown(metrics, days=14)
        assert "Seuil retenu : 75" in md

    def test_warns_if_no_data(self):
        metrics = pb.aggregate_metrics([], [])
        md = pb.render_markdown(metrics, days=14)
        assert "aucune donnee" in md.lower() or "aucune donnée" in md.lower()
