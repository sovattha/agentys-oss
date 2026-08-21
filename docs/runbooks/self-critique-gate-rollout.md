# Runbook — SelfCritique Gate rollout (`off` → `shadow` → `active`)

> **⚠️ DÉPRÉCIÉ 2026-05-04 — gate retiré du codebase.**
>
> Le gate SelfCritique a été supprimé de `DraftOrchestrator` après que la
> refonte du Critic le 2026-05-04 (placeholder hard-rule + décision
> déterministe en code + 5 exemples calibrés en few-shot) a fait passer
> le FP rate de 31 % → 9 % (effectif 2.2 % sur cas labellisés cohéremment,
> cf. `tasks/critic-vs-ground-truth-2026-05-04.md`). La raison d'être du
> gate (rescuer les FP du Critic) a disparu — le gate aurait skippé
> 25 % des drafts pour économiser ~9 cas Critic/200, ratio
> coût-de-maintenance / valeur trop faible pour le garder.
>
> **Code retiré** : ~150 lignes dans `app/services/draft_orchestrator.py`
> (constantes `_GATE_*`, `_read_gate_mode`, `_gate_should_skip_critic`,
> `_build_synthetic_valid_critique`, `_evaluate_with_shadow_gate`,
> `_maybe_skip_critic_via_gate`, `_emit_orchestration_summary`),
> `tests/services/test_draft_orchestrator_self_critique_gate.py`,
> `ai_team/agents/cron/sentinel_self_critique_gate.py`,
> `tests/ai_team/test_sentinel_self_critique_gate.py`.
>
> **Conservé pour usage compose-only** : `app/self_critique_agent.py`,
> `app/domain/entities/self_critique.py`, et l'usage shadow dans
> `app/application/services/_compose_path.py` — la compose path n'a
> pas de Critic externe et utilise SelfCritique en mode purement
> informatif (pipeline_info), donc cette infrastructure reste utile.
>
> **Env var Railway** : `AGENTYS_SELF_CRITIQUE_GATE` à supprimer après
> deploy de ce commit (`railway variables --remove AGENTYS_SELF_CRITIQUE_GATE`)
> — le code ne la lit plus, elle ne fait plus rien.
>
> **Rollback** : si jamais le Critic devait régresser et le gate redevenait
> nécessaire, `git revert` du commit de suppression suffit. Tout le pattern
> (env var 3-mode, sentinel, runbook) est dans l'historique.
>
> Le runbook ci-dessous est conservé pour traçabilité historique de la
> décision et du raisonnement — il ne décrit PLUS le comportement actuel
> du système.

---

## Pourquoi (historique)

L'orchestrateur draft (`app/services/draft_orchestrator.py`) a un gate optionnel qui réduit le coût + la latence sur les drafts confiants. L'eval synthétique 200 cas (`tasks/eval-self-critique-vs-critic-summary-2026-04-30.md`) montre 0% faux positifs vs 34% pour le Critic.

**MAJ 2026-05-04 — règle assouplie via le sweep `tasks/eval-gate-rule-sweep-2026-05-04.md`** :
- Avant : `score>=85, risks==(), a_confirmer==0, conf=='high'` → 5 % skip rate sur l'eval (replay au runbook initial : `tasks/eval-deployed-gate-verdict-2026-05-03.md`).
- Maintenant : `score>=85, risks ⊆ {filler}, a_confirmer==0, conf=='high'` → **25 % skip rate** sur la même eval, **0 cas dangereux non-`good`**.
- Score-threshold relaxation (75 vs 85) et confidence-relaxation (med vs high) n'apportent rien sur ce dataset (SelfCritique sort `good` drafts à 88+ et conf=high systématiquement). Le seul levier qui débloque le skip rate est l'allow-list `filler`.

**Effet immédiat de chaque mode** (chiffres CALIBRÉS sur le replay live, pas le synthétique) :

