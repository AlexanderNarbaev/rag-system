# Блок A. OpenAI-совместимый API (FR-01 — FR-08)

---

## FR-01. Chat Completions — streaming и non-streaming

**Описание:**
Прокси предоставляет эндпоинт `/v1/chat/completions`, совместимый с OpenAI API.
Клиент отправляет POST-запрос с массивом `messages` (роль + контент), параметрами
`temperature`, `max_tokens`, `stream`. Прокси выполняет RAG-пайплайн (поиск →
ранжирование → сборка контекста → генерация LLM) и возвращает ответ в формате
OpenAI Chat Completion.

При `stream=true` ответ идёт по SSE (Server-Sent Events) с `data: {...}` строками
и финальным `data: [DONE]`. При `stream=false` возвращается полный JSON.

**Критерий приёмки:**
1. `curl -X POST /v1/chat/completions -d '{"messages":[{"role":"user","content":"test"}],"stream":false}'` возвращает 200 с JSON `{choices: [{message: {content: "..."}}]}`
2. Тот же запрос с `"stream":true` возвращает SSE-поток, завершающийся `data: [DONE]`
3. OpenAI Python SDK `OpenAI(base_url="http://localhost:8080/v1").chat.completions.create(...)` работает без ошибок

**Статус:** ⚠️ Код есть (`proxy/app/api/chat.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** ADR-004, `proxy/app/api/chat.py`

---

## FR-02. Models endpoint

**Описание:**
Эндпоинт `GET /v1/models` возвращает список доступных моделей в формате OpenAI.
Каждая модель имеет `id` (имя модели из конфигурации), `object="model"`, `created`
(unix timestamp), `owned_by="local"`.

**Критерий приёмки:**
1. `curl /v1/models` возвращает `{object: "list", data: [{id: "...", object: "model", ...}]}`
2. В списке присутствует модель из `LLM_MODEL_NAME`

**Статус:** ✅ Подтверждено (`proxy/app/main.py:846`)
**Приоритет:** CRITICAL
**Связь:** ADR-004

---

## FR-03. Health check — полный статус

**Описание:**
Эндпоинт `GET /v1/health` проверяет доступность всех зависимостей: Qdrant, LLM,
Neo4j (опционально), Redis (опционально), embedder, reranker. Возвращает JSON с
статусом каждого компонента (`healthy`/`degraded`/`down`) и общий HTTP-код: 200
если все критичные компоненты здоровы, 503 если хотя бы один критичный недоступен.

**Критерий приёмки:**
1. При всех запущенных сервисах — HTTP 200, все компоненты `healthy`
2. При остановленном Qdrant — HTTP 503, Qdrant `down`, остальные `healthy`
3. При остановленном Neo4j (GRAPH_ENABLED=true) — HTTP 200 (Neo4j не критичен), Neo4j `down`

**Статус:** ⚠️ Код есть (`proxy/app/api/health.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** ADR-004, best-practices-checklist 4.3

---

## FR-04. Kubernetes probes — liveness и readiness

**Описание:**
- `GET /v1/health/live` — liveness probe. Возвращает 200 если процесс жив (не завис).
  Не проверяет внешние зависимости.
- `GET /v1/health/ready` — readiness probe. Возвращает 200 только если все критичные
  зависимости доступны (Qdrant, LLM). Если нет — 503.

**Критерий приёмки:**
1. `/v1/health/live` всегда возвращает 200 пока процесс работает
2. `/v1/health/ready` возвращает 503 при недоступном Qdrant

**Статус:** ⚠️ Код есть (`proxy/app/api/health.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** roadmap Phase 3, best-practices-checklist 4.7

---

## FR-05. RAG-специфичные параметры запроса

**Описание:**
К стандартному OpenAI-запросу добавляются дополнительные параметры:
- `rag_version` (string) — запрашивает конкретную версию документов
- `rag_force_refresh` (bool) — обходит кэш ответов
- `rag_skip_generation` (bool) — режим «только поиск» (возвращает найденные чанки)
- `rag_return_chunks` (bool) — возвращает найденные чанки в ответе
- `rag_top_k` (int) — переопределяет количество чанков после ранжирования

Все параметры опциональны. Стандартные OpenAI-клиенты их игнорируют.

**Критерий приёмки:**
1. `rag_version="v1"` — в ответе только чанки версии v1
2. `rag_force_refresh=true` — ответ генерируется заново (не из кэша)
3. `rag_skip_generation=true` — возвращаются только найденные чанки без генерации
4. `rag_return_chunks=true` — в ответе есть поле `rag_sources` с чанками
5. `rag_top_k=5` — после ранжирования не более 5 чанков

**Статус:** ⚠️ Код есть (`proxy/app/api/chat.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** ADR-004

---

## FR-06. RAG-специфичные поля ответа

**Описание:**
Каждый ответ `/v1/chat/completions` содержит дополнительные поля:
- `rag_feedback_id` (string) — уникальный ID для отправки обратной связи
- `rag_confidence` (float 0-1) — уверенность системы в ответе
- `rag_sources` (array) — список источников с `chunk_id`, `source`, `title`, `version`, `relevance`

**Критерий приёмки:**
1. Ответ содержит `rag_feedback_id` (непустая строка)
2. Ответ содержит `rag_confidence` (float от 0 до 1)
3. Ответ содержит `rag_sources` (массив, может быть пустым если нет результатов поиска)

**Статус:** ⚠️ Код есть (`proxy/app/api/chat.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** ADR-004

---

## FR-07. Response caching (Redis)

**Описание:**
Нестриминговые ответы кэшируются в Redis с TTL 1 час. Повторный запрос с тем же
содержанием возвращает кэшированный ответ без вызова LLM. Параметр
`rag_force_refresh=true` обходит кэш. Ключ кэша формируется как
`rag:{user_id}:{query}:{version}`.

**Критерий приёмки:**
1. Два одинаковых запроса — второй отдаётся из кэша (лог: "Cache hit")
2. Запрос с `rag_force_refresh=true` — генерируется заново
3. TTL истекает через 1 час — следующий запрос генерируется заново

**Статус:** ✅ Подтверждено (`proxy/app/shared/cache.py`)
**Приоритет:** CRITICAL
**Связь:** ADR-004, performance-quality 1.4

---

## FR-08. SSE streaming format

**Описание:**
При `stream=true` ответ идёт по Server-Sent Events. Каждый чат — строка
`data: {"choices":[{"delta":{"content":"token"}}]}\n\n`. Поток завершается
`data: [DONE]\n\n`. Content-Type: `text/event-stream`.

**Критерий приёмки:**
1. Content-Type ответа — `text/event-stream`
2. Каждая строка начинается с `data: `
3. Последняя строка — `data: [DONE]`
4. Каждый промежуточный JSON парсится и содержит `choices[0].delta.content`

**Статус:** ⚠️ Код есть (`proxy/app/api/chat.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** ADR-004
