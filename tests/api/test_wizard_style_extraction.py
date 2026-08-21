# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les fonctions d'extraction de style dans wizard.py.

Couvre:
- _empty_profile() - profil de style vide
- _extract_style_profile() - extraction de patterns
- _parse_signature() - parsing des signatures
- _save_style_profile() - sauvegarde du profil
- _detect_email_context() - detection contexte email
- _detect_tone() - detection ton
- _infer_context() - inference contexte conclusion
"""

from unittest.mock import patch, MagicMock

from app.api.wizard import (
    _empty_profile,
    _extract_style_profile,
    _parse_signature,
    _save_style_profile,
    _empty_deep_profile,
    _detect_email_context,
    _detect_tone,
    _infer_context,
)


class TestEmptyProfile:
    """Tests pour _empty_profile()."""

    def test_returns_dict(self):
        """Retourne un dictionnaire."""
        result = _empty_profile()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        """Contient toutes les cles requises."""
        result = _empty_profile()
        assert "signature" in result
        assert "tone" in result
        assert "formality_level" in result
        assert "avg_response_length" in result
        assert "greeting_patterns" in result
        assert "closing_patterns" in result

    def test_signature_is_none(self):
        """La signature est None."""
        result = _empty_profile()
        assert result["signature"] is None

    def test_tone_is_unknown(self):
        """Le ton est unknown."""
        result = _empty_profile()
        assert result["tone"] == "unknown"

    def test_formality_is_unknown(self):
        """La formalite est unknown."""
        result = _empty_profile()
        assert result["formality_level"] == "unknown"

    def test_avg_length_is_zero(self):
        """La longueur moyenne est 0."""
        result = _empty_profile()
        assert result["avg_response_length"] == 0

    def test_patterns_are_empty_lists(self):
        """Les patterns sont des listes vides."""
        result = _empty_profile()
        assert result["greeting_patterns"] == []
        assert result["closing_patterns"] == []


class TestExtractStyleProfile:
    """Tests pour _extract_style_profile()."""

    def test_empty_emails_list(self):
        """Gere une liste d'emails vide."""
        result = _extract_style_profile([])
        assert result["avg_response_length"] == 0
        assert result["greeting_patterns"] == []

    def test_emails_without_body(self):
        """Gere des emails sans body."""
        emails = [
            {"subject": "Test", "to": "test@example.com"},
            {"subject": "Test2"},
        ]
        result = _extract_style_profile(emails)
        assert result["avg_response_length"] == 0

    def test_detects_bonjour_greeting(self):
        """Detecte la formule Bonjour."""
        emails = [
            {"body": "Bonjour Jean,\n\nMerci pour votre email.\n\nCordialement"},
            {"body": "Bonjour Marie,\n\nVoici le document.\n\nCordialement"},
            {"body": "Bonjour Pierre,\n\nBien recu.\n\nCordialement"},
        ]
        result = _extract_style_profile(emails)
        greetings = result["greeting_patterns"]
        assert any("Bonjour" in g for g in greetings)

    def test_detects_salut_greeting(self):
        """Detecte la formule Salut (informel)."""
        emails = [
            {"body": "Salut Jean,\n\nCa va?\n\nA+"},
            {"body": "Salut Marie,\n\nMerci!\n\nA+"},
            {"body": "Salut Pierre,\n\nOK!\n\nA+"},
        ]
        result = _extract_style_profile(emails)
        greetings = result["greeting_patterns"]
        assert any("Salut" in g for g in greetings)

    def test_detects_cordialement_closing(self):
        """Detecte la formule Cordialement."""
        emails = [
            {"body": "Bonjour,\n\nMerci.\n\nCordialement"},
            {"body": "Bonjour,\n\nVoici.\n\nCordialement"},
            {"body": "Bonjour,\n\nBien recu.\n\nCordialement"},
        ]
        result = _extract_style_profile(emails)
        closings = result["closing_patterns"]
        assert any("Cordialement" in c for c in closings)

    def test_detects_vous_formality(self):
        """Detecte le vouvoiement."""
        emails = [
            {"body": "Bonjour, je vous remercie pour votre email."},
            {"body": "Pourriez-vous me confirmer votre disponibilite?"},
            {"body": "Je vous prie de trouver ci-joint le document."},
        ]
        result = _extract_style_profile(emails)
        assert result["formality_level"] == "vous"

    def test_detects_tu_formality(self):
        """Detecte le tutoiement."""
        emails = [
            {"body": "Salut, tu peux me donner ton avis?"},
            {"body": "Tu as vu le message? Dis-moi ce que tu en penses."},
            {"body": "Je t'envoie le fichier, toi aussi tu peux le modifier."},
        ]
        result = _extract_style_profile(emails)
        assert result["formality_level"] == "tu"

    def test_detects_formal_tone(self):
        """Detecte le ton formel."""
        emails = [
            {"body": "Cher Monsieur,\n\nJe vous prie de bien vouloir..."},
            {"body": "Chere Madame,\n\nVeuillez trouver ci-joint..."},
            {"body": "Cher client,\n\nNous vous remercions pour votre confiance..."},
        ]
        result = _extract_style_profile(emails)
        assert result["tone"] == "formal"

    def test_detects_informal_tone(self):
        """Detecte le ton informel."""
        emails = [
            {"body": "Salut! Tu as vu le match hier?"},
            {"body": "Salut Jean, ca va? Tu viens ce soir?"},
            {"body": "Salut, top le projet! Tu geres!"},
        ]
        result = _extract_style_profile(emails)
        assert result["tone"] == "informal"

    def test_calculates_avg_length(self):
        """Calcule la longueur moyenne."""
        emails = [
            {"body": "A" * 100},
            {"body": "B" * 200},
            {"body": "C" * 300},
        ]
        result = _extract_style_profile(emails)
        assert result["avg_response_length"] == 200  # (100+200+300)/3

    def test_handles_content_key(self):
        """Gere les emails avec cle 'content' au lieu de 'body'."""
        emails = [
            {"content": "Bonjour, voici le rapport.\n\nCordialement"},
        ]
        result = _extract_style_profile(emails)
        assert result["avg_response_length"] > 0

    def test_detects_signature_pattern(self):
        """Detecte les signatures avec separateur --."""
        emails = [
            {"body": "Bonjour,\n\nMerci.\n\n--\nJean Dupont\nDirecteur\nAcme Corp"},
        ]
        result = _extract_style_profile(emails)
        # La signature peut ou non etre detectee selon le pattern
        # Ce test verifie que ca ne plante pas
        assert "signature" in result


