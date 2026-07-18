# proxy/app/api/admin_config.py
"""Runtime configuration API — view and update config at runtime (admin only)."""

import logging
import os
import threading
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(prefix="/v1/admin/config", tags=["admin-config"])


# ---------------------------------------------------------------------------
# Safe vs secret keys classification
# ---------------------------------------------------------------------------

SECRET_KEY_PATTERNS = (
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "TOKEN",
    "KEYCLOAK",
    "JWT_PUBLIC",
    "MINIO_",
    "PRIVATE",
    "ENCRYPTION",
)

SAFE_KEYS = frozenset(
    {
        "LOG_LEVEL",
        "LOG_FORMAT",
        "LOG_REQUESTS",
        "LOG_DIR",
        "METRICS_ENABLED",
        "AUDIT_ENABLED",
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_PER_MINUTE",
        "RATE_LIMIT_BURST",
        "MAX_CHUNKS_RETRIEVAL",
        "MAX_CHUNKS_AFTER_RERANK",
        "CONFIDENCE_THRESHOLD",
        "MAX_VERIFY_LOOPS",
        "COMPRESSION_ENABLED",
        "COMPRESSION_LEVEL",
        "COMPRESSION_MIN_SIZE",
        "COMPRESSION_STRATEGY",
        "USE_REDIS",
        "REDIS_URL",
        "USE_LANGGRAPH",
        "GRAPH_ENABLED",
        "USE_GRAPH_EXPANSION",
        "WARMUP_ENABLED",
        "WARMUP_ON_STARTUP",
        "SANITIZE_INPUT",
        "TOOLS_ENABLED",
        "TOOLS_PARALLEL_EXECUTION",
        "TOOLS_MAX_CONCURRENCY",
        "LIVE_SOURCES_ENABLED",
        "GRACEFUL_SHUTDOWN_ENABLED",
        "SHUTDOWN_TIMEOUT",
        "RELOAD",
        "WORKERS",
        "REQUEST_TIMEOUT",
        "MAX_RETRIES",
        "RETRY_DELAY",
        "STALE_DETECTION_ENABLED",
        "STALE_CONFLUENCE_DAYS",
        "STALE_JIRA_DAYS",
        "STALE_GITLAB_DAYS",
        "STALE_DEFAULT_DAYS",
        "STALE_DETECTION_SCAN_LIMIT",
        "REINDEX_ENABLED",
        "REINDEX_CHECK_INTERVAL",
        "REINDEX_STALENESS_THRESHOLD",
        "REINDEX_MAX_CONCURRENT_TASKS",
        "I18N_ENABLED",
        "DEFAULT_LANGUAGE",
        "SELF_CRITIQUE_ENABLED",
        "HYDE_ENABLED",
        "HYDE_ENABLED_IN_PROGRESSIVE",
        "REFLECTION_ENABLED",
        "REFLECTION_DEPTH",
        "HALLUCINATION_CHECK_ENABLED",
        "NLI_GROUNDING_ENABLED",
        "CRAG_DECOMPOSITION_ENABLED",
        "PREFIX_CACHING_ENABLED",
        "TOKEN_OPTIMIZER_ENABLED",
        "SSE_CHUNK_SIZE",
        "STREAM_BUFFER_SIZE",
        "CONVERSATION_MAX_TURNS",
        "CONVERSATION_SUMMARY_THRESHOLD_TOKENS",
        "CLARIFICATION_ENABLED",
        "CROSS_LINGUAL_ENABLED",
        "MULTILINGUAL_INTENT_ENABLED",
        "ADAPTIVE_ROUTING_ENABLED",
        "MAX_RETRIEVAL_LOOPS",
        "NLI_MODEL_ENABLED",
        "ENRICHMENT_ENABLED",
        "CANARY_ENABLED",
        "CANARY_PHASE_DURATION_5",
        "CANARY_PHASE_DURATION_25",
        "CANARY_PHASE_DURATION_50",
        "CANARY_PHASE_DURATION_75",
        "CANARY_COOLDOWN_SECONDS",
        "HOT_RELOAD_ENABLED",
        "HOT_RELOAD_WATCH_INTERVAL",
        "HOT_RELOAD_SIGNAL_ENABLED",
        "MODEL_EVOLUTION_ENABLED",
        "TRAINING_PROFILE",
        "INTEGRITY_CHECK_ENABLED",
        "INTEGRITY_NLI_CONTRADICTION_THRESHOLD",
        "INTEGRITY_CHUNK_SAMPLE_LIMIT",
        "EVAL_DATASET_PATH",
        "ADMIN_ALERT_ENABLED",
        "ADMIN_ALERT_ENDPOINT",
        "NAMESPACE_ISOLATION_ENABLED",
        "AB_TEST_ENABLED",
        "OTEL_ENABLED",
        "OTEL_EXPORTER_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "OTEL_BATCH_TIMEOUT",
        "OTEL_MAX_ATTRIBUTES_PER_SPAN",
        "CORS_ORIGINS",
        "TRUSTED_PROXY_COUNT",
        "TOOLS_DECLARATIVE_DIR",
        "TOOLS_OPENAPI_SPECS",
    }
)


