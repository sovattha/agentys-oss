# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.application.detect_phishing."""

from unittest.mock import MagicMock

from app.domain.entities import PhishingResult
from app.application.detect_phishing import DetectPhishingUseCase
from app.interfaces.email_provider import StandardEmail


def _make_email(**overrides) -> StandardEmail:
    """Crée un StandardEmail minimal pour les tests."""
    defaults = dict(
        id="email-1",
        sender="test@example.com",
        sender_name="Test",
        to=["dest@example.com"],
        cc=[],
        subject="Test Subject",
        body="Test body content",
        body_html="",
        received_at="2026-03-01T10:00:00Z",
        is_read=False,
        has_attachments=False,
        attachments=[],
        conversation_id=None,
        provider_source="gmail",
        raw_metadata={},
    )
    defaults.update(overrides)
    return StandardEmail(**defaults)


class TestDetectPhishingUseCase:
    def test_execute_delegates_to_detector(self):
        expected_result = PhishingResult.default()
        mock_detector = MagicMock()
        mock_detector.analyze_email.return_value = expected_result

        use_case = DetectPhishingUseCase(detector=mock_detector)
        email = _make_email(subject="Urgent: Verify your account", body="Click here now")
        result = use_case.execute(email)

        assert result is expected_result
        mock_detector.analyze_email.assert_called_once_with(
            subject="Urgent: Verify your account",
            body="Click here now",
        )

    def test_passes_subject_and_body_only(self):
        """Le use case ne passe que subject et body au détecteur."""
        mock_detector = MagicMock()
        mock_detector.analyze_email.return_value = PhishingResult.default()

        use_case = DetectPhishingUseCase(detector=mock_detector)
        email = _make_email(
            subject="Invoice #12345",
            body="Please pay immediately",
            sender="suspicious@phish.com",
        )
        use_case.execute(email)

        call_kwargs = mock_detector.analyze_email.call_args
        assert call_kwargs == ((), {"subject": "Invoice #12345", "body": "Please pay immediately"})

    def test_returns_phishing_result(self):
        phishing_result = PhishingResult(
            risk_score=85,
            suspicious_urls=[],
            is_phishing=True,
            analysis_summary="High risk phishing detected",
        )
        mock_detector = MagicMock()
        mock_detector.analyze_email.return_value = phishing_result

        use_case = DetectPhishingUseCase(detector=mock_detector)
        result = use_case.execute(_make_email())

        assert result.is_phishing is True
        assert result.risk_score == 85
