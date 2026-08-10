"""Focused edge-case tests for proxy/app/shared/security.py.

Targeted at IPAllowlist, RequestSigner, and validation paths that may
not be exercised fully by existing comprehensive tests.
"""

from __future__ import annotations

import time

from proxy.app.shared.security import (
    CSRFProtection,
    InputValidator,
    IPAllowlist,
    PasswordStrengthValidator,
    RequestSigner,
    SecretsManager,
    SecurityHeaders,
    SQLInjectionDetector,
)

# ---------------------------------------------------------------------------
# InputValidator edge cases
# ---------------------------------------------------------------------------


class TestInputValidatorEdge:
    def test_non_string_query_returns_empty(self):
        assert InputValidator.validate_query(123) == ""
        assert InputValidator.validate_query(None) == ""

    def test_truncates_long_queries(self):
        long_q = "a" * 10000
        result = InputValidator.validate_query(long_q)
        assert len(result) <= InputValidator.MAX_QUERY_LENGTH

    def test_validate_non_empty_default(self):
        assert InputValidator.validate_non_empty("") is None
        assert InputValidator.validate_non_empty(123) is None

    def test_validate_non_empty_strips_html(self):
        result = InputValidator.validate_non_empty("<b>hello</b>")
        assert result == "hello"

    def test_sanitize_email_replaced(self):
        result = InputValidator.sanitize_for_log("contact test@example.com today")
        assert "[EMAIL]" in result
        assert "test@example.com" not in result

    def test_sanitize_ip_replaced(self):
        result = InputValidator.sanitize_for_log("from 192.168.1.42")
        assert "[IP]" in result

    def test_sanitize_long_token(self):
        result = InputValidator.sanitize_for_log("token=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD")
        assert "[REDACTED]" in result

    def test_sanitize_non_string(self):
        assert InputValidator.sanitize_for_log(123) == ""

    def test_validate_model_name_invalid(self):
        # "model/../etc" contains '/' which is allowed in the regex.
        # Use semicolon which is NOT in the allowed character class.
        assert InputValidator.validate_model_name("model;DROP") is False
        assert InputValidator.validate_model_name("evil name with spaces") is False

    def test_validate_path_traversal(self):
        assert InputValidator.validate_path_traversal("../etc/passwd") is False
        assert InputValidator.validate_path_traversal("~/secret") is False
        assert InputValidator.validate_path_traversal("/safe/path") is True

    def test_sanitize_headers_redacts_known(self):
        headers = {
            "Authorization": "Bearer x",
            "X-API-Key": "key1",
            "Content-Type": "application/json",
        }
        result = InputValidator.sanitize_headers(headers)
        assert result["Authorization"] == "[REDACTED]"
        assert result["X-API-Key"] == "[REDACTED]"
        assert result["Content-Type"] == "application/json"

    def test_escape_shell_arg(self):
        assert InputValidator.escape_shell_arg("hello-world.txt") == "hello-world.txt"
        assert "$" not in InputValidator.escape_shell_arg("echo $HOME")
        assert ";" not in InputValidator.escape_shell_arg("rm; sudo")

    def test_escape_shell_arg_non_string(self):
        assert InputValidator.escape_shell_arg(123) == ""


# ---------------------------------------------------------------------------
# SecretsManager edge cases
# ---------------------------------------------------------------------------


class TestSecretsManagerEdge:
    def test_constant_time_compare_bytes(self):
        # Should accept bytes too (used internally for hmac.compare_digest)
        assert SecretsManager.constant_time_compare(b"abc", b"abc") is True

    def test_constant_time_compare_diff(self):
        assert SecretsManager.constant_time_compare("a", "b") is False

    def test_generate_token_default_length(self):
        token = SecretsManager.generate_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_mask_in_response_handles_list(self):
        data = {"items": [{"password": "secret"}]}
        result = SecretsManager.mask_in_response(data)
        assert result["items"][0]["password"] == "***"

    def test_mask_in_response_handles_list_non_dict(self):
        data = {"items": [{"x": 1}, "string", 5]}
        result = SecretsManager.mask_in_response(data)
        # Strings/ints in list pass through
        assert result["items"][1] == "string"
        assert result["items"][2] == 5

    def test_mask_in_response_non_dict(self):
        # Non-dict input is returned as-is
        assert SecretsManager.mask_in_response("not a dict") == "not a dict"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SecurityHeaders
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_default_headers_have_x_frame_options(self):
        assert "X-Frame-Options" in SecurityHeaders.DEFAULT_HEADERS

    def test_get_headers_merges_extras(self):
        extra = {"X-Custom-Header": "value"}
        result = SecurityHeaders.get_headers(extra)
        assert result["X-Custom-Header"] == "value"
        assert "X-Frame-Options" in result  # defaults preserved

    def test_get_headers_extras_override_defaults(self):
        extra = {"X-Frame-Options": "SAMEORIGIN"}
        result = SecurityHeaders.get_headers(extra)
        assert result["X-Frame-Options"] == "SAMEORIGIN"


