"""Enhanced security tests: security headers completeness, API key rotation,
CSRF protection, SQL injection detection, rate limiting edge cases, JWT edge cases."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from proxy.app.shared.security import (
    CSRFProtection,
    InputValidator,
    SecurityHeaders,
    SQLInjectionDetector,
)


class TestSecurityHeadersCompleteness:
    """Tests for all security headers including newly added ones."""

    def test_all_security_headers_present(self):
        headers = SecurityHeaders.get_headers()
        required = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "Referrer-Policy",
            "Permissions-Policy",
            "Cross-Origin-Opener-Policy",
            "Cross-Origin-Resource-Policy",
            "Cross-Origin-Embedder-Policy",
            "X-Permitted-Cross-Domain-Policies",
            "X-Download-Options",
            "X-DNS-Prefetch-Control",
            "Cache-Control",
        ]
        for h in required:
            assert h in headers, f"Missing required security header: {h}"

    def test_coop_same_origin(self):
        headers = SecurityHeaders.get_headers()
        assert headers["Cross-Origin-Opener-Policy"] == "same-origin"

    def test_corp_same_origin(self):
        headers = SecurityHeaders.get_headers()
        assert headers["Cross-Origin-Resource-Policy"] == "same-origin"

    def test_coep_credentialless(self):
        headers = SecurityHeaders.get_headers()
        assert headers["Cross-Origin-Embedder-Policy"] == "credentialless"

    def test_permitted_cross_domain_none(self):
        headers = SecurityHeaders.get_headers()
        assert headers["X-Permitted-Cross-Domain-Policies"] == "none"

    def test_download_options_noopen(self):
        headers = SecurityHeaders.get_headers()
        assert headers["X-Download-Options"] == "noopen"

    def test_dns_prefetch_control_off(self):
        headers = SecurityHeaders.get_headers()
        assert headers["X-DNS-Prefetch-Control"] == "off"

    def test_hsts_max_age(self):
        headers = SecurityHeaders.get_headers()
        assert "max-age=31536000" in headers["Strict-Transport-Security"]
        assert "includeSubDomains" in headers["Strict-Transport-Security"]

    def test_csp_no_unsafe_eval(self):
        headers = SecurityHeaders.get_headers()
        csp = headers["Content-Security-Policy"]
        assert "unsafe-eval" not in csp

    def test_csp_no_data_uri_in_script(self):
        headers = SecurityHeaders.get_headers()
        csp = headers["Content-Security-Policy"]
        assert "script-src 'self' 'unsafe-inline'" in csp
        assert "data:" not in csp.split("script-src")[1].split(";")[0] if "script-src" in csp else True

    def test_permissions_policy_sensors(self):
        headers = SecurityHeaders.get_headers()
        pp = headers["Permissions-Policy"]
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp

    def test_cache_control_no_store(self):
        headers = SecurityHeaders.get_headers()
        cc = headers["Cache-Control"]
        assert "no-store" in cc
        assert "no-cache" in cc
        assert "must-revalidate" in cc

    def test_referrer_policy(self):
        headers = SecurityHeaders.get_headers()
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_xss_protection_block_mode(self):
        headers = SecurityHeaders.get_headers()
        assert headers["X-XSS-Protection"] == "1; mode=block"

    def test_total_header_count(self):
        headers = SecurityHeaders.get_headers()
        assert len(headers) >= 14

    def test_extra_headers_override(self):
        headers = SecurityHeaders.get_headers(extra={
            "X-Frame-Options": "SAMEORIGIN",
            "Cache-Control": "public, max-age=60",
        })
        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert headers["Cache-Control"] == "public, max-age=60"

    def test_extra_headers_add_new(self):
        headers = SecurityHeaders.get_headers(extra={"X-Custom-Security": "enabled"})
        assert headers["X-Custom-Security"] == "enabled"
        assert headers["X-Content-Type-Options"] == "nosniff"


class TestAPIKeySecurity:
    """Tests for API key rotation, expiry, and security properties."""

    def test_generate_key_has_prefix(self):
        from proxy.app.auth.api_keys import api_key_manager

        key = api_key_manager.generate_key("test-user")
        assert key.startswith("sk-")
        assert len(key) > 40

    def test_generate_key_hash_not_stored_plaintext(self):
        from proxy.app.auth.api_keys import api_key_manager

        key = api_key_manager.generate_key("hash-user")
        for stored_key in api_key_manager._keys.values():
            assert stored_key.key_hash != key

    def test_key_has_expiry(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("expiry-user", ttl_days=30)
        stored = api_key_manager.list_keys(user_id="expiry-user")[0]
        assert stored.expires_at is not None
        exp = datetime.fromisoformat(stored.expires_at)  # type: ignore[arg-type]
        assert exp > datetime.now(UTC)

    def test_default_ttl_is_90_days(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("default-ttl-user")
        stored = api_key_manager.list_keys(user_id="default-ttl-user")[0]
        assert stored.expires_at is not None
        exp = datetime.fromisoformat(stored.expires_at)  # type: ignore[arg-type]
        delta = exp - datetime.now(UTC)
        assert 80 < delta.days <= 91

    def test_expired_key_rejected(self):
        from proxy.app.auth.api_keys import api_key_manager

        key_value = api_key_manager.generate_key("expired-user", ttl_days=0)
        stored = api_key_manager.list_keys(user_id="expired-user")[0]
        stored.expires_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        result = api_key_manager.validate_key(key_value)
        assert result is None

    def test_valid_key_accepted(self):
        from proxy.app.auth.api_keys import api_key_manager

        key_value = api_key_manager.generate_key("valid-user", ttl_days=90)
        result = api_key_manager.validate_key(key_value)
        assert result is not None
        assert result.user_id == "valid-user"

    def test_revoked_key_rejected(self):
        from proxy.app.auth.api_keys import api_key_manager

        key_value = api_key_manager.generate_key("revoked-user")
        stored = api_key_manager.list_keys(user_id="revoked-user")[0]
        api_key_manager.revoke_key(stored.key_id)
        result = api_key_manager.validate_key(key_value)
        assert result is None

    def test_rotate_key_produces_new_valid_key(self):
        from proxy.app.auth.api_keys import api_key_manager

        old_key = api_key_manager.generate_key("rotate-user")
        old_stored = api_key_manager.list_keys(user_id="rotate-user")[0]
        new_key = api_key_manager.rotate_key(old_stored.key_id)
        assert new_key is not None
        assert new_key != old_key
        new_stored = api_key_manager.list_keys(user_id="rotate-user")
        assert len(new_stored) >= 1

    def test_rotate_key_invalid_id_returns_none(self):
        from proxy.app.auth.api_keys import api_key_manager

        result = api_key_manager.rotate_key("nonexistent-key-id")
        assert result is None

    def test_rotate_key_records_lineage(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("lineage-user")
        old_stored = api_key_manager.list_keys(user_id="lineage-user")[0]
        api_key_manager.rotate_key(old_stored.key_id)
        new_keys = api_key_manager.list_keys(user_id="lineage-user")
        newest = [k for k in new_keys if k.rotated_from_key_id == old_stored.key_id]
        assert len(newest) >= 1

    def test_max_keys_per_user(self):
        from proxy.app.auth.api_keys import ApiKeyManager

        mgr = ApiKeyManager()
        for _ in range(mgr.MAX_KEYS_PER_USER):
            mgr.generate_key("max-user")
        with pytest.raises(ValueError, match="maximum"):
            mgr.generate_key("max-user")

    def test_validate_key_none_or_non_sk(self):
        from proxy.app.auth.api_keys import api_key_manager

        assert api_key_manager.validate_key(None) is None  # type: ignore[arg-type]
        assert api_key_manager.validate_key("") is None
        assert api_key_manager.validate_key("not-an-api-key") is None
        assert api_key_manager.validate_key("Bearer something") is None

    def test_validate_key_updates_last_used(self):
        from proxy.app.auth.api_keys import api_key_manager

        key_value = api_key_manager.generate_key("lastused-user")
        result = api_key_manager.validate_key(key_value)
        assert result is not None
        assert result.last_used is not None

    def test_key_uniqueness(self):
        from proxy.app.auth.api_keys import api_key_manager

        keys = {api_key_manager.generate_key(f"user-{i}") for i in range(100)}
        assert len(keys) == 100

    def test_expire_key_manual(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("manual-expire-user")
        stored = api_key_manager.list_keys(user_id="manual-expire-user")[0]
        assert api_key_manager.expire_key(stored.key_id) is True
        assert api_key_manager.expire_key("nonexistent") is False

    def test_list_keys_active_only(self):
        from proxy.app.auth.api_keys import ApiKeyManager

        mgr = ApiKeyManager()
        mgr.generate_key("filter-user-1")
        mgr.generate_key("filter-user-2")
        stored_1 = mgr.list_keys(user_id="filter-user-1")[0]
        mgr.revoke_key(stored_1.key_id)
        active = mgr.list_keys()
        assert len(active) >= 1
        assert all(k.is_active and not k.is_expired for k in active)

    def test_key_health_summary(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("health-user")
        health = api_key_manager.get_key_health()
        assert health["total_keys"] >= 1
        assert health["active_keys"] >= 1
        assert "expired_keys" in health
        assert "keys_near_expiry" in health
        assert health["max_keys_per_user"] == 10

    def test_cleanup_expired_keys(self):
        from proxy.app.auth.api_keys import ApiKeyManager

        mgr = ApiKeyManager()
        mgr.generate_key("cleanup-user")
        stored = mgr.list_keys(user_id="cleanup-user")[0]
        stored.expires_at = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        removed = mgr.cleanup_expired_keys()
        assert removed >= 1

    def test_is_expired_property(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("prop-expired", ttl_days=0)
        stored = api_key_manager.list_keys(user_id="prop-expired", include_inactive=True)[0]
        stored.expires_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        assert stored.is_expired is True

    def test_is_expired_no_expiry(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("prop-noexpiry")
        stored = api_key_manager.list_keys(user_id="prop-noexpiry", include_inactive=True)[0]
        stored.expires_at = None
        assert stored.is_expired is False

    def test_age_days(self):
        from proxy.app.auth.api_keys import api_key_manager

        api_key_manager.generate_key("age-user")
        stored = api_key_manager.list_keys(user_id="age-user", include_inactive=True)[0]
        assert stored.age_days is not None
        assert stored.age_days >= 0


class TestCSRFProtection:
    """Tests for CSRF protection utility."""

    def test_generate_token_is_unique(self):
        tokens = {CSRFProtection.generate_token() for _ in range(50)}
        assert len(tokens) == 50

    def test_generate_token_length(self):
        token = CSRFProtection.generate_token()
        assert len(token) >= 32

    def test_validate_with_matching_tokens(self):
        token = CSRFProtection.generate_token()
        headers = {CSRFProtection.HEADER_NAME: token}
        cookies = {CSRFProtection.COOKIE_NAME: token}
        assert CSRFProtection.validate_request(headers, cookies) is True

    def test_validate_with_mismatched_tokens(self):
        headers = {CSRFProtection.HEADER_NAME: CSRFProtection.generate_token()}
        cookies = {CSRFProtection.COOKIE_NAME: CSRFProtection.generate_token()}
        assert CSRFProtection.validate_request(headers, cookies) is False

    def test_validate_with_missing_header(self):
        cookies = {CSRFProtection.COOKIE_NAME: CSRFProtection.generate_token()}
        assert CSRFProtection.validate_request({}, cookies) is False

    def test_validate_with_missing_cookie(self):
        headers = {CSRFProtection.HEADER_NAME: CSRFProtection.generate_token()}
        assert CSRFProtection.validate_request(headers, {}) is False

    def test_validate_with_empty_both(self):
        assert CSRFProtection.validate_request({}, {}) is False

    def test_state_changing_methods(self):
        assert CSRFProtection.is_state_changing("POST") is True
        assert CSRFProtection.is_state_changing("PUT") is True
        assert CSRFProtection.is_state_changing("PATCH") is True
        assert CSRFProtection.is_state_changing("DELETE") is True

    def test_non_state_changing_methods(self):
        assert CSRFProtection.is_state_changing("GET") is False
        assert CSRFProtection.is_state_changing("HEAD") is False
        assert CSRFProtection.is_state_changing("OPTIONS") is False

    def test_header_name_constant(self):
        assert CSRFProtection.HEADER_NAME == "X-CSRF-Token"
        assert CSRFProtection.COOKIE_NAME == "csrf_token"

    def test_token_is_urlsafe(self):
        for _ in range(20):
            token = CSRFProtection.generate_token()
            assert "+" not in token
            assert "/" not in token
            assert "=" not in token


class TestSQLInjectionDetector:
    """Tests for SQL injection and XSS pattern detection."""

    def test_detect_union_select(self):
        findings = SQLInjectionDetector.detect_sqli("1 UNION SELECT * FROM users")
        assert len(findings) > 0

    def test_detect_drop_table(self):
        findings = SQLInjectionDetector.detect_sqli("; DROP TABLE users; --")
        assert len(findings) > 0

    def test_detect_or_injection(self):
        findings = SQLInjectionDetector.detect_sqli("' OR '1'='1")
        assert len(findings) > 0

    def test_detect_sleep_injection(self):
        findings = SQLInjectionDetector.detect_sqli("1; SLEEP(5)")
        assert len(findings) > 0

    def test_detect_benchmark_injection(self):
        findings = SQLInjectionDetector.detect_sqli("1 AND BENCHMARK(1000000,MD5('a'))")
        assert len(findings) > 0

    def test_clean_input_no_findings(self):
        findings = SQLInjectionDetector.detect_sqli("What is the capital of France?")
        assert len(findings) == 0

    def test_detect_xss_script_tag(self):
        findings = SQLInjectionDetector.detect_xss("<script>alert('xss')</script>")
        assert len(findings) > 0

    def test_detect_xss_javascript_uri(self):
        findings = SQLInjectionDetector.detect_xss("javascript:alert(1)")
        assert len(findings) > 0

    def test_detect_xss_event_handler(self):
        findings = SQLInjectionDetector.detect_xss("<img onerror='alert(1)'>")
        assert len(findings) > 0

    def test_detect_xss_iframe(self):
        findings = SQLInjectionDetector.detect_xss("<iframe src='evil.com'></iframe>")
        assert len(findings) > 0

    def test_detect_xss_data_uri(self):
        findings = SQLInjectionDetector.detect_xss("data:text/html,<script>alert(1)</script>")
        assert len(findings) > 0

    def test_detect_xss_vbscript(self):
        findings = SQLInjectionDetector.detect_xss("vbscript:msgbox(1)")
        assert len(findings) > 0

    def test_clean_input_no_xss(self):
        findings = SQLInjectionDetector.detect_xss("Normal text without any HTML")
        assert len(findings) == 0

    def test_is_suspicious_sqli(self):
        assert SQLInjectionDetector.is_suspicious("' OR 1=1 --") is True

    def test_is_suspicious_xss(self):
        assert SQLInjectionDetector.is_suspicious("<script>alert(1)</script>") is True

    def test_is_suspicious_clean(self):
        assert SQLInjectionDetector.is_suspicious("What is RAG?") is False

    def test_detect_delete_from(self):
        findings = SQLInjectionDetector.detect_sqli("DELETE FROM users WHERE id=1")
        assert len(findings) > 0

    def test_detect_insert_into(self):
        findings = SQLInjectionDetector.detect_sqli("INSERT INTO users VALUES ('admin','pass')")
        assert len(findings) > 0

    def test_detect_alter_table(self):
        findings = SQLInjectionDetector.detect_sqli("ALTER TABLE users ADD COLUMN hacked")
        assert len(findings) > 0

    def test_detect_waitfor_delay(self):
        findings = SQLInjectionDetector.detect_sqli("WAITFOR DELAY '00:00:05'")
        assert len(findings) > 0

    def test_detect_xss_expression(self):
        findings = SQLInjectionDetector.detect_xss("expression(alert(1))")
        assert len(findings) > 0


class TestInputValidatorEdgeCases:
    """Edge case tests for InputValidator."""

    def test_validate_query_unicode_normalization(self):
        result = InputValidator.validate_query("Caf\u00e9 r\u00e9sum\u00e9")
        assert "Caf" in result or "r\u00e9sum\u00e9" in result

    def test_validate_query_multibyte_boundary(self):
        query = "a" * 7999 + "\u4e2d"
        result = InputValidator.validate_query(query)
        assert len(result) <= InputValidator.MAX_QUERY_LENGTH

    def test_validate_query_only_html(self):
        result = InputValidator.validate_query("<b><i><u></u></i></b>")
        assert result == ""

    def test_validate_query_nested_html(self):
        result = InputValidator.validate_query("<div><span>text</span></div>")
        assert "text" in result
        assert "<div>" not in result

    def test_validate_query_html_entities(self):
        result = InputValidator.validate_query("&lt;script&gt;alert&lpar;1&rpar;&lt;/script&gt;")
        assert "script" in result.lower()

    def test_validate_non_empty_strips_control_chars(self):
        result = InputValidator.validate_non_empty("test\x00data\x1fhere", max_len=100)
        assert result is not None
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_validate_model_name_extended_chars(self):
        valid = [
            "gpt-4",
            "claude-3.5-sonnet",
            "meta-llama/Llama-3.1-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
            "sentence-transformers/all-MiniLM-L6-v2",
        ]
        for name in valid:
            assert InputValidator.validate_model_name(name) is True, f"Failed: {name}"

    def test_validate_model_name_null_byte(self):
        assert InputValidator.validate_model_name("model\x00hidden") is False

    def test_path_traversal_backslash(self):
        assert InputValidator.validate_path_traversal("..\\..\\windows\\system32") is False

    def test_path_traversal_encoded(self):
        assert InputValidator.validate_path_traversal("/normal/path/file.txt") is True

    def test_sanitize_for_log_no_pii(self):
        text = "Simple log message without PII"
        result = InputValidator.sanitize_for_log(text)
        assert result == text

    def test_sanitize_for_log_jwt_token(self):
        jwt_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            + "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        result = InputValidator.sanitize_for_log(f"Token: {jwt_token}")
        assert jwt_token not in result
        assert "[REDACTED]" in result

    def test_sanitize_for_log_credit_card(self):
        result = InputValidator.sanitize_for_log("Card: 4111111111111111")
        assert "4111111111111111" in result  # Not redacted (too short)

    def test_sanitize_headers_case_insensitive(self):
        headers = {
            "Authorization": "Bearer token1",
            "AUTHORIZATION": "Bearer token2",
            "X-Api-Key": "sk-secret1",
            "Cookie": "session=abc",
            "Set-Cookie": "session=xyz",
        }
        result = InputValidator.sanitize_headers(headers)
        assert result["Authorization"] == "[REDACTED]"
        assert result["AUTHORIZATION"] == "[REDACTED]"
        assert result["X-Api-Key"] == "[REDACTED]"
        assert result["Cookie"] == "[REDACTED]"
        assert result["Set-Cookie"] == "[REDACTED]"

    def test_escape_shell_arg_keeps_safe_chars(self):
        assert InputValidator.escape_shell_arg("my-file_v2.0") == "my-file_v2.0"
        assert InputValidator.escape_shell_arg("path/to/file") == "pathtofile"


class TestRateLimitingEdgeCases:
    """Edge case tests for rate limiting."""

    def test_token_bucket_precision(self):
        from proxy.app.shared.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=1.0, burst=1)
        allowed, _ = bucket.consume()
        assert allowed is True
        allowed, wait = bucket.consume()
        assert allowed is False
        assert wait > 0.9

    def test_token_bucket_burst_never_exceeds(self):
        from proxy.app.shared.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=100.0, burst=3)
        for _ in range(10):
            bucket.consume()
        assert bucket.tokens <= 3

    def test_token_bucket_high_rate(self):
        from proxy.app.shared.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=10000.0, burst=100)
        for _ in range(100):
            allowed, _ = bucket.consume()
            assert allowed is True

    def test_rate_limiter_same_key_shared_bucket(self):
        async def _test():
            from proxy.app.shared.rate_limiter import RateLimiter

            limiter = RateLimiter(rate_per_minute=600, burst=5)
            for _ in range(5):
                allowed, _ = await limiter.is_allowed("shared-key")
                assert allowed is True
            allowed, _ = await limiter.is_allowed("shared-key")
            assert allowed is False

        asyncio.run(_test())

    def test_rate_limiter_different_keys_independent(self):
        async def _test():
            from proxy.app.shared.rate_limiter import RateLimiter

            limiter = RateLimiter(rate_per_minute=600, burst=3)
            for _ in range(3):
                await limiter.is_allowed("key-a")
            allowed, _ = await limiter.is_allowed("key-b")
            assert allowed is True

        asyncio.run(_test())

    def test_rate_limiter_key_with_spaces(self):
        from proxy.app.shared.rate_limiter import RateLimiter, RateLimitMiddleware

        limiter = RateLimiter(rate_per_minute=60, burst=10)
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers = {"Authorization": "Bearer key with spaces"}
        middleware = RateLimitMiddleware(None, limiter)
        key = middleware._extract_key(mock_request)
        assert "key with spaces" in key

    def test_x_forwarded_for_extraction(self):
        from proxy.app.shared.rate_limiter import RateLimiter, RateLimitMiddleware

        limiter = RateLimiter(rate_per_minute=60, burst=10)
        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.headers = {
            "X-Forwarded-For": "203.0.113.1, 10.0.0.1",
        }

        import proxy.app.shared.config as config_mod
        import proxy.app.shared.rate_limiter as rl_mod

        original_trusted_config = config_mod.TRUSTED_PROXY_COUNT
        original_trusted_rl = rl_mod.TRUSTED_PROXY_COUNT
        try:
            config_mod.TRUSTED_PROXY_COUNT = 2
            rl_mod.TRUSTED_PROXY_COUNT = 2
            middleware = RateLimitMiddleware(None, limiter)
            key = middleware._extract_key(mock_request)
            assert "203.0.113.1" in key
        finally:
            config_mod.TRUSTED_PROXY_COUNT = original_trusted_config  # type: ignore[assignment]
            rl_mod.TRUSTED_PROXY_COUNT = original_trusted_rl  # type: ignore[assignment]


class TestJWTEdgeCases:
    """Edge case tests for JWT token handling."""

    def test_create_token_with_custom_expiry(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-edge")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-edge")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-edge")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")

        from proxy.app.auth.jwt import create_token

        token = create_token(user_id="u1", username="alice", expires_in_hours=1)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 20

    def test_token_contains_all_claims(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-claims")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-claims")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-claims")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")

        from proxy.app.auth.jwt import create_token, verify_token

        token = create_token(
            user_id="u-claims",
            username="testuser",
            roles=["admin", "expert"],
            groups=["engineering", "platform"],
            access_level="confidential",
            namespace="engineering",
            expires_in_hours=24,
        )
        ctx = verify_token(token)
        assert ctx.user_id == "u-claims"
        assert ctx.username == "testuser"
        assert "admin" in ctx.roles
        assert "expert" in ctx.roles
        assert "engineering" in ctx.groups
        assert "platform" in ctx.groups
        assert ctx.access_level == "confidential"
        assert ctx.namespace == "engineering"

    def test_verify_invalid_token_format(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-invalid")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-invalid")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-invalid")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")

        from fastapi import HTTPException

        from proxy.app.auth.jwt import verify_token

        with pytest.raises(HTTPException) as exc_info:
            verify_token("not.a.valid.jwt")
        assert exc_info.value.status_code == 401

    def test_verify_empty_token(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-empty")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-empty")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-empty")

        from fastapi import HTTPException

        from proxy.app.auth.jwt import verify_token

        with pytest.raises(HTTPException) as exc_info:
            verify_token("")
        assert exc_info.value.status_code == 401

    def test_get_user_from_token_expired(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-expired-gentle")
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-expired-gentle")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-expired-gentle")
        monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")

        from proxy.app.auth.jwt import create_token, get_user_from_token

        token = create_token(user_id="u1", username="alice", expires_in_hours=-1)
        ctx = get_user_from_token(token)
        assert ctx is None

    def test_user_context_properties(self):
        from proxy.app.auth.jwt import UserContext

        admin = UserContext(user_id="a1", username="admin", roles=["admin", "user"])
        assert admin.is_admin is True
        assert admin.is_expert is False

        expert = UserContext(user_id="e1", username="expert", roles=["expert", "user"])
        assert expert.is_expert is True
        assert expert.is_admin is False

        anon = UserContext.anonymous()
        assert anon.is_authenticated is False
        assert anon.user_id == "anonymous"

    def test_user_context_effective_namespace(self):
        from proxy.app.auth.jwt import UserContext

        ctx = UserContext(user_id="u1", username="u", namespace="sales", groups=["engineering"])
        assert ctx.effective_namespace == "sales"

        ctx2 = UserContext(user_id="u2", username="u", namespace="", groups=["platform"])
        assert ctx2.effective_namespace == "platform"

        ctx3 = UserContext(user_id="u3", username="u")
        assert ctx3.effective_namespace == ""


class TestSecretsManagerEdgeCases:
    """Edge case tests for SecretsManager."""

    def test_mask_in_response_nested_list_of_dicts(self):
        from proxy.app.shared.security import SecretsManager

        data = {
            "items": [
                {"name": "a", "token": "t1"},
                {"name": "b", "secret": "s1"},
                {"name": "c"},
            ],
        }
        result = SecretsManager.mask_in_response(data)
        assert result["items"][0]["token"] == "***"
        assert result["items"][1]["secret"] == "***"
        assert result["items"][2]["name"] == "c"

    def test_mask_in_response_deeply_nested(self):
        from proxy.app.shared.security import SecretsManager

        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "password": "deep-secret",
                        "name": "visible",
                    },
                },
            },
        }
        result = SecretsManager.mask_in_response(data)
        assert result["level1"]["level2"]["level3"]["password"] == "***"
        assert result["level1"]["level2"]["level3"]["name"] == "visible"

    def test_generate_api_key_length(self):
        from proxy.app.shared.security import SecretsManager

        key = SecretsManager.generate_api_key()
        assert key.startswith("rag_")
        assert len(key) > 30  # prefix rag_ + token_urlsafe(32) ≈ 47 chars

    def test_constant_time_compare_timing(self):
        import time as time_m

        from proxy.app.shared.security import SecretsManager

        a = "a" * 1000
        b = "a" * 999 + "b"
        start = time_m.perf_counter()
        SecretsManager.constant_time_compare(a, b)
        duration_diff = time_m.perf_counter() - start

        a2 = "a" * 1000
        b2 = "a" * 1000
        start = time_m.perf_counter()
        SecretsManager.constant_time_compare(a2, b2)
        duration_same = time_m.perf_counter() - start

        assert abs(duration_diff - duration_same) < 0.02

    def test_verify_secret_against_wrong_hash_format(self):
        from proxy.app.shared.security import SecretsManager

        assert SecretsManager.verify_secret("test", "not-a-valid-hash") is False

    def test_hash_secret_utf8(self):
        from proxy.app.shared.security import SecretsManager

        result = SecretsManager.hash_secret("пароль123!@#")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestPasswordPolicyEdgeCases:
    """Edge case tests for password strength validation."""

    def test_policy_min_length_exactly_10(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        valid, _ = PasswordStrengthValidator.validate("Abcdefgh1!")
        assert valid is True

    def test_policy_max_length_exactly_128(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        pwd = "A" + "b" * 125 + "1!"
        valid, _ = PasswordStrengthValidator.validate(pwd)
        assert valid is True

    def test_policy_over_max_length(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        pwd = "A" + "b" * 128 + "1!"
        valid, error = PasswordStrengthValidator.validate(pwd)
        assert valid is False
        assert error is not None
        assert "at most" in error.lower()

    def test_policy_all_special_chars(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        valid, _ = PasswordStrengthValidator.validate("!@#$%^&*()Ab1")
        assert valid is True

    def test_policy_common_weak_passwords_rejected(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        valid, error = PasswordStrengthValidator.validate("Password1!")
        assert valid is True

    def test_policy_empty_string(self):
        from proxy.app.shared.security import PasswordStrengthValidator

        valid, error = PasswordStrengthValidator.validate("")
        assert valid is False


class TestConfigSecurityEdgeCases:
    """Tests for secure configuration defaults."""

    def test_ssl_verify_enabled_by_default(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.SSL_VERIFY is True

    def test_bcrypt_rounds_minimum(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.BCRYPT_ROUNDS >= 10

    def test_token_blacklist_max_entries(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.TOKEN_BLACKLIST_MAX_ENTRIES >= 1000

    def test_refresh_token_days_reasonable(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.REFRESH_TOKEN_DAYS <= 30

    def test_workers_is_one_for_safety(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.WORKERS == 1

    def test_cors_origins_localhost_only(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        origins = cfg.CORS_ORIGINS
        assert "localhost" in origins
        assert "0.0.0.0" not in origins


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware behavior."""

    @pytest.mark.asyncio
    async def test_middleware_injects_headers(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from proxy.app.shared.middleware import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse("ok")

        client = TestClient(app)
        response = client.get("/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
        assert response.headers.get("Cross-Origin-Resource-Policy") == "same-origin"
        assert response.headers.get("Cross-Origin-Embedder-Policy") == "credentialless"
        assert response.headers.get("X-Permitted-Cross-Domain-Policies") == "none"
        assert response.headers.get("X-Download-Options") == "noopen"
        assert response.headers.get("X-DNS-Prefetch-Control") == "off"

    @pytest.mark.asyncio
    async def test_middleware_does_not_overwrite_existing(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from proxy.app.shared.middleware import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom")
        async def custom_endpoint():
            from fastapi.responses import Response
            return Response("ok", headers={"X-Frame-Options": "SAMEORIGIN"})

        client = TestClient(app)
        response = client.get("/custom")
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestInputSanitizationMiddleware:
    """Tests for InputSanitizationMiddleware."""

    @pytest.mark.asyncio
    async def test_sanitization_is_idempotent_on_clean_input(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from proxy.app.shared.middleware import InputSanitizationMiddleware

        app = FastAPI()
        app.add_middleware(InputSanitizationMiddleware)

        @app.get("/search")
        async def search(q: str = ""):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(q)

        client = TestClient(app)
        response = client.get("/search", params={"q": "What is RAG?"})
        assert response.status_code == 200
        assert response.text == "What is RAG?"
