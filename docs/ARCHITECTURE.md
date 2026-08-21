# Architecture Agentys

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Agentys                                       │
│                     Pipeline Multi-Agents Email                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌──────────────────────────────────────────────────┐   │
│  │   Daemon    │    │                 Pipeline IA                       │   │
│  │  Principal  │───▶│                                                   │   │
│  └─────────────┘    │  ┌───────────┐  ┌──────────┐  ┌────────────────┐ │   │
│        │            │  │Classifier │  │Prioritizer│ │ Drafter Agent  │ │   │
│        │            │  │  Agent    │─▶│  Agent    │─▶│    (V1/V2)     │ │   │
│        │            │  └───────────┘  └──────────┘  └────────┬───────┘ │   │
│        │            │                                        │         │   │
│        │            │                                ┌───────▼───────┐ │   │
│        │            │                                │ Critic Agent  │ │   │
│        │            │                                └───────────────┘ │   │
│        │            └──────────────────────────────────────────────────┘   │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Infrastructure                                │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │ Circuit  │  │  Rate    │  │  Retry   │  │  Audit   │            │   │
│  │  │ Breaker  │  │ Limiter  │  │  Logic   │  │  Logger  │            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │  Cost    │  │ Security │  │ Database │  │ Logging  │            │   │
│  │  │ Manager  │  │ (RGPD)   │  │ (SQLite) │  │ (JSON)   │            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Flux de traitement d'un email

```
┌──────────────┐
│ Email reçu   │
│  (Gmail/     │
│   Outlook)   │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌─────────────────────────────────────────────┐
│  Classifier  │────▶│ Catégories:                                 │
│    Agent     │     │ URGENT | IMPORTANT | NORMAL | NEWSLETTER |  │
└──────┬───────┘     │ PROMO | SPAM | CC_ONLY                      │
       │             └─────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│  Skip si     │────▶ NEWSLETTER, PROMO, SPAM, CC_ONLY (si configuré)
│  low priority│
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌─────────────────────────────────────────────┐
│ Prioritizer  │────▶│ Score: 0-100                                │
│    Agent     │     │ Facteurs: Urgence, Sender VIP, Mots-clés    │
└──────┬───────┘     └─────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│   Email      │────▶ Nettoyer signatures, citations, truncate
│   Cleaner    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Drafter    │────▶ Génère Draft V1
│    Agent     │      (avec knowledge base + patterns appris)
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌─────────────────────────────────────────────┐
│   Critic     │────▶│ Évaluation:                                 │
│    Agent     │     │ [VALID] ou [REJET: raison]                  │
└──────┬───────┘     └─────────────────────────────────────────────┘
       │
       ├───────────────────────────────┐
       │                               │
       ▼ [VALID]                       ▼ [REJET]
┌──────────────┐               ┌──────────────┐
│  Draft V1    │               │   Drafter    │
│  Final       │               │   Revision   │
└──────┬───────┘               └──────┬───────┘
       │                               │
       │                               ▼
       │                       ┌──────────────┐
       │                       │  Draft V2    │
       │                       │  Final       │
       │                       └──────┬───────┘
       │                               │
       └───────────┬───────────────────┘
                   │
                   ▼
           ┌──────────────┐
           │ Create Draft │
           │  in Mailbox  │
           └──────┬───────┘
                  │
                  ▼
           ┌──────────────┐
           │   Track for  │
           │  Follow-ups  │
           └──────────────┘
```

## Structure des dossiers

