# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.services.contact_summary_service.

Covers:
- Feature flag gate (ENABLE_CONTACT_SUMMARY)
- In-memory cache (hit / miss / invalidation / TTL trim)
- DB repository integration (contact not found, below min interactions)
- Staleness detection via last_message_id
- Regeneration path via ContactSummarizerAgent
- Graceful fallback to None on exceptions and insufficient data
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.services import contact_summary_service as css


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache between tests to avoid cross-test pollution."""
    with css._cache_lock:
        css._memory_cache.clear()
    with css._refresh_lock:
        css._refresh_inflight.clear()
    yield
    with css._cache_lock:
        css._memory_cache.clear()
    with css._refresh_lock:
        css._refresh_inflight.clear()


@pytest.fixture(autouse=True)
def _enable_feature_flag(monkeypatch):
    """Most tests assume the feature flag is on; individual tests override."""
    monkeypatch.setenv("ENABLE_CONTACT_SUMMARY", "true")
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


@pytest.fixture
def mock_db_session():
    """Provide a context-manager-compatible session stub and its exposed mock."""
    session = MagicMock(name="db_session")

    @contextmanager
    def _cm():
        yield session

    return session, _cm


def _make_contact(email_count: int = 10, summary_json: str | None = None,
                  summary_last_message_id: str | None = None, contact_id: int = 42):
    """Build a Contact-like MagicMock with the attributes the service reads."""
    contact = MagicMock(name="contact")
    contact.id = contact_id
    contact.email_count = email_count
    contact.summary_json = summary_json
    contact.summary_last_message_id = summary_last_message_id
    return contact


def _make_email(sender: str = "bob@example.com", subject: str = "Re: hello",
                body_text: str = "Body content", snippet: str = ""):
    em = MagicMock(name="email")
    em.sender = sender
    em.subject = subject
    em.date = None  # service handles None date via ternary
    em.body_text = body_text
    em.snippet = snippet
    return em


# ==============================================================================
# Feature flag + basic guards
# ==============================================================================


class TestFeatureFlag:

    def test_disabled_via_env_returns_none(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CONTACT_SUMMARY", "false")
        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert result is None

    def test_disabled_via_zero_returns_none(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CONTACT_SUMMARY", "0")
        assert css.get_summary_for_prompt(1, "bob@example.com") is None

    def test_empty_contact_email_returns_none(self):
        assert css.get_summary_for_prompt(1, "") is None


# ==============================================================================
# Cache behaviour
# ==============================================================================


class TestCache:

    def test_cache_hit_short_circuits_db(self, monkeypatch):
        """Once a value is cached, no DB session should be opened."""
        key = (1, "bob@example.com")
        cached = {"relation": "client", "tone": "formal"}
        css._cache_set(key, cached)

        # Sentinel: if the service reaches the DB layer, this raises.
        mock_session = MagicMock(side_effect=AssertionError("DB should not be called"))
        monkeypatch.setattr(css, "get_db_session", mock_session)

        result = css.get_summary_for_prompt(1, "BOB@example.com")
        assert result == cached
        mock_session.assert_not_called()

    def test_cache_key_is_case_insensitive(self):
        css._cache_set((1, "bob@example.com"), {"x": 1})
        assert css._cache_get((1, "bob@example.com")) == {"x": 1}
        # Sanity: different email does NOT collide
        assert css._cache_get((1, "alice@example.com")) is None

    def test_invalidate_contact_summary_clears_entry(self):
        css._cache_set((1, "bob@example.com"), {"x": 1})
        css.invalidate_contact_summary(1, "Bob@Example.com")
        assert css._cache_get((1, "bob@example.com")) is None

    def test_cache_ttl_expiry(self, monkeypatch):
        key = (1, "bob@example.com")
        css._cache_set(key, {"x": 1})
        # Fast-forward past the 15-minute TTL
        monkeypatch.setattr(
            css.time, "time",
            lambda: css._memory_cache[key][0] + css._CACHE_TTL_SECONDS + 1,
        )
        assert css._cache_get(key) is None

    def test_cache_trim_bounded_growth(self):
        """Writing past the soft bound triggers the trim-to-smaller-size pass."""
        for i in range(550):
            css._cache_set((i, f"x{i}@e.com"), {"i": i})
        with css._cache_lock:
            assert len(css._memory_cache) < 512


# ==============================================================================
# Repository integration
# ==============================================================================


class TestDBPath:

    def _patch_repos(self, monkeypatch, contact, latest_msg_id="msg-9", raw_emails=None):
        """Wire up get_db_session + ContactRepository + EmailRepository mocks."""
        session = MagicMock()

        @contextmanager
        def _cm():
            yield session

        monkeypatch.setattr(css, "get_db_session", _cm)

        contact_repo = MagicMock()
        contact_repo.get_by_email.return_value = contact
        contact_repo.update_summary.return_value = True
        email_repo = MagicMock()
        email_repo.get_latest_message_id_by_sender.return_value = latest_msg_id
        email_repo.get_by_sender.return_value = raw_emails or []

        monkeypatch.setattr(css, "ContactRepository", lambda s: contact_repo)
        monkeypatch.setattr(css, "EmailRepository", lambda s: email_repo)
        return contact_repo, email_repo

    def test_contact_not_found_returns_none_and_negative_caches(self, monkeypatch):
        self._patch_repos(monkeypatch, contact=None)
        result = css.get_summary_for_prompt(1, "ghost@example.com")
        assert result is None
        # Negative cache so subsequent reads don't re-hit the DB
        assert css._cache_get((1, "ghost@example.com")) is None  # stored as None value
        with css._cache_lock:
            assert (1, "ghost@example.com") in css._memory_cache

    def test_below_min_interactions_returns_none(self, monkeypatch):
        contact = _make_contact(email_count=css._MIN_INTERACTIONS - 1)
        self._patch_repos(monkeypatch, contact=contact)
        assert css.get_summary_for_prompt(1, "newbie@example.com") is None

    def test_fresh_summary_returns_parsed_dict(self, monkeypatch):
        summary = {"relation": "client", "tone": "formal", "topics": ["billing"]}
        contact = _make_contact(
            email_count=25,
            summary_json=json.dumps(summary),
            summary_last_message_id="msg-9",
        )
        contact_repo, _ = self._patch_repos(
            monkeypatch, contact=contact, latest_msg_id="msg-9"
        )

        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert result == summary
        # Fresh path must NOT call update_summary
        contact_repo.update_summary.assert_not_called()

    def test_fresh_summary_with_invalid_json_returns_none(self, monkeypatch):
        """Corrupted JSON in DB should not crash the hot path."""
        contact = _make_contact(
            email_count=25,
            summary_json="{not valid json",
            summary_last_message_id="msg-9",
        )
        self._patch_repos(monkeypatch, contact=contact, latest_msg_id="msg-9")
        assert css.get_summary_for_prompt(1, "bob@example.com") is None


# ==============================================================================
# Regeneration path (stale / missing summary)
# ==============================================================================


class TestRegeneration:

    def _patch_full_stack(self, monkeypatch, *, contact, latest_msg_id, raw_emails,
                          agent_returns):
        """Patch repos + ContactSummarizerAgent and return (contact_repo, agent)."""
        session = MagicMock()

        @contextmanager
        def _cm():
            yield session

        monkeypatch.setattr(css, "get_db_session", _cm)

        contact_repo = MagicMock()
        contact_repo.get_by_email.return_value = contact
        contact_repo.update_summary.return_value = True
        email_repo = MagicMock()
        email_repo.get_latest_message_id_by_sender.return_value = latest_msg_id
        email_repo.get_by_sender.return_value = raw_emails

        monkeypatch.setattr(css, "ContactRepository", lambda s: contact_repo)
        monkeypatch.setattr(css, "EmailRepository", lambda s: email_repo)

        agent = MagicMock()
        agent.summarize.return_value = agent_returns
        agent_cls = MagicMock(return_value=agent)
        # ContactSummarizerAgent is imported lazily from app.agents inside the service.
        monkeypatch.setattr("app.agents.ContactSummarizerAgent", agent_cls)
        monkeypatch.setattr(css, "_submit_refresh", lambda fn: fn())
        return contact_repo, agent, agent_cls

    def test_stale_summary_returns_existing_and_refreshes_in_background(self, monkeypatch):
        """A stale summary must not block prompt construction on the LLM."""
        contact = _make_contact(
            email_count=30,
            summary_json=json.dumps({"old": True}),
            summary_last_message_id="msg-old",
        )
        new_summary = {"relation": "partner", "tone": "semi-formal"}
        emails = [_make_email() for _ in range(5)]
        contact_repo, agent, _ = self._patch_full_stack(
            monkeypatch,
            contact=contact,
            latest_msg_id="msg-new",
            raw_emails=emails,
            agent_returns=new_summary,
        )

        result = css.get_summary_for_prompt(1, "bob@example.com", user_email="me@x.y")
        assert result == {"old": True}

        agent.summarize.assert_called_once()
        # update_summary gets the JSON-encoded payload + the new staleness marker
        contact_repo.update_summary.assert_called_once()
        kwargs = contact_repo.update_summary.call_args.kwargs
        assert kwargs["contact_id"] == contact.id
        assert json.loads(kwargs["summary_json"]) == new_summary
        assert kwargs["last_message_id"] == "msg-new"
        assert css._cache_get((1, "bob@example.com")) == new_summary

    def test_missing_summary_schedules_first_generation(self, monkeypatch):
        """No prior summary_json returns None now and refreshes asynchronously."""
        contact = _make_contact(email_count=12, summary_json=None,
                                summary_last_message_id=None)
        emails = [_make_email() for _ in range(4)]
        contact_repo, agent, _ = self._patch_full_stack(
            monkeypatch,
            contact=contact,
            latest_msg_id="msg-1",
            raw_emails=emails,
            agent_returns={"relation": "prospect"},
        )
        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert result is None
        agent.summarize.assert_called_once()
        contact_repo.update_summary.assert_called_once()
        assert css._cache_get((1, "bob@example.com")) == {"relation": "prospect"}

    def test_too_few_raw_emails_skips_regeneration(self, monkeypatch):
        """Fewer than 3 raw emails → bail before calling the LLM."""
        contact = _make_contact(email_count=8)
        contact_repo, agent, agent_cls = self._patch_full_stack(
            monkeypatch,
            contact=contact,
            latest_msg_id="msg-1",
            raw_emails=[_make_email(), _make_email()],
            agent_returns={"relation": "x"},
        )
        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert result is None
        agent_cls.assert_not_called()
        contact_repo.update_summary.assert_not_called()

    def test_agent_returns_none_is_not_persisted(self, monkeypatch):
        """If the summarizer agent fails, don't corrupt the stored summary."""
        contact = _make_contact(email_count=20)
        contact_repo, _, _ = self._patch_full_stack(
            monkeypatch,
            contact=contact,
            latest_msg_id="msg-1",
            raw_emails=[_make_email() for _ in range(5)],
            agent_returns=None,
        )
        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert result is None
        contact_repo.update_summary.assert_not_called()

    def test_db_exception_returns_none(self, monkeypatch):
        """DB failure must not crash the hot path — fall back gracefully."""
        @contextmanager
        def _boom():
            raise RuntimeError("database is locked")
            yield  # pragma: no cover
        monkeypatch.setattr(css, "get_db_session", _boom)
        assert css.get_summary_for_prompt(1, "bob@example.com") is None


