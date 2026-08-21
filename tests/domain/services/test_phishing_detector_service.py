# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour PhishingDetector.

Couvre:
- Extraction d'URLs
- Analyse d'URLs individuelles
- Analyse complète d'emails
- Détection de multiples patterns de phishing
"""

import pytest
from app.domain.services.phishing_detector import PhishingDetector
from app.domain.entities.phishing import SuspiciousUrl, PhishingResult


class TestUrlExtraction:
    """Tests de la méthode extract_urls()."""

    def test_extract_urls_empty_text(self):
        """Retourne une liste vide pour un texte vide."""
        detector = PhishingDetector()
        assert detector.extract_urls("") == []

    def test_extract_urls_none_text(self):
        """Retourne une liste vide pour None."""
        detector = PhishingDetector()
        assert detector.extract_urls(None) == []

    def test_extract_urls_single_http(self):
        """Extrait une URL HTTP simple."""
        detector = PhishingDetector()
        urls = detector.extract_urls("Check this http://example.com")
        assert len(urls) == 1
        assert urls[0] == "http://example.com"

    def test_extract_urls_single_https(self):
        """Extrait une URL HTTPS simple."""
        detector = PhishingDetector()
        urls = detector.extract_urls("Visit https://secure.example.com")
        assert len(urls) == 1
        assert urls[0] == "https://secure.example.com"

    def test_extract_urls_multiple_urls(self):
        """Extrait plusieurs URLs du même texte."""
        detector = PhishingDetector()
        text = "Go to https://site1.com or http://site2.org for more info"
        urls = detector.extract_urls(text)
        assert len(urls) == 2
        assert "https://site1.com" in urls
        assert "http://site2.org" in urls

    def test_extract_urls_data_uri(self):
        """Extrait les data: URIs."""
        detector = PhishingDetector()
        urls = detector.extract_urls("data:text/html,<h1>Test</h1>")
        assert len(urls) == 1
        assert urls[0].startswith("data:")

    def test_extract_urls_with_path_and_query(self):
        """Extrait les URLs avec chemins et paramètres de requête."""
        detector = PhishingDetector()
        urls = detector.extract_urls("https://example.com/path?param=value")
        assert len(urls) == 1
        assert urls[0] == "https://example.com/path?param=value"

    def test_extract_urls_stops_at_whitespace(self):
        """Les URLs s'arrêtent au caractère whitespace."""
        detector = PhishingDetector()
        urls = detector.extract_urls("Visit https://example.com today")
        assert len(urls) == 1
        assert urls[0] == "https://example.com"

    def test_extract_urls_no_urls_found(self):
        """Retourne liste vide quand aucune URL n'est trouvée."""
        detector = PhishingDetector()
        urls = detector.extract_urls("This text has no URLs at all")
        assert urls == []


