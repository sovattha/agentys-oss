"""
Tests profonds d'angles morts du système d'auto-labelling (Round 2).

Couvre les edge cases NON couverts par test_label_blind_spots.py:
- Questions about noise topics (receipt, shipping, etc.) killed by noise patterns
- None/empty field handling (crash potential)
- Body truncation at 2000 chars
- Invoice negative lookahead edge cases
- Password reset / login alert / security alert requiring action
- Delivery failed vs tracking notification
- Weak action from real person with unsubscribe footer
- Unicode edge cases (ellipsis, accented chars)
- Real-world email types: GitHub PRs, calendar invites, contracts, SaaS billing
- Cross-field conflicts (subject action vs body noise)
- classify_by_rules_only fast path parity

pytest tests/application/test_label_deep_blind_spots.py -v
"""

import pytest
from unittest.mock import Mock
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
# 1. QUESTIONS ABOUT NOISE TOPICS
#    Bug: noise text patterns (step 3) fire BEFORE the ? check (step 4b),
#    so questions about receipts/shipping/etc. are classified as Noise.
# ============================================================================


class TestQuestionsAboutNoiseTopics:
    """Questions containing noise keywords should be Action, not Noise."""

    def test_question_about_receipt_with_noise_subject(self, use_case):
        """FIXED: 'Missing receipt' + body ? → ? guard skips all noise text → Action."""
        email = make_email(
            subject="Missing receipt",
            body="I didn't receive the receipt. Can you resend it?"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → ALL noise text patterns skipped → step 4b → Action
        assert label == "Action"

    def test_question_about_receipt_neutral_subject(self, use_case):
        """Question about receipt with neutral subject → Action (? overrides noise text)."""
        email = make_email(
            subject="Quick question",
            body="I didn't receive the receipt. Can you resend it?"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → noise text skipped → step 4b → Action
        assert label == "Action"

    def test_question_about_shipping_is_action(self, use_case):
        """'Any update on shipping?' has 'shipping' → Noise at step 3."""
        email = make_email(
            subject="Order update",
            body="Can you check the shipping status for order #456?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: question about shipping should be Action"

    def test_question_about_password_reset_is_action(self, use_case):
        """'Did you get the password reset link?' — 'password reset' fires Noise."""
        email = make_email(
            subject="Account issue",
            body="Did you get the password reset link I sent?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: question about password reset should be Action"

    def test_question_about_security_alert_is_action(self, use_case):
        """'Did you see the security alert?' — 'security alert' fires Noise."""
        email = make_email(
            subject="Account security",
            body="Did you see the security alert from last night?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: question about security alert should be Action"

    def test_question_about_order_confirmation_is_action(self, use_case):
        """'Where is my order confirmation?' — 'order confirmation' fires Noise."""
        email = make_email(
            subject="Order issue",
            body="I haven't received my order confirmation. Can you check?"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action", f"Got {label}: question about order should be Action"

    def test_pure_shipping_notification_still_noise(self, use_case):
        """Actual shipping notification without question should remain Noise."""
        email = make_email(
            sender="noreply@amazon.com",
            subject="Your order has shipped",
            body="Your package is on its way. Tracking: 1234567890"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ sender catches at step 2 before step 3
        assert label == "Noise"

    def test_pure_receipt_notification_still_noise(self, use_case):
        """Actual receipt without question should remain Noise."""
        email = make_email(
            subject="Payment receipt",
            body="Receipt for $50.00. Transaction ID: TXN123"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise"


# ============================================================================
# 2. NULL / EMPTY FIELD HANDLING
#    Bug: if body or sender is None (not ""), code crashes on .lower()
# ============================================================================


class TestNullFieldHandling:
    """Pipeline should not crash on None/missing fields."""

    def test_none_body_doesnt_crash(self, use_case):
        """Body=None should not crash (get("body","").lower() returns None.lower() → crash)."""
        email_data = {
            "sender": "alice@company.com",
            "subject": "Hello",
            "body": None,
            "recipients": [],
            "is_cc": False,
        }
        try:
            use_case._apply_builtin_rules(email_data)
            # Should not crash — any result is acceptable
            assert True
        except (AttributeError, TypeError) as e:
            pytest.fail(f"None body caused crash: {e}")

    def test_none_sender_doesnt_crash(self, use_case):
        """Sender=None should not crash."""
        email_data = {
            "sender": None,
            "subject": "Hello",
            "body": "Some content",
            "recipients": [],
            "is_cc": False,
        }
        try:
            use_case._apply_builtin_rules(email_data)
            assert True
        except (AttributeError, TypeError) as e:
            pytest.fail(f"None sender caused crash: {e}")

    def test_none_subject_doesnt_crash(self, use_case):
        """Subject=None should not crash."""
        email_data = {
            "sender": "alice@company.com",
            "subject": None,
            "body": "Please review this",
            "recipients": [],
            "is_cc": False,
        }
        try:
            use_case._apply_builtin_rules(email_data)
            assert True
        except (AttributeError, TypeError) as e:
            pytest.fail(f"None subject caused crash: {e}")

    def test_all_none_fields_dont_crash(self, use_case):
        """All None fields should not crash."""
        email_data = {
            "sender": None,
            "subject": None,
            "body": None,
            "recipients": [],
            "is_cc": False,
        }
        try:
            use_case._apply_builtin_rules(email_data)
            assert True
        except (AttributeError, TypeError) as e:
            pytest.fail(f"All None fields caused crash: {e}")

    def test_empty_subject_with_action_body(self, use_case):
        """Empty subject + action body should still classify."""
        email = make_email(
            subject="",
            body="Please review the attached proposal."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_empty_body_empty_subject(self, use_case):
        """Both empty → should fall to LLM (no crash)."""
        email = make_email(subject="", body="")
        label = get_builtin_label(use_case, email)
        # No patterns match → falls to LLM
        assert label is None


# ============================================================================
# 3. BODY TRUNCATION (2000 chars)
#    Pattern match past truncation boundary is invisible.
# ============================================================================


class TestBodyTruncation:
    """Body is truncated at 2000 chars — patterns past boundary are missed."""

    def test_action_pattern_before_truncation_works(self, use_case):
        """Action pattern at char 1990 is within limit."""
        filler = "x " * 990  # ~1980 chars
        email = make_email(
            subject="Request",
            body=filler + "please review this"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_action_pattern_after_truncation_missed(self, use_case):
        """Action pattern at char 2010 is past limit — invisible to pipeline."""
        filler = "x " * 1005  # ~2010 chars
        email = make_email(
            subject="Important",
            body=filler + "please review this immediately"
        )
        label = get_builtin_label(use_case, email)
        # Pattern is past 2000 chars → not matched → falls to LLM
        assert label is None, "Pattern after truncation should not match"

    def test_question_mark_past_truncation(self, use_case):
        """? at char 2010 — not detected as question."""
        filler = "x " * 1005  # ~2010 chars
        email = make_email(
            subject="Quick",
            body=filler + "What do you think?"
        )
        label = get_builtin_label(use_case, email)
        # ? is past 2000 chars → not seen
        assert label is None

    def test_noise_pattern_past_truncation_not_triggered(self, use_case):
        """Noise pattern past 2000 chars should not trigger Noise."""
        filler = "x " * 1005
        email = make_email(
            subject="Update",
            body=filler + "unsubscribe from this newsletter"
        )
        label = get_builtin_label(use_case, email)
        # Past truncation → no match → LLM
        assert label is None


# ============================================================================
# 4. INVOICE NEGATIVE LOOKAHEAD EDGE CASES
#    Pattern: \binvoice\b(?!.*(?:paid|receipt|confirmed))
# ============================================================================


class TestInvoicePatternEdgeCases:
    """Invoice regex negative lookahead may miss edge cases."""

    def test_invoice_followed_by_receipt_no_match(self, use_case):
        """'Invoice receipt from Amazon' — receipt AFTER invoice → no match (correct)."""
        email = make_email(
            subject="Invoice receipt from Amazon",
            body="Your invoice receipt for order #123"
        )
        label = get_builtin_label(use_case, email)
        # Negative lookahead blocks invoice match → receipt matches at step 3 → Noise
        assert label == "Noise"

    def test_receipt_before_invoice_is_noise(self, use_case):
        """FIXED: 'Receipt for invoice #123' — receipt BEFORE invoice → not Action."""
        email = make_email(
            subject="Receipt for invoice #123",
            body=""
        )
        label = get_builtin_label(use_case, email)
        # Programmatic check: "receipt" at pos 0 < "invoice" at pos 12 → skip invoice match
        # Falls to step 3: "receipt" in subject → Noise
        assert label == "Noise"

    def test_invoice_with_paid_in_same_sentence(self, use_case):
        """'Invoice #123 has been paid' — paid after invoice → no match."""
        email = make_email(
            subject="Invoice #123 has been paid",
            body="Thank you for your payment."
        )
        label = get_builtin_label(use_case, email)
        # Negative lookahead blocks: "has been paid" after invoice → no match
        # Cross-field: body has "payment" but not "confirmed/paid" check by invoice handler
        # Actually, the pattern doesn't match at all due to lookahead
        assert label != "Action", "Paid invoice should not be Action"

    def test_invoice_in_body_not_subject(self, use_case):
        """Invoice pattern should also check body, not just subject."""
        email = make_email(
            subject="Payment request",
            body="Please pay the attached invoice by Friday."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_reinvoice_word_boundary(self, use_case):
        """'reinvoice' should NOT match \\binvoice\\b → falls to LLM."""
        email = make_email(
            subject="Can we reinvoice the client?",
            body="Need to reinvoice for the extra services."
        )
        label = get_builtin_label(use_case, email)
        # \b prevents "reinvoice" from matching invoice pattern
        # Subject has "?" but only body ? is checked. Body has no "?"
        # No patterns match → falls to LLM
        assert label is None

    def test_invoice_cross_field_paid_in_body(self, use_case):
        """Invoice in subject + 'paid' in body → should be Noise (receipt)."""
        email = make_email(
            subject="Invoice #456",
            body="This invoice has been paid in full. Thank you."
        )
        label = get_builtin_label(use_case, email)
        # Cross-field check: invoice in subject + body has "paid" → Noise
        assert label == "Noise"


# ============================================================================
# 5. SECURITY / LOGIN / PASSWORD ALERTS REQUIRING ACTION
#    Bug: "password reset", "login alert", "security alert" are Noise,
#    but confirm/verify variants require action.
# ============================================================================


class TestSecurityAlertsThatNeedAction:
    """Security alerts that require user action should not be Noise."""

    def test_password_reset_confirmation_no_question(self, use_case):
        """'Confirm your password reset' with no ? in body → Noise (transactional notification).
        The body has no question mark, so noise text patterns fire normally."""
        email = make_email(
            sender="security@service.com",
            subject="Confirm your password reset",
            body="Click this link to confirm your password reset. Expires in 1 hour."
        )
        label = get_builtin_label(use_case, email)
        # Body has no "?" → noise text patterns active
        # "password reset" in subject → Noise (weak action "confirm your" would be step 6
        # but step 3 fires first)
        assert label == "Noise"

    def test_confirm_login_from_new_device(self, use_case):
        """FIXED: 'Was this you?' login verification → Action (? guard skips noise text)."""
        email = make_email(
            sender="security@google.com",
            subject="Security alert: New sign-in",
            body="Someone signed in to your account from a new device. Was this you?"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → ALL noise text patterns skipped (including "security alert")
        # Step 4b: "?" → Action
        assert label == "Action"

    def test_two_factor_auth_code(self, use_case):
        """2FA code — Action via step 0-verify (cd630d67 P4 follow-up).

        Initialement classé Noise sous prétexte que `noreply@` wins, mais
        c'était un bug : un user qui rate son code 2FA est bloqué de son
        compte. Le step 0-verify match `\\bverification\\s+code\\b` dans
        le subject AVANT step 2-noreply pour garantir que le code
        atteint l'utilisateur.

        Note : la classe parente s'appelle `TestSecurityAlertsThatNeedAction`
        — le test était littéralement contradictoire avec son fixture.
        """
        email = make_email(
            sender="noreply@bank.com",
            subject="Your verification code",
            body="Your verification code is 123456. Do not share this code."
        )
        label = get_builtin_label(use_case, email)
        # step 0-verify > step 2-noreply (intentional, P4 design).
        assert label == "Action"

    def test_fraud_alert_with_please_verify(self, use_case):
        """Fraud alert from alerts@ → Noise (automated sender, security skipped)."""
        email = make_email(
            sender="alerts@creditcard.com",
            subject="Suspicious transaction",
            body="An unauthorized charge of $500 was detected. Please verify this transaction."
        )
        label = get_builtin_label(use_case, email)
        # alerts@ sender = automated → security patterns skipped → Noise
        assert label == "Noise"

    def test_fraud_alert_from_real_bank_email(self, use_case):
        """Fraud alert from bank support team — real email, not noreply@."""
        email = make_email(
            sender="fraud-team@bank.com",
            subject="Urgent: Suspicious activity on your account",
            body="We detected suspicious activity. Please confirm these transactions are legitimate."
        )
        label = get_builtin_label(use_case, email)
        # "please confirm" is ACTION_STRONG_PATTERNS → step 1b → Action
        assert label == "Action"


# ============================================================================
# 6. DELIVERY FAILED vs TRACKING NOTIFICATION
#    "delivery notification" is Noise but "delivery failed" is Action.
# ============================================================================


class TestDeliveryEdgeCases:
    """Delivery notifications vs failed deliveries."""

    def test_delivery_notification_is_noise(self, use_case):
        """Standard delivery notification → Noise."""
        email = make_email(
            sender="noreply@ups.com",
            subject="Delivery notification",
            body="Your package has been delivered."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Noise"  # noreply@ or "delivery notification"

    def test_delivery_failed_from_noreply(self, use_case):
        """Delivery failed from noreply — noreply@ catches first → Noise."""
        email = make_email(
            sender="noreply@fedex.com",
            subject="Delivery failed",
            body="We couldn't deliver your package. Please reschedule."
        )
        label = get_builtin_label(use_case, email)
        # "noreply@" catches at step 2 → Noise
        # Even though "please reschedule" is weak action
        assert label == "Noise"

    def test_delivery_failed_from_real_sender(self, use_case):
        """Delivery failed from real sender — has question mark."""
        email = make_email(
            sender="support@courier.com",
            subject="Package delivery issue",
            body="Delivery failed twice. Would you like to reschedule?"
        )
        label = get_builtin_label(use_case, email)
        # "would you like" is ACTION_STRONG_PATTERNS → step 1b → Action
        assert label == "Action"


# ============================================================================
# 7. WEAK ACTION FROM REAL PERSON + UNSUBSCRIBE FOOTER
#    Automated signals kill weak action, but real person with company footer.
# ============================================================================


class TestWeakActionWithFooter:
    """Real person emails with company-wide unsubscribe footer."""

    def test_real_person_can_you_with_footer(self, use_case):
        """'Can you send me the file?' + unsubscribe footer → body has ? → Action."""
        email = make_email(
            subject="Document request",
            body="Can you send me the latest version of the deck?\n\n---\nUnsubscribe from notifications"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → noise text patterns skipped → step 4b → Action
        # The ? guard protects real questions even with footer
        assert label == "Action"

    def test_real_person_let_me_know_with_footer(self, use_case):
        """'Let me know if you have questions' + opt-out footer → no ? → Noise.
        Body has no actual "?" character — just the word "questions" with period."""
        email = make_email(
            subject="Project update",
            body="Here's the update. Let me know if you have questions.\n\nManage preferences | Opt-out"
        )
        label = get_builtin_label(use_case, email)
        # Body has no "?" → noise text check is active (but no noise text matches)
        # Step 6: "let me know" weak action + "manage preferences" automated → Noise
        assert label == "Noise"

    def test_strong_action_not_killed_by_footer(self, use_case):
        """'Please review' + unsubscribe footer → strong action wins."""
        email = make_email(
            subject="Contract review",
            body="Please review the attached contract.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # "please review" is strong action → step 1b → Action (before automated check)
        assert label == "Action"

    def test_question_with_do_not_reply_footer(self, use_case):
        """Question + 'This is an automated message' footer → Noise (auto-ack pattern fires at step 1b-ack)."""
        email = make_email(
            subject="Quick question",
            body="What time works for you tomorrow?\n\nThis is an automated message. Do not reply."
        )
        label = get_builtin_label(use_case, email)
        # "This is an automated message" matches NOISE_AUTO_ACK_PATTERNS at step 1b-ack
        # which fires BEFORE strong action or question detection.
        assert label == "Noise"


# ============================================================================
# 8. UNICODE EDGE CASES
# ============================================================================


class TestUnicodeEdgeCases:
    """Unicode characters that may break pattern matching."""

    def test_unicode_ellipsis_not_matched_as_dots(self, use_case):
        """Unicode ellipsis '…' (U+2026) vs ASCII dots '...'."""
        email = make_email(
            subject="Update",
            body="\u2026"  # Unicode ellipsis, single character
        )
        label = get_builtin_label(use_case, email)
        # Pattern r"^\s*\.+\s*$" only matches ASCII dots
        # Unicode "…" is 1 char → r"^\s*.{0,3}\s*$" matches (1 char ≤ 3) → Noise
        assert label == "Noise"

    def test_unicode_question_mark_fullwidth(self, use_case):
        """Fullwidth question mark ？ (U+FF1F) not matched by '?' check."""
        email = make_email(
            subject="Request",
            body="Are you available tomorrow\uff1f"  # Fullwidth ?
        )
        label = get_builtin_label(use_case, email)
        # Code checks `"?" in body` — fullwidth ？ is not ASCII ?
        # "are you available" is strong action pattern → step 1b → Action anyway
        assert label == "Action"

    def test_curly_quotes_in_french_pattern(self, use_case):
        """French 'j'ai besoin' with typographic apostrophe (U+2019)."""
        email = make_email(
            subject="Demande",
            body="J\u2019ai besoin de votre aide."
        )
        label = get_builtin_label(use_case, email)
        # Pattern r"\bj['\u2019]ai besoin\b" handles both ' and '
        assert label == "Action"

    def test_curly_quotes_ascii_apostrophe(self, use_case):
        """French 'j'ai besoin' with ASCII apostrophe."""
        email = make_email(
            subject="Demande",
            body="J'ai besoin de votre aide."
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_accented_characters_in_body(self, use_case):
        """French accented text should not break regex."""
        email = make_email(
            subject="Réponse nécessaire",
            body="Est-ce que tu peux vérifier le dossier rapidement?"
        )
        label = get_builtin_label(use_case, email)
        # "est-ce que tu peux" is strong action
        assert label == "Action"


# ============================================================================
# 9. REAL-WORLD EMAIL TYPES (GitHub, Calendar, SaaS, etc.)
# ============================================================================


class TestRealWorldEmailTypes:
    """Common email types from real services."""

    def test_github_pr_review_request(self, use_case):
        """GitHub PR review request — from notifications@ noise sender → Noise."""
        email = make_email(
            sender="notifications@github.com",
            subject="Review requested: fix-auth-bug #456",
            body="alice requested your review on pull request #456. Please review the changes."
        )
        label = get_builtin_label(use_case, email)
        # "notifications@" is noise sender → Noise before any action pattern
        assert label == "Noise"

    def test_github_ci_notification(self, use_case):
        """GitHub CI failure — from notifications@, no action patterns."""
        email = make_email(
            sender="notifications@github.com",
            subject="Build failed: main (abc1234)",
            body="Tests failed in CI pipeline. Check the logs."
        )
        label = get_builtin_label(use_case, email)
        # "notifications@" → Noise at step 2. No strong action to override.
        assert label == "Noise"

    def test_calendar_invite_with_rsvp(self, use_case):
        """NEW calendar invitation from calendar@ → Action (RSVP required).

        The ``^Invitation:`` subject pattern matches
        ``CALENDAR_INVITATION_ACTION_PATTERNS`` (label_email.py:785), which
        is intentionally checked BEFORE the noise sender rule for calendar@.
        This promotes new meeting requests from Google Calendar to Action
        even though the sender is technically a noise-pattern address —
        the user still has a binary decision (accept/decline/tentative) to
        make and shouldn't miss the invitation.

        Existing event updates/cancels are caught earlier by
        ``CALENDAR_HARD_NOISE_PATTERNS`` (line 797) and stay Noise — see
        test_calendar_invite_from_noreply below for the pure-noise path.
        """
        email = make_email(
            sender="calendar@google.com",
            subject="Invitation: Team standup @ 2pm",
            body="Alice has invited you to Team standup. RSVP: Yes / No / Maybe"
        )
        label = get_builtin_label(use_case, email)
        assert label == "Action"

    def test_calendar_invite_from_noreply(self, use_case):
        """Calendar invite from noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@google.com",
            subject="You've been invited to: Quarterly Review",
            body="Please RSVP by Thursday."
        )
        label = get_builtin_label(use_case, email)
        # noreply@ is caught at step 1b-noreply → always Noise, before any action patterns
        assert label == "Noise"

    def test_calendar_rsvp_from_calendar_sender(self, use_case):
        """RSVP from calendar-notification@ → Noise (calendar notification)."""
        email = make_email(
            sender="calendar-notification@google.com",
            subject="Accepted: Meeting with Alex",
            body="Please RSVP to confirm attendance."
        )
        label = get_builtin_label(use_case, email)
        # calendar-notification@ + "Accepted:" subject → Noise
        assert label == "Noise"

    def test_meeting_cancelled_notification(self, use_case):
        """Meeting cancelled from calendar@ → Noise (automated notification)."""
        email = make_email(
            sender="calendar@google.com",
            subject="Cancelled: Team standup",
            body="The event Team standup has been cancelled."
        )
        label = get_builtin_label(use_case, email)
        # calendar@ matches noise sender pattern → Noise
        assert label == "Noise"

    def test_docusign_signature_request(self, use_case):
        """DocuSign from noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@docusign.com",
            subject="Contract ready for signature",
            body="Alice sent you a contract. Please sign the document by Friday."
        )
        label = get_builtin_label(use_case, email)
        # noreply@ is caught at step 1b-noreply → always Noise, even with "please sign"
        assert label == "Noise"

    def test_subscription_renewal_failed(self, use_case):
        """SaaS billing@ sender → Noise (automated sender overrides action patterns)."""
        email = make_email(
            sender="billing@saas.com",
            subject="Payment failed",
            body="Your credit card was declined. Please update your payment method."
        )
        label = get_builtin_label(use_case, email)
        # "billing@" is a noise sender → Noise before any action pattern
        assert label == "Noise"

    def test_slack_mention_with_question(self, use_case):
        """Slack mention from noreply@ → Noise (noreply sender fires at step 1b-noreply before action patterns)."""
        email = make_email(
            sender="noreply@slack.com",
            subject="@alice mentioned you in #project",
            body="@alice: what do you think about the new design?"
        )
        label = get_builtin_label(use_case, email)
        # noreply@ is caught at step 1b-noreply → always Noise, even with "what do you think"
        assert label == "Noise"

    def test_linkedin_connection_request(self, use_case):
        """LinkedIn connection — automated notification."""
        email = make_email(
            sender="messages-noreply@linkedin.com",
            subject="Alice wants to connect with you",
            body="Accept or ignore this invitation.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # "noreply@" in sender → Noise at step 2
        assert label == "Noise"

    def test_trial_ending_notification(self, use_case):
        """SaaS trial ending — from noreply@, no strong action."""
        email = make_email(
            sender="noreply@saas.com",
            subject="Your trial ends in 3 days",
            body="Upgrade now to keep your data. Special offer: 20% off."
        )
        label = get_builtin_label(use_case, email)
        # "noreply@" → Noise at step 2
        assert label == "Noise"

    def test_job_application_acknowledgment(self, use_case):
        """Job application received — waiting pattern."""
        email = make_email(
            sender="careers@company.com",
            subject="Application received",
            body="We have received your application. We will get back to you within 2 weeks."
        )
        label = get_builtin_label(use_case, email)
        # "we will get back to you" is strong waiting → step 1 → Waiting
        assert label == "FYI"

    def test_expense_report_needs_revision(self, use_case):
        """Expense report rejected — needs action."""
        email = make_email(
            sender="finance@company.com",
            subject="Expense report #789 needs revision",
            body="Please provide receipts for items 3 and 5 and resubmit."
        )
        label = get_builtin_label(use_case, email)
        # "please provide" is weak action, but body has "receipts" →
        # Step 3: "receipt" matches Noise? Actually \breceipt\b → "receipts" with s
        # \breceipts\b has boundary after s, but \breceipt\b matches "receipt" in "receipts"
        # because word boundary is between "t" and "s"? No — "receipts" has \breceipt\b
        # matching at the start (r-e-c-e-i-p-t) then followed by "s" — but \b requires
        # a boundary AFTER "t". "ts" is word chars → no boundary. So \breceipt\b does NOT
        # match "receipts"! Good.
        # So: no noise patterns match → step 4b: body has "?"? No.
        # Weak action: "please provide" is weak action → step 6 → is_automated? No → Action
        assert label == "Action"


# ============================================================================
# 10. CROSS-FIELD CONFLICTS
#     Subject says one thing, body says another.
# ============================================================================


class TestCrossFieldConflicts:
    """Conflicting signals between subject and body."""

    def test_action_subject_no_action_needed_body(self, use_case):
        """Subject says 'Review needed', body says 'No action needed'."""
        email = make_email(
            subject="Review needed: Q4 report",
            body="FYI — the Q4 report is attached. No action needed from your side."
        )
        label = get_builtin_label(use_case, email)
        # "No action needed" is strong FYI → step 5
        # But "please review" not in subject (it's "review needed", not "please review")
        # Step 1b: "review needed" is not in ACTION_STRONG_PATTERNS → no match
        # Step 5: "no action needed" → FYI
        assert label == "FYI"

    def test_fyi_subject_question_body(self, use_case):
        """Subject is FYI but body asks a question."""
        email = make_email(
            subject="FYI: New policy update",
            body="New policy attached. Do you have any concerns?"
        )
        label = get_builtin_label(use_case, email)
        # "FYI" in subject is strong FYI → step 5
        # "do you" in body is not strong action (not in patterns)
        # Step 4b: "?" in body → Action
        # But step 5 comes AFTER step 4b... wait no:
        # Pipeline: 1→1b→1c→2→3→3b→4b→5
        # Step 4b: body has "?" → Action (before FYI step 5)
        assert label == "Action"

    def test_noise_sender_real_content(self, use_case):
        """Noise sender but genuinely personal content (rare edge case)."""
        email = make_email(
            sender="noreply@internal.company.com",
            subject="Urgent: Server down",
            body="The production server is down. Who can take a look?"
        )
        label = get_builtin_label(use_case, email)
        # "noreply@" → step 2 Noise. Unless strong action/waiting at step 1/1b.
        # Body has "?" but step 2 fires first.
        # No strong patterns match → step 2 → Noise
        # This is a real issue with internal noreply@ senders for urgent issues
        assert label == "Noise"

    def test_re_prefix_not_treated_as_forward(self, use_case):
        """'Re: Meeting' should not trigger Fwd: FYI pattern."""
        email = make_email(
            subject="Re: Meeting tomorrow",
            body="Sounds good, see you then."
        )
        label = get_builtin_label(use_case, email)
        # "Re:" does NOT match r"^(?:fwd?|tr)\s*:" → no weak FYI trigger
        # No noise/action patterns → falls to LLM
        assert label is None


# ============================================================================
# 11. CLASSIFY_BY_RULES_ONLY PARITY
#     Fast path should behave like _apply_builtin_rules for all key cases.
# ============================================================================


class TestFastPathParity:
    """classify_by_rules_only should match _apply_builtin_rules behavior."""

    def _fast_path_label(self, email):
        """Run classify_by_rules_only and return label name."""
        label_store = Mock()
        label_store.get_rules.return_value = []
        result = LabelEmailUseCase.classify_by_rules_only(email, label_store)
        if result and result.default_label:
            return result.default_label
        return None

    def test_fast_path_strong_action_before_noise_sender(self, use_case):
        """Fast path: strong action should override noise sender."""
        email = make_email(
            sender="noreply@billing.com",
            subject="Invoice #789",
            body="Payment of $500 is due by Friday."
        )
        builtin = get_builtin_label(use_case, email)
        fast = self._fast_path_label(email)
        assert builtin == fast, f"Parity: builtin={builtin}, fast={fast}"

    def test_fast_path_invoice_cross_field(self, use_case):
        """Fast path: invoice + paid body → Noise."""
        email = make_email(
            subject="Invoice #123",
            body="Payment has been confirmed. Thank you."
        )
        builtin = get_builtin_label(use_case, email)
        fast = self._fast_path_label(email)
        assert builtin == fast, f"Parity: builtin={builtin}, fast={fast}"

    def test_fast_path_noise_subject_only(self, use_case):
        """Fast path: newsletter in subject → Noise."""
        email = make_email(
            subject="Weekly newsletter",
            body="Here's what happened this week."
        )
        builtin = get_builtin_label(use_case, email)
        fast = self._fast_path_label(email)
        assert builtin == fast, f"Parity: builtin={builtin}, fast={fast}"

    def test_fast_path_none_for_no_match(self, use_case):
        """Fast path: no match → returns None (LLM fallback needed)."""
        email = make_email(
            sender="alice@company.com",
            subject="Project discussion",
            body="Let's discuss the project scope next week."
        )
        builtin = get_builtin_label(use_case, email)
        fast = self._fast_path_label(email)
        assert builtin == fast, f"Parity: builtin={builtin}, fast={fast}"


# ============================================================================
# 12. SHIPPING / RECEIPT WORD BOUNDARY
#     Does \breceipt\b match "receipts"? Does \bshipping\b match "shipping"?
# ============================================================================


class TestWordBoundaryPrecision:
    """Word boundary patterns should not over-match plural/compound forms."""

    def test_receipts_plural_not_matched(self, use_case):
        """'Receipts' (plural) should NOT match \\breceipt\\b → falls to LLM."""
        email = make_email(
            subject="Expense report",
            body="Please attach the receipts for reimbursement."
        )
        label = get_builtin_label(use_case, email)
        # \breceipt\b does NOT match "receipts" — both "t" and "s" are \w, no boundary
        # No noise patterns match. No strong action. No "?" in body.
        # Falls to LLM
        assert label is None

    def test_unsubscribes_plural_not_matched_in_subject(self, use_case):
        """'Unsubscribes' should NOT match \\bunsubscribe\\b in subject-only."""
        email = make_email(
            subject="Tracking unsubscribes from campaign",
            body="Here are the metrics."
        )
        label = get_builtin_label(use_case, email)
        # \bunsubscribe\b should not match "unsubscribes"
        # Falls to LLM
        assert label is None

    def test_shipping_in_different_context(self, use_case):
        """FIXED: 'The shipping department needs your approval' → shipping only in subject-only patterns."""
        email = make_email(
            subject="Approval needed",
            body="The shipping department needs your approval on this order."
        )
        label = get_builtin_label(use_case, email)
        # "shipping" moved to NOISE_SUBJECT_ONLY_PATTERNS — body match doesn't trigger
        # Subject "Approval needed" has no noise patterns
        # No strong action match. No "?" in body. Falls to LLM.
        assert label is None


# ============================================================================
# 13. AUTOMATED SIGNALS INTERACTION WITH QUESTION MARK
#     Question mark at step 4b doesn't check is_automated. Should it?
# ============================================================================


class TestQuestionMarkAndAutomatedSignals:
    """Step 4b (?) fires before automated signal check — is that correct?"""

    def test_automated_email_with_question_mark(self, use_case):
        """Marketing email with '?' + 'Unsubscribe' → Noise (automated signals detected).
        The question is rhetorical marketing, not a genuine question needing a reply."""
        email = make_email(
            subject="Ready to upgrade",
            body="Want to unlock premium features? Click here to upgrade.\n\nUnsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # "Want to unlock" = marketing question (MARKETING_QUESTION_RE)
        # "Unsubscribe" = automated signal → is_automated=True
        # Step 4b: is_automated=True + marketing question → no base score → not genuine
        # No other patterns match → falls to LLM
        # NOTE: with newsletter detection, this could also be caught at step 2-auto
        assert label is None or label == "Noise"

    def test_newsletter_question_in_subject_only(self, use_case):
        """Newsletter with '?' in subject — subject ? is NOT checked (correct)."""
        email = make_email(
            subject="Is your portfolio ready for 2026?",
            body="Our latest analysis shows... Unsubscribe"
        )
        label = get_builtin_label(use_case, email)
        # Code only checks "?" in body, not subject (good!)
        # "unsubscribe" in body → AUTOMATED_SIGNALS_RE (body, not NOISE_TEXT_PATTERNS)
        # No noise text patterns match → no strong patterns
        # Step 4b: body has no "?" (just subject has it)... wait, does body have "?"?
        # Body: "Our latest analysis shows... Unsubscribe" → no "?"
        # Step 6: is_automated=True → weak action patterns?
        # No weak action patterns match → no label → LLM
        assert label is None


# ============================================================================
# 14. EDGE CASES IN EMPTY BODY PATTERNS
# ============================================================================


class TestEmptyBodyPatternEdgeCases:
    """Subtle edge cases in NOISE_EMPTY_BODY_PATTERNS."""

    def test_body_with_only_whitespace(self, use_case):
        """Body is just spaces/newlines."""
        email = make_email(
            subject="Subject",
            body="   \n\n   "
        )
        label = get_builtin_label(use_case, email)
        # r"^\s*.{0,3}\s*$" — whitespace body is 0 visible chars → matches
        # But body.lower()[:2000] is "   \n\n   " — does re.match work with \n?
        # re.match only matches start of string; \n is included in \s
        # The body stripped is empty (0 chars ≤ 3) → Noise
        assert label == "Noise"

    def test_body_exactly_4_chars(self, use_case):
        """Body '1234' (4 chars) → should NOT match ≤3 pattern."""
        email = make_email(
            subject="Code",
            body="1234"
        )
        label = get_builtin_label(use_case, email)
        # 4 chars > 3 → r"^\s*.{0,3}\s*$" doesn't match
        # No other patterns → LLM
        assert label is None

    def test_body_thanks_with_period(self, use_case):
        """'Thanks.' in a thread (Re:) → FYI (thread acknowledgment)."""
        email = make_email(
            subject="Re: Document",
            body="Thanks."
        )
        label = get_builtin_label(use_case, email)
        # Thread ack: "Thanks." in Re: thread → FYI (not Noise)
        assert label == "FYI"

    def test_body_thanks_but_has_question(self, use_case):
        """'Thanks?' — contains ? → empty body check is skipped."""
        email = make_email(
            subject="Re: Proposal",
            body="Thanks?"
        )
        label = get_builtin_label(use_case, email)
        # Body has "?" → step 1c skipped
        # Step 4b: "?" in body → Action
        assert label == "Action"

    def test_body_just_emoji(self, use_case):
        """Body is just an emoji — short body pattern."""
        email = make_email(
            subject="Re: Meeting",
            body="\U0001f44d"  # 👍
        )
        label = get_builtin_label(use_case, email)
        # Single character → r"^\s*.{0,3}\s*$" matches? 👍 is 1 char (4 bytes)
        # In Python, len("👍") == 1, so .{0,3} matches it → Noise
        assert label == "Noise"

    def test_body_multiline_short(self, use_case):
        """Body with newlines but short content in Re: thread → FYI (thread ack)."""
        email = make_email(
            subject="Re: Update",
            body="ok\n\n"
        )
        label = get_builtin_label(use_case, email)
        # Thread ack: "ok" in Re: thread → FYI (not Noise)
        assert label == "FYI"
