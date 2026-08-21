# Guide d'installation Agentys

## Prérequis

- Windows 10/11, macOS ou Linux
- Python 3.12+
- Node.js 20+ (via fnm recommandé)
- Yarn
- Compte Gmail avec mot de passe d'application
- Clé API Anthropic

## Installation rapide

### 1. Cloner le dépôt

```bash
git clone https://github.com/nathan/agentys.git
cd agentys
```

### 2. Installer Python 3.12 (Windows)

```bash
winget install Python.Python.3.12
```

### 3. Installer Node.js (via fnm)

```bash
winget install Schniz.fnm
fnm install --lts
fnm use lts-latest
```

### 4. Installer Yarn

```bash
npm install -g yarn
```

### 5. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

> **Note**: Si `sqlcipher3-binary` échoue sur Windows, ignorer cette erreur (fallback SQLite utilisé).

### 6. Installer les dépendances Frontend

```bash
cd agentys-app
yarn install
cd ..
```

### 7. Configurer le fichier `.env`

```bash
cp .env.example .env
```

Éditer `.env` avec vos valeurs :

```env
# API Anthropic (obligatoire)
ANTHROPIC_API_KEY=sk-ant-api03-...

# Configuration Gmail
EMAIL_PROVIDER_TYPE=IMAP_SMTP
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=votre-email@gmail.com
IMAP_PASSWORD=votre-mot-de-passe-application
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=votre-email@gmail.com
SMTP_PASSWORD=votre-mot-de-passe-application
```

#### Obtenir un mot de passe d'application Gmail

1. Aller sur https://myaccount.google.com/apppasswords
2. Sélectionner "Mail" et "Ordinateur Windows"
3. Cliquer "Générer"
4. Copier le mot de passe à 16 caractères

### 8. Initialiser la base de données

```bash
python -c "from app.db.database import init_db; init_db()"
```

## Lancement

### Backend API (port 5050)

```bash
python run_api.py --port 5050
```

### Frontend (port 1420)

```bash
cd agentys-app
yarn dev
```

### Daemon Email (optionnel)

Pour le traitement automatique des emails en arrière-plan :

```bash
python run_daemon.py
```

## Accès

- **Frontend**: http://localhost:1420
- **API**: http://localhost:5050
- **API Docs (Swagger)**: http://localhost:5050/api/docs/

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Frontend React (Vite)                       │
│                  localhost:1420                          │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP + WebSocket
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Backend Flask + SocketIO                    │
│                  localhost:5050                          │
│  • API REST (/api/*)                                     │
│  • WebSocket (/daemon)                                   │
│  • Sync Service (120s interval)                          │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  Gmail IMAP/SMTP │     │  Anthropic API  │
│  imap.gmail.com  │     │  Claude LLM     │
└─────────────────┘     └─────────────────┘
```

## Dépannage

### Erreur CORS

Si le frontend affiche "Déconnecté" avec des erreurs CORS :

1. Vérifier que `run_api.py` est lancé (pas `run_daemon.py`)
2. Vérifier que le port est 5050
3. Redémarrer l'API

### Erreur "no such table"

```bash
python -c "from app.db.database import init_db; init_db()"
```

### Gmail "Authentication failed"

1. Vérifier que vous utilisez un mot de passe d'application (pas le mot de passe Gmail)
2. Vérifier que IMAP est activé dans Gmail (Paramètres > Transfert et POP/IMAP)

Voir [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) pour plus de détails.
