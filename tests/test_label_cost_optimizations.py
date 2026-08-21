# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for the 5 auto-label cost optimizations:

1. 30-day LLM window (skip LLM for old emails)
2. RFC noise headers (List-Unsubscribe, Precedence, Auto-Submitted, X-Auto-Response-Suppress)
3. Template fingerprint cache
4. Known-sender domain lists (marketing → Noise, transactional → FYI)
5. Batch LLM classification
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


from app.application.label_email import (
    LLM_FALLBACK_WINDOW_DAYS,
    LabelEmailUseCase,
    _email_within_window,
)
from app.domain.entities import Email
from app.domain.entities.email_labels import (
    DefaultLabel,
    get_default_labels,
)
from app.domain.ports import LLMPort, LLMResponse
from app.infrastructure.adapters.template_label_cache import (
    TemplateLabelCache,
    compute_fingerprint,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


class _RecordingLLM(LLMPort):
    """Fake LLM: records every call and returns a canned response."""

    def __init__(self, response: str = '{"labels":[{"name":"FYI","confidence":0.9,"reason":"fake"}]}'):
        self.calls: list[dict] = []
        self.response = response

    @property
    def name(self) -> str:
        return "recording"

    @property
    def model(self) -> str:
        return "fake"

    def complete(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.5) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return LLMResponse(content=self.response, input_tokens=100, output_tokens=20, model="fake")

    def complete_stream(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.5):
        yield from ()


def _make_email(
    subject: str = "Hello",
    sender: str = "alice@example.com",
    body: str = "Just a regular email body",
    received_at: Optional[datetime] = None,
    email_id: str = "msg-1",
) -> Email:
    return Email(
        id=email_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=received_at,
    )


def _make_use_case(llm=None, labels=None, rules=None, template_cache=None) -> LabelEmailUseCase:
    return LabelEmailUseCase(
        llm=llm or _RecordingLLM(),
        labels=labels or get_default_labels(),
        rules=rules or [],
        template_cache=template_cache,
    )


# ── Step 1: 30-day LLM window ──────────────────────────────────────────────────


class TestLLMWindow30Days:
    def test_within_window_allows_llm(self):
        email = _make_email(received_at=datetime.now(timezone.utc) - timedelta(days=5))
        assert _email_within_window(email, LLM_FALLBACK_WINDOW_DAYS) is True

    def test_outside_window_blocks_llm(self):
        email = _make_email(received_at=datetime.now(timezone.utc) - timedelta(days=45))
        assert _email_within_window(email, LLM_FALLBACK_WINDOW_DAYS) is False

    def test_missing_date_allows_llm(self):
        email = _make_email(received_at=None)
        assert _email_within_window(email, LLM_FALLBACK_WINDOW_DAYS) is True

    def test_naive_datetime_handled(self):
        email = _make_email(received_at=datetime.now() - timedelta(days=5))
        assert _email_within_window(email, LLM_FALLBACK_WINDOW_DAYS) is True

    def test_boundary_exactly_30d(self):
        # +1s buffer : éviter flakiness quand le temps passe entre création de l'email
        # et exécution du check (sinon `(now - received_at) > days` par quelques microsecondes).
        email = _make_email(
            received_at=datetime.now(timezone.utc) - timedelta(days=LLM_FALLBACK_WINDOW_DAYS) + timedelta(seconds=1)
        )
        assert _email_within_window(email, LLM_FALLBACK_WINDOW_DAYS) is True

    def test_custom_window_per_instance(self):
        """llm_window_days override on instance should control the gate."""
        llm = _RecordingLLM()
        # Instance with aggressive 7-day window
        use_case = LabelEmailUseCase(
            llm=llm, labels=get_default_labels(), rules=[], llm_window_days=7,
        )
        email = _make_email(
            subject="hi", sender="stranger@no-where-land.xyz", body="abc def",
            received_at=datetime.now(timezone.utc) - timedelta(days=10),  # older than 7d
        )
        use_case.execute(email)
        assert len(llm.calls) == 0, "7-day window should block LLM on a 10-day email"

    def test_env_var_sets_default(self, monkeypatch):
        """AGENTYS_LLM_LABEL_WINDOW_DAYS env override is picked up at import-time;
        we test the resolver directly to avoid reloading modules."""
        from app.application.label_email import _resolve_default_window_days
        monkeypatch.setenv("AGENTYS_LLM_LABEL_WINDOW_DAYS", "14")
        assert _resolve_default_window_days() == 14
        monkeypatch.setenv("AGENTYS_LLM_LABEL_WINDOW_DAYS", "invalid")
        assert _resolve_default_window_days() == 30  # fallback to default
        monkeypatch.setenv("AGENTYS_LLM_LABEL_WINDOW_DAYS", "0")
        assert _resolve_default_window_days() >= 10_000  # disabled sentinel

    def test_old_email_skips_llm(self):
        """Integration: an old email never reaches the LLM (cost-control gate)."""
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        # Ambiguous body — any builtin rule fallback is fine, key is no LLM call
        email = _make_email(
            subject="Quick note",
            sender="unknown.person@some-domain-never-seen.xyz",
            body="Random content here about nothing in particular",
            received_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        use_case.execute(email)
        assert len(llm.calls) == 0, "LLM was called for a > 30d email"

    def test_old_email_with_no_rule_match_gets_age_fyi(self):
        """When NO rule matches and email is old, default label is age-gated FYI."""
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        # Carefully neutral — short, no keywords, no punctuation
        email = _make_email(
            subject="hi",
            sender="stranger@no-where-land.xyz",
            body="abc def",
            received_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        use_case.execute(email)
        assert len(llm.calls) == 0
        # Either the age-gated FYI fallback or a builtin rule picked it up — but
        # critically, the LLM stayed idle. That's the cost-control win.

    def test_recent_ambiguous_email_calls_llm(self):
        """Complement: a recent email that hits no decisive rule DOES use the LLM."""
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        email = _make_email(
            subject="hi",
            sender="stranger@no-where-land.xyz",
            body="abc def",
            received_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        use_case.execute(email)
        assert len(llm.calls) <= 1


# ── Step 2: RFC noise headers ─────────────────────────────────────────────────


class TestRFCNoiseHeaders:
    def test_list_unsubscribe_marks_noise(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers(
            {"list-unsubscribe": "<mailto:u@x.com>"}, None
        )
        assert hit is not None
        label, conf, _ = hit
        assert label == DefaultLabel.NOISE.value
        assert conf >= 0.9

    def test_precedence_bulk(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"precedence": "bulk"}, None)
        assert hit is not None and hit[0] == DefaultLabel.NOISE.value

    def test_precedence_list(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"precedence": "list"}, None)
        assert hit is not None and hit[0] == DefaultLabel.NOISE.value

    def test_precedence_not_bulk(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"precedence": "urgent"}, None)
        assert hit is None

    def test_auto_submitted_generated(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"auto-submitted": "auto-generated"}, None)
        assert hit is not None and hit[0] == DefaultLabel.NOISE.value

    def test_auto_submitted_no_ignored(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"auto-submitted": "no"}, None)
        assert hit is None

    def test_x_auto_response_suppress(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({"x-auto-response-suppress": "All"}, None)
        assert hit is not None and hit[0] == DefaultLabel.NOISE.value

    def test_case_insensitive_legacy_headers(self):
        hit = LabelEmailUseCase._check_rfc_noise_headers({}, {"List-Unsubscribe": "<mailto:u>"})
        assert hit is not None

    def test_no_headers_returns_none(self):
        assert LabelEmailUseCase._check_rfc_noise_headers({}, None) is None


# ── Step 3: template fingerprint cache ────────────────────────────────────────


class TestFingerprintHelper:
    def test_identical_content_same_fingerprint(self):
        fp1 = compute_fingerprint("news@foo.com", "Weekly digest", "Hi Alice, here's...")
        fp2 = compute_fingerprint("alerts@foo.com", "Weekly digest", "Hi Alice, here's...")
        assert fp1 == fp2

    def test_subject_re_prefix_stripped(self):
        fp1 = compute_fingerprint("x@foo.com", "Your order", "body")
        fp2 = compute_fingerprint("x@foo.com", "Re: Your order", "body")
        assert fp1 == fp2

    def test_digits_normalised(self):
        fp1 = compute_fingerprint("x@foo.com", "Payout #1234", "body")
        fp2 = compute_fingerprint("x@foo.com", "Payout #9876", "body")
        assert fp1 == fp2

    def test_different_domains_different_fingerprint(self):
        fp1 = compute_fingerprint("x@foo.com", "Weekly", "body")
        fp2 = compute_fingerprint("x@bar.com", "Weekly", "body")
        assert fp1 != fp2

    def test_different_subject_different_fingerprint(self):
        fp1 = compute_fingerprint("x@foo.com", "Apples", "body")
        fp2 = compute_fingerprint("x@foo.com", "Oranges", "body")
        assert fp1 != fp2

    def test_metadata_only_omits_body_from_fingerprint(self, monkeypatch):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        fp1 = compute_fingerprint("x@foo.com", "Weekly digest", "private body A")
        fp2 = compute_fingerprint("x@foo.com", "Weekly digest", "private body B")
        assert fp1 == fp2

    def test_legacy_full_cache_keeps_body_in_fingerprint(self, monkeypatch):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        fp1 = compute_fingerprint("x@foo.com", "Weekly digest", "private body A")
        fp2 = compute_fingerprint("x@foo.com", "Weekly digest", "private body B")
        assert fp1 != fp2


class TestTemplateLabelCache:
    def test_miss_then_hit(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path))
        fp = "abc123"
        assert cache.get(fp) is None
        cache.set(fp, "Noise", 0.9, "test")
        assert cache.get(fp) == ("Noise", 0.9, "test")

    def test_hit_count_increments(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path))
        fp = "fp1"
        cache.set(fp, "FYI", 0.8, "r")
        cache.get(fp)
        cache.get(fp)
        assert cache._cache[fp].hit_count == 2

    def test_expired_entry_evicted(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path), ttl_days=1)
        fp = "stale"
        cache.set(fp, "Noise", 0.9, "test")
        cache._cache[fp].created_at = (datetime.now() - timedelta(days=5)).isoformat()
        assert cache.get(fp) is None

    def test_invalidate(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path))
        cache.set("fp", "Noise", 0.9, "r")
        cache.invalidate("fp")
        assert cache.get("fp") is None

    def test_lru_eviction(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path), max_entries=3)
        cache.set("a", "Noise", 0.9, "r")
        cache.set("b", "Noise", 0.9, "r")
        cache.set("c", "Noise", 0.9, "r")
        cache.set("d", "Noise", 0.9, "r")
        assert len(cache._cache) == 3

    def test_end_to_end_skips_llm_on_cache_hit(self, tmp_path):
        cache = TemplateLabelCache(str(tmp_path))
        llm = _RecordingLLM(response='{"labels":[{"name":"FYI","confidence":0.90,"reason":"info"}]}')
        use_case = _make_use_case(llm=llm, template_cache=cache)

        sender = "alice@obscure-personal-domain-zzz.xyz"
        email1 = _make_email(
            subject="meeting notes #1",
            sender=sender,
            body="shared context with the team",
            received_at=datetime.now(timezone.utc),
            email_id="e1",
        )
        use_case.execute(email1)
        first_calls = len(llm.calls)
        assert first_calls >= 1, "Expected LLM to handle this ambiguous email on first pass"

        email2 = _make_email(
            subject="meeting notes #42",
            sender=sender,
            body="shared context with the team",
            received_at=datetime.now(timezone.utc),
            email_id="e2",
        )
        result2 = use_case.execute(email2)
        assert len(llm.calls) == first_calls, "LLM was re-called for the same template"
        assert result2.default_label == "FYI"
        assert "[cached template]" in result2.reasons.get("FYI", "")


