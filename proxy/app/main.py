# proxy/app/main.py
"""OpenAI-compatible RAG proxy server.

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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware

from proxy.app.auth import (
    AUTH_ENABLED,
    AuthMiddleware,
    UserContext,
)
from proxy.app.core.confidence import should_generate_answer
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
    COLLECTION_NAME,
    COMPRESSION_ENABLED,
    COMPRESSION_LEVEL,
    COMPRESSION_MIN_SIZE,
    CORS_ORIGINS,
    GRACEFUL_SHUTDOWN_ENABLED,
    GRAPH_ENABLED,
    LLM_MODEL_NAME,
    LOG_DIR,
    LOG_REQUESTS,  # noqa: F401 — re-export for test patching
    MAX_CHUNKS_AFTER_RERANK,
    MAX_CHUNKS_RETRIEVAL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
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
    USER_DB_PATH,
    WARMUP_ENABLED,
    WARMUP_ON_STARTUP,
)
from proxy.app.shared.logging import setup_logging
from proxy.app.shared.metrics import init_metrics
from proxy.app.shared.middleware import add_cors_middleware, setup_all_middleware
from proxy.app.shared.rate_limiter import add_rate_limit_middleware
from proxy.app.tools.registry import get_enhanced_registry

# Optional modules
# Note: get_orchestrator is imported lazily inside lifespan() to avoid
# "possibly unbound" type-checker warnings and to keep the module-level
# import surface minimal when USE_LANGGRAPH is false.

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("rag-proxy")

# ---------------------------------------------------------------------------
# Global state (tests mock these at proxy.app.main.*)
# ---------------------------------------------------------------------------
cache_manager = None
orchestrator = None
audit_logger = None
kb_manager = None
request_tracker = RequestTracker()
token_optimizer = TokenOptimizer()
retrieval_evaluator = RetrievalEvaluator()

shutting_down = False
_active_requests: set[asyncio.Task[None]] = set()

# Default TTL for cached responses (1 hour)
DEFAULT_CACHE_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Qdrant collection auto-provisioning
# ---------------------------------------------------------------------------


def _ensure_qdrant_collection() -> None:
    """Create the default knowledge-base collection in Qdrant if it doesn't exist.

    Called during startup so the proxy works out-of-the-box even when the
    separate ``scripts/init_collections.py`` hasn't been run yet.
    """
    from proxy.app.core.retrieval import qdrant_client

    if qdrant_client is None:
        logger.warning("Qdrant client not available — skipping collection check")
        return

    try:
        existing = {c.name for c in qdrant_client.get_collections().collections}
        if COLLECTION_NAME in existing:
            logger.info("Qdrant collection '%s' already exists", COLLECTION_NAME)
            return
        # Create collection with named dense vector (matches ETL indexer schema)
        from qdrant_client.http import models as qmodels

        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": qmodels.VectorParams(size=1024, distance=qmodels.Distance.COSINE),
            },
            optimizers_config=qmodels.OptimizersConfigDiff(indexing_threshold=20000),
        )
        # Create payload indexes for common filter fields
        for field_name in ["source_type", "source_id", "version", "doc_title"]:
            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        logger.info("Qdrant collection '%s' created with indexes", COLLECTION_NAME)
    except Exception as exc:
        logger.warning("Failed to ensure Qdrant collection '%s': %s", COLLECTION_NAME, exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: initialize and clean up resources.

    Initializes cache, orchestrator, tools, and warm-up on startup.
    Drains in-flight requests and closes connections on shutdown.
    """
    global cache_manager, orchestrator, audit_logger, kb_manager
    setup_logging()
    logger.info("Starting RAG Proxy...")

    from proxy.app.shared.config import validate_auth_config

    validate_auth_config()
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

    # Run database migrations on startup
    try:
        from proxy.app.db.migrations import get_migration_manager

        migration_manager = get_migration_manager(
            db_path=USER_DB_PATH,
            neo4j_uri=NEO4J_URI if GRAPH_ENABLED else None,
            neo4j_user=NEO4J_USER if GRAPH_ENABLED else None,
            neo4j_password=NEO4J_PASSWORD if GRAPH_ENABLED else None,
        )
        await migration_manager.initialize()
        status = await migration_manager.get_status()
        if status["pending_count"] > 0:
            logger.info("Applying %d pending database migration(s)...", status["pending_count"])
            applied = await migration_manager.upgrade()
            logger.info("Applied %d migration(s) successfully", len(applied))
        else:
            logger.info("Database schema up to date (version %d)", status["current_version"])
    except Exception as e:
        logger.warning("Database migration check failed (non-blocking): %s", e)

    # Initialize cache
    if USE_REDIS and REDIS_URL:
        cache_manager = CacheManager(redis_url=REDIS_URL)
        await cache_manager.initialize()
        logger.info("Redis cache initialized")
    else:
        cache_manager = CacheManager(use_redis=False)
        logger.info("In-memory cache initialized (no Redis)")
    # Auto-initialize Qdrant collections on startup
    try:
        from proxy.app.core.retrieval import initialize_retrieval

        initialize_retrieval()
        # Ensure the default collection exists
        _ensure_qdrant_collection()
        logger.info("Retrieval subsystem initialized")
    except Exception as e:
        logger.warning("Retrieval initialization failed (degraded mode): %s", e)
    # Initialize Knowledge Base Manager
    try:
        from proxy.app.core.kb_manager import KnowledgeBaseManager
        from proxy.app.core.retrieval import qdrant_client as _qc

        kb_manager = KnowledgeBaseManager(db_path="data/knowledge_bases.db", qdrant_client=_qc)
        logger.info("Knowledge Base Manager initialized")
    except Exception as e:
        logger.warning("KB Manager initialization failed: %s", e)
    # Initialize LangGraph orchestrator (if enabled)
    if USE_LANGGRAPH:
        from proxy.app.core.orchestrator import get_orchestrator

        orchestrator = get_orchestrator()
        if orchestrator is not None:
            logger.info("LangGraph orchestrator initialized")
        else:
            logger.warning("LangGraph not available — agentic orchestration disabled")
    # Tool discovery from all providers
    if TOOLS_ENABLED:
        registry = get_enhanced_registry()

        # Declarative provider
        if os.path.isdir(TOOLS_DECLARATIVE_DIR):
            try:
                from proxy.app.tools.declarative import DeclarativeProvider

                declarative_provider: Any = DeclarativeProvider()
                discovered = await declarative_provider.discover()
                for tool in discovered:
                    registry.register(tool)
                logger.info("Startup: loaded %d tools from declarative provider", len(discovered))
            except Exception as e:
                logger.warning("Startup: declarative tool discovery failed: %s", e)

        # OpenAPI provider
        if TOOLS_OPENAPI_SPECS:
            try:
                from proxy.app.tools.openapi import OpenAPIProvider

                openapi_provider: Any = OpenAPIProvider()
                discovered = await openapi_provider.discover()
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

    # Start reindex scheduler (background task for stale document detection)
    try:
        from proxy.app.core.reindex_scheduler import start_reindex_scheduler
        from proxy.app.core.retrieval import qdrant_client as _rc

        if kb_manager is not None and _rc is not None:
            await start_reindex_scheduler(kb_manager, _rc)
    except Exception as e:
        logger.warning("Reindex scheduler start failed (non-blocking): %s", e)

    if GRACEFUL_SHUTDOWN_ENABLED:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_initiate_shutdown(s)))  # type: ignore[misc]
            except (NotImplementedError, RuntimeError, ValueError):
                logger.info(f"Signal handler for {sig.name} skipped (not supported in this environment)")
        logger.info("Graceful shutdown handlers registered")

    logger.info("RAG Proxy ready")
    yield
    # Cleanup
    global shutting_down
    shutting_down = True
    # Stop reindex scheduler
    try:
        from proxy.app.core.reindex_scheduler import stop_reindex_scheduler

        await stop_reindex_scheduler()
    except Exception as e:
        logger.warning("Reindex scheduler stop failed: %s", e)
    logger.info("Draining in-flight requests...")
    if _active_requests:
        done, pending = await asyncio.wait(_active_requests, timeout=SHUTDOWN_TIMEOUT)
        for task in pending:
            task.cancel()
        logger.info(f"Drained {len(done)} requests, cancelled {len(pending)}")
    if cache_manager:
        await cache_manager.close()
    logger.info("RAG Proxy shutdown")


