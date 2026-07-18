# tests/etl/test_semantic_chunker.py
import json
from unittest.mock import MagicMock, patch

from etl.chunker.semantic_chunker import (
    AdaptiveChunker,
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
        chunker = SemanticChunker(max_tokens=1500)
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
        chunker = SemanticChunker(max_tokens=1500)
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
            ),
        ]
        output = tmp_path / "chunks.json"
        save_chunks_to_json(chunks, output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "chunk text"
        assert data[0]["hash"] == "abc123"


class TestAdaptiveChunkerInit:
    def test_default_construction(self):
        chunker = AdaptiveChunker()
        assert chunker.min_chunk_size == 200
        assert chunker.max_chunk_size == 2000
        assert chunker.target_chunk_size == 800
        assert chunker.overlap_ratio == 0.15

    def test_custom_construction(self):
        chunker = AdaptiveChunker(
            min_chunk_size=100,
            max_chunk_size=1000,
            target_chunk_size=500,
            overlap_ratio=0.2,
        )
        assert chunker.min_chunk_size == 100
        assert chunker.target_chunk_size == 500
        assert chunker.overlap_ratio == 0.2


class TestAdaptiveChunkerDetectStructure:
    def test_header_detection(self):
        chunker = AdaptiveChunker()
        text = "# Main Title\nSome content.\n## Subtitle\nMore content."
        elements = chunker._detect_structure(text)
        assert len(elements) >= 4
        types = [e["type"] for e in elements]
        assert "header" in types

    def test_header_levels(self):
        chunker = AdaptiveChunker()
        text = "### H3 Level\nContent under h3."
        elements = chunker._detect_structure(text)
        headers = [e for e in elements if e["type"] == "header"]
        assert len(headers) == 1
        assert headers[0]["level"] == 3

    def test_code_block_detection(self):
        chunker = AdaptiveChunker()
        text = "Before\n```python\nprint('hello')\nx = 1\n```\nAfter"
        elements = chunker._detect_structure(text)
        code_blocks = [e for e in elements if e["type"] == "code"]
        assert len(code_blocks) == 1
        assert "print" in code_blocks[0]["text"]

    def test_code_block_unclosed(self):
        chunker = AdaptiveChunker()
        text = "```\ncode without closing\n"
        elements = chunker._detect_structure(text)
        code_blocks = [e for e in elements if e["type"] == "code"]
        assert len(code_blocks) >= 1

    def test_table_detection(self):
        chunker = AdaptiveChunker()
        text = "| Col1 | Col2 |\n|------|------|\n| A    | B    |\n\nAfter table."
        elements = chunker._detect_structure(text)
        tables = [e for e in elements if e["type"] == "table"]
        assert len(tables) == 1
        assert "Col1" in tables[0]["text"]

    def test_paragraph_detection(self):
        chunker = AdaptiveChunker()
        text = "This is a simple paragraph.\n\nAnother paragraph."
        elements = chunker._detect_structure(text)
        paragraphs = [e for e in elements if e["type"] == "paragraph"]
        assert len(paragraphs) >= 2

    def test_empty_text(self):
        chunker = AdaptiveChunker()
        elements = chunker._detect_structure("")
        assert elements == []

    def test_mixed_content(self):
        chunker = AdaptiveChunker()
        text = """# Header
Some paragraph.

```python
code block
```

| A | B |
|---|---|
| 1 | 2 |

Final paragraph."""
        elements = chunker._detect_structure(text)
        types = {e["type"] for e in elements}
        assert "header" in types
        assert "code" in types
        assert "table" in types
        assert "paragraph" in types


class TestAdaptiveChunkerMergeSmallElements:
    def test_merge_small_paragraphs(self):
        chunker = AdaptiveChunker(min_chunk_size=10, target_chunk_size=200)
        elements = [
            {"type": "paragraph", "text": "Short.", "start": 0, "end": 6},
            {"type": "paragraph", "text": "Also short.", "start": 7, "end": 18},
            {"type": "paragraph", "text": "Long enough " + "x" * 50, "start": 19, "end": 70},
        ]
        merged = chunker._merge_small_elements(elements)
        assert len(merged) < len(elements)

    def test_headers_not_merged_with_previous(self):
        chunker = AdaptiveChunker(min_chunk_size=10, target_chunk_size=200)
        elements = [
            {"type": "paragraph", "text": "Content before header.", "start": 0, "end": 20},
            {"type": "header", "level": 2, "text": "## Section", "start": 21, "end": 31},
            {"type": "paragraph", "text": "Content after header.", "start": 32, "end": 52},
        ]
        merged = chunker._merge_small_elements(elements)
        assert len(merged) >= 2

    def test_empty_elements(self):
        chunker = AdaptiveChunker()
        assert chunker._merge_small_elements([]) == []

    def test_single_element(self):
        chunker = AdaptiveChunker()
        elements = [{"type": "paragraph", "text": "Only one.", "start": 0, "end": 9}]
        merged = chunker._merge_small_elements(elements)
        assert len(merged) == 1
        assert merged[0]["text"] == "Only one."

    def test_merge_below_min_size(self):
        chunker = AdaptiveChunker(min_chunk_size=100, target_chunk_size=200)
        elements = [
            {"type": "paragraph", "text": "Tiny.", "start": 0, "end": 5},
            {"type": "paragraph", "text": "Small.", "start": 6, "end": 12},
        ]
        merged = chunker._merge_small_elements(elements)
        assert len(merged) == 1

    def test_merge_stops_at_header(self):
        chunker = AdaptiveChunker(min_chunk_size=10, target_chunk_size=200)
        elements = [
            {"type": "paragraph", "text": "Larger paragraph here.", "start": 0, "end": 22},
            {"type": "header", "level": 1, "text": "# H1", "start": 23, "end": 27},
            {"type": "paragraph", "text": "Para2.", "start": 28, "end": 34},
        ]
        merged = chunker._merge_small_elements(elements)
        assert len(merged) >= 2


class TestAdaptiveChunkerSplitLargeChunks:
    def test_small_chunk_not_split(self):
        chunker = AdaptiveChunker(max_chunk_size=2000)
        elements = [{"type": "paragraph", "text": "Short text.", "start": 0, "end": 11}]
        result = chunker._split_large_chunks(elements)
        assert len(result) == 1
        assert result[0]["text"] == "Short text."

    def test_large_chunk_split_at_sentences(self):
        chunker = AdaptiveChunker(max_chunk_size=50, target_chunk_size=30)
        text = "First sentence is here. Second sentence goes here. Third one too."
        elements = [{"type": "paragraph", "text": text, "start": 0, "end": len(text)}]
        result = chunker._split_large_chunks(elements)
        assert len(result) >= 2

    def test_single_long_sentence_not_splittable(self):
        chunker = AdaptiveChunker(max_chunk_size=20, target_chunk_size=10)
        text = "NoPunctuationMakesOneSentence " * 5
        elements = [{"type": "paragraph", "text": text.strip(), "start": 0, "end": len(text)}]
        result = chunker._split_large_chunks(elements)
        assert len(result) >= 1

    def test_empty_result_for_empty_input(self):
        chunker = AdaptiveChunker()
        assert chunker._split_large_chunks([]) == []


class TestAdaptiveChunkerApplyOverlap:
    def test_no_overlap_when_disabled(self):
        chunker = AdaptiveChunker(overlap_ratio=0.0)
        chunks = [
            {"type": "paragraph", "text": "Chunk one.", "start": 0, "end": 10},
            {"type": "paragraph", "text": "Chunk two.", "start": 11, "end": 21},
        ]
        result = chunker._apply_overlap(chunks)
        assert len(result) == 2
        assert "previous context" not in result[0]["text"]

    def test_overlap_adds_context_prefix(self):
        chunker = AdaptiveChunker(overlap_ratio=0.3)
        chunks = [
            {"type": "paragraph", "text": "First chunk which has more text.", "start": 0, "end": 30},
            {"type": "paragraph", "text": "Second chunk text.", "start": 31, "end": 50},
        ]
        result = chunker._apply_overlap(chunks)
        assert "[previous context" in result[1]["text"]

    def test_single_chunk_no_overlap(self):
        chunker = AdaptiveChunker(overlap_ratio=0.5)
        chunks = [{"type": "paragraph", "text": "Only chunk.", "start": 0, "end": 11}]
        result = chunker._apply_overlap(chunks)
        assert len(result) == 1
        assert "previous context" not in result[0]["text"]


class TestAdaptiveChunkerChunk:
    def test_chunk_plain_text(self):
        chunker = AdaptiveChunker(
            min_chunk_size=10,
            max_chunk_size=2000,
            target_chunk_size=500,
            overlap_ratio=0.1,
        )
        text = "# Title\n\nFirst paragraph with enough text to be a chunk.\n\nAnother chunk of content."
        result = chunker.chunk(text)
        assert len(result) >= 1
        for r in result:
            assert "text" in r
            assert "type" in r
            assert "start" in r
            assert "end" in r

    def test_chunk_with_code_and_tables(self):
        chunker = AdaptiveChunker(
            max_chunk_size=5000,
            target_chunk_size=2000,
            overlap_ratio=0.1,
        )
        text = """# Header

Some paragraph here.

```python
x = 1
y = 2
```

| A | B |
|---|---|
| 1 | 2 |

Final text here with more words to ensure separation."""
        result = chunker.chunk(text)
        assert len(result) >= 1

    def test_chunk_long_document(self):
        chunker = AdaptiveChunker(
            min_chunk_size=50,
            max_chunk_size=500,
            target_chunk_size=200,
            overlap_ratio=0.1,
        )
        text = "# Long Document\n\n" + ("Some paragraph with reasonable length. " * 50)
        result = chunker.chunk(text)
        assert len(result) >= 5


class TestAdaptiveChunkerChunkMarkdown:
    def test_chunk_markdown_simple(self):
        chunker = AdaptiveChunker(max_chunk_size=2000)
        md = "# Title\n\nContent here.\n\n## Section\n\nMore text."
        chunks = chunker.chunk_markdown(md)
        assert len(chunks) >= 1
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.text
            assert c.hash

    def test_chunk_markdown_with_metadata(self):
        chunker = AdaptiveChunker(max_chunk_size=2000)
        md = "# Doc\n\nSome content."
        metadata = {
            "source_type": "gitlab",
            "source_id": "repo1",
            "version": "v1.0",
            "doc_title": "README",
        }
        chunks = chunker.chunk_markdown(md, metadata)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source_type == "gitlab"
            assert c.source_id == "repo1"
            assert c.doc_title == "README"
            assert c.version == "v1.0"

    def test_chunk_markdown_positions(self):
        chunker = AdaptiveChunker(max_chunk_size=2000)
        md = "# One\n\nFirst.\n\n## Two\n\nSecond.\n\n# Three\n\nThird."
        chunks = chunker.chunk_markdown(md)
        positions = [c.position for c in chunks]
        assert positions == sorted(positions)
        assert len(set(positions)) == len(chunks)

    def test_chunk_markdown_empty(self):
        chunker = AdaptiveChunker()
        chunks = chunker.chunk_markdown("")
        assert chunks == []

    def test_chunk_markdown_single_para(self):
        chunker = AdaptiveChunker(max_chunk_size=2000)
        md = "Just a single paragraph with no headings."
        chunks = chunker.chunk_markdown(md)
        assert len(chunks) == 1
        assert "single paragraph" in chunks[0].text


class TestMetadataEnricherEnrichWithSlm:
    def test_enrich_with_slm_disabled(self):
        enricher = MetadataEnricher(use_slm=False)
        result = enricher.enrich_with_slm("some text")
        assert result == {}

    def test_enrich_with_slm_success(self):
        enricher = MetadataEnricher(use_slm=True, slm_endpoint="http://localhost:8000/slm")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "text": '{"summary": "A summary", "keywords": ["k1", "k2"], "questions": ["Q1?"]}'
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_resp
            result = enricher.enrich_with_slm("test text")
        assert result["summary"] == "A summary"
        assert "k1" in result["keywords"]
        assert len(result["hypothetical_questions"]) >= 1

    def test_enrich_with_slm_http_error(self):
        enricher = MetadataEnricher(use_slm=True, slm_endpoint="http://localhost:8000/slm")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_resp
            result = enricher.enrich_with_slm("test text")
        assert result == {}

    def test_enrich_with_slm_network_error(self):
        enricher = MetadataEnricher(use_slm=True, slm_endpoint="http://localhost:8000/slm")
        with patch("requests.post") as mock_post:
            mock_post.side_effect = ConnectionError("unreachable")
            result = enricher.enrich_with_slm("test text")
        assert result == {}

    def test_enrich_with_slm_invalid_json_response(self):
        enricher = MetadataEnricher(use_slm=True, slm_endpoint="http://localhost:8000/slm")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "not valid json at all"}
        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_resp
            result = enricher.enrich_with_slm("test text")
        assert result == {}