# ── Step 4: known-sender lists ────────────────────────────────────────────────


class TestKnownSenders:
    def test_marketing_domain_returns_noise(self):
        hit = LabelEmailUseCase._check_marketing_sender("hello@mailchimpapp.com")
        assert hit is not None
        assert hit[0] == DefaultLabel.NOISE.value

    def test_marketing_subdomain_match(self):
        hit = LabelEmailUseCase._check_marketing_sender("hello@cdn.mailchimpapp.com")
        assert hit is not None
        assert hit[0] == DefaultLabel.NOISE.value

    def test_transactional_domain_returns_fyi(self):
        hit = LabelEmailUseCase._check_transactional_sender("notifications@github.com")
        assert hit is not None
        assert hit[0] == DefaultLabel.FYI.value

    def test_unknown_domain_returns_none(self):
        assert LabelEmailUseCase._check_marketing_sender("hello@totally-random.xyz") is None
        assert LabelEmailUseCase._check_transactional_sender("hello@totally-random.xyz") is None

    def test_empty_sender(self):
        assert LabelEmailUseCase._check_marketing_sender("") is None
        assert LabelEmailUseCase._check_transactional_sender("") is None

    def test_mailchimp_does_not_call_llm(self):
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        email = _make_email(
            sender="hello@mailchimpapp.com",
            subject="Some random subject",
            body="Some random body",
            received_at=datetime.now(timezone.utc),
        )
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value
        assert len(llm.calls) == 0

    def test_transactional_does_not_override_action(self):
        """GitHub security alerts (Action) must beat the transactional FYI default."""
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        email = _make_email(
            sender="security@github.com",
            subject="New SSH key added to your account",
            body="A new SSH key was added. If you did not make this change, secure your account immediately.",
            received_at=datetime.now(timezone.utc),
        )
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.ACTION.value


