# Smart Routing Engine — Documentation Technique

> Dernière mise à jour : 12 février 2026 (Phase 14: Draft Quality v3)
> Fichier source : `app/smart_routing.py` (~4200 lignes)
> Post-LLM pipeline : 27 étapes (voir Phase 12 dans CHANGELOG.md)

---

## Vue d'ensemble

Le Smart Routing Engine route chaque email entrant vers le tier de génération le moins coûteux capable de produire un draft de qualité :

```
Email entrant
    │
    ▼
┌─────────────┐     ┌─────────────┐
│  Pre-filter  │────▶│    SKIP     │  $0.000  (auto-senders, self-sent)
│  (règles)    │     └─────────────┘
│              │
│  Complexity  │     ┌─────────────┐
│  Classifier  │────▶│   SIMPLE    │  $0.000  (micro-templates)
│  (score 0-100)     └─────────────┘
│              │
│              │     ┌─────────────┐
│              │────▶│  STANDARD   │  $0.003  (Haiku 4.5)
│              │     └─────────────┘
│              │
│              │     ┌─────────────┐
│              └────▶│   COMPLEX   │  $0.003  (Haiku 4.5 + tokens élevés)
│                    └─────────────┘
└─────────────┘
```

## Tiers de routage

### SKIP ($0.000)

**Critères** : Pre-filter rule-based (aucun appel LLM)
- Auto-senders : `noreply@`, `no-reply@`, `notification@`, `calendar-notification@`, etc.
- Self-sent : l'utilisateur s'envoie un email
- Labels non-Action : FYI, Noise, Waiting (sauf si `force=True`)

**Résultat** : Aucun draft généré.

### SIMPLE ($0.000)

**Critères** : `complexity_score < ROUTING_SIMPLE_THRESHOLD` (défaut: 30) ET pas d'instructions utilisateur.

**Path A — Automated senders** :
- Template engine existant (`MatchTemplateUseCase`)
- Variables injectées depuis le profil d'écriture (greeting, sign-off, signature)

**Path B — Human senders** (micro-templates) :
- Meeting/availability (sans `?`, body < 120 chars)
- Acknowledgment (reçu, noté, ci-joint, body < 150 chars)
- Thanks/gratitude (sans `?`, body < 120 chars)
- Greeting style-aware via `WritingStyleProfile` + formality detection

**Guards de sécurité** :
- Toute présence de `?` dans le body → fallback STANDARD (sauf ack)
- Body trop long → fallback STANDARD
- Pas d'instructions utilisateur (sinon STANDARD forcé)

### STANDARD ($0.003 Haiku / $0.009 Sonnet si tone-sensitive)

**Critères** : Score entre SIMPLE_THRESHOLD et COMPLEX_THRESHOLD, ou fallback depuis SIMPLE.

**Pipeline** :
1. Récupération du profil d'écriture (`WritingStyleProfile`)
2. Construction des prompts (`get_standard_draft_prompts()`) :
   - Injection `extract_sent_examples()` + `extract_user_formulas()` (style réel utilisateur) *[Phase 14]*
   - Injection `_get_fewshot_section()` (exemples par intent/formality/langue) *[Phase 14]*
3. Détection formality → température adaptée (0.25 formel → 0.45 casual)
4. **Tone-sensitive routing** : si `_is_tone_sensitive()` → upgrade vers `container.llm_sonnet` (Sonnet 4) *[Phase 14]*
5. Appel LLM via `llm.complete()` (Haiku ou Sonnet selon tone)
6. Post-LLM cleanup (27 étapes)
7. Application des corrections apprises
8. Enforcement du greeting

**max_tokens dynamiques** :

| Body | Questions | max_tokens |
|------|-----------|-----------|
| < 150 chars | 0 | 128 |
| < 300 chars | ≤ 1 | 256 |
| < 500 chars | ≤ 2 | 384 |
| < 1000 chars | ≤ 3 | 512 |
| > 1000 chars | — | 768 |

### COMPLEX ($0.003)

**Critères** : `complexity_score >= ROUTING_COMPLEX_THRESHOLD` (défaut: 50)

