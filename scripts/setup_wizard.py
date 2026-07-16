#!/usr/bin/env python3
"""RAG System Configuration Wizard

Interactive setup wizard for configuring the RAG proxy environment.
Generates proxy/.env from user inputs with validation and connectivity testing.

Usage:
    python scripts/setup_wizard.py
    make wizard
"""

import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

# ── ANSI Colors ───────────────────────────────────────────────────────────────

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"


# ── Helpers ───────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"{GREEN}[RAG]{NC} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}")


def info(msg: str) -> None:
    print(f"{BLUE}[INFO]{NC} {msg}")


def header(msg: str) -> None:
    print(f"\n{CYAN}{BOLD}{'─' * 60}{NC}")
    print(f"{CYAN}{BOLD}  {msg}{NC}")
    print(f"{CYAN}{BOLD}{'─' * 60}{NC}\n")


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    """Ask user for input with optional default value."""
    while True:
        if default:
            value = input(f"  {prompt} [{default}]: ").strip()
            if not value:
                return default
        else:
            value = input(f"  {prompt}: ").strip()

        if required and not value:
            error("This field is required. Please enter a value.")
            continue

        return value


def ask_bool(prompt: str, default: bool = False) -> bool:
    """Ask yes/no question."""
    hint = "Y/n" if default else "y/N"
    value = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "true", "1")


def ask_choice(prompt: str, choices: list[str], default: str = "") -> str:
    """Ask user to choose from a list."""
    print(f"  {prompt}")
    for i, choice in enumerate(choices, 1):
        marker = " *" if choice == default else ""
        print(f"    {i}) {choice}{marker}")
    while True:
        value = input(f"  Select [1-{len(choices)}]: ").strip()
        if not value and default:
            return default
        try:
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            if value in choices:
                return value
        error(f"Invalid choice. Enter 1-{len(choices)}.")


# ── Validation ────────────────────────────────────────────────────────────────


def validate_url(url: str) -> bool:
    """Validate URL format."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def validate_host(host: str) -> bool:
    """Validate hostname or IP address."""
    if not host:
        return False
    # IP address pattern
    ip_pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    if re.match(ip_pattern, host):
        parts = host.split(".")
        return all(0 <= int(p) <= 255 for p in parts)
    # Hostname pattern
    hostname_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$"
    return bool(re.match(hostname_pattern, host))


def validate_port(port: str) -> bool:
    """Validate port number."""
    try:
        p = int(port)
        return 1 <= p <= 65535
    except ValueError:
        return False


# ── Connectivity Tests ────────────────────────────────────────────────────────


def test_tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    """Test TCP connectivity to host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def test_http(url: str, timeout: float = 5.0) -> bool:
    """Test HTTP connectivity."""
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


# ── Wizard Steps ──────────────────────────────────────────────────────────────


def step_llm() -> dict[str, str]:
    """Configure LLM backend."""
    header("1. LLM Backend Configuration")
    info("Configure the LLM endpoint (vLLM, llama.cpp, Ollama, OpenAI-compatible)")
    print()

    endpoint = ask(
        "LLM endpoint URL",
        default="http://localhost:8000/v1",
        required=True,
    )

    model_name = ask(
        "Model name (e.g., gemma-4-26b-it, llama-3.1-70b)",
        required=True,
    )

    api_key = ask("API key (leave empty if none)")

    provider = ask_choice(
        "LLM provider:",
        ["vllm", "llama_cpp", "openai_compatible", "ollama"],
        default="vllm",
    )

    return {
        "LLM_ENDPOINT": endpoint,
        "LLM_MODEL_NAME": model_name,
        "LLM_API_KEY": api_key,
        "LLM_PROVIDER": provider,
    }


def step_qdrant() -> dict[str, str]:
    """Configure Qdrant."""
    header("2. Qdrant Configuration")
    info("Qdrant is the vector database for hybrid search")
    print()

    host = ask("Qdrant host", default="localhost", required=True)
    port = ask("Qdrant HTTP port", default="6333", required=True)
    collection = ask("Collection name", default="knowledge_base")

    return {
        "QDRANT_HOST": host,
        "QDRANT_PORT": port,
        "COLLECTION_NAME": collection,
    }


