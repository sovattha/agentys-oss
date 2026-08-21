# Nightly UX Inspection — Agentys

Tu es un **utilisateur innocent** qui decouvre l'app Agentys pour la premiere fois.
Teste chaque section et documente les problemes.

## Configuration

- **Frontend**: variable `TARGET_FRONTEND` (defaut: `http://localhost:1420`)
- **Backend**: variable `TARGET_BACKEND` (defaut: `http://127.0.0.1:5050`)
- **Label**: variable `TARGET_LABEL` (LOCAL ou STAGING)
- **Fichier rapport**: variable `REPORT_FILE`

## REGLE CRITIQUE : economie de tokens

- **JAMAIS** utiliser `browser_snapshot` (DOM complet = enorme). Utilise `browser_take_screenshot` a la place.
- Collecter console_messages et network_requests une SEULE fois a la fin, pas apres chaque section.
- Pas de Lighthouse (trop couteux). On le fera dans un run separe.
- Ecrire le rapport avec le tool `Write` vers REPORT_FILE (pas sur stdout) pour qu'il persiste meme si le budget expire.

## Phase de setup

1. Obtiens un JWT via Bash :
   ```bash
   curl -s -X POST http://127.0.0.1:5050/api/auth/dev-login -H "Content-Type: application/json" -d '{"email":"nightly-test@agentys.local"}'
   ```
   Recupere le `access_token`.

2. Navigue vers le frontend avec `browser_navigate`
3. Injecte le token via `browser_evaluate` :
   ```javascript
   localStorage.setItem('agentys_jwt', '<TOKEN>');
   location.reload();
   ```
4. Attends le chargement de l'inbox

## Sections a tester (DANS L'ORDRE)

Pour chaque section : screenshot + noter les problemes visuels/UX.

### 1. Inbox
- Verifie le chargement de la liste d'emails
- Clique sur un email si present
- Screenshot

### 2-7. Dossiers sidebar
Teste chacun rapidement (clic sidebar, attendre, screenshot) :
- Brouillons
- Envoyes
- Archive
- Spam
- Corbeille
- Snoozed

### 8. Parametres
- Ouvre les parametres (icone engrenage)
- Navigue les 6 sous-sections : Compte, Agentys AI, Outils, Productivite, Automatisation, General
- 1 screenshot pour la premiere et la derniere sous-section

### 9. Composer un email
- Clique sur le bouton composer ou touche N
- Verifie que la modale s'ouvre
- Screenshot
- Ferme

### 10. Recherche
- Clique sur la barre de recherche, tape "test"
- Screenshot

### 11. Palette de commandes
- Ctrl+K, verifie l'ouverture
- Screenshot, ferme

### 12. Sprint / Deep Focus
- Clique l'icone eclair
- Screenshot, ferme

## Apres tous les tests

1. `browser_console_messages` — recupere tout
2. `browser_network_requests` — recupere tout
3. Filtre : garde console.error, console.warn, requetes 4xx/5xx/timeout
4. Ignore : favicon 404, HMR websocket, extensions navigateur

## Ecriture du rapport

Utilise le tool `Write` pour ecrire le rapport COMPLET dans le fichier `REPORT_FILE` avec cette structure :

```markdown
# Nightly UX Report — [DATE] — [TARGET_LABEL]

## Resume
- Cible: [URL]
- Sections testees: X/12
- Console errors: X | Warnings: X
- Requetes echouees: X
- Issues critiques: X | Importantes: X | Mineures: X

## Issues critiques
### [CRIT-1] Titre
- Section: ...
- Description: (max 2 phrases)
- Suggestion: ...

## Issues importantes
### [IMP-1] Titre
...

## Issues mineures
### [MIN-1] Titre
...

## Console Errors
| # | Type | Message | Source |
|---|------|---------|--------|

## Requetes echouees
| # | URL | Status | Methode |
|---|-----|--------|---------|
```

## Regles

- JAMAIS modifier de fichier code
- JAMAIS utiliser browser_snapshot (trop de tokens)
- Ecrire le rapport via Write tool (pas stdout)
- Si une section echoue, noter et passer a la suivante
- Max 2 phrases par issue
