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
Tests des améliorations de patterns du système de labellisation v5.

Couvre les améliorations par phase :
- Phase 1 : Security Action Patterns (~12 tests)
- Phase 2 : Noise Sender Patterns (~6 tests)
- Phase 3 : Automated Footer Signals (~5 tests)
- Phase 4 : FYI Weak Patterns (~8 tests)
- Phase 5 : French Conditional Patterns (~6 tests)
- Phase 8 : Reputation Thresholds (~5 tests)
- Conditional Action Patterns (~5 tests)
- Payment Failed Strong Action (~3 tests)

pytest tests/application/test_label_pattern_improvements.py -v
"""

import pytest
from unittest.mock import Mock, patch
from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import (
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
# 1. SECURITY ACTION PATTERNS (Phase 1)
#    Security emails override noise senders — "if this wasn't you",
#    "unusual activity", "account locked", etc.
# ============================================================================


class TestSecurityActionPatterns:
    """Security action patterns override noise senders and fire at step 1b-sec."""

    def test_security_if_wasnt_you_from_noreply(self, use_case):
        """'If this wasn't you' from noreply@ → Noise (automated sender, not actionable)."""
        email = make_email(
            sender="noreply@google.com",
            subject="New sign-in",
            body="New sign-in. If this wasn't you, secure your account"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: noreply@ security alert should be Noise"

    def test_security_unusual_activity_from_alerts(self, use_case):
        """'Unusual activity detected' from alerts@ → Noise (automated sender)."""
        email = make_email(
            sender="alerts@paypal.com",
            subject="Account alert",
            body="Unusual activity detected on your account"
        )
        label = get_builtin_label(use_case, email)
        # alerts@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: alerts@ security notification should be Noise"

    def test_security_account_locked(self, use_case):
        """'Account has been locked' → Action."""
        email = make_email(
            sender="security@service.com",
            subject="Account locked",
            body="Your account has been locked due to suspicious activity"
        )
        label = get_builtin_label(use_case, email)
        # "account locked" matches SECURITY_ACTION_PATTERNS
        assert label == "Action", f"Got {label}: account locked should be Action"

    def test_security_unauthorized_transaction(self, use_case):
        """'Unauthorized transaction' from alerts@ → Noise (automated sender)."""
        email = make_email(
            sender="alerts@bank.com",
            subject="Transaction alert",
            body="An unauthorized transaction of $200 was detected"
        )
        label = get_builtin_label(use_case, email)
        # alerts@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: alerts@ transaction notification should be Noise"

    def test_security_verify_identity(self, use_case):
        """'Please verify your identity' from noreply@ → Noise (automated sender)."""
        email = make_email(
            sender="noreply@bank.com",
            subject="Identity verification",
            body="Please verify your identity to continue"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: noreply@ verify identity should be Noise"

    def test_security_suspicious_login(self, use_case):
        """'Suspicious sign-in attempt' in subject → Action."""
        email = make_email(
            sender="security@company.com",
            subject="Suspicious sign-in attempt",
            body="Someone tried to access your account"
        )
        label = get_builtin_label(use_case, email)
        # "suspicious sign-in" matches SECURITY_ACTION_PATTERNS in subject
        assert label == "Action", f"Got {label}: suspicious login should be Action"

    def test_security_fr_si_ce_netait_pas_vous(self, use_case):
        """FR: 'Si ce n'était pas vous' from noreply@ → Noise (automated sender)."""
        email = make_email(
            sender="noreply@google.com",
            subject="Nouvelle connexion",
            body="Nouvelle connexion détectée. Si ce n'était pas vous, sécurisez votre compte"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: noreply@ FR security should be Noise"

    def test_security_fr_compte_suspendu(self, use_case):
        """FR: 'Compte suspendu' → Action."""
        email = make_email(
            sender="security@service.fr",
            subject="Alerte sécurité",
            body="Votre compte a été suspendu suite à une activité suspecte"
        )
        label = get_builtin_label(use_case, email)
        # "compte suspendu" or "activité suspecte" matches FR SECURITY_ACTION_PATTERNS
        assert label == "Action", f"Got {label}: FR compte suspendu should be Action"

    def test_security_fr_activite_inhabituelle(self, use_case):
        """FR: 'Activité inhabituelle' from alerts@ → Noise (automated sender)."""
        email = make_email(
            sender="alerts@banque.fr",
            subject="Alerte compte",
            body="Activité inhabituelle détectée sur votre compte"
        )
        label = get_builtin_label(use_case, email)
        # alerts@ sender = automated → security patterns skipped → Noise
        assert label == "Noise", f"Got {label}: alerts@ FR security should be Noise"

    def test_security_negative_password_reset_noise(self, use_case):
        """'Password was reset successfully' → Noise (no action needed)."""
        email = make_email(
            sender="noreply@service.com",
            subject="Password reset",
            body="Your password was reset successfully"
        )
        label = get_builtin_label(use_case, email)
        # "password reset" in subject matches NOISE_TEXT_PATTERNS → Noise
        # "reset your password" is SECURITY but "password was reset successfully" is not
        # noreply@ catches at step 2 → Noise
        assert label == "Noise", f"Got {label}: password reset confirmation should be Noise"

    def test_security_negative_login_alert_no_action(self, use_case):
        """'Login alert' without 'if this wasn't you' from noreply@ → Noise."""
        email = make_email(
            sender="noreply@app.com",
            subject="Login alert",
            body="You logged in from Chrome."
        )
        label = get_builtin_label(use_case, email)
        # No SECURITY_ACTION_PATTERNS match (no "if this wasn't you", no "unusual activity")
        # "noreply@" catches at step 2, or "login alert" matches NOISE_TEXT_PATTERNS
        assert label == "Noise", f"Got {label}: plain login alert should be Noise"

    def test_security_verify_transaction_from_bank(self, use_case):
        """'Please verify this transaction' from security@ → Action."""
        email = make_email(
            sender="security@bank.com",
            subject="Transaction review",
            body="Please verify this transaction on your account"
        )
        label = get_builtin_label(use_case, email)
        # "verify this transaction" matches SECURITY_ACTION_PATTERNS → step 1b-sec → Action
        assert label == "Action", f"Got {label}: verify transaction should be Action"


# ============================================================================
# 2. NOISE SENDER PATTERNS (Phase 2)
#    New noise senders: notion.so, figma.com, sentry.io, hubspot.com, etc.
# ============================================================================


class TestNoiseSenderPatterns:
    """New noise sender patterns added in v5."""

    def test_noise_sender_notion(self, use_case):
        """Notion notifications → Noise."""
        email = make_email(
            sender="team@notion.so",
            subject="Page updated",
            body="Someone updated a page in your workspace."
        )
        label = get_builtin_label(use_case, email)
        # "@notion.so" in NOISE_SENDER_PATTERNS → step 2 → Noise
        assert label == "Noise", f"Got {label}: Notion sender should be Noise"

    def test_noise_sender_figma(self, use_case):
        """Figma notifications → Noise."""
        email = make_email(
            sender="updates@figma.com",
            subject="New comment on design",
            body="Someone left a comment on your file."
        )
        label = get_builtin_label(use_case, email)
        # "updates@" or "@figma.com" in NOISE_SENDER_PATTERNS → Noise
        assert label == "Noise", f"Got {label}: Figma sender should be Noise"

    def test_noise_sender_sentry(self, use_case):
        """Sentry error notifications → Noise."""
        email = make_email(
            sender="noreply@sentry.io",
            subject="New error: TypeError in production",
            body="A new error was detected in your project."
        )
        label = get_builtin_label(use_case, email)
        # "noreply@" or "@sentry.io" in NOISE_SENDER_PATTERNS → Noise
        assert label == "Noise", f"Got {label}: Sentry sender should be Noise"

    def test_noise_sender_hubspot(self, use_case):
        """HubSpot marketing → Noise."""
        email = make_email(
            sender="marketing@hubspot.com",
            subject="New leads this week",
            body="You have 5 new leads to review."
        )
        label = get_builtin_label(use_case, email)
        # "marketing@" or "@hubspot.com" in NOISE_SENDER_PATTERNS → Noise
        assert label == "Noise", f"Got {label}: HubSpot sender should be Noise"

    def test_noise_sender_receipts(self, use_case):
        """receipts@ → Noise."""
        email = make_email(
            sender="receipts@company.com",
            subject="Your receipt",
            body="Thank you for your purchase. Here is your receipt."
        )
        label = get_builtin_label(use_case, email)
        # "receipts@" in NOISE_SENDER_PATTERNS → Noise
        assert label == "Noise", f"Got {label}: receipts@ sender should be Noise"

    def test_noise_sender_billing_generic(self, use_case):
        """billing@ → Noise (when no strong action pattern)."""
        email = make_email(
            sender="billing@saas.com",
            subject="Monthly statement",
            body="Your monthly statement is ready."
        )
        label = get_builtin_label(use_case, email)
        # "billing@" in NOISE_SENDER_PATTERNS → step 2 → Noise
        # No strong action patterns to override
        assert label == "Noise", f"Got {label}: billing@ generic should be Noise"


# ============================================================================
# 3. AUTOMATED FOOTER SIGNALS (Phase 3)
#    New footer patterns: "You are receiving this", "Sent via", "Powered by",
#    "Update your email preferences", "Forward to a friend".
# ============================================================================


class TestAutomatedFooterSignals:
    """New automated footer signal patterns in AUTOMATED_SIGNALS_RE."""

    def test_footer_you_are_receiving(self, use_case):
        """'You are receiving this because...' → automated signal → newsletter detection."""
        email = make_email(
            sender="info@company.com",
            subject="Weekly roundup",
            body="Some content here. You are receiving this because you signed up."
        )
        label = get_builtin_label(use_case, email)
        # "You are receiving this" is in AUTOMATED_SIGNALS_RE
        # "info@" matches NEWSLETTER_SENDER_RE → newsletter score >= 0.4
        # Newsletter early exit → Noise
        assert label == "Noise", f"Got {label}: 'You are receiving this' footer should trigger newsletter → Noise"

    def test_footer_sent_via(self, use_case):
        """'Sent via Mailchimp' → automated signal detected."""
        email = make_email(
            sender="news@company.com",
            subject="Article update",
            body="Article content here. Sent via Mailchimp."
        )
        label = get_builtin_label(use_case, email)
        # "Sent via" in AUTOMATED_SIGNALS_RE + "news@" in NOISE_SENDER_PATTERNS
        assert label == "Noise", f"Got {label}: 'Sent via' footer should be Noise"

    def test_footer_powered_by(self, use_case):
        """'Powered by SendGrid' → automated signal detected."""
        email = make_email(
            sender="newsletter@company.com",
            subject="Monthly digest",
            body="Content. Powered by SendGrid."
        )
        label = get_builtin_label(use_case, email)
        # "Powered by" in AUTOMATED_SIGNALS_RE + "newsletter@" in NOISE_SENDER_PATTERNS
        assert label == "Noise", f"Got {label}: 'Powered by' footer should be Noise"

    def test_footer_update_preferences(self, use_case):
        """'Update your email preferences' → automated signal detected."""
        email = make_email(
            sender="digest@company.com",
            subject="News update",
            body="News content. Update your email preferences here."
        )
        label = get_builtin_label(use_case, email)
        # "Update your email preferences" in AUTOMATED_SIGNALS_RE + "digest@" in NOISE_SENDER_PATTERNS
        assert label == "Noise", f"Got {label}: 'Update preferences' footer should be Noise"

    def test_footer_forward_to_friend(self, use_case):
        """'Forward to a friend' → automated signal detected."""
        email = make_email(
            sender="promo@store.com",
            subject="Great deal",
            body="Great deal! Forward to a friend."
        )
        label = get_builtin_label(use_case, email)
        # "Forward to a friend" in AUTOMATED_SIGNALS_RE
        # is_automated=True, but also check sender or newsletter detection
        # No noise sender pattern for "promo@" directly, but "forward to a friend" signals automated
        # is_newsletter check: sender has no newsletter keyword, but body has automated signal (0.3)
        # Need 0.4+ for newsletter → might not reach newsletter threshold alone
        # But is_automated=True → weak action gets killed
        # Actually no strong/weak patterns match here → falls to LLM? Or noise text?
        # "deal" in subject matches NOISE_SUBJECT_ONLY → Noise
        assert label == "Noise", f"Got {label}: 'Forward to a friend' should contribute to Noise"


# ============================================================================
# 4. FYI WEAK PATTERNS (Phase 4)
#    New FYI weak patterns: "out of office", "on vacation", "got it",
#    "noted", "see attached", FR equivalents.
# ============================================================================


class TestFYIWeakPatterns:
    """FYI weak patterns for acknowledgments, OOO, and simple confirmations."""

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_fyi_out_of_office(self, mock_rep, use_case):
        """'Out of office' → FYI (weak FYI pattern, not automated)."""
        mock_rep.return_value.get_sender_reputation.return_value = None
        mock_rep.return_value.get_domain_reputation.return_value = None
        email = make_email(
            sender="colleague@company.com",
            subject="Out of office",
            body="I'm out of office until Monday"
        )
        label = get_builtin_label(use_case, email)
        # "out of office" matches FYI_WEAK_PATTERNS → step 8 (if not automated) → FYI
        assert label == "FYI", f"Got {label}: out of office should be FYI"

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_fyi_on_vacation(self, mock_rep, use_case):
        """'On vacation' → FYI."""
        mock_rep.return_value.get_sender_reputation.return_value = None
        mock_rep.return_value.get_domain_reputation.return_value = None
        email = make_email(
            sender="colleague@company.com",
            subject="Vacation",
            body="I'm on vacation this week"
        )
        label = get_builtin_label(use_case, email)
        # "on vacation" matches FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: on vacation should be FYI"

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_fyi_got_it(self, mock_rep, use_case):
        """'Got it' → FYI (acknowledgment)."""
        mock_rep.return_value.get_sender_reputation.return_value = None
        mock_rep.return_value.get_domain_reputation.return_value = None
        email = make_email(
            sender="colleague@company.com",
            subject="Re: Meeting",
            body="Got it, thanks for the update"
        )
        label = get_builtin_label(use_case, email)
        # "got it" matches FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: 'got it' should be FYI"

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_fyi_noted(self, mock_rep, use_case):
        """'Noted' → FYI (acknowledgment)."""
        mock_rep.return_value.get_sender_reputation.return_value = None
        mock_rep.return_value.get_domain_reputation.return_value = None
        email = make_email(
            sender="colleague@company.com",
            subject="Re: Action item",
            body="Noted. Will proceed as discussed."
        )
        label = get_builtin_label(use_case, email)
        # "noted" matches FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: 'noted' should be FYI"

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_fyi_see_attached(self, mock_rep, use_case):
        """'See attached' → FYI."""
        mock_rep.return_value.get_sender_reputation.return_value = None
        mock_rep.return_value.get_domain_reputation.return_value = None
        email = make_email(
            sender="colleague@company.com",
            subject="Report",
            body="See attached the latest report"
        )
        label = get_builtin_label(use_case, email)
        # "see attached" matches FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: 'see attached' should be FYI"

    def test_fyi_fr_en_vacances(self, use_case):
        """FR: 'En vacances' → FYI."""
        email = make_email(
            sender="collegue@company.com",
            subject="Absence",
            body="Je suis en vacances jusqu'à lundi"
        )
        label = get_builtin_label(use_case, email)
        # "en vacances" matches FR FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: FR 'en vacances' should be FYI"

    def test_fyi_fr_bien_recu(self, use_case):
        """FR: 'Bien reçu' → FYI."""
        email = make_email(
            sender="collegue@company.com",
            subject="Re: Document",
            body="Bien reçu, merci pour l'info"
        )
        label = get_builtin_label(use_case, email)
        # "bien reçu" matches FR FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: FR 'bien reçu' should be FYI"

    def test_fyi_fr_ci_joint(self, use_case):
        """FR: 'Ci-joint' → FYI."""
        email = make_email(
            sender="collegue@company.com",
            subject="Document",
            body="Ci-joint le document demandé"
        )
        label = get_builtin_label(use_case, email)
        # "ci-joint" matches FR FYI_WEAK_PATTERNS → FYI
        assert label == "FYI", f"Got {label}: FR 'ci-joint' should be FYI"


# ============================================================================
# 5. FRENCH CONDITIONAL PATTERNS (Phase 5)
#    FR patterns that are conditional: only trigger Action if NOT
#    automated/newsletter (vouvoiement/tutoiement can be marketing).
# ============================================================================


class TestFrenchConditionalPatterns:
    """French conditional action patterns — only for real people, not newsletters."""

    def test_fr_on_valide(self, use_case):
        """FR: 'On valide le budget ?' from colleague → Action."""
        email = make_email(
            sender="collegue@company.com",
            subject="Budget Q2",
            body="On valide le budget ?"
        )
        label = get_builtin_label(use_case, email)
        # "on valide" matches ACTION_STRONG_CONDITIONAL_PATTERNS
        # Not automated/newsletter → Action
        assert label == "Action", f"Got {label}: FR 'on valide' from real person should be Action"

    def test_fr_tu_valides(self, use_case):
        """FR: 'Tu valides cette approche ?' → Action."""
        email = make_email(
            sender="collegue@company.com",
            subject="Approche technique",
            body="Tu valides cette approche ?"
        )
        label = get_builtin_label(use_case, email)
        # "tu valides" matches ACTION_STRONG_CONDITIONAL_PATTERNS → Action
        assert label == "Action", f"Got {label}: FR 'tu valides' should be Action"

    def test_fr_ca_te_va(self, use_case):
        """FR: 'Ça te va si on fait comme ça ?' → Action."""
        email = make_email(
            sender="collegue@company.com",
            subject="Organisation",
            body="Ça te va si on fait comme ça ?"
        )
        label = get_builtin_label(use_case, email)
        # "ça te va" matches ACTION_STRONG_CONDITIONAL_PATTERNS → Action
        assert label == "Action", f"Got {label}: FR 'ça te va' should be Action"

    def test_fr_ca_vous_convient(self, use_case):
        """FR: 'Ça vous convient ?' → Action."""
        email = make_email(
            sender="client@company.com",
            subject="Proposition",
            body="Ça vous convient ?"
        )
        label = get_builtin_label(use_case, email)
        # "ça vous convient" matches ACTION_STRONG_CONDITIONAL_PATTERNS → Action
        assert label == "Action", f"Got {label}: FR 'ça vous convient' should be Action"

    def test_fr_verifie_ca(self, use_case):
        """FR: 'Vérifie ça quand tu as le temps' → Action."""
        email = make_email(
            sender="collegue@company.com",
            subject="Vérification",
            body="Vérifie ça quand tu as le temps"
        )
        label = get_builtin_label(use_case, email)
        # "vérifie ça" matches ACTION_STRONG_CONDITIONAL_PATTERNS → Action
        assert label == "Action", f"Got {label}: FR 'vérifie ça' should be Action"

    def test_fr_on_valide_from_newsletter(self, use_case):
        """FR: 'On valide' from newsletter → Noise (automated → conditional patterns skipped)."""
        email = make_email(
            sender="newsletter@marketing.com",
            subject="Offre spéciale",
            body="On valide l'offre? Unsubscribe here"
        )
        label = get_builtin_label(use_case, email)
        # "newsletter@" in NOISE_SENDER_PATTERNS → step 2 → Noise
        # Even if "on valide" is conditional action, noise sender fires first at step 2
        # (conditional is step 1b-cond, but newsletter@ is NOISE_SENDER at step 2
        #  and conditional is skipped when is_newsletter=True)
        assert label == "Noise", f"Got {label}: FR conditional from newsletter should be Noise"


# ============================================================================
# 6. REPUTATION THRESHOLDS (Phase 8)
#    Sender: 2+ emails, 80%+ confidence
#    Domain: 3+ emails, 85%+ confidence
# ============================================================================


class TestReputationThresholds:
    """Reputation-based classification with correct thresholds."""

    def test_reputation_sender_2_emails_triggers(self, use_case):
        """Sender with 2 emails and 80% confidence → uses reputation."""
        email = make_email(
            sender="vendor@specific-vendor.com",
            subject="Update",
            body="Here is the latest update."
        )
        mock_rep_store = Mock()
        mock_rep_store.get_sender_reputation.return_value = {
            "dominant_label": "Noise",
            "confidence": 0.80,
            "count": 2,
        }
        mock_rep_store.get_domain_reputation.return_value = None

        with patch(
            "app.infrastructure.sender_reputation_store.get_reputation_store",
            return_value=mock_rep_store,
        ):
            label = get_builtin_label(use_case, email)
        # 2 emails, 80% confidence → meets threshold (2+, 80%+) → uses reputation
        assert label == "Noise", f"Got {label}: sender with 2 emails @ 80% should use reputation"

    def test_reputation_sender_1_email_skipped(self, use_case):
        """Sender with 1 email → skipped (below minimum of 2)."""
        email = make_email(
            sender="new-sender@company.com",
            subject="Hello",
            body="Just checking in."
        )
        mock_rep_store = Mock()
        # get_sender_reputation returns None when count < 2
        mock_rep_store.get_sender_reputation.return_value = None
        mock_rep_store.get_domain_reputation.return_value = None

        with patch(
            "app.infrastructure.sender_reputation_store.get_reputation_store",
            return_value=mock_rep_store,
        ):
            label = get_builtin_label(use_case, email)
        # 1 email → below threshold → reputation skipped → falls to other rules or LLM
        assert label is None, f"Got {label}: sender with 1 email should not use reputation"

    def test_reputation_domain_3_emails_triggers(self, use_case):
        """Domain with 3 emails and 85% confidence → uses reputation."""
        email = make_email(
            sender="someone@vendor-domain.com",
            subject="Monthly report",
            body="Report attached."
        )
        mock_rep_store = Mock()
        mock_rep_store.get_sender_reputation.return_value = None
        mock_rep_store.get_domain_reputation.return_value = {
            "dominant_label": "FYI",
            "confidence": 0.85,
            "count": 3,
        }

        with patch(
            "app.infrastructure.sender_reputation_store.get_reputation_store",
            return_value=mock_rep_store,
        ):
            label = get_builtin_label(use_case, email)
        # 3 emails, 85% confidence → meets threshold (3+, 85%+) → uses domain reputation
        assert label == "FYI", f"Got {label}: domain with 3 emails @ 85% should use reputation"

    def test_reputation_domain_2_emails_skipped(self, use_case):
        """Domain with 2 emails → skipped (below minimum of 3)."""
        email = make_email(
            sender="someone@new-domain.com",
            subject="Info",
            body="General information."
        )
        mock_rep_store = Mock()
        mock_rep_store.get_sender_reputation.return_value = None
        # get_domain_reputation returns None when count < 3
        mock_rep_store.get_domain_reputation.return_value = None

        with patch(
            "app.infrastructure.sender_reputation_store.get_reputation_store",
            return_value=mock_rep_store,
        ):
            label = get_builtin_label(use_case, email)
        # 2 emails → below threshold → reputation skipped
        assert label is None, f"Got {label}: domain with 2 emails should not use reputation"

    def test_reputation_domain_79_pct_skipped(self, use_case):
        """Domain with 3 emails but 79% confidence → skipped (below 85% threshold)."""
        email = make_email(
            sender="someone@mixed-domain.com",
            subject="Question",
            body="Various topic."
        )
        mock_rep_store = Mock()
        mock_rep_store.get_sender_reputation.return_value = None
        mock_rep_store.get_domain_reputation.return_value = {
            "dominant_label": "Action",
            "confidence": 0.79,
            "count": 3,
        }

        with patch(
            "app.infrastructure.sender_reputation_store.get_reputation_store",
            return_value=mock_rep_store,
        ):
            label = get_builtin_label(use_case, email)
        # 3 emails but 79% < 85% → below confidence threshold → skipped
        assert label is None, f"Got {label}: domain with 79% confidence should not use reputation"


# ============================================================================
# 7. CONDITIONAL ACTION PATTERNS
#    Marketing emails don't trigger conditional patterns like "would you like",
#    "do you want", "shall we" — but real people do.
# ============================================================================


class TestConditionalActionPatterns:
    """Conditional action patterns skipped for automated/newsletter, active for real people."""

    def test_conditional_would_you_like_real_person(self, use_case):
        """'Would you like to grab lunch?' from friend → Action."""
        email = make_email(
            sender="friend@gmail.com",
            subject="Lunch",
            body="Would you like to grab lunch?"
        )
        label = get_builtin_label(use_case, email)
        # "would you like" matches ACTION_STRONG_CONDITIONAL_PATTERNS
        # Not automated/newsletter → Action
        assert label == "Action", f"Got {label}: 'would you like' from real person should be Action"

    def test_conditional_would_you_like_newsletter(self, use_case):
        """'Would you like our new product?' from newsletter → Noise."""
        email = make_email(
            sender="newsletter@shop.com",
            subject="New arrivals",
            body="Would you like our new product? Unsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # "newsletter@" in NOISE_SENDER_PATTERNS → step 2 → Noise
        # (even conditional action step 1b-cond would be skipped due to is_newsletter)
        assert label == "Noise", f"Got {label}: 'would you like' from newsletter should be Noise"

    def test_conditional_do_you_want_marketing(self, use_case):
        """'Do you want 50% off?' from promo sender → Noise."""
        email = make_email(
            sender="promo@store.com",
            subject="Special offer",
            body="Do you want 50% off? Shop now! Unsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # "do you want" is conditional but sender is marketing + "Unsubscribe" = automated
        # is_newsletter=True (automated signals + check) → conditional skipped
        # Step 2: no direct noise sender match for "promo@"
        # Step 2-auto: newsletter → Noise
        # Or NOISE_TEXT "special offer" / NOISE_SUBJECT_ONLY "deal" / etc.
        assert label == "Noise", f"Got {label}: 'do you want' from marketing should be Noise"

    def test_conditional_shall_we_colleague(self, use_case):
        """'Shall we schedule the meeting?' from colleague → Action."""
        email = make_email(
            sender="colleague@company.com",
            subject="Meeting",
            body="Shall we schedule the meeting for Thursday?"
        )
        label = get_builtin_label(use_case, email)
        # "shall we" matches ACTION_STRONG_CONDITIONAL_PATTERNS
        # Not automated/newsletter → Action
        assert label == "Action", f"Got {label}: 'shall we' from colleague should be Action"

    def test_conditional_tu_veux_marketing(self, use_case):
        """FR: 'Tu veux découvrir nos nouveautés?' from newsletter → Noise."""
        email = make_email(
            sender="newsletter@boutique.fr",
            subject="Nouveautés",
            body="Tu veux découvrir nos nouveautés? Se désabonner"
        )
        label = get_builtin_label(use_case, email)
        # "newsletter@" in NOISE_SENDER_PATTERNS → step 2 → Noise
        assert label == "Noise", f"Got {label}: FR 'tu veux' from newsletter should be Noise"


# ============================================================================
# 8. PAYMENT FAILED STRONG ACTION
#    "payment failed", "card declined" — strong action overrides noise senders.
# ============================================================================


class TestPaymentFailedStrongAction:
    """Payment failure patterns — strong action from real senders, Noise from noreply senders."""

    def test_payment_failed_from_billing_is_noise(self, use_case):
        """'Payment failed' from billing@ → Noise (automated sender overrides action)."""
        email = make_email(
            sender="billing@saas.com",
            subject="Payment failed",
            body="Your payment could not be processed. Please update your payment method."
        )
        label = get_builtin_label(use_case, email)
        # "billing@" noise sender → Noise before any action pattern
        assert label == "Noise", f"Got {label}: billing@ is automated → Noise"

    def test_payment_failed_from_real_sender(self, use_case):
        """'Payment failed' from real sender → Action."""
        email = make_email(
            sender="support@saas.com",
            subject="Payment failed",
            body="Your payment could not be processed. Please update your payment method."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: payment failed from real sender → Action"

    def test_card_declined_from_noreply(self, use_case):
        """'Card declined' from noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@service.com",
            subject="Card declined",
            body="Your credit card was declined"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ is caught at step 1b-noreply → always Noise, even with "card declined"
        assert label == "Noise", f"Got {label}: noreply@ sender should be Noise"

    def test_payment_failed_not_payment_received(self, use_case):
        """'Payment received' → Noise (not a failure, just a confirmation)."""
        email = make_email(
            sender="billing@company.com",
            subject="Payment received",
            body="Your payment was received"
        )
        label = get_builtin_label(use_case, email)
        # "payment received" matches NOISE_TEXT_PATTERNS → Noise
        # Also "billing@" in NOISE_SENDER_PATTERNS
        # No strong action patterns match ("payment failed" ≠ "payment received")
        assert label == "Noise", f"Got {label}: payment received should be Noise, not Action"


# ============================================================================
# DEMANDE D'INFORMATION — French inquiry subject patterns
# ============================================================================


class TestDemandeInformationPattern:
    """'Demande d'information' et variantes → Action (ACTION_STRONG_PATTERNS)."""

    def test_demande_information_subject(self, use_case):
        """Sujet 'Demande d'information' d'un inconnu → Action."""
        email = make_email(
            sender="alexandre.simon@example.com",
            subject="Demande d'information",
            body="Bonjour, je souhaite obtenir des informations sur vos services.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: 'Demande d'information' doit être Action"

    def test_demande_dinformation_apostrophe_typographique(self, use_case):
        """Apostrophe typographique (’) → Action."""
        email = make_email(
            sender="contact@prospect.com",
            subject="Demande d’information",
            body="Bonjour, pouvez-vous me renseigner?",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: apostrophe typographique doit être acceptée"

    def test_demande_de_devis(self, use_case):
        """'Demande de devis' → Action."""
        email = make_email(
            sender="client@prospect.fr",
            subject="Demande de devis",
            body="Bonjour, je souhaite obtenir un devis pour votre solution.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: 'Demande de devis' doit être Action"

    def test_demande_de_rappel(self, use_case):
        """'Demande de rappel' → Action."""
        email = make_email(
            sender="lead@startup.io",
            subject="Demande de rappel",
            body="Merci de me rappeler au 06 12 34 56 78.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: 'Demande de rappel' doit être Action"

    def test_demande_de_rendez_vous(self, use_case):
        """'Demande de rendez-vous' → Action."""
        email = make_email(
            sender="prospect@corp.com",
            subject="Demande de rendez-vous",
            body="Je souhaite fixer un rendez-vous pour discuter de votre offre.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: 'Demande de rendez-vous' doit être Action"

    def test_demande_information_case_insensitive(self, use_case):
        """Casse insensible → Action."""
        email = make_email(
            sender="user@example.com",
            subject="DEMANDE D'INFORMATION",
            body="Bonjour.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: casse insensible doit fonctionner"

    def test_re_demande_information(self, use_case):
        """'Re: Demande d'information' (thread reply) → Action."""
        email = make_email(
            sender="client@example.com",
            subject="Re: Demande d'information",
            body="Suite à ma demande initiale, voici mes questions.",
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: réponse à une demande d'info doit être Action"


# ============================================================================
# REAL CONTACT FLOOR — contacts réels ne doivent jamais être Noise
# ============================================================================


def _make_email_entity(sender, subject, body="Bonjour.", received_days_ago=1):
    """Crée un Email domain entity pour les tests execute()."""
    from datetime import datetime, timedelta, timezone
    from app.domain.entities import Email
    return Email(
        id=f"test-{abs(hash((sender, subject))) % 1_000_000}",
        sender=sender,
        subject=subject,
        body=body,
        received_at=datetime.now(timezone.utc) - timedelta(days=received_days_ago),
    )


def _raw_meta(is_real_contact: bool) -> dict:
    return {"classification_headers": {}, "sender_is_real_contact": is_real_contact}


class TestRealContactFloor:
    """Contacts réels (échanges bidirectionnels) ne doivent jamais être Noise."""

    def test_real_contact_demande_information_is_action(self, use_case):
        """Contact réel avec 'Demande d'information' → Action (pattern fort)."""
        email = _make_email_entity("alexandre@example.com", "Demande d'information")
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=True))
        assert result.default_label != "Noise", (
            f"Got {result.default_label}: contact réel ne doit jamais être Noise"
        )

    def test_real_contact_generic_subject_not_noise(self, use_case):
        """Contact réel avec sujet neutre → FYI ou Action, jamais Noise."""
        email = _make_email_entity("ami@gmail.com", "Salut", "Comment ça va ?")
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=True))
        assert result.default_label != "Noise", (
            f"Got {result.default_label}: contact réel sujet neutre ne doit pas être Noise"
        )

    def test_real_contact_noise_body_pattern_not_noise(self, use_case):
        """Contact réel dont le corps contient 'receipt' → pas Noise (corps = pièce jointe ou citation)."""
        email = _make_email_entity(
            "partenaire@business.com",
            "Re: notre réunion",
            "Voici le receipt pour notre dîner d'affaires.",
        )
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=True))
        assert result.default_label != "Noise", (
            f"Got {result.default_label}: contact réel avec 'receipt' en corps ne doit pas être Noise"
        )

    def test_real_contact_with_noise_domain_not_noise(self, use_case):
        """Contact réel dont le domaine est dans NOISE_DOMAIN_SUFFIXES → pas Noise."""
        # bell.ca est dans NOISE_SENDER_DOMAINS ; si c'est un vrai contact, on ignore le domaine
        email = _make_email_entity("john.doe@bell.ca", "Question rapide", "Peux-tu me rappeler ?")
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=True))
        assert result.default_label != "Noise", (
            f"Got {result.default_label}: contact réel sur domaine bruit ne doit pas être Noise"
        )

    def test_unknown_contact_noise_domain_stays_noise(self, use_case):
        """Inconnu dont le domaine est noise-domain → reste Noise (comportement normal)."""
        email = _make_email_entity("promo@bell.ca", "Offre spéciale abonnement", "Profitez de notre offre.")
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=False))
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: inconnu sur domaine bruit doit rester Noise"
        )

    def test_real_contact_calendar_rsvp_stays_noise(self, use_case):
        """Contact réel qui accepte une invitation calendrier → Noise (calendar hard-noise, pas de réponse utile)."""
        email = _make_email_entity(
            "collegue@company.com",
            "Accepted: Réunion équipe lundi",
            "Je participerai.",
        )
        result = use_case.execute(email, raw_metadata=_raw_meta(is_real_contact=True))
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: RSVP accepté d'un contact réel doit rester Noise"
        )


# ============================================================================
# STRONG BULK SIGNAL — override du contact floor pour les plateformes
# ============================================================================


class TestStrongBulkSignalOverride:
    """Un "real contact" bidirectionnel est protégé par défaut, mais un signal
    bulk fort (mass-mail prefix OU 2+ signaux newsletter) fait sauter la
    protection — c'est ce qui catch Notion/Miro/Uber/Daily Degen même si
    l'user a déjà échangé avec le domaine."""

    def _raw_meta_with_lu(self, is_real_contact: bool, headers: dict | None = None) -> dict:
        return {
            "classification_headers": {"list-unsubscribe": "<https://unsub.example/x>"} | (headers or {}),
            "sender_is_real_contact": is_real_contact,
        }

    def test_mass_mail_prefix_beats_contact_floor(self, use_case):
        """Signal A : sender avec prefix 'team@' → bypass contact floor, RFC check fire → Noise."""
        email = _make_email_entity(
            "team@notion.com",
            "Get a first look at our developer tools",
            "Bonjour, nouvelles features. Unsubscribe here.",
        )
        result = use_case.execute(email, raw_metadata=self._raw_meta_with_lu(is_real_contact=True))
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: team@ + List-Unsubscribe doit déclencher Noise malgré real_contact"
        )

    def test_news_prefix_beats_contact_floor(self, use_case):
        """Signal A bis : news@ est aussi un mass-mail prefix."""
        email = _make_email_entity(
            "news@thedailydegen.com",
            "The Daily Degen — April 23rd, 2026",
            "Daily market brief. Click to read. Unsubscribe.",
        )
        result = use_case.execute(email, raw_metadata=self._raw_meta_with_lu(is_real_contact=True))
        assert result.default_label == "Noise"

    def test_combined_signals_beat_contact_floor(self, use_case):
        """Signal B : List-Unsubscribe + 2+ CTAs marketing → score >= 0.7, bypass."""
        email = _make_email_entity(
            "jane@company.io",  # pas de mass-mail prefix
            "Votre repas gratuit vous attend",
            "Profitez-en ! Rendez-vous sur votre app. Découvrez l'offre !",
        )
        result = use_case.execute(email, raw_metadata=self._raw_meta_with_lu(is_real_contact=True))
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: List-Unsubscribe + 2 CTAs doit dépasser le seuil de bypass"
        )

    def test_single_list_unsubscribe_does_not_beat_contact_floor(self, use_case):
        """Garde-fou : List-Unsubscribe SEUL (score 0.4) sur un domaine NEUTRE
        (pas dans NOISE_SENDER_PATTERNS) ne doit PAS bypasser le contact floor.
        Ça protège l'ami qui t'écrit depuis un MTA custom qui injecte
        List-Unsubscribe. Les plateformes déclarées noise (Substack, Mailchimp)
        elles restent catchées — mitigation via VIP."""
        email = _make_email_entity(
            "jane.doe@example.com",  # neutral domain, not in any noise list
            "My weekly thoughts",
            "Salut, voici mes réflexions de la semaine.",
        )
        result = use_case.execute(email, raw_metadata=self._raw_meta_with_lu(is_real_contact=True))
        assert result.default_label != "Noise", (
            f"Got {result.default_label}: List-Unsubscribe seul sur domaine neutre ne doit pas briser le contact floor"
        )

    def test_unknown_sender_with_list_unsubscribe_is_noise(self, use_case):
        """Sanity : un inconnu avec List-Unsubscribe → Noise (comportement initial)."""
        email = _make_email_entity(
            "hello@startup.io",
            "Check out our product",
            "We built something new.",
        )
        result = use_case.execute(email, raw_metadata=self._raw_meta_with_lu(is_real_contact=False))
        assert result.default_label == "Noise"


