# proxy/app/main.py
"""
OpenAI-совместимый прокси-сервер для RAG.
Поддерживает:
- /v1/chat/completions (stream + non-stream)
- /v1/models
- /v1/health
- /v1/auth/login (JWT token generation)
- /v1/auth/refresh (token refresh)

Использует:
- Qdrant для гибридного поиска
- Cross-encoder для реранкинга
- LangGraph (опционально) для агентной оркестрации
- Redis для кэширования эмбеддингов (опционально)
"""

import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import uvicorn
from app.access_control import (
    build_access_filter,
    filter_chunks,
)
from app.audit import AuditLogger, RequestTracker
from app.auth import (
    AUTH_ENABLED,
    UserContext,
    create_token,
    get_auth_context,
    verify_token,
)
from app.cache import CacheManager
from app.confidence import compute_confidence

# Импорт внутренних модулей
from app.config import (
    COMPRESSION_ENABLED,
    COMPRESSION_LEVEL,
    COMPRESSION_MIN_SIZE,
    CORS_ORIGINS,
    LLM_ENDPOINT,
    LLM_MODEL_NAME,
    LOG_DIR,
    LOG_REQUESTS,
    MAX_CHUNKS_AFTER_RERANK,
    MAX_CHUNKS_RETRIEVAL,
    RATE_LIMIT_BURST,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_PER_MINUTE,
    REDIS_URL,
    SSE_CHUNK_SIZE,
    STREAM_BUFFER_SIZE,
    USE_LANGGRAPH,
    USE_REDIS,
    WARMUP_ENABLED,
    WARMUP_ON_STARTUP,
)
from app.context_builder import build_context, deduplicate_chunks, extract_version_from_query
from app.hitl import generate_feedback_id, log_interaction
from app.logging_config import setup_logging
from app.metrics import init_metrics, metrics_endpoint
from app.middleware import add_cors_middleware, setup_all_middleware
from app.provider_adapter import non_stream_completion, stream_completion
from app.rate_limiter import add_rate_limit_middleware
from app.rerank import rerank_chunks
from app.retrieval import hybrid_search
from app.retrieval_evaluator import RetrievalEvaluator
from app.security import InputValidator
from app.token_optimizer import TokenOptimizer
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware

# Опциональные модули
if USE_LANGGRAPH:
    from app.orchestrator import get_orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("rag-proxy")

