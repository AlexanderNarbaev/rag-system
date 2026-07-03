#!/usr/bin/env python3
"""
MCP Server for RAG System — exposes knowledge base tools, resources, and prompts
to MCP-compatible clients (OpenCode, Claude Desktop, etc.).

Supports:
- STDIO transport (local OpenCode)
- Streamable HTTP transport (remote OpenCode)

Configuration via environment variables (see README.md).
"""

import os
import sys
import json
import hashlib
import logging
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("rag-mcp")

# ---------------------------------------------------------------------------
# Environment configuration (mirrors proxy/app/config.py)
# ---------------------------------------------------------------------------
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_GRPC_PORT: int = int(os.getenv("QDRANT_GRPC_PORT", "6334"))
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "knowledge_base")

EMBEDDER_MODEL: str = os.getenv("EMBEDDER_MODEL", "BAAI/bge-m3")
EMBEDDER_DEVICE: str = os.getenv("EMBEDDER_DEVICE", "cpu")

GRAPH_ENABLED: bool = os.getenv("GRAPH_ENABLED", "false").lower() == "true"
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8000"))

# RAG proxy connection for rag_chat tool
RAG_PROXY_URL: str = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
RAG_PROXY_API_KEY: str = os.getenv("RAG_PROXY_API_KEY", "")

# ---------------------------------------------------------------------------
# Lazy service clients
# ---------------------------------------------------------------------------
_qdrant_client: Any = None
_neo4j_driver: Any = None
_embedder: Any = None

_qdrant_available: bool = False
_neo4j_available: bool = False
_embedder_available: bool = False


def _get_qdrant_client():
    """Lazy-init Qdrant client. Returns None if unavailable."""
    global _qdrant_client, _qdrant_available
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient, models  # noqa: F401

        _qdrant_client = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            grpc_port=QDRANT_GRPC_PORT,
            prefer_grpc=False,
        )
        _qdrant_client.get_collections()
        _qdrant_available = True
        logger.info(
            "Qdrant connected at %s:%s", QDRANT_HOST, QDRANT_PORT
        )
    except Exception as exc:
        logger.warning("Qdrant unavailable: %s", exc)
        _qdrant_available = False
        _qdrant_client = None
    return _qdrant_client


def _get_embedder():
    """Lazy-init embedder. Returns None if unavailable."""
    global _embedder, _embedder_available
    if _embedder is not None:
        return _embedder
    try:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)
        _embedder_available = True
        logger.info("Embedder %s loaded on %s", EMBEDDER_MODEL, EMBEDDER_DEVICE)
    except Exception as exc:
        logger.warning("Embedder unavailable: %s", exc)
        _embedder_available = False
        _embedder = None
    return _embedder


