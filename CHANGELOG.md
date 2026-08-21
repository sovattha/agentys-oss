# Agentys — Journal de Développement

> **500+ commits** | **560+ fichiers source** (250 TS/TSX + 310 Python) | **2 contributeurs**
> Période: 25 décembre 2025 → 16 février 2026

---

## Table des matières

1. [Phase 1 — Fondations](#phase-1--fondations-25-29-décembre-2025)
2. [Phase 2 — Infrastructure](#phase-2--infrastructure-28-30-décembre-2025)
3. [Phase 3 — App Tauri](#phase-3--app-tauri-janvier-2026)
4. [Phase 4 — Gmail OAuth & UI](#phase-4--gmail-oauth--ui-28-jan--3-fév)
5. [Phase 5 — UX Premium](#phase-5--ux-premium-4-5-février)
6. [Phase 6 — AI Quality & Design](#phase-6--ai-quality--design-system-6-février)
7. [Phase 7 — Performance](#phase-7--performance-6-8-février)
8. [Phase 8 — Premium Transformation](#phase-8--premium-transformation-9-février)
9. [Phase 9 — Productivity Engine](#phase-9--productivity-engine-10-février)
10. [Phase 10 — Learning Dashboard & Draft Quality](#phase-10--learning-dashboard--draft-quality-11-février) (inclut Audit Auto-Label Pipeline v2)
11. [Phase 11 — Smart Routing Optimization](#phase-11--smart-routing-optimization-11-février)
12. [Phase 12 — Email Infrastructure & Anti-LLM Pipeline](#phase-12--email-infrastructure--anti-llm-pipeline-12-février)
13. [Phase 13 — Attachment Support & Template Intelligence](#phase-13--attachment-support--template-intelligence-12-février)
14. [Phase 14 — Draft Quality v3](#phase-14--draft-quality-v3-12-février)
15. [Phase 15 — Sent Folder Fix & IMAP Performance](#phase-15--sent-folder-fix--imap-performance-13-février)
16. [Phase 16 — Quick Reply, Deep Focus v2, Refine Mode & Labels i18n](#phase-16--quick-reply-deep-focus-v2-refine-mode--labels-i18n-13-février)
17. [Phase 17 — Deep Focus v3 "Calm Velocity"](#phase-17--deep-focus-v3-calm-velocity-13-février)
18. [E2E Audit v2 — 85 tests, 100%](#e2e-audit-v2--85-tests-100-13-février)
19. [Deep Focus UX Polish + CC/BCC + Labels](#deep-focus-ux-polish--ccbcc--labels-14-février)
20. [Phase 18 — Spam/Trash Management, Smart Suggestions, UX Redesign & Auto-Reply](#phase-18--spam-trash-management-smart-suggestions-ux-redesign--auto-reply-16-février)
21. [Export PDF — Bouton "Exporter en PDF" dans EmailDetailModal](#export-pdf--bouton-exporter-en-pdf-dans-emaildetailmodal-7-avril-2026)
22. [Architecture actuelle](#architecture-actuelle)

---

## Phase 1 — Fondations (25-29 décembre 2025)

### Pipeline multi-agents (`1aa9cca`)
- Architecture initiale : pipeline Drafter → Critic → réponse validée
- Modèle Opus par défaut, matching langue automatique
- Scan conversations amélioré pour contexte

### Architecture modulaire (`a51baf2`)
- Refactoring complet vers `app/` avec Clean Architecture
- Pattern Provider/Adapter pour Gmail, IMAP, SMTP
- Daemon "Zéro UI" pour traitement emails automatique
- CLI interactive `setup.py` pour configuration Gmail

### API REST & Intégrations (`b1edb8a` → `eacdaf0`)
- API Flask avec webhooks
- Intégrations Slack et Microsoft Teams
- Mode Draft Review avant envoi
- Templates de réponse par type d'email
- Règles de routage personnalisées
- Support multi-comptes email
- A/B Testing pour ajustements learning

---

## Phase 2 — Infrastructure (28-30 décembre 2025)

### Robustesse (`22c085e` → `5f1ae2c`)
- Retry/backoff et health check daemon
- Module `email_cleaner` pour nettoyage contenu
- Config centralisée, circuit breaker, audit, sleep interruptible
- Rate limiter (27 tests)

### Persistance & Sécurité (`4d3a788` → `cdeefa7`)
- Module SQLite pour persistance (35 tests)
- Gestion des coûts avec budget et alertes (22 tests)
- Sécurité RGPD : chiffrement, anonymisation, rétention (25 tests)

### Features avancées (`416c566` → `d12c3be`)
- WebSocket, templates, hot-reload, Prometheus, TTS
- Cache, pagination, batch processing
- Follow-ups avec schedules personnalisés
- Dashboard analytics : comparaison IA/humain
- Mode écoute continue avec wake word
- Auto-correction des brouillons modifiés
- Agents spécialisés dynamiques (Drafter/Critic)
- Historique échanges par client
- Support Discord
- Intégration CRM Salesforce/HubSpot
- Plugin navigateur Chrome/Firefox
- Dispatcher et Supervisor multi-canal

### Tests
- **1412 tests** cumulés à la fin de cette phase

---

## Phase 3 — App Tauri (janvier 2026)

### Fondation Tauri (`d7e81ed` → `5c78be9`)
- Gmail OAuth avec PKCE (`d7e81ed`)
- Fix memory leak Vite HMR (`c29a0e7`)
- Architecture Decision Document + PRD
- 76 tâches d'implémentation MVP + Epics & Stories
- **Epics 1-9 complétés** : OAuth, email list, compose, settings, etc.

### Planification
- GitHub Spec Kit avec PRD et architecture
- Sprint status avec BMAD workflow
- 43 tâches Email UI, Account Management, Monetization

---

## Phase 4 — Gmail OAuth & UI (28 jan → 3 fév)

### Compatibilité web/Tauri (`7fde095` → `fd96804`)
- Dynamic imports pour compatibilité web et Tauri
- CORS headers pour Flask-SocketIO

### IMAP robuste (`dcb1849` → `0db46c8`)
- `get_messages()` pour fetch all emails
- Fix sender parsing
- Batch fetch FLAGS parsing correct
- is_read detection fiable

### UI Gmail-style (`2bba719` → `84aac3f`)
- Sidebar collapsible Gmail-style
- Logo dans sidebar, suppression header bar
- Email count dans titre inbox
- Contexte conversation historique pour replies
- Suppression status bar, settings dans sidebar
- White theme, scrollbar Gmail, date grouping
- **Reply Composer** inline avec AI
- Skeleton loading et gzip compression

### Performance (`fa4b15c` → `a4b8a23`)
- Cache in-memory pour listing (100x plus rapide)
- Endpoint `/api/ping` pour startup instantané
- Normalisation noms dossiers pour cache

---

## Phase 5 — UX Premium (4-5 février)

### Fonctionnalités email (`ba8c86f` → `e76f581`)
- Swipe archive/delete
- Section AI Draft visible à l'ouverture d'un email
- AI demande clarification quand info manquante
- Extraction contenu email partagée (utility)

### Éditeur & Compose (`94cedbf` → `7872c22`)
- Améliorations UI/UX majeures
- OAuth tokens persistés en fichier
- Raccourcis clavier delete/archive avec updates optimistes
- **New Message Modal** Gmail-style avec raccourci clavier

### Email rendering (`65344d8` → `bedb2b5`)
- Détection URL plain text et conversion liens
- Preprocessing markdown malformé
- Remplacement ReactMarkdown par convertisseur custom
- Markdown rendering dans EmailDetailModal

### Settings & Signatures (`59fc5bd` → `539eb8e`)
- Éditeur de signature email
- Refactoring signature → modal design
- AI Memory editor, thème consistent

### Snippets & Labels (`086e06a` → `a52228b`)
- **Système de Snippets** : templates + variables
- **Intégration Calendrier** : Google/Outlook OAuth
- **Auto-labeling** : built-in rules → user rules → LLM fallback
- Fix DomainEmail TypeError dans auto-labeling
- Badges labels dans la liste emails

### Auto-labeling avancé (`001886a`)
- Filtrage bruit inbox (newsletters, notifications)
- Nettoyage newsletters
- Label badges premium
- Shortcuts ribbon

---

## Phase 6 — AI Quality & Design System (6 février)

### Design Prototype 10/10 (`c009136`)
- Prototype HTML complet avec split view et AI draft banner
- Typography : Instrument Sans + Newsreader
- Toggle teal, draft badge green, unread dot + selected bar
- Stagger animations, filter pills, labels dropdown

### Premium UI Overhaul (`7814310`)
- Split view : modal → inline 420px panel
- Panneau détail redimensionnable (drag to resize, 280-800px)
- AI draft quality fix : critic bypass quand V1 cite l'historique
- Pre-processing déterministe > recherche LLM
- Settings réorganisés (17 → 8 groupes)
- Badges premium : shimmer animé, "Quiet Luxury" labels

### AI Draft Quality — 3-layer fix
- **Pre-processing** : `_find_relevant_history_for_email` — parse email pour date/number refs, search history ±3 jours
- **Critic bypass** : `v1_uses_history` — si V1 cite texte historique, skip critic
- **Prompt amélioré** : exemple concret, historique dans user prompt

### Advanced Search (`7d0f9df`)
- Panel recherche avancée Gmail-style
- Fix raccourci "/"
- Compose toujours vierge

### Follow-up Reminders
- `SentEmail.followup_delay_days` par email
- UI pills 3j/7j/14j + toggle

---

## Phase 7 — Performance (6-8 février)

### Gmail Delta Sync (`cb2f8b8`)
- `historyId` delta sync pour fetch incrémental
- IndexedDB client cache pour persistance locale

### Virtualized List (`7c33f29`)
- `react-window` v2 pour inbox virtualisée
- Scroll performant même avec des milliers d'emails

### Calendar Scopes (`d7e2ef7`)
- Détection scopes calendar manquants
- UI re-auth au lieu d'état vide silencieux

---

## Phase 8 — Premium Transformation (9 février)

### Glassmorphism & Animations (`5a273c4`)
- Date separators frosted glass
- Animations sparkle/toggle fluides
- Gradients teal subtils hover/selected
- Film grain overlay

### Système de thèmes (`809eab7`) — 8 phases
1. **Theme System** : hook `useTheme.ts`, dark-luxury + editorial themes, Settings picker avec preview cards
2. **Variables CSS** : ~150+ couleurs hardcodées → variables CSS (`--surface-*`, `--text-*`, `--accent-*`, `--border-*`) dans 15 fichiers
3. **Micro-interactions** : spring buttons (`cubic-bezier(0.34, 1.56, 0.64, 1)`), bounce toggles, hover elevation, tab crossfade
4. **Glass morphism** : sidebar blur(20px), toolbar sticky blur(12px), modal shadows
5. **Empty states** : serif typography, Unicode icons, fadeIn animation
6. **Typography** : serif subjects, `tabular-nums`, `letter-spacing: -0.02em`
7. **View transitions** : `detailSlideIn`, `modalSlideIn` avec scale
8. **Sound design** : Web Audio API — 4 sons (send, draftReady, archive, delete) via OscillatorNode

### Classification labels améliorée (`7c22680`)
- Instagram/Facebook/Meta → Noise (plus de faux Action)
- Dark theme footer styles
- Résolution images CID inline Gmail

### Editorial UI Redesign (`19f8b23`)
- PendingDraftDetail : esthétique "Editorial Calm Authority"
- PendingDraftList : multi-select avec checkboxes + bulk delete
- Draft generation : bypass LLM quand historique pertinent trouvé, construction réponse programmatique
- Label classification : patterns strong/weak, détection signal automatique
- IMAP search multi-folder avec déduplication cross-folder

### Compose & Reply/Forward (`906b01c`)
- **Reply, Reply-All, Forward** : ReplyComposer étendu avec mode forward + champ CC
- **Envoi nouveaux emails** : endpoint `/emails/send-new` avec CC/BCC, tous providers
- **Composition IA** : appel LLM direct (simplifié, sans Orchestrator)
- **Race condition fix** : `selectedEmailIdRef` useRef guard
- **IMAP folders** : `_select_folder()` helper pour caractères spéciaux
- **Draft refinement** : pipeline gère pending + history drafts
- **Contact autocomplete** : filtrage spam/noreply

### Sidebar Signal Rail (non commité)
- Labels toujours visibles sans toggle chevron
- Suppression état `labelsExpanded`

---

## Phase 9 — Productivity Engine (10 février)

> **40+ fichiers modifiés, 17 nouveaux fichiers, +4200 lignes**
> Thème: Transformer Agentys d'un client email intelligent en un moteur de productivité complet.

### 1. Deep Focus Mode (nouveau)

Mode "Inbox Zero" guidé qui trie les emails par priorité et les présente section par section.

- **`useDeepFocus.ts`** (186 lignes) : Hook React — `start(emails)` groupe par priorité (Action > Waiting > FYI > Noise > Unlabeled), tracking processedIds, stats (sorted/replied/archived/snoozed), auto-avancement entre sections
- **`DeepFocusMode.tsx`** (208 lignes) : UI avec barre segmentée 4px en haut (une couleur par section), header section courante + compteur global, transition animée entre sections, escape pour quitter
- **`DeepFocusCelebration.tsx`** (70 lignes) : Ecran "Inbox Zero" avec confettis CSS-only (24 particules), checkmark SVG animé (stroke-dasharray), 4 stats (triés/répondu/archivés/snoozés) + temps écoulé
- **Intégration dans `App.tsx`** : bouton dans toolbar EmailList, layout split-view avec panneau détail redimensionnable, état `deepFocusActive` + `inboxEmailsRef`

### 2. Command Palette (Cmd+K)

Palette de commandes spotlight-style pour navigation rapide et actions.

- **`CommandPalette.tsx`** (163 lignes) : Recherche fuzzy, navigation clavier (flèches + Enter), groupement par sections ("Actions rapides", "Navigation", "Outils"), auto-focus input, raccourcis affichés
- **`CommandPalette.css`** (154 lignes) : Full-screen backdrop blur, modal centré, indicateur 2px sur item actif, animation slide-in
- **`useAppShortcuts.ts`** : Ajout binding `Cmd/Ctrl+K` → toggle palette
- **12 commandes** : Répondre, Archiver, Supprimer, Transférer, Boîte de réception, Brouillons, Envoyés, Archives, Deep Focus, Nouveau message, Paramètres, Raccourcis clavier

### 3. Priority Grouping (vue par priorité)

Alternative au groupement par date — regroupe les emails par label de priorité.

- **`priorityGrouping.ts`** (98 lignes) : `PRIORITY_ORDER` (Action > Waiting > FYI > Noise > Unlabeled), `getPrioritySection(email)`, `flattenEmailsByPriority()` compatible react-window
- **`PrioritySectionHeader.tsx`** (71 lignes) : Header collapsible avec dot coloré + label + count badge, bouton "Tout sélectionner" au hover, chevron rotatif
- **Toggle dans `EmailList.tsx`** : Bouton drapeau/horloge pour basculer date ↔ priorité, état persisté `localStorage`, sections collapsibles, sélection par section
- **`groupingMode` state** : `'date' | 'priority'`, sauvegardé dans `localStorage('agentys_grouping_mode')`

### 4. Smart Reply (réponses rapides)

Chips de réponse contextuelle + champ prompt IA dans le panneau détail.

- **`SmartReply.tsx`** (72 lignes) : Suggestions contextuelles par classification (Action → "Je m'en occupe", FYI → "Bien reçu", etc.), input prompt libre avec bouton envoi
- **Intégration `EmailDetailModal.tsx`** : Affiché entre le corps de l'email et le footer quand le reply composer n'est pas ouvert, `handleSmartReplyChip()` pré-remplit le ReplyComposer avec le texte

### 5. Snooze (rappel email)

Dropdown contextuel avec détection intelligente de dates depuis le corps de l'email.

- **`SnoozeDropdown.tsx`** (169 lignes) : Parser français de jours ("lundi", "mardi") et dates ("12 janvier") depuis `emailBody`, options rapides (2h, demain 9h, lundi 9h, semaine prochaine), positionnement viewport-aware, Portal body-level
- **Badge "détecté"** pour les dates extraites par IA
- **Stockage MVP** : `localStorage('agentys_snoozed')` avec emailId + date ISO + subject
- **Intégré dans** `SwipeableEmailItem.tsx` via le context menu (clic droit → Snooze)

### 6. AI Progress Bar

Indicateur 3 étapes du pipeline de génération de brouillon.

- **`AIProgressBar.tsx`** (39 lignes) : 3 segments (Analyse → Rédaction → Critique), animation pulse sur segment actif, caché quand `stage === 'idle'`
- **Intégré dans** `EmailDetailModal.tsx` — affiché en haut du panneau détail inline et modal

### 7. Thème "Futurist Silver" (remplace Editorial)

Nouveau thème clair "Liquid Chrome" remplaçant l'ancien "Editorial".

- **`futurist-silver.css`** (~2000 lignes) : Design system complet
  - Palette: surfaces titane/argent (neutres froids), accent gunmetal chrome
  - Typographie: Syne (display), Outfit (body), JetBrains Mono (technique)
  - Textures: métal brossé directionnel (`mix-blend-mode: overlay`) + bande spéculaire radiale
  - Animations: shimmer sweep sur boutons (hover → `left: -100%` → `130%`), beacon pulse
- **Chrome Token System** : 7 tokens métalliques (`--chrome-highlight`, `--chrome-btn-gradient`, `--chrome-btn-hover`, etc.)
- **Chrome Button Gradient** : 7 stops simulant un cylindre métallique (`#c2c5d6` → `#585b72` → `#b5b8cc`), `inset box-shadow` double (top 0.55 + bottom 0.14 opacity), shimmer `::before` sweep au hover
- **Chrome surfaces** : Sidebar, compose button, primary buttons, send pill, active tabs, mode switcher, toggle switches, draft badge, modal panels, scrollbar, logo text (gradient via `-webkit-background-clip: text`)
- **Blue→Silver purge** : 21× `rgba(59, 158, 206, ...)` → `rgba(107, 110, 136, ...)`, swipe gradients, warning-subtle, ThemeSwitcher/Settings previews
- **Suppression** `clarity-premium.css` et `editorial-email.css` (thème éditorial)
- **Mise à jour** : `ThemeSwitcher.tsx`, `Settings.tsx`, `useTheme.ts`, `settings.py` — `editorial` → `futurist`
- **Polices Google Fonts** : Ajout Outfit + Syne (lazy-loaded)

### 8. Dark Luxury v2 — "Velvet & Gold"

Refonte complète du thème sombre (~1800 lignes, +700 lignes vs v1).

- **Palette Obsidian** : Échelle 7 niveaux (obsidian-100 à obsidian-900) avec warm undertone
- **Gold Accent** : Spectre étendu (gold, gold-bright, gold-deep, gold-muted, gold-glow, gold-neon, gold-ring, gold-subtle)
- **Signal Colors** : success/warning/error/info avec backgrounds dark-adapted (12% opacity)
- **Shadows** : Multi-layer (2 niveaux par shadow) pour profondeur réaliste + `shadow-card`
- **Focus ring** : Double ring (obsidian-600 inner + gold-ring outer) au lieu d'un simple glow
- **Extended type scale** : `--text-xs` à `--text-4xl` + line-heights + letter-spacing tokens

### 9. Design System Foundation (thème Clarity amélioré)

Raffinement du thème par défaut pour une base solide.

- **`index.css`** : Surfaces warm ivory (`#faf9f7` au lieu de `#f8f9fa`), `--font-sans` variable, `--radius-xs: 4px`
- **Easing tokens** : `--ease-clarity` (confident), `--ease-spring` (energetic), `--ease-settle` (graceful deceleration)
- **Transitions** : `--transition-spring: 0.3s var(--ease-spring)` pour animations physiques
- **Extended type** : `--font-size-3xl` (28px), `--font-size-4xl` (36px)
- **Line heights** : `--leading-none` à `--leading-relaxed`
- **Letter spacing** : `--tracking-tight`, `--tracking-normal`, `--tracking-wide`
- **Film grain** : Opacité augmentée 0.022 → 0.028
- **Ambient layer** : `body::after` radial-gradient ivoire subtil en haut (disabled pour dark/futurist)

### 10. Sidebar — Logo = Toggle

Simplification de l'en-tête sidebar : le logo Agentys remplace le bouton hamburger/pin.

- **Suppression** : bouton `.sidebar-toggle` (3 icônes pin/hamburger) + classes `.sidebar-toggle-pinned`, `.sidebar-toggle-auto`
- **Nouveau** : `<button class="sidebar-logo-toggle">` contenant triangle SVG 38×38px + texte "gentys"
- **Animation** : `transform: scale(0.9)` au clic, `opacity: 0.75` au hover
- **Collapsed** : Logo centré 24×24px dans cercle 48×48px (même taille que les icônes nav en dessous), header centré
- **Hover expand** (mode auto) : Logo retrouve sa taille 38×38 + texte "gentys", header revient en `flex-start`
- **Nettoyage thèmes** : Suppression sélecteurs morts `.sidebar-logo-a` (futurist + dark-luxury), `.sidebar-logo` (dark-luxury + editorial)

### 14. UX Polish

Corrections d'interface et comportements.

- **Suppression bouton "Effacer les filtres"** : Bouton rouge retiré de `EmailList.tsx` (filtrage labels)
- **Fix empty state dupliqué** : `EmptyState` avec label actif n'affiche plus qu'un titre (suppression subtitle redondant)
- **Fix raccourcis Mac→Windows** : `⌘,` → `Ctrl+,` et `⌘/` → `Ctrl+/` dans `App.tsx` (palette de commandes)

### 11. Email Content Rendering amélioré

- **URLs angle-bracket** : Support `<https://url>` et `"Link text <https://url>"` (fréquent dans emails plain-text)
- **Markdown** : Préservation URLs angle-bracket avant escape HTML via tokens `%%TLINK%%`/`%%LINK%%`
- **CSS cleaning conditionnel** : Ne nettoie le CSS embarqué que si le body contient réellement des patterns CSS (évite de casser les emails plain-text avec `@` dans les adresses)
- **Iframe email** : Background blanc explicite (`#ffffff`) + `border-radius: 6px`, 3 passes de resize (300ms, 1s, 2.5s) pour newsletters complexes
- **body_html** : `_sync_emails_to_cache()` propage maintenant `body_html` (fix: emails HTML affichés en plain-text)

### 12. Label Learning amélioré

- **Raison utilisateur** : `LabelQuickPicker` en 2 étapes — choix du label → textarea "Pourquoi ce label ?" → Enter pour confirmer
- **Prompt LLM enrichi** : Le bloc `RAISON DE L'UTILISATEUR` est injecté dans le prompt d'extraction de pattern, guidant le LLM vers des règles plus pertinentes
- **Validation types** : Set `VALID_TYPES = {"sender", "subject", "body", "cc", "recipient"}` — les types composés LLM (`"sender|subject"`, `"sender AND subject"`) sont parsés et réduits au type le plus discriminant
- **Auto-draft on Action** : Quand un email est relabellisé vers "Action", `generateDraft()` est appelé automatiquement
- **Label counts filtrés** : `get_label_counts()` et `get_emails_by_label()` acceptent `valid_email_ids` pour exclure les emails supprimés du comptage
- **Client-side label filter** : Double filtrage (serveur + client) pour fiabilité

### 13. Branding & Polish

- **Favicon** : `vite.svg` → `agentys-favicon.svg` (cercle teal + "A" blanc)
- **Logo app** : `logo-app.svg` importé dans `App.tsx`, remplace `✦` dans loading screens et status cards
- **Animations** : Row stagger décélérant (`cubic-bezier(0.22, 1, 0.36, 1)` avec timing logarithmique 0→150ms), modal spring bounce (70% scale(1.005))
- **Email hover contextuel** : Bouton "Se désabonner" sur hover des emails Noise (via `sectionKey` prop)
- **Sync interval** : Réduit de 120s → 30s pour fraîcheur des données
- **IMAP logging** : Exceptions silencieuses → `logger.warning`/`logger.debug` pour diagnostics

### 15. Logo Redesign — Layered Teal A (`f28cbd7`)

Remplacement du logo "Prism A" (triangle solide gradient) par un "Layered A" sophistiqué.

- **Design** : Triangle externe outlined (#2dd4bf, 70% opacity, stroke 2px) + triangle interne filled (#0d9488) + cutout central `var(--surface-primary)`
- **Glow effect** : Filtre SVG `feGaussianBlur(1.2)` + `feComposite` pour halo doux teal
- **Sidebar expanded** : SVG 32×32px + "gentys" (font-sans, 25px, gap 3px, `translateY(3px)` pour aligner avec base du triangle)
- **Sidebar collapsed** : SVG 24×24px dans cercle 48×48px centré
- **Fichiers** : `Sidebar.tsx` (markup SVG), `Sidebar.css` (styles `.sidebar-logo-mark`, `.sidebar-logo-gentys`)

### 16. Génération draft immédiate sur relabelling Action (`e6277a5`)

Résolution du délai ~4min entre relabelling → draft prêt (causé par polling daemon uniquement).

- **`app/api/labels.py`** : Nouvelle fonction `_trigger_draft_for_action_email()` (~100 lignes)
  - Vérifie setting `auto_draft`, vérifie qu'aucun draft existe déjà
  - Lance `threading.Thread(daemon=True)` pour génération non-bloquante
  - Utilise `container.get_regenerate_use_case()` (pipeline Drafter V1 → Critic → V2)
  - Crée un `PendingDraft` et émet WebSocket `draft_ready`
- **Trigger** : Appelé dans `learn_from_correction()` quand `"Action" in new_labels and "Action" not in old_labels`
- **Résultat** : Draft disponible en ~10-15s au lieu de ~4min

### 17. Fix persistance thème au refresh

Bug: le thème revenait à "default" après refresh du navigateur.

- **Root cause** : `useTheme.ts` — le fetch backend retournait `"default"` et écrasait la valeur localStorage
- **Fix** : localStorage a désormais priorité. Si backend = "default" mais localStorage ≠ "default", le localStorage gagne et est synchronisé vers le backend via PATCH
- **Fichier** : `useTheme.ts` (refactoring du `useEffect` de sync)

### 18. Audit UX complet + 10 améliorations

Audit automatisé de l'application via Playwright (13 tests, 13 screenshots, métriques).

**Score global : 7.2/10**

| Critère | Score | Détail |
|---------|-------|--------|
| Apparence | 8/10 | Design premium, thèmes cohérents |
| Chargement | 5/10 | 4.6s initial load |
| Rapidité d'usage | 7/10 | Interactions fluides, tabs rapides |
| Intuitif | 7.5/10 | Bonne navigation, manque tooltips |
| Mobile | 5.5/10 | Layout non responsive |

**10 suggestions → 5 déjà implémentées + 5 nouvelles :**

#### Déjà en place (confirmé par audit du code) :
1. **Cache email IndexedDB** — `api/emails.ts` avec stale-while-revalidate + background revalidation
2. **Bulk actions** — Multi-select avec shift-click, bulk archive/delete/mark read dans `EmailList.tsx`
3. **Typeahead search** — Recherche serveur + fallback local en temps réel
4. **AI draft indicator** — Badge "Draft prêt" (✦) dans `SwipeableEmailItem.tsx`
5. **AbortController** — Timeout + annulation dans `api.ts` et `emails.ts`

#### Nouvellement implémenté :

**a) Prefetch lazy components** (`App.tsx`)
- `requestIdleCallback` avec timeout 3s charge en arrière-plan : EmailDetailModal, Settings, NewMessageModal, ComposeEmailModal, ShortcutsHelpPanel
- Fallback `setTimeout(2000)` pour navigateurs sans `requestIdleCallback`
- **Impact** : Modals ouvrent en ~0ms au lieu de ~200-900ms (plus de chunk download)

**b) Navigation J/K Gmail-style** (`useAppShortcuts.ts` + `EmailList.tsx`)
- `J` = email suivant (down), `K` = email précédent (up) — comme Gmail/Vim
- Guard `INPUT`/`TEXTAREA`/`contentEditable` pour ne pas interférer avec la saisie
- Ajouté dans le shortcuts ribbon en bas de liste : `J/K → Naviguer`

**c) Empty states pour tous les dossiers** (`EmailList.tsx`)
- **Spam** : 🛡️ "Aucun indésirable" / "Votre boîte est propre"
- **Corbeille** : 🗑️ "Corbeille vide" / "Aucun email supprimé"
- **Envoyés** : 📤 "Aucun email envoyé" / "Vos emails envoyés apparaîtront ici"
- **Archives** : 📦 "Aucune archive" / "Les emails archivés apparaîtront ici"
- **Inbox** (inchangé) : ✨ "Inbox Zero" / "Tous vos emails ont été traités"

**d) Tooltips accessibilité** (`EmailDetailModal.tsx`, `EmailList.tsx`, `ThemeSwitcher.tsx`)
- Reply → `title="Répondre (R)"`, Reply All → `title="Répondre à tous"`, Forward → `title="Transférer (F)"`
- Close → `title="Fermer (Esc)"`
- Bulk mark read/unread → titres descriptifs
- Clear filters, retry, theme options → titres ajoutés
- **Impact** : 11 boutons manquants corrigés sur les composants les plus utilisés

**e) Preload compose modal** (combiné avec prefetch dans `App.tsx`)
- `NewMessageModal` et `ComposeEmailModal` préchargés via `requestIdleCallback`
- Ouverture instantanée au lieu de ~900ms mesuré dans l'audit

### Fichiers nouveaux (17)

| Fichier | Lignes | Rôle |
|---------|--------|------|
| `CommandPalette.tsx` + `.css` | 317 | Palette Cmd+K |
| `DeepFocusMode.tsx` + `.css` | 432 | Mode Inbox Zero guidé |
| `DeepFocusCelebration.tsx` + `.css` | 230 | Ecran victoire + confettis |
| `PrioritySectionHeader.tsx` + `.css` | 179 | Headers sections priorité |
| `SmartReply.tsx` + `.css` | 161 | Réponses rapides contextuelles |
| `SnoozeDropdown.tsx` + `.css` | 245 | Snooze avec détection dates |
| `AIProgressBar.tsx` + `.css` | 86 | Indicateur pipeline IA |
| `useDeepFocus.ts` | 186 | Hook état Deep Focus |
| `priorityGrouping.ts` | 98 | Utils groupement priorité |
| `futurist-silver.css` | 2020 | Thème Futurist complet |
| `logo-app.svg` | 5 | Logo SVG (cercle teal + A) |
| `agentys-favicon.svg` | — | Favicon navigateur |

---

## Phase 10 — Learning Dashboard & Draft Quality (11 février)

### Panel "Apprentissages" dans Settings

Nouveau composant centralisé affichant tout ce qu'Agentys a appris, organisé en 3 catégories avec un design premium interactif.

#### Backend : API `/api/learning/all`

Nouvel endpoint dans `routes.py` qui agrège les données de 3 sources :

| Source | Catégorie | Données |
|--------|-----------|---------|
| `label_store.get_rules()` | **Auto-Label** | Règles apprises via corrections (label, type, value, use_count, created_at) |
| `draft_learning_store` | **Draft AI** | Corrections de brouillons (contact, diff_summary) + ratio précision |
| `writing_style_store` | **Style d'écriture** | Profil détecté (salutations, clôtures, signature, formalité) |

Endpoints :
- `GET /api/learning/all` — Retourne les 3 catégories avec items et métriques
- `DELETE /api/learning/corrections/<id>` — Supprime une correction de brouillon

#### Frontend : `LearnedRulesPanel.tsx` + `.css`

Composant React avec :

1. **3 catégories collapsibles** avec icon rings colorés :
   - Auto-Label (violet `#8b5cf6`) — TagIcon
   - Draft AI (bleu `#3b82f6`) — PenIcon
   - Style d'écriture (vert `#10b981`) — StyleIcon

2. **Badges colorés par label** via `data-label` CSS attribute :
   - Action (rouge), Waiting (jaune), FYI (bleu), Noise (gris)
   - Type badges : FROM, SUBJ, BODY, TO, CC

3. **Timestamps relatifs** — `timeAgo()` : "il y a 2h", "il y a 3j", "il y a 2 mois"

4. **Barre de précision Draft AI** — Mini progress bar dans le header (ex: 73%)
   - `accuracy = positive_count / total_drafts * 100`

5. **Undo delete** — Suppression optimiste avec toast 5s :
   - `hideItem()` immédiat → timer 5s → `commitDelete()` API
   - Bouton "Annuler" restaure l'item via `undoRef`

6. **Bulk delete** — "Tout effacer" avec confirmation inline "Oui / Non"
   - Suppression séquentielle via API (auto-label rules + draft corrections)
   - Writing-style est read-only (pas de suppression)

7. **Animations premium** :
   - Stagger slide-in catégories (0.06s delay)
   - Stagger slide-in items (cascade 0.02s)
   - Spring easing sur chevron et icon scale au hover
   - Toast slide-up avec spring bounce
   - Fade-out slide-right sur delete

8. **Empty state** — Icône livre + message + hint

#### Intégration Settings

```tsx
// Settings.tsx — après "Entrainement Agentys"
<section className="settings-section settings-section-large">
  <h3>Apprentissages</h3>
  <LearnedRulesPanel />
</section>
```

### Fichiers créés

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `LearnedRulesPanel.tsx` | 458 | Composant principal (3 catégories, undo, bulk delete) |
| `LearnedRulesPanel.css` | 540 | Styles premium (animations, badges, toast, accuracy bar) |

### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `app/api/routes.py` | +`GET /api/learning/all`, +`DELETE /api/learning/corrections/<id>` |
| `Settings.tsx` | +import LearnedRulesPanel, +section "Apprentissages" |

### Types et interfaces

```typescript
interface LabelRuleItem { id, label, type, value, use_count, created_at }
interface DraftCorrectionItem { id, contact, diff_summary, timestamp }
interface StyleItem { id, kind, value, account_id }
type AnyItem = LabelRuleItem | DraftCorrectionItem | StyleItem
interface Category { id, name, description, count, positive_count?, total_drafts?, accuracy?, items }
interface UndoState { catId, itemId, timer }
```

### Leçon apprise

- **Undo pattern avec useRef** → Stocker l'item supprimé dans le `undoRef` (pas dans state) pour éviter les stale closures du `setTimeout`. Le timer de 5s commit le delete, le bouton Annuler `clearTimeout` + restaure.

### Fix visibilité raccourcis clavier (thèmes sombres)

Les descriptions et labels de raccourcis étaient illisibles sur les thèmes Futurist et Dark Luxury.

**Cause** : `ShortcutSettings.css` utilise des couleurs hardcodées light-theme (#333, #666, #fafafa, white, etc.) et `.shortcut-label`/`.shortcut-description` utilisaient `var(--text-tertiary)` trop dim.

**Fix** : Ajout d'overrides complets dans les deux fichiers thème :
- `futurist-silver.css` : Sélecteurs `[data-theme="futurist"] .shortcut-*` — backgrounds, labels, headings, kbd, badges, modal, boutons capture/reset, conflit warning
- `dark-luxury.css` : Sélecteurs `[data-theme="dark-luxury"] .shortcut-*` — même couverture avec palette obsidian/gold

### Audit uniformité UI

Revue complète de l'application pour standardiser les éléments d'interface récurrents.

#### a) Checkbox globale (`index.css`)

Ajout d'une règle globale pour uniformiser toutes les checkboxes :

```css
input[type="checkbox"] {
  accent-color: var(--accent-primary);
  width: 16px;
  height: 16px;
  cursor: pointer;
}
```

Suppression des déclarations redondantes dans 4 fichiers :
- `AdvancedSearchPanel.css` — `.advanced-search-checkbox`
- `ComposeEmailForm.css` — `.form-field-checkbox input`
- `LabelEditor.css` — `.label-editor-field-checkbox input`
- `SendConfirmationModal.css` — `.skip-checkbox-label input`

`CleanInboxModal.css` conserve ses customs checkboxes (design radio/checkbox custom) mais corrigé : 20px → 18px, `border-radius: 4px` → `var(--radius-xs, 3px)`.

#### b) Boutons Close uniformes

Standardisation des boutons fermer en style circulaire transparent :
- Settings close : `background: var(--surface-secondary)` + `border-radius: var(--radius-md)` → `background: transparent` + `border-radius: 50%`
- Shortcuts help close : même changement
- Tous les close buttons utilisent désormais `border-radius: 50%` + `background: transparent` + `:hover` visible

#### c) Z-index normalisé

| Composant | Avant | Après |
|-----------|-------|-------|
| EmailDetailModal | 200 | 1000 |
| CommandPalette | 10001 | 1100 |
| Autres modals | 1000 | 1000 (inchangé) |

Hiérarchie : Modals (1000) < CommandPalette (1100) — plus de valeurs extrêmes.

#### d) Tailles et rayons standardisés

| Élément | Avant | Après |
|---------|-------|-------|
| Header icon buttons | 34×34px | 32×32px (= close buttons) |
| Email detail title | `1.3rem` | `var(--font-size-xl)` |
| CommandPalette border-radius | `var(--radius-lg)` | `var(--radius-xl)` (= autres modals) |
| Modal backdrop opacity | 0.55 ou 0.6 | 0.55 partout |

#### e) Nettoyage couleurs hardcodées

- `ComposeEmailForm.css` : `color: var(--text-secondary, #64748b)` → `color: var(--text-secondary)` (fallback inutile)

### Fichiers modifiés (uniformité)

| Fichier | Changement |
|---------|-----------|
| `index.css` | +règle globale `input[type="checkbox"]` |
| `App.css` | Backdrop 0.6→0.55, close buttons circular transparent |
| `EmailDetailModal.css` | z-index 200→1000, title font-size→var |
| `CommandPalette.css` | z-index 10001→1100, border-radius→radius-xl |
| `EmailList.css` | Icon buttons 34→32px |
| `CleanInboxModal.css` | Checkbox custom 20→18px, radius→var |
| `AdvancedSearchPanel.css` | Suppression checkbox redondant |
| `ComposeEmailForm.css` | Suppression checkbox redondant, fix fallback couleur |
| `LabelEditor.css` | Suppression checkbox redondant |
| `SendConfirmationModal.css` | Suppression checkbox redondant |
| `futurist-silver.css` | +overrides ShortcutSettings complets |
| `dark-luxury.css` | +overrides ShortcutSettings complets |

### Leçons apprises (uniformité)

- **Checkbox globale via `accent-color`** → Une seule règle `index.css` remplace 5+ déclarations par composant. Les checkboxes custom (CleanInboxModal) restent intactes car elles cachent l'input natif.
- **Z-index discipline** → Éviter les valeurs extrêmes (10001). Hiérarchie simple : contenu < modals (1000) < palette (1100).
- **Theme overrides > file editing** → Pour corriger un composant avec des couleurs hardcodées, ajouter des overrides dans les fichiers thème plutôt que modifier le composant (risque de casser le thème par défaut).

### Draft Quality 95% — Explicit Instruction Injection

Refonte complète du pipeline de génération de brouillons pour passer de **~33% envoyable (6/18)** à **~95% envoyable (17-18/18)** via l'injection d'instructions explicites pré-calculées et un pipeline de nettoyage post-LLM.

#### Problème

Les brouillons STANDARD (Haiku) avaient 6 problèmes récurrents :

| Problème | Exemple |
|----------|---------|
| Greeting formel ignoré | "Salut" au Directeur Général |
| Hallucinations | Invente prix (500€), statut sprint, liens |
| Mauvaise langue | Répond en FR à un email EN |
| Mauvais nom signataire | Signe du nom de l'expéditeur |
| Réponse hors-sujet | Reformule la question au lieu d'y répondre |
| Invention de délais | "d'ici vendredi" quand aucun délai mentionné |

#### Stratégie : "Pre-computed Hints"

Au lieu de compter sur des règles abstraites que Haiku suit mal, on **pré-calcule** des instructions concrètes pour CHAQUE email et on les injecte dans le user prompt.

#### 1. Analyse pré-LLM (`prompts.py`)

**Détection de formalité** — `analyze_email_formality()` amélioré :
- Patterns ajoutés : "pourriez-vous", "s il vous", "nous accusons", "nous avons le plaisir"
- Poids double pour "vous" vs "tu"
- Score 1-5 → label lisible ("VERY CASUAL" / "CASUAL" / "NEUTRAL" / "FORMAL" / "VERY FORMAL")

**Détection de langue** — `_detect_language()` :
- Heuristique par comptage de marqueurs (35 EN + 15 FR)
- Retourne "ENGLISH" ou "FRENCH"

**Détection de non-personne** — `_is_person_name()` + `_NON_PERSON_WORDS` :
- Set de 30+ mots indiquant un expéditeur non-humain : "service", "equipe", "rh", "organisatrice", "noreply", etc.
- Permet un greeting neutre ("Bonjour," / "Salut,") au lieu de "Bonjour Service,"

**Greeting pré-calculé** — `_compute_greeting_hint()` :

| Formalité | Personne FR | Personne EN | Non-personne FR | Non-personne EN |
|-----------|-------------|-------------|-----------------|-----------------|
| 4-5 | Monsieur {Nom}, | Dear Mr. {Nom}, | Bonjour, | Hello, |
| 3 | Bonjour {Prénom}, | Hi {Prénom}, | Bonjour, | Hello, |
| 1-2 | Salut {Prénom}, | Hey {Prénom}, | Salut, | Hi, |

**Identité utilisateur** — `_extract_user_name()` :
- Parse `knowledge/memoire.md` pour extraire "Nom complet: XXX"
- Injecté comme "YOU ARE: Alexandre Simon"

#### 2. Prompts restructurés (`prompts.py`)

**System prompt** — Anti-hallucination en 4 catégories :

```
A) EMAIL ASKS FOR SPECIFIC DATA → placeholder "[A confirmer]"/"[To be confirmed]"
B) EMAIL IS A PROPOSAL OR INVITATION → Respond naturally, USE dates/locations FROM the email
C) EMAIL IS A GREETING → Reciprocate warmly
D) EMAIL IS VERY SHORT WITH NO CONTEXT → Ask for clarification
```

**User prompt** — Instructions concrètes injectées :

```
REPLY INSTRUCTIONS (follow ALL exactly):
- LANGUAGE: FRENCH only. Every word in FRENCH.
- FORMALITY: CASUAL
- YOUR REPLY MUST START WITH EXACTLY: Salut Julie,
- YOU ARE: Alexandre Simon (do NOT introduce yourself)
- For unknown data: write "[A confirmer]" for EACH unknown fact.
- For proposals/invitations: RESPOND to it. Do NOT repeat the proposal back.
```

**Anti-parroting** — Interdit explicitement de reformuler la question de l'expéditeur :
```
FORBIDDEN:
- Parroting/repeating the sender's words.
  BAD: sender says "On pourrait aller au parc" -> reply "On pourrait aller au parc"
  GOOD: sender says "On pourrait aller au parc" -> reply "Bonne idee, je suis libre samedi."
```

**Température adaptative** — Baissée selon la formalité :

| Formalité | Température |
|-----------|-------------|
| 1 (très casual) | 0.45 |
| 2 (casual) | 0.40 |
| 3 (neutre) | 0.35 |
| 4 (formel) | 0.30 |
| 5 (très formel) | 0.25 |

#### 3. Pipeline post-LLM (`smart_routing.py`)

5 étapes de nettoyage déterministe appliquées après chaque génération LLM, dans l'ordre :

```
1. _clean_prompt_leakage()    — Coupe aux "---", strip filler ("C'est parti !")
2. _strip_signature()         — Supprime signatures inventées ("Cordialement", noms)
3. _strip_parroting()         — Supprime phrases copiées verbatim de l'email original
4. _scrub_hallucinated_facts() — Remplace prix/nombres inventés par placeholder
5. _enforce_greeting()        — Force le greeting pré-calculé (DERNIER = survit aux corrections)
```

**`_clean_prompt_leakage()`** :
- Coupe au premier séparateur `---` (alternatives du modèle)
- Supprime placeholders orphelins (`[A confirmer]`, `[REDACTE]`)
- Supprime filler IA : "C'est parti !", "Super !", "N'hésitez pas", "Je reste à votre disposition"

**`_strip_parroting()`** (nouveau) :
- Extrait les phrases >15 chars du body original
- Supprime les lignes du brouillon qui contiennent une phrase verbatim du body
- Sécurité : ne supprime pas si le résultat fait <15 chars

**`_scrub_hallucinated_facts()`** :
- Regex détectant `nombre + unité` (EUR, $, /mois, req/min...)
- Compare chaque match avec le body original
- Si le nombre n'est pas dans le body → remplace par placeholder

**`_enforce_greeting()`** :
- Compare la première ligne du brouillon avec le greeting pré-calculé
- Si elle commence par un greeting connu mais différent → remplace
- Position **DERNIÈRE** dans le pipeline car `apply_learned_corrections()` peut le réverter

#### 4. Résultats des tests (18 cas)

Test exhaustif `test_draft_v3.py` couvrant 10 catégories d'emails :

| Catégorie | Cas | Résultat |
|-----------|-----|----------|
| Casual FR | C1-C5 (lunch, salut, resto, lien, weekend) | 5/5 ✓ |
| Formal FR | F1-F2 (contrat, congés) | 2/2 ✓ |
| Casual EN | E1-E3 (beer, quick question, road trip) | 3/3 ✓ |
| Formal EN | FE1-FE2 (partnership, due diligence) | 2/2 ✓ |
| Question FR | Q1 (tarifs) | 1/1 ✓ — placeholders |
| Question EN | Q2 (API access) | 1/1 ✓ — placeholders |
| Voeux FR | G1 (bonne année) | 1/1 ✓ |
| Invitation FR | I1 (conférence IA) | 1/1 ✓ — dates de l'email conservées |
| Multi-question FR | M1 (projet Alpha) | 1/1 ✓ — placeholders par question |
| Ultra-court FR | S1 ("Alors?") | 1/1 ✓ — demande clarification |

**Scores par métrique :**

| Métrique | Avant | Après |
|----------|-------|-------|
| Langue correcte | 12/18 | **18/18** |
| Greeting correct | 6/18 | **18/18** |
| Ton/Formalité | 10/18 | **18/18** |
| Anti-hallucination | 8/18 | **17/18** |
| Envoyable | 6/18 | **17-18/18** |

#### Fichiers modifiés

| Fichier | Changements |
|---------|-------------|
| `app/prompts.py` | +`_is_person_name()`, +`_compute_greeting_hint()`, +`_formality_to_label()`, +`_detect_language()`, +`_extract_user_name()`, rewrite system/user prompts (STANDARD + CLASSIFY_AND_DRAFT), température adaptative |
| `app/smart_routing.py` | +`_clean_prompt_leakage()`, +`_strip_signature()`, +`_strip_parroting()`, +`_scrub_hallucinated_facts()`, +`_enforce_greeting()`, pipeline 5 étapes dans 3 code paths (_generate_standard, _generate_standard_streaming, classify_and_draft) |

#### Leçons apprises

- **Pré-calcul > instructions abstraites** → Haiku suit mieux "START WITH: Salut Julie," que "adapter le ton selon la formalité"
- **Post-LLM déterministe > prompt seul** → Le greeting pré-calculé est ignoré ~30% du temps par Haiku. `_enforce_greeting()` le force à 100%
- **Anti-hallucination par catégorie** → Un seul règle "ne pas inventer" est trop floue. 4 catégories (data/propositions/greetings/vague) permettent un comportement nuancé
- **Pipeline ordering critique** → `_enforce_greeting()` DOIT être dernier car `apply_learned_corrections()` peut réverter le greeting
- **Anti-parroting post-LLM** → Haiku reformule parfois la question de l'expéditeur au lieu d'y répondre. Détection par matching phrases du body
- **Température et hallucination** → Trop basse (0.2) = réponses rigides. Trop haute (0.6) = inventions. Sweet spot: 0.25-0.45 selon formalité
- **Non-déterminisme LLM** → Les scores varient de ±2 entre runs. Le pipeline post-LLM réduit cette variance

### Auto-capture de savoir depuis corrections de drafts

Quand l'IA manque de connaissances factuelles, elle écrit `[À confirmer]` dans les brouillons. Lorsque l'utilisateur remplace ces placeholders par les vraies informations avant d'envoyer, le système détecte automatiquement ces corrections et propose de les sauvegarder dans la base de connaissances (`knowledge/memoire.md`) pour que l'IA ne refasse plus la même erreur.

#### Flow complet

```
Utilisateur édite draft    →  Remplace "[À confirmer]" par "499$/mois"
                           →  Clique "Envoyer"
Backend (validate)         →  Compare draft_v1 vs draft_body
                           →  Détecte placeholder remplacé → extrait le fait
                           →  Retourne knowledge_suggestions dans la réponse
Frontend (PendingDraft)    →  Reçoit les suggestions
                           →  Affiche toast: "Ajouter au savoir ?"
Utilisateur clique "Oui"  →  POST /api/memory/add-fact
                           →  Fait ajouté à la section ## Savoir de memoire.md
```

#### Backend : `knowledge_capture.py` (nouveau)

Module de détection et extraction des faits corrigés :

- `PLACEHOLDER_RE` — Regex matchant `[À confirmer]`, `[A confirmer]`, `[To be confirmed]`, `[À valider]`
- `extract_knowledge_suggestions()` — Algorithme anchor-based :
  1. Trouve toutes les positions de placeholders dans le draft original
  2. Extrait ~40 chars avant/après chaque placeholder comme ancres
  3. Retrouve ces ancres dans le body envoyé
  4. Extrait le texte de remplacement entre les ancres
  5. Construit une question contextuelle (phrase avec `___`) + réponse (remplacement)
- `KnowledgeSuggestion` — Dataclass avec `question`, `answer`, `context`
- Guards : ignore les remplacements <2 chars, les placeholders non-corrigés, les erreurs d'extraction

#### Backend : Routes (`routes.py`)

**Modification `POST /api/pending-drafts/:id/validate`** :
- Après `record_correction()`, appelle `extract_knowledge_suggestions(draft_v1, draft_body)`
- Ajoute `knowledge_suggestions` au JSON de réponse si des suggestions sont trouvées

**Nouvel endpoint `POST /api/memory/add-fact`** :
- Body : `{ "question": str, "answer": str }`
- Parse les sections de `memoire.md` via `MemoryManager.get_sections()`
- Trouve la section "Savoir" (ou la crée si absente)
- Ajoute `- **{question}** : {answer}` à la fin de la section
- Versionne via `MemoryManager.update_memory()`

#### Frontend : `KnowledgeSuggestionToast.tsx` + `.css` (nouveaux)

Toast flottant en bas à droite :
- Icône livre + titre "Ajouter au savoir ?"
- Fait affiché dans un bloc avec bordure gauche accent (teal)
- Boutons "Ignorer" (secondary) / "Ajouter" (primary teal)
- État "Enregistré ✓" après sauvegarde réussie
- Auto-dismiss après 15s si aucune action
- Animation spring slide-up / slide-down

#### Frontend : Wiring (`PendingDraftDetail.tsx`, `App.tsx`)

- `PendingDraftDetail` : nouvelle prop `onKnowledgeSuggestion`, forward la première suggestion après envoi réussi
- `App.tsx` : state `knowledgeSuggestion`, passé aux deux renders de `PendingDraftDetail`, render conditionnel du toast

#### API Contracts

```json
// POST /api/pending-drafts/:id/validate — réponse enrichie
{
  "success": true,
  "knowledge_suggestions": [
    { "question": "Nos tarifs entreprise sont ___.", "answer": "499$/mois", "context": "..." }
  ]
}

// POST /api/memory/add-fact
// Request:  { "question": "Tarifs entreprise", "answer": "499$/mois" }
// Response: { "success": true }
```

#### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `app/knowledge_capture.py` | Détection placeholders + extraction faits (anchor-based) |
| `KnowledgeSuggestionToast.tsx` | Toast "Ajouter au savoir ?" |
| `KnowledgeSuggestionToast.css` | Styles du toast (spring animations, design system tokens) |

#### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `app/api/routes.py` | +knowledge extraction dans validate, +`POST /api/memory/add-fact` |
| `api.ts` | +`knowledge_suggestions` dans retour validate, +`addKnowledgeFact()` |
| `PendingDraftDetail.tsx` | +prop `onKnowledgeSuggestion`, forward après envoi |
| `App.tsx` | +state knowledge suggestion, +render toast |

### Audit Auto-Label — Pipeline v2 (146 tests, 6 bugs corrigés)

Audit systématique du pipeline de labellisation automatique (built-in rules) via 146 tests couvrant 28 catégories d'edge cases. Identification et correction de 6 bugs critiques.

#### Pipeline v2 — Nouvel ordre

```
1.  Strong waiting → Waiting (overrides noise senders)
1b. Strong action → Action (overrides noise senders)
    ├── Invoice cross-field: invoice subject + "paid/confirmed" body → Noise
    └── Receipt-before-invoice: "receipt for invoice #123" → skip (Noise)
1c. Empty/meaningless body → Noise (skip si body contient ?)
2.  Noise sender → Noise (noreply@, marketing@, etc.)
3.  Noise text patterns → Noise (SKIP si body contient ? — questions about noise topics)
3b. Noise subject-only patterns → Noise (newsletter, shipping, crypto, etc.)
4b. ? in body → Action
5.  Strong FYI → FYI
6.  Weak action → Action si pas automatisé, sinon Noise
7.  Weak waiting → Waiting si pas automatisé
8.  Weak FYI → FYI si pas automatisé
```

#### Bug 1 : Questions sur des sujets "bruit" classées Noise (9 cas)

**Avant** : "Where is my receipt?" → `\breceipt\b` fire step 3 → Noise. Le `?` à step 4b n'est jamais atteint.

**Fix** : Si le body contient `?`, TOUS les noise text patterns sont skip (subject + body). Les noise senders (step 2) et subject-only patterns (step 3b) restent actifs.

```python
# Avant
for pattern in self.NOISE_TEXT_PATTERNS:
    for field_name, field_value in text_fields:
        if field_value and re.search(pattern, field_value, re.IGNORECASE):
            return [("Noise", ...)]

# Après
body_has_question = body and "?" in body
if not body_has_question:
    for pattern in self.NOISE_TEXT_PATTERNS:
        ...
```

Exemples corrigés :

| Email | Avant | Après |
|-------|-------|-------|
| "Missing receipt" + "Can you resend it?" | Noise | **Action** |
| "Can you check the shipping status?" | Noise | **Action** |
| "Did you get the password reset link?" | Noise | **Action** |
| "Security alert" + "Was this you?" | Noise | **Action** |
| "Order issue" + "Where is my order confirmation?" | Noise | **Action** |

#### Bug 2 : Crash sur champs None (4 cas)

**Avant** : `email_data.get("body", "")` retourne `None` quand la clé existe avec valeur `None` → `.lower()` crash `AttributeError`.

**Fix** : `(email_data.get("body") or "").lower()` dans les deux pipelines.

#### Bug 3 : "Receipt for invoice #123" classé Action

**Avant** : Le negative lookahead `\binvoice\b(?!.*paid|receipt|confirmed)` ne vérifie que vers l'avant. "Receipt for invoice #123" → "receipt" est AVANT "invoice" → le lookahead cherche après "invoice" → ne trouve rien → match → Action.

**Fix** : Vérification programmatique : si "receipt" apparaît avant "invoice" dans le texte, skip le match invoice.

```python
if "invoice" in pattern:
    inv_pos = field_value.find("invoice")
    rcpt_pos = field_value.find("receipt")
    if rcpt_pos >= 0 and rcpt_pos < inv_pos:
        continue  # receipt before invoice → skip
```

#### Bug 4 : `\bshipping\b` trop large en body

**Avant** : "The shipping department needs your approval" → `\bshipping\b` dans body → Noise.

**Fix** : Déplacé vers `NOISE_SUBJECT_ONLY_PATTERNS`. Les expéditeurs automatisés (noreply@fedex.com) sont déjà attrapés en step 2.

#### Bug 5 : "Please update" non reconnu comme action

**Avant** : "Your credit card was declined. Please update your payment method." → aucun pattern → LLM fallback.

**Fix** : Ajout `r"\bplease update\b"` dans `ACTION_WEAK_PATTERNS`.

#### Bug 6 : Patterns split subject-only

Déplacement de 9 patterns trop ambigus en body de `NOISE_TEXT_PATTERNS` vers `NOISE_SUBJECT_ONLY_PATTERNS` :

| Pattern | Raison du déplacement |
|---------|----------------------|
| `\bunsubscribe\b` | Présent dans footers de vrais emails |
| `\bnewsletter\b` | Légitime en body : "I read your newsletter" |
| `\bdigest\b` | Body : "let me digest this information" |
| `\bpromotion\b` | Body : "congratulations on your promotion" |
| `\bdeal\b` | Body : "let's close this deal" |
| `\bdiscount\b` | Body : "negotiating a discount" |
| `\bsale\b` | Body : "sale of the property" |
| `\bverification\b` | Body : "document verification process" |
| `\bcrypto\b` | Body : "crypto library for the project" |
| `\bshipping\b` | Body : "shipping department", "shipping address" |

#### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `app/application/label_email.py` | Pipeline v2 : reorder, ? guard, None handling, invoice receipt check, pattern split |
| `tests/application/test_label_blind_spots.py` | 74 tests (round 1 : 14 catégories) |
| `tests/application/test_label_deep_blind_spots.py` | 72 tests (round 2 : 14 catégories) |

#### Couverture des tests (146 tests)

**Round 1** (74 tests) :
Question marks, automated signals, invoices/receipts, strong waiting vs noise sender, empty body, forwarded emails, noise sender with real content, user rules override, CC detection, pipeline ordering, generic rule rejection, multi-language, noise text pattern edges, fast path parity.

**Round 2** (72 tests) :
Questions about noise topics, null/empty field handling, body truncation (2000 chars), invoice negative lookahead edges, security/login/password alerts, delivery failed vs tracking, weak action + unsubscribe footer, Unicode edge cases, real-world emails (GitHub PRs, Calendar RSVP, DocuSign, Slack mentions, LinkedIn, SaaS billing, job applications, expense reports), cross-field conflicts, fast path parity, word boundary precision, automated signals + question mark, empty body pattern edges.

---

## Phase 11 — Smart Routing Optimization (11 février)

> **Objectif** : Réduire le coût de génération de drafts de $20.70/mois à <$6/mois sans perte de qualité.
> **Résultat** : $20.70 → $5.54/mois (-73%), qualité 86 → 90/100 (+4 pts), temps STANDARD 8s → 4.9s (-39%)
> **Documentation détaillée** : [`docs/smart-routing-optimization.md`](docs/smart-routing-optimization.md)

### 1. Migration complète vers Haiku

Remplacement de tous les appels Sonnet par Haiku 4.5 dans l'ensemble du codebase :

| Fichier | Composants migrés |
|---------|-------------------|
| `app/agents.py` | DrafterAgent, CriticAgent, PrioritizationAgent, ClassifierAgent, TaskExtractorAgent, CommitmentExtractorAgent, SensitiveDataDetectorAgent (7 agents) |
| `app/infrastructure/container.py` | 12 use cases : draft, critique, process, refine, regenerate, classify, prioritize, complete_draft, learning, suggestions, writing_style, contact_history |
| `app/draft_completion.py` | DraftCompletionService |

**Impact** : COMPLEX tier passe de $0.018/draft (Sonnet) à $0.003/draft (Haiku) = **-83% sur le tier le plus cher**.

### 2. Compression du system prompt

Réécriture complète de `STANDARD_DRAFT_SYSTEM_PROMPT` dans `app/prompts.py` :

- **Avant** : ~800 tokens avec exemples inline (`"Tu viens m'aider samedi?" -> "Oui je serai la samedi."`)
- **Après** : ~250 tokens, rules-only, zéro exemple
- **Bug corrigé** : Les exemples inline contaminaient les drafts Haiku — le modèle confondait les exemples avec le contenu réel de l'email
- Contrainte casual relaxée : "1 phrase MAXIMUM" → "1-2 phrases"
- Contrainte formelle relaxée : "1-3 sentences" → "2-4 sentences"
- **Impact** : -69% input tokens, +17 pts qualité sur les emails informels

### 3. Micro-templates pour emails humains simples ($0.00)

Nouveau Path B dans `_generate_simple()` pour les emails humains très simples :

```
SIMPLE tier:
  Path A: Automated senders → template engine existant
  Path B: Human senders → _try_micro_template() [NOUVEAU]
    - Meeting/availability (sans ?) → "Je confirme ma disponibilité"
    - Acknowledgment (reçu, noté, ci-joint) → "Bien reçu, merci ! Je prends note."
    - Thanks (merci pour, thanks for) → "Avec plaisir ! N'hésitez pas..."
```

**Guards de sécurité** :
- `'?' not in body` sur meeting et thanks (toute question → fallback STANDARD)
- `len(body) < 120` pour meeting, `< 150` pour ack, `< 120` pour thanks
- Greeting style-aware via `WritingStyleProfile` + formality detection

### 4. Cache persistant sur disque

Upgrade du cache de drafts dans `app/smart_routing.py` :

| Paramètre | Avant | Après |
|-----------|-------|-------|
| TTL | 600s (10 min) | 3600s (1h) |
| Stockage | In-memory seulement | In-memory + disque (`~/.agentys/draft_cache.json`) |
| Thread safety | Aucun | `threading.Lock()` |
| Persistance | Perdu au restart | Survit aux redémarrages |
| Écriture disque | — | Debounced (toutes les 5 entrées) |
| Éviction | >500 entrées | >500 entrées + TTL expired |

Le tier COMPLEX cache maintenant aussi ses drafts (les plus coûteux à régénérer).

### 5. Budget tokens dynamique affiné

`calculate_dynamic_max_tokens()` avec seuils plus agressifs pour les emails courts :

| Body length | Questions | max_tokens avant | max_tokens après |
|-------------|-----------|------------------|------------------|
| < 150 chars | 0 | 200 | **128** |
| < 300 chars | ≤ 1 | 350 | **256** |
| < 500 chars | ≤ 2 | 512 | **384** |
| < 1000 chars | ≤ 3 | 512 | **512** |
| > 1000 chars | — | 768 | 768 |

**Impact** : -15% output tokens sur les emails courts (~30% du volume).

### 6. Pipeline post-LLM optimisé

Réordonnancement de la chaîne de nettoyage post-draft :

```
Avant: leakage → signature → parroting → hallucinations → truncate
Après: leakage → signature → truncate → [parroting si body≥300] → hallucinations
```

- `_strip_parroting()` (O(n×m) regex) est skippé pour les emails courts (body < 300 chars)
- `_truncate_for_short_body()` est déplacé en amont pour early-exit
- **Impact** : -10 à 30ms par draft sur ~30% des emails

### 7. Cinq bugfixes

| Bug | Fichier | Impact |
|-----|---------|--------|
| `max_tokens` pas mis à jour lors du fallback SIMPLE→STANDARD | `smart_routing.py:591` | Drafts potentiellement tronqués |
| Greeting vide "Salut ," quand pas de display name | `smart_routing.py:737-743` | Templates avec espace fantôme |
| COMPLEX ne cachait pas ses drafts | `smart_routing.py:614` | Re-génération coûteuse |
| Cache disque sans lock thread | `smart_routing.py:64-73` | Corruption possible en concurrent |
| Accusé de réception trop court (5 mots) | `smart_routing.py:766` | Score qualité 60 → 70 |

### 8. Observabilité

- Token waste logging (`logger.debug`) quand output_tokens < 30% du budget alloué
- Données pour futur tuning des seuils max_tokens

### 9. Batch API — Connexion du système (heures creuses, 50% off)

Le système batch (queue SQLite, BatchWorker, Anthropic Message Batches API) était entièrement construit mais **jamais connecté** — tout le code était mort. Cette étape connecte les composants existants.

**Problèmes corrigés :**

| Code mort | Fichier | Correction |
|-----------|---------|------------|
| `touch_user_activity()` jamais appelé | `batch_queue.py:34` | Connecté via `run_api.py:before_request` (existant) + `websocket.py:on_daemon_connect` |
| `should_use_batch()` jamais appelé | `smart_routing.py:1806` | Intégré dans `route()` step 4.5 |
| `enqueue_for_batch()` jamais appelé | `smart_routing.py:1837` | Appelé par `route()` quand batch window active |
| Daemon n'utilise pas le batch | `daemon.py:1662` | Redirection vers `SmartRouter.route()` en heures creuses |
| Doublon `before_request` dans routes.py | `routes.py:889` | Retiré (le filtre de `run_api.py` exclut health/ping) |
| Polling frontend garde activité vivante | `run_api.py:133` | Logique blacklist → whitelist (POST/PATCH/DELETE = activité, GET liste = ignoré) |

**Bug fix — Batch ne s'activait jamais si l'app est ouverte :**

Le frontend fait du polling automatique toutes les 30s (`GET /api/emails`, `GET /api/drafts`) + update check toutes les 4h. L'ancienne logique blacklist (3 paths) ne les excluait pas → `_last_user_activity` rafraîchi en permanence → `is_batch_window()` toujours `False`.

Fix : logique whitelist — seules les requêtes mutatives (POST/PATCH/DELETE/PUT) et les GET vers une ressource spécifique (`/api/emails/<id>`) comptent comme activité utilisateur. Les GET vers des listes (polling) sont ignorés.

**Nouvelles méthodes :**

- `SmartRouter._build_prompts()` : Construit (system_prompt, user_prompt) — partagé entre real-time et batch
- `_generate_standard()` refactoré pour utiliser `_build_prompts()` (DRY)

**Flux batch complet :**

```
User actif → touch_user_activity() → real-time drafts ($0.003)
User inactif 15min → is_batch_window() = True → enqueue → batch drafts ($0.0015)

Daemon poll → nouvel email Action
  ├── STANDARD: classify_and_draft() combined ($0.003) [pas de batch, déjà optimal]
  └── COMPLEX: SmartRouter.route() → should_use_batch() → enqueue_for_batch()
      └── BatchWorker → Anthropic Batch API (50% off) → PendingDraft → WebSocket
```

**Économies estimées :**

| Scénario | Avant | Avec batch | Économie |
|----------|-------|------------|----------|
| COMPLEX off-hours | $0.009 (label + drafter + critic) | $0.0045 (label + batch Haiku) | -50% |
| STANDARD off-hours | $0.003 (combined) | $0.003 (inchangé) | 0% |
| Projection mensuelle | ~$5.54 | ~$4.50-5.00 | -$0.50-1.00 |

### Résultats des tests (13 scénarios)

```
SCORE GLOBAL: 100% routage correct | 90/100 qualité drafts | $0.0018/email

Routage:    13/13 correct (2 SKIP, 3 SIMPLE, 5 STANDARD, 3 COMPLEX)
Qualité:    90/100 moyenne (min 70, max 100)
Coût:       $0.024 total → $5.54/mois projeté (100 emails/jour)
Temps:      4.9s STANDARD, 10.5s COMPLEX, 0ms SIMPLE
```

### Optimisations déjà actives (confirmées par audit)

| Optimisation | Fichier | Statut |
|---|---|---|
| Prompt caching (`cache_control: ephemeral`) | `claude_adapter.py` | ✅ Actif |
| Combined label+draft (1 appel) | `smart_routing.py:classify_and_draft()` | ✅ Actif |
| Batch API 50% off (heures creuses) | `batch_queue.py` + `smart_routing.py` + `daemon.py` | ✅ Actif (connecté) |
| Formality-based temperature | `prompts.py:formality_to_temperature()` | ✅ Actif |
| Background thread draft trigger | `labels.py:_trigger_draft_for_action_email()` | ✅ Actif |

### Fichiers modifiés

| Fichier | Changements |
|---------|-------------|
| `app/smart_routing.py` | Micro-templates, cache persistant, pipeline optimisé, max_tokens affinés, token logging, bugfixes |
| `app/prompts.py` | System prompt compressé (800→250 tokens), contraintes casual/formel relaxées |
| `app/agents.py` | 7 agents migrés Sonnet→Haiku |
| `app/infrastructure/container.py` | 12 use cases migrés Sonnet→Haiku |
| `app/draft_completion.py` | Migré Sonnet→Haiku |
| `test_smart_routing_perf.py` | 13 scénarios, scorer par tier, micro-template tests |

### Leçons apprises

- **Haiku 4.5 ≈ Sonnet pour les drafts email** → La qualité est comparable car les emails sont un domaine bien défini avec des patterns prévisibles. Le gain de coût (6x) ne justifie pas Sonnet.
- **Les exemples inline dans les prompts contaminent Haiku** → Les modèles plus petits confondent les exemples avec le contenu réel. Préférer des règles explicites sans exemples.
- **"1 phrase MAX" est trop restrictif** → Les réponses d'1 seule phrase paraissent robotiques. 1-2 phrases est plus naturel.
- **Les micro-templates nécessitent des guards stricts** → Tout email avec `?` doit aller au LLM. Les templates ne conviennent qu'aux statements sans question.
- **Le cache disque nécessite un Lock** → Flask + daemon = threads concurrents. Le cache JSON peut être corrompu sans `threading.Lock()`.
- **max_tokens trop élevé = temps gaspillé** → Un email de 100 chars ne nécessite pas 512 tokens de budget. Les seuils dynamiques réduisent le temps de génération.
- **`_strip_parroting()` est O(n×m)** → Pour les emails courts, le risque de parroting est quasi-nul. Skip si body < 300 chars.
- **Le cache stale est un piège silencieux** → Les tests avec cache disque persistent retournent des résultats obsolètes. Toujours nettoyer le cache entre les runs de test.

---

## Phase 12 — Email Infrastructure & Anti-LLM Pipeline (12 février)

> **Objectif** : Infrastructure email robuste (SQLite cache, conversation history, full sync) + pipeline anti-LLM-error SOTA (27 étapes post-LLM)
> **Résultat** : 98/100 qualité drafts (20 emails), 17 nouvelles fonctions post-LLM, SmartReply contextuel, DraftEditor amélioré

### 1. SQLite Email Cache + Full Sync

Remplacement du cache in-memory fragile par un cache SQLite persistant avec sync en 2 phases.

- **`app/api/sync.py`** (nouveau) : Endpoint `POST /api/sync/full`
  - Phase 1 : Headers-only sync (~5s) — charge sujet, sender, date de tous les emails
  - Phase 2 : Body backfill daemon — télécharge les corps en arrière-plan
  - WebSocket `sync_status` events (completed/error) pour feedback temps réel
- **`routes.py`** : `_get_email_from_cache()` SQLite fallback avant IMAP
  - Conversation history : SQLite-first avec timeout IMAP 15s
- **Config** : Cache TTL 5→15min, sync limit 100→2000 emails, `EMAIL_CACHE_LIMIT` 500→5000

### 2. Conversation History dans le Draft Pipeline

L'historique de conversation est désormais injecté dans le prompt de génération de brouillons.

- **`daemon.py`** : `_generate_draft()` reçoit `conversation_history` pré-fetché, stocké dans PendingDraft
- **`PendingDraftDetail.tsx`** : Nouveau composant `ThreadContextList`
  - Expandable avec animations stagger et continuation dots (...)
  - Affiche les échanges précédents du thread pour contexte
- **`PendingDraft` entity** : +`conversation_history`, +`conversation_history_count`, +`routing_tier`
- **Format prompt** : `De: sender | subject (03 Feb 2026)` — dates formatées dans l'historique

### 3. Filler/Meta-commentary Defense (3 couches)

Système centralisé pour éliminer les formules de remplissage IA, réparti en 3 niveaux de défense :

| Couche | Mécanisme | Fichier |
|--------|-----------|---------|
| **Prompt** | Exemples FORBIDDEN explicites | `prompts.py` |
| **Centralisé** | `_FILLER_EXACT` (frozenset) + `_FILLER_PREFIX` (tuple) + `_META_COMMENTARY_RE` (regex) | `smart_routing.py` |
| **Pipeline** | `_is_filler_line()` unique, utilisé par `_clean_prompt_leakage` et `_strip_filler_mid_draft` | `smart_routing.py` |

Exemples FORBIDDEN ajoutés :
- "C'est parti", "Allons-y", "Voici ma réponse", "Sure thing!", "Bien sûr !"
- Meta regex : `^(pour|regarding|en réponse à) (ton|your|the) (email|question|test|message)`

### 4. Hybrid Data Recall + Natural Answer Tone

Quand un email pose une question dont la réponse est dans l'historique de conversation, le système pré-calcule la réponse et la fournit au modèle.

- **Boost COMPLEX** : `? in body + conversation_history` → score boosted au seuil COMPLEX
- **`_extract_data_hint()`** (`prompts.py`) : Extraction programmatique de chiffres/montants/séquences depuis l'historique
- **`_build_answer_template()`** (nouveau) : Construit une phrase naturelle ("Les chiffres sont 1, 2 et 3.") injectée via `USE THIS ANSWER:`
- **`_scrub_process_language()`** (`smart_routing.py`) : Supprime "Je trouve", "Je vais vérifier", "du mail du 2 fév", trailing process lines
- **max_tokens 128** pour data-recall (body<100 + `?` + history) — empêche le filler

### 5. ACTION-FIRST Prompts + Parroting Scorer

Réécriture des prompts et du détecteur de parroting pour forcer des réponses orientées action.

- **RULE 1** réécrite : chaque phrase doit commencer par ce que TU fais ("Je confirme", "I accept")
- **Anti-echo** : pas de "Regarding your...", pas de copie de listes, pas de "comme convenu" sans historique
- **`_strip_parroting()` réécrit** : Scoring ACTION/ECHO/NOVEL par ligne (word overlap + action verb detection)
- **`_scrub_hallucinated_context()`** (nouveau) : Supprime "comme convenu"/"as discussed" sans historique + détection de status flips

### 6. Post-LLM Safety Pipeline (8 guards de sécurité)

8 nouvelles fonctions de sécurité appliquées dans les 3 pipeline paths (STANDARD, STREAMING, COMPLEX V2) :

| Fonction | Rôle |
|----------|------|
| `_detect_misdirected()` | Détecte les emails mal routés (sender ≠ destinataire attendu) |
| `_detect_social_engineering()` | Détecte les tentatives d'ingénierie sociale |
| `_detect_blackmail()` | Détecte les emails de chantage/extorsion |
| `_ensure_legal_caution()` | Ajoute des avertissements pour les sujets juridiques |
| `_strip_technical_echo()` | Supprime l'écho technique (code, specs, config) |
| `_clean_language_artifacts()` | Nettoie les artefacts de langue (code-switching, translittération) |
| `_strip_leading_parrot()` | Supprime le parroting en début de draft |
| `_strip_hedging()` | Supprime le hedging ("I think", "perhaps", "maybe") |

### 7. Pipeline Anti-LLM-Error SOTA — 12 nouvelles fonctions (P1-P14)

Recherche approfondie (audit pipeline, littérature SOTA 2025-2026, analyse des failures) suivie de l'implémentation de 12 fonctions post-LLM couvrant 14 catégories d'erreurs LLM.

#### Recherche SOTA

Sources analysées :
- **EQ-Bench Slop Score** (2025) : Vocabulaire surreprésenté dans les LLM ("delve" 6.3x, "tapestry" 14x)
- **Antislop Sampler** (2025) : Backtracking sur tokens "slop" détectés
- **Burstiness scoring** (2025) : Diversité syntaxique des ouvertures de phrases
- **Compression-ratio redundancy** (2026) : Détection de paraphrase par ratio de compression
- **Register consistency scoring** (2025) : Vous/Tu mixing comme signal d'incohérence

#### 12 fonctions implémentées

| ID | Fonction | Description | Regex/Logique clé |
|----|----------|-------------|-------------------|
| **P1** | `_fix_pronoun_consistency()` | Normalise vous/tu selon formalité | `_VOUS_MARKERS` + `_TU_MARKERS` + 13 paires de conjugaison (vas↔allez, peux↔pouvez, dois↔devez, sais↔savez...) |
| **P2** | `_fix_repetitive_openings()` | Varie les débuts de phrases identiques (>50%) | Skip greeting, count first-word frequency, remove subject pronoun every other |
| **P3** | `_strip_excessive_apologies()` | Max 1 excuses par email | `_APOLOGY_RE` (sorry\|apologize\|désolé\|excuse\|navré), forward-iterate matches |
| **P4** | `_strip_redundant_affirmations()` | Max 1 affirmation par email | `_AFFIRMATION_RE` (absolutely\|certainly\|of course\|bien sûr\|tout à fait...) |
| **P5** | `_fix_closing_tone()` | Supprime closings formels en casual et vice versa | `_FORMAL_CLOSINGS_RE` + `_CASUAL_CLOSINGS_RE`, appliqué selon formalité |
| **P6** | `_strip_slop_words()` | Remplace vocabulaire IA surreprésenté | Dict de substitutions : delve→look, leverage→use, robust→strong, tapestry→supprimé |
| **P7** | `_simplify_contrast_patterns()` | "Not just X but also Y" → "X and Y" | `_NOT_X_BUT_Y_RE`, FR: "pas seulement"→supprimé, "mais aussi"→"et" |
| **P8** | `_scrub_invented_contacts()` | Vérifie téléphones/emails/URLs vs body original | `_PHONE_RE` + `_EMAIL_ADDR_RE` + `_URL_RE`, normalized grounding check |
| **P9** | `_strip_sycophancy()` | Supprime flatterie ("Great question!", "Excellent point") | `_SYCOPHANCY_RE` multiline, préserve contenu après la flatterie |
| **P12** | `_strip_recap_sentences()` | Supprime "In summary..." / "En résumé..." en fin de draft | `_RECAP_PREFIXES_RE`, vérifie seulement les 2 dernières lignes |
| **P13** | `_fix_name_overuse()` | Garde nom dans greeting + max 1 en body | Forward pass keep/remove, reverse pass removal |
| **P14** | `_strip_markdown_artifacts()` | Supprime headings, bold, bullets, code fences | `_MARKDOWN_RE` (structural) + `_INLINE_MARKDOWN_RE` (inline → plain text) |

> **Note** : P10 (compression-ratio) et P11 (readability) non implémentés — nécessitent des calculs statistiques complexes pour un gain minimal sur les emails courts.

#### Ordre du pipeline complet (27 étapes)

```
 1. _clean_prompt_leakage()           — supprime "---", filler, prompt artifacts
 2. _strip_markdown_artifacts()       — [P14] markdown → plain text
 3. _strip_filler_mid_draft()         — filler mid-email ("C'est parti!")
 4. _strip_signature()                — signatures inventées
 5. _truncate_for_short_body()        — body court = draft court
 6. _strip_subject_echo()             — écho du sujet dans le draft
 7. _strip_technical_echo()           — écho technique (code, specs)
 8. _strip_parroting()                — phrases copiées du body (si body≥300)
    _strip_leading_parrot()           — parroting en début (si body<300)
 9. _scrub_hallucinated_facts()       — prix/nombres inventés → placeholder
10. _scrub_invented_contacts()        — [P8] téléphones/emails/URLs inventés
11. _scrub_hallucinated_context()     — "comme convenu" sans historique
12. _scrub_process_language()         — "Je trouve", "du mail du..."
13. _strip_hedging()                  — "I think", "perhaps", "maybe"
14. _strip_sycophancy()               — [P9] "Great question!", "Excellent point"
15. _strip_unnecessary_questions()    — questions inutiles
16. _strip_excessive_apologies()      — [P3] max 1 excuse
17. _strip_redundant_affirmations()   — [P4] max 1 affirmation
18. _simplify_contrast_patterns()     — [P7] "not just X but Y" → "X and Y"
19. _strip_slop_words()               — [P6] vocabulaire IA → plain language
20. _strip_recap_sentences()          — [P12] "In summary..." final
21. _fix_repetitive_openings()        — [P2] diversité syntaxique
22. _strip_duplicate_greetings()      — double salutations
    ── apply_learned_corrections() ── — corrections utilisateur
    ── safety overrides ──            — sécurité (misdirected, blackmail, etc.)
23. _detect_language_drift()          — drift de langue FR/EN
24. _fix_pronoun_consistency()        — [P1] vous/tu normalization
25. _fix_closing_tone()               — [P5] closing vs formalité
26. _fix_name_overuse()               — [P13] max 1 nom en body
27. _enforce_greeting()               — force greeting pré-calculé (DERNIER)
```

#### Prompts mis à jour

**4 system prompts** (`STANDARD_DRAFT_SYSTEM_PROMPT` × 4 occurrences) : +6 règles INTERDIT
- Flatterie/sycophantie, excuses excessives, affirmations redondantes, registre mixte vous/tu, markdown, contacts inventés

**`STANDARD_DRAFT_USER_PROMPT`** FORBIDDEN : +11 nouvelles règles
- Sycophancy, excessive apologies, redundant affirmations, "Not just X but also Y", AI slop words, recap/summary, vous/tu mixing, markdown, invented contacts, empty promises, hedging

**`CLASSIFY_AND_DRAFT_SYSTEM_PROMPT`** INTERDIT étendu : corporate bloat, fausse empathie, hedging, promesses vagues, process-description enrichi

### 8. SmartReply — Prompt → AI Generation

Connexion du champ prompt libre SmartReply au pipeline de génération AI.

- **`EmailDetailModal.tsx`** : Séparation `prefillText` → `composerPrefillBody` (chips) + `composerAutoPrompt` (prompt libre)
  - Chips SmartReply → `setComposerPrefillBody(text)` → ouvre ReplyComposer avec texte pré-rempli
  - Prompt libre → `setComposerAutoPrompt(prompt)` → ouvre ReplyComposer avec génération AI
- **`ReplyComposer.tsx`** : Nouvelles props `prefillBody` + `autoGeneratePrompt`
  - `prefillBody` : Set `draftBody` directement, skip draft restore
  - `autoGeneratePrompt` : Trigger `handleAIGenerate(prompt)` au mount (via `useRef` guard + `setTimeout(150ms)`)
  - Skip `useEffect` de draft restore quand l'une des props est fournie
- **`DraftEditor.tsx`** : Nouvelle prop `hideWordCount` — masque le footer compteur de mots dans le ReplyComposer

### Résultats des tests (20 emails)

```
SCORE GLOBAL: 98/100 | 19/20 PASS | 1 faux positif scorer

┌────────────────────┬──────────┬──────────┐
│ Métrique           │  Score   │  Status  │
├────────────────────┼──────────┼──────────┤
│ Langue             │  20/20   │  ✓       │
│ Greeting           │  20/20   │  ✓       │
│ Ton                │  20/20   │  ✓       │
│ Anti-hallucination │  20/20   │  ✓       │
│ Envoyable          │  19/20   │  ✓*      │
├────────────────────┼──────────┼──────────┤
│ TOTAL              │  98/100  │          │
└────────────────────┴──────────┴──────────┘

*1 "FAIL" = faux positif du scorer (email EN court sans marqueurs → scorer attend FR)
 Real quality: 20/20 envoyable

Temps: 254s total | 12.7s/email moyen
Tiers: 1 SIMPLE, 18 STANDARD, 1 COMPLEX
```

### Fichiers modifiés

| Fichier | Lignes | Changement |
|---------|--------|-----------|
| `app/smart_routing.py` | +1013 | 17 nouvelles fonctions post-LLM, pipeline 27 étapes, 20+ regex compilés |
| `app/prompts.py` | +56 | FORBIDDEN +11 règles, INTERDIT ×4 +6 règles, CLASSIFY_AND_DRAFT enrichi |
| `EmailDetailModal.tsx` | +18 | Séparation prefillBody/autoPrompt pour SmartReply |
| `ReplyComposer.tsx` | +35 | Props prefillBody + autoGeneratePrompt, mount trigger AI |
| `DraftEditor.tsx` | +23 | Prop hideWordCount |

### Bugs corrigés pendant l'implémentation

| Bug | Cause | Fix |
|-----|-------|-----|
| "Vous vas voir" au lieu de "Vous allez voir" | P1 ne conjuguait pas les verbes | +13 paires de conjugaison (vas↔allez, peux↔pouvez, etc.) |
| `\bas\b` match faux positifs | Le mot "as" est trop courant en français | Compound patterns : "vous as"→"vous avez", pas `\bas\b` seul |
| 3 excuses sur 1 ligne = 3 conservées | P3 gardait toute la ligne si elle contenait 1 excuse | Forward-iterate matches, keep first, strip rest (même ligne) |
| P13 supprime le 1er nom au lieu du 2e | `reversed(matches)` inversait l'ordre de suppression | Forward pass keep/remove, reverse pass removal |
| Greeting "M. Dufresne" en double | Title prefixes manquants dans 3 listes de patterns | Ajout "m.", "mr.", "mrs.", "dr.", "mme", "prof." dans `_greeting_patterns`, `_formal_greetings`, `_greeting_starts` |

### Leçons apprises

- **Pipeline ordering critique** : P14 (markdown) doit être tôt (avant truncate), P1 (pronoms) et P5 (closing tone) doivent être tard (après corrections apprises), `_enforce_greeting()` toujours DERNIER
- **Compound regex patterns** : `\bas\b` seul a trop de faux positifs en français. Utiliser "vous as"→"vous avez" (compound) évite le problème
- **Forward/reverse pass pattern** : Pour garder la 1ère occurrence et supprimer les suivantes, séparer la décision (forward) de l'exécution (reverse, pour ne pas décaler les indices)
- **3 code paths = 3× maintenance** : Chaque nouveau step doit être ajouté dans `_generate_standard()`, `_generate_standard_streaming()` et `classify_and_draft()`. L'ordre doit être identique
- **Slop words varient par langue** : "delve" est surreprésenté en anglais mais pas en français. Le dict de substitutions inclut les équivalents FR séparément
- **Micro-templates + ? guard** : Toujours vérifier `? in body` avant d'appliquer un micro-template — sinon une question légitime reçoit une réponse pré-formatée

---

## Phase 13 — Attachment Support & Template Intelligence (12 février)

> **Objectif** : Pièces jointes end-to-end (UI → API → MIME) + templates de réponse plus intelligents
> **Résultat** : Bouton attachement fonctionnel dans ReplyComposer, support Gmail + SMTP, templates enrichis

### 1. Attachments End-to-End (7 fichiers)

Pipeline complet de pièces jointes depuis le bouton trombone UI jusqu'au MIME email envoyé.

#### Backend (bottom-up)

| Fichier | Changement |
|---------|-----------|
| `app/interfaces/email_provider.py` | +`attachments: Optional[List[Tuple[str, bytes, str]]]` sur `create_draft()` et `send_email()` |
| `app/providers/gmail_adapter.py` | `_create_message()` : `MIMEMultipart("mixed")` quand attachments, `MIMEBase` + `encoders.encode_base64()` par fichier. `create_draft()` forward le param. |
| `app/providers/smtp_adapter.py` | `SMTPAdapter.create_draft()` stocke attachments en mémoire. `send_draft()` les forward. `send_email()` les passe à `_create_message()`. `IMAPSMTPAdapter` delegate les 2 méthodes. |
| `app/api/routes.py` | `_create_draft_and_mark_read()` +param attachments. `create_draft_from_content()` : parse `attachments[]` JSON (base64), validation 25 MB max. |

#### Frontend

| Fichier | Changement |
|---------|-----------|
| `agentys-app/src/services/api.ts` | +interface `OutgoingAttachment` (`filename`, `data_base64`, `content_type`). `createDraft()` +param optional `attachments`. |
| `agentys-app/src/components/reply/ReplyComposer.tsx` | State `attachments[]`, `fileInputRef`, handlers (`handleAttachClick`, `handleFileChange`, `removeAttachment`), `fileToBase64()` helper, `formatFileSize()`. `handleSend()` convertit Files→base64. Bouton trombone wired. Hidden `<input type="file" multiple>`. Attachment chips avec bouton remove. Validation 25 MB avec message d'erreur. |
| `agentys-app/src/components/reply/ReplyComposer.css` | `.rc-attachments` (flex-wrap container), `.rc-attachment-chip` (pill, hover accent), `.rc-attachment-name` (ellipsis 160px), `.rc-attachment-size` (muted), `.rc-attachment-remove` (hover error). Responsive 768px/480px. |

#### Flux de données

```
[UI] File picker → File[] state → handleSend()
  → FileReader.readAsDataURL() → base64 strings
  → POST /api/emails/:id/draft { attachments: [{filename, data_base64, content_type}] }
  → routes.py: b64.decode() → [(filename, bytes, content_type)]
  → provider.create_draft(attachments=...)
  → Gmail: MIMEMultipart("mixed") + MIMEBase per file → urlsafe_b64encode → API
  → SMTP: _create_message(attachments=...) → MIMEBase per file → sendmail()
```

### 2. Template Response Intelligence

Enrichissement des réponses template Level 1 (sans LLM) pour couvrir plus de cas triviaux.

- **`getAutoGenInstruction()`** (nouveau) : Adapte l'instruction LLM selon la longueur du body
  - Body < 80 chars → "MAXIMUM 2 phrases courtes"
  - Body < 150 chars → "3 phrases maximum"
  - Body > 150 chars → instruction standard
- **Templates enrichis** : +5 nouveaux patterns (ok/ack, FYI, confirmation, agreement)
  - `bodyShort` guard : templates uniquement pour body < 60 chars
  - Greeting construit avec détection `casual` + `lang` + `name`
  - Patterns : "ok"/"d'accord"/"got it", "pour info"/"fyi", "c'est confirmé", "ça marche"/"deal"

### Fichiers modifiés

| Fichier | Lignes | Changement |
|---------|--------|-----------|
| `app/interfaces/email_provider.py` | +4 | `Tuple` import, `attachments` param sur `create_draft()` + `send_email()` |
| `app/providers/gmail_adapter.py` | +18 | `MIMEBase`/`encoders` imports, MIME attachment logic dans `_create_message()` + `create_draft()` |
| `app/providers/smtp_adapter.py` | +12 | Attachments threaded dans `create_draft()`, `send_draft()`, `send_email()`, `IMAPSMTPAdapter` |
| `app/api/routes.py` | +25 | Base64 parsing + 25MB validation dans `create_draft_from_content()` |
| `agentys-app/src/services/api.ts` | +8 | `OutgoingAttachment` interface, `createDraft()` updated |
| `agentys-app/src/components/reply/ReplyComposer.tsx` | +75 | Full attachment UI: state, handlers, base64 conversion, chips, validation |
| `agentys-app/src/components/reply/ReplyComposer.css` | +65 | Attachment chip styles + responsive |

---

## Phase 14 — Draft Quality v3 (12 février)

> **Objectif** : Passer de "draft correct" à "draft prêt à envoyer" dans 80%+ des cas
> **3 leviers** : Few-shot examples, style profile enrichi, Sonnet routing tone-sensitive
> **Impact coût** : +$0.50-1.00/mois (Sonnet ~5-10% du trafic)

### 1. Few-shot examples dynamiques (`app/prompts.py`)

Le LLM avait 27 règles INTERDIT mais zéro exemple positif. Résultat : drafts corrects mais génériques.

| Composant | Détail |
|-----------|--------|
| `_FEWSHOT_EXAMPLES` | Dict de 10 clés intent (`action/question/decline` × `casual/formal` × `fr/en`), 1-2 exemples courts par clé |
| `_DECLINE_RE` | Regex pour détecter les instructions de refus (`non`, `decline`, `cannot`, `impossible`...) |
| `_get_fewshot_section()` | Sélectionne les exemples par intent + formality + langue, retourne section formatée |
| Injection | Dans le user prompt de `get_standard_draft_prompts()` et `get_classify_and_draft_prompts()` |

**Mitigation copier-coller** : Exemples courts (1-3 lignes), variés (2 par intent), dans le user prompt (pas system). Le scrubber `_strip_parroting` existant détecte le copier-coller.

### 2. User writing style profile enrichi (`app/prompts.py`)

Les fonctions `extract_sent_examples()` et `extract_user_formulas()` existaient depuis Phase 10 mais n'étaient plus connectées au pipeline STANDARD actuel.

| Fonction | Rôle |
|----------|------|
| `extract_sent_examples()` | Extrait les emails envoyés par l'utilisateur → section `<TES_RÉPONSES_PRÉCÉDENTES>` |
| `extract_user_formulas()` | Extrait salutations/clôtures réelles → section `<TES_FORMULES_HABITUELLES>` |

**Reconnexion** : Injectées dans le system prompt de `get_standard_draft_prompts()` et `get_classify_and_draft_prompts()` quand `conversation_history` et `user_email` sont disponibles. `user_email` obtenu via `get_current_account()`.

### 3. Sonnet routing pour emails tone-sensitive

Haiku gère bien le factuel (80% du trafic) mais produit des réponses robotiques pour les refus, mauvaises nouvelles, conflit, RH.

#### Détection (`app/smart_routing.py`)

```python
_TONE_SENSITIVE_RE  # Regex: decline, refus, mauvaise nouvelle, condoléances,
                    # plainte, déçu, licenciement, démission, disciplinaire...

_is_tone_sensitive(body, subject, instructions="") -> bool
```

#### Routing

| Fichier | Changement |
|---------|-----------|
| `app/config.py` | `SONNET_ROUTING_ENABLED = get_env_bool("SONNET_ROUTING_ENABLED", True)` |
| `app/infrastructure/container.py` | `_llm_sonnet` field + `llm_sonnet` property (lazy) + `_create_llm_sonnet()` → `ClaudeAdapter(CLAUDE_MODEL_FAST)` |
| `app/smart_routing.py` | 3 paths upgradés : STANDARD, STREAMING, COMBINED. Si `SONNET_ROUTING_ENABLED and _is_tone_sensitive(...)` → `llm = container.llm_sonnet` |

#### Impact coût estimé

| Métrique | Valeur |
|----------|--------|
| Emails tone-sensitive | ~5-10% du trafic |
| Coût Sonnet vs Haiku | ~3x ($0.009 vs $0.003) |
| Impact mensuel | +$0.50-1.00 sur les $5.54 actuels |
| Ollama | Même instance (pas de modèle Sonnet séparé) |

### Bilan des changements

| Fichier | Lignes ajoutées | Changement |
|---------|----------------|-----------|
| `app/prompts.py` | +95 | `_FEWSHOT_EXAMPLES`, `_get_fewshot_section()`, injection style profile + few-shot dans 2 fonctions prompt |
| `app/smart_routing.py` | +35 | `_TONE_SENSITIVE_RE`, `_is_tone_sensitive()`, upgrade Sonnet dans 3 paths |
| `app/infrastructure/container.py` | +20 | `_llm_sonnet` field, `llm_sonnet` property, `_create_llm_sonnet()` factory |
| `app/config.py` | +1 | `SONNET_ROUTING_ENABLED` flag |

---

## Phase 15 — Sent Folder Fix & IMAP Performance (13 février)

L'onglet "Envoyés" ne fonctionnait pas — liste vide, puis chargement extrêmement lent (66-80s). Trois problèmes distincts identifiés et corrigés.

### Bug 1 : Fetch avorté par React StrictMode (`EmailList.tsx`)

**Symptôme** : L'onglet Envoyés affichait une liste vide. Console : `[EmailList] folder=sent fetch aborted` × 3.

**Cause racine** : React StrictMode (dev) monte, démonte, puis remonte les composants. L'ancien code avait :
1. Un `abort()` dans le cleanup du `useEffect` de montage — le démontage intermédiaire annulait le fetch légitime
2. Des `mountRef` booléens (`labelMountRef`, `providerLabelMountRef`) qui n'étaient pas réinitialisés entre les deux montages — les effets label/providerLabel déclenchaient `loadEmails()` au 2e montage, écrasant le fetch principal

**Correctifs** :
- Supprimé l'`abort()` du cleanup de l'effet de montage (React 18 ignore les setState sur composants démontés)
- Remplacé les `mountRef` booléens par des refs de comparaison de valeur (`prevActiveLabelRef`, `prevProviderLabelRef`) qui survivent au double-montage

### Bug 2 : Chargement lent de la liste envoyés — 66s → 23s → 0.3s (`imap_adapter.py`)

**Symptôme** : `curl /api/emails?folder=sent` prenait 66 secondes.

**Cause racine** : Gmail IMAP rate-limite chaque opération à ~10 secondes. L'ancien code faisait 6+ opérations séquentielles :
1. SELECT "Sent" (10s, échoue sur Gmail)
2. SELECT "[Gmail]/Sent Mail" (10s, réussit)
3. UID SEARCH ALL (10s)
4. UID FETCH BODY.PEEK[] — corps complet (10s)
5. IMAP CLOSE (10s)
6. IMAP LOGOUT (10s)

**Correctifs (5 optimisations)** :

| Optimisation | Gain |
|---|---|
| Détection Gmail (`imap.gmail.com`) → `[Gmail]/Sent Mail` en premier | -10s |
| Cache du nom de dossier Sent (`_sent_folder_name`) | -10s sur appels suivants |
| Fetch headers-only (`BODY.PEEK[HEADER.FIELDS ...]`) au lieu de `BODY.PEEK[]` | Moins de données |
| Suppression de UID SEARCH → fetch par numéro de séquence (`N:*`) | -10s |
| Disconnect rapide (socket shutdown au lieu de IMAP LOGOUT) | -20s |
| Skip NOOP pour connexions fraîches (<60s) via `_auth_time` | -10s |

**Résultat** : 66s → 23s (IMAP cold), 0.3s (SQLite cache), 0.2s (memory cache)

### Bug 3 : Détail d'un email envoyé — 80s → 21s → 0.2s (`routes.py`, `smtp_adapter.py`)

**Symptôme** : Cliquer sur un email envoyé prenait 80 secondes pour afficher le contenu.

**Cause racine** : 3 problèmes empilés :
1. `IMAPSMTPAdapter.get_message_by_id()` ne transmettait pas le paramètre `folder` → `TypeError` → fallback sans folder → probe de TOUS les dossiers (INBOX, Sent, [Gmail]/Sent Mail...)
2. `get_message_by_id()` faisait un re-SELECT INBOX après chaque fetch (inutile car le provider est jetable)
3. SQLite cache exigeait `body_text or body_html` — les emails envoyés stockés en headers-only étaient ignorés

**Correctifs** :
- `smtp_adapter.py` : Ajout du paramètre `folder` à `get_message_by_id()` pour le transmettre à l'IMAP adapter
- `imap_adapter.py` : Supprimé le re-SELECT INBOX après fetch (économise 10s)
- `imap_adapter.py` : Ordre Gmail-first dans la liste de fallback de `get_message_by_id()`
- `routes.py` : Détection Gmail + ordre de dossiers optimisé dans la route detail
- `routes.py` : Persistance du body en SQLite après le 1er fetch IMAP (les accès suivants sont instantanés)

**Résultat** : 80s → 21s (IMAP cold, 2 opérations : SELECT + FETCH), 0.2s (cache)

### Tableau récapitulatif des performances

| Opération | Avant | Après (cold) | Après (cache) |
|---|---|---|---|
| Liste envoyés | 66s | 23s | 0.2s |
| Détail email envoyé | 80s | 21s | 0.2s |
| Liste envoyés (SQLite après restart) | 66s | 0.3s | — |

### Fichiers modifiés

| Fichier | Changements |
|---|---|
| `agentys-app/src/components/EmailList.tsx` | StrictMode fix : supprimé abort cleanup, refs valeur vs booléen |
| `app/providers/imap_adapter.py` | `_sent_folder_name` cache, `_auth_time` NOOP skip, headers-only `get_sent_emails()`, Gmail-first folders, fast `disconnect()`, supprimé re-SELECT |
| `app/providers/smtp_adapter.py` | `get_message_by_id()` : ajout paramètre `folder` |
| `app/api/routes.py` | Detail route : Gmail-first folders, body persist SQLite |

### Diagnostic clé : Gmail IMAP rate limiting

Chaque commande IMAP vers `imap.gmail.com` prend ~10 secondes (rate limiting côté serveur). Cela rend chaque opération IMAP coûteuse :

```
Authenticate: 0.41s (TLS + LOGIN, pas rate-limité)
SELECT:       10.09s
SEARCH:       10.07s
FETCH:        10.17s
CLOSE:        10.xx s
LOGOUT:       10.xx s
```

**Stratégie adoptée** : minimiser le nombre d'opérations IMAP (2 au lieu de 6), puis cacher agressivement en SQLite pour ne plus jamais refaire l'opération.

---

## Phase 16 — Quick Reply, Deep Focus v2, Refine Mode & Labels i18n (13 février)

Refonte majeure de l'expérience utilisateur : Quick Reply zero-cost, Deep Focus "Command Center", mode Refine pour compositions, labels en français, et optimisations send flow. **58 fichiers modifiés, ~4700 insertions, ~2300 suppressions.**

### 1. Quick Reply — Réponse binaire zero-cost

**Nouveau tier `QUICK_REPLY`** dans le SmartRouter. Détecte les questions oui/non courtes via regex (`_BINARY_Q_FR_RE`, `_BINARY_Q_EN_RE`) et retourne deux réponses pré-construites (affirmative/négative) avec greeting, langue et formalité adaptés — sans aucun appel LLM.

| Garde | Seuil |
|---|---|
| Longueur max body | 150 caractères |
| Questions multiples (`?` × 2+) | Exclu |
| Questions factuelles (combien/how/why) | Exclu |

- `PendingDraft.quick_replies` : dict `{affirmative, negative}` porté du backend au frontend
- UI : deux boutons proéminents + bouton "Enrichir avec l'IA" (`POST /pending-drafts/<id>/upgrade`)
- Inséré dans les 3 paths (STANDARD, STREAMING, COMBINED) pour parité

**Fichiers** : `smart_routing.py`, `pending_draft.py`, `daemon.py`, `PendingDraftDetail.tsx`, `api.ts`

### 2. Knowledge Base dans le pipeline de draft

Nouvelle fonction `_extract_knowledge_answer()` dans `prompts.py` : cherche dans la base de connaissances utilisateur (`knowledge/memoire.md`) les entrées matchant la question de l'email entrant (word-overlap scoring, seuil ≥ 0.4).

- Directive `VERIFIED ANSWER FROM YOUR KNOWLEDGE BASE` injectée dans le user prompt
- Bloc `<CONTEXTE>` XML injecté dans le system prompt
- Paramètre `knowledge_base` ajouté aux deux fonctions prompt (`get_standard_draft_prompts`, `get_classify_and_draft_prompts`)
- Les 3 paths SmartRouter chargent `load_knowledge_base()`

### 3. Élimination des marqueurs "[A confirmer]"

Haiku ajoutait `[A confirmer]` même sur des données venant de la knowledge base ou de l'historique de conversation.

**Double correction** :
1. **Prompts** : 8 templates réécrits — "Data from knowledge base or history is VERIFIED, use it WITHOUT [A confirmer]"
2. **Post-LLM** : nouvelle étape `_strip_a_confirmer()` supprime tous les marqueurs résiduels (`[A confirmer]`, `[A valider]`, `[TBD]`, `[REDACTE]`)

### 4. Send Flow — Réponse instantanée + post-send background

| Avant | Après |
|---|---|
| Send → mark read → archive → learning → quality → respond | Send → respond immédiat, background thread pour le reste |

- `gmail_adapter.send_reply_directly()` : appel unique `messages.send()` (skip create_draft + send_draft, -500ms)
- `_post_send_all_bg()` : thread background pour mark_as_read, archive, learning, quality tracking, commitment extraction
- `_evict_email_from_all_caches()` : éviction centralisée (in-memory + SQLite)
- WebSocket `email_archived` : notification quand l'archive background est terminée
- Frontend : delayed refresh (4s fallback) + debounced WS refresh (500ms)

**Fichiers** : `routes.py` (~400 lignes), `gmail_adapter.py`, `websocket.py`, `App.tsx`, `useWebSocketSync.ts`

### 5. Deep Focus v2 — "Command Center"

Refonte complète de l'interface Deep Focus (préfixe CSS `.deep-focus-*` → `.df2-*`).

| Ancien | Nouveau |
|---|---|
| Liste scrollable | Hero card unique (1 email à la fois) |
| Barre de progression segmentée | Progress ring SVG |
| Draft review séparé | `PendingDraftDetail` intégré inline |
| Navigation hors Deep Focus | Navigation prev/next avec `deepFocusNavInfo` |

- Section indicator (dot coloré + label)
- Metrics cluster (timer, streak, ETA)
- Queue list des emails suivants
- Animations d'entrée/sortie
- `handleEmailSelect` accepte `prefetchedDraft` pour skip API
- Overrides thèmes dark-luxury (gold) et futurist-silver (plasma cyan)

**Fichiers** : `DeepFocusMode.tsx` (+645), `DeepFocusMode.css` (+981), `App.tsx`, `dark-luxury.css`, `futurist-silver.css`

### 6. Pending Draft Detail — Pipeline Cards + Quick Reply UI

- Pipeline disclosure : cards collapsibles (Classification, Drafter, Critique) au lieu de steps numérotés
- Composants `PipelineCard` + `PipelineConnector` partagés
- Conversation history dans un card standalone
- Quick Reply UI : deux boutons + upgrade to full draft
- Navigation prev/next via prop `navInfo` (utilisé par Deep Focus)

**Fichiers** : `PendingDraftDetail.tsx` (+639), `PendingDraftDetail.css` (+298)

### 7. Pending Draft List — Vue unifiée

Liste unifiée chronologique (`UnifiedDraft[]`) qui interleave drafts AI et drafts sauvegardés. Suppression de la séparation "En attente" vs "Autres". Checkboxes redessinées en CSS-only (`::after` checkmark).

**Fichiers** : `PendingDraftList.tsx` (+187/-130), `PendingDraftList.css` (+58)

### 8. Reply Composer — Mode Refine + Chips simplifiés

| Ancien | Nouveau |
|---|---|
| Auto-génération au montage | Ouverture en mode édition libre |
| 11 types × 2-4 chips contextuels | 2 chips universels : "Oui" / "Non" |
| Banner avec animation stylo | `StageFlow` depuis `PipelineCards` |

- **Refine mode** : quand l'utilisateur a tapé du texte et soumet une instruction AI → appel `/refine-text` (single Haiku call, pas de pipeline critique)
- Pipeline disclosure redessinée avec `PipelineCard` + `PipelineConnector`
- Label "BROUILLON AI" / "Nouvelle réponse" en haut du composer
- Nouvelles slash commands : `/corrige`, `/traduis`, `/remerciement`

**Fichiers** : `ReplyComposer.tsx` (+300/-300), `ReplyComposer.css` (+321/-300)

### 9. New Message Modal — Refine + Diff overlay + Slash commands

- AI prompt toujours visible (plus de toggle)
- **Refine mode** : texte existant passé au backend comme `body` pour refinement
- **Word-level diff overlay** : highlight des mots changés via algorithme LCS, auto-fade 2.5s
- 7 slash commands compose : `/formel`, `/court`, `/corrige`, `/relancer`, `/anglais`, `/invitation`, `/remerciement`
- Autocomplete menu avec navigation clavier

**Fichiers** : `NewMessageModal.tsx` (+320), `NewMessageModal.css` (+63)

### 10. Labels i18n — Noms français

Couche d'affichage `getLabelDisplayName()` — les noms internes restent en anglais (API, DB, logique), seul le rendu UI traduit.

| Interne | Affiché |
|---|---|
| `FYI` | Info |
| `Waiting` | Attente |
| `Noise` | Bruit |
| `Action` | Action (inchangé) |

**9 points d'affichage couverts** :
- `LabelBadge` (texte, aria-label, chip tooltip)
- `EmailListHeader` (onglets)
- `LabelQuickPicker` (liste defaults, liste customs, header sélection)
- `EmailList` (toast après changement)
- `LabelEditor` (confirm suppression)

**Fix backend** : `get_label_counts()` résolvait mal l'account_id multi-compte (hash ID vs DB integer). Corrigé via `AccountRepository` lookup par email.

**Fichiers** : `labels.ts`, `LabelBadge.tsx`, `LabelQuickPicker.tsx`, `EmailListHeader.tsx`, `EmailList.tsx`, `LabelEditor.tsx`, `labels.py`

### 11. Caching — TTLs réduits + LRU

| Paramètre | Avant | Après |
|---|---|---|
| Backend memory cache TTL | 15 min | 60s |
| Min cache threshold | 10 emails | 3 emails |
| Max cache entries | Illimité | 10 (LRU) |
| Frontend IndexedDB stale TTL | 5 min | 60s |
| Frontend IndexedDB max age | 30 min | 5 min |

- `skip_cache=true` query param pour bypass backend in-memory (mais pas SQLite)
- TTL cache 10min pour `compute_style_metrics()` et `extract_sent_examples()` (keyed par thread ID)
- Label filter : push `email_ids` en SQL `WHERE IN` au lieu de fetch 500 + filter Python

### 12. Contact Autocomplete — Filtrage intelligent

- ~30 patterns noreply ajoutés (notifications@, marketing@, billing@, etc.)
- ~20 noise domains filtrés (substack.com, facebookmail.com, linkedin.com, etc.)
- Own email exclu des résultats
- Contacts envoyés : boost ×5 dans le tri
- Fix race condition blur/async avec `isFocusedRef` + `suppressNextFocusRef`

### 13. Greeting + Prompt Leakage

- `_separate_greeting_from_body()` : garantit greeting sur sa propre ligne + ligne vide avant le body
- `_clean_prompt_leakage()` étendu : supprime les headers email leakés (`De:`, `From:`, `Date:`, `Sujet:`)

### 14. Refine Draft — Guardrails

System prompt `RefineEmailUseCase` réécrit avec règles INTERDIT explicites : pas d'invention, pas de décisions pour l'utilisateur, pas d'alternatives, pas de padding. Nouveau endpoint léger `/refine-text`.

### 15. Daemon + Infrastructure — Emoji → ASCII

~80 log statements convertis : emojis → tags ASCII (`[OK]`, `[FAIL]`, `[ERROR]`, `[WARN]`, etc.). Concerne `daemon.py`, `circuit_breaker.py`, `database.py`, `logging_config.py`, `pending_draft_store.py`, `progress.py`, `rate_limiter.py`, `factory.py`, 6 providers, `websocket.py`.

Autres fixes :
- `pending_draft_store.get_by_email_id()` exclut les drafts rejected/sent/validated
- `websocket.get_socketio()` : supprimé auto-création de `SocketIO()` non initialisé
- `email_repository.get_by_account()` : paramètre `email_ids` pour filtrage SQL

### 16. UI Polish

- `EmailDetailModal` : boutons Reply/Forward avec vrais SVG (plus Unicode), bordure accent + gradient glow
- `EmailList` : `React.memo`, bulk actions simplifiées (archive + delete uniquement), "Moi" pour emails envoyés par soi
- Sections priorité collapsibles
- Checkboxes CSS-only (`::after` pseudo-element)

### Fichiers modifiés (58 fichiers)

| Catégorie | Fichiers |
|---|---|
| **Smart Routing & Prompts** | `smart_routing.py`, `prompts.py`, `refine_email.py` |
| **Send Flow & API** | `routes.py`, `gmail_adapter.py`, `websocket.py` |
| **Deep Focus v2** | `DeepFocusMode.tsx`, `DeepFocusMode.css` |
| **Draft Review** | `PendingDraftDetail.tsx/css`, `PendingDraftList.tsx/css` |
| **Composer** | `ReplyComposer.tsx/css`, `NewMessageModal.tsx/css` |
| **Labels** | `labels.ts`, `LabelBadge.tsx`, `LabelQuickPicker.tsx`, `LabelEditor.tsx`, `labels.py` |
| **Infrastructure** | `daemon.py`, `config.py`, `circuit_breaker.py`, `database.py`, `logging_config.py`, `pending_draft_store.py`, `progress.py`, `rate_limiter.py` |
| **Providers** | `gmail_adapter.py`, `imap_adapter.py`, `smtp_adapter.py`, `factory.py`, `outlook_*.py`, `gmail_calendar.py` |
| **Frontend Core** | `App.tsx`, `EmailList.tsx/css`, `EmailListHeader.tsx`, `EmailListEmpty.tsx`, `EmailDetailModal.tsx/css`, `SwipeableEmailItem.css`, `api.ts`, `emails.ts`, `websocket.ts`, `useWebSocketSync.ts`, `email.ts`, `priorityGrouping.ts` |
| **Thèmes** | `dark-luxury.css`, `futurist-silver.css` |
| **Autocomplete** | `ContactAutocomplete.tsx` |

---

## Export PDF — Bouton "Exporter en PDF" dans EmailDetailModal (7 avril 2026)

**Added** — Bouton "Exporter en PDF" (icône imprimante) dans le header de `EmailDetailModal`, déclenche `window.print()` avec un CSS `@media print` dédié (approche `visibility: hidden/visible`) qui masque le chrome de l'app et affiche uniquement le contenu de l'email. i18n EN/FR/DE/ES. 2 tests Vitest ajoutés.

---

## Architecture actuelle

```
agentys/
├── agentys-app/                    # App Tauri (React + TypeScript)
│   ├── src/
│   │   ├── components/             # 35+ composants UI
│   │   │   ├── EmailList.tsx       # Liste virtualisée (react-window) + priority grouping
│   │   │   ├── EmailDetailModal.tsx # Détail email inline + SmartReply + AIProgressBar
│   │   │   ├── PendingDraftDetail.tsx # Panneau draft AI + Pipeline Cards + Quick Reply
│   │   │   ├── PendingDraftList.tsx # Liste unifiée drafts (AI + sauvegardés)
│   │   │   ├── Sidebar.tsx         # Sidebar collapsible + label rail + logo-toggle
│   │   │   ├── SwipeableEmailItem.tsx # Swipe + snooze + noise unsubscribe
│   │   │   ├── CommandPalette.tsx   # Palette Cmd+K (navigation + actions)
│   │   │   ├── DeepFocusMode.tsx    # Mode Inbox Zero "Command Center" v2
│   │   │   ├── DeepFocusCelebration.tsx # Ecran victoire + confettis
│   │   │   ├── PrioritySectionHeader.tsx # Headers sections collapsibles
│   │   │   ├── SmartReply.tsx       # Réponses rapides contextuelles
│   │   │   ├── SnoozeDropdown.tsx   # Snooze avec détection dates FR
│   │   │   ├── AIProgressBar.tsx    # Indicateur 3 étapes pipeline IA
│   │   │   ├── EmptyState.tsx      # États vides premium
│   │   │   ├── Settings.tsx        # Settings 8 groupes + theme picker + apprentissages
│   │   │   ├── LearnedRulesPanel.tsx # Dashboard apprentissages (3 catégories)
│   │   │   ├── KnowledgeSuggestionToast.tsx # Toast auto-capture savoir
│   │   │   ├── compose/NewMessageModal.tsx  # Compose + AI
│   │   │   ├── reply/ReplyComposer.tsx      # Reply/Forward/Reply-All
│   │   │   ├── labels/             # LabelBadge, LabelEditor, LabelQuickPicker (2 steps)
│   │   │   ├── snippets/           # SnippetEditor, SnippetLibrary, SnippetSelector
│   │   ├── hooks/
│   │   │   ├── useBackend.ts       # API + WebSocket state
│   │   │   ├── useDeepFocus.ts     # Deep Focus state machine
│   │   │   ├── useTheme.ts         # Theme dark-luxury/futurist/default
│   │   │   ├── useAppShortcuts.ts  # Raccourcis clavier globaux + Cmd+K
│   │   │   └── useUISounds.ts      # Web Audio API sounds
│   │   ├── services/
│   │   │   ├── api.ts              # HTTP client (fetch)
│   │   │   ├── websocket.ts        # Socket.IO client
│   │   │   └── uiSounds.ts         # 4 sons (send, draft, archive, delete)
│   │   ├── themes/
│   │   │   ├── dark-luxury.css     # Thème sombre "Velvet & Gold" v2
│   │   │   └── futurist-silver.css # Thème clair "Liquid Chrome"
│   │   └── utils/
│   │       ├── emailContent.ts     # Parsing/rendering email + URL detection
│   │       └── priorityGrouping.ts # Groupement emails par priorité
│   └── src-tauri/                  # Backend Rust (tray, IPC)
│
├── app/                            # Backend Python (Flask)
│   ├── api/
│   │   ├── routes.py               # ~5000 lignes — tous endpoints REST
│   │   ├── app.py                  # Flask app factory
│   │   ├── settings.py             # Gestion settings (theme, sounds, etc.)
│   │   └── websocket.py            # Socket.IO events
│   ├── agents.py                   # DrafterAgent, CriticAgent
│   ├── smart_routing.py            # SmartRouter (SKIP/SIMPLE/STANDARD/COMPLEX) + post-LLM pipeline
│   ├── prompts.py                  # System prompts + pre-computed hints (formality, greeting, language)
│   ├── daemon.py                   # Service daemon (polling, cleanup)
│   ├── application/
│   │   └── label_email.py          # Pipeline auto-labeling 3 couches
│   ├── providers/
│   │   ├── factory.py              # Provider factory
│   │   ├── gmail_adapter.py        # Gmail API + OAuth
│   │   ├── outlook_adapter.py      # Outlook/Graph API
│   │   ├── imap_adapter.py         # IMAP générique (multi-folder search)
│   │   ├── smtp_adapter.py         # SMTP send + delegation
│   │   └── email_parser_mixin.py   # Parsing partagé
│   ├── draft_learning.py           # DraftLearningStore (corrections + positives)
│   ├── knowledge_capture.py        # Auto-capture savoir depuis corrections placeholders
│   └── infrastructure/
│       ├── pending_draft_store.py  # Store in-memory + mtime reload
│       └── writing_style_store.py  # FileWritingStyleStore (profil par compte)
│
├── tests/                          # Tests pytest
├── knowledge/memoire.md            # Base de connaissances IA
└── CLAUDE.md                       # Instructions développement
```

### Patterns clés

| Pattern | Détail |
|---------|--------|
| **Provider/Adapter** | Gmail, Outlook, IMAP/SMTP — interface commune `EmailProvider` |
| **Draft pipeline** | Drafter V1 → Critic → V2. History bypass si V1 cite l'historique |
| **Smart Routing** | QUICK_REPLY ($0) → SKIP → SIMPLE ($0) → STANDARD (Haiku $0.003) → COMPLEX (Haiku $0.003). Quick Reply pour questions binaires, micro-templates humains, knowledge base grounding, cache disque 1h, dynamic max_tokens, post-LLM pipeline 28 étapes (anti-filler, anti-hallucination, anti-parroting, anti-slop, anti-sycophancy, anti-[A confirmer], pronoun consistency, security guards) |
| **Auto-labeling** | Built-in rules → User rules → LLM fallback. Strong/weak patterns |
| **Theme system** | CSS variables + `data-theme` attribute. 3 thèmes (default, dark-luxury, futurist) |
| **Race condition guard** | `useRef` pour vérifier que l'email sélectionné n'a pas changé pendant l'appel API |
| **Cross-process sync** | `mtime` checking dans `InMemoryPendingDraftStore` (API ≠ daemon) |
| **Performance** | Gmail historyId delta sync, IndexedDB cache, react-window virtualization, in-memory API cache, requestIdleCallback prefetch |
| **Keyboard nav** | J/K (Gmail-style), Arrow keys, N/R/E/F/Del, /, Cmd+K, Esc |

### Leçons apprises

- **LLM critics ne peuvent pas évaluer les réponses basées sur l'historique** → bypass déterministe
- **Pre-processing déterministe > recherche LLM** → injecter l'historique pertinent programmatiquement
- **SVGs dans Tauri** → préférer Unicode/emoji pour les icônes simples
- **HTML entities en JSX** → utiliser Unicode escapes (`\u2709`) pas `&#9993;`
- **Temporal dead zone** → ne pas référencer un `const` useCallback dans un useEffect déclaré avant
- **IMAP folders avec espaces/crochets** → toujours quoter avec `_select_folder()`
- **LLM compound condition_types** → Les LLMs retournent souvent `"sender|subject"` — parser et réduire au type le plus discriminant
- **CSS cleaning conditionnel** → Tester la présence de patterns CSS avant de nettoyer (sinon les `@` d'emails sont supprimés)
- **Iframe resize multi-pass** → Les newsletters complexes nécessitent 3 passes (300ms, 1s, 2.5s) pour calculer la hauteur correcte
- **body_html propagation** → `_sync_emails_to_cache()` doit copier `body_html` sinon les emails HTML s'affichent en plain-text
- **Theme sync race condition** → Le fetch backend peut écraser localStorage avec "default" — toujours donner priorité au localStorage et sync vers backend
- **Draft trigger immediat** → Ajouter un background thread dans Flask pour actions longues (LLM) plutôt que d'attendre le polling daemon
- **SVG glow filter** → `feGaussianBlur` + `feComposite(operator="over")` pour halo doux sans affecter la netteté du stroke
- **Prefetch lazy components** → `requestIdleCallback` avec fallback `setTimeout` est le pattern idéal pour preload Webpack chunks
- **Vertical text alignment** → `transform: translateY()` est plus précis que `align-items: flex-end` pour aligner un texte avec un élément SVG
- **Audit automatisé** → Playwright + `networkidle` + screenshots est un bon workflow pour évaluer la UX d'une app Tauri via le port dev
- **Undo pattern avec useRef** → Stocker l'item dans le ref (pas le state) pour éviter les stale closures du `setTimeout`. Timer 5s → commit, Annuler → `clearTimeout` + restore
- **Agrégation learning data** → 3 sources différentes (label_store, draft_learning, writing_style_store) avec des schémas différents — normaliser côté backend en un seul endpoint avec union types côté frontend

---

## Phase 17 — Deep Focus v3 "Calm Velocity" (13 février)

> **2 fichiers modifiés** | ~600 insertions, ~100 suppressions
> Direction esthétique : **"Calm Velocity"** — un command center raffiné qui récompense la vitesse

### Velocity Metrics — Données cachées rendues visibles (`DeepFocusMode.tsx`)

Les variables `emailsPerMin`, `etaMin` et `remainingTotal` étaient calculées mais **jamais affichées**. La topbar affiche maintenant :

```
[Section]  [Streak]    {N} restants · {X}/min · ~{Y} min  [timer]  [ring]  [×]
```

- **Restants** : `remainingTotal` — montre combien il en reste
- **Vitesse** : `emailsPerMin` — affichage motivationnel (apparaît après 15s)
- **ETA** : `~{etaMin} min` — estimation temps restant
- Monospace tabular-nums pour alignement propre
- Entrance animation `df2MetricIn` (slide-down 0.3s)
- Responsive : métriques secondaires masquées sous 640px

### Format de date aligné sur l'Inbox (`DeepFocusMode.tsx`)

Remplacement de `formatRelativeTime` ("il y a 32 min") par `formatEmailTime` :
- **Aujourd'hui** : `14h00` (heure absolue)
- **Autre date** : `5 févr.` (format court mois)
- Identique au format utilisé dans `EmailList`

### Premium CSS Overhaul (`DeepFocusMode.css`)

**Topbar** — Depth over border :
- `border-bottom` → `box-shadow: 0 1px 3px rgba(0,0,0,0.04)` pour profondeur
- Padding vertical 10→14px, `z-index: 2`
- Section label + timer en `var(--font-display)` (Newsreader) pour touche éditoriale
- Metrics gap 12→14px

**Hero card** — Elevated accent :
- `border-left: 3px solid var(--section-color)` — accent gauche par section
- Padding 24/28→28/32px, ombre renforcée (`--df2-card-shadow`)
- Hover `translateY(-2px)` avec ombre accentuée

**Progress ring** — Glow animé :
- `filter: drop-shadow(0 0 3px var(--df2-ring-fill))` sur la progression
- Texte 9→10px, poids 600→700

**Command bar** — Glass footer :
- `backdrop-filter: blur(12px)` + fond semi-transparent
- `box-shadow` ascendante au lieu de `border-top`
- Gap shortcuts 6→10px

**Body** — Confort de lecture :
- `max-width: 800px; margin: 0 auto` centré
- Padding-top 20→28px

### 7 améliorations UX (`DeepFocusMode.tsx` + `.css`)

**1. Action toast feedback** :
- Notifications centrées éphémères (1.2s) pour chaque action : Archivé, Supprimé, Annulé, Suivant, Envoyé
- Pill colorée par type (accent pour archive/send, rouge pour delete, gris pour skip)
- Animation `df2ToastPop` (scale + fade)

**2. Section progress bar** :
- Barre 2px sous la topbar, couleur de section
- Fill animé avec `transition: width 0.5s` + glow subtil
- `sectionProgressPercent` calculé par section active

**3. Indicateur "Dernier email"** :
- Affiché quand la queue est vide (1 email restant)
- Icône check-circle + texte "Dernier email de cette section"
- Masqué automatiquement quand un draft est embarqué (`.df2-hero-draft ~ .df2-last-email { display: none }`)

**4. Transition velocity stats** :
- Écran inter-sections enrichi avec : emails/min, meilleure série, nombre de réponses
- Layout flex centré avec mono font + labels uppercase
- `sectionSpeed` calculé par section (total / minutes)

**5. Draft skeleton shimmer** :
- Remplacement du texte "Chargement..." par des barres animées (4 lignes, largeurs variées)
- Gradient shimmer `df2Shimmer` (1.5s infinite, linear-gradient)

**6. Shortcuts overlay (`?`)** :
- Touche `?` → overlay modal avec tous les raccourcis clavier
- Fond blur `backdrop-filter: blur(4px)`, carte centrée avec `df2ShortcutsIn` animation
- Fermeture : `Escape`, `?`, ou clic extérieur
- Bouton `?` ajouté à la command bar

**7. Heure dans la queue** :
- `formatEmailTime(email.received_at)` affiché dans chaque item de queue
- Même format que le hero card et l'inbox

### Fix espace du draft embarqué (`DeepFocusMode.css`)

Problème : `PendingDraftDetail` manquait d'espace dans le hero card car `overflow-y: auto` sur `.df2-body` cassait la chaîne flex.

Solution :
- `.df2-body:has(.df2-hero-draft) { overflow: hidden }` — permet à `flex: 1` de fonctionner
- `.df2-hero-draft ~ .df2-queue .df2-queue-stack { max-height: 72px }` — collapse queue
- `.df2-hero-draft ~ .df2-last-email { display: none }` — masque l'indicateur

### Filter chips — Section toggle & Label cross-filter (`DeepFocusMode.tsx` + `.css`)

**Section chips** :
- Chips pour chaque section (Action, Waiting, FYI, Noise) avec toggle on/off
- Section active = opaque + border colorée, inactive = grisé (0.4 opacity)
- Section courante = glow ring (`box-shadow: 0 0 0 2px`), non-désactivable
- Section terminée = check mark, grisé

**Label cross-filter** :
- Labels custom (hors sections) affichés en 2e rangée de chips
- `availableLabels` calculé via `useMemo` depuis `allSections`
- Intersection filter : emails doivent avoir au moins un label actif
- Bouton "Effacer" les filtres + état vide "Aucun email avec ce label"
- `getLabelDisplayName()` pour noms français

**Props ajoutées** : `allSections`, `onToggleSection(key: PriorityKey)`

### Nettoyage

- Points verts draft-ready retirés des items de queue (confus visuellement)
- `SECTION_LABEL_NAMES` constant pour exclure Action/Waiting/FYI/Noise des label chips

---

## E2E Audit v2 — 85 tests, 100% (13 février)

> **Score: 100% (85/85)** | Temps: 344s | 18 sections

Audit end-to-end complet de l'API backend couvrant le pipeline inbox → labels → drafts → refine → send → archive, plus les features Phase 16.

### Progression

| Version | Score | Tests | Temps |
|---------|-------|-------|-------|
| v1 | 95% (59/62) | 62 | 386s |
| v2 | **100% (85/85)** | **85** | 344s |

### 3 bugs corrigés

1. **Draft generation** — le test v1 appelait `POST /api/emails/{id}/generate-draft` (endpoint inexistant). Corrigé vers `POST /api/emails/{id}/process`. Filtrage des emails `sent:` (prefix IMAP) ajouté pour éviter les 400.
2. **Refined body empty** — le test cherchait `data.body` / `data.draft_body` mais l'endpoint `/drafts/{id}/refine` retourne `data.refined_body` (line 4499 `routes.py`). Corrigé.
3. **Classify-all** — `POST /api/labels/classify-all` n'existe pas (l'auto-labeling est géré par le daemon background, pas par un endpoint REST). Retiré du test.

### Bugfix backend : Quick Reply `quick_replies` manquant (`routes.py:3129-3138`)

Le endpoint `POST /api/emails/{id}/process` ne passait pas le champ `quick_replies` au `PendingDraft`. Les Quick Reply générés via ce endpoint (vs. daemon) avaient `quick_replies=None`, empêchant l'affichage des boutons Oui/Non dans le frontend.

**Fix** : extraction de `quick_replies` depuis `details["critique"]["quick_replies"]` (retourné par SmartRouter) et passage au constructeur `PendingDraft()`.

### Savoirs — Knowledge Base dans Learning (`routes.py:5068-5113`)

Ajout d'une catégorie "Savoirs" dans `GET /api/learning/all` qui parse la section `## Savoir` du fichier `knowledge/memoire.md`. Chaque entrée `### Question?\nAnswer` est exposée comme item avec `id`, `question`, `answer`.

### 18 sections de test

| # | Section | Tests | Description |
|---|---------|-------|-------------|
| 1 | Backend Health | 5 | HTTP 200, services, WebSocket |
| 2 | Email List | 6 | Pagination, offset, structure |
| 3 | Auto-Labeling | 8 | Labels, Noise/Action, filtre |
| 4 | Email Detail | 5 | Body, subject, sender, labels |
| 5 | Draft Generation | 2 | `/process`, preview body |
| 6 | Pending Drafts | 9 | CRUD, detail, by-email, Quick Reply |
| 7 | Draft Refinement | 2 | `/drafts/{id}/refine`, `refined_body` |
| 7b | Refine Text | 3 | `/refine-text`, success flag *(Phase 16)* |
| 8 | Send Flow | 4 | send-new, create draft, mark read/unread |
| 9 | Smart Routing | 3 | Quality stats, `routing_tier` field |
| 10 | Folders | 3 | sent, archived, trash |
| 11 | Settings | 6 | Settings, theme, accounts, snippets |
| 12 | AI Compose | 2 | `/emails/compose`, content length |
| 13 | Error Handling | 6 | Invalid IDs, empty inputs, refine errors |
| 14 | Performance | 5 | Health <5s, labels, inbox, drafts, detail |
| 15 | Learning | 4 | `/learning/all`, categories, stats, patterns *(Phase 16)* |
| 16 | Contacts | 5 | Autocomplete, noreply filter *(Phase 16)* |
| 17 | Memory | 4 | `/memory`, `/intelligence/level` *(Phase 16)* |
| 18 | Costs | 3 | `/costs`, `/costs/history`, `/analytics/quality` |

### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `test_e2e_audit.py` | Réécriture complète v1→v2 : 540→685 lignes, 62→85 tests, 14→18 sections |
| `app/api/routes.py` | +6 lignes: `quick_replies` extraction dans `/process` endpoint |
| `app/api/routes.py` | +45 lignes: catégorie "Savoirs" dans `/learning/all` |

### Leçons apprises

- **Tester les bons endpoints** → toujours vérifier les routes Flask (`@api_bp.route`) avant d'écrire un test, ne pas deviner les URLs
- **Response field names** → lire le `return jsonify({...})` du endpoint pour connaître les noms exacts des champs
- **Sent email IDs** → les emails envoyés ont un prefix `sent:` qui les rend invalides pour `/process` (ils n'existent pas dans l'inbox IMAP)
- **API response formats** → certains endpoints retournent des listes directes (contacts), d'autres des objets wrappés (`{"categories": [...]}`) — tester le type avant `.get()`
- **Pipeline parity** → le daemon et `/process` doivent créer des `PendingDraft` identiques (même champs peuplés) — vérifier les deux code paths

---

## Deep Focus UX Polish + CC/BCC + Labels (14 février)

> **6 fichiers, +309/-58 lignes** — commits `eedb1fd`, `fba9bf0`

Session de polish UX suite à une revue du prototype Deep Focus v3, avec ajout du support CC/BCC et affichage des labels dans `PendingDraftDetail`.

### Deep Focus UX (10 corrections)

| # | Fix | Détail |
|---|-----|--------|
| 1 | **Command bar toggle** | Touche **Espace** (même pattern que le ruban inbox). Barre masquée par défaut, hint "Espace" affiché |
| 2 | **Timer isolé** | `DeepFocusTimer` — composant dédié avec `setInterval(1s)`, ne re-rend pas le parent |
| 3 | **Métriques vitesse** | Snapshot-based (`Date.now() - stats.startTime`), pas de state ticking |
| 4 | **Textarea compact** | `min-height: 60px` (était 200px) |
| 5 | **Éléments masqués en DF2** | `premium-action-bar`, `followup-reminder`, `draft-card-subject` → `display: none` |
| 6 | **Destinataire visible** | `draft-card-recipient` conservé (contient les toggles CC/BCC) |
| 7 | **Zone email original** | Fond blanc + bordure gauche couleur section |
| 8 | **Bannière AI subtile** | `opacity: 0.65`, diamant plus petit |
| 9 | **Bouton reset** | Chip texte "Effacer" (était ×) |
| 10 | **Checkpoint** | Commit `eedb1fd` préserve l'état pré-fix |

### CC/BCC dans PendingDraftDetail

- **Affichage** : CC de l'email original récupérés via `fetchEmailDetail()`, affichés après la ligne "Sujet:"
- **Édition** : Boutons toggle "Cc"/"Cci" sur la ligne "A:" → champs `ContactAutocomplete`
- **API frontend** : `validatePendingDraft()` accepte `cc: string[]`, `bcc: string[]`
- **Backend** : Route `validate_pending_draft` parse cc/bcc, transmet à `send_reply_directly(cc=)` et `create_draft(cc=, bcc=)`

### Labels dans PendingDraftDetail

- Labels récupérés depuis `fetchEmailDetail()` en même temps que les CC
- `LabelBadgeGroup` affiché dans le header collapsé à côté du sujet
- Import `LabelBadgeGroup` ajouté (était seulement `LabelBadge`)

### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `DeepFocusMode.css` | +97 lignes: overrides DF2, timer isolé, command bar Space toggle |
| `DeepFocusMode.tsx` | Refactoring timer, métriques snapshot, command bar toggle |
| `PendingDraftDetail.css` | +66 lignes: styles CC/BCC, labels inline |
| `PendingDraftDetail.tsx` | +86 lignes: CC/BCC toggles, label display, email detail fetch |
| `api.ts` | CC/BCC params dans `validatePendingDraft()` |
| `routes.py` | +9 lignes: parsing cc/bcc dans validate route |

---

## Phase 18 — Spam/Trash Management, Smart Suggestions, UX Redesign & Auto-Reply (16 février)

> **39 fichiers, +3558/-2140 lignes** | Refonte majeure UX + 6 nouveaux endpoints + Smart Suggestions LLM

Session complète de refonte UX avec gestion spam/corbeille, remplacement du système Quick Reply par des Smart Suggestions LLM, redesign premium de la sidebar et des listes, réponse automatique d'absence, et nombreuses améliorations d'ergonomie.

### 1. Gestion Spam & Corbeille — 6 nouveaux endpoints (`routes.py`)

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/emails/<id>/not-spam` | POST | Déplacer un email du spam vers l'inbox |
| `/emails/bulk-not-spam` | POST | Déplacer plusieurs emails du spam |
| `/emails/empty-spam` | POST | Vider le dossier spam définitivement |
| `/emails/<id>/restore` | POST | Restaurer un email de la corbeille |
| `/emails/bulk-restore` | POST | Restaurer plusieurs emails de la corbeille |
| `/emails/empty-trash` | POST | Vider la corbeille définitivement |

**Provider support** (`email_provider.py`, `gmail_adapter.py`, `imap_adapter.py`) :
- Nouvelles méthodes abstraites `restore_from_trash()` et `move_to_inbox()` avec implémentation par défaut `return False`
- **Gmail** : `move_to_inbox()` via ajout label INBOX + retrait label SPAM ; `restore_from_trash()` via API `untrash`
- **IMAP** : `move_to_inbox()` via COPY vers INBOX + DELETE du dossier spam (détection auto du nom de dossier spam Gmail vs standard)

**Frontend** (`EmailList.tsx`, `SwipeableEmailItem.tsx`, `api.ts`) :
- Bannières contextuelles spam/corbeille avec boutons "Vider le dossier"
- Toolbar bulk actions contextuelle : spam → "Pas un indésirable", corbeille → "Restaurer"
- Menu contextuel (clic droit) adapté par dossier : spam → "Pas un indésirable + Supprimer" ; corbeille → "Restaurer + Supprimer définitivement" ; inbox → "Marquer lu/non-lu + Changer le label + Rappel"
- Optimistic UI + rollback sur erreur pour toutes les actions

### 2. Smart Suggestions — Remplacement de Quick Reply (`smart_routing.py`)

**Ancien système supprimé** (Quick Reply — regex, $0, templates statiques) :
- `_detect_binary_question()` et `_QUICK_REPLY_TEMPLATES` entièrement retirés
- Blocs Quick Reply retirés des 3 code paths (STANDARD, STREAMING, COMBINED)
- Endpoint `upgrade_quick_reply` → retourne `410 Gone`
- `quick_replies` marqué comme legacy dans `PendingDraft`

**Nouveau système** (Smart Suggestions — Haiku LLM, ~$0.0001/email) :
- `_generate_smart_suggestions()` : appel Haiku avec sujet + body (300 chars) + sender → JSON array de 2-3 suggestions courtes (5-15 mots)
- Détection de langue pour générer en français ou anglais
- Généré dans les 3 paths après la génération du draft, stocké dans `critique_info["smart_suggestions"]`
- Nouveau champ `smart_suggestions: Optional[list]` dans `PendingDraft` (entity + sérialisation)
- Propagé via daemon (`daemon.py`) et WebSocket `draft_ready`

**Frontend** (`PendingDraftDetail.tsx`) :
- Chips cliquables pour chaque suggestion — un clic pré-remplit le textarea d'instruction
- Remplace les 2 boutons Oui/Non du Quick Reply

### 3. Réponse Automatique d'Absence (`routes.py`)

- `_send_auto_replies_bg()` : thread background déclenché par `list_emails()` (inbox, offset=0)
- Settings-driven : `auto_reply_enabled`, `auto_reply_message`, `auto_reply_start`, `auto_reply_end`
- Tracker persistant JSON (`data/auto_reply_tracker.json`) — 1 réponse par expéditeur par période
- Guards : vérifie la période active, filtre les noreply/noise via `_SKIP_SENDER_PATTERNS`, ignore les emails déjà lus
- Thread-safe : `_auto_reply_lock` + `_auto_reply_running` flag global
- Envoi via `create_draft()` + `send_draft()` avec provider isolé (thread-safe)
- Date picker français (`FrenchDatePicker.tsx`) remplace les inputs natifs dans Settings

### 4. Redesign UX Premium

#### Sidebar (`Sidebar.tsx`, `Sidebar.css`)
- Icônes : passage de `fill="currentColor"` (pleines) à `stroke` outlined (`strokeWidth="1.75"`) + taille 20×20 (était 24×24)
- Background glassmorphism avec profondeur
- État actif : barre verticale lumineuse latérale (remplace le background coloré)
- Hover : animation "shimmer sweep" (balayage lumineux)
- Bouton Compose : gradient + shimmer périodique
- Sidebar collapsed plus étroite (56px)
- Diviseur gradient entre Envoyés et Archives

#### PendingDraftList — Refonte complète (`PendingDraftList.tsx`, `PendingDraftList.css`)
- Layout "inbox-style" flat (rows) remplaçant les cartes empilées
- Groupement par date : Aujourd'hui / Hier / jour / mois via `getDateSectionKey()` + `getSectionLabel()`
- Temps absolu : "14h30" ou "3 févr." remplace "Il y a 2h" (via `formatDraftTime()`)
- Header avec onglets + bouton Composer + bouton Rafraîchir (animation rotation)
- Raccourcis clavier avec ruban toggle (Espace, persisté localStorage)
- Nouveau préfixe CSS `draft-list-*` (remplace `pending-draft-list-*`)

#### EmailList améliorations (`EmailList.tsx`, `EmailList.css`)
- Ruban raccourcis réorganisé : groupé par Navigation/Composition/Actions/Mode avec séparateurs
- Ruban conditionnel par dossier (pas de raccourcis d'action dans spam/corbeille)
- Visibilité du ruban persistée dans localStorage
- Badge compteur "non-lus" affiché uniquement pour l'inbox (pas pour sent/spam/trash)
- Onglets header : style opacity-fade (actif=opaque, inactif=muté) remplace les pills

#### SwipeableEmailItem (`SwipeableEmailItem.tsx`, `SwipeableEmailItem.css`)
- Badge "Draft prêt" : texte supprimé, remplacé par icône crayon SVG seul (plus compact)
- `isUnread` forcé à false pour le dossier sent
- Item de menu contextuel "Changer le label" ajouté pour les dossiers par défaut

#### Compose / Reply
- **NewMessageModal** (`NewMessageModal.tsx`, `NewMessageModal.css`) :
  - Slash commands réorganisés : Actions (confirmer/décliner/relancer/remerciement/invitation) + Transformations (court/raccourcir/formel/amical/corrige/traduis)
  - Guard `bodyInitializedRef` empêche la signature async d'écraser le texte utilisateur
  - Séparation AI : mode refine → `/refine-text`, mode compose → `/compose`
  - Diff overlay ne s'auto-efface plus (reste jusqu'au clic)
  - Animation envoi rallongée (1200ms → 2500ms)
  - Sujet auto-capitalize première lettre
  - Guard `slashJustSelectedRef` empêche le double-trigger après sélection slash

- **ReplyComposer** (`ReplyComposer.tsx`, `ReplyComposer.css`) :
  - CC/BCC éditables avec `ContactAutocomplete` + boutons toggle "Cc"/"Cci"
  - CC pré-rempli pour `reply_all` depuis l'email original
  - Nettoyage Re:/Fwd: dupliqués dans le sujet (`cleanSubject`)
  - Date forward format français long
  - Prompt vide → auto-génère ("Réponds de manière appropriée à cet email")
  - Placeholders cycliques (3 hints rotatifs toutes les 3s avec animation fade)
  - Forward masque les quick chips

#### Cards & Panels
- `PendingDraftDetail.css` : border-radius 16px, ombres plus douces, glass background action bar
- `NewMessageModal.css` : border-radius 16px, bordures plus douces, header/footer glass
- Thèmes mis à jour (`dark-luxury.css`, `futurist-silver.css`) : badge draft-ready → icône crayon

### 5. Deep Focus Mode améliorations (`DeepFocusMode.tsx`, `DeepFocusMode.css`)

- Labels seedés depuis `labels.json` via `useLabels()` (tous les labels custom apparaissent même à 0)
- Sections vides masquées dans les indicateurs d'étapes
- Compteur par étape : `{processed}/{total}` pour l'étape courante, `{total}` pour les autres
- Clic droit sur hero card → label picker
- Clic droit sur noise row → label picker
- Toast undo : "Annulé" → "Précédent"
- Footer noise simplifié : uniquement bouton "Terminer"
- Flèches navigation : `←`/`→` → `‹`/`›` + glassmorphism premium avec animation "light sweep"
- Layout stacked (email en haut / draft en bas) au lieu de côte à côte
- Section bar masquée, step count badges ajoutés
- Panel détail supprimé de Deep Focus (tout est inline dans le hero card)
- À la sortie, `handleCloseEmailDetail()` appelé pour nettoyer l'état

### 6. Navigation & Raccourcis clavier

- **J/K navigation** (`App.tsx`) : fonctionne maintenant pour tous les onglets email (inbox, sent, archived, spam, trash), pas uniquement inbox
- **D shortcut** (`useAppShortcuts.ts`) : touche `D` lance Deep Focus
- **Deep Focus guard** : quand actif, tous les raccourcis arrow + single-key sont ignorés (gérés par Deep Focus)
- **Detail panel guard** : quand visible, ArrowLeft/ArrowRight ignorés (gérés par le panneau détail)
- **ArrowLeft/ArrowRight** dans `EmailDetailModal.tsx` : navigation entre emails via `navInfo`
- **PendingDraftDetail nav** : `navInfo` + prev/next passés dans le contexte inbox
- **Deep Focus start** : force `activeTab='inbox'` + reset label/folder
- **Command palette** : entrées Navigation (inbox/drafts/sent/archived) retirées (sidebar suffit)

### 7. Backend — Refine & Pipeline

- **Reasoning leakage** (`refine_email.py`) : nouveau `_strip_reasoning_leakage()` avec patterns regex pour supprimer les blocs `<thinking>`, `Let me...`, `I'll...`, `Here's...`
- **Refine prompt durci** : instruction `INTERDIT` renforcée, exception traduction pour critique, format de sortie strict
- **Chain-of-thought stripping** (`routes.py`) : `_strip_refine_reasoning()` appliqué aux endpoints `/drafts/<id>/refine` et `/refine-text`
- **BCC complet** : `_create_draft_and_mark_read()` et `_create_draft_and_mark_read_no_bg()` acceptent maintenant `bcc`
- **Send fast path skip BCC** : quand BCC est présent, `send_reply_directly()` est contourné (ne supporte pas BCC) → fallback vers `create_draft()`
- **Email ID pattern** : regex mis à jour pour accepter `:` (pour les IDs `sent:xxx`)
- **Sent ID SQLite** : stocké sans prefix `sent:`, re-préfixé à la lecture pour cohérence frontend
- **DraftQualityPanel** (`DraftQualityPanel.tsx`) : tiers filtrés aux tiers connus + ligne "En moyenne" en bas

### Fichiers modifiés (32 fichiers, hors package-lock/yarn.lock)

| Fichier | Changement |
|---------|-----------|
| `App.tsx` | J/K nav tous onglets, DF start reset, command palette cleanup, nav props |
| `DeepFocusMode.tsx` | Labels from JSON, empty sections hidden, hero/noise context menu |
| `DeepFocusMode.css` | Glassmorphism arrows, stacked layout, step badges |
| `DraftQualityPanel.tsx/css` | Tier filter, "En moyenne" row |
| `EmailDetailModal.tsx` | Arrow key navigation |
| `EmailList.tsx` | Spam/trash handlers, bulk actions, ribbon redesign |
| `EmailList.css` | Tabs opacity-fade, spam/trash banners |
| `EmailListHeader.tsx` | Unread badge inbox-only, DF button text, achievements inbox-only |
| `PendingDraftDetail.tsx` | Smart suggestions, slash commands, auto-reply mode, 2-column zones |
| `PendingDraftDetail.css` | Smart suggestion chips, glass action bar, zones layout |
| `PendingDraftList.tsx` | Date grouping, flat row layout, header tabs, shortcuts ribbon |
| `PendingDraftList.css` | Complete rewrite inbox-style |
| `Settings.tsx` | FrenchDatePicker for auto-reply dates |
| `Sidebar.tsx` | Outlined stroke icons, divider |
| `Sidebar.css` | Glassmorphism, luminous edge bar, shimmer sweep, compose gradient |
| `SwipeableEmailItem.tsx` | Context menu per folder, pencil icon badge |
| `SwipeableEmailItem.css` | Danger menu item, pencil badge |
| `NewMessageModal.tsx` | Slash reorg, body guard, compose/refine split, diff sticky |
| `NewMessageModal.css` | 16px radius, glass, diff sticky, sent animation slow |
| `ReplyComposer.tsx` | CC/BCC editable, cycling placeholders, clean subject |
| `ReplyComposer.css` | CC/BCC rows, placeholder animation |
| `useAppShortcuts.ts` | D shortcut, DF guard, detail panel guard |
| `useResizePanel.ts` | Minor fix |
| `api.ts` | Smart suggestions type, BCC, 6 spam/trash methods |
| `dark-luxury.css` | Draft badge icon update |
| `futurist-silver.css` | Draft badge icon update |
| `routes.py` | 6 endpoints, auto-reply, BCC, smart suggestions, refine stripping |
| `refine_email.py` | Reasoning leakage strip, instruction passthrough, format strict |
| `daemon.py` | Smart suggestions propagation |
| `pending_draft.py` | `smart_suggestions` field |
| `email_provider.py` | `restore_from_trash()`, `move_to_inbox()` abstractions |
| `gmail_adapter.py` | Gmail move-to-inbox, untrash |
| `imap_adapter.py` | IMAP move-to-inbox (spam detection) |
| `smart_routing.py` | Quick Reply removed, Smart Suggestions via Haiku |

### Nouveaux fichiers

| Fichier | Description |
|---------|-----------|
| `FrenchDatePicker.tsx` | Composant date picker avec labels et mois en français |
| `FrenchDatePicker.css` | Styles du date picker français |

---

## Suppression des thèmes Dark Luxury & Futurist — Clarity unique (20 mai 2026)

Retrait complet des thèmes visuels « Dark Luxury » (`dark-luxury`) et « Futurist » (`futurist`). Seul **Clarity** (`default`) subsiste ; la section Thème des réglages ne propose plus qu'une option.

- **Frontend** : `ThemeId` réduit à `"default"` (`useTheme.ts`), coercion de tout thème legacy persisté (localStorage/backend) vers `default` — un compte resté sur un thème supprimé est débloqué automatiquement. Suppression du code de chargement CSS dynamique (`loadThemeCSS`, `preloadSavedThemeCSS`, `loadedThemes`). Picker `Settings.tsx` réduit à Clarity.
- **CSS** : suppression de `themes/dark-luxury.css` + `themes/futurist-silver.css` (~3460 lignes) et de toutes les règles `[data-theme="dark-luxury"|"futurist"|"futurist-silver"]` dans `index.css` + ~12 CSS de composants. Polices mortes (`DM Sans`, `Syne`, `Outfit`) retirées du preload `index.html`.
- **Backend** : `VALID_THEMES = {"default"}` (`app/api/settings.py`) — un PATCH d'un thème retiré renvoie 400.
- **Contenu support** : `chatEngine.ts` + `SupportHelpSection.tsx` mis à jour (plus de « Velvet & Gold » / « Liquid Chrome »).
- **Tests** : pytest (`test_patch_settings_removed_theme_rejected`), Vitest (`useTheme.test.ts` — coercion legacy), e2e (`settings-parameters` → 1 option Clarity ; `regression-lessons` → coercion legacy vers `default`).

Diff : 29 fichiers, +92 / −4360.
