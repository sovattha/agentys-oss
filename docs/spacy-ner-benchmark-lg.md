# Benchmark spaCy NER — fr_core_news_md
**Model** : `fr_core_news_lg`
**Date** : 2026-04-12
**Dataset** : `tmp/ner_benchmark/emails.csv` (106 emails annotés)

---
## Métriques globales
| Métrique | Valeur |
|----------|-------:|
| Precision | 24.7% |
| Recall | 29.6% |
| F1 | 26.9% |
| TP / FP / FN | 64 / 195 / 152 |

## Par type d'entité
| Type | Precision | Recall | F1 | TP | FP | FN |
|------|----------:|-------:|---:|---:|---:|---:|
| PERSON | 28.0% | 24.6% | 26.2% | 14 | 36 | 43 |
| ORG | 37.3% | 30.9% | 33.8% | 38 | 64 | 85 |
| LOC | 11.2% | 33.3% | 16.8% | 12 | 95 | 24 |

## Par catégorie d'email
| Catégorie | Precision | Recall | F1 | TP | FP | FN |
|-----------|----------:|-------:|---:|---:|---:|---:|
| factures | 34.9% | 40.7% | 37.6% | 22 | 41 | 32 |
| internal | 31.0% | 24.7% | 27.5% | 18 | 40 | 55 |
| newsletter | 20.0% | 29.6% | 23.9% | 8 | 32 | 19 |
| rdv | 14.8% | 40.0% | 21.6% | 4 | 23 | 6 |
| spam_like | 21.9% | 23.3% | 22.6% | 7 | 25 | 23 |
| support | 12.8% | 22.7% | 16.4% | 5 | 34 | 17 |

## Confusions de type
Entités présentes dans la GT mais taggées sous un autre type par spaCy :

| GT type | spaCy type | Count |
|---------|-----------|------:|
| ORG | LOC | 10 |
| ORG | PERSON | 4 |
| PERSON | LOC | 2 |
| PERSON | ORG | 2 |

## Échantillon d'erreurs (10 premières par type)
### False positives (spaCy tag, GT ne tag pas)
| Row | Type | Entité |
|-----|------|--------|
| 43 | LOC | pbc #2732-5245-4320 |
| 43 | LOC | anthropic |
| 43 | LOC | pbc |
| 905 | LOC | nathan |
| 905 | LOC | 00:37 |
| 211 | LOC | nathan sok |
| 211 | PERSON | nathan sok nathanroy@gmail.com |
| 211 | LOC | suisse https://www.google.com/maps/search/la+romana,+rue+de+vermont+37,+1202+gen%c3%a8ve,+suisse?hl=fr organisateur |
| 211 | LOC | utc+2 |
| 211 | LOC | rue de vermont 37 |
| 219 | PERSON | redcare-apotheke.ch |
| 219 | PERSON | redcare apotheke |
| 121 | LOC | rejoignez |
| 121 | PERSON | min |
| 121 | LOC | domaine le z |

...et 180 autres.

### False negatives (GT tag, spaCy rate)
| Row | Type | Entité |
|-----|------|--------|
| 43 | ORG | anthropic, pbc |
| 117 | ORG | agentys |
| 905 | PERSON | nathan |
| 211 | LOC | suisse |
| 211 | ORG | google agenda |
| 211 | PERSON | nathan sok |
| 211 | LOC | europe |
| 211 | LOC | paris |
| 211 | ORG | la romana |
| 219 | ORG | redcare apotheke |
| 121 | ORG | domaine le z |
| 484 | ORG | google ai studio |
| 484 | PERSON | nathan |
| 484 | ORG | gemini |
| 946 | ORG | klarna |

...et 137 autres.

## Décision gate
🔴 **spaCy insuffisant** — PERSON recall = 24.6% < 85%. Évaluer alternatives (fr_core_news_lg, flair/ner-french, XLM-R) ou review 100% des fixtures avant commit.
