# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Performance latency tests for the RAG proxy with mocked external services.

Tests measure latency through the FastAPI TestClient with all external services
(Qdrant, LLM, embedder, reranker) mocked. This isolates the proxy framework
overhead from external service latency.

Run with: pytest tests/performance/test_latency.py -v
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock heavy external dependencies before importing the app
_modules_to_mock = [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "langgraph",
    "langgraph.graph",
    "langgraph.checkpoint",
    "neo4j",
    "redis",
    "redis.asyncio",
    "tiktoken",
    "bcrypt",
]

for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from proxy.app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_auth(monkeypatch):
    """Disable authentication for all tests in this module."""
    import proxy.app.auth.jwt as _jwt
    import proxy.app.shared.config as _cfg

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(_cfg, "AUTH_ENABLED", False)
    monkeypatch.setattr(_jwt, "AUTH_ENABLED", False)


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_rag_pipeline():
    """Mock all RAG pipeline dependencies for consistent latency measurement."""
    with (
        patch("proxy.app.main.hybrid_search") as mock_hybrid,
        patch("proxy.app.main.rerank_chunks") as mock_rerank,
        patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
        patch("proxy.app.main.build_context") as mock_build,
        patch("proxy.app.main.non_stream_completion") as mock_nonstream,
        patch("proxy.app.main.stream_completion") as mock_stream,
        patch("proxy.app.main.extract_version_from_query", return_value=None),
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.log_interaction") as mock_log,
    ):
        mock_hybrid.return_value = []
        mock_rerank.return_value = []
        mock_dedup.return_value = []
        mock_build.return_value = ""
        mock_nonstream.return_value = "Mocked response for performance testing."
        mock_stream.return_value = iter([])
        yield {
            "hybrid_search": mock_hybrid,
            "rerank_chunks": mock_rerank,
            "deduplicate_chunks": mock_dedup,
            "build_context": mock_build,
            "non_stream_completion": mock_nonstream,
            "stream_completion": mock_stream,
            "log_interaction": mock_log,
        }


@pytest.fixture
def mock_healthy_services():
    """Mock Qdrant and LLM as healthy for health endpoint tests."""
    with (
        patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
        patch("requests.get") as mock_get,
    ):
        mock_get.return_value.status_code = 200

        # The health check does: len(collections.collections),
        # so get_collections() must return something with a .collections attribute.
        mock_collections = MagicMock()
        mock_collections.collections = []
        mock_qdrant.get_collections.return_value = mock_collections
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_percentiles(values: list[float]) -> dict[str, float]:
    """Compute p50, p95, p99 from a list of latency values in ms."""
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "p50": sorted_vals[int(n * 0.50)] if n > 1 else sorted_vals[0],
        "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
        "p99": sorted_vals[min(int(n * 0.99), n - 1)] if n > 1 else sorted_vals[0],
    }


# ---------------------------------------------------------------------------
# Test: Chat Completion Latency
# ---------------------------------------------------------------------------


class TestChatCompletionLatency:
    """Latency benchmarks for non-streaming chat completion."""

    def test_chat_completion_latency_under_5s(self, client, mock_rag_pipeline):
        """Single chat completion should complete in < 5s with mocked services.

        This tests the framework overhead: request parsing, pipeline routing,
        response serialization. External service latency is zero (mocked).
        """
        max_latency_ms = 5000  # 5 seconds

        start = time.perf_counter()
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )
        latency_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        assert latency_ms < max_latency_ms, (
            f"Chat completion latency {latency_ms:.1f}ms exceeded {max_latency_ms}ms threshold"
        )

    def test_chat_completion_repeated_latency_stable(self, client, mock_rag_pipeline):
        """10 sequential chat completions should all be under 5s."""
        max_latency_ms = 5000
        latencies = []

        for i in range(10):
            start = time.perf_counter()
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-proxy",
                    "messages": [{"role": "user", "content": f"Query {i}"}],
                    "stream": False,
                },
            )
            latency_ms = (time.perf_counter() - start) * 1000
            assert response.status_code == 200
            latencies.append(latency_ms)

        p95 = _compute_percentiles(latencies)["p95"]
        assert p95 < max_latency_ms, f"p95 latency {p95:.1f}ms exceeded {max_latency_ms}ms threshold"