**Différences avec STANDARD** :
- Instructions enrichies : "Address EACH question individually. Use 3-6 sentences."
- max_tokens plus élevés : 768 (base), 896 (score ≥ 70), 1024 (score ≥ 90)
- Même modèle Haiku (plus Sonnet depuis Phase 11)

---

## Classificateur de complexité

### Signaux analysés (`analyze_complexity()`)

| Signal | Points | Description |
|--------|--------|-------------|
| `question_count` | 3/question | Nombre de `?` dans body |
| `body_length` | 1-15 | Graduel : 200→3, 500→6, 1000→10, 2000→15 |
| `enumeration` | 8 | Listes numérotées/à puces dans le body |
| `conditional` | 5/match | "si...alors", "if...then", etc. |
| `multi_topic` | 10 | Marqueurs de changement de sujet (par ailleurs, also, secondly...) |
| `thread_depth` | 3/message | Nombre de messages dans le thread |
| `legal_financial` | 10 | Termes juridiques/financiers (contrat, clause, facture...) |
| `urgency` | 5 | "urgent", "asap", "deadline"... |
| `has_instructions` | 15 | L'utilisateur a fourni des instructions spécifiques |

### Seuils

```python
ROUTING_SIMPLE_THRESHOLD = 30   # score < 30 → SIMPLE
ROUTING_COMPLEX_THRESHOLD = 50  # score >= 50 → COMPLEX
```

---

## Pipeline post-LLM

Après génération du draft par Haiku, 6 étapes de nettoyage (ordonnées pour early-exit) :

```python
draft = _clean_prompt_leakage(draft)           # ~2ms  — supprime "---", "[instruction..."
draft = _strip_signature(draft)                 # ~1ms  — supprime signatures inventées
draft = _truncate_for_short_body(draft, body)   # ~1ms  — raccourcit si body ultra-court
if len(body) >= 300:
    draft = _strip_parroting(draft, body)       # ~10-50ms — détecte phrases recopiées
draft = _scrub_hallucinated_facts(draft, body)  # ~5-20ms — remplace données inventées par [A confirmer]
# ... corrections apprises ...
draft = _enforce_greeting(draft, greeting_hint) # ~1ms  — force le greeting correct
```

**Temps total** : 15-75ms selon la longueur du body.

### `_strip_parroting()` — Complexité O(n×m)

Détecte quand le LLM recopie des phrases du body original dans le draft :
- Tokenise le body et le draft en phrases (split sur `.?!`)
- Compare chaque phrase du draft avec chaque phrase du body
- Supprime les phrases avec >60% de mots en commun
- **Skippé si body < 300 chars** (risque de parroting quasi-nul, économie de 10-30ms)

### `_scrub_hallucinated_facts()`

Remplace les données inventées par le LLM par des placeholders :
- Prix/montants non présents dans le body
- Dates spécifiques non mentionnées
- Noms de personnes/entreprises inventés
- Pattern : `[A confirmer]` en FR, `[TBC]` en EN

---

## Cache de drafts

### Architecture

```
┌─────────────────────────────────┐
│     _draft_cache (dict)         │  ← In-memory, accès ~0ms
│     {email_id: (draft, timestamp)}
├─────────────────────────────────┤
│     ~/.agentys/draft_cache.json │  ← Disque, chargé au 1er accès
│     Écriture debounced (5 ops)  │     TTL: 1 heure
│     Thread-safe (Lock)          │
└─────────────────────────────────┘
```

### Paramètres

| Paramètre | Valeur |
|-----------|--------|
| TTL | 3600 secondes (1 heure) |
| Max entries | 500 (éviction des expirés au-delà) |
| Persistance | JSON sur disque (`~/.agentys/draft_cache.json`) |
| Écriture disque | Debounced (toutes les 5 écritures en mémoire) |
| Thread safety | `threading.Lock()` sur les lectures/écritures |
| Chargement | Lazy load au premier accès cache |

### Flux de cache

```
1. Vérifier cache mémoire (email_id) → HIT → retourner draft
2. Si premier accès → charger cache disque → vérifier
3. Vérifier PendingDraftStore (cross-process) → HIT → cacher + retourner
4. Générer draft via tier approprié
5. Stocker en mémoire + incrémenter compteur
6. Si compteur % 5 == 0 → persister sur disque
```

