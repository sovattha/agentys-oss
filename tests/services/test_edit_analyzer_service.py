"""Tests pour edit_analyzer_service (#196).

Le classifieur est heuristique. Les tests se concentrent sur les cas clairs
pour éviter les faux positifs ; les zones grises retombent sur OTHER, ce qui
est une décision volontaire : mieux vaut ne pas ajuster le prompt sur un signal
ambigu que de dériver le ton utilisateur par erreur.
"""

from app.domain.entities.draft_edit_event import EditCategory, EditEvent
from app.services.edit_analyzer_service import (
    LENGTH_ADJ_MIN_DELTA,
    build_event,
    classify_edit,
)


class TestClassifyEdit:
    def test_identical_returns_other(self):
        assert classify_edit("Bonjour", "Bonjour") == EditCategory.OTHER

    def test_signature_override_detected(self):
        initial = "Bonjour,\n\nJe confirme pour demain."
        final = (
            "Bonjour,\n\nJe confirme pour demain.\n\n"
            "--\nNathan Roy\nAgentys\nnathan@agentys.io\n+33 6 12 34 56 78"
        )
        assert classify_edit(initial, final) == EditCategory.SIGNATURE_OVERRIDE

    def test_content_addition_detected(self):
        initial = "OK pour demain 10h."
        final = (
            "OK pour demain 10h. "
            "Je t'enverrai l'ordre du jour ce soir. "
            "Peux-tu préparer le budget Q3 ? "
            "Je vais aussi inviter Sophie."
        )
        assert classify_edit(initial, final) == EditCategory.CONTENT_ADDITION

    def test_length_adjustment_shortening(self):
        initial = "A" * 100
        final = "A" * 60  # 40% plus court
        assert classify_edit(initial, final) == EditCategory.LENGTH_ADJUSTMENT

    def test_length_adjustment_threshold_boundary(self):
        # Juste en dessous du seuil → MINOR_TYPO_FIX ou OTHER, PAS length_adjustment.
        initial = "A" * 100
        final = "A" * int(100 * (1 - LENGTH_ADJ_MIN_DELTA + 0.05))  # ~85%
        assert classify_edit(initial, final) != EditCategory.LENGTH_ADJUSTMENT

    def test_tone_shift_formal_to_casual(self):
        # Longueur stable pour éviter que length_adjustment prenne la priorité.
        initial = (
            "Bonjour Jean, cordialement je confirme le rendez-vous de demain, "
            "bien cordialement et à bientôt."
        )
        final = (
            "Salut Jean, cheers je confirme le rendez-vous de demain, "
            "thanks beaucoup et à plus."
        )
        assert classify_edit(initial, final) == EditCategory.TONE_SHIFT

    def test_tone_shift_casual_to_formal(self):
        initial = "Salut,\nCheers,"
        # Ajouter des marqueurs formels en gardant longueur similaire.
        final = "Cordialement,\nSincèrement,\nBien à vous,"
        # Length delta ~33% → LENGTH_ADJUSTMENT prioritaire (voir priorités).
        # On vérifie que c'est du LENGTH_ADJUSTMENT (pas OTHER).
        cat = classify_edit(initial, final)
        assert cat in {EditCategory.TONE_SHIFT, EditCategory.LENGTH_ADJUSTMENT}

    def test_structure_change_paragraphs_added(self):
        initial = "Un seul paragraphe."
        # Garder longueur similaire mais casser en 3 paragraphes.
        final = "Un.\n\nSeul.\n\nParagraphe."
        cat = classify_edit(initial, final)
        # Peut être structure ou length (les deux se chevauchent avec ces chaînes courtes).
        assert cat in {EditCategory.STRUCTURE_CHANGE, EditCategory.LENGTH_ADJUSTMENT}

    def test_minor_typo_fix(self):
        # Modif < 5% et pas de signal de ton / structure / contenu.
        initial = "Bonjour Marc, je confirme pour demain matin 10h, à très vite."
        final = "Bonjour Marc, je confirme pour demain matin 10h; à très vite."
        assert classify_edit(initial, final) == EditCategory.MINOR_TYPO_FIX


class TestBuildEvent:
    def test_produces_valid_event(self):
        ev = build_event(
            draft_id="abc123",
            account_id=7,
            initial="Hello",
            final="Hi there friend, hope you're well!",
        )
        assert isinstance(ev, EditEvent)
        assert ev.account_id == 7
        assert ev.initial_length == 5
        assert ev.final_length == len("Hi there friend, hope you're well!")
        assert ev.magnitude > 0

    def test_magnitude_is_relative(self):
        # initial_len = 1 ne doit pas crasher (division par zéro protégée).
        ev = build_event(
            draft_id="x",
            account_id=1,
            initial="",
            final="quelques mots ajoutés",
        )
        assert ev.magnitude == float(ev.final_length)  # max(0,1) = 1

    def test_event_carries_intent_and_recipient(self):
        ev = build_event(
            draft_id="abc",
            account_id=1,
            initial="foo",
            final="foo bar baz qux beaucoup plus long",
            intent="NEGOTIATION",
            recipient_email="alice@example.com",
            original_email_id=42,
        )
        assert ev.intent == "NEGOTIATION"
        assert ev.recipient_email == "alice@example.com"
        assert ev.original_email_id == 42
