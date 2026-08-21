"""Quick verification tests for the promo classification fix."""

import pytest
from unittest.mock import Mock
from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import get_default_labels


@pytest.fixture
def uc():
    labels = get_default_labels()
    llm = Mock()
    llm.complete.return_value = Mock(
        content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
    )
    return LabelEmailUseCase(llm=llm, labels=labels, rules=[])


def _label(uc, sender, subject, body):
    email_data = {
        "sender": sender,
        "subject": subject,
        "body": body,
        "recipients": ["me@test.com"],
        "is_cc": False,
    }
    results = uc._apply_builtin_rules(email_data)
    return results[0][0] if results else None


class TestPromoFix:
    def test_rencontresportive_promo_is_noise(self, uc):
        label = _label(
            uc,
            "contact@rencontresportive.com",
            "PROMO TOTALE !",
            "Ce contenu ne s affiche pas bien ? Voyez-le dans votre navigateur\n"
            "rabais de 20% sur tous les forfaits\n"
            "code promo Paques26\n"
            "Rendez-vous sur la page du forfait\n"
            "Vous avez deja la Totale ?",
        )
        assert label == "Noise"

    def test_french_promo_rabais_code_is_noise(self, uc):
        label = _label(
            uc,
            "offres@boutique.fr",
            "Offre speciale printemps",
            "Profitez d un rabais de 30% avec le code promo SPRING30\n"
            "Vous cherchez le cadeau parfait ?",
        )
        assert label == "Noise"

    def test_promo_subject_is_noise(self, uc):
        label = _label(uc, "sales@store.com", "Grande promo ete", "Decouvrez nos offres.")
        assert label == "Noise"

    def test_genuine_question_stays_action(self, uc):
        label = _label(
            uc, "alice@company.com", "Re: Rapport Q1", "Avez-vous deja envoye le rapport ?"
        )
        assert label == "Action"

    def test_legitimate_code_promo_mention_stays_action(self, uc):
        label = _label(
            uc,
            "alice@company.com",
            "Question sur le code promo",
            "Bonjour, est-ce que le code promo du client XYZ a ete active ?",
        )
        assert label == "Action"

    def test_short_genuine_question_stays_action(self, uc):
        label = _label(uc, "bob@company.com", "Re: Dispo", "ok?")
        assert label == "Action"

    def test_english_promo_still_noise(self, uc):
        label = _label(uc, "deals@store.com", "Flash sale - 50% off", "Shop now and save big")
        assert label == "Noise"

    def test_view_in_browser_regex(self):
        assert LabelEmailUseCase.VIEW_IN_BROWSER_RE.search("Voyez-le dans votre navigateur")
        assert LabelEmailUseCase.VIEW_IN_BROWSER_RE.search("voir dans votre navigateur")

    def test_marketing_cta_regex(self):
        assert LabelEmailUseCase.MARKETING_CTA_RE.search("Rendez-vous sur la page du forfait")
        assert not LabelEmailUseCase.MARKETING_CTA_RE.search("J ai un rendez-vous demain")

    def test_marketing_question_regex(self):
        assert LabelEmailUseCase.MARKETING_QUESTION_RE.search("Vous avez deja la Totale ?")
        assert not LabelEmailUseCase.MARKETING_QUESTION_RE.search(
            "Avez-vous deja envoye le rapport ?"
        )
