# Extensibility Guide: Adding New Data Sources

This guide describes how to extend the RAG system with new data sources — from writing a custom
extractor to configuring chunking, entity extraction, and incremental indexing.

---

## 1. Plugin Architecture for Extractors

Every extractor must implement the `BaseExtractor` abstract interface. The orchestrator in
`etl/scheduler/run_etl.py` discovers and invokes extractors via config-driven dispatch.

```python
# etl/extractors/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
import json

class BaseExtractor(ABC):
    """Abstract base for all data source extractors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.output_dir = Path(config.get("output_dir", "./raw_data/unknown"))
        self.wal_path = Path(config.get("wal_file", "./wal/extractor_wal.json"))
        self.incremental = config.get("incremental", True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_data = self._load_wal()

    def _load_wal(self) -> Dict:
        if self.wal_path.exists():
            with open(self.wal_path, "r") as f:
                return json.load(f)
        return {"last_run": None, "items_hash": {}}

    def _save_wal(self):
        with open(self.wal_path, "w") as f:
            json.dump(self.wal_data, f, indent=2, default=str)

    @abstractmethod
    def extract(self) -> Dict[str, Any]:
        """Extract documents. Returns doc dict with keys: id, source_type, title,
        content, content_type (html|markdown|text|code), metadata."""

    @abstractmethod
    def run(self):
        """Orchestrate full extraction: extract → save → WAL update."""
```

### Registration in run_etl.py

Add a new section in `etl/scheduler/run_etl.py`:

```python
from etl.extractors.book_extractor import BookExtractor

def run_extract_books(config: Dict, wal: WALManager) -> Path:
    logger.info("=== Starting Book extraction ===")
    book_config = config.get("books", {})
    book_config["wal_file"] = str(wal.wal_path)
    extractor = BookExtractor(book_config)
    extractor.run()
    wal.update_last_run("books")
    return Path(book_config.get("output_dir", "./raw_data/books"))
```

Then add a `books:` block to `etl/config/etl_config.yaml` and a `collect_books_documents()`
function to feed the chunking pipeline.

---

## 2. Adding New Source Types

### Books (EPUB, PDF, DOCX)

- **EPUB** — use `EbookLib` to parse `.epub`, extract chapters from `spine`/`toc`, preserve
  hierarchy (`part → chapter → section`). Strip HTML to plain text via `BeautifulSoup`.
- **PDF** — use `pypdf` for text extraction, `pdfplumber` for tables. Detect headings by font
  size heuristics. Chunk by section boundaries detected from TOC or heading patterns.
- **DOCX** — use `python-docx`, map `Heading 1–3` styles to structural hierarchy.

### BookExtractor Example (EPUB)

```python
# etl/extractors/book_extractor.py
from pathlib import Path
from typing import Dict, Any
from ebooklib import epub
from bs4 import BeautifulSoup
from etl.extractors.base import BaseExtractor

class BookExtractor(BaseExtractor):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.books_dir = Path(config.get("books_dir", "./books"))

    def extract(self) -> Dict[str, Any]:
        documents = {}
        for epub_path in self.books_dir.glob("*.epub"):
            book = epub.read_epub(str(epub_path))
            book_id = hashlib.sha256(epub_path.name.encode()).hexdigest()[:12]
            chapters = []
            for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
                soup = BeautifulSoup(item.get_content(), "html.parser")
                title = soup.find("h1")
                chapters.append({
                    "id": f"book_{book_id}_ch{len(chapters)}",
                    "title": title.text if title else epub_path.stem,
                    "content": soup.get_text(separator="\n"),
                    "content_type": "text",
                    "metadata": {
                        "book_title": epub_path.stem,
                        "section_index": len(chapters),
                        "source_file": str(epub_path)
                    }
                })
            documents[book_id] = {"source_type": "book", "chapters": chapters}
        return documents

    def run(self):
        docs = self.extract()
        out_file = self.output_dir / "books.json"
        with open(out_file, "w") as f:
            json.dump(docs, f, indent=2)
        self.wal_data["last_run"] = datetime.now().isoformat()
        self._save_wal()
```

### Documentation (Markdown, RST, AsciiDoc)

Parse with `mistletoe` (Markdown), `docutils` (RST), `asciidoctor` CLI (AsciiDoc). Preserve
code blocks with language tags, extract diagram descriptions (Mermaid/PlantUML) as structural
metadata.

### Chat History

Parse JSON exports from DeepSeek/ChatGPT/Claude. Thread conversations by `conversation_id`,
extract Q&A pairs (`user → assistant`), and enrich with `model_name`, `timestamp`, and token
counts as metadata. Each Q&A turn becomes a chunk.

### Code Repositories

Beyond GitLab commits, index source code with `tree-sitter`/`ast` for AST-aware chunking at
function/class boundaries. Embed commit messages as cross-references to affected code chunks.

---

## 3. Metadata Enrichment Pipeline

`MetadataEnricher` (in `etl/chunker/semantic_chunker.py`) enriches chunks using:

1. **TF-IDF** — extracts top-N keywords from chunk text.
2. **spaCy NER** — identifies PERSON, ORG, GPE, PRODUCT entities.
3. **SLM (Gemma-2B)** — generates hypothetical questions and summaries (optional).

To add source-type-specific enrichment, extend the `enrich()` method:

```python
def enrich(self, chunk: Chunk) -> Chunk:
    if chunk.source_type == "book":
        chunk.keywords = self._extract_book_keywords(chunk.text)  # TF-IDF tuned for prose
    elif chunk.source_type == "code":
        chunk.keywords = self._extract_code_symbols(chunk.text)   # function/class names
    # ... fall through to default
    return chunk
```

Custom metadata schemas are defined per source type in the config:

```yaml
books:
  metadata_schema:
    required: ["book_title", "author", "isbn", "chapter"]
    optional: ["publisher", "year", "language"]
```

---

## 4. Chunking Strategy per Source Type

`MDKeyChunker` splits documents by structural hierarchy (H1→H2→H3). Configure per source:

| Source    | Split On          | Overlap | Max Tokens |
|-----------|-------------------|---------|------------|
| Books     | Chapters, sections | 100    | 2000       |
| Code      | Functions, classes | 0      | 1000       |
| Chat      | Q&A turns          | 50     | 1500       |

Cross-reference linking embeds `parent_id` metadata so chunks from the same document or chapter
can be grouped during retrieval.

---

## 5. Version Tracking for New Sources

`HashVersioning` computes SHA-256 over chunk text + metadata (see `compute_chunk_hash()` in
`etl/chunker/hash_versioning.py`). For new sources:

- **Books** — hash over `(chapter text, book_title, chapter_index)`. Changes trigger re-chunk.
- **Code** — hash over `(function source, file_path)`. Only re-index changed functions.
- **Decision logic**: if `incremental=True`, compare hashes; if only metadata changed
  (e.g., added keyword), update in place without recomputing embeddings.

---

## 6. Graph Building for New Sources

`EntityRelationExtractor` extracts entities per source type. Customize with a configurable
entity map:

```yaml
graph:
  entity_types:
    book: [AUTHOR, BOOK, CHARACTER, CONCEPT, TOPIC]
    code: [CLASS, FUNCTION, MODULE, IMPORT, PATTERN]
    chat: [PERSON, TOPIC, DECISION, ACTION_ITEM]
```

Cross-source relationships (e.g., linking a Confluence page about "Auth Service" to GitLab
code that implements it) use `RELATES_TO` edges with `source_type` metadata on the edge.
