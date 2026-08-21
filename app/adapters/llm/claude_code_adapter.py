# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter LLM pour Claude Code (mode pipe).

Utilise `claude -p` en subprocess pour les complétions LLM.
Avantage : utilise l'authentification de Claude Code, pas besoin de clé API séparée.
"""

import json
import logging
import os
import re
import subprocess
import shutil
import tempfile

from app.domain.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.domain.ports import LLMPort, LLMResponse

logger = logging.getLogger(__name__)

# Timeout par défaut pour les appels Claude Code (secondes)
# 900s pour laisser le temps aux prompts volumineux (onboarding avec 100+ emails)
# Note : 3 agents parallèles + session Claude principale = contention CPU
DEFAULT_TIMEOUT = 900


class ClaudeCodeAdapter(LLMPort):
    """Adapter utilisant Claude Code CLI en mode pipe."""

    def __init__(self, model: str = None, timeout: int = DEFAULT_TIMEOUT):
        """
        Initialise l'adapter Claude Code.

        Args:
            model: Le modèle à utiliser (ex: 'sonnet', 'haiku', 'opus').
                   Par défaut utilise le modèle configuré dans Claude Code.
            timeout: Timeout en secondes pour les appels subprocess.
        """
        self._model = model or "sonnet"
        self._timeout = timeout
        self._claude_path = shutil.which("claude")

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Génère une complétion via Claude Code en mode pipe."""
        if not self._claude_path:
            raise LLMConnectionError(
                provider="claude-code",
                url="claude CLI",
                message="Claude Code CLI non trouvé. Installez-le avec: npm install -g @anthropic-ai/claude-code",
            )

        cmd = [
            self._claude_path,
            "-p",
            "--output-format", "json",
            "--model", self._model,
            "--max-turns", "1",
            "--tools", "",              # Désactiver les outils internes
            "--strict-mcp-config",      # Ignorer la config MCP utilisateur (zéro serveurs)
            "--system-prompt", system,
        ]

        # Env nettoyé pour les sous-processus claude -p :
        # 1. CLAUDE* : éviter le check de session imbriquée
        # 2. ANTHROPIC_API_KEY : forcer l'auth subscription (pas la clé API qui peut
        #    être épuisée). claude -p utilisera l'OAuth token de `claude auth`.
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("CLAUDE") and k != "ANTHROPIC_API_KEY"
        }
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        try:
            result = subprocess.run(
                cmd,
                input=user.encode('utf-8'),  # bytes — bypasses Windows locale (cp1252) entirely
                capture_output=True,
                text=False,                  # binary mode
                timeout=self._timeout,
                env=env,
                cwd=tempfile.gettempdir(),  # Répertoire neutre cross-platform
            )

            stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""

            if result.returncode != 0:
                stderr_snippet = stderr[:500] if stderr else "(no stderr)"
                logger.warning(
                    "claude -p failed: code=%d, stderr=%s",
                    result.returncode, stderr_snippet,
                )
                raise LLMResponseError(
                    provider="claude-code",
                    message=f"Claude Code exited with code {result.returncode}: {stderr_snippet}",
                )

            return self._parse_output(stdout)

        except subprocess.TimeoutExpired:
            raise LLMTimeoutError(
                provider="claude-code",
                timeout_seconds=self._timeout,
                message=f"Claude Code timed out after {self._timeout}s",
            )
        except FileNotFoundError:
            raise LLMConnectionError(
                provider="claude-code",
                url="claude CLI",
                message="Claude Code CLI non trouvé",
            )

    def _parse_output(self, stdout: str) -> LLMResponse:
        """Parse la sortie JSON de claude -p --output-format json."""
        if not stdout.strip():
            raise LLMResponseError(
                provider="claude-code",
                message="Claude Code returned empty output",
            )

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            # Parfois la sortie contient plusieurs objets JSON sur des lignes séparées
            parsed = []
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        parsed.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Normaliser en liste : claude -p retourne un objet unique ou un tableau
        if isinstance(parsed, dict):
            events = [parsed]
        elif isinstance(parsed, list):
            events = parsed
        else:
            events = []

        if not events:
            raise LLMResponseError(
                provider="claude-code",
                message="Could not parse Claude Code JSON output",
            )

        # Chercher le résultat final
        content = ""
        input_tokens = 0
        output_tokens = 0
        model_name = self._model

        for event in events:
            if not isinstance(event, dict):
                continue

            if event.get("type") == "result":
                content = event.get("result", "")
                usage = event.get("usage", {})
                input_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                break

            if event.get("type") == "assistant":
                msg = event.get("message", {})
                content_blocks = msg.get("content", [])
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        content = block.get("text", "")

                usage = msg.get("usage", {})
                input_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                model_name = msg.get("model", self._model)

        if not content:
            raise LLMResponseError(
                provider="claude-code",
                message="Claude Code returned no content in response",
            )

        content = self._sanitize_plan_artifacts(content)

        if not content:
            raise LLMResponseError(
                provider="claude-code",
                message="Claude Code returned only plan artifacts — no usable content",
            )

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model_name,
        )

    # Patterns d'artefacts du mode plan de Claude Code (NEW-A fix).
    # Détection en deux niveaux : blocs JSON multi-lignes + lignes individuelles.
    _PLAN_TOOL_NAMES = re.compile(
        r'"name"\s*:\s*"(?:Write|Read|Edit|ExitPlanMode|Bash|Glob|Grep|TodoWrite|NotebookEdit|'
        r'MultiEdit|WebFetch|WebSearch|mcp__[a-zA-Z0-9_]+)',
        re.IGNORECASE
    )
    # Signal fort de plan mode : présence de ExitPlanMode
    _PLAN_EXIT_SIGNAL = re.compile(r'"ExitPlanMode"', re.IGNORECASE)
    # Blocs JSON d'appels d'outils : une ligne qui commence par { et contient "name": "<ToolName>"
    _PLAN_JSON_LINE = re.compile(
        r'^\s*\{.*"name"\s*:\s*"(?:Write|Read|Edit|ExitPlanMode|Bash|Glob|Grep|TodoWrite)',
        re.IGNORECASE
    )
    # Chemins vers des fichiers plan
    _PLAN_PATH_PATTERNS: list[re.Pattern] = [
        re.compile(r'[A-Za-z]:\\[^\\]+\\\.claude\\plans\\', re.IGNORECASE),
        re.compile(r'/(?:home|Users|root)/[^/]+/\.claude/plans/'),
    ]
    # Phrases de préambule du mode plan (EN + FR)
    _PLAN_PREAMBLE_PATTERNS: list[re.Pattern] = [
        re.compile(r'\bI need to create a plan file\b', re.IGNORECASE),
        re.compile(r'\bLet me (?:do that|create the plan|write the plan)\b', re.IGNORECASE),
        re.compile(r'\bCreating plan(?:ning)? file\b', re.IGNORECASE),
        re.compile(r'\bI(?:\'m| am| will) (?:going to )?create (?:a |the )?plan\b', re.IGNORECASE),
        # French preambles
        re.compile(r'\bJe vais créer (?:le |un )?plan\b', re.IGNORECASE),
        re.compile(r'\bCréation du (?:fichier )?plan\b', re.IGNORECASE),
        re.compile(r'\bJe vais (?:d\'abord )?(?:créer|écrire|rédiger) (?:le |un )?plan\b', re.IGNORECASE),
        re.compile(r'\bVoici (?:le |mon )?plan\b', re.IGNORECASE),
    ]

    def _sanitize_plan_artifacts(self, content: str) -> str:
        """Filtre les artefacts du mode plan de Claude Code hors du contenu généré.

        NEW-A fix : filtrage amélioré en deux passes :
        1. Détection du signal fort ExitPlanMode → rejet complet du bloc plan
        2. Filtrage ligne par ligne des JSON d'outils + chemins + préambules (EN + FR)
        """
        if not content:
            return content

        # Vérification rapide : y a-t-il des artefacts?
        all_patterns = (
            [self._PLAN_JSON_LINE, self._PLAN_EXIT_SIGNAL, self._PLAN_TOOL_NAMES]
            + self._PLAN_PATH_PATTERNS
            + self._PLAN_PREAMBLE_PATTERNS
        )
        has_artifact = any(p.search(content) for p in all_patterns)
        if not has_artifact:
            return content

        logger.warning(
            "claude_code_adapter: plan-mode artifacts détectés dans la sortie — filtrage en cours"
        )

        # Si ExitPlanMode est présent, c'est un signal fort : tout le contenu est du mode plan.
        # On tente de récupérer le texte AVANT la première ligne JSON de type outil.
        if self._PLAN_EXIT_SIGNAL.search(content):
            logger.warning(
                "claude_code_adapter: ExitPlanMode détecté — contenu entier probable plan mode"
            )
            # Essai de récupérer le texte naturel avant les blocs JSON
            pre_json = re.split(r'\n\s*\{[^\n]{0,20}"name"\s*:', content)[0].strip()
            if pre_json and not any(p.search(pre_json) for p in self._PLAN_PREAMBLE_PATTERNS):
                # Il y a du texte propre avant les blocs — le garder
                content = pre_json
            else:
                # Tout est plan mode — contenu inutilisable
                return ""

        # Passe 2 : filtrage ligne par ligne
        line_patterns = (
            [self._PLAN_JSON_LINE]
            + self._PLAN_PATH_PATTERNS
            + self._PLAN_PREAMBLE_PATTERNS
        )
        clean_lines: list[str] = []
        for line in content.split("\n"):
            if any(p.search(line) for p in line_patterns):
                logger.debug("claude_code_adapter: ligne supprimée (artefact plan): %r", line[:120])
                continue
            # Supprimer aussi les lignes qui ressemblent à du JSON de tool call pur
            stripped = line.strip()
            if stripped.startswith("{") and self._PLAN_TOOL_NAMES.search(stripped):
                logger.debug("claude_code_adapter: bloc JSON outil supprimé: %r", line[:120])
                continue
            clean_lines.append(line)

        return "\n".join(clean_lines).strip()

    def is_available(self) -> bool:
        """Vérifie si Claude Code CLI est installé et accessible."""
        return self._claude_path is not None