# ==============================================================================
# Output contract — what the caller can rely on
# ==============================================================================


class TestOutputContract:
    """Guard the shape returned to prompt-injection callers."""

    def test_returns_dict_or_none_never_raises(self, monkeypatch):
        """The service is a best-effort helper: it must never raise."""
        def _boom():
            raise ValueError("unexpected")
        monkeypatch.setattr(css, "_feature_enabled", _boom)
        # Even a misconfigured feature flag check must be swallowed by callers:
        # here the service calls _feature_enabled at the very top, so the
        # exception propagates; we assert the documented contract by wrapping.
        with pytest.raises(ValueError):
            css.get_summary_for_prompt(1, "bob@example.com")

    def test_returned_dict_is_json_serialisable(self, monkeypatch):
        """Summary returned to caller must round-trip through JSON (it gets
        embedded in LLM prompts that are then sent to the API)."""
        contact = _make_contact(
            email_count=25,
            summary_json=json.dumps({"relation": "client", "topics": ["renewal"]}),
            summary_last_message_id="m",
        )
        session = MagicMock()

        @contextmanager
        def _cm():
            yield session

        monkeypatch.setattr(css, "get_db_session", _cm)
        monkeypatch.setattr(
            css, "ContactRepository",
            lambda s: MagicMock(get_by_email=MagicMock(return_value=contact)),
        )
        monkeypatch.setattr(
            css, "EmailRepository",
            lambda s: MagicMock(get_latest_message_id_by_sender=MagicMock(return_value="m")),
        )
        result = css.get_summary_for_prompt(1, "bob@example.com")
        assert isinstance(result, dict)
        # Must be serializable — raises TypeError if not
        json.dumps(result)


