# proxy/app/core/orchestrator/nodes.py
"""Node implementations for the RAG LangGraph state graph."""

import logging
from typing import Any, Literal

from proxy.app.core.token_optimizer import TokenOptimizer
from proxy.app.shared.config import (
    MAX_CHUNKS_AFTER_RERANK,
    MAX_CHUNKS_RETRIEVAL,
    MAX_RETRIEVAL_LOOPS,
    USE_GRAPH_EXPANSION,
)

logger = logging.getLogger(__name__)


def _get_hybrid_search():
    """Lazy import to allow test patching at orchestrator level."""
    from proxy.app.core.orchestrator import hybrid_search

    return hybrid_search


def _get_rerank_chunks():
    """Lazy import to allow test patching at orchestrator level."""
    from proxy.app.core.orchestrator import rerank_chunks

    return rerank_chunks


def _get_non_stream_completion():
    """Lazy import to allow test patching at orchestrator level."""
    from proxy.app.core.orchestrator import non_stream_completion

    return non_stream_completion


def _get_deduplicate_chunks():
    """Lazy import to allow test patching at orchestrator level."""
    from proxy.app.core.context import deduplicate_chunks

    return deduplicate_chunks


def _get_build_context():
    """Lazy import to allow test patching at orchestrator level."""
    from proxy.app.core.context import build_context

    return build_context


def _get_apply_time_decay():
    """Lazy import for apply_time_decay."""
    from proxy.app.core.retrieval import apply_time_decay

    return apply_time_decay


def _get_graph_expand_query():
    """Lazy import for graph_expand_query."""
    from proxy.app.core.retrieval import graph_expand_query

    return graph_expand_query


def _dynamic_top_k(query: str, *, max_default: int = 50) -> int:
    """Determine the optimal number of chunks to retrieve based on query intent.

    Greeting → 0 (skip retrieval), SimpleFact → 5, Factual → 15,
    Procedural → 25, Summarization → 30,
    Comparison/Complex → max_default. Falls back to max_default on error.
    """
    try:
        # Import here to allow test patching at orchestrator level
        from proxy.app.core.orchestrator import IntentType, classify_intent

        intent, _ = classify_intent(query)
        mapping = {
            IntentType.GREETING: 0,
            IntentType.SIMPLE_FACT: min(5, max_default),
            IntentType.FACTUAL: min(15, max_default),
            IntentType.PROCEDURAL: min(25, max_default),
            IntentType.SUMMARIZATION: min(30, max_default),
            IntentType.COMPARISON: max_default,
            IntentType.COMPLEX: max_default,
        }
        return mapping.get(intent, max_default)
    except Exception:
        return max_default