def _get_default_value(name: str) -> Any:
    """Get the hardcoded default value from the config module source."""
    import proxy.app.shared.config as cfg

    defaults: dict[str, Any] = {
        "QDRANT_HOST": "localhost",
        "QDRANT_PORT": 6333,
        "COLLECTION_NAME": "knowledge_base",
        "EMBEDDER_MODEL": "",
        "EMBEDDER_DEVICE": "cpu",
        "EMBEDDER_ENDPOINT": "",
        "EMBEDDER_API_KEY": "",
        "EMBEDDER_FALLBACK_LOCAL": True,
        "RERANKER_MODEL": "",
        "RERANKER_MAX_LENGTH": 512,
        "RERANKER_BATCH_SIZE": 32,
        "RERANKER_ENDPOINT": "",
        "RERANKER_API_KEY": "",
        "RERANKER_FALLBACK_LOCAL": True,
        "LLM_ENDPOINT": "http://localhost:8000/v1",
        "LLM_MODEL_NAME": "",
        "LLM_API_KEY": None,
        "LLM_PROVIDER_TYPE": "openai",
        "REQUEST_TIMEOUT": 120,
        "MAX_RETRIES": 3,
        "RETRY_DELAY": 1.0,
        "SLM_ENDPOINT": "",
        "SLM_MODEL_NAME": "",
        "SLM_API_KEY": None,
        "SLM_MAX_TOKENS": 256,
        "SLM_LOCAL_ENABLED": False,
        "SLM_LOCAL_BINARY": "llama.cpp/build/bin/llama-server",
        "SLM_LOCAL_MODEL_PATH": "",
        "SLM_LOCAL_CONTEXT_SIZE": 4096,
        "SLM_LOCAL_THREADS": 4,
        "SLM_LOCAL_PORT": 8081,
        "SLM_LOCAL_STARTUP_TIMEOUT": 60,
        "MAX_CHUNKS_RETRIEVAL": 50,
        "MAX_CHUNKS_AFTER_RERANK": 20,
        "USE_REDIS": False,
        "REDIS_URL": "redis://localhost:6379",
        "USE_LANGGRAPH": False,
        "ADAPTIVE_ROUTING_ENABLED": False,
        "MAX_RETRIEVAL_LOOPS": 3,
        "GRAPH_ENABLED": False,
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "",
        "USE_GRAPH_EXPANSION": False,
        "LOG_REQUESTS": True,
        "LOG_DIR": "./logs",
        "SENSITIVE_SECRETS": [],
        "METRICS_ENABLED": True,
        "LOG_FORMAT": "json",
        "LOG_LEVEL": "INFO",
        "OTEL_ENABLED": False,
        "OTEL_EXPORTER_ENDPOINT": "http://localhost:4318/v1/traces",
        "OTEL_SERVICE_NAME": "rag-proxy",
        "OTEL_BATCH_TIMEOUT": 5,
        "OTEL_MAX_ATTRIBUTES_PER_SPAN": 128,
        "RATE_LIMIT_ENABLED": False,
        "RATE_LIMIT_PER_MINUTE": 60,
        "RATE_LIMIT_BURST": 10,
        "TRUSTED_PROXY_COUNT": 0,
        "CORS_ORIGINS": "http://localhost:3000,http://localhost:8080",
        "AUTH_ENABLED": True,
        "JWT_SECRET": "",
        "JWT_ALGORITHM": "RS256",
        "JWT_PUBLIC_KEY": "",
        "JWT_AUDIENCE": "rag-proxy",
        "JWT_ISSUER": "rag-proxy",
        "TOKEN_EXPIRE_HOURS": 24,
        "AUTH_VALID_USERS": "{}",
        "USER_DB_PATH": "./data/users.db",
        "BCRYPT_ROUNDS": 12,
        "ACCESS_TOKEN_MINUTES": 60,
        "REFRESH_TOKEN_DAYS": 7,
        "TOKEN_BLACKLIST_MAX_ENTRIES": 10000,
        "AD_ENABLED": False,
        "AD_URL": "",
        "AD_BASE_DN": "",
        "AD_USER_DN_TEMPLATE": "cn={username},{base_dn}",
        "AD_GROUP_DN": "",
        "RBAC_ENABLED": True,
        "KEYCLOAK_URL": "",
        "KEYCLOAK_REALM": "master",
        "KEYCLOAK_CLIENT_ID": "rag-proxy",
        "SANITIZE_INPUT": True,
        "AUDIT_ENABLED": True,
        "NAMESPACE_ISOLATION_ENABLED": False,
        "AB_TEST_ENABLED": False,
        "HOST": "0.0.0.0",
        "PORT": 8080,
        "RELOAD": False,
        "WORKERS": 1,
        "CONFIDENCE_THRESHOLD": 0.5,
        "CONFIDENCE_THRESHOLD_CALIBRATED": 0,
        "MAX_VERIFY_LOOPS": 2,
        "NLI_GROUNDING_ENABLED": True,
        "SELF_CRITIQUE_ENABLED": True,
        "COMPRESSION_STRATEGY": "keyword",
        "REORDER_ENABLED": True,
        "CRAG_DECOMPOSITION_ENABLED": True,
        "NLI_MODEL_ENABLED": False,
        "HYDE_ENABLED": True,
        "HYDE_ENABLED_IN_PROGRESSIVE": True,
        "REFLECTION_ENABLED": True,
        "REFLECTION_DEPTH": 2,
        "HALLUCINATION_CHECK_ENABLED": False,
        "ENRICHMENT_ENABLED": False,
        "TOKEN_OPTIMIZER_ENABLED": True,
        "PREFIX_CACHING_ENABLED": False,
        "EVAL_DATASET_PATH": "./data/eval_dataset.json",
        "ADMIN_ALERT_ENABLED": False,
        "ADMIN_ALERT_ENDPOINT": "",
        "TOOLS_ENABLED": False,
        "LIVE_SOURCES_ENABLED": False,
        "TOOLS_PARALLEL_EXECUTION": True,
        "TOOLS_MAX_CONCURRENCY": 10,
        "TOOLS_DECLARATIVE_DIR": "./tools/declarative",
        "TOOLS_OPENAPI_SPECS": "",
        "CONFLUENCE_API_URL": "",
        "CONFLUENCE_API_TOKEN": "",
        "CONFLUENCE_API_USER": "",
        "JIRA_API_URL": "",
        "JIRA_API_TOKEN": "",
        "JIRA_API_USER": "",
        "GITLAB_API_URL": "",
        "GITLAB_API_TOKEN": "",
        "CONVERSATION_MAX_TURNS": 10,
        "CONVERSATION_SUMMARY_THRESHOLD_TOKENS": 2000,
        "CLARIFICATION_ENABLED": True,
        "I18N_ENABLED": True,
        "DEFAULT_LANGUAGE": "en",
        "SUPPORTED_LANGUAGES": ["en", "ru", "de", "fr", "zh"],
        "MULTILINGUAL_INTENT_ENABLED": True,
        "CROSS_LINGUAL_ENABLED": True,
        "COMPRESSION_ENABLED": True,
        "COMPRESSION_MIN_SIZE": 500,
        "COMPRESSION_LEVEL": 6,
        "SSE_CHUNK_SIZE": 4,
        "STREAM_BUFFER_SIZE": 1,
        "WARMUP_ENABLED": True,
        "WARMUP_ON_STARTUP": True,
        "MODEL_EVOLUTION_ENABLED": False,
        "MLFLOW_TRACKING_URI": "http://localhost:5000",
        "MLFLOW_EXPERIMENT_NAME": "rag-system",
        "MLFLOW_ARTIFACT_ROOT": "s3://rag-artifacts",
        "MINIO_ENDPOINT": "localhost:9000",
        "MINIO_ACCESS_KEY": "",
        "MINIO_SECRET_KEY": "",
        "MINIO_BUCKET": "rag-artifacts",
        "MINIO_SECURE": False,
        "MINIO_DOCS_BUCKET": "rag-documents",
        "SSL_VERIFY": True,
        "SSL_CERT_PATH": "",
        "TRAINING_PROFILE": "dev",
        "HOT_RELOAD_ENABLED": False,
        "HOT_RELOAD_WATCH_INTERVAL": 5,
        "HOT_RELOAD_SIGNAL_ENABLED": True,
        "CANARY_ENABLED": False,
        "CANARY_PHASE_DURATION_5": 300,
        "CANARY_PHASE_DURATION_25": 600,
        "CANARY_PHASE_DURATION_50": 900,
        "CANARY_PHASE_DURATION_75": 1200,
        "CANARY_COOLDOWN_SECONDS": 3600,
        "EVAL_GATE_LLM_BERTSCORE_MIN": 0.70,
        "EVAL_GATE_LLM_HALLUCINATION_MAX": 0.05,
        "EVAL_GATE_LLM_ROUGE_L_MIN": 0.35,
        "EVAL_GATE_SLM_F1_MIN": 0.85,
        "EVAL_GATE_SLM_ACCURACY_MIN": 0.90,
        "EVAL_GATE_RERANKER_MRR_MIN": 0.75,
        "EVAL_GATE_RERANKER_NDCG_MIN": 0.70,
        "STALE_DETECTION_ENABLED": True,
        "STALE_CONFLUENCE_DAYS": 90,
        "STALE_JIRA_DAYS": 30,
        "STALE_GITLAB_DAYS": 14,
        "STALE_DEFAULT_DAYS": 180,
        "STALE_DETECTION_SCAN_LIMIT": 500,
        "REINDEX_ENABLED": True,
        "REINDEX_CHECK_INTERVAL": 3600,
        "REINDEX_STALENESS_THRESHOLD": 80,
        "REINDEX_MAX_CONCURRENT_TASKS": 5,
        "INTEGRITY_CHECK_ENABLED": True,
        "INTEGRITY_NLI_CONTRADICTION_THRESHOLD": 0.7,
        "INTEGRITY_CHUNK_SAMPLE_LIMIT": 200,
        "GRACEFUL_SHUTDOWN_ENABLED": True,
        "SHUTDOWN_TIMEOUT": 30,
        "ETL_SECRET": "***" if cfg.ETL_SECRET else "",
    }
    return defaults.get(name, getattr(cfg, name, None))


