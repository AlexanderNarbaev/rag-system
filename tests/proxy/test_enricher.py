"""Tests for self-enrichment pipeline."""

from unittest.mock import MagicMock

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
