# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Test case generators for email complexity scoring.

Each function returns a list of tuples:
    (body, subject, thread_depth, has_instructions, has_attachments,
     expected_tier, score_min, score_max, description)

expected_tier: "COMPLEX" (score >= 50) or "STANDARD" (30 <= score < 50) or "SIMPLE" (< 30)

Scoring reference:
  score = body*0.20 + q*0.20 + tech*0.15 + thread*0.10 + topic*0.10
          + multi*0.10 + instr*0.10 + attach*0.05

  Component scores:
    body: <200→0, 200-1000→linear(0-50), 1000-2000→linear(50-100), 2000+→100
    q: 0→0, 1→35, 2→70, 3+→100
    tech: 0→0, 1→40, 2-3→70, 4+→100
    thread: 0→0, 1→20, 2-3→40, 4→60, 5+→100
    topic: 1→0, 2→50, 3+→100
    multi: (lists OR 3+q) → 100, else 0
    instr: instructions → 100, else 0
    attach: attachments → 100, else 0

  Weighted maxima (points contributed):
    body: 20, q: 20, tech: 15, thread: 10, topic: 10, multi: 10, instr: 10, attach: 5
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pad(text, target_chars):
    """Pad text with neutral filler to reach target character count."""
    if len(text) >= target_chars:
        return text[:target_chars]
    filler = " Merci de votre patience et compréhension dans ce dossier."
    while len(text) < target_chars:
        text += filler
    return text[:target_chars]


def _repeat(unit, n):
    """Repeat a short string n times (useful for precise char counts)."""
    return (unit * n)


def _body_score(length):
    """Compute body_score for a given character length."""
    if length < 200:
        return 0
    elif length < 1000:
        return int((length - 200) / 800 * 50)
    elif length < 2000:
        return int(50 + (length - 1000) / 1000 * 50)
    else:
        return 100


def _tier(score, has_instructions=False):
    """Return tier string for a score."""
    if score < 30 and not has_instructions:
        return "SIMPLE"
    elif score < 50:
        return "STANDARD"
    else:
        return "COMPLEX"


# ============================================================================
# 1. COMPLEX — Multi-question emails (100 cases)
# ============================================================================

