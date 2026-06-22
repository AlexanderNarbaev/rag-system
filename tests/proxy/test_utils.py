"""Tests for proxy/app/utils.py utility functions."""
import json
import re
import sys
from unittest.mock import patch, MagicMock

import pytest

from proxy.app.utils import (
    compute_hash,
    estimate_tokens,
    truncate_by_tokens,
    generate_request_id,
    format_metadata,
    now_iso,
    safe_json_loads,
    extract_issue_keys,
    extract_urls,
    mask_sensitive_data,
    chunk_list,
    safe_divide,
    TIKTOKEN_AVAILABLE,
)


class TestComputeHash:
    """Tests for compute_hash function."""

    def test_hash_string(self):
        result = compute_hash("hello")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_dict_deterministic(self):
        a = compute_hash({"b": 2, "a": 1})
        b = compute_hash({"a": 1, "b": 2})
        assert a == b

    def test_hash_list(self):
        result = compute_hash([1, 2, 3])
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_different_values_different_hash(self):
        a = compute_hash("hello")
        b = compute_hash("world")
        assert a != b

    def test_hash_empty_string(self):
        result = compute_hash("")
        assert len(result) == 64


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_fallback_estimation(self):
        with patch("proxy.app.utils.TIKTOKEN_AVAILABLE", False):
            assert estimate_tokens("abcd") == 1
            assert estimate_tokens("abcdefgh") == 2
            assert estimate_tokens("abc") == 0

    def test_tiktoken_available(self):
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(5))
        with patch("proxy.app.utils.TIKTOKEN_AVAILABLE", True), \
             patch("proxy.app.utils.tiktoken") as mock_tiktoken:
            mock_tiktoken.encoding_for_model.return_value = mock_encoding
            result = estimate_tokens("some text", model="gpt-4")
            assert result == 5
            mock_tiktoken.encoding_for_model.assert_called_with("gpt-4")

    def test_tiktoken_falls_back_on_error(self):
        with patch("proxy.app.utils.TIKTOKEN_AVAILABLE", True), \
             patch("proxy.app.utils.tiktoken") as mock_tiktoken:
            mock_tiktoken.encoding_for_model.side_effect = Exception("boom")
            result = estimate_tokens("12345678")
            assert result == 2  # fallback: 8 // 4


class TestTruncateByTokens:
    """Tests for truncate_by_tokens function."""

    def test_within_limit(self):
        text = "short"
        assert truncate_by_tokens(text, max_tokens=100) == text

    def test_exceeds_limit(self):
        text = "a" * 100
        with patch("proxy.app.utils.TIKTOKEN_AVAILABLE", False):
            result = truncate_by_tokens(text, max_tokens=10)
            assert result.endswith("...")
            assert len(result) <= 10 * 4 + 3

    def test_very_small_max(self):
        text = "a" * 100
        with patch("proxy.app.utils.TIKTOKEN_AVAILABLE", False):
            result = truncate_by_tokens(text, max_tokens=0)
            assert result == "..."

    def test_empty_text(self):
        assert truncate_by_tokens("", max_tokens=10) == ""


