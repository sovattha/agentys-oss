# Agentys Mobile

App mobile companion pour Agentys — mode conduite, gestion de brouillons, réponses vocales.

## Prérequis

- Node.js 18+
- Expo CLI : `npm install -g expo-cli`
- Expo Go sur votre téléphone ([iOS](https://apps.apple.com/app/expo-go/id982107779) / [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))
- Backend Agentys qui tourne (`python run_api.py` sur port 5050)

## Installation

```bash
cd agentys-mobile
npm install
```

## Lancement

```bash
npx expo start
```

Scanner le QR code avec Expo Go sur votre téléphone.

## Configuration de l'URL API

Par défaut, l'app se connecte à `http://localhost:5050`.

Pour pointer vers un backend distant :

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.X:5050 npx expo start
```

Ou modifier dans l'écran **Réglages** de l'app.

## Structure

```
app/                    # Expo Router (écrans)
├── _layout.tsx         # Root layout + AuthProvider
├── index.tsx           # Redirect login/inbox
├── login.tsx           # Magic link auth
├── auth-callback.tsx   # Deep link handler
└── (tabs)/
    ├── inbox.tsx       # Liste brouillons
    ├── drive.tsx       # Mode conduite
    └── settings.tsx    # Configuration

src/
├── services/           # API, auth, WebSocket
├── hooks/              # useAuth, useApi, useDriveMode
├── components/         # UI réutilisables
├── types/              # TypeScript types
└── config.ts           # Configuration
```

## Deep Linking

Scheme : `agentys://`

Le magic link redirige vers `agentys://auth-callback?token=X` pour l'authentification mobile.

## Build EAS (production)

```bash
npm install -g eas-cli
eas login
eas build --platform all
```

## Troubleshooting

| Problème | Solution |
|----------|----------|
| "Network request failed" | Vérifier que le backend tourne et que l'URL API est correcte |
| "Unauthorized" | Se déconnecter et reconnecter via magic link |
| QR code ne marche pas | Utiliser `npx expo start --tunnel` pour le réseau |
| Build échoue | `rm -rf node_modules && yarn install` |
| `yarn install` échoue sur `[postinstall-patch]` | Un bump a cassé un patch de compat Expo 54 / RN 0.86 — voir [docs/expo54-rn086-compat.md](docs/expo54-rn086-compat.md) |

> ⚠️ **Expo SDK 54 + RN 0.86 est un combo hors matrice supportée**, tenu par
> des patches postinstall. Avant tout bump de `expo`, `react-native` ou
> `@react-native/*`, lire [docs/expo54-rn086-compat.md](docs/expo54-rn086-compat.md).
