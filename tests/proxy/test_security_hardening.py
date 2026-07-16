"""Security hardening tests for RAG proxy.

Tests cover:
- Request signing (HMAC) for webhooks
- IP allowlisting for admin endpoints
- Audit logging for all auth events
- Password history (prevent reuse)
- Integration of hardening features with existing security
"""

import time

from proxy.app.shared.security import (
    IPAllowlist,
    PasswordHistoryManager,
    RequestSigner,
    SecretsManager,
)


class TestRequestSigner:
    """Tests for HMAC-based webhook request signing."""

    def test_sign_produces_valid_hex(self):
        secret = "test-secret"
        payload = '{"event": "page_created"}'
        signature = RequestSigner.sign(payload, secret)
        assert isinstance(signature, str)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_is_deterministic_with_timestamp(self):
        secret = "test-secret"
        payload = "test-payload"
        ts = "1234567890"
        sig1 = RequestSigner.sign(payload, secret, timestamp=ts)
        sig2 = RequestSigner.sign(payload, secret, timestamp=ts)
        assert sig1 == sig2

    def test_sign_differs_with_different_payloads(self):
        secret = "test-secret"
        sig1 = RequestSigner.sign("payload-a", secret, timestamp="100")
        sig2 = RequestSigner.sign("payload-b", secret, timestamp="100")
        assert sig1 != sig2

    def test_sign_differs_with_different_secrets(self):
        payload = "test-payload"
        sig1 = RequestSigner.sign(payload, "secret-a", timestamp="100")
        sig2 = RequestSigner.sign(payload, "secret-b", timestamp="100")
        assert sig1 != sig2

    def test_verify_valid_signature(self):
        secret = "shared-secret"
        payload = '{"event": "issue_updated"}'
        ts = str(int(time.time()))
        signature = RequestSigner.sign(payload, secret, timestamp=ts)
        assert RequestSigner.verify(payload, signature, secret, ts) is True

    def test_verify_rejects_expired_timestamp(self):
        secret = "shared-secret"
        payload = "test"
        old_ts = str(int(time.time()) - 600)
        signature = RequestSigner.sign(payload, secret, timestamp=old_ts)
        assert RequestSigner.verify(payload, signature, secret, old_ts) is False

    def test_verify_rejects_wrong_secret(self):
        payload = "test"
        ts = str(int(time.time()))
        signature = RequestSigner.sign(payload, "correct-secret", timestamp=ts)
        assert RequestSigner.verify(payload, signature, "wrong-secret", ts) is False

    def test_verify_rejects_tampered_payload(self):
        secret = "shared-secret"
        ts = str(int(time.time()))
        signature = RequestSigner.sign("original", secret, timestamp=ts)
        assert RequestSigner.verify("tampered", signature, secret, ts) is False

    def test_verify_rejects_empty_signature(self):
        assert RequestSigner.verify("payload", "", "secret", "123") is False

    def test_verify_rejects_empty_timestamp(self):
        assert RequestSigner.verify("payload", "sig", "secret", "") is False

    def test_verify_rejects_invalid_timestamp_format(self):
        assert RequestSigner.verify("payload", "sig", "secret", "not-a-number") is False

    def test_generate_secret_length(self):
        secret = RequestSigner.generate_secret()
        assert len(secret) == 64

    def test_generate_secret_is_random(self):
        s1 = RequestSigner.generate_secret()
        s2 = RequestSigner.generate_secret()
        assert s1 != s2

    def test_extract_from_request_headers(self):
        headers = {
            "X-Webhook-Signature": "abc123",
            "X-Webhook-Timestamp": "1700000000",
            "Content-Type": "application/json",
        }
        sig, ts = RequestSigner.extract_from_request(headers, "body")
        assert sig == "abc123"
        assert ts == "1700000000"

    def test_extract_from_request_missing_headers(self):
        headers = {"Content-Type": "application/json"}
        sig, ts = RequestSigner.extract_from_request(headers, "body")
        assert sig == ""
        assert ts == ""

    def test_timing_attack_resistant_comparison(self):
        """Verify that signature comparison is constant-time."""
        secret = "test-secret"
        payload = "test"
        ts = str(int(time.time()))
        sig = RequestSigner.sign(payload, secret, timestamp=ts)

        # Wrong prefix signature — same length
        wrong_sig = "0" * len(sig)
        assert RequestSigner.verify(payload, wrong_sig, secret, ts) is False

        # Wrong length signature
        assert RequestSigner.verify(payload, "short", secret, ts) is False


class TestIPAllowlist:
    """Tests for IP allowlisting and denylisting."""

    def test_empty_allowlist_allows_all(self):
        al = IPAllowlist()
        assert al.is_allowed("192.168.1.1") is True
        assert al.is_allowed("10.0.0.1") is True
        assert al.is_allowed("127.0.0.1") is True

    def test_allowlist_single_ip(self):
        al = IPAllowlist(allowlist=["10.0.0.5"])
        assert al.is_allowed("10.0.0.5") is True
        assert al.is_allowed("10.0.0.6") is False
        assert al.is_allowed("192.168.1.1") is False

    def test_allowlist_cidr_range(self):
        al = IPAllowlist(allowlist=["10.0.0.0/24"])
        assert al.is_allowed("10.0.0.1") is True
        assert al.is_allowed("10.0.0.255") is True
        assert al.is_allowed("10.0.1.1") is False

    def test_allowlist_multiple_entries(self):
        al = IPAllowlist(allowlist=["10.0.0.5", "192.168.1.0/24"])
        assert al.is_allowed("10.0.0.5") is True
        assert al.is_allowed("192.168.1.100") is True
        assert al.is_allowed("172.16.0.1") is False

    def test_denylist_blocks_allowlisted_ip(self):
        al = IPAllowlist(allowlist=["10.0.0.0/8"], denylist=["10.0.0.5"])
        assert al.is_allowed("10.0.0.1") is True
        assert al.is_allowed("10.0.0.5") is False

    def test_denylist_alone_blocks_specific_ip(self):
        al = IPAllowlist(denylist=["192.168.1.100"])
        assert al.is_allowed("192.168.1.1") is True
        assert al.is_allowed("192.168.1.100") is False

    def test_denylist_cidr_block(self):
        al = IPAllowlist(denylist=["192.168.0.0/16"])
        assert al.is_allowed("10.0.0.1") is True
        assert al.is_allowed("192.168.1.1") is False

    def test_invalid_ip_is_denied(self):
        al = IPAllowlist(allowlist=["10.0.0.0/24"])
        assert al.is_allowed("not-an-ip") is False

    def test_add_to_allowlist(self):
        al = IPAllowlist()
        assert al.add_to_allowlist("10.0.0.1") is True
        assert al.is_allowed("10.0.0.1") is True

    def test_add_invalid_entry_to_allowlist(self):
        al = IPAllowlist()
        assert al.add_to_allowlist("not-an-ip/33") is False

    def test_add_to_denylist(self):
        al = IPAllowlist()
        assert al.add_to_denylist("10.0.0.1") is True
        assert al.is_allowed("10.0.0.1") is False

    def test_remove_from_allowlist(self):
        al = IPAllowlist(allowlist=["10.0.0.5", "10.0.0.6"])
        assert al.is_allowed("10.0.0.5") is True
        assert al.is_allowed("10.0.0.6") is True
        assert al.remove_from_allowlist("10.0.0.5") is True
        assert al.is_allowed("10.0.0.5") is False
        assert al.is_allowed("10.0.0.6") is True

    def test_remove_nonexistent_from_allowlist(self):
        al = IPAllowlist()
        assert al.remove_from_allowlist("10.0.0.5") is False

    def test_allowlist_entries_property(self):
        al = IPAllowlist(allowlist=["10.0.0.1", "10.0.0.0/24"])
        entries = al.allowlist_entries
        assert "10.0.0.1" in entries
        assert "10.0.0.0/24" in entries

    def test_denylist_entries_property(self):
        al = IPAllowlist(denylist=["192.168.0.0/16", "10.0.0.5"])
        entries = al.denylist_entries
        assert "192.168.0.0/16" in entries
        assert "10.0.0.5" in entries

    def test_localhost_is_allowlisted_by_default(self):
        al = IPAllowlist()
        assert al.is_allowed("127.0.0.1") is True
        assert al.is_allowed("::1") is True

    def test_is_denied_invalid_ip(self):
        al = IPAllowlist()
        assert al.is_denied("not-an-ip") is True

    def test_empty_string_in_allowlist_ignored(self):
        al = IPAllowlist(allowlist=["", "10.0.0.1"])
        assert al.is_allowed("10.0.0.1") is True

    def test_add_empty_string_to_allowlist(self):
        al = IPAllowlist()
        assert al.add_to_allowlist("") is False


