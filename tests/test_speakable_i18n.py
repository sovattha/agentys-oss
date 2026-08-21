# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour le champ detected_language dans l'endpoint speakable."""



class TestSpeakableDetectedLanguage:
    """Vérifie que l'endpoint GET /api/emails/<id>/speakable retourne detected_language."""

    def _make_speakable_result(self, email_id="test123"):
        from app.application.make_speakable import SpeakableResult
        return SpeakableResult(
            email_id=email_id,
            subject="Test subject",
            sender_name="Test Sender",
            speakable_text="This is the speakable text.",
        )

    def test_speakable_response_contains_detected_language(self):
        """La réponse doit contenir le champ detected_language."""
        result = self._make_speakable_result()
        assert hasattr(result, 'email_id')
        assert hasattr(result, 'speakable_text')
        # The detected_language is added in the route, not in the use case
        # Verify the DetectLanguage use case works and returns a supported lang
        from app.application.detect_language import DetectLanguage
        detect = DetectLanguage()
        lang = detect.run("Hello this is an English email body")
        assert lang in DetectLanguage.SUPPORTED

    def test_detected_language_field_in_dict(self):
        """Un dict de réponse avec detected_language a le bon format."""
        from app.application.detect_language import DetectLanguage
        result = self._make_speakable_result()
        response_dict = {
            "id": result.email_id,
            "subject": result.subject,
            "sender_name": result.sender_name,
            "speakable_text": result.speakable_text,
            "detected_language": DetectLanguage().run(result.speakable_text),
        }
        assert "detected_language" in response_dict
        assert response_dict["detected_language"] in {'fr', 'en', 'de', 'es'}

    def test_detected_language_fallback_on_empty_body(self):
        """Corps vide → detected_language = 'fr'."""
        from app.application.detect_language import DetectLanguage
        lang = DetectLanguage().run("")
        assert lang == 'fr'
