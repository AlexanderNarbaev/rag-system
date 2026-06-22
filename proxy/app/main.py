# proxy/app/main.py
"""
OpenAI-совместимый прокси-сервер для RAG с Gemma.
Поддерживает:
- /v1/chat/completions (stream + non-stream)
- /v1/models
- /v1/health

Использует:
- Qdrant для гибридного поиска
- Cross-encoder для реранкинга
- LangGraph (опционально) для агентной оркестрации
- Redis для кэширования эмбеддингов (опционально)
"""
import os
import json
import logging
import time
from typing import List, Optional, Dict, Any, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

# Импорт внутренних модулей
from app.config import (
    QDRANT_HOST, QDRANT_PORT, COLLECTION_NAME,
    EMBEDDER_MODEL, RERANKER_MODEL, LLM_ENDPOINT, LLM_MODEL_NAME,
    MAX_CHUNKS_RETRIEVAL, MAX_CHUNKS_AFTER_RERANK,
    REDIS_URL, USE_REDIS, USE_LANGGRAPH, LOG_REQUESTS, LOG_DIR,
    METRICS_ENABLED, RATE_LIMIT_ENABLED, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_BURST,
    LOG_FORMAT, CORS_ORIGINS,
)
from app.retrieval import hybrid_search
from app.rerank import rerank_chunks
from app.context_builder import build_context, deduplicate_chunks, extract_version_from_query
from app.token_optimizer import TokenOptimizer
from app.retrieval_evaluator import RetrievalEvaluator
from app.llm_router import stream_completion, non_stream_completion
from app.cache import CacheManager
from app.hitl import log_interaction
from app.metrics import metrics_endpoint, init_metrics
from app.middleware import setup_all_middleware, add_cors_middleware
from app.rate_limiter import add_rate_limit_middleware
from app.logging_config import setup_logging

# Опциональные модули
if USE_LANGGRAPH:
    from app.orchestrator import get_orchestrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("rag-proxy")

