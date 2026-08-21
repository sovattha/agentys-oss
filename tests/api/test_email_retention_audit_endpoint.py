# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for /api/_internal/email-retention-audit.

This endpoint is the production bridge for the metadata-only email storage
audit. It must stay token-protected, return 200 only when the audit is clean,
and degrade when the audit either finds content or loses DB/file coverage.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "t-test-secret")
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _ok_report() -> dict:
    return {
        "ok": True,
        "status": "ok",
        "counts": {
            "json_files_scanned": 2,
            "database_checks": 3,
            "findings": 0,
        },
        "findings": [],
        "coverage_errors": [],
        "data_dir": "/data/agentys",
    }


class TestEmailRetentionAuditAuth:
    def test_returns_401_without_token(self, client):
        resp = client.get("/api/_internal/email-retention-audit")
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "unauthorized"}

    def test_returns_401_with_wrong_token(self, client):
        resp = client.get(
            "/api/_internal/email-retention-audit",
            headers={"X-Observability-Token": "wrong"},
        )
        assert resp.status_code == 401


class TestEmailRetentionAuditStatus:
    def test_clean_audit_returns_200(self, client, monkeypatch):
        from app.api import routes_selftest

        calls: list[dict] = []

        def fake_run(*, min_json_files: int, min_database_checks: int):
            calls.append({
                "min_json_files": min_json_files,
                "min_database_checks": min_database_checks,
            })
            return _ok_report()

        monkeypatch.setattr(routes_selftest, "_run_email_retention_audit", fake_run)

        resp = client.get(
            "/api/_internal/email-retention-audit?min_json_files=1&min_database_checks=2",
            headers={"X-Observability-Token": "t-test-secret"},
        )

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
        assert calls == [{"min_json_files": 1, "min_database_checks": 2}]

    def test_findings_return_503(self, client, monkeypatch):
        from app.api import routes_selftest

        report = _ok_report()
        report["ok"] = False
        report["status"] = "degraded"
        report["counts"]["findings"] = 1
        report["findings"] = [{
            "source": "database",
            "location": "emails.body_text",
            "detail": "non-empty metadata-only forbidden database column",
            "count": 1,
        }]
        monkeypatch.setattr(
            routes_selftest,
            "_run_email_retention_audit",
            lambda **_: report,
        )

        resp = client.get(
            "/api/_internal/email-retention-audit",
            headers={"X-Observability-Token": "t-test-secret"},
        )

        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "degraded"
        assert body["findings"][0]["location"] == "emails.body_text"

    def test_audit_exception_returns_500_without_traceback(self, client, monkeypatch):
        from app.api import routes_selftest

        def boom(**_):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(routes_selftest, "_run_email_retention_audit", boom)

        resp = client.get(
            "/api/_internal/email-retention-audit",
            headers={"X-Observability-Token": "t-test-secret"},
        )

        assert resp.status_code == 500
        body = resp.get_json()
        assert body["status"] == "error"
        assert "database unavailable" in body["error"]
        assert "Traceback" not in body["error"]


def test_retention_audit_coverage_errors_degrade(monkeypatch):
    from app.api import routes_selftest

    class FakeAudit:
        @staticmethod
        def parse_args(argv):
            return argv

        @staticmethod
        def build_report(_args):
            class FakeReport:
                @staticmethod
                def to_dict():
                    return {
                        "ok": True,
                        "counts": {
                            "json_files_scanned": 0,
                            "database_checks": 0,
                            "findings": 0,
                        },
                        "findings": [],
                    }

            return FakeReport()

    monkeypatch.setattr(
        routes_selftest,
        "_load_email_retention_audit_module",
        lambda: FakeAudit,
    )
    monkeypatch.setenv("EMAIL_RETENTION_AUDIT_DATA_DIR", "/data/agentys")

    report = routes_selftest._run_email_retention_audit(
        min_json_files=1,
        min_database_checks=1,
    )

    assert report["status"] == "degraded"
    assert "json_files_scanned below required minimum" in report["coverage_errors"][0]
    assert "database_checks below required minimum" in report["coverage_errors"][1]


def test_retention_audit_helper_loads_real_script(tmp_path, monkeypatch):
    from app.api import routes_selftest

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "style_profile_1.json").write_text(
        '{"reference_examples": [{"body_excerpt": "", "subject": ""}]}',
        encoding="utf-8",
    )

    db_path = tmp_path / "agentys.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE emails (body_text TEXT, body_html TEXT, snippet TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("EMAIL_RETENTION_AUDIT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EMAIL_RETENTION_AUDIT_SQLITE_DB_PATH", str(db_path))
    monkeypatch.delenv("EMAIL_RETENTION_AUDIT_DATABASE_URL", raising=False)

    report = routes_selftest._run_email_retention_audit(
        min_json_files=1,
        min_database_checks=1,
    )

    assert report["status"] == "ok"
    assert report["counts"]["json_files_scanned"] == 1
    assert report["counts"]["database_checks"] >= 1