---

## Coûts détaillés

### Modèle de coût par tier

| Tier | Modèle | Input tokens | Output tokens | Coût/draft |
|------|--------|-------------|---------------|------------|
| SKIP | — | 0 | 0 | $0.000 |
| SIMPLE | Templates | 0 | 0 | $0.000 |
| STANDARD | Haiku 4.5 | ~800 | ~100-200 | ~$0.003 |
| COMPLEX | Haiku 4.5 | ~1200 | ~300-500 | ~$0.003 |

### Projection mensuelle (100 emails/jour)

```
Distribution typique:
  30% SKIP     × 3000 = 900  × $0.000 =  $0.00
  10% SIMPLE   × 3000 = 300  × $0.000 =  $0.00
  40% STANDARD × 3000 = 1200 × $0.003 =  $3.60
  20% COMPLEX  × 3000 = 600  × $0.003 =  $1.80
                                          ──────
  Sous-total (sans optimisations)         $5.40
  - Prompt caching (-90% système repeat)  -$0.30
  - Cache hits (~15% économisés)          -$0.80
  - Batch API 50% off (heures creuses)    -$0.80
                                          ──────
  TOTAL ESTIMÉ                            ~$3.50/mois
```

### Historique des coûts

| Phase | Coût/mois | Modèle COMPLEX | Qualité |
|-------|-----------|----------------|---------|
| Phase 8 (avant) | $20.70 | Sonnet ($0.018) | 86/100 |
| Phase 11 (après) | $5.54 | Haiku ($0.003) | 90/100 |
| Phase 11 + batch | ~$3.50 | Haiku + batch | 90/100 |

---

## Optimisations actives

### 1. Prompt caching (Anthropic)

```python
# claude_adapter.py
system_block = [{
    "type": "text",
    "text": system,
    "cache_control": {"type": "ephemeral"},
}]
```

Le system prompt (~250 tokens, identique pour chaque draft) est caché côté Anthropic. Les appels consécutifs ne paient que le delta (user prompt + output).

### 2. Combined label+draft

`classify_and_draft()` dans `smart_routing.py` fait classification ET draft en un seul appel Haiku pour les emails STANDARD. Économise 1 appel API par email Action.

### 3. Batch API (50% discount)

Les drafts générés en heures creuses (20h-7h + weekends) sont envoyés via l'API Message Batches d'Anthropic à 50% du prix.

**Architecture :**

```
┌─────────────────────────────────────────────────────────────┐
│  Tracking activité utilisateur (whitelist)                   │
│  ├── run_api.py: before_request                             │
│  │   ├── POST/PATCH/DELETE/PUT → activité (action user)     │
│  │   ├── GET /api/emails/<id>  → activité (lecture email)   │
│  │   └── GET /api/emails (liste), /api/drafts, etc → ignoré│
│  └── websocket.py: on_daemon_connect → activité             │
│       → touch_user_activity() → _last_user_activity = now   │
├─────────────────────────────────────────────────────────────┤
│  Décision batch (is_batch_window)                           │
│  ├── BATCH_API_ENABLED = True                               │
│  ├── Heure actuelle hors 07:00-20:00 OU weekend             │
│  └── Aucune activité depuis BATCH_ACTIVITY_TIMEOUT_MIN (15) │
├─────────────────────────────────────────────────────────────┤
│  Intégration dans le flux                                   │
│  ├── smart_routing.py: route() step 4.5 → enqueue_for_batch │
│  └── daemon.py: process_email() step 6 → SmartRouter.route()│
├─────────────────────────────────────────────────────────────┤
│  BatchWorker (thread daemon, poll 30s)                      │
│  ├── SQLite queue (batch_queue.db)                          │
│  ├── Submit micro-batches → Anthropic Batch API             │
│  ├── Poll results → save PendingDraft + WebSocket           │
│  └── Fallback: stale > 30min → real-time SmartRouter        │
└─────────────────────────────────────────────────────────────┘
```

**Stratégie par tier :**

