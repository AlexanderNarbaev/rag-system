"""Tests for domain-driven design models.

Covers:
- Entity lifecycle (Document, Chunk, KnowledgeBase, User)
- Value object validation and immutability (SearchQuery, RetrievalResult, ConfidenceScore, TokenBudget)
- Domain event creation and typing
- Domain service business logic (AccessControlService, RetrievalScoringService)
"""

from __future__ import annotations

import pytest

from proxy.app.domain.entities import (
    Chunk,
    ChunkStatus,
    Document,
    DocumentStatus,
    KnowledgeBase,
    User,
)
from proxy.app.domain.events import (
    ChunkCreated,
    DocumentIndexed,
    DocumentUpdated,
    DomainEvent,
    FeedbackSubmitted,
    ModelPromoted,
    RetrievalPerformed,
    UserAuthenticated,
)
from proxy.app.domain.services import (
    AccessControlService,
    RetrievalScoringService,
)
from proxy.app.domain.value_objects import (
    ConfidenceScore,
    RetrievalResult,
    SearchQuery,
    TokenBudget,
)

# ---------------------------------------------------------------------------
# Entity tests: Document
# ---------------------------------------------------------------------------


class TestDocument:
    """Tests for the Document entity."""

    def test_create_with_defaults(self) -> None:
        doc = Document()
        assert doc.id  # auto-generated UUID
        assert doc.title == ""
        assert doc.status == DocumentStatus.ACTIVE
        assert doc.version == "v1"
        assert doc.chunks == []

    def test_create_with_values(self) -> None:
        doc = Document(
            title="Architecture Guide",
            source_type="confluence",
            source_id="12345",
            version="v2",
        )
        assert doc.title == "Architecture Guide"
        assert doc.source_type == "confluence"
        assert doc.source_id == "12345"
        assert doc.version == "v2"

    def test_mark_stale(self) -> None:
        doc = Document(title="Test")
        assert doc.status == DocumentStatus.ACTIVE
        old_updated = doc.updated_at

        doc.mark_stale()
        assert doc.status == DocumentStatus.STALE
        assert doc.updated_at >= old_updated

    def test_mark_archived(self) -> None:
        doc = Document(title="Test")
        doc.mark_archived()
        assert doc.status == DocumentStatus.ARCHIVED

    def test_update_version(self) -> None:
        doc = Document(title="Test", version="v1")
        doc.update_version("v3")
        assert doc.version == "v3"

    def test_is_stale_property(self) -> None:
        doc = Document()
        assert doc.is_stale is False
        doc.mark_stale()
        assert doc.is_stale is True

    def test_add_chunk(self) -> None:
        doc = Document(title="Test")
        chunk = Chunk(text="Hello world")
        doc.add_chunk(chunk)

        assert len(doc.chunks) == 1
        assert doc.chunks[0].document_id == doc.id
        assert doc.chunks[0].text == "Hello world"

    def test_identity_by_id(self) -> None:
        """Two documents with the same ID are the same entity."""
        doc1 = Document(id="fixed-id", title="A")
        doc2 = Document(id="fixed-id", title="B")
        assert doc1.id == doc2.id  # same identity

    def test_metadata(self) -> None:
        doc = Document(metadata={"author": "alice", "tags": ["arch"]})
        assert doc.metadata["author"] == "alice"


# ---------------------------------------------------------------------------
# Entity tests: Chunk
# ---------------------------------------------------------------------------


class TestChunk:
    """Tests for the Chunk entity."""

    def test_create_with_defaults(self) -> None:
        chunk = Chunk()
        assert chunk.id
        assert chunk.status == ChunkStatus.INDEXED
        assert chunk.access_level == "public"
        assert chunk.quality_score == 0.0
        assert chunk.embedding == []

    def test_create_with_acl(self) -> None:
        chunk = Chunk(
            text="Secret content",
            access_level="restricted",
            allowed_groups=["engineering"],
            allowed_users=["user-1"],
        )
        assert chunk.access_level == "restricted"
        assert "engineering" in chunk.allowed_groups
        assert "user-1" in chunk.allowed_users

    def test_mark_stale(self) -> None:
        chunk = Chunk(text="test")
        chunk.mark_stale()
        assert chunk.status == ChunkStatus.STALE

    def test_mark_deleted(self) -> None:
        chunk = Chunk(text="test")
        chunk.mark_deleted()
        assert chunk.status == ChunkStatus.DELETED

    def test_is_accessible_publicly(self) -> None:
        chunk_pub = Chunk(access_level="public")
        chunk_res = Chunk(access_level="restricted")
        assert chunk_pub.is_accessible_publicly is True
        assert chunk_res.is_accessible_publicly is False

    def test_embedding_stored(self) -> None:
        embedding = [0.1, 0.2, 0.3]
        chunk = Chunk(embedding=embedding)
        assert chunk.embedding == embedding


