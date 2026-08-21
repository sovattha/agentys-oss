# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour DetectPhishingUseCase."""

import pytest
from unittest.mock import Mock

from app.application.detect_phishing import DetectPhishingUseCase
from app.domain.entities import PhishingResult, SuspiciousUrl
from app.domain.services import PhishingDetector
from app.interfaces.email_provider import StandardEmail


class TestDetectPhishingUseCase:
    """Tests pour DetectPhishingUseCase."""

    def test_execute_returns_phishing_result(self):
        detector = Mock(spec=PhishingDetector)
        expected_result = PhishingResult(
            risk_score=0,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="No URLs found in email"
        )
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject="Hello", body="Safe email content")

        result = use_case.execute(email)

        assert result == expected_result
        detector.analyze_email.assert_called_once_with(
            subject="Hello",
            body="Safe email content"
        )

    def test_execute_detects_phishing_email(self):
        detector = Mock(spec=PhishingDetector)
        suspicious_url = SuspiciousUrl(
            url="http://amaz0n-login.xyz/verify",
            reasons=["typosquatting", "suspicious_tld", "suspicious_path"],
            risk_score=75
        )
        expected_result = PhishingResult(
            risk_score=75,
            suspicious_urls=[suspicious_url],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED: 1 suspicious URL(s) found"
        )
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(
            subject="Account verification required",
            body="Click here: http://amaz0n-login.xyz/verify"
        )

        result = use_case.execute(email)

        assert result.is_phishing is True
        assert result.risk_score == 75
        assert len(result.suspicious_urls) == 1

    def test_execute_handles_none_subject(self):
        detector = Mock(spec=PhishingDetector)
        expected_result = PhishingResult.default()
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject=None, body="Body content")

        use_case.execute(email)

        detector.analyze_email.assert_called_once_with(
            subject=None,
            body="Body content"
        )

    def test_execute_handles_none_body(self):
        detector = Mock(spec=PhishingDetector)
        expected_result = PhishingResult.default()
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject="Subject", body=None)

        use_case.execute(email)

        detector.analyze_email.assert_called_once_with(
            subject="Subject",
            body=None
        )

    def test_execute_handles_empty_email(self):
        detector = Mock(spec=PhishingDetector)
        expected_result = PhishingResult(
            risk_score=0,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="No URLs found in email"
        )
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject="", body="")

        result = use_case.execute(email)

        assert result.is_phishing is False

    def test_execute_with_real_detector(self):
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="Urgent: Verify your account",
            body="Please click http://g00gle-login.xyz/verify to verify your account"
        )

        result = use_case.execute(email)

        assert result.is_phishing is True
        assert result.risk_score >= 70

    def test_execute_safe_email_with_real_detector(self):
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="Meeting tomorrow",
            body="Let's meet at 10am. See you then!"
        )

        result = use_case.execute(email)

        assert result.is_phishing is False
        assert result.risk_score == 0

    def test_execute_propagates_detector_exception(self):
        """Le use case propage les exceptions du detector."""
        detector = Mock(spec=PhishingDetector)
        detector.analyze_email.side_effect = RuntimeError("Detector error")

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject="Test", body="Test body")

        with pytest.raises(RuntimeError, match="Detector error"):
            use_case.execute(email)

    def test_execute_with_unicode_content(self):
        """Le use case gère correctement les caractères Unicode."""
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="Réunion demain 日本語 🚀",
            body="Vérifiez votre compte sur https://例え.jp/login"
        )

        result = use_case.execute(email)

        # Doit s'exécuter sans erreur, même avec des caractères Unicode
        assert result is not None
        assert isinstance(result.risk_score, int)

    def test_execute_with_special_characters_in_subject(self):
        """Le use case gère les caractères spéciaux dans le sujet."""
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="RE: [URGENT] <test> 'quoted' \"double\" & ampersand",
            body="Normal body content"
        )

        result = use_case.execute(email)

        assert result is not None
        assert result.is_phishing is False

    def test_execute_with_very_long_email(self):
        """Le use case gère les emails très longs."""
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        # Email avec un body très long (100K caractères)
        long_body = "A" * 100000

        email = self._create_email(
            subject="Long email test",
            body=long_body
        )

        result = use_case.execute(email)

        assert result is not None
        assert result.is_phishing is False

    def test_execute_with_multiple_suspicious_urls_in_body(self):
        """Le use case détecte correctement plusieurs URLs suspectes."""
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="Check these links",
            body="""
            First link: http://g00gle-login.xyz/verify
            Second link: http://amaz0n-secure.xyz/account
            Third link: http://paypa1-security.xyz/verify
            """
        )

        result = use_case.execute(email)

        assert result.is_phishing is True
        assert len(result.suspicious_urls) >= 1
        assert result.risk_score >= 70

    def test_execute_with_mixed_safe_and_suspicious_urls(self):
        """Le use case détecte le phishing même avec des URLs légitimes."""
        detector = PhishingDetector()
        use_case = DetectPhishingUseCase(detector=detector)

        email = self._create_email(
            subject="Links for you",
            body="""
            Safe: https://www.google.com
            Safe: https://github.com/user/repo
            DANGEROUS: http://g00gle-verify.xyz/login
            """
        )

        result = use_case.execute(email)

        # L'URL suspecte doit être détectée
        assert result.is_phishing is True

    def test_execute_with_both_none_subject_and_body(self):
        """Le use case gère None pour subject et body simultanément."""
        detector = Mock(spec=PhishingDetector)
        expected_result = PhishingResult(
            risk_score=0,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="No content"
        )
        detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=detector)
        email = self._create_email(subject=None, body=None)

        result = use_case.execute(email)

        detector.analyze_email.assert_called_once_with(
            subject=None,
            body=None
        )
        assert result.is_phishing is False

    def _create_email(
        self,
        subject: str = "Test",
        body: str = "Test body"
    ) -> StandardEmail:
        return StandardEmail(
            id="test-email-123",
            sender="sender@example.com",
            sender_name="Test Sender",
            to=["recipient@example.com"],
            cc=[],
            subject=subject,
            body=body,
            body_html=None,
            received_at="2024-01-15T10:00:00Z",
            is_read=False,
            has_attachments=False,
            conversation_id="conv-123",
            provider_source="test",
            raw_metadata={}
        )
