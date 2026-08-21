# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour DetectPhishingUseCase."""

from unittest.mock import MagicMock
from app.application.detect_phishing import DetectPhishingUseCase
from app.domain.entities.phishing import PhishingResult, SuspiciousUrl


class TestDetectPhishingUseCase:
    """Tests pour DetectPhishingUseCase."""

    def _make_use_case(self, detector=None):
        if detector is None:
            detector = MagicMock()
        return DetectPhishingUseCase(detector=detector)

    def _make_email(self, subject="Test", body="Test body"):
        email = MagicMock()
        email.subject = subject
        email.body = body
        return email

    def test_execute_calls_detector(self):
        detector = MagicMock()
        expected = PhishingResult.default()
        detector.analyze_email.return_value = expected
        uc = self._make_use_case(detector)
        email = self._make_email()

        result = uc.execute(email)

        detector.analyze_email.assert_called_once_with(
            subject=email.subject,
            body=email.body,
        )
        assert result == expected

    def test_execute_returns_phishing_result(self):
        url = SuspiciousUrl(url="http://evil.com", reasons=["lookalike"], risk_score=90)
        expected = PhishingResult(
            risk_score=85,
            suspicious_urls=[url],
            is_phishing=True,
            analysis_summary="Phishing detected",
        )
        detector = MagicMock()
        detector.analyze_email.return_value = expected
        uc = self._make_use_case(detector)
        email = self._make_email(subject="Urgent", body="Click here")

        result = uc.execute(email)

        assert result.is_phishing is True
        assert result.risk_score == 85
        assert len(result.suspicious_urls) == 1

    def test_execute_safe_email(self):
        expected = PhishingResult(
            risk_score=5,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="Email is safe",
        )
        detector = MagicMock()
        detector.analyze_email.return_value = expected
        uc = self._make_use_case(detector)
        email = self._make_email()

        result = uc.execute(email)

        assert result.is_phishing is False
        assert result.suspicious_urls == []

    def test_execute_passes_correct_subject_and_body(self):
        detector = MagicMock()
        detector.analyze_email.return_value = PhishingResult.default()
        uc = self._make_use_case(detector)
        email = self._make_email(subject="Verify your account", body="Click this link")

        uc.execute(email)

        call_args = detector.analyze_email.call_args
        assert call_args.kwargs["subject"] == "Verify your account"
        assert call_args.kwargs["body"] == "Click this link"