# ============================================================================
# SHORT-BODY GENUINE QUESTION — scorer doit catch "Est-ce que je peux X ?"
# même en ligne 2/3 (pas seulement dans les 60% du début)
# ============================================================================


class TestShortBodyQuestionDetection:
    """Une vraie question formulée depuis le sender (`Est-ce que je peux X ?`)
    dans un email court de 2-3 phrases doit être Action, même si le `?` tombe
    en ligne 2/3 (position_ratio > 0.60). Le filtre de position n'est conçu
    que pour les emails marketing longs avec CTAs en footer."""

    def test_short_email_question_in_second_line_is_action(self, use_case):
        """Cas concret de l'user : email de 3 phrases avec question en ligne 2."""
        email = _make_email_entity(
            "alexandre.simon@hotmail.com",
            "Achat maison vis caché",
            """Bonjour Alexandre,

J'ai acheté une maison il y a 6 mois et j'ai trouvé un problème majeur dans la fondation. Est-ce que je peux faire une réclamation pour ma maison?

Merci,""",
        )
        result = use_case.execute(
            email,
            raw_metadata={"classification_headers": {}, "sender_is_real_contact": True},
        )
        assert result.default_label == "Action", (
            f"Got {result.default_label}: question réelle dans email court doit être Action"
        )

    def test_short_email_puis_je_question_is_action(self, use_case):
        """Variante FR : 'Puis-je' devrait aussi déclencher genuine question."""
        email = _make_email_entity(
            "contact@entreprise.fr",
            "Demande d'information",
            """Bonjour,

Votre produit m'intéresse. Comment puis-je l'obtenir?

Cordialement,""",
        )
        result = use_case.execute(
            email,
            raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Action", (
            f"Got {result.default_label}: question formelle dans email court doit être Action"
        )

    def test_brevo_verify_device_is_action(self, use_case):
        """Cas concret : email Brevo 'Verify your new device' DOIT être Action
        même si `@t.brevo.com` est dans NOISE_SENDER_PATTERNS."""
        email = _make_email_entity(
            "account-alerts@t.brevo.com",
            "Verify your new device",
            "We couldn't recognize this new device, please verify it using the 6-digit verification code.",
        )
        result = use_case.execute(
            email, raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Action", (
            f"Got {result.default_label}: email 2FA de sender noise doit rester Action"
        )

    def test_otp_from_noreply_is_action(self, use_case):
        """Google 2FA via noreply : le code de connexion doit rester Action."""
        email = _make_email_entity(
            "noreply@accounts.google.com",
            "Your verification code is 123456",
            "Use this code to complete your sign-in.",
        )
        result = use_case.execute(
            email, raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Action"

    def test_password_reset_from_noreply_is_action(self, use_case):
        """Password reset: Action même si le sender est noreply."""
        email = _make_email_entity(
            "no-reply@app.example.com",
            "Reset your password",
            "Click the link below to reset your password.",
        )
        result = use_case.execute(
            email, raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Action"

    def test_fr_code_verification_is_action(self, use_case):
        """Code de vérification FR depuis domaine marketing → Action."""
        email = _make_email_entity(
            "notifications@mail.example.com",
            "Code de vérification : 456789",
            "Votre code pour accéder à votre compte est 456789.",
        )
        result = use_case.execute(
            email, raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Action"

    def test_brevo_marketing_campaign_stays_noise(self, use_case):
        """Garde-fou : email marketing Brevo (sans mots de verification) reste Noise."""
        email = _make_email_entity(
            "campaigns@m.brevo.com",
            "Alexandre, ready to grow your business?",
            "Check out our latest campaign features and boost your conversions today!",
        )
        result = use_case.execute(
            email, raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: marketing Brevo sans keyword 2FA doit rester Noise"
        )

    def test_long_marketing_email_keeps_position_filter(self, use_case):
        """Garde-fou : un email marketing long garde le filtre position à 60%.
        Un CTA en fin de body (ligne 15+) ne doit PAS devenir Action."""
        # Body simulant une newsletter marketing longue (8+ lignes)
        marketing_body = """Dear customer,

We have amazing news for you this week!

Our new product line is now available.
Check out our bestsellers below.
Free shipping on orders over $50.
Limited-time 20% discount with code WELCOME20.
Follow us on social media for more deals.
Don't miss our weekly newsletter.
Browse our catalog at example.com/shop.

Ready to upgrade your experience?

Click below to learn more."""
        email = _make_email_entity(
            "newsletter@shop.com",  # newsletter@ is in MASS_MAIL_PREFIXES → Noise anyway
            "Weekly deals just for you",
            marketing_body,
        )
        result = use_case.execute(
            email,
            raw_metadata={"classification_headers": {}, "sender_is_real_contact": False},
        )
        assert result.default_label == "Noise", (
            f"Got {result.default_label}: marketing long avec CTA rhétorique doit rester Noise"
        )
