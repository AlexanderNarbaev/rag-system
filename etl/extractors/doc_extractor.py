"""Documentation extractor for Markdown, RST, and AsciiDoc formats."""

import logging
import re
from collections.abc import Generator
from pathlib import Path

from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class DocExtractor(BaseExtractor):
    """Extracts structured content from Markdown, RST, and AsciiDoc documentation."""

    FORMAT_MARKDOWN = "markdown"
    FORMAT_RST = "rst"
    FORMAT_ASCIIDOC = "asciidoc"

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".txt"}

    def __init__(self, config: ExtractorConfig):
        super().__init__(config)
        self._validated = False
        self._source_files: list[Path] = []

    async def validate_connection(self) -> bool:
        """Validate that source documentation files exist."""
        base_path = Path(self.config.base_url) if self.config.base_url else None
        if not base_path:
            logger.error("No base_url provided for doc extractor")
            return False
        if not base_path.exists():
            logger.error(f"Doc source directory does not exist: {base_path}")
            return False

        self._source_files = []
        for ext in self.SUPPORTED_EXTENSIONS:
            self._source_files.extend(list(base_path.rglob(f"*{ext}")))

        if self.config.exclude_patterns:
            self._source_files = [
                f for f in self._source_files if not any(p in str(f) for p in self.config.exclude_patterns)
            ]

        self._validated = len(self._source_files) > 0
        if self._validated:
            logger.info(f"Found {len(self._source_files)} doc files in {base_path}")
        else:
            logger.warning(f"No supported doc files found in {base_path}")
        return self._validated

    async def extract(self) -> Generator[ExtractedDocument, None, None]:
        """Extract documents from all supported documentation files."""
        if not self._validated:
            await self.validate_connection()

        for file_path in self._source_files:
            try:
                ext = file_path.suffix.lower()
                if ext in (".md", ".markdown"):
                    docs = self._extract_markdown(file_path)
                elif ext == ".rst":
                    docs = self._extract_rst(file_path)
                elif ext in (".adoc", ".asciidoc"):
                    docs = self._extract_asciidoc(file_path)
                else:
                    docs = self._extract_generic_text(file_path)

                for doc in docs:
                    yield doc
            except Exception as e:
                logger.error(f"Failed to extract doc file {file_path}: {e}", exc_info=True)

    def _extract_markdown(self, file_path: Path) -> list[ExtractedDocument]:
        """Extract structured content from Markdown with heading hierarchy."""
        content = file_path.read_text(encoding="utf-8")
        title = file_path.stem

        title_match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        headings = self._parse_markdown_headings(content)
        code_blocks = self._extract_markdown_code_blocks(content)
        tables = self._extract_markdown_tables(content)
        links = self._extract_markdown_links(content)

        if not headings:
            return [self._make_document(file_path, title, content, "markdown", 0, 1, code_blocks, tables, links)]

        documents = []
        for idx, (h_title, h_level, _section_text) in enumerate(headings):
            section_text = self._get_section_text(content, headings, idx)

            doc_code_blocks = self._extract_markdown_code_blocks(section_text)
            doc_tables = self._extract_markdown_tables(section_text)

            doc = ExtractedDocument(
                source_id=f"doc_md_{file_path.stem}_h{idx}",
                source_type="doc",
                title=f"{title} > {h_title}" if title != h_title else h_title,
                content=section_text,
                content_type="markdown",
                metadata={
                    "doc_title": title,
                    "section_title": h_title,
                    "heading_level": h_level,
                    "section_index": idx,
                    "total_sections": len(headings),
                    "format": "markdown",
                    "code_blocks": doc_code_blocks,
                    "code_block_count": len(doc_code_blocks),
                    "tables": doc_tables,
                    "table_count": len(doc_tables),
                    "file_path": str(file_path),
                    "cross_references": links,
                },
            )
            documents.append(doc)

        return documents

    def _extract_rst(self, file_path: Path) -> list[ExtractedDocument]:
        """Extract structured content from RST files."""
        content = file_path.read_text(encoding="utf-8")
        title = file_path.stem

        title_match = re.search(r"^(.+)\n[=]{3,}\s*$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        code_blocks = self._extract_rst_code_blocks(content)
        plain_text = self._rst_to_text(content)
        headings = self._parse_rst_headings(content)

        if not headings:
            return [self._make_document(file_path, title, plain_text, "rst", 0, 1, code_blocks, [], [])]

        documents = []
        for idx, (h_title, h_level, _section_text) in enumerate(headings):
            section_text = self._get_rst_section_text(plain_text, headings, idx)

            doc = ExtractedDocument(
                source_id=f"doc_rst_{file_path.stem}_h{idx}",
                source_type="doc",
                title=f"{title} > {h_title}" if title != h_title else h_title,
                content=section_text,
                content_type="text",
                metadata={
                    "doc_title": title,
                    "section_title": h_title,
                    "heading_level": h_level,
                    "section_index": idx,
                    "total_sections": len(headings),
                    "format": "rst",
                    "code_blocks": code_blocks,
                    "code_block_count": len(code_blocks),
                    "file_path": str(file_path),
                },
            )
            documents.append(doc)

        return documents

    def _extract_asciidoc(self, file_path: Path) -> list[ExtractedDocument]:
        """Extract structured content from AsciiDoc files."""
        content = file_path.read_text(encoding="utf-8")
        title = file_path.stem

        title_match = re.match(r"^=\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        code_blocks = self._extract_asciidoc_code_blocks(content)
        plain_text = self._asciidoc_to_text(content)
        headings = self._parse_asciidoc_headings(content)

        if not headings:
            return [self._make_document(file_path, title, plain_text, "asciidoc", 0, 1, code_blocks, [], [])]

        documents = []
        for idx, (h_title, h_level, _section_text) in enumerate(headings):
            section_text = self._get_section_text_from_headings(plain_text, headings, idx)

            doc = ExtractedDocument(
                source_id=f"doc_adoc_{file_path.stem}_h{idx}",
                source_type="doc",
                title=f"{title} > {h_title}" if title != h_title else h_title,
                content=section_text,
                content_type="text",
                metadata={
                    "doc_title": title,
                    "section_title": h_title,
                    "heading_level": h_level,
                    "section_index": idx,
                    "total_sections": len(headings),
                    "format": "asciidoc",
                    "code_blocks": code_blocks,
                    "code_block_count": len(code_blocks),
                    "file_path": str(file_path),
                },
            )
            documents.append(doc)

        return documents

    def _extract_generic_text(self, file_path: Path) -> list[ExtractedDocument]:
        """Fallback extraction for plain text files."""
        content = file_path.read_text(encoding="utf-8")
        return [self._make_document(file_path, file_path.stem, content, "text", 0, 1, [], [], [])]

    def _make_document(
        self,
        file_path: Path,
        title: str,
        content: str,
        format_type: str,
        section_idx: int,
        total_sections: int,
        code_blocks: list[str],
        tables: list[str],
        links: list[str],
    ) -> ExtractedDocument:
        return ExtractedDocument(
            source_id=f"doc_{format_type}_{file_path.stem}_s{section_idx}",
            source_type="doc",
            title=title,
            content=content,
            content_type=format_type,
            metadata={
                "doc_title": title,
                "section_index": section_idx,
                "total_sections": total_sections,
                "format": format_type,
                "code_blocks": code_blocks,
                "code_block_count": len(code_blocks),
                "tables": tables,
                "table_count": len(tables),
                "cross_references": links,
                "file_path": str(file_path),
            },
        )

    @staticmethod
    def _parse_markdown_headings(text: str) -> list[tuple[str, int, str]]:
        """Parse markdown headings with their section text."""
        pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        results = []
        for _i, m in enumerate(matches):
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            results.append((heading_text, level, ""))
        return results

    @staticmethod
    def _parse_rst_headings(text: str) -> list[tuple[str, int, str]]:
        """Parse RST headings."""
        results = []
        lines = text.splitlines()
        current_heading = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if current_heading is None:
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if re.match(r"^[=~\-`:'^\"*+#<>]{3,}$", next_line):
                    level = 1
                    current_heading = (stripped, level, "")
                    results.append(current_heading)
                    continue
            current_heading = None

            heading_match = re.match(r"^(\d+\.)?\s*(.+)", stripped)
            if heading_match and re.match(r"^[=~\-]{3,}$", lines[i + 1] if i + 1 < len(lines) else ""):
                next_char = lines[i + 1][0] if i + 1 < len(lines) else "="
                level_map = {"=": 1, "-": 2, "~": 3, "^": 4, '"': 5}
                level = level_map.get(next_char, 2)
                results.append((heading_match.group(2).strip(), level, ""))

        return results

    @staticmethod
    def _parse_asciidoc_headings(text: str) -> list[tuple[str, int, str]]:
        """Parse AsciiDoc headings."""
        pattern = re.compile(r"^(=+)\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        return [(m.group(2).strip(), len(m.group(1)), "") for m in matches]

    @staticmethod
    def _get_section_text(text: str, headings: list[tuple[str, int, str]], idx: int) -> str:
        """Get the text section for a heading."""
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        all_matches = list(heading_pattern.finditer(text))

        if idx >= len(all_matches):
            return ""

        start = all_matches[idx].start()
        end = all_matches[idx + 1].start() if idx + 1 < len(all_matches) else len(text)
        return text[start:end].strip()

    @staticmethod
    def _get_rst_section_text(text: str, headings: list[tuple[str, int, str]], idx: int) -> str:
        """Get text section for RST heading."""
        heading_title = headings[idx][0]
        escaped = re.escape(heading_title)
        matches = list(re.finditer(re.compile(r"^" + escaped + r"$", re.MULTILINE), text))
        if not matches:
            return text
        start = matches[0].start()
        end = matches[1].start() if len(matches) > 1 else len(text)
        return text[start:end].strip()

    @staticmethod
    def _get_section_text_from_headings(text: str, headings: list[tuple[str, int, str]], idx: int) -> str:
        """Get text section using heading data."""
        heading_title = headings[idx][0]
        escaped = re.escape(heading_title)
        matches = list(re.finditer(re.compile(r"^[=]+\s+" + escaped + r"$", re.MULTILINE), text))
        if not matches:
            matches = list(re.finditer(re.compile(escaped), text))
        if not matches:
            return text
        start = matches[0].start()
        end = matches[1].start() if len(matches) > 1 else len(text)
        return text[start:end].strip()

    @staticmethod
    def _extract_markdown_code_blocks(text: str) -> list[str]:
        """Extract code blocks from markdown."""
        blocks = []
        pattern = re.compile(r"```(?:\w*)\n(.*?)```", re.DOTALL)
        for match in pattern.finditer(text):
            code = match.group(1).strip()
            if code:
                blocks.append(code[:2000])
        return blocks

    @staticmethod
    def _extract_markdown_tables(text: str) -> list[str]:
        """Extract markdown table rows."""
        tables = []
        in_table = False
        current_table = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") and "|" in stripped[1:]:
                if not in_table:
                    in_table = True
                    current_table = [stripped]
                else:
                    current_table.append(stripped)
            else:
                if in_table:
                    tables.append("\n".join(current_table))
                    current_table = []
                    in_table = False
        if in_table and current_table:
            tables.append("\n".join(current_table))
        return tables

    @staticmethod
    def _extract_markdown_links(text: str) -> list[str]:
        """Extract markdown links."""
        pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        return [m.group(2) for m in pattern.finditer(text)]

    @staticmethod
    def _extract_rst_code_blocks(text: str) -> list[str]:
        """Extract RST code blocks."""
        blocks = []
        pattern = re.compile(r"\.\.\s+code-block::.*?\n\n(.*?)(?=\n\S|\Z)", re.DOTALL)
        for match in pattern.finditer(text):
            code = match.group(1).strip()
            blocks.append(code[:2000])
        return blocks

    @staticmethod
    def _extract_asciidoc_code_blocks(text: str) -> list[str]:
        """Extract AsciiDoc code blocks."""
        blocks = []
        pattern = re.compile(r"----\n(.*?)----", re.DOTALL)
        for match in pattern.finditer(text):
            code = match.group(1).strip()
            blocks.append(code[:2000])
        return blocks

    @staticmethod
    def _rst_to_text(text: str) -> str:
        """Convert RST to plain text."""
        text = re.sub(r"\.\.\s+\w+::.*", "", text)
        text = re.sub(r"\.\.\s+_\w+:\s*http\S+", "", text)
        text = re.sub(r":\w+:`([^`]+)`", r"\1", text)
        text = re.sub(r"``([^`]+)``", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"\n[=~\-`:'^\"*+#<>]{3,}\n", "\n", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    @staticmethod
    def _asciidoc_to_text(text: str) -> str:
        """Convert AsciiDoc to plain text."""
        text = re.sub(r"\.\w+::.*", "", text)
        text = re.sub(r"link:\S+\[([^\]]+)\]", r"\1", text)
        text = re.sub(r"image:\S+\[.*?\]", "", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\b\*([^*]+)\*\b", r"\1", text)
        text = re.sub(r"\b_([^_]+)_\b", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"----\n.*?----", "", text, flags=re.DOTALL)
        text = re.sub(r"----", "", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def should_process(self, doc: ExtractedDocument, last_hash: str) -> bool:
        """Check if document needs processing based on content hash."""
        if not last_hash:
            return True
        return self.compute_hash(doc.content) != last_hash
