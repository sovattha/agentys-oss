# Stripe Billing

## Prix des plans (Checkout)

`POST /api/billing/checkout` résout le price Stripe via `STRIPE_PRICE_<PLAN>_<PERIODE>`
(`app/api/billing.py:_select_price_id`). Les **quatre** variables sont requises pour
que le checkout fonctionne dans les deux périodes :

| Variable | Plan | Période |
| --- | --- | --- |
| `STRIPE_PRICE_STARTER_MONTHLY` | Starter | Mensuel |
| `STRIPE_PRICE_STARTER_YEARLY` | Starter | **Annuel** |
| `STRIPE_PRICE_PROFESSIONAL_MONTHLY` | Professional | Mensuel |
| `STRIPE_PRICE_PROFESSIONAL_YEARLY` | Professional | **Annuel** |

⚠️ **Piège « le paiement annuel ne fonctionne pas »** : si une variable `*_YEARLY`
manque, `_select_price_id` lève `BillingConfigError`, le checkout renvoie
`503 BILLING_NOT_CONFIGURED`, et le front affiche « Impossible d'ouvrir le paiement
Stripe » — **uniquement** pour la période annuelle (le mensuel marche toujours car
sa variable est présente). Le détail (`STRIPE_PRICE_…_YEARLY is missing`) est
journalisé côté serveur (`[BILLING] Checkout not configured …`) et visible dans la
console du navigateur.

Alias de compatibilité (implémentation Pro-only d'origine) : `STRIPE_PRICE_PRO_MONTHLY`
et `STRIPE_PRICE_PRO_YEARLY` sont acceptés en repli **uniquement** pour `professional`.
Le plan `starter` n'a aucun alias et exige ses propres variables.

## Variables non secrètes (usage LLM)

Ces variables décrivent le contrat de facturation à l'usage. Elles peuvent être documentées dans `.env.example`; elles ne remplacent pas `STRIPE_SECRET_KEY`, qui reste un secret à stocker uniquement dans l'environnement de déploiement.

| Variable | Usage |
| --- | --- |
| `STRIPE_LLM_OVERAGE_PRICE_ID` | Price Stripe metered ajouté à la Checkout Session pour facturer les crédits LLM au-delà du forfait. |
| `STRIPE_LLM_OVERAGE_METER_EVENT_NAME` | Nom de l'event Stripe Meter envoyé quand l'usage LLM dépasse les crédits inclus. |

Le prix metered est attaché à l'abonnement au checkout. Ensuite, les logs d'usage LLM calculent le dépassement mensuel et publient des Meter Events avec `STRIPE_LLM_OVERAGE_METER_EVENT_NAME`.