def _gen_complex_multi_questions():
    """100 cases: 3+ questions, often with lists. Score 50+. Mix FR/EN.

    To hit COMPLEX (50+) with 3+ questions:
      q=100*0.20=20, multi=100*0.10=10 → 30 from questions.
      Need 20+ more from body/tech/thread/topic/instr/attach.
      Strategy: use body >= 1000 chars (body_score=50*0.20=10) + tech or topics.
    """
    cases = []

    # --- FR multi-question business emails with padded bodies ---

    cases.append((
        _pad(
            "Bonjour,\n\nJ'ai plusieurs questions concernant le projet.\n\n"
            "1. Quand est-ce que la livraison est prévue?\n"
            "2. Est-ce que le budget a été validé par la direction?\n"
            "3. Pouvez-vous confirmer la liste des participants?\n\n"
            "Par ailleurs, j'aimerais savoir si le planning de la semaine prochaine est finalisé.\n\n"
            "Merci de me revenir rapidement sur ces points. Le comité attend ces informations "
            "pour prendre une décision éclairée.", 1200
        ),
        "Questions projet Alpha", 2, False, False,
        "COMPLEX", 50, 75, "FR 3q + list + 2 topics + thread + body 1200"
    ))

    cases.append((
        _pad(
            "Bonjour équipe,\n\nSuite à notre réunion de ce matin, j'ai besoin de clarifications:\n\n"
            "- Est-ce que le contrat a été signé?\n"
            "- Quand sera disponible la version staging?\n"
            "- Combien de jours de retard sur le sprint?\n"
            "- Pouvez-vous partager le lien Jira du backlog?\n\n"
            "Merci d'avance pour vos retours rapides. Le client attend une réponse avant vendredi. "
            "Nous devons absolument clarifier ces points pour éviter tout malentendu.", 1200
        ),
        "Clarifications post-réunion", 1, False, False,
        "COMPLEX", 52, 82, "FR 4q + list + tech (staging, sprint, Jira) + body 1200"
    ))

    cases.append((
        _pad(
            "Salut,\n\nPlusieurs points à valider pour la mise en production:\n\n"
            "1. Est-ce que les tests de régression sont passés?\n"
            "2. Le déploiement est prévu pour quelle date?\n"
            "3. As-tu validé les accès en production?\n"
            "4. Comment on gère le rollback en cas de problème?\n\n"
            "Concernant le monitoring, est-ce que les alertes sont configurées?\n\n"
            "Je reste disponible pour en discuter. C'est critique pour la release de vendredi.", 1200
        ),
        "Mise en production v2.1", 3, False, False,
        "COMPLEX", 55, 85, "FR 5q + tech (deploy, rollback, production) + topics + thread"
    ))

    cases.append((
        _pad(
            "Bonjour Marc,\n\nJ'ai reçu le devis mais j'ai quelques interrogations:\n\n"
            "1. Le tarif inclut-il la maintenance annuelle?\n"
            "2. Quelles sont les conditions de résiliation?\n"
            "3. Est-ce que le SLA de 99.9% est garanti contractuellement?\n\n"
            "Par ailleurs, pouvez-vous préciser les modalités de facturation?\n\n"
            "D'autre part, est-ce que vous proposez un tarif dégressif pour un engagement de 24 mois?", 1200
        ),
        "Questions devis #2024-0891", 0, False, False,
        "COMPLEX", 50, 80, "FR 5q + legal tech (SLA, tarif, résiliation, contrat) + topics"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nSuite à l'incident de production de ce matin:\n\n"
            "- Quelle est la cause racine du bug?\n"
            "- Combien d'utilisateurs ont été impactés?\n"
            "- Est-ce que le hotfix a été déployé?\n\n"
            "Le client demande un rapport d'incident avant 17h. "
            "Pouvez-vous me fournir les logs du stack trace?\n\n"
            "Merci de traiter en priorité. La situation est critique et le SLA est menacé.", 1200
        ),
        "Incident production - URGENT", 4, False, False,
        "COMPLEX", 58, 88, "FR 4q + tech (bug, deploy, stack trace, production, SLA) + topic + thread 4"
    ))

    cases.append((
        _pad(
            "Bonjour Sophie,\n\nJe prépare la revue trimestrielle et j'ai besoin de données:\n\n"
            "1. Quel est le KPI de satisfaction client ce trimestre?\n"
            "2. Combien de tickets support ont été résolus?\n"
            "3. Est-ce que le ROI du projet est positif?\n\n"
            "Également, peux-tu me fournir le taux de churn et le NPS?\n\n"
            "Le comité de direction se réunit jeudi, j'ai besoin de ces chiffres avant mercredi. "
            "Prépare un dashboard si possible.", 1200
        ),
        "Données revue Q1 2026", 1, False, False,
        "COMPLEX", 50, 80, "FR 4q + business tech (KPI, ROI) + topic + body 1200"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nConcernant la migration de la base de données:\n\n"
            "1. Est-ce que le schema a été validé par le DBA?\n"
            "2. Quand est prévue la migration en staging?\n"
            "3. Combien de temps d'indisponibilité est estimé?\n"
            "4. Est-ce que les backups sont en place?\n\n"
            "Par ailleurs, comment gère-t-on la compatibilité avec l'API v1?\n\n"
            "L'équipe front attend la nouvelle structure pour adapter les endpoints. "
            "C'est bloquant pour le sprint en cours.", 1300
        ),
        "Migration DB - Planning", 2, False, False,
        "COMPLEX", 58, 90, "FR 5q + heavy tech (migration, database, schema, staging, API, endpoint, sprint)"
    ))

    cases.append((
        _pad(
            "Salut l'équipe,\n\nPour le sprint planning de lundi:\n\n"
            "- Est-ce que le backlog est priorisé?\n"
            "- Combien de story points on vise?\n"
            "- Qui prend le lead sur le feature flag?\n\n"
            "D'autre part, est-ce qu'on a les maquettes pour le nouveau dashboard?\n\n"
            "Le product owner veut aussi savoir si on peut intégrer le ticket dans ce sprint. "
            "Confirmez vos disponibilités pour le planning de 14h.", 1200
        ),
        "Sprint 14 - Préparation", 1, False, False,
        "COMPLEX", 52, 80, "FR 4q + agile tech (sprint, Jira) + topics"
    ))

    cases.append((
        _pad(
            "Bonjour Pierre,\n\nJ'ai examiné le contrat d'avenant et j'ai des questions:\n\n"
            "1. La clause de non-concurrence s'applique-t-elle aux sous-traitants?\n"
            "2. Quelle est la durée du préavis en cas de résiliation?\n"
            "3. Le renouvellement est-il automatique?\n\n"
            "Concernant la facturation, est-ce qu'on passe en paiement mensuel?\n\n"
            "Merci de me confirmer avant la signature prévue vendredi. "
            "Le juridique a besoin d'une réponse claire sur chaque point.", 1200
        ),
        "Avenant contrat - Questions", 0, False, False,
        "COMPLEX", 50, 80, "FR 4q + legal tech (contrat, avenant, résiliation, facturation)"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nNous avons détecté un problème de conformité RGPD:\n\n"
            "1. Est-ce que les données personnelles sont chiffrées au repos?\n"
            "2. Le DPO a-t-il été consulté?\n"
            "3. Quand la DPIA a-t-elle été mise à jour pour la dernière fois?\n\n"
            "Par ailleurs, est-ce que nos sous-traitants ont signé les clauses contractuelles?\n\n"
            "Également, comment gère-t-on le droit à l'effacement pour les données archivées?\n\n"
            "C'est urgent car l'audit CNIL est prévu le mois prochain.", 1300
        ),
        "Conformité RGPD - Audit imminent", 3, False, False,
        "COMPLEX", 60, 92, "FR 5q + GDPR tech (RGPD, DPIA, DPO, contrat) + 3 topics + thread"
    ))

    # --- EN multi-question emails ---

    cases.append((
        _pad(
            "Hi team,\n\nI have several questions about the upcoming release:\n\n"
            "1. When is the code freeze?\n"
            "2. Have all pull requests been reviewed?\n"
            "3. Is the staging environment ready for QA?\n\n"
            "Additionally, can we schedule a go/no-go meeting for Thursday?\n\n"
            "The client expects the release by end of month. We need to be aligned on timeline.", 1200
        ),
        "Release v3.2 - Questions", 2, False, False,
        "COMPLEX", 52, 82, "EN 4q + tech (pull request, staging) + topic + thread"
    ))

    cases.append((
        _pad(
            "Hello Sarah,\n\nRegarding the API migration:\n\n"
            "- What endpoints are affected by the breaking changes?\n"
            "- How do we handle backward compatibility?\n"
            "- When will the new API documentation be ready?\n"
            "- Can we set up a migration guide for external consumers?\n\n"
            "Also, do we need to update the SDK packages?\n\n"
            "This is blocking the mobile team's work. Please prioritize this.", 1200
        ),
        "API migration - Breaking changes", 1, False, False,
        "COMPLEX", 55, 88, "EN 5q + tech (API, endpoint, SDK, migration) + topic"
    ))

    cases.append((
        _pad(
            "Hi,\n\nI've been reviewing the security audit report and need clarification:\n\n"
            "1. How many critical vulnerabilities were found?\n"
            "2. Is the SQL injection on the search endpoint fixed?\n"
            "3. When was the last penetration test?\n\n"
            "Regarding GDPR compliance, are we storing any PII in the logs?\n\n"
            "The compliance team needs answers by Friday. This is a blocker for the certification.", 1200
        ),
        "Security audit follow-up", 3, False, False,
        "COMPLEX", 55, 88, "EN 4q + tech (SQL, endpoint, GDPR) + topic + thread"
    ))

    cases.append((
        _pad(
            "Hello,\n\nFor the Docker deployment setup:\n\n"
            "- Which base image should we use for the production containers?\n"
            "- How do we handle secrets management?\n"
            "- Is the CI/CD pipeline configured for auto-deploy?\n"
            "- Can we use Terraform for infrastructure provisioning?\n\n"
            "What's the estimated cost on AWS for this setup?\n\n"
            "We need the dev environment ready by next Monday. Budget approval is pending.", 1200
        ),
        "Docker deployment - Setup questions", 0, False, False,
        "COMPLEX", 55, 90, "EN 5q + heavy tech (Docker, CI/CD, Terraform, AWS, production)"
    ))

    cases.append((
        _pad(
            "Hi team,\n\nBefore we merge the feature branch:\n\n"
            "1. Did you run the full regression test suite?\n"
            "2. Are there any merge conflicts with main?\n"
            "3. What's the test coverage percentage?\n\n"
            "Also, can you add the missing unit tests for the new endpoints?\n\n"
            "The PR has been open for 5 days now, let's close it out. QA is waiting.", 1200
        ),
        "Feature branch merge - Checklist", 2, False, False,
        "COMPLEX", 52, 85, "EN 4q + tech (merge, branch, endpoint) + topic + thread"
    ))

    # --- Mixed FR/EN multi-question ---

    cases.append((
        _pad(
            "Bonjour,\n\nConcernant le déploiement sur AWS:\n\n"
            "1. Is the Terraform config ready for production?\n"
            "2. Est-ce que le load balancer est configuré?\n"
            "3. How do we handle the database migration?\n\n"
            "Par ailleurs, can you check the Docker images are up to date?\n\n"
            "On doit livrer avant vendredi. L'infrastructure doit être prête.", 1200
        ),
        "Deploy AWS - Questions mixtes", 1, False, False,
        "COMPLEX", 55, 90, "Mixed FR/EN 4q + heavy tech (AWS, Terraform, Docker, migration, database, production)"
    ))

    cases.append((
        _pad(
            "Hi,\n\nSuite au bug report #4521:\n\n"
            "- Can you reproduce the crash on staging?\n"
            "- Est-ce que le stack trace pointe vers le module auth?\n"
            "- How long has this been in production?\n\n"
            "Le client est très mécontent, pouvez-vous traiter en priorité?\n\n"
            "I need an update before the standup tomorrow. This is P0.", 1200
        ),
        "Bug #4521 - Investigation", 3, False, False,
        "COMPLEX", 58, 90, "Mixed 4q + tech (bug, staging, stack trace, production) + topic + thread"
    ))

    # --- Generate more parametric cases with guaranteed COMPLEX scoring ---
    # Formula: 3q gives q(20)+multi(10)=30. Need 20 more.
    # body 1500 chars = body_score 75*0.20 = 15. Total: 45. Still need 5 more.
    # body 2000 chars = 20. Total: 50. COMPLEX.
    # body 1200 + 2 tech = 12 + 10 = 22. Total: 52. COMPLEX.
    # body 1200 + topic(2) = 12 + 5 = 17. Total: 47. Need more.
    # body 1200 + topic(3+) = 12 + 10 = 22. Total: 52. COMPLEX.
    # body 1200 + thread(1) = 12 + 2 = 14. + q(30) = 44. Not enough.
    # body 1200 + thread(5) = 12 + 10 = 22. Total: 52. COMPLEX.

    _parametric_fr = [
        # Each has 3+ questions, 1200+ chars body, and extra signals to reach 50+
        (
            "Bonjour,\n\nPour le prochain comité:\n\n"
            "1. Où en est le recrutement?\n"
            "2. Le budget formation est-il épuisé?\n"
            "3. Quand est la prochaine évaluation annuelle?\n"
            "4. Est-ce qu'on a le feedback des équipes?\n"
            "5. Quel est le taux d'absentéisme?\n\n"
            "Par ailleurs, les résultats de l'enquête de satisfaction sont attendus.\n\n"
            "Merci de préparer les données pour mardi.",
            "Comité RH - 5 questions", 0, "FR 5q + 2 topics"
        ),
        (
            "Bonjour,\n\nPour le projet de refactoring:\n\n"
            "- Est-ce qu'on garde le monolithe ou on passe en microservices?\n"
            "- Quel est l'impact sur la dette technique?\n"
            "- Combien de sprints ça va prendre?\n\n"
            "De plus, le CTO veut un estimé des coûts pour le budget annuel.\n\n"
            "Le CTO veut une décision avant la fin du mois. Le planning est serré.",
            "Refactoring - Architecture", 2, "FR 3q + tech (refactor, sprint) + 2 topics + thread"
        ),
        (
            "Bonjour l'équipe,\n\nAvant de valider le release candidate:\n\n"
            "1. Les tests E2E sont-ils tous verts?\n"
            "2. A-t-on vérifié la compatibilité navigateur?\n"
            "3. Le changelog est-il à jour?\n"
            "4. Est-ce que le monitoring est en place?\n"
            "5. Qui fait le deploy en production?\n\n"
            "D'autre part, le marketing a besoin des release notes.\n\n"
            "On vise un deploy demain à 6h. Confirmez votre disponibilité.",
            "Release candidate v4.0", 3, "FR 5q + tech (deploy, production, release) + topic + thread"
        ),
        (
            "Bonjour,\n\nPour la conformité SOC2:\n\n"
            "1. Est-ce que tous les employés ont suivi la formation sécurité?\n"
            "2. Les accès sont-ils revus trimestriellement?\n"
            "3. Avons-nous un plan de continuité d'activité?\n\n"
            "De plus, l'auditeur veut voir nos procédures de gestion des incidents.\n\n"
            "L'audit commence dans 3 semaines. Chaque département doit être prêt.",
            "Audit SOC2 - Préparation", 0, "FR 3q + 2 topics"
        ),
        (
            "Bonjour,\n\nSur le plan de continuité d'activité:\n\n"
            "1. Est-ce que le backup est testé régulièrement?\n"
            "2. Quand est le prochain exercice de reprise?\n"
            "3. Qui est le responsable PCA dans chaque département?\n\n"
            "Concernant la reprise après sinistre, les procédures sont-elles documentées?\n\n"
            "Le DG veut un rapport mensuel à ce sujet. C'est une priorité.",
            "PCA - Questions", 1, "FR 4q + topics + thread"
        ),
        (
            "Bonjour,\n\nPour le lancement du nouveau produit:\n\n"
            "1. Est-ce que le site web est prêt pour le lancement?\n"
            "2. Les assets marketing sont-ils validés par la direction?\n"
            "3. Quand commence la campagne publicitaire?\n\n"
            "Par ailleurs, le budget média a-t-il été approuvé?\n\n"
            "Le DG veut tout caler avant le salon professionnel de mai.",
            "Lancement produit", 0, "FR 4q + 2 topics"
        ),
        (
            "Bonjour,\n\nConcernant la migration des données client:\n\n"
            "1. Combien d'enregistrements sont concernés par la migration?\n"
            "2. Est-ce que la validation est automatisée via le CI/CD?\n"
            "3. Quand est la fenêtre de migration prévue?\n\n"
            "De plus, l'ancienne base sera décommissionnée le 31 mars.\n\n"
            "L'équipe base de données attend le feu vert pour commencer le schema update.",
            "Migration données", 2, "FR 3q + tech (migration, CI/CD, database, schema) + topic + thread"
        ),
        (
            "Bonjour,\n\nPour le dashboard analytics:\n\n"
            "1. Est-ce qu'on utilise Grafana ou un outil custom?\n"
            "2. Quels KPI sont prioritaires pour le management?\n"
            "3. Comment on gère le real-time vs batch processing?\n\n"
            "De plus, est-ce que les données sont agrégées en SQL ou en code applicatif?\n\n"
            "Le directeur veut le dashboard opérationnel la semaine prochaine.",
            "Dashboard analytics", 2, "FR 4q + tech (KPI, SQL) + topic + thread"
        ),
        (
            "Bonjour,\n\nConcernant les tests automatisés du pipeline:\n\n"
            "- Quel est le coverage actuel du code backend?\n"
            "- Est-ce que les tests d'intégration sont stables sur le CI/CD?\n"
            "- Comment on gère les tests flaky dans le pipeline?\n\n"
            "Par ailleurs, le temps d'exécution du CI est passé de 10 à 25 minutes. "
            "Pourquoi cette régression?\n\n"
            "On perd beaucoup de temps en boucle de feedback.",
            "CI tests - Performance", 1, "FR 4q + tech (CI/CD) + topic + thread"
        ),
        (
            "Bonjour,\n\nJ'ai des questions sur l'hébergement cloud:\n\n"
            "1. Est-ce qu'on reste sur AWS ou on migre vers GCP?\n"
            "2. Quel est le coût mensuel actuel de l'infrastructure?\n"
            "3. Comment on gère le multi-région et la redondance?\n"
            "4. Est-ce que le backup de la database est testé régulièrement?\n\n"
            "De plus, le contrat AWS expire dans 3 mois. On doit renégocier.\n\n"
            "Le budget cloud est serré cette année.",
            "Hébergement cloud", 1, "FR 5q + tech (AWS, GCP, migration, database, contrat) + topic"
        ),
        (
            "Bonjour,\n\nVoici mes questions pour la revue de sécurité:\n\n"
            "1. Est-ce que l'authentification MFA est obligatoire pour tous?\n"
            "2. Les mots de passe ont-ils une politique de rotation?\n"
            "3. Comment on gère les accès VPN depuis l'étranger?\n\n"
            "De plus, le RSSI demande un audit complet des permissions d'accès.\n"
            "Quand peut-on planifier ça?\n\n"
            "La conformité ISO 27001 est en jeu.",
            "Sécurité - Audit accès", 0, "FR 4q + 2 topics"
        ),
        (
            "Bonjour,\n\nPour la gestion des environnements de dev:\n\n"
            "1. Est-ce que l'env de dev est synchronisé avec le staging?\n"
            "2. Comment on gère les données de test sensibles?\n"
            "3. Qui a accès à l'environnement de production?\n\n"
            "Concernant Docker, est-ce que les images sont à jour?\n\n"
            "On a eu des problèmes de drift entre les envs la semaine dernière.",
            "Environnements - Gestion", 2, "FR 4q + tech (Docker, staging, production) + topic + thread"
        ),
    ]

    for body_raw, subj, depth, desc in _parametric_fr:
        body = _pad(body_raw, 1200)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 90, desc))

    _parametric_en = [
        (
            "Hi,\n\nSeveral questions about the onboarding process:\n\n"
            "1. Do new hires get access to Jira on day one?\n"
            "2. Who assigns the buddy mentor for each team?\n"
            "3. Is the IT setup checklist automated via CI/CD?\n"
            "4. How long is the probation period?\n"
            "5. When do they get production access?\n\n"
            "Additionally, can we improve the onboarding documentation?\n\n"
            "The last 3 hires had significant issues with this process.",
            "Onboarding improvements", 1, "EN 6q + tech (Jira, CI/CD, production) + topic"
        ),
        (
            "Hello,\n\nI'm preparing the quarterly business review:\n\n"
            "- What was our MRR growth this quarter compared to last?\n"
            "- How many new enterprise clients did we sign?\n"
            "- What's the current churn rate by segment?\n"
            "- Can you provide the NPS score breakdown by region?\n\n"
            "Additionally, what's the ROI on the marketing campaigns?\n\n"
            "The board meeting is next Tuesday. I need slides by Monday.",
            "Q1 Business Review", 0, "EN 5q + business tech (KPI, ROI) + topic"
        ),
        (
            "Hi Alex,\n\nRegarding the database performance issues:\n\n"
            "1. What queries are causing the slowdown in the API?\n"
            "2. Have we added the missing indexes to the schema?\n"
            "3. Is the connection pool sized correctly for production?\n\n"
            "Also, should we consider moving to a read replica setup?\n\n"
            "The response time has degraded from 200ms to 3s since last deploy.",
            "DB performance", 4, "EN 4q + tech (database, API, schema, production, deploy) + topic + thread 4"
        ),
        (
            "Hello team,\n\nFor the GDPR data subject access request we received:\n\n"
            "- Which systems contain this user's personal data?\n"
            "- Can we export all data within the 30-day GDPR deadline?\n"
            "- How do we handle data in third-party services?\n\n"
            "Regarding the right to erasure, is our deletion process automated?\n\n"
            "The legal team needs a response plan by end of week.",
            "GDPR DSAR", 1, "EN 4q + GDPR tech + topic + thread"
        ),
        (
            "Hi,\n\nI need some information about the new microservices:\n\n"
            "1. How many services are we splitting the monolith into?\n"
            "2. What messaging system are we using for the API?\n"
            "3. How do services discover each other in the cluster?\n"
            "4. What's the deployment strategy (blue-green, canary)?\n\n"
            "Can we also discuss the schema migration plan for shared databases?\n\n"
            "I want to start the design doc this week.",
            "Microservices architecture", 0, "EN 5q + tech (deploy, schema, migration, database, API)"
        ),
        (
            "Hello,\n\nAbout the sprint retrospective action items:\n\n"
            "- Did we fix the flaky CI tests in the pipeline?\n"
            "- Has the code review turnaround improved this sprint?\n"
            "- Are we tracking technical debt in Jira properly?\n\n"
            "Also, when is the next sprint planning session?\n\n"
            "The velocity has been dropping for 3 sprints in a row.",
            "Sprint retro follow-up", 2, "EN 4q + agile tech (sprint, CI, Jira) + topic + thread"
        ),
        (
            "Hi,\n\nFor the new authentication system design:\n\n"
            "1. Are we using OAuth 2.0 or OpenID Connect?\n"
            "2. How do we handle multi-factor authentication?\n"
            "3. What's the session timeout policy for the API?\n"
            "4. Can users link multiple identity providers?\n"
            "5. How do we handle the migration of existing sessions?\n\n"
            "The security review is scheduled for next week.",
            "Auth system design", 0, "EN 5q + tech (OAuth, migration, API)"
        ),
        (
            "Hello,\n\nQuick questions about the API rate limiting:\n\n"
            "1. What's the current rate limit per API client?\n"
            "2. How do we handle burst traffic on the endpoints?\n"
            "3. Is the rate limiter at the gateway or app level?\n"
            "4. Can premium clients get higher limits via the SLA?\n\n"
            "Our biggest client is hitting the limit during peak hours.\n\n"
            "We need a solution this sprint.",
            "API rate limiting", 0, "EN 4q + tech (API, endpoint, SLA, sprint) + topic"
        ),
        (
            "Hello team,\n\nFor the vendor evaluation process:\n\n"
            "- Which vendors have responded to our RFP?\n"
            "- What are the scoring criteria for the evaluation?\n"
            "- When is the shortlist decision expected?\n\n"
            "Regarding the technical evaluation, can we set up a staging environment "
            "to test each vendor's API integration?\n\n"
            "The procurement team needs this finalized by end of quarter.",
            "Vendor evaluation", 1, "EN 4q + tech (staging, API) + topic + thread"
        ),
        (
            "Hi team,\n\nRegarding our testing strategy:\n\n"
            "- What's our current code coverage on the CI/CD pipeline?\n"
            "- Are integration tests automated for all API endpoints?\n"
            "- How do we handle performance testing in staging?\n\n"
            "Also, the test suite takes 45 minutes to run. Can we optimize?\n\n"
            "The QA lead is asking for a status update on all fronts.",
            "Testing strategy review", 2, "EN 4q + tech (CI/CD, API, endpoint, staging) + topic + thread"
        ),
        (
            "Hi,\n\nAbout the data pipeline reliability:\n\n"
            "1. What's the latency from ingestion to dashboard?\n"
            "2. How do we handle schema evolution in the pipeline?\n"
            "3. Is the pipeline idempotent for reprocessing?\n\n"
            "Also, the ETL jobs keep failing on weekends. "
            "Can we look into the error logs for the database?\n\n"
            "I'll set up a Jira board to track these issues.",
            "Data pipeline reliability", 3, "EN 4q + tech (schema, Jira, error, database) + topic + thread"
        ),
    ]

    for body_raw, subj, depth, desc in _parametric_en:
        body = _pad(body_raw, 1200)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 90, desc))

    # --- With instructions (3q + instructions = 30 + 10 = 40, need 10 more from body) ---
    _instr_cases = [
        (
            "Bonjour,\n\nMerci de traiter les points suivants:\n\n"
            "1. Est-ce que le rapport est prêt?\n"
            "2. Quand est la deadline?\n"
            "3. Qui est le responsable?\n\n"
            "Réponds de manière formelle et détaillée pour le client.",
            "Points urgents", 0, True, False, "FR 3q + instructions"
        ),
        (
            "Hi,\n\nPlease handle these questions about the API endpoint:\n\n"
            "1. What's the status of the staging deployment?\n"
            "2. When can we deploy to production?\n"
            "3. Is the bug fixed on the CI/CD pipeline?\n\n"
            "Reply in bullet points with dates.",
            "Status update needed", 1, True, False, "EN 3q + tech + instructions"
        ),
        (
            "Bonjour,\n\nVoici les questions du client enterprise:\n\n"
            "- Quand sera livrée la fonctionnalité de facturation?\n"
            "- Est-ce que le prix inclut le support technique?\n"
            "- Comment on gère les mises à jour de l'API?\n\n"
            "Sois concis et professionnel dans ta réponse.",
            "Questions client - Urgent", 2, True, False, "FR 3q + tech (facturation, API) + instructions + thread"
        ),
        (
            "Hello,\n\nThe board needs answers to these questions:\n\n"
            "1. What's our current burn rate this quarter?\n"
            "2. How many months of runway do we have?\n"
            "3. What's the revenue forecast for Q3?\n\n"
            "Keep it executive-level, no technical jargon.",
            "Board questions", 0, True, False, "EN 3q + instructions"
        ),
        (
            "Bonjour,\n\nMerci de me préparer un résumé:\n\n"
            "1. Où en est le projet de migration SQL?\n"
            "2. Quels sont les risques identifiés pour le deploy?\n"
            "3. Quel est le planning prévisionnel du sprint?\n\n"
            "Utilise un ton formel, c'est pour le comex.",
            "Résumé projet migration", 1, True, False, "FR 3q + tech (migration, SQL, deploy, sprint) + instructions"
        ),
    ]

    for body_raw, subj, depth, instr, attach, desc in _instr_cases:
        body = _pad(body_raw, 1000)
        cases.append((body, subj, depth, instr, attach, "COMPLEX", 50, 90, desc))

    # --- With attachments ---
    _attach_cases = [
        (
            "Bonjour,\n\nVeuillez trouver ci-joint les documents demandés.\n\n"
            "1. Est-ce que le format du rapport convient?\n"
            "2. Faut-il ajouter d'autres annexes au dossier?\n"
            "3. Quand est la date limite de soumission?\n\n"
            "Par ailleurs, le document contient des données confidentielles.",
            "Documents - Validation", 1, False, True, "FR 3q + attach + topic"
        ),
        (
            "Hi,\n\nPlease review the attached database migration report:\n\n"
            "- Are the SQL queries optimized for staging?\n"
            "- Does the schema look correct for production?\n"
            "- Can we use this for the deploy plan?\n\n"
            "The database team needs feedback by Thursday.",
            "Report review", 2, False, True, "EN 3q + tech (SQL, schema, staging, production, deploy, database) + attach + thread"
        ),
    ]

    for body_raw, subj, depth, instr, attach, desc in _attach_cases:
        body = _pad(body_raw, 1000)
        cases.append((body, subj, depth, instr, attach, "COMPLEX", 50, 92, desc))

    # --- Fill to 100 with more parametric cases ---
    _fill_templates = [
        ("Bonjour,\n\nConcernant {topic}:\n\n"
         "1. {q1}?\n2. {q2}?\n3. {q3}?\n\n"
         "Par ailleurs, {extra}.\n\nCordialement",
         "{topic} - Questions"),
    ]

    _fill_data = [
        {"topic": "le CRM", "q1": "Quand est la mise en production du deploy",
         "q2": "Est-ce que les données clients sont migrées dans la database",
         "q3": "Combien d'utilisateurs seront formés",
         "extra": "le budget formation et le contrat avec l'intégrateur doivent être validés",
         "depth": 1, "desc": "FR 3q CRM project + tech"},
        {"topic": "l'ERP et la facturation", "q1": "Est-ce que le module de facturation est testé sur le staging",
         "q2": "Quand commence la formation utilisateurs",
         "q3": "Comment on gère la migration des données SQL historiques",
         "extra": "le contrat avec l'intégrateur doit être renouvelé selon le SLA",
         "depth": 0, "desc": "FR 3q ERP + tech"},
        {"topic": "l'application mobile", "q1": "Est-ce que le build iOS passe sur le CI/CD",
         "q2": "Quand est la soumission sur l'App Store et le deploy",
         "q3": "Comment on gère les push notifications via l'API",
         "extra": "le designer a besoin des specs et le sprint se termine vendredi",
         "depth": 2, "desc": "FR 3q mobile + tech"},
        {"topic": "la refonte du site web", "q1": "Est-ce que le design est validé pour le staging",
         "q2": "Quand est la mise en production du deploy",
         "q3": "Comment on gère le SEO pendant la migration de l'API",
         "extra": "le contenu doit être traduit et le sprint planning est lundi",
         "depth": 1, "desc": "FR 3q web + tech"},
        {"topic": "le data warehouse", "q1": "Est-ce que le schema SQL est documenté",
         "q2": "Quand sont prévus les tests de charge sur le staging",
         "q3": "Comment on gère la rétention des données dans la database",
         "extra": "l'équipe BI attend l'accès au endpoint de l'API depuis 2 semaines",
         "depth": 1, "desc": "FR 3q data warehouse + tech"},
        {"topic": "la formation équipe", "q1": "Combien de sessions sont prévues ce trimestre",
         "q2": "Est-ce que le formateur externe est confirmé pour le sprint",
         "q3": "Quel est le budget restant pour la formation technique sur l'API",
         "extra": "les retours de la dernière formation montrent un taux de satisfaction de 85%",
         "depth": 0, "desc": "FR 3q training + tech"},
        {"topic": "le partenariat tech", "q1": "Est-ce que le NDA est signé avec le partenaire",
         "q2": "Quand est le prochain workshop technique sur l'API REST",
         "q3": "Comment on partage les accès staging et les endpoints",
         "extra": "le juridique a des questions sur les clauses du contrat de propriété intellectuelle",
         "depth": 1, "desc": "FR 3q partnership + tech"},
        {"topic": "le budget IT", "q1": "Est-ce que les licences Jira et Confluence sont renouvelées",
         "q2": "Quand expire le contrat AWS pour le cloud hosting",
         "q3": "Combien coûte le SLA premium avec le fournisseur de database",
         "extra": "le DSI veut un comparatif avec Azure et GCP avant la fin du trimestre",
         "depth": 2, "desc": "FR 3q budget + tech"},
        {"topic": "le processus qualité", "q1": "Est-ce que les procédures du CI/CD sont documentées",
         "q2": "Quand est le prochain audit interne du sprint process",
         "q3": "Combien de non-conformités ont été identifiées sur le deploy en staging",
         "extra": "l'auditeur externe vérifiera aussi les endpoints de l'API en production",
         "depth": 0, "desc": "FR 3q quality + tech"},
        {"topic": "la communication interne", "q1": "Est-ce que la newsletter mensuelle est prête",
         "q2": "Quand est la prochaine town hall avec la direction",
         "q3": "Comment on communique sur le deploy de la nouvelle version de l'API",
         "extra": "les résultats de l'enquête de satisfaction montrent des points d'amélioration",
         "depth": 1, "desc": "FR 3q comms + tech"},
    ]

    for d in _fill_data:
        tmpl = _fill_templates[0]
        body_raw = tmpl[0].format(**d)
        subj = tmpl[1].format(**d)
        body = _pad(body_raw, 1200)
        cases.append((
            body, subj, d["depth"], False, False,
            "COMPLEX", 50, 90, d["desc"]
        ))

    # Additional EN fill cases
    _fill_en = [
        (
            "Hi,\n\nFollowing up on the project status:\n\n"
            "- Are we on track for the Q2 deadline for the API deploy?\n"
            "- What are the main blockers on the CI/CD pipeline?\n"
            "- Can we reallocate resources from the staging team?\n\n"
            "Also, the stakeholder meeting is next week.\n\n"
            "Let's sync tomorrow at 10am to align on the sprint goals.",
            "Project status - Follow-up", 2, "EN 3q + tech + topic + thread"
        ),
        (
            "Hello,\n\nAbout the new feature request from client X:\n\n"
            "- Is this technically feasible with our current REST API?\n"
            "- How many sprints would it take to deploy?\n"
            "- Do we need to update the database schema?\n\n"
            "Regarding pricing, should this be a premium feature?\n\n"
            "The sales team promised a response by Friday.",
            "Feature request - Feasibility", 1, "EN 4q + tech (REST, API, sprint, deploy, database, schema)"
        ),
        (
            "Hi,\n\nI have questions about our monitoring setup:\n\n"
            "1. Are we using Prometheus or Datadog for the API?\n"
            "2. What metrics are we tracking for the SLA?\n"
            "3. How do we get alerted on endpoint failures?\n\n"
            "Additionally, the monitoring dashboard hasn't been updated.\n"
            "Can someone take ownership of the CI/CD alerts?\n\n"
            "We need this operational before the next on-call rotation.",
            "Monitoring - Setup review", 3, "EN 4q + tech (API, SLA, endpoint, CI/CD) + topic + thread"
        ),
        (
            "Hello,\n\nFor the upcoming payment provider migration:\n\n"
            "- What's the timeline for the switchover of the API?\n"
            "- How do we handle in-flight transactions during deploy?\n"
            "- Is the new REST endpoint backward compatible?\n"
            "- What testing has been done on the staging database?\n\n"
            "The current provider's contract ends next month.",
            "Payment migration - Timeline", 2, "EN 4q + tech (migration, API, deploy, REST, endpoint, staging, database, contrat)"
        ),
        (
            "Hi,\n\nFor the A/B testing framework setup:\n\n"
            "- Which tool are we deploying (LaunchDarkly, custom)?\n"
            "- How do we assign users to cohorts via the API?\n"
            "- What's the minimum sample size for significance?\n\n"
            "Also, the last test showed a 15% conversion lift on staging.\n"
            "Should we roll out the winner to production?\n\n"
            "Product wants to run 3 more tests this sprint.",
            "A/B testing framework", 1, "EN 4q + tech (deploy, API, staging, production, sprint) + topic"
        ),
        (
            "Hello,\n\nAbout the customer support tool API integration:\n\n"
            "- Can we pull ticket data via their REST endpoint?\n"
            "- Is there a webhook for real-time notifications?\n"
            "- How do we map their JSON schema to our database?\n"
            "- What authentication method (API key, OAuth)?\n\n"
            "The support team needs this integration by end of month.",
            "Support tool - API integration", 0, "EN 4q + tech (REST, endpoint, JSON, schema, database, API, OAuth)"
        ),
        (
            "Hi team,\n\nQuestions about the localization effort for deploy:\n\n"
            "- How many languages are we targeting for the API v2?\n"
            "- Are all strings externalized in JSON files?\n"
            "- Who is doing the French and Spanish translations?\n\n"
            "Regarding the RTL support, is that in scope for this sprint?\n\n"
            "The international production launch is in 6 weeks.",
            "Localization - Planning", 1, "EN 4q + tech (API, JSON, sprint, production) + topic"
        ),
        (
            "Hello,\n\nI have concerns about our error handling strategy:\n\n"
            "1. Are we logging all exceptions with stack traces in the API?\n"
            "2. How do users see error messages from the endpoint?\n"
            "3. What's our process for triaging bug reports in Jira?\n"
            "4. Is the production monitoring configured?\n\n"
            "The error rate spiked to 5% last week on staging.",
            "Error handling - Improvements", 3, "EN 4q + tech (exception, stack trace, API, endpoint, bug, Jira, production, staging) + thread"
        ),
        (
            "Hello,\n\nAbout the multi-tenant architecture for our API:\n\n"
            "- How do we isolate tenant data in the database?\n"
            "- Is the schema shared or per-tenant in production?\n"
            "- How does this affect our deployment strategy?\n\n"
            "Also, what's the performance impact on the REST endpoint?\n\n"
            "The enterprise clients need this before contract renewal.",
            "Multi-tenant architecture", 2, "EN 4q + tech (database, schema, production, deploy, REST, endpoint, contrat) + topic"
        ),
        (
            "Hi,\n\nRegarding the load testing results on staging:\n\n"
            "- What was the peak concurrent users on the API?\n"
            "- Did we hit any error rate thresholds?\n"
            "- Is the auto-scaling policy working on Kubernetes?\n"
            "- How does the database handle the load?\n\n"
            "The staging environment crashed at 500 concurrent users.\n\n"
            "We need to fix this before the production deploy.",
            "Load testing - Results review", 3, "EN 4q + tech (staging, API, error, Kubernetes, database, production, deploy) + topic + thread"
        ),
    ]

    for body_raw, subj, depth, desc in _fill_en:
        body = _pad(body_raw, 1200)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 92, desc))

    # More parametric fill to reach 100
    _extra_fill = [
        ("Bonjour,\n\nPour le plan de formation:\n\n1. Combien de sessions prévues?\n2. Est-ce que le formateur est confirmé pour le sprint?\n3. Quel est le budget restant pour l'API training?\n\nPar ailleurs, les retours de la dernière session sont positifs.", "Formation plan", 0),
        ("Hi,\n\nAbout the client demo for the API:\n\n1. What version are we showing on staging?\n2. Is the test data loaded in the database?\n3. Who is presenting the deploy process?\n\nWe need to rehearse the endpoint flow today.", "Client demo prep", 1),
        ("Bonjour,\n\nConcernant l'offre commerciale:\n\n1. Est-ce que le pricing de l'API est finalisé?\n2. Quand envoie-t-on la proposition au client?\n3. Qui valide le contrat côté direction?\n\nLe prospect attend une réponse pour le deploy.", "Offre commerciale", 0),
        ("Hello,\n\nFor the vendor API integration:\n\n- Did they provide the REST endpoint documentation?\n- What authentication does the staging use?\n- Is there a sandbox for the database testing?\n\nOur sprint depends on the CI/CD pipeline.", "Vendor integration", 1),
        ("Bonjour,\n\nPour la revue des processus CI/CD:\n\n1. Est-ce que les procédures de deploy sont documentées?\n2. Les non-conformités du staging sont-elles corrigées?\n3. Qui est responsable du pipeline API?\n\nL'auditeur externe arrive le mois prochain.", "Revue processus CI/CD", 0),
        ("Hello,\n\nFor the workspace IT setup:\n\n- When is the server room deploy planned?\n- How many endpoints need the API connection?\n- What happens to the staging database?\n\nIT needs at least 2 weeks for the CI/CD migration.", "Workspace IT", 0),
        ("Bonjour,\n\nSur le budget cloud AWS:\n\n1. Est-ce que le Terraform est optimisé pour le deploy?\n2. Combien coûte le staging mensuel sur Kubernetes?\n3. Quand expire le contrat avec le fournisseur API?\n\nLe DSI veut une réponse avant la fin du sprint.", "Budget cloud", 2),
        ("Hi,\n\nRegarding the incident response:\n\n- Do we have a clear escalation path for the API?\n- Who is on-call for the production endpoint this week?\n- Is the database runbook for staging failures updated?\n\nWe had 3 incidents last month on the deploy pipeline.", "Incident response", 2),
        ("Bonjour,\n\nPour l'intégration SSO OAuth:\n\n1. Est-ce que le provider est configuré pour l'API?\n2. Quand sera le deploy en staging prévu?\n3. Comment on gère le rollback du endpoint?\n\nLe client enterprise attend cette fonctionnalité.", "SSO OAuth integration", 1),
        ("Hello,\n\nAbout the accessibility audit:\n\n- Are all endpoints accessible via the REST API?\n- Does the staging deploy meet WCAG standards?\n- Can users navigate the dashboard via the CI/CD?\n\nWe need compliance before the production launch.", "Accessibility audit", 1),
        ("Bonjour,\n\nConcernant le POC blockchain:\n\n1. Quelle plateforme pour le deploy de l'API?\n2. Est-ce que le smart contrat est audité en staging?\n3. Comment on gère les frais via le endpoint REST?\n\nLe POC doit être prêt dans 2 sprints.", "POC blockchain", 0),
        ("Hi,\n\nFor the new reporting module on the API:\n\n- What KPI dashboards are we deploying to staging?\n- Is the database schema ready for the endpoint?\n- How do we handle the SQL migration in production?\n\nThe analytics team needs this before the sprint ends.", "Reporting module", 2),
        ("Bonjour,\n\nPour le pentest de sécurité:\n\n1. Est-ce que tous les endpoints API sont testés?\n2. Le staging est-il configuré pour le CI/CD scan?\n3. Quand sera le rapport de vulnérabilité du deploy?\n\nLe RSSI attend les résultats pour la database.", "Pentest sécurité", 3),
        ("Hello,\n\nRegarding the mobile app API:\n\n- Is the REST endpoint optimized for mobile staging?\n- When will the CI/CD pipeline deploy the new build?\n- Can we reduce the database response time on production?\n\nThe app store submission deadline is next week.", "Mobile API", 1),
        ("Bonjour,\n\nPour le chatbot IA:\n\n1. Est-ce que l'API du modèle est déployée en staging?\n2. Comment on gère le endpoint de la database?\n3. Quand sera le CI/CD configuré pour le sprint?\n\nL'équipe produit veut une démo avant la release.", "Chatbot IA", 0),
        ("Hi team,\n\nAbout the data privacy:\n\n- Is the API endpoint RGPD compliant on staging?\n- When will the DPO review the database schema?\n- Can the deploy pipeline check for PII in production?\n\nThe DPIA must be updated before the audit.", "Data privacy", 2),
        ("Bonjour,\n\nPour les notifications push:\n\n1. Est-ce que l'API endpoint est configuré en staging?\n2. Le CI/CD déploie-t-il les notifications en production?\n3. Comment on gère le rollback de la database?\n\nLes utilisateurs se plaignent des retards.", "Push notifications", 1),
        ("Hello,\n\nFor the search optimization:\n\n- Is the Elasticsearch API endpoint deployed on staging?\n- When will the database schema be optimized?\n- Can the CI/CD pipeline run performance tests?\n\nSearch latency increased 300% since the last deploy.", "Search optimization", 3),
        ("Bonjour,\n\nConcernant le système de cache:\n\n1. Est-ce que Redis est configuré pour l'API endpoint?\n2. Comment on gère l'invalidation en staging?\n3. Quand sera le deploy en production via le CI/CD?\n\nLes temps de réponse de la database ont augmenté.", "Cache system", 2),
        ("Hi,\n\nAbout the API versioning strategy:\n\n- How do we handle breaking changes on the REST endpoint?\n- Is the staging database compatible with both schema versions?\n- When will the CI/CD pipeline support the deploy of v2?\n\nOur enterprise clients need backward compatibility.", "API versioning", 0),
        ("Bonjour,\n\nPour le monitoring applicatif:\n\n1. Est-ce que les alertes sont configurées pour l'API endpoint?\n2. Le staging détecte-t-il les erreurs de la database?\n3. Quand sera le deploy du dashboard de monitoring?\n\nLe SLA avec le client exige 99.9% de disponibilité.", "Monitoring applicatif", 1),
        ("Hello,\n\nRegarding the feature flags:\n\n- Is LaunchDarkly deployed to the staging API?\n- How do we toggle features for the production endpoint?\n- Can the CI/CD pipeline manage the database migration?\n\nWe need this for the A/B testing sprint.", "Feature flags", 2),
        ("Bonjour,\n\nPour l'automatisation des tests:\n\n1. Est-ce que le CI/CD est configuré pour l'API endpoint?\n2. Les tests de staging couvrent-ils la database?\n3. Quand sera le deploy automatisé en production?\n\nL'équipe QA veut augmenter le coverage du sprint.", "Test automation", 0),
        ("Hello,\n\nAbout the CDN configuration:\n\n- Is the API endpoint cached on staging?\n- When will the deploy propagate to all production regions?\n- Can the CI/CD pipeline verify the database sync?\n\nLatency from Asia is too high for the REST endpoint.", "CDN config", 1),
        ("Bonjour,\n\nPour le plan de disaster recovery:\n\n1. Est-ce que le backup de la database est testé en staging?\n2. Quand sera le deploy du site secondaire?\n3. Comment on vérifie l'API endpoint après le rollback?\n\nLe SLA du contrat exige un RPO de 4 heures.", "Disaster recovery", 2),
        ("Hi,\n\nFor the code review process:\n\n- How many pull requests are pending in the sprint?\n- Is the CI/CD pipeline blocking the merge to staging?\n- When can we deploy the branch to the API endpoint?\n\nThe database migration depends on this code review.", "Code review process", 0),
        ("Bonjour,\n\nConcernant la scalabilité de l'API:\n\n1. Est-ce que le Kubernetes auto-scaling fonctionne en staging?\n2. Combien de requêtes par seconde le endpoint peut-il gérer en production?\n3. Quand sera le deploy de la nouvelle config Docker?\n\nLa database montre des signes de saturation.", "Scalabilité API", 3),
        ("Hello,\n\nRegarding the tech debt reduction:\n\n- Which API endpoints need refactoring for the sprint?\n- Is the database schema migration planned for staging?\n- When can we deploy the CI/CD improvements?\n\nThe technical debt is slowing down the pull request reviews.", "Tech debt reduction", 1),
        ("Bonjour,\n\nPour la documentation technique:\n\n1. Est-ce que l'API endpoint est documenté dans Confluence?\n2. Le guide de deploy en staging est-il à jour?\n3. Quand sera la formation sur le CI/CD pipeline de la database?\n\nLes nouveaux développeurs perdent du temps sans docs.", "Documentation technique", 0),
        ("Hi,\n\nAbout the performance benchmarks:\n\n- What's the current latency for the REST API endpoint?\n- Is the staging database optimized with the SQL indexes?\n- When will the CI/CD pipeline include performance tests?\n\nThe deploy to production should not regress performance.", "Performance benchmarks", 2),
        ("Bonjour,\n\nPour le rollout progressif:\n\n1. Est-ce que le feature flag est configuré pour l'API endpoint?\n2. Comment on monitore la database pendant le deploy en staging?\n3. Quand sera le rollout en production via le CI/CD?\n\nLe sprint se termine vendredi et le canary deploy est critique.", "Rollout progressif", 1),
        ("Hello,\n\nRegarding the developer onboarding:\n\n- Is the Docker development environment documented for the API?\n- When will the staging database be available for new developers?\n- Can the CI/CD pipeline run the local endpoint tests?\n\nThe last 3 hires took 2 weeks to set up their deploy environment.", "Developer onboarding", 0),
        ("Bonjour,\n\nPour la revue d'architecture:\n\n1. Est-ce que l'API endpoint est scalable en production?\n2. Comment on gère la migration du schema de la database?\n3. Quand sera la revue du CI/CD pipeline en staging?\n\nLe CTO veut valider avant le prochain sprint de deploy.", "Revue architecture", 2),
    ]

    for body_raw, subj, depth in _extra_fill:
        body = _pad(body_raw, 1200)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 92, f"Fill: {subj}"))

    return cases[:100]


