# etl/chunker/semantic_chunker.py
"""Семантический чанкинг для RAG-системы.
Реализует MDKeyChunker (Semantic Chunker) с извлечением метаданных и каскадированием.
Поддерживает HTML и Markdown, LLM-обогащение (опционально).
Добавлены: HTML→Markdown конвертация, heading-level indexing, document-level embedding.
"""

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Для парсинга HTML и Markdown
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]
try:
    import markdown
except ImportError:
    markdown = None

# HTML→Markdown конвертер
try:
    import markdownify

    MARKDOWNIFY_AVAILABLE = True
except ImportError:
    MARKDOWNIFY_AVAILABLE = False

# Для NLP (опционально)
try:
    import spacy

    NLP_AVAILABLE = True
except ImportError:
    NLP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Структура чанка с метаданными."""

    text: str
    hash: str
    title: str = ""
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    hypothetical_questions: list[str] = field(default_factory=list)
    semantic_key: str = ""  # для группировки
    source_type: str = ""  # confluence, jira, gitlab
    source_id: str = ""  # page_id, issue_key, commit_sha
    version: str = ""  # версия документа
    doc_title: str = ""  # оригинальный заголовок документа
    parent_metadata: dict[str, Any] = field(default_factory=dict)  # унаследованные метаданные
    position: int = 0  # порядковый номер в документе
    tokens_approx: int = 0  # примерное количество токенов
    original_text: str = ""  # текст без контекстного префикса (для отображения)
    enriched: bool = False  # был ли чанк обогащён контекстом
    access_level: str = "public"  # public, internal, confidential, restricted
    allowed_groups: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)


class SemanticChunker:
    """Базовый семантический чанкер. Разбивает документ на структурные блоки:
    заголовки (h1-h3), абзацы, списки, таблицы. Поддерживает HTML и Markdown.
    """

    def __init__(
        self,
        max_tokens: int = 1500,
        overlap_tokens: int = 200,
        min_chunk_tokens: int = 100,
        contextual_enrichment: bool = True,
    ):
        """:param max_tokens: максимальное количество токенов в чанке (для эмбеддера)
                           Research-backed optimal: 1500 tokens (~6000 chars) for retrieval quality.
                           See: https://habr.com/ru/articles/1029740/
        :param overlap_tokens: перекрытие между чанками (токены)
                                200 tokens (~800 chars, ~13% overlap) for context continuity.
        :param min_chunk_tokens: минимальный размер чанка, иначе объединяется со следующим
        :param contextual_enrichment: enable ContextualEnricher for each chunk
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.contextual_enricher = ContextualEnricher(enabled=contextual_enrichment)

    def _estimate_tokens(self, text: str) -> int:
        """Language-aware token estimation.

        BPE tokenization ratios vary by script:
        - Latin scripts (English, etc.): ~4 chars/token
        - Cyrillic scripts (Russian, etc.): ~3 chars/token (UTF-8 multibyte)
        - CJK scripts: ~1.5 chars/token
        - Mixed text: weighted average based on script detection.

        Uses character-script classification to choose the appropriate ratio.
        For multilingual models (bge-m3, multilingual-e5), Cyrillic and CJK
        consume more tokens per character than Latin text.
        """
        if not text:
            return 0

        cyrillic = 0
        latin = 0
        cjk = 0
        other = 0

        for ch in text:
            cp = ord(ch)
            if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
                cyrillic += 1
            elif (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
                latin += 1
            elif (
                (0x4E00 <= cp <= 0x9FFF)
                or (0x3040 <= cp <= 0x309F)
                or (0x30A0 <= cp <= 0x30FF)
                or (0xAC00 <= cp <= 0xD7AF)
            ):
                cjk += 1
            else:
                other += 1
        weighted_ratio = cyrillic / 3.0 + latin / 4.0 + cjk / 1.5 + other / 4.0
        return max(1, int(weighted_ratio))

    def _html_to_markdown(self, html: str) -> str:
        """Convert Confluence HTML to clean Markdown.

        Preserves structure: headings as # ## ###, tables as Markdown tables,
        links as [text](url), lists as - item. Strips scripts, styles, images.
        """
        if not MARKDOWNIFY_AVAILABLE:
            raise ImportError("markdownify is required for HTML→Markdown conversion. Install: pip install markdownify")
        md = markdownify.markdownify(
            html,
            heading_style="ATX",  # # Heading 1, ## Heading 2
            bullets="-",
            strip=["img", "script", "style"],
        )
        return md

    def _split_markdown_by_headings(self, md_text: str) -> list[dict[str, Any]]:
        """Split Markdown text into sections by ATX headings (#, ##, ###).
        Returns list of {heading: str, level: int, content: str}
        """
        heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(heading_re.finditer(md_text))
        if not matches:
            return [{"heading": "root", "level": 0, "content": md_text.strip()}]

        sections = []
        for i, match in enumerate(matches):
            level = len(match.group(1))
            heading = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
            content = md_text[start:end].strip()
            sections.append({"heading": heading, "level": level, "content": content})

        return sections

    def _split_by_headings(self, html: str) -> list[dict[str, Any]]:
        """Разбивает HTML на секции по заголовкам — преобразует HTML в Markdown и разбивает.
        Возвращает список {heading: str, content: str}
        """
        if MARKDOWNIFY_AVAILABLE:
            md_text = self._html_to_markdown(html)
            sections = self._split_markdown_by_headings(md_text)
            return [{"heading": s["heading"], "content": s["content"]} for s in sections]

        if BeautifulSoup is None:
            raise ImportError("BeautifulSoup4 is required for HTML parsing. Install: pip install beautifulsoup4")
        soup = BeautifulSoup(html, "html.parser")
        sections = []
        current_heading = "root"
        current_content = []
        for elem in soup.find_all(["h1", "h2", "h3", "p", "ul", "ol", "table"]):
            if elem.name in ["h1", "h2", "h3"]:
                if current_content:
                    sections.append({"heading": current_heading, "content": "\n".join(current_content)})
                current_heading = elem.get_text(strip=True)
                current_content = []
            else:
                current_content.append(elem.get_text(separator=" ", strip=True))
        if current_content:
            sections.append({"heading": current_heading, "content": "\n".join(current_content)})
        return sections

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """Разбивает текст на абзацы (две новые строки)."""
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _merge_short_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Объединяет короткие чанки с соседними."""
        if not chunks:
            return chunks
        merged = []
        buffer = chunks[0]
        for chunk in chunks[1:]:
            combined_tokens = buffer.tokens_approx + chunk.tokens_approx
            if combined_tokens <= self.max_tokens and (
                buffer.tokens_approx < self.min_chunk_tokens or chunk.tokens_approx < self.min_chunk_tokens
            ):
                # Объединяем
                buffer.text += "\n\n" + chunk.text
                buffer.tokens_approx = self._estimate_tokens(buffer.text)
                buffer.hash = hashlib.sha256(buffer.text.encode()).hexdigest()
                # Объединяем метаданные
                buffer.keywords.extend(chunk.keywords)
                buffer.entities.extend(chunk.entities)
                buffer.hypothetical_questions.extend(chunk.hypothetical_questions)
            else:
                merged.append(buffer)
                buffer = chunk
        merged.append(buffer)
        return merged

    def _prepend_context(self, chunk_text: str, metadata: dict) -> str:
        """Prepend document-level context to chunk text for better embedding.
        This helps preserve context that gets lost when chunking.

        Pattern from Anthropic's contextual chunking approach.
        """
        context_parts = []

        if metadata.get("doc_title"):
            context_parts.append(f"Document: {metadata['doc_title']}")

        if metadata.get("section_title"):
            context_parts.append(f"Section: {metadata['section_title']}")

        if metadata.get("source_type"):
            context_parts.append(f"Source: {metadata['source_type']}")

        if context_parts:
            context_prefix = " | ".join(context_parts) + "\n\n"
            return context_prefix + chunk_text

        return chunk_text

    def chunk_html(self, html: str, source_metadata: dict[str, Any]) -> list[Chunk]:
        """Нарезка HTML-документа на семантические чанки.
        Конвертирует HTML в Markdown, затем разбивает по заголовкам.
        Таблицы, списки, ссылки сохраняются в Markdown-формате.
        :param html: HTML-строка документа
        :param source_metadata: базовые метаданные (source_type, doc_title, version и т.д.)
        :return: список Chunk
        """
        if MARKDOWNIFY_AVAILABLE:
            md_text = self._html_to_markdown(html)
            return self.chunk_markdown_with_overlap(md_text, source_metadata)

        sections = self._split_by_headings(html)
        chunks = []
        position = 0
        for sec in sections:
            heading = sec["heading"]
            content = sec["content"]
            paragraphs = self._split_by_paragraphs(content)
            current_text = f"## {heading}\n" if heading != "root" else ""
            for para in paragraphs:
                if not para.strip():
                    continue
                candidate = current_text + para
                if self._estimate_tokens(candidate) > self.max_tokens and current_text:
                    if current_text:
                        chunk = self._create_chunk(current_text, position, source_metadata, heading)
                        chunks.append(chunk)
                        position += 1
                    current_text = f"## {heading}\n" + para
                elif not current_text:
                    current_text = para
                else:
                    current_text += "\n\n" + para
            if current_text:
                chunk = self._create_chunk(current_text, position, source_metadata, heading)
                chunks.append(chunk)
                position += 1
        chunks = self._apply_overlap(chunks)
        chunks = self._merge_short_chunks(chunks)
        if self.contextual_enricher.enabled and source_metadata:
            doc_text = self._html_to_markdown(html) if MARKDOWNIFY_AVAILABLE else html
            chunks = self.contextual_enricher.enrich_chunks(chunks, doc_text, source_metadata)
        return chunks

    def chunk_markdown_with_overlap(
        self,
        md_text: str,
        source_metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Chunk Markdown text with token-aware overlap.

        Splits by ATX headings (#, ##, ###), then by paragraphs within
        sections that exceed max_tokens. Overlap from the end of chunk N
        is prepended to chunk N+1 to preserve context across boundaries.

        :param md_text: Markdown text to chunk
        :param source_metadata: optional metadata dict (source_type, doc_title, etc.)
        :return: list of Chunk objects
        """
        if source_metadata is None:
            source_metadata = {}

        sections = self._split_markdown_by_headings(md_text)
        chunks = []
        position = 0
        for sec in sections:
            heading = sec["heading"]
            content = sec["content"]
            heading_prefix = f"{'#' * max(sec['level'], 1)} {heading}\n" if heading != "root" else ""
            paragraphs = self._split_by_paragraphs(content)
            current_text = heading_prefix
            for para in paragraphs:
                if not para.strip():
                    continue
                candidate = current_text + "\n\n" + para if current_text else para
                if self._estimate_tokens(candidate) > self.max_tokens and current_text:
                    if current_text.strip():
                        chunk = self._create_chunk(current_text, position, source_metadata, heading)
                        chunks.append(chunk)
                        position += 1
                    current_text = heading_prefix + para
                elif not current_text:
                    current_text = para
                else:
                    current_text += "\n\n" + para
            if current_text.strip():
                chunk = self._create_chunk(current_text, position, source_metadata, heading)
                chunks.append(chunk)
                position += 1
        chunks = self._apply_overlap(chunks)
        chunks = self._merge_short_chunks(chunks)
        if self.contextual_enricher.enabled and source_metadata:
            chunks = self.contextual_enricher.enrich_chunks(chunks, md_text, source_metadata)
        return chunks

    def extract_headings(self, html: str) -> list[dict[str, Any]]:
        """Extract all headings (h1, h2, h3) with anchor IDs from Confluence HTML.

        Returns a flat list of heading dicts with:
        - text: heading text
        - level: 1, 2, or 3
        - anchor_id: Confluence anchor ID (for URL: /display/SPACE/Page#anchor)
        """
        if BeautifulSoup is None:
            logger.warning("BeautifulSoup not available, cannot extract headings")
            return []

        soup = BeautifulSoup(html, "html.parser")
        headings: list[dict[str, Any]] = []

        for elem in soup.find_all(["h1", "h2", "h3"]):
            level = int(elem.name[1])
            text = elem.get_text(strip=True)
            if not text:
                continue

            # Try to find Confluence anchor ID:
            # 1. Look for preceding <ac:structured-macro ac:name="anchor">
            # 2. Look for id attribute on the heading itself
            anchor_id = self._find_anchor_id(elem)

            headings.append(
                {
                    "text": text,
                    "level": level,
                    "anchor_id": anchor_id,
                }
            )

        return headings

    def _find_anchor_id(self, heading_elem: Any) -> str:
        """Find Confluence anchor ID associated with a heading element.

        Confluence stores anchors as:
        <ac:structured-macro ac:name="anchor">
          <ac:parameter ac:name="">anchor-name</ac:parameter>
        </ac:structured-macro>
        or as <h2 id="Header-Text">.
        """
        # Check element's own id attribute
        elem_id = heading_elem.get("id", "")
        if elem_id:
            return elem_id

        # Check preceding sibling for anchor macro
        prev = heading_elem.previous_sibling
        while prev is not None:
            if hasattr(prev, "get") and prev.get("ac:name") == "anchor":
                param = prev.find("ac:parameter")
                if param and param.get_text(strip=True):
                    return param.get_text(strip=True)
            if hasattr(prev, "name") and prev.name == "ac:structured-macro" and prev.get("ac:name") == "anchor":
                param = prev.find("ac:parameter")
                if param and param.get_text(strip=True):
                    return param.get_text(strip=True)
                return ""
            prev = prev.previous_sibling if hasattr(prev, "previous_sibling") else None

        return ""

    def _build_heading_tree(
        self,
        headings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build a hierarchical heading tree from a flat list.

        Each node has: text, level, anchor_id, children (list of sub-headings).
        """
        if not headings:
            return []

        root: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = []

        for h in headings:
            node = {
                "text": h["text"],
                "level": h["level"],
                "anchor_id": h["anchor_id"],
                "children": [],
            }

            while stack and stack[-1]["level"] >= h["level"]:
                stack.pop()

            if stack:
                stack[-1]["children"].append(node)
            else:
                root.append(node)

            stack.append(node)

        return root

    def create_heading_chunks(
        self,
        html: str,
        source_metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Create heading-level index chunks for a Confluence page.

        Each chunk represents a heading with its position in the document
        hierarchy. These are indexed with source_type="heading" to enable
        queries like "Find the section about network racks".

        :param html: Confluence page HTML
        :param source_metadata: dict with source_type, doc_title, source_id (page_id), etc.
        :return: list of Chunk objects with source_type="heading"
        """
        headings = self.extract_headings(html)
        if not headings:
            return []

        tree = self._build_heading_tree(headings)

        chunks: list[Chunk] = []
        page_id = source_metadata.get("source_id", "")
        page_title = source_metadata.get("doc_title", "")

        for i, h in enumerate(headings):
            heading_node = self._find_node_in_tree(tree, h["text"], h["level"])
            child_headings = [c["text"] for c in (heading_node.get("children", []) if heading_node else [])]

            text_parts = [f"{'#' * h['level']} {h['text']}"]
            if page_title:
                text_parts.insert(0, f"Document: {page_title}")
            if child_headings:
                text_parts.append(f"Sections: {', '.join(child_headings)}")

            text = "\n".join(text_parts)
            chunk_hash = hashlib.sha256(text.encode()).hexdigest()

            chunk = Chunk(
                text=text,
                hash=chunk_hash,
                title=h["text"],
                source_type="heading",
                source_id=page_id,
                doc_title=page_title,
                position=i,
                tokens_approx=self._estimate_tokens(text),
                keywords=[h["text"], *child_headings],
                parent_metadata={
                    "heading_text": h["text"],
                    "heading_level": h["level"],
                    "anchor_id": h["anchor_id"],
                    "page_id": page_id,
                    "page_title": page_title,
                    "child_headings": child_headings,
                },
            )
            # Use original_text to store the raw heading for display
            chunk.original_text = h["text"]
            chunks.append(chunk)

        return chunks

    def _find_node_in_tree(
        self,
        tree: list[dict[str, Any]],
        text: str,
        level: int,
    ) -> dict[str, Any] | None:
        """Find a heading node in the tree by text and level."""
        for node in tree:
            if node["text"] == text and node["level"] == level:
                return node
            result = self._find_node_in_tree(node.get("children", []), text, level)
            if result:
                return result
        return None

    def create_document_chunk(self, markdown_text: str, source_metadata: dict[str, Any]) -> Chunk | None:
        """Create a document-level summary chunk for broad topic matching.

        Encodes the page title + first ~500 characters of content
        as a single point with source_type="document".

        :param markdown_text: Markdown content of the page
        :param source_metadata: dict with source_type, doc_title, source_id (page_id)
        :return: Chunk with source_type="document" or None if content is empty
        """
        page_title = source_metadata.get("doc_title", "Untitled")
        page_id = source_metadata.get("source_id", "")

        first_line = markdown_text.split("\n")[0] if markdown_text else ""
        # Get first ~500 chars after stripping heading markers
        clean_text = re.sub(r"^#+\s*", "", markdown_text, flags=re.MULTILINE).strip()
        preview = clean_text[:500]
        if len(clean_text) > 500:
            preview += "..."

        summary_text = f"# {page_title}\n\n{preview}"

        chunk_hash = hashlib.sha256(summary_text.encode()).hexdigest()

        return Chunk(
            text=summary_text,
            hash=chunk_hash,
            title=page_title,
            summary=preview,
            source_type="document",
            source_id=page_id,
            doc_title=page_title,
            position=0,
            tokens_approx=self._estimate_tokens(summary_text),
            keywords=[page_title],
            parent_metadata={
                "page_id": page_id,
                "page_title": page_title,
                "first_line": first_line,
            },
        )

    def chunk_markdown(self, markdown_text: str, source_metadata: dict[str, Any]) -> list[Chunk]:
        """Конвертирует Markdown в HTML и использует chunk_html."""
        if markdown is None:
            raise ImportError("markdown library is required. Install: pip install markdown")
        html = markdown.markdown(markdown_text, extensions=["extra", "tables"])
        return self.chunk_html(html, source_metadata)

    def _create_chunk(self, text: str, position: int, source_metadata: dict, heading: str) -> Chunk:
        chunk = Chunk(
            text=text,
            hash=hashlib.sha256(text.encode()).hexdigest(),
            title=heading,
            source_type=source_metadata.get("source_type", ""),
            source_id=source_metadata.get("source_id", ""),
            version=source_metadata.get("version", ""),
            doc_title=source_metadata.get("doc_title", ""),
            position=position,
            tokens_approx=self._estimate_tokens(text),
            access_level=source_metadata.get("access_level", "public"),
            allowed_groups=list(source_metadata.get("allowed_groups", [])),
            allowed_users=list(source_metadata.get("allowed_users", [])),
        )
        return chunk

    def _apply_overlap(self, chunks: list[Chunk]) -> list[Chunk]:
        """Добавляет перекрытие между чанками (последние overlap_tokens из предыдущего в начало следующего)."""
        if self.overlap_tokens <= 0 or len(chunks) <= 1:
            return chunks
        overlapped = []
        prev_text = ""
        for _i, chunk in enumerate(chunks):
            if prev_text:
                # Берем последние self.overlap_tokens токенов из prev_text (приближённо)
                overlap_chars = self.overlap_tokens * 4
                overlap_snippet = prev_text[-overlap_chars:] if len(prev_text) > overlap_chars else prev_text
                chunk.text = f"[previous context: ...{overlap_snippet}]\n\n" + chunk.text
                # Пересчитываем хеш и токены
                chunk.hash = hashlib.sha256(chunk.text.encode()).hexdigest()
                chunk.tokens_approx = self._estimate_tokens(chunk.text)
            overlapped.append(chunk)
            prev_text = chunk.text
        return overlapped


class MetadataEnricher:
    """Обогащение чанков метаданными с использованием NLP (spaCy) и опционально SLM."""

    def __init__(self, use_slm: bool = False, slm_endpoint: str | None = None):
        self.use_slm = use_slm
        self.slm_endpoint = slm_endpoint
        self.nlp = None
        if NLP_AVAILABLE:
            try:
                # Загружаем маленькую модель для русского/английского
                self.nlp = spacy.load("ru_core_news_sm")  # или "en_core_web_sm"
            except Exception:
                try:
                    self.nlp = spacy.load("en_core_web_sm")
                except Exception:
                    logger.warning("spaCy model not found. Install: python -m spacy download ru_core_news_sm")
                    self.nlp = None

    def extract_keywords_tfidf(self, text: str, top_n: int = 5) -> list[str]:
        """Извлекает ключевые слова (простейший TF-IDF на уровне предложений). Заглушка для простоты."""
        # Упрощённо: берём наиболее частые слова длиннее 3 символов, исключая стоп-слова
        stopwords = {"и", "в", "на", "с", "к", "у", "по", "для", "из", "о", "не", "быть", "что", "как", "это"}
        words = re.findall(r"\b\w{4,}\b", text.lower())
        freq = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_n]]

    def extract_entities_spacy(self, text: str) -> list[str]:
        """Извлекает именованные сущности (люди, организации, продукты)."""
        if not self.nlp:
            return []
        doc = self.nlp(text[:500000])  # ограничиваем длину
        entities = list({ent.text for ent in doc.ents if ent.label_ in ("PERSON", "ORG", "PRODUCT", "GPE")})
        return entities[:10]

    def generate_summary(self, text: str) -> str:
        """Генерирует суммаризацию через эвристики (первые 2 предложения). Для SLM оставляем заглушку."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) <= 2:
            return text
        return " ".join(sentences[:2]) + "..."

    def generate_hypothetical_questions(self, text: str) -> list[str]:
        """Генерирует гипотетические вопросы, которые может задать пользователь (заглушка)."""
        # Простейший шаблон: извлечение ключевых фраз с вопросительными словами
        questions = []
        # Ищем фразы с "как", "почему", "что такое"
        for match in re.finditer(r"(Как|Что такое|Почему|Зачем|Где)([^.!?]+)", text):
            q = match.group(0).strip() + "?"
            if len(q) < 100:
                questions.append(q)
        return questions[:3]

    def enrich_with_slm(self, chunk_text: str) -> dict[str, Any]:
        """Вызывает локальный SLM (через REST API) для генерации суммаризации, ключевых слов, вопросов."""
        if not self.use_slm or not self.slm_endpoint:
            return {}
        try:
            import requests

            prompt = f"""Analyze the following technical text and output JSON with fields:
