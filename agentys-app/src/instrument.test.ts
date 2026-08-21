// Audit fix L-1 (issue #544) — Sentry frontend DSN must not be hardcoded.
//
// Bug : `agentys-app/src/instrument.ts:6` embarquait le DSN Sentry en clair
// dans le bundle client. Le DSN est public-by-design (Sentry frontend
// tourne dans le navigateur) mais le hardcoder empêche la rotation sans
// rebuild ET fait qu'un fork du repo embarque par accident notre DSN.
//
// Fix : le DSN est désormais lu depuis `import.meta.env.VITE_SENTRY_DSN`
// (configuré dans Vercel) ; absent → Sentry désactivé silencieusement.
//
// Ce test verrouille la convention au niveau du source pour empêcher
// qu'un futur refactor ne ré-introduise un literal.

import { describe, it, expect } from "vitest";
// Vite's `?raw` query loads the file content as a string at build time —
// avoids pulling Node APIs into the test (which would require @types/node
// in tsconfig.app.json and pollute the app type surface).
import source from "./instrument.ts?raw";

describe("instrument.ts — L-1 audit (no hardcoded DSN)", () => {
  it("does not contain a hardcoded Sentry DSN URL", () => {
    // Un DSN Sentry a la forme `https://<key>@<org>.ingest.<region>.sentry.io/<project>`.
    // On grep le motif `ingest.*.sentry.io` qui est invariant et non-mockable.
    const dsnPattern = /https:\/\/[a-f0-9]+@o\d+\.ingest\.[a-z]+\.sentry\.io\/\d+/i;
    expect(source).not.toMatch(dsnPattern);
  });

  it("reads the DSN from import.meta.env.VITE_SENTRY_DSN", () => {
    // Garantit qu'on a bien migré vers l'env var (et pas, par exemple,
    // process.env qui ne marche pas en build Vite client-side).
    expect(source).toMatch(/import\.meta\.env\.VITE_SENTRY_DSN/);
  });

  it("guards Sentry.init behind a DSN-present check", () => {
    // Sans cette gate, `Sentry.init({ dsn: undefined })` log un warning
    // et perturbe la console en dev/staging quand le DSN n'est pas
    // configuré.
    expect(source).toMatch(/if\s*\(\s*dsn\s*\)/);
  });
});
