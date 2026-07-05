import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest

from .config import (
    FEDERATION_MERGE_K,
    FEDERATION_MERGE_STRATEGY,
    FEDERATION_MODE,
    FEDERATION_RRF_K,
    load_silos,
)
from .exceptions import AllSilosDownError, FederationError
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
    user_groups = ["admin"]
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

    user_groups = ["admin"]

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

    sources = [
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

    return {
        "id": f"fed-{int(time.time())}",
        "object": "chat.completion",
        "model": "rag-federated",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": (
                    f"Retrieved {len(result.merged_chunks)} chunks from {len(result.silo_results)} silos. "
                    "Federation delegates generation to primary silo — see rag_sources below."
                ),
            },
            "finish_reason": "stop",
        }],
        "rag_sources": sources,
        "rag_confidence": 0.5,
        "federation": {
            "mode": federation_mode,
            "silos_queried": [r.silo_id for r in result.silo_results if r.chunks],
            "silos_skipped": result.skipped_silos,
            "cross_silo": len({r.silo_id for r in result.silo_results if r.chunks}) > 1,
            "total_latency_ms": result.total_latency_ms,
            "per_silo_latency_ms": {
                r.silo_id: r.latency_ms for r in result.silo_results
            },
            "warnings": result.errors,
        },
    }


@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type="text/plain")
