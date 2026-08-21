# Onboarding — Pipeline d'apprentissage

L'onboarding analyse les 100 derniers emails d'un utilisateur pour construire
une base de connaissances qui permettra au `DrafterAgent` de rédiger des
brouillons de réponse avec le bon ton, le bon style et le bon contexte.

## Architecture

```
                          ┌─────────────────────┐
                          │   Frontend (React)   │
                          │   Bouton "Apprendre" │
                          └──────────┬──────────┘
                                     │ POST /api/onboarding/start
                                     ▼
                          ┌─────────────────────┐
                          │  OnboardingManager   │
                          │  (manager.py)        │
                          │                      │
                          │  - Crée un record DB │
                          │  - Lance un thread   │
                          │  - Émet WebSocket    │
                          └──────────┬──────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │    1. Loader      │  │    2. Indexer     │  │  3. Orchestrator │
    │    (loader.py)    │──▶│    (indexer.py)   │──▶│  (orchestrator   │
    │                  │  │                  │  │   .py)            │
    │  Charge les      │  │  Tri, groupe,    │  │  Lance les 3     │
    │  emails bruts    │  │  calcule les     │  │  agents LLM      │
    │                  │  │  métriques       │  │  séquentiellement │
    └──────────────────┘  └──────────────────┘  └────────┬─────────┘
                                                         │
                                        ┌────────────────┼────────────────┐
                                        │                │                │
                                        ▼                ▼                ▼
                                 ┌────────────┐  ┌────────────┐  ┌────────────┐
                                 │  Profile    │  │ Knowledge  │  │   Rules    │
                                 │  Agent      │  │  Agent     │  │   Agent    │
                                 │             │  │            │  │            │
                                 │ Qui es-tu ? │  │ Qui        │  │ Comment    │
                                 │             │  │ connais-tu │  │ écris-tu ? │
                                 │             │  │ ?          │  │            │
                                 └──────┬──────┘  └──────┬─────┘  └──────┬─────┘
                                        │                │                │
                                        ▼                ▼                ▼
                                 profile.json    knowledge.json    rules.json
                                        │                │                │
                                        └────────────────┼────────────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────┐
                                              │    Stockage       │
                                              │                  │
                                              │ - DB (SQLite)    │
                                              │ - memoire.md     │
                                              └──────────────────┘
```

## Étapes du pipeline

### 1. Loader — Chargement des emails

**Fichier** : `loader.py`

Deux implémentations :

| Loader | Usage | Source |
|--------|-------|--------|
| `FixtureLoader` | Tests / eval | Fichier JSON (`tests/fixtures/test_emails.json`) |
| `RepositoryLoader` | Production | Base SQLite via `EmailRepository` |

Chaque email est normalisé en un `OnboardingEmail` avec :
expéditeur, destinataires, CC, sujet, corps, date, direction (envoyé/reçu),
thread_id, signature, langue, labels.

### 2. Indexer — Structuration

**Fichier** : `indexer.py`

L'`EmailIndexer` prend les emails bruts et produit un `IndexedEmails` :

- **Tri chronologique** de tous les emails
- **Séparation** envoyés vs reçus
- **Groupement par contact** : tous les échanges avec un même contact
- **Groupement par thread** : les emails d'un même fil de conversation
- **Métriques par contact** : nombre d'interactions, premier/dernier échange,
  sujets abordés, nom du contact

### 3. Orchestrateur — Coordination des agents

**Fichier** : `orchestrator.py`

L'`OnboardingOrchestrator` lance les 3 agents séquentiellement et émet des
événements WebSocket de progression (5% → 33% → 66% → 100%).

### 4. Agents LLM — Analyse

**Répertoire** : `agents/`

Chaque agent reçoit les `IndexedEmails` mais en extrait un sous-ensemble
différent pour construire son prompt LLM.

#### ProfileAgent (`agents/profile_agent.py`)

**Question** : Qui est l'utilisateur ?

- **Input** : Échantillon de 30 emails envoyés (corps + signatures)
- **Output** : Nom, titre, entreprise, téléphone, ton par défaut (formel /
  semi-formel / casual), langues utilisées, heures d'activité

#### KnowledgeAgent (`agents/knowledge_agent.py`)

**Question** : Qui connaît-il et sur quoi travaille-t-il ?

