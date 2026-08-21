# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Infrastructure Layer - Configuration et injection de dépendances.

Cette couche câble les différentes parties de l'application :
- container.py : Conteneur d'injection de dépendances
- config.py : Chargement de la configuration
- retry.py : Retry avec backoff exponentiel
- circuit_breaker.py : Protection contre les cascades d'échecs
- audit.py : Logging d'audit
- logging_config.py : Configuration du logging structuré
- hot_reload.py : Hot-reload de configuration
- metrics.py : Métriques Prometheus

Règle : Cette couche connaît toutes les autres et les assemble.
"""

from .container import Container
from .config import Config
from .retry import with_retry, retry_call, RetryExhaustedError
from .circuit_breaker import CircuitBreaker, circuit_breaker, CircuitOpenError
from .audit import audit_logger, AuditEventType
from .logging_config import setup_logging, get_logger
from .rate_limiter import (
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    RateLimitExceededError,
    rate_limit,
    get_rate_limiter,
)
from .hot_reload import (
    ConfigWatcher,
    EnvConfigReloader,
    get_config_watcher,
    get_env_reloader,
    setup_hot_reload,
    WATCHDOG_AVAILABLE,
)
from .metrics import (
    AgentysMetrics,
    get_metrics,
    start_metrics_server,
    get_metrics_text,
    create_metrics_blueprint,
    timed,
    count_errors,
    PROMETHEUS_AVAILABLE,
)
from .cache import (
    Cache,
    FileCache,
    KnowledgeBaseCache,
    get_cache,
    get_knowledge_cache,
    cached,
)
from .pagination import (
    Paginator,
    PageResult,
    CursorPaginator,
    CursorPageResult,
    EmailPaginator,
    paginate,
    chunked,
)
from .batch import (
    BatchProcessor,
    BatchResult,
    BatchItemResult,
    BatchItemStatus,
    process_in_batches,
)
from .yaml_config import (
    YamlConfigLoader,
    load_yaml_config,
    get_yaml_config,
    generate_default_config,
    create_default_config_file,
)
from .monitoring import (
    HealthStatus,
    FailureType,
    HealthCheck,
    FailureEvent,
    MonitoringStatus,
    HealthMonitor,
    get_health_monitor,
    setup_default_monitoring,
    check_disk_space,
    check_memory_usage,
    check_api_connectivity,
)

__all__ = [
    "Container",
    "Config",
    "with_retry",
    "retry_call",
    "RetryExhaustedError",
    "CircuitBreaker",
    "circuit_breaker",
    "CircuitOpenError",
    "audit_logger",
    "AuditEventType",
    "setup_logging",
    "get_logger",
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
    "RateLimitExceededError",
    "rate_limit",
    "get_rate_limiter",
    # Hot reload
    "ConfigWatcher",
    "EnvConfigReloader",
    "get_config_watcher",
    "get_env_reloader",
    "setup_hot_reload",
    "WATCHDOG_AVAILABLE",
    # Metrics
    "AgentysMetrics",
    "get_metrics",
    "start_metrics_server",
    "get_metrics_text",
    "create_metrics_blueprint",
    "timed",
    "count_errors",
    "PROMETHEUS_AVAILABLE",
    # Cache
    "Cache",
    "FileCache",
    "KnowledgeBaseCache",
    "get_cache",
    "get_knowledge_cache",
    "cached",
    # Pagination
    "Paginator",
    "PageResult",
    "CursorPaginator",
    "CursorPageResult",
    "EmailPaginator",
    "paginate",
    "chunked",
    # Batch processing
    "BatchProcessor",
    "BatchResult",
    "BatchItemResult",
    "BatchItemStatus",
    "process_in_batches",
    # YAML Config
    "YamlConfigLoader",
    "load_yaml_config",
    "get_yaml_config",
    "generate_default_config",
    "create_default_config_file",
    # Monitoring
    "HealthStatus",
    "FailureType",
    "HealthCheck",
    "FailureEvent",
    "MonitoringStatus",
    "HealthMonitor",
    "get_health_monitor",
    "setup_default_monitoring",
    "check_disk_space",
    "check_memory_usage",
    "check_api_connectivity",
]
