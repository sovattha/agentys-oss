# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter LLM pour Ollama (modèles locaux).

Clean Architecture:
- Traduit les erreurs techniques (requests) en exceptions Domain (LLM*)
- Les Use Cases ne connaissent que les exceptions Domain
"""

import json
import os
from typing import List

import requests

from app.domain.exceptions import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports import LLMPort, LLMResponse
from app.domain.ports.llm_port import SystemPrompt


class OllamaAdapter(LLMPort):
    """Adapter utilisant Ollama pour les modèles locaux."""

    def __init__(self, model: str = None, base_url: str = None):
        """
        Initialise l'adapter Ollama.

        Args:
            model: Le modèle à utiliser (défaut: mixtral:latest)
            base_url: URL du serveur Ollama (défaut: http://localhost:11434)
        """
        self._model = model or os.getenv("LLM_MODEL", "mixtral:latest")
        self._base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        system: SystemPrompt,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Génère une complétion via l'API Ollama.

        Ollama ne supporte pas le prompt caching — si `system` est segmenté,
        les segments sont concaténés en un seul prompt système.
        """
        url = f"{self._base_url}/api/chat"

        # Ollama: pas de cache breakpoints, on join.
        system_str = system if isinstance(system, str) else "\n\n".join(s.text for s in system if s.text)

        options = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_str},
                {"role": "user", "content": user}
            ],
            "stream": False,
            "options": options,
        }

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            # Validate response structure
            if "message" not in data:
                raise LLMResponseError(
                    provider="ollama",
                    message="Invalid response from Ollama: missing 'message' field"
                )

            message = data["message"]
            if "content" not in message:
                raise LLMResponseError(
                    provider="ollama",
                    message="Invalid response from Ollama: missing 'content' in message"
                )

            content = message.get("content", "")
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)

            return LLMResponse(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self._model
            )

        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(
                provider="ollama",
                url=self._base_url,
                message=f"Cannot connect to Ollama at {self._base_url}. "
                        "Make sure Ollama is running with 'ollama serve'"
            ) from e
        except requests.exceptions.Timeout as e:
            raise LLMTimeoutError(
                provider="ollama",
                timeout_seconds=120,
                message=f"Request to Ollama timed out. Model {self._model} may be too slow."
            ) from e
        except requests.exceptions.HTTPError as e:
            self._handle_http_error(e)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                provider="ollama",
                message=f"Invalid JSON response from Ollama: {e}"
            ) from e

    def _handle_http_error(self, error: requests.exceptions.HTTPError) -> None:
        """Traduit les erreurs HTTP en exceptions Domain."""
        response = error.response
        status_code = response.status_code if response is not None else 0

        if status_code == 404:
            raise LLMModelNotFoundError(
                provider="ollama",
                model=self._model,
                message=f"Model '{self._model}' not found on Ollama"
            ) from error
        elif status_code == 429:
            retry_after = None
            if response is not None:
                retry_after_str = response.headers.get("Retry-After")
                if retry_after_str:
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        pass
            raise LLMRateLimitError(
                provider="ollama",
                retry_after=retry_after,
                message="Rate limit exceeded for Ollama"
            ) from error
        elif status_code >= 500:
            raise LLMUnavailableError(
                provider="ollama",
                message=f"Ollama server error (HTTP {status_code})"
            ) from error
        else:
            # Autres erreurs HTTP
            raise LLMUnavailableError(
                provider="ollama",
                message=f"HTTP error from Ollama: {status_code}"
            ) from error

    def is_available(self) -> bool:
        """Vérifie si Ollama est accessible."""
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except (requests.exceptions.RequestException, OSError):
            return False

    def list_models(self) -> List[str]:
        """Liste les modèles disponibles sur Ollama."""
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, OSError):
            return []
