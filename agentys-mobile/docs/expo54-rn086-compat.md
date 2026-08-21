# Compatibilité Expo SDK 54 + React Native 0.86

> **Ce combo est hors matrice supportée.** Le SDK 54 est calibré pour RN 0.81 ;
> nous faisons tourner RN 0.86 dessus (besoin : simulateur iOS 26 beta,
> commit `69b711ec`). Ça ne tient que grâce aux patches décrits ici.
> Toute personne (ou agent) qui bump `expo`, `react-native` ou
> `@react-native/*` doit lire ce document.

## Pourquoi

- RN 0.86 introduit des event types Flow dans ses composants internes
  (`react-native/src/private/`) que `@react-native/codegen@0.81.5`
  (toolchain Expo 54) ne sait pas parser → crash au bundle.
- Le simulateur iOS 26 beta enregistre le ViewManager `DebuggingOverlay`
  avec une view config incomplète → « Invariant Violation: View config not
  found » au démarrage.
- L'ancienne architecture (`newArchEnabled: false` dans `app.json`) est
  requise : en old arch, `codegenNativeComponent()` retombe sur
  `requireNativeComponent()` au runtime, ce qui rend inoffensif le skip du
  codegen build-time.

## Les patches (`scripts/patch-codegen-plugin.js`, postinstall)

| # | Fichier patché (node_modules) | Raison | Optionnel |
|---|---|---|---|
| 1 | `@react-native/babel-plugin-codegen/index.js` | try-catch autour de `generateViewConfig` pour `react-native/src/private/` | non |
| 2a | `@react-native/codegen/lib/parsers/error-utils.js` | event arguments non résolus → `[]` au lieu de throw | non |
| 2b | idem | bubbling type non résolu → `'direct'` au lieu de throw | non |
| 3 | `react-native/Libraries/Debugging/DebuggingOverlay.js` | désactive l'overlay (dev tool) — view config incomplète sim iOS 26 beta | **oui** |

À quoi s'ajoute `VirtualViewNativeComponentStub.js` (racine) : stub de
`VirtualViewNativeComponent` (New Architecture only en RN 0.86, rien dans
l'app n'utilise `unstable_VirtualView`).

## Comportement fail-loud (#1118)

Le script est idempotent (marqueurs). Depuis #1118 :

- patch **requis** non applicable (fichier absent OU chaîne cible
  introuvable) → **`yarn install` échoue (exit 1)** avec le récapitulatif.
  C'est voulu : un bump qui change le code cible doit casser à l'install,
  pas produire un crash différé illisible au bundle.
- patch **optionnel** (DebuggingOverlay) non applicable → warning seulement.

Si l'install casse ici : soit adapter la chaîne `target` du patch au nouveau
code de la dépendance, soit déclencher la stratégie de sortie ci-dessous.

## Stratégie de sortie (à trancher, ne pas laisser pourrir)

Deux portes de sortie, la première atteinte gagne :

1. **Un SDK Expo supportant RN 0.86** est publié → `expo upgrade`, supprimer
   les 4 patches + le stub + ce document.
2. **Le besoin iOS 26 beta disparaît** (simulateur stable supporté par
   RN 0.81) → revenir à `react-native@0.81.x` (canonique SDK 54), supprimer
   les patches + le stub + ce document.

## Checklist après tout bump de dépendance native

```bash
cd agentys-mobile
yarn install          # les patches doivent logger Patched/Already patched
npx tsc --noEmit      # 0 erreur attendu
yarn test             # suite complète verte
npx expo run:ios      # build + boot simulateur
```