# ---------------------------------------------------------------------------
# PasswordStrengthValidator
# ---------------------------------------------------------------------------


class TestPasswordStrength:
    def test_valid_password(self):
        valid, msg = PasswordStrengthValidator.validate("Strong1!Password")
        assert valid is True
        assert msg is None

    def test_too_short(self):
        valid, msg = PasswordStrengthValidator.validate("Ab1!")
        assert valid is False
        assert "at least" in (msg or "")

    def test_no_uppercase(self):
        valid, msg = PasswordStrengthValidator.validate("weak1!password")
        assert valid is False
        assert "uppercase" in (msg or "")

    def test_no_lowercase(self):
        valid, msg = PasswordStrengthValidator.validate("WEAK1!PASSWORD")
        assert valid is False
        assert "lowercase" in (msg or "")

    def test_no_digit(self):
        valid, msg = PasswordStrengthValidator.validate("WeakPass!Word")
        assert valid is False
        assert "digit" in (msg or "")

    def test_no_special(self):
        valid, msg = PasswordStrengthValidator.validate("Weak1Password")
        assert valid is False
        assert "special" in (msg or "")

    def test_too_long(self):
        very_long = "Aa1!" + "x" * 130
        valid, msg = PasswordStrengthValidator.validate(very_long)
        assert valid is False

    def test_non_string(self):
        valid, msg = PasswordStrengthValidator.validate(12345)
        assert valid is False
        assert "string" in (msg or "")


# ---------------------------------------------------------------------------
# CSRFProtection
# ---------------------------------------------------------------------------


class TestCSRFProtection:
    def test_generate_token_unique(self):
        t1 = CSRFProtection.generate_token()
        t2 = CSRFProtection.generate_token()
        assert t1 != t2
        assert len(t1) > 0

    def test_validate_matching(self):
        token = CSRFProtection.generate_token()
        headers = {CSRFProtection.HEADER_NAME: token}
        cookies = {CSRFProtection.COOKIE_NAME: token}
        assert CSRFProtection.validate_request(headers, cookies) is True

    def test_validate_mismatch(self):
        headers = {CSRFProtection.HEADER_NAME: "a"}
        cookies = {CSRFProtection.COOKIE_NAME: "b"}
        assert CSRFProtection.validate_request(headers, cookies) is False

    def test_validate_missing_header(self):
        cookies = {CSRFProtection.COOKIE_NAME: "x"}
        assert CSRFProtection.validate_request({}, cookies) is False

    def test_validate_missing_cookie(self):
        headers = {CSRFProtection.HEADER_NAME: "x"}
        assert CSRFProtection.validate_request(headers, {}) is False

    def test_is_state_changing(self):
        assert CSRFProtection.is_state_changing("POST") is True
        assert CSRFProtection.is_state_changing("DELETE") is True
        assert CSRFProtection.is_state_changing("PATCH") is True
        assert CSRFProtection.is_state_changing("PUT") is True
        assert CSRFProtection.is_state_changing("GET") is False


# ---------------------------------------------------------------------------
# SQLInjectionDetector
# ---------------------------------------------------------------------------


class TestSQLInjection:
    def test_clean_text(self):
        assert SQLInjectionDetector.is_suspicious("hello world") is False

    def test_basic_sqli(self):
        assert SQLInjectionDetector.is_suspicious("1; DROP TABLE users") is True

    def test_union_select(self):
        assert SQLInjectionDetector.is_suspicious("UNION SELECT * FROM users") is True

    def test_basic_xss(self):
        assert SQLInjectionDetector.is_suspicious("<script>alert(1)</script>") is True

    def test_javascript_uri(self):
        assert SQLInjectionDetector.is_suspicious("javascript:alert(1)") is True

    def test_on_event_attr(self):
        assert SQLInjectionDetector.is_suspicious('onerror="alert(1)"') is True


# ---------------------------------------------------------------------------
# RequestSigner
# ---------------------------------------------------------------------------


