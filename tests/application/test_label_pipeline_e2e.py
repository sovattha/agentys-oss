# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
End-to-end test of the cost-optimised labelling pipeline.

Feeds 100 realistic emails through ``LabelEmailUseCase.execute_batch`` and
asserts that the LLM is invoked on a small fraction of them. This is the
regression test that catches "someone disabled a rule branch and the pipeline
silently fell back to the LLM for everything".

Assertion thresholds:
- LLM calls ≤ 5 for a fresh 100-email run (fixtures tuned for high rules-only coverage)
- LLM calls == 0 on a second identical run (template cache must kick in)
- Batch size effective: max(1, ceil(deferred/10)) LLM calls — never per-email
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple


from app.application.label_email import LabelEmailUseCase
from app.domain.entities import Email
from app.domain.entities.email_labels import DefaultLabel, get_default_labels
from app.domain.ports import LLMPort, LLMResponse
from app.infrastructure.adapters.template_label_cache import TemplateLabelCache


class _CountingLLM(LLMPort):
    """Returns a canned batch response; counts every call."""

    def __init__(self):
        self.calls = 0
        self.batch_sizes: List[int] = []

    @property
    def name(self) -> str:
        return "counting"

    @property
    def model(self) -> str:
        return "fake"

    def complete(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.5) -> LLMResponse:
        self.calls += 1
        # Count how many "EMAIL N" markers are in the user prompt
        n_emails = user.count("=== EMAIL ")
        self.batch_sizes.append(max(n_emails, 1))
        # Return a batch response covering all indices
        if n_emails > 0:
            items = []
            for i in range(n_emails):
                label = "FYI" if i % 2 == 0 else "Noise"
                items.append(f'{{"idx":{i},"label":"{label}","confidence":0.88,"reason":"batched"}}')
            return LLMResponse(
                content='{"classifications":[' + ",".join(items) + "]}",
                input_tokens=500 + 50 * n_emails,
                output_tokens=50 * n_emails,
                model="fake",
            )
        return LLMResponse(
            content='{"labels":[{"name":"FYI","confidence":0.85,"reason":"fallback"}]}',
            input_tokens=400,
            output_tokens=30,
            model="fake",
        )

    def complete_stream(self, *args, **kwargs):
        yield from ()


