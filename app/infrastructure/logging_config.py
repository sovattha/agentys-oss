# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de configuration du logging structuré.

Fournit:
- Logging JSON structuré (optionnel)
- Rotation des fichiers de log
- Logging console et fichier simultanés
"""

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

from app.config import LOGS_DIR, DEFAULT_LOGGING_CONFIG


def _is_pytest_logging_handler(handler: logging.Handler) -> bool:
    """Return True for pytest's internal log-capture handlers."""
    return handler.__class__.__module__.startswith("_pytest.logging")


class JsonFormatter(logging.Formatter):
    """Formateur JSON pour logs structurés."""

    def format(self, record: logging.LogRecord) -> str:
        """Formate un enregistrement de log en JSON."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Ajouter les données d'exception si présentes
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Ajouter les champs supplémentaires
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data

        return json.dumps(log_data, ensure_ascii=False)


class StandardFormatter(logging.Formatter):
    """Formateur standard avec couleurs pour la console."""

    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Vert
        "WARNING": "\033[33m",  # Jaune
        "ERROR": "\033[31m",    # Rouge
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S"
        )
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Formate un enregistrement de log avec couleurs."""
        formatted = super().format(record)

        if self.use_colors and record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            formatted = f"{color}{formatted}{self.RESET}"

        return formatted


def setup_logging(
    level: Optional[str] = None,
    format_style: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
    log_to_file: Optional[bool] = None,
    log_to_console: Optional[bool] = None,
) -> logging.Logger:
    """
    Configure le logging de l'application.

    Args:
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format_style: Style de formatage ("standard" ou "json").
        log_file: Nom du fichier de log.
        max_bytes: Taille max du fichier avant rotation.
        backup_count: Nombre de fichiers de backup à conserver.
        log_to_file: Activer le logging fichier.
        log_to_console: Activer le logging console.

    Returns:
        Le logger racine configuré.
    """
    config = DEFAULT_LOGGING_CONFIG

    # Utiliser les paramètres fournis ou les valeurs par défaut
    level = level or config.level
    format_style = format_style or config.format_style
    max_bytes = max_bytes or config.max_bytes
    backup_count = backup_count or config.backup_count
    log_to_file = log_to_file if log_to_file is not None else config.log_to_file
    log_to_console = log_to_console if log_to_console is not None else config.log_to_console
    log_file = log_file or "agentys.log"

    # Obtenir le logger racine
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Supprimer les handlers applicatifs existants tout en gardant la capture
    # pytest. Sinon un import qui appelle setup_logging() rend caplog muet pour
    # le reste de la suite.
    pytest_handlers = [
        handler
        for handler in root_logger.handlers
        if _is_pytest_logging_handler(handler)
    ]
    root_logger.handlers[:] = pytest_handlers

    # Handler console
    if log_to_console:
        # Windows consoles default to cp1252 — a log line containing a
        # non-Latin-1 char (→, …, emoji) would raise UnicodeEncodeError in
        # the StreamHandler and spam "--- Logging error ---" tracebacks.
        # Force UTF-8 with errors='replace' so a stray glyph degrades to
        # '?' instead of crashing the emit.
        for _std in (sys.stdout, sys.stderr):
            try:
                _std.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass  # stream doesn't support reconfigure (already wrapped)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(root_logger.level)

        if format_style == "json":
            console_handler.setFormatter(JsonFormatter())
        else:
            # Couleurs seulement si sortie vers terminal
            use_colors = sys.stdout.isatty()
            console_handler.setFormatter(StandardFormatter(use_colors=use_colors))

        root_logger.addHandler(console_handler)

    # Handler fichier avec rotation
    if log_to_file:
        log_path = LOGS_DIR / log_file
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(root_logger.level)

        # Toujours utiliser JSON pour les fichiers
        file_handler.setFormatter(JsonFormatter())

        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Obtient un logger nommé.

    Args:
        name: Nom du logger (généralement __name__).

    Returns:
        Le logger configuré.
    """
    return logging.getLogger(name)


class LoggerAdapter(logging.LoggerAdapter):
    """Adaptateur de logger avec support pour données supplémentaires."""

    def process(self, msg, kwargs):
        """Ajoute les données supplémentaires au log."""
        extra = kwargs.get("extra", {})
        if self.extra:
            extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs

