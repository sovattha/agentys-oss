# Tests de charge locaux

Ces scénarios chargent l'API sans consommer de tokens réels. Le backend doit
être démarré en mode test de charge pour isoler les données locales et éviter
les services de fond réels.

## Préparer

```bash
pip install -r requirements-dev.txt
```

## Démarrer l'API mockée

```bash
rm -rf /tmp/agentys-load-data
AGENTYS_LOAD_TEST_MODE=true \
AGENTYS_MOCK_LLM_LATENCY_MS=80 \
python run_api.py --host 127.0.0.1 --port 5050
```

`AGENTYS_LOAD_TEST_MODE=true` force le LLM mocké, le provider email mocké, le
bypass local du rate limit, `BATCH_API_ENABLED=false`, et isole la DB +
`pending_drafts.json` + `draft_cache.json` + les corrections de draft sous
`/tmp/agentys-load-data` si tu ne fournis pas `AGENTYS_DATA_DIR` /
`AGENTYS_DB_PATH`. Le mode désactive aussi les schedulers de fond pendant le
run.

Par défaut, les tokens synthétiques du mock LLM ne sont pas persistés dans
`token_usage_log`. Pour tester aussi l'attribution des appels LLM :

```bash
AGENTYS_MOCK_LLM_RECORD_USAGE=true
```

## Lancer Locust en headless

Commande recommandée : runner autonome avec rapport de dégradation.

```bash
scripts/load-test-mocked.sh \
  --stages 50,100,150,200,300,400,600,800,1000,1250,1500,2000 \
  --duration 10m \
  --spawn-rate 25
```

Le rapport final est écrit dans `tasks/load-reports/<run-id>/report.md`.
Il indique :

- le dernier palier sain ;
- le premier palier dégradé ;
- le premier palier crash/échec dur ;
- la backpressure contrôlée (`429 Retry-After`) ;
- le débit réel de drafts tentés / acceptés par minute ;
- les p95 HTTP et le p95 `process_background_total` extrait des logs serveur.

Seuils par défaut :

- dégradé si `failure_rate > 0.1%` ;
- dégradé si p95 HTTP ou acceptation `/process` > `250 ms` ;
- dégradé si p95 background draft > `1500 ms` ;
- crash si l'API ne répond plus à `/api/health` ou si Locust sort en erreur.

Pour une passe rapide :

```bash
scripts/load-test-mocked.sh --stages 5,10 --duration 30s --spawn-rate 5
```

## Tester par débit métier

Les “users Locust” sont volontairement agressifs : 100 users virtuels peuvent
déclencher beaucoup plus de drafts qu'une vraie cohorte produit. Pour répondre
à “combien de drafts/minute avant dégradation”, utiliser le mode débit :

```bash
scripts/load-test-mocked.sh \
  --draft-rates-per-minute 60,120,240,480,720 \
  --users-per-rate-stage 100 \
  --duration 5m \
  --spawn-rate 50 \
  --run-id drafts-per-minute-$(date +%Y%m%d-%H%M)
```

Ce mode garde un nombre fixe d'utilisateurs virtuels actifs, mais throttle les
appels `/process` avec `LOAD_TARGET_DRAFTS_PER_MINUTE`. Le rapport distingue :

- `Target drafts/min` : débit métier demandé ;
- `Draft attempts/min` : appels `/process` réellement envoyés ;
- `Draft accepts/min` : appels acceptés hors backpressure.

Variables utiles pour calibrer la saturation :

- `DRAFT_WORKER_MAX` : workers fixes de génération dans le process API.
- `DRAFT_QUEUE_MAX` : backlog global maximum avant `429`.
- `DRAFT_PER_ACCOUNT_MAX` : drafts actifs simultanés par compte.
- `DRAFT_PER_ACCOUNT_QUEUE_MAX` : backlog total par compte avant `429`.
- `DRAFT_QUEUE_RETRY_AFTER_SECONDS` : délai conseillé au client quand saturé.
- `DRAFT_QUEUE_WARN_UTILIZATION` / `DRAFT_QUEUE_CRITICAL_UTILIZATION` :
  seuils de `/api/health/capacity`.
- `LOAD_ACCOUNT_POOL_SIZE` : répartit les users Locust sur plusieurs
  `X-Account-Id` simulés au lieu de charger un seul compte.

Pendant un run, `GET /api/health/capacity` donne l'état instantané de la queue,
des workers, des rejets et des SLO configurés.

