"""Tests for etl/indexer/chunk_enricher.py."""

import json
from unittest.mock import MagicMock, patch

from etl.indexer.chunk_enricher import (
    ChunkEnricher,
    build_chunk_enricher_from_config,
)


class TestChunkEnricherInit:
    def test_default_construction(self):
        enricher = ChunkEnricher()
        assert enricher._model == "qwen2.5-3b"
        assert enricher._max_concurrent == 5
        assert enricher._fallback_to_heuristic is True
        assert enricher.is_enabled is False  # no endpoint

    def test_with_endpoint(self):
        enricher = ChunkEnricher(slm_endpoint="http://localhost:8080/v1")
        assert enricher.is_enabled is True
        assert "http://localhost:8080/v1" in enricher._endpoint

    def test_with_api_key(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            api_key="sk-test",
        )
        assert enricher._headers.get("Authorization") == "Bearer sk-test"

    def test_without_api_key(self):
        enricher = ChunkEnricher(slm_endpoint="http://localhost:8080/v1")
        assert "Authorization" not in enricher._headers

    def test_fallback_disabled(self):
        enricher = ChunkEnricher(fallback_to_heuristic=False)
        assert enricher._fallback_to_heuristic is False

    def test_with_timeout(self):
        enricher = ChunkEnricher(timeout=15)
        assert enricher._timeout == 15

    def test_endpoint_normalized(self):
        enricher = ChunkEnricher(slm_endpoint="http://host:8080/v1/")
        assert enricher._endpoint == "http://host:8080/v1"


class TestChunkEnricherEmptyInput:
    def test_empty_text(self):
        enricher = ChunkEnricher()
        result = enricher.enrich("")
        assert result == {"keywords": [], "entities": [], "hyde_questions": [], "summary": ""}

    def test_whitespace_text(self):
        enricher = ChunkEnricher()
        result = enricher.enrich("   ")
        assert result == {"keywords": [], "entities": [], "hyde_questions": [], "summary": ""}

    def test_none_metadata(self):
        enricher = ChunkEnricher()
        result = enricher.enrich("some text", None)
        assert "keywords" in result
        assert "entities" in result
        assert "hyde_questions" in result
        assert "summary" in result


class TestHeuristicKeywords:
    def test_extracts_keywords(self):
        keywords = ChunkEnricher._heuristic_keywords(
            "Retrieval augmented generation system processes technical documents for search"
        )
        assert len(keywords) > 0
        assert "retrieval" in keywords or "augmented" in keywords or "generation" in keywords

    def test_russian_keywords(self):
        keywords = ChunkEnricher._heuristic_keywords(
            "Система гибридного поиска использует dense и sparse эмбеддеры для поиска документов"
        )
        assert len(keywords) > 0
        assert any(w in keywords for w in ["гибридного", "поиска", "эмбеддеры", "документов"])

    def test_filters_short_words(self):
        keywords = ChunkEnricher._heuristic_keywords("a b c the and or is")
        assert keywords == []

    def test_empty_text(self):
        assert ChunkEnricher._heuristic_keywords("") == []

    def test_returns_capped_list(self):
        keywords = ChunkEnricher._heuristic_keywords(" ".join([f"term{i}" for i in range(20)]))
        assert len(keywords) <= 8


class TestHeuristicEntities:
    def test_extracts_entities_regex(self):
        enricher = ChunkEnricher()
        enricher._nlp = None
        entities = enricher._heuristic_entities(
            "Qdrant is a vector database. BAAI/bge-m3 is used for embeddings. Version 1.2.3 released."
        )
        assert len(entities) > 0

    def test_spacy_entities(self):
        enricher = ChunkEnricher()
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent1 = MagicMock()
        mock_ent1.text = "John"
        mock_ent1.label_ = "PERSON"
        mock_ent2 = MagicMock()
        mock_ent2.text = "Acme Corp"
        mock_ent2.label_ = "ORG"
        mock_ent3 = MagicMock()
        mock_ent3.text = "Kubernetes"
        mock_ent3.label_ = "PRODUCT"
        mock_doc.ents = [mock_ent1, mock_ent2, mock_ent3]
        mock_nlp.return_value = mock_doc
        enricher._nlp = mock_nlp
        entities = enricher._heuristic_entities("John works at Acme Corp using Kubernetes 1.2.3")
        assert len(entities) >= 2

    def test_empty_text(self):
        enricher = ChunkEnricher()
        enricher._nlp = None
        assert enricher._heuristic_entities("") == []


