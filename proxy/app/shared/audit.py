# proxy/app/audit.py
"""Audit logging and tracking for all RAG operations."""

import datetime
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger ("rag-proxy.audit")


@dataclass
class AuditEvent:
  """Single auditable event in the RAG system."""

  event_id: str
  timestamp: str
  event_type: str  # query, login, access_denied, config_change, error
  user_id: str | None
  client_ip: str
  endpoint: str
  request_hash: str
  details: dict [str, Any] = field (default_factory = dict)
  duration_ms: float | None = None
  tokens_used: int | None = None
  result_status: str = "unknown"

  def to_dict (self) -> dict [str, Any]:
    data = asdict (self)
    return {k: v for k, v in data.items () if v is not None}

  def to_json (self) -> str:
    return json.dumps (self.to_dict (), ensure_ascii = False)


class AuditLogger:
  """Writes audit events to JSONL file and optional syslog."""

  def __init__ (self, log_dir: str = "/var/log/rag-system"):
    self.log_dir = log_dir
    os.makedirs (log_dir, exist_ok = True)
    self._audit_file = os.path.join (log_dir, "audit.jsonl")

  def _write_event (self, event: AuditEvent) -> None:
    """Write an audit event to the JSONL file."""
    try:
      with open (self._audit_file, "a", encoding = "utf-8") as f:
        f.write (event.to_json () + "\n")
      logger.debug (f"Audit event recorded: {event.event_id} ({event.event_type})")
    except Exception as e:
      logger.error (f"Failed to write audit event: {e}")

  def _generate_event_id (self) -> str:
    ts = int (time.time () * 1_000_000)
    rand = os.urandom (6).hex ()
    return f"evt_{ts}_{rand}"

  def _hash_request (self, query: str) -> str:
    return hashlib.sha256 (query.encode ("utf-8")).hexdigest () [:16]

  def log_query (
      self, user_id: str | None, query: str, response_preview: str, chunks: int, duration_ms: float, tokens: int,
      client_ip: str = "unknown", endpoint: str = "/v1/chat/completions", result_status: str = "success",
      metadata: dict [str, Any] | None = None, ) -> None:
    """Log a query event."""
    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (), event_type = "query", user_id = user_id,
        client_ip = client_ip, endpoint = endpoint, request_hash = self._hash_request (query), details = {
            "query_preview": query [:200], "response_preview": response_preview [:200], "chunks_retrieved": chunks,
            "metadata": metadata or {},
        }, duration_ms = round (duration_ms, 2), tokens_used = tokens, result_status = result_status, )
    self._write_event (event)

  def log_access_denied (self, user_id: str | None, resource: str, reason: str, client_ip: str = "unknown") -> None:
    """Log an access denied event."""
    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (), event_type = "access_denied", user_id = user_id,
        client_ip = client_ip, endpoint = resource, request_hash = "n/a", details = {
            "resource": resource, "reason": reason,
        }, result_status = "denied", )
    self._write_event (event)

  def log_config_change (
      self, user_id: str | None, key: str, old_value: str, new_value: str, client_ip: str = "unknown", ) -> None:
    """Log configuration changes (values masked)."""

    def mask_val (v: str) -> str:
      if v is None:
        return "***"
      if len (v) > 20:
        return v [:4] + "***" + v [-4:]
      return "***"

    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (), event_type = "config_change", user_id = user_id,
        client_ip = client_ip, endpoint = "/admin/config", request_hash = "n/a", details = {
            "config_key": key, "old_value": mask_val (old_value), "new_value": mask_val (new_value),
        }, result_status = "success", )
    self._write_event (event)

  def log_error (
      self, error_type: str, error_msg: str, stack_trace: str | None, context: dict [str, Any] | None = None,
      client_ip: str = "unknown", endpoint: str = "unknown", ) -> None:
    """Log error events."""
    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (), event_type = "error",
        user_id = context.get ("user_id") if context else None, client_ip = client_ip, endpoint = endpoint,
        request_hash = "n/a", details = {
            "error_type": error_type, "error_message": error_msg [:500], "stack_trace": (stack_trace or "") [:2000],
            "context": context or {},
        }, result_status = "error", )
    self._write_event (event)

  def log_trace (
      self, request_id: str, user_id: str | None, query: str, chunks_count: int,
      rerank_scores: list [float] | None = None, duration_ms: float = 0.0, tokens: int = 0,
      confidence: float | None = None, feedback_id: str | None = None, client_ip: str = "unknown",
      metadata: dict [str, Any] | None = None, ) -> None:
    """Log detailed per-request trace with retrieval and observability metadata.

    Includes:
    - Retrieval latency per source
    - Chunk retrieval count
    - Rerank scores distribution (min, max, avg)
    - Token usage breakdown
    - Confidence score
    - Feedback link
    """
    scores = rerank_scores or []
    score_stats = {}
    if scores:
      score_stats = {
          "rerank_min": round (min (scores), 4), "rerank_max": round (max (scores), 4),
          "rerank_avg": round (sum (scores) / len (scores), 4), "rerank_count": len (scores),
      }

    feedback_link = f"/v1/feedback/{feedback_id}" if feedback_id else None

    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (), event_type = "trace", user_id = user_id,
        client_ip = client_ip, endpoint = "/v1/chat/completions", request_hash = self._hash_request (query), details = {
            "query_preview": query [:200], "chunks_retrieved": chunks_count, "rerank_scores_distribution": score_stats,
            "token_breakdown": {
                "total_tokens": tokens, "estimated_prompt_tokens": max (0, tokens - (len (query) // 4)),
                "estimated_completion_tokens": len (query) // 4,
            }, "confidence_score": confidence, "feedback_link": feedback_link, "metadata": metadata or {},
        }, duration_ms = round (duration_ms, 2), tokens_used = tokens,
        result_status = "success" if confidence is None or confidence >= 0.5 else "low_confidence", )
    self._write_event (event)

  def log_auth (
      self, user_id: str | None, action: str, success: bool, details: dict [str, Any] | None = None,
      client_ip: str = "unknown", ) -> None:
    """Log authentication events."""
    event = AuditEvent (event_id = self._generate_event_id (),
        timestamp = datetime.datetime.now (datetime.UTC).isoformat (),
        event_type = "login" if action == "login" else "auth", user_id = user_id, client_ip = client_ip,
        endpoint = "/auth", request_hash = "n/a", details = {
            "action": action, "success": success, **(details or {}),
        }, result_status = "success" if success else "failure", )
    self._write_event (event)

  def query_history (
      self, user_id: str | None = None, limit: int = 100, start_time: str | None = None, ) -> list [dict [str, Any]]:
    """Read audit log with filters."""
    results: list [dict [str, Any]] = []
    if not os.path.exists (self._audit_file):
      return results

    if start_time:
      try:
        cutoff = datetime.datetime.fromisoformat (start_time)
      except (ValueError, TypeError):
        cutoff = None
    else:
      cutoff = None

    try:
      with open (self._audit_file, encoding = "utf-8") as f:
        lines = f.readlines ()
    except Exception as e:
      logger.error (f"Failed to read audit log: {e}")
      return results

    for line in reversed (lines):
      line = line.strip ()
      if not line:
        continue
      try:
        record = json.loads (line)
      except json.JSONDecodeError:
        continue

      if user_id and record.get ("user_id") != user_id:
        continue
      if cutoff:
        try:
          event_time = datetime.datetime.fromisoformat (record ["timestamp"])
          if event_time < cutoff:
            continue
        except (ValueError, KeyError):
          pass

      results.append (record)
      if len (results) >= limit:
        break

    return results

  def export_report (self, start_time: str, end_time: str, fmt: str = "json") -> str:
    """Generate usage report for time period."""
    try:
      start_dt = datetime.datetime.fromisoformat (start_time)
      end_dt = datetime.datetime.fromisoformat (end_time)
    except (ValueError, TypeError):
      return json.dumps ({"error": "invalid time format"})

    events = []
    if not os.path.exists (self._audit_file):
      report = {
          "period": {"start": start_time, "end": end_time}, "summary": {
              "total_events": 0, "queries": 0, "errors": 0, "access_denied": 0, "total_tokens_used": 0,
          }, "events": [],
      }
      return json.dumps (report, ensure_ascii = False, indent = 2)

    try:
      with open (self._audit_file, encoding = "utf-8") as f:
        for line in f:
          line = line.strip ()
          if not line:
            continue
          try:
            rec = json.loads (line)
            ts = datetime.datetime.fromisoformat (rec ["timestamp"])
            if ts.tzinfo is None:
              ts = ts.replace (tzinfo = datetime.UTC)
            if start_dt.tzinfo is None:
              start_dt = start_dt.replace (tzinfo = datetime.UTC)
            if end_dt.tzinfo is None:
              end_dt = end_dt.replace (tzinfo = datetime.UTC)
            if start_dt <= ts <= end_dt:
              events.append (rec)
          except (json.JSONDecodeError, KeyError, ValueError):
            continue
    except Exception as e:
      logger.error (f"Failed to read audit log for report: {e}")
      return json.dumps ({"error": str (e)})

    query_count = sum (1 for e in events if e.get ("event_type") == "query")
    error_count = sum (1 for e in events if e.get ("event_type") == "error")
    denied_count = sum (1 for e in events if e.get ("event_type") == "access_denied")
    total_tokens = sum (e.get ("tokens_used", 0) or 0 for e in events)

    report = {
        "period": {"start": start_time, "end": end_time}, "summary": {
            "total_events": len (events), "queries": query_count, "errors": error_count, "access_denied": denied_count,
            "total_tokens_used": total_tokens,
        }, "events": events if fmt == "json" else [],
    }
    return json.dumps (report, ensure_ascii = False, indent = 2)


class RequestTracker:
  """Tracks request lifecycle: start -> processing -> complete."""

  def __init__ (self) -> None:
    self._active: dict [str, dict [str, Any]] = {}
    self._lock = None  # not async-safe; use in single-worker context

  def start (self, request_id: str, metadata: dict [str, Any] | None = None) -> None:
    """Record the start of a request."""
    self._active [request_id] = {
        "start_time": time.monotonic (), "metadata": metadata or {}, "status": "processing",
    }

  def complete (self, request_id: str, status: str = "success", tokens: int = 0) -> dict [str, Any] | None:
    """Record the completion of a request. Returns duration info or None."""
    entry = self._active.pop (request_id, None)
    if entry is None:
      return None
    duration_ms = (time.monotonic () - entry ["start_time"]) * 1000
    return {
        "request_id": request_id, "duration_ms": round (duration_ms, 2), "status": status, "tokens": tokens,
        "metadata": entry ["metadata"],
    }

  @property
  def active_requests (self) -> int:
    return len (self._active)