class TestHtmlToMarkdownConversion:
    """Tests for HTML → Markdown conversion."""

    def test_html_to_markdown_basic(self):
        chunker = SemanticChunker()
        html = "<h1>Title</h1><p>Some paragraph.</p>"
        md = chunker._html_to_markdown(html)
        assert "# Title" in md
        assert "Some paragraph." in md

    def test_html_to_markdown_tables(self):
        chunker = SemanticChunker()
        html = "<table><tr><th>Col1</th><th>Col2</th></tr><tr><td>A</td><td>B</td></tr></table>"
        md = chunker._html_to_markdown(html)
        assert "Col1" in md
        assert "Col2" in md

    def test_html_to_markdown_lists(self):
        chunker = SemanticChunker()
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        md = chunker._html_to_markdown(html)
        assert "- " in md
        assert "Item 1" in md

    def test_html_to_markdown_links(self):
        chunker = SemanticChunker()
        html = '<a href="http://example.com">Click here</a>'
        md = chunker._html_to_markdown(html)
        assert "Click here" in md
        assert "http://example.com" in md

    def test_html_to_markdown_strips_images_scripts_styles(self):
        chunker = SemanticChunker()
        html = "<p>Visible</p><img src='x.png' alt='photo'/><script>alert('xss')</script><style>body{}</style>"
        md = chunker._html_to_markdown(html)
        assert "Visible" in md
        assert "photo" not in md  # img tag stripped, alt text removed


