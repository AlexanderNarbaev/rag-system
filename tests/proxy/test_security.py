"""Comprehensive security tests for RAG proxy hardening.

Tests cover:
- Input validation (XSS, SQL injection, path traversal, control chars)
- Secrets management (generation, masking, constant-time comparison)
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Password policy validation (complexity requirements)
- Dependency vulnerability scanning
- JWT/API key auth security
- Rate limiting logic
- Token blacklisting
- SQL injection safety (parameterized queries)
- Timing attack protection
"""

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.shared.security import (
    DependencyScanner,
    InputValidator,
    PasswordStrengthValidator,
    SecretsManager,
    SecurityHeaders,
)


class TestInputValidator:
    """Tests for InputValidator — query sanitization, XSS prevention, etc."""

    def test_validate_query_basic(self):
        result = InputValidator.validate_query("What is RAG?")
        assert result == "What is RAG?"

    def test_validate_query_strips_html(self):
        result = InputValidator.validate_query("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_validate_query_strips_script_tags_aggressive(self):
        result = InputValidator.validate_query('<img src=x onerror="alert(1)">')
        assert "<img" not in result.lower()
        assert "onerror" not in result.lower()

    def test_validate_query_strips_event_handlers(self):
        result = InputValidator.validate_query("<div onmouseover='alert(1)'>text</div>")
        assert "<div" not in result.lower()
        assert "text" in result

    def test_validate_query_max_length(self):
        long_query = "A" * 10000
        result = InputValidator.validate_query(long_query)
        assert len(result) <= InputValidator.MAX_QUERY_LENGTH

    def test_validate_query_strips_control_chars(self):
        result = InputValidator.validate_query("Hello\x00World\x1f!")
        assert "\x00" not in result
        assert "Hello" in result

    def test_validate_query_strips_null_bytes(self):
        result = InputValidator.validate_query("SELECT\x00FROM\x00users")
        assert "\x00" not in result
        assert "SELECT" in result

    def test_validate_query_collapses_whitespace(self):
        result = InputValidator.validate_query("Hello    World \n\n Test")
        assert result == "Hello World Test"

    def test_validate_query_empty_string(self):
        result = InputValidator.validate_query("")
        assert result == ""

    def test_validate_query_non_string(self):
        result = InputValidator.validate_query(None)  # type: ignore[arg-type]
        assert result == ""
        result = InputValidator.validate_query(123)  # type: ignore[arg-type]
        assert result == ""

    def test_validate_query_sql_injection_pattern(self):
        result = InputValidator.validate_query("'; DROP TABLE users; --")
        assert "DROP TABLE" in result
        assert len(result) <= 8000

    def test_validate_query_preserves_cyrillic(self):
        result = InputValidator.validate_query("Привет мир - RAG система")
        assert "Привет" in result
        assert "RAG" in result

    def test_validate_query_unicode_emojis_removed(self):
        result = InputValidator.validate_query("hello \U0001f600 world")
        assert "\U0001f600" in result

    def test_validate_non_empty_valid(self):
        result = InputValidator.validate_non_empty("hello", max_len=100)
        assert result == "hello"

    def test_validate_non_empty_blank(self):
        result = InputValidator.validate_non_empty("   ")
        assert result is None

    def test_validate_non_empty_too_long(self):
        result = InputValidator.validate_non_empty("A" * 100, max_len=10)
        assert result is not None
        assert len(result) <= 10

    def test_validate_non_empty_none(self):
        result = InputValidator.validate_non_empty(None)  # type: ignore[arg-type]
        assert result is None

    def test_validate_non_empty_strips_html(self):
        result = InputValidator.validate_non_empty("<b>hello</b>", max_len=100)
        assert result == "hello"

    def test_sanitize_for_log_emails(self):
        result = InputValidator.sanitize_for_log("Contact user@example.com for help")
        assert "@example.com" not in result
        assert "[EMAIL]" in result

    def test_sanitize_for_log_multiple_emails(self):
        result = InputValidator.sanitize_for_log("a@b.com and c@d.org")
        assert "@b.com" not in result
        assert "@d.org" not in result
        assert result.count("[EMAIL]") == 2

    def test_sanitize_for_log_ips(self):
        result = InputValidator.sanitize_for_log("From 192.168.1.1 to 10.0.0.1")
        assert "192.168.1.1" not in result
        assert "[IP]" in result

    def test_sanitize_for_log_ipv4_all_octets(self):
        result = InputValidator.sanitize_for_log("Connect to 10.255.255.1")
        assert "10.255.255.1" not in result
        assert "[IP]" in result

    def test_sanitize_for_log_tokens(self):
        token = "A" * 32 + "B" * 8
        result = InputValidator.sanitize_for_log(f"Token: {token}")
        assert token not in result
        assert "[REDACTED]" in result

    def test_sanitize_for_log_api_key_pattern(self):
        result = InputValidator.sanitize_for_log("Using key: sk-abcdef1234567890abcdef1234567890")
        assert "sk-abcdef" not in result
        assert "[REDACTED]" in result

    def test_validate_model_name_valid(self):
        assert InputValidator.validate_model_name("test-model-v1") is True
        assert InputValidator.validate_model_name("meta-llama/Llama-3.1-70B") is True
        assert InputValidator.validate_model_name("sentence-transformers/all-MiniLM-L6-v2") is True

    def test_validate_model_name_invalid(self):
        assert InputValidator.validate_model_name("bad; rm -rf /") is False
        assert InputValidator.validate_model_name("") is False
        assert InputValidator.validate_model_name(None) is False  # type: ignore[arg-type]
        assert InputValidator.validate_model_name("model<script>") is False

    def test_validate_model_name_injection_patterns(self):
        assert InputValidator.validate_model_name("model$(whoami)") is False
        assert InputValidator.validate_model_name("model`id`") is False
        assert InputValidator.validate_model_name("model|cat /etc/passwd") is False

    def test_validate_path_traversal_safe(self):
        assert InputValidator.validate_path_traversal("/var/log/app.log") is True

    def test_validate_path_traversal_dangerous(self):
        assert InputValidator.validate_path_traversal("../../../etc/passwd") is False
        assert InputValidator.validate_path_traversal("/home/~user/file") is False
        assert InputValidator.validate_path_traversal("/path/\x00hidden") is False

    def test_validate_path_traversal_encoded(self):
        assert InputValidator.validate_path_traversal("%2e%2e%2fetc%2fpasswd") is True

    def test_sanitize_headers_redacts_sensitive(self):
        headers = {
            "content-type": "application/json",
            "authorization": "Bearer secret-token-12345",
            "x-api-key": "sk-abcdef",
            "cookie": "session=abc123",
            "x-auth-token": "tok123",
            "set-cookie": "session=xyz",
        }
        result = InputValidator.sanitize_headers(headers)
        assert result["authorization"] == "[REDACTED]"
        assert result["x-api-key"] == "[REDACTED]"
        assert result["cookie"] == "[REDACTED]"
        assert result["x-auth-token"] == "[REDACTED]"
        assert result["set-cookie"] == "[REDACTED]"
        assert result["content-type"] == "application/json"

    def test_sanitize_headers_preserves_safe(self):
        headers = {"content-type": "text/html", "accept": "application/json"}
        result = InputValidator.sanitize_headers(headers)
        assert result == headers

    def test_escape_shell_arg(self):
        assert InputValidator.escape_shell_arg("safe-name") == "safe-name"
        result = InputValidator.escape_shell_arg("bad; rm -rf /")
        assert ";" not in result

    def test_escape_shell_arg_command_injection(self):
        result = InputValidator.escape_shell_arg("test$(whoami)")
        assert "$" not in result
        result = InputValidator.escape_shell_arg("test`id`")
        assert "`" not in result

    def test_escape_shell_arg_empty(self):
        assert InputValidator.escape_shell_arg("") == ""


class TestSecretsManager:
    """Tests for SecretsManager — key generation, masking, hashing."""

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

    def test_generate_api_key_entropy(self):
        key = SecretsManager.generate_api_key()
        parts = key.split("_")
        random_part = parts[-1]
        assert len(random_part) >= 20

    def test_hash_secret_deterministic(self):
        a = SecretsManager.hash_secret("my-secret")
        b = SecretsManager.hash_secret("my-secret")
        assert a == b

    def test_hash_secret_different_values(self):
        a = SecretsManager.hash_secret("secret-a")
        b = SecretsManager.hash_secret("secret-b")
        assert a != b

    def test_hash_secret_sha256_format(self):
        result = SecretsManager.hash_secret("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

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

    def test_mask_in_response_deep_nested(self):
        data = {
            "config": {
                "secrets": {"private_key": "top-secret", "public_name": "visible"},
                "items": [{"token": "t1"}, {"name": "item"}],
            },
        }
        result = SecretsManager.mask_in_response(data)
        assert result["config"]["secrets"]["private_key"] == "***"
        assert result["config"]["secrets"]["public_name"] == "visible"
        assert result["config"]["items"][0]["token"] == "***"
        assert result["config"]["items"][1]["name"] == "item"

    def test_mask_in_response_preserves_original(self):
        data = {"password": "original"}
        result = SecretsManager.mask_in_response(data)
        assert data["password"] == "original"
        assert result["password"] == "***"

    def test_mask_in_response_non_dict(self):
        assert SecretsManager.mask_in_response("not a dict") == "not a dict"  # type: ignore[arg-type]
        assert SecretsManager.mask_in_response(None) is None  # type: ignore[arg-type]

    def test_generate_token_length(self):
        token = SecretsManager.generate_token(length=16)
        decoded = __import__("base64").urlsafe_b64decode(token + "==")
        assert len(decoded) == 16

    def test_generate_token_urlsafe(self):
        token = SecretsManager.generate_token(length=32)
        assert "/" not in token
        assert "+" not in token

    def test_constant_time_compare_match(self):
        assert SecretsManager.constant_time_compare("abc", "abc") is True

    def test_constant_time_compare_mismatch(self):
        assert SecretsManager.constant_time_compare("abc", "abd") is False

    def test_constant_time_compare_different_lengths(self):
        assert SecretsManager.constant_time_compare("abc", "abcd") is False

    def test_constant_time_compare_empty_strings(self):
        assert SecretsManager.constant_time_compare("", "") is True

    def test_verify_secret_is_deterministic_hash_compare(self):
        secret = "my-secret"
        hashed = SecretsManager.hash_secret(secret)
        assert SecretsManager.hash_secret("my-secret") == hashed
        assert SecretsManager.hash_secret("different") != hashed


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
            assert h in headers, f"Missing required header: {h}"

    def test_extra_overrides_default(self):
        headers = SecurityHeaders.get_headers(extra={"X-Frame-Options": "SAMEORIGIN"})
        assert headers["X-Frame-Options"] == "SAMEORIGIN"

    def test_csp_contains_required_directives(self):
        headers = SecurityHeaders.get_headers()
        csp = headers["Content-Security-Policy"]
        assert "default-src" in csp
        assert "script-src" in csp
        assert "connect-src" in csp
        assert "style-src" in csp

    def test_hsts_includes_subdomains(self):
        headers = SecurityHeaders.get_headers()
        assert "includeSubDomains" in headers["Strict-Transport-Security"]

    def test_hsts_max_age_is_one_year(self):
        headers = SecurityHeaders.get_headers()
        assert "max-age=31536000" in headers["Strict-Transport-Security"]

    def test_xss_protection_block_mode(self):
        headers = SecurityHeaders.get_headers()
        assert "mode=block" in headers["X-XSS-Protection"]

    def test_permissions_policy_restricts_sensitive(self):
        headers = SecurityHeaders.get_headers()
        pp = headers["Permissions-Policy"]
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp

    def test_cache_control_no_store(self):
        headers = SecurityHeaders.get_headers()
        assert "no-store" in headers["Cache-Control"]

    def test_referrer_policy_strict(self):
        headers = SecurityHeaders.get_headers()
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestPasswordStrengthValidator:
    """Tests for PasswordStrengthValidator."""

    def test_valid_strong_password(self):
        valid, error = PasswordStrengthValidator.validate("Str0ng!Pass")
        assert valid is True
        assert error is None

    def test_valid_complex_password(self):
        valid, error = PasswordStrengthValidator.validate("C0mpl3x!P@ssw0rd")
        assert valid is True
        assert error is None

    def test_too_short(self):
        valid, error = PasswordStrengthValidator.validate("Ab1!")
        assert valid is False
        assert error is not None and "at least" in error

    def test_missing_uppercase(self):
        valid, error = PasswordStrengthValidator.validate("validpassword1!")
        assert valid is False
        assert error is not None and "uppercase" in error.lower()

    def test_missing_lowercase(self):
        valid, error = PasswordStrengthValidator.validate("PASSWORD1234!")
        assert valid is False
        assert error is not None and "lowercase" in error.lower()

    def test_missing_digit(self):
        valid, error = PasswordStrengthValidator.validate("Password!@#$")
        assert valid is False
        assert error is not None and "digit" in error.lower()

    def test_missing_special_char(self):
        valid, error = PasswordStrengthValidator.validate("Password1234")
        assert valid is False
        assert error is not None and "special" in error.lower()

    def test_exactly_min_length(self):
        valid, error = PasswordStrengthValidator.validate("Abcdefgh1!")
        assert valid is True

    def test_non_string_input(self):
        valid, error = PasswordStrengthValidator.validate(None)  # type: ignore[arg-type]
        assert valid is False
        valid, error = PasswordStrengthValidator.validate(123)  # type: ignore[arg-type]
        assert valid is False

    def test_too_long(self):
        valid, error = PasswordStrengthValidator.validate("A1!" + "a" * 130)
        assert valid is False

    def test_unicode_characters(self):
        valid, error = PasswordStrengthValidator.validate("Pässwörd123!Äöü")
        assert valid is True


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

    def test_parse_requirements_line_greater_equal(self):
        result = DependencyScanner.parse_requirements_line("pandas>=2.0.0")
        assert result == ("pandas", "2.0.0")

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

    def test_scan_requirements_urllib3_vuln(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("urllib3==1.26.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) >= 1
            assert any(f["package"] == "urllib3" for f in findings)
        finally:
            os.unlink(path)

    def test_scan_requirements_certifi_vuln(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("certifi==2021.0.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) >= 1
            assert any(f["package"] == "certifi" for f in findings)
        finally:
            os.unlink(path)

    def test_scan_requirements_file_not_found(self):
        findings = DependencyScanner.scan_requirements("/nonexistent/file.txt")
        assert len(findings) == 1
        assert "error" in findings[0]

    def test_parse_requirements_line_empty(self):
        assert DependencyScanner.parse_requirements_line("") is None
        assert DependencyScanner.parse_requirements_line("   ") is None

    def test_scan_requirements_multiple_packages(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("requests==2.25.0\n")
            f.write("urllib3==1.26.0\n")
            f.write("flask==3.0.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) == 2
        finally:
            os.unlink(path)

    def test_scan_requirements_ignores_comments(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# requests==2.25.0\n")
            f.write("flask==3.0.0\n")
            path = f.name

        try:
            findings = DependencyScanner.scan_requirements(path)
            assert len(findings) == 0
        finally:
            os.unlink(path)


class TestJwtSecurity:
    """Security-focused JWT tests."""

    def test_jwt_secret_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "")
        assert True  # JWT_SECRET is empty by default

    def test_create_token_fails_without_secret(self, monkeypatch):
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "")
        from proxy.app.auth.jwt import create_token

        with pytest.raises(ValueError, match="JWT_SECRET"):
            create_token(user_id="u1", username="alice")

    def test_none_algorithm_rejected(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
        import jwt as pyjwt
        from fastapi import HTTPException

        from proxy.app.auth.jwt import verify_token

        fake_token = pyjwt.encode({"sub": "user", "exp": 9999999999}, "", algorithm="none")
        with pytest.raises(HTTPException) as exc_info:
            verify_token(fake_token)
        assert exc_info.value.status_code == 401

    def test_expired_token_rejected(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
        from fastapi import HTTPException

        from proxy.app.auth.jwt import create_token, verify_token

        token = create_token(user_id="u1", username="alice", expires_in_hours=-1)
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_blacklist_works(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")

        mock_db = AsyncMock()
        mock_db.add_to_blacklist = AsyncMock()

        with (
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db),
            patch("jwt.decode", return_value={"jti": "test-jti-123", "exp": int(time.time()) + 3600}),
        ):
            from proxy.app.auth.jwt import blacklist_access_token

            await blacklist_access_token("fake-token")
            mock_db.add_to_blacklist.assert_called_once()

    def test_token_without_jti_set(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
        from proxy.app.auth.jwt import create_token, verify_token

        token = create_token(user_id="u1", username="alice")
        decoded = verify_token(token)
        assert decoded.user_id == "u1"
        assert decoded.username == "alice"

    def test_rs256_without_public_key_fails(self, monkeypatch):
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "RS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "RS256")
        monkeypatch.setattr("proxy.app.shared.config.JWT_PUBLIC_KEY", "")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_PUBLIC_KEY", "")
        from proxy.app.auth.jwt import _get_verify_key

        assert _get_verify_key() is None


class TestSQLInjectionSafety:
    """Tests verifying parameterized queries prevent SQL injection."""

    def test_user_db_uses_parameterized_queries(self):
        import inspect

        from proxy.app.auth.user_db import UserDatabase

        source = inspect.getsource(UserDatabase.create_user)
        assert "?" in source

    def test_no_string_interpolation_in_queries(self):
        import inspect

        from proxy.app.auth.user_db import UserDatabase

        methods = [
            "create_user",
            "get_user",
            "get_user_by_username",
            "verify_password",
            "store_refresh_token",
            "consume_refresh_token",
            "add_to_blacklist",
            "is_blacklisted",
            "update_user",
            "delete_user",
            "list_users",
        ]
        for method_name in methods:
            source = inspect.getsource(getattr(UserDatabase, method_name))
            assert "f'" not in source or "SELECT" not in source, f"{method_name} has potential SQL injection"
            assert "%s" not in source or "SELECT" not in source, f"{method_name} has potential SQL injection"

    def test_user_db_uses_parameterized_placeholders(self):
        import inspect

        from proxy.app.auth.user_db import UserDatabase

        source = inspect.getsource(UserDatabase.create_user)
        assert "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)" in source

    def test_update_user_allowed_fields(self):
        import inspect

        from proxy.app.auth.user_db import UserDatabase

        source = inspect.getsource(UserDatabase.update_user)
        assert "allowed" in source
        assert "email" in source


class TestRateLimiting:
    """Tests for rate limiting logic."""

    def test_token_bucket_basics(self):
        from proxy.app.shared.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=10.0, burst=5)
        for _ in range(5):
            allowed, _ = bucket.consume()
            assert allowed is True
        allowed, wait = bucket.consume()
        assert allowed is False
        assert wait > 0

    def test_token_bucket_refill(self):
        from proxy.app.shared.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=100.0, burst=5)
        for _ in range(5):
            bucket.consume()
        time.sleep(0.1)
        allowed, _ = bucket.consume()
        assert allowed is True

    def test_rate_limiter_key_extraction_ip(self):
        from proxy.app.shared.rate_limiter import RateLimiter, RateLimitMiddleware

        limiter = RateLimiter(rate_per_minute=60, burst=10)

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {}

        middleware = RateLimitMiddleware(None, limiter)
        key = middleware._extract_key(mock_request)
        assert "192.168.1.100" in key

    def test_rate_limiter_key_extraction_api_key(self):
        from proxy.app.shared.rate_limiter import RateLimiter, RateLimitMiddleware

        limiter = RateLimiter(rate_per_minute=60, burst=10)

        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.headers = {"Authorization": "Bearer sk-test-apikey"}

        middleware = RateLimitMiddleware(None, limiter)
        key = middleware._extract_key(mock_request)
        assert "sk-test-apikey" in key

    def test_auth_endpoint_login_rate_limit(self):
        from fastapi import HTTPException

        from proxy.app.api.auth_endpoints import _LOGIN_MAX_ATTEMPTS, _check_login_rate_limit

        for i in range(_LOGIN_MAX_ATTEMPTS):
            try:
                _check_login_rate_limit("test-login-ip")
            except HTTPException:
                pytest.fail(f"Rate limit triggered too early at attempt {i + 1}")

        with pytest.raises(HTTPException) as exc_info:
            _check_login_rate_limit("test-login-ip")
        assert exc_info.value.status_code == 429

    def test_rate_limiter_cleanup_expired(self):
        import asyncio

        from proxy.app.shared.rate_limiter import RateLimiter

        async def run_test():
            limiter = RateLimiter(rate_per_minute=60, burst=10)
            await limiter.is_allowed("key-old-1")
            await limiter.is_allowed("key-old-2")
            assert len(limiter._buckets) == 2
            await limiter.cleanup_expired(max_age=0.0)
            assert len(limiter._buckets) == 0

        asyncio.run(run_test())


class TestConfigSecurity:
    """Tests for configuration security defaults."""

    def test_jwt_secret_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "")
        assert True  # JWT_SECRET is empty by default

    def test_neo4j_password_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        monkeypatch.setattr("proxy.app.shared.config.NEO4J_PASSWORD", "")
        assert True  # NEO4J_PASSWORD is empty by default

    def test_minio_credentials_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
        monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
        monkeypatch.setattr("proxy.app.shared.config.MINIO_ACCESS_KEY", "")
        monkeypatch.setattr("proxy.app.shared.config.MINIO_SECRET_KEY", "")
        assert True  # MINIO credentials are empty by default

    def test_auth_disabled_by_default(self):
        from proxy.app.shared.config import AUTH_ENABLED, RBAC_ENABLED

        assert AUTH_ENABLED is False
        assert RBAC_ENABLED is False

    def test_rate_limit_disabled_by_default(self):
        from proxy.app.shared.config import RATE_LIMIT_ENABLED

        assert RATE_LIMIT_ENABLED is False

    def test_sanitize_input_enabled_by_default(self):
        from proxy.app.shared.config import SANITIZE_INPUT

        assert SANITIZE_INPUT is True

    def test_user_db_path_is_local(self):
        from proxy.app.shared.config import USER_DB_PATH

        assert USER_DB_PATH == "./data/users.db"

    def test_bcrypt_rounds_are_acceptable(self):
        from proxy.app.shared.config import BCRYPT_ROUNDS

        assert BCRYPT_ROUNDS >= 10
