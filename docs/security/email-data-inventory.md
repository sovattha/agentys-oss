# Inventaire des données email — pivot metadata-only

Date : 2026-05-15  
Décision source : [ADR 0003](../adr/0003-email-cloud-metadata-only.md)

## Objectif

Identifier les endroits où Agentys stocke, indexe ou expose du contenu email
afin de migrer le cloud vers un modèle metadata-only. Cet inventaire sert de
checklist pour les phases d'implémentation et de purge.

## Classification cible

- **Metadata cloud** : conservable côté serveur, tout en restant donnée
  personnelle.
- **Artefact IA minimisé** : conservable seulement si réduit, utile, traçable
  et effaçable.
- **Local-only** : cache chiffré côté appareil utilisateur.
- **Éphémère** : mémoire RAM pendant une requête/job, sans persistance.
- **Purge / TTL** : à supprimer ou expirer rapidement.
- **Opt-in** : stockage complet possible seulement avec consentement explicite.

## Matrice données

| Surface | État actuel | Classe cible | Action |
| --- | --- | --- | --- |
| `emails.body_text` | Corps texte persisté dans `app/db/models/email.py`, alimenté par `sync_service` et onboarding. | Éphémère / local-only | Ne plus écrire en mode `metadata_only`; purger l'historique. |
| `emails.body_html` | Corps HTML persisté et renvoyé par `to_dict_full()`. | Éphémère / local-only | Fetch provider à l'ouverture; pas de persistance cloud. |
| `emails.snippet` | Aperçu dérivé du contenu, stocké jusqu'à 500 chars et fallback depuis `body_text`. | Local-only ou aperçu court opt-in | Traiter comme contenu, pas comme metadata neutre. |
| `emails.raw_headers` | JSON d'en-têtes RFC, parfois backfill depuis provider. | Metadata cloud allowlist | Allowlist stricte en place. Les signaux presence-only (`list-unsubscribe`, `x-auto-response-suppress`) sont réduits à `present` pour ne pas stocker URLs/tokens. |
| `emails.attachments_meta` | JSON libre; peut contenir noms de fichiers. | Metadata cloud minimale | Garder `has_attachments`, nombre, types génériques; éviter noms de fichiers. |
| `emails.subject` | Sujet stocké et indexé. | Metadata cloud sensible | Garder pour l'UX, mais inclure export/suppression et éviter logs longs. |
| `emails.sender`, `recipients`, `cc`, `bcc` | Adresses persistées. | Metadata cloud sensible | Garder si nécessaire; vérifier minimisation de `bcc` et affichages. |
| `emails.deadline_at`, `emoji_marker_json`, labels, folder, read/starred | États dérivés et organisation. | Metadata cloud / artefact IA minimisé | Garder; garantir suppression par compte. |
| `emails_fts.body_text` | Index FTS SQLite sur le corps via migration `002_fts5_search`. | Purge / remplacé | Migration `030_purge_email_content_cache` reconstruit l'index après purge des bodies. |
| `drafts.body_text`, `drafts.body_html` | Brouillons IA stockés en DB. | TTL / provider Drafts / opt-in | Préférer provider Drafts; sinon rétention courte et action utilisateur explicite. |
| `drafts.generation_prompt`, `user_edits`, `feedback_notes` | Instructions et retours libres. | Artefact IA minimisé / TTL | En `metadata_only`, ces champs ne sont plus écrits via `DraftRepository`, sont masqués à la sérialisation, et la migration `030` purge les anciennes valeurs. |
| `draft_history.email_body`, `draft_v1`, `critique`, `draft_final` | Historique complet legacy dans `app/infrastructure/database.py`, `SqliteDraftHistoryAdapter` et le JSON legacy. | Purge / métriques | Nouvelles écritures minimisées en `metadata_only`; migration `030_purge_email_content_cache` met les anciens contenus à `NULL` en gardant ids, statuts, tokens et feedback. |
| `draft_feedback.note` | Note libre utilisateur, sans corps par défaut. | Artefact IA minimisé / TTL | Garder avec longueur courte, suppression et TTL. |
| `draft_edit_events` | Stocke catégorie, magnitude, longueurs, intent, recipient. | Artefact IA minimisé | Bon pattern; éviter d'ajouter diff texte. |
| `pending_draft_store` / `PendingDraft.email_body`, `draft_body`, `draft_v1` | Store UI de drafts avec contenu. | TTL / provider Drafts | En `metadata_only`, le fichier disque garde temporairement le draft final mais supprime `email_body`, `conversation_history`, `draft_v1`, `critique` et `pipeline_summary`; les fichiers legacy sont minimisés au chargement. Les brouillons actifs expirent par défaut après 30 jours (`AGENTYS_PENDING_DRAFT_ACTIVE_RETENTION_DAYS`) et les statuts terminaux après 30 jours (`AGENTYS_PENDING_DRAFT_TERMINAL_RETENTION_DAYS`). |
| `sent_emails.body_preview` | Aperçu legacy de follow-up. | Purge / metadata minimale | En `metadata_only`, les repositories/adapters n'écrivent plus l'aperçu, les anciennes lignes sont masquées à la lecture, et la migration `030` purge `body_preview`. |
| `learned_patterns.examples`, `correction` | Exemples et corrections libres. | Artefact IA minimisé | En `metadata_only`, les `examples` SQLite et JSON legacy ne sont plus écrits ni exposés; la migration purge SQLite et `JsonLearningPatternStore` réécrit les anciens fichiers à l'ouverture. `trigger` / `correction` restent comme règles abstraites. |
| `draft_corrections/<account_id>.json` / `DraftLearningStore` | Corrections de brouillons, exemples positifs, instructions refine, clics smart suggestion. | Artefact IA minimisé / TTL | En `metadata_only`, `original`, `sent`, snippets, sujets, before/after et textes de suggestions ne sont plus persistés ni injectés dans les prompts; seuls compteurs, contacts, résumés abstraits et règles restent. Les traces datées expirent via `AGENTYS_AI_ARTIFACT_RETENTION_DAYS` (90 jours par défaut). |
| `data/corrections/{corrections,patterns}.json` / `DraftCorrectionManager` | Corrections utilisateur et patterns exacts de remplacement. | Artefact IA minimisé / TTL | En `metadata_only`, les brouillons originaux/corrigés, sujets, sender brut et remplacements exacts ne sont plus persistés; seuls contextes minimisés et changements de ton abstraits restent. Les corrections datées expirent via `AGENTYS_AI_ARTIFACT_RETENTION_DAYS`; les patterns abstraits restent durables. |
| `style_profile_<account_id>.json` / `ReferenceExample.body_excerpt` | Exemples de style anonymisés côté fichier. | Artefact IA minimisé / TTL | En `metadata_only`, le store refuse les exemples non anonymisés et ne persiste plus `body_excerpt` ni `subject`, même anonymisés. Il conserve seulement les métriques (`length_bucket`, `word_count`), `source_email_id` comme provenance metadata, et expire les exemples via `AGENTYS_AI_ARTIFACT_RETENTION_DAYS` (90 jours par défaut). |
| `contacts.summary_json` | Résumé relationnel dérivé des échanges email, avec sujets, formules exactes, faits et dernière interaction. | Artefact IA minimisé | En `metadata_only`, seuls `relation_type`, `habitual_tone` et `language` allowlistés sont écrits, lus et injectés; la migration `030` réduit aussi les anciens résumés. |
| `knowledge_entries.content` | Savoir durable par compte. | Opt-in / artefact IA minimisé | Distinguer saisie manuelle vs extraction email; extraction email avec consentement et scrub. |
| `recipient_profiles.disc_scores_json` | Scores dérivés par contact. | Artefact IA minimisé | Garder si explicable et effaçable; pas d'extraits texte. |
| `template_label_cache` fingerprint body prefix | Fingerprint basé historiquement sur sender/subject/body prefix. | Artefact minimisé | En `metadata_only`, le fingerprint n'inclut plus le body prefix; le mode legacy garde l'ancien comportement pour migration locale. |
| Logs backend, Sentry, analytics frontend | Risque de fuite via exceptions, payloads et snippets. | Éphémère / metadata | Logs évidents nettoyés pour body/snippet/sujet. Le redactor global masque les champs de contenu email connus dans les logs Python, tracebacks et payloads Sentry; `scripts/run_privacy_retention.py --redact-logs` réécrit les logs texte historiques bornés. |
| Cache local Tauri / navigateur | Variable selon stores locaux. | Local-only chiffré | Chiffrer, TTL, suppression utilisateur, pas de sync cloud du body. |

