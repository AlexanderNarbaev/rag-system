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
