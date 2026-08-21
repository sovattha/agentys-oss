"""
Test case generators for STANDARD-tier email complexity scoring.

Each function returns a list of tuples:
(body, subject, thread_depth, has_instructions, has_attachments, expected_tier, score_min, score_max, description)

STANDARD tier: score 30-49, OR score < 30 with has_instructions=True.
"""


def _pad_to(text, target_len, signature=""):
    """Pad text to reach approximately target_len characters for body."""
    if not signature:
        signature = "\n\nCordialement,\nJean Dupont\nDirecteur Commercial"
    current = text + signature
    if len(current) >= target_len:
        return current[:target_len]
    # Add filler sentences before signature
    fillers_fr = [
        "Je reste disponible pour en discuter de vive voix si nécessaire.",
        "N'hésitez pas à me faire part de vos remarques ou suggestions.",
        "Nous pourrons également aborder ce sujet lors de notre prochaine réunion.",
        "Je vous tiendrai informé de l'avancement dès que possible.",
        "Merci pour votre réactivité sur ce dossier.",
        "Le contexte actuel nous impose de traiter ce point rapidement.",
        "J'ai pris note de vos observations et j'y reviendrai en détail.",
        "Ce point mérite une attention particulière de notre part.",
        "L'équipe travaille activement sur ce sujet depuis la semaine dernière.",
        "Votre retour sera déterminant pour la suite des opérations.",
        "Je souhaite m'assurer que nous sommes bien alignés sur les prochaines étapes.",
        "La situation évolue rapidement et nous devons rester vigilants.",
        "Je me permets de revenir vers vous concernant notre dernier échange.",
        "Votre avis serait précieux pour avancer sur ce dossier.",
        "Nous avons bien avancé sur les différents points évoqués précédemment.",
    ]
    fillers_en = [
        "I remain available to discuss this further at your convenience.",
        "Please do not hesitate to share your thoughts or feedback.",
        "We can also address this topic during our next scheduled meeting.",
        "I will keep you updated on the progress as soon as possible.",
        "Thank you for your responsiveness on this matter.",
        "The current context requires us to address this promptly.",
        "I have taken note of your observations and will review them.",
        "This point deserves particular attention from our team.",
        "The team has been actively working on this since last week.",
        "Your feedback will be crucial for the next steps.",
        "I want to make sure we are well aligned on next steps.",
        "The situation is evolving quickly and we need to stay on top of it.",
        "I am following up on our last conversation regarding this topic.",
        "Your input would be valuable to move forward on this matter.",
        "We have made good progress on the various points discussed previously.",
    ]
    fillers = fillers_fr if any(c in text for c in "éèêàùôîç") else fillers_en
    result = text
    idx = 0
    while len(result + signature) < target_len and idx < len(fillers):
        result += " " + fillers[idx]
        idx += 1
    if len(result + signature) < target_len:
        gap = target_len - len(result + signature)
        result += " " + "Nous suivons ce dossier de près. " * (gap // 35 + 1)
    return (result + signature)[:target_len]


def _gen_standard_medium():
    """
    200 test cases for STANDARD tier with medium complexity.
    1-2 questions, body 300-900 chars, 0-1 tech keywords. Score 30-49.
    Mix of French and English with realistic business email content.
    """
    cases = []

    # =========================================================================
    # GROUP A (50 cases): 2 questions + body 500-900 chars + 1 tech keyword + thread_depth=1
    # q=70*0.20=14, body~(19-43)*0.20=3.8-8.7, tech=40*0.15=6, thread=20*0.10=2
    # Total ~25.8-30.7. Add topics=2 for +5 to push into 30-35 range.
    # With topics=2: +50*0.10=5 → 30.8-35.7
    # =========================================================================

    # A1-A10: French, 2 questions, ~600 chars, 1 tech, thread=1, 2 topics
    cases.append((
        _pad_to(
            "Bonjour Pierre,\n\nJe reviens vers vous au sujet du projet Alpha. "
            "Nous avons reçu les retours du client et plusieurs points nécessitent des ajustements. "
            "Le planning initial prévoyait une livraison en mars, mais le calendrier semble compromis.\n\n"
            "Par ailleurs, j'aimerais savoir si vous avez pu valider le budget prévisionnel ? "
            "Est-ce que l'équipe est disponible la semaine prochaine pour un point d'avancement ?",
            600, "\n\nCordialement,\nMarc Lefèvre\nChef de projet"
        ),
        "RE: Projet Alpha - Point d'avancement sprint",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 600ch, 1tech(sprint), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Sophie,\n\nSuite à notre échange de la semaine dernière, je souhaitais revenir sur "
            "les conditions du contrat de maintenance annuel. Le prestataire nous a transmis une nouvelle "
            "grille tarifaire qui diffère sensiblement de l'offre initiale.\n\n"
            "Concernant les délais, pourriez-vous confirmer si le renouvellement doit être signé avant fin mars ? "
            "Avez-vous eu le temps de consulter les nouvelles conditions ?",
            650, "\n\nBien à vous,\nThomas Martin\nResponsable achats"
        ),
        "RE: Renouvellement contrat maintenance",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 650ch, 1tech(contrat), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Nathalie,\n\nJe fais suite à votre demande concernant la mise en place du nouveau "
            "processus de facturation. L'équipe comptable a préparé un document récapitulatif "
            "qui détaille les différentes étapes à suivre pour la transition.\n\n"
            "D'autre part, avez-vous prévu une formation pour les utilisateurs du nouveau système ? "
            "Pouvez-vous nous indiquer une date pour la réunion de validation ?",
            620, "\n\nCordialement,\nAntoine Rousseau\nDAF"
        ),
        "RE: Nouveau processus facturation",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 620ch, 1tech(facturation), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Julien,\n\nNous avons bien avancé sur le dossier de certification. "
            "Les audits préliminaires sont terminés et les résultats sont globalement positifs. "
            "Il reste cependant quelques non-conformités mineures à corriger avant la visite finale.\n\n"
            "Par ailleurs, est-ce que le responsable qualité a validé les actions correctives ? "
            "Pouvons-nous planifier une revue interne la semaine du 15 ?",
            600, "\n\nBien cordialement,\nClaire Dumont\nResponsable qualité"
        ),
        "RE: Certification - actions correctives KPI",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 600ch, 1tech(KPI), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Éric,\n\nJ'espère que vous allez bien. Je souhaitais faire le point sur "
            "l'avancement de la migration vers le nouveau système de gestion des stocks. "
            "Les premiers tests en environnement de recette sont encourageants, mais nous avons "
            "identifié quelques problèmes de performance.\n\n"
            "Concernant le budget, le tarif du prestataire est-il définitif ? "
            "Pouvez-vous confirmer la date de mise en production prévue ?",
            680, "\n\nCordialement,\nLaurent Petit\nDSI"
        ),
        "RE: Migration système stocks",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 680ch, 1tech(tarif), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Catherine,\n\nComme convenu lors de notre dernier comité, je vous transmets "
            "le récapitulatif des actions en cours. Le plan de formation a été finalisé et les "
            "inscriptions sont ouvertes pour les sessions de mars et avril.\n\n"
            "Par ailleurs, avez-vous pu obtenir les retours des managers sur les besoins en compétences ? "
            "L'enveloppe budgétaire pour le licensing des outils est-elle validée ?",
            660, "\n\nBien à vous,\nPhilippe Moreau\nDRH"
        ),
        "RE: Plan de formation - budget licensing",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 660ch, 1tech(licensing), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Vincent,\n\nJe reviens vers vous suite aux retours du comité de pilotage. "
            "Plusieurs membres ont soulevé des interrogations sur la faisabilité technique du projet. "
            "Le planning prévisionnel devra être ajusté en conséquence.\n\n"
            "D'autre part, le SLA proposé par le fournisseur vous semble-t-il acceptable ? "
            "Avez-vous vérifié la compatibilité avec nos systèmes existants ?",
            620, "\n\nCordialement,\nAudrey Leroy\nDirectrice technique"
        ),
        "RE: Comité pilotage - retours SLA",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 620ch, 1tech(SLA), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Marie,\n\nSuite à notre discussion, j'ai préparé une synthèse des différentes "
            "options pour le renouvellement de notre infrastructure. Chaque scénario a été chiffré "
            "et les avantages/inconvénients sont détaillés dans le document joint.\n\n"
            "Concernant la clause d'exclusivité, est-elle vraiment indispensable à ce stade ? "
            "Pensez-vous que le fournisseur acceptera de négocier ce point ?",
            640, "\n\nCordialement,\nRomain Bernard\nAchats"
        ),
        "RE: Renouvellement infrastructure",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 640ch, 1tech(clause), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Stéphane,\n\nJe souhaitais vous informer que le processus de résiliation "
            "du contrat avec notre ancien prestataire est en cours. Les équipes juridiques "
            "travaillent sur les conditions de sortie et les éventuelles pénalités.\n\n"
            "Par ailleurs, avez-vous contacté les candidats présélectionnés pour le remplacement ? "
            "Pouvez-vous me faire un retour sur les propositions reçues avant vendredi ?",
            660, "\n\nBien cordialement,\nIsabelle Faure\nDirection générale"
        ),
        "RE: Résiliation prestataire - sélection remplacement",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 660ch, 1tech(résiliation), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Alexandre,\n\nLe projet de refonte du site web avance conformément au planning. "
            "Les maquettes ont été validées par le comité éditorial et l'intégration a débuté. "
            "Nous avons cependant pris du retard sur le volet accessibilité.\n\n"
            "D'autre part, avez-vous finalisé le contenu pour la page d'accueil ? "
            "La date de mise en ligne du 15 avril est-elle toujours réaliste ?",
            650, "\n\nCordialement,\nCamille Girard\nChef de projet digital"
        ),
        "Refonte site web - point d'avancement avenant",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 650ch, 1tech(avenant), thread=1, 2topics"
    ))

    # A11-A20: English, 2 questions, ~600 chars, 1 tech, thread=1, 2 topics
    cases.append((
        _pad_to(
            "Hi Sarah,\n\nI wanted to follow up on the quarterly review we discussed last week. "
            "The sales numbers are looking solid for Q1 and the pipeline is healthy. "
            "However, we need to address the customer churn issue before it impacts Q2 targets.\n\n"
            "Additionally, have you had a chance to review the updated KPI dashboard ? "
            "Can we schedule a sync to align on the go-to-market strategy for next quarter?",
            620, "\n\nBest regards,\nDavid Chen\nVP Sales"
        ),
        "RE: Q1 Review - KPI alignment",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 620ch, 1tech(KPI), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Michael,\n\nThank you for sending over the vendor proposals. I have reviewed "
            "all three and documented my initial thoughts in the shared folder. "
            "The pricing structures vary significantly and we need to compare them carefully.\n\n"
            "Regarding the contract terms, does the two-year commitment clause seem reasonable? "
            "Would it be possible to negotiate a shorter initial period?",
            600, "\n\nBest,\nEmily Watson\nProcurement Manager"
        ),
        "RE: Vendor proposals - contrat review",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 600ch, 1tech(contrat), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Jennifer,\n\nI hope this message finds you well. Following our team meeting, "
            "I have compiled the action items and shared them via the project tracker. "
            "Most deliverables are on track but we have a potential bottleneck on the design side.\n\n"
            "Also, could you confirm whether the production timeline has been updated? "
            "Are the external consultants still scheduled to start on Monday?",
            640, "\n\nRegards,\nJames Miller\nProgram Manager"
        ),
        "RE: Team meeting follow-up - production schedule",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 640ch, 1tech(production), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Robert,\n\nJust circling back on the partnership discussion from Thursday. "
            "I believe there is strong synergy between our teams and the proposed collaboration "
            "could yield significant results in the next fiscal year.\n\n"
            "Regarding the NDA, have your legal team finished reviewing the draft? "
            "Do you foresee any issues with the confidentiality clauses?",
            600, "\n\nKind regards,\nLisa Thompson\nBusiness Development"
        ),
        "RE: Partnership discussion - NDA review",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 600ch, 1tech(NDA), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Amanda,\n\nThank you for the comprehensive update on the hiring initiative. "
            "We have received a strong pool of candidates and the initial screenings are underway. "
            "The HR team has been very efficient in processing the applications.\n\n"
            "Also, is the ROI analysis for the new recruitment platform finalized? "
            "Can you share the comparison metrics with the old system?",
            640, "\n\nBest regards,\nChris Anderson\nHR Director"
        ),
        "RE: Hiring initiative - ROI analysis",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 640ch, 1tech(ROI), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Daniel,\n\nI am writing to update you on the facility renovation project. "
            "The contractors have completed the first phase and the inspection passed without issues. "
            "Phase two is set to begin next Monday pending final approvals.\n\n"
            "Regarding the release of the second payment tranche, have the invoices been validated? "
            "Is the project still within the allocated budget?",
            650, "\n\nBest,\nPatricia Lee\nFacilities Manager"
        ),
        "RE: Facility renovation - budget release",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 650ch, 1tech(release), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Kevin,\n\nI wanted to touch base regarding the upcoming conference in Berlin. "
            "The agenda has been finalized and our speaking slot is confirmed for the afternoon session. "
            "We need to coordinate travel arrangements for the team.\n\n"
            "Additionally, have you confirmed the staging area for the product demo? "
            "Is the marketing team prepared with the updated materials?",
            630, "\n\nRegards,\nNatalie Brown\nEvents Coordinator"
        ),
        "RE: Berlin conference - staging prep",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 630ch, 1tech(staging), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Mark,\n\nFollowing our quarterly planning session, I have outlined the key priorities "
            "for the next period. The team has agreed on three main workstreams and resource allocation "
            "has been tentatively mapped out.\n\n"
            "Regarding compliance, have you received the updated GDPR guidelines from legal? "
            "Do we need to adjust our data retention policies accordingly?",
            640, "\n\nBest regards,\nRachel Green\nCompliance Officer"
        ),
        "RE: Quarterly planning - GDPR compliance",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 640ch, 1tech(GDPR), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Tom,\n\nThe annual budget review is approaching and I wanted to share some preliminary "
            "figures. Revenue is tracking ahead of forecast by approximately eight percent "
            "and operational costs have remained stable throughout the quarter.\n\n"
            "Also, has the deploy schedule for the new expense management tool been confirmed? "
            "Can we discuss the rollout timeline during our next one-on-one?",
            650, "\n\nRegards,\nStephanie Adams\nFinance Director"
        ),
        "RE: Budget review - deploy schedule",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 650ch, 1tech(deploy), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Laura,\n\nI hope you are doing well. I wanted to provide an update on the supplier "
            "negotiations. We have narrowed down the shortlist to two finalists and both have "
            "submitted competitive proposals with favorable terms.\n\n"
            "Regarding the schema of the evaluation criteria, have you reviewed the scoring matrix? "
            "Is there anything you would like to adjust before the final round?",
            650, "\n\nBest,\nAndrew Wilson\nStrategic Sourcing"
        ),
        "RE: Supplier negotiations - evaluation schema",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 650ch, 1tech(schema), thread=1, 2topics"
    ))

    # =========================================================================
    # GROUP B (50 cases): 1 question + body 700-900 chars + 2 tech keywords + thread=2
    # q=35*0.20=7, body~(31-43)*0.20=6.2-8.7, tech=70*0.15=10.5, thread=40*0.10=4
    # Total ~27.7-30.2. Add topics=2 for +5 → 32.7-35.2
    # =========================================================================

    # B1-B10: French, 1 question, ~800 chars, 2 tech, thread=2, 2 topics
    cases.append((
        _pad_to(
            "Bonjour Frédéric,\n\nJe fais suite à notre réunion sur le projet de migration "
            "de la base de données vers la nouvelle infrastructure cloud. L'équipe technique a "
            "terminé l'analyse d'impact et le plan de migration est prêt pour validation. "
            "Les tests de charge ont été concluants et la performance est au rendez-vous. "
            "Nous avons identifié quelques points de vigilance concernant la compatibilité "
            "des anciens connecteurs avec le nouveau schéma.\n\n"
            "Par ailleurs, les coûts de licensing pour la nouvelle plateforme ont été négociés "
            "à la baisse. Pouvez-vous valider le bon de commande avant la fin de la semaine ?",
            800, "\n\nCordialement,\nGuillaume Perrin\nArchitecte solutions"
        ),
        "RE: Migration database - plan de transition",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(database,licensing), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Caroline,\n\nVoici le compte-rendu de la revue technique de vendredi dernier. "
            "Nous avons passé en revue les différents scénarios pour le déploiement en production "
            "et avons retenu l'approche progressive avec un rollback automatique en cas de problème. "
            "Les équipes sont mobilisées et les environnements de test sont prêts.\n\n"
            "Concernant le calendrier, nous visons une mise en production le 25 mars. "
            "Le plan de communication interne est-il finalisé ?",
            800, "\n\nBien cordialement,\nMaxime Durand\nDevOps Lead"
        ),
        "RE: Revue technique - production deploy",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(production,rollback), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Hélène,\n\nSuite à l'incident de production de mardi, nous avons mené une "
            "analyse approfondie des causes. Le problème provenait d'une erreur de configuration "
            "dans le module de facturation qui impactait le calcul des remises. "
            "L'équipe a corrigé le bug et mis en place des contrôles supplémentaires "
            "pour éviter que ce type de situation ne se reproduise.\n\n"
            "Par ailleurs, les résultats du trimestre sont encourageants malgré cet incident. "
            "Pensez-vous que nous devrions communiquer proactivement auprès des clients affectés ?",
            800, "\n\nCordialement,\nYannick Lefebvre\nDirecteur des opérations"
        ),
        "RE: Incident production - post-mortem facturation",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(bug,facturation), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Nicolas,\n\nComme discuté, nous avons finalisé le cahier des charges pour "
            "le nouveau système de gestion des contrats. Les fonctionnalités clés ont été "
            "priorisées et le planning de développement est aligné avec le budget disponible. "
            "Le prestataire a confirmé sa capacité à livrer dans les délais impartis "
            "et nous avons sécurisé un tarif préférentiel pour la première année.\n\n"
            "D'autre part, la procédure de résiliation de l'ancien outil est en cours. "
            "Avez-vous prévu un plan de formation pour les équipes ?",
            800, "\n\nBien à vous,\nSandrine Morel\nResponsable des systèmes d'information"
        ),
        "RE: Nouveau système contrats - planning",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(contrat,tarif), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Olivier,\n\nJe souhaitais vous tenir informé de l'état d'avancement du "
            "projet de conformité RGPD. Nous avons terminé la cartographie des traitements "
            "de données personnelles et identifié les zones à risque. "
            "Le registre des traitements est en cours de rédaction et sera soumis à validation "
            "d'ici la fin du mois. Les équipes juridiques travaillent en parallèle sur "
            "la mise à jour des clauses contractuelles.\n\n"
            "Concernant les budgets, pourriez-vous confirmer l'enveloppe allouée à ce chantier ?",
            800, "\n\nCordialement,\nDiane Lambert\nDPO"
        ),
        "RE: Conformité RGPD - cartographie clause",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(RGPD,clause), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Patrick,\n\nVoici mon retour sur la proposition commerciale du fournisseur "
            "de services cloud. Les conditions tarifaires sont compétitives mais le SLA proposé "
            "ne correspond pas tout à fait à nos exigences en termes de disponibilité. "
            "J'ai demandé une révision sur ce point spécifique ainsi que sur les pénalités "
            "en cas de non-respect des engagements.\n\n"
            "De plus, l'impact sur notre budget de licences est significatif. "
            "Pensez-vous que nous pouvons absorber ce surcoût sur l'exercice en cours ?",
            800, "\n\nBien cordialement,\nBrigitte Fournier\nDirectrice financière"
        ),
        "RE: Proposition fournisseur cloud - SLA licences",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(SLA,licences), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Christophe,\n\nSuite au sprint planning de ce matin, voici les éléments "
            "que j'ai retenus. Nous avons priorisé les user stories liées à la refonte du "
            "parcours utilisateur et décalé les optimisations de performance au sprint suivant. "
            "L'équipe front-end a besoin de deux jours supplémentaires pour finaliser "
            "les maquettes interactives. Le backlog est en ordre et la vélocité est stable.\n\n"
            "Par ailleurs, la revue de code sur les derniers endpoints est en attente. "
            "Pouvez-vous assigner un reviewer pour cette semaine ?",
            800, "\n\nCordialement,\nFabien Roche\nScrum Master"
        ),
        "RE: Sprint planning - endpoints review",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(sprint,endpoint), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Valérie,\n\nJe vous écris pour vous informer de l'avancement du projet "
            "de digitalisation des processus métier. Les premières workflows ont été configurés "
            "et les tests fonctionnels sont en cours. L'intégration avec notre système de "
            "gestion documentaire fonctionne correctement et les retours utilisateurs sont positifs. "
            "L'avenant au contrat cadre a été transmis au service juridique pour validation.\n\n"
            "D'autre part, nous devons recruter un profil supplémentaire pour renforcer l'équipe. "
            "Pouvez-vous valider le descriptif de poste ?",
            800, "\n\nBien à vous,\nJean-Marc Simon\nDirecteur de la transformation"
        ),
        "RE: Digitalisation processus - avenant contrat",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(avenant,contrat), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Sylvie,\n\nVoici le point hebdomadaire sur la mise en conformité des "
            "processus achats. Nous avons terminé l'audit des fournisseurs stratégiques et "
            "les résultats sont satisfaisants dans l'ensemble. Quelques écarts mineurs ont été "
            "identifiés sur les procédures de validation et un plan d'action correctif "
            "a été établi. La prochaine étape concerne le déploiement du nouveau workflow "
            "de commande qui est prévu pour le mois prochain.\n\n"
            "Concernant le KPI de délai moyen de traitement, est-il en amélioration ?",
            800, "\n\nCordialement,\nPascal Mercier\nResponsable achats"
        ),
        "RE: Conformité achats - deploy workflow KPI",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(deploy,KPI), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Cédric,\n\nJe fais suite à votre demande concernant la sécurisation "
            "des accès au système d'information. L'audit de sécurité mené par le prestataire "
            "externe est terminé et le rapport final sera disponible en début de semaine. "
            "Les recommandations portent principalement sur le renforcement de l'authentification "
            "et la mise en place de politiques de mots de passe plus strictes.\n\n"
            "Par ailleurs, la mise en conformité GDPR de nos traitements est en bonne voie. "
            "Pouvez-vous nous transmettre la liste des sous-traitants à auditer ?",
            800, "\n\nBien cordialement,\nMathieu Blanc\nRSSI"
        ),
        "RE: Audit sécurité - conformité GDPR",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(GDPR,error/audit), thread=2, 2topics"
    ))

    # B11-B20: English, 1 question, ~800 chars, 2 tech, thread=2, 2 topics
    cases.append((
        _pad_to(
            "Hi Rachel,\n\nI am pleased to report that the API integration project is progressing "
            "well. The development team has completed the core endpoints and initial testing shows "
            "promising results. The documentation has been updated to reflect the latest changes "
            "and the staging environment is ready for the QA team to begin their review.\n\n"
            "Additionally, we have received positive feedback from the early adopters program. "
            "Do you think we should expand the beta to include more partners?",
            800, "\n\nBest regards,\nBrian Foster\nEngineering Manager"
        ),
        "RE: API integration - staging update",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(API,staging), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Susan,\n\nFollowing up on our call about the database optimization initiative. "
            "The performance benchmarks have been completed and the results indicate a significant "
            "improvement in query response times. The migration script has been tested in the "
            "staging environment and is ready for the production rollout. "
            "We are targeting next Tuesday for the cutover.\n\n"
            "Also, the monitoring dashboards have been updated with the new metrics. "
            "Should we schedule a walkthrough with the operations team?",
            800, "\n\nRegards,\nRyan Mitchell\nDatabase Administrator"
        ),
        "RE: Database optimization - staging rollout",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(database,staging), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Jessica,\n\nI wanted to share the results from last week's sprint retrospective. "
            "The team identified several areas for improvement, particularly around the code review "
            "process and the deployment pipeline. We have agreed to implement pair reviews for "
            "critical changes and to set up automated regression tests to catch issues earlier.\n\n"
            "Regarding the upcoming release, the feature freeze is scheduled for Friday. "
            "Can you confirm that all priority items have been merged?",
            800, "\n\nBest,\nMatt Johnson\nTech Lead"
        ),
        "RE: Sprint retro - release planning",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(sprint,release), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Catherine,\n\nThe vendor evaluation process is nearing completion. We have conducted "
            "detailed demos with all four shortlisted providers and scored them against our criteria. "
            "Two vendors stand out for their robust approach to data management and their competitive "
            "pricing. The contract terms have been reviewed by legal and there are no major concerns.\n\n"
            "Furthermore, the ROI projections for each option have been documented. "
            "Would you like to review them before the steering committee meeting?",
            800, "\n\nKind regards,\nAlex Turner\nStrategic Procurement"
        ),
        "RE: Vendor evaluation - ROI contrat analysis",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(ROI,contrat), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Peter,\n\nThank you for your patience while we resolved the compliance matter. "
            "The legal team has completed their review and confirmed that our processes align "
            "with the updated GDPR requirements. We have documented all changes and the compliance "
            "report is ready for submission. The only outstanding item is the update to our "
            "data processing agreement with the third-party provider.\n\n"
            "Also, the licensing costs for the compliance tool have been finalized. "
            "Do you need approval from the board before we proceed?",
            800, "\n\nBest regards,\nOlivia Hart\nHead of Compliance"
        ),
        "RE: GDPR compliance - licensing update",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(GDPR,licensing), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Greg,\n\nI am writing to provide an update on the infrastructure modernization project. "
            "The team has successfully completed the Docker containerization of the main application "
            "and the initial deployment to our test cluster went smoothly. Performance metrics are "
            "within acceptable thresholds and no critical issues have been reported.\n\n"
            "Regarding the timeline, we are on track for the production cutover. "
            "Can you confirm the maintenance window for the weekend of April fifth?",
            800, "\n\nRegards,\nSamantha Clarke\nInfrastructure Lead"
        ),
        "RE: Infrastructure modernization - Docker deploy",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(docker,deploy), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Michelle,\n\nHere is a summary of the customer feedback analysis from last quarter. "
            "Overall satisfaction scores have improved by twelve percent and the net promoter score "
            "reached its highest point in two years. Key drivers include faster response times "
            "and the improved self-service portal. The main area for improvement remains "
            "the onboarding experience for new customers.\n\n"
            "Additionally, the Jira board for the improvement initiatives has been set up. "
            "Would you like to prioritize any specific items for the next sprint?",
            800, "\n\nBest,\nWilliam Park\nCustomer Success Manager"
        ),
        "RE: Customer feedback - Jira sprint planning",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(jira,sprint), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Nicole,\n\nThe annual security assessment has been completed and I wanted to share "
            "the key findings. Our overall security posture has improved since last year but there "
            "are a few areas that require attention. Specifically, the branch protection rules "
            "need to be tightened and we should implement mandatory code reviews for all production "
            "changes to minimize the risk of unauthorized modifications.\n\n"
            "Also, the merge request workflow needs to be standardized across teams. "
            "Can we discuss the implementation timeline during our next sync?",
            800, "\n\nRegards,\nSteven Hall\nSecurity Engineer"
        ),
        "RE: Security assessment - branch merge policy",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(branch,merge), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Victoria,\n\nI wanted to update you on the cloud migration initiative. "
            "The team has completed the assessment phase and identified all workloads suitable "
            "for migration. The cost analysis shows that moving to AWS will result in approximately "
            "twenty percent savings on our annual infrastructure spend. The proof of concept "
            "has been validated and we are ready to proceed with the first wave.\n\n"
            "Regarding the current error rates in the legacy system, they continue to climb. "
            "Should we accelerate the timeline to mitigate risks?",
            800, "\n\nBest regards,\nChristopher Davis\nCloud Architect"
        ),
        "RE: Cloud migration - AWS error analysis",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 800ch, 2tech(aws,error), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Diana,\n\nThe talent acquisition strategy for the engineering team has been "
            "finalized. We are targeting fifteen new hires across frontend, backend, and DevOps "
            "roles. The job descriptions have been reviewed and approved by the hiring managers "
            "and the positions will be posted on all major platforms this week.\n\n"
            "Additionally, the Confluence page with the interview process has been updated. "
            "Do you have any feedback on the technical assessment criteria?",
            750, "\n\nKind regards,\nNathan Brooks\nHead of Talent"
        ),
        "RE: Engineering hiring - Confluence terraform docs",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 750ch, 2tech(confluence,terraform), thread=2, 2topics"
    ))

    # B21-B30: Mixed FR/EN, 1q, ~750 chars, 2 tech, thread=2, 2topics
    cases.append((
        _pad_to(
            "Bonjour Rémi,\n\nJe reviens vers vous avec les résultats de l'audit des licences "
            "logicielles. Nous avons identifié plusieurs postes sous-utilisés et des opportunités "
            "d'optimisation significatives. Le rapport détaillé est disponible sur le serveur "
            "partagé et inclut des recommandations concrètes pour chaque éditeur.\n\n"
            "D'autre part, le déploiement du nouvel outil de gestion des assets sur Azure "
            "est prévu pour le mois prochain. Pouvez-vous valider le planning ?",
            750, "\n\nCordialement,\nEmmanuelle Vernier\nGestionnaire licences"
        ),
        "RE: Audit licences - deploy Azure",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 750ch, 2tech(licences,azure), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Jason,\n\nThank you for your thorough analysis of the system architecture. "
            "The proposed changes to the REST layer look solid and should address the scalability "
            "concerns we discussed. The team is ready to begin implementation once we get "
            "the green light from the product owner. The estimated effort is three sprints.\n\n"
            "Also, the refactoring of the legacy modules is planned for Q2. "
            "Should we start the knowledge transfer sessions this week?",
            750, "\n\nBest,\nCaroline Murphy\nSolutions Architect"
        ),
        "RE: Architecture review - REST refactor",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 750ch, 2tech(REST,refactor), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Arnaud,\n\nSuite à la réunion d'hier sur le plan de continuité d'activité, "
            "voici les principales conclusions. Le scénario de reprise a été testé avec succès "
            "et les temps de basculement sont conformes aux exigences du SLA. "
            "L'infrastructure de secours sur GCP est opérationnelle et supervisée.\n\n"
            "Concernant la documentation, le plan d'action a été mis à jour. "
            "Pouvez-vous le relire avant la prochaine revue de direction ?",
            750, "\n\nCordialement,\nBertrand Collet\nResponsable PCA"
        ),
        "RE: Plan continuité - SLA GCP",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 750ch, 2tech(SLA,gcp), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Emma,\n\nI have finished reviewing the quarterly financial reports and everything "
            "looks solid. The variance analysis shows that we are slightly under budget on most "
            "line items. The exception is the technology spend which came in higher due to the "
            "Kubernetes cluster expansion we approved in January.\n\n"
            "Regarding the Terraform scripts for the new environments, they need updating. "
            "Can you coordinate with the infrastructure team to get this done?",
            750, "\n\nRegards,\nPhilip Grant\nFinancial Controller"
        ),
        "RE: Quarterly financials - Kubernetes Terraform update",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 750ch, 2tech(kubernetes,terraform), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Thierry,\n\nVoici le point sur le projet de refonte de l'extranet client. "
            "Les développements front-end sont terminés et le back-end est en cours de finalisation. "
            "L'intégration avec le module d'authentification OAuth est fonctionnelle et les premiers "
            "retours des beta-testeurs sont encourageants. Le design responsive a été validé "
            "sur les principales résolutions.\n\n"
            "Par ailleurs, le endpoint de synchronisation des données doit encore être optimisé. "
            "Avez-vous une idée du temps nécessaire ?",
            800, "\n\nBien à vous,\nAnne-Sophie Martin\nProduct Owner"
        ),
        "RE: Extranet client - OAuth endpoint",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 800ch, 2tech(OAuth,endpoint), thread=2, 2topics"
    ))

    # B26-B30: More mixed cases
    cases.append((
        _pad_to(
            "Hi Luke,\n\nThe data warehouse project is making good progress. We have completed "
            "the ETL pipeline setup and initial data loading was successful. The SQL queries "
            "for the core reports have been optimized and response times are within acceptable limits. "
            "The dashboarding layer is the next phase and we expect to have a prototype ready "
            "by the end of the month.\n\n"
            "Also, the CSV export functionality needs to be added for the finance team. "
            "When do you think we can have that feature ready?",
            780, "\n\nBest,\nHelen Ward\nData Engineering Lead"
        ),
        "RE: Data warehouse - SQL CSV exports",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 780ch, 2tech(SQL,CSV), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Marina,\n\nJe vous transmets le bilan de la campagne de recrutement du "
            "premier trimestre. Nous avons reçu quatre-vingts candidatures qualifiées et mené "
            "vingt-cinq entretiens. Huit offres ont été émises dont six acceptées. Le taux "
            "de conversion est en hausse par rapport à l'année précédente. Le suivi des "
            "candidatures via Jira a bien fonctionné.\n\n"
            "Concernant le processus d'intégration via Confluence, la documentation est-elle à jour ?",
            780, "\n\nCordialement,\nDamien Fleury\nChargé de recrutement"
        ),
        "RE: Bilan recrutement Q1 - Jira Confluence",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 780ch, 2tech(jira,confluence), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Sophia,\n\nI wanted to let you know that the GraphQL API is now live in the "
            "staging environment. The schema has been finalized and all the documented queries "
            "are working as expected. The team has also implemented rate limiting and "
            "authentication middleware to ensure security. Performance testing will begin "
            "on Monday and we expect the results by Wednesday.\n\n"
            "Regarding the XML feed for the legacy clients, it needs to be maintained in parallel. "
            "Can your team handle the maintenance during the transition?",
            790, "\n\nRegards,\nVictor Chang\nBackend Lead"
        ),
        "RE: GraphQL API - XML feed maintenance",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 790ch, 2tech(GraphQL,XML), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Léa,\n\nSuite à l'analyse des indicateurs de performance du mois dernier, "
            "les résultats sont globalement positifs. Le taux de disponibilité du service est "
            "conforme au SLA et les temps de réponse moyens ont diminué de quinze pour cent. "
            "L'équipe support a traité tous les tickets dans les délais impartis. Le nombre "
            "d'incidents critiques est en baisse notable.\n\n"
            "D'autre part, le rapport sur les KPI doit être présenté au comité. "
            "Pouvez-vous préparer une synthèse pour vendredi ?",
            790, "\n\nCordialement,\nRaphaël Garnier\nDirecteur des services"
        ),
        "RE: Indicateurs performance - SLA KPI",
        2, False, False, "STANDARD", 30, 49,
        "FR 1q, 790ch, 2tech(SLA,KPI), thread=2, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Benjamin,\n\nThe CI/CD pipeline improvements are now complete. Build times "
            "have been reduced by forty percent and the deployment process is fully automated. "
            "The team has also added integration tests that run on every pull request to catch "
            "regressions early. The feedback from the developers has been very positive.\n\n"
            "Also, we identified some areas where the JSON configuration files need cleanup. "
            "Should we prioritize this for the next iteration?",
            790, "\n\nBest regards,\nTracy Fisher\nDevOps Engineer"
        ),
        "RE: CI/CD improvements - JSON pull request cleanup",
        2, False, False, "STANDARD", 30, 49,
        "EN 1q, 790ch, 2tech(CI/CD,JSON), thread=2, 2topics"
    ))

    # =========================================================================
    # GROUP C (40 cases): 2 questions + body 400-600 chars + 0 tech + thread=2-3 + topics=2
    # q=70*0.20=14, body~(12-25)*0.20=2.5-5.0, thread=40*0.10=4, topic=50*0.10=5
    # Total ~25.5-28.0. Need attachments (5) or instructions-like signals.
    # With attachments: +100*0.05=5 → 30.5-33.0 → STANDARD
    # =========================================================================

    # C1-C10: French, 2q, ~500 chars, 0 tech, thread=2, 2 topics, attachments
    cases.append((
        _pad_to(
            "Bonjour Florence,\n\nJe vous contacte au sujet de la prochaine réunion du comité. "
            "L'ordre du jour a été mis à jour et je vous le transmets en pièce jointe. "
            "Nous devrons traiter plusieurs sujets importants cette semaine.\n\n"
            "Par ailleurs, pouvez-vous confirmer votre présence le jeudi matin ? "
            "Avez-vous des points supplémentaires à ajouter à l'agenda ?",
            500, "\n\nCordialement,\nGéraldine Renard\nAssistante de direction"
        ),
        "RE: Comité hebdomadaire - ordre du jour",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Bernard,\n\nSuite à notre dernier échange, j'ai préparé les documents "
            "nécessaires pour la prochaine phase du projet. Vous trouverez ci-joint le planning "
            "révisé ainsi que la note de cadrage actualisée.\n\n"
            "Concernant les ressources, pensez-vous que l'équipe actuelle est suffisante ? "
            "Pouvons-nous compter sur le renfort prévu pour le mois prochain ?",
            500, "\n\nBien à vous,\nMartine Picard\nCoordinatrice projets"
        ),
        "RE: Phase 2 projet - documents",
        3, False, True, "STANDARD", 30, 49,
        "FR 2q, 500ch, 0tech, thread=3, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Dominique,\n\nJe vous envoie le compte-rendu de la réunion de lundi. "
            "Les principales décisions sont résumées dans le document joint. "
            "Nous avons notamment validé le budget pour le second semestre.\n\n"
            "D'autre part, pourriez-vous relire la section sur les objectifs annuels ? "
            "Souhaitez-vous que nous prévoyions un point de suivi supplémentaire ?",
            500, "\n\nCordialement,\nFrançoise Michel\nSecrétaire générale"
        ),
        "RE: Compte-rendu réunion - validation",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Mireille,\n\nVeuillez trouver ci-joint le rapport mensuel d'activité. "
            "Les chiffres sont encourageants et montrent une progression constante. "
            "L'équipe a fait un excellent travail ce mois-ci.\n\n"
            "Par ailleurs, avez-vous eu le temps de lire le rapport de la semaine dernière ? "
            "Souhaitez-vous que je prépare une version synthétique pour la direction ?",
            500, "\n\nBien cordialement,\nHubert Lemoine\nContrôleur de gestion"
        ),
        "RE: Rapport mensuel - synthèse",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Gilles,\n\nJe vous transmets les propositions commerciales reçues des "
            "trois fournisseurs. Chaque offre a été analysée selon les critères convenus. "
            "Le comparatif est disponible en annexe du mail.\n\n"
            "Concernant la décision finale, avez-vous une préférence parmi les options ? "
            "Souhaitez-vous organiser une réunion de sélection avant vendredi ?",
            500, "\n\nCordialement,\nJoëlle Prat\nResponsable achats"
        ),
        "RE: Propositions fournisseurs - comparatif",
        3, False, True, "STANDARD", 30, 49,
        "FR 2q, 500ch, 0tech, thread=3, 2topics, attach"
    ))

    # C6-C10: English, 2q, ~500 chars, 0 tech, thread=2, 2 topics, attachments
    cases.append((
        _pad_to(
            "Hi Margaret,\n\nPlease find attached the updated project charter for your review. "
            "I have incorporated the changes we discussed during our last call and highlighted "
            "the key revisions for easy reference.\n\n"
            "Also, do you agree with the revised timeline in section three? "
            "Would you prefer to discuss the resource allocation in person?",
            500, "\n\nBest regards,\nTimothy Ross\nProject Manager"
        ),
        "RE: Project charter - review requested",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Karen,\n\nI have prepared the presentation slides for next week's board meeting. "
            "The deck covers our strategic priorities, financial outlook, and key milestones for "
            "the upcoming quarter. The file is attached for your review.\n\n"
            "Additionally, should we include a section on market expansion? "
            "Do you have any last-minute additions to propose?",
            500, "\n\nKind regards,\nDonald White\nChief of Staff"
        ),
        "RE: Board meeting presentation",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Barbara,\n\nAttached is the draft agreement for the new office lease. "
            "Our legal counsel has reviewed the initial terms and provided comments. "
            "The key points to negotiate are the renewal clause and the annual increase cap.\n\n"
            "Regarding the timeline, can we aim to finalize this by end of month? "
            "Is there anything else you need from my side to move forward?",
            500, "\n\nBest,\nEdward King\nReal Estate Manager"
        ),
        "RE: Office lease - draft agreement",
        3, False, True, "STANDARD", 30, 49,
        "EN 2q, 500ch, 0tech, thread=3, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Scott,\n\nI am sharing the competitive analysis report that was completed "
            "last week. The findings are quite insightful and highlight several areas where "
            "we have a strong advantage as well as gaps to address.\n\n"
            "Also, have you had a chance to review the market sizing section? "
            "Do you want to set up a working session to discuss next steps?",
            500, "\n\nRegards,\nJulia Adams\nStrategy Analyst"
        ),
        "RE: Competitive analysis - market review",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Christine,\n\nPlease see the attached training schedule for the new team members. "
            "The program spans four weeks and covers all essential processes and tools. "
            "Each module includes practical exercises and assessments.\n\n"
            "Additionally, is the mentoring program ready to launch alongside the training? "
            "Would you like to review the assessment criteria before we share them?",
            500, "\n\nBest regards,\nPaul Richards\nLearning and Development"
        ),
        "RE: New hire training schedule",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 500ch, 0tech, thread=2, 2topics, attach"
    ))

    # =========================================================================
    # GROUP D (30 cases): 1 question + body 800-900 chars + 1 tech + thread=3 + topics=2
    # q=35*0.20=7, body~(37-43)*0.20=7.5-8.7, tech=40*0.15=6, thread=40*0.10=4, topic=50*0.10=5
    # Total ~29.5-30.7. Add attachments for a bit more → 34.5-35.7
    # Without attachments, borderline ~30
    # =========================================================================

    # D1-D10: French
    cases.append((
        _pad_to(
            "Bonjour Renaud,\n\nJe fais le point sur l'avancement du chantier de rénovation "
            "des bureaux du troisième étage. Les travaux de cloisonnement sont terminés et "
            "l'électricien a commencé l'installation du câblage réseau. Le mobilier commandé "
            "devrait être livré dans deux semaines. L'ambiance générale est positive et les "
            "collaborateurs attendent avec impatience leur nouvel espace de travail.\n\n"
            "Concernant le budget, nous avons utilisé environ soixante-quinze pour cent de "
            "l'enveloppe prévue. Le sprint de finalisation commence lundi prochain. "
            "Pensez-vous que nous pourrons respecter la date de livraison initiale ?",
            850, "\n\nCordialement,\nBéatrice Gautier\nServices généraux"
        ),
        "RE: Rénovation bureaux - point sprint",
        3, False, True, "STANDARD", 30, 49,
        "FR 1q, 850ch, 1tech(sprint), thread=3, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Noémie,\n\nVoici les éléments demandés pour la préparation du séminaire "
            "annuel. Le programme prévisionnel est finalisé et les intervenants externes ont "
            "confirmé leur participation. Le lieu a été réservé et la logistique est en cours "
            "d'organisation. Nous avons également prévu des ateliers de travail collaboratif "
            "pour favoriser les échanges entre les différents services.\n\n"
            "Par ailleurs, le budget de production de l'événement dépasse légèrement "
            "les prévisions initiales. Pouvez-vous obtenir une validation exceptionnelle ?",
            850, "\n\nBien à vous,\nAlain Dufour\nResponsable communication interne"
        ),
        "RE: Séminaire annuel - budget production",
        3, False, False, "STANDARD", 30, 49,
        "FR 1q, 850ch, 1tech(production), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Christelle,\n\nJe vous informe que la phase de recette du nouveau portail "
            "collaboratif est terminée. L'ensemble des scénarios de test ont été déroulés avec "
            "succès et les anomalies mineures détectées ont été corrigées. Les performances "
            "sont satisfaisantes et conformes aux attentes. L'équipe est prête pour le passage "
            "en environnement de pré-production.\n\n"
            "D'autre part, il reste à finaliser la documentation utilisateur pour le release. "
            "Quand pensez-vous que celle-ci sera disponible ?",
            850, "\n\nCordialement,\nFrédérique Mallet\nChef de projet IT"
        ),
        "RE: Portail collaboratif - recette release",
        3, False, False, "STANDARD", 30, 49,
        "FR 1q, 850ch, 1tech(release), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Sébastien,\n\nSuite à la dernière revue de direction, je vous transmets "
            "les actions qui nous concernent. Le plan stratégique a été validé dans ses grandes "
            "lignes et les objectifs pour l'année prochaine sont ambitieux mais réalistes. "
            "L'accent sera mis sur l'innovation et la satisfaction client. Les ressources "
            "nécessaires ont été identifiées et les arbitrages budgétaires sont en cours.\n\n"
            "Concernant la feuille de route du projet de migration, est-elle définitive ?",
            850, "\n\nBien cordialement,\nMonique Caron\nDirectrice de la stratégie"
        ),
        "RE: Revue direction - feuille route migration",
        3, False, False, "STANDARD", 30, 49,
        "FR 1q, 850ch, 1tech(migration), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Denis,\n\nLe bilan de l'opération commerciale de février est positif. "
            "Nous avons dépassé nos objectifs de vente de dix pour cent et attiré une "
            "cinquantaine de nouveaux clients. L'efficacité de la campagne multicanal est "
            "confirmée et les retours des commerciaux terrain sont excellents. Le coût "
            "d'acquisition client est en baisse significative par rapport au trimestre précédent.\n\n"
            "Par ailleurs, le renouvellement des supports de communication est prévu. "
            "Pouvez-vous valider le visuel avant l'envoi à l'imprimeur ?",
            850, "\n\nCordialement,\nVéronique Legrand\nDirectrice commerciale"
        ),
        "Bilan opération commerciale - renouvellement supports",
        3, False, True, "STANDARD", 30, 49,
        "FR 1q, 850ch, 1tech(renouvellement), thread=3, 2topics, attach"
    ))

    # D6-D10: English
    cases.append((
        _pad_to(
            "Hi Rebecca,\n\nI am happy to report that the client onboarding process redesign "
            "has been well received by all stakeholders. The new workflow reduces the average "
            "onboarding time by thirty percent and includes automated notifications at each stage. "
            "The pilot group has completed their first month and the feedback has been overwhelmingly "
            "positive. We are confident in scaling this across the organization.\n\n"
            "Regarding the endpoint for the integration with the CRM, it needs minor adjustments. "
            "Can you coordinate with the development team to get this resolved?",
            850, "\n\nBest regards,\nAaron Scott\nOperations Director"
        ),
        "RE: Client onboarding - endpoint CRM integration",
        3, False, False, "STANDARD", 30, 49,
        "EN 1q, 850ch, 1tech(endpoint), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Megan,\n\nThe marketing campaign for the product launch is ready to go. "
            "All creative assets have been finalized and the media buy has been confirmed. "
            "The landing page is live and the social media calendar has been loaded. "
            "We are expecting significant engagement during the first week based on the "
            "pre-launch interest. The team has worked incredibly hard to get everything ready.\n\n"
            "Also, the error tracking for the landing page analytics needs attention. "
            "When can we expect the analytics dashboard to be fully functional?",
            850, "\n\nRegards,\nJordan Hayes\nMarketing Manager"
        ),
        "RE: Product launch campaign - error tracking",
        3, False, False, "STANDARD", 30, 49,
        "EN 1q, 850ch, 1tech(error), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Christina,\n\nI wanted to provide a status update on the office relocation project. "
            "The new space has been fitted out according to specifications and the IT infrastructure "
            "has been installed. Network testing was completed yesterday and all connections are "
            "operational. The move logistics have been planned in detail and communicated to all "
            "departments. We are on schedule for the transition this weekend.\n\n"
            "Additionally, the rollback plan in case of any issues has been documented. "
            "Do you want to review it before we proceed?",
            850, "\n\nBest,\nBruce Taylor\nFacilities Director"
        ),
        "RE: Office relocation - rollback plan",
        3, False, True, "STANDARD", 30, 49,
        "EN 1q, 850ch, 1tech(rollback), thread=3, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Sandra,\n\nThe employee satisfaction survey results are in and I wanted to share "
            "the highlights. Overall satisfaction has increased by five points compared to last year. "
            "The areas scoring highest are team collaboration and work-life balance. "
            "The areas needing improvement are career development and internal communication. "
            "I have prepared an action plan that addresses the key themes.\n\n"
            "Also, the schema for the new feedback portal needs to be approved. "
            "Would it be possible to get your sign-off by end of week?",
            850, "\n\nKind regards,\nGary Evans\nHR Business Partner"
        ),
        "RE: Employee survey results - feedback schema",
        3, False, False, "STANDARD", 30, 49,
        "EN 1q, 850ch, 1tech(schema), thread=3, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Tiffany,\n\nI completed the review of our insurance policies and here are my "
            "findings. The current coverage is adequate for our standard operations but falls "
            "short in areas related to cyber risk and business interruption. I have obtained "
            "quotes from two additional providers and the premiums are competitive. "
            "The comparison spreadsheet is attached for your review.\n\n"
            "Regarding the clause on liability limits, there is a discrepancy to resolve. "
            "Can we discuss this during our next scheduled meeting?",
            850, "\n\nRegards,\nRoger Price\nRisk Manager"
        ),
        "RE: Insurance review - liability clause",
        3, False, True, "STANDARD", 30, 49,
        "EN 1q, 850ch, 1tech(clause), thread=3, 2topics, attach"
    ))

    # =========================================================================
    # GROUP E (30 cases): 2 questions + body 300-500 chars + 1 tech + thread=1-2 + topics=2 + attach
    # q=70*0.20=14, body~(6-18)*0.20=1.2-3.7, tech=40*0.15=6, thread=20-40*0.10=2-4, topic=50*0.10=5, attach=5
    # Total ~33.2-37.7
    # =========================================================================

    # E1-E10: French
    cases.append((
        _pad_to(
            "Bonjour Henri,\n\nVeuillez trouver ci-joint le devis révisé pour le projet.\n\n"
            "D'autre part, le contrat est-il prêt pour signature ? "
            "Pouvez-vous confirmer la date de démarrage ?",
            350, "\n\nCordialement,\nSylvain Martel\nChargé d'affaires"
        ),
        "RE: Devis révisé - contrat",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 350ch, 1tech(contrat), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Annick,\n\nJe vous envoie les tableaux de bord mis à jour pour la revue.\n\n"
            "Par ailleurs, le KPI de satisfaction client est-il en hausse ? "
            "Avez-vous les chiffres de la semaine dernière ?",
            380, "\n\nBien à vous,\nDidier Lenoir\nResponsable qualité"
        ),
        "RE: Tableaux de bord - KPI revue",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 380ch, 1tech(KPI), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Nathalie,\n\nCi-joint le planning détaillé pour la migration du trimestre.\n\n"
            "Concernant les risques, pensez-vous que le calendrier est réaliste ? "
            "Avez-vous identifié des points bloquants à ce stade ?",
            380, "\n\nCordialement,\nPierre-Antoine Jolivet\nPMO"
        ),
        "RE: Planning migration Q2",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 380ch, 1tech(migration), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Josiane,\n\nVoici le document de synthèse pour le comité de la semaine.\n\n"
            "Par ailleurs, l'avenant au contrat cadre est-il validé par le juridique ? "
            "Pouvons-nous planifier la signature pour mardi ?",
            370, "\n\nBien cordialement,\nLionel Dupuis\nDirecteur juridique"
        ),
        "RE: Comité - avenant contrat cadre",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 370ch, 2tech(avenant,contrat), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Régis,\n\nJe vous joins le rapport d'analyse des performances du service.\n\n"
            "D'autre part, la facturation du mois précédent est-elle clôturée ? "
            "Pouvez-vous me transmettre le récapitulatif ?",
            380, "\n\nCordialement,\nChantal Brun\nDAF adjointe"
        ),
        "RE: Analyse performances - facturation",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 380ch, 1tech(facturation), thread=1, 2topics, attach"
    ))

    # E6-E10: English
    cases.append((
        _pad_to(
            "Hi Charles,\n\nPlease find attached the revised budget proposal.\n\n"
            "Also, has the ROI analysis been completed for the new initiative? "
            "Can you share the updated projections by Thursday?",
            350, "\n\nBest regards,\nLinda Moore\nFinance Manager"
        ),
        "RE: Budget proposal - ROI analysis",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 350ch, 1tech(ROI), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Beth,\n\nI am sending over the updated timeline for the release schedule.\n\n"
            "Regarding the testing phase, is the QA team ready to begin next week? "
            "Would you like to adjust the milestone dates?",
            370, "\n\nRegards,\nMartin Cruz\nRelease Manager"
        ),
        "RE: Release schedule - QA timeline",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(release), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Derek,\n\nAttached are the findings from the recent security audit.\n\n"
            "Additionally, have you reviewed the recommendations about the endpoint security? "
            "Do you agree with the proposed remediation timeline?",
            380, "\n\nBest,\nClaire Sullivan\nSecurity Analyst"
        ),
        "RE: Security audit findings - endpoint review",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 380ch, 1tech(endpoint), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Frank,\n\nPlease see the attached deployment checklist for your review.\n\n"
            "Also, is the staging environment ready for the pre-launch testing? "
            "Can we confirm the go-live date with the stakeholders?",
            370, "\n\nRegards,\nAnna Thompson\nProject Lead"
        ),
        "RE: Deployment checklist - staging prep",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(staging), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Paula,\n\nI have attached the summary of vendor compliance reviews.\n\n"
            "Regarding the NDA renewals, are they on track for this quarter? "
            "Should we prioritize any specific vendors for the upcoming audit?",
            370, "\n\nBest regards,\nRichard Blake\nVendor Manager"
        ),
        "RE: Vendor compliance - NDA renewals",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(NDA), thread=2, 2topics, attach"
    ))

    # E11-E20: More mixed, same pattern
    cases.append((
        _pad_to(
            "Bonjour Corinne,\n\nVoici en pièce jointe le récapitulatif des actions.\n\n"
            "Par ailleurs, le déploiement du correctif est-il prévu cette semaine ? "
            "Avez-vous besoin d'une validation supplémentaire ?",
            360, "\n\nCordialement,\nJacques Berger\nSupport technique"
        ),
        "RE: Récapitulatif actions - deploy correctif",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 360ch, 1tech(deploy), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Lucien,\n\nCi-joint les éléments pour le dossier de financement.\n\n"
            "D'autre part, la date de la prochaine revue de sprint est-elle fixée ? "
            "Pouvez-vous partager l'ordre du jour avec l'équipe ?",
            370, "\n\nBien à vous,\nRosalie Mercier\nContrôleuse de gestion"
        ),
        "RE: Dossier financement - revue sprint",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 370ch, 1tech(sprint), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Nathan,\n\nAttached is the risk assessment matrix we discussed.\n\n"
            "Also, have you finalized the database backup schedule? "
            "Can we verify the recovery procedures before the end of the month?",
            370, "\n\nBest,\nSophia Grant\nIT Manager"
        ),
        "RE: Risk assessment - database backup",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(database), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Eleanor,\n\nPlease find the draft communication plan attached.\n\n"
            "Additionally, has the Jira board been set up for the new workstream? "
            "Do you need any help with the initial task breakdown?",
            370, "\n\nRegards,\nBrandon Wells\nProgram Coordinator"
        ),
        "RE: Communication plan - Jira setup",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(jira), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Geneviève,\n\nJe vous envoie le plan de formation actualisé.\n\n"
            "Concernant les certifications, les sessions de formation AWS sont-elles ouvertes ? "
            "Pouvez-vous inscrire les trois collaborateurs identifiés ?",
            380, "\n\nCordialement,\nFranck Delorme\nRH formation"
        ),
        "RE: Plan formation - certifications AWS",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 380ch, 1tech(aws), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Jacob,\n\nI have enclosed the preliminary design documents.\n\n"
            "Also, is the pull request for the shared library ready for review? "
            "Can we schedule the code walkthrough for tomorrow morning?",
            370, "\n\nBest regards,\nMonika Schulz\nSoftware Engineer"
        ),
        "RE: Design docs - pull request review",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(pull request), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Jean-Pierre,\n\nVeuillez trouver ci-joint l'état des lieux.\n\n"
            "Par ailleurs, la résiliation du bail est-elle effective ? "
            "Pouvez-vous me confirmer les conditions de sortie ?",
            370, "\n\nBien cordialement,\nCéline Dupuis\nGestion immobilière"
        ),
        "RE: État des lieux - résiliation bail",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 370ch, 1tech(résiliation), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Brenda,\n\nPlease review the attached vendor assessment forms.\n\n"
            "Regarding the schema changes for the reporting module, are they final? "
            "Should we proceed with the implementation next week?",
            370, "\n\nRegards,\nTodd Nelson\nBusiness Analyst"
        ),
        "RE: Vendor assessment - reporting schema",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(schema), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour André,\n\nCi-joint le compte-rendu de la dernière revue.\n\n"
            "D'autre part, le bug signalé par le client a-t-il été corrigé ? "
            "Pouvez-vous tester la correction en environnement de recette ?",
            380, "\n\nCordialement,\nPatricia Vasseur\nQA Lead"
        ),
        "RE: Revue qualité - correction bug",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 380ch, 1tech(bug), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Angela,\n\nI am forwarding the meeting notes from today's session.\n\n"
            "Also, has the merge of the feature branch been completed? "
            "Can you verify that the automated tests passed?",
            370, "\n\nBest,\nKevin Stewart\nDev Lead"
        ),
        "RE: Meeting notes - feature merge",
        2, False, True, "STANDARD", 30, 49,
        "EN 2q, 370ch, 1tech(merge), thread=2, 2topics, attach"
    ))

    # E21-E30: Higher body, lower thread to stay in range
    cases.append((
        _pad_to(
            "Bonjour Serge,\n\nVeuillez trouver ci-joint le planning mis à jour pour la semaine "
            "prochaine. Les réunions ont été réorganisées pour tenir compte des disponibilités "
            "de chacun.\n\n"
            "Par ailleurs, le crash observé hier sur l'application mobile est-il résolu ? "
            "Avez-vous pu identifier la cause du problème ?",
            450, "\n\nCordialement,\nÉlodie Fournier\nCoordinatrice"
        ),
        "RE: Planning semaine - crash application",
        1, False, True, "STANDARD", 30, 49,
        "FR 2q, 450ch, 1tech(crash), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Ian,\n\nPlease find attached the status report for the current period. "
            "The project is on track and all major deliverables are progressing well.\n\n"
            "Regarding the refactoring effort, is it included in the current iteration? "
            "Do we need additional resources for the cleanup tasks?",
            420, "\n\nRegards,\nDiane Walker\nDelivery Manager"
        ),
        "RE: Status report - refactor planning",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 420ch, 1tech(refactor), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Colette,\n\nJe vous transmets le document de cadrage en pièce jointe. "
            "Il reprend l'ensemble des spécifications validées lors du dernier comité.\n\n"
            "D'autre part, l'exception signalée dans les logs de production est-elle critique ? "
            "Pouvez-vous confirmer qu'elle n'impacte pas les utilisateurs ?",
            420, "\n\nBien à vous,\nRobert Lamy\nIngénieur support"
        ),
        "RE: Document cadrage - exception production",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 420ch, 1tech(exception), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Roy,\n\nI am attaching the proposal that was discussed in yesterday's call. "
            "The scope has been refined based on the latest requirements.\n\n"
            "Also, has the debug session for the intermittent issue been scheduled? "
            "Would you like the QA team to prepare a reproduction scenario?",
            400, "\n\nBest regards,\nAlicia Bennett\nQA Manager"
        ),
        "RE: Proposal update - debug session",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 400ch, 1tech(debug), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Yves,\n\nCi-joint le rapport hebdomadaire avec les indicateurs de suivi. "
            "Les performances sont stables et en ligne avec nos objectifs.\n\n"
            "Concernant la stack trace identifiée ce matin, est-ce un problème récurrent ? "
            "Pouvez-vous vérifier que le correctif est bien déployé ?",
            420, "\n\nCordialement,\nMuriel Garnier\nIngénieur de production"
        ),
        "RE: Rapport hebdomadaire - stack trace",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 420ch, 1tech(stack trace), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Louise,\n\nPlease see the attached document with the latest figures. "
            "Everything is progressing according to the timeline we agreed upon.\n\n"
            "Additionally, is the HTTP endpoint for the webhook integration functional? "
            "Can you run a quick health check before the demo tomorrow?",
            400, "\n\nRegards,\nSean Cooper\nIntegration Specialist"
        ),
        "RE: Latest figures - HTTP endpoint check",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 400ch, 1tech(HTTP), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Michèle,\n\nJe vous envoie le fichier demandé en pièce jointe. "
            "Il contient les données consolidées pour la période concernée.\n\n"
            "Par ailleurs, la DPIA a-t-elle été réalisée pour ce nouveau traitement ? "
            "Pouvez-vous vérifier avec le service juridique ?",
            400, "\n\nCordialement,\nHervé Bonnet\nCorrespondant informatique"
        ),
        "RE: Données consolidées - DPIA vérification",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 400ch, 1tech(DPIA), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Samantha,\n\nAttached is the market research summary as requested. "
            "The key findings are highlighted in the executive summary section.\n\n"
            "Also, has the SDK integration been tested with the latest version? "
            "Do you need any support from the platform team?",
            400, "\n\nBest,\nDouglas Perry\nProduct Analyst"
        ),
        "RE: Market research - SDK integration",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 400ch, 1tech(SDK), thread=1, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Fabienne,\n\nVeuillez trouver ci-joint les éléments demandés pour la "
            "préparation de la réunion de vendredi prochain.\n\n"
            "D'autre part, le DPO a-t-il validé le traitement des données ? "
            "Pouvez-vous nous transmettre son avis avant la réunion ?",
            400, "\n\nBien à vous,\nGuy Lecomte\nChef de service"
        ),
        "RE: Préparation réunion - validation DPO",
        2, False, True, "STANDARD", 30, 49,
        "FR 2q, 400ch, 1tech(DPO), thread=2, 2topics, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Wendy,\n\nI have attached the outline for the upcoming workshop. "
            "The agenda includes sessions on best practices and process improvement.\n\n"
            "Regarding the Terraform templates, have they been updated for the new region? "
            "Can you validate the configuration before we proceed?",
            400, "\n\nKind regards,\nAlan Douglas\nCloud Engineer"
        ),
        "RE: Workshop outline - Terraform config",
        1, False, True, "STANDARD", 30, 49,
        "EN 2q, 400ch, 1tech(terraform), thread=1, 2topics, attach"
    ))

    # =========================================================================
    # GROUP F (100 cases): Programmatically varied combinations to reach 200 total
    # Patterns that reliably produce score 30-49:
    #   Pattern 1: 2q + body 500-700 + 1tech + thread=1 + 2topics (score ~30-35)
    #   Pattern 2: 1q + body 700-900 + 2tech + thread=1 + 2topics (score ~30-35)
    #   Pattern 3: 2q + body 400-600 + 0tech + thread=2 + 2topics + attach (score ~30-36)
    #   Pattern 4: 2q + body 300-500 + 1tech + thread=2 + 2topics + attach (score ~33-40)
    # =========================================================================

    # --- Pattern 1 variants (25 cases): 2q, ~600ch, 1tech, thread=1, 2topics ---
    _p1_fr = [
        ("Bonjour Alicia,\n\nNous avons reçu les spécifications techniques pour le module de reporting. "
         "L'équipe d'analyse a commencé la revue et prévoit de livrer ses commentaires d'ici lundi. "
         "Nous devons cependant clarifier plusieurs aspects du périmètre fonctionnel.\n\n"
         "Par ailleurs, le budget prévisionnel est-il validé par le comité ? "
         "Avez-vous reçu les retours du directeur financier ?",
         "RE: Module reporting - spécifications sprint", "sprint",
         "\n\nCordialement,\nBrice Humbert\nAnalyste fonctionnel"),
        ("Bonjour Éléonore,\n\nLe chantier de refonte de notre outil interne avance à bon rythme. "
         "Les workshops avec les utilisateurs clés ont permis de recueillir des retours précieux "
         "et l'équipe de développement travaille sur les premières itérations.\n\n"
         "Concernant le planning, est-il toujours réaliste de livrer avant fin avril ? "
         "Pouvez-vous me transmettre le tableau de suivi mis à jour ?",
         "RE: Refonte outil interne - planning contrat", "contrat",
         "\n\nBien à vous,\nStanislas Forget\nChef de projet MOA"),
        ("Bonjour Théo,\n\nJe reviens vers vous concernant l'organisation de la prochaine formation. "
         "Les supports pédagogiques sont finalisés et les convocations ont été envoyées. "
         "Nous attendons encore les confirmations de quelques participants.\n\n"
         "D'autre part, la salle de formation est-elle équipée du matériel nécessaire ? "
         "Le tarif du formateur externe a-t-il été négocié ?",
         "RE: Formation équipe - organisation tarif", "tarif",
         "\n\nCordialement,\nManon Girard\nRH développement"),
        ("Bonjour Charlotte,\n\nSuite à l'analyse des retours clients du dernier trimestre, "
         "plusieurs pistes d'amélioration ont été identifiées. L'équipe produit prépare "
         "une feuille de route pour adresser les points les plus fréquemment mentionnés.\n\n"
         "Par ailleurs, le taux de rétention est-il en progression ? "
         "Avez-vous les métriques de satisfaction du service après-vente ?",
         "RE: Retours clients - satisfaction KPI", "KPI",
         "\n\nBien cordialement,\nOlivier Blandin\nDirecteur expérience client"),
        ("Bonjour Édouard,\n\nLe comité de sélection s'est réuni hier et a retenu trois candidats "
         "pour le poste de responsable logistique. Les entretiens finaux sont programmés pour "
         "la semaine prochaine et les références seront vérifiées en parallèle.\n\n"
         "Concernant le processus d'intégration, est-il adapté à un démarrage rapide ? "
         "Le SLA avec le cabinet de recrutement a-t-il été respecté ?",
         "RE: Recrutement logistique - intégration SLA", "SLA",
         "\n\nCordialement,\nAgathe Lefeuvre\nResponsable recrutement"),
    ]
    _p1_en = [
        ("Hi Oliver,\n\nI wanted to provide an update on the vendor evaluation process. "
         "We have received proposals from all five shortlisted companies and the scoring "
         "is underway. The evaluation criteria have been weighted as discussed.\n\n"
         "Also, has the budget allocation for this fiscal year been confirmed? "
         "Is the ROI threshold still set at fifteen percent?",
         "RE: Vendor evaluation - budget ROI", "ROI",
         "\n\nBest regards,\nHarper Davis\nProcurement Specialist"),
        ("Hi Alyssa,\n\nThe customer feedback analysis for the new product line is complete. "
         "Overall sentiment is positive and the net promoter score exceeds our target. "
         "The marketing team is preparing a case study based on the results.\n\n"
         "Regarding the release date, is it still aligned with the trade show? "
         "Have the press materials been finalized?",
         "RE: Customer feedback - release timeline", "release",
         "\n\nRegards,\nConnor Walsh\nProduct Marketing"),
        ("Hi Isabelle,\n\nThank you for sharing the revised partnership terms. "
         "Our legal team has reviewed the key sections and provided initial feedback. "
         "The main areas requiring further discussion are the exclusivity period and termination.\n\n"
         "Additionally, do you have a preferred timeline for finalizing the NDA? "
         "Can we schedule a joint call with both legal teams?",
         "RE: Partnership terms - NDA finalization", "NDA",
         "\n\nBest,\nEthan Moore\nBD Manager"),
        ("Hi Claudia,\n\nThe quarterly business review presentation has been drafted. "
         "It covers revenue performance, pipeline health, and key wins for the period. "
         "The finance team has validated all figures and the charts are up to date.\n\n"
         "Also, is the production environment stable enough for the client demo? "
         "Should we prepare a backup demo environment?",
         "RE: QBR presentation - production demo", "production",
         "\n\nKind regards,\nNathan Hart\nAccount Executive"),
        ("Hi Maria,\n\nI have finalized the resource allocation plan for the upcoming quarter. "
         "The team will be split between maintenance and new feature development "
         "with a sixty-forty ratio as discussed.\n\n"
         "Regarding the deploy schedule, is Friday evening still the preferred window? "
         "Have the stakeholders been notified of the planned downtime?",
         "RE: Resource allocation - deploy schedule", "deploy",
         "\n\nRegards,\nSebastian Cole\nEngineering Manager"),
    ]
    for body_base, subj, _tech, sig in _p1_fr:
        cases.append((
            _pad_to(body_base, 600, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"FR 2q, 600ch, 1tech({_tech}), thread=1, 2topics [gen]"
        ))
    for body_base, subj, _tech, sig in _p1_en:
        cases.append((
            _pad_to(body_base, 600, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"EN 2q, 600ch, 1tech({_tech}), thread=1, 2topics [gen]"
        ))
    # Repeat pattern 1 with slight body length variation (650ch)
    _p1b_fr = [
        ("Bonjour Loïs,\n\nLe planning prévisionnel pour le trimestre a été mis à jour. "
         "Nous avons intégré les modifications demandées lors du dernier comité et pris en compte "
         "les retours des différentes directions. Le document est en cours de diffusion.\n\n"
         "D'autre part, la clause de pénalité a-t-elle été revue par le juridique ? "
         "Pouvez-vous nous confirmer le montant des pénalités applicables ?",
         "RE: Planning Q2 - clause pénalité", "clause",
         "\n\nCordialement,\nAntoine Leclère\nContrôleur de gestion"),
        ("Bonjour Solange,\n\nJe fais le point sur la campagne de communication interne. "
         "Les supports visuels ont été validés par la direction et les messages clés ont été "
         "définis en collaboration avec les managers de proximité.\n\n"
         "Par ailleurs, le renouvellement du contrat avec l'agence est-il acté ? "
         "Avez-vous obtenu des propositions alternatives ?",
         "RE: Communication interne - renouvellement contrat", "contrat",
         "\n\nBien à vous,\nPascale Vergnaud\nCom interne"),
        ("Bonjour Alexis,\n\nNous avons finalisé l'audit des processus de gestion des commandes. "
         "Les résultats montrent une amélioration notable des délais de traitement. "
         "Quelques ajustements restent à faire sur le circuit de validation.\n\n"
         "Concernant la facturation des commandes en retard, le processus est-il clarifié ? "
         "Pouvez-vous me donner les chiffres du mois de février ?",
         "RE: Audit processus - facturation retards", "facturation",
         "\n\nCordialement,\nRégine Martins\nContrôle interne"),
        ("Bonjour Pauline,\n\nSuite à la visite de nos locaux par le prestataire de maintenance, "
         "un rapport a été émis avec plusieurs recommandations. Les points urgents sont en cours "
         "de traitement et un planning d'intervention a été établi.\n\n"
         "D'autre part, l'avenant au contrat de maintenance est-il signé ? "
         "Pouvez-vous vérifier les conditions de garantie ?",
         "RE: Maintenance locaux - avenant contrat", "avenant",
         "\n\nBien cordialement,\nFrédéric Vasseur\nServices généraux"),
        ("Bonjour Stéphanie,\n\nLes indicateurs de performance du service client sont disponibles. "
         "Le temps moyen de résolution est en baisse et le taux de résolution au premier contact "
         "progresse de manière satisfaisante. L'équipe est motivée par ces résultats.\n\n"
         "Par ailleurs, le licensing de notre outil de ticketing doit-il être renouvelé ce mois-ci ? "
         "Avez-vous comparé les offres disponibles ?",
         "RE: Performance service client - licensing outil", "licensing",
         "\n\nCordialement,\nGérard Collin\nDirecteur service client"),
    ]
    _p1b_en = [
        ("Hi Zachary,\n\nThe annual compliance training program is ready for launch. "
         "All modules have been reviewed and approved by the legal department. "
         "The rollout schedule targets all departments within the next three weeks.\n\n"
         "Also, is the GDPR module mandatory for all employees or just managers? "
         "Have the completion deadlines been communicated to team leads?",
         "RE: Compliance training - GDPR rollout", "GDPR",
         "\n\nBest regards,\nMelody Brooks\nCompliance Coordinator"),
        ("Hi Priscilla,\n\nI wanted to follow up on the strategic planning session from last week. "
         "The key outcomes have been documented and distributed to all participants. "
         "Three priority initiatives were identified for the next fiscal year.\n\n"
         "Regarding the endpoint for the analytics dashboard, is it ready for review? "
         "Would you like to schedule a demo for the leadership team?",
         "RE: Strategic planning - analytics endpoint", "endpoint",
         "\n\nRegards,\nBrady Morgan\nStrategy Director"),
        ("Hi Regina,\n\nThe talent development program has been redesigned based on the latest "
         "organizational needs assessment. New learning paths have been created and the "
         "mentorship matching process has been streamlined.\n\n"
         "Additionally, has the migration of training records been completed? "
         "Can you confirm that all historical data is preserved?",
         "RE: Talent development - records migration", "migration",
         "\n\nBest,\nIvana Petrovic\nLearning Manager"),
        ("Hi Samira,\n\nThe sustainability report for the fiscal year has been compiled. "
         "Our carbon footprint has decreased by twelve percent compared to the previous year. "
         "The environmental committee has endorsed the findings and recommendations.\n\n"
         "Also, is the schema for the ESG data collection tool finalized? "
         "Do we need to adjust the reporting frequency?",
         "RE: Sustainability report - ESG schema", "schema",
         "\n\nKind regards,\nColin Murphy\nESG Officer"),
        ("Hi Wesley,\n\nThe customer loyalty program redesign is almost complete. "
         "The new tier structure has been modeled and the financial projections look promising. "
         "Early feedback from the focus group was overwhelmingly positive.\n\n"
         "Regarding the database for tracking loyalty points, is it scaled appropriately? "
         "Can you validate the data model before we proceed?",
         "RE: Loyalty program - database model", "database",
         "\n\nRegards,\nAudrey Chang\nLoyalty Program Manager"),
    ]
    for body_base, subj, _tech, sig in _p1b_fr:
        cases.append((
            _pad_to(body_base, 650, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"FR 2q, 650ch, 1tech({_tech}), thread=1, 2topics [gen-b]"
        ))
    for body_base, subj, _tech, sig in _p1b_en:
        cases.append((
            _pad_to(body_base, 650, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"EN 2q, 650ch, 1tech({_tech}), thread=1, 2topics [gen-b]"
        ))

    # --- Pattern 2 variants (25 cases): 1q, ~800ch, 2tech, thread=2, 2topics ---
    _p2_fr = [
        ("Bonjour Martial,\n\nLe bilan du premier trimestre montre des résultats encourageants "
         "pour le pôle innovation. Les projets en cours sont alignés avec la feuille de route "
         "stratégique et les premiers livrables ont été présentés aux sponsors. "
         "L'équipe a réalisé un excellent travail de prototypage et les retours du marché "
         "sont positifs. Le rapport détaillé sera diffusé en fin de semaine.\n\n"
         "Concernant le prochain sprint de développement, les stories Jira sont-elles priorisées ?",
         "RE: Bilan innovation Q1 - sprint Jira", "sprint", "jira",
         "\n\nCordialement,\nCélia Ferrand\nDirectrice innovation"),
        ("Bonjour Roselyne,\n\nSuite au comité de sécurité informatique, voici les principales "
         "actions retenues. La politique de gestion des mots de passe sera renforcée et une "
         "campagne de sensibilisation est prévue pour le mois prochain. Les tests d'intrusion "
         "annuels seront avancés à mai. La conformité RGPD est en bonne voie avec "
         "quatre-vingts pour cent des actions réalisées.\n\n"
         "Par ailleurs, le contrat avec notre fournisseur de sécurité arrive-t-il à échéance ?",
         "RE: Comité sécurité - RGPD contrat", "RGPD", "contrat",
         "\n\nBien à vous,\nVincent Masson\nRSSI"),
        ("Bonjour Laurence,\n\nJe vous informe que le projet de dématérialisation des factures "
         "entre dans sa phase finale. Les interfaces avec le système de facturation ont été "
         "testées et validées. Le flux de traitement automatique fonctionne correctement "
         "et les premiers envois réels sont prévus pour la semaine prochaine. "
         "Les retours des fournisseurs pilotes sont positifs.\n\n"
         "D'autre part, le tarif de la solution retenue inclut-il la maintenance corrective ?",
         "RE: Dématérialisation - facturation tarif", "facturation", "tarif",
         "\n\nCordialement,\nGabriel Durand\nResponsable achats"),
        ("Bonjour Anaïs,\n\nLe projet de refonte du parcours d'inscription en ligne progresse "
         "conformément au planning. Les maquettes ont été validées et le développement des "
         "principales fonctionnalités est en cours. L'intégration avec le module de paiement "
         "sera la prochaine étape. Le design a été pensé pour être accessible et intuitif "
         "pour tous les profils d'utilisateurs.\n\n"
         "Concernant le SLA de disponibilité, celui-ci est-il défini dans le cahier des charges ?",
         "RE: Refonte inscription - SLA disponibilité endpoint", "SLA", "endpoint",
         "\n\nBien cordialement,\nDavid Lecomte\nProduct Owner"),
        ("Bonjour Margaux,\n\nLa revue annuelle des fournisseurs stratégiques est terminée. "
         "Sur les vingt fournisseurs évalués, quinze obtiennent une note satisfaisante. "
         "Les cinq restants font l'objet de plans d'amélioration spécifiques. "
         "Le tableau de synthèse sera présenté en comité achats la semaine prochaine. "
         "Les contrats en cours seront renégociés dans la foulée.\n\n"
         "Par ailleurs, la résiliation du contrat avec le fournisseur B est-elle en cours ?",
         "RE: Revue fournisseurs - résiliation contrat B", "résiliation", "contrat",
         "\n\nCordialement,\nNicolas Perrot\nAcheteur senior"),
    ]
    _p2_en = [
        ("Hi Vanessa,\n\nThe employee engagement survey analysis is now complete and the "
         "results have been shared with the leadership team. Overall scores are up by eight "
         "points compared to last year. Key areas of improvement include career development "
         "and internal communication. The action plan has been drafted and individual team "
         "workshops are scheduled for the coming weeks.\n\n"
         "Also, has the sprint for the new HR portal been planned?",
         "RE: Engagement survey - HR sprint Jira", "sprint", "jira",
         "\n\nBest regards,\nVictor Ramirez\nHR Analytics"),
        ("Hi Alexandra,\n\nI am pleased to share that the new procurement platform has gone "
         "live. All major workflows have been tested and the vendor onboarding process is "
         "fully automated. Training sessions have been completed for all buying teams "
         "and the adoption rate is encouraging. The initial feedback suggests significant "
         "time savings on routine purchase orders.\n\n"
         "Regarding the API integration with our ERP, is it functioning correctly?",
         "RE: Procurement platform launch - API endpoint", "API", "endpoint",
         "\n\nRegards,\nRachel Stewart\nProcurement Director"),
        ("Hi Jonathan,\n\nThe data governance framework has been finalized and approved by "
         "the steering committee. All data domains have been mapped to their respective "
         "owners and the data quality rules are being implemented progressively. "
         "The metadata catalog is now accessible to all teams and training materials "
         "have been published on the internal knowledge base.\n\n"
         "Also, has the database audit for compliance purposes been scheduled?",
         "RE: Data governance - database audit SQL", "database", "SQL",
         "\n\nBest,\nLinda Zhang\nChief Data Officer"),
        ("Hi Pamela,\n\nThe infrastructure cost optimization project has delivered "
         "better than expected results. Monthly cloud spend has been reduced by "
         "twenty-two percent through rightsizing and reserved instance purchases. "
         "The savings will be reinvested in new development initiatives. "
         "The team has also implemented automated cost alerts to prevent overspending.\n\n"
         "Regarding the Kubernetes cluster configuration, is it optimized for our workloads?",
         "RE: Cost optimization - Kubernetes Docker workloads", "kubernetes", "docker",
         "\n\nKind regards,\nRobert Kim\nFinOps Manager"),
        ("Hi Christina,\n\nThe annual technology roadmap review has been completed. "
         "We have aligned all planned initiatives with the business strategy and "
         "identified key dependencies between projects. The budget has been allocated "
         "across four main investment areas: infrastructure, security, data, and customer "
         "experience. The executive summary is ready for board review.\n\n"
         "Also, is the GCP migration timeline still realistic given our current resources?",
         "RE: Tech roadmap - GCP Azure migration", "gcp", "azure",
         "\n\nRegards,\nMichael Torres\nCTO Office"),
    ]
    for body_base, subj, t1, t2, sig in _p2_fr:
        cases.append((
            _pad_to(body_base, 800, sig),
            subj, 2, False, False, "STANDARD", 30, 49,
            f"FR 1q, 800ch, 2tech({t1},{t2}), thread=2, 2topics [gen]"
        ))
    for body_base, subj, t1, t2, sig in _p2_en:
        cases.append((
            _pad_to(body_base, 800, sig),
            subj, 2, False, False, "STANDARD", 30, 49,
            f"EN 1q, 800ch, 2tech({t1},{t2}), thread=2, 2topics [gen]"
        ))
    # Pattern 2 with longer body (850ch)
    _p2b_fr = [
        ("Bonjour Maryse,\n\nJe souhaitais vous faire part de l'état d'avancement du projet "
         "de centralisation des achats. Les procédures ont été harmonisées entre les différentes "
         "filiales et le catalogue commun est opérationnel. Les premiers retours des acheteurs "
         "locaux sont positifs et le taux d'adoption dépasse nos prévisions initiales. "
         "La prochaine étape sera l'intégration du module de gestion des marchés.\n\n"
         "D'autre part, l'avenant au contrat cadre fournisseur a-t-il été transmis au juridique ?",
         "RE: Centralisation achats - avenant contrat cadre", "avenant", "contrat",
         "\n\nCordialement,\nCamille Beaumont\nDirectrice achats groupe"),
        ("Bonjour Viviane,\n\nLe projet de transformation digitale du service comptable franchit "
         "une étape importante. La numérisation des archives est terminée et le nouveau workflow "
         "de validation des factures est en production depuis lundi. Les performances du système "
         "sont au rendez-vous et aucun incident majeur n'a été signalé. "
         "Les équipes s'approprient rapidement les nouveaux outils.\n\n"
         "Par ailleurs, le tarif mensuel du service de numérisation doit-il être renégocié ?",
         "RE: Transformation digitale compta - production tarif", "production", "tarif",
         "\n\nBien à vous,\nPhilippe Arnaud\nDAF groupe"),
        ("Bonjour Hervé,\n\nVoici le bilan intermédiaire du programme de modernisation "
         "de notre système d'information. Les chantiers prioritaires sont en bonne voie : "
         "la migration du datacenter est achevée à soixante-quinze pour cent et les premiers "
         "services sont opérationnels sur la nouvelle plateforme. Les performances mesurées "
         "sont conformes aux engagements pris dans le cahier des charges.\n\n"
         "Concernant le KPI de disponibilité, est-il suivi de manière automatisée ?",
         "RE: Modernisation SI - migration KPI disponibilité", "migration", "KPI",
         "\n\nCordialement,\nLaetitia Boucher\nDSI adjointe"),
    ]
    _p2b_en = [
        ("Hi Ronald,\n\nThe global supply chain optimization initiative has reached its "
         "second milestone. Inventory levels have been reduced by fifteen percent while "
         "maintaining service levels above target. The new forecasting model has been "
         "validated and is now being rolled out to regional warehouses. "
         "Logistics partners have been briefed on the new processes.\n\n"
         "Also, has the SLA with the primary carrier been renegotiated?",
         "RE: Supply chain optimization - SLA licensing carrier", "SLA", "licensing",
         "\n\nBest regards,\nDenise Walker\nSupply Chain VP"),
        ("Hi Carolyn,\n\nThe digital marketing analytics platform is now fully operational. "
         "All campaign data sources have been connected and the real-time dashboards are "
         "providing actionable insights. Attribution modeling has been improved and the "
         "team can now track the full customer journey. Early results show a significant "
         "improvement in campaign ROI measurement accuracy.\n\n"
         "Regarding the HTTPS endpoints for the tracking pixels, are they all validated?",
         "RE: Marketing analytics - ROI HTTPS tracking", "ROI", "HTTPS",
         "\n\nRegards,\nBernard Taylor\nDigital Analytics Director"),
    ]
    for body_base, subj, t1, t2, sig in _p2b_fr:
        cases.append((
            _pad_to(body_base, 850, sig),
            subj, 2, False, False, "STANDARD", 30, 49,
            f"FR 1q, 850ch, 2tech({t1},{t2}), thread=2, 2topics [gen-b]"
        ))
    for body_base, subj, t1, t2, sig in _p2b_en:
        cases.append((
            _pad_to(body_base, 850, sig),
            subj, 2, False, False, "STANDARD", 30, 49,
            f"EN 1q, 850ch, 2tech({t1},{t2}), thread=2, 2topics [gen-b]"
        ))

    # --- Pattern 3 variants (25 cases): 2q, ~500ch, 0tech, thread=2-3, 2topics, attach ---
    _p3_fr = [
        ("Bonjour Odile,\n\nJe vous transmets le document de synthèse en pièce jointe. "
         "Les chiffres du premier trimestre sont conformes aux prévisions et l'équipe "
         "a atteint ses objectifs principaux.\n\n"
         "Par ailleurs, souhaitez-vous que nous ajoutions une annexe détaillée ? "
         "Pouvez-vous confirmer la date de présentation au comité ?",
         "RE: Synthèse Q1 - présentation comité",
         "\n\nCordialement,\nLoïc Lambert\nContrôleur de gestion"),
        ("Bonjour Yannick,\n\nCi-joint le planning révisé pour l'événement de juin. "
         "Nous avons intégré les modifications demandées par les partenaires et les "
         "lieux ont été confirmés pour toutes les sessions.\n\n"
         "D'autre part, le budget de communication est-il suffisant pour la promotion ? "
         "Avez-vous validé la liste des intervenants externes ?",
         "RE: Événement juin - planning révisé",
         "\n\nBien à vous,\nBérénice Moreau\nÉvénementiel"),
        ("Bonjour Christiane,\n\nVeuillez trouver ci-joint le comparatif des offres "
         "pour le renouvellement de notre flotte automobile. Les trois propositions "
         "sont détaillées avec les coûts sur trois et cinq ans.\n\n"
         "Concernant les critères environnementaux, faut-il privilégier les véhicules hybrides ? "
         "Pouvez-vous soumettre ce comparatif à la direction générale ?",
         "RE: Flotte auto - comparatif offres",
         "\n\nCordialement,\nJean-Marc Guillot\nServices généraux"),
        ("Bonjour Cécilia,\n\nJe vous envoie le bilan des formations du mois dernier "
         "en pièce jointe. Le taux de participation est en hausse de huit pour cent "
         "et les évaluations à chaud sont excellentes.\n\n"
         "Par ailleurs, les sessions d'avril sont-elles toutes planifiées ? "
         "Avez-vous besoin de formateurs supplémentaires pour les ateliers pratiques ?",
         "RE: Bilan formations - sessions avril",
         "\n\nBien cordialement,\nRégis Carpentier\nRH formation"),
        ("Bonjour Gaëtan,\n\nCi-joint le résumé des actions en cours pour le projet d'extension "
         "des bureaux. Les plans ont été validés par l'architecte et le permis de construire "
         "est en instruction auprès de la mairie.\n\n"
         "D'autre part, le devis du sous-traitant électricité est-il raisonnable ? "
         "Pouvons-nous lancer la consultation pour le second lot ?",
         "RE: Extension bureaux - actions en cours",
         "\n\nCordialement,\nNicole Picard\nResponsable immobilier"),
        ("Bonjour Josette,\n\nVeuillez trouver ci-joint le rapport d'activité du service "
         "commercial pour le mois de février. Les objectifs ont été atteints à "
         "cent dix pour cent grâce aux efforts de prospection de l'équipe terrain.\n\n"
         "Par ailleurs, la campagne de prospection de mars est-elle lancée ? "
         "Avez-vous ciblé les nouveaux segments identifiés lors du séminaire ?",
         "RE: Rapport activité commercial",
         "\n\nBien à vous,\nPascal Legrand\nDirecteur commercial adjoint"),
        ("Bonjour Murielle,\n\nJe vous fais parvenir le planning des congés de l'équipe "
         "pour la période estivale. Les demandes ont été consolidées et les rotations "
         "ont été validées avec chaque manager.\n\n"
         "Concernant les remplacements, les intérimaires sont-ils disponibles aux dates prévues ? "
         "Devons-nous anticiper des ajustements en fonction de la charge de travail ?",
         "RE: Planning congés été - remplacement",
         "\n\nCordialement,\nSylviane Petit\nAssistante RH"),
    ]
    _p3_en = [
        ("Hi Gregory,\n\nPlease find attached the quarterly progress report for the "
         "expansion project. All milestones are on track and the budget is within "
         "the approved limits. The team has been very productive this period.\n\n"
         "Also, do you agree with the proposed adjustments to the timeline? "
         "Would you like to review the risk register before the next checkpoint?",
         "RE: Expansion project - progress report",
         "\n\nBest regards,\nMelissa Turner\nProject Director"),
        ("Hi Kathleen,\n\nI am attaching the summary of the supplier audit findings. "
         "Overall compliance is good but there are a few areas where corrective actions "
         "are needed. The detailed action plan is included.\n\n"
         "Additionally, have you reviewed the follow-up deadlines? "
         "Can we discuss the escalation process for non-conformities?",
         "RE: Supplier audit summary",
         "\n\nRegards,\nDarren Woods\nQuality Assurance"),
        ("Hi Martha,\n\nAttached is the draft agenda for the annual strategy offsite. "
         "The program includes interactive workshops, executive presentations, and "
         "team-building activities over two days.\n\n"
         "Regarding the venue, is the preferred location available for our dates? "
         "Should we arrange transportation for participants?",
         "RE: Strategy offsite - draft agenda",
         "\n\nBest,\nTimothy Black\nChief of Staff"),
        ("Hi Eugene,\n\nPlease see the attached market analysis for the Southeast region. "
         "The data indicates strong growth potential and several untapped segments "
         "that align with our product offering.\n\n"
         "Also, have you identified potential distribution partners in the region? "
         "Do you need additional market research on specific segments?",
         "RE: Market analysis Southeast",
         "\n\nKind regards,\nSophia Reynolds\nMarket Intelligence"),
        ("Hi Brenda,\n\nI have compiled the insurance renewal documentation and attached "
         "it for your review. The current policies have been benchmarked against "
         "market rates and our coverage is competitive.\n\n"
         "Regarding the deductible structure, is it aligned with our risk appetite? "
         "Should we explore umbrella coverage for the international operations?",
         "RE: Insurance renewal documentation",
         "\n\nRegards,\nCharles Hunt\nRisk Management"),
        ("Hi Constance,\n\nPlease find the updated employee handbook attached. "
         "The revisions incorporate the new remote work policy and updated "
         "benefits information that were approved last month.\n\n"
         "Additionally, has the legal review been completed for the new sections? "
         "Would you like to schedule an all-hands to communicate the changes?",
         "RE: Employee handbook update",
         "\n\nBest regards,\nPatrick Stone\nHR Director"),
    ]
    for body_base, subj, sig in _p3_fr:
        cases.append((
            _pad_to(body_base, 500, sig),
            subj, 2, False, True, "STANDARD", 30, 49,
            "FR 2q, 500ch, 0tech, thread=2, 2topics, attach [gen]"
        ))
    for body_base, subj, sig in _p3_en:
        cases.append((
            _pad_to(body_base, 500, sig),
            subj, 2, False, True, "STANDARD", 30, 49,
            "EN 2q, 500ch, 0tech, thread=2, 2topics, attach [gen]"
        ))

    # --- Pattern 4 variants (25 cases): 2q, ~400ch, 1tech, thread=2, 2topics, attach ---
    _p4_fr = [
        ("Bonjour Danièle,\n\nCi-joint le tableau de bord mensuel.\n\n"
         "D'autre part, le bug signalé vendredi est-il résolu ? "
         "Pouvez-vous faire un retour à l'équipe support ?",
         "RE: Tableau de bord - suivi bug", "bug",
         "\n\nCordialement,\nAlban Renaud\nAnalyste"),
        ("Bonjour Jérémie,\n\nVeuillez trouver ci-joint le récapitulatif financier.\n\n"
         "Par ailleurs, le sprint en cours est-il conforme aux prévisions ? "
         "Avez-vous besoin de ressources complémentaires ?",
         "RE: Récap financier - sprint", "sprint",
         "\n\nBien à vous,\nBénédicte Fleury\nFinance"),
        ("Bonjour Flora,\n\nJe vous transmets le document de cadrage en annexe.\n\n"
         "Concernant le déploiement, est-il toujours prévu pour vendredi ? "
         "Pouvez-vous valider avec l'équipe technique ?",
         "RE: Document cadrage - deploy", "deploy",
         "\n\nCordialement,\nArthur Lefranc\nChef de projet"),
        ("Bonjour Ludovic,\n\nCi-joint les résultats de l'enquête de satisfaction.\n\n"
         "D'autre part, la résiliation de l'ancien outil est-elle effective ? "
         "Avez-vous reçu la confirmation du fournisseur ?",
         "RE: Enquête satisfaction - résiliation outil", "résiliation",
         "\n\nBien cordialement,\nSabine Gérard\nQualité"),
        ("Bonjour Émilie,\n\nVoici le planning mis à jour en pièce jointe.\n\n"
         "Par ailleurs, l'exception signalée dans les logs est-elle corrigée ? "
         "Pouvez-vous vérifier que les tests passent correctement ?",
         "RE: Planning - correction exception", "exception",
         "\n\nCordialement,\nTanguy Maillet\nDev senior"),
        ("Bonjour Agathe,\n\nJe vous envoie le devis révisé en annexe.\n\n"
         "D'autre part, le KPI de satisfaction a-t-il évolué depuis le dernier reporting ? "
         "Pouvez-vous partager les derniers chiffres avec l'équipe ?",
         "RE: Devis révisé - KPI satisfaction", "KPI",
         "\n\nBien à vous,\nVinciane Moreau\nCommerciale"),
    ]
    _p4_en = [
        ("Hi Nicole,\n\nPlease see attached the updated specifications.\n\n"
         "Also, has the database schema been finalized for the new module? "
         "Can you confirm the target date for the beta release?",
         "RE: Specifications - database schema", "database",
         "\n\nBest regards,\nBrandon Lee\nProduct Owner"),
        ("Hi Teresa,\n\nI have attached the compliance checklist for your review.\n\n"
         "Regarding the error logging configuration, has it been updated? "
         "Do you need help with the implementation?",
         "RE: Compliance checklist - error logging", "error",
         "\n\nRegards,\nKyle Robinson\nQA Engineer"),
        ("Hi Leonard,\n\nPlease find the meeting minutes attached.\n\n"
         "Also, is the staging environment ready for the demo tomorrow? "
         "Can we run a quick dry run this afternoon?",
         "RE: Meeting minutes - staging demo", "staging",
         "\n\nBest,\nCarolyn Hayes\nScrum Master"),
        ("Hi Donna,\n\nAttached are the test results from this morning.\n\n"
         "Regarding the merge conflict on the main branch, has it been resolved? "
         "Should we delay the deployment until it is fixed?",
         "RE: Test results - merge conflict", "merge",
         "\n\nKind regards,\nSteve Collins\nRelease Lead"),
        ("Hi Jeffrey,\n\nI am sending the cost breakdown attached.\n\n"
         "Also, is the refactoring of the payment module on schedule? "
         "Do you anticipate any delays in the delivery?",
         "RE: Cost breakdown - refactor schedule", "refactor",
         "\n\nRegards,\nMonica Hill\nFinancial Analyst"),
        ("Hi Lorraine,\n\nPlease find the incident report attached.\n\n"
         "Additionally, has the rollback procedure been documented? "
         "Can the on-call team access the runbook?",
         "RE: Incident report - rollback procedure", "rollback",
         "\n\nBest regards,\nRandall Price\nSRE"),
        ("Hi Catherine,\n\nAttached is the vendor scorecard for this quarter.\n\n"
         "Also, has the NDA with the new supplier been executed? "
         "Do we need to expedite the procurement process?",
         "RE: Vendor scorecard - NDA execution", "NDA",
         "\n\nRegards,\nAntonio Garcia\nVendor Relations"),
    ]
    for body_base, subj, _tech, sig in _p4_fr:
        cases.append((
            _pad_to(body_base, 400, sig),
            subj, 2, False, True, "STANDARD", 30, 49,
            f"FR 2q, 400ch, 1tech({_tech}), thread=2, 2topics, attach [gen]"
        ))
    for body_base, subj, _tech, sig in _p4_en:
        cases.append((
            _pad_to(body_base, 400, sig),
            subj, 2, False, True, "STANDARD", 30, 49,
            f"EN 2q, 400ch, 1tech({_tech}), thread=2, 2topics, attach [gen]"
        ))

    # --- Pattern 5 (39 cases to reach 200): 2q, ~550ch, 1tech, thread=1, 2topics ---
    # Score calc: q=70*0.20=14 + body~(21)*0.20=4.3 + tech=40*0.15=6 + thread=20*0.10=2 + topic=50*0.10=5 = ~31.3
    _p5_bodies = [
        # (body_text, subject, tech_keyword, signature, lang)
        ("Bonjour Armand,\n\nLe comité d'investissement se tiendra mercredi prochain. "
         "L'ordre du jour a été envoyé aux membres et les dossiers sont en cours de finalisation. "
         "Nous devons préparer les éléments de décision.\n\n"
         "Concernant le ROI du dernier projet, est-il conforme aux prévisions ? "
         "Avez-vous les chiffres consolidés ?",
         "RE: Comité investissement - ROI", "ROI", "\n\nCordialement,\nPriscilla Bonnet\nInvestissements", "FR"),
        ("Hi Gina,\n\nThe annual performance reviews are scheduled to begin next week. "
         "All managers have received the templates and guidelines for conducting the assessments. "
         "The calibration sessions will follow two weeks later.\n\n"
         "Also, has the rollback plan for the new review system been prepared? "
         "Should we conduct a pilot run first?",
         "RE: Performance reviews - rollback plan", "rollback", "\n\nBest,\nHarold Kim\nHR Operations", "EN"),
        ("Bonjour Denise,\n\nLes résultats de l'enquête de satisfaction interne sont disponibles. "
         "Le taux de participation atteint soixante-huit pour cent et les scores sont en hausse "
         "sur la majorité des critères évalués.\n\n"
         "Par ailleurs, le contrat avec le prestataire d'enquête est-il renouvelé ? "
         "Pouvez-vous vérifier les tarifs pour l'année prochaine ?",
         "RE: Enquête satisfaction - contrat prestataire", "contrat", "\n\nBien à vous,\nRaymond Vernier\nQVT", "FR"),
        ("Hi Gwendolyn,\n\nI am sharing the latest figures from the customer acquisition campaign. "
         "The cost per acquisition has decreased by twelve percent and the conversion rate "
         "is tracking above the quarterly target.\n\n"
         "Additionally, has the deploy of the new attribution model been validated? "
         "Do you need the analytics team to run additional tests?",
         "RE: Acquisition campaign - deploy attribution", "deploy", "\n\nRegards,\nClayton Ross\nGrowth", "EN"),
        ("Bonjour Roxane,\n\nJe fais suite à votre demande de renseignements sur le programme "
         "de fidélisation. Les conditions générales ont été mises à jour et le nouveau barème "
         "de points sera applicable dès le premier avril.\n\n"
         "D'autre part, le renouvellement du partenariat avec la compagnie aérienne est-il signé ? "
         "Avez-vous obtenu des conditions préférentielles ?",
         "RE: Programme fidélisation - renouvellement partenariat", "renouvellement", "\n\nCordialement,\nAurélien Blanc\nPartenariats", "FR"),
        ("Hi Dominic,\n\nThe office network upgrade has been completed ahead of schedule. "
         "All floors are now connected via the new fiber backbone and WiFi coverage has "
         "been significantly improved throughout the building.\n\n"
         "Also, has the SLA with the internet provider been renegotiated? "
         "Can you share the new bandwidth specifications?",
         "RE: Network upgrade - SLA bandwidth", "SLA", "\n\nBest regards,\nAbigail Lane\nIT Infrastructure", "EN"),
        ("Bonjour Lauriane,\n\nLe bilan de la démarche qualité est positif pour cette année. "
         "Nous avons obtenu la certification attendue et les audits de suivi sont programmés. "
         "L'engagement des équipes a été exemplaire tout au long du processus.\n\n"
         "Concernant le licensing des outils de qualité, le budget est-il bouclé ? "
         "Pouvez-vous me transmettre le comparatif des éditeurs ?",
         "RE: Démarche qualité - licensing outils", "licensing", "\n\nCordialement,\nFabrice Delmas\nQualité", "FR"),
        ("Hi Alison,\n\nThe succession planning exercise for senior leadership has been completed. "
         "We have identified potential successors for all critical roles and development "
         "plans are being crafted for each individual.\n\n"
         "Regarding the database of leadership competencies, has it been updated? "
         "Would you like to review it during our next HR committee?",
         "RE: Succession planning - leadership database", "database", "\n\nRegards,\nPatrick Burns\nTalent VP", "EN"),
        ("Bonjour Micheline,\n\nLa veille concurrentielle du mois de mars est prête. "
         "Nous avons identifié trois nouvelles tendances significatives sur notre marché "
         "et deux mouvements stratégiques de la part de nos principaux concurrents.\n\n"
         "Par ailleurs, le tarif de l'abonnement au service de veille doit-il être renégocié ? "
         "Avez-vous comparé avec d'autres prestataires ?",
         "RE: Veille concurrentielle - tarif abonnement", "tarif", "\n\nBien cordialement,\nGaston Lemaire\nStratégie", "FR"),
        ("Hi Russell,\n\nThe ESG reporting framework has been aligned with the latest regulatory "
         "requirements. All metrics have been validated by the external auditor and the "
         "publication timeline is confirmed.\n\n"
         "Also, has the schema for data collection from subsidiaries been standardized? "
         "Can you coordinate with the regional offices?",
         "RE: ESG reporting - data schema", "schema", "\n\nBest,\nEleanor Simmons\nSustainability", "EN"),
        ("Bonjour Nelly,\n\nJe reviens vers vous concernant l'organisation du salon professionnel. "
         "Le stand a été réservé et le design est en cours de validation. Les goodies et supports "
         "de communication seront livrés la semaine précédant l'événement.\n\n"
         "D'autre part, l'avenant au contrat avec l'organisateur est-il signé ? "
         "Pouvez-vous me confirmer les horaires d'installation ?",
         "RE: Salon professionnel - avenant organisateur", "avenant", "\n\nCordialement,\nDominique Ferrer\nMarketing", "FR"),
        ("Hi Loretta,\n\nI wanted to update you on the corporate training initiative. "
         "The e-learning platform has been configured and all mandatory courses "
         "are now available. Enrollment rates are encouraging so far.\n\n"
         "Regarding the endpoint for SSO integration, is it configured correctly? "
         "Do we need to test it with all identity providers?",
         "RE: Training initiative - SSO endpoint", "endpoint", "\n\nKind regards,\nFrederick Cole\nLearning Tech", "EN"),
        ("Bonjour Laurette,\n\nLe projet de modernisation de l'espace d'accueil est en bonne voie. "
         "Les travaux ont débuté et le planning est respecté. Les visiteurs sont orientés "
         "vers l'entrée temporaire sans difficulté.\n\n"
         "Par ailleurs, le crash de l'application de réservation des salles est-il résolu ? "
         "Pouvez-vous vérifier avec le prestataire technique ?",
         "RE: Modernisation accueil - crash appli réservation", "crash", "\n\nBien à vous,\nRoland Dubois\nAccueil", "FR"),
        ("Hi Tabitha,\n\nThe customer data platform implementation is moving forward smoothly. "
         "All data sources have been connected and the initial data quality scores are "
         "exceeding expectations. The marketing team is already creating segments.\n\n"
         "Also, has the GDPR consent management module been activated? "
         "Do we have the data processing agreements in place?",
         "RE: CDP implementation - GDPR consent", "GDPR", "\n\nRegards,\nJeremy Brooks\nMarTech Lead", "EN"),
        ("Bonjour Joséphine,\n\nLes résultats financiers du premier semestre seront présentés "
         "au conseil d'administration la semaine prochaine. Les comptes ont été clôturés "
         "dans les délais et validés par les commissaires aux comptes.\n\n"
         "Concernant la clause d'ajustement de prix, est-elle applicable cette année ? "
         "Pouvez-vous préparer une simulation ?",
         "RE: Résultats financiers - clause ajustement", "clause", "\n\nCordialement,\nBernard Vasseur\nDAF", "FR"),
        ("Hi Harriet,\n\nThe mobile app beta testing phase is complete and the feedback "
         "has been overwhelmingly positive. Key metrics including crash rate, load time, "
         "and user retention are all within acceptable thresholds.\n\n"
         "Regarding the release to the app stores, is the submission process ready? "
         "Have all the required screenshots been prepared?",
         "RE: Mobile app beta - release submission", "release", "\n\nBest regards,\nDwight Palmer\nMobile PM", "EN"),
        ("Bonjour Renée,\n\nLe programme d'intrapreneuriat a suscité un fort intérêt interne. "
         "Dix-huit projets ont été soumis et le comité de sélection a retenu six finalistes. "
         "Les présentations finales auront lieu le mois prochain.\n\n"
         "D'autre part, la migration des documents vers la nouvelle plateforme est-elle terminée ? "
         "Pouvez-vous me donner un état d'avancement ?",
         "RE: Intrapreneuriat - migration documents", "migration", "\n\nBien cordialement,\nSéverine Roux\nInnovation", "FR"),
        ("Hi Naomi,\n\nThe supply chain risk assessment has been updated to reflect current "
         "market conditions. Two critical suppliers have been flagged for elevated risk "
         "and contingency plans have been prepared.\n\n"
         "Also, has the error rate in the order management system decreased since the patch? "
         "Do you have the latest reliability metrics?",
         "RE: Supply chain risk - error rate metrics", "error", "\n\nRegards,\nVernon Hart\nSupply Chain", "EN"),
        ("Bonjour Madeleine,\n\nSuite à la réorganisation du service, les nouvelles fiches de poste "
         "ont été validées par les managers. Les entretiens individuels de transition sont "
         "programmés sur les deux prochaines semaines.\n\n"
         "Par ailleurs, le NDA avec le cabinet de conseil en restructuration est-il signé ? "
         "Pouvez-vous me transmettre une copie ?",
         "RE: Réorganisation - NDA cabinet conseil", "NDA", "\n\nCordialement,\nThierry Morel\nDRH adjoint", "FR"),
        ("Hi Bonnie,\n\nThe brand refresh project is on track for the Q2 launch. "
         "All visual assets have been redesigned and the brand guidelines document "
         "has been updated. Partner communications will begin next week.\n\n"
         "Regarding the XML feed for the partner portal, has it been updated with new assets? "
         "Can you verify that all thumbnails are rendering correctly?",
         "RE: Brand refresh - XML partner feed", "XML", "\n\nBest,\nWarren Blake\nBrand Manager", "EN"),
        ("Bonjour Élise,\n\nLe processus d'onboarding des nouveaux collaborateurs a été revu. "
         "Le parcours d'intégration est désormais plus structuré et les retours des dernières "
         "promotions sont très positifs.\n\n"
         "Concernant la facturation des formations externes, est-elle centralisée ? "
         "Pouvez-vous me donner le montant engagé ce trimestre ?",
         "RE: Onboarding - facturation formations", "facturation", "\n\nBien à vous,\nHugo Marchand\nRH", "FR"),
        ("Hi Melody,\n\nI am pleased to share that the customer portal redesign has received "
         "excellent feedback in user testing. Navigation clarity and task completion rates "
         "have both improved significantly.\n\n"
         "Also, has the CSV export feature for reporting been tested? "
         "Should we add it to the next iteration scope?",
         "RE: Portal redesign - CSV reporting", "CSV", "\n\nRegards,\nClifford Green\nUX Lead", "EN"),
        ("Bonjour Adeline,\n\nLa négociation avec le nouveau fournisseur de matières premières "
         "avance bien. Les conditions tarifaires proposées sont compétitives et les délais de "
         "livraison correspondent à nos besoins.\n\n"
         "D'autre part, le DPO a-t-il validé le traitement des données fournisseur ? "
         "Pouvez-vous me confirmer que nous sommes en conformité ?",
         "RE: Négociation fournisseur - DPO conformité", "DPO", "\n\nCordialement,\nGisèle Martin\nAchats", "FR"),
        ("Hi Candice,\n\nThe year-end financial close process is progressing well. "
         "All journal entries have been posted and the reconciliation is nearly complete. "
         "The auditors will begin their fieldwork next Monday.\n\n"
         "Regarding the HTTP connection to the banking platform, is it secure? "
         "Can you run a connectivity test before the audit period?",
         "RE: Year-end close - HTTP banking connection", "HTTP", "\n\nBest regards,\nMorgan Fields\nController", "EN"),
        ("Bonjour Yolande,\n\nLe rapport environnemental annuel est en cours de rédaction. "
         "Les données ont été collectées auprès de tous les sites et les calculs "
         "d'empreinte carbone sont terminés.\n\n"
         "Par ailleurs, la résiliation du contrat avec l'ancien auditeur est-elle effective ? "
         "Pouvez-vous me transmettre la lettre de clôture ?",
         "RE: Rapport environnemental - résiliation auditeur", "résiliation", "\n\nBien cordialement,\nGilbert Morin\nRSE", "FR"),
        ("Hi Ellen,\n\nThe knowledge management initiative is gaining traction across departments. "
         "The internal wiki has seen a forty percent increase in contributions and the "
         "quality of articles has improved noticeably.\n\n"
         "Also, has the SDK for the search functionality been integrated? "
         "Do we need to adjust the indexing configuration?",
         "RE: Knowledge management - search SDK", "SDK", "\n\nRegards,\nPercy Nash\nKM Lead", "EN"),
        ("Bonjour Edwina,\n\nLa campagne de communication sur les nouvelles mesures de sécurité "
         "a été bien accueillie par les collaborateurs. Le taux de lecture des messages atteint "
         "quatre-vingt-cinq pour cent ce qui est remarquable.\n\n"
         "Concernant la DPIA pour le nouveau système de badges, est-elle finalisée ? "
         "Pouvez-vous la soumettre au DPO pour validation ?",
         "RE: Communication sécurité - DPIA badges", "DPIA", "\n\nCordialement,\nRaymond Blanc\nSûreté", "FR"),
        ("Hi Veronica,\n\nThe partner ecosystem expansion is yielding strong results. "
         "Twelve new partners have been onboarded this quarter and the pipeline "
         "is robust for the remainder of the year.\n\n"
         "Regarding the OAuth configuration for partner access, has it been tested? "
         "Should we run a security review before going live?",
         "RE: Partner ecosystem - OAuth access config", "OAuth", "\n\nBest,\nEdmund Price\nPartner VP", "EN"),
        ("Bonjour Vivien,\n\nLe nouveau système de gestion des temps est opérationnel. "
         "Les collaborateurs peuvent désormais saisir leurs heures en temps réel "
         "et les managers ont accès aux tableaux de bord de suivi.\n\n"
         "D'autre part, le bug sur le calcul des heures supplémentaires est-il corrigé ? "
         "Pouvez-vous me confirmer que les fiches de paie sont correctes ?",
         "RE: Gestion temps - correction bug heures", "bug", "\n\nBien à vous,\nLiliane Perrot\nPaie", "FR"),
        ("Hi Clementine,\n\nI wanted to provide an update on the digital accessibility initiative. "
         "All public-facing pages have been audited and remediation is underway. "
         "The compliance deadline is fast approaching.\n\n"
         "Also, has the staging version been updated with the accessibility fixes? "
         "Can you schedule the final audit for next week?",
         "RE: Accessibility - staging compliance audit", "staging", "\n\nRegards,\nDaryl Morrison\nAccessibility Lead", "EN"),
        ("Bonjour Félicien,\n\nLes nouvelles procédures de gestion des risques ont été déployées. "
         "Les cartographies sont à jour et les plans d'action associés sont en cours. "
         "Le dispositif de veille est renforcé.\n\n"
         "Par ailleurs, la production du rapport trimestriel est-elle en avance cette fois ? "
         "Pouvez-vous me transmettre les premières données ?",
         "RE: Gestion risques - rapport production", "production", "\n\nCordialement,\nJeanine Lambert\nRisk Manager", "FR"),
        ("Hi Evelyn,\n\nThe procurement digitalization project has reached an important milestone. "
         "Electronic purchase orders are now processed end to end and the average "
         "processing time has been reduced by half.\n\n"
         "Regarding the GraphQL interface for the reporting module, is it stable? "
         "Do you need additional development resources?",
         "RE: Procurement digitalization - GraphQL reporting", "GraphQL", "\n\nBest regards,\nSterling Ford\nProcurement Ops", "EN"),
        ("Bonjour Édith,\n\nJe vous informe que le plan de continuité informatique a été mis à jour. "
         "Les scénarios de crise ont été revus et les procédures de basculement testées "
         "avec succès lors du dernier exercice.\n\n"
         "D'autre part, le KPI de temps de reprise est-il conforme aux exigences ? "
         "Pouvez-vous partager les résultats du dernier test ?",
         "RE: Plan continuité - KPI reprise", "KPI", "\n\nCordialement,\nArmelle Dumont\nPCA", "FR"),
        ("Hi Trudy,\n\nThe diversity and inclusion program metrics for the quarter are now available. "
         "We have seen meaningful progress on several key indicators and the employee "
         "resource groups are more active than ever.\n\n"
         "Also, is the REST endpoint for the D&I dashboard operational? "
         "Should we share the dashboard link with the board members?",
         "RE: D&I metrics - REST dashboard endpoint", "REST", "\n\nRegards,\nMarcus Webb\nD&I Director", "EN"),
        ("Bonjour Clothilde,\n\nLe déménagement des archives physiques vers le nouveau local "
         "est programmé pour la fin du mois. L'inventaire a été réalisé et les cartons sont "
         "préparés. Le prestataire de transport est confirmé.\n\n"
         "Par ailleurs, le debug du système de recherche dans les archives numériques est-il terminé ? "
         "Pouvez-vous vérifier que les résultats de recherche sont corrects ?",
         "RE: Déménagement archives - debug recherche", "debug", "\n\nBien cordialement,\nSerge Dupuis\nArchives", "FR"),
        ("Hi Bethany,\n\nI am glad to report that the mentoring program pilot has been successful. "
         "Participant satisfaction scores are high and the mentor-mentee matching algorithm "
         "is working well. We are ready to scale the program company-wide.\n\n"
         "Regarding the Confluence page with program guidelines, has it been published? "
         "Can we announce the program expansion next week?",
         "RE: Mentoring program - Confluence guidelines", "confluence", "\n\nBest,\nHarvey Stone\nPeople Development", "EN"),
        ("Bonjour Solène,\n\nLe suivi des projets en portefeuille montre une bonne dynamique. "
         "Douze projets sur quinze sont dans les temps et les deux restants font l'objet "
         "d'un plan de rattrapage spécifique.\n\n"
         "D'autre part, le stack trace observé sur le portail projets est-il résolu ? "
         "Pouvez-vous demander à l'équipe technique de vérifier ?",
         "RE: Portefeuille projets - stack trace portail", "stack trace", "\n\nCordialement,\nAndrée Martin\nPMO", "FR"),
        ("Hi Adrienne,\n\nThe workplace wellness program has been refreshed for the new year. "
         "New activities include mindfulness sessions, ergonomic assessments, and "
         "fitness challenges. Employee sign-ups have exceeded expectations.\n\n"
         "Also, has the JSON configuration for the wellness app been updated? "
         "Do we need to coordinate with the vendor for the new features?",
         "RE: Wellness program - JSON app config", "JSON", "\n\nKind regards,\nSheldon Burke\nWellness Coordinator", "EN"),
        ("Bonjour Noëlle,\n\nLa politique de télétravail a été mise à jour pour intégrer "
         "les nouvelles dispositions réglementaires. Le document a été diffusé à l'ensemble "
         "des managers et une FAQ est disponible sur l'intranet.\n\n"
         "Par ailleurs, le pull request pour la mise à jour du portail RH est-il validé ? "
         "Pouvez-vous vérifier avec l'équipe de développement ?",
         "RE: Politique télétravail - pull request portail", "pull request", "\n\nBien à vous,\nCorentin Fabre\nRelations sociales", "FR"),
    ]
    for body_base, subj, _tech, sig, lang in _p5_bodies:
        cases.append((
            _pad_to(body_base, 550, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"{lang} 2q, 550ch, 1tech({_tech}), thread=1, 2topics [gen-p5]"
        ))

    assert len(cases) == 200, f"Expected 200, got {len(cases)}"
    return cases


def _gen_standard_with_tech():
    """
    100 test cases with prominent tech keywords, 1-2 questions, body 400-800 chars.
    Score 30-49. Business/tech themes: project updates, deployments, meetings about technical topics.
    """
    cases = []

    # =========================================================================
    # GROUP A (25 cases): 1q + 2 tech + body 600-800 + thread=1 + topics=2
    # q=35*0.20=7, body~(25-37)*0.20=5-7.5, tech=70*0.15=10.5, thread=20*0.10=2, topic=50*0.10=5
    # Total ~29.5-32 → borderline to STANDARD
    # =========================================================================

    cases.append((
        _pad_to(
            "Bonjour Fabrice,\n\nJe souhaitais faire un point rapide sur le déploiement de "
            "la nouvelle version. L'équipe a terminé les tests sur l'environnement de staging "
            "et les résultats sont conformes aux attentes. La mise en production est prévue pour "
            "jeudi soir avec un créneau de maintenance de deux heures.\n\n"
            "Par ailleurs, les métriques de performance post-déploiement seront surveillées "
            "en temps réel. Avez-vous confirmé le plan de rollback en cas de problème ?",
            700, "\n\nCordialement,\nAlexis Morin\nLead DevOps"
        ),
        "RE: Déploiement v3.2 - staging validation",
        1, False, False, "STANDARD", 30, 49,
        "FR 1q, 700ch, 2tech(staging,rollback), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Marcus,\n\nThe API refactoring effort is going well. We have redesigned the "
            "authentication flow and simplified the endpoint structure. The new documentation "
            "is being generated automatically from the codebase and should be ready for review "
            "by end of week.\n\n"
            "Also, the performance benchmarks show a significant improvement in response times. "
            "Can you sign off on the changes before we merge into the main branch?",
            700, "\n\nBest regards,\nKatherine Morris\nBackend Engineer"
        ),
        "RE: API refactor - endpoint redesign",
        1, False, False, "STANDARD", 30, 49,
        "EN 1q, 700ch, 2tech(API,endpoint), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Adrien,\n\nSuite à l'incident de ce matin, l'équipe a identifié la cause "
            "du bug dans le module de synchronisation des données. Un correctif a été développé "
            "et testé en environnement de pré-production. Le déploiement du patch est prévu pour "
            "cet après-midi.\n\n"
            "De plus, nous avons mis en place un monitoring renforcé pour détecter ce type "
            "d'anomalie plus rapidement. La migration vers le nouveau système est-elle impactée ?",
            700, "\n\nCordialement,\nLucie Reynaud\nIngénieure support"
        ),
        "RE: Incident sync - correction bug migration",
        1, False, False, "STANDARD", 30, 49,
        "FR 1q, 700ch, 2tech(bug,migration), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Charlotte,\n\nI wanted to update you on the Kubernetes cluster optimization. "
            "We have rightsized the node pools and implemented autoscaling policies that should "
            "reduce our monthly cloud spend by approximately fifteen percent. The Docker images "
            "have also been optimized to reduce build times and storage consumption.\n\n"
            "Furthermore, the monitoring stack has been upgraded to capture more granular metrics. "
            "Would you like a walkthrough of the new dashboard?",
            700, "\n\nRegards,\nOscar Rivera\nPlatform Engineer"
        ),
        "RE: Kubernetes optimization - Docker image cleanup",
        1, False, False, "STANDARD", 30, 49,
        "EN 1q, 700ch, 2tech(kubernetes,docker), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Éloïse,\n\nLe sprint review d'hier s'est bien passé. L'équipe a démontré "
            "les nouvelles fonctionnalités de l'espace client et les retours du product owner "
            "sont positifs. Nous avons quelques ajustements mineurs à effectuer avant le "
            "passage en recette. Le backlog du prochain sprint est en cours de priorisation.\n\n"
            "D'autre part, le ticket Jira pour le correctif de sécurité est-il créé ?",
            680, "\n\nBien à vous,\nGuillaume Dupuis\nScrum Master"
        ),
        "RE: Sprint review - prochaines priorités Jira",
        1, False, False, "STANDARD", 30, 49,
        "FR 1q, 680ch, 2tech(sprint,jira), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Vanessa,\n\nThe SQL performance optimization project has yielded excellent results. "
            "Query execution times for the main reports have been reduced by over sixty percent. "
            "The database team also implemented index improvements that further enhanced read "
            "performance. The changes have been validated in the staging environment.\n\n"
            "Additionally, we discovered some legacy stored procedures that need attention. "
            "Should we include them in the next iteration?",
            700, "\n\nBest,\nRyan O'Brien\nDatabase Lead"
        ),
        "RE: SQL optimization - staging validation",
        1, False, False, "STANDARD", 30, 49,
        "EN 1q, 700ch, 2tech(SQL,staging), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Hugo,\n\nJe vous informe que la migration vers le nouveau fournisseur cloud "
            "Azure progresse comme prévu. Les premières charges de travail ont été migrées avec "
            "succès et les tests de performance sont en cours. L'équipe infrastructure assure "
            "le suivi quotidien des indicateurs de disponibilité.\n\n"
            "Concernant la stratégie de déploiement multi-région, un document de référence a été "
            "préparé. Pouvez-vous le relire avant notre prochaine réunion de pilotage ?",
            700, "\n\nCordialement,\nValentin Roux\nArchitecte cloud"
        ),
        "RE: Migration Azure - deploy multi-région",
        1, False, False, "STANDARD", 30, 49,
        "FR 1q, 700ch, 2tech(azure,deploy), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Stella,\n\nThe new REST API gateway has been deployed to our staging cluster. "
            "All endpoints have been validated against the OpenAPI specification and the "
            "authentication layer is working correctly with the OAuth provider. The team is now "
            "focused on writing integration tests to ensure backward compatibility.\n\n"
            "Also, we need to finalize the rate limiting configuration for production. "
            "Can we discuss the thresholds during tomorrow's architecture review?",
            700, "\n\nRegards,\nDamien West\nAPI Team Lead"
        ),
        "RE: REST API gateway - OAuth staging deploy",
        1, False, False, "STANDARD", 30, 49,
        "EN 1q, 700ch, 3tech(REST,OAuth,staging), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Amandine,\n\nLa revue de code sur la branche de feature est terminée. "
            "Les commentaires ont été pris en compte et les modifications demandées ont été "
            "intégrées. Le merge est en attente de votre approbation finale. Les tests unitaires "
            "et d'intégration passent tous avec succès sur la CI.\n\n"
            "Par ailleurs, le processus de revue de la pull request prend plus de temps que "
            "prévu. Pensez-vous que nous devrions ajuster notre workflow ?",
            700, "\n\nCordialement,\nBaptiste Leroux\nDéveloppeur senior"
        ),
        "RE: Revue code - merge branch pull request",
        1, False, False, "STANDARD", 30, 49,
        "FR 1q, 700ch, 3tech(merge,branch,pull request), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Derek,\n\nThe Terraform infrastructure-as-code migration is progressing nicely. "
            "We have converted eighty percent of the manual configurations into reproducible "
            "templates. The remaining resources on AWS are scheduled for conversion next week. "
            "Testing has been thorough and no issues have been found.\n\n"
            "Also, the documentation for the new provisioning process needs updating. "
            "Would you be available to review the runbook on Thursday?",
            700, "\n\nBest regards,\nLiam Cooper\nInfrastructure Engineer"
        ),
        "RE: Terraform migration - AWS provisioning",
        1, False, False, "STANDARD", 30, 49,
        "EN 1q, 700ch, 2tech(terraform,aws), thread=1, 2topics"
    ))

    # =========================================================================
    # GROUP B (25 cases): 2q + 1 tech + body 500-700 + thread=1 + topics=2
    # q=70*0.20=14, body~(18-31)*0.20=3.7-6.2, tech=40*0.15=6, thread=20*0.10=2, topic=50*0.10=5
    # Total ~30.7-33.2 → solid STANDARD
    # =========================================================================

    cases.append((
        _pad_to(
            "Bonjour Clémence,\n\nJe reviens vers vous au sujet de la mise à jour du portail "
            "fournisseurs. Les nouvelles fonctionnalités ont été intégrées et les premiers "
            "retours sont encourageants.\n\n"
            "D'autre part, la documentation utilisateur sur Confluence est-elle à jour ? "
            "Avez-vous prévu des sessions de formation pour les équipes achats ?",
            550, "\n\nCordialement,\nVictor Blanchard\nResponsable SI achats"
        ),
        "RE: Portail fournisseurs - mise à jour Confluence",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 550ch, 1tech(confluence), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Monica,\n\nI wanted to check in on the status of the data pipeline redesign. "
            "The initial proof of concept was completed last week and the results look promising. "
            "The team is now working on the production-ready version.\n\n"
            "Regarding the JSON schema validation, is it included in the current scope? "
            "Do you need any additional resources for the testing phase?",
            560, "\n\nBest,\nCaleb Harrison\nData Engineer"
        ),
        "RE: Data pipeline - JSON schema validation",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 560ch, 1tech(JSON), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Raphaëlle,\n\nLe projet de centralisation des données progresse bien. "
            "L'intégration des flux CSV issus des différents systèmes sources est fonctionnelle "
            "et les contrôles de qualité sont en place.\n\n"
            "Par ailleurs, avez-vous validé le format d'export pour les partenaires externes ? "
            "Le mapping des champs est-il conforme à leurs spécifications ?",
            550, "\n\nBien à vous,\nÉtienne Lacroix\nIngénieur données"
        ),
        "RE: Centralisation données - export CSV partenaires",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 550ch, 1tech(CSV), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Tanya,\n\nThank you for the update on the security review. The team has addressed "
            "all high-priority findings and the remediation is complete. The penetration test "
            "results were better than expected.\n\n"
            "Also, has the new OAuth configuration been tested with all client applications? "
            "Are there any compatibility issues we should be aware of?",
            550, "\n\nRegards,\nChris Palmer\nSecurity Lead"
        ),
        "RE: Security review - OAuth compatibility",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 550ch, 1tech(OAuth), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Lionel,\n\nLe tableau de bord des indicateurs de production a été mis à jour "
            "avec les données du mois dernier. Les temps de réponse sont stables et le taux "
            "de disponibilité reste au-dessus de nos engagements.\n\n"
            "Concernant le prochain déploiement, est-ce que le plan de déploiement a été revu ? "
            "Pouvez-vous confirmer la fenêtre de maintenance ?",
            560, "\n\nCordialement,\nSonia Chevallier\nIngénieure production"
        ),
        "RE: Indicateurs production - plan deploy",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 560ch, 1tech(deploy), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Amanda,\n\nThe XML feed integration with our partner's system has been completed. "
            "Data flows are now bidirectional and the validation rules are working correctly. "
            "The reconciliation process runs daily and any discrepancies are flagged automatically.\n\n"
            "Additionally, do you have the latest schema documentation from the partner? "
            "Is there a timeline for the next version of their feed specification?",
            580, "\n\nBest regards,\nEric Nguyen\nIntegration Lead"
        ),
        "RE: XML feed integration - partner schema",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 580ch, 1tech(XML), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Séverine,\n\nVoici un rapide point sur la migration du système de ticketing "
            "vers Jira. Les configurations ont été importées et les workflows personnalisés sont "
            "opérationnels. Les utilisateurs pilotes sont satisfaits.\n\n"
            "D'autre part, avez-vous formé les équipes support à la nouvelle interface ? "
            "La date de bascule définitive est-elle maintenue au premier avril ?",
            560, "\n\nBien cordialement,\nGrégoire Fontaine\nResponsable outils"
        ),
        "RE: Migration ticketing Jira - bascule",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 560ch, 1tech(jira), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Raymond,\n\nThe GraphQL layer for our mobile application has been implemented. "
            "The queries have been optimized for mobile bandwidth and the caching strategy "
            "is working well. Initial user testing shows improved performance.\n\n"
            "Also, have you tested the offline mode with the new data layer? "
            "Is the error handling robust enough for production?",
            560, "\n\nRegards,\nGrace Liu\nMobile Lead"
        ),
        "RE: GraphQL mobile - offline mode",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 560ch, 1tech(GraphQL), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Mélanie,\n\nL'intégration du SDK de paiement a été finalisée. Les tests "
            "en sandbox sont concluants et les transactions de test passent sans erreur. "
            "Nous sommes prêts pour la phase de validation fonctionnelle.\n\n"
            "Concernant la certification PCI, le dossier est-il complet ? "
            "Pouvez-vous me confirmer que les exigences de sécurité sont toutes remplies ?",
            560, "\n\nCordialement,\nFlorent Mercier\nIngénieur paiement"
        ),
        "RE: SDK paiement - certification validation",
        1, False, False, "STANDARD", 30, 49,
        "FR 2q, 560ch, 1tech(SDK), thread=1, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Maggie,\n\nThe HTTPS migration for all our public-facing services is complete. "
            "All certificates have been renewed and automated rotation has been configured. "
            "The redirect rules are in place and no broken links have been reported.\n\n"
            "Also, have you updated the external documentation with the new URLs? "
            "Is the monitoring set up to alert us before certificate expiration?",
            570, "\n\nBest,\nBen Taylor\nSite Reliability Engineer"
        ),
        "RE: HTTPS migration - certificate monitoring",
        1, False, False, "STANDARD", 30, 49,
        "EN 2q, 570ch, 1tech(HTTPS), thread=1, 2topics"
    ))

    # =========================================================================
    # GROUP C (25 cases): 2q + 2 tech + body 400-600 + thread=0 + topics=2
    # q=70*0.20=14, body~(12-25)*0.20=2.5-5.0, tech=70*0.15=10.5, thread=0, topic=50*0.10=5
    # Total ~32-34.5
    # =========================================================================

    cases.append((
        _pad_to(
            "Bonjour Xavier,\n\nLe correctif pour le bug en production a été développé et "
            "testé. Nous avons vérifié que le crash ne se reproduit plus sur les scénarios "
            "identifiés.\n\n"
            "Par ailleurs, faut-il déclencher un déploiement d'urgence ? "
            "Pouvez-vous valider la priorité de cette correction ?",
            450, "\n\nCordialement,\nAnne Bertrand\nDéveloppeur"
        ),
        "RE: Correctif bug - crash production",
        0, False, False, "STANDARD", 30, 49,
        "FR 2q, 450ch, 2tech(bug,crash), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Tyler,\n\nThe database migration script has been tested in staging and is ready "
            "for the production run. All tables have been verified and the data integrity checks "
            "passed without issues.\n\n"
            "Additionally, has the rollback script been tested as well? "
            "Do you want to do a dry run before the actual migration window?",
            480, "\n\nBest regards,\nMelissa Brooks\nDBA"
        ),
        "RE: Database migration - staging rollback",
        0, False, False, "STANDARD", 30, 49,
        "EN 2q, 480ch, 2tech(database,staging), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Sandrine,\n\nLe nouveau schéma de base de données a été validé par "
            "l'architecte. Les performances des requêtes sur le nouvel endpoint sont conformes "
            "aux objectifs fixés.\n\n"
            "D'autre part, les tests de charge sont-ils programmés ? "
            "Avez-vous besoin d'un accès à l'environnement de performance ?",
            470, "\n\nBien à vous,\nMathias Robin\nDBA"
        ),
        "RE: Nouveau schéma - endpoint performance",
        0, False, False, "STANDARD", 30, 49,
        "FR 2q, 470ch, 2tech(schema,endpoint), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Katherine,\n\nThe Terraform modules for the new environment have been written "
            "and peer-reviewed. The GCP project has been provisioned and the IAM policies "
            "are configured according to our security standards.\n\n"
            "Also, should we enable budget alerts for this new project? "
            "Would you like to review the access permissions before we go live?",
            480, "\n\nRegards,\nJake Wilson\nCloud Engineer"
        ),
        "RE: Terraform modules - GCP provisioning",
        0, False, False, "STANDARD", 30, 49,
        "EN 2q, 480ch, 2tech(terraform,gcp), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Marine,\n\nLe sprint planning est terminé et les user stories pour les deux "
            "prochaines semaines ont été estimées. Le carnet de commandes Jira est à jour avec "
            "les priorités validées par le product owner.\n\n"
            "Concernant la vélocité de l'équipe, est-elle stable depuis le dernier trimestre ? "
            "Devons-nous ajuster notre capacité pour la prochaine itération ?",
            490, "\n\nCordialement,\nJérôme Martin\nAgile Coach"
        ),
        "RE: Sprint planning - vélocité Jira",
        0, False, False, "STANDARD", 30, 49,
        "FR 2q, 490ch, 2tech(sprint,jira), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Joanne,\n\nThe CI/CD pipeline has been updated to include additional security "
            "scanning. Every pull request now triggers a vulnerability scan and the results are "
            "posted as comments on the PR.\n\n"
            "Regarding the false positives, have they been reduced since the configuration change? "
            "Should we add additional exclusion rules?",
            480, "\n\nBest,\nMiles Foster\nDevSecOps Engineer"
        ),
        "RE: CI/CD security - pull request scanning",
        0, False, False, "STANDARD", 30, 49,
        "EN 2q, 480ch, 2tech(CI/CD,pull request), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Thibaut,\n\nLe déploiement de la nouvelle version sur l'environnement de "
            "staging s'est bien passé. Les tests automatisés ont été exécutés et tous les "
            "scénarios sont verts.\n\n"
            "Par ailleurs, la release note est-elle prête pour la communication aux utilisateurs ? "
            "Avez-vous prévu une démonstration avant la mise en production ?",
            480, "\n\nBien cordialement,\nInès Fournier\nRelease Manager"
        ),
        "RE: Déploiement staging - release communication",
        0, False, False, "STANDARD", 30, 49,
        "FR 2q, 480ch, 2tech(staging,release), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Nancy,\n\nThe exception handling framework has been standardized across all "
            "microservices. The new error codes have been documented and the logging format "
            "is consistent throughout the platform.\n\n"
            "Also, have the monitoring alerts been updated with the new error patterns? "
            "Is the on-call runbook current with the latest troubleshooting steps?",
            490, "\n\nRegards,\nPatrick Young\nPlatform Lead"
        ),
        "RE: Exception handling - error standardization",
        0, False, False, "STANDARD", 30, 49,
        "EN 2q, 490ch, 2tech(exception,error), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Bonjour Delphine,\n\nLa configuration OAuth pour l'application mobile a été "
            "finalisée. Les flux d'authentification fonctionnent correctement avec le "
            "fournisseur d'identité et les tokens sont gérés de manière sécurisée.\n\n"
            "D'autre part, les tests REST de bout en bout sont-ils à jour ? "
            "Pouvez-vous vérifier la compatibilité avec les anciennes versions ?",
            480, "\n\nCordialement,\nMaxence Picard\nDéveloppeur mobile"
        ),
        "RE: OAuth mobile - tests REST compatibilité",
        0, False, False, "STANDARD", 30, 49,
        "FR 2q, 480ch, 2tech(OAuth,REST), thread=0, 2topics"
    ))
    cases.append((
        _pad_to(
            "Hi Carla,\n\nThe Confluence documentation for the new onboarding process has been "
            "published. All step-by-step guides have been updated with screenshots and the "
            "video tutorials are being recorded this week.\n\n"
            "Regarding the merge strategy for the documentation repository, is it documented? "
            "Should we implement branch protection rules?",
            480, "\n\nBest regards,\nRussell Wright\nTechnical Writer"
        ),
        "RE: Confluence documentation - merge branch strategy",
        0, False, False, "STANDARD", 30, 49,
        "EN 2q, 480ch, 3tech(confluence,merge,branch), thread=0, 2topics"
    ))

    # =========================================================================
    # GROUP D (25 cases): 1q + 2 tech + body 500-700 + thread=2 + topics=1 (single paragraph)
    # q=35*0.20=7, body~(18-31)*0.20=3.7-6.2, tech=70*0.15=10.5, thread=40*0.10=4, topic=0
    # Total ~25.2-27.7. Add attachments (+5) → 30.2-32.7
    # =========================================================================

    cases.append((
        _pad_to(
            "Bonjour Patrice,\n\nSuite au signalement d'une error ce matin, l'équipe a investigué "
            "et identifié un problème de configuration lors du deploy. Le correctif "
            "a été appliqué et les logs confirment que le service fonctionne normalement depuis "
            "onze heures. Nous surveillons la situation de près et les alertes de monitoring sont "
            "en place. Pouvez-vous confirmer que le problème est résolu de votre côté ?",
            600, "\n\nCordialement,\nMorgane Petit\nIngénieure exploitation"
        ),
        "RE: Module deploy - correctif error",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(error,deploy), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Walter,\n\nThe debug session for the intermittent crash in the payment module "
            "has been completed. The root cause was a race condition in the transaction handler "
            "that occurred under high load. A fix has been implemented and deployed to staging "
            "for validation. The automated tests now include a specific stress test scenario "
            "to catch this type of issue. Can you approve the promotion to production?",
            600, "\n\nRegards,\nHeidi Zhang\nSenior Engineer"
        ),
        "RE: Debug crash payment - staging fix",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 2tech(debug,crash), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Joël,\n\nLe processus de déploiement continu via notre pipeline CI/CD "
            "a été renforcé avec l'ajout de tests de sécurité automatisés. Chaque commit "
            "sur la branche principale déclenche désormais une analyse de vulnérabilité complète. "
            "Les premiers résultats sont positifs et aucune faille critique n'a été détectée. "
            "Pouvez-vous valider la nouvelle configuration avec l'équipe sécurité ?",
            600, "\n\nBien à vous,\nOcéane Leclerc\nDevSecOps"
        ),
        "RE: Pipeline CI/CD - tests branch sécurité",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2+tech(CI/CD,branch), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Nina,\n\nThe Kubernetes cluster has been upgraded to the latest stable version "
            "and all workloads have been migrated without downtime. The new version includes "
            "improved resource management and better support for our Docker containers. "
            "Monitoring dashboards show healthy metrics across all pods and nodes. "
            "Would you like to schedule a post-upgrade review meeting?",
            600, "\n\nBest,\nDean Murphy\nSRE Lead"
        ),
        "RE: Kubernetes upgrade - Docker workload migration",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 2tech(kubernetes,docker), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Karine,\n\nJe vous confirme que l'intégration entre notre système de "
            "facturation et le nouveau module de tarification est opérationnelle. Les tests "
            "de bout en bout ont été réalisés avec succès et les calculs sont conformes aux "
            "règles métier définies. Le document de recette est joint à ce mail pour votre "
            "validation. Pouvez-vous nous donner le feu vert pour le passage en production ?",
            600, "\n\nCordialement,\nWilliam Robert\nChef de projet finance"
        ),
        "RE: Intégration facturation - tarif production",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(facturation,tarif), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Judith,\n\nThe AWS infrastructure review has been completed. We have identified "
            "several instances that can be rightsized to reduce costs. The Terraform scripts "
            "have been updated to reflect the recommended instance types and the changes are "
            "ready for testing. I have attached the cost projection report for your review. "
            "Should we proceed with the changes during the next maintenance window?",
            600, "\n\nRegards,\nLuke Adams\nCloud Solutions Architect"
        ),
        "RE: AWS infrastructure review - Terraform updates",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 2tech(aws,terraform), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Loïc,\n\nSuite à l'audit de sécurité, nous devons mettre à jour notre "
            "politique de gestion des accès. Le rapport recommande de renforcer les mécanismes "
            "d'authentification et de revoir la matrice des droits. L'implémentation de ces "
            "changements nécessitera une coordination avec l'équipe en charge du RGPD et du SLA. "
            "Pouvez-vous organiser une réunion de cadrage cette semaine ?",
            600, "\n\nBien cordialement,\nFanny Boulanger\nRSSI adjointe"
        ),
        "RE: Audit sécurité - RGPD SLA politique accès",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(RGPD,SLA), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Trevor,\n\nThe API versioning strategy has been documented and shared with all "
            "consuming teams. We will maintain backward compatibility for at least six months "
            "after each major version release. The deprecation notices have been added to the "
            "SDK documentation and the migration guides are being prepared. "
            "Do you have any concerns about the proposed timeline?",
            600, "\n\nBest regards,\nErica Martinez\nPlatform Architect"
        ),
        "RE: API versioning - SDK deprecation release",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 3tech(API,SDK,release), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Julien,\n\nLe rapport de tests de charge est finalisé et les résultats "
            "montrent que le système supporte correctement la montée en charge prévue. "
            "Nous avons simulé mille utilisateurs simultanés sans dégradation significative "
            "des temps de réponse. La stack trace identifiée précédemment sous forte charge "
            "a disparu grâce au correctif de la semaine dernière. "
            "Faut-il publier le rapport sur le Confluence de l'équipe ?",
            620, "\n\nCordialement,\nElsa Robin\nIngénieure performance"
        ),
        "RE: Tests charge - stack trace Confluence",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 620ch, 2tech(stack trace,confluence), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Chelsea,\n\nThe GCP to Azure migration assessment has been finalized. We have "
            "mapped all current services to their Azure equivalents and estimated the effort "
            "for each workload. The cost comparison is favorable for the majority of services "
            "and the team is confident in the technical feasibility. I have attached the "
            "detailed comparison matrix. Shall we present this to the leadership team next week?",
            620, "\n\nRegards,\nAdam Foster\nMigration Lead"
        ),
        "RE: GCP to Azure migration assessment",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 620ch, 2tech(gcp,azure), thread=2, 1topic, attach"
    ))

    # D11-D15: More varied combinations
    cases.append((
        _pad_to(
            "Bonjour Lucile,\n\nLe déploiement du patch de sécurité est planifié pour ce soir à "
            "vingt-deux heures. Le rollback a été testé et fonctionne correctement en cas de "
            "problème. Les équipes d'astreinte sont prévenues et les procédures d'escalade "
            "sont en place. L'impact sur le service devrait être minimal avec une interruption "
            "de cinq minutes maximum. Pouvez-vous confirmer votre disponibilité pour le suivi ?",
            600, "\n\nCordialement,\nAntoine Costa\nAdministrateur système"
        ),
        "RE: Patch sécurité - deploy rollback",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(deploy,rollback), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Bradley,\n\nThe new JSON API specification has been published and all consumer "
            "teams have been notified. The XML legacy format will be deprecated at the end of "
            "the quarter as planned. Migration guides have been distributed and most teams "
            "are already in the process of updating their integrations. "
            "Can you check whether the finance team has started their migration?",
            600, "\n\nBest,\nLaura Chen\nIntegrations Manager"
        ),
        "RE: JSON API spec - XML deprecation",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 2tech(JSON,XML), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Edwige,\n\nLe projet de mise en conformité continue d'avancer. L'équipe "
            "juridique a finalisé la revue des clauses contractuelles et le registre des "
            "traitements GDPR a été mis à jour. Les formations obligatoires sont en cours "
            "de déploiement et le taux de participation atteint déjà soixante-quinze pour cent. "
            "Pouvez-vous nous transmettre les dernières recommandations de la CNIL ?",
            600, "\n\nBien à vous,\nThéophile Morel\nJuriste données"
        ),
        "RE: Conformité clause - registre GDPR",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(clause,GDPR), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Hi Claire,\n\nThe production monitoring setup for the new microservices has been "
            "completed. Dashboard panels cover all critical metrics including request latency, "
            "error rates, and resource utilization. The SQL queries powering the analytics "
            "dashboard have been optimized for real-time reporting. "
            "Would you like to do a walkthrough of the monitoring setup?",
            600, "\n\nRegards,\nEliot Parker\nObservability Engineer"
        ),
        "RE: Production monitoring - SQL analytics",
        2, False, True, "STANDARD", 30, 49,
        "EN 1q, 600ch, 2tech(production,SQL), thread=2, 1topic, attach"
    ))
    cases.append((
        _pad_to(
            "Bonjour Isabelle,\n\nLe nouveau processus de gestion des incidents a été formalisé "
            "et documenté. Les niveaux de criticité ont été redéfinis et les procédures "
            "d'escalade sont claires. Le tableau de suivi sur Jira est opérationnel et les "
            "équipes ont été formées. Le prochain sprint sera consacré à l'automatisation "
            "des notifications. Souhaitez-vous valider la procédure avant diffusion ?",
            600, "\n\nCordialement,\nRomain Gautier\nIncident Manager"
        ),
        "RE: Processus incidents - Jira sprint",
        2, False, True, "STANDARD", 30, 49,
        "FR 1q, 600ch, 2tech(jira,sprint), thread=2, 1topic, attach"
    ))

    # =========================================================================
    # GROUP E (55 more cases to reach 100): Programmatic generation
    # =========================================================================

    # --- E-Pattern 1 (15 cases): 2q + 1tech + body 500-600 + thread=1 + 2topics ---
    # q=70*0.20=14, body~(18-25)*0.20=3.7-5.0, tech=40*0.15=6, thread=20*0.10=2, topic=50*0.10=5
    # Total ~30.7-32.0
    _ep1 = [
        ("Bonjour Simone,\n\nLe projet de mise à jour du catalogue produits avance conformément "
         "au planning. L'équipe a terminé la saisie des fiches et la relecture est en cours.\n\n"
         "Par ailleurs, la base de données produits est-elle synchronisée avec le site web ? "
         "Avez-vous vérifié les prix affichés ?",
         "RE: Catalogue produits - synchronisation database", "database",
         "\n\nCordialement,\nCédric Bonhomme\nProduct Data", "FR"),
        ("Hi Gabriella,\n\nThe annual contract renegotiations are well underway. "
         "Most vendors have submitted their revised proposals and the evaluation "
         "process is in its final stages.\n\n"
         "Regarding the deployment of the new vendor management system, is it on track? "
         "Can we begin onboarding vendors next month?",
         "RE: Contract renegotiations - deploy vendor system", "deploy",
         "\n\nBest regards,\nIsaac Powell\nVendor Management", "EN"),
        ("Bonjour Martine,\n\nLes ateliers de design thinking organisés la semaine dernière "
         "ont été très productifs. L'équipe a généré plus de cinquante idées et les dix "
         "meilleures ont été sélectionnées pour le prototypage.\n\n"
         "D'autre part, le sprint de prototypage démarre-t-il bien lundi ? "
         "Avez-vous réservé la salle de création pour la semaine ?",
         "RE: Design thinking - prototypage sprint", "sprint",
         "\n\nBien à vous,\nArnaud Legendre\nInnovation", "FR"),
        ("Hi Deanna,\n\nI wanted to share the results from the website performance audit. "
         "Page load times have improved significantly and the bounce rate has decreased. "
         "The optimization work has paid off nicely.\n\n"
         "Also, has the migration of the analytics tracking code been completed? "
         "Are we capturing all the events we need?",
         "RE: Website performance - analytics migration", "migration",
         "\n\nRegards,\nBlake Harrison\nWebOps", "EN"),
        ("Bonjour Lisette,\n\nLa révision des processus de gestion documentaire est terminée. "
         "Les nouveaux workflows sont opérationnels et les utilisateurs se sont bien adaptés "
         "au changement. Le taux d'adoption dépasse nos attentes.\n\n"
         "Concernant le bug sur le moteur de recherche documentaire, est-il corrigé ? "
         "Pouvez-vous lancer une nouvelle série de tests ?",
         "RE: Gestion documentaire - correction bug recherche", "bug",
         "\n\nCordialement,\nJulien Berthier\nArchiviste numérique", "FR"),
        ("Hi Fiona,\n\nThe competitive intelligence report for Q1 has been finalized. "
         "Key trends and market movements have been documented and the strategic "
         "implications are outlined in the executive summary.\n\n"
         "Regarding the JSON data feed from our market research provider, is it reliable? "
         "Should we explore alternative data sources?",
         "RE: Competitive intelligence - JSON data feed", "JSON",
         "\n\nBest,\nVincent Taylor\nStrategy Insights", "EN"),
        ("Bonjour Ghislaine,\n\nLe plan d'action suite à l'audit social est en cours de mise "
         "en oeuvre. Les mesures prioritaires ont été lancées et les premiers résultats "
         "seront visibles d'ici deux mois.\n\n"
         "Par ailleurs, le contrat avec le cabinet d'audit social est-il reconduit ? "
         "Pouvez-vous me transmettre les conditions financières ?",
         "RE: Audit social - plan action contrat", "contrat",
         "\n\nBien cordialement,\nAriane Mercier\nRH", "FR"),
        ("Hi Rosemary,\n\nThe partner certification program has been revamped to include "
         "new competency tracks. The updated curriculum is ready and the first cohort "
         "is scheduled to begin in two weeks.\n\n"
         "Also, has the endpoint for the certification portal been updated? "
         "Can you verify the login flow works correctly?",
         "RE: Partner certification - portal endpoint", "endpoint",
         "\n\nRegards,\nDerrick Nash\nPartner Enablement", "EN"),
        ("Bonjour Wanda,\n\nLe comité social et économique s'est tenu mardi dernier. "
         "Les principaux sujets abordés concernaient les conditions de travail et le budget "
         "des activités sociales pour le prochain exercice.\n\n"
         "D'autre part, la clause de révision salariale a-t-elle été discutée ? "
         "Pouvez-vous me résumer les positions de chaque partie ?",
         "RE: CSE - clause révision salariale", "clause",
         "\n\nCordialement,\nRené Lefranc\nRelations sociales", "FR"),
        ("Hi Iris,\n\nThe inventory management system upgrade is progressing smoothly. "
         "All warehouse locations have been migrated to the new platform and the team "
         "has completed the user acceptance testing.\n\n"
         "Regarding the XML interface with the logistics provider, has it been validated? "
         "Do we need a contingency plan for the transition period?",
         "RE: Inventory upgrade - XML logistics interface", "XML",
         "\n\nBest regards,\nAlbert Wong\nWarehouse Operations", "EN"),
        ("Bonjour Carine,\n\nLa mise en place du nouveau système de pointage est terminée. "
         "Les badges ont été distribués et les bornes sont opérationnelles sur tous les sites. "
         "L'équipe RH suit l'adoption de près.\n\n"
         "Par ailleurs, le tarif de maintenance des bornes est-il négocié ? "
         "Avez-vous comparé les offres de service ?",
         "RE: Système pointage - tarif maintenance", "tarif",
         "\n\nBien à vous,\nFernand Collet\nMoyens généraux", "FR"),
        ("Hi Bridget,\n\nThe digital signage project has been deployed across all office locations. "
         "Content templates have been created and the scheduling system is fully operational. "
         "Employee feedback has been positive so far.\n\n"
         "Also, is the REST API for content updates functioning reliably? "
         "Should we set up monitoring for the content delivery?",
         "RE: Digital signage - REST API monitoring", "REST",
         "\n\nRegards,\nRodney Campbell\nFacilities Tech", "EN"),
        ("Bonjour Géraldine,\n\nLe suivi des réclamations clients montre une tendance positive. "
         "Le délai moyen de traitement a diminué de vingt pour cent et le taux de résolution "
         "au premier contact s'améliore.\n\n"
         "Concernant le SLA de traitement des réclamations, est-il respecté ? "
         "Devons-nous ajuster les objectifs pour le prochain trimestre ?",
         "RE: Réclamations clients - SLA traitement", "SLA",
         "\n\nCordialement,\nMaëlle Deschamps\nService client", "FR"),
        ("Hi Valerie,\n\nI am happy to report that the new employee referral program "
         "has generated thirty qualified candidates in its first month. "
         "The conversion rate from referral to hire is very promising.\n\n"
         "Regarding the CSV export of referral tracking data, is it accurate? "
         "Can you verify the bonus calculations match the payroll system?",
         "RE: Referral program - CSV tracking export", "CSV",
         "\n\nBest,\nCurtis Flynn\nTalent Acquisition", "EN"),
        ("Bonjour Éliane,\n\nLa campagne de collecte pour l'association caritative partenaire "
         "a dépassé les objectifs fixés. La mobilisation des collaborateurs a été remarquable "
         "et nous remercions tous les participants.\n\n"
         "D'autre part, le renouvellement de la convention de partenariat est-il en cours ? "
         "Pouvez-vous me transmettre le projet de convention ?",
         "RE: Collecte caritative - renouvellement convention", "renouvellement",
         "\n\nBien cordialement,\nHenri Vasseur\nRSE", "FR"),
    ]
    for body_base, subj, _tech, sig, lang in _ep1:
        cases.append((
            _pad_to(body_base, 550, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"{lang} 2q, 550ch, 1tech({_tech}), thread=1, 2topics [ep1]"
        ))

    # --- E-Pattern 2 (15 cases): 1q + 2tech + body 700 + thread=1 + 2topics ---
    # q=35*0.20=7, body~30*0.20=6, tech=70*0.15=10.5, thread=20*0.10=2, topic=50*0.10=5 = ~30.5
    _ep2 = [
        ("Bonjour Norbert,\n\nLe chantier de modernisation de la messagerie d'entreprise avance "
         "bien. Le nouvel outil de collaboration est en phase de test avec un groupe pilote "
         "de cinquante utilisateurs. Les premiers retours sont positifs et les fonctionnalités "
         "de visioconférence sont particulièrement appréciées.\n\n"
         "Par ailleurs, la migration des boîtes aux lettres est planifiée par lots. "
         "Le déploiement du premier lot sur Azure est-il prévu cette semaine ?",
         "RE: Modernisation messagerie - migration Azure deploy", "azure", "deploy",
         "\n\nCordialement,\nAdelaide Roux\nAdmin système", "FR"),
        ("Hi Penelope,\n\nThe regulatory compliance dashboard has been updated with the latest "
         "reporting requirements. All metrics are now aligned with the new framework and "
         "the automated alerts are configured. The quarterly submission process has been "
         "streamlined to reduce manual effort.\n\n"
         "Also, the GDPR module needs a minor configuration change to handle the new "
         "data categories. Can you schedule this for the next maintenance window?",
         "RE: Compliance dashboard - GDPR SLA config", "GDPR", "SLA",
         "\n\nBest regards,\nTyler Bennett\nRegulatory Affairs", "EN"),
        ("Bonjour Josette,\n\nLa phase de recette utilisateur du nouveau portail RH touche "
         "à sa fin. Les testeurs ont validé quatre-vingt-quinze pour cent des cas de test "
         "et les dernières anomalies sont en cours de correction. Le planning de formation "
         "est prêt et les supports pédagogiques sont finalisés.\n\n"
         "Concernant le endpoint d'authentification unique, la configuration OAuth est-elle "
         "finalisée pour l'ensemble des populations ?",
         "RE: Portail RH - recette OAuth endpoint", "OAuth", "endpoint",
         "\n\nBien à vous,\nVirginie Blanc\nSIRH", "FR"),
        ("Hi Sandra,\n\nThe IT asset lifecycle management tool has been deployed company-wide. "
         "All hardware and software inventories have been reconciled and the automated "
         "refresh workflows are operational. Cost savings from better visibility into "
         "underutilized assets are already materializing.\n\n"
         "Regarding the Jira integration for tracking asset requests, "
         "has the Confluence knowledge base article been published?",
         "RE: IT asset management - Jira Confluence integration", "jira", "confluence",
         "\n\nRegards,\nNoel Patterson\nIT Asset Manager", "EN"),
        ("Bonjour Renaud,\n\nLe plan de formation technique pour les développeurs a été "
         "validé par les managers. Les parcours couvrent les nouvelles technologies adoptées "
         "par l'entreprise et incluent des certifications reconnues. Le budget formation "
         "est suffisant pour couvrir l'ensemble des inscriptions prévues.\n\n"
         "D'autre part, les sessions sur Kubernetes et Docker sont-elles ouvertes "
         "aux inscriptions ?",
         "RE: Formation technique - Kubernetes Docker", "kubernetes", "docker",
         "\n\nCordialement,\nFabienne Leclerc\nFormation IT", "FR"),
        ("Hi Travis,\n\nThe data lake implementation project has been delivering value ahead "
         "of schedule. The ingestion pipelines for all major data sources are operational "
         "and the data quality framework is enforcing validation rules consistently. "
         "The analytics team can now access centralized data through self-service tools.\n\n"
         "Also, have the SQL views for the executive dashboard been optimized? "
         "The response times for the JSON API seem slower than expected.",
         "RE: Data lake - SQL JSON dashboard performance", "SQL", "JSON",
         "\n\nBest,\nSimone Clarke\nData Platform Lead", "EN"),
        ("Bonjour Lucienne,\n\nLe système de gestion des habilitations a été renforcé suite "
         "aux recommandations de l'audit. Les profils d'accès ont été revus et les comptes "
         "dormants désactivés. Un processus de revue trimestrielle a été mis en place "
         "pour maintenir la conformité dans la durée.\n\n"
         "Par ailleurs, le rapport de conformité RGPD incluant les nouvelles clauses "
         "est-il prêt pour soumission ?",
         "RE: Habilitations - RGPD clause conformité", "RGPD", "clause",
         "\n\nBien cordialement,\nMagali Dupont\nConformité IT", "FR"),
        ("Hi Cassandra,\n\nThe managed services contract renewal has been negotiated successfully. "
         "We have secured improved terms on both pricing and service levels. The new contract "
         "includes enhanced reporting capabilities and more flexible escalation paths. "
         "The transition to the new terms will be seamless.\n\n"
         "Regarding the licensing model for the new monitoring tools, "
         "has the production environment been included in the scope?",
         "RE: Managed services - licensing production", "licensing", "production",
         "\n\nRegards,\nWayne Richards\nIT Sourcing", "EN"),
        ("Bonjour Christine,\n\nLe tableau de bord de suivi des projets stratégiques a été "
         "refondu pour améliorer la lisibilité et la pertinence des indicateurs. Les nouveaux "
         "graphiques interactifs facilitent l'analyse et la prise de décision. Le comité de "
         "direction a exprimé sa satisfaction lors de la dernière présentation.\n\n"
         "Concernant l'intégration avec le système de facturation, le tarif du connecteur "
         "est-il inclus dans notre abonnement ?",
         "RE: Tableau bord stratégique - facturation tarif", "facturation", "tarif",
         "\n\nCordialement,\nPierrick Lemaire\nPMO stratégique", "FR"),
        ("Hi Danielle,\n\nThe new CRM implementation is progressing according to plan. "
         "The data migration from the legacy system is sixty percent complete and the "
         "user training program has been well received. Sales team adoption metrics "
         "are trending positively and we expect full rollout by month end.\n\n"
         "Also, has the API for the marketing automation integration been configured? "
         "The staging environment needs to be provisioned for the next test cycle.",
         "RE: CRM implementation - API staging", "API", "staging",
         "\n\nBest regards,\nCorinne Hughes\nCRM Program Manager", "EN"),
        ("Bonjour Pascaline,\n\nLa revue des contrats fournisseurs stratégiques a permis "
         "d'identifier plusieurs opportunités d'optimisation. Les avenants sont en cours "
         "de rédaction pour intégrer les nouvelles conditions négociées. Les économies "
         "attendues représentent environ huit pour cent du portefeuille achats.\n\n"
         "D'autre part, le KPI de conformité des livraisons a-t-il atteint "
         "l'objectif de quatre-vingt-quinze pour cent ?",
         "RE: Contrats fournisseurs - avenant KPI livraisons", "avenant", "KPI",
         "\n\nBien à vous,\nGéraud Moreau\nAchats stratégiques", "FR"),
        ("Hi Annabelle,\n\nThe workforce planning model has been refined based on the latest "
         "business projections. Headcount requirements have been validated with all department "
         "heads and the recruitment pipeline has been aligned accordingly. The talent "
         "acquisition team is ready to execute on the approved positions.\n\n"
         "Regarding the sprint for the workforce analytics dashboard, "
         "has the Jira board been set up with the correct stories?",
         "RE: Workforce planning - sprint Jira analytics", "sprint", "jira",
         "\n\nRegards,\nJuliana Price\nWorkforce Planning VP", "EN"),
        ("Bonjour Myriam,\n\nLe programme de responsabilité sociétale continue de progresser. "
         "Les actions de réduction de l'empreinte carbone ont produit des résultats mesurables "
         "et le rapport annuel est en cours de rédaction. Les parties prenantes seront "
         "consultées lors du prochain comité de pilotage.\n\n"
         "Par ailleurs, le NDA avec le consultant en développement durable est-il signé ? "
         "La résiliation de l'ancien prestataire est-elle effective ?",
         "RE: RSE - NDA consultant résiliation", "NDA", "résiliation",
         "\n\nCordialement,\nHortense Garnier\nRSE", "FR"),
        ("Hi Gloria,\n\nI wanted to update you on the innovation lab activities. "
         "Three proof of concepts have been completed and two have been approved for "
         "further development. The lab budget utilization is within the approved envelope "
         "and the pipeline of new ideas is healthy.\n\n"
         "Also, has the GraphQL API for the innovation portal been finalized? "
         "The XML export for the patent database needs to be tested as well.",
         "RE: Innovation lab - GraphQL XML exports", "GraphQL", "XML",
         "\n\nBest,\nMaxwell Stone\nInnovation Director", "EN"),
        ("Bonjour Jocelyne,\n\nLa politique de sécurité de l'information a été mise à jour "
         "pour intégrer les dernières normes en vigueur. La diffusion aux collaborateurs "
         "sera effectuée via la plateforme de formation en ligne et un quiz de validation "
         "sera proposé pour s'assurer de la bonne compréhension.\n\n"
         "Concernant le déploiement du nouveau pare-feu, le rollback en cas de problème "
         "est-il documenté ?",
         "RE: Politique sécurité - deploy rollback pare-feu", "deploy", "rollback",
         "\n\nBien cordialement,\nClément Faure\nRSSI", "FR"),
    ]
    for body_base, subj, t1, t2, sig, lang in _ep2:
        cases.append((
            _pad_to(body_base, 700, sig),
            subj, 1, False, False, "STANDARD", 30, 49,
            f"{lang} 1q, 700ch, 2tech({t1},{t2}), thread=1, 2topics [ep2]"
        ))

    # --- E-Pattern 3 (15 cases): 2q + 2tech + body 450 + thread=0 + 2topics ---
    # q=70*0.20=14, body~(15)*0.20=3.1, tech=70*0.15=10.5, thread=0, topic=50*0.10=5 = ~32.6
    _ep3 = [
        ("Bonjour Étienne,\n\nLe rapport de veille technologique est disponible.\n\n"
         "Par ailleurs, le déploiement sur staging est-il terminé ? "
         "Pouvez-vous vérifier que tous les tests passent ?",
         "RE: Veille technologique - deploy staging", "deploy", "staging",
         "\n\nCordialement,\nNadège Robin\nVeille tech", "FR"),
        ("Hi Leah,\n\nThe project retrospective notes have been shared with the team.\n\n"
         "Regarding the merge conflicts on the release branch, have they been resolved? "
         "Can you update the status in the tracking system?",
         "RE: Retrospective - merge release branch", "merge", "release",
         "\n\nBest regards,\nTrent Morgan\nScrum Master", "EN"),
        ("Bonjour Sabrina,\n\nLe point hebdomadaire est prévu pour demain matin.\n\n"
         "D'autre part, la configuration OAuth pour le nouveau module est-elle fonctionnelle ? "
         "Avez-vous testé le endpoint de callback ?",
         "RE: Point hebdo - OAuth endpoint callback", "OAuth", "endpoint",
         "\n\nBien à vous,\nLudivine Perrin\nDev team", "FR"),
        ("Hi Miranda,\n\nI am sharing the updated risk register for your review.\n\n"
         "Also, has the database backup procedure been tested this week? "
         "Is the SQL restore process documented?",
         "RE: Risk register - database SQL backup", "database", "SQL",
         "\n\nRegards,\nCameron Young\nRisk Analyst", "EN"),
        ("Bonjour Gertrude,\n\nLes résultats du benchmark secteur sont encourageants.\n\n"
         "Par ailleurs, le sprint en cours chez le prestataire Jira avance-t-il bien ? "
         "Pouvez-vous demander un point d'avancement ?",
         "RE: Benchmark - sprint Jira prestataire", "sprint", "jira",
         "\n\nCordialement,\nValentin Renaud\nBenchmark", "FR"),
        ("Hi Vivian,\n\nThe annual IT budget proposal is ready for submission.\n\n"
         "Regarding the Terraform scripts for the test environment, are they up to date? "
         "Has the AWS cost estimate been validated?",
         "RE: IT budget - Terraform AWS estimate", "terraform", "aws",
         "\n\nBest,\nStanley Reed\nIT Finance", "EN"),
        ("Bonjour Odette,\n\nLa mise à jour des fiches processus est terminée.\n\n"
         "D'autre part, le bug identifié lors du crash serveur a-t-il été analysé ? "
         "Pouvez-vous partager le rapport d'incident ?",
         "RE: Fiches processus - bug crash serveur", "bug", "crash",
         "\n\nBien cordialement,\nAmbroise Dupuis\nQualité IT", "FR"),
        ("Hi Cora,\n\nI have prepared the project closeout documentation.\n\n"
         "Also, has the CI/CD pipeline been configured for the new repository? "
         "Is the pull request template standardized?",
         "RE: Project closeout - CI/CD pull request", "CI/CD", "pull request",
         "\n\nKind regards,\nDereck Hunt\nDevOps", "EN"),
        ("Bonjour Arlette,\n\nLe plan de communication du changement est finalisé.\n\n"
         "Par ailleurs, le schéma de la nouvelle base de données est-il validé ? "
         "Le endpoint pour les tests d'intégration est-il disponible ?",
         "RE: Communication changement - schema endpoint", "schema", "endpoint",
         "\n\nCordialement,\nBaptiste Morel\nConduite du changement", "FR"),
        ("Hi Roberta,\n\nThe vendor compliance audit results have been compiled.\n\n"
         "Regarding the GCP project for the new analytics workload, is it provisioned? "
         "Has the Kubernetes namespace been created?",
         "RE: Vendor compliance - GCP Kubernetes analytics", "gcp", "kubernetes",
         "\n\nRegards,\nMitchell Barnes\nCloud Ops", "EN"),
        ("Bonjour Brigitte,\n\nLe calendrier des revues de direction est établi.\n\n"
         "D'autre part, la migration des données vers le nouveau CSV est-elle achevée ? "
         "L'export XML pour les partenaires fonctionne-t-il correctement ?",
         "RE: Revues direction - migration CSV XML", "CSV", "XML",
         "\n\nBien à vous,\nMarcel Leconte\nSecrétariat général", "FR"),
        ("Hi Dora,\n\nI wanted to share the updated organizational chart.\n\n"
         "Also, has the refactoring of the user management module been completed? "
         "Is the error handling consistent across all services?",
         "RE: Org chart - refactor error handling", "refactor", "error",
         "\n\nBest regards,\nPaige Weber\nPeople Ops", "EN"),
        ("Bonjour Roland,\n\nLe calendrier prévisionnel du prochain trimestre est prêt.\n\n"
         "Par ailleurs, le contrat de licence du nouveau logiciel est-il signé ? "
         "La facturation est-elle prévue en début de mois ?",
         "RE: Planning trimestre - contrat facturation", "contrat", "facturation",
         "\n\nCordialement,\nMonique Dumas\nPlanification", "FR"),
        ("Hi Sheila,\n\nThe health and safety inspection report is available.\n\n"
         "Regarding the GDPR requirements for the new visitor management system, "
         "has the DPIA been submitted? "
         "Do we have all the necessary consents in place?",
         "RE: H&S inspection - GDPR DPIA visitor system", "GDPR", "DPIA",
         "\n\nRegards,\nArturo Gomez\nH&S Manager", "EN"),
        ("Bonjour Josiane,\n\nLe bilan de fin d'année est en préparation.\n\n"
         "D'autre part, le ROI du programme de transformation est-il calculé ? "
         "Le KPI de productivité a-t-il évolué favorablement ?",
         "RE: Bilan annuel - ROI KPI productivité", "ROI", "KPI",
         "\n\nBien cordialement,\nPhilomène Garnier\nTransformation", "FR"),
    ]
    for body_base, subj, t1, t2, sig, lang in _ep3:
        cases.append((
            _pad_to(body_base, 450, sig),
            subj, 0, False, False, "STANDARD", 30, 49,
            f"{lang} 2q, 450ch, 2tech({t1},{t2}), thread=0, 2topics [ep3]"
        ))

    # --- E-Pattern 4 (10 cases): 1q + 1tech + body 800 + thread=3 + 2topics ---
    # q=35*0.20=7, body~37*0.20=7.5, tech=40*0.15=6, thread=40*0.10=4, topic=50*0.10=5 = ~29.5
    # With attach=5 → 34.5
    _ep4 = [
        ("Bonjour Régine,\n\nJe vous transmets le compte-rendu détaillé de la réunion de pilotage "
         "du programme de transformation. Les chantiers avancent conformément aux jalons définis "
         "et les risques identifiés sont sous contrôle. Le budget consommé est en ligne avec "
         "les prévisions et les prochaines étapes ont été validées par le sponsor.\n\n"
         "Concernant la prochaine phase de la migration, est-elle confirmée pour avril ?",
         "RE: Pilotage transformation - prochaine migration", "migration",
         "\n\nCordialement,\nDorian Lemaire\nPMO", "FR"),
        ("Hi Joanna,\n\nI am pleased to report that the automation initiative has exceeded "
         "initial expectations. Process automation has been implemented across twelve "
         "workflows and the average time savings per process is forty percent. "
         "The team is now identifying additional candidates for the next wave.\n\n"
         "Also, should we include the sprint planning for wave two in next week's agenda?",
         "RE: Automation initiative - wave two sprint", "sprint",
         "\n\nBest regards,\nRoland Murphy\nAutomation Lead", "EN"),
        ("Bonjour Josette,\n\nLa restructuration de l'organigramme du département est finalisée. "
         "Les nouvelles missions ont été définies et les fiches de poste actualisées. "
         "Les entretiens de repositionnement ont été menés avec bienveillance et les "
         "collaborateurs ont dans l'ensemble bien accepté les changements proposés.\n\n"
         "Par ailleurs, le renouvellement des délégations de signature est-il effectif ?",
         "RE: Restructuration département - renouvellement délégations", "renouvellement",
         "\n\nBien à vous,\nGuy-Noël Bertrand\nDRH", "FR"),
        ("Hi Cynthia,\n\nThe year-end employee recognition event planning is well underway. "
         "The venue has been booked and the program has been drafted. The nominations for "
         "the various award categories have been received and the selection committee "
         "will convene next week to finalize the winners.\n\n"
         "Regarding the error in the nomination tracking spreadsheet, has it been fixed?",
         "RE: Recognition event - nomination error tracking", "error",
         "\n\nRegards,\nCecilia Ward\nEmployee Experience", "EN"),
        ("Bonjour Georgette,\n\nLe projet de développement du réseau de distribution prend forme. "
         "Les études de marché sont terminées pour les trois zones cibles et les business plans "
         "ont été soumis au comité d'investissement. Les premiers contacts avec les "
         "partenaires locaux sont encourageants et les négociations avancent.\n\n"
         "D'autre part, le contrat type pour les distributeurs a-t-il été validé ?",
         "RE: Réseau distribution - contrat type distributeurs", "contrat",
         "\n\nCordialement,\nAlexandrine Picard\nDéveloppement commercial", "FR"),
        ("Hi Eleanor,\n\nThe office space optimization project has yielded significant cost "
         "savings. The new layout provides more collaborative spaces while maintaining "
         "adequate quiet zones. Employee satisfaction with the new arrangement has been "
         "measured through surveys and the results are positive.\n\n"
         "Also, is the clause in the lease agreement about modifications still valid?",
         "RE: Space optimization - lease clause", "clause",
         "\n\nBest,\nRandolph Fisher\nFacilities", "EN"),
        ("Bonjour Madeleine,\n\nLa politique de voyage d'entreprise a été mise à jour. "
         "Les nouveaux plafonds de remboursement sont définis et les outils de réservation "
         "en ligne sont configurés. La communication aux voyageurs sera diffusée lundi "
         "et une FAQ sera mise à disposition sur l'intranet.\n\n"
         "Par ailleurs, le tarif négocié avec la compagnie aérienne est-il appliqué ?",
         "RE: Politique voyage - tarif compagnie aérienne", "tarif",
         "\n\nBien cordialement,\nAlbertine Simon\nTravel Management", "FR"),
        ("Hi Tamara,\n\nThe corporate social responsibility report has been finalized and "
         "is ready for publication. All data points have been verified and the narrative "
         "sections have been reviewed by external stakeholders. The design team is "
         "preparing the final layout for both digital and print versions.\n\n"
         "Regarding the SLA for the report publishing platform, is it guaranteed?",
         "RE: CSR report - publishing SLA", "SLA",
         "\n\nRegards,\nWalter Price\nCSR Director", "EN"),
        ("Bonjour Jacqueline,\n\nLe plan d'investissement pour les équipements informatiques "
         "a été approuvé. Les commandes seront passées progressivement au cours du trimestre "
         "et le déploiement suivra un calendrier précis pour minimiser les perturbations. "
         "Le budget total est conforme à l'enveloppe validée.\n\n"
         "D'autre part, le licensing des postes de travail est-il inclus dans l'enveloppe ?",
         "RE: Investissement IT - licensing postes", "licensing",
         "\n\nCordialement,\nAlfred Royer\nDSI", "FR"),
        ("Hi Lorraine,\n\nThe internal communications strategy for the upcoming merger has been "
         "drafted. Key messages have been developed and the communication timeline is aligned "
         "with the regulatory approval milestones. All spokespeople have been briefed "
         "and media preparation sessions are scheduled.\n\n"
         "Also, has the NDA with the PR agency been executed?",
         "RE: Merger communications - PR NDA", "NDA",
         "\n\nBest regards,\nHarvey Quinn\nCorporate Communications", "EN"),
    ]
    for body_base, subj, _tech, sig, lang in _ep4:
        cases.append((
            _pad_to(body_base, 800, sig),
            subj, 3, False, True, "STANDARD", 30, 49,
            f"{lang} 1q, 800ch, 1tech({_tech}), thread=3, 2topics, attach [ep4]"
        ))

    assert len(cases) == 100, f"Expected 100, got {len(cases)}"
    return cases


def _gen_standard_forced():
    """
    20 test cases: score < 30 but has_instructions=True → forced to STANDARD.
    Short body, 0-1 questions, with user instructions flag.
    """
    cases = []

    # Score < 30 with instructions=True
    # Typical: 0-1 questions + short body (<300 chars) + 0-1 tech → score 0-29
    # With has_instructions=True → STANDARD

    # 0 questions, body ~150 chars, 0 tech, no thread → score ~0
    cases.append((
        "Bonjour,\n\nMerci pour votre message. Bien reçu.",
        "RE: Confirmation",
        0, True, False, "STANDARD", 0, 29,
        "FR 0q, 50ch, 0tech, thread=0, instructions forced"
    ))
    cases.append((
        "Hi,\n\nThank you for the update. Everything looks good.",
        "RE: Update",
        0, True, False, "STANDARD", 0, 29,
        "EN 0q, 55ch, 0tech, thread=0, instructions forced"
    ))

    # 0 questions, body ~200 chars, 0 tech, thread=1 → body_score=0, thread=2 → score ~2
    cases.append((
        _pad_to(
            "Bonjour Pierre,\n\nBien noté pour la réunion de demain. Je serai présent à "
            "quatorze heures comme convenu.",
            200, "\n\nCordialement,\nJean Martin"
        ),
        "RE: Réunion demain",
        1, True, False, "STANDARD", 0, 29,
        "FR 0q, 200ch, 0tech, thread=1, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi Laura,\n\nGot it, I will review the document by end of day and share my "
            "feedback tomorrow morning.",
            200, "\n\nBest,\nMark Stevens"
        ),
        "RE: Document review",
        1, True, False, "STANDARD", 0, 29,
        "EN 0q, 200ch, 0tech, thread=1, instructions forced"
    ))

    # 1 question, body ~250 chars, 0 tech, thread=0 → q=35*0.20=7, body=3*0.20=0.6 → score ~7
    cases.append((
        _pad_to(
            "Bonjour Alain,\n\nMerci pour ces informations. Je les transmettrai au service "
            "concerné dans la journée. Pouvez-vous me confirmer le numéro de référence ?",
            250, "\n\nCordialement,\nClaude Dupuis"
        ),
        "RE: Informations demandées",
        0, True, False, "STANDARD", 0, 29,
        "FR 1q, 250ch, 0tech, thread=0, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi James,\n\nThanks for sharing the report. I will take a look this afternoon. "
            "Can you send me the latest version of the spreadsheet?",
            250, "\n\nRegards,\nSarah Cooper"
        ),
        "RE: Report received",
        0, True, False, "STANDARD", 0, 29,
        "EN 1q, 250ch, 0tech, thread=0, instructions forced"
    ))

    # 0 questions, body ~180 chars, 1 tech, thread=0 → tech=40*0.15=6 → score ~6
    cases.append((
        _pad_to(
            "Bonjour Sophie,\n\nLe déploiement est terminé. Tout fonctionne correctement. "
            "Rien à signaler.",
            180, "\n\nCordialement,\nPaul Lefèvre"
        ),
        "Déploiement terminé",
        0, True, False, "STANDARD", 0, 29,
        "FR 0q, 180ch, 1tech(deploy), thread=0, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi Tom,\n\nThe staging environment has been updated. No issues detected so far.",
            180, "\n\nBest,\nKelly Brown"
        ),
        "Staging update done",
        0, True, False, "STANDARD", 0, 29,
        "EN 0q, 180ch, 1tech(staging), thread=0, instructions forced"
    ))

    # 1 question, body ~300 chars, 0 tech, thread=0 → q=7, body=6*0.20=1.2 → ~8
    cases.append((
        _pad_to(
            "Bonjour Marie,\n\nJ'ai bien reçu votre demande et je la traiterai dans les "
            "meilleurs délais. L'équipe est actuellement mobilisée sur un autre sujet mais "
            "nous vous recontacterons rapidement. Avez-vous une date limite à respecter ?",
            300, "\n\nBien à vous,\nFrançois Renard"
        ),
        "RE: Votre demande",
        0, True, False, "STANDARD", 0, 29,
        "FR 1q, 300ch, 0tech, thread=0, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi Nancy,\n\nI have received your request and will process it shortly. "
            "The team is currently wrapping up another project but we should be able to "
            "get to yours by Thursday. Is there a specific deadline we should be aware of?",
            300, "\n\nRegards,\nChris Wood"
        ),
        "RE: Your request",
        0, True, False, "STANDARD", 0, 29,
        "EN 1q, 300ch, 0tech, thread=0, instructions forced"
    ))

    # 0 questions, body ~120 chars, 0 tech, thread=0 → score ~0
    cases.append((
        "Bonjour,\n\nBien reçu, merci. Je reviens vers vous rapidement.",
        "RE: Suivi",
        0, True, False, "STANDARD", 0, 29,
        "FR 0q, 60ch, 0tech, thread=0, instructions forced minimal"
    ))
    cases.append((
        "Hi,\n\nNoted, thanks. I will follow up with you shortly.",
        "RE: Follow up",
        0, True, False, "STANDARD", 0, 29,
        "EN 0q, 55ch, 0tech, thread=0, instructions forced minimal"
    ))

    # 1 question, ~200 chars, 1 tech, thread=1 → q=7 + tech=6 + thread=2 = 15
    cases.append((
        _pad_to(
            "Bonjour,\n\nLe bug a été signalé au support. Est-ce que vous avez des nouvelles ?",
            200, "\n\nCordialement,\nLuc Martin"
        ),
        "RE: Bug signalé",
        1, True, False, "STANDARD", 0, 29,
        "FR 1q, 200ch, 1tech(bug), thread=1, instructions forced"
    ))
    cases.append((
        "Hi,\n\nThe update was successful. Any feedback from the clients so far?\n\nBest,\nJane Smith",
        "RE: Update feedback",
        1, True, False, "STANDARD", 0, 29,
        "EN 1q, ~90ch, 0tech, thread=1, instructions forced"
    ))

    # Very short, 0q, 0tech → score=0, forced by instructions
    cases.append((
        "OK, merci.",
        "RE: Validation",
        0, True, False, "STANDARD", 0, 29,
        "FR 0q, 10ch, 0tech, instructions forced ultra-short"
    ))
    cases.append((
        "Got it, thanks.",
        "RE: Acknowledged",
        0, True, False, "STANDARD", 0, 29,
        "EN 0q, 15ch, 0tech, instructions forced ultra-short"
    ))

    # 0 questions, ~250 chars, 0 tech, thread=2 → thread=40*0.10=4 → score ~4
    cases.append((
        _pad_to(
            "Bonjour Michel,\n\nJe prends note de vos remarques et je les intégrerai dans "
            "la prochaine version du document. Merci pour votre retour détaillé.",
            250, "\n\nCordialement,\nAnne Giraud"
        ),
        "RE: Remarques document",
        2, True, False, "STANDARD", 0, 29,
        "FR 0q, 250ch, 0tech, thread=2, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi Robert,\n\nThank you for the detailed comments. I will incorporate your "
            "suggestions into the revised version and share it by Friday.",
            250, "\n\nBest regards,\nDiana Scott"
        ),
        "RE: Document comments",
        2, True, False, "STANDARD", 0, 29,
        "EN 0q, 250ch, 0tech, thread=2, instructions forced"
    ))

    # 1 question, ~280 chars, 0 tech, thread=0 → q=7, body=5*0.20=1 → score ~8
    cases.append((
        _pad_to(
            "Bonjour Liliane,\n\nMerci pour votre retour rapide. Je vais étudier les "
            "différentes options et revenir vers vous en début de semaine prochaine. "
            "Pouvez-vous me rappeler le délai de réponse attendu ?",
            280, "\n\nCordialement,\nSerge Blanchard"
        ),
        "RE: Options à étudier",
        0, True, False, "STANDARD", 0, 29,
        "FR 1q, 280ch, 0tech, thread=0, instructions forced"
    ))
    cases.append((
        _pad_to(
            "Hi Sandra,\n\nThank you for the quick turnaround. I will review the options "
            "and get back to you early next week with my recommendation. "
            "Is there a hard deadline I should be aware of?",
            280, "\n\nBest,\nTerence Mills"
        ),
        "RE: Options review",
        0, True, False, "STANDARD", 0, 29,
        "EN 1q, 280ch, 0tech, thread=0, instructions forced"
    ))

    assert len(cases) == 20, f"Expected 20, got {len(cases)}"
    return cases
