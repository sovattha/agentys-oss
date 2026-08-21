# Benchmark spaCy NER — fr_core_news_md
**Model** : `fr_core_news_md`
**Date** : 2026-04-12
**Dataset** : `tmp/ner_benchmark/emails.csv` (106 emails annotés)

---
## Métriques globales
| Métrique | Valeur |
|----------|-------:|
| Precision | 13.9% |
| Recall | 21.3% |
| F1 | 16.8% |
| TP / FP / FN | 46 / 286 / 170 |

## Par type d'entité
| Type | Precision | Recall | F1 | TP | FP | FN |
|------|----------:|-------:|---:|---:|---:|---:|
| PERSON | 20.8% | 36.8% | 26.6% | 21 | 80 | 36 |
| ORG | 14.2% | 12.2% | 13.1% | 15 | 91 | 108 |
| LOC | 8.0% | 27.8% | 12.4% | 10 | 115 | 26 |

## Par catégorie d'email
| Catégorie | Precision | Recall | F1 | TP | FP | FN |
|-----------|----------:|-------:|---:|---:|---:|---:|
| factures | 26.3% | 37.0% | 30.8% | 20 | 56 | 34 |
| internal | 0.0% | 0.0% | 0.0% | 0 | 92 | 73 |
| newsletter | 20.0% | 40.7% | 26.8% | 11 | 44 | 16 |
| rdv | 12.5% | 30.0% | 17.6% | 3 | 21 | 7 |
| spam_like | 17.9% | 23.3% | 20.3% | 7 | 32 | 23 |
| support | 10.9% | 22.7% | 14.7% | 5 | 41 | 17 |

## Confusions de type
Entités présentes dans la GT mais taggées sous un autre type par spaCy :

| GT type | spaCy type | Count |
|---------|-----------|------:|
| ORG | PERSON | 22 |
| ORG | LOC | 10 |
| PERSON | ORG | 1 |

## Échantillon d'erreurs (10 premières par type)
### False positives (spaCy tag, GT ne tag pas)
| Row | Type | Entité |
|-----|------|--------|
| 43 | LOC | https://dashboard.stripe.com/receipts/invoices/cacqaroxchvhy2n0xzfnrxhr |
| 43 | LOC | pbc #2732-5245 |
| 43 | LOC | https://stripe-images.s3.amazonaws.com/emails/invoices_invoice_illustration.png |
| 43 | ORG | pbc |
| 43 | LOC | anthropic |
| 43 | ORG | pbc receipt from anthropic |
| 905 | ORG | infomaniak <no-reply@infomaniak.com |
| 211 | ORG | utc+2 |
| 211 | LOC | rue de vermont 37 |
| 211 | LOC | romana |
| 211 | PERSON | line |
| 219 | LOC | bonjour |
| 121 | PERSON | min |
| 121 | PERSON | messieurs |
| 121 | PERSON | -) merci |

...et 271 autres.

### False negatives (GT tag, spaCy rate)
| Row | Type | Entité |
|-----|------|--------|
| 43 | ORG | anthropic, pbc |
| 117 | ORG | agentys |
| 905 | ORG | infomaniak |
| 211 | ORG | google agenda |
| 211 | LOC | europe |
| 211 | LOC | paris |
| 211 | ORG | la romana |
| 121 | ORG | domaine le z |
| 484 | ORG | google ai studio |
| 484 | ORG | gemini |
| 484 | PERSON | nathan |
| 946 | ORG | klarna |
| 898 | LOC | suisse |
| 898 | PERSON | nathan |
| 149 | ORG | vercel inc |

...et 155 autres.

## Décision gate
🔴 **spaCy insuffisant** — PERSON recall = 36.8% < 85%. Évaluer alternatives (fr_core_news_lg, flair/ner-french, XLM-R) ou review 100% des fixtures avant commit.
