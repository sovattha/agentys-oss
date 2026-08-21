# ADR 0003 — Email cloud metadata-only par défaut

- **Statut** : Accepté
- **Date** : 2026-05-15
- **Auteur** : Nat + Codex
- **Contexte lié** : pivot privacy-first, Loi 25, RGPD, SOC 2, ISO 27001,
  Google API Services User Data Policy

## Contexte

Agentys manipule des emails Gmail/Outlook via OAuth. Le modèle historique
stocke une copie serveur de données très sensibles : corps texte/HTML,
snippets, en-têtes bruts, brouillons IA, historique de drafts et artefacts
d'apprentissage. Cette approche facilite la recherche et l'IA, mais elle fait
d'Agentys Cloud un dépositaire de contenu email complet.

Ce niveau de rétention augmente fortement le risque sécurité et conformité :
impact incident plus large, droit à l'effacement plus difficile, revues CASA /
restricted scopes plus exigeantes, et surface SOC 2 / ISO 27001 plus lourde.

La décision produit est de privilégier la confiance et la conformité : le cloud
ne doit pas devenir l'archive email secondaire de l'utilisateur.

## Décision

Agentys Cloud passe en **metadata-only par défaut** pour le contenu email.

### D1 — Pas de corps email brut stocké côté cloud par défaut

En production, Agentys Cloud ne persiste pas les corps entrants/sortants bruts :

- pas de `emails.body_text` ;
- pas de `emails.body_html` ;
- pas de snippet long ou aperçu dérivé du corps par défaut ;
- pas de pièces jointes ni noms de fichiers sensibles ;
- pas d'en-têtes RFC complets non filtrés.

Le cloud peut conserver les métadonnées nécessaires au produit : identifiants
provider, `thread_id`, `account_id`, dates, états lu/starred/dossier/label,
expéditeur/destinataires, état des jobs, checkpoints de sync, quotas et
artefacts de classification.

### D2 — Lecture du contenu à la demande

Quand l'utilisateur ouvre un email ou demande une action IA, Agentys récupère le
contenu depuis le provider via OAuth, dans le scope du compte demandé.

Le backend peut agir comme proxy éphémère pour l'app web, mais le contenu reste
en mémoire volatile et n'est pas écrit en base, fichier, log ou cache disque
côté cloud. Pour la performance, le cache long terme du contenu doit vivre côté
appareil utilisateur, chiffré, avec TTL.

### D3 — Recherche sans index cloud du corps

La recherche full-text serveur sur `body_text` est dépréciée. Les alternatives
cibles sont :

- recherche provider Gmail/Outlook ;
- index local chiffré côté appareil ;
- recherche cloud limitée aux métadonnées non sensibles.

### D4 — IA éphémère, mémoire minimisée

Les agents IA peuvent traiter le contenu email en mémoire pour générer une
classification, une réponse ou une action. Les données durables doivent être
minimisées :

- labels, scores, catégories et décisions sans corps brut ;
- profils de style ou règles sous forme de métriques/résumés anonymisés ;
- `source_message_id`, finalité, date de création et TTL pour toute mémoire IA ;
- scrub PII avant tout artefact durable ;
- pas d'entraînement de modèles tiers avec données utilisateur par défaut
  (`AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING=false`, refusé en production si activé).

Les brouillons générés sont aussi des données personnelles. Le stockage cible
est soit le dossier Drafts du provider, soit une rétention Agentys explicite et
courte, liée à une action utilisateur.

### D5 — Mode legacy uniquement transitoire

Un mode `legacy_full_cache` peut exister pour migration, tests ou usage local
contrôlé. Il ne doit pas être le défaut de production. En production, une config
qui demanderait le stockage complet doit échouer sans opt-in explicite et audit.

## Conséquences

### Positives

- Moins de contenu sensible en base cloud.
- Blast radius réduit en cas d'incident.
- Story conformité plus claire : Agentys orchestre et assiste, mais n'archive
  pas la mailbox.
- Meilleure cohérence avec la minimisation des données Loi 25 / RGPD.
- Moins de friction pour SOC 2, ISO 27001 et revues Google restricted scopes.

### Négatives

- `GET /api/emails/<id>` ne peut plus supposer que le body est en DB.
- La recherche serveur dans le corps doit être remplacée.
- Le learning actuel qui lit des emails historiques doit être revu.
- Certaines règles de labels / Quick Steps basées sur le body devront fetcher
  à la demande ou devenir opt-in/locales.
- La latence d'ouverture email dépend davantage du provider et du cache local.

## Plan d'application

1. Inventorier toutes les surfaces qui stockent ou exposent du contenu email.
2. Ajouter un contrat runtime `AGENTYS_EMAIL_CONTENT_STORAGE_MODE`.
3. Adapter l'ingestion pour écrire metadata-only par défaut.
4. Remplacer les lectures DB du body par un fetch provider éphémère.
5. Déplacer recherche et cache body vers provider/local encrypted cache.
6. Minimiser les artefacts IA persistés.
7. Purger les corps historiques, reconstruire les index dérivés, et ajouter
   des tests de non-rétention.
8. Exécuter la rétention via `scripts/run_privacy_retention.py --redact-logs`
   et utiliser `DELETE /api/privacy/accounts/<account_id>/data` pour le droit à
   l'effacement côté Agentys.

## Non-objectifs

- Supprimer OAuth Gmail/Outlook.
- Promettre zéro donnée personnelle en cloud : les métadonnées email restent
  des données personnelles.
- Implémenter immédiatement BYOK/CMEK.
- Stocker les pièces jointes chez Agentys.

## À reconsidérer

- Si un segment entreprise exige une recherche serveur ultra-rapide dans le
  corps, réouvrir l'ADR avec un opt-in explicite, chiffrement fort, TTL,
  isolation tenant, journalisation d'accès et contrat de traitement dédié.
- Si l'app web ne peut pas offrir une UX acceptable sans cache cloud, privilégier
  d'abord un cache local chiffré et du préchargement provider borné.