def step_embedder() -> dict[str, str]:
    """Configure embedding model."""
    header("3. Embedding Model Configuration")
    info("BGE-M3 provides dense + sparse multilingual embeddings")
    print()

    model = ask(
        "Embedder model",
        default="BAAI/bge-m3",
        required=True,
    )

    device = ask_choice(
        "Embedding device:",
        ["cpu", "cuda"],
        default="cpu",
    )

    return {
        "EMBEDDER_MODEL": model,
        "EMBEDDER_DEVICE": device,
    }


def step_reranker() -> dict[str, str]:
    """Configure reranker."""
    header("4. Reranker Configuration")
    info("Cross-encoder for reranking retrieved chunks")
    print()

    model = ask(
        "Reranker model",
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        required=True,
    )

    return {
        "RERANKER_MODEL": model,
    }


def step_features() -> dict[str, str]:
    """Configure optional features."""
    header("5. Optional Features")
    info("Enable or disable optional components")
    print()

    config: dict[str, str] = {}

    # Redis
    if ask_bool("Enable Redis caching?", default=False):
        config["USE_REDIS"] = "true"
        redis_url = ask("Redis URL", default="redis://localhost:6379")
        config["REDIS_URL"] = redis_url
    else:
        config["USE_REDIS"] = "false"

    # Neo4j
    if ask_bool("Enable Neo4j knowledge graph?", default=False):
        config["GRAPH_ENABLED"] = "true"
        config["USE_GRAPH_EXPANSION"] = "true"
        neo4j_uri = ask("Neo4j URI", default="bolt://localhost:7687")
        neo4j_user = ask("Neo4j user", default="neo4j")
        neo4j_pass = ask("Neo4j password", required=True)
        config["NEO4J_URI"] = neo4j_uri
        config["NEO4J_USER"] = neo4j_user
        config["NEO4J_PASSWORD"] = neo4j_pass
    else:
        config["GRAPH_ENABLED"] = "false"
        config["USE_GRAPH_EXPANSION"] = "false"

    # LangGraph
    if ask_bool("Enable LangGraph agentic orchestration?", default=False):
        config["USE_LANGGRAPH"] = "true"
    else:
        config["USE_LANGGRAPH"] = "false"

    # Authentication
    if ask_bool("Enable JWT authentication?", default=False):
        config["AUTH_ENABLED"] = "true"
        import secrets

        jwt_secret = secrets.token_urlsafe(48)
        config["JWT_SECRET"] = jwt_secret
        info(f"Generated JWT secret: {jwt_secret[:16]}...")
    else:
        config["AUTH_ENABLED"] = "false"

    # Rate limiting
    if ask_bool("Enable rate limiting?", default=False):
        config["RATE_LIMIT_ENABLED"] = "true"
        rpm = ask("Requests per minute", default="60")
        config["RATE_LIMIT_PER_MINUTE"] = rpm
    else:
        config["RATE_LIMIT_ENABLED"] = "false"

    # Metrics
    if ask_bool("Enable Prometheus metrics?", default=True):
        config["METRICS_ENABLED"] = "true"
    else:
        config["METRICS_ENABLED"] = "false"

    return config


def step_validation(config: dict[str, str]) -> None:
    """Validate configuration."""
    header("6. Configuration Validation")
    log("Validating configuration...")

    errors: list[str] = []

    # Validate URLs
    for key in ("LLM_ENDPOINT",):
        if key in config and not validate_url(config[key]):
            errors.append(f"Invalid URL: {key}={config[key]}")

    # Validate hosts
    if "QDRANT_HOST" in config and not validate_host(config["QDRANT_HOST"]):
        errors.append(f"Invalid host: QDRANT_HOST={config['QDRANT_HOST']}")

    # Validate ports
    if "QDRANT_PORT" in config and not validate_port(config["QDRANT_PORT"]):
        errors.append(f"Invalid port: QDRANT_PORT={config['QDRANT_PORT']}")

    # Required fields
    for key in ("LLM_MODEL_NAME", "EMBEDDER_MODEL", "RERANKER_MODEL"):
        if not config.get(key):
            errors.append(f"Required field missing: {key}")

    if errors:
        for err in errors:
            error(f"  {err}")
        warn("Configuration has validation errors. Please fix and re-run.")
    else:
        log("Configuration is valid ✅")