def _is_secret(name: str) -> bool:
    """Check if a config key contains secret/sensitive data."""
    return any(pattern in name.upper() for pattern in SECRET_KEY_PATTERNS)


def _mask_value(name: str, value: Any) -> Any:
    """Mask a config value if it's a secret."""
    if _is_secret(name) and value:
        if isinstance(value, str) and len(value) > 4:
            return value[:4] + "***"
        return "***"
    return value


def _is_safe_key(name: str) -> bool:
    """Check if a config key is safe for runtime modification."""
    return name in SAFE_KEYS


# ---------------------------------------------------------------------------
# In-memory runtime overrides
# ---------------------------------------------------------------------------

_runtime_overrides: dict[str, Any] = {}
_runtime_lock = threading.RLock()


def get_override(name: str) -> Any | None:
    """Get a runtime override value, or None if not overridden."""
    with _runtime_lock:
        return _runtime_overrides.get(name)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ConfigItem(BaseModel):
    name: str
    value: Any
    secret: bool
    safe: bool
    overridden: bool = False


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(
        ...,
        description="Dict of config key → new value. Only safe keys are allowed.",
    )


class ConfigUpdateResponse(BaseModel):
    accepted: dict[str, Any]
    rejected: dict[str, str]
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _collect_all_config() -> list[ConfigItem]:
    """Collect all config values from the config module."""
    import proxy.app.shared.config as cfg

    items: list[ConfigItem] = []
    skipped_prefixes = ("__", "_")
    seen: set[str] = set()

    for attr_name in sorted(dir(cfg)):
        if attr_name.startswith(skipped_prefixes):
            continue
        if attr_name in seen:
            continue
        seen.add(attr_name)

        attr_value = getattr(cfg, attr_name, None)

        # Skip callables, modules, classes
        if callable(attr_value) or isinstance(attr_value, (type, type(os))):
            continue

        # Skip non-primitive containers
        if not isinstance(attr_value, (str, int, float, bool, list, dict, type(None), tuple)):
            continue

        # Check override
        overridden = attr_name in _runtime_overrides
        display_value = _runtime_overrides.get(attr_name, attr_value)

        items.append(
            ConfigItem(
                name=attr_name,
                value=_mask_value(attr_name, display_value),
                secret=_is_secret(attr_name),
                safe=_is_safe_key(attr_name),
                overridden=overridden,
            )
        )

    return items


