# Руководство по ETL-пайплайну

## Обзор

ETL-пайплайн (Extract, Transform, Load) загружает данные из корпоративных источников знаний в RAG-систему. Работает как отдельный процесс, на выделенной ETL-машине, отдельно от прокси-слоя.

### Этапы пайплайна

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Extract  │───>│  Chunk   │───>│  Graph   │───>│  Index   │───>│  Done    │
│          │    │          │    │(опция)   │    │          │    │          │
│Confluence│    │Семантик. │    │ Сущности │    │ Qdrant   │    │  WAL     │
│Jira      │    │Markdown  │    │ Связи    │    │ Гибрид.  │    │ Обновлён │
│GitLab    │    │HTML      │    │ Neo4j    │    │ Dense +  │    │          │
│Книги/Доки│    │Перекрыт. │    │          │    │ Sparse   │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### Ключевые принципы проектирования

- **Инкрементальный режим по умолчанию** — SHA-256 адресуемые чанки, WAL-чекпоинты
- **Работа в воздушном зазоре** — все модели предзагружены, без внешних API-вызовов
- **Плавная деградация** — Neo4j недоступен? Пропускаем расширение графа. OOM эмбеддера? Пропускаем индексацию.
- **Возможность возобновления** — WAL-чекпоинты позволяют перезапуск с последнего успешного этапа

## Архитектура

### Структура директорий

```
etl/
├── extractors/          # Экстракторы источников данных
│   ├── base_extractor.py    # Базовый ABC экстрактор
│   ├── confluence.py        # Экстрактор Confluence API
│   ├── jira.py              # Экстрактор Jira API
│   ├── gitlab.py            # Экстрактор GitLab API
│   ├── book_extractor.py    # Экстрактор EPUB/PDF/DOCX
│   ├── doc_extractor.py     # Экстрактор Markdown/RST/AsciiDoc
│   ├── chat_extractor.py    # Экстрактор экспорта чатов
│   └── image_extractor.py   # Извлечение изображений + подпись
├── chunker/             # Нарезка текста
│   ├── semantic_chunker.py  # Семантическая нарезка с обогащением метаданных
│   └── hash_versioning.py   # SHA-256 версионирование и детекция изменений
├── graph_builder/       # Граф знаний
│   ├── entity_extractor.py  # NER + извлечение связей
│   ├── neo4j_loader.py      # Загрузчик в Neo4j
│   └── schema.yaml          # Схема графа
├── indexer/             # Индексация в Qdrant
│   ├── qdrant_hybrid.py     # Dense + sparse + ColBERT индексация
│   ├── live_vector_lake.py  # Горячее/холодное хранение с откатом
│   └── wal_manager.py       # Менеджер WAL
├── scheduler/           # Оркестрация ETL
│   └── run_etl.py           # Главный оркестратор пайплайна
├── config/
│   └── etl_config.yaml      # Конфигурация пайплайна
└── requirements_etl.txt
```

## Справочник по конфигурации

Вся конфигурация находится в `etl/config/etl_config.yaml`. Основные разделы:

### Конфигурация источников

| Источник | Основные параметры | Описание |
|----------|-------------------|----------|
| **Confluence** | `url`, `username`, `token`, `space_keys` | API-эндпоинт, учётные данные, фильтр пространств |
| **Jira** | `url`, `username`, `token`, `jql` | API-эндпоинт, учётные данные, JQL-запрос |
| **GitLab** | `url`, `token`, `project_ids` | API-эндпоинт, PAT, фильтр проектов |

### Параметры нарезки

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `max_tokens` | 8000 | Максимум токенов в чанке |
| `overlap_tokens` | 200 | Перекрытие токенов между чанками |
| `min_chunk_tokens` | 100 | Минимальный размер чанка перед объединением |
| `use_slm` | false | Использовать SLM для обогащения метаданных |

### Параметры индексации

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `embedder_model` | `BAAI/bge-m3` | Модель эмбеддингов |
| `embedder_device` | `cpu` | Устройство (`cpu` или `cuda`) |
| `qdrant_host` | `localhost` | Хост Qdrant |
| `qdrant_port` | `6333` | Порт Qdrant |
| `collection_name` | `knowledge_base` | Имя коллекции |
| `batch_size` | `100` | Размер пакета для upsert |

### Параметры графа (опционально)

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `graph.enabled` | `false` | Включить извлечение графа |
| `graph.use_spacy` | `true` | Использовать spaCy для NER |
| `graph.spacy_model` | — | Модель spaCy (ОБЯЗАТЕЛЬНО при включении) |
| `graph.neo4j.enabled` | `false` | Включить загрузку в Neo4j |
| `graph.neo4j.uri` | `bolt://localhost:7687` | URI подключения Neo4j |

### Переменные окружения

Для конфиденциальных значений (токены, пароли) используйте переменные окружения или `etl/.env`:

```bash
cp etl/.env.example etl/.env
# Отредактируйте etl/.env с вашими учётными данными
```