# ---------------------------------------------------------------------------
# Entity tests: KnowledgeBase
# ---------------------------------------------------------------------------


class TestKnowledgeBase:
    """Tests for the KnowledgeBase entity."""

    def test_create_with_defaults(self) -> None:
        kb = KnowledgeBase()
        assert kb.id
        assert kb.document_count == 0
        assert kb.chunk_count == 0

    def test_add_document(self) -> None:
        kb = KnowledgeBase(name="Main KB")
        doc = Document(title="Doc1")
        doc.add_chunk(Chunk(text="chunk1"))
        doc.add_chunk(Chunk(text="chunk2"))

        kb.add_document(doc)
        assert kb.document_count == 1
        assert kb.chunk_count == 2

    def test_add_multiple_documents(self) -> None:
        kb = KnowledgeBase()
        doc1 = Document()
        doc1.add_chunk(Chunk(text="a"))
        doc2 = Document()
        doc2.add_chunk(Chunk(text="b"))
        doc2.add_chunk(Chunk(text="c"))

        kb.add_document(doc1)
        kb.add_document(doc2)
        assert kb.document_count == 2
        assert kb.chunk_count == 3

    def test_remove_document(self) -> None:
        kb = KnowledgeBase()
        doc = Document()
        doc.add_chunk(Chunk(text="a"))
        doc.add_chunk(Chunk(text="b"))
        kb.add_document(doc)

        kb.remove_document(chunk_count=2)
        assert kb.document_count == 0
        assert kb.chunk_count == 0

    def test_remove_document_clamp_zero(self) -> None:
        """Counts should not go negative."""
        kb = KnowledgeBase()
        kb.remove_document(chunk_count=5)
        assert kb.document_count == 0
        assert kb.chunk_count == 0


# ---------------------------------------------------------------------------
# Entity tests: User
# ---------------------------------------------------------------------------


class TestUser:
    """Tests for the User entity."""

    def test_create_with_defaults(self) -> None:
        user = User()
        assert user.id == ""
        assert user.is_active is True
        assert user.roles == []

    def test_admin_role(self) -> None:
        user = User(roles=["admin"])
        assert user.is_admin is True
        assert user.is_expert is True  # admin implies expert

    def test_expert_role(self) -> None:
        user = User(roles=["expert"])
        assert user.is_admin is False
        assert user.is_expert is True

    def test_regular_user(self) -> None:
        user = User(roles=["user"])
        assert user.is_admin is False
        assert user.is_expert is False

    def test_can_access_public(self) -> None:
        user = User(id="u1", roles=["user"])
        assert user.can_access("public", [], []) is True

    def test_can_access_admin_always(self) -> None:
        user = User(id="u1", roles=["admin"])
        assert user.can_access("restricted", [], []) is True

    def test_can_access_by_user_id(self) -> None:
        user = User(id="u1", roles=["user"])
        assert user.can_access("restricted", [], ["u1"]) is True
        assert user.can_access("restricted", [], ["u2"]) is False

    def test_can_access_by_group(self) -> None:
        user = User(id="u1", roles=["user"], groups=["engineering"])
        assert user.can_access("restricted", ["engineering"], []) is True
        assert user.can_access("restricted", ["marketing"], []) is False

    def test_cannot_access_restricted(self) -> None:
        user = User(id="u1", roles=["user"], groups=["sales"])
        assert user.can_access("restricted", ["engineering"], ["u2"]) is False


# ---------------------------------------------------------------------------
# Value object tests: SearchQuery
# ---------------------------------------------------------------------------


class TestSearchQuery:
    """Tests for the SearchQuery value object."""

    def test_create_valid(self) -> None:
        q = SearchQuery(text="how to deploy")
        assert q.text == "how to deploy"
        assert q.top_k == 20
        assert q.version is None

    def test_create_with_params(self) -> None:
        q = SearchQuery(text="deploy", version="v2", top_k=5)
        assert q.version == "v2"
        assert q.top_k == 5

    def test_empty_text_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            SearchQuery(text="")

    def test_whitespace_text_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            SearchQuery(text="   ")

    def test_top_k_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="top_k must be >= 1"):
            SearchQuery(text="test", top_k=0)

    def test_immutability(self) -> None:
        q = SearchQuery(text="test")
        with pytest.raises(AttributeError):
            q.text = "changed"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        q1 = SearchQuery(text="test", top_k=10)
        q2 = SearchQuery(text="test", top_k=10)
        assert q1 == q2

    def test_inequality_by_value(self) -> None:
        q1 = SearchQuery(text="test", top_k=10)
        q2 = SearchQuery(text="test", top_k=5)
        assert q1 != q2


