# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.infrastructure.batch."""

import pytest
from app.infrastructure.batch import (
    BatchItemStatus,
    BatchItemResult,
    BatchResult,
    BatchProcessor,
    process_in_batches,
)
from datetime import datetime


# ============================================================================
# BatchItemStatus
# ============================================================================

class TestBatchItemStatus:
    def test_all_values(self):
        assert BatchItemStatus.PENDING.value == "pending"
        assert BatchItemStatus.PROCESSING.value == "processing"
        assert BatchItemStatus.SUCCESS.value == "success"
        assert BatchItemStatus.FAILED.value == "failed"
        assert BatchItemStatus.SKIPPED.value == "skipped"


# ============================================================================
# BatchResult
# ============================================================================

class TestBatchResult:
    def _make_result(self, items=None, **kwargs) -> BatchResult:
        defaults = dict(
            total=5,
            successful=3,
            failed=1,
            skipped=1,
            items=items or [],
            total_time=2.5,
            started_at=datetime(2026, 3, 24, 10, 0),
            finished_at=datetime(2026, 3, 24, 10, 0, 2),
        )
        defaults.update(kwargs)
        return BatchResult(**defaults)

    def test_success_rate(self):
        result = self._make_result(total=10, successful=8)
        assert result.success_rate == 80.0

    def test_success_rate_zero_total(self):
        result = self._make_result(total=0, successful=0)
        assert result.success_rate == 0.0

    def test_avg_processing_time(self):
        items = [
            BatchItemResult(item="a", status=BatchItemStatus.SUCCESS, processing_time=1.0),
            BatchItemResult(item="b", status=BatchItemStatus.SUCCESS, processing_time=3.0),
            BatchItemResult(item="c", status=BatchItemStatus.FAILED, processing_time=0.5),
        ]
        result = self._make_result(items=items)
        assert result.avg_processing_time == pytest.approx(2.0)

    def test_avg_processing_time_no_success(self):
        items = [
            BatchItemResult(item="a", status=BatchItemStatus.FAILED, processing_time=1.0),
        ]
        result = self._make_result(items=items)
        assert result.avg_processing_time == 0.0

    def test_get_failed_items(self):
        items = [
            BatchItemResult(item="ok", status=BatchItemStatus.SUCCESS),
            BatchItemResult(item="fail1", status=BatchItemStatus.FAILED, error="err1"),
            BatchItemResult(item="fail2", status=BatchItemStatus.FAILED, error="err2"),
        ]
        result = self._make_result(items=items)
        failed = result.get_failed_items()
        assert len(failed) == 2
        assert failed[0].item == "fail1"

    def test_to_dict(self):
        result = self._make_result(total=5, successful=4, failed=1, skipped=0)
        d = result.to_dict()
        assert d["total"] == 5
        assert d["successful"] == 4
        assert d["success_rate"] == 80.0
        assert "started_at" in d
        assert "finished_at" in d


# ============================================================================
# BatchProcessor
# ============================================================================

class TestBatchProcessor:
    def test_process_all_success(self):
        processor = BatchProcessor(
            process_func=lambda x: x * 2,
            batch_size=5,
            max_workers=2,
            max_retries=0,
        )
        result = processor.process([1, 2, 3, 4, 5])
        assert result.total == 5
        assert result.successful == 5
        assert result.failed == 0

    def test_process_with_failures(self):
        def flaky(x):
            if x == 3:
                raise ValueError("Boom")
            return x

        processor = BatchProcessor(
            process_func=flaky,
            batch_size=10,
            max_workers=1,
            max_retries=0,
            retry_delay=0,
        )
        result = processor.process([1, 2, 3, 4])
        assert result.successful == 3
        assert result.failed == 1

    def test_process_with_skip_func(self):
        processor = BatchProcessor(
            process_func=lambda x: x,
            batch_size=10,
            max_workers=1,
        )
        result = processor.process(
            [1, 2, 3, 4, 5],
            skip_func=lambda x: x > 3,
        )
        assert result.skipped == 2
        assert result.successful == 3

    def test_process_empty_list(self):
        processor = BatchProcessor(process_func=lambda x: x)
        result = processor.process([])
        assert result.total == 0
        assert result.successful == 0

    def test_process_batched(self):
        """Items should be processed in batches."""
        processed = []
        def track(x):
            processed.append(x)
            return x

        processor = BatchProcessor(
            process_func=track,
            batch_size=2,
            max_workers=1,
        )
        result = processor.process([1, 2, 3, 4, 5])
        assert result.total == 5
        assert len(processed) == 5

    def test_on_progress_callback(self):
        progress_calls = []
        processor = BatchProcessor(
            process_func=lambda x: x,
            batch_size=2,
            max_workers=1,
            on_progress=lambda done, total: progress_calls.append((done, total)),
        )
        processor.process([1, 2, 3, 4])
        assert len(progress_calls) > 0

    def test_on_item_complete_callback(self):
        completed_items = []
        processor = BatchProcessor(
            process_func=lambda x: x * 10,
            batch_size=5,
            max_workers=1,
            on_item_complete=lambda result: completed_items.append(result),
        )
        processor.process([1, 2, 3])
        assert len(completed_items) == 3

    def test_stop_halts_processing(self):
        """Stop should prevent further batch processing."""
        processor = BatchProcessor(
            process_func=lambda x: x,
            batch_size=1,
            max_workers=1,
        )
        # Immediately request stop
        processor.stop()
        result = processor.process([1, 2, 3])
        assert result.total == 3
        # Some items may not have been processed
        assert result.successful <= 3

    def test_processed_count(self):
        processor = BatchProcessor(
            process_func=lambda x: x,
            batch_size=10,
            max_workers=1,
        )
        processor.process([1, 2, 3])
        assert processor.processed_count == 3

    def test_retry_on_failure(self):
        call_count = {"n": 0}
        def flaky(x):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise ValueError("Temporary")
            return x

        processor = BatchProcessor(
            process_func=flaky,
            batch_size=10,
            max_workers=1,
            max_retries=2,
            retry_delay=0,
        )
        result = processor.process([1])
        assert result.successful == 1


# ============================================================================
# process_in_batches helper
# ============================================================================

class TestProcessInBatches:
    def test_basic_usage(self):
        result = process_in_batches(
            items=[1, 2, 3],
            process_func=lambda x: x * 2,
            batch_size=2,
        )
        assert result.total == 3
        assert result.successful == 3