Смотрите `etl/.env.example` для полного списка переменных.

## Запуск ETL

### Полный пайплайн

```bash
# Через Makefile (рекомендуется)
make etl

# Прямой вызов
cd etl && python scheduler/run_etl.py --config config/etl_config.yaml
```

### Отдельные источники

```bash
# Только Confluence
make etl-confluence

# Только Jira
make etl-jira

# Только GitLab
make etl-gitlab
```

### Опции пайплайна

```bash
# Пропуск отдельных этапов
python scheduler/run_etl.py --config config/etl_config.yaml --skip-graph
python scheduler/run_etl.py --config config/etl_config.yaml --skip-extract

# Принудительная переиндексация (игнорировать WAL)
python scheduler/run_etl.py --config config/etl_config.yaml --force-reindex

# Сброс WAL и запуск с нуля
python scheduler/run_etl.py --config config/etl_config.yaml --reset-wal
```

### Потоковый режим (реальное время)

```bash
# Запуск вебхук-сервера + потребителя потока
python scheduler/run_etl.py --streaming

# Только вебхук-сервер
python scheduler/run_etl.py --webhook-only

# Только потребитель потока
python scheduler/run_etl.py --consumer-only
```

## Добавление нового источника данных

### Шаг 1: Создайте экстрактор

Создайте `etl/extractors/my_source.py`:

```python
from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig

class MySourceExtractor(BaseExtractor):
    def __init__(self, config: ExtractorConfig):
        super().__init__(config)

    async def extract(self):
        """Возвращает объекты ExtractedDocument."""
        # Подключение к API источника
        # Итерация по документам
        # Yield ExtractedDocument для каждого
        ...

    async def validate_connection(self) -> bool:
        """Проверка доступности источника."""
        ...

    def should_process(self, doc: ExtractedDocument, last_hash: str) -> bool:
        """Проверка необходимости обработки (инкрементальный режим)."""
        if not last_hash:
            return True
        return self.compute_hash(doc.content) != last_hash
```

### Шаг 2: Добавьте конфигурацию

Добавьте в `etl/config/etl_config.yaml`:

```yaml
my_source:
  url: "https://my-source.example.com"
  token: "your_token"
  output_dir: "./raw_data/my_source"
  incremental: true
```

### Шаг 3: Зарегистрируйте в оркестраторе

Добавьте функцию извлечения в `etl/scheduler/run_etl.py`:

```python
from etl.extractors.my_source import MySourceExtractor

def run_extract_my_source(config: Dict, wal: WALManager) -> Path:
    my_config = config.get("my_source", {})
    extractor = MySourceExtractor(ExtractorConfig(
        source_name="my_source",
        source_type="my_source",
        base_url=my_config["url"],
        api_token=my_config.get("token", ""),
    ))
    # Запуск извлечения и возврат директории вывода
    ...
```

### Шаг 4: Добавьте в пайплайн

Вызовите вашу функцию извлечения в функции `main()` файла `run_etl.py`.

## Планирование ETL

### Через Cron

```bash
# Запуск ETL ежедневно в 2:00
0 2 * * * cd /path/to/rag-system && make etl >> /var/log/etl.log 2>&1

# Запуск Confluence каждые 6 часов
0 */6 * * * cd /path/to/rag-system && make etl-confluence
```

### Через systemd Timer

Создайте `/etc/systemd/system/etl.service`:

```ini
[Unit]
Description=RAG ETL Pipeline
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/rag-system
ExecStart=/usr/bin/python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml
```

Создайте `/etc/systemd/system/etl.timer`:

```ini
[Unit]
Description=Run RAG ETL daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now etl.timer
```

## Мониторинг и устранение неполадок

### WAL-чекпоинты

Файл WAL (`./wal/etl_wal.json`) отслеживает прогресс пайплайна:

```json
{
  "confluence_extractor": {"last_run": "2025-06-01T00:00:00"},
  "jira_extractor": {"last_run": "2025-06-01T12:00:00"},
  "indexing": {"added": 150, "deleted": 5}
}
```

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Connection refused` | API источника недоступен | Проверьте доступность источника |
| `401 Unauthorized` | Истёкший токен | Обновите API-токен |
| `OOM при индексации` | Большой размер пакета | Уменьшите `batch_size` в конфигурации |
| `ImportError: markdown` | Отсутствует зависимость | `pip install markdown` |
| `spaCy model not found` | Отсутствует модель NER | `python -m spacy download ru_core_news_sm` |

### Логи

По умолчанию логи пишутся в stdout. Для продакшена перенаправьте в файл:

```bash
python scheduler/run_etl.py --config config/etl_config.yaml 2>&1 | tee /var/log/etl.log
```

## Запуск тестов

```bash
# Все ETL-тесты
make test-etl

# Конкретный тест
python -m pytest tests/etl/test_semantic_chunker.py -v

# С покрытием
python -m pytest tests/etl/ --cov=etl --cov-report=html
```
