"""
E2E test suite for auto-labeling classification system.

Tests built-in rules + fast path across diverse email types.
Validates that Action, Noise, FYI, Waiting, and Security emails
are correctly classified, and that learned rules work.

pytest tests/application/test_label_auto_classification_e2e.py -v
"""

import pytest
from unittest.mock import Mock
from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import get_default_labels, LabelingRule


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def labels():
    return get_default_labels()


@pytest.fixture
def use_case(labels):
    """Use case sans LLM (pour tester les built-in rules uniquement)."""
    llm = Mock()
    llm.complete.return_value = Mock(
        content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
    )
    return LabelEmailUseCase(llm=llm, labels=labels, rules=[])


def make_email(sender="alice@company.com", subject="Test", body="", cc="", to="me@agentys.com"):
    email = Mock()
    email.id = "test-email"
    email.sender = sender
    email.subject = subject
    email.body = body
    email.to = to
    email.cc = cc
    email.recipients = [to] if to else []
    return email


def get_builtin_label(use_case, email):
    """Appelle _apply_builtin_rules directement pour tester les built-in."""
    email_data = {
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "recipients": getattr(email, "recipients", []),
        "is_cc": False,
    }
    results = use_case._apply_builtin_rules(email_data)
    if results:
        return results[0][0]  # label name
    return None


def get_fast_path_label(email):
    """Appelle classify_by_rules_only pour tester le fast path."""
    label_store = Mock()
    label_store.get_rules.return_value = []
    assignment = LabelEmailUseCase.classify_by_rules_only(email, label_store, "me@agentys.com")
    if assignment and assignment.default_label:
        return assignment.default_label
    return None


# ============================================================================
# 1. ACTION — Real people asking for things
# ============================================================================


