"""Run espion_recap synchrone et poste le compte-rendu final dans Telegram.

Conçu pour être exécuté dans le container agentys-pm :
    docker exec -d agentys-pm python /tmp/espion_recap_telegram.py

Reproduit la logique de cmd_espion_recap (cf. ai_team/lib/telegram.py) côté
CLI : run_recap(wait_for_forums=True) + summary text + pm_telegram.send.
"""

from __future__ import annotations

import asyncio
import sys

from ai_team.agents.pm import espion_recap
from ai_team.lib import telegram as pm_telegram


def build_summary_text(metrics: dict) -> str:
    status = metrics.get("status", "?")
    if status == "no_history":
        return (
            f"📚 *Récap Espion* — aucun signal historique trouvé "
            f"sur les {metrics.get('days_back')} derniers jours."
        )
    if status == "synthesis_failed":
        return (
            "❌ *Récap Espion — synthèse échouée*\n\n"
            "Sonnet n'a pas produit de JSON exploitable. Vérifie les logs."
        )
    if status != "success":
        return f"⚠️ *Récap Espion — status inattendu* : `{status}`"

    summary = metrics.get("synthesis_summary") or "_(pas de résumé)_"
    verdicts = metrics.get("feature_verdicts") or []
    approved = [v for v in verdicts if v.get("status") == "forum_approved"]
    long_term = [v for v in verdicts if v.get("status") == "forum_approved_long_term"]
    rejected = [v for v in verdicts if v.get("status") == "forum_rejected"]

    lines = [
        f"✅ *Récap Espion terminé* `{metrics.get('recap_id')}`",
        "",
        "📊 *Métriques :*",
        f"  • {metrics.get('signals_count')} signaux ingérés "
        f"({metrics.get('issues_count')} issues GH)",
        f"  • {metrics.get('features_routed')} features votées par le forum",
        f"  • {metrics.get('marketing_routed')} points marketing → dossier",
        "",
    ]

    def _entry_line(v):
        title = v.get("title", "?")[:80]
        comp = v.get("competitor", "—")
        freq = v.get("frequency", "?")
        extra = []
        if comp and comp != "—":
            extra.append(comp)
        if freq and freq != "?":
            extra.append(f"{freq}×")
        suffix = f" _({' · '.join(extra)})_" if extra else ""
        return f"  • {title}{suffix}"

    if approved:
        lines.append(f"✅ *APPROVED ({len(approved)})* — `/features` pour valider :")
        lines.extend(_entry_line(v) for v in approved)
        lines.append("")
    if long_term:
        lines.append(f"📚 *LONG-TERM RFC ({len(long_term)})* — `/features_long_term` :")
        lines.extend(_entry_line(v) for v in long_term)
        lines.append("")
    if rejected:
        lines.append(f"❌ *REJECTED ({len(rejected)})* :")
        for v in rejected:
            lines.append(f"  • {v.get('title', '?')[:80]}")
        lines.append("")

    lines.append(f"*Tendances observées :*\n_{summary}_")
    lines.append("")
    lines.append(
        f"📋 `/concurrence` pour le dossier marketing/pricing "
        f"({metrics.get('marketing_routed', 0)} entrées)"
    )
    return "\n".join(lines)


def main() -> int:
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    print(f"[recap-cli] starting run_recap(days_back={days_back}, wait_for_forums=True)",
          flush=True)
    metrics = espion_recap.run_recap(
        days_back=days_back,
        dispatched_by="cli-deploy-2026-05-01",
        wait_for_forums=True,
    )
    print(
        f"[recap-cli] done : status={metrics.get('status')}, "
        f"features_routed={metrics.get('features_routed')}, "
        f"marketing_routed={metrics.get('marketing_routed')}, "
        f"verdicts_count={len(metrics.get('feature_verdicts') or [])}",
        flush=True,
    )

    text = build_summary_text(metrics)
    print(f"[recap-cli] posting summary ({len(text)} chars) to Telegram alerts topic",
          flush=True)
    asyncio.run(pm_telegram.send(text, topic="alerts"))
    print("[recap-cli] summary posted", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
