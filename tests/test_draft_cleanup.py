from app.utils.draft_cleanup import strip_terminal_parenthetical_note


def test_strips_final_standalone_parenthetical_note():
    text = "Bonjour,\n\nMerci pour votre retour.\n\nCordialement,\nAlex\n\n(je peux adapter le ton si besoin)"

    assert strip_terminal_parenthetical_note(text) == "Bonjour,\n\nMerci pour votre retour.\n\nCordialement,\nAlex"


def test_keeps_inline_parentheses():
    text = "Je vous confirme la référence (arts. 1726-1733 CCQ) pour le dossier.\n\nCordialement,"

    assert strip_terminal_parenthetical_note(text) == text
