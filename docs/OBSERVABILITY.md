# Observability — boucle de feedback à 4 couches

Guide de référence pour comprendre **où placer un test**, **quel type de signal il produit**, et **combien ça coûte**.

Agentys mélange Python, crons autonomes, LLMs, infra Hetzner/Railway. Une seule stratégie de tests ne suffit pas — chaque type d'erreur échappe à une autre.

## Vue d'ensemble

| Couche | Outil | Où ça tourne | Cadence | Ce qui triche pas là-bas | Coût |
|---|---|---|---|---|---|
| **L1** Unit tests | `pytest` | CI + dev local | À chaque push | Logique pure, branches | $0 |
| **L2** Integration tests | `pytest` + fixtures | CI + dev local | À chaque push | Branchement des composants, schémas DB | $0 |
| **L3** Sentinelles | Python + APScheduler | Hetzner/Railway (live) | Min à hebdo | État réel de l'infra, drift production | $0 |
| **L4** LLM-as-judge | `claude -p` | Hetzner (live) | Quotidien | Taste, cohérence sémantique, drift qualitatif | ~$0.15/mois par sentinelle |

Les 4 couches sont **complémentaires, pas redondantes**. Chacune attrape un type d'erreur que la précédente ne voit pas.

---

## L1 — Unit tests : « ma fonction fait ce que je pense »

**Définition** : tester une fonction pure, isolée, avec inputs/outputs déterministes. Pas d'I/O réel (filesystem, réseau, DB). Mocker tout ce qui dépasse la fonction testée.

**Exemple** ([`tests/ai_team/test_sentinel_standup.py`](../tests/ai_team/test_sentinel_standup.py)) :

```python
def test_counts_distinct_personas():
    transcript = "**PM** : hi\n**pm** : bye\n**Alice** : yo"
    count, _ = _parse_transcript(transcript)
    assert count == 2  # PM (case-folded) + Alice
```

**Ce qu'il voit** : bug dans une regex, edge case oublié, comportement incorrect d'une branche if.

**Ce qu'il ne voit pas** : la fonction est-elle bien **appelée** dans le vrai pipeline ? Le schéma DB réel est-il cohérent ?

**Quand en ajouter** :
- Chaque nouvelle fonction pure (transformation de données, parsing)
- Chaque bug fix (test de régression qui reproduit le bug d'abord)
- Avant refactor (pour geler le contrat avant de refactorer)

---

## L2 — Integration tests : « mes morceaux branchés ensemble font le job »

**Définition** : orchestrer plusieurs unités ensemble avec des fixtures réelles (DB tmp, filesystem tmp) mais stubber les appels externes non déterministes (LLM, Telegram, GitHub API).

**Exemple** ([`tests/ai_team/test_sentinel_standup.py::TestCheckDate`](../tests/ai_team/test_sentinel_standup.py)) :

```python
def test_l4_drop_triggers_alert(tmp_path):
    # Seed une VRAIE SQLite avec 3 jours de scores élevés → median=85
    seed_quality_db(tmp_path / "q.db", [("2026-04-18", 85), ...])
    # Crée un vrai fichier transcript sur filesystem tmp
    (tmp_path / "2026-04-19.md").write_text(GOOD_TRANSCRIPT)
    # Stub uniquement le LLM (non déterministe)
    with patch("_l4_judge", return_value=({"overall": 52}, "")):
        result = check_date("2026-04-19", standups_dir=tmp_path, ...)
    assert result.l4_drop_vs_median >= 16  # drop 85→52 = 33pt
```

**Ce qu'il voit** : mauvais branchement entre modules, schéma DB incohérent, erreur d'injection de dépendance, ordre d'exécution fautif.

**Ce qu'il ne voit pas** : le cron ne fire pas parce que `APScheduler` n'a pas été redémarré ; la prod a une config env différente ; Telegram n'est pas configuré sur cette machine.

**Quand en ajouter** :
- Pipeline de plusieurs étapes (extract → transform → load)
- Use case avec DI complexe
- Flow qui lit ET écrit sur la même ressource (détecte les races)

---

## L3 — Sentinelles : « le système en prod fait réellement ce qu'il doit »

**Définition** : un processus tourne en prod sur l'infra réelle, à cadence fixe, et vérifie l'état observable du système. Pas de stub, pas de tmp — vraie DB, vrai filesystem, vrai Telegram.

**Exemple** ([`ai_team/agents/cron/sentinel_standup.py`](../ai_team/agents/cron/sentinel_standup.py)) :

```python
def run() -> None:
    # Tourne chaque jour 09:00 UTC via APScheduler sur Hetzner
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    result = check_date(yesterday.strftime("%Y-%m-%d"))
    # → lit le VRAI filesystem, insère dans la VRAIE DB,
    #   envoie un VRAI message Telegram si anomalie
```

**Ce qu'il voit** : cron qui ne fire pas, DB indisponible, régression que les tests locaux ne reproduisent pas, bug de config Hetzner, dérive d'état entre redéploiements.

**Ce qu'il ne voit pas** : la qualité littéraire du transcript (c'est L4) ; une dégradation lente de la pertinence sémantique.

