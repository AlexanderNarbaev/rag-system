# tests/etl/test_semantic_chunker.py
import json
from unittest.mock import MagicMock

from etl.chunker.semantic_chunker import (
    Chunk,
    MDKeyChunker,
    MetadataEnricher,
    SemanticChunker,
    save_chunks_to_json,
)


class TestChunkDataclass:
    def test_default_construction(self):
        c = Chunk(text="hello", hash="abc")
        assert c.text == "hello"
        assert c.hash == "abc"
        assert c.keywords == []
        assert c.entities == []
        assert c.position == 0
        assert c.tokens_approx == 0

    def test_full_construction(self):
        c = Chunk(
            text="full text",
            hash="xyz",
            title="My Title",
            summary="summary",
            keywords=["a", "b"],
            entities=["PERSON:John"],
            source_type="wiki",
            source_id="123",
            version="2.0",
            doc_title="Doc",
            position=5,
            tokens_approx=100,
        )
        assert c.text == "full text"
        assert c.title == "My Title"
        assert c.keywords == ["a", "b"]
        assert c.position == 5


class TestSemanticChunkerEstimateTokens:
    def test_estimate_tokens_rough(self):
        chunker = SemanticChunker()
        assert chunker._estimate_tokens("1234") == 1
        assert chunker._estimate_tokens("1234567890123456") == 4
        assert chunker._estimate_tokens("") == 0


class TestSemanticChunkerSplitByHeadings:
    def test_split_html_with_headings(self):
        chunker = SemanticChunker()
        html = """
        <h1>Intro</h1>
        <p>First paragraph.</p>
        <h2>Details</h2>
        <ul><li>Item 1</li><li>Item 2</li></ul>
        <p>More text.</p>
        """
        sections = chunker._split_by_headings(html)
        assert len(sections) >= 2
        assert sections[0]["heading"] == "Intro"
        assert sections[1]["heading"] == "Details"

    def test_split_html_no_headings(self):
        chunker = SemanticChunker()
        html = "<p>Just a paragraph.</p><p>Another.</p>"
        sections = chunker._split_by_headings(html)
        assert len(sections) == 1
        assert sections[0]["heading"] == "root"


class TestSemanticChunkerSplitByParagraphs:
    def test_split_by_paragraphs(self):
        chunker = SemanticChunker()
        text = "Para one.\n\nPara two.\n\nPara three."
        paragraphs = chunker._split_by_paragraphs(text)
        assert len(paragraphs) == 3
        assert paragraphs[0] == "Para one."
        assert paragraphs[1] == "Para two."
        assert paragraphs[2] == "Para three."

    def test_split_single_paragraph(self):
        chunker = SemanticChunker()
        text = "Just one paragraph."
        paragraphs = chunker._split_by_paragraphs(text)
        assert len(paragraphs) == 1
        assert paragraphs[0] == "Just one paragraph."

    def test_split_empty_text(self):
        chunker = SemanticChunker()
        assert chunker._split_by_paragraphs("") == []
        assert chunker._split_by_paragraphs("\n\n\n") == []


class TestSemanticChunkerMergeShortChunks:
    def test_merge_short_chunks(self):
        chunker = SemanticChunker(max_tokens=1000, min_chunk_tokens=100)
        chunks = [
            Chunk(text="short", hash="a", tokens_approx=10),
            Chunk(text="short2", hash="b", tokens_approx=20),
            Chunk(text="long enough text " * 50, hash="c", tokens_approx=300),
        ]
        merged = chunker._merge_short_chunks(chunks)
        assert len(merged) < 3

    def test_no_merge_when_all_large(self):
        chunker = SemanticChunker(max_tokens=1000, min_chunk_tokens=10)
        chunks = [
            Chunk(text="x" * 200, hash="a", tokens_approx=50),
            Chunk(text="y" * 200, hash="b", tokens_approx=50),
        ]
        merged = chunker._merge_short_chunks(chunks)
        assert len(merged) == 2

    def test_merge_empty_list(self):
        chunker = SemanticChunker()
        assert chunker._merge_short_chunks([]) == []


