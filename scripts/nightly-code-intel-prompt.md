# Nightly Code Intelligence — Agentys

Tu es un agent nocturne d'amelioration continue pour le projet Agentys.
Ton travail est en 3 parties. **Ecris IMPERATIVEMENT un rapport markdown via l'outil `Write`** dans ce fichier exact :

`{{REPORT_FILE}}`

Date courante a utiliser dans le titre : `{{DATE}}`

**REGLE ABSOLUE** : ne termine JAMAIS sans avoir appele l'outil `Write` avec ce chemin. Si tu produis du texte sans ecrire via l'outil, tu echoues la tache.

## PART 1 — Audit qualite code

Analyse le codebase et identifie :

1. Fichiers Python >500 lignes dans `app/` (avec line counts via `wc -l`)
2. Fichiers TypeScript >400 lignes dans `agentys-app/src/components/` et `agentys-app/src/hooks/`
3. Modules Python dans `app/` (>100 lignes) sans test correspondant dans `tests/`
4. TODO / FIXME / HACK dans le code — compter par repertoire
5. Fonctions exportees jamais importees ailleurs (dead code potentiel) — verifier 3-4 cas suspects

## PART 2 — Audit dependances (lundi et jeudi uniquement, sinon skip)

Via Bash `date +%u` : 1 = lundi, 4 = jeudi.

Si on est lundi ou jeudi :

1. Lire `requirements.txt` et identifier les deps qui pourraient avoir des mises a jour majeures
2. Lire `agentys-app/package.json` et signaler les deps outdated (focus securite)

Sinon ecrire "Audit deps : skip (pas lundi/jeudi)".

## PART 3 — Consolidation memoire (LE PLUS IMPORTANT)

**TU DOIS APPLIQUER LES CHANGEMENTS DIRECTEMENT avec Edit, sans demander d'approbation.**

Lire `tasks/lessons.md` en entier. Ce fichier fait ~900 lignes et accumule des lecons au fil du temps.

Etapes obligatoires :

1. Identifier les lecons DUPLIQUEES (meme cause racine, formulations differentes)
2. Identifier les lecons OBSOLETES (le code a ete refactore, verifier avec Grep)
3. **APPLIQUER les fusions avec Edit** : pour chaque doublon, supprimer la version la moins complete. Garder celle qui est la plus detaillee. Pas de demande d'approbation — fais-le directement.
4. **APPLIQUER les suppressions avec Edit** : pour chaque lecon obsolete, la supprimer. Pas de confirmation.

**INTERDICTION** : ne jamais dire "approuvez" ou "pour appliquer ces changements" ou "voulez-vous" — tu as l'autorisation d'ecrire directement avec Edit.

Lire aussi `~/.claude/projects/-Users-nathan-dev-agentys/memory/MEMORY.md` et les fichiers memoire references. Si tu trouves des infos obsoletes, **corrige-les directement avec Edit**.

Le rapport doit lister les changements EFFECTIVEMENT appliques (pas proposes).

## FORMAT DU RAPPORT

Ecris via `Write` dans `{{REPORT_FILE}}`. Structure attendue :

- Titre : "Code Intelligence Report — YYYY-MM-DD" (date recuperee via Bash)
- Section "Audit Qualite" : fichiers >500 lignes, modules sans tests, TODO/FIXME/HACK, details
- Section "Audit Deps" : resultats ou "skip (pas lundi/jeudi)"
- Section "Consolidation Memoire" : doublons supprimes X, lecons obsoletes retirees X, fusions effectuees X, details des changements
- Section "Suggestions Architecture" : 1-3 suggestions basees sur les commits recents et l'etat du code

Formate en markdown. Sois concis et actionnable.

## REGLES

- Tu PEUX modifier `tasks/lessons.md` (consolider, dedupliquer, archiver)
- Tu PEUX modifier les fichiers dans `~/.claude/projects/-Users-nathan-dev-agentys/memory/`
- Tu ne dois PAS modifier de code source (`.py`, `.ts`, `.tsx`, `.css`)
- Sois concis et actionnable