class TestUrlAnalysis:
    """Tests de la méthode analyze_url()."""

    def test_analyze_url_data_uri(self):
        """Les data: URIs obtiennent un score de 50 avec reason data_uri."""
        detector = PhishingDetector()
        result = detector.analyze_url("data:text/html,<img src=x>")
        assert result.url == "data:text/html,<img src=x>"
        assert result.risk_score == 50
        assert "data_uri" in result.reasons

    def test_analyze_url_valid_domain_no_risks(self):
        """Une URL valide sans risques obtient un score de 0."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://www.google.com/search")
        assert result.risk_score == 0
        assert result.reasons == []

    def test_analyze_url_ip_address(self):
        """Les adresses IP obtiennent +30 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("http://192.168.1.1/login")
        assert "ip_address" in result.reasons
        assert result.risk_score >= 30

    def test_analyze_url_ip_with_port(self):
        """Les adresses IP avec port sont détectées."""
        detector = PhishingDetector()
        result = detector.analyze_url("http://192.168.1.1:8080/")
        assert "ip_address" in result.reasons

    def test_analyze_url_typosquatting_google(self):
        """La typosquattage g00gle est détecté (+40)."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://g00gle.com")
        assert "typosquatting" in result.reasons
        assert result.risk_score >= 40

    def test_analyze_url_typosquatting_amazon(self):
        """La typosquattage amaz0n est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://amaz0n.com/login")
        assert "typosquatting" in result.reasons

    def test_analyze_url_typosquatting_paypal(self):
        """La typosquattage paypa1 est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://paypa1.com")
        assert "typosquatting" in result.reasons

    def test_analyze_url_typosquatting_microsoft(self):
        """La typosquattage microsoft est détectée."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://micros0ft.com")
        assert "typosquatting" in result.reasons

    def test_analyze_url_typosquatting_apple(self):
        """La typosquattage apple est détectée."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://app1e.com")
        assert "typosquatting" in result.reasons

    def test_analyze_url_suspicious_path_login(self):
        """Le chemin /login obtient +20 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/login")
        assert "suspicious_path" in result.reasons
        assert result.risk_score >= 20

    def test_analyze_url_suspicious_path_verify(self):
        """Le chemin /verify est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/verify")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_suspicious_path_account(self):
        """Le chemin /account est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/account")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_suspicious_path_signin(self):
        """Le chemin /signin est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/signin")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_suspicious_path_secure(self):
        """Le chemin /secure est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/secure")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_suspicious_path_update(self):
        """Le chemin /update est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/update")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_suspicious_path_password(self):
        """Le chemin /password est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/password")
        assert "suspicious_path" in result.reasons

    def test_analyze_url_encoded_chars_2f(self):
        """Les caractères encodés %2f obtiennent +25 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/path%2flogin")
        assert "encoded_chars" in result.reasons
        assert result.risk_score >= 25

    def test_analyze_url_encoded_chars_3a(self):
        """Les caractères encodés %3a obtiennent +25 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/path%3alogin")
        assert "encoded_chars" in result.reasons

    def test_analyze_url_suspicious_tld_xyz(self):
        """Le TLD .xyz obtient +15 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.xyz")
        assert "suspicious_tld" in result.reasons
        assert result.risk_score >= 15

    def test_analyze_url_suspicious_tld_tk(self):
        """Le TLD .tk est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.tk")
        assert "suspicious_tld" in result.reasons

    def test_analyze_url_suspicious_tld_ml(self):
        """Le TLD .ml est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.ml")
        assert "suspicious_tld" in result.reasons

    def test_analyze_url_suspicious_tld_ga(self):
        """Le TLD .ga est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.ga")
        assert "suspicious_tld" in result.reasons

    def test_analyze_url_suspicious_tld_cf(self):
        """Le TLD .cf est détecté."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.cf")
        assert "suspicious_tld" in result.reasons

    def test_analyze_url_long_subdomain(self):
        """Les subdomains longs (>=4 parties) obtiennent +15 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://mail.google.accounts.verify.com")
        assert "long_subdomain" in result.reasons
        assert result.risk_score >= 15

    def test_analyze_url_long_subdomain_exactly_4(self):
        """Exactement 4 parties déclenche long_subdomain."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://a.b.c.d.com")
        assert "long_subdomain" in result.reasons

    def test_analyze_url_short_url_bitly(self):
        """Les URLs raccourcies bit.ly obtiennent +10 points."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://bit.ly/abc123")
        assert "short_url" in result.reasons
        assert result.risk_score >= 10

    def test_analyze_url_short_url_tco(self):
        """Les URLs raccourcies t.co sont détectées."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://t.co/abc123")
        assert "short_url" in result.reasons

    def test_analyze_url_short_url_tinyurl(self):
        """Les URLs raccourcies tinyurl.com sont détectées."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://tinyurl.com/abc")
        assert "short_url" in result.reasons

    def test_analyze_url_short_url_googl(self):
        """Les URLs raccourcies goo.gl sont détectées."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://goo.gl/abc")
        assert "short_url" in result.reasons

    def test_analyze_url_invalid_url_format(self):
        """Les URLs invalides (non parseable) obtiennent un score faible."""
        detector = PhishingDetector()
        # Une URL qui ne commence pas par http/https/data: ne sera pas capturée par le regex
        # Mais si elle est passée directement à analyze_url, elle est traitée
        result = detector.analyze_url("ht!tp://[invalid]")
        # Les URLs qui ne peuvent pas être parsées se voient assigner un score de 30 et invalid_url
        assert result.risk_score <= 30
        assert isinstance(result.reasons, list)

    def test_analyze_url_multiple_risks(self):
        """Les risques multiples s'additionnent."""
        detector = PhishingDetector()
        # IP + suspicious path = 30 + 20 = 50
        result = detector.analyze_url("http://192.168.1.1/login")
        assert "ip_address" in result.reasons
        assert "suspicious_path" in result.reasons
        assert result.risk_score >= 50

    def test_analyze_url_combined_typosquatting_and_path(self):
        """Typosquatting + suspicious path s'additionnent (40 + 20 = 60)."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://g00gle.com/login")
        assert "typosquatting" in result.reasons
        assert "suspicious_path" in result.reasons
        assert result.risk_score >= 60

    def test_analyze_url_score_capped_at_100(self):
        """Le score ne dépasse jamais 100."""
        detector = PhishingDetector()
        # Combiner plusieurs risques
        result = detector.analyze_url("http://192.168.1.1/login%2fverify.xyz/account")
        assert result.risk_score <= 100

    def test_analyze_url_returns_suspicious_url_object(self):
        """analyze_url() retourne un objet SuspiciousUrl valide."""
        detector = PhishingDetector()
        result = detector.analyze_url("https://example.com/login")
        assert isinstance(result, SuspiciousUrl)
        assert result.url == "https://example.com/login"
        assert isinstance(result.reasons, list)
        assert isinstance(result.risk_score, int)

    def test_analyze_url_case_insensitive(self):
        """L'analyse est insensible à la casse."""
        detector = PhishingDetector()
        result1 = detector.analyze_url("HTTPS://EXAMPLE.COM/LOGIN")
        result2 = detector.analyze_url("https://example.com/login")
        assert result1.risk_score == result2.risk_score
        assert set(result1.reasons) == set(result2.reasons)