## Matrice endpoints et services

| Surface | Dépendance actuelle au contenu cloud | Action cible |
| --- | --- | --- |
| `GET /api/emails` | Liste lit `snippet` et peut fallback `body_text[:150]`. | Liste metadata-only; snippet local/provider uniquement. |
| `GET /api/emails/<id>` | Lit la DB metadata puis fetch provider si aucun body affichable n'est en cache. | En `metadata_only`, le list-cache headers-only ne court-circuite plus l'ouverture; le provider est fetché en ligne, le corps est retourné au client/cache mémoire, et `body_text` / `body_html` / `snippet` restent non persistés. |
| `_fetch_body_html_background` | Backfill historique du body en DB pour casser les boucles. | En `metadata_only`, met à jour uniquement le cache mémoire/événements et ne persiste pas `body_text`, `body_html` ni `snippet`. |
| `POST /api/emails/<id>/process`, `/draft`, `/preview` | Agents lisent le body depuis provider avant génération. | Fetch provider en mémoire, générer, puis ne persister que l'artefact autorisé (`PendingDraftStore` minimise les traces intermédiaires). |
| `app/services/search_service.py` | FTS/LIKE sur `body_text`, snippets de résultat. | Cloud metadata search seulement en `metadata_only`; provider search ou index local chiffré à brancher pour la recherche dans le corps. |
| `app/api/search.py` fallback provider | Upsert headers-only déjà présent, mais snippets restent utilisés. | Garder fallback provider, ne pas hydrater body cloud. |
| Onboarding deep training | Écrit `body_text`, `body_html`, snippets, puis analyse les bodies. | Lire provider en stream/batches éphémères, persister profils minimisés. |
| Writing style / style inference | Sélectionne exemples depuis `body_text`. | Features anonymisées, aucun exemple brut sans anonymisation prouvée; exemples datés, sourcés par ID provider, puis expirés en `metadata_only`. |
| Contact history / summaries / relationship detection | Lit `body_text` ou `snippet`. | `contacts.summary_json` est réduit aux labels abstraits en `metadata_only`; la suppression de compte cascade les lignes DB et purge les artefacts fichier associés. Les surfaces contact map restent metadata-only/opt-in. |
| Labeling / Quick Steps body rules | Certaines règles analysent `body` / `body_html`. | Analyse éphémère au moment sync/detail; stocker résultat, pas source. |
| Contact map | Construit historiquement des textes depuis sujet + body pour géocoder et afficher des snippets. | En `metadata_only`, ne scanne plus sujet/body, n'expose plus de snippet de contenu, et retombe seulement sur les métadonnées de contacts + fallback TLD. |
| Mobile companion drafts / outbox offline | Peut transporter des brouillons et corps d'envoi localement. | Aucun cache cloud; la session drive ne stocke que compte/index, et la queue offline SecureStore expire les corps d'envoi après 7 jours. |

