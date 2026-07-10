# Федеративный RAG

**Версия:** v2.0.0 | **Последнее обновление:** 2026-07-06

Руководство по развёртыванию и эксплуатации федеративного RAG-прокси — автономного сервиса, который распределяет запросы по множеству независимых RAG-инстансов (силосов), объединяет результаты и генерирует ответы из унифицированного корпуса.

---

## Содержание

1. [Концепция](#1-концепция)
2. [Архитектура](#2-архитектура)
3. [Быстрый старт](#3-быстрый-старт)
4. [Справочник по конфигурации](#4-справочник-по-конфигурации)
5. [Схема конфигурации силоса](#5-схема-конфигурации-силоса)
6. [Режимы федерации](#6-режимы-федерации)
7. [Стратегии объединения](#7-стратегии-объединения)
8. [Справочник по API](#8-справочник-по-api)
9. [Контроль доступа](#9-контроль-доступа)
10. [Делегирование генерации](#10-делегирование-генерации)
11. [Автоматические выключатели](#11-автоматические-выключатели)
12. [Мониторинг](#12-мониторинг)
13. [Развёртывание](#13-развёртывание)
14. [Устранение неполадок](#14-устранение-неполадок)

---

## 1. Концепция

### Что такое федеративный RAG?

Федеративный RAG позволяет запрашивать **несколько независимых RAG-инстансов** (называемых «силосами») через единую точку входа. Каждый силос поддерживает собственную векторную базу данных, граф знаний и коллекцию документов. Слой федерации:

1. Принимает единый запрос от пользователя
2. Распределяет запрос по нескольким силосам **параллельно** (через `asyncio.gather`)
3. Объединяет результаты с использованием настраиваемых стратегий
4. Опционально генерирует финальный ответ с помощью общего LLM или делегирует основному силосу

### Когда использовать

| Сценарий | Зачем нужен федеративный RAG |
|----------|------------------------------|
| **Мультиотделовые знания** | HR, инженерия, финансы — каждый имеет отдельный RAG-инстанс с разными правами доступа |
| **Географически распределённые команды** | Силосы в US-East, US-West, EU-West с оптимизацией локальной задержки |
| **Слияния и поглощения** | Объединение RAG-систем разных компаний без миграции данных |
| **Требования изоляции данных** | Юридические/политические требования хранить определённые наборы документов на отдельной инфраструктуре |
| **Независимое масштабирование** | Высоконагруженная инженерная документация и малонагруженная HR-документация масштабируются независимо |

### Топология с несколькими силосами

```
┌──────────────────────────────────────────────────────┐
│                  Federated RAG Proxy                  │
│                    (Port 8001)                        │
│                                                       │
│  /v1/chat/completions   /v1/search   /v1/silos       │
│  /v1/health             /v1/models   /metrics         │
└───────┬─────────────────┬──────────────────┬──────────┘
        │                 │                  │
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ HR Silo │       │ Eng Silo│       │ Fin Silo│
   │ Qdrant-A│       │ Qdrant-B│       │ Qdrant-C│
   │ Neo4j-A │       │ Neo4j-B │       │ Neo4j-C │
   │ LLM-A   │       │ LLM-B   │       │ LLM-C   │
   └─────────┘       └─────────┘       └─────────┘
```

**Ключевой принцип:** Каждый силос — это полноценный, автономный RAG-прокси с собственным эндпоинтом `/v1/chat/completions`. Слой федерации **не** имеет собственного векторного хранилища — это чисто маршрутизатор, объединитель и делегатор генерации.

---

## 2. Архитектура

### Обзор компонентов

```
federation/
├── app/
│   ├── main.py              # FastAPI app, 6 endpoints, lifespan management
│   ├── router.py            # federated_search(): fan-out orchestration
│   ├── merger.py            # weighted_rrf, round_robin, top_per_instance strategies
│   ├── silo_client.py       # Async HTTP fan-out to individual silos
│   ├── silo_registry.py     # SiloConfig registry with access group filtering
│   ├── circuit_breaker.py   # Per-silo circuit breaker (CLOSED → OPEN → HALF_OPEN)
│   ├── auto_router.py       # Keyword-based query → silo classification
│   ├── auth.py              # check_silo_access()
│   ├── jwt_auth.py          # JWT token → user_groups extraction
│   ├── models.py            # SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
│   ├── config.py            # All FEDERATION_* env vars
│   ├── metrics.py           # 7 Prometheus metrics
│   └── exceptions.py        # FederationError hierarchy
├── tests/                   # 14 test files
├── Dockerfile
├── docker-compose.federation.yml
├── requirements.txt
└── .env.example
```

### Поток запроса

```
Client Request
      │
      ▼
┌─────────────────┐
│  JWT Extraction  │  extract_user_groups() → ["admin", "engineering"]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Mode Resolution │  auto → classify_query() | strict → target_silos | merge → all accessible
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Access Filter   │  list_accessible(user_groups) → [SiloConfig, ...]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Circuit Breaker  │  For each silo: allow_request()? → active | skipped
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Parallel Fanout │  asyncio.gather(query_silo(s1), query_silo(s2), ...)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Merge Results   │  weighted_rrf() | round_robin() | top_per_instance()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate Answer  │  Direct LLM (FEDERATION_LLM_ENDPOINT) | Primary silo delegation
└────────┬────────┘
         │
         ▼
   Client Response
```

### Ключевые проектные решения

| Решение | Обоснование |
|---------|-------------|
| **Асинхронный fan-out (asyncio.gather)** | Параллелизует запросы к силосам; суммарная задержка ≈ max(задержка_силоса), а не сумма |
| **Автоматический выключатель на силос** | Предотвращает каскадные отказы; 5 последовательных сбоев → OPEN на 30 секунд |
| **Отсутствие векторного хранилища в федерации** | Федерация не хранит состояние; весь поиск происходит в силосах |
| **Частичный отказ с graceful degradation** | Если 1 из 3 силосов не отвечает, федерация возвращает результаты от двух остальных |
| **rag_skip_generation при запросах к силосам** | Силосы возвращают только `rag_sources` (чанки), а не полные ответы — экономия LLM-инференса |

---

## 3. Быстрый старт

### Предварительные требования

- **Docker** 24.0+ и **Docker Compose** v2.20+
- Минимум **один работающий RAG-прокси** (слой федерации запрашивает силосы через их эндпоинты `/v1/chat/completions`)
- Python 3.12+ (при запуске без Docker)

### 3.1 Развёртывание через Docker (рекомендуется)

```bash
# From the project root
cd federation

# Copy and edit the environment file
cp .env.example .env

# Edit .env to point to your silos
# Minimum: update FEDERATION_INSTANCES_JSON

# Start the federation proxy
docker compose -f docker-compose.federation.yml up -d

# Verify it's running
curl http://localhost:8001/v1/health
```

### 3.2 Минимальная конфигурация

Создайте `federation/.env`:

```bash
# Federation mode: auto | strict | merge
FEDERATION_MODE=auto

# At least one silo (pointing to an existing RAG proxy)
FEDERATION_INSTANCES_JSON='[
  {
    "id": "hr",
    "name": "HR Knowledge Base",
    "proxy_url": "http://localhost:8000/v1",
    "weight": 1.0,
    "access_groups": ["admin", "hr"],
    "collections": ["knowledge_base"],
    "is_primary": true
  }
]'

# Merge strategy
FEDERATION_MERGE_STRATEGY=weighted_rrf
FEDERATION_MERGE_K=60
FEDERATION_RRF_K=60

# Timeouts
FEDERATION_TOTAL_TIMEOUT_S=30
FEDERATION_PER_INSTANCE_TIMEOUT_S=10
```

### 3.3 Первый запрос

```bash
# Chat completion — search + generate
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-federated",
    "messages": [
      {"role": "user", "content": "What is our sick leave policy?"}
    ]
  }'

# Search only — retrieve chunks without generation
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "vacation policy",
    "federation_top_k": 20
  }'

# List accessible silos
curl http://localhost:8001/v1/silos

# List models
curl http://localhost:8001/v1/models

# Health check
curl http://localhost:8001/v1/health
```

---

## 4. Справочник по конфигурации

Вся конфигурация задаётся через переменные окружения в `federation/.env`.

### Обязательные переменные

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_INSTANCES_JSON` | `[]` | JSON-массив конфигураций силосов. Должен содержать хотя бы один силос. |
| `FEDERATION_MODE` | `auto` | Режим федерации: `auto`, `strict` или `merge`. См. [раздел 6](#6-режимы-федерации). |

### Конфигурация объединения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_MERGE_STRATEGY` | `weighted_rrf` | Стратегия объединения: `weighted_rrf`, `round_robin` или `top_per_instance`. См. [раздел 7](#7-стратегии-объединения). |
| `FEDERATION_MERGE_K` | `60` | Максимальное количество чанков после объединения (top-K). Диапазон: 1–200. |
| `FEDERATION_RRF_K` | `60` | Постоянная сглаживания RRF. Более высокие значения снижают чувствительность к позиции ранга. Используется только стратегией `weighted_rrf`. |

### Конфигурация тайм-аутов

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_PER_INSTANCE_TIMEOUT_S` | `10` | Тайм-аут для каждого отдельного HTTP-запроса к силосу (секунды). |
| `FEDERATION_TOTAL_TIMEOUT_S` | `30` | Бюджетный общий тайм-аут — логируется для мониторинга, не применяется на уровне HTTP (FastAPI обрабатывает тайм-ауты на уровне запроса). |

### Конфигурация автоматических выключателей

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_CIRCUIT_BREAKER_THRESHOLD` | `5` | Количество последовательных сбоев перед открытием автоматического выключателя. |
| `FEDERATION_CIRCUIT_BREAKER_RECOVERY_S` | `30` | Ожидание в секундах перед попыткой восстановления (переход в HALF_OPEN). |

### Конфигурация LLM / генерации

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_LLM_ENDPOINT` | `""` | Прямой эндпоинт LLM для генерации. Если задан, слой федерации генерирует ответы самостоятельно вместо делегирования основному силосу. Пример: `http://llm-host:8000/v1` |
| `FEDERATION_LLM_MODEL` | `""` | Имя модели для использования с `FEDERATION_LLM_ENDPOINT` при прямой генерации. |
| `FEDERATION_AUTO_SLM_ENABLED` | `true` | Включает автороутинг на основе ключевых слов в режиме `auto`. При `false` режим `auto` распределяет запросы по всем силосам. |

### Конфигурация аутентификации

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_AUTH_ENABLED` | `false` | При `true` федерация извлекает группы пользователей из JWT-токенов. При `false` использует `FEDERATION_DEFAULT_GROUPS`. |
| `FEDERATION_JWT_SECRET` | `""` | Секретный ключ для проверки подписи JWT. Использует переменную окружения `JWT_SECRET` как запасной вариант. |
| `FEDERATION_JWT_ALGORITHM` | `HS256` | Алгоритм подписи JWT. Использует переменную окружения `JWT_ALGORITHM` как запасной вариант. |
| `FEDERATION_DEFAULT_GROUPS` | `admin` | Через запятую список групп, назначаемых при отключённой аутентификации. Пример: `admin,engineering,hr`. |

### Альтернатива: файл конфигурации силосов

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FEDERATION_INSTANCES_FILE` | `""` | Путь к JSON-файлу с конфигурациями силосов. Если задан, переопределяет `FEDERATION_INSTANCES_JSON`. Полезно для монтирования через ConfigMap в K8s. |

---

## 5. Схема конфигурации силоса

Каждый силос в `FEDERATION_INSTANCES_JSON` — это JSON-объект со следующими полями:

### Полная схема

```json
{
  "id": "hr",
  "name": "HR Knowledge Base",
  "proxy_url": "http://rag-hr.internal:8000/v1",
  "weight": 1.0,
  "access_groups": ["admin", "hr"],
  "collections": ["knowledge_base"],
  "api_key": "sk-hr-proxy-key-12345",
  "timeout_s": 10,
  "is_primary": true
}
```

### Справочник по полям

| Поле | Тип | Обязательно | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `id` | string | **Да** | — | Уникальный идентификатор силоса. Используется в метаданных федерации и именовании автоматических выключателей. |
| `name` | string | **Да** | — | Человекочитаемое имя силоса для ответов и логов. |
| `proxy_url` | string | **Да** | — | Базовый URL RAG-прокси. Должен включать префикс пути (например, `http://host:8000/v1`). Конечные слеши удаляются автоматически. |
| `weight` | float | Нет | `1.0` | Относительный вес для стратегии объединения `weighted_rrf`. Больший вес = результаты силоса ранжируются выше. Должен быть > 0. |
| `access_groups` | string[] | Нет | `[]` | Список групп, имеющих доступ к силосу. Пользователь должен состоять хотя бы в одной группе. Пустой список = без ограничений по группам. |
| `collections` | string[] | Нет | `[]` | Коллекции Qdrant, доступные в силосе. Информационное поле — не применяется на уровне федерации. |
| `api_key` | string | Нет | `null` | Bearer-токен, отправляемый как `Authorization: Bearer <api_key>` к прокси силоса. |
| `timeout_s` | int | Нет | `10` | Тайм-аут для конкретного силоса (переопределяет `FEDERATION_PER_INSTANCE_TIMEOUT_S`). |
| `is_primary` | boolean | Нет | `false` | При `true` этот силос используется для делегирования LLM-генерации, если не настроен прямой `FEDERATION_LLM_ENDPOINT`. Рекомендуется только один основной силос. |

### Правила валидации

Метод `SiloRegistry.validate()` обеспечивает:
- Каждый `id` должен быть уникальным (дублирующиеся ID вызывают `ConfigError`)
- `weight` должен быть > 0
- `proxy_url` не должен быть пустым

### Примеры

**Одиночный основной силос (минимальный):**
```json
[
  {
    "id": "all",
    "name": "All Knowledge",
    "proxy_url": "http://localhost:8000/v1",
    "is_primary": true
  }
]
```

**Мультиотделовой с контролем доступа:**
```json
[
  {
    "id": "eng",
    "name": "Engineering Wiki",
    "proxy_url": "http://rag-eng.internal:8000/v1",
    "weight": 1.2,
    "access_groups": ["engineering", "admin"],
    "collections": ["eng_docs", "eng_wiki"],
    "api_key": "sk-eng-xxx",
    "timeout_s": 8,
    "is_primary": true
  },
  {
    "id": "hr",
    "name": "HR Knowledge Base",
    "proxy_url": "http://rag-hr.internal:8000/v1",
    "weight": 1.0,
    "access_groups": ["hr", "admin"],
    "collections": ["hr_policies", "hr_benefits"],
    "api_key": "sk-hr-xxx",
    "timeout_s": 10
  },
  {
    "id": "finance",
    "name": "Finance Documents",
    "proxy_url": "http://rag-fin.internal:8000/v1",
    "weight": 0.8,
    "access_groups": ["finance", "admin"],
    "collections": ["finance_reports"],
    "api_key": "sk-fin-xxx",
    "timeout_s": 15,
    "is_primary": false
  }
]
```

**Географически распределённый с региональными весами:**
```json
[
  {
    "id": "us-east",
    "name": "US East Region",
    "proxy_url": "http://rag-use1.internal:8000/v1",
    "weight": 1.0,
    "timeout_s": 10,
    "is_primary": true
  },
  {
    "id": "us-west",
    "name": "US West Region",
    "proxy_url": "http://rag-usw2.internal:8000/v1",
    "weight": 1.0,
    "timeout_s": 12
  },
  {
    "id": "eu-west",
    "name": "EU West Region",
    "proxy_url": "http://rag-euw1.internal:8000/v1",
    "weight": 0.7,
    "timeout_s": 20
  }
]
```

---

## 6. Режимы федерации

Три режима определяют, какие силосы получают запросы. Режим задаётся через `FEDERATION_MODE` и может быть переопределён для каждого запроса через поле `federation_mode` в теле запроса.

### 6.1 `auto` — маршрутизация на основе ключевых слов (по умолчанию)

Федерация анализирует текст запроса и маршрутизирует его к наиболее релевантным силосам с помощью сопоставления ключевых слов.

**Как это работает:**
1. `classify_query()` в `auto_router.py` проверяет запрос по карте ключевых слов:
   - **hr**: `sick leave`, `vacation`, `hiring`, `onboarding`, `payroll`, `salary`, `benefits`, `hr policy` и русские эквиваленты (`больничный`, `отпуск`)
   - **engineering**: `deploy`, `production`, `kubernetes`, `docker`, `pipeline`, `code review`, `merge request`, `pull request`, `git`, `jira`, `confluence`, `architecture`, `microservice`, `api`
   - **finance**: `budget`, `expense`, `invoice`, `reimbursement`, `report`, `quarterly`, `annual`, `fiscal`, `tax`
2. Силосы сортируются по количеству совпадений (больше совпадений — выше).
3. Если ключевые слова не совпали, запрос распределяется по **всем** доступным силосам.

**Когда использовать:**
- Запросы относятся к конкретной предметной области и ключевых слов достаточно для маршрутизации
- Вы хотите минимизировать нагрузку на силосы, не отправляя запросы в нерелевантные силосы
- У вас небольшое количество чётко разделённых предметных областей

**Когда НЕ использовать:**
- Запросы охватывают несколько областей (например, «Сравните процессы онбординга в инженерии и HR»)
- Ваши силосы имеют перекрывающийся контент, не улавливаемый картой ключевых слов

**Отключение маршрутизации по ключевым словам:**
Установите `FEDERATION_AUTO_SLM_ENABLED=false`, чтобы режим `auto` безусловно распределял запросы по всем силосам.

### 6.2 `strict` — явное указание силоса

Запрашивает только тот силос (или те силосы), который указан клиентом в поле запроса `federation_silo`.

**Как это работает:**
1. Клиент отправляет `"federation_silo": "hr"` в теле запроса.
2. Запрашивается только силос `hr`.
3. Остальные силосы полностью игнорируются.
4. Контроль доступа по-прежнему применяется — пользователь должен иметь доступ к запрашиваемому силосу.

**Пример запроса:**
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-federated",
    "federation_silo": "hr",
    "federation_mode": "strict",
    "messages": [
      {"role": "user", "content": "What is our remote work policy?"}
    ]
  }'
```

**Когда использовать:**
- Клиент (UI или вышестоящий сервис) уже знает, какой силос запрашивать
- У вас есть селектор силосов в чат-интерфейсе
- Отладка — изоляция поведения конкретного силоса

### 6.3 `merge` — распределение по всем доступным силосам

Запрашивает **каждый** силос, к которому у пользователя есть доступ, независимо от содержания запроса.

**Как это работает:**
1. `list_accessible(user_groups)` возвращает все силосы, к которым у пользователя есть доступ.
2. Запрос отправляется параллельно во все доступные силосы.
3. Результаты от всех силосов объединяются.

**Когда использовать:**
- Междоменные запросы (например, «Какие корпоративные политики применяются к стажёрам в инженерии?»)
- Вы хотите максимальный полноту выдачи ценой более высокой задержки и нагрузки на силосы
- У вас небольшое количество силосов (2–5), где накладные расходы на fan-out приемлемы

### Сравнение режимов

| Аспект | `auto` | `strict` | `merge` |
|--------|--------|----------|---------|
| Выбор силоса | На основе ключевых слов, запасной вариант — все | Указан клиентом: `federation_silo` | Все доступные силосы |
| Задержка | Низкая (запрашивается мало силосов) | Самая низкая (1 силос) | Самая высокая (все силосы) |
| Полнота | Ориентированная на домен | В пределах силоса | Максимальная межсилосная |
| Переопределение на запрос | `federation_mode: "auto"` | `federation_mode: "strict"` | `federation_mode: "merge"` |
| Подходит для | Разделённые по доменам знания | Изолированные запросы к силосу | Междоменный поиск |

---

## 7. Стратегии объединения

После fan-out федерация должна объединить результаты из нескольких силосов в единый ранжированный список. Доступны три стратегии.

### 7.1 `weighted_rrf` — взвешенное объединение по взаимному рангу (по умолчанию)

**Формула:**

Для каждого чанка на позиции ранга `r` (с нуля) от силоса с весом `w`:

```
RRF_Score(chunk) = w / (k + r + 1)
```

Где:
- `w` — настроенный коэффициент `weight` силоса (по умолчанию: 1.0)
- `k` — постоянная сглаживания RRF (`FEDERATION_RRF_K`, по умолчанию: 60)
- `r` — ранг чанка (с нуля) в результатах его силоса

После подсчёта очков чанки сортируются по убыванию RRF-оценки, дедуплицируются (по SHA-256 от text+source+title) и обрезаются до `merge_k`.

**Влияние `k`:**
- Высокое `k` (например, 120) → позиция ранга менее важна → более равномерное смешивание
- Низкое `k` (например, 20) → позиция ранга доминирует → чанки с верхних позиций из каждого силоса сильно предпочитаются

**Влияние `weight`:**
- `weight: 2.0` → чанки силоса всегда выше идентично расположенных чанков от силоса с `weight: 1.0`
- Полезно для приоритета основных/авторитетных источников

**Пример:**

```
Silo A (weight=1.0): [chunk_a1 (rank 0), chunk_a2 (rank 1)]
Silo B (weight=1.2): [chunk_b1 (rank 0), chunk_b2 (rank 1)]

RRF(chunk_a1) = 1.0 / (60 + 0 + 1) = 0.01639
RRF(chunk_a2) = 1.0 / (60 + 1 + 1) = 0.01613
RRF(chunk_b1) = 1.2 / (60 + 0 + 1) = 0.01967  ← top result
RRF(chunk_b2) = 1.2 / (60 + 1 + 1) = 0.01935

Final order: chunk_b1, chunk_b2, chunk_a1, chunk_a2
```

**Когда использовать:**
- Вы доверяете внутреннему ранжированию силосов (поисковая выдача с учётом оценок)
- У вас силосы с разными уровнями авторитета (используйте веса)
- Стратегия по умолчанию для большинства развёртываний

### 7.2 `round_robin` — чередование для справедливости

Берёт первый чанк из каждого силоса, затем второй, затем третий и т.д.

**Пример:**

```
Silo A: [a1, a2, a3]
Silo B: [b1, b2]

Round-robin: a1, b1, a2, b2, a3 → deduplicated, truncated to merge_k
```

**Когда использовать:**
- Вы хотите равное представительство от каждого силоса
- Внутренние ранжирования силосов ненадёжны или несопоставимы
- Вам нужна разнообразность между силосами, а не оптимизация по оценкам

**Ограничение:** Не использует `weight` — все силосы рассматриваются равными.

### 7.3 `top_per_instance` — пропорциональное распределение

Берёт топ `merge_k / n` чанков от каждого из `n` силосов, затем сортирует все выбранные чанки по оценке.

**Пример (merge_k=60, 3 силоса):**

```
Per silo: 20 chunks selected

Silo A top-20: [...]
Silo B top-20: [...]
Silo C top-20: [...]

All 60 chunks sorted by descending score → truncated to merge_k
```

**Когда использовать:**
- Вы хотите гарантированное представительство от каждого силоса
- Оценки каждого силоса сопоставимы между силосами
- Вам нужно «лучшее от каждого», а не чистое чередование

### Руководство по выбору стратегии

| Стратегия | Использует веса | Использует оценки | Лучше всего для |
|-----------|-----------------|-------------------|-----------------|
| `weighted_rrf` | Да | Да (косвенно, через ранг) | Большинство развёртываний; авторитетные источники |
| `round_robin` | Нет | Нет | Разнообразность; равное представительство |
| `top_per_instance` | Нет | Да (оценки силосов) | Гарантированное представительство каждого силоса |

**Переопределение на уровне запроса:**

```bash
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment checklist",
    "federation_merge_strategy": "round_robin",
    "federation_top_k": 30
  }'
```

Если указана неизвестная стратегия, объединитель возвращается к `weighted_rrf`.

---

## 8. Справочник по API

Все эндпоинты обслуживаются FastAPI-приложением федерации на порту 8001.

### 8.1 `POST /v1/chat/completions`

Совместимый с OpenAI чат-комплит с федерацией. Выполняет поиск + объединение + генерацию.

**Запрос:**
```json
{
  "model": "rag-federated",
  "messages": [
    {"role": "user", "content": "What is our sick leave policy?"}
  ],
  "federation_mode": "auto",
  "federation_silo": null,
  "federation_merge_strategy": "weighted_rrf",
  "federation_top_k": 60,
  "rag_skip_generation": false,
  "temperature": 0.3,
  "stream": false
}
```

**Поля запроса:**

| Поле | Тип | Обязательно | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `model` | string | Да | — | Должно быть `"rag-federated"`. |
| `messages` | array | Да | — | Сообщения чата. Содержимое последнего сообщения используется как запрос. |
| `federation_mode` | string | Нет | `FEDERATION_MODE` | Переопределение режима: `auto`, `strict` или `merge`. |
| `federation_silo` | string | Нет | `null` | Целевой ID силоса для режима `strict`. |
| `federation_merge_strategy` | string | Нет | `FEDERATION_MERGE_STRATEGY` | Переопределение стратегии объединения. |
| `federation_top_k` | int | Нет | `FEDERATION_MERGE_K` | Максимум чанков после объединения. |
| `rag_skip_generation` | boolean | Нет | `false` | При `true` возвращает только результаты поиска (без LLM-генерации). |

**Ответ (с генерацией):**
```json
{
  "id": "fed-1751234567",
  "object": "chat.completion",
  "model": "rag-federated",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Based on the federated search across HR and Engineering silos, the sick leave policy allows..."
      },
      "finish_reason": "stop"
    }
  ],
  "rag_sources": [
    {
      "chunk_id": "abc123",
      "source": "confluence",
      "title": "Sick Leave Policy 2026",
      "version": "v3.1",
      "silo_id": "hr",
      "silo_name": "HR Knowledge Base",
      "relevance": 0.01967,
      "text_preview": "Employees are entitled to 10 sick days per calendar year..."
    }
  ],
  "rag_confidence": 0.7,
  "federation": {
    "mode": "auto",
    "silos_queried": ["hr"],
    "silos_skipped": [],
    "cross_silo": false,
    "total_latency_ms": 234.5,
    "per_silo_latency_ms": {
      "hr": 215.3
    },
    "warnings": []
  }
}
```

**Ответ (skip_generation=true или нет чанков):**
```json
{
  "id": "fed-1751234567",
  "object": "chat.completion",
  "model": "rag-federated",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": ""
      },
      "finish_reason": "stop"
    }
  ],
  "rag_sources": [...],
  "rag_metadata": {
    "total_retrieved": 12,
    "merged_count": 8,
    "latency_ms": 234.5
  },
  "federation": {...}
}
```

**Ответ с ошибкой (все силосы недоступны):**
```json
{
  "error": "All silos unavailable: ['hr', 'eng']",
  "type": "AllSilosDownError"
}
```
HTTP-статус: 503

### 8.2 `POST /v1/search`

Эндпоинт только для поиска. Извлекает и объединяет чанки без LLM-генерации.

**Запрос:**
```json
{
  "query": "deployment pipeline",
  "federation_mode": "merge",
  "federation_silo": null,
  "federation_merge_strategy": "weighted_rrf",
  "federation_top_k": 30
}
```

**Ответ:**
```json
{
  "rag_sources": [
    {
      "chunk_id": "def456",
      "source": "gitlab",
      "title": "CI/CD Pipeline Setup",
      "version": "v2.0",
      "silo_id": "eng",
      "silo_name": "Engineering Wiki",
      "relevance": 0.02100,
      "text_preview": "The deployment pipeline consists of three stages..."
    }
  ],
  "rag_metadata": {
    "total_retrieved": 45,
    "merged_count": 25,
    "latency_ms": 312.8
  },
  "federation": {
    "mode": "merge",
    "silos_queried": ["eng", "hr"],
    "silos_skipped": [],
    "cross_silo": true,
    "total_latency_ms": 312.8,
    "per_silo_latency_ms": {
      "eng": 180.2,
      "hr": 295.5
    },
    "warnings": []
  }
}
```

### 8.3 `GET /v1/silos`

Возвращает список силосов, доступных аутентифицированному пользователю (или все силосы, если аутентификация отключена).

**Ответ:**
```json
{
  "silos": [
    {
      "id": "hr",
      "name": "HR Knowledge Base",
      "collections": ["knowledge_base"],
      "accessible": true
    },
    {
      "id": "eng",
      "name": "Engineering Wiki",
      "collections": ["eng_docs", "eng_wiki"],
      "accessible": true
    },
    {
      "id": "finance",
      "name": "Finance Documents",
      "collections": ["finance_reports"],
      "accessible": false
    }
  ]
}
```

### 8.4 `GET /v1/health`

Комплексная проверка здоровья со статусом силосов.

**Ответ:**
```json
{
  "status": "healthy",
  "federation": {
    "mode": "auto",
    "total_silos": 3,
    "silos": {
      "hr": {"name": "HR Knowledge Base", "status": "configured"},
      "eng": {"name": "Engineering Wiki", "status": "configured"},
      "finance": {"name": "Finance Documents", "status": "configured"}
    }
  }
}
```

### 8.5 `GET /v1/health/live`

Проверка жизнеспособности Kubernetes. Возвращает `{"status": "ok"}`, если процесс запущен.

### 8.6 `GET /v1/health/ready`

Проверка готовности Kubernetes. Возвращает URL и статусы силосов. Возвращает `not_ready`, если реестр силосов не инициализирован.

### 8.7 `GET /v1/models`

Совместимый с OpenAI список моделей.

**Ответ:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "rag-federated",
      "object": "model",
      "created": 1751234567,
      "owned_by": "federation"
    }
  ]
}
```

### 8.8 `GET /metrics`

Эндпоинт метрик Prometheus. Возвращает текстовые метрики в формате Prometheus exposition.

---

## 9. Контроль доступа

### Принцип работы

1. **Аутентификация включена** (`FEDERATION_AUTH_ENABLED=true`):
   - `extract_user_groups()` читает JWT из заголовка `Authorization: Bearer <token>`
   - Декодирует токен с помощью `FEDERATION_JWT_SECRET` и `FEDERATION_JWT_ALGORITHM`
   - Извлекает группы из `payload.groups` и `payload.realm_access.roles`
   - Оба списка объединяются в единый массив `user_groups`

2. **Аутентификация отключена** (по умолчанию):
   - Все пользователи получают группы из `FEDERATION_DEFAULT_GROUPS` (по умолчанию: `"admin"`)

3. **Проверка доступа к силосу:**
   - `SiloConfig.is_accessible_by(user_groups)` проверяет, что пересечение `user_groups` и `silo.access_groups` непустое
   - Если `silo.access_groups` пуст, все пользователи имеют доступ к силосу

4. **Фильтрация:**
   - `registry.list_accessible(user_groups)` возвращает только силосы, к которым у пользователя есть доступ
   - Недоступные силосы исключаются из всех запросов

### Структура JWT-токена

Федерация ожидает JWT со следующими клеймами:

```json
{
  "sub": "user123",
  "groups": ["admin", "engineering"],
  "realm_access": {
    "roles": ["viewer"]
  },
  "exp": 1751320000
}
```

Поддерживаются оба формата: `groups` (прямой массив) и `realm_access.roles` (стиль Keycloak).

### Запасной вариант: неподписанные токены

Если `FEDERATION_JWT_SECRET` пуст, но токен предоставлен:
- Токен декодируется **без проверки подписи**
- Группы извлекаются из полезной нагрузки
- Логируется предупреждение: `"No JWT secret configured — returning empty groups"`
- Это полезно только для разработки — **никогда не используйте в продакшене**

### Пример контроля доступа

```bash
# Silo config:
# hr silo: access_groups=["hr", "admin"]
# eng silo: access_groups=["engineering", "admin"]
# finance silo: access_groups=["finance", "admin"]

# User with groups ["hr"]:
# → Can access: hr
# → Cannot access: eng, finance

# User with groups ["admin"]:
# → Can access: hr, eng, finance (all)

# User with groups ["intern"]:
# → Can access: none (unless a silo has empty access_groups)
```

---

## 10. Делегирование генерации

После объединения чанков федерация должна сгенерировать финальный ответ. Для этого используется **трёхуровневая стратегия с запасными вариантами**:

### Уровень 1: Прямой LLM (FEDERATION_LLM_ENDPOINT)

Если задан `FEDERATION_LLM_ENDPOINT`, федерация генерирует ответ напрямую:

```
Federation ──→ Direct LLM (FEDERATION_LLM_ENDPOINT)
                POST /chat/completions
                {
                  "model": "${FEDERATION_LLM_MODEL}",
                  "messages": [
                    {"role": "system", "content": "You are a federated RAG assistant..."},
                    {"role": "user", "content": "Context:\n{merged_chunks}\n\nQuestion: {query}"}
                  ],
                  "temperature": 0.3
                }
```

**Используйте, когда:**
- У вас есть выделенный LLM для федерации (избегаете загрузки LLM силосов)
- Вы хотите единый стиль генерации во всех силосах
- У вас нет основного силоса, который должен «владеть» генерацией ответов

### Уровень 2: Делегирование основному силосу

Если `FEDERATION_LLM_ENDPOINT` не задан, федерация находит **основной силос** (с `is_primary: true`) и делегирует генерацию ему:

```
Federation ──→ Primary Silo (/v1/chat/completions)
               {
                 "model": "rag-internal",
                 "messages": [
                   {"role": "system", "content": "You are a federated RAG assistant..."},
                   {"role": "user", "content": "Context from federated search:\n{merged_chunks}\n\nQuestion: {query}"}
                 ],
                 "temperature": 0.3
               }
```

Основной силос получает **все объединённые чанки** (не только свои) и генерирует исчерпывающий ответ. Для аутентификации используется `api_key` основного силоса.

**Используйте, когда:**
- У вашего основного силоса самый мощный LLM
- Вы хотите, чтобы ответы были согласованы со стилем генерации основного силоса
- У вас нет отдельного эндпоинта LLM для федерации

### Уровень 3: Запасной контент

Если и прямой LLM, и делегирование основному силосу не удались (или ни один не настроен), федерация возвращает статическое запасное сообщение:

```
"Retrieved {N} chunks from {M} silos. Generation service is currently unavailable.
 Review the rag_sources below for relevant information."
```

`rag_confidence` устанавливается в `0.3` для запасных ответов.

### Сводка потока генерации

```
                ┌──────────────────────┐
                │  Merged chunks ready  │
                └──────────┬───────────┘
                           │
                    ┌──────▼──────┐
                    │ LLM_ENDPOINT │
                    │    set?      │
                    └──┬───────┬───┘
                  Yes  │       │  No
           ┌───────────▼┐  ┌───▼───────────────┐
           │ Generate    │  │ Primary silo      │
           │ directly    │  │ configured?       │
           └──────┬──────┘  └───┬───────────┬───┘
                  │          Yes│           │No
                  │     ┌───────▼──┐   ┌────▼───────────┐
                  │     │ Delegate  │   │ Fallback static │
                  │     │ to primary│   │ message         │
                  │     └──────┬────┘   └────┬────────────┘
                  │            │             │
                  └────────────┼─────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Return to client    │
                    │ with rag_confidence │
                    └─────────────────────┘
```

---

## 11. Автоматические выключатели

Каждый силос имеет независимый автоматический выключатель для предотвращения каскадных отказов при неработоспособности силоса.

### Конечный автомат

```
      ┌─────────┐
      │ CLOSED  │  ← Normal operation. All requests pass through.
      └────┬────┘
           │ failure_count >= threshold (5 consecutive failures)
           ▼
      ┌─────────┐
      │  OPEN   │  ← All requests are rejected. Silo is skipped.
      └────┬────┘
           │ recovery_timeout_s elapsed (30s)
           ▼
      ┌──────────┐
      │ HALF_OPEN│  ← Next request is a probe.
      └──┬────┬──┘
   success│    │failure
     ┌────▼┐ ┌─▼────┐
     │CLOSED│ │ OPEN │
     └─────┘ └──────┘
```

### Как это работает на практике

```
Request arrives
      │
      ▼
For each silo:
  breaker = get_breaker("federation_{silo.id}")
  if breaker.allow_request():
      → Query silo
      → On success: breaker.record_success()
      → On failure: breaker.record_failure()
  else:
      → Skip silo (circuit open)
      → Log: "Silo 'eng' skipped (circuit breaker open)"
```

### Конфигурация

| Параметр | Переменная окружения | По умолчанию | Эффект |
|----------|----------------------|--------------|--------|
| Порог сбоев | `FEDERATION_CIRCUIT_BREAKER_THRESHOLD` | 5 | Количество последовательных сбоев перед открытием |
| Тайм-аут восстановления | `FEDERATION_CIRCUIT_BREAKER_RECOVERY_S` | 30 | Секунды в состоянии OPEN перед переходом в HALF_OPEN |

### Переходы состояний

- **CLOSED → OPEN:** `failure_count` достигает порога (5 последовательных сбоев)
- **OPEN → HALF_OPEN:** Истекает тайм-аут восстановления (30 секунд с момента открытия)
- **HALF_OPEN → CLOSED:** Первый запрос в HALF_OPEN успешен
- **HALF_OPEN → OPEN:** Первый запрос в HALF_OPEN завершается сбоем
- **CLOSED → CLOSED:** `success_count` достигает порога (5 последовательных успехов) → сбрасывает `failure_count` в 0

### Мониторинг автоматических выключателей

Датчик `rag_federation_circuit_breaker_state` сообщает состояние для каждого силоса. Проверьте эндпоинт Prometheus `/metrics`:

```
rag_federation_circuit_breaker_state{silo="hr"} 0.0   # 0 = CLOSED
rag_federation_circuit_breaker_state{silo="eng"} 1.0  # 1 = OPEN
rag_federation_circuit_breaker_state{silo="fin"} 0.5  # 2 = HALF_OPEN
```

Оповещения должны срабатывать, когда любой силос находится в состоянии OPEN более 2 минут.

---

## 12. Мониторинг

### Метрики Prometheus

Все метрики экспортируются на `GET /metrics` федеративного прокси (порт 8001).

| Метрика | Тип | Метки | Описание |
|---------|-----|-------|----------|
| `rag_federation_requests_total` | Counter | `mode`, `status` | Общее количество запросов федерации. `status`: `started`, `success`, `error`. |
| `rag_federation_silo_requests_total` | Counter | `silo`, `status` | Количество запросов к каждому силосу. Отслеживается `silo_client.py`. |
| `rag_federation_silo_latency_seconds` | Histogram | `silo` | Задержка ответа каждого силоса. Корзины: 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0s. |
| `rag_federation_total_latency_seconds` | Histogram | `mode` | Сквозная задержка федерации (fan-out + объединение + генерация). Корзины: 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0s. |
| `rag_federation_merge_total_chunks` | Histogram | — | Распределение количества чанков после объединения. Корзины: 5, 10, 20, 30, 40, 50, 60, 80, 100. |
| `rag_federation_circuit_breaker_state` | Gauge | `silo` | Состояние автоматического выключателя: 0=CLOSED, 1=OPEN, 2=HALF_OPEN. |
| `rag_federation_silos_active` | Gauge | — | Общее количество настроенных силосов при запуске. |

### Ключевые запросы мониторинга (PromQL)

```promql
# Error rate by mode
rate(rag_federation_requests_total{status="error"}[5m]) /
rate(rag_federation_requests_total[5m])

# P99 total latency by mode
histogram_quantile(0.99,
  rate(rag_federation_total_latency_seconds_bucket[5m]))

# P95 per-silo latency
histogram_quantile(0.95,
  rate(rag_federation_silo_latency_seconds_bucket[5m]))

# Circuit breakers open
rag_federation_circuit_breaker_state == 1

# Average chunks per merge
rate(rag_federation_merge_total_chunks_sum[5m]) /
rate(rag_federation_merge_total_chunks_count[5m])

# Success rate (%)
100 * rate(rag_federation_requests_total{status="success"}[5m]) /
rate(rag_federation_requests_total[5m])
```

### Логирование

Федерация использует стандартный модуль Python `logging` с именем логгера `"federation"`. Ключевые события логирования:

| Событие | Уровень | Шаблон сообщения |
|---------|---------|-------------------|
| Запуск | INFO | `Federation started: {N} silos, mode={mode}` |
| Выключатель открывается | WARNING | `Breaker 'federation_{silo}' → OPEN ({count} failures)` |
| Выключатель закрывается | INFO | `Breaker 'federation_{silo}' → CLOSED (half-open success)` |
| Сбой запроса к силосу | WARNING | `Silo '{id}' query failed: {error}` |
| Сбой генерации | WARNING | `Direct LLM generation failed: {error}` / `Generation via primary silo '{id}' failed: {error}` |
| Ограничение частоты | WARNING | *(от middleware, если включено)* |
| Остановка | INFO | `Federation shutting down` |

---

## 13. Развёртывание

### 13.1 Docker Compose

Рекомендуемая конфигурация запускает федеративный прокси вместе с вашими RAG-силосами:

```yaml
# docker-compose.federation.yml
version: "3.8"
services:
  federation:
    build:
      context: ..
      dockerfile: federation/Dockerfile
    ports:
      - "8001:8001"
    environment:
      - FEDERATION_MODE=merge
      - FEDERATION_INSTANCES_JSON='[
          {"id":"hr","name":"HR KB","proxy_url":"http://proxy:8000/v1","weight":1.0,"access_groups":["admin"],"is_primary":true},
          {"id":"eng","name":"Engineering","proxy_url":"http://rag-eng:8000/v1","weight":1.2,"access_groups":["admin","engineering"]}
        ]'
      - FEDERATION_MERGE_STRATEGY=weighted_rrf
      - FEDERATION_MERGE_K=60
      - FEDERATION_RRF_K=60
      - FEDERATION_PER_INSTANCE_TIMEOUT_S=10
      - FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5
      - FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30
      - FEDERATION_LLM_ENDPOINT=http://llm-host:8000/v1
      - FEDERATION_LLM_MODEL=llama-3-70b
    depends_on:
      - proxy
    networks:
      - rag-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/v1/health/live"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
```

### 13.2 Kubernetes с Helm

**ConfigMap для конфигурации силосов:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: federation-silos
  namespace: rag-system
data:
  silos.json: |
    [
      {
        "id": "eng",
        "name": "Engineering Wiki",
        "proxy_url": "http://rag-eng.rag-system.svc.cluster.local:8000/v1",
        "weight": 1.2,
        "access_groups": ["engineering", "admin"],
        "collections": ["eng_docs"],
        "api_key": "${ENG_API_KEY}",
        "timeout_s": 8,
        "is_primary": true
      },
      {
        "id": "hr",
        "name": "HR Knowledge Base",
        "proxy_url": "http://rag-hr.rag-system.svc.cluster.local:8000/v1",
        "weight": 1.0,
        "access_groups": ["hr", "admin"],
        "collections": ["hr_policies"],
        "api_key": "${HR_API_KEY}",
        "timeout_s": 10
      },
      {
        "id": "finance",
        "name": "Finance Documents",
        "proxy_url": "http://rag-fin.rag-system.svc.cluster.local:8000/v1",
        "weight": 0.8,
        "access_groups": ["finance", "admin"],
        "collections": ["finance_reports"],
        "api_key": "${FIN_API_KEY}",
        "timeout_s": 15
      }
    ]
```

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-federation
  namespace: rag-system
  labels:
    app: rag-federation
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rag-federation
  template:
    metadata:
      labels:
        app: rag-federation
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8001"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: federation
        image: rag-system/federation:v2.0.0
        ports:
        - containerPort: 8001
          name: http
        env:
        - name: FEDERATION_MODE
          value: "auto"
        - name: FEDERATION_INSTANCES_FILE
          value: "/etc/federation/silos.json"
        - name: FEDERATION_MERGE_STRATEGY
          value: "weighted_rrf"
        - name: FEDERATION_MERGE_K
          value: "60"
        - name: FEDERATION_RRF_K
          value: "60"
        - name: FEDERATION_PER_INSTANCE_TIMEOUT_S
          value: "10"
        - name: FEDERATION_CIRCUIT_BREAKER_THRESHOLD
          value: "5"
        - name: FEDERATION_CIRCUIT_BREAKER_RECOVERY_S
          value: "30"
        - name: FEDERATION_LLM_ENDPOINT
          value: "http://llm-service.rag-system.svc.cluster.local:8000/v1"
        - name: FEDERATION_LLM_MODEL
          value: "llama-3-70b"
        - name: FEDERATION_AUTH_ENABLED
          value: "true"
        - name: FEDERATION_JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: federation-secrets
              key: jwt-secret
        volumeMounts:
        - name: silo-config
          mountPath: /etc/federation
          readOnly: true
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /v1/health/live
            port: 8001
          initialDelaySeconds: 10
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /v1/health/ready
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: silo-config
        configMap:
          name: federation-silos
```

**Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rag-federation
  namespace: rag-system
spec:
  selector:
    app: rag-federation
  ports:
  - port: 8001
    targetPort: 8001
    name: http
```

**Secrets:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: federation-secrets
  namespace: rag-system
type: Opaque
stringData:
  jwt-secret: "your-256-bit-secret-here-change-in-production"
```

### 13.3 Фрагмент Helm values

```yaml
# values.yaml — federation section
federation:
  enabled: true
  replicas: 2
  image:
    repository: rag-system/federation
    tag: v2.0.0
  env:
    FEDERATION_MODE: auto
    FEDERATION_MERGE_STRATEGY: weighted_rrf
    FEDERATION_MERGE_K: "60"
    FEDERATION_RRF_K: "60"
    FEDERATION_PER_INSTANCE_TIMEOUT_S: "10"
    FEDERATION_CIRCUIT_BREAKER_THRESHOLD: "5"
    FEDERATION_CIRCUIT_BREAKER_RECOVERY_S: "30"
    FEDERATION_LLM_ENDPOINT: http://llm-service:8000/v1
    FEDERATION_LLM_MODEL: llama-3-70b
    FEDERATION_AUTH_ENABLED: "true"
  silos:
    - id: eng
      name: Engineering Wiki
      proxy_url: http://rag-eng:8000/v1
      weight: 1.2
      access_groups:
        - engineering
        - admin
      collections:
        - eng_docs
      api_key_secret: eng-api-key
      timeout_s: 8
      is_primary: true
    - id: hr
      name: HR Knowledge Base
      proxy_url: http://rag-hr:8000/v1
      weight: 1.0
      access_groups:
        - hr
        - admin
      collections:
        - hr_policies
      api_key_secret: hr-api-key
      timeout_s: 10
```

---

## 14. Устранение неполадок

### 14.1 Все силосы возвращают "No accessible silos for user"

**Симптом:** Ответ содержит `"errors": ["No accessible silos for user"]` с нулём чанков.

**Причины:**
- Аутентификация включена (`FEDERATION_AUTH_ENABLED=true`), но не предоставлен валидный JWT-токен
- Группы пользователя в JWT не совпадают ни с одним `access_groups` силоса
- `FEDERATION_DEFAULT_GROUPS` установлена на группу, у которой нет доступа

**Решение:**
1. Проверьте группы JWT-токена: декодируйте его на [jwt.io](https://jwt.io) и убедитесь в клеймах `groups` или `realm_access.roles`
2. Убедитесь, что `access_groups` силосов совпадают с группами пользователя
3. При тестировании без аутентификации установите `FEDERATION_AUTH_ENABLED=false` и `FEDERATION_DEFAULT_GROUPS=admin`
4. Проверьте, что хотя бы один силос имеет `"access_groups": ["admin"]` или пустой `"access_groups": []`

### 14.2 Конкретный силос постоянно пропускается

**Симптом:** Один силос стабильно появляется в `silos_skipped` в метаданных федерации.

**Причины:**
- Автоматический выключатель в состоянии OPEN для этого силоса (5+ последовательных сбоев)
- `access_groups` силоса не включают группы пользователя
- В режиме `auto` запрос не соответствует ключевым словам для этого силоса

**Решение:**
1. Проверьте состояние автоматического выключателя: ищите сообщения `WARNING` с `Breaker 'federation_{silo}' → OPEN`
2. Подождите тайм-аут восстановления (по умолчанию 30 секунд) или перезапустите сервис федерации для сброса выключателей
3. Убедитесь, что силос действительно доступен: `curl http://silo-host:8000/v1/health`
4. Проверьте группы доступа: `curl http://localhost:8001/v1/silos` — какие силосы доступны

### 14.3 Высокая задержка федерации

**Симптом:** Суммарная задержка значительно превышает задержки отдельных силосов.

**Причины:**
- Один медленный силос блокирует fan-out (суммарная задержка ≈ max из индивидуальных задержек)
- Этап генерации медленный (LLM-инференс)
- Высокая сетевая задержка до силосов

**Решение:**
1. Проверьте `per_silo_latency_ms` в метаданных федерации для выявления медленного силоса
2. Уменьшите `FEDERATION_PER_INSTANCE_TIMEOUT_S` для быстрого отказа на медленных силосах
3. Снизьте `FEDERATION_MERGE_K` для уменьшения размера контекста для генерации
4. Рассмотрите использование режима `auto` вместо `merge` для запроса меньшего числа силосов
5. Разверните силосы ближе к слою федерации (один кластер/регион)

### 14.4 Дублирующиеся чанки в результатах

**Симптом:** Один и тот же контент появляется несколько раз в `rag_sources`.

**Причины:**
- Два силоса содержат один и тот же документ (например, и инженерный, и HR силосы имеют корпоративный справочник)
- Дедупликация SHA-256 не поймала дубликаты из-за незначительных различий в тексте (форматирование, метаданные)

**Решение:**
- Встроенная `deduplicate_chunks()` использует SHA-256 от `text + source_type + title`. Если дубликаты сохраняются, чанки различаются в одном из этих полей
- Проверьте конфигурации силосов, чтобы убедиться, что документы не индексируются в нескольких силосах непреднамеренно
- Проверьте ETL-пайплайн для каждого силоса на предмет перекрытия источников данных

### 14.5 Генерация возвращает запасное сообщение

**Симптом:** Ответ содержит "Retrieved N chunks from M silos. Generation service is currently unavailable."

**Причины:**
- `FEDERATION_LLM_ENDPOINT` не задан И ни один силос не имеет `is_primary: true`
- Прямой эндпоинт LLM недоступен
- LLM основного силоса не работает или силос вернул ошибку при генерации
- В запросе было установлено `rag_skip_generation: true`

**Решение:**
1. Проверьте логи на наличие: `"Direct LLM generation failed"` или `"Generation via primary silo 'X' failed"`
2. Убедитесь, что `FEDERATION_LLM_ENDPOINT` доступен: `curl $FEDERATION_LLM_ENDPOINT/models`
3. Убедитесь, что ровно один силос имеет `"is_primary": true`
4. Проверьте здоровье основного силоса: `curl http://primary-silo:8000/v1/health`
5. При использовании делегирования убедитесь, что `api_key` в конфигурации основного силоса верный

### 14.6 ConfigError при запуске

**Симптом:** Федерация не запускается с `ConfigError`.

**Типичные ошибки конфигурации:**
```
ConfigError: Invalid FEDERATION_INSTANCES_JSON: ...    # Malformed JSON
ConfigError: FEDERATION_INSTANCES_JSON must be a JSON array  # Object instead of array
ConfigError: Missing required field 'id' in silo config       # Missing required field
ConfigError: Missing required field 'name' in silo config     # Missing required field
ConfigError: Missing required field 'proxy_url' in silo config # Missing required field
ConfigError: Duplicate silo id: hr                            # Non-unique ID
ConfigError: Silo 'hr' weight must be > 0, got 0              # Invalid weight
ConfigError: Silo 'hr' proxy_url is empty                     # Empty URL
```

**Решение:**
1. Проверьте JSON на [jsonlint.com](https://jsonlint.com)
2. Убедитесь, что каждый силос имеет поля `id`, `name` и `proxy_url`
3. Убедитесь, что все ID силосов уникальны
4. Убедитесь, что все веса — положительные числа с плавающей точкой
5. При использовании `FEDERATION_INSTANCES_FILE` проверьте, что файл существует и доступен для чтения

### 14.7 Режим auto маршрутизирует не в тот силос

**Симптом:** Запрос на HR-тематику маршрутизируется в инженерный силос (или наоборот).

**Причины:**
- Ключевые слова не совпали, и режим auto вернулся к распределению по всем силосам
- Карта ключевых слов не покрывает термины запроса пользователя

**Решение:**
1. Текущая карта ключевых слов захардкожена в `auto_router.py`. Для кастомизации:
   - Отредактируйте словарь `_KEYWORD_MAP` в `federation/app/auto_router.py`
   - Добавьте ключевые слова вашей предметной области к соответствующей записи силоса
   - Пересоберите Docker-образ
2. Используйте режим `strict` с `federation_silo` для явной маршрутизации
3. Установите `FEDERATION_AUTO_SLM_ENABLED=false` для отключения маршрутизации по ключевым словам и постоянного распределения по всем силосам

### 14.8 Эндпоинты проверки здоровья

Используйте их для отладки:

```bash
# Is the federation process alive?
curl http://localhost:8001/v1/health/live
# → {"status": "ok"}

# Is the federation ready to serve requests?
curl http://localhost:8001/v1/health/ready
# → {"status": "ready", "silos": {"hr": {"name": "HR KB", "url": "http://..."}}}

# Full health with silo status
curl http://localhost:8001/v1/health
# → {"status": "healthy", "federation": {"mode": "auto", "total_silos": 3, ...}}

# Which silos can the current user access?
curl http://localhost:8001/v1/silos
# → {"silos": [{"id": "hr", "accessible": true}, ...]}

# Prometheus metrics
curl http://localhost:8001/metrics | grep federation
```

---

## Приложение A: Карта быстрого доступа

```bash
# ─── Start federation ───
cd federation && docker compose -f docker-compose.federation.yml up -d

# ─── Query federation ───
# Chat completion
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}]}'

# Search only
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"YOUR QUERY","federation_top_k":20}'

# Strict mode (single silo)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}],"federation_mode":"strict","federation_silo":"hr"}'

# Skip generation (chunks only)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}],"rag_skip_generation":true}'

# ─── Health ───
curl http://localhost:8001/v1/health
curl http://localhost:8001/v1/health/live
curl http://localhost:8001/v1/health/ready

# ─── Silos ───
curl http://localhost:8001/v1/silos
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8001/v1/silos

# ─── Metrics ───
curl http://localhost:8001/metrics | grep federation

# ─── Logs ───
docker compose -f docker-compose.federation.yml logs -f federation
```

## Приложение B: Краткий справочник по переменным окружения

```bash
# federation/.env — all available settings

# ─── Required ───
FEDERATION_MODE=auto                                   # auto | strict | merge
FEDERATION_INSTANCES_JSON='[{"id":"hr","name":"HR KB","proxy_url":"http://localhost:8000/v1"}]'

# ─── Optional: File-based config ───
# FEDERATION_INSTANCES_FILE=/etc/federation/silos.json  # Overrides FEDERATION_INSTANCES_JSON

# ─── Merge ───
FEDERATION_MERGE_STRATEGY=weighted_rrf                  # weighted_rrf | round_robin | top_per_instance
FEDERATION_MERGE_K=60                                   # Max chunks after merge
FEDERATION_RRF_K=60                                     # RRF smoothing constant

# ─── Timeouts ───
FEDERATION_TOTAL_TIMEOUT_S=30                           # Budgeted total timeout
FEDERATION_PER_INSTANCE_TIMEOUT_S=10                    # Per-silo request timeout

# ─── Circuit Breakers ───
FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5                  # Failures before opening
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30                # Recovery wait time

# ─── Generation ───
FEDERATION_LLM_ENDPOINT=http://llm-host:8000/v1         # Direct LLM endpoint
FEDERATION_LLM_MODEL=llama-3                            # Model name for direct LLM

# ─── Auto Routing ───
FEDERATION_AUTO_SLM_ENABLED=true                        # Enable keyword-based routing

# ─── Auth ───
FEDERATION_AUTH_ENABLED=false                           # Enable JWT auth
FEDERATION_JWT_SECRET=                                  # JWT signing secret
FEDERATION_JWT_ALGORITHM=HS256                          # JWT algorithm
FEDERATION_DEFAULT_GROUPS=admin                         # Default groups when auth is off
```
