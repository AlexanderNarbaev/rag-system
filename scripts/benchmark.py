"""Benchmark RAG system performance against NFR targets.

Usage:
    python scripts/benchmark.py --proxy-url http://localhost:8080
"""

import argparse
import asyncio
import time
from statistics import mean, median, quantiles
from typing import Any

import httpx

REQUEST_PATH = "/v1/chat/completions"


def _percentile(latencies: list[float], percentile: int) -> float:
    """Return a percentile in milliseconds, including small samples."""
    if not latencies:
        return 0.0
    if len(latencies) == 1:
        return latencies[0] * 1000
    count = 100 if percentile == 99 else 20
    index = 98 if percentile == 99 else 18
    if len(latencies) < count:
        ordered = sorted(latencies)
        position = (len(ordered) - 1) * percentile / 100
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        return value * 1000
    return quantiles(latencies, n=count)[index] * 1000


async def benchmark_chat_completion(proxy_url: str, iterations: int = 100) -> dict[str, Any]:
    """Benchmark sequential chat completion latency."""
    latencies: list[float] = []
    async with httpx.AsyncClient(base_url=proxy_url, timeout=30.0) as client:
        for i in range(iterations):
            start = time.perf_counter()
            try:
                response = await client.post(
                    REQUEST_PATH,
                    json={
                        "model": "test-model+RAG",
                        "messages": [{"role": "user", "content": f"Test query {i}"}],
                    },
                )
            except httpx.HTTPError:
                continue
            elapsed = time.perf_counter() - start
            if response.status_code == 200:
                latencies.append(elapsed)

    if not latencies:
        return {"error": "No successful requests"}

    return {
        "iterations": iterations,
        "successful": len(latencies),
        "p50": median(latencies) * 1000,
        "p95": _percentile(latencies, 95),
        "p99": _percentile(latencies, 99),
        "mean": mean(latencies) * 1000,
        "max": max(latencies) * 1000,
    }


async def benchmark_concurrent(proxy_url: str, concurrent: int = 50) -> dict[str, Any]:
    """Benchmark latency for concurrent users."""

    async def make_request(client: httpx.AsyncClient, i: int) -> tuple[float, int]:
        start = time.perf_counter()
        try:
            response = await client.post(
                REQUEST_PATH,
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": f"Concurrent test {i}"}],
                },
            )
            return time.perf_counter() - start, response.status_code
        except httpx.HTTPError:
            return time.perf_counter() - start, 0

    async with httpx.AsyncClient(base_url=proxy_url, timeout=30.0) as client:
        results = await asyncio.gather(*(make_request(client, i) for i in range(concurrent)))

    latencies = [elapsed for elapsed, status in results if status == 200]
    return {
        "concurrent": concurrent,
        "successful": len(latencies),
        "p95": _percentile(latencies, 95),
        "mean": mean(latencies) * 1000 if latencies else 0,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark RAG system performance")
    parser.add_argument("--proxy-url", default="http://localhost:8080")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--concurrent", type=int, default=50)
    args = parser.parse_args()

    print("=== RAG System Benchmark ===")
    print(f"Proxy: {args.proxy_url}")

    print("\n[1] Chat completion latency")
    result = await benchmark_chat_completion(args.proxy_url, args.iterations)
    print(f"  p50: {result.get('p50', 0):.1f}ms")
    print(f"  p95: {result.get('p95', 0):.1f}ms (target: <5000ms)")
    print(f"  p99: {result.get('p99', 0):.1f}ms")

    print("\n[2] Concurrent users")
    result = await benchmark_concurrent(args.proxy_url, args.concurrent)
    print(f"  Successful: {result.get('successful', 0)}/{args.concurrent}")
    print(f"  p95: {result.get('p95', 0):.1f}ms (target: <5000ms)")


if __name__ == "__main__":
    asyncio.run(main())
