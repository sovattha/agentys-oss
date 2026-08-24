# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Driver one-shot pour valider le pipeline espion_recap localement.

Usage : python scripts/espion_recap_dry_run.py [days_back]

Fetch GH → synthèse Sonnet → pour chaque feature : feature_board.propose +
forum Opus SYNCHRONE (pas de thread daemon — on attend le verdict). Pour chaque
marketing point : competitor_dossier.add_entry. Reporting console.

Coût estimé : ~$0.10 Sonnet + 5-10 forums Opus × $0.50 = $2-5.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure project root is on PYTHONPATH so `import ai_team` works.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if k.strip() and v and k.strip() not in os.environ:
            os.environ[k.strip()] = v


def _get_gh_token() -> str | None:
    try:
        out = subprocess.check_output(["gh", "auth", "token"], text=True, timeout=5)
        return out.strip() or None
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] gh auth token failed: {e}")
        return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    _load_env_file(repo_root / ".env")

    if "GITHUB_TOKEN" not in os.environ:
        token = _get_gh_token()
        if token:
            os.environ["GITHUB_TOKEN"] = token
            print("[OK] GITHUB_TOKEN injected from gh CLI")
        else:
            print("[FAIL] GITHUB_TOKEN missing and gh CLI unavailable")
            return 1
    os.environ.setdefault("GITHUB_OWNER", "nathan")
    os.environ.setdefault("GITHUB_REPO", "agentys")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[FAIL] ANTHROPIC_API_KEY missing")
        return 1

    # DB locale temporaire — on ne pollue pas la prod, et le conftest ne
    # s'applique pas aux scripts CLI.
    tmpdir = Path(tempfile.mkdtemp(prefix="espion_recap_dryrun_"))
    db_path = tmpdir / "ai_team_dryrun.db"
    os.environ["AGENTYS_DB_PATH"] = str(db_path)
    print(f"[OK] Using temp DB: {db_path}")

    # Apply migration 001 (agent_actions schema needed by audit logs).
    import sqlite3
    migration = repo_root / "ai_team" / "migrations" / "001_ai_team_tables.sql"
    if migration.exists():
        sql = migration.read_text(encoding="utf-8")
        con = sqlite3.connect(str(db_path), timeout=10)
        try:
            con.executescript(sql)
            con.commit()
        finally:
            con.close()
        print("[OK] migration 001_ai_team_tables.sql applied")

    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 90

    # ---------- Étape 1 : fetch GH ----------
    print(f"\n{'='*72}\n  Étape 1 : fetch issues GH (last {days_back}d)\n{'='*72}")
    from ai_team.agents.pm.espion_recap import (
        fetch_historical_signals,
        synthesize_strategic_recap,
    )
    signals, issue_numbers = fetch_historical_signals(days_back=days_back)
    print(f"  → {len(signals)} signaux ingérés depuis {len(issue_numbers)} issues GH")
    if not signals:
        print("[STOP] Aucun signal historique → rien à synthétiser")
        return 0
    print(f"  Issues consommées : {issue_numbers}")
    # Aperçu
    print("\n  Aperçu (5 premiers signaux) :")
    for s in signals[:5]:
        print(f"    [{s.get('severity'):>8}] {s.get('competitor', '?'):>15}  {s.get('title', '?')[:80]}")

    # ---------- Étape 2 : synthèse Sonnet ----------
    print(f"\n{'='*72}\n  Étape 2 : synthèse Sonnet 4.6\n{'='*72}")
    recap = synthesize_strategic_recap(signals)
    if not recap:
        print("[FAIL] Sonnet synthesis returned None — aborting")
        return 1

    summary = recap.get("summary", "")
    features = recap.get("features_to_investigate") or []
    marketing = recap.get("marketing_points") or []
    print(f"  Tendances : {summary}")
    print(f"  → {len(features)} features stratégiques + {len(marketing)} points marketing")

    print("\n  Features candidats :")
    for i, f in enumerate(features, 1):
        print(f"    {i}. [{f.get('competitor', '?')}] freq={f.get('frequency', '?')} — {f.get('title', '?')}")

    print("\n  Marketing/pricing candidats :")
    for i, m in enumerate(marketing, 1):
        print(f"    {i}. [{m.get('axis', '?')} {m.get('severity', '?')}] {m.get('competitor', '?')} — {m.get('title', '?')}")

    # ---------- Étape 3 : routing dossier marketing ----------
    print(f"\n{'='*72}\n  Étape 3 : routing competitor_dossier\n{'='*72}")
    from ai_team.agents.pm import competitor_dossier
    dossier_added = 0
    for m in marketing:
        if not isinstance(m, dict):
            continue
        title = str(m.get("title", "")).strip()
        body = str(m.get("body", "")).strip()
        axis = str(m.get("axis", "")).lower()
        sev = str(m.get("severity", "medium")).lower()
        if axis not in competitor_dossier.VALID_AXES:
            print(f"  [SKIP] axis invalide '{axis}' pour {title!r}")
            continue
        if sev not in competitor_dossier.VALID_SEVERITIES:
            sev = "medium"
        try:
            entry_id = competitor_dossier.add_entry(
                competitor=str(m.get("competitor") or "—"),
                axis=axis, severity=sev,
                title=title, body=body,
                source="espion-recap dry-run",
                citation=str(m.get("recommended_action") or "")[:200] or None,
                metadata={"recap_origin": True, "dry_run": True},
                dedup_hours=0,
            )
            if entry_id:
                dossier_added += 1
                print(f"  [OK] {entry_id} : {title[:60]}")
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR] {title[:60]} : {e}")
    print(f"  → {dossier_added} entrées ajoutées au dossier")

    # ---------- Étape 4 : forums Opus SYNCHRONES ----------
    print(f"\n{'='*72}\n  Étape 4 : forums Opus 4.7 (5 personas, STRICT 3/5)\n{'='*72}")
    from ai_team.agents.pm import feature_board
    verdicts: list[dict] = []
    for i, feat in enumerate(features, 1):
        if not isinstance(feat, dict):
            continue
        title = str(feat.get("title", "")).strip()
        body = str(feat.get("body", "")).strip()
        action = str(feat.get("recommended_action", "")).strip()
        competitor = str(feat.get("competitor") or "—")
        frequency = int(feat.get("frequency") or 0)
        if not title:
            continue

        description = (
            f"{body}\n\n"
            f"**Action recommandée** : {action or '—'}\n"
            f"**Concurrent observé** : {competitor}\n"
            f"**Fréquence historique** : {frequency} signal(aux)"
        )
        feat_id = feature_board.propose(
            source="espion-recap-dryrun",
            title=title,
            description=description,
            metadata={"competitor": competitor, "frequency": frequency,
                      "dry_run": True},
        )

        print(f"\n  [{i}/{len(features)}] Forum sur '{title[:60]}' (feat_id={feat_id})")
        print(f"        Concurrent: {competitor} · Fréquence: {frequency}")
        try:
            forum_id = feature_board.open_feature_forum_sync(
                feat_id, notify_telegram=False,  # pas de Telegram en dry-run
            )
        except Exception as e:  # noqa: BLE001
            print(f"        [FAIL] forum crashed : {e}")
            verdicts.append({"feat_id": feat_id, "title": title,
                             "outcome": "error", "error": str(e)})
            continue

        feat_after = feature_board.get(feat_id)
        if not feat_after:
            print("        [FAIL] feat disappeared after forum")
            continue

        verdict = {
            "feat_id": feat_id,
            "title": title,
            "competitor": competitor,
            "frequency": frequency,
            "forum_id": forum_id,
            "status": feat_after.status,
            "votes": feat_after.votes,
        }
        verdicts.append(verdict)

        # Affichage immédiat
        approve_count = sum(1 for v in feat_after.votes if v.get("vote") == "approve")
        reject_count = sum(1 for v in feat_after.votes if v.get("vote") == "reject")
        abstain_count = sum(1 for v in feat_after.votes if v.get("vote") == "abstain")
        outcome_emoji = {"forum_approved": "✓ APPROVED",
                        "forum_rejected": "✗ REJECTED"}.get(feat_after.status, "?")
        print(f"        VERDICT : {outcome_emoji}  ({approve_count}A / {reject_count}R / {abstain_count}Abs)")
        for v in feat_after.votes:
            voter = v.get("voter", "?")
            vote_emoji = {"approve": "✓", "reject": "✗", "abstain": "⊘"}.get(
                v.get("vote", ""), "•",
            )
            rationale = (v.get("rationale") or "").strip()[:90]
            print(f"          {vote_emoji} {voter:<12} — {rationale}")

    # ---------- Étape 5 : récap final ----------
    print(f"\n{'='*72}\n  RÉCAP FINAL\n{'='*72}")
    approved = [v for v in verdicts if v.get("status") == "forum_approved"]
    rejected = [v for v in verdicts if v.get("status") == "forum_rejected"]
    print(f"  Total features candidates : {len(features)}")
    print(f"  Approuvées par le forum   : {len(approved)}")
    print(f"  Rejetées par le forum     : {len(rejected)}")
    print(f"  Marketing/pricing dossier : {dossier_added}")

    if approved:
        print("\n  ✅ FEATURES APPROUVÉES (à investiguer en priorité) :")
        for v in approved:
            print(f"    • {v['title']}")
            print(f"      _concurrent: {v['competitor']}, fréquence: {v['frequency']}_")

    if rejected:
        print("\n  ❌ FEATURES REJETÉES par le forum :")
        for v in rejected:
            print(f"    • {v['title']}")
            print(f"      _concurrent: {v['competitor']}, fréquence: {v['frequency']}_")

    print(f"\n  Tendances Sonnet : {summary}")
    print(f"\n[DONE] DB temp : {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