class TestSplitMarkdownByHeadings:
    """Tests for _split_markdown_by_headings."""

    def test_split_markdown_by_headings(self):
        chunker = SemanticChunker()
        md = "# H1\nContent under h1.\n\n## H2\nContent under h2."
        sections = chunker._split_markdown_by_headings(md)
        assert len(sections) == 2
        assert sections[0]["heading"] == "H1"
        assert sections[0]["level"] == 1
        assert sections[1]["heading"] == "H2"
        assert sections[1]["level"] == 2

    def test_split_markdown_with_h3(self):
        chunker = SemanticChunker()
        md = "### H3\nContent under h3."
        sections = chunker._split_markdown_by_headings(md)
        assert len(sections) == 1
        assert sections[0]["heading"] == "H3"
        assert sections[0]["level"] == 3

    def test_split_markdown_no_headings(self):
        chunker = SemanticChunker()
        md = "Just plain text without any headings."
        sections = chunker._split_markdown_by_headings(md)
        assert len(sections) == 1
        assert sections[0]["heading"] == "root"

    def test_split_markdown_empty(self):
        chunker = SemanticChunker()
        sections = chunker._split_markdown_by_headings("")
        assert len(sections) == 1
        assert sections[0]["heading"] == "root"
        assert sections[0]["content"] == ""

    def test_split_markdown_preserves_section_content(self):
        chunker = SemanticChunker()
        md = "# Section 1\n\nContent one.\n\n# Section 2\n\nContent two."
        sections = chunker._split_markdown_by_headings(md)
        assert len(sections) == 2
        assert "Content one." in sections[0]["content"]
        assert "Content two." in sections[1]["content"]

    def test_split_markdown_h4_ignored(self):
        chunker = SemanticChunker()
        md = "#### H4\nNot a heading level we chunk on."
        sections = chunker._split_markdown_by_headings(md)
        assert len(sections) == 1
        assert sections[0]["heading"] == "root"


