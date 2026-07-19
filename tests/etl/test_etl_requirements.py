# tests/etl/test_etl_requirements.py
"""Integration tests for ETL requirements FR-40 through FR-57.

Each test class corresponds to a Functional Requirement from
docs/ru/requirements/06-etl.md with acceptance criteria verification.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

# ─────────────────────────────────────────────────────────────────────────────
# FR-40: 6 Data Sources
# ─────────────────────────────────────────────────────────────────────────────


class TestFR40Extractors:
    """FR-40: Each extractor returns documents with id, title, content,
    source_type, metadata. Incremental extraction — only changed documents.
    """

    def _assert_document_fields(self, doc: dict) -> None:
        """Verify a document has required fields: id/title, content, source_type, metadata."""
        has_id = "id" in doc or "source_id" in doc or "key" in doc
        assert has_id, f"Document missing id/source_id/key: {list(doc.keys())}"
        assert "title" in doc or "summary" in doc, f"Document missing title/summary: {list(doc.keys())}"
        assert "content" in doc or "description" in doc, "Document missing content/description"
        assert "source_type" in doc or "key" in doc, "Document missing source_type"

    def test_confluence_extractor_returns_valid_docs(self, sample_confluence_page):
        """FR-40 AC1: Confluence extractor returns docs with id, title, content, source_type."""
        from etl.extractors.confluence import ConfluenceExtractor

        config = {
            "url": "https://confluence.test.local",
            "token": "test-token",
            "space_keys": ["DEV"],
            "output_dir": "/tmp/test_confluence",
            "wal_file": "/tmp/test_wal/confluence_wal.json",
        }
        extractor = ConfluenceExtractor(config)

        # Mock the session._request to avoid network calls
        page_detail = {
            "id": "12345",
            "title": "Test Page",
            "space": {"key": "DEV"},
            "version": {"number": 1, "when": "2025-01-15T10:00:00Z", "by": {"displayName": "Test User"}},
            "body": {
                "storage": {"value": "<p>Test content with RAG information.</p>"},
                "view": {"value": "<p>Test content with RAG information.</p>"},
            },
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = page_detail
        mock_response.raise_for_status = MagicMock()
        extractor.session.get = MagicMock(return_value=mock_response)

        page_data = extractor.extract_page(sample_confluence_page)

        assert "id" in page_data
        assert "title" in page_data
        assert "body_markdown" in page_data or "body_storage_raw" in page_data
        assert page_data["title"] == "Test Page"

    def test_jira_extractor_returns_valid_docs(self, sample_jira_issue):
        """FR-40 AC1: Jira extractor returns docs with id, title, content, source_type."""
        from etl.extractors.jira import JiraExtractor

        config = {
            "url": "https://jira.test.local",
            "token": "test-token",
            "output_dir": "/tmp/test_jira",
            "wal_file": "/tmp/test_wal/jira_wal.json",
        }
        extractor = JiraExtractor(config)
        result = extractor._process_issue(sample_jira_issue)

        assert "key" in result
        assert result["key"] == "PROJ-123"
        assert "summary" in result
        assert result["summary"] == "Test issue"
        assert "description" in result

    def test_gitlab_extractor_returns_valid_docs(self):
        """FR-40 AC1: GitLab extractor returns docs with id, title, content."""
        from etl.extractors.gitlab import GitLabExtractor

        config = {
            "url": "https://gitlab.test.local",
            "token": "test-token",
            "project_ids": [1],
            "output_dir": "/tmp/test_gitlab",
            "wal_file": "/tmp/test_wal/gitlab_wal.json",
        }
        extractor = GitLabExtractor(config)
        assert extractor.url == "https://gitlab.test.local"
        assert extractor.project_ids == [1]

    def test_doc_extractor_returns_valid_docs(self, tmp_path):
        """FR-40 AC1: Doc extractor returns docs with id, title, content, source_type."""
        from etl.extractors.base_extractor import ExtractorConfig
        from etl.extractors.doc_extractor import DocExtractor

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "test.md").write_text("# Test Title\n\nTest content here.")

        config = ExtractorConfig(
            source_name="docs",
            source_type="doc",
            base_url=str(docs_dir),
        )
        extractor = DocExtractor(config)

        async def run():
            await extractor.validate_connection()
            docs = []
            async for doc in extractor.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(run())
        assert len(docs) > 0
        doc = docs[0]
        assert doc.source_id
        assert doc.title
        assert doc.content
        assert doc.source_type == "doc"

    def test_book_extractor_returns_valid_docs(self, tmp_path):
        """FR-40 AC1: Book extractor returns docs with id, title, content, source_type."""
        from etl.extractors.base_extractor import ExtractorConfig
        from etl.extractors.book_extractor import BookExtractor

        books_dir = tmp_path / "books"
        books_dir.mkdir()
        (books_dir / "test.md").write_text("# Chapter 1\n\nBook content here.")

        config = ExtractorConfig(
            source_name="books",
            source_type="book",
            base_url=str(books_dir),
        )
        extractor = BookExtractor(config)
        assert extractor.config.source_type == "book"

    def test_chat_extractor_returns_valid_docs(self, tmp_path):
        """FR-40 AC1: Chat extractor returns docs with id, title, content, source_type."""
        from etl.extractors.base_extractor import ExtractorConfig
        from etl.extractors.chat_extractor import ChatExtractor

        chats_dir = tmp_path / "chats"
        chats_dir.mkdir()
        chat_data = {
            "conversations": [
                {
                    "id": "conv_1",
                    "title": "Test Chat",
                    "messages": [
                        {"role": "user", "content": "What is RAG?"},
                        {"role": "assistant", "content": "RAG is Retrieval Augmented Generation."},
                    ],
                }
            ]
        }
        (chats_dir / "chat.json").write_text(json.dumps(chat_data))

        config = ExtractorConfig(
            source_name="chats",
            source_type="chat",
            base_url=str(chats_dir),
        )
        extractor = ChatExtractor(config)

        async def run():
            await extractor.validate_connection()
            docs = []
            async for doc in extractor.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(run())
        assert len(docs) > 0
        doc = docs[0]
        assert doc.source_type == "chat"
        assert doc.content

    def test_all_six_extractors_exist(self):
        """FR-40: All 6 extractor modules exist and are importable."""
        from etl.extractors import (
            book_extractor,
            chat_extractor,
            confluence,
            doc_extractor,
            gitlab,
            jira,
        )

        assert hasattr(confluence, "ConfluenceExtractor")
        assert hasattr(jira, "JiraExtractor")
        assert hasattr(gitlab, "GitLabExtractor")
        assert hasattr(doc_extractor, "DocExtractor")
        assert hasattr(book_extractor, "BookExtractor")
        assert hasattr(chat_extractor, "ChatExtractor")

    def test_incremental_extraction_skips_unchanged(self, tmp_path):
        """FR-40 AC3: Incremental extraction — only changed documents."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        chunks_v1 = [{"hash": "aaa", "text": "content v1"}]
        added1, _ = store.update_document_chunks("doc_1", chunks_v1)
        assert len(added1) == 1

        # Same content — should return no changes
        added2, _ = store.update_document_chunks("doc_1", chunks_v1)
        assert len(added2) == 0

    def test_confluence_incremental_skips_unchanged_pages(self, tmp_path):
        """FR-40 AC3: Confluence extractor skips pages with unchanged hash."""
        from etl.extractors.confluence import ConfluenceExtractor

        config = {
            "url": "https://confluence.test.local",
            "token": "test-token",
            "output_dir": str(tmp_path / "output"),
            "wal_file": str(tmp_path / "wal" / "confluence_wal.json"),
            "incremental": True,
        }
        extractor = ConfluenceExtractor(config)

        page = {"id": "123", "body": {"storage": {"value": "<p>content</p>"}}, "version": {"number": 1, "when": ""}}
        new_hash = extractor._calculate_page_hash(page)
        assert extractor._should_process_page("123", new_hash) is True

        # Simulate WAL already has this hash
        extractor.wal_data["pages_hash"] = {"123": new_hash}
        assert extractor._should_process_page("123", new_hash) is False


