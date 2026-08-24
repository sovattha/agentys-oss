# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from app.utils.draft_cleanup import strip_terminal_parenthetical_note


def test_strips_final_standalone_parenthetical_note():
    text = "Bonjour,\n\nMerci pour votre retour.\n\nCordialement,\nAlex\n\n(je peux adapter le ton si besoin)"

    assert strip_terminal_parenthetical_note(text) == "Bonjour,\n\nMerci pour votre retour.\n\nCordialement,\nAlex"


def test_keeps_inline_parentheses():
    text = "Je vous confirme la référence (arts. 1726-1733 CCQ) pour le dossier.\n\nCordialement,"

    assert strip_terminal_parenthetical_note(text) == text
