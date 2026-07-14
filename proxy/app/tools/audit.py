# proxy/app/tools/audit.py
"""Tool audit logging — structured JSON logging of tool invocations.

Provides ``ToolAuditLogger`` with configurable output destinations
(stdout, file, or both), parameter sanitization, and integration
with the tools SDK via ``ToolContext`` and ``ToolResult``.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .definition import ToolResult
from .sdk import ToolContext

logger = logging.getLogger ("rag-proxy.tools.audit")


class AuditDestination (StrEnum):
  STDOUT = "stdout"
  FILE = "file"
  BOTH = "both"


@dataclass
class ToolAuditRecord:
  """A single tool invocation audit record."""
  
  timestamp: str
  tool_name: str
  tool_call_id: str
  user_id: str | None
  request_id: str
  params: dict [str, Any]
  result_status: str
  duration_ms: float
  error: str | None = None
  
  def to_json (self) -> str:
    data = asdict (self)
    return json.dumps (data, ensure_ascii = False, default = str)


def _sanitize_params (params: dict [str, Any], max_value_length: int = 200) -> dict [str, Any]:
  sanitized: dict [str, Any] = {}
  
  for key, value in params.items ():
    if key.lower () in ("password", "secret", "token", "api_key", "apikey", "authorization"):
      sanitized [key] = "***"
      continue
    
    if isinstance (value, str):
      if len (value) > max_value_length:
        sanitized [key] = value [:max_value_length] + "..."
      else:
        sanitized [key] = value
    elif isinstance (value, (int, float, bool, type (None))):
      sanitized [key] = value
    elif isinstance (value, (list, dict)):
      try:
        truncated = json.dumps (value, ensure_ascii = False, default = str)
        if len (truncated) > max_value_length:
          truncated = truncated [:max_value_length] + "..."
        sanitized [key] = truncated
      except (TypeError, ValueError):
        sanitized [key] = str (type (value).__name__)
    else:
      sanitized [key] = str (type (value).__name__)
  
  return sanitized


class ToolAuditLogger:
  """Structured audit logger for tool invocations.

  Writes JSON-per-line records and supports three output modes:
  stdout, file, or both.

  Usage::

      audit = ToolAuditLogger(destination=AuditDestination.BOTH, log_dir="/var/log/tools")
      audit.log_invocation(tool_name="search_docs", tool_call_id="call_1",
                           user_id="user_1", request_id="req_1", params={"q": "RAG"},
                           result_status="success", duration_ms=12.5)
  """
  
  def __init__ (
      self, destination: AuditDestination = AuditDestination.STDOUT, log_dir: str = "/var/log/rag-system/tools", ):
    self._destination = destination
    self._log_dir = log_dir
    
    if destination in (AuditDestination.FILE, AuditDestination.BOTH):
      os.makedirs (log_dir, exist_ok = True)
      self._audit_file = os.path.join (log_dir, "tools_audit.jsonl")
  
  def log_invocation (
      self, tool_name: str, tool_call_id: str = "", user_id: str | None = None, request_id: str = "",
      params: dict [str, Any] | None = None, result_status: str = "success", duration_ms: float = 0.0,
      error: str | None = None, ) -> None:
    record = ToolAuditRecord (timestamp = datetime.datetime.now (datetime.UTC).isoformat (), tool_name = tool_name,
        tool_call_id = tool_call_id, user_id = user_id, request_id = request_id,
        params = _sanitize_params (params or {}), result_status = result_status, duration_ms = round (duration_ms, 3),
        error = error, )
    self._write (record)
  
  def log_from_result (
      self, result: ToolResult, context: ToolContext | None = None, params: dict [str, Any] | None = None, ) -> None:
    self.log_invocation (tool_name = result.tool_name, tool_call_id = result.tool_call_id,
        user_id = context.user_id if context else None, request_id = context.request_id if context else "",
        params = params, result_status = result.status, duration_ms = result.duration_ms, error = result.error, )
  
  def _write (self, record: ToolAuditRecord) -> None:
    line = record.to_json () + "\n"
    
    if self._destination in (AuditDestination.STDOUT, AuditDestination.BOTH):
      try:
        sys.stdout.write (line)
        sys.stdout.flush ()
      except Exception as e:
        logger.error (f"Failed to write tool audit to stdout: {e}")
    
    if self._destination in (AuditDestination.FILE, AuditDestination.BOTH):
      try:
        with open (self._audit_file, "a", encoding = "utf-8") as f:
          f.write (line)
      except Exception as e:
        logger.error (f"Failed to write tool audit to file: {e}")
  
  def read_records (self, limit: int = 100, tool_name: str | None = None) -> list [dict [str, Any]]:
    """Read recent audit records from file (only when FILE/BOTH destination)."""
    if self._destination == AuditDestination.STDOUT:
      return []
    
    results: list [dict [str, Any]] = []
    if not os.path.exists (self._audit_file):
      return results
    
    try:
      with open (self._audit_file, encoding = "utf-8") as f:
        lines = f.readlines ()
    except Exception as e:
      logger.error (f"Failed to read tool audit log: {e}")
      return results
    
    for line in reversed (lines):
      line = line.strip ()
      if not line:
        continue
      try:
        record = json.loads (line)
      except json.JSONDecodeError:
        continue
      
      if tool_name and record.get ("tool_name") != tool_name:
        continue
      
      results.append (record)
      if len (results) >= limit:
        break
    
    return results