def _get_neo4j_driver():
    """Lazy-init Neo4j driver. Returns None if unavailable."""
    global _neo4j_driver, _neo4j_available
    if not GRAPH_ENABLED:
        return None
    if _neo4j_driver is not None:
        return _neo4j_driver
    try:
        from neo4j import GraphDatabase

        _neo4j_driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        _neo4j_driver.verify_connectivity()
        _neo4j_available = True
        logger.info("Neo4j connected at %s", NEO4J_URI)
    except Exception as exc:
        logger.warning("Neo4j unavailable: %s", exc)
        _neo4j_available = False
        _neo4j_driver = None
    return _neo4j_driver


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("RAG Knowledge Base", json_response=True)
except ImportError:
    logger.error(
        "mcp SDK not installed. Run: pip install 'mcp[cli]>=1.0'"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
def _compute_dense_embedding(text: str) -> Optional[list[float]]:
    """Compute dense embedding vector with error handling."""
    embedder = _get_embedder()
    if embedder is None:
        return None
    try:
        return embedder.encode(text, normalize_embeddings=True).tolist()
    except Exception as exc:
        logger.error("Embedding computation failed: %s", exc)
        return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    return max(1, len(text) // 4)


def _hit_to_dict(hit: Any, score: Optional[float] = None) -> dict[str, Any]:
    """Convert a Qdrant ScoredPoint to a plain dict."""
    payload = {}
    if hasattr(hit, "payload") and hit.payload is not None:
        payload = dict(hit.payload)
    return {
        "id": getattr(hit, "id", None),
        "score": score if score is not None else getattr(hit, "score", 0.0),
        "text": payload.get("text", ""),
        "source_type": payload.get("source_type", "unknown"),
        "source_id": payload.get("source_id", ""),
        "title": payload.get("title", ""),
        "doc_title": payload.get("doc_title", ""),
        "version": payload.get("version", "latest"),
        "url": payload.get("url", ""),
    }


# ===================================================================
# TOOLS
# ===================================================================


@mcp.tool()
def rag_search(
    query: str,
    top_k: int = 10,
    source_type: Optional[str] = None,
) -> str:
    """Search the RAG knowledge base and return ranked results.

    Args:
        query: Natural-language search query.
        top_k: Maximum number of results to return (1-100).
        source_type: Optional filter by source type
                     (e.g. 'confluence', 'jira', 'gitlab').

    Returns:
        JSON string with ranked search results including text, metadata,
        and relevance scores.
    """
    logger.info(
        "rag_search query=%r top_k=%d source_type=%s", query, top_k, source_type
    )
    client = _get_qdrant_client()
    if client is None:
        return json.dumps(
            {"error": "Qdrant is unavailable", "results": []}, ensure_ascii=False
        )

    top_k = max(1, min(top_k, 100))
    collection_name = COLLECTION_NAME

    try:
        # Build optional filter
        q_filter = None
        if source_type:
            from qdrant_client.http import models

            q_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value=source_type),
                    )
                ]
            )

        # Try dense search first
        dense_vec = _compute_dense_embedding(query)
        if dense_vec is not None:
            results = client.search(
                collection_name=collection_name,
                query_vector=dense_vec,
                limit=top_k,
                query_filter=q_filter,
                with_payload=True,
            )
        else:
            # Fallback: text-only scroll with filtering
            logger.warning(
                "Embedder unavailable, falling back to text-only search"
            )
            scroll_results, _ = client.scroll(
                collection_name=collection_name,
                limit=top_k,
                with_payload=True,
            )
            # Filter by source_type if provided
            if source_type:
                scroll_results = [
                    r
                    for r in scroll_results
                    if r.payload
                    and r.payload.get("source_type") == source_type
                ]
            results = scroll_results[:top_k]

        hits = [_hit_to_dict(h) for h in results]
        output = {
            "query": query,
            "count": len(hits),
            "results": hits,
        }
        logger.info("rag_search returned %d results", len(hits))
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("rag_search failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "results": []}, ensure_ascii=False
        )


@mcp.tool()
def rag_get_context(
    query: str,
    max_tokens: int = 5000,
    source_type: Optional[str] = None,
) -> str:
    """Search and assemble a ready-to-use context for LLM prompting.

    Performs search, deduplication by content hash, and token-limited
    assembly with source metadata headers.

    Args:
        query: Natural-language search query.
        max_tokens: Maximum tokens in assembled context (default 5000).
        source_type: Optional source type filter.

    Returns:
        Assembled context text ready for insertion into an LLM prompt.
    """
    logger.info(
        "rag_get_context query=%r max_tokens=%d", query, max_tokens
    )
    client = _get_qdrant_client()
    if client is None:
        return "[Qdrant unavailable — no context available]"

    try:
        # Search
        dense_vec = _compute_dense_embedding(query)
        if dense_vec is None:
            return "[Embedder unavailable — cannot compute embeddings]"

        # Build filter
        q_filter = None
        if source_type:
            from qdrant_client.http import models

            q_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value=source_type),
                    )
                ]
            )

        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=dense_vec,
            limit=50,
            query_filter=q_filter,
            with_payload=True,
        )

        if not results:
            return "[No relevant documents found]"

        # Dedup by content hash
        seen_hashes: set[str] = set()
        unique_chunks: list[dict[str, Any]] = []
        for hit in results:
            chunk = _hit_to_dict(hit)
            h = hashlib.sha256(
                chunk["text"].encode("utf-8")
            ).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_chunks.append(chunk)

        # Assemble context with token limit
        parts: list[str] = []
        total_tokens = 0
        for chunk in unique_chunks:
            header = (
                f"[{chunk['source_type']}] {chunk['doc_title']} / "
                f"{chunk['title']} (v{chunk['version']}) "
                f"[rel={chunk['score']:.3f}]\n"
            )
            body = header + chunk["text"] + "\n\n"
            body_tokens = _estimate_tokens(body)
            if total_tokens + body_tokens > max_tokens:
                remaining = max_tokens - total_tokens
                if remaining > 50:
                    truncated = chunk["text"][: remaining * 4]
                    parts.append(header + truncated + "...\n")
                break
            parts.append(body)
            total_tokens += body_tokens

        context = "".join(parts)
        logger.info(
            "rag_get_context assembled %d chars, ~%d tokens",
            len(context),
            total_tokens,
        )
        return context

    except Exception as exc:
        logger.error("rag_get_context failed: %s", exc)
        return f"[Error assembling context: {exc}]"


