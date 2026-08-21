/**
 * Script d'inspection UX nocturne — exécuté via Node + Playwright
 */
import { chromium } from '@playwright/test';
import { writeFileSync, mkdirSync } from 'fs';

const TOKEN = process.env.JWT_TOKEN || '';
const FRONTEND = process.env.TARGET_FRONTEND || 'http://localhost:1420';
const LABEL = process.env.TARGET_LABEL || 'LOCAL';
const REPORT_FILE = process.argv[2] || 'tasks/nightly-reports/ux-report-tmp.md';
const SS_DIR = '/tmp/nightly-ux-screenshots';

const issues = { critical: [], important: [], minor: [] };
const screenshots = [];
let sectionsOk = 0;

function imp(id, section, desc, suggestion) { issues.important.push({ id, section, desc, suggestion }); }
function min(id, section, desc, suggestion) { issues.minor.push({ id, section, desc, suggestion }); }

async function run() {
  mkdirSync(SS_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // Listeners enregistrés AVANT toute navigation
  const consoleMsgs = [];
  page.on('console', (msg) => {
    if (['error', 'warning'].includes(msg.type())) {
      consoleMsgs.push({ type: msg.type(), text: msg.text(), url: msg.location()?.url || '' });
    }
  });
  const failedRequests = [];
  page.on('response', (resp) => {
    const s = resp.status();
    if (s >= 400 && !resp.url().includes('favicon')) {
      failedRequests.push({ url: resp.url(), status: s, method: resp.request().method() });
    }
  });

  async function ss(name) {
    const path = `${SS_DIR}/${name}.jpeg`;
    await page.screenshot({ path, type: 'jpeg', quality: 65 });
    screenshots.push({ name, path });
  }

  async function tryClick(selectors) {
    for (const sel of selectors) {
      try {
        const el = await page.$(sel);
        if (el) { await el.click(); return true; }
      } catch {}
    }
    return false;
  }

  // ── Setup ─────────────────────────────────────────────────────────────────
  await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
  if (TOKEN) {
    await page.evaluate((tok) => { localStorage.setItem('agentys_jwt', tok); }, TOKEN);
    await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
  }
  await page.waitForTimeout(2500);
  const pageTitle = await page.title();

  // ── 1. Inbox ──────────────────────────────────────────────────────────────
  try {
    await ss('01-inbox');
    const hasEmails = await page.$('[class*="EmailListItem"], [class*="email-item"], [data-testid*="email-row"]');
    if (!hasEmails) imp('IMP-1', 'Inbox', 'Aucun email visible dans la liste inbox', 'Vérifier le chargement des emails et les sélecteurs');
    const firstEmail = await page.$('[class*="EmailListItem"]:first-child, [class*="email-item"]:first-child');
    if (firstEmail) {
      await firstEmail.click();
      await page.waitForTimeout(1200);
      await ss('01b-inbox-email-open');
    }
    sectionsOk++;
  } catch (e) { imp('IMP-1', 'Inbox', `Inbox: ${e.message.slice(0, 80)}`, 'Investiguer le composant inbox'); }

  // ── 2-7. Dossiers sidebar ─────────────────────────────────────────────────
  const folders = [
    ['Brouillons', ['text=Brouillons', 'text=Drafts', '[href*="draft"]', '[class*="draft"]']],
    ['Envoyés',    ['text=Envoyés', 'text=Sent', '[href*="sent"]', '[class*="sent"]']],
    ['Archive',    ['text=Archive', 'text=Archivés', '[href*="archiv"]', '[class*="archiv"]']],
    ['Spam',       ['text=Spam', '[href*="spam"]', '[class*="spam"]']],
    ['Corbeille',  ['text=Corbeille', 'text=Trash', '[href*="trash"]', '[class*="trash"]']],
    ['Snoozed',    ['text=Snoozed', 'text=Reporté', '[href*="snooze"]', '[class*="snooze"]']],
  ];
  for (let i = 0; i < folders.length; i++) {
    const [name, sels] = folders[i];
    const num = String(i + 2).padStart(2, '0');
    try {
      const clicked = await tryClick(sels);
      if (!clicked) min(`MIN-${i + 1}`, name, `Lien sidebar "${name}" introuvable`, 'Vérifier les sélecteurs sidebar');
      await page.waitForTimeout(1000);
      await ss(`${num}-${name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s/g, '-')}`);
      sectionsOk++;
    } catch (e) { imp(`IMP-${i + 2}`, name, `${name}: ${e.message.slice(0, 80)}`, 'Investiguer la sidebar'); }
  }

  // ── 8. Paramètres ─────────────────────────────────────────────────────────
  try {
    const settingOpened = await tryClick([
      '[data-testid="settings-btn"]', '[aria-label*="ettings"]', '[aria-label*="aramètre"]',
      '[class*="settings-icon"]', 'a[href*="settings"]', '[title*="Settings"]',
    ]);
    if (!settingOpened) await page.keyboard.press(',');
    await page.waitForTimeout(1500);
    await ss('08-settings-first');

    const lastSubSection = await tryClick(['text=Général', 'text=General', 'text=Automatisation', 'text=Automation']);
    if (!lastSubSection) min('MIN-7', 'Paramètres', 'Sous-section finale des paramètres introuvable', 'Vérifier les onglets paramètres');
    await page.waitForTimeout(800);
    await ss('08-settings-last');
    sectionsOk++;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);
  } catch (e) { imp('IMP-8', 'Paramètres', `Paramètres: ${e.message.slice(0, 80)}`, 'Vérifier l\'accès aux paramètres'); }

  // ── 9. Composer ───────────────────────────────────────────────────────────
  try {
    const composeOpened = await tryClick([
      '[data-testid*="compose"]', 'button[aria-label*="ompose"]', 'button[aria-label*="édiger"]',
      '[class*="compose-button"]', '[class*="ComposeButton"]', 'text=Composer', 'text=New Email',
    ]);
    if (!composeOpened) await page.keyboard.press('n');
    await page.waitForTimeout(1500);
    await ss('09-compose');
    const modal = await page.$('[class*="modal"], [class*="compose"], [role="dialog"]');
    if (!modal) imp('IMP-9', 'Composer', 'Modale composer non détectée après clic/touche N', 'Vérifier le raccourci clavier N et le bouton composer');
    sectionsOk++;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);
  } catch (e) { imp('IMP-9', 'Composer', `Composer: ${e.message.slice(0, 80)}`, 'Vérifier la modale composer'); }

  // ── 10. Recherche ─────────────────────────────────────────────────────────
  try {
    const searchOpened = await tryClick([
      'input[type="search"]', 'input[placeholder*="earch"]', 'input[placeholder*="echerche"]',
      '[class*="SearchBar"] input', '[class*="search-input"]', '[data-testid*="search"]',
    ]);
    if (searchOpened) {
      await page.keyboard.type('test');
    } else {
      await tryClick(['[class*="search"]', '[class*="Search"]']);
      await page.waitForTimeout(400);
      await page.keyboard.type('test');
    }
    await page.waitForTimeout(1200);
    await ss('10-search');
    sectionsOk++;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  } catch (e) { min('MIN-8', 'Recherche', `Recherche: ${e.message.slice(0, 80)}`, 'Vérifier la barre de recherche'); }

  // ── 11. Palette de commandes ──────────────────────────────────────────────
  try {
    await page.keyboard.press('Control+k');
    await page.waitForTimeout(1000);
    await ss('11-command-palette');
    const palette = await page.$('[class*="command"], [class*="palette"], [class*="kbar"], [role="dialog"] input');
    if (!palette) min('MIN-9', 'Palette commandes', 'Palette de commandes non détectée après Ctrl+K', 'Vérifier le raccourci Ctrl+K');
    sectionsOk++;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  } catch (e) { min('MIN-9', 'Palette commandes', `Palette: ${e.message.slice(0, 80)}`, 'Vérifier Ctrl+K'); }

  // ── 12. Sprint / Deep Focus ───────────────────────────────────────────────
  try {
    const sprintOpened = await tryClick([
      '[data-testid*="sprint"]', '[data-testid*="focus"]',
      '[class*="SprintButton"]', '[class*="DeepFocus"]',
      '[aria-label*="Sprint"]', '[aria-label*="Focus"]',
      '[class*="bolt"]', '[class*="lightning"]',
    ]);
    if (!sprintOpened) min('MIN-10', 'Sprint/Deep Focus', 'Icône Sprint/Deep Focus introuvable', 'Vérifier l\'icône éclair dans l\'interface');
    await page.waitForTimeout(1200);
    await ss('12-sprint');
    sectionsOk++;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  } catch (e) { min('MIN-10', 'Sprint/Deep Focus', `Sprint: ${e.message.slice(0, 80)}`, 'Investiguer le composant Sprint'); }

  await ss('13-final-state');
  await browser.close();

  // ── Rapport ───────────────────────────────────────────────────────────────
  const now = new Date().toISOString().slice(0, 16).replace('T', ' ');
  const { critical, important, minor } = issues;

  function renderIssues(arr) {
    if (!arr.length) return '_Aucune_\n';
    return arr.map(i => `### [${i.id}] ${i.section}\n- **Description**: ${i.desc}\n- **Suggestion**: ${i.suggestion}\n`).join('\n');
  }

  const consoleTable = consoleMsgs.length
    ? '| # | Type | Message | Source |\n|---|------|---------|--------|\n' +
      consoleMsgs.map((m, i) => `| ${i+1} | ${m.type} | ${m.text.slice(0,100).replace(/\|/g,'/')} | ${m.url.slice(0,60)} |`).join('\n')
    : '_Aucune erreur/warning console capturée_';

  const failedTable = failedRequests.length
    ? '| # | URL | Status | Méthode |\n|---|-----|--------|----------|\n' +
      failedRequests.map((r, i) => `| ${i+1} | ${r.url.slice(0,80).replace(/\|/g,'/')} | ${r.status} | ${r.method} |`).join('\n')
    : '_Aucune requête échouée_';

  const ssListMd = screenshots.map(s => `- \`${s.name}\`: \`${s.path}\``).join('\n');

  const report = `# Nightly UX Report — ${now} — ${LABEL}

## Résumé
- **Cible**: ${FRONTEND}
- **Titre page**: ${pageTitle}
- **Sections testées**: ${sectionsOk}/12
- **Console errors**: ${consoleMsgs.filter(m=>m.type==='error').length} | **Warnings**: ${consoleMsgs.filter(m=>m.type==='warning').length}
- **Requêtes échouées**: ${failedRequests.length}
- **Issues critiques**: ${critical.length} | **Importantes**: ${important.length} | **Mineures**: ${minor.length}

## Issues critiques
${renderIssues(critical)}
## Issues importantes
${renderIssues(important)}
## Issues mineures
${renderIssues(minor)}
## Console Errors & Warnings
${consoleTable}

## Requêtes échouées
${failedTable}

## Screenshots
${ssListMd}
`;

  writeFileSync(REPORT_FILE, report, 'utf-8');
  console.log(`DONE | Rapport: ${REPORT_FILE} | Sections: ${sectionsOk}/12 | Crit:${critical.length} Imp:${important.length} Min:${minor.length}`);
}

run().catch((err) => {
  const report = `# Nightly UX Report — ERREUR\n\n## Erreur fatale\n\`\`\`\n${err.message}\n${err.stack}\n\`\`\`\n`;
  writeFileSync(process.argv[2] || 'tasks/nightly-reports/ux-report-error.md', report);
  console.error('ERREUR:', err.message);
  process.exit(1);
});
