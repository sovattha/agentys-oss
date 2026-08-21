# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the inbox label→email-id scan cache (perf).

`_collect_inbox_label_email_ids` runs an UNBOUNDED inbox scan + a full
`email_labels` JOIN + 2–3 store iterations on EVERY `/api/labels/counts` poll
(header-tab unread badges) and every label-filtered email-list open. These
tests pin the short-TTL, per-(account, unread_only) cache and its invalidation.

The heavy uncached body is mocked, so the tests are deterministic and never
touch the DB — they assert *how many times* the expensive scan actually runs.
"""

import pytest
from unittest.mock import patch

import app.api.labels as labels


@pytest.fixture(autouse=True)
def _clear_cache():
    # _invalidate_labels_cache() with no arg clears _inbox_label_ids_cache too.
    labels._invalidate_labels_cache()
    yield
    labels._invalidate_labels_cache()


def _fake_result(tag):
    """A stand-in (label→ids, inbox_total) tuple, like the real scan returns."""
    return ({"Action": {f"{tag}-1"}}, 7)


class TestInboxLabelIdsCache:
    def test_second_call_within_ttl_uses_cache(self):
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            return_value=_fake_result("a"),
        ) as heavy:
            r1 = labels._collect_inbox_label_email_ids(1)
            r2 = labels._collect_inbox_label_email_ids(1)
        assert heavy.call_count == 1  # the second call is served from cache
        assert r1 == r2 == _fake_result("a")

    def test_unread_only_variants_are_keyed_separately(self):
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            side_effect=[_fake_result("all"), _fake_result("unread")],
        ) as heavy:
            labels._collect_inbox_label_email_ids(1, unread_only=False)
            labels._collect_inbox_label_email_ids(1, unread_only=True)
            # Repeats of each variant are cache hits.
            labels._collect_inbox_label_email_ids(1, unread_only=False)
            labels._collect_inbox_label_email_ids(1, unread_only=True)
        assert heavy.call_count == 2

    def test_accounts_are_keyed_separately(self):
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            side_effect=[_fake_result("acct1"), _fake_result("acct2")],
        ) as heavy:
            labels._collect_inbox_label_email_ids(1)
            labels._collect_inbox_label_email_ids(2)
        assert heavy.call_count == 2

    def test_invalidate_account_drops_only_that_account(self):
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            side_effect=[
                _fake_result("a1"),
                _fake_result("a2"),
                _fake_result("a1b"),
            ],
        ) as heavy:
            labels._collect_inbox_label_email_ids(1)
            labels._collect_inbox_label_email_ids(2)
            labels._invalidate_labels_cache(account_id=1)
            labels._collect_inbox_label_email_ids(1)  # recomputed (dropped)
            labels._collect_inbox_label_email_ids(2)  # still cached
        assert heavy.call_count == 3

    def test_invalidate_all_drops_every_account(self):
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            side_effect=[_fake_result("x"), _fake_result("y")],
        ) as heavy:
            labels._collect_inbox_label_email_ids(1)
            labels._invalidate_labels_cache()  # no arg → clear all
            labels._collect_inbox_label_email_ids(1)
        assert heavy.call_count == 2

    def test_cache_expires_after_ttl(self):
        ttl = labels._INBOX_LABEL_IDS_CACHE_TTL
        # The wrapper calls time.monotonic() exactly once per invocation:
        # first stores at t=100, second reads at t=100+ttl+1 → expired → recompute.
        times = [100.0, 100.0 + ttl + 1.0]
        with patch.object(
            labels,
            "_collect_inbox_label_email_ids_uncached",
            side_effect=[_fake_result("first"), _fake_result("second")],
        ) as heavy, patch(
            "app.api.labels.time.monotonic", side_effect=times
        ):
            labels._collect_inbox_label_email_ids(1)
            labels._collect_inbox_label_email_ids(1)
        assert heavy.call_count == 2
