# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Stress test: 100 email label corrections → learning rules.

Tests the full pipeline:
  LearnLabelingRuleUseCase.execute() → LabelStore.add_rule() → rule matching

pytest tests/application/test_label_learning_100.py -v
"""

import json
from collections import Counter
from datetime import datetime
from unittest.mock import Mock

import pytest

from app.application.label_email import LearnLabelingRuleUseCase
from app.domain.entities import TokenUsage
from app.domain.entities.email_labels import LabelingRule, DEFAULT_LABEL_NAMES
from app.domain.ports import LLMPort
from app.infrastructure.adapters.label_store import LabelStore


# ============================================================================
# TEST DATA: 100 diverse emails
# ============================================================================

EMAILS_100 = [
    # --- Noise (30 emails) ---
    # Newsletters (10)
    {"id": "e001", "sender": "news@techcrunch.com", "subject": "Daily Digest: AI roundup", "body": "Top stories in AI today..."},
    {"id": "e002", "sender": "newsletter@medium.com", "subject": "Weekly picks for you", "body": "Based on your reading history..."},
    {"id": "e003", "sender": "digest@producthunt.com", "subject": "Top 5 launches today", "body": "Check out today's best..."},
    {"id": "e004", "sender": "updates@linkedin.com", "subject": "Your weekly summary", "body": "15 profile views this week..."},
    {"id": "e005", "sender": "no-reply@twitter.com", "subject": "Popular tweets near you", "body": "Based on your location..."},
    {"id": "e006", "sender": "no-reply@github.com", "subject": "Explore trending repos", "body": "Trending in Python..."},
    {"id": "e007", "sender": "promo@amazon.fr", "subject": "Ventes flash du jour", "body": "Jusqu'a -50% sur l'electronique..."},
    {"id": "e008", "sender": "newsletter@substack.com", "subject": "New post from your subscriptions", "body": "A writer you follow..."},
    {"id": "e009", "sender": "marketing@hubspot.com", "subject": "Marketing trends 2026", "body": "Download our free report..."},
    {"id": "e010", "sender": "events@meetup.com", "subject": "Events near Paris this week", "body": "Join local tech meetups..."},
    # Notifications (10)
    {"id": "e011", "sender": "noreply@trello.com", "subject": "Card moved: Sprint planning", "body": "Alice moved card to Done..."},
    {"id": "e012", "sender": "notifications@slack.com", "subject": "New messages in #general", "body": "You have 5 unread messages..."},
    {"id": "e013", "sender": "noreply@jira.atlassian.com", "subject": "PROJ-421 updated", "body": "Status changed to In Review..."},
    {"id": "e014", "sender": "no-reply@figma.com", "subject": "Comment on Dashboard v3", "body": "Bob commented on your design..."},
    {"id": "e015", "sender": "no-reply@notion.so", "subject": "Page updated: Team OKRs", "body": "Changes by Carol..."},
    {"id": "e016", "sender": "noreply@sentry.io", "subject": "New issue: TypeError in api.py", "body": "Error rate increased..."},
    {"id": "e017", "sender": "alerts@datadog.com", "subject": "CPU alert: prod-web-01", "body": "CPU usage exceeded 90%..."},
    {"id": "e018", "sender": "no-reply@vercel.com", "subject": "Deploy succeeded: main@abc123", "body": "Your project deployed..."},
    {"id": "e019", "sender": "noreply@stripe.com", "subject": "Payment received: 49.99 EUR", "body": "Invoice INV-2026-042..."},
    {"id": "e020", "sender": "no-reply@calendly.com", "subject": "New booking: Demo call", "body": "Someone booked a 30min slot..."},
    # Spam-ish (10)
    {"id": "e021", "sender": "deals@groupon.com", "subject": "50% off restaurants", "body": "Limited time offer..."},
    {"id": "e022", "sender": "promo@booking.com", "subject": "Last-minute deals in Rome", "body": "Hotels from 59 EUR/night..."},
    {"id": "e023", "sender": "offers@cdiscount.com", "subject": "Soldes extraordinaires", "body": "Profitez de -70%..."},
    {"id": "e024", "sender": "info@leboncoin.fr", "subject": "Nouvelles annonces pour vous", "body": "3 nouvelles annonces..."},
    {"id": "e025", "sender": "noreply@spotify.com", "subject": "Your 2026 Wrapped is here", "body": "See your listening stats..."},
    {"id": "e026", "sender": "team@canva.com", "subject": "New templates available", "body": "Design faster with..."},
    {"id": "e027", "sender": "hello@typeform.com", "subject": "Your form got 12 responses", "body": "Check out the results..."},
    {"id": "e028", "sender": "no-reply@dropbox.com", "subject": "Storage almost full", "body": "You're using 98% of your space..."},
    {"id": "e029", "sender": "support@1password.com", "subject": "Security audit complete", "body": "All good, no breaches..."},
    {"id": "e030", "sender": "news@coinbase.com", "subject": "Bitcoin hits new high", "body": "Markets update..."},

    # --- FYI (25 emails) ---
    {"id": "e031", "sender": "Marie Dupont <marie.dupont@company.fr>", "subject": "CR reunion equipe", "body": "Voici le resume de la reunion..."},
    {"id": "e032", "sender": "Pierre Martin <pierre@startup.io>", "subject": "Mise a jour du roadmap", "body": "J'ai mis a jour le roadmap Q2..."},
    {"id": "e033", "sender": "Sophie Leclerc <sophie@agency.com>", "subject": "Brief campagne social media", "body": "Voici le brief pour la campagne..."},
    {"id": "e034", "sender": "Team HR <rh@company.fr>", "subject": "Conges equipe mars 2026", "body": "Planning des conges..."},
    {"id": "e035", "sender": "IT Support <it@company.fr>", "subject": "Maintenance serveurs samedi", "body": "Maintenance prevue de 2h a 6h..."},
    {"id": "e036", "sender": "Marc Bernard <marc@partner.com>", "subject": "Benchmark concurrence Q1", "body": "Veuillez trouver ci-joint..."},
    {"id": "e037", "sender": "Julie Moreau <julie.m@company.fr>", "subject": "Newsletter interne fevrier", "body": "Les actus de ce mois..."},
    {"id": "e038", "sender": "Direction <direction@company.fr>", "subject": "Resultats annuels 2025", "body": "Nous avons le plaisir de partager..."},
    {"id": "e039", "sender": "Legal Team <legal@company.fr>", "subject": "Mise a jour CGV", "body": "Les nouvelles CGV entrent en vigueur..."},
    {"id": "e040", "sender": "Comite CE <ce@company.fr>", "subject": "Sorties team building ete", "body": "Inscrivez-vous avant le 15 mars..."},
    {"id": "e041", "sender": "alice.chen@bigcorp.com", "subject": "Industry report shared", "body": "FYI - attached the report we discussed..."},
    {"id": "e042", "sender": "bob.jones@contractor.net", "subject": "Project status update", "body": "Everything on track for Q2 delivery..."},
    {"id": "e043", "sender": "carol@design.studio", "subject": "Brand guidelines v2", "body": "Updated brand book attached..."},
    {"id": "e044", "sender": "david@analytics.co", "subject": "Monthly KPI dashboard", "body": "Key metrics for February..."},
    {"id": "e045", "sender": "emma@finance.corp", "subject": "Budget forecast Q2", "body": "Preliminary numbers attached..."},
    {"id": "e046", "sender": "frank@ops.team", "subject": "Warehouse inventory report", "body": "Current stock levels..."},
    {"id": "e047", "sender": "grace@marketing.io", "subject": "Campaign results Feb 2026", "body": "CTR improved by 15%..."},
    {"id": "e048", "sender": "henry@engineering.dev", "subject": "Architecture decision record", "body": "ADR-042: Moving to microservices..."},
    {"id": "e049", "sender": "isabelle@research.lab", "subject": "Etude utilisateur resultats", "body": "Les tests montrent que..."},
    {"id": "e050", "sender": "jean@sales.company.fr", "subject": "Pipeline CRM mis a jour", "body": "5 nouveaux leads qualifies..."},
    {"id": "e051", "sender": "karen@support.help", "subject": "CSAT score this month", "body": "Customer satisfaction at 94%..."},
    {"id": "e052", "sender": "lucas@product.team", "subject": "Feature flag rollout plan", "body": "Gradual rollout starting Monday..."},
    {"id": "e053", "sender": "nina@data.science", "subject": "ML model performance report", "body": "Accuracy improved to 97.3%..."},
    {"id": "e054", "sender": "oscar@security.io", "subject": "Quarterly security review", "body": "No critical vulnerabilities found..."},
    {"id": "e055", "sender": "paula@compliance.co", "subject": "GDPR audit completed", "body": "All requirements met..."},

    # --- Action (30 emails) ---
    {"id": "e056", "sender": "CEO <ceo@company.fr>", "subject": "Valider le budget Q2 avant vendredi", "body": "Merci de valider le budget ci-joint avant vendredi midi."},
    {"id": "e057", "sender": "Client VIP <vip@bigclient.com>", "subject": "Urgent: probleme facturation", "body": "Nous avons un probleme sur la facture #2042..."},
    {"id": "e058", "sender": "RH <rh@company.fr>", "subject": "Signer votre avenant contrat", "body": "Merci de signer l'avenant ci-joint et de le retourner..."},
    {"id": "e059", "sender": "Support <support@provider.com>", "subject": "Action requise: renouveler licence", "body": "Votre licence expire dans 7 jours..."},
    {"id": "e060", "sender": "compta@company.fr", "subject": "Notes de frais a soumettre", "body": "Merci de soumettre vos notes de frais du mois..."},
    {"id": "e061", "sender": "manager@company.fr", "subject": "Review code PR #245 avant merge", "body": "Peux-tu reviewer et approuver la PR?"},
    {"id": "e062", "sender": "partenaire@external.com", "subject": "Contrat a signer avant le 30", "body": "Ci-joint le contrat definitif a signer..."},
    {"id": "e063", "sender": "dev@team.company.fr", "subject": "Bug critique en production", "body": "Le endpoint /api/users renvoie 500 depuis 10h..."},
    {"id": "e064", "sender": "client2@important.biz", "subject": "Demande de devis urgente", "body": "Pouvez-vous nous envoyer un devis pour 500 licences?"},
    {"id": "e065", "sender": "admin@saas-tool.com", "subject": "Your subscription requires attention", "body": "Payment method expired, update now..."},
    {"id": "e066", "sender": "recruiter@talent.co", "subject": "Interview feedback needed by EOD", "body": "Please submit your assessment..."},
    {"id": "e067", "sender": "procurement@company.fr", "subject": "Approuver commande #PO-2026-089", "body": "Commande en attente de validation..."},
    {"id": "e068", "sender": "auditor@external-audit.com", "subject": "Documents requis pour audit", "body": "Merci de fournir les documents suivants..."},
    {"id": "e069", "sender": "partner-api@integration.io", "subject": "API key rotation required", "body": "Your API keys will expire in 48 hours..."},
    {"id": "e070", "sender": "security@company.fr", "subject": "Incident response: data breach", "body": "Immediate action required..."},
    {"id": "e071", "sender": "customer@enterprise.com", "subject": "Escalation: SLA breach ticket #T-999", "body": "Response time exceeded SLA by 4 hours..."},
    {"id": "e072", "sender": "board@company.fr", "subject": "Preparer presentation CA", "body": "Preparer la presentation pour le conseil d'administration du 28 mars..."},
    {"id": "e073", "sender": "vendor@supplier.com", "subject": "Price increase notification", "body": "Review and acknowledge the new pricing..."},
    {"id": "e074", "sender": "dpo@company.fr", "subject": "Demande RGPD a traiter sous 72h", "body": "Un utilisateur demande la suppression de ses donnees..."},
    {"id": "e075", "sender": "finance@company.fr", "subject": "Rapprochement bancaire a valider", "body": "Merci de verifier et valider avant cloture..."},
    {"id": "e076", "sender": "project-lead@company.fr", "subject": "Mise a jour sprint planning requise", "body": "Mettre a jour les estimations pour le sprint 12..."},
    {"id": "e077", "sender": "ops@infra.company.fr", "subject": "Approve infrastructure changes", "body": "Terraform plan ready for review..."},
    {"id": "e078", "sender": "training@company.fr", "subject": "Inscription formation obligatoire", "body": "Inscrivez-vous avant le 25 mars..."},
    {"id": "e079", "sender": "compliance@company.fr", "subject": "Certifications a renouveler", "body": "ISO 27001 renewal due in 30 days..."},
    {"id": "e080", "sender": "intern@company.fr", "subject": "Rapport de stage a corriger", "body": "Pourriez-vous relire et corriger mon rapport?"},
    {"id": "e081", "sender": "tech-lead@company.fr", "subject": "Design review scheduled", "body": "Please prepare your architecture proposal..."},
    {"id": "e082", "sender": "qa@company.fr", "subject": "Release blocker: 3 critical tests failing", "body": "Cannot ship v2.4 until fixed..."},
    {"id": "e083", "sender": "pm@company.fr", "subject": "Customer demo Thursday - prep needed", "body": "Please prepare demo environment..."},
    {"id": "e084", "sender": "legal@company.fr", "subject": "NDA a signer pour partenariat", "body": "Ci-joint le NDA, retour attendu sous 48h..."},
    {"id": "e085", "sender": "cto@company.fr", "subject": "Tech debt prioritization meeting", "body": "Prepare your list of top 5 tech debts..."},

    # --- Waiting (15 emails) ---
    {"id": "e086", "sender": "fournisseur@logistics.fr", "subject": "Confirmation livraison en attente", "body": "Nous reviendrons vers vous avec le tracking..."},
    {"id": "e087", "sender": "banque@mabanque.fr", "subject": "Demande de pret en cours d'etude", "body": "Votre dossier est en cours d'analyse..."},
    {"id": "e088", "sender": "avocat@cabinet-legal.com", "subject": "Dossier en cours - attente tribunal", "body": "La date d'audience sera fixee prochainement..."},
    {"id": "e089", "sender": "assurance@axa.fr", "subject": "Sinistre #S-2026-103 en traitement", "body": "Votre declaration est en cours de traitement..."},
    {"id": "e090", "sender": "impots@dgfip.finances.gouv.fr", "subject": "Demande de degrevement en instruction", "body": "Votre demande est en cours d'instruction..."},
    {"id": "e091", "sender": "visa@consulat.gouv.fr", "subject": "Visa application processing", "body": "Your application is being reviewed..."},
    {"id": "e092", "sender": "repair@apple.com", "subject": "Repair status: in progress", "body": "Your MacBook Pro repair is underway..."},
    {"id": "e093", "sender": "recruiter@dreamjob.com", "subject": "Application received - next steps", "body": "We'll get back to you within 2 weeks..."},
    {"id": "e094", "sender": "vendor-support@saas.com", "subject": "Feature request #FR-123 received", "body": "We've added it to our roadmap..."},
    {"id": "e095", "sender": "landlord@immo-agency.fr", "subject": "Dossier location en cours", "body": "Nous etudions votre candidature..."},
    {"id": "e096", "sender": "grant@eu-funding.europa.eu", "subject": "Application under evaluation", "body": "Your H2026 proposal is being evaluated..."},
    {"id": "e097", "sender": "patent@office.eu", "subject": "Patent application #EP2026-042", "body": "Examination in progress..."},
    {"id": "e098", "sender": "university@admission.edu", "subject": "Admission decision pending", "body": "Results will be announced April 1..."},
    {"id": "e099", "sender": "warranty@dell.com", "subject": "Warranty claim #WC-2026-555", "body": "Under review, expect response in 5 days..."},
    {"id": "e100", "sender": "partner@jv-project.com", "subject": "Joint venture proposal review", "body": "Our legal team is reviewing the terms..."},
]

# Expected label for each email
EXPECTED_LABELS = {}
for e in EMAILS_100:
    eid = e["id"]
    num = int(eid[1:])
    if num <= 30:
        EXPECTED_LABELS[eid] = "Noise"
    elif num <= 55:
        EXPECTED_LABELS[eid] = "FYI"
    elif num <= 85:
        EXPECTED_LABELS[eid] = "Action"
    else:
        EXPECTED_LABELS[eid] = "Waiting"


def _make_mock_email(data):
    email = Mock()
    email.id = data["id"]
    email.sender = data["sender"]
    email.subject = data["subject"]
    email.body = data["body"]
    return email


def _make_llm_response(condition_type, condition_value, confidence=0.85):
    """Create a mock LLM response."""
    resp = Mock()
    resp.content = json.dumps({
        "condition_type": condition_type,
        "condition_value": condition_value,
        "confidence": confidence,
    })
    resp.input_tokens = 50
    resp.output_tokens = 20
    resp.model = "test-model"
    return resp


def _make_llm_response_for_email(email_data, label):
    """Generate a realistic LLM response based on the email and label."""
    sender = email_data["sender"]
    subject = email_data["subject"]

    # Extract email address from "Name <email>" format
    import re
    match = re.search(r'<([^>]+)>', sender)
    email_addr = match.group(1).strip().lower() if match else sender.strip().lower()
    domain = email_addr.split("@")[1] if "@" in email_addr else ""

    if label == "Noise":
        # Newsletters/notifications → domain rule
        return _make_llm_response("sender", f"@{domain}", 0.9)
    elif label == "FYI":
        # FYI contacts → sender rule
        return _make_llm_response("sender", email_addr, 0.85)
    elif label == "Waiting":
        # Waiting → sender rule
        return _make_llm_response("sender", email_addr, 0.85)
    elif label == "Action":
        # Action → subject keyword (sender→Action is blocked)
        words = subject.lower().split()
        # Pick 2-word keyword from subject
        if len(words) >= 2:
            keyword = " ".join(words[:2])
        else:
            keyword = subject.lower()
        return _make_llm_response("subject", keyword, 0.8)
    else:
        return _make_llm_response("sender", email_addr, 0.75)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def label_store(tmp_path):
    """LabelStore with temporary storage."""
    return LabelStore(storage_dir=str(tmp_path / "labels"))


@pytest.fixture
def mock_llm():
    return Mock(spec=LLMPort)


@pytest.fixture
def use_case(mock_llm):
    return LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())


# ============================================================================
# TEST: 100 EMAIL LABEL CORRECTIONS
# ============================================================================


class TestLabelLearning100Emails:
    """Stress test: 100 email label corrections through the full pipeline."""

    def test_100_corrections_generate_rules(self, mock_llm, label_store):
        """Every label correction should produce at least one learned rule."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        total_rules_created = 0
        total_rules_saved = 0
        failures = []

        for email_data in EMAILS_100:
            email = _make_mock_email(email_data)
            target_label = EXPECTED_LABELS[email_data["id"]]
            old_label = "FYI" if target_label != "FYI" else "Noise"

            # Configure mock LLM for this email
            mock_llm.complete.return_value = _make_llm_response_for_email(
                email_data, target_label
            )

            rules = use_case.execute(email, [old_label], [target_label])
            total_rules_created += len(rules)

            for rule in rules:
                saved = label_store.add_rule(rule)
                if saved:
                    total_rules_saved += 1

            if not rules:
                failures.append(email_data["id"])

        # Stats
        all_rules = label_store.get_rules()
        learned = [r for r in all_rules if r.learned_from]

        print(f"\n{'='*60}")
        print("100 EMAIL LEARNING STRESS TEST RESULTS")
        print(f"{'='*60}")
        print("Total corrections: 100")
        print(f"Rules generated: {total_rules_created}")
        print(f"Rules saved (not duplicates): {total_rules_saved}")
        print(f"Learned rules in store: {len(learned)}")
        print(f"Failures (no rules): {len(failures)}")
        if failures:
            print(f"  Failed IDs: {failures}")

        # By label
        label_counts = Counter(r.label_name for r in learned)
        print("\nRules by label:")
        for label, count in sorted(label_counts.items()):
            print(f"  {label}: {count}")

        # By type
        type_counts = Counter(r.condition_type for r in learned)
        print("\nRules by type:")
        for ctype, count in sorted(type_counts.items()):
            print(f"  {ctype}: {count}")

        print(f"{'='*60}")

        # Assertions
        assert total_rules_created >= 80, f"Expected 80+ rules, got {total_rules_created}"
        assert len(learned) >= 50, f"Expected 50+ unique learned rules, got {len(learned)}"
        assert all(r.learned_from is not None for r in learned), "All learned rules must have learned_from set"

    def test_100_corrections_llm_failure_fallback(self, mock_llm, label_store):
        """When LLM fails for all 100, fallback rules should still be created."""
        from app.domain.exceptions import LLMConnectionError
        mock_llm.complete.side_effect = LLMConnectionError(
            provider="test", url="test", message="connection refused"
        )

        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        total_rules = 0
        fallback_created = 0
        no_fallback = []

        for email_data in EMAILS_100:
            email = _make_mock_email(email_data)
            target_label = EXPECTED_LABELS[email_data["id"]]
            old_label = "FYI" if target_label != "FYI" else "Noise"

            rules = use_case.execute(email, [old_label], [target_label])
            total_rules += len(rules)

            for rule in rules:
                label_store.add_rule(rule)

            if rules:
                fallback_created += 1
            else:
                no_fallback.append((email_data["id"], target_label))

        all_rules = label_store.get_rules()
        learned = [r for r in all_rules if r.learned_from]

        print(f"\n{'='*60}")
        print("100 EMAIL FALLBACK TEST (LLM=OFFLINE)")
        print(f"{'='*60}")
        print(f"Emails with fallback rule: {fallback_created}/100")
        print(f"Emails without fallback: {len(no_fallback)}")
        print(f"Unique rules in store: {len(learned)}")

        # Breakdown: which labels got no fallback?
        no_fallback_labels = Counter(label for _, label in no_fallback)
        print("\nNo-fallback by label:")
        for label, count in sorted(no_fallback_labels.items()):
            print(f"  {label}: {count}")
        print(f"{'='*60}")

        # Most emails should get fallback rules (Action gets subject-based)
        assert fallback_created >= 90, (
            f"Expected 90+ fallback rules, got {fallback_created}. "
            f"No fallback: {no_fallback[:5]}"
        )

    def test_rule_deduplication_same_sender(self, mock_llm, label_store):
        """Correcting 10 emails from same sender creates only 1 rule."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        for i in range(10):
            email = Mock()
            email.id = f"dup-{i}"
            email.sender = "newsletter@same-company.com"
            email.subject = f"Newsletter #{i}"
            email.body = f"Content {i}"

            mock_llm.complete.return_value = _make_llm_response(
                "sender", "@same-company.com", 0.9
            )

            rules = use_case.execute(email, ["FYI"], ["Noise"])
            for rule in rules:
                label_store.add_rule(rule)

        all_rules = label_store.get_rules()
        noise_rules = [r for r in all_rules if r.label_name == "Noise"
                       and "same-company" in r.condition_value]
        assert len(noise_rules) == 1, f"Expected 1 rule, got {len(noise_rules)}"

    def test_rule_conflict_resolution(self, mock_llm, label_store):
        """Changing label from FYI to Noise then back to FYI on same sender."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        email = Mock()
        email.id = "conflict-1"
        email.sender = "ambiguous@company.com"
        email.subject = "Monthly update"
        email.body = "Here's the monthly update..."

        # First: user says Noise
        mock_llm.complete.return_value = _make_llm_response(
            "sender", "ambiguous@company.com", 0.9
        )
        rules = use_case.execute(email, ["FYI"], ["Noise"])
        for r in rules:
            label_store.add_rule(r)

        # Verify Noise rule exists
        all_rules = label_store.get_rules()
        assert any(r.label_name == "Noise" and "ambiguous" in r.condition_value for r in all_rules)

        # Second: user changes mind to FYI
        email.id = "conflict-2"
        mock_llm.complete.return_value = _make_llm_response(
            "sender", "ambiguous@company.com", 0.9
        )
        rules = use_case.execute(email, ["Noise"], ["FYI"])
        for r in rules:
            label_store.add_rule(r)

        # Verify: latest correction wins (FYI replaces Noise)
        all_rules = label_store.get_rules()
        ambiguous_rules = [r for r in all_rules if "ambiguous" in r.condition_value
                           and r.label_name in DEFAULT_LABEL_NAMES]
        assert len(ambiguous_rules) == 1, f"Should have 1 rule after conflict, got {len(ambiguous_rules)}"
        assert ambiguous_rules[0].label_name == "FYI", f"Latest correction should win: expected FYI, got {ambiguous_rules[0].label_name}"

    def test_rule_matching_accuracy(self, mock_llm, label_store):
        """After learning from 100 emails, test that rules match new similar emails."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        # Learn from all 100 emails
        for email_data in EMAILS_100:
            email = _make_mock_email(email_data)
            target_label = EXPECTED_LABELS[email_data["id"]]
            old_label = "FYI" if target_label != "FYI" else "Noise"

            mock_llm.complete.return_value = _make_llm_response_for_email(
                email_data, target_label
            )

            rules = use_case.execute(email, [old_label], [target_label])
            for rule in rules:
                label_store.add_rule(rule)

        # Now test matching on "new" emails from same senders
        all_rules = [r for r in label_store.get_rules() if r.is_active]

        test_cases = [
            # New email from techcrunch → should match Noise rule
            {"sender": "news@techcrunch.com", "subject": "New article", "body": "..."},
            # New email from marie.dupont → should match FYI rule
            {"sender": "marie.dupont@company.fr", "subject": "Autre sujet", "body": "..."},
            # New email from fournisseur → should match Waiting rule
            {"sender": "fournisseur@logistics.fr", "subject": "Update livraison", "body": "..."},
        ]

        matches_found = 0
        for test_email in test_cases:
            email_data = {
                "sender": test_email["sender"].lower(),
                "subject": test_email["subject"].lower(),
                "body": test_email["body"].lower(),
                "recipients": [],
                "is_cc": False,
            }
            matched = [r for r in all_rules if r.matches(email_data)]
            if matched:
                matches_found += 1

        assert matches_found >= 2, f"Expected at least 2/3 test emails to match rules, got {matches_found}"

    def test_learned_rules_have_correct_metadata(self, mock_llm, label_store):
        """Verify all learned rules have proper metadata."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        for email_data in EMAILS_100[:20]:
            email = _make_mock_email(email_data)
            target_label = EXPECTED_LABELS[email_data["id"]]
            old_label = "FYI" if target_label != "FYI" else "Noise"

            mock_llm.complete.return_value = _make_llm_response_for_email(
                email_data, target_label
            )

            rules = use_case.execute(email, [old_label], [target_label])
            for rule in rules:
                label_store.add_rule(rule)

        all_rules = label_store.get_rules()
        learned = [r for r in all_rules if r.learned_from]

        for rule in learned:
            assert rule.rule_id, "rule_id must be set"
            assert rule.label_name in DEFAULT_LABEL_NAMES or rule.label_name, "label_name must be set"
            assert rule.condition_type in ("sender", "subject", "body", "cc", "recipient"), (
                f"Invalid condition_type: {rule.condition_type}"
            )
            assert rule.condition_value, "condition_value must not be empty"
            assert rule.learned_from is not None, "learned_from must be set"
            assert rule.created_at, "created_at must be set"
            assert 0 < rule.confidence <= 1.0, f"confidence out of range: {rule.confidence}"
            assert rule.priority in (35, 40), f"learned rule priority should be 35 or 40, got {rule.priority}"
            assert rule.is_active, "new rules should be active"

    def test_rules_persist_to_disk(self, mock_llm, label_store):
        """Rules survive store reload."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        email = _make_mock_email(EMAILS_100[0])
        mock_llm.complete.return_value = _make_llm_response(
            "sender", "@techcrunch.com", 0.9
        )
        rules = use_case.execute(email, ["FYI"], ["Noise"])
        for rule in rules:
            label_store.add_rule(rule)

        # Reload store from same directory
        store2 = LabelStore(storage_dir=label_store.storage_dir)
        all_rules = store2.get_rules()
        learned = [r for r in all_rules if r.learned_from]
        assert len(learned) >= 1, "Learned rules should persist after reload"

    def test_learning_all_endpoint_format(self, mock_llm, label_store):
        """Verify rules match the format expected by /api/learning/all."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())

        for email_data in EMAILS_100[:10]:
            email = _make_mock_email(email_data)
            target_label = EXPECTED_LABELS[email_data["id"]]
            old_label = "FYI" if target_label != "FYI" else "Noise"

            mock_llm.complete.return_value = _make_llm_response_for_email(
                email_data, target_label
            )

            rules = use_case.execute(email, [old_label], [target_label])
            for rule in rules:
                label_store.add_rule(rule)

        # Simulate what /api/learning/all does
        all_rules = label_store.get_rules()
        learned = [r for r in all_rules if getattr(r, "learned_from", None)]

        items = []
        for r in learned:
            tm = getattr(r, 'total_matches', 0)
            corr = getattr(r, 'corrections', 0)
            precision = round((tm - corr) / tm * 100) if tm > 0 else None
            items.append({
                "id": r.rule_id,
                "label": r.label_name,
                "type": r.condition_type,
                "value": r.condition_value,
                "use_count": r.use_count,
                "total_matches": tm,
                "corrections": corr,
                "precision": precision,
                "is_active": getattr(r, 'is_active', True),
                "created_at": r.created_at,
            })

        assert len(items) > 0, "Should have items for the learning panel"
        for item in items:
            assert item["id"], "id must be set"
            assert item["label"], "label must be set"
            assert item["type"] in ("sender", "subject", "body", "cc", "recipient")
            assert item["value"], "value must be set"
            assert isinstance(item["is_active"], bool)


