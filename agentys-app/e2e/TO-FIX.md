# E2E Tests — Issues to Fix

## Selectors manquants (data-testid)

### Priorité Haute
- **LoginPage** (`src/components/LoginPage.tsx`) — Aucun `data-testid`. Ajouter :
  - `data-testid="login-page"` sur `.login-page`
  - `data-testid="login-email-input"` sur l'input email
  - `data-testid="login-submit"` sur le bouton submit
  - `data-testid="login-sent"` sur l'écran de confirmation
  - `data-testid="login-error"` sur la bannière d'erreur
  - `data-testid="login-oauth-google"` et `data-testid="login-oauth-outlook"` sur les boutons OAuth

- **ErrorBoundary** (`src/components/ErrorBoundary.tsx`) — Zéro sélecteur stable (inline styles uniquement). Ajouter :
  - `data-testid="error-boundary-fallback"` sur le conteneur d'erreur
  - `data-testid="error-boundary-reload"` sur le bouton "Recharger"

- **MonthlyRecapPage** (`src/components/MonthlyRecapPage.tsx`) — Aucun `data-testid`. Ajouter :
  - `data-testid="recap-page"` sur le root
  - `data-testid="recap-loading"` sur le skeleton
  - `data-testid="recap-hero"` sur le bloc hero

### Priorité Moyenne
- **AccountManager** — Les items de compte n'ont pas de `data-testid` par item
- **CalendarView** — Utilise Tailwind + FullCalendar internals, sélecteurs fragiles
- **CommandPalette** — Pas de `data-testid` mais bons `role`/`aria` déjà en place

### Priorité Basse
- **GuidedTour** — Classes CSS stables, ok pour les tests
- **SnippetLibrary** — Classes CSS workable
- **LabelLibrary** — Classes CSS workable

## Problèmes de structure/code détectés

### 1. App.tsx — Fichier monstre (1815 lignes)
- **Risque** : Difficile à maintenir, trop de state dans un seul composant
- **Suggestion** : Extraire les blocs de dossier (sent, archived, spam, trash) en composant `<FolderView>` partagé — code dupliqué 5x (lignes 1309-1483)

### 2. Code dupliqué dans les onglets de dossier
- Les 5 onglets (inbox, sent, archived, spam, trash) utilisent quasi le même JSX pour EmailList + EmailDetailModal
- Seul `folder` prop et quelques handlers changent
- **Suggestion** : Extraire un composant `<FolderEmailView folder={...} />`

### 3. Shortcuts ribbon — Duplication massive
- Le bloc shortcuts ribbon (lignes 1486-1580) a ~6 variantes conditionelles avec beaucoup de HTML dupliqué
- **Suggestion** : Extraire un composant `<ShortcutsRibbon context={...} />`

### 4. waitForTimeout dans les tests existants
- Plusieurs tests e2e utilisent `page.waitForTimeout(500)` — anti-pattern qui cause des tests flaky
- **Fichiers** : `email-list.spec.ts`, `draft-list.spec.ts`, `email-compose.spec.ts`, `shortcuts.spec.ts`
- **Fix** : Remplacer par `await expect(...).toBeVisible()` ou `page.waitForResponse()`

### 5. Soft assertions trop permissives
- Plusieurs tests ont `expect(true).toBeTruthy()` ou `expect(isVisible || true).toBeTruthy()` — ces tests ne testent rien
- **Fichiers** : `email-list.spec.ts` (ligne 293), `shortcuts.spec.ts` (lignes 24, 62, 74)
- **Fix** : Rendre les assertions conditionnelles plus strictes ou skip le test proprement

### 6. Tests qui ne mockent pas l'auth — ✅ CORRIGÉ
- `shortcuts.spec.ts` utilise maintenant `setupBaseMocks()`
- `setupBaseMocks()` pose le token DEV (`agentys_jwt: 'dev:test@example.com'`) + mock `/api/auth/me`

