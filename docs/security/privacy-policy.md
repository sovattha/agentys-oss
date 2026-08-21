# Politique de confidentialité — brouillon produit

Dernière mise à jour : 2026-05-16  
Statut : brouillon à publier sur `https://www.agentys.io/privacy` après revue légale.

Ce document décrit le comportement cible d'Agentys après le pivot
metadata-only. Il doit rester aligné avec l'ADR
[`0003-email-cloud-metadata-only`](../adr/0003-email-cloud-metadata-only.md) et
l'inventaire [`email-data-inventory.md`](email-data-inventory.md).

## Responsable du traitement

Agentys traite les données pour fournir l'assistant email connecté à Gmail,
Outlook ou IMAP. Le responsable de la protection des renseignements personnels
est la direction d'Agentys jusqu'à délégation écrite. Les coordonnées publiques
à afficher avant utilisateurs externes : `support@agentys.io` ou une boîte
dédiée `privacy@agentys.io` une fois créée.

## Données collectées

Agentys collecte uniquement les données nécessaires au produit :

- compte connecté : adresse email, fournisseur, identifiants provider,
  paramètres, avatar éventuel, état de synchronisation ;
- tokens OAuth Google/Microsoft chiffrés côté application ;
- métadonnées email : ID provider, thread ID, sujet, expéditeur,
  destinataires, date, dossier, labels, états lu/favori, présence de pièces
  jointes et signaux headers allowlistés ;
- artefacts IA minimisés : profil de style, règles abstraites, labels,
  métriques de génération, statuts de jobs, feedback structuré ;
- brouillons ou actions uniquement quand ils sont nécessaires à l'expérience
  utilisateur et soumis à rétention.

## Données non stockées par défaut

Agentys Cloud ne stocke pas par défaut :

- le corps texte ou HTML des emails ;
- les pièces jointes ou leurs contenus ;
- les snippets longs dérivés du corps ;
- les headers libres contenant URLs, tokens ou valeurs arbitraires ;
- les prompts complets, critiques, exemples de style non anonymisés ou
  historiques de brouillons contenant le contenu original.

Le contenu complet est lu depuis Gmail/Outlook/IMAP à la demande, traité en
mémoire pendant la requête ou le job, puis oublié. Un futur cache cloud complet
nécessiterait un opt-in explicite, une nouvelle ADR, une durée de conservation
et une mise à jour de cette politique avant activation.

## Utilisation des données

Les données servent à :

- afficher la boîte de réception et les vues de travail ;
- classer les emails et appliquer les règles choisies par l'utilisateur ;
- générer ou améliorer des brouillons ;
- apprendre un style d'écriture sous forme minimisée ;
- détecter les erreurs, abus, quotas et incidents opérationnels.

Les données Gmail/Outlook ne sont pas vendues. Elles ne sont pas utilisées pour
entraîner des modèles publics ou tiers par défaut.
`AGENTYS_ALLOW_THIRD_PARTY_AI_TRAINING=true` est refusé en production.

## Fournisseurs et transferts

Agentys peut communiquer des données aux catégories de fournisseurs suivantes,
uniquement pour fournir ou sécuriser le service :

- Google ou Microsoft pour OAuth, Gmail, Outlook et les actions email ;
- Railway pour l'API backend et PostgreSQL ;
- Vercel pour le frontend web ;
- fournisseurs IA configurés pour génération ou analyse éphémère ;
- Sentry ou outils similaires pour erreurs, avec redaction des secrets et
  champs de contenu email.

Ces fournisseurs peuvent opérer hors Québec ou hors Union européenne. Les
transferts doivent être documentés dans le registre fournisseurs avant ouverture
à des utilisateurs externes.

## Conservation et suppression

La base cloud conserve les métadonnées et artefacts minimisés tant qu'ils sont
nécessaires au compte. Les artefacts IA et brouillons temporaires expirent via
les durées configurées dans le backend.

L'utilisateur peut supprimer les données Agentys d'un compte via :

```http
DELETE /api/privacy/accounts/<account_id>/data
{"confirm":"DELETE"}
```

La suppression couvre le compte, les métadonnées associées, les labels, les
artefacts IA, les trackers, les tokens et les caches applicatifs connus.

## Accès, portabilité et rectification

Les données visibles dans l'application peuvent être consultées et modifiées
dans les paramètres, labels, brouillons et vues de compte. Une exportation des
données Agentys stockées est disponible via :

```http
GET /api/privacy/accounts/<account_id>/data
```

L'export omet volontairement les corps d'emails, snippets longs, headers libres,
tokens et prompts complets, car ces données ne doivent pas être conservées dans
Agentys Cloud en mode metadata-only.

Les utilisateurs peuvent aussi révoquer l'accès OAuth directement depuis Google
ou Microsoft.

## Références réglementaires vérifiées

- Commission d'accès à l'information du Québec — Loi 25, responsable,
  transparence, incidents et portabilité :
  <https://www.cai.gouv.qc.ca/protection-renseignements-personnels/sujets-et-domaines-dinteret/principaux-changements-loi-25>
- Commission européenne — droits RGPD des personnes :
  <https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en>
- Google API Services User Data Policy — disclosures, privacy policy et
  minimisation des permissions :
  <https://developers.google.com/terms/api-services-user-data-policy>
