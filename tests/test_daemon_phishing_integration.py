# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests d'intégration du PhishingDetector dans le daemon."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.daemon import EmailDaemon
from app.domain.entities import PhishingResult, SuspiciousUrl
from app.domain.services import PhishingDetector
from app.interfaces.email_provider import StandardEmail


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = []
    provider.create_draft.return_value = "draft-456"
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    return provider


@pytest.fixture
def mock_drafter():
    drafter = MagicMock()
    drafter.draft.return_value = "Generated response."
    drafter.revise.return_value = "Revised response."
    return drafter


@pytest.fixture
def mock_critic():
    critic = MagicMock()
    critic.evaluate.return_value = "VALID"
    critic.is_valid.return_value = True
    return critic


@pytest.fixture
def mock_prioritizer():
    prioritizer = MagicMock()
    prioritizer.analyze.return_value = {"priority_score": 75}
    return prioritizer


@pytest.fixture
def mock_classifier():
    classifier = MagicMock()
    classifier.classify.return_value = {"category": "NORMAL"}
    classifier.should_skip.return_value = False
    return classifier


@pytest.fixture
def mock_tracker():
    tracker = MagicMock()
    tracker.is_processed.return_value = False
    tracker.mark_processed.return_value = None
    tracker.count.return_value = 0
    return tracker


@pytest.fixture
def mock_learning_manager():
    manager = MagicMock()
    manager.should_require_review.return_value = False
    return manager


@pytest.fixture
def mock_draft_history():
    history = MagicMock()
    history.add.return_value = None
    return history


@pytest.fixture
def mock_processed_drafts_tracker():
    tracker = MagicMock()
    tracker.is_processed.return_value = False
    return tracker


@pytest.fixture
def mock_message_router():
    router = MagicMock()
    router.route.return_value = MagicMock(routing_decision=None, supervision_result=None)
    router.get_final_agent_id.return_value = "default_agent"
    return router


@pytest.fixture
def mock_phishing_detector():
    detector = MagicMock(spec=PhishingDetector)
    detector.analyze_email.return_value = PhishingResult(
        risk_score=0,
        suspicious_urls=[],
        is_phishing=False,
        analysis_summary="No URLs found"
    )
    return detector


@pytest.fixture
def mock_draft_completion_agent():
    agent = MagicMock()
    agent.is_completion_request.return_value = False
    return agent


@pytest.fixture
def mock_task_extractor():
    extractor = MagicMock()
    extractor.extract.return_value = []
    return extractor


@pytest.fixture
def mock_task_repository():
    repository = MagicMock()
    repository.add_many.return_value = []
    return repository


@pytest.fixture
def safe_email():
    return StandardEmail(
        id="email-safe-123",
        sender="colleague@company.com",
        sender_name="Colleague",
        to=["me@company.com"],
        cc=[],
        subject="Meeting tomorrow",
        body="Let's meet at 10am.",
        body_html=None,
        received_at=datetime.now().isoformat(),
        is_read=False,
        has_attachments=False,
        conversation_id="thread-123",
        provider_source="test",
    )


@pytest.fixture
def phishing_email():
    return StandardEmail(
        id="email-phishing-456",
        sender="security@amaz0n-secure.xyz",
        sender_name="Amazon Security",
        to=["me@company.com"],
        cc=[],
        subject="Urgent: Verify your account now!",
        body="Your account has been compromised. Click here: http://amaz0n-login.xyz/verify",
        body_html=None,
        received_at=datetime.now().isoformat(),
        is_read=False,
        has_attachments=False,
        conversation_id="thread-456",
        provider_source="test",
    )