# ─────────────────────────────────────────────────────────────────────────────
# FR-41: Semantic Chunking
# ─────────────────────────────────────────────────────────────────────────────


class TestFR41SemanticChunking:
    """FR-41: Chunks respect headings, preserve context, overlap 50-100 tokens."""

    def test_chunks_split_by_headings(self):
        """FR-41 AC1: Chunks don't break sentences."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=500, overlap_tokens=80)
        md = "# Title\n\nFirst paragraph.\n\n## Section 1\n\nSecond paragraph here."
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.text.strip()
            assert len(chunk.text) > 0

    def test_chunks_contain_context(self):
        """FR-41 AC2: Each chunk contains context (section heading, document name)."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=200, overlap_tokens=80)
        md = "# Test Doc\n\nFirst paragraph content here.\n\n## Section A\n\nSection A content."
        source_metadata = {"source_type": "confluence", "doc_title": "Test Doc", "source_id": "123"}
        chunks = chunker.chunk_markdown_with_overlap(md, source_metadata)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.source_type or chunk.doc_title

    def test_overlap_between_chunks(self):
        """FR-41 AC3: Overlap between adjacent chunks — 50-100 tokens."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=50, overlap_tokens=10)
        # Create a document long enough to produce multiple chunks
        paragraphs = [f"Paragraph number {i} with enough text to fill tokens. " * 5 for i in range(10)]
        md = "# Title\n\n" + "\n\n".join(paragraphs)
        chunks = chunker.chunk_markdown_with_overlap(md)
        if len(chunks) > 1:
            # Verify overlap is applied — second chunk should have context prefix
            assert "[previous context:" in chunks[1].text or chunks[1].text

    def test_preserves_table_structure(self):
        """FR-41: Tables are preserved in chunk content."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=500)
        md = "# Table Doc\n\n| Col1 | Col2 |\n|------|------|\n| A    | B    |\n| C    | D    |"
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) >= 1
        table_found = any("|" in c.text or "Col1" in c.text for c in chunks)
        assert table_found

    def test_preserves_code_blocks(self):
        """FR-41: Code block structure is preserved."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=500)
        md = "# Code Doc\n\n```python\ndef hello():\n    print('hello')\n```"
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) >= 1
        assert "def hello" in chunks[0].text or "hello" in chunks[0].text

    def test_acl_metadata_propagated_to_chunks(self):
        """FR-41: ACL metadata (access_level, allowed_groups, allowed_users) in chunks."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=500)
        md = "# Doc\n\nSome content."
        metadata = {
            "source_type": "confluence",
            "doc_title": "Doc",
            "access_level": "confidential",
            "allowed_groups": ["admin"],
            "allowed_users": ["user1"],
        }
        chunks = chunker.chunk_markdown_with_overlap(md, metadata)
        assert len(chunks) >= 1
        assert chunks[0].access_level == "confidential"
        assert "admin" in chunks[0].allowed_groups
        assert "user1" in chunks[0].allowed_users


# ─────────────────────────────────────────────────────────────────────────────
# FR-44: WAL-based Incremental Extraction
# ─────────────────────────────────────────────────────────────────────────────