def step_connectivity(config: dict[str, str]) -> None:
    """Test connectivity to configured services."""
    header("7. Connectivity Test")
    info("Testing connections to configured services...")
    print()

    results: list[tuple[str, bool]] = []

    # Qdrant
    qdrant_host = config.get("QDRANT_HOST", "localhost")
    qdrant_port = int(config.get("QDRANT_PORT", "6333"))
    ok = test_tcp(qdrant_host, qdrant_port)
    results.append((f"Qdrant ({qdrant_host}:{qdrant_port})", ok))
    status = f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"
    print(f"  {status} Qdrant ({qdrant_host}:{qdrant_port})")

    # LLM
    llm_endpoint = config.get("LLM_ENDPOINT", "")
    if llm_endpoint:
        # Try /models endpoint
        models_url = llm_endpoint.rstrip("/") + "/models"
        ok = test_http(models_url)
        results.append((f"LLM ({llm_endpoint})", ok))
        status = f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"
        print(f"  {status} LLM ({llm_endpoint})")

    # Redis
    if config.get("USE_REDIS") == "true":
        redis_url = config.get("REDIS_URL", "redis://localhost:6379")
        parsed = urlparse(redis_url)
        redis_host = parsed.hostname or "localhost"
        redis_port = parsed.port or 6379
        ok = test_tcp(redis_host, redis_port)
        results.append((f"Redis ({redis_host}:{redis_port})", ok))
        status = f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"
        print(f"  {status} Redis ({redis_host}:{redis_port})")

    # Neo4j
    if config.get("GRAPH_ENABLED") == "true":
        neo4j_uri = config.get("NEO4J_URI", "bolt://localhost:7687")
        parsed = urlparse(neo4j_uri)
        neo4j_host = parsed.hostname or "localhost"
        neo4j_port = parsed.port or 7687
        ok = test_tcp(neo4j_host, neo4j_port)
        results.append((f"Neo4j ({neo4j_host}:{neo4j_port})", ok))
        status = f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"
        print(f"  {status} Neo4j ({neo4j_host}:{neo4j_port})")

    print()
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    if passed == total:
        log(f"All {total} services reachable ✅")
    else:
        warn(f"{passed}/{total} services reachable. Unreachable services may not be started yet.")


# ── .env Generation ───────────────────────────────────────────────────────────

ENV_TEMPLATE = """\
# ───── RAG Proxy Configuration ─────
# Generated by setup wizard on {date}
# Edit as needed before starting services.

# ── Qdrant (vector database) ────────────────────────────────────────────────
QDRANT_HOST={QDRANT_HOST}
QDRANT_PORT={QDRANT_PORT}
COLLECTION_NAME={COLLECTION_NAME}

# ── Embedding model ─────────────────────────────────────────────────────────
EMBEDDER_MODEL={EMBEDDER_MODEL}
EMBEDDER_DEVICE={EMBEDDER_DEVICE}

# ── Reranker / Cross-Encoder ────────────────────────────────────────────────
RERANKER_MODEL={RERANKER_MODEL}
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32

# ── LLM / Primary Language Model ────────────────────────────────────────────
LLM_ENDPOINT={LLM_ENDPOINT}
LLM_MODEL_NAME={LLM_MODEL_NAME}
LLM_API_KEY={LLM_API_KEY}
LLM_PROVIDER={LLM_PROVIDER}
REQUEST_TIMEOUT=120
MAX_RETRIES=3
RETRY_DELAY=1.0

# ── SLM / Small Language Model ──────────────────────────────────────────────
SLM_ENDPOINT=
SLM_MODEL_NAME=
SLM_API_KEY=
SLM_MAX_TOKENS=256

# ── Retrieval parameters ────────────────────────────────────────────────────
MAX_CHUNKS_RETRIEVAL=50
MAX_CHUNKS_AFTER_RERANK=20

# ── Redis cache ─────────────────────────────────────────────────────────────
USE_REDIS={USE_REDIS}
REDIS_URL={REDIS_URL}

# ── LangGraph agentic orchestration ─────────────────────────────────────────
USE_LANGGRAPH={USE_LANGGRAPH}
MAX_RETRIEVAL_LOOPS=3

# ── Neo4j graph knowledge base ──────────────────────────────────────────────
GRAPH_ENABLED={GRAPH_ENABLED}
NEO4J_URI={NEO4J_URI}
NEO4J_USER={NEO4J_USER}
NEO4J_PASSWORD={NEO4J_PASSWORD}
USE_GRAPH_EXPANSION={USE_GRAPH_EXPANSION}

# ── Authentication ──────────────────────────────────────────────────────────
AUTH_ENABLED={AUTH_ENABLED}
JWT_SECRET={JWT_SECRET}
JWT_ALGORITHM=HS256
TOKEN_EXPIRE_HOURS=24
ACCESS_TOKEN_MINUTES=60

# ── User Database ───────────────────────────────────────────────────────────
USER_DB_PATH=./data/users.db
BCRYPT_ROUNDS=12
REFRESH_TOKEN_DAYS=30

# ── RBAC ────────────────────────────────────────────────────────────────────
RBAC_ENABLED=false

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_REQUESTS=false
LOG_DIR=./logs

# ── Observability ───────────────────────────────────────────────────────────
METRICS_ENABLED={METRICS_ENABLED}
LOG_FORMAT=text

# ── Rate Limiting ───────────────────────────────────────────────────────────
RATE_LIMIT_ENABLED={RATE_LIMIT_ENABLED}
RATE_LIMIT_PER_MINUTE={RATE_LIMIT_PER_MINUTE}
RATE_LIMIT_BURST=10

# ── Server ──────────────────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8080
RELOAD=false
WORKERS=1

# ── Confidence Scoring ───────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD=0.5
MAX_VERIFY_LOOPS=2

# ── Self-Enrichment ──────────────────────────────────────────────────────────
ENRICHMENT_ENABLED=false

# ── Admin Alerts ─────────────────────────────────────────────────────────────
ADMIN_ALERT_ENABLED=false
ADMIN_ALERT_ENDPOINT=

# ── Tools / Function Calling ─────────────────────────────────────────────────
TOOLS_ENABLED=false
LIVE_SOURCES_ENABLED=false
TOOLS_PARALLEL_EXECUTION=true
TOOLS_MAX_CONCURRENCY=10
"""