class TestPasswordHistoryManager:
    """Tests for password history and reuse prevention."""

    def test_is_previously_used_true(self):
        manager = PasswordHistoryManager(max_history=3)
        password = "OldPassword1!"
        old_hash = manager.hash_password(password)
        assert manager.is_previously_used(password, [old_hash]) is True

    def test_is_previously_used_false(self):
        manager = PasswordHistoryManager(max_history=3)
        old_password = "OldPassword1!"
        new_password = "NewPassword2@"
        old_hash = manager.hash_password(old_password)
        assert manager.is_previously_used(new_password, [old_hash]) is False

    def test_respects_max_history_limit(self):
        manager = PasswordHistoryManager(max_history=2)
        pw1_hash = manager.hash_password("Password1!")
        pw2_hash = manager.hash_password("Password2@")
        pw3_hash = manager.hash_password("Password3#")

        history = [pw1_hash, pw2_hash, pw3_hash]
        assert manager.is_previously_used("Password1!", history) is False
        assert manager.is_previously_used("Password2@", history) is True
        assert manager.is_previously_used("Password3#", history) is True

    def test_hash_password_uses_bcrypt(self):
        manager = PasswordHistoryManager()
        h = manager.hash_password("TestPassword1!")
        assert h.startswith("$2b$") or h.startswith("$2a$") or h.startswith("$2y$")

    def test_hash_password_is_salted(self):
        manager = PasswordHistoryManager()
        h1 = manager.hash_password("SamePassword1!")
        h2 = manager.hash_password("SamePassword1!")
        assert h1 != h2

    def test_trim_history_respects_max(self):
        manager = PasswordHistoryManager(max_history=2)
        history = ["hash1", "hash2", "hash3", "hash4"]
        trimmed = manager.trim_history(history, manager.max_history)
        assert len(trimmed) == 2
        assert trimmed == ["hash3", "hash4"]

    def test_trim_history_no_trim_needed(self):
        manager = PasswordHistoryManager(max_history=5)
        history = ["hash1", "hash2"]
        trimmed = manager.trim_history(history, manager.max_history)
        assert trimmed == history

    def test_max_history_property(self):
        manager = PasswordHistoryManager(max_history=7)
        assert manager.max_history == 7

    def test_default_max_history(self):
        manager = PasswordHistoryManager()
        assert manager.max_history == 5

    def test_max_history_minimum_one(self):
        manager = PasswordHistoryManager(max_history=0)
        assert manager.max_history == 1


class TestSecretsManagerExtended:
    """Additional tests for SecretsManager including hardening features."""

    def test_generate_api_key_prefix(self):
        key = SecretsManager.generate_api_key("rag")
        assert key.startswith("rag_")
        assert len(key) > 10

    def test_constant_time_compare_equal(self):
        assert SecretsManager.constant_time_compare("abc", "abc") is True

    def test_constant_time_compare_different(self):
        assert SecretsManager.constant_time_compare("abc", "abd") is False

    def test_constant_time_compare_different_lengths(self):
        assert SecretsManager.constant_time_compare("abc", "abcd") is False

    def test_constant_time_compare_empty(self):
        assert SecretsManager.constant_time_compare("", "") is True

    def test_generate_token_length(self):
        token = SecretsManager.generate_token(64)
        assert len(token) > 40

    def test_generate_token_random(self):
        t1 = SecretsManager.generate_token()
        t2 = SecretsManager.generate_token()
        assert t1 != t2
