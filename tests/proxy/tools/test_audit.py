"""Tests for proxy/app/tools/audit.py — ToolAuditLogger and ToolAuditRecord."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))


class TestToolAuditRecord:
    """Tests for ToolAuditRecord dataclass."""

    def test_create_record_with_all_fields(self):
        from tools.audit import ToolAuditRecord

        record = ToolAuditRecord(
            timestamp="2025-01-01T00:00:00Z",
            tool_name="search_documents",
            tool_call_id="call_1",
            user_id="user_1",
            request_id="req_1",
            params={"query": "RAG", "top_k": 5},
            result_status="success",
            duration_ms=12.5,
        )
        assert record.tool_name == "search_documents"
        assert record.result_status == "success"
        assert record.duration_ms == 12.5
        assert record.error is None

    def test_create_record_with_error(self):
        from tools.audit import ToolAuditRecord

        record = ToolAuditRecord(
            timestamp="2025-01-01T00:00:00Z",
            tool_name="search_documents",
            tool_call_id="call_2",
            user_id=None,
            request_id="req_2",
            params={},
            result_status="error",
            duration_ms=0.0,
            error="Tool not found",
        )
        assert record.result_status == "error"
        assert record.error == "Tool not found"

    def test_to_json_produces_serializable_dict(self):
        from tools.audit import ToolAuditRecord

        record = ToolAuditRecord(
            timestamp="2025-01-01T00:00:00Z",
            tool_name="search_documents",
            tool_call_id="call_3",
            user_id="user_1",
            request_id="req_3",
            params={"query": "test"},
            result_status="success",
            duration_ms=5.0,
        )
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert parsed["tool_name"] == "search_documents"
        assert parsed["params"] == {"query": "test"}
        assert parsed["duration_ms"] == 5.0


class TestSanitizeParams:
    """Tests for _sanitize_params helper."""

    def test_masks_password_field(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"password": "secret123"})
        assert result["password"] == "***"

    def test_masks_token_field(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"token": "abc123xyz"})
        assert result["token"] == "***"

    def test_masks_api_key_field(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"api_key": "sk-1234567890abcdef"})
        assert result["api_key"] == "***"

    def test_masks_authorization_field(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"authorization": "Bearer xyz"})
        assert result["authorization"] == "***"

    def test_truncates_long_string_values(self):
        from tools.audit import _sanitize_params

        long_text = "a" * 300
        result = _sanitize_params({"query": long_text}, max_value_length=200)
        assert len(result["query"]) == 203
        assert result["query"].endswith("...")

    def test_preserves_short_strings(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"query": "What is RAG?"})
        assert result["query"] == "What is RAG?"

    def test_preserves_primitives(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"count": 5, "active": True, "ratio": 0.95, "notes": None})
        assert result["count"] == 5
        assert result["active"] is True
        assert result["ratio"] == 0.95
        assert result["notes"] is None

    def test_truncates_large_dict_values(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"data": {"nested": {"deep": ["x" * 1000]}}}, max_value_length=200)
        assert len(result["data"]) == 203

    def test_case_insensitive_sensitive_fields(self):
        from tools.audit import _sanitize_params

        result = _sanitize_params({"Secret": "hidden", "APIKEY": "key"})
        assert result["Secret"] == "***"
        assert result["APIKEY"] == "***"


class TestToolAuditLoggerStdout:
    """Tests for ToolAuditLogger with stdout destination."""

    @pytest.fixture
    def audit_logger(self):
        from tools.audit import AuditDestination, ToolAuditLogger

        return ToolAuditLogger(destination=AuditDestination.STDOUT)

    def test_log_invocation_writes_to_stdout(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(
                tool_name="search_documents",
                tool_call_id="call_1",
                user_id="user_1",
                request_id="req_1",
                params={"query": "RAG"},
                result_status="success",
                duration_ms=12.5,
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert output
        record = json.loads(output.strip())
        assert record["tool_name"] == "search_documents"
        assert record["tool_call_id"] == "call_1"
        assert record["result_status"] == "success"
        assert record["duration_ms"] == 12.5

    def test_log_invocation_with_error(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(
                tool_name="bad_tool",
                tool_call_id="call_err",
                result_status="error",
                error="Execution failed",
            )
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["result_status"] == "error"
        assert record["error"] == "Execution failed"

    def test_log_invocation_sanitizes_params(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(
                tool_name="auth_tool",
                tool_call_id="call_3",
                params={"password": "secret!", "query": "hello"},
            )
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["params"]["password"] == "***"
        assert record["params"]["query"] == "hello"

    def test_log_invocation_includes_timestamp(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(tool_name="t", tool_call_id="c")
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert "timestamp" in record
        assert record["timestamp"]

    def test_log_invocation_rounds_duration(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(
                tool_name="t",
                tool_call_id="c",
                duration_ms=12.56789,
            )
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["duration_ms"] == 12.568


class TestToolAuditLoggerFile:
    """Tests for ToolAuditLogger with file destination."""

    @pytest.fixture
    def audit_logger(self):
        from tools.audit import AuditDestination, ToolAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            yield ToolAuditLogger(destination=AuditDestination.FILE, log_dir=tmpdir)

    def test_log_invocation_writes_to_file(self, audit_logger):
        audit_logger.log_invocation(
            tool_name="search_documents",
            tool_call_id="call_1",
            user_id="user_1",
            request_id="req_1",
            params={"query": "RAG"},
            result_status="success",
            duration_ms=12.5,
        )
        assert os.path.exists(audit_logger._audit_file)
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["tool_name"] == "search_documents"

    def test_multiple_events_appended(self, audit_logger):
        for i in range(5):
            audit_logger.log_invocation(
                tool_name=f"tool_{i}",
                tool_call_id=f"call_{i}",
                params={"index": i},
            )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_read_records_returns_all(self, audit_logger):
        audit_logger.log_invocation(tool_name="t1", tool_call_id="c1")
        audit_logger.log_invocation(tool_name="t2", tool_call_id="c2")
        audit_logger.log_invocation(tool_name="t1", tool_call_id="c3")
        records = audit_logger.read_records(limit=10)
        assert len(records) == 3

    def test_read_records_filter_by_tool_name(self, audit_logger):
        audit_logger.log_invocation(tool_name="search_documents", tool_call_id="c1")
        audit_logger.log_invocation(tool_name="get_metadata", tool_call_id="c2")
        audit_logger.log_invocation(tool_name="search_documents", tool_call_id="c3")
        records = audit_logger.read_records(limit=10, tool_name="search_documents")
        assert len(records) == 2
        assert all(r["tool_name"] == "search_documents" for r in records)

    def test_read_records_respects_limit(self, audit_logger):
        for i in range(10):
            audit_logger.log_invocation(tool_name="t", tool_call_id=f"c{i}")
        records = audit_logger.read_records(limit=3)
        assert len(records) == 3

    def test_read_records_most_recent_first(self, audit_logger):
        audit_logger.log_invocation(tool_name="t", tool_call_id="first")
        audit_logger.log_invocation(tool_name="t", tool_call_id="last")
        records = audit_logger.read_records(limit=2)
        assert records[0]["tool_call_id"] == "last"
        assert records[1]["tool_call_id"] == "first"

    def test_read_records_returns_empty_for_stdout(self):
        from tools.audit import AuditDestination, ToolAuditLogger

        al = ToolAuditLogger(destination=AuditDestination.STDOUT)
        assert al.read_records() == []

    def test_read_records_no_file_graceful(self):
        from tools.audit import AuditDestination, ToolAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "nonexistent")
            al = ToolAuditLogger(destination=AuditDestination.FILE, log_dir=log_path)
            assert al.read_records() == []


class TestToolAuditLoggerBoth:
    """Tests for ToolAuditLogger with both destinations."""

    @pytest.fixture
    def audit_logger(self):
        from tools.audit import AuditDestination, ToolAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            yield ToolAuditLogger(destination=AuditDestination.BOTH, log_dir=tmpdir)

    def test_log_invocation_writes_to_both(self, audit_logger):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            audit_logger.log_invocation(
                tool_name="search_documents",
                tool_call_id="call_both",
                params={"q": "test"},
            )
        finally:
            sys.stdout = sys.__stdout__

        stdout_record = json.loads(captured.getvalue().strip())
        assert stdout_record["tool_call_id"] == "call_both"

        with open(audit_logger._audit_file) as f:
            file_record = json.loads(f.readline())
        assert file_record["tool_call_id"] == "call_both"


class TestLogFromResult:
    """Tests for log_from_result using ToolResult and ToolContext."""

    def test_log_from_result_success(self):
        from tools.audit import AuditDestination, ToolAuditLogger
        from tools.definition import ToolResult
        from tools.sdk import ToolContext

        captured = io.StringIO()
        sys.stdout = captured
        try:
            al = ToolAuditLogger(destination=AuditDestination.STDOUT)
            result = ToolResult(
                tool_name="search_documents",
                tool_call_id="call_1",
                content="Found 3 results",
                duration_ms=15.0,
            )
            context = ToolContext(user_id="user_1", request_id="req_1")
            al.log_from_result(result, context=context, params={"query": "RAG"})
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["tool_name"] == "search_documents"
        assert record["tool_call_id"] == "call_1"
        assert record["user_id"] == "user_1"
        assert record["request_id"] == "req_1"
        assert record["result_status"] == "success"
        assert record["duration_ms"] == 15.0

    def test_log_from_result_error(self):
        from tools.audit import AuditDestination, ToolAuditLogger
        from tools.definition import ToolResult
        from tools.sdk import ToolContext

        captured = io.StringIO()
        sys.stdout = captured
        try:
            al = ToolAuditLogger(destination=AuditDestination.STDOUT)
            result = ToolResult(
                tool_name="unknown_tool",
                tool_call_id="call_err",
                error="Tool not found",
            )
            context = ToolContext(user_id="user_2", request_id="req_2")
            al.log_from_result(result, context=context)
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["result_status"] == "error"
        assert record["error"] == "Tool not found"
        assert record["user_id"] == "user_2"

    def test_log_from_result_no_context(self):
        from tools.audit import AuditDestination, ToolAuditLogger
        from tools.definition import ToolResult

        captured = io.StringIO()
        sys.stdout = captured
        try:
            al = ToolAuditLogger(destination=AuditDestination.STDOUT)
            result = ToolResult(tool_name="test_tool", tool_call_id="c1")
            al.log_from_result(result)
        finally:
            sys.stdout = sys.__stdout__

        record = json.loads(captured.getvalue().strip())
        assert record["user_id"] is None
        assert record["request_id"] == ""