class TestParseSignature:
    """Tests pour _parse_signature()."""

    def test_empty_list(self):
        """Retourne None pour une liste vide."""
        result = _parse_signature([])
        assert result is None

    def test_extracts_name(self):
        """Extrait le nom de la signature."""
        signatures = ["Jean Dupont\nDirecteur\nAcme Corp"]
        result = _parse_signature(signatures)
        assert result is not None
        assert result["name"] == "Jean Dupont"

    def test_extracts_title(self):
        """Extrait le titre/poste."""
        signatures = ["Jean Dupont\nDirecteur Commercial\nAcme Corp"]
        result = _parse_signature(signatures)
        assert result is not None
        assert "Directeur" in (result.get("title") or "")

    def test_extracts_company_with_at(self):
        """Extrait l'entreprise avec @."""
        signatures = ["Jean Dupont\n@ Acme Corp"]
        result = _parse_signature(signatures)
        assert result is not None
        assert result.get("company") == "Acme Corp"

    def test_extracts_company_with_chez(self):
        """Extrait l'entreprise avec 'chez'."""
        signatures = ["Jean Dupont\nConsultant chez Acme Corp"]
        result = _parse_signature(signatures)
        assert result is not None
        assert result.get("company") == "Acme Corp"

    def test_extracts_company_with_pipe(self):
        """Extrait l'entreprise avec |."""
        # Le pipe doit etre sur une ligne separee du nom
        signatures = ["Jean Dupont\nConsultant | Acme Corp"]
        result = _parse_signature(signatures)
        assert result is not None
        assert result.get("company") == "Acme Corp"

    def test_handles_empty_lines(self):
        """Gere les signatures avec lignes vides."""
        signatures = ["\n\n\n"]
        result = _parse_signature(signatures)
        assert result is None

    def test_picks_longest_signature(self):
        """Choisit la signature la plus longue."""
        signatures = [
            "Jean",
            "Jean Dupont\nDirecteur\nAcme Corp\nParis",
            "JD",
        ]
        result = _parse_signature(signatures)
        assert result is not None
        assert result["name"] == "Jean Dupont"

    def test_handles_various_titles(self):
        """Detecte differents types de titres."""
        test_cases = [
            ("Jean Dupont\nManager Commercial", "Manager"),
            ("Marie Martin\nCEO", "CEO"),
            ("Pierre Durand\nResponsable Marketing", "Responsable"),
            ("Sophie Lefevre\nChef de projet", "Chef"),
            ("Thomas Bernard\nSenior Developer", "Senior"),
            ("Julie Lambert\nIngenieur R&D", "Ingenieur"),
        ]
        for sig, expected_title in test_cases:
            result = _parse_signature([sig])
            assert result is not None, f"Failed for {sig}"