class TestHeuristicHydeQuestions:
    def test_extracts_questions_from_text(self):
        questions = ChunkEnricher._heuristic_hyde_questions(
            "Как настроить RAG систему? Почему мы используем Qdrant? Что такое гибридный поиск?"
        )
        assert len(questions) >= 2

    def test_english_questions(self):
        questions = ChunkEnricher._heuristic_hyde_questions(
            "How does RAG work? What is a vector database? Why use hybrid search?"
        )
        assert len(questions) >= 2

    def test_template_fallback(self):
        questions = ChunkEnricher._heuristic_hyde_questions(
            "This is plain text without questions.",
            {"doc_title": "RAG Overview", "source_type": "confluence"},
        )
        assert len(questions) >= 1
        assert any("RAG Overview" in q for q in questions)

    def test_jira_template(self):
        questions = ChunkEnricher._heuristic_hyde_questions(
            "Bug report text.",
            {"doc_title": "Fix login", "source_type": "jira"},
        )
        assert len(questions) >= 1

    def test_capped_at_three(self):
        questions = ChunkEnricher._heuristic_hyde_questions(
            "Как сделать A? Почему B? Что такое C? Где найти D? Когда менять E?"
        )
        assert len(questions) <= 3


class TestHeuristicSummary:
    def test_short_text(self):
        summary = ChunkEnricher._heuristic_summary("Short text.")
        assert summary == "Short text."

    def test_long_text(self):
        summary = ChunkEnricher._heuristic_summary("First sentence. Second sentence. Third sentence. Fourth sentence.")
        assert len(summary) <= 150
        assert "First sentence." in summary

    def test_empty_text(self):
        assert ChunkEnricher._heuristic_summary("") == ""

    def test_strips_context_prefix(self):
        summary = ChunkEnricher._heuristic_summary(
            "[Document: My Doc | Section: Overview]\n\nActual content starts here."
        )
        assert summary.startswith("Actual content")

    def test_strips_heading_markers(self):
        summary = ChunkEnricher._heuristic_summary("## Section Title\n\nThe actual content of the section.")
        assert summary.startswith("Section Title") or summary.startswith("The actual")