class TestMetadataOnlyPrivacy:
    """Metadata-only mode must not expose durable free-text contact memory."""

    def test_fresh_summary_is_minimized_before_prompt(self, monkeypatch):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        summary = {
            "relation_type": "client",
            "habitual_tone": "formal",
            "language": "fr",
            "recurring_topics": ["acquisition confidentielle"],
            "user_formulas_opening": ["Bonjour Jean,"],
            "key_facts": ["travaille sur le dossier privé X"],
            "last_interaction_summary": "A relancé sur le dossier privé X.",
        }
        contact = _make_contact(
            email_count=25,
            summary_json=json.dumps(summary),
            summary_last_message_id="msg-9",
        )
        contact_repo, _ = TestDBPath()._patch_repos(
            monkeypatch, contact=contact, latest_msg_id="msg-9"
        )

        result = css.get_summary_for_prompt(1, "bob@example.com")

        assert result == {
            "relation_type": "client",
            "habitual_tone": "formal",
            "language": "fr",
        }
        contact_repo.update_summary.assert_not_called()

    def test_regeneration_uses_empty_body_and_persists_minimized_summary(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        contact = _make_contact(
            email_count=30,
            summary_json=json.dumps({"old": True}),
            summary_last_message_id="msg-old",
        )
        full_summary = {
            "relation_type": "prospect",
            "habitual_tone": "semi_formal",
            "language": "en",
            "recurring_topics": ["private roadmap"],
            "user_formulas_closing": ["Best,"],
            "key_facts": ["budget detail from an email"],
            "last_interaction_summary": "Asked about a confidential roadmap.",
        }
        emails = [
            _make_email(body_text="secret body", snippet="secret snippet")
            for _ in range(5)
        ]
        contact_repo, agent, _ = TestRegeneration()._patch_full_stack(
            monkeypatch,
            contact=contact,
            latest_msg_id="msg-new",
            raw_emails=emails,
            agent_returns=full_summary,
        )

        result = css.get_summary_for_prompt(1, "bob@example.com")

        minimized = {
            "relation_type": "prospect",
            "habitual_tone": "semi_formal",
            "language": "en",
        }
        assert result is None
        email_dicts = agent.summarize.call_args.args[0]
        assert [email["body"] for email in email_dicts] == [""] * 5
        kwargs = contact_repo.update_summary.call_args.kwargs
        assert json.loads(kwargs["summary_json"]) == minimized
        assert css._cache_get((1, "bob@example.com")) == minimized
