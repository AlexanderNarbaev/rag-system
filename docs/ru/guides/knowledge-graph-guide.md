# Руководство по графу знаний

## 1. Обзор

Граф знаний — это дополнительный слой, который связывает сущности (людей, проекты, технологии, документы), извлечённые из корпоративных источников данных — Confluence, Jira и GitLab — в структурированный граф, хранящийся в Neo4j.

**Зачем это нужно:**

- **Межсистемные связи** — Git-коммит можно проследить до задачи Jira, которую он решает, и до страницы Confluence, которая документирует функциональность.
- **Многопереходный поиск** — когда пользователь спрашивает «Кто работал над модулем аутентификации?», граф переходит от модуля к связанным задачам и далее к назначенным исполнителям.
- **Обогащённый контекст** — векторный поиск находит текстуально похожие фрагменты; расширение графа добавляет структурно связанную информацию, которая может не быть текстуально похожей.

> **Статус**: Граф знаний полностью реализован, но **по умолчанию отключён**. Включайте его только когда Neo4j доступен и заполнен через ETL-пайплайн.

---

## 2. Архитектура

Граф знаний охватывает два слоя:

```
┌─────────────────────────────────────────────────────────┐
│  ETL-слой (машина загрузки данных)                      │
│                                                         │
│  Экстракторы ─→ Чанкер ─→ EntityExtractor ─→ Neo4jLoader│
│  (Confluence,       │          │                  │      │
│   Jira,            ▼          ▼                  ▼      │
│   GitLab)    Индекс Qdrant  spaCy NER +       Neo4j     │
│                          SLM-отношения      (граф БД)   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Proxy-слой (API-сервер)                                │
│                                                         │
│  Запрос ─→ hybrid_search(Qdrant) ─→ top-k фрагментов   │
│                     │                                   │
│                     ▼                                   │
│           graph_expand_query(Neo4j) ─→ расш. контекст   │
│                     │                                   │
│                     ▼                                   │
│           rerank ─→ build_context ─→ генерация LLM      │
└─────────────────────────────────────────────────────────┘
```

### 2.1 ETL-сторона

| Компонент | Файл | Роль |
|-----------|------|------|
| `EntityRelationExtractor` | `etl/graph_builder/entity_extractor.py` | Извлекает сущности через spaCy NER; опционально извлекает отношения через SLM |
| `Neo4jLoader` | `etl/graph_builder/neo4j_loader.py` | Загружает сущности/отношения в Neo4j, управляет ограничениями, индексами и очисткой |
| Схема | `etl/graph_builder/schema.yaml` | Определяет типы сущностей, типы отношений, правила извлечения и конфигурацию Neo4j |

### 2.2 Proxy-сторона

| Компонент | Файл | Роль |
|-----------|------|------|
| `graph_expand_query()` | `proxy/app/core/retrieval.py` | Расширяет запрос пользователя, находя связанные сущности в Neo4j |
| Параметры конфигурации | `proxy/app/shared/config.py` | `GRAPH_ENABLED`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `USE_GRAPH_EXPANSION` |

---

## 3. Схема

### 3.1 Типы сущностей (узлы)

| Тип сущности | Метки Neo4j | Описание |
|--------------|-------------|----------|
| `PERSON` | `:Entity:Person` | Сотрудники, разработчики, авторы, менеджеры |
| `ORGANIZATION` | `:Entity:Organization` | Команды, отделы, компании |
| `TECHNOLOGY` | `:Entity:Technology` | Языки программирования, фреймворки, базы данных, инструменты |
| `PRODUCT` | `:Entity:Product` | Продукты, сервисы, модули, библиотеки |
| `PROJECT` | `:Entity` | Проекты Jira, проекты GitLab, пространства Confluence |
| `DOCUMENT` | `:Entity:Document` | Страницы Confluence, статьи, общие документы |
| `TICKET` | `:Entity:Ticket` | Задачи Jira (Bug, Task, Story, Epic) |
| `COMMIT` | `:Entity:Commit` | Git-коммиты из GitLab |
| `CODE_FILE` | `:Entity:CodeFile` | Файлы с исходным кодом |
| `CONCEPT` | `:Entity:Concept` | Абстрактные понятия, доменная терминология |
| `LOCATION` | `:Entity:Location` | Географические места, офисы |

### 3.2 Типы отношений (рёбра)

| Отношение | От | К | Пример |
|-----------|----|----|--------|
| `WORKS_ON` | PERSON | PROJECT, TICKET | «Иван работает над PROJ-123» |
| `AUTHORED_BY` | DOCUMENT, COMMIT, TICKET | PERSON | «Эту страницу написала Мария» |
| `MENTIONS` | DOCUMENT | PERSON, TECHNOLOGY, PRODUCT, CONCEPT | «Документ упоминает PostgreSQL» |
| `DEPENDS_ON` | PROJECT, TICKET, CODE_FILE | PROJECT, PRODUCT, TECHNOLOGY | «Бэкенд зависит от Redis» |
| `RELATES_TO` | любой | любой | Универсальная связь с оценкой силы |
| `CONTAINS` | PROJECT, DOCUMENT | CODE_FILE, DOCUMENT, TICKET | «Эпик содержит подзадачи» |
| `PARENT_OF` | TICKET, DOCUMENT | TICKET, DOCUMENT | «Эпик → Story → Подзадача» |
| `REFERENCES` | DOCUMENT | DOCUMENT | «Страница Confluence ссылается на другую» |
| `UPDATES` | COMMIT | CODE_FILE, TICKET | «Коммит изменяет auth.py» |
| `BELONGS_TO` | DOCUMENT, TICKET, CODE_FILE | PROJECT, ORGANIZATION | «Файл принадлежит бэкенд-репозиторию» |