# ============================================================================
# 2. COMPLEX — Technical emails (80 cases)
# ============================================================================

def _gen_complex_technical():
    """80 cases: 4+ tech keywords, combined with questions and/or long body. Score 50+.

    Tech alone at 4+ keywords gives only 15 points. To reach COMPLEX (50):
      tech(15) + body_2000(20) + 2q(14) = 49. Barely.
      tech(15) + body_2000(20) + 2q(14) + thread(2) = 51. COMPLEX.
      tech(15) + body_1500(15) + 3q(20) + multi(10) = 60. COMPLEX.
      tech(15) + body_1200(12) + 3q(20) + multi(10) = 57. COMPLEX.
    Strategy: combine tech (15) with body >= 1200 + 2-3 questions + some thread/topic.
    """
    cases = []

    # --- Hand-crafted heavy tech + questions ---

    cases.append((
        _pad(
            "Bonjour,\n\nSuite au deploy en production, l'API REST renvoie des erreurs 500. "
            "Le stack trace montre un problème dans le module de migration de la database. "
            "J'ai vérifié les logs du CI/CD et le build était vert sur staging. "
            "Le rollback a été effectué mais le bug persiste.\n\n"
            "Pouvez-vous investiguer rapidement? Quand sera le fix déployé? "
            "Est-ce qu'on doit prévenir le client?", 1300
        ),
        "Erreur 500 post-deploy", 2, False, False,
        "COMPLEX", 55, 92, "FR tech (deploy, production, API, REST, stack trace, migration, database, CI/CD, staging, rollback, bug) + 3q + thread"
    ))

    cases.append((
        _pad(
            "Hi team,\n\nThe Docker containers on the Kubernetes cluster are crashing on startup. "
            "The error logs show an issue with the database schema migration. "
            "I've checked the Terraform configuration and the AWS security groups look correct. "
            "The CI/CD pipeline passed all tests on the staging environment.\n\n"
            "Can someone look at this today? Is the production endpoint returning 503? "
            "Should we rollback the last deploy?", 1300
        ),
        "K8s pods crashing", 3, False, False,
        "COMPLEX", 58, 95, "EN tech (Docker, Kubernetes, database, schema, migration, Terraform, AWS, CI/CD, staging, production, endpoint, rollback, deploy) + 3q + thread"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nLe endpoint GraphQL renvoie des erreurs de schéma. "
            "J'ai vérifié la migration SQL et elle semble correcte. "
            "Le problème pourrait venir du merge de la branche feature/api-v2. "
            "Le deploy en staging a réussi mais le bug apparaît en production.\n\n"
            "Est-ce qu'on doit faire un rollback ou un hotfix? "
            "Quand peut-on tester en staging? "
            "Le CI/CD est-il configuré pour les tests de régression?", 1300
        ),
        "Erreur GraphQL - schema", 1, False, False,
        "COMPLEX", 55, 92, "FR heavy tech + 3q"
    ))

    cases.append((
        _pad(
            "Hello,\n\nI'm setting up the new CI/CD pipeline with the following stack:\n"
            "- Docker for containerization\n"
            "- Kubernetes for orchestration\n"
            "- Terraform for infrastructure as code\n"
            "- AWS for cloud hosting\n\n"
            "The main challenge is the database migration strategy. "
            "We need to handle schema changes without downtime.\n\n"
            "What's the best approach for zero-downtime deployments? "
            "Is there a rollback strategy for the SQL migration? "
            "Can we test this on staging first?", 1300
        ),
        "DevOps stack setup", 0, False, False,
        "COMPLEX", 55, 92, "EN heavy tech (CI/CD, Docker, Kubernetes, Terraform, AWS, database, migration, schema, deploy, rollback, SQL, staging) + 3q"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nLe SLA du contrat stipule un uptime de 99.9%. "
            "Or, notre monitoring montre que les données personnelles ne sont pas "
            "correctement anonymisées dans les exports JSON via l'API REST.\n\n"
            "Le DPO a demandé une correction urgente pour la conformité RGPD. "
            "La DPIA doit être mise à jour avant l'audit.\n\n"
            "Pouvez-vous vérifier le endpoint /api/export? "
            "Quand sera le correctif en staging? "
            "Est-ce que la database est impactée?", 1300
        ),
        "RGPD - Export données", 2, False, False,
        "COMPLEX", 58, 95, "FR tech (SLA, contrat, RGPD, JSON, API, REST, DPO, DPIA, endpoint, staging, database) + 3q + thread"
    ))

    cases.append((
        _pad(
            "Hi,\n\nWe need to refactor the authentication module. Current issues:\n"
            "- OAuth tokens are not properly refreshed via the API endpoint\n"
            "- The SQL queries for user lookup are slow on the database\n"
            "- Error handling doesn't include stack traces in production\n"
            "- The REST endpoint for login has no rate limiting\n\n"
            "I've created a Jira ticket and a new branch for the sprint.\n\n"
            "Can you review the pull request? "
            "When can we merge to main? "
            "Is the CI/CD pipeline running the new tests?", 1300
        ),
        "Auth refactor - Code review", 1, False, False,
        "COMPLEX", 58, 95, "EN heavy tech (refactor, OAuth, API, endpoint, SQL, database, error, stack trace, production, REST, Jira, branch, sprint, pull request, merge, CI/CD) + 3q"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\nLe déploiement Docker en production a échoué. "
            "Le container ne démarre pas à cause d'une erreur dans la configuration Terraform. "
            "J'ai vérifié les variables d'environnement et le schema de la database. "
            "Le problème semble lié à la migration du endpoint /api/v2/users.\n\n"
            "Le CI/CD est bloqué sur la branche main. "
            "Est-ce qu'on peut merger le hotfix directement? "
            "Quand le staging sera-t-il disponible? "
            "Le rollback est-il une option?", 1300
        ),
        "Deploy Docker échoué", 4, False, False,
        "COMPLEX", 60, 95, "FR heavy tech + 3q + thread 4"
    ))

    cases.append((
        _pad(
            "Hello,\n\nThe Kubernetes pods are in CrashLoopBackOff state. "
            "After checking the logs, it appears the database connection pool is exhausted. "
            "The SQL queries from the new API endpoints are not properly optimized.\n\n"
            "I suspect the recent schema migration introduced a regression. "
            "The staging environment works fine, so it might be a production-only config issue.\n\n"
            "Should we rollback the last deploy? "
            "How many users are affected? "
            "Can we increase the connection pool size?", 1300
        ),
        "K8s CrashLoopBackOff", 5, False, False,
        "COMPLEX", 62, 98, "EN heavy tech + 3q + thread 5"
    ))

    # --- More varied tech cases with questions ---
    _tech_cases = [
        (
            "Le pull request pour le refactor du module OAuth est prêt. "
            "J'ai aussi mis à jour le schema JSON de l'API et corrigé les endpoints REST. "
            "Le CI/CD passe sur staging mais le deploy en production a des warnings.\n\n"
            "Pouvez-vous reviewer? Quand le merge sera-t-il fait? "
            "Est-ce que le rollback automatique est configuré?",
            "PR OAuth refactor", 1, "FR tech + 3q"
        ),
        (
            "The database migration script needs to handle the schema changes for the new REST API. "
            "I've tested it on staging with Docker and the SQL looks correct. "
            "The CI pipeline passes all integration tests.\n\n"
            "Is it ready for production deploy? "
            "Should we run the migration during the maintenance window? "
            "Can you verify the endpoint health after deploy?",
            "DB migration ready", 0, "EN tech + 3q"
        ),
        (
            "Bonjour,\n\nL'erreur sur le endpoint /api/webhooks semble liée à un bug dans le parsing JSON. "
            "Le stack trace montre une exception dans le module GraphQL. "
            "J'ai vérifié la branche et le merge avec main est propre.\n\n"
            "Le deploy en staging fonctionne. On peut passer en production? "
            "Quand sera le fix déployé? Est-ce que le CI/CD est configuré?",
            "Bug endpoint webhooks", 2, "FR tech + 3q"
        ),
        (
            "The Terraform provisioning for the new AWS region is complete. "
            "I've configured the Kubernetes cluster with auto-scaling. "
            "The database schema has been migrated and the REST API endpoints are responding.\n\n"
            "Should we set up the CI/CD pipeline next? "
            "When will the staging environment be ready? "
            "Can we start the production deploy this week?",
            "AWS region setup", 0, "EN tech + 3q"
        ),
        (
            "Suite au bug signalé dans Jira, le pipeline CI/CD est cassé sur la branche develop. "
            "Le problème vient d'une migration SQL qui modifie le schema de manière incompatible. "
            "Le rollback n'est pas possible car le deploy en production est déjà fait.\n\n"
            "On doit merger un hotfix rapidement. Quand sera-t-il prêt? "
            "Est-ce que le staging est impacté? Comment on vérifie le endpoint?",
            "CI cassé - hotfix urgent", 3, "FR tech + 3q + thread"
        ),
        (
            "I've deployed the new API endpoints to the staging environment. "
            "The Docker containers are running on Kubernetes with the updated database schema. "
            "The CI/CD pipeline includes automated SQL migration tests.\n\n"
            "Can you verify the GraphQL playground is working? "
            "Is the REST endpoint responding correctly? "
            "When can we proceed to production?",
            "Staging deployment done", 1, "EN tech + 3q"
        ),
        (
            "Bonjour,\n\nLe contrat SLA avec le client stipule 99.95% d'uptime. "
            "Or le dernier incident en production a causé 2h de downtime à cause d'un bug. "
            "Le stack trace a été analysé et un hotfix déployé sur le endpoint API REST.\n\n"
            "Le rapport d'incident pour la RGPD est-il prêt? "
            "Quand le DPO va-t-il valider? Le CI/CD est-il reconfiguré?",
            "Incident SLA - Rapport", 2, "FR tech + 3q + thread"
        ),
        (
            "The sprint review revealed several blockers in the deployment pipeline. "
            "The Docker images need to be rebuilt due to a base image vulnerability. "
            "The Kubernetes config needs updating for the new database endpoints. "
            "The CI/CD tests are failing because the SQL migration changed the schema.\n\n"
            "When can we fix the pipeline? How many sprints will this take? "
            "Should we create Jira tickets for each issue?",
            "Sprint blockers - DevOps", 1, "EN tech + 3q"
        ),
        (
            "Bonjour,\n\nPour la conformité RGPD, le DPO a identifié que nos endpoints API "
            "exposent des données personnelles sans anonymisation. "
            "Le schema de la database doit être modifié pour ajouter le chiffrement. "
            "La migration SQL est prête mais doit être validée en staging.\n\n"
            "Quand le déploiement en production est-il prévu? "
            "Est-ce que le CI/CD vérifie la conformité? "
            "Le DPIA doit-il être mis à jour?",
            "RGPD - Anonymisation API", 0, "FR tech + 3q"
        ),
        (
            "I need to set up the JSON schema validation for the REST API endpoints. "
            "The current implementation doesn't handle the OAuth token refresh properly. "
            "I've also found a bug where the database migration rolls back on error. "
            "The CI/CD pipeline needs an update to test this edge case.\n\n"
            "Can I submit a pull request for the fix? "
            "When should we deploy to staging? "
            "Is the production endpoint affected?",
            "JSON schema + OAuth fix", 2, "EN tech + 3q + thread"
        ),
    ]

    for body_raw, subj, depth, desc in _tech_cases:
        body = _pad(body_raw, 1300)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 95, desc))

    # --- Tech + instructions ---
    _tech_instr = [
        (
            "Le pipeline CI/CD est cassé à cause d'une migration SQL sur staging. "
            "Le Docker container ne build plus depuis le merge de la branche develop. "
            "Le endpoint API /users retourne une erreur 500 en production.\n\n"
            "Corrige le bug et redéploie sur staging d'abord. "
            "Pouvez-vous confirmer le fix? Quand sera-t-il en production? "
            "Le rollback est-il une option de secours?",
            "CI fix urgent", 2, True, False, "FR tech + instr + 3q"
        ),
        (
            "The Kubernetes cluster needs a configuration update for the new REST API. "
            "The database schema migration must be applied before the deploy. "
            "Check the Terraform state file and ensure the AWS credentials are valid.\n\n"
            "Deploy to staging first and run the full test suite. "
            "Is the CI/CD pipeline configured? When can we go to production? "
            "Should we prepare a rollback plan?",
            "K8s update needed", 1, True, False, "EN tech + instr + 3q"
        ),
        (
            "Bonjour,\n\nLe stack trace montre un bug dans le module GraphQL. "
            "Le schema JSON de l'endpoint /api/v2/products est cassé sur le staging. "
            "Le CI/CD est rouge sur la branche main depuis le dernier merge.\n\n"
            "Analyse le problème et propose un fix dans un pull request. "
            "Quand sera le deploy en production? Est-ce que la database est impactée? "
            "Le rollback est-il prévu?",
            "Bug GraphQL - Fix needed", 3, True, False, "FR tech + instr + 3q + thread"
        ),
        (
            "The production database is experiencing slow queries on the new endpoints. "
            "The SQL execution plan shows full table scans on the user_sessions table. "
            "The Jira ticket has the full stack trace of the error.\n\n"
            "Add the missing indexes and test on staging before deploying to production. "
            "When will the fix be ready? Can we validate the endpoint performance? "
            "Is the CI/CD pipeline passing?",
            "DB slow queries - Fix", 2, True, False, "EN tech + instr + 3q + thread"
        ),
        (
            "Le deploy Docker sur Kubernetes a échoué à cause d'un problème de migration SQL. "
            "Le schema de la database est en conflit avec la version en production. "
            "Le CI/CD a détecté le problème mais le rollback automatique n'a pas fonctionné.\n\n"
            "Vérifie la config Terraform et le endpoint de la DB. "
            "Est-ce que l'API REST fonctionne sur staging? Quand sera le fix déployé? "
            "Le SLA du contrat est-il menacé?",
            "Deploy K8s échoué - Action", 1, True, False, "FR tech + instr + 3q"
        ),
    ]

    for body_raw, subj, depth, instr, attach, desc in _tech_instr:
        body = _pad(body_raw, 1300)
        cases.append((body, subj, depth, instr, attach, "COMPLEX", 55, 98, desc))

    # --- Tech + attachments ---
    _tech_attach = [
        (
            "Ci-joint le rapport d'incident production. "
            "Le stack trace montre un bug dans le module OAuth sur l'endpoint API. "
            "Le CI/CD a validé le build mais le problème apparaît en staging. "
            "Le endpoint REST /api/auth retourne une erreur de schema JSON.\n\n"
            "Quand sera le correctif en production? Est-ce que la database est impactée? "
            "Le rollback est-il prévu?",
            "Rapport incident - OAuth", 2, False, True, "FR tech + attach + 3q + thread"
        ),
        (
            "Please find attached the database migration plan. "
            "The SQL scripts handle the schema changes for the new API endpoints. "
            "I've tested them on staging with Docker and Kubernetes.\n\n"
            "Review the Terraform changes in the attached PR diff. "
            "Is the CI/CD pipeline configured for the migration? "
            "When can we deploy to production? Is the rollback tested?",
            "Migration plan attached", 1, False, True, "EN tech + attach + 3q"
        ),
        (
            "Bonjour,\n\nVeuillez trouver ci-joint l'audit de sécurité. "
            "Plusieurs endpoints API présentent des vulnérabilités SQL injection. "
            "Le schema de la database n'est pas correctement validé. "
            "Le rapport RGPD du DPO est aussi en pièce jointe.\n\n"
            "Quand sera le correctif déployé en staging? "
            "Est-ce que le CI/CD détecte ces vulnérabilités? "
            "Le contrat SLA est-il impacté?",
            "Audit sécurité + RGPD", 0, False, True, "FR tech + attach + 3q"
        ),
    ]

    for body_raw, subj, depth, instr, attach, desc in _tech_attach:
        body = _pad(body_raw, 1300)
        cases.append((body, subj, depth, instr, attach, "COMPLEX", 55, 98, desc))

    # --- Generate parametric tech cases ---
    _tech_templates = [
        "Le {t1} du {t2} a révélé un problème avec le {t3}. Le {t4} doit être corrigé avant le prochain {t5}. "
        "Est-ce que le fix est prêt? Quand sera-t-il en staging? Pouvez-vous confirmer?",
        "Suite au {t1}, le {t2} ne fonctionne plus. Le {t3} montre des erreurs dans le {t4}. Le {t5} est impacté. "
        "Quand sera le correctif déployé? Est-ce urgent? Comment on procède?",
        "Le {t1} est configuré pour le {t2}. Le {t3} a été migré vers le {t4}. Le {t5} est opérationnel. "
        "Est-ce que les tests passent? Quand le merge? Pouvez-vous valider?",
        "Problème avec le {t1}: le {t2} retourne des erreurs. Le {t3} a été vérifié sur {t4}. Le {t5} fonctionne. "
        "Comment on corrige? Est-ce que le rollback est possible? Quand sera le fix prêt?",
    ]

    _tech_word_sets = [
        {"t1": "deploy", "t2": "endpoint API", "t3": "schema SQL", "t4": "CI/CD pipeline", "t5": "staging", "depth": 1},
        {"t1": "merge", "t2": "branche Docker", "t3": "migration database", "t4": "Terraform", "t5": "sprint", "depth": 2},
        {"t1": "rollback", "t2": "production", "t3": "stack trace", "t4": "JSON endpoint", "t5": "pull request", "depth": 0},
        {"t1": "refactor", "t2": "module REST", "t3": "schema GraphQL", "t4": "Kubernetes cluster", "t5": "Jira ticket", "depth": 3},
        {"t1": "bug", "t2": "SLA contractuel", "t3": "endpoint API", "t4": "CI/CD", "t5": "deploy production", "depth": 1},
        {"t1": "migration", "t2": "database Azure", "t3": "schema SQL", "t4": "Docker container", "t5": "branch main", "depth": 2},
        {"t1": "deploy Docker", "t2": "cluster AWS", "t3": "endpoint REST", "t4": "schema JSON", "t5": "sprint review", "depth": 0},
        {"t1": "CI/CD", "t2": "branche feature", "t3": "merge conflict", "t4": "staging database", "t5": "production deploy", "depth": 4},
        {"t1": "bug RGPD", "t2": "endpoint GraphQL", "t3": "migration SQL", "t4": "rollback", "t5": "Terraform state", "depth": 1},
        {"t1": "exception", "t2": "endpoint OAuth", "t3": "schema database", "t4": "Docker staging", "t5": "CI/CD deploy", "depth": 2},
        {"t1": "deploy Kubernetes", "t2": "endpoint API REST", "t3": "migration schema", "t4": "SQL database", "t5": "Jira sprint", "depth": 0},
        {"t1": "error production", "t2": "stack trace", "t3": "JSON REST API", "t4": "Docker build", "t5": "branch merge", "depth": 3},
        {"t1": "bug critique", "t2": "endpoint /api/v2", "t3": "migration Azure", "t4": "Terraform deploy", "t5": "schema SQL", "depth": 1},
        {"t1": "crash production", "t2": "database endpoint", "t3": "Docker Kubernetes", "t4": "CI/CD staging", "t5": "merge branch", "depth": 2},
        {"t1": "release candidate", "t2": "API GraphQL", "t3": "SQL migration", "t4": "schema endpoint", "t5": "deploy staging", "depth": 0},
        {"t1": "sprint planning", "t2": "Jira backlog", "t3": "pull request", "t4": "merge branch", "t5": "deploy Docker", "depth": 1},
        {"t1": "contrat SLA", "t2": "KPI production", "t3": "endpoint REST", "t4": "schema database", "t5": "migration SQL", "depth": 2},
        {"t1": "GDPR audit", "t2": "DPO report", "t3": "API endpoint", "t4": "database schema", "t5": "deploy production", "depth": 0},
        {"t1": "deploy AWS", "t2": "Terraform config", "t3": "Docker Kubernetes", "t4": "REST API endpoint", "t5": "SQL migration", "depth": 3},
        {"t1": "rollback production", "t2": "stack trace error", "t3": "bug database", "t4": "schema migration", "t5": "CI/CD staging", "depth": 1},
        {"t1": "refactor module", "t2": "endpoint REST API", "t3": "SQL schema", "t4": "Docker deploy", "t5": "Kubernetes staging", "depth": 2},
        {"t1": "exception handler", "t2": "GraphQL schema", "t3": "JSON endpoint", "t4": "database migration", "t5": "CI pipeline", "depth": 0},
        {"t1": "deploy staging", "t2": "API REST endpoint", "t3": "schema SQL database", "t4": "Docker CI/CD", "t5": "Terraform AWS", "depth": 1},
        {"t1": "bug merge", "t2": "branch production", "t3": "Kubernetes deploy", "t4": "rollback database", "t5": "sprint Jira", "depth": 2},
        {"t1": "migration endpoint", "t2": "schema GraphQL", "t3": "SQL Docker", "t4": "CI/CD staging", "t5": "Terraform deploy", "depth": 0},
        {"t1": "release production", "t2": "stack trace bug", "t3": "API endpoint", "t4": "database schema", "t5": "Docker Kubernetes", "depth": 3},
        {"t1": "sprint merge", "t2": "pull request Jira", "t3": "CI/CD deploy", "t4": "staging production", "t5": "SQL migration", "depth": 1},
        {"t1": "contrat RGPD", "t2": "DPO DPIA", "t3": "SLA endpoint", "t4": "API REST", "t5": "facturation", "depth": 0},
        {"t1": "Kubernetes AWS", "t2": "Terraform Docker", "t3": "deploy staging", "t4": "database endpoint", "t5": "schema migration", "depth": 2},
        {"t1": "OAuth refactor", "t2": "endpoint API", "t3": "JSON schema", "t4": "SQL database", "t5": "CI/CD branch", "depth": 1},
        {"t1": "bug exception", "t2": "error production", "t3": "stack trace endpoint", "t4": "rollback deploy", "t5": "staging database", "depth": 3},
        {"t1": "merge sprint", "t2": "Jira Confluence", "t3": "pull request branch", "t4": "deploy Docker", "t5": "Kubernetes staging", "depth": 0},
        {"t1": "RGPD contrat", "t2": "SLA facturation", "t3": "DPO DPIA", "t4": "endpoint API", "t5": "deploy production", "depth": 1},
        {"t1": "Docker AWS", "t2": "Terraform Kubernetes", "t3": "staging endpoint", "t4": "CI/CD deploy", "t5": "database migration", "depth": 2},
        {"t1": "OAuth GraphQL", "t2": "REST JSON endpoint", "t3": "schema migration", "t4": "SQL database", "t5": "CI/CD staging", "depth": 0},
        {"t1": "sprint Jira", "t2": "pull request merge", "t3": "branch deploy", "t4": "Kubernetes Docker", "t5": "staging production", "depth": 3},
        {"t1": "deploy endpoint", "t2": "API REST staging", "t3": "database SQL schema", "t4": "CI/CD Docker", "t5": "migration rollback", "depth": 1},
        {"t1": "bug production", "t2": "error stack trace", "t3": "exception endpoint", "t4": "deploy staging", "t5": "CI/CD database", "depth": 2},
        {"t1": "refactor API", "t2": "schema endpoint", "t3": "migration deploy", "t4": "staging production", "t5": "CI/CD Docker", "depth": 0},
        {"t1": "Terraform AWS", "t2": "Kubernetes deploy", "t3": "Docker staging", "t4": "database endpoint", "t5": "SQL migration", "depth": 1},
        {"t1": "contrat SLA", "t2": "RGPD DPO", "t3": "API endpoint", "t4": "staging deploy", "t5": "database facturation", "depth": 2},
        {"t1": "GraphQL schema", "t2": "JSON endpoint", "t3": "REST API", "t4": "migration SQL", "t5": "CI/CD deploy", "depth": 0},
        {"t1": "sprint planning", "t2": "Jira backlog", "t3": "merge branch", "t4": "deploy production", "t5": "staging database", "depth": 3},
        {"t1": "Kubernetes pod", "t2": "Docker deploy", "t3": "Terraform staging", "t4": "AWS endpoint", "t5": "database API", "depth": 1},
        {"t1": "rollback production", "t2": "deploy staging", "t3": "CI/CD endpoint", "t4": "database schema", "t5": "SQL migration", "depth": 2},
        {"t1": "pull request", "t2": "merge branch", "t3": "sprint deploy", "t4": "staging production", "t5": "Jira CI/CD", "depth": 0},
        {"t1": "bug endpoint", "t2": "error API", "t3": "stack trace staging", "t4": "deploy production", "t5": "database migration", "depth": 3},
        {"t1": "OAuth API", "t2": "GraphQL endpoint", "t3": "REST staging", "t4": "deploy CI/CD", "t5": "database schema", "depth": 1},
        {"t1": "exception production", "t2": "debug staging", "t3": "crash endpoint", "t4": "rollback deploy", "t5": "CI/CD database", "depth": 2},
        {"t1": "migration SQL", "t2": "schema endpoint", "t3": "database deploy", "t4": "staging production", "t5": "Docker Kubernetes", "depth": 0},
        {"t1": "Terraform config", "t2": "AWS deploy", "t3": "Kubernetes staging", "t4": "Docker endpoint", "t5": "CI/CD database", "depth": 1},
        {"t1": "contrat avenant", "t2": "SLA endpoint", "t3": "API deploy", "t4": "staging production", "t5": "database RGPD", "depth": 2},
        {"t1": "release deploy", "t2": "staging API", "t3": "endpoint database", "t4": "schema CI/CD", "t5": "Docker SQL", "depth": 0},
        {"t1": "Kubernetes deploy", "t2": "AWS staging", "t3": "Terraform endpoint", "t4": "API migration", "t5": "database schema", "depth": 1},
        {"t1": "sprint merge", "t2": "branch Jira", "t3": "pull request deploy", "t4": "CI/CD staging", "t5": "production endpoint", "depth": 2},
        {"t1": "error exception", "t2": "bug stack trace", "t3": "crash endpoint", "t4": "API deploy", "t5": "staging database", "depth": 3},
    ]

    for i, ws in enumerate(_tech_word_sets):
        tmpl = _tech_templates[i % len(_tech_templates)]
        body_raw = tmpl.format(**ws)
        body = _pad(body_raw, 1300)
        subj = f"Tech issue #{i+1}"
        depth = ws["depth"]
        cases.append((
            body, subj, depth, False, False,
            "COMPLEX", 50, 95,
            f"Parametric tech #{i+1} (4+ keywords + 3q + 1300 chars)"
        ))

    return cases[:80]


