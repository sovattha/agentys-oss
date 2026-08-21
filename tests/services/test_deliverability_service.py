"""Tests pour deliverability_service (#192).

Le score est heuristique ; les tests se concentrent sur :
1. Les cas clairs de spam (score bas).
2. Les emails professionnels propres (score haut).
3. La robustesse aux inputs invalides (jamais d'exception).
"""

import pytest

from app.services.deliverability_service import (
    DeliverabilityReport,
    Severity,
    score_draft,
)


class TestCleanDrafts:
    def test_plain_professional_email_scores_high(self):
        r = score_draft(
            subject="Proposition de rendez-vous semaine prochaine",
            body=(
                "Bonjour Marc,\n\n"
                "Suite à notre discussion, seriez-vous disponible mardi ou "
                "jeudi après-midi pour un point de 30 minutes ?\n\n"
                "Merci d'avance."
            ),
        )
        assert r.score >= 90
        assert all(i.severity != Severity.HIGH for i in r.issues)

    def test_report_serializable(self):
        r = score_draft("Hello", "Bonjour.")
        d = r.to_dict()
        assert "score" in d
        assert isinstance(d["issues"], list)


class TestSubjectIssues:
    def test_empty_subject_is_high_severity(self):
        r = score_draft("", "Body normal.")
        assert any(i.code == "subject_empty" and i.severity == Severity.HIGH for i in r.issues)

    def test_subject_too_long_is_info(self):
        r = score_draft("A" * 120, "Body normal.")
        assert any(i.code == "subject_too_long" for i in r.issues)

    def test_fake_re_prefix_flagged(self):
        r = score_draft("Re: Re: Re: your order", "Body.")
        assert any(i.code == "fake_re_prefix" for i in r.issues)
        assert r.score < 80

    def test_subject_shouting(self):
        r = score_draft("URGENT ACTION REQUIRED NOW", "Body.")
        assert any(i.code == "subject_shouting" for i in r.issues)


class TestBodyIssues:
    def test_excessive_exclamations(self):
        r = score_draft("Hello", "Wow!!! Amazing!!! Buy now!!! Click!!!")
        assert any(i.code == "excessive_exclamations" for i in r.issues)

    def test_excessive_uppercase(self):
        # 5 mots tous en MAJ.
        r = score_draft("Hello", "GAGNEZ GRATUIT ARGENT FACILE URGENT.")
        codes = {i.code for i in r.issues}
        # Peut déclencher soit excessive_uppercase soit spam_trigger_words.
        assert "excessive_uppercase" in codes or "spam_trigger_words" in codes

    def test_spam_trigger_words_low_severity_for_single(self):
        r = score_draft("Discount available", "We have a free trial for you.")
        trig = [i for i in r.issues if i.code == "spam_trigger_words"]
        assert len(trig) == 1
        assert trig[0].severity == Severity.WARN

    def test_spam_trigger_words_high_severity_for_multiple(self):
        r = score_draft(
            "Discount",
            "Free offer: click here and gagnez immediately. Limited time.",
        )
        trig = [i for i in r.issues if i.code == "spam_trigger_words"]
        assert len(trig) == 1
        assert trig[0].severity == Severity.HIGH

    def test_excessive_links(self):
        body = "See " + " ".join([f"https://example.com/{i}" for i in range(8)])
        r = score_draft("Resources", body)
        codes = {i.code for i in r.issues}
        assert "excessive_links" in codes

    def test_empty_body_is_high(self):
        r = score_draft("Question", "")
        assert any(i.code == "body_empty" and i.severity == Severity.HIGH for i in r.issues)


class TestRobustness:
    @pytest.mark.parametrize("bad_input", [None, 42, b"bytes", {"nope": 1}])
    def test_never_raises_on_bad_inputs(self, bad_input):
        r = score_draft(bad_input, bad_input)  # type: ignore[arg-type]
        assert isinstance(r, DeliverabilityReport)
        assert 0 <= r.score <= 100


class TestScoring:
    def test_penalties_compose(self):
        # Plusieurs issues composées → score baisse nettement.
        r = score_draft(
            "URGENT ACTION REQUIRED NOW",
            "Free offer!!! Click here!!! Gagnez!!!",
        )
        assert r.score < 70
        assert len(r.issues) >= 3

    def test_score_floor_is_zero(self):
        r = score_draft(
            "",
            "FREE FREE FREE!!! CLICK HERE!!! GAGNEZ GRATUIT ARGENT URGENT "
            + " ".join(f"https://bad.example/{i}" for i in range(10)),
        )
        assert r.score == 0

    def test_is_risky_below_threshold(self):
        r = DeliverabilityReport(score=40)
        assert r.is_risky(50)
        assert not r.is_risky(30)