class TestActionEmails:
    """Emails nécessitant une action de l'utilisateur → Action."""

    def test_direct_question_fr_dispo(self, use_case):
        email = make_email(body="Tu es dispo demain pour le meeting?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_fr_ca_te_dit(self, use_case):
        email = make_email(body="Ça te dit de déjeuner ensemble ce midi?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_fr_peux_tu(self, use_case):
        email = make_email(body="Peux-tu m'envoyer le fichier avant 17h?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_fr_pourrais_tu(self, use_case):
        email = make_email(body="Pourrais-tu relire ce document?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_fr_on_se_voit(self, use_case):
        email = make_email(body="On se voit vendredi pour en discuter?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_fr_quen_penses_tu(self, use_case):
        email = make_email(body="Voici ma proposition. Qu'en penses-tu?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_direct_question_en_what_do_you_think(self, use_case):
        email = make_email(body="I've drafted the proposal. What do you think?")
        assert get_builtin_label(use_case, email) == "Action"

    def test_invoice_payment_due(self, use_case):
        email = make_email(
            sender="accounting@vendor.com",
            subject="Invoice #4521 — payment due March 30",
            body="Please find attached invoice #4521. Payment due by March 30."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_payment_failed(self, use_case):
        email = make_email(
            sender="support@service.com",
            body="Your card was declined. Please update your payment method."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_please_review(self, use_case):
        email = make_email(body="Please review the attached document and let me know.")
        assert get_builtin_label(use_case, email) == "Action"

    def test_please_approve(self, use_case):
        email = make_email(body="Please approve the budget for Q2.")
        assert get_builtin_label(use_case, email) == "Action"

    def test_rsvp(self, use_case):
        email = make_email(body="RSVP for the team dinner on Friday.")
        assert get_builtin_label(use_case, email) == "Action"

    def test_action_required_subject(self, use_case):
        email = make_email(
            subject="Action required: update your banking info",
            body="Your banking information needs to be updated."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_response_needed(self, use_case):
        email = make_email(body="Response needed by end of day.")
        assert get_builtin_label(use_case, email) == "Action"

    def test_i_need_you_to(self, use_case):
        email = make_email(body="I need you to finalize the report today.")
        assert get_builtin_label(use_case, email) == "Action"

    def test_client_billing_question(self, use_case):
        email = make_email(
            sender="client@business.com",
            body="When is my next billing date? I want to know about my subscription renewal."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_overdue_payment(self, use_case):
        email = make_email(
            subject="Past due: Invoice #789",
            body="This invoice is overdue. Please settle the payment."
        )
        assert get_builtin_label(use_case, email) == "Action"


# ============================================================================
# 2. NOISE — Automated / marketing / newsletters
# ============================================================================


class TestNoiseEmails:
    """Emails automatisés, marketing, newsletters → Noise."""

    def test_noreply_sender(self, use_case):
        email = make_email(
            sender="noreply@company.com",
            body="Your monthly statement is ready."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_no_reply_sender(self, use_case):
        email = make_email(
            sender="no-reply@service.com",
            body="Your account settings have been updated."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_notifications_sender(self, use_case):
        email = make_email(
            sender="notifications@github.com",
            body="New comment on PR #123: looks good!"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_newsletter_with_unsubscribe(self, use_case):
        email = make_email(
            sender="info@techstartup.com",
            body="Discover our amazing new features today!\n\nUnsubscribe | Manage preferences"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_marketing_promo_fr(self, use_case):
        email = make_email(
            sender="promo@boutique.fr",
            body="Offre spéciale: -50% sur tout le site!\n\nSe désabonner"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_linkedin_notification(self, use_case):
        email = make_email(
            sender="notifications@linkedin.com",
            body="You have 5 new notifications this week."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_substack_newsletter(self, use_case):
        email = make_email(
            sender="author@substack.com",
            body="This week's edition: 10 tips for productivity."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_crypto_exchange(self, use_case):
        email = make_email(
            sender="info@binance.com",
            body="Your weekly portfolio update: BTC +5%."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_payment_received_receipt(self, use_case):
        email = make_email(
            sender="receipts@company.com",
            body="Payment received — $49.99. Thank you for your purchase."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_password_reset(self, use_case):
        email = make_email(
            sender="security@service.com",
            body="A password reset was requested for your account."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_weekly_digest_subject(self, use_case):
        email = make_email(
            sender="digest@platform.com",
            subject="Your weekly update — March 2026",
            body="Here's what happened this week."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_marketing_question_ready_to(self, use_case):
        """Marketing '?' rhétorique → toujours Noise."""
        email = make_email(
            sender="growth@saas.com",
            body="Ready to upgrade your workflow? Try our premium plan today!\n\nUnsubscribe"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_shop_now_cta(self, use_case):
        email = make_email(
            sender="deals@shop.com",
            body="Shop now and save 30% on all items! Limited time offer."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_dont_miss_fr(self, use_case):
        email = make_email(
            sender="marketing@brand.fr",
            body="Ne manquez pas notre vente flash! -40% sur tout."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_airdrop_crypto(self, use_case):
        email = make_email(
            sender="promo@crypto.io",
            body="Claim your airdrop now! 500 free tokens waiting."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_amazon_notification(self, use_case):
        email = make_email(
            sender="order-update@notification.amazon.com",
            body="Your package is on its way!"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_twitter_notification(self, use_case):
        email = make_email(
            sender="info@e.x.com",
            body="You have new mentions."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_strava_activity(self, use_case):
        email = make_email(
            sender="no-reply@strava.com",
            body="Great run today! You earned a new achievement."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_newsletter_subject(self, use_case):
        email = make_email(
            sender="editor@blog.com",
            subject="Newsletter: This week in tech",
            body="Welcome to this week's newsletter."
        )
        assert get_builtin_label(use_case, email) == "Noise"


# ============================================================================
# 3. FYI — Informational, no action needed
# ============================================================================


class TestFYIEmails:
    """Emails informatifs sans action requise → FYI."""

    def test_fyi_keyword(self, use_case):
        email = make_email(body="FYI: the budget report is attached.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_for_your_information(self, use_case):
        email = make_email(body="For your information, the meeting has been moved to 3pm.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_forwarded_email(self, use_case):
        email = make_email(
            subject="Fwd: Meeting notes from yesterday",
            body="See the forwarded notes below."
        )
        assert get_builtin_label(use_case, email) == "FYI"

    def test_heads_up(self, use_case):
        email = make_email(body="Just a heads up — server maintenance tonight at 11pm.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_no_action_needed(self, use_case):
        email = make_email(body="No action needed — just sharing the Q1 results with the team.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_out_of_office(self, use_case):
        email = make_email(body="I'm out of office until March 25. Contact Jean for urgent matters.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_pour_info_fr(self, use_case):
        email = make_email(body="Pour info: le rapport est disponible sur le drive.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_pas_besoin_de_repondre_fr(self, use_case):
        email = make_email(body="Pas besoin de répondre, juste pour te dire que le fix est en prod.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_just_letting_you_know(self, use_case):
        email = make_email(body="Just letting you know that I'll be late tomorrow.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_en_vacances_fr(self, use_case):
        email = make_email(body="Je suis en vacances du 20 au 27 mars.")
        assert get_builtin_label(use_case, email) == "FYI"


# ============================================================================
# 4. WAITING patterns → mapped to FYI in built-in rules
# ============================================================================


class TestWaitingPatterns:
    """Waiting patterns (ticket under review, etc.) sont mappés vers FYI."""

    def test_ticket_under_review(self, use_case):
        email = make_email(body="Your ticket #4521 is under review. We'll get back to you soon.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_we_have_received_your_request(self, use_case):
        email = make_email(body="We have received your request and will process it shortly.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_well_get_back_to_you(self, use_case):
        email = make_email(body="Thank you for reaching out. We'll get back to you within 48 hours.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_pending_approval(self, use_case):
        email = make_email(body="Your submission is pending approval.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_accuse_reception_fr(self, use_case):
        email = make_email(body="Nous avons bien reçu votre demande. Nous reviendrons vers vous sous 48h.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_en_cours_de_traitement_fr(self, use_case):
        email = make_email(body="Votre dossier est en cours de traitement.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_being_reviewed(self, use_case):
        email = make_email(body="Your application is being reviewed by our team.")
        assert get_builtin_label(use_case, email) == "FYI"

    def test_will_be_processed(self, use_case):
        email = make_email(body="Your refund will be processed within 5-7 business days.")
        assert get_builtin_label(use_case, email) == "FYI"


# ============================================================================
# 5. SECURITY — Override noise senders
# ============================================================================


class TestSecurityOverride:
    """Alertes sécurité depuis des senders non-automatisés → Action.
    Note: security patterns only fire for non-automated senders.
    Senders like alerts@, noreply@ are automated → security patterns skipped → Noise.
    """

    def test_unusual_signin_non_automated(self, use_case):
        """security@google.com n'est PAS dans NOISE_SENDER_PATTERNS → Action."""
        email = make_email(
            sender="security@google.com",
            body="Unusual sign-in detected on your account. If this wasn't you, change your password."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_suspicious_activity_non_automated(self, use_case):
        email = make_email(
            sender="security@bank.com",
            body="We detected suspicious activity on your account."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_verify_identity_non_automated(self, use_case):
        email = make_email(
            sender="security@platform.com",
            body="Please verify your identity to regain access."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_security_fr_activite_suspecte(self, use_case):
        """securite@banque.fr n'est PAS automatisé → Action."""
        email = make_email(
            sender="securite@banque.fr",
            body="Activité suspecte détectée sur votre compte. Veuillez vérifier."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_secure_your_account_non_automated(self, use_case):
        email = make_email(
            sender="security@service.com",
            body="Secure your account now. We noticed unusual login activity."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_security_from_automated_sender_is_noise(self, use_case):
        """alerts@ est un sender automatisé → security patterns ignorés → Noise."""
        email = make_email(
            sender="alerts@bank.com",
            body="We detected suspicious activity on your account."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_security_from_noreply_is_noise(self, use_case):
        """noreply@ est automatisé → security patterns ignorés → Noise."""
        email = make_email(
            sender="noreply@service.com",
            body="Your account has been locked due to multiple failed login attempts."
        )
        assert get_builtin_label(use_case, email) == "Noise"


# ============================================================================
# 6. EDGE CASES — Tricky classifications
# ============================================================================


class TestEdgeCases:
    """Cas limites et signaux mixtes."""

    def test_marketing_could_you_please_is_noise(self, use_case):
        """'Could you please' depuis un sender marketing → Noise."""
        email = make_email(
            sender="marketing@company.com",
            body="Could you please check out our new features?\n\nUnsubscribe"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_real_person_could_you_please_is_action(self, use_case):
        """'Could you please' depuis un vrai humain → Action."""
        email = make_email(
            sender="alice@company.com",
            body="Could you please send me the report by Friday?"
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_short_body_test_is_noise(self, use_case):
        """Body 'test' → Noise (empty/meaningless)."""
        email = make_email(body="test")
        assert get_builtin_label(use_case, email) == "Noise"

    def test_short_body_ok_is_noise(self, use_case):
        """Body 'ok' → Noise (empty/meaningless)."""
        email = make_email(body="ok")
        label = get_builtin_label(use_case, email)
        assert label in ("Noise", "FYI"), f"Short 'ok' should be Noise or FYI, got {label}"

    def test_noreply_with_invoice_is_noise(self, use_case):
        """Noreply sender + 'invoice' → Noise (noreply always overrides action patterns)."""
        email = make_email(
            sender="noreply@vendor.com",
            subject="Invoice #1234 attached",
            body="Please find your invoice attached. Payment due in 30 days."
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_real_sender_with_invoice_is_action(self, use_case):
        """Real sender + 'invoice' → Action (real person sending invoice)."""
        email = make_email(
            sender="comptabilite@vendor.fr",
            subject="Invoice #1234 attached",
            body="Please find your invoice attached. Payment due in 30 days."
        )
        assert get_builtin_label(use_case, email) == "Action"

    def test_newsletter_with_rhetorical_question(self, use_case):
        """Newsletter '?' rhétorique → Noise (pas Action)."""
        email = make_email(
            sender="newsletter@startup.fr",
            body="Tu veux découvrir nos nouvelles fonctionnalités? Clique ici!\n\nSe désabonner"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_empty_body_from_human_falls_to_llm(self, use_case):
        """Body vide depuis un humain → pas de règle (LLM fallback)."""
        email = make_email(sender="bob@team.com", subject="Hey", body="")
        label = get_builtin_label(use_case, email)
        assert label is None, "Empty body from human should fall to LLM"

    def test_receipt_with_question_mark(self, use_case):
        """'Where is my receipt?' → question réelle, pas pattern noise."""
        email = make_email(
            sender="alice@company.com",
            body="Where is my receipt? I haven't received it yet."
        )
        # Should NOT be Noise (question about receipt is a real question)
        label = get_builtin_label(use_case, email)
        assert label != "Noise", "Question about receipt should not be Noise"

    def test_do_you_want_from_marketing_is_noise(self, use_case):
        """'Do you want' depuis marketing → Noise."""
        email = make_email(
            sender="promos@shop.com",
            body="Do you want to save 20%? Use code SAVE20!\n\nUnsubscribe"
        )
        assert get_builtin_label(use_case, email) == "Noise"

    def test_invoice_paid_is_not_action(self, use_case):
        """'Invoice paid' / 'invoice confirmed' → Noise (not Action)."""
        email = make_email(
            sender="billing@service.com",
            body="Invoice paid. Payment confirmed — $150.00."
        )
        label = get_builtin_label(use_case, email)
        assert label != "Action", "'Invoice paid' should NOT be Action"


# ============================================================================
# 7. LEARNED RULES — User-defined rules applied correctly
# ============================================================================


class TestLearnedRules:
    """Vérifie que les règles apprises sont appliquées correctement."""

    def test_sender_rule_applied(self, labels):
        """Règle sender → label appliqué."""
        rule = LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="sender",
            condition_value="boss@company.com",
            priority=40,
            learned_from="email-123",
            confidence=0.9,
        )
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[rule])
        email = make_email(sender="boss@company.com", body="See you tomorrow.")
        email_data = {
            "sender": email.sender,
            "subject": email.subject,
            "body": email.body,
            "recipients": email.recipients,
            "is_cc": False,
        }
        results = uc._apply_rules(email_data)
        assert any(r[0] == "Action" for r in results), "Sender rule should match"

    def test_subject_rule_applied(self, labels):
        """Règle subject regex → label appliqué.

        ``subject_regex`` is the explicit regex condition type. Plain
        ``subject`` does literal-substring matching and would miss
        word-boundary patterns like ``\\bweekly report\\b``.
        """
        rule = LabelingRule(
            rule_id="rule-2",
            label_name="Noise",
            condition_type="subject_regex",
            condition_value=r"\bweekly report\b",
            priority=40,
            learned_from="email-456",
            confidence=0.85,
        )
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[rule])
        email = make_email(subject="Weekly report — March 2026", body="Here are the numbers.")
        email_data = {
            "sender": email.sender,
            "subject": email.subject,
            "body": email.body,
            "recipients": email.recipients,
            "is_cc": False,
        }
        results = uc._apply_rules(email_data)
        assert any(r[0] == "Noise" for r in results), "Subject rule should match"

    def test_body_rule_applied(self, labels):
        """Règle body_regex → label appliqué.

        Word-boundary regex requires ``body_regex``; plain ``body``
        does literal-substring matching.
        """
        rule = LabelingRule(
            rule_id="rule-3",
            label_name="FYI",
            condition_type="body_regex",
            condition_value=r"\bproject update\b",
            priority=40,
            learned_from="email-789",
            confidence=0.8,
        )
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[rule])
        email = make_email(body="Here's the project update for this sprint.")
        email_data = {
            "sender": email.sender,
            "subject": email.subject,
            "body": email.body,
            "recipients": email.recipients,
            "is_cc": False,
        }
        results = uc._apply_rules(email_data)
        assert any(r[0] == "FYI" for r in results), "Body rule should match"

    def test_user_rule_overrides_builtin(self, labels):
        """Règle utilisateur (priority 50) > built-in pour un sender noise."""
        rule = LabelingRule(
            rule_id="rule-4",
            label_name="Action",
            condition_type="sender",
            condition_value="noreply@important-vendor.com",
            priority=50,
            confidence=1.0,
        )
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[rule])
        email = make_email(
            sender="noreply@important-vendor.com",
            body="New shipment arriving tomorrow."
        )
        email_data = {
            "sender": email.sender,
            "subject": email.subject,
            "body": email.body,
            "recipients": email.recipients,
            "is_cc": False,
        }
        results = uc._apply_rules(email_data)
        assert any(r[0] == "Action" for r in results), "User rule should override builtin noise"

    def test_rule_no_match(self, labels):
        """Règle qui ne matche pas → pas de résultat."""
        rule = LabelingRule(
            rule_id="rule-5",
            label_name="Action",
            condition_type="sender",
            condition_value="specific@sender.com",
            priority=40,
            confidence=0.9,
        )
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[rule])
        email = make_email(sender="other@company.com", body="Hello there.")
        email_data = {
            "sender": email.sender,
            "subject": email.subject,
            "body": email.body,
            "recipients": email.recipients,
            "is_cc": False,
        }
        results = uc._apply_rules(email_data)
        assert not any(r[0] == "Action" for r in results), "Unmatched rule should not fire"


# ============================================================================
# 8. FAST PATH PARITY — Same results from both methods
# ============================================================================


class TestFastPathParity:
    """Vérifie que classify_by_rules_only donne les mêmes résultats que _apply_builtin_rules."""

    def test_noreply_fast_path(self):
        email = make_email(sender="noreply@company.com", body="Update available.")
        assert get_fast_path_label(email) == "Noise"

    def test_linkedin_fast_path(self):
        email = make_email(sender="messages@linkedin.com", body="You have new messages.")
        assert get_fast_path_label(email) == "Noise"

    def test_invoice_fast_path(self):
        email = make_email(subject="Invoice #999", body="Invoice attached. Payment due in 15 days.")
        assert get_fast_path_label(email) == "Action"

    def test_fyi_not_in_fast_path(self):
        """FYI patterns fall to LLM in fast path (not rule-detected)."""
        email = make_email(body="FYI: the deployment is complete.")
        label = get_fast_path_label(email)
        # FYI/Waiting patterns are only in _apply_builtin_rules, not fast path
        assert label is None, f"FYI should not be in fast path, got {label}"

    def test_security_from_non_automated_fast_path(self):
        """Security from non-automated sender → Action in fast path."""
        email = make_email(
            sender="security@google.com",
            body="Unusual sign-in detected. If this wasn't you, change your password."
        )
        assert get_fast_path_label(email) == "Action"

    def test_waiting_not_in_fast_path(self):
        """Waiting patterns fall to LLM in fast path."""
        email = make_email(body="Your ticket #100 is under review.")
        label = get_fast_path_label(email)
        assert label is None, f"Waiting should not be in fast path, got {label}"

    def test_receipt_fast_path(self):
        email = make_email(body="Payment received. Receipt attached.")
        assert get_fast_path_label(email) == "Noise"

    def test_human_question_no_fast_path(self):
        """Human question without strong patterns → falls to LLM (None)."""
        email = make_email(sender="alice@company.com", body="Hi, how are you doing?")
        label = get_fast_path_label(email)
        assert label is None, "Generic human email should fall to LLM"