# ============================================================================
# 3. COMPLEX — Long body (70 cases)
# ============================================================================

def _gen_complex_long():
    """70 cases: body > 1500 chars (body_score 75-100) + questions/tech. Score 50+.

    body 2000 chars = body_score 100 * 0.20 = 20. Need 30 more for COMPLEX.
    body 2000 + 2q = 20 + 14 = 34. STANDARD.
    body 2000 + 3q = 20 + 20 + 10(multi) = 50. COMPLEX.
    body 2000 + 2q + 2 tech = 20 + 14 + 10 = 44. STANDARD.
    body 2000 + 2q + 4 tech = 20 + 14 + 15 = 49. STANDARD.
    body 2000 + 2q + 4 tech + thread(1) = 51. COMPLEX.
    Strategy: long body + 3 questions + some tech, or long body + 2q + heavy tech + signals.
    """
    cases = []

    cases.append((
        _pad(
            "Bonjour l'équipe,\n\n"
            "Je vous écris pour faire un point détaillé sur l'avancement du projet Alpha. "
            "Comme vous le savez, nous sommes en phase de recette depuis deux semaines et "
            "plusieurs problèmes ont été identifiés par l'équipe QA.\n\n"
            "Premièrement, le module de facturation présente des écarts de calcul sur les "
            "montants TTC pour les clients avec TVA intracommunautaire. L'équipe backend a "
            "identifié la cause: une erreur d'arrondi dans la fonction de calcul des remises.\n\n"
            "Deuxièmement, les performances du dashboard se dégradent significativement "
            "au-delà de 10 000 lignes de données. Les temps de chargement passent de 200ms "
            "à plus de 5 secondes, ce qui est inacceptable pour nos clients enterprise.\n\n"
            "Troisièmement, l'intégration avec l'API du partenaire TechCo renvoie des erreurs "
            "intermittentes. Le problème semble lié à un timeout trop court côté serveur.\n\n"
            "Est-ce que tout le monde est disponible à 9h pour un point? "
            "Quand le correctif de la facturation sera-t-il prêt? "
            "Comment on priorise ces corrections?", 2000
        ),
        "Point projet Alpha - Recette", 2, False, False,
        "COMPLEX", 52, 82, "FR 2000 chars + 3q + tech (API, error, facturation) + 3 topics + thread"
    ))

    cases.append((
        _pad(
            "Hi everyone,\n\n"
            "I wanted to provide a comprehensive update on the Q1 product development "
            "progress and highlight some areas that need attention.\n\n"
            "The mobile application team has completed the core features for the v2.0 release. "
            "The main improvements include a redesigned navigation flow, offline support, and "
            "push notification enhancements. However, we've encountered some challenges with "
            "the iOS build pipeline that are causing intermittent CI/CD failures.\n\n"
            "On the backend side, the API migration from v1 to v2 is approximately 70% complete. "
            "The remaining endpoints include the payment processing module and the reporting "
            "dashboard. The database schema changes have been applied to staging and initial "
            "performance tests show a 30% improvement in query response times.\n\n"
            "The DevOps team has made significant progress on the infrastructure front. We've "
            "migrated 80% of our services to Kubernetes and implemented auto-scaling policies. "
            "The CI/CD pipeline now includes automated security scans.\n\n"
            "Can we schedule a cross-functional meeting this week? "
            "What are the main blockers that each team is facing? "
            "Do we need additional resources to meet the Q2 deadline?", 2500
        ),
        "Q1 Dev Update - Action needed", 1, False, False,
        "COMPLEX", 62, 95, "EN 2500 chars + 3q + heavy tech + topics"
    ))

    cases.append((
        _pad(
            "Bonjour,\n\n"
            "Suite à l'audit de sécurité réalisé la semaine dernière par le cabinet CyberSec, "
            "je vous transmets les conclusions principales et les actions correctives.\n\n"
            "L'audit a couvert l'ensemble de notre infrastructure: serveurs de production, "
            "environnements de staging, pipeline CI/CD, et configuration réseau. Au total, "
            "47 points de contrôle ont été vérifiés.\n\n"
            "Les points critiques identifiés:\n"
            "1. Les certificats SSL de 3 sous-domaines expirent dans 15 jours\n"
            "2. La politique de rotation des mots de passe n'est pas appliquée\n"
            "3. Les logs d'accès ne sont pas centralisés dans un SIEM\n"
            "4. Les backups de la database ne sont pas chiffrés\n\n"
            "Les recommandations:\n"
            "- Mise en place d'un WAF devant les endpoints API publics\n"
            "- Activation du MFA pour tous les accès administrateurs\n"
            "- Revue trimestrielle des droits d'accès\n\n"
            "Le DPO a été informé car certains points impactent notre conformité RGPD.\n\n"
            "Pouvez-vous confirmer la disponibilité des équipes DevOps? "
            "Est-ce que le budget de 15k euros pour les outils est validé? "
            "Quand commencent les corrections?", 2200
        ),
        "Audit sécurité - Plan d'action", 3, False, False,
        "COMPLEX", 65, 98, "FR 2200 chars + 3q + heavy tech + lists + topics + thread"
    ))

    # Long + instructions
    cases.append((
        _pad(
            "Bonjour,\n\n"
            "Voici le contexte complet du problème rencontré avec le système de paiement.\n\n"
            "Depuis lundi dernier, nous recevons des plaintes de clients qui signalent des "
            "doubles prélèvements sur leurs comptes bancaires. Après investigation avec l'API, "
            "le webhook de confirmation du prestataire envoie parfois deux notifications. "
            "Notre backend ne gère pas correctement l'idempotence des endpoints.\n\n"
            "L'impact est significatif: 23 transactions en double pour un montant total de "
            "4567 euros. Le service client est submergé.\n\n"
            "Le problème technique est clair: il faut ajouter une clé d'idempotence dans la "
            "table de la database et vérifier l'unicité.\n\n"
            "Rédige une réponse professionnelle pour le client. "
            "Est-ce que le correctif est en staging? "
            "Quand sera-t-il déployé en production? "
            "Faut-il prévenir tous les clients impactés?", 1800
        ),
        "Double prélèvement - Réponse client", 1, True, False,
        "COMPLEX", 60, 98, "FR 1800 chars + instructions + 3q + tech (API, endpoint, database, staging, production)"
    ))

    # Long + attachments
    cases.append((
        _pad(
            "Hi team,\n\n"
            "Please find attached the technical specification for the new reporting module. "
            "This document covers the architecture decisions, database schema changes, and "
            "API endpoint definitions for the REST service.\n\n"
            "The main changes include:\n"
            "- New REST API endpoints for report generation and export via JSON\n"
            "- Database schema modifications for the reporting tables\n"
            "- Integration with the existing OAuth authentication module\n"
            "- Scheduled job configuration for automated report generation\n\n"
            "The deployment plan includes staging validation before production rollout. "
            "The CI/CD pipeline will need to be updated to include the new tests.\n\n"
            "Is the staging environment ready for testing? "
            "When can we start the deploy process? "
            "Should we run the SQL migration first?", 1800
        ),
        "Tech spec - Reporting module", 0, False, True,
        "COMPLEX", 58, 95, "EN 1800 chars + attachment + 3q + heavy tech + lists + topics"
    ))

    # Template-based long cases
    _long_templates = [
        (
            "Bonjour,\n\n"
            "Je vous fais un résumé détaillé de la situation actuelle sur le projet {project}. "
            "Nous avons avancé sur plusieurs fronts ces dernières semaines.\n\n"
            "{details}\n\n"
            "{questions}\n\n"
            "Merci pour votre retour rapide.",
            "Résumé projet {project}"
        ),
        (
            "Hello team,\n\n"
            "Here is a comprehensive summary of the current state of the {project} project. "
            "We have made progress on several fronts.\n\n"
            "{details}\n\n"
            "{questions}\n\n"
            "Looking forward to your feedback.",
            "Update on {project}"
        ),
    ]

    _project_details = [
        {
            "project": "migration cloud AWS",
            "details": (
                "La première phase de la migration vers AWS est terminée. Nous avons transféré "
                "les services non-critiques et les résultats sont positifs. Le temps de réponse "
                "moyen a diminué de 40%. Cependant, les coûts sont supérieurs de 15% en raison "
                "du trafic inter-régions.\n\n"
                "La deuxième phase concerne les services critiques: database principale, "
                "système de paiement, et module d'authentification OAuth. L'équipe DevOps "
                "a préparé un plan de déploiement avec des tests de rollback à chaque étape. "
                "Le CI/CD pipeline est configuré pour les tests de migration."
            ),
            "questions": "Quand la phase 2 sera-t-elle terminée sur le staging?\n"
                        "Est-ce que le budget cloud a été réajusté pour la production?\n"
                        "Comment on gère le rollback en cas de problème sur l'API?",
            "depth": 1, "desc": "FR long migration cloud + 3q + tech"
        },
        {
            "project": "refonte CRM API",
            "details": (
                "L'équipe front-end a terminé les maquettes du nouveau CRM. Le développement "
                "est en cours avec une approche modulaire.\n\n"
                "Côté backend, l'API REST a été redesignée pour supporter les nouvelles "
                "fonctionnalités. Le schema de la database a été optimisé et les tests de "
                "performance montrent une amélioration de 60% sur les endpoints. Le pipeline "
                "CI/CD a été mis à jour pour intégrer les tests d'accessibilité. "
                "Le deploy en staging est prévu la semaine prochaine."
            ),
            "questions": "Est-ce que les utilisateurs pilotes ont été identifiés?\n"
                        "Comment on gère la migration des données SQL?\n"
                        "Quand peut-on commencer le deploy en production?",
            "depth": 2, "desc": "FR long CRM refonte + 3q + tech"
        },
        {
            "project": "API platform v2",
            "details": (
                "The API platform development is progressing well. We have implemented 35 out of "
                "50 planned endpoints and the documentation is generated from the OpenAPI spec. "
                "The authentication layer supports OAuth 2.0 and API key methods.\n\n"
                "Performance testing shows the platform can handle 10,000 requests per second "
                "with p99 latency under 200ms. The database layer uses connection pooling and "
                "read replicas. We've set up comprehensive monitoring with SLA alerts. "
                "The CI/CD pipeline runs all regression tests on staging before deploy."
            ),
            "questions": "When will the remaining endpoints be completed?\n"
                        "Is the staging environment ready for partner testing?\n"
                        "Can we start the production rollout this sprint?",
            "depth": 0, "desc": "EN long API platform + 3q + tech"
        },
        {
            "project": "sécurité réseau CI/CD",
            "details": (
                "L'audit de sécurité réseau a été réalisé avec succès. Les principales "
                "recommandations concernent la segmentation réseau et la mise à jour des "
                "pare-feux.\n\n"
                "Le déploiement du nouveau SIEM est prévu pour la semaine prochaine. "
                "L'intégration avec notre pipeline CI/CD permettra de scanner automatiquement "
                "les images Docker avant déploiement en staging. Le DPO a validé "
                "que ces changements sont conformes à la RGPD. "
                "Les endpoints de l'API seront aussi protégés par un WAF."
            ),
            "questions": "Combien de temps pour déployer le SIEM en production?\n"
                        "Est-ce que l'équipe a besoin de formation sur le CI/CD?\n"
                        "Quand sera le premier deploy en staging?",
            "depth": 3, "desc": "FR long sécurité + 3q + tech"
        },
        {
            "project": "data pipeline SQL",
            "details": (
                "The data pipeline redesign is well underway. We have migrated from batch "
                "processing to a streaming architecture using event-driven patterns.\n\n"
                "The main technical challenge was handling schema evolution without breaking "
                "downstream consumers. We implemented a schema registry. The database "
                "migration was completed last week and all SQL queries have been optimized. "
                "The staging environment is fully operational. "
                "The CI/CD pipeline includes automated data quality checks on all endpoints."
            ),
            "questions": "Are there any performance regressions on the API endpoints?\n"
                        "What's the plan for deploying to production?\n"
                        "Should we schedule a rollback drill on staging?",
            "depth": 1, "desc": "EN long data pipeline + 3q + tech"
        },
    ]

    for tmpl_pair in _long_templates:
        for pd in _project_details:
            body_raw = tmpl_pair[0].format(**pd)
            body = _pad(body_raw, 2000)
            subj = tmpl_pair[1].format(**pd)
            cases.append((
                body, subj, pd["depth"], False, False,
                "COMPLEX", 52, 95, pd["desc"]
            ))

    # Very long emails (2500+ chars)
    cases.append((
        _pad(
            "Bonjour,\n\n"
            "Je vous adresse ce mail pour partager l'ensemble des retours que nous avons "
            "collectés suite à la mise en production de la nouvelle version.\n\n"
            "Les utilisateurs sont globalement satisfaits de la nouvelle interface.\n\n"
            "Cependant, plusieurs irritants ont été identifiés:\n"
            "1. Le chargement des pages est lent sur mobile\n"
            "2. Le formulaire de contact ne fonctionne pas sur Safari\n"
            "3. Les notifications email arrivent avec un délai\n"
            "4. Le module de recherche ne retourne pas les résultats attendus\n"
            "5. L'export PDF des rapports est cassé au-delà de 50 pages\n\n"
            "L'équipe technique a déjà commencé à travailler sur les points 1 et 2. "
            "Un hotfix est prévu pour demain sur le staging.\n\n"
            "Les points 3, 4 et 5 seront traités dans le prochain sprint.\n\n"
            "Par ailleurs, nous avons reçu des demandes de fonctionnalités:\n"
            "- Intégration avec Salesforce via API REST\n"
            "- Single Sign-On (SSO) avec Azure AD via OAuth\n"
            "- API d'export des données en temps réel via JSON\n"
            "- Tableau de bord personnalisable\n\n"
            "Je recommande de prioriser le SSO car c'est un bloqueur pour le contrat avec "
            "le client Durand (150k euros annuels).\n\n"
            "Est-ce que le deploy du hotfix est prévu pour demain? "
            "Quand peut-on commencer le SSO sur le staging? "
            "Le budget CI/CD est-il suffisant pour ces développements?",
            2800
        ),
        "Retours post-launch - Synthèse", 2, False, False,
        "COMPLEX", 62, 98, "FR 2800 chars + 3q + tech (staging, sprint, Azure, API, REST, OAuth, JSON, contrat, deploy, CI/CD) + lists + topics + thread"
    ))

    cases.append((
        _pad(
            "Hello everyone,\n\n"
            "I'm writing to share a detailed analysis of our infrastructure costs for Q1 2026 "
            "and propose an optimization plan that could save us 40%.\n\n"
            "Current monthly spend breakdown:\n"
            "- AWS EC2 instances: $12,500 (48%)\n"
            "- AWS RDS (PostgreSQL): $4,200 (16%)\n"
            "- AWS S3 + CloudFront: $2,800 (11%)\n"
            "- Kubernetes cluster (EKS): $3,500 (13%)\n"
            "- Monitoring (Datadog): $1,800 (7%)\n"
            "Total: $26,000/month\n\n"
            "Proposed optimizations:\n\n"
            "Phase 1 - Quick wins ($5,000/month savings):\n"
            "a) Right-size EC2 instances using the database metrics\n"
            "b) Use Reserved Instances for the API staging servers\n"
            "c) Clean up unused EBS volumes\n\n"
            "Phase 2 - Architecture changes ($3,000/month savings):\n"
            "a) Migrate batch processing to Spot Instances\n"
            "b) Implement S3 lifecycle policies via Terraform\n"
            "c) Consolidate Kubernetes namespaces for the REST endpoints\n\n"
            "The Terraform scripts for Phase 1 are ready for review via pull request.\n\n"
            "Can we schedule a review meeting this week? "
            "Do we have budget approval for the deploy to staging? "
            "Who should own the CI/CD pipeline changes?",
            3000
        ),
        "Cloud cost optimization - Proposal", 1, False, False,
        "COMPLEX", 68, 100, "EN 3000 chars + 3q + heavy tech + lists + topics"
    ))

    # Long + with-instructions
    _long_instr = [
        (
            "Bonjour,\n\n"
            "Voici le contexte complet pour la réponse au client enterprise.\n\n"
            "Le client a souscrit au plan enterprise il y a 6 mois. Depuis le deploy "
            "de la mise à jour v2.3 en production, il rencontre des problèmes de performance "
            "sur le module de reporting. Les rapports via l'API REST prennent 2 minutes.\n\n"
            "L'équipe support a identifié que le problème vient d'une requête SQL non "
            "optimisée dans le nouveau code du endpoint /api/reports.\n\n"
            "Le client a escaladé et menace de résilier son contrat SLA (valeur annuelle: 85k).\n\n"
            "Notre équipe a préparé un hotfix qui sera déployé demain en staging. "
            "Les tests sur le CI/CD montrent que les performances reviennent à la normale.\n\n"
            "Rédige une réponse empathique et professionnelle. "
            "Est-ce que le fix sera en production demain? "
            "Quand le client sera-t-il informé? "
            "Le SLA est-il respecté?",
            "Client enterprise - Réponse escalade", 1, True, False,
            "FR long + instr + 3q + tech", 2000
        ),
    ]

    for body_raw, subj, depth, instr, attach, desc, target_len in _long_instr:
        body = _pad(body_raw, target_len)
        cases.append((body, subj, depth, instr, attach, "COMPLEX", 58, 98, desc))

    # Generate parametric long emails
    for i in range(55):
        char_target = 1800 + (i * 25)  # 1800 to 3175 chars
        depth = i % 5
        has_instr = i % 8 == 0

        base_text = (
            "Bonjour,\n\nVoici un rapport détaillé sur le sujet #{n}.\n\n"
            "L'équipe a travaillé sur le déploiement de l'API REST et la migration "
            "de la base de données SQL. Le CI/CD pipeline est opérationnel sur le staging. "
            "Le deploy en production est prévu prochainement.\n\n"
            "Est-ce que le planning est validé pour le sprint?\n"
            "Quand est la prochaine étape du deploy?\n"
            "Qui est le responsable du endpoint en production?"
        ).format(n=i+1)

        if has_instr:
            base_text += "\n\nRédige un résumé concis pour le comité de direction."

        body = _pad(base_text, char_target)
        desc = f"FR parametric long #{i+1}: {char_target} chars, 3q, tech, depth={depth}"

        cases.append((
            body, f"Rapport #{i+1}", depth, has_instr, False,
            "COMPLEX", 50, 98, desc
        ))

    return cases[:70]


