# Scaling des drafts

## État actuel

`POST /api/emails/<id>/process` accepte rapidement la requête puis place le
travail dans une queue mémoire bornée. Cette queue protège l'API contre
l'explosion de threads et applique une backpressure `429 Retry-After` quand le
serveur est saturé. En production Railway, la même route peut utiliser Redis/RQ
pour déléguer la génération à un service worker séparé.

Paramètres runtime :

- `AGENTYS_SERVICE_ROLE=draft-worker` : lance le service Railway en mode worker
  RQ au lieu du web.
- `AGENTYS_LOAD_TEST_MODE=true` : lance l'API mock sous Gunicorn `gthread`
  (`1` worker process, threads configurables) au lieu du serveur Werkzeug pour
  les mesures de forte concurrence.
- `AGENTYS_GUNICORN_THREADS` : nombre de threads Gunicorn par replica
  (`256` par défaut dans l'entrypoint Railway).
- `DRAFT_WORKER_MAX` : nombre de workers fixes.
- `DRAFT_QUEUE_MAX` : backlog global.
- `DRAFT_PER_ACCOUNT_MAX` : drafts actifs simultanés par compte.
- `DRAFT_PER_ACCOUNT_QUEUE_MAX` : backlog maximum par compte.
- `DRAFT_QUEUE_RETRY_AFTER_SECONDS` : délai de retry client conseillé.
- `DRAFT_QUEUE_BACKEND=redis` : active Redis/RQ.
- `DRAFT_QUEUE_NAME` : nom de queue RQ (`drafts` par défaut).
- `DRAFT_RQ_WORKERS` : nombre de process workers dans le service worker.

Observation :

- `GET /api/health/capacity` expose queue, workers, rejets, wait time et SLO.
- Les tests de charge mockés peuvent cibler des users ou des drafts/minute.

## Limite de ce modèle

La queue mémoire scale verticalement dans un seul process API. Elle ne permet
pas encore de partager le backlog entre plusieurs containers API ou workers.
Monter `DRAFT_WORKER_MAX` aide tant que CPU, DB, provider email et LLM suivent,
mais ce n'est pas du scaling horizontal durable.

## Workers horizontaux

Le chemin Redis/RQ est câblé :

- l'API réserve l'admission dans Redis via un script Lua atomique, sans lock
  global, puis enqueue un payload sérialisable dans RQ;
- `python -m app.workers.draft_worker` draine la queue;
- le worker recrée le provider depuis le compte sérialisé;
- Socket.IO utilise Redis comme `message_queue` quand la queue Redis est active,
  donc les événements `draft_ready` émis par un worker externe arrivent au
  process web;
- si Redis tombe, l'API revient à la queue mémoire sauf avec
  `DRAFT_QUEUE_REDIS_FAIL_CLOSED=true`.

Sur Railway, le même `railway.toml` sert au web et au worker. Le dispatcher
`scripts/railway_entrypoint.py` lance le web par défaut, saute Alembic pour les
workers, et expose un mini healthcheck dans `app.workers.draft_worker` pour que
le service worker passe `/api/health/strict`.

À garder pendant le dimensionnement :

1. Même en Redis, conserver `DRAFT_PER_ACCOUNT_QUEUE_MAX` pour éviter qu'un
   compte bruyant bloque les autres.
2. Dimensionner ensemble `DRAFT_RQ_WORKERS`, CPU/mémoire du service worker, et
   replicas Railway.
3. Tester par débit métier.
   La cible de capacité doit être exprimée en `drafts/minute`, par exemple :
   API p95 < 250 ms, draft ready p95 < 5 s, backpressure < 1 %.

## Mesure actuelle

Dernière mesure Railway mockée du 2026-05-27 :

- API mock : `3` replicas Railway sous Gunicorn `gthread`.
- Worker mock : `2` replicas Railway, `32` workers RQ au total observé.
- LLM et providers email : mockés.
- Trafic : environ `1 draft/minute/utilisateur`, durée `120s` par palier.

Résultat :

| Palier | Statut | Signal |
|---:|---|---|
| 12000 users | sain confirmé | 23964/23964 drafts complétés, 0 erreur, p95 prêt 595ms |
| 12500 users | échec dur | 5.25% erreurs client de connexion HTTPS |
| 13000 users | échec dur | 2.15% erreurs client de connexion HTTPS |
| 15000 users | échec dur | 16.71% erreurs client, p95 prêt 2300ms |

Interprétation : Redis/RQ n'est plus le goulot sur ce profil. La queue reste
vide, `run_p95` reste sous ~205ms, et il n'y a plus de `redis_lock_timeout`.
Le plafond mesuré vient de l'établissement des connexions HTTPS vers Railway ou
du générateur de charge mono-machine. Pour valider un objectif supérieur à
12000 utilisateurs concurrents, distribuer le load generator sur plusieurs
machines avant de conclure à une limite backend.

## Critère de migration

Migrer vers workers séparés quand le produit exige plus que ce qu'un process API
dimensionné verticalement peut tenir sans backpressure excessive, ou dès qu'on
déploie plusieurs instances API derrière un load balancer.