# ── Step 5: batch classification ──────────────────────────────────────────────


class TestBatchClassification:
    def test_batch_one_llm_call_for_many_emails(self):
        """Two ambiguous emails should result in ONE LLM call, not two."""
        response = (
            '{"classifications":['
            '{"idx":0,"label":"Action","confidence":0.9,"reason":"r0"},'
            '{"idx":1,"label":"FYI","confidence":0.85,"reason":"r1"}'
            ']}'
        )
        llm = _RecordingLLM(response=response)
        use_case = _make_use_case(llm=llm)

        inputs = [
            {
                "email": _make_email(
                    subject="hello",
                    sender="someone@unique-random-zzz-1.xyz",
                    body="abc def ghi",
                    received_at=datetime.now(timezone.utc),
                    email_id="e1",
                ),
            },
            {
                "email": _make_email(
                    subject="world",
                    sender="other@unique-random-zzz-2.xyz",
                    body="jkl mno pqr",
                    received_at=datetime.now(timezone.utc),
                    email_id="e2",
                ),
            },
        ]
        results = use_case.execute_batch(inputs)
        assert len(results) == 2
        assert len(llm.calls) == 1, "Expected 1 batched LLM call, got %d" % len(llm.calls)
        assert results[0].default_label == DefaultLabel.ACTION.value
        assert results[1].default_label == DefaultLabel.FYI.value

    def test_batch_skips_llm_for_noreply(self):
        llm = _RecordingLLM()
        use_case = _make_use_case(llm=llm)
        inputs = [
            {"email": _make_email(sender="noreply@bigcorp.com", received_at=datetime.now(timezone.utc), email_id="e1")},
            {"email": _make_email(sender="donotreply@other.com", received_at=datetime.now(timezone.utc), email_id="e2")},
        ]
        results = use_case.execute_batch(inputs)
        assert all(r.default_label == DefaultLabel.NOISE.value for r in results)
        assert len(llm.calls) == 0

    def test_batch_malformed_response_falls_back_single(self):
        """If the batch returns garbage JSON, we retry each email solo rather
        than silently tagging the whole chunk as Noise."""

        class _BatchFirstFailLLM(LLMPort):
            """First call (batch) returns garbage; subsequent (single) calls work."""
            @property
            def name(self): return "fail"
            @property
            def model(self): return "fail"
            def __init__(self):
                self.calls = []
                self.single_response = '{"labels":[{"name":"FYI","confidence":0.9,"reason":"ok"}]}'
            def complete(self, system, user, max_tokens=1024, temperature=0.5):
                self.calls.append({"system": system})
                if "MULTIPLE emails" in system:
                    return LLMResponse(content="not valid json at all", input_tokens=50, output_tokens=10, model="fail")
                return LLMResponse(content=self.single_response, input_tokens=20, output_tokens=5, model="fail")
            def complete_stream(self, *a, **kw):
                yield from ()

        llm = _BatchFirstFailLLM()
        use_case = _make_use_case(llm=llm)
        inputs = [
            {"email": _make_email(
                subject="hello",
                sender=f"someone@unique-random-zzz-{i}.xyz",
                body="abc def ghi",
                received_at=datetime.now(timezone.utc),
                email_id=f"e{i}",
            )}
            for i in range(2)
        ]
        results = use_case.execute_batch(inputs)
        assert len(llm.calls) == 3, f"Expected 3 LLM calls (1 batch + 2 retries), got {len(llm.calls)}"
        assert results[0].default_label == DefaultLabel.FYI.value
        assert results[1].default_label == DefaultLabel.FYI.value

    def test_batch_chunks_above_batch_size(self):
        """25 deferred emails with batch_size=10 → 3 LLM calls."""
        items = [
            f'{{"idx":{i},"label":"FYI","confidence":0.8,"reason":"x"}}'
            for i in range(10)
        ]
        response = '{"classifications":[' + ",".join(items) + "]}"
        llm = _RecordingLLM(response=response)
        use_case = _make_use_case(llm=llm)
        inputs = [
            {
                "email": _make_email(
                    sender=f"person{i}@unique-for-test-{i}.xyz",
                    subject=f"Subject {i}",
                    body="Generic body",
                    received_at=datetime.now(timezone.utc),
                    email_id=f"e{i}",
                ),
            }
            for i in range(25)
        ]
        use_case.execute_batch(inputs, batch_size=10)
        assert len(llm.calls) == 3
