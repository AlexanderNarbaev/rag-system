"""Tests for feedback system improvements (FR-13, FR-14, FR-15)."""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── FR-13: Role-restricted feedback submission ──


class TestFeedbackSubmissionRoleRestriction:
    """FR-13: Users can submit simple feedback; corrections are expert-only."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        with patch("proxy.app.core.hitl.get_logger", return_value=MagicMock()), \
             patch("proxy.app.core.feedback_store.get_feedback_store", return_value=MagicMock()), \
             patch("proxy.app.shared.metrics.record_enrichment"), \
             patch("proxy.app.shared.metrics.record_feedback"), \
             patch("proxy.app.core.ragas_eval.evaluate_rag_response", return_value={}):
            yield

    @pytest.fixture
    def user_context_user(self):
        return MagicMock(
            user_id="user-1",
            username="testuser",
            roles=["user"],
            groups=["everyone"],
        )

    @pytest.fixture
    def user_context_expert(self):
        return MagicMock(
            user_id="expert-1",
            username="expertuser",
            roles=["expert"],
            groups=["experts"],
        )

    @pytest.fixture
    def user_context_admin(self):
        return MagicMock(
            user_id="admin-1",
            username="adminuser",
            roles=["admin"],
            groups=["admins"],
        )

    def test_user_can_submit_simple_feedback(self, user_context_user):
        import asyncio

        from proxy.app.api.feedback import FeedbackRequest, submit_feedback

        request = FeedbackRequest(
            feedback_id="fb_test123",
            rating="positive",
            comment="Great answer",
        )

        result = asyncio.run(submit_feedback(request, MagicMock(), user_context_user))
        assert result.status == "ok"

    def test_user_cannot_submit_correction(self, user_context_user):
        import asyncio

        from fastapi import HTTPException

        from proxy.app.api.feedback import FeedbackRequest, submit_feedback

        request = FeedbackRequest(
            feedback_id="fb_test456",
            rating="negative",
            correction="Corrected answer text",
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(submit_feedback(request, MagicMock(), user_context_user))
        assert exc.value.status_code == 403
        assert "Corrections require expert" in exc.value.detail

    def test_expert_can_submit_correction(self, user_context_expert):
        import asyncio

        from proxy.app.api.feedback import FeedbackRequest, submit_feedback

        request = FeedbackRequest(
            feedback_id="fb_test789",
            rating="negative",
            correction="The correct answer is...",
            comment="Wrong answer provided",
        )

        result = asyncio.run(submit_feedback(request, MagicMock(), user_context_expert))
        assert result.status == "ok"

    def test_admin_can_submit_correction(self, user_context_admin):
        import asyncio

        from proxy.app.api.feedback import FeedbackRequest, submit_feedback

        request = FeedbackRequest(
            feedback_id="fb_testadmin",
            rating="negative",
            correction="Admin correction",
        )

        result = asyncio.run(submit_feedback(request, MagicMock(), user_context_admin))
        assert result.status == "ok"


# ── FR-14: Admin feedback review workflow ──


class TestAdminFeedbackEndpoints:
    """FR-14: Admin feedback review endpoints."""

    @pytest.fixture(autouse=True)
    def _patch_store(self):
        with patch("proxy.app.core.feedback_store.get_feedback_store") as mock:
            store = MagicMock()
            mock.return_value = store
            yield store

    def _admin_user(self):
        return MagicMock(user_id="admin-1", username="admin", roles=["admin"])

    def test_list_feedback_with_filters(self):
        import asyncio

        from proxy.app.api.admin_feedback import list_feedback

        result = asyncio.run(list_feedback(
            status="pending",
            kb_id="kb-1",
            date_from="2026-01-01",
            date_to="2026-07-01",
            min_confidence=0.3,
            limit=50,
            offset=0,
            user=self._admin_user(),
        ))

        assert result.total == 0
        assert result.entries == []

    def test_list_feedback_defaults(self):
        import asyncio

        from proxy.app.api.admin_feedback import list_feedback

        result = asyncio.run(list_feedback(user=self._admin_user()))
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_update_feedback_status(self):
        from proxy.app.core.feedback_store import FeedbackEntry, get_feedback_store

        admin_user = self._admin_user()

        store = get_feedback_store()
        entry = FeedbackEntry(feedback_id="fb_1", status="pending")
        store.get.return_value = entry

        from proxy.app.api.admin_feedback import FeedbackUpdateRequest, update_feedback
        body = FeedbackUpdateRequest(status="reviewed", admin_notes="Looks good")

        result = await update_feedback("fb_1", body, admin_user)
        assert result.status_code == 200
        store.update.assert_called_once_with("fb_1", {"status": "reviewed", "admin_notes": "Looks good"})

    @pytest.mark.asyncio
    async def test_update_feedback_not_found(self):
        from fastapi import HTTPException

        from proxy.app.core.feedback_store import get_feedback_store

        admin_user = self._admin_user()
        get_feedback_store().get.return_value = None

        from proxy.app.api.admin_feedback import FeedbackUpdateRequest, update_feedback

        with pytest.raises(HTTPException) as exc:
            await update_feedback("nonexistent", FeedbackUpdateRequest(status="reviewed"), admin_user)
        assert exc.value.status_code == 404

    def test_feedback_stats(self):
        import asyncio

        from proxy.app.api.admin_feedback import feedback_stats
        from proxy.app.core.feedback_store import get_feedback_store

        get_feedback_store().stats.return_value = {
            "total": 100,
            "positive": 70,
            "negative": 30,
            "pos_ratio": 0.7,
            "neg_ratio": 0.3,
            "average_confidence": None,
            "average_retrieval_quality": None,
            "most_corrected_topics": [],
            "feedback_by_user": [],
        }

        result = asyncio.run(feedback_stats(user=self._admin_user()))
        assert result.total == 100
        assert result.positive == 70


# ── FR-15: Retrieval-quality feedback dimension ──


class TestChunkFeedbackDimension:
    """FR-15: Chunk-level feedback and retrieval quality scoring."""

    def test_chunk_feedback_in_request_model(self):
        from proxy.app.api.feedback import ChunkFeedbackItem, FeedbackRequest

        request = FeedbackRequest(
            feedback_id="fb_chunks",
            rating="positive",
            chunk_feedback=[
                ChunkFeedbackItem(chunk_id="chunk_1", relevance_score=5),
                ChunkFeedbackItem(chunk_id="chunk_2", relevance_score=2),
                ChunkFeedbackItem(chunk_id="chunk_3", relevance_score=1),
            ],
            retrieval_quality=3,
        )

        assert request.chunk_feedback is not None
        assert len(request.chunk_feedback) == 3
        assert request.chunk_feedback[0].relevance_score == 5
        assert request.chunk_feedback[2].relevance_score == 1
        assert request.retrieval_quality == 3

    def test_chunk_feedback_rejected_if_score_out_of_range(self):
        from pydantic import ValidationError

        from proxy.app.api.feedback import ChunkFeedbackItem

        with pytest.raises(ValidationError):
            ChunkFeedbackItem(chunk_id="c1", relevance_score=0)

        with pytest.raises(ValidationError):
            ChunkFeedbackItem(chunk_id="c1", relevance_score=6)

    def test_retrieval_quality_out_of_range(self):
        from pydantic import ValidationError

        from proxy.app.api.feedback import FeedbackRequest

        with pytest.raises(ValidationError):
            FeedbackRequest(feedback_id="fb_1", rating="positive", retrieval_quality=0)

        with pytest.raises(ValidationError):
            FeedbackRequest(feedback_id="fb_1", rating="positive", retrieval_quality=6)

    @pytest.fixture
    def _patch_chunk_store(self):
        with patch("proxy.app.core.feedback_store.get_feedback_store") as mock_get_store:
            store = MagicMock()
            store.chunk_stats.return_value = [
                {"chunk_id": "low_chunk", "average_relevance": 1.5, "ratings_count": 4, "low_ratings": 3},
                {"chunk_id": "good_chunk", "average_relevance": 4.8, "ratings_count": 10, "low_ratings": 0},
            ]
            mock_get_store.return_value = store
            yield

    def test_chunk_stats_endpoint(self, _patch_chunk_store):
        import asyncio

        from proxy.app.api.admin_feedback import chunk_stats

        admin_user = MagicMock(user_id="admin-1", username="admin", roles=["admin"])

        result = asyncio.run(chunk_stats(user=admin_user))
        assert len(result) == 2
        assert result[0].chunk_id == "low_chunk"
        assert result[0].average_relevance == 1.5
        assert result[0].low_ratings == 3

    @pytest.fixture
    def _patch_neg_store(self):
        with patch("proxy.app.core.feedback_store.get_feedback_store") as mock_get_store:
            store = MagicMock()
            store.get_negative_training_pairs.return_value = [
                {"query": "How to set up CI?", "chunk_id": "chunk_bad_1", "relevance_score": 1},
                {"query": "What is RAG?", "chunk_id": "chunk_bad_2", "relevance_score": 2},
            ]
            mock_get_store.return_value = store
            yield

    def test_negative_training_pairs_endpoint(self, _patch_neg_store):
        import asyncio

        from proxy.app.api.admin_feedback import negative_training_pairs

        admin_user = MagicMock(user_id="admin-1", username="admin", roles=["admin"])

        result = asyncio.run(negative_training_pairs(user=admin_user))
        assert len(result) == 2
        assert result[0].query == "How to set up CI?"
        assert result[0].relevance_score == 1


# ── FeedbackStore unit tests ──


class TestFeedbackStore:
    """Unit tests for the SQLite FeedbackStore."""

    @pytest.fixture
    def store(self, tmp_path):
        from proxy.app.core.feedback_store import FeedbackStore
        db_path = tmp_path / "test_feedback.db"
        return FeedbackStore(db_path=db_path)

    def test_insert_and_get(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        entry = FeedbackEntry(
            feedback_id="fb_1",
            user_id="u1",
            username="alice",
            role="user",
            rating="positive",
            feedback_type="user_rating",
            comment="Great!",
            question="What is RAG?",
            answer="RAG is...",
            confidence=0.95,
            chunk_feedback_json=json.dumps([{"chunk_id": "c1", "relevance_score": 5}]),
            retrieval_quality=4,
        )
        store.insert(entry)

        retrieved = store.get("fb_1")
        assert retrieved is not None
        assert retrieved.feedback_id == "fb_1"
        assert retrieved.rating == "positive"
        assert retrieved.feedback_type == "user_rating"
        assert retrieved.confidence == 0.95
        assert retrieved.retrieval_quality == 4
        assert len(retrieved.chunk_feedback) == 1
        assert retrieved.chunk_feedback[0]["relevance_score"] == 5

    def test_list_with_filters(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        e1 = FeedbackEntry(feedback_id="fb_a", rating="positive", status="pending", kb_id="kb1", confidence=0.9)
        e2 = FeedbackEntry(feedback_id="fb_b", rating="negative", status="reviewed", kb_id="kb1", confidence=0.3)
        e3 = FeedbackEntry(feedback_id="fb_c", rating="positive", status="pending", kb_id="kb2", confidence=0.8)
        store.insert(e1)
        store.insert(e2)
        store.insert(e3)

        pending = store.list(status="pending")
        assert len(pending) == 2

        kb1 = store.list(kb_id="kb1")
        assert len(kb1) == 2

        low_conf = store.list(min_confidence=0.5)
        assert len(low_conf) == 1
        assert low_conf[0].feedback_id in ("fb_b",)

    def test_update_status(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        entry = FeedbackEntry(feedback_id="fb_u", status="pending")
        store.insert(entry)

        store.update("fb_u", {"status": "accepted", "admin_notes": "Approved"})
        updated = store.get("fb_u")
        assert updated.status == "accepted"
        assert updated.admin_notes == "Approved"

    def test_stats(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        store.insert(FeedbackEntry(feedback_id="fb_s1", rating="positive", confidence=0.9, retrieval_quality=4,
                                   question="Q1", correction="Fixed A1"))
        store.insert(FeedbackEntry(feedback_id="fb_s2", rating="negative", confidence=0.5, retrieval_quality=2,
                                   question="Q1", correction="Fixed A1b"))
        store.insert(FeedbackEntry(feedback_id="fb_s3", rating="positive", confidence=0.8, retrieval_quality=5,
                                   question="Q2"))
        store.insert(FeedbackEntry(feedback_id="fb_s4", rating="negative", confidence=0.2, retrieval_quality=1))

        stats = store.stats()
        assert stats["total"] == 4
        assert stats["positive"] == 2
        assert stats["negative"] == 2
        assert stats["pos_ratio"] == 0.5
        assert stats["average_confidence"] is not None
        assert stats["average_retrieval_quality"] is not None
        assert len(stats["most_corrected_topics"]) == 1
        assert stats["most_corrected_topics"][0]["question"].startswith("Q1")

    def test_chunk_stats(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        store.insert(FeedbackEntry(
            feedback_id="fb_cs1",
            rating="negative",
            chunk_feedback_json=json.dumps([
                {"chunk_id": "c1", "relevance_score": 1},
                {"chunk_id": "c2", "relevance_score": 5},
            ]),
        ))
        store.insert(FeedbackEntry(
            feedback_id="fb_cs2",
            rating="negative",
            chunk_feedback_json=json.dumps([
                {"chunk_id": "c1", "relevance_score": 2},
                {"chunk_id": "c3", "relevance_score": 3},
            ]),
        ))

        results = store.chunk_stats()
        c1 = next(r for r in results if r["chunk_id"] == "c1")
        assert c1["average_relevance"] == 1.5
        assert c1["low_ratings"] == 2

    def test_negative_training_pairs(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        store.insert(FeedbackEntry(
            feedback_id="fb_np1",
            question="How to set up CI/CD?",
            chunk_feedback_json=json.dumps([
                {"chunk_id": "bad_chunk", "relevance_score": 1},
                {"chunk_id": "good_chunk", "relevance_score": 5},
            ]),
        ))
        store.insert(FeedbackEntry(
            feedback_id="fb_np2",
            question="What is RAG?",
            chunk_feedback_json=json.dumps([
                {"chunk_id": "mediocre_chunk", "relevance_score": 2},
            ]),
        ))

        pairs = store.get_negative_training_pairs()
        assert len(pairs) == 2
        chunk_ids = {p["chunk_id"] for p in pairs}
        assert "bad_chunk" in chunk_ids
        assert "mediocre_chunk" in chunk_ids
        assert "good_chunk" not in chunk_ids

    def test_feedback_entry_to_dict(self, store):
        from proxy.app.core.feedback_store import FeedbackEntry

        entry = FeedbackEntry(
            feedback_id="fb_dict",
            user_id="u1",
            username="alice",
            role="user",
            rating="positive",
            feedback_type="user_rating",
            contexts_json=json.dumps(["ctx1", "ctx2"]),
            chunk_feedback_json=json.dumps([{"chunk_id": "c1", "relevance_score": 4}]),
        )
        d = entry.to_dict()
        assert d["feedback_id"] == "fb_dict"
        assert d["contexts"] == ["ctx1", "ctx2"]
        assert d["chunk_feedback"] == [{"chunk_id": "c1", "relevance_score": 4}]
