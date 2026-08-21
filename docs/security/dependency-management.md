# Dependency Management — CASA Tier 2 (ASVS V14.2)

> Procédure interne pour l'audit, la mise à jour et l'exception sur les
> dépendances tierces d'Agentys. Couvre Python (backend Flask), JS/TS (Tauri
> + mobile Expo), GitHub Actions. Référence : issue [#211](https://github.com/nathan/agentys/issues/211),
> parent [#205](https://github.com/nathan/agentys/issues/205).

## Périmètre

| Écosystème | Manifeste | Outil audit | Auto-update |
|---|---|---|---|
| Python backend | `requirements.txt`, `requirements-dev.txt` | `pip-audit` (OSV) | Dependabot `pip` |
| Tauri (frontend desktop) | `agentys-app/package.json` + `yarn.lock` (Yarn Berry) | `yarn npm audit` | Dependabot `npm` `/agentys-app` |
| Mobile Expo | `agentys-mobile/package.json` + `yarn.lock` (Yarn 1) | `yarn audit` | Dependabot `npm` `/agentys-mobile` |
| GitHub Actions | `.github/workflows/*.yml` | (n/a — Dependabot direct) | Dependabot `github-actions` |
| `browser_plugin/` | `manifest.json` (MV3) seul | **N/A** | **N/A** — voir ci-dessous |
| `ai_team/deploy/requirements.{pm,worker}.txt` | (Hetzner standalone) | `pip-audit` manuel | Hors Dependabot (déploiement séparé) |

### Pourquoi `browser_plugin/` est N/A

L'extension Chrome MV3 dans `browser_plugin/` est en **vanilla JavaScript** :
pas de `package.json`, pas de bundler, pas de `node_modules`. Les seules
dépendances sont les APIs natives du navigateur (`chrome.*`, `fetch`, DOM).
Aucun écosystème npm/pip à auditer. Si on introduit un jour un build step
(esbuild, rollup, webpack), il faudra ajouter une entrée Dependabot et un step
au job nightly `dependency-audit`.

## Audit local

### Python — `pip-audit`

```bash
pip install pip-audit
pip-audit -r requirements.txt
```

**Workaround Windows — `sqlcipher3-binary`**

`sqlcipher3-binary` ne distribue pas de wheel Windows (Linux + macOS uniquement).
Sur une station Windows, `pip-audit` échoue à l'install dans son venv temporaire.
Deux options :

```bash
# Option 1 : exclure manuellement
grep -v "sqlcipher3-binary" requirements.txt > /tmp/req-audit.txt
pip-audit -r /tmp/req-audit.txt

# Option 2 : utiliser WSL ou Docker (recommandé pour parité avec la CI)
docker run --rm -v "${PWD}:/app" -w /app python:3.11-slim \
  bash -c "pip install pip-audit && pip-audit -r requirements.txt"
```

La CI nightly tourne sur `ubuntu-latest` et n'a pas ce problème.

### JS/TS — `yarn audit`

```bash
# agentys-app (Yarn Berry)
cd agentys-app
yarn npm audit --environment production --severity high

# agentys-mobile (Yarn 1 classic)
cd agentys-mobile
yarn audit --level high
```

**Note Yarn 1** : `yarn audit` retourne un **bitmask** d'exit code (1=info,
2=low, 4=moderate, 8=high, 16=critical). Le CI nightly masque les bits
low/moderate (1+2+4 = 7) pour ne fail que sur high/critical (≥ 8).

## CI — job nightly `dependency-audit`

Workflow : `.github/workflows/nightly.yml`, cron `0 4 * * *` (4h UTC).

```
backend-tests-coverage ─┐
frontend-checks ────────┤
dependency-audit ───────┴─→ nightly-summary (toujours)
                        └─→ dependency-audit-alert (si failure)
```

**`dependency-audit-alert`** ouvre automatiquement une issue avec les labels
`auto-sentinelle,security,dependencies` (dédoublonnage par titre). Cette
issue contient :

- Le lien vers le run GitHub Actions
- Une procédure de résolution (étapes 1-5)
- Un pointeur vers ce document

**Seuil** : HIGH ou CRITICAL bloque. LOW + MODERATE sont loggés mais ne
fail pas le job (cohérent avec `yarn npm audit --severity high` côté
push CI dans `test.yml`).

## Mise à jour des dépendances

### Bornes hautes — pattern semver

Toutes les deps Python ont une **borne haute** depuis l'issue #211 :

```
package>=X.Y.Z,<{current_major + 1}.0
```

Cela force une **review Dependabot explicite** avant tout passage à un
major suivant — protection contre `pip install -U` qui tirerait un major
breaking silencieusement (erreur déjà rencontrée lors du jump React/Tauri
v1→v2).

### Rotation après un nouveau major

Quand Dependabot ouvre une PR pour un major (ex. `cryptography 47→48`) :

1. Tester la PR localement : `pip install -r requirements.txt && pytest tests/`
2. Si OK : merger la PR (Dependabot bumpe automatiquement le `>=` et la
   borne `<{major+1}.0` doit être ajustée manuellement)
3. Mettre à jour la borne haute dans `requirements.txt`
4. Déployer → smoke test prod

Packages avec **majors fréquents** (rotation manuelle plus régulière) :

- `cryptography` (~3 majors/an)
- `flask-cors`, `flask-compress`
- `Pillow` (cadence 6-12 mois)
- `psutil` (cadence 12 mois)

### Bornes JS/TS

Les `package.json` utilisent du caret (`^X.Y.Z`) qui est déjà semver-bound
par défaut (pas de bump major automatique). Pas de pattern explicite à
ajouter — Dependabot fait le travail. Les `resolutions` dans
`agentys-app/package.json` et `agentys-mobile/package.json` servent à
forcer une version sur une transitive vulnérable (voir section
**Exceptions** ci-dessous).

## Exceptions — CVE non patchable

Si une CVE HIGH/CRITICAL ne peut pas être résolue immédiatement (pas de
patch upstream, ou breaking change qui bloque), documenter ici.

**Format** :

```markdown
### CVE-YYYY-NNNNN — <package> <vulnerable_versions>

- **Date détectée** : YYYY-MM-DD
- **Severity** : HIGH | CRITICAL
- **Vecteur** : <description courte>
- **Exploitabilité chez nous** : NON | OUI (mitigée par X)
- **Mitigation** : <ce qui empêche l'exploit en attendant un patch>
- **Plan de résolution** : <quand/comment on règle ça>
- **Lien upstream** : <URL issue/PR upstream>
```

**Exceptions actives** : aucune au 2026-04-29.

## Resolutions — fix transitives

Quand une CVE est dans une dépendance **transitive** (sub-dep d'une dep
directe), on ne peut pas bumper la dep directe sans casser. Dans ce cas,
ajouter une **`resolutions`** clé dans le `package.json`.

### `agentys-app` — Yarn Berry

```json
"resolutions": {
  "minimatch": ">=3.1.5",
  "brace-expansion": ">=1.1.13",
  "flatted": ">=3.4.2",
  "picomatch": ">=4.0.4",
  "ajv": "^6.14.0",
  "socket.io-parser": ">=4.2.6",
  "undici": "^7.24.0",
  "rollup": ">=4.59.0"
}
```

### `agentys-mobile` — Yarn 1 classic

```json
"resolutions": {
  "uuid": "^14.0.0",
  "postcss": "^8.5.10"
}
```

Pourquoi ces deux entrées (au 2026-04-29) :

- **uuid <14** — buffer bounds check missing (CVE moderate, 4 chemins via
  `expo>@expo/config-plugins>xcode>uuid`). Pin à `^14.0.0` pour expo CLI
  + jest-expo + metro-config.
- **postcss <8.5.10** — XSS via `</style>` non échappé dans le CSS
  Stringify Output (CVE moderate, 2 chemins via `expo>@expo/metro-config`).

Après ajout, **toujours** :

```bash
rm -rf node_modules
yarn install
yarn audit --level high  # confirmer que les vulns sont gone
```

## Lecture des labels Dependabot

Issues / PRs créés automatiquement par Dependabot portent ces labels :

| Label | Source | Sens |
|---|---|---|
| `dependencies` | Dependabot config | Toute PR auto-deps |
| `python` | `dependabot.yml` (groupe pip) | Backend Python |
| `frontend` | `dependabot.yml` (groupe agentys-app) | Tauri |
| `mobile` | `dependabot.yml` (groupe agentys-mobile) | Expo / RN |
| `ci` | `dependabot.yml` (groupe github-actions) | Workflows |
| `auto-sentinelle` | `dependency-audit-alert` job | Alert auto sur CVE |
| `security` | `dependency-audit-alert` job | + tracking CASA |

## Garde-fous CASA Tier 2

Critères ASVS V14.2 satisfaits par cette pipeline :

- **V14.2.1** — All components are up to date : ✅ Dependabot weekly + nightly audit
- **V14.2.2** — All unneeded features removed : ⚠️ revue manuelle annuelle (pas auto)
- **V14.2.3** — Inventory of components maintained : ✅ `requirements.txt` +
  `package.json` lockés en git
- **V14.2.4** — Components from official sources over secure links : ✅ PyPI
  + npm registry HTTPS (defaults)
- **V14.2.5** — Removal of unsupported components : ⚠️ revue manuelle (pas auto)

## Références

- [ASVS V14.2 — Dependency](https://github.com/OWASP/ASVS/blob/master/4.0/en/0x22-V14-Config.md)
- [pip-audit](https://github.com/pypa/pip-audit) (OSV.dev backend)
- [GitHub Dependabot](https://docs.github.com/en/code-security/dependabot)
- [Yarn 1 audit bitmask](https://classic.yarnpkg.com/lang/en/docs/cli/audit/)
- [Yarn Berry npm audit](https://yarnpkg.com/cli/npm/audit)
- Issue parent CASA : [#205](https://github.com/nathan/agentys/issues/205)
- Issue dependency audit : [#211](https://github.com/nathan/agentys/issues/211)