| Mode | Comportement | Coût/draft moyen | Latence/draft moyenne |
|---|---|---|---|
| `off` (défaut) | SelfCritique ne tourne jamais. Critic systématique. | baseline | baseline |
| `shadow` (depuis #async, 2026-05-03) | SelfCritique ET Critic en **parallèle**. Décisions loggées. | **+$0.0001** (gate seul, ~free) | **+0ms** (parallèle, max(gate, critic) = critic) |
| `active` | SelfCritique séquentiel, Critic skippé sur les 5% confiants. | gate ajoute $0.0001/draft, économise $0.0015/draft × 5% skip = **−$0.00007/draft net** (~−5%) | gate ajoute ~400ms/draft, économise ~1500ms × 5% skip = **+325ms/draft net** |

**Caveats à comprendre AVANT de promouvoir vers `active`** :

1. **Les chiffres "−25-29% coût / −40% latence" du runbook initial sont CONDITIONNELS au sous-ensemble qui skip (5% des drafts), pas au draft moyen.** En valeur moyenne, `active` est légèrement plus cher en latence et marginalement plus économe en coût.

2. **Couverture du rubric SelfCritique : 5 catégories** (hallucination, placeholder, tone_mismatch, off_topic, filler). Le Critic structuré + post-processing pipeline en vérifie ~50 (langue, longueur, signature double, KB-grounded facts, sender misdirection, social engineering, hedging, etc.). Quand le gate dit "no risks, score 92" il a vérifié **~10% de ce que le Critic vérifie**. Voir `tasks/eval-deployed-gate-verdict-2026-05-03.md` pour le détail.

3. **Validation sans ground-truth** : le sentinel mesure "agreement gate-vs-Critic", pas "gate-vs-vérité". Le Critic a lui-même 34% de faux-positifs. Pour valider correctement, il faut un set de 50-100 drafts hand-labellés (TODO § "Ground truth set").

4. **Caching prompt-Critic est déjà câblé** (`app/adapters/llm/claude_adapter.py:138`) avec `cache_control: ephemeral`. Si le prefix dépasse 1024 tokens et qu'on reste sous le TTL 5min, l'input cost du Critic chute de ~90%. Si effective, ça grignote la valeur du gate. Audit séparé requis (roadmap #2).

## Pré-requis avant de flipper

- [ ] Sentinel `sentinel_self_critique_gate` déployé sur Hetzner (cron daily 09:00 Paris)
- [ ] Backend Railway écrit les `[ORCHESTRATION_SUMMARY] {json}` lines dans le fichier que le sentinel lit (cf. § "Acquisition des logs" plus bas)
- [ ] Tests verts : `pytest tests/services/test_draft_orchestrator_self_critique_gate.py tests/ai_team/test_sentinel_self_critique_gate.py`

## Étape 1 — Flip en `shadow` (semaine 1)

```bash
# Sur ton macOS box (railway CLI installé)
railway variables --set AGENTYS_SELF_CRITIQUE_GATE=shadow --service backend
# Le redéploiement est automatique, ~30s
```

**Coût additionnel** : ~$0.0005/draft × ~600 drafts/jour ≈ **$0.30/mois** pendant la phase shadow. Trivial.

**Attendre** : minimum 7 jours pour accumuler ≥ 50 décisions comparables (gate ran ∧ critic ran).

**Vérifier les premiers logs après 1h** :
```bash
railway logs --service backend | grep ORCHESTRATION_SUMMARY | tail -10
```
Tu devrais voir des lignes JSON avec `"gate_mode": "shadow"`, `"gate_ran": true`, `"critic_source": "critic_agent"`.

## Étape 2 — Lecture du sentinel (vérification quotidienne)

Le sentinel tourne automatiquement à 09:00 Paris et alerte via Telegram si :
- **FP rate > 5%** sur ≥ 50 décisions, OU
- **Agreement rate < 90%** sur ≥ 50 décisions

**Lecture manuelle** :
```bash
# Sur Hetzner
ssh agentys@65.109.150.123
docker exec agentys-pm python -m ai_team.agents.cron.sentinel_self_critique_gate
# Cherche dans la sortie : "comparable_decisions=N, FP X.X%, agreement Y.Y%"
```

**Critères pour aller en `active`** :
- `comparable_decisions >= 200` (échantillon stat. fiable)
- `false_positive_rate <= 2%` (objectif rigoureux ; le seuil d'alerte est 5%)
- `agreement_rate >= 95%` (objectif rigoureux ; le seuil d'alerte est 90%)
- Aucune alerte Telegram pendant ≥ 5 jours consécutifs

Si l'un ne tient pas → analyser les FP samples (`samples_fp` dans le log audit) et **tuner les thresholds** dans `app/services/draft_orchestrator.py:72-73` :
- `_GATE_MIN_SELF_SCORE = 85` (augmenter à 90 rend le gate plus prudent)
- `_GATE_REQUIRED_CONFIDENCE = "high"` (déjà au max)

## Étape 3 — Flip en `active` (semaine 2 ou plus)

```bash
railway variables --set AGENTYS_SELF_CRITIQUE_GATE=active --service backend
```

**Effet immédiat** :
- ~50-75% des drafts skippent le Critic externe
- Coût mensuel draft pipeline : −25 à −29%
- Latence p50 : 1.5-2s au lieu de 4-5s
- Sentinel continue de surveiller (en mode actif il monitore les cas où le gate refuse de skip → Critic tourne → comparable)

## Rollback (n'importe quel moment)

```bash
railway variables --set AGENTYS_SELF_CRITIQUE_GATE=off --service backend
```

Effet : retour au comportement pré-Phase-3 en ~30s. Le code du gate reste mais ne s'exécute plus. Aucune migration de données nécessaire (les rows existants sont juste de la télémétrie).

## Acquisition des logs (v1, à câbler)

Le sentinel lit `/var/lib/agentys/data/orchestration_summary.jsonl` par défaut (overridable via `ORCHESTRATION_SUMMARY_LOG_PATH`).

**Le backend Railway DOIT écrire les `[ORCHESTRATION_SUMMARY]` log lines dans ce fichier** pour que le sentinel ait quelque chose à lire. Trois options selon la config infra :

1. **Option A — Volume monté + log shipping** (recommandé) : Railway écrit ses logs vers un fichier sur le volume monté `~/.agentys/data/`, un cron rsync vers Hetzner toutes les heures.
2. **Option B — Railway logs API** : un cron Hetzner appelle `railway logs --service backend --json` toutes les heures, filtre les `[ORCHESTRATION_SUMMARY]` lines, append au fichier local. Nécessite `RAILWAY_TOKEN` sur Hetzner.
3. **Option C — Push direct** : modifier l'orchestrateur pour POST chaque summary à un endpoint Hetzner. Plus complexe.

Sans ce câblage, le sentinel skip avec un warning explicite — pas d'échec dur, juste "pas de data, je dors".

**Décision pragmatique** : commencer en `shadow` SANS le sentinel câblé, vérifier manuellement via `railway logs | grep ORCHESTRATION_SUMMARY` les premiers jours, puis câbler l'option A ou B une fois confiant que le format des logs est stable.

## Garde-fous architecturaux (déjà en place)

Le gate est **fail-safe par design** (cf. `app/services/draft_orchestrator.py:99-117`) :
- Si SelfCritique raise une exception → fall-through au Critic
- Si SelfCritique fail (timeout, parse) → `failure_reason` set, fall-through au Critic
- Si self_score < 85, ou risks détectés, ou [À confirmer], ou confidence != high → fall-through au Critic
- Le gate ne tourne JAMAIS sur les itérations de révision (V2) — un draft rejeté par Critic ne peut pas être ré-acquitté par SelfCritique
- Une exception dans la télémétrie est catch et logged (jamais raise) — ne masque jamais le résultat de l'orchestration

## Tests pertinents

```bash
# Gate tests (21 cas — modes off/shadow/active, fail-safe, single-iteration contract)
pytest tests/services/test_draft_orchestrator_self_critique_gate.py -v

# Sentinel tests (28 cas — parsing, agrégation, thresholds, file I/O)
pytest tests/ai_team/test_sentinel_self_critique_gate.py -v

# Orchestrator regression baseline (22 cas)
pytest tests/services/test_draft_orchestrator.py -v
```

Les 76 tests doivent passer en ~10s. Si l'un casse → arrêter le rollout, investiguer.

## Référence

- Plan complet : `tasks/draft-pipeline-optimization-2026-05-03.md`
- Eval synthétique 200 cas : `tasks/eval-self-critique-vs-critic-summary-2026-04-30.md`
- Code gate : `app/services/draft_orchestrator.py:60-117`
- Code sentinel : `ai_team/agents/cron/sentinel_self_critique_gate.py`

## TODO — Bloquant pour valider rigoureusement le gate

### Ground truth set (50-100 drafts hand-labellés)

Aujourd'hui, le sentinel mesure `agreement gate-vs-Critic`. Le Critic a 34% de FP propres. Donc l'agreement-rate est tautologique : "deux LLM biaisés sont d'accord" ne dit rien sur la qualité réelle.

**Action** : exporter 50-100 paires `(email_original, draft_v1)` depuis prod (ou `tests/fixtures/drafting_eval_runs/run_20260417_153024/`), labelliser à la main `is_actually_good: true | false` selon ces critères :
- Pas d'hallucination factuelle
- Bonne langue
- Greeting/closing OK
- Pas de [À confirmer] résiduel
- Concision adaptée au contexte
- Le draft est *envoyable tel quel*

Une fois le set existant (`tasks/ground-truth-drafts-2026-XX.json`), on peut réécrire le sentinel pour mesurer **gate vs ground-truth** et **Critic vs ground-truth** séparément. Le verdict final compare les deux.

**Effort** : ~2h (labellisation), aucun coût LLM.

### Audit prompt caching effectif sur le Critic

Le wrapper adapter (`claude_adapter.py:138`) annote le system prompt avec `cache_control: ephemeral`. Pour qu'Anthropic mette le prefix en cache, il faut **≥1024 tokens** de prefix stable dans la fenêtre de TTL 5min.

Mesurer (depuis Railway logs ou via instrumentation custom) :
- Combien de tokens fait le system prompt structured Critic typique ?
- Quel est le `cache_read_input_tokens` vs `cache_creation_input_tokens` retourné par l'API sur les calls successifs ?

Si le prefix est trop court ou si la KB change d'un account à l'autre → le cache ne hit pas. C'est le levier #2 de `tasks/draft-pipeline-optimization-2026-05-03.md` qui peut grignoter -80% sur l'input cost du Critic — si effectif, la valeur du gate (-5% net coût) devient marginale.

**Effort** : ~1h instrumentation + analyse.