class TestChunkMarkdownWithOverlap:
    """Tests for chunk_markdown_with_overlap."""

    def test_chunk_markdown_basic(self):
        chunker = SemanticChunker(max_tokens=1500)
        md = "# Title\n\nSome content here.\n\n## Section\n\nMore text."
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) >= 1
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.hash

    def test_chunk_markdown_with_metadata(self):
        chunker = SemanticChunker(max_tokens=1500)
        md = "# Doc\n\nContent."
        metadata = {"source_type": "wiki", "doc_title": "Test Doc"}
        chunks = chunker.chunk_markdown_with_overlap(md, metadata)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source_type == "wiki"
            assert c.doc_title == "Test Doc"

    def test_chunk_markdown_overlap_preserves_context(self):
        chunker = SemanticChunker(max_tokens=10, overlap_tokens=5)
        md = "# Section\n\n" + "word " * 50
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) > 1
        assert "[previous context" in chunks[1].text

    def test_chunk_markdown_empty(self):
        chunker = SemanticChunker()
        chunks = chunker.chunk_markdown_with_overlap("")
        assert len(chunks) == 0

    def test_chunk_markdown_preserves_headings_in_chunks(self):
        chunker = SemanticChunker(max_tokens=1500)
        md = "# Overview\n\nBrief intro.\n\n## Details\n\nSpecific info."
        chunks = chunker.chunk_markdown_with_overlap(md)
        assert len(chunks) >= 1
        texts = [c.text for c in chunks]
        joined = " ".join(texts)
        assert "# Overview" in joined
        assert "## Details" in joined