async def _initiate_shutdown(sig: signal.Signals) -> None:
    """Initiate graceful shutdown on SIGTERM/SIGINT.

    Sets the shutting_down flag and cancels all active tasks
    after a brief delay to allow in-flight requests to complete.
    """
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
    other_messages: list[dict[str, Any]] | None = None,
    user_context: UserContext | None = None,
    top_k_override: int | None = None,
) -> tuple[str, str | list[dict[str, str]], bool, list[dict[str, Any]], dict[str, float]]:
    """Core RAG pipeline: search → filter → rerank → dedup → context → LLM.

    Steps:
        1. Cache check (Redis/in-memory)
        2. Qdrant hybrid search (dense + sparse)
        3. Row-level access control filtering
        4. Cross-encoder reranking
        5. Deduplication and version filtering
        6. Source citation building
        7. Retrieval quality evaluation (CRAG-style)
        8. Context assembly with token budget
        9. System prompt construction
        10. LLM call (stream or non-stream)

    Returns:
        Tuple of (response_text_or_context, messages_or_context, from_cache, sources).
        When stream=True, second element is the messages list for LLM streaming.
        When stream=False, first element is the final response text.

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
            return cached, "", True, [], {}

    # 2. Adaptive query routing (opt-in via config)
    from proxy.app.shared.config import ADAPTIVE_ROUTING_ENABLED

    if ADAPTIVE_ROUTING_ENABLED:
        from proxy.app.core.query_router import get_query_router

        router = get_query_router()
        complexity = router.classify(user_query)
        routing_params = router.get_retrieval_params(complexity)
        logger.debug(f"Query classified as '{complexity}': {user_query[:50]}...")

        if not routing_params["retrieve"]:
            # Simple query — no retrieval needed
            logger.info(f"Skipping retrieval for 'direct' query: {user_query[:50]}...")
            messages = [{"role": "system", "content": "You are a helpful assistant. Answer briefly and directly."}]
            if other_messages:
                for msg in other_messages:
                    if msg.get("role") != "system":
                        messages.append(msg)
            messages.append({"role": "user", "content": user_query})
            response_text = await non_stream_completion(messages, temperature=temperature, max_tokens=max_tokens)
            return response_text, "", False, [], {}

    # 3. Hybrid search
    try:
        search_results = hybrid_search(query=user_query, version=version, top_k=top_k_override or MAX_CHUNKS_RETRIEVAL)
    except Exception as e:
        logger.warning(f"Hybrid search failed (degraded mode): {e}")
        search_results = None
    sources: list[dict[str, Any]] = []
    chunks_for_eval: list[dict[str, Any]] = []
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
                f"chunks (user={user_context.username}, roles={user_context.roles})",
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

            if unique_chunks:
                for chunk, score in unique_chunks:
                    sources.append(
                        {
                            "chunk_id": compute_chunk_hash(chunk),
                            "source": chunk.get("source_type", "unknown"),
                            "title": chunk.get("title", "") or chunk.get("doc_title", ""),
                            "version": chunk.get("version", "unknown"),
                            "relevance": round(score, 4),
                            "text_preview": chunk.get("text", "")[:200],
                        },
                    )

            # 6. Retrieval quality evaluation (CRAG-style)
            chunks_for_eval = []
            for c, s in unique_chunks:
                c_copy = dict(c)
                c_copy["score"] = s
                chunks_for_eval.append(c_copy)
            confidence, action, quality_processed = retrieval_evaluator.evaluate_and_act(
                query=user_query,
                retrieved_chunks=chunks_for_eval,
            )
            logger.info(f"Retrieval quality: confidence={confidence:.3f}, action={action}")

            # CRAG-style corrective retrieval
            if action == "REWRITE":
                logger.info("CRAG: Triggering query rewrite due to low retrieval quality")
                # Rewrite query and re-retrieve
                rewritten_query = f"More specific: {user_query}"
                try:
                    additional_results = hybrid_search(
                        query=rewritten_query,
                        version=version,
                        top_k=top_k_override or MAX_CHUNKS_RETRIEVAL,
                    )
                    if additional_results:
                        # Merge with original results
                        search_results = list(search_results) + list(additional_results)
                        logger.info(f"CRAG: Added {len(additional_results)} results from rewritten query")
                except Exception as e:
                    logger.warning(f"CRAG rewrite failed: {e}")

            elif action == "EXPAND":
                logger.info("CRAG: Triggering context expansion")
                # Try broader search
                try:
                    expanded_results = hybrid_search(
                        query=user_query,
                        version=None,  # Remove version filter
                        top_k=(top_k_override or MAX_CHUNKS_RETRIEVAL) * 2,
                    )
                    if expanded_results:
                        search_results = list(search_results) + list(expanded_results)
                        logger.info(f"CRAG: Added {len(expanded_results)} expanded results")
                except Exception as e:
                    logger.warning(f"CRAG expansion failed: {e}")

            if action == "FALLBACK":
                context = ""
                chunks_metadata = []
            elif action == "EXPAND":
                # Expanded context budget for retrieval quality expansion
                context = build_context(unique_chunks, max_tokens=100_000)
            else:
                # 7. Smart token budget allocation
                available_tokens = 130_000  # approximate context window budget for LLM
                budget = token_optimizer.smart_token_budget(
                    available_tokens=available_tokens,
                    num_chunks=len(unique_chunks),
                )

                # 8. Context compression with budget
                raw_context = build_context(unique_chunks, max_tokens=budget["context_total"], include_metadata=True)

                if budget["context_total"] < len(raw_context) // 4:
                    context = token_optimizer.compress_context(
                        [c for c, _ in unique_chunks],
                        max_tokens=budget["context_total"],
                        strategy="hierarchical",
                    )
                else:
                    context = raw_context

                logger.info(
                    f"Token budget: system={budget['system_prompt']}, "
                    f"context={budget['context_total']}, response={budget['response']}",
                )

    # 9. Negative evidence check — refuse to hallucinate if retrieval is insufficient
    should_gen, reason = should_generate_answer(chunks_for_eval)
    if not should_gen:
        logger.info(f"Negative evidence: refusing to generate — {reason}")
        refusal = f"I don't have enough relevant information to answer this question reliably. {reason}"
        return refusal, "", False, sources, {}

    # 10. Build system prompt
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
    # Add the user query as the final message
    messages_for_llm.append({"role": "user", "content": user_query})

    # 11. LLM call
    if stream:
        return context, messages_for_llm, False, sources, {}
    try:
        response_text = await non_stream_completion(
            messages_for_llm,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as llm_err:
        logger.error("LLM completion failed: %s", llm_err, exc_info=True)
        response_text = (
            "Извините, сервис LLM временно недоступен. Пожалуйста, попробуйте позже или обратитесь к администратору."
        )
    if cache_manager and not force_refresh:
        await cache_manager.set(cache_key, response_text, ttl=DEFAULT_CACHE_TTL_SECONDS)

    # 11.5 Self-critique verification
    from proxy.app.core.confidence import self_critique_answer

    is_valid, critique_score, critique_reason = await self_critique_answer(
        query=user_query,
        context=context,
        answer=response_text,
    )
    if not is_valid:
        logger.warning(
            f"Self-critique failed: {critique_reason} (score={critique_score:.1f})",
        )  # Low confidence answers get
        # flagged in metadata

    # 12. Compute RAGAS evaluation scores
    ragas_scores: dict[str, float] = {}
    if chunks_for_eval:
        from proxy.app.core.ragas_eval import evaluate_rag_response

        context_texts = [c.get("text", "") for c in chunks_for_eval]
        ragas_scores = evaluate_rag_response(
            question=user_query,
            answer=response_text,
            contexts=context_texts,
        )
        logger.info(f"RAGAS scores: {ragas_scores}")

    return response_text, context, False, sources, ragas_scores


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAG Proxy for Gemma",
    description=(
        "OpenAI-compatible proxy with hybrid search, reranking, and Gemma LLM.\n\n"
        "## Features\n"
        "- **Chat Completions** — `/v1/chat/completions` (streaming + non-streaming)\n"
        "- **Hybrid Search** — dense + sparse RRF fusion in Qdrant\n"
        "- **Reranking** — cross-encoder (MiniLM-L-6-v2)\n"
        "- **Graph Expansion** — optional Neo4j entity traversal\n"
        "- **Auth** — JWT + RBAC (admin/expert/user/read-only)\n"
        "- **Tools** — agentic tool SDK with OpenAPI discovery\n"
        "- **Model Evolution** — LoRA/QLoRA fine-tuning pipeline\n\n"
        "## RAG-specific parameters\n"
        "- `rag_version` — request a specific document version\n"
        "- `rag_force_refresh` — bypass response cache\n"
        "- Response extensions: `rag_feedback_id`, `rag_confidence`, `rag_sources`"
    ),
    version="2.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "chat", "description": "Chat completions (OpenAI-compatible)"},
        {"name": "models", "description": "List available models"},
        {"name": "health", "description": "Health and readiness probes"},
        {"name": "auth", "description": "Authentication and authorization"},
        {"name": "feedback", "description": "Expert feedback submission"},
        {"name": "tools", "description": "Agentic tool discovery"},
        {"name": "admin", "description": "Model training and management"},
        {"name": "files", "description": "File upload/download (MinIO)"},
        {"name": "widget", "description": "Embeddable chat widget"},
        {"name": "metrics", "description": "Prometheus metrics"},
    ],
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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
    """Model metadata returned by the /v1/models endpoint."""

    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    """Response wrapper for the /v1/models endpoint."""

    object: str = "list"
    data: list[ModelInfo]


@app.get("/v1/models")
async def list_models() -> ModelsResponse:
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
    files_router,
    health_router,
    metrics_router,
    tools_router,
    widget_router,
)
from proxy.app.api.admin_feedback import router as admin_feedback_router  # noqa: E402
from proxy.app.api.admin_kb import router as admin_kb_router  # noqa: E402

app.include_router(metrics_router)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(files_router)
app.include_router(tools_router)
app.include_router(feedback_router)
app.include_router(widget_router)
app.include_router(admin_router)
app.include_router(admin_feedback_router)
app.include_router(admin_kb_router)

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
