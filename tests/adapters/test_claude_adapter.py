# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour ClaudeAdapter."""

import pytest
from unittest.mock import MagicMock, patch

from app.domain.ports import LLMResponse
from app.domain.exceptions import (
    LLMAuthenticationError,
    LLMBillingError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMContextLengthError,
    LLMResponseError,
    LLMModelNotFoundError,
    InvalidBoundsError,
)

# anthropic is already in sys.modules (installed), so we can import and patch normally
from app.adapters.llm.claude_adapter import ClaudeAdapter


@pytest.fixture
def claude_adapter():
    """Crée un ClaudeAdapter avec un client mocké."""
    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        adapter = ClaudeAdapter(model="test-model", api_key="sk-test")
        yield adapter, mock_client


def _make_mock_response(text="Réponse", input_tokens=10, output_tokens=5):
    """Crée une réponse mock de l'API Anthropic."""
    mock_response = MagicMock()
    mock_content = MagicMock()
    mock_content.text = text
    mock_response.content = [mock_content]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    return mock_response


class TestClaudeAdapterInit:
    """Tests d'initialisation."""

    def test_raises_without_api_key(self):
        # NB : ne pas mocker `os.environ.get` globalement — cela casse
        # `distro.LinuxDistribution.__init__` (importé transitivement par
        # `anthropic._base_client`) qui query des variables d'env au moment
        # de l'init. Un `patch.dict` ciblé avec `clear` suffit pour
        # reproduire "no API key" sans perturber le reste de l'environnement.
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            with patch("anthropic.Anthropic"):
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    ClaudeAdapter(api_key=None)

    def test_name_is_claude(self, claude_adapter):
        adapter, _ = claude_adapter
        assert adapter.name == "claude"

    def test_model_returns_configured_model(self):
        with patch("anthropic.Anthropic"):
            adapter = ClaudeAdapter(model="claude-3-haiku", api_key="sk-test")
            assert adapter.model == "claude-3-haiku"

    def test_is_available_with_key(self, claude_adapter):
        adapter, _ = claude_adapter
        assert adapter.is_available() is True


class TestClaudeAdapterComplete:
    """Tests de la méthode complete."""

    def test_returns_llm_response(self, claude_adapter):
        adapter, client = claude_adapter
        client.messages.create.return_value = _make_mock_response("Bonjour!", 100, 50)

        response = adapter.complete(system="sys", user="usr")

        assert isinstance(response, LLMResponse)
        assert response.content == "Bonjour!"
        assert response.input_tokens == 100
        assert response.output_tokens == 50

    def test_passes_system_as_cache_block(self, claude_adapter):
        adapter, client = claude_adapter
        client.messages.create.return_value = _make_mock_response()

        adapter.complete(system="Mon système", user="Mon message")

        call_kwargs = client.messages.create.call_args.kwargs
        system_block = call_kwargs["system"]
        assert len(system_block) == 1
        assert system_block[0]["type"] == "text"
        assert system_block[0]["text"] == "Mon système"
        assert system_block[0]["cache_control"] == {"type": "ephemeral"}

    def test_passes_temperature_when_provided(self, claude_adapter):
        adapter, client = claude_adapter
        client.messages.create.return_value = _make_mock_response()

        adapter.complete(system="sys", user="usr", temperature=0.7)

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7

    def test_omits_temperature_when_none(self, claude_adapter):
        adapter, client = claude_adapter
        client.messages.create.return_value = _make_mock_response()

        adapter.complete(system="sys", user="usr", temperature=None)

        call_kwargs = client.messages.create.call_args.kwargs
        assert "temperature" not in call_kwargs

    def test_raises_invalid_bounds_for_zero_max_tokens(self, claude_adapter):
        adapter, _ = claude_adapter
        with pytest.raises(InvalidBoundsError):
            adapter.complete(system="sys", user="usr", max_tokens=0)

    def test_raises_invalid_bounds_for_negative_max_tokens(self, claude_adapter):
        adapter, _ = claude_adapter
        with pytest.raises(InvalidBoundsError):
            adapter.complete(system="sys", user="usr", max_tokens=-1)

    def test_raises_on_empty_response_content(self, claude_adapter):
        adapter, client = claude_adapter
        mock_resp = MagicMock()
        mock_resp.content = []
        client.messages.create.return_value = mock_resp

        with pytest.raises(LLMResponseError):
            adapter.complete(system="sys", user="usr")

    def test_raises_on_missing_text_attribute(self, claude_adapter):
        adapter, client = claude_adapter
        mock_resp = MagicMock()
        mock_content = MagicMock(spec=[])  # No text attribute
        mock_resp.content = [mock_content]
        client.messages.create.return_value = mock_resp

        with pytest.raises(LLMResponseError):
            adapter.complete(system="sys", user="usr")