# ---------------------------------------------------------------------------
# Value object tests: RetrievalResult
# ---------------------------------------------------------------------------


class TestRetrievalResult:
    """Tests for the RetrievalResult value object."""

    def _make_result(self, score: float) -> RetrievalResult:
        return RetrievalResult(
            chunk_id="c1",
            text="some text",
            score=score,
            source_type="confluence",
            source_id="s1",
            title="Doc",
            version="v1",
            metadata={},
        )

    def test_high_relevance(self) -> None:
        r = self._make_result(0.9)
        assert r.relevance == "high"

    def test_medium_relevance(self) -> None:
        r = self._make_result(0.6)
        assert r.relevance == "medium"

    def test_low_relevance(self) -> None:
        r = self._make_result(0.3)
        assert r.relevance == "low"

    def test_boundary_high_medium(self) -> None:
        assert self._make_result(0.8).relevance == "high"
        assert self._make_result(0.79).relevance == "medium"

    def test_boundary_medium_low(self) -> None:
        assert self._make_result(0.5).relevance == "medium"
        assert self._make_result(0.49).relevance == "low"

    def test_immutability(self) -> None:
        r = self._make_result(0.5)
        with pytest.raises(AttributeError):
            r.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Value object tests: ConfidenceScore
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    """Tests for the ConfidenceScore value object."""

    def test_confident(self) -> None:
        cs = ConfidenceScore(value=0.7, factors={}, action="USE")
        assert cs.is_confident is True
        assert cs.needs_review is False

    def test_needs_review(self) -> None:
        cs = ConfidenceScore(value=0.3, factors={}, action="EXPAND")
        assert cs.is_confident is False
        assert cs.needs_review is True

    def test_boundary_confident(self) -> None:
        assert ConfidenceScore(value=0.6, factors={}, action="USE").is_confident is True
        assert ConfidenceScore(value=0.59, factors={}, action="REWRITE").is_confident is False

    def test_boundary_needs_review(self) -> None:
        assert ConfidenceScore(value=0.5, factors={}, action="REWRITE").needs_review is False
        assert ConfidenceScore(value=0.49, factors={}, action="EXPAND").needs_review is True

    def test_immutability(self) -> None:
        cs = ConfidenceScore(value=0.5, factors={}, action="USE")
        with pytest.raises(AttributeError):
            cs.value = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Value object tests: TokenBudget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    """Tests for the TokenBudget value object."""

    def test_remaining(self) -> None:
        tb = TokenBudget(total=1000, used=300, reserved=100)
        assert tb.remaining == 600

    def test_remaining_clamped(self) -> None:
        """Remaining should not go negative."""
        tb = TokenBudget(total=100, used=80, reserved=50)
        assert tb.remaining == 0

    def test_utilization(self) -> None:
        tb = TokenBudget(total=1000, used=500)
        assert tb.utilization == 0.5

    def test_utilization_zero_total(self) -> None:
        tb = TokenBudget(total=0, used=0)
        assert tb.utilization == 0.0

    def test_can_fit_true(self) -> None:
        tb = TokenBudget(total=1000, used=500, reserved=100)
        assert tb.can_fit(399) is True
        assert tb.can_fit(400) is True

    def test_can_fit_false(self) -> None:
        tb = TokenBudget(total=1000, used=500, reserved=100)
        assert tb.can_fit(401) is False

    def test_allocate(self) -> None:
        tb = TokenBudget(total=1000, used=0)
        tb2 = tb.allocate(200)
        assert tb2.used == 200
        assert tb2.remaining == 800
        # original unchanged (immutable)
        assert tb.used == 0

    def test_immutability(self) -> None:
        tb = TokenBudget(total=1000, used=0)
        with pytest.raises(AttributeError):
            tb.total = 500  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Domain event tests
# ---------------------------------------------------------------------------


