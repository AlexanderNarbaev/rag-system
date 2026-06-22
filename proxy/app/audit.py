# proxy/app/audit.py
"""Audit logging and tracking for all RAG operations."""
import json
import hashlib
import datetime
from datetime import timezone
import os
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("rag-proxy.audit")


@dataclass
class AuditEvent:
    """Single auditable event in the RAG system."""
    event_id: str
    timestamp: str
    event_type: str  # query, login, access_denied, config_change, error
    user_id: Optional[str]
    client_ip: str
    endpoint: str
    request_hash: str
    details: Dict = field(default_factory=dict)
    duration_ms: Optional[float] = None
    tokens_used: Optional[int] = None
    result_status: str = "unknown"

    def to_dict(self) -> Dict:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class AuditLogger:
    """Writes audit events to JSONL file and optional syslog."""

    def __init__(self, log_dir: str = "/var/log/rag-system"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._audit_file = os.path.join(log_dir, "audit.jsonl")

    def _write_event(self, event: AuditEvent):
        """Write an audit event to the JSONL file."""
        try:
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
            logger.debug(f"Audit event recorded: {event.event_id} ({event.event_type})")
        except Exception as e:
            logger.error(f"Failed to write audit event: {e}")

    def _generate_event_id(self) -> str:
        ts = int(time.time() * 1_000_000)
        rand = os.urandom(6).hex()
        return f"evt_{ts}_{rand}"

    def _hash_request(self, query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    def log_query(
        self,
        user_id: Optional[str],
        query: str,
        response_preview: str,
        chunks: int,
        duration_ms: float,
        tokens: int,
        client_ip: str = "unknown",
        endpoint: str = "/v1/chat/completions",
        result_status: str = "success",
        metadata: Optional[Dict] = None,
    ):
        """Log a query event."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            timestamp=datetime.datetime.now(timezone.utc).isoformat(),
            event_type="query",
            user_id=user_id,
            client_ip=client_ip,
            endpoint=endpoint,
            request_hash=self._hash_request(query),
            details={
                "query_preview": query[:200],
                "response_preview": response_preview[:200],
                "chunks_retrieved": chunks,
                "metadata": metadata or {},
            },
            duration_ms=round(duration_ms, 2),
            tokens_used=tokens,
            result_status=result_status,
        )
        self._write_event(event)

    def log_access_denied(self, user_id: Optional[str], resource: str, reason: str, client_ip: str = "unknown"):
        """Log an access denied event."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            timestamp=datetime.datetime.now(timezone.utc).isoformat(),
            event_type="access_denied",
            user_id=user_id,
            client_ip=client_ip,
            endpoint=resource,
            request_hash="n/a",
            details={
                "resource": resource,
                "reason": reason,
            },
            result_status="denied",
        )
        self._write_event(event)

    def log_config_change(self, user_id: Optional[str], key: str, old_value: str, new_value: str, client_ip: str = "unknown"):
        """Log configuration changes (values masked)."""
        def mask_val(v: str) -> str:
            if v is None:
                return "***"
            if len(v) > 20:
                return v[:4] + "***" + v[-4:]
            return "***"

        event = AuditEvent(
            event_id=self._generate_event_id(),
            timestamp=datetime.datetime.now(timezone.utc).isoformat(),
            event_type="config_change",
            user_id=user_id,
            client_ip=client_ip,
            endpoint="/admin/config",
            request_hash="n/a",
            details={
                "config_key": key,
                "old_value": mask_val(old_value),
                "new_value": mask_val(new_value),
            },
            result_status="success",
        )
        self._write_event(event)

    def log_error(
        self,
        error_type: str,
        error_msg: str,
        stack_trace: Optional[str],
        context: Optional[Dict] = None,
        client_ip: str = "unknown",
        endpoint: str = "unknown",
    ):
        """Log error events."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            timestamp=datetime.datetime.now(timezone.utc).isoformat(),
            event_type="error",
            user_id=context.get("user_id") if context else None,
            client_ip=client_ip,
            endpoint=endpoint,
            request_hash="n/a",
            details={
                "error_type": error_type,
                "error_message": error_msg[:500],
                "stack_trace": (stack_trace or "")[:2000],
                "context": context or {},
            },
            result_status="error",
        )
        self._write_event(event)

    def log_auth(self, user_id: Optional[str], action: str, success: bool, details: Optional[Dict] = None, client_ip: str = "unknown"):
        """Log authentication events."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            timestamp=datetime.datetime.now(timezone.utc).isoformat(),
            event_type="login" if action == "login" else "auth",
            user_id=user_id,
            client_ip=client_ip,
            endpoint="/auth",
            request_hash="n/a",
            details={
                "action": action,
                "success": success,
                **(details or {}),
            },
            result_status="success" if success else "failure",
        )
        self._write_event(event)

    def query_history(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
        start_time: Optional[str] = None,
    ) -> List[Dict]:
        """Read audit log with filters."""
        results = []
        if not os.path.exists(self._audit_file):
            return results

        if start_time:
            try:
                cutoff = datetime.datetime.fromisoformat(start_time)
            except (ValueError, TypeError):
                cutoff = None
        else:
            cutoff = None

        try:
            with open(self._audit_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")
            return results

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if user_id and record.get("user_id") != user_id:
                continue
            if cutoff:
                try:
                    event_time = datetime.datetime.fromisoformat(record["timestamp"])
                    if event_time < cutoff:
                        continue
                except (ValueError, KeyError):
                    pass

            results.append(record)
            if len(results) >= limit:
                break

        return results

    def export_report(self, start_time: str, end_time: str, fmt: str = "json") -> str:
        """Generate usage report for time period."""
        try:
            start_dt = datetime.datetime.fromisoformat(start_time)
            end_dt = datetime.datetime.fromisoformat(end_time)
        except (ValueError, TypeError):
            return json.dumps({"error": "invalid time format"})

        events = []
        if not os.path.exists(self._audit_file):
            report = {
                "period": {"start": start_time, "end": end_time},
                "summary": {
                    "total_events": 0,
                    "queries": 0,
                    "errors": 0,
                    "access_denied": 0,
                    "total_tokens_used": 0,
                },
                "events": [],
            }
            return json.dumps(report, ensure_ascii=False, indent=2)

        try:
            with open(self._audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts = datetime.datetime.fromisoformat(rec["timestamp"])
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=datetime.timezone.utc)
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
                        if start_dt <= ts <= end_dt:
                            events.append(rec)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Failed to read audit log for report: {e}")
            return json.dumps({"error": str(e)})

        query_count = sum(1 for e in events if e.get("event_type") == "query")
        error_count = sum(1 for e in events if e.get("event_type") == "error")
        denied_count = sum(1 for e in events if e.get("event_type") == "access_denied")
        total_tokens = sum(e.get("tokens_used", 0) or 0 for e in events)

        report = {
            "period": {"start": start_time, "end": end_time},
            "summary": {
                "total_events": len(events),
                "queries": query_count,
                "errors": error_count,
                "access_denied": denied_count,
                "total_tokens_used": total_tokens,
            },
            "events": events if fmt == "json" else [],
        }
        return json.dumps(report, ensure_ascii=False, indent=2)


class RequestTracker:
    """Tracks request lifecycle: start -> processing -> complete."""

    def __init__(self):
        self._active: Dict[str, Dict] = {}
        self._lock = None  # not async-safe; use in single-worker context

    def start(self, request_id: str, metadata: Optional[Dict] = None):
        """Record the start of a request."""
        self._active[request_id] = {
            "start_time": time.monotonic(),
            "metadata": metadata or {},
            "status": "processing",
        }

    def complete(self, request_id: str, status: str = "success", tokens: int = 0) -> Optional[Dict]:
        """Record the completion of a request. Returns duration info or None."""
        entry = self._active.pop(request_id, None)
        if entry is None:
            return None
        duration_ms = (time.monotonic() - entry["start_time"]) * 1000
        return {
            "request_id": request_id,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "tokens": tokens,
            "metadata": entry["metadata"],
        }

    @property
    def active_requests(self) -> int:
        return len(self._active)
