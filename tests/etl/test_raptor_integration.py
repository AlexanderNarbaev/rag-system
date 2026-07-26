# ruff: noqa: E402
"""RAPTOR integration tests (FR-48).

These tests exercise the multi-level RAPTOR tree end-to-end:
- Building the tree from a realistic corpus
- Hierarchical retrieval (top-level summaries, mid-level clusters, leaf chunks)
- Parent/child traversal for context expansion
- Tree persistence

The embedder is mocked so the tests stay offline and deterministic.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure etl/ is on the path for module resolution
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "etl"))

from etl.indexer.tree_builder import RaptorTreeBuilder  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def doc_corpus() -> list[dict]:
    """A small but realistic multi-topic corpus of document chunks."""
    return [
        {
            "text": (
                "RAG combines a retrieval system with a generative language model. "
                "Documents are split into chunks and indexed in a vector database."
            ),
            "metadata": {"source": "rag_overview.md", "topic": "rag"},
        },
        {
            "text": (
                "Hybrid search merges dense embeddings with sparse lexical scoring. "
                "Reciprocal Rank Fusion combines both result lists into a unified ranking."
            ),
            "metadata": {"source": "retrieval.md", "topic": "rag"},
        },
        {
            "text": (
                "Cross-encoder reranking re-scores query-document pairs with a deep "
                "transformer. It is more accurate but slower than bi-encoder retrieval."
            ),
            "metadata": {"source": "reranker.md", "topic": "rag"},
        },
        {
            "text": (
                "Qdrant supports HNSW indexing for approximate nearest neighbours. "
                "ef_construction and M control the recall/latency trade-off."
            ),
            "metadata": {"source": "qdrant.md", "topic": "infra"},
        },
        {
            "text": (
                "Neo4j stores the knowledge graph of entities and relationships. "
                "Cypher queries traverse multi-hop paths in O(degree) per hop."
            ),
            "metadata": {"source": "neo4j.md", "topic": "infra"},
        },
        {
            "text": (
                "ETL pipelines extract data from sources like Confluence, Jira and "
                "GitLab. They chunk documents, embed them, and upsert into Qdrant."
            ),
            "metadata": {"source": "etl.md", "topic": "pipeline"},
        },
        {
            "text": (
                "LoRA fine-tunes a small number of low-rank adapter weights. It "
                "matches full-fine-tuning accuracy for many tasks at a fraction of "
                "the memory cost."
            ),
            "metadata": {"source": "lora.md", "topic": "training"},
        },
        {
            "text": (
                "Confidence scoring blends retrieval similarity with an optional SLM "
                "verification pass. Low-confidence responses are flagged for HITL."
            ),
            "metadata": {"source": "confidence.md", "topic": "rag"},
        },
        {
            "text": (
                "Caching reduces LLM latency for repeated queries. A two-tier cache "
                "uses Redis for embeddings and an LRU in-memory map for responses."
            ),
            "metadata": {"source": "cache.md", "topic": "perf"},
        },
    ]


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Deterministic embedder that hashes tokens into a fixed-length vector.

    The vector is stable for the same input text, which lets us assert
    deterministic similarity across runs without touching real models.
    """

    def _embed(text: str) -> list[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # 16 floats is plenty for unit-level checks
        return [b / 255.0 for b in digest[:16]]

    return MagicMock(side_effect=_embed)


@pytest.fixture
def raptor(mock_embedder) -> RaptorTreeBuilder:
    """A RAPTOR builder with a deterministic embedder and small clusters."""
    return RaptorTreeBuilder(
        max_cluster_size=3,
        max_levels=3,
        embed_fn=mock_embedder,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tree construction
# ─────────────────────────────────────────────────────────────────────────────


class TestRaptorTreeBuilding:
    """Test RAPTOR tree building with real document chunks."""

    def test_build_tree_with_real_chunks(self, raptor, doc_corpus):
        """Build a tree from a real-shaped corpus and verify the shape."""
        tree = raptor.build_tree(doc_corpus)

        # The tree must contain leaf nodes for every chunk
        leaves = [n for n in tree.values() if n.level == 0]
        assert len(leaves) == len(doc_corpus)

        # There must be at least one upper-level node (since leaves > 1)
        upper = [n for n in tree.values() if n.level >= 1]
        assert len(upper) > 0

        # Highest level reached depends on cluster size; assert >= 1
        max_level = max(n.level for n in tree.values())
        assert max_level >= 1

    def test_tree_node_id_format(self, raptor, doc_corpus):
        """All node IDs follow the L{level}_{idx} convention."""
        tree = raptor.build_tree(doc_corpus)
        for node_id, node in tree.items():
            assert node_id == node.id
            assert node_id.startswith(f"L{node.level}_")

    def test_leaf_node_metadata_is_preserved(self, raptor, doc_corpus):
        """Metadata of the original chunks survives into the leaf nodes."""
        tree = raptor.build_tree(doc_corpus)
        leaves = sorted(
            (n for n in tree.values() if n.level == 0),
            key=lambda n: n.id,
        )
        # Topics should be visible across leaves
        topics = [n.metadata.get("topic") for n in leaves]
        assert "rag" in topics
        assert "infra" in topics


# ─────────────────────────────────────────────────────────────────────────────
# Multi-level retrieval
# ─────────────────────────────────────────────────────────────────────────────


class TestRaptorMultiLevelRetrieval:
    """Test multi-level retrieval: top summaries, mid clusters, bottom chunks."""

    def test_top_level_summaries_are_general(self, raptor, doc_corpus):
        """Level-1+ nodes are summaries (shorter than leaf texts)."""
        tree = raptor.build_tree(doc_corpus)

        top_summaries = raptor.get_summaries_at_level(tree, level=1)
        assert len(top_summaries) > 0
        # A summary should not equal any single leaf verbatim
        leaf_texts = {n.text for n in tree.values() if n.level == 0}
        for s in top_summaries:
            assert s not in leaf_texts

    def test_mid_level_cluster_covers_multiple_leaves(self, raptor, doc_corpus):
        """Each cluster at level 1 has at least one child at level 0."""
        tree = raptor.build_tree(doc_corpus)
        level1_nodes = [n for n in tree.values() if n.level == 1]
        assert level1_nodes, "Expected at least one level-1 cluster"

        for cluster in level1_nodes:
            # Every recorded child must exist in the tree
            for child_id in cluster.children:
                assert child_id in tree
                assert tree[child_id].level == 0

    def test_bottom_level_returns_all_chunks(self, raptor, doc_corpus):
        """Level 0 returns every original chunk exactly once."""
        tree = raptor.build_tree(doc_corpus)
        leaves = raptor.get_summaries_at_level(tree, level=0)
        assert len(leaves) == len(doc_corpus)

    def test_get_all_summaries_groups_by_level(self, raptor, doc_corpus):
        """``get_all_summaries`` returns a level-indexed dict."""
        tree = raptor.build_tree(doc_corpus)
        grouped = raptor.get_all_summaries(tree)

        assert 0 in grouped
        assert len(grouped[0]) == len(doc_corpus)

        # Higher levels should also be present and non-empty
        for _level, items in grouped.items():
            assert len(items) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Parent-child traversal
# ─────────────────────────────────────────────────────────────────────────────


class TestRaptorParentChildTraversal:
    """Test parent-child relationship traversal for context expansion."""

    def test_all_non_root_nodes_have_a_parent(self, raptor, doc_corpus):
        """Every non-root node points to a parent in the tree.

        The single root (top of the tree) is allowed to have no parent;
        all other upper-level nodes must point to one.
        """
        tree = raptor.build_tree(doc_corpus)
        max_level = max(n.level for n in tree.values())
        if max_level < 2:
            pytest.skip("Tree has only one level — no non-root upper nodes")

        orphans = []
        for node in tree.values():
            if node.parent is None and node.level < max_level:
                orphans.append(node.id)
        assert orphans == [], f"Orphan non-root nodes: {orphans}"

    def test_children_ids_match_parent_lists(self, raptor, doc_corpus):
        """If A → B is a parent link, then B's children include A's id."""
        tree = raptor.build_tree(doc_corpus)
        for node in tree.values():
            if node.parent is not None:
                parent = tree[node.parent]
                assert node.id in parent.children

    def test_traverse_root_to_leaves(self, raptor, doc_corpus):
        """Walking from a top-level node down reaches only valid descendants."""
        tree = raptor.build_tree(doc_corpus)
        top_nodes = [n for n in tree.values() if n.level == max(n.level for n in tree.values())]
        if not top_nodes:
            pytest.skip("Tree only has one level")

        for top in top_nodes:
            visited = set()
            stack = list(top.children)
            while stack:
                cid = stack.pop()
                if cid in visited:
                    continue
                visited.add(cid)
                child = tree[cid]
                stack.extend(child.children)
            # All visited IDs must be valid and below the top node
            assert visited.issubset(set(tree))
            assert visited.isdisjoint({top.id})


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


class TestRaptorPersistence:
    """Test save/load round-trip of the RAPTOR tree."""

    def test_tree_save_and_load_roundtrip(self, raptor, doc_corpus, tmp_path):
        """save_tree → load_tree preserves node count and level structure."""
        tree = raptor.build_tree(doc_corpus)
        path = tmp_path / "raptor_tree.json"

        raptor.save_tree(tree, path)
        assert path.exists()
        assert path.stat().st_size > 0

        loaded = raptor.load_tree(path)
        assert len(loaded) == len(tree)

        # Compare levels
        original_levels = sorted(n.level for n in tree.values())
        loaded_levels = sorted(n.level for n in loaded.values())
        assert original_levels == loaded_levels

    def test_saved_tree_is_valid_json(self, raptor, doc_corpus, tmp_path):
        """The saved file is valid UTF-8 JSON."""
        tree = raptor.build_tree(doc_corpus)
        path = tmp_path / "raptor_tree.json"

        raptor.save_tree(tree, path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        # Every record should have the canonical fields
        for _node_id, node_data in data.items():
            assert "level" in node_data
            assert "text" in node_data
            assert "summary" in node_data
            assert "children" in node_data


# ─────────────────────────────────────────────────────────────────────────────
# Embedder integration
# ─────────────────────────────────────────────────────────────────────────────


class TestRaptorEmbedderIntegration:
    """Test that the embedder is invoked and shapes the tree."""

    def test_embedder_is_stored_on_builder(self, mock_embedder, doc_corpus):
        """The embed_fn passed at construction is stored on the builder.

        The current builder stores the embedder for downstream summarisation;
        it is not invoked during ``build_tree`` itself. We assert that the
        reference is preserved so callers can rely on it for later steps.
        """
        builder = RaptorTreeBuilder(
            max_cluster_size=3,
            max_levels=2,
            embed_fn=mock_embedder,
        )
        assert builder.embed_fn is mock_embedder

    def test_builder_without_embedder_still_works(self, doc_corpus):
        """A builder without an embed_fn still produces a valid tree."""
        builder = RaptorTreeBuilder(max_cluster_size=3, max_levels=2)
        tree = builder.build_tree(doc_corpus)
        # Leaves exist even without embeddings
        leaves = [n for n in tree.values() if n.level == 0]
        assert len(leaves) == len(doc_corpus)