```
agentys/
├── app/
│   ├── __init__.py
│   ├── agents.py          # DrafterAgent, CriticAgent, Classifier, Prioritizer
│   ├── config.py          # Configuration centralisée
│   ├── daemon.py          # EmailDaemon principal
│   ├── dashboard.py       # Interface web Flask
│   ├── followups.py       # Suivi des relances
│   ├── history.py         # Historique des drafts
│   ├── learning.py        # Apprentissage des patterns
│   ├── prompts.py         # Templates de prompts
│   │
│   ├── adapters/          # Adaptateurs externes
│   │   └── llm/
│   │       ├── claude_adapter.py
│   │       └── ollama_adapter.py
│   │
│   ├── infrastructure/    # Services techniques
│   │   ├── audit.py       # Logs d'audit
│   │   ├── circuit_breaker.py
│   │   ├── cost_manager.py
│   │   ├── database.py    # SQLite
│   │   ├── logging_config.py
│   │   ├── rate_limiter.py
│   │   ├── retry.py
│   │   └── security.py    # Chiffrement, RGPD
│   │
│   ├── interfaces/        # Abstractions
│   │   └── email_provider.py
│   │
│   ├── providers/         # Implémentations email
│   │   ├── factory.py
│   │   ├── gmail_adapter.py
│   │   └── outlook_adapter.py
│   │
│   └── utils/             # Utilitaires
│       └── email_cleaner.py
│
├── data/                  # Données persistantes
│   ├── agentys.db       # Base SQLite
│   ├── audit.json
│   └── followups/
│
├── docs/                  # Documentation
│   ├── ARCHITECTURE.md
│   └── TROUBLESHOOTING.md
│
├── knowledge/             # Base de connaissances
│   └── memoire.md
│
├── logs/                  # Logs applicatifs
│   └── agentys.log
│
├── tests/                 # Tests unitaires
│   ├── test_agents.py
│   ├── test_database.py
│   ├── test_daemon_integration.py
│   ├── test_infrastructure.py
│   └── ...
│
├── .env                   # Configuration (non versionné)
├── requirements.txt
├── run_daemon.py          # Point d'entrée daemon
├── run_dashboard.py       # Point d'entrée dashboard
└── setup.py               # Configuration interactive
```

## Composants Infrastructure

### Circuit Breaker

```
                    ┌────────────┐
                    │   CLOSED   │◀──────────────────┐
                    │  (Normal)  │                   │
                    └─────┬──────┘                   │
                          │                          │
                 N échecs │                          │ Succès
                          ▼                          │
                    ┌────────────┐                   │
                    │    OPEN    │                   │
                    │  (Rejet)   │                   │
                    └─────┬──────┘                   │
                          │                          │
                 Timeout  │                          │
                          ▼                          │
                    ┌────────────┐                   │
                    │ HALF-OPEN  │───────────────────┘
                    │  (Test)    │
                    └────────────┘
```

### Rate Limiter

```
    Sliding Window Rate Limiter
    ┌─────────────────────────────────┐
    │ Window: 60 seconds              │
    │ Max: 100 requests               │
    │                                 │
    │  ████████████░░░░░░░░░░░░░░░░░ │
    │  └── Requêtes dans la fenêtre   │
    └─────────────────────────────────┘

    Token Bucket Rate Limiter
    ┌─────────────────────────────────┐
    │ Bucket: 10 tokens max           │
    │ Refill: 5 tokens/sec            │
    │                                 │
    │  [■■■■■■■■░░]  8/10 tokens      │
    └─────────────────────────────────┘
```

### Base de données SQLite

