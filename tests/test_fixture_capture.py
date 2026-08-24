# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests unitaires pour `app._fixture_capture`.

Couvre :
  - No-op quand env var OFF
  - Écriture JSONL quand env var ON
  - Rotation par quota (500 max par mode par jour)
  - Swallow silencieux des erreurs
  - Isolation par mode (quota séparé standard/streaming/classify/v2_partial)
"""

from __future__ import annotations

import json

import pytest

from app import _fixture_capture as fc


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    """Reset les compteurs en mémoire et redirige la capture vers un tmp_path."""
    fc.reset_daily_counts_for_testing()
    monkeypatch.setenv("PIPELINE_CAPTURE_DIR", str(tmp_path))
    monkeypatch.delenv(fc.ENV_FLAG, raising=False)
    yield
    fc.reset_daily_counts_for_testing()


def _valid_invocation() -> dict:
    return dict(
        mode="standard",
        raw_draft="Bonjour, voici ma réponse.",
        pipeline_input={
            "body": "Email source",
            "subject": "Test",
            "sender": "alice@example.com",
            "formality": 3,
        },
        cleaned_draft="Bonjour, voici ma réponse nettoyée.",
        corrections=2,
        correction_details=["html_cleanup", "filler_removed"],
        learned_corrections_applied=[],
    )


def test_no_op_when_env_var_off(tmp_path):
    """Env var OFF → aucun fichier créé."""
    fc.capture_if_enabled(**_valid_invocation())
    assert list(tmp_path.iterdir()) == []


def test_writes_jsonl_when_enabled(monkeypatch, tmp_path):
    """Env var ON → fichier JSONL écrit avec le payload attendu."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    fc.capture_if_enabled(**_valid_invocation())

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip()
    record = json.loads(content)

    assert record["mode"] == "standard"
    assert record["cleaned_draft"] == "Bonjour, voici ma réponse nettoyée."
    assert record["corrections"] == 2
    assert record["correction_details"] == ["html_cleanup", "filler_removed"]
    assert record["learned_corrections_applied"] == []
    assert "captured_at" in record
    assert record["pipeline_input"]["formality"] == 3


def test_multiple_captures_append_to_same_file(monkeypatch, tmp_path):
    """Plusieurs captures le même jour s'appendent dans le même fichier JSONL."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    fc.capture_if_enabled(**_valid_invocation())
    fc.capture_if_enabled(**_valid_invocation())
    fc.capture_if_enabled(**_valid_invocation())

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    # Chaque ligne est du JSON valide
    for line in lines:
        record = json.loads(line)
        assert record["mode"] == "standard"


def test_quota_blocks_after_500_per_mode(monkeypatch, tmp_path):
    """501e capture du même mode le même jour est bloquée silencieusement."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    for _ in range(fc.MAX_CAPTURES_PER_MODE_PER_DAY):
        fc.capture_if_enabled(**_valid_invocation())
    fc.capture_if_enabled(**_valid_invocation())  # 501e

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == fc.MAX_CAPTURES_PER_MODE_PER_DAY


def test_quota_isolated_per_mode(monkeypatch, tmp_path):
    """Quota séparé par mode — standard peut être full sans bloquer streaming."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    for _ in range(fc.MAX_CAPTURES_PER_MODE_PER_DAY):
        fc.capture_if_enabled(**_valid_invocation())  # mode=standard

    streaming = _valid_invocation()
    streaming["mode"] = "streaming"
    fc.capture_if_enabled(**streaming)

    files = list(tmp_path.iterdir())
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == fc.MAX_CAPTURES_PER_MODE_PER_DAY + 1

    modes = [json.loads(line)["mode"] for line in lines]
    assert modes.count("standard") == fc.MAX_CAPTURES_PER_MODE_PER_DAY
    assert modes.count("streaming") == 1


def test_capture_swallows_exception_silently(monkeypatch, tmp_path):
    """Si l'écriture échoue (ex: disque plein), pas de crash."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)

    # Ne doit rien raise
    fc.capture_if_enabled(**_valid_invocation())


def test_extra_field_preserved(monkeypatch, tmp_path):
    """Le champ `extra` optionnel est conservé dans le JSONL."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    invocation = _valid_invocation()
    invocation["extra"] = {"account_id": 42, "tier": "STANDARD"}
    fc.capture_if_enabled(**invocation)

    content = list(tmp_path.iterdir())[0].read_text(encoding="utf-8").strip()
    record = json.loads(content)
    assert record["extra"]["account_id"] == 42
    assert record["extra"]["tier"] == "STANDARD"


def test_non_ascii_content_encoded_correctly(monkeypatch, tmp_path):
    """Les caractères français (é, è, ç) sont encodés en UTF-8 sans échappement unicode."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    invocation = _valid_invocation()
    invocation["cleaned_draft"] = "Bonsoir Dušan, à très bientôt !"
    fc.capture_if_enabled(**invocation)

    content = list(tmp_path.iterdir())[0].read_text(encoding="utf-8").strip()
    # ensure_ascii=False → caractères natifs dans le JSONL
    assert "Dušan" in content
    assert "à très bientôt" in content


def test_learned_corrections_applied_captured(monkeypatch, tmp_path):
    """La liste `learned_corrections_applied` est préservée pour le mock replay."""
    monkeypatch.setenv(fc.ENV_FLAG, "1")
    invocation = _valid_invocation()
    invocation["learned_corrections_applied"] = ["rule_xyz", "rule_abc"]
    fc.capture_if_enabled(**invocation)

    content = list(tmp_path.iterdir())[0].read_text(encoding="utf-8").strip()
    record = json.loads(content)
    assert record["learned_corrections_applied"] == ["rule_xyz", "rule_abc"]