- summary: short summary (one sentence)
- keywords: list of 5 key terms
- questions: list of 3 likely user questions

Text: {chunk_text[:1500]}

Output JSON:"""
            resp = requests.post(
                self.slm_endpoint,
                json={"prompt": prompt, "max_tokens": 300, "temperature": 0.3},
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json()
                # Предполагаем, что SLM возвращает текст, который можно распарсить
                import json as json_parse

                try:
                    data = json_parse.loads(result.get("text", "{}"))
                    return {
                        "summary": data.get("summary", ""),
                        "keywords": data.get("keywords", []),
                        "hypothetical_questions": data.get("questions", []),
                    }
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"SLM enrichment failed: {e}")
        return {}


class MDKeyChunker:
    """Полноценный семантический чанкер с каскадированием метаданных и биновой упаковкой."""

    def __init__(self, base_chunker: SemanticChunker, enricher: MetadataEnricher):
        self.base = base_chunker
        self.enricher = enricher

    def process_document(self, content: str, content_type: str, source_metadata: dict[str, Any]) -> list[Chunk]:
        """Основной метод: нарезка, обогащение, каскадирование метаданных.
        :param content: HTML или Markdown строка
        :param content_type: "html" или "markdown"
        :param source_metadata: словарь с source_type, doc_title, version, source_id
        """
        chunks = self._do_chunking(content, content_type, source_metadata)
        self._enrich_chunks(chunks, source_metadata)
        self._apply_rolling_key_propagation(chunks)
        return self._pack_by_semantic_key(chunks)

    def _do_chunking(self, content: str, content_type: str, source_metadata: dict[str, Any]) -> list[Chunk]:
        """Prepare and chunk the content based on its type."""
        enriched_content = self.base._prepend_context(content, source_metadata)
        if content_type == "markdown":
            return self.base.chunk_markdown(enriched_content, source_metadata)
        return self.base.chunk_html(enriched_content, source_metadata)

    def _enrich_chunks(self, chunks: list[Chunk], source_metadata: dict[str, Any]) -> None:
        """Enrich each chunk with NLP metadata and optional SLM data."""
        for chunk in chunks:
            chunk.source_type = source_metadata.get("source_type", "")
            chunk.source_id = source_metadata.get("source_id", "")
            chunk.version = source_metadata.get("version", "")
            chunk.doc_title = source_metadata.get("doc_title", "")

            # Propagate ACL from document metadata to chunk
            chunk.access_level = source_metadata.get("access_level", chunk.access_level)
            if source_metadata.get("allowed_groups"):
                chunk.allowed_groups = list(source_metadata["allowed_groups"])
            if source_metadata.get("allowed_users"):
                chunk.allowed_users = list(source_metadata["allowed_users"])

            if not self.enricher:
                continue

            chunk.entities = self.enricher.extract_entities_spacy(chunk.text)
            chunk.keywords = self.enricher.extract_keywords_tfidf(chunk.text)
            chunk.summary = self.enricher.generate_summary(chunk.text)
            chunk.hypothetical_questions = self.enricher.generate_hypothetical_questions(chunk.text)

            if self.enricher.use_slm:
                self._apply_slm_enrichment(chunk)

    def _apply_slm_enrichment(self, chunk: Chunk) -> None:
        """Apply SLM-based enrichment to a single chunk."""
        slm_data = self.enricher.enrich_with_slm(chunk.text)
        if slm_data.get("summary"):
            chunk.summary = slm_data["summary"]
        if slm_data.get("keywords"):
            chunk.keywords = slm_data["keywords"]
        if slm_data.get("hypothetical_questions"):
            chunk.hypothetical_questions = slm_data["hypothetical_questions"]

    def _apply_rolling_key_propagation(self, chunks: list[Chunk]) -> None:
        """Save original text and propagate metadata across chunks."""
        for chunk in chunks:
            chunk.original_text = chunk.text
            chunk.enriched = True

        prev_metadata: dict[str, Any] = {}
        for chunk in chunks:
            if chunk.semantic_key == "":
                chunk.parent_metadata = prev_metadata.copy()
            else:
                prev_metadata = {"title": chunk.title, "keywords": chunk.keywords, "entities": chunk.entities}

            meta_prefix = f"Context: {chunk.doc_title}"
            if chunk.parent_metadata.get("title"):
                meta_prefix += f" > {chunk.parent_metadata['title']}"
            chunk.text = f"[{meta_prefix}]\n{chunk.text}"
            chunk.hash = hashlib.sha256(chunk.text.encode()).hexdigest()

    def _pack_by_semantic_key(self, chunks: list[Chunk]) -> list[Chunk]:
        """Объединяет чанки с одинаковым semantic_key в один, сохраняя порядок."""
        groups = {}
        for ch in chunks:
            key = ch.semantic_key or f"_unique_{ch.hash}"
            if key not in groups:
                groups[key] = []
            groups[key].append(ch)
        packed = []
        for key, group in groups.items():
            if len(group) == 1:
                packed.append(group[0])
            else:
                # Объединяем тексты и метаданные
                combined_text = "\n\n---\n\n".join([ch.text for ch in group])
                combined_hash = hashlib.sha256(combined_text.encode()).hexdigest()
                combined_entities = list({e for ch in group for e in ch.entities})
                combined_keywords = list({k for ch in group for k in ch.keywords})
                combined_questions = []
                for ch in group:
                    combined_questions.extend(ch.hypothetical_questions)
                combined_questions = combined_questions[:5]
                first = group[0]
                packed_chunk = Chunk(
                    text=combined_text,
                    hash=combined_hash,
                    title=first.title,
                    summary=first.summary,
                    keywords=combined_keywords,
                    entities=combined_entities,
                    hypothetical_questions=combined_questions,
                    semantic_key=key,
                    source_type=first.source_type,
                    source_id=first.source_id,
                    version=first.version,
                    doc_title=first.doc_title,
                    parent_metadata=first.parent_metadata,
                    position=first.position,
                )
                packed.append(packed_chunk)
        return packed


class ContextualEnricher:
    """Contextual chunk enrichment without LLM calls.

    Implements Anthropic's contextual retrieval pattern:
    prepends document context to each chunk before embedding,
    reducing retrieval failures by up to 49%.

    Uses document structure heuristics (headings, adjacent paragraphs)
    to generate a 50-100 token contextual prefix — no LLM required.
    """

    TARGET_CONTEXT_TOKENS = 75
    MAX_CONTEXT_TOKENS = 100

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def enrich_chunks(
        self,
        chunks: list[Chunk],
        full_document_text: str,
        source_metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Enrich each chunk with a contextual prefix from the document structure.

        For each chunk:
        1. Find the nearest heading before the chunk in the document
        2. Grab surrounding sentences from adjacent paragraphs
        3. Prepend context prefix: "Document: {title}\\nSection: {heading}\\nContext: {surrounding}\\n\\n{chunk_text}"
        """
        if not self.enabled or not chunks:
            return chunks

        doc_title = source_metadata.get("doc_title", "")
        sections = self._parse_document_sections(full_document_text)

        for chunk in chunks:
            if chunk.original_text:
                continue
            chunk.original_text = chunk.text
            chunk.enriched = True

            context = self._build_context(chunk, sections, doc_title, full_document_text)
            if context:
                chunk.text = f"{context}\n\n{chunk.text}"
                chunk.hash = hashlib.sha256(chunk.text.encode()).hexdigest()
                chunk.tokens_approx = max(1, int(len(chunk.text) / 4))

        return chunks

    def _parse_document_sections(self, text: str) -> list[dict[str, Any]]:
        """Parse document into sections by headings.

        Returns list of {heading: str, level: int, start: int, end: int}
        """
        heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(heading_re.finditer(text))

        if not matches:
            return [{"heading": "", "level": 0, "start": 0, "end": len(text)}]

        sections = []
        for i, match in enumerate(matches):
            level = len(match.group(1))
            heading = match.group(2).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append({"heading": heading, "level": level, "start": start, "end": end})

        return sections

    def _build_context(
        self,
        chunk: Chunk,
        sections: list[dict[str, Any]],
        doc_title: str,
        full_text: str,
    ) -> str:
        """Build contextual prefix for a chunk."""
        parts: list[str] = []

        if doc_title:
            parts.append(f"Document: {doc_title}")

        section_heading = self._find_section_for_chunk(chunk, sections, full_text)
        if section_heading:
            parts.append(f"Section: {section_heading}")

        surrounding = self._extract_surrounding_context(chunk, full_text)
        if surrounding:
            parts.append(f"Context: {surrounding}")

        if not parts:
            return ""

        return "\n".join(parts)

    def _find_section_for_chunk(
        self,
        chunk: Chunk,
        sections: list[dict[str, Any]],
        full_text: str,
    ) -> str:
        """Find which section a chunk belongs to by position."""
        chunk_pos = full_text.find(chunk.original_text or chunk.text)
        if chunk_pos < 0:
            return ""

        for section in reversed(sections):
            if section["start"] <= chunk_pos:
                return section["heading"]

        return ""

    def _extract_surrounding_context(self, chunk: Chunk, full_text: str) -> str:
        """Extract surrounding sentences for contextual grounding.

        Takes ~1-2 sentences before the chunk start and ~1-2 after the chunk end.
        """
        chunk_text = chunk.original_text or chunk.text
        chunk_pos = full_text.find(chunk_text)
        if chunk_pos < 0:
            return ""

        chunk_end = chunk_pos + len(chunk_text)

        before = full_text[max(0, chunk_pos - 300) : chunk_pos].strip()
        after = full_text[chunk_end : chunk_end + 300].strip()

        sentences_before = re.split(r"(?<=[.!?])\s+", before)
        sentences_after = re.split(r"(?<=[.!?])\s+", after)

        context_chars = 0
        max_context_chars = self.MAX_CONTEXT_TOKENS * 4
        parts: list[str] = []

        for sentence in reversed(sentences_before):
            if context_chars + len(sentence) > max_context_chars:
                break
            if sentence.strip():
                parts.insert(0, sentence.strip())
                context_chars += len(sentence)

        for sentence in sentences_after:
            if context_chars + len(sentence) > max_context_chars:
                break
            if sentence.strip():
                parts.append(sentence.strip())
                context_chars += len(sentence)

        return " ".join(parts)


