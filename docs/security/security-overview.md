# Sécurité Agentys — page publique courte

Dernière mise à jour : 2026-05-16  
Statut : brouillon pour page publique ou annexe sécurité.

## Modèle de données email

Agentys Cloud est metadata-only par défaut. Les corps d'emails, HTML, pièces
jointes et snippets longs restent chez Gmail/Outlook/IMAP et sont récupérés
uniquement au moment où une fonctionnalité en a besoin. Le backend les traite en
mémoire et ne les écrit pas en base, fichier, log ou Sentry.

## OAuth et permissions

Agentys utilise OAuth pour Gmail et Outlook. L'utilisateur peut révoquer l'accès
depuis son fournisseur. Les scopes doivent rester limités aux fonctions visibles
dans l'interface : lecture, classement, brouillons, envoi demandé et
synchronisation.

## IA et entraînement

Les fournisseurs IA reçoivent du contenu seulement pour exécuter une action
utilisateur ou un job attendu : analyse de style, classement, génération de
brouillon. Agentys ne permet pas l'entraînement de modèles tiers avec les
données utilisateur en production.

## Chiffrement

- En transit : HTTPS/TLS entre client, API et fournisseurs.
- En production : PostgreSQL Railway chiffré au repos, plus chiffrement Fernet
  applicatif pour les tokens OAuth.
- En local desktop : SQLite SQLCipher et clé dans le trousseau du système.

## Rétention

Les métadonnées restent nécessaires à l'expérience inbox. Les artefacts IA
temporaires, brouillons, logs et caches sont soumis à TTL ou purge. Le script
`scripts/run_privacy_retention.py --redact-logs` applique la maintenance
privacy et la redaction historique bornée.

## Accès interne

L'accès production doit être réservé aux comptes nécessaires, avec MFA, revue
périodique, journalisation des actions admin et interdiction de consulter des
emails bruts sauf accord explicite de l'utilisateur ou obligation sécurité/loi.

## Sous-traitants

Le registre fournisseurs doit couvrir au minimum Google, Microsoft, Railway,
Vercel, le fournisseur IA actif et l'outil d'erreurs. Chaque entrée doit
indiquer la finalité, la catégorie de données, la région ou le transfert
possible, le DPA/SCC disponible et le contact sécurité.

## Incident response

Tout incident impliquant des renseignements personnels doit être trié selon son
risque, consigné dans un registre, notifié aux autorités/personnes concernées
quand requis, et suivi jusqu'à remédiation. Les logs d'incident doivent rester
redactés : pas de corps email, pas de tokens, pas de prompts libres.

## Références

- Politique privacy brouillon : [`privacy-policy.md`](privacy-policy.md)
- Inventaire email : [`email-data-inventory.md`](email-data-inventory.md)
- Chiffrement : [`data-at-rest.md`](data-at-rest.md)
- Registre fournisseurs : [`vendor-register.md`](vendor-register.md)
- Incident response : [`incident-response.md`](incident-response.md)
