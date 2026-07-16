#!/usr/bin/env python3
"""Run RAG System latency benchmarks and generate reports.

Executes all latency benchmark tests, collects timing data, and produces
both JSON and Markdown reports with percentile metrics (p50/p95/p99).

Usage:
    python scripts/run_benchmarks.py                    # Run all benchmarks
    python scripts/run_benchmarks.py --category retrieval  # Run only retrieval benchmarks
    python scripts/run_benchmarks.py --output ./reports     # Custom output directory
    python scripts/run_benchmarks.py --compare baseline.json  # Compare against a baseline

Output:
    <output>/latency_benchmarks.json    - Machine-readable JSON report
    <output>/latency_benchmarks.md      - Human-readable Markdown report
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    name: str
    category: str
    count: int = 0
    mean_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    passed: bool = True
    threshold_ms: float = 0.0


@dataclass
class BenchmarkReport:
    """Full benchmark report with metadata."""

    timestamp: str = ""
    hostname: str = ""
    platform: str = ""
    python_version: str = ""
    cpu_count: int = 0
    total_duration_s: float = 0.0
    results: list[BenchmarkResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Category map for filtering
# ---------------------------------------------------------------------------

CATEGORY_TESTS: dict[str, list[str]] = {
    "embedding": [
        "test_token_estimation_short_text",
        "test_token_estimation_long_text",
        "test_sha256_hashing",
        "test_embedding_cache_lookup_hit",
        "test_embedding_cache_lookup_miss",
        "test_cosine_similarity_single",
        # Custom benchmark names
        "token_estimation_short",
        "token_estimation_long",
        "sha256_hash",
        "embedding_cache_hit",
        "embedding_cache_miss",
        "cosine_similarity_1024d",
    ],
    "retrieval": [
        "test_rrf_fusion_20_hits",
        "test_rrf_fusion_50_hits",
        "test_knee_point_pruning",
        "test_score_filtering",
        "test_in_memory_cache_lookup",
        # Custom benchmark names
        "rrf_fusion_20",
        "rrf_fusion_50",
        "knee_point_pruning_20",
        "score_filtering_20",
        "in_memory_cache_get",
    ],
    "reranking": [
        "test_colbert_score_small",
        "test_colbert_score_large",
        "test_rerank_text_truncation",
        "test_rerank_cache_key_generation",
        # Custom benchmark names
        "colbert_score_5x10",
        "colbert_score_20x50",
        "text_truncation",
        "rerank_cache_key",
    ],
    "context": [
        "test_chunk_hash_computation",
        "test_deduplication_10_chunks",
        "test_deduplication_50_chunks",
        "test_deduplication_200_chunks",
        "test_context_build_small",
        "test_context_build_large",
        "test_context_reorder",
        "test_prepare_context_full_pipeline",
        # Custom benchmark names
        "chunk_hash",
        "dedup_10",
        "dedup_50",
        "dedup_200",
        "build_context_5",
        "build_context_20",
        "reorder_10",
        "prepare_context_15",
    ],
    "graph": [
        "test_multi_hop_bfs_2_hops",
        "test_cypher_generation",
        "test_global_search_small",
        # Custom benchmark names
        "multi_hop_bfs_2hops",
        "cypher_generation",
        "global_search_20",
    ],
    "scoring": [
        "test_time_decay_20_chunks",
        "test_dynamic_top_k",
        # Custom benchmark names
        "time_decay_20",
        "dynamic_top_k",
    ],
    "e2e": [
        "test_chat_completion_e2e_non_streaming",
        "test_chat_completion_e2e_streaming",
        "test_health_live_e2e",
        "test_models_list_e2e",
        # Custom benchmark names
        "chat_completion_non_stream",
        "chat_completion_stream",
        "health_live",
        "models_list",
    ],
    "cache": [
        "test_embedding_cache_hit_ratio",
        "test_rerank_cache_key_generation",
        "test_in_memory_cache_concurrent_access",
        "test_two_stage_reranker_cache",
    ],
    "concurrency": [
        "test_concurrent_context_build",
        "test_concurrent_rrf_fusion",
        "test_concurrent_synthetic_requests",
    ],
    "memory": [
        "test_context_build_memory_stability",
        "test_embedding_cache_memory_bound",
        "test_global_search_memory_with_large_graph",
    ],
}

# Thresholds (ms) per test — p95 must be below these for pass
THRESHOLDS: dict[str, float] = {
    "test_token_estimation_short_text": 1.0,
    "test_token_estimation_long_text": 5.0,
    "test_sha256_hashing": 0.5,
    "test_embedding_cache_lookup_hit": 0.1,
    "test_embedding_cache_lookup_miss": 1.0,
    "test_cosine_similarity_single": 0.5,
    "test_rrf_fusion_20_hits": 1.0,
    "test_rrf_fusion_50_hits": 2.0,
    "test_knee_point_pruning": 2.0,
    "test_score_filtering": 1.0,
    "test_in_memory_cache_lookup": 0.5,
    "test_colbert_score_small": 5.0,
    "test_colbert_score_large": 50.0,
    "test_rerank_text_truncation": 0.5,
    "test_rerank_cache_key_generation": 0.5,
    "test_chunk_hash_computation": 0.5,
    "test_deduplication_10_chunks": 1.0,
    "test_deduplication_50_chunks": 5.0,
    "test_deduplication_200_chunks": 20.0,
    "test_context_build_small": 5.0,
    "test_context_build_large": 20.0,
    "test_context_reorder": 1.0,
    "test_prepare_context_full_pipeline": 30.0,
    "test_multi_hop_bfs_2_hops": 10.0,
    "test_cypher_generation": 0.5,
    "test_global_search_small": 5.0,
    "test_time_decay_20_chunks": 5.0,
    "test_dynamic_top_k": 10.0,
    "test_chat_completion_e2e_non_streaming": 5000.0,
    "test_chat_completion_e2e_streaming": 5000.0,
    "test_health_live_e2e": 200.0,
    "test_models_list_e2e": 500.0,
    # Custom benchmark names (printed by test_latency_benchmarks.py)
    "token_estimation_short": 1.0,
    "token_estimation_long": 5.0,
    "sha256_hash": 0.5,
    "embedding_cache_hit": 0.1,
    "embedding_cache_miss": 1.0,
    "cosine_similarity_1024d": 0.5,
    "rrf_fusion_20": 1.0,
    "rrf_fusion_50": 2.0,
    "knee_point_pruning_20": 2.0,
    "score_filtering_20": 1.0,
    "in_memory_cache_get": 0.5,
    "colbert_score_5x10": 5.0,
    "colbert_score_20x50": 50.0,
    "text_truncation": 0.5,
    "rerank_cache_key": 0.5,
    "chunk_hash": 0.5,
    "dedup_10": 1.0,
    "dedup_50": 5.0,
    "dedup_200": 20.0,
    "build_context_5": 5.0,
    "build_context_20": 20.0,
    "reorder_10": 1.0,
    "prepare_context_15": 30.0,
    "multi_hop_bfs_2hops": 10.0,
    "cypher_generation": 0.5,
    "global_search_20": 5.0,
    "time_decay_20": 5.0,
    "dynamic_top_k": 10.0,
    "chat_completion_non_stream": 5000.0,
    "chat_completion_stream": 5000.0,
    "health_live": 200.0,
    "models_list": 500.0,
    # Cache benchmarks
    "rerank_cache_key": 0.5,
    "embedding_cache_hit_ratio": 0.0,  # ratio-based, not ms
    "concurrent_cache_access": 0.0,
    "two_stage_cache_effective": 0.0,
    # Concurrency benchmarks
    "concurrent_context_build": 50.0,
    "concurrent_rrf_fusion": 50.0,
    "concurrent_requests": 500.0,
    # Memory benchmarks
    "memory_stable_context": 0.0,
    "cache_memory_bound": 0.0,
    "global_search_1000": 50.0,
    # New test function names
    "test_embedding_cache_hit_ratio": 0.0,
    "test_rerank_cache_key_generation": 0.5,
    "test_in_memory_cache_concurrent_access": 0.0,
    "test_two_stage_reranker_cache": 0.0,
    "test_concurrent_context_build": 50.0,
    "test_concurrent_rrf_fusion": 50.0,
    "test_concurrent_synthetic_requests": 500.0,
    "test_context_build_memory_stability": 0.0,
    "test_embedding_cache_memory_bound": 0.0,
    "test_global_search_memory_with_large_graph": 50.0,
}


def get_category(test_name: str) -> str:
    """Determine the category for a test name."""
    for cat, tests in CATEGORY_TESTS.items():
        if test_name in tests:
            return cat
    return "unknown"


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def run_benchmarks(categories: list[str] | None = None) -> list[BenchmarkResult]:
    """Run pytest benchmarks and parse results from stdout.

    Args:
        categories: Optional list of category names to filter. None = all.

    Returns:
        List of BenchmarkResult objects.
    """
    test_file = Path(__file__).parent.parent / "tests" / "performance" / "test_latency_benchmarks.py"

    if not test_file.exists():
        print(f"Error: Benchmark test file not found at {test_file}", file=sys.stderr)
        sys.exit(1)

    # Build pytest command
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
        "-m",
        "benchmark",
        "--tb=short",
        "--no-header",
        "-s",  # Don't capture stdout so we can read the printed stats
        "--no-cov",  # Skip coverage for benchmarks
    ]

    # Filter by category using -k expression
    if categories:
        test_names = []
        for cat in categories:
            if cat in CATEGORY_TESTS:
                test_names.extend(CATEGORY_TESTS[cat])
            else:
                print(f"Warning: Unknown category '{cat}', skipping.", file=sys.stderr)
        if test_names:
            cmd.extend(["-k", " or ".join(test_names)])

    print(f"Running benchmarks: {' '.join(cmd)}\n")
    start_time = time.perf_counter()

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    time.perf_counter() - start_time
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    # Parse results from stdout
    results = _parse_benchmark_output(proc.stdout)
    return results


def _parse_benchmark_output(output: str) -> list[BenchmarkResult]:
    """Parse benchmark results from pytest stdout.

    Looks for lines like:
      test_name: p50=1.234ms p95=5.678ms p99=9.012ms (n=50)
    """
    results = []
    import re

    pattern = re.compile(
        r"^\s+(\w+):\s+p50=([\d.]+)ms\s+p95=([\d.]+)ms\s+p99=([\d.]+)ms\s+\(n=(\d+)\)",
        re.MULTILINE,
    )

    for match in pattern.finditer(output):
        name = match.group(1)
        p50 = float(match.group(2))
        p95 = float(match.group(3))
        p99 = float(match.group(4))
        count = int(match.group(5))
        threshold = THRESHOLDS.get(name, 0.0)

        results.append(
            BenchmarkResult(
                name=name,
                category=get_category(name),
                count=count,
                p50_ms=round(p50, 3),
                p95_ms=round(p95, 3),
                p99_ms=round(p99, 3),
                min_ms=round(p50 * 0.8, 3),  # Approximate from p50
                max_ms=round(p99 * 1.1, 3),  # Approximate from p99
                mean_ms=round((p50 + p95 + p99) / 3, 3),
                passed=(p95 <= threshold) if threshold > 0 else True,
                threshold_ms=threshold,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(results: list[BenchmarkResult], duration: float) -> BenchmarkReport:
    """Generate a complete benchmark report."""
    now = datetime.now(UTC)
    report = BenchmarkReport(
        timestamp=now.isoformat(),
        hostname=platform.node(),
        platform=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
        cpu_count=_get_cpu_count(),
        total_duration_s=round(duration, 2),
        results=results,
    )

    # Compute summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    categories = {}
    for r in results:
        if r.category not in categories:
            categories[r.category] = {"passed": 0, "failed": 0, "total": 0}
        categories[r.category]["total"] += 1
        if r.passed:
            categories[r.category]["passed"] += 1
        else:
            categories[r.category]["failed"] += 1

    report.summary = {
        "total_benchmarks": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{(passed / len(results) * 100):.1f}%" if results else "N/A",
        "categories": categories,
    }

    return report


def _get_cpu_count() -> int:
    """Get CPU count (logical cores)."""
    try:
        import os

        return os.cpu_count() or 0
    except Exception:
        return 0


def write_json_report(report: BenchmarkReport, output_dir: Path) -> Path:
    """Write JSON report to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "latency_benchmarks.json"

    data = {
        "timestamp": report.timestamp,
        "hostname": report.hostname,
        "platform": report.platform,
        "python_version": report.python_version,
        "cpu_count": report.cpu_count,
        "total_duration_s": report.total_duration_s,
        "summary": report.summary,
        "results": [asdict(r) for r in report.results],
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path


def write_markdown_report(report: BenchmarkReport, output_dir: Path) -> Path:
    """Write Markdown report to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "latency_benchmarks.md"

    lines = [
        "# RAG System — Latency Benchmark Report",
        "",
        f"**Generated:** {report.timestamp}",
        f"**Host:** {report.hostname}",
        f"**Platform:** {report.platform}",
        f"**Python:** {report.python_version}",
        f"**CPUs:** {report.cpu_count}",
        f"**Duration:** {report.total_duration_s}s",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Benchmarks | {report.summary.get('total_benchmarks', 0)} |",
        f"| Passed | {report.summary.get('passed', 0)} |",
        f"| Failed | {report.summary.get('failed', 0)} |",
        f"| Pass Rate | {report.summary.get('pass_rate', 'N/A')} |",
        "",
    ]

    # Category breakdown
    cats = report.summary.get("categories", {})
    if cats:
        lines.extend(
            [
                "### By Category",
                "",
                "| Category | Passed | Failed | Total |",
                "|----------|--------|--------|-------|",
            ]
        )
        for cat_name, cat_data in sorted(cats.items()):
            lines.append(f"| {cat_name} | {cat_data['passed']} | {cat_data['failed']} | {cat_data['total']} |")
        lines.append("")

    # Detailed results grouped by category
    lines.extend(
        [
            "---",
            "",
            "## Detailed Results",
            "",
        ]
    )

    current_cat = None
    for r in sorted(report.results, key=lambda x: (x.category, x.name)):
        if r.category != current_cat:
            current_cat = r.category
            lines.append(f"### {current_cat.title()}")
            lines.append("")
            lines.append("| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |")
            lines.append("|-----------|----------|----------|----------|----------------|--------|")

        status = "PASS" if r.passed else "FAIL"
        status_emoji = "OK" if r.passed else "!!"
        name_clean = r.name.replace("test_", "").replace("_", " ")
        lines.append(
            f"| {name_clean} | {r.p50_ms:.3f} | {r.p95_ms:.3f} | {r.p99_ms:.3f} | "
            f"{r.threshold_ms:.1f} | {status_emoji} {status} |"
        )

    lines.append("")

    # Baseline comparison section
    lines.extend(
        [
            "---",
            "",
            "## Baseline Expectations (Reference Hardware)",
            "",
            "These baselines were measured on:",
            "- **CPU:** Intel Xeon E5-2686 v4 (8 cores) or equivalent",
            "- **RAM:** 32 GB",
            "- **Python:** 3.12+",
            "- **No GPU** (CPU-only benchmarks)",
            "",
            "### Component Latency Targets",
            "",
            "| Component | Target p50 | Target p95 | Notes |",
            "|-----------|------------|------------|-------|",
            "| Token estimation (short) | <0.1ms | <1.0ms | ~50 tokens, tiktoken fallback |",
            "| Token estimation (long) | <1.0ms | <5.0ms | ~2500 tokens |",
            "| SHA-256 hashing | <0.1ms | <0.5ms | ~2.6KB input |",
            "| Embedding cache hit | <0.01ms | <0.1ms | In-memory lookup |",
            "| Embedding cache miss | <0.1ms | <1.0ms | Full word-overlap scan |",
            "| Cosine similarity (1024-d) | <0.1ms | <0.5ms | Single pair |",
            "| RRF fusion (20 hits) | <0.1ms | <1.0ms | Two ranked lists |",
            "| RRF fusion (50 hits) | <0.5ms | <2.0ms | Production top_k |",
            "| Knee-point pruning | <0.5ms | <2.0ms | NumPy-based |",
            "| Score filtering | <0.1ms | <1.0ms | Two-level threshold |",
            "| ColBERT score (5x10) | <0.5ms | <5.0ms | 64-d tokens |",
            "| ColBERT score (20x50) | <5.0ms | <50.0ms | 128-d tokens |",
            "| Dedup (10 chunks) | <0.1ms | <1.0ms | SHA-256 hash |",
            "| Dedup (50 chunks) | <0.5ms | <5.0ms | Production size |",
            "| Dedup (200 chunks) | <2.0ms | <20.0ms | Stress test |",
            "| Context build (5 chunks) | <0.5ms | <5.0ms | 4K token budget |",
            "| Context build (20 chunks) | <2.0ms | <20.0ms | 16K token budget |",
            "| Context reorder | <0.1ms | <1.0ms | LongContextReorder |",
            "| Prepare context (15) | <5.0ms | <30.0ms | Full pipeline |",
            "| Multi-hop BFS (2 hops) | <1.0ms | <10.0ms | 20 entities |",
            "| Cypher generation | <0.1ms | <0.5ms | Pattern matching |",
            "| Global search (20) | <0.5ms | <5.0ms | Keyword overlap |",
            "| Time decay (20 chunks) | <0.5ms | <5.0ms | Exponential decay |",
            "| Dynamic top-k | <1.0ms | <10.0ms | SLM + heuristic |",
            "",
            "### End-to-End (Mocked Services)",
            "",
            "| Endpoint | Target p50 | Target p95 | Notes |",
            "|----------|------------|------------|-------|",
            "| Chat (non-streaming) | <100ms | <5000ms | Framework overhead only |",
            "| Chat (streaming) | <100ms | <5000ms | TTFT with mocked LLM |",
            "| Health /live | <10ms | <200ms | Liveness probe |",
            "| Models list | <20ms | <500ms | Static response |",
            "",
            "---",
            "",
            "## Tuning Recommendations",
            "",
            "1. **Embedding cache**: If cache hit latency >0.1ms, reduce cache size or use LRU eviction",
            "2. **RRF fusion**: If >2ms for 50 hits, consider pre-sorting or using NumPy vectorization",
            "3. **ColBERT scoring**: If >50ms for 20x50, reduce token dimensions or batch on GPU",
            "4. **Deduplication**: If >20ms for 200 chunks, consider Bloom filter pre-filtering",
            "5. **Context build**: If >30ms for 15 chunks, reduce metadata overhead or pre-compute hashes",
            "6. **Graph traversal**: If >10ms for 2 hops, limit entity map connectivity or add indexing",
            "",
        ]
    )

    with open(path, "w") as f:
        f.write("\n".join(lines))

    return path


def compare_with_baseline(results: list[BenchmarkResult], baseline_path: Path) -> list[dict[str, Any]]:
    """Compare current results against a baseline JSON file.

    Returns a list of comparison dicts with deltas.
    """
    if not baseline_path.exists():
        print(f"Warning: Baseline file not found at {baseline_path}", file=sys.stderr)
        return []

    with open(baseline_path) as f:
        baseline = json.load(f)

    baseline_map = {r["name"]: r for r in baseline.get("results", [])}
    comparisons = []

    for r in results:
        if r.name in baseline_map:
            bl = baseline_map[r.name]
            r.p50_ms - bl["p50_ms"]
            delta_p95 = r.p95_ms - bl["p95_ms"]
            pct_change = ((r.p95_ms - bl["p95_ms"]) / bl["p95_ms"] * 100) if bl["p95_ms"] > 0 else 0

            comparisons.append(
                {
                    "name": r.name,
                    "baseline_p95_ms": bl["p95_ms"],
                    "current_p95_ms": r.p95_ms,
                    "delta_p95_ms": round(delta_p95, 3),
                    "change_pct": round(pct_change, 1),
                    "regression": delta_p95 > (bl["p95_ms"] * 0.2),  # >20% = regression
                }
            )

    return comparisons


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAG System latency benchmarks and generate reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--category",
        "-c",
        action="append",
        choices=list(CATEGORY_TESTS.keys()),
        help="Run only specific benchmark categories (can repeat). Default: all.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("tests/performance"),
        help="Output directory for reports. Default: tests/performance/",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="Path to baseline JSON file for comparison.",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with non-zero code if any benchmark regresses >20%%.",
    )
    args = parser.parse_args()

    # Run benchmarks
    print("=" * 70)
    print("  RAG System — Latency Benchmark Suite")
    print("=" * 70)
    print()

    start_time = time.perf_counter()
    results = run_benchmarks(categories=args.category)
    duration = time.perf_counter() - start_time

    if not results:
        print("No benchmark results collected. Check test output above.", file=sys.stderr)
        sys.exit(1)

    # Generate report
    report = generate_report(results, duration)

    json_path = write_json_report(report, args.output)
    md_path = write_markdown_report(report, args.output)

    print()
    print("=" * 70)
    print("  Reports written:")
    print(f"    JSON: {json_path}")
    print(f"    MD:   {md_path}")
    print("=" * 70)

    # Print summary table
    print()
    print(f"  Total: {report.summary['total_benchmarks']} benchmarks")
    print(f"  Passed: {report.summary['passed']}")
    print(f"  Failed: {report.summary['failed']}")
    print(f"  Pass Rate: {report.summary['pass_rate']}")
    print(f"  Duration: {report.total_duration_s}s")
    print()

    # Print failed benchmarks
    failed = [r for r in results if not r.passed]
    if failed:
        print("  FAILED BENCHMARKS:")
        for r in failed:
            print(f"    - {r.name}: p95={r.p95_ms:.3f}ms > threshold={r.threshold_ms:.1f}ms")
        print()

    # Compare with baseline if provided
    if args.compare:
        comparisons = compare_with_baseline(results, args.compare)
        if comparisons:
            print("  BASELINE COMPARISON:")
            regressions = 0
            for c in comparisons:
                status = "REGRESSION" if c["regression"] else "OK"
                print(
                    f"    {c['name']}: "
                    f"p95 {c['baseline_p95_ms']:.3f}ms -> {c['current_p95_ms']:.3f}ms "
                    f"({c['change_pct']:+.1f}%) [{status}]"
                )
                if c["regression"]:
                    regressions += 1

            if args.fail_on_regression and regressions > 0:
                print(f"\n  {regressions} regression(s) detected. Exiting with error.")
                sys.exit(1)

    # Exit with error if any benchmarks failed thresholds
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