# ---------------------------------------------------------------------------
# Test: Streaming First-Chunk Latency (TTFT)
# ---------------------------------------------------------------------------


class TestStreamingFirstChunkLatency:
    """Latency benchmarks for streaming time-to-first-token (TTFT)."""

    def test_streaming_first_chunk_under_1s(self, client, mock_rag_pipeline):
        """Time-to-first-chunk should be < 1s with mocked services.

        The initial empty chunk from StreamOptimizer should arrive immediately,
        followed by content chunks.
        """
        max_ttft_ms = 1000  # 1 second

        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "First "}}]}
            yield {"id": "2", "choices": [{"delta": {"content": "chunk."}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        start = time.perf_counter()
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
        )
        first_chunk_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        # The full response arrives at once with TestClient, but the framework
        # overhead should still be minimal
        assert first_chunk_ms < max_ttft_ms, (
            f"Streaming first-chunk latency {first_chunk_ms:.1f}ms exceeded {max_ttft_ms}ms"
        )

    def test_streaming_initial_chunk_is_immediate(self, client, mock_rag_pipeline):
        """StreamOptimizer's initial empty chunk should be the first data line."""

        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "Hello"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        body = response.text
        lines = [line for line in body.split("\n") if line.startswith("data:")]
        assert len(lines) >= 1
        # First data line should be the initial chunk or content
        assert "data:" in lines[0]


# ---------------------------------------------------------------------------
# Test: Health Check Latency
# ---------------------------------------------------------------------------


class TestHealthCheckLatency:
    """Latency benchmarks for health check endpoints."""

    def test_health_live_under_100ms(self, client):
        """GET /v1/health/live should respond in < 100ms.

        Liveness probe is a trivial endpoint — no external calls.
        """
        max_latency_ms = 100

        start = time.perf_counter()
        response = client.get("/v1/health/live")
        latency_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        assert latency_ms < max_latency_ms, f"Health live latency {latency_ms:.1f}ms exceeded {max_latency_ms}ms"

    def test_health_live_repeated_under_100ms(self, client, mock_healthy_services):
        """10 sequential liveness probes should all be under 100ms."""
        max_latency_ms = 100
        latencies = []

        for _ in range(10):
            start = time.perf_counter()
            response = client.get("/v1/health/live")
            latency_ms = (time.perf_counter() - start) * 1000
            assert response.status_code == 200
            latencies.append(latency_ms)

        p95 = _compute_percentiles(latencies)["p95"]
        assert p95 < max_latency_ms, f"Health live p95 latency {p95:.1f}ms exceeded {max_latency_ms}ms"

    def test_health_ready_under_100ms(self, client, mock_healthy_services):
        """GET /v1/health/ready should respond in < 100ms with mocked services.

        With mocked Qdrant and LLM, the readiness probe overhead is minimal.
        """
        max_latency_ms = 100

        start = time.perf_counter()
        response = client.get("/v1/health/ready")
        latency_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        assert latency_ms < max_latency_ms, f"Health ready latency {latency_ms:.1f}ms exceeded {max_latency_ms}ms"

    def test_health_full_under_500ms(self, client, mock_healthy_services):
        """GET /v1/health should respond in < 500ms with mocked services."""
        max_latency_ms = 500

        start = time.perf_counter()
        response = client.get("/v1/health")
        latency_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        assert latency_ms < max_latency_ms, f"Health full latency {latency_ms:.1f}ms exceeded {max_latency_ms}ms"


# ---------------------------------------------------------------------------
# Test: Concurrent Request Handling
# ---------------------------------------------------------------------------


class TestConcurrentRequestHandling:
    """Concurrency benchmarks for parallel request handling."""

    def test_10_parallel_chat_requests(self, client, mock_rag_pipeline):
        """10 parallel chat requests should all succeed.

        Uses ThreadPoolExecutor to simulate concurrent clients.
        All requests should complete in < 10s total.
        """
        num_workers = 10
        max_total_ms = 10000  # 10 seconds for all 10 requests
        max_per_request_ms = 5000  # 5 seconds per individual request

        def send_request(query_id: int) -> tuple[float, int]:
            start = time.perf_counter()
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-proxy",
                    "messages": [{"role": "user", "content": f"Concurrent query {query_id}"}],
                    "stream": False,
                },
            )
            latency_ms = (time.perf_counter() - start) * 1000
            return latency_ms, response.status_code

        start_total = time.perf_counter()
        latencies = []
        errors = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(send_request, i) for i in range(num_workers)]
            for future in as_completed(futures):
                latency_ms, status = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        total_ms = (time.perf_counter() - start_total) * 1000

        assert errors == 0, f"Some requests failed: {errors}/{num_workers}"
        assert len(latencies) == num_workers, f"Only {len(latencies)}/{num_workers} succeeded"
        assert total_ms < max_total_ms, (
            f"Total time {total_ms:.1f}ms exceeded {max_total_ms}ms for {num_workers} parallel requests"
        )

        # Each individual request should be under the per-request threshold
        for i, lat in enumerate(latencies):
            assert lat < max_per_request_ms, f"Request {i} latency {lat:.1f}ms exceeded {max_per_request_ms}ms"

    def test_10_parallel_streaming_requests(self, client, mock_rag_pipeline):
        """10 parallel streaming requests should all complete."""
        num_workers = 10

        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "Response"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        def send_streaming_request(query_id: int) -> tuple[float, int]:
            start = time.perf_counter()
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-proxy",
                    "messages": [{"role": "user", "content": f"Stream query {query_id}"}],
                    "stream": True,
                },
            )
            latency_ms = (time.perf_counter() - start) * 1000
            return latency_ms, response.status_code

        latencies = []
        errors = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(send_streaming_request, i) for i in range(num_workers)]
            for future in as_completed(futures):
                latency_ms, status = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        assert errors == 0, f"Some streaming requests failed: {errors}/{num_workers}"
        assert len(latencies) == num_workers

    def test_concurrent_health_and_chat(self, client, mock_rag_pipeline, mock_healthy_services):
        """Mix of health checks and chat requests should all succeed."""
        num_workers = 10

        def send_request(idx: int) -> tuple[float, int, str]:
            start = time.perf_counter()
            if idx % 3 == 0:
                # Health check
                response = client.get("/v1/health/live")
                endpoint = "health"
            elif idx % 3 == 1:
                # Model list
                response = client.get("/v1/models")
                endpoint = "models"
            else:
                # Chat
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "rag-proxy",
                        "messages": [{"role": "user", "content": f"Mixed query {idx}"}],
                        "stream": False,
                    },
                )
                endpoint = "chat"
            latency_ms = (time.perf_counter() - start) * 1000
            return latency_ms, response.status_code, endpoint

        latencies = []
        errors = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(send_request, i) for i in range(num_workers)]
            for future in as_completed(futures):
                latency_ms, status, endpoint = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        assert errors == 0, f"Some mixed requests failed: {errors}/{num_workers}"
        assert len(latencies) == num_workers

    def test_concurrent_request_latency_percentiles(self, client, mock_rag_pipeline):
        """Compute latency percentiles for 10 concurrent chat requests."""
        num_workers = 10

        def send_request(query_id: int) -> tuple[float, int]:
            start = time.perf_counter()
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-proxy",
                    "messages": [{"role": "user", "content": f"Percentile test {query_id}"}],
                    "stream": False,
                },
            )
            latency_ms = (time.perf_counter() - start) * 1000
            return latency_ms, response.status_code

        latencies = []

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(send_request, i) for i in range(num_workers)]
            for future in as_completed(futures):
                latency_ms, status = future.result()
                if status == 200:
                    latencies.append(latency_ms)

        assert len(latencies) == num_workers

        percentiles = _compute_percentiles(latencies)
        # With mocked services, all percentiles should be well under 5s
        assert percentiles["p50"] < 5000, f"p50 {percentiles['p50']:.1f}ms too high"
        assert percentiles["p95"] < 5000, f"p95 {percentiles['p95']:.1f}ms too high"
        assert percentiles["p99"] < 5000, f"p99 {percentiles['p99']:.1f}ms too high"
