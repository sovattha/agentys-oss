# ADR 0002 — Lifecycle de l'équipe Projets (pipeline 7 passes)

- **Statut** : Accepté
- **Date** : 2026-04-28
- **Auteur** : équipe ai_team (Nat + Claude)
- **Lié à** : ADR 0001 (forum in-process), `tasks/projects-team-plan.md`

## Contexte

Aujourd'hui, le `feature_board` (`ai_team/agents/pm/feature_board.py`) gère
le cycle `pending_forum → forum_approved → human_approved → shipped`, mais
le passage de `human_approved` à `shipped` est manuel : on crée une issue
GitHub, l'`intake` la triage, puis l'humain code à la main. Aucun pipeline
n'orchestre `dev-feature`/BMAD, aucune review adversariale du **plan** avant
impl, aucun ADR auto, aucune borne sur les itérations UI/test.

Le coût caché : décisions invisibles dans le code mergé, pas d'audit trail
des alternatives non considérées, pas de stop-loss budgétaire, et un
résultat livré qui peut diverger du visuel attendu sans détection
automatique.

## Décisions

### D1 — In-process (cohérent ADR 0001)

Pas d'A2A protocol, pas de service séparé. L'orchestrateur tourne dans le
même process que le PM bot Telegram. Cohérent avec l'ADR 0001 qui
choisissait l'in-process pour les forums.

**Pourquoi** : YAGNI tant qu'il n'y a pas de second service consommateur.
Une feature qui boucle sur Sonnet 30s dans un thread ne dérange pas un
polling Telegram. À reconsidérer si > 5 features actives en parallèle.

### D2 — SQLite tables dédiées (`feature_requests`, `feature_runs`)

Pas de réutilisation de `publication_drafts`. Tables nouvelles, schéma
idempotent au boot (pattern `pinterest/store.py`), même DB que le reste de
l'`ai_team` (`AGENTYS_DB_PATH`).

**Pourquoi** : `publication_drafts` est `(agent, channel, body)` — un body
unique à publier. Une feature est multi-pass, multi-itérations, avec lien
GitHub PR/issue. Forcer le mariage = colonnes nullables partout, sémantique
floue, indexes inadaptés. Nouvelle table = tests propres.

### D3 — Routing automatique avec override humain

L'orchestrateur Pass B classe `simple|complex|bmad-full|hotfix` via
heuristique + Haiku. Nat ou Alex peut override via `/route_feature <id>
<routing>` (à implémenter Phase 2).

**Pourquoi** : 90 % des features Agentys sont triables par règle simple
(LOC touchées, modules, migration DB, contrat API public). L'humain reste
en boucle pour les 10 % ambigus. Override = pas de blocage si le LLM se
trompe.

### D4 — Senior-dev plan critic = Sonnet par défaut, Opus si `complexity=high`

Le critic (Pass D, inspiré des prompts Audit Pass 1+2) tourne sur Sonnet.
Si Pass B a routé `complex|bmad-full`, on bascule en Opus pour l'analyse
adversariale.

**Pourquoi** : Sonnet trouve 90 % des findings P0/P1, Opus +5 % mais 5x
plus cher. Sur des features critiques (sécurité, multi-worker, OAuth), les
5 % manquants peuvent valoir 10 ans de dette technique — d'où le
basculement automatique. Cohérent avec la règle d'or "Haiku-first partout"
(`MEMORY.md:5`) sauf quand le complexe vaut le coût.

### D5 — UI iteration via Playwright MCP local (pas headless cloud)

Pass F utilise les outils `mcp__playwright__*` déjà câblés (cf.
`scripts/nightly-ux-inspection.sh`), screenshot capture canonique, LLM
judge Haiku qui compare au `success_criteria` du Pass A.

**Pourquoi** : Playwright MCP est déjà installé, déjà testé sur la pipeline
nocturne. Cloud headless = nouvelle infra, nouvelle auth, nouveaux secrets.
Coût marginal nul vs $30/mois si on prend BrowserStack ou équivalent.

### D6 — Notification de complétion → topic Telegram dédié `projects`

Quand une feature termine en `status='merged'`, on poste un résumé complet
(titre, routing, coût final vs cap, durée pipeline, runs Pass A→G avec
findings, liens spec/ADR/PR/issue) dans un topic Telegram dédié.

