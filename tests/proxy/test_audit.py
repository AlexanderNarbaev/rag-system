# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/audit.py audit logging module."""

import datetime
import json
import os
import tempfile
import time

import pytest

from proxy.app.shared.audit import AuditEvent, AuditLogger, RequestTracker


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_create_basic_event(self):
        event = AuditEvent(
            event_id="evt_123",
            timestamp="2025-01-01T00:00:00Z",
            event_type="query",
            user_id="user1",
            client_ip="127.0.0.1",
            endpoint="/v1/chat/completions",
            request_hash="abc123",
            result_status="success",
        )
        assert event.event_id == "evt_123"
        assert event.event_type == "query"
        assert event.result_status == "success"

    def test_to_dict_excludes_none(self):
        event = AuditEvent(
            event_id="evt_1",
            timestamp="2025-01-01T00:00:00Z",
            event_type="query",
            user_id=None,
            client_ip="10.0.0.1",
            endpoint="/v1/test",
            request_hash="hash1",
            details={"key": "val"},
        )
        d = event.to_dict()
        assert "user_id" not in d
        assert d["client_ip"] == "10.0.0.1"
        assert d["details"] == {"key": "val"}

    def test_to_json_serializable(self):
        event = AuditEvent(
            event_id="evt_json",
            timestamp="2025-01-01T00:00:00Z",
            event_type="access_denied",
            user_id="user2",
            client_ip="192.168.1.1",
            endpoint="/admin",
            request_hash="n/a",
            details={"reason": "forbidden"},
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "access_denied"
        assert parsed["details"]["reason"] == "forbidden"

    def test_fields_have_correct_types(self):
        event = AuditEvent(
            event_id="evt_types",
            timestamp="2025-06-22T10:00:00Z",
            event_type="error",
            user_id="u1",
            client_ip="1.2.3.4",
            endpoint="/error",
            request_hash="hash_err",
            duration_ms=42.5,
            tokens_used=100,
            result_status="error",
        )
        assert isinstance(event.event_id, str)
        assert isinstance(event.duration_ms, float)
        assert isinstance(event.tokens_used, int)
        assert isinstance(event.to_dict(), dict)


class TestAuditLogger:
    """Tests for AuditLogger class."""

    @pytest.fixture
    def audit_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AuditLogger(log_dir=tmpdir)

    def test_log_query_writes_event(self, audit_logger):
        audit_logger.log_query(
            user_id="user1",
            query="What is RAG?",
            response_preview="RAG is a technique.",
            chunks=5,
            duration_ms=100.0,
            tokens=50,
            client_ip="10.0.0.1",
        )
        assert os.path.exists(audit_logger._audit_file)
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "query"
        assert "What is RAG?" in event["details"]["query_preview"]

    def test_log_access_denied(self, audit_logger):
        audit_logger.log_access_denied(
            user_id="user2",
            resource="/admin/config",
            reason="insufficient_permissions",
            client_ip="10.0.0.2",
        )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "access_denied"
        assert event["result_status"] == "denied"

    def test_log_config_change(self, audit_logger):
        audit_logger.log_config_change(
            user_id="admin",
            key="MAX_CHUNKS_RETRIEVAL",
            old_value="50",
            new_value="100",
            client_ip="10.0.0.1",
        )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "config_change"
        assert "MAX_CHUNKS_RETRIEVAL" in event["details"]["config_key"]
        assert event["details"]["old_value"] != "50"  # masked

    def test_log_error(self, audit_logger):
        audit_logger.log_error(
            error_type="ValueError",
            error_msg="Invalid input parameter",
            stack_trace="Traceback line 1\nTraceback line 2",
            context={"user_id": "user3", "endpoint": "/api"},
            client_ip="10.0.0.3",
            endpoint="/v1/chat/completions",
        )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "error"
        assert event["result_status"] == "error"

    def test_log_auth(self, audit_logger):
        audit_logger.log_auth(
            user_id="user4",
            action="login",
            success=True,
            details={"method": "api_key"},
            client_ip="10.0.0.4",
        )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "login"
        assert event["result_status"] == "success"

    def test_log_auth_failure(self, audit_logger):
        audit_logger.log_auth(
            user_id=None,
            action="login",
            success=False,
            details={"reason": "invalid_credentials"},
            client_ip="10.0.0.5",
        )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["result_status"] == "failure"

    def test_multiple_events_appended(self, audit_logger):
        for i in range(5):
            audit_logger.log_query(
                user_id=f"user_{i}",
                query=f"query {i}",
                response_preview=f"response {i}",
                chunks=i,
                duration_ms=i * 10.0,
                tokens=i * 5,
            )
        with open(audit_logger._audit_file) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_query_history_filter_by_user(self, audit_logger):
        audit_logger.log_query(user_id="alice", query="q1", response_preview="r1", chunks=1, duration_ms=10, tokens=5)
        audit_logger.log_query(user_id="bob", query="q2", response_preview="r2", chunks=2, duration_ms=20, tokens=10)
        audit_logger.log_query(user_id="alice", query="q3", response_preview="r3", chunks=3, duration_ms=30, tokens=15)
        results = audit_logger.query_history(user_id="alice", limit=10)
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_query_history_limit(self, audit_logger):
        for i in range(10):
            audit_logger.log_query(
                user_id="u1", query=f"q{i}", response_preview="r", chunks=1, duration_ms=10, tokens=1
            )
        results = audit_logger.query_history(limit=3)
        assert len(results) == 3

    def test_query_history_start_time_filter(self, audit_logger):
        datetime.datetime.now(datetime.UTC).isoformat()
        time.sleep(0.01)
        audit_logger.log_query(user_id="u1", query="after", response_preview="r", chunks=1, duration_ms=10, tokens=1)
        time.sleep(0.01)
        t2 = datetime.datetime.now(datetime.UTC).isoformat()
        audit_logger.log_query(
            user_id="u1", query="even_later", response_preview="r", chunks=1, duration_ms=10, tokens=1
        )
        results = audit_logger.query_history(user_id="u1", limit=10, start_time=t2)
        assert len(results) == 1

    def test_export_report(self, audit_logger):
        t_start = "2025-01-01T00:00:00"
        t_end = "2030-12-31T23:59:59"
        audit_logger.log_query(user_id="u1", query="q1", response_preview="r1", chunks=2, duration_ms=50, tokens=100)
        audit_logger.log_error(error_type="TestError", error_msg="test", stack_trace=None)
        report = audit_logger.export_report(start_time=t_start, end_time=t_end)
        data = json.loads(report)
        assert data["summary"]["total_events"] == 2
        assert data["summary"]["queries"] == 1
        assert data["summary"]["errors"] == 1

    def test_export_report_empty(self, audit_logger):
        t_start = "2020-01-01T00:00:00"
        t_end = "2020-12-31T23:59:59"
        report = audit_logger.export_report(start_time=t_start, end_time=t_end)
        data = json.loads(report)
        assert data["summary"]["total_events"] == 0

    def test_export_report_invalid_time(self, audit_logger):
        report = audit_logger.export_report(start_time="invalid", end_time="also_invalid")
        data = json.loads(report)
        assert "error" in data

    def test_query_history_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            al = AuditLogger(log_dir=tmpdir)
            results = al.query_history(limit=10)
            assert results == []

    def test_export_report_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            al = AuditLogger(log_dir=tmpdir)
            report = al.export_report(start_time="2025-01-01T00:00:00", end_time="2025-12-31T00:00:00")
            data = json.loads(report)
            assert data["summary"]["total_events"] == 0


class TestRequestTracker:
    """Tests for RequestTracker class."""

    def test_start_and_complete(self):
        tracker = RequestTracker()
        tracker.start("req_1")
        assert tracker.active_requests == 1
        result = tracker.complete("req_1", status="success", tokens=100)
        assert result is not None
        assert result["status"] == "success"
        assert result["tokens"] == 100
        assert result["duration_ms"] >= 0
        assert tracker.active_requests == 0

    def test_complete_unknown_id(self):
        tracker = RequestTracker()
        result = tracker.complete("nonexistent")
        assert result is None

    def test_active_requests_count(self):
        tracker = RequestTracker()
        assert tracker.active_requests == 0
        tracker.start("a")
        tracker.start("b")
        tracker.start("c")
        assert tracker.active_requests == 3
        tracker.complete("a")
        assert tracker.active_requests == 2
        tracker.complete("b")
        tracker.complete("c")
        assert tracker.active_requests == 0

    def test_start_with_metadata(self):
        tracker = RequestTracker()
        tracker.start("req_m", metadata={"user": "alice", "model": "test-model"})
        tracker.complete("req_m")
        assert tracker.active_requests == 0