class AdaptiveChunker:
    """Adaptive chunking that adjusts chunk size based on document structure.

    Strategy:
    - Headers/sections: chunk by section (natural boundaries)
    - Code blocks: keep together (don't split)
    - Tables: keep together
    - Long paragraphs: split at sentence boundaries
    - Short paragraphs: combine with neighbors

    Based on research: optimal chunk size 500-1500 chars with 10-20% overlap.
    """

    def __init__(
        self,
        min_chunk_size: int = 200,
        max_chunk_size: int = 2000,
        target_chunk_size: int = 800,
        overlap_ratio: float = 0.15,
    ):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.target_chunk_size = target_chunk_size
        self.overlap_ratio = overlap_ratio

    def _estimate_tokens(self, text: str) -> int:
        """Language-aware token estimation for chunks. Same logic as SemanticChunker."""
        if not text:
            return 0
        cyrillic = latin = cjk = other = 0
        for ch in text:
            cp = ord(ch)
            if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
                cyrillic += 1
            elif (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
                latin += 1
            elif (
                (0x4E00 <= cp <= 0x9FFF)
                or (0x3040 <= cp <= 0x309F)
                or (0x30A0 <= cp <= 0x30FF)
                or (0xAC00 <= cp <= 0xD7AF)
            ):
                cjk += 1
            else:
                other += 1
        weighted_ratio = cyrillic / 3.0 + latin / 4.0 + cjk / 1.5 + other / 4.0
        return max(1, int(weighted_ratio))

    def _detect_structure(self, text: str) -> list[dict[str, Any]]:
        """Detect document structure: headers, code blocks, tables, paragraphs.
        Returns list of structural elements.
        """
        elements = []
        lines = text.split("\n")
        current_pos = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # Header detection
            if re.match(r"^#{1,6}\s+", line):
                level_match = re.match(r"^(#{1,6})", line)
                elements.append(
                    {
                        "type": "header",
                        "level": len(level_match.group(1)) if level_match else 1,
                        "text": line,
                        "start": current_pos,
                        "end": current_pos + len(line) + 1,
                    },
                )

            # Code block detection
            elif line.strip().startswith("```"):
                # Find closing ```
                code_lines = [line]
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                if i < len(lines):
                    code_lines.append(lines[i])
                code_text = "\n".join(code_lines)
                elements.append(
                    {
                        "type": "code",
                        "text": code_text,
                        "start": current_pos,
                        "end": current_pos + len(code_text) + 1,
                    },
                )

            # Table detection
            elif "|" in line and i + 1 < len(lines) and "---" in lines[i + 1]:
                table_lines = [line]
                i += 1
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                table_text = "\n".join(table_lines)
                elements.append(
                    {
                        "type": "table",
                        "text": table_text,
                        "start": current_pos,
                        "end": current_pos + len(table_text) + 1,
                    },
                )
                i -= 1  # Will be incremented at end of loop

            # Regular paragraph
            elif line.strip():
                elements.append(
                    {
                        "type": "paragraph",
                        "text": line,
                        "start": current_pos,
                        "end": current_pos + len(line) + 1,
                    },
                )

            current_pos += len(line) + 1
            i += 1

        return elements

    def _merge_small_elements(self, elements: list[dict]) -> list[dict[str, Any]]:
        """Merge small adjacent elements to reach target chunk size."""
        if not elements:
            return []

        merged = []
        current_chunk = elements[0].copy()

        for elem in elements[1:]:
            # Don't merge headers with previous content
            if elem["type"] == "header":
                if len(current_chunk["text"]) >= self.min_chunk_size:
                    merged.append(current_chunk)
                current_chunk = elem.copy()
                continue

            # Don't merge code blocks
            if elem["type"] == "code" or current_chunk["type"] == "code":
                if len(current_chunk["text"]) >= self.min_chunk_size:
                    merged.append(current_chunk)
                current_chunk = elem.copy()
                continue

            # Merge if combined size is under target
            combined_size = len(current_chunk["text"]) + len(elem["text"])
            if combined_size <= self.target_chunk_size:
                current_chunk["text"] += "\n" + elem["text"]
                current_chunk["end"] = elem["end"]
            else:
                if len(current_chunk["text"]) >= self.min_chunk_size:
                    merged.append(current_chunk)
                current_chunk = elem.copy()

        if current_chunk:
            merged.append(current_chunk)

        return merged

    def _split_large_chunks(self, elements: list[dict]) -> list[dict[str, Any]]:
        """Split chunks that exceed max_chunk_size at sentence boundaries."""
        result = []
        for elem in elements:
            if len(elem["text"]) <= self.max_chunk_size:
                result.append(elem)
                continue

            # Split at sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", elem["text"])
            current_chunk = ""

            for sentence in sentences:
                if len(current_chunk) + len(sentence) > self.target_chunk_size:
                    if current_chunk:
                        result.append(
                            {
                                "type": elem["type"],
                                "text": current_chunk.strip(),
                                "start": elem["start"],
                                "end": elem["start"] + len(current_chunk),
                            },
                        )
                    current_chunk = sentence
                else:
                    current_chunk += " " + sentence if current_chunk else sentence

            if current_chunk:
                result.append(
                    {
                        "type": elem["type"],
                        "text": current_chunk.strip(),
                        "start": elem["start"],
                        "end": elem["start"] + len(current_chunk),
                    },
                )

        return result

    def _apply_overlap(self, chunks: list[dict]) -> list[dict[str, Any]]:
        """Apply overlap between consecutive chunks for context continuity."""
        if self.overlap_ratio <= 0 or len(chunks) <= 1:
            return chunks

        overlapped = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                overlap_chars = int(len(chunks[i - 1]["text"]) * self.overlap_ratio)
                overlap_text = chunks[i - 1]["text"][-overlap_chars:]
                chunk["text"] = f"[previous context: ...{overlap_text}]\n\n{chunk['text']}"
            overlapped.append(chunk)

        return overlapped

    def chunk(self, text: str) -> list[dict[str, Any]]:
        """Adaptive chunking: detect structure, merge small, split large.

        Returns list of chunks with:
        - text: chunk content
        - type: structural type (header, code, table, paragraph)
        - start/end: position in original text
        """
        # Step 1: Detect structure
        elements = self._detect_structure(text)

        # Step 2: Merge small elements
        merged = self._merge_small_elements(elements)

        # Step 3: Split large chunks
        final = self._split_large_chunks(merged)

        # Step 4: Apply overlap
        final = self._apply_overlap(final)

        return final

    def chunk_markdown(self, markdown_text: str, source_metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunk markdown text and return Chunk objects compatible with the pipeline.

        :param markdown_text: Raw markdown text
        :param source_metadata: Optional metadata dict with source_type, doc_title, etc.
        :return: List of Chunk objects
        """
        if source_metadata is None:
            source_metadata = {}

        raw_chunks = self.chunk(markdown_text)
        chunks: list[Chunk] = []

        for i, raw in enumerate(raw_chunks):
            text = raw["text"]
            chunk = Chunk(
                text=text,
                hash=hashlib.sha256(text.encode()).hexdigest(),
                title=raw.get("type", "paragraph"),
                source_type=source_metadata.get("source_type", ""),
                source_id=source_metadata.get("source_id", ""),
                version=source_metadata.get("version", ""),
                doc_title=source_metadata.get("doc_title", ""),
                position=i,
                tokens_approx=self._estimate_tokens(text),
            )
            chunks.append(chunk)

        return chunks


# Утилита для сохранения чанков в JSON (для последующей индексации)
def save_chunks_to_json(chunks: list[Chunk], output_path: Path):
    """Сохраняет список чанков в JSON-файл."""
    data = []
    for ch in chunks:
        d = asdict(ch)
        # Преобразуем списки в обычные списки
        d["keywords"] = list(d["keywords"])
        d["entities"] = list(d["entities"])
        d["hypothetical_questions"] = list(d["hypothetical_questions"])
        data.append(d)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Пример использования
    test_html = """
    <h1>Introduction to RAG</h1>
    <p>Retrieval-Augmented Generation is a technique for enhancing LLMs with external knowledge.</p>
    <h2>Components</h2>
    <p>RAG consists of retriever and generator.</p>
    <ul><li>Retriever fetches relevant documents</li><li>Generator produces answer</li></ul>
    """
    metadata = {"source_type": "confluence", "source_id": "12345", "version": "2.0", "doc_title": "RAG Overview"}
    chunker = SemanticChunker(max_tokens=800, overlap_tokens=50)
    enricher = MetadataEnricher(use_slm=False)
    md_chunker = MDKeyChunker(chunker, enricher)
    chunks = md_chunker.process_document(test_html, "html", metadata)
    for ch in chunks:
        print(f"Chunk {ch.position}: {ch.title} -> {ch.tokens_approx} tokens")
        print(f"  Keywords: {ch.keywords}")
        print(f"  Entities: {ch.entities}")
        print(f"  Summary: {ch.summary}")
        print("---")  # Сохранить в JSON  # save_chunks_to_json(chunks, Path("./chunks_output.json"))