# ============================================================================
# 4. BOUNDARY — Body length (40 cases)
# ============================================================================

def _gen_boundary_body_length():
    """40 cases: test exact char boundaries for body_score calculation."""
    cases = []

    # body_score = 0 for <200 chars → *0.20 = 0
    # body_score = linear(0-50) for 200-1000 → *0.20 = 0-10
    # body_score = linear(50-100) for 1000-2000 → *0.20 = 10-20
    # body_score = 100 for 2000+ → *0.20 = 20

    # --- Under 200 chars (body_score=0) ---
    cases.append((
        _repeat("x ", 98),  # 196 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=196 chars (under 200) -> body_score=0"
    ))

    cases.append((
        _repeat("x ", 99),  # 198 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=198 chars (just under 200) -> body_score=0"
    ))

    # --- At exactly 200 chars (body_score=0: (200-200)/800*50=0) ---
    cases.append((
        _repeat("x ", 100),  # 200 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=200 chars (exact boundary) -> body_score=0"
    ))

    # --- Just over 200 chars ---
    cases.append((
        _repeat("x ", 101),  # 202 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=202 chars -> body_score=int(2/800*50)=0"
    ))

    # --- 300 chars (body_score = int(100/800*50) = int(6.25) = 6, *0.20 = 1) ---
    cases.append((
        _repeat("x ", 150),  # 300 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=300 chars -> body_score=6, *0.20=1"
    ))

    # --- 600 chars (body_score = int(400/800*50) = int(25) = 25, *0.20 = 5) ---
    cases.append((
        _repeat("x ", 300),  # 600 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 10, "body=600 chars -> body_score=25, *0.20=5"
    ))

    # --- At exactly 1000 chars (body_score = int(800/800*50) = 50, *0.20 = 10) ---
    cases.append((
        _repeat("x ", 500),  # 1000 chars
        "Test", 0, False, False,
        "SIMPLE", 5, 15, "body=1000 chars (boundary) -> body_score=50, *0.20=10"
    ))

    # --- 1500 chars (body_score = int(50+500/1000*50) = 75, *0.20 = 15) ---
    cases.append((
        _repeat("x ", 750),  # 1500 chars
        "Test", 0, False, False,
        "SIMPLE", 10, 20, "body=1500 chars -> body_score=75, *0.20=15"
    ))

    # --- At exactly 2000 chars (body_score = int(50+1000/1000*50) = 100, *0.20 = 20) ---
    cases.append((
        _repeat("x ", 1000),  # 2000 chars
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body=2000 chars (boundary) -> body_score=100, *0.20=20"
    ))

    # --- Over 2000 (body_score=100, *0.20=20, capped) ---
    cases.append((
        _repeat("x ", 1500),  # 3000 chars
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body=3000 chars -> body_score=100, *0.20=20"
    ))

    # --- Boundary + 3 questions → q(20)+multi(10)+body(?)=30+body ---
    # Body 600 + 3q: body(5)+q(20)+multi(10)=35 → STANDARD
    cases.append((
        _repeat("x ", 270) + " Est-ce ok? Quand? Pourquoi ce choix?",
        "Test", 0, False, False,
        "STANDARD", 30, 45, "body~600 + 3 questions -> q(20)+multi(10)+body(~5)=35"
    ))

    # Body 1500 + 3q: body(15)+q(20)+multi(10)=45 → STANDARD
    cases.append((
        _repeat("x ", 730) + " Est-ce ok? Quand? Pourquoi ce choix?",
        "Test", 0, False, False,
        "STANDARD", 40, 50, "body~1500 + 3 questions -> q(20)+multi(10)+body(15)=45"
    ))

    # Body ~2000 + 3q: body(~19)+q(20)+multi(10)=49 -> STANDARD (int truncation)
    cases.append((
        _repeat("x ", 980) + " Est-ce ok? Quand? Pourquoi ce choix?",
        "Test", 0, False, False,
        "STANDARD", 48, 52, "body~2000 + 3q -> int truncation may give 49"
    ))

    # Body 2100 + 3q: body(20)+q(20)+multi(10)=50 -> COMPLEX
    cases.append((
        _repeat("x ", 1030) + " Est-ce ok? Quand? Pourquoi ce choix?",
        "Test", 0, False, False,
        "COMPLEX", 50, 55, "body~2100 + 3q -> body(20)+q(20)+multi(10)=50"
    ))

    # --- Boundary with tech keywords ---
    # body 600 + 4 tech: body(5) + tech(15) = 20 → SIMPLE
    cases.append((
        "Le deploy API staging CI/CD " + _repeat("x ", 280),
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body~600 + 4 tech (deploy, API, staging, CI/CD) -> body(5)+tech(15)=20"
    ))

    # body 2000 + 4 tech: body(20) + tech(15) = 35 → STANDARD
    cases.append((
        "Le deploy API staging CI/CD " + _repeat("x ", 980),
        "Test", 0, False, False,
        "STANDARD", 30, 40, "body~2000 + 4 tech -> body(20)+tech(15)=35"
    ))

    # body 2000 + 1q: body(20) + q(7) = 27 → SIMPLE
    cases.append((
        _repeat("x ", 990) + " Est-ce ok?",
        "Test", 0, False, False,
        "SIMPLE", 25, 30, "body~2000 + 1q -> body(20)+q(7)=27"
    ))

    # body 2000 + 2q: body(20) + q(14) = 34 → STANDARD
    cases.append((
        _repeat("x ", 980) + " Est-ce ok? Quand sera-ce prêt?",
        "Test", 0, False, False,
        "STANDARD", 30, 40, "body~2000 + 2q -> body(20)+q(14)=34"
    ))

    # --- Thread depth variations at body boundary ---
    for depth in [0, 1, 3, 5]:
        thread_val = {0: 0, 1: 20, 3: 40, 5: 100}[depth]
        thread_contrib = int(thread_val * 0.10)
        body_contrib = 10  # body=1000
        total = body_contrib + thread_contrib
        tier = _tier(total)
        cases.append((
            _repeat("x ", 500),  # 1000 chars
            "Test", depth, False, False,
            tier, max(0, total - 5), min(100, total + 5),
            f"body=1000 + depth={depth} -> body({body_contrib})+thread({thread_contrib})={total}"
        ))

    # --- Instructions at body boundary ---
    # body=1000 + instr: body(10)+instr(10)=20 → SIMPLE
    cases.append((
        _repeat("x ", 500),
        "Test", 0, True, False,
        "STANDARD", 15, 25, "body=1000 + instructions -> body(10)+instr(10)=20"
    ))

    # --- Attachments at body boundary ---
    # body=1000 + attach: body(10)+attach(5)=15 → SIMPLE
    cases.append((
        _repeat("x ", 500),
        "Test", 0, False, True,
        "SIMPLE", 10, 20, "body=1000 + attachments -> body(10)+attach(5)=15"
    ))

    # --- Empty body ---
    cases.append((
        "",
        "Test subject", 0, False, False,
        "SIMPLE", 0, 5, "empty body -> body_score=0"
    ))

    # Very short body
    cases.append((
        "Ok",
        "Re: test", 0, False, False,
        "SIMPLE", 0, 5, "body=2 chars -> body_score=0"
    ))

    # Exactly 199 chars
    cases.append((
        "x" * 199,
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=199 chars (one under 200) -> body_score=0"
    ))

    # Exactly 201 chars
    cases.append((
        "x" * 201,
        "Test", 0, False, False,
        "SIMPLE", 0, 5, "body=201 chars (one over 200) -> body_score=0"
    ))

    # Exactly 999 chars
    cases.append((
        "x" * 999,
        "Test", 0, False, False,
        "SIMPLE", 5, 15, "body=999 chars (one under 1000) -> body_score=49, *0.20=9"
    ))

    # Exactly 1001 chars
    cases.append((
        "x" * 1001,
        "Test", 0, False, False,
        "SIMPLE", 5, 15, "body=1001 chars (one over 1000) -> body_score=50, *0.20=10"
    ))

    # Exactly 1999 chars
    cases.append((
        "x" * 1999,
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body=1999 chars (one under 2000) -> body_score=99, *0.20=19"
    ))

    # Exactly 2001 chars
    cases.append((
        "x" * 2001,
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body=2001 chars (one over 2000) -> body_score=100, *0.20=20"
    ))

    # Body + all signals maxed
    cases.append((
        _pad(
            "Le deploy CI/CD sur staging via Docker avec Kubernetes et l'API REST en production. "
            "Le schema SQL de la database endpoint migration Terraform AWS. "
            "Est-ce ok? Quand? Pourquoi?\n\n"
            "Par ailleurs, deuxième sujet.\n\nConcernant le troisième.",
            2500
        ),
        "All signals maxed", 5, True, True,
        "COMPLEX", 85, 100, "body~2500 + 3q + 10+ tech + depth=5 + topics + instr + attach -> near max"
    ))

    # Medium body, no signals
    cases.append((
        _repeat("x ", 400),  # 800 chars
        "Test", 0, False, False,
        "SIMPLE", 0, 10, "body=800 chars -> body_score=37, *0.20=7"
    ))

    # Additional precise boundary cases
    cases.append((
        _repeat("x ", 250),  # 500 chars → body_score=18, *0.20=3
        "Test", 0, True, False,
        "STANDARD", 8, 18, "body=500 + instr -> body(3)+instr(10)=13"
    ))

    cases.append((
        _repeat("x ", 600),  # 1200 chars → body_score=60, *0.20=12
        "Test", 2, False, False,
        "SIMPLE", 12, 22, "body=1200 + depth 2 -> body(12)+thread(4)=16"
    ))

    cases.append((
        _repeat("x ", 850),  # 1700 chars → body_score=85, *0.20=17
        "Test", 0, False, True,
        "SIMPLE", 18, 28, "body=1700 + attach -> body(17)+attach(5)=22"
    ))

    cases.append((
        _repeat("x ", 450) + " Est-ce ok? Quand?",
        "Test", 0, False, False,
        "SIMPLE", 18, 28, "body~920 + 2q -> body(~9)+q(14)=23"
    ))

    # body 400 + 3q + 4 tech + thread 3 + instr
    cases.append((
        _pad("Le deploy CI/CD API staging. Est-ce ok? Quand? Pourquoi?", 400),
        "Test", 3, True, False,
        "COMPLEX", 55, 68, "body=400 + 3q + 4tech + thread 3 + instr (filler adds tech)"
    ))

    # body 1800 + no other signals
    cases.append((
        _repeat("x ", 900),
        "Test", 0, False, False,
        "SIMPLE", 15, 25, "body=1800 -> body_score=90, *0.20=18"
    ))

    return cases[:40]


# ============================================================================
# 5. BOUNDARY — Questions (30 cases)
# ============================================================================

