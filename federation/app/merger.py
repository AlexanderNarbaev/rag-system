import hashlib
import logging

from .models import SiloSearchResult

logger = logging.getLogger("federation")


def _hash_chunk(chunk: dict) -> str:
    text = chunk.get("text", "")
    source = chunk.get("source_type", chunk.get("source", ""))
    title = chunk.get("title", chunk.get("doc_title", ""))
    key = f"{text}|{source}|{title}"
    return hashlib.sha256(key.encode()).hexdigest()


def deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for chunk in chunks:
        h = _hash_chunk(chunk)
        if h not in seen or chunk.get("score", 0) > seen[h].get("score", 0):
            seen[h] = chunk
    return list(seen.values())


def _get_weight(silo_result: SiloSearchResult) -> float:
    return silo_result.chunks[0].get("_silo_weight", 1.0) if silo_result.chunks else 1.0


def merge_weighted_rrf(
    results: list[SiloSearchResult], rrf_k: int = 60, merge_k: int = 60
) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for silo_result in results:
        w = _get_weight(silo_result)
        if w <= 0:
            w = 1.0
        for rank, chunk in enumerate(silo_result.chunks):
            rrf_score = w / (rrf_k + rank + 1)
            chunk_copy = dict(chunk)
            chunk_copy["score"] = rrf_score
            chunk_copy["silo_id"] = silo_result.silo_id
            chunk_copy["silo_name"] = silo_result.silo_name
            scored.append((rrf_score, chunk_copy))
    scored.sort(key=lambda x: x[0], reverse=True)
    merged = [c for _, c in scored]
    deduped = deduplicate_chunks(merged)
    return deduped[:merge_k]


def merge_round_robin(
    results: list[SiloSearchResult], merge_k: int = 60
) -> list[dict]:
    interleaved: list[dict] = []
    max_len = max((len(r.chunks) for r in results), default=0)
    for i in range(max_len):
        for silo_result in results:
            if i < len(silo_result.chunks):
                chunk = dict(silo_result.chunks[i])
                chunk["silo_id"] = silo_result.silo_id
                chunk["silo_name"] = silo_result.silo_name
                interleaved.append(chunk)
    deduped = deduplicate_chunks(interleaved)
    return deduped[:merge_k]


def merge_top_per_instance(
    results: list[SiloSearchResult], merge_k: int = 60
) -> list[dict]:
    n = len(results)
    if n == 0:
        return []
    per_instance = max(1, merge_k // n)
    selected: list[dict] = []
    for silo_result in results:
        for chunk in silo_result.chunks[:per_instance]:
            chunk_copy = dict(chunk)
            chunk_copy["silo_id"] = silo_result.silo_id
            chunk_copy["silo_name"] = silo_result.silo_name
            selected.append(chunk_copy)
    selected.sort(key=lambda c: c.get("score", 0), reverse=True)
    deduped = deduplicate_chunks(selected)
    return deduped[:merge_k]


def merge(
    results: list[SiloSearchResult],
    strategy: str = "weighted_rrf",
    rrf_k: int = 60,
    merge_k: int = 60,
) -> list[dict]:
    if strategy == "round_robin":
        return merge_round_robin(results, merge_k)
    elif strategy == "top_per_instance":
        return merge_top_per_instance(results, merge_k)
    else:
        return merge_weighted_rrf(results, rrf_k, merge_k)