class TestSLMEnrichment:
    def test_slm_successful_call(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        slm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "keywords": ["RAG", "retrieval", "embedding"],
                                "entities": ["Qdrant", "Transformer"],
                                "hyde_questions": ["Как работает RAG?", "Что такое Qdrant?"],
                                "summary": "Обзор компонентов RAG системы.",
                            }
                        )
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = slm_response
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = enricher.enrich(
                "RAG combines retrieval with generation using Qdrant",
                {"doc_title": "RAG Overview"},
            )

        assert "RAG" in result["keywords"]
        assert "Qdrant" in result["entities"]
        assert len(result["hyde_questions"]) >= 1
        assert len(result["summary"]) > 0

    def test_slm_codeblock_response(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        slm_response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '```json\n{"keywords": ["test"], "entities": [], '
                            '"hyde_questions": ["What is this?"], "summary": "A test."}\n```'
                        ),
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = slm_response
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = enricher.enrich("test text")

        assert result["keywords"] == ["test"]
        assert result["summary"] == "A test."

    def test_slm_http_error_falls_back(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = Exception("Server error")

        with patch("requests.post", return_value=mock_resp):
            result = enricher.enrich(
                "RAG system uses Qdrant and bge-m3 for hybrid search",
                {"doc_title": "RAG System"},
            )

        assert "keywords" in result
        assert "hyde_questions" in result
        assert "summary" in result

    def test_slm_network_error_falls_back(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        with patch("requests.post", side_effect=ConnectionError("unreachable")):
            result = enricher.enrich("test text", {"doc_title": "Test"})

        assert "keywords" in result
        assert "entities" in result
        assert "hyde_questions" in result
        assert "summary" in result

    def test_slm_invalid_json_response(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        slm_response = {"choices": [{"message": {"content": "not valid json at all"}}]}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = slm_response
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = enricher.enrich("test text", {"doc_title": "Test"})

        assert "keywords" in result

    def test_slm_empty_response(self):
        enricher = ChunkEnricher(
            slm_endpoint="http://localhost:8080/v1",
            model="qwen2.5-3b",
        )
        slm_response = {"choices": [{"message": {"content": ""}}]}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = slm_response
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = enricher.enrich("test text", {"doc_title": "Test"})

        assert "keywords" in result


class TestEnrichDisabled:
    def test_no_endpoint_heuristic_only(self):
        enricher = ChunkEnricher()
        result = enricher.enrich(
            "RAG system with Qdrant and bge-m3",
            {"doc_title": "Test"},
        )
        assert isinstance(result["keywords"], list)
        assert isinstance(result["entities"], list)
        assert isinstance(result["hyde_questions"], list)
        assert isinstance(result["summary"], str)

    def test_no_fallback_returns_empty(self):
        enricher = ChunkEnricher(fallback_to_heuristic=False)
        result = enricher.enrich("some text")
        assert result == {"keywords": [], "entities": [], "hyde_questions": [], "summary": ""}


class TestValidateResult:
    def test_fills_gaps_with_heuristic(self):
        enricher = ChunkEnricher()
        partial = {"keywords": [], "entities": [], "hyde_questions": [], "summary": ""}
        result = enricher._validate_result(partial, "RAG system with Qdrant", {"doc_title": "Test"})
        assert len(result["keywords"]) > 0
        assert len(result["hyde_questions"]) > 0
        assert len(result["summary"]) > 0

    def test_preserves_valid_fields(self):
        enricher = ChunkEnricher()
        result = enricher._validate_result(
            {
                "keywords": ["RAG", "Qdrant"],
                "entities": ["Acme Corp"],
                "hyde_questions": ["What is RAG?"],
                "summary": "A test summary.",
            },
            "backup text",
            {},
        )
        assert result["keywords"] == ["RAG", "Qdrant"]
        assert result["entities"] == ["Acme Corp"]
        assert result["hyde_questions"] == ["What is RAG?"]
        assert result["summary"] == "A test summary."

    def test_filters_invalid_entries(self):
        enricher = ChunkEnricher()
        result = enricher._validate_result(
            {
                "keywords": ["ok", "", "x"],
                "entities": [None, 123, "Valid"],
                "hyde_questions": ["short", "Valid question?"],
                "summary": "",
            },
            "backup",
            {},
        )
        assert len(result["keywords"]) == 1
        assert result["keywords"] == ["ok"]
        assert len(result["entities"]) == 1
        assert result["entities"] == ["Valid"]
        assert len(result["hyde_questions"]) == 1


class TestBuildEnricherFromConfig:
    def test_disabled_returns_none(self):
        config = {"enrichment": {"enabled": False}}
        assert build_chunk_enricher_from_config(config) is None

    def test_no_section_returns_none(self):
        assert build_chunk_enricher_from_config({}) is None

    def test_enabled_with_endpoint(self):
        config = {
            "enrichment": {
                "enabled": True,
                "slm_endpoint": "http://host/v1",
                "slm_model": "qwen2.5-3b",
                "max_concurrent": 3,
                "fallback_to_heuristic": True,
                "timeout": 60,
            }
        }
        enricher = build_chunk_enricher_from_config(config)
        assert enricher is not None
        assert enricher.is_enabled is True
        assert enricher._model == "qwen2.5-3b"
        assert enricher._max_concurrent == 3
        assert enricher._timeout == 60

    def test_enabled_no_endpoint_with_fallback(self):
        config = {
            "enrichment": {
                "enabled": True,
                "slm_endpoint": "",
                "fallback_to_heuristic": True,
            }
        }
        enricher = build_chunk_enricher_from_config(config)
        assert enricher is not None
        assert enricher.is_enabled is False

    def test_enabled_no_endpoint_no_fallback(self):
        config = {
            "enrichment": {
                "enabled": True,
                "slm_endpoint": "",
                "fallback_to_heuristic": False,
            }
        }
        assert build_chunk_enricher_from_config(config) is None


class TestChunkEnricherBatch:
    def test_enrich_chunks_sync(self):
        enricher = ChunkEnricher()
        chunks = [
            {"text": "First chunk about RAG.", "metadata": {"doc_title": "Doc 1"}},
            {"text": "Second chunk about Qdrant.", "metadata": {"doc_title": "Doc 2"}},
        ]
        results = enricher.enrich_chunks_sync(chunks)
        assert len(results) == 2
        for r in results:
            assert "keywords" in r
            assert "entities" in r
            assert "hyde_questions" in r
            assert "summary" in r