# ============================================================================
# TEST: ACTION LABEL SUBJECT FALLBACK
# ============================================================================


class TestActionFallback:
    """Tests for deterministic Action subject-based fallback rules."""

    def test_action_fallback_creates_subject_rule(self, mock_llm):
        """Action fallback creates a subject-based rule."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "action-1"
        email.sender = "boss@company.com"
        email.subject = "Valider le budget Q2 avant vendredi"
        email.body = "Merci de valider..."

        result = use_case._create_fallback_rule(email, "Action")
        assert result is not None
        assert result.condition_type == "subject"
        assert result.label_name == "Action"
        assert result.learned_from == "action-1"
        assert result.confidence == 0.65

    def test_action_fallback_strips_prefixes(self, mock_llm):
        """Action fallback strips Re:/Fwd: prefixes."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "action-2"
        email.sender = "test@test.com"
        email.subject = "Re: Fwd: Approuver la commande urgente"
        email.body = "..."

        result = use_case._create_fallback_rule(email, "Action")
        assert result is not None
        assert "re:" not in result.condition_value.lower()
        assert "fwd:" not in result.condition_value.lower()

    def test_action_fallback_needs_2_words(self, mock_llm):
        """Action fallback returns None for single-word subjects."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "action-3"
        email.sender = "test@test.com"
        email.subject = "OK"
        email.body = "..."

        result = use_case._create_fallback_rule(email, "Action")
        assert result is None

    def test_action_fallback_empty_subject(self, mock_llm):
        """Action fallback returns None for empty subject."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "action-4"
        email.sender = "test@test.com"
        email.subject = ""
        email.body = "Some body text"

        result = use_case._create_fallback_rule(email, "Action")
        assert result is None


