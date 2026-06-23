# Руководство по развёртыванию ETL

ETL-пайплайн работает на выделенной машине (или на той же машине, что и прокси, в небольших развёртываниях). Он извлекает данные из Confluence, Jira, GitLab и других источников, разбивает документы семантически на чанки, извлекает сущности для графа знаний и индексирует всё в Qdrant.

---

## Предварительные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **Python** | 3.11 | 3.12 |
| **RAM** | 8 GB | 16+ GB |
| **Диск** | 50 GB SSD | 200+ GB NVMe |
| **CPU** | 4 ядра | 8+ ядер |
| **Сеть** | Доступ к системам-источникам | — |
| **Qdrant** | Запущен и доступен | Порты 6333, 6334 |
| **Neo4j** (опционально) | Запущен и доступен | Порт 7687 |

ETL-машина должна иметь сетевой доступ к:
- Серверу Qdrant (по умолчанию: `http://<qdrant-host>:6333`)
- Серверу Neo4j (опционально, по умолчанию: `bolt://<neo4j-host>:7687`)
- Системам-источникам: Confluence, Jira, GitLab

---

## Установка

```bash
# Клонируйте репозиторий (или перенесите tarball в air-gapped среде)
cd /opt
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Установите зависимости ETL
cd etl
pip install -r requirements_etl.txt

# Для air-gapped:
pip install --no-index --find-links /opt/pip-offline -r requirements_etl.txt
```

---

## Конфигурация

Отредактируйте `etl/config/etl_config.yaml`. Все опции:

### WAL (Write-Ahead Log)

Управляет инкрементальным чекпоинтингом и возможностью возобновления.

```yaml
wal:
  wal_file: "./wal/etl_wal.json"    # Путь к файлу WAL
  use_lock: true                     # Блокировка на основе файла для конкурентной безопасности
  lock_timeout: 30                   # Таймаут захвата блокировки (секунды)
```

Файл WAL отслеживает:
- `last_confluence_sync` — временная метка последней успешной выгрузки Confluence
- `last_jira_sync` — временная метка последней успешной выгрузки Jira
- `last_gitlab_sync` — временная метка последней успешной выгрузки GitLab
- `total_indexed` — общее количество проиндексированных чанков
- `completed_sources` — список источников, завершённых в последнем запуске
- `last_successful_run` — временная метка последнего полного запуска

**Восстановление:** Если ETL аварийно завершился, удалите `wal/etl_wal.json` для принудительной полной переиндексации или запустите с `--sources` для пропуска завершённых источников.

### Confluence

```yaml
confluence:
  url: "https://confluence.internal.company.com"
  username: "etl_bot"
  token: "your_personal_access_token"   # Personal Access Token или пароль
  space_keys:                           # Список ключей пространств; null или пропустите для всех
    - "DEV"
    - "OPS"
    - "QA"
  output_dir: "./raw_data/confluence"
  incremental: true                     # Извлекать только изменённые страницы с последнего запуска
  download_attachments: true            # Загружать и индексировать вложенные файлы
  max_versions: 0                       # 0 = все версии; N = хранить последние N
  api_version: "2"                      # "2" (CQL) или "1" (legacy)
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `url` | string | *обязательно* | Базовый URL Confluence |
| `username` | string | *обязательно* | Имя пользователя бот-аккаунта |
| `token` | string | *обязательно* | Personal Access Token или пароль |
| `space_keys` | list | `null` | Ключи пространств для выгрузки; пропустите для всех доступных |
| `incremental` | bool | `true` | Извлекать только страницы, изменённые с последнего запуска |
| `download_attachments` | bool | `true` | Загружать и индексировать PDF, изображения (OCR), документы Office |
| `max_versions` | int | `0` | Хранить только последние N версий на страницу |
| `api_version` | string | `"2"` | Версия Confluence REST API |

### Jira

```yaml
jira:
  url: "https://jira.internal.company.com"
  username: "etl_bot"
  token: "your_api_token"
  jql: "project in (DEV, OPS) ORDER BY updated DESC"
  output_dir: "./raw_data/jira"
  incremental: true
  download_attachments: true
  max_issues_per_run: 0                 # 0 = без ограничений
  fields: "*all"
  expand: "changelog,renderedBody"
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `url` | string | *обязательно* | Базовый URL Jira |
| `username` | string | *обязательно* | Имя пользователя бот-аккаунта |
| `token` | string | *обязательно* | API-токен или пароль |
| `jql` | string | *обязательно* | JQL-запрос для фильтрации задач |
| `incremental` | bool | `true` | Извлекать только задачи, обновлённые с последнего запуска |
| `download_attachments` | bool | `true` | Загружать и индексировать вложенные файлы |
| `max_issues_per_run` | int | `0` | Ограничить задачи за запуск (0 = без ограничений) |
| `fields` | string | `"*all"` | Поля Jira для включения в вывод |
| `expand` | string | — | Дополнительные расширения Jira API |

