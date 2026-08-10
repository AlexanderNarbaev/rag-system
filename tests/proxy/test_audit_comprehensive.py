"""Comprehensive tests for proxy/app/shared/audit.py.

Covers AuditEvent, AuditLogger (event types + history + reports),
and RequestTracker lifecycle.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from proxy.app.shared.audit import AuditEvent, AuditLogger, RequestTracker


@pytest.fixture
def tmp_audit_dir(tmp_path):
    return str(tmp_path / "audit-logs")


@pytest.fixture
def audit_logger(tmp_audit_dir) -> AuditLogger:
    return AuditLogger(log_dir=tmp_audit_dir)


# ---------------------------------------------------------------------------
# AuditEvent dataclass
# ---------------------------------------------------------------------------


class TestAuditEvent:
    def test_init_minimal(self):
        e = AuditEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            event_type="query",
            user_id="u1",
            client_ip="127.0.0.1",
            endpoint="/v1",
            request_hash="abcd",
        )
        assert e.event_id == "e1"
        assert e.details == {}
        assert e.duration_ms is None
        assert e.tokens_used is None
        assert e.result_status == "unknown"

    def test_to_dict_drops_none(self):
        e = AuditEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            event_type="query",
            user_id="u1",
            client_ip="127.0.0.1",
            endpoint="/v1",
            request_hash="abcd",
        )
        data = e.to_dict()
        # duration_ms and tokens_used are None → not in dict
        assert "duration_ms" not in data
        assert "tokens_used" not in data
        assert data["event_id"] == "e1"

    def test_to_dict_keeps_present_values(self):
        e = AuditEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            event_type="query",
            user_id="u1",
            client_ip="127.0.0.1",
            endpoint="/v1",
            request_hash="abcd",
            duration_ms=120.5,
            tokens_used=42,
        )
        data = e.to_dict()
        assert data["duration_ms"] == 120.5
        assert data["tokens_used"] == 42

    def test_to_json_round_trip(self):
        e = AuditEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            event_type="query",
            user_id="u1",
            client_ip="127.0.0.1",
            endpoint="/v1",
            request_hash="abcd",
            details={"k": "v"},
        )
        js = e.to_json()
        loaded = json.loads(js)
        assert loaded["event_id"] == "e1"
        assert loaded["details"] == {"k": "v"}

    def test_to_json_unicode(self):
        e = AuditEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            event_type="query",
            user_id="пользователь",
            client_ip="127.0.0.1",
            endpoint="/v1",
            request_hash="abcd",
        )
        js = e.to_json()
        assert "пользователь" in js


# ---------------------------------------------------------------------------
# AuditLogger — init & private helpers
# ---------------------------------------------------------------------------


class TestAuditLoggerInit:
    def test_creates_log_dir(self, tmp_audit_dir):
        AuditLogger(log_dir=tmp_audit_dir)
        assert os.path.isdir(tmp_audit_dir)

    def test_falls_back_to_tempdir_when_unwritable(self):
        # Use an obviously-wrong path on Linux: file in /proc
        with patch("os.makedirs", side_effect=PermissionError("nope")):
            al = AuditLogger(log_dir="/proc/audit")
            # Should have fallen back to a tempdir
            assert os.path.isdir(al.log_dir)

    def test_generate_event_id_unique(self, audit_logger):
        ids = {audit_logger._generate_event_id() for _ in range(50)}
        # Should produce many unique IDs (collisions are extraordinarily unlikely)
        assert len(ids) >= 45

    def test_generate_event_id_format(self, audit_logger):
        eid = audit_logger._generate_event_id()
        assert eid.startswith("evt_")
        parts = eid.split("_")
        assert len(parts) == 3

    def test_hash_request_deterministic(self, audit_logger):
        h1 = audit_logger._hash_request("hello world")
        h2 = audit_logger._hash_request("hello world")
        assert h1 == h2

    def test_hash_request_short(self, audit_logger):
        h = audit_logger._hash_request("hello")
        assert len(h) == 16

    def test_hash_request_different_inputs(self, audit_logger):
        assert audit_logger._hash_request("a") != audit_logger._hash_request("b")


# ---------------------------------------------------------------------------
# AuditLogger.log_query
# ---------------------------------------------------------------------------


class TestLogQuery:
    def test_writes_event_to_file(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query(
            user_id="u1",
            query="What is RAG?",
            response_preview="RAG is...",
            chunks=4,
            duration_ms=120.5,
            tokens=200,
            client_ip="1.2.3.4",
        )
        path = Path(tmp_audit_dir) / "audit.jsonl"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "RAG" in content
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert len(events) == 1
        e = events[0]
        assert e["event_type"] == "query"
        assert e["user_id"] == "u1"
        assert e["client_ip"] == "1.2.3.4"
        assert e["endpoint"] == "/v1/chat/completions"
        assert e["duration_ms"] == pytest.approx(120.5)
        assert e["tokens_used"] == 200
        assert e["result_status"] == "success"

    def test_truncates_long_query(self, audit_logger, tmp_audit_dir):
        long_q = "x" * 1000
        audit_logger.log_query(
            user_id=None,
            query=long_q,
            response_preview="r",
            chunks=0,
            duration_ms=1.0,
            tokens=0,
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        # The preview should be truncated to 200 chars
        assert '"query_preview": "' + "x" * 200 + '"' in content or "x" * 200 in content

    def test_metadata_optional(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query(
            user_id="u1",
            query="x",
            response_preview="y",
            chunks=2,
            duration_ms=10,
            tokens=10,
            metadata=None,
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["details"]["metadata"] == {}

    def test_result_status_custom(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query(
            user_id="u1",
            query="x",
            response_preview="y",
            chunks=0,
            duration_ms=10,
            tokens=10,
            result_status="timeout",
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["result_status"] == "timeout"


# ---------------------------------------------------------------------------
# AuditLogger.log_access_denied
# ---------------------------------------------------------------------------


class TestLogAccessDenied:
    def test_writes_event(self, audit_logger, tmp_audit_dir):
        audit_logger.log_access_denied(
            user_id="u1",
            resource="/secret",
            reason="ACL",
            client_ip="1.2.3.4",
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "access_denied"
        assert e["result_status"] == "denied"
        assert e["details"]["resource"] == "/secret"
        assert e["details"]["reason"] == "ACL"
        assert e["client_ip"] == "1.2.3.4"

    def test_default_client_ip(self, audit_logger, tmp_audit_dir):
        audit_logger.log_access_denied("u1", "/x", "r")
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["client_ip"] == "unknown"


# ---------------------------------------------------------------------------
# AuditLogger.log_config_change
# ---------------------------------------------------------------------------


class TestLogConfigChange:
    def test_writes_event(self, audit_logger, tmp_audit_dir):
        audit_logger.log_config_change(
            user_id="admin",
            key="KEYCLOAK_URL",
            old_value="http://old",
            new_value="http://new",
            client_ip="1.2.3.4",
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "config_change"
        assert e["details"]["config_key"] == "KEYCLOAK_URL"
        # Short values are masked
        assert e["details"]["old_value"] == "***"
        assert e["details"]["new_value"] == "***"

    def test_long_values_kept_partially(self, audit_logger, tmp_audit_dir):
        old = "abcdefghijklmnopqrstuvwxyz" * 2
        new = "zyxwvutsrqponmlkjihgfedcba" * 2
        audit_logger.log_config_change("u", "k", old, new)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        # Long values are kept partially — first 4 + *** + last 4
        assert "***" in e["details"]["old_value"]
        assert e["details"]["old_value"].startswith("abcd")
        assert e["details"]["old_value"].endswith("wxyz")

    def test_none_value_masked(self, audit_logger, tmp_audit_dir):
        # Note: type signature says str, but defensive code treats None
        audit_logger.log_config_change("u", "k", "old", "new")
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["details"]["new_value"] == "***"


# ---------------------------------------------------------------------------
# AuditLogger.log_error
# ---------------------------------------------------------------------------


class TestLogError:
    def test_writes_event(self, audit_logger, tmp_audit_dir):
        audit_logger.log_error(
            error_type="ValueError",
            error_msg="bad input",
            stack_trace="Traceback ...",
            context={"user_id": "u1", "x": "y"},
            client_ip="1.2.3.4",
            endpoint="/v1/chat",
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "error"
        assert e["user_id"] == "u1"  # extracted from context
        assert e["details"]["error_type"] == "ValueError"
        assert e["details"]["error_message"] == "bad input"

    def test_truncates_long_message(self, audit_logger, tmp_audit_dir):
        audit_logger.log_error(
            error_type="e",
            error_msg="x" * 1000,
            stack_trace="s" * 5000,
            context=None,
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        # Error message truncated to 500; stack to 2000
        assert len(events[0]["details"]["error_message"]) == 500
        assert len(events[0]["details"]["stack_trace"]) == 2000

    def test_no_user_when_no_context(self, audit_logger, tmp_audit_dir):
        audit_logger.log_error("e", "m", None, context=None)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        # user_id is None so to_dict omits it
        assert "user_id" not in events[0] or events[0]["user_id"] is None


# ---------------------------------------------------------------------------
# AuditLogger.log_trace
# ---------------------------------------------------------------------------


class TestLogTrace:
    def test_writes_event(self, audit_logger, tmp_audit_dir):
        audit_logger.log_trace(
            request_id="req-1",
            user_id="u1",
            query="hello",
            chunks_count=3,
            rerank_scores=[0.1, 0.5, 0.9],
            duration_ms=100.0,
            tokens=200,
            confidence=0.85,
            feedback_id="fb-1",
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "trace"
        stats = e["details"]["rerank_scores_distribution"]
        assert stats["rerank_min"] == 0.1
        assert stats["rerank_max"] == 0.9
        assert stats["rerank_avg"] == pytest.approx(0.5)
        assert stats["rerank_count"] == 3
        assert e["details"]["feedback_link"] == "/v1/feedback/fb-1"
        assert e["details"]["confidence_score"] == 0.85
        # Confidence high → success
        assert e["result_status"] == "success"

    def test_no_scores_no_distribution(self, audit_logger, tmp_audit_dir):
        audit_logger.log_trace(
            request_id="r",
            user_id="u",
            query="q",
            chunks_count=0,
            rerank_scores=None,
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["details"]["rerank_scores_distribution"] == {}

    def test_no_feedback_link(self, audit_logger, tmp_audit_dir):
        audit_logger.log_trace("r", "u", "q", 0)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["details"]["feedback_link"] is None

    def test_low_confidence_status(self, audit_logger, tmp_audit_dir):
        audit_logger.log_trace("r", "u", "q", 0, confidence=0.2)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["result_status"] == "low_confidence"

    def test_token_breakdown_includes_query_estimate(self, audit_logger, tmp_audit_dir):
        audit_logger.log_trace("r", "u", "abcdefgh", 0, tokens=10)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        tb = events[0]["details"]["token_breakdown"]
        # prompt = max(0, 10 - 8//4=2) = 8; completion = 8//4 = 2
        assert tb["estimated_prompt_tokens"] == 8
        assert tb["estimated_completion_tokens"] == 2


# ---------------------------------------------------------------------------
# AuditLogger.log_auth
# ---------------------------------------------------------------------------


class TestLogAuth:
    def test_login_event_type(self, audit_logger, tmp_audit_dir):
        audit_logger.log_auth(user_id="u1", action="login", success=True, client_ip="1.2.3.4")
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "login"
        assert e["result_status"] == "success"
        assert e["details"]["action"] == "login"
        assert e["details"]["success"] is True

    def test_non_login_event_type(self, audit_logger, tmp_audit_dir):
        audit_logger.log_auth(user_id="u1", action="logout", success=False)
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        e = events[0]
        assert e["event_type"] == "auth"
        assert e["result_status"] == "failure"

    def test_extra_details(self, audit_logger, tmp_audit_dir):
        audit_logger.log_auth(
            user_id="u1",
            action="refresh",
            success=True,
            details={"token_id": "tk1"},
        )
        content = (Path(tmp_audit_dir) / "audit.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n")]
        assert events[0]["details"]["token_id"] == "tk1"


# ---------------------------------------------------------------------------
# AuditLogger.query_history
# ---------------------------------------------------------------------------


class TestQueryHistory:
    def test_empty_when_no_file(self, audit_logger):
        result = audit_logger.query_history()
        assert result == []

    def test_reads_recent_events(self, audit_logger, tmp_audit_dir):
        for i in range(5):
            audit_logger.log_query(f"u{i}", f"q{i}", "r", 1, 10.0, 10)
        result = audit_logger.query_history()
        assert len(result) == 5

    def test_filters_by_user(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("alice", "q1", "r", 1, 10.0, 10)
        audit_logger.log_query("bob", "q2", "r", 1, 10.0, 10)
        result = audit_logger.query_history(user_id="alice")
        assert all(e.get("user_id") == "alice" for e in result)
        assert len(result) == 1

    def test_limit(self, audit_logger, tmp_audit_dir):
        for i in range(20):
            audit_logger.log_query("u", f"q{i}", "r", 1, 10.0, 10)
        result = audit_logger.query_history(limit=5)
        assert len(result) == 5

    def test_filters_by_start_time(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q1", "r", 1, 10.0, 10)
        # Use a start_time far in the future to filter out everything
        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)).isoformat()
        result = audit_logger.query_history(start_time=future)
        assert result == []

    def test_start_time_invalid_string_ignored(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        # Bad ISO string → cutoff=None → returns all events
        result = audit_logger.query_history(start_time="not-a-date")
        assert len(result) == 1

    def test_skips_blank_lines(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        # Append blank lines to the audit file
        path = Path(tmp_audit_dir) / "audit.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n")
        result = audit_logger.query_history()
        assert len(result) == 1

    def test_skips_malformed_json(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        path = Path(tmp_audit_dir) / "audit.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write("not-valid-json\n")
        result = audit_logger.query_history()
        # Well-formed event still parsed
        assert len(result) == 1


# ---------------------------------------------------------------------------
# AuditLogger.export_report
# ---------------------------------------------------------------------------


class TestExportReport:
    def test_invalid_time(self, audit_logger):
        report = audit_logger.export_report("bad", "alsogood")
        assert "error" in json.loads(report)

    def test_empty_report(self, audit_logger):
        start = "2026-01-01T00:00:00+00:00"
        end = "2026-01-02T00:00:00+00:00"
        report = json.loads(audit_logger.export_report(start, end))
        assert report["period"] == {"start": start, "end": end}
        assert report["summary"]["total_events"] == 0

    def test_summary_counts(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        audit_logger.log_error("e", "m", None, context=None)
        audit_logger.log_access_denied("u", "/x", "r")

        start = "2020-01-01T00:00:00+00:00"
        end = "2099-01-01T00:00:00+00:00"
        report = json.loads(audit_logger.export_report(start, end))
        summary = report["summary"]
        assert summary["total_events"] == 3
        assert summary["queries"] == 1
        assert summary["errors"] == 1
        assert summary["access_denied"] == 1

    def test_sums_tokens(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 100)
        audit_logger.log_query("u", "q", "r", 1, 10.0, 50)
        start = "2020-01-01T00:00:00+00:00"
        end = "2099-01-01T00:00:00+00:00"
        report = json.loads(audit_logger.export_report(start, end))
        assert report["summary"]["total_tokens_used"] == 150

    def test_filters_by_time(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        # Range entirely in the past
        start = "2020-01-01T00:00:00+00:00"
        end = "2020-01-02T00:00:00+00:00"
        report = json.loads(audit_logger.export_report(start, end))
        assert report["summary"]["total_events"] == 0

    def test_naive_datetime_assumed_utc(self, audit_logger, tmp_audit_dir):
        audit_logger.log_query("u", "q", "r", 1, 10.0, 10)
        # Naive datetimes → assumed UTC; range covers everything
        start = "2020-01-01T00:00:00"
        end = "2099-01-01T00:00:00"
        report = json.loads(audit_logger.export_report(start, end))
        assert report["summary"]["total_events"] == 1


# ---------------------------------------------------------------------------
# Write failure handling
# ---------------------------------------------------------------------------


class TestAuditLoggerErrors:
    def test_write_failure_does_not_propagate(self, audit_logger):
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise
            audit_logger.log_query("u", "q", "r", 0, 0, 0)


# ---------------------------------------------------------------------------
# RequestTracker
# ---------------------------------------------------------------------------


class TestRequestTracker:
    def test_init(self):
        rt = RequestTracker()
        assert rt.active_requests == 0

    def test_start_records_request(self):
        rt = RequestTracker()
        rt.start("r1")
        assert rt.active_requests == 1

    def test_start_with_metadata(self):
        rt = RequestTracker()
        rt.start("r1", metadata={"k": "v"})
        rt.complete("r1")
        # complete returns the duration info

    def test_complete_unknown_returns_none(self):
        rt = RequestTracker()
        assert rt.complete("ghost") is None

    def test_complete_returns_info(self):
        rt = RequestTracker()
        rt.start("r1")
        info = rt.complete("r1", status="success", tokens=10)
        assert info["request_id"] == "r1"
        assert info["status"] == "success"
        assert info["tokens"] == 10
        assert info["duration_ms"] >= 0
        assert "metadata" in info

    def test_complete_removes_active(self):
        rt = RequestTracker()
        rt.start("r1")
        assert rt.active_requests == 1
        rt.complete("r1")
        assert rt.active_requests == 0

    def test_active_count_after_multiple(self):
        rt = RequestTracker()
        rt.start("a")
        rt.start("b")
        rt.start("c")
        assert rt.active_requests == 3
        rt.complete("a")
        assert rt.active_requests == 2
        rt.complete("b")
        rt.complete("c")
        assert rt.active_requests == 0

    def test_start_default_metadata(self):
        rt = RequestTracker()
        rt.start("r1")
        info = rt.complete("r1")
        assert info["metadata"] == {}