| Tier | Heures actives | Heures creuses (batch) |
|------|---------------|----------------------|
| SKIP | Pas de draft | Pas de draft |
| SIMPLE | Template ($0) | Template ($0) |
| STANDARD | Combined label+draft ($0.003) | Combined label+draft ($0.003) — pas de batch* |
| COMPLEX | Label + orchestrateur ($0.009) | Label + batch Haiku ($0.0045) |

\* Le combined path est déjà plus économique que label-only + batch draft.

### 4. Formality-based temperature

| Formality | Temperature | Effet |
|-----------|------------|-------|
| 1 (casual) | 0.45 | Plus créatif, ton détendu |
| 3 (neutre) | 0.35 | Équilibré |
| 5 (formel) | 0.25 | Plus précis, ton professionnel |

### 5. Token waste logging

```python
if used_out < max_tokens * 0.3:
    logger.debug(f"SmartRouter: token budget waste — used {used_out}/{max_tokens}")
```

Signale quand le budget tokens est sous-utilisé pour permettre un tuning futur des seuils.

---

## Tests de performance

### Script : `test_smart_routing_perf.py`

13 scénarios couvrant tous les tiers :

| # | Scénario | Tier attendu | Langue |
|---|----------|-------------|--------|
| 1 | Notification auto (noreply) | SKIP | — |
| 2 | Invitation calendrier | SKIP | — |
| 3 | Question simple collègue | STANDARD | FR |
| 4 | Relance livraison | STANDARD | FR |
| 5 | Message informel ami | STANDARD | FR |
| 6 | Demande client pro | STANDARD | FR |
| 7 | Email en anglais | STANDARD | EN |
| 8 | Négociation multi-questions | COMPLEX | FR |
| 9 | Problème technique complexe | COMPLEX | FR |
| 10 | Discussion juridique | COMPLEX | FR |
| 11 | Dispo réunion (micro-template) | SIMPLE | FR |
| 12 | Accusé de réception (micro-template) | SIMPLE | FR |
| 13 | Remerciement simple (micro-template) | SIMPLE | FR |

### Scorer de qualité (par tier)

| Critère | Pénalité | Applicable |
|---------|----------|------------|
| Pas de greeting | -7 | Tous |
| Prompt leakage | -20 | Tous |
| Mauvaise langue | -20 | Tous |
| Trop long (>150 mots STANDARD, >300 mots COMPLEX) | -7 | STANDARD, COMPLEX |
| Trop court (<4 mots) | -20 | Tous |
| Parroting (recopie du body) | -6 | Tous |

### Exécution

```bash
# Nécessite le backend Python (Flask) actif
python test_smart_routing_perf.py

# Résultats JSON détaillés
cat test_smart_routing_results.json
```

---

## Configuration

### Variables (`app/config.py`)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SMART_ROUTING_ENABLED` | `True` | Active/désactive le routeur |
| `ROUTING_SIMPLE_THRESHOLD` | `30` | Score max pour tier SIMPLE |
| `ROUTING_COMPLEX_THRESHOLD` | `50` | Score min pour tier COMPLEX |
| `BATCH_API_ENABLED` | `True` | Active le batch off-hours |
| `BATCH_ACTIVE_HOURS_START` | `07:00` | Début des heures actives (real-time) |
| `BATCH_ACTIVE_HOURS_END` | `20:00` | Fin des heures actives |
| `BATCH_WEEKEND_ALL_DAY` | `True` | Batch toute la journée le weekend |
| `BATCH_ACTIVITY_TIMEOUT_MIN` | `15` | Timeout inactivité avant batch (minutes) |
| `BATCH_QUEUE_MIN_SIZE` | `5` | Taille minimum pour soumettre un micro-batch |
| `BATCH_QUEUE_MAX_SIZE` | `50` | Taille maximum d'un micro-batch |
| `BATCH_QUEUE_MAX_AGE_SEC` | `60` | Âge max avant soumission forcée |
| `BATCH_WORKER_POLL_SEC` | `30` | Intervalle de polling du worker |
| `BATCH_FALLBACK_TIMEOUT_MIN` | `30` | Timeout avant fallback real-time |

### Cache (`app/smart_routing.py`)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `_CACHE_TTL_SECONDS` | `3600` | Durée de vie cache (1h) |
| Cache file | `~/.agentys/draft_cache.json` | Persistance disque |