def generate_env(config: dict[str, str], output_path: Path) -> None:
    """Generate .env file from configuration."""
    from datetime import datetime

    # Defaults for optional fields
    defaults = {
        "LLM_API_KEY": "",
        "LLM_PROVIDER": "vllm",
        "USE_REDIS": "false",
        "REDIS_URL": "redis://localhost:6379",
        "USE_LANGGRAPH": "false",
        "GRAPH_ENABLED": "false",
        "USE_GRAPH_EXPANSION": "false",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "",
        "AUTH_ENABLED": "false",
        "JWT_SECRET": "change-me-in-production",
        "METRICS_ENABLED": "true",
        "RATE_LIMIT_ENABLED": "false",
        "RATE_LIMIT_PER_MINUTE": "60",
        "EMBEDDER_DEVICE": "cpu",
    }

    merged = {**defaults, **config}
    merged["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = ENV_TEMPLATE.format(**merged)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    log(f"Configuration saved to {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║       RAG System — Configuration Wizard             ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    info("This wizard will guide you through configuring the RAG proxy.")
    info("Press Enter to accept defaults shown in [brackets].")
    print()

    # Determine project root
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    env_path = project_root / "proxy" / ".env"

    # Check if .env already exists
    if env_path.exists():
        warn(f"{env_path} already exists.")
        if not ask_bool("Overwrite existing configuration?", default=False):
            info("Keeping existing configuration. Exiting.")
            return

    # Collect configuration
    config: dict[str, str] = {}

    config.update(step_llm())
    config.update(step_qdrant())
    config.update(step_embedder())
    config.update(step_reranker())
    config.update(step_features())

    # Validate
    step_validation(config)

    # Test connectivity
    if ask_bool("Run connectivity tests?", default=True):
        step_connectivity(config)

    # Generate .env
    print()
    if ask_bool(f"Save configuration to {env_path}?", default=True):
        generate_env(config, env_path)
        print()
        log("Setup complete! Next steps:")
        info(f"  1. Review {env_path}")
        info("  2. Start services:  make docker-up")
        info("  3. Test the API:    curl http://localhost:8080/v1/health")
        info("  4. View logs:       make docker-logs")
    else:
        info("Configuration not saved. Exiting.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        warn("Wizard cancelled by user.")
        sys.exit(1)