Pour mesurer le chemin Redis/RQ localement, lancer Redis puis demander au
runner de démarrer le worker :

```bash
docker run -d --rm --name agentys-load-redis -p 6380:6379 redis:7-alpine
DRAFT_QUEUE_BACKEND=redis \
DRAFT_RQ_WORKERS=16 \
scripts/load-test-mocked.sh \
  --redis-url redis://127.0.0.1:6380/0 \
  --start-draft-worker \
  --draft-rates-per-minute 2000,4000,8000 \
  --account-pool-size 25 \
  --users-per-rate-stage 100 \
  --duration 1m \
  --spawn-rate 100
docker stop agentys-load-redis
```

Le worker RQ draft utilise `DRAFT_RQ_WORKER_MODE=fork` par défaut, le mode RQ
historique avec isolation par job. `DRAFT_RQ_WORKER_MODE=simple` existe comme
levier expérimental in-process, mais il laisse aussi les tâches différées
continuer dans le worker ; à tester sous charge avant de l'activer.

Pour chercher le plafond de génération sans saturer la machine de test avec
les endpoints auxiliaires :

```bash
LOAD_HEALTH_CHECKS=false \
LOAD_LIST_EMAILS=false \
LOAD_WAIT_MIN_SECONDS=0.005 \
LOAD_WAIT_MAX_SECONDS=0.01 \
scripts/load-test-mocked.sh \
  --draft-rates-per-minute 2000,4000,8000,12000 \
  --account-pool-size 25 \
  --users-per-rate-stage 100 \
  --duration 1m \
  --spawn-rate 100
```

Le rapport ajoute alors un détail par compte à partir des logs
`[DRAFT-QUEUE]`, ce qui permet de distinguer une saturation globale d'une
saturation d'un seul compte.

Smoke test :

```bash
locust -f tests/load/locustfile.py \
  --headless -u 5 -r 1 -t 2m \
  --host http://127.0.0.1:5050
```

Baseline :

```bash
locust -f tests/load/locustfile.py \
  --headless -u 50 -r 5 -t 10m \
  --host http://127.0.0.1:5050 \
  --html /tmp/agentys-load-report.html \
  --csv /tmp/agentys-load
```

## Scénario Gmail-shaped

Pour mesurer la dégradation quand Gmail backoff sur le détail e-mail, activer le
scénario de détail non caché et le provider mock qui simule des quotas :

```bash
LOAD_OPEN_EMAIL_DETAIL=true \
AGENTYS_MOCK_GMAIL_DETAIL_BACKOFF_EVERY=5 \
AGENTYS_MOCK_GMAIL_BACKOFF_SECONDS=8 \
scripts/load-test-mocked.sh --stages 50,100 --duration 2m --spawn-rate 10
```

Pour simuler une sync Sent qui met le compte en backoff avant des lectures
interactives :

```bash
AGENTYS_MOCK_GMAIL_SENT_BACKOFF_EVERY=1
```

Stress court :

```bash
locust -f tests/load/locustfile.py \
  --headless -u 200 -r 20 -t 5m \
  --host http://127.0.0.1:5050
```

Variables utiles :

- `LOAD_PROCESS_EMAILS=false` : ne teste que health + liste emails.
- `LOAD_AUTH_MODE=dev-login` : force un JWT dev local avant les requêtes.
- `LOAD_ACCOUNT_ID=...` : ajoute `X-Account-Id` si tu veux cibler un compte.
- `LOAD_WAIT_MIN_SECONDS` / `LOAD_WAIT_MAX_SECONDS` : cadence entre requêtes.
- `AGENTYS_MOCK_LLM_OUTPUT` : force une réponse LLM précise pour reproduire un cas.

Chaque appel `/process` injecte une référence unique dans le corps de l'email
pour éviter que le cache `content_hash` masque les appels de génération.
Les emails de confirmation courts peuvent désormais sortir en `SIMPLE_TEMPLATE`
sans LLM ; pour forcer le chemin LLM dans un test, utiliser un corps plus long,
plusieurs questions ou des instructions utilisateur explicites.

## Railway mock : users + providers

Pour les services Railway dédiés `load-mock-api` / `load-mock-worker`, utiliser
le runner API asynchrone. Il ne démarre pas de serveur local et écrit un rapport
incrémental dans `tasks/load-reports/<run-id>/report.md`.

Mesure draft end-to-end avec statut Redis/RQ partagé :

