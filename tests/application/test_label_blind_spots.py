"""
Tests d'angles morts du système d'auto-labelling.

Couvre les edge cases identifiés lors de l'audit:
- Question mark false positives
- Automated signals + real person (footer unsubscribe)
- Invoice vs receipt ambiguïté
- Strong waiting + noise sender
- Weak patterns + automated signals (trop agressif)
- Forwarded emails
- Body vide/court mais significatif
- User rules override tout
- Generic rule rejection
- Pipeline ordering conflicts
- Multi-langue (au-delà FR/EN)

pytest tests/application/test_label_blind_spots.py -v
"""

import pytest
from unittest.mock import Mock
from app.application.label_email import LabelEmailUseCase, LearnLabelingRuleUseCase
from app.domain.entities.email_labels import (
    LabelingRule,
    get_default_labels,
)


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
    # Mock() auto-crée tout attribut en Mock truthy : `getattr(m, 'x', default)`
    # ne retourne jamais le default, et `Mock or ""` retourne le Mock — ce qui
    # casse les concaténations str dans label_email.py.
    email.body_html = ""
    email.attachments_meta = None
    email.headers = {}
    email.bcc = []
    email.thread_id = None
    email.conversation_id = None
    email.received_at = None
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


def get_builtin_result(use_case, email):
    """Retourne (label, confidence, reason) du built-in."""
    email_data = {
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "recipients": getattr(email, "recipients", []),
        "is_cc": False,
    }
    results = use_case._apply_builtin_rules(email_data)
    if results:
        return results[0]
    return None


# ============================================================================
# 1. QUESTION MARK FALSE POSITIVES
# ============================================================================


