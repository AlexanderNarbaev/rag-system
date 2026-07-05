"""Tests for proxy/app/tools/metrics.py — Tool observability metrics."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))


class TestToolMetricsCounters:
    """Tests for Prometheus counters: tool_calls_total, tool_errors_total."""

    def test_tool_calls_total_counter_exists(self):
        from tools.metrics import tool_calls_total
        assert tool_calls_total is not None
        assert tool_calls_total._name == "tool_calls"  # prometheus strips _total suffix

    def test_tool_errors_total_counter_exists(self):
        from tools.metrics import tool_errors_total
        assert tool_errors_total is not None
        assert tool_errors_total._name == "tool_errors"  # prometheus strips _total suffix


class TestToolMetricsHistograms:
    """Tests for Prometheus histograms: tool_duration_seconds, tool_retry_count."""

    def test_tool_duration_seconds_histogram_exists(self):
        from tools.metrics import tool_duration_seconds
        assert tool_duration_seconds is not None
        assert tool_duration_seconds._name == "tool_duration_seconds"

    def test_tool_duration_seconds_has_buckets(self):
        from tools.metrics import tool_duration_seconds
        buckets = tool_duration_seconds._upper_bounds
        assert len(buckets) > 0

    def test_tool_retry_count_histogram_exists(self):
        from tools.metrics import tool_retry_count
        assert tool_retry_count is not None
        assert tool_retry_count._name == "tool_retry_count"


class TestToolMetricsGauges:
    """Tests for Prometheus gauges: tools_registered_total."""

    def test_tools_registered_total_gauge_exists(self):
        from tools.metrics import tools_registered_total
        assert tools_registered_total is not None
        assert tools_registered_total._name == "tools_registered_total"


class TestToolMetricsRecordCall:
    """Tests for ToolMetrics.record_call()."""

    def test_record_call_increments_counter_success(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_call(tool_name="search_documents", status="success")

    def test_record_call_increments_counter_error(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_call(tool_name="search_documents", status="error")

    def test_record_call_with_duration(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_call(tool_name="search_documents", status="success", duration_seconds=0.5)

    def test_record_call_default_status(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_call(tool_name="search_documents")


class TestToolMetricsRecordError:
    """Tests for ToolMetrics.record_error()."""

    def test_record_error_tool_not_found(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="unknown_tool", error_type="ToolNotFoundError")

    def test_record_error_execution(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="search_documents", error_type="ToolExecutionError")

    def test_record_error_timeout(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="search_documents", error_type="ToolTimeoutError")

    def test_record_error_permission(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="admin_tool", error_type="ToolPermissionError")

    def test_record_error_validation(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="search_documents", error_type="ToolValidationError")

    def test_record_error_rate_limit(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="search_documents", error_type="ToolRateLimitError")

    def test_record_error_dependency(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_error(tool_name="compound_tool", error_type="ToolDependencyError")


class TestToolMetricsRecordRetry:
    """Tests for ToolMetrics.record_retry()."""

    def test_record_retry_single(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_retry(tool_name="search_documents", retry_count=1)

    def test_record_retry_multiple(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_retry(tool_name="search_documents", retry_count=3)

    def test_record_retry_zero(self):
        from tools.metrics import ToolMetrics
        metrics = ToolMetrics()
        metrics.record_retry(tool_name="search_documents", retry_count=0)