---

## Diagramme de flux complet

```
Email reçu
    │
    ├── Pre-filter ──────────────────────────── SKIP ($0)
    │   (auto-sender, self-sent, non-Action)
    │
    ├── Cache check ─────────────────────────── CACHE HIT ($0)
    │   (mémoire → disque → PendingDraftStore)
    │
    ├── Classify complexity (score 0-100)
    │   │
    │   ├── score < 30 ── SIMPLE
    │   │   ├── Auto sender → template engine
    │   │   ├── Human + match → micro-template ─── SIMPLE ($0)
    │   │   └── Human + no match → fallback ───── STANDARD ($0.003)
    │   │
    │   ├── 30 ≤ score < 50 ──────────────────── STANDARD ($0.003 / $0.009)
    │   │   ├── tone_sensitive? → Sonnet ($0.009)
    │   │   └── normal → Haiku ($0.003)
    │   │
    │   └── score ≥ 50 ──────────────────────── COMPLEX ($0.003 / $0.009)
    │       ├── tone_sensitive? → Sonnet ($0.009)
    │       └── normal → Haiku + enriched instructions + higher max_tokens
    │
    ├── Batch check (STANDARD/COMPLEX, force=False)
    │   ├── User actif (< 15min) → real-time (ci-dessus)
    │   └── User inactif + off-hours → enqueue_for_batch()
    │       └── BatchWorker → Anthropic Batch API (50% off)
    │           └── PendingDraft → WebSocket → UI (différé)
    │
    ├── Cache store (mémoire + disque debounced)
    │
    └── Draft prêt → PendingDraftStore → WebSocket → UI
```

---

## Tone-Sensitive Routing (Phase 14)

Certains emails nécessitent une nuance émotionnelle que Haiku ne produit pas bien. Le Smart Router détecte ces cas et upgrade vers Sonnet.

### Détection

`_is_tone_sensitive(body, subject, instructions)` utilise `_TONE_SENSITIVE_RE` pour détecter :

| Catégorie | Patterns |
|-----------|----------|
| Refus/déclin | `decline`, `refuse`, `cannot attend`, `regret`, `unfortunately`, `malheureusement`, `impossible` |
| Mauvaises nouvelles | `bad news`, `sad to inform`, `mauvaise nouvelle`, `décès`, `condoléances` |
| Conflit/plainte | `complaint`, `disappointed`, `unacceptable`, `escalat`, `plainte`, `déçu`, `réclamation` |
| RH/sensible | `terminat`, `dismissal`, `resignation`, `disciplin`, `licenciement`, `démission`, `avertissement` |

### Configuration

```python
SONNET_ROUTING_ENABLED = get_env_bool("SONNET_ROUTING_ENABLED", True)
```

### Impact sur les 3 paths

Les 3 paths (STANDARD, STREAMING, COMBINED) ont le même code d'upgrade :

```python
llm = container.llm_label  # Haiku par défaut
if SONNET_ROUTING_ENABLED and _is_tone_sensitive(body, subject, instructions):
    llm = container.llm_sonnet  # Upgrade Sonnet
```

---

## Few-shot Examples & Style Profile (Phase 14)

### Few-shot dynamiques

`_get_fewshot_section()` sélectionne 1-2 exemples curated par combinaison :
- **Intent** : `action` (défaut), `question` (si `?`), `decline` (si instructions contiennent un refus)
- **Formality** : `casual` (1-2), `formal` (3-5)
- **Langue** : `fr` (FRENCH), `en` (autre)

Injectés dans le **user prompt** (pas system) pour éviter le cache et limiter la contamination.

### Style profile utilisateur

`extract_sent_examples()` et `extract_user_formulas()` extraient des exemples réels de l'historique :
- `<TES_RÉPONSES_PRÉCÉDENTES>` : 2 derniers emails envoyés par l'utilisateur au contact
- `<TES_FORMULES_HABITUELLES>` : salutations et clôtures les plus fréquentes

Injectés dans le **system prompt** des 2 fonctions prompt (`get_standard_draft_prompts()`, `get_classify_and_draft_prompts()`).
