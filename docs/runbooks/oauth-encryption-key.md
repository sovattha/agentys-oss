# Runbook — OAuth Encryption Key & Garde-fou boot

## Garde-fou dans `app/api/oauth.py`

Au boot, `oauth.py` vérifie que la clé de chiffrement des tokens OAuth n'est pas la valeur par défaut en prod. Il lève une `RuntimeError` qui empêche le démarrage si :

- `OAUTH_TOKEN_ENCRYPTION_KEY` est absent **ET**
- `SECRET_KEY` est absent ou égal à `"agentys-dev-secret-change-in-prod"` **ET**
- l'env indique la prod (`FLASK_ENV=production`, `ENVIRONMENT=production`, ou `RAILWAY_ENVIRONMENT=production`)

**Piège** : setter `SECRET_KEY` à la valeur par défaut littérale ne débloque rien — le garde-fou compare la string. Seul un `OAUTH_TOKEN_ENCRYPTION_KEY` truthy ou un `SECRET_KEY` différent le court-circuite.

## Réalité de la persistance des tokens OAuth

Contrairement à ce que laisse croire `_TOKENS_FILE` dans `oauth.py`, **aucun token OAuth n'est persisté entre deploys** :

- Le code hardcode `_TOKENS_FILE = /app/data/oauth_tokens.json`, **n'honore pas `AGENTYS_DATA_DIR`** → écrit dans le filesystem éphémère du container Railway.
- Le volume persistant `/data/agentys/` ne contient **aucun fichier de tokens OAuth**.
- `email_accounts.json` et `app/multi_accounts.py:AccountManager` **ne stockent pas** de tokens.
- Le fichier `.encryption_key` (44 bytes Fernet) dans le volume est utilisé par `app/infrastructure/security.py:EncryptionManager` pour l'anonymisation de l'historique, **pas pour OAuth**.

**Conséquence** : la rotation de `OAUTH_TOKEN_ENCRYPTION_KEY` est **indolore** (pas de re-OAuth forcé, pas de migration nécessaire) — rien à déchiffrer/rechiffrer.

## Rotation de la clé

```bash
# Générer une clé Fernet aléatoire
NEW_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Setter dans Railway (déclenche auto-redeploy)
railway variables --set "OAUTH_TOKEN_ENCRYPTION_KEY=$NEW_KEY"

# Vérifier
curl -sS https://agentys-backend-production.up.railway.app/api/health
```

## Reflex diagnostic crash boot Railway

1. `railway status --json` → extraire `latestDeployment.id` et `status`
2. Si `FAILED` : `railway logs --deployment <id>` (pas `railway logs` simple, qui renvoie les logs de l'ancien container encore vivant)
3. `railway logs --build` pour distinguer un échec build vs runtime
4. Inspection live : `railway ssh '<commande>'` fonctionne en non-interactif. User `root`, `sqlite3` CLI **absent** — utiliser `python3 -c` avec `sqlite3` stdlib pour la DB.
