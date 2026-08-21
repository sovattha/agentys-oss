# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Provider LLM pour Ollama (modèles locaux).
"""

import os
import requests
from .base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Provider utilisant Ollama pour les modèles locaux."""

    def __init__(self, model: str = None, base_url: str = None):
        """
        Initialise le provider Ollama.

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
        system: str,
        user: str,
        max_tokens: int = 1024
    ) -> LLMResponse:
        """Génère une complétion via l'API Ollama."""
        url = f"{self._base_url}/api/chat"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens
            }
        }

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            # Ollama retourne les tokens dans la réponse
            content = data.get("message", {}).get("content", "")

            # Estimation des tokens (Ollama ne donne pas toujours les counts exacts)
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)

            return LLMResponse(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self._model
            )

        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Impossible de se connecter à Ollama sur {self._base_url}. "
                "Assurez-vous qu'Ollama est démarré avec 'ollama serve'"
            )
        except requests.exceptions.Timeout:
            raise TimeoutError(
                f"Timeout lors de la requête à Ollama. "
                f"Le modèle {self._model} peut être trop lent."
            )

    def is_available(self) -> bool:
        """Vérifie si Ollama est accessible."""
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list:
        """Liste les modèles disponibles sur Ollama."""
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