class TestExtractHeadings:
    """Tests for heading extraction from HTML."""

    def test_extract_headings_basic(self):
        chunker = SemanticChunker()
        html = "<h1>Title</h1><p>content</p><h2>Section</h2><p>more</p>"
        headings = chunker.extract_headings(html)
        assert len(headings) == 2
        assert headings[0]["text"] == "Title"
        assert headings[0]["level"] == 1
        assert headings[1]["text"] == "Section"
        assert headings[1]["level"] == 2

    def test_extract_headings_with_ids(self):
        chunker = SemanticChunker()
        html = '<h1 id="overview">Overview</h1><h2 id="details">Details</h2>'
        headings = chunker.extract_headings(html)
        assert len(headings) == 2
        assert headings[0]["anchor_id"] == "overview"
        assert headings[1]["anchor_id"] == "details"

    def test_extract_headings_no_headings(self):
        chunker = SemanticChunker()
        html = "<p>No headings here.</p>"
        headings = chunker.extract_headings(html)
        assert headings == []

    def test_extract_headings_empty(self):
        chunker = SemanticChunker()
        html = ""
        headings = chunker.extract_headings(html)
        assert headings == []


class TestBuildHeadingTree:
    """Tests for _build_heading_tree."""

    def test_build_heading_tree_flat(self):
        chunker = SemanticChunker()
        headings = [
            {"text": "A", "level": 1, "anchor_id": ""},
            {"text": "B", "level": 1, "anchor_id": ""},
        ]
        tree = chunker._build_heading_tree(headings)
        assert len(tree) == 2
        assert tree[0]["text"] == "A"
        assert tree[1]["text"] == "B"

    def test_build_heading_tree_nested(self):
        chunker = SemanticChunker()
        headings = [
            {"text": "A", "level": 1, "anchor_id": ""},
            {"text": "A1", "level": 2, "anchor_id": ""},
            {"text": "A2", "level": 2, "anchor_id": ""},
            {"text": "B", "level": 1, "anchor_id": ""},
        ]
        tree = chunker._build_heading_tree(headings)
        assert len(tree) == 2
        assert len(tree[0]["children"]) == 2
        assert tree[0]["children"][0]["text"] == "A1"
        assert tree[0]["children"][1]["text"] == "A2"

    def test_build_heading_tree_deep_nested(self):
        chunker = SemanticChunker()
        headings = [
            {"text": "H1", "level": 1, "anchor_id": ""},
            {"text": "H2", "level": 2, "anchor_id": ""},
            {"text": "H3", "level": 3, "anchor_id": ""},
        ]
        tree = chunker._build_heading_tree(headings)
        assert len(tree) == 1
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["text"] == "H2"
        assert tree[0]["children"][0]["children"][0]["text"] == "H3"

    def test_build_heading_tree_empty(self):
        chunker = SemanticChunker()
        tree = chunker._build_heading_tree([])
        assert tree == []


