"""Tests for proxy/app/security.py security hardening module."""
import json
import os
import re
import tempfile
from unittest.mock import patch

import pytest

from proxy.app.security import (
    InputValidator,
    SecretsManager,
    SecurityHeaders,
    DependencyScanner,
)


class TestInputValidator:
    """Tests for InputValidator."""

    def test_validate_query_basic(self):
        result = InputValidator.validate_query("What is RAG?")
        assert result == "What is RAG?"

    def test_validate_query_strips_html(self):
        result = InputValidator.validate_query("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_validate_query_max_length(self):
        long_query = "A" * 10000
        result = InputValidator.validate_query(long_query)
        assert len(result) <= InputValidator.MAX_QUERY_LENGTH

    def test_validate_query_strips_control_chars(self):
        result = InputValidator.validate_query("Hello\x00World\x1f!")
        assert "\x00" not in result
        assert "Hello" in result

    def test_validate_query_collapses_whitespace(self):
        result = InputValidator.validate_query("Hello    World \n\n Test")
        assert result == "Hello World Test"

    def test_validate_query_empty_string(self):
        result = InputValidator.validate_query("")
        assert result == ""

    def test_validate_query_non_string(self):
        result = InputValidator.validate_query(None)
        assert result == ""
        result = InputValidator.validate_query(123)
        assert result == ""

    def test_validate_non_empty_valid(self):
        result = InputValidator.validate_non_empty("hello", max_len=100)
        assert result == "hello"

    def test_validate_non_empty_blank(self):
        result = InputValidator.validate_non_empty("   ")
        assert result is None

    def test_validate_non_empty_too_long(self):
        result = InputValidator.validate_non_empty("A" * 100, max_len=10)
        assert len(result) <= 10

    def test_validate_non_empty_none(self):
        result = InputValidator.validate_non_empty(None)
        assert result is None

    def test_sanitize_for_log_emails(self):
        result = InputValidator.sanitize_for_log("Contact user@example.com for help")
        assert "@example.com" not in result
        assert "[EMAIL]" in result

    def test_sanitize_for_log_ips(self):
        result = InputValidator.sanitize_for_log("From 192.168.1.1 to 10.0.0.1")
        assert "192.168.1.1" not in result
        assert "[IP]" in result

    def test_sanitize_for_log_tokens(self):
        token = "A" * 32 + "B" * 8
        result = InputValidator.sanitize_for_log(f"Token: {token}")
        assert token not in result
        assert "[REDACTED]" in result

    def test_validate_model_name_valid(self):
        assert InputValidator.validate_model_name("gemma-4-26b-it") is True

    def test_validate_model_name_invalid(self):
        assert InputValidator.validate_model_name("bad; rm -rf /") is False
        assert InputValidator.validate_model_name("") is False
        assert InputValidator.validate_model_name(None) is False

    def test_validate_path_traversal_safe(self):
        assert InputValidator.validate_path_traversal("/var/log/app.log") is True

    def test_validate_path_traversal_dangerous(self):
        assert InputValidator.validate_path_traversal("../../../etc/passwd") is False
        assert InputValidator.validate_path_traversal("/home/~user/file") is False
        assert InputValidator.validate_path_traversal("/path/\x00hidden") is False

    def test_sanitize_headers_redacts_sensitive(self):
        headers = {
            "content-type": "application/json",
            "authorization": "Bearer secret-token-12345",
            "x-api-key": "sk-abcdef",
        }
        result = InputValidator.sanitize_headers(headers)
        assert result["authorization"] == "[REDACTED]"
        assert result["x-api-key"] == "[REDACTED]"
        assert result["content-type"] == "application/json"

    def test_sanitize_headers_preserves_safe(self):
        headers = {"content-type": "text/html", "accept": "application/json"}
        result = InputValidator.sanitize_headers(headers)
        assert result == headers

    def test_escape_shell_arg(self):
        assert InputValidator.escape_shell_arg("safe-name") == "safe-name"
        result = InputValidator.escape_shell_arg("bad; rm -rf /")
        assert ";" not in result

    def test_escape_shell_arg_empty(self):
        assert InputValidator.escape_shell_arg("") == ""


class TestSecretsManager:
    """Tests for SecretsManager."""

    def test_generate_api_key_format(self):
        key = SecretsManager.generate_api_key()
        assert key.startswith("rag_")
        parts = key.split("_")
        assert len(parts) >= 2

    def test_generate_api_key_custom_prefix(self):
        key = SecretsManager.generate_api_key(prefix="test")
        assert key.startswith("test_")

    def test_generate_api_key_uniqueness(self):
        keys = {SecretsManager.generate_api_key() for _ in range(50)}
        assert len(keys) == 50

    def test_hash_secret_deterministic(self):
        a = SecretsManager.hash_secret("my-secret")
        b = SecretsManager.hash_secret("my-secret")
        assert a == b

    def test_hash_secret_different_values(self):
        a = SecretsManager.hash_secret("secret-a")
        b = SecretsManager.hash_secret("secret-b")
        assert a != b

    def test_verify_secret_correct(self):
        secret = "test-password"
        hashed = SecretsManager.hash_secret(secret)
        assert SecretsManager.verify_secret(secret, hashed) is True

    def test_verify_secret_incorrect(self):
        hashed = SecretsManager.hash_secret("correct")
        assert SecretsManager.verify_secret("wrong", hashed) is False

    def test_mask_in_response_simple(self):
        data = {"name": "John", "api_key": "secret123"}
        result = SecretsManager.mask_in_response(data)
        assert result["name"] == "John"
        assert result["api_key"] == "***"

    def test_mask_in_response_nested(self):
        data = {
            "user": {"name": "Alice", "password": "hunter2"},
            "auth": {"token": "abc", "public": "visible"},
        }
        result = SecretsManager.mask_in_response(data)
        assert result["user"]["name"] == "Alice"
        assert result["user"]["password"] == "***"
        assert result["auth"]["token"] == "***"
        assert result["auth"]["public"] == "visible"

    def test_mask_in_response_non_dict(self):
        assert SecretsManager.mask_in_response("not a dict") == "not a dict"
        assert SecretsManager.mask_in_response(None) is None

    def test_generate_token_length(self):
        token = SecretsManager.generate_token(length=16)
        decoded = __import__("base64").urlsafe_b64decode(token + "==")
        assert len(decoded) == 16

    def test_constant_time_compare_match(self):
        assert SecretsManager.constant_time_compare("abc", "abc") is True

    def test_constant_time_compare_mismatch(self):
        assert SecretsManager.constant_time_compare("abc", "abd") is False


class TestSecurityHeaders:
    """Tests for SecurityHeaders."""

    def test_default_headers_present(self):
        headers = SecurityHeaders.get_headers()
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "Strict-Transport-Security" in headers

    def test_get_headers_with_extra(self):
        headers = SecurityHeaders.get_headers(extra={"X-Custom": "value"})
        assert headers["X-Custom"] == "value"
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_all_sensitive_headers_present(self):
        headers = SecurityHeaders.get_headers()
        required = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "Referrer-Policy",
            "Cache-Control",
        ]
        for h in required:
            assert h in headers

    def test_extra_overrides_default(self):
        headers = SecurityHeaders.get_headers(extra={"X-Frame-Options": "SAMEORIGIN"})
        assert headers["X-Frame-Options"] == "SAMEORIGIN"


