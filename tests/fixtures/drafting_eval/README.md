# Drafting Eval — Fixtures & Golds

Ce dossier contient les fixtures et réponses gold pour l'eval harness drafting (Issue #468).

## Format des fichiers

### `cases.example.json`

Liste de cas drafting normalisés. Chaque entrée porte les champs `DraftingFixtureCase` :

```json
[
  {
    "case_id": "lawyer_decline_meeting_fr",
    "persona": "lawyer_paris",
    "incoming_email": {
      "from": "client@example.com",
      "from_name": "Jean Client",
      "subject": "Demande de réunion vendredi 14h",
      "body": "Maître,\n\nPourriez-vous me recevoir vendredi 14h pour discuter du dossier X ?\n\nCordialement,\nJean"
    },
    "conversation_history": [],
    "instructions": "décliner poliment, proposer mardi 10h ou jeudi 16h",
    "user_email": "barreau@example.com",
    "user_signature": "Marc-Antoine Barreau\nAvocat à la Cour",
    "metadata": {
      "language": "fr",
      "length": "short",
      "intent": "decline",
      "complexity": "low",
      "has_user_keywords": true,
      "selection_reason": "test ton décliner-poliment formel + guidage Reply Composer"
    }
  }
]
```

Champs requis : `case_id` (unique), `incoming_email.body`, `user_email`.
Champs optionnels : `conversation_history`, `instructions`, `user_signature`, `metadata`.

#### `instructions` — mots-clés Reply Composer (critique pour la fidélité au cas prod)

En production, le drafter reçoit des mots-clés tapés par l'utilisateur dans
le **Reply Composer** (`drafter.draft(..., instructions="décliner poliment, proposer mardi 14h")`).
Sans ce paramètre, le harness teste un cas dégénéré (auto-draft) qui sous-représente
le vrai trafic.

- `"instructions": ""` → auto-draft (pas de guidage utilisateur)
- `"instructions": "<mots-clés>"` → Reply Composer guidé (cible majoritaire)

Le judge intègre les `instructions` dans le prompt user pour ne pas pénaliser
des choix qui découlent directement d'une directive utilisateur (ton, longueur,
décision). Voir `_format_instructions_section()` dans `scripts/eval_drafting.py`.

**Recommandation pour Run2** : viser au moins 60% des cas avec `instructions`
non vide pour refléter la distribution prod du Reply Composer.

### `golds.example.json`

Réponses « parfaites cibles » éditées à la main, indexées par `case_id`. Format `DraftingGold` :

```json
[
  {
    "case_id": "lawyer_decline_meeting_fr",
    "gold_body": "Cher Monsieur,\n\nJe vous remercie pour votre demande. Vendredi 14h ne m'est malheureusement pas possible — je peux vous proposer mardi 10h ou jeudi 16h. Quelle option vous convient ?\n\nDans l'attente de votre retour,",
    "rationale": "ton formel attendu d'un avocat ; refus avec alternative concrète plutôt qu'esquive ; pas d'invention de date hypothétique",
    "edge_cases_handled": ["decline_politely", "propose_alt_dates", "fr_formal"]
  }
]
```

Champs requis : `case_id`, `gold_body`.
Champs optionnels : `rationale` (utile pour relire 6 mois plus tard), `edge_cases_handled`.

## Critère d'un gold

> **« Si le drafter générait exactement ça, je l'enverrais sans toucher. »**

Tout écart (typo, ton off, info inventée) disqualifie le gold. Vaut mieux un gold absent qu'un gold médiocre — l'eval harness fallback gracieusement sur le `reference_reply` extrait du fil pour les cas sans gold.

## Curation des cas (à faire en Run2)

Pour Run2, sélectionner 15-20 cas couvrant explicitement la matrice :

| Axis        | Valeurs                                          |
|-------------|--------------------------------------------------|
| `language`  | `fr`, `en`                                       |
| `length`    | `short` (<10 lignes), `long` (≥10 lignes)        |
| `intent`    | `reply`, `decline`, `schedule`, `ack`            |
| `complexity`| `low`, `mid`, `high`                             |

Documenter `selection_reason` dans `metadata` pour chaque cas — ça permet de défendre le choix lors d'une revue 3 mois plus tard.

## Lancement de l'eval

### Mode v1 (latence + gold)

```bash
# Single persona, 3 runs par cas, judge avec golds
python scripts/eval_drafting.py --persona lawyer_paris --repeat 3 --with-gold --save

# Comparer au baseline figé
python scripts/eval_drafting.py --persona lawyer_paris --repeat 3 --with-gold \
    --compare tests/fixtures/drafting_eval_runs/v1_lawyer_paris_<TIMESTAMP>
```

### Mode legacy (compat)

```bash
# Comportement inchangé sans les nouveaux flags
python scripts/eval_drafting.py --persona lawyer_paris --save
```

## Hors-scope Run1

- **Curation des 15-20 cas** : Run2 (Phase 2 du plan #468)
- **Écriture des golds** : Run2 (jugement humain requis)
- **Mode v1 + `--all-personas`** : Run2
- **Métrique `gold_alignment` séparée** : Run3 si Phase 3 le justifie

## Schéma des runs (`run.json`)

Format `RunV1` (`scripts/eval_drafting_helpers.py`) :

```json
{
  "schema_version": 1,
  "timestamp_utc": "2026-05-04T01:00:00Z",
  "config": {
    "persona": "lawyer_paris",
    "drafter_model": "claude-haiku-4-5",
    "judge_model": "sonnet",
    "use_claude_cli": true,
    "with_gold": true,
    "gold_dir": "tests/fixtures/drafting_eval",
    "repeat": 3,
    "warmup": true,
    "no_llm_judge": false
  },
  "cases": [
    {
      "case_id": "...",
      "subject": "...",
      "runs": [
        {"run_idx": 0, "latency_ms": 2200, "judge_overall": 85}
      ],
      "stats": {"n": 3, "p50_ms": 2200, "p95_ms": 2400, "mean_ms": 2300, "std_ms": 100},
      "critic_overall": 82,
      "judge_overall_mean": 85,
      "last_draft": "..."
    }
  ],
  "aggregate": {
    "p50_ms": 2200,
    "p95_ms": 2400,
    "mean_ms": 2300,
    "n_total_runs": 45,
    "judge_overall_mean": 84.3,
    "judge_overall_p25": 80.0
  }
}
```

Toute évolution du schéma doit incrémenter `schema_version` et `_SUPPORTED_SCHEMA_VERSION` dans `eval_drafting_helpers.py`. Sans ça, `--compare` casse silencieusement entre runs.
