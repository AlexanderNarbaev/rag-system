# proxy/app/tools/metrics.py
"""Tool system observability metrics.

Prometheus counters, histograms, and gauges for tool call tracking
with a high-level ``ToolMetrics`` class.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from proxy.app.shared.metrics import _reuse_metric  # noqa: F401  # canonical location

tool_calls_total: Counter = _reuse_metric("tool_calls_total", Counter) or Counter(
    "tool_calls_total",
    "Total number of tool calls",
    ["tool_name", "status"],
)

tool_errors_total: Counter = _reuse_metric("tool_errors_total", Counter) or Counter(
    "tool_errors_total",
    "Total number of tool errors",
    ["tool_name", "error_type"],
)

tool_duration_seconds: Histogram = _reuse_metric("tool_duration_seconds", Histogram) or Histogram(
    "tool_duration_seconds",
    "Tool call duration in seconds",
    ["tool_name"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

tool_retry_count: Histogram = _reuse_metric("tool_retry_count", Histogram) or Histogram(
    "tool_retry_count",
    "Number of retries per tool call",
    ["tool_name"],
    buckets=(0, 1, 2, 3, 5, 10),
)

tools_registered_total: Gauge = _reuse_metric("tools_registered_total", Gauge) or Gauge(
    "tools_registered_total",
    "Total number of registered tools",
)


class ToolMetrics:
    """High-level metrics interface for tool observability.

    Usage::

        metrics = ToolMetrics()
        metrics.record_call("search_docs", status="success", duration_seconds=0.25)
        metrics.record_error("search_docs", error_type="ToolTimeoutError")
        metrics.record_retry("search_docs", retry_count=2)
    """

    @staticmethod
    def record_call(
        tool_name: str,
        status: str = "success",
        duration_seconds: float | None = None,
    ) -> None:
        """Record a completed tool call."""
        tool_calls_total.labels(tool_name=tool_name, status=status).inc()
        if duration_seconds is not None:
            tool_duration_seconds.labels(tool_name=tool_name).observe(duration_seconds)

    @staticmethod
    def record_error(tool_name: str, error_type: str) -> None:
        """Record a tool error by error type."""
        tool_errors_total.labels(tool_name=tool_name, error_type=error_type).inc()

    @staticmethod
    def record_retry(tool_name: str, retry_count: int) -> None:
        """Record a retry count for a tool call."""
        tool_retry_count.labels(tool_name=tool_name).observe(retry_count)