### GitLab

```yaml
gitlab:
  url: "https://gitlab.internal.company.com"
  token: "your_personal_access_token"
  project_ids: null                     # null = все доступные проекты
  output_dir: "./raw_data/gitlab"
  incremental: true
  fetch_commits: true
  fetch_files: true
  fetch_merge_requests: true
  max_commits_per_project: 1000
  since_date: null                      # Дата ISO: "2025-01-01T00:00:00Z"
  file_paths_filter:
    - "*.py"
    - "*.md"
    - "Dockerfile"
    - "*.yaml"
    - "*.yml"
    - "*.sql"
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `url` | string | *обязательно* | Базовый URL GitLab |
| `token` | string | *обязательно* | Personal Access Token с `read_api`, `read_repository` |
| `project_ids` | list | `null` | Конкретные ID проектов; пропустите для всех доступных |
| `incremental` | bool | `true` | Извлекать только изменения с последнего запуска |
| `fetch_commits` | bool | `true` | Извлекать сообщения коммитов и диффы |
| `fetch_files` | bool | `true` | Извлекать содержимое файлов (фильтруется `file_paths_filter`) |
| `fetch_merge_requests` | bool | `true` | Извлекать заголовки, описания и обсуждения MR |
| `max_commits_per_project` | int | `1000` | Ограничить коммиты на проект за запуск |
| `since_date` | string | `null` | Обрабатывать только данные после этой даты ISO |
| `file_paths_filter` | list | — | Glob-паттерны для файлов для индексации |

### Чанкинг

```yaml
chunking:
  max_tokens: 8000                     # Максимальный размер чанка (для окна контекста эмбеддера)
  overlap_tokens: 200                  # Перекрытие между соседними чанками
  min_chunk_tokens: 100                # Минимальный размер чанка (меньшие объединяются с соседним)
  use_slm: false                       # Использовать SLM для обогащения чанков
  slm_endpoint: "http://localhost:8080/v1/completions"
  output_dir: "./chunks"               # Директория для JSON-файлов чанков
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `max_tokens` | int | `8000` | Максимум токенов на чанк (ограничение окна контекста эмбеддера) |
| `overlap_tokens` | int | `200` | Перекрытие токенов между последовательными чанками |
| `min_chunk_tokens` | int | `100` | Минимальный размер чанка; меньшие чанки объединяются |
| `use_slm` | bool | `false` | Использовать SLM для обогащения метаданных чанков |
| `output_dir` | string | `"./chunks"` | Директория для JSON-файлов чанков |

Семантический чанкер (`MDKeyChunker`) разбивает документы по заголовкам и разделам markdown, соблюдая структуру документа. Он создаёт чанки, которые:

- **Самодостаточны** — каждый чанк имеет достаточно контекста для независимого понимания
- **Версионированы** — хешированы SHA-256, контентно-адресуемы
- **Отслеживаемы** — ID чанков связаны с исходными документами и версиями

### Индексация