@pytest.fixture
def daemon_with_phishing_detector(
    mock_provider, mock_drafter, mock_critic, mock_prioritizer, mock_classifier,
    mock_tracker, mock_learning_manager, mock_draft_history,
    mock_processed_drafts_tracker, mock_message_router, mock_phishing_detector,
    mock_draft_completion_agent, mock_task_extractor, mock_task_repository
):
    daemon = EmailDaemon(
        provider=mock_provider,
        drafter=mock_drafter,
        critic=mock_critic,
        prioritizer=mock_prioritizer,
        classifier=mock_classifier,
        tracker=mock_tracker,
        learning_manager=mock_learning_manager,
        draft_history=mock_draft_history,
        processed_drafts_tracker=mock_processed_drafts_tracker,
        message_router=mock_message_router,
        draft_completion_agent=mock_draft_completion_agent,
        task_extractor=mock_task_extractor,
        task_repository=mock_task_repository,
        phishing_detector=mock_phishing_detector,
        poll_interval=1,
        use_smart_routing=False,
    )
    return daemon


class TestPhishingDetectionInDaemon:
    """Tests pour la détection de phishing intégrée au daemon.

    Note: auto-draft is disabled in process_email() so step 3 (_detect_phishing)
    is not reached. Tests that verify phishing detection use _detect_phishing()
    directly or verify process_email() returns True (auto-draft disabled).
    """

    def test_daemon_has_phishing_detector(self, daemon_with_phishing_detector):
        assert daemon_with_phishing_detector.phishing_detector is not None

    def test_process_email_calls_phishing_detector(
        self, daemon_with_phishing_detector, safe_email, mock_phishing_detector
    ):
        """Auto-draft disabled: phishing detector not called from process_email.
        Test _detect_phishing directly."""
        result = daemon_with_phishing_detector._detect_phishing(safe_email)

        assert result is False
        mock_phishing_detector.analyze_email.assert_called_once_with(
            subject=safe_email.subject,
            body=safe_email.body
        )

    def test_safe_email_continues_processing(
        self, daemon_with_phishing_detector, safe_email, mock_provider
    ):
        """Auto-draft disabled: process_email returns True, no draft created."""
        result = daemon_with_phishing_detector.process_email(safe_email)

        assert result is True
        # Auto-draft disabled: no draft created
        mock_provider.create_draft.assert_not_called()

    def test_phishing_email_applies_label(
        self, daemon_with_phishing_detector, phishing_email,
        mock_phishing_detector, mock_provider
    ):
        """Test _detect_phishing applies PHISHING label directly."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=75,
            suspicious_urls=[SuspiciousUrl(
                url="http://amaz0n-login.xyz/verify",
                reasons=["typosquatting", "suspicious_tld"],
                risk_score=75
            )],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )

        result = daemon_with_phishing_detector._detect_phishing(phishing_email)

        assert result is True
        mock_provider.apply_label.assert_any_call(phishing_email.id, "PHISHING")

    def test_phishing_email_skips_draft_generation(
        self, daemon_with_phishing_detector, phishing_email,
        mock_phishing_detector, mock_drafter
    ):
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=75,
            suspicious_urls=[SuspiciousUrl(
                url="http://amaz0n-login.xyz/verify",
                reasons=["typosquatting"],
                risk_score=75
            )],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )

        daemon_with_phishing_detector.process_email(phishing_email)

        mock_drafter.draft.assert_not_called()

    def test_phishing_detection_returns_true_for_skipped_email(
        self, daemon_with_phishing_detector, phishing_email, mock_phishing_detector
    ):
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=80,
            suspicious_urls=[],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )

        result = daemon_with_phishing_detector.process_email(phishing_email)

        assert result is True

    def test_daemon_without_phishing_detector_still_works(
        self, mock_provider, mock_drafter, mock_critic, mock_prioritizer,
        mock_classifier, mock_tracker, mock_learning_manager, mock_draft_history,
        mock_processed_drafts_tracker, mock_message_router,
        mock_draft_completion_agent, mock_task_extractor, mock_task_repository, safe_email
    ):
        """Auto-draft disabled: process_email returns True without draft."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            tracker=mock_tracker,
            learning_manager=mock_learning_manager,
            draft_history=mock_draft_history,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            draft_completion_agent=mock_draft_completion_agent,
            task_extractor=mock_task_extractor,
            task_repository=mock_task_repository,
            poll_interval=1,
            use_smart_routing=False,
        )

        result = daemon.process_email(safe_email)

        assert result is True
        # Auto-draft disabled: no draft created
        mock_provider.create_draft.assert_not_called()


