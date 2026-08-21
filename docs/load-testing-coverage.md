# Couverture des tests de charge

## Objectif

Les tests de charge ne doivent pas seulement répondre à "combien de drafts par
minute". Ils doivent aussi couvrir les angles morts produits : durée longue,
burst, providers email, LLM réel et parcours complet utilisateur.

## Suites ajoutées

Les suites utilisent `scripts/load-test-coverage-suite.sh`, qui appelle le
runner Railway existant avec des paramètres explicites.

| Suite | Ce qu'elle couvre | Commande |
|---|---|---|
| Soak mock | Stabilité 4h au dernier palier sain connu | `scripts/load-test-coverage-suite.sh soak-mock` |
| Burst mock | Pic simultané au lieu d'un trafic étalé | `scripts/load-test-coverage-suite.sh burst-mock` |
| Full-flow mock | List/detail provider + draft + sent-provider | `scripts/load-test-coverage-suite.sh full-flow-mock` |
| Provider live smoke | Quotas/latence provider réels à faible volume | `scripts/load-test-coverage-suite.sh provider-live-smoke --host <prod>` |
| LLM live smoke | Latence/coût/erreurs LLM réels à faible volume | `scripts/load-test-coverage-suite.sh llm-live-smoke --host <prod>` |

## Garde-fous live

Les modes live sont volontairement explicites :

- `--llm-mode live` ou `--provider-mode live` échoue sans
  `--allow-live-services`.
- Les runs live sont limités à `--max-live-users 25` par défaut.
- Monter au-dessus de cette limite demande
  `--allow-high-volume-live-services`.

Ce design évite de lancer par erreur un test coûteux ou agressif contre les
quotas Google/Microsoft/LLM.

## Interprétation

- `draft-users` mesure le chemin génération draft.
- `provider` mesure le chemin provider isolé.
- `full-flow` combine provider list/detail, génération draft, puis probe sent.
- `--traffic-shape burst` sert à tester les clics simultanés après une notif.
- `--soak-hours` sert à tester la stabilité longue, les fuites et la dérive de
  latence.

Les runs mock restent les seuls adaptés aux gros volumes. Les runs live doivent
rester petits et servent à calibrer les hypothèses de latence/backoff réels.
