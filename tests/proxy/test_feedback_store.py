"""Tests for feedback_store module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.feedback_store import (
    FeedbackEntry,
    FeedbackStore,
    get_feedback_store,
)


class TestFeedbackEntry:
    def test_creation_with_kwargs(self):
        entry = FeedbackEntry(
            id="fb-1",
            feedback_id="fid-1",
            user_id="user-1",
            username="testuser",
            role="user",
            rating="positive",
            feedback_type="simple",
            comment="great",
        )
        assert entry.id == "fb-1"
        assert entry.feedback_id == "fid-1"
        assert entry.user_id == "user-1"
        assert entry.username == "testuser"
        assert entry.role == "user"
        assert entry.rating == "positive"
        assert entry.feedback_type == "simple"
        assert entry.comment == "great"

    def test_default_values(self):
        entry = FeedbackEntry()
        assert entry.id == ""
        assert entry.status == "pending"
        assert entry.created_at == ""

    def test_contexts_property_empty(self):
        entry = FeedbackEntry()
        assert entry.contexts == []

    def test_contexts_property_with_json(self):
        entry = FeedbackEntry(contexts_json=json.dumps(["ctx1", "ctx2"]))
        assert entry.contexts == ["ctx1", "ctx2"]

    def test_chunk_feedback_property_empty(self):
        entry = FeedbackEntry()
        assert entry.chunk_feedback == []

    def test_chunk_feedback_property_with_json(self):
        data = [{"chunk_id": "c1", "relevance_score": 4}]
        entry = FeedbackEntry(chunk_feedback_json=json.dumps(data))
        assert entry.chunk_feedback == data

    def test_to_dict(self):
        entry = FeedbackEntry(
            id="fb-1",
            feedback_id="fid-1",
            user_id="user-1",
            username="u",
            role="user",
            rating="positive",
            contexts_json=json.dumps(["c1"]),
            chunk_feedback_json=json.dumps([{"chunk_id": "c1"}]),
        )
        d = entry.to_dict()
        assert d["id"] == "fb-1"
        assert d["contexts"] == ["c1"]
        assert d["chunk_feedback"] == [{"chunk_id": "c1"}]
        assert d["status"] == "pending"


class TestFeedbackStore:
    @pytest.fixture(autouse=True)
    def _setup_store(self, tmp_path):
        db_path = tmp_path / "test_feedback.db"
        self.store = FeedbackStore(db_path=db_path)

    def test_insert_and_get(self):
        entry = FeedbackEntry(feedback_id="fid-1", user_id="u1", rating="positive")
        self.store.insert(entry)

        assert entry.id == "fid-1"
        assert entry.created_at != ""
        assert entry.updated_at != ""

        fetched = self.store.get("fid-1")
        assert fetched is not None
        assert fetched.feedback_id == "fid-1"
        assert fetched.rating == "positive"

    def test_insert_preserves_existing_id(self):
        self.store.insert(FeedbackEntry(id="custom-id", feedback_id="fid-2"))
        fetched = self.store.get("fid-2")
        assert fetched.id == "custom-id"

    def test_get_nonexistent(self):
        assert self.store.get("nonexistent") is None

    def test_update_existing(self):
        self.store.insert(FeedbackEntry(feedback_id="fid-upd", rating="negative"))
        result = self.store.update("fid-upd", {"status": "reviewed"})
        assert result is True

        fetched = self.store.get("fid-upd")
        assert fetched.status == "reviewed"

    def test_update_nonexistent(self):
        result = self.store.update("no-such-id", {"status": "reviewed"})
        assert result is False

    def test_list_entries_no_filters(self):
        self.store.insert(FeedbackEntry(feedback_id="a1", user_id="u1"))
        self.store.insert(FeedbackEntry(feedback_id="a2", user_id="u2"))

        entries, total = self.store.list_entries()
        assert total == 2
        assert len(entries) == 2

    def test_list_entries_with_status_filter(self):
        self.store.insert(FeedbackEntry(feedback_id="b1", rating="positive"))
        self.store.insert(FeedbackEntry(feedback_id="b2", rating="negative"))

        self.store.update("b2", {"status": "approved"})
        entries, total = self.store.list_entries(status="approved")
        assert total == 1
        assert entries[0].feedback_id == "b2"

    def test_list_entries_with_kb_filter(self):
        self.store.insert(FeedbackEntry(feedback_id="c1", kb_id="kb-a"))
        self.store.insert(FeedbackEntry(feedback_id="c2", kb_id="kb-b"))

        entries, total = self.store.list_entries(kb_id="kb-a")
        assert total == 1
        assert entries[0].feedback_id == "c1"

    def test_list_entries_with_limit_and_offset(self):
        for i in range(5):
            self.store.insert(FeedbackEntry(feedback_id=f"d{i}", user_id="u"))

        entries, total = self.store.list_entries(limit=2, offset=2)
        assert total == 5
        assert len(entries) == 2

    def test_list_entries_with_confidence_filter(self):
        self.store.insert(FeedbackEntry(feedback_id="e1", confidence=0.3))
        self.store.insert(FeedbackEntry(feedback_id="e2", confidence=0.9))

        entries, total = self.store.list_entries(max_confidence=0.5)
        assert total == 1
        assert entries[0].feedback_id == "e1"

    def test_stats_empty(self):
        result = self.store.stats()
        assert result["total"] == 0
        assert result["positive"] == 0
        assert result["negative"] == 0
        assert result["pos_ratio"] == 0
        assert result["neg_ratio"] == 0
        assert result["average_confidence"] is None

    def test_stats_with_data(self):
        self.store.insert(FeedbackEntry(feedback_id="s1", rating="positive", confidence=0.9))
        self.store.insert(FeedbackEntry(feedback_id="s2", rating="positive", confidence=0.8))
        self.store.insert(FeedbackEntry(feedback_id="s3", rating="negative", confidence=0.4))

        result = self.store.stats()
        assert result["total"] == 3
        assert result["positive"] == 2
        assert result["negative"] == 1
        assert result["pos_ratio"] == pytest.approx(0.6667, abs=0.01)
        assert result["neg_ratio"] == pytest.approx(0.3333, abs=0.01)
        assert result["average_confidence"] is not None

    def test_stats_with_corrections(self):
        self.store.insert(
            FeedbackEntry(
                feedback_id="cor1",
                rating="negative",
                question="How to X?",
                correction="Use Y instead.",
            )
        )

        result = self.store.stats()
        assert result["total"] == 1
        assert len(result["most_corrected_topics"]) >= 1

    def test_chunk_stats_empty(self):
        result = self.store.chunk_stats()
        assert result == []

    def test_chunk_stats_with_data(self):
        cf_json = json.dumps([{"chunk_id": "chunk-a", "relevance_score": 3}])
        self.store.insert(
            FeedbackEntry(
                feedback_id="cs1",
                chunk_feedback_json=cf_json,
                retrieval_quality=3,
            )
        )
        cf_json2 = json.dumps([{"chunk_id": "chunk-a", "relevance_score": 5}])
        self.store.insert(
            FeedbackEntry(
                feedback_id="cs2",
                chunk_feedback_json=cf_json2,
                retrieval_quality=5,
            )
        )

        result = self.store.chunk_stats()
        assert len(result) == 1
        assert result[0]["chunk_id"] == "chunk-a"
        assert result[0]["ratings_count"] == 2
        assert result[0]["average_relevance"] == 4.0

    def test_chunk_stats_respects_min_count(self):
        cf_json = json.dumps([{"chunk_id": "chunk-b", "relevance_score": 3}])
        self.store.insert(FeedbackEntry(feedback_id="cs3", chunk_feedback_json=cf_json))

        result = self.store.chunk_stats(min_count=2)
        assert result == []

    def test_get_negative_training_pairs_empty(self):
        assert self.store.get_negative_training_pairs() == []

    def test_get_negative_training_pairs_filters_low_scores(self):
        cf_json = json.dumps(
            [
                {"chunk_id": "bad-chunk", "relevance_score": 1},
                {"chunk_id": "good-chunk", "relevance_score": 4},
            ]
        )
        self.store.insert(
            FeedbackEntry(
                feedback_id="nt1",
                question="What is X?",
                chunk_feedback_json=cf_json,
            )
        )

        result = self.store.get_negative_training_pairs()
        assert len(result) == 1
        assert result[0]["chunk_id"] == "bad-chunk"
        assert result[0]["relevance_score"] == 1
        assert result[0]["query"] == "What is X?"


class TestGetFeedbackStore:
    def setup_method(self):
        import proxy.app.core.feedback_store as fbs

        fbs._store = None

    def test_creates_singleton(self):
        with patch("proxy.app.core.feedback_store.FeedbackStore") as mock_store_cls:
            mock_instance = MagicMock()
            mock_store_cls.return_value = mock_instance

            store1 = get_feedback_store()
            store2 = get_feedback_store()

            assert store1 is store2
            assert mock_store_cls.call_count == 1