def _gen_boundary_questions():
    """30 cases: test 0, 1, 2, 3 exact question counts with controlled bodies."""
    cases = []

    # Base body ~600 chars (body_score=25, *0.20=5)
    base_600 = _repeat("x ", 300)

    # --- 0 questions -> q_score=0, multi=0 ---
    cases.append((
        base_600,
        "No questions", 0, False, False,
        "SIMPLE", 0, 10, "0 questions + 600 chars -> q(0)+body(5)=5"
    ))

    cases.append((
        "Merci pour votre retour. Je prends note. " + _repeat("x ", 278),
        "Accusé de réception", 0, False, False,
        "SIMPLE", 0, 10, "0 questions, statement only -> q(0)"
    ))

    # --- 1 question -> q_score=35, *0.20=7. multi=0. ---
    cases.append((
        base_600 + " Est-ce que c'est ok?",
        "Question unique", 0, False, False,
        "SIMPLE", 5, 15, "1 question + 600 chars -> q(7)+body(5)=12"
    ))

    cases.append((
        "Bonjour, pouvez-vous me confirmer la date de livraison? " + _repeat("x ", 270),
        "Confirmation date", 0, False, False,
        "SIMPLE", 5, 15, "1 question (phrase interrogative) -> q(7)"
    ))

    cases.append((
        "Hi, when is the next meeting? " + _repeat("x ", 285),
        "Meeting query", 0, False, False,
        "SIMPLE", 5, 15, "1 question (EN when) -> q(7)"
    ))

    # --- 2 questions -> q_score=70, *0.20=14. multi=0 (2q < 3). ---
    cases.append((
        base_600 + " Est-ce ok? Quand sera-ce prêt?",
        "Deux questions", 0, False, False,
        "SIMPLE", 15, 25, "2 questions + 600 chars -> q(14)+body(5)=19"
    ))

    cases.append((
        "Can you send me the report? When will it be ready? " + _repeat("x ", 275),
        "Two questions EN", 0, False, False,
        "SIMPLE", 15, 25, "2 questions (EN) -> q(14)"
    ))

    cases.append((
        "Pouvez-vous confirmer? Est-ce que le budget est validé? " + _repeat("x ", 270),
        "Deux questions FR", 0, False, False,
        "SIMPLE", 15, 25, "2 questions (FR phrase) -> q(14)"
    ))

    # --- 3 questions -> q_score=100*0.20=20. multi_score=100*0.10=10. Total from q: 30. ---
    # With 600 chars body(5), total = 35. STANDARD.
    cases.append((
        base_600 + " Est-ce ok? Quand? Pourquoi ce choix?",
        "Trois questions", 0, False, False,
        "STANDARD", 30, 42, "3 questions + 600 chars -> q(20)+multi(10)+body(5)=35"
    ))

    cases.append((
        "How is the project going? When is the deadline? Can we extend it? " + _repeat("x ", 265),
        "Three questions EN", 0, False, False,
        "STANDARD", 30, 42, "3 questions (EN) -> q(20)+multi(10)+body(~5)"
    ))

    cases.append((
        "Pouvez-vous confirmer la date? Est-ce que le budget est ok? Combien ça va coûter? " + _repeat("x ", 255),
        "Trois questions FR", 0, False, False,
        "STANDARD", 30, 42, "3 questions (FR phrase) -> q(20)+multi(10)+body(~5)"
    ))

    # --- 4+ questions -> same as 3 (q_score=100), confirms ceiling ---
    cases.append((
        base_600 + " Est-ce ok? Quand? Pourquoi? Comment?",
        "Quatre questions", 0, False, False,
        "STANDARD", 30, 42, "4 questions -> same q(20)+multi(10) as 3"
    ))

    cases.append((
        "What? When? Where? Why? How? " + _repeat("x ", 285),
        "Five questions EN", 0, False, False,
        "STANDARD", 30, 42, "5 questions -> same q(20)+multi(10), confirms ceiling"
    ))

    # --- Question mark without interrogative phrase ---
    cases.append((
        "Vraiment? " + _repeat("x ", 295),
        "Single ?", 0, False, False,
        "SIMPLE", 14, 24, "1 question (? only) -> q(7)"
    ))

    cases.append((
        "Vraiment? Sérieusement? Ah bon? " + _repeat("x ", 280),
        "Three ?", 0, False, False,
        "STANDARD", 30, 42, "3 questions (? marks) -> q(20)+multi(10)"
    ))

    # --- Phrase interrogative without ? mark ---
    cases.append((
        "Pouvez-vous me confirmer. " + _repeat("x ", 287),
        "Phrase without ?", 0, False, False,
        "SIMPLE", 14, 24, "1 interrogative phrase without ? -> q(7)"
    ))

    cases.append((
        "Can you tell me. Could you send. Would you please. " + _repeat("x ", 275),
        "EN phrases no ?", 0, False, False,
        "STANDARD", 30, 42, "3 EN interrogative phrases -> q(20)+multi(10)"
    ))

    # --- Questions in subject (counted in full_text) ---
    cases.append((
        _repeat("x ", 300),
        "Est-ce urgent? Quand? Pourquoi?", 0, False, False,
        "STANDARD", 30, 42, "3 questions in subject -> q(20)+multi(10)"
    ))

    # --- 3 questions with higher body -> near COMPLEX boundary ---
    # int truncation may give 49: STANDARD
    cases.append((
        _repeat("x ", 980) + " Est-ce ok? Quand? Pourquoi?",
        "Long + 3q", 0, False, False,
        "STANDARD", 48, 52, "3q + ~2000 chars -> int truncation may give 49"
    ))

    # 3 questions + thread depth for near-COMPLEX
    cases.append((
        _repeat("x ", 300) + " Est-ce ok? Quand? Pourquoi?",
        "3q + thread", 3, False, False,
        "STANDARD", 35, 48, "3q + 640 chars + depth 3 -> q(20)+multi(10)+body(5)+thread(4)=39"
    ))

    # 3 questions + tech -> near boundary, int truncation may give 49
    cases.append((
        _repeat("x ", 250) + " Est-ce que le deploy API staging CI/CD fonctionne? Quand? Pourquoi?",
        "3q + tech", 0, False, False,
        "STANDARD", 45, 55, "3q + 4 tech -> int truncation may give 49"
    ))

    # 2 questions + instructions -> q(14) + instr(10) = 24
    cases.append((
        base_600 + " Est-ce ok? Quand?",
        "2q + instr", 0, True, False,
        "STANDARD", 24, 34, "2q + instr + 640 chars -> q(14)+instr(10)+body(5)=29"
    ))

    # 2 questions + attachments -> q(14) + attach(5) = 19
    cases.append((
        base_600 + " Est-ce ok? Quand?",
        "2q + attach", 0, False, True,
        "SIMPLE", 20, 30, "2q + attach + 640 chars -> q(14)+attach(5)+body(5)=24"
    ))

    # 0 questions + everything else to show q isn't needed
    cases.append((
        _pad("Le deploy CI/CD Docker Kubernetes AWS Terraform API REST staging production.", 2000),
        "No q + all tech", 5, True, True,
        "COMPLEX", 50, 70, "0q + 2000 chars + 8 tech + depth 5 + instr + attach -> body(20)+tech(15)+thread(10)+instr(10)+attach(5)=60"
    ))

    # 6 questions -> same ceiling as 3
    cases.append((
        "Quoi? Quand? Ou? Comment? Pourquoi? Combien? " + _repeat("x ", 270),
        "Six questions", 0, False, False,
        "STANDARD", 30, 42, "6 questions -> same q(20)+multi(10), confirms ceiling at 3+"
    ))

    # 1 question in subject, 2 in body -> total 3
    cases.append((
        base_600 + " Est-ce ok? Quand sera-ce prêt?",
        "Pourquoi le retard?", 0, False, False,
        "STANDARD", 30, 42, "2q in body + 1q in subject -> total 3 -> q(20)+multi(10)"
    ))

    # Mix ? and phrase interrogative in same sentence (should count as 1)
    cases.append((
        "Est-ce que vous pouvez confirmer? " + _repeat("x ", 283),
        "Mixed", 0, False, False,
        "SIMPLE", 5, 15, "1 sentence with ? + phrase -> count as 1"
    ))

    # Question separated by newlines
    cases.append((
        "Premier paragraphe.\n\nEst-ce validé?\nQuand?\nPourquoi? " + _repeat("x ", 260),
        "Newline questions", 0, False, False,
        "STANDARD", 30, 48, "3 questions separated by newlines -> q(20)+multi(10)+topic(~5)"
    ))

    # 0 questions with tech + thread + long body (no q contribution)
    cases.append((
        _pad("Le deploy de l'API REST staging est terminé. Le CI/CD pipeline a validé.", 2000),
        "No q, all other", 5, True, True,
        "COMPLEX", 55, 75, "0q + 2000 + 4 tech + depth 5 + instr + attach"
    ))

    # 1 question + heavy tech + long body
    cases.append((
        _pad("Le deploy CI/CD API staging Docker Kubernetes. Est-ce ok?", 1500),
        "1q + heavy tech + long", 2, False, False,
        "STANDARD", 35, 50, "1q + 6 tech + 1500 chars + depth 2"
    ))

    return cases[:30]


# ============================================================================
# 6. BOUNDARY — Tech keywords (30 cases)
# ============================================================================

def _gen_boundary_tech():
    """30 cases: test 0, 1, 2, 3, 4+ unique tech keyword counts."""
    cases = []

    # --- 0 tech -> tech_score=0 ---
    cases.append((
        "Bonjour, merci pour votre message. " + _repeat("x ", 280),
        "No tech", 0, False, False,
        "SIMPLE", 0, 10, "0 tech keywords -> tech(0)"
    ))

    cases.append((
        "The meeting is scheduled for Tuesday. " + _repeat("x ", 278),
        "No tech EN", 0, False, False,
        "SIMPLE", 0, 10, "0 tech keywords (EN) -> tech(0)"
    ))

    # --- 1 tech -> tech_score=40, *0.15=6 ---
    cases.append((
        "Le deploy est prévu pour demain. " + _repeat("x ", 283),
        "1 tech", 0, False, False,
        "SIMPLE", 5, 15, "1 tech (deploy) -> tech(6)+body(5)=11"
    ))

    cases.append((
        "There's a bug in the login page. " + _repeat("x ", 283),
        "1 tech EN", 0, False, False,
        "SIMPLE", 5, 15, "1 tech (bug) -> tech(6)"
    ))

    cases.append((
        "Le contrat doit être renouvelé. " + _repeat("x ", 283),
        "1 tech contrat", 0, False, False,
        "SIMPLE", 5, 15, "1 tech (contrat) -> tech(6)"
    ))

    # --- 2 tech -> tech_score=70, *0.15=10 ---
    cases.append((
        "Le deploy en staging est terminé. " + _repeat("x ", 280),
        "2 tech", 0, False, False,
        "SIMPLE", 10, 20, "2 tech (deploy, staging) -> tech(10)+body(5)=15"
    ))

    cases.append((
        "The API returns a JSON error. " + _repeat("x ", 283),
        "2 tech API JSON", 0, False, False,
        "SIMPLE", 10, 20, "2 tech (API, JSON) -> tech(10)"
    ))

    # --- 3 tech -> tech_score=70, *0.15=10 (same as 2) ---
    cases.append((
        "Le deploy en staging de l'API est ok. " + _repeat("x ", 278),
        "3 tech", 0, False, False,
        "SIMPLE", 10, 20, "3 tech (deploy, staging, API) -> tech(10), same as 2"
    ))

    cases.append((
        "The SQL migration broke the schema. " + _repeat("x ", 280),
        "3 tech SQL migration schema", 0, False, False,
        "SIMPLE", 10, 20, "3 tech (SQL, migration, schema) -> tech(10)"
    ))

    # --- 4 tech -> tech_score=100, *0.15=15 ---
    cases.append((
        "Le deploy en staging de l'API REST est ok. " + _repeat("x ", 275),
        "4 tech", 0, False, False,
        "SIMPLE", 15, 25, "4 tech (deploy, staging, API, REST) -> tech(15)+body(5)=20"
    ))

    cases.append((
        "The SQL migration broke the database schema endpoint. " + _repeat("x ", 270),
        "5 tech", 0, False, False,
        "SIMPLE", 15, 25, "5 tech (SQL, migration, database, schema, endpoint) -> tech(15)"
    ))

    # --- 4 tech + 1 question -> tech(15)+q(7)+body(5)=27 -> SIMPLE ---
    cases.append((
        "Le deploy API staging CI/CD est ok? " + _repeat("x ", 278),
        "4 tech + 1q", 0, False, False,
        "SIMPLE", 22, 32, "4 tech + 1q -> tech(15)+q(7)+body(5)=27"
    ))

    # --- 4 tech + 3 questions -> int truncation may give 49 -> STANDARD ---
    cases.append((
        "Le deploy API staging CI/CD est ok? Quand? Pourquoi? " + _repeat("x ", 265),
        "4 tech + 3q", 0, False, False,
        "STANDARD", 45, 52, "4 tech + 3q -> int truncation may give 49"
    ))

    # --- 4 tech + instructions -> int truncation gives 29 -> SIMPLE ---
    cases.append((
        "Le deploy CI/CD de l'API en staging. " + _repeat("x ", 278),
        "4 tech + instr", 0, True, False,
        "STANDARD", 24, 34, "4 tech + instr -> int truncation may give 29"
    ))

    # --- 4 tech + thread depth 5 -> int truncation gives 29 -> SIMPLE ---
    cases.append((
        "Le deploy CI/CD de l'API en staging. " + _repeat("x ", 278),
        "4 tech + depth 5", 5, False, False,
        "SIMPLE", 25, 32, "4 tech + depth 5 -> int truncation may give 29"
    ))

    # --- Different tech categories ---
    cases.append((
        "Le contrat SLA et la conformité RGPD. Le DPO demande une DPIA. " + _repeat("x ", 255),
        "Legal tech", 0, False, False,
        "SIMPLE", 15, 25, "4+ legal tech (contrat, SLA, RGPD, DPO, DPIA) -> tech(15)"
    ))

    cases.append((
        "Le sprint est en cours. L'équipe utilise Jira et Confluence. Pull request ouvert. " + _repeat("x ", 245),
        "Agile tech", 0, False, False,
        "SIMPLE", 15, 25, "4+ agile tech (sprint, Jira, Confluence, pull request) -> tech(15)"
    ))

    cases.append((
        "Docker et Kubernetes sont configurés sur AWS avec Terraform. " + _repeat("x ", 265),
        "DevOps tech", 0, False, False,
        "SIMPLE", 15, 25, "4 DevOps tech (Docker, Kubernetes, AWS, Terraform) -> tech(15)"
    ))

    cases.append((
        "Le debug montre un crash avec un stack trace et une exception. " + _repeat("x ", 265),
        "Error tech", 0, False, False,
        "SIMPLE", 15, 25, "4 error tech (debug, crash, stack trace, exception) -> tech(15)"
    ))

    # --- Repeated same keyword (should count as 1 unique) ---
    cases.append((
        "Le deploy est fait. Le deploy est validé. Le deploy est confirmé. " + _repeat("x ", 265),
        "Repeated deploy", 0, False, False,
        "SIMPLE", 5, 15, "Same keyword repeated (deploy x3) -> 1 unique -> tech(6)"
    ))

    # --- Tech keywords in subject only ---
    cases.append((
        _repeat("x ", 300),
        "Deploy API staging CI/CD", 0, False, False,
        "SIMPLE", 15, 25, "4 tech in subject only -> tech(15)"
    ))

    # --- Case insensitive ---
    cases.append((
        "api rest json sql " + _repeat("x ", 290),
        "lowercase tech", 0, False, False,
        "SIMPLE", 15, 25, "4 tech lowercase -> tech(15)"
    ))

    # --- Exactly 4 unique keywords ---
    cases.append((
        "Le deploy de l'API en staging avec rollback automatique. " + _repeat("x ", 265),
        "Exactly 4 unique", 0, False, False,
        "SIMPLE", 15, 25, "Exactly 4 unique tech -> tech(15)"
    ))

    # --- 4 tech + 2q + depth 2 -> tech(15)+q(14)+thread(4)+body(5)=38 -> STANDARD ---
    cases.append((
        "Le deploy API est ok? Le staging fonctionne? " + _repeat("x ", 275),
        "4t + 2q + d2", 2, False, False,
        "STANDARD", 33, 43, "4 tech + 2q + depth 2 -> tech(15)+q(14)+body(5)+thread(4)=38"
    ))

    # --- 4 tech + body 2000 + instr -> tech(15)+body(20)+instr(10)=45 -> STANDARD ---
    cases.append((
        "Le deploy CI/CD API staging " + _repeat("x ", 985),
        "4t + long + instr", 0, True, False,
        "STANDARD", 40, 50, "4 tech + 2000 chars + instr -> tech(15)+body(20)+instr(10)=45"
    ))

    # --- No tech, max everything else ---
    cases.append((
        _pad("Est-ce ok? Quand? Pourquoi?", 2000),
        "No tech, max other", 5, True, True,
        "COMPLEX", 60, 80, "0 tech + 2000 chars + 3q + depth 5 + instr + attach -> body(20)+q(20)+multi(10)+thread(10)+instr(10)+attach(5)=75"
    ))

    # --- 10+ tech keywords (confirms ceiling at 4+) ---
    cases.append((
        "Le deploy CI/CD API REST staging Docker Kubernetes Terraform AWS SQL " + _repeat("x ", 240),
        "10+ tech keywords", 0, False, False,
        "SIMPLE", 15, 25, "10+ unique tech -> tech_score=100, *0.15=15, same as 4"
    ))

    # --- 1 tech with SLA ---
    cases.append((
        "We need to check the SLA terms. " + _repeat("x ", 283),
        "1 tech SLA", 0, False, False,
        "SIMPLE", 5, 15, "1 tech (SLA) -> tech(6)"
    ))

    # 2 tech + 2q -> tech(10)+q(14)+body(5)=29 -> SIMPLE
    cases.append((
        "Le deploy en staging est ok? Quand? " + _repeat("x ", 278),
        "2 tech + 2q", 0, False, False,
        "SIMPLE", 25, 32, "2 tech (deploy, staging) + 2q -> tech(10)+q(14)+body(5)=29"
    ))

    # 3 tech + attach + thread -> tech(10)+attach(5)+thread(4)+body(5)=24
    cases.append((
        "Le deploy API en staging est ok. " + _repeat("x ", 280),
        "3 tech + attach + thread", 2, False, True,
        "SIMPLE", 20, 30, "3 tech + attach + thread 2 -> tech(10)+attach(5)+thread(4)+body(5)=24"
    ))

    return cases[:30]


# ============================================================================
# 7. THREAD DEPTH — Variations (30 cases)
# ============================================================================

def _gen_thread_depth_variations():
    """30 cases: test depth 0, 1, 2, 3, 4, 5, 6 with otherwise identical emails.

    thread_score: 0->0, 1->20, 2-3->40, 4->60, 5+->100
    *0.10 = 0, 2, 4, 4, 6, 10, 10
    """
    cases = []

    # Base: 3 questions + 1200 chars + 3 tech + 4 topics + list -> q(20)+multi(10)+body(12)+tech(10.5)+topic(10) = 62
    base_body = _pad(
        "Bonjour,\n\nConcernant le deploy en staging:\n\n"
        "1. Est-ce que c'est prêt pour la production?\n"
        "2. Quand est la livraison prévue?\n"
        "3. Qui valide le deploy?\n\n"
        "Merci de me répondre rapidement.", 1200
    )

    for depth in [0, 1, 2, 3, 4, 5, 6]:
        thread_contrib = {0: 0, 1: 2, 2: 4, 3: 4, 4: 6, 5: 10, 6: 10}[depth]
        total_approx = 62 + thread_contrib
        cases.append((
            base_body, "Thread test", depth, False, False,
            "COMPLEX", max(50, total_approx - 5), min(100, total_approx + 5),
            f"3q+2tech+1200chars + depth={depth} -> thread({thread_contrib}), total~{total_approx}"
        ))

    # Same but with no questions (pure body + tech)
    # body 2000 + 4 tech -> body(20)+tech(15) = 35
    base_body2 = _pad("Le deploy CI/CD API staging est opérationnel.", 2000)

    for depth in [0, 1, 2, 3, 4, 5, 6]:
        thread_contrib = {0: 0, 1: 2, 2: 4, 3: 4, 4: 6, 5: 10, 6: 10}[depth]
        total_approx = 35 + thread_contrib
        tier = _tier(total_approx)
        cases.append((
            base_body2, "Thread no q", depth, False, False,
            tier, max(0, total_approx - 5), min(100, total_approx + 5),
            f"4tech+2000chars + depth={depth} -> thread({thread_contrib}), total~{total_approx}"
        ))

    # High depth alone with minimal content (600 chars -> body(5))
    base_minimal = _repeat("x ", 300)

    for depth in [0, 3, 5, 6]:
        thread_contrib = {0: 0, 3: 4, 5: 10, 6: 10}[depth]
        total_approx = 5 + thread_contrib
        cases.append((
            base_minimal, "Minimal + depth", depth, False, False,
            "SIMPLE", max(0, total_approx - 3), min(29, total_approx + 5),
            f"600 chars only + depth={depth} -> thread({thread_contrib}), total~{total_approx}"
        ))

    # Thread depth with instructions and attachments
    for depth in [0, 2, 4, 5]:
        thread_contrib = {0: 0, 2: 4, 4: 6, 5: 10}[depth]
        total_approx = 5 + 10 + 5 + thread_contrib
        tier = _tier(total_approx, has_instructions=True)
        cases.append((
            base_minimal, "Depth + instr + attach", depth, True, True,
            tier, max(0, total_approx - 5), min(100, total_approx + 5),
            f"600 chars + instr + attach + depth={depth} -> total~{total_approx}"
        ))

    # Depth 0 vs 5 with COMPLEX baseline (body 1200 + 3q + 4 tech)
    complex_base = _pad(
        "Le deploy CI/CD API staging est ok? Quand le merge? Pourquoi le bug? "
        "Le schema de la database endpoint doit être corrigé.", 1200
    )

    cases.append((
        complex_base, "Complex + d0", 0, False, False,
        "COMPLEX", 50, 68, "3q+4tech+1200 + depth=0"
    ))

    cases.append((
        complex_base, "Complex + d5", 5, False, False,
        "COMPLEX", 60, 78, "3q+4tech+1200 + depth=5"
    ))

    # Extra: depth with 2q + 1500 body
    base_2q = _pad("Est-ce ok? Quand sera-ce prêt? Le deploy en staging fonctionne.", 1500)
    for depth in [0, 1, 3, 4, 5, 6]:
        thread_contrib = {0: 0, 1: 2, 3: 4, 4: 6, 5: 10, 6: 10}[depth]
        total_approx = 14 + 15 + 6 + thread_contrib  # q(14) + body(15) + tech(6)
        tier = _tier(total_approx)
        cases.append((
            base_2q, f"2q+long+tech+d{depth}", depth, False, False,
            tier, max(0, total_approx - 5), min(100, total_approx + 5),
            f"2q+1tech+1500chars + depth={depth} -> total~{total_approx}"
        ))

    return cases[:30]


# ============================================================================
# 8. TOPIC VARIATIONS (30 cases)
# ============================================================================

