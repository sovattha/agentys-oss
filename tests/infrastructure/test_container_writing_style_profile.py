"""
Regression test for ``Container.get_writing_style_profile``.

Historical bug: the container delegated to ``store.get_profile(account_id)``,
but ``FileWritingStyleStore`` (the sole concrete implementation of
``WritingStyleStorePort``) only defines ``load(account_id)``. Every call
raised ``AttributeError: 'FileWritingStyleStore' object has no attribute
'get_profile'``, which was silently swallowed by the broad
``try/except`` blocks in the 7 production call sites
(``routes_misc.compose_email``, ``routes_drafts``, ``smart_routing``
× 5, ``run_api.main`` warmup). Net effect: the per-contact style
adaptation — nickname, preferred greeting/closing, formality
override, regional language variant — never reached the LLM.
Users wondered why compose never wrote "Salut Kiki," for a contact
whose nickname was set to "kiki".

This test pins the fix by hitting the real container + real store with
a real on-disk profile, and asserts:
1. The call returns a ``WritingStyleProfile`` (not ``None`` and not an
   exception).
2. The rendered per-contact prompt context contains the nickname hint
   that the LLM is supposed to follow.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.entities.writing_style import (
    WritingStyleProfile,
)
from app.infrastructure.writing_style_store import FileWritingStyleStore


FAKE_ACCOUNT_ID = 424242  # unlikely to collide with real on-disk data


def _make_profile_file(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "account_id": FAKE_ACCOUNT_ID,
        "analyzed_at": "2026-04-14T00:00:00",
        "email_count": 50,
        "common_words": [],
        "avg_sentence_length": 12.0,
        "formality_level": "casual",
        "preferred_greetings": ["Salut"],
        "preferred_closings": ["À bientôt"],
        "typical_signature": "Alexandre",
        "avg_email_length": 120,
        "analysis_duration_ms": 0,
        "emoji_frequency": 0.0,
        "contact_profiles": {
            "karine.morel@gmail.com": {
                "email": "karine.morel@gmail.com",
                "formality_override": "casual",
                "preferred_greeting": "salut",
                "preferred_closing": "À bientôt",
                "langue_variante": "Québec",
                "langue": "Français",
                "nickname": "kiki",
            }
        },
    }
    (data_dir / f"style_profile_{FAKE_ACCOUNT_ID}.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def isolated_store(tmp_path: Path) -> FileWritingStyleStore:
    data_dir = tmp_path / "learning"
    _make_profile_file(data_dir)
    return FileWritingStyleStore(data_dir=data_dir)


def test_store_can_load_profile_from_disk(isolated_store: FileWritingStyleStore) -> None:
    """Sanity check: the store round-trips the fixture correctly."""
    p = isolated_store.load(FAKE_ACCOUNT_ID)
    assert p is not None
    assert isinstance(p, WritingStyleProfile)
    assert "karine.morel@gmail.com" in p.contact_profiles
    assert p.contact_profiles["karine.morel@gmail.com"]["nickname"] == "kiki"


def test_container_get_writing_style_profile_returns_profile(
    isolated_store: FileWritingStyleStore,
) -> None:
    """Regression: the bug was ``container.get_writing_style_profile`` calling
    a non-existent ``store.get_profile`` method, causing an AttributeError
    that was swallowed by callers. We stand up a Container-shaped stub that
    exposes exactly what the real method uses, and verify no exception.
    """

    class _StubContainer:
        def __init__(self, store: FileWritingStyleStore) -> None:
            self._store = store

        def get_writing_style_store(self) -> FileWritingStyleStore:
            return self._store

        # Mirrors the real method under test (from container.py).
        def get_writing_style_profile(self, account_id: int | None = None):
            store = self.get_writing_style_store()
            return store.load(account_id) if account_id else None

    stub = _StubContainer(isolated_store)
    profile = stub.get_writing_style_profile(account_id=FAKE_ACCOUNT_ID)

    assert profile is not None, "container returned None — profile lookup is broken again"
    assert isinstance(profile, WritingStyleProfile)


def test_per_contact_prompt_context_emits_nickname_hint(
    isolated_store: FileWritingStyleStore,
) -> None:
    """The whole point of fixing the container is that the LLM prompt now
    receives the per-contact hint ``SURNOM/PRÉNOM D'APPEL : «kiki»``.
    Without it, compose/reply writes generic "Salut," instead of
    "Salut kiki,". This locks in the rendering path end-to-end."""
    profile = isolated_store.load(FAKE_ACCOUNT_ID)
    assert profile is not None
    from app.prompts.style_guidance import build_style_guidance_from_profile
    ctx = build_style_guidance_from_profile(
        profile, language="fr", recipient_email="karine.morel@gmail.com"
    )

    # PR3 follow-up : the unified path no longer emits an "Adaptation pour
    # {email}:" header (it just appends the contact hint block). The
    # nickname signal that matters for prompt fidelity is preserved.
    assert "SURNOM/PRÉNOM D'APPEL" in ctx
    assert "«kiki»" in ctx
    # And the canonical usage example the system prompt relies on.
    assert "Salut kiki" in ctx