def rewrite_query(state: dict[str, Any]) -> dict[str, Any]:
    """
    Переписывает запрос с помощью LLM для улучшения ретривала.
    Используется при первом входе или когда контекст признан недостаточным.
    """
    query = state["query"]
    rewrite_count = state.get("rewrite_count", 0)

    if rewrite_count >= MAX_RETRIEVAL_LOOPS:
        logger.warning(f"Max rewrite loops reached ({MAX_RETRIEVAL_LOOPS}), using original query")
        return {"rewritten_query": query, "rewrite_count": rewrite_count}

    prompt = (
        "Перепиши следующий вопрос пользователя в более "
        "эффективный поисковый запрос для технической документации."
        "\n"
        "Сохрани все ключевые сущности (номера задач, технологии, имена)."
        "\n"
        "Выдай только переписанный запрос, без пояснений."
        f"\n\nОригинальный вопрос: {query}"
        "\n\nПереписанный запрос:"
    )

    try:
        rewritten = _get_non_stream_completion()([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=100)
        rewritten = rewritten.strip()
        logger.info(f"Rewritten query: '{query}' -> '{rewritten}'")
        return {"rewritten_query": rewritten, "rewrite_count": rewrite_count + 1}
    except Exception as e:
        logger.error(f"Rewrite failed: {e}, using original")
        return {"rewritten_query": query, "rewrite_count": rewrite_count + 1}


def retrieve(state: dict[str, Any]) -> dict[str, Any]:
    """
    Выполняет гибридный поиск в Qdrant.
    Использует переписанный запрос, если есть, иначе оригинальный.
    Применяет time-decay бустинг для версионированных документов.
    """
    query_to_use = state.get("rewritten_query") or state["query"]
    version = state.get("version")

    logger.info(f"Retrieving for: '{query_to_use}' (version: {version})")
    results = _get_hybrid_search()(query=query_to_use, version=version, top_k=MAX_CHUNKS_RETRIEVAL)

    # Преобразуем результаты в список словарей для единообразия
    chunks = []
    for hit in results:
        chunks.append({"id": hit.id, "text": hit.payload.get("text", ""), "score": hit.score, "payload": hit.payload})

    # Применяем time-decay бустинг для версионированных документов
    chunks = _get_apply_time_decay()(chunks)

    logger.info(f"Retrieved {len(chunks)} chunks (with time-decay)")
    return {"retrieved_chunks": chunks}


def graph_expand(state: dict[str, Any]) -> dict[str, Any]:
    """
    Расширяет запрос с помощью графа знаний (Neo4j).
    Возвращает дополнительные сущности или связанные документы.
    """
    if not USE_GRAPH_EXPANSION:
        return {"graph_context": ""}

    query = state.get("rewritten_query") or state["query"]
    try:
        graph_results = _get_graph_expand_query()(query)
        context = f"\n\nСвязанные сущности из графа знаний:\n{graph_results}\n"
        logger.info("Graph expansion added")
        return {"graph_context": context}
    except Exception as e:
        logger.warning(f"Graph expansion failed: {e}")
        return {"graph_context": ""}


def check_sufficiency(state: dict[str, Any]) -> Literal["rewrite", "rerank"]:
    """
    Оценивает, достаточно ли релевантны извлечённые чанки.
    Если средний балл или покрытие низкое -> инициирует повторное переписывание.
    """
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        logger.info("No chunks retrieved, need rewrite")
        return "rewrite"

    # Простая эвристика: средний скор выше порога?
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)
    if avg_score < 0.6 and state.get("rewrite_count", 0) < MAX_RETRIEVAL_LOOPS:
        logger.info(f"Low average score {avg_score:.2f}, rewriting query")
        return "rewrite"

    logger.info(f"Sufficient context (avg_score={avg_score:.2f})")
    return "rerank"


def rerank(state: dict[str, Any]) -> dict[str, Any]:
    """
    Выполняет кросс-энкодер реранкинг извлечённых чанков.
    """
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {"reranked_chunks": []}

    query = state.get("rewritten_query") or state["query"]
    texts = [c["text"] for c in chunks]
    scores = [c["score"] for c in chunks]

    indices = _get_rerank_chunks()(query, texts, top_k=MAX_CHUNKS_AFTER_RERANK)
    reranked = [(chunks[i], scores[i]) for i in indices]

    # Дедупликация
    unique = _get_deduplicate_chunks()(reranked)
    logger.info(f"Reranked to {len(unique)} chunks")
    return {"reranked_chunks": unique}


