# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour ClaudeBatchAdapter."""

import pytest
from unittest.mock import MagicMock, patch

from app.adapters.llm.claude_batch_adapter import (
    BatchRequest,
    BatchResult,
    ClaudeBatchAdapter,
)


def _make_batch_request(**overrides) -> BatchRequest:
    defaults = dict(
        custom_id="req-1",
        model="claude-sonnet-4-20250514",
        system_prompt="Tu es un assistant.",
        user_prompt="Bonjour",
        max_tokens=512,
        temperature=0.5,
    )
    defaults.update(overrides)
    return BatchRequest(**defaults)


@pytest.fixture
def batch_adapter():
    """Crée un ClaudeBatchAdapter avec un client mocké."""
    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        adapter = ClaudeBatchAdapter(api_key="sk-test")
        yield adapter, mock_client


class TestBatchRequest:
    """Tests de l'entité BatchRequest."""

    def test_init_with_defaults(self):
        req = BatchRequest(
            custom_id="r1",
            model="m1",
            system_prompt="sys",
            user_prompt="usr",
        )
        assert req.custom_id == "r1"
        assert req.max_tokens == 512
        assert req.temperature == 0.5

    def test_init_with_custom_values(self):
        req = BatchRequest(
            custom_id="r2",
            model="m2",
            system_prompt="sys",
            user_prompt="usr",
            max_tokens=1024,
            temperature=0.8,
        )
        assert req.max_tokens == 1024
        assert req.temperature == 0.8


class TestBatchResult:
    """Tests de l'entité BatchResult."""

    def test_succeeded_result(self):
        result = BatchResult(
            custom_id="r1",
            status="succeeded",
            content="Réponse",
            input_tokens=100,
            output_tokens=50,
        )
        assert result.status == "succeeded"
        assert result.content == "Réponse"
        assert result.error == ""

    def test_errored_result(self):
        result = BatchResult(
            custom_id="r1",
            status="errored",
            error="Rate limit exceeded",
        )
        assert result.status == "errored"
        assert result.content == ""
        assert result.error == "Rate limit exceeded"

    def test_default_values(self):
        result = BatchResult(custom_id="r1", status="canceled")
        assert result.content == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.error == ""


class TestClaudeBatchAdapterSubmitBatch:
    """Tests de soumission de batch."""

    def test_submit_empty_returns_none(self, batch_adapter):
        adapter, client = batch_adapter
        result = adapter.submit_batch([])
        assert result is None
        client.beta.messages.batches.create.assert_not_called()

    def test_submit_returns_batch_id(self, batch_adapter):
        adapter, client = batch_adapter
        mock_batch = MagicMock()
        mock_batch.id = "batch-123"
        client.beta.messages.batches.create.return_value = mock_batch

        result = adapter.submit_batch([_make_batch_request()])
        assert result == "batch-123"

    def test_submit_error_returns_none(self, batch_adapter):
        adapter, client = batch_adapter
        client.beta.messages.batches.create.side_effect = Exception("API error")

        result = adapter.submit_batch([_make_batch_request()])
        assert result is None

    def test_submit_multiple_requests(self, batch_adapter):
        adapter, client = batch_adapter
        mock_batch = MagicMock()
        mock_batch.id = "batch-456"
        client.beta.messages.batches.create.return_value = mock_batch

        requests = [
            _make_batch_request(custom_id="r1"),
            _make_batch_request(custom_id="r2"),
            _make_batch_request(custom_id="r3"),
        ]
        result = adapter.submit_batch(requests)

        assert result == "batch-456"
        call_kwargs = client.beta.messages.batches.create.call_args.kwargs
        assert len(call_kwargs["requests"]) == 3