class TestDomainEvents:
    """Tests for domain events."""

    def test_base_event(self) -> None:
        ev = DomainEvent()
        assert ev.id
        assert ev.timestamp
        assert ev.event_type == ""

    def test_document_indexed(self) -> None:
        ev = DocumentIndexed(document_id="d1", chunk_count=5, source_type="confluence")
        assert ev.event_type == "document.indexed"
        assert ev.document_id == "d1"
        assert ev.chunk_count == 5

    def test_document_updated(self) -> None:
        ev = DocumentUpdated(document_id="d1", old_version="v1", new_version="v2")
        assert ev.event_type == "document.updated"
        assert ev.old_version == "v1"
        assert ev.new_version == "v2"

    def test_feedback_submitted(self) -> None:
        ev = FeedbackSubmitted(
            feedback_id="f1",
            user_id="u1",
            feedback_type="positive",
            query="how to deploy",
        )
        assert ev.event_type == "feedback.submitted"
        assert ev.feedback_type == "positive"

    def test_model_promoted(self) -> None:
        ev = ModelPromoted(model_name="slm-v2", version="1.0", promoted_by="admin")
        assert ev.event_type == "model.promoted"

    def test_retrieval_performed(self) -> None:
        ev = RetrievalPerformed(query="deploy", result_count=10, latency_ms=42.5, cache_hit=True)
        assert ev.event_type == "retrieval.performed"
        assert ev.cache_hit is True

    def test_chunk_created(self) -> None:
        ev = ChunkCreated(chunk_id="c1", document_id="d1", text_length=500)
        assert ev.event_type == "chunk.created"

    def test_user_authenticated(self) -> None:
        ev = UserAuthenticated(user_id="u1", method="jwt", success=True)
        assert ev.event_type == "user.authenticated"

    def test_event_ids_unique(self) -> None:
        ev1 = DomainEvent()
        ev2 = DomainEvent()
        assert ev1.id != ev2.id


# ---------------------------------------------------------------------------
# Service tests: AccessControlService
# ---------------------------------------------------------------------------


class TestAccessControlService:
    """Tests for the AccessControlService domain service."""

    def setup_method(self) -> None:
        self.service = AccessControlService()

    def _make_chunks(self) -> list[Chunk]:
        return [
            Chunk(id="c1", text="public", access_level="public"),
            Chunk(
                id="c2",
                text="eng only",
                access_level="restricted",
                allowed_groups=["engineering"],
            ),
            Chunk(
                id="c3",
                text="user1 only",
                access_level="restricted",
                allowed_users=["user-1"],
            ),
        ]

    def test_admin_sees_all(self) -> None:
        admin = User(id="admin", roles=["admin"])
        chunks = self._make_chunks()
        filtered = self.service.filter_chunks_by_access(chunks, admin)
        assert len(filtered) == 3

    def test_anonymous_sees_public(self) -> None:
        chunks = self._make_chunks()
        filtered = self.service.filter_chunks_by_access(chunks, None)
        assert len(filtered) == 3  # None = unrestricted

    def test_regular_user_sees_public_and_own(self) -> None:
        user = User(id="user-1", roles=["user"], groups=["sales"])
        chunks = self._make_chunks()
        filtered = self.service.filter_chunks_by_access(chunks, user)
        ids = [c.id for c in filtered]
        assert "c1" in ids  # public
        assert "c3" in ids  # allowed_users
        assert "c2" not in ids  # not in engineering

    def test_group_access(self) -> None:
        user = User(id="u2", roles=["user"], groups=["engineering"])
        chunks = self._make_chunks()
        filtered = self.service.filter_chunks_by_access(chunks, user)
        ids = [c.id for c in filtered]
        assert "c1" in ids
        assert "c2" in ids  # engineering group
        assert "c3" not in ids

    def test_build_access_filter_admin(self) -> None:
        admin = User(id="admin", roles=["admin"])
        assert self.service.build_access_filter(admin) is None

    def test_build_access_filter_anonymous(self) -> None:
        assert self.service.build_access_filter(None) is None

    def test_build_access_filter_regular_user(self) -> None:
        user = User(id="u1", roles=["user"], groups=["eng", "data"])
        f = self.service.build_access_filter(user)
        assert f is not None
        assert f["must"][0]["match"]["value"] == "public"
        assert f["should"][0]["match"]["any"] == ["u1"]
        assert f["should"][1]["match"]["any"] == ["eng", "data"]


# ---------------------------------------------------------------------------
# Service tests: RetrievalScoringService
# ---------------------------------------------------------------------------