```
┌─────────────────────────────────────────────────────────────────┐
│                          agentys.db                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │  processed_emails   │  │    draft_history    │              │
│  ├─────────────────────┤  ├─────────────────────┤              │
│  │ id TEXT PK          │  │ id INTEGER PK       │              │
│  │ processed_at TS     │  │ email_id TEXT       │              │
│  └─────────────────────┘  │ email_sender TEXT   │              │
│                           │ draft_final TEXT    │              │
│  ┌─────────────────────┐  │ status TEXT         │              │
│  │    sent_emails      │  │ priority_score INT  │              │
│  ├─────────────────────┤  │ category TEXT       │              │
│  │ id TEXT PK          │  └─────────────────────┘              │
│  │ recipient TEXT      │                                       │
│  │ thread_id TEXT      │  ┌─────────────────────┐              │
│  │ status TEXT         │  │   cost_tracking     │              │
│  └─────────────────────┘  ├─────────────────────┤              │
│                           │ date DATE           │              │
│  ┌─────────────────────┐  │ model TEXT          │              │
│  │   learned_patterns  │  │ cost_usd REAL       │              │
│  ├─────────────────────┤  └─────────────────────┘              │
│  │ pattern_type TEXT   │                                       │
│  │ pattern_value TEXT  │  ┌─────────────────────┐              │
│  │ confidence REAL     │  │     audit_log       │              │
│  └─────────────────────┘  ├─────────────────────┤              │
│                           │ event_type TEXT     │              │
│                           │ success INTEGER     │              │
│                           │ timestamp TS        │              │
│                           └─────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## Flux des données

```
┌────────────┐      ┌────────────┐      ┌────────────┐
│   Gmail    │      │  Outlook   │      │   IMAP     │
│    API     │      │  Graph API │      │   Server   │
└─────┬──────┘      └─────┬──────┘      └─────┬──────┘
      │                   │                   │
      └─────────┬─────────┴─────────┬─────────┘
                │                   │
                ▼                   ▼
        ┌───────────────────────────────────┐
        │         EmailProvider             │
        │       (Interface commune)         │
        └───────────────┬───────────────────┘
                        │
                        ▼
        ┌───────────────────────────────────┐
        │          EmailDaemon              │
        │    (Orchestration principale)     │
        └───────────────┬───────────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  Claude  │  │  Ollama  │  │ Learning │
    │   API    │  │   Local  │  │ Manager  │
    └──────────┘  └──────────┘  └──────────┘
          │             │             │
          └─────────────┼─────────────┘
                        │
                        ▼
        ┌───────────────────────────────────┐
        │            SQLite DB              │
        │    (Historique, Coûts, Audit)     │
        └───────────────────────────────────┘
