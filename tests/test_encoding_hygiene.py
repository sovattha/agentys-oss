# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression guard: every text file read/write in ``app/`` must pass an
explicit ``encoding="utf-8"``.

Why this exists — on Windows, ``open()`` / ``Path.read_text()`` /
``Path.write_text()`` default to the platform code page (cp1252), not
UTF-8. A file written UTF-8 by one path and read without ``encoding=`` by
another comes back mojibake (``é`` → ``Ã©``). That is exactly how the
``email_accounts.json`` / token / store JSON files could silently corrupt
accented data. This test fails loudly the moment a new ``open()`` without
``encoding=`` lands, instead of waiting for a user to see "Crypto
UniversitÃ©" in the UI.

Binary modes (``rb`` / ``wb`` / ``ab`` …) are correctly exempt — they take
no ``encoding`` argument.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _mode_of(call: ast.Call) -> str:
    """Best-effort extraction of an ``open()`` call's mode string."""
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"  # text read is the open() default


def _has_encoding_kw(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" for kw in call.keywords)


def _scan_file(path: Path) -> list[str]:
    """Return ``file:line: kind`` strings for offending calls in one module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            if "b" in _mode_of(node):  # binary — no encoding applies
                continue
            if not _has_encoding_kw(node):
                rel = path.relative_to(_APP_DIR.parent).as_posix()
                offenders.append(f"{rel}:{node.lineno}: open()")
        elif isinstance(func, ast.Attribute) and func.attr in (
            "read_text",
            "write_text",
        ):
            if not _has_encoding_kw(node):
                rel = path.relative_to(_APP_DIR.parent).as_posix()
                offenders.append(f"{rel}:{node.lineno}: {func.attr}()")
    return offenders


def test_no_text_io_missing_encoding_in_app():
    """No ``open()`` / ``read_text()`` / ``write_text()`` in ``app/`` may
    omit ``encoding=`` (binary modes excepted)."""
    offenders: list[str] = []
    for py_file in sorted(_APP_DIR.rglob("*.py")):
        offenders.extend(_scan_file(py_file))

    assert not offenders, (
        "Text file I/O missing explicit encoding= (Windows defaults to "
        "cp1252 → mojibake on accented data). Add encoding=\"utf-8\":\n  "
        + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