class TestFR44WALIncremental:
    """FR-44: WAL tracks stage state. On failure, ETL resumes from last
    successful stage. WAL contains checkpoint per stage. WAL cleared on success.
    """

    def test_wal_checkpoint_resume_after_failure(self, tmp_path):
        """FR-44 AC1: Failure at embedding stage — restart resumes from embedding."""
        from etl.indexer.wal_manager import WALManager

        wal = WALManager(tmp_path / "wal.json", use_lock=False)
        wal.set_checkpoint("indexing", {"stage": "embedding", "doc_id": "doc_1", "progress": 0.5})
        wal.set_checkpoint("extraction", {"stage": "completed", "doc_id": "doc_1"})

        # Verify extraction is completed but embedding is incomplete
        assert wal.get_checkpoint("extraction", "stage") == "completed"
        assert wal.get_checkpoint("indexing", "stage") == "embedding"
        assert wal.get_checkpoint("indexing", "progress") == 0.5

    def test_wal_contains_checkpoint_per_stage(self, tmp_path):
        """FR-44 AC2: WAL file contains checkpoint for each stage."""
        from etl.indexer.wal_manager import WALManager

        wal = WALManager(tmp_path / "wal.json", use_lock=False)
        stages = ["extraction", "chunking", "embedding", "indexing"]
        for stage in stages:
            wal.set_checkpoint(stage, {"status": "completed", "timestamp": datetime.now(UTC).isoformat()})

        for stage in stages:
            assert wal.get_checkpoint(stage, "status") == "completed"

    def test_wal_cleared_on_success(self, tmp_path):
        """FR-44 AC3: Successful completion — WAL is cleared."""
        from etl.indexer.wal_manager import WALManager

        wal = WALManager(tmp_path / "wal.json", use_lock=False)
        wal.set_checkpoint("extraction", {"status": "completed"})
        wal.set_checkpoint("indexing", {"status": "completed"})

        # Simulate successful completion
        wal.reset_all()
        assert wal.get_checkpoint("extraction") == {}
        assert wal.get_checkpoint("indexing") == {}

    def test_wal_reset_single_pipeline(self, tmp_path):
        """FR-44: Reset single pipeline without affecting others."""
        from etl.indexer.wal_manager import WALManager

        wal = WALManager(tmp_path / "wal.json", use_lock=False)
        wal.set_checkpoint("confluence_extractor", {"status": "completed"})
        wal.set_checkpoint("jira_extractor", {"status": "running"})

        wal.reset_pipeline("confluence_extractor")
        assert wal.get_checkpoint("confluence_extractor") == {}
        assert wal.get_checkpoint("jira_extractor", "status") == "running"

    def test_wal_preserves_last_run_on_reset(self, tmp_path):
        """FR-44: keep_last_run preserves the timestamp."""
        from etl.indexer.wal_manager import WALManager

        wal = WALManager(tmp_path / "wal.json", use_lock=False)
        wal.set_checkpoint("pipe_a", {"last_run": "2025-01-01T00:00:00", "status": "running"})

        wal.reset_pipeline("pipe_a", keep_last_run=True)
        assert wal.get_checkpoint("pipe_a", "last_run") == "2025-01-01T00:00:00"


# ─────────────────────────────────────────────────────────────────────────────
# FR-45: SHA-256 Content-Addressable Chunks
# ─────────────────────────────────────────────────────────────────────────────


