# ADR-004: OpenAI-Compatible Proxy Pattern

**Status:** Accepted
**Date:** 2026-06-22

## Context

The RAG system must integrate with existing tools in the corporate environment — OpenWebUI, OpenCode, and custom internal clients — all of which speak the OpenAI chat completions API. Building a custom API would require adapting every client, adding maintenance burden and fragmentation. The system must support both streaming (real-time token generation) and non-streaming modes while internally performing RAG (retrieval, reranking, context assembly) before calling the LLM.

Alternatives considered: **native LangChain integration** (ties clients to a specific framework), **custom REST API** (requires client-side changes), **gRPC service** (not supported by existing tools).

## Decision

**Implement an OpenAI-compatible proxy using FastAPI, exposing `/v1/chat/completions`, `/v1/models`, and `/v1/health`.**

The proxy is defined in `proxy/app/main.py` with Pydantic models matching OpenAI's schema:
- `ChatCompletionRequest` (`main.py:93-103`) mirrors OpenAI fields (model, messages, temperature, max_tokens, stream) and adds RAG-specific extensions: `rag_version` for version-pinned retrieval, `rag_force_refresh` to bypass cache.
- `ChatCompletionResponse` (`main.py:111-117`) includes usage statistics, finish_reason, and model identifiers.

Streaming uses Server-Sent Events (`main.py:317-337`) — `text/event-stream` with `data: {json}\n\n` chunks, terminated by `data: [DONE]\n\n`, matching OpenAI's streaming protocol.

The internal RAG pipeline (`main.py:137-208`) is transparent to the client: retrieval, reranking, deduplication, and context assembly happen within the proxy before the LLM call. Non-streaming responses are cached in Redis for 1 hour (`main.py:207`, `ttl=3600`).

Health check (`/v1/health` at `main.py:211-238`) reports Qdrant and LLM endpoint status, returning 503 if degraded — compatible with Docker health checks and load balancers.

## Consequences

**Positive:** Drop-in replacement for any OpenAI client — existing tools point to the proxy URL and continue working unchanged. Single proxy handles both RAG logic and LLM routing, reducing network hops. RAG extensions (`rag_version`, `rag_force_refresh`) are ignored by standard OpenAI clients (extra fields are silently accepted).

**Negative:** Non-RAG queries still go through the full pipeline (retrieval, context assembly) unless special-cased. The proxy adds 200-500ms latency for retrieval+reranking before LLM generation starts. Single worker mode (`main.py:377`, `workers=1`) limits concurrency to protect shared state (embedder, cache).

**Mitigations:** Cache layer reduces repeated query latency to <10ms. SLM-based intent classification (`slm_router.py:116-122`) can detect greetings/no-context queries and skip retrieval. Production scaling can use Redis-backed cache to enable multiple workers.
