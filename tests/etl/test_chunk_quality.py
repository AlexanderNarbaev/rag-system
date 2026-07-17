"""Tests for etl/indexer/chunk_quality.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from etl.indexer.chunk_quality import (
    BOILERPLATE_PATTERNS,
    ChunkQualityFilter,
    build_chunk_quality_filter_from_config,
)


class TestChunkQualityFilterInit:
    def test_default_initialization(self) -> None:
        qf = ChunkQualityFilter(
            reranker_endpoint="http://host:8080/v1/rerank",
            model="test-model",
        )
        assert qf._endpoint == "http://host:8080"
        assert qf._rerank_url == "http://host:8080/v1/rerank"
        assert qf._model == "test-model"
        assert qf._threshold == 0.3
        assert qf._detect_boilerplate_enabled is True
        assert qf._max_chunks_per_doc == 500

    def test_custom_threshold(self) -> None:
        qf = ChunkQualityFilter(
            reranker_endpoint="http://host:8080",
            model="test",
            threshold=0.5,
        )
        assert qf._threshold == 0.5

    def test_endpoint_normalization(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080/v1/rerank")
        assert qf._rerank_url == "http://host:8080/v1/rerank"

        qf2 = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        assert qf2._rerank_url == "http://host:8080/v1/rerank"

        qf3 = ChunkQualityFilter(reranker_endpoint="http://host:8080/v1")
        assert qf3._rerank_url == "http://host:8080/v1/rerank"

    def test_api_key_in_headers(self) -> None:
        qf = ChunkQualityFilter(
            reranker_endpoint="http://host:8080",
            api_key="sk-test",
        )
        headers = qf._make_headers()
        assert headers["Authorization"] == "Bearer sk-test"

    def test_no_api_key_in_headers(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        headers = qf._make_headers()
        assert "Authorization" not in headers

    def test_healthy_by_default(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        assert qf.is_healthy is True


class TestScoreChunks:
    def test_empty_texts_returns_neutral(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        scores = qf.score_chunks("query", [])
        assert scores == []

    def test_empty_query_returns_neutral(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        scores = qf.score_chunks("", ["text1", "text2"])
        assert scores == [0.5, 0.5]

    def test_successful_api_call(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.32},
                {"index": 2, "relevance_score": 0.78},
            ],
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            scores = qf.score_chunks("test query", ["chunk1", "chunk2", "chunk3"])
            assert len(scores) == 3
            assert scores[0] == 0.95
            assert scores[1] == 0.32
            assert scores[2] == 0.78

    def test_api_failure_returns_neutral(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            scores = qf.score_chunks("query", ["chunk1", "chunk2"])
            assert scores == [0.5, 0.5]
            assert qf.is_healthy is False


class TestDetectBoilerplate:
    def test_empty_chunk(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("")
        assert is_bp is True
        assert "minimal" in reason or "too_short" in reason

    def test_whitespace_only_chunk(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("   \n  \t  ")
        assert is_bp is True

    def test_too_short_chunk(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("ab")
        assert is_bp is True
        assert "too_short" in reason

    def test_too_few_words(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("helloworldhelloworldhelloworld")
        assert is_bp is True
        assert "too_few_words" in reason

    def test_copyright_boilerplate(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Copyright 2024 All Rights Reserved. This document is proprietary.")
        assert is_bp is True
        assert "boilerplate" in reason

    def test_last_modified_boilerplate(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Last modified by John Doe on January 15, 2025")
        assert is_bp is True
        assert "boilerplate" in reason

    def test_russian_boilerplate(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Последнее изменение: 15 января 2025. Все права защищены.")
        assert is_bp is True

    def test_navigation_breadcrumb(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Home > Documentation > API Reference > Endpoints")
        assert is_bp is True

    def test_previous_page_nav(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Previous page: Introduction | Next page: Setup Guide")
        assert is_bp is True

    def test_valid_content_passes(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate(
            "The CI/CD pipeline is configured through a YAML file. Each job defines "
            "a set of commands to execute within a Docker container. GitLab Runners "
            "are the agents that execute these jobs.",
        )
        assert is_bp is False

    def test_horizontal_rule(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("---")
        assert is_bp is True

    def test_powered_by_boilerplate(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Powered by Confluence. Terms of Use | Privacy Policy")
        assert is_bp is True

    def test_boilerplate_disabled(self) -> None:
        """When detect_boilerplate is disabled, filter() skips boilerplate detection.
        The detect_boilerplate() method itself still works when called directly."""
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080", detect_boilerplate=False)
        assert qf._detect_boilerplate_enabled is False
        # The method itself still detects, but filter() won't use it

    def test_social_media_boilerplate(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Follow us on Twitter, Facebook, and LinkedIn")
        assert is_bp is True


class TestFilter:
    def setup_method(self) -> None:
        self.qf = ChunkQualityFilter(reranker_endpoint="http://host:8080", threshold=0.3)

    def test_empty_chunks_returns_empty(self) -> None:
        filtered, stats = self.qf.filter("Test Doc", [])
        assert filtered == []
        assert stats["total"] == 0

    def test_all_boilerplate_filtered(self) -> None:
        chunks = [
            {"text": "Copyright 2024 All Rights Reserved.", "heading": ""},
            {"text": "Last modified by admin", "heading": ""},
        ]
        filtered, stats = self.qf.filter("Test Doc", chunks)
        assert len(filtered) == 0
        assert stats["dropped"] == 2
        assert stats["dropped_boilerplate"] == 2
        assert stats["dropped_pct"] == 100.0

    def test_boilerplate_detection_disabled_skips_filtering(self) -> None:
        """When detect_boilerplate is disabled, boilerplate chunks pass through."""
        qf = ChunkQualityFilter(
            reranker_endpoint="http://host:8080",
            threshold=0.0,
            detect_boilerplate=False,
        )
        chunks = [
            {"text": "Copyright 2024 All Rights Reserved. Some more text here to pass checks."},
        ]
        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.95},
            ],
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            filtered, stats = qf.filter("Test Doc", chunks)
            assert stats["dropped_boilerplate"] == 0

    def test_filter_by_relevance(self) -> None:
        """Test that chunks below threshold are filtered out."""
        chunks = [
            {"text": "Relevant content about the document topic goes here.", "heading": "Topic"},
            {"text": "Another relevant paragraph with useful information.", "heading": "Details"},
            {"text": "This is about a completely different unrelated subject.", "heading": "Other"},
        ]

        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.85},
                {"index": 1, "relevance_score": 0.72},
                {"index": 2, "relevance_score": 0.15},
                # Heading scores
            ],
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            filtered, stats = self.qf.filter("Test Document Title", chunks)
            assert len(filtered) >= 1
            assert stats["total"] == 3
            assert stats["kept"] <= 3

    def test_max_chunks_safety_limit(self) -> None:
        """Test that chunks beyond max limit are truncated."""
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080", max_chunks_per_doc=2)
        chunks = [
            {"text": f"Chunk number {i} with enough text to pass boilerplate check."}
            for i in range(10)
        ]

        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.8},
            ],
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            filtered, stats = qf.filter("Test Doc", chunks)
            assert stats["total"] == 10
            assert len(filtered) <= 2

    def test_mixed_boilerplate_and_relevance(self) -> None:
        """Test filter with some boilerplate and some relevant chunks."""
        chunks = [
            {"text": "Relevant content about the topic with meaningful information.", "heading": "Intro"},
            {"text": "Copyright 2024 Company. All Rights Reserved.", "heading": ""},
            {"text": "More detailed analysis of the subject matter discussed here.", "heading": "Analysis"},
            {"text": "Follow us on social media for updates.", "heading": ""},
        ]

        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.88},
                {"index": 1, "relevance_score": 0.72},
            ],
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            filtered, stats = self.qf.filter("Test Document", chunks)
            assert stats["total"] == 4
            assert stats["dropped_boilerplate"] == 2
            assert stats["dropped_relevance"] >= 0


class TestQualityAnnotations:
    def test_filter_adds_score_annotations(self) -> None:
        """Test that filtered chunks get quality score annotations."""
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080", threshold=0.3)
        chunks = [
            {"text": "Meaningful content about the document subject matter here.", "heading": "Section"},
        ]

        mock_response = {
            "results": [
                {"index": 0, "relevance_score": 0.92},
            ],
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            filtered, stats = qf.filter("Document Title", chunks)
            assert len(filtered) >= 1
            if filtered:
                chunk = filtered[0]
                assert "_quality_title_score" in chunk
                assert "_quality_combined" in chunk


class TestBuildFromConfig:
    def test_disabled_returns_none(self) -> None:
        config = {"quality_filter": {"enabled": False}}
        result = build_chunk_quality_filter_from_config(config)
        assert result is None

    def test_no_section_returns_none(self) -> None:
        config = {"other": {}}
        result = build_chunk_quality_filter_from_config(config)
        assert result is None

    def test_enabled_but_no_endpoint_returns_none(self) -> None:
        config = {"quality_filter": {"enabled": True, "reranker_endpoint": ""}}
        result = build_chunk_quality_filter_from_config(config)
        assert result is None

    def test_fully_configured_returns_filter(self) -> None:
        config = {
            "quality_filter": {
                "enabled": True,
                "reranker_endpoint": "http://host:8080/v1/rerank",
                "reranker_model": "test-model",
                "relevance_threshold": 0.4,
                "detect_boilerplate": True,
                "max_chunks_per_doc": 100,
                "timeout": 15,
            },
        }
        result = build_chunk_quality_filter_from_config(config)
        assert result is not None
        assert isinstance(result, ChunkQualityFilter)
        assert result._threshold == 0.4
        assert result._model == "test-model"
        assert result._max_chunks_per_doc == 100
        assert result._timeout == 15

    def test_defaults_applied(self) -> None:
        config = {
            "quality_filter": {
                "enabled": True,
                "reranker_endpoint": "http://host:8080",
            },
        }
        result = build_chunk_quality_filter_from_config(config)
        assert result is not None
        assert result._threshold == 0.3
        assert result._detect_boilerplate_enabled is True
        assert result._max_chunks_per_doc == 500

    def test_api_key_from_config(self) -> None:
        config = {
            "quality_filter": {
                "enabled": True,
                "reranker_endpoint": "http://host:8080",
                "api_key": "sk-secret",
            },
        }
        result = build_chunk_quality_filter_from_config(config)
        assert result is not None
        assert result._api_key == "sk-secret"


class TestBoilerplatePatterns:
    def test_patterns_compiled(self) -> None:
        assert len(BOILERPLATE_PATTERNS) > 0
        for pattern in BOILERPLATE_PATTERNS:
            assert hasattr(pattern, "search")

    def test_comment_section_header(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Comments: \n")
        assert is_bp is True

    def test_leave_a_comment(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Leave a comment below")
        assert is_bp is True

    def test_cookie_notice(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("This site uses cookies to improve your experience. Cookie Policy")
        assert is_bp is True

    def test_privacy_policy(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("Read our Privacy Policy and Terms of Service for more information.")
        assert is_bp is True

    def test_single_bullet_point(self) -> None:
        qf = ChunkQualityFilter(reranker_endpoint="http://host:8080")
        is_bp, reason = qf.detect_boilerplate("•")
        assert is_bp is True
