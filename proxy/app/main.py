# proxy/app/main.py
"""
OpenAI-compatible RAG proxy server.

Supports:
- /v1/chat/completions (stream + non-stream) via api/chat router
- /v1/models
- /v1/health via api/health router
- /v1/auth/* via api/auth_endpoints router
- /v1/tools via api/tools router
- /v1/feedback via api/feedback router
- /v1/widget via api/widget router
- /v1/admin/* via api/admin router
- /metrics via api/metrics router

Uses:
- Qdrant for hybrid search
- Cross-encoder for reranking
- LangGraph (optional) for agentic orchestration
- Redis for embedding cache (optional)
"""

import asyncio
import logging
import os
import signal
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware

from proxy.app.auth import (
    AUTH_ENABLED,
    AuthMiddleware,
    UserContext,
)
from proxy.app.core.context import (  # noqa: F401 — re-export for test patching
    build_context,
    deduplicate_chunks,
    extract_version_from_query,
)
from proxy.app.core.rerank import rerank_chunks
from proxy.app.core.retrieval import hybrid_search
from proxy.app.core.retrieval_evaluator import RetrievalEvaluator
from proxy.app.core.token_optimizer import TokenOptimizer
from proxy.app.llm.provider import non_stream_completion, stream_completion  # noqa: F401 — re-export for test patching
from proxy.app.shared.access_control import (
    build_access_filter,
    filter_chunks,
)
from proxy.app.shared.audit import AuditLogger, RequestTracker
from proxy.app.shared.cache import CacheManager

# Internal module imports
from proxy.app.shared.config import (
    COMPRESSION_ENABLED,
    COMPRESSION_LEVEL,
    COMPRESSION_MIN_SIZE,
    CORS_ORIGINS,
    GRACEFUL_SHUTDOWN_ENABLED,
    LLM_MODEL_NAME,
    LOG_DIR,
    LOG_REQUESTS,  # noqa: F401 — re-export for test patching
    MAX_CHUNKS_AFTER_RERANK,
    MAX_CHUNKS_RETRIEVAL,
    OTEL_ENABLED,
    RATE_LIMIT_BURST,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_PER_MINUTE,
    REDIS_URL,
    SHUTDOWN_TIMEOUT,
    TOOLS_DECLARATIVE_DIR,
    TOOLS_ENABLED,
    TOOLS_OPENAPI_SPECS,
    USE_LANGGRAPH,
    USE_REDIS,
    WARMUP_ENABLED,
    WARMUP_ON_STARTUP,
)
from proxy.app.shared.logging import setup_logging
from proxy.app.shared.metrics import init_metrics
from proxy.app.shared.middleware import add_cors_middleware, setup_all_middleware
from proxy.app.shared.rate_limiter import add_rate_limit_middleware
from proxy.app.tools.registry import get_enhanced_registry

# Optional modules
if USE_LANGGRAPH:
    from proxy.app.core.orchestrator import get_orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("rag-proxy")

# ---------------------------------------------------------------------------
# Global state (tests mock these at proxy.app.main.*)
# ---------------------------------------------------------------------------
cache_manager = None
orchestrator = None
audit_logger = None
request_tracker = RequestTracker()
token_optimizer = TokenOptimizer()
retrieval_evaluator = RetrievalEvaluator()