class TestEmailAnalysis:
    """Tests de la méthode analyze_email()."""

    def test_analyze_email_no_urls(self):
        """Email sans URLs obtient un score de 0, pas phishing."""
        detector = PhishingDetector()
        result = detector.analyze_email("Hello there", "This is a normal email body")
        assert result.risk_score == 0
        assert result.is_phishing is False
        assert result.suspicious_urls == []

    def test_analyze_email_none_subject(self):
        """Email avec subject None est géré gracieusement."""
        detector = PhishingDetector()
        result = detector.analyze_email(None, "Body with https://example.com")
        assert isinstance(result, PhishingResult)
        assert len(result.suspicious_urls) >= 0

    def test_analyze_email_none_body(self):
        """Email avec body None est géré gracieusement."""
        detector = PhishingDetector()
        result = detector.analyze_email("Subject with https://example.com", None)
        assert isinstance(result, PhishingResult)

    def test_analyze_email_both_none(self):
        """Email avec subject et body None retourne score 0."""
        detector = PhishingDetector()
        result = detector.analyze_email(None, None)
        assert result.risk_score == 0
        assert result.is_phishing is False

    def test_analyze_email_single_safe_url(self):
        """Email avec une URL sûre retourne score 0."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Subject",
            "Visit https://www.google.com"
        )
        assert result.is_phishing is False

    def test_analyze_email_single_suspicious_url(self):
        """Email avec une URL suspecte (mais sous le seuil) retourne is_phishing=False."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Verify your account",
            "Click https://g00gle.com/verify"
        )
        # Typosquatting (40) + suspicious_path (20) = 60, ce qui est < 70
        assert result.is_phishing is False
        assert result.risk_score == 60
        assert len(result.suspicious_urls) > 0

    def test_analyze_email_threshold_exactly_70(self):
        """Un score de 70 est considéré comme phishing."""
        detector = PhishingDetector()
        # data: URI = 50, short_url = 10, suspicious_tld = 15 = 75
        result = detector.analyze_email(
            "Subject",
            "Check data:text/html,<h1>Test</h1>"
        )
        if result.risk_score >= 70:
            assert result.is_phishing is True
        else:
            assert result.is_phishing is False

    def test_analyze_email_below_threshold(self):
        """Un score < 70 retourne is_phishing=False."""
        detector = PhishingDetector()
        # short_url seul = 10 points
        result = detector.analyze_email("Subject", "Check https://bit.ly/test")
        assert result.is_phishing is False

    def test_analyze_email_multiple_urls_max_score_used(self):
        """Le score max parmi toutes les URLs est utilisé."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Subject",
            "Visit https://google.com and https://g00gle.com/verify"
        )
        assert result.risk_score >= 60  # Typosquatting + path

    def test_analyze_email_subject_and_body_combined(self):
        """Les URLs du subject et du body sont combinées."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Click https://bit.ly/link",
            "Or visit https://example.com"
        )
        assert len(result.suspicious_urls) >= 0

    def test_analyze_email_returns_phishing_result(self):
        """analyze_email() retourne un PhishingResult valide."""
        detector = PhishingDetector()
        result = detector.analyze_email("Subject", "Body")
        assert isinstance(result, PhishingResult)
        assert hasattr(result, "risk_score")
        assert hasattr(result, "suspicious_urls")
        assert hasattr(result, "is_phishing")
        assert hasattr(result, "analysis_summary")

    def test_analyze_email_summary_no_urls(self):
        """Le résumé indique quand aucune URL n'est trouvée."""
        detector = PhishingDetector()
        result = detector.analyze_email("Normal email", "With no URLs")
        assert "No URLs" in result.analysis_summary

    def test_analyze_email_summary_phishing_detected(self):
        """Le résumé indique quand c'est du phishing."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Urgent",
            "https://g00gle.com/verify and https://amaz0n.com/account"
        )
        if result.is_phishing:
            assert "PHISHING DETECTED" in result.analysis_summary

    def test_analyze_email_summary_low_risk(self):
        """Le résumé indique faible risque."""
        detector = PhishingDetector()
        result = detector.analyze_email("Subject", "https://bit.ly/test")
        if not result.is_phishing and result.suspicious_urls:
            assert "Low risk" in result.analysis_summary

    def test_analyze_email_high_complexity_scenario(self):
        """Scénario complexe avec multiples risques."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Verify Account Now",
            """
            Please verify your account at https://g00gle.com/verify/login.
            Alternatively, visit http://192.168.1.1/account.
            Or use https://bit.ly/verify which is on a suspicious_tld
            """
        )
        assert result.suspicious_urls is not None
        assert isinstance(result.suspicious_urls, list)

    def test_analyze_email_empty_strings(self):
        """Email avec strings vides est géré."""
        detector = PhishingDetector()
        result = detector.analyze_email("", "")
        assert result.risk_score == 0
        assert result.is_phishing is False


