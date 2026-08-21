# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les entités phishing."""

import pytest
from app.domain.entities.phishing import SuspiciousUrl, PhishingResult
from app.domain.exceptions import InvalidBoundsError


class TestSuspiciousUrl:
    """Tests pour SuspiciousUrl."""

    def test_create_valid_suspicious_url(self):
        url = SuspiciousUrl(url="http://evil.com", reasons=["lookalike"], risk_score=80)
        assert url.url == "http://evil.com"
        assert url.reasons == ["lookalike"]
        assert url.risk_score == 80

    def test_risk_score_zero_is_valid(self):
        url = SuspiciousUrl(url="http://safe.com", reasons=[], risk_score=0)
        assert url.risk_score == 0

    def test_risk_score_100_is_valid(self):
        url = SuspiciousUrl(url="http://evil.com", reasons=["phishing"], risk_score=100)
        assert url.risk_score == 100

    def test_risk_score_negative_raises(self):
        with pytest.raises(InvalidBoundsError):
            SuspiciousUrl(url="http://evil.com", reasons=[], risk_score=-1)

    def test_risk_score_above_100_raises(self):
        with pytest.raises(InvalidBoundsError):
            SuspiciousUrl(url="http://evil.com", reasons=[], risk_score=101)

    def test_to_dict(self):
        url = SuspiciousUrl(url="http://evil.com", reasons=["lookalike", "typosquat"], risk_score=75)
        d = url.to_dict()
        assert d == {
            "url": "http://evil.com",
            "reasons": ["lookalike", "typosquat"],
            "risk_score": 75,
        }

    def test_multiple_reasons(self):
        url = SuspiciousUrl(url="http://x.com", reasons=["a", "b", "c"], risk_score=50)
        assert len(url.reasons) == 3

    def test_empty_reasons_list(self):
        url = SuspiciousUrl(url="http://x.com", reasons=[], risk_score=10)
        assert url.reasons == []


class TestPhishingResult:
    """Tests pour PhishingResult."""

    def test_create_valid_result(self):
        result = PhishingResult(
            risk_score=50,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="Safe email",
        )
        assert result.risk_score == 50
        assert result.is_phishing is False

    def test_risk_score_negative_raises(self):
        with pytest.raises(InvalidBoundsError):
            PhishingResult(risk_score=-1, suspicious_urls=[], is_phishing=False, analysis_summary="")

    def test_risk_score_above_100_raises(self):
        with pytest.raises(InvalidBoundsError):
            PhishingResult(risk_score=101, suspicious_urls=[], is_phishing=False, analysis_summary="")

    def test_default_factory(self):
        result = PhishingResult.default()
        assert result.risk_score == 0
        assert result.suspicious_urls == []
        assert result.is_phishing is False
        assert result.analysis_summary == "No analysis performed"

    def test_to_dict_with_urls(self):
        url = SuspiciousUrl(url="http://evil.com", reasons=["phish"], risk_score=90)
        result = PhishingResult(
            risk_score=85,
            suspicious_urls=[url],
            is_phishing=True,
            analysis_summary="Likely phishing",
        )
        d = result.to_dict()
        assert d["risk_score"] == 85
        assert d["is_phishing"] is True
        assert len(d["suspicious_urls"]) == 1
        assert d["suspicious_urls"][0]["url"] == "http://evil.com"

    def test_to_dict_empty_urls(self):
        result = PhishingResult.default()
        d = result.to_dict()
        assert d["suspicious_urls"] == []

    def test_boundary_risk_score_zero(self):
        result = PhishingResult(risk_score=0, suspicious_urls=[], is_phishing=False, analysis_summary="")
        assert result.risk_score == 0

    def test_boundary_risk_score_100(self):
        result = PhishingResult(risk_score=100, suspicious_urls=[], is_phishing=True, analysis_summary="")
        assert result.risk_score == 100
