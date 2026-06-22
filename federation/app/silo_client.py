import time
import logging
import httpx
from .models import SiloConfig, SiloSearchResult

logger = logging.getLogger("federation")


async def query_silo(
    silo: SiloConfig,
    query: str,
    top_k: int = 30,
    timeout_s: int | None = None,
) -> SiloSearchResult:
    timeout = timeout_s if timeout_s is not None else silo.timeout_s
    headers = {"Content-Type": "application/json"}
    if silo.api_key:
        headers["Authorization"] = f"Bearer {silo.api_key}"

    payload = {
        "model": "rag-internal",
        "messages": [{"role": "user", "content": query}],
        "rag_skip_generation": True,
        "rag_top_k": top_k,
        "rag_return_chunks": True,
        "temperature": 0,
        "stream": False,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            response = await client.post(
                f"{silo.proxy_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            latency_ms = (time.monotonic() - start) * 1000

            sources = data.get("rag_sources", [])
            chunks = _normalize_chunks(sources, silo)

            return SiloSearchResult(
                silo_id=silo.id,
                silo_name=silo.name,
                chunks=chunks,
                latency_ms=latency_ms,
            )
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        logger.warning(f"Silo '{silo.id}' query failed: {e}")
        return SiloSearchResult(
            silo_id=silo.id,
            silo_name=silo.name,
            chunks=[],
            latency_ms=latency_ms,
            error=str(e),
            partial=True,
        )


def _normalize_chunks(sources: list[dict], silo: SiloConfig) -> list[dict]:
    chunks = []
    for src in sources:
        chunk = {
            "id": src.get("chunk_id", ""),
            "text": src.get("text", src.get("text_preview", "")),
            "source_type": src.get("source", src.get("source_type", "unknown")),
            "title": src.get("title", src.get("doc_title", "")),
            "version": src.get("version", ""),
            "score": src.get("relevance", src.get("score", 0.0)),
            "_silo_weight": silo.weight,
        }
        chunks.append(chunk)
    return chunks