class TestDependencyScanner:
    """Tests for DependencyScanner."""

    def test_parse_requirements_line_with_version(self):
        result = DependencyScanner.parse_requirements_line("requests==2.25.0")
        assert result == ("requests", "2.25.0")

    def test_parse_requirements_line_no_version(self):
        result = DependencyScanner.parse_requirements_line("fastapi")
        assert result == ("fastapi", "any")

    def test_parse_requirements_line_comment(self):
        assert DependencyScanner.parse_requirements_line("# comment") is None
        assert DependencyScanner.parse_requirements_line("  # inline comment") is None

    def test_parse_requirements_line_flag(self):
        assert DependencyScanner.parse_requirements_line("-r requirements.txt") is None

    def test_scan_requirements_known_vulnerability(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("requests==2.25.0\n")
            f.write("safe-package==1.0.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) >= 1
            assert any(f["package"] == "requests" for f in findings)
        finally:
            os.unlink(path)

    def test_scan_requirements_no_vulnerability(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("safe-package==2.0.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) == 0
        finally:
            os.unlink(path)

    def test_scan_requirements_file_not_found(self):
        findings = DependencyScanner.scan_requirements("/nonexistent/file.txt")
        assert len(findings) == 1
        assert "error" in findings[0]

    def test_parse_requirements_line_empty(self):
        assert DependencyScanner.parse_requirements_line("") is None
        assert DependencyScanner.parse_requirements_line("   ") is None
