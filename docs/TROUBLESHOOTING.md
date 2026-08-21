# Guide de Troubleshooting - Agentys

## Table des matieres
1. [Erreurs d'authentification](#erreurs-dauthentification)
2. [Erreurs IMAP/SMTP](#erreurs-imapsmtp-recommandé)
3. [Erreurs API LLM](#erreurs-api-llm)
4. [Problemes de performance](#problèmes-de-performance)
5. [Erreurs de configuration](#erreurs-de-configuration)
6. [Problemes de base de donnees](#problèmes-de-base-de-données)
7. [Problemes d'affichage des emails](#problemes-daffichage-des-emails)
8. [Logs et diagnostic](#logs-et-diagnostic)

---

## Erreurs d'authentification

### Gmail - `token.json` invalide ou corrompu

**Symptôme:**
```
Error: Failed to authenticate with Gmail API
Invalid credentials or token expired
```

**Solution:**
1. Supprimer le fichier `token.json`
2. Relancer l'application
3. Suivre le flux d'authentification OAuth dans le navigateur

```bash
rm token.json
python run_daemon.py
```

### Gmail - Erreur `invalid_grant`

**Symptôme:**
```
google.auth.exceptions.RefreshError: ('invalid_grant', ...)
```

**Causes possibles:**
- Token révoqué dans Google Account
- Changement de mot de passe récent
- Token expiré depuis plus de 7 jours

**Solution:**
1. Accéder à [https://myaccount.google.com/permissions](https://myaccount.google.com/permissions)
2. Révoquer l'accès à Agentys
3. Supprimer `token.json`
4. Réauthentifier

### Outlook - Erreur 401 Unauthorized

**Symptôme:**
```
ClientAuthenticationError: 401 Unauthorized
```

**Solution:**
1. Vérifier les credentials Azure dans `.env`:
   ```
   AZURE_TENANT_ID=your-tenant-id
   AZURE_CLIENT_ID=your-client-id
   AZURE_CLIENT_SECRET=your-client-secret
   ```
2. Vérifier que l'app est bien enregistrée dans Azure AD
3. Vérifier les permissions API (Mail.ReadWrite, Mail.Send)

---

## Erreurs IMAP/SMTP (recommandé)

### IMAP - Authentification échouée

**Symptôme:**
```
imaplib.IMAP4.error: b'AUTHENTICATIONFAILED'
```

**Causes et solutions par fournisseur:**

#### Gmail via IMAP
- **Cause principale:** Google bloque les "apps moins sécurisées"
- **Solution:** Créer un "Mot de passe d'application":
  1. Aller sur [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
  2. Activer la 2FA si pas déjà fait
  3. Créer un mot de passe pour "Mail" / "Autre"
  4. Utiliser ce mot de passe dans `IMAP_PASSWORD`

```
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=votre@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx  # Mot de passe d'application
```

#### Outlook/Office365 via IMAP
- **Note:** Microsoft a désactivé IMAP basic auth pour Microsoft 365
- **Solution:** Utiliser OAuth2 (provider `outlook`) ou IMAP avec mot de passe d'application
- Pour comptes personnels (@outlook.com, @hotmail.com):
  ```
  IMAP_HOST=outlook.office365.com
  IMAP_PORT=993
  IMAP_USER=votre@outlook.com
  IMAP_PASSWORD=votre-mot-de-passe
  ```

#### OVH
```
IMAP_HOST=ssl0.ovh.net
IMAP_PORT=993
IMAP_USER=votre@votredomaine.fr
IMAP_PASSWORD=votre-mot-de-passe
```

#### Infomaniak
```
IMAP_HOST=mail.infomaniak.com
IMAP_PORT=993
IMAP_USER=votre@votredomaine.ch
IMAP_PASSWORD=votre-mot-de-passe
```

### IMAP - Connection timeout

**Symptôme:**
```
socket.timeout: Connection timed out
```

**Solutions:**
1. Vérifier le firewall/proxy
2. Vérifier le port (993 SSL, 143 non-SSL)
3. Tester la connexion:
   ```bash
   openssl s_client -connect imap.votreserveur.com:993
   ```

### IMAP - Certificat SSL invalide

**Symptôme:**
```
ssl.SSLCertVerificationError: certificate verify failed
```

**Solutions:**
1. Vérifier que le certificat du serveur est valide
2. Pour serveurs internes avec certificats auto-signés (non recommandé en production), voir la documentation spécifique

### SMTP - Authentification échouée (535)

**Symptôme:**
```
smtplib.SMTPAuthenticationError: (535, '5.7.8 Username and Password not accepted')
```

**Solutions par fournisseur:**

#### Gmail
Même solution que IMAP - utiliser un mot de passe d'application:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=votre@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx  # Mot de passe d'application
```

#### Outlook/Office365
```
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=votre@outlook.com
SMTP_PASSWORD=votre-mot-de-passe
```

#### OVH
```
SMTP_HOST=ssl0.ovh.net
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_USE_TLS=false
SMTP_USER=votre@votredomaine.fr
SMTP_PASSWORD=votre-mot-de-passe
```

#### Infomaniak
```
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=votre@votredomaine.ch
SMTP_PASSWORD=votre-mot-de-passe
```

### SMTP - Relay access denied (550)

**Symptôme:**
```
smtplib.SMTPRecipientsRefused: 550 5.7.1 Relay access denied
```

**Causes:**
- L'adresse expéditeur ne correspond pas au compte authentifié
- Le serveur refuse de relayer pour ce domaine

**Solution:**
Vérifier que `SMTP_FROM_EMAIL` correspond au compte:
```
SMTP_USER=votre@domaine.com
SMTP_FROM_EMAIL=votre@domaine.com  # Doit correspondre!
```

### SMTP - TLS/SSL confusion

**Symptôme:**
```
ssl.SSLError: [SSL: WRONG_VERSION_NUMBER] wrong version number
```

**Cause:** Confusion entre TLS (STARTTLS) et SSL direct

**Solutions:**

Pour **port 587** (STARTTLS):
```
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

Pour **port 465** (SSL direct):
```
SMTP_PORT=465
SMTP_USE_TLS=false
SMTP_USE_SSL=true
```

Pour **port 25** (sans chiffrement - non recommandé):
```
SMTP_PORT=25
SMTP_USE_TLS=false
SMTP_USE_SSL=false
```

### Test de connectivité IMAP/SMTP

```bash
# Test IMAP
openssl s_client -connect imap.votreserveur.com:993

# Test SMTP SSL
openssl s_client -connect smtp.votreserveur.com:465

# Test SMTP STARTTLS
openssl s_client -connect smtp.votreserveur.com:587 -starttls smtp
```

---

## Erreurs API LLM

### Claude API - Rate Limit (429)

**Symptôme:**
```
anthropic.RateLimitError: Error code: 429
```

**Solutions:**
1. **Immédiat:** Attendre quelques secondes (le retry automatique gère ça)
2. **Long terme:** Réduire `MAX_EMAILS_PER_POLL` dans `.env`:
   ```
   MAX_EMAILS_PER_POLL=10
   DAEMON_POLL_INTERVAL=120
   ```

Le système inclut un rate limiter automatique. Vérifier les stats:
```python
from app.infrastructure.rate_limiter import get_rate_limiter
limiter = get_rate_limiter("claude_api")
print(limiter.stats)
```

### Claude API - Overloaded (529)

**Symptôme:**
```
anthropic.APIStatusError: Error code: 529 - API is overloaded
```

**Solution:**
Le circuit breaker protège contre les échecs en cascade:
```python
from app.infrastructure.circuit_breaker import get_circuit_breaker
cb = get_circuit_breaker("claude_api")
print(f"État: {cb.state}, Échecs: {cb.stats.failed_calls}")
```

Configuration du circuit breaker dans `.env`:
```
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
```

### Ollama - Connection Refused

**Symptôme:**
```
ConnectionError: Connection refused to localhost:11434
```

**Solutions:**
1. Vérifier qu'Ollama est démarré:
   ```bash
   ollama serve
   ```
2. Vérifier l'URL dans `.env`:
   ```
   OLLAMA_HOST=http://localhost:11434
   ```
3. Vérifier que le modèle est téléchargé:
   ```bash
   ollama pull llama3
   ```

---

## Problèmes de performance

### Traitement lent des emails

**Diagnostic:**
```python
from app.history import draft_history
stats = draft_history.get_stats()
print(f"Temps moyen: {stats['avg_processing_time_sec']}s")
```

**Solutions:**
1. Utiliser un modèle plus rapide:
   ```
   LLM_MODEL=claude-3-5-haiku-20241022
   ```
2. Réduire la taille du contexte:
   ```
   EMAIL_MAX_TOKENS=4000
   ```
3. Activer le skip des emails basse priorité:
   ```
   DAEMON_SKIP_LOW_PRIORITY=true
   ```

### Consommation mémoire élevée

**Symptôme:**
L'application utilise beaucoup de RAM après plusieurs heures.

**Solutions:**
1. Activer la purge automatique:
   ```python
   from app.infrastructure.security import get_data_retention_manager
   manager = get_data_retention_manager()
   manager.purge_old_data()
   ```
2. Réduire l'historique en mémoire:
   ```
   HISTORY_MAX_ENTRIES=500
   ```

---

## Erreurs de configuration

### Variable d'environnement manquante

**Symptôme:**
```
ConfigValidationError: Missing required environment variable: ANTHROPIC_API_KEY
```

**Solution:**
1. Vérifier le fichier `.env`:
   ```bash
   cat .env | grep ANTHROPIC
   ```
2. Utiliser le script de setup:
   ```bash
   python setup.py
   ```
3. Variables requises minimales:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   EMAIL_PROVIDER_TYPE=GMAIL
   ```

### Configuration invalide

**Symptôme:**
```
Validation error: DAEMON_POLL_INTERVAL must be >= 30
```

**Solution:**
Le système valide la configuration au démarrage. Vérifier les contraintes:
```python
from app.config import validate_config
errors = validate_config()
for error in errors:
    print(error)
```

---

## Problèmes de base de données

### Base SQLite corrompue

**Symptôme:**
```
sqlite3.DatabaseError: database disk image is malformed
```

**Solutions:**
1. Sauvegarder et réparer:
   ```bash
   cp data/agentys.db data/agentys.db.backup
   sqlite3 data/agentys.db "PRAGMA integrity_check"
   ```
2. Si corruption, recréer la base:
   ```bash
   rm data/agentys.db
   python -c "from app.infrastructure.database import db; print('DB recreated')"
   ```

### Migration depuis JSON

Si vous aviez des données JSON avant la migration SQLite:
```python
from app.infrastructure.database import migrate_from_json
results = migrate_from_json()
print(f"Migrés: {results}")
```

---

## Logs et diagnostic

### Activer les logs détaillés

Dans `.env`:
```
LOG_LEVEL=DEBUG
LOG_FORMAT=json
LOG_TO_FILE=true
```

### Consulter les logs

```bash
# Logs récents
tail -f logs/agentys.log

# Filtrer par niveau
grep '"level":"ERROR"' logs/agentys.log | jq .

# Logs d'audit
cat data/audit.json | jq '.events[-10:]'
```

### Health check manuel

```python
from app.daemon import EmailDaemon

daemon = EmailDaemon()
health = daemon.health_check()
print(f"Email Provider: {'OK' if health['email_provider'] else 'FAIL'}")
print(f"LLM: {'OK' if health['llm'] else 'FAIL'}")
```

### Vérifier l'état du circuit breaker

```python
from app.infrastructure.circuit_breaker import get_circuit_breaker, reset_all_circuit_breakers

# État
cb = get_circuit_breaker("claude_api")
print(f"État: {cb.state}")
print(f"Échecs: {cb.stats.failed_calls}")

# Reset si nécessaire
reset_all_circuit_breakers()
```

### Statistiques de coûts

```python
from app.infrastructure.cost_manager import get_cost_manager

manager = get_cost_manager()
stats = manager.get_stats()
print(f"Coût ce mois: ${stats['current_month_cost']:.2f}")
print(f"Par agent: {stats['by_agent']}")
```

---

## Problemes d'affichage des emails

### Corps de l'email vide dans le modal

**Symptome:**
Le modal d'email affiche les metadonnees (expediteur, date, sujet) mais le corps du message reste vide.

**Date du fix:** 2026-02-03

**Cause racine:**
Certains emails (notamment les notifications bancaires, newsletters) sont envoyes uniquement en HTML sans partie `text/plain`. L'adaptateur IMAP n'extrayait le texte du HTML que pour les messages non-multipart.

**Structure d'email problematique:**
```
multipart/mixed
  └── multipart/alternative
        └── multipart/related
              └── text/html  ← Seul contenu disponible
```

**Diagnostic:**
1. Verifier l'API directement:
   ```bash
   curl -s "http://localhost:5050/api/emails/<id>"
   ```
   Si `body` est vide mais que l'email existe, c'est ce probleme.

2. Verifier la structure de l'email:
   ```python
   import imaplib
   import email

   conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
   conn.login(user, password)
   conn.select("INBOX")
   status, data = conn.fetch(b'<id>', '(BODYSTRUCTURE)')
   print(data)  # Voir si text/plain existe
   ```

**Fichiers modifies:**

1. `app/providers/imap_adapter.py` - Ajout du fallback HTML vers texte:
   ```python
   def _get_body(self, msg):
       # ... extraction text/plain et text/html ...

       # CORRECTION: Si on n'a que du HTML, extraire le texte
       if not body_text and body_html:
           body_text = self._extract_text_from_html(body_html)

       return body_text.strip(), body_html
   ```

2. `app/providers/email_parser_mixin.py` - Decodage des entites HTML:
   ```python
   def _extract_text_from_html(self, html: str) -> str:
       import html as html_module
       text = self._HTML_TAG_RE.sub('', html)
       text = html_module.unescape(text)  # &eacute; -> e
       return text.strip()
   ```

**Points cles du debugging:**

1. **Identifier le bon serveur:** L'API Flask (`run_api.py` sur port 5050) est separee du daemon (`run_daemon.py`). Redemarrer le bon processus!

2. **Cache Python:** Apres modification, tuer tous les processus Python et supprimer `__pycache__`:
   ```bash
   taskkill /F /IM python.exe
   find . -name __pycache__ -exec rm -rf {} +
   ```

3. **Type hints:** L'import `import email` ne charge pas automatiquement `email.message`. Ajouter explicitement:
   ```python
   import email.message
   ```

**Prevention:**
Toujours tester avec des emails de differentes sources (newsletters, notifications bancaires, emails personnels) car ils utilisent des structures MIME differentes.

---

## Modifications UI - Session 2026-02-03

### Formatage des dates dans la liste d'emails

**Date:** 2026-02-03

**Changement:**
Le format d'affichage des dates dans la liste d'emails a ete modifie pour etre plus lisible:

| Periode | Format | Exemple |
|---------|--------|---------|
| Aujourd'hui | Heure (HHhMM) | 11h00, 14h30 |
| 1-7 jours | Jour + Mois court | 2 FEB, 31 JAN |
| > 7 jours | Date complete | 31/12/2025 |

**Separateurs de date:**
Les emails sont maintenant groupes par date avec des en-tetes:
- Pas d'en-tete pour aujourd'hui (emails en haut)
- "Yesterday" pour hier
- "February 1st", "January 30th" pour les 7 derniers jours
- "December 2025", "January 2026" pour les mois passes

**Fichiers modifies:**
- `agentys-app/src/components/EmailList.tsx` - Fonctions `formatEmailTime()`, `getDateSectionKey()`, `getSectionLabel()`, `groupEmailsByDate()`
- `agentys-app/src/components/EmailList.css` - Classes `.email-date-group`, `.email-date-separator`, `.email-date-label`

---

### Theme blanc pour la fenetre de reponse

**Date:** 2026-02-03

**Probleme:**
La fenetre de composition/reponse avait un theme vert et noir au lieu de blanc.

**Solution:**
Remplacement du theme colore par un theme blanc minimaliste style Superhuman.

**Fichiers modifies:**

1. `agentys-app/src/components/reply/ReplyComposer.css`:
   - Bordure: `#10b981` (vert) → `#e5e7eb` (gris clair)
   - Header: gradient vert → fond blanc `#fff`
   - Bouton Send: gradient vert → `#1f2937` (gris fonce)
   - Suppression du dark mode

2. `agentys-app/src/components/DraftEditor.css`:
   - Variables forcees en mode clair
   - Suppression du dark mode media query

3. `agentys-app/src/components/reply/AIPromptInput.css`:
   - Variables forcees en mode clair
   - Suppression du dark mode media query

---

### Suppression du tagline header

**Date:** 2026-02-03

**Changement:**
Suppression de "L'IA qui s'ameliore avec vous" du header.

**Fichier modifie:**
- `agentys-app/src/App.tsx` - Suppression de `<p className="tagline">...</p>`

---

### Scrollbar minimaliste style Gmail

**Date:** 2026-02-03

**Probleme:**
Deux barres de defilement visibles (double scrollbar).

**Solution:**
1. Suppression de l'overflow sur `.app-main`
2. Une seule barre de defilement sur `.email-list-virtualized`
3. Style minimaliste Gmail: 8px, gris clair, arrondi

**Fichiers modifies:**

1. `agentys-app/src/App.css`:
   ```css
   .app-main {
     overflow: hidden; /* au lieu de overflow-y: auto */
   }
   ```

2. `agentys-app/src/components/EmailList.css`:
   ```css
   .email-list-virtualized {
     overflow-y: auto; /* seul element scrollable */
   }
   .email-list-scroll, .email-list {
     /* overflow supprime */
   }
   ```

3. `agentys-app/src/index.css`:
   ```css
   ::-webkit-scrollbar {
     width: 8px;
   }
   ::-webkit-scrollbar-thumb {
     background: #dadce0;
     border-radius: 4px;
   }
   ```

---

### Inbox pleine largeur

**Date:** 2026-02-03

**Changement:**
Suppression des contraintes de largeur pour que l'inbox prenne toute la largeur de l'ecran.

**Fichier modifie:**
- `agentys-app/src/App.css`:
  - `.app-main`: suppression de `max-width: 1400px` et `margin: 0 auto`
  - `.email-list-panel.full-width`: `max-width: 800px` → `width: 100%`

---

### Simplification du header de la liste d'emails

**Date:** 2026-02-03

**Changement:**
Suppression des boutons "Selectionner" et "Actualiser" du header de la liste d'emails.

**Fichier modifie:**
- `agentys-app/src/components/EmailList.tsx` - Header simplifie avec uniquement le titre et le compteur

---

## Codes d'erreur courants

| Code | Message | Solution |
|------|---------|----------|
| AUTH_001 | Gmail token expired | Supprimer token.json, réauthentifier |
| AUTH_002 | Outlook credentials invalid | Vérifier Azure AD config |
| LLM_001 | Rate limit exceeded | Attendre ou réduire la charge |
| LLM_002 | API overloaded | Circuit breaker actif, attendre |
| DB_001 | Database locked | Vérifier les processus concurrent |
| CFG_001 | Config validation failed | Corriger .env |

---

## Obtenir de l'aide

1. **Logs:** Toujours inclure les logs pertinents
2. **Configuration:** Exporter la config (sans secrets):
   ```bash
   env | grep -v KEY | grep -v SECRET > config_export.txt
   ```
3. **État du système:**
   ```python
   from app.infrastructure.circuit_breaker import get_circuit_breaker
   from app.infrastructure.rate_limiter import get_rate_limiter

   print("Circuit Breakers:", [cb.state for cb in get_all_circuit_breakers()])
   print("Rate Limiters:", [rl.stats for rl in get_all_rate_limiters()])
   ```