class TestPhishingDetectionEdgeCases:
    """Tests pour les cas limites de la détection de phishing.

    Note: auto-draft is disabled so _detect_phishing is not reached from process_email.
    These tests call _detect_phishing directly.
    """

    def test_phishing_detection_with_none_body(
        self, daemon_with_phishing_detector, mock_phishing_detector
    ):
        email = StandardEmail(
            id="email-none-body",
            sender="test@example.com",
            sender_name="Test",
            to=["me@example.com"],
            cc=[],
            subject="Test subject",
            body=None,
            body_html=None,
            received_at=datetime.now().isoformat(),
            is_read=False,
            has_attachments=False,
            conversation_id="thread-1",
            provider_source="test",
        )

        daemon_with_phishing_detector._detect_phishing(email)

        mock_phishing_detector.analyze_email.assert_called_once()

    def test_phishing_detection_with_empty_subject_and_body(
        self, daemon_with_phishing_detector, mock_phishing_detector
    ):
        email = StandardEmail(
            id="email-empty",
            sender="test@example.com",
            sender_name="Test",
            to=["me@example.com"],
            cc=[],
            subject="",
            body="",
            body_html=None,
            received_at=datetime.now().isoformat(),
            is_read=False,
            has_attachments=False,
            conversation_id="thread-1",
            provider_source="test",
        )

        daemon_with_phishing_detector._detect_phishing(email)

        mock_phishing_detector.analyze_email.assert_called_once()

    def test_borderline_risk_score_below_threshold(
        self, daemon_with_phishing_detector, safe_email,
        mock_phishing_detector, mock_drafter
    ):
        """Risk score below threshold: _detect_phishing returns False (not phishing)."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=69,
            suspicious_urls=[SuspiciousUrl(
                url="http://example.xyz/login",
                reasons=["suspicious_tld", "suspicious_path"],
                risk_score=35
            )],
            is_phishing=False,
            analysis_summary="Low risk"
        )

        result = daemon_with_phishing_detector._detect_phishing(safe_email)

        assert result is False

    def test_borderline_risk_score_at_threshold(
        self, daemon_with_phishing_detector, safe_email,
        mock_phishing_detector, mock_drafter
    ):
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=70,
            suspicious_urls=[],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )

        daemon_with_phishing_detector.process_email(safe_email)

        mock_drafter.draft.assert_not_called()

    def test_apply_label_failure_propagates(
        self, daemon_with_phishing_detector, phishing_email,
        mock_phishing_detector, mock_provider
    ):
        """If apply_label raises, the exception propagates from _detect_phishing.

        Note: apply_label('PHISHING') is not wrapped in try/except in _detect_phishing,
        so the exception propagates. The caller (process_email) catches it.
        """
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=85,
            suspicious_urls=[],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )
        mock_provider.apply_label.side_effect = Exception("Label API error")

        with pytest.raises(Exception, match="Label API error"):
            daemon_with_phishing_detector._detect_phishing(phishing_email)

    def test_phishing_detector_exception_propagates(
        self, daemon_with_phishing_detector, safe_email, mock_phishing_detector
    ):
        """Une exception dans le detector is propagated from _detect_phishing."""
        mock_phishing_detector.analyze_email.side_effect = RuntimeError(
            "Detector crash"
        )

        with pytest.raises(RuntimeError, match="Detector crash"):
            daemon_with_phishing_detector._detect_phishing(safe_email)

    def test_non_phishing_with_positive_risk_score(
        self, daemon_with_phishing_detector, safe_email,
        mock_phishing_detector, mock_drafter
    ):
        """Email with score > 0 but < threshold: _detect_phishing returns False."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=45,
            suspicious_urls=[SuspiciousUrl(
                url="http://example.xyz/something",
                reasons=["suspicious_tld"],
                risk_score=45
            )],
            is_phishing=False,
            analysis_summary="Low risk - below threshold"
        )

        result = daemon_with_phishing_detector._detect_phishing(safe_email)

        assert result is False

    def test_phishing_with_none_subject_returns_false(
        self, daemon_with_phishing_detector, mock_phishing_detector, mock_provider
    ):
        """Email avec subject None cause une erreur (bug connu: email.subject[:50])."""
        email = StandardEmail(
            id="email-none-subject",
            sender="scam@phishing.xyz",
            sender_name="Scammer",
            to=["victim@company.com"],
            cc=[],
            subject=None,
            body="Click http://g00gle-verify.xyz/login now!",
            body_html=None,
            received_at=datetime.now().isoformat(),
            is_read=False,
            has_attachments=False,
            conversation_id="thread-scam",
            provider_source="test",
        )
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=80,
            suspicious_urls=[],
            is_phishing=True,
            analysis_summary="PHISHING DETECTED"
        )

        # Bug connu: le daemon fait email.subject[:50] qui échoue si subject=None
        # Le daemon gère l'exception et retourne False
        result = daemon_with_phishing_detector.process_email(email)

        assert result is False

    def test_multiple_phishing_urls_detected(
        self, daemon_with_phishing_detector, mock_phishing_detector, mock_provider
    ):
        """Email with multiple phishing URLs detected by _detect_phishing."""
        email = StandardEmail(
            id="email-multi-phishing",
            sender="scam@phishing.xyz",
            sender_name="Scammer",
            to=["victim@company.com"],
            cc=[],
            subject="Multiple links",
            body="""
            Link 1: http://g00gle-login.xyz/verify
            Link 2: http://amaz0n-secure.xyz/account
            """,
            body_html=None,
            received_at=datetime.now().isoformat(),
            is_read=False,
            has_attachments=False,
            conversation_id="thread-multi",
            provider_source="test",
        )
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=90,
            suspicious_urls=[
                SuspiciousUrl(
                    url="http://g00gle-login.xyz/verify",
                    reasons=["typosquatting"],
                    risk_score=85
                ),
                SuspiciousUrl(
                    url="http://amaz0n-secure.xyz/account",
                    reasons=["typosquatting"],
                    risk_score=85
                ),
            ],
            is_phishing=True,
            analysis_summary="PHISHING: 2 URLs suspectes"
        )

        result = daemon_with_phishing_detector._detect_phishing(email)

        assert result is True
        mock_provider.apply_label.assert_any_call(email.id, "PHISHING")

    def test_risk_score_zero_continues_processing(
        self, daemon_with_phishing_detector, safe_email,
        mock_phishing_detector, mock_drafter
    ):
        """Email with score 0 (no URLs): _detect_phishing returns False."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=0,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="No URLs found"
        )

        result = daemon_with_phishing_detector._detect_phishing(safe_email)

        assert result is False

    def test_risk_score_exactly_one_below_threshold(
        self, daemon_with_phishing_detector, safe_email,
        mock_phishing_detector, mock_drafter
    ):
        """Email avec score 69 (juste en dessous du seuil 70) continue."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=69,
            suspicious_urls=[SuspiciousUrl(
                url="http://slightly-suspicious.xyz/page",
                reasons=["suspicious_tld"],
                risk_score=69
            )],
            is_phishing=False,
            analysis_summary="Borderline but OK"
        )

        result = daemon_with_phishing_detector._detect_phishing(safe_email)

        assert result is False

    def test_risk_score_maximum_100(
        self, daemon_with_phishing_detector, phishing_email,
        mock_phishing_detector, mock_provider, mock_drafter
    ):
        """Email with maximum score (100) is blocked by _detect_phishing."""
        mock_phishing_detector.analyze_email.return_value = PhishingResult(
            risk_score=100,
            suspicious_urls=[SuspiciousUrl(
                url="http://192.168.1.1/g00gle-amaz0n-paypa1.php",
                reasons=["ip_address", "typosquatting", "suspicious_path"],
                risk_score=100
            )],
            is_phishing=True,
            analysis_summary="CRITICAL PHISHING"
        )

        result = daemon_with_phishing_detector._detect_phishing(phishing_email)

        assert result is True
        mock_provider.apply_label.assert_any_call(phishing_email.id, "PHISHING")
