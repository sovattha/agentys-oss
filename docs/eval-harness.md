# Harnais d'évaluation (onboarding, drafting)

Référence du tooling d'évaluation LLM-as-judge pour les pipelines Agentys.

## Vue d'ensemble

Deux harnais distincts co-existent :

| Harnais | Script | Cible évaluée | Sortie |
|---|---|---|---|
| **Onboarding** | `scripts/eval_onboarding.py` | 3 agents : Profile / Knowledge / Style | Score 0-100 par persona + moyenne |
| **Drafting** | `scripts/eval_drafting.py` | Drafter + Critic | Double scoring Critic prod + juge externe |

Les deux utilisent le pattern **LLM-as-judge** : un LLM évalue l'output d'un pipeline contre un `ground_truth` de référence.

## Modes d'exécution

Les scripts peuvent router le LLM de 2 façons :

1. **`claude -p` (défaut, subscription)** : `claude code` en mode pipe, utilise l'abonnement Claude Code. Pas de coût par token côté utilisateur final.
2. **API directe (`--api`)** : appelle l'API Anthropic ou Ollama selon `LLM_PROVIDER`. Coût à la consommation.

**Règle projet** (voir `CLAUDE.md`) : **toujours utiliser `claude -p`** pour entraîner les prompts, jamais l'API directe.

### Bypass du check d'env

`app/config.py:494` refuse le boot si `LLM_PROVIDER=claude` (défaut) ET `ANTHROPIC_API_KEY` absent. Pour bypasser en local sans `.env` :

```bash
LLM_PROVIDER=ollama python scripts/eval_onboarding.py --all-personas
```

Le monkey-patch `activate_claude_cli` remplace ensuite l'adapter au runtime, donc la valeur `ollama` n'est jamais utilisée réellement.

## Confounding writer = judge (CRITIQUE)

Avant le commit `52524115` (2026-04-17), `activate_claude_cli` remplaçait `container._llm_sonnet` par l'adapter du writer. Or `EvaluationAgent.__post_init__` (le juge) pulle depuis `llm_sonnet`. Résultat : **le juge utilisait le même modèle que le writer**, introduisant un biais d'auto-indulgence.

**Impact mesuré** : Opus-juge notait Opus-writer +5 à +8 pts plus haut qu'un juge Sonnet indépendant. Toute comparaison cross-modèle faite avant ce commit est **invalide**.

### Flag `--judge-model` (commit `52524115`)

Permet de découpler writer et juge :

```bash
# Bench équitable : Opus 4.7 comme writer, Sonnet comme juge fixe
python scripts/eval_onboarding.py \
  --all-personas \
  --model claude-opus-4-7 \
  --judge-model sonnet
```

Règle : **pour toute comparaison de modèles writer, fixer un juge stable** (typiquement Sonnet). Idéalement utiliser l'ID complet (`claude-sonnet-4-6`) plutôt que l'alias (`sonnet`) pour éviter le drift quand Anthropic publie une nouvelle version.

## Personas disponibles (onboarding)

6 personas dans `tests/fixtures/` :

- `default` (Sophie Martin, PM tech bilingue)
- `lawyer_paris` (Marc-Antoine Barreau, avocat d'affaires Paris)
- `sales_director` (Karim Mandat, directeur commercial immobilier Lyon)
- `startup_ceo` (Priya Pivot, CEO startup SaaS bilingue)
- `hr_director` (Catherine Carrière, DRH banque)
- `consultant_intl` (James Conseil, consultant stratégie international)

Commandes utiles :

```bash
# Liste les personas
python scripts/eval_onboarding.py --list-personas

# Bench un seul persona
python scripts/eval_onboarding.py --persona lawyer_paris

# Bench tous + tableau comparatif
python scripts/eval_onboarding.py --all-personas

# Sauvegarder le run pour diff ultérieur
python scripts/eval_onboarding.py --all-personas --save
# → tests/fixtures/eval_runs/run_<timestamp>/
```

## Variance et reproductibilité

- **Variance intra-run ±5 à ±6 pts** par persona (LLM-as-judge non-déterministe).
- **Moyenne sur 6 personas** varie de ±2 pts entre runs — plus stable grâce à l'agrégation.
- **Règle** : ne pas sur-réagir à un delta < 5 pts par persona. Pour des conclusions robustes, faire 3 runs et prendre la moyenne.

## État actuel des scores (2026-04-17)

Bench fair (juge Sonnet fixe) :

| Writer | Score moyen 6 personas | Durée |
|---|---:|---:|
| Sonnet | 68 | 20m44 |
| Opus 4.6 | 68 | 18m15 |
| Opus 4.7 | 70 | 11m18 |

**Régression active** : la baseline mémoire d'époque (Epoch 4 round 4) était à 82/100. La régression a été tracée au commit `b35b2a32` (2026-04-11) "restauration complète des changements perdus (backup-local-work)" qui a rollback les prompts onboarding de 440→152 lignes (−65%). Détails + plan de remédiation : **[issue #237](https://github.com/nathan/agentys/issues/237)**.

## Architecture du harness onboarding

```
scripts/eval_onboarding.py
  ├── FixtureLoader         charge emails + metadata par persona
  ├── EmailIndexer          indexe par thread/contact/direction
  ├── run_agent()           lance ProfileAgent / KnowledgeAgent / StyleAgent (parallèle)
  └── EvaluationAgent       compare output vs ground_truth, retourne score 0-100
```

Monkey-patch important (`activate_claude_cli`) :

```python
container._llm_sonnet = adapter    # utilisé par les 3 agents ET le juge (sauf --judge-model)
container._llm_label  = adapter    # LabelAgent (classification emails)
container._llm        = adapter    # fallback générique
```

Le juge (`EvaluationAgent.__post_init__`) lit `container.llm_sonnet`. Si `--judge-model` est fourni, un 2e adapter est créé et `EvaluationAgent.__post_init__` est monkey-patché pour l'utiliser.

## Rubrique d'évaluation

Le juge note sur 3 dimensions (0-100 chacune) :

- **Completeness** : tous les items du ground_truth ont-ils été trouvés ?
- **Precision** : les items produits sont-ils corrects (pas d'hallucination) ?
- **Usefulness** : les outputs sont-ils exploitables pour générer des brouillons ?

Agrégation finale via `EvaluationAgent` → score `overall` par catégorie (Profile / Knowledge / Rules) puis moyenne.

## Références projet

- **Issue #237** — Plan de restauration des scores prompts onboarding post-`b35b2a32`
- **Commit `52524115`** — Ajout du flag `--judge-model`
- **`tasks/lessons.md`** — Leçons méthodologiques (dont "LLM-as-judge : ne jamais utiliser le même modèle comme writer ET juge")
- **`docs/sessions/2026-04-17.md`** — Investigation détaillée de la régression b35b2a32
- **Mémoire projet** : `opus-vs-sonnet-eval-2026-04-17.md` (détails chiffres + variances)

## À faire (pistes ouvertes)

- [ ] Bench CI bloquant sur régression (seuil 75, cf issue #237 Phase 4.1)
- [ ] Script wrapper `scripts/bench_multi.sh` pour agréger N runs (moyenne + σ)
- [ ] Holdout persona neuf pour détecter overfit lors des optims prompts
- [ ] Documenter la rubrique du juge drafter (`scripts/eval_drafting.py`) de façon similaire