class TestSemanticChunkerCreateChunk:
    def test_create_chunk(self):
        chunker = SemanticChunker()
        metadata = {"source_type": "wiki", "source_id": "42", "version": "1", "doc_title": "Test"}
        chunk = chunker._create_chunk("hello world", 0, metadata, "Header1")
        assert chunk.text == "hello world"
        assert chunk.title == "Header1"
        assert chunk.source_type == "wiki"
        assert chunk.source_id == "42"
        assert chunk.position == 0
        assert chunk.tokens_approx > 0
        assert len(chunk.hash) == 64


class TestSemanticChunkerApplyOverlap:
    def test_no_overlap_when_disabled(self):
        chunker = SemanticChunker(overlap_tokens=0)
        c1 = Chunk(text="first chunk", hash="a")
        c2 = Chunk(text="second chunk", hash="b")
        result = chunker._apply_overlap([c1, c2])
        assert len(result) == 2
        assert "previous context" not in result[0].text

    def test_overlap_adds_context(self):
        chunker = SemanticChunker(overlap_tokens=5)
        c1 = Chunk(text="aaaa bbbb cccc dddd eeee", hash="a")
        c2 = Chunk(text="second chunk", hash="b")
        result = chunker._apply_overlap([c1, c2])
        assert len(result) == 2
        assert "[previous context" in result[1].text

    def test_single_chunk_no_overlap(self):
        chunker = SemanticChunker(overlap_tokens=20)
        c1 = Chunk(text="only one", hash="a")
        result = chunker._apply_overlap([c1])
        assert len(result) == 1
        assert "previous context" not in result[0].text


