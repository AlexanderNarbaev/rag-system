# tests/conftest.py
"""Shared fixtures for RAG system integration tests."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def sample_chunks():
    """Sample chunks representing results from different sources with versioning."""
    return [
        {
            "text": "RAG (Retrieval-Augmented Generation) — техника, объединяющая LLM с внешней базой знаний.",
            "hash": "hash_confluence_v1_1",
            "title": "RAG Overview",
            "source_type": "confluence",
            "source_id": "confluence_123",
            "version": "1.0",
            "doc_title": "Архитектура RAG",
            "keywords": ["RAG", "LLM", "retrieval"],
            "entities": ["LLM", "RAG"],
            "summary": "RAG объединяет LLM с базой знаний.",
            "position": 0,
            "semantic_key": "rag_overview",
        },
        {
            "text": "RAG (Retrieval-Augmented Generation) — updated: combines retrieval with generation for accurate "
            "responses.",
            "hash": "hash_confluence_v2_1",
            "title": "RAG Overview",
            "source_type": "confluence",
            "source_id": "confluence_123",
            "version": "2.0",
            "doc_title": "Архитектура RAG",
            "keywords": ["RAG", "LLM", "retrieval", "generation"],
            "entities": ["LLM", "RAG"],
            "summary": "Updated RAG overview.",
            "position": 0,
            "semantic_key": "rag_overview",
        },
        {
            "text": "Для настройки CI/CD pipeline необходимо создать файл .gitlab-ci.yml в корне репозитория.",
            "hash": "hash_gitlab_mr_1",
            "title": "CI/CD Setup",
            "source_type": "gitlab_merge_request",
            "source_id": "gitlab_mr_42",
            "version": "latest",
            "doc_title": "CI/CD Configuration Guide",
            "keywords": ["CI/CD", "GitLab", "pipeline"],
            "entities": ["GitLab", "CI/CD"],
            "summary": "CI/CD pipeline setup instructions.",
            "position": 0,
            "semantic_key": "cicd_setup",
        },
        {
            "text": "Задача PROJ-123: Интеграция RAG с корпоративным поиском. Приоритет: High.",
            "hash": "hash_jira_v1_1",
            "title": "Интеграция RAG",
            "source_type": "jira",
            "source_id": "jira_PROJ-123",
            "version": "1.5",
            "doc_title": "PROJ-123",
            "keywords": ["RAG", "интеграция", "поиск"],
            "entities": ["RAG", "интеграция"],
            "summary": "Jira task for RAG integration.",
            "position": 0,
            "semantic_key": "jira_proj123",
        },
        {
            "text": "GitLab commit a1b2c3d: Added hybrid search module using Qdrant.",
            "hash": "hash_gitlab_commit_1",
            "title": "hybrid search commit",
            "source_type": "gitlab_commit",
            "source_id": "gitlab_commit_a1b2c3d",
            "version": "latest",
            "doc_title": "Commit a1b2c3d",
            "keywords": ["hybrid", "search", "Qdrant"],
            "entities": ["Qdrant"],
            "summary": "Added hybrid search module.",
            "position": 0,
            "semantic_key": "gitlab_commit",
        },
    ]


@pytest.fixture
def sample_search_results(sample_chunks):
    """Mocked Qdrant ScoredPoint search results."""

    class ScoredPoint:
        def __init__(self, id, score, payload):
            self.id = id
            self.score = score
            self.payload = payload

    results = []
    for i, chunk in enumerate(sample_chunks):
        results.append(ScoredPoint(id=chunk["hash"], score=0.95 - i * 0.05, payload=chunk.copy()))
    return results


@pytest.fixture
def mock_qdrant_client():
    """Mocked QdrantClient for testing."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock()
    client.search.return_value = []
    client.upsert.return_value = None
    return client


@pytest.fixture
def mock_sentence_transformer():
    """Mocked SentenceTransformer embedding generation."""
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        instance = mock_st.return_value
        instance.encode.return_value = type("obj", (object,), {"tolist": lambda: [0.1] * 1024})()
        instance.encode_sparse.return_value = {
            "indices": [1, 5, 10],
            "values": [0.5, 0.3, 0.2],
        }
        yield mock_st


@pytest.fixture
def mock_http_requests():
    """Mocked requests library for HTTP calls."""
    with (
        patch("requests.get") as mock_get,
        patch("requests.post") as mock_post,
        patch("requests.Session") as mock_session,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "Mocked response"}}]}
        mock_resp.text = json.dumps({"choices": [{"message": {"content": "Mocked response"}}]})
        mock_get.return_value = mock_resp
        mock_post.return_value = mock_resp
        yield {"get": mock_get, "post": mock_post, "session": mock_session}


@pytest.fixture
def sample_documents():
    """Test documents in Confluence, Jira, and GitLab formats."""
    return {
        "confluence": {
            "id": "12345",
            "title": "RAG Architecture Guide",
            "space": "DEV",
            "version": 2,
            "created_at": "2025-01-15T10:00:00",
            "updated_at": "2025-06-20T14:00:00",
            "body_storage_raw": "<h1>RAG Architecture</h1><p>RAG combines retrieval and generation.</p>",
            "body_view_html": "<h1>RAG Architecture</h1><p>RAG combines retrieval and generation.</p>",
        },
        "jira": {
            "key": "PROJ-123",
            "summary": "Интеграция RAG с поиском",
            "description": "Необходимо интегрировать RAG систему с корпоративным поиском.",
            "status": "In Progress",
            "priority": "High",
            "assignee": "ivanov",
            "comments": [{"author": "petrov", "body": "Начал разработку."}],
        },
        "gitlab": {
            "id": "a1b2c3d4e5f6",
            "title": "Add hybrid search module",
            "message": "Added hybrid search module using Qdrant with dense and sparse vectors.",
            "author_name": "ivanov",
            "created_at": "2025-06-18T12:00:00",
        },
    }


@pytest.fixture
def mock_cache_manager():
    """Mocked CacheManager (in-memory, no Redis)."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    cache.clear = AsyncMock()
    cache.close = AsyncMock()
    cache.get_sync.return_value = None
    cache.set_sync.return_value = True
    return cache


@pytest.fixture
def mock_non_stream_completion():
    """Mock for non_stream_completion returning a pre-defined answer."""
    with patch("proxy.app.llm.router.non_stream_completion") as mock:

        async def _mock_fn(*args, **kwargs):
            return (
                "На основе предоставленного контекста: RAG — это техника объединения LLM с внешней базой знаний для "
                "повышения точности ответов."
            )

        mock.side_effect = _mock_fn
        yield mock


@pytest.fixture
def mock_stream_completion():
    """Mock for stream_completion returning SSE chunks."""
    with patch("proxy.app.llm.router.stream_completion") as mock:

        async def _mock_stream(*args, **kwargs):
            chunks = [
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": "RAG "}, "index": 0}],
                },
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": "это "}, "index": 0}],
                },
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": "техника."}, "index": 0}],
                },
            ]
            for chunk in chunks:
                yield chunk

        mock.side_effect = _mock_stream
        yield mock


def pytest_collection_modifyitems(config, items):
    """Skip minikube tests unless RAG_PROXY_URL is set."""
    import os

    if not os.getenv("RAG_PROXY_URL"):
        skip_marker = pytest.mark.skip(reason="RAG_PROXY_URL not set")
        for item in items:
            if "minikube" in item.nodeid:
                item.add_marker(skip_marker)
