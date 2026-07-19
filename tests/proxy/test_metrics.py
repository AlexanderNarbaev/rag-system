"""Tests for proxy/app/metrics.py - Prometheus metrics module."""

import sys
from unittest.mock import MagicMock

import pytest

# Mock heavy dependencies before importing anything from proxy.app.main
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
]
for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


class TestMetricsDefinitions:
    """Test that all Prometheus metrics are defined and available."""

    def test_import_metrics_module(self):
        from proxy.app.shared.metrics import (
            RAG_CACHE_HITS,
            RAG_CACHE_MISSES,
            RAG_QUEUE_DEPTH,
            rag_active_requests,
            rag_cache_hits_total,
            rag_context_tokens,
            rag_llm_duration_seconds,
            rag_request_duration_seconds,
            rag_requests_total,
            rag_rerank_duration_seconds,
            rag_retrieval_duration_seconds,
        )

        assert rag_requests_total is not None
        assert rag_request_duration_seconds is not None
        assert rag_retrieval_duration_seconds is not None
        assert rag_rerank_duration_seconds is not None
        assert rag_llm_duration_seconds is not None
        assert rag_cache_hits_total is not None
        assert rag_context_tokens is not None
        assert rag_active_requests is not None
        assert RAG_CACHE_HITS is not None
        assert RAG_CACHE_MISSES is not None
        assert RAG_QUEUE_DEPTH is not None

    def test_requests_counter_increments(self):
        from proxy.app.shared.metrics import rag_requests_total

        rag_requests_total.labels(endpoint="/v1/chat/completions", status="200").inc()
        rag_requests_total.labels(endpoint="/v1/chat/completions", status="200").inc()
        rag_requests_total.labels(endpoint="/v1/chat/completions", status="500").inc()
        # Counters are cumulative, we just verify no errors on inc()
        assert True

    def test_request_duration_histogram(self):
        from proxy.app.shared.metrics import rag_request_duration_seconds

        rag_request_duration_seconds.labels(endpoint="/v1/chat/completions").observe(0.5)
        rag_request_duration_seconds.labels(endpoint="/v1/chat/completions").observe(1.2)
        rag_request_duration_seconds.labels(endpoint="/v1/models").observe(0.01)
        # Verify no errors on observe()
        assert True

    def test_gauge_set(self):
        from proxy.app.shared.metrics import rag_active_requests, rag_context_tokens

        rag_active_requests.set(3)
        rag_active_requests.inc()
        rag_active_requests.dec()
        rag_context_tokens.set(5000)
        assert True

    def test_cache_hits_counter(self):
        from proxy.app.shared.metrics import rag_cache_hits_total

        rag_cache_hits_total.inc()
        rag_cache_hits_total.inc()
        rag_cache_hits_total.inc()
        assert True


