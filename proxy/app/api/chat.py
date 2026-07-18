# proxy/app/api/chat.py
"""Chat completions endpoint — the core OpenAI-compatible RAG chat API.

Uses deferred imports from proxy.app.main for functions/globals that tests
mock at ``proxy.app.main.*`` paths (process_rag_query, cache_manager, etc.).
"""

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext, get_auth_context
from proxy.app.shared.security import InputValidator
from proxy.app.shared.tracing import add_event, get_current_span, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Pydantic models (re-exported from main.py for backward compatibility)
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """Single message in a chat conversation."""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with RAG extensions."""

    model: str
    messages: list[ChatMessage]
    temperature: float | None = 0.2
    top_p: float | None = 0.95
    max_tokens: int | None = 4096
    stream: bool | None = False
    # Non-standard RAG parameters
    rag_version: str | None = None
    rag_force_refresh: bool | None = False
    rag_skip_generation: bool | None = False
    rag_return_chunks: bool | None = False
    rag_top_k: int | None = None
    # Language override (FR-146): ISO 639-1 code. If set, overrides auto-detection.
    lang: str | None = None


class ChatCompletionResponseChoice(BaseModel):
    """Single choice in a chat completion response."""

    index: int
    message: ChatMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response with RAG extensions."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionResponseChoice]
    usage: dict[str, int] = Field(default={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    rag_feedback_id: str | None = None
    rag_confidence: float | None = None
    rag_sources: list[dict[str, Any]] | None = None
    ragas_scores: dict[str, float] | None = None
    rag_knowledge_status: str | None = None
    rag_source_count: int | None = None
    rag_clarification_needed: bool | None = None
    rag_clarifying_questions: list[str] | None = None


class ModelInfo(BaseModel):
    """Model metadata for the /v1/models endpoint."""

    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    """Response wrapper for the /v1/models endpoint."""

    object: str = "list"
    data: list[ModelInfo]


# ---------------------------------------------------------------------------
# SSE streaming helpers
# ---------------------------------------------------------------------------


class StreamOptimizer:
    """Optimizes SSE streaming for low time-to-first-token (TTFT).

    Sends an empty initial chunk immediately after receiving the request
    to reduce client-side latency. Buffers streamed content up to the
    configured chunk size before emitting, balancing latency and overhead.
    """

    def __init__(self, chunk_size: int | None = None, buffer_size: int | None = None):
        from proxy.app.shared.config import SSE_CHUNK_SIZE, STREAM_BUFFER_SIZE

        self.sse_chunk_size = chunk_size or SSE_CHUNK_SIZE
        self.stream_buffer_size = buffer_size or STREAM_BUFFER_SIZE
        self.initial_chunk_sent = False

    def initial_chunk(self) -> str:
        """Return the initial empty SSE chunk to reduce TTFT."""
        if self.initial_chunk_sent:
            return ""
        self.initial_chunk_sent = True
        return 'data: {"role":"initial_chunk"}\n\n'

    def format_chunk(self, chunk: dict[str, Any]) -> str:
        """Format a single chunk as an SSE event."""
        return f"data: {json.dumps(chunk)}\n\n"


def generate_request_id() -> str:
    """Generate a unique request ID for tracing and logging."""
    return f"rag_{int(time.time())}_{os.urandom(4).hex()}"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    user: UserContext = Depends(get_auth_context),  # noqa: B008
) -> ChatCompletionResponse | StreamingResponse:
    """Main chat endpoint (OpenAI compatible)."""
    # Deferred imports from main.py to preserve test mock compatibility
    import proxy.app.main as _main

    request_id = generate_request_id()
    start_time = time.time()

    raw_request.state.user_context = user

    # Trace: extract incoming context from headers (available for future instrumentation)
    _ = {k.lower(): v for k, v in raw_request.headers.items() if k.lower().startswith("trace")}

    # Input validation
    validated_model = InputValidator.validate_non_empty(request.model, max_len=256)
    if not validated_model:
        raise HTTPException(status_code=400, detail="Invalid model name")

    # Extract last user query
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

    # Trace: set attributes on any parent span (middleware-created)
    parent_span = get_current_span()
    if parent_span.is_recording():
        parent_span.set_attribute("rag.request_id", request_id)
        parent_span.set_attribute("rag.model", request.model)
        parent_span.set_attribute("rag.stream", bool(request.stream))
        parent_span.set_attribute("rag.query_length", len(user_query))

    # Extract version from query
    version = request.rag_version or _main.extract_version_from_query(user_query)  # type: ignore[attr-defined]

    # Log incoming request
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
        role_info = ",".join(user.roles) if user.is_authenticated else "anonymous"
        safe_query = InputValidator.sanitize_for_log(user_query[:100])
        logger.info(
            f"Request {request_id}: user={client_ip}, roles={role_info}, "
            f"query={safe_query}, version={version}, stream={request.stream}",
        )

    _main.request_tracker.start(request_id, metadata={"model": request.model, "client_ip": client_ip})

    # Federation: skip LLM generation, return chunks only
    if request.rag_skip_generation:
        rag_context, _, _, sources, _ = await _main.process_rag_query(
            user_query=user_query,
            version=version,
            force_refresh=request.rag_force_refresh or False,
            temperature=request.temperature or 0.2,
            max_tokens=request.max_tokens or 4096,
            stream=True,
            other_messages=other_messages,
            user_context=user,
            top_k_override=request.rag_top_k,
            lang=request.lang,
        )
        from proxy.app.core.confidence import should_generate_answer
        from proxy.app.core.knowledge_status import determine_knowledge_status

        chunks_for_status = sources or []
        chunks_with_score = [{"score": s.get("relevance", 0)} for s in chunks_for_status]
        should_gen, _ = should_generate_answer(chunks_with_score)
        knowledge_status = determine_knowledge_status(chunks_for_status, should_generate=should_gen)

        skip_response = ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=""),
                    finish_reason="stop",
                ),
            ],
            rag_sources=sources,
            rag_knowledge_status=knowledge_status.status,
            rag_source_count=knowledge_status.source_count,
        )
        duration_ms = (time.time() - start_time) * 1000
        _main.request_tracker.complete(request_id, status="success", tokens=0)
        if _main.audit_logger:
            _main.audit_logger.log_query(
                user_id=client_ip,
                query=user_query,
                response_preview="[skip_generation]",
                chunks=len(sources),
                duration_ms=duration_ms,
                tokens=0,
                client_ip=client_ip,
                result_status="success",
                metadata={"version": version, "model": request.model, "skip_generation": True},
            )
        return skip_response

    # LangGraph orchestrator path
    if _main.USE_LANGGRAPH and _main.orchestrator:  # type: ignore[attr-defined]
        try:
            orchestrator_response = await _main.orchestrator.ainvoke(
                {
                    "query": user_query,
                    "version": version,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "stream": request.stream,
                },
            )
        except Exception as orch_err:
            logger.error("LangGraph orchestrator failed: %s", orch_err, exc_info=True)
            if _main.audit_logger:
                _main.audit_logger.log_error(
                    error_type="OrchestratorError",
                    error_msg=str(orch_err),
                    stack_trace=None,
                    client_ip=client_ip,
                    endpoint="/v1/chat/completions",
                )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "orchestrator_unavailable",
                    "message": "Agentic pipeline temporarily unavailable. Please try again.",
                },
            ) from orch_err
        if request.stream:
            return StreamingResponse(orchestrator_response, media_type="text/event-stream")
        response_text = orchestrator_response["answer"]
        context = orchestrator_response.get("context", "")
        orchestrator_sources: list[dict[str, Any]] = []
        from proxy.app.core.context import compute_chunk_hash

        for chunk, score in orchestrator_response.get("reranked_chunks", []):
            orchestrator_sources.append(
                {
                    "chunk_id": compute_chunk_hash(chunk),
                    "source": chunk.get("source_type", "unknown"),
                    "title": chunk.get("title", "") or chunk.get("doc_title", ""),
                    "version": chunk.get("version", "unknown"),
                    "relevance": round(score, 4),
                    "text_preview": chunk.get("text", "")[:200],
                },
            )
        from proxy.app.core.confidence import compute_confidence
        from proxy.app.core.hitl import generate_feedback_id
        from proxy.app.core.knowledge_status import determine_knowledge_status

        feedback_id = generate_feedback_id()
        confidence = compute_confidence(
            query=user_query,
            context=context,
            answer=response_text,
            sources=orchestrator_sources,
        )
        knowledge_status = determine_knowledge_status(orchestrator_sources, should_generate=True)
        completion = ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=response_text),
                    finish_reason="stop",
                ),
            ],
            rag_feedback_id=feedback_id,
            rag_confidence=confidence.score,
            rag_sources=orchestrator_sources,
            rag_knowledge_status=knowledge_status.status,
            rag_source_count=knowledge_status.source_count,
        )
        duration_ms = (time.time() - start_time) * 1000
        _main.request_tracker.complete(request_id, status="success", tokens=len(response_text) // 4)
        if _main.audit_logger:
            _main.audit_logger.log_query(
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
            _main.audit_logger.log_trace(
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
        if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
            from proxy.app.core.hitl import log_interaction

            await log_interaction(
                request_id=request_id,
                user_query=user_query,
                context="[agentic]",
                response=response_text,
                metadata={"version": version, "model": request.model, "client_ip": client_ip},
            )
        return completion

    # Standard RAG pipeline
    if request.stream:

        async def event_generator() -> AsyncIterator[str]:
            accumulated_answer = []
            optimizer = StreamOptimizer()
            try:
                initial = optimizer.initial_chunk()
                if initial:
                    yield initial
                add_event("rag.pipeline.stream.start", {"query": user_query[:100], "version": version or "latest"})

                from proxy.app.shared.memory_manager import enrich_query_with_context, get_conversation

                stream_session_id = user.user_id if user.is_authenticated else client_ip
                stream_conversation = get_conversation(stream_session_id)
                enriched_stream_query = enrich_query_with_context(stream_conversation, user_query)

                with tracer.start_as_current_span("rag.pipeline.process") as pipeline_span:
                    if pipeline_span.is_recording():
                        pipeline_span.set_attribute("rag.query", user_query[:200])
                        pipeline_span.set_attribute("rag.version", version or "latest")
                        pipeline_span.set_attribute("rag.stream", True)
                    rag_context, messages_for_llm, _, sources, _ = await _main.process_rag_query(
                        user_query=enriched_stream_query,
                        version=version,
                        force_refresh=request.rag_force_refresh or False,
                        temperature=request.temperature or 0.2,
                        max_tokens=request.max_tokens or 4096,
                        stream=True,
                        other_messages=other_messages,
                        user_context=user,
                        top_k_override=request.rag_top_k,
                        lang=request.lang,
                    )
                from proxy.app.core.clarification import build_uncertainty_response, generate_clarifying_questions
                from proxy.app.core.confidence import should_generate_answer
                from proxy.app.core.knowledge_status import determine_knowledge_status
                from proxy.app.shared.config import CLARIFICATION_ENABLED

                chunks_for_status = sources or []
                chunks_with_score = [{"score": s.get("relevance", 0)} for s in chunks_for_status]
                should_gen, _ = should_generate_answer(chunks_with_score)
                knowledge_status = determine_knowledge_status(chunks_for_status, should_generate=should_gen)

                clarification_result = None
                if CLARIFICATION_ENABLED and knowledge_status.status in ("partial", "insufficient", "absent"):
                    clarification_result = generate_clarifying_questions(
                        query=user_query,
                        status=knowledge_status.status,
                        sources=chunks_for_status,
                        context=rag_context if isinstance(rag_context, str) else "",
                        lang=request.lang,
                    )

                conversation = stream_conversation
                if conversation.needs_summarization():
                    from proxy.app.shared.config import CONVERSATION_MAX_TURNS

                    conversation.summarize_older_turns(keep_recent=CONVERSATION_MAX_TURNS // 2)

                # If retrieval failed and we got a refusal, return structured uncertainty response
                if not messages_for_llm:
                    add_event("rag.pipeline.refusal", {"reason": "no_messages_for_llm"})
                    if rag_context and isinstance(rag_context, str):
                        refusal_text = rag_context
                    else:
                        refusal_text = build_uncertainty_response(
                            query=user_query,
                            status=knowledge_status.status,
                            sources=chunks_for_status,
                            clarification=clarification_result,
                        )
                    conversation.add_turn("user", user_query)
                    conversation.add_turn(
                        "assistant",
                        refusal_text,
                        metadata={"knowledge_status": knowledge_status.status},
                    )
                    yield optimizer.format_chunk(
                        {
                            "choices": [{"delta": {"content": refusal_text}, "index": 0, "finish_reason": "stop"}],
                        },
                    )
                    status_meta = {
                        "rag_knowledge_status": knowledge_status.status,
                        "rag_source_count": knowledge_status.source_count,
                    }
                    yield f"data: {json.dumps(status_meta)}\n\n"
                    if clarification_result and clarification_result.clarification_needed:
                        clar_meta = {
                            "rag_clarification_needed": True,
                            "rag_clarifying_questions": clarification_result.questions,
                        }
                        yield f"data: {json.dumps(clar_meta)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                assert isinstance(messages_for_llm, list), "messages_for_llm must be a list after RAG query"
                async for chunk in _main.stream_completion(  # type: ignore[attr-defined]
                    messages_for_llm,
                    request.temperature or 0.2,
                    request.max_tokens or 4096,
                ):
                    choices = chunk.get("choices", [])
                    delta_content = choices[0].get("delta", {}).get("content", "") if choices else ""
                    if delta_content:
                        accumulated_answer.append(delta_content)
                    yield optimizer.format_chunk(chunk)
                full_answer = "".join(accumulated_answer)
                from proxy.app.core.confidence import compute_confidence
                from proxy.app.core.hitl import generate_feedback_id

                feedback_id = generate_feedback_id()
                confidence = compute_confidence(
                    query=user_query,
                    context=rag_context,
                    answer=full_answer,
                    sources=chunks_for_status,
                )

                conversation.add_turn("user", user_query)
                conversation.add_turn(
                    "assistant",
                    full_answer,
                    metadata={
                        "knowledge_status": knowledge_status.status,
                        "confidence": confidence.score,
                    },
                )

                final_meta = {
                    "rag_feedback_id": feedback_id,
                    "rag_confidence": confidence.score,
                    "rag_knowledge_status": knowledge_status.status,
                    "rag_source_count": knowledge_status.source_count,
                }
                yield f"data: {json.dumps(final_meta)}\n\n"
                if clarification_result and clarification_result.clarification_needed:
                    clar_meta = {
                        "rag_clarification_needed": True,
                        "rag_clarifying_questions": clarification_result.questions,
                    }
                    yield f"data: {json.dumps(clar_meta)}\n\n"
                yield "data: [DONE]\n\n"
                duration_ms = (time.time() - start_time) * 1000
                _main.request_tracker.complete(request_id, status="success")
                if _main.audit_logger:
                    _main.audit_logger.log_query(
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
                if _main.audit_logger:
                    _main.audit_logger.log_error(
                        error_type="StreamingError",
                        error_msg=str(e),
                        stack_trace=None,
                        client_ip=client_ip,
                        endpoint="/v1/chat/completions",
                    )
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    # Non-streaming
    from proxy.app.shared.memory_manager import enrich_query_with_context, get_conversation

    session_id = user.user_id if user.is_authenticated else client_ip
    conversation = get_conversation(session_id)
    enriched_query = enrich_query_with_context(conversation, user_query)

    try:
        _rag_result = await _main.process_rag_query(
            user_query=enriched_query,
            version=version,
            force_refresh=request.rag_force_refresh or False,
            temperature=request.temperature or 0.2,
            max_tokens=request.max_tokens or 4096,
            stream=False,
            other_messages=other_messages,
            user_context=user,
            top_k_override=request.rag_top_k,
            lang=request.lang,
        )
    except Exception as rag_err:
        logger.error("Non-streaming RAG query failed: %s", rag_err, exc_info=True)
        if _main.audit_logger:
            _main.audit_logger.log_error(
                error_type="RAGQueryError",
                error_msg=str(rag_err),
                stack_trace=None,
                client_ip=client_ip,
                endpoint="/v1/chat/completions",
            )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "rag_unavailable",
                "message": "Knowledge system temporarily unavailable. Please try again later.",
            },
        ) from rag_err
    response_text = str(_rag_result[0])
    rag_ctx: str = str(_rag_result[1])
    from_cache = _rag_result[2]
    sources = _rag_result[3]
    ragas_scores = _rag_result[4]
    from proxy.app.core.clarification import build_uncertainty_response, generate_clarifying_questions
    from proxy.app.core.confidence import compute_confidence, should_generate_answer
    from proxy.app.core.hitl import generate_feedback_id
    from proxy.app.core.knowledge_status import determine_knowledge_status
    from proxy.app.shared.config import ALLOW_UNGROUNDED_GENERATION, CLARIFICATION_ENABLED, UNGROUNDED_NOTICE

    feedback_id = generate_feedback_id()
    confidence = compute_confidence(query=user_query, context=rag_ctx, answer=response_text, sources=sources)

    chunks_with_score = [{"score": s.get("relevance", 0)} for s in sources]
    should_gen, reason = should_generate_answer(chunks_with_score)
    knowledge_status = determine_knowledge_status(sources, should_generate=should_gen)

    clarification_result = None
    clarifying_questions = None
    if CLARIFICATION_ENABLED and knowledge_status.status in ("partial", "insufficient", "absent"):
        clarification_result = generate_clarifying_questions(
            query=user_query,
            status=knowledge_status.status,
            sources=sources,
            context=rag_ctx,
            lang=request.lang,
        )
        if clarification_result.clarification_needed:
            clarifying_questions = clarification_result.questions

    # Build structured uncertainty response when knowledge is insufficient
    final_response = response_text
    if knowledge_status.status == "absent" and not should_gen:
        if ALLOW_UNGROUNDED_GENERATION:
            # Keep LLM response but prepend notice about missing knowledge
            final_response = f"{UNGROUNDED_NOTICE}\n\n{response_text}"
        else:
            uncertainty_message = build_uncertainty_response(
                query=user_query,
                status=knowledge_status.status,
                sources=sources,
                clarification=clarification_result,
            )
            if uncertainty_message:
                final_response = uncertainty_message

    # Store conversation turn (conversation already loaded above for query enrichment)
    if conversation.needs_summarization():
        from proxy.app.shared.config import CONVERSATION_MAX_TURNS

        conversation.summarize_older_turns(keep_recent=CONVERSATION_MAX_TURNS // 2)
    conversation.add_turn("user", user_query)
    conversation.add_turn(
        "assistant",
        final_response,
        metadata={
            "knowledge_status": knowledge_status.status,
            "confidence": confidence.score,
        },
    )

    completion = ChatCompletionResponse(
        id=request_id,
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatCompletionResponseChoice(
                index=0,
                message=ChatMessage(role="assistant", content=final_response),
                finish_reason="stop",
            ),
        ],
        rag_feedback_id=feedback_id,
        rag_confidence=confidence.score,
        rag_sources=sources,
        ragas_scores=ragas_scores or None,
        rag_knowledge_status=knowledge_status.status,
        rag_source_count=knowledge_status.source_count,
        rag_clarification_needed=clarification_result.clarification_needed if clarification_result else None,
        rag_clarifying_questions=clarifying_questions,
    )
    duration_ms = (time.time() - start_time) * 1000
    _main.request_tracker.complete(request_id, status="success", tokens=len(response_text) // 4)
    if _main.audit_logger:
        _main.audit_logger.log_query(
            user_id=client_ip,
            query=user_query,
            response_preview=final_response[:200],
            chunks=len(sources),
            duration_ms=duration_ms,
            tokens=len(response_text) // 4,
            client_ip=client_ip,
            result_status="success",
            metadata={"version": version, "model": request.model, "from_cache": from_cache},
        )
        _main.audit_logger.log_trace(
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
    if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
        from proxy.app.core.hitl import log_interaction

        await log_interaction(
            request_id=request_id,
            user_query=user_query,
            context="[rag_context_omitted_for_logging]",
            response=final_response,
            metadata={"version": version, "model": request.model, "client_ip": client_ip, "from_cache": from_cache},
        )
    return completion