class TestCreateHeadingChunks:
    """Tests for create_heading_chunks."""

    def test_create_heading_chunks_basic(self):
        chunker = SemanticChunker()
        html = "<h1>Main</h1><p>text</p><h2>Sub</h2><p>more</p>"
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_1",
            "doc_title": "Test Page",
            "version": "2.0",
        }
        chunks = chunker.create_heading_chunks(html, source_metadata)
        assert len(chunks) == 2
        for c in chunks:
            assert c.source_type == "heading"
            assert c.source_id == "page_1"
            assert c.doc_title == "Test Page"

    def test_create_heading_chunks_with_child_headings(self):
        chunker = SemanticChunker()
        html = "<h1>Parent</h1><p>x</p><h2>Child1</h2><p>x</p><h2>Child2</h2><p>x</p>"
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_2",
            "doc_title": "Parent Page",
        }
        chunks = chunker.create_heading_chunks(html, source_metadata)
        assert len(chunks) == 3
        parent = chunks[0]
        assert parent.title == "Parent"
        assert "Child1" in parent.text
        assert "Child2" in parent.text
        assert "Sections:" in parent.text

    def test_create_heading_chunks_no_headings(self):
        chunker = SemanticChunker()
        html = "<p>No headings.</p>"
        source_metadata = {"source_type": "confluence"}
        chunks = chunker.create_heading_chunks(html, source_metadata)
        assert chunks == []

    def test_create_heading_chunks_metadata_stored(self):
        chunker = SemanticChunker()
        html = "<h1 id='intro'>Intro</h1><p>text</p>"
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_3",
            "doc_title": "Metadata Page",
        }
        chunks = chunker.create_heading_chunks(html, source_metadata)
        assert len(chunks) == 1
        pm = chunks[0].parent_metadata
        assert pm["heading_text"] == "Intro"
        assert pm["heading_level"] == 1
        assert pm["anchor_id"] == "intro"
        assert pm["page_id"] == "page_3"
        assert pm["page_title"] == "Metadata Page"


class TestCreateDocumentChunk:
    """Tests for create_document_chunk."""

    def test_create_document_chunk_basic(self):
        chunker = SemanticChunker()
        md = "# Page Title\n\nFirst paragraph with some content."
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_1",
            "doc_title": "Page Title",
        }
        doc_chunk = chunker.create_document_chunk(md, source_metadata)
        assert doc_chunk is not None
        assert doc_chunk.source_type == "document"
        assert doc_chunk.source_id == "page_1"
        assert doc_chunk.doc_title == "Page Title"
        assert "# Page Title" in doc_chunk.text
        assert "First paragraph" in doc_chunk.text

    def test_create_document_chunk_long_content_truncated(self):
        chunker = SemanticChunker()
        long_text = "x" * 1000
        md = f"# Title\n\n{long_text}"
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_2",
            "doc_title": "Title",
        }
        doc_chunk = chunker.create_document_chunk(md, source_metadata)
        assert doc_chunk is not None
        assert doc_chunk.text.endswith("...")
        assert len(doc_chunk.text) < len(long_text) + 100

    def test_create_document_chunk_empty_content(self):
        chunker = SemanticChunker()
        md = ""
        source_metadata = {
            "source_type": "confluence",
            "source_id": "empty",
            "doc_title": "Empty Page",
        }
        doc_chunk = chunker.create_document_chunk(md, source_metadata)
        assert doc_chunk is not None
        assert "Empty Page" in doc_chunk.text

    def test_create_document_chunk_preserves_metadata(self):
        chunker = SemanticChunker()
        md = "# Doc\n\nContent."
        source_metadata = {
            "source_type": "confluence",
            "source_id": "page_3",
            "doc_title": "Doc",
        }
        doc_chunk = chunker.create_document_chunk(md, source_metadata)
        assert doc_chunk is not None
        pm = doc_chunk.parent_metadata
        assert pm["page_id"] == "page_3"
        assert pm["page_title"] == "Doc"


