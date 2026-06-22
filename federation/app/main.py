import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest

from .config import (
    FEDERATION_LLM_ENDPOINT,
    FEDERATION_LLM_MODEL,
    FEDERATION_MERGE_K,
    FEDERATION_MERGE_STRATEGY,
    FEDERATION_MODE,
    FEDERATION_RRF_K,
    load_silos,
)
from .exceptions import AllSilosDownError, FederationError
from .jwt_auth import extract_user_groups
from .metrics import REQUESTS_TOTAL, SILOS_ACTIVE
from .models import FederationContext
from .router import federated_search
from .silo_registry import SiloRegistry

logger = logging.getLogger("federation")

registry: SiloRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    silos = load_silos()
    registry = SiloRegistry(silos)
    SILOS_ACTIVE.set(len(silos))
    logger.info(f"Federation started: {len(silos)} silos, mode={FEDERATION_MODE}")
    yield
    logger.info("Federation shutting down")


app = FastAPI(
    title="Federated RAG Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(FederationError)
async def federation_error_handler(request: Request, exc: FederationError):
    return JSONResponse(
        status_code=503 if isinstance(exc, AllSilosDownError) else 400,
        content={"error": str(exc), "type": type(exc).__name__},
    )


@app.get("/v1/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/v1/health/ready")
async def health_ready():
    if registry is None:
        return {"status": "not_ready", "silos": []}
    silos_status = {}
    for silo in registry.list_all():
        silos_status[silo.id] = {
            "name": silo.name,
            "url": silo.proxy_url,
        }
    return {"status": "ready", "silos": silos_status}


@app.get("/v1/health")
async def health():
    if registry is None:
        return {"status": "starting"}
    silos_status = {}
    for silo in registry.list_all():
        silos_status[silo.id] = {"name": silo.name, "status": "configured"}
    return {
        "status": "healthy",
        "federation": {
            "mode": FEDERATION_MODE,
            "total_silos": len(registry),
            "silos": silos_status,
        }
    }


@app.get("/v1/silos")
async def list_silos(request: Request):
    if registry is None:
        return {"silos": []}
    user_groups = extract_user_groups(request)
    accessible = registry.list_accessible(user_groups)
    return {
        "silos": [
            {
                "id": s.id,
                "name": s.name,
                "collections": s.collections,
                "accessible": True,
            }
            for s in accessible
        ]
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "rag-federated",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "federation",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if registry is None:
        raise HTTPException(status_code=503, detail="Federation not ready")

    body = await request.json()
    messages = body.get("messages", [])
    user_query = messages[-1]["content"] if messages else ""

    federation_silo = body.get("federation_silo")
    federation_mode = body.get("federation_mode", FEDERATION_MODE)
    merge_k = body.get("federation_top_k", FEDERATION_MERGE_K)
    merge_strategy = body.get("federation_merge_strategy", FEDERATION_MERGE_STRATEGY)
    skip_generation = body.get("rag_skip_generation", False)

    user_groups = extract_user_groups(request)

    target_silos = [federation_silo] if federation_silo else []

    ctx = FederationContext(
        mode=federation_mode,
        target_silos=target_silos,
        merge_strategy=merge_strategy,
        merge_k=merge_k,
        rrf_k=FEDERATION_RRF_K,
        user_groups=user_groups,
        query=user_query,
    )

    REQUESTS_TOTAL.labels(mode=federation_mode, status="started").inc()

    try:
        result = await federated_search(ctx, registry)
        REQUESTS_TOTAL.labels(mode=federation_mode, status="success").inc()
    except Exception as e:
        REQUESTS_TOTAL.labels(mode=federation_mode, status="error").inc()
        raise HTTPException(status_code=500, detail=str(e)) from e

    if result.errors and not result.merged_chunks:
        raise AllSilosDownError(failed_silos=[r.silo_id for r in result.silo_results])

    sources = _build_sources(result)
    federation_meta = _build_federation_meta(result, federation_mode)

    if skip_generation or not result.merged_chunks:
        return {
            "id": f"fed-{int(time.time())}",
            "object": "chat.completion",
            "model": "rag-federated",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "" if skip_generation else "No relevant information found across silos.",
                },
                "finish_reason": "stop",
            }],
            "rag_sources": sources,
            "rag_metadata": {
                "total_retrieved": sum(len(r.chunks) for r in result.silo_results),
                "merged_count": len(result.merged_chunks),
                "latency_ms": result.total_latency_ms,
            },
            "federation": federation_meta,
        }

    generation = await delegate_generation(user_query, messages, result, user_groups)

    return {
        "id": f"fed-{int(time.time())}",
        "object": "chat.completion",
        "model": "rag-federated",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": generation.get("content", ""),
            },
            "finish_reason": "stop",
        }],
        "rag_sources": sources,
        "rag_confidence": generation.get("confidence", 0.5),
        "federation": federation_meta,
    }