**Pattern standard d'une sentinelle** :
1. Fetch l'état live (fichier existe ? row DB présente ? API répond ?)
2. Compare à un seuil ou à l'historique récent
3. Log dans `agent_actions` (audit)
4. Si anomalie → Telegram avec dédup Redis (24h ou 7j TTL)

**Quand en ajouter** :
- Nouveau pipeline user-facing ou financier (drafting, paiement, emails)
- Nouvelle intégration tierce (nouvel API provider)
- Après un incident prod (sentinelle dédiée au type de drift observé)

---

## L4 — LLM-as-judge : « la qualité est-elle bonne aujourd'hui ? »

**Définition** : un LLM (Haiku en général) lit un output produit par le système et **le note qualitativement** sur des axes où aucune règle déterministe ne peut trancher.

**Exemple** ([`ai_team/agents/cron/sentinel_standup.py::_l4_judge`](../ai_team/agents/cron/sentinel_standup.py)) :

Haiku reçoit le transcript du daily standup et renvoie :
```json
{
  "humour": 82,
  "personas": 78,
  "safeguards": 95,
  "alpha_idiot": 85,
  "overall": 82,
  "comment": "alpha-idiot digresse bien, security reste parano cohérent"
}
```

Le sentinel compare `overall` à la médiane 7j → alerte si drop > 15pt.

**Ce qu'il voit** : dérive qualitative (alpha-idiot qui devient plat, safeguards respectés mais personas confondues, ton qui glisse vers générique), régression sémantique post-mise à jour de prompt.

**Ce qu'il ne voit pas** : bug mécanique (fichier manquant → L3), erreur de logique (regex cassée → L1).

**Pattern standard d'un judge** :
1. Prompt système strict : *« tu es juge, scores 0-100 sur ces axes précis, sortie JSON uniquement »*
2. Utilise [`ai_team/lib/llm_judge.py`](../ai_team/lib/llm_judge.py) → fallback cascade JSON parsing, `required_keys` enforcement, `max_budget_usd` hardcap
3. Persiste les scores (table dédiée style `standup_quality`)
4. Alerte sur drift vs médiane N-jours, pas sur score absolu
5. **Haiku > Sonnet** pour les judges : précision ordinale suffisante à 0.005 $/call vs 0.03 $/call

