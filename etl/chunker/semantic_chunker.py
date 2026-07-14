# etl/chunker/semantic_chunker.py
"""
Семантический чанкинг для RAG-системы.
Реализует MDKeyChunker (Semantic Chunker) с извлечением метаданных и каскадированием.
Поддерживает HTML и Markdown, LLM-обогащение (опционально).
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
  BeautifulSoup = None
try:
  import markdown
except ImportError:
  markdown = None

# Для NLP (опционально)
try:
  import spacy
  
  NLP_AVAILABLE = True
except ImportError:
  NLP_AVAILABLE = False

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger (__name__)


@dataclass
class Chunk:
  """Структура чанка с метаданными."""
  
  text: str
  hash: str
  title: str = ""
  summary: str = ""
  keywords: list [str] = field (default_factory = list)
  entities: list [str] = field (default_factory = list)
  hypothetical_questions: list [str] = field (default_factory = list)
  semantic_key: str = ""  # для группировки
  source_type: str = ""  # confluence, jira, gitlab
  source_id: str = ""  # page_id, issue_key, commit_sha
  version: str = ""  # версия документа
  doc_title: str = ""  # оригинальный заголовок документа
  parent_metadata: dict [str, Any] = field (default_factory = dict)  # унаследованные метаданные
  position: int = 0  # порядковый номер в документе
  tokens_approx: int = 0  # примерное количество токенов
  original_text: str = ""  # текст без контекстного префикса (для отображения)
  enriched: bool = False  # был ли чанк обогащён контекстом


class SemanticChunker:
  """
  Базовый семантический чанкер. Разбивает документ на структурные блоки:
  заголовки (h1-h3), абзацы, списки, таблицы. Поддерживает HTML и Markdown.
  """
  
  def __init__ (self, max_tokens: int = 1500, overlap_tokens: int = 200, min_chunk_tokens: int = 100):
    """
    :param max_tokens: максимальное количество токенов в чанке (для эмбеддера)
                       Research-backed optimal: 1500 tokens (~6000 chars) for retrieval quality.
                       See: https://habr.com/ru/articles/1029740/
    :param overlap_tokens: перекрытие между чанками (токены)
                           200 tokens (~800 chars, ~13% overlap) for context continuity.
    :param min_chunk_tokens: минимальный размер чанка, иначе объединяется со следующим
    """
    self.max_tokens = max_tokens
    self.overlap_tokens = overlap_tokens
    self.min_chunk_tokens = min_chunk_tokens
  
  def _estimate_tokens (self, text: str) -> int:
    """Грубая оценка токенов (4 символа ~ 1 токен для рус/англ). Для точности использовать tiktoken."""
    return len (text) // 4
  
  def _split_by_headings (self, html: str) -> list [dict]:
    """
    Разбивает HTML на секции по заголовкам h1, h2, h3.
    Возвращает список {heading: str, content: str}
    """
    if BeautifulSoup is None:
      raise ImportError ("BeautifulSoup4 is required for HTML parsing. Install: pip install beautifulsoup4")
    soup = BeautifulSoup (html, "html.parser")
    sections = []
    current_heading = "root"
    current_content = []
    for elem in soup.find_all (["h1", "h2", "h3", "p", "ul", "ol", "table"]):
      if elem.name in ["h1", "h2", "h3"]:
        # Сохраняем предыдущую секцию
        if current_content:
          sections.append ({"heading": current_heading, "content": "\n".join (current_content)})
        current_heading = elem.get_text (strip = True)
        current_content = []
      else:
        current_content.append (str (elem))
    if current_content:
      sections.append ({"heading": current_heading, "content": "\n".join (current_content)})
    return sections
  
  def _split_by_paragraphs (self, text: str) -> list [str]:
    """Разбивает текст на абзацы (две новые строки)."""
    paragraphs = re.split (r"\n\s*\n", text)
    return [p.strip () for p in paragraphs if p.strip ()]
  
  def _merge_short_chunks (self, chunks: list [Chunk]) -> list [Chunk]:
    """Объединяет короткие чанки с соседними."""
    if not chunks:
      return chunks
    merged = []
    buffer = chunks [0]
    for chunk in chunks [1:]:
      combined_tokens = buffer.tokens_approx + chunk.tokens_approx
      if combined_tokens <= self.max_tokens and (
          buffer.tokens_approx < self.min_chunk_tokens or chunk.tokens_approx < self.min_chunk_tokens):
        # Объединяем
        buffer.text += "\n\n" + chunk.text
        buffer.tokens_approx = self._estimate_tokens (buffer.text)
        buffer.hash = hashlib.sha256 (buffer.text.encode ()).hexdigest ()
        # Объединяем метаданные
        buffer.keywords.extend (chunk.keywords)
        buffer.entities.extend (chunk.entities)
        buffer.hypothetical_questions.extend (chunk.hypothetical_questions)
      else:
        merged.append (buffer)
        buffer = chunk
    merged.append (buffer)
    return merged
  
  def _prepend_context (self, chunk_text: str, metadata: dict) -> str:
    """
    Prepend document-level context to chunk text for better embedding.
    This helps preserve context that gets lost when chunking.

    Pattern from Anthropic's contextual chunking approach.
    """
    context_parts = []
    
    if metadata.get ("doc_title"):
      context_parts.append (f"Document: {metadata ['doc_title']}")
    
    if metadata.get ("section_title"):
      context_parts.append (f"Section: {metadata ['section_title']}")
    
    if metadata.get ("source_type"):
      context_parts.append (f"Source: {metadata ['source_type']}")
    
    if context_parts:
      context_prefix = " | ".join (context_parts) + "\n\n"
      return context_prefix + chunk_text
    
    return chunk_text
  
  def chunk_html (self, html: str, source_metadata: dict [str, Any]) -> list [Chunk]:
    """
    Нарезка HTML-документа на семантические чанки.
    :param html: HTML-строка документа
    :param source_metadata: базовые метаданные (source_type, doc_title, version и т.д.)
    :return: список Chunk
    """
    sections = self._split_by_headings (html)
    chunks = []
    position = 0
    for sec in sections:
      heading = sec ["heading"]
      content = sec ["content"]
      # Разбиваем содержимое на абзацы, если слишком большой
      paragraphs = self._split_by_paragraphs (content)
      current_text = f"## {heading}\n" if heading != "root" else ""
      for para in paragraphs:
        if not para.strip ():
          continue
        candidate = current_text + para
        if self._estimate_tokens (candidate) > self.max_tokens and current_text:
          # Сохраняем текущий накопленный чанк и начинаем новый
          if current_text:
            chunk = self._create_chunk (current_text, position, source_metadata, heading)
            chunks.append (chunk)
            position += 1
          current_text = f"## {heading}\n" + para
        else:
          if not current_text:
            current_text = para
          else:
            current_text += "\n\n" + para
      if current_text:
        chunk = self._create_chunk (current_text, position, source_metadata, heading)
        chunks.append (chunk)
        position += 1
    # Применяем перекрытие (overlap)
    chunks = self._apply_overlap (chunks)
    # Объединяем короткие чанки
    chunks = self._merge_short_chunks (chunks)
    return chunks
  
  def chunk_markdown (self, markdown_text: str, source_metadata: dict [str, Any]) -> list [Chunk]:
    """Конвертирует Markdown в HTML и использует chunk_html."""
    if markdown is None:
      raise ImportError ("markdown library is required. Install: pip install markdown")
    html = markdown.markdown (markdown_text, extensions = ["extra", "tables"])
    return self.chunk_html (html, source_metadata)
  
  def _create_chunk (self, text: str, position: int, source_metadata: dict, heading: str) -> Chunk:
    chunk = Chunk (text = text, hash = hashlib.sha256 (text.encode ()).hexdigest (), title = heading,
        source_type = source_metadata.get ("source_type", ""), source_id = source_metadata.get ("source_id", ""),
        version = source_metadata.get ("version", ""), doc_title = source_metadata.get ("doc_title", ""),
        position = position, tokens_approx = self._estimate_tokens (text), )
    return chunk
  
  def _apply_overlap (self, chunks: list [Chunk]) -> list [Chunk]:
    """Добавляет перекрытие между чанками (последние overlap_tokens из предыдущего в начало следующего)."""
    if self.overlap_tokens <= 0 or len (chunks) <= 1:
      return chunks
    overlapped = []
    prev_text = ""
    for _i, chunk in enumerate (chunks):
      if prev_text:
        # Берем последние self.overlap_tokens токенов из prev_text (приближённо)
        overlap_chars = self.overlap_tokens * 4
        overlap_snippet = prev_text [-overlap_chars:] if len (prev_text) > overlap_chars else prev_text
        chunk.text = f"[previous context: ...{overlap_snippet}]\n\n" + chunk.text
        # Пересчитываем хеш и токены
        chunk.hash = hashlib.sha256 (chunk.text.encode ()).hexdigest ()
        chunk.tokens_approx = self._estimate_tokens (chunk.text)
      overlapped.append (chunk)
      prev_text = chunk.text
    return overlapped


class MetadataEnricher:
  """
  Обогащение чанков метаданными с использованием NLP (spaCy) и опционально SLM.
  """
  
  def __init__ (self, use_slm: bool = False, slm_endpoint: str | None = None):
    self.use_slm = use_slm
    self.slm_endpoint = slm_endpoint
    self.nlp = None
    if NLP_AVAILABLE:
      try:
        # Загружаем маленькую модель для русского/английского
        self.nlp = spacy.load ("ru_core_news_sm")  # или "en_core_web_sm"
      except Exception:
        try:
          self.nlp = spacy.load ("en_core_web_sm")
        except Exception:
          logger.warning ("spaCy model not found. Install: python -m spacy download ru_core_news_sm")
          self.nlp = None
  
  def extract_keywords_tfidf (self, text: str, top_n: int = 5) -> list [str]:
    """Извлекает ключевые слова (простейший TF-IDF на уровне предложений). Заглушка для простоты."""
    # Упрощённо: берём наиболее частые слова длиннее 3 символов, исключая стоп-слова
    stopwords = {"и", "в", "на", "с", "к", "у", "по", "для", "из", "о", "не", "быть", "что", "как", "это"}
    words = re.findall (r"\b\w{4,}\b", text.lower ())
    freq = {}
    for w in words:
      if w not in stopwords:
        freq [w] = freq.get (w, 0) + 1
    sorted_words = sorted (freq.items (), key = lambda x: x [1], reverse = True)
    return [w for w, _ in sorted_words [:top_n]]
  
  def extract_entities_spacy (self, text: str) -> list [str]:
    """Извлекает именованные сущности (люди, организации, продукты)."""
    if not self.nlp:
      return []
    doc = self.nlp (text [:500000])  # ограничиваем длину
    entities = list ({ent.text for ent in doc.ents if ent.label_ in ("PERSON", "ORG", "PRODUCT", "GPE")})
    return entities [:10]
  
  def generate_summary (self, text: str) -> str:
    """Генерирует суммаризацию через эвристики (первые 2 предложения). Для SLM оставляем заглушку."""
    sentences = re.split (r"(?<=[.!?])\s+", text)
    if len (sentences) <= 2:
      return text
    return " ".join (sentences [:2]) + "..."
  
  def generate_hypothetical_questions (self, text: str) -> list [str]:
    """Генерирует гипотетические вопросы, которые может задать пользователь (заглушка)."""
    # Простейший шаблон: извлечение ключевых фраз с вопросительными словами
    questions = []
    # Ищем фразы с "как", "почему", "что такое"
    for match in re.finditer (r"(Как|Что такое|Почему|Зачем|Где)([^.!?]+)", text):
      q = match.group (0).strip () + "?"
      if len (q) < 100:
        questions.append (q)
    return questions [:3]
  
  def enrich_with_slm (self, chunk_text: str) -> dict [str, Any]:
    """Вызывает локальный SLM (через REST API) для генерации суммаризации, ключевых слов, вопросов."""
    if not self.use_slm or not self.slm_endpoint:
      return {}
    try:
      import requests
      
      prompt = f"""Analyze the following technical text and output JSON with fields:
