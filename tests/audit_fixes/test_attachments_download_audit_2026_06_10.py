"""Regression tests for the 24h audit of 2026-06-10.

Report: tasks/audit-reports/2026-06-10_2318_regressions/pass-3-summary.md

F-02 — ``download-all`` returned HTTP 200 with a silently incomplete zip when
any single attachment download failed at the provider (log-and-continue, no
failure counter). The user could archive/delete the source email believing
everything was saved. The fix surfaces the dropped filenames in the
``X-Failed-Attachments`` response header (URL-encoded, comma-separated) so the
frontend can raise a warning toast.
"""

from contextlib import ExitStack
from unittest.mock import Mock, patch
from urllib.parse import unquote

import io
import zipfile

import pytest

pytest.importorskip("flask_cors")

# Authenticated JWT caller reaching the handler through the real create_app —
# same pattern as tests/audit_fixes/test_deep_audit_2026_06_02.py.
REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
_BEARER = {"Authorization": "Bearer stub-token"}
EMAIL_ID = "1a2b3c4d5e6f7890"


def _decode_jwt_ok():
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": 1, "email": "audit@example.com"},
    )


@pytest.fixture
def client():
    from app.api.app import create_app
    return create_app(config={"TESTING": True}).test_client()


class _FakeProvider:
    """Provider stub: every attachment downloads fine except ``fail_ids``."""

    def __init__(self, attachments, fail_ids=()):
        self._attachments = attachments
        self._fail_ids = set(fail_ids)

    def get_message_by_id(self, _raw_id):
        msg = Mock()
        msg.attachments = self._attachments
        msg.subject = "Sujet test"
        return msg

    def download_attachment(self, _raw_id, att_id):
        if att_id in self._fail_ids:
            raise RuntimeError("provider transient 500")
        return b"x" * 10, "application/pdf", f"{att_id}.pdf"


def _atts(*names):
    return [
        {"id": f"att-{i}", "filename": name, "size": 50_000}
        for i, name in enumerate(names, 1)
    ]


def _call_download_all(client, provider):
    with ExitStack() as stack:
        stack.enter_context(_decode_jwt_ok())
        stack.enter_context(patch(
            "app.api.routes_emails._get_current_account_for_user",
            return_value=Mock(id=7, email="audit@example.com"),
        ))
        stack.enter_context(patch(
            "app.providers.factory.get_pooled_provider",
            return_value=provider,
        ))
        return client.get(
            f"/api/emails/{EMAIL_ID}/attachments/download-all",
            headers=_BEARER,
            environ_base=REMOTE,
        )


def _zip_names(resp) -> list:
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        return sorted(zf.namelist())


def test_download_all_partial_failure_reports_dropped_files(client):
    """F-02: one failed attachment out of three must be surfaced to the client,
    not silently dropped from the archive."""
    provider = _FakeProvider(
        _atts("contrat.pdf", "rapport.pdf", "annexe.pdf"), fail_ids={"att-2"}
    )
    resp = _call_download_all(client, provider)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _zip_names(resp) == ["annexe.pdf", "contrat.pdf"]

    header = resp.headers.get("X-Failed-Attachments")
    assert header, "partial failure must set X-Failed-Attachments"
    failed = [unquote(part) for part in header.split(",")]
    assert failed == ["rapport.pdf"]


def test_download_all_full_success_has_no_failed_header(client):
    """The warning channel must stay silent when the zip is complete."""
    provider = _FakeProvider(_atts("contrat.pdf", "rapport.pdf", "annexe.pdf"))
    resp = _call_download_all(client, provider)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _zip_names(resp) == ["annexe.pdf", "contrat.pdf", "rapport.pdf"]
    assert resp.headers.get("X-Failed-Attachments") is None


def test_failed_names_with_commas_and_accents_round_trip(client):
    """Review F3 : le join sur virgule ne tient que parce que quote() encode
    les virgules — épingler le contrat (virgule + UTF-8 dans le nom)."""
    provider = _FakeProvider(
        _atts("rapport, final é.pdf", "ok.pdf", "annexe très spéciale.pdf"),
        fail_ids={"att-1", "att-3"},
    )
    resp = _call_download_all(client, provider)
    assert resp.status_code == 200
    failed = [unquote(p) for p in resp.headers["X-Failed-Attachments"].split(",")]
    assert failed == ["rapport, final é.pdf", "annexe très spéciale.pdf"]


def test_failed_header_bounded_at_20_names(client):
    """Review F5 : le manifeste est borné (20 noms) pour ne pas produire un
    header multi-Ko qu'un proxy edge rejetterait."""
    atts = _atts(*[f"doc-{i:02d}.pdf" for i in range(25)])
    provider = _FakeProvider(atts, fail_ids={f"att-{i}" for i in range(1, 25)})
    resp = _call_download_all(client, provider)
    assert resp.status_code == 200  # att-25 réussit
    failed = resp.headers["X-Failed-Attachments"].split(",")
    assert len(failed) == 20


def test_download_all_all_failed_keeps_404_contract(client):
    """Pin the pre-existing all-failed contract: a 404 the FE already toasts."""
    provider = _FakeProvider(
        _atts("contrat.pdf", "rapport.pdf"), fail_ids={"att-1", "att-2"}
    )
    resp = _call_download_all(client, provider)
    assert resp.status_code == 404


def test_failed_attachments_header_exposed_to_cors_clients():
    """The Vite dev origin (1420) is cross-origin from the API (5050): without
    Access-Control-Expose-Headers the browser hides the warning header and the
    FE silently regresses to the pre-fix behavior."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    client = app.test_client()
    with ExitStack() as stack:
        stack.enter_context(_decode_jwt_ok())
        resp = client.get(
            "/api/health",
            headers={**_BEARER, "Origin": "http://localhost:1420"},
            environ_base=REMOTE,
        )
    exposed = resp.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Failed-Attachments" in exposed, (
        f"CORS must expose X-Failed-Attachments; got: {exposed!r}"
    )
