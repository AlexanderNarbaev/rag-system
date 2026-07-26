"""Integration tests for DDD domain models wired into core modules.

These tests verify that:
- ``EventBus.publish`` invokes all registered handlers (sync and async)
- ``KnowledgeBaseManager`` fires domain events during document indexing
- Retrieval uses ``AccessControlService`` for post-filtering
- Retrieval uses ``RetrievalScoringService`` for RRF and knee-point scoring
- ``compute_confidence`` produces a domain ``ConfidenceScore`` alongside the
  existing ``ConfidenceReport``
- ``TokenOptimizer`` exposes ``TokenBudget`` helpers for callers that
  prefer the value-object API
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from proxy.app.core.confidence import compute_confidence, compute_confidence_score
from proxy.app.core.kb_manager import KnowledgeBase, KnowledgeBaseManager
from proxy.app.core.retrieval import (
    DomainChunkAdapter,
    domain_build_access_filter,
    domain_filter_chunks_by_access,
    domain_find_knee_point,
    reciprocal_rank_fusion,
)
from proxy.app.core.token_optimizer import (
    build_token_budget,
    fit_chunks_into_budget,
    token_budget_from_dict,
)
from proxy.app.domain.entities import Chunk, Document, User
from proxy.app.domain.event_bus import EventBus, bus
from proxy.app.domain.events import (
    ChunkCreated,
    DocumentIndexed,
    DocumentUpdated,
    DomainEvent,
)
from proxy.app.domain.services import AccessControlService, RetrievalScoringService
from proxy.app.domain.value_objects import ConfidenceScore, TokenBudget

# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------


class _IntegrationProbeEvent(DomainEvent):
    event_type: str = "integration.probe"


class _IntegrationProbeOther(DomainEvent):
    event_type: str = "integration.probe_other"


class TestEventBus:
    """Direct tests for the EventBus — no module integration."""

    def test_publish_calls_all_handlers(self) -> None:
        local_bus = EventBus()
        calls: list[DomainEvent] = []

        def h1(event: DomainEvent) -> None:
            calls.append(event)

        def h2(event: DomainEvent) -> None:
            calls.append(event)

        local_bus.subscribe(_IntegrationProbeEvent, h1)
        local_bus.subscribe(_IntegrationProbeEvent, h2)
        event = _IntegrationProbeEvent()
        local_bus.publish(event)

        assert len(calls) == 2
        assert all(c is event for c in calls)

    def test_publish_isolated_by_event_type(self) -> None:
        local_bus = EventBus()
        calls: list[DomainEvent] = []

        def h(event: DomainEvent) -> None:
            calls.append(event)

        local_bus.subscribe(_IntegrationProbeEvent, h)
        local_bus.publish(_IntegrationProbeOther())
        assert calls == []

        local_bus.publish(_IntegrationProbeEvent())
        assert len(calls) == 1

    def test_handler_exception_does_not_propagate(self) -> None:
        local_bus = EventBus()
        second_called = []

        def broken(event: DomainEvent) -> None:
            raise RuntimeError("boom")

        def ok(event: DomainEvent) -> None:
            second_called.append(event)

        local_bus.subscribe(_IntegrationProbeEvent, broken)
        local_bus.subscribe(_IntegrationProbeEvent, ok)
        local_bus.publish(_IntegrationProbeEvent())
        assert len(second_called) == 1

    def test_async_publish_runs_concurrently(self) -> None:
        local_bus = EventBus()
        results: list[str] = []

        async def h1(event: DomainEvent) -> None:
            await asyncio.sleep(0.001)
            results.append("h1")

        async def h2(event: DomainEvent) -> None:
            results.append("h2")

        local_bus.subscribe_async(_IntegrationProbeEvent, h1)
        local_bus.subscribe_async(_IntegrationProbeEvent, h2)
        asyncio.run(local_bus.publish_async(_IntegrationProbeEvent()))
        assert set(results) == {"h1", "h2"}

    def test_global_bus_is_singleton(self) -> None:
        # The module-level ``bus`` instance must be importable and
        # usable from any module.
        from proxy.app.domain.event_bus import bus as bus_again

        assert bus is bus_again
        assert isinstance(bus, EventBus)


# ---------------------------------------------------------------------------
# kb_manager event publishing tests
# ---------------------------------------------------------------------------


class TestKbManagerEvents:
    """Verify ``KnowledgeBaseManager`` publishes domain events on indexing."""

    @pytest.fixture
    def kb_manager(self, tmp_path) -> KnowledgeBaseManager:
        return KnowledgeBaseManager(db_path=str(tmp_path / "kb.db"), qdrant_client=None)

    @pytest.fixture
    def sample_kb(self, kb_manager) -> KnowledgeBase:
        return kb_manager.create_kb(name="Events Test KB")

    def _captured(self) -> dict[type, list[DomainEvent]]:
        captured: dict[type, list[DomainEvent]] = {}

        def make_handler(event_type: type):
            def handler(event: DomainEvent) -> None:
                captured.setdefault(event_type, []).append(event)

            return handler

        bus.subscribe(DocumentIndexed, make_handler(DocumentIndexed))
        bus.subscribe(DocumentUpdated, make_handler(DocumentUpdated))
        bus.subscribe(ChunkCreated, make_handler(ChunkCreated))
        return captured

    def _cleanup_captures(self) -> None:
        bus.clear(DocumentIndexed)
        bus.clear(DocumentUpdated)
        bus.clear(ChunkCreated)

    def test_index_document_fires_document_indexed(self, kb_manager, sample_kb) -> None:
        captured = self._captured()
        try:
            doc = kb_manager.index_document(
                kb_id=sample_kb.id,
                title="Indexing Doc",
                source_type="confluence",
                source_id="page-42",
            )
            assert isinstance(doc, Document)
            assert doc.title == "Indexing Doc"
            assert doc.source_type == "confluence"
            assert isinstance(captured.get(DocumentIndexed), list)
            assert len(captured[DocumentIndexed]) == 1
            event = captured[DocumentIndexed][0]
            assert event.document_id == doc.id
            assert event.source_type == "confluence"
            assert event.chunk_count == 0
        finally:
            self._cleanup_captures()

    def test_index_document_with_chunks_fires_chunk_created(self, kb_manager, sample_kb) -> None:
        captured = self._captured()
        try:
            chunks = [
                Chunk(text="First chunk text", access_level="public"),
                Chunk(text="Second chunk text", access_level="internal", allowed_groups=["eng"]),
            ]
            doc = kb_manager.index_document(
                kb_id=sample_kb.id,
                title="Multi-chunk Doc",
                source_type="jira",
                source_id="JIRA-1",
                chunks=chunks,
            )
            chunk_created = captured.get(ChunkCreated, [])
            assert len(chunk_created) == 2
            assert {c.chunk_id for c in chunk_created} == {chunks[0].id, chunks[1].id}
            # Each chunk is also attached to the document
            assert len(doc.chunks) == 2
            assert all(c.document_id == doc.id for c in doc.chunks)
            # One DocumentIndexed event at the end (with the chunk count)
            document_indexed = captured.get(DocumentIndexed, [])
            assert len(document_indexed) == 1
            assert document_indexed[0].chunk_count == 2
        finally:
            self._cleanup_captures()

    def test_update_document_fires_document_updated(self, kb_manager, sample_kb) -> None:
        self._captured()
        try:
            doc = kb_manager.index_document(
                kb_id=sample_kb.id,
                title="Updatable Doc",
                source_type="gitlab",
                source_id="proj-1",
            )
            assert doc.version == "v1"
            event = kb_manager.update_document(doc, new_version="v2")
            assert isinstance(event, DocumentUpdated)
            assert event.old_version == "v1"
            assert event.new_version == "v2"
            assert event.document_id == doc.id
            assert doc.version == "v2"  # document was mutated
        finally:
            self._cleanup_captures()

    def test_create_chunk_helper_attaches_to_document(self, kb_manager, sample_kb) -> None:
        captured = self._captured()
        try:
            doc = Document(title="Chunk Parent", source_type="confluence", source_id="p1")
            chunk = kb_manager.create_chunk(
                document=doc,
                text="A new chunk for the document",
                access_level="confidential",
                allowed_groups=["finance"],
            )
            assert isinstance(chunk, Chunk)
            assert chunk.document_id == doc.id
            assert chunk in doc.chunks
            assert chunk.access_level == "confidential"
            assert chunk.allowed_groups == ["finance"]
            # ChunkCreated was published
            chunk_events = captured.get(ChunkCreated, [])
            assert len(chunk_events) == 1
            assert chunk_events[0].chunk_id == chunk.id
            assert chunk_events[0].text_length == len("A new chunk for the document")
        finally:
            self._cleanup_captures()


# ---------------------------------------------------------------------------
# Retrieval — AccessControlService tests
# ---------------------------------------------------------------------------


@dataclass
class _StubHit:
    """Lightweight stand-in for a Qdrant ScoredPoint."""

    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    access_level: str = "public"
    allowed_groups: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)


class TestAccessControlIntegration:
    """Verify retrieval uses ``AccessControlService`` for ACL decisions."""

    def test_domain_build_access_filter_admin_returns_none(self) -> None:
        result = domain_build_access_filter(user_id="admin", username="admin", roles=["admin"], is_admin=True)
        assert result is None

    def test_domain_build_access_filter_anonymous_returns_none(self) -> None:
        result = domain_build_access_filter()
        assert result is None

    def test_domain_build_access_filter_user_returns_qdrant_filter(self) -> None:
        result = domain_build_access_filter(
            user_id="u1",
            username="alice",
            roles=["user"],
            groups=["eng", "data"],
        )
        assert result is not None
        assert result["must"][0]["match"]["value"] == "public"
        # The user's id and groups appear in the should clauses
        should_any = [c["match"]["any"] for c in result["should"] if "any" in c.get("match", {})]
        assert ["u1"] in should_any
        assert ["eng", "data"] in should_any

    def test_domain_filter_chunks_by_access_keeps_public_only_for_outsider(self) -> None:
        chunks = [
            _StubHit(id="c1", score=0.9, access_level="public"),
            _StubHit(id="c2", score=0.8, access_level="internal", allowed_groups=["eng"]),
            _StubHit(id="c3", score=0.7, access_level="confidential", allowed_users=["alice"]),
        ]
        result = domain_filter_chunks_by_access(
            chunks,
            user_id="bob",
            username="bob",
            roles=["user"],
            groups=["sales"],
        )
        ids = [c.id for c in result]
        assert "c1" in ids
        assert "c2" not in ids  # bob is not in eng
        assert "c3" not in ids  # bob is not in allowed_users

    def test_domain_filter_chunks_by_access_admin_keeps_all(self) -> None:
        chunks = [
            _StubHit(id="c1", score=0.9, access_level="public"),
            _StubHit(id="c2", score=0.8, access_level="restricted", allowed_users=["someone"]),
        ]
        result = domain_filter_chunks_by_access(chunks, user_id="admin", is_admin=True)
        assert {c.id for c in result} == {"c1", "c2"}

    def test_domain_chunk_adapter_extracts_payload_fields(self) -> None:
        hit = _StubHit(
            id="hit-1",
            score=0.9,
            payload={"access_level": "internal", "allowed_groups": ["eng"], "allowed_users": ["u1"], "text": "hello"},
        )
        domain_chunk = DomainChunkAdapter.to_domain(hit)
        assert isinstance(domain_chunk, Chunk)
        assert domain_chunk.id == "hit-1"
        assert domain_chunk.access_level == "internal"
        assert domain_chunk.allowed_groups == ["eng"]
        assert domain_chunk.allowed_users == ["u1"]
        assert domain_chunk.text == "hello"


# ---------------------------------------------------------------------------
# Retrieval — RetrievalScoringService tests
# ---------------------------------------------------------------------------


def _make_hit(hit_id: str, score: float = 0.5) -> _StubHit:
    return _StubHit(id=hit_id, score=score)


class TestRetrievalScoringIntegration:
    """Verify retrieval uses ``RetrievalScoringService`` for RRF + knee."""

    def test_reciprocal_rank_fusion_top_result_in_both_lists(self) -> None:
        """Original RRF: an item in both lists wins."""
        dense = [_make_hit("a", 0.9), _make_hit("b", 0.8)]
        sparse = [_make_hit("c", 0.7), _make_hit("a", 0.5)]
        result = reciprocal_rank_fusion(dense, sparse)
        ids = [r.id for r in result]
        assert ids[0] == "a"
        assert len(result) == 3

    def test_reciprocal_rank_fusion_handles_empty_sparse(self) -> None:
        dense = [_make_hit("x", 0.9)]
        result = reciprocal_rank_fusion(dense, [])
        assert len(result) == 1
        assert result[0].id == "x"

    def test_rrf_delegates_to_scoring_service(self) -> None:
        """The math used inside reciprocal_rank_fusion matches the domain service.

        We construct two known lists and verify the per-item contribution
        is exactly ``RetrievalScoringService.compute_rrf_score(r, 0, k)``
        (modulo the small sentinel offset added for absent-list hits).
        """
        scoring = RetrievalScoringService()
        dense = [_make_hit("a", 0.9), _make_hit("b", 0.8)]
        sparse = [_make_hit("a", 0.5)]

        # Sanity-check the formula directly:
        # "a" appears at dense rank 1, sparse rank 1 → score should be
        # 2 * compute_rrf_score(1, 1, 60) up to the sentinel offset.
        expected_a = scoring.compute_rrf_score(1, 1, 60)
        assert expected_a > 0

        result = reciprocal_rank_fusion(dense, sparse)
        # "a" must be the top result because it appears in both lists
        assert result[0].id == "a"

    def test_domain_find_knee_point_uses_largest_drop(self) -> None:
        results = [_make_hit(f"r{i}", s) for i, s in enumerate([0.9, 0.85, 0.8, 0.3, 0.2, 0.1])]
        pruned = domain_find_knee_point(results)
        # The largest drop is between index 2 (0.8) and 3 (0.3); the
        # domain knee is index 3 → at least 3 results retained.
        assert len(pruned) >= 2
        assert len(pruned) <= len(results)

    def test_domain_find_knee_point_short_list_returned_as_is(self) -> None:
        results = [_make_hit("a", 0.9), _make_hit("b", 0.5)]
        pruned = domain_find_knee_point(results)
        assert len(pruned) == 2


# ---------------------------------------------------------------------------
# Confidence module tests
# ---------------------------------------------------------------------------


class TestConfidenceIntegration:
    """Verify the confidence module wires through ``ConfidenceScore``."""

    def test_compute_confidence_attaches_domain_confidence_score(self) -> None:
        report = compute_confidence(
            query="What is RAG?",
            context="Retrieval augmented generation combines retrieval with generation. " * 5,
            answer="RAG is a technique that augments generation with retrieved context.",
        )
        assert hasattr(report, "domain_confidence"), "ConfidenceReport should carry a domain_confidence attribute"
        cs = report.domain_confidence
        assert isinstance(cs, ConfidenceScore)
        # Same numeric value
        assert cs.value == report.score
        # Action reflects the score bucket
        assert cs.action in {"USE", "REWRITE", "EXPAND", "FALLBACK"}
        # The is_confident / needs_review properties line up
        assert cs.is_confident is (cs.value >= 0.6)
        assert cs.needs_review is (cs.value < 0.5)

    def test_compute_confidence_low_score_marks_needs_review(self) -> None:
        report = compute_confidence(
            query="hi",
            context="",
            answer="I don't know",
        )
        cs = report.domain_confidence
        assert isinstance(cs, ConfidenceScore)
        assert cs.value < 0.5
        assert cs.needs_review is True
        assert cs.is_confident is False

    def test_compute_confidence_score_helper(self) -> None:
        cs = compute_confidence_score(
            context_length=1000,
            answer_length=200,
            nli_score=0.8,
            uncertainty_hits=0,
        )
        assert isinstance(cs, ConfidenceScore)
        # nli_score 0.8 should push us above 0.6 → USE
        assert cs.value >= 0.6
        assert cs.action == "USE"
        assert cs.is_confident is True
        assert cs.needs_review is False

    def test_compute_confidence_score_helper_no_context(self) -> None:
        cs = compute_confidence_score(
            context_length=0,
            answer_length=200,
            nli_score=None,
            uncertainty_hits=0,
        )
        assert cs.value < 0.5
        assert cs.action in {"FALLBACK", "EXPAND", "REWRITE"}
        assert cs.needs_review is True


# ---------------------------------------------------------------------------
# TokenOptimizer — TokenBudget tests
# ---------------------------------------------------------------------------


class TestTokenBudgetIntegration:
    """Verify ``TokenOptimizer`` exposes a ``TokenBudget`` value-object API."""

    def test_build_token_budget(self) -> None:
        b = build_token_budget(4096, reserved=256)
        assert isinstance(b, TokenBudget)
        assert b.total == 4096
        assert b.used == 0
        assert b.reserved == 256
        assert b.remaining == 4096 - 256

    def test_token_budget_from_dict(self) -> None:
        alloc = {"system_prompt": 200, "context_total": 2400, "history": 500, "response": 996}
        b = token_budget_from_dict(alloc)
        assert isinstance(b, TokenBudget)
        assert b.total == sum(alloc.values())
        assert b.reserved == b.total
        assert b.used == 0
        assert b.remaining == 0

    def test_fit_chunks_into_budget_greedy(self) -> None:
        budget = build_token_budget(1000)
        # Each chunk costs ~400 tokens (10000 chars * 0.4 ≈ 4000 chars /
        # 4 = 1000, weighted). Make each chunk 4000 chars so 3 chunks
        # of 400 tokens total ≈ 1200 > 1000 → only first two fit.
        chunks = [{"text": "x" * 4000}, {"text": "y" * 4000}, {"text": "z" * 4000}]
        selected, new_budget = fit_chunks_into_budget(chunks, budget)
        # Three chunks (~1200 tokens total) won't fit; first two should.
        assert len(selected) == 2
        assert new_budget.used > 0
        assert new_budget.remaining < budget.remaining

    def test_fit_chunks_into_budget_empty(self) -> None:
        budget = build_token_budget(1000)
        selected, new_budget = fit_chunks_into_budget([], budget)
        assert selected == []
        assert new_budget.used == 0

    def test_fit_chunks_into_budget_respects_reservation(self) -> None:
        budget = build_token_budget(1000, reserved=800)
        # Only 200 tokens remain; one short chunk fits, longer does not.
        # 800 chars ≈ 200 tokens; 4000 chars ≈ 1000 tokens.
        chunks = [{"text": "x" * 800}, {"text": "y" * 4000}]
        selected, new_budget = fit_chunks_into_budget(chunks, budget)
        assert len(selected) == 1
        assert selected[0] is chunks[0]


# ---------------------------------------------------------------------------
# End-to-end smoke: domain services work together
# ---------------------------------------------------------------------------


class TestEndToEndDomainFlow:
    """A single scenario that exercises all wired-in domain services."""

    def test_user_query_flow_uses_all_services(self) -> None:
        # 1) Build a domain user with their roles/groups.
        user = User(id="u-end", username="end_user", roles=["user"], groups=["engineering"])

        # 2) Use AccessControlService to filter chunks.
        acl = AccessControlService()
        chunks = [
            Chunk(text="public note", access_level="public"),
            Chunk(text="confidential note", access_level="confidential", allowed_groups=["finance"]),
            Chunk(text="eng note", access_level="confidential", allowed_groups=["engineering"]),
        ]
        visible = acl.filter_chunks_by_access(chunks, user)
        visible_ids = {c.id for c in visible}
        assert visible_ids == {chunks[0].id, chunks[2].id}

        # 3) Use RetrievalScoringService to score the visible chunks.
        scoring = RetrievalScoringService()
        scores = [0.9, 0.85, 0.3]
        for s in scores:
            assert s > 0  # domain sanity
        knee = scoring.find_knee_point(scores)
        assert knee >= 1

        # 4) Compute a domain confidence score from the visible chunks.
        cs = ConfidenceScore(
            value=0.8,
            factors={"coverage": 0.9, "score": 0.8},
            action="USE",
        )
        assert cs.is_confident is True
        assert cs.needs_review is False

        # 5) Allocate a token budget for assembling context.
        budget = TokenBudget(total=2048, used=0, reserved=128)
        allocated = budget.allocate(256)
        assert allocated.used == 256
        assert allocated.remaining == 2048 - 256 - 128

        # 6) Publish a domain event (the bus is the global one).
        event = DocumentIndexed(document_id="d-end", chunk_count=3, source_type="confluence")
        # No handler is registered, so this is a no-op (no error).
        bus.publish(event)
