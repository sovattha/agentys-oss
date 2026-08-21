# Onboarding — Prompt Engineering

## Scores actuels (re-évalué 2026-05-06, run all-personas)

| Persona | Profile | Knowledge | Rules | TOTAL | vs ancienne baseline (82) |
|---|---|---|---|---|---|
| default | 70 | 58 | 77 | 68 | -15 |
| lawyer_paris | 75 | 72 | 80 | 76 | -11 |
| sales_director | 75 | 71 | 85 | 77 | -6 |
| startup_ceo | 42 | 63 | **80** ⬆ | 62 | -13 |
| hr_director | 85 | 68 | 77 | 77 | -7 |
| consultant_intl | 68 | 54 | 75 | 66 | -17 |
| **MOYENNE** | **69** | **64** | **79** | **71** | **-11** |

> Run sauvegardé : `tests/fixtures/eval_runs/run_20260506_*` — judge `claude-sonnet-4-20250514`, mode `--api`.

### Diagnostic 2026-05-06

- **Profile (mean 69)** est le sous-score le plus bas. Cause racine identifiée : le schéma profile a évolué (champs `preferred_name`, `addressing`, `language_variant` ajoutés par le prompt actuel) mais les fixtures `ground_truth_*.json` n'ont PAS été mises à jour. Le judge marque ces champs comme « fabriqués » → -10 à -15 pts par persona. **Fix opérationnel** : régénérer les ground truths pour refléter le schéma actuel, pas un changement de prompt.
- **Rules (mean 79)** tient bien. **startup_ceo Rules est passé de 75 → 80 (+5 pts) après l'ajout de la catégorie « Vocabulaire métier »** dans `style.txt` (audit 2026-05-06). Le delta est dans le bruit pour les autres personas (±2-3 pts) — la modification est neutre, pas régressive.
- **Knowledge (mean 64)** souffre principalement de `topics` et `type` souvent vides — gap d'extraction connu, à creuser séparément.

## Ancienne ligne (avant 2026-05-06, scores stale)

| Persona | Score | Delta |
|---|---|---|
| default | 83 | +6 |
| lawyer_paris | 87 | +10 |
| sales_director | 83 | +6 |
| startup_ceo | 75 | -2 |
| hr_director | 84 | +7 |
| consultant_intl | 83 | +6 |
| **MOYENNE** | **82** | **+5** |

> Cette ligne était basée sur un judge différent et un schéma profile antérieur. Conservée pour traçabilité — le run du 2026-05-06 ci-dessus est la baseline actuelle.

## Fichiers clés

- `app/onboarding/agents/prompts/profile.txt` — profil utilisateur (ton, signature, horaires)
- `app/onboarding/agents/prompts/knowledge.txt` — contacts, langue, ton (PAS de projets/terminologie/FAQ — ces clés sont filtrées comme hallucinations, voir `knowledge_agent.py`)
- `app/onboarding/agents/prompts/style.txt` — style d'écriture (formality, longueur, vocabulaire) — ex-`rules.txt` renommé
- `app/onboarding/agents/prompts/label.txt` — labels d'organisation (LabelAgent)
- `scripts/eval_onboarding.py` — script d'évaluation LLM-as-judge (voir [`docs/eval-harness.md`](eval-harness.md) pour la doc complète + flag `--judge-model` pour bench équitable)

> Note (2026-05-04) : `rules.txt` et `domain.txt` ont été supprimés (DomainResearchAgent retiré dans #151). Les 4 fichiers ci-dessus sont la totalité du pipeline d'extraction onboarding.

## 7 règles d'or

1. **Prescriptif vs Extractif** : Ne jamais hardcoder les NOMS de sorties dans un prompt d'extraction. Guider par catégories ouvertes, laisser le LLM nommer.
2. **Effet balancier** : Toujours tester sur TOUS les personas après chaque changement (`--all-personas`). Jamais optimiser un seul persona en isolation.
3. **Ton = couple (greeting, closing) + relation hiérarchique** : "Hi" = semi-formal PAR DÉFAUT, SAUF si closing ultra-casual ET collègue de même niveau.
4. **Anti-hallucination** : Pour les champs optionnels, spécifier le défaut vide `[]` et exiger des preuves observées.
5. **Types extensibles** : La liste des types de contacts doit couvrir tous les domaines testés. Vérifier chaque ground truth.
6. **Variabilité LLM-as-judge** : ±5 pts entre runs identiques. Ne pas sur-réagir à un delta < 5 pts.
7. **Règles conditionnées au domaine** : Toute règle domaine-spécifique doit avoir une clause d'exclusion explicite pour les autres domaines.

## Historique des optimisations

```
Epoch 1 (pipeline)     : 69/100 (1 persona)
Epoch 2 (mono-persona) : 90/100 (1 persona, +21 pts)
Epoch 3 (multi-persona): 77/100 (6 personas, chute de généralisation)
Epoch 4 round 1        : 80/100 (+3)
Epoch 4 round 2        : 81/100 (fix startup_ceo)
Epoch 4 round 3        : 81/100 (balancier startup/consultant)
Epoch 4 round 4        : 82/100 (hybride final)
```

## Axes d'amélioration restants

- **startup_ceo (75)** : le plus résistant — Rules à 68 (variabilité LLM), contact types non-standard
- **Titres de contacts** souvent `null` (LLM n'extrait pas des signatures)
- **response_time / active_hours** approximatifs (LLM calcule mal les médianes)