Полное определение схемы: `etl/graph_builder/schema.yaml`

---

## 4. Конфигурация

### 4.1 Переменные окружения

```bash
# ── Proxy (proxy/.env) ──
GRAPH_ENABLED=false              # Включить расширение графа в прокси
NEO4J_URI=bolt://localhost:7687  # Адрес Neo4j (протокол Bolt)
NEO4J_USER=neo4j                 # Имя пользователя Neo4j
NEO4J_PASSWORD=                  # ОБЯЗАТЕЛЬНО при GRAPH_ENABLED=true
USE_GRAPH_EXPANSION=false        # Включить обход графа при поиске

# ── ETL (etl/.env) ──
GRAPH_ENABLED=false              # Включить извлечение сущностей и загрузку в Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
```

### 4.2 Когда включать каждый флаг

| Флаг | Слой | Назначение |
|------|------|------------|
| `GRAPH_ENABLED` (ETL) | ETL | Запускает извлечение сущностей при индексации и загружает результаты в Neo4j |
| `GRAPH_ENABLED` (Proxy) | Proxy | Разрешает прокси подключиться к Neo4j при старте |
| `USE_GRAPH_EXPANSION` | Proxy | Фактически запускает расширение графа при обработке запроса |

**Типичный порядок развёртывания:**
1. Установите `GRAPH_ENABLED=true` в ETL, запустите полный ETL для заполнения Neo4j.
2. Установите `GRAPH_ENABLED=true` и `USE_GRAPH_EXPANSION=true` в Proxy.
3. Перезапустите прокси — он подключится к Neo4j при старте.

### 4.3 Docker Compose

В `proxy/docker-compose.yml` есть определение сервиса Neo4j. При включении графа:

```yaml
neo4j:
  image: neo4j:5-community
  ports:
    - "7474:7474"   # HTTP-браузер
    - "7687:7687"   # Протокол Bolt
  environment:
    NEO4J_AUTH: neo4j/your-password
  volumes:
    - neo4j_data:/data
```

---

## 5. Как это работает

### 5.1 ETL: извлечение сущностей при индексации

Когда в конфигурации ETL установлено `GRAPH_ENABLED=true`:

1. **Извлечение** — после создания текстовых фрагментов `EntityRelationExtractor` запускает spaCy NER на каждом фрагменте для поиска сущностей типов PERSON, ORGANIZATION, TECHNOLOGY, PRODUCT, LOCATION и CONCEPT.
2. **Связывание** (опционально) — если настроен SLM-эндпоинт, экстрактор отправляет текст + список сущностей в SLM для вывода связей между ними.
3. **Загрузка** — `Neo4jLoader` записывает сущности и отношения в Neo4j с помощью MERGE-операций (идемпотентно). При первом запуске также создаёт индексы и ограничения.
4. **Очистка** — устаревшие сущности (из источников, отсутствующих в текущем ETL-пакете) удаляются.

```python
# Упрощённый ETL-поток
from etl.graph_builder.entity_extractor import EntityRelationExtractor
from etl.graph_builder.neo4j_loader import Neo4jLoader, batch_load_from_extractor

extractor = EntityRelationExtractor(use_spacy=True)
entities, relations = extractor.extract_from_chunk(text="...", source_id="confluence_123")

with Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="...") as loader:
    batch_load_from_extractor(loader, entities_as_dicts, relations_as_dicts)
```

### 5.2 Proxy: расширение графа при запросе

Когда установлены `GRAPH_ENABLED=true` и `USE_GRAPH_EXPANSION=true`:

1. Пользователь отправляет запрос на `/v1/chat/completions`.
2. `hybrid_search()` извлекает top-k фрагментов из Qdrant (dense + sparse RRF-слияние).
3. `graph_expand_query()` извлекает ключевые слова из запроса и ищет в Neo4j совпадающие сущности и их 1-переходных соседей.
4. Контекст графа (имена сущностей, типы и связанные сущности) добавляется к промпту LLM рядом с фрагментами, найденными векторным поиском.

```python
# В proxy/app/core/retrieval.py
def graph_expand_query(query: str, max_entities: int = 5) -> str:
    if not _GRAPH_ENABLED or not neo4j_driver:
        return ""  # graceful degradation — возвращаем пустую строку

    keywords = [w for w in query.split() if len(w) > 3][:3]
    # Cypher: ищем сущности по ключевым словам, возвращаем со связанными
    ...
```

### 5.3 Межсистемные связи

Главная ценность графа — соединение информации из разных систем:

```
Git-коммит abc123
  ──UPDATES──→ auth.py (CODE_FILE)
  ──MENTIONS──→ PROJ-456 (TICKET)
                ──REFERENCES──→ «Архитектура аутентификации» (Confluence DOCUMENT)
                ──AUTHORED_BY──→ Иван Иванов (PERSON)
                                  ──WORKS_ON──→ Backend-команда (ORGANIZATION)
```

Пользователь, спрашивающий «Кто поддерживает модуль аутентификации?», получает ответ, обогащённый графом, который связывает код, задачи, документацию и людей — даже если ни один документ не содержит всей этой информации.

---

## 6. Добавление пользовательских типов сущностей

### 6.1 Редактирование схемы

Добавьте новый тип сущности в `etl/graph_builder/schema.yaml`:

```yaml
entity_types:
  - name: "SERVICE"
    label: "Service"
    description: "Микросервис или API-эндпоинт"
    properties:
      - name: "name"
        type: "string"
        required: true
      - name: "endpoint"
        type: "string"
      - name: "team_owner"
        type: "string"
```

### 6.2 Добавление маппинга spaCy

В `entity_extractor.py` обновите словарь `type_map` в методе `extract_entities_spacy()`:

```python
type_map = {
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "PRODUCT": "PRODUCT",
    "EVENT": "EVENT",
    "WORK_OF_ART": "PRODUCT",
    # Добавьте ваш маппинг:
    "FAC": "SERVICE",  # метка spaCy FAC → SERVICE
}
```

### 6.3 Добавление ограничения Neo4j

В `neo4j_loader.py` добавьте ограничение в `create_constraints_and_indexes()`:

```python
constraints = [
    ...
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.id IS UNIQUE",
]
```

### 6.4 Добавление правила извлечения SLM

В `schema.yaml` добавьте правила извлечения для SLM:

```yaml
extraction_rules:
  entity_patterns:
    SERVICE:
      - keywords: ["auth-service", "user-api", "payment-gateway"]
      - pattern: "[a-z]+-service"
```

---

## 7. Устранение неполадок

### 7.1 Не удаётся подключиться к Neo4j при старте прокси

**Симптом**: В логах `Neo4j connection failed: ... Graph expansion disabled.`

**Причины**:
- Neo4j не запущен — проверьте `docker ps` или `systemctl status neo4j`.
- Неверный URI/порт — убедитесь, что `NEO4J_URI` соответствует вашему экземпляру Neo4j.
- Неверные учётные данные — проверьте `NEO4J_USER` и `NEO4J_PASSWORD`.

**Поведение**: Прокси деградирует gracefully. Расширение графа молча отключается; все остальные функции работают нормально.

### 7.2 Экстрактор сущностей не находит сущности

**Симптом**: ETL выполняется, но Neo4j пуст.

**Причины**:
- Модель spaCy не установлена — выполните `python -m spacy download ru_core_news_sm` (или `en_core_web_sm` для английского).
- `GRAPH_ENABLED=false` в конфигурации ETL.
- Текстовые фрагменты слишком короткие или не содержат именованных сущностей.

**Проверка**: Запустите экстрактор отдельно:
```bash
python -c "
from etl.graph_builder.entity_extractor import EntityRelationExtractor
ext = EntityRelationExtractor(use_spacy=True)
ents, rels = ext.extract_from_chunk('Иван Иванов работает над PROJ-123 используя PostgreSQL', 'test')
for e in ents: print(e.name, e.type)
"
```

### 7.3 Расширение графа возвращает пустую строку

**Симптом**: `graph_expand_query()` возвращает `""`.

**Причины**:
- `GRAPH_ENABLED=false` или `USE_GRAPH_EXPANSION=false` в конфигурации прокси.
- Драйвер Neo4j не удалось инициализировать (ошибка подключения при старте).
- Нет сущностей, соответствующих ключевым словам запроса (слова запроса ≤ 3 символов, или нет совпадающих сущностей в графе).

### 7.4 Медленные запросы к графу

**Симптом**: Задержка прокси значительно увеличивается при включённом графе.

**Причины**:
- Отсутствуют индексы — выполните `Neo4jLoader.create_constraints_and_indexes()` или проверьте наличие индексов на `Entity.name` и `Entity.type`.
- Большой граф без ограничений — параметр `max_entities` в `graph_expand_query()` ограничивает результаты.

### 7.5 Ошибка импорта: пакет `neo4j` не установлен

**Симптом**: `ImportError: neo4j driver is required`.

**Решение**: `pip install neo4j` (ETL) или он включён в `requirements_proxy.txt` (Proxy).

---

## Ссылки

- [Стратегия графа знаний (углублённый обзор)](knowledge-graph-strategy.md) — детальный дизайн многопереходного обхода, оценки путей, временной осведомлённости и самообогащения
- Определение схемы: `etl/graph_builder/schema.yaml`
- Экстрактор сущностей: `etl/graph_builder/entity_extractor.py`
- Загрузчик Neo4j: `etl/graph_builder/neo4j_loader.py`
- Proxy-поиск: `proxy/app/core/retrieval.py`