```bash
scripts/load-test-railway-mock.sh \
  --scenario draft-users \
  --provider-kind gmail \
  --stages 400,800,1200,1600 \
  --stage-seconds 180 \
  --draft-period-seconds 60 \
  --poll-timeout-seconds 120 \
  --poll-max-interval-seconds 5 \
  --run-id railway-draft-gmail-$(date +%Y%m%d-%H%M)
```

Le polling de statut draft utilise un backoff borné entre
`--poll-interval-seconds` et `--poll-max-interval-seconds`. Pour les rampes
`5000+` utilisateurs, garder `--poll-max-interval-seconds >= 5` évite que les
GET `/api/draft-jobs/:task_id` deviennent eux-mêmes le goulot mesuré.

En `AGENTYS_LOAD_TEST_MODE=true`, l'entrypoint Railway lance automatiquement
l'API sous Gunicorn `gthread` au lieu du serveur Werkzeug. À `12000+`
utilisateurs, vérifier aussi que `load-mock-api` a plusieurs replicas et que le
générateur de charge n'est pas mono-machine avant d'attribuer les
`ClientConnectorError` au backend.

Mesure provider email mocké, sans LLM :

```bash
scripts/load-test-railway-mock.sh \
  --scenario provider \
  --provider-kind outlook \
  --stages 100,400,800,1200 \
  --stage-seconds 180 \
  --provider-period-seconds 15 \
  --provider-mix detail:8,list:1,sent:1 \
  --run-id railway-provider-outlook-$(date +%Y%m%d-%H%M)
```

Variables Railway utiles pour profiler les providers mockés :

- `AGENTYS_MOCK_EMAIL_PROVIDER_KIND=gmail|outlook` pour le défaut du service.
  Le runner passe aussi `provider_kind=gmail|outlook` à
  `/api/load-test/provider-probe`, ce qui permet de comparer les deux providers
  sans redéployer ou muter les variables Railway entre deux runs.
- `AGENTYS_MOCK_GMAIL_DETAIL_LATENCY_MS` /
  `AGENTYS_MOCK_OUTLOOK_DETAIL_LATENCY_MS`
- `AGENTYS_MOCK_GMAIL_LIST_LATENCY_MS` /
  `AGENTYS_MOCK_OUTLOOK_LIST_LATENCY_MS`
- `AGENTYS_MOCK_GMAIL_SENT_LATENCY_MS` /
  `AGENTYS_MOCK_OUTLOOK_SENT_LATENCY_MS`
- `AGENTYS_MOCK_GMAIL_DETAIL_BACKOFF_EVERY` /
  `AGENTYS_MOCK_OUTLOOK_DETAIL_BACKOFF_EVERY`
- `AGENTYS_MOCK_GMAIL_BACKOFF_SECONDS` /
  `AGENTYS_MOCK_OUTLOOK_BACKOFF_SECONDS`

Le scenario provider appelle `/api/load-test/provider-probe`, qui retourne 404
hors `AGENTYS_LOAD_TEST_MODE=true` + `AGENTYS_MOCK_EMAIL_PROVIDER=true`.
Les statuts inattendus (`404`, `400`, etc.) sont comptés comme erreurs client
et font échouer le palier au-delà du seuil `--max-failure-rate`.

## Diagnostic des 429 draft

Les refus `/api/emails/:id/process` exposent `reason`, `backend`,
`queue_status`, `queue_depth`, `queue_max`, `active_workers` et
`active_for_account`. Le runner écrit aussi `backpressure.jsonl` et agrège
`counters.backpressure_reasons`.

Principaux motifs attendus :

- `queue_full` : la queue globale a atteint `DRAFT_QUEUE_MAX`.
- `account_queue_full` : un compte a atteint `DRAFT_PER_ACCOUNT_QUEUE_MAX`.
- `redis_lock_timeout` : l'API n'a pas acquis le lock Redis assez vite pour
  enregistrer le job. Dans ce cas, la queue peut rester vide ; augmenter
  `DRAFT_REDIS_LOCK_BLOCKING_TIMEOUT_SECONDS` réduit les faux 429 au prix d'un
  POST `/process` qui attend un peu plus sous forte concurrence. Ce motif ne
  doit plus apparaître sur le chemin nominal : l'admission Redis/RQ est
  atomique et sans lock.
- `redis_unavailable` / `redis_connection_error` : Redis ou RQ indisponible,
  fail-closed en prod/load test.
