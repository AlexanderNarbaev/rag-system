"""Tests for proxy/app/shared/logging.py — structured logging configuration."""

import logging
import os
from unittest.mock import patch

import pytest

from proxy.app.shared.logging import (
    ColoredConsoleFormatter,
    JsonFormatter,
    RequestIdFilter,
    get_log_format,
    get_log_level,
    mask_sensitive_data,
    set_log_level,
    setup_logging,
)


class TestMaskSensitiveData:
    def test_mask_api_key(self):
        result = mask_sensitive_data("api_key=my-secret-key and more")
        assert "my-secret-key" not in result
        assert "api_key=" in result
        assert "***" in result

    def test_mask_authorization_header(self):
        result = mask_sensitive_data("Authorization: Bearer token123abc for request")
        assert "token123abc" not in result
        assert "Authorization: Bearer" in result
        assert "***" in result

    def test_mask_password(self):
        result = mask_sensitive_data("password=supersecret123 end")
        assert "supersecret123" not in result
        assert "password=" in result

    def test_mask_secret(self):
        result = mask_sensitive_data("secret=myappsecret value")
        assert "myappsecret" not in result
        assert "***" in result

    def test_mask_token(self):
        result = mask_sensitive_data("token=abc123xyz end")
        assert "abc123xyz" not in result
        assert "token=" in result

    def test_no_sensitive_data_unchanged(self):
        msg = "This is a normal log message without secrets"
        assert mask_sensitive_data(msg) == msg

    def test_mask_case_insensitive(self):
        result = mask_sensitive_data("API_KEY=secret-key")
        assert "secret-key" not in result
        assert "***" in result


class TestJsonFormatter:
    def test_format_basic_record(self):
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "test message", (), None)
        result = fmt.format(record)
        assert "test message" in result
        assert "INFO" in result
        assert "timestamp" in result
        assert "logger" in result

    def test_format_masks_sensitive_data(self):
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "api_key=secret123", (), None)
        result = fmt.format(record)
        assert "secret123" not in result
        assert "api_key=" in result

    def test_format_with_request_id(self):
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "message", (), None)
        record.request_id = "req-1234"
        result = fmt.format(record)
        assert "req-1234" in result

    def test_format_with_exception(self):
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.ERROR, "test.py", 10, "error message", (), None)
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record.exc_info = sys.exc_info()
            result = fmt.format(record)
            assert "ValueError" in result
            assert "exception" in result


class TestColoredConsoleFormatter:
    def test_format_basic_record(self):
        fmt = ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "hello world", (), None)
        result = fmt.format(record)
        assert "hello world" in result
        assert "INFO" in result

    def test_format_error_record(self):
        fmt = ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord("test", logging.ERROR, "test.py", 10, "an error", (), None)
        result = fmt.format(record)
        assert "an error" in result
        assert "ERROR" in result

    def test_format_masks_sensitive_data(self):
        fmt = ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "token=secret-token", (), None)
        result = fmt.format(record)
        assert "secret-token" not in result

    def test_format_debug_record(self):
        fmt = ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord("test", logging.DEBUG, "test.py", 10, "debug info", (), None)
        result = fmt.format(record)
        assert "debug info" in result
        assert "DEBUG" in result

    def test_format_no_color_for_unknown_level(self):
        fmt = ColoredConsoleFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord("test", logging.NOTSET, "test.py", 10, "trace info", (), None)
        result = fmt.format(record)
        assert "trace info" in result
        assert "NOTSET" in result


class TestRequestIdFilter:
    def test_filter_sets_request_id_empty(self):
        RequestIdFilter._request_id = None
        filt = RequestIdFilter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
        assert filt.filter(record) is True
        # request_id is dynamically added by filter
        assert hasattr(record, "request_id")

    def test_filter_sets_request_id(self):
        RequestIdFilter.set_request_id("req-5678")
        filt = RequestIdFilter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
        assert filt.filter(record) is True
        assert record.request_id == "req-5678"

    def test_set_request_id_none(self):
        RequestIdFilter.set_request_id("req-temp")
        RequestIdFilter.set_request_id(None)
        filt = RequestIdFilter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
        filt.filter(record)
        assert record.request_id == "-"


class TestGetLogLevel:
    def test_default_info(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        assert get_log_level() == logging.INFO

    def test_debug_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert get_log_level() == logging.DEBUG

    def test_warning_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        assert get_log_level() == logging.WARNING

    def test_error_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        assert get_log_level() == logging.ERROR

    def test_critical_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
        assert get_log_level() == logging.CRITICAL

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        assert get_log_level() == logging.DEBUG

    def test_invalid_returns_default(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "INVALID")
        assert get_log_level() == logging.INFO


class TestSetupLogging:
    def test_setup_logging_text_format(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "text")
        handler = setup_logging()
        assert isinstance(handler, logging.StreamHandler)
        assert isinstance(handler.formatter, ColoredConsoleFormatter)

    def test_setup_logging_json_format(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "json")
        handler = setup_logging()
        assert isinstance(handler, logging.StreamHandler)
        assert isinstance(handler.formatter, JsonFormatter)

    def test_setup_logging_with_custom_level(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "text")
        handler = setup_logging(level=logging.DEBUG)
        assert logging.getLogger().level == logging.DEBUG

    def test_setup_logging_removes_existing_handlers(self, monkeypatch):
        root = logging.getLogger()
        monkeypatch.setenv("LOG_FORMAT", "text")
        handler = setup_logging()
        assert handler in root.handlers


class TestSetLogLevel:
    def test_set_log_level_module(self):
        logger = logging.getLogger("test_module_set_level")
        set_log_level("test_module_set_level", logging.DEBUG)
        assert logger.level == logging.DEBUG
        set_log_level("test_module_set_level", logging.WARNING)
        assert logger.level == logging.WARNING
