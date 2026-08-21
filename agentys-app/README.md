# Agentys Desktop App

Application desktop Tauri pour Agentys - Assistant IA de reponse email.

## Stack Technique

- **Frontend**: React 19 + TypeScript + Vite
- **Backend Desktop**: Rust (Tauri 2.0)
- **Style**: CSS custom avec design system Agentys

## Prerequisites

- Node.js 20+
- pnpm
- Rust 1.77+
- Xcode Command Line Tools (macOS)

## Installation

```bash
cd agentys-app
pnpm install
```

## Development

```bash
# Frontend only (hot reload)
pnpm dev

# App Tauri complete
pnpm tauri:dev
```

## Build

```bash
# Build production
pnpm tauri:build
```

Le bundle sera genere dans `src-tauri/target/release/bundle/`.

## Structure

```
agentys-app/
├── src/                 # Frontend React
│   ├── App.tsx          # Composant principal
│   ├── App.css          # Styles composants
│   ├── index.css        # Styles globaux
│   └── main.tsx         # Point d'entree React
├── src-tauri/           # Backend Rust Tauri
│   ├── src/
│   │   ├── main.rs      # Point d'entree Tauri
│   │   └── lib.rs       # Configuration app
│   ├── icons/           # Icones app (toutes tailles)
│   ├── capabilities/    # Permissions Tauri
│   ├── Cargo.toml       # Dependances Rust
│   └── tauri.conf.json  # Config Tauri
├── dist/                # Build frontend (genere)
└── package.json         # Dependances npm
```

## Communication avec le Backend Python

L'app communique avec le backend Python via HTTP/WebSocket:

- `GET /api/health` - Verification du statut
- `GET /api/emails` - Liste des emails en attente
- `POST /api/generate` - Generer une reponse IA
- WebSocket pour les notifications temps reel

Le backend doit etre lance separement avec `python run_daemon.py` depuis le repertoire racine du projet.

## Design System

Couleurs Agentys:
- Primary: `#673de6`
- Secondary: `#6366F1`
- Background: `#0f0f1a`
- Card: `#1a1a2e`
