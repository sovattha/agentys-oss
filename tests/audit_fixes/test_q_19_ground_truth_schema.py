# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-19 — Ground-truth fixtures aligned to current profile schema (audit 2026-05-06).

Pre-fix: ProfileAgent extracts ``preferred_name``, ``addressing``, and
``language_variant`` (added by recent prompt work), but the
``ground_truth_*.json`` fixtures didn't carry those keys. The judge
reported every persona's extra fields as "fabricated", subtracting
points across the board.

Post-fix: ``scripts/regenerate_ground_truths.py`` is idempotent and
adds the three keys with persona-appropriate values (derived from
domain TLD, signature first name, and existing tutoiement/vouvoiement
rules). Re-running on already-current files is a no-op.

This test pins the contract — a future fixture rewrite must keep all
three keys present.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"

GROUND_TRUTHS = [
    "ground_truth.json",
    "ground_truth_lawyer_paris.json",
    "ground_truth_sales_director.json",
    "ground_truth_startup_ceo.json",
    "ground_truth_hr_director.json",
    "ground_truth_consultant_intl.json",
]


def _load(name):
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def test_all_ground_truths_have_new_schema_fields():
    """Every ground truth must include the 3 schema fields ProfileAgent extracts."""
    for name in GROUND_TRUTHS:
        data = _load(name)
        prof = data.get("expected_profile", {})
        for key in ("preferred_name", "addressing", "language_variant"):
            assert key in prof, (
                f"{name}: expected_profile is missing {key!r}. "
                "Run scripts/regenerate_ground_truths.py."
            )


def test_addressing_values_are_valid():
    """addressing must be one of the documented values."""
    valid = {"tu", "vous", "mixed", None}
    for name in GROUND_TRUTHS:
        prof = _load(name)["expected_profile"]
        v = prof["addressing"]
        assert v in valid, f"{name}: addressing={v!r} not in {valid}"


def test_language_variant_values_are_iso_or_null():
    """language_variant must be ISO ll-CC code or null."""
    import re
    iso = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
    for name in GROUND_TRUTHS:
        prof = _load(name)["expected_profile"]
        v = prof["language_variant"]
        if v is not None:
            assert iso.match(v), f"{name}: language_variant={v!r} not ISO"


def test_preferred_name_is_substring_of_user_name():
    """preferred_name should be derived from user_name (first name typically)."""
    for name in GROUND_TRUTHS:
        prof = _load(name)["expected_profile"]
        un = prof.get("user_name", "")
        pn = prof.get("preferred_name", "")
        assert pn, f"{name}: preferred_name must be non-empty"
        # Allow the case where preferred_name is a substring (case-insensitive)
        # of user_name — handles "Marc-Antoine" in "Marc-Antoine Barreau".
        assert pn.lower() in un.lower(), (
            f"{name}: preferred_name={pn!r} not a substring of user_name={un!r}"
        )


def test_regen_script_is_idempotent():
    """Running the regen script twice must be a no-op the second time."""
    import subprocess
    import sys
    # Run once (writes if needed)
    subprocess.run(
        [sys.executable, "scripts/regenerate_ground_truths.py"],
        capture_output=True, check=True,
    )
    # Run twice — must report all "OK (already current)"
    out = subprocess.run(
        [sys.executable, "scripts/regenerate_ground_truths.py"],
        capture_output=True, text=True, check=True,
    )
    # Either "0/N changed" or absence of "UPDATED" lines is acceptable.
    assert "UPDATED" not in out.stdout, (
        "Re-running the regen script must be a no-op — it isn't:\n"
        + out.stdout
    )