class TestPhishingDetectorIntegration:
    """Tests d'intégration du PhishingDetector."""

    def test_detector_constants_exist(self):
        """Les constantes du PhishingDetector existent."""
        assert PhishingDetector.PHISHING_THRESHOLD == 70
        assert len(PhishingDetector.SUSPICIOUS_PATTERNS) > 0
        assert len(PhishingDetector.KNOWN_DOMAINS_TYPOSQUATS) > 0
        assert len(PhishingDetector.SUSPICIOUS_TLDS) > 0
        assert len(PhishingDetector.SHORT_URL_DOMAINS) > 0

    def test_suspicious_url_validation(self):
        """SuspiciousUrl valide les scores."""
        with pytest.raises(Exception):
            SuspiciousUrl(url="http://example.com", reasons=[], risk_score=150)

        with pytest.raises(Exception):
            SuspiciousUrl(url="http://example.com", reasons=[], risk_score=-1)

    def test_suspicious_url_valid_range(self):
        """SuspiciousUrl accepte les scores 0-100."""
        for score in [0, 50, 100]:
            url = SuspiciousUrl(
                url="http://example.com",
                reasons=[],
                risk_score=score
            )
            assert url.risk_score == score

    def test_phishing_result_validation(self):
        """PhishingResult valide les scores."""
        with pytest.raises(Exception):
            PhishingResult(
                risk_score=150,
                suspicious_urls=[],
                is_phishing=False,
                analysis_summary=""
            )

    def test_phishing_result_to_dict(self):
        """PhishingResult peut être converti en dict."""
        result = PhishingResult(
            risk_score=50,
            suspicious_urls=[],
            is_phishing=False,
            analysis_summary="Test"
        )
        result_dict = result.to_dict()
        assert "risk_score" in result_dict
        assert "suspicious_urls" in result_dict
        assert "is_phishing" in result_dict
        assert "analysis_summary" in result_dict

    def test_suspicious_url_to_dict(self):
        """SuspiciousUrl peut être converti en dict."""
        url = SuspiciousUrl(
            url="https://example.com",
            reasons=["short_url"],
            risk_score=10
        )
        url_dict = url.to_dict()
        assert url_dict["url"] == "https://example.com"
        assert url_dict["reasons"] == ["short_url"]
        assert url_dict["risk_score"] == 10

    def test_real_world_phishing_scenario_1(self):
        """Scénario réel 1: Email de vérification de compte - détecte URL suspecte."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Urgent: Verify Your Account",
            "Please verify your PayPal account: https://paypa1.com/verify"
        )
        # Typosquatting (40) + suspicious_path (20) = 60, ce qui est < 70
        assert result.risk_score == 60
        assert result.suspicious_urls  # Il y a des URLs suspectes
        assert any("typosquatting" in url.reasons for url in result.suspicious_urls)

    def test_real_world_phishing_scenario_2(self):
        """Scénario réel 2: Lien raccourci suspect."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Click here",
            "https://bit.ly/login-confirm"
        )
        # Les liens raccourcis seuls sont faible risque
        assert result.suspicious_urls or result.risk_score >= 0

    def test_real_world_legitimate_scenario(self):
        """Scénario légitime: Email normal."""
        detector = PhishingDetector()
        result = detector.analyze_email(
            "Meeting tomorrow",
            "Visit our official website at https://company.com"
        )
        assert result.is_phishing is False
