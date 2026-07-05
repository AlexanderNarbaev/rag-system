import asyncio
import time
import logging
from .models import (
    SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
)
from .silo_registry import SiloRegistry
from .silo_client import query_silo
from .merger import merge
from .auto_router import classify_query
from .config import (
    FEDERATION_PER_INSTANCE_TIMEOUT_S,
    FEDERATION_MERGE_K,
    FEDERATION_RRF_K,
)

logger = logging.getLogger("federation")


def _resolve_target_silos(
    ctx: FederationContext, registry: SiloRegistry
) -> list[SiloConfig]:
    if ctx.mode == "strict" and ctx.target_silos:
        silos = []
        for sid in ctx.target_silos:
            silo = registry.get(sid)
            if silo and silo.is_accessible_by(ctx.user_groups):
                silos.append(silo)
        return silos
    return registry.list_accessible(ctx.user_groups)


async def _resolve_auto_silos(
    ctx: FederationContext, registry: SiloRegistry
) -> list[SiloConfig]:
    target_ids = await classify_query(ctx.query, registry)
    ctx.cross_silo = len(target_ids) > 1
    ctx.target_silos = target_ids
    return [registry.get(sid) for sid in target_ids if registry.get(sid)]


async def federated_search(
    ctx: FederationContext,
    registry: SiloRegistry,
) -> FederatedSearchResult:
    start = time.monotonic()
    if ctx.mode == "auto":
        silos = await _resolve_auto_silos(ctx, registry)
    else:
        silos = _resolve_target_silos(ctx, registry)
    errors: list[str] = []
    skipped: list[str] = []

    if not silos:
        return FederatedSearchResult(
            query=ctx.query,
            merged_chunks=[],
            silo_results=[],
            total_latency_ms=0,
            errors=["No accessible silos for user"],
        )

    timeout = FEDERATION_PER_INSTANCE_TIMEOUT_S
    tasks = [
        query_silo(silo, ctx.query, ctx.merge_k, timeout_s=timeout)
        for silo in silos
    ]
    silo_results: list[SiloSearchResult] = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[SiloSearchResult] = []
    for i, result in enumerate(silo_results):
        if isinstance(result, Exception):
            silo_id = silos[i].id
            errors.append(f"{silo_id}: {result}")
            results.append(SiloSearchResult(
                silo_id=silo_id, silo_name=silos[i].name,
                chunks=[], latency_ms=0, error=str(result), partial=True
            ))
        else:
            results.append(result)
            if result.error:
                errors.append(f"{result.silo_id}: {result.error}")

    merged_chunks = merge(
        [r for r in results if r.chunks],
        strategy=ctx.merge_strategy,
        rrf_k=ctx.rrf_k,
        merge_k=ctx.merge_k,
    )

    total_latency = (time.monotonic() - start) * 1000

    return FederatedSearchResult(
        query=ctx.query,
        merged_chunks=merged_chunks,
        silo_results=results,
        total_latency_ms=total_latency,
        errors=errors,
        skipped_silos=skipped,
    )