```

## Points d'extension

### Ajouter un nouveau provider email

1. Créer `app/providers/nouveau_adapter.py`
2. Implémenter l'interface `EmailProvider`
3. Enregistrer dans `app/providers/factory.py`

### Ajouter un nouveau modèle LLM

1. Créer `app/adapters/llm/nouveau_adapter.py`
2. Implémenter les méthodes `complete()`, `complete_with_system()`
3. Ajouter les coûts dans `app/infrastructure/cost_manager.py`

### Ajouter un nouvel agent

1. Créer la classe dans `app/agents.py`
2. Définir le prompt dans `app/prompts.py`
3. Intégrer dans le pipeline de `app/daemon.py`

## Fondements scientifiques

Les fonctionnalités d'Agentys s'appuient sur des recherches publiées dans des revues et conférences de premier plan (ACM CHI, *Science*, KDD).

### Brouillons IA — DrafterAgent + CriticAgent

| Principe | Implémentation dans Agentys |
|----------|----------------------------|
| **Assistance paragraphe complet** | DrafterAgent génère un brouillon complet (pas de simples complétions) |
| **Boucle humain-dans-la-boucle** | CriticAgent valide, l'utilisateur confirme/édite/rejette |
| **Réduction du temps de rédaction** | Pipeline automatique : classification → drafting → critique → post-traitement |

**Noy, S., & Zhang, W.** (2023). *Experimental Evidence on the Productivity Effects of Generative Artificial Intelligence.* Science, 381(6654), 187–192. DOI: [10.1126/science.adh2586](https://doi.org/10.1126/science.adh2586)

> **Méthodologie** : Expérience randomisée avec 444 professionnels diplômés sur des tâches de rédaction.
>
> **Résultats clés** :
> - L'accès à l'IA réduit le temps de rédaction de **40%** et améliore la qualité de **18%**
> - L'IA bénéficie davantage aux rédacteurs moins expérimentés, compressant la distribution de productivité
> - Les tâches se restructurent vers la génération d'idées et l'édition, et s'éloignent de la rédaction brute
>
> ~950 citations. Publiée dans *Science* — la validation empirique la plus forte que l'assistance IA à la rédaction produit des gains mesurables de productivité et de qualité.

---

### Smart Suggestions

| Principe | Implémentation dans Agentys |
|----------|----------------------------|
| **Suggestions contextuelles** | `_generate_smart_suggestions()` — 2-3 réponses courtes (5-15 mots) via Haiku |
| **Réponse en un clic** | Chips cliquables dans PendingDraftDetail |
| **Coût quasi-nul** | ~$0.0001 par appel Haiku |

**Kannan, A., Kurach, K., Ravi, S., Kaufmann, T., Tomkins, A., Miklos, B., Corrado, G., Lukacs, L., Ganea, M., Young, P., & Ramavajjala, V.** (2016). *Smart Reply: Automated Response Suggestion for Email.* Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD '16), 955–964. DOI: [10.1145/2939672.2939801](https://doi.org/10.1145/2939672.2939801)

> **Méthodologie** : Paire de réseaux neuronaux récurrents (LSTM) entraînés sur des milliards d'emails Gmail.
>
> **Résultats clés** :
> - Smart Reply est responsable de **10% de toutes les réponses mobiles** dans Google Inbox
> - Le système génère des suggestions sémantiquement diversifiées en temps réel
> - Traite des centaines de millions de messages quotidiennement
>
> ~290 citations. Le papier fondateur de Google qui a démontré que les suggestions de réponse courtes réduisent massivement le temps de réponse aux emails.

---

### Mode Deep Focus — Concentration par lots

| Principe | Implémentation dans Agentys |
|----------|----------------------------|
| **Traitement par lots** | Emails groupés par section (labels), traités un à un séquentiellement |
| **Élimination des auto-interruptions** | Interface épurée, pas de sidebar ni de liste visible, raccourcis clavier uniquement |
| **Réduction du temps email** | Brouillons IA pré-générés, validation en un clic, Smart Suggestions |
| **Indicateurs de progression** | Progress ring SVG, compteur de section, ETA, streak |

**Mark, G., Iqbal, S. T., Czerwinski, M., Johns, P., & Sano, A.** (2016). *Email Duration, Batching and Self-interruption: Patterns of Email Use on Productivity and Stress.* Proceedings of the 2016 CHI Conference on Human Factors in Computing Systems (CHI '16), San Jose, CA, USA. ACM, pp. 1717–1728. DOI: [10.1145/2858036.2858262](https://doi.org/10.1145/2858036.2858262)

> **Méthodologie** : 40 travailleurs de l'information, 12 jours ouvrables, capteurs biométriques + logging informatique + questionnaires quotidiens.
>
> **Résultats clés** :
> - Plus de temps passé sur les emails = productivité perçue plus faible + stress plus élevé
> - Le traitement par lots (batching) des emails est associé à une meilleure productivité
> - La difficulté de concentration est le médiateur principal de la relation email-productivité
> - Les auto-interruptions sont plus fréquentes que les interruptions par notifications
>
> ~150 citations (Scopus). Valide directement 3 des 4 piliers du mode Deep Focus.

**Kushlev, K., & Dunn, E. W.** (2015). *Checking Email Less Frequently Reduces Stress.* Computers in Human Behavior, 43, 220–228. DOI: [10.1016/j.chb.2014.11.005](https://doi.org/10.1016/j.chb.2014.11.005)

> **Méthodologie** : Expérience randomisée avec 124 adultes sur 2 semaines — groupe limité à 3 consultations/jour vs groupe illimité.
>
> **Résultats clés** :
> - Consulter ses emails **3x/jour au lieu de continuellement** réduit significativement le stress quotidien
> - La réduction diminue aussi la distraction et prédit un meilleur bien-être global
>
> ~350 citations. La seule expérience randomisée sur la fréquence de consultation email — valide le principe de batching du Deep Focus.