def _gen_topic_variations():
    """30 cases: test 0, 1, 2, 3+ double-newline separators and trigger phrases.

    topic_count = max(1, min(paragraphs, 5)) where paragraphs = count of _TOPIC_SEPARATORS matches
    topic_score: 1->0, 2->50(*0.10=5), 3+->100(*0.10=10)
    """
    cases = []

    # --- No separators (topic_count=1, topic_score=0) ---
    cases.append((
        "Bonjour, voici mon message sans séparation de paragraphe. " + _repeat("x ", 265),
        "No topics", 0, False, False,
        "SIMPLE", 0, 10, "0 separators -> topic_count=1 -> topic(0)"
    ))

    # --- 1 double newline -> paragraphs=1, topic_count=max(1,1)=1, topic_score=0 ---
    cases.append((
        "Premier." + _repeat("x ", 140) + "\n\nDeuxième." + _repeat("x ", 140),
        "1 separator", 0, False, False,
        "SIMPLE", 0, 10, "1 double-newline -> paragraphs=1, topic_count=1 -> topic(0)"
    ))

    # --- 2 double newlines -> paragraphs=2, topic_count=2, topic_score=50*0.10=5 ---
    cases.append((
        "Sujet A." + _repeat("x ", 100) + "\n\nSujet B." + _repeat("x ", 100) + "\n\nSujet C." + _repeat("x ", 100),
        "2 separators", 0, False, False,
        "SIMPLE", 0, 15, "2 double-newlines -> paragraphs=2, topic_count=2 -> topic(5)"
    ))

    # --- 3 double newlines -> paragraphs=3, topic_count=3, topic_score=100*0.10=10 ---
    cases.append((
        "A." + _repeat("x ", 80) + "\n\nB." + _repeat("x ", 80) + "\n\nC." + _repeat("x ", 80) + "\n\nD." + _repeat("x ", 80),
        "3 separators", 0, False, False,
        "SIMPLE", 5, 20, "3 double-newlines -> paragraphs=3, topic_count=3 -> topic(10)"
    ))

    # --- Topic phrases ---
    cases.append((
        "Premier." + _repeat("x ", 140) + "\npar ailleurs, deuxième." + _repeat("x ", 140),
        "Par ailleurs", 0, False, False,
        "SIMPLE", 0, 10, "'par ailleurs' at line start -> paragraphs=1, topic_count=1"
    ))

    cases.append((
        "Premier." + _repeat("x ", 100) + "\n\npar ailleurs, deuxième." + _repeat("x ", 100) + "\n\ntroisième." + _repeat("x ", 100),
        "Par ailleurs + \\n\\n", 0, False, False,
        "SIMPLE", 5, 20, "'par ailleurs' + double newlines -> paragraphs=3, topic(10)"
    ))

    cases.append((
        "First." + _repeat("x ", 130) + "\nregarding the second point." + _repeat("x ", 130),
        "Regarding", 0, False, False,
        "SIMPLE", 0, 10, "'regarding' at line start"
    ))

    cases.append((
        "Premier." + _repeat("x ", 140) + "\nd'autre part, deuxième." + _repeat("x ", 140),
        "D'autre part", 0, False, False,
        "SIMPLE", 0, 10, "'d'autre part' at line start"
    ))

    cases.append((
        "Premier." + _repeat("x ", 140) + "\nconcernant le deuxième point." + _repeat("x ", 140),
        "Concernant", 0, False, False,
        "SIMPLE", 0, 10, "'concernant' at line start"
    ))

    cases.append((
        "First." + _repeat("x ", 140) + "\nadditionally, second point." + _repeat("x ", 140),
        "Additionally", 0, False, False,
        "SIMPLE", 0, 10, "'additionally' at line start"
    ))

    cases.append((
        "First." + _repeat("x ", 140) + "\nalso, second point." + _repeat("x ", 140),
        "Also", 0, False, False,
        "SIMPLE", 0, 10, "'also' at line start"
    ))

    cases.append((
        "Premier." + _repeat("x ", 140) + "\nde plus, deuxième." + _repeat("x ", 140),
        "De plus", 0, False, False,
        "SIMPLE", 0, 10, "'de plus' at line start"
    ))

    # --- Multiple topic phrases ---
    cases.append((
        "Premier." + _repeat("x ", 60) + "\npar ailleurs, deux." + _repeat("x ", 60) + "\nconcernant trois." + _repeat("x ", 60) + "\nde plus, quatre." + _repeat("x ", 60),
        "3 topic phrases", 0, False, False,
        "SIMPLE", 5, 20, "3 topic phrases -> paragraphs=3 -> topic(10)"
    ))

    # --- Mixed separators ---
    cases.append((
        "Premier." + _repeat("x ", 60) + "\n\nDeuxième." + _repeat("x ", 60) + "\npar ailleurs, trois." + _repeat("x ", 60) + "\n\nQuatre." + _repeat("x ", 60),
        "Mixed separators", 0, False, False,
        "SIMPLE", 5, 20, "2 \\n\\n + 1 phrase -> paragraphs=3+ -> topic(10)"
    ))

    # --- Topic score + questions to push toward COMPLEX ---
    # 3 topics(10) + 3q(20) + multi(10) + body(~5) = 45 -> STANDARD
    cases.append((
        "Premier.\n\nEst-ce ok?\n\nDeuxième.\n\nQuand? Pourquoi?" + _repeat("x ", 220),
        "Topics + 3q", 0, False, False,
        "STANDARD", 38, 50, "3+ topics + 3q -> topic(10)+q(20)+multi(10)+body(~5)=45"
    ))

    # 3 topics + 4 tech + 3 questions -> COMPLEX
    cases.append((
        _pad(
            "Le deploy est ok.\n\nPar ailleurs, le CI/CD fonctionne en staging.\n\n"
            "Concernant l'API, est-ce prêt? Quand le merge? Pourquoi le bug?",
            1200
        ),
        "Full topics + tech + q", 0, False, False,
        "COMPLEX", 55, 78, "3+ topics + 4 tech + 3q + 1200 chars"
    ))

    # --- 5+ separators ---
    cases.append((
        "A." + _repeat("x ", 50) + "\n\nB." + _repeat("x ", 50) + "\n\nC." + _repeat("x ", 50) + "\n\nD." + _repeat("x ", 50) + "\n\nE." + _repeat("x ", 50) + "\n\nF." + _repeat("x ", 50),
        "5 separators", 0, False, False,
        "SIMPLE", 5, 20, "5 double-newlines -> paragraphs=5, topic_count=5 -> topic(10)"
    ))

    # --- 0 topics, high everything else ---
    cases.append((
        _pad("Le deploy CI/CD API staging. Est-ce ok? Quand? Pourquoi?", 1200),
        "No topics, high other", 5, True, True,
        "COMPLEX", 65, 90, "0 topics + 4tech + 3q + 1200chars + depth5 + instr + attach"
    ))

    # --- Topics in very short body ---
    cases.append((
        "A.\n\nB.\n\nC.",
        "Short + topics", 0, False, False,
        "SIMPLE", 0, 15, "3 separators but body < 200 -> topic(10) but body(0)"
    ))

    # --- No topic separator, long body ---
    cases.append((
        _repeat("x ", 1000),
        "Long no topics", 0, False, False,
        "SIMPLE", 15, 25, "2000 chars, no separators -> body(20)+topic(0)=20"
    ))

    # --- Whitespace between newlines ---
    cases.append((
        "A." + _repeat("x ", 100) + "\n   \nB." + _repeat("x ", 100) + "\n\t\nC." + _repeat("x ", 100),
        "Whitespace separators", 0, False, False,
        "SIMPLE", 0, 15, "\\n + spaces/tabs + \\n -> matches \\n\\s*\\n"
    ))

    # --- Multiple consecutive empty lines ---
    cases.append((
        "A." + _repeat("x ", 80) + "\n\n\n\nB." + _repeat("x ", 80) + "\n\n\n\n\nC." + _repeat("x ", 80),
        "Multiple empty lines", 0, False, False,
        "SIMPLE", 0, 20, "Multiple consecutive empty lines"
    ))

    # --- 4 separators ---
    cases.append((
        "A." + _repeat("x ", 60) + "\n\nB." + _repeat("x ", 60) + "\n\nC." + _repeat("x ", 60) + "\n\nD." + _repeat("x ", 60) + "\n\nE." + _repeat("x ", 60),
        "4 separators", 0, False, False,
        "SIMPLE", 5, 20, "4 double-newlines -> paragraphs=4 -> topic(10)"
    ))

    # --- Topic + instructions ---
    cases.append((
        "A." + _repeat("x ", 100) + "\n\nB." + _repeat("x ", 100) + "\n\nC." + _repeat("x ", 100),
        "Topics + instr", 0, True, False,
        "STANDARD", 15, 25, "2+ topics + instr -> topic(5-10)+instr(10)+body(~5)"
    ))

    # --- Topic + attachments ---
    cases.append((
        "A." + _repeat("x ", 100) + "\n\nB." + _repeat("x ", 100) + "\n\nC." + _repeat("x ", 100) + "\n\nD." + _repeat("x ", 100),
        "Topics + attach", 0, False, True,
        "SIMPLE", 10, 25, "3+ topics + attach -> topic(10)+attach(5)+body(~5)"
    ))

    # --- Single separator with phrase ---
    cases.append((
        "Context." + _repeat("x ", 140) + "\n\nconcernant le second sujet." + _repeat("x ", 120),
        "1 sep + concernant", 0, False, False,
        "SIMPLE", 0, 15, "1 \\n\\n + 'concernant' -> paragraphs=2 -> topic(5)"
    ))

    # --- Topic + 2q + tech at boundary ---
    cases.append((
        "Le deploy est terminé.\n\nPar ailleurs, le staging fonctionne.\n\nEst-ce qu'on peut merger l'API?" + _repeat("x ", 225),
        "2 topics + 1q + tech", 2, False, False,
        "STANDARD", 30, 48, "2+ topics + 1q + tech + thread 2"
    ))

    # 2 topics + 2q -> topic(5)+q(14)+body(~5)=24
    cases.append((
        "Premier sujet." + _repeat("x ", 120) + "\n\nDeuxième sujet." + _repeat("x ", 120) + "\n\nEst-ce ok? Quand?",
        "2 topics + 2q", 0, False, False,
        "SIMPLE", 20, 30, "2 topics + 2q -> topic(5)+q(14)+body(~5)=24"
    ))

    # 3+ topics + instr + thread -> topic(10)+instr(10)+thread(4)+body(~5)=29
    cases.append((
        "A." + _repeat("x ", 80) + "\n\nB." + _repeat("x ", 80) + "\n\nC." + _repeat("x ", 80) + "\n\nD." + _repeat("x ", 80),
        "Topics + instr + thread", 2, True, False,
        "STANDARD", 24, 34, "3+ topics + instr + thread 2"
    ))

    # 0 topics + 0 everything (baseline)
    cases.append((
        "Simple text without any separators or special content." + _repeat("x ", 265),
        "Zero topics zero all", 0, False, False,
        "SIMPLE", 0, 10, "No topics, no signals at all"
    ))

    return cases[:30]


# ============================================================================
# 9. LIST DETECTION (20 cases)
# ============================================================================

def _gen_list_detection():
    """20 cases: numbered "1. ", bullet "- ", alpha "a) ", no lists.

    multiple_requests = has_lists or questions >= 3
    multi_score = 100 if multiple_requests else 0 -> *0.10=10
    """
    cases = []

    # --- No lists, 0 questions -> multi_score=0 ---
    cases.append((
        "Bonjour, merci pour le retour. " + _repeat("x ", 283),
        "No list", 0, False, False,
        "SIMPLE", 0, 10, "No list items, no 3q -> multi(0)"
    ))

    # --- Numbered list "1. " -> has_lists=True -> multi(10) ---
    cases.append((
        "Points:\n1. Premier point\n2. Deuxième point\n3. Troisième point\n" + _repeat("x ", 250),
        "Numbered list", 0, False, False,
        "SIMPLE", 5, 20, "Numbered list -> has_lists=True -> multi(10)"
    ))

    # --- Numbered list "1) " ---
    cases.append((
        "Actions:\n1) Vérifier le système\n2) Tester la connexion\n" + _repeat("x ", 265),
        "Numbered paren list", 0, False, False,
        "SIMPLE", 5, 20, "Numbered list (1) 2)) -> multi(10)"
    ))

    # --- Bullet list "- " ---
    cases.append((
        "Éléments:\n- Premier\n- Deuxième\n- Troisième\n" + _repeat("x ", 260),
        "Bullet list dash", 0, False, False,
        "SIMPLE", 5, 20, "Bullet list (- ) -> multi(10)"
    ))

    # --- Bullet list "* " ---
    cases.append((
        "Notes:\n* Point A\n* Point B\n* Point C\n" + _repeat("x ", 260),
        "Bullet list star", 0, False, False,
        "SIMPLE", 5, 20, "Bullet list (* ) -> multi(10)"
    ))

    # --- Alpha list "a) " ---
    cases.append((
        "Options:\na) Option A\nb) Option B\nc) Option C\n" + _repeat("x ", 260),
        "Alpha list", 0, False, False,
        "SIMPLE", 5, 20, "Alpha list (a) b) c)) -> multi(10)"
    ))

    # --- Alpha list "a. " ---
    cases.append((
        "Steps:\na. First step\nb. Second step\n" + _repeat("x ", 270),
        "Alpha dot list", 0, False, False,
        "SIMPLE", 5, 20, "Alpha list (a. b.) -> multi(10)"
    ))

    # --- List + 3 questions -> multi from both triggers ---
    # q(20)+multi(10)+body(~5) = 35 -> STANDARD
    cases.append((
        "Points:\n1. Premier\n2. Deuxième\nEst-ce ok? Quand? Pourquoi?" + _repeat("x ", 230),
        "List + 3q", 0, False, False,
        "STANDARD", 30, 42, "List + 3q -> multi(10)+q(20)+body(~5)=35"
    ))

    # --- No list but 3 questions -> multi via questions ---
    cases.append((
        "Est-ce ok? Quand sera-ce prêt? Pourquoi le retard?" + _repeat("x ", 255),
        "3q no list", 0, False, False,
        "STANDARD", 30, 42, "No list but 3q -> multi(10) via question count"
    ))

    # --- List with indentation ---
    cases.append((
        "Checklist:\n  1. Vérifier\n  2. Valider\n  3. Confirmer\n" + _repeat("x ", 255),
        "Indented list", 0, False, False,
        "SIMPLE", 5, 20, "Indented numbered list -> multi(10)"
    ))

    # --- Mixed list types ---
    cases.append((
        "Actions:\n1. Premier\n- Sous-point\na) Alternative\n" + _repeat("x ", 255),
        "Mixed list types", 0, False, False,
        "SIMPLE", 5, 20, "Mixed list types -> has_lists=True -> multi(10)"
    ))

    # --- Dash at start of body ---
    cases.append((
        "- Premier point\n- Deuxième point\nMerci " + _repeat("x ", 275),
        "Dash at start", 0, False, False,
        "SIMPLE", 5, 20, "Dash at body start -> multi(10)"
    ))

    # --- "1. " at very start of body ---
    cases.append((
        "1. Premier\n2. Deuxième\n" + _repeat("x ", 280),
        "List at start", 0, False, False,
        "SIMPLE", 5, 20, "List at very start of body -> multi(10)"
    ))

    # --- Not a list (1.0 without space) ---
    cases.append((
        "Version 1.0 est sortie. Le prix est de 2.50 euros.\n" + _repeat("x ", 265),
        "Not a list (1.0)", 0, False, False,
        "SIMPLE", 0, 10, "1.0 and 2.50 -> not a list -> multi(0)"
    ))

    # --- List + tech + 3q for COMPLEX (with padding) ---
    cases.append((
        _pad(
            "Actions deploy:\n1. Vérifier le CI/CD\n2. Tester le staging\n3. Merger la branche\n"
            "Est-ce ok? Quand? Pourquoi le retard de l'API? "
            "Le schema endpoint doit être vérifié.", 1200
        ),
        "List + tech + 3q", 0, False, False,
        "COMPLEX", 50, 72, "List + 4+ tech + 3q + 1200 chars"
    ))

    # --- List only + 600 chars ---
    cases.append((
        "Points:\n- A\n- B\n" + _repeat("x ", 290),
        "List only", 0, False, False,
        "SIMPLE", 5, 20, "List only + 600 chars -> multi(10)+body(5)=15"
    ))

    # --- 2q + list -> multi from list (2q doesn't trigger multi) ---
    cases.append((
        "Actions:\n1. Premier\n2. Deuxième\nEst-ce ok? Quand?" + _repeat("x ", 250),
        "List + 2q", 0, False, False,
        "SIMPLE", 25, 35, "List + 2q -> multi(10)+q(14)+body(~5)=29"
    ))

    # --- 2q, no list -> multi=0 ---
    cases.append((
        "Est-ce ok? Quand sera-ce prêt? " + _repeat("x ", 280),
        "2q no list", 0, False, False,
        "SIMPLE", 15, 25, "2q, no list -> multi(0)+q(14)+body(5)=19"
    ))

    # --- High numbered list ---
    cases.append((
        "Étapes:\n10. Finaliser\n11. Implémenter\n" + _repeat("x ", 260),
        "High numbered list", 0, False, False,
        "SIMPLE", 5, 20, "High numbered list (10. 11.) -> multi(10)"
    ))

    # --- Single list item ---
    cases.append((
        "Todo:\n1. Seul item à faire\n" + _repeat("x ", 280),
        "Single list item", 0, False, False,
        "SIMPLE", 5, 20, "Single list item -> multi(10)"
    ))

    return cases[:20]


# ============================================================================
# 10. ATTACHMENTS (20 cases)
# ============================================================================

def _gen_attachments():
    """20 cases: with/without attachments, verify +5 pts contribution.

    attach_score = 100 if has_attachments else 0. *0.05 = 5 or 0.
    """
    cases = []

    base = _repeat("x ", 300)  # 600 chars -> body(5)

    # --- Without attachments ---
    cases.append((
        base, "No attach", 0, False, False,
        "SIMPLE", 0, 10, "No attachments -> attach(0)"
    ))

    cases.append((
        base, "No attach v2", 2, False, False,
        "SIMPLE", 5, 15, "No attach + depth 2 -> body(5)+thread(4)=9"
    ))

    # --- With attachments -> +5 points ---
    cases.append((
        base, "With attach", 0, False, True,
        "SIMPLE", 5, 15, "With attachments -> attach(5)+body(5)=10"
    ))

    cases.append((
        base, "With attach v2", 2, False, True,
        "SIMPLE", 10, 20, "With attach + depth 2 -> attach(5)+body(5)+thread(4)=14"
    ))

    # --- Attachments at the tipping point ---
    # Base: 3q+3tech+1200 chars = q(20)+multi(10)+tech(10)+body(12) = 52
    # Without attach=52, with attach=57
    cases.append((
        _pad("Le deploy en staging est ok? Quand le merge? Pourquoi le CI/CD échoue?", 1200),
        "Attach tipping NO", 0, False, False,
        "COMPLEX", 48, 58, "3q+3tech+1200 = ~52 without attach"
    ))

    cases.append((
        _pad("Le deploy en staging est ok? Quand le merge? Pourquoi le CI/CD échoue?", 1200),
        "Attach tipping YES", 0, False, True,
        "COMPLEX", 52, 62, "3q+3tech+1200+attach = ~57 with attach"
    ))

    # --- Attachments + instructions ---
    cases.append((
        base, "Attach + instr", 0, True, True,
        "STANDARD", 15, 25, "Attach(5) + instr(10) + body(5) = 20"
    ))

    # --- Attachments + long body ---
    cases.append((
        _repeat("x ", 1000), "Attach + long", 0, False, True,
        "SIMPLE", 20, 30, "Attach(5) + body(20) = 25"
    ))

    # --- Attachments with questions ---
    cases.append((
        base + " Est-ce ok?", "Attach + 1q", 0, False, True,
        "SIMPLE", 12, 22, "Attach(5) + q(7) + body(5) = 17"
    ))

    cases.append((
        base + " Est-ce ok? Quand?", "Attach + 2q", 0, False, True,
        "SIMPLE", 20, 30, "Attach(5) + q(14) + body(5) = 24"
    ))

    cases.append((
        base + " Est-ce ok? Quand? Pourquoi?", "Attach + 3q", 0, False, True,
        "STANDARD", 35, 48, "Attach(5) + q(20) + multi(10) + body(5) = 40"
    ))

    # --- Attachments + tech ---
    cases.append((
        "Le deploy API est en staging. " + _repeat("x ", 280),
        "Attach + tech", 0, False, True,
        "SIMPLE", 15, 25, "Attach(5) + tech(~10) + body(5) = 20"
    ))

    # --- Attachments + deep thread ---
    cases.append((
        base, "Attach + depth 5", 5, False, True,
        "SIMPLE", 15, 25, "Attach(5) + thread(10) + body(5) = 20"
    ))

    # --- Attachments + topics ---
    cases.append((
        "A." + _repeat("x ", 130) + "\n\nB." + _repeat("x ", 130) + "\n\nC." + _repeat("x ", 130),
        "Attach + 3 topics", 0, False, True,
        "SIMPLE", 15, 25, "Attach(5) + topic(10) + body(5) = 20"
    ))

    # --- Realistic attach cases ---
    cases.append((
        "Bonjour,\n\nVeuillez trouver ci-joint le rapport mensuel.\n\nCordialement",
        "Rapport mensuel", 0, False, True,
        "SIMPLE", 0, 15, "Short body + attach -> attach(5)+body(0)=5"
    ))

    cases.append((
        "Hi, please see the attached document for your review.",
        "Document review", 0, False, True,
        "SIMPLE", 0, 15, "Short body + attach -> attach(5)+body(0)=5"
    ))

    cases.append((
        "Ci-joint les 3 fichiers demandés. " + _repeat("x ", 280),
        "3 files attached", 0, False, True,
        "SIMPLE", 5, 15, "Attach(5) + body(5) = 10"
    ))

    # --- Attach + moderate all signals ---
    cases.append((
        _pad("Le deploy en staging est ok. Est-ce que le CI/CD API fonctionne?", 1000),
        "Attach + moderate", 2, True, True,
        "COMPLEX", 42, 58, "1q + 4 tech + 1000 chars + depth 2 + instr + attach"
    ))

    # --- No attach + similar signals for comparison ---
    cases.append((
        _pad("Le deploy en staging est ok. Est-ce que le CI/CD API fonctionne?", 1000),
        "No attach same", 2, True, False,
        "STANDARD", 38, 52, "Same as above but no attach"
    ))

    # Attach with long body + 2q
    cases.append((
        _repeat("x ", 750) + " Est-ce ok? Quand sera-ce prêt?",
        "Attach + long + 2q", 0, False, True,
        "STANDARD", 30, 42, "Attach(5) + body(15) + q(14) = 34"
    ))

    return cases[:20]


