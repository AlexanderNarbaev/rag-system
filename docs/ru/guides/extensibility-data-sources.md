# Руководство по расширяемости: добавление новых источников данных

Это руководство описывает, как расширить RAG-систему новыми источниками данных — от написания пользовательского экстрактора до настройки чанкинга, извлечения сущностей и инкрементального индексирования.

---

## 1. Плагинная архитектура экстракторов

Каждый экстрактор должен реализовывать абстрактный интерфейс `BaseExtractor`. Оркестратор в `etl/scheduler/run_etl.py` обнаруживает и вызывает экстракторы через диспетчеризацию на основе конфигурации.

```python
# etl/extractors/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
import json

class BaseExtractor(ABC):
    """Абстрактный базовый класс для всех экстракторов источников данных."""

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
        """Извлечь документы. Возвращает dict с ключами: id, source_type, title,
        content, content_type (html|markdown|text|code), metadata."""

    @abstractmethod
    def run(self):
        """Оркестрировать полное извлечение: extract → save → WAL update."""
```

### Регистрация в run_etl.py

Добавьте новую секцию в `etl/scheduler/run_etl.py`:

```python
from etl.extractors.book_extractor import BookExtractor

def run_extract_books(config: Dict, wal: WALManager) -> Path:
    logger.info("=== Начало извлечения книг ===")
    book_config = config.get("books", {})
    book_config["wal_file"] = str(wal.wal_path)
    extractor = BookExtractor(book_config)
    extractor.run()
    wal.update_last_run("books")
    return Path(book_config.get("output_dir", "./raw_data/books"))
```

Затем добавьте блок `books:` в `etl/config/etl_config.yaml` и функцию `collect_books_documents()` для подачи в конвейер чанкинга.

---

## 2. Добавление новых типов источников

### Книги (EPUB, PDF, DOCX)

- **EPUB** — используйте `EbookLib` для парсинга `.epub`, извлекайте главы из `spine`/`toc`, сохраняйте иерархию (`part → chapter → section`). Очищайте HTML до plain text через `BeautifulSoup`.
- **PDF** — используйте `pypdf` для извлечения текста, `pdfplumber` для таблиц. Обнаруживайте заголовки по эвристике размера шрифта. Разбивайте на чанки по границам разделов, обнаруженным из TOC или паттернов заголовков.
- **DOCX** — используйте `python-docx`, сопоставляйте стили `Heading 1–3` со структурной иерархией.

### Пример BookExtractor (EPUB)

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

### Документация (Markdown, RST, AsciiDoc)

Парсите с помощью `mistletoe` (Markdown), `docutils` (RST), `asciidoctor` CLI (AsciiDoc). Сохраняйте блоки кода с языковыми тегами, извлекайте описания диаграмм (Mermaid/PlantUML) как структурные метаданные.

### История чатов

Парсите JSON-экспорты из DeepSeek/ChatGPT/Claude. Группируйте беседы по `conversation_id`, извлекайте пары Q&A (`user → assistant`) и обогащайте `model_name`, `timestamp` и количеством токенов как метаданными. Каждый ход Q&A становится чанком.

### Репозитории кода

Помимо коммитов GitLab, индексируйте исходный код с помощью `tree-sitter`/`ast` для AST-осведомлённого чанкинга на границах функций/классов. Встраивайте сообщения коммитов как перекрёстные ссылки на затронутые чанки кода.

---

## 3. Конвейер обогащения метаданных

`MetadataEnricher` (в `etl/chunker/semantic_chunker.py`) обогащает чанки с использованием:

1. **TF-IDF** — извлекает top-N ключевых слов из текста чанка.
2. **spaCy NER** — идентифицирует сущности PERSON, ORG, GPE, PRODUCT.
3. **SLM (ваша лёгкая модель)** — генерирует гипотетические вопросы и резюме (опционально).

Для добавления специфичного для типа источника обогащения расширьте метод `enrich()`:

```python
def enrich(self, chunk: Chunk) -> Chunk:
    if chunk.source_type == "book":
        chunk.keywords = self._extract_book_keywords(chunk.text)  # TF-IDF для прозы
    elif chunk.source_type == "code":
        chunk.keywords = self._extract_code_symbols(chunk.text)   # имена функций/классов
    # ... переход к стандартному
    return chunk
```

Пользовательские схемы метаданных определяются для каждого типа источника в конфигурации:

```yaml
books:
  metadata_schema:
    required: ["book_title", "author", "isbn", "chapter"]
    optional: ["publisher", "year", "language"]
```

---

## 4. Стратегия чанкинга для каждого типа источника

`MDKeyChunker` разбивает документы по структурной иерархии (H1→H2→H3). Настройка для каждого источника:

| Источник | Разбиение по | Перекрытие | Макс. токенов |
|----------|-------------|-----------|--------------|
| Книги | Главы, разделы | 100 | 2000 |
| Код | Функции, классы | 0 | 1000 |
| Чат | Ходы Q&A | 50 | 1500 |

Перекрёстное связывание встраивает метаданные `parent_id`, чтобы чанки из одного документа или главы можно было группировать при поиске.

---

## 5. Отслеживание версий для новых источников

`HashVersioning` вычисляет SHA-256 по тексту чанка + метаданным (см. `compute_chunk_hash()` в `etl/chunker/hash_versioning.py`). Для новых источников:

- **Книги** — хеш по `(текст главы, book_title, chapter_index)`. Изменения вызывают повторный чанкинг.
- **Код** — хеш по `(исходный код функции, file_path)`. Переиндексировать только изменённые функции.
- **Логика решения**: если `incremental=True`, сравнивать хеши; если изменились только метаданные (например, добавлено ключевое слово), обновить на месте без перевычисления эмбеддингов.

---

## 6. Построение графа для новых источников

`EntityRelationExtractor` извлекает сущности для каждого типа источника. Настройка с помощью конфигурируемой карты сущностей:

```yaml
graph:
  entity_types:
    book: [AUTHOR, BOOK, CHARACTER, CONCEPT, TOPIC]
    code: [CLASS, FUNCTION, MODULE, IMPORT, PATTERN]
    chat: [PERSON, TOPIC, DECISION, ACTION_ITEM]
```

Межисточниковые связи (например, связывание страницы Confluence об "Auth Service" с кодом GitLab, который её реализует) используют рёбра `RELATES_TO` с метаданными `source_type` на ребре.
