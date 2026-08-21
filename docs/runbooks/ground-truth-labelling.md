# Ground-truth labelling — runbook

## Pourquoi

Toutes les métriques précédentes du Critic (eval 2026-04-30, sweep 2026-05-04, replay du gate) mesuraient *gate-vs-Critic agreement* — pas *gate-vs-vérité*. Le Critic a un FP rate documenté de 34 % sur drafts sains : agreement avec une décision elle-même biaisée à 34 % ne dit rien sur la qualité réelle. Sans set de drafts hand-labellés, on ne peut pas réparer le rubric — on peut seulement déplacer les biais.

Cette session débloque le rubric tuning : tu labellises 60 drafts réalistes (issus de `tests/fixtures/drafting_eval_runs/`), je compare les verdicts du Critic actuel avec tes labels, je propose des edits ciblés du rubric basés sur les patterns d'erreur.

## Comment labelliser (~2 h, peut être fait en plusieurs sessions)

```bash
python scripts/label_drafts_for_ground_truth.py
```

Pour chaque draft, tu vois :
- l'email entrant (avec sender + subject + body)
- le draft AI

Et tu réponds à UNE question : **« est-ce que tu enverrais ce draft TEL QUEL au destinataire ? »**

Touches :
- `g` = oui, je l'envoie sans modification
- `b` = non, ça nécessite une révision
- `n` = non + ajouter une note (1 ligne) sur ce qui cloche
- `s` = skip (revient plus tard)
- `<` = retour (re-labelliser le précédent)
- `q` = save & quit (re-run pour reprendre où tu en étais)

L'auto-save est par-case (atomic write). Tu peux quitter à n'importe quel moment, re-run pour reprendre. Re-run skippe automatiquement les cas déjà labellisés.

Sortie : `tasks/ground-truth-drafts-2026-05-04.json`.

## Conseils pour labelliser efficacement

1. **N'overthink pas.** Lis l'email + le draft. Si t'es prêt à cliquer "send" tel quel, c'est `g`. Sinon c'est `b`. Tu en es à ton 30ᵉ draft, pas une thèse.
2. **Ne pas comparer aux autres.** Chaque draft est jugé sur ses propres mérites, pas en relatif au précédent.
3. **Pas un draft "parfait" — un draft "envoyable".** Les drafts AI sont rarement parfaits. La barre est : "est-ce que ça fait le job sans m'embarrasser ?".
4. **Note quand quelque chose te frappe.** Si tu mets `b`, et que tu sais pourquoi en 1-2 mots, utilise `n` au lieu de `b`. Les notes guident le rubric tuning.
5. **`[À confirmer]` est OK ou pas ?** À toi de juger. Certains placeholders sont acceptables ("je vous reviens avec X"), d'autres sont des trous béants.

## Critères suggérés (pour t'aligner sur "ce qu'on cherche à enseigner au Critic")

Un draft envoyable :
- Répond à TOUS les points de l'email entrant (ou explicitement renvoie à plus tard)
- Pas d'invention factuelle (chiffres, dates, noms qui ne sont pas dans l'email)
- Ton compatible avec le sender (formel ↔ formel, casual ↔ casual)
- Pas de placeholders critiques laissés bruts (`[À confirmer]` sur le point central)
- Greeting + closing présents (sauf hyper-casual avec interlocuteur connu)
- Longueur proportionnée au sujet

Un draft pas envoyable :
- Élude la question principale
- Hallucinations factuelles (la cause #1 de bad drafts en prod)
- Tone-mismatch frappant
- Trop long pour le sujet (paraphrase + politesses creuses)
- Ouvre des questions au lieu d'apporter de la valeur

## Après le labelling

Quand tu auras labellisé ≥40 cas (voir le total quand tu hit `q`), je peux lancer la prochaine étape :

```bash
# (je le construirai après ton labelling — pas de pre-build pour éviter
# d'orienter les labels)
python scripts/analyze_critic_vs_ground_truth.py
```

Output attendu :
- Per-case : verdict humain vs verdict Critic actuel (Haiku) + breakdown des 7 dimensions
- Patterns de désaccord : "le Critic baisse `tone` à <50 quand X" → c'est ce que le rubric edit doit corriger
- Suggestion d'edit du rubric (`app/prompts/templates/critic_structured_system_prompt.txt`)
- Re-eval du rubric edité contre tes labels pour confirmer l'amélioration

## Si tu veux abandonner mid-session

Tape `q`. Tes labels sont déjà sauvegardés. Re-run plus tard pour reprendre. ≥40 cas suffit pour des inférences statistiques utiles ; 60 (le total) est mieux mais pas obligatoire.