```yaml
indexing:
  qdrant_host: "localhost"
  qdrant_port: 6333
  collection_name: "knowledge_base"
  embedder_model: "your-embedding-model"   # например, "BAAI/bge-m3"
  embedder_device: "cpu"               # "cpu" или "cuda"
  batch_size: 100
  hot_dir: "./hot_chunks"              # Горячее хранилище (текущие версии)
  cold_dir: "./cold_chunks"            # Холодное хранилище (исторические версии, Parquet)
  lake_dir: "./cold_lake"              # Холодное хранилище LiveVectorLake
  use_delta: false                     # Использовать формат Delta Lake
  version_wal: "./wal/version_wal.json"
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `qdrant_host` | string | `"localhost"` | Имя хоста сервера Qdrant |
| `qdrant_port` | int | `6333` | gRPC-порт Qdrant |
| `collection_name` | string | `"knowledge_base"` | Имя коллекции Qdrant |
| `embedder_model` | string | `"your-embedding-model"` | Модель sentence-transformers для эмбеддингов |
| `embedder_device` | string | `"cpu"` | Устройство для эмбеддинга: `cpu`, `cuda`, `cuda:0` |
| `batch_size` | int | `100` | Чанков на батч эмбеддинга |
| `hot_dir` | string | `"./hot_chunks"` | Горячее хранилище для текущих активных чанков |
| `cold_dir` | string | `"./cold_chunks"` | Холодное хранилище для исторических версий |
| `lake_dir` | string | `"./cold_lake"` | Холодное хранилище LiveVectorLake |
| `use_delta` | bool | `false` | Использовать формат Delta Lake для холодного хранения |
| `version_wal` | string | `"./wal/version_wal.json"` | WAL для отслеживания версий чанков |

**LiveVectorLake** стратифицирует чанки на:
- **Горячие** — текущие версии, всегда в Qdrant
- **Холодные** — исторические версии, хранятся как файлы Parquet, загружаются по требованию

### Граф знаний (опционально)

```yaml
graph:
  enabled: false                       # Включить построение графа
  use_spacy: true                      # Использовать spaCy для NER
  spacy_model: "ru_core_news_sm"       # например, "ru_core_news_sm" для русского, "en_core_web_sm" для английского
  use_slm: false                       # Использовать SLM для извлечения связей
  slm_endpoint: "http://localhost:8080/v1/completions"
  cache_dir: "./entity_cache"          # Кэш извлечения сущностей
  neo4j:
    enabled: false
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "your_neo4j_password"
    database: "neo4j"
```

| Параметр | Тип | По умолчанию | Описание |
|---------|------|-------------|----------|
| `enabled` | bool | `false` | Включить построение графа |
| `use_spacy` | bool | `true` | Использовать spaCy для распознавания именованных сущностей |
| `spacy_model` | string | `"ru_core_news_sm"` | Модель spaCy для NER (зависит от языка) |
| `use_slm` | bool | `false` | Использовать SLM для извлечения связей (выше качество, медленнее) |
| `cache_dir` | string | `"./entity_cache"` | Кэшировать извлечённые сущности |
| `neo4j.enabled` | bool | `false` | Загружать сущности и связи в Neo4j |
| `neo4j.uri` | string | — | Neo4j Bolt URI |
| `neo4j.user` | string | `"neo4j"` | Имя пользователя Neo4j |
| `neo4j.password` | string | — | Пароль Neo4j |
| `neo4j.database` | string | `"neo4j"` | Имя базы данных Neo4j |

---

## Запуск ETL-пайплайна

### Полный запуск

```bash
cd etl
python scheduler/run_etl.py --config config/etl_config.yaml
```

### Частичный запуск (конкретные источники)

```bash
# Только Confluence и Jira
python scheduler/run_etl.py --config config/etl_config.yaml --sources confluence,jira

# Только GitLab
python scheduler/run_etl.py --config config/etl_config.yaml --sources gitlab
```

### Полная переиндексация (игнорировать WAL)

```bash
python scheduler/run_etl.py --config config/etl_config.yaml --full
```

Это удаляет все существующие чанки, очищает WAL и заново извлекает всё с нуля. **Внимание:** это может занять часы в зависимости от объёма данных.

### Пробный запуск

```bash
python scheduler/run_etl.py --config config/etl_config.yaml --dry-run
```

Показывает, что будет извлечено, без внесения изменений.

### Через Docker

```bash
# Сборка образа ETL
docker build -f Dockerfile.etl -t rag-etl .

# Запуск с примонтированными томами для сохранения WAL
docker run --rm --network=host \
  -v $(pwd)/wal:/app/etl/wal \
  -v $(pwd)/chunks:/app/etl/chunks \
  -v $(pwd)/raw_data:/app/etl/raw_data \
  rag-etl --config /app/etl/config/etl_config.yaml
```

---

## Планирование

ETL спроектирован для запуска по расписанию. Используйте cron или systemd timers:

### Cron (каждые 4 часа)

```cron
# /etc/cron.d/rag-etl
0 */4 * * * rag cd /opt/rag-system/etl && python scheduler/run_etl.py --config config/etl_config.yaml >> /var/log/rag-etl.log 2>&1
```

### systemd Timer

```ini
# /etc/systemd/system/rag-etl.service
[Unit]
Description=RAG System ETL Pipeline
After=network.target