shutting_down = False
_active_requests: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: initialize and clean up resources."""
    global cache_manager, orchestrator, audit_logger
    setup_logging()
    logger.info("Starting RAG Proxy...")
    init_metrics()

    # OpenTelemetry tracing (graceful degradation)
    if OTEL_ENABLED:
        try:
            from proxy.app.shared.tracing import setup_tracing

            setup_tracing()
            logger.info("OpenTelemetry tracing initialized")
        except Exception as e:
            logger.warning("OpenTelemetry tracing setup failed (non-blocking): %s", e)

    audit_logger = AuditLogger(log_dir=LOG_DIR)
    # Initialize cache
    if USE_REDIS and REDIS_URL:
        cache_manager = CacheManager(redis_url=REDIS_URL)
        await cache_manager.initialize()
        logger.info("Redis cache initialized")
    else:
        cache_manager = CacheManager(use_redis=False)
        logger.info("In-memory cache initialized (no Redis)")
    # Initialize LangGraph orchestrator (if enabled)
    if USE_LANGGRAPH:
        orchestrator = get_orchestrator()
        logger.info("LangGraph orchestrator initialized")
    # Tool discovery from all providers
    if TOOLS_ENABLED:
        registry = get_enhanced_registry()

        # Declarative provider
        if os.path.isdir(TOOLS_DECLARATIVE_DIR):
            try:
                from proxy.app.tools.declarative import DeclarativeProvider

                provider = DeclarativeProvider()
                discovered = await provider.discover()
                for tool in discovered:
                    registry.register(tool)
                logger.info("Startup: loaded %d tools from declarative provider", len(discovered))
            except Exception as e:
                logger.warning("Startup: declarative tool discovery failed: %s", e)

        # OpenAPI provider
        if TOOLS_OPENAPI_SPECS:
            try:
                from proxy.app.tools.openapi_discovery import OpenAPIProvider

                provider = OpenAPIProvider()
                discovered = await provider.discover()
                for tool in discovered:
                    registry.register(tool)
                logger.info("Startup: loaded %d tools from OpenAPI provider", len(discovered))
            except Exception as e:
                logger.warning("Startup: OpenAPI tool discovery failed: %s", e)
    # Model warm-up on startup
    if WARMUP_ENABLED and WARMUP_ON_STARTUP:
        try:
            from proxy.app.shared.warmup import warmup_all

            warmup_result = await warmup_all()
            logger.info(f"Model warm-up completed: {warmup_result}")
        except Exception as e:
            logger.warning(f"Model warm-up failed (non-blocking): {e}")

    if GRACEFUL_SHUTDOWN_ENABLED:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_initiate_shutdown(s)))
            except (NotImplementedError, RuntimeError, ValueError):
                logger.info(f"Signal handler for {sig.name} skipped (not supported in this environment)")
        logger.info("Graceful shutdown handlers registered")

    logger.info("RAG Proxy ready")
    yield
    # Cleanup
    global shutting_down
    shutting_down = True
    logger.info("Draining in-flight requests...")
    if _active_requests:
        done, pending = await asyncio.wait(_active_requests, timeout=SHUTDOWN_TIMEOUT)
        for task in pending:
            task.cancel()
        logger.info(f"Drained {len(done)} requests, cancelled {len(pending)}")
    if cache_manager:
        await cache_manager.close()
    logger.info("RAG Proxy shutdown")


async def _initiate_shutdown(sig: signal.Signals):
    """Initiate graceful shutdown on SIGTERM/SIGINT."""
    global shutting_down
    if shutting_down:
        return
    shutting_down = True
    logger.info(f"Received signal {sig.name}, starting graceful shutdown...")
    await asyncio.sleep(0.5)
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


# ---------------------------------------------------------------------------
# Core RAG pipeline (tests mock internals at proxy.app.main.*)
# ---------------------------------------------------------------------------


async def process_rag_query(
    user_query: str,
    version: str | None = None,
    force_refresh: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    stream: bool = False,
    other_messages: list[dict] = None,
    user_context: UserContext | None = None,
    top_k_override: int | None = None,
):
    """
    Core RAG pipeline:
    1. Qdrant hybrid search
    2. Access control filtering
    3. Reranking
    4. Deduplication and version filtering
    5. Context assembly
    6. LLM call
    """
    if user_context is None:
        user_context = UserContext.anonymous()

    _access_filter = build_access_filter(user_context)

    # 1. Cache check
    cache_key = f"rag:{user_context.user_id}:{user_query}:{version or 'latest'}"
    if not force_refresh and cache_manager:
        cached = await cache_manager.get(cache_key)
        if cached:
            logger.info(f"Cache hit for query: {user_query[:50]}...")
            return cached, "", True, []

    # 2. Hybrid search
    try:
        search_results = hybrid_search(query=user_query, version=version, top_k=top_k_override or MAX_CHUNKS_RETRIEVAL)
    except Exception as e:
        logger.warning(f"Hybrid search failed (degraded mode): {e}")
        search_results = None
    sources: list[dict] = []
    if not search_results:
        context = ""
        chunks_metadata = []
    else:
        chunks_texts = [hit.payload["text"] for hit in search_results]
        chunks_metadata = [hit.payload for hit in search_results]
        scores = [hit.score for hit in search_results]

        # 2.5. Row-level access control filtering
        chunk_dicts = [{**meta, "_score": scores[i]} for i, meta in enumerate(chunks_metadata)]
        filtered_chunks = filter_chunks(chunk_dicts, user_context)
        if len(filtered_chunks) < len(chunk_dicts):
            logger.info(
                f"Access control filtered {len(chunk_dicts) - len(filtered_chunks)} "
                f"chunks (user={user_context.username}, roles={user_context.roles})"
            )

        if not filtered_chunks:
            context = ""
            chunks_metadata = []
        else:
            filtered_metadata = []
            filtered_scores = []
            filtered_texts = []
            for fc in filtered_chunks:
                score = fc.pop("_score", 0.0)
                filtered_metadata.append(fc)
                filtered_scores.append(score)
                filtered_texts.append(fc.get("text", ""))
            chunks_metadata = filtered_metadata
            scores = filtered_scores
            chunks_texts = filtered_texts

            # 3. Reranking
            reranked_indices = rerank_chunks(user_query, chunks_texts, top_k=MAX_CHUNKS_AFTER_RERANK)
            reranked_chunks = [(chunks_metadata[i], scores[i]) for i in reranked_indices]

            # 4. Deduplication and versioning
            unique_chunks = deduplicate_chunks(reranked_chunks)

            # 5. Build source citations
            from proxy.app.core.context import compute_chunk_hash

            for chunk, score in unique_chunks:
                sources.append(
                    {
                        "chunk_id": compute_chunk_hash(chunk),
                        "source": chunk.get("source_type", "unknown"),
                        "title": chunk.get("title", "") or chunk.get("doc_title", ""),
                        "version": chunk.get("version", "unknown"),
                        "relevance": round(score, 4),
                        "text_preview": chunk.get("text", "")[:200],
                    }
                )

            # 6. Retrieval quality evaluation (CRAG-style)
            chunks_for_eval = []
            for c, s in unique_chunks:
                c_copy = dict(c)
                c_copy["score"] = s
                chunks_for_eval.append(c_copy)
            confidence, action, quality_processed = retrieval_evaluator.evaluate_and_act(
                query=user_query, retrieved_chunks=chunks_for_eval
            )
            logger.info(f"Retrieval quality: confidence={confidence:.3f}, action={action}")

            if action == "FALLBACK":
                context = ""
                chunks_metadata = []
            elif action == "EXPAND":
                context = build_context(unique_chunks, max_tokens=100000)
            else:
                # 7. Smart token budget allocation
                available_tokens = 130000
                budget = token_optimizer.smart_token_budget(
                    available_tokens=available_tokens, num_chunks=len(unique_chunks)
                )

                # 8. Context compression with budget
                raw_context = build_context(unique_chunks, max_tokens=budget["context_total"], include_metadata=True)

                if budget["context_total"] < len(raw_context) // 4:
                    context = token_optimizer.compress_context(
                        [c for c, _ in unique_chunks], max_tokens=budget["context_total"], strategy="hierarchical"
                    )
                else:
                    context = raw_context

                logger.info(
                    f"Token budget: system={budget['system_prompt']}, "
                    f"context={budget['context_total']}, response={budget['response']}"
                )

    # 9. Build system prompt
    system_prompt = (
        "Ты – технический ассистент. Используй предоставленный контекст для ответа. "
        "Если контекст противоречив, укажи на противоречия. Если не знаешь, скажи честно.\n\n"
        f"Контекст:\n{context}"
    )
    messages_for_llm = [{"role": "system", "content": system_prompt}]
    if other_messages:
        for msg in other_messages:
            if msg.get("role") != "system":
                messages_for_llm.append(msg)

    # 10. LLM call
    if stream:
        return context, messages_for_llm, False, sources
    else:
        response_text = await non_stream_completion(messages_for_llm, temperature=temperature, max_tokens=max_tokens)
        if cache_manager and not force_refresh:
            await cache_manager.set(cache_key, response_text, ttl=3600)
        return response_text, context, False, sources


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAG Proxy for Gemma",
    description="OpenAI-compatible proxy with hybrid search, reranking, and Gemma LLM",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware setup (order matters: CORS > auth > correlation > request-id > logging > rate-limit > compression)
add_cors_middleware(app, origins=CORS_ORIGINS)
if AUTH_ENABLED:
    app.add_middleware(AuthMiddleware)
setup_all_middleware(app, audit_logger=audit_logger)
if RATE_LIMIT_ENABLED:
    add_rate_limit_middleware(app, rate_per_minute=RATE_LIMIT_PER_MINUTE, burst=RATE_LIMIT_BURST)
if COMPRESSION_ENABLED:
    app.add_middleware(GZipMiddleware, minimum_size=COMPRESSION_MIN_SIZE, compresslevel=COMPRESSION_LEVEL)

# OpenTelemetry FastAPI instrumentation
if OTEL_ENABLED:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OpenTelemetry instrumentation enabled")
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed")
    except Exception as e:
        logger.warning("FastAPI instrumentation failed (non-blocking): %s", e)


# ---------------------------------------------------------------------------
# /v1/models endpoint (kept here — not part of router task)
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


@app.get("/v1/models")
async def list_models():
    """Return list of available models."""
    models = [
        ModelInfo(id=LLM_MODEL_NAME, created=int(time.time())),
        ModelInfo(id="rag-proxy", created=int(time.time())),
    ]
    return ModelsResponse(data=models)


# ---------------------------------------------------------------------------
# Include all routers
# ---------------------------------------------------------------------------

from proxy.app.api import (  # noqa: E402
    admin_router,
    auth_router,
    chat_router,
    feedback_router,
    health_router,
    metrics_router,
    tools_router,
    widget_router,
)

app.include_router(metrics_router)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(feedback_router)
app.include_router(widget_router)
app.include_router(admin_router)


# ---------------------------------------------------------------------------
# Backward-compatible re-exports for tests (proxy.app.main.*)
# ---------------------------------------------------------------------------

# Re-export chat models and helpers so tests that do
# ``from proxy.app.main import ChatMessage`` still work.
# Re-export admin helpers so tests that patch
# ``proxy.app.main._get_model_registry`` still work.
from proxy.app.api.admin import (  # noqa: E402, F401
    _canary_state,
    _get_model_registry,
    _training_jobs,
)
from proxy.app.api.chat import (  # noqa: E402, F401
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatMessage,
    StreamOptimizer,
    generate_request_id,
)

# Re-export tools helpers so tests that patch
# ``proxy.app.main._highest_role_from_user`` still work.
from proxy.app.api.tools import _highest_role_from_user  # noqa: E402, F401

# Re-export hitl helpers so tests that patch
# ``proxy.app.main.log_interaction`` still work (chat.py uses _main.log_interaction).
from proxy.app.core.hitl import log_interaction  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        workers=1,
    )
