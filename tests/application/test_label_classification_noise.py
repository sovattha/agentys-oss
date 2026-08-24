# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests de classification Noise vs Action.

Vérifie que les newsletters, emails marketing et automatisés sont correctement
labellisés Noise au lieu d'Action, même quand ils contiennent des patterns
qui ressemblent à des actions (questions rhétoriques, "could you please", etc.)

pytest tests/application/test_label_classification_noise.py -v
"""

import pytest
from unittest.mock import Mock
from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import get_default_labels


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
# 1. NEWSLETTERS AVEC "?" → NOISE (pas Action)
# ============================================================================


class TestNewsletterWithQuestion:
    """Les newsletters contenant des questions rhétoriques doivent rester Noise."""

    def test_newsletter_with_question_in_body(self, use_case):
        """Newsletter classique avec '?' rhétorique → Noise."""
        email = make_email(
            sender="info@techcompany.com",
            body="Ready to upgrade your workflow? Try our new features today.\n\nUnsubscribe | Manage preferences"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "Newsletter avec '?' rhétorique devrait être Noise"

    def test_newsletter_with_multiple_questions(self, use_case):
        """Newsletter avec 3+ '?' → ne devrait PAS auto-déclencher Action."""
        email = make_email(
            sender="info@media.com",
            body="Ready for change? Want more? Need help? Click here to learn more.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "Newsletter avec 3+ '?' rhétoriques devrait être Noise"

    def test_marketing_question_with_unsubscribe(self, use_case):
        """Email marketing avec pattern 'want to' + unsubscribe → Noise."""
        email = make_email(
            sender="growth@saas.com",
            body="Want to save 20%? Shop now!\n\nSe désabonner | View in browser"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "Marketing email avec 'Want to' + unsubscribe devrait être Noise"


# ============================================================================
# 2. EMAILS MARKETING AVEC PATTERNS ACTION → NOISE
# ============================================================================


class TestMarketingWithActionPatterns:
    """Les patterns action communs dans les emails marketing doivent être ignorés."""

    def test_could_you_please_in_marketing(self, use_case):
        """'Could you please' dans un email marketing → Noise (pas Action)."""
        email = make_email(
            sender="marketing@company.com",
            body="Could you please take a moment to review our new features?\n\nUnsubscribe | Manage preferences"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'Could you please' dans marketing devrait être Noise"

    def test_do_you_want_in_promo(self, use_case):
        """'Do you want' dans un email promo → Noise."""
        email = make_email(
            sender="promos@shop.com",
            body="Do you want to save 20%? Use code SAVE20 at checkout.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'Do you want' dans promo devrait être Noise"

    def test_would_you_like_to_upgrade(self, use_case):
        """'Would you like to upgrade?' dans un email SaaS → Noise."""
        email = make_email(
            sender="growth@saas.com",
            body="Would you like to upgrade to premium?\n\nManage your subscription preferences"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'Would you like' dans SaaS marketing devrait être Noise"

    def test_are_you_available_in_newsletter(self, use_case):
        """'Are you available' dans une newsletter → Noise."""
        email = make_email(
            sender="events@conference.com",
            body="Are you available for our annual conference? Register now!\n\nUnsubscribe from this list"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'Are you available' dans newsletter devrait être Noise"

    def test_tu_veux_in_newsletter_fr(self, use_case):
        """'Tu veux' dans une newsletter FR → Noise."""
        email = make_email(
            sender="newsletter@startup.fr",
            body="Tu veux découvrir nos nouvelles fonctionnalités ? Clique ici !\n\nSe désabonner"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'Tu veux' dans newsletter FR devrait être Noise"


# ============================================================================
# 3. EMAILS DE VRAIS HUMAINS → TOUJOURS ACTION
# ============================================================================


class TestRealPersonStaysAction:
    """Les vrais humains posant des questions doivent rester Action."""

    def test_real_person_tu_es_dispo(self, use_case):
        """Vrai humain: 'Tu es dispo demain?' → Action."""
        email = make_email(
            sender="alice@company.com",
            body="Tu es dispo demain?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "Vrai humain 'Tu es dispo?' devrait être Action"

    def test_real_person_tu_veux_venir(self, use_case):
        """Vrai humain: 'Tu veux venir au resto?' → Action."""
        email = make_email(
            sender="alice@company.com",
            body="Salut! Tu veux venir au resto ce soir?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "Vrai humain 'Tu veux venir?' devrait être Action"

    def test_real_person_are_you_free(self, use_case):
        """Vrai humain: 'Are you free tomorrow?' → Action."""
        email = make_email(
            sender="bob@team.com",
            body="Hey, are you free tomorrow for a quick call?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "Vrai humain 'Are you free?' devrait être Action"

    def test_real_person_could_you_please(self, use_case):
        """Vrai humain: 'Could you please review this?' → Action."""
        email = make_email(
            sender="manager@company.com",
            body="Could you please review this document by Friday?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "Vrai humain 'Could you please' devrait être Action"

    def test_real_person_would_you_like(self, use_case):
        """Vrai humain: 'Would you like to join us?' → Action."""
        email = make_email(
            sender="colleague@company.com",
            body="Would you like to join us for lunch?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "Vrai humain 'Would you like' devrait être Action"

    def test_real_person_what_do_you_think(self, use_case):
        """Vrai humain: 'What do you think about this?' → Action (unconditional strong)."""
        email = make_email(
            sender="peer@company.com",
            body="I just finished the design. What do you think?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "'What do you think' devrait toujours être Action"


# ============================================================================
# 4. NOREPLY@ AVEC "?" → NOISE
# ============================================================================


class TestNoreplyWithQuestion:
    """noreply@ senders avec des questions doivent être Noise."""

    def test_noreply_with_question(self, use_case):
        """noreply@ + question → Noise (noise sender détecté en premier)."""
        email = make_email(
            sender="noreply@service.com",
            body="Satisfied with your purchase? Rate your experience."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "noreply@ avec '?' devrait être Noise"

    def test_notification_sender_with_question(self, use_case):
        """notifications@ + question → Noise."""
        email = make_email(
            sender="notifications@platform.com",
            body="Did you know about our new features? Check them out!"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "notifications@ avec '?' devrait être Noise"


# ============================================================================
# 5. REGRESSIONS — Les patterns critiques doivent continuer à fonctionner
# ============================================================================


class TestCriticalPatternsRegression:
    """Regression: patterns critiques avec senders variés (noreply = Noise, real = Action)."""

    def test_invoice_from_noreply_is_noise(self, use_case):
        """Invoice depuis noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@billing.com",
            subject="Invoice #12345 — Payment due",
            body="Please pay your invoice of $500 by March 30."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "noreply@ sender devrait toujours être Noise"

    def test_please_review_stays_action(self, use_case):
        """'Please review' from system@ → Noise (system@ is automated sender)."""
        email = make_email(
            sender="system@company.com",
            body="Please review the attached contract and sign by EOD.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "'system@' is automated → Noise"

    def test_please_review_from_real_person(self, use_case):
        """'Please review' from real person → Action."""
        email = make_email(
            sender="alice@company.com",
            body="Please review the attached contract and sign by EOD."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "'Please review' from real person → Action"

    def test_rsvp_stays_action(self, use_case):
        """RSVP → toujours Action (unconditional strong)."""
        email = make_email(
            sender="events@company.com",
            body="You are invited to our team dinner. Please RSVP by Friday.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "RSVP devrait toujours être Action"

    def test_action_required_from_noreply_is_noise(self, use_case):
        """'Action required' from noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@hr.com",
            subject="Action required: Update your benefits",
            body="Please update your benefits selection by end of month."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise", "noreply@ sender devrait toujours être Noise"

    def test_peux_tu_stays_action(self, use_case):
        """'Peux-tu' → toujours Action (unconditional strong, tutoiement = vrai humain)."""
        email = make_email(
            sender="collegue@company.com",
            body="Peux-tu envoyer le rapport avant 17h?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "'Peux-tu' devrait toujours être Action"

    def test_ca_te_dit_stays_action(self, use_case):
        """'Ça te dit' → toujours Action (unconditional strong, très informel)."""
        email = make_email(
            sender="ami@gmail.com",
            body="Ça te dit un ciné ce weekend?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", "'Ça te dit' devrait toujours être Action"


# ============================================================================
# 6. FAST PATH PARITY (classify_by_rules_only)
# ============================================================================


class TestFastPathParity:
    """classify_by_rules_only doit avoir la même logique que _apply_builtin_rules."""

    def test_fast_path_newsletter_is_noise(self):
        """Fast path: newsletter avec unsubscribe → Noise."""
        email = make_email(
            sender="newsletter@startup.com",
            body="Check out our latest update!\n\nUnsubscribe"
        )
        label = get_fast_path_label(email)
        assert label == "Noise", "Fast path: newsletter devrait être Noise"

    def test_fast_path_marketing_question_is_noise(self):
        """Fast path: marketing avec '?' + unsubscribe → Noise."""
        email = make_email(
            sender="info@company.com",
            body="Ready to upgrade? Try premium now.\n\nUnsubscribe | View in browser"
        )
        label = get_fast_path_label(email)
        assert label == "Noise", "Fast path: marketing '?' devrait être Noise"

    def test_fast_path_real_person_tu_veux_is_action(self):
        """Fast path: vrai humain 'tu veux' → Action."""
        email = make_email(
            sender="alice@company.com",
            body="Tu veux qu'on se retrouve à 14h?"
        )
        label = get_fast_path_label(email)
        assert label == "Action", "Fast path: vrai humain 'tu veux' devrait être Action"

    def test_fast_path_invoice_from_noreply_is_noise(self):
        """Fast path: invoice depuis noreply@ → Noise (noreply sender fires before action patterns)."""
        email = make_email(
            sender="noreply@billing.com",
            subject="Invoice #12345",
            body="Payment due: $500"
        )
        label = get_fast_path_label(email)
        assert label == "Noise", "Fast path: noreply@ sender devrait être Noise"

    def test_fast_path_noreply_with_question_is_noise(self):
        """Fast path: noreply@ + question → Noise."""
        email = make_email(
            sender="noreply@service.com",
            body="Satisfied with your purchase?"
        )
        label = get_fast_path_label(email)
        assert label == "Noise", "Fast path: noreply@ '?' devrait être Noise"

    def test_fast_path_please_review_stays_action(self):
        """Fast path: 'please review' + unsubscribe → Action (unconditional)."""
        email = make_email(
            sender="system@company.com",
            body="Please review the contract.\n\nUnsubscribe"
        )
        label = get_fast_path_label(email)
        assert label == "Action", "Fast path: 'please review' devrait être Action"

    def test_fast_path_could_you_please_in_newsletter_is_noise(self):
        """Fast path: 'could you please' dans newsletter → Noise."""
        email = make_email(
            sender="marketing@company.com",
            body="Could you please spare 2 minutes for our survey?\n\nUnsubscribe | Manage preferences"
        )
        label = get_fast_path_label(email)
        assert label == "Noise", "Fast path: 'could you please' dans newsletter devrait être Noise"


# ============================================================================
# 7. _is_likely_newsletter DETECTION
# ============================================================================


class TestNewsletterDetection:
    """Tests directs de la méthode _is_likely_newsletter."""

    def test_sender_keyword_newsletter(self):
        """Sender avec 'newsletter' → newsletter."""
        assert LabelEmailUseCase._is_likely_newsletter("newsletter@company.com", "", "") is True

    def test_sender_keyword_marketing(self):
        """Sender avec 'marketing' → newsletter."""
        assert LabelEmailUseCase._is_likely_newsletter("marketing@company.com", "", "") is True

    def test_unsubscribe_alone_not_newsletter(self):
        """'Unsubscribe' seul ne suffit pas (score 0.3 < 0.4)."""
        assert LabelEmailUseCase._is_likely_newsletter(
            "alice@company.com", "some text\nunsubscribe", ""
        ) is False

    def test_unsubscribe_plus_view_in_browser(self):
        """'Unsubscribe' + 'view in browser' → newsletter (0.3 + 0.3 = 0.6)."""
        assert LabelEmailUseCase._is_likely_newsletter(
            "alice@company.com", "content\nunsubscribe\nview this email in your browser", ""
        ) is True

    def test_real_person_with_footer(self):
        """Vrai humain avec footer 'gérer vos notifications' → PAS newsletter."""
        assert LabelEmailUseCase._is_likely_newsletter(
            "alice@company.com", "contenu\ngérer vos notifications", ""
        ) is False

    def test_newsletter_sender_plus_unsubscribe(self):
        """Sender newsletter + unsubscribe → newsletter (0.5 + 0.3 = 0.8)."""
        assert LabelEmailUseCase._is_likely_newsletter(
            "info@company.com", "content\nunsubscribe", ""
        ) is True

    def test_multiple_ctas(self):
        """2+ marketing CTAs → contribue au score."""
        assert LabelEmailUseCase._is_likely_newsletter(
            "alice@company.com", "Shop now! Buy now! Great deals\nunsubscribe", ""
        ) is True
