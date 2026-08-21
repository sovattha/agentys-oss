# Migrer la prod Railway vers PostgreSQL

Objectif : déplacer la base principale SQLAlchemy (`accounts`, `emails`,
`contacts`, `drafts`, `onboarding_results`, etc.) de SQLite/SQLCipher vers
PostgreSQL, sans changer la base locale/desktop par défaut.

## Ce qui migre

- Migre : tables déclarées dans `app.db.models.Base`.
- Ne migre pas encore : stores SQLite legacy dans `app.infrastructure.database`
  et caches SQLite dédiés (`tts_cache`, `template_label_cache`, etc.).

Cette phase réduit le verrou global sur les tables critiques (`emails`,
`accounts`, onboarding), mais les stores legacy restent à migrer séparément.

## Préparation

1. Ajouter un service PostgreSQL dans le projet Railway `agentys-backend`.
2. Noter l'URL interne Railway, mais ne pas encore l'exposer au backend.
3. Installer la dépendance côté image via le déploiement qui contient
   `psycopg[binary]`.
4. Garder `AGENTYS_ENCRYPTION_KEY` en place pendant la migration : le script
   doit pouvoir lire la DB source SQLCipher. Ne pas utiliser `AGENTYS_DB_PATH`
   comme fallback runtime en production ; depuis la bascule Postgres, le
   backend refuse de booter sans `DATABASE_URL`.

## Dry-run sur cible jetable

Créer une DB PostgreSQL vide puis lancer :

```bash
railway ssh 'python scripts/migrate_sqlite_to_postgres.py --target "<postgres-url>" --dry-run'
```

Le dry-run vérifie l'ouverture SQLite/SQLCipher et compte les lignes source par
table. Il ne modifie pas PostgreSQL.

## Import

Sur une fenêtre courte, éviter les nouvelles écritures pendant l'import :

```bash
railway ssh 'python - <<'"'"'PY'"'"'
from pathlib import Path
from shutil import copy2
from datetime import datetime

src = Path("/data/agentys/agentys.db")
dst = src.with_suffix(f".backup-{datetime.utcnow():%Y%m%d-%H%M%S}.db")
copy2(src, dst)
print(dst)
PY'
```

Puis importer :

```bash
railway ssh 'python scripts/migrate_sqlite_to_postgres.py --target "<postgres-url>" --truncate-target'
```

Le script :

- crée le schéma PostgreSQL depuis les modèles SQLAlchemy ;
- copie par batchs ;
- vérifie les counts table par table ;
- remet les séquences PostgreSQL au bon `MAX(id)` ;
- stamp `alembic_version` sur la tête courante.

## Bascule backend

Après import réussi :

```bash
railway variables --set DATABASE_URL="<postgres-url>"
```

L'application utilise PostgreSQL uniquement quand `DATABASE_URL` est présent.
En production Railway, l'absence de `DATABASE_URL` est fatale : le backend
refuse de retomber sur SQLite/SQLCipher pour éviter des écritures partagées
entre deux bases.

## Smoke tests

```bash
curl -fsS https://api.agentys.io/api/health/strict
railway logs --deployment <latest-id> --lines 200
```

Vérifier ensuite dans l'app :

- login OAuth ;
- chargement inbox ;
- onboarding `Réessayer` ;
- génération de draft ;
- sync Gmail/Outlook sur un compte réel.

## Rollback

Rollback immédiat :

```bash
railway rollback
```

Ne jamais faire `railway variables --unset DATABASE_URL` en production pour
"revenir sur SQLite" : le backend refusera de booter. Restaurer plutôt un
snapshot PostgreSQL ou redéployer un commit précédent qui pointe toujours vers
la même base Postgres. Ce plan n'installe pas de dual-write.
