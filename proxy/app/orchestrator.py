# proxy/app/orchestrator.py
"""
Агентная оркестрация RAG-пайплайна с использованием LangGraph.
Реализует циклы:
1. Переписывание запроса (rewrite)
2. Гибридный поиск (retrieve)
3. Оценка достаточности (check_sufficiency) -> если недостаточно, повторный rewrite/retrieve
4. Графовое расширение (graph_expand) – опционально
5. Реранкинг (rerank)
6. Генерация ответа (generate)
"""
import logging
from typing import TypedDict, List, Dict, Any, Optional, Literal, Annotated
from datetime import datetime

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

# Импорт модулей RAG
from app.config import (
    MAX_CHUNKS_RETRIEVAL, MAX_CHUNKS_AFTER_RERANK,
    USE_GRAPH_EXPANSION, MAX_RETRIEVAL_LOOPS
)
from app.retrieval import hybrid_search, graph_expand_query
from app.rerank import rerank_chunks
from app.context_builder import deduplicate_chunks, build_context, extract_version_from_query
from app.llm_router import non_stream_completion, stream_completion

logger = logging.getLogger(__name__)


class RAGState(TypedDict):
    """Состояние графа RAG."""
    query: str
    version: Optional[str]
    rewritten_query: Optional[str]
    rewrite_count: int
    retrieved_chunks: List[Dict[str, Any]]
    reranked_chunks: List[Dict[str, Any]]
    graph_context: Optional[str]
    context: str
    answer: str
    sufficient: bool
    temperature: float
    max_tokens: int
    stream: bool