@mcp.tool()
def rag_list_sources() -> str:
    """List all available data sources with document counts.

    Queries Qdrant to enumerate source types and count unique documents.

    Returns:
        JSON string with source types and their document counts.
    """
    logger.info("rag_list_sources called")
    client = _get_qdrant_client()
    if client is None:
        return json.dumps(
            {"error": "Qdrant is unavailable", "sources": []},
            ensure_ascii=False,
        )

    try:
        # Scroll through all points to aggregate source stats
        sources: dict[str, set[str]] = {}
        offset = None

        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                if point.payload:
                    st = point.payload.get("source_type", "unknown")
                    sid = point.payload.get("source_id", "")
                    if st not in sources:
                        sources[st] = set()
                    if sid:
                        sources[st].add(sid)

            if next_offset is None:
                break
            offset = next_offset

        output = {
            "sources": [
                {
                    "source_type": st,
                    "document_count": len(doc_ids),
                    "documents": sorted(doc_ids)[:50],
                }
                for st, doc_ids in sorted(sources.items())
            ],
            "total_points": sum(len(v) for v in sources.values()),
            "collection": COLLECTION_NAME,
        }
        logger.info("rag_list_sources found %d source types", len(sources))
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("rag_list_sources failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "sources": []}, ensure_ascii=False
        )


@mcp.tool()
def rag_get_document(doc_id: str) -> str:
    """Retrieve a specific document by its Qdrant point ID.

    Args:
        doc_id: The Qdrant point ID (string or UUID).

    Returns:
        JSON string with the full document payload and metadata.
    """
    logger.info("rag_get_document doc_id=%r", doc_id)
    client = _get_qdrant_client()
    if client is None:
        return json.dumps(
            {"error": "Qdrant is unavailable"}, ensure_ascii=False
        )

    try:
        # Try numeric ID first, then string
        point_id: Any = doc_id
        try:
            import uuid

            point_id = uuid.UUID(doc_id)
        except (ValueError, AttributeError):
            try:
                point_id = int(doc_id)
            except ValueError:
                pass

        points = client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return json.dumps(
                {"error": f"Document {doc_id} not found", "document": None},
                ensure_ascii=False,
            )

        doc = _hit_to_dict(points[0])
        return json.dumps(
            {"document": doc}, ensure_ascii=False, indent=2
        )

    except Exception as exc:
        logger.error("rag_get_document failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "document": None}, ensure_ascii=False
        )


@mcp.tool()
def rag_get_entities(entity_name: str) -> str:
    """Query Neo4j for entities and their relationships.

    Args:
        entity_name: Name of the entity to look up in the knowledge graph.

    Returns:
        JSON string with entity details and related entities.
    """
    logger.info("rag_get_entities entity_name=%r", entity_name)
    driver = _get_neo4j_driver()
    if driver is None:
        return json.dumps(
            {
                "error": "Neo4j is unavailable (check GRAPH_ENABLED and connection)",
                "entities": [],
            },
            ensure_ascii=False,
        )

    try:
        cypher = """
        MATCH (e:Entity)
        WHERE e.name CONTAINS $name
        OPTIONAL MATCH (e)-[r]-(related:Entity)
        RETURN e.name AS name,
               e.type AS type,
               labels(e) AS labels,
               collect(DISTINCT {
                   name: related.name,
                   type: related.type,
                   relation: type(r)
               }) AS related
        LIMIT 20
        """
        entities = []
        with driver.session() as session:
            result = session.run(cypher, {"name": entity_name})
            for record in result:
                entities.append(
                    {
                        "name": record["name"],
                        "type": record["type"],
                        "labels": record["labels"],
                        "related": [
                            r
                            for r in record["related"]
                            if r["name"] is not None
                        ],
                    }
                )

        output = {
            "query": entity_name,
            "count": len(entities),
            "entities": entities,
        }
        logger.info(
            "rag_get_entities found %d entities", len(entities)
        )
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("rag_get_entities failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "entities": []}, ensure_ascii=False
        )