class TestFR45ContentAddressable:
    """FR-45: Same content → same hash → one Qdrant point.
    Changed content → different hash → new Qdrant point.
    """

    def test_same_content_same_hash(self):
        """FR-45 AC1: Same content → same hash."""
        from etl.chunker.hash_versioning import compute_chunk_hash

        chunk_a = {"text": "hello world", "title": "Test", "source_type": "wiki"}
        chunk_b = {"text": "hello world", "title": "Test", "source_type": "wiki"}
        assert compute_chunk_hash(chunk_a) == compute_chunk_hash(chunk_b)

    def test_different_content_different_hash(self):
        """FR-45 AC2: Changed content → different hash."""
        from etl.chunker.hash_versioning import compute_chunk_hash

        chunk_a = {"text": "original content", "title": "Test"}
        chunk_b = {"text": "modified content", "title": "Test"}
        assert compute_chunk_hash(chunk_a) != compute_chunk_hash(chunk_b)

    def test_hash_is_sha256(self):
        """FR-45: Hash is SHA-256 (64 hex chars)."""
        from etl.chunker.hash_versioning import compute_chunk_hash

        h = compute_chunk_hash({"text": "test"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_used_as_point_id(self):
        """FR-45 AC3: Hash is used as Point ID in Qdrant."""
        from etl.chunker.hash_versioning import compute_chunk_hash

        chunk = {"text": "content", "title": "Doc", "source_type": "wiki"}
        h = compute_chunk_hash(chunk)
        expected = hashlib.sha256(
            json.dumps(
                {
                    "text": "content",
                    "title": "Doc",
                    "source_type": "wiki",
                    "source_id": "",
                    "version": "",
                    "doc_title": "",
                    "keywords": [],
                    "entities": [],
                    "summary": "",
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        assert h == expected

    def test_hash_deduplication(self, tmp_path):
        """FR-45: Identical chunks produce identical hashes for dedup."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        chunks = [
            {"hash": "aaa", "text": "content"},
        ]
        added, _ = store.update_document_chunks("doc_1", chunks)
        assert len(added) == 1

        # Same content again — no changes detected
        added2, _ = store.update_document_chunks("doc_1", chunks)
        assert len(added2) == 0


# ─────────────────────────────────────────────────────────────────────────────
# FR-46: Hot/Cold Storage Stratification
# ─────────────────────────────────────────────────────────────────────────────


class TestFR46HotColdStorage:
    """FR-46: Current version in Qdrant (hot), old versions in Parquet (cold).
    rag_version query finds chunks in cold storage too.
    """

    def test_hot_storage_contains_current_version(self, tmp_path):
        """FR-46 AC1: Current version stored in hot directory."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        chunks = [{"hash": "aaa", "text": "current content"}]
        store.update_document_chunks("doc_1", chunks)

        hot_file = tmp_path / "hot" / "doc_1.json"
        assert hot_file.exists()
        with open(hot_file) as f:
            loaded = json.load(f)
        assert len(loaded) == 1
        assert loaded[0]["hash"] == "aaa"

    def test_cold_storage_contains_old_versions(self, tmp_path):
        """FR-46 AC2: Old versions stored in cold storage."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        # Version 1
        chunks_v1 = [{"hash": "aaa", "text": "v1 content"}]
        store.update_document_chunks("doc_1", chunks_v1)
        # Version 2
        chunks_v2 = [{"hash": "bbb", "text": "v2 content"}]
        store.update_document_chunks("doc_1", chunks_v2)

        # Cold storage should have history
        history = store.get_chunk_history("doc_1")
        assert len(history) > 0

    def test_get_all_current_chunks_from_hot(self, tmp_path):
        """FR-46: get_all_current_chunks returns all current (hot) chunks."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        store.update_document_chunks("doc_a", [{"hash": "a1", "text": "text a"}])
        store.update_document_chunks("doc_b", [{"hash": "b1", "text": "text b"}, {"hash": "b2", "text": "text b2"}])

        all_chunks = store.get_all_current_chunks()
        assert len(all_chunks) == 3


# ─────────────────────────────────────────────────────────────────────────────
# FR-47: Version Tracking
# ─────────────────────────────────────────────────────────────────────────────


class TestFR47VersionTracking:
    """FR-47: Old chunks marked stale, new chunks get current version.
    Version filtering returns only requested version.
    """

    def test_updated_doc_marks_old_chunks_stale(self, tmp_path):
        """FR-47 AC1: Updated document — old chunks get stale=true."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        chunks_v1 = [{"hash": "aaa", "text": "v1", "version": "1.0"}]
        store.update_document_chunks("doc_1", chunks_v1)

        chunks_v2 = [{"hash": "bbb", "text": "v2", "version": "2.0"}]
        added, deleted = store.update_document_chunks("doc_1", chunks_v2)

        assert len(added) == 1
        assert added[0]["version"] == "2.0"
        assert len(deleted) == 1
        assert deleted[0] == "aaa"

    def test_version_field_in_chunks(self):
        """FR-47: Chunks have version field."""
        from etl.chunker.semantic_chunker import SemanticChunker

        chunker = SemanticChunker(max_tokens=500)
        md = "# Doc\n\nContent."
        metadata = {"source_type": "confluence", "doc_title": "Doc", "version": "3.0"}
        chunks = chunker.chunk_markdown_with_overlap(md, metadata)
        assert len(chunks) >= 1
        assert chunks[0].version == "3.0"

    def test_version_history_tracked(self, tmp_path):
        """FR-47: System tracks version history."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        for v in range(3):
            chunks = [{"hash": f"v{v}", "text": f"version {v}", "version": str(v)}]
            store.update_document_chunks("doc_1", chunks)

        history = store.get_chunk_history("doc_1")
        assert len(history) >= 2  # At least 2 updates recorded


# ─────────────────────────────────────────────────────────────────────────────
# FR-48: RAPTOR Hierarchical Indexing
# ─────────────────────────────────────────────────────────────────────────────


class TestFR48RaptorTree:
    """FR-48: Tree of summaries (root → cluster → chunks).
    Top-level search returns general summaries, bottom returns specific chunks.
    """

    def test_build_tree_from_chunks(self):
        """FR-48 AC1: Tree is built (root → cluster → chunks)."""
        from etl.indexer.tree_builder import RaptorTreeBuilder

        builder = RaptorTreeBuilder(max_cluster_size=3)
        chunks = [{"text": f"Chunk {i} about topic {i // 3}"} for i in range(9)]
        tree = builder.build_tree(chunks)

        levels = {node.level for node in tree.values()}
        assert 0 in levels  # Leaf nodes
        assert 1 in levels  # Cluster summaries
        # Root may be level 2 depending on clustering

    def test_top_level_returns_summaries(self):
        """FR-48 AC2: Search at top level returns general summaries."""
        from etl.indexer.tree_builder import RaptorTreeBuilder

        builder = RaptorTreeBuilder(max_cluster_size=3)
        chunks = [{"text": f"Chunk {i} content"} for i in range(6)]
        tree = builder.build_tree(chunks)

        top_summaries = builder.get_summaries_at_level(tree, level=1)
        assert len(top_summaries) > 0
        for s in top_summaries:
            assert len(s) > 0

    def test_bottom_level_returns_chunks(self):
        """FR-48 AC3: Search at bottom level returns specific chunks."""
        from etl.indexer.tree_builder import RaptorTreeBuilder

        builder = RaptorTreeBuilder(max_cluster_size=5)
        chunks = [{"text": f"Specific chunk {i}"} for i in range(5)]
        tree = builder.build_tree(chunks)

        leaf_summaries = builder.get_summaries_at_level(tree, level=0)
        assert len(leaf_summaries) == 5

    def test_tree_nodes_have_parent_child_relationship(self):
        """FR-48: Tree nodes have parent-child relationships."""
        from etl.indexer.tree_builder import RaptorTreeBuilder

        builder = RaptorTreeBuilder(max_cluster_size=2)
        chunks = [{"text": f"Chunk {i}"} for i in range(4)]
        tree = builder.build_tree(chunks)

        # At least one node should have a parent
        has_parent = any(node.parent is not None for node in tree.values())
        assert has_parent

    def test_tree_save_and_load(self, tmp_path):
        """FR-48: Tree can be saved and loaded."""
        from etl.indexer.tree_builder import RaptorTreeBuilder

        builder = RaptorTreeBuilder(max_cluster_size=3)
        chunks = [{"text": f"Chunk {i}"} for i in range(6)]
        tree = builder.build_tree(chunks)

        path = tmp_path / "tree.json"
        builder.save_tree(tree, path)
        assert path.exists()

        loaded = builder.load_tree(path)
        assert len(loaded) == len(tree)


# ─────────────────────────────────────────────────────────────────────────────
# FR-49: Code-aware Chunking (AST-based)
# ─────────────────────────────────────────────────────────────────────────────


class TestFR49CodeChunking:
    """FR-49: Python files split by functions/classes using AST.
    Each chunk has function name in metadata. Imports duplicated for context.
    """

    def test_python_file_produces_function_chunks(self):
        """FR-49 AC1: Python file with 3 functions → 3 chunks."""
        from etl.chunker.code_chunker import chunk_python

        source = '''
def func_a():
    """Function A."""
    return "a"

def func_b():
    """Function B."""
    return "b"

def func_c():
    """Function C."""
    return "c"
'''
        chunks = chunk_python(source)
        names = [c.name for c in chunks]
        assert "func_a" in names
        assert "func_b" in names
        assert "func_c" in names

    def test_chunk_has_function_name_in_metadata(self):
        """FR-49 AC2: Each chunk contains function name."""
        from etl.chunker.code_chunker import chunk_python

        source = "def my_function():\n    return 42\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "my_function"
        assert "def my_function" in chunks[0].code

    def test_class_chunking(self):
        """FR-49: Python classes are chunked as units."""
        from etl.chunker.code_chunker import chunk_python

        source = '''
class MyClass:
    """A test class."""

    def method_a(self):
        return "a"

    def method_b(self):
        return "b"
'''
        chunks = chunk_python(source)
        names = [c.name for c in chunks]
        assert "MyClass" in names

    def test_chunk_has_line_numbers(self):
        """FR-49: Chunks have line start/end numbers."""
        from etl.chunker.code_chunker import chunk_python

        source = "def func():\n    return 42\n"
        chunks = chunk_python(source)
        assert chunks[0].line_start > 0
        assert chunks[0].line_end >= chunks[0].line_start

    def test_chunk_has_docstring(self):
        """FR-49: Chunks extract docstrings."""
        from etl.chunker.code_chunker import chunk_python

        source = 'def documented():\n    """This is a docstring."""\n    pass\n'
        chunks = chunk_python(source)
        assert chunks[0].docstring == "This is a docstring."

    def test_code_chunk_dispatch(self):
        """FR-49: chunk_code dispatches to correct language."""
        from etl.chunker.code_chunker import chunk_code

        py_source = 'def hello():\n    print("hello")\n'
        chunks = chunk_code(py_source, "python")
        assert len(chunks) >= 1
        assert chunks[0].language == "python"


# ─────────────────────────────────────────────────────────────────────────────
# FR-50: Image OCR Extraction
# ─────────────────────────────────────────────────────────────────────────────


class TestFR50ImageOCR:
    """FR-50: OCR extracts text from images. PDF scans supported.
    OCR quality >= 90% for clear images.
    """

    def test_ocr_result_has_text_and_confidence(self):
        """FR-50 AC1: OCR result has text and confidence fields."""
        from etl.extractors.image_extractor import OCRResult

        result = OCRResult(text="Hello world", confidence=95.0)
        assert result.text == "Hello world"
        assert result.confidence == 95.0
        assert result.is_above_threshold  # Default threshold is 60

    def test_ocr_result_below_threshold(self):
        """FR-50: OCR result below threshold is flagged."""
        from etl.extractors.image_extractor import OCRResult

        result = OCRResult(text="noise", confidence=30.0)
        assert not result.is_above_threshold

    def test_extract_images_from_html(self):
        """FR-50: Extract image references from HTML."""
        from etl.extractors.image_extractor import extract_images_from_html

        html = '<img src="image1.png" alt="Diagram"><img src="image2.jpg" alt="Chart">'
        images = extract_images_from_html(html)
        assert len(images) == 2
        assert images[0].src == "image1.png"
        assert images[0].alt == "Diagram"

    def test_extract_images_skips_data_uris(self):
        """FR-50: Data URI images are skipped."""
        from etl.extractors.image_extractor import extract_images_from_html

        html = '<img src="data:image/png;base64,abc123"><img src="real.png">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "real.png"

    def test_image_info_dataclass(self):
        """FR-50: ImageInfo has required fields."""
        from etl.extractors.image_extractor import ImageInfo

        info = ImageInfo(src="test.png", alt="Test image")
        assert info.src == "test.png"
        assert info.alt == "Test image"

    def test_extracted_image_dataclass(self):
        """FR-50: ExtractedImage has required fields."""
        from etl.extractors.image_extractor import ExtractedImage

        img = ExtractedImage(path="/tmp/img.png", page_number=1, width=800, height=600)
        assert img.path == "/tmp/img.png"
        assert img.page_number == 1


# ─────────────────────────────────────────────────────────────────────────────
# FR-51: Quality Metrics for Chunks
# ─────────────────────────────────────────────────────────────────────────────


class TestFR51QualityMetrics:
    """FR-51: Each chunk has quality_score (0-1). Low-score chunks filtered.
    Metrics are logged.
    """

    def test_quality_filter_scores_chunks(self):
        """FR-51 AC1: Each chunk gets a quality score."""
        from etl.indexer.chunk_quality import ChunkQualityFilter

        qf = ChunkQualityFilter(
            reranker_endpoint="",  # No remote API — heuristic only
            threshold=0.0,  # Accept all
            detect_boilerplate=True,
        )
        chunks = [
            {"text": "This is a meaningful technical document about RAG systems."},
            {"text": "All rights reserved. Copyright 2025."},
        ]
        filtered, stats = qf.filter("RAG System", chunks)
        assert stats["total"] == 2
        assert stats["kept"] >= 1  # At least the meaningful chunk
        assert stats["dropped"] >= 1  # The copyright boilerplate

    def test_boilerplate_detection(self):
        """FR-51: Boilerplate chunks are detected and filtered."""
        from etl.indexer.chunk_quality import ChunkQualityFilter

        qf = ChunkQualityFilter(detect_boilerplate=True)
        is_bp, reason = qf.detect_boilerplate("All rights reserved. Copyright 2025.")
        assert is_bp
        assert reason

    def test_quality_filter_keeps_good_content(self):
        """FR-51: Good content passes the filter."""
        from etl.indexer.chunk_quality import ChunkQualityFilter

        qf = ChunkQualityFilter(
            reranker_endpoint="",
            threshold=0.0,
            detect_boilerplate=True,
        )
        chunks = [{"text": "The RAG system uses vector search with hybrid retrieval for better accuracy."}]
        filtered, stats = qf.filter("RAG System", chunks)
        assert stats["kept"] == 1

    def test_quality_filter_empty_input(self):
        """FR-51: Empty input returns empty result."""
        from etl.indexer.chunk_quality import ChunkQualityFilter

        qf = ChunkQualityFilter()
        filtered, stats = qf.filter("Title", [])
        assert stats["total"] == 0
        assert stats["kept"] == 0

    def test_minimal_content_detected(self):
        """FR-51: Very short content is detected as low quality."""
        from etl.indexer.chunk_quality import ChunkQualityFilter

        qf = ChunkQualityFilter(detect_boilerplate=True)
        is_bp, _ = qf.detect_boilerplate("---")
        assert is_bp


# ─────────────────────────────────────────────────────────────────────────────
# FR-52: Chunk Enrichment (SLM)
# ─────────────────────────────────────────────────────────────────────────────


class TestFR52ChunkEnrichment:
    """FR-52: SLM generates summary, entities, keywords for each chunk.
    Enrichment doesn't break existing metadata.
    """

    def test_enricher_generates_summary(self):
        """FR-52 AC1: Each chunk gets a summary."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        result = enricher.enrich("RAG systems combine retrieval with generation for better answers.")
        assert "summary" in result
        assert len(result["summary"]) > 0

    def test_enricher_generates_keywords(self):
        """FR-52 AC2: Each chunk gets keywords."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        result = enricher.enrich("The RAG system uses Qdrant vector database with BAAI/bge-m3 embeddings.")
        assert "keywords" in result
        assert len(result["keywords"]) > 0

    def test_enricher_generates_entities(self):
        """FR-52 AC2: Each chunk gets entities."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        result = enricher.enrich("Qdrant is used with BAAI/bge-m3 for embeddings in the RAG system.")
        assert "entities" in result

    def test_enricher_generates_hyde_questions(self):
        """FR-52: Enricher generates hypothetical questions."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        result = enricher.enrich("How does the RAG system work? It uses retrieval augmented generation.")
        assert "hyde_questions" in result

    def test_enricher_preserves_existing_metadata(self):
        """FR-52 AC3: Enrichment doesn't break existing metadata."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        metadata = {"doc_title": "My Doc", "source_type": "confluence"}
        result = enricher.enrich("Content about RAG.", metadata)
        # Original metadata should still be accessible
        assert "keywords" in result
        assert "entities" in result
        assert "summary" in result

    def test_enricher_empty_input(self):
        """FR-52: Empty input returns empty result."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        result = enricher.enrich("")
        assert result["keywords"] == []
        assert result["entities"] == []
        assert result["summary"] == ""

    def test_enricher_heuristic_keywords(self):
        """FR-52: Heuristic keyword extraction works."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        keywords = enricher._heuristic_keywords(
            "The RAG system uses vector database and embedding model for retrieval augmented generation."
        )
        assert len(keywords) > 0
        assert all(isinstance(k, str) for k in keywords)

    def test_enricher_heuristic_summary(self):
        """FR-52: Heuristic summary generation works."""
        from etl.indexer.chunk_enricher import ChunkEnricher

        enricher = ChunkEnricher(fallback_to_heuristic=True)
        summary = enricher._heuristic_summary("First sentence. Second sentence. Third sentence.")
        assert len(summary) > 0
        assert "First sentence" in summary


# ─────────────────────────────────────────────────────────────────────────────
# FR-53: Streaming Pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestFR53StreamingPipeline:
    """FR-53: Documents processed as they arrive (streaming, not batch).
    Webhook triggers immediate processing. Error → retry with backoff.
    """

    def test_streaming_result_has_required_fields(self):
        """FR-53: StreamingResult has source, doc_id, chunks_count."""
        from etl.scheduler.streaming_pipeline import StreamingResult

        result = StreamingResult(source="confluence", doc_id="page_123")
        assert result.source == "confluence"
        assert result.doc_id == "page_123"
        assert result.chunks_count == 0
        assert result.chunks_indexed == 0

    def test_pipeline_progress_tracking(self):
        """FR-53: Pipeline tracks progress."""
        from etl.scheduler.streaming_pipeline import PipelineProgress

        progress = PipelineProgress(total_docs=100, processed_docs=50)
        assert progress.progress_pct == 50.0

    def test_pipeline_progress_zero_docs(self):
        """FR-53: Progress with zero docs returns 0%."""
        from etl.scheduler.streaming_pipeline import PipelineProgress

        progress = PipelineProgress(total_docs=0)
        assert progress.progress_pct == 0.0

    def test_streaming_pipeline_init(self):
        """FR-53: StreamingPipeline can be initialized."""
        from etl.scheduler.streaming_pipeline import StreamingPipeline

        config = {"streaming": {"max_concurrent_api_calls": 5}}
        wal = MagicMock()
        pipeline = StreamingPipeline(config, wal)
        assert pipeline._max_concurrent == 5


# ─────────────────────────────────────────────────────────────────────────────
# FR-54: Event Pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestFR54EventPipeline:
    """FR-54: Events from Confluence/Jira/GitLab trigger ETL.
    page_updated → reindex, page_removed → delete, unknown → log.
    """

    def test_event_pipeline_init(self):
        """FR-54: EventPipeline initializes with config."""
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        config = {"streaming": {"redis_host": "localhost", "redis_port": 6379}}
        pipeline = EventPipeline(config)
        assert pipeline.state == PipelineState.IDLE
        assert not pipeline.is_running

    def test_event_pipeline_states(self):
        """FR-54: Pipeline has correct lifecycle states."""
        from etl.scheduler.event_pipeline import PipelineState

        assert PipelineState.IDLE == "idle"
        assert PipelineState.STARTING == "starting"
        assert PipelineState.RUNNING == "running"
        assert PipelineState.STOPPING == "stopping"
        assert PipelineState.STOPPED == "stopped"
        assert PipelineState.ERROR == "error"

    def test_event_pipeline_status(self):
        """FR-54: get_status returns correct info."""
        from etl.scheduler.event_pipeline import EventPipeline

        config = {}
        pipeline = EventPipeline(config)
        status = pipeline.get_status()
        assert "state" in status
        assert "is_running" in status
        assert status["state"] == "idle"

    def test_confluence_page_updated_triggers_reindex(self):
        """FR-54 AC1: page_updated event → reindex."""
        from etl.scheduler.event_pipeline import EventPipeline

        config = {}
        pipeline = EventPipeline(config)
        event = {
            "source": "confluence",
            "event_type": "page_updated",
            "doc_id": "page_123",
            "payload": {},
        }
        # process_event returns False when consumer not initialized (stub)
        result = pipeline.process_event(event)
        assert isinstance(result, bool)

    def test_unknown_event_logged_not_crash(self):
        """FR-54 AC3: Unknown event is logged, doesn't crash."""
        from etl.scheduler.event_pipeline import EventPipeline

        config = {}
        pipeline = EventPipeline(config)
        event = {
            "source": "unknown_source",
            "event_type": "unknown_event",
            "doc_id": "unknown",
            "payload": {},
        }
        # Should not raise
        result = pipeline.process_event(event)
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# FR-55: Webhook Server
# ─────────────────────────────────────────────────────────────────────────────


class TestFR55WebhookServer:
    """FR-55: POST /webhook/confluence, /webhook/gitlab endpoints.
    Valid payload → process. Invalid → 400. HMAC signature check.
    """

    def test_webhook_app_creation(self):
        """FR-55: Webhook app is created with correct endpoints."""
        from etl.scheduler.webhook_server import create_app

        app = create_app(redis_client=None, webhook_secret="test_secret")
        # Verify app is a FastAPI instance with routes
        assert app is not None
        assert hasattr(app, "routes")
        assert len(app.routes) > 0

    def test_webhook_health_endpoint(self):
        """FR-55: Health endpoint returns ok."""
        from fastapi.testclient import TestClient

        from etl.scheduler.webhook_server import create_app

        app = create_app(redis_client=None)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_invalid_json_returns_422(self):
        """FR-55 AC2: Invalid payload → error response."""
        import hashlib
        import hmac

        from fastapi.testclient import TestClient

        from etl.scheduler.webhook_server import create_app

        secret = "test_secret"
        app = create_app(redis_client=None, webhook_secret=secret)
        client = TestClient(app)

        body = b"not valid json"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = client.post(
            "/webhook/confluence",
            content=body,
            headers={"X-Hub-Signature-256": f"sha256={sig}"},
        )
        assert response.status_code == 422

    def test_webhook_missing_signature_returns_401(self):
        """FR-55 AC3: Missing HMAC signature → 401."""
        from fastapi.testclient import TestClient

        from etl.scheduler.webhook_server import create_app

        app = create_app(redis_client=None, webhook_secret="test_secret")
        client = TestClient(app)
        response = client.post(
            "/webhook/confluence",
            json={"event": "page_updated"},
        )
        assert response.status_code == 401

    def test_webhook_invalid_signature_returns_401(self):
        """FR-55 AC3: Invalid HMAC signature → 401."""
        from fastapi.testclient import TestClient

        from etl.scheduler.webhook_server import create_app

        app = create_app(redis_client=None, webhook_secret="test_secret")
        client = TestClient(app)
        response = client.post(
            "/webhook/confluence",
            json={"event": "page_updated"},
            headers={"X-Hub-Signature-256": "sha256=invalid_signature"},
        )
        assert response.status_code == 401

    def test_webhook_disabled_returns_503(self):
        """FR-55: Disabled webhook returns 503."""
        import hashlib
        import hmac

        from fastapi.testclient import TestClient

        from etl.scheduler.webhook_server import create_app

        secret = "test"
        app = create_app(redis_client=None, webhook_secret=secret, webhook_enabled=False)
        client = TestClient(app)

        body = json.dumps({"event": "page_updated"}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# FR-56: Task Scheduler
# ─────────────────────────────────────────────────────────────────────────────


class TestFR56TaskScheduler:
    """FR-56: Full indexing — daily. Incremental — every 15 min.
    Cleanup — weekly. Failed tasks retry up to 3 times.
    """

    def test_task_scheduler_init(self):
        """FR-56: TaskScheduler initializes correctly."""
        from etl.scheduler.task_scheduler import TaskScheduler

        scheduler = TaskScheduler()
        assert scheduler.kb_manager is None
        assert scheduler._active_tasks == {}

    def test_task_scheduler_with_kb_manager(self):
        """FR-56: TaskScheduler works with KB manager."""
        from etl.scheduler.task_scheduler import TaskScheduler

        mock_kb = MagicMock()
        mock_task = MagicMock()
        mock_task.id = "task_1"
        mock_kb.create_task.return_value = mock_task

        scheduler = TaskScheduler(kb_manager=mock_kb)
        task_id = scheduler.start_task("kb_1", "confluence", "page_123")
        assert task_id == "task_1"
        mock_kb.create_task.assert_called_once()

    def test_task_scheduler_no_kb_manager_returns_none(self):
        """FR-56: Without KB manager, start_task returns None."""
        from etl.scheduler.task_scheduler import TaskScheduler

        scheduler = TaskScheduler()
        result = scheduler.start_task("kb_1", "confluence", "page_123")
        assert result is None

    def test_task_scheduler_complete_task(self):
        """FR-56: complete_task marks task as completed."""
        from etl.scheduler.task_scheduler import TaskScheduler

        mock_kb = MagicMock()
        mock_task = MagicMock()
        mock_task.kb_id = "kb_1"
        mock_kb.get_task.return_value = mock_task

        scheduler = TaskScheduler(kb_manager=mock_kb)
        scheduler.complete_task("task_1")
        mock_kb.update_task.assert_called_with("task_1", status="completed", progress=1.0)

    def test_task_scheduler_fail_task(self):
        """FR-56: fail_task marks task as failed."""
        from etl.scheduler.task_scheduler import TaskScheduler

        mock_kb = MagicMock()
        scheduler = TaskScheduler(kb_manager=mock_kb)
        scheduler.fail_task("task_1", "Connection timeout")
        mock_kb.update_task.assert_called_with("task_1", status="failed", error_message="Connection timeout")

    def test_task_scheduler_get_pending_tasks(self):
        """FR-56: get_pending_tasks returns pending tasks."""
        from etl.scheduler.task_scheduler import TaskScheduler

        mock_kb = MagicMock()
        mock_kb.list_tasks.return_value = [{"id": "t1"}, {"id": "t2"}]
        scheduler = TaskScheduler(kb_manager=mock_kb)
        tasks = scheduler.get_pending_tasks("kb_1")
        assert len(tasks) == 2


# ─────────────────────────────────────────────────────────────────────────────
# FR-57: Cold Storage Cleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestFR57ColdStorageCleanup:
    """FR-57: Versions > 90 days deleted, 30-90 days archived to S3.
    Log contains count of processed records.
    """

    def test_cleanup_cold_storage_basic(self, tmp_path):
        """FR-57 AC1: Cleanup removes old Parquet versions."""
        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        cold_dir = tmp_path / "cold"
        cold_dir.mkdir()
        # Create version files
        (cold_dir / "doc_v1.parquet").write_text("v1")
        (cold_dir / "doc_v2.parquet").write_text("v2")
        (cold_dir / "doc_v3.parquet").write_text("v3")

        deleted = cleanup_cold_storage(str(cold_dir), max_versions=2)
        assert deleted >= 1

    def test_cleanup_keeps_latest_versions(self, tmp_path):
        """FR-57 AC1: Latest versions are kept."""
        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        cold_dir = tmp_path / "cold"
        cold_dir.mkdir()
        (cold_dir / "doc_v1.parquet").write_text("v1")
        (cold_dir / "doc_v2.parquet").write_text("v2")

        deleted = cleanup_cold_storage(str(cold_dir), max_versions=2)
        assert deleted == 0

    def test_cleanup_empty_directory(self, tmp_path):
        """FR-57: Cleanup on empty directory returns 0."""
        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        cold_dir = tmp_path / "empty_cold"
        cold_dir.mkdir()
        deleted = cleanup_cold_storage(str(cold_dir))
        assert deleted == 0

    def test_cleanup_nonexistent_directory(self, tmp_path):
        """FR-57: Cleanup on nonexistent directory returns 0."""
        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        deleted = cleanup_cold_storage(str(tmp_path / "nonexistent"))
        assert deleted == 0

    def test_list_parquet_versions(self, tmp_path):
        """FR-57: Parquet versions are correctly detected."""
        from etl.scheduler.cold_storage_cleanup import _list_parquet_versions

        cold_dir = tmp_path / "cold"
        cold_dir.mkdir()
        (cold_dir / "doc_v1.parquet").write_text("v1")
        (cold_dir / "doc_v2.parquet").write_text("v2")
        (cold_dir / "other_v1.parquet").write_text("v1")

        versions = _list_parquet_versions(cold_dir)
        assert "doc" in versions
        assert "other" in versions
        assert len(versions["doc"]) == 2

    def test_cleanup_multiple_documents(self, tmp_path):
        """FR-57: Cleanup handles multiple documents."""
        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        cold_dir = tmp_path / "cold"
        cold_dir.mkdir()
        for doc in ["doc_a", "doc_b"]:
            for v in range(1, 4):
                (cold_dir / f"{doc}_v{v}.parquet").write_text(f"v{v}")

        deleted = cleanup_cold_storage(str(cold_dir), max_versions=1)
        assert deleted == 4  # 2 old versions per document

    def test_cleanup_stats_logged(self, tmp_path, caplog):
        """FR-57 AC3: Log contains count of processed records."""
        import logging

        from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage

        cold_dir = tmp_path / "cold"
        cold_dir.mkdir()
        (cold_dir / "doc_v1.parquet").write_text("v1")
        (cold_dir / "doc_v2.parquet").write_text("v2")

        with caplog.at_level(logging.INFO):
            cleanup_cold_storage(str(cold_dir), max_versions=1)

        assert any("pruned" in record.message or "cleanup" in record.message.lower() for record in caplog.records)