def build_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Собирает финальный контекст из отреранжированных чанков и графового расширения.
    Применяет extractive-компрессию если контекст превышает токен-бюджет.
    """
    chunks_with_scores = state.get("reranked_chunks", [])
    graph_ctx = state.get("graph_context", "")
    query = state.get("rewritten_query") or state["query"]
    max_tokens = state.get("max_tokens", 120000)

    context = _get_build_context()(chunks_with_scores, max_tokens=max_tokens)

    # Оценка токенов и extractive-компрессия при превышении бюджета
    optimizer = TokenOptimizer()
    approx_tokens = optimizer.estimate_token_cost(context)
    if approx_tokens > max_tokens * 0.9 and chunks_with_scores:
        logger.info(f"Context ~{approx_tokens} tokens exceeds budget {max_tokens}, applying extractive compression")
        chunk_texts = [chunk.get("text", "") for chunk, _ in chunks_with_scores]
        compressed_text = optimizer.extractive_compress(chunk_texts, query, max_sentences=3)
        compressed_chunks = [(dict(chunk, text=compressed_text), score) for chunk, score in chunks_with_scores[:1]]
        context = _get_build_context()(compressed_chunks, max_tokens=max_tokens)

    if graph_ctx:
        context += graph_ctx

    logger.info(f"Context built, total length (chars): {len(context)}")
    return {"context": context, "sufficient": True}


def generate(state: dict[str, Any]) -> dict[str, Any]:
    """
    Генерация ответа с использованием контекста.
    Поддерживает как потоковый, так и обычный режим.
    """
    user_query = state["query"]
    context = state.get("context", "")
    temperature = state.get("temperature", 0.2)
    max_tokens = state.get("max_tokens", 4096)

    system_prompt = (
        "Ты – технический ассистент. Используй предоставленный контекст для ответа. "
        "Если контекст противоречив, укажи на противоречия. Если не знаешь, скажи честно.\n\n"
        f"Контекст:\n{context}"
    )
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}]

    answer = _get_non_stream_completion()(messages, temperature=temperature, max_tokens=max_tokens)
    logger.info(f"Generated answer length: {len(answer)}")
    return {"answer": answer}


def check_confidence(state: dict) -> dict:
    """Check confidence of generated answer and decide if escalation needed."""
    from proxy.app.core.confidence import compute_confidence
    from proxy.app.shared.config import (
        ADMIN_ALERT_ENABLED,
        CONFIDENCE_THRESHOLD,
        HALLUCINATION_CHECK_ENABLED,
        MAX_VERIFY_LOOPS,
        SELF_CRITIQUE_ENABLED,
    )

    answer = state.get("answer", "")
    context = state.get("context", "")
    query = state.get("rewritten_query") or state.get("query", "")
    rewrite_count = state.get("rewrite_count", 0)

    if not answer:
        return {"confidence": None, "needs_escalation": False, "needs_self_critique": False}

    if not HALLUCINATION_CHECK_ENABLED:
        return {"confidence": 0.7, "needs_escalation": False, "needs_self_critique": False}

    report = compute_confidence(query=query, context=context, answer=answer)

    needs_escalation = report.score < CONFIDENCE_THRESHOLD and rewrite_count < MAX_VERIFY_LOOPS
    needs_admin_alert = (
        report.score < CONFIDENCE_THRESHOLD and rewrite_count >= MAX_VERIFY_LOOPS and ADMIN_ALERT_ENABLED
    )

    if needs_admin_alert:
        logger.warning(f"Low confidence answer — admin alert: query='{query[:80]}...', score={report.score}")

    needs_self_critique = (
        SELF_CRITIQUE_ENABLED and answer.strip() and not needs_escalation and state.get("self_critique_count", 0) < 1
    )

    return {
        "confidence": report.score,
        "needs_escalation": needs_escalation,
        "escalation_reason": "; ".join(report.uncertainties) if needs_escalation else "",
        "needs_self_critique": needs_self_critique,
    }


def self_critique(state: dict) -> dict:
    """Rate the generated answer's usefulness and suggest improvement.

    Uses SLM to score the answer 1-5 on usefulness.
    If score < 3 and retry budget remains, sets needs_rewrite=True
    to trigger query rewrite and re-generation.

    Implements ISUSE pattern: Is the answer useful? Score → Escalate.
    """
    from proxy.app.llm.slm import _call_slm_sync

    answer = state.get("answer", "")
    query = state.get("rewritten_query") or state.get("query", "")
    rewrite_count = state.get("rewrite_count", 0)
    critique_count = state.get("self_critique_count", 0)
    max_rewrites = state.get("max_rewrites", 2)

    if not answer or not answer.strip():
        return {
            "self_critique_score": 0,
            "needs_rewrite": False,
            "self_critique_count": critique_count,
        }

    if rewrite_count >= max_rewrites:
        logger.info(f"Max rewrites ({max_rewrites}) reached, skipping self-critique")
        return {
            "self_critique_score": 3,
            "needs_rewrite": False,
            "self_critique_count": critique_count,
        }

    prompt = (
        f"Rate the following answer's usefulness on a scale of 1 to 5.\n"
        f"Consider: relevance, accuracy, completeness, clarity.\n"
        f"On a new line, write ONLY the integer score, then optionally one improvement suggestion.\n\n"
        f"User question: {query}\n\n"
        f"Answer: {answer}\n\n"
        f"Score (1-5):"
    )

    try:
        result = _call_slm_sync(prompt, max_tokens=50, temperature=0.0)
        score_text = result.strip() if result else "3"
        score = 3
        for char in score_text:
            if char.isdigit():
                score = max(1, min(5, int(char)))
                break

        needs_rewrite = score < 3 and rewrite_count < max_rewrites
        logger.info(f"Self-critique: score={score}, needs_rewrite={needs_rewrite}")

        return {
            "self_critique_score": score,
            "needs_rewrite": needs_rewrite,
            "self_critique_count": critique_count + 1,
        }
    except Exception as e:
        logger.warning(f"Self-critique call failed: {e}, accepting answer")
        return {
            "self_critique_score": 3,
            "needs_rewrite": False,
            "self_critique_count": critique_count + 1,
        }


def self_reflection(state: dict) -> dict:
    """Evaluate answer quality: is the answer fully supported by the context?

    Uses SLM to reflect on whether the generated answer is grounded in the
    retrieved context. If gaps are identified, triggers re-retrieval and
    re-generation (up to REFLECTION_DEPTH cycles).

    Multi-hop: for complex answers, verifies each piece independently,
    accumulating uncovered gaps for targeted re-retrieval.

    Config: REFLECTION_ENABLED, REFLECTION_DEPTH
    """
    from proxy.app.llm.slm import _call_slm_sync
    from proxy.app.shared.config import REFLECTION_DEPTH, REFLECTION_ENABLED

    answer = state.get("answer", "")
    context = state.get("context", "")
    query = state.get("rewritten_query") or state.get("query", "")
    reflection_count = state.get("reflection_count", 0)

    if not REFLECTION_ENABLED:
        return {"needs_reflection": False, "reflection_count": reflection_count}

    if not answer or not answer.strip():
        return {"needs_reflection": False, "reflection_count": reflection_count}

    if reflection_count >= REFLECTION_DEPTH:
        logger.info(f"Max reflection depth ({REFLECTION_DEPTH}) reached, accepting answer")
        return {"needs_reflection": False, "reflection_count": reflection_count}

    prompt = (
        f"You are an answer quality evaluator. Determine if the answer is fully supported by the context.\n"
        f"Reply with ONLY one of these exact words: FULLY_SUPPORTED, PARTIALLY_SUPPORTED, or NOT_SUPPORTED.\n"
        f"If PARTIALLY_SUPPORTED or NOT_SUPPORTED, on the next line write: MISSING: <what information is missing>\n\n"
        f"User question: {query}\n\n"
        f"Context:\n{context}\n\n"
        f"Answer: {answer}\n\n"
        f"Evaluation:"
    )

    try:
        result = _call_slm_sync(prompt, max_tokens=100, temperature=0.0)
        response_text = result.strip().upper() if result else ""
        logger.info(f"Self-reflection result: '{response_text[:120]}'")

        is_fully_supported = response_text.startswith("FULLY_SUPPORTED")

        if not is_fully_supported:
            missing_info = ""
            if "MISSING:" in response_text:
                missing_info = response_text.split("MISSING:", 1)[1].strip() if "MISSING:" in response_text else ""
            logger.info(f"Self-reflection: gaps identified. Missing info: '{missing_info[:80]}'. Re-retrieving.")
            return {
                "needs_reflection": True,
                "reflection_count": reflection_count + 1,
                "reflection_gaps": missing_info,
            }

        logger.info("Self-reflection: answer fully supported")
        return {"needs_reflection": False, "reflection_count": reflection_count + 1}

    except Exception as e:
        logger.warning(f"Self-reflection call failed: {e}, accepting answer")
        return {"needs_reflection": False, "reflection_count": reflection_count + 1}


def call_tools(state: dict[str, Any]) -> dict[str, Any]:
    """Execute tool calls requested by the LLM and collect results."""
    from proxy.app.tools import get_tool_registry, handle_function_call

    tool_calls = state.get("tool_calls", [])
    tool_results = state.get("tool_results", [])
    tool_loop_count = state.get("tool_loop_count", 0)

    registry = get_tool_registry()

    for tc in tool_calls:
        try:
            result = handle_function_call(tc, registry)
            tool_results.append(
                {
                    "tool_call_id": tc.get("id", result.tool_call_id),
                    "name": result.name,
                    "content": result.content,
                    "error": result.error,
                }
            )
            logger.info("Tool %s executed successfully", result.name)
        except Exception as e:
            func_name = tc.get("function", {}).get("name", "")
            logger.warning("Tool %s failed: %s", func_name, e)
            tool_results.append(
                {
                    "tool_call_id": tc.get("id", ""),
                    "name": func_name,
                    "content": f"Error: {e}",
                    "error": str(e),
                }
            )

    return {
        "tool_results": tool_results,
        "tool_loop_count": tool_loop_count + 1,
        "tool_calls": [],  # Clear for next iteration
    }
