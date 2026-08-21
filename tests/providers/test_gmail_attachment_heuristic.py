# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Inbox-list paperclip accuracy (audit fix 2026-06-02).

_map_metadata_to_standard_email derived has_attachments from
`"multipart/mixed" in payload.mimeType`, which showed a false paperclip on
inline-only emails and missed attachments under multipart/signed|related roots.
The fix runs the real _check_has_attachments part scan instead.
"""
from __future__ import annotations

from app.providers.gmail_adapter import GmailAdapter


def _msg(payload: dict) -> dict:
    return {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX"],
        "snippet": "hi",
        "payload": payload,
    }


def _map(payload: dict):
    return GmailAdapter()._map_metadata_to_standard_email(_msg(payload))


def test_inline_only_multipart_mixed_has_no_attachment():
    # multipart/mixed root but the only "part with a filename" is an inline image
    # (carries a Content-ID) — the old heuristic wrongly flagged a paperclip.
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Newsletter"}],
        "parts": [
            {"mimeType": "text/html", "filename": "", "body": {"size": 1200}},
            {
                "mimeType": "image/png",
                "filename": "logo.png",
                "headers": [{"name": "Content-ID", "value": "<logo123>"}],
                "body": {"attachmentId": "att-inline", "size": 8000},
            },
        ],
    }
    assert _map(payload).has_attachments is False


def test_real_attachment_under_multipart_signed_is_detected():
    # multipart/signed root with a genuine PDF attachment — the old heuristic
    # (root must be multipart/mixed) missed it entirely.
    payload = {
        "mimeType": "multipart/signed",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 50}},
            {
                "mimeType": "application/pdf",
                "filename": "invoice.pdf",
                "body": {"attachmentId": "att-pdf", "size": 52000},
            },
        ],
    }
    assert _map(payload).has_attachments is True


def test_real_attachment_under_multipart_mixed_still_detected():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 40}},
            {
                "mimeType": "application/zip",
                "filename": "report.zip",
                "body": {"attachmentId": "att-zip", "size": 120000},
            },
        ],
    }
    assert _map(payload).has_attachments is True


def test_plain_alternative_email_has_no_attachment():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 40}},
            {"mimeType": "text/html", "filename": "", "body": {"size": 80}},
        ],
    }
    assert _map(payload).has_attachments is False


# ── Pièces jointes Outlook : Content-ID + Content-Disposition: attachment ──
# Bug 2026-06-10 : Outlook met un Content-ID sur de VRAIES pièces jointes ;
# le scan les prenait pour des images inline et elles disparaissaient de
# l'email reçu (message « pj test » : le PDF de 87 Ko manquait, le .txt
# sans Content-ID s'affichait).

def _outlook_pdf_part() -> dict:
    return {
        "mimeType": "application/pdf",
        "filename": "Sortie de FIN D'ANNEE 2026.pdf",
        "headers": [
            {"name": "Content-ID", "value": "<40386CAE@namprd12.prod.outlook.com>"},
            {"name": "Content-Disposition", "value": 'attachment; filename="Sortie de FIN D\'ANNEE 2026.pdf"'},
        ],
        "body": {"attachmentId": "att-outlook-pdf", "size": 87314},
    }


def test_outlook_attachment_with_content_id_is_detected():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 26}},
            _outlook_pdf_part(),
        ],
    }
    assert _map(payload).has_attachments is True


def test_outlook_attachment_with_content_id_appears_in_metadata():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"size": 26}},
            _outlook_pdf_part(),
            {
                "mimeType": "text/plain",
                "filename": "Options sans vendre de parts.txt",
                "headers": [
                    {"name": "Content-Disposition", "value": 'attachment; filename="Options sans vendre de parts.txt"'},
                ],
                "body": {"attachmentId": "att-txt", "size": 1485},
            },
        ],
    }
    atts = GmailAdapter()._extract_attachment_metadata(payload)
    assert [a["filename"] for a in atts] == [
        "Sortie de FIN D'ANNEE 2026.pdf",
        "Options sans vendre de parts.txt",
    ]


def test_inline_image_without_disposition_still_excluded_from_metadata():
    # L'image inline classique (Content-ID, pas de Content-Disposition
    # attachment) reste exclue — le fix ne doit pas réintroduire les logos.
    payload = {
        "mimeType": "multipart/related",
        "parts": [
            {"mimeType": "text/html", "filename": "", "body": {"size": 1200}},
            {
                "mimeType": "image/png",
                "filename": "logo.png",
                "headers": [
                    {"name": "Content-ID", "value": "<logo123>"},
                    {"name": "Content-Disposition", "value": "inline; filename=logo.png"},
                ],
                "body": {"attachmentId": "att-inline", "size": 8000},
            },
        ],
    }
    assert GmailAdapter()._extract_attachment_metadata(payload) == []
    assert _map(payload).has_attachments is False