# ============================================================================
# TEST: CUSTOM LABEL FALLBACK
# ============================================================================


class TestCustomLabelFallback:
    """Tests for custom label sender-based fallback rules."""

    def test_custom_label_creates_sender_rule(self, mock_llm):
        """Custom label fallback creates a sender-based rule."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "custom-1"
        email.sender = "John <john@project.com>"
        email.subject = "Update on the project"
        email.body = "..."

        result = use_case._create_fallback_rule(email, "MyProject")
        assert result is not None
        assert result.condition_type == "sender"
        assert result.condition_value == "john@project.com"
        assert result.label_name == "MyProject"
        assert result.confidence == 0.70

    def test_custom_label_with_llm_failure(self, mock_llm):
        """Custom label correction gets fallback when LLM fails."""
        from app.domain.exceptions import LLMConnectionError
        mock_llm.complete.side_effect = LLMConnectionError(
            provider="test", url="test", message="offline"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=TokenUsage())
        email = Mock()
        email.id = "custom-2"
        email.sender = "alice@team.com"
        email.subject = "Sprint update"
        email.body = "..."

        result = use_case.execute(email, ["FYI"], ["VIP"])
        assert len(result) == 1
        assert result[0].label_name == "VIP"
        assert result[0].condition_type == "sender"


# ============================================================================
# TEST: RULE PRUNING
# ============================================================================


class TestRulePruning:
    """Tests for rule pruning mechanism."""

    def test_prune_removes_disabled_old_rules(self, label_store):
        """Pruning removes disabled rules older than 90 days."""
        from datetime import timedelta

        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        recent_date = (datetime.now() - timedelta(days=10)).isoformat()

        # Old disabled rule (should be pruned)
        old_disabled = LabelingRule(
            rule_id="prune-1", label_name="Noise",
            condition_type="sender", condition_value="@old.com",
            is_active=False, disabled_reason="low_precision:30%",
            created_at=old_date, learned_from="e1",
        )
        # Recent disabled rule (should NOT be pruned)
        recent_disabled = LabelingRule(
            rule_id="prune-2", label_name="Noise",
            condition_type="sender", condition_value="@recent.com",
            is_active=False, disabled_reason="low_precision:40%",
            created_at=recent_date, learned_from="e2",
        )
        # Old active rule with usage (should NOT be pruned)
        old_active = LabelingRule(
            rule_id="prune-3", label_name="FYI",
            condition_type="sender", condition_value="friend@example.com",
            is_active=True, use_count=5, total_matches=5,
            created_at=old_date, learned_from="e3",
        )

        label_store.add_rule(old_disabled)
        label_store.add_rule(recent_disabled)
        label_store.add_rule(old_active)

        pruned = label_store.prune_inactive_rules(max_age_days=90)
        assert pruned == 1

        remaining = label_store.get_rules()
        remaining_ids = {r.rule_id for r in remaining}
        assert "prune-1" not in remaining_ids, "Old disabled should be pruned"
        assert "prune-2" in remaining_ids, "Recent disabled should remain"
        assert "prune-3" in remaining_ids, "Old active should remain"

    def test_prune_removes_unused_old_learned_rules(self, label_store):
        """Pruning removes learned rules with 0 usage older than 90 days."""
        from datetime import timedelta
        from app.domain.entities.email_labels import EmailLabel

        # LabelStore.add_rule rejects rules whose label_name isn't in the
        # library. The "Agentys" custom label below must be registered
        # first, otherwise the manual_unused rule is silently rejected and
        # the prune assertion on "prune-6" fails for the wrong reason.
        label_store.add_label(EmailLabel(
            name="Agentys",
            color="#0d9488",
            description="Custom Agentys label",
            is_default=False,
        ))

        old_date = (datetime.now() - timedelta(days=100)).isoformat()

        unused_old = LabelingRule(
            rule_id="prune-4", label_name="FYI",
            condition_type="sender", condition_value="unused@example.com",
            is_active=True, use_count=0, total_matches=0,
            created_at=old_date, learned_from="e4",
        )
        used_old = LabelingRule(
            rule_id="prune-5", label_name="FYI",
            condition_type="sender", condition_value="used@example.com",
            is_active=True, use_count=5, total_matches=10,
            created_at=old_date, learned_from="e5",
        )
        # Manual rule (no learned_from) should never be pruned
        manual_unused = LabelingRule(
            rule_id="prune-6", label_name="Agentys",
            condition_type="body", condition_value="agentys",
            is_active=True, use_count=0, total_matches=0,
            created_at=old_date,
        )

        assert label_store.add_rule(unused_old), "unused_old rule must be accepted"
        assert label_store.add_rule(used_old), "used_old rule must be accepted"
        assert label_store.add_rule(manual_unused), "manual_unused rule must be accepted"

        pruned = label_store.prune_inactive_rules(max_age_days=90)
        assert pruned == 1

        remaining = label_store.get_rules()
        remaining_ids = {r.rule_id for r in remaining}
        assert "prune-4" not in remaining_ids, "Unused old learned rule pruned"
        assert "prune-5" in remaining_ids, "Used old rule kept"
        assert "prune-6" in remaining_ids, "Manual rule never pruned"

    def test_prune_returns_zero_when_nothing_to_prune(self, label_store):
        """Pruning returns 0 when no rules to prune."""
        pruned = label_store.prune_inactive_rules()
        assert pruned == 0