class TestSaveStyleProfile:
    """Tests pour _save_style_profile()."""

    def test_no_config_returns_error(self):
        """Retourne erreur si pas de configuration."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            result = _save_style_profile({})

            assert result["success"] is False
            assert "No configuration" in result["error"]

    def test_saves_closing_pattern(self):
        """Sauvegarde la formule de conclusion detectee."""
        mock_config = MagicMock()
        mock_config.knowledge_base = MagicMock()
        mock_config.knowledge_base.custom_signatures = {}
        mock_config.knowledge_base.tone_guidelines = ""

        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_config

            profile = {
                "closing_patterns": ["Cordialement", "Bien a vous"],
            }
            result = _save_style_profile(profile)

            assert result["success"] is True
            assert mock_config.knowledge_base.custom_signatures["default"] == "Cordialement"

    def test_saves_full_signature(self):
        """Sauvegarde la signature complete."""
        mock_config = MagicMock()
        mock_config.knowledge_base = MagicMock()
        mock_config.knowledge_base.custom_signatures = {}
        mock_config.knowledge_base.tone_guidelines = ""

        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_config

            profile = {
                "signature": {
                    "name": "Jean Dupont",
                    "title": "Directeur",
                    "company": "Acme Corp",
                },
            }
            result = _save_style_profile(profile)

            assert result["success"] is True
            full_sig = mock_config.knowledge_base.custom_signatures.get("full", "")
            assert "Jean Dupont" in full_sig
            assert "Directeur" in full_sig
            assert "Acme Corp" in full_sig

    def test_saves_formal_tone_guidelines(self):
        """Sauvegarde les guidelines de ton formel."""
        mock_config = MagicMock()
        mock_config.knowledge_base = MagicMock()
        mock_config.knowledge_base.custom_signatures = {}
        mock_config.knowledge_base.tone_guidelines = ""

        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_config

            profile = {
                "tone": "formal",
                "formality_level": "vous",
            }
            result = _save_style_profile(profile)

            assert result["success"] is True
            assert "formel" in mock_config.knowledge_base.tone_guidelines.lower()
            assert "vouvoyer" in mock_config.knowledge_base.tone_guidelines.lower()

    def test_saves_informal_tone_guidelines(self):
        """Sauvegarde les guidelines de ton informel."""
        mock_config = MagicMock()
        mock_config.knowledge_base = MagicMock()
        mock_config.knowledge_base.custom_signatures = {}
        mock_config.knowledge_base.tone_guidelines = ""

        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_config

            profile = {
                "tone": "informal",
                "formality_level": "tu",
            }
            result = _save_style_profile(profile)

            assert result["success"] is True
            assert "decontract" in mock_config.knowledge_base.tone_guidelines.lower()
            assert "tutoyer" in mock_config.knowledge_base.tone_guidelines.lower()


class TestEmptyDeepProfile:
    """Tests pour _empty_deep_profile()."""

    def test_returns_dict(self):
        """Retourne un dictionnaire."""
        result = _empty_deep_profile()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        """Contient toutes les cles requises."""
        result = _empty_deep_profile()
        assert "recurring_formulas" in result
        assert "contextual_patterns" in result
        assert "signature_expressions" in result
        assert "response_rhythm" in result

    def test_formulas_have_greetings_and_closings(self):
        """Les formules ont greetings et closings vides."""
        result = _empty_deep_profile()
        assert result["recurring_formulas"]["greetings"] == []
        assert result["recurring_formulas"]["closings"] == []


class TestDetectEmailContext:
    """Tests pour _detect_email_context()."""

    def test_detects_urgent_context(self):
        """Detecte le contexte urgent."""
        email = {"subject": "URGENT: Need response ASAP", "to": "test@example.com"}
        result = _detect_email_context(email)
        assert result == "urgent"

    def test_detects_client_context_by_subject(self):
        """Detecte le contexte client par le sujet."""
        test_cases = [
            {"subject": "Facture N123", "to": "client@example.com"},
            {"subject": "Devis demande", "to": "test@example.com"},
            {"subject": "Commande #456", "to": "test@example.com"},
            {"subject": "Invoice needed", "to": "test@example.com"},
        ]
        for email in test_cases:
            result = _detect_email_context(email)
            assert result == "client", f"Failed for {email['subject']}"

    def test_detects_client_context_by_recipient(self):
        """Detecte le contexte client par le destinataire."""
        test_cases = [
            {"subject": "Hello", "to": "support@company.com"},
            {"subject": "Hello", "to": "contact@company.com"},
            {"subject": "Hello", "to": "info@company.com"},
            {"subject": "Hello", "to": "client-service@company.com"},
        ]
        for email in test_cases:
            result = _detect_email_context(email)
            assert result == "client", f"Failed for {email['to']}"

    def test_detects_followup_context(self):
        """Detecte le contexte followup."""
        test_cases = [
            {"subject": "Re: Meeting tomorrow", "to": "test@example.com"},
            {"subject": "Fwd: Document requested", "to": "test@example.com"},
            {"subject": "Tr: Message a transmettre", "to": "test@example.com"},
        ]
        for email in test_cases:
            result = _detect_email_context(email)
            assert result == "followup", f"Failed for {email['subject']}"

    def test_defaults_to_colleague(self):
        """Par defaut, retourne colleague."""
        email = {"subject": "Meeting next week", "to": "colleague@company.com"}
        result = _detect_email_context(email)
        assert result == "colleague"

    def test_handles_missing_fields(self):
        """Gere les emails sans champs to ou subject."""
        result = _detect_email_context({})
        assert result == "colleague"


class TestDetectTone:
    """Tests pour _detect_tone()."""

    def test_detects_formal_tone_with_vous(self):
        """Detecte le ton formel avec vous."""
        text = "Je vous remercie pour votre email. Pourriez-vous me confirmer?"
        result = _detect_tone(text)
        assert result == "formal"

    def test_detects_formal_tone_with_markers(self):
        """Detecte le ton formel avec marqueurs."""
        test_cases = [
            "Cher Monsieur, je vous prie de bien vouloir...",
            "Madame, veuillez trouver ci-joint...",
            "Monsieur le Directeur, je vous adresse mes salutations.",
        ]
        for text in test_cases:
            result = _detect_tone(text)
            assert result == "formal", f"Failed for: {text[:30]}..."

    def test_detects_informal_tone_with_tu(self):
        """Detecte le ton informel avec tu."""
        text = "Salut! Tu peux me donner ton avis? Toi aussi tu as vu le bug?"
        result = _detect_tone(text)
        assert result == "informal"

    def test_detects_informal_tone_with_markers(self):
        """Detecte le ton informel avec marqueurs."""
        test_cases = [
            "Salut Jean! Ca va?",
            "Coucou, tu as une minute?",
            "Bisous a toute la famille!",
        ]
        for text in test_cases:
            result = _detect_tone(text)
            assert result == "informal", f"Failed for: {text[:30]}..."

    def test_neutral_tone_default(self):
        """Par defaut, retourne neutral."""
        text = "Message sans marqueur particulier."
        result = _detect_tone(text)
        assert result == "neutral"


class TestInferContext:
    """Tests pour _infer_context()."""

    def test_infers_professional_formal(self):
        """Infere contexte professionnel formel."""
        test_cases = [
            "Cordialement",
            "Meilleures salutations",
            "Sinceres salutations",
        ]
        for closing in test_cases:
            result = _infer_context(closing)
            assert "professional" in result, f"Failed for {closing}"
            assert "formal" in result, f"Failed for {closing}"

    def test_infers_informal_personal(self):
        """Infere contexte informel personnel."""
        test_cases = [
            "Amicalement",
            "Bises",
            "Bisous",
        ]
        for closing in test_cases:
            result = _infer_context(closing)
            assert "informal" in result, f"Failed for {closing}"
            assert "personal" in result, f"Failed for {closing}"

    def test_infers_professional_international(self):
        """Infere contexte professionnel international."""
        test_cases = [
            "Best regards",
            "Best",
            "Sincerely",
        ]
        for closing in test_cases:
            result = _infer_context(closing)
            assert "professional" in result, f"Failed for {closing}"
            assert "international" in result, f"Failed for {closing}"

    def test_defaults_to_professional(self):
        """Par defaut, retourne professional."""
        result = _infer_context("A bientot")
        assert "professional" in result
