# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Service de détection de phishing - logique pure sans I/O."""

import re
from typing import List
from urllib.parse import urlparse, unquote

from app.domain.entities.phishing import SuspiciousUrl, PhishingResult


class PhishingDetector:
    """Service de détection de phishing - logique pure sans I/O."""

    PHISHING_THRESHOLD: int = 70

    SUSPICIOUS_PATTERNS: tuple = (
        r"/login",
        r"/verify",
        r"/account",
        r"/signin",
        r"/secure",
        r"/update",
        r"/confirm",
        r"/validate",
        r"/authenticate",
        r"/password",
    )

    KNOWN_DOMAINS_TYPOSQUATS: dict = {
        "google": ("g00gle", "gooogle", "googl3", "go0gle", "goog1e"),
        "amazon": ("amaz0n", "amazn", "amazonn", "amzon", "amaz1n"),
        "paypal": ("paypa1", "paypai", "paypa1", "paypall", "payp4l"),
        "microsoft": ("micros0ft", "microsft", "mircosoft", "m1crosoft"),
        "apple": ("app1e", "appie", "aple", "applle"),
        "facebook": ("faceb00k", "facebok", "faecbook", "faceb0ok"),
        "netflix": ("netf1ix", "netfiix", "netfl1x", "n3tflix"),
        "instagram": ("1nstagram", "instagran", "instgram", "lnstagram"),
        "twitter": ("tw1tter", "twiter", "twtter", "twltter"),
        "linkedin": ("linkedln", "l1nkedin", "link3din", "1inkedin"),
    }

    SUSPICIOUS_TLDS: tuple = (
        ".xyz", ".tk", ".ml", ".ga", ".cf", ".gq",
        ".top", ".club", ".work", ".loan", ".click"
    )

    SHORT_URL_DOMAINS: tuple = (
        "bit.ly", "t.co", "tinyurl.com", "goo.gl",
        "ow.ly", "is.gd", "buff.ly", "adf.ly"
    )

    # Limite à 2048 caractères max pour éviter ReDoS
    MAX_URL_LENGTH = 2048
    URL_REGEX = re.compile(
        r'https?://[^\s<>"\']{1,2048}|'
        r'data:[^\s<>"\']{1,2048}',
        re.IGNORECASE
    )

    def extract_urls(self, text: str) -> List[str]:
        if not text:
            return []
        return self.URL_REGEX.findall(text)

    def analyze_url(self, url: str) -> SuspiciousUrl:
        if url.startswith("data:"):
            return SuspiciousUrl(url=url, reasons=["data_uri"], risk_score=50)

        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path.lower()
            decoded_path = unquote(path)
        except Exception:
            return SuspiciousUrl(url=url, reasons=["invalid_url"], risk_score=30)

        reasons, score = self._evaluate_url_risks(domain, path, decoded_path)
        return SuspiciousUrl(url=url, reasons=reasons, risk_score=min(score, 100))

    def _evaluate_url_risks(self, domain: str, path: str, decoded_path: str) -> tuple:
        """Évalue les risques d'une URL et retourne (reasons, score)."""
        reasons: List[str] = []
        score = 0

        checks = [
            (self._is_ip_address(domain), "ip_address", 30),
            (self._check_typosquatting(domain), "typosquatting", 40),
            (self._has_suspicious_path(path), "suspicious_path", 20),
            (self._has_encoded_chars(path, decoded_path), "encoded_chars", 25),
            (self._has_suspicious_tld(domain), "suspicious_tld", 15),
            (self._has_long_subdomain(domain), "long_subdomain", 15),
            (self._is_short_url(domain), "short_url", 10),
        ]

        for condition, reason, points in checks:
            if condition:
                reasons.append(reason)
                score += points

        return reasons, score

    def _has_encoded_chars(self, path: str, decoded_path: str) -> bool:
        """Vérifie la présence de caractères encodés suspects."""
        return decoded_path != path and ("%2f" in path.lower() or "%3a" in path.lower())

    def analyze_email(self, subject: str, body: str) -> PhishingResult:
        # Validation robuste des entrées None
        safe_subject = subject if subject is not None else ""
        safe_body = body if body is not None else ""
        combined_text = f"{safe_subject} {safe_body}"
        urls = self.extract_urls(combined_text)

        if not urls:
            return PhishingResult(
                risk_score=0,
                suspicious_urls=[],
                is_phishing=False,
                analysis_summary="No URLs found in email"
            )

        suspicious_urls: List[SuspiciousUrl] = []
        max_score = 0

        for url in urls:
            analysis = self.analyze_url(url)
            if analysis.risk_score > 0:
                suspicious_urls.append(analysis)
            max_score = max(max_score, analysis.risk_score)

        is_phishing = max_score >= self.PHISHING_THRESHOLD
        summary = self._generate_summary(suspicious_urls, is_phishing)

        return PhishingResult(
            risk_score=max_score,
            suspicious_urls=suspicious_urls,
            is_phishing=is_phishing,
            analysis_summary=summary
        )

    def _is_ip_address(self, domain: str) -> bool:
        domain_without_port = domain.split(":")[0]
        parts = domain_without_port.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def _check_typosquatting(self, domain: str) -> bool:
        domain_base = domain.split(":")[0]
        return any(
            typo in domain_base
            for typos in self.KNOWN_DOMAINS_TYPOSQUATS.values()
            for typo in typos
        )

    def _has_suspicious_path(self, path: str) -> bool:
        return any(
            re.search(pattern, path, re.IGNORECASE)
            for pattern in self.SUSPICIOUS_PATTERNS
        )

    def _has_suspicious_tld(self, domain: str) -> bool:
        return any(domain.endswith(tld) for tld in self.SUSPICIOUS_TLDS)

    def _has_long_subdomain(self, domain: str) -> bool:
        parts = domain.split(".")
        return len(parts) >= 4

    def _is_short_url(self, domain: str) -> bool:
        return any(
            domain == short_domain or domain.endswith("." + short_domain)
            for short_domain in self.SHORT_URL_DOMAINS
        )

    def _generate_summary(self, suspicious_urls: List[SuspiciousUrl], is_phishing: bool) -> str:
        if not suspicious_urls:
            return "Email appears safe - no suspicious URLs detected"
        if is_phishing:
            return f"PHISHING DETECTED: {len(suspicious_urls)} suspicious URL(s) found"
        return f"Low risk: {len(suspicious_urls)} URL(s) with minor concerns"