def _mk(
    subject: str,
    sender: str,
    body: str = "body content",
    is_cc: bool = False,
    headers: Tuple[Tuple[str, str], ...] = (),
    email_id: str = "",
    days_ago: int = 1,
) -> Tuple[Email, dict]:
    """Build (Email, raw_metadata) tuple ready for execute_batch input."""
    email = Email(
        id=email_id or f"m-{abs(hash((subject, sender, body))) % 10_000_000}",
        sender=sender,
        subject=subject,
        body=body,
        received_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    raw_meta = {"classification_headers": dict(headers), "sender_is_real_contact": False}
    return email, raw_meta


def _build_fixture_100() -> List[dict]:
    """Build a realistic 100-email inbox snapshot.

    Distribution:
    - 30 marketing/newsletters (List-Unsubscribe header or known marketing domain)
    - 15 noreply/donotreply senders
    - 10 transactional (github/slack/notion/zoom)
    - 10 calendar invitations
    - 5 security alerts from real senders
    - 10 direct questions from unknown senders (builtin question detection)
    - 20 ambiguous short-body emails (should hit LLM)
    """
    inputs: List[dict] = []

    # 30 marketing — List-Unsubscribe header is decisive
    for i in range(30):
        email, raw = _mk(
            subject=f"Weekly digest {i}",
            sender=f"news{i}@example-marketing-{i}.com",
            body="Read more on our platform. Click here to manage your preferences.",
            headers=(("list-unsubscribe", "<mailto:u@x.com>"),),
            email_id=f"mkt-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    # 15 noreply
    for i in range(15):
        email, raw = _mk(
            subject=f"Order confirmation {i}",
            sender=f"noreply@some-shop-{i}.com",
            body="Your order has been received.",
            email_id=f"nr-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    # 10 transactional (known domains)
    trans_senders = [
        ("notifications@github.com", "New comment on your PR"),
        ("notifications@github.com", "Weekly digest"),
        ("no-reply@slack.com", "Daily recap"),
        ("team@notion.so", "Shared page update"),
        ("events@zoom.us", "Your recording is ready"),
        ("noreply@asana.com", "Tasks due this week"),
        ("team@linear.app", "Weekly cycle summary"),
        ("notifications@figma.com", "Comment on design"),
        ("no-reply@calendly.com", "Event scheduled"),
        ("no-reply@loom.com", "Your video was viewed"),
    ]
    for i, (sender, subj) in enumerate(trans_senders):
        s = sender.replace("noreply@", "alerts@").replace("no-reply@", "team@")
        email, raw = _mk(subject=subj, sender=s, body="Update notification", email_id=f"tx-{i}")
        inputs.append({"email": email, "raw_metadata": raw})

    # 10 calendar invitations
    for i in range(10):
        email, raw = _mk(
            subject=f"Invitation: Meeting {i}",
            sender=f"organiser{i}@realcompany-{i}.com",
            body="You are invited to the meeting.",
            email_id=f"cal-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    # 5 security alerts (real sender domain, security keyword triggers Action)
    for i in range(5):
        email, raw = _mk(
            subject=f"Unusual sign-in on your account {i}",
            sender=f"security@legit-service-{i}.com",
            body="If this wasn't you, secure your account immediately.",
            email_id=f"sec-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    # 10 questions from unknown senders (smart question detection → Action)
    for i in range(10):
        email, raw = _mk(
            subject="Quick question about the proposal",
            sender=f"prospect{i}@unknown-co-{i}.com",
            body="Hi, can you send me the updated pricing? Thanks.",
            email_id=f"q-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    # 20 ambiguous emails → these reach the LLM (no keyword matches)
    for i in range(20):
        email, raw = _mk(
            subject=f"xyz notes {i}",
            sender=f"random{i}@totally-unknown-domain-{i}.xyz",
            body=f"lorem ipsum dolor sit amet consectetur adipiscing elit {i}",
            email_id=f"amb-{i}",
        )
        inputs.append({"email": email, "raw_metadata": raw})

    return inputs


def test_pipeline_100_emails_keeps_llm_calls_low(tmp_path):
    """Happy path: 100 typical inbox emails should produce at most 3 LLM calls."""
    llm = _CountingLLM()
    cache = TemplateLabelCache(str(tmp_path))
    use_case = LabelEmailUseCase(
        llm=llm,
        labels=get_default_labels(),
        rules=[],
        template_cache=cache,
    )

    inputs = _build_fixture_100()
    assert len(inputs) == 100

    assignments = use_case.execute_batch(inputs, batch_size=10)
    assert len(assignments) == 100
    assert all(a.default_label for a in assignments), "Every email must get a default label"

    # Upper bound: ceil(20 ambiguous / 10 batch_size) = 2 batch calls.
    # Budget 3 to absorb any single-email retries.
    assert llm.calls <= 3, (
        f"Expected ≤3 LLM calls for 100 emails, got {llm.calls} (batch_sizes={llm.batch_sizes}). "
        f"Regression: a rules branch has stopped firing."
    )

    # Verify distribution: rule-labelled emails span multiple labels
    labels_counter = {}
    for a in assignments:
        labels_counter[a.default_label] = labels_counter.get(a.default_label, 0) + 1
    assert DefaultLabel.NOISE.value in labels_counter
    assert DefaultLabel.ACTION.value in labels_counter
    assert DefaultLabel.FYI.value in labels_counter


def test_pipeline_second_run_hits_cache(tmp_path):
    """Re-running the same inbox should fire 0 LLM calls thanks to the template cache."""
    cache = TemplateLabelCache(str(tmp_path))

    llm1 = _CountingLLM()
    use_case_1 = LabelEmailUseCase(
        llm=llm1, labels=get_default_labels(), rules=[], template_cache=cache,
    )
    inputs = _build_fixture_100()
    use_case_1.execute_batch(inputs, batch_size=10)
    calls_1 = llm1.calls
    assert calls_1 >= 1, "Fixture must trigger at least one LLM call to prime the cache"

    llm2 = _CountingLLM()
    use_case_2 = LabelEmailUseCase(
        llm=llm2, labels=get_default_labels(), rules=[], template_cache=cache,
    )
    inputs_2 = _build_fixture_100()
    for inp in inputs_2:
        inp["email"].id = inp["email"].id + "-v2"
    use_case_2.execute_batch(inputs_2, batch_size=10)

    assert llm2.calls == 0, (
        f"Second run should hit cache for all previously-classified templates. "
        f"Got {llm2.calls} LLM calls (first run: {calls_1})."
    )


def test_cache_stats_reflect_hits_and_misses(tmp_path):
    """The cache stats API must reveal the hit_rate after a two-run workload."""
    cache = TemplateLabelCache(str(tmp_path))
    use_case = LabelEmailUseCase(
        llm=_CountingLLM(), labels=get_default_labels(), rules=[], template_cache=cache,
    )

    use_case.execute_batch(_build_fixture_100(), batch_size=10)
    stats_1 = cache.stats()
    assert stats_1["session_misses"] >= 1

    inputs_2 = _build_fixture_100()
    for inp in inputs_2:
        inp["email"].id = inp["email"].id + "-v2"
    use_case.execute_batch(inputs_2, batch_size=10)
    stats_2 = cache.stats()

    assert stats_2["session_hits"] >= 1, "Second run should produce cache hits"
    assert stats_2["llm_calls_saved"] == stats_2["session_hits"]
    assert 0.0 <= stats_2["hit_rate"] <= 1.0
    assert stats_2["entries"] >= 1
