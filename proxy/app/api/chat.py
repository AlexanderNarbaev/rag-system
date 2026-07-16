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

logger = logging.getLogger ("rag-proxy")

router = APIRouter (tags = ["chat"])


# ---------------------------------------------------------------------------
# Pydantic models (re-exported from main.py for backward compatibility)
# ---------------------------------------------------------------------------


class ChatMessage (BaseModel):
  """Single message in a chat conversation."""

  role: str
  content: str


class ChatCompletionRequest (BaseModel):
  """OpenAI-compatible chat completion request with RAG extensions."""

  model: str
  messages: list [ChatMessage]
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


class ChatCompletionResponseChoice (BaseModel):
  """Single choice in a chat completion response."""

  index: int
  message: ChatMessage
  finish_reason: str | None = "stop"


class ChatCompletionResponse (BaseModel):
  """OpenAI-compatible chat completion response with RAG extensions."""

  id: str
  object: str = "chat.completion"
  created: int
  model: str
  choices: list [ChatCompletionResponseChoice]
  usage: dict [str, int] = Field (default = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
  rag_feedback_id: str | None = None
  rag_confidence: float | None = None
  rag_sources: list [dict [str, Any]] | None = None
  ragas_scores: dict [str, float] | None = None


class ModelInfo (BaseModel):
  """Model metadata for the /v1/models endpoint."""

  id: str
  object: str = "model"
  created: int
  owned_by: str = "local"


class ModelsResponse (BaseModel):
  """Response wrapper for the /v1/models endpoint."""

  object: str = "list"
  data: list [ModelInfo]


# ---------------------------------------------------------------------------
# SSE streaming helpers
# ---------------------------------------------------------------------------


class StreamOptimizer:
  """Optimizes SSE streaming for low time-to-first-token (TTFT).

  Sends an empty initial chunk immediately after receiving the request
  to reduce client-side latency. Buffers streamed content up to the
  configured chunk size before emitting, balancing latency and overhead.
  """

  def __init__ (self, chunk_size: int | None = None, buffer_size: int | None = None):
    from proxy.app.shared.config import SSE_CHUNK_SIZE, STREAM_BUFFER_SIZE

    self.sse_chunk_size = chunk_size or SSE_CHUNK_SIZE
    self.stream_buffer_size = buffer_size or STREAM_BUFFER_SIZE
    self.initial_chunk_sent = False

  def initial_chunk (self) -> str:
    """Return the initial empty SSE chunk to reduce TTFT."""
    if self.initial_chunk_sent:
      return ""
    self.initial_chunk_sent = True
    return 'data: {"role":"initial_chunk"}\n\n'

  def format_chunk (self, chunk: dict [str, Any]) -> str:
    """Format a single chunk as an SSE event."""
    return f"data: {json.dumps (chunk)}\n\n"


def generate_request_id () -> str:
  """Generate a unique request ID for tracing and logging."""
  return f"rag_{int (time.time ())}_{os.urandom (4).hex ()}"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post ("/v1/chat/completions", response_model = None)
async def chat_completions (
    request: ChatCompletionRequest, raw_request: Request, user: UserContext = Depends (get_auth_context),  # noqa: B008
) -> ChatCompletionResponse | StreamingResponse:
  """Main chat endpoint (OpenAI compatible)."""
  # Deferred imports from main.py to preserve test mock compatibility
  import proxy.app.main as _main

  request_id = generate_request_id ()
  start_time = time.time ()

  raw_request.state.user_context = user

  # Input validation
  validated_model = InputValidator.validate_non_empty (request.model, max_len = 256)
  if not validated_model:
    raise HTTPException (status_code = 400, detail = "Invalid model name")

  # Extract last user query
  user_query = None
  other_messages = []
  for msg in request.messages:
    sanitized_content = InputValidator.validate_query (msg.content)
    if msg.role == "user" and user_query is None:
      user_query = sanitized_content
    else:
      sanitized_msg = msg.model_dump ()
      sanitized_msg ["content"] = sanitized_content
      other_messages.append (sanitized_msg)

  if not user_query:
    raise HTTPException (status_code = 400, detail = "No user message found")

  # Extract version from query
  version = request.rag_version or _main.extract_version_from_query (user_query)  # type: ignore[attr-defined]

  # Log incoming request
  client_ip = raw_request.client.host if raw_request.client else "unknown"
  if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
    role_info = ",".join (user.roles) if user.is_authenticated else "anonymous"
    safe_query = InputValidator.sanitize_for_log (user_query [:100])
    logger.info (f"Request {request_id}: user={client_ip}, roles={role_info}, "
                 f"query={safe_query}, version={version}, stream={request.stream}")

  _main.request_tracker.start (request_id, metadata = {"model": request.model, "client_ip": client_ip})

  # Federation: skip LLM generation, return chunks only
  if request.rag_skip_generation:
    rag_context, _, _, sources, _ = await _main.process_rag_query (user_query = user_query, version = version,
        force_refresh = request.rag_force_refresh or False, temperature = request.temperature or 0.2,
        max_tokens = request.max_tokens or 4096, stream = True, other_messages = other_messages, user_context = user,
        top_k_override = request.rag_top_k, )
    skip_response = ChatCompletionResponse (id = request_id, created = int (time.time ()), model = request.model,
        choices = [
            ChatCompletionResponseChoice (index = 0, message = ChatMessage (role = "assistant", content = ""),
                finish_reason = "stop")
        ], rag_sources = sources, )
    duration_ms = (time.time () - start_time) * 1000
    _main.request_tracker.complete (request_id, status = "success", tokens = 0)
    if _main.audit_logger:
      _main.audit_logger.log_query (user_id = client_ip, query = user_query, response_preview = "[skip_generation]",
          chunks = len (sources), duration_ms = duration_ms, tokens = 0, client_ip = client_ip,
          result_status = "success", metadata = {"version": version, "model": request.model, "skip_generation": True}, )
    return skip_response

  # LangGraph orchestrator path
  if _main.USE_LANGGRAPH and _main.orchestrator:  # type: ignore[attr-defined]
    try:
      final_response = await _main.orchestrator.ainvoke ({
          "query": user_query, "version": version, "temperature": request.temperature, "max_tokens": request.max_tokens,
          "stream": request.stream,
      })
    except Exception as orch_err:
      logger.error ("LangGraph orchestrator failed: %s", orch_err, exc_info = True)
      if _main.audit_logger:
        _main.audit_logger.log_error (error_type = "OrchestratorError", error_msg = str (orch_err),
            stack_trace = None, client_ip = client_ip, endpoint = "/v1/chat/completions", )
      raise HTTPException (status_code = 503,
          detail = {"error": "orchestrator_unavailable",
              "message": "Agentic pipeline temporarily unavailable. Please try again.", }) from orch_err
    if request.stream:
      return StreamingResponse (final_response, media_type = "text/event-stream")
    else:
      response_text = final_response ["answer"]
      context = final_response.get ("context", "")
      orchestrator_sources: list [dict [str, Any]] = []
      from proxy.app.core.context import compute_chunk_hash

      for chunk, score in final_response.get ("reranked_chunks", []):
        orchestrator_sources.append ({
            "chunk_id": compute_chunk_hash (chunk), "source": chunk.get ("source_type", "unknown"),
            "title": chunk.get ("title", "") or chunk.get ("doc_title", ""),
            "version": chunk.get ("version", "unknown"), "relevance": round (score, 4),
            "text_preview": chunk.get ("text", "") [:200],
        })
      from proxy.app.core.confidence import compute_confidence
      from proxy.app.core.hitl import generate_feedback_id

      feedback_id = generate_feedback_id ()
      confidence = compute_confidence (query = user_query, context = context, answer = response_text)
      completion = ChatCompletionResponse (id = request_id, created = int (time.time ()), model = request.model,
          choices = [
              ChatCompletionResponseChoice (index = 0,
                  message = ChatMessage (role = "assistant", content = response_text), finish_reason = "stop")
          ], rag_feedback_id = feedback_id, rag_confidence = confidence.score, rag_sources = orchestrator_sources, )
      duration_ms = (time.time () - start_time) * 1000
      _main.request_tracker.complete (request_id, status = "success", tokens = len (response_text) // 4)
      if _main.audit_logger:
        _main.audit_logger.log_query (user_id = client_ip, query = user_query, response_preview = response_text [:200],
            chunks = len (orchestrator_sources), duration_ms = duration_ms, tokens = len (response_text) // 4,
            client_ip = client_ip, result_status = "success",
            metadata = {"version": version, "model": request.model, "source": "langgraph"}, )
        _main.audit_logger.log_trace (request_id = request_id, user_id = client_ip, query = user_query,
            chunks_count = len (orchestrator_sources), rerank_scores = [s ["relevance"] for s in orchestrator_sources],
            duration_ms = duration_ms, tokens = len (response_text) // 4, confidence = confidence.score,
            feedback_id = feedback_id, client_ip = client_ip, )
      if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
        from proxy.app.core.hitl import log_interaction

        await log_interaction (request_id = request_id, user_query = user_query, context = "[agentic]",
            response = response_text, metadata = {"version": version, "model": request.model, "client_ip": client_ip}, )
      return completion

  # Standard RAG pipeline
  if request.stream:

    async def event_generator () -> AsyncIterator [str]:
      accumulated_answer = []
      optimizer = StreamOptimizer ()
      try:
        initial = optimizer.initial_chunk ()
        if initial:
          yield initial
        rag_context, messages_for_llm, _, _, _ = await _main.process_rag_query (user_query = user_query,
            version = version, force_refresh = request.rag_force_refresh or False,
            temperature = request.temperature or 0.2, max_tokens = request.max_tokens or 4096, stream = True,
            other_messages = other_messages, user_context = user, top_k_override = request.rag_top_k, )
        # If retrieval failed and we got a refusal (empty messages list), return rag_context directly
        if not messages_for_llm:
          refusal_text = rag_context if rag_context else (
            "I don't have enough relevant information to answer this question reliably."
          )
          yield optimizer.format_chunk ({
              "choices": [{"delta": {"content": refusal_text}, "index": 0, "finish_reason": "stop"}],
          })
          yield "data: [DONE]\n\n"
          return
        assert isinstance (messages_for_llm, list), "messages_for_llm must be a list after RAG query"
        async for chunk in _main.stream_completion (  # type: ignore[attr-defined]
            messages_for_llm, request.temperature or 0.2, request.max_tokens or 4096):
          choices = chunk.get ("choices", [])
          delta_content = choices [0].get ("delta", {}).get ("content", "") if choices else ""
          if delta_content:
            accumulated_answer.append (delta_content)
          yield optimizer.format_chunk (chunk)
        full_answer = "".join (accumulated_answer)
        from proxy.app.core.confidence import compute_confidence
        from proxy.app.core.hitl import generate_feedback_id

        feedback_id = generate_feedback_id ()
        confidence = compute_confidence (query = user_query, context = rag_context, answer = full_answer)
        yield f"data: {json.dumps ({'rag_feedback_id': feedback_id, 'rag_confidence': confidence.score})}\n\n"
        yield "data: [DONE]\n\n"
        duration_ms = (time.time () - start_time) * 1000
        _main.request_tracker.complete (request_id, status = "success")
        if _main.audit_logger:
          _main.audit_logger.log_query (user_id = client_ip, query = user_query, response_preview = "[streaming]",
              chunks = 0, duration_ms = duration_ms, tokens = 0, client_ip = client_ip, result_status = "success",
              metadata = {"version": version, "model": request.model}, )
      except Exception as e:
        logger.error (f"Streaming error: {e}", exc_info = True)
        if _main.audit_logger:
          _main.audit_logger.log_error (error_type = "StreamingError", error_msg = str (e), stack_trace = None,
              client_ip = client_ip, endpoint = "/v1/chat/completions", )
        yield f"data: {json.dumps ({'error': str (e)})}\n\n"

    return StreamingResponse (event_generator (), media_type = "text/event-stream")
  else:
    # Non-streaming
    try:
      _rag_result = await _main.process_rag_query (user_query = user_query, version = version,
          force_refresh = request.rag_force_refresh or False, temperature = request.temperature or 0.2,
          max_tokens = request.max_tokens or 4096, stream = False, other_messages = other_messages, user_context = user,
          top_k_override = request.rag_top_k, )
    except Exception as rag_err:
      logger.error ("Non-streaming RAG query failed: %s", rag_err, exc_info = True)
      if _main.audit_logger:
        _main.audit_logger.log_error (error_type = "RAGQueryError", error_msg = str (rag_err),
            stack_trace = None, client_ip = client_ip, endpoint = "/v1/chat/completions", )
      raise HTTPException (status_code = 503,
          detail = {"error": "rag_unavailable",
              "message": "Knowledge system temporarily unavailable. Please try again later.", }) from rag_err
    response_text = str (_rag_result [0])
    rag_ctx: str = str (_rag_result [1])
    from_cache = _rag_result [2]
    sources = _rag_result [3]
    ragas_scores = _rag_result [4]
    from proxy.app.core.confidence import compute_confidence
    from proxy.app.core.hitl import generate_feedback_id

    feedback_id = generate_feedback_id ()
    confidence = compute_confidence (query = user_query, context = rag_ctx, answer = response_text)
    completion = ChatCompletionResponse (id = request_id, created = int (time.time ()), model = request.model,
        choices = [
            ChatCompletionResponseChoice (index = 0,
                message = ChatMessage (role = "assistant", content = response_text), finish_reason = "stop")
        ], rag_feedback_id = feedback_id, rag_confidence = confidence.score, rag_sources = sources,
        ragas_scores = ragas_scores or None, )
    duration_ms = (time.time () - start_time) * 1000
    _main.request_tracker.complete (request_id, status = "success", tokens = len (response_text) // 4)
    if _main.audit_logger:
      _main.audit_logger.log_query (user_id = client_ip, query = user_query, response_preview = response_text [:200],
          chunks = len (sources), duration_ms = duration_ms, tokens = len (response_text) // 4, client_ip = client_ip,
          result_status = "success",
          metadata = {"version": version, "model": request.model, "from_cache": from_cache}, )
      _main.audit_logger.log_trace (request_id = request_id, user_id = client_ip, query = user_query,
          chunks_count = len (sources), rerank_scores = [s ["relevance"] for s in sources], duration_ms = duration_ms,
          tokens = len (response_text) // 4, confidence = confidence.score, feedback_id = feedback_id,
          client_ip = client_ip, )
    if _main.LOG_REQUESTS:  # type: ignore[attr-defined]
      from proxy.app.core.hitl import log_interaction

      await log_interaction (request_id = request_id, user_query = user_query,
          context = "[rag_context_omitted_for_logging]", response = response_text,
          metadata = {"version": version, "model": request.model, "client_ip": client_ip, "from_cache": from_cache}, )
    return completion