# Глобальные объекты (инициализируются при старте)
cache_manager = None
orchestrator = None
audit_logger = None
request_tracker = RequestTracker()
token_optimizer = TokenOptimizer()
retrieval_evaluator = RetrievalEvaluator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения: инициализация и очистка ресурсов."""
    global cache_manager, orchestrator, audit_logger
    setup_logging()
    logger.info("Starting RAG Proxy...")
    init_metrics()
    audit_logger = AuditLogger(log_dir=LOG_DIR)
    # Инициализация кэша
    if USE_REDIS and REDIS_URL:
        cache_manager = CacheManager(redis_url=REDIS_URL)
        await cache_manager.initialize()
        logger.info("Redis cache initialized")
    else:
        cache_manager = CacheManager(use_redis=False)
        logger.info("In-memory cache initialized (no Redis)")
    # Инициализация оркестратора LangGraph (если включён)
    if USE_LANGGRAPH:
        orchestrator = get_orchestrator()
        logger.info("LangGraph orchestrator initialized")
    # Model warm-up on startup (graceful degradation)
    if WARMUP_ENABLED and WARMUP_ON_STARTUP:
        try:
            from app.warmup import warmup_all
            warmup_result = await warmup_all()
            logger.info(f"Model warm-up completed: {warmup_result}")
        except Exception as e:
            logger.warning(f"Model warm-up failed (non-blocking): {e}")
    logger.info("RAG Proxy ready")
    yield
    # Очистка
    if cache_manager:
        await cache_manager.close()
    logger.info("RAG Proxy shutdown")


app = FastAPI(
    title="RAG Proxy for Gemma",
    description="OpenAI-compatible proxy with hybrid search, reranking, and Gemma LLM",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware setup (order matters: CORS > correlation > request-id > logging > rate-limit > compression)
add_cors_middleware(app, origins=CORS_ORIGINS)
setup_all_middleware(app, audit_logger=audit_logger)
if RATE_LIMIT_ENABLED:
    add_rate_limit_middleware(app, rate_per_minute=RATE_LIMIT_PER_MINUTE, burst=RATE_LIMIT_BURST)
if COMPRESSION_ENABLED:
    app.add_middleware(GZipMiddleware, minimum_size=COMPRESSION_MIN_SIZE, compresslevel=COMPRESSION_LEVEL)


# Metrics endpoint
@app.get("/metrics")
async def metrics():
    return metrics_endpoint()


# Pydantic модели для OpenAI API
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = 0.2
    top_p: float | None = 0.95
    max_tokens: int | None = 4096
    stream: bool | None = False
    # Нестандартные параметры для RAG
    rag_version: str | None = None  # конкретная версия документа
    rag_force_refresh: bool | None = False  # игнорировать кэш


class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionResponseChoice]
    usage: dict[str, int] = Field(default={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    rag_feedback_id: str | None = None
    rag_confidence: float | None = None
    rag_sources: list[dict] | None = None  # source chunks with metadata


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


# ===========================================================================
# Auth models
# ===========================================================================


class LoginRequest(BaseModel):
    username: str
    password: str
    expires_in_hours: int | None = 24


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user_id: str
    username: str
    roles: list[str]
    groups: list[str]


class RefreshRequest(BaseModel):
    token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    roles: list[str]
    groups: list[str]
    access_level: str
    is_admin: bool
    is_authenticated: bool


class FeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="rag_feedback_id from the response")
    rating: str = Field(..., pattern="^(positive|negative)$")
    correction: str | None = Field(None, description="Corrected answer text")
    comment: str | None = Field(None, description="Expert comment")


class FeedbackResponse(BaseModel):
    status: str
    message: str


# Вспомогательные функции


class StreamOptimizer:
    """Optimizes SSE streaming for low time-to-first-token (TTFT).

    Sends an empty initial chunk immediately after receiving the request
    to reduce client-side latency. Buffers streamed content up to the
    configured chunk size before emitting, balancing latency and overhead.
    """

    def __init__(self, chunk_size: int | None = None, buffer_size: int | None = None):
        self.sse_chunk_size = chunk_size or SSE_CHUNK_SIZE
        self.stream_buffer_size = buffer_size or STREAM_BUFFER_SIZE
        self.initial_chunk_sent = False

    def initial_chunk(self) -> str:
        """Return the initial empty SSE chunk to reduce TTFT."""
        if self.initial_chunk_sent:
            return ""
        self.initial_chunk_sent = True
        return 'data: {"role":"initial_chunk"}\n\n'

    def format_chunk(self, chunk: dict) -> str:
        """Format a single chunk as an SSE event."""
        return f"data: {json.dumps(chunk)}\n\n"


def generate_request_id() -> str:
    return f"rag_{int(time.time())}_{os.urandom(4).hex()}"


async def process_rag_query(
    user_query: str,
    version: str | None = None,
    force_refresh: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    stream: bool = False,
    other_messages: list[dict] = None,
    user_context: UserContext | None = None,
):
    """
    Основной RAG-пайплайн:
    1. Поиск в Qdrant (гибридный)
    2. Access control filtering
    3. Реранкинг
    4. Дедупликация и фильтрация версий
    5. Сборка контекста
    6. Вызов LLM
    """
    if user_context is None:
        user_context = UserContext.anonymous()

    # Build access filter for Qdrant (optional push-down filtering)
    access_filter = build_access_filter(user_context)

    # 1. Кэш: проверяем, есть ли уже ответ на этот запрос (опционально)
    cache_key = f"rag:{user_context.user_id}:{user_query}:{version or 'latest'}"
    if not force_refresh and cache_manager:
        cached = await cache_manager.get(cache_key)
        if cached:
            logger.info(f"Cache hit for query: {user_query[:50]}...")
            return cached, "", True, []

    # 2. Гибридный поиск
    search_results = hybrid_search(query=user_query, version=version, top_k=MAX_CHUNKS_RETRIEVAL)
    sources: list[dict] = []
    if not search_results:
        # Нет релевантных чанков -> ответ без контекста
        context = ""
        chunks_metadata = []
    else:
        chunks_texts = [hit.payload["text"] for hit in search_results]
        chunks_metadata = [hit.payload for hit in search_results]
        scores = [hit.score for hit in search_results]

        # 2.5. Row-level access control filtering (post-retrieval safety net)
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
            # Rebuild metadata and scores from filtered chunks
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

            # 3. Реранкинг
            reranked_indices = rerank_chunks(user_query, chunks_texts, top_k=MAX_CHUNKS_AFTER_RERANK)
            reranked_chunks = [(chunks_metadata[i], scores[i]) for i in reranked_indices]

            # 4. Дедупликация и версионирование
            unique_chunks = deduplicate_chunks(reranked_chunks)

            # 5. Build source citations from unique chunks
            from app.context_builder import compute_chunk_hash

            for chunk, score in unique_chunks:
                sources.append({
                    "chunk_id": compute_chunk_hash(chunk),
                    "source": chunk.get("source_type", "unknown"),
                    "title": chunk.get("title", "") or chunk.get("doc_title", ""),
                    "version": chunk.get("version", "unknown"),
                    "relevance": round(score, 4),
                    "text_preview": chunk.get("text", "")[:200],
                })

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

    # 9. Формируем системный промпт
    system_prompt = (
        "Ты – технический ассистент. Используй предоставленный контекст для ответа. "
        "Если контекст противоречив, укажи на противоречия. Если не знаешь, скажи честно.\n\n"
        f"Контекст:\n{context}"
    )
    messages_for_llm = [{"role": "system", "content": system_prompt}]
    # Добавляем историю диалога (кроме system сообщений, которые мы заменили)
    if other_messages:
        for msg in other_messages:
            if msg.get("role") != "system":
                messages_for_llm.append(msg)

    # 10. Вызов LLM
    if stream:
        return context, messages_for_llm, False, sources  # streaming handled separately
    else:
        response_text = await non_stream_completion(messages_for_llm, temperature=temperature, max_tokens=max_tokens)
        # Сохраняем в кэш
        if cache_manager and not force_refresh:
            await cache_manager.set(cache_key, response_text, ttl=3600)  # 1 час
        return response_text, context, False, sources


@app.get("/v1/health")
async def health():
    """Check proxy and dependency health."""
    status = {"status": "ok", "timestamp": datetime.now(UTC).isoformat(), "components": {}}
    try:
        from app.retrieval import qdrant_client

        qdrant_client.get_collections()
        status["components"]["qdrant"] = "ok"
    except Exception as e:
        status["components"]["qdrant"] = f"error: {str(e)}"
        status["status"] = "degraded"
    try:
        import requests

        resp = requests.get(f"{LLM_ENDPOINT}/health", timeout=2)
        if resp.status_code == 200:
            status["components"]["llm"] = "ok"
        else:
            status["components"]["llm"] = "unhealthy"
    except Exception as e:
        status["components"]["llm"] = f"error: {str(e)}"
        status["status"] = "degraded"
    return JSONResponse(status_code=200 if status["status"] == "ok" else 503, content=status)


@app.get("/v1/health/live")
async def health_live():
    """Liveness probe — returns 200 if the process is alive."""
    return JSONResponse(status_code=200, content={"status": "alive", "timestamp": datetime.now(UTC).isoformat()})


@app.get("/v1/health/ready")
async def health_ready():
    """Readiness probe — checks Qdrant and LLM connectivity."""
    status = {"status": "ready", "timestamp": datetime.now(UTC).isoformat(), "components": {}}
    try:
        from app.retrieval import qdrant_client

        qdrant_client.get_collections()
        status["components"]["qdrant"] = "ok"
    except Exception:
        status["components"]["qdrant"] = "unavailable"
        status["status"] = "not_ready"
    try:
        import requests

        resp = requests.get(f"{LLM_ENDPOINT}/health", timeout=2)
        if resp.status_code == 200:
            status["components"]["llm"] = "ok"
        else:
            status["components"]["llm"] = "unavailable"
            status["status"] = "not_ready"
    except Exception:
        status["components"]["llm"] = "unavailable"
        status["status"] = "not_ready"
    http_code = 200 if status["status"] == "ready" else 503
    return JSONResponse(status_code=http_code, content=status)


@app.get("/v1/models")
async def list_models():
    """Возвращает список доступных моделей."""
    models = [
        ModelInfo(id=LLM_MODEL_NAME, created=int(time.time())),
        ModelInfo(id="rag-proxy", created=int(time.time())),  # виртуальная модель для RAG
    ]
    return ModelsResponse(data=models)


# ===========================================================================
# Auth endpoints
# ===========================================================================

# Brute-force protection: in-memory rate limiter for login attempts
# In production, use Redis-backed rate limiter instead
_LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_LOGIN_COOLDOWN_SECONDS = 900  # 15 minutes after max attempts


def _check_login_rate_limit(identifier: str) -> None:
    """Check and update login rate limit for an identifier (username or IP).
    Raises HTTPException if rate limit exceeded."""
    now = time.time()
    if identifier in _LOGIN_ATTEMPTS:
        count, first_attempt = _LOGIN_ATTEMPTS[identifier]
        if now - first_attempt > _LOGIN_WINDOW_SECONDS:
            _LOGIN_ATTEMPTS[identifier] = (1, now)
            return
        if count >= _LOGIN_MAX_ATTEMPTS:
            if now - first_attempt < _LOGIN_COOLDOWN_SECONDS:
                wait = int(_LOGIN_COOLDOWN_SECONDS - (now - first_attempt))
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many login attempts. Try again in {wait} seconds.",
                )
            else:
                _LOGIN_ATTEMPTS[identifier] = (1, now)
                return
        _LOGIN_ATTEMPTS[identifier] = (count + 1, first_attempt)
    else:
        _LOGIN_ATTEMPTS[identifier] = (1, now)


@app.post("/v1/auth/login", response_model=LoginResponse)
async def auth_login(request: LoginRequest, raw_request: Request):
    """Generate a JWT token for the given credentials.

    In production, this would validate against Keycloak/LDAP.
    For air-gapped deployments, it uses a hardcoded credential store
    configurable via environment variables.
    """
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    rate_limit_key = f"{client_ip}:{request.username}"

    valid_users_json = os.getenv("AUTH_VALID_USERS", "{}")
    try:
        valid_users = json.loads(valid_users_json) if valid_users_json else {}
    except json.JSONDecodeError:
        logger.warning("AUTH_VALID_USERS is not valid JSON, using empty dict")
        valid_users = {}

    if request.username not in valid_users:
        _check_login_rate_limit(rate_limit_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_data = valid_users[request.username]
    if not secrets.compare_digest(user_data.get("password", ""), request.password):
        _check_login_rate_limit(rate_limit_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(
        user_id=user_data.get("user_id", request.username),
        username=request.username,
        roles=user_data.get("roles", ["viewer"]),
        groups=user_data.get("groups", []),
        access_level=user_data.get("access_level", "internal"),
        expires_in_hours=request.expires_in_hours or 24,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=(request.expires_in_hours or 24) * 3600,
        user_id=user_data.get("user_id", request.username),
        username=request.username,
        roles=user_data.get("roles", ["viewer"]),
        groups=user_data.get("groups", []),
    )


@app.post("/v1/auth/refresh", response_model=RefreshResponse)
async def auth_refresh(request: RefreshRequest):
    """Refresh an existing JWT token.

    Validates the current token and issues a new one with the same claims
    but a fresh expiration timestamp.
    """
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")

    try:
        user_ctx = verify_token(request.token)
    except HTTPException:
        raise

    new_token = create_token(
        user_id=user_ctx.user_id,
        username=user_ctx.username,
        roles=user_ctx.roles,
        groups=user_ctx.groups,
        access_level=user_ctx.access_level,
    )

    return RefreshResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=24 * 3600,
    )


@app.get("/v1/auth/me", response_model=UserInfoResponse)
async def auth_me(user: UserContext = Depends(get_auth_context)):
    """Return the current authenticated user's context."""
    return UserInfoResponse(
        user_id=user.user_id,
        username=user.username,
        roles=user.roles,
        groups=user.groups,
        access_level=user.access_level,
        is_admin=user.is_admin,
        is_authenticated=user.is_authenticated,
    )