def rewrite_query(state: RAGState) -> Dict[str, Any]:
    """
    Переписывает запрос с помощью LLM для улучшения ретривала.
    Используется при первом входе или когда контекст признан недостаточным.
    """
    query = state["query"]
    rewrite_count = state.get("rewrite_count", 0)
    
    if rewrite_count >= MAX_RETRIEVAL_LOOPS:
        logger.warning(f"Max rewrite loops reached ({MAX_RETRIEVAL_LOOPS}), using original query")
        return {"rewritten_query": query, "rewrite_count": rewrite_count}
    
    prompt = f"""Перепиши следующий вопрос пользователя в более эффективный поисковый запрос для технической документации. 
Сохрани все ключевые сущности (номера задач, технологии, имена). 
Выдай только переписанный запрос, без пояснений.

Оригинальный вопрос: {query}

Переписанный запрос:"""
    
    try:
        rewritten = non_stream_completion([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=100)
        rewritten = rewritten.strip()
        logger.info(f"Rewritten query: '{query}' -> '{rewritten}'")
        return {"rewritten_query": rewritten, "rewrite_count": rewrite_count + 1}
    except Exception as e:
        logger.error(f"Rewrite failed: {e}, using original")
        return {"rewritten_query": query, "rewrite_count": rewrite_count + 1}


def retrieve(state: RAGState) -> Dict[str, Any]:
    """
    Выполняет гибридный поиск в Qdrant.
    Использует переписанный запрос, если есть, иначе оригинальный.
    """
    query_to_use = state.get("rewritten_query") or state["query"]
    version = state.get("version")
    
    logger.info(f"Retrieving for: '{query_to_use}' (version: {version})")
    results = hybrid_search(query=query_to_use, version=version, top_k=MAX_CHUNKS_RETRIEVAL)
    
    # Преобразуем результаты в список словарей для единообразия
    chunks = []
    for hit in results:
        chunks.append({
            "id": hit.id,
            "text": hit.payload.get("text", ""),
            "score": hit.score,
            "payload": hit.payload
        })
    
    logger.info(f"Retrieved {len(chunks)} chunks")
    return {"retrieved_chunks": chunks}


def graph_expand(state: RAGState) -> Dict[str, Any]:
    """
    Расширяет запрос с помощью графа знаний (Neo4j).
    Возвращает дополнительные сущности или связанные документы.
    """
    if not USE_GRAPH_EXPANSION:
        return {"graph_context": ""}
    
    query = state.get("rewritten_query") or state["query"]
    try:
        graph_results = graph_expand_query(query)
        context = f"\n\nСвязанные сущности из графа знаний:\n{graph_results}\n"
        logger.info("Graph expansion added")
        return {"graph_context": context}
    except Exception as e:
        logger.warning(f"Graph expansion failed: {e}")
        return {"graph_context": ""}


def check_sufficiency(state: RAGState) -> Literal["rewrite", "rerank"]:
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
    
    # Альтернатива: проверяем, содержит ли топ-3 чанк хоть какие-то ключевые слова из запроса
    # (можно сделать через LLM-классификатор, но для скорости – эвристика)
    logger.info(f"Sufficient context (avg_score={avg_score:.2f})")
    return "rerank"


def rerank(state: RAGState) -> Dict[str, Any]:
    """
    Выполняет кросс-энкодер реранкинг извлечённых чанков.
    """
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {"reranked_chunks": []}
    
    query = state.get("rewritten_query") or state["query"]
    texts = [c["text"] for c in chunks]
    scores = [c["score"] for c in chunks]
    
    indices = rerank_chunks(query, texts, top_k=MAX_CHUNKS_AFTER_RERANK)
    reranked = [(chunks[i], scores[i]) for i in indices]
    
    # Дедупликация
    unique = deduplicate_chunks(reranked)
    logger.info(f"Reranked to {len(unique)} chunks")
    return {"reranked_chunks": unique}


def build_context_node(state: RAGState) -> Dict[str, Any]:
    """
    Собирает финальный контекст из отреранжированных чанков и графового расширения.
    """
    chunks_with_scores = state.get("reranked_chunks", [])
    graph_ctx = state.get("graph_context", "")
    
    context = build_context(chunks_with_scores, max_tokens=120000)
    if graph_ctx:
        context += graph_ctx
    
    logger.info(f"Context built, total length (chars): {len(context)}")
    return {"context": context, "sufficient": True}


def generate(state: RAGState) -> Dict[str, Any]:
    """
    Генерация ответа с использованием контекста.
    Поддерживает как потоковый, так и обычный режим.
    """
    user_query = state["query"]
    context = state.get("context", "")
    temperature = state.get("temperature", 0.2)
    max_tokens = state.get("max_tokens", 4096)
    stream = state.get("stream", False)
    
    system_prompt = (
        "Ты – технический ассистент. Используй предоставленный контекст для ответа. "
        "Если контекст противоречив, укажи на противоречия. Если не знаешь, скажи честно.\n\n"
        f"Контекст:\n{context}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    # Note: streaming is handled at the main.py level, not inside LangGraph
    answer = non_stream_completion(messages, temperature=temperature, max_tokens=max_tokens)
    logger.info(f"Generated answer length: {len(answer)}")
    return {"answer": answer}


# Строим граф
def build_rag_graph() -> StateGraph:
    """Создаёт и компилирует граф RAG."""
    builder = StateGraph(RAGState)
    
    # Добавляем узлы
    builder.add_node("rewrite", rewrite_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("graph_expand", graph_expand)
    builder.add_node("rerank", rerank)
    builder.add_node("build_context", build_context_node)
    builder.add_node("generate", generate)
    builder.add_node("check_sufficiency", check_sufficiency)
    
    # Начало
    builder.set_entry_point("rewrite")
    
    # Переходы
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("retrieve", "check_sufficiency")
    
    # Условное ребро после проверки
    builder.add_conditional_edges(
        "check_sufficiency",
        check_sufficiency,
        {
            "rewrite": "rewrite",
            "rerank": "rerank"
        }
    )
    
    builder.add_edge("build_context", "generate")
    builder.add_edge("generate", END)
    
    # Добавляем графовое расширение как опциональный узел между rerank и build_context
    # В текущей архитектуре: retrieve -> check_sufficiency -> rerank -> graph_expand -> build_context
    builder.add_edge("rerank", "graph_expand")
    builder.add_edge("graph_expand", "build_context")
    
    return builder


class RAGOrchestrator:
    """Обёртка над скомпилированным графом."""
    def __init__(self, checkpointer=None):
        self.builder = build_rag_graph()
        self.graph = self.builder.compile(checkpointer=checkpointer or MemorySaver())
    
    async def ainvoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Асинхронный вызов графа."""
        # Поскольку LangGraph поддерживает async, используем.
        # Но для синхронного вызова можно invoke.
        return await self.graph.ainvoke(inputs)
    
    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Синхронный вызов графа."""
        return self.graph.invoke(inputs)


# Функция для получения экземпляра оркестратора (синглтон)
_orchestrator = None

def get_orchestrator() -> RAGOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RAGOrchestrator()
    return _orchestrator