[Service]
Type=oneshot
User=rag
WorkingDirectory=/opt/rag-system/etl
ExecStart=/usr/bin/python3 scheduler/run_etl.py --config config/etl_config.yaml
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/rag-etl.timer
[Unit]
Description=RAG System ETL Pipeline Timer

[Timer]
OnCalendar=*-*-* 00/4:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable rag-etl.timer
systemctl start rag-etl.timer
```

---

## Мониторинг работоспособности ETL

### Проверка статуса WAL

```bash
python -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
print('Last Confluence sync:', wal.get('last_confluence_sync', 'never'))
print('Last Jira sync:', wal.get('last_jira_sync', 'never'))
print('Last GitLab sync:', wal.get('last_gitlab_sync', 'never'))
print('Total indexed chunks:', wal.get('total_indexed', 0))
print('Last successful run:', wal.get('last_successful_run', 'never'))
print('Completed sources:', wal.get('completed_sources', []))
"
```

### Проверка коллекции Qdrant

```bash
curl http://localhost:6333/collections/knowledge_base | python -m json.tool
```

Проверьте:
- `vectors_count` — должно увеличиваться после каждого запуска ETL
- `segments_count` — количество проиндексированных сегментов
- `points_count` — общее количество проиндексированных точек

### Мониторинг использования диска

```bash
# Проверка хранилища чанков
du -sh etl/chunks/ etl/hot_chunks/ etl/cold_chunks/ etl/cold_lake/

# Проверка сырых данных
du -sh etl/raw_data/confluence/ etl/raw_data/jira/ etl/raw_data/gitlab/

# Очистка старых холодных чанков (старше 30 дней)
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete
```

---

## Устранение неполадок

### Повреждение WAL

```bash
# Симптом: "WAL file corrupted" или ETL зависает
rm etl/wal/etl_wal.json
python scheduler/run_etl.py --config config/etl_config.yaml --full
```

### Ограничения скорости API

```bash
# Симптом: "429 Too Many Requests"
# Добавьте задержку между вызовами API:
export ETL_RATE_LIMIT_DELAY=1.0

# Для GitLab уменьшите объём коммитов:
# Измените etl_config.yaml: gitlab.max_commits_per_project: 100
```

### Частичная переиндексация после сбоя

```bash
# Проверьте, какие источники завершены:
python -c "import json; wal=json.load(open('etl/wal/etl_wal.json')); print(wal.get('completed_sources',[]))"

# Переиндексируйте только отказавшие источники:
python scheduler/run_etl.py --config config/etl_config.yaml --sources jira,gitlab
```

### Переполнение диска

```bash
# Очистка старых данных:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete
find etl/raw_data/ -name "*.json" -mtime +7 -delete

# Переместите холодное хранилище на больший том:
mkdir -p /mnt/cold_storage/rag_lake
ln -s /mnt/cold_storage/rag_lake etl/cold_lake
```

---

## Настройка производительности

| Сценарий | Параметр | Рекомендация |
|----------|---------|-------------|
| Большой объём документов (>100K) | `chunking.max_tokens` | Увеличьте до `8000` для уменьшения количества чанков |
| Машина с ограниченной памятью | `indexing.batch_size` | Уменьшите до `50` |
| Доступен GPU | `indexing.embedder_device` | Установите `cuda` для ускорения в 10–50× |
| Медленный Confluence API | `confluence.max_versions` | Установите `1` (только последняя) |
| Большие репозитории GitLab | `gitlab.max_commits_per_project` | Уменьшите до `100` |
| Медленное построение графа | `graph.use_slm` | Установите `false`, используйте только spaCy |

---

## Автономное (Air-Gapped) развёртывание

На машине с интернетом:

```bash
# Загрузите модели spaCy (замените на ваши языковые модели)
python -m spacy download ru_core_news_sm    # Русский
python -m spacy download en_core_web_sm     # Английский

# Упакуйте для переноса
tar -czf spacy_models.tar.gz $(python -c "import spacy; print(spacy.util.get_package_path('ru_core_news_sm'))") \
  $(python -c "import spacy; print(spacy.util.get_package_path('en_core_web_sm'))")
```

На автономной машине:

```bash
# Распакуйте модели spaCy
tar -xzf spacy_models.tar.gz -C /opt/
export SPACY_DATA=/opt/spacy_data

# Установите офлайн-пакеты
pip install --no-index --find-links /opt/pip-offline -r requirements_etl.txt
```