# ===========================================================================
# Chat completions
# ===========================================================================


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    user: UserContext = Depends(get_auth_context),
):
    """Основной эндпоинт для чата (OpenAI совместимый)."""
    request_id = generate_request_id()
    start_time = time.time()

    # Store user context in request state for downstream components
    raw_request.state.user_context = user

    # Input validation
    validated_model = InputValidator.validate_non_empty(request.model, max_len=256)
    if not validated_model:
        raise HTTPException(status_code=400, detail="Invalid model name")

    # Извлекаем последний пользовательский запрос
    user_query = None
    other_messages = []
    for msg in request.messages:
        sanitized_content = InputValidator.validate_query(msg.content)
        if msg.role == "user" and user_query is None:
            user_query = sanitized_content
        else:
            sanitized_msg = msg.model_dump()
            sanitized_msg["content"] = sanitized_content
            other_messages.append(sanitized_msg)

    if not user_query:
        raise HTTPException(status_code=400, detail="No user message found")

    # Извлекаем версию из запроса
    version = request.rag_version or extract_version_from_query(user_query)

    # Логирование входящего запроса (опционально)
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    if LOG_REQUESTS:
        role_info = ",".join(user.roles) if user.is_authenticated else "anonymous"
        safe_query = InputValidator.sanitize_for_log(user_query[:100])
        logger.info(
            f"Request {request_id}: user={client_ip}, roles={role_info}, "
            f"query={safe_query}, version={version}, stream={request.stream}"
        )

    # Track request lifecycle
    request_tracker.start(request_id, metadata={"model": request.model, "client_ip": client_ip})

    # Используем оркестратор LangGraph, если включён
    if USE_LANGGRAPH and orchestrator:
        # Агентный пайплайн
        final_response = await orchestrator.ainvoke(
            {
                "query": user_query,
                "version": version,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "stream": request.stream,
            }
        )
        if request.stream:
            # Для стриминга нужно возвращать StreamingResponse из оркестратора
            return StreamingResponse(final_response, media_type="text/event-stream")
        else:
            response_text = final_response["answer"]
            context = final_response.get("context", "")
            # Build sources from orchestrator state
            orchestrator_sources: list[dict] = []
            from app.context_builder import compute_chunk_hash

            for chunk, score in final_response.get("reranked_chunks", []):
                orchestrator_sources.append({
                    "chunk_id": compute_chunk_hash(chunk),
                    "source": chunk.get("source_type", "unknown"),
                    "title": chunk.get("title", "") or chunk.get("doc_title", ""),
                    "version": chunk.get("version", "unknown"),
                    "relevance": round(score, 4),
                    "text_preview": chunk.get("text", "")[:200],
                })
            feedback_id = generate_feedback_id()
            confidence = compute_confidence(query=user_query, context=context, answer=response_text)
            # Формируем ответ в OpenAI формате
            completion = ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model=request.model,
                choices=[
                    ChatCompletionResponseChoice(
                        index=0, message=ChatMessage(role="assistant", content=response_text), finish_reason="stop"
                    )
                ],
                rag_feedback_id=feedback_id,
                rag_confidence=confidence.score,
                rag_sources=orchestrator_sources,
            )
            duration_ms = (time.time() - start_time) * 1000
            request_tracker.complete(request_id, status="success", tokens=len(response_text) // 4)
            # Audit log query
            if audit_logger:
                audit_logger.log_query(
                    user_id=client_ip,
                    query=user_query,
                    response_preview=response_text[:200],
                    chunks=len(orchestrator_sources),
                    duration_ms=duration_ms,
                    tokens=len(response_text) // 4,
                    client_ip=client_ip,
                    result_status="success",
                    metadata={"version": version, "model": request.model, "source": "langgraph"},
                )
                # Trace-level audit log
                audit_logger.log_trace(
                    request_id=request_id,
                    user_id=client_ip,
                    query=user_query,
                    chunks_count=len(orchestrator_sources),
                    rerank_scores=[s["relevance"] for s in orchestrator_sources],
                    duration_ms=duration_ms,
                    tokens=len(response_text) // 4,
                    confidence=confidence.score,
                    feedback_id=feedback_id,
                    client_ip=client_ip,
                )
            # Асинхронно логируем в HITL
            if LOG_REQUESTS:
                await log_interaction(
                    request_id=request_id,
                    user_query=user_query,
                    context="[agentic]",
                    response=response_text,
                    metadata={"version": version, "model": request.model, "client_ip": client_ip},
                )
            return completion

    # Стандартный RAG пайплайн
    if request.stream:
        # Потоковый режим
        async def event_generator():
            accumulated_answer = []
            optimizer = StreamOptimizer()
            try:
                # Send initial empty chunk to reduce TTFT
                initial = optimizer.initial_chunk()
                if initial:
                    yield initial
                # Выполняем поиск и подготовку контекста (синхронно, но в потоке)
                rag_context, messages_for_llm, _, _ = await process_rag_query(
                    user_query=user_query,
                    version=version,
                    force_refresh=request.rag_force_refresh,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=True,
                    other_messages=other_messages,
                    user_context=user,
                )
                # Передаём сообщения в LLM с потоковой генерацией
                async for chunk in stream_completion(messages_for_llm, request.temperature, request.max_tokens):
                    delta_content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta_content:
                        accumulated_answer.append(delta_content)
                    yield optimizer.format_chunk(chunk)
                # Yield final metadata chunk with confidence + feedback_id
                full_answer = "".join(accumulated_answer)
                feedback_id = generate_feedback_id()
                confidence = compute_confidence(query=user_query, context=rag_context, answer=full_answer)
                yield f"data: {json.dumps({'rag_feedback_id': feedback_id, 'rag_confidence': confidence.score})}\n\n"
                yield "data: [DONE]\n\n"
                duration_ms = (time.time() - start_time) * 1000
                request_tracker.complete(request_id, status="success")
                if audit_logger:
                    audit_logger.log_query(
                        user_id=client_ip,
                        query=user_query,
                        response_preview="[streaming]",
                        chunks=0,
                        duration_ms=duration_ms,
                        tokens=0,
                        client_ip=client_ip,
                        result_status="success",
                        metadata={"version": version, "model": request.model},
                    )
            except Exception as e:
                logger.error(f"Streaming error: {e}", exc_info=True)
                if audit_logger:
                    audit_logger.log_error(
                        error_type="StreamingError",
                        error_msg=str(e),
                        stack_trace=None,
                        client_ip=client_ip,
                        endpoint="/v1/chat/completions",
                    )
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # Non-streaming
        response_text, rag_context, from_cache, sources = await process_rag_query(
            user_query=user_query,
            version=version,
            force_refresh=request.rag_force_refresh,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
            other_messages=other_messages,
            user_context=user,
        )
        feedback_id = generate_feedback_id()
        confidence = compute_confidence(query=user_query, context=rag_context, answer=response_text)
        completion = ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0, message=ChatMessage(role="assistant", content=response_text), finish_reason="stop"
                )
            ],
            rag_feedback_id=feedback_id,
            rag_confidence=confidence.score,
            rag_sources=sources,
        )
        duration_ms = (time.time() - start_time) * 1000
        request_tracker.complete(request_id, status="success", tokens=len(response_text) // 4)
        # Audit log query
        if audit_logger:
            audit_logger.log_query(
                user_id=client_ip,
                query=user_query,
                response_preview=response_text[:200],
                chunks=len(sources),
                duration_ms=duration_ms,
                tokens=len(response_text) // 4,
                client_ip=client_ip,
                result_status="success",
                metadata={"version": version, "model": request.model, "from_cache": from_cache},
            )
            # Trace-level audit log
            audit_logger.log_trace(
                request_id=request_id,
                user_id=client_ip,
                query=user_query,
                chunks_count=len(sources),
                rerank_scores=[s["relevance"] for s in sources],
                duration_ms=duration_ms,
                tokens=len(response_text) // 4,
                confidence=confidence.score,
                feedback_id=feedback_id,
                client_ip=client_ip,
            )
        # Логирование взаимодействия
        if LOG_REQUESTS:
            await log_interaction(
                request_id=request_id,
                user_query=user_query,
                context="[rag_context_omitted_for_logging]",
                response=response_text,
                metadata={"version": version, "model": request.model, "client_ip": client_ip, "from_cache": from_cache},
            )
        return completion


@app.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest, raw_request: Request):
    """Submit feedback on a RAG response."""
    from app.hitl import FeedbackType, get_logger

    hlog = get_logger()

    feedback_type = FeedbackType.POSITIVE if request.rating == "positive" else FeedbackType.NEGATIVE

    try:
        hlog.log_feedback(
            request_id=request.feedback_id,
            feedback_type=feedback_type,
            comment=request.comment or "",
            corrected_response=request.correction,
        )

        from app.config import ENRICHMENT_ENABLED

        if ENRICHMENT_ENABLED and (request.rating == "positive" or request.correction):
            try:
                from app.enricher import enrich_from_feedback

                await enrich_from_feedback(request)
            except Exception as e:
                logger.error(f"Enrichment failed (non-blocking): {e}")

        return FeedbackResponse(status="ok", message="Feedback recorded")
    except Exception as e:
        logger.error(f"Failed to record feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {e}") from e


# ===========================================================================
# Admin warm-up endpoint
# ===========================================================================


@app.post("/v1/admin/warmup")
async def admin_warmup(user: UserContext = Depends(get_auth_context)):
    """Trigger model warm-up (admin only).

    Runs embedder, reranker, and LLM warmup to pre-load models into memory.
    Uses graceful degradation: each component failure is logged, not fatal.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if not WARMUP_ENABLED:
        return JSONResponse(status_code=200, content={"status": "disabled", "message": "Warm-up is disabled"})
    try:
        from app.warmup import warmup_all
        result = await warmup_all()
        return JSONResponse(status_code=200, content={"status": "ok", "results": result})
    except Exception as e:
        logger.error(f"Warm-up failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        workers=1,  # Для стриминга и кэша лучше 1 воркер, или использовать Redis
    )