class TestQuestionMarkEdgeCases:
    """Le '?' dans body → Action (0.90) peut provoquer des faux positifs."""

    def test_url_with_query_params_should_not_be_action(self, use_case):
        """Un body avec juste une URL contenant ? ne devrait pas déclencher Action."""
        email = make_email(
            sender="noreply@service.com",  # noise sender → Noise avant la check ?
            body="Cliquez ici: https://example.com/page?utm_source=email&ref=123"
        )
        label = get_builtin_label(use_case, email)
        # Le sender noreply@ devrait catcher en Noise AVANT le check ?
        assert label == "Noise"

    def test_question_from_real_person_is_action(self, use_case):
        """Une vraie question d'une vraie personne = Action."""
        email = make_email(
            sender="alice@company.com",
            subject="Réunion",
            body="Tu es dispo demain à 14h?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_question_in_body_without_noise_sender(self, use_case):
        """? dans body d'un vrai humain → Action."""
        email = make_email(
            sender="bob@client.fr",
            body="Bonjour, est-ce que le rapport est prêt?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_url_query_from_real_person_still_action(self, use_case):
        """Un body avec une question ET une URL → Action (le ? est probablement une question)."""
        email = make_email(
            sender="alice@company.com",
            body="Tu as vu cet article? https://example.com/page?id=123"
        )
        label = get_builtin_label(use_case, email)
        # C'est correct: il y a une vraie question "Tu as vu cet article?"
        assert label == "Action"

    def test_body_only_url_no_question(self, use_case):
        """Un body avec seulement une URL (pas une question humaine) — pas de noise sender.
        FIXED in v3: smart question detection ignores ? in URLs (no interrogative word/direct address).
        """
        email = make_email(
            sender="alice@company.com",
            body="https://example.com/page?utm_source=email"
        )
        label = get_builtin_label(use_case, email)
        # v3: ? in URL is not a genuine question → no Action, falls through to LLM (None)
        assert label is None  # No builtin match, LLM fallback needed


# ============================================================================
# 2. AUTOMATED SIGNALS + REAL PERSON (FOOTER UNSUBSCRIBE)
# ============================================================================


class TestAutomatedSignalsEdgeCases:
    """Le footer 'unsubscribe' neutralise les weak patterns → faux négatifs."""

    def test_real_email_with_unsubscribe_footer(self, use_case):
        """FIXED: 'unsubscribe' dans body ne tue plus les strong patterns."""
        email = make_email(
            sender="alice@company.com",
            subject="Question rapide",
            body="Salut, pouvez-vous me confirmer la date?\n\n---\nPour vous désabonner: unsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "unsubscribe" moved to NOISE_SUBJECT_ONLY_PATTERNS
        # Body "?" triggers Action at step 4b
        assert label == "Action"

    def test_weak_action_killed_by_automated_signal(self, use_case):
        """Weak action + automated signal (gérer préférences) → Noise (by design)."""
        email = make_email(
            sender="alice@company.com",
            subject="Merci de confirmer",
            body="Merci de confirmer votre présence.\n\nPour gérer vos préférences: cliquez ici"
        )
        label = get_builtin_label(use_case, email)
        # "merci de" is weak action, "gérer vos préférences" is automated signal
        # Weak action + automated = Noise (by design — automated signals neutralize weak patterns)
        assert label == "Noise"

    def test_strong_action_survives_unsubscribe_in_body(self, use_case):
        """FIXED: Strong action survives 'unsubscribe' in body."""
        email = make_email(
            sender="alice@company.com",
            subject="Please review the contract",
            body="Please review the attached document.\n\nUnsubscribe from this list"
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "unsubscribe" only in NOISE_SUBJECT_ONLY_PATTERNS
        # "please review" fires at step 1b (strong action override)
        assert label == "Action"

    def test_fyi_killed_by_automated_signals(self, use_case):
        """Un weak FYI + automated signal → pas de label (tombe au LLM)."""
        email = make_email(
            sender="alice@company.com",
            subject="Fwd: article intéressant",
            body="Je voulais te partager cet article.\n\nGérer vos notifications"
        )
        label = get_builtin_label(use_case, email)
        # "Fwd:" est weak FYI, "je voulais te partager" aussi
        # "gérer vos notifications" est un automated signal
        # Weak FYI + automated = rien (tombe au LLM)
        # MAIS le body contient aucun ? donc pas d'Action
        assert label is None  # Tombe au LLM


# ============================================================================
# 3. INVOICE VS RECEIPT EDGE CASES
# ============================================================================


class TestInvoiceReceiptEdgeCases:
    """Le regex invoice avec negative lookahead (?!.*paid|receipt|confirmed)."""

    def test_invoice_simple_is_action(self, use_case):
        """Invoice simple → Action."""
        email = make_email(subject="Invoice #1234", body="Payment due by March 15")
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_invoice_paid_is_not_action(self, use_case):
        """Invoice paid → pas Action (la negative lookahead fonctionne)."""
        email = make_email(subject="Invoice #1234 - paid", body="Thank you for your payment")
        label = get_builtin_label(use_case, email)
        # "invoice" + "paid" dans le sujet → la regex ne matche pas
        # Mais "receipt" pourrait matcher via NOISE_TEXT_PATTERNS
        assert label != "Action"

    def test_invoice_receipt_is_noise(self, use_case):
        """Invoice receipt → Noise."""
        email = make_email(subject="Invoice receipt", body="Payment confirmed")
        label = get_builtin_label(use_case, email)
        # "invoice" sujet a "receipt" donc pas Action
        # "receipt" matche NOISE_TEXT_PATTERNS → Noise
        assert label == "Noise"

    def test_invoice_with_confirmed_in_body(self, use_case):
        """FIXED: Invoice subject + 'confirmed' in body → not Action (cross-field check)."""
        email = make_email(
            subject="Invoice #789",
            body="Your payment has been confirmed. Thank you."
        )
        label = get_builtin_label(use_case, email)
        # FIXED: Strong action step 1b now checks body for "paid/confirmed" when
        # invoice matches in subject → skips → falls through to Noise patterns
        # "payment confirmed" in body matches NOISE_TEXT_PATTERNS → Noise
        assert label == "Noise"

    def test_invoice_payment_due_is_action(self, use_case):
        """Payment due → Action."""
        email = make_email(
            subject="Your payment is past due",
            body="Please pay the outstanding amount of $500"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_receipt_in_subject_is_noise(self, use_case):
        """Receipt dans subject → Noise."""
        email = make_email(subject="Payment receipt - Order #456")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_payout_notification_is_noise(self, use_case):
        """Payout notification → Noise."""
        email = make_email(
            sender="noreply@stripe.com",
            subject="Your payout is on the way",
            body="A payout of $1,234.56 will arrive in 2 days"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise"


# ============================================================================
# 4. STRONG WAITING + NOISE SENDER
# ============================================================================


class TestStrongWaitingVsNoiseSender:
    """Strong waiting overrides noise senders — est-ce toujours correct?"""

    def test_support_ticket_from_noreply_is_waiting(self, use_case):
        """Support ticket de noreply → Waiting (correct)."""
        email = make_email(
            sender="noreply@support.company.com",
            subject="Re: Your support ticket #12345",
            body="We have received your request. We'll get back to you within 24 hours."
        )
        label = get_builtin_label(use_case, email)
        # Strong waiting "we'll get back to you" overrides noise sender
        assert label == "FYI"

    def test_newsletter_promising_followup_is_waiting(self, use_case):
        """Newsletter disant 'we'll get back to you' → Waiting (faux positif potentiel)."""
        email = make_email(
            sender="newsletter@marketing.com",
            subject="Weekly Product Update",
            body="Exciting news! We'll get back to you with more details about our launch."
        )
        label = get_builtin_label(use_case, email)
        # Angle mort: "we'll get back to you" est strong waiting (0.90)
        # mais c'est un newsletter → devrait être Noise
        assert label == "FYI"  # Angle mort: devrait être Noise

    def test_automated_review_confirmation_is_waiting(self, use_case):
        """Confirmation automatique de review → Waiting (correct)."""
        email = make_email(
            sender="noreply@service.com",
            subject="Your submission is under review",
            body="Thank you for your submission. It is currently being reviewed."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"

    def test_french_waiting_from_automated(self, use_case):
        """Accusé de réception français → Waiting (correct)."""
        email = make_email(
            sender="noreply@mairie.fr",
            subject="Accusé de réception",
            body="Nous avons bien reçu votre demande. Votre dossier est en cours de traitement."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"


# ============================================================================
# 5. EMPTY/SHORT BODY EDGE CASES
# ============================================================================


class TestEmptyBodyEdgeCases:
    """Corps vide ou très court — certains sont significatifs."""

    def test_just_test_is_noise(self, use_case):
        """Body 'test' seul → Noise."""
        email = make_email(sender="alice@company.com", body="test")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_test_cc_is_noise(self, use_case):
        """Body 'test CC' → Noise."""
        email = make_email(body="test CC")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_ok_is_noise(self, use_case):
        """Body 'ok' → Noise."""
        email = make_email(body="ok")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_single_dot_is_noise(self, use_case):
        """Body '.' → Noise."""
        email = make_email(body=".")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_three_chars_is_noise(self, use_case):
        """Body 'abc' → Noise (≤3 chars)."""
        email = make_email(body="abc")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_short_question_is_action(self, use_case):
        """FIXED: Body 'ok?' → Action (? guard skips empty body check)."""
        email = make_email(body="ok?")
        label = get_builtin_label(use_case, email)
        # FIXED: Empty body check now skips if body contains "?"
        # "ok?" has "?" → skip empty body → step 4b: "?" in body → Action
        assert label == "Action"

    def test_four_char_body_not_noise(self, use_case):
        """Body 'cool' (4 chars) → pas Noise par le regex vide."""
        email = make_email(body="cool")
        label = get_builtin_label(use_case, email)
        # "cool" = 4 chars → ne matche pas .{0,3}
        # Pas de patterns → tombe au LLM
        assert label is None

    def test_meaningful_short_body(self, use_case):
        """Body 'RDV 14h' court mais significatif → pas Noise."""
        email = make_email(body="RDV 14h")
        label = get_builtin_label(use_case, email)
        # 6 chars, pas d'empty pattern match
        # Pas de strong/weak patterns match
        # Tombe au LLM
        assert label is None

    def test_merci_is_noise(self, use_case):
        """Body 'merci' seul → Noise."""
        email = make_email(body="merci")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"

    def test_thanks_exclamation_is_noise(self, use_case):
        """Body 'thanks!' → Noise."""
        email = make_email(body="thanks!")
        label = get_builtin_label(use_case, email)
        assert label == "Noise"


# ============================================================================
# 6. FORWARDED EMAILS (Fwd: prefix)
# ============================================================================


class TestForwardedEmails:
    """Les emails transférés (Fwd:, Tr:) ont un weak FYI pattern."""

    def test_fwd_prefix_is_fyi(self, use_case):
        """Sujet avec 'Fwd:' → FYI (si pas automatisé)."""
        email = make_email(
            sender="alice@company.com",
            subject="Fwd: Proposition commerciale",
            body="Voici la proposition dont je te parlais."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"

    def test_tr_prefix_is_fyi(self, use_case):
        """Sujet avec 'Tr:' (français) → FYI."""
        email = make_email(
            sender="alice@company.com",
            subject="Tr: Compte-rendu réunion",
            body="Comme discuté ce matin."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"

    def test_fw_prefix_is_fyi(self, use_case):
        """Sujet avec 'Fw:' → FYI."""
        email = make_email(
            sender="bob@partner.com",
            subject="Fw: Important document",
            body="See the document below."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"

    def test_fwd_with_question_is_action(self, use_case):
        """Fwd + question dans body → Action (question > Fwd)."""
        email = make_email(
            sender="alice@company.com",
            subject="Fwd: Contract draft",
            body="What do you think about this?"
        )
        label = get_builtin_label(use_case, email)
        # "what do you think" is a strong action pattern → Action (0.90)
        # Strong action (step 4) comes before weak FYI (step 8)
        assert label == "Action"

    def test_fwd_with_unsubscribe_falls_to_weak_fyi(self, use_case):
        """FIXED: Fwd + 'unsubscribe' in body → weak FYI neutralized by automated signal."""
        email = make_email(
            sender="alice@company.com",
            subject="Fwd: Interesting tech article",
            body="Check this out.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "unsubscribe" only in NOISE_SUBJECT_ONLY (not body)
        # "Fwd:" is weak FYI but "unsubscribe" is in AUTOMATED_SIGNALS_RE
        # Weak FYI + automated signal = nothing → falls to LLM
        assert label is None


# ============================================================================
# 7. NOISE SENDER WITH REAL CONTENT
# ============================================================================


class TestNoiseSenderWithRealContent:
    """Les noise senders sont toujours Noise, même avec du contenu important."""

    def test_noreply_with_action_content_is_action(self, use_case):
        """noreply@ + 'confirm your account' → Action via step 0-verify.

        Comportement changé par cd630d67 (P4 follow-up) : les patterns de
        vérification compte/email/2FA dans subject ou body forcent Action
        AVANT step 1b-noreply. Évite que les codes de vérification 2FA
        soient enterrés en Noise quand l'expéditeur est `noreply@`.
        """
        email = make_email(
            sender="noreply@service.com",
            subject="Please review your account",
            body="Please review and confirm your account details."
        )
        label = get_builtin_label(use_case, email)
        # step 0-verify match `\bconfirm\s+(?:your\s+)?account\b` dans body
        # → Action AVANT que step 1b-noreply ait une chance de fire.
        assert label == "Action"

    def test_noreply_with_invoice_is_noise(self, use_case):
        """noreply@ + invoice → Noise (automated invoice notification)."""
        email = make_email(
            sender="noreply@billing.com",
            subject="Invoice #456",
            body="Your invoice for $500 is ready"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ at step 1b-noreply → Noise before invoice check
        assert label == "Noise"

    def test_real_sender_with_invoice_is_action(self, use_case):
        """Real sender + invoice → Action."""
        email = make_email(
            sender="finance@vendor.com",
            subject="Invoice #456",
            body="Your invoice for $500 is ready"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_noreply_with_waiting_is_waiting(self, use_case):
        """noreply@ + strong waiting → Waiting (step 1 overrides step 2)."""
        email = make_email(
            sender="noreply@support.com",
            subject="Ticket update",
            body="Your request has been received and is under review."
        )
        label = get_builtin_label(use_case, email)
        # Step 1: "under review" → strong waiting → MATCHES → Waiting
        assert label == "FYI"


# ============================================================================
# 8. USER RULES OVERRIDE EVERYTHING
# ============================================================================


class TestUserRulesOverride:
    """Les user rules prennent le dessus sur tous les built-in."""

    def test_user_rule_overrides_noise_sender(self, labels):
        """User rule peut forcer Action même sur un noise sender."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Action", condition_type="sender",
                condition_value="noreply@important-billing.com", priority=100, confidence=0.95
            )
        ]
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=rules)
        email = make_email(
            sender="noreply@important-billing.com",
            subject="Invoice due",
            body="Please pay"
        )
        result = uc.execute(email)
        assert result.default_label == "Action"

    def test_user_rule_overrides_builtin_action(self, labels):
        """User rule peut forcer Noise même sur un email avec strong action."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Noise", condition_type="sender",
                condition_value="@spammy-person.com", priority=100, confidence=0.95
            )
        ]
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=rules)
        email = make_email(
            sender="bob@spammy-person.com",
            subject="Please review this document",
            body="Could you please review the attached?"
        )
        result = uc.execute(email)
        assert result.default_label == "Noise"

    def test_multiple_user_rules_first_wins(self, labels):
        """Parmi plusieurs user rules, la première (plus haute priorité) gagne."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Action", condition_type="subject",
                condition_value="facture", priority=100, confidence=0.95
            ),
            LabelingRule(
                rule_id="r2", label_name="Noise", condition_type="sender",
                condition_value="@billing.com", priority=50, confidence=0.90
            ),
        ]
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=rules)
        email = make_email(
            sender="auto@billing.com",
            subject="Votre facture mensuelle"
        )
        result = uc.execute(email)
        # r1 (priorité 100) matche "facture" → Action
        assert result.default_label == "Action"


# ============================================================================
# 9. CC DETECTION EDGE CASES
# ============================================================================


class TestCCDetectionEdgeCases:
    """Edge cases dans la détection CC."""

    def test_user_in_both_to_and_cc(self, labels):
        """User dans TO et CC → pas en CC (TO prend le dessus)."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": [{"name": "Action", "confidence": 0.9, "reason": "test"}]}',
            input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[], user_email="me@test.com")
        email = make_email(to="me@test.com", cc="me@test.com, other@test.com")
        result = uc.execute(email)
        assert result.is_cc is False

    def test_cc_with_multiple_recipients(self, labels):
        """User dans CC parmi plusieurs → CC détecté."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[], user_email="me@test.com")
        email = make_email(to="alice@test.com", cc="bob@test.com, me@test.com, carol@test.com")
        result = uc.execute(email)
        assert result.is_cc is True
        assert "FYI" in result.labels

    def test_cc_case_insensitive(self, labels):
        """CC détecté même avec casse différente."""
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
        )
        uc = LabelEmailUseCase(llm=llm, labels=labels, rules=[], user_email="Me@Test.com")
        email = make_email(to="alice@test.com", cc="ME@TEST.COM")
        result = uc.execute(email)
        assert result.is_cc is True


# ============================================================================
# 10. PIPELINE ORDERING CONFLICTS
# ============================================================================


class TestPipelineOrdering:
    """L'ordre du pipeline détermine le label final."""

    def test_strong_waiting_beats_noise_sender(self, use_case):
        """Strong waiting (step 1) > Noise sender (step 2)."""
        email = make_email(
            sender="noreply@company.com",
            body="We have received your request. We'll get back to you within 48 hours."
        )
        label = get_builtin_label(use_case, email)
        assert label == "FYI"

    def test_verify_email_beats_noise_sender(self, use_case):
        """noreply@ + 'Verify your email' → Action via step 0-verify.

        Comportement changé par cd630d67 (P4 follow-up) : un subject qui
        match la regex `\\bverify\\s+(?:your\\s+)?(?:device|email|account|phone)\\b`
        force Action AVANT step 1b-noreply. Crucial pour que les emails
        de vérification de compte ne soient jamais perdus en Noise.
        """
        email = make_email(
            sender="noreply@newsletter.com",
            subject="Action required: Verify your email",
            body="Please confirm your subscription."
        )
        label = get_builtin_label(use_case, email)
        # step 0-verify > step 1b-noreply (intentional, P4 design).
        assert label == "Action"

    def test_strong_action_beats_noise_subject(self, use_case):
        """FIXED: Strong action (step 1b) > Noise subject-only (step 3b)."""
        email = make_email(
            sender="alice@company.com",
            subject="Newsletter: Please review our latest article",
            body="Don't miss our discount offer!"
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "please review" strong action at step 1b fires before
        # "newsletter" noise subject-only at step 3b → Action
        assert label == "Action"

    def test_strong_action_beats_question_mark(self, use_case):
        """Strong action (step 4) matches before ? (step 4b)."""
        email = make_email(
            sender="alice@company.com",
            body="Could you please send me the report? Thanks."
        )
        label = get_builtin_label(use_case, email)
        # "could you please" is strong action → Action (step 4)
        assert label == "Action"

    def test_question_beats_strong_fyi(self, use_case):
        """? (step 4b) > Strong FYI (step 5)."""
        email = make_email(
            sender="alice@company.com",
            body="FYI, the project is on track. Do you need more details?"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → Action (step 4b)
        # "FYI" strong pattern would be step 5 but step 4b fires first
        assert label == "Action"

    def test_empty_body_beats_noise_sender(self, use_case):
        """Empty body (step 1b) > Noise sender (step 2)."""
        email = make_email(
            sender="alice@company.com",
            body="test"
        )
        label = get_builtin_label(use_case, email)
        # "test" matches empty body pattern (step 1b)
        # Even from a real sender
        assert label == "Noise"


# ============================================================================
# 11. GENERIC RULE REJECTION
# ============================================================================


class TestGenericRuleRejection:
    """Vérifier que les règles trop génériques sont rejetées."""

    def test_single_word_subject_rejected(self):
        """Mot seul dans subject rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "test", "Action") is True
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "hello", "FYI") is True
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "meeting", "Action") is True

    def test_short_subject_rejected(self):
        """Subject < 5 chars et sans espace → rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "abc", "Action") is True
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "todo", "Action") is True

    def test_multi_word_subject_accepted(self):
        """Multi-mots dans subject → accepté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "facture impayée", "Action") is False
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "meeting demain", "Action") is False

    def test_sender_action_rejected(self):
        """sender → Action toujours rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("sender", "alice@company.com", "Action") is True

    def test_sender_noise_accepted(self):
        """sender → Noise accepté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("sender", "@newsletter.com", "Noise") is False

    def test_sender_too_short_rejected(self):
        """Sender < 5 chars et sans @ → rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("sender", "abc", "Noise") is True

    def test_empty_value_rejected(self):
        """Valeur vide → rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("subject", "", "Action") is True
        assert LearnLabelingRuleUseCase._is_rule_too_generic("sender", "a", "Noise") is True

    def test_body_generic_word_rejected(self):
        """Mots génériques dans body → rejeté."""
        assert LearnLabelingRuleUseCase._is_rule_too_generic("body", "urgent", "Action") is True
        assert LearnLabelingRuleUseCase._is_rule_too_generic("body", "info", "FYI") is True


# ============================================================================
# 12. MULTI-LANGUAGE (beyond FR/EN)
# ============================================================================


class TestMultiLanguage:
    """Emails dans d'autres langues que FR/EN tombent au LLM."""

    def test_spanish_fyi_no_builtin(self, use_case):
        """FYI en espagnol → pas de builtin (tombe au LLM)."""
        email = make_email(
            sender="carlos@empresa.es",
            subject="Información importante",
            body="Hola, solo quería informarte sobre el proyecto."
        )
        label = get_builtin_label(use_case, email)
        # Pas de pattern match, pas de ?, pas de noise → LLM
        assert label is None

    def test_italian_action_no_builtin(self, use_case):
        """Demande d'action en italien → pas de builtin."""
        email = make_email(
            sender="mario@azienda.it",
            subject="Richiesta urgente",
            body="Potresti inviarmi il documento per favore"
        )
        label = get_builtin_label(use_case, email)
        # Pas de pattern FR/EN
        # Pas de "?" dans body → pas de question rule
        assert label is None  # Angle mort: action en italien non détectée

# ============================================================================
# 13. NOISE TEXT PATTERNS - EDGE CASES
# ============================================================================


class TestNoiseTextPatternsEdgeCases:
    """Edge cases dans les patterns texte Noise."""

    def test_receipt_in_real_email(self, use_case):
        """'receipt' dans un email réel humain → Noise (faux positif?)."""
        email = make_email(
            sender="alice@company.com",
            subject="Please keep this receipt",
            body="Here's the receipt for your expenses."
        )
        label = get_builtin_label(use_case, email)
        # "receipt" in subject → Noise (step 3)
        assert label == "Noise"  # Pourrait être FYI dans certains contextes

    def test_word_sale_in_business_email(self, use_case):
        """FIXED: 'sale' in subject → Noise (subject-only, correct for marketing)."""
        email = make_email(
            sender="alice@company.com",
            subject="The house sale is progressing well",
            body="Good news about the property sale."
        )
        label = get_builtin_label(use_case, email)
        # "sale" in subject → Noise (subject-only pattern step 3b)
        # Note: this is a tradeoff — "sale" in subject is usually marketing
        assert label == "Noise"

    def test_sale_only_in_body_not_noise(self, use_case):
        """FIXED: 'sale' only in body (not subject) → no longer Noise."""
        email = make_email(
            sender="alice@company.com",
            subject="Property update",
            body="Good news about the property sale."
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "sale" moved to NOISE_SUBJECT_ONLY_PATTERNS → body not checked
        assert label is None  # Falls to LLM (correct)

    def test_crypto_in_legitimate_email(self, use_case):
        """FIXED: 'crypto' in subject → still Noise (subject-only)."""
        email = make_email(
            sender="alice@company.com",
            subject="Crypto project update",
            body="The crypto implementation is going well."
        )
        label = get_builtin_label(use_case, email)
        # "crypto" in subject → Noise (subject-only)
        assert label == "Noise"

    def test_crypto_only_in_body_not_noise(self, use_case):
        """FIXED: 'crypto' only in body → no longer Noise."""
        email = make_email(
            sender="alice@company.com",
            subject="Project update",
            body="The crypto implementation is going well."
        )
        label = get_builtin_label(use_case, email)
        # FIXED: "crypto" in NOISE_SUBJECT_ONLY → body not checked
        assert label is None  # Falls to LLM

    def test_verification_from_real_person(self, use_case):
        """FIXED: 'verification' subject but strong action in body → Action."""
        email = make_email(
            sender="alice@company.com",
            subject="Document verification needed",
            body="I need you to verify these documents."
        )
        label = get_builtin_label(use_case, email)
        # "I need you to" in body is a strong action pattern (step 1b)
        # Strong action fires BEFORE noise subject-only patterns (step 3b)
        assert label == "Action"

    def test_discount_in_business_negotiation(self, use_case):
        """FIXED: 'discount' in subject → Noise (still subject-only)."""
        email = make_email(
            sender="supplier@parts.com",
            subject="Regarding the volume discount",
            body="We can offer a 10% discount on bulk orders."
        )
        label = get_builtin_label(use_case, email)
        # "discount" in subject → Noise (subject-only)
        assert label == "Noise"


# ============================================================================
# 14. CLASSIFY BY RULES ONLY (fast path)
# ============================================================================


class TestClassifyByRulesOnly:
    """Test du fast path sans LLM."""

    def test_noise_sender_returns_assignment(self, labels):
        """Noise sender retourne un LabelAssignment."""
        email = make_email(sender="noreply@service.com", subject="Notification")
        from unittest.mock import MagicMock
        label_store = MagicMock()
        label_store.get_rules.return_value = []
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store)
        assert result is not None
        assert result.default_label == "Noise"

    def test_action_pattern_returns_assignment(self, labels):
        """Strong action retourne un LabelAssignment."""
        email = make_email(
            sender="alice@company.com",
            subject="Please review the proposal",
            body="Attached is the proposal."
        )
        from unittest.mock import MagicMock
        label_store = MagicMock()
        label_store.get_rules.return_value = []
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store)
        assert result is not None
        assert result.default_label == "Action"

    def test_no_match_returns_none(self, labels):
        """Pas de match → None (LLM needed)."""
        email = make_email(
            sender="alice@company.com",
            subject="Bonjour",
            body="Juste un petit mot pour te dire que tout va bien."
        )
        from unittest.mock import MagicMock
        label_store = MagicMock()
        label_store.get_rules.return_value = []
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store)
        assert result is None

    def test_user_rule_has_priority_in_fast_path(self, labels):
        """User rules prennent le dessus dans le fast path aussi."""
        email = make_email(
            sender="noreply@billing.com",
            subject="Invoice #789",
            body="Payment due"
        )
        from unittest.mock import MagicMock
        label_store = MagicMock()
        label_store.get_rules.return_value = [
            LabelingRule(
                rule_id="r1", label_name="Action", condition_type="subject",
                condition_value="invoice", priority=100, confidence=0.95
            )
        ]
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store)
        assert result is not None
        assert result.default_label == "Action"

    def test_cc_returns_fyi_in_fast_path(self, labels):
        """CC → FYI dans le fast path."""
        email = make_email(to="alice@company.com", cc="me@agentys.com")
        from unittest.mock import MagicMock
        label_store = MagicMock()
        label_store.get_rules.return_value = []
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store, user_email="me@agentys.com")
        assert result is not None
        assert result.default_label == "FYI"