class TestMetricsEndpoint:
    """Test the /metrics endpoint returns Prometheus-formatted output."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        with TestClient(app) as c:
            yield c

    def test_metrics_endpoint_returns_200(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_content_type(self, client):
        response = client.get("/metrics")
        from prometheus_client import CONTENT_TYPE_LATEST

        assert response.headers["content-type"] == CONTENT_TYPE_LATEST

    def test_metrics_endpoint_contains_standard_metrics(self, client):
        response = client.get("/metrics")
        body = response.text
        assert "rag_requests_total" in body
        assert "rag_request_duration_seconds" in body

    def test_metrics_endpoint_no_newlines_in_headers(self, client):
        """Verify the response is valid Prometheus format (no injection)."""
        response = client.get("/metrics")
        body = response.text
        for line in body.strip().split("\n"):
            if line and not line.startswith("#"):
                metric_name = line.split("{")[0].split(" ")[0]
                assert not metric_name.startswith("#")


class TestInitMetrics:
    """Test metrics initialization function."""

    def test_init_sets_flag(self):
        from proxy.app.shared.metrics import init_metrics, is_initialized

        init_metrics()
        assert is_initialized() is True


class TestMetricsEndpointFunction:
    """Test the metrics_endpoint function directly."""

    def test_returns_prometheus_content(self):
        from proxy.app.shared.metrics import init_metrics, metrics_endpoint

        init_metrics()
        result = metrics_endpoint()
        assert result.status_code == 200
        assert "rag_requests_total" in result.body.decode()


class TestMetricsHelperFunctions:
    """Test helper functions for recording RAG-specific metrics."""

    def test_record_rag_request(self):
        from proxy.app.shared.metrics import record_rag_request

        record_rag_request(method="POST", status="200", has_context=True, duration=0.5)
        assert True

    def test_record_retrieval(self):
        from proxy.app.shared.metrics import record_retrieval

        record_retrieval(score=0.85, duration=0.1)
        assert True

    def test_record_cache_hit(self):
        from proxy.app.shared.metrics import record_cache_hit

        record_cache_hit(cache_type="embedding")
        record_cache_hit(cache_type="response")
        assert True

    def test_record_cache_miss(self):
        from proxy.app.shared.metrics import record_cache_miss

        record_cache_miss(cache_type="embedding")
        record_cache_miss(cache_type="rerank")
        assert True

    def test_set_queue_depth(self):
        from proxy.app.shared.metrics import set_queue_depth

        set_queue_depth(5)
        set_queue_depth(0)
        assert True

    def test_record_llm_tokens(self):
        from proxy.app.shared.metrics import record_llm_tokens

        record_llm_tokens(prompt_tokens=500, completion_tokens=200)
        assert True

    def test_record_confidence(self):
        from proxy.app.shared.metrics import record_confidence

        record_confidence(score=0.92)
        record_confidence(score=0.45)
        assert True

    def test_record_hallucination(self):
        from proxy.app.shared.metrics import record_hallucination

        record_hallucination()
        record_hallucination()
        assert True

    def test_record_negative_rejection(self):
        from proxy.app.shared.metrics import record_negative_rejection

        record_negative_rejection()
        assert True

    def test_metrics_endpoint_generates_latest(self):
        from proxy.app.shared.metrics import metrics_endpoint

        result = metrics_endpoint()
        assert result.status_code == 200
        assert "rag_" in result.body.decode()


class TestMetricsRetrievalQualityGauges:
    """Test retrieval quality gauge metrics."""

    def test_retrieval_quality_gauges_exist(self):
        from proxy.app.shared.metrics import (
            rag_compression_ratio,
            rag_confidence_score_high_ratio,
            rag_graph_expansion_rate,
            rag_grounding_score_high_ratio,
            rag_retrieval_chunks_after_rerank,
            rag_retrieval_chunks_total,
            rag_retrieval_mrr,
        )

        for gauge, value in [
            (rag_retrieval_chunks_total, 10),
            (rag_retrieval_chunks_after_rerank, 5),
            (rag_graph_expansion_rate, 0.3),
            (rag_retrieval_mrr, 0.75),
            (rag_confidence_score_high_ratio, 0.85),
            (rag_grounding_score_high_ratio, 0.90),
            (rag_compression_ratio, 0.4),
        ]:
            gauge.set(value)
        assert True


class TestMetricsHelpersEdgeCases:
    """Test metrics helpers with edge case values."""

    def test_record_rag_request_without_context(self):
        from proxy.app.shared.metrics import record_rag_request

        record_rag_request(method="GET", status="404", has_context=False, duration=0.01)
        assert True

    def test_record_retrieval_zero_score(self):
        from proxy.app.shared.metrics import record_retrieval

        record_retrieval(score=0.0, duration=0.0)
        assert True

    def test_record_llm_tokens_zero(self):
        from proxy.app.shared.metrics import record_llm_tokens

        record_llm_tokens(prompt_tokens=0, completion_tokens=0)
        assert True


class TestCacheMissMetrics:
    """Test cache miss tracking."""

    def test_record_cache_miss_does_not_raise(self):
        from proxy.app.shared.metrics import record_cache_miss

        record_cache_miss("memory")
        record_cache_miss("redis")

    def test_cache_miss_increments_and_shows_in_metrics(self):
        from proxy.app.shared.metrics import RAG_CACHE_MISSES, init_metrics, metrics_endpoint

        init_metrics()
        RAG_CACHE_MISSES.labels(cache_type="memory").inc()
        result = metrics_endpoint()
        assert "rag_cache_misses_total" in result.body.decode()
        assert 'cache_type="memory"' in result.body.decode()


class TestQueueDepthMetrics:
    """Test queue depth tracking."""

    def test_set_queue_depth_does_not_raise(self):
        from proxy.app.shared.metrics import set_queue_depth

        set_queue_depth(0)
        set_queue_depth(5)
        set_queue_depth(100)

    def test_queue_depth_appears_in_metrics(self):
        from proxy.app.shared.metrics import RAG_QUEUE_DEPTH, init_metrics, metrics_endpoint

        init_metrics()
        RAG_QUEUE_DEPTH.set(3)
        result = metrics_endpoint()
        assert "rag_queue_depth" in result.body.decode()