class TestRequestSigner:
    def test_sign_and_verify(self):
        secret = "shh"
        payload = '{"key":"value"}'
        ts = str(int(time.time()))
        sig = RequestSigner.sign(payload, secret, timestamp=ts)
        assert RequestSigner.verify(payload, sig, secret, ts) is True

    def test_verify_wrong_secret(self):
        sig = RequestSigner.sign("payload", "real", timestamp=str(int(time.time())))
        assert RequestSigner.verify("payload", sig, "wrong", str(int(time.time()))) is False

    def test_verify_expired_timestamp(self):
        # Timestamp from 1 hour ago
        old_ts = str(int(time.time()) - 3600)
        sig = RequestSigner.sign("payload", "secret", timestamp=old_ts)
        assert RequestSigner.verify("payload", sig, "secret", old_ts) is False

    def test_verify_missing_signature(self):
        assert RequestSigner.verify("payload", "", "secret", str(int(time.time()))) is False

    def test_verify_missing_timestamp(self):
        assert RequestSigner.verify("payload", "sig", "secret", "") is False

    def test_verify_non_integer_timestamp(self):
        assert RequestSigner.verify("p", "sig", "secret", "not-an-int") is False

    def test_extract_from_request(self):
        headers = {
            RequestSigner.SIGNATURE_HEADER: "abc",
            RequestSigner.TIMESTAMP_HEADER: "123",
        }
        sig, ts = RequestSigner.extract_from_request(headers, "body")
        assert sig == "abc"
        assert ts == "123"

    def test_extract_from_request_empty(self):
        sig, ts = RequestSigner.extract_from_request({}, "body")
        assert sig == ""
        assert ts == ""


# ---------------------------------------------------------------------------
# IPAllowlist
# ---------------------------------------------------------------------------


class TestIPAllowlist:
    def test_empty_allows_all(self):
        al = IPAllowlist()
        assert al.is_allowed("127.0.0.1") is True

    def test_specific_allow(self):
        al = IPAllowlist(allowlist=["192.168.1.1"])
        assert al.is_allowed("192.168.1.1") is True
        assert al.is_allowed("10.0.0.1") is False

    def test_cidr_allow(self):
        al = IPAllowlist(allowlist=["192.168.1.0/24"])
        assert al.is_allowed("192.168.1.5") is True
        assert al.is_allowed("192.168.2.5") is False

    def test_deny_overrides_allow(self):
        al = IPAllowlist(allowlist=["192.168.1.0/24"], denylist=["192.168.1.5"])
        assert al.is_allowed("192.168.1.5") is False
        assert al.is_allowed("192.168.1.10") is True

    def test_invalid_ip_format(self):
        al = IPAllowlist()
        assert al.is_allowed("not-an-ip") is False

    def test_invalid_cidr_skipped(self):
        # Bad CIDR should be silently skipped
        al = IPAllowlist(allowlist=["bad-cidr", "192.168.1.0/24"])
        assert al.is_allowed("192.168.1.5") is True

    def test_is_denied(self):
        al = IPAllowlist(denylist=["192.168.1.1"])
        assert al.is_denied("192.168.1.1") is True
        assert al.is_denied("192.168.1.2") is False

    def test_is_denied_invalid_ip(self):
        al = IPAllowlist()
        # Invalid IP returns True (per implementation: "deny-by-default on invalid")
        assert al.is_denied("not-an-ip") is True

    def test_add_to_allowlist(self):
        al = IPAllowlist()
        al.add_to_allowlist("10.0.0.5")
        assert al.is_allowed("10.0.0.5") is True

    def test_add_to_denylist(self):
        al = IPAllowlist()
        al.add_to_denylist("10.0.0.5")
        assert al.is_allowed("10.0.0.5") is False

    def test_add_empty_returns_false(self):
        al = IPAllowlist()
        assert al.add_to_allowlist("") is False
        assert al.add_to_denylist("") is False

    def test_add_invalid_ip_silent(self):
        # For non-CIDR single IPs the implementation has no
        # validation — it just adds to the set. Only CIDR-format
        # inputs raise ValueError on parse error.
        al = IPAllowlist()
        # Non-CIDR invalid IP is added without error.
        assert al.add_to_allowlist("not-an-ip") is True

    def test_add_invalid_cidr_returns_false(self):
        al = IPAllowlist()
        assert al.add_to_allowlist("10.0.0.0/abc") is False

    def test_blank_entries_skipped(self):
        al = IPAllowlist(allowlist=["", "  "])
        # Both blank — no real entries
        assert al.is_allowed("10.0.0.1") is True

    def test_ipv6_allow(self):
        al = IPAllowlist(allowlist=["::1"])
        assert al.is_allowed("::1") is True