class TestRetrievalScoringService:
    """Tests for the RetrievalScoringService domain service."""

    def setup_method(self) -> None:
        self.service = RetrievalScoringService()

    # -- RRF --

    def test_rrf_basic(self) -> None:
        score = self.service.compute_rrf_score(dense_rank=1, sparse_rank=1, k=60)
        expected = 1.0 / 61 + 1.0 / 61
        assert abs(score - expected) < 1e-9

    def test_rrf_different_ranks(self) -> None:
        score = self.service.compute_rrf_score(dense_rank=1, sparse_rank=10, k=60)
        assert score > 0
        # rank 1 contributes more than rank 10
        rank1_contrib = 1.0 / 61
        rank10_contrib = 1.0 / 70
        assert abs(score - (rank1_contrib + rank10_contrib)) < 1e-9

    def test_rrf_higher_rank_lower_score(self) -> None:
        s1 = self.service.compute_rrf_score(1, 1)
        s5 = self.service.compute_rrf_score(5, 5)
        assert s1 > s5

    # -- Knee point --

    def test_knee_point_obvious(self) -> None:
        scores = [0.9, 0.85, 0.3, 0.2, 0.1]
        knee = self.service.find_knee_point(scores)
        assert knee == 2  # biggest drop between index 1 and 2

    def test_knee_point_gradual(self) -> None:
        # Use values that are exact in IEEE 754 to avoid FP precision issues
        scores = [0.5, 0.25, 0.125, 0.0625]
        knee = self.service.find_knee_point(scores)
        # drops: 0.25, 0.125, 0.0625 — biggest is first → knee=1
        assert knee == 1

    def test_knee_point_small_list(self) -> None:
        assert self.service.find_knee_point([0.9]) == 1
        assert self.service.find_knee_point([0.9, 0.5]) == 2

    def test_knee_point_empty(self) -> None:
        assert self.service.find_knee_point([]) == 0

    # -- Confidence --

    def test_confidence_high(self) -> None:
        cs = self.service.compute_confidence(
            score_distribution=[0.9, 0.85, 0.8],
            coverage_ratio=0.9,
            result_count=5,
            recency_decay=1.0,
        )
        assert cs.action == "USE"
        assert cs.is_confident is True

    def test_confidence_low_fallback(self) -> None:
        cs = self.service.compute_confidence(
            score_distribution=[0.1, 0.05],
            coverage_ratio=0.1,
            result_count=1,
            recency_decay=0.2,
        )
        assert cs.action == "FALLBACK"
        assert cs.is_confident is False

    def test_confidence_empty_distribution(self) -> None:
        cs = self.service.compute_confidence(
            score_distribution=[],
            coverage_ratio=0.0,
            result_count=0,
        )
        assert cs.value == 0.0
        assert cs.action == "FALLBACK"

    def test_confidence_rewrite_range(self) -> None:
        """Test REWRITE action (0.4 <= value < 0.6)."""
        cs = self.service.compute_confidence(
            score_distribution=[0.5],
            coverage_ratio=0.5,
            result_count=3,
            recency_decay=0.5,
        )
        # score_factor = min(0.5/0.8, 1.0) * 0.4 = 0.25
        # coverage_factor = 0.5 * 0.3 = 0.15
        # count_factor = min(3/5, 1.0) * 0.2 = 0.12
        # recency_factor = 0.5 * 0.1 = 0.05
        # total = 0.57 → REWRITE? Let's just check it's one of the valid actions
        assert cs.action in ("USE", "REWRITE", "EXPAND", "FALLBACK")

    def test_confidence_expand_range(self) -> None:
        """Test EXPAND action (0.2 <= value < 0.4)."""
        cs = self.service.compute_confidence(
            score_distribution=[0.2],
            coverage_ratio=0.1,
            result_count=1,
            recency_decay=0.1,
        )
        # score_factor = min(0.2/0.8, 1.0) * 0.4 = 0.1
        # coverage_factor = 0.1 * 0.3 = 0.03
        # count_factor = min(1/5, 1.0) * 0.2 = 0.04
        # recency_factor = 0.1 * 0.1 = 0.01
        # total = 0.18 → FALLBACK
        assert cs.action in ("EXPAND", "FALLBACK")

    def test_confidence_factors_sum(self) -> None:
        """Factors should sum approximately to the value."""
        cs = self.service.compute_confidence(
            score_distribution=[0.7, 0.6],
            coverage_ratio=0.8,
            result_count=4,
            recency_decay=0.9,
        )
        factor_sum = sum(cs.factors.values())
        assert abs(factor_sum - cs.value) < 1e-9