class TestGenerateRequestId:
    """Tests for generate_request_id function."""

    def test_format(self):
        rid = generate_request_id()
        assert rid.startswith("rag_")
        parts = rid.split("_")
        assert len(parts) == 3
        assert parts[1].isdigit()

    def test_uniqueness(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestFormatMetadata:
    """Tests for format_metadata function."""

    def test_non_empty_metadata(self):
        result = format_metadata({"source": "confluence", "version": "2.0"})
        assert "source: confluence" in result
        assert "version: 2.0" in result

    def test_none_value_skipped(self):
        result = format_metadata({"key": None, "name": "test"})
        assert "key" not in result
        assert "name: test" in result

    def test_empty_dict(self):
        assert format_metadata({}) == ""

    def test_none_input(self):
        assert format_metadata(None) == ""


class TestNowIso:
    """Tests for now_iso function."""

    def test_returns_string(self):
        result = now_iso()
        assert isinstance(result, str)
        assert "T" in result

    def test_iso_format_parsable(self):
        from datetime import datetime
        result = now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed is not None


class TestSafeJsonLoads:
    """Tests for safe_json_loads function."""

    def test_valid_json(self):
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_valid_list(self):
        assert safe_json_loads('[1, 2, 3]') == [1, 2, 3]

    def test_invalid_json_returns_default(self):
        assert safe_json_loads("not json") is None
        assert safe_json_loads("not json", default=[]) == []

    def test_empty_string(self):
        assert safe_json_loads("") is None


class TestExtractIssueKeys:
    """Tests for extract_issue_keys function."""

    def test_single_issue(self):
        assert extract_issue_keys("See PROJ-123 for details") == ["PROJ-123"]

    def test_multiple_issues(self):
        result = extract_issue_keys("PROJ-1 and TEST-456 and DEV-789")
        assert result == ["PROJ-1", "TEST-456", "DEV-789"]

    def test_no_issues(self):
        assert extract_issue_keys("no issues here") == []

    def test_underscore_in_project(self):
        # \b boundary means underscore prevents matching "PROJ-42" in "REF_PROJ-42"
        # because _ is a word character, so there's no word boundary before P
        assert extract_issue_keys("REF_PROJ-42 is done") == []
        assert extract_issue_keys("PROJ-42 is done") == ["PROJ-42"]

    def test_full_jira_key(self):
        result = extract_issue_keys("RELATED-TO TMS-9999 and OPS-001")
        assert len(result) == 2


class TestExtractUrls:
    """Tests for extract_urls function."""

    def test_http_url(self):
        assert extract_urls("visit http://example.com") == ["http://example.com"]

    def test_https_url(self):
        assert extract_urls("see https://docs.example.org/page") == ["https://docs.example.org/page"]

    def test_multiple_urls(self):
        text = "a: https://a.com b: https://b.com"
        assert extract_urls(text) == ["https://a.com", "https://b.com"]

    def test_no_urls(self):
        assert extract_urls("no urls here") == []

    def test_url_in_brackets(self):
        result = extract_urls('see <https://example.com/path?q=1>')
        assert "https://example.com/path?q=1" in result


class TestMaskSensitiveData:
    """Tests for mask_sensitive_data function."""

    def test_token_masking(self):
        token = "a" * 50
        result = mask_sensitive_data(f"my token: {token}")
        assert "[REDACTED_TOKEN]" in result
        assert token not in result

    def test_short_string_not_masked(self):
        result = mask_sensitive_data("abc123")
        assert "[REDACTED]" not in result
        assert "[REDACTED_TOKEN]" not in result

    def test_custom_secrets(self):
        secret = "my-secret-key"
        result = mask_sensitive_data(f"use key: {secret}", secrets=[secret])
        assert "[REDACTED]" in result
        assert secret not in result

    def test_empty_text(self):
        assert mask_sensitive_data("") == ""

    def test_none_input(self):
        assert mask_sensitive_data(None) is None


class TestChunkList:
    """Tests for chunk_list function."""

    def test_even_split(self):
        assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_chunk_size_larger_than_list(self):
        assert chunk_list([1, 2], 10) == [[1, 2]]

    def test_empty_list(self):
        assert chunk_list([], 3) == []

    def test_chunk_size_one(self):
        assert chunk_list([1, 2, 3], 1) == [[1], [2], [3]]


class TestSafeDivide:
    """Tests for safe_divide function."""

    def test_normal_division(self):
        assert safe_divide(10, 2) == 5.0

    def test_zero_division_returns_default(self):
        assert safe_divide(10, 0) == 0.0

    def test_custom_default(self):
        assert safe_divide(10, 0, default=-1.0) == -1.0

    def test_negative_numbers(self):
        assert safe_divide(-10, 2) == -5.0