- summary: short summary (one sentence)
- keywords: list of 5 key terms
- questions: list of 3 likely user questions

Text: {chunk_text [:1500]}

Output JSON:"""
      resp = requests.post (self.slm_endpoint, json = {"prompt": prompt, "max_tokens": 300, "temperature": 0.3},
          timeout = 10)
      if resp.status_code == 200:
        result = resp.json ()
        # Предполагаем, что SLM возвращает текст, который можно распарсить
        import json as json_parse
        
        try:
          data = json_parse.loads (result.get ("text", "{}"))
          return {
              "summary": data.get ("summary", ""), "keywords": data.get ("keywords", []),
              "hypothetical_questions": data.get ("questions", []),
          }
        except Exception:
          pass
    except Exception as e:
      logger.warning (f"SLM enrichment failed: {e}")
    return {}


class MDKeyChunker:
  """
  Полноценный семантический чанкер с каскадированием метаданных и биновой упаковкой.
  """
  
  def __init__ (self, base_chunker: SemanticChunker, enricher: MetadataEnricher):
    self.base = base_chunker
    self.enricher = enricher
  
  def process_document (self, content: str, content_type: str, source_metadata: dict [str, Any]) -> list [Chunk]:
    """
    Основной метод: нарезка, обогащение, каскадирование метаданных.
    :param content: HTML или Markdown строка
    :param content_type: "html" или "markdown"
    :param source_metadata: словарь с source_type, doc_title, version, source_id
    """
    # Before chunking, prepend context to the content
    enriched_content = self.base._prepend_context (content, source_metadata)
    if content_type == "markdown":
      chunks = self.base.chunk_markdown (enriched_content, source_metadata)
    else:
      chunks = self.base.chunk_html (enriched_content, source_metadata)
    
    # Обогащение метаданными (NLP + SLM)
    for _idx, chunk in enumerate (chunks):
      # Базовые метаданные от источника
      chunk.source_type = source_metadata.get ("source_type", "")
      chunk.source_id = source_metadata.get ("source_id", "")
      chunk.version = source_metadata.get ("version", "")
      chunk.doc_title = source_metadata.get ("doc_title", "")
      
      # Извлечение сущностей
      if self.enricher:
        chunk.entities = self.enricher.extract_entities_spacy (chunk.text)
        chunk.keywords = self.enricher.extract_keywords_tfidf (chunk.text)
        chunk.summary = self.enricher.generate_summary (chunk.text)
        chunk.hypothetical_questions = self.enricher.generate_hypothetical_questions (chunk.text)
        # SLM обогащение (опционально)
        if self.enricher.use_slm:
          slm_data = self.enricher.enrich_with_slm (chunk.text)
          if slm_data.get ("summary"):
            chunk.summary = slm_data ["summary"]
          if slm_data.get ("keywords"):
            chunk.keywords = slm_data ["keywords"]
          if slm_data.get ("hypothetical_questions"):
            chunk.hypothetical_questions = slm_data ["hypothetical_questions"]
    
    # Save original text before context prefix is added in Rolling Key Propagation
    for chunk in chunks:
      chunk.original_text = chunk.text
      chunk.enriched = True
    
    # Rolling Key Propagation: передаём метаданные предыдущего чанка следующему, если semantic_key не задан
    prev_metadata = {}
    for chunk in chunks:
      if chunk.semantic_key == "":
        chunk.parent_metadata = prev_metadata.copy ()
      else:
        prev_metadata = {"title": chunk.title, "keywords": chunk.keywords, "entities": chunk.entities}
      # Сохраняем в тексте чанка заголовок и ключевые слова для контекста
      meta_prefix = f"Context: {chunk.doc_title}"
      if chunk.parent_metadata.get ("title"):
        meta_prefix += f" > {chunk.parent_metadata ['title']}"
      chunk.text = f"[{meta_prefix}]\n{chunk.text}"
      chunk.hash = hashlib.sha256 (chunk.text.encode ()).hexdigest ()
    
    # Биновая упаковка: группируем чанки с одинаковым semantic_key (если есть)
    packed_chunks = self._pack_by_semantic_key (chunks)
    return packed_chunks
  
  def _pack_by_semantic_key (self, chunks: list [Chunk]) -> list [Chunk]:
    """Объединяет чанки с одинаковым semantic_key в один, сохраняя порядок."""
    groups = {}
    for ch in chunks:
      key = ch.semantic_key if ch.semantic_key else f"_unique_{ch.hash}"
      if key not in groups:
        groups [key] = []
      groups [key].append (ch)
    packed = []
    for key, group in groups.items ():
      if len (group) == 1:
        packed.append (group [0])
      else:
        # Объединяем тексты и метаданные
        combined_text = "\n\n---\n\n".join ([ch.text for ch in group])
        combined_hash = hashlib.sha256 (combined_text.encode ()).hexdigest ()
        combined_entities = list ({e for ch in group for e in ch.entities})
        combined_keywords = list ({k for ch in group for k in ch.keywords})
        combined_questions = []
        for ch in group:
          combined_questions.extend (ch.hypothetical_questions)
        combined_questions = combined_questions [:5]
        first = group [0]
        packed_chunk = Chunk (text = combined_text, hash = combined_hash, title = first.title, summary = first.summary,
            keywords = combined_keywords, entities = combined_entities, hypothetical_questions = combined_questions,
            semantic_key = key, source_type = first.source_type, source_id = first.source_id, version = first.version,
            doc_title = first.doc_title, parent_metadata = first.parent_metadata, position = first.position, )
        packed.append (packed_chunk)
    return packed


class AdaptiveChunker:
  """
  Adaptive chunking that adjusts chunk size based on document structure.

  Strategy:
  - Headers/sections: chunk by section (natural boundaries)
  - Code blocks: keep together (don't split)
  - Tables: keep together
  - Long paragraphs: split at sentence boundaries
  - Short paragraphs: combine with neighbors

  Based on research: optimal chunk size 500-1500 chars with 10-20% overlap.
  """
  
  def __init__ (
      self, min_chunk_size: int = 200, max_chunk_size: int = 2000, target_chunk_size: int = 800,
      overlap_ratio: float = 0.15, ):
    self.min_chunk_size = min_chunk_size
    self.max_chunk_size = max_chunk_size
    self.target_chunk_size = target_chunk_size
    self.overlap_ratio = overlap_ratio
  
  def _detect_structure (self, text: str) -> list [dict]:
    """
    Detect document structure: headers, code blocks, tables, paragraphs.
    Returns list of structural elements.
    """
    elements = []
    lines = text.split ("\n")
    current_pos = 0
    
    i = 0
    while i < len (lines):
      line = lines [i]
      
      # Header detection
      if re.match (r"^#{1,6}\s+", line):
        level_match = re.match (r"^(#{1,6})", line)
        elements.append ({
            "type": "header", "level": len (level_match.group (1)) if level_match else 1, "text": line,
            "start": current_pos, "end": current_pos + len (line) + 1,
        })
      
      # Code block detection
      elif line.strip ().startswith ("```"):
        # Find closing ```
        code_lines = [line]
        i += 1
        while i < len (lines) and not lines [i].strip ().startswith ("```"):
          code_lines.append (lines [i])
          i += 1
        if i < len (lines):
          code_lines.append (lines [i])
        code_text = "\n".join (code_lines)
        elements.append ({
            "type": "code", "text": code_text, "start": current_pos, "end": current_pos + len (code_text) + 1,
        })
      
      # Table detection
      elif "|" in line and i + 1 < len (lines) and "---" in lines [i + 1]:
        table_lines = [line]
        i += 1
        while i < len (lines) and "|" in lines [i]:
          table_lines.append (lines [i])
          i += 1
        table_text = "\n".join (table_lines)
        elements.append ({
            "type": "table", "text": table_text, "start": current_pos, "end": current_pos + len (table_text) + 1,
        })
        i -= 1  # Will be incremented at end of loop
      
      # Regular paragraph
      elif line.strip ():
        elements.append ({
            "type": "paragraph", "text": line, "start": current_pos, "end": current_pos + len (line) + 1,
        })
      
      current_pos += len (line) + 1
      i += 1
    
    return elements
  
  def _merge_small_elements (self, elements: list [dict]) -> list [dict]:
    """Merge small adjacent elements to reach target chunk size."""
    if not elements:
      return []
    
    merged = []
    current_chunk = elements [0].copy ()
    
    for elem in elements [1:]:
      # Don't merge headers with previous content
      if elem ["type"] == "header":
        if len (current_chunk ["text"]) >= self.min_chunk_size:
          merged.append (current_chunk)
        current_chunk = elem.copy ()
        continue
      
      # Don't merge code blocks
      if elem ["type"] == "code" or current_chunk ["type"] == "code":
        if len (current_chunk ["text"]) >= self.min_chunk_size:
          merged.append (current_chunk)
        current_chunk = elem.copy ()
        continue
      
      # Merge if combined size is under target
      combined_size = len (current_chunk ["text"]) + len (elem ["text"])
      if combined_size <= self.target_chunk_size:
        current_chunk ["text"] += "\n" + elem ["text"]
        current_chunk ["end"] = elem ["end"]
      else:
        if len (current_chunk ["text"]) >= self.min_chunk_size:
          merged.append (current_chunk)
        current_chunk = elem.copy ()
    
    if current_chunk:
      merged.append (current_chunk)
    
    return merged
  
  def _split_large_chunks (self, elements: list [dict]) -> list [dict]:
    """Split chunks that exceed max_chunk_size at sentence boundaries."""
    result = []
    for elem in elements:
      if len (elem ["text"]) <= self.max_chunk_size:
        result.append (elem)
        continue
      
      # Split at sentence boundaries
      sentences = re.split (r"(?<=[.!?])\s+", elem ["text"])
      current_chunk = ""
      
      for sentence in sentences:
        if len (current_chunk) + len (sentence) > self.target_chunk_size:
          if current_chunk:
            result.append ({
                "type": elem ["type"], "text": current_chunk.strip (), "start": elem ["start"],
                "end": elem ["start"] + len (current_chunk),
            })
          current_chunk = sentence
        else:
          current_chunk += " " + sentence if current_chunk else sentence
      
      if current_chunk:
        result.append ({
            "type": elem ["type"], "text": current_chunk.strip (), "start": elem ["start"],
            "end": elem ["start"] + len (current_chunk),
        })
    
    return result
  
  def _apply_overlap (self, chunks: list [dict]) -> list [dict]:
    """Apply overlap between consecutive chunks for context continuity."""
    if self.overlap_ratio <= 0 or len (chunks) <= 1:
      return chunks
    
    overlapped = []
    for i, chunk in enumerate (chunks):
      if i > 0:
        overlap_chars = int (len (chunks [i - 1] ["text"]) * self.overlap_ratio)
        overlap_text = chunks [i - 1] ["text"] [-overlap_chars:]
        chunk ["text"] = f"[previous context: ...{overlap_text}]\n\n{chunk ['text']}"
      overlapped.append (chunk)
    
    return overlapped
  
  def chunk (self, text: str) -> list [dict]:
    """
    Adaptive chunking: detect structure, merge small, split large.

    Returns list of chunks with:
    - text: chunk content
    - type: structural type (header, code, table, paragraph)
    - start/end: position in original text
    """
    # Step 1: Detect structure
    elements = self._detect_structure (text)
    
    # Step 2: Merge small elements
    merged = self._merge_small_elements (elements)
    
    # Step 3: Split large chunks
    final = self._split_large_chunks (merged)
    
    # Step 4: Apply overlap
    final = self._apply_overlap (final)
    
    return final
  
  def chunk_markdown (self, markdown_text: str, source_metadata: dict [str, Any] | None = None) -> list [Chunk]:
    """
    Chunk markdown text and return Chunk objects compatible with the pipeline.

    :param markdown_text: Raw markdown text
    :param source_metadata: Optional metadata dict with source_type, doc_title, etc.
    :return: List of Chunk objects
    """
    if source_metadata is None:
      source_metadata = {}
    
    raw_chunks = self.chunk (markdown_text)
    chunks: list [Chunk] = []
    
    for i, raw in enumerate (raw_chunks):
      text = raw ["text"]
      chunk = Chunk (text = text, hash = hashlib.sha256 (text.encode ()).hexdigest (),
          title = raw.get ("type", "paragraph"), source_type = source_metadata.get ("source_type", ""),
          source_id = source_metadata.get ("source_id", ""), version = source_metadata.get ("version", ""),
          doc_title = source_metadata.get ("doc_title", ""), position = i, tokens_approx = len (text) // 4,
          # Rough token estimate
      )
      chunks.append (chunk)
    
    return chunks


# Утилита для сохранения чанков в JSON (для последующей индексации)
def save_chunks_to_json (chunks: list [Chunk], output_path: Path):
  """Сохраняет список чанков в JSON-файл."""
  data = []
  for ch in chunks:
    d = asdict (ch)
    # Преобразуем списки в обычные списки
    d ["keywords"] = list (d ["keywords"])
    d ["entities"] = list (d ["entities"])
    d ["hypothetical_questions"] = list (d ["hypothetical_questions"])
    data.append (d)
  with open (output_path, "w", encoding = "utf-8") as f:
    json.dump (data, f, ensure_ascii = False, indent = 2)


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
  chunker = SemanticChunker (max_tokens = 800, overlap_tokens = 50)
  enricher = MetadataEnricher (use_slm = False)
  md_chunker = MDKeyChunker (chunker, enricher)
  chunks = md_chunker.process_document (test_html, "html", metadata)
  for ch in chunks:
    print (f"Chunk {ch.position}: {ch.title} -> {ch.tokens_approx} tokens")
    print (f"  Keywords: {ch.keywords}")
    print (f"  Entities: {ch.entities}")
    print (f"  Summary: {ch.summary}")
    print ("---")  # Сохранить в JSON  # save_chunks_to_json(chunks, Path("./chunks_output.json"))