@mcp.tool()
def rag_search_graph(
    query: str,
    max_hops: int = 2,
) -> str:
    """Graph-enhanced search: vector search + knowledge graph traversal.

    Searches Qdrant for initial candidates, then expands results by
    traversing entity relationships in Neo4j.

    Args:
        query: Natural-language search query.
        max_hops: Maximum graph traversal depth (1-5).

    Returns:
        JSON string with enriched results including graph context.
    """
    logger.info(
        "rag_search_graph query=%r max_hops=%d", query, max_hops
    )
    max_hops = max(1, min(max_hops, 5))

    client = _get_qdrant_client()
    if client is None:
        return json.dumps(
            {"error": "Qdrant is unavailable", "results": [], "graph_context": ""},
            ensure_ascii=False,
        )

    try:
        # Step 1: Vector search
        dense_vec = _compute_dense_embedding(query)
        if dense_vec is None:
            return json.dumps(
                {"error": "Embedder unavailable", "results": [], "graph_context": ""},
                ensure_ascii=False,
            )

        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=dense_vec,
            limit=20,
            with_payload=True,
        )
        hits = [_hit_to_dict(h) for h in results]

        # Step 2: Graph expansion
        graph_context = ""
        driver = _get_neo4j_driver()
        if driver is not None:
            # Extract entity-like keywords from query and top results
            keywords: set[str] = set()
            # From query
            for word in query.split():
                if len(word) > 3:
                    keywords.add(word.lower())
            # From top-3 result titles
            for h in hits[:3]:
                title = h.get("title", "")
                for word in title.split():
                    if len(word) > 3:
                        keywords.add(word.lower())

            if keywords:
                cypher = """
                MATCH (e:Entity)
                WHERE ANY(k IN $keywords WHERE toLower(e.name) CONTAINS k)
                OPTIONAL MATCH path = (e)-[*1..${hops}]-(related:Entity)
                RETURN e.name AS entity,
                       e.type AS etype,
                       collect(DISTINCT related.name)[0..10] AS related
                LIMIT 10
                """
                cypher = cypher.replace("${hops}", str(max_hops))
                with driver.session() as session:
                    graph_result = session.run(
                        cypher,
                        {"keywords": list(keywords)[:5]},
                    )
                    lines = []
                    for record in graph_result:
                        entity = record["entity"]
                        etype = record["etype"]
                        related = record["related"]
                        if related:
                            lines.append(
                                f"- {entity} ({etype}) → "
                                f"{', '.join(r for r in related if r)}"
                            )
                        else:
                            lines.append(f"- {entity} ({etype})")
                    if lines:
                        graph_context = (
                            "Knowledge graph relationships:\n"
                            + "\n".join(lines)
                        )

        output = {
            "query": query,
            "count": len(hits),
            "results": hits,
            "graph_context": graph_context,
        }
        logger.info(
            "rag_search_graph returned %d results + graph context",
            len(hits),
        )
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("rag_search_graph failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "results": [], "graph_context": ""},
            ensure_ascii=False,
        )


# ── rag_chat tool ──────────────────────────────────────────────────────────


