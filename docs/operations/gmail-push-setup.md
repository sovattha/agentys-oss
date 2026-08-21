# Gmail Pub/Sub push — setup opérationnel (N3)

Cette intégration remplace le polling Gmail toutes les 120 secondes par un
webhook déclenché par Google à chaque changement de boîte. Avant que ça
fonctionne en prod, il y a une **mise en place GCP one-shot** à faire dans la
Google Cloud Console.

> Une fois la config GCP en place, le code s'auto-bootstrap : Railway pousse,
> on appelle `POST /api/gmail/watch/start` une fois par compte connecté, et
> un cron quotidien tape `POST /api/gmail/watch/renew-due` pour régénérer
> les watches qui expirent dans les 24h.

## 1. Côté Google Cloud Console

### 1.1 — Créer un topic Pub/Sub

```bash
gcloud pubsub topics create agentys-gmail \
  --project=<gcp-project-id>
```

### 1.2 — Donner à Gmail le droit de publier

Le service account interne Gmail (`gmail-api-push@system.gserviceaccount.com`)
doit avoir `roles/pubsub.publisher` sur le topic, sinon `users.watch()`
échoue immédiatement.

```bash
gcloud pubsub topics add-iam-policy-binding agentys-gmail \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher" \
  --project=<gcp-project-id>
```

### 1.3 — Créer un service account dédié pour signer les push

```bash
gcloud iam service-accounts create agentys-pubsub-pusher \
  --display-name="Agentys Pub/Sub OIDC push" \
  --project=<gcp-project-id>
```

Récupérer son email (`agentys-pubsub-pusher@<project>.iam.gserviceaccount.com`).

### 1.4 — Créer la subscription "push" vers Railway

```bash
gcloud pubsub subscriptions create agentys-gmail-push \
  --topic=agentys-gmail \
  --push-endpoint="https://agentys-backend-production.up.railway.app/api/gmail/push" \
  --push-auth-service-account="agentys-pubsub-pusher@<project>.iam.gserviceaccount.com" \
  --push-auth-token-audience="https://agentys-backend-production.up.railway.app/api/gmail/push" \
  --ack-deadline=20 \
  --project=<gcp-project-id>
```

L'audience doit **exactement** correspondre à ce que vérifie le backend
(`GMAIL_PUSH_AUDIENCE`).

## 2. Côté Railway (variables d'environnement)

```bash
railway variables set GMAIL_PUSH_TOPIC="projects/<gcp-project-id>/topics/agentys-gmail"
railway variables set GMAIL_PUSH_AUDIENCE="https://agentys-backend-production.up.railway.app/api/gmail/push"
railway variables set GMAIL_PUSH_SERVICE_ACCOUNT="agentys-pubsub-pusher@<project>.iam.gserviceaccount.com"
```

## 3. Activer le watch pour un compte connecté

Une fois les variables propagées (un déploy Railway suffit) :

```bash
curl -X POST https://agentys-backend-production.up.railway.app/api/gmail/watch/start \
  -H "Authorization: Bearer <user-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"account_id": 42}'
```

Réponse attendue :

```json
{
  "status": "ok",
  "history_id": "1234567",
  "expiration": "2026-04-23T00:00:00+00:00",
  "topic": "projects/<gcp-project-id>/topics/agentys-gmail"
}
```

## 4. Cron de renouvellement

Gmail expire les watches après 7 jours. Programmer un cron quotidien (Railway
scheduler ou GitHub Actions) qui tape :

```bash
curl -X POST https://agentys-backend-production.up.railway.app/api/gmail/watch/renew-due \
  -H "Authorization: Bearer <admin-jwt>"
```

Le endpoint regarde tous les comptes Gmail actifs dont le watch expire dans
les 24h et appelle `users.watch()` à nouveau (idempotent côté Gmail).

## 5. Désactiver

```bash
curl -X POST https://agentys-backend-production.up.railway.app/api/gmail/watch/stop \
  -H "Authorization: Bearer <user-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"account_id": 42}'
```

## 6. Validation locale

Le webhook valide chaque requête en vérifiant le JWT OIDC signé par Google
(audience + service account). Sans `GMAIL_PUSH_AUDIENCE` configurée, le
endpoint refuse tout et log un warning — c'est volontaire pour éviter un
relais ouvert.

## 7. Migration

La migration DB ajoute deux colonnes à `accounts` :

- `gmail_watch_expiration` (DateTime, nullable)
- `gmail_watch_topic` (String 512, nullable)

Le schema migrator auto-applique le diff au démarrage (visible dans les logs :
`Schema migration: added column accounts.gmail_watch_expiration`).

## 8. Effet attendu

Avant : poll toutes les 120s → 720 polls/jour/compte → quota Gmail consommé
même quand rien ne bouge.

Après : 0 poll. Une push notification arrive ~1-2s après l'événement réel.
Sync incrémental ciblé via History API → réduction massive des 429.