**Implémentation** : `ai_team/agents/projects/telegram_bridge.py` —
`notify_feature_merged()` (async) + `notify_feature_merged_sync()`
(wrapper pour l'orchestrateur sync). Pure function `build_merged_summary`
testable sans Telegram.

**Wiring** : ajouter `"projects": <thread_id>` au JSON de la variable d'env
`TELEGRAM_TOPICS` (cf. `/etc/agentys/ai-team.env` sur Hetzner). Si non
mappé, le message tombe sur General (legacy fallback de
`pm_telegram.send`, zéro régression).

**Pourquoi** : sans ce résumé, l'humain doit ouvrir GitHub + lire l'ADR +
faire `/project <id>` pour comprendre ce qui a été décidé. Avec, il a tout
en 30 secondes dans le topic qu'il monitore déjà. Cohérent avec le pattern
des autres agents (Pinterest, Cinéaste, Bookkeeper digest).

### D7 — Cost cap par feature = $10 (Nat 2026-04-28)

Variable d'env `PROJECTS_FEATURE_COST_CAP_CENTS=1000`. À l'atteinte du cap
(via `projects_store.add_cost()`), la feature passe en `status='abandoned'`
et un message Telegram alerte sur le topic `alerts`.

**Pourquoi** : 50 features/mois × $10 = $500/mois worst-case, gérable. Une
feature qui dépasse = signal de mauvais routing (devrait être complex donc
coupée plus tôt) ou de boucle infinie (bug à fixer). Le cap force la
discipline. Validé par Nat 2026-04-28.

## Conséquences

### Positives
- Audit trail complet par feature (table `feature_runs` immutable)
- Décisions tracées (ADR auto par feature en Phase 3, dans `docs/adr/`)
- Stop-loss budgétaire = pas de spirale invisible
- Codex auditable : la PR finale arrive avec `tasks/projects-reports/<feat>-final.md`
  contenant file:line, blast_radius, verification_plan

### Négatives
- 2 nouvelles tables = 2 nouveaux endroits où corrompre des données
- L'humain doit comprendre la sémantique distincte `proposed_features` vs
  `feature_requests`. Mitigé par les commandes Telegram qui hide la
  complexité (`/newfeatures` parle de l'un, `/projects` parle de l'autre).
- Phase 1 ne fait que « préparer le terrain » : rien ne bouge tant que
  Phase 2 n'est pas livrée. Risque d'avoir des `queued` orphelins si on
  s'arrête là. Mitigé par la sentinel `sentinel_projects` (Phase 5) qui
  alerte si `status` inchangé > 7 jours.

## Alternatives considérées et rejetées

### A1 — Une seule table `feature_pipeline` qui remplace `proposed_features`
**Rejeté** : casserait `feature_board` existant + tests + `/features`
`/feature` `/approve_feature` `/reject_feature` Telegram commands. ROI
négatif, blast radius énorme. Mieux : tables séparées avec lien
`feature_board_id`.

### A2 — Faire tourner l'orchestrateur sur Hetzner serverless (séparé du PM)
**Rejeté** : YAGNI. Le PM bot a la connexion DB, les credentials Anthropic,
le contexte env. Ajouter un 2ᵉ service = configuration parallèle, sync
deploy, coût opérationnel.

### A3 — Persister les artefacts (specs, ADRs, rapports) en DB plutôt qu'en
fichiers
**Rejeté** : git track = audit naturel + diff visible + reviewable comme
n'importe quel doc. DB = invisible aux greps habituels, pas de PR-review
pour un changement de spec. Les fichiers gagnent.

### A4 — Démarrer direct par BMAD pour TOUTES les features (pas de track simple)
**Rejeté** : 80 % des features sont des polish UI ou bug fixes complexes
qui ne méritent pas un PRD complet. La cérémonie BMAD est fantastique pour
le complexe, écrasante pour le simple. Le routing Pass B fait ce tri.

## À reconsidérer

- D1 (in-process) si > 5 features actives en parallèle simultanément
- D6 (cap $10) après 30 jours d'usage : ajuster vers $5 si la moyenne
  réelle est < $3, vers $20 si on coupe trop de features valides
- D5 (Playwright MCP local) si des features mobiles pures arrivent — Expo
  ne s'autotest pas via Playwright web

## Liens

- Plan : `tasks/projects-team-plan.md`
- ADR 0001 : `docs/adr/0001-forum-in-process-vs-a2a.md`
- Code Phase 1 : `ai_team/agents/projects/store.py`,
  `ai_team/agents/pm/feature_board.py:human_approve`
- Tests : `tests/ai_team/test_projects_store.py`,
  `tests/ai_team/test_feature_board_pipeline.py`
