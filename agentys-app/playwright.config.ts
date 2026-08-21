import { defineConfig, devices } from '@playwright/test'
import { readFileSync } from 'fs'

// --- Quarantaine des échecs chroniques (e2e/quarantine.json) ---
// Tests rouges sur ≥4 runs nocturnes consécutifs : ils ne portent plus aucun
// signal et brûlaient ~80% du runtime de la suite en timeouts (audit
// 2026-06-13). Exclus du run par défaut ; un échec redevient donc une vraie
// régression. Réparation progressive : retirer l'entrée du JSON une fois le
// test vert.
//   E2E_QUARANTINE=include  → exécute TOUTE la suite (quarantaine comprise)
//   E2E_QUARANTINE=only     → n'exécute QUE la quarantaine (mode réparation)
// La cible grep de Playwright est titlePath().join(' ') sans numéros de
// ligne : "<project> <fichier relatif au testDir> <describe…> <titre>".
const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const quarantine = JSON.parse(
  readFileSync(new URL('./e2e/quarantine.json', import.meta.url), 'utf-8'),
) as { tests: Array<{ file: string; title: string }> }
const quarantineRegex = quarantine.tests.length
  ? new RegExp(
      quarantine.tests
        .map(
          (t) =>
            `${escapeRegex(t.file.replace(/^e2e\//, ''))} ${escapeRegex(t.title.split(' › ').join(' '))}$`,
        )
        .join('|'),
    )
  : undefined
const quarantineMode = process.env.E2E_QUARANTINE

export default defineConfig({
  grep: quarantineMode === 'only' ? quarantineRegex : undefined,
  grepInvert:
    quarantineMode === 'include' || quarantineMode === 'only'
      ? undefined
      : quarantineRegex,
  testDir: './e2e',
  testIgnore: ['**/_*.spec.ts', '**/*.py'],
  // Warm the Vite dev server before tests so the first-load module compile
  // doesn't eat into the per-test timeout (see e2e/global-setup.ts).
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // retries=0 en CI : tests flaky = bugs à fixer, pas à masquer. 3× attempts
  // multiplie le runtime et fait exploser le budget Actions.
  retries: 0,
  // workers=2 en CI : le runner Linux a 4 vCPUs, 2 workers ≈ 2× plus rapide
  // que workers=1. Plus que 2 pose des problèmes de ressources (backend Python
  // partagé, sockets qui se battent).
  workers: process.env.CI ? 2 : undefined,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:1420',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Couverture cross-browser opt-in : `npx playwright install firefox` puis
    // `PW_FIREFOX=1 yarn test:e2e --project=firefox`. Hors défaut pour ne pas
    // doubler le budget Actions (les runners CI n'installent que chromium).
    ...(process.env.PW_FIREFOX
      ? [{ name: 'firefox', use: { ...devices['Desktop Firefox'] } }]
      : []),
  ],

  webServer: {
    command: 'yarn dev',
    url: 'http://localhost:1420',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
    // Mode API ABSOLU : la suite a été écrite pour des mocks sur les origins
    // :5050 (cf. fixtures/setup.ts). La CSP (avril 2026) avait cassé ce mode
    // → cspDevRelaxPlugin (vite.config.ts) le rétablit en dev uniquement.
    // ATTENTION reuseExistingServer : un `yarn dev` déjà lancé SANS cette
    // variable (mode proxy) sera réutilisé tel quel et fera échouer les specs
    // à mocks :5050 — tuer le serveur :1420 avant de lancer la suite en cas
    // de doute.
    env: {
      VITE_API_URL: 'http://127.0.0.1:5050',
    },
  },
})
