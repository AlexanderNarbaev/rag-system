"""Tests for self-enrichment pipeline."""

import json
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.enricher import chunk_qa_pair, extract_qa_pair


def test_extract_qa_pair_positive():
    feedback = MagicMock()
    feedback.feedback_id = "fb_test"
    feedback.rating = "positive"
    feedback.correction = None
    feedback.comment = ""

    interaction = {
        "query": "What is Docker?",
        "response": "Docker is a containerization platform.",
        "context": "Docker enables containerization.",
    }

    qa = extract_qa_pair(feedback, interaction)
    assert qa is not None
    assert "Docker" in qa["question"]
    assert "containerization" in qa["answer"]
    assert qa["rating"] == "positive"


def test_extract_qa_pair_with_correction():
    feedback = MagicMock()
    feedback.feedback_id = "fb_test2"
    feedback.rating = "negative"
    feedback.correction = "Docker is a platform for developing, shipping, and running applications in containers."
    feedback.comment = ""

    interaction = {
        "query": "What is Docker?",
        "response": "Docker is a tool.",
        "context": "",
    }

    qa = extract_qa_pair(feedback, interaction)
    assert qa is not None
    assert qa["answer"] == feedback.correction


def test_extract_qa_pair_empty_returns_none():
    feedback = MagicMock()
    feedback.correction = None

    interaction = {"query": "", "response": ""}
    qa = extract_qa_pair(feedback, interaction)
    assert qa is None


def test_chunk_qa_pair():
    qa = {
        "question": "What is Docker?",
        "answer": "Docker is a containerization platform.",
        "feedback_id": "fb1",
        "rating": "positive",
        "context": "",
    }
    chunk = chunk_qa_pair(qa)
    assert chunk is not None
    assert "What is Docker?" in chunk["text"]
    assert chunk["metadata"]["source"] == "user_feedback"
    assert chunk["metadata"]["rating"] == "positive"
    assert len(chunk["id"]) == 64  # SHA-256 hex


def test_chunk_qa_pair_idempotent():
    qa = {"question": "Q", "answer": "A", "feedback_id": "fb1", "rating": "positive", "context": ""}
    chunk1 = chunk_qa_pair(qa)
    chunk2 = chunk_qa_pair(qa)
    assert chunk1["id"] == chunk2["id"]


# --- Tests for enrich_from_feedback ---


@pytest.mark.asyncio
@patch("proxy.app.core.enricher._index_chunk")
@patch("proxy.app.core.enricher._find_interaction")
async def test_enrich_from_feedback_success(mock_find, mock_index):
    from proxy.app.core.enricher import enrich_from_feedback

    feedback = MagicMock()
    feedback.feedback_id = "fb_123"
    feedback.correction = None
    feedback.rating = "positive"

    mock_find.return_value = {"query": "What is X?", "response": "X is Y.", "context": ""}
    mock_index.return_value = True

    result = await enrich_from_feedback(feedback)
    assert result is True
    mock_index.assert_called_once()


@pytest.mark.asyncio
@patch("proxy.app.core.enricher._find_interaction")
async def test_enrich_from_feedback_no_interaction(mock_find):
    from proxy.app.core.enricher import enrich_from_feedback

    feedback = MagicMock()
    feedback.feedback_id = "fb_missing"
    mock_find.return_value = None

    result = await enrich_from_feedback(feedback)
    assert result is False


@pytest.mark.asyncio
@patch("proxy.app.core.enricher._index_chunk")
@patch("proxy.app.core.enricher._find_interaction")
async def test_enrich_from_feedback_empty_qa(mock_find, mock_index):
    from proxy.app.core.enricher import enrich_from_feedback

    feedback = MagicMock()
    feedback.feedback_id = "fb_empty"
    feedback.correction = None
    feedback.rating = "positive"

    mock_find.return_value = {"query": "", "response": ""}

    result = await enrich_from_feedback(feedback)
    assert result is False
    mock_index.assert_not_called()


@pytest.mark.asyncio
@patch("proxy.app.core.enricher._index_chunk")
@patch("proxy.app.core.enricher._find_interaction")
async def test_enrich_from_feedback_index_failure(mock_find, mock_index):
    from proxy.app.core.enricher import enrich_from_feedback

    feedback = MagicMock()
    feedback.feedback_id = "fb_fail"
    feedback.correction = None
    feedback.rating = "negative"

    mock_find.return_value = {"query": "Q", "response": "A", "context": ""}
    mock_index.return_value = False

    result = await enrich_from_feedback(feedback)
    assert result is False


