# ADR 0001 — Forum inter-agents : in-process LLM plutôt qu'A2A

- **Statut** : accepté
- **Date** : 2026-04-28
- **Auteur** : Nat (avec Claude pour l'écriture)
- **Issue liée** : [#386](https://github.com/nathan/agentys/issues/386)

## Contexte

L'issue #386 propose un mécanisme de **forum inter-agents** : un agent peut
convoquer ses pairs (broadcast), poser une question, recevoir des votes, puis
décider d'escalader ou non selon le consensus. Cas concrets :

- Alpha Idiot trouve un comportement bizarre du Support → forum → si pairs OK, escalade au PM
- Journaliste a un sujet candidat → forum → si pairs LENIENT, lance le digest
- Auditeur nocturne identifie un bug → forum → si pairs APPROVE, crée l'issue GitHub

## Options envisagées

### Option A — Protocole A2A (Agent2Agent)

Standard ouvert publié par Google en mars 2025, désormais sous Linux Foundation
([github.com/a2aproject/A2A](https://github.com/a2aproject/A2A), Apache 2.0,
23k stars). Chaque agent expose un serveur HTTP avec :

- un `AgentCard` à `/.well-known/agent-card.json` (registry de capabilities)
- un endpoint JSON-RPC qui accepte des `Message` et retourne des `Task` avec artifacts

**Pour** :
- Standard ouvert future-proof, écosystème croissant
- Permet d'inviter à terme des agents externes (Codex, partenaires, agents tiers)
- Vraie identité agent auditable
- Support natif du streaming, push notifications, multi-tenant

**Contre** :
- Un serveur HTTP **permanent** par peer (uvicorn + Starlette + a2a-sdk)
- Mémoire allouée 24/7 alors que les peers sont sollicités ~3 fois par jour
- 5 deps tirées : `a2a-sdk` 1.0.2, `protobuf<7`, `starlette`, `uvicorn`, `sse-starlette`
- Bug subtil découvert au POC : `a2a-sdk` 1.0.2 lit `field.label` retiré dans protobuf 7.x → pinning obligatoire
- Latence réseau ajoutée (5-10ms par appel intra-Docker)
- Complexité de déploiement : ajouter N services à `docker-compose.yml`
- Surface d'attaque : N ports HTTP à protéger

### Option B — In-process LLM (à la `daily_standup`)

Le pattern déjà éprouvé du daily standup : **un seul process** qui aggrège
toutes les perspectives. Pour le forum, ça se traduit par :

- Un YAML qui définit des "personas" (rôle Senior Dev, QA, Espion, Muse, Écrivain…)
- Quand le forum s'ouvre, on appelle Haiku **en parallèle** pour chaque persona avec un prompt « tu es agent X, voici la question, vote `approve`/`reject`/`abstain` avec une rationale »
- On parse les JSON, on aggrège dans le tally existant, on persiste dans `ai_team_forums`

**Pour** :
- Zéro infra supplémentaire (pas de container, pas de port HTTP, pas de service)
- Zéro deps supplémentaires (`anthropic` est déjà dans `requirements.pm.txt`)
- Latence intra-process (< 500ms total avec asyncio.gather pour 3 votants)
- Coût LLM identique : 3 votes Haiku ≈ $0.001/forum
- Code simple : ~30 lignes pour `LlmPeerSender`
- Personas évolutifs : éditer le YAML, redémarrer, fini
- Cohérent avec l'archi existante (PM = un seul process qui orchestre tout)

**Contre** :
- Pas d'interop externe → un partenaire qui voudrait participer devrait passer par un endpoint custom
- Pas d'identité agent auditable au niveau réseau (mais l'audit DB existe)
- Standard maison, pas conforme A2A

### Option C — Hybride (les deux)

Garder `A2APeerSender` ET ajouter `LlmPeerSender`. Le port `PeerSender`
Protocol existe déjà — on peut switcher au runtime selon la config.

**Contre** : entretenir 2 chemins pour un usage qui n'a pas besoin des deux. Dette
technique pour zéro bénéfice immédiat.

## Décision

**Option B retenue.**

L'argument qui tranche : **YAGNI**. On n'a pas de besoin réel d'interopérabilité
externe à court ou moyen terme. Le coût opérationnel (5 deps, N conteneurs, deux
patterns à maintenir) dépasse le bénéfice théorique (futur-proof).

Le pattern in-process est de plus **cohérent avec l'existant** : `daily_standup`,
`bookkeeper`, `sentinel_*` font tous leur travail dans un seul process. Pas de
raison de casser cette homogénéité pour le forum.

## Conséquences

### Code retiré
- `A2APeerSender` et `extract_vote_from_artifacts` dans `ai_team/lib/forum.py`
- `ai_team/agents/peers/senior_dev_a2a.py` (serveur Starlette/uvicorn)
- POC `scripts/poc/a2a/` (rapatrié comme historique dans cet ADR)
- Deps `a2a-sdk`, `protobuf<7`, `sse-starlette`, `starlette`, `uvicorn` dans `requirements.{pm,worker}.txt`

### Code conservé
- Tout le **domaine pur** de `forum.py` : `Vote`, `Outcome`, `ForumRecord`, `tally`, `should_escalate`, `EscalationPolicy`
- Le port `PeerSender` Protocol (au cas où on rebrancherait A2A plus tard pour vraie raison)
- L'adapter `SqliteForumStore` (audit DB)
- L'orchestrateur `open_forum`, le helper `gate_issue_creation`
- Le sentinel `sentinel_forum_quality` (cron L3 daily 12:00 UTC)
- La commande Telegram `/forum_log` et le formatter `format_forum_log`
- Les tests purs (33 sur 46 tests existants restent valides)

### Code ajouté
- `LlmPeerSender` dans `ai_team/lib/forum_llm_peer.py` (~80 lignes) — implémente le port `PeerSender` via appels Haiku in-process
- `ai_team/config/forum_peers.yaml` — personas (Senior Dev, QA, Espion, Muse, Écrivain) avec rôle + heuristique en prompt
- Tests : parser de réponse Claude, fallback vote si JSON invalide, integration test avec mock Claude

### Comportement utilisateur
- **Aucun changement visible** : le forum continue de fonctionner exactement pareil pour Nat et Alex.
- Le feature flag `JOURNALISTE_FORUM_ENABLED` reste valide, opt-in.
- Le `/forum_log` Telegram reste identique.
- Les invitees passent d'URLs HTTP (`http://senior-dev:9002`) à des **noms de personas** (`senior-dev`, `qa`, `espion`).

### Réversibilité

Si demain on a un besoin réel d'interop externe (un partenaire veut participer
au forum, ou Codex veut voter), on peut **réajouter `A2APeerSender`** sans
changer une ligne du domaine. Le port `PeerSender` Protocol est une
interface stable, c'est exactement ce qu'il garantit.

L'historique du POC A2A reste accessible :

- code : commit pre-rebase `1e87b9cd` (recoverable via reflog jusqu'à 90j)
- doc : cet ADR + [`ai_team/lib/forum.README.md`](../../ai_team/lib/forum.README.md)
- spec : [a2a-protocol.org](https://a2a-protocol.org/latest/specification/)

## Leçon retenue

> Quand on évalue un protocole standard "ouvert et future-proof", la question à
> poser n'est pas "est-ce que ce serait sympa d'avoir ça ?" mais "**quel
> besoin concret aujourd'hui le justifie ?**". S'il n'y en a pas, YAGNI prime
> sur le futur-proof.
>
> Le pattern par défaut sur Agentys est : **un seul process orchestre tout, on
> appelle des fonctions**. Sortir de ce pattern (ajouter un microservice, un
> protocole réseau, une lib externe) doit être justifié par une vraie
> contrainte qu'on ne peut pas résoudre autrement.