# ============================================================================
# 11. MIXED LANGUAGE (30 cases)
# ============================================================================

def _gen_mixed_language():
    """30 cases: French questions + English tech, or vice versa."""
    cases = []

    # FR questions + EN tech keywords (padded to 1200+ chars for COMPLEX)
    cases.append((
        _pad(
            "Bonjour,\n\nEst-ce que le deploy en staging est ok? "
            "Quand est-ce que le CI/CD pipeline sera prêt pour la production? "
            "Pourquoi le Docker container ne démarre pas?\n\n"
            "Le Kubernetes cluster semble avoir un problème avec l'API endpoint.", 1200
        ),
        "Deploy staging - Questions", 1, False, False,
        "COMPLEX", 55, 85, "FR questions + EN tech (deploy, staging, CI/CD, Docker, Kubernetes, API, endpoint, production)"
    ))

    cases.append((
        _pad(
            "Pouvez-vous vérifier l'API REST endpoint? "
            "Est-ce que le JSON schema est correct pour le staging? "
            "Comment on gère la migration SQL de la database?", 1200
        ),
        "API schema questions", 0, False, False,
        "COMPLEX", 55, 88, "FR interrogative + EN tech (API, REST, endpoint, JSON, schema, staging, migration, SQL, database)"
    ))

    cases.append((
        _pad(
            "Combien de bugs sont ouverts dans Jira pour ce sprint? "
            "Est-ce que le pull request review est confirmé pour le CI/CD? "
            "Quand est le prochain deploy en staging via le pipeline?", 1200
        ),
        "Sprint bugs", 1, False, False,
        "COMPLEX", 55, 88, "FR questions + EN agile tech (bug, Jira, sprint, pull request, CI/CD, deploy, staging)"
    ))

    # EN questions + FR business context
    cases.append((
        _pad(
            "Can you check the contrat with the SLA clause for the API? "
            "When will the facturation module be deployed in staging? "
            "How do we handle the résiliation process for the endpoint?", 1200
        ),
        "Contract SLA questions", 0, False, False,
        "COMPLEX", 55, 85, "EN questions + FR business tech (contrat, SLA, facturation, résiliation, API, staging, endpoint, deploy)"
    ))

    cases.append((
        _pad(
            "What is the status of the avenant for the contrat? "
            "Do we need to update the RGPD compliance on the API endpoint? "
            "Can the DPO review the DPIA before the deploy in staging?", 1200
        ),
        "Legal compliance", 1, False, False,
        "COMPLEX", 55, 88, "EN questions + FR legal tech (avenant, contrat, RGPD, DPO, DPIA, API, endpoint, deploy, staging)"
    ))

    # Mixed within same sentence
    cases.append((
        _pad(
            "Bonjour, could you check le deploy de l'API en staging? "
            "Est-ce que the CI/CD pipeline is green for production? "
            "When est-ce que le Docker container sera prêt sur Kubernetes?", 1200
        ),
        "Mixed sentences", 0, False, False,
        "COMPLEX", 55, 88, "FR/EN mixed in same sentences + heavy tech"
    ))

    # FR body + EN subject with tech
    cases.append((
        _pad(
            "Bonjour,\n\nPouvez-vous vérifier les points suivants?\n\n"
            "1. Le serveur de staging fonctionne-t-il après le deploy?\n"
            "2. Les données de l'API sont-elles sauvegardées dans la database?\n"
            "3. Quand est la prochaine mise à jour du CI/CD?\n\n"
            "Merci de votre retour rapide.", 1200
        ),
        "Deploy staging CI/CD Docker review", 1, False, False,
        "COMPLEX", 52, 82, "FR body with 3q + EN tech in subject"
    ))

    # EN body + FR subject
    cases.append((
        _pad(
            "Hi team,\n\nI need updates on these items:\n\n"
            "1. Is the deploy to staging complete for the API?\n"
            "2. Did the database migration succeed on the endpoint?\n"
            "3. Are the Docker containers healthy on the CI/CD?\n\n"
            "Please respond by end of day.", 1200
        ),
        "Déploiement staging - Vérification", 2, False, False,
        "COMPLEX", 55, 85, "EN body with 3q + heavy tech + FR subject"
    ))

    # FR questions about EN tools
    cases.append((
        _pad(
            "Bonjour,\n\nEst-ce que Terraform est configuré pour AWS et le deploy? "
            "Quand est-ce que les Kubernetes pods seront stables en staging? "
            "Pourquoi le Docker build échoue sur le CI/CD de l'API?", 1200
        ),
        "Infrastructure questions", 0, False, False,
        "COMPLEX", 55, 88, "FR questions about EN tools (Terraform, AWS, Kubernetes, Docker, CI/CD, API, deploy, staging)"
    ))

    cases.append((
        _pad(
            "Est-ce que le GraphQL schema fonctionne sur le endpoint REST? "
            "Combien d'endpoints sont migrés dans la database SQL? "
            "Quand est-ce que l'OAuth sera en production via l'API?", 1200
        ),
        "Tech migration FR questions", 1, False, False,
        "COMPLEX", 55, 88, "FR questions + heavy tech"
    ))

    # Generate more parametric mixed cases
    _mixed_data = [
        (
            "Bonjour,\n\nIs the CI/CD pipeline ready for the API deploy? "
            "Est-ce que le staging fonctionne avec le Docker endpoint? "
            "When will the database migration be completed?",
            "Mixed CI/CD query", 0, "Mixed CI/CD FR/EN"
        ),
        (
            "Hi, est-ce que the Docker container is running on Kubernetes? "
            "Quand est le deploy prévu pour le staging de l'API? "
            "Can you check the database schema endpoint?",
            "Bilingual Docker check", 1, "Mixed Docker FR/EN"
        ),
        (
            "Bonjour, when is the pull request review for the sprint? "
            "Est-ce que le Jira backlog est priorisé pour le CI/CD? "
            "How do we handle the merge of the API branch?",
            "Mixed Agile query", 2, "Mixed Agile FR/EN"
        ),
        (
            "Hi team, est-ce que the SQL schema is correct for the database? "
            "When will the REST endpoint be ready for staging? "
            "Pouvez-vous vérifier le JSON payload de l'API?",
            "Mixed Data query", 0, "Mixed Data FR/EN"
        ),
        (
            "Bonjour, is the SLA contrat updated for the API endpoint? "
            "Est-ce que la conformité RGPD est validée par le DPO? "
            "When will the DPIA be completed for the deploy?",
            "Mixed Legal query", 1, "Mixed Legal FR/EN"
        ),
        (
            "Hi, est-ce que the Terraform config is ready for AWS deploy? "
            "When is the production rollout planned for the API? "
            "Pouvez-vous vérifier le staging endpoint sur Kubernetes?",
            "Mixed Infra query", 2, "Mixed Infra FR/EN"
        ),
        (
            "Bonjour, can you check the OAuth flow on the GraphQL endpoint? "
            "Est-ce que le merge de la branche est prêt pour le CI/CD? "
            "When will the schema migration be deployed to staging?",
            "Mixed Auth query", 0, "Mixed Auth FR/EN"
        ),
        (
            "Hi, est-ce que the rollback plan is ready for the staging deploy? "
            "Quand sera le bug fix prêt pour la production de l'API? "
            "Can you check the error on the database endpoint?",
            "Mixed Release query", 3, "Mixed Release FR/EN"
        ),
        (
            "Bonjour, is the error handling configured for the API endpoint? "
            "Est-ce que le stack trace est analysé pour le CI/CD staging? "
            "When will the exception logging be deployed to production?",
            "Mixed Debug query", 1, "Mixed Debug FR/EN"
        ),
        (
            "Hi team, est-ce que the database schema migration is tested? "
            "Quand sera le deploy Docker sur le Kubernetes cluster en staging? "
            "Can you verify the REST API endpoint performance?",
            "Mixed Perf query", 2, "Mixed Perf FR/EN"
        ),
        (
            "Bonjour, when will the Jira sprint backlog be updated? "
            "Est-ce que le pull request pour le CI/CD est prêt? "
            "How do we handle the merge conflict on the API branch?",
            "Mixed Workflow query", 0, "Mixed Workflow FR/EN"
        ),
        (
            "Hi, pouvez-vous check the contrat SLA for the RGPD compliance? "
            "When is the DPO meeting for the DPIA review of the API? "
            "Est-ce que le endpoint est conforme au KPI de facturation?",
            "Mixed Compliance query", 1, "Mixed Compliance FR/EN"
        ),
        (
            "Bonjour, is the Terraform AWS configuration ready for deploy? "
            "Est-ce que le Docker Kubernetes cluster est stable en staging? "
            "When will the SQL database endpoint migration be complete?",
            "Mixed Cloud query", 2, "Mixed Cloud FR/EN"
        ),
        (
            "Hi, est-ce que the OAuth refactor is ready for the API endpoint? "
            "Quand sera le JSON schema validated for the REST staging? "
            "Can you check the SQL database migration on the CI/CD pipeline?",
            "Mixed Refactor query", 3, "Mixed Refactor FR/EN"
        ),
        (
            "Bonjour, when is the bug fix for the exception on the endpoint? "
            "Est-ce que le stack trace error est analysé pour la production? "
            "How do we handle the rollback of the deploy in staging?",
            "Mixed Hotfix query", 1, "Mixed Hotfix FR/EN"
        ),
        (
            "Hi team, est-ce que the sprint Jira Confluence documentation is updated? "
            "Quand sera le pull request for the branch merge reviewed? "
            "Can you deploy the Docker images to the Kubernetes staging?",
            "Mixed Process query", 0, "Mixed Process FR/EN"
        ),
        (
            "Bonjour, is the GDPR audit DPO report finalized for the API? "
            "Est-ce que le database schema endpoint is secure in production? "
            "When will the deploy be completed on staging?",
            "Mixed GDPR query", 2, "Mixed GDPR FR/EN"
        ),
        (
            "Hi, pouvez-vous check the AWS Terraform config for deploy? "
            "When is the Docker Kubernetes cluster ready for the REST API? "
            "Est-ce que la SQL migration du database endpoint est testée?",
            "Mixed Multi-cloud query", 1, "Mixed Multi-cloud FR/EN"
        ),
        (
            "Bonjour, can you verify the rollback production stack trace? "
            "Est-ce que le bug database schema migration est corrigé? "
            "When will the CI/CD staging be operational for the deploy?",
            "Mixed Recovery query", 3, "Mixed Recovery FR/EN"
        ),
        (
            "Hi, est-ce que the refactor module endpoint REST API is complete? "
            "Quand sera le SQL schema Docker deploy ready in Kubernetes? "
            "Can you check the staging database migration?",
            "Mixed Architecture query", 0, "Mixed Architecture FR/EN"
        ),
    ]

    for body_raw, subj, depth, desc in _mixed_data:
        body = _pad(body_raw, 1200)
        cases.append((body, subj, depth, False, False, "COMPLEX", 50, 92, desc))

    return cases[:30]


# ============================================================================
# 12. EDGE CASES (50 cases)
# ============================================================================

def _gen_edge_cases():
    """50 cases: empty body, special chars, very long, whitespace-only, etc."""
    cases = []

    # --- Empty body ---
    cases.append(("", "", 0, False, False, "SIMPLE", 0, 5, "Empty body + empty subject"))
    cases.append(("", "Important subject", 0, False, False, "SIMPLE", 0, 5, "Empty body, content in subject"))
    cases.append(("", "Est-ce urgent?", 0, False, False, "SIMPLE", 0, 10, "Empty body, question in subject"))
    cases.append(("", "Deploy API staging bug", 0, False, False, "SIMPLE", 5, 20, "Empty body, tech keywords in subject"))

    # Empty body + 3q + tech in subject -> q(20)+multi(10)+tech(?) = 30+
    cases.append((
        "", "Est-ce que le deploy API staging fonctionne? Quand? Pourquoi?", 0, False, False,
        "STANDARD", 30, 50, "Empty body, 3q + tech in subject"
    ))

    # --- Single character ---
    cases.append((".", "Re:", 0, False, False, "SIMPLE", 0, 5, "Body is single dot"))
    cases.append(("!", "", 0, False, False, "SIMPLE", 0, 5, "Body is single exclamation"))
    cases.append(("?", "", 0, False, False, "SIMPLE", 0, 10, "Body is single question mark"))

    # --- Very short bodies ---
    cases.append(("ok", "Re: Projet", 0, False, False, "SIMPLE", 0, 5, "Body is 'ok'"))
    cases.append(("Merci", "Re: Livraison", 0, False, False, "SIMPLE", 0, 5, "Body is 'Merci'"))
    cases.append(("Oui", "Re: Confirmation", 0, False, False, "SIMPLE", 0, 5, "Body is 'Oui'"))
    cases.append(("Non", "Re: Validation", 0, False, False, "SIMPLE", 0, 5, "Body is 'Non'"))
    cases.append(("test", "test", 0, False, False, "SIMPLE", 0, 5, "Body and subject are 'test'"))
    cases.append(("D'accord, je m'en occupe.", "Re: Action", 0, False, False, "SIMPLE", 0, 5, "Short acknowledgment"))
    cases.append(("Bien reçu, merci.", "Re: Document", 0, False, False, "SIMPLE", 0, 5, "Receipt confirmation"))

    # --- Whitespace-only body ---
    cases.append(("   ", "Test", 0, False, False, "SIMPLE", 0, 5, "Body is only spaces"))
    cases.append(("\n\n\n", "Test", 0, False, False, "SIMPLE", 0, 12, "Body is only newlines"))
    cases.append(("\t\t\t", "Test", 0, False, False, "SIMPLE", 0, 5, "Body is only tabs"))
    cases.append((" \n \n \n ", "Test", 0, False, False, "SIMPLE", 0, 12, "Body is mixed whitespace"))

    # --- Very long body (5000+ chars), no signals ---
    cases.append((
        _repeat("x ", 2500), "Very long", 0, False, False,
        "SIMPLE", 15, 25, "5000 chars, no signals -> body(20)"
    ))
    cases.append((
        _repeat("x ", 5000), "Extremely long", 0, False, False,
        "SIMPLE", 15, 25, "10000 chars -> body(20), capped"
    ))

    # Very long + 3 questions
    cases.append((
        _repeat("x ", 2480) + " Est-ce ok? Quand? Pourquoi?", "Very long + 3q", 0, False, False,
        "COMPLEX", 50, 58, "5000+ chars + 3q -> body(20)+q(20)+multi(10)=50"
    ))

    # --- Special characters ---
    cases.append((
        "Café résumé naïve côté façade " + _repeat("x ", 280),
        "Accents français", 0, False, False,
        "SIMPLE", 0, 10, "French accents in body"
    ))

    cases.append((
        "Ça va très bien, merci. L'équipe est prête. " + _repeat("x ", 270),
        "Cédille + apostrophe", 0, False, False,
        "SIMPLE", 0, 10, "Cédille + smart apostrophe"
    ))

    cases.append((
        "Price: 1.500,00 \u20ac \u2014 delivery: Q2 2026 " + _repeat("x ", 268),
        "Currency + date", 0, False, False,
        "SIMPLE", 0, 10, "Euro sign + em dash"
    ))

    cases.append((
        "Great job! \U0001f44d Let's keep going! \U0001f680 " + _repeat("x ", 275),
        "Emojis", 0, False, False,
        "SIMPLE", 0, 10, "Emojis in body"
    ))

    cases.append((
        "\u2022 Point 1\n\u2022 Point 2\n\u2022 Point 3\n" + _repeat("x ", 270),
        "Unicode bullets", 0, False, False,
        "SIMPLE", 0, 15, "Unicode bullet points (not ASCII -)"
    ))

    cases.append((
        "\u00abBonjour\u00bb, a-t-il dit. \u2014 \u00abMerci\u00bb, répondit-elle. " + _repeat("x ", 265),
        "French guillemets", 0, False, False,
        "SIMPLE", 0, 10, "French quotation marks (guillemets)"
    ))

    # --- Subject-only emails ---
    cases.append((
        "", "Meeting tomorrow at 3pm - please confirm", 0, False, False,
        "SIMPLE", 0, 5, "Empty body, subject with content but no tech"
    ))

    # --- HTML-like content ---
    cases.append((
        "<html><body><p>Bonjour</p></body></html> " + _repeat("x ", 270),
        "HTML content", 0, False, False,
        "SIMPLE", 0, 10, "HTML tags in body"
    ))

    cases.append((
        "See https://api.example.com/endpoint/v2?format=json for details. " + _repeat("x ", 265),
        "URL with tech", 0, False, False,
        "SIMPLE", 21, 31, "URL containing tech words"
    ))

    # --- Signatures and forwarded markers ---
    cases.append((
        "Sounds good.\n\n--\nJohn Doe\nSenior Engineer",
        "Re: Quick update", 0, False, False,
        "SIMPLE", 0, 10, "Short body + email signature"
    ))

    cases.append((
        "---------- Forwarded message ----------\nFrom: sender@example.com\n\nOriginal content here." + _repeat("x ", 200),
        "Fwd: Original subject", 0, False, False,
        "SIMPLE", 0, 15, "Forwarded message marker"
    ))

    # --- Numbers and data ---
    cases.append((
        "Revenue: $1,234,567.89\nGrowth: +15.3%\nCAC: $42.50\nLTV: $890",
        "Monthly metrics", 0, False, False,
        "SIMPLE", 0, 10, "Body with financial data"
    ))

    # --- Code snippets ---
    cases.append((
        "def hello():\n    print('hello world')\n\nhello() " + _repeat("x ", 270),
        "Code snippet", 0, False, False,
        "SIMPLE", 0, 12, "Python code in body"
    ))

    cases.append((
        "SELECT * FROM users WHERE status = 'active' " + _repeat("x ", 270),
        "SQL query", 0, False, False,
        "SIMPLE", 5, 15, "SQL query in body -> tech(SQL)"
    ))

    # --- Repeated punctuation ---
    cases.append(("..." + _repeat("x ", 297), "...", 0, False, False, "SIMPLE", 0, 5, "Body starts with ellipsis"))
    cases.append(("!!!!!!!!!! " + _repeat("x ", 293), "!!!", 0, False, False, "SIMPLE", 0, 5, "Multiple exclamation marks"))
    cases.append(("??? " + _repeat("x ", 296), "???", 0, False, False, "SIMPLE", 13, 23, "Multiple question marks"))

    # --- Maximal score ---
    cases.append((
        _pad(
            "Le deploy CI/CD API REST staging Docker Kubernetes Terraform AWS "
            "SQL migration database schema endpoint GraphQL OAuth "
            "bug debug stack trace exception error crash "
            "refactor sprint Jira Confluence pull request merge branch "
            "SLA NDA RGPD GDPR DPIA DPO KPI ROI "
            "contrat avenant résiliation tarif facturation licences "
            "rollback release production JSON XML CSV HTTP "
            "Est-ce ok? Quand? Pourquoi? Comment? Combien? "
            "1. Premier\n2. Deuxième\n3. Troisième\n\n"
            "Par ailleurs, deuxième sujet.\n\n"
            "Concernant le troisième point.\n\nDe plus, quatrième.",
            2500
        ),
        "All signals maxed", 6, True, True,
        "COMPLEX", 85, 100, "Every signal maxed"
    ))

    # --- All signals at zero ---
    cases.append(("", "", 0, False, False, "SIMPLE", 0, 0, "All signals zero -> score=0"))

    # --- Newlines between questions ---
    cases.append((
        "Oui?\n\n\nNon?\n\n\nPeut-être?" + _repeat("x ", 270),
        "Spaced questions", 0, False, False,
        "STANDARD", 30, 48, "3 questions separated by many newlines"
    ))

    # --- Unicode zero-width chars ---
    cases.append((
        "Hello\u200b world\u200b test" + _repeat("x ", 285),
        "Zero-width chars", 0, False, False,
        "SIMPLE", 0, 10, "Zero-width spaces in body"
    ))

    # --- RTL text ---
    cases.append((
        "\u0645\u0631\u062d\u0628\u0627 " + _repeat("x ", 295),
        "Arabic greeting", 0, False, False,
        "SIMPLE", 0, 10, "Arabic text in body"
    ))

    # --- Very long subject ---
    cases.append((
        _repeat("x ", 300), "A" * 500, 0, False, False,
        "SIMPLE", 0, 10, "Very long subject (500 chars)"
    ))

    # --- Null-like values ---
    cases.append(("null", "null", 0, False, False, "SIMPLE", 0, 5, "Body and subject are 'null'"))
    cases.append(("undefined", "undefined", 0, False, False, "SIMPLE", 0, 5, "Body and subject are 'undefined'"))

    # --- Punctuation body ---
    cases.append((
        ".,;:!-_()[]{}@#$%^&*+=~`|\\/<>" + _repeat("x ", 280),
        "Punctuation body", 0, False, False,
        "SIMPLE", 0, 10, "Body with only punctuation characters"
    ))

    # --- CJK characters ---
    cases.append((
        "\u4f60\u597d\u4e16\u754c " + _repeat("x ", 295),
        "CJK chars", 0, False, False,
        "SIMPLE", 0, 10, "Chinese characters in body"
    ))

    return cases[:50]