### 7. Sidebar toggle crash (ErrorBoundary)
- **Bug** : Cliquer sur le bouton toggle sidebar déclenche un crash React (ErrorBoundary)
- **Composant** : `Sidebar.tsx` — `handleToggle()` → `cycleMode()` → crash lors du re-render
- **Impact** : Le cycle pinned → auto → collapsed ne fonctionne pas en e2e
- **Test** : `sidebar.spec.ts` — marqué `test.fixme`

### 8. Focus trap settings modal incomplet
- **Bug** : Après 10+ Tab dans les settings, le focus s'échappe de l'overlay
- **Composant** : `App.tsx` — `settingsTrapRef` sur l'overlay
- **Test** : `accessibility.spec.ts` — marqué `test.fixme`

### 9. SupportIntentCards non utilisé
- **Observation** : `SupportIntentCards.tsx` existe mais n'est importé nulle part
- Le `SupportPanel` utilise `SupportChat` à la place — les tests ont été adaptés
- **Suggestion** : Supprimer `SupportIntentCards.tsx` ou le réintégrer

### 10. PendingDraftDetail ne se monte pas en e2e
- Les mocks de `/api/pending-drafts/by-email` ne déclenchent pas le montage de `.pending-draft-detail`
- **Impact** : 3 tests scroll-unified marqués `test.fixme`
- **Fix** : Investiguer le flow complet email → draft detail pour corriger les mocks

### 7. CSS selectors au lieu de data-testid
- Les tests existants utilisent beaucoup `.swipeable-email-item`, `.email-detail-title`, `.gmail-title` etc.
- **Suggestion** : Migrer progressivement vers `data-testid` selon le skill e2e-testing-patterns

## Composants sans couverture e2e

### Maintenant couverts (nouveaux tests ajoutés)
- [x] Sidebar navigation (`sidebar.spec.ts`)
- [x] Login page (`login.spec.ts`)
- [x] Command palette (`command-palette.spec.ts`)
- [x] My Style modal (`my-style.spec.ts`)
- [x] Account manager (`account-manager.spec.ts`)
- [x] Shortcuts help panel (`shortcuts-help.spec.ts`)
- [x] DND mode (`dnd-mode.spec.ts`)
- [x] Support panel (`support-panel.spec.ts`)
- [x] Learning dashboard (`learning-dashboard.spec.ts`)
- [x] Snippet library (`snippet-library.spec.ts`)
- [x] Label library (`label-library.spec.ts`)
- [x] Folder tabs (sent/archived/spam/trash) (`folder-tabs.spec.ts`)
- [x] Accessibility basics (`accessibility.spec.ts`)
- [x] Error states (`error-states.spec.ts`)

### Pas encore couverts (besoin de tests supplémentaires)
- [ ] CalendarView — FullCalendar DOM rend les tests complexes
- [ ] GuidedTour — Step-by-step walkthrough
- [ ] DeepFocusMode — Mode sprint avec sections
- [ ] DeepWorkOverlay — Timer overlay avec bypass
- [ ] TrainingPage — Entraînement IA avec progress
- [ ] MonthlyRecapPage — Récap mensuel avec stats
- [ ] Onboarding flow (PremiumOnboarding) — Multi-step wizard
- [ ] RecapBanner — Banner contextuel
- [ ] MilestoneToast / FirstDraftCelebration — Toasts de célébration

## Améliorations recommandées

1. **Page Object Model** : Créé `e2e/pages/AppPage.ts` — étendre avec d'autres POs
2. **Fixtures auth** : Centraliser le mock d'auth dans un fixture Playwright réutilisable
3. **Visual regression** : Ajouter `toHaveScreenshot()` pour les composants critiques
4. **CI pipeline** : Ajouter un job GitHub Actions pour les tests e2e
5. **Tests de performance** : Vérifier que la virtualisation fonctionne avec 500+ emails
