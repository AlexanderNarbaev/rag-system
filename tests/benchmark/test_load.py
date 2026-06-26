"""Performance benchmark tests for the RAG proxy.

Uses concurrent.futures.ThreadPoolExecutor for load generation.
Records p50, p95, p99 latency, RPS, and error rates.
"""

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import requests


def _send_chat_request(service_url: str, query: str = "What is RAG?") -> tuple[float, int, str]:
    """Send a single chat request and return (latency_ms, status_code, response_preview)."""
    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": query}],
                "stream": False,
            },
            timeout=60,
        )
        latency = (time.perf_counter() - start) * 1000
        preview = ""
        try:
            data = resp.json()
            preview = data.get("choices", [{}])[0].get("message", {}).get("content", "")[:100]
        except json.JSONDecodeError:
            preview = resp.text[:100]
        return latency, resp.status_code, preview
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return latency, 0, str(e)[:100]


def _compute_percentiles(values: list[float]) -> dict:
    """Compute p50, p95, p99 from a list of values."""
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "p50": sorted_vals[int(n * 0.50)] if n > 1 else sorted_vals[0],
        "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
        "p99": sorted_vals[min(int(n * 0.99), n - 1)] if n > 1 else sorted_vals[0],
    }


@pytest.mark.benchmark
class TestLatency:
    """Latency benchmarks at moderate concurrency."""

    def test_latency_at_10_users(self, service_url: str, benchmark_report: list):
        """10 concurrent users -> measure p50, p95, p99 latency."""
        num_workers = 10
        latencies = []
        errors = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_send_chat_request, service_url)
                for _ in range(num_workers)
            ]
            for future in as_completed(futures):
                latency_ms, status, _ = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        assert len(latencies) > 0, "No successful requests"
        percentiles = _compute_percentiles(latencies)
        mean_latency = statistics.mean(latencies)

        result = {
            "test": "test_latency_at_10_users",
            "concurrent_users": num_workers,
            "successful_requests": len(latencies),
            "errors": errors,
            "mean_ms": round(mean_latency, 2),
            **{k: round(v, 2) for k, v in percentiles.items()},
        }
        benchmark_report.append(result)

        assert errors < num_workers * 0.5, f"Too many errors: {errors}/{num_workers}"

    def test_warm_start_latency(self, service_url: str, benchmark_report: list):
        """After warm-up, measure first request latency."""
        # Warm up with 3 requests
        for _ in range(3):
            try:
                requests.post(
                    f"{service_url}/v1/chat/completions",
                    json={
                        "model": "rag-proxy",
                        "messages": [{"role": "user", "content": "Warm-up request"}],
                        "stream": False,
                    },
                    timeout=30,
                )
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.5)

        # Measure first request after warm-up
        latencies = []
        for _ in range(5):
            latency_ms, status, _ = _send_chat_request(service_url, "Warm start test")
            if status == 200:
                latencies.append(latency_ms)

        result = {
            "test": "test_warm_start_latency",
            "successful_requests": len(latencies),
            "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            "min_ms": round(min(latencies), 2) if latencies else 0,
            "max_ms": round(max(latencies), 2) if latencies else 0,
        }
        benchmark_report.append(result)


@pytest.mark.benchmark
class TestThroughput:
    """Throughput benchmarks at moderate concurrency."""

    def test_throughput_at_50_users(self, service_url: str, benchmark_report: list):
        """50 concurrent users -> measure RPS and error rate."""
        num_workers = 50
        latencies = []
        errors = 0
        start_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_send_chat_request, service_url)
                for _ in range(num_workers)
            ]
            for future in as_completed(futures):
                latency_ms, status, _ = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        elapsed = time.perf_counter() - start_time
        rps = len(latencies) / elapsed if elapsed > 0 else 0
        error_rate = errors / num_workers if num_workers > 0 else 0
        percentiles = _compute_percentiles(latencies)

        result = {
            "test": "test_throughput_at_50_users",
            "concurrent_users": num_workers,
            "elapsed_seconds": round(elapsed, 2),
            "rps": round(rps, 2),
            "successful_requests": len(latencies),
            "errors": errors,
            "error_rate": round(error_rate, 4),
            "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            **{k: round(v, 2) for k, v in percentiles.items()},
        }
        benchmark_report.append(result)

        assert error_rate < 0.5, f"Error rate too high: {error_rate:.2%}"


@pytest.mark.benchmark
class TestStress:
    """Stress tests at high concurrency."""

    def test_stress_at_100_users(self, service_url: str, benchmark_report: list):
        """100 concurrent users -> no crash, p95 < 60s (degraded threshold)."""
        num_workers = 100
        latencies = []
        errors = 0
        start_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_send_chat_request, service_url, f"Stress test query {i}")
                for i in range(num_workers)
            ]
            for future in as_completed(futures):
                latency_ms, status, _ = future.result()
                if status == 200:
                    latencies.append(latency_ms)
                else:
                    errors += 1

        elapsed = time.perf_counter() - start_time
        rps = len(latencies) / elapsed if elapsed > 0 else 0
        percentiles = _compute_percentiles(latencies)

        result = {
            "test": "test_stress_at_100_users",
            "concurrent_users": num_workers,
            "elapsed_seconds": round(elapsed, 2),
            "rps": round(rps, 2),
            "successful_requests": len(latencies),
            "errors": errors,
            "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            **{k: round(v, 2) for k, v in percentiles.items()},
        }
        benchmark_report.append(result)

        # Service should survive — at least some requests must succeed
        assert len(latencies) > 0, "No successful requests under stress"
        # p95 should be under 60s in degraded mode
        assert percentiles["p95"] < 60000, f"p95 too high: {percentiles['p95']}ms"