# Глобальные объекты (инициализируются при старте)
cache_manager = None
orchestrator = None
token_optimizer = TokenOptimizer()
retrieval_evaluator = RetrievalEvaluator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения: инициализация и очистка ресурсов."""
    global cache_manager, orchestrator
    setup_logging()
    logger.info("Starting RAG Proxy...")
    init_metrics()
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
    lifespan=lifespan
)

# Middleware setup (order matters: CORS > correlation > request-id > logging > rate-limit)
add_cors_middleware(app, origins=CORS_ORIGINS)
setup_all_middleware(app)
if RATE_LIMIT_ENABLED:
    add_rate_limit_middleware(app, rate_per_minute=RATE_LIMIT_PER_MINUTE, burst=RATE_LIMIT_BURST)


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
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.2
    top_p: Optional[float] = 0.95
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    # Нестандартные параметры для RAG
    rag_version: Optional[str] = None  # конкретная версия документа
    rag_force_refresh: Optional[bool] = False  # игнорировать кэш


class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Dict[str, int] = Field(default={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


# Вспомогательные функции
def generate_request_id() -> str:
    return f"rag_{int(time.time())}_{os.urandom(4).hex()}"


async def process_rag_query(
    user_query: str,
    version: Optional[str] = None,
    force_refresh: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    stream: bool = False,
    other_messages: List[Dict] = None
):
    """
    Основной RAG-пайплайн:
    1. Поиск в Qdrant (гибридный)
    2. Реранкинг
    3. Дедупликация и фильтрация версий
    4. Сборка контекста
    5. Вызов LLM
    """
    # 1. Кэш: проверяем, есть ли уже ответ на этот запрос (опционально)
    cache_key = f"rag:{user_query}:{version or 'latest'}"
    if not force_refresh and cache_manager:
        cached = await cache_manager.get(cache_key)
        if cached:
            logger.info(f"Cache hit for query: {user_query[:50]}...")
            return cached, True

    # 2. Гибридный поиск
    search_results = hybrid_search(
        query=user_query,
        version=version,
        top_k=MAX_CHUNKS_RETRIEVAL
    )
    if not search_results:
        # Нет релевантных чанков -> ответ без контекста
        context = ""
        chunks_metadata = []
    else:
        chunks_texts = [hit.payload["text"] for hit in search_results]
        chunks_metadata = [hit.payload for hit in search_results]
        scores = [hit.score for hit in search_results]

        # 3. Реранкинг
        reranked_indices = rerank_chunks(user_query, chunks_texts, top_k=MAX_CHUNKS_AFTER_RERANK)
        reranked_chunks = [(chunks_metadata[i], scores[i]) for i in reranked_indices]

        # 4. Дедупликация и версионирование
        unique_chunks = deduplicate_chunks(reranked_chunks)

        # 5. Retrieval quality evaluation (CRAG-style)
        chunks_for_eval = []
        for c, s in unique_chunks:
            c_copy = dict(c)
            c_copy["score"] = s
            chunks_for_eval.append(c_copy)
        confidence, action, quality_processed = retrieval_evaluator.evaluate_and_act(
            query=user_query,
            retrieved_chunks=chunks_for_eval
        )
        logger.info(f"Retrieval quality: confidence={confidence:.3f}, action={action}")

        if action == "FALLBACK":
            context = ""
            chunks_metadata = []
        elif action == "EXPAND":
            context = build_context(unique_chunks, max_tokens=100000)
        else:
            # 6. Smart token budget allocation
            available_tokens = 130000
            budget = token_optimizer.smart_token_budget(
                available_tokens=available_tokens,
                num_chunks=len(unique_chunks)
            )

            # 7. Context compression with budget
            raw_context = build_context(
                unique_chunks,
                max_tokens=budget["context_total"],
                include_metadata=True
            )

            if budget["context_total"] < len(raw_context) // 4:
                context = token_optimizer.compress_context(
                    [c for c, _ in unique_chunks],
                    max_tokens=budget["context_total"],
                    strategy="hierarchical"
                )
            else:
                context = raw_context

            logger.info(
                f"Token budget: system={budget['system_prompt']}, "
                f"context={budget['context_total']}, response={budget['response']}"
            )

    # 6. Формируем системный промпт
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

    # 7. Вызов LLM
    if stream:
        return context, messages_for_llm  # потоковая генерация обрабатывается отдельно
    else:
        response_text = await non_stream_completion(messages_for_llm, temperature=temperature, max_tokens=max_tokens)
        # Сохраняем в кэш
        if cache_manager and not force_refresh:
            await cache_manager.set(cache_key, response_text, ttl=3600)  # 1 час
        return response_text, False


@app.get("/v1/health")
async def health():
    """Проверка работоспособности прокси и зависимостей."""
    status = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {}
    }
    # Проверка Qdrant (опционально)
    try:
        from app.retrieval import qdrant_client
        qdrant_client.get_collections()
        status["components"]["qdrant"] = "ok"
    except Exception as e:
        status["components"]["qdrant"] = f"error: {str(e)}"
        status["status"] = "degraded"
    # Проверка LLM эндпоинта
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


@app.get("/v1/models")
async def list_models():
    """Возвращает список доступных моделей."""
    models = [
        ModelInfo(id=LLM_MODEL_NAME, created=int(time.time())),
        ModelInfo(id="rag-proxy", created=int(time.time()))  # виртуальная модель для RAG
    ]
    return ModelsResponse(data=models)


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, raw_request: Request):
    """Основной эндпоинт для чата (OpenAI совместимый)."""
    request_id = generate_request_id()
    start_time = time.time()
    
    # Извлекаем последний пользовательский запрос
    user_query = None
    other_messages = []
    for msg in request.messages:
        if msg.role == "user" and user_query is None:
            user_query = msg.content
        else:
            other_messages.append(msg.model_dump())
    
    if not user_query:
        raise HTTPException(status_code=400, detail="No user message found")
    
    # Извлекаем версию из запроса
    version = request.rag_version or extract_version_from_query(user_query)
    
    # Логирование входящего запроса (опционально)
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    if LOG_REQUESTS:
        logger.info(f"Request {request_id}: user={client_ip}, query={user_query[:100]}, version={version}, stream={request.stream}")
    
    # Используем оркестратор LangGraph, если включён
    if USE_LANGGRAPH and orchestrator:
        # Агентный пайплайн
        final_response = await orchestrator.ainvoke({
            "query": user_query,
            "version": version,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": request.stream
        })
        if request.stream:
            # Для стриминга нужно возвращать StreamingResponse из оркестратора
            return StreamingResponse(final_response, media_type="text/event-stream")
        else:
            response_text = final_response["answer"]
            # Формируем ответ в OpenAI формате
            completion = ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model=request.model,
                choices=[ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=response_text),
                    finish_reason="stop"
                )]
            )
            # Асинхронно логируем в HITL
            if LOG_REQUESTS:
                await log_interaction(
                    request_id=request_id,
                    user_query=user_query,
                    context="[agentic]",
                    response=response_text,
                    metadata={"version": version, "model": request.model, "client_ip": client_ip}
                )
            return completion
    
    # Стандартный RAG пайплайн
    if request.stream:
        # Потоковый режим
        async def event_generator():
            try:
                # Выполняем поиск и подготовку контекста (синхронно, но в потоке)
                context, messages_for_llm = await process_rag_query(
                    user_query=user_query,
                    version=version,
                    force_refresh=request.rag_force_refresh,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=True,
                    other_messages=other_messages
                )
                # Передаём сообщения в LLM с потоковой генерацией
                async for chunk in stream_completion(messages_for_llm, request.temperature, request.max_tokens):
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
                # Логирование после завершения (можно сохранить собранный ответ, но в стриминге сложно)
            except Exception as e:
                logger.error(f"Streaming error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # Non-streaming
        response_text, from_cache = await process_rag_query(
            user_query=user_query,
            version=version,
            force_refresh=request.rag_force_refresh,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
            other_messages=other_messages
        )
        completion = ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=request.model,
            choices=[ChatCompletionResponseChoice(
                index=0,
                message=ChatMessage(role="assistant", content=response_text),
                finish_reason="stop"
            )]
        )
        # Логирование взаимодействия
        if LOG_REQUESTS:
            await log_interaction(
                request_id=request_id,
                user_query=user_query,
                context="[rag_context_omitted_for_logging]",
                response=response_text,
                metadata={"version": version, "model": request.model, "client_ip": client_ip, "from_cache": from_cache}
            )
        return completion


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        workers=1  # Для стриминга и кэша лучше 1 воркер, или использовать Redis
    )