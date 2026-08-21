# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for scripts/nightly-oauth-expiry.py.

Issue #577 item 2 — surface a 30-day warning before the Azure App
Registration "Agentys" Client Secret expires (currently 2026-09-10).
Without this monitoring, the next outage is "100% green up to D-day,
then 100% red, no warning, user finds out by phone".

Exit code contract — every value here is observable from the GitHub
Actions runner and drives the auto-sentinelle alert pairing:
    0 — OK, secret expires in > 30 days
    1 — WARN, secret expires in <= 30 days but not yet expired
    2 — CRITICAL, secret already expired
The workflow `oauth-expiry-alert` job opens a deduped issue when the
audit job exits non-zero, so any change to these codes must keep the
non-zero == "deserves human attention" semantic.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "nightly-oauth-expiry.py"


@pytest.fixture
def script_module():
    """Import the script as a module so we can call its main() directly.

    A script with a hyphen in the filename can't be imported normally;
    importlib.util.spec_from_file_location is the canonical workaround.
    """
    spec = importlib.util.spec_from_file_location(
        "nightly_oauth_expiry", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"script not found at {_SCRIPT_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["nightly_oauth_expiry"] = module
    spec.loader.exec_module(module)
    return module


class TestExpiryClassification:
    """Pure function: days_until -> exit code. No I/O, easy to lock down."""

    def test_returns_0_when_more_than_30_days_remaining(self, script_module):
        assert script_module.classify_expiry(days_remaining=31) == 0
        assert script_module.classify_expiry(days_remaining=180) == 0

    def test_returns_1_when_30_days_or_fewer_remaining(self, script_module):
        assert script_module.classify_expiry(days_remaining=30) == 1
        assert script_module.classify_expiry(days_remaining=1) == 1
        assert script_module.classify_expiry(days_remaining=0) == 1

    def test_returns_2_when_already_expired(self, script_module):
        assert script_module.classify_expiry(days_remaining=-1) == 2
        assert script_module.classify_expiry(days_remaining=-365) == 2


class TestExpiryDateResolution:
    """Source of truth: env var first, hardcoded default fallback.

    The hardcoded default is a safety net so that a forgotten env var on
    a fresh CI runner doesn't silently skip the check — it must keep
    pointing at the real expiry date until the next rotation.
    """

    def test_env_var_overrides_default(self, script_module, monkeypatch):
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2027-01-15")
        resolved = script_module.resolve_expiry_date()
        assert resolved == _dt.date(2027, 1, 15)

    def test_default_used_when_env_var_absent(self, script_module, monkeypatch):
        monkeypatch.delenv(
            "MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", raising=False
        )
        resolved = script_module.resolve_expiry_date()
        # The hardcoded default must match the real Azure secret expiry
        # (cf. memory/outlook-oauth-setup.md). Update when the secret
        # is rotated and the script no longer reflects reality.
        assert resolved == _dt.date(2026, 9, 10)

    def test_invalid_env_var_falls_back_to_default(
        self, script_module, monkeypatch
    ):
        """A malformed env var should not crash the cron — it would mean
        the cron is dead and we lose the safety net entirely. Falling
        back to the hardcoded default keeps coverage even on a bad
        deploy of the workflow secrets."""
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "not-a-date")
        resolved = script_module.resolve_expiry_date()
        assert resolved == _dt.date(2026, 9, 10)


class TestMainExitCode:
    """End-to-end: main() returns exit code based on today() vs expiry."""

    def _patch_today(self, script_module, fake_today: _dt.date):
        """Patch the script's date.today() — must use a class because
        datetime.date is C-implemented and can't have its methods
        monkeypatched directly."""

        class _FrozenDate(_dt.date):
            @classmethod
            def today(cls):
                return fake_today

        return patch.object(script_module, "_date", _FrozenDate)

    def test_main_returns_0_long_before_expiry(self, script_module, monkeypatch):
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2026-12-31")
        with self._patch_today(script_module, _dt.date(2026, 5, 9)):
            assert script_module.main(argv=[]) == 0

    def test_main_returns_1_in_30_day_warning_window(
        self, script_module, monkeypatch
    ):
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2026-06-08")
        # 30 days exactly -> exit 1 (boundary)
        with self._patch_today(script_module, _dt.date(2026, 5, 9)):
            assert script_module.main(argv=[]) == 1

    def test_main_returns_2_when_expired(self, script_module, monkeypatch):
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2026-04-01")
        with self._patch_today(script_module, _dt.date(2026, 5, 9)):
            assert script_module.main(argv=[]) == 2


class TestOutputContract:
    """The script's stdout must be parseable by humans skimming the
    nightly run summary AND by GitHub Actions step logs (no secrets,
    no PII)."""

    def test_output_contains_days_remaining_and_date(
        self, script_module, monkeypatch, capsys
    ):
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2026-12-31")

        class _FrozenDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 5, 9)

        with patch.object(script_module, "_date", _FrozenDate):
            script_module.main(argv=[])
        out = capsys.readouterr().out
        assert "2026-12-31" in out
        assert "236" in out  # 236 days between 2026-05-09 and 2026-12-31

    def test_output_does_not_contain_secret_value(
        self, script_module, monkeypatch, capsys
    ):
        # Even if MICROSOFT_CLIENT_SECRET happens to leak into the
        # process env, the audit script must never echo it.
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "super-secret-value")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET_EXPIRY_DATE", "2026-12-31")

        class _FrozenDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 5, 9)

        with patch.object(script_module, "_date", _FrozenDate):
            script_module.main(argv=[])
        out = capsys.readouterr().out
        assert "super-secret-value" not in out
