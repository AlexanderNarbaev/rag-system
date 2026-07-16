"""Load testing for the RAG proxy using asyncio concurrent requests.

Runs 10, 50, and 100 concurrent user simulations. Measures:
- Response time percentiles (p50, p95, p99)
- Error rate under load
- Requests per second (RPS)

Generates a load_test_report.json file with results.

Run with: pytest tests/performance/test_load.py -v -m benchmark
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import pytest

REPORT_PATH = Path(__file__).parent / "load_test_report.json"


@dataclass
class LoadTestResult:
    test: str
    concurrent_users: int
    successful_requests: int
    errors: int
    elapsed_seconds: float
    rps: float
    error_rate: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float


def _compute_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "p50": sorted_vals[int(n * 0.50)],
        "p95": sorted_vals[min(int(n * 0.95), n - 1)],
        "p99": sorted_vals[min(int(n * 0.99), n - 1)],
    }


async def _send_chat_request(
    session: aiohttp.ClientSession,
    service_url: str,
    query: str = "What is RAG?",
    timeout: float = 60.0,
) -> tuple[float, int, str]:
    start = time.perf_counter()
    try:
        async with session.post(
            f"{service_url}/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": query}],
                "stream": False,
            },
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            latency = (time.perf_counter() - start) * 1000
            preview = ""
            try:
                data = await resp.json()
                preview = data.get("choices", [{}])[0].get("message", {}).get("content", "")[:100]
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                text = await resp.text()
                preview = text[:100]
            return latency, resp.status, preview
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return latency, 0, str(e)[:100]


async def _run_concurrent_load(
    service_url: str,
    num_users: int,
    test_name: str,
) -> LoadTestResult:
    latencies: list[float] = []
    errors = 0

    start_time = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        tasks = [_send_chat_request(session, service_url, f"{test_name} query {i}") for i in range(num_users)]
        results = await asyncio.gather(*tasks)

    elapsed = time.perf_counter() - start_time

    for latency_ms, status, _ in results:
        if status == 200:
            latencies.append(latency_ms)
        else:
            errors += 1

    successful = len(latencies)
    rps = successful / elapsed if elapsed > 0 else 0
    error_rate = errors / num_users if num_users > 0 else 0
    percentiles = _compute_percentiles(latencies)

    return LoadTestResult(
        test=test_name,
        concurrent_users=num_users,
        successful_requests=successful,
        errors=errors,
        elapsed_seconds=round(elapsed, 3),
        rps=round(rps, 2),
        error_rate=round(error_rate, 4),
        mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
        p50_ms=round(percentiles["p50"], 2),
        p95_ms=round(percentiles["p95"], 2),
        p99_ms=round(percentiles["p99"], 2),
        min_ms=round(min(latencies), 2) if latencies else 0.0,
        max_ms=round(max(latencies), 2) if latencies else 0.0,
    )


def _save_report(results: list[LoadTestResult]) -> Path:
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": [r.__dict__ for r in results],
        "summary": {
            "total_simulations": len(results),
            "max_concurrent_users": max(r.concurrent_users for r in results) if results else 0,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    return REPORT_PATH


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.benchmark
class TestLoad10Users:
    """Load test: 10 concurrent users."""

    @pytest.mark.asyncio
    async def test_load_10_concurrent_users(self, service_url: str, benchmark_report: list):
        result = await _run_concurrent_load(service_url, num_users=10, test_name="load_10_users")
        benchmark_report.append(result.__dict__)

        assert result.successful_requests > 0, "No successful requests"
        assert result.error_rate < 0.5, f"Error rate too high: {result.error_rate:.2%}"


@pytest.mark.benchmark
class TestLoad50Users:
    """Load test: 50 concurrent users."""

    @pytest.mark.asyncio
    async def test_load_50_concurrent_users(self, service_url: str, benchmark_report: list):
        result = await _run_concurrent_load(service_url, num_users=50, test_name="load_50_users")
        benchmark_report.append(result.__dict__)

        assert result.successful_requests > 0, "No successful requests"
        assert result.error_rate < 0.5, f"Error rate too high: {result.error_rate:.2%}"


@pytest.mark.benchmark
class TestLoad100Users:
    """Load test: 100 concurrent users."""

    @pytest.mark.asyncio
    async def test_load_100_concurrent_users(self, service_url: str, benchmark_report: list):
        result = await _run_concurrent_load(service_url, num_users=100, test_name="load_100_users")
        benchmark_report.append(result.__dict__)

        assert result.successful_requests > 0, "No successful requests under stress"
        assert result.p95_ms < 60000, f"p95 too high: {result.p95_ms}ms"


@pytest.mark.benchmark
class TestLoadPercentiles:
    """Validate response time percentiles at 50 users."""

    @pytest.mark.asyncio
    async def test_response_time_percentiles(self, service_url: str, benchmark_report: list):
        result = await _run_concurrent_load(service_url, num_users=50, test_name="percentile_50_users")
        benchmark_report.append(result.__dict__)

        assert result.successful_requests > 0, "No successful requests"
        assert result.p50_ms > 0, "p50 not measured"

        # Record percentiles as dedicated entries
        benchmark_report.append(
            {
                "test": "response_time_percentiles_50_users",
                "concurrent_users": 50,
                "p50_ms": result.p50_ms,
                "p95_ms": result.p95_ms,
                "p99_ms": result.p99_ms,
                "mean_ms": result.mean_ms,
                "min_ms": result.min_ms,
                "max_ms": result.max_ms,
                "error_rate": result.error_rate,
            }
        )


@pytest.mark.benchmark
class TestLoadErrorRate:
    """Validate error rate stays low under load."""

    @pytest.mark.asyncio
    async def test_error_rate_under_100_users(self, service_url: str, benchmark_report: list):
        result = await _run_concurrent_load(service_url, num_users=100, test_name="error_rate_100_users")
        benchmark_report.append(result.__dict__)

        assert result.successful_requests > 0, "No successful requests"
        # Under heavy load, some errors are acceptable but rate should be reasonable
        assert result.error_rate < 0.8, f"Error rate catastrophic: {result.error_rate:.2%}"


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point — generate load test report standalone
# ═══════════════════════════════════════════════════════════════════════════


async def _generate_report(service_url: str) -> int:
    """Run all load simulations and write load_test_report.json. Returns exit code."""
    results: list[LoadTestResult] = []
    configs = [
        (10, "load_10_users"),
        (50, "load_50_users"),
        (100, "load_100_users"),
    ]

    for num_users, name in configs:
        print(f"Running {name} ({num_users} concurrent users)...")
        result = await _run_concurrent_load(service_url, num_users, name)
        results.append(result)
        print(
            f"  {result.successful_requests} OK, {result.errors} errors, "
            f"p50={result.p50_ms}ms, p95={result.p95_ms}ms, p99={result.p99_ms}ms, "
            f"RPS={result.rps}"
        )

    report_path = _save_report(results)
    print(f"\nLoad test report saved to: {report_path}")
    return 0