**Pièges connus** :
- Un judge trop verbeux → JSON parsing fragile → faux négatifs. Contre-mesure : `required_keys` obligatoires.
- Un prompt système trop ouvert → drift du juge lui-même dans le temps. Contre-mesure : geler le prompt en `.md` committé, pas modifiable à la volée.
- Un LLM qui refuse de juger ses propres outputs → préférer une instance différente (Haiku juge Sonnet, ou l'inverse).

**Quand en ajouter** :
- Contenu user-facing généré par LLM (emails, articles, réponses support)
- Agents "créatifs" (muse, journaliste, espion) où le déterminisme n'existe pas
- Après avoir décidé ce que "bon" signifie sur 3-5 axes explicites

---

## Matrice de décision : quelle couche pour quel signal ?

| Type d'erreur | Détecté par |
|---|---|
| Regex qui matche mal | L1 |
| Fonction appelée avec mauvais arguments | L1 ou L2 |
| Schéma DB incohérent avec le code | L2 |
| Race condition sur une ressource partagée | L2 (si reproductible) |
| Cron qui ne fire pas | L3 |
| Provider API qui rate-limit | L3 |
| Config env différente en prod | L3 |
| Qualité de contenu en baisse | **L4 uniquement** |
| Agent qui perd son persona | **L4 uniquement** |
| Drift lent sur 2 semaines | **L4 uniquement** |

**Règle d'or** : si L1-L3 verts pendant 1 mois et le produit se dégrade → il manque L4.

---

## Coûts typiques

| Couche | Coût par run | Coût mensuel | Volume typique |
|---|---|---|---|
| L1 | $0 | $0 | 100-500 assertions/push CI |
| L2 | $0 | $0 | 20-50 tests d'intégration/push |
| L3 | $0 | $0 (compute PM déjà payé) | 1 run toutes les 5min à hebdo |
| L4 | ~$0.005/call | ~$0.15/mois par sentinelle quotidienne | 1 call/jour |

Une stack complète des 4 couches pour 1 pipeline coûte **< $1/mois**.

---

## Sentinelles déployées aujourd'hui

Voir [`ai_team/agents/cron/README.md`](../ai_team/agents/cron/README.md) pour la liste à jour et le schedule exact.

| Sentinelle | Cadence | Couches | Protège |
|---|---|---|---|
| `sentinel_standup` | daily 09:00 UTC | L3 + L4 | Daily standup #262 |
| `sentinel_drift` | dimanche 20:00 UTC | L3 (pur AST + Levenshtein) | Migration prompts #261 Phase 2 |

À venir (cf. [issue #289](https://github.com/nathan/agentys/issues/289)) :
- `sentinel_cost` — anomaly detection sur la consommation par clé Anthropic
- `sentinel_drafter_quality` — shadow mode old vs new Drafter avec LLM-judge quotidien (prérequis pour migration #261 Partie D)

---

## Ajouter un nouveau sentinel — template

```python
# ai_team/agents/cron/sentinel_<domain>.py
from __future__ import annotations
import logging
from dataclasses import dataclass

log = logging.getLogger("ai_team.sentinel_<domain>")

@dataclass(frozen=True)
class <Domain>Check:
    # champs résultat
    ...

def check_target(target_id: str, *, ...) -> <Domain>Check:
    """Pure function — L1/L2 testable sans I/O."""
    ...

def run() -> None:
    """Cron entry — appelée par APScheduler via cron.yaml."""
    result = check_target(...)

    # L3 → Audit
    try:
        from ai_team.lib.audit import Audit
        Audit().log_action("sentinel-<domain>", "check", "t1",
                           result="success" if not result.alerts else "error",
                           metadata=result.to_dict())
    except Exception as e:  # noqa: BLE001
        log.warning("audit failed: %s", e)

    # L3 → Telegram (avec cooldown Redis)
    if result.alerts:
        _send_alert_with_cooldown(...)

    # L4 (optionnel) → LLM judge
    if result.ready_for_judge:
        from ai_team.lib.llm_judge import judge
        scores = judge(system=..., user=..., required_keys=(...))
        # persist + compare to median
```

Puis ajouter l'entrée dans `ai_team/config/cron.yaml` :

```yaml
  - name: sentinel_<domain>
    enabled: true
    agent: sentinel-<domain>
    function: ai_team.agents.cron.sentinel_<domain>:run
    trigger: cron
    schedule:
      hour: N
      minute: 0
```

Redémarrer le PM : `systemctl restart ai_team_pm` (Hetzner) ou relancer `python -m ai_team.agents.pm` (dev).

---

## Références

- Issue fondatrice : [#289](https://github.com/nathan/agentys/issues/289) — Feedback loop IA : 4 couches tests + 3 sentinelles
- Architecture cron : [`ai_team/agents/cron/README.md`](../ai_team/agents/cron/README.md)
- Helper LLM-judge : [`ai_team/lib/llm_judge.py`](../ai_team/lib/llm_judge.py)
- Audit DB schema : [`ai_team/lib/audit.py`](../ai_team/lib/audit.py)