## Ordre d'implémentation recommandé

1. Ajouter `AGENTYS_EMAIL_CONTENT_STORAGE_MODE=metadata_only` par défaut.
2. Faire échouer la prod si `legacy_full_cache` est activé sans opt-in explicite.
3. Modifier l'ingestion pour ne plus écrire `body_text` / `body_html` /
   snippet long.
4. Ajouter les tests de non-rétention sur sync, search upsert et onboarding.
5. Adapter le détail email pour fetch provider en mémoire.
6. Remplacer search body par provider/local index. Le cloud `metadata_only`
   refuse déjà les filtres `body:` / `contenu:` et ne scanne plus
   `emails.body_text`.
7. Réduire learning/drafts/history avec TTL et scrub PII. `draft_history`
   ne persiste déjà plus les contenus source/drafts en `metadata_only`.
8. Écrire migration de purge avec dry-run counts avant prod.

## Tests attendus

- Sync metadata-only : un email entrant crée une ligne `emails` sans body.
- Détail metadata-only : ouverture email fonctionne et ne met pas à jour
  `body_text` / `body_html`.
- Search provider fallback : n'écrit pas de contenu cloud.
- Draft IA : body lu en mémoire, draft final stocké seulement selon policy.
- Draft history : `email_body`, `draft_v1`, `critique`, `draft_final` ne sont
  pas persistés en `metadata_only`, et les métriques restent disponibles.
- Onboarding : aucun exemple de style non anonymisé n'est persisté, et les
  exemples anonymisés expirent via `AGENTYS_AI_ARTIFACT_RETENTION_DAYS`.
- Rétention : `scripts/run_privacy_retention.py --redact-logs` applique la
  rétention des pending drafts, learning/corrections/style profiles et redaction
  des logs texte.
- Suppression : `DELETE /api/privacy/accounts/<account_id>/data` avec
  `{"confirm":"DELETE"}` délègue à la suppression de compte et purge aussi
  pending drafts, profils de style, learning/corrections IA, trackers, tokens,
  labels et logs applicatifs redacted.
- Purge : les colonnes historiques de contenu passent à `NULL` sans supprimer
  ids provider/thread/labels, et `emails_fts` ne matche plus l'ancien body.
- Logs : test contractuel qui échoue si un body/snippet long est loggué.
- Audit rétention : `scripts/audit_email_content_retention.py` échoue si un
  champ de contenu email réapparaît dans les stores JSON ou dans les colonnes
  DB metadata-only.
- Sentinelle prod : `.github/workflows/email-retention-sentinel.yml` appelle
  `/api/_internal/email-retention-audit` avec `OBSERVABILITY_TOKEN`, exécute
  l'audit dans le conteneur Railway et ouvre une issue `auto-sentinelle` si
  des findings ou une perte de couverture apparaissent.

## Politique fournisseurs IA

- `AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING` est `false` par défaut.
- `validate_config()` refuse `AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING=true` en
  production.
- Les exports d'entraînement depuis `draft_history` retournent une liste vide
  en `metadata_only`.
- Les intégrations IA traitent le contenu email comme donnée éphémère : aucune
  mémoire longue durée ne doit conserver de body, prompt libre ou exemple non
  anonymisé.