@router.get("")
async def get_config(
    request: Request,
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return all configuration values, with secrets masked."""
    with tracer.start_as_current_span("admin.config.list"):
        items = _collect_all_config()
        result: dict[str, Any] = {}
        for item in items:
            result[item.name] = {
                "value": item.value,
                "secret": item.secret,
                "safe": item.safe,
                "overridden": item.overridden,
            }
        return JSONResponse(
            status_code=200,
            content={
                "config": result,
                "total": len(result),
            },
        )


@router.get("/defaults")
async def get_config_defaults(
    request: Request,
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Show default values vs current values for all config keys."""
    with tracer.start_as_current_span("admin.config.defaults"):
        import proxy.app.shared.config as cfg

        result: dict[str, dict[str, Any]] = {}
        for attr_name in sorted(dir(cfg)):
            if attr_name.startswith("_"):
                continue
            attr_value = getattr(cfg, attr_name, None)
            if callable(attr_value) or isinstance(attr_value, (type, type(os))):
                continue
            if not isinstance(attr_value, (str, int, float, bool, list, dict, type(None), tuple)):
                continue

            default_value = _get_default_value(attr_name)
            current_value = _runtime_overrides.get(attr_name, attr_value)
            is_secret = _is_secret(attr_name)

            result[attr_name] = {
                "default": _mask_value(attr_name, default_value) if is_secret else default_value,
                "current": _mask_value(attr_name, current_value) if is_secret else current_value,
                "overridden": attr_name in _runtime_overrides,
            }

        return JSONResponse(
            status_code=200,
            content={
                "defaults": result,
                "total": len(result),
            },
        )


@router.patch("", response_model=ConfigUpdateResponse)
async def update_config(
    req: ConfigUpdateRequest,
    request: Request,
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> ConfigUpdateResponse:
    """Update safe configuration values at runtime.

    Only non-secret, safe config keys can be updated.
    Changes persist only in memory until restart.
    """
    with tracer.start_as_current_span("admin.config.update") as span:
        import proxy.app.shared.config as cfg

        accepted: dict[str, Any] = {}
        rejected: dict[str, str] = {}

        for key, new_value in req.updates.items():
            if not _is_safe_key(key):
                rejected[key] = f"Key '{key}' is not safe for runtime modification"
                continue
            if not hasattr(cfg, key):
                rejected[key] = f"Key '{key}' not found in config module"
                continue

            old_value = getattr(cfg, key)
            try:
                # Type-coerce to match existing type
                if isinstance(old_value, bool) and not isinstance(new_value, bool):
                    rejected[key] = f"Expected bool, got {type(new_value).__name__}"
                    continue
                if isinstance(old_value, int) and not isinstance(new_value, int):
                    try:
                        new_value = int(new_value)
                    except (ValueError, TypeError):
                        rejected[key] = "Cannot convert to int"
                        continue
                if isinstance(old_value, float) and not isinstance(new_value, float):
                    try:
                        new_value = float(new_value)
                    except (ValueError, TypeError):
                        rejected[key] = "Cannot convert to float"
                        continue

                with _runtime_lock:
                    _runtime_overrides[key] = new_value
                logger.info(f"Config '{key}' updated from {old_value} to {new_value} (runtime)")
                accepted[key] = new_value
            except Exception as e:
                rejected[key] = str(e)

        if span.is_recording():
            span.set_attribute("admin.config.accepted_count", len(accepted))
            span.set_attribute("admin.config.rejected_count", len(rejected))

        return ConfigUpdateResponse(
            accepted=accepted,
            rejected=rejected,
            message=f"Updated {len(accepted)} config(s), rejected {len(rejected)}",
        )