class TestChunkHtmlWithMarkdownConversion:
    """Tests for chunk_html with HTML→Markdown conversion."""

    def test_chunk_html_preserves_table_structure(self):
        chunker = SemanticChunker(max_tokens=2000)
        html = (
            "<h1>Table Section</h1><table><tr><th>Name</th><th>Value</th></tr><tr><td>Alpha</td><td>1</td></tr></table>"
        )
        metadata = {"source_type": "confluence", "doc_title": "Table Doc"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        all_text = " ".join(c.text for c in chunks)
        assert "Name" in all_text
        assert "Alpha" in all_text

    def test_chunk_html_preserves_lists(self):
        chunker = SemanticChunker(max_tokens=2000)
        html = "<h1>List Section</h1><ul><li>First item</li><li>Second item</li></ul>"
        metadata = {"source_type": "confluence", "doc_title": "List Doc"}
        chunks = chunker.chunk_html(html, metadata)
        all_text = " ".join(c.text for c in chunks)
        assert "First item" in all_text
        assert "Second item" in all_text

    def test_chunk_html_preserves_links(self):
        chunker = SemanticChunker(max_tokens=2000)
        html = '<h1>Links</h1><p>See <a href="http://wiki/page">this page</a> for details.</p>'
        metadata = {"source_type": "confluence", "doc_title": "Links Doc"}
        chunks = chunker.chunk_html(html, metadata)
        all_text = " ".join(c.text for c in chunks)
        assert "this page" in all_text


class TestFindAnchorId:
    """Tests for _find_anchor_id."""

    def test_find_anchor_from_element_id(self):
        from bs4 import BeautifulSoup

        chunker = SemanticChunker()
        soup = BeautifulSoup('<h2 id="section-id">Section</h2>', "html.parser")
        elem = soup.find("h2")
        anchor = chunker._find_anchor_id(elem)
        assert anchor == "section-id"

    def test_find_anchor_no_id(self):
        from bs4 import BeautifulSoup

        chunker = SemanticChunker()
        soup = BeautifulSoup("<h2>No Anchor</h2>", "html.parser")
        elem = soup.find("h2")
        anchor = chunker._find_anchor_id(elem)
        assert anchor == ""


class TestSemanticChunkerEdgeCases:
    """Edge case tests for SemanticChunker."""

    def test_html_empty_content(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = ""
        metadata = {"source_type": "confluence", "doc_title": "Empty Page"}
        chunks = chunker.chunk_html(html, metadata)
        assert chunks == []

    def test_html_whitespace_only(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = "   \n  \n   "
        metadata = {"source_type": "confluence"}
        chunks = chunker.chunk_html(html, metadata)
        assert chunks == []

    def test_html_only_scripts_and_styles(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = "<script>console.log('xss')</script><style>body{color:red}</style>"
        metadata = {"source_type": "confluence", "doc_title": "Script Only"}
        chunks = chunker.chunk_html(html, metadata)
        for c in chunks:
            assert "<script" not in c.text
            assert "<style" not in c.text

    def test_html_deeply_nested_tables(self):
        chunker = SemanticChunker(max_tokens=5000)
        html = """
        <h1>Nested Tables</h1>
        <table>
            <tr><th>Outer</th></tr>
            <tr><td>
                <table>
                    <tr><th>Inner A</th><th>Inner B</th></tr>
                    <tr><td>Val 1</td><td>Val 2</td></tr>
                    <tr><td>
                        <table>
                            <tr><th>Deep Head</th></tr>
                            <tr><td>Deep Value</td></tr>
                        </table>
                    </td></tr>
                </table>
            </td></tr>
        </table>
        """
        metadata = {"source_type": "confluence", "doc_title": "Deep Tables"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        all_text = " ".join(c.text for c in chunks)
        assert "Outer" in all_text
        assert "Inner A" in all_text
        assert "Deep Value" in all_text

    def test_html_non_latin_content_cyrillic(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = (
            "<h1>Быстродействие системы</h1>"
            "<p>Техническая документация по оптимизации производительности.</p>"
            "<h2>Кэширование</h2><p>Использование Redis для кэширования запросов.</p>"
        )
        metadata = {"source_type": "confluence", "doc_title": "Техническая документация"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        all_text = " ".join(c.text for c in chunks)
        assert "Быстродействие" in all_text
        assert "Кэширование" in all_text
        for c in chunks:
            assert c.tokens_approx > 0

    def test_html_non_latin_content_cjk(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = "<h1>システム概要</h1><p>このドキュメントでは、システムの全体的なアーキテクチャについて説明します。</p>"
        metadata = {"source_type": "confluence", "doc_title": "システム概要"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        all_text = " ".join(c.text for c in chunks)
        assert "システム概要" in all_text
        for c in chunks:
            assert c.tokens_approx > 0

    def test_html_mixed_latin_and_non_latin(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = "<h1>RAG System / RAG система</h1><p>This document describes RAG for English and русский text.</p>"
        metadata = {"source_type": "confluence", "doc_title": "Mixed Content"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1
        all_text = " ".join(c.text for c in chunks)
        assert "RAG" in all_text
        assert "русский" in all_text

    def test_boundary_max_tokens_one_token(self):
        chunker = SemanticChunker(max_tokens=1, overlap_tokens=0)
        html = "<h1>Title</h1><p>word1 word2 word3 word4 word5</p>"
        metadata = {"source_type": "confluence"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) >= 1

    def test_boundary_max_tokens_very_large(self):
        chunker = SemanticChunker(max_tokens=100000)
        html = "<h1>Huge Limit</h1><p>This should all fit in one chunk.</p>"
        metadata = {"source_type": "confluence"}
        chunks = chunker.chunk_html(html, metadata)
        assert len(chunks) == 1

    def test_chunk_markdown_empty_string(self):
        chunker = SemanticChunker()
        chunks = chunker.chunk_markdown_with_overlap("")
        assert len(chunks) == 0

    def test_chunk_html_empty_source_metadata(self):
        chunker = SemanticChunker(max_tokens=1500)
        html = "<h1>Test</h1><p>Content.</p>"
        chunks = chunker.chunk_html(html, {})
        assert len(chunks) >= 1

    def test_prepend_context_with_all_fields(self):
        chunker = SemanticChunker()
        metadata = {
            "doc_title": "My Doc",
            "source_type": "confluence",
        }
        text = "Some chunk content."
        result = chunker._prepend_context(text, metadata)
        assert "Document: My Doc" in result
        assert "Source: confluence" in result
        assert "Some chunk content." in result

    def test_prepend_context_with_section_title(self):
        chunker = SemanticChunker()
        metadata = {
            "doc_title": "Doc",
            "section_title": "Section 1",
            "source_type": "wiki",
        }
        result = chunker._prepend_context("Content", metadata)
        assert "Section: Section 1" in result

    def test_prepend_context_empty_metadata(self):
        chunker = SemanticChunker()
        result = chunker._prepend_context("Just content", {})
        assert result == "Just content"

    def test_estimate_tokens_non_latin_cyrillic(self):
        chunker = SemanticChunker()
        tokens = chunker._estimate_tokens("Привет мир это тест")
        assert tokens >= 1

    def test_estimate_tokens_non_latin_cjk(self):
        chunker = SemanticChunker()
        tokens = chunker._estimate_tokens("こんにちは世界")
        assert tokens >= 1
