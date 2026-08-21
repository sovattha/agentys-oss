import json

from app.adapters.llm import MockLLMAdapter
from app.infrastructure.config import Config
from app.infrastructure.container import Container


def test_mock_llm_returns_structured_critic_response(monkeypatch):
    monkeypatch.setenv("AGENTYS_MOCK_LLM_LATENCY_MS", "0")
    monkeypatch.delenv("AGENTYS_MOCK_LLM_RECORD_USAGE", raising=False)

    adapter = MockLLMAdapter(tier="label")
    response = adapter.complete(
        system="Return JSON with coherence, tone, completeness and over_commitment.",
        user="Critique ce brouillon.",
    )

    data = json.loads(response.content)
    assert data["coherence"] >= 90
    assert data["over_commitment"] >= 90
    assert response.model == "mock-label"
    assert response.usage_recorded is True


def test_mock_llm_can_record_synthetic_usage(monkeypatch):
    calls = []

    def fake_record_usage(**kwargs):
        calls.append(kwargs)

    monkeypatch.setenv("AGENTYS_MOCK_LLM_LATENCY_MS", "0")
    monkeypatch.setenv("AGENTYS_MOCK_LLM_RECORD_USAGE", "true")
    monkeypatch.setattr("app.infrastructure.token_usage_writer.record_usage", fake_record_usage)

    response = MockLLMAdapter(tier="smart").complete(system="draft", user="email")

    assert response.usage_recorded is True
    assert calls == [
        {
            "model": "mock-smart",
            "input_tokens": 900,
            "output_tokens": 180,
        }
    ]


def test_mock_llm_stream_emits_content_before_final_chunk(monkeypatch):
    monkeypatch.setenv("AGENTYS_MOCK_LLM_LATENCY_MS", "0")

    chunks = list(MockLLMAdapter(tier="label").stream(system="draft", user="email"))

    assert chunks[0].text.startswith("Je vérifie le délai")
    assert chunks[0].is_final is False
    assert chunks[-1].text == ""
    assert chunks[-1].is_final is True
    assert chunks[-1].stop_reason == "end_turn"


def test_container_uses_mock_llm_when_enabled(monkeypatch):
    monkeypatch.setenv("AGENTYS_MOCK_LLM", "true")

    container = Container(config=Config.from_env())

    assert isinstance(container.llm_background, MockLLMAdapter)
    assert container.llm_background.model == "mock-label"