@mcp.tool()
def rag_chat(
    query: str,
    stream: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Send a question to the RAG proxy chat endpoint and return the answer.

    This tool calls POST /v1/chat/completions on the RAG proxy, which handles
    retrieval, reranking, context assembly, and LLM generation.

    :param query: The user's question.
    :param stream: Whether to stream the response (default False).
    :param temperature: LLM sampling temperature (default 0.2).
    :param max_tokens: Maximum tokens in the response (default 4096).
    :return: The generated answer text.
    """
    import urllib.request
    import urllib.error

    url = f"{RAG_PROXY_URL.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if RAG_PROXY_API_KEY:
        headers["Authorization"] = f"Bearer {RAG_PROXY_API_KEY}"

    payload = {
        "model": "rag-model",
        "messages": [{"role": "user", "content": query}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        if stream:
            with urllib.request.urlopen(req, timeout=120) as resp:
                chunks = []
                buffer = ""
                while True:
                    raw = resp.read(4096)
                    if not raw:
                        break
                    buffer += raw.decode("utf-8")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: ") and line[6:] != "[DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                delta = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                chunks.append(delta)
                            except json.JSONDecodeError:
                                pass
                return "".join(chunks)
        else:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return f"Error {e.code}: {error_body}"
    except Exception as e:
        return f"Error: {e}"


# ===================================================================
# RESOURCES
# ===================================================================


@mcp.resource("knowledge://sources")
def resource_list_sources() -> str:
    """Resource: list of all indexed knowledge sources."""
    logger.info("Resource knowledge://sources accessed")
    return rag_list_sources()


@mcp.resource("knowledge://document/{doc_id}")
def resource_get_document(doc_id: str) -> str:
    """Resource: specific document content by ID."""
    logger.info("Resource knowledge://document/%s accessed", doc_id)
    return rag_get_document(doc_id)


@mcp.resource("knowledge://entity/{entity_name}")
def resource_get_entity(entity_name: str) -> str:
    """Resource: entity with its relationships from the knowledge graph."""
    logger.info(
        "Resource knowledge://entity/%s accessed", entity_name
    )
    return rag_get_entities(entity_name)


# ===================================================================
# PROMPTS
# ===================================================================


@mcp.prompt()
def rag_search_prompt(query: str) -> str:
    """Generate a reusable RAG search prompt template.

    Use this prompt to instruct an LLM to answer questions using
    retrieved knowledge base context.

    Args:
        query: The user's question to be answered.

    Returns:
        A formatted prompt string.
    """
    return (
        "You are a corporate knowledge assistant with access to an "
        "indexed knowledge base (Confluence, Jira, GitLab).\n\n"
        "Use the provided context to answer the user's question "
        "accurately and concisely.\n\n"
        "If the context does not contain sufficient information, "
        "clearly state what is missing.\n\n"
        f"User question: {query}\n\n"
        "Context:\n"
        "{context}\n\n"
        "Answer:"
    )


@mcp.prompt()
def rag_code_review_prompt(code: str, context: str) -> str:
    """Generate a code review prompt enriched with knowledge base context.

    Args:
        code: The source code to review.
        context: Retrieved context from the knowledge base (standards,
                 conventions, related documentation).

    Returns:
        A formatted prompt string for code review.
    """
    return (
        "You are a senior code reviewer. Review the following code "
        "using the provided knowledge base context as reference for "
        "coding standards, conventions, and best practices.\n\n"
        "Knowledge base context:\n"
        f"{context}\n\n"
        "Code to review:\n"
        f"```\n{code}\n```\n\n"
        "Provide a structured review covering:\n"
        "1. Correctness — logical errors, edge cases\n"
        "2. Style — adherence to conventions\n"
        "3. Performance — bottlenecks, inefficiencies\n"
        "4. Security — vulnerabilities, data handling\n"
        "5. Suggestions — concrete improvement recommendations\n\n"
        "Review:"
    )


# ===================================================================
# Entry point
# ===================================================================


def main() -> None:
    """Run the MCP server with the configured transport."""
    transport = MCP_TRANSPORT.lower()

    logger.info(
        "Starting RAG MCP server (transport=%s, qdrant=%s:%s, "
        "neo4j=%s, embedder=%s/%s)",
        transport,
        QDRANT_HOST,
        QDRANT_PORT,
        "enabled" if GRAPH_ENABLED else "disabled",
        EMBEDDER_MODEL,
        EMBEDDER_DEVICE,
    )

    # Pre-warm connections (best-effort)
    _get_qdrant_client()
    if GRAPH_ENABLED:
        _get_neo4j_driver()

    if transport == "http":
        mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
