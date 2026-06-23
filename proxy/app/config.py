# proxy/app/config.py
"""
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

# ============ Reranker / Cross-Encoder ============
# Examples: cross-encoder/ms-marco-MiniLM-L-6-v2, BAAI/bge-reranker-v2-m3, mixedbread-ai/mxbai-rerank-large-v1
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "")
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
RERANKER_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", "32"))

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
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", None)
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

# ============ Rate Limiting ============
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "10"))

# ============ CORS ============
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# ============ Authentication & RBAC ============
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "24"))
AUTH_VALID_USERS = os.getenv("AUTH_VALID_USERS", "{}")  # JSON dict of valid users for login endpoint

# ============ Настройки сервера ============
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
RELOAD = os.getenv("RELOAD", "false").lower() == "true"
WORKERS = int(os.getenv("WORKERS", "1"))


# ============ Confidence Scoring ============
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
MAX_VERIFY_LOOPS = int(os.getenv("MAX_VERIFY_LOOPS", "2"))

# ============ Self-Enrichment ============
ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "false").lower() == "true"

# ============ Admin Alerts ============
ADMIN_ALERT_ENABLED = os.getenv("ADMIN_ALERT_ENABLED", "false").lower() == "true"
ADMIN_ALERT_ENDPOINT = os.getenv("ADMIN_ALERT_ENDPOINT", "")

# ============ Вспомогательная функция для отладки ============
def print_config():
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