class TestSemanticChunkerChunkHtml:
    def test_chunk_html_simple(self):
        chunker = SemanticChunker(max_tokens=8000)
        html = "<h1>Title</h1><p>Some content here.</p><p>More content.</p>"
        metadata = {"source_type": "wiki", "doc_title": "Test Doc"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source_type == "wiki"
            assert c.doc_title == "Test Doc"

    def test_chunk_html_large_content_splits(self):
        chunker = SemanticChunker(max_tokens=5)
        huge_text = "word " * 100
        html = f"<h1>Big</h1><p>{huge_text}</p>"
        metadata = {}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1


class TestSemanticChunkerChunkMarkdown:
    def test_chunk_markdown_simple(self):
        chunker = SemanticChunker(max_tokens=8000)
        md = "# Hello\n\nThis is a paragraph.\n\n## Sub\n\nMore text."
        metadata = {"source_type": "gitlab"}
        chunks = chunker.chunk_markdown(md, metadata)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source_type == "gitlab"


class TestMetadataEnricherExtractKeywords:
    def test_extract_keywords_tfidf(self):
        enricher = MetadataEnricher(use_slm=False)
        text = "Retrieval augmented generation system processes documents"
        keywords = enricher.extract_keywords_tfidf(text, top_n=3)
        assert isinstance(keywords, list)
        assert len(keywords) <= 3

    def test_extract_keywords_empty_text(self):
        enricher = MetadataEnricher()
        assert enricher.extract_keywords_tfidf("") == []


class TestMetadataEnricherExtractEntities:
    def test_extract_entities_no_spacy(self, monkeypatch):
        # Force nlp to None
        enricher = MetadataEnricher(use_slm=False)
        enricher.nlp = None
        assert enricher.extract_entities_spacy("some text") == []

    def test_extract_entities_with_mock_spacy(self):
        enricher = MetadataEnricher(use_slm=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent1 = MagicMock()
        mock_ent1.text = "John"
        mock_ent1.label_ = "PERSON"
        mock_ent2 = MagicMock()
        mock_ent2.text = "Acme Corp"
        mock_ent2.label_ = "ORG"
        mock_doc.ents = [mock_ent1, mock_ent2]
        mock_nlp.return_value = mock_doc
        enricher.nlp = mock_nlp
        entities = enricher.extract_entities_spacy("John works at Acme Corp")
        assert len(entities) >= 1
        assert "John" in entities


class TestMetadataEnricherSummary:
    def test_generate_summary_short_text(self):
        enricher = MetadataEnricher()
        result = enricher.generate_summary("Short text.")
        assert result == "Short text."

    def test_generate_summary_long_text(self):
        enricher = MetadataEnricher()
        text = "First sentence. Second sentence. Third sentence. Fourth."
        result = enricher.generate_summary(text)
        assert result.endswith("...")
        assert "First sentence." in result


class TestMetadataEnricherHypotheticalQuestions:
    def test_generate_questions(self):
        enricher = MetadataEnricher()
        text = "Как настроить систему? Почему мы используем это? Что такое RAG?"
        questions = enricher.generate_hypothetical_questions(text)
        assert isinstance(questions, list)
        assert len(questions) <= 3

    def test_generate_questions_no_matches(self):
        enricher = MetadataEnricher()
        text = "This is plain text without Russian question words."
        questions = enricher.generate_hypothetical_questions(text)
        assert questions == []


class TestMDKeyChunkerProcessDocument:
    def test_process_html_document(self):
        chunker = SemanticChunker(max_tokens=800)
        enricher = MetadataEnricher(use_slm=False)
        enricher.nlp = None
        md_key = MDKeyChunker(chunker, enricher)
        html = "<h1>RAG</h1><p>Retrieval-Augmented Generation.</p>"
        metadata = {"source_type": "wiki", "doc_title": "RAG Overview", "source_id": "1"}
        chunks = md_key.process_document(html, "html", metadata)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source_type == "wiki"

    def test_process_markdown_document(self):
        chunker = SemanticChunker(max_tokens=800)
        enricher = MetadataEnricher(use_slm=False)
        enricher.nlp = None
        md_key = MDKeyChunker(chunker, enricher)
        md = "# Title\n\nContent."
        metadata = {"source_type": "gitlab"}
        chunks = md_key.process_document(md, "markdown", metadata)
        assert len(chunks) >= 1


class TestMDKeyChunkerPackBySemanticKey:
    def test_pack_no_semantic_keys(self):
        chunker = SemanticChunker()
        enricher = MetadataEnricher()
        enricher.nlp = None
        md_key = MDKeyChunker(chunker, enricher)
        chunks = [
            Chunk(text="a", hash="a1", source_type="wiki"),
            Chunk(text="b", hash="b1", source_type="wiki"),
        ]
        packed = md_key._pack_by_semantic_key(chunks)
        assert len(packed) == 2

    def test_pack_with_same_semantic_key(self):
        chunker = SemanticChunker()
        enricher = MetadataEnricher()
        enricher.nlp = None
        md_key = MDKeyChunker(chunker, enricher)
        chunks = [
            Chunk(text="a", hash="a1", semantic_key="group1", source_type="wiki"),
            Chunk(text="b", hash="b1", semantic_key="group1", source_type="wiki"),
        ]
        packed = md_key._pack_by_semantic_key(chunks)
        assert len(packed) == 1
        assert "a" in packed[0].text
        assert "b" in packed[0].text


class TestSaveChunksToJson:
    def test_save_chunks_to_json(self, tmp_path):
        chunks = [
            Chunk(
                text="chunk text",
                hash="abc123",
                keywords=["test"],
                entities=["ORG:Acme"],
                hypothetical_questions=["What is this?"],
                source_type="wiki",
            )
        ]
        output = tmp_path / "chunks.json"
        save_chunks_to_json(chunks, output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "chunk text"
        assert data[0]["hash"] == "abc123"