# --- Tests for _index_chunk ---


@pytest.mark.asyncio
async def test_index_chunk_success():
    """Test _index_chunk with properly isolated mocks."""
    import sys

    from proxy.app.core.enricher import _index_chunk

    mock_model = MagicMock()
    mock_model.encode.return_value.tolist.return_value = [0.1, 0.2, 0.3]

    mock_client = MagicMock()
    mock_point_cls = MagicMock()

    # Save and restore sys.modules to avoid polluting other tests
    saved_qc = sys.modules.get("qdrant_client")
    saved_qc_models = sys.modules.get("qdrant_client.models")
    try:
        # Create a proper mock package structure
        mock_qc = MagicMock()
        mock_qc.QdrantClient.return_value = mock_client
        mock_qc.models.PointStruct = mock_point_cls
        sys.modules["qdrant_client"] = mock_qc
        sys.modules["qdrant_client.models"] = mock_qc.models

        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_model):
            chunk = {
                "id": "abc123",
                "text": "Q: What?\nA: That.",
                "metadata": {"source": "user_feedback", "feedback_id": "fb1", "rating": "positive"},
            }
            result = await _index_chunk(chunk)
            assert result is True
            mock_client.upsert.assert_called_once()
    finally:
        if saved_qc is not None:
            sys.modules["qdrant_client"] = saved_qc
        else:
            sys.modules.pop("qdrant_client", None)
        if saved_qc_models is not None:
            sys.modules["qdrant_client.models"] = saved_qc_models
        else:
            sys.modules.pop("qdrant_client.models", None)


@pytest.mark.asyncio
async def test_index_chunk_failure():
    """Test _index_chunk failure path."""
    from proxy.app.core.enricher import _index_chunk

    with patch("proxy.app.llm.remote_services.create_embedder", side_effect=RuntimeError("Embedder down")):
        chunk = {
            "id": "abc123",
            "text": "Q: What?\nA: That.",
            "metadata": {"source": "user_feedback", "feedback_id": "fb1", "rating": "positive"},
        }
        result = await _index_chunk(chunk)
        assert result is False


# --- Tests for _find_interaction ---


@patch("proxy.app.core.enricher.Path")
def test_find_interaction_not_found(mock_path_cls):
    from proxy.app.core.enricher import _find_interaction

    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_path_cls.return_value = mock_path

    result = _find_interaction("fb_nonexistent")
    assert result is None


@patch("proxy.app.core.enricher.Path")
def test_find_interaction_found_by_feedback_id(mock_path_cls):
    from proxy.app.core.enricher import _find_interaction

    log_content = json.dumps({"feedback_id": "fb_target", "query": "Q", "response": "A"}) + "\n"

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = log_content
    mock_path_cls.return_value = mock_path

    result = _find_interaction("fb_target")
    assert result is not None
    assert result["feedback_id"] == "fb_target"


@patch("proxy.app.core.enricher.Path")
def test_find_interaction_found_by_request_id(mock_path_cls):
    from proxy.app.core.enricher import _find_interaction

    log_content = json.dumps({"request_id": "req_abc", "query": "Q", "response": "A"}) + "\n"

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = log_content
    mock_path_cls.return_value = mock_path

    result = _find_interaction("req_abc")
    assert result is not None
    assert result["request_id"] == "req_abc"


@patch("proxy.app.core.enricher.Path")
def test_find_interaction_skips_blank_lines(mock_path_cls):
    from proxy.app.core.enricher import _find_interaction

    log_content = "\n\n" + json.dumps({"feedback_id": "fb_target", "query": "Q", "response": "A"}) + "\n\n"

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = log_content
    mock_path_cls.return_value = mock_path

    result = _find_interaction("fb_target")
    assert result is not None


@patch("proxy.app.core.enricher.Path")
def test_find_interaction_handles_parse_error(mock_path_cls):
    from proxy.app.core.enricher import _find_interaction

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "not-json\n"
    mock_path_cls.return_value = mock_path

    result = _find_interaction("fb_any")
    assert result is None