@app.post("/v1/search")
async def search(request: Request):
    if registry is None:
        raise HTTPException(status_code=503, detail="Federation not ready")

    body = await request.json()
    query = body.get("query", body.get("messages", [{}])[-1].get("content", ""))

    federation_silo = body.get("federation_silo")
    federation_mode = body.get("federation_mode", FEDERATION_MODE)
    merge_k = body.get("federation_top_k", FEDERATION_MERGE_K)
    merge_strategy = body.get("federation_merge_strategy", FEDERATION_MERGE_STRATEGY)

    user_groups = extract_user_groups(request)

    target_silos = [federation_silo] if federation_silo else []

    ctx = FederationContext(
        mode=federation_mode,
        target_silos=target_silos,
        merge_strategy=merge_strategy,
        merge_k=merge_k,
        rrf_k=FEDERATION_RRF_K,
        user_groups=user_groups,
        query=query,
    )

    try:
        result = await federated_search(ctx, registry)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if result.errors and not result.merged_chunks:
        raise AllSilosDownError(failed_silos=[r.silo_id for r in result.silo_results])

    sources = _build_sources(result)
    federation_meta = _build_federation_meta(result, federation_mode)

    return {
        "rag_sources": sources,
        "rag_metadata": {
            "total_retrieved": sum(len(r.chunks) for r in result.silo_results),
            "merged_count": len(result.merged_chunks),
            "latency_ms": result.total_latency_ms,
        },
        "federation": federation_meta,
    }


def _build_sources(result):
    return [
        {
            "chunk_id": c.get("id", ""),
            "source": c.get("source_type", "unknown"),
            "title": c.get("title", ""),
            "version": c.get("version", ""),
            "silo_id": c.get("silo_id", ""),
            "silo_name": c.get("silo_name", ""),
            "relevance": c.get("score", 0.0),
            "text_preview": c.get("text", "")[:200],
        }
        for c in result.merged_chunks
    ]


def _build_federation_meta(result, federation_mode):
    return {
        "mode": federation_mode,
        "silos_queried": [r.silo_id for r in result.silo_results if r.chunks],
        "silos_skipped": result.skipped_silos,
        "cross_silo": len({r.silo_id for r in result.silo_results if r.chunks}) > 1,
        "total_latency_ms": result.total_latency_ms,
        "per_silo_latency_ms": {
            r.silo_id: r.latency_ms for r in result.silo_results
        },
        "warnings": result.errors,
    }


async def delegate_generation(
    query: str,
    messages: list[dict],
    result,
    user_groups: list[str],
) -> dict:
    context_text = "\n\n".join(
        f"[Source: {c.get('source_type', 'unknown')} | {c.get('title', '')}]\n{c.get('text', '')}"
        for c in result.merged_chunks[:15]
    )

    if FEDERATION_LLM_ENDPOINT:
        return await _generate_direct(query, messages, context_text)

    if registry is None:
        return {"content": _build_fallback_content(result), "confidence": 0.5}

    primary = registry.get_primary()
    if primary is None:
        return {"content": _build_fallback_content(result), "confidence": 0.5}

    return await _generate_via_primary(query, messages, context_text, primary, result)


async def _generate_direct(query: str, messages: list[dict], context: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
            payload = {
                "model": FEDERATION_LLM_MODEL or "rag-federated",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a federated RAG assistant. Answer the user's question "
                            "using only the provided context from multiple knowledge silos. "
                            "If the context is insufficient, say you don't know."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {query}",
                    },
                ],
                "temperature": 0.3,
                "stream": False,
            }
            response = await client.post(
                f"{FEDERATION_LLM_ENDPOINT.rstrip('/')}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"content": content, "confidence": 0.7}
    except Exception as e:
        logger.warning(f"Direct LLM generation failed: {e}")
        return {"content": _build_fallback_content(result=None), "confidence": 0.3}


async def _generate_via_primary(
    query: str, messages: list[dict], context: str, primary, result
) -> dict:
    try:
        headers = {"Content-Type": "application/json"}
        if primary.api_key:
            headers["Authorization"] = f"Bearer {primary.api_key}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
            payload = {
                "model": "rag-internal",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a federated RAG assistant. Generate a complete answer "
                            "to the user's question using the provided context from all federated silos. "
                            "Cite sources by title and silo when relevant."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context from federated search:\n{context}\n\nQuestion: {query}",
                    },
                ],
                "temperature": 0.3,
                "stream": False,
            }
            response = await client.post(
                f"{primary.proxy_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {"content": content, "confidence": 0.7}
    except Exception as e:
        logger.warning(f"Generation via primary silo '{primary.id}' failed: {e}")
        return {"content": _build_fallback_content(result), "confidence": 0.3}


def _build_fallback_content(result) -> str:
    if result is None:
        return "Unable to generate a response. Please try again later."
    chunk_count = len(result.merged_chunks) if result else 0
    silo_count = len(result.silo_results) if result else 0
    return (
        f"Retrieved {chunk_count} chunks from {silo_count} silos. "
        "Generation service is currently unavailable. "
        "Review the rag_sources below for relevant information."
    )


@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type="text/plain")