class TestClaudeAdapterExceptionMapping:
    """Tests du mapping d'exceptions Anthropic vers domaine."""

    @staticmethod
    def _make_exc(exc_type_name: str, message: str = "", response=None):
        """Crée une exception avec le __class__.__name__ voulu."""
        # Create a new exception class with the desired name
        exc_class = type(exc_type_name, (Exception,), {})
        exc = exc_class(message)
        if response is not None:
            exc.response = response
        return exc

    def test_authentication_error_maps_to_auth(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("AuthenticationError", "Invalid API key")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMAuthenticationError):
            adapter.complete(system="sys", user="usr")

    def test_authentication_error_with_billing_maps_to_billing(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("AuthenticationError", "insufficient credit balance")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMBillingError):
            adapter.complete(system="sys", user="usr")

    def test_rate_limit_error_maps_to_rate_limit(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("RateLimitError", "Too many requests")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMRateLimitError):
            adapter.complete(system="sys", user="usr")

    def test_rate_limit_with_billing_maps_to_billing(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("RateLimitError", "billing quota exceeded")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMBillingError):
            adapter.complete(system="sys", user="usr")

    def test_rate_limit_extracts_retry_after(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("RateLimitError", "Too many requests")
        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "30"}
        exc.response = mock_response
        client.messages.create.side_effect = exc

        with pytest.raises(LLMRateLimitError) as exc_info:
            adapter.complete(system="sys", user="usr")
        assert exc_info.value.retry_after == 30

    def test_internal_server_error_maps_to_unavailable(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("InternalServerError")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMUnavailableError):
            adapter.complete(system="sys", user="usr")

    def test_timeout_error_maps_to_timeout(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("APITimeoutError")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMTimeoutError):
            adapter.complete(system="sys", user="usr")

    def test_connection_error_maps_to_connection(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("APIConnectionError")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMConnectionError):
            adapter.complete(system="sys", user="usr")

    def test_bad_request_context_maps_to_context_length(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("BadRequestError", "context length exceeded, too long")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMContextLengthError):
            adapter.complete(system="sys", user="usr")

    def test_bad_request_generic_maps_to_response_error(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("BadRequestError", "invalid parameter")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMResponseError):
            adapter.complete(system="sys", user="usr")

    def test_not_found_error_maps_to_model_not_found(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("NotFoundError")
        client.messages.create.side_effect = exc

        with pytest.raises(LLMModelNotFoundError):
            adapter.complete(system="sys", user="usr")

    def test_api_status_error_500_maps_to_unavailable(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("APIStatusError")
        mock_response = MagicMock()
        mock_response.status_code = 503
        exc.response = mock_response
        client.messages.create.side_effect = exc

        with pytest.raises(LLMUnavailableError):
            adapter.complete(system="sys", user="usr")

    def test_api_status_error_402_billing_maps_to_billing(self, claude_adapter):
        adapter, client = claude_adapter
        exc = self._make_exc("APIStatusError", "payment required billing")
        mock_response = MagicMock()
        mock_response.status_code = 402
        exc.response = mock_response
        client.messages.create.side_effect = exc

        with pytest.raises(LLMBillingError):
            adapter.complete(system="sys", user="usr")

    def test_unknown_exception_reraises(self, claude_adapter):
        adapter, client = claude_adapter
        client.messages.create.side_effect = RuntimeError("unexpected")

        with pytest.raises(RuntimeError, match="unexpected"):
            adapter.complete(system="sys", user="usr")


class TestClaudeAdapterStream:
    """Tests de la méthode stream."""

    def test_raises_invalid_bounds_for_zero_max_tokens(self, claude_adapter):
        adapter, _ = claude_adapter
        with pytest.raises(InvalidBoundsError):
            list(adapter.stream(system="sys", user="usr", max_tokens=0))

    def test_raises_invalid_bounds_for_negative_max_tokens(self, claude_adapter):
        adapter, _ = claude_adapter
        with pytest.raises(InvalidBoundsError):
            list(adapter.stream(system="sys", user="usr", max_tokens=-5))


class TestTruncationTelemetry:
    """Tests for the truncation counter wired into complete()."""

    def test_truncated_response_increments_counter(self, claude_adapter):
        from app.adapters.llm.claude_adapter import (
            get_truncation_stats,
            _reset_truncation_stats_for_tests,
        )
        _reset_truncation_stats_for_tests()

        adapter, client = claude_adapter
        mock_response = _make_mock_response(text="cut off mid")
        mock_response.stop_reason = "max_tokens"
        client.messages.create.return_value = mock_response

        adapter.complete(system="sys", user="usr", max_tokens=80)

        stats = get_truncation_stats()
        assert stats["lifetime"]["calls"] == 1
        assert stats["lifetime"]["truncated"] == 1
        assert stats["rolling"]["rate"] == 1.0
        assert "test-model:80" in stats["by_budget"]
        assert stats["by_budget"]["test-model:80"] == {
            "calls": 1, "truncated": 1, "rate": 1.0,
        }

    def test_normal_response_does_not_count_as_truncation(self, claude_adapter):
        from app.adapters.llm.claude_adapter import (
            get_truncation_stats,
            _reset_truncation_stats_for_tests,
        )
        _reset_truncation_stats_for_tests()

        adapter, client = claude_adapter
        mock_response = _make_mock_response(text="full reply")
        mock_response.stop_reason = "end_turn"
        client.messages.create.return_value = mock_response

        adapter.complete(system="sys", user="usr", max_tokens=80)

        stats = get_truncation_stats()
        assert stats["lifetime"]["calls"] == 1
        assert stats["lifetime"]["truncated"] == 0
        assert stats["rolling"]["rate"] == 0.0
        assert stats["by_budget"]["test-model:80"]["truncated"] == 0

    def test_per_budget_breakdown_tracks_each_cap_separately(self, claude_adapter):
        from app.adapters.llm.claude_adapter import (
            get_truncation_stats,
            _reset_truncation_stats_for_tests,
        )
        _reset_truncation_stats_for_tests()

        adapter, client = claude_adapter

        truncated = _make_mock_response(text="cut")
        truncated.stop_reason = "max_tokens"
        normal = _make_mock_response(text="ok")
        normal.stop_reason = "end_turn"

        client.messages.create.return_value = truncated
        adapter.complete(system="sys", user="usr", max_tokens=60)
        client.messages.create.return_value = normal
        adapter.complete(system="sys", user="usr", max_tokens=60)
        adapter.complete(system="sys", user="usr", max_tokens=250)

        stats = get_truncation_stats()
        assert stats["by_budget"]["test-model:60"] == {
            "calls": 2, "truncated": 1, "rate": 0.5,
        }
        assert stats["by_budget"]["test-model:250"] == {
            "calls": 1, "truncated": 0, "rate": 0.0,
        }
        assert stats["lifetime"]["calls"] == 3
        assert stats["lifetime"]["truncated"] == 1


class TestCacheStatsAggregator:
    """Compatibility tests for the per-model cache counters."""

    def _reset_cache_stats(self):
        from app.adapters.llm import claude_adapter as _ca

        with _ca._cache_stats_lock:
            _ca._cache_stats.clear()
            _ca._cache_stats_last_log_at = 0.0

    def test_records_cache_usage_per_model(self):
        from app.adapters.llm.claude_adapter import (
            _get_cache_stats_snapshot,
            _record_cache_usage,
        )

        self._reset_cache_stats()
        _record_cache_usage("claude-test", fresh_in=10, cache_read=40, cache_creation=5)

        assert _get_cache_stats_snapshot()["claude-test"] == {
            "calls": 1,
            "fresh_in": 10,
            "cache_read_in": 40,
            "cache_creation_in": 5,
        }

    def test_sums_multiple_calls(self):
        from app.adapters.llm.claude_adapter import (
            _get_cache_stats_snapshot,
            _record_cache_usage,
        )

        self._reset_cache_stats()
        _record_cache_usage("claude-test", fresh_in=10, cache_read=40, cache_creation=5)
        _record_cache_usage("claude-test", fresh_in=3, cache_read=7, cache_creation=11)

        assert _get_cache_stats_snapshot()["claude-test"] == {
            "calls": 2,
            "fresh_in": 13,
            "cache_read_in": 47,
            "cache_creation_in": 16,
        }

    def test_ignores_unconvertible_mock_values(self):
        from unittest.mock import MagicMock
        from app.adapters.llm.claude_adapter import (
            _get_cache_stats_snapshot,
            _record_cache_usage,
        )

        self._reset_cache_stats()
        _record_cache_usage(
            "claude-test",
            fresh_in=MagicMock(),
            cache_read=MagicMock(),
            cache_creation=MagicMock(),
        )

        assert _get_cache_stats_snapshot()["claude-test"] == {
            "calls": 1,
            "fresh_in": 0,
            "cache_read_in": 0,
            "cache_creation_in": 0,
        }
