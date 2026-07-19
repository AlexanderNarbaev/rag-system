# proxy/app/config.py
"""RAG proxy configuration.

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
# Examples: cross-encoder/ms-marco-MiniLM-L-6-v2 (fallback), BAAI/bge-reranker-v2-m3 (default)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "8192"))
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

# ============ Available Models ============
# Comma-separated list of model names served by the LLM backend.
# Defaults to LLM_MODEL_NAME if not set.
AVAILABLE_MODELS = [m.strip() for m in os.getenv("AVAILABLE_MODELS", LLM_MODEL_NAME).split(",") if m.strip()]

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

# ============ Progressive Retrieval (FR-25) ============
PROGRESSIVE_RETRIEVAL_ENABLED = os.getenv("PROGRESSIVE_RETRIEVAL_ENABLED", "true").lower() == "true"
PROGRESSIVE_RETRIEVAL_STAGES = os.getenv("PROGRESSIVE_RETRIEVAL_STAGES", "5,10,20")

# ============ Кэш ============
USE_REDIS = os.getenv("USE_REDIS", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "proxy:")

# ============ Semantic Response Cache ============
SEMANTIC_CACHE_ENABLED = os.getenv("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
SEMANTIC_CACHE_SIMILARITY = float(os.getenv("SEMANTIC_CACHE_SIMILARITY", "0.92"))
SEMANTIC_CACHE_TTL = int(os.getenv("SEMANTIC_CACHE_TTL", "300"))

# ============ Агентная оркестрация (LangGraph) ============
USE_LANGGRAPH = os.getenv("USE_LANGGRAPH", "false").lower() == "true"

# ── Adaptive routing (opt-in) ──
ADAPTIVE_ROUTING_ENABLED = os.getenv("ADAPTIVE_ROUTING_ENABLED", "false").lower() == "true"
MAX_RETRIEVAL_LOOPS = int(os.getenv("MAX_RETRIEVAL_LOOPS", "3"))

# ============ Граф знаний (Neo4j) ============
GRAPH_ENABLED = os.getenv("GRAPH_ENABLED", "false").lower() == "true"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
USE_GRAPH_EXPANSION = os.getenv("USE_GRAPH_EXPANSION", "false").lower() == "true"

if GRAPH_ENABLED and not NEO4J_PASSWORD:
    import warnings

    warnings.warn(
        "GRAPH_ENABLED is true but NEO4J_PASSWORD is empty. Set NEO4J_PASSWORD in your environment.",
        stacklevel=2,
    )

# ============ Логирование и HITL ============
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "true").lower() == "true"
LOG_DIR = os.getenv("LOG_DIR", "./logs")

# ============ Безопасность ============
# Список секретов для маскировки в логах (дополнительно)
SENSITIVE_SECRETS = os.getenv("SENSITIVE_SECRETS", "").split(",") if os.getenv("SENSITIVE_SECRETS") else []

# ============ Observability ============
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" or "text"
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
FEEDBACK_RATE_LIMIT = int(os.getenv("FEEDBACK_RATE_LIMIT", "100"))  # submissions per hour per user

# ============ CORS ============
# Default allows localhost only. For production, set explicit allowed origins.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")

# ============ Authentication & RBAC ============
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "RS256")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "rag-proxy")
JWT_ISSUER = os.getenv("JWT_ISSUER", "rag-proxy")
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "24"))
AUTH_VALID_USERS = os.getenv("AUTH_VALID_USERS", "{}")  # JSON dict of valid users for login endpoint

# ── User Database (SQLite) ──
USER_DB_PATH = os.getenv("USER_DB_PATH", "./data/users.db")
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# ── Auth startup validation ──
_JWT_IS_EPHEMERAL = False
if AUTH_ENABLED and not JWT_SECRET:
    import secrets
    import warnings

    JWT_SECRET = secrets.token_hex(32)
    _JWT_IS_EPHEMERAL = True
    warnings.warn(
        "AUTH_ENABLED is true but JWT_SECRET is empty — auto-generated an ephemeral key. "
        "Tokens WILL NOT survive restarts. Set JWT_SECRET in your environment for persistence. "
        "Generate with: openssl rand -hex 32",
        stacklevel=2,
    )


def validate_auth_config() -> None:
    """Validate authentication configuration at startup. Called from main.py lifespan."""
    if _JWT_IS_EPHEMERAL:
        import warnings

        warnings.warn(
            "JWT_SECRET is ephemeral (auto-generated). All issued tokens will be invalidated on restart. "
            "For production, set JWT_SECRET in your environment.",
            stacklevel=2,
        )
    if _ETL_SECRET_IS_EPHEMERAL:
        import warnings

        warnings.warn(
            "ETL_SECRET is ephemeral (auto-generated). ETL admin API tokens will not survive restarts. "
            "For production, set ETL_SECRET in your environment and ETL config.",
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
RBAC_ENABLED = os.getenv("RBAC_ENABLED", "true").lower() == "true"

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
HYDE_ENABLED_IN_PROGRESSIVE = os.getenv("HYDE_ENABLED_IN_PROGRESSIVE", "true").lower() == "true"
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

# ============ Qdrant Performance Tuning ============
# Scalar quantization reduces memory usage ~4x for 1024-dim vectors.
# Enables int8 quantization for all vectors in the collection.
# See: https://qdrant.tech/documentation/guides/quantization/
QDRANT_QUANTIZATION_ENABLED = os.getenv("QDRANT_QUANTIZATION_ENABLED", "false").lower() == "true"

# gRPC gives ~3-5x higher throughput than HTTP for Qdrant operations.
# Requires Qdrant gRPC port to be accessible (default: 6334).
QDRANT_GRPC_ENABLED = os.getenv("QDRANT_GRPC_ENABLED", "false").lower() == "true"
QDRANT_GRPC_PORT = int(os.getenv("QDRANT_GRPC_PORT", "6334"))

# HNSW tuning for better recall/speed tradeoff in production workloads.
# m=16: higher m improves recall at cost of build time and memory.
# ef_construct=100: larger build-time search depth improves index quality.
# See: https://qdrant.tech/documentation/guides/optimize/
QDRANT_HNSW_M = int(os.getenv("QDRANT_HNSW_M", "16"))
QDRANT_HNSW_EF_CONSTRUCT = int(os.getenv("QDRANT_HNSW_EF_CONSTRUCT", "100"))

# ============ Retrieval Evaluation ============
EVAL_DATASET_PATH = os.getenv("EVAL_DATASET_PATH", "./data/eval_dataset.json")

# ============ Admin Alerts ============
ADMIN_ALERT_ENABLED = os.getenv("ADMIN_ALERT_ENABLED", "false").lower() == "true"
ADMIN_ALERT_ENDPOINT = os.getenv("ADMIN_ALERT_ENDPOINT", "")
ALERT_CONFIDENCE_THRESHOLD = float(os.getenv("ALERT_CONFIDENCE_THRESHOLD", "0.5"))

# ============ Ungrounded Generation ============
# When enabled, the LLM will generate answers even when no relevant knowledge is found.
# A notice is prepended indicating the answer is not based on the knowledge base.
ALLOW_UNGROUNDED_GENERATION = os.getenv("ALLOW_UNGROUNDED_GENERATION", "true").lower() == "true"
UNGROUNDED_NOTICE = os.getenv(
    "UNGROUNDED_NOTICE",
    "⚠️ The RAG knowledge base contains no relevant information on this topic. "
    "The following answer is based on the model's internal training data "
    "and may be inaccurate. For reliable answers, please add relevant "
    "documents to the knowledge base.",
)

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

# ============ Conversation Memory ============
CONVERSATION_MAX_TURNS = int(os.getenv("CONVERSATION_MAX_TURNS", "10"))
CONVERSATION_SUMMARY_THRESHOLD_TOKENS = int(os.getenv("CONVERSATION_SUMMARY_THRESHOLD_TOKENS", "2000"))
SESSION_TTL = int(os.getenv("SESSION_TTL", "1800"))
CLARIFICATION_ENABLED = os.getenv("CLARIFICATION_ENABLED", "true").lower() == "true"

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
USE_BROTLI = os.getenv("USE_BROTLI", "false").lower() == "true"

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
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "rag-artifacts")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_DOCS_BUCKET = os.getenv("MINIO_DOCS_BUCKET", "rag-documents")

if MODEL_EVOLUTION_ENABLED and (not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY):
    import warnings

    warnings.warn(
        "MODEL_EVOLUTION_ENABLED is true but MINIO_ACCESS_KEY or MINIO_SECRET_KEY is empty. "
        "MinIO S3 storage will fail. Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY in your environment.",
        stacklevel=2,
    )

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

# ============ Stale Document Detection ============
STALE_DETECTION_ENABLED = os.getenv("STALE_DETECTION_ENABLED", "true").lower() == "true"
STALE_CONFLUENCE_DAYS = int(os.getenv("STALE_CONFLUENCE_DAYS", "90"))
STALE_JIRA_DAYS = int(os.getenv("STALE_JIRA_DAYS", "30"))
STALE_GITLAB_DAYS = int(os.getenv("STALE_GITLAB_DAYS", "14"))
STALE_DEFAULT_DAYS = int(os.getenv("STALE_DEFAULT_DAYS", "180"))
STALE_DETECTION_SCAN_LIMIT = int(os.getenv("STALE_DETECTION_SCAN_LIMIT", "500"))

# ============ Reindex Scheduler ============
REINDEX_ENABLED = os.getenv("REINDEX_ENABLED", "true").lower() == "true"
REINDEX_CHECK_INTERVAL = int(os.getenv("REINDEX_CHECK_INTERVAL", "3600"))
REINDEX_STALENESS_THRESHOLD = int(os.getenv("REINDEX_STALENESS_THRESHOLD", "80"))
REINDEX_MAX_CONCURRENT_TASKS = int(os.getenv("REINDEX_MAX_CONCURRENT_TASKS", "5"))

# ============ Knowledge Integrity Validation ============
INTEGRITY_CHECK_ENABLED = os.getenv("INTEGRITY_CHECK_ENABLED", "true").lower() == "true"
INTEGRITY_NLI_CONTRADICTION_THRESHOLD = float(os.getenv("INTEGRITY_NLI_CONTRADICTION_THRESHOLD", "0.7"))
INTEGRITY_CHUNK_SAMPLE_LIMIT = int(os.getenv("INTEGRITY_CHUNK_SAMPLE_LIMIT", "200"))

# ============ Graceful Shutdown ============
GRACEFUL_SHUTDOWN_ENABLED = os.getenv("GRACEFUL_SHUTDOWN_ENABLED", "true").lower() == "true"
SHUTDOWN_TIMEOUT = int(os.getenv("SHUTDOWN_TIMEOUT", "30"))

# ============ ETL IPC Secret ============
ETL_SECRET = os.getenv("ETL_SECRET", "")
_ETL_SECRET_IS_EPHEMERAL = False
if not ETL_SECRET and os.getenv("REINDEX_ENABLED", "true").lower() != "false":
    import secrets as _etl_secrets
    import warnings as _etl_warnings

    _ETL_SECRET_FILE = Path(__file__).parent.parent / "data" / ".etl_secret"
    try:
        if _ETL_SECRET_FILE.exists():
            ETL_SECRET = _ETL_SECRET_FILE.read_text().strip()
        else:
            ETL_SECRET = _etl_secrets.token_hex(32)
            _ETL_SECRET_IS_EPHEMERAL = False
            _ETL_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            _ETL_SECRET_FILE.write_text(ETL_SECRET)
    except OSError as _etl_fs_err:
        ETL_SECRET = _etl_secrets.token_hex(32)
        _ETL_SECRET_IS_EPHEMERAL = True
        _etl_warnings.warn(
            f"ETL_SECRET is empty but REINDEX_ENABLED is not false — auto-generated an ephemeral key. "
            f"ETL will be unable to authenticate to the proxy across restarts. "
            f"Could not persist to file ({_etl_fs_err}). "
            f"Set ETL_SECRET in your environment for persistence. "
            f"Generate with: openssl rand -hex 32",
            stacklevel=2,
        )


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