- **Input** : Métriques par contact + 15 threads les plus actifs (corps inclus)
- **Output** : Contacts avec rôle (collègue / client / fournisseur / partenaire),
  projets actifs, terminologie métier, sujets fréquents

#### RulesAgent (`agents/rules_agent.py`)

**Question** : Comment s'adresse-t-il à chacun ?

- **Input** : Emails envoyés groupés par destinataire (top 15 contacts,
  5 emails par contact)
- **Output** : Règles par contact (ton, langue, formule d'ouverture/fermeture,
  tu/vous), règles générales, expressions interdites

### 5. Stockage — Persistance

**Fichier** : `manager.py`

Le `OnboardingManager` :

1. Sauvegarde les résultats en DB (`onboarding_result` table) sous forme JSON
2. Génère un fichier `knowledge/memoire.md` structuré en 3 sections
   (Profil, Savoir, Règles) utilisable par le `DrafterAgent`
3. Émet les événements WebSocket finaux (`learning_completed`,
   `insights_generated`)

## Schemas

**Fichier** : `schemas.py`

Définit les structures de données cibles (dataclasses) :

- `UserProfile` : profil complet (signature, ton, langues)
- `KnowledgeBase` : contacts, projets, terminologie
- `RulesSet` : règles par contact, règles générales, expressions interdites
- Enums : `EmailDirection`, `ToneLevel`, `ContactType`, `Language`

## Évaluation

**Fichier** : `agents/evaluation_agent.py`
**Script** : `scripts/eval_onboarding.py`

L'`EvaluationAgent` compare les outputs des agents à un ground truth
(`tests/fixtures/ground_truth.json`) avec 3 métriques :

| Métrique | Description |
|----------|-------------|
| Completeness | Tout le ground truth a été trouvé ? |
| Precision | Pas de hallucinations ou d'erreurs ? |
| Usefulness | Les résultats sont exploitables pour le drafting ? |

Deux modes d'évaluation :

- **LLM-as-judge** : Un LLM compare les outputs (plus précis, plus lent)
- **Heuristique** : Comparaison programmatique (rapide, pour CI)

### Lancer une évaluation

```bash
# Run complet avec évaluation heuristique
python scripts/eval_onboarding.py --no-llm-judge --save

# Agent unique
python scripts/eval_onboarding.py --agent profile --no-llm-judge --save

# Via Claude Code (pas de clé API nécessaire)
python scripts/eval_onboarding.py --claude-cli --no-llm-judge --save

# Comparer avec un run précédent
python scripts/eval_onboarding.py --claude-cli --save --compare run_20260214_104709
```

### Structure des résultats

Chaque run crée un répertoire dans `tests/fixtures/eval_runs/` :

```
tests/fixtures/eval_runs/run_20260214_104709/
├── config.json      # Config du run (modèle, mode, timing)
├── scores.json      # Scores d'évaluation (completeness, precision, usefulness)
├── profile.json     # Output brut du ProfileAgent
├── knowledge.json   # Output brut du KnowledgeAgent
└── rules.json       # Output brut du RulesAgent
```

## Événements WebSocket

| Événement | Quand | Données |
|-----------|-------|---------|
| `onboarding:learning_started` | Début du pipeline | `account_id`, `onboarding_id` |
| `onboarding:progress_updated` | Progression d'un agent | `confidence` (0-100), `phase` |
| `onboarding:learning_completed` | Fin (succès ou échec) | `status`, `emails_analysed` |
| `onboarding:insights_generated` | Résumé pour le frontend | `writing_style`, `topics`, `strengths` |

## Arborescence

```
app/onboarding/
├── __init__.py
├── README.md              ← Ce fichier
├── schemas.py             # Dataclasses (UserProfile, KnowledgeBase, RulesSet)
├── loader.py              # FixtureLoader, RepositoryLoader
├── indexer.py             # EmailIndexer → IndexedEmails
├── orchestrator.py        # OnboardingOrchestrator (séquence des 3 agents)
├── manager.py             # OnboardingManager (thread, DB, WebSocket, memoire.md)
└── agents/
    ├── __init__.py
    ├── profile_agent.py   # ProfileAgent → UserProfile
    ├── knowledge_agent.py # KnowledgeAgent → KnowledgeBase
    ├── rules_agent.py     # RulesAgent → RulesSet
    └── evaluation_agent.py # EvaluationAgent (scoring vs ground truth)
```
