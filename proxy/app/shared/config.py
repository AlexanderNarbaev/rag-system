# proxy/app/config.py
"""
RAG proxy configuration.

All parameters are loaded from environment variables or have default values.
Supports .env file loading for local development.

Конфигурация RAG-прокси.
Все параметры загружаются из переменных окружения или имеют значения по умолчанию.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загрузка .env файла (если существует)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ============ Qdrant ============
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_base")

# ============ Embedder / Embedding Model ============
# Examples: BAAI/bge-m3, intfloat/multilingual-e5-large, sentence-transformers/all-MiniLM-L6-v2
EMBEDDER_MODEL = os.getenv("EMBEDDER_MODEL", "")
EMBEDDER_DEVICE = os.getenv("EMBEDDER_DEVICE", "cpu")
# Remote embedding service (OpenAI /v1/embeddings or compatible). Leave empty for local model.
# Examples: http://localhost:8081/v1, https://api.openai.com/v1
EMBEDDER_ENDPOINT = os.getenv("EMBEDDER_ENDPOINT", "")
EMBEDDER_API_KEY = os.getenv("EMBEDDER_API_KEY", "")
# When remote embedder is unavailable, fall back to local SentenceTransformer
EMBEDDER_FALLBACK_LOCAL = os.getenv("EMBEDDER_FALLBACK_LOCAL", "true").lower() == "true"

# ============ Reranker / Cross-Encoder ============
# Examples: cross-encoder/ms-marco-MiniLM-L-6-v2, BAAI/bge-reranker-v2-m3, mixedbread-ai/mxbai-rerank-large-v1
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "")
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
RERANKER_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", "32"))
# Remote reranker service (Cohere /v1/rerank or compatible). Leave empty for local model.
# Examples: http://localhost:8082/v1, https://api.cohere.com/v1
RERANKER_ENDPOINT = os.getenv("RERANKER_ENDPOINT", "")
RERANKER_API_KEY = os.getenv("RERANKER_API_KEY", "")
# When remote reranker is unavailable, fall back to local CrossEncoder
RERANKER_FALLBACK_LOCAL = os.getenv("RERANKER_FALLBACK_LOCAL", "true").lower() == "true"

# ============ LLM / Primary Language Model ============
# Supports any OpenAI-compatible endpoint (vLLM, llama.cpp, Ollama, LiteLLM, etc.)
# Examples: gemma-4-26b-it, meta-llama/Llama-3.1-70B, mistralai/Mixtral-8x22B
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://localhost:8000/v1")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", None)
LLM_PROVIDER_TYPE = os.getenv("LLM_PROVIDER_TYPE", "openai")  # openai, anthropic, generic
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))

# ============ SLM / Small Language Model (routing, decomposition) ============
# Leave SLM_ENDPOINT empty to disable SLM features (heuristic fallback will be used)
# Examples: gemma-2b-it, Qwen/Qwen2.5-1.5B-Instruct, microsoft/Phi-3-mini-4k-instruct
SLM_ENDPOINT = os.getenv("SLM_ENDPOINT", "")
SLM_MODEL_NAME = os.getenv("SLM_MODEL_NAME", "")
SLM_API_KEY = os.getenv("SLM_API_KEY", None)
SLM_MAX_TOKENS = int(os.getenv("SLM_MAX_TOKENS", "256"))

# ============ SLM Local (llama.cpp subprocess) ============
# Enable local llama.cpp subprocess mode for air-gapped deployments.
# When enabled, the SLM runs locally via a llama-server subprocess instead of
# an external OpenAI-compatible API endpoint.
SLM_LOCAL_ENABLED = os.getenv("SLM_LOCAL_ENABLED", "false").lower() == "true"
# Path to the llama.cpp server binary (llama-server).
SLM_LOCAL_BINARY = os.getenv("SLM_LOCAL_BINARY", "llama.cpp/build/bin/llama-server")
# Path to the .gguf model file to load.
SLM_LOCAL_MODEL_PATH = os.getenv("SLM_LOCAL_MODEL_PATH", "")
# LLM context size (in tokens) for the local model.
SLM_LOCAL_CONTEXT_SIZE = int(os.getenv("SLM_LOCAL_CONTEXT_SIZE", "4096"))
# Number of CPU threads for inference.
SLM_LOCAL_THREADS = int(os.getenv("SLM_LOCAL_THREADS", "4"))
# Port the local llama-server will listen on (auto-assigned if 0).
SLM_LOCAL_PORT = int(os.getenv("SLM_LOCAL_PORT", "8081"))
# Maximum seconds to wait for the local server to become ready.
SLM_LOCAL_STARTUP_TIMEOUT = int(os.getenv("SLM_LOCAL_STARTUP_TIMEOUT", "60"))

# ============ Параметры RAG ============
MAX_CHUNKS_RETRIEVAL = int(os.getenv("MAX_CHUNKS_RETRIEVAL", "50"))
MAX_CHUNKS_AFTER_RERANK = int(os.getenv("MAX_CHUNKS_AFTER_RERANK", "20"))

# ============ Кэш ============
USE_REDIS = os.getenv("USE_REDIS", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ============ Агентная оркестрация (LangGraph) ============
USE_LANGGRAPH = os.getenv("USE_LANGGRAPH", "false").lower() == "true"
MAX_RETRIEVAL_LOOPS = int(os.getenv("MAX_RETRIEVAL_LOOPS", "3"))

# ============ Граф знаний (Neo4j) ============
GRAPH_ENABLED = os.getenv("GRAPH_ENABLED", "false").lower() == "true"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
USE_GRAPH_EXPANSION = os.getenv("USE_GRAPH_EXPANSION", "false").lower() == "true"

# ============ Логирование и HITL ============
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "true").lower() == "true"
LOG_DIR = os.getenv("LOG_DIR", "./logs")

# ============ Безопасность ============
# Список секретов для маскировки в логах (дополнительно)
SENSITIVE_SECRETS = os.getenv("SENSITIVE_SECRETS", "").split(",") if os.getenv("SENSITIVE_SECRETS") else []

# ============ Observability ============
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # "json" or "text"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# ── OpenTelemetry Tracing ──
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://localhost:4318/v1/traces")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "rag-proxy")
OTEL_BATCH_TIMEOUT = int(os.getenv("OTEL_BATCH_TIMEOUT", "5"))
OTEL_MAX_ATTRIBUTES_PER_SPAN = int(os.getenv("OTEL_MAX_ATTRIBUTES_PER_SPAN", "128"))

# ============ Rate Limiting ============
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "10"))
TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))

# ============ CORS ============
# Default allows localhost only. For production, set explicit allowed origins.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")

# ============ Authentication & RBAC ============
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "24"))
AUTH_VALID_USERS = os.getenv("AUTH_VALID_USERS", "{}")  # JSON dict of valid users for login endpoint

# ── User Database (SQLite) ──
USER_DB_PATH = os.getenv("USER_DB_PATH", "./data/users.db")
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# ── Auth startup validation ──
if AUTH_ENABLED and not JWT_SECRET:
    import warnings

    warnings.warn(
        "AUTH_ENABLED is true but JWT_SECRET is empty — token signing will fail. Set JWT_SECRET in your environment.",
        stacklevel=2,
    )

# ── Token Management ──
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
TOKEN_BLACKLIST_MAX_ENTRIES = int(os.getenv("TOKEN_BLACKLIST_MAX_ENTRIES", "10000"))

# ── AD/LDAP Integration ──
AD_ENABLED = os.getenv("AD_ENABLED", "false").lower() == "true"
AD_URL = os.getenv("AD_URL", "")
AD_BASE_DN = os.getenv("AD_BASE_DN", "")
AD_USER_DN_TEMPLATE = os.getenv("AD_USER_DN_TEMPLATE", "cn={username},{base_dn}")
AD_GROUP_DN = os.getenv("AD_GROUP_DN", "")

# ============ RBAC ============
RBAC_ENABLED = os.getenv("RBAC_ENABLED", "false").lower() == "true"

# ============ Keycloak OIDC ============
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "rag-proxy")

# ============ Input Sanitization ============
SANITIZE_INPUT = os.getenv("SANITIZE_INPUT", "true").lower() == "true"

# ============ Audit Logging ============
AUDIT_ENABLED = os.getenv("AUDIT_ENABLED", "true").lower() == "true"

# ============ Namespace Isolation ============
NAMESPACE_ISOLATION_ENABLED = os.getenv("NAMESPACE_ISOLATION_ENABLED", "false").lower() == "true"

# ============ A/B Testing ============
AB_TEST_ENABLED = os.getenv("AB_TEST_ENABLED", "false").lower() == "true"

# ============ Настройки сервера ============
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
RELOAD = os.getenv("RELOAD", "false").lower() == "true"
WORKERS = int(os.getenv("WORKERS", "1"))


# ============ Confidence Scoring ============
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
CONFIDENCE_THRESHOLD_CALIBRATED = float(os.getenv("CONFIDENCE_THRESHOLD_CALIBRATED", "0"))  # 0 = use fallback
MAX_VERIFY_LOOPS = int(os.getenv("MAX_VERIFY_LOOPS", "2"))
NLI_GROUNDING_ENABLED = os.getenv("NLI_GROUNDING_ENABLED", "true").lower() == "true"

# ============ Self-Correction ============
SELF_CRITIQUE_ENABLED = os.getenv("SELF_CRITIQUE_ENABLED", "true").lower() == "true"
COMPRESSION_STRATEGY = os.getenv("COMPRESSION_STRATEGY", "keyword")  # "perplexity", "keyword", "none"
REORDER_ENABLED = os.getenv("REORDER_ENABLED", "true").lower() == "true"
CRAG_DECOMPOSITION_ENABLED = os.getenv("CRAG_DECOMPOSITION_ENABLED", "true").lower() == "true"
NLI_MODEL_ENABLED = os.getenv("NLI_MODEL_ENABLED", "false").lower() == "true"

# ============ Level 5: Self-Correcting RAG ============
HYDE_ENABLED = os.getenv("HYDE_ENABLED", "true").lower() == "true"
REFLECTION_ENABLED = os.getenv("REFLECTION_ENABLED", "true").lower() == "true"
REFLECTION_DEPTH = int(os.getenv("REFLECTION_DEPTH", "2"))
# HALLUCINATION_CHECK_ENABLED gates the full hallucination detection pipeline
# (confidence scoring + NLI grounding + self-reflection). When enabled, acts
# as an alias for NLI_GROUNDING_ENABLED in the confidence layer.
# For granular control, use NLI_GROUNDING_ENABLED (grounding only).
HALLUCINATION_CHECK_ENABLED = os.getenv("HALLUCINATION_CHECK_ENABLED", "false").lower() == "true"

# ============ Self-Enrichment ============
ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "false").lower() == "true"

# ============ Token Optimizer ============
TOKEN_OPTIMIZER_ENABLED = os.getenv("TOKEN_OPTIMIZER_ENABLED", "true").lower() == "true"

# ============ vLLM Prefix Caching ============
# To enable in vLLM, set --enable-prefix-caching in the vLLM launch command.
# This reduces prefill latency by caching KV-cache from common prefixes.
# See: https://docs.vllm.ai/en/latest/features/prefix_caching.html
PREFIX_CACHING_ENABLED = os.getenv("PREFIX_CACHING_ENABLED", "false").lower() == "true"

# ============ Retrieval Evaluation ============
EVAL_DATASET_PATH = os.getenv("EVAL_DATASET_PATH", "./data/eval_dataset.json")

# ============ Admin Alerts ============
ADMIN_ALERT_ENABLED = os.getenv("ADMIN_ALERT_ENABLED", "false").lower() == "true"
ADMIN_ALERT_ENDPOINT = os.getenv("ADMIN_ALERT_ENDPOINT", "")

# ============ Tool Calling / Function Calling ============
TOOLS_ENABLED = os.getenv("TOOLS_ENABLED", "false").lower() == "true"
LIVE_SOURCES_ENABLED = os.getenv("LIVE_SOURCES_ENABLED", "false").lower() == "true"
TOOLS_PARALLEL_EXECUTION = os.getenv("TOOLS_PARALLEL_EXECUTION", "true").lower() == "true"
TOOLS_MAX_CONCURRENCY = int(os.getenv("TOOLS_MAX_CONCURRENCY", "10"))
TOOLS_DECLARATIVE_DIR = os.getenv("TOOLS_DECLARATIVE_DIR", "./tools/declarative")
TOOLS_OPENAPI_SPECS = os.getenv("TOOLS_OPENAPI_SPECS", "")

# ============ Live Source APIs ============
CONFLUENCE_API_URL = os.getenv("CONFLUENCE_API_URL", "")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
CONFLUENCE_API_USER = os.getenv("CONFLUENCE_API_USER", "")
JIRA_API_URL = os.getenv("JIRA_API_URL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_API_USER = os.getenv("JIRA_API_USER", "")
GITLAB_API_URL = os.getenv("GITLAB_API_URL", "")
GITLAB_API_TOKEN = os.getenv("GITLAB_API_TOKEN", "")

# ============ I18N / Multi-Language Support ============
I18N_ENABLED = os.getenv("I18N_ENABLED", "true").lower() == "true"
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
SUPPORTED_LANGUAGES = os.getenv("SUPPORTED_LANGUAGES", "en,ru,de,fr,zh").split(",")
MULTILINGUAL_INTENT_ENABLED = os.getenv("MULTILINGUAL_INTENT_ENABLED", "true").lower() == "true"
CROSS_LINGUAL_ENABLED = os.getenv("CROSS_LINGUAL_ENABLED", "true").lower() == "true"

# ============ Response Compression ============
COMPRESSION_ENABLED = os.getenv("COMPRESSION_ENABLED", "true").lower() == "true"
COMPRESSION_MIN_SIZE = int(os.getenv("COMPRESSION_MIN_SIZE", "500"))
COMPRESSION_LEVEL = int(os.getenv("COMPRESSION_LEVEL", "6"))

# ============ SSE Streaming Optimization ============
SSE_CHUNK_SIZE = int(os.getenv("SSE_CHUNK_SIZE", "4"))
STREAM_BUFFER_SIZE = int(os.getenv("STREAM_BUFFER_SIZE", "1"))

# ============ Model Warm-Up ============
WARMUP_ENABLED = os.getenv("WARMUP_ENABLED", "true").lower() == "true"
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "true").lower() == "true"

# ============ Model Evolution ============
MODEL_EVOLUTION_ENABLED = os.getenv("MODEL_EVOLUTION_ENABLED", "false").lower() == "true"

# MLflow
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "rag-system")
MLFLOW_ARTIFACT_ROOT = os.getenv("MLFLOW_ARTIFACT_ROOT", "s3://rag-artifacts")

# MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "rag-artifacts")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_DOCS_BUCKET = os.getenv("MINIO_DOCS_BUCKET", "rag-documents")

# SSL / TLS
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() == "true"
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "")  # Path to corporate CA bundle

# Training
TRAINING_PROFILE = os.getenv("TRAINING_PROFILE", "dev")

# Hot-Reload
HOT_RELOAD_ENABLED = os.getenv("HOT_RELOAD_ENABLED", "false").lower() == "true"
HOT_RELOAD_WATCH_INTERVAL = int(os.getenv("HOT_RELOAD_WATCH_INTERVAL", "5"))
HOT_RELOAD_SIGNAL_ENABLED = os.getenv("HOT_RELOAD_SIGNAL_ENABLED", "true").lower() == "true"

# Canary
CANARY_ENABLED = os.getenv("CANARY_ENABLED", "false").lower() == "true"
CANARY_PHASE_DURATION_5 = int(os.getenv("CANARY_PHASE_DURATION_5", "300"))
CANARY_PHASE_DURATION_25 = int(os.getenv("CANARY_PHASE_DURATION_25", "600"))
CANARY_PHASE_DURATION_50 = int(os.getenv("CANARY_PHASE_DURATION_50", "900"))
CANARY_PHASE_DURATION_75 = int(os.getenv("CANARY_PHASE_DURATION_75", "1200"))
CANARY_COOLDOWN_SECONDS = int(os.getenv("CANARY_COOLDOWN_SECONDS", "3600"))

# Eval Gate Thresholds
EVAL_GATE_LLM_BERTSCORE_MIN = float(os.getenv("EVAL_GATE_LLM_BERTSCORE_MIN", "0.70"))
EVAL_GATE_LLM_HALLUCINATION_MAX = float(os.getenv("EVAL_GATE_LLM_HALLUCINATION_MAX", "0.05"))
EVAL_GATE_LLM_ROUGE_L_MIN = float(os.getenv("EVAL_GATE_LLM_ROUGE_L_MIN", "0.35"))
EVAL_GATE_SLM_F1_MIN = float(os.getenv("EVAL_GATE_SLM_F1_MIN", "0.85"))
EVAL_GATE_SLM_ACCURACY_MIN = float(os.getenv("EVAL_GATE_SLM_ACCURACY_MIN", "0.90"))
EVAL_GATE_RERANKER_MRR_MIN = float(os.getenv("EVAL_GATE_RERANKER_MRR_MIN", "0.75"))
EVAL_GATE_RERANKER_NDCG_MIN = float(os.getenv("EVAL_GATE_RERANKER_NDCG_MIN", "0.70"))

# ============ Graceful Shutdown ============
GRACEFUL_SHUTDOWN_ENABLED = os.getenv("GRACEFUL_SHUTDOWN_ENABLED", "true").lower() == "true"
SHUTDOWN_TIMEOUT = int(os.getenv("SHUTDOWN_TIMEOUT", "30"))


# ============ Вспомогательная функция для отладки ============
def print_config() -> None:
    """Выводит текущую конфигурацию (скрывая секреты)."""
    config_vars = {k: v for k, v in globals().items() if not k.startswith("_") and isinstance(v, (str, int, bool))}
    # Маскируем чувствительные переменные
    sensitive_keys = ["API_KEY", "PASSWORD", "SECRET"]
    for key in config_vars:
        for sens in sensitive_keys:
            if sens in key:
                config_vars[key] = "***"
    print("RAG Proxy Configuration:")
    for key, value in config_vars.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    print_config()
