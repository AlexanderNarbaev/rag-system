# proxy/app/logging_config.py
"""
Structured logging configuration for RAG proxy.
Supports JSON and text formats, request ID propagation, sensitive data masking.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime

SENSITIVE_PATTERNS = [
    re.compile(r'(api[_-]?key[=:]\s*["\']?)([^"\'&\s]+)', re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", re.IGNORECASE),
    re.compile(r'(password[=:]\s*["\']?)([^"\'&\s]+)', re.IGNORECASE),
    re.compile(r'(secret[=:]\s*["\']?)([^"\'&\s]+)', re.IGNORECASE),
    re.compile(r'(token[=:]\s*["\']?)([^"\'&\s]+)', re.IGNORECASE),
]

MASK_REPLACEMENT = "\\1***"


def mask_sensitive_data(message: str) -> str:
    """Replace sensitive values in log messages with '***'."""
    for pattern in SENSITIVE_PATTERNS:
        message = pattern.sub(MASK_REPLACEMENT, message)
    return message


class JsonFormatter(logging.Formatter):
    """JSON structured log formatter for machine-parseable logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_sensitive_data(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """Injects request_id from context into log records."""

    _request_id: str | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        if RequestIdFilter._request_id:
            record.request_id = RequestIdFilter._request_id
        else:
            record.request_id = "-"
        return True

    @classmethod
    def set_request_id(cls, request_id: str | None) -> None:
        """Set the current request ID for log correlation."""
        cls._request_id = request_id


class ColoredConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with optional colors."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        message = mask_sensitive_data(record.getMessage())
        request_id = getattr(record, "request_id", "-")
        base = f"{self.formatTime(record)} [{record.name}] [{record.levelname}] [{request_id}] {message}"
        if color:
            return f"{color}{base}{self.RESET}"
        return base


_LOG_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def get_log_format() -> str:
    return os.getenv("LOG_FORMAT", "text").lower()


def get_log_level() -> int:
    """Return log level from LOG_LEVEL env var (default: INFO)."""
    raw = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return _LOG_LEVEL_MAP.get(raw, logging.INFO)


def setup_logging(level: int | None = None) -> logging.Handler:
    """
    Configures root logger and returns the configured handler.
    Uses LOG_FORMAT env var: 'json' for structured JSON, 'text' for console.
    Uses LOG_LEVEL env var: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO).
    """
    if level is None:
        level = get_log_level()
    log_format = get_log_format()
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S"))

    root_logger.addHandler(handler)

    logging.getLogger("uvicorn").handlers = []
    logging.getLogger("uvicorn").addHandler(handler)
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").addHandler(handler)

    return handler


def set_log_level(module_name: str, level: int):
    """Set log level for a specific module."""
    logger = logging.getLogger(module_name)
    logger.setLevel(level)
