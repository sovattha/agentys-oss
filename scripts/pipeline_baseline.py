#!/usr/bin/env python
"""Pipeline draft baseline — Phase 0 of unified Drafter+SelfCritique pipeline.

Reads `draft_history` and `cost_tracking` from the Agentys SQLCipher database,
aggregates metrics over a configurable window (default 14 days), and emits a
markdown report consumed by the Phase 1 calibration.

Read-only. No prod code is modified. No LLM call.

Usage:
    python scripts/pipeline_baseline.py [--db PATH] [--days 14] [--out PATH]

Exit codes:
    0  success
    1  AGENTYS_ENCRYPTION_KEY missing (DB encrypted, cannot read)
    2  database file not found or unreadable
    3  unexpected error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# `tier` is not persisted in draft_history (only logged). We use `model` as a
# coarse proxy: any model name containing 'haiku' ≈ SIMPLE/STANDARD,
# any 'sonnet' ≈ COMPLEX. Phase 1 must add explicit tier persistence.
_HAIKU_PATTERNS = ("haiku",)
_SONNET_PATTERNS = ("sonnet",)
_OPUS_PATTERNS = ("opus",)

# SQLCipher key must be 64-char hex (32 raw bytes). Any other shape would be
# rejected by SQLCipher itself, but we validate up-front to avoid SQL injection
# via PRAGMA interpolation (cannot use ? placeholder in PRAGMA).
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# ---------------------------------------------------------------------------
# Pure helpers (testable without DB)
# ---------------------------------------------------------------------------

def parse_critique_json(raw: Any) -> dict:
    """Parse the `critique` column safely. Returns {} on any failure.

    Why robust: `draft_history.critique` was historically a free text field and
    contains a mix of stringified JSON, double-stringified JSON, and plain
    text from older code paths. Never raises — a failed parse means the row
    just doesn't contribute to critique-derived metrics.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip()
    if not s:
        return {}
    try:
        out = json.loads(s)
        if isinstance(out, str):
            # Double-encoded JSON — try one more layer
            try:
                out2 = json.loads(out)
                return out2 if isinstance(out2, dict) else {}
            except (json.JSONDecodeError, ValueError):
                return {}
        return out if isinstance(out, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (numpy-compatible). Returns 0 on empty."""
    if not values:
        return 0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _model_proxy_tier(model: str) -> str:
    """Coarse tier proxy from model name. Patterns match any prefix/suffix variant
    (e.g. claude-haiku-4-5, claude-3-5-haiku-20241022 both classify as Haiku)."""
    if not model:
        return "UNKNOWN"
    m = model.lower()
    if any(p in m for p in _HAIKU_PATTERNS):
        return "STANDARD/SIMPLE (Haiku)"
    if any(p in m for p in _SONNET_PATTERNS):
        return "COMPLEX (Sonnet)"
    if any(p in m for p in _OPUS_PATTERNS):
        return "COMPLEX (Opus)"
    return f"OTHER ({model})"


def aggregate_metrics(rows: list[dict], cost_rows: list[dict]) -> dict:
    """Aggregate draft_history rows + cost_tracking rows into a flat metrics dict.

    `tokens_used = 0` is a valid value (e.g. cached LLM call). We treat only `None`
    as missing — `0` contributes to the average. Same for `processing_time_ms`.
    """
    total = len(rows)
    latencies = [r["processing_time_ms"] for r in rows if r.get("processing_time_ms") is not None]
    tokens = [r["tokens_used"] for r in rows if r.get("tokens_used") is not None]

    # Per-model breakdown
    by_model: dict[str, dict] = {}
    for r in rows:
        model = r.get("model") or "unknown"
        bucket = by_model.setdefault(model, {"count": 0, "latencies": [], "tokens": []})
        bucket["count"] += 1
        if r.get("processing_time_ms") is not None:
            bucket["latencies"].append(r["processing_time_ms"])
        if r.get("tokens_used") is not None:
            bucket["tokens"].append(r["tokens_used"])

    # Compute per-model p50 in-place
    for model, bucket in by_model.items():
        bucket["latency_p50_ms"] = int(_percentile(bucket["latencies"], 50))
        bucket["proxy_tier"] = _model_proxy_tier(model)
        # Drop raw arrays before serialisation
        del bucket["latencies"]
        del bucket["tokens"]

    # Critic-related metrics — derived from critique JSON
    skipped_count = 0
    critic_ran_count = 0
    revised_count = 0
    scores = []
    for r in rows:
        crit = parse_critique_json(r.get("critique"))
        if not crit:
            continue
        if crit.get("skipped"):
            skipped_count += 1
        else:
            critic_ran_count += 1
            if crit.get("was_revised"):
                revised_count += 1
        if isinstance(crit.get("overall_score"), (int, float)):
            scores.append(crit["overall_score"])

    gate_skip_rate = skipped_count / total if total else 0.0
    critic_revision_rate = revised_count / critic_ran_count if critic_ran_count else 0.0

    # Cost from cost_tracking
    cost_total = sum(float(c.get("cost_usd", 0) or 0) for c in cost_rows)
    cost_by_model: dict[str, float] = {}
    for c in cost_rows:
        m = c.get("model") or "unknown"
        cost_by_model[m] = cost_by_model.get(m, 0.0) + float(c.get("cost_usd", 0) or 0)

    # Active days = distinct YYYY-MM-DD seen in created_at. Linear projections
    # over the requested window are misleading when the backend was idle for
    # part of it; we expose this so the report can warn the reader.
    active_days = len({
        str(r["created_at"])[:10] for r in rows
        if r.get("created_at")
    })

    return {
        "total_drafts": total,
        "latency_p50_ms": int(_percentile(latencies, 50)),
        "latency_p95_ms": int(_percentile(latencies, 95)),
        "tokens_avg": int(statistics.mean(tokens)) if tokens else 0,
        "by_model": by_model,
        "gate_skip_rate": gate_skip_rate,
        "critic_revision_rate": critic_revision_rate,
        "critique_score_p50": int(_percentile(scores, 50)),
        "critique_score_p95": int(_percentile(scores, 95)),
        "critique_scores_count": len(scores),
        "cost_total_usd": round(cost_total, 4),
        "cost_by_model": {k: round(v, 4) for k, v in cost_by_model.items()},
        "active_days": active_days,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(metrics: dict, days: int) -> str:
    """Render the baseline as a self-contained markdown report."""
    total = metrics["total_drafts"]
    if total == 0:
        return (
            "# Pipeline draft baseline\n\n"
            f"**Généré** : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Fenêtre** : {days} derniers jours\n\n"
            "## Aucune donnée\n\n"
            "Aucune ligne dans `draft_history` sur la fenêtre demandée. La DB cible ne contient\n"
            "soit aucun draft (DB locale dev), soit aucun draft sur la période (backend inactif).\n\n"
            "## Générer le vrai baseline depuis la prod\n\n"
            "Le script doit tourner sur Railway pour accéder à la DB SQLCipher de production :\n\n"
            "```bash\n"
            "# Depuis le repo agentys/ local, avec railway CLI authentifiée :\n"
            "railway run python scripts/pipeline_baseline.py --days 14 \\\n"
            "    --out tasks/pipeline-baseline-prod-$(date +%Y-%m-%d).md\n"
            "```\n\n"
            "Le script lit en read-only — aucun risque d'effet de bord.\n"
            "Il honore `AGENTYS_ENCRYPTION_KEY` automatiquement quand sqlcipher3 est détecté.\n\n"
            "## Alternative : télécharger un dump et tourner localement\n\n"
            "```bash\n"
            "# Dump prod -> local (lit la DB chiffrée, écrit un .db plain)\n"
            "railway ssh 'sqlite3 /app/data/agentys.db .dump' > /tmp/prod.sql\n"
            "sqlite3 /tmp/prod-baseline.db < /tmp/prod.sql\n"
            "python scripts/pipeline_baseline.py --db /tmp/prod-baseline.db --days 14\n"
            "```\n\n"
            "## Rappel — structure du rapport quand des données sont présentes\n\n"
            "Le rapport rendu contient 5 sections : Résumé exécutif, Distribution par modèle,\n"
            "Coûts mensuels projetés, Recommandation seuil initial `self_score`,\n"
            "Limites & instrumentation manquante.\n"
        )

    # Recommandation seuil
    rev_rate = metrics["critic_revision_rate"]
    if rev_rate < 0.10:
        seuil_reco = 75
        seuil_rationale = (
            "Le taux de révision actuel est faible (<10 %). Le Critic externe valide "
            "presque toujours V1. Le seuil 75 pour `self_score` reproduira ce comportement "
            "(escalade conservatrice ~25-30 %)."
        )
    elif rev_rate < 0.20:
        seuil_reco = 70
        seuil_rationale = (
            "Le taux de révision (10-20 %) suggère que le Critic attrape régulièrement "
            "des problèmes que les heuristiques laissent passer. Seuil 70 pour escalader "
            "un peu plus que le baseline et garder la qualité."
        )
    else:
        seuil_reco = 65
        seuil_rationale = (
            f"Le taux de révision est élevé ({rev_rate:.1%}). Soit le Critic est trop "
            "strict, soit le Drafter sous-performe. Seuil 65 pour escalader agressivement "
            "en attendant un audit qualitatif."
        )

    # Coûts projetés — basés sur le nombre de jours réellement actifs (≠ days),
    # sinon une période de inactivité partielle écraserait la projection.
    active_days = metrics.get("active_days", 0) or 1
    daily_cost = metrics["cost_total_usd"] / active_days
    monthly_cost = daily_cost * 30

    lines = []
    lines.append("# Pipeline draft baseline")
    lines.append("")
    lines.append(f"**Généré** : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Fenêtre** : {days} derniers jours ({metrics.get('active_days', 0)} jours actifs)")
    lines.append("**Source** : `draft_history` + `cost_tracking` (SQLCipher `agentys.db`)")
    lines.append("")
    lines.append("## Résumé exécutif")
    lines.append("")
    lines.append(f"- **Total drafts** : {total}")
    lines.append(f"- **Latence p50** : {metrics['latency_p50_ms']} ms")
    lines.append(f"- **Latence p95** : {metrics['latency_p95_ms']} ms")
    lines.append(f"- **Tokens moyen / draft** : {metrics['tokens_avg']}")
    lines.append(f"- **Critic gate skip rate** : {metrics['gate_skip_rate']:.1%} (heuristique actuelle)")
    lines.append(f"- **Critic revision rate** (parmi ceux qui passent le Critic) : {rev_rate:.1%}")
    lines.append(f"- **Score critique médian** : {metrics['critique_score_p50']} (p95 : {metrics['critique_score_p95']})")
    lines.append("")

    lines.append("## Distribution par modèle")
    lines.append("")
    lines.append("Le `tier` (SIMPLE/STANDARD/COMPLEX) n'est PAS persisté dans `draft_history`")
    lines.append("(uniquement loggé via `logger.info`). On utilise `model` comme proxy en attendant")
    lines.append("la Phase 1 qui ajoutera la colonne `tier`.")
    lines.append("")
    lines.append("| Modèle | Proxy tier | Count | Latence p50 (ms) |")
    lines.append("|---|---|---|---|")
    for model, bucket in sorted(metrics["by_model"].items(), key=lambda x: -x[1]["count"]):
        lines.append(
            f"| `{model}` | {bucket['proxy_tier']} | {bucket['count']} | {bucket['latency_p50_ms']} |"
        )
    lines.append("")

    lines.append("## Coûts mensuels projetés")
    lines.append("")
    lines.append(f"- **Coût total observé** ({days} jours, {metrics.get('active_days', 0)} actifs) : ${metrics['cost_total_usd']:.4f}")
    lines.append(f"- **Coût quotidien moyen** (sur jours actifs uniquement) : ${daily_cost:.4f}")
    lines.append(f"- **Projection mensuelle** (30 × coût/jour actif) : ${monthly_cost:.2f}")
    lines.append("")
    if metrics.get("active_days", 0) < days:
        lines.append(
            f"> ⚠️ Backend actif seulement {metrics.get('active_days', 0)}/{days} jours sur la fenêtre. "
            "La projection extrapole le rythme observé sur les jours actifs ; elle sur-estime "
            "si l'inactivité reflète une utilisation réelle (vacances, weekend, etc.)."
        )
        lines.append("")
    if metrics["cost_by_model"]:
        lines.append("**Coût par modèle :**")
        lines.append("")
        for model, cost in sorted(metrics["cost_by_model"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{model}` : ${cost:.4f}")
        lines.append("")

    lines.append("## Recommandation seuil initial self_score")
    lines.append("")
    lines.append(f"**Seuil retenu : {seuil_reco}**")
    lines.append("")
    lines.append(seuil_rationale)
    lines.append("")
    lines.append("Le seuil sera ajusté en semaine 2 du rollout (Phase 4) selon les métriques")
    lines.append("`would_escalate` vs `actual_critic_REJECT` mesurées par le sentinel L3.")
    lines.append("")

    lines.append("## Limites & instrumentation manquante")
    lines.append("")
    lines.append("- `tier` non persistant : seul le `model` est queryable. Phase 1 doit ajouter")
    lines.append("  une colonne `tier TEXT` à `draft_history` et la populer depuis `RoutingDecision.tier.value`.")
    lines.append("- `self_score` (output Phase 1) : prévoir une colonne `self_critique TEXT` (JSON)")
    lines.append("  pour stocker `{self_score, risks, a_confirmer_count, confidence}` au moment de l'insert.")
    lines.append("- Drafts hors `draft_history` (compose_email path direct Haiku) ne sont pas dans ce baseline")
    lines.append("  car `routes_misc.py:compose_email` ne persiste pas via le pipeline draft_history.")
    lines.append("  Ajouter cette persistance dès Phase 2 (DraftService unifié).")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DB I/O (not unit-tested; covered by smoke run in CI)
# ---------------------------------------------------------------------------

def _resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Prefer AGENTYS_DATA_DIR if set (matches infrastructure/database.py)
    data_dir = os.environ.get("AGENTYS_DATA_DIR")
    if data_dir:
        return (Path(data_dir).expanduser() / "agentys.db").resolve()
    return (Path.home() / ".agentys" / "data" / "agentys.db").resolve()


def _is_plain_sqlite(db_path: Path) -> bool:
    """Detect plain SQLite vs encrypted by inspecting the first 16 bytes.

    Plain SQLite header is the literal string 'SQLite format 3\\0'. SQLCipher
    encrypts the header too, so an encrypted DB starts with random bytes.
    Cheap, deterministic probe — no need to attempt opening the file.
    """
    try:
        with open(db_path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _open_db(db_path: Path):
    """Open the DB connection — plain SQLite if header matches, SQLCipher otherwise.

    Why this order: even when sqlcipher3 is installed (it is, in the prod
    requirements), local fixture copies are often plain SQLite. Probing the
    file header first avoids the lesson #4 trap (silent 'file is not a
    database' from mixing the two libs on the same path).
    """
    plain = _is_plain_sqlite(db_path)
    key = os.environ.get("AGENTYS_ENCRYPTION_KEY", "").strip()

    if plain:
        import sqlite3 as sqlite_mod  # type: ignore
        conn = sqlite_mod.connect(str(db_path))
    else:
        # Encrypted file — sqlcipher3 + key are mandatory
        try:
            import sqlcipher3 as sqlite_mod  # type: ignore
        except ImportError:
            print(
                f"[FATAL] {db_path} appears encrypted but sqlcipher3 is not installed. "
                "Install with `pip install sqlcipher3-binary`.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not key:
            # Strict fail-closed (lesson #7)
            print(
                "[FATAL] Encrypted DB but AGENTYS_ENCRYPTION_KEY is empty. "
                "Export the key or pass --db to a plaintext fixture copy.",
                file=sys.stderr,
            )
            sys.exit(1)
        # SQLCipher accepts only PRAGMA-style key passing (no `?` parameter
        # binding for PRAGMAs). Validate the key is exactly 64 hex chars to
        # rule out injection of arbitrary SQL via crafted env var.
        if not _HEX_KEY_RE.fullmatch(key):
            print(
                "[FATAL] AGENTYS_ENCRYPTION_KEY must be exactly 64 hex characters "
                "(32 raw bytes). Refusing to open the DB.",
                file=sys.stderr,
            )
            sys.exit(1)
        conn = sqlite_mod.connect(str(db_path))
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
        conn.execute("PRAGMA cipher_page_size = 4096")
        conn.execute("PRAGMA kdf_iter = 256000")
        conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
        conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")

    conn.row_factory = sqlite_mod.Row
    # Probe — fails fast on wrong key / corrupt file
    conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    return conn


def fetch_rows(conn, days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT id, account_id, email_id, email_sender, email_subject,
               status, model, processing_time_ms, tokens_used,
               critique, draft_v1, draft_final, created_at
        FROM draft_history
        WHERE created_at >= ?
        ORDER BY created_at DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_cost_rows(conn, days: int) -> list[dict]:
    """Fetch cost_tracking rows. Degrades gracefully if the table is absent
    (older DBs) — but louder errors (corruption, schema drift) are surfaced."""
    import sqlite3 as _stdlib_sqlite
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        rows = conn.execute(
            """
            SELECT date, model, input_tokens, output_tokens, cost_usd, request_count
            FROM cost_tracking
            WHERE date >= ?
            ORDER BY date DESC
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except _stdlib_sqlite.OperationalError as e:
        # Missing table or column — expected on older DBs, degrade silently
        # but tag the warning so it's visible in CI logs.
        msg = str(e).lower()
        if "no such table" in msg or "no such column" in msg:
            print(f"[WARN] cost_tracking unavailable: {e}", file=sys.stderr)
            return []
        raise  # Real DB error (corruption, locked) — surface it


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline draft baseline (Phase 0)")
    parser.add_argument("--db", help="Path to agentys.db (default: ~/.agentys/data/agentys.db)")
    parser.add_argument("--days", type=int, default=14, help="Window in days (default: 14)")
    parser.add_argument(
        "--out",
        default="tasks/pipeline-baseline-2026-04-30.md",
        help="Output markdown path (default: tasks/pipeline-baseline-2026-04-30.md)",
    )
    args = parser.parse_args(argv)

    db_path = _resolve_db_path(args.db)
    if not db_path.exists():
        print(f"[FATAL] Database not found: {db_path}", file=sys.stderr)
        return 2

    try:
        conn = _open_db(db_path)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[FATAL] Cannot open DB ({db_path}): {e}", file=sys.stderr)
        return 2

    try:
        rows = fetch_rows(conn, args.days)
        cost_rows = fetch_cost_rows(conn, args.days)
    finally:
        conn.close()

    metrics = aggregate_metrics(rows, cost_rows)
    md = render_markdown(metrics, days=args.days)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    print(f"[OK] Baseline écrit dans {out_path}")
    print(f"     {metrics['total_drafts']} drafts analysés sur {args.days} jours "
          f"({metrics.get('active_days', 0)} jours actifs)")
    print(f"     gate_skip_rate={metrics['gate_skip_rate']:.1%}, "
          f"critic_revision_rate={metrics['critic_revision_rate']:.1%}")
    print(f"     coût total observé : ${metrics['cost_total_usd']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