class TestClaudeBatchAdapterGetBatchStatus:
    """Tests de vérification du statut."""

    def test_get_status_returns_dict(self, batch_adapter):
        adapter, client = batch_adapter
        mock_batch = MagicMock()
        mock_batch.processing_status = "ended"
        mock_batch.request_counts.succeeded = 5
        mock_batch.request_counts.errored = 1
        mock_batch.request_counts.processing = 0
        mock_batch.request_counts.expired = 0
        mock_batch.request_counts.canceled = 0
        mock_batch.ended_at = "2025-01-15T12:00:00Z"
        client.beta.messages.batches.retrieve.return_value = mock_batch

        status = adapter.get_batch_status("batch-123")

        assert status["status"] == "ended"
        assert status["succeeded"] == 5
        assert status["errored"] == 1

    def test_get_status_error_returns_none(self, batch_adapter):
        adapter, client = batch_adapter
        client.beta.messages.batches.retrieve.side_effect = Exception("Network error")

        status = adapter.get_batch_status("batch-123")
        assert status is None


class TestClaudeBatchAdapterGetResults:
    """Tests de récupération des résultats."""

    def test_get_results_succeeded(self, batch_adapter):
        adapter, client = batch_adapter
        mock_result = MagicMock()
        mock_result.custom_id = "r1"
        mock_result.result.type = "succeeded"
        mock_msg = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Réponse batch"
        mock_msg.content = [mock_content]
        mock_msg.usage.input_tokens = 100
        mock_msg.usage.output_tokens = 50
        mock_result.result.message = mock_msg

        client.beta.messages.batches.results.return_value = [mock_result]

        results = adapter.get_batch_results("batch-123")

        assert len(results) == 1
        assert results[0].status == "succeeded"
        assert results[0].content == "Réponse batch"
        assert results[0].input_tokens == 100

    def test_get_results_errored(self, batch_adapter):
        adapter, client = batch_adapter
        mock_result = MagicMock()
        mock_result.custom_id = "r1"
        mock_result.result.type = "errored"
        mock_result.result.error = "Server error"
        client.beta.messages.batches.results.return_value = [mock_result]

        results = adapter.get_batch_results("batch-123")

        assert len(results) == 1
        assert results[0].status == "errored"
        assert "Server error" in results[0].error

    def test_get_results_expired(self, batch_adapter):
        adapter, client = batch_adapter
        mock_result = MagicMock()
        mock_result.custom_id = "r1"
        mock_result.result.type = "expired"
        client.beta.messages.batches.results.return_value = [mock_result]

        results = adapter.get_batch_results("batch-123")
        assert len(results) == 1
        assert results[0].status == "expired"

    def test_get_results_canceled(self, batch_adapter):
        adapter, client = batch_adapter
        mock_result = MagicMock()
        mock_result.custom_id = "r1"
        mock_result.result.type = "canceled"
        client.beta.messages.batches.results.return_value = [mock_result]

        results = adapter.get_batch_results("batch-123")
        assert len(results) == 1
        assert results[0].status == "canceled"

    def test_get_results_mixed_statuses(self, batch_adapter):
        adapter, client = batch_adapter
        r1 = MagicMock()
        r1.custom_id = "r1"
        r1.result.type = "succeeded"
        msg1 = MagicMock()
        c1 = MagicMock()
        c1.text = "Ok"
        msg1.content = [c1]
        msg1.usage.input_tokens = 10
        msg1.usage.output_tokens = 5
        r1.result.message = msg1

        r2 = MagicMock()
        r2.custom_id = "r2"
        r2.result.type = "errored"
        r2.result.error = "Timeout"

        client.beta.messages.batches.results.return_value = [r1, r2]

        results = adapter.get_batch_results("batch-123")
        assert len(results) == 2
        succeeded = [r for r in results if r.status == "succeeded"]
        errored = [r for r in results if r.status == "errored"]
        assert len(succeeded) == 1
        assert len(errored) == 1

    def test_get_results_api_error_returns_empty(self, batch_adapter):
        adapter, client = batch_adapter
        client.beta.messages.batches.results.side_effect = Exception("Network error")

        results = adapter.get_batch_results("batch-123")
        assert results == []